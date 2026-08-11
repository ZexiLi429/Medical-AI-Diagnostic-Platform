"""
kidney_eval_zalign.py — SEG→CT alignment by matching Z coordinates
"""

import os, io, json, tempfile, zipfile, requests, pydicom, numpy as np
import SimpleITK as sitk
from pydicom_seg.reader import SegmentReader

ORTHANC  = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"
TCIA     = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

CASES = [
    ("KiTS-00095","1.3.6.1.4.1.14519.5.2.1.6919.4624.321986215317450174304381809203",
     "1.2.276.0.7230010.3.1.3.0.75397.1588585017.365820"),
    ("KiTS-389",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379",
     "1.2.276.0.7230010.3.1.3.0.75752.1588585674.788120"),
    ("KiTS-738",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368",
     "1.2.276.0.7230010.3.1.3.0.74998.1588584273.225699"),
    ("KiTS-987",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497",
     "1.2.276.0.7230010.3.1.3.0.76174.1588586497.15246"),
    ("KiTS-1059", "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681",
     "1.2.276.0.7230010.3.1.3.0.75995.1588586281.559261"),
]


def get_ct_slice_z(ct_uid):
    """Return sorted list of (z_position, instance_id) for CT series."""
    all_s = requests.get(f"{ORTHANC}/series", timeout=10).json()
    sid = None
    for s in all_s:
        info = requests.get(f"{ORTHANC}/series/{s}", timeout=10).json()
        if info.get("MainDicomTags",{}).get("SeriesInstanceUID") == ct_uid:
            sid = s; break
    instances = requests.get(f"{ORTHANC}/series/{sid}", timeout=10).json()["Instances"]
    slices = []
    for inst_id in instances:
        tags = requests.get(f"{ORTHANC}/instances/{inst_id}/simplified-tags", timeout=10).json()
        ipp = tags.get("ImagePositionPatient", "0\\0\\0")
        z = float(ipp.split("\\")[-1])
        slices.append((z, inst_id))
    slices.sort(key=lambda x: x[0])
    # Read first slice for spacing
    r = requests.get(f"{ORTHANC}/instances/{slices[0][1]}/file", timeout=30)
    ds = pydicom.dcmread(io.BytesIO(r.content))
    spacing = [float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1]),
               abs(slices[1][0] - slices[0][0]) if len(slices) > 1 else 1.0]
    z_positions = [s[0] for s in slices]
    return z_positions, spacing, len(slices)


def get_seg_frames_z(seg_ds):
    """Extract per-frame Z positions from DICOM SEG."""
    frames_z = []
    for frame in seg_ds.PerFrameFunctionalGroupsSequence:
        pps = frame.PlanePositionSequence[0]
        z = float(pps.ImagePositionPatient[2])
        frames_z.append(z)
    return frames_z


def load_seg_kidney_by_z(seg_uid, ct_z_positions, shape_xy):
    """Load SEG kidney mask, map frames to CT slices by nearest Z."""
    r = requests.get(f"{TCIA}/getImage",
                     params={"SeriesInstanceUID": seg_uid}, timeout=60)
    tmp = os.path.join(tempfile.gettempdir(), f"seg_{seg_uid[:8]}.zip")
    with open(tmp, "wb") as f: f.write(r.content)
    with zipfile.ZipFile(tmp, "r") as zf:
        dcm_name = [n for n in zf.namelist() if n.lower().endswith(".dcm")][0]
        seg_ds = pydicom.dcmread(io.BytesIO(zf.read(dcm_name)))
    os.remove(tmp)

    reader = SegmentReader()
    seg_data = reader.read(seg_ds)
    for seg_num, info in seg_data.segment_infos.items():
        label = getattr(info, 'SegmentLabel', str(seg_num))
        if "kidney" in label.lower() and "tumor" not in label.lower():
            gt_img = seg_data.segment_image(seg_num); break
    else:
        gt_img = seg_data.segment_image(list(seg_data.segment_infos.keys())[0])

    gt_arr = sitk.GetArrayFromImage(gt_img)  # (z, y, x)
    seg_z = get_seg_frames_z(seg_ds)

    # Build per-CT-slice kidney mask by matching nearest Z
    n_ct = len(ct_z_positions)
    kidney_mask = np.zeros((n_ct,) + shape_xy, dtype=np.uint8)

    for i, ct_z in enumerate(ct_z_positions):
        # Find nearest SEG frame
        if not seg_z:
            continue
        best_j = min(range(len(seg_z)), key=lambda j: abs(seg_z[j] - ct_z))
        if best_j < gt_arr.shape[0]:
            # Resample XY if needed
            seg_slice = gt_arr[best_j]
            if seg_slice.shape != shape_xy:
                from scipy.ndimage import zoom
                zx, zy = shape_xy[0]/seg_slice.shape[0], shape_xy[1]/seg_slice.shape[1]
                seg_slice = (zoom(seg_slice.astype(float), (zx, zy), order=0) > 0.5)
            kidney_mask[i] = seg_slice

    print(f"    SEG frames={len(seg_z)} CT slices={n_ct}  mapped={int(kidney_mask.sum())} voxels")
    return kidney_mask


def main():
    for name, ct_uid, seg_uid in CASES:
        print(f"\n{'='*40}")
        print(f"Case: {name}")
        try:
            # CT Z positions
            ct_z, spacing, n_slices = get_ct_slice_z(ct_uid)
            print(f"  CT: {n_slices} slices, Z=[{ct_z[0]:.1f}..{ct_z[-1]:.1f}]")

            # GT aligned by Z
            gt = load_seg_kidney_by_z(seg_uid, ct_z, (512, 512))
            print(f"  GT kidney: {int(gt.sum())} voxels")

            # Prediction
            pred_path = os.path.join(OUTPUT, f"pred_{name}.npy")
            labels_path = os.path.join(OUTPUT, f"labels_{name}.json")
            if not os.path.exists(pred_path):
                r = requests.post(f"{TOTALSEG}/segment_mask",
                                json={"series_instance_uid": ct_uid}, timeout=900)
                np.save(pred_path, np.load(r.json()["file_path"]))
                with open(labels_path, "w") as f:
                    json.dump({"labels": r.json()["labels"],
                              "label_names": r.json()["label_names"]}, f)
            pred = np.load(pred_path)
            with open(labels_path) as f:
                lm = json.load(f)
            kid_ids = [l for l,n in zip(lm["labels"],lm["label_names"])
                       if "kidney" in n.lower() and "tumor" not in n.lower()]
            pred_k = np.isin(pred, kid_ids).astype(np.uint8)

            # Match shapes
            if pred_k.shape != gt.shape:
                from scipy.ndimage import zoom
                if pred_k.shape[0] < gt.shape[0]:
                    z = [pred_k.shape[i]/gt.shape[i] for i in range(3)]
                    gt = (zoom(gt.astype(float), z, order=0) > 0.5).astype(np.uint8)
                else:
                    z = [gt.shape[i]/pred_k.shape[i] for i in range(3)]
                    pred_k = (zoom(pred_k.astype(float), z, order=0) > 0.5).astype(np.uint8)

            # Dice
            inter = (pred_k & gt).sum()
            denom = pred_k.sum() + gt.sum()
            dice = 2*inter/denom if denom > 0 else 0
            print(f"  Dice={dice:.4f}  PredVol={pred_k.sum():.0f}  GTVol={gt.sum():.0f}")

        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")

if __name__ == "__main__":
    main()
