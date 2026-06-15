"""
MedSAM FastAPI Service - 修复版
医学影像分割API服务 - 兼容前端接口
"""
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
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

# 模型检查点路径
MODEL_CHECKPOINT = "work_dir/MedSAM/medsam_vit_b.pth"


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
    file: UploadFile = File(None)  # 原始图像（可选）
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
        
        # 自动使用整个图像中心80%区域作为bbox
        H, W = image_np.shape[:2]
        margin = 0.1
        x1, y1 = int(W * margin), int(H * margin)
        x2, y2 = int(W * (1 - margin)), int(H * (1 - margin))
        box_np = np.array([x1, y1, x2, y2])
        
        print(f"[DEBUG] Auto bbox: {box_np}")
        
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
        
        print(f"[DEBUG] Segmentation complete, saved to {image_url}")
        
        return JSONResponse({
            "success": True,
            "image_url": image_url,
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
    file: UploadFile = File(None)
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
        
        # 使用图像中心点作为前景点
        point_coords = np.array([[W // 2, H // 2]])
        point_labels = np.array([1])  # 1 = 前景
        
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
        
        print(f"[DEBUG] Point segmentation complete, saved to {image_url}")
        
        return JSONResponse({
            "success": True,
            "image_url": image_url,
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
        
        # 自动检测肝脏区域（简化版：使用右上区域作为启发式）
        H, W = image_np.shape[:2]
        
        # 肝脏通常在图像右上方区域
        x1, y1 = int(W * 0.4), int(H * 0.2)
        x2, y2 = int(W * 0.9), int(H * 0.7)
        box_np = np.array([x1, y1, x2, y2])
        
        print(f"[DEBUG] Auto liver bbox: {box_np}")
        
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
        
        print(f"[DEBUG] Auto liver segmentation complete, saved to {image_url}")
        
        return JSONResponse({
            "success": True,
            "image_url": image_url,
            "organ": organ,
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


if __name__ == "__main__":
    import uvicorn
    print("Starting MedSAM Service (Fixed Version)...")
    print(f"Device: {device}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
