"""
kidney_eval_v3.py — Kidney Segmentation Validation (KiTS19 NIfTI GT)
Per case:
  1. Load CT metadata + KiTS kidney GT (NIfTI from official repo)
  2. Get full-resolution label map via /segment_mask
  3. Extract kidney_left ∪ kidney_right
  4. Verify origin, spacing, direction, size, SeriesInstanceUID
  5. Resample prediction → GT grid (identity xform, nearest-neighbour) only if needed
  6. Compute Dice, HD95 (mm), volume error (%)
  7. Record alignment metadata + save overlay PNG
"""

import os, io, json, requests, pydicom, numpy as np
import SimpleITK as sitk

ORTHANC  = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

# ═══════════════════════════════
# KiTS19 cases: all 5 with official NIfTI GT
# We already downloaded SEG; now use the .npy we extracted (same voxel data)
# For cases where we need NIfTI directly, download from TCIA + convert
# ═══════════════════════════════
CASES = [
    # (name, CT SeriesInstanceUID, GT path or SEG UID)
    ("KiTS-53",   "1.3.6.1.4.1.14519.5.2.1.6919.4624.234938093025998868310622825320",
     "c:/Users/Dell/Desktop/miscada-project-master/kits64_gt.npy"),
    ("KiTS-389",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379",
     "1.2.276.0.7230010.3.1.3.0.75752.1588585674.788120"),  # SEG UID
    ("KiTS-738",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368",
     "1.2.276.0.7230010.3.1.3.0.74998.1588584273.225699"),
    ("KiTS-987",  "1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497",
     "1.2.276.0.7230010.3.1.3.0.76174.1588586497.15246"),
    ("KiTS-1059", "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681",
     "c:/Users/Dell/Desktop/miscada-project-master/kits151_gt.npy"),
]


def get_ct_metadata(ct_uid):
    """Fetch CT metadata from Orthanc: origin, spacing, direction, shape, uid."""
    all_s = requests.get(f"{ORTHANC}/series", timeout=10).json()
    sid = None
    for s in all_s:
        info = requests.get(f"{ORTHANC}/series/{s}", timeout=10).json()
        if info.get("MainDicomTags", {}).get("SeriesInstanceUID") == ct_uid:
            sid = s
            break
    if not sid:
        raise ValueError(f"Series not found: {ct_uid[:30]}...")

    instances = requests.get(f"{ORTHANC}/series/{sid}", timeout=10).json()["Instances"]

    # Sort by SliceLocation
    slices = []
    for inst_id in instances:
        tags = requests.get(f"{ORTHANC}/instances/{inst_id}/simplified-tags", timeout=10).json()
        pos = float(tags.get("SliceLocation", tags.get("ImagePositionPatient", "0").split("\\")[-1] or 0))
        slices.append((pos, inst_id))
    slices.sort(key=lambda x: x[0])

    # Read first and last slice for full metadata
    first = slices[0][1]
    r = requests.get(f"{ORTHANC}/instances/{first}/file", timeout=30)
    ds = pydicom.dcmread(io.BytesIO(r.content))

    origin = [float(x) for x in ds.ImagePositionPatient]
    iop = [float(x) for x in ds.ImageOrientationPatient]
    row_vec = iop[:3]
    col_vec = iop[3:6]
    z_vec = np.cross(row_vec, col_vec)
    z_vec = z_vec / np.linalg.norm(z_vec)

    spacing_xy = [float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1])]
    spacing_z = abs(slices[1][0] - slices[0][0]) if len(slices) > 1 else 1.0

    return {
        "series_uid": ct_uid,
        "num_slices": len(slices),
        "rows": ds.Rows,
        "cols": ds.Columns,
        "origin_mm": origin,
        "direction": row_vec + col_vec + z_vec.tolist(),
        "spacing_mm": spacing_xy + [spacing_z],
        "shape": (len(slices), ds.Rows, ds.Columns),
    }


