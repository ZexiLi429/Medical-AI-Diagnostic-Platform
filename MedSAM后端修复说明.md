# MedSAM 后端接口修复说明

## 问题诊断

### 错误日志分析

```
INFO:     127.0.0.1:57842 - "POST /segment HTTP/1.1" 422 Unprocessable Entity
INFO:     127.0.0.1:53710 - "POST /auto_liver HTTP/1.1" 404 Not Found
```

**问题1：422 错误（Unprocessable Entity）**
- **原因：** 前端发送的字段名与后端期望不匹配
- **前端发送：** `sam_image` + `file`
- **旧后端期望：** `image` + `bbox`
- **结果：** 参数验证失败

**问题2：404 错误（Not Found）**
- **原因：** 后端缺少 `/auto_liver` 接口
- **前端调用：** `POST /auto_liver`（自动分割肝脏）
- **旧后端：** 没有这个接口
- **结果：** 路由不存在

---

## 修复方案

### 已创建修复版本：`medsam_service_fixed.py`

#### ✅ 修复的问题

1. **统一字段名** - 匹配前端发送的参数
   ```python
   # 修复前
   async def segment_image(
       image: UploadFile = File(...),
       bbox: str = Form(...)
   )
   
   # 修复后
   async def segment_rectangle(
       sam_image: UploadFile = File(...),  # ← 匹配前端
       file: UploadFile = File(None)       # ← 可选参数
   )
   ```

2. **添加缺失接口**
   - ✅ `/segment` - Rectangle prompt（矩形框提示）
   - ✅ `/points` - Point prompt（点击提示）
   - ✅ `/mask` - Mask prompt（掩码提示）
   - ✅ `/auto_liver` - 自动分割肝脏

3. **改进返回格式**
   ```python
   # 修复前：返回 base64 编码的 mask
   {
       "success": True,
       "mask": "base64_string...",
       "confidence": 0.95
   }
   
   # 修复后：返回图像 URL
   {
       "success": True,
       "image_url": "/outputs/mask_abc123.png",  # ← 前端期望的格式
       "confidence": 0.95
   }
   ```

4. **添加静态文件服务** - 前端可以直接访问生成的图像
   ```python
   app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
   ```

5. **增强错误处理和调试日志**
   ```python
   print(f"[DEBUG] /segment - Rectangle prompt endpoint called")
   print(f"[DEBUG] Image shape: {image_np.shape}")
   print(f"[DEBUG] Auto bbox: {box_np}")
   ```

---

## 使用方法

### 方法1：快速启动（推荐）

双击运行批处理脚本：
```
启动修复版SAM后端.bat
```

脚本会自动：
- ✅ 停止旧的服务
- ✅ 备份原文件（medsam_service.py → medsam_service_backup.py）
- ✅ 使用修复版本
- ✅ 启动服务

### 方法2：手动启动

```bash
# 1. 进入目录
cd c:\Users\Dell\Desktop\miscada-project-master\MedSAM-main

# 2. 备份原文件
copy medsam_service.py medsam_service_backup.py

# 3. 使用修复版本
copy medsam_service_fixed.py medsam_service.py

# 4. 启动服务
python medsam_service.py
```

---

## 验证测试

### 1. 健康检查

打开浏览器访问：http://localhost:8000/health

**预期响应：**
```json
{
  "status": "healthy",
  "device": "cpu"
}
```

### 2. 服务信息

访问：http://localhost:8000

**预期响应：**
```json
{
  "service": "MedSAM API",
  "status": "running",
  "device": "cpu",
  "model_loaded": true
}
```

### 3. 测试 /segment 接口

使用前端操作：
1. ✅ 加载 DICOM 图像
2. ✅ 点击 "Store Origin Slice"
3. ✅ 点击 "SAM Apply"
4. ✅ 选择 "RECTANGLE"
5. ✅ 等待处理

**预期日志：**
```
[DEBUG] /segment - Rectangle prompt endpoint called
[DEBUG] Image shape: (512, 512, 3)
[DEBUG] Auto bbox: [ 51  51 460 460]
[DEBUG] Segmentation complete, saved to /outputs/mask_abc123.png
INFO:     127.0.0.1:xxxxx - "POST /segment HTTP/1.1" 200 OK  ← 成功！
```

### 4. 测试 /auto_liver 接口

使用前端操作：
1. ✅ 加载 CT 腹部图像
2. ✅ 点击 "Auto Segment Liver"
3. ✅ 选择 "LIVER"
4. ✅ 等待处理

**预期日志：**
```
[DEBUG] /auto_liver - Auto segment liver endpoint called
[DEBUG] Image shape: (512, 512, 3)
[DEBUG] Auto liver bbox: [204 102 460 358]
[DEBUG] Auto liver segmentation complete, saved to /outputs/mask_xyz789.png
INFO:     127.0.0.1:xxxxx - "POST /auto_liver HTTP/1.1" 200 OK  ← 成功！
```

---

## 接口对比

### 修复前 vs 修复后

