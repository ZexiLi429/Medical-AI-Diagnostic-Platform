"""
LiteMedSAM FastAPI Service
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
import io, cv2, uuid, requests as http_requests
from pathlib import Path

from tiny_vit_sam import TinyViT
from segment_anything.modeling import MaskDecoder, PromptEncoder, TwoWayTransformer

# ─── 配置 ───────────────────────────────────────────────────────────────────
CHECKPOINT = Path(__file__).parent / "work_dir" / "LiteMedSAM" / "lite_medsam.pth"
OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
IMAGE_SIZE = 256  # LiteMedSAM 使用 256，原版 MedSAM 用 1024

# ─── Embedding 缓存 ──────────────────────────────────────────────────────────
# key: image_hash(str) → value: {embedding, new_hw, orig_hw, timestamp}
# 用于预计算：分割时直接取缓存的 embedding，跳过最慢的 image_encoder 步骤（约 0.4s → 0.03s）
import hashlib, time, threading
from collections import OrderedDict

_embedding_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 500        # 最多缓存 500 张（约 500MB）
_CACHE_TTL = 3600       # 1小时过期

def _cache_key(img_bytes: bytes) -> str:
    return hashlib.md5(img_bytes).hexdigest()

def _cache_get(key: str):
    with _cache_lock:
        entry = _embedding_cache.get(key)
        if entry and (time.time() - entry['ts'] < _CACHE_TTL):
            _embedding_cache.move_to_end(key)  # LRU
            return entry
        return None

def _cache_set(key: str, embedding, new_hw, orig_hw):
    with _cache_lock:
        if len(_embedding_cache) >= _CACHE_MAX:
            _embedding_cache.popitem(last=False)  # 移除最旧
        _embedding_cache[key] = {
            'embedding': embedding,
            'new_hw': new_hw,
            'orig_hw': orig_hw,
            'ts': time.time(),
        }

# ─── 模型定义 ─────────────────────────────────────────────────────────────────
class MedSAM_Lite(nn.Module):
    def __init__(self, image_encoder, mask_decoder, prompt_encoder):
        super().__init__()
        self.image_encoder = image_encoder
        self.mask_decoder = mask_decoder
        self.prompt_encoder = prompt_encoder

    @torch.no_grad()
    def postprocess_masks(self, masks, new_size, original_size):
        masks = masks[..., :new_size[0], :new_size[1]]
        masks = F.interpolate(masks, size=original_size, mode="bilinear", align_corners=False)
        return masks


def build_lite_medsam():
    image_encoder = TinyViT(
        img_size=256, in_chans=3,
        embed_dims=[64, 128, 160, 320],
        depths=[2, 2, 6, 2], num_heads=[2, 4, 5, 10],
        window_sizes=[7, 7, 14, 7], mlp_ratio=4.,
        drop_rate=0., drop_path_rate=0., use_checkpoint=False,
        mbconv_expand_ratio=4., local_conv_size=3, layer_lr_decay=0.8
    )
    prompt_encoder = PromptEncoder(
        embed_dim=256, image_embedding_size=(64, 64),
        input_image_size=(256, 256), mask_in_chans=16
    )
    mask_decoder = MaskDecoder(
        num_multimask_outputs=3,
        transformer=TwoWayTransformer(depth=2, embedding_dim=256, mlp_dim=2048, num_heads=8),
        transformer_dim=256, iou_head_depth=3, iou_head_hidden_dim=256,
    )
    return MedSAM_Lite(image_encoder, mask_decoder, prompt_encoder)


# ─── 图像预处理工具 ───────────────────────────────────────────────────────────
def resize_longest_side(image: np.ndarray, target=256) -> np.ndarray:
    h, w = image.shape[:2]
    scale = target / max(h, w)
    return cv2.resize(image, (int(w * scale + .5), int(h * scale + .5)), interpolation=cv2.INTER_AREA)

def pad_to_square(image: np.ndarray, target=256) -> np.ndarray:
    h, w = image.shape[:2]
    pad = ((0, target - h), (0, target - w), (0, 0)) if image.ndim == 3 else ((0, target - h), (0, target - w))
    return np.pad(image, pad)

def preprocess(image_np: np.ndarray):
    """返回 (tensor, new_hw, original_hw)"""
    if image_np.ndim == 2:
        image_np = np.stack([image_np] * 3, axis=-1)
    if image_np.shape[-1] == 4:
        image_np = image_np[..., :3]
    H, W = image_np.shape[:2]
    img256 = resize_longest_side(image_np, 256)
    new_h, new_w = img256.shape[:2]
    img256 = img256.astype(np.float32)
    lo, hi = img256.min(), img256.max()
    img256 = (img256 - lo) / np.clip(hi - lo, 1e-8, None)
    img256 = pad_to_square(img256, 256)
    tensor = torch.from_numpy(img256).permute(2, 0, 1).unsqueeze(0).float().to(device)
    return tensor, (new_h, new_w), (H, W)

def scale_box_to_256(box, original_size):
    """将原始图像坐标系的 bbox 缩放到 256 坐标系"""
    ratio = 256 / max(original_size)
    return np.array([int(v * ratio) for v in box])

def scale_points_to_256(points_orig, orig_size):
    """将原始图像坐标系的点列表缩放到 256 坐标系"""
    ratio = 256 / max(orig_size)
    return np.array([[p[0] * ratio, p[1] * ratio] for p in points_orig])

@torch.no_grad()
def run_inference(model, img_embed, box256, new_size, orig_size, points256=None, point_labels=None):
    box_torch = torch.as_tensor(box256[None, None, ...], dtype=torch.float, device=img_embed.device)
    
    # 准备 point prompts
    pts_torch = None
    lbl_torch = None
    if points256 is not None and point_labels is not None and len(points256) > 0:
        pts_torch = torch.as_tensor(points256[None, ...], dtype=torch.float, device=img_embed.device)
        lbl_torch = torch.as_tensor(point_labels[None, ...], dtype=torch.float, device=img_embed.device)
        print(f"[inference] using {len(points256)} point prompts with bbox")
    
    sparse_emb, dense_emb = model.prompt_encoder(points=pts_torch, boxes=box_torch, masks=None)
    low_res_logits, iou = model.mask_decoder(
        image_embeddings=img_embed,
        image_pe=model.prompt_encoder.get_dense_pe(),
        sparse_prompt_embeddings=sparse_emb,
        dense_prompt_embeddings=dense_emb,
        multimask_output=False,
    )
    mask = model.postprocess_masks(low_res_logits, new_size, orig_size)
    mask = torch.sigmoid(mask).squeeze().cpu().numpy()
    return (mask > 0.5).astype(np.uint8), float(iou.squeeze())

def detect_bbox_from_annotation(ann_img: np.ndarray, orig_img: np.ndarray) -> Optional[np.ndarray]:
    """
    从带标注的截图中检测用户绘制的矩形框。
    Cornerstone3D 标注通常是高饱和度彩色线条。
    返回原始图像坐标系下的 [x1, y1, x2, y2]，检测失败返回 None。
    """
    try:
        diff = cv2.absdiff(ann_img, orig_img) if orig_img is not None else None
        src = cv2.cvtColor(diff if diff is not None else ann_img, cv2.COLOR_RGB2HSV)
        # 高饱和度 + 高亮度 = 标注颜色
        mask = cv2.inRange(src, np.array([0, 120, 120]), np.array([180, 255, 255]))
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        # 选面积最大的轮廓
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) < 100:
            return None
        x, y, w, h = cv2.boundingRect(c)
        # 映射到原始图像坐标
        sy = orig_img.shape[0] / ann_img.shape[0] if orig_img is not None else 1
        sx = orig_img.shape[1] / ann_img.shape[1] if orig_img is not None else 1
        return np.array([int(x * sx), int(y * sy), int((x + w) * sx), int((y + h) * sy)])
    except Exception:
        return None

def encode_rle(mask: np.ndarray) -> dict:
    """
    将二值掩码编码为 RLE（游程编码），按行优先展平。
    格式：{"counts": [count0, count1, ...], "starts_with": 0|1, "width": W, "height": H}
    counts[0] 对应 starts_with 值的连续像素数，之后交替。
    与 COCO RLE 兼容（仅 uint8 二值掩码）。
    """
    flat = mask.flatten().astype(np.uint8)
    # 找到值变化的位置
    changes = np.diff(flat, prepend=flat[0] ^ 1)  # 强制首段与flat[0]相同值
    change_idx = np.where(changes != 0)[0]
    counts = np.diff(np.append(change_idx, len(flat))).tolist()
    return {
        "counts": counts,
        "starts_with": int(flat[0]),
        "width": int(mask.shape[1]),
        "height": int(mask.shape[0]),
    }


def get_organ_prior_box(organ: str, width: int, height: int):
    organ_priors = {
        # 轴位CT默认显示中，患者右侧位于图像左侧
        "liver":        [int(width * 0.08), int(height * 0.18), int(width * 0.58), int(height * 0.80)],
        "spleen":       [int(width * 0.58), int(height * 0.20), int(width * 0.90), int(height * 0.72)],
        "kidney":       [int(width * 0.16), int(height * 0.28), int(width * 0.84), int(height * 0.80)],
        "kidney_left":  [int(width * 0.56), int(height * 0.30), int(width * 0.84), int(height * 0.76)],
        "kidney_right": [int(width * 0.16), int(height * 0.30), int(width * 0.46), int(height * 0.76)],
        "lung_l":       [int(width * 0.54), int(height * 0.08), int(width * 0.96), int(height * 0.92)],
        "lung_r":       [int(width * 0.04), int(height * 0.08), int(width * 0.46), int(height * 0.92)],
    }
    alias = {
        "lung": "lung_l",
        "left_kidney": "kidney_left",
        "right_kidney": "kidney_right",
    }
    organ_key = alias.get(organ, organ)
    return np.array(organ_priors.get(organ_key, organ_priors["liver"])), organ_key

def save_result(mask: np.ndarray, original: np.ndarray) -> str:
    """叠加 mask 到原图后保存，返回 URL"""
    fname = f"mask_{uuid.uuid4().hex[:8]}.png"
    fpath = OUTPUT_DIR / fname
    vis = original.copy() if original.ndim == 3 else np.stack([original] * 3, axis=-1)
    overlay = np.zeros_like(vis)
    overlay[mask > 0] = [255, 80, 80]
    vis = cv2.addWeighted(vis, 0.65, overlay, 0.35, 0)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, cnts, -1, (0, 230, 0), 2)
    cv2.imwrite(str(fpath), cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))
    return f"/outputs/{fname}"


# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(title="LiteMedSAM Service", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

model: Optional[MedSAM_Lite] = None

@app.on_event("startup")
async def startup():
    global model
    if not CHECKPOINT.exists():
        print(f"[WARN] 模型权重未找到: {CHECKPOINT}")
        print("[WARN] 请从 Google Drive 下载 lite_medsam.pth：")
        print("[WARN] https://drive.google.com/file/d/18Zed-TUTsmr2zc5CHUWd5Tu13nb6vq6z/view")
        print(f"[WARN] 保存到: {CHECKPOINT}")
        return
    print(f"[INFO] 加载 LiteMedSAM 模型 ({device})...")
    m = build_lite_medsam()
    ckpt = torch.load(str(CHECKPOINT), map_location="cpu", weights_only=True)
    m.load_state_dict(ckpt)
    m.to(device).eval()
    model = m
    print(f"[INFO] LiteMedSAM 就绪！(图像尺寸: {IMAGE_SIZE}x{IMAGE_SIZE})")


@app.get("/health")
async def health():
    return {
        "status": "healthy" if model else "no_model",
        "model": "LiteMedSAM",
        "device": str(device),
        "image_size": IMAGE_SIZE,
        "checkpoint": str(CHECKPOINT),
        "checkpoint_exists": CHECKPOINT.exists(),
    }


@app.post("/segment")
async def segment(
    sam_image: UploadFile = File(...),   # 带标注的视口截图
    file: UploadFile = File(None),       # 原始切片（可选，用于精准 bbox 检测）
    bbox: str = Form(None),              # 可选: "x1,y1,x2,y2" 像素坐标
):
    """
    矩形框分割 (Rectangle Prompt)
    优先使用 bbox 参数；未提供时从截图标注中自动检测。
    """
    if model is None:
        return JSONResponse({"success": False, "error": "模型未加载，请先下载 lite_medsam.pth"}, status_code=503)

    try:
        ann_bytes = await sam_image.read()
        ann_np = np.array(Image.open(io.BytesIO(ann_bytes)).convert("RGB"))

        orig_np = None
        if file:
            orig_bytes = await file.read()
            orig_np = np.array(Image.open(io.BytesIO(orig_bytes)).convert("RGB"))

        ref_img = orig_np if orig_np is not None else ann_np
        H, W = ref_img.shape[:2]

        # 1. 确定 bbox
        if bbox:
            box = np.array([int(v) for v in bbox.split(",")])
            print(f"[INFO] 使用前端提供的 bbox: {box}")
        else:
            box = detect_bbox_from_annotation(ann_np, orig_np)
            if box is None:
                # 降级：使用中心 70% 区域
                margin = 0.15
                box = np.array([int(W*margin), int(H*margin), int(W*(1-margin)), int(H*(1-margin))])
                print(f"[WARN] 未检测到标注矩形，使用默认 bbox: {box}")
            else:
                print(f"[INFO] 从截图检测到 bbox: {box}")

        # 2. 预处理 + Embedding（优先读缓存）
        img_key = _cache_key(orig_bytes if file else ann_bytes)
        cached = _cache_get(img_key)
        if cached:
            img_embed = cached['embedding']
            new_hw   = cached['new_hw']
            orig_hw  = cached['orig_hw']
            print(f"[INFO] ✅ Embedding 缓存命中 key={img_key[:8]}，跳过 image_encoder")
        else:
            tensor, new_hw, orig_hw = preprocess(ref_img)
            with torch.no_grad():
                img_embed = model.image_encoder(tensor)
            _cache_set(img_key, img_embed, new_hw, orig_hw)
            print(f"[INFO] 🔄 新计算 Embedding key={img_key[:8]}")

        # 3. 缩放 bbox 到 256 坐标系并推理
        box256 = scale_box_to_256(box, (H, W))
        mask, iou = run_inference(model, img_embed, box256, new_hw, orig_hw)

        # 5. 编码 RLE + 保存预览图
        rle = encode_rle(mask)
        image_url = save_result(mask, ref_img)
        print(f"[INFO] 分割完成 IoU={iou:.3f}, 掩码像素数={int(mask.sum())}, 保存至 {image_url}")

        return JSONResponse({
            "success": True,
            "image_url": image_url,   # 向后兼容：PNG 预览图
            "rle": rle,               # 新增：直接写入 labelmap
            "iou": iou,
            "bbox_used": box.tolist(),
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/points")
async def segment_points(
    sam_image: UploadFile = File(...),
    file: UploadFile = File(None),
    points: str = Form(None),  # "x1,y1,x2,y2,..." 可选
):
    """点击提示分割（复用矩形推理，用点的 bounding box）"""
    return await segment(sam_image=sam_image, file=file, bbox=None)


@app.post("/mask")
async def segment_mask(
    sam_image: UploadFile = File(...),
    file: UploadFile = File(None),
):
    """Mask Prompt（复用矩形推理）"""
    return await segment(sam_image=sam_image, file=file, bbox=None)


@app.post("/auto_liver")
async def auto_liver(
    file: UploadFile = File(...),
    organ: str = Form(default="liver"),
):
    """
    自动分割器官（无需手动标注），使用 CT/MRI 解剖先验位置推断
    支持：liver, spleen, kidney, kidney_left, kidney_right, lung_l, lung_r
    """
    if model is None:
        return JSONResponse({"success": False, "error": "模型未加载"}, status_code=503)

    try:
        img_bytes = await file.read()
        img_np = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        H, W = img_np.shape[:2]

        # -------------------------------------------------------
        # 各器官解剖先验 bbox（基于腹/胸部 CT 轴位图像比例）
        # 坐标格式：[x1, y1, x2, y2]，均为比例 × 图像尺寸
        # -------------------------------------------------------
        organ_priors = {
            # 腹部器官。注意轴位CT通常按“从足端看向头端”显示，患者右侧位于图像左侧。
            "liver":        [int(W*0.08), int(H*0.18), int(W*0.58), int(H*0.80)],
            "spleen":       [int(W*0.58), int(H*0.20), int(W*0.90), int(H*0.72)],
            "kidney":       [int(W*0.16), int(H*0.28), int(W*0.84), int(H*0.80)],
            "kidney_left":  [int(W*0.56), int(H*0.30), int(W*0.84), int(H*0.76)],  # 患者左肾（图右侧）
            "kidney_right": [int(W*0.16), int(H*0.30), int(W*0.46), int(H*0.76)],  # 患者右肾（图左侧）
            # 胸部器官
            "lung_l":       [int(W*0.54), int(H*0.08), int(W*0.96), int(H*0.92)],  # 患者左肺（图右侧）
            "lung_r":       [int(W*0.04), int(H*0.08), int(W*0.46), int(H*0.92)],  # 患者右肺（图左侧）
        }
        # 别名兼容
        alias = {"lung": "lung_l"}
        organ_key = alias.get(organ, organ)
        box = np.array(organ_priors.get(organ_key, organ_priors["liver"]))
        print(f"[INFO] 自动分割 {organ} (key={organ_key}), bbox={box.tolist()}")

        # Embedding 优先读缓存
        img_key = _cache_key(img_bytes)
        cached = _cache_get(img_key)
        if cached:
            img_embed = cached['embedding']
            new_hw    = cached['new_hw']
            orig_hw   = cached['orig_hw']
            print(f"[INFO] ✅ Embedding 缓存命中 key={img_key[:8]}")
        else:
            tensor, new_hw, orig_hw = preprocess(img_np)
            with torch.no_grad():
                img_embed = model.image_encoder(tensor)
            _cache_set(img_key, img_embed, new_hw, orig_hw)

        box256 = scale_box_to_256(box, (H, W))
        mask, iou = run_inference(model, img_embed, box256, new_hw, orig_hw)

        rle = encode_rle(mask)
        image_url = save_result(mask, img_np)
        print(f"[INFO] 自动分割完成 organ={organ} IoU={iou:.3f}, 掩码像素数={int(mask.sum())}")

        return JSONResponse({
            "success": True,
            "image_url": image_url,
            "rle": rle,
            "organ": organ,
            "iou": iou,
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ============================================================
#  /preload  —  批量预计算切片 Embedding（加速后续分割）
# ============================================================

@app.post("/preload")
async def preload_slices(
    files: List[UploadFile] = File(...),
):
    """
    接受一组图像文件（CT系列切片截图），批量预计算 SAM image embeddings 并缓存。
    后续 /segment 请求对相同图像将直接使用缓存，推理时间从 ~0.4s 降至 ~0.03s。
    """
    if model is None:
        return JSONResponse({"success": False, "error": "模型未加载"}, status_code=503)

    results = []
    for f in files:
        try:
            img_bytes = await f.read()
            img_key = _cache_key(img_bytes)
            if _cache_get(img_key):
                results.append({"filename": f.filename, "status": "cached"})
                continue
            img_np = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
            tensor, new_hw, orig_hw = preprocess(img_np)
            with torch.no_grad():
                img_embed = model.image_encoder(tensor)
            _cache_set(img_key, img_embed, new_hw, orig_hw)
            results.append({"filename": f.filename, "status": "computed", "key": img_key[:8]})
        except Exception as e:
            results.append({"filename": f.filename, "status": "error", "error": str(e)})

    cached_count = sum(1 for r in results if r["status"] in ("computed", "cached"))
    print(f"[INFO] /preload 完成: {cached_count}/{len(files)} 张已缓存")
    return JSONResponse({
        "success": True,
        "total": len(files),
        "cached": cached_count,
        "results": results,
    })


@app.get("/cache_status")
async def cache_status():
    """返回当前 embedding 缓存状态"""
    with _cache_lock:
        count = len(_embedding_cache)
        keys = [k[:8] for k in list(_embedding_cache.keys())[-10:]]
    return JSONResponse({
        "cached_embeddings": count,
        "max_cache": _CACHE_MAX,
        "ttl_seconds": _CACHE_TTL,
        "recent_keys": keys,
    })


# ============================================================
#  /segment_dicom  —  后端直连 Orthanc 读原始 DICOM 像素分割
#  比截图路径精度更高，同时返回真实体积 mm³
# ============================================================

class DicomSegRequest(BaseModel):
    sop_instance_uid: str
    bbox: List[int]              # [x1, y1, x2, y2] 像素坐标（相对于 DICOM 图像）
    points: Optional[List[List[float]]] = None  # [[x1,y1], [x2,y2], ...] 可选点提示
    labels: Optional[List[int]] = None          # [1, 1, ...] 点标签 (1=前景)
    window_center: Optional[float] = None       # 前端 viewport 窗位
    window_width: Optional[float] = None        # 前端 viewport 窗宽
    mask_rle: Optional[dict] = None             # 刷子掩码
    orthanc_url: str = "http://localhost:8042"
    orthanc_user: str = "orthanc"
    orthanc_password: str = "orthanc"


class AutoOrganDicomRequest(BaseModel):
    sop_instance_uid: str
    organ: str = "liver"
    orthanc_url: str = "http://localhost:8042"
    orthanc_user: str = "orthanc"
    orthanc_password: str = "orthanc"


@app.post("/segment_dicom")
async def segment_dicom(req: DicomSegRequest):
    """
    正确数据流：后端直接从 Orthanc 读取 DICOM 像素，无需前端传截图。
    前端只需发送：{ sop_instance_uid, bbox: [x1,y1,x2,y2] }
    返回：{ success, rle, volume_mm3, pixel_spacing, confidence, model }
    """
    if model is None:
        return JSONResponse({"success": False, "error": "模型未加载"}, status_code=503)
    try:
        auth = (req.orthanc_user, req.orthanc_password)

        # 1. 通过 SOPInstanceUID 查找 Orthanc 内部 ID
        find_resp = http_requests.post(
            f"{req.orthanc_url}/tools/find",
            auth=auth,
            json={"Level": "Instance", "Query": {"SOPInstanceUID": req.sop_instance_uid}},
            timeout=10,
        )
        find_resp.raise_for_status()
        instance_ids = find_resp.json()
        if not instance_ids:
            raise HTTPException(status_code=404, detail=f"SOPInstanceUID {req.sop_instance_uid} not found in Orthanc")
        orthanc_id = instance_ids[0]

        # 2. 获取 pixel spacing（用于体积计算）
        pixel_spacing = [1.0, 1.0]
        try:
            tags = http_requests.get(
                f"{req.orthanc_url}/instances/{orthanc_id}/simplified-tags",
                auth=auth, timeout=10
            ).json()
            ps = tags.get("PixelSpacing") or tags.get("ImagerPixelSpacing")
            if ps:
                if isinstance(ps, str):
                    parts = ps.replace("\\", " ").split()
                    if len(parts) >= 2:
                        pixel_spacing = [float(parts[0]), float(parts[1])]
                elif isinstance(ps, list) and len(ps) >= 2:
                    pixel_spacing = [float(ps[0]), float(ps[1])]
        except Exception:
            pass

        # 3. 获取渲染后的 PNG（传入窗宽窗位与前端一致）
        render_params = {"quality": 100}
        if req.window_center is not None and req.window_width is not None:
            render_params["window-center"] = int(req.window_center)
            render_params["window-width"] = int(req.window_width)
        img_resp = http_requests.get(
            f"{req.orthanc_url}/instances/{orthanc_id}/rendered",
            auth=auth, params=render_params, timeout=30,
        )
        img_resp.raise_for_status()
        img_bytes = img_resp.content
        img_np = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        H, W = img_np.shape[:2]

        # 4. 验证 bbox
        x1, y1, x2, y2 = req.bbox
        x1, x2 = max(0, min(x1, W-1)), max(1, min(x2, W))
        y1, y2 = max(0, min(y1, H-1)), max(1, min(y2, H))
        if x2 <= x1 or y2 <= y1:
            raise HTTPException(status_code=400, detail="Invalid bbox coordinates")
        box_np = np.array([x1, y1, x2, y2])
        print(f"[segment_dicom] uid={req.sop_instance_uid[:12]}…, bbox={box_np}, img={W}x{H}")
        if req.points:
            print(f"[segment_dicom]   + {len(req.points)} point prompts")

        # 5. LiteMedSAM 推理（优先用 embedding 缓存）
        img_key = _cache_key(img_bytes)
        cached = _cache_get(img_key)
        if cached:
            img_embed = cached['embedding']
            new_hw    = cached['new_hw']
            orig_hw   = cached['orig_hw']
            print(f"[segment_dicom] ✅ embedding cache hit")
        else:
            tensor, new_hw, orig_hw = preprocess(img_np)
            with torch.no_grad():
                img_embed = model.image_encoder(tensor)
            _cache_set(img_key, img_embed, new_hw, orig_hw)

        box256 = scale_box_to_256(box_np, (H, W))
        pts256 = None
        labels = None
        if req.points and req.labels:
            pts256 = scale_points_to_256(req.points, (H, W))
            labels = req.labels
        mask, confidence = run_inference(model, img_embed, box256, new_hw, (H, W), pts256, labels)

        # 6. 体积计算
        pixel_count = int(np.sum(mask))
        volume_mm3 = round(pixel_count * pixel_spacing[0] * pixel_spacing[1], 2)
        rle_data = encode_rle(mask)
        print(f"[segment_dicom] Done: pixels={pixel_count}, volume={volume_mm3} mm³")

        return JSONResponse({
            "success": True,
            "rle": rle_data,
            "volume_mm3": volume_mm3,
            "pixel_spacing": pixel_spacing,
            "confidence": confidence,
            "shape": {"width": W, "height": H},
            "model": "lite_medsam",
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/auto_organ_dicom")
async def auto_organ_dicom(req: AutoOrganDicomRequest):
    if model is None:
        return JSONResponse({"success": False, "error": "模型未加载"}, status_code=503)
    try:
        auth = (req.orthanc_user, req.orthanc_password)
        find_resp = http_requests.post(
            f"{req.orthanc_url}/tools/find",
            auth=auth,
            json={"Level": "Instance", "Query": {"SOPInstanceUID": req.sop_instance_uid}},
            timeout=10,
        )
        find_resp.raise_for_status()
        instance_ids = find_resp.json()
        if not instance_ids:
            raise HTTPException(status_code=404, detail=f"SOPInstanceUID {req.sop_instance_uid} not found in Orthanc")
        orthanc_id = instance_ids[0]

        pixel_spacing = [1.0, 1.0]
        try:
            tags = http_requests.get(
                f"{req.orthanc_url}/instances/{orthanc_id}/simplified-tags",
                auth=auth,
                timeout=10,
            ).json()
            ps = tags.get("PixelSpacing") or tags.get("ImagerPixelSpacing")
            if ps:
                if isinstance(ps, str):
                    parts = ps.replace("\\", " ").split()
                    if len(parts) >= 2:
                        pixel_spacing = [float(parts[0]), float(parts[1])]
                elif isinstance(ps, list) and len(ps) >= 2:
                    pixel_spacing = [float(ps[0]), float(ps[1])]
        except Exception:
            pass

        img_resp = http_requests.get(
            f"{req.orthanc_url}/instances/{orthanc_id}/rendered",
            auth=auth,
            params={"quality": 100},
            timeout=30,
        )
        img_resp.raise_for_status()
        img_bytes = img_resp.content
        img_np = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        height, width = img_np.shape[:2]

        box_np, organ_key = get_organ_prior_box(req.organ, width, height)
        print(f"[auto_organ_dicom] uid={req.sop_instance_uid[:12]}..., organ={req.organ}, key={organ_key}, bbox={box_np.tolist()}")

        img_key = _cache_key(img_bytes)
        cached = _cache_get(img_key)
        if cached:
            img_embed = cached['embedding']
            new_hw = cached['new_hw']
            print("[auto_organ_dicom] ✅ embedding cache hit")
        else:
            tensor, new_hw, _orig_hw = preprocess(img_np)
            with torch.no_grad():
                img_embed = model.image_encoder(tensor)
            _cache_set(img_key, img_embed, new_hw, (height, width))

        box256 = scale_box_to_256(box_np, (height, width))
        mask, confidence = run_inference(model, img_embed, box256, new_hw, (height, width))

        pixel_count = int(np.sum(mask))
        volume_mm3 = round(pixel_count * pixel_spacing[0] * pixel_spacing[1], 2)
        rle_data = encode_rle(mask)
        image_url = save_result(mask, img_np)

        return JSONResponse({
            "success": True,
            "rle": rle_data,
            "image_url": image_url,
            "volume_mm3": volume_mm3,
            "pixel_spacing": pixel_spacing,
            "confidence": confidence,
            "shape": {"width": width, "height": height},
            "organ": req.organ,
            "organ_key": organ_key,
            "bbox_used": box_np.tolist(),
            "model": "lite_medsam",
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ============================================================
#  /report  —  医疗 AI 报告生成
# ============================================================

@app.post("/report")
async def generate_report(
    image: UploadFile = File(None),
    segment_labels: str = Form(default=""),
    modality: str = Form(default="CT"),
    organ_hint: str = Form(default=""),
    volume_mm3: str = Form(default=""),
    tracked_slices: str = Form(default=""),
):
    """
    根据分割结果生成放射科报告。
    优先调用 Ollama 本地 LLM；若不可用则返回模板报告。
    """
    import datetime

    label_text = segment_labels.strip() or "未指定分割区域"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = (
        f"你是一位经验丰富的放射科医生，请根据以下信息撰写一份简洁的中文放射学报告：\n"
        f"- 检查类型：{modality}\n"
        f"- AI 自动分割结果：{label_text}\n\n"
        f"报告格式：\n"
        f"【检查所见】\n"
        f"【印象/诊断】\n"
        f"【建议】\n"
        f"请用专业但简洁的语言撰写，不超过 300 字。"
    )

    report_text = None
    organ_hint = (organ_hint or "").strip()
    volume_value = None
    tracked_value = None
    try:
        if volume_mm3:
            volume_value = float(volume_mm3)
    except Exception:
        volume_value = None
    try:
        if tracked_slices:
            tracked_value = int(float(tracked_slices))
    except Exception:
        tracked_value = None

    # 尝试调用 Ollama（http://localhost:11434）
    try:
        import urllib.request
        import json as _json
        payload = _json.dumps({
            "model": "medllama2",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 512},
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode())
            report_text = result.get("response", "").strip()
        print(f"[INFO] Ollama 报告生成成功 (model=medllama2, {len(report_text)} 字符)")
    except Exception as ollama_err:
        print(f"[WARN] Ollama 不可用: {ollama_err}，使用模板报告")

    def _build_fallback_report():
        volume_cm3 = (volume_value / 1000.0) if isinstance(volume_value, (float, int)) else None
        organ_text = organ_hint or "未指定器官"
        return (
            f"放射学报告\n"
            f"{'='*40}\n"
            f"检查时间：{now}\n"
            f"检查类型：{modality}\n\n"
            f"【检查所见】\n"
            f"AI 辅助分割系统（LiteMedSAM）对本次 {modality} 图像进行了自动分析。\n"
            f"识别区域：{label_text}\n"
            f"器官提示：{organ_text}\n"
            f"估计体积：{(f'{volume_cm3:.2f} cm³' if volume_cm3 is not None else '未提供')}\n"
            f"追踪切片数：{tracked_value if tracked_value is not None else '未提供'}\n\n"
            f"【印象/诊断】\n"
            f"本次 AI 分割提示上述区域存在异常，建议结合临床资料及其他影像学检查综合判断。\n\n"
            f"【建议】\n"
            f"1. 请结合患者临床症状及实验室检查进行综合评估。\n"
            f"2. 如有必要，建议进行增强扫描或 MRI 进一步检查。\n"
            f"3. 定期随访复查。\n\n"
            f"注意：本报告由 AI 辅助生成，仅供参考，不可替代专业医师诊断。\n"
            f"{'='*40}"
        )

    def _verify_report(text: str) -> bool:
        if not text or not text.strip():
            return False
        t = text.lower()
        if organ_hint and organ_hint.lower().replace('_', ' ') not in t:
            return False
        if isinstance(volume_value, (float, int)) and volume_value > 0:
            v_mm3 = f"{volume_value:.2f}".lower()
            v_cm3 = f"{(volume_value/1000.0):.2f}".lower()
            if v_mm3 not in t and v_cm3 not in t:
                return False
        return True

    # Fallback：结构化模板报告
    if not report_text:
        report_text = _build_fallback_report()
    elif not _verify_report(report_text):
        print("[WARN] 报告校验失败，使用模板兜底")
        report_text = _build_fallback_report()

    return JSONResponse({"success": True, "report": report_text})


if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  LiteMedSAM Service v2.0")
    print(f"  Device: {device}")
    print(f"  Checkpoint: {CHECKPOINT}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8002)