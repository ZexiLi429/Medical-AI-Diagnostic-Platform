"""
TotalSegmentator 全器官分割服务 (port 8004)
- POST /segment            {series_id | series_instance_uid}  →  全部 104 器官
- POST /segment_by_name    {series_instance_uid, organ_name}  →  仅匹配器官
- POST /segment_3d         {series_instance_uid}             →  多器官 3D Mesh（用于 OHIF 3D 渲染）
- GET  /health             →  健康检查
- 自动从 Orthanc 读取 DICOM 序列，运行 TotalSegmentator 推理
"""
from dotenv import load_dotenv
load_dotenv()

import multiprocessing
if 'win' in __import__('sys').platform:
    multiprocessing.set_start_method("spawn", force=True)
import os
os.environ["nnUNet_n_proc_DA"] = "0"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
import torch
torch._dynamo.config.disable = True
print(f"[TotalSeg] CUDA: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
multiprocessing.freeze_support()

import sys
import io
import time
import tempfile
import json
import glob
import shutil
import gc
import traceback
from pathlib import Path
import numpy as np
import nibabel as nib
import requests
from PIL import Image
from typing import List, Optional, Tuple
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from scipy.ndimage import zoom
from skimage.measure import marching_cubes

# ── 初始化 nnUNet 路径（必须在导入 nnunet 前） ──
from totalsegmentator.config import setup_nnunet
setup_nnunet()

# ── monkey-patch: 单进程预处理 ──
import nnunet.inference.predict as nnunet_predict
_orig = nnunet_predict.preprocess_multithreaded
def _sync_preprocess(trainer, list_of_lists, output_files, num_processes=2, segs_from_prev_stage=None):
    if segs_from_prev_stage is None:
        segs_from_prev_stage = [None] * len(list_of_lists)
    classes = list(range(1, trainer.num_classes))
    for i, l in enumerate(list_of_lists):
        d, _, dct = trainer.preprocess_patient(l)
        if segs_from_prev_stage[i] is not None:
            import SimpleITK as sitk
            from batchgenerators.augmentations.utils import resize_segmentation
            from nnunet.utilities.one_hot_encoding import to_one_hot
            seg_prev = sitk.GetArrayFromImage(sitk.ReadImage(segs_from_prev_stage[i]))
            seg_prev = seg_prev.transpose(trainer.plans['transpose_forward'])
            seg_reshaped = resize_segmentation(seg_prev, d.shape[1:], order=1, cval=0)
            seg_reshaped = to_one_hot(seg_reshaped, classes)
            d = np.vstack((d, seg_reshaped)).astype(np.float32)
        if np.prod(d.shape) > (2e9 / 4 * 0.85):
            np.save(output_files[i][:-7] + ".npy", d)
            d = output_files[i][:-7] + ".npy"
        yield (output_files[i], (d, dct))
nnunet_predict.preprocess_multithreaded = _sync_preprocess

from totalsegmentator.python_api import totalsegmentator

# ── 标签映射：运行时从已安装的 TotalSegmentator 包自动读取 ──
LABEL_MAP: dict = {}
try:
    from totalsegmentator.map_to_binary import class_map as _ts_class_map
    LABEL_MAP = _ts_class_map.get("total", {})
    print(f"[TotalSeg] 从已安装包读取 class_map['total']: {len(LABEL_MAP)} 类")
except Exception as e:
    print(f"[TotalSeg] 警告: 无法读取 class_map ({e})")

# ── Docker v2 额外标签（v2.11 新增 13 类）──
_V2_EXTRA_LABELS = {
    105: "prostate",
    106: "seminal_vesicle_left",
    107: "seminal_vesicle_right",
    108: "epididymis_left",
    109: "epididymis_right",
    110: "penis",
    111: "vagina",
    112: "uterus",
    113: "ovary_left",
    114: "ovary_right",
    115: "testis_left",
    116: "testis_right",
    117: "spermatic_cord",
}

# 补齐 Docker v2 标签（本地 v1.5.7 只有 104 类）
if len(LABEL_MAP) < 117:
    for lbl, nm in _V2_EXTRA_LABELS.items():
        if lbl not in LABEL_MAP:
            LABEL_MAP[lbl] = nm
    print(f"[TotalSeg] 已补齐 Docker v2 标签 → {len(LABEL_MAP)} 类")

# 兜底（万一啥都没读到）
if not LABEL_MAP:
    LABEL_MAP = {
        1: "spleen", 2: "kidney_right", 3: "kidney_left", 4: "gallbladder",
        5: "liver", 6: "stomach", 7: "aorta", 8: "inferior_vena_cava",
        9: "portal_vein_and_splenic_vein", 10: "pancreas", 11: "adrenal_gland_right",
        12: "adrenal_gland_left", 13: "lung_upper_lobe_left", 14: "lung_lower_lobe_left",
        15: "lung_upper_lobe_right", 16: "lung_middle_lobe_right", 17: "lung_lower_lobe_right",
        18: "vertebrae_L5", 19: "vertebrae_L4", 20: "vertebrae_L3", 21: "vertebrae_L2",
        22: "vertebrae_L1", 23: "vertebrae_T12", 24: "vertebrae_T11", 25: "vertebrae_T10",
        26: "vertebrae_T9", 27: "vertebrae_T8", 28: "vertebrae_T7", 29: "vertebrae_T6",
        30: "vertebrae_T5", 31: "vertebrae_T4", 32: "vertebrae_T3", 33: "vertebrae_T2",
        34: "vertebrae_T1", 35: "vertebrae_C7", 36: "vertebrae_C6", 37: "vertebrae_C5",
        38: "vertebrae_C4", 39: "vertebrae_C3", 40: "vertebrae_C2", 41: "vertebrae_C1",
        42: "esophagus", 43: "trachea", 44: "heart_myocardium", 45: "heart_atrium_left",
        46: "heart_ventricle_left", 47: "heart_atrium_right", 48: "heart_ventricle_right",
        49: "pulmonary_artery", 50: "brain", 51: "iliac_artery_left", 52: "iliac_artery_right",
        53: "iliac_vena_left", 54: "iliac_vena_right", 55: "small_bowel", 56: "duodenum",
        57: "colon", 58: "rib_left_1", 59: "rib_left_2", 60: "rib_left_3",
        61: "rib_left_4", 62: "rib_left_5", 63: "rib_left_6", 64: "rib_left_7",
        65: "rib_left_8", 66: "rib_left_9", 67: "rib_left_10", 68: "rib_left_11",
        69: "rib_left_12", 70: "rib_right_1", 71: "rib_right_2", 72: "rib_right_3",
        73: "rib_right_4", 74: "rib_right_5", 75: "rib_right_6", 76: "rib_right_7",
        77: "rib_right_8", 78: "rib_right_9", 79: "rib_right_10", 80: "rib_right_11",
        81: "rib_right_12", 82: "humerus_left", 83: "humerus_right", 84: "scapula_left",
        85: "scapula_right", 86: "clavicula_left", 87: "clavicula_right",
        88: "femur_left", 89: "femur_right", 90: "hip_left", 91: "hip_right",
        92: "sacrum", 93: "face", 94: "gluteus_maximus_left", 95: "gluteus_maximus_right",
        96: "gluteus_medius_left", 97: "gluteus_medius_right", 98: "gluteus_minimus_left",
        99: "gluteus_minimus_right", 100: "autochthon_left", 101: "autochthon_right",
        102: "iliopsoas_left", 103: "iliopsoas_right", 104: "urinary_bladder",
    }

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TotalSegmentator Service", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ORTHANC = os.environ.get("ORTHANC_URL", "http://localhost:8042")


class SegmentRequest(BaseModel):
    series_id: str = ""          # Orthanc series ID
    series_instance_uid: str = ""  # DICOM SeriesInstanceUID (与 OHIF 前端对接)
    organ_name: str = ""          # 可选：仅分割/渲染匹配的器官（用于 /segment_3d）

class SegByNameRequest(BaseModel):
    series_instance_uid: str     # DICOM SeriesInstanceUID
    organ_name: str              # 如 "liver", "spleen", "kidney_left"
    series_id: str = ""          # 可选直接 Orthanc ID

class OrganInfo(BaseModel):
    label: int
    name: str
    voxels: int
    volume_cm3: float

    class Config:
        # allow extra fields for future compat
        extra = "allow"


class SegmentResponse(BaseModel):
    success: bool
    organs: List[OrganInfo]
    total_organs: int
    shape: List[int]
    elapsed_s: float
    error: str = ""


def resolve_series_id(series_id: str, series_instance_uid: str) -> str:
    """通过 DICOM UID 查询 Orthanc 获取实际 series ID"""
    if series_id:
        return series_id
    if series_instance_uid:
        # 通过 Orthanc tools/find 查询
        try:
            r = requests.post(f"{ORTHANC}/tools/find", json={
                "Level": "Series",
                "Query": {"SeriesInstanceUID": series_instance_uid},
                "Limit": 1,
            }, timeout=10)
            r.raise_for_status()
            results = r.json()
            if results:
                return results[0]
        except Exception as e:
            print(f"[TotalSeg] Orthanc lookup failed: {e}")
    raise ValueError("Neither series_id nor series_instance_uid provided, or lookup failed")


# ── 常用别名映射（方便用户用简短名称查询） ──
ORGAN_ALIASES: dict = {
    "left lung": ["lung_upper_lobe_left", "lung_lower_lobe_left"],
    "right lung": ["lung_upper_lobe_right", "lung_middle_lobe_right", "lung_lower_lobe_right"],
    "left kidney": ["kidney_left"],
    "right kidney": ["kidney_right"],
    "heart": ["heart_myocardium", "heart_atrium_left", "heart_ventricle_left",
              "heart_atrium_right", "heart_ventricle_right"],
    "spine": ["vertebrae_C1","vertebrae_C2","vertebrae_C3","vertebrae_C4","vertebrae_C5",
              "vertebrae_C6","vertebrae_C7","vertebrae_T1","vertebrae_T2","vertebrae_T3",
              "vertebrae_T4","vertebrae_T5","vertebrae_T6","vertebrae_T7","vertebrae_T8",
              "vertebrae_T9","vertebrae_T10","vertebrae_T11","vertebrae_T12",
              "vertebrae_L1","vertebrae_L2","vertebrae_L3","vertebrae_L4","vertebrae_L5",
              "sacrum"],
    "ribs left": ["rib_left_1","rib_left_2","rib_left_3","rib_left_4","rib_left_5",
                  "rib_left_6","rib_left_7","rib_left_8","rib_left_9","rib_left_10",
                  "rib_left_11","rib_left_12"],
    "ribs right": ["rib_right_1","rib_right_2","rib_right_3","rib_right_4","rib_right_5",
                   "rib_right_6","rib_right_7","rib_right_8","rib_right_9","rib_right_10",
                   "rib_right_11","rib_right_12"],
    "pelvis": ["hip_left", "hip_right", "sacrum"],
    "great vessels": ["aorta", "inferior_vena_cava", "portal_vein_and_splenic_vein",
                      "pulmonary_artery", "iliac_artery_left", "iliac_artery_right",
                      "iliac_vena_left", "iliac_vena_right"],
}


def match_organs(organ_name: str) -> List[int]:
    """多词精确交集匹配器官名，返回匹配的 label 列表。

    支持:
    - 精确别名（如 "left lung" → 左上叶+左下叶）
    - 多词交集匹配（如 "lung left" → 同时含 lung 和 left 的器官）
    - 单词片段匹配（如 "liver" → 直接子串匹配）
    """
    query = organ_name.lower().strip()
    if not query:
        return []

    # 1) 精确别名匹配
    if query in ORGAN_ALIASES:
        alias_names = ORGAN_ALIASES[query]
        labels = []
        for lbl, nm in LABEL_MAP.items():
            if nm in alias_names:
                labels.append(lbl)
        if labels:
            print(f"[TotalSeg] alias '{query}' → {len(labels)} labels: {alias_names}")
            return labels

    # 2) 多词交集匹配：所有 token 都必须出现在器官名的某个部分中
    tokens = query.split()
    matched = []
    for label, name in LABEL_MAP.items():
        name_parts = name.split('_')
        # 每个 token 只需匹配器官名或其任一部分
        all_match = True
        for tok in tokens:
            tok_match = (tok in name) or any(tok in p for p in name_parts)
            if not tok_match:
                all_match = False
                break
        if all_match:
            matched.append(label)

    if matched:
        names = [LABEL_MAP[l] for l in matched]
        print(f"[TotalSeg] query '{query}' → {len(matched)} labels: {names}")
        return matched

    # 3) 兜底：单 token 的宽松子串匹配
    if len(tokens) == 1:
        tok = tokens[0]
        for label, name in LABEL_MAP.items():
            if tok in name:
                matched.append(label)
        if not matched:
            for label, name in LABEL_MAP.items():
                parts = name.split('_')
                if any(tok in p for p in parts):
                    matched.append(label)

    if matched:
        names = [LABEL_MAP[l] for l in matched]
        print(f"[TotalSeg] query '{query}' (fallback) → {len(matched)} labels: {names}")

    return matched


def _parse_dicom_list(val):
    """解析 DICOM 反斜杠分隔的多值字符串 (如 IPP, PS, IOP)"""
    if val is None or not isinstance(val, str):
        return [0.0]
    BS = chr(92)  # 反斜杠字符
    # 按反斜杠拆分
    parts = val.replace(BS + BS, ' ').replace(BS, ' ').split()
    try:
        return [float(p) for p in parts if p]
    except ValueError:
        return [0.0]

def load_dicom_series(series_id: str) -> Tuple[np.ndarray, dict]:
    """从 Orthanc 加载完整 DICOM 序列，返回 (volume, meta)"""
    r = requests.get(f"{ORTHANC}/series/{series_id}", timeout=10)
    r.raise_for_status()
    instances = r.json()["Instances"]

    inst_data = []
    for inst_id in instances:
        tags = requests.get(f"{ORTHANC}/instances/{inst_id}/simplified-tags", timeout=10).json()
        inst_num_raw = tags.get("InstanceNumber", "9999")
        inst_num = int(inst_num_raw) if inst_num_raw else 9999
        # 直接从 JSON 取 IPP — 可能是字符串如 "0\\0\\-115"
        ipp_raw = tags.get("ImagePositionPatient")
        ipp_vals = _parse_dicom_list(ipp_raw)
        ip_z = ipp_vals[2] if len(ipp_vals) >= 3 else 0.0
        inst_data.append((inst_num, ip_z, inst_id, tags, ipp_raw))
    inst_data.sort(key=lambda x: x[1])  # 按 IPP Z 排序（保 origin 正确；坐标变换已对齐 MedSAM2）

    sorted_ids = [x[2] for x in inst_data]
    first_tags = inst_data[0][3]
    first_ipp_raw = inst_data[0][4]
    last_ip_z = inst_data[-1][1]
    first_ip_z = inst_data[0][1]

    # PixelSpacing
    ps_vals = _parse_dicom_list(first_tags.get("PixelSpacing"))
    sx = ps_vals[0] if len(ps_vals) >= 1 else 1.0
    sy = ps_vals[1] if len(ps_vals) >= 2 else sx

    # Z spacing
    if len(inst_data) >= 2 and abs(last_ip_z - first_ip_z) > 0.01:
        dz = abs(last_ip_z - first_ip_z) / (len(inst_data) - 1)
    else:
        st_vals = _parse_dicom_list(first_tags.get("SliceThickness"))
        dz = st_vals[0] if st_vals and st_vals[0] > 0.01 else 1.0

    # IPP origin: 兼容 Orthanc simplified-tags 返回 string 或 list 两种格式
    ipp_raw = first_tags.get("ImagePositionPatient", "")
    if isinstance(ipp_raw, (list, tuple)):
        # Orthanc 可能直接返回 JSON 数组 [x, y, z]
        ipp_parsed = [float(v) for v in ipp_raw[:3]]
    elif ipp_raw and isinstance(ipp_raw, str):
        ipp_parsed = _parse_dicom_list(ipp_raw)
    else:
        ipp_parsed = [0.0, 0.0, 0.0]
    if len(ipp_parsed) < 3:
        # 补齐或用排序得到的 Z 值
        while len(ipp_parsed) < 3:
            ipp_parsed.append(0.0)

    origin_x = ipp_parsed[0]
    origin_y = ipp_parsed[1]
    origin_z = ipp_parsed[2]

    # IOP — 同样兼容 string / list 两种格式
    iop_raw = first_tags.get("ImageOrientationPatient", "")
    if isinstance(iop_raw, (list, tuple)):
        iop = [float(v) for v in iop_raw[:6]]
    else:
        iop = _parse_dicom_list(iop_raw)
    if len(iop) < 6:
        iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]

    meta = {
        "spacing": [sx, sy, dz],
        "origin": [origin_x, origin_y, origin_z],
        "iop": iop,
        "num_slices": len(instances),
    }
    print(f"[TotalSeg] DICOM: spacing=[{sx},{sy},{dz}], origin=[{origin_x:.1f},{origin_y:.1f},{origin_z:.1f}], IOP={iop[:3]}/{iop[3:]}, slices={len(instances)}")

    # 读像素
    slices = []
    for inst_id in sorted_ids:
        img = requests.get(f"{ORTHANC}/instances/{inst_id}/rendered",
                           params={"quality": 100}, timeout=30)
        arr = np.array(Image.open(io.BytesIO(img.content)).convert("L"))
        slices.append(arr)

    return np.stack(slices), meta


