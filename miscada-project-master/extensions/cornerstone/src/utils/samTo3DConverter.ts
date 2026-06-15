/**
 * SAM分割结果3D可视化工具
 * 
 * 功能：将MedSAM返回的2D掩码转换为3D分割对象，并在3D视图中显示
 * 
 * 使用场景：
 * 1. 医生使用SAM分割肿瘤后，自动在3D视图中高亮显示
 * 2. 支持多层累积，生成完整的3D肿瘤模型
 * 3. 可导出为DICOM SEG格式
 */

import { cache, Enums as CoreEnums, Types as CoreTypes } from '@cornerstonejs/core';
import { segmentation, Enums as ToolEnums } from '@cornerstonejs/tools';
import type { Types as OhifTypes } from '@ohif/core';

interface SAMMaskData {
  mask_array: number[][];  // 2D二值数组 (0=背景, 1=目标)
  slice_index?: number;     // 切片索引
  confidence: number;       // 置信度
  area_mm2?: number;        // 面积(mm²)
  bbox_refined?: number[];  // 精确边界框 [x1, y1, x2, y2]
}

/**
 * 将SAM 2D掩码转换为3D分割并显示
 * 
 * @param maskData SAM返回的掩码数据
 * @param viewportId 当前视窗ID
 * @param servicesManager OHIF服务管理器
 * @param options 可选配置
 */
