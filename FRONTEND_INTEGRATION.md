# 前端集成指南 - 将AI服务集成到OHIF

## 概述

本指南说明如何将MedSAM和LLM诊断服务集成到OHIF前端。

---

## 📍 关键代码位置

### 1. 命令模块 (Command Module)
**文件**: `extensions/cornerstone/src/commandsModule.ts`

这是实现所有按钮回调函数的地方。

### 2. 工具栏按钮 (Toolbar Buttons)
**文件**: `modes/sam/src/toolbarButtons.ts` 或 `modes/segmentation/src/toolbarButtons.ts`

定义右侧面板的按钮配置。

### 3. 模式配置 (Mode Configuration)
**文件**: `modes/sam/src/index.tsx`

注册按钮和配置布局。

---

## 🔧 集成步骤

### 步骤1: 在commandsModule.ts中添加LLM调用函数

在 `extensions/cornerstone/src/commandsModule.ts` 文件末尾添加:

```typescript
// 在文件顶部添加全局变量
let currentDiagnosticReport: string | null = null;

// 在commands对象中添加新命令
const commandsModule = ({ servicesManager, commandsManager }) => {
  // ... 现有代码 ...
  
  return {
    actions: {
      // ... 现有命令 ...
      
      // ===== 新增: LLM诊断报告生成 =====
      generateDiagnosticReport: async () => {
        const { uiNotificationService, measurementService, viewportGridService } = 
          servicesManager.services;
        
        try {
          uiNotificationService.show({
            title: 'Generating Report',
            message: 'AI is analyzing the imaging data...',
            type: 'info',
          });

          // 获取当前视图的测量数据
          const measurements = measurementService.getMeasurements();
          
          // 获取分割结果（如果有）
          const segmentationResults = {
            // TODO: 从segmentationService获取实际数据
            organs: ['lung_right', 'lung_left'],
            lesions: 0,
            volume: 0
          };

          // 构建请求数据
          const requestData = {
            patient_id: 'PATIENT_ID_HERE', // 从DICOM元数据获取
            modality: 'CT',
            body_region: 'Chest',
            clinical_history: 'Patient clinical history here',
            imaging_findings: 'Findings from radiologist review',
            segmentation_results: segmentationResults,
            measurements: measurements.map(m => ({
              type: m.label,
              length: m.length,
              area: m.area,
              volume: m.volume
            })),
            model: 'gpt-4'
          };

          // 调用LLM服务
          const response = await fetch('http://localhost:8001/generate_report', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestData),
          });

          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const result = await response.json();

          if (result.success) {
            currentDiagnosticReport = result.report;
            
            uiNotificationService.show({
              title: 'Report Generated',
              message: 'Diagnostic report has been created successfully.',
              type: 'success',
              duration: 3000,
            });

            // 显示报告 - 可以使用对话框或面板
            // TODO: 实现报告显示UI
            console.log('Diagnostic Report:', result.report);
            
          } else {
            throw new Error(result.error || 'Report generation failed');
          }

        } catch (error) {
          console.error('Error generating report:', error);
          uiNotificationService.show({
            title: 'Report Generation Failed',
            message: error.message || 'Failed to generate diagnostic report',
            type: 'error',
            duration: 5000,
          });
        }
      },

      // ===== 新增: MedSAM分割调用 =====
      performMedSAMSegmentation: async ({ bbox }) => {
        const { 
          uiNotificationService, 
          viewportGridService,
          segmentationService 
        } = servicesManager.services;
        
        try {
          // 获取当前viewport截图
          const { activeViewportId } = viewportGridService.getState();
          const viewport = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`);
          
          if (!viewport) {
            throw new Error('No active viewport found');
          }

          uiNotificationService.show({
            title: 'MedSAM Segmentation',
            message: 'Processing segmentation request...',
            type: 'info',
          });

          // 使用html2canvas截图
          const html2canvas = (await import('html2canvas')).default;
          const canvas = await html2canvas(viewport);
          
          // 转换为blob
          const blob = await new Promise(resolve => 
            canvas.toBlob(resolve, 'image/png', 1.0)
          );

          // 准备表单数据
          const formData = new FormData();
          formData.append('image', blob, 'slice.png');
          formData.append('bbox', `${bbox.x1},${bbox.y1},${bbox.x2},${bbox.y2}`);

          // 调用MedSAM服务
          const response = await fetch('http://localhost:8000/segment', {
            method: 'POST',
            body: formData,
          });

          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const result = await response.json();

          if (result.success) {
            // 将mask结果应用到segmentation
            const maskImage = new Image();
            maskImage.src = `data:image/png;base64,${result.mask}`;
            
            maskImage.onload = () => {
              // TODO: 将mask转换为cornerstone segmentation格式
              console.log('Segmentation mask loaded:', maskImage);
              
              uiNotificationService.show({
                title: 'Segmentation Complete',
                message: `Confidence: ${(result.confidence * 100).toFixed(1)}%`,
                type: 'success',
                duration: 3000,
              });
            };

          } else {
            throw new Error('Segmentation failed');
          }

        } catch (error) {
          console.error('Error performing segmentation:', error);
          uiNotificationService.show({
            title: 'Segmentation Failed',
            message: error.message || 'Failed to perform MedSAM segmentation',
            type: 'error',
            duration: 5000,
          });
        }
      },

      // ===== 新增: 显示诊断报告 =====
      showDiagnosticReport: () => {
        const { uiDialogService } = servicesManager.services;
        
        if (!currentDiagnosticReport) {
          uiNotificationService.show({
            title: 'No Report Available',
            message: 'Please generate a diagnostic report first.',
            type: 'warning',
          });
          return;
        }

        // 显示报告对话框
        uiDialogService.create({
          id: 'diagnostic-report-dialog',
          centralize: true,
          isDraggable: true,
          showOverlay: true,
          content: DiagnosticReportDialog,
          contentProps: {
            report: currentDiagnosticReport,
            onClose: () => uiDialogService.dismiss({ id: 'diagnostic-report-dialog' }),
          },
        });
      },
    },
    definitions: {
      // ... 现有定义 ...
      
      generateDiagnosticReport: {
        commandFn: actions.generateDiagnosticReport,
        storeContexts: [],
        options: {},
      },
      performMedSAMSegmentation: {
        commandFn: actions.performMedSAMSegmentation,
        storeContexts: [],
        options: {},
      },
      showDiagnosticReport: {
        commandFn: actions.showDiagnosticReport,
        storeContexts: [],
        options: {},
      },
    },
  };
};
```

---

### 步骤2: 添加工具栏按钮

在 `modes/sam/src/toolbarButtons.ts` 中添加:

```typescript
export const toolbarButtons = [
  // ... 现有按钮 ...
  
  // LLM诊断报告按钮
  {
    id: 'GenerateDiagnosticReport',
    uiType: 'ohif.toolBoxButton',
    props: {
      icon: 'icon-ai-report', // 需要添加图标
      label: 'Generate AI Report',
      tooltip: 'Generate diagnostic report using LLM',
      commands: 'generateDiagnosticReport',
      evaluate: [
        'evaluate.action',
        {
          name: 'evaluate.viewport.supported',
          unsupportedViewportTypes: ['video', 'wholeSlide'],
        },
      ],
    },
  },
  
  // 查看诊断报告按钮
  {
    id: 'ShowDiagnosticReport',
    uiType: 'ohif.toolBoxButton',
    props: {
      icon: 'icon-document',
      label: 'View Report',
      tooltip: 'View generated diagnostic report',
      commands: 'showDiagnosticReport',
    },
  },
  
  // MedSAM分割按钮
  {
    id: 'MedSAMSegmentation',
    uiType: 'ohif.toolBoxButton',
    props: {
      icon: 'icon-segment',
      label: 'MedSAM Segment',
      tooltip: 'Perform MedSAM segmentation with bounding box',
      commands: 'performMedSAMSegmentation',
      evaluate: [
        'evaluate.action',
        { name: 'evaluate.cornerstone.segmentation' },
      ],
    },
  },
];
```

---

### 步骤3: 在模式中注册按钮

在 `modes/sam/src/index.tsx` 中:

```typescript
// 在路由初始化中注册工具栏按钮
toolbarService.updateSection('SegmentationUtilities', [
  'StoreOriginSlice',
  'UploadToSAM',
  'GenerateDiagnosticReport',  // 新增
  'ShowDiagnosticReport',       // 新增
  'MedSAMSegmentation',         // 新增
]);
```

---

## 🎨 创建诊断报告显示组件

创建新文件: `extensions/cornerstone/src/components/DiagnosticReportDialog.tsx`

```typescript
import React from 'react';
import { Button } from '@ohif/ui';

