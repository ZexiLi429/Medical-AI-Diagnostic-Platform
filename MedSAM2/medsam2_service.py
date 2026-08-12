"""
MedSAM2 FastAPI Service  —  SAM-2 三维全序列追踪
端口: 8003

功能：
  - 接收 SeriesInstanceUID，从 Orthanc 拉取整个 CT 系列
  - 在指定关键帧上施加 bbox prompt
  - 用 SAM-2 向前后传播，生成全系列 3D 分割
  - 返回每个切片的 RLE 掩码 + 总体积 (mm³)

模型文件下载（选一个）：
  cd checkpoints && bash ../download.sh
  推荐: MedSAM2_latest.pt  (~300MB)
  CT病灶专用: MedSAM2_CTLesion.pt

配置文件: sam2/configs/sam2.1_hiera_t512.yaml (已存在)
"""

import os, sys, io, uuid, threading, time, asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import requests as http_requests
from PIL import Image
import cv2

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Agent 导入 ──────────────────────────────────────────────────────────
from analyze_agent import AnalyzeAgent, LesionMetrics, run_analyze
from report_agent import ReportAgent, generate_report as _generate_report_internal
from evaluate_agent import EvaluateAgent, run_evaluate

# ─── 路径配置 ────────────────────────────────────────────────────────────────
SERVICE_DIR  = Path(__file__).parent
CHECKPOINT   = SERVICE_DIR / "checkpoints" / "MedSAM2_latest.pt"
ALT_CKPT     = SERVICE_DIR / "checkpoints" / "MedSAM2_CTLesion.pt"  # 备选
MODEL_CFG    = "configs/sam2.1_hiera_t512.yaml"                       # 相对于 sam2 包

# SAM2 包路径
sys.path.insert(0, str(SERVICE_DIR))

# ─── GCP 凭证（Med-PaLM 2 需要）─────────────────────────────────────────
GCP_KEY_PATH = SERVICE_DIR.parent / "medsam-key.json"
if GCP_KEY_PATH.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(GCP_KEY_PATH)
    print(f"[MedSAM2] GCP credentials loaded from {GCP_KEY_PATH}")
else:
    print("[MedSAM2] GCP key not found — report will use template fallback")

device = "cuda" if torch.cuda.is_available() else "cpu"
IMAGE_SIZE = 512   # MedSAM2 默认 512×512

# ─── 全局 ────────────────────────────────────────────────────────────────────
predictor = None          # SAM2 video predictor
_model_lock = threading.Lock()

# ─── 会话存储（用于多步骤API）────────────────────────────────────────────────
_sessions: Dict[str, Dict] = {}
_session_lock = threading.Lock()

# ─── 线程池（推理不阻塞事件循环）─────────────────────────────────────────────
_inference_executor = ThreadPoolExecutor(max_workers=1)


def _find_checkpoint() -> Optional[Path]:
    """按优先级查找可用模型文件"""
    for p in [CHECKPOINT, ALT_CKPT]:
        if p.exists() and p.stat().st_size > 1024 * 1024:  # >1MB
            return p
    # 搜索 checkpoints 目录下任何 .pt 文件
    for p in (SERVICE_DIR / "checkpoints").glob("*.pt"):
        if p.stat().st_size > 1024 * 1024:
            return p
    return None


def load_predictor():
    """加载 SAM2 video predictor"""
    global predictor
    ckpt = _find_checkpoint()
    if ckpt is None:
        print("=" * 60)
        print("[MedSAM2] ⚠️  模型文件未找到！")
        print("[MedSAM2] 请运行以下命令下载模型（约 300MB）：")
        print(f"[MedSAM2]   cd {SERVICE_DIR / 'checkpoints'}")
        print("[MedSAM2]   # Windows 用 curl：")
        print("[MedSAM2]   curl -L -o MedSAM2_latest.pt 'https://huggingface.co/bowang-lab/MedSAM2/resolve/main/MedSAM2_latest.pt'")
        print("[MedSAM2] 下载后重启本服务")
        print("=" * 60)
        return False

    print(f"[MedSAM2] 加载模型: {ckpt.name}  (device={device})")
    try:
        from sam2.build_sam import build_sam2_video_predictor_npz
        with _model_lock:
            predictor = build_sam2_video_predictor_npz(MODEL_CFG, str(ckpt))
        print(f"[MedSAM2] ✅ 模型就绪")
        return True
    except Exception as e:
        print(f"[MedSAM2] ❌ 模型加载失败: {e}")
        print("[MedSAM2] 请确认已安装 sam2 包：pip install -e .")
        return False


def resize_to_rgb_512(arr_3d: np.ndarray, size: int = 512) -> np.ndarray:
    """
    将 (D, H, W) uint8 灰度序列转为 (D, 3, size, size) float 归一化张量
    """
    D = arr_3d.shape[0]
    out = np.zeros((D, 3, size, size), dtype=np.float32)
    img_mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    img_std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    for i in range(D):
        pil = Image.fromarray(arr_3d[i]).convert("RGB").resize((size, size))
        rgb = np.array(pil).astype(np.float32) / 255.0   # (H,W,3)
        rgb = (rgb - img_mean) / img_std                  # normalize
        out[i] = rgb.transpose(2, 0, 1)                   # (3,H,W)
    return out