export async function convertSAMMaskTo3DSegmentation(
  maskData: SAMMaskData,
  viewportId: string,
  servicesManager: OhifTypes.ServicesManager,
  options: {
    segmentLabel?: string;
    segmentColor?: number[];  // RGB颜色 [R, G, B]
    autoRender?: boolean;
  } = {}
): Promise<string | null> {
  const {
    segmentationService,
    cornerstoneViewportService,
    viewportGridService,
    uiNotificationService,
  } = servicesManager.services as AppTypes.Services;

  const {
    segmentLabel = 'SAM Segmentation',
    segmentColor = [255, 0, 0],  // 默认红色
    autoRender = true,
  } = options;

  try {
    console.log('[SAM3D] 开始转换2D掩码到3D分割...');

    // 1. 获取当前viewport信息
    const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
    if (!viewport) {
      throw new Error('无法获取viewport');
    }

    // 2. 检查是否已存在分割对象，没有则创建
    let activeSegmentation = segmentationService.getActiveSegmentation(viewportId);
    let segmentationId: string;

    if (!activeSegmentation) {
      // 创建新的分割对象
      console.log('[SAM3D] 创建新的分割对象...');
      
      segmentationId = await segmentationService.createSegmentationForViewport(
        viewportId,
        {
          label: segmentLabel,
          type: ToolEnums.SegmentationRepresentations.Labelmap,
        }
      );

      activeSegmentation = segmentationService.getSegmentation(segmentationId);
    } else {
      segmentationId = activeSegmentation.segmentationId;
      console.log('[SAM3D] 使用现有分割对象:', segmentationId);
    }

    // 3. 获取分割volume数据
    const segmentationRepresentation = segmentation.state.getSegmentationRepresentations(
      viewportId
    )?.[0];

    if (!segmentationRepresentation) {
      throw new Error('无法获取分割表示');
    }

    const { volumeId } = segmentationRepresentation;
    const segmentationVolume = cache.getVolume(volumeId);
    
    if (!segmentationVolume) {
      throw new Error('无法获取分割volume');
    }

    const scalarData = segmentationVolume.getScalarData();
    const { dimensions, spacing, origin } = segmentationVolume;
    const [width, height, depth] = dimensions;

    console.log('[SAM3D] Volume信息:', { dimensions, spacing, origin });

    // 4. 确定当前切片索引
    let sliceIndex: number;
    if (maskData.slice_index !== undefined) {
      sliceIndex = maskData.slice_index;
    } else {
      // 根据viewport当前位置推断切片索引
      if (viewport.type === CoreEnums.ViewportType.STACK) {
        sliceIndex = (viewport as any).getCurrentImageIdIndex();
      } else if (viewport.type === CoreEnums.ViewportType.ORTHOGRAPHIC) {
        const { sliceIndex: idx } = (viewport as any).getCurrentImageIdIndex
          ? (viewport as any).getCurrentImageIdIndex()
          : { sliceIndex: Math.floor(depth / 2) };
        sliceIndex = idx;
      } else {
        sliceIndex = Math.floor(depth / 2);  // 默认中间层
      }
    }

    console.log('[SAM3D] 目标切片索引:', sliceIndex);

    // 5. 将2D掩码数据填充到3D volume
    const mask2D = maskData.mask_array;
    const maskHeight = mask2D.length;
    const maskWidth = mask2D[0]?.length || 0;

    if (maskHeight === 0 || maskWidth === 0) {
      throw new Error('掩码数据为空');
    }

    console.log('[SAM3D] 掩码尺寸:', { maskWidth, maskHeight });
    console.log('[SAM3D] Volume尺寸:', { width, height, depth });

    // 创建新的segment（如果需要）
    const activeSegmentIndex = segmentationService.getActiveSegment(viewportId).segmentIndex;
    let targetSegmentIndex = activeSegmentIndex;

    if (activeSegmentIndex === undefined || activeSegmentIndex === 0) {
      // 添加新segment
      targetSegmentIndex = await segmentationService.addSegment(
        segmentationId,
        {
          label: segmentLabel,
          color: segmentColor,
        }
      );
      console.log('[SAM3D] 创建新segment索引:', targetSegmentIndex);
    }

    // 6. 填充数据（考虑尺寸可能不匹配的情况）
    const frameSize = width * height;
    const sliceOffset = sliceIndex * frameSize;
    
    let filledPixels = 0;
    
    for (let y = 0; y < maskHeight && y < height; y++) {
      for (let x = 0; x < maskWidth && x < width; x++) {
        const maskValue = mask2D[y][x];
        
        if (maskValue > 0) {
          const volumeIndex = sliceOffset + y * width + x;
          scalarData[volumeIndex] = targetSegmentIndex;  // 设置为segment索引
          filledPixels++;
        }
      }
    }

    console.log(`[SAM3D] 填充像素数: ${filledPixels}`);

    // 7. 通知volume数据已更新
    segmentationVolume.modified();

    // 8. 刷新所有使用该分割的viewport
    const viewportIdsToRender = segmentation.state
      .getViewportIdsWithSegmentation(segmentationId)
      .filter(id => {
        const vp = cornerstoneViewportService.getCornerstoneViewport(id);
        return vp !== null;
      });

    console.log('[SAM3D] 刷新viewport:', viewportIdsToRender);

    // 9. 触发渲染
    if (autoRender) {
      viewportIdsToRender.forEach(vpId => {
        const vp = cornerstoneViewportService.getCornerstoneViewport(vpId);
        if (vp) {
          vp.render();
        }
      });
    }

    // 10. 显示成功通知
    if (uiNotificationService) {
      uiNotificationService.show({
        title: 'SAM 3D Segmentation',
        message: `已成功在切片 ${sliceIndex} 上创建3D分割，填充 ${filledPixels} 个像素`,
        type: 'success',
        duration: 3000,
      });
    }

    console.log('[SAM3D] 3D分割转换完成');
    return segmentationId;

  } catch (error) {
    console.error('[SAM3D] 转换失败:', error);
    
    if (uiNotificationService) {
      uiNotificationService.show({
        title: 'SAM 3D Error',
        message: `3D转换失败: ${error.message}`,
        type: 'error',
        duration: 5000,
      });
    }
    
    return null;
  }
}

/**
 * 批量添加多层SAM分割（用于累积多个切片生成完整3D模型）
 * 
 * @param maskDataList 多个切片的掩码数据数组
 * @param viewportId 当前视窗ID
 * @param servicesManager OHIF服务管理器
 */
