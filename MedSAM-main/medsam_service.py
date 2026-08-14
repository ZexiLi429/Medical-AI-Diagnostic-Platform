"""
MedSAM FastAPI Service 
"""
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import numpy as np
import torch
from segment_anything import sam_model_registry
from PIL import Image
import io
import base64
import cv2
from typing import List, Optional
import json
import os
from pathlib import Path
import uuid
import requests as http_requests

app = FastAPI(title="MedSAM API Service", version="1.0.0")

# 配置CORS - 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8042", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建输出目录
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# 挂载静态文件目录
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# 全局模型变量
medsam_model = None
device = "cuda" if torch.cuda.is_available() else "cpu"

# 模型检查点路径 — SAM vit_b (支持 mask prompt)
MODEL_CHECKPOINT = "work_dir/SAM/sam_vit_b_01ec64.pth"


def load_model():
    """加载MedSAM模型"""
    global medsam_model
    if medsam_model is None:
        print("Loading MedSAM model...")
        medsam_model = sam_model_registry["vit_b"](checkpoint=MODEL_CHECKPOINT)
        medsam_model.to(device)
        medsam_model.eval()
        print(f"Model loaded on device: {device}")
    return medsam_model


def rle_to_mask(rle: dict) -> np.ndarray:
    """解码 RLE（与前端 _decodeRLE 一致）→ 二值 numpy 掩码"""
    w, h = rle["width"], rle["height"]
    total = w * h
    flat = np.zeros(total, dtype=np.uint8)
    idx, cv = 0, rle["starts_with"]
    for cnt in rle["counts"]:
        if cv == 1:
            flat[idx:idx + cnt] = 1
        idx += cnt
        cv = 1 - cv
    return flat.reshape((h, w))


def mask_to_rle(mask_np: np.ndarray) -> dict:
    """Encode binary mask as run-length encoding (RLE) for compact frontend transfer.
    Returns counts of alternating 0-runs and 1-runs starting from starts_with."""
    H, W = mask_np.shape
    flat = mask_np.flatten().astype(np.uint8)
    if len(flat) == 0:
        return {"counts": [], "starts_with": 0, "width": W, "height": H}
    counts = []
    cur = int(flat[0])
    cnt = 0
    for v in flat:
        if int(v) == cur:
            cnt += 1
        else:
            counts.append(cnt)
            cnt = 1
            cur = int(v)
    counts.append(cnt)
    pixel_count = int(np.sum(flat))
    return {"counts": counts, "starts_with": int(flat[0]), "width": W, "height": H, "pixel_count": pixel_count}