def encode_rle(mask: np.ndarray) -> dict:
    """二值掩码 → RLE"""
    flat = mask.flatten().astype(np.uint8)
    changes = np.diff(flat, prepend=flat[0] ^ 1)
    change_idx = np.where(changes != 0)[0]
    counts = np.diff(np.append(change_idx, len(flat))).tolist()
    return {
        "counts": counts,
        "starts_with": int(flat[0]),
        "width": int(mask.shape[1]),
        "height": int(mask.shape[0]),
        "pixel_count": int(np.sum(flat)),
    }


def fetch_series_from_orthanc(
    series_uid: str,
    orthanc_url: str = "http://localhost:8042",
    auth: tuple = ("orthanc", "orthanc"),
) -> tuple:
    """
    从 Orthanc 拉取整个系列的所有切片，按 InstanceNumber 排序。
    返回 (images_np: np.ndarray (D,H,W) uint8, pixel_spacing: [row, col], slice_thickness: float,
          image_origin: [x,y,z], image_direction: [[rx,cx,xx],[ry,cy,xy],[rz,cz,xz]] row-major 3x3)
    """
    # 1. 找到系列
    find_resp = http_requests.post(
        f"{orthanc_url}/tools/find",
        auth=auth,
        json={"Level": "Series", "Query": {"SeriesInstanceUID": series_uid}},
        timeout=10,
    )
    find_resp.raise_for_status()
    series_ids = find_resp.json()
    if not series_ids:
        raise ValueError(f"SeriesInstanceUID {series_uid} not found in Orthanc")
    series_id = series_ids[0]

    # 2. 获取所有 instances
    instances_resp = http_requests.get(
        f"{orthanc_url}/series/{series_id}",
        auth=auth, timeout=10
    )
    instances_resp.raise_for_status()
    series_data = instances_resp.json()
    instance_ids = series_data.get("Instances", [])
    if not instance_ids:
        raise ValueError(f"Series {series_uid} has no instances")

    # 3. 获取每个 instance 的 InstanceNumber 用于排序，同时提取 DICOM 空间元数据
    inst_list = []
    pixel_spacing = [1.0, 1.0]
    slice_thickness = 1.0
    image_origin = [0.0, 0.0, 0.0]
    image_direction = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]  # row-major 3x3

    def _parse_dicom_list(val):
        """Orthanc simplified-tags 返回字符串 'a\b\c' 或已解析的 list"""
        if isinstance(val, list):
            return [float(x) for x in val]
        if isinstance(val, str) and "\\" in val:
            return [float(x) for x in val.split("\\")]
        if isinstance(val, str) and val.replace(".","").replace("-","").isdigit():
            return [float(val)]
        return None

    for inst_id in instance_ids:
        try:
            tags = http_requests.get(
                f"{orthanc_url}/instances/{inst_id}/simplified-tags",
                auth=auth, timeout=10
            ).json()
            inst_num = int(tags.get("InstanceNumber", 9999))

            if pixel_spacing == [1.0, 1.0]:
                ps = _parse_dicom_list(tags.get("PixelSpacing") or tags.get("ImagerPixelSpacing"))
                if ps and len(ps) >= 2:
                    pixel_spacing = [ps[0], ps[1]]

            if slice_thickness == 1.0:
                st = tags.get("SliceThickness")
                if st is not None:
                    try: slice_thickness = float(st)
                    except: pass

            if image_origin == [0.0, 0.0, 0.0]:
                ipp = _parse_dicom_list(tags.get("ImagePositionPatient"))
                if ipp and len(ipp) >= 3:
                    image_origin = [ipp[0], ipp[1], ipp[2]]

            if image_direction == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]:
                iop = _parse_dicom_list(tags.get("ImageOrientationPatient"))
                if iop and len(iop) >= 6:
                    import numpy as _np
                    row_vec = _np.array([iop[0], iop[1], iop[2]])
                    col_vec = _np.array([iop[3], iop[4], iop[5]])
                    normal = _np.cross(row_vec, col_vec)
                    image_direction = [
                        [float(iop[0]), float(iop[1]), float(iop[2])],
                        [float(iop[3]), float(iop[4]), float(iop[5])],
                        [float(normal[0]), float(normal[1]), float(normal[2])],
                    ]

            inst_list.append((inst_num, inst_id))
        except Exception:
            inst_list.append((9999, inst_id))

    inst_list.sort(key=lambda x: x[0])

    # 4. 下载渲染图
    slices = []
    orig_hw = None
    for _, inst_id in inst_list:
        try:
            resp = http_requests.get(
                f"{orthanc_url}/instances/{inst_id}/rendered",
                auth=auth, params={"quality": 95}, timeout=30
            )
            resp.raise_for_status()
            img = np.array(Image.open(io.BytesIO(resp.content)).convert("L"))  # grayscale
            if orig_hw is None:
                orig_hw = img.shape
            slices.append(img)
        except Exception as e:
            print(f"[MedSAM2] 跳过 instance {inst_id}: {e}")

    if not slices:
        raise ValueError("Failed to download any slices from Orthanc")

    images_np = np.stack(slices, axis=0)  # (D, H, W)
    print(f"[MedSAM2] 加载系列: {len(slices)} 切片, shape={images_np.shape}, ps={pixel_spacing}, origin={image_origin}")
    return images_np, pixel_spacing, slice_thickness, image_origin, image_direction


