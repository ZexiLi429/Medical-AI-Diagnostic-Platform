"""dice_1059_v2.py — 对齐 GT 和预测的坐标系"""
import numpy as np
from scipy.ndimage import zoom

pred = np.load("c:/Users/Dell/Desktop/miscada-project-master/experiment_results/pred_27a3a67f-4fc.npy")
gt = np.load("c:/Users/Dell/Desktop/miscada-project-master/kits151_gt.npy")

print(f"Pred: {pred.shape}, GT: {gt.shape}")

# GT 只有部分切片有标注，找出 GT 的有效切片范围
gt_has_label = (gt.max(axis=(1,2)) > 0)
gt_slices = np.where(gt_has_label)[0]
print(f"GT has labels on slices: {gt_slices[0]} ~ {gt_slices[-1]} ({len(gt_slices)} slices)")

# 裁剪到 GT 有效区域
z0, z1 = gt_slices[0], gt_slices[-1]+1
gt_crop = gt[z0:z1]
pred_crop = pred[z0:z1]

# GT kidney=1, mass=2  |  Pred kidney=2 (from label analysis)
gt_k = (gt_crop == 1).astype(np.float64)
gt_m = (gt_crop == 2).astype(np.float64)
pred_k = (pred_crop == 2).astype(np.float64)  # kidney

# 找 TotalSegmentator 的肿瘤标签
pred_labels = np.unique(pred_crop)
print(f"Pred labels in crop: {pred_labels}")

# 尝试几个可能的 tumor 标签
# TotalSegmentator class_map: kidney_tumor 通常是某个特定ID
# 常见: 没有直接的 kidney_tumor, 病灶检测用的是 liver_tumor, kidney_cyst 等
# 试试看哪些标签只在肾脏区域出现
for lid in pred_labels:
    if lid <= 1:
        continue
    vox = int((pred_crop == lid).sum())
    if vox > 100:
        overlap_with_gt_mass = int(((pred_crop == lid) & (gt_crop == 2)).sum())
        print(f"  Pred label {lid}: {vox} voxels, overlap with GT mass: {overlap_with_gt_mass}")

# Dice for kidney only (most reliable)
def dice(p, g):
    i = (p*g).sum()
    d = p.sum() + g.sum()
    return round(float(2*i/d if d>0 else 0), 4)

kd = dice(pred_k, gt_k)
print(f"\nKidney Dice (on GT slices): {kd}")

# 也试试简单的位移矫正：把 pred 沿各轴滑动几个像素找最大重叠
print("\nTrying shift correction ...")
best_dice = 0
best_shift = (0,0,0)
for dx in range(-5, 6, 2):
    for dy in range(-5, 6, 2):
        p_shifted = np.roll(pred_k, (0, dy, dx), axis=(0,1,2))
        d = dice(p_shifted, gt_k)
        if d > best_dice:
            best_dice = d
            best_shift = (0, dy, dx)
print(f"Best shift: {best_shift}, Dice: {best_dice:.4f}")
