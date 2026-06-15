# DICOM 测试数据获取和上传指南

## 📦 测试数据来源

### 1. **TCIA (The Cancer Imaging Archive)** ⭐ 推荐
最专业的医学影像数据库，包含大量真实临床数据。

**网址**: https://www.cancerimagingarchive.net/

**推荐数据集**:
- **[LIDC-IDRI](https://www.cancerimagingarchive.net/collection/lidc-idri/)** - 肺部CT扫描，适合测试3D渲染和分割
  - 1018个病例，胸部CT图像
  - 包含肺结节标注
  - 文件大小: 124GB（可选择单个病例下载，约100-200MB/例）

- **[TCGA-GBM](https://www.cancerimagingarchive.net/collection/tcga-gbm/)** - 脑胶质母细胞瘤MRI
  - 适合测试多模态医学影像（T1、T2、FLAIR等序列）
  - 每个病例约50-100MB

- **[CT Colonography](https://www.cancerimagingarchive.net/collection/ct-colonography/)** - 结肠CT扫描
  - 825个病例
  - 适合测试高分辨率3D渲染

**如何下载**:
1. 访问 TCIA 网站
2. 选择数据集（Collections）
3. 点击 "Access the Images" → Download NBIA Data Retriever
4. 安装 NBIA Data Retriever 工具
5. 下载 `.tcia` 清单文件
6. 在 NBIA 工具中打开清单文件下载影像

---

### 2. **OsiriX DICOM Sample Data** ⭐ 快速测试推荐
预处理好的小样本数据，无需注册，直接下载。

**网址**: https://www.osirix-viewer.com/resources/dicom-image-library/

**推荐数据**:
- **MANIX** - 全身CT扫描（约300张切片）
  - 文件大小: 约100MB
  - 适合测试3D体积渲染
  - 下载: https://www.osirix-viewer.com/datasets/DATA/MANIX.zip

- **BRAINIX** - 脑部MRI扫描
  - 多序列MRI数据
  - 文件大小: 约50MB
  - 适合测试多模态影像查看

- **KNIX** - 膝关节MRI
  - 文件大小: 约20MB
  - 适合快速测试SAM分割功能

**如何下载**:
```powershell
# 直接下载 ZIP 文件
Invoke-WebRequest -Uri "https://www.osirix-viewer.com/datasets/DATA/MANIX.zip" -OutFile "MANIX.zip"

# 解压
Expand-Archive -Path "MANIX.zip" -DestinationPath "test-data/MANIX"
```

---

### 3. **NIH Visible Human Project**
人体解剖学数据，高精度CT和MRI扫描。

**网址**: https://www.nlm.nih.gov/databases/download/vhp.html

**特点**:
- 超高分辨率（断层扫描）
- 适合测试极限性能
- 需要申请账号下载

---

### 4. **Medical Segmentation Decathlon**
专门用于医学影像分割的数据集。

**网址**: http://medicaldecathlon.com/

**推荐任务**:
- Task01_BrainTumour - 脑肿瘤 MRI
- Task03_Liver - 肝脏 CT（包含肿瘤标注）
- Task06_Lung - 肺部 CT

**特点**:
- 包含 Ground Truth 分割标注
- 适合验证 SAM 分割准确性

---

### 5. **3D-IRCADb (肝脏CT数据集)**
专门用于肝脏图像研究。

**网址**: https://www.ircad.fr/research/data-sets/liver-segmentation-3d-ircadb-01/

**特点**:
- 20个肝脏CT病例（每例300-400张切片）
- 包含肿瘤标注
- 文件大小: 每个病例约200-300MB
- 免费下载，需注册

---

### 6. **DICOM Library - 免费测试文件** ⭐ 最简单测试
快速测试用的小文件集合。

**网址**: https://dicomlibrary.com/

**推荐**:
- Chest CT - 胸部CT：https://dicomlibrary.com/meddream/?study=1.3.12.2.1107.5.2.19.45152.2013030808110258929378490
- Brain MRI - 脑部MRI：https://dicomlibrary.com/meddream/?study=1.3.12.2.1107.5.2.19.45152.2013030808292342191372490

**如何使用**:
1. 在浏览器中打开链接
2. 点击右上角下载按钮
3. 选择 "Download as ZIP"

---

### 7. **Kaggle 医学影像数据集**
各种医学影像竞赛数据。

**网址**: https://www.kaggle.com/datasets

**推荐数据集**:
- [RSNA Pneumonia Detection Challenge](https://www.kaggle.com/c/rsna-pneumonia-detection-challenge) - 肺炎检测胸部X光
- [SIIM-ACR Pneumothorax Segmentation](https://www.kaggle.com/c/siim-acr-pneumothorax-segmentation) - 气胸分割CT
- [COVID-19 CT Scans](https://www.kaggle.com/datasets/andrewmvd/covid19-ct-scans) - 新冠肺炎CT

---

## 📤 上传数据到 OHIF

### 方法1: 通过 Orthanc 上传（需要运行本地服务器）

#### 启动 Orthanc
```powershell
# 如果使用 Docker
cd miscada-project-master
docker-compose up -d

# 访问 Orthanc Web UI
# 浏览器打开: http://localhost:8042
# 默认用户名: orthanc
# 默认密码: orthanc
```

#### 上传 DICOM 文件
1. 打开 http://localhost:8042
2. 点击顶部的 "Upload" 按钮
3. 选择 DICOM 文件（支持 .dcm 文件或整个文件夹）
4. 点击 "Start Upload"
5. 上传完成后，在 OHIF 中刷新即可看到新数据

---

### 方法2: 直接通过 OHIF 本地文件模式 ⭐ 最简单

OHIF 支持直接拖放 DICOM 文件到浏览器！

#### 步骤:
1. **启动 OHIF 开发服务器**
   ```powershell
   cd miscada-project-master
   yarn run dev
   ```

2. **打开浏览器**
   - 访问: http://localhost:3000

3. **拖放 DICOM 文件**
   - 直接将 DICOM 文件（.dcm）拖到浏览器窗口
   - 或者点击 "Study List" 页面的上传按钮
   - 支持拖放整个文件夹

4. **查看影像**
   - 上传完成后，点击 Study 即可查看

**注意**: 
- 本地上传模式需要文件名符合 DICOM 标准
- 建议使用从 TCIA 或 OsiriX 下载的标准 DICOM 文件

---

### 方法3: 使用 Orthanc 命令行工具上传

#### 使用 Python 脚本上传
```python
# upload_dicom.py
import requests
import os
import glob

ORTHANC_URL = "http://localhost:8042"
AUTH = ("orthanc", "orthanc")

def upload_dicom_folder(folder_path):
    dcm_files = glob.glob(os.path.join(folder_path, "**/*.dcm"), recursive=True)
    
    for dcm_file in dcm_files:
        with open(dcm_file, 'rb') as f:
            response = requests.post(
                f"{ORTHANC_URL}/instances",
                auth=AUTH,
                files={'file': f}
            )
            if response.status_code == 200:
                print(f"✓ Uploaded: {dcm_file}")
            else:
                print(f"✗ Failed: {dcm_file} - {response.text}")

# 使用示例
upload_dicom_folder("test-data/MANIX")
```

#### 运行上传脚本
```powershell
python upload_dicom.py
```

---

## 🧪 推荐测试方案

### 快速测试（5分钟内完成）

**目标**: 验证系统基本功能

1. **下载 OsiriX KNIX 数据集**（20MB，膝关节MRI）
   ```powershell
   Invoke-WebRequest -Uri "https://www.osirix-viewer.com/datasets/DATA/KNIX.zip" -OutFile "KNIX.zip"
   Expand-Archive -Path "KNIX.zip" -DestinationPath "test-data/KNIX"
   ```

2. **启动 OHIF**
   ```powershell
   cd miscada-project-master
   yarn run dev
   ```

3. **浏览器打开**: http://localhost:3000

4. **拖放 DICOM 文件** 到浏览器（test-data/KNIX 文件夹中的所有 .dcm 文件）

5. **选择模式**: "Segmentation" 或 "MedSAM Viewer"

6. **测试功能**:
   - 查看 2D 切片
   - 切换到 MPR（多平面重建）
   - 使用 Rectangle 工具绘制区域

---

### 完整测试（30分钟）

**目标**: 测试 3D 渲染和 SAM 分割

1. **下载 MANIX 数据集**（100MB，全身CT）
   ```powershell
   Invoke-WebRequest -Uri "https://www.osirix-viewer.com/datasets/DATA/MANIX.zip" -OutFile "MANIX.zip"
   Expand-Archive -Path "MANIX.zip" -DestinationPath "test-data/MANIX"
   ```

2. **启动所有服务**
   ```powershell
   # 启动 MedSAM 后端
   cd MedSAM-main
   python medsam_service.py
   
   # 新终端：启动 OHIF 前端
   cd miscada-project-master
   yarn run dev
   ```

3. **上传数据到 OHIF**（拖放或通过 Orthanc）

4. **测试 3D 渲染**:
   - 选择 "Segmentation" 模式
   - 选择 "3D Only" 或 "3D Primary" 布局
   - 验证 3D 体积渲染是否正常显示

5. **测试 SAM 分割**:
   - 在 2D Axial 视图中选择感兴趣的切片
   - 点击工具栏 "SAM Apply" → "Store Origin Slice"
   - 使用 Rectangle 工具绘制目标区域边界框
   - 观察 MedSAM 自动生成的分割结果

6. **测试 LLM 诊断报告**（可选）:
   - 配置 `.env` 文件中的 API 密钥
   - 启动 `llm_diagnostic_service.py`
   - 点击 "Generate Report" 查看 AI 生成的诊断报告

---

### 高级测试（测试极限性能）

**目标**: 压力测试和性能评估

1. **下载大型数据集**:
   - TCIA LIDC-IDRI 单个病例（200MB）
   - 或 Medical Decathlon Liver CT（300MB）

2. **测试大数据量渲染**:
   - 加载 400+ 张切片的 CT 数据
   - 测试 3D 渲染流畅度
   - 验证内存占用（Chrome DevTools → Performance）

3. **批量分割测试**:
   - 在多个切片上执行 SAM 分割
   - 测试分割速度和准确性
   - 导出分割结果（DICOM SEG 格式）

---

## 📊 数据格式要求

### DICOM 文件要求
- **文件扩展名**: `.dcm` 或无扩展名
- **支持的模态**: CT, MRI, PET, X-Ray, Ultrasound
- **编码格式**: 支持所有标准 DICOM 传输语法

### 适合测试 SAM 分割的数据特征
- **模态**: CT 或 MRI（高对比度）
- **切片厚度**: < 5mm
- **分辨率**: 512x512 或更高
- **目标特征**: 器官、肿瘤、结节等明显边界的结构

### 适合测试 3D 渲染的数据特征
- **切片数量**: > 100 张（越多越好）
- **层间距**: < 3mm（越均匀越好）
- **模态**: CT（骨骼、血管）或 MRI（软组织）
- **视野**: 全身或大区域扫描

---

## 🚨 常见问题

### Q1: 上传 DICOM 文件后看不到数据？

**解决方案**:
1. 检查浏览器开发者工具（F12）→ Network，查看是否有上传错误
2. 确认文件是否为有效的 DICOM 格式（使用 DICOM Viewer 预先验证）
3. 刷新 Study List 页面（Ctrl+F5）
4. 检查 Orthanc 日志：`docker logs miscada-project-master_orthanc_1`

### Q2: 3D 渲染显示空白或卡顿？

**解决方案**:
1. 确保浏览器启用了硬件加速（Chrome Settings → System）
2. 清除浏览器缓存（Ctrl+Shift+Del）
3. 尝试使用更小的数据集（< 200 张切片）
4. 查看 [TROUBLESHOOTING_3D.md](TROUBLESHOOTING_3D.md)

### Q3: SAM 分割不准确？

**可能原因**:
1. 目标边界不清晰（低对比度）
2. 边界框绘制过大或过小
3. MedSAM 模型未正确加载（检查 `medsam_vit_b.pth` 文件）

**改进方法**:
- 调整窗宽窗位（Window/Level）提高对比度
- 精确绘制更贴合目标的边界框
- 使用高分辨率切片（512x512 或更高）

### Q4: 从 TCIA 下载的数据无法上传？

**解决方案**:
1. TCIA 数据通常已经是标准 DICOM 格式，直接拖放即可
2. 如果下载的是 `.tcia` 文件，需要使用 NBIA Data Retriever 解压
3. 确保解压后的文件夹包含 `.dcm` 文件

---

## 🎯 推荐首次测试流程

**最简单的 5 步测试**:

```powershell
# 1. 下载测试数据（OsiriX KNIX，20MB）
Invoke-WebRequest -Uri "https://www.osirix-viewer.com/datasets/DATA/KNIX.zip" -OutFile "KNIX.zip"
Expand-Archive -Path "KNIX.zip" -DestinationPath "test-data"

# 2. 启动 OHIF
cd miscada-project-master
yarn run dev

# 3. 浏览器打开 http://localhost:3000

# 4. 拖放 test-data/KNIX 文件夹中的所有 .dcm 文件到浏览器

# 5. 选择 "Segmentation" 模式，开始测试！
```

---

## 📚 额外资源

- **DICOM 标准文档**: https://www.dicomstandard.org/
- **Cornerstone3D 文档**: https://www.cornerstonejs.org/
- **OHIF 官方文档**: https://docs.ohif.org/
- **医学影像数据集汇总**: https://grand-challenge.org/challenges/

---

## 总结

| 数据来源 | 文件大小 | 下载难度 | 推荐用途 |
|---------|---------|---------|---------|
| **OsiriX KNIX** ⭐ | 20MB | 易 | 快速测试 |
| **OsiriX MANIX** ⭐⭐ | 100MB | 易 | 3D渲染测试 |
| **DICOM Library** ⭐ | 5-10MB | 易 | 基本功能验证 |
| **TCIA 数据集** ⭐⭐⭐ | 100MB-10GB | 中 | 完整功能测试 |
| **Medical Decathlon** ⭐⭐⭐ | 500MB-5GB | 中 | SAM分割验证 |
| **3D-IRCADb** ⭐⭐ | 200-300MB | 中 | 肝脏专项测试 |

**推荐首选**: OsiriX KNIX（最快）或 MANIX（完整测试）