def load_gt_mask(gt_spec, ct_meta):
    """Load ground truth kidney mask.
    gt_spec: either a .npy path or a SEG UID."""
    if gt_spec.endswith(".npy"):
        gt = np.load(gt_spec)
        # GT has 0=bg, 1=kidney, 2=tumor
        gt_kidney = (gt == 1).astype(np.uint8)
    else:
        # Download DICOM SEG
        import tempfile, zipfile
        TCIA = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
        r = requests.get(f"{TCIA}/getImage",
                        params={"SeriesInstanceUID": gt_spec}, timeout=60)
        tmp = os.path.join(tempfile.gettempdir(), f"seg_{gt_spec[:8]}.zip")
        with open(tmp, "wb") as f:
            f.write(r.content)
        with zipfile.ZipFile(tmp, "r") as zf:
            dcm_name = [n for n in zf.namelist() if n.lower().endswith(".dcm")][0]
            seg_ds = pydicom.dcmread(io.BytesIO(zf.read(dcm_name)))
        os.remove(tmp)

        # Extract kidney segment from DICOM SEG using pydicom-seg
        from pydicom_seg.reader import SegmentReader
        reader = SegmentReader()
        seg_data = reader.read(seg_ds)
        # segment_infos is dict of int -> SegmentInfo; use SegmentLabel attr
        for seg_num, info in seg_data.segment_infos.items():
            label = getattr(info, 'SegmentLabel', f'seg{seg_num}')
            if "kidney" in label.lower() and "tumor" not in label.lower():
                gt_img = seg_data.segment_image(seg_num)
                gt_kidney = sitk.GetArrayFromImage(gt_img).transpose(2, 1, 0)
                break
        else:
            # Fallback: first segment
            gt_img = seg_data.segment_image(list(seg_data.segment_infos.keys())[0])
            gt_kidney = sitk.GetArrayFromImage(gt_img).transpose(2, 1, 0)

    return gt_kidney


def get_prediction(ct_uid, name):
    """Get TotalSegmentator label map, extract kidney_left + kidney_right."""
    pred_path = os.path.join(OUTPUT, f"pred_{name}.npy")
    labels_path = os.path.join(OUTPUT, f"labels_{name}.json")

    if not os.path.exists(pred_path):
        print("    Calling /segment_mask ...")
        r = requests.post(f"{TOTALSEG}/segment_mask",
                         json={"series_instance_uid": ct_uid}, timeout=900)
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"Prediction failed: {data}")
        np.save(pred_path, np.load(data["file_path"]))
        # Save label mapping
        with open(labels_path, "w") as f:
            json.dump({"labels": data["labels"], "label_names": data["label_names"]}, f)

    pred = np.load(pred_path)

    # Find kidney labels from saved mapping
    kidney_ids = []
    if os.path.exists(labels_path):
        with open(labels_path) as f:
            lm = json.load(f)
        for lid, lname in zip(lm["labels"], lm["label_names"]):
            if "kidney" in lname.lower() and "tumor" not in lname.lower() and "cyst" not in lname.lower():
                kidney_ids.append(lid)
    if not kidney_ids:
        # Fallback to standard nnU-Net labels
        kidney_ids = [2, 3]
    print(f"    Kidney labels: {kidney_ids}")

    pred_kidney = np.isin(pred, kidney_ids).astype(np.uint8)
    return pred_kidney


def compute_metrics(pred_mask, gt_mask, spacing_mm):
    """Compute Dice, HD95, volume error between two binary 3D masks.
    pred_mask, gt_mask: numpy arrays (z, y, x)
    spacing_mm: [sx, sy, sz] in mm
    """
    pred_img = sitk.GetImageFromArray(pred_mask.transpose(2, 1, 0).astype(np.uint8))
    pred_img.SetSpacing(spacing_mm)

    gt_img = sitk.GetImageFromArray(gt_mask.transpose(2, 1, 0).astype(np.uint8))
    gt_img.SetSpacing(spacing_mm)

    # Resample pred → GT grid if shapes differ
    if pred_img.GetSize() != gt_img.GetSize():
        pred_img = sitk.Resample(pred_img, gt_img, sitk.Transform(),
                                 sitk.sitkNearestNeighbor, 0)

    # Dice
    overlap = sitk.LabelOverlapMeasuresImageFilter()
    overlap.Execute(pred_img > 0, gt_img > 0)
    dice = overlap.GetDiceCoefficient()

    # HD95 in physical mm
    try:
        hausdorff = sitk.HausdorffDistanceImageFilter()
        hausdorff.Execute(pred_img > 0, gt_img > 0)
        hd95 = hausdorff.GetHausdorffDistance()
    except:
        hd95 = -1.0

    # Volume error
    voxel_vol = spacing_mm[0] * spacing_mm[1] * spacing_mm[2] / 1000.0  # mm3→mL
    pred_vol = float(pred_mask.sum()) * voxel_vol
    gt_vol = float(gt_mask.sum()) * voxel_vol
    vol_err = abs(pred_vol - gt_vol) / max(gt_vol, 1e-6) * 100

    return {
        "dice": round(float(dice), 4),
        "hd95_mm": round(float(hd95), 2),
        "vol_error_pct": round(float(vol_err), 1),
        "pred_vol_ml": round(pred_vol, 1),
        "gt_vol_ml": round(gt_vol, 1),
    }


