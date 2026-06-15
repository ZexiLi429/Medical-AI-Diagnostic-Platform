# ⚡ MISCADA 快速参考卡片

## 📌 快速启动 (3步)

```powershell
# 1️⃣ 下载模型 (必需!)
# 下载 medsam_vit_b.pth 到:
# MedSAM-main/work_dir/MedSAM/medsam_vit_b.pth
# https://drive.google.com/drive/folders/1ETWmi4AiniJeWOt6HAsYgTjYv_fkgzoN

# 2️⃣ 安装依赖
cd MedSAM-main
pip install -r requirements_services.txt

# 3️⃣ 启动
# 双击运行: start_all.bat
# 或手动启动各服务(见下方)
```

---

## 🚀 服务启动命令

### 后端服务

```powershell
# MedSAM分割服务 (端口8000)
cd MedSAM-main
python medsam_service.py

# LLM诊断服务 (端口8001)
cd MedSAM-main
python llm_diagnostic_service.py
```

### 前端服务

```powershell
# OHIF前端 (端口3000)
cd miscada-project-master
yarn run dev:orthanc

# Orthanc数据服务器 (端口8042)
cd platform\app\.recipes\Nginx-Orthanc
docker-compose up -d
```

---

## 🌐 访问地址

| 服务 | 地址 | 用途 |
|------|------|------|
| 🖥️ **OHIF前端** | http://localhost:3000 | 医学影像查看器 |
| 🤖 **MedSAM API** | http://localhost:8000 | AI分割服务 |
| 🧠 **LLM API** | http://localhost:8001 | 诊断报告生成 |
| 💾 **Orthanc** | http://localhost:8042 | DICOM数据管理 |

**Orthanc登录**: 用户名 `orthanc` / 密码 `orthanc`

---

## 🧪 快速测试

```powershell
# 运行自动化测试
cd MedSAM-main
python test_services.py
```

---

## 📁 关键文件位置

### 后端代码
- MedSAM服务: `MedSAM-main/medsam_service.py`
- LLM服务: `MedSAM-main/llm_diagnostic_service.py`
- 环境配置: `MedSAM-main/.env` (从.env.example复制)

### 前端代码
- 命令实现: `extensions/cornerstone/src/commandsModule.ts`
- 工具栏按钮: `modes/sam/src/toolbarButtons.ts`
- 模式配置: `modes/sam/src/index.tsx`

### 文档
- 📘 部署指南: `DEPLOYMENT_GUIDE.md`
- 📗 集成指南: `FRONTEND_INTEGRATION.md`
- 📙 项目总结: `PROJECT_SUMMARY.md`

---

## ⚙️ 环境配置

### Python依赖
```bash
pip install fastapi uvicorn torch torchvision
pip install opencv-python Pillow numpy
pip install openai anthropic  # LLM客户端
```

### LLM API密钥 (可选)
```bash
# 编辑 MedSAM-main/.env
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

---

## 🔧 常见问题速查

### Q: MedSAM服务无法启动
```powershell
# 检查CUDA
python -c "import torch; print(torch.cuda.is_available())"
# 如果False，服务会自动使用CPU
```

### Q: LLM服务返回错误
```bash
# 检查API密钥配置
# 编辑 .env 文件，添加正确的API密钥
```

### Q: 端口被占用
```powershell
# 查看端口占用
netstat -ano | findstr :8000
# 修改服务端口
uvicorn medsam_service:app --port 8002
```

### Q: 前端启动失败
```bash
# 重新安装依赖
yarn clean
yarn install
```

---

## 📊 API快速调用

### MedSAM分割
```javascript
const formData = new FormData();
formData.append('image', imageBlob);
formData.append('bbox', '100,100,300,300');

const response = await fetch('http://localhost:8000/segment', {
  method: 'POST',
  body: formData
});
const result = await response.json();
```

### LLM诊断报告
```javascript
const response = await fetch('http://localhost:8001/generate_report', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    patient_id: 'PT001',
    modality: 'CT',
    body_region: 'Chest',
    clinical_history: '...',
    model: 'gpt-4'
  })
});
const result = await response.json();
console.log(result.report);
```

---

## ✅ 验证清单

- [ ] MedSAM模型已下载
- [ ] Python依赖已安装
- [ ] MedSAM服务能访问 (http://localhost:8000)
- [ ] LLM服务能访问 (http://localhost:8001)
- [ ] OHIF前端能访问 (http://localhost:3000)
- [ ] Orthanc能登录 (http://localhost:8042)
- [ ] 能上传DICOM文件
- [ ] 能查看3D渲染

---

## 🎯 项目功能总览

### ✅ Project 2: 3D体积渲染
- Web Portal访问
- 实时3D渲染
- MPR多平面重建
- 中央数据管理

### ✅ Project 3: LLM诊断
- AI影像分析
- 诊断报告生成
- 多模态数据融合
- 临床上下文理解

---

## 💡 提示

- 📚 详细文档见各MD文件
- 🔍 出现问题先查看服务日志
- 🧪 使用 `test_services.py` 诊断
- 🚀 首次启动需等待约30秒

---

**🎉 准备好了吗？运行 `start_all.bat` 开始！**