export async function addMultiSliceSAMSegmentation(
  maskDataList: SAMMaskData[],
  viewportId: string,
  servicesManager: OhifTypes.ServicesManager
): Promise<string | null> {
  console.log(`[SAM3D] 批量添加 ${maskDataList.length} 层分割...`);

  const { segmentationService, uiNotificationService } = servicesManager.services as AppTypes.Services;

  try {
    // 第一层创建分割对象
    const firstMask = maskDataList[0];
    const segmentationId = await convertSAMMaskTo3DSegmentation(
      firstMask,
      viewportId,
      servicesManager,
      { autoRender: false }  // 批量处理时延迟渲染
    );

    if (!segmentationId) {
      throw new Error('首层分割创建失败');
    }

    // 后续层直接填充数据
    for (let i = 1; i < maskDataList.length; i++) {
      const maskData = maskDataList[i];
      
      // 使用相同的segmentationId填充
      await convertSAMMaskTo3DSegmentation(
        maskData,
        viewportId,
        servicesManager,
        { autoRender: false }
      );
    }

    // 所有层处理完后统一渲染
    const viewportIdsToRender = segmentation.state.getViewportIdsWithSegmentation(segmentationId);
    
    const { cornerstoneViewportService } = servicesManager.services as AppTypes.Services;
    viewportIdsToRender.forEach(vpId => {
      const vp = cornerstoneViewportService.getCornerstoneViewport(vpId);
      if (vp) {
        vp.render();
      }
    });

    if (uiNotificationService) {
      uiNotificationService.show({
        title: '批量SAM 3D分割完成',
        message: `已成功处理 ${maskDataList.length} 个切片`,
        type: 'success',
        duration: 3000,
      });
    }

    return segmentationId;

  } catch (error) {
    console.error('[SAM3D] 批量转换失败:', error);
    return null;
  }
}

/**
 * 从SAM分割中提取统计信息
 * 
 * @param segmentationId 分割对象ID
 * @param segmentIndex segment索引
 * @param servicesManager OHIF服务管理器
 * @returns 体积、表面积等统计信息
 */
export function calculateSAMSegmentationStats(
  segmentationId: string,
  segmentIndex: number,
  servicesManager: OhifTypes.ServicesManager
) {
  const { segmentationService } = servicesManager.services as AppTypes.Services;

  try {
    const segmentation = segmentationService.getSegmentation(segmentationId);
    if (!segmentation) {
      throw new Error('分割对象不存在');
    }

    const segmentationRepresentation = segmentation.representationData?.LABELMAP;
    if (!segmentationRepresentation) {
      throw new Error('无Labelmap表示');
    }

    const { volumeId } = segmentationRepresentation;
    const volume = cache.getVolume(volumeId);
    
    if (!volume) {
      throw new Error('无法获取volume');
    }

    const scalarData = volume.getScalarData();
    const { dimensions, spacing } = volume;
    const [sx, sy, sz] = spacing;  // 像素间距 (mm)

    // 统计像素数量
    let voxelCount = 0;
    for (let i = 0; i < scalarData.length; i++) {
      if (scalarData[i] === segmentIndex) {
        voxelCount++;
      }
    }

    // 计算体积
    const voxelVolume = sx * sy * sz;  // 单个体素体积 (mm³)
    const totalVolume = voxelCount * voxelVolume;  // 总体积 (mm³)
    const totalVolumeCm3 = totalVolume / 1000;  // 转换为 cm³

    console.log('[SAM3D Stats]', {
      voxelCount,
      voxelVolume,
      totalVolume: `${totalVolume.toFixed(2)} mm³`,
      totalVolumeCm3: `${totalVolumeCm3.toFixed(2)} cm³`,
    });

    return {
      voxelCount,
      voxelVolume,
      totalVolume,
      totalVolumeCm3,
      spacing,
      dimensions,
    };

  } catch (error) {
    console.error('[SAM3D Stats] 计算失败:', error);
    return null;
  }
}

/**
 * 导出SAM分割为DICOM SEG格式
 * 
 * @param segmentationId 分割对象ID
 * @param servicesManager OHIF服务管理器
 */
export async function exportSAMSegmentationToDICOMSEG(
  segmentationId: string,
  servicesManager: OhifTypes.ServicesManager
) {
  console.log('[SAM3D] 导出DICOM SEG...');

  const { segmentationService, commandsManager } = servicesManager.services as AppTypes.Services;

  try {
    // 使用OHIF内置的DICOM SEG导出命令
    await commandsManager.runCommand('exportSegmentation', {
      segmentationId,
      format: 'DICOM_SEG',
    });

    console.log('[SAM3D] DICOM SEG导出成功');

  } catch (error) {
    console.error('[SAM3D] DICOM SEG导出失败:', error);
    throw error;
  }
}
