# Medical AI Diagnostic Platform

<div align="center">

![MedSAM](https://img.shields.io/badge/MedSAM-AI%20Segmentation-blue)
![OHIF](https://img.shields.io/badge/OHIF-3D%20Viewer-green)
![LLM](https://img.shields.io/badge/LLM-Diagnostic%20AI-orange)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

**医学影像AI辅助诊断系统**

[English](#) | [中文文档](#项目简介)

</div>

---

## 🌟 项目简介

**Medical AI Diagnostic Platform (MISCADA)** 是一个集成了人工智能医学影像分割、3D体积渲染和大语言模型诊断辅助的综合性医疗影像平台。

### 核心功能

- 🎨 **3D医学影像查看器** - 基于OHIF Viewer 3.x，支持实时浏览器端3D渲染
- 🤖 **AI智能分割** - 集成MedSAM模型，支持器官、病灶的智能识别和分割
- 🧠 **LLM诊断辅助** - 利用GPT-4/Claude 3生成结构化医学诊断报告
- 📊 **多平面重建** - MPR视图（轴向/冠状/矢状）
- 💾 **DICOM标准支持** - 完整的医学影像数据管理

---

## 🚀 快速开始

### 前置要求

- Python 3.8+
- Node.js 16+
- 8GB+ RAM
- （可选）NVIDIA GPU用于加速推理

### 安装步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/YOUR_USERNAME/Medical-AI-Diagnostic-Platform.git
cd Medical-AI-Diagnostic-Platform
```

#### 2. 下载MedSAM模型

下载预训练模型 `medsam_vit_b.pth` 到：
```
MedSAM-main/work_dir/MedSAM/medsam_vit_b.pth
```

模型下载链接: [Google Drive](https://drive.google.com/drive/folders/1ETWmi4AiniJeWOt6HAsYgTjYv_fkgzoN)

#### 3. 安装Python依赖

```bash
cd MedSAM-main
pip install -r requirements_services.txt
```

#### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，添加你的OpenAI或Anthropic API密钥
```

#### 5. 启动服务

**Windows用户：**
```bash
双击运行: start_all.bat
```

**Linux/Mac用户：**
```bash
# 启动MedSAM分割服务
cd MedSAM-main
python medsam_service.py &

# 启动LLM诊断服务
python llm_diagnostic_service.py &

# 启动前端
cd ../miscada-project-master
yarn install
yarn run dev:orthanc
```

#### 6. 访问应用

- 🖥️ **OHIF前端**: http://localhost:3000
- 🤖 **MedSAM API**: http://localhost:8000
- 🧠 **LLM API**: http://localhost:8001
- 💾 **Orthanc服务器**: http://localhost:8042

---

## 📖 文档

| 文档 | 描述 |
|------|------|
| [项目状态报告](./项目状态报告.md) | 已解决和待解决问题清单 |
| [快速启动指南](./QUICK_START.md) | 3步快速启动教程 |
| [部署指南](./DEPLOYMENT_GUIDE.md) | 完整部署说明 |
| [前端集成](./FRONTEND_INTEGRATION.md) | 前端开发和集成教程 |
| [MedSAM功能说明](./MEDSAM_功能说明.md) | AI分割功能详解 |
| [后端修复说明](./MedSAM后端修复说明.md) | 接口修复和故障排查 |

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    用户浏览器                            │
│              http://localhost:3000                      │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────▼───────────┐
         │   OHIF Viewer 3.x     │
         │  (React + TypeScript) │
         │  - 3D渲染              │
         │  - MPR视图             │
         │  - 工具栏              │
         └───────────┬───────────┘
                     │
      ┌──────────────┼──────────────┐
      │              │              │
┌─────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
│  Orthanc   │ │ MedSAM   │ │ LLM诊断    │
│   DICOM    │ │   API    │ │   API      │
│   Server   │ │ (FastAPI)│ │ (FastAPI)  │
│   :8042    │ │  :8000   │ │   :8001    │
└────────────┘ └──────────┘ └────────────┘
                     │              │
                ┌────▼──────┐  ┌───▼──────┐
                │  MedSAM   │  │ GPT-4 /  │
                │  Model    │  │ Claude 3 │
                │ (PyTorch) │  │  (API)   │
                └───────────┘  └──────────┘
```

---

## 🎯 主要功能

### 1. AI智能分割

- **器官分割**: 肺、肝、心、肾、脑等
- **病灶检测**: 肿瘤、结节、囊肿
- **异常识别**: 肺炎、骨折、积液

**支持的提示模式**:
- 矩形框提示 (Rectangle prompt)
- 点击提示 (Point prompt)
- 掩码提示 (Mask prompt)
- 自动分割模式

### 2. 3D体积渲染

- WebGL加速渲染
- 实时交互操作
- 窗宽窗位调整
- 多平面重建（MPR）

### 3. LLM诊断报告

- 结构化医学报告生成
- 多模态输入分析
- 临床数据整合
- 诊断建议和解释

---

## 🛠️ 技术栈

### 前端
- **框架**: React 18 + TypeScript
- **医学影像**: OHIF Viewer 3.x, Cornerstone3D
- **3D渲染**: WebGL, VTK.js
- **UI**: React UI Components

### 后端
- **框架**: FastAPI + Uvicorn
- **AI模型**: MedSAM (ViT-B), PyTorch
- **LLM**: OpenAI GPT-4, Anthropic Claude 3
- **图像处理**: OpenCV, Pillow, NumPy

### 数据服务
- **DICOM服务器**: Orthanc
- **协议**: DICOM Web, DICOMweb
- **存储**: 本地文件系统/云存储

---

## 📊 项目状态

### 已完成 ✅

- [x] 3D体积渲染Web框架
- [x] MedSAM分割API集成
- [x] LLM诊断报告生成
- [x] 前后端接口对接
- [x] 一键启动脚本
- [x] 完整文档

### 进行中 🔄

- [ ] 设备性能自适应
- [ ] SAM 3D可视化
- [ ] Docker容器化部署
- [ ] 测试数据集

### 计划中 📋

- [ ] 用户认证系统
- [ ] 多语言支持
- [ ] HIS/PACS系统集成
- [ ] 移动端适配

详见 [项目状态报告](./项目状态报告.md)

---

## 🤝 贡献指南

我们欢迎各种形式的贡献！

### 如何贡献

1. Fork 本仓库
2. 创建功能分支: `git checkout -b feature/amazing-feature`
3. 提交更改: `git commit -m 'Add amazing feature'`
4. 推送到分支: `git push origin feature/amazing-feature`
5. 提交Pull Request

### 开发规范

- 遵循代码风格指南
- 添加适当的注释和文档
- 编写单元测试
- 更新相关文档

---

## 📝 许可证

本项目遵循 **Apache License 2.0** 许可证。

MedSAM模型遵循其原始许可证。详见 [LICENSE](./LICENSE) 文件。

---

## 🙏 致谢

本项目基于以下优秀的开源项目：

- [OHIF Viewer](https://github.com/OHIF/Viewers) - 医学影像查看器
- [MedSAM](https://github.com/bowang-lab/MedSAM) - 医学影像分割模型
- [Cornerstone3D](https://github.com/cornerstonejs/cornerstone3D) - 医学影像渲染引擎
- [Orthanc](https://www.orthanc-server.com/) - DICOM服务器

---

## 📞 联系方式

- 📧 Email: [待补充]
- 💬 Issues: [GitHub Issues](https://github.com/YOUR_USERNAME/Medical-AI-Diagnostic-Platform/issues)
- 📖 文档: [项目Wiki](https://github.com/YOUR_USERNAME/Medical-AI-Diagnostic-Platform/wiki)

---

## ⭐ Star History

如果这个项目对你有帮助，请给我们一个Star！⭐

---

<div align="center">

**Made with ❤️ for Medical Imaging Community**

</div>