# ─── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(title="MedSAM2 3D Tracking Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    load_predictor()


@app.get("/health")
async def health():
    ckpt = _find_checkpoint()
    return JSONResponse({
        "status": "ok" if predictor is not None else "no_model",
        "model_loaded": predictor is not None,
        "checkpoint": str(ckpt) if ckpt else "not found",
        "device": device,
    })


# ─── 全局（image predictor 用于单张 2D 分割）──────────────────────────────────
image_predictor = None    # SAM2ImagePredictor 实例

# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class SegmentSliceRequest(BaseModel):
    sop_instance_uid: str
    bbox: List[int]              # [x1, y1, x2, y2] 像素坐标
    points: Optional[List[List[float]]] = None
    labels: Optional[List[int]] = None
    mask_rle: Optional[Dict[str, Any]] = None   # SAM mask prompt（当前暂不使用）
    clip_rle: Optional[Dict[str, Any]] = None   # 裁剪掩码，结果必须在这个范围内
    orthanc_url: str = "http://localhost:8042"
    orthanc_user: str = "orthanc"
    orthanc_password: str = "orthanc"

class CreateSessionRequest(BaseModel):
    series_instance_uid: str
    orthanc_url: str = "http://localhost:8042"
    orthanc_user: str = "orthanc"
    orthanc_password: str = "orthanc"
    organ_hint: Optional[str] = None
    prompt_frames: Optional[List[Dict[str, Any]]] = None


class SegmentRequest(BaseModel):
    key_slice_idx: int          # 关键帧索引（从0开始）
    bbox: List[int]             # [x1, y1, x2, y2]，像素坐标（相对于原始图像）
    organ_hint: Optional[str] = None
    prompt_frames: Optional[List[Dict[str, Any]]] = None
    preview_confirmed: bool = False


