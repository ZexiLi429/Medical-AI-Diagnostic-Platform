"""
LLM Medical Diagnostic Service
整合大语言模型与医学影像分析，生成诊断报告
"""
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import openai
import anthropic
import base64
import json
from datetime import datetime
import os

app = FastAPI(title="LLM Diagnostic Service", version="1.0.0")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8042"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API配置 - 从环境变量读取
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 医学影像分析提示词模板
RADIOLOGY_ANALYSIS_PROMPT = """You are an expert radiologist AI assistant. Analyze the provided medical imaging data and clinical information to generate a comprehensive diagnostic report.

**Patient Information:**
{patient_info}

**Clinical History:**
{clinical_history}

**Imaging Findings:**
{imaging_findings}

**Segmentation Results:**
{segmentation_results}

**Measurements:**
{measurements}

Please provide:
1. **Findings Summary**: Detailed description of abnormalities detected
2. **Diagnostic Impression**: Primary and differential diagnoses
3. **Recommendations**: Suggested follow-up or additional studies
4. **Confidence Level**: Your confidence in the diagnosis (High/Medium/Low)

Format the response as a structured medical report."""


class DiagnosticRequest(BaseModel):
    """诊断请求数据模型"""
    patient_id: Optional[str] = "Unknown"
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    modality: str  # CT, MRI, X-Ray, etc.
    body_region: str  # Head, Chest, Abdomen, etc.
    clinical_history: Optional[str] = ""
    imaging_findings: Optional[str] = ""
    segmentation_results: Optional[Dict[str, Any]] = {}
    measurements: Optional[List[Dict[str, Any]]] = []
    image_base64: Optional[str] = None
    model: str = "gpt-4"  # gpt-4, gpt-4-vision, claude-3-opus, etc.


class DiagnosticResponse(BaseModel):
    """诊断响应数据模型"""
    success: bool
    report: Optional[str] = None
    structured_findings: Optional[Dict[str, Any]] = None
    timestamp: str
    model_used: str
    error: Optional[str] = None


@app.get("/")
async def root():
    """服务信息"""
    return {
        "service": "LLM Diagnostic Service",
        "status": "running",
        "supported_models": ["gpt-4", "gpt-4-vision", "claude-3-opus", "claude-3-sonnet"],
        "openai_configured": bool(OPENAI_API_KEY),
        "anthropic_configured": bool(ANTHROPIC_API_KEY)
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


def format_patient_info(request: DiagnosticRequest) -> str:
    """格式化患者信息"""
    info = f"Patient ID: {request.patient_id}\n"
    if request.patient_age:
        info += f"Age: {request.patient_age}\n"
    if request.patient_gender:
        info += f"Gender: {request.patient_gender}\n"
    info += f"Modality: {request.modality}\n"
    info += f"Body Region: {request.body_region}\n"
    return info


def format_segmentation_results(results: Dict[str, Any]) -> str:
    """格式化分割结果"""
    if not results:
        return "No segmentation performed"
    
    output = "Segmentation Analysis:\n"
    if "organs" in results:
        output += f"- Organs detected: {', '.join(results['organs'])}\n"
    if "lesions" in results:
        output += f"- Lesions detected: {results['lesions']} total\n"
    if "volume" in results:
        output += f"- Total volume: {results['volume']:.2f} cm³\n"
    return output


def format_measurements(measurements: List[Dict[str, Any]]) -> str:
    """格式化测量数据"""
    if not measurements:
        return "No measurements available"
    
    output = "Measurements:\n"
    for i, measurement in enumerate(measurements, 1):
        output += f"{i}. {measurement.get('type', 'Unknown')}: "
        if 'length' in measurement:
            output += f"{measurement['length']:.2f} mm"
        if 'area' in measurement:
            output += f", Area: {measurement['area']:.2f} mm²"
        if 'volume' in measurement:
            output += f", Volume: {measurement['volume']:.2f} mm³"
        output += "\n"
    return output


async def generate_with_openai(prompt: str, model: str, image_base64: Optional[str] = None) -> str:
    """使用OpenAI生成诊断报告"""
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured")
    
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    
    try:
        if image_base64 and "vision" in model:
            # GPT-4 Vision with image
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000
            )
        else:
            # Text-only GPT-4
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert radiologist providing diagnostic interpretations."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3  # Lower temperature for more consistent medical reports
            )
        
        return response.choices[0].message.content
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")