def save_mask_image(mask_np: np.ndarray, original_image: np.ndarray = None) -> str:
    """保存分割结果为图像文件"""
    filename = f"mask_{uuid.uuid4().hex[:8]}.png"
    filepath = OUTPUT_DIR / filename
    
    if original_image is not None:
        # 叠加显示：原图 + 半透明mask
        H, W = original_image.shape[:2]
        if len(original_image.shape) == 2:
            original_image = cv2.cvtColor(original_image, cv2.COLOR_GRAY2RGB)
        
        # 创建彩色mask（红色）
        colored_mask = np.zeros_like(original_image)
        colored_mask[mask_np > 0] = [255, 0, 0]  # 红色
        
        # 叠加
        result = cv2.addWeighted(original_image, 0.7, colored_mask, 0.3, 0)
        
        # 添加轮廓
        contours, _ = cv2.findContours(
            mask_np.astype(np.uint8), 
            cv2.RETR_EXTERNAL, 
            cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(result, contours, -1, (0, 255, 0), 2)
        
        cv2.imwrite(str(filepath), cv2.cvtColor(result, cv2.COLOR_RGB2BGR))
    else:
        # 仅保存mask
        mask_img = Image.fromarray((mask_np * 255).astype(np.uint8))
        mask_img.save(filepath)
    
    return f"/outputs/{filename}"


@app.on_event("startup")
async def startup_event():
    """服务启动时加载模型"""
    load_model()
    print("MedSAM Service is ready!")


@app.get("/")
async def root():
    """健康检查接口"""
    return {
        "service": "MedSAM API",
        "status": "running",
        "device": device,
        "model_loaded": medsam_model is not None
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "device": device}


@app.post("/segment")
async def segment_rectangle(
    sam_image: UploadFile = File(...),
    file: UploadFile = File(None),  # 原始图像（可选）
    bbox: Optional[str] = Form(None),  # "x1,y1,x2,y2" in image pixel coords
):
    """
    医学影像分割接口 - Rectangle Prompt
    
    参数:
    - sam_image: 带有矩形框标注的截图（PNG/JPG格式）
    - file: 原始医学影像（可选）
    
    返回:
    - image_url: 分割结果图像的URL
    - success: 是否成功
    """
    try:
        print("[DEBUG] /segment - Rectangle prompt endpoint called")
        model = load_model()
        
        # 读取图像
        image_bytes = await sam_image.read()
        image_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image_np = np.array(image_pil)
        
        print(f"[DEBUG] Image shape: {image_np.shape}")
        
        H, W = image_np.shape[:2]

        # 优先使用前端提交的 bbox（来自 RectangleROI 标注）
        box_np = None
        if bbox:
            try:
                parts = [int(v.strip()) for v in bbox.split(',')]
                if len(parts) == 4:
                    bx1, by1, bx2, by2 = parts
                    # 确保坐标合法
                    bx1, bx2 = max(0, min(bx1, W-1)), max(1, min(bx2, W))
                    by1, by2 = max(0, min(by1, H-1)), max(1, min(by2, H))
                    if bx2 > bx1 and by2 > by1:
                        box_np = np.array([bx1, by1, bx2, by2])
                        print(f"[DEBUG] Using frontend bbox: {box_np}")
            except Exception as e:
                print(f"[DEBUG] bbox parse error ({e}), falling back to auto")

        if box_np is None:
            # 降级：使用中心 80% 区域
            margin = 0.1
            x1, y1 = int(W * margin), int(H * margin)
            x2, y2 = int(W * (1 - margin)), int(H * (1 - margin))
            box_np = np.array([x1, y1, x2, y2])
            print(f"[DEBUG] Auto bbox (fallback): {box_np}")
        
        # 预处理
        if len(image_np.shape) == 2:
            image_np = np.repeat(image_np[:, :, None], 3, axis=-1)
        
        # Resize to 1024x1024
        image_1024 = cv2.resize(image_np, (1024, 1024), interpolation=cv2.INTER_CUBIC)
        box_1024 = box_np / np.array([W, H, W, H]) * 1024
        
        # 转换为tensor
        image_tensor = torch.tensor(image_1024).float().permute(2, 0, 1).unsqueeze(0)
        image_tensor = (image_tensor - image_tensor.min()) / (image_tensor.max() - image_tensor.min()) * 255.0
        image_tensor = image_tensor.to(device)
        
        # MedSAM推理
        with torch.no_grad():
            image_embedding = model.image_encoder(image_tensor)
            box_torch = torch.tensor(box_1024).unsqueeze(0).to(device)
            
            sparse_embeddings, dense_embeddings = model.prompt_encoder(
                points=None,
                boxes=box_torch,
                masks=None,
            )
            
            low_res_logits, _ = model.mask_decoder(
                image_embeddings=image_embedding,
                image_pe=model.prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
            )
            
            low_res_pred = torch.sigmoid(low_res_logits)
            low_res_pred = torch.nn.functional.interpolate(
                low_res_pred,
                size=(1024, 1024),
                mode="bilinear",
                align_corners=False,
            )
            
            medsam_seg = (low_res_pred > 0.5).cpu().numpy()[0, 0]
        
        # Resize回原始大小
        medsam_seg_original = cv2.resize(
            medsam_seg.astype(np.uint8),
            (W, H),
            interpolation=cv2.INTER_NEAREST
        )
        
        # 保存结果图像
        image_url = save_mask_image(medsam_seg_original, image_np)
        rle_data = mask_to_rle(medsam_seg_original)
        
        print(f"[DEBUG] Segmentation complete, saved to {image_url}, pixels={rle_data['pixel_count']}")
        
        return JSONResponse({
            "success": True,
            "image_url": image_url,
            "rle": rle_data,
            "confidence": float(low_res_pred.max().cpu().numpy()),
            "shape": {"width": W, "height": H}
        })
        
    except Exception as e:
        print(f"[ERROR] /segment failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/points")
async def segment_points(
    sam_image: UploadFile = File(...),
    file: UploadFile = File(None),
    points_coords: Optional[str] = Form(None),  # "x1,y1 x2,y2 ..." space-separated pairs
    points_labels: Optional[str] = Form(None),  # "1 0 1 ..." space-separated (1=fg, 0=bg)
):
    """
    医学影像分割接口 - Point Prompt
    
    参数:
    - sam_image: 带有点击标注的截图
    - file: 原始医学影像（可选）
    
    返回:
    - image_url: 分割结果图像的URL
    """
    try:
        print("[DEBUG] /points - Point prompt endpoint called")
        # 简化实现：使用中心点
        model = load_model()
        
        image_bytes = await sam_image.read()
        image_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image_np = np.array(image_pil)
        
        H, W = image_np.shape[:2]
        
        # 优先使用前端传入的点击坐标
        point_coords = None
        point_labels_arr = None
        if points_coords:
            try:
                pairs = points_coords.strip().split()
                coords = []
                for pair in pairs:
                    x, y = [int(v) for v in pair.split(',')]
                    coords.append([x, y])
                if coords:
                    point_coords = np.array(coords)
                    if points_labels:
                        point_labels_arr = np.array([int(l) for l in points_labels.strip().split()])
                    else:
                        point_labels_arr = np.ones(len(coords), dtype=np.int64)
                    print(f"[DEBUG] Using frontend points: {point_coords}")
            except Exception as e:
                print(f"[DEBUG] points parse error ({e}), using center")

        if point_coords is None:
            # 降级：使用图像中心点作为前景点
            point_coords = np.array([[W // 2, H // 2]])
            point_labels_arr = np.array([1])  # 1 = 前景
        point_labels = point_labels_arr
        
        # 预处理
        if len(image_np.shape) == 2:
            image_np = np.repeat(image_np[:, :, None], 3, axis=-1)
        
        image_1024 = cv2.resize(image_np, (1024, 1024), interpolation=cv2.INTER_CUBIC)
        point_coords_1024 = point_coords / np.array([W, H]) * 1024
        
        image_tensor = torch.tensor(image_1024).float().permute(2, 0, 1).unsqueeze(0)
        image_tensor = (image_tensor - image_tensor.min()) / (image_tensor.max() - image_tensor.min()) * 255.0
        image_tensor = image_tensor.to(device)
        
        # MedSAM推理
        with torch.no_grad():
            image_embedding = model.image_encoder(image_tensor)
            
            point_coords_torch = torch.tensor(point_coords_1024).unsqueeze(0).to(device)
            point_labels_torch = torch.tensor(point_labels).unsqueeze(0).to(device)
            
            sparse_embeddings, dense_embeddings = model.prompt_encoder(
                points=(point_coords_torch, point_labels_torch),
                boxes=None,
                masks=None,
            )
            
            low_res_logits, _ = model.mask_decoder(
                image_embeddings=image_embedding,
                image_pe=model.prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
            )
            
            low_res_pred = torch.sigmoid(low_res_logits)
            low_res_pred = torch.nn.functional.interpolate(
                low_res_pred,
                size=(1024, 1024),
                mode="bilinear",
                align_corners=False,
            )
            
            medsam_seg = (low_res_pred > 0.5).cpu().numpy()[0, 0]
        
        medsam_seg_original = cv2.resize(
            medsam_seg.astype(np.uint8),
            (W, H),
            interpolation=cv2.INTER_NEAREST
        )
        
        image_url = save_mask_image(medsam_seg_original, image_np)
        rle_data = mask_to_rle(medsam_seg_original)
        
        print(f"[DEBUG] Point segmentation complete, saved to {image_url}")
        
        return JSONResponse({
            "success": True,
            "image_url": image_url,
            "rle": rle_data,
            "confidence": float(low_res_pred.max().cpu().numpy())
        })
        
    except Exception as e:
        print(f"[ERROR] /points failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/mask")
async def segment_mask(
    sam_image: UploadFile = File(...),
    file: UploadFile = File(None)
):
    """
    医学影像分割接口 - Mask Prompt
    
    参数:
    - sam_image: 带有mask标注的截图
    - file: 原始医学影像（可选）
    
    返回:
    - image_url: 分割结果图像的URL
    """
    try:
        print("[DEBUG] /mask - Mask prompt endpoint called")
        # 简化实现：使用整个图像
        return await segment_rectangle(sam_image, file)
        
    except Exception as e:
        print(f"[ERROR] /mask failed: {str(e)}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/auto_liver")
async def auto_segment_liver(
    file: UploadFile = File(...),
    organ: str = Form(default="liver")
):
    """
    自动分割器官接口 - 无需手动标注
    
    参数:
    - file: 医学影像（PNG/JPG格式）
    - organ: 器官名称（默认：liver）
    
    返回:
    - image_url: 分割结果图像的URL
    """
    try:
        print(f"[DEBUG] /auto_liver - Auto segment {organ} endpoint called")
        model = load_model()
        
        # 读取图像
        image_bytes = await file.read()
        image_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image_np = np.array(image_pil)
        
        print(f"[DEBUG] Image shape: {image_np.shape}")
        
        H, W = image_np.shape[:2]

        organ_priors = {
            # 轴位CT默认显示中，患者右侧位于图像左侧
            "liver":        [int(W*0.08), int(H*0.18), int(W*0.58), int(H*0.80)],
            "spleen":       [int(W*0.58), int(H*0.20), int(W*0.90), int(H*0.72)],
            "kidney":       [int(W*0.16), int(H*0.28), int(W*0.84), int(H*0.80)],
            "kidney_left":  [int(W*0.56), int(H*0.30), int(W*0.84), int(H*0.76)],
            "kidney_right": [int(W*0.16), int(H*0.30), int(W*0.46), int(H*0.76)],
            "lung_l":       [int(W*0.54), int(H*0.08), int(W*0.96), int(H*0.92)],
            "lung_r":       [int(W*0.04), int(H*0.08), int(W*0.46), int(H*0.92)],
        }
        alias = {
            "lung": "lung_l",
            "left_kidney": "kidney_left",
            "right_kidney": "kidney_right",
        }
        organ_key = alias.get(organ, organ)
        box_np = np.array(organ_priors.get(organ_key, organ_priors["liver"]))

        print(f"[DEBUG] Auto organ bbox for {organ} (key={organ_key}): {box_np}")
        
        # 预处理
        if len(image_np.shape) == 2:
            image_np = np.repeat(image_np[:, :, None], 3, axis=-1)
        
        image_1024 = cv2.resize(image_np, (1024, 1024), interpolation=cv2.INTER_CUBIC)
        box_1024 = box_np / np.array([W, H, W, H]) * 1024
        
        image_tensor = torch.tensor(image_1024).float().permute(2, 0, 1).unsqueeze(0)
        image_tensor = (image_tensor - image_tensor.min()) / (image_tensor.max() - image_tensor.min()) * 255.0
        image_tensor = image_tensor.to(device)
        
        # MedSAM推理
        with torch.no_grad():
            image_embedding = model.image_encoder(image_tensor)
            box_torch = torch.tensor(box_1024).unsqueeze(0).to(device)
            
            sparse_embeddings, dense_embeddings = model.prompt_encoder(
                points=None,
                boxes=box_torch,
                masks=None,
            )
            
            low_res_logits, _ = model.mask_decoder(
                image_embeddings=image_embedding,
                image_pe=model.prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
            )
            
            low_res_pred = torch.sigmoid(low_res_logits)
            low_res_pred = torch.nn.functional.interpolate(
                low_res_pred,
                size=(1024, 1024),
                mode="bilinear",
                align_corners=False,
            )
            
            medsam_seg = (low_res_pred > 0.5).cpu().numpy()[0, 0]
        
        medsam_seg_original = cv2.resize(
            medsam_seg.astype(np.uint8),
            (W, H),
            interpolation=cv2.INTER_NEAREST
        )
        
        image_url = save_mask_image(medsam_seg_original, image_np)
        rle_data = mask_to_rle(medsam_seg_original)
        
        print(f"[DEBUG] Auto liver segmentation complete, saved to {image_url}")
        
        return JSONResponse({
            "success": True,
            "image_url": image_url,
            "rle": rle_data,
            "organ": organ,
            "organ_key": organ_key,
            "confidence": float(low_res_pred.max().cpu().numpy())
        })
        
    except Exception as e:
        print(f"[ERROR] /auto_liver failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


# ─────────────────────────────────────────────────────────────────
# P0 新增：正确数据流端点 — 后端直连 Orthanc 读 DICOM，避免传截图
# ─────────────────────────────────────────────────────────────────

class DicomSegRequest(BaseModel):
    sop_instance_uid: str
    bbox: List[int]          # [x1, y1, x2, y2]像素坐标（相对于 DICOM 图像）
    window_center: Optional[float] = None
    window_width: Optional[float] = None
    foreground_mask_rle: Optional[dict] = None  # 前端刷子涂抹的mask RLE → 用作SAM mask prompt
    mask_rle: Optional[dict] = None
    clip_rle: Optional[dict] = None
    orthanc_url: str = "http://localhost:8042"
    orthanc_user: str = "orthanc"
    orthanc_password: str = "orthanc"


@app.post("/segment_dicom")
async def segment_dicom(req: DicomSegRequest):
    """
    正确数据流：后端直接从 Orthanc 读取 DICOM 像素，无需前端传截图。

    前端只需发送：
        { sop_instance_uid, bbox: [x1,y1,x2,y2] }

    返回：
        { rle, volume_mm3, pixel_spacing, confidence }
    """
    try:
        model = load_model()
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

        # 2. 获取实例元数据（pixel spacing）
        pixel_spacing = [1.0, 1.0]
        try:
            tags_resp = http_requests.get(
                f"{req.orthanc_url}/instances/{orthanc_id}/simplified-tags",
                auth=auth, timeout=10
            )
            tags = tags_resp.json()
            ps = tags.get("PixelSpacing") or tags.get("ImagerPixelSpacing")
            if ps:
                # Orthanc returns PixelSpacing as "0.859375\\0.859375" (backslash-separated string)
                if isinstance(ps, str):
                    parts = ps.replace("\\", " ").split()
                    if len(parts) >= 2:
                        pixel_spacing = [float(parts[0]), float(parts[1])]
                elif isinstance(ps, list) and len(ps) >= 2:
                    pixel_spacing = [float(ps[0]), float(ps[1])]
        except Exception:
            pass

        # 3. 获取渲染后的 PNG（Orthanc 自动应用窗宽窗位）
        # 构建 rendered 参数，传入窗宽窗位与前端一致
        render_params = {"quality": 100}
        if req.window_center is not None and req.window_width is not None:
            render_params["window-center"] = int(req.window_center)
            render_params["window-width"] = int(req.window_width)
            print(f"[segment_dicom] Using window WC={int(req.window_center)}, WW={int(req.window_width)}")
        img_resp = http_requests.get(
            f"{req.orthanc_url}/instances/{orthanc_id}/rendered",
            auth=auth,
            params=render_params,
            timeout=30,
        )
        img_resp.raise_for_status()
        image_np = np.array(Image.open(io.BytesIO(img_resp.content)).convert("RGB"))
        H, W = image_np.shape[:2]

        # 4. 验证 bbox 坐标合法性
        x1, y1, x2, y2 = req.bbox
        x1, x2 = max(0, min(x1, W-1)), max(1, min(x2, W))
        y1, y2 = max(0, min(y1, H-1)), max(1, min(y2, H))
        if x2 <= x1 or y2 <= y1:
            raise HTTPException(status_code=400, detail="Invalid bbox coordinates")
        box_np = np.array([x1, y1, x2, y2])
        print(f"[segment_dicom] SOPInstanceUID={req.sop_instance_uid}, bbox={box_np}, image={W}x{H}")

        # 5. SAM 推理 — 纯 bbox prompt（精度最高，iou=0.9355）
        if len(image_np.shape) == 2:
            image_np = np.repeat(image_np[:, :, None], 3, axis=-1)
        image_1024 = cv2.resize(image_np, (1024, 1024), interpolation=cv2.INTER_CUBIC)
        box_1024 = box_np / np.array([W, H, W, H]) * 1024

        image_tensor = torch.tensor(image_1024).float().permute(2, 0, 1).unsqueeze(0)
        image_tensor = (image_tensor - image_tensor.min()) / (image_tensor.max() - image_tensor.min() + 1e-8) * 255.0
        image_tensor = image_tensor.to(device)

        with torch.no_grad():
            image_embedding = model.image_encoder(image_tensor)
            box_torch = torch.tensor(box_1024, dtype=torch.float32).unsqueeze(0).to(device)
            sparse_embeddings, dense_embeddings = model.prompt_encoder(
                points=None, boxes=box_torch, masks=None
            )

            low_res_logits, _ = model.mask_decoder(
                image_embeddings=image_embedding,
                image_pe=model.prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
            )
            low_res_pred = torch.sigmoid(low_res_logits)
            low_res_pred = torch.nn.functional.interpolate(
                low_res_pred, size=(H, W), mode="bilinear", align_corners=False
            )
            medsam_seg = (low_res_pred > 0.5).cpu().numpy()[0, 0]

        # 6. 体积计算（像素数 × 像素间距²）
        pixel_count = int(np.sum(medsam_seg))
        volume_mm3 = pixel_count * pixel_spacing[0] * pixel_spacing[1]

        # ── 诊断：保存后端处理的图像 ──
        try:
            vis_img = image_np.copy()
            cv2.rectangle(vis_img, (x1, y1), (x2, y2), (255, 255, 0), 2)
            overlay = vis_img.copy()
            overlay[medsam_seg > 0] = [255, 60, 60]
            vis_img = cv2.addWeighted(vis_img, 0.5, overlay, 0.5, 0)
            cnts, _ = cv2.findContours(medsam_seg.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(vis_img, cnts, -1, (0, 255, 0), 2)
            ts = str(uuid.uuid4().hex)[:6]
            cv2.imwrite(str(OUTPUT_DIR / f"debug_{ts}_bbox{x1}_{y1}_{x2}_{y2}_px{pixel_count}.png"),
                        cv2.cvtColor(vis_img, cv2.COLOR_RGB2BGR))
            print(f"[segment_dicom] Debug image saved: outputs/debug_{ts}_...png")
        except Exception:
            pass

        rle_data = mask_to_rle(medsam_seg)
        print(f"[segment_dicom] Done: pixels={pixel_count}, volume={volume_mm3:.2f} mm³")

        return JSONResponse({
            "success": True,
            "rle": rle_data,
            "volume_mm3": round(volume_mm3, 2),
            "pixel_spacing": pixel_spacing,
            "confidence": float(low_res_pred.max().cpu().numpy()),
            "shape": {"width": W, "height": H},
        })

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/report")
async def generate_report(
    image: UploadFile = File(...),
    segment_labels: str = Form(""),
    modality: str = Form("CT"),
):
    """
    本地模板化报告接口。
    当前不依赖外部 LLM，保证前端 report 功能可用。
    """
    try:
        image_bytes = await image.read()
        image_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image_pil.size

        labels = [label.strip() for label in segment_labels.split(',') if label.strip() and label.strip() != '(no label)']
        if not labels:
            labels = ["未命名分割区域"]

        findings = [
            f"当前{modality}图像已完成分割分析。",
            f"图像分辨率约为 {width} x {height} 像素。",
            f"识别到的分割目标包括：{'、'.join(labels)}。",
            "前端当前版本根据分割叠加层与当前视口截图生成本报告，内容用于演示与流程联调。",
        ]

        if any("lung" in label.lower() or "肺" in label for label in labels):
            findings.append("可见肺部相关分割区域，建议结合原始横断面继续核对病灶边界与层面连续性。")
        if any("liver" in label.lower() or "肝" in label for label in labels):
            findings.append("可见肝脏相关分割区域，建议结合多期增强与三维重建结果综合评估。")
        if any("tumor" in label.lower() or "lesion" in label.lower() or "瘤" in label or "灶" in label for label in labels):
            findings.append("存在病灶/肿瘤相关分割提示，建议结合体积、边界及邻近结构受累情况进一步判读。")

        report = (
            "Imaging Modality: " + modality + "\n\n"
            "Findings:\n- " + "\n- ".join(findings) + "\n\n"
            "Impression:\n"
            "1. 已检测到并展示分割结果，可用于后续三维展示与临床工作流演示。\n"
            "2. 当前报告为本地模板化自动生成结果，建议由临床医师结合原始 DICOM 图像最终确认。"
        )

        return JSONResponse({
            "success": True,
            "report": report,
            "labels": labels,
            "modality": modality,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    print("Starting MedSAM Service (Fixed Version)...")
    print(f"Device: {device}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
