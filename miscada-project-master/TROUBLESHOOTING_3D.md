# 3D渲染问题排查指南

## 问题：3D Primary黑屏 + WebGL错误

### 错误信息
```
TypeError: Cannot read properties of null (reading 'isAttributeUsed')
at publicAPI.setMapperShaderParameters
```

---

## 🔍 问题原因

这个错误通常由以下原因引起：

1. **WebGL上下文丢失**
2. **GPU硬件加速未启用**
3. **显卡驱动过旧**
4. **数据加载不完整**
5. **浏览器WebGL支持问题**

---

## ✅ 解决方案（按优先级）

### 方案1: 检查并启用硬件加速 ⭐ 推荐

#### Chrome/Edge:
```
1. 访问: chrome://settings/system
2. 确保 "使用硬件加速" 已启用
3. 重启浏览器
```

或直接在地址栏输入：
```
chrome://settings/system
edge://settings/system
```

#### Firefox:
```
1. 访问: about:preferences
2. 性能 -> 取消勾选 "使用推荐的性能设置"
3. 勾选 "使用硬件加速"
4. 重启浏览器
```

---

### 方案2: 检查WebGL支持

访问测试网站：
```
https://get.webgl.org/
```

如果看到旋转的立方体 = WebGL正常
如果显示错误消息 = WebGL未启用

#### 手动启用WebGL (Chrome/Edge):

1. 访问：`chrome://flags`
2. 搜索并启用以下选项：
   - `#ignore-gpu-blocklist` → **Enabled**
   - `#enable-webgl2-compute-context` → **Enabled**
3. 重启浏览器

---

### 方案3: 清除浏览器缓存

```powershell
# Chrome/Edge 快捷键
Ctrl + Shift + Delete

# 或访问
chrome://settings/clearBrowserData
```

选择：
- ✅ 缓存的图像和文件
- ✅ Cookie和其他网站数据
- 时间范围：全部

清除后重新加载OHIF

---

### 方案4: 使用不同的3D布局

某些3D布局可能更稳定：

1. **尝试其他3D布局**：
   - `3D Only` (纯3D，资源占用小)
   - `MPR` (多平面重建，更稳定)
   - `Axial Primary` (2D为主)

2. **避免复杂布局**：
   - 初次加载避免使用 `Four Up` (四视图)
   - 等数据完全加载后再切换

---

### 方案5: 降低数据质量（临时方案）

如果数据集太大导致内存不足：

**修改配置文件**：
```javascript
// platform/app/public/config/docker-nginx-orthanc.js
window.config = {
  // ... 现有配置
  
  // 添加以下配置
  maxNumberOfWebWorkers: 2, // 降低worker数量
  
  // 降低预加载
  maxNumRequests: {
    interaction: 50,
    thumbnail: 30,
    prefetch: 10,
  },
};
```

---

### 方案6: 更新显卡驱动

#### NVIDIA:
```
访问: https://www.nvidia.com/Download/index.aspx
选择您的显卡型号下载最新驱动
```

#### AMD:
```
访问: https://www.amd.com/en/support
下载Auto-Detect工具或手动选择驱动
```

#### Intel:
```
访问: https://www.intel.com/content/www/us/en/support/products/80939/graphics.html
下载Driver & Support Assistant
```

---

### 方案7: 切换到CPU渲染（降级方案）

如果GPU有问题，可以强制使用CPU渲染：

**在浏览器控制台运行**：
```javascript
// 打开开发者工具 (F12)
// 在Console中输入：
localStorage.setItem('ohif-use-cpu-rendering', 'true');
location.reload();
```

恢复GPU渲染：
```javascript
localStorage.removeItem('ohif-use-cpu-rendering');
location.reload();
```

---

### 方案8: 检查系统资源

#### Windows任务管理器 (Ctrl + Shift + Esc):

检查以下资源使用率：
- **CPU**: < 80% 
- **内存**: < 90%
- **GPU**: 是否在使用

如果内存不足：
- 关闭其他浏览器标签
- 关闭不必要的应用程序
- 减少预加载切片数量

---

### 方案9: 使用不同浏览器测试

按推荐顺序尝试：

1. **Chrome** (最佳兼容性)
2. **Edge** (基于Chromium)
3. **Firefox** (备选)
4. ❌ 避免使用 Safari/IE

下载最新版Chrome：
```
https://www.google.com/chrome/
```

---

## 🧪 诊断步骤

### 步骤1: 浏览器控制台检查

按 `F12` 打开开发者工具，查看：

#### Console标签：
```javascript
// 检查WebGL状态
const gl = document.createElement('canvas').getContext('webgl2');
console.log('WebGL2支持:', gl !== null);

// 检查GPU信息
const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
console.log('GPU:', gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL));
```

#### Network标签：
- 检查是否有DICOM数据加载失败（红色）
- 确保所有资源都加载成功（绿色200）

---

### 步骤2: 测试简单数据

