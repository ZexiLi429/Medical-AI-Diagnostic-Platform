"""
dice_eval.py — 分割准确率评估 (Dice Score)
比较 TotalSegmentator 预测 vs KiTS ground truth

依赖: totalseg_service.py 的推理函数
Usage: python dice_eval.py
"""

import os, sys, time, json
import numpy as np
import nibabel as nib
import requests
import pydicom
from io import BytesIO
from scipy.ndimage import zoom

# ═══════════════════════════════
# CONFIG
# ═══════════════════════════════
ORTHANC = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"
GT_PATH = "c:/Users/Dell/Desktop/miscada-project-master/kits64_gt.npy"

# KiTS-53 (late phase, 53 slices - matches GT)
SERIES_UID = "1.3.6.1.4.1.14519.5.2.1.6919.4624.234938093025998868310622825320"


def log(msg):
    print(f"[DICE] {msg}")


def fetch_dicom_volume(series_uid):
    """从 Orthanc 拉取整个 DICOM 序列，堆叠成 3D volume"""
    log("Fetching DICOM from Orthanc ...")
    r = requests.get(f"{ORTHANC}/series", timeout=10)
    all_series = r.json()

    # 找到匹配 series
    series_id = None
    for sid in all_series:
        s = requests.get(f"{ORTHANC}/series/{sid}", timeout=10).json()
        if s.get("MainDicomTags", {}).get("SeriesInstanceUID") == series_uid:
            series_id = sid
            break

    if not series_id:
        raise ValueError(f"Series {series_uid} not found in Orthanc")

    # 获取所有 instance
    s_info = requests.get(f"{ORTHANC}/series/{series_id}", timeout=10).json()
    instances = s_info["Instances"]
    log(f"  Found {len(instances)} slices")

    # 按 Z 坐标排序
    slices_info = []
    for inst_id in instances:
        i = requests.get(f"{ORTHANC}/instances/{inst_id}/simplified-tags", timeout=10).json()
        pos = float(i.get("SliceLocation", i.get("ImagePositionPatient", "0").split("\\")[-1] or 0))
        slices_info.append((pos, inst_id))

    slices_info.sort(key=lambda x: x[0])

    # 读取所有切片
    volume_slices = []
    spacing = None
    for _, inst_id in slices_info:
        r = requests.get(f"{ORTHANC}/instances/{inst_id}/file", timeout=30)
        ds = pydicom.dcmread(BytesIO(r.content))
        volume_slices.append(ds.pixel_array.astype(np.float32))
        if spacing is None:
            spacing = [
                float(ds.PixelSpacing[0]),
                float(ds.PixelSpacing[1]),
                abs(slices_info[1][0] - slices_info[0][0]) if len(slices_info) > 1 else 1.0
            ]

    volume = np.stack(volume_slices, axis=0)
    log(f"  Volume shape: {volume.shape}, spacing: {spacing}")
    return volume, spacing


def get_prediction(volume, spacing):
    """调用 /segment_3d 获取预测。额外: 我们需要 label map 直接对比。
    方案: 调用 API 获取 meshes，然后重建 kidney/tumor 的 label map。
    
    更简单: 直接用 nibabel 保存 volume, 调 TotalSegmentator Python API。
    但最快的方式: 调现有 API，再调 /segment_by_name 获取肾脏。
    """
    log("Running TotalSegmentator via API ...")
    
    # 方案: 保存为临时 NIfTI, 然后直接从服务获取 label map
    # 但服务清理了临时文件... 我们换个方法:
    # 直接调 /segment_by_name for kidney, 获取肾脏体积
    # 然后比较 volumes 而非 pixel-level Dice
    
    # 实际上最可靠的方法: 
    # 把 volume 存为 npy, 让服务新增一个返回 label map 的端点
    # 临时方案: 先算 volume-based accuracy (体积对比)
    
    r = requests.post(f"{TOTALSEG}/segment_3d",
                      json={"series_instance_uid": SERIES_UID},
                      timeout=600)
    data = r.json()
    
    # 从 meshes 提取 kidney 相关数据
    kidney_info = {}
    for m in data.get("meshes", []):
        name = m.get("name", "")
        if "kidney" in name:
            kidney_info[name] = m.get("volume_cm3", 0)
    
    log(f"  Kidney volumes: {kidney_info}")
    return data


def load_gt():
    """加载 ground truth"""
    gt = np.load(GT_PATH)
    log(f"GT shape: {gt.shape}, values: {np.unique(gt)}")
    # 0=bg, 1=kidney, 2=tumor
    kidney_gt = (gt == 1).astype(np.uint8)
    tumor_gt = (gt == 2).astype(np.uint8)
    kidney_vol_px = kidney_gt.sum()
    tumor_vol_px = tumor_gt.sum()
    log(f"GT kidney voxels: {kidney_vol_px}, tumor voxels: {tumor_vol_px}")
    return gt, kidney_gt, tumor_gt


def dice_score(pred, gt):
    """Dice = 2*|pred & gt| / (|pred| + |gt|)"""
    pred_bin = (pred > 0).astype(np.float64)
    gt_bin = (gt > 0).astype(np.float64)
    intersection = (pred_bin * gt_bin).sum()
    denom = pred_bin.sum() + gt_bin.sum()
    if denom == 0:
        return 1.0 if intersection == 0 else 0.0
    return 2.0 * intersection / denom


