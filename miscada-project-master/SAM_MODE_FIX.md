# 快速解决MedSAM Viewer渲染错误

## 🔧 立即修复步骤

### 方案1: 清除缓存并重新构建 ⭐ 推荐

```powershell
# 停止开发服务器 (Ctrl+C)

# 清除所有缓存
cd c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master
yarn clean

# 删除node_modules/.cache (如果存在)
Remove-Item -Recurse -Force node_modules\.cache -ErrorAction SilentlyContinue

# 清除浏览器缓存
# Ctrl + Shift + Delete 或访问 chrome://settings/clearBrowserData
# 勾选"缓存的图像和文件"，点击"清除数据"

# 重新启动
yarn run dev:orthanc
```

---

### 方案2: 使用更简单的Segmentation模式 ⭐⭐ 最快

**直接使用Segmentation模式代替MedSAM Viewer**：

1. 选择病例后，选择 **"Segmentation"** 模式而不是"MedSAM Viewer"
2. Segmentation模式更稳定，也支持手动分割
3. 等MedSAM后端准备好后，仍然可以调用SAM API

---

### 方案3: 禁用3D渲染工具

修改MedSAM模式，移除导致问题的3D工具：

```powershell
# 编辑文件
notepad c:\Users\Dell\Desktop\miscada-project-master\miscada-project-master\modes\sam\src\index.tsx
```

找到这行：
```typescript
'TrackballRotate',
```

将其注释掉：
```typescript
// 'TrackballRotate',  // 禁用3D旋转工具
```

保存后重启服务。

---

### 方案4: 强制使用2D Stack视图

创建更安全的SAM模式配置：
