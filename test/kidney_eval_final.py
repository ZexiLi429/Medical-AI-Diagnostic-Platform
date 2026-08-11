"""
kidney_eval_final.py — Kidney Dice/HD95/Volume Error (4 KiTS19 arterial cases)
Spatial alignment via pydicom-seg + SimpleITK resampling
"""

import os, io, json, tempfile, zipfile
import numpy as np
import requests, pydicom
import SimpleITK as sitk
from pydicom_seg.reader import SegmentReader

ORTHANC  = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"
TCIA     = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

# 5 KiTS19 arterial cases with kidney GT
CASES = [
    ("KiTS-00095", "1.3.6.1.4.1.14519.5.2.1.6919.4624.321986215317450174304381809203",
     "1.2.276.0.7230010.3.1.3.0.75397.1588585017.365820"),
    ("KiTS-389",   "1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379",
     "1.2.276.0.7230010.3.1.3.0.75752.1588585674.788120"),
    ("KiTS-738",   "1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368",
     "1.2.276.0.7230010.3.1.3.0.74998.1588584273.225699"),
    ("KiTS-987",   "1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497",
     "1.2.276.0.7230010.3.1.3.0.76174.1588586497.15246"),
    ("KiTS-1059",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681",
     "1.2.276.0.7230010.3.1.3.0.75995.1588586281.559261"),
]


def get_ct_image(ct_uid):
    """Build SimpleITK CT image from Orthanc series."""
    all_s = requests.get(f"{ORTHANC}/series", timeout=10).json()
    sid = None
    for s in all_s:
        info = requests.get(f"{ORTHANC}/series/{s}", timeout=10).json()
        if info.get("MainDicomTags", {}).get("SeriesInstanceUID") == ct_uid:
            sid = s; break
    if not sid:
        raise ValueError("Series not found")

    instances = requests.get(f"{ORTHANC}/series/{sid}", timeout=10).json()["Instances"]
    slices = []
    for inst_id in instances:
        tags = requests.get(f"{ORTHANC}/instances/{inst_id}/simplified-tags", timeout=10).json()
        pos = float(tags.get("SliceLocation",
                   tags.get("ImagePositionPatient", "0").split("\\")[-1] or 0))
        slices.append((pos, inst_id))
    slices.sort(key=lambda x: x[0])

    arrays, origin, spacing, direction = [], None, None, None
    for _, inst_id in slices:
        r = requests.get(f"{ORTHANC}/instances/{inst_id}/file", timeout=30)
        ds = pydicom.dcmread(io.BytesIO(r.content))
        arrays.append(ds.pixel_array.astype(np.int16))
        if origin is None:
            origin = [float(x) for x in ds.ImagePositionPatient]
            iop = [float(x) for x in ds.ImageOrientationPatient]
            spacing = [float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1]),
                       abs(slices[1][0] - slices[0][0]) if len(slices) > 1 else 1.0]
            z_vec = list(np.cross(iop[:3], iop[3:6]))
            direction = iop[:3] + iop[3:6] + z_vec

    vol = np.stack(arrays, axis=0)
    img = sitk.GetImageFromArray(vol.transpose(2, 1, 0).astype(np.int16))
    img.SetOrigin(origin)
    img.SetSpacing(spacing)
    img.SetDirection(direction)
    return img, {"shape": vol.shape, "spacing": spacing, "origin": origin,
                 "direction": direction, "slices": len(slices)}


def get_gt_kidney(seg_uid, num_ct_slices):
    """Download DICOM SEG, extract kidney as (z,y,x) numpy aligned to CT."""
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

    # Find kidney segment
    for seg_num, info in seg_data.segment_infos.items():
        label = getattr(info, 'SegmentLabel', str(seg_num))
        if "kidney" in label.lower() and "tumor" not in label.lower():
            gt_img = seg_data.segment_image(seg_num)
            break
    else:
        gt_img = seg_data.segment_image(list(seg_data.segment_infos.keys())[0])

    # Convert ITK (x,y,z) → numpy (z,y,x), ensure matches CT slice count
    gt_arr = sitk.GetArrayFromImage(gt_img)  # (z, y, x)

    # If SEG has fewer frames than CT slices, pad; if more, truncate
    if gt_arr.shape[0] < num_ct_slices:
        padded = np.zeros((num_ct_slices,) + gt_arr.shape[1:], dtype=np.uint8)
        padded[:gt_arr.shape[0]] = gt_arr
        gt_arr = padded
    elif gt_arr.shape[0] > num_ct_slices:
        gt_arr = gt_arr[:num_ct_slices]

    print(f"    GT shape={gt_arr.shape} (aligned to CT), kidney voxels={int(gt_arr.sum())}")
    return gt_arr


def get_pred_kidney(ct_uid, name):
    """Get TotalSegmentator prediction, extract kidney mask as numpy (z,y,x)."""
    pred_path = os.path.join(OUTPUT, f"pred_{name}.npy")
    labels_path = os.path.join(OUTPUT, f"labels_{name}.json")

    if not os.path.exists(pred_path):
        print("    Running /segment_mask ...")
        r = requests.post(f"{TOTALSEG}/segment_mask",
                         json={"series_instance_uid": ct_uid}, timeout=900)
        data = r.json()
        np.save(pred_path, np.load(data["file_path"]))
        with open(labels_path, "w") as f:
            json.dump({"labels": data["labels"], "label_names": data["label_names"]}, f)

    pred = np.load(pred_path)
    with open(labels_path) as f:
        lm = json.load(f)
    kidney_ids = [lid for lid, lname in zip(lm["labels"], lm["label_names"])
                  if "kidney" in lname.lower() and "tumor" not in lname.lower()
                  and "cyst" not in lname.lower()]
    print(f"    Kidney labels: {kidney_ids}")

    pred_kidney = np.isin(pred, kidney_ids).astype(np.uint8)
    return pred_kidney