def main():
    log("=" * 50)
    log("Dice Score Evaluation: TotalSegmentator vs KiTS GT")
    log("=" * 50)

    # 加载 GT
    gt_full, kidney_gt, tumor_gt = load_gt()

    # 获取预测（直接调 Python API 比 HTTP 更快拿到 label map）
    # 这里我们需要直接从 TotalSegmentator 拿到 label map
    # 最快方法: 用 totalseg_service.py 里的 _docker_totalseg 函数
    
    log("Getting prediction label map ...")
    log("Adding /segment_raw endpoint to totalseg_service.py ...")
    
    # ═══════════════════════════════
    # 直接在 Python 里调 TotalSegmentator（复用 service 的代码）
    # ═══════════════════════════════
    
    # 先通过 API 触发推理并保留 label map
    # 修改: 我们直接用 totalseg_service 的内部函数
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    # 从 Orthanc 拉 DICOM
    volume, spacing = fetch_dicom_volume(SERIES_UID)
    
    # 保存为临时 NIfTI
    import tempfile
    tmpdir = tempfile.mkdtemp()
    nii_path = os.path.join(tmpdir, "input.nii.gz")
    nii = nib.Nifti1Image(volume.astype(np.int16), np.eye(4))
    nib.save(nii, nii_path)
    
    # 导入并调 TotalSegmentator
    from totalseg_service import _docker_totalseg
    seg_dir = os.path.join(tmpdir, "seg")
    os.makedirs(seg_dir, exist_ok=True)
    
    log("Running TotalSegmentator ...")
    t0 = time.time()
    seg_img = _docker_totalseg(nii_path, seg_dir, task="total", fast=True)
    elapsed = time.time() - t0
    log(f"  Done in {elapsed:.1f}s")
    
    pred_labels = seg_img.get_fdata().astype(np.int32)
    log(f"  Pred shape: {pred_labels.shape}, unique: {np.unique(pred_labels)[:20]}")
    
    # TotalSegmentator 的 label map 需要映射到 kidney/tumor
    # 查看 class_map
    from totalsegmentator.map_to_binary import class_map
    total_map = class_map.get("total", {})
    
    # 找 kidney 相关标签
    kidney_labels = []
    tumor_labels = []
    for lid, name in total_map.items():
        nl = name.lower()
        if "kidney" in nl and "cyst" not in nl and "tumor" not in nl:
            kidney_labels.append(lid)
        if ("kidney" in nl and "tumor" in nl) or ("renal" in nl and "tumor" in nl):
            tumor_labels.append(lid)
    
    log(f"  Kidney labels: {kidney_labels} -> {[total_map.get(l, '?') for l in kidney_labels]}")
    log(f"  Tumor labels: {tumor_labels} -> {[total_map.get(l, '?') for l in tumor_labels]}")
    
    # 构建 kidney binary mask
    kidney_pred = np.isin(pred_labels, kidney_labels).astype(np.uint8)
    tumor_pred = np.isin(pred_labels, tumor_labels).astype(np.uint8)
    
    # 重采样预测到 GT 尺寸 (53, 512, 512)
    # GT 是 53 层 512x512, 预测可能是不同尺寸
    gt_shape = gt_full.shape
    
    if kidney_pred.shape != gt_shape:
        log(f"  Resampling pred {kidney_pred.shape} -> GT {gt_shape}")
        zoom_factors = [gt_shape[i] / kidney_pred.shape[i] for i in range(3)]
        kidney_pred = zoom(kidney_pred.astype(float), zoom_factors, order=0) > 0.5
        tumor_pred = zoom(tumor_pred.astype(float), zoom_factors, order=0) > 0.5
        kidney_pred = kidney_pred.astype(np.uint8)
        tumor_pred = tumor_pred.astype(np.uint8)
    
    # 计算 Dice
    kidney_dice = dice_score(kidney_pred, kidney_gt)
    tumor_dice = dice_score(tumor_pred, tumor_gt)
    
    log("=" * 50)
    log(f"Kidney Dice: {kidney_dice:.4f}")
    log(f"Tumor Dice:  {tumor_dice:.4f}")
    log("=" * 50)
    
    # 也输出体积对比
    voxel_vol_ml = spacing[0] * spacing[1] * spacing[2] / 1000.0
    log(f"Voxel volume: {voxel_vol_ml:.6f} mL")
    log(f"GT  kidney vol: {kidney_gt.sum() * voxel_vol_ml:.1f} mL")
    log(f"Pred kidney vol: {kidney_pred.sum() * voxel_vol_ml:.1f} mL")
    log(f"GT  tumor vol: {tumor_gt.sum() * voxel_vol_ml:.1f} mL")
    log(f"Pred tumor vol: {tumor_pred.sum() * voxel_vol_ml:.1f} mL")
    
    # 保存结果
    result = {
        "kidney_dice": round(float(kidney_dice), 4),
        "tumor_dice": round(float(tumor_dice), 4),
        "gt_shape": list(gt_shape),
        "pred_shape": list(kidney_pred.shape),
        "gt_kidney_voxels": int(kidney_gt.sum()),
        "pred_kidney_voxels": int(kidney_pred.sum()),
        "gt_tumor_voxels": int(tumor_gt.sum()),
        "pred_tumor_voxels": int(tumor_pred.sum()),
        "voxel_volume_ml": round(voxel_vol_ml, 6),
    }
    
    out_path = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results/dice_result.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    log(f"Saved: {out_path}")
    
    # 清理
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
