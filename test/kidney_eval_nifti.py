"""
kidney_eval_nifti.py — KiTS19 NIfTI GT + TotalSegmentator prediction
NIfTI自带空间信息，sitk.Resample自动对齐
"""

import os, json, numpy as np, requests, SimpleITK as sitk

ORTHANC  = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"
GT_DIR   = "c:/Users/Dell/Desktop/miscada-project-master/kits19_gt"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

# case_NNNNN on GitHub → our Orthanc CT UID
CASES = [
    ("00095", "KiTS-314", "1.3.6.1.4.1.14519.5.2.1.6919.4624.321986215317450174304381809203"),
    ("00123", "KiTS-389", "1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379"),
    ("00059", "KiTS-738", "1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368"),
    ("00156", "KiTS-987", "1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497"),
    ("00151", "KiTS-1059","1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681"),
]


def main():
    for case_id, name, ct_uid in CASES:
        print(f"\n{'='*40}")
        print(f"Case: {name} (case_{case_id})")

        # 1. Load GT (NIfTI - already spatially correct)
        gt_path = os.path.join(GT_DIR, f"case_{case_id}.nii.gz")
        gt_img = sitk.ReadImage(gt_path)
        gt_arr = sitk.GetArrayFromImage(gt_img)  # (z,y,x)
        # GT has 0=bg, 1=kidney, 2=tumor — keep only kidney
        gt_kidney = (gt_arr == 1).astype(np.uint8)
        print(f"  GT: {gt_kidney.shape}  kidney voxels={int(gt_kidney.sum())}")

        # 2. Get prediction
        pred_path = os.path.join(OUTPUT, f"pred_{name}.npy")
        labels_path = os.path.join(OUTPUT, f"labels_{name}.json")
        if not os.path.exists(pred_path):
            print("  Running /segment_mask ...")
            r = requests.post(f"{TOTALSEG}/segment_mask",
                            json={"series_instance_uid": ct_uid}, timeout=900)
            data = r.json()
            np.save(pred_path, np.load(data["file_path"]))
            with open(labels_path, "w") as f:
                json.dump({"labels": data["labels"], "label_names": data["label_names"]}, f)

        pred = np.load(pred_path)
        with open(labels_path) as f:
            lm = json.load(f)
        kid_ids = [l for l, n in zip(lm["labels"], lm["label_names"])
                   if "kidney" in n.lower() and "tumor" not in n.lower()]
        pred_k = np.isin(pred, kid_ids).astype(np.uint8)
        print(f"  Pred: {pred_k.shape}  kidney labels={kid_ids}  voxels={int(pred_k.sum())}")

        # 3. Resample to same grid
        if pred_k.shape != gt_kidney.shape:
            from scipy.ndimage import zoom
            if pred_k.shape[0] < gt_kidney.shape[0]:
                z = [pred_k.shape[i]/gt_kidney.shape[i] for i in range(3)]
                gt_kidney = (zoom(gt_kidney.astype(float), z, order=0) > 0.5).astype(np.uint8)
                print(f"  Downsampled GT: {gt_kidney.shape}")
            else:
                z = [gt_kidney.shape[i]/pred_k.shape[i] for i in range(3)]
                pred_k = (zoom(pred_k.astype(float), z, order=0) > 0.5).astype(np.uint8)
                print(f"  Upsampled pred: {pred_k.shape}")

        # 4. Dice
        inter = (pred_k & gt_kidney).sum()
        denom = pred_k.sum() + gt_kidney.sum()
        dice = 2 * inter / denom if denom > 0 else 0
        print(f"  Dice = {dice:.4f}")
        print(f"  Pred vol = {pred_k.sum():.0f} vox  GT vol = {gt_kidney.sum():.0f} vox")


if __name__ == "__main__":
    main()
