"""
dice_client.py — 调 /segment_mask 端点拿 label map，和 GT 算 Dice
Usage: python dice_client.py
"""

import requests, json, base64, io, numpy as np
from scipy.ndimage import zoom

TOTALSEG = "http://localhost:8004"
GT_PATH  = "c:/Users/Dell/Desktop/miscada-project-master/kits64_gt.npy"

# KiTS-53 (53 slices, matches GT)
UID = "1.3.6.1.4.1.14519.5.2.1.6919.4624.234938093025998868310622825320"


def dice(pred, gt):
    p = (pred > 0).astype(np.float64)
    g = (gt > 0).astype(np.float64)
    inter = (p * g).sum()
    denom = p.sum() + g.sum()
    return 2.0 * inter / denom if denom > 0 else 1.0


print("Calling /segment_mask ...")
r = requests.post(f"{TOTALSEG}/segment_mask",
                  json={"series_instance_uid": UID}, timeout=600)
if r.status_code != 200:
    print(f"ERROR: {r.status_code} {r.text[:200]}")
    exit(1)

data = r.json()
print(f"Pred shape: {data['shape']}")
print(f"Labels: {data['labels']}")
print(f"Names: {data['label_names']}")

# 解码 label map
buf = io.BytesIO(base64.b64decode(data["data_b64"]))
buf.seek(0)
pred = np.load(buf)
print(f"Loaded pred: {pred.shape}, dtype={pred.dtype}")

# 加载 GT
gt = np.load(GT_PATH)
print(f"GT shape: {gt.shape}, values={np.unique(gt)}")

# TotalSegmentator kidney labels: 通常 kidney_right=2, kidney_left=3
# 从 label_names 中找到 kidney 相关的
kidney_ids = []
tumor_ids = []
for lid, name in zip(data["labels"], data["label_names"]):
    nl = name.lower()
    if "kidney" in nl and "tumor" not in nl and "cyst" not in nl:
        kidney_ids.append(lid)
    if ("kidney" in nl and "tumor" in nl) or ("renal" in nl and "tumor" in nl):
        tumor_ids.append(lid)

print(f"Kidney label IDs: {kidney_ids}")
print(f"Tumor label IDs: {tumor_ids}")

# 构建 binary masks
kidney_pred = np.isin(pred, kidney_ids).astype(np.uint8)
tumor_pred = np.isin(pred, tumor_ids).astype(np.uint8)
kidney_gt = (gt == 1).astype(np.uint8)
tumor_gt = (gt == 2).astype(np.uint8)

# 重采样 (如果尺寸不同)
if kidney_pred.shape != kidney_gt.shape:
    z = [kidney_gt.shape[i] / kidney_pred.shape[i] for i in range(3)]
    print(f"Resampling: {kidney_pred.shape} -> {kidney_gt.shape} (z={[round(x,3) for x in z]})")
    kidney_pred = (zoom(kidney_pred.astype(float), z, order=0) > 0.5).astype(np.uint8)
    tumor_pred = (zoom(tumor_pred.astype(float), z, order=0) > 0.5).astype(np.uint8)

# Dice
kd = dice(kidney_pred, kidney_gt)
td = dice(tumor_pred, tumor_gt)

print()
print("=" * 50)
print(f"  Kidney Dice:  {kd:.4f}")
print(f"  Tumor Dice:   {td:.4f}")
print("=" * 50)

# 保存
result = {"kidney_dice": round(float(kd), 4), "tumor_dice": round(float(td), 4)}
with open("c:/Users/Dell/Desktop/miscada-project-master/experiment_results/dice_result.json", "w") as f:
    json.dump(result, f, indent=2)
print("\nSaved: experiment_results/dice_result.json")