def compute_metrics_numpy(pred_mask, gt_mask, spacing_mm):
    """Dice, HD95, volume error. Both masks are numpy (z,y,x)."""
    # Dice
    inter = (pred_mask & gt_mask).sum()
    denom = pred_mask.sum() + gt_mask.sum()
    dice = 2 * inter / denom if denom > 0 else 0.0

    # HD95 via SimpleITK
    pred_img = sitk.GetImageFromArray(pred_mask.transpose(2,1,0).astype(np.uint8))
    gt_img = sitk.GetImageFromArray(gt_mask.transpose(2,1,0).astype(np.uint8))
    pred_img.SetSpacing(spacing_mm)
    gt_img.SetSpacing(spacing_mm)
    try:
        hd = sitk.HausdorffDistanceImageFilter()
        hd.Execute(pred_img > 0, gt_img > 0)
        hd95 = hd.GetHausdorffDistance()
    except:
        hd95 = -1.0

    # Volume
    voxel_vol = spacing_mm[0] * spacing_mm[1] * spacing_mm[2] / 1000.0
    pred_ml = pred_mask.sum() * voxel_vol
    gt_ml = gt_mask.sum() * voxel_vol
    vol_err = abs(pred_ml - gt_ml) / max(gt_ml, 1e-6) * 100

    return {
        "dice": round(float(dice), 4),
        "hd95_mm": round(float(hd95), 2),
        "vol_error_pct": round(float(vol_err), 1),
        "pred_ml": round(pred_ml, 1),
        "gt_ml": round(gt_ml, 1),
    }


def main():
    print("=" * 60)
    print("KIDNEY DICE/HD95/VOL ERROR — KiTS19 (5 cases)")
    print("=" * 60)

    results = []
    for name, ct_uid, seg_uid in CASES:
        print(f"\n{'='*40}")
        print(f"Case: {name}")
        try:
            # 1. CT metadata
            print("  [1/4] CT metadata ...")
            ct_img, ct_meta = get_ct_image(ct_uid)
            print(f"    Slices={ct_meta['slices']} "
                  f"Spacing={[round(x,2) for x in ct_meta['spacing']]}")

            # 2. GT kidney from SEG (numpy, aligned by frame index)
            print("  [2/4] Loading GT (DICOM SEG, frame-aligned) ...")
            gt_kidney = get_gt_kidney(seg_uid, ct_meta["slices"])

            # 3. Prediction (numpy)
            print("  [3/4] Getting prediction ...")
            pred_kidney = get_pred_kidney(ct_uid, name)

            # 4. Match shapes: downsample GT to pred resolution
            print("  [4/4] Computing metrics ...")
            spacing = list(ct_meta["spacing"])  # copy
            if pred_kidney.shape != gt_kidney.shape:
                from scipy.ndimage import zoom
                print(f"    Shape mismatch: pred={pred_kidney.shape} gt={gt_kidney.shape}")
                if pred_kidney.shape[0] < gt_kidney.shape[0]:
                    z = [pred_kidney.shape[i]/gt_kidney.shape[i] for i in range(3)]
                    print(f"    Downsampling GT -> pred (z={[round(x,3) for x in z]})")
                    gt_kidney = (zoom(gt_kidney.astype(float), z, order=0) > 0.5).astype(np.uint8)
                    # Adjust Z-spacing for downsampled grid
                    spacing[2] = ct_meta["spacing"][2] / z[0]
                else:
                    z = [gt_kidney.shape[i]/pred_kidney.shape[i] for i in range(3)]
                    print(f"    Upsampling pred -> GT")
                    pred_kidney = (zoom(pred_kidney.astype(float), z, order=0) > 0.5).astype(np.uint8)

            m = compute_metrics_numpy(pred_kidney, gt_kidney, spacing)
            m["case"] = name
            m["slices"] = ct_meta["slices"]
            print(f"    Dice={m['dice']:.4f}  HD95={m['hd95_mm']:.1f}mm  "
                  f"VolErr={m['vol_error_pct']:.1f}%  "
                  f"Pred={m['pred_ml']:.1f}mL  GT={m['gt_ml']:.1f}mL")
            results.append(m)

        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")
            results.append({"case": name, "error": str(e)})

    # Summary
    ok = [r for r in results if "dice" in r]
    if ok:
        dice_vals = [r["dice"] for r in ok]
        print(f"\n{'='*60}")
        print(f"SUMMARY (n={len(ok)})")
        print(f"  Dice:  {np.mean(dice_vals):.4f} +- {np.std(dice_vals):.4f}")
        print(f"  Range: [{min(dice_vals):.4f}, {max(dice_vals):.4f}]")

    out_path = os.path.join(OUTPUT, "kidney_eval_final.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