# ── 推理缓存：避免同一 series 重复跑模型 ──
_inference_cache: dict = {}  # {series_id: (seg_arr, organs, elapsed, meta)}
_lesion_cache: dict = {}     # {(series_id, organ): (lesion_arr, lesion_organs, meta, original_z)}

def _docker_totalseg(input_nii: str, output_dir: str, task: str = "total", fast: bool = True):
    """通过 Docker 运行 TotalSegmentator v2（117 类，nnUNet v2）。
    
    自动拉取 wasserth/totalsegmentator 镜像，挂载 input/output 目录运行推理。
    Windows 本地用 v1.5.7（104 类），Docker 里用最新版（117 类）。
    """
    import subprocess
    input_abs = os.path.abspath(input_nii)
    input_parent = os.path.dirname(input_abs)
    input_name = os.path.basename(input_abs)
    output_abs = os.path.abspath(output_dir)
    os.makedirs(output_abs, exist_ok=True)

    # 检查 Docker 可用性
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[TotalSeg] Docker 不可用 ({e})，回退到本地 v1.5.7")
        if task != "total":
            raise RuntimeError(f"Docker required for task '{task}' — local v1.5.7 only supports 'total'")
        return totalsegmentator(input_nii, output=output_dir, task=task, fast=fast,
                                ml=True, nr_thr_saving=1, body_seg=True, quiet=True)

    cmd = [
        "docker", "run", "--rm",
        "--network=host",
        "-v", f"{input_parent}:/input:ro",
        "-v", f"{output_abs}:/output",
    ]

    # 病灶任务不需要 ml/nr_thr_saving（只有 total 任务支持）
    extra_args = ", ml=True, nr_thr_saving=1" if task == "total" else ""

    cmd += [
        "-e", "nnUNet_n_proc_DA=0",
        "-e", "OMP_NUM_THREADS=1",
        "-e", "MKL_NUM_THREADS=1",
        "-e", "nnUNet_compile=False",
        "-e", "CUDA_VISIBLE_DEVICES=",
        "--shm-size=4g",
        "--memory=16g",
        "--entrypoint", "",
        "wasserth/totalsegmentator:2.15.0",
        "python", "-c",
        f"import os; os.environ['nnUNet_n_proc_DA']='0'; os.environ['nnUNet_compile']='False'; "
        f"from totalsegmentator.python_api import totalsegmentator; "
        f"print('[Docker] Starting inference ({task})...'); "
        f"seg = totalsegmentator('/input/{input_name}', output='/output/seg', task='{task}', fast={'True' if fast else 'False'}{extra_args}); "
        f"print('[Docker] DONE')",
    ]
    
    print(f"[TotalSeg] Docker: starting inference...")
    process = None
    last_lines: list = []
    try:
        # 实时输出进度
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, encoding='utf-8', errors='replace')
        for line in process.stdout:
            line = line.rstrip()
            if line:
                print(f"[Docker] {line}")
                last_lines.append(line)
                if len(last_lines) > 20:
                    last_lines.pop(0)
        process.wait(timeout=1800)
        
        if process.returncode != 0:
            full_err = "\n".join(last_lines[-5:])
            raise RuntimeError(f"Docker TotalSegmentator failed (code={process.returncode}). Last output:\n{full_err}")
        
        # Docker 输出: /output/seg.nii 或 /output/seg.nii.gz 或 /output/seg/s01.nii.gz
        candidates = glob.glob(os.path.join(output_abs, "**", "*.nii*"), recursive=True)
        if not candidates:
            raise FileNotFoundError(f"No .nii/.nii.gz found in {output_abs}/")
        seg_file = candidates[0]
        
        print(f"[TotalSeg] Docker 完成，读取 {seg_file}")
        seg_img = nib.load(seg_file)
        # 立即加载到内存（nibabel 懒加载，需要 get_fdata 才能真正读取）
        data = seg_img.get_fdata().astype(np.int16)
        # 清理临时目录
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except:
            pass
        # 重建一个内存 Nifti 对象返回
        return nib.Nifti1Image(data, seg_img.affine, seg_img.header)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker TotalSegmentator timed out (30 min)")
    finally:
        if process and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=10)
            except:
                pass

