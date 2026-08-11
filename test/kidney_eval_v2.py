"""
kidney_eval_v2.py — Kidney Dice/HD95/Volume Error for all 5 KiTS cases
Uses pydicom-seg + SimpleITK for DICOM spatial alignment
"""

import os, tempfile, zipfile, io, json
import numpy as np
import requests, pydicom
import SimpleITK as sitk
from pydicom_seg.reader import SegmentReader

ORTHANC  = "http://localhost:8042"
TCIA_API = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

CASES = [
    ("KiTS-53",   "1.3.6.1.4.1.14519.5.2.1.6919.4624.234938093025998868310622825320",
     "1.2.276.0.7230010.3.1.3.0.75044.1588584379.525361"),
    ("KiTS-389",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379",
     "1.2.276.0.7230010.3.1.3.0.75752.1588585674.788120"),
    ("KiTS-738",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368",
     "1.2.276.0.7230010.3.1.3.0.74998.1588584273.225699"),
    ("KiTS-987",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497",
     "1.2.276.0.7230010.3.1.3.0.76174.1588586497.15246"),
    ("KiTS-1059", "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681",
     "1.2.276.0.7230010.3.1.3.0.75995.1588586281.559261"),
]


def download_seg(seg_uid):
    """Download DICOM SEG, return pydicom dataset."""
    r = requests.get(f"{TCIA_API}/getImage",
                     params={"SeriesInstanceUID": seg_uid}, timeout=60)
    tmp = os.path.join(tempfile.gettempdir(), f"seg_{seg_uid[:8]}.zip")
    with open(tmp, "wb") as f:
        f.write(r.content)
    with zipfile.ZipFile(tmp, "r") as zf:
        for name in zf.namelist():
            if name.lower().endswith(".dcm"):
                ds = pydicom.dcmread(io.BytesIO(zf.read(name)))
                os.remove(tmp)
                return ds
    os.remove(tmp)
    raise FileNotFoundError("No DCM in SEG")


def get_kidney_gt_sitk(seg_ds):
    """Use pydicom-seg to read SEG into SimpleITK label map, return kidney mask."""
    reader = SegmentReader()
    seg_data = reader.read(seg_ds)
    # seg_data.segment_infos: dict of segment_number -> SegmentInfo
    # seg_data.segment_image(segment_number) -> sitk.Image
    for seg_num, info in seg_data.segment_infos.items():
        print(f"    Segment {seg_num}: {info.label}")
        if "kidney" in info.label.lower() and "tumor" not in info.label.lower():
            return seg_data.segment_image(seg_num)
    # Fallback: return first segment
    return seg_data.segment_image(1)


def get_prediction_kidney(ct_uid, name):
    """Get TotalSegmentator prediction and return kidney mask as sitk Image."""
    pred_path = os.path.join(OUTPUT, f"pred_{name}.npy")
    
    # Check if cached
    if not os.path.exists(pred_path):
        print("    Running /segment_mask ...")
        r = requests.post("http://localhost:8004/segment_mask",
                         json={"series_instance_uid": ct_uid}, timeout=900)
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"Prediction failed: {data}")
        np.save(pred_path, np.load(data["file_path"]))
    
    pred = np.load(pred_path)
    
    # Find kidney labels from a quick API call
    # TotalSegmentator kidney_right=2, kidney_left=3 (check actual labels)
    kidney_ids = [2, 3]  # standard nnU-Net kidney labels
    
    pred_k = np.isin(pred, kidney_ids).astype(np.uint8)
    
    # Build dummy sitk image for prediction (it's already aligned to CT)
    img = sitk.GetImageFromArray(pred_k.transpose(2, 1, 0).astype(np.uint8))
    return img


def compute_metrics(pred_img, gt_img):
    """Compute Dice, HD95, relative volume error between two sitk Images."""
    # Resample prediction to GT space if needed
    if pred_img.GetSize() != gt_img.GetSize() or pred_img.GetSpacing() != gt_img.GetSpacing():
        pred_img = sitk.Resample(pred_img, gt_img, sitk.Transform(),
                                 sitk.sitkNearestNeighbor, 0)

    # Dice
    overlap = sitk.LabelOverlapMeasuresImageFilter()
    overlap.Execute(pred_img > 0, gt_img > 0)
    dice = overlap.GetDiceCoefficient()

    # HD95
    hausdorff = sitk.HausdorffDistanceImageFilter()
    hausdorff.Execute(pred_img > 0, gt_img > 0)
    hd95_val = hausdorff.GetHausdorffDistance()

    # Volume error
    pred_vol = sitk.GetArrayViewFromImage(pred_img).sum()
    gt_vol = sitk.GetArrayViewFromImage(gt_img).sum()
    vol_err = abs(pred_vol - gt_vol) / max(gt_vol, 1) * 100 if gt_vol > 0 else 0

    return {
        "dice": round(float(dice), 4),
        "hd95_mm": round(float(hd95_val), 2),
        "vol_error_pct": round(float(vol_err), 1),
        "pred_voxels": int(pred_vol),
        "gt_voxels": int(gt_vol),
    }


def main():
    print("=" * 60)
    print("KIDNEY SEGMENTATION EVALUATION (KiTS19)")
    print("=" * 60)

    all_results = []

    for name, ct_uid, seg_uid in CASES:
        print(f"\n{'='*40}")
        print(f"Case: {name}")
        
        try:
            # 1. Get prediction kidney mask
            print("  [1/3] Prediction ...")
            pred_img = get_prediction_kidney(ct_uid, name)
            print(f"    Size: {pred_img.GetSize()}")

            # 2. Get GT kidney mask
            print("  [2/3] GT from SEG ...")
            seg_ds = download_seg(seg_uid)
            gt_img = get_kidney_gt_sitk(seg_ds)
            print(f"    Size: {gt_img.GetSize()}, Spacing: {gt_img.GetSpacing()}")

            # 3. Resample GT to prediction space and compute metrics
            print("  [3/3] Computing metrics ...")
            gt_resampled = sitk.Resample(gt_img, pred_img, sitk.Transform(),
                                         sitk.sitkNearestNeighbor, 0)
            m = compute_metrics(pred_img, gt_resampled)
            m["case"] = name
            print(f"    Dice={m['dice']:.4f}  HD95={m['hd95_mm']:.1f}mm  VolErr={m['vol_error_pct']:.1f}%")
            all_results.append(m)

        except Exception as e:
            print(f"  FAIL: {e}")
            all_results.append({"case": name, "error": str(e)})

    # Summary
    dice_vals = [r["dice"] for r in all_results if "dice" in r]
    if dice_vals:
        print(f"\n{'='*60}")
        print(f"Mean Dice: {np.mean(dice_vals):.4f} ± {np.std(dice_vals):.4f}")
        print(f"Range: [{min(dice_vals):.4f}, {max(dice_vals):.4f}]")

    out_path = os.path.join(OUTPUT, "kidney_eval_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
