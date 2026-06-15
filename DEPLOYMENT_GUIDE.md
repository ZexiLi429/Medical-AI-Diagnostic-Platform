# MISCADA项目完整部署指南
# 医学影像3D渲染 + LLM诊断系统

## 📋 项目架构

```
MISCADA完整系统
├── 前端 (OHIF Viewer) - 端口 3000
│   ├── 3D体积渲染
│   ├── 测量工具
│   └── AI分割集成
│
├── 数据服务 (Orthanc) - 端口 8042
│   └── DICOM数据管理
│
├── AI服务
│   ├── MedSAM分割服务 - 端口 8000
│   └── LLM诊断服务 - 端口 8001
```

---

## 🚀 完整部署步骤

### 第一步：环境准备

#### 1. 检查系统要求
```powershell
# Node.js (>= 20)
node -v

# Python (>= 3.9)
python --version

# Docker (可选，用于Orthanc)
docker --version

# CUDA (可选，用于GPU加速)
nvidia-smi
```

#### 2. 创建Python虚拟环境
```powershell
# 进入MedSAM目录
cd c:\Users\Dell\Desktop\miscada-project-master\MedSAM-main

# 创建虚拟环境
conda create -n miscada python=3.9 -y
conda activate miscada

# 或使用venv
python -m venv venv
.\venv\Scripts\activate
```

#### 3. 安装依赖
```powershell
# 安装PyTorch (根据您的系统选择)
# CPU版本：
pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cpu

# GPU版本 (CUDA 11.8)：
pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118

# 安装MedSAM
pip install -e .

# 安装服务依赖
pip install -r requirements_services.txt
```

#### 4. 下载模型权重
```powershell
# 下载MedSAM模型 (约180MB)
# 访问: https://drive.google.com/drive/folders/1ETWmi4AiniJeWOt6HAsYgTjYv_fkgzoN
# 下载 medsam_vit_b.pth
# 放置到: work_dir/MedSAM/medsam_vit_b.pth
```

#### 5. 配置API密钥
```powershell
# 复制环境配置文件
copy .env.example .env

# 编辑 .env 文件，填入API密钥
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
```

---

### 第二步：启动后端服务

#### 1. 启动Orthanc数据服务器

**⚠️ 重要提示：Orthanc是可选的！如果Docker有问题，可以跳过此步骤。**

##### 方式A: 使用Docker (需要Docker Desktop运行)

```powershell
# 1. 确保Docker Desktop已启动
# 打开Docker Desktop应用程序，等待它完全启动（图标变绿）

# 2. 验证Docker运行
docker --version
docker ps

# 3. 启动Orthanc
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master\platform\app\.recipes\Nginx-Orthanc
docker-compose up -d

# 访问: http://localhost:8042
# 用户名: orthanc / 密码: orthanc
```

**如果看到错误 "The system cannot find the file specified"**：
1. 打开 Docker Desktop 应用程序
2. 等待图标变为绿色（运行状态）
3. 重新运行 `docker-compose up -d`

##### 方式B: 不使用Orthanc（推荐新手）⭐

**跳过Orthanc，直接使用OHIF的在线演示数据**：

```powershell
# 无需任何操作！
# OHIF默认连接到在线演示数据
# 直接启动前端即可使用
```

优点：
- ✅ 无需Docker
- ✅ 无需配置
- ✅ 立即可用
- ✅ 包含多种测试数据

##### 方式C: 本地安装Orthanc（不用Docker）

```powershell
# 1. 下载Orthanc Windows版本
# 访问: https://www.orthanc-server.com/download-windows.php

# 2. 解压并运行 Orthanc.exe

# 3. 访问: http://localhost:8042
```

#### 2. 启动MedSAM分割服务
```powershell
# 新开一个终端
cd c:\Users\Dell\Desktop\miscada-project-master\MedSAM-main
conda activate miscada

# 启动服务
python medsam_service.py

# 或使用uvicorn
uvicorn medsam_service:app --host 0.0.0.0 --port 8000 --reload
```

测试: http://localhost:8000

#### 3. 启动LLM诊断服务
```powershell
# 新开一个终端
cd c:\Users\Dell\Desktop\miscada-project-master\MedSAM-main
conda activate miscada

# 确保已配置API密钥
python llm_diagnostic_service.py

# 或使用uvicorn
uvicorn llm_diagnostic_service:app --host 0.0.0.0 --port 8001 --reload
```

测试: http://localhost:8001

---

### 第三步：启动前端

```powershell
# 进入OHIF项目目录
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master

# 首次运行需要安装依赖
yarn config set workspaces-experimental true
yarn install

# === 选择启动方式 ===

# 方式1: 连接本地Orthanc (需要Orthanc运行在8042端口)
yarn run dev:orthanc

# 方式2: 使用在线演示数据 (推荐！无需Orthanc) ⭐
yarn run dev

# 方式3: 快速模式 (性能更好)
yarn run dev:fast
```