async def generate_with_anthropic(prompt: str, model: str, image_base64: Optional[str] = None) -> str:
    """使用Anthropic Claude生成诊断报告"""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="Anthropic API key not configured")
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    try:
        if image_base64:
            # Claude with vision
            message = client.messages.create(
                model=model,
                max_tokens=2000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ],
                    }
                ],
            )
        else:
            # Text-only Claude
            message = client.messages.create(
                model=model,
                max_tokens=2000,
                temperature=0.3,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
        
        return message.content[0].text
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Anthropic API error: {str(e)}")


@app.post("/generate_report", response_model=DiagnosticResponse)
async def generate_diagnostic_report(request: DiagnosticRequest):
    """
    生成AI辅助诊断报告
    
    整合：
    1. 患者信息和临床病史
    2. 影像发现
    3. AI分割结果
    4. 测量数据
    5. (可选) 影像图片
    """
    try:
        # 构建完整的提示词
        prompt = RADIOLOGY_ANALYSIS_PROMPT.format(
            patient_info=format_patient_info(request),
            clinical_history=request.clinical_history or "No clinical history provided",
            imaging_findings=request.imaging_findings or "No specific findings reported",
            segmentation_results=format_segmentation_results(request.segmentation_results),
            measurements=format_measurements(request.measurements)
        )
        
        # 根据模型选择生成方法
        if request.model.startswith("gpt"):
            report_text = await generate_with_openai(prompt, request.model, request.image_base64)
        elif request.model.startswith("claude"):
            report_text = await generate_with_anthropic(prompt, request.model, request.image_base64)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported model: {request.model}")
        
        # TODO: 解析结构化字段
        structured_findings = {
            "generated_at": datetime.now().isoformat(),
            "model": request.model,
            "patient_id": request.patient_id
        }
        
        return DiagnosticResponse(
            success=True,
            report=report_text,
            structured_findings=structured_findings,
            timestamp=datetime.now().isoformat(),
            model_used=request.model
        )
    
    except HTTPException:
        raise
    except Exception as e:
        return DiagnosticResponse(
            success=False,
            timestamp=datetime.now().isoformat(),
            model_used=request.model,
            error=str(e)
        )


@app.post("/analyze_image_with_context")
async def analyze_image_with_context(
    image: UploadFile = File(...),
    clinical_data: str = Form(...)
):
    """
    分析医学影像并结合临床上下文生成报告
    """
    try:
        # 读取图像并转换为base64
        image_bytes = await image.read()
        image_base64 = base64.b64encode(image_bytes).decode()
        
        # 解析临床数据
        clinical_dict = json.loads(clinical_data)
        
        # 创建诊断请求
        request = DiagnosticRequest(
            patient_id=clinical_dict.get("patient_id"),
            modality=clinical_dict.get("modality", "CT"),
            body_region=clinical_dict.get("body_region", "Unknown"),
            clinical_history=clinical_dict.get("clinical_history", ""),
            model="gpt-4-vision",
            image_base64=image_base64
        )
        
        # 生成报告
        result = await generate_diagnostic_report(request)
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch_analyze")
async def batch_analyze_studies(requests: List[DiagnosticRequest]):
    """
    批量分析多个病例
    """
    results = []
    for request in requests:
        try:
            result = await generate_diagnostic_report(request)
            results.append(result)
        except Exception as e:
            results.append(DiagnosticResponse(
                success=False,
                timestamp=datetime.now().isoformat(),
                model_used=request.model,
                error=str(e)
            ))
    
    return {"total": len(requests), "results": results}


if __name__ == "__main__":
    import uvicorn
    print("Starting LLM Diagnostic Service...")
    print(f"OpenAI configured: {bool(OPENAI_API_KEY)}")
    print(f"Anthropic configured: {bool(ANTHROPIC_API_KEY)}")
    uvicorn.run(app, host="0.0.0.0", port=8001)