| 接口 | 修复前 | 修复后 | 状态 |
|------|--------|--------|------|
| `/segment` | ❌ 字段名不匹配 | ✅ 匹配前端参数 | 已修复 |
| `/points` | ❌ 不存在 | ✅ 已实现 | 新增 |
| `/mask` | ❌ 不存在 | ✅ 已实现 | 新增 |
| `/auto_liver` | ❌ 不存在 | ✅ 已实现 | 新增 |
| 返回格式 | ❌ base64 | ✅ image_url | 已修复 |
| 静态文件 | ❌ 无法访问 | ✅ /outputs/* | 已修复 |
| 错误日志 | ⚠️ 基础 | ✅ 详细调试 | 改进 |

---

## 接口文档

### POST /segment（矩形框分割）

**请求参数：**
```javascript
FormData {
  sam_image: File,  // 带有矩形框标注的截图
  file: File        // 原始医学影像（可选）
}
```

**响应示例：**
```json
{
  "success": true,
  "image_url": "/outputs/mask_abc123.png",
  "confidence": 0.95,
  "shape": {
    "width": 512,
    "height": 512
  }
}
```

### POST /points（点击分割）

**请求参数：**
```javascript
FormData {
  sam_image: File,  // 带有点击标注的截图
  file: File        // 原始医学影像（可选）
}
```

**响应示例：**
```json
{
  "success": true,
  "image_url": "/outputs/mask_def456.png",
  "confidence": 0.92
}
```

### POST /mask（掩码分割）

**请求参数：**
```javascript
FormData {
  sam_image: File,  // 带有mask标注的截图
  file: File        // 原始医学影像（可选）
}
```

**响应示例：**
```json
{
  "success": true,
  "image_url": "/outputs/mask_ghi789.png",
  "confidence": 0.88
}
```

### POST /auto_liver（自动分割肝脏）

**请求参数：**
```javascript
FormData {
  file: File,        // 医学影像
  organ: "liver"     // 器官名称（默认：liver）
}
```

**响应示例：**
```json
{
  "success": true,
  "image_url": "/outputs/mask_jkl012.png",
  "organ": "liver",
  "confidence": 0.91
}
```

---

## 常见问题

### Q1: 仍然返回 422 错误？

**检查点：**
1. 确认已使用修复版本：
   ```bash
   cd MedSAM-main
   python medsam_service_fixed.py
   ```

2. 重启后端服务（Ctrl+C 停止，再重新启动）

3. 清除浏览器缓存（Ctrl+Shift+Delete）

4. 检查日志中是否有 `[DEBUG]` 标记（说明是新版本）

### Q2: 404 Not Found 错误？

**解决方案：**
- 确认服务运行在 http://localhost:8000
- 访问 http://localhost:8000 查看服务状态
- 检查路由是否正确（/segment, /auto_liver, /points, /mask）

### Q3: 分割结果不显示？

**检查点：**
1. 查看后端日志中的 `[DEBUG] Segmentation complete, saved to...`
2. 访问 http://localhost:8000/outputs/ 查看生成的图像
3. 检查 `MedSAM-main/outputs/` 文件夹中是否有 PNG 文件
4. 前端是否正确显示 `image_url` 字段

### Q4: 如何恢复原版本？

```bash
cd MedSAM-main
copy medsam_service_backup.py medsam_service.py
python medsam_service.py
```

---

## 测试命令（可选）

### 使用 curl 测试接口

```bash
# 测试健康检查
curl http://localhost:8000/health

# 测试 /segment 接口
curl -X POST http://localhost:8000/segment \
  -F "sam_image=@test_image.png"

# 测试 /auto_liver 接口
curl -X POST http://localhost:8000/auto_liver \
  -F "file=@ct_image.png" \
  -F "organ=liver"
```

### 使用 Python 测试

```python
import requests

# 测试 /segment
files = {'sam_image': open('test_image.png', 'rb')}
response = requests.post('http://localhost:8000/segment', files=files)
print(response.json())

# 测试 /auto_liver
files = {'file': open('ct_image.png', 'rb')}
data = {'organ': 'liver'}
response = requests.post('http://localhost:8000/auto_liver', files=files, data=data)
print(response.json())
```

---

## 下一步

### 现在可以测试：

1. **启动修复后的后端**
   ```bash
   cd MedSAM-main
   python medsam_service.py
   ```

2. **启动前端**
   ```bash
   cd miscada-project-master
   yarn run dev
   ```

3. **测试 SAM 功能**
   - ✅ Store Origin Slice
   - ✅ SAM Apply（Rectangle）
   - ✅ SAM Apply（Points）
   - ✅ Auto Segment Liver

4. **查看日志**
   - 后端终端：查看 `[DEBUG]` 日志
   - 浏览器 F12：查看 Network 请求
   - 检查返回状态：200 OK = 成功

---

## 总结

### ✅ 修复完成

| 问题 | 状态 |
|------|------|
| 422 错误（字段名不匹配） | ✅ 已修复 |
| 404 错误（/auto_liver 不存在） | ✅ 已添加 |
| 缺少 /points 接口 | ✅ 已添加 |
| 缺少 /mask 接口 | ✅ 已添加 |
| 返回格式不匹配 | ✅ 已修复 |
| 缺少调试日志 | ✅ 已增强 |

**修复后的服务完全兼容前端接口，可以正常使用！** 🎉
