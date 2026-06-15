# Docker问题快速解决方案

## 问题：Docker Desktop未运行

错误信息：
```
unable to get image 'webapp:latest'
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified
```

---

## ⚡ 快速解决方案（3选1）

### 🥇 方案1: 不使用Orthanc（最简单）⭐⭐⭐

**直接跳过Orthanc，使用OHIF的在线演示数据**：

```powershell
# 进入前端目录
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master

# 启动前端（使用在线数据）
yarn run dev
```

**优点**：
- ✅ 无需Docker
- ✅ 无需配置
- ✅ 立即可用
- ✅ 包含CT、MRI、PET等多种演示数据
- ✅ 可以测试所有功能

**访问**：http://localhost:3000

---

### 🥈 方案2: 启动Docker Desktop

如果您需要上传自己的DICOM文件：

```powershell
# 1. 打开Windows开始菜单
# 2. 搜索 "Docker Desktop"
# 3. 点击启动
# 4. 等待Docker图标变为绿色（约30秒）
# 5. 重新运行命令

cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master\platform\app\.recipes\Nginx-Orthanc
docker-compose up -d
```

**如果Docker Desktop未安装**：
```
下载地址: https://www.docker.com/products/docker-desktop/
安装后重启电脑
```

---

### 🥉 方案3: 本地安装Orthanc（不用Docker）

```powershell
# 1. 下载Orthanc for Windows
# 访问: https://www.orthanc-server.com/download-windows.php

# 2. 下载最新版本的 Orthanc-Win64.zip

# 3. 解压到某个目录，例如：
# C:\Orthanc

# 4. 双击运行 Orthanc.exe

# 5. 访问: http://localhost:8042
# 用户名: orthanc
# 密码: orthanc
```

---

## 🎯 推荐方案总结

| 场景 | 推荐方案 | 难度 |
|------|---------|------|
| **快速测试项目** | 方案1: 用在线数据 ⭐ | 最简单 |
| **上传自己的DICOM** | 方案2或3: 安装Orthanc | 中等 |
| **生产环境部署** | 方案2: Docker | 专业 |

---

## 📋 当前推荐操作

**如果只是想先运行起来看看效果**：

```powershell
# 1. 跳过Orthanc
# 2. 直接启动前端
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master
yarn run dev

# 3. 访问
# http://localhost:3000
```

**系统会自动使用AWS S3上的演示数据，包含**：
- ✅ CT扫描
- ✅ MRI数据
- ✅ PET-CT
- ✅ 多种分辨率
- ✅ 完整的DICOM元数据

---

## 🔧 Docker Desktop问题排查

如果您确实需要Docker但遇到问题：

### 检查1: Docker Desktop是否安装
```powershell
docker --version
```
如果提示"不是内部或外部命令"，说明未安装。

### 检查2: Docker服务是否运行
```powershell
# 查看Docker进程
Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue

# 查看Docker状态
docker info
```

### 检查3: WSL2是否安装（Docker Desktop需要）
```powershell
# 检查WSL
wsl --list --verbose

# 如果未安装，运行
wsl --install
```

### 检查4: Hyper-V是否启用（Windows专业版）
```
控制面板 → 程序 → 启用或关闭Windows功能
勾选 "Hyper-V" 和 "虚拟机平台"
```

---

## 💡 测试项目的最佳路径

```
阶段1: 基础功能测试（无需Orthanc）
├── 使用 yarn run dev
├── 测试基础查看器
├── 测试MPR布局
├── 测试分割模式
└── 验证前端功能正常

阶段2: AI功能测试（需要后端服务）
├── 启动MedSAM服务 (python medsam_service.py)
├── 启动LLM服务 (可选)
└── 测试AI分割功能

阶段3: 自定义数据（可选，需要Orthanc）
├── 安装Orthanc
├── 上传自己的DICOM
└── 在OHIF中查看
```

---

## ⚠️ 常见误区

**误区1**: "必须有Orthanc才能使用OHIF"
- ❌ 错误！OHIF默认连接在线数据源
- ✅ Orthanc只是数据源之一

**误区2**: "必须用Docker"
- ❌ 错误！Orthanc有独立安装版
- ✅ Docker只是部署方式之一

**误区3**: "没有数据无法测试"
- ❌ 错误！OHIF提供丰富的在线演示数据
- ✅ 足够测试所有功能

---

## 🚀 立即开始（1分钟）

```powershell
# 1. 打开PowerShell
# 2. 进入项目目录
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master

# 3. 启动（使用在线数据）
yarn run dev

# 4. 等待编译完成（约30秒）
# 5. 浏览器访问 http://localhost:3000
# 6. 开始使用！
```

---

**现在您可以完全跳过Orthanc，直接测试项目的所有功能！** 🎉

等以后需要上传自己的DICOM数据时，再回来安装Orthanc。