def _run_inference_and_collect_organs(series_id: str) -> tuple:
    """共用推理逻辑，返回 (seg_arr, organs, elapsed, meta)；命中缓存直接返回"""
    if series_id in _inference_cache:
        seg_arr, organs, elapsed, meta = _inference_cache[series_id]
        print(f"[TotalSeg] Cache hit for {series_id}, {len(organs)} organs")
        return seg_arr, organs, elapsed, meta

    # 清除旧缓存，防止 OOM
    _inference_cache.clear()
    _lesion_cache.clear()

    t0 = time.time()
    print(f"[TotalSeg] Loading series {series_id}...")
    volume, meta = load_dicom_series(series_id)
    print(f"[TotalSeg] Volume shape: {volume.shape}")

    # 大体积自动降采样（CPU 16GB 内存限制）
    original_shape = volume.shape
    z_scale = 1.0
    MAX_SLICES = 250
    if volume.shape[0] > MAX_SLICES:
        z_scale = MAX_SLICES / volume.shape[0]
        print(f"[TotalSeg] Downsampling Z: {volume.shape[0]} -> {MAX_SLICES} (scale={z_scale:.2f})...")
        # 用 float32 降采样，减少峰值内存
        tmp = volume.astype(np.float32)
        del volume; gc.collect()
        volume = zoom(tmp, (z_scale, 1.0, 1.0), order=1).astype(np.int16)
        del tmp; gc.collect()
        meta["spacing"] = [meta["spacing"][0], meta["spacing"][1], meta["spacing"][2] / z_scale]
        print(f"[TotalSeg] Downsampled shape: {volume.shape}")

    # 预清理，释放读 DICOM 时的临时内存
    gc.collect()

    output_dir = tempfile.mkdtemp()
    nii_path = os.path.join(output_dir, "input.nii.gz")
    nii = nib.Nifti1Image(volume.astype(np.int16), np.eye(4))
    nib.save(nii, nii_path)
    # 写完后立即释放 volume
    del volume; gc.collect()

    print(f"[TotalSeg] Running inference via Docker (v2 117 classes)...")
    seg_img = _docker_totalseg(
        nii_path,
        os.path.join(output_dir, "seg"),
        task="total",
        fast=True,
    )
    seg_arr_small = seg_img.get_fdata().astype(np.int16)
    del seg_img
    gc.collect()

    # 恢复到原始 Z 维度
    if z_scale < 1.0:
        print(f"[TotalSeg] Upsampling seg from {seg_arr_small.shape} back to {original_shape}...")
        seg_arr = zoom(seg_arr_small.astype(np.float32), (1/z_scale, 1.0, 1.0), order=0).astype(np.int16)
        del seg_arr_small
        gc.collect()
    else:
        seg_arr = seg_arr_small

    sx, sy, dz = meta["spacing"]

    organs = []
    unique_labels = np.unique(seg_arr)
    for label in unique_labels:
        if label == 0:
            continue
        count = int((seg_arr == label).sum())
        if count > 100:
            name = LABEL_MAP.get(int(label), f"unknown_{label}")
            vol = count * sx * sy * dz / 1000.0  # mm³ → cm³（真实间距）
            organs.append(OrganInfo(
                label=int(label),
                name=name,
                voxels=count,
                volume_cm3=round(vol, 1),
            ))
    organs.sort(key=lambda x: x.volume_cm3, reverse=True)

    elapsed = time.time() - t0
    print(f"[TotalSeg] Done in {elapsed:.1f}s, {len(organs)} organs found")

    # ── 诊断：打印关键标签的切片分布 ──
    _debug_labels = {57: "colon", 5: "liver", 6: "stomach", 13: "lung_upper_lobe_left"}
    for _dlbl, _dname in _debug_labels.items():
        _slices_with = np.where((seg_arr == _dlbl).any(axis=(1, 2)))[0]
        if len(_slices_with) > 0:
            _z_min_mm = _slices_with[0] * dz
            _z_max_mm = _slices_with[-1] * dz
            print(f"[TotalSeg DIAG] {_dname}({_dlbl}): slices {_slices_with[0]}-{_slices_with[-1]} ({(len(_slices_with))} slices), Z=[{_z_min_mm:.1f}..{_z_max_mm:.1f}] mm relative")
        else:
            print(f"[TotalSeg DIAG] {_dname}({_dlbl}): NOT FOUND")
    print(f"[TotalSeg DIAG] DICOM origin (IPP): {meta['origin']}")
    print(f"[TotalSeg DIAG] DICOM IOP: {meta['iop'][:3]} / {meta['iop'][3:]}")
    print(f"[TotalSeg DIAG] Num slices: {meta['num_slices']}, spacing: {meta['spacing']}")

    _inference_cache[series_id] = (seg_arr, organs, elapsed, meta)
    gc.collect()
    # 清理临时目录
    try:
        shutil.rmtree(output_dir, ignore_errors=True)
    except:
        pass
    return seg_arr, organs, elapsed, meta