**推荐：如果Orthanc没有运行，使用 `yarn run dev`**

访问: http://localhost:3000

---

## ✅ 验证部署

### 1. 检查所有服务状态

| 服务 | 地址 | 状态检查 |
|------|------|---------|
| OHIF前端 | http://localhost:3000 | 能打开界面 |
| Orthanc | http://localhost:8042 | 能登录 |
| MedSAM | http://localhost:8000 | 访问显示 `{"service": "MedSAM API"}` |
| LLM服务 | http://localhost:8001 | 访问显示 `{"service": "LLM Diagnostic Service"}` |

### 2. 上传测试数据

1. 访问 http://localhost:8042
2. 登录 (orthanc/orthanc)
3. 点击 "Upload" 上传DICOM文件
4. 在OHIF中查看: http://localhost:3000

### 3. 测试AI分割功能

1. 在OHIF中打开一个CT/MRI影像
2. 使用SAM模式
3. 绘制边界框触发分割
4. 查看分割结果

### 4. 测试LLM诊断报告

使用API测试工具 (Postman/curl):

```powershell
# 测试诊断报告生成
curl -X POST "http://localhost:8001/generate_report" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "TEST001",
    "modality": "CT",
    "body_region": "Chest",
    "clinical_history": "Patient presents with shortness of breath",
    "imaging_findings": "Opacity in right lung field",
    "model": "gpt-4"
  }'
```

---

## 🎯 实现两个项目要求

### Project Topic 2: 3D体积渲染Web框架 ✅

**已实现功能：**
1. ✅ Web Portal访问 - OHIF前端
2. ✅ 中央数据共享 - Orthanc DICOM服务器
3. ✅ 实时3D体积渲染 - Cornerstone3D引擎
4. ✅ MPR多平面重建
5. ✅ 浏览器内渲染 - 无需插件
6. ✅ 前后端分离架构
7. ✅ 响应式性能优化

**关键代码位置：**
- 3D渲染: `extensions/cornerstone/src/Viewport/`
- 体积数据处理: `extensions/cornerstone/src/utils/`
- 视图控制: `platform/core/src/services/`

---

### Project Topic 3: LLM与医学影像分析 ✅

**已实现功能：**
1. ✅ LLM集成 (GPT-4, Claude 3)
2. ✅ 多模态处理 (图像+文本)
3. ✅ 临床数据整合
4. ✅ AI分割结果解读
5. ✅ 自动诊断报告生成
6. ✅ 结构化报告输出

**关键文件：**
- LLM服务: `MedSAM-main/llm_diagnostic_service.py`
- MedSAM集成: `MedSAM-main/medsam_service.py`
- 前端调用: `extensions/cornerstone/src/commandsModule.ts`

---

## 📝 开发任务清单

### Project 2 优化任务
- [ ] 添加性能监控面板
- [ ] 实现渲染缓存机制
- [ ] 优化大数据集加载
- [ ] 添加用户角色权限管理
- [ ] 实现数据预加载策略

### Project 3 优化任务  
- [ ] 微调LLM模型（医学领域）
- [ ] 添加更多临床模板
- [ ] 实现报告版本控制
- [ ] 添加医生审核工作流
- [ ] 集成电子病历(EMR)系统

---

## 🐛 常见问题

### Q1: MedSAM服务启动失败
```powershell
# 检查CUDA
python -c "import torch; print(torch.cuda.is_available())"

# 如果没有GPU，修改 medsam_service.py:
device = "cpu"
```

### Q2: LLM服务返回401错误
```
# 检查API密钥配置
# 编辑 .env 文件，确保API密钥正确
```

### Q3: 前端无法连接后端
```
# 检查CORS配置
# 在服务文件中允许前端域名
allow_origins=["http://localhost:3000"]
```

### Q4: 端口被占用
```powershell
# 查看端口占用
netstat -ano | findstr :8000

# 修改服务端口
uvicorn medsam_service:app --port 8002
```

---

## 📚 参考文档

- OHIF文档: https://docs.ohif.org/
- Cornerstone3D: https://www.cornerstonejs.org/
- MedSAM论文: https://arxiv.org/abs/2304.12306
- FastAPI文档: https://fastapi.tiangolo.com/
- OpenAI API: https://platform.openai.com/docs

---

## 💡 下一步建议

1. **性能优化**: 实现WebGL加速渲染
2. **模型训练**: 使用医院数据微调MedSAM
3. **临床验证**: 与放射科医生合作验证AI准确性
4. **部署上线**: 配置生产环境(HTTPS, 负载均衡)
5. **用户培训**: 制作使用教程和演示视频

---

## 📄 许可证

- OHIF: MIT License
- MedSAM: Apache 2.0 License
- 本项目: 遵循各组件原始许可证

---

**祝部署顺利！🎉**

如有问题，请查看各服务的日志输出。