interface DiagnosticReportDialogProps {
  report: string;
  onClose: () => void;
}

const DiagnosticReportDialog: React.FC<DiagnosticReportDialogProps> = ({
  report,
  onClose,
}) => {
  const handleCopy = () => {
    navigator.clipboard.writeText(report);
    // 显示复制成功提示
  };

  const handleDownload = () => {
    const blob = new Blob([report], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `diagnostic_report_${new Date().getTime()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="diagnostic-report-dialog">
      <div className="header">
        <h2>AI Diagnostic Report</h2>
        <button onClick={onClose}>×</button>
      </div>
      
      <div className="content">
        <pre style={{ whiteSpace: 'pre-wrap' }}>{report}</pre>
      </div>
      
      <div className="actions">
        <Button onClick={handleCopy}>Copy to Clipboard</Button>
        <Button onClick={handleDownload}>Download Report</Button>
        <Button onClick={onClose}>Close</Button>
      </div>
    </div>
  );
};

export default DiagnosticReportDialog;
```

---

## 📡 API调用示例

### 1. 生成诊断报告

```javascript
const response = await fetch('http://localhost:8001/generate_report', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    patient_id: 'PT001',
    modality: 'CT',
    body_region: 'Chest',
    clinical_history: 'Patient history...',
    imaging_findings: 'Findings description...',
    model: 'gpt-4'
  }),
});

const result = await response.json();
console.log(result.report);
```

### 2. MedSAM分割

```javascript
const formData = new FormData();
formData.append('image', imageBlob);
formData.append('bbox', '100,100,300,300');

const response = await fetch('http://localhost:8000/segment', {
  method: 'POST',
  body: formData,
});

const result = await response.json();
// result.mask 包含base64编码的分割掩码
```

---

## 🧪 测试集成

1. 启动所有服务 (Orthanc, MedSAM, LLM, OHIF)
2. 在OHIF中打开一个study
3. 点击 "Generate AI Report" 按钮
4. 检查浏览器控制台输出
5. 查看生成的报告

---

## 🔒 安全注意事项

1. **生产环境**: 使用HTTPS而不是HTTP
2. **API密钥**: 不要在前端代码中暴露API密钥
3. **CORS**: 正确配置CORS策略
4. **数据隐私**: 遵守HIPAA等医疗数据保护法规
5. **用户认证**: 添加用户身份验证

---

## 📚 相关文档

- [OHIF扩展开发](https://docs.ohif.org/development/extensions)
- [Cornerstone3D API](https://www.cornerstonejs.org/docs/api)
- [FastAPI文档](https://fastapi.tiangolo.com/)

---

**集成完成后，您就可以在OHIF界面中直接使用AI诊断功能了！** 🎉
