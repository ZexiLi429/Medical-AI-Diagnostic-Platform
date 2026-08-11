"""KiTS-00064: TotalSegmentator vs Ground Truth Dice 计算"""
import numpy as np
import requests
import os

# 1. Ground truth
gt = np.load(r'c:\Users\Dell\Desktop\miscada-project-master\kits64_gt.npy')
gt_kidney = (gt == 1).astype(np.uint8)
gt_tumor = (gt == 2).astype(np.uint8)
gt_all = (gt > 0).astype(np.uint8)

print(f'GT shape: {gt.shape} (53 slices)')
print(f'  Kidney: {gt_kidney.sum():,} voxels')
print(f'  Tumor:  {gt_tumor.sum():,} voxels')

# 2. TotalSegmentator
uid = '1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681'
resp = requests.post('http://localhost:8004/segment', json={
    'series_instance_uid': uid,
}, timeout=60)
data = resp.json()
organs = data.get('organs', [])
shape = data.get('shape', [])

print(f'\nTotalSeg shape: {shape}')
kidney_organs = [o for o in organs if 'kidney' in o['name']]
for ko in kidney_organs:
    print(f'  {ko["name"]}: {ko["volume_cm3"]:.1f} cm3, {ko["voxels"]:,} voxels')

# 3. 体积对比 (GT 没有 spacing，但可以估算)
# GT: 53 slices, TotalSeg: 1059 slices
# KiTS 的体素间距通常 ~0.8mm in-plane, 1-3mm between slices
# TotalSeg 已给出了 volume_cm3（基于 DICOM spacing 计算）

total_ts_vol = sum(o['volume_cm3'] for o in kidney_organs)
total_ts_vox = sum(o['voxels'] for o in kidney_organs)

print(f'\n=== Summary ===')
print(f'GT kidney+tumor voxels: {gt_all.sum():,}')
print(f'TotalSeg kidney voxels: {total_ts_vox:,}')
print(f'TotalSeg kidney volume: {total_ts_vol:.1f} cm3')
print(f'\nNote: GT is 53 slices (one phase), TotalSeg is 1059 slices (multi-phase).')
print(f'Dice cannot be directly computed without slice-matching.')
