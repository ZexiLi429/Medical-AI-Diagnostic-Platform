"""
kits_nifti_dice.py — TotalSegmentator on KiTS NIfTI imaging vs GT segmentation
Both in same NIfTI coordinate system — guaranteed alignment
"""
import requests, json, numpy as np, nibabel as nib, os

TOTALSEG = "http://localhost:8004"
GT_DIR   = "c:/Users/Dell/Desktop/miscada-project-master/kits19_gt"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

# Cases we have imaging.nii.gz for
# Auto-discover all cases with both imaging and segmentation
import glob
CASES = []
for img_path in sorted(glob.glob(os.path.join(GT_DIR, "*_imaging.nii.gz"))):
    case_id = os.path.basename(img_path).replace("case_", "").replace("_imaging.nii.gz", "")
    seg_path = os.path.join(GT_DIR, f"case_{case_id}.nii.gz")
    if os.path.exists(seg_path):
        CASES.append((case_id, f"case_{case_id}"))

for case_id, name in CASES:
    nii_path = os.path.join(GT_DIR, f"{name}_imaging.nii.gz")
    seg_path = os.path.join(GT_DIR, f"{name}.nii.gz")

    print(f"\n=== {name} ===")

    # 1. Call /segment_file
    print("  Running TotalSegmentator on NIfTI ...")
    r = requests.post(f"{TOTALSEG}/segment_file",
                     json={"nifti_path": nii_path}, timeout=900)
    data = r.json()
    pred_path = data["file_path"]
    pred = np.load(pred_path)
    print(f"  Pred: {pred.shape} labels={data['labels']}")

    # 2. Load GT
    gt_nii = nib.load(seg_path)
    gt = gt_nii.get_fdata().astype(np.uint8)
    print(f"  GT: {gt.shape}")

    # 3. Match shapes (TS may downsample)
    if pred.shape != gt.shape:
        from scipy.ndimage import zoom
        if pred.shape[0] < gt.shape[0]:
            z = [pred.shape[i]/gt.shape[i] for i in range(3)]
            print(f"  Downsampling GT: {gt.shape} -> {[int(s*z[i]) for i,s in enumerate(gt.shape)]}")
            gt_k = (zoom((gt==1).astype(float), z, order=0) > 0.5).astype(np.uint8)
            gt_t = (zoom((gt==2).astype(float), z, order=0) > 0.5).astype(np.uint8)
        else:
            z = [gt.shape[i]/pred.shape[i] for i in range(3)]
            pred = (zoom(pred.astype(float), z, order=0) > 0.5).astype(pred.dtype)
            gt_k = (gt == 1).astype(np.uint8)
            gt_t = (gt == 2).astype(np.uint8)
    else:
        gt_k = (gt == 1).astype(np.uint8)
        gt_t = (gt == 2).astype(np.uint8)

    # 4. Find kidney labels in prediction
    kid_ids = [l for l, n in zip(data["labels"], data["label_names"])
               if "kidney" in n.lower() and "tumor" not in n.lower()]
    pred_k = np.isin(pred, kid_ids).astype(np.uint8)
    print(f"  Kidney labels: {kid_ids}")

    # 5. Dice
    def dice(p, g):
        i = (p & g).sum()
        d = p.sum() + g.sum()
        return round(2*i/d, 4) if d > 0 else 0

    kd = dice(pred_k, gt_k)
    print(f"\n  Kidney Dice: {kd}")
    print(f"  GT kidney voxels: {gt_k.sum()}, Pred kidney: {pred_k.sum()}")

    # Save
    with open(os.path.join(OUTPUT, f"dice_{name}.json"), "w") as f:
        json.dump({"case": name, "dice": kd, "gt_vox": int(gt_k.sum()), "pred_vox": int(pred_k.sum())}, f)

# Summary
print("\n" + "=" * 60)
print("RANKED RESULTS")
import glob as _g
all_dice = []
for f in sorted(_g.glob(os.path.join(OUTPUT, "dice_case_*.json"))):
    with open(f) as _f:
        d = json.load(_f)
        all_dice.append((d["case"], d["dice"]))
all_dice.sort(key=lambda x: -x[1])
for name, d in all_dice:
    print(f"  {name}: Dice={d:.4f}")
if all_dice:
    good = [d for _, d in all_dice if d > 0.5]
    if good:
        print(f"\n  Dice > 0.5: {len(good)} cases, mean={np.mean(good):.4f}")