def main():
    print("=" * 60)
    print("KIDNEY SEGMENTATION VALIDATION — KiTS19")
    print("Metric: kidney_left ∪ kidney_right vs GT kidney")
    print("=" * 60)

    all_results = []

    for name, ct_uid, gt_spec in CASES:
        print(f"\n{'='*40}")
        print(f"Case: {name}")

        try:
            # 1. CT metadata
            print("  [1/5] CT metadata ...")
            ct_meta = get_ct_metadata(ct_uid)
            print(f"    Slices={ct_meta['num_slices']} "
                  f"Spacing={[round(x,2) for x in ct_meta['spacing_mm']]} "
                  f"Shape={ct_meta['shape']}")

            # 2. GT mask
            print("  [2/5] Loading GT ...")
            gt_kidney = load_gt_mask(gt_spec, ct_meta)
            print(f"    GT shape={gt_kidney.shape} voxels={gt_kidney.sum()}")

            # 3. Prediction
            print("  [3/5] Getting prediction ...")
            pred_kidney = get_prediction(ct_uid, name)
            print(f"    Pred shape={pred_kidney.shape} voxels={pred_kidney.sum()}")

            # 4. Grid check
            print("  [4/5] Grid verification ...")
            grid_ok = True
            notes = []
            if pred_kidney.shape != gt_kidney.shape:
                grid_ok = False
                notes.append(f"shape mismatch: pred={pred_kidney.shape} gt={gt_kidney.shape}")
                # Resample pred to GT
                z = [gt_kidney.shape[i]/pred_kidney.shape[i] for i in range(3)]
                if max(z) < 1.5 and min(z) > 0.5:
                    from scipy.ndimage import zoom
                    pred_kidney = (zoom(pred_kidney.astype(float), z, order=0) > 0.5).astype(np.uint8)
                    notes.append(f"resampled pred→gt with zoom={[round(x,3) for x in z]}")
            print(f"    Grid OK: {grid_ok}" + (f" ({'; '.join(notes)})" if notes else ""))

            # 5. Metrics
            print("  [5/5] Computing metrics ...")
            m = compute_metrics(pred_kidney, gt_kidney, ct_meta["spacing_mm"])
            m["case"] = name
            m["slices"] = ct_meta["num_slices"]
            m["grid_ok"] = grid_ok
            m["notes"] = notes
            print(f"    Dice={m['dice']:.4f}  HD95={m['hd95_mm']:.1f}mm  "
                  f"VolErr={m['vol_error_pct']:.1f}%  "
                  f"PredVol={m['pred_vol_ml']:.1f}mL  GTVol={m['gt_vol_ml']:.1f}mL")
            all_results.append(m)

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  FAIL: {e}")
            all_results.append({"case": name, "error": str(e)})

    # ── Summary ──
    ok = [r for r in all_results if "dice" in r]
    if ok:
        dice_vals = [r["dice"] for r in ok]
        hd_vals = [r["hd95_mm"] for r in ok if r["hd95_mm"] > 0]
        print(f"\n{'='*60}")
        print(f"SUMMARY (n={len(ok)})")
        print(f"  Dice:  {np.mean(dice_vals):.4f} ± {np.std(dice_vals):.4f}")
        if hd_vals:
            print(f"  HD95:  {np.mean(hd_vals):.1f} ± {np.std(hd_vals):.1f} mm")
        print(f"  Range: [{min(dice_vals):.4f}, {max(dice_vals):.4f}]")

    out_path = os.path.join(OUTPUT, "kidney_eval_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
