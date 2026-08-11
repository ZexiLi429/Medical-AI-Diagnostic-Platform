"""measure_alignment.py — Auto landmark alignment verification"""
import requests, json, numpy as np

uid = '1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379'

# 1. Get CT metadata from Orthanc
all_s = requests.get('http://localhost:8042/series', timeout=10).json()
sid = None
for s in all_s:
    info = requests.get(f'http://localhost:8042/series/{s}', timeout=10).json()
    if info.get('MainDicomTags', {}).get('SeriesInstanceUID') == uid:
        sid = s; break

instances = requests.get(f'http://localhost:8042/series/{sid}', timeout=10).json()['Instances']
slices = []
for inst_id in instances:
    tags = requests.get(f'http://localhost:8042/instances/{inst_id}/simplified-tags', timeout=10).json()
    ipp = tags.get('ImagePositionPatient', '0\\0\\0')
    z = float(ipp.split('\\')[-1])
    slices.append((z, inst_id))
slices.sort(key=lambda x: x[0])

# First slice info
tags0 = requests.get(f'http://localhost:8042/instances/{slices[0][1]}/simplified-tags', timeout=10).json()
ipp0 = [float(x) for x in tags0.get('ImagePositionPatient', '0\\0\\0').split('\\')]
spacing_z = abs(slices[1][0] - slices[0][0]) if len(slices) > 1 else 1.0

import pydicom, io
r0 = requests.get(f'http://localhost:8042/instances/{slices[0][1]}/file', timeout=30)
ds = pydicom.dcmread(io.BytesIO(r0.content))
sp_xy = [float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1])]
rows, cols = ds.Rows, ds.Columns
n_slices = len(slices)

# DICOM origin (ImagePositionPatient of first slice)
dicom_origin = np.array(ipp0)

# CT physical bounds in DICOM world coords
ct_min = dicom_origin
ct_max = np.array([
    ipp0[0] + cols * sp_xy[0],
    ipp0[1] + rows * sp_xy[1],
    ipp0[2] + n_slices * spacing_z
])
print(f"CT bounds (DICOM world): X=[{ct_min[0]:.1f},{ct_max[0]:.1f}] Y=[{ct_min[1]:.1f},{ct_max[1]:.1f}] Z=[{ct_min[2]:.1f},{ct_max[2]:.1f}]")
print(f"DICOM origin (ImagePositionPatient): {dicom_origin}")

# 2. Get mesh data from TotalSegmentator
r = requests.post('http://localhost:8004/segment_3d',
                  json={'series_instance_uid': uid}, timeout=300)
data = r.json()

# 3. Convert mesh vertices from image-local to DICOM world coords
#    TS returns mesh in "image physical space" (voxel_index * spacing),
#    not DICOM patient coords. Add ImagePositionPatient to align.
img_origin = np.array(data.get('origin', dicom_origin))  # TS-reported origin

# === Organ grouping for thesis ===
VISCERAL = {'liver', 'kidney_right', 'kidney_left', 'spleen', 'pancreas',
            'stomach', 'adrenal_gland_left', 'adrenal_gland_right',
            'lung_upper_lobe_left', 'lung_lower_lobe_left',
            'lung_upper_lobe_right', 'lung_lower_lobe_right', 'heart'}
BONE = {'vertebrae_L3', 'vertebrae_L4', 'vertebrae_L5',
        'rib_left_6', 'rib_left_7', 'rib_left_8', 'rib_left_9',
        'rib_left_10', 'rib_left_11', 'rib_left_12',
        'rib_right_6', 'rib_right_7', 'rib_right_8', 'rib_right_9',
        'rib_right_10', 'rib_right_11', 'rib_right_12',
        'femur_left', 'femur_right', 'hip_left', 'hip_right'}
VASCULAR = {'aorta', 'iliac_artery_left', 'iliac_artery_right',
            'inferior_vena_cava', 'spermatic_cord'}

def classify_organ(name):
    if name in VISCERAL: return 'visceral'
    if name in BONE: return 'bone'
    return 'other'