@app.post("/segment", response_model=SegmentResponse)
def segment_series(req: SegmentRequest):
    try:
        series_id = resolve_series_id(req.series_id, req.series_instance_uid)
        seg_arr, organs, elapsed, _meta = _run_inference_and_collect_organs(series_id)
        return SegmentResponse(
            success=True,
            organs=organs,
            total_organs=len(organs),
            shape=list(seg_arr.shape),
            elapsed_s=round(elapsed, 1),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/segment_by_name", response_model=SegmentResponse)
def segment_by_name(req: SegByNameRequest):
    """文本提示词分割 — 如 organ_name='liver' 只返回肝脏"""
    try:
        series_id = resolve_series_id(req.series_id, req.series_instance_uid)
        matched_labels = match_organs(req.organ_name)
        if not matched_labels:
            raise HTTPException(status_code=404, detail=f"Organ '{req.organ_name}' not found")
        print(f"[TotalSeg] Organ hint: '{req.organ_name}' → labels {matched_labels}")
        seg_arr, all_organs, elapsed, _meta = _run_inference_and_collect_organs(series_id)
        filtered = [o for o in all_organs if o.label in matched_labels]
        return SegmentResponse(success=True, organs=filtered, total_organs=len(filtered), shape=list(seg_arr.shape), elapsed_s=round(elapsed, 1))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class FileMaskRequest(BaseModel):
    nifti_path: str  # absolute path to .nii.gz file

class MaskRequest(BaseModel):
    series_id: str = ""
    series_instance_uid: str = ""

class MaskResponse(BaseModel):
    success: bool
    shape: List[int]
    labels: List[int]
    label_names: List[str]
    file_path: str = ""         # saved .npy path
    elapsed_s: float = 0.0

@app.post("/segment_file", response_model=MaskResponse)
def segment_file(req: FileMaskRequest):
    """直接对本地 NIfTI 文件推理，返回 label map"""
    import tempfile, shutil
    nii = nib.load(req.nifti_path)
    volume = nii.get_fdata().astype(np.int16)
    # NIfTI from HuggingFace is already (z, y, x) — keep as-is
    # Moderate downsampling for very large volumes
    MAX_SLICES = 500
    z_scale = 1.0
    if volume.shape[0] > MAX_SLICES:
        z_scale = MAX_SLICES / volume.shape[0]
        print(f"[TotalSeg NIfTI] Downsampling {volume.shape[0]} -> {MAX_SLICES}")
        volume = zoom(volume.astype(np.float32), (z_scale, 1.0, 1.0), order=1).astype(np.int16)
        gc.collect()

    output_dir = tempfile.mkdtemp()
    nii_path = os.path.join(output_dir, "input.nii.gz")
    nib.save(nib.Nifti1Image(volume.astype(np.int16), np.eye(4)), nii_path)
    del volume; gc.collect()

    t0 = time.time()
    seg_img = _docker_totalseg(nii_path, os.path.join(output_dir, "seg"), task="total", fast=True)
    elapsed = time.time() - t0
    seg_arr = seg_img.get_fdata().astype(np.int32)
    gc.collect()

    unique_labels = sorted(set(int(v) for v in np.unique(seg_arr)))
    label_names = []
    for lbl in unique_labels:
        label_names.append("background" if lbl == 0 else LABEL_MAP.get(lbl, f"class_{lbl}"))

    out_path = f"c:/Users/Dell/Desktop/miscada-project-master/experiment_results/pred_nifti_{os.path.basename(req.nifti_path).replace('.nii.gz','')}.npy"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.save(out_path, seg_arr.astype(np.int16))

    shutil.rmtree(output_dir, ignore_errors=True)
    return MaskResponse(success=True, shape=list(seg_arr.shape), labels=unique_labels,
                       label_names=label_names, file_path=out_path, elapsed_s=round(elapsed,1))


@app.post("/segment_mask", response_model=MaskResponse)
def segment_mask(req: MaskRequest):
    """保存原始 label map 到本地 .npy，返回路径"""
    series_id = resolve_series_id(req.series_id, req.series_instance_uid)
    seg_arr, organs, elapsed, _meta = _run_inference_and_collect_organs(series_id)
    unique_labels = sorted(set(int(v) for v in np.unique(seg_arr)))
    label_names = []
    for lbl in unique_labels:
        if lbl == 0:
            label_names.append("background")
        else:
            label_names.append(LABEL_MAP.get(lbl, f"class_{lbl}"))
    # 保存到本地
    out_path = f"c:/Users/Dell/Desktop/miscada-project-master/experiment_results/pred_{series_id[:12]}.npy"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.save(out_path, seg_arr.astype(np.int16))
    return MaskResponse(
        success=True,
        shape=list(seg_arr.shape),
        labels=unique_labels,
        label_names=label_names,
        file_path=out_path,
        elapsed_s=round(elapsed, 1),
    )


# ── 3D Mesh 数据模型 ──────────────────────────────────────────────

# 20 种高对比度颜色（用于区分不同器官）
ORGAN_COLORS: List[List[float]] = [
    [0.90, 0.30, 0.30],  # red
    [0.30, 0.60, 0.90],  # blue
    [0.30, 0.80, 0.40],  # green
    [0.95, 0.75, 0.10],  # gold
    [0.70, 0.30, 0.90],  # purple
    [0.10, 0.80, 0.80],  # cyan
    [1.00, 0.50, 0.00],  # orange
    [0.50, 0.50, 0.90],  # indigo
    [0.90, 0.40, 0.70],  # pink
    [0.40, 0.70, 0.30],  # lime
    [0.80, 0.60, 0.20],  # brown
    [0.20, 0.50, 0.80],  # steel
    [0.90, 0.20, 0.50],  # crimson
    [0.50, 0.80, 0.50],  # mint
    [0.80, 0.40, 0.40],  # salmon
    [0.40, 0.40, 0.80],  # lavender
    [0.70, 0.70, 0.20],  # olive
    [0.30, 0.70, 0.70],  # teal
    [0.90, 0.55, 0.30],  # peach
    [0.55, 0.30, 0.70],  # plum
]


class OrganMesh(BaseModel):
    label: int
    name: str
    volume_cm3: float
    color: List[float]  # [r, g, b] 0-1
    vertices: List[List[float]]  # [[x, y, z], ...]  mm
    faces: List[List[int]]       # [[i, j, k], ...]


class Segment3DResponse(BaseModel):
    success: bool
    meshes: List[OrganMesh]
    total_organs: int
    shape: List[int]
    spacing: List[float]
    origin: List[float]
    elapsed_s: float
    error: str = ""
    available_lesions: List[str] = []  # 可选病灶：["liver", "kidney", "lung"]


def _generate_meshes(seg_arr: np.ndarray, organs: List[OrganInfo], meta: dict, max_organs: int = 20) -> List[OrganMesh]:
    """对 top N 器官生成 marching cubes mesh。

    输出顶点为 [col, row, slice] 像素坐标——前端用 vtk.js indexToWorld() 转换到世界坐标。
    不做任何 spacing 缩放或 IOP 方向旋转，完全交给 vtk.js 处理。
    """
    D, H, W = seg_arr.shape

    # 降采样
    scale = min(1.0, 128.0 / max(D, H, W))
    if scale < 1.0:
        small = zoom(seg_arr.astype(np.float32), scale, order=0).astype(np.uint8)
    else:
        small = seg_arr.astype(np.uint8)
    inv_scale = 1.0 / scale

    sD, sH, sW = small.shape
    print(f"[TotalSeg 3D] downsampled {D}x{H}x{W} → {sD}x{sH}x{sW} (scale={scale:.2f})")

    meshes: List[OrganMesh] = []

    for idx, org in enumerate(organs[:max_organs]):
        label = org.label
        binary = (small == label).astype(np.uint8)
        if int(binary.sum()) < 100:
            continue

        try:
            verts_px, faces, _, _ = marching_cubes(binary, level=0.5,
                spacing=(inv_scale, inv_scale, inv_scale))
            # verts_px: (Z, Y, X) 像素坐标（经 inv_scale 还原为原始像素空间）

            n_verts = len(verts_px)
            # 输出 [col, row, slice] 像素坐标，前端用 vtk.js indexToWorld() 转换
            px_coords = np.zeros((n_verts, 3), dtype=np.float64)
            px_coords[:, 0] = verts_px[:, 2]   # col (X)
            px_coords[:, 1] = verts_px[:, 1]   # row (Y)
            px_coords[:, 2] = verts_px[:, 0]   # slice (Z)

            if len(faces) > 200000:
                keep = np.random.choice(len(faces), 200000, replace=False)
                faces = faces[keep]

            color = ORGAN_COLORS[idx % len(ORGAN_COLORS)]
            meshes.append(OrganMesh(label=label, name=org.name,
                volume_cm3=org.volume_cm3, color=color,
                vertices=px_coords.tolist(), faces=faces.tolist()))
            bx = px_coords.min(axis=0); bX = px_coords.max(axis=0)
            print(f"[TotalSeg 3D] {org.name}: {n_verts}v {len(faces)}f px:[{bx[0]:.0f},{bX[0]:.0f}] [{bx[1]:.0f},{bX[1]:.0f}] [{bx[2]:.0f},{bX[2]:.0f}]")
        except Exception as e:
            print(f"[TotalSeg 3D] skip {org.name}: {e}")

    return meshes


@app.post("/segment_3d", response_model=Segment3DResponse)
def segment_3d(req: SegmentRequest):
    """一键分割 + 生成多器官 3D Mesh，可选 organ_name 过滤"""
    t0 = time.time()
    try:
        series_id = resolve_series_id(req.series_id, req.series_instance_uid)
        seg_arr, organs, elapsed, meta = _run_inference_and_collect_organs(series_id)

        # 如果指定了 organ_name，过滤器官列表
        if req.organ_name:
            matched_labels = match_organs(req.organ_name)
            organs = [o for o in organs if o.label in matched_labels]
            print(f"[TotalSeg 3D] organ_name='{req.organ_name}' → filtered to {len(organs)} organs")

        print(f"[TotalSeg 3D] Generating meshes for top organs...")
        meshes = _generate_meshes(seg_arr, organs, meta)

        # 检测可用病灶类型
        available_lesions = []
        organ_names = [o.name for o in organs]
        if any("liver" in n for n in organ_names):
            available_lesions.append("liver")
        if any("kidney" in n for n in organ_names):
            available_lesions.append("kidney")
        if any("lung" in n for n in organ_names):
            available_lesions.append("lung")
        if available_lesions:
            print(f"[TotalSeg 3D] Lesion detection available for: {available_lesions}")

        total_elapsed = time.time() - t0
        return Segment3DResponse(
            success=True,
            meshes=meshes,
            total_organs=len(meshes),
            shape=list(seg_arr.shape),
            spacing=[meta["spacing"][0], meta["spacing"][1], meta["spacing"][2]],
            origin=[meta["origin"][0], meta["origin"][1], meta["origin"][2]],
            elapsed_s=round(total_elapsed, 1),
            available_lesions=available_lesions,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class BBoxSegmentRequest(BaseModel):
    series_instance_uid: str
    bbox: List[float]          # [x1, y1, x2, y2] 像素坐标
    slice_idx: int


@app.post("/segment_by_bbox", response_model=Segment3DResponse)
def segment_by_bbox(req: BBoxSegmentRequest):
    """框选分割：自动识别 bbox 内器官，仅生成匹配器官的 3D Mesh"""
    t0 = time.time()
    try:
        series_id = resolve_series_id("", req.series_instance_uid)
        seg_arr, all_organs, elapsed, meta = _run_inference_and_collect_organs(series_id)
        D, H, W = seg_arr.shape

        x1 = max(0, min(W-1, int(req.bbox[0])))
        y1 = max(0, min(H-1, int(req.bbox[1])))
        x2 = max(0, min(W-1, int(req.bbox[2])))
        y2 = max(0, min(H-1, int(req.bbox[3])))
        sl = max(0, min(D-1, req.slice_idx))

        bbox_area = seg_arr[sl, y1:y2+1, x1:x2+1]
        labels_in_bbox = np.unique(bbox_area)
        matched_labels = [int(l) for l in labels_in_bbox if l > 0]
        organs = [o for o in all_organs if o.label in matched_labels]
        print(f"[TotalSeg BBOX] [{x1},{y1},{x2},{y2}] s={sl} → {len(organs)} organs: {[o.name for o in organs]}")

        meshes = _generate_meshes(seg_arr, organs, meta) if organs else []
        return Segment3DResponse(
            success=True, meshes=meshes, total_organs=len(meshes),
            shape=list(seg_arr.shape),
            spacing=[meta["spacing"][0], meta["spacing"][1], meta["spacing"][2]],
            origin=[meta["origin"][0], meta["origin"][1], meta["origin"][2]],
            elapsed_s=round(time.time()-t0, 1),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class LesionSegmentRequest(BaseModel):
    series_instance_uid: str
    bbox: List[float]
    slice_idx: int
    organ_hint: str = ""  # 可选：liver/kidney/lung，不传则自动检测


# 器官标签 → 病灶任务映射
ORGAN_LESION_MAP = {
    "liver": "liver_lesions",
    "kidney_right": "kidney_cysts", "kidney_left": "kidney_cysts",
    "lung_upper_lobe_left": "lung_nodules", "lung_lower_lobe_left": "lung_nodules",
    "lung_upper_lobe_right": "lung_nodules", "lung_middle_lobe_right": "lung_nodules",
    "lung_lower_lobe_right": "lung_nodules",
}


@app.post("/segment_lesion", response_model=Segment3DResponse)
def segment_lesion(req: LesionSegmentRequest):
    """病灶分割：框选/涂抹区域自动检测所属器官，运行对应病灶模型"""
    t0 = time.time()
    try:
        series_id = resolve_series_id("", req.series_instance_uid)
        seg_arr, all_organs, _, meta = _run_inference_and_collect_organs(series_id)
        D, H, W = seg_arr.shape

        x1 = max(0, min(W-1, int(req.bbox[0])))
        y1 = max(0, min(H-1, int(req.bbox[1])))
        x2 = max(0, min(W-1, int(req.bbox[2])))
        y2 = max(0, min(H-1, int(req.bbox[3])))
        sl = max(0, min(D-1, req.slice_idx))

        # 自动识别器官
        bbox_area = seg_arr[sl, y1:y2+1, x1:x2+1]
        labels_in_bbox = np.unique(bbox_area)
        organ_names_in_bbox = [LABEL_MAP.get(int(l), f"unknown_{l}") for l in labels_in_bbox if l > 0]

        if req.organ_hint:
            organ_names_in_bbox = [n for n in organ_names_in_bbox if req.organ_hint.lower() in n.lower()]

        lesion_task = None
        for name in organ_names_in_bbox:
            if name in ORGAN_LESION_MAP:
                lesion_task = ORGAN_LESION_MAP[name]
                print(f"[TotalSeg LESION] organ={name} → task={lesion_task}")
                break

        if not lesion_task:
            return Segment3DResponse(
                success=True, meshes=[], total_organs=0,
                shape=list(seg_arr.shape),
                spacing=[meta["spacing"][0], meta["spacing"][1], meta["spacing"][2]],
                origin=[meta["origin"][0], meta["origin"][1], meta["origin"][2]],
                elapsed_s=round(time.time()-t0, 1),
                error=f"No lesion model for organs: {organ_names_in_bbox}"
            )

        # 读 DICOM → NIfTI → Docker 病灶推理（病灶模型内存更敏感，降到 200 切片）
        volume, _ = load_dicom_series(series_id)
        original_z = volume.shape[0]
        if volume.shape[0] > 200:
            print(f"[TotalSeg LESION] Downsampling {volume.shape[0]}→200 slices for lesion task")
            volume = zoom(volume.astype(np.float32), (200.0/volume.shape[0], 1.0, 1.0), order=1).astype(np.int16)
        output_dir = tempfile.mkdtemp()
        nii_path = os.path.join(output_dir, "input.nii.gz")
        nib.save(nib.Nifti1Image(volume.astype(np.int16), np.eye(4)), nii_path)

        print(f"[TotalSeg LESION] Running {lesion_task} via Docker...")
        lesion_img = _docker_totalseg(nii_path, os.path.join(output_dir, "seg"), task=lesion_task, fast=False)
        lesion_arr = lesion_img.get_fdata().astype(np.int16)
        # 清理临时目录
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except:
            pass

        # 病灶模型的器官标签=1
        lesion_labels = np.unique(lesion_arr)
        lesion_labels = [int(l) for l in lesion_labels if l > 0]

        lesion_organs = []
        for lbl in lesion_labels:
            count = int((lesion_arr == lbl).sum())
            if count > 50:
                sx, sy, dz = meta["spacing"]
                vol_cm3 = count * sx * sy * dz / 1000.0
                lesion_organs.append(OrganInfo(label=lbl, name=f"lesion_{lbl}", voxels=count, volume_cm3=round(vol_cm3, 1)))

        meshes = _generate_meshes(lesion_arr, lesion_organs, meta) if lesion_organs else []
        # Z 缩放回原始空间
        z_factor = original_z / max(lesion_arr.shape[0], 1)
        if abs(z_factor - 1.0) > 0.01:
            for m in meshes:
                for v in m.vertices:
                    v[2] *= z_factor
        return Segment3DResponse(
            success=True, meshes=meshes, total_organs=len(meshes),
            shape=list(lesion_arr.shape),
            spacing=[meta["spacing"][0], meta["spacing"][1], meta["spacing"][2]],
            origin=[meta["origin"][0], meta["origin"][1], meta["origin"][2]],
            elapsed_s=round(time.time()-t0, 1),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── 智能病灶分析 + 一键分割 ──

class LesionAnalysisRequest(BaseModel):
    organs: List[dict] = []  # [{name, volume_cm3, label}]
    available_lesions: List[str] = []  # ["liver", "kidney", "lung"]


class LesionAnalysisResponse(BaseModel):
    success: bool
    analysis: str = ""  # LLM 分析文本
    suspicious_organs: List[str] = []  # LLM 认为可疑的器官名
    elapsed_s: float = 0


@app.post("/analyze_lesions", response_model=LesionAnalysisResponse)
def analyze_lesions(req: LesionAnalysisRequest):
    """LLM 分析哪些器官体积异常、可能有病灶"""
    t0 = time.time()
    try:
        if not req.available_lesions:
            return LesionAnalysisResponse(success=True, analysis="No lesion models available for detected organs.", suspicious_organs=[], elapsed_s=0)

        lines = "\n".join(f"- {o['name']}: {o.get('volume_cm3','?')} cm³" for o in req.organs[:30])
        lesion_opts = ", ".join(req.available_lesions)

        prompt = f"""Analyze the following organ volumes from a CT scan and determine which organs likely contain lesions requiring further investigation. You are a radiologist.

ORGAN VOLUMES:
{lines}

AVAILABLE LESION DETECTION MODELS: {lesion_opts}

Be concise. For each suspicious organ, state the finding in one sentence. Normal ranges:
- Liver: 1200-1600 cm³
- Spleen: 150-200 cm³
- Kidneys: 130-200 cm³ each
- Pancreas: 60-100 cm³

Return your response in this EXACT format:
SUSPICIOUS: organ1, organ2, ...
ANALYSIS: (1-2 sentences per suspicious organ explaining why)"""

        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a radiologist. Be concise. Only flag organs if volumes are clearly abnormal."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 500,
        }

        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )

        if resp.status_code != 200:
            return LesionAnalysisResponse(success=False, analysis=f"LLM error: {resp.status_code}", suspicious_organs=[], elapsed_s=round(time.time()-t0,1))

        text = resp.json()["choices"][0]["message"]["content"]
        print(f"[TotalSeg ANALYZE] LLM response: {text[:200]}...")

        # 解析 SUSPICIOUS 行
        suspicious = []
        for line in text.split("\n"):
            if line.upper().startswith("SUSPICIOUS:"):
                parts = line.split(":", 1)[1].strip()
                suspicious = [s.strip().lower() for s in parts.split(",") if s.strip()]
                break

        # 只保留我们有病灶模型的器官
        suspicious = [s for s in suspicious if s in req.available_lesions]

        return LesionAnalysisResponse(
            success=True,
            analysis=text.strip(),
            suspicious_organs=suspicious,
            elapsed_s=round(time.time()-t0, 1),
        )
    except Exception as e:
        traceback.print_exc()
        return LesionAnalysisResponse(success=False, analysis=str(e), suspicious_organs=[], elapsed_s=round(time.time()-t0,1))


class LesionByOrganRequest(BaseModel):
    series_instance_uid: str
    organ_name: str  # "liver", "kidney", "lung"


@app.post("/segment_lesion_by_organ", response_model=Segment3DResponse)
def segment_lesion_by_organ(req: LesionByOrganRequest):
    """一键病灶分割：指定器官名 → 自动定位 → 分割病灶"""
    t0 = time.time()
    try:
        series_id = resolve_series_id("", req.series_instance_uid)
        seg_arr, all_organs, _, meta = _run_inference_and_collect_organs(series_id)

        # 找到器官对应的标签
        organ_label = None
        for o in all_organs:
            if req.organ_name.lower() in o.name.lower():
                organ_label = o.label
                print(f"[TotalSeg LESION-BY-ORGAN] Found {o.name} (label={organ_label})")
                break

        if organ_label is None:
            raise HTTPException(status_code=404, detail=f"Organ '{req.organ_name}' not found in segmentation")

        # 映射到病灶任务（直接用请求的 organ_name）
        lesion_task = None
        org_lower = req.organ_name.lower()
        if "liver" in org_lower:
            lesion_task = "liver_lesions"
        elif "kidney" in org_lower:
            lesion_task = "kidney_cysts"
        elif "lung" in org_lower:
            lesion_task = "lung_nodules"

        if not lesion_task:
            raise HTTPException(status_code=400, detail=f"No lesion model for '{req.organ_name}'")

        # ── 病灶缓存 ──
        cache_key = (series_id, org_lower)
        if cache_key in _lesion_cache:
            lesion_arr, lesion_organs, cache_meta, orig_z = _lesion_cache[cache_key]
            print(f"[TotalSeg LESION-BY-ORGAN] Cache hit for {org_lower}, {len(lesion_organs)} lesions")
            meshes = _generate_meshes(lesion_arr, lesion_organs, cache_meta) if lesion_organs else []
            z_factor = orig_z / max(lesion_arr.shape[0], 1)
            if abs(z_factor - 1.0) > 0.01:
                for m in meshes:
                    for v in m.vertices:
                        v[2] *= z_factor
            return Segment3DResponse(success=True, meshes=meshes, total_organs=len(meshes),
                shape=list(lesion_arr.shape),
                spacing=[cache_meta["spacing"][0], cache_meta["spacing"][1], cache_meta["spacing"][2]],
                origin=[cache_meta["origin"][0], cache_meta["origin"][1], cache_meta["origin"][2]],
                elapsed_s=round(time.time()-t0, 1))

        # 运行病灶推理（病灶模型小，fast=False 即可，但大体积需降采样）
        volume, _ = load_dicom_series(series_id)
        original_z = volume.shape[0]  # 记录原始 Z 维度，后续缩放 mesh 用
        if volume.shape[0] > 200:
            print(f"[TotalSeg LESION-BY-ORGAN] Downsampling {volume.shape[0]}→200 slices")
            volume = zoom(volume.astype(np.float32), (200.0/volume.shape[0], 1.0, 1.0), order=1).astype(np.int16)

        output_dir = tempfile.mkdtemp()
        nii_path = os.path.join(output_dir, "input.nii.gz")
        nib.save(nib.Nifti1Image(volume.astype(np.int16), np.eye(4)), nii_path)

        print(f"[TotalSeg LESION-BY-ORGAN] Running {lesion_task} (fast=False)...")
        lesion_img = _docker_totalseg(nii_path, os.path.join(output_dir, "seg"), task=lesion_task, fast=False)
        lesion_arr = lesion_img.get_fdata().astype(np.int16)

        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except:
            pass

        lesion_labels = [int(l) for l in np.unique(lesion_arr) if l > 0]
        lesion_organs = []
        for lbl in lesion_labels:
            count = int((lesion_arr == lbl).sum())
            if count > 50:
                sx, sy, dz = meta["spacing"]
                vol_cm3 = count * sx * sy * dz / 1000.0
                lesion_organs.append(OrganInfo(label=lbl, name=f"{req.organ_name}_lesion_{lbl}", voxels=count, volume_cm3=round(vol_cm3, 1)))

        _lesion_cache[cache_key] = (lesion_arr, lesion_organs, meta, original_z)
        gc.collect()

        meshes = _generate_meshes(lesion_arr, lesion_organs, meta) if lesion_organs else []
        z_factor = original_z / lesion_arr.shape[0] if lesion_arr.shape[0] > 0 else 1.0
        if abs(z_factor - 1.0) > 0.01:
            for m in meshes:
                for v in m.vertices:
                    v[2] *= z_factor
            print(f"[TotalSeg LESION-BY-ORGAN] Scaled mesh Z back to original (×{z_factor:.1f})")
        return Segment3DResponse(
            success=True, meshes=meshes, total_organs=len(meshes),
            shape=list(lesion_arr.shape),
            spacing=[meta["spacing"][0], meta["spacing"][1], meta["spacing"][2]],
            origin=[meta["origin"][0], meta["origin"][1], meta["origin"][2]],
            elapsed_s=round(time.time()-t0, 1),
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── 报告生成 ──
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY = os.getenv("GROQ_API_KEY", "")


class ReportRequest(BaseModel):
    organs: List[dict] = []          # [{name, volume_cm3, label}, ...]
    lesions: List[dict] = []         # [{name, volume_cm3, label}, ...]
    patient_age: int = 0
    patient_gender: str = ""         # Male / Female / Other
    chief_complaint: str = ""
    clinical_question: str = ""
    medical_history: str = ""
    modality: str = "CT"
    screenshot_base64: str = ""      # optional 3D screenshot


class ReportResponse(BaseModel):
    success: bool
    report: str = ""
    elapsed_s: float = 0
    error: str = ""


@app.post("/generate_report", response_model=ReportResponse)
def generate_report(req: ReportRequest):
    """生成放射诊断报告：TotalSegmentator 结果 + 临床信息 → Groq LLM"""
    t0 = time.time()
    try:
        # 组装器官摘要
        organ_lines = ""
        for o in req.organs:
            organ_lines += f"- {o.get('name','unknown')}: {o.get('volume_cm3','?')} cm³\n"
        if not organ_lines:
            organ_lines = "(no organ data provided)\n"

        lesion_lines = ""
        for l in req.lesions:
            lesion_lines += f"- {l.get('name','lesion')}: {l.get('volume_cm3','?')} cm³\n"
        if not lesion_lines:
            lesion_lines = "(no lesions detected)\n"

        gender_str = req.patient_gender or "Not specified"
        age_str = f"{req.patient_age} years" if req.patient_age else "Not specified"

        prompt = f"""You are a board-certified radiologist with 20 years of experience. Generate a COMPREHENSIVE diagnostic radiology report in English only.

PATIENT INFORMATION:
- Age: {age_str}
- Gender: {gender_str}
- Modality: {req.modality}

CLINICAL CONTEXT:
- Chief Complaint: {req.chief_complaint or 'Not provided'}
- Clinical Question: {req.clinical_question or 'Not provided'}
- Medical History: {req.medical_history or 'Not provided'}

QUANTITATIVE FINDINGS (from AI segmentation):
Organs segmented:
{organ_lines}
Lesions detected:
{lesion_lines}

Generate a detailed radiology report with ALL of the following sections in English. Write at least 300 words. Reference the actual numbers provided above.

## CLINICAL HISTORY
Summarize the patient's clinical context in 2-3 sentences using professional radiological language.

## FINDINGS
Write 5-8 sentences covering:
- Each organ's volume and whether it falls within normal range (liver ~1200-1600 cm³, spleen ~150-200 cm³, kidneys ~130-200 cm³ each)
- For each lesion: precise anatomical location, size, margins, internal characteristics
- Relationship to adjacent structures
- Any incidental findings worth noting

## IMPRESSION
Provide 2-4 differential diagnoses ranked by likelihood:
1. **Most likely** — with 2-3 sentence justification
2. **Alternative** — with reasoning
3. **Additional possibility** — with clinical context
Reference clinical guidelines where appropriate (LI-RADS for liver, Bosniak for renal, Fleischner for lung).

## RECOMMENDATIONS
5-8 specific, actionable recommendations:
- Follow-up imaging interval and modality
- Biopsy indication if warranted
- Relevant laboratory tests (tumor markers, LFTs, etc.)
- Multidisciplinary team discussion
- Reference relevant clinical guidelines
- Lifestyle or medical management suggestions

IMPORTANT: Output in English only. Be specific and reference the actual numbers. Make the report clinically useful."""

        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a board-certified radiologist. Write comprehensive, clinically actionable diagnostic reports in English. Be thorough — at least 300 words. Reference quantitative data precisely. Provide specific differential diagnoses with clinical reasoning."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 3000,
        }

        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )

        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"]
            return ReportResponse(
                success=True, report=text.strip(),
                elapsed_s=round(time.time() - t0, 1),
            )
        else:
            return ReportResponse(
                success=False,
                error=f"Groq API error {resp.status_code}: {resp.text[:300]}",
                elapsed_s=round(time.time() - t0, 1),
            )

    except Exception as e:
        traceback.print_exc()
        return ReportResponse(success=False, error=str(e), elapsed_s=round(time.time() - t0, 1))


def health():
    return {"status": "ok", "service": "totalsegmentator"}


if __name__ == "__main__":
    multiprocessing.freeze_support()
    port = int(os.environ.get("TOTALSEG_PORT", 8004))
    print(f"Starting TotalSegmentator service on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