def _apply_organ_roi_hint_to_bbox(
    bbox: List[int],
    organ_hint: Optional[str],
    width: int,
    height: int,
) -> List[int]:
    if not organ_hint:
        return bbox

    x1, y1, x2, y2 = bbox
    hint = organ_hint.lower()

    # Heuristic ROI constraints to reduce blind segmentation region.
    if hint in {"left_lung", "lung_l", "left lung"}:
        roi = [0, 0, width // 2, height]
    elif hint in {"right_lung", "lung_r", "right lung"}:
        roi = [width // 2, 0, width, height]
    elif hint in {"liver"}:
        roi = [int(width * 0.35), int(height * 0.35), width, height]
    elif hint in {"spleen"}:
        roi = [0, int(height * 0.3), int(width * 0.65), height]
    elif hint in {"kidney"}:
        roi = [int(width * 0.1), int(height * 0.25), int(width * 0.9), int(height * 0.9)]
    else:
        return bbox

    rx1, ry1, rx2, ry2 = roi
    cx1 = max(x1, rx1)
    cy1 = max(y1, ry1)
    cx2 = min(x2, rx2)
    cy2 = min(y2, ry2)

    # If clipping degenerates bbox, keep original bbox to avoid invalid prompts.
    if cx2 <= cx1 or cy2 <= cy1:
        return bbox
    return [cx1, cy1, cx2, cy2]


# ─── API 端点 ─────────────────────────────────────────────────────────────────

@app.post("/segment_dicom")
async def segment_single_slice(req: SegmentSliceRequest):
    """
    单张 DICOM 切片分割（使用 SAM2ImagePredictor，精度远高于 LiteMedSAM）。
    """
    global image_predictor

    if image_predictor is None:
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        from sam2.build_sam import build_sam2
        ckpt = _find_checkpoint()
        if ckpt is None:
            return JSONResponse({"success": False, "error": "模型未找到"}, status_code=503)
        print(f"[MedSAM2] loading SAM2ImagePredictor: {ckpt.name}")
        sam2_model = build_sam2(MODEL_CFG, str(ckpt), device=device)
        image_predictor = SAM2ImagePredictor(sam2_model)
        print("[MedSAM2] SAM2ImagePredictor ready")

    try:
        auth = (req.orthanc_user, req.orthanc_password)
        find_resp = http_requests.post(
            f"{req.orthanc_url}/tools/find", auth=auth,
            json={"Level": "Instance", "Query": {"SOPInstanceUID": req.sop_instance_uid}}, timeout=10)
        find_resp.raise_for_status()
        ids = find_resp.json()
        if not ids:
            raise HTTPException(status_code=404, detail="SOPInstanceUID not found")
        orthanc_id = ids[0]

        pixel_spacing = [1.0, 1.0]
        try:
            tags = http_requests.get(f"{req.orthanc_url}/instances/{orthanc_id}/simplified-tags", auth=auth, timeout=10).json()
            ps = tags.get("PixelSpacing") or tags.get("ImagerPixelSpacing")
            if ps and len(ps) >= 2: pixel_spacing = [float(ps[0]), float(ps[1])]
        except: pass

        img_resp = http_requests.get(f"{req.orthanc_url}/instances/{orthanc_id}/rendered", auth=auth, params={"quality": 100}, timeout=30)
        img_resp.raise_for_status()
        img_np = np.array(Image.open(io.BytesIO(img_resp.content)).convert("RGB"))
        H, W = img_np.shape[:2]

        x1, y1, x2, y2 = req.bbox
        x1, x2 = max(0, min(x1, W-1)), max(1, min(x2, W))
        y1, y2 = max(0, min(y1, H-1)), max(1, min(y2, H))
        print(f"[MedSAM2 seg] uid={req.sop_instance_uid[:12]}… bbox=[{x1},{y1},{x2},{y2}] img={W}x{H}")

        image_predictor.set_image(img_np)
        box_xyxy = np.array([x1, y1, x2, y2], dtype=np.float32)

        # 只用 bbox，让 SAM2 自己找器官边界（不用 mask prompt）
        masks, scores, _ = image_predictor.predict(
            point_coords=None, point_labels=None,
            box=box_xyxy, mask_input=None, multimask_output=True)
        best = int(np.argmax(scores))
        mask = (masks[best] > 0.5).astype(np.uint8)
        confidence = float(scores[best])
        print(f"[MedSAM2 seg] SAM raw: pixels={int(mask.sum())}, conf={confidence:.3f}")

        # 裁剪：用刷子掩码裁剪 SAM 结果，结果必在刷子范围内
        clip_src = req.clip_rle if hasattr(req, 'clip_rle') and req.clip_rle else req.mask_rle
        if clip_src:
            mr = clip_src
            total_b = mr["width"] * mr["height"]
            brush_flat = np.zeros(total_b, dtype=np.uint8)
            bidx, bcv = 0, mr["starts_with"]
            for cnt in mr["counts"]:
                if bcv == 1: brush_flat[bidx:bidx+cnt] = 1
                bidx += cnt; bcv = 1 - bcv
            brush_full = brush_flat.reshape((mr["height"], mr["width"]))
            if brush_full.shape != mask.shape:
                brush_full = cv2.resize(brush_full.astype(np.float32), (mask.shape[1], mask.shape[0]),
                                        interpolation=cv2.INTER_NEAREST).astype(np.uint8)
            mask = (mask & brush_full).astype(np.uint8)
            print(f"[MedSAM2 seg] after clip: pixels={int(mask.sum())}")
        px = int(np.sum(mask))
        vol = round(px * pixel_spacing[0] * pixel_spacing[1], 2)
        rle = encode_rle(mask)
        print(f"[MedSAM2 seg] Done: pixels={px}, conf={confidence:.3f}")

        return JSONResponse({"success": True, "rle": rle, "volume_mm3": vol,
            "pixel_spacing": pixel_spacing, "confidence": confidence,
            "shape": {"width": W, "height": H}, "model": "medsam2"})
    except HTTPException: raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/session/create")
async def create_session(req: CreateSessionRequest):
    """
    加载整个 CT 系列到内存，返回 session_id。
    后续调用 /session/{id}/segment 执行 3D 追踪。
    """
    if predictor is None:
        ckpt = _find_checkpoint()
        if ckpt is None:
            raise HTTPException(
                status_code=503,
                detail="MedSAM2 模型未加载。请先下载模型文件：\n"
                       "curl -L -o MedSAM2/checkpoints/MedSAM2_latest.pt "
                       "'https://huggingface.co/bowang-lab/MedSAM2/resolve/main/MedSAM2_latest.pt'\n"
                       "然后重启 medsam2_service.py"
            )
        load_predictor()
        if predictor is None:
            raise HTTPException(status_code=503, detail="模型加载失败，请检查日志")

    try:
        auth = (req.orthanc_user, req.orthanc_password)
        images_np, pixel_spacing, slice_thickness, image_origin, image_direction = fetch_series_from_orthanc(
            req.series_instance_uid, req.orthanc_url, auth
        )

        # 预处理：归一化到 [0, 255] uint8
        lo, hi = float(images_np.min()), float(images_np.max())
        if hi > lo:
            images_uint8 = ((images_np.astype(np.float32) - lo) / (hi - lo) * 255).astype(np.uint8)
        else:
            images_uint8 = images_np.astype(np.uint8)

        session_id = uuid.uuid4().hex
        with _session_lock:
            _sessions[session_id] = {
                "images_uint8": images_uint8,
                "orig_hw": images_uint8.shape[1:],   # (H, W)
                "pixel_spacing": pixel_spacing,
                "slice_thickness": slice_thickness,
                "image_origin": image_origin,
                "image_direction": image_direction,
                "series_uid": req.series_instance_uid,
                "organ_hint": req.organ_hint,
                "prompt_frames": req.prompt_frames or [],
                "created_at": time.time(),
                "progress": {"current": 0, "total": len(images_uint8), "phase": "idle"},
            }

        return JSONResponse({
            "success": True,
            "session_id": session_id,
            "slice_count": len(images_uint8),
            "shape": list(images_uint8.shape),
            "pixel_spacing": pixel_spacing,
            "slice_thickness": slice_thickness,
            "organ_hint": req.organ_hint,
            "prompt_frames_count": len(req.prompt_frames or []),
        })

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/session/{session_id}/progress")
async def get_progress(session_id: str):
    """查询 3D 传播进度（供前端轮询）"""
    with _session_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return JSONResponse(session.get("progress", {"current": 0, "total": 0, "phase": "unknown"}))


@app.post("/session/{session_id}/segment")
async def segment_3d(session_id: str, req: SegmentRequest):
    """
    在关键帧施加 prompt，向前后传播生成完整 3D 分割。
    推理在线程池中执行，不阻塞事件循环 → 前端实时轮询进度。
    """
    with _session_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found or expired")

    if predictor is None:
        raise HTTPException(status_code=503, detail="模型未加载")

    # 在线程池中运行推理，保持事件循环可响应 progress 请求
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _inference_executor,
            _run_segment_inference,
            session_id, req, session,
        )
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _run_segment_inference(session_id: str, req: SegmentRequest, session: Dict) -> Dict:
    """在后台线程中执行的同步推理函数"""
    try:
        images_uint8  = session["images_uint8"]   # (D, H, W)
        orig_hw       = session["orig_hw"]         # (H, W)
        pixel_spacing = session["pixel_spacing"]
        slice_thickness = session["slice_thickness"]
        image_origin  = session.get("image_origin", [0.0, 0.0, 0.0])
        image_direction = session.get("image_direction", [[1,0,0],[0,1,0],[0,0,1]])
        D, H, W = images_uint8.shape

        key_idx = max(0, min(req.key_slice_idx, D - 1))
        organ_hint = req.organ_hint or session.get("organ_hint")

        # bbox 缩放到 IMAGE_SIZE 坐标系
        seed_bbox = _apply_organ_roi_hint_to_bbox(req.bbox, organ_hint, W, H)
        sx = IMAGE_SIZE / W
        sy = IMAGE_SIZE / H

        def _scale_bbox_to_512(box: List[int]) -> np.ndarray:
            x1, y1, x2, y2 = box
            return np.array([
                max(0, int(x1 * sx)), max(0, int(y1 * sy)),
                min(IMAGE_SIZE, int(x2 * sx)), min(IMAGE_SIZE, int(y2 * sy))
            ])

        bbox_scaled = _scale_bbox_to_512(seed_bbox)
        print(f"[MedSAM2] key_idx={key_idx}, bbox_orig={seed_bbox}, bbox_512={bbox_scaled.tolist()}, D={D}, organ_hint={organ_hint}")

        incoming_prompt_frames = req.prompt_frames or []
        session_prompt_frames = session.get("prompt_frames") or []
        merged_prompt_frames: Dict[int, Dict[str, Any]] = {}

        for item in session_prompt_frames + incoming_prompt_frames:
            if not isinstance(item, dict):
                continue
            idx = item.get("slice_idx", item.get("imageIndex", item.get("sliceIndex")))
            if idx is None:
                continue
            try:
                idx = int(idx)
            except Exception:
                continue
            if idx < 0 or idx >= D:
                continue
            merged_prompt_frames[idx] = item

        if key_idx not in merged_prompt_frames:
            merged_prompt_frames[key_idx] = {
                "slice_idx": key_idx,
                "bbox": seed_bbox,
            }

        def _get_prompt_kwargs(frame: Dict[str, Any]) -> Dict[str, Any]:
            kwargs: Dict[str, Any] = {
                "clear_old_points": True,
                "normalize_coords": True,
            }

            # ── mask prompt (highest priority) ──
            mask_rle = frame.get("mask_rle")
            if isinstance(mask_rle, dict) and mask_rle.get("counts"):
                try:
                    total = mask_rle["width"] * mask_rle["height"]
                    mask_flat = np.zeros(total, dtype=np.uint8)
                    idx = 0
                    cur = mask_rle.get("starts_with", 0)
                    for cnt in mask_rle["counts"]:
                        if cur == 1:
                            mask_flat[idx:idx+cnt] = 1
                        idx += cnt
                        cur = 1 - cur
                    mask_2d = mask_flat.reshape(mask_rle["height"], mask_rle["width"])
                    if mask_2d.shape != (H, W):
                        mask_2d = cv2.resize(mask_2d, (W, H), interpolation=cv2.INTER_NEAREST)
                    if mask_2d.shape != (IMAGE_SIZE, IMAGE_SIZE):
                        mask_2d = cv2.resize(mask_2d.astype(np.uint8), (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_NEAREST)
                    kwargs["mask"] = mask_2d.astype(np.bool_)
                except Exception as e:
                    print(f"[MedSAM2] mask_rle decode failed: {e}")

            # ── bbox prompt ──
            frame_bbox = frame.get("bbox")
            if isinstance(frame_bbox, (list, tuple)) and len(frame_bbox) == 4:
                clipped = _apply_organ_roi_hint_to_bbox(list(map(int, frame_bbox)), organ_hint, W, H)
                kwargs["box"] = _scale_bbox_to_512(clipped)

            # ── points prompt ──
            points = frame.get("points")
            labels = frame.get("labels")
            if points and labels and len(points) == len(labels):
                scaled_points = []
                scaled_labels = []
                for p, lb in zip(points, labels):
                    if not isinstance(p, (list, tuple)) or len(p) < 2:
                        continue
                    x, y = float(p[0]), float(p[1])
                    scaled_points.append([max(0.0, x * sx), max(0.0, y * sy)])
                    scaled_labels.append(int(lb))
                if scaled_points and scaled_labels:
                    kwargs["points"] = np.array(scaled_points, dtype=np.float32)
                    kwargs["labels"] = np.array(scaled_labels, dtype=np.int32)

            # ── fallback: bbox from seed ──
            if "box" not in kwargs and "points" not in kwargs and "mask" not in kwargs:
                kwargs["box"] = bbox_scaled

            return kwargs

        # 预处理图像序列 → (D, 3, 512, 512) tensor
        img_tensor = torch.from_numpy(
            resize_to_rgb_512(images_uint8, IMAGE_SIZE)
        )
        if device == "cuda":
            img_tensor = img_tensor.cuda()

        segs_3d = np.zeros((D, H, W), dtype=np.uint8)
        print(f"[MedSAM2] images shape={images_uint8.shape}, orig_H={H}, orig_W={W}, IMAGE_SIZE={IMAGE_SIZE}")

        with _model_lock:
            with torch.inference_mode():
                ctx = torch.autocast("cuda", dtype=torch.bfloat16) if device == "cuda" else torch.no_grad()
                with ctx:
                    # 前向传播（从关键帧到末尾）
                    inf_state = predictor.init_state(img_tensor, IMAGE_SIZE, IMAGE_SIZE)
                    for frame_idx in sorted(merged_prompt_frames.keys()):
                        prompt_kwargs = _get_prompt_kwargs(merged_prompt_frames[frame_idx])
                        prompt_mask = prompt_kwargs.pop("mask", None)
                        if prompt_mask is not None and prompt_mask.sum() > 0:
                            print(f"[MedSAM2] using mask prompt on frame {frame_idx}, mask_nz={int(prompt_mask.sum())}")
                            predictor.add_new_mask(
                                inference_state=inf_state,
                                frame_idx=frame_idx,
                                obj_id=1,
                                mask=prompt_mask,
                            )
                        else:
                            if prompt_mask is not None:
                                print(f"[MedSAM2] mask prompt empty on frame {frame_idx}, falling back to bbox/points")
                            predictor.add_new_points_or_box(
                                inference_state=inf_state,
                                frame_idx=frame_idx,
                                obj_id=1,
                                **prompt_kwargs,
                            )
                    for out_frame_idx, _, out_mask_logits in predictor.propagate_in_video(inf_state):
                        mask_np = (out_mask_logits[0] > 0.0).cpu().numpy()
                        if mask_np.ndim == 3:
                            mask_np = mask_np[0]
                        if mask_np.shape != (H, W):
                            mask_np = cv2.resize(mask_np.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
                        segs_3d[out_frame_idx] = mask_np.astype(np.uint8)
                        if out_frame_idx == key_idx:
                            nz = int(np.sum(mask_np))
                            print(f"[MedSAM2] key frame {out_frame_idx}: mask non-zero={nz}, shape={mask_np.shape}, logits=[{float(out_mask_logits.min()):.3f},{float(out_mask_logits.max()):.3f}]")
                        with _session_lock:
                            if session_id in _sessions:
                                _sessions[session_id]["progress"] = {
                                    "current": out_frame_idx + 1, "total": D, "phase": "forward"
                                }
                    predictor.reset_state(inf_state)

                    # 反向传播（从关键帧向前）
                    inf_state = predictor.init_state(img_tensor, IMAGE_SIZE, IMAGE_SIZE)
                    for frame_idx in sorted(merged_prompt_frames.keys()):
                        prompt_kwargs = _get_prompt_kwargs(merged_prompt_frames[frame_idx])
                        prompt_mask = prompt_kwargs.pop("mask", None)
                        if prompt_mask is not None and prompt_mask.sum() > 0:
                            predictor.add_new_mask(
                                inference_state=inf_state,
                                frame_idx=frame_idx,
                                obj_id=1,
                                mask=prompt_mask,
                            )
                        else:
                            predictor.add_new_points_or_box(
                                inference_state=inf_state,
                                frame_idx=frame_idx,
                                obj_id=1,
                                **prompt_kwargs,
                            )
                    for out_frame_idx, _, out_mask_logits in predictor.propagate_in_video(inf_state, reverse=True):
                        mask_np = (out_mask_logits[0] > 0.0).cpu().numpy()
                        if mask_np.ndim == 3:
                            mask_np = mask_np[0]
                        if mask_np.shape != (H, W):
                            mask_np = cv2.resize(mask_np.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
                        segs_3d[out_frame_idx] |= mask_np.astype(np.uint8)
                        with _session_lock:
                            if session_id in _sessions:
                                _sessions[session_id]["progress"] = {
                                    "current": out_frame_idx + 1, "total": D, "phase": "reverse"
                                }
                    predictor.reset_state(inf_state)

        # 编码每切片 RLE
        masks_per_slice = []
        total_pixels = 0
        for i in range(D):
            if np.any(segs_3d[i]):
                rle = encode_rle(segs_3d[i])
                masks_per_slice.append({"slice_idx": i, "rle": rle})
                total_pixels += rle["pixel_count"]
            if i % 10 == 0:
                with _session_lock:
                    if session_id in _sessions:
                        _sessions[session_id]["progress"] = {
                            "current": i + 1, "total": D, "phase": "encoding"
                        }
        with _session_lock:
            if session_id in _sessions:
                _sessions[session_id]["progress"] = {"current": D, "total": D, "phase": "done"}

        voxel_vol = pixel_spacing[0] * pixel_spacing[1] * slice_thickness
        volume_mm3 = round(total_pixels * voxel_vol, 2)

        print(f"[MedSAM2] 完成: {len(masks_per_slice)}/{D} 切片有分割, volume={volume_mm3} mm³")

        # ── 生成 3D 表面 mesh（marching cubes），供前端渲染 ──
        # 顶点从像素空间转换到 DICOM 物理毫米空间，确保与 CT Volume 对齐
        mesh = None
        try:
            from scipy.ndimage import binary_fill_holes, binary_closing, zoom
            
            # 降采样减少顶点数（目标 ~128³）
            scale = min(128.0 / max(H, W, D), 1.0)
            if scale < 1.0:
                small = zoom(segs_3d.astype(np.float32), scale, order=0).astype(np.uint8)
            else:
                small = segs_3d
            
            # 形态学清理：填充空洞 + 闭合小缝隙
            small = binary_closing(small, iterations=2).astype(np.uint8)
            small = binary_fill_holes(small).astype(np.uint8)
            
            if np.sum(small) > 0:
                # ── 构建 DICOM 空间变换矩阵 ──
                # marching_cubes 输出 (Z, Y, X) → 物理 (x, y, z) via:
                #   P_phys = origin + Dir @ diag(spacing) @ [col_px, row_px, slice_px]
                # 其中 col_px=X, row_px=Y, slice_px=Z
                dir_mat = np.array(image_direction, dtype=np.float64)  # 3x3 row-major
                spacing_vec = np.array([pixel_spacing[0], pixel_spacing[1], slice_thickness], dtype=np.float64)
                
                try:
                    from skimage.measure import marching_cubes
                    # spacing 参数还原降采样缩放
                    verts_px, faces, _, _ = marching_cubes(small, level=0.5, spacing=(1/scale, 1/scale, 1/scale))
                    # verts_px: (N, 3) in (Z, Y, X) order = (slice_idx, row_idx, col_idx)
                    
                    # 转换到物理空间: [col, row, slice] pixels → physical mm
                    # note: verts_px[:,2]=col, verts_px[:,1]=row, verts_px[:,0]=slice
                    px_coords = np.column_stack([
                        verts_px[:, 2],  # X = column
                        verts_px[:, 1],  # Y = row
                        verts_px[:, 0],  # Z = slice
                    ])  # (N, 3) in (col, row, slice) order
                    
                    # P_phys = origin + px_coords @ diag(spacing) @ dir_mat^T
                    phys_coords = px_coords * spacing_vec[np.newaxis, :]  # (N, 3) scaled
                    phys_coords = phys_coords @ dir_mat.T  # apply direction rotation
                    phys_coords = phys_coords + np.array(image_origin, dtype=np.float64)[np.newaxis, :]
                    
                    # 限制面数
                    if len(faces) > 200000:
                        idx = np.random.choice(len(faces), 200000, replace=False)
                        faces = faces[idx]
                    
                    mesh = {
                        "vertices": phys_coords.tolist(),
                        "faces": faces.tolist(),
                        "dims": [int(W), int(H), int(D)],
                        "origin": image_origin,
                        "spacing": [pixel_spacing[0], pixel_spacing[1], slice_thickness],
                    }
                    print(f"[MedSAM2] marching_cubes mesh (phys mm): {len(verts_px)} verts, {len(faces)} faces, origin={image_origin}")
                except ImportError:
                    # 回退：边界点云
                    border = np.zeros_like(small)
                    for axis in [0, 1, 2]:
                        diff = np.diff(small.astype(np.int8), axis=axis, prepend=0)
                        border |= (diff != 0)
                    bz, by, bx = np.where(border)
                    if len(bx) > 0:
                        step = max(1, len(bx) // 80000)
                        px_list = []
                        for i in range(0, len(bx), step):
                            px_list.append([float(bx[i])/scale, float(by[i])/scale, float(bz[i])/scale])
                        px_arr = np.array(px_list, dtype=np.float64)
                        phys_arr = px_arr * spacing_vec[np.newaxis, :]
                        phys_arr = phys_arr @ dir_mat.T
                        phys_arr = phys_arr + np.array(image_origin, dtype=np.float64)[np.newaxis, :]
                        mesh = {
                            "vertices": phys_arr.tolist(),
                            "dims": [int(W), int(H), int(D)],
                            "origin": image_origin,
                            "spacing": [pixel_spacing[0], pixel_spacing[1], slice_thickness],
                        }
                        print(f"[MedSAM2] point cloud (phys mm): {len(phys_arr)} verts")
        except Exception as me:
            print(f"[MedSAM2] mesh generation skipped: {me}")

        # ── 运行 Analyze Agent ──
        analysis = None
        try:
            analysis = run_analyze(
                seg_data={
                    "masks_per_slice": masks_per_slice,
                    "total_slices": D,
                    "volume_mm3": volume_mm3,
                },
                ct_params={
                    "pixel_spacing": pixel_spacing,
                    "slice_thickness": slice_thickness,
                    "organ_hint": organ_hint if 'organ_hint' in dir() else "",
                },
                bbox=seed_bbox if 'seed_bbox' in dir() else None,
            )
            print(f"[MedSAM2] AnalyzeAgent: vol={analysis.get('volume_cm3')}cm³, area={analysis.get('max_slice_area_cm2')}cm²")
        except Exception as ae:
            print(f"[MedSAM2] AnalyzeAgent failed: {ae}")

        # 存储到 session 供后续 /report 使用
        with _session_lock:
            if session_id in _sessions:
                _sessions[session_id]["seg_result"] = {
                    "masks_per_slice": masks_per_slice,
                    "total_slices": D,
                    "volume_mm3": volume_mm3,
                    "pixel_spacing": pixel_spacing,
                    "slice_thickness": slice_thickness,
                    "analysis": analysis,
                }
                _sessions[session_id]["ct_params"] = {
                    "pixel_spacing": pixel_spacing,
                    "slice_thickness": slice_thickness,
                    "organ_hint": organ_hint if 'organ_hint' in dir() else "",
                }

        return {
            "success": True,
            "masks_per_slice": masks_per_slice,
            "total_slices_segmented": len(masks_per_slice),
            "total_slices": D,
            "volume_mm3": volume_mm3,
            "pixel_spacing": pixel_spacing,
            "slice_thickness": slice_thickness,
            "mesh": mesh,  # 3D 表面点云，供前端轻量渲染
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """释放会话内存"""
    with _session_lock:
        removed = _sessions.pop(session_id, None)
    return JSONResponse({"success": removed is not None})


@app.get("/sessions")
async def list_sessions():
    """查看当前活跃会话"""
    with _session_lock:
        info = [
            {
                "session_id": sid,
                "series_uid": s["series_uid"],
                "slices": s["images_uint8"].shape[0],
                "age_seconds": int(time.time() - s["created_at"]),
            }
            for sid, s in _sessions.items()
        ]
    return JSONResponse({"sessions": info, "count": len(info)})


# ─── 定时清理过期会话（1小时）────────────────────────────────────────────────
def _cleanup_sessions():
    while True:
        time.sleep(300)
        now = time.time()
        with _session_lock:
            expired = [sid for sid, s in _sessions.items() if now - s["created_at"] > 3600]
            for sid in expired:
                del _sessions[sid]
        if expired:
            print(f"[MedSAM2] 清理过期会话: {expired}")

threading.Thread(target=_cleanup_sessions, daemon=True).start()


# ════════════════════════════════════════════════════════════════
#  📊 Report Generation Endpoint
# ════════════════════════════════════════════════════════════════

@app.post("/session/{session_id}/report")
async def generate_report_endpoint(session_id: str, request: Request):
    """
    Generate English radiology report.
    Requires /session/{id}/segment to have completed first.
    Optional body: {"clinical_context": "..."}
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    clinical_context = body.get("clinical_context", "") if isinstance(body, dict) else ""
    organ_hint_override = body.get("organ_hint", "") if isinstance(body, dict) else ""

    with _session_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    seg_result = session.get("seg_result")
    ct_params = session.get("ct_params")
    if not seg_result:
        raise HTTPException(status_code=400, detail="No segmentation result. Run /segment first.")

    clinical_context = (body or {}).get("clinical_context", "")

    # 1. Analyze (if not cached)
    analysis = seg_result.get("analysis")
    if not analysis:
        analysis = run_analyze(
            seg_data=seg_result,
            ct_params=ct_params or {},
            bbox=None,
        )

    # Apply organ hint from frontend (overrides auto-detected)
    if organ_hint_override and isinstance(analysis, dict):
        analysis["organ_hint"] = organ_hint_override

    # 2. Evaluate
    eval_result = run_evaluate(analysis, seg_result)

    # 3. Report (with clinical context)
    report_text = _generate_report_internal(analysis, extra_context=clinical_context or "")

    return JSONResponse({
        "success": True,
        "report": report_text,
        "metrics": analysis,
        "evaluation": eval_result,
        "session_id": session_id,
    })


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  MedSAM2 3D Tracking Service v1.0")
    print(f"  Device: {device}")
    ckpt = _find_checkpoint()
    print(f"  Checkpoint: {ckpt if ckpt else '⚠️  未找到，请下载'}")
    print("  端口: 8003")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8003)