# 4. Per-structure deviation statistics
def deviation_distances(verts_world, ct_min, ct_max):
    """Return array of deviation distances (0 = inside, >0 = outside)"""
    d = np.zeros(len(verts_world))
    for dim in range(3):
        below = np.maximum(0, ct_min[dim] - verts_world[:, dim])
        above = np.maximum(0, verts_world[:, dim] - ct_max[dim])
        d += (below + above) ** 2
    return np.sqrt(d)

print("\n" + "="*100)
print(f"{'Structure':<25s} {'Outside':>8s} {'Total':>8s} {'Rate%':>8s}  {'Mean':>8s} {'Median':>8s} {'P95':>8s} {'Max':>8s}  Group")
print("="*100)

all_deviations = []
group_stats = {'visceral': {'outside': 0, 'total': 0, 'devs': []},
               'bone': {'outside': 0, 'total': 0, 'devs': []},
               'other': {'outside': 0, 'total': 0, 'devs': []}}

structure_rows = []

for m in data.get('meshes', []):
    verts = np.array(m['vertices'])
    verts_world = verts + img_origin
    n_total = len(verts_world)

    devs = deviation_distances(verts_world, ct_min, ct_max)
    n_outside = int((devs > 0).sum())
    rate = 100.0 * n_outside / n_total if n_total > 0 else 0

    mean_d = devs.mean()
    median_d = np.median(devs)
    p95_d = np.percentile(devs, 95)
    max_d = devs.max()

    grp = classify_organ(m['name'])
    group_stats[grp]['outside'] += n_outside
    group_stats[grp]['total'] += n_total
    group_stats[grp]['devs'].extend(devs.tolist())

    all_deviations.extend(devs.tolist())

    structure_rows.append((m['name'], n_outside, n_total, rate, mean_d, median_d, p95_d, max_d, grp))

# Sort by outside rate descending
structure_rows.sort(key=lambda r: -r[3])

for (name, n_out, n_tot, rate, mean_d, med_d, p95_d, max_d, grp) in structure_rows:
    print(f"{name:<25s} {n_out:>8d} {n_tot:>8d} {rate:>7.1f}% {mean_d:>8.2f} {med_d:>8.2f} {p95_d:>8.2f} {max_d:>8.2f}  {grp}")

# 5. Group summaries
print("\n" + "-"*100)
print(f"{'GROUP SUMMARY':<25s} {'Outside':>8s} {'Total':>8s} {'Rate%':>8s}  {'Mean':>8s} {'Median':>8s} {'P95':>8s} {'Max':>8s}")
print("-"*100)

total_out = sum(g['outside'] for g in group_stats.values())
total_vert = sum(g['total'] for g in group_stats.values())

for grp_name in ['visceral', 'bone', 'other']:
    g = group_stats[grp_name]
    if g['total'] == 0:
        continue
    devs_arr = np.array(g['devs'])
    rate = 100.0 * g['outside'] / g['total']
    print(f"{grp_name:<25s} {g['outside']:>8d} {g['total']:>8d} {rate:>7.1f}% {devs_arr.mean():>8.2f} {np.median(devs_arr):>8.2f} {np.percentile(devs_arr,95):>8.2f} {devs_arr.max():>8.2f}")

# 6. Overall
all_devs = np.array(all_deviations)
overall_rate = 100.0 * total_out / total_vert if total_vert > 0 else 0
print("-"*100)
print(f"{'OVERALL':<25s} {total_out:>8d} {total_vert:>8d} {overall_rate:>7.1f}% {all_devs.mean():>8.2f} {np.median(all_devs):>8.2f} {np.percentile(all_devs,95):>8.2f} {all_devs.max():>8.2f}")

# 7. Origin delta
print("\n" + "="*70)
print("ORIGIN VERIFICATION")
print("="*70)
print(f"  TS reported origin:     {img_origin}")
print(f"  DICOM IPP (first slice): {dicom_origin}")
print(f"  Origin delta: {np.linalg.norm(img_origin - dicom_origin):.4f} mm")
print("="*70)
