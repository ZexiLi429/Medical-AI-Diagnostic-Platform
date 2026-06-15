# SAM 功能使用指南（恢复版）

## 已恢复的更改

### ✅ 恢复内容

**1. 按钮前置检查（已恢复）**
- ✅ StoreOriginSlice - 需要先创建分割对象
- ✅ SAMApply - 需要先创建分割对象
- ✅ AutoSegmentLiver - 需要先创建分割对象

**2. 命令逻辑（已恢复）**
- ✅ `runSegmentBidirectional` - 使用 `_getActiveSegmentationInfo()`
- ✅ `interpolateLabelmap` - 使用 `_getActiveSegmentationInfo()`
- ✅ `addNewSegment` - 使用 `getActiveSegmentation()`

**3. 自动创建功能（已移除）**
- ❌ 不再自动创建分割对象
- ❌ `_ensureActiveSegmentation()` 函数保留但不使用

---

## 正确使用流程

### 步骤 1：加载 DICOM 图像
1. 打开 OHIF Viewer (http://localhost:3000)
2. 加载 DICOM 数据

### 步骤 2：创建分割对象（必须！）
**这是关键步骤，必须先执行：**

#### 方法 A：使用侧边栏（推荐）
1. 点击右侧面板的 **"Segmentation"** 标签
2. 点击 **"Add Segmentation"** 按钮（蓝色加号）
3. 系统创建 "Segmentation 1"
4. 自动添加 "Segment 1"

#### 方法 B：使用工具栏
1. 找到工具栏的 **"Create Segmentation"** 按钮
2. 点击创建

**创建后，左侧面板应该显示：**
```
📁 Segmentation 1
   └─ 🔵 Segment 1 (active)
```

### 步骤 3：使用 SAM 功能

现在 SAM 按钮应该从**灰色**变为**蓝色**（可用状态）。

#### 3A. Rectangle Prompt（矩形框分割）
1. ✅ 点击 **"Store Origin Slice"** 
   - 提示："The screenshot was successful"
   
2. ✅ 点击 **"SAM Apply"**
   - 选择 **"RECTANGLE"**
   
3. ✅ 在图像上绘制矩形框（框选目标区域）

4. ✅ 等待后端处理（显示 "Processing image, please wait..."）

5. ✅ 查看分割结果

#### 3B. Auto Segment Liver（自动分割）
1. ✅ 确保已创建分割对象
2. ✅ 点击 **"Auto Segment Liver"**
3. ✅ 选择 **"LIVER"**
4. ✅ 等待处理
5. ✅ 查看结果

---

## 常见问题

### Q1: SAM 按钮显示灰色，不能点击？

**原因：** 没有创建分割对象

**解决：**
1. 打开右侧 "Segmentation" 面板
2. 点击 "Add Segmentation"
3. 确认出现 "Segmentation 1"
4. SAM 按钮变蓝色

### Q2: 点击 SAM 按钮后报错 "Cannot read properties of undefined"？

**原因：** 分割对象被意外删除或未正确创建

**解决：**
1. 刷新页面（F5）
2. 重新加载 DICOM 图像
3. **重新创建分割对象**
4. 再使用 SAM 功能

### Q3: 如何创建多个分割对象？

**步骤：**
1. 创建第一个分割对象 "Segmentation 1"
2. 使用 SAM 分割器官A
3. 点击 "Add Segmentation" 创建 "Segmentation 2"
4. 使用 SAM 分割器官B
5. 可以在面板中切换活动分割对象

### Q4: 如何在同一个分割对象中添加多个分段？

**步骤：**
1. 创建 "Segmentation 1"
2. 使用 SAM 分割区域1 → 保存在 Segment 1
3. 点击 "Add Segment" → 创建 Segment 2
4. 使用 SAM 分割区域2 → 保存在 Segment 2

---

## 为什么恢复原设计？

### 技术原因

**自动创建分割对象的问题：**
```javascript
// 错误场景：
1. 用户加载图像
2. 点击 SAM 按钮
3. 系统自动创建分割对象
4. 同时触发 setActiveSegment()
5. 但分割对象尚未完全初始化
6. 导致 TypeError: Cannot read properties of undefined (reading 'id')
```

**原设计的优点：**
- ✅ 用户明确知道何时创建了分割对象
- ✅ 分割对象完全初始化后才开始使用
- ✅ 避免竞态条件（race condition）
- ✅ 错误更少，更稳定

### 用户体验

**原设计流程：**
```
1. 加载图像
2. 手动创建分割对象（明确的操作）
3. 使用 SAM（按钮可用）
4. 查看结果
```

**自动创建流程（已废弃）：**
```
1. 加载图像
2. 直接使用 SAM（看似方便）
3. ❌ 系统后台自动创建（用户不知情）
4. ⚠️ 可能出现竞态条件错误
```

---

## 测试验证清单

### ✅ 基础测试
- [ ] 加载 DICOM 图像
- [ ] SAM 按钮显示灰色（禁用）
- [ ] 创建分割对象
- [ ] SAM 按钮变蓝色（可用）
- [ ] Store Origin Slice 成功
- [ ] SAM Apply 成功
- [ ] 分割结果显示在图像上

### ✅ 错误处理
- [ ] 未创建分割对象时，SAM 按钮不可点击
- [ ] 不再出现 "Cannot read properties of undefined" 错误
- [ ] 删除分割对象后，SAM 按钮变灰

### ✅ 多对象测试
- [ ] 创建多个分割对象
- [ ] 在不同对象间切换
- [ ] SAM 结果保存到正确的对象

---

## 快速参考

### 正确顺序（重要！）
```
1️⃣ 加载图像
2️⃣ 创建分割对象（右侧面板 → Add Segmentation）
3️⃣ Store Origin Slice
4️⃣ SAM Apply（或 Auto Segment Liver）
5️⃣ 查看结果
```

### 错误顺序（会失败）
```
1️⃣ 加载图像
2️⃣ ❌ 直接点击 SAM 按钮 → 灰色，无法点击
```

---

## 现在可以测试

### 1. 重启前端
```bash
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master
yarn run dev
```

### 2. 确认后端运行
```bash
cd c:\Users\Dell\Desktop\miscada-project-master\MedSAM-main
python medsam_service.py
```

### 3. 测试流程
1. http://localhost:3000
2. 加载 DICOM
3. **Add Segmentation** ← 关键步骤！
4. Store Origin Slice
5. SAM Apply
6. ✅ 成功，无错误

---

## 总结

| 更改 | 状态 | 说明 |
|------|------|------|
| 按钮前置检查 | ✅ 已恢复 | 需要先创建分割对象 |
| 自动创建逻辑 | ❌ 已移除 | 避免竞态条件错误 |
| 命令函数 | ✅ 已恢复 | 使用原始逻辑 |
| 错误修复 | ✅ 已修复 | 不再出现 undefined 错误 |
| 用户体验 | ⚠️ 需额外步骤 | 但更稳定可靠 |

**核心要点：使用 SAM 前，必须先手动创建分割对象！** 🎯