使用小数据集测试：
1. 上传单个CT序列（<50张切片）
2. 避免大型4D或动态数据
3. 确认2D视图正常工作

---

### 步骤3: 查看OHIF日志

在浏览器控制台查找：
```
- WebGL context lost
- Out of memory
- GPU process crashed
- Failed to compile shader
```

---

## 🔧 高级修复

### 修复1: 重置WebGL上下文

创建脚本清理WebGL状态：

```javascript
// 在浏览器控制台运行
function resetWebGL() {
  const canvases = document.getElementsByTagName('canvas');
  for (let canvas of canvases) {
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (gl) {
      const loseContext = gl.getExtension('WEBGL_lose_context');
      if (loseContext) {
        loseContext.loseContext();
        setTimeout(() => loseContext.restoreContext(), 100);
      }
    }
  }
  console.log('WebGL contexts reset');
}

resetWebGL();
```

---

### 修复2: 禁用特定WebGL扩展

如果某个WebGL扩展有问题：

```javascript
// 在加载页面前运行（浏览器控制台）
const originalGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, attributes) {
  if (type === 'webgl' || type === 'webgl2') {
    attributes = attributes || {};
    attributes.preserveDrawingBuffer = true;
    attributes.antialias = false; // 禁用抗锯齿
  }
  return originalGetContext.call(this, type, attributes);
};
```

---

### 修复3: 调整Cornerstone配置

修改 `platform/app/src/index.js`，添加错误处理：

```javascript
// 在文件顶部添加
window.addEventListener('webglcontextlost', (event) => {
  console.error('WebGL context lost', event);
  event.preventDefault();
  alert('3D渲染上下文丢失，请刷新页面');
}, false);

window.addEventListener('webglcontextrestored', (event) => {
  console.log('WebGL context restored', event);
  location.reload();
}, false);
```

---

## 📊 快速诊断清单

运行此清单快速诊断：

```javascript
// 复制到浏览器控制台运行
console.log('=== OHIF 3D渲染诊断 ===');

// 1. WebGL支持
const canvas = document.createElement('canvas');
const gl = canvas.getContext('webgl2');
console.log('✓ WebGL2支持:', gl !== null);

if (gl) {
  // 2. GPU信息
  const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
  if (debugInfo) {
    console.log('✓ GPU厂商:', gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL));
    console.log('✓ GPU型号:', gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL));
  }
  
  // 3. WebGL限制
  console.log('✓ 最大纹理大小:', gl.getParameter(gl.MAX_TEXTURE_SIZE));
  console.log('✓ 最大3D纹理大小:', gl.getParameter(gl.MAX_3D_TEXTURE_SIZE));
  console.log('✓ 最大颜色附件:', gl.getParameter(gl.MAX_COLOR_ATTACHMENTS));
}

// 4. 内存信息
if (performance.memory) {
  console.log('✓ 内存使用:', (performance.memory.usedJSHeapSize / 1048576).toFixed(2), 'MB');
  console.log('✓ 内存限制:', (performance.memory.jsHeapSizeLimit / 1048576).toFixed(2), 'MB');
}

// 5. 硬件加速
console.log('✓ 硬件并发数:', navigator.hardwareConcurrency);

console.log('=== 诊断完成 ===');
```

---

## ❓ 常见问题

### Q1: 错误信息显示"GPU进程崩溃"
**A**: 更新显卡驱动或降低渲染质量

### Q2: 只有黑屏，没有错误
**A**: 检查数据是否加载完成，等待30秒再尝试

### Q3: 2D正常但3D崩溃
**A**: GPU内存不足，尝试减少数据量或使用`3D Only`布局

### Q4: 每次刷新都崩溃
**A**: 清除浏览器缓存和localStorage

### Q5: 笔记本电脑性能差
**A**: 
- 使用独立显卡而非集成显卡
- 在NVIDIA控制面板设置浏览器使用高性能GPU
- 连接电源适配器（避免省电模式）

---

## 🎯 推荐配置

### 最佳浏览器设置:
- Chrome 120+ 或 Edge 120+
- 硬件加速：✅ 启用
- WebGL2：✅ 支持
- GPU：独立显卡（GTX 1050+或同级）
- 内存：8GB+

### 最佳系统配置:
- Windows 10/11 (64位)
- 16GB RAM
- NVIDIA/AMD独立显卡
- 最新驱动程序

---

## 📞 仍然无法解决？

1. **检查浏览器控制台完整错误**
2. **截图错误信息**
3. **运行诊断清单并记录结果**
4. **提供系统信息**：
   - 操作系统版本
   - 浏览器版本
   - 显卡型号
   - 内存大小

---

## 🔗 相关资源

- WebGL测试：https://get.webgl.org/
- Chrome GPU状态：chrome://gpu/
- Cornerstone文档：https://www.cornerstonejs.org/docs/faq
- VTK.js问题：https://github.com/Kitware/vtk-js/issues

---

**祝您成功解决3D渲染问题！** 🎉
