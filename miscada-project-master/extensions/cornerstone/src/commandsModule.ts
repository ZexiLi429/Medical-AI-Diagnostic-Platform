import React from 'react';
import {
  getEnabledElement,
  StackViewport,
  VolumeViewport,
  utilities as csUtils,
  Enums as CoreEnums,
  Types as CoreTypes,
  BaseVolumeViewport,
} from '@cornerstonejs/core';
import {
  ToolGroupManager,
  Enums,
  utilities as cstUtils,
  annotation,
  Types as ToolTypes,
} from '@cornerstonejs/tools';
import * as cornerstoneTools from '@cornerstonejs/tools';
import * as labelmapInterpolation from '@cornerstonejs/labelmap-interpolation';
import { ONNXSegmentationController } from '@cornerstonejs/ai';

import { Types as OhifTypes, utils } from '@ohif/core';
import i18n from '@ohif/i18n';
import {
  callInputDialogAutoComplete,
  createReportAsync,
  colorPickerDialog,
  callInputDialog,
} from '@ohif/extension-default';
import { vec3, mat4 } from 'gl-matrix';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import toggleImageSliceSync from './utils/imageSliceSync/toggleImageSliceSync';
import { getFirstAnnotationSelected } from './utils/measurementServiceMappings/utils/selection';
import getActiveViewportEnabledElement from './utils/getActiveViewportEnabledElement';
import toggleVOISliceSync from './utils/toggleVOISliceSync';
import { usePositionPresentationStore, useSegmentationPresentationStore } from './stores';
import { toolNames } from './initCornerstoneTools';
import CornerstoneViewportDownloadForm from './utils/CornerstoneViewportDownloadForm';
import CornerstoneSamAndUnsamForm from './utils/CornerstoneSamAndUnsamForm';
import { updateSegmentBidirectionalStats } from './utils/updateSegmentationStats';
import { generateSegmentationCSVReport } from './utils/generateSegmentationCSVReport';
import { getUpdatedViewportsForSegmentation } from './utils/hydrationUtils';
import { SegmentationRepresentations } from '@cornerstonejs/tools/enums';
import html2canvas from 'html2canvas';

import Segmentation3DMeshModal, { type MeshData } from './components/Segmentation3DMeshModal';
import ReportModal from './components/ReportModal';

// ── VTK.js for 3D mesh overlay on volume viewport ──
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';

const { DefaultHistoryMemo } = csUtils.HistoryMemo;
const toggleSyncFunctions = {
  imageSlice: toggleImageSliceSync,
  voi: toggleVOISliceSync,
};

const { segmentation: segmentationUtils } = cstUtils;

// 在文件顶部添加全局变量
let originSliceBlob: Blob | null = null;

type LesionPromptFrame = {
  slice_idx: number;
  bbox?: [number, number, number, number];
  points?: number[][];
  labels?: number[];
  mask_rle?: { counts: number[]; starts_with: number; width: number; height: number };
};

type LesionWorkflowState = {
  organHint?: string | null;
  promptFrames: LesionPromptFrame[];
  previewAccepted: boolean;
  last3DVolumeMm3?: number | null;
  lastTrackedSlices?: number | null;
  last3DMesh?: MeshData | null;
  last2DScreenshot?: string | null;
  last3DScreenshot?: string | null;
};

const lesionWorkflowStateByViewport = new Map<string, LesionWorkflowState>();
const organHintByViewport = new Map<string, string>();
const lesion3DStatusBarByViewport = new Map<string, HTMLDivElement>();

function upsertLesion3DStatusBar({
  viewportId,
  returnedSlices,
  writtenSlices,
  representationType,
  volumeMm3,
  status,
}: {
  viewportId: string;
  returnedSlices: number;
  writtenSlices: number;
  representationType: string;
  volumeMm3?: number | null;
  status: 'success' | 'warning' | 'error';
}) {
  if (typeof document === 'undefined') {
    return;
  }

  const viewportContainer = document.querySelector(
    `div[data-viewport-uid="${viewportId}"]`
  ) as HTMLElement | null;

  if (!viewportContainer) {
    return;
  }

  const containerStyle = window.getComputedStyle(viewportContainer);
  if (containerStyle.position === 'static') {
    viewportContainer.style.position = 'relative';
  }

  let statusBar = lesion3DStatusBarByViewport.get(viewportId);
  if (!statusBar || !viewportContainer.contains(statusBar)) {
    statusBar = document.createElement('div');
    statusBar.setAttribute('data-ai-3d-status', 'true');
    statusBar.style.position = 'absolute';
    statusBar.style.left = '10px';
    statusBar.style.right = '10px';
    statusBar.style.bottom = '10px';
    statusBar.style.zIndex = '30';
    statusBar.style.padding = '8px 12px';
    statusBar.style.borderRadius = '8px';
    statusBar.style.backdropFilter = 'blur(2px)';
    statusBar.style.fontSize = '12px';
    statusBar.style.lineHeight = '1.4';
    statusBar.style.pointerEvents = 'none';
    viewportContainer.appendChild(statusBar);
    lesion3DStatusBarByViewport.set(viewportId, statusBar);
  }

  if (status === 'success') {
    statusBar.style.background = 'rgba(21, 128, 61, 0.86)';
    statusBar.style.border = '1px solid rgba(134, 239, 172, 0.55)';
    statusBar.style.color = '#ecfdf5';
  } else if (status === 'warning') {
    statusBar.style.background = 'rgba(146, 64, 14, 0.86)';
    statusBar.style.border = '1px solid rgba(252, 211, 77, 0.55)';
    statusBar.style.color = '#fffbeb';
  } else {
    statusBar.style.background = 'rgba(127, 29, 29, 0.88)';
    statusBar.style.border = '1px solid rgba(252, 165, 165, 0.55)';
    statusBar.style.color = '#fef2f2';
  }

  const volumeText =
    typeof volumeMm3 === 'number' && Number.isFinite(volumeMm3)
      ? `${volumeMm3.toFixed(1)} mm3`
      : 'N/A';
  const statusText = status === 'success' ? '3D Complete' : status === 'warning' ? '3D Partial' : '3D Failed';

  statusBar.textContent =
    `${statusText} | Slices returned: ${returnedSlices} | Written: ${writtenSlices} | Display: ${representationType} | Volume: ${volumeText}`;
}

function getLesionWorkflow(viewportId: string): LesionWorkflowState {
  const existing = lesionWorkflowStateByViewport.get(viewportId);
  if (existing) {
    return existing;
  }

  const created: LesionWorkflowState = {
    organHint: null,
    promptFrames: [],
    previewAccepted: false,
    last3DVolumeMm3: null,
    lastTrackedSlices: null,
    last3DMesh: null,
    last2DScreenshot: null,
    last3DScreenshot: null,
  };
  lesionWorkflowStateByViewport.set(viewportId, created);
  return created;
}

function upsertPromptFrame(viewportId: string, promptFrame: LesionPromptFrame, maxFrames = 3) {
  const state = getLesionWorkflow(viewportId);
  const next = state.promptFrames.filter(item => item.slice_idx !== promptFrame.slice_idx);
  next.push(promptFrame);
  next.sort((a, b) => a.slice_idx - b.slice_idx);
  state.promptFrames = next.slice(-maxFrames);
}

function buildReportFallbackText({
  organHint,
  volumeMm3,
  trackedSlices,
}: {
  organHint?: string | null;
  volumeMm3?: number | null;
  trackedSlices?: number | null;
}) {
  const organ = (organHint || 'target region').replace('_', ' ');
  const volumeText =
    typeof volumeMm3 === 'number' && Number.isFinite(volumeMm3)
      ? `${(volumeMm3 / 1000).toFixed(2)} cm3`
      : 'not available';

  return [
    'Findings:',
    `Segmentation was generated for the ${organ}.`,
    `Estimated lesion volume: ${volumeText}.`,
    trackedSlices ? `Tracked slices: ${trackedSlices}.` : null,
    '',
    'Impression:',
    `Segmented lesion in the ${organ}; correlate with source images and clinical context.`,
  ]
    .filter(Boolean)
    .join('\n');
}

function verifyOrFallbackReport(
  reportText: string | undefined,
  {
    organHint,
    volumeMm3,
    trackedSlices,
  }: {
    organHint?: string | null;
    volumeMm3?: number | null;
    trackedSlices?: number | null;
  }
) {
  if (!reportText || !reportText.trim()) {
    return {
      ok: false,
      reason: 'empty',
      text: buildReportFallbackText({ organHint, volumeMm3, trackedSlices }),
    };
  }

  const lower = reportText.toLowerCase();
  const expectedOrgan = organHint?.replace('_', ' ').toLowerCase();

  if (expectedOrgan && !lower.includes(expectedOrgan)) {
    return {
      ok: false,
      reason: 'organ_mismatch',
      text: buildReportFallbackText({ organHint, volumeMm3, trackedSlices }),
    };
  }

  if (typeof volumeMm3 === 'number' && Number.isFinite(volumeMm3) && volumeMm3 > 0) {
    const vMm3 = volumeMm3.toFixed(2).toLowerCase();
    const vCm3 = (volumeMm3 / 1000).toFixed(2).toLowerCase();
    if (!lower.includes(vMm3) && !lower.includes(vCm3)) {
      return {
        ok: false,
        reason: 'volume_mismatch',
        text: buildReportFallbackText({ organHint, volumeMm3, trackedSlices }),
      };
    }
  }

  return {
    ok: true,
    reason: 'verified',
    text: reportText,
  };
}

// MedSAM2 (port 8003) 可用性缓存 —— 优先用于 2D 预览分割
let _medsam2Available: boolean | null = null;
async function isMedSAM2Available(): Promise<boolean> {
  if (_medsam2Available !== null) return _medsam2Available;
  try {
    const resp = await fetch('http://localhost:8003/health', { signal: AbortSignal.timeout(1500) });
    _medsam2Available = resp.ok;
  } catch {
    _medsam2Available = false;
  }
  console.log(`[SAM] MedSAM2 (port 8003) available: ${_medsam2Available}`);
  return _medsam2Available;
}

// LiteMedSAM (port 8002) 可用性缓存 —— 每次刷新页面检测一次
let _liteMedSAMAvailable: boolean | null = null;
async function isLiteMedSAMAvailable(): Promise<boolean> {
  if (_liteMedSAMAvailable !== null) return _liteMedSAMAvailable;
  try {
    const resp = await fetch('http://localhost:8002/health', { signal: AbortSignal.timeout(1500) });
    _liteMedSAMAvailable = resp.ok;
  } catch {
    _liteMedSAMAvailable = false;
  }
  console.log(`[SAM] LiteMedSAM (port 8002) available: ${_liteMedSAMAvailable}`);
  return _liteMedSAMAvailable;
}

const getLabelmapTools = ({ toolGroupService }) => {
  const labelmapTools = [];
  const toolGroupIds = toolGroupService.getToolGroupIds();
  toolGroupIds.forEach(toolGroupId => {
    const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroup(toolGroupId);
    const tools = toolGroup.getToolInstances();
    // tools is an object with toolName as the key and tool as the value
    Object.keys(tools).forEach(toolName => {
      const tool = tools[toolName];
      if (tool instanceof cornerstoneTools.LabelmapBaseTool) {
        labelmapTools.push(tool);
      }
    });
  });
  return labelmapTools;
};

const segmentAI = new ONNXSegmentationController({
  autoSegmentMode: true,
  models: {
    sam_b: [
      {
        name: 'sam-b-encoder',
        url: 'https://huggingface.co/schmuell/sam-b-fp16/resolve/main/sam_vit_b_01ec64.encoder-fp16.onnx',
        size: 180,
        key: 'encoder',
      },
      {
        name: 'sam-b-decoder',
        url: 'https://huggingface.co/schmuell/sam-b-fp16/resolve/main/sam_vit_b_01ec64.decoder.onnx',
        size: 17,
        key: 'decoder',
      },
    ],
  },
  modelName: 'sam_b',
});
let segmentAIEnabled = false;

function commandsModule({
  servicesManager,
  commandsManager,
}: OhifTypes.Extensions.ExtensionParams): OhifTypes.Extensions.CommandsModule {
  const {
    viewportGridService,
    toolGroupService,
    cineService,
    uiDialogService,
    cornerstoneViewportService,
    uiNotificationService,
    measurementService,
    customizationService,
    colorbarService,
    hangingProtocolService,
    syncGroupService,
    segmentationService,
    displaySetService,
  } = servicesManager.services as AppTypes.Services;

  function _getActiveViewportEnabledElement() {
    return getActiveViewportEnabledElement(viewportGridService);
  }

  function _getActiveViewportToolGroupId() {
    const viewport = _getActiveViewportEnabledElement();
    return toolGroupService.getToolGroupForViewport(viewport.id);
  }

  function _isSegmentationEditingTool(toolName?: string) {
    const n = String(toolName ?? '').toLowerCase();
    return n.includes('brush') || n.includes('scissor') || n.includes('eraser') || n.includes('paint');
  }

  function _getActiveSegmentationInfo() {
    const viewportId = viewportGridService.getActiveViewportId();
    const activeSegmentation = segmentationService.getActiveSegmentation(viewportId);
    const segmentationId = activeSegmentation?.segmentationId;
    const activeSegmentIndex = segmentationService.getActiveSegment(viewportId).segmentIndex;

    return {
      segmentationId,
      segmentIndex: activeSegmentIndex,
    };
  }

  /**
   * 确保存在活动的分割对象，如果不存在则自动创建
   * 用于SAM等需要保存分割结果的功能
   */
  async function _ensureActiveSegmentation() {
    const viewportId = viewportGridService.getActiveViewportId();
    
    // 检查是否已有活动分割对象
    let activeSegmentation = segmentationService.getActiveSegmentation(viewportId);
    
    if (!activeSegmentation) {
      // 没有分割对象，自动创建一个
      console.log('[SAM] No active segmentation found, creating one automatically...');
      
      const { viewports } = viewportGridService.getState();
      const viewportEntry = viewports.get(viewportId);
      const displaySetInstanceUID = viewportEntry?.displaySetInstanceUIDs?.[0];
      
      if (!displaySetInstanceUID) {
        throw new Error('No display set found to create segmentation');
      }
      
      const displaySet = displaySetService.getDisplaySetByUID(displaySetInstanceUID);
      const segmentationId = `sam-auto-${csUtils.uuidv4()}`;
      
      // 创建 labelmap 分割对象
      const generatedSegmentationId = await segmentationService.createLabelmapForDisplaySet(
        displaySet,
        {
          label: 'SAM Segmentation',
          segmentationId,
          segments: {
            1: {
              label: 'SAM Result',
              active: true,
            },
          },
        }
      );
      
      // 添加到视口
      await segmentationService.addSegmentationRepresentation(viewportId, {
        segmentationId: generatedSegmentationId,
        type: Enums.SegmentationRepresentations.Labelmap,
      });
      
      // 显示通知
      uiNotificationService.show({
        title: 'Segmentation Created',
        message: 'Auto-created "SAM Segmentation" for storing AI results',
        type: 'info',
        duration: 3000,
      });
      
      // 重新获取
      activeSegmentation = segmentationService.getActiveSegmentation(viewportId);
      console.log('[SAM] Auto-created segmentation:', generatedSegmentationId);
    }
    
    const activeSegment = segmentationService.getActiveSegment(viewportId);
    const activeSegmentIndex = typeof activeSegment?.segmentIndex === 'number'
      ? activeSegment.segmentIndex
      : 1;

    const labelmapRepresentations = segmentationService.getSegmentationRepresentations(viewportId, {
      segmentationId: activeSegmentation.segmentationId,
      type: Enums.SegmentationRepresentations.Labelmap,
    });

    if (!labelmapRepresentations.length) {
      await segmentationService.addSegmentationRepresentation(viewportId, {
        segmentationId: activeSegmentation.segmentationId,
        type: Enums.SegmentationRepresentations.Labelmap,
      });
    }

    segmentationService.setActiveSegment(activeSegmentation.segmentationId, activeSegmentIndex);
    
    return {
      segmentationId: activeSegmentation.segmentationId,
      segmentIndex: activeSegmentIndex,
    };
  }

  async function _getActiveSegmentationSliceBBox(viewportId: string, sliceIdx: number) {
    const activeSegmentation = segmentationService.getActiveSegmentation(viewportId);
    if (!activeSegmentation?.segmentationId) {
      return null;
    }

    const { cache: csCache } = await import('@cornerstonejs/core');
    const { segmentation: csSeg } = await import('@cornerstonejs/tools');
    const segObj = csSeg.state.getSegmentation(activeSegmentation.segmentationId);
    const labelmapData = segObj?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
    const labelmapVolume = labelmapData?.volumeId ? csCache.getVolume(labelmapData.volumeId) : null;
    const stackImageIds = (labelmapData as any)?.imageIds as string[] | undefined;

    let minCol = Number.POSITIVE_INFINITY;
    let minRow = Number.POSITIVE_INFINITY;
    let maxCol = -1;
    let maxRow = -1;

    if (labelmapVolume) {
      const { dimensions } = labelmapVolume;
      const [cols, rows] = dimensions;
      const scalarData = labelmapVolume.getScalarData() as Uint8Array;
      const sliceOffset = sliceIdx * cols * rows;
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          if (scalarData[sliceOffset + row * cols + col] > 0) {
            if (col < minCol) minCol = col;
            if (row < minRow) minRow = row;
            if (col > maxCol) maxCol = col;
            if (row > maxRow) maxRow = row;
          }
        }
      }
    } else if (stackImageIds?.length && stackImageIds[sliceIdx]) {
      const imageId = stackImageIds[sliceIdx];
      const sliceImage = (csCache as any).getImage(imageId);
      const pixels = sliceImage?.getPixelData?.();
      const width = sliceImage?.width ?? 0;
      const height = sliceImage?.height ?? 0;
      if (pixels && width > 0 && height > 0) {
        for (let row = 0; row < height; row++) {
          for (let col = 0; col < width; col++) {
            if (pixels[row * width + col] > 0) {
              if (col < minCol) minCol = col;
              if (row < minRow) minRow = row;
              if (col > maxCol) maxCol = col;
              if (row > maxRow) maxRow = row;
            }
          }
        }
      }
    }

    if (maxCol < 0 || maxRow < 0) {
      return null;
    }

    return [minCol, minRow, maxCol + 1, maxRow + 1] as [number, number, number, number];
  }

  async function _getActiveSegmentationSlicePromptData(viewportId: string, sliceIdx: number, maxPoints = 8) {
    const activeSegmentation = segmentationService.getActiveSegmentation(viewportId);
    if (!activeSegmentation?.segmentationId) {
      return null;
    }

    const { cache: csCache } = await import('@cornerstonejs/core');
    const { segmentation: csSeg } = await import('@cornerstonejs/tools');
    const segObj = csSeg.state.getSegmentation(activeSegmentation.segmentationId);
    const labelmapData = segObj?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
    const labelmapVolume = (labelmapData as any)?.volumeId ? csCache.getVolume((labelmapData as any).volumeId) : null;
    const stackImageIds = (labelmapData as any)?.imageIds as string[] | undefined;

    const foregroundPoints: number[][] = [];
    let minCol = Number.POSITIVE_INFINITY;
    let minRow = Number.POSITIVE_INFINITY;
    let maxCol = -1;
    let maxRow = -1;

    const visitForeground = (col: number, row: number) => {
      foregroundPoints.push([col, row]);
      if (col < minCol) minCol = col;
      if (row < minRow) minRow = row;
      if (col > maxCol) maxCol = col;
      if (row > maxRow) maxRow = row;
    };

    if (labelmapVolume) {
      const { dimensions } = labelmapVolume;
      const [cols, rows] = dimensions;
      const scalarData = labelmapVolume.getScalarData() as Uint8Array;
      const sliceOffset = sliceIdx * cols * rows;
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          if (scalarData[sliceOffset + row * cols + col] > 0) {
            visitForeground(col, row);
          }
        }
      }
    } else if (stackImageIds?.length && stackImageIds[sliceIdx]) {
      const imageId = stackImageIds[sliceIdx];
      const sliceImage = (csCache as any).getImage(imageId);
      const pixels = sliceImage?.getPixelData?.();
      const width = sliceImage?.width ?? 0;
      const height = sliceImage?.height ?? 0;
      if (pixels && width > 0 && height > 0) {
        for (let row = 0; row < height; row++) {
          for (let col = 0; col < width; col++) {
            if (pixels[row * width + col] > 0) {
              visitForeground(col, row);
            }
          }
        }
      }
    }

    if (!foregroundPoints.length || maxCol < 0 || maxRow < 0) {
      return null;
    }

    const bbox: [number, number, number, number] = [minCol, minRow, maxCol + 1, maxRow + 1];
    const seedRatios = [
      [0.5, 0.5],
      [0.25, 0.25],
      [0.75, 0.25],
      [0.25, 0.75],
      [0.75, 0.75],
      [0.5, 0.2],
      [0.2, 0.5],
      [0.8, 0.5],
    ].slice(0, Math.max(1, maxPoints));

    const unique = new Set<string>();
    const sampledPoints: number[][] = [];
    for (const [rx, ry] of seedRatios) {
      const tx = minCol + (maxCol - minCol) * rx;
      const ty = minRow + (maxRow - minRow) * ry;
      let best: number[] | null = null;
      let bestDist = Number.POSITIVE_INFINITY;
      for (const [px, py] of foregroundPoints) {
        const dist = (px - tx) * (px - tx) + (py - ty) * (py - ty);
        if (dist < bestDist) {
          best = [px, py];
          bestDist = dist;
        }
      }
      if (!best) continue;
      const key = `${best[0]}:${best[1]}`;
      if (unique.has(key)) continue;
      unique.add(key);
      sampledPoints.push(best);
    }

    // 负样本点：bbox 外围 8 个方向，标签=0，告诉 SAM 物体边界
    const negPoints: number[][] = [];
    const pad = Math.max(5, Math.round((maxCol - minCol) * 0.1));
    const candidates: [number, number][] = [
      [minCol - pad, minRow - pad], [maxCol + pad, minRow - pad],
      [minCol - pad, maxRow + pad], [maxCol + pad, maxRow + pad],
      [(minCol + maxCol) / 2, minRow - pad], [(minCol + maxCol) / 2, maxRow + pad],
      [minCol - pad, (minRow + maxRow) / 2], [maxCol + pad, (minRow + maxRow) / 2],
    ];
    for (const [cx, cy] of candidates) {
      negPoints.push([Math.max(0, Math.round(cx)), Math.max(0, Math.round(cy))]);
    }

    const allPoints = [...sampledPoints, ...negPoints];
    const allLabels = [...sampledPoints.map(() => 1), ...negPoints.map(() => 0)];

    return { bbox, points: allPoints, labels: allLabels };
  }

  /** 提取当前 slice 上活跃 segment 的掩码 RLE（用于 mask prompt） */
  async function _getSliceMaskRLE(viewportId: string, sliceIdx: number) {
    const activeSeg = segmentationService.getActiveSegmentation(viewportId);
    if (!activeSeg?.segmentationId) return null;
    const { cache: csCache } = await import('@cornerstonejs/core');
    const { segmentation: csSeg } = await import('@cornerstonejs/tools');
    const segObj = csSeg.state.getSegmentation(activeSeg.segmentationId);
    const labelmapData = segObj?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
    const volumeId = (labelmapData as any)?.volumeId;
    const stackImageIds = (labelmapData as any)?.imageIds as string[] | undefined;
    const activeIdx = segmentationService.getActiveSegment(viewportId)?.segmentIndex ?? 1;

    let maskFlat: Uint8Array | null = null;
    let w = 0, h = 0;

    if (volumeId) {
      const vol = csCache.getVolume(volumeId);
      const [cols, rows] = vol.dimensions;
      const scalar = vol.getScalarData() as Uint8Array;
      const off = sliceIdx * cols * rows;
      maskFlat = new Uint8Array(cols * rows);
      for (let i = 0; i < cols * rows; i++) {
        maskFlat[i] = scalar[off + i] === activeIdx ? 1 : 0;
      }
      w = cols; h = rows;
    } else if (stackImageIds?.[sliceIdx]) {
      const img = (csCache as any).getImage(stackImageIds[sliceIdx]);
      const pixels = img?.getPixelData?.();
      w = img?.width ?? 0; h = img?.height ?? 0;
      if (pixels && w > 0) {
        maskFlat = new Uint8Array(w * h);
        for (let i = 0; i < w * h; i++) maskFlat[i] = pixels[i] === activeIdx ? 1 : 0;
      }
    }

    if (!maskFlat || w === 0) return null;

    // 简单 RLE 编码
    const counts: number[] = [];
    let cur = maskFlat[0];
    let run = 1;
    for (let i = 1; i < maskFlat.length; i++) {
      if (maskFlat[i] === cur) { run++; }
      else { counts.push(run); cur = maskFlat[i]; run = 1; }
    }
    counts.push(run);
    return { counts, starts_with: maskFlat[0], width: w, height: h };
  }

  /** 膨胀 RLE 掩码：解码→缩小→重新编码，模拟形态学膨胀 */
  function _dilateMaskRLE(rle: { counts: number[]; starts_with: number; width: number; height: number }, ratio: number) {
    const total = rle.width * rle.height;
    const flat = new Uint8Array(total);
    let idx = 0, cv = rle.starts_with;
    for (const cnt of rle.counts) {
      if (cv === 1) flat.fill(1, idx, idx + cnt);
      idx += cnt; cv = 1 - cv;
    }
    // 缩小到 1/(1+ratio) 再放大回原尺寸 = 膨胀效果
    const smallW = Math.max(1, Math.round(rle.width / (1 + ratio)));
    const smallH = Math.max(1, Math.round(rle.height / (1 + ratio)));
    const mask2d = new Array(rle.height);
    for (let y = 0; y < rle.height; y++) {
      mask2d[y] = flat.slice(y * rle.width, (y + 1) * rle.width);
    }
    // 简单缩放：对小尺寸用最近邻采样然后放大
    const dilated = new Uint8Array(total);
    for (let y = 0; y < rle.height; y++) {
      for (let x = 0; x < rle.width; x++) {
        const sx = Math.round((x / rle.width) * smallW);
        const sy = Math.round((y / rle.height) * smallH);
        // 检查缩小图对应位置及邻域
        let hasOne = false;
        for (let dy = -1; dy <= 1 && !hasOne; dy++) {
          for (let dx = -1; dx <= 1 && !hasOne; dx++) {
            const nx = Math.min(smallW - 1, Math.max(0, sx + dx));
            const ny = Math.min(smallH - 1, Math.max(0, sy + dy));
            const ox = Math.round((nx / smallW) * rle.width);
            const oy = Math.round((ny / smallH) * rle.height);
            if (ox >= 0 && ox < rle.width && oy >= 0 && oy < rle.height && flat[oy * rle.width + ox] === 1) {
              hasOne = true;
            }
          }
        }
        dilated[y * rle.width + x] = hasOne ? 1 : 0;
      }
    }
    // 重新编码
    const counts: number[] = [];
    let cur = dilated[0], run = 1;
    for (let i = 1; i < total; i++) {
      if (dilated[i] === cur) { run++; }
      else { counts.push(run); cur = dilated[i]; run = 1; }
    }
    counts.push(run);
    return { counts, starts_with: dilated[0], width: rle.width, height: rle.height };
  }

  /** RLE 交集：a ∩ b，结果尺寸取两者较小值 */
  function _intersectRLE(a: any, b: any) {
    const w = Math.min(a.width, b.width), h = Math.min(a.height, b.height);
    const total = w * h;
    const decA = _decodeRLE(a), decB = _decodeRLE(b);
    const nzA = decA.reduce((s: number, v: number) => s + (v > 0 ? 1 : 0), 0);
    const nzB = decB.reduce((s: number, v: number) => s + (v > 0 ? 1 : 0), 0);
    const out = new Uint8Array(total);
    for (let i = 0; i < total; i++) {
      out[i] = (decA[i] ?? 0) && (decB[i] ?? 0) ? 1 : 0;
    }
    const nzOut = out.reduce((s, v) => s + (v > 0 ? 1 : 0), 0);
    console.log(`[_intersectRLE] A=${nzA} B=${nzB} → intersect=${nzOut} (${w}x${h})`);
    const counts: number[] = [];
    let cur = out[0], run = 1;
    for (let i = 1; i < total; i++) {
      if (out[i] === cur) { run++; }
      else { counts.push(run); cur = out[i]; run = 1; }
    }
    counts.push(run);
    return { counts, starts_with: out[0], width: w, height: h };
  }
  function _decodeRLE(rle: any) {
    const total = rle.width * rle.height;
    const flat = new Uint8Array(total);
    let idx = 0, cv = rle.starts_with;
    for (const cnt of rle.counts) {
      if (cv === 1) flat.fill(1, idx, idx + cnt);
      idx += cnt; cv = 1 - cv;
    }
    return flat;
  }

  async function _clearSegmentationSlice(segmentationId: string, segmentIndex: number, sliceIdx: number) {
    const { cache: csCache } = await import('@cornerstonejs/core');
    const { segmentation: csSeg } = await import('@cornerstonejs/tools');
    const segObj = csSeg.state.getSegmentation(segmentationId);
    const labelmapData = segObj?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
    const labelmapVolume = labelmapData?.volumeId ? csCache.getVolume(labelmapData.volumeId) : null;
    const stackImageIds = (labelmapData as any)?.imageIds as string[] | undefined;

    if (labelmapVolume) {
      const { dimensions } = labelmapVolume;
      const [cols, rows] = dimensions;
      const scalarData = labelmapVolume.getScalarData() as Uint8Array;
      const sliceOffset = sliceIdx * cols * rows;
      const sliceView = scalarData.subarray(sliceOffset, sliceOffset + cols * rows);
      for (let idx = 0; idx < sliceView.length; idx++) {
        if (sliceView[idx] === segmentIndex) {
          sliceView[idx] = 0;
        }
      }
    } else if (stackImageIds?.length && stackImageIds[sliceIdx]) {
      const imageId = stackImageIds[sliceIdx];
      const sliceImage = (csCache as any).getImage(imageId);
      const pixels = sliceImage?.getPixelData?.();
      if (pixels) {
        for (let idx = 0; idx < pixels.length; idx++) {
          if (pixels[idx] === segmentIndex) {
            pixels[idx] = 0;
          }
        }
      }
    }
    (segmentationUtils as any).triggerSegmentationModified?.(segmentationId);
    const activeViewportId = viewportGridService.getActiveViewportId();
    if (activeViewportId) {
      (cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any)?.render?.();
    }
  }

  const actions = {
    hydrateSecondaryDisplaySet: async ({ displaySet, viewportId }) => {
      if (!displaySet) {
        return;
      }

      if (displaySet.isOverlayDisplaySet) {
        // update the previously stored segmentationPresentation with the new viewportId
        // presentation so that when we put the referencedDisplaySet back in the viewport
        // it will have the correct segmentation representation hydrated
        commandsManager.runCommand('updateStoredSegmentationPresentation', {
          displaySet,
          type:
            displaySet.Modality === 'SEG'
              ? SegmentationRepresentations.Labelmap
              : SegmentationRepresentations.Contour,
        });
      }

      const referencedDisplaySetInstanceUID = displaySet.referencedDisplaySetInstanceUID;

      const storePositionPresentation = refDisplaySet => {
        // update the previously stored positionPresentation with the new viewportId
        // presentation so that when we put the referencedDisplaySet back in the viewport
        // it will be in the correct position zoom and pan
        commandsManager.runCommand('updateStoredPositionPresentation', {
          viewportId,
          displaySetInstanceUIDs: [refDisplaySet.displaySetInstanceUID],
        });
      };

      if (displaySet.Modality === 'SEG' || displaySet.Modality === 'RTSTRUCT') {
        const referencedDisplaySet = displaySetService.getDisplaySetByUID(
          referencedDisplaySetInstanceUID
        );
        storePositionPresentation(referencedDisplaySet);
        return commandsManager.runCommand('loadSegmentationDisplaySetsForViewport', {
          viewportId,
          displaySetInstanceUIDs: [referencedDisplaySet.displaySetInstanceUID],
        });
      } else if (displaySet.Modality === 'SR') {
        const results = commandsManager.runCommand('hydrateStructuredReport', {
          displaySetInstanceUID: displaySet.displaySetInstanceUID,
        });
        const { SeriesInstanceUIDs } = results;
        const referencedDisplaySets = displaySetService.getDisplaySetsForSeries(
          SeriesInstanceUIDs[0]
        );
        referencedDisplaySets.forEach(storePositionPresentation);

        if (referencedDisplaySets.length) {
          actions.setDisplaySetsForViewports({
            viewportsToUpdate: [
              {
                viewportId: viewportGridService.getActiveViewportId(),
                displaySetInstanceUIDs: [referencedDisplaySets[0].displaySetInstanceUID],
              },
            ],
          });
        }
        return results;
      }
    },
    runSegmentBidirectional: async ({ segmentationId, segmentIndex } = {}) => {
      // Get active segmentation if not specified
      const targetSegmentation =
        segmentationId && segmentIndex
          ? { segmentationId, segmentIndex }
          : _getActiveSegmentationInfo();

      const { segmentationId: targetId, segmentIndex: targetIndex } = targetSegmentation;

      // Get bidirectional measurement data
      const bidirectionalData = await cstUtils.segmentation.getSegmentLargestBidirectional({
        segmentationId: targetId,
        segmentIndices: [targetIndex],
      });

      const activeViewportId = viewportGridService.getActiveViewportId();

      // Process each bidirectional measurement
      bidirectionalData.forEach(measurement => {
        const { segmentIndex, majorAxis, minorAxis } = measurement;

        // Create annotation
        const annotation = cornerstoneTools.SegmentBidirectionalTool.hydrate(
          activeViewportId,
          [majorAxis, minorAxis],
          {
            segmentIndex,
            segmentationId: targetId,
          }
        );

        measurement.annotationUID = annotation.annotationUID;

        // Update segmentation stats
        const updatedSegmentation = updateSegmentBidirectionalStats({
          segmentationId: targetId,
          segmentIndex: targetIndex,
          bidirectionalData: measurement,
          segmentationService,
          annotation,
        });

        // Save changes if needed
        if (updatedSegmentation) {
          segmentationService.addOrUpdateSegmentation({
            segmentationId: targetId,
            segments: updatedSegmentation.segments,
          });
        }
      });

      // get the active segmentIndex bidirectional annotation and jump to it
      const activeBidirectional = bidirectionalData.find(
        measurement => measurement.segmentIndex === targetIndex
      );
      commandsManager.run('jumpToMeasurement', {
        uid: activeBidirectional.annotationUID,
      });
    },
    interpolateLabelmap: () => {
      const { segmentationId, segmentIndex } = _getActiveSegmentationInfo();
      labelmapInterpolation.interpolate({
        segmentationId,
        segmentIndex,
      });
    },
    /**
     * Generates the selector props for the context menu, specific to
     * the cornerstone viewport, and then runs the context menu.
     */
    showCornerstoneContextMenu: options => {
      const element = _getActiveViewportEnabledElement()?.viewport?.element;

      const optionsToUse = { ...options, element };
      const { useSelectedAnnotation, nearbyToolData, event } = optionsToUse;

      // This code is used to invoke the context menu via keyboard shortcuts
      if (useSelectedAnnotation && !nearbyToolData) {
        const firstAnnotationSelected = getFirstAnnotationSelected(element);
        // filter by allowed selected tools from config property (if there is any)
        const isToolAllowed =
          !optionsToUse.allowedSelectedTools ||
          optionsToUse.allowedSelectedTools.includes(firstAnnotationSelected?.metadata?.toolName);
        if (isToolAllowed) {
          optionsToUse.nearbyToolData = firstAnnotationSelected;
        } else {
          return;
        }
      }

      optionsToUse.defaultPointsPosition = [];
      // if (optionsToUse.nearbyToolData) {
      //   optionsToUse.defaultPointsPosition = commandsManager.runCommand(
      //     'getToolDataActiveCanvasPoints',
      //     { toolData: optionsToUse.nearbyToolData }
      //   );
      // }

      // TODO - make the selectorProps richer by including the study metadata and display set.
      optionsToUse.selectorProps = {
        toolName: optionsToUse.nearbyToolData?.metadata?.toolName,
        value: optionsToUse.nearbyToolData,
        uid: optionsToUse.nearbyToolData?.annotationUID,
        nearbyToolData: optionsToUse.nearbyToolData,
        event,
        ...optionsToUse.selectorProps,
      };

      commandsManager.run(options, optionsToUse);
    },
    updateStoredSegmentationPresentation: ({ displaySet, type }) => {
      const { addSegmentationPresentationItem } = useSegmentationPresentationStore.getState();

      const referencedDisplaySetInstanceUID = displaySet.referencedDisplaySetInstanceUID;
      addSegmentationPresentationItem(referencedDisplaySetInstanceUID, {
        segmentationId: displaySet.displaySetInstanceUID,
        hydrated: true,
        type,
      });
    },
    updateStoredPositionPresentation: ({
      viewportId,
      displaySetInstanceUIDs,
      referencedImageId,
      options,
    }) => {
      const presentations = cornerstoneViewportService.getPresentations(viewportId);
      const { positionPresentationStore, setPositionPresentation, getPositionPresentationId } =
        usePositionPresentationStore.getState();

      // Look inside positionPresentationStore and find the key that includes ALL the displaySetInstanceUIDs
      // and the value has viewportId as activeViewportId.
      let previousReferencedDisplaySetStoreKey;

      if (
        displaySetInstanceUIDs &&
        Array.isArray(displaySetInstanceUIDs) &&
        displaySetInstanceUIDs.length > 0
      ) {
        previousReferencedDisplaySetStoreKey = Object.entries(positionPresentationStore).find(
          ([key, value]) => {
            return (
              displaySetInstanceUIDs.every(uid => key.includes(uid)) &&
              value.viewportId === viewportId
            );
          }
        )?.[0];
      }

      // Create presentation data with referencedImageId and options if provided
      const presentationData = referencedImageId
        ? {
            ...presentations.positionPresentation,
            viewReference: {
              referencedImageId,
              ...options,
            },
          }
        : presentations.positionPresentation;

      if (previousReferencedDisplaySetStoreKey) {
        setPositionPresentation(previousReferencedDisplaySetStoreKey, presentationData);
        return;
      }

      // if not found means we have not visited that referencedDisplaySetInstanceUID before
      // so we need to grab the positionPresentationId directly from the store,
      // Todo: this is really hacky, we should have a better way for this
      const positionPresentationId = getPositionPresentationId({
        displaySetInstanceUIDs,
        viewportId,
      });

      setPositionPresentation(positionPresentationId, presentationData);
    },
    getNearbyToolData({ nearbyToolData, element, canvasCoordinates }) {
      return nearbyToolData ?? cstUtils.getAnnotationNearPoint(element, canvasCoordinates);
    },
    getNearbyAnnotation({ element, canvasCoordinates }) {
      const nearbyToolData = actions.getNearbyToolData({
        nearbyToolData: null,
        element,
        canvasCoordinates,
      });

      const isAnnotation = toolName => {
        const enabledElement = getEnabledElement(element);

        if (!enabledElement) {
          return;
        }

        const { renderingEngineId, viewportId } = enabledElement;
        const toolGroup = ToolGroupManager.getToolGroupForViewport(viewportId, renderingEngineId);

        const toolInstance = toolGroup.getToolInstance(toolName);

        return toolInstance?.constructor?.isAnnotation ?? true;
      };

      return nearbyToolData?.metadata?.toolName && isAnnotation(nearbyToolData.metadata.toolName)
        ? nearbyToolData
        : null;
    },
    /**
     * Common logic for handling measurement label updates through dialog
     * @param uid - measurement uid
     * @returns Promise that resolves when the label is updated
     */
    _handleMeasurementLabelDialog: async uid => {
      const labelConfig = customizationService.getCustomization('measurementLabels');
      const renderContent = customizationService.getCustomization('ui.labellingComponent');
      const measurement = measurementService.getMeasurement(uid);

      if (!measurement) {
        console.debug('No measurement found for label editing');
        return;
      }

      if (!labelConfig) {
        const label = await callInputDialog({
          uiDialogService,
          title: 'Edit Measurement Label',
          placeholder: measurement.label || 'Enter new label',
          defaultValue: measurement.label,
        });

        if (label !== undefined && label !== null) {
          measurementService.update(uid, { ...measurement, label }, true);
        }
        return;
      }

      const val = await callInputDialogAutoComplete({
        measurement,
        uiDialogService,
        labelConfig,
        renderContent,
      });

      if (val !== undefined && val !== null) {
        measurementService.update(uid, { ...val }, true);
      }
    },
    /**
     * Show the measurement labelling input dialog and update the label
     * on the measurement with a response if not cancelled.
     */
    setMeasurementLabel: async ({ uid }) => {
      await actions._handleMeasurementLabelDialog(uid);
    },
    renameMeasurement: async ({ uid }) => {
      await actions._handleMeasurementLabelDialog(uid);
    },
    /**
     *
     * @param props - containing the updates to apply
     * @param props.measurementKey - chooses the measurement key to apply the
     *        code to.  This will typically be finding or site to apply a
     *        finding code or a findingSites code.
     * @param props.code - A coding scheme value from DICOM, including:
     *       * CodeValue - the language independent code, for example '1234'
     *       * CodingSchemeDesignator - the issue of the code value
     *       * CodeMeaning - the text value shown to the user
     *       * ref - a string reference in the form `<designator>:<codeValue>`
     *       * type - defaulting to 'finding'.  Will replace other codes of same type
     *       * style - a styling object to use
     *       * Other fields
     *     Note it is a valid option to remove the finding or site values by
     *     supplying null for the code.
     * @param props.uid - the measurement UID to find it with
     * @param props.label - the text value for the code.  Has NOTHING to do with
     *        the measurement label, which can be set with textLabel
     * @param props.textLabel is the measurement label to apply.  Set to null to
     *            delete.
     *
     * If the measurementKey is `site`, then the code will also be added/replace
     * the 0 element of findingSites.  This behaviour is expected to be enhanced
     * in the future with ability to set other site information.
     */
    updateMeasurement: props => {
      const { code, uid, textLabel, label } = props;
      let { style } = props;
      const measurement = measurementService.getMeasurement(uid);
      if (!measurement) {
        console.warn('No measurement found to update', uid);
        return;
      }
      const updatedMeasurement = {
        ...measurement,
      };
      // Call it textLabel as the label value
      // TODO - remove the label setting when direct rendering of findingSites is enabled
      if (textLabel !== undefined) {
        updatedMeasurement.label = textLabel;
      }
      if (code !== undefined) {
        const measurementKey = code.type || 'finding';

        if (code.ref && !code.CodeValue) {
          const split = code.ref.indexOf(':');
          code.CodeValue = code.ref.substring(split + 1);
          code.CodeMeaning = code.text || label;
          code.CodingSchemeDesignator = code.ref.substring(0, split);
        }
        updatedMeasurement[measurementKey] = code;
        if (measurementKey !== 'finding') {
          if (updatedMeasurement.findingSites) {
            updatedMeasurement.findingSites = updatedMeasurement.findingSites.filter(
              it => it.type !== measurementKey
            );
            updatedMeasurement.findingSites.push(code);
          } else {
            updatedMeasurement.findingSites = [code];
          }
        }
      }

      style ||= updatedMeasurement.finding?.style;
      style ||= updatedMeasurement.findingSites?.find(site => site?.style)?.style;

      if (style) {
        // Reset the selected values to preserve appearance on selection
        style.lineDashSelected ||= style.lineDash;
        annotation.config.style.setAnnotationStyles(measurement.uid, style);

        // this is a bit ugly, but given the underlying behavior, this is how it needs to work.
        switch (measurement.toolName) {
          case toolNames.PlanarFreehandROI: {
            const targetAnnotation = annotation.state.getAnnotation(measurement.uid);
            targetAnnotation.data.isOpenUShapeContour = !!style.isOpenUShapeContour;
            break;
          }
          default:
            break;
        }
      }
      measurementService.update(updatedMeasurement.uid, updatedMeasurement, true);
    },

    /**
     * Jumps to the specified (by uid) measurement in the active viewport.
     * Also marks any provided display measurements isActive value
     */
    jumpToMeasurement: ({ uid, displayMeasurements = [] }) => {
      measurementService.jumpToMeasurement(viewportGridService.getActiveViewportId(), uid);
      for (const measurement of displayMeasurements) {
        measurement.isActive = measurement.uid === uid;
      }
    },

    removeMeasurement: ({ uid }) => {
      if (Array.isArray(uid)) {
        measurementService.removeMany(uid);
      } else {
        measurementService.remove(uid);
      }
    },

    toggleLockMeasurement: ({ uid }) => {
      measurementService.toggleLockMeasurement(uid);
    },

    toggleVisibilityMeasurement: ({ uid, items, visibility }) => {
      if (visibility === undefined && items?.length) {
        visibility = !items[0].isVisible;
      }
      if (Array.isArray(uid)) {
        measurementService.toggleVisibilityMeasurementMany(uid, visibility);
      } else {
        measurementService.toggleVisibilityMeasurement(uid, visibility);
      }
    },

    /**
     * Download the CSV report for the measurements.
     */
    downloadCSVMeasurementsReport: ({ measurementFilter }) => {
      utils.downloadCSVReport(measurementService.getMeasurements(measurementFilter));
    },

    downloadCSVSegmentationReport: ({ segmentationId }) => {
      const segmentation = segmentationService.getSegmentation(segmentationId);

      const { representationData } = segmentation;
      const { Labelmap } = representationData;
      const { referencedImageIds } = Labelmap;

      const firstImageId = referencedImageIds[0];

      // find displaySet for firstImageId
      const displaySet = displaySetService
        .getActiveDisplaySets()
        .find(ds => ds.imageIds?.some(i => i === firstImageId));

      const {
        SeriesNumber,
        SeriesInstanceUID,
        StudyInstanceUID,
        SeriesDate,
        SeriesTime,
        SeriesDescription,
      } = displaySet;

      const additionalInfo = {
        reference: {
          SeriesNumber,
          SeriesInstanceUID,
          StudyInstanceUID,
          SeriesDate,
          SeriesTime,
          SeriesDescription,
        },
      };

      generateSegmentationCSVReport(segmentation, additionalInfo);
    },

    // Retrieve value commands
    getActiveViewportEnabledElement: _getActiveViewportEnabledElement,

    setViewportActive: ({ viewportId }) => {
      const viewportInfo = cornerstoneViewportService.getViewportInfo(viewportId);
      if (!viewportInfo) {
        console.warn('No viewport found for viewportId:', viewportId);
        return;
      }

      viewportGridService.setActiveViewportId(viewportId);
    },
    arrowTextCallback: async ({ callback }) => {
      const labelConfig = customizationService.getCustomization('measurementLabels');
      const renderContent = customizationService.getCustomization('ui.labellingComponent');

      const value = await callInputDialogAutoComplete({
        uiDialogService,
        labelConfig,
        renderContent,
      });
      callback?.(value);
    },

    toggleCine: () => {
      const { viewports } = viewportGridService.getState();
      const { isCineEnabled } = cineService.getState();
      cineService.setIsCineEnabled(!isCineEnabled);
      viewports.forEach((_, index) => cineService.setCine({ id: index, isPlaying: false }));
    },

    setViewportWindowLevel({
      viewportId,
      windowWidth,
      windowCenter,
      displaySetInstanceUID,
    }: {
      viewportId: string;
      windowWidth: number;
      windowCenter: number;
      displaySetInstanceUID?: string;
    }) {
      // convert to numbers
      const windowWidthNum = Number(windowWidth);
      const windowCenterNum = Number(windowCenter);

      // get actor from the viewport
      const renderingEngine = cornerstoneViewportService.getRenderingEngine();
      const viewport = renderingEngine.getViewport(viewportId);

      const { lower, upper } = csUtils.windowLevel.toLowHighRange(windowWidthNum, windowCenterNum);

      if (viewport instanceof BaseVolumeViewport) {
        const volumeId = actions.getVolumeIdForDisplaySet({
          viewportId,
          displaySetInstanceUID,
        });
        viewport.setProperties(
          {
            voiRange: {
              upper,
              lower,
            },
          },
          volumeId
        );
      } else {
        viewport.setProperties({
          voiRange: {
            upper,
            lower,
          },
        });
      }
      viewport.render();
    },
    toggleViewportColorbar: ({ viewportId, displaySetInstanceUIDs, options = {} }) => {
      const hasColorbar = colorbarService.hasColorbar(viewportId);
      if (hasColorbar) {
        colorbarService.removeColorbar(viewportId);
        return;
      }
      colorbarService.addColorbar(viewportId, displaySetInstanceUIDs, options);
    },
    setWindowLevel(props) {
      const { toolGroupId } = props;
      const { viewportId } = _getActiveViewportEnabledElement();
      const viewportToolGroupId = toolGroupService.getToolGroupForViewport(viewportId);

      if (toolGroupId && toolGroupId !== viewportToolGroupId) {
        return;
      }

      actions.setViewportWindowLevel({ ...props, viewportId });
    },
    setWindowLevelPreset: ({ presetName, presetIndex }) => {
      const windowLevelPresets = customizationService.getCustomization(
        'cornerstone.windowLevelPresets'
      );

      const activeViewport = viewportGridService.getActiveViewportId();
      const viewport = cornerstoneViewportService.getCornerstoneViewport(activeViewport);
      const metadata = viewport.getImageData().metadata;

      const modality = metadata.Modality;

      if (!modality) {
        return;
      }

      const windowLevelPresetForModality = windowLevelPresets[modality];

      if (!windowLevelPresetForModality) {
        return;
      }

      const windowLevelPreset =
        windowLevelPresetForModality[presetName] ??
        Object.values(windowLevelPresetForModality)[presetIndex];

      actions.setViewportWindowLevel({
        viewportId: activeViewport,
        windowWidth: windowLevelPreset.window,
        windowCenter: windowLevelPreset.level,
      });
    },
    getVolumeIdForDisplaySet: ({ viewportId, displaySetInstanceUID }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
      if (viewport instanceof BaseVolumeViewport) {
        const volumeIds = viewport.getAllVolumeIds();
        const volumeId = volumeIds.find(id => id.includes(displaySetInstanceUID));
        return volumeId;
      }
      return null;
    },
    setToolEnabled: async ({ toolName, toggle, toolGroupId }) => {
      const { viewports } = viewportGridService.getState();

      if (!viewports.size) {
        return;
      }

      if (_isSegmentationEditingTool(toolName)) {
        try {
          await _ensureActiveSegmentation();
        } catch (e) {
          console.warn('[Segmentation] failed to initialize before enabling brush-like tool:', e);
        }
      }

      const toolGroup = toolGroupService.getToolGroup(toolGroupId ?? null);

      if (!toolGroup || !toolGroup.hasTool(toolName)) {
        return;
      }

      const toolIsEnabled = toolGroup.getToolOptions(toolName).mode === Enums.ToolModes.Enabled;

      // Toggle the tool's state only if the toggle is true
      if (toggle) {
        toolIsEnabled ? toolGroup.setToolDisabled(toolName) : toolGroup.setToolEnabled(toolName);
      } else {
        toolGroup.setToolEnabled(toolName);
      }

      const renderingEngine = cornerstoneViewportService.getRenderingEngine();
      renderingEngine.render();
    },
    toggleEnabledDisabledToolbar({ value, itemId, toolGroupId }) {
      const toolName = itemId || value;
      toolGroupId = toolGroupId ?? _getActiveViewportToolGroupId();

      const toolGroup = toolGroupService.getToolGroup(toolGroupId);
      if (!toolGroup || !toolGroup.hasTool(toolName)) {
        return;
      }

      const toolIsEnabled = toolGroup.getToolOptions(toolName).mode === Enums.ToolModes.Enabled;

      toolIsEnabled ? toolGroup.setToolDisabled(toolName) : toolGroup.setToolEnabled(toolName);
    },
    toggleActiveDisabledToolbar({ value, itemId, toolGroupId }) {
      const toolName = itemId || value;
      toolGroupId = toolGroupId ?? _getActiveViewportToolGroupId();
      const toolGroup = toolGroupService.getToolGroup(toolGroupId);
      if (!toolGroup || !toolGroup.hasTool(toolName)) {
        return;
      }

      const toolIsActive = [
        Enums.ToolModes.Active,
        Enums.ToolModes.Enabled,
        Enums.ToolModes.Passive,
      ].includes(toolGroup.getToolOptions(toolName).mode);

      toolIsActive
        ? toolGroup.setToolDisabled(toolName)
        : actions.setToolActive({ toolName, toolGroupId });

      // we should set the previously active tool to active after we set the
      // current tool disabled
      if (toolIsActive) {
        const prevToolName = toolGroup.getPrevActivePrimaryToolName();
        if (prevToolName !== toolName) {
          actions.setToolActive({ toolName: prevToolName, toolGroupId });
        }
      }
    },
    setToolActiveToolbar: async ({ value, itemId, toolName, toolGroupIds = [] }) => {
      // Sometimes it is passed as value (tools with options), sometimes as itemId (toolbar buttons)
      toolName = toolName || itemId || value;
      console.debug('setToolActiveToolbar', toolName);
      toolGroupIds = toolGroupIds.length ? toolGroupIds : toolGroupService.getToolGroupIds();

      if (_isSegmentationEditingTool(toolName)) {
        try {
          await _ensureActiveSegmentation();
        } catch (e) {
          console.warn('[Segmentation] failed to initialize before activating brush-like tool:', e);
        }
      }

      for (const toolGroupId of toolGroupIds) {
        await actions.setToolActive({ toolName, toolGroupId });
      }
    },
    setToolActive: async ({ toolName, toolGroupId = null }) => {
      const { viewports } = viewportGridService.getState();

      if (!viewports.size) {
        return;
      }

      if (_isSegmentationEditingTool(toolName)) {
        try {
          await _ensureActiveSegmentation();
        } catch (e) {
          console.warn('[Segmentation] failed to initialize before setToolActive:', e);
        }
      }

      const toolGroup = toolGroupService.getToolGroup(toolGroupId);

      if (!toolGroup) {
        return;
      }

      if (!toolGroup?.hasTool(toolName)) {
        return;
      }

      const activeToolName = toolGroup.getActivePrimaryMouseButtonTool();

      if (activeToolName) {
        const activeToolOptions = toolGroup.getToolConfiguration(activeToolName);
        activeToolOptions?.disableOnPassive
          ? toolGroup.setToolDisabled(activeToolName)
          : toolGroup.setToolPassive(activeToolName);
      }

      // Set the new toolName to be active
      toolGroup.setToolActive(toolName, {
        bindings: [
          {
            mouseButton: Enums.MouseBindings.Primary,
          },
        ],
      });
    },
    // capture viewport
    showDownloadViewportModal: () => {
      const { activeViewportId } = viewportGridService.getState();

      if (!cornerstoneViewportService.getCornerstoneViewport(activeViewportId)) {
        // Cannot download a non-cornerstone viewport (image).
        uiNotificationService.show({
          title: 'Download Image',
          message: 'Image cannot be downloaded',
          type: 'error',
        });
        return;
      }

      const { uiModalService } = servicesManager.services;

      if (uiModalService) {
        uiModalService.show({
          content: CornerstoneViewportDownloadForm,
          title: 'Download High Quality Image',
          contentProps: {
            activeViewportId,
            cornerstoneViewportService,
          },
          containerClassName: 'max-w-4xl p-4',
        });
      }
    },
    storeOriginSlice: async () => {
      const { activeViewportId } = viewportGridService.getState();
      const divForUpload = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`);
      if (!divForUpload) {
        originSliceBlob = null;
        return;
      }
      const canvas = await html2canvas(divForUpload as HTMLElement);
      originSliceBlob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png', 1.0));

      uiNotificationService.show({
        title: 'The screenshot was successful.',
        message: 'The screenshot of the original image has been saved and can be used for subsequent uploads.',
        type: 'success',
      });
    },
    showSAMUploadModal: async (options: {
      promptType?: 'points' | 'rectangle' | 'mask';
      reviewMode?: boolean;
      organHint?: string | null;
    } = {}) => {
      console.error('🔥🔥🔥 [SAM v3] showSAMUploadModal ENTRY — 新代码已加载！');
      const { activeViewportId } = viewportGridService.getState();
      const csViewport = cornerstoneViewportService.getCornerstoneViewport(activeViewportId);
      const reviewMode = Boolean(options.reviewMode);
      const workflow = getLesionWorkflow(activeViewportId);
      const organHint = options.organHint ?? workflow.organHint ?? organHintByViewport.get(activeViewportId) ?? null;

      const fmt = (s: number) => s.toFixed(2);

      if (!csViewport) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'Image cannot be uploaded',
          type: 'error',
        });
        return;
      }

      const { uiModalService } = servicesManager.services;

      // Only count "Select Prompt -> Render Completed".
      let t_prompt_selected: number | null = null;

      let promptType: 'points' | 'rectangle' | 'mask' | null = options.promptType ?? null;
      if (promptType) {
        t_prompt_selected = performance.now() / 1000;
      }

      if (!promptType) {
        promptType = await new Promise<'points' | 'rectangle' | 'mask' | null>(resolve => {
          if (!uiModalService) return resolve(null);

        const PromptSelector = () => {
          return React.createElement(
            'div',
            { style: { padding: 24, textAlign: 'center', color: '#fff' } }, 
            React.createElement('h3', { style: { marginBottom: 16, fontSize: 18 } }, 'Select MedSAM prompt type'),
            React.createElement(
              'div',
              { style: { display: 'flex', justifyContent: 'center', gap: 12 } },
              ...['points', 'rectangle', 'mask'].map(type =>
                React.createElement(
                  'button',
                  {
                    key: type,
                    onClick: () => {
                      // === Starting point: Select Prompt ===
                      t_prompt_selected = performance.now() / 1000;
                      resolve(type as any);
                      uiModalService.hide(modalId);
                    },
                    className: 'bg-blue-500 hover:bg-blue-600 text-white font-medium py-1 px-3 rounded text-sm',
                  },
                  type.toUpperCase()
                )
              )
            )
          );
        };

          const modalId = uiModalService.show({
            title: 'Select Prompt Type',
            content: PromptSelector,
            containerClassName: 'min-w-[300px] p-4',
            isDraggable: true,
          });
        });
      }

      if (!promptType) return;

      let loadingModalId: any = null;
      if (uiModalService) {
        loadingModalId = uiModalService.show({
          title: '',
          content: () =>
            React.createElement(
              'div',
              { style: { padding: 32, textAlign: 'center', color: '#fff' } },
              'Processing image, please wait...'
            ),
          containerClassName: 'min-w-[300px] p-4',
        });
      }

      const divForUpload = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`);
      if (!divForUpload) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'No viewport found for upload',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      const fileType = 'png';
      const screenshotCanvas = await html2canvas(divForUpload as HTMLElement);
      const screenshotBlob: Blob = await new Promise(resolve =>
        screenshotCanvas.toBlob(resolve, `image/${fileType}`, 1.0)
      );

      const formData = new FormData();
      formData.append('sam_image', screenshotBlob, `image.${fileType}`);

      // 提取当前切片的 SOPInstanceUID（用于后端直接读 DICOM）
      let sopInstanceUID = '';
      try {
        const currentImageId = (csViewport as any).getCurrentImageId?.();
        if (currentImageId) {
          // imageId 格式示例: "wadors:http://localhost:8042/.../instances/{id}/..."
          const match = currentImageId.match(/\/instances\/([^\/]+)\//i);
          if (match) sopInstanceUID = match[1];
        }
      } catch { /* ignore */ }
      if (originSliceBlob) {
        formData.append('file', originSliceBlob, 'origin_slice.png');
      }

      let selectedImageSpaceBBox: [number, number, number, number] | null = null;
      let selectedMaskPromptPoints: number[][] = [];
      let selectedMaskPromptLabels: number[] = [];
      let currentSliceIdx = 0;
      let currentImageId = '';
      try {
        currentSliceIdx = (csViewport as any).getCurrentImageIdIndex?.() ?? 0;
        currentImageId = (csViewport as any).getCurrentImageId?.() ?? '';
      } catch {
        currentSliceIdx = 0;
      }

      // ─── 提取提示框 bbox（Rectangle 或当前 Brush 掩码）───────────────
      if (promptType === 'rectangle') {
        try {
          const element = csViewport.element;
          const imageData = (csViewport as any).getImageData?.();
          const imageW = imageData?.dimensions?.[0] ?? screenshotCanvas.width;
          const imageH = imageData?.dimensions?.[1] ?? screenshotCanvas.height;
          const allAnnotations = annotation.state.getAllAnnotations?.() ?? [];
          const rects = allAnnotations.filter(rect =>
            ['RectangleROI', 'Rectangle', 'RectangleScissor'].includes(rect.metadata?.toolName) &&
            rect.data?.handles?.points?.length >= 2
          );

          if (rects.length > 0) {
            const lastRect = rects[rects.length - 1];
            const pts: number[][] = lastRect.data?.handles?.points ?? [];
            if (pts.length >= 2) {
              // ── 修复：直接用 image origin+spacing 做 world→pixel 转换 ──
              // 旧方法 canvasX * (imageW/canvasW) 假设图像从canvas(0,0)开始，但图像居中时会有偏移导致bbox错误
              let originX = 0, originY = 0, spacingCol = 1, spacingRow = 1;
              if (imageData?.origin && imageData?.spacing) {
                originX = imageData.origin[0] ?? 0;
                originY = imageData.origin[1] ?? 0;
                // Cornerstone3D spacing: [rowSpacing, colSpacing, ...]
                spacingCol = (imageData.spacing[1] ?? imageData.spacing[0] ?? 1);
                spacingRow = (imageData.spacing[0] ?? 1);
              }
              const imagePts = pts.map((p: number[]) => [
                Math.round((p[0] - originX) / Math.max(1e-6, spacingCol)),
                Math.round((p[1] - originY) / Math.max(1e-6, spacingRow)),
              ]);
              const imageXs = imagePts.map(p => p[0]);
              const imageYs = imagePts.map(p => p[1]);
              const rawImageBBox: [number, number, number, number] = [
                Math.min(...imageXs),
                Math.min(...imageYs),
                Math.max(...imageXs),
                Math.max(...imageYs),
              ];
              console.log(`[SAM] world→pixel bbox: [${rawImageBBox.join(',')}] (img ${imageW}x${imageH}, origin=[${originX},${originY}], spacing=[${spacingRow},${spacingCol}])`);

              // Organ-aware ROI cropping: clamp lesion bbox within current organ segmentation bbox when available.
              if (organHint) {
                const organBBox = await _getActiveSegmentationSliceBBox(activeViewportId, currentSliceIdx);
                if (organBBox) {
                  rawImageBBox[0] = Math.max(rawImageBBox[0], organBBox[0]);
                  rawImageBBox[1] = Math.max(rawImageBBox[1], organBBox[1]);
                  rawImageBBox[2] = Math.min(rawImageBBox[2], organBBox[2]);
                  rawImageBBox[3] = Math.min(rawImageBBox[3], organBBox[3]);
                }
              }

              selectedImageSpaceBBox = rawImageBBox;

              const screenshotBBox = [
                Math.round((rawImageBBox[0] / imageW) * screenshotCanvas.width),
                Math.round((rawImageBBox[1] / imageH) * screenshotCanvas.height),
                Math.round((rawImageBBox[2] / imageW) * screenshotCanvas.width),
                Math.round((rawImageBBox[3] / imageH) * screenshotCanvas.height),
              ];

              formData.append('bbox', screenshotBBox.join(','));
              console.log(`[SAM] 发送 bbox(image): ${rawImageBBox.join(',')}`);
            }
          }
        } catch (bboxErr) {
          console.warn('[SAM] bbox 提取失败，服务端将自动检测:', bboxErr);
        }
      }

      // ── 矩形模式降级：没找到 Cornerstone3D 标注时，从 labelmap 提取 bbox ──
      // OHIF 的 Rectangle 工具直接写 labelmap，不创建 Cornerstone3D 标注
      if (promptType === 'rectangle' && !selectedImageSpaceBBox) {
        try {
          const labelmapBBox = await _getActiveSegmentationSliceBBox(activeViewportId, currentSliceIdx);
          if (labelmapBBox) {
            selectedImageSpaceBBox = [...labelmapBBox] as [number, number, number, number];
            console.log(`[SAM] rectangle bbox from labelmap: [${selectedImageSpaceBBox.join(',')}]`);
          }
        } catch(e) { console.warn('[SAM] labelmap bbox fallback failed:', e); }
      }

      if (promptType === 'mask' && !selectedImageSpaceBBox) {
        try {
          const imageData = (csViewport as any).getImageData?.();
          const imageW = imageData?.dimensions?.[0] ?? screenshotCanvas.width;
          const imageH = imageData?.dimensions?.[1] ?? screenshotCanvas.height;
          const maskPromptData = await _getActiveSegmentationSlicePromptData(activeViewportId, currentSliceIdx);
          if (maskPromptData?.bbox) {
            selectedImageSpaceBBox = [...maskPromptData.bbox] as [number, number, number, number];
            selectedMaskPromptPoints = maskPromptData.points ?? [];
            selectedMaskPromptLabels = maskPromptData.labels ?? [];
            if (organHint) {
              const organBBox = await _getActiveSegmentationSliceBBox(activeViewportId, currentSliceIdx);
              if (organBBox) {
                selectedImageSpaceBBox[0] = Math.max(selectedImageSpaceBBox[0], organBBox[0]);
                selectedImageSpaceBBox[1] = Math.max(selectedImageSpaceBBox[1], organBBox[1]);
                selectedImageSpaceBBox[2] = Math.min(selectedImageSpaceBBox[2], organBBox[2]);
                selectedImageSpaceBBox[3] = Math.min(selectedImageSpaceBBox[3], organBBox[3]);
              }
            }

            const screenshotBBox = [
              Math.round((selectedImageSpaceBBox[0] / imageW) * screenshotCanvas.width),
              Math.round((selectedImageSpaceBBox[1] / imageH) * screenshotCanvas.height),
              Math.round((selectedImageSpaceBBox[2] / imageW) * screenshotCanvas.width),
              Math.round((selectedImageSpaceBBox[3] / imageH) * screenshotCanvas.height),
            ];

            formData.append('bbox', screenshotBBox.join(','));
            console.log(`[SAM] Brush mask bbox(image): ${selectedImageSpaceBBox.join(',')}`);
            if (selectedMaskPromptPoints.length) {
              formData.append(
                'points_coords',
                selectedMaskPromptPoints.map(point => `${point[0]},${point[1]}`).join(' ')
              );
              formData.append('points_labels', selectedMaskPromptLabels.join(' '));
            }
          }
        } catch (maskBboxErr) {
          console.warn('[SAM] brush mask bbox 提取失败:', maskBboxErr);
        }
      }
      // ────────────────────────────────────────────────────────────────────────

      let samImageUrl = '';
      let rleData: { counts: number[]; starts_with: number; width: number; height: number } | null = null;
      // 2D 预览优先级：MedSAM(8000, vit_b 1024x1024) > LiteMedSAM(8002) > fallback
      // MedSAM vit_b 是 1024x1024 分辨率，比 LiteMedSAM (256x256) 精度更高
      const useMedSAM2 = false;
      const useLite = await isLiteMedSAMAvailable();
      const useMedSAM = await (async () => {
        try {
          const r = await fetch('http://localhost:8000/health', { signal: AbortSignal.timeout(2000) });
          const d = await r.json();
          return d?.status === 'healthy' || d?.model_loaded === true;
        } catch { return false; }
      })();
      // MedSAM(8000) > LiteMedSAM(8002)
      const SAM_PORT = useMedSAM ? 8000 : (useLite ? 8002 : 8000);
      const IMAGE_URL_PREFIX = `http://localhost:${SAM_PORT}`;
      console.log(`[SAM] 2D backend: port=${SAM_PORT}, MedSAM=${useMedSAM}, LiteMedSAM=${useLite}`);

      try {
        // ── DICOM 路径：MedSAM/LiteMedSAM /segment_dicom ──
        if (sopInstanceUID && selectedImageSpaceBBox
            && (promptType === 'rectangle' || promptType === 'mask')) {
          const dicomPorts = useMedSAM ? [8000, 8002] : (useLite ? [8002, 8000] : [8000]);
          for (const port of dicomPorts) {
            try {
              // 只发 bbox，不发 mask_rle
              // LiteMedSAM 自己在 bbox 内找边界 → 后端裁剪到刷子范围（更精准）
              const reqBody: any = { sop_instance_uid: sopInstanceUID, bbox: selectedImageSpaceBBox };
              console.log(`[SAM] ========================================`);
              console.log(`[SAM] sending to port ${port} /segment_dicom`);
              console.log(`[SAM]   sliceIdx=${currentSliceIdx}, imageId=${currentImageId?.slice(-60)}`);
              console.log(`[SAM]   SOPInstanceUID=${sopInstanceUID}`);
              console.log(`[SAM]   bbox=[${selectedImageSpaceBBox.join(',')}] (${promptType})`);
              console.log(`[SAM] ========================================`);
              // 提取 viewport 当前窗宽窗位，传给后端确保图像一致
              try {
                const vp = cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any;
                // 尝试多种方式获取 VOI
                let wc: number | undefined, ww: number | undefined;
                const voi = vp?.getViewPresentation?.()?.voi ?? vp?.voi;
                if (voi?.windowCenter != null && voi?.windowWidth != null) {
                  wc = voi.windowCenter; ww = voi.windowWidth;
                } else {
                  // 备用：从 getProperties().voiRange 获取
                  const voiRange = vp?.getProperties?.()?.voiRange;
                  if (voiRange?.lower != null && voiRange?.upper != null) {
                    ww = voiRange.upper - voiRange.lower;
                    wc = (voiRange.upper + voiRange.lower) / 2;
                  }
                }
                if (wc != null && ww != null) {
                  reqBody.window_center = wc;
                  reqBody.window_width = ww;
                  console.log(`[SAM] viewport window: WC=${wc}, WW=${ww}`);
                }
              } catch(e) { console.warn('[SAM] failed to get VOI:', e); }
              // ── mask 模式：保存刷子 RLE，传给后端仅 bbox，返回后再做 S&M 裁剪 ──
              let savedBrushRle: any = null;  // 保存刷子 RLE 用于后处理裁剪
              try {
                savedBrushRle = await _getSliceMaskRLE(activeViewportId, currentSliceIdx);
                if (savedBrushRle) {
                  const nz = savedBrushRle.counts.reduce((s: number, c: number, i: number) =>
                    i % 2 === (savedBrushRle.starts_with === 1 ? 0 : 1) ? s + c : s, 0);
                  console.log(`[SAM] saved brush RLE for post-clip: ${savedBrushRle.width}x${savedBrushRle.height}, fg=${nz}`);
                }
              } catch(e) { console.warn('[SAM] save brush RLE failed:', e); }
              const dicomResp = await fetch(`http://localhost:${port}/segment_dicom`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqBody),
                signal: AbortSignal.timeout(port === 8000 ? 90000 : 20000),
              });
              if (dicomResp.ok) {
                const dicomData = await dicomResp.json();
                if (dicomData.success) {
                  rleData = dicomData.rle;
                  // ── 后处理：SAM 输出 S & 刷子 M → 只保留刷子范围内的分割 ──
                  if (rleData && savedBrushRle && promptType === 'mask') {
                    try {
                      rleData = _intersectRLE(rleData, savedBrushRle);
                      // 解码裁剪后 RLE 确认像素数
                      const cTotal = rleData.width * rleData.height;
                      const cFlat = new Uint8Array(cTotal);
                      let ci = 0, ccv = rleData.starts_with;
                      for (const cnt of rleData.counts) {
                        if (ccv === 1) cFlat.fill(1, ci, ci + cnt);
                        ci += cnt; ccv = 1 - ccv;
                      }
                      const cNnz = cFlat.reduce((s, v) => s + (v > 0 ? 1 : 0), 0);
                      console.log(`[SAM] POST-CLIP (S&M): ${cNnz} pixels (SAM raw=${dicomData.rle?.pixel_count}, brush=${savedBrushRle?.counts?.reduce((s:number,c:number,i:number)=>i%2===(savedBrushRle.starts_with===1?0:1)?s+c:s,0)})`);
                    } catch(e) { console.warn('[SAM] post-clip failed:', e); }
                  }
                  // ── 诊断：解码当前 rleData（可能是裁剪后的）──
                  const rawPx = dicomData.rle?.pixel_count ?? 'N/A';
                  const rawW = dicomData.rle?.width ?? '?';
                  const rawH = dicomData.rle?.height ?? '?';
                  // 立即解码 RLE 确认
                  const rawTotal = (rleData?.width ?? 0) * (rleData?.height ?? 0);
                  const rawDecoded = new Uint8Array(rawTotal);
                  let ri = 0, rcv = rleData?.starts_with ?? 0;
                  let rSum = 0;
                  for (const cnt of (rleData?.counts ?? [])) {
                    if (rcv === 1) rawDecoded.fill(1, ri, ri + cnt);
                    ri += cnt; rSum += cnt;
                    rcv = 1 - rcv;
                  }
                  const rNnz = rawDecoded.reduce((s, v) => s + (v > 0 ? 1 : 0), 0);
                  console.log(`[SAM] FINAL rle: decoded_nz=${rNnz}, size=${rawW}x${rawH}`);
                  // 2D 面积提示 — 使用裁剪后的像素数
                  const pixelArea = `${rNnz} px (clipped)`;
                  console.log(`[SAM] 2D area: ${pixelArea}`);
                  uiNotificationService.show({
                    title: 'SAM 2D Segmentation',
                    message: `Segmented area: ${pixelArea} — review, then Accept for 3D tracking`,
                    type: 'success',
                    duration: 5000,
                  });
                  console.log(`[SAM] Used /segment_dicom on port ${port} (model: ${dicomData.model ?? 'unknown'})`);
                  break; // success, stop trying
                }
              }
            } catch { /* port not available, try next */ }
          }
        }

        // ── 优先路径 2（截图）：LiteMedSAM → MedSAM 降级 ──
        if (!rleData) {
          const routeMap: Record<'points' | 'rectangle' | 'mask', string> = {
            points: '/points',
            rectangle: '/segment',
            // mask: 直接用 /segment + bbox（/points 后端忽略了点坐标，效果一样）
            mask: '/segment',
          };
          const route = routeMap[promptType];

          const screenshotPorts = useLite ? [8002, 8000] : [8000];
          for (const port of screenshotPorts) {
            try {
              const resp = await fetch(`http://localhost:${port}${route}`, {
                method: 'POST',
                body: formData,
                signal: AbortSignal.timeout(15000),
              });
              if (!resp.ok) continue;
              const data = await resp.json();
              if (data.success) {
                if (data.image_url) samImageUrl = `http://localhost:${port}${data.image_url}`;
                if (data.rle) rleData = data.rle;
                console.log(`[SAM] Screenshot path used port ${port} (model: ${data.model ?? 'unknown'})`);
                if (rleData) {
                  break;
                }
              }
            } catch { /* try next port */ }
          }

          // If backend returned preview image but no RLE, retry once with a full-image bbox
          // so we can still obtain a writable mask for 2D display/edit workflow.
          if (!rleData) {
            const fullBBox = `0,0,${Math.max(0, screenshotCanvas.width - 1)},${Math.max(0, screenshotCanvas.height - 1)}`;
            const fallbackPorts = useLite ? [8002, 8000] : [8000];

            for (const port of fallbackPorts) {
              try {
                const fallbackFormData = new FormData();
                fallbackFormData.append('sam_image', screenshotBlob, `image.${fileType}`);
                if (originSliceBlob) {
                  fallbackFormData.append('file', originSliceBlob, 'origin_slice.png');
                }
                fallbackFormData.append('bbox', fullBBox);

                const fallbackResp = await fetch(`http://localhost:${port}/segment`, {
                  method: 'POST',
                  body: fallbackFormData,
                  signal: AbortSignal.timeout(15000),
                });

                if (!fallbackResp.ok) continue;
                const fallbackData = await fallbackResp.json();
                if (!fallbackData?.success) continue;

                if (fallbackData.image_url) {
                  samImageUrl = `http://localhost:${port}${fallbackData.image_url}`;
                }
                if (fallbackData.rle) {
                  rleData = fallbackData.rle;
                  console.log(`[SAM] Full-bbox fallback produced RLE on port ${port}`);
                  break;
                }
              } catch {
                // try next port
              }
            }
          }
        }
      } catch (e) {
        console.error(e);
        uiNotificationService.show({
          title: 'MedSAM Error',
          message: 'MedSAM upload failed',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);

      // ─── 优先路径：RLE → 直接写入 Cornerstone3D labelmap ──────────────────────
      console.log('[SAM→DIAG] loadingModal hidden, rleData=', rleData ? `YES ${rleData.width}x${rleData.height}` : 'NO', 'reviewMode=', reviewMode);
      if (rleData) {
        try {
          const { cache: csCache } = await import('@cornerstonejs/core');
          const { segmentation: csSeg } = await import('@cornerstonejs/tools');

          const { segmentationId, segmentIndex } = await _ensureActiveSegmentation();

          // ── 单 segment 方案：先清空当前 slice 的刷子数据，再写入 SAM RLE ──
          // 简单可靠，不涉及多 segment 管理复杂度
          const segObj = csSeg.state.getSegmentation(segmentationId);
          const labelmapData = segObj?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
          const volumeId = (labelmapData as any)?.volumeId;
          const labelmapVolume = volumeId ? csCache.getVolume(volumeId) : null;
          const stackImageIds = (labelmapData as any)?.imageIds as string[] | undefined;

          // 获取当前切片 index（StackViewport）
          let sliceIdx = 0;
          const vpObj = csViewport as StackViewport;
          if (typeof (vpObj as any).getCurrentImageIdIndex === 'function') {
            sliceIdx = (vpObj as any).getCurrentImageIdIndex();
          }

          // 解码 RLE → Uint8Array（行优先）
          const { counts, starts_with: startsVal, width: rleW, height: rleH } = rleData;
          const total = rleW * rleH;
          const maskFlat = new Uint8Array(total);
          let idx = 0;
          let curVal = startsVal;
          for (const cnt of counts) {
            if (curVal === 1) maskFlat.fill(1, idx, idx + cnt);
            idx += cnt;
            curVal = curVal === 0 ? 1 : 0;
          }

          let wroteMask = false;

          if (labelmapVolume) {
            // labelmap volume: dims = [cols, rows, slices]
            const { dimensions } = labelmapVolume;
            const [cols, rows] = dimensions;
            const scalarData = labelmapVolume.getScalarData() as Uint8Array;
            const sliceOffset = sliceIdx * cols * rows;
            const sliceLen = cols * rows;

            // 先清除当前 slice 上的刷子数据
            let clearedCount = 0;
            for (let i = 0; i < sliceLen; i++) {
              if (scalarData[sliceOffset + i] === segmentIndex) {
                scalarData[sliceOffset + i] = 0;
                clearedCount++;
              }
            }
            console.log(`[SAM→Labelmap] cleared ${clearedCount} brush pixels on slice ${sliceIdx}`);

            // 将 mask 写入当前切片（mask 尺寸 vs labelmap 尺寸可能不同，需缩放）
            if (rleW === cols && rleH === rows) {
              let writeCount = 0;
              for (let i = 0; i < total; i++) {
                if (maskFlat[i] > 0) { scalarData[sliceOffset + i] = segmentIndex; writeCount++; }
              }
              console.log(`[SAM→Labelmap] wrote ${writeCount} SAM pixels (${rleW}x${rleH})`);
            } else {
              // 尺寸不匹配：双线性映射
              const scaleX = rleW / cols;
              const scaleY = rleH / rows;
              for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                  const srcX = Math.min(Math.round(c * scaleX), rleW - 1);
                  const srcY = Math.min(Math.round(r * scaleY), rleH - 1);
                  if (maskFlat[srcY * rleW + srcX] > 0) {
                    scalarData[sliceOffset + r * cols + c] = segmentIndex;
                  }
                }
              }
            }
            wroteMask = true;
          } else if (stackImageIds?.length && stackImageIds[sliceIdx]) {
            const imageId = stackImageIds[sliceIdx];
            const sliceImage = (csCache as any).getImage(imageId);
            const pixels = sliceImage?.getPixelData?.();
            const imgW = sliceImage?.width ?? 0;
            const imgH = sliceImage?.height ?? 0;
            if (pixels && imgW > 0 && imgH > 0) {
              // 清除该 slice 上 segment 旧数据
              const pixLen = imgW * imgH;
              let stackCleared = 0;
              for (let i = 0; i < pixLen; i++) {
                if (pixels[i] === segmentIndex) { pixels[i] = 0; stackCleared++; }
              }
              console.log(`[SAM→Labelmap] stack: cleared ${stackCleared} brush pixels (img ${imgW}x${imgH})`);
              // 验证：重新读取确认清除生效
              const verifyPixels = sliceImage?.getPixelData?.();
              let verifyCount = 0;
              if (verifyPixels) {
                for (let i = 0; i < pixLen; i++) {
                  if (verifyPixels[i] === segmentIndex) verifyCount++;
                }
              }
              console.log(`[SAM→Labelmap] stack: verify after clear: ${verifyCount} pixels still at segmentIndex`);

              let stackWritten = 0;
              if (rleW === imgW && rleH === imgH) {
                for (let i = 0; i < total; i++) {
                  if (maskFlat[i] > 0) { pixels[i] = segmentIndex; stackWritten++; }
                }
              } else {
                const scaleX = rleW / imgW;
                const scaleY = rleH / imgH;
                for (let r = 0; r < imgH; r++) {
                  for (let c = 0; c < imgW; c++) {
                    const srcX = Math.min(Math.round(c * scaleX), rleW - 1);
                    const srcY = Math.min(Math.round(r * scaleY), rleH - 1);
                    if (maskFlat[srcY * rleW + srcX] > 0) {
                      pixels[r * imgW + c] = segmentIndex; stackWritten++;
                    }
                  }
                }
              }
              console.log(`[SAM→Labelmap] stack: wrote ${stackWritten} SAM pixels (RLE ${rleW}x${rleH}, img ${imgW}x${imgH})`);
              wroteMask = true;
            }
          }

          if (wroteMask) {
            // ── 确保分割层可见 ──
            const csTools2d = await import('@cornerstonejs/tools');
            const segState2d = csTools2d.segmentation.state;
            const segObj2d = segState2d.getSegmentation(segmentationId);

            // 激活 segment
            try {
              segmentationService.setActiveSegment(segmentationId, segmentIndex);
            } catch { /* ignore */ }

            // 确保 Labelmap 表示已添加到当前 viewport
            try {
              const reps = segmentationService.getSegmentationRepresentations(activeViewportId, {
                segmentationId,
              });
              const hasLabelmap = reps?.some((r: any) => r.type === Enums.SegmentationRepresentations.Labelmap);
              if (!hasLabelmap) {
                await segmentationService.addSegmentationRepresentation(activeViewportId, {
                  segmentationId,
                  type: Enums.SegmentationRepresentations.Labelmap,
                });
              }
            } catch { /* ignore */ }

            // 触发修改 + 刷新缓存
            (segmentationUtils as any).triggerSegmentationModified?.(segmentationId);
            try {
              const csCache2d = await import('@cornerstonejs/core').then(m => m.cache);
              const repData2d = segObj2d?.representationData?.Labelmap;
              if (repData2d?.imageIds?.[sliceIdx]) {
                const imgId2d = repData2d.imageIds[sliceIdx];
                const cachedImg = (csCache2d as any).getImage(imgId2d);
                if (cachedImg) {
                  (cachedImg as any).imageFrame = undefined;
                  (cachedImg as any).preScale = undefined;
                }
              }
              if (repData2d?.volumeId) {
                const vol2d = (csCache2d as any).getVolume(repData2d.volumeId);
                if (vol2d?.vtkOpenGLTexture) {
                  vol2d.vtkOpenGLTexture.modified();
                }
              }
            } catch { /* best effort */ }
            csViewport.render?.();
            setTimeout(() => csViewport.render?.(), 150);
            setTimeout(() => csViewport.render?.(), 400);

            console.log(`[SAM→Labelmap] wrote slice ${sliceIdx}, segmentIndex=${segmentIndex} (cleared+rewritten)`);

            // 计时
            requestAnimationFrame(() => {
              if (t_prompt_selected != null) {
                const t_rendered = performance.now() / 1000;
                console.log(`[Latency][Frontend] Prompt→Labelmap = ${fmt(t_rendered - t_prompt_selected)} s`);
              }
            });

            uiNotificationService.show({
              title: reviewMode ? '2D Preview Ready' : 'SAM Segmentation',
              message: reviewMode
                ? `Preview generated on slice ${sliceIdx + 1}`
                : `Segmentation written to slice ${sliceIdx + 1}`,
              type: 'success',
            });

            if (reviewMode) {
              if (organHint) {
                workflow.organHint = organHint;
              }
              workflow.previewAccepted = false;

              let reviewPromptBBox = selectedImageSpaceBBox;
              if (!reviewPromptBBox) {
                reviewPromptBBox = await _getActiveSegmentationSliceBBox(activeViewportId, sliceIdx);
              }
              if (reviewPromptBBox) {
                upsertPromptFrame(activeViewportId, {
                  slice_idx: sliceIdx,
                  bbox: reviewPromptBBox,
                  points: promptType === 'mask' ? selectedMaskPromptPoints : undefined,
                  labels: promptType === 'mask' ? selectedMaskPromptLabels : undefined,
                  mask_rle: rleData || undefined,
                });
              }

              if (promptType === 'points') {
                try {
                  const imageData = (csViewport as any).getImageData?.();
                  const imageW = imageData?.dimensions?.[0] ?? screenshotCanvas.width;
                  const imageH = imageData?.dimensions?.[1] ?? screenshotCanvas.height;
                  const canvasEl = (csViewport.element as HTMLElement).querySelector('canvas') as HTMLCanvasElement | null;
                  const canvasW = canvasEl?.width ?? (csViewport.element as HTMLElement).clientWidth ?? screenshotCanvas.width;
                  const canvasH = canvasEl?.height ?? (csViewport.element as HTMLElement).clientHeight ?? screenshotCanvas.height;
                  const scaleToImageX = imageW / canvasW;
                  const scaleToImageY = imageH / canvasH;

                  const allAnnotations = annotation.state.getAllAnnotations?.() ?? [];
                  const promptPoints: number[][] = [];
                  const promptLabels: number[] = [];

                  allAnnotations.forEach((ann: any) => {
                    const handles = ann?.data?.handles?.points;
                    const toolName = String(ann?.metadata?.toolName ?? '').toLowerCase();
                    const looksLikePoint = toolName.includes('probe') || toolName.includes('point');
                    if (!looksLikePoint || !Array.isArray(handles) || handles.length < 1) return;
                    const canvasPoint = (csViewport as any).worldToCanvas?.(handles[0]);
                    if (!canvasPoint) return;
                    promptPoints.push([
                      Math.max(0, Math.round(canvasPoint[0] * scaleToImageX)),
                      Math.max(0, Math.round(canvasPoint[1] * scaleToImageY)),
                    ]);
                    // MVP: treat extracted points as positive prompts.
                    promptLabels.push(1);
                  });

                  if (promptPoints.length > 0) {
                    upsertPromptFrame(activeViewportId, {
                      slice_idx: sliceIdx,
                      points: promptPoints,
                      labels: promptLabels,
                    });
                  }
                } catch {
                  // best effort only
                }
              }
              // ── 2D 预览：从 Orthanc 拿干净 CT + SAM 轮廓 ──
              console.log('[SAM→DIAG] entering Accept2DContent modal, uiModalService=', !!uiModalService, 'reviewMode=', reviewMode);
              const accept3D = await new Promise<boolean>(async resolve => {
                if (!uiModalService) { console.error('[SAM→DIAG] uiModalService is NULL — modal cannot show!'); resolve(false); return; }

                let previewImageDataUrl = '';
                try {
                  // 1. 预览：从 DICOMweb 拿干净 CT（带窗位参数，与后端一致）
                  let cleanCT: HTMLImageElement | null = null;
                  try {
                    const imgId = (csViewport as any).getCurrentImageId?.() ?? '';
                    const m = imgId.match(/wadors:(https?:\/\/.+\/instances\/[^\/]+)/);
                    if (m) {
                      const vp = cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any;
                      const voi = vp?.getViewPresentation?.()?.voi ?? vp?.voi;
                      let url = m[1] + '/rendered';
                      if (voi?.windowCenter != null) url += '?window-center=' + voi.windowCenter + '&window-width=' + voi.windowWidth;
                      const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
                      if (resp.ok) {
                        const blob = await resp.blob();
                        cleanCT = await new Promise(r => { const img = new Image(); img.onload = () => r(img); img.onerror = () => r(null); img.src = URL.createObjectURL(blob); });
                      }
                    }
                  } catch { /* fallback */ }

                  const vpEl = (csViewport as any).element as HTMLElement;
                  const vpCanvas = vpEl?.querySelector('canvas') as HTMLCanvasElement | null;
                  // 预览尺寸统一为 512×512（与后端 debug 图一致，无拉伸）
                  const cw = 512;
                  const ch = 512;

                  const offscreen = document.createElement('canvas');
                  offscreen.width = cw;
                  offscreen.height = ch;
                  const ctx = offscreen.getContext('2d')!;

                  // 2. 底图：干净的 DICOM 图像（缩放到 512×512）
                  if (cleanCT) {
                    ctx.drawImage(cleanCT, 0, 0, cw, ch);
                  } else if (vpCanvas) {
                    // vpCanvas 非正方形 → 保持比例居中
                    const vw = vpCanvas.width, vh = vpCanvas.height;
                    const fitScale = Math.min(cw / vw, ch / vh);
                    const dw = vw * fitScale, dh = vh * fitScale;
                    const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
                    ctx.fillStyle = '#000';
                    ctx.fillRect(0, 0, cw, ch);
                    ctx.drawImage(vpCanvas, 0, 0, vw, vh, dx, dy, dw, dh);
                  }

                  // 3. 解码 SAM RLE 并叠加（降低透明度，弱化红色填充）
                  if (rleData) {
                    const { counts, starts_with: sv, width: rw, height: rh } = rleData;
                    // 诊断：确认预览用的是裁剪后的RLE
                    const prevTotal = rw * rh;
                    const prevFlat = new Uint8Array(prevTotal);
                    let pidx = 0, pcv = sv;
                    for (const cnt of counts) { if (pcv === 1) prevFlat.fill(1, pidx, pidx + cnt); pidx += cnt; pcv = 1 - pcv; }
                    const prevNnz = prevFlat.reduce((s, v) => s + (v > 0 ? 1 : 0), 0);
                    console.log(`[SAM→Preview] rendering ${prevNnz} pixels (RLE ${rw}x${rh}) — should match POST-CLIP count`);
                    const totalPx = rw * rh;
                    const maskArr = new Uint8Array(totalPx);
                    let idx = 0, cv = sv;
                    for (const cnt of counts) {
                      if (cv === 1) maskArr.fill(1, idx, idx + cnt);
                      idx += cnt; cv = cv === 0 ? 1 : 0;
                    }
                    // 红色半透明填充 — 已移除，预览只展示绿色轮廓（与后端 debug 图一致）
                    // 绿色轮廓 — 细线
                    ctx.strokeStyle = '#00ff00';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    for (let y = 0; y < rh; y++) {
                      for (let x = 0; x < rw; x++) {
                        if (maskArr[y * rw + x] === 0) continue;
                        const isEdge = x === 0 || x === rw - 1 || y === 0 || y === rh - 1 ||
                          maskArr[y * rw + (x - 1)] === 0 || maskArr[y * rw + (x + 1)] === 0 ||
                          maskArr[(y - 1) * rw + x] === 0 || maskArr[(y + 1) * rw + x] === 0;
                        if (isEdge) {
                          ctx.fillStyle = '#00ff00';
                          ctx.fillRect(x, y, 2, 2);
                        }
                      }
                    }
                    console.log(`[SAM→Preview] SAM contour rendered (RLE ${rw}x${rh})`);
                  }

                  previewImageDataUrl = offscreen.toDataURL('image/jpeg', 0.9);
                } catch (e) {
                  console.warn('[SAM→Preview] render failed:', e);
                }

                const Accept2DContent = () =>
                  React.createElement(
                    'div',
                    { style: { padding: 18, minWidth: 380, color: '#e5e7eb' } },
                    React.createElement('div', { style: { fontSize: 15, marginBottom: 4 } }, '✅ 2D preview applied on current slice.'),
                    React.createElement(
                      'div',
                      { style: { fontSize: 12, color: '#9ca3af', marginBottom: 12, lineHeight: 1.6 } },
                      'The SAM result has been written to the segmentation layer. The segmented region is shown in the viewport behind this dialog.'
                    ),
                    previewImageDataUrl ? React.createElement('img', {
                      src: previewImageDataUrl,
                      style: { width: '100%', maxHeight: 180, objectFit: 'contain', borderRadius: 6, border: '1px solid #333', marginBottom: 10 },
                    }) : null,
                    React.createElement('p', { style: { fontSize: 11, color: '#fbbf24', marginBottom: 6, marginTop: 2 } },
                      '💡 Capture a screenshot of the segmented view — it will be included in your AI report!'
                    ),
                    React.createElement(
                      'div',
                      { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
                      React.createElement(
                        'button',
                        {
                          className: 'bg-green-600 hover:bg-green-500 text-white font-medium py-1 px-3 rounded text-sm',
                          onClick: () => {
                            // 直接用弹窗中已渲染好的 SAM 分割预览图（CT + 绿色轮廓）
                            if (previewImageDataUrl) {
                              workflow.last2DScreenshot = previewImageDataUrl;
                              alert('2D Screenshot captured (' + (workflow.last2DScreenshot?.length||0) + ' chars). This is the SAM segmentation result — will appear in your AI report!');
                            } else {
                              alert('Preview not yet ready — please wait a moment and try again');
                            }
                          },
                        },
                        'Capture 2D View'
                      ),
                      React.createElement(
                        'button',
                        {
                          className: 'bg-green-700 hover:bg-green-600 text-white font-medium py-2 px-4 rounded text-sm',
                          onClick: () => {
                            uiModalService.hide(accept2DModalId);
                            resolve(true);
                          },
                        },
                        'Accept & Start 3D Tracking'
                      ),
                      React.createElement(
                        'button',
                        {
                          className: 'bg-slate-700 hover:bg-slate-600 text-white font-medium py-2 px-4 rounded text-sm',
                          onClick: () => {
                            uiModalService.hide(accept2DModalId);
                            resolve(false);
                          },
                        },
                        'Keep Refining (Redraw)'
                      )
                    )
                  );

                const accept2DModalId = uiModalService.show({
                  title: '2D Preview Ready — Accept?',
                  content: Accept2DContent,
                  containerClassName: 'min-w-[400px] p-4',
                  isDraggable: true,
                });
              });

              if (accept3D) {
                workflow.previewAccepted = true;
                await actions.segment3DSAM2({
                  promptFrames: workflow.promptFrames,
                  organHint: workflow.organHint ?? null,
                  previewConfirmed: true,
                });
                return;
              }

              // user chose "Keep Refining": stay in 2D, clear invalid prompt from this slice
              workflow.promptFrames = workflow.promptFrames.filter(
                frame => frame.slice_idx !== sliceIdx
              );
              uiNotificationService.show({
                title: '2D Preview',
                message: 'Continue refining this slice. Re-run Preview when ready.',
                type: 'info',
                duration: 5000,
              });
              return;
            }

            // 旧 HP 自动切换已删除——改为由 segment3DSAM2 流程中的 addMeshTo3DViewport 负责
            return; // 不弹模态框
          }

          console.warn('[SAM] RLE received but no writable labelmap target found on this viewport');
          uiNotificationService.show({
            title: 'Preview Warning',
            message: 'Segmentation result was returned, but no writable labelmap was found on this viewport.',
            type: 'warning',
            duration: 6000,
          });
        } catch (labelmapErr) {
          console.warn('[SAM] labelmap 写入失败，降级到预览模态框:', labelmapErr);
        }
      }
      // ─── 降级路径：显示 PNG 预览模态框（原有逻辑）──────────────────────────────

      if (reviewMode && !rleData) {
        if (organHint) {
          workflow.organHint = organHint;
        }
        workflow.previewAccepted = false;

        if (selectedImageSpaceBBox) {
          upsertPromptFrame(activeViewportId, {
            slice_idx: currentSliceIdx,
            bbox: selectedImageSpaceBBox,
            points: promptType === 'mask' ? selectedMaskPromptPoints : undefined,
            labels: promptType === 'mask' ? selectedMaskPromptLabels : undefined,
          });
        }
        uiNotificationService.show({
          title: 'Preview Image Only',
          message: 'No writable RLE mask returned. Refine prompt and preview again, then start 3D tracking after 2D mask appears.',
          type: 'warning',
          duration: 6000,
        });
      }

      if (uiModalService) {
        uiModalService.show({
          content: CornerstoneSamAndUnsamForm,
          title: 'Upload Segmentation Image to MedSAM Model',
          contentProps: {
            activeViewportId,
            cornerstoneViewportService,
            samImageUrl,
          },
          containerClassName: 'min-w-[1150px] p-4',
        });

       // === Endpoint: The first frame of the result has been rendered successfully ===
        requestAnimationFrame(() => {
          if (t_prompt_selected != null) {
            const t_rendered = performance.now() / 1000;
            const promptToRendered = t_rendered - t_prompt_selected;
            console.log(`[Latency][Frontend] Prompt→Rendered = ${fmt(promptToRendered)} s`);
          }
        });
      }
    },


    autoSegmentLiver: async () => {
      const { activeViewportId } = viewportGridService.getState();

      const csViewport = cornerstoneViewportService.getCornerstoneViewport(activeViewportId);

      if (!csViewport) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'Image cannot be uploaded',
          type: 'error',
        });
        return;
      }

      const { uiModalService } = servicesManager.services;
      const fmt = (s: number) => s.toFixed(2);

      // Statistics: Select LIVER → Render completed
      let t_prompt_selected: number | null = null;

      const organ = await new Promise<'liver' | 'spleen' | 'kidney' | 'lung_l' | 'lung_r' | '__tumor__' | '__tumor_mask__' | '__sam2_3d__' | null>(resolve => {
        if (!uiModalService) return resolve(null);

        const organs = [
          { key: 'liver',   label: 'Liver' },
          { key: 'spleen',  label: 'Spleen' },
          { key: 'kidney',  label: 'Kidney' },
          { key: 'lung_l',  label: 'Lung (L)' },
          { key: 'lung_r',  label: 'Lung (R)' },
        ];

        const OrganSelector = () => {
          return React.createElement(
            'div',
            { style: { padding: 20, color: '#e0e0e0', minWidth: 320 } },
            React.createElement('p', { style: { marginBottom: 12, fontSize: 13, color: '#aaa' } }, 'Select an organ for automatic segmentation:'),
            React.createElement(
              'div',
              { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 } },
              ...organs.map(o =>
                React.createElement(
                  'button',
                  {
                    key: o.key,
                    onClick: () => {
                      organHintByViewport.set(activeViewportId, o.key);
                      const lesionState = getLesionWorkflow(activeViewportId);
                      lesionState.organHint = o.key;
                      lesionState.promptFrames = [];
                      lesionState.previewAccepted = false;
                      t_prompt_selected = performance.now() / 1000;
                      resolve(o.key as any);
                      uiModalService.hide(modalId);
                    },
                    className: 'bg-blue-700 hover:bg-blue-600 text-white font-medium py-2 px-3 rounded text-sm',
                  },
                  o.label
                )
              )
            ),
            React.createElement('hr', { style: { borderColor: '#333', marginBottom: 10 } }),
            React.createElement(
              'div',
              { style: { background: '#1a2a3a', borderRadius: 4, padding: '10px 12px', fontSize: 12, lineHeight: 1.6, marginBottom: 8 } },
              React.createElement('div', { style: { fontWeight: 600, marginBottom: 4, color: '#ccc' } }, 'Lesion / Tumor Segmentation'),
              React.createElement('div', { style: { color: '#888', marginBottom: 8 } }, 'Use Rectangle or Brush on the current slice, then click Preview Current Slice.'),
              React.createElement(
                'button',
                {
                  onClick: () => { resolve('__tumor__'); uiModalService.hide(modalId); },
                  className: 'bg-orange-700 hover:bg-orange-600 text-white font-medium py-1 px-3 rounded text-sm',
                },
                'Preview Current Slice'
              )
            ),
            React.createElement(
              'div',
              { style: { background: '#1a2a1a', borderRadius: 4, padding: '10px 12px', fontSize: 12, lineHeight: 1.6 } },
              React.createElement('div', { style: { fontWeight: 600, marginBottom: 4, color: '#ccc' } }, '3D Series Tracking (SAM-2)'),
              React.createElement('div', { style: { color: '#888', marginBottom: 8 } }, 'Draw a rectangle on any slice, then run 3D tracking across the full series. Requires medsam2_service.py (port 8003).'),
              React.createElement(
                'button',
                {
                  onClick: () => { resolve('__sam2_3d__' as any); uiModalService.hide(modalId); },
                  className: 'bg-green-800 hover:bg-green-700 text-white font-medium py-1 px-4 rounded text-sm',
                },
                'Start 3D Tracking'
              )
            )
          );
        };

        const modalId = uiModalService.show({
          title: 'Auto Segment',
          content: OrganSelector,
          containerClassName: 'min-w-[340px] p-4',
          isDraggable: true,
        });
      });


      if (!organ) return;

      // 肿瘤模式：直接触发 SAMApply 流程（使用已画的 RectangleROI）
      if (organ === '__tumor__') {
        const lesionState = getLesionWorkflow(activeViewportId);
        let promptType: 'rectangle' | 'mask' = 'rectangle';
        let hasBrushMaskPrompt = false;

        try {
          const currentSliceIdx = (csViewport as any).getCurrentImageIdIndex?.() ?? 0;
          const allAnnotations = annotation.state.getAllAnnotations?.() ?? [];
          const hasRectanglePrompt = allAnnotations.some((ann: any) =>
            ['RectangleROI', 'Rectangle', 'RectangleScissor'].includes(ann?.metadata?.toolName) &&
            Array.isArray(ann?.data?.handles?.points) &&
            ann.data.handles.points.length >= 2
          );

          // ── labelmap 有数据 → 提取 bbox → mask 模式 ──
          // 刷子涂抹的 labelmap 数据用作 SAM 的 mask prompt
          hasBrushMaskPrompt = Boolean(
            await _getActiveSegmentationSliceBBox(activeViewportId, currentSliceIdx)
          );

          if (hasBrushMaskPrompt) {
            // 刷子涂抹 → mask 模式：labelmap 数据作为 mask prompt 发给 SAM
            promptType = 'mask';
          } else {
            uiNotificationService.show({
              title: 'Preview Current Slice',
              message: 'Draw a rectangle or paint with brush on current slice before preview.',
              type: 'warning',
              duration: 5000,
            });
            return;
          }
        } catch (promptDetectErr) {
          console.warn('[SAM] failed to detect prompt type, fallback to rectangle:', promptDetectErr);
        }

        // 自动推断：大面积→器官模式加裁剪，小面积→肿瘤模式不加裁剪
        let autoOrganHint = lesionState.organHint ?? organHintByViewport.get(activeViewportId) ?? null;
        if (!autoOrganHint && hasBrushMaskPrompt) {
          try {
            const bbox = await _getActiveSegmentationSliceBBox(activeViewportId, currentSliceIdx);
            if (bbox) {
              const area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]);
              const ratio = area / (512 * 512);
              if (ratio > 0.10) {
                const cx = (bbox[0] + bbox[2]) / 2, cy = (bbox[1] + bbox[3]) / 2;
                if (cx > 256 && cy < 205) autoOrganHint = 'lung_l';
                else if (cx < 256 && cy < 205) autoOrganHint = 'lung_r';
                else if (cx > 256 && cy > 256) autoOrganHint = 'liver';
                else if (cx < 204 && cy > 205) autoOrganHint = 'spleen';
                if (autoOrganHint) console.log(`[SAM] organ mode: ${autoOrganHint} (${(ratio*100).toFixed(1)}%)`);
              } else {
                console.log(`[SAM] tumor mode: no clipping (${(ratio*100).toFixed(1)}%)`);
              }
            }
          } catch {}
        }

        await actions.showSAMUploadModal({
          promptType,
          reviewMode: true,
          organHint: autoOrganHint,
        });
        return;
      }

      if (organ === '__tumor_mask__') {
        const lesionState = getLesionWorkflow(activeViewportId);
        await actions.showSAMUploadModal({
          promptType: 'mask',
          reviewMode: true,
          organHint: lesionState.organHint ?? organHintByViewport.get(activeViewportId) ?? null,
        });
        return;
      }

      // 3D SAM-2 全序列追踪
      if ((organ as string) === '__sam2_3d__') {
        const lesionState = getLesionWorkflow(activeViewportId);
        const canStart3D = lesionState.promptFrames.length > 0;
        if (!canStart3D) {
          uiNotificationService.show({
            title: 'Start 3D Tracking',
            message: 'Please click "Preview Current Slice" first to generate a 2D mask before 3D tracking.',
            type: 'warning',
            duration: 6000,
          });
          return;
        }

        const shouldStart = await new Promise<boolean>(resolve => {
          if (!uiModalService) {
            resolve(true);
            return;
          }

          const ConfirmStart3DContent = () =>
            React.createElement(
              'div',
              { style: { padding: 18, minWidth: 380, color: '#e5e7eb' } },
              React.createElement('div', { style: { fontSize: 15, marginBottom: 8 } }, '2D preview is ready.'),
              React.createElement(
                'div',
                { style: { fontSize: 12, color: '#9ca3af', marginBottom: 14, lineHeight: 1.6 } },
                'Confirm to start SAM2 3D tracking. You can cancel now and keep refining this slice first.'
              ),
              React.createElement(
                'div',
                { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
                React.createElement(
                  'button',
                  {
                    className: 'bg-slate-600 hover:bg-slate-500 text-white font-medium py-1 px-3 rounded text-sm',
                    onClick: () => {
                      (csViewport as any).render?.();
                      requestAnimationFrame(() => {
                        requestAnimationFrame(() => {
                          const vpEl = (csViewport as any).element as HTMLElement;
                          const c = vpEl?.querySelector('canvas') as HTMLCanvasElement;
                          if (c) { lesionState.last2DScreenshot = c.toDataURL('image/png'); alert('2D Screenshot captured (' + (lesionState.last2DScreenshot?.length||0) + ' chars). Will be included in your report.'); }
                          else alert('No canvas found');
                        });
                      });
                    },
                  },
                  '📸 Screenshot'
                ),
                React.createElement(
                  'button',
                  {
                    className: 'bg-green-700 hover:bg-green-600 text-white font-medium py-1 px-3 rounded text-sm',
                    onClick: () => {
                      uiModalService.hide(confirm3DModalId);
                      resolve(true);
                    },
                  },
                  'Confirm and Start 3D Tracking'
                ),
                React.createElement(
                  'button',
                  {
                    className: 'bg-slate-700 hover:bg-slate-600 text-white font-medium py-1 px-3 rounded text-sm',
                    onClick: () => {
                      uiModalService.hide(confirm3DModalId);
                      resolve(false);
                    },
                  },
                  'Cancel and Keep Refining'
                )
              )
            );

          const confirm3DModalId = uiModalService.show({
            title: 'Confirm 3D Tracking',
            content: ConfirmStart3DContent,
            containerClassName: 'min-w-[400px] p-4',
            isDraggable: true,
          });
        });

        if (!shouldStart) {
          return;
        }

        await actions.segment3DSAM2({
          promptFrames: lesionState.promptFrames,
          organHint: lesionState.organHint ?? null,
          previewConfirmed: true,
        });
        return;
      }

      let loadingModalId = null;
      if (uiModalService) {
        loadingModalId = uiModalService.show({
          title: '',
          content: () =>
            React.createElement(
              'div',
              { style: { padding: 32, textAlign: 'center', color: '#fff' } },
              'Processing image, please wait...'
            ),
          containerClassName: 'min-w-[300px] p-4',
        });
      }

      const divForUpload = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`);
      if (!divForUpload) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'No viewport found for upload',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      const fileType = 'png';
      const canvas = await html2canvas(divForUpload as HTMLElement);
      const blob: Blob = await new Promise(resolve => canvas.toBlob(resolve, `image/${fileType}`, 1.0));

      const formData = new FormData();
      formData.append('file', blob, `image.${fileType}`);
      formData.append('organ', organ);
      let samImageUrl = '';
      let rleData = null;
      try {
        const useLite = await isLiteMedSAMAvailable();
        const candidatePorts = useLite ? [8002, 8000] : [8000];
        let lastError: Error | null = null;

        let sopInstanceUID = '';
        try {
          const currentImageId = (csViewport as any).getCurrentImageId?.();
          if (currentImageId) {
            const match = currentImageId.match(/\/instances\/([^\/]+)\//i);
            if (match) {
              sopInstanceUID = match[1];
            }
          }
        } catch { /* ignore */ }

        if (useLite && sopInstanceUID) {
          try {
            const dicomResp = await fetch('http://localhost:8002/auto_organ_dicom', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ sop_instance_uid: sopInstanceUID, organ }),
            });
            if (dicomResp.ok) {
              const dicomData = await dicomResp.json();
              if (dicomData.success) {
                rleData = dicomData.rle;
                samImageUrl = dicomData.image_url ? `http://localhost:8002${dicomData.image_url}` : '';
                console.log(`[Auto Segment] Used /auto_organ_dicom for ${organ}`);
              }
            }
          } catch { /* fall back below */ }
        }

        if (!rleData) {
          for (const port of candidatePorts) {
            try {
              const resp = await fetch(`http://localhost:${port}/auto_liver`, {
                method: 'POST',
                body: formData,
              });
              if (!resp.ok) {
                throw new Error(`Auto segment HTTP ${resp.status}`);
              }
              const data = await resp.json();
              if (!data.success) {
                throw new Error(data.error || 'Auto segment failed');
              }
              samImageUrl = `http://localhost:${port}${data.image_url}`;
              if (data.rle) {
                rleData = data.rle;
              }
              console.log(`[Auto Segment] Used backend port ${port} for organ ${organ}`);
              lastError = null;
              break;
            } catch (portErr) {
              lastError = portErr as Error;
            }
          }
        }

        if (!rleData && lastError) {
          throw lastError;
        }
      } catch (e) {
        uiNotificationService.show({
          title: 'Auto Segment Error',
          message: String((e as Error)?.message || e || 'Auto segment failed'),
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);

      if (rleData) {
        try {
          const { cache: csCache } = await import('@cornerstonejs/core');
          const { segmentation: csSeg } = await import('@cornerstonejs/tools');

          const { segmentationId, segmentIndex } = await _ensureActiveSegmentation();
          const segObj = csSeg.state.getSegmentation(segmentationId);
          const labelmapData = segObj?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
          const volumeId = labelmapData?.volumeId;
          const labelmapVolume = volumeId ? csCache.getVolume(volumeId) : null;

          if (labelmapVolume) {
            const { counts, starts_with: startsVal, width: rleW, height: rleH } = rleData;
            const total = rleW * rleH;
            const maskFlat = new Uint8Array(total);
            let idx = 0;
            let curVal = startsVal;
            for (const cnt of counts) {
              if (curVal === 1) maskFlat.fill(1, idx, idx + cnt);
              idx += cnt;
              curVal = curVal === 0 ? 1 : 0;
            }

            let sliceIdx = 0;
            const vpObj = cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as StackViewport;
            if (typeof (vpObj as any)?.getCurrentImageIdIndex === 'function') {
              sliceIdx = (vpObj as any).getCurrentImageIdIndex();
            }

            const { dimensions } = labelmapVolume;
            const [cols, rows] = dimensions;
            const scalarData = labelmapVolume.getScalarData() as Uint8Array;
            const sliceOffset = sliceIdx * cols * rows;

            if (rleW === cols && rleH === rows) {
              for (let i = 0; i < total; i++) {
                if (maskFlat[i] > 0) scalarData[sliceOffset + i] = segmentIndex;
              }
            } else {
              const scaleX = rleW / cols;
              const scaleY = rleH / rows;
              for (let row = 0; row < rows; row++) {
                for (let col = 0; col < cols; col++) {
                  const srcX = Math.min(Math.round(col * scaleX), rleW - 1);
                  const srcY = Math.min(Math.round(row * scaleY), rleH - 1);
                  if (maskFlat[srcY * rleW + srcX] > 0) {
                    scalarData[sliceOffset + row * cols + col] = segmentIndex;
                  }
                }
              }
            }

            (segmentationUtils as any).triggerSegmentationModified?.(segmentationId);
            (cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any)?.render?.();

            requestAnimationFrame(() => {
              if (t_prompt_selected != null) {
                const t_rendered = performance.now() / 1000;
                const promptToRendered = t_rendered - t_prompt_selected;
                console.log(`[Latency][Frontend] Prompt→Labelmap = ${fmt(promptToRendered)} s`);
              }
            });

            uiNotificationService.show({
              title: 'Auto Segment',
              message: `自动分割完成 (${organ})，结果已写入当前分割层。可点 Start 3D Tracking 进行 3D 传播。`,
              type: 'success',
              duration: 6000,
            });
            // 保存 organ hint 用于后续 3D
            const ls = getLesionWorkflow(activeViewportId);
            ls.organHint = organ;
            // 提取 bbox 写入 promptFrames
            try {
              const bbox = await _getActiveSegmentationSliceBBox(activeViewportId, 0);
              if (bbox) upsertPromptFrame(activeViewportId, { slice_idx: 0, bbox });
            } catch {}
            return;
          }
        } catch (labelmapErr) {
          console.warn('[Auto Segment] labelmap 写入失败，降级到预览模态框:', labelmapErr);
        }
      }

      // 所有后端均失败 — 显示清晰错误而非旧上传弹窗
      uiNotificationService.show({
        title: 'Auto Segment Failed',
        message: `器官自动分割失败（${organ}）。请确认 Orthanc (localhost:8042) 已启动且目标器官在当前切片可见。`,
        type: 'error',
        duration: 8000,
      });
    },

    // ─── 预加载当前系列所有切片的 SAM Embedding 到后端缓存 ──────────────────
    // ─── P2: MedSAM-2 3D 全序列追踪 ────────────────────────────────────────────
    segment3DSAM2: async (options: {
      promptFrames?: LesionPromptFrame[];
      organHint?: string | null;
      previewConfirmed?: boolean;
    } = {}) => {
      const { activeViewportId } = viewportGridService.getState();
      const csViewport = cornerstoneViewportService.getCornerstoneViewport(activeViewportId);
      const { uiModalService } = servicesManager.services;
      const lesionState = getLesionWorkflow(activeViewportId);
      const promptFrames = Array.isArray(options.promptFrames) && options.promptFrames.length
        ? options.promptFrames
        : lesionState.promptFrames;
      const organHint = options.organHint ?? lesionState.organHint ?? organHintByViewport.get(activeViewportId) ?? null;

      if (!csViewport) {
        uiNotificationService.show({ title: '3D SAM2', message: 'No active viewport', type: 'error' });
        return;
      }

      // 1. Get SeriesInstanceUID from displaySet
      const { viewports: _vps } = viewportGridService.getState();
      const _vpEntry = _vps.get(activeViewportId);
      const _dsUID = _vpEntry?.displaySetInstanceUIDs?.[0];
      const _ds = _dsUID ? displaySetService.getDisplaySetByUID(_dsUID) : null;
      const seriesInstanceUID = (_ds as any)?.SeriesInstanceUID;
      if (!seriesInstanceUID) {
        uiNotificationService.show({ title: '3D SAM2', message: 'Cannot find SeriesInstanceUID — load DICOM from Orthanc', type: 'error' });
        return;
      }

      // 2. Current slice index
      let keySliceIdx = 0;
      let imageIds3d: string[] = [];
      try {
        imageIds3d = (csViewport as any).getImageIds?.() ?? [];

        if (typeof (csViewport as any).getCurrentImageIdIndex === 'function') {
          const currentIdx = (csViewport as any).getCurrentImageIdIndex();
          if (typeof currentIdx === 'number' && currentIdx >= 0) {
            keySliceIdx = currentIdx;
          }
        } else {
          const curId = (csViewport as any).getCurrentImageId?.();
          const idx = imageIds3d.indexOf(curId);
          if (idx >= 0) keySliceIdx = idx;
        }
      } catch { /* ignore */ }

      let seededBBoxFromPrompt: [number, number, number, number] | null = null;
      if (promptFrames.length > 0) {
        const seedFrame = promptFrames[promptFrames.length - 1];
        console.log('[3D SAM2] seedFrame:', { slice_idx: seedFrame.slice_idx, hasBbox: !!seedFrame.bbox?.length, hasMaskRle: !!seedFrame.mask_rle, hasPoints: !!seedFrame.points?.length });
        if (typeof seedFrame.slice_idx === 'number') {
          keySliceIdx = seedFrame.slice_idx;
        }
        if (seedFrame.bbox?.length === 4) {
          seededBBoxFromPrompt = seedFrame.bbox;
        }
      }

      console.log('[3D SAM2] resolved keySliceIdx:', keySliceIdx, 'promptFrames count:', promptFrames.length);

      // 3. Extract bbox from the most recent RectangleROI annotation.
      // If there is no live rectangle annotation, fall back to the current
      // slice's active segmentation mask bounding box so RectangleScissor /
      // labelmap-based workflows can still launch SAM-2 tracking.
      let bboxCoords: [number, number, number, number] | null = seededBBoxFromPrompt;
      try {
        const imgData3d = (csViewport as any).getImageData?.();
        const imgW = imgData3d?.dimensions?.[0] ?? 512;
        const imgH = imgData3d?.dimensions?.[1] ?? 512;
        const divEl3d = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`) as HTMLElement;
        const allAnns = annotation.state.getAllAnnotations();
        const rectAnns = allAnns.filter(a =>
          ['RectangleROI', 'Rectangle', 'RectangleScissor'].includes(a.metadata?.toolName) &&
          a.data?.handles?.points?.length >= 2
        );
        if (rectAnns.length > 0) {
          const ann3d = rectAnns[rectAnns.length - 1];
          // ── 修复：直接用 image origin+spacing 做 world→pixel 转换（避免canvas偏移bug）──
          let originX = 0, originY = 0, spacingCol = 1, spacingRow = 1;
          if (imgData3d?.origin && imgData3d?.spacing) {
            originX = imgData3d.origin[0] ?? 0;
            originY = imgData3d.origin[1] ?? 0;
            spacingCol = (imgData3d.spacing[1] ?? imgData3d.spacing[0] ?? 1);
            spacingRow = (imgData3d.spacing[0] ?? 1);
          }
          const imgPts3d = ann3d.data.handles.points.map((pt: any) => [
            Math.round((pt[0] - originX) / Math.max(1e-6, spacingCol)),
            Math.round((pt[1] - originY) / Math.max(1e-6, spacingRow)),
          ]);
          const ix3d = imgPts3d.map((p: number[]) => p[0]);
          const iy3d = imgPts3d.map((p: number[]) => p[1]);
          const bx1 = Math.min(...ix3d), by1 = Math.min(...iy3d);
          const bx2 = Math.max(...ix3d), by2 = Math.max(...iy3d);
          if (bx2 > bx1 && by2 > by1) bboxCoords = [bx1, by1, bx2, by2];
          console.log('[3D SAM2] world→pixel bbox:', bboxCoords);
        }

        if (!bboxCoords) {
          try {
            const activeSegmentation = segmentationService.getActiveSegmentation(activeViewportId);
            if (activeSegmentation?.segmentationId) {
              const { cache: csCache3d } = await import('@cornerstonejs/core');
              const { segmentation: csSeg3d } = await import('@cornerstonejs/tools');
              const segObj3d = csSeg3d.state.getSegmentation(activeSegmentation.segmentationId);
              const labelmapData3d = segObj3d?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
              const volumeId3d = labelmapData3d?.volumeId;
              const stackImageIds3d = (labelmapData3d as any)?.imageIds as string[] | undefined;
              const labelmapVolume3d = volumeId3d ? csCache3d.getVolume(volumeId3d) : null;

              if (labelmapVolume3d) {
                const { dimensions: dims3d } = labelmapVolume3d;
                const [cols3d, rows3d] = dims3d;
                const scalarData3d = labelmapVolume3d.getScalarData() as Uint8Array;
                const sliceOffset3d = keySliceIdx * cols3d * rows3d;

                let minCol = cols3d;
                let minRow = rows3d;
                let maxCol = -1;
                let maxRow = -1;

                for (let row = 0; row < rows3d; row++) {
                  for (let col = 0; col < cols3d; col++) {
                    if (scalarData3d[sliceOffset3d + row * cols3d + col] > 0) {
                      if (col < minCol) minCol = col;
                      if (row < minRow) minRow = row;
                      if (col > maxCol) maxCol = col;
                      if (row > maxRow) maxRow = row;
                    }
                  }
                }

                if (maxCol >= minCol && maxRow >= minRow) {
                  bboxCoords = [minCol, minRow, maxCol + 1, maxRow + 1];
                  console.log('[3D SAM2] Using active segmentation bbox fallback (volume):', bboxCoords);
                }
              } else if (stackImageIds3d && stackImageIds3d.length > keySliceIdx) {
                // stack-based segmentation: read per-slice labelmap image
                const sliceLabelmapImgId = stackImageIds3d[keySliceIdx];
                const sliceLabelmapImg = sliceLabelmapImgId ? (csCache3d as any).getImage(sliceLabelmapImgId) : null;
                if (sliceLabelmapImg) {
                  const pixels = sliceLabelmapImg.getPixelData?.() ?? [];
                  const imgWidth = sliceLabelmapImg.width ?? 512;
                  const imgHeight = sliceLabelmapImg.height ?? 512;
                  let minCol = imgWidth, minRow = imgHeight, maxCol = -1, maxRow = -1;
                  for (let row = 0; row < imgHeight; row++) {
                    for (let col = 0; col < imgWidth; col++) {
                      if (pixels[row * imgWidth + col] > 0) {
                        if (col < minCol) minCol = col;
                        if (row < minRow) minRow = row;
                        if (col > maxCol) maxCol = col;
                        if (row > maxRow) maxRow = row;
                      }
                    }
                  }
                  if (maxCol >= minCol && maxRow >= minRow) {
                    bboxCoords = [minCol, minRow, maxCol + 1, maxRow + 1];
                    console.log('[3D SAM2] Using active segmentation bbox fallback (stack):', bboxCoords);
                  }
                }
              }
            }
          } catch (fallbackErr) {
            console.warn('[3D SAM2] segmentation bbox fallback error:', fallbackErr);
          }
        }
      } catch (e) { console.warn('[3D SAM2] bbox extraction error:', e); }

      if (!bboxCoords) {
        uiNotificationService.show({
          title: '3D SAM2',
          message: 'Please draw a rectangle, or create a visible segmentation on the current slice, then start 3D tracking',
          type: 'warning',
        });
        return;
      }

      // 4. Loading modal — 直接 textContent 更新，避免闪烁
      let loadingId3d: any = null;
      let loadingMsgEl: HTMLElement | null = null;
      let loadingSubEl: HTMLElement | null = null;
      const showLoad3d = (msg: string, sub?: string) => {
        if (loadingMsgEl && loadingMsgEl.isConnected) {
          loadingMsgEl.textContent = msg;
          if (loadingSubEl) loadingSubEl.textContent = sub || '';
          return;
        }
        // 重新创建 modal
        if (loadingId3d && uiModalService) uiModalService.hide(loadingId3d);
        loadingMsgEl = null; loadingSubEl = null;
        if (uiModalService) {
          loadingId3d = uiModalService.show({
            title: '',
            content: () => React.createElement('div',
              { style: { padding: 32, textAlign: 'center', color: '#fff', minWidth: 320 } },
              React.createElement('div', { style: { fontSize: 16, marginBottom: 8 }, ref: (el: any) => { loadingMsgEl = el; } }, msg),
              sub ? React.createElement('div', { style: { fontSize: 12, color: '#aaa' }, ref: (el: any) => { loadingSubEl = el; } }, sub) : null
            ),
            containerClassName: 'min-w-[320px] p-4',
          });
        }
      };

      let sessionId3d: string | null = null;
      try {
        // ── 预检测：视口是否有图像数据（等效于 Orthanc 可连接）──
        const csVp3d = cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any;
        const hasImageData = !!(csVp3d?.getImageData?.() || csVp3d?.getCurrentImageId?.());
        if (!hasImageData) {
          if (loadingId3d && uiModalService) { uiModalService.hide(loadingId3d); loadingId3d = null; }
          uiNotificationService.show({
            title: '无图像数据',
            message: '视口未加载 DICOM 图像。请确认 Orthanc (localhost:8042) 已启动并刷新页面。',
            type: 'error',
            duration: 9000,
          });
          return;
        }

        let backendDevice = 'cpu';
        try {
          const healthResp = await fetch('http://localhost:8003/health', { signal: AbortSignal.timeout(3000) });
          const healthData = await healthResp.json();
          backendDevice = healthData.device ?? 'cpu';
        } catch { /* ignore */ }

        const deviceNote = backendDevice === 'cpu'
          ? '⚠️ MedSAM2 running on CPU — 240 slices may take 2–5 minutes.'
          : '✅ GPU detected — should finish in 20–40s.';

        // 5. Create SAM2 session (downloads all slices from Orthanc, ~30-60s)
        showLoad3d('Loading CT series...', `${imageIds3d.length} slices | ${deviceNote}`);
        const createResp = await fetch('http://localhost:8003/session/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            series_instance_uid: seriesInstanceUID,
            organ_hint: organHint,
            prompt_frames: promptFrames,
          }),
        });
        if (!createResp.ok) throw new Error(`Session create HTTP ${createResp.status}: ${await createResp.text()}`);
        const createData = await createResp.json();
        if (!createData.success) throw new Error(createData.detail ?? 'Session creation failed');
        sessionId3d = createData.session_id;

        // 6. Run 3D propagation with real-time progress polling
        let lastProgress = `Slice 0 / ${createData.slice_count} — forward`;
        showLoad3d('SAM-2 3D tracking...', lastProgress);

        // 启动进度轮询（连续 3 次 404 自动停止）
        let pollTimer: any = null;
        let pollActive = true;
        let notFoundCount = 0;
        pollTimer = setInterval(async () => {
          if (!pollActive) return;
          try {
            const progResp = await fetch(`http://localhost:8003/session/${sessionId3d}/progress`);
            if (!progResp.ok) {
              if (progResp.status === 404) {
                notFoundCount++;
                if (notFoundCount >= 3) {
                  pollActive = false;
                  clearInterval(pollTimer);
                }
              }
              return;
            }
            notFoundCount = 0; // reset on success
            const prog = await progResp.json();
            if (prog && typeof prog.current === 'number') {
              const phaseMap: Record<string, string> = { forward: 'forward', reverse: 'reverse', encoding: 'encoding RLE', done: 'done' };
              const phaseLabel = phaseMap[prog.phase] || prog.phase || 'working';
              lastProgress = `Slice ${prog.current} / ${prog.total} — ${phaseLabel}`;
              showLoad3d('SAM-2 3D tracking...', lastProgress);
              if (prog.phase === 'done') {
                pollActive = false;
                clearInterval(pollTimer);
              }
            }
          } catch { /* ignore poll errors */ }
        }, 1500);

        let segResp: Response;
        try {
          segResp = await fetch(`http://localhost:8003/session/${sessionId3d}/segment`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              key_slice_idx: keySliceIdx,
              bbox: bboxCoords,
              organ_hint: organHint,
              prompt_frames: promptFrames,
              preview_confirmed: Boolean(options.previewConfirmed),
            }),
          });
        } finally {
          // 停止轮询
          pollActive = false;
          if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        }

        if (!segResp.ok) {
          const errText = await segResp.text().catch(() => '');
          throw new Error(`Segment HTTP ${segResp.status}${errText ? ': ' + errText.slice(0, 200) : ''}`);
        }
        const segData = await segResp.json();
        if (!segData.success) throw new Error(segData.detail ?? '3D segmentation failed');

        // ── always close the loading modal first ──────────────────────────
        if (loadingId3d && uiModalService) { uiModalService.hide(loadingId3d); loadingId3d = null; loadingMsgEl = null; loadingSubEl = null; }

        // 7. Write all slice masks into the labelmap
        const { segmentationId: segId3d, segmentIndex: segIdx3d } = await _ensureActiveSegmentation();
        lesionState.lastSegmentationId = segId3d; // 保存以供后续 3D 叠加使用
        const { cache: csCache3d } = await import('@cornerstonejs/core');
        const { segmentation: csSeg3d } = await import('@cornerstonejs/tools');
        const segObj3d = csSeg3d.state.getSegmentation(segId3d);
        const lmData3d = segObj3d?.representationData?.[Enums.SegmentationRepresentations.Labelmap];
        const lmVolume3d = lmData3d?.volumeId ? csCache3d.getVolume(lmData3d.volumeId) : null;
        const stackImageIds3d = (lmData3d as any)?.imageIds as string[] | undefined;
        const representationType3d = lmVolume3d || stackImageIds3d?.length ? 'Labelmap' : 'None';

        let slicesWritten3d = 0;
        let masksAttempted3d = 0;

        const _decodeRle = (rle: any, segIndex: number, targetPixels: any, targetW: number, targetH: number) => {
          const { counts, starts_with, width: rleW, height: rleH } = rle;
          const total = rleW * rleH;
          const mask = new Uint8Array(total);
          let fi = 0, cv = starts_with;
          let writtenCount = 0;
          for (const cnt of counts) {
            if (cv === 1) mask.fill(1, fi, fi + cnt);
            fi += cnt; cv = cv === 0 ? 1 : 0;
          }
          if (rleW === targetW && rleH === targetH) {
            for (let i = 0; i < total; i++) {
              if (mask[i] > 0) {
                targetPixels[i] = segIndex;
                writtenCount++;
              }
            }
          } else {
            const sX = rleW / targetW, sY = rleH / targetH;
            for (let r = 0; r < targetH; r++) {
              for (let c = 0; c < targetW; c++) {
                const sx = Math.min(Math.round(c * sX), rleW - 1);
                const sy = Math.min(Math.round(r * sY), rleH - 1);
                if (mask[sy * rleW + sx] > 0) {
                  targetPixels[r * targetW + c] = segIndex;
                  writtenCount++;
                }
              }
            }
          }
          return writtenCount;
        };

        const masksPerSlice = Array.isArray(segData.masks_per_slice) ? segData.masks_per_slice : [];
        const resolveSliceIndex = (sliceIdx: number, totalSlices: number) => {
          if (sliceIdx >= 0 && sliceIdx < totalSlices) {
            return sliceIdx;
          }
          const reverseIdx = totalSlices - 1 - sliceIdx;
          if (reverseIdx >= 0 && reverseIdx < totalSlices) {
            return reverseIdx;
          }
          return -1;
        };

        console.log('[3D SAM2] write-back start', {
          masksReturned: masksPerSlice.length,
          imageIdsInViewport: imageIds3d.length,
          hasVolumeLabelmap: Boolean(lmVolume3d),
          hasStackLabelmap: Boolean(stackImageIds3d?.length),
        });

        if (lmVolume3d) {
          // ── Volume segmentation path ─────────────────────────────────────
          const { dimensions: dims3d } = lmVolume3d;
          const [cols3d, rows3d, slices3d] = dims3d;
          const scalarData3d = lmVolume3d.getScalarData() as Uint8Array;
          const totalSlices3d = typeof slices3d === 'number' && slices3d > 0
            ? slices3d
            : Math.floor(scalarData3d.length / (cols3d * rows3d));

          for (const { slice_idx, rle } of masksPerSlice) {
            masksAttempted3d++;
            const resolvedSliceIdx = resolveSliceIndex(slice_idx, totalSlices3d);
            if (resolvedSliceIdx < 0) {
              continue;
            }

            const sliceOff3d = resolvedSliceIdx * cols3d * rows3d;
            const targetSlice = scalarData3d.subarray(sliceOff3d, sliceOff3d + cols3d * rows3d);
            if (!targetSlice.length) {
              continue;
            }

            const written = _decodeRle(rle, segIdx3d, targetSlice, cols3d, rows3d);
            if (written > 0) {
              slicesWritten3d++;
            }
          }
          if (slicesWritten3d > 0) {
            (segmentationUtils as any).triggerSegmentationModified?.(segId3d);
            try {
              if ((lmVolume3d as any)?.vtkOpenGLTexture) {
                (lmVolume3d as any).vtkOpenGLTexture.modified();
              }
            } catch { /* ignore */ }
            const vp3d = cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any;
            vp3d?.render?.();
            setTimeout(() => vp3d?.render?.(), 200);
          }
        } else if (stackImageIds3d?.length) {
          // ── Stack segmentation path (SAM mode Stack Viewport) ────────────
          const totalSlices3d = stackImageIds3d.length;
          for (const { slice_idx, rle } of masksPerSlice) {
            masksAttempted3d++;
            const resolvedSliceIdx = resolveSliceIndex(slice_idx, totalSlices3d);
            if (resolvedSliceIdx < 0) {
              continue;
            }

            const sliceLabelmapImgId = stackImageIds3d[resolvedSliceIdx];
            if (!sliceLabelmapImgId) continue;
            const sliceImg = (csCache3d as any).getImage(sliceLabelmapImgId);
            if (!sliceImg) continue;
            const pixels = sliceImg.getPixelData?.();
            if (!pixels) continue;
            const written = _decodeRle(rle, segIdx3d, pixels, sliceImg.width ?? 512, sliceImg.height ?? 512);
            if (written > 0) {
              slicesWritten3d++;
            }
          }
          if (slicesWritten3d > 0) {
            (segmentationUtils as any).triggerSegmentationModified?.(segId3d);
            const vp3dStack = cornerstoneViewportService.getCornerstoneViewport(activeViewportId) as any;
            vp3dStack?.render?.();
            setTimeout(() => vp3dStack?.render?.(), 200);
          }
        }

        console.log('[3D SAM2] write-back result', {
          masksReturned: masksPerSlice.length,
          masksAttempted: masksAttempted3d,
          slicesWritten: slicesWritten3d,
          volumeMm3: segData.volume_mm3,
          representationType: representationType3d,
        });

        if (slicesWritten3d > 0) {
          upsertLesion3DStatusBar({
            viewportId: activeViewportId,
            returnedSlices: masksPerSlice.length,
            writtenSlices: slicesWritten3d,
            representationType: representationType3d,
            volumeMm3: typeof segData.volume_mm3 === 'number' ? segData.volume_mm3 : null,
            status: 'success',
          });

          lesionState.previewAccepted = true;
          lesionState.last3DVolumeMm3 = typeof segData.volume_mm3 === 'number' ? segData.volume_mm3 : null;
          lesionState.lastTrackedSlices = slicesWritten3d;
          lesionState.last3DMesh = segData.mesh ?? null;

          const volStr = typeof segData.volume_mm3 === 'number'
            ? `${(segData.volume_mm3 / 1000).toFixed(2)} cm³ (${segData.volume_mm3.toFixed(1)} mm³)`
            : 'N/A';

          // ── 3D 完成：自动切 3D Only 布局 + 绿色高亮 ──
          const show3DOverlay = async () => {
            try {
              const segId3d = lesionState.lastSegmentationId;
              if (!segId3d) { console.warn('[3D] no segmentationId'); return; }
              console.log('[3D] show3DOverlay start, segId:', segId3d);

              // ─── Step 1: 查找 3D hanging protocol（优先 mprAnd3DVolumeViewport / 3D only）───
              let threeDProtocolId = '';
              let threeDStageIdx = 0;
              try {
                // OHIF hanging protocol service 的内部协议 Map
                const protocols: any[] = Array.from(
                  (hangingProtocolService as any).protocols?.values?.() ?? []
                );
                console.log('[3D] available protocols count:', protocols.length);
                // 优先匹配：mprAnd3DVolumeViewport → 3D only → any 3d/volume
                const preferred = protocols.find((hp: any) => {
                  const name = (hp.name || hp.id || '').toLowerCase();
                  return hp.isPreset && (name.includes('mprand3d') || name.includes('3donly') || name.includes('3d only'));
                });
                const hp = preferred || protocols.find((hp: any) => {
                  const name = (hp.name || hp.id || '').toLowerCase();
                  return hp.isPreset && (name.includes('3d') || name.includes('only3d') || name.includes('volume'));
                });
                if (hp) {
                  threeDProtocolId = hp.id;
                  // 找第一个带 volume3d 视口的 stage
                  const stages = hp.stages || [];
                  for (let i = 0; i < stages.length; i++) {
                    const vps = stages[i]?.viewportStructure?.viewports || [];
                    const has3D = vps.some((v: any) => 
                      (v.viewportOptions?.viewportType || v.type || '').includes('volume3d')
                    );
                    if (has3D) { threeDStageIdx = i; break; }
                  }
                  console.log('[3D] matched:', hp.id, hp.name, 'stage:', threeDStageIdx);
                } else {
                  console.log('[3D] no 3D protocol found in preset protocols');
                }
              } catch(e) { console.warn('[3D] protocol search error:', e); }

              // ─── Step 2: 切换布局 + 等待 Volume 完全加载 ───
              if (threeDProtocolId) {
                console.log('[3D] switching to protocol:', threeDProtocolId, 'stage:', threeDStageIdx);
                await commandsManager.runCommand('setHangingProtocol', {
                  protocolId: threeDProtocolId,
                  stageIndex: threeDStageIdx,
                });
              } else {
                console.warn('[3D] no 3D protocol found, staying in 2D');
                const reps2d = segmentationService.getSegmentationRepresentations(activeViewportId, { segmentationId: segId3d });
                if (!reps2d?.length) {
                  await segmentationService.addSegmentationRepresentation(activeViewportId, {
                    segmentationId: segId3d,
                    type: Enums.SegmentationRepresentations.Labelmap,
                  });
                }
                segmentationService.setSegmentColor(activeViewportId, segId3d, 1, [34, 197, 94, 200]);
                return;
              }

              // ─── Step 3: 轮询等待 volume3d 视口 + CT Volume 都就绪 ───
              let volumeVpId = '';
              let csVp3d: any = null;
              // 先等视口出现
              for (let attempt = 0; attempt < 15; attempt++) {
                const vpMap = viewportGridService.getState().viewports as Map<string, any>;
                for (const [id, vp] of vpMap.entries()) {
                  const vpType = vp?.viewportOptions?.viewportType || '';
                  if (vpType === 'volume3d') {
                    volumeVpId = id;
                    csVp3d = cornerstoneViewportService.getCornerstoneViewport(id) as any;
                    break;
                  }
                }
                if (volumeVpId) break;
                await new Promise(r => setTimeout(r, 1000));
              }
              if (!volumeVpId || !csVp3d) {
                console.error('[3D] volume3d viewport never appeared');
                return;
              }
              console.log('[3D] found volume3d viewport:', volumeVpId);

              // ─── 修复 vtk 着色器崩溃 ───
              try {
                const volumeMapper = csVp3d?.getMapper?.();
                if (volumeMapper) {
                  volumeMapper.removeShaderDefine('vtkImageLabelOutlineOn');
                  volumeMapper.setUseLabelOutline(false);
                  volumeMapper.setLabelOutlineOpacity(0);
                  console.log('[3D] shader fix: removed vtkImageLabelOutlineOn');
                }
              } catch(e) { console.warn('[3D] mapper fix failed:', e); }

              // ─── Step 4: 获取 DICOM 空间参数（3D Volume → 2D image 兜底）───
              // ── Step 4: 提取 spacing ──
              let spacing: number[] = [1, 1, 1];
              const imgData2d = (csViewport as any).getImageData?.();
              if (imgData2d?.spacing?.length >= 2) {
                spacing[0] = Number(imgData2d.spacing[0]) || 1;
                spacing[1] = Number(imgData2d.spacing[1]) || 1;
              }

              // ── Z spacing：3 级兜底 ──
              // 1) stack 连续两帧 IPP[2] 差值
              if (stackImageIds3d?.length >= 2) {
                try {
                  const _getIpp = (img: any) => 
                    img?.imagePositionPatient || img?.data?.metadata?.ImagePositionPatient ||
                    img?.data?.metadata?.imagePositionPatient;
                  const img0 = (csCache3d as any).getImage(stackImageIds3d[0]);
                  const img1 = (csCache3d as any).getImage(stackImageIds3d[1]);
                  const ipp0 = _getIpp(img0), ipp1 = _getIpp(img1);
                  if (ipp0?.length >= 3 && ipp1?.length >= 3) {
                    const dz = Math.abs(Number(ipp1[2]) - Number(ipp0[2]));
                    if (dz > 0.01) { spacing[2] = dz; console.log('[3D] ✅ Z spacing from stack IPP diff:', dz.toFixed(4)); }
                  }
                } catch(e) {}
              }
              // 2) imgData2d.spacing[2] 如果合理
              if (spacing[2] <= 0.01 && imgData2d?.spacing?.[2] > 0.05) {
                spacing[2] = Number(imgData2d.spacing[2]);
              }
              // 3) 硬编码兜底
              if (spacing[2] <= 0.01) {
                spacing[2] = 3.0;
                console.warn('[3D] ⚠️ Z spacing forced to 3.0mm (all sources gave <0.01)');
              }

              console.log('[3D] spacing:', JSON.stringify(spacing.map(v=>Number(v).toFixed(4))), 'keySliceIdx=', keySliceIdx);

              // ── 取当前切片的 DICOM IPP + IOP ──
              let ippX = 0, ippY = 0, ippZ = 0;
              let iopRow = [1, 0, 0], iopCol = [0, -1, 0];  // 轴位 CT 默认
              if (imgData2d) {
                if (imgData2d.origin?.length >= 3) {
                  ippX = Number(imgData2d.origin[0]) || 0;
                  ippY = Number(imgData2d.origin[1]) || 0;
                  ippZ = Number(imgData2d.origin[2]) || 0;
                }
                if (imgData2d.direction?.length >= 6) {
                  iopRow = [Number(imgData2d.direction[0])||0, Number(imgData2d.direction[1])||0, Number(imgData2d.direction[2])||0];
                  iopCol = [Number(imgData2d.direction[3])||0, Number(imgData2d.direction[4])||0, Number(imgData2d.direction[5])||0];
                }
              }
              // IOP 法向量 = row × col
              const iopNrm = [
                iopRow[1]*iopCol[2] - iopRow[2]*iopCol[1],
                iopRow[2]*iopCol[0] - iopRow[0]*iopCol[2],
                iopRow[0]*iopCol[1] - iopRow[1]*iopCol[0],
              ];
              console.log('[3D] IPP:', ippX.toFixed(1), ippY.toFixed(1), ippZ.toFixed(1),
                'IOP row:', iopRow, 'col:', iopCol);

              // ─── Step 5: 标准 DICOM 像素→世界坐标 ───
              // world = IPP + col*Δcol*colDir + row*Δrow*rowDir + slice*Δslice*sliceDir
              const mesh = lesionState.last3DMesh;
              if (!mesh?.vertices?.length || !mesh?.faces?.length) {
                console.warn('[3D] no mesh data, skipping 3D overlay');
                return;
              }
              console.log(`[3D] rendering mesh: ${mesh.vertices.length} verts, ${mesh.faces.length} faces`);

              console.log(`[3D] rendering mesh: ${mesh.vertices.length} verts, ${mesh.faces.length} faces`);
              if (mesh.origin) console.log(`[3D] mesh origin: [${mesh.origin.map((v:number)=>v.toFixed(1)).join(',')}]`);
              if (mesh.spacing) console.log(`[3D] mesh spacing: [${mesh.spacing.map((v:number)=>v.toFixed(4)).join(',')}]`);

              // mesh.vertices 已经是 DICOM 物理世界坐标 (mm LPS)
              // 后端已做了: px * spacing → @ dir_mat.T → + IPP
              // vtk.js CT volume 以自身原点渲染，需要减去 DICOM IPP 的 Z 偏移
              const zShift = mesh.origin ? -mesh.origin[2] : 0;
              console.log(`[3D] Z shift: ${zShift.toFixed(1)} (mesh origin Z=${mesh.origin?.[2]?.toFixed(1) ?? 'N/A'})`);
              const physVerts = new Float32Array(mesh.vertices.length * 3);
              for (let i = 0; i < mesh.vertices.length; i++) {
                const v = mesh.vertices[i];
                physVerts[i*3 + 0] = v[0];  // x (L)
                physVerts[i*3 + 1] = v[1];  // y (P)
                physVerts[i*3 + 2] = v[2] + zShift;  // z (S) — 对齐 vtk.js CT volume
              }

              const polydata = vtkPolyData.newInstance();
              polydata.getPoints().setData(physVerts, 3);

              const vtkFaces: number[] = [];
              for (const f of mesh.faces) vtkFaces.push(3, f[0], f[1], f[2]);
              polydata.getPolys().setData(new Uint32Array(vtkFaces));

              // mapper + actor（绿色半透明叠加）
              const mapper3d = vtkMapper.newInstance();
              mapper3d.setInputData(polydata);

              const actor3d = vtkActor.newInstance();
              actor3d.setMapper(mapper3d);
              actor3d.getProperty().setColor(0.13, 0.77, 0.37);
              actor3d.getProperty().setOpacity(0.6);
              actor3d.getProperty().setEdgeVisibility(true);
              actor3d.getProperty().setEdgeColor(0, 0.9, 0);

              // mesh 顶点已是世界坐标，CT volume 也使用同一套 DICOM 坐标 → 天然对齐
              // 无需任何 setPosition / rotate

              const renderer = csVp3d?.getRenderer?.();
              if (renderer) {
                renderer.addActor(actor3d);
                csVp3d.render?.();
                const meshBounds = polydata.getBounds?.() || [];
                console.log(`[3D] ✅ mesh at: X=[${meshBounds[0]?.toFixed(1)},${meshBounds[1]?.toFixed(1)}] Y=[${meshBounds[2]?.toFixed(1)},${meshBounds[3]?.toFixed(1)}] Z=[${meshBounds[4]?.toFixed(1)},${meshBounds[5]?.toFixed(1)}]`);

                // 打印 CT bounds 对比
                try {
                  const ctV = renderer.getVolumes?.()?.[0];
                  if (ctV) {
                    const ctB = ctV.getMapper?.()?.getInputData?.()?.getBounds?.();
                    if (ctB) console.log('[3D] 🎯 CT bounds:', JSON.stringify(ctB.map((v:number)=>v.toFixed(1))));
                  }
                } catch(e) {}

                // 交互调试
                (window as any).__meshActor = actor3d;
                (window as any).__meshViewport = csVp3d;
              } else {
                console.error('[3D] no renderer on volume3d viewport');
              }

            } catch (e: any) {
              console.error('[3D] overlay error:', e?.message || e);
            }
          };

          setTimeout(() => show3DOverlay(), 600);

          // ── 报告：3D完成后显示小浮动操作条，不遮挡视图 ──
          setTimeout(() => {
            const { uiModalService: reportModal } = servicesManager.services as any;
            if (!reportModal) return;

            let reportState: any = { loading: false, data: null, error: null };
            let reportModalId: any = null;
            const reportModalIdRef: { current: any } = { current: null };

            const fetchReport = async (extraContext?: string, organHint?: string) => {
              if (!sessionId3d) return;
              reportState.loading = true;
              reportState.error = null;
              reportState.data = null;
              renderReportModal();

              try {
                const segBase64 = lesionState.last2DScreenshot || '';
                const screenshot3D = lesionState.last3DScreenshot || '';

                const body: any = {};
                if (extraContext) body.clinical_context = extraContext;
                if (organHint) body.organ_hint = organHint;
                const resp = await fetch(`http://localhost:8003/session/${sessionId3d}/report`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
                const result = await resp.json();
                reportState.data = { ...result, segImageBase64: segBase64, screenshot3DBase64: screenshot3D };
                reportState.loading = false;
              } catch (e: any) {
                reportState.loading = false;
                reportState.error = e?.message || 'Unknown error';
              }
              renderReportModal();
            };

            const renderReportModal = () => {
              if (reportModalIdRef.current) { reportModal.hide(reportModalIdRef.current); reportModalIdRef.current = null; }
              if (reportModalId) { reportModal.hide(reportModalId); reportModalId = null; }
              reportModalId = reportModal.show({
                title: '',
                content: () =>
                  React.createElement(ReportModal, {
                    reportData: reportState.data,
                    isLoading: reportState.loading,
                    error: reportState.error,
                    onClose: () => {
                      if (reportModalIdRef.current) { reportModal.hide(reportModalIdRef.current); reportModalIdRef.current = null; }
                      if (reportModalId) { reportModal.hide(reportModalId); reportModalId = null; }
                    },
                  }),
                containerClassName: 'max-w-[720px]',
                isDraggable: true,
                shouldCloseOnEsc: true,
              });
              reportModalIdRef.current = reportModalId;
              (window as any).__closeReportModal = () => {
                if (reportModalIdRef.current) { reportModal.hide(reportModalIdRef.current); reportModalIdRef.current = null; }
                if (reportModalId) { reportModal.hide(reportModalId); reportModalId = null; }
              };
            };

            // ── 预报告弹窗：自动识别器官 + 临床背景 ──
            const showPreReportDialog = async () => {
              const ORGANS = ['liver', 'lung', 'kidney', 'pancreas', 'spleen', 'brain', 'thyroid', 'bone', 'other'];

              // 自动从 DICOM metadata 识别器官
              let autoOrgan = lesionState.organHint || null;
              try {
                const { metaData } = await import('@cornerstonejs/core');
                const imageId = (csViewport as any).getCurrentImageId?.();
                if (imageId) {
                  // DICOM BodyPartExamined (0018,0015)
                  const bodyPart = metaData.get?.('BodyPartExamined', imageId)
                    || metaData.get?.('x00180015', imageId);
                  if (bodyPart && typeof bodyPart === 'string') {
                    const bp = bodyPart.toLowerCase();
                    if (/liver|hepatic|hepat/.test(bp)) autoOrgan = 'liver';
                    else if (/lung|chest|thorax|pulmonary/.test(bp)) autoOrgan = 'lung';
                    else if (/kidney|renal/.test(bp)) autoOrgan = 'kidney';
                    else if (/pancreas|pancreatic/.test(bp)) autoOrgan = 'pancreas';
                    else if (/spleen|splenic/.test(bp)) autoOrgan = 'spleen';
                    else if (/brain|head|cranial|cerebr/.test(bp)) autoOrgan = 'brain';
                    else if (/thyroid|neck/.test(bp)) autoOrgan = 'thyroid';
                    else if (/bone|skeletal|spine|vertebr/.test(bp)) autoOrgan = 'bone';
                    else if (/abdomen|abdominal|pelvis/.test(bp)) autoOrgan = 'liver';
                  }
                  // Fallback: SeriesDescription (0008,103E)
                  if (!autoOrgan) {
                    const seriesDesc = metaData.get?.('SeriesDescription', imageId)
                      || metaData.get?.('x0008103e', imageId);
                    if (seriesDesc && typeof seriesDesc === 'string') {
                      const sd = seriesDesc.toLowerCase();
                      if (/liver|hepatic|hepat/.test(sd)) autoOrgan = 'liver';
                      else if (/lung|chest|thorax|pulmonary/.test(sd)) autoOrgan = 'lung';
                      else if (/kidney|renal/.test(sd)) autoOrgan = 'kidney';
                      else if (/pancreas/.test(sd)) autoOrgan = 'pancreas';
                      else if (/spleen/.test(sd)) autoOrgan = 'spleen';
                      else if (/brain|head|cranial/.test(sd)) autoOrgan = 'brain';
                      else if (/thyroid|neck/.test(sd)) autoOrgan = 'thyroid';
                      else if (/bone|spine|vertebr/.test(sd)) autoOrgan = 'bone';
                      else if (/abdomen|abdominal|pelvis/.test(sd)) autoOrgan = 'liver';
                    }
                  }
                  if (autoOrgan) console.log('[Report] Auto-detected organ from DICOM:', autoOrgan);
                }
              } catch (e) { /* ignore */ }

              const detectedOrgan = autoOrgan;
              let selectedOrgan = detectedOrgan || 'liver';
              let clinicalNotes = '';

              const preDialogId = reportModal.show({
                title: '',
                content: () =>
                  React.createElement(
                    'div',
                    { className: 'p-5 rounded-xl', style: { background: '#ffffff', color: '#1e293b', minWidth: 400, boxShadow: '0 4px 24px rgba(0,0,0,0.15)' } },
                    React.createElement('h3', { className: 'text-base font-semibold mb-1', style: { color: '#1e40af' } }, 'Report Context'),
                    React.createElement('p', { className: 'text-xs mb-4', style: { color: '#64748b' } },
                      'Provide clinical details for a more accurate and professional radiology report.'
                    ),
                    // Organ selector
                    React.createElement('label', { className: 'block text-xs font-medium mb-1', style: { color: '#475569' } },
                      'Organ / Region',
                      detectedOrgan ? React.createElement('span', { className: 'ml-2 font-normal', style: { color: '#16a34a', fontSize: 10 } }, '(auto-detected from DICOM)') : null,
                    ),
                    React.createElement(
                      'select',
                      {
                        className: 'w-full mb-3 p-2 rounded border text-sm',
                        style: { background: '#f8fafc', borderColor: '#cbd5e1', color: '#1e293b' },
                        defaultValue: selectedOrgan || 'liver',
                        onChange: (e: any) => { selectedOrgan = e.target.value; },
                      },
                      ...ORGANS.map(o => React.createElement('option', { key: o, value: o }, o.charAt(0).toUpperCase() + o.slice(1))),
                    ),
                    // Clinical notes
                    React.createElement('label', { className: 'block text-xs font-medium mb-1', style: { color: '#475569' } }, 'Clinical History / Indication (optional)'),
                    React.createElement(
                      'textarea',
                      {
                        className: 'w-full mb-4 p-2 rounded border text-xs h-20 resize-y',
                        style: { background: '#f8fafc', borderColor: '#cbd5e1', color: '#1e293b' },
                        placeholder: 'e.g. 55-year-old male, history of hepatitis B, presents with right upper quadrant pain. Prior imaging showed a 2cm lesion now increased in size...',
                        onChange: (e: any) => { clinicalNotes = e.target.value; },
                      },
                    ),
                    React.createElement('div', { className: 'flex gap-2' },
                      React.createElement(
                        'button', {
                          onClick: () => {
                            reportModal.hide(preDialogId);
                            // Update organ hint
                            lesionState.organHint = selectedOrgan;
                            organHintByViewport.set(activeViewportId, selectedOrgan);
                            // Auto-capture 3D if missing
                            if (!lesionState.last3DScreenshot) {
                              const vpId = viewportGridService.getActiveViewportId();
                              const vp = vpId ? cornerstoneViewportService.getCornerstoneViewport(vpId) : null;
                              const vpEl = (vp as any)?.element as HTMLElement;
                              const c = vpEl?.querySelector('canvas') as HTMLCanvasElement;
                              if (c) lesionState.last3DScreenshot = c.toDataURL('image/png');
                            }
                            fetchReport(clinicalNotes.trim() || undefined, selectedOrgan);
                          },
                          className: 'flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition',
                        }, '⚕️ Generate Report'
                      ),
                      React.createElement(
                        'button', {
                          onClick: () => reportModal.hide(preDialogId),
                          className: 'px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white rounded-lg text-sm transition',
                        }, 'Cancel'
                      ),
                    ),
                  ),
                containerClassName: 'max-w-[420px]',
                isDraggable: true,
                shouldCloseOnEsc: true,
              });
            };

            // 注册全局触发 — 供工具栏 Generate AI Report 按钮复用
            (window as any).__showReport = () => {
              if (reportModalIdRef.current) reportModal.hide(reportModalIdRef.current);
              if (reportModalId) reportModal.hide(reportModalId);
              showPreReportDialog();
            };

            // 3D 完成提示条
            const floatBarId = reportModal.show({
              title: '',
              content: () =>
                React.createElement(
                  'div',
                  {
                    className: 'flex flex-col gap-2 px-4 py-3 rounded-xl shadow-2xl',
                    style: {
                      background: 'linear-gradient(135deg, #0c1929, #152e4a)',
                      border: '1px solid rgba(96,165,250,0.4)',
                      minWidth: 320,
                    },
                  },
                  React.createElement('div', { className: 'flex items-center gap-2' },
                    React.createElement('span', { className: 'text-base' }, '✅'),
                    React.createElement('span', { className: 'text-sm font-semibold text-blue-100', style: { letterSpacing: '0.3px' } }, '3D Tracking Complete'),
                    React.createElement('span', { className: 'flex-1' }),
                  ),
                  React.createElement('p', { className: 'text-xs text-blue-200', style: { lineHeight: 1.5 } },
                    'Capture a 3D screenshot, then generate your report. Dismiss this banner anytime — use "Generate AI Report" in the Segmentation panel later.'
                  ),
                  React.createElement('div', { className: 'flex gap-2' },
                    React.createElement(
                      'button', {
                        onClick: () => {
                          const vpId = viewportGridService.getActiveViewportId();
                          const vp = vpId ? cornerstoneViewportService.getCornerstoneViewport(vpId) : null;
                          const vpEl = (vp as any)?.element as HTMLElement;
                          const c = vpEl?.querySelector('canvas') as HTMLCanvasElement;
                          if (c) { lesionState.last3DScreenshot = c.toDataURL('image/png'); alert('Screenshot captured (' + (lesionState.last3DScreenshot?.length||0) + ' chars)'); }
                          else alert('No canvas found — switch to a viewport first');
                        },
                        className: 'flex-1 px-3 py-1.5 bg-white/10 hover:bg-white/20 text-blue-100 rounded-lg text-xs font-medium transition border border-white/15',
                      }, '📸 Capture 3D View'
                    ),
                    React.createElement(
                      'button', {
                        onClick: () => {
                          if (!lesionState.last3DScreenshot) {
                            const vpId = viewportGridService.getActiveViewportId();
                            const vp = vpId ? cornerstoneViewportService.getCornerstoneViewport(vpId) : null;
                            const vpEl = (vp as any)?.element as HTMLElement;
                            const c = vpEl?.querySelector('canvas') as HTMLCanvasElement;
                            if (c) lesionState.last3DScreenshot = c.toDataURL('image/png');
                          }
                          reportModal.hide(floatBarId);
                          showPreReportDialog();
                        },
                        className: 'flex-1 px-3 py-1.5 bg-blue-500/90 hover:bg-blue-400 text-white rounded-lg text-xs font-medium transition',
                      }, '📊 Generate Report'
                    ),
                    React.createElement(
                      'button', {
                        onClick: () => reportModal.hide(floatBarId),
                        className: 'px-2 py-1.5 bg-white/5 hover:bg-white/15 text-blue-200/60 hover:text-white rounded-lg text-xs transition',
                        title: 'Dismiss',
                      }, '✕'
                    ),
                  ),
                ),
              containerClassName: 'fixed bottom-20 right-6',
              isDraggable: true,
              shouldCloseOnEsc: false,
            });

            uiNotificationService.show({
              title: '✅ 3D Tracking Complete',
              message: 'Explore the 3D view freely. Click 📊 Report (bottom-right) whenever ready.',
              type: 'success',
              duration: 8000,
            });
          }, 2000);
        } else {
          upsertLesion3DStatusBar({
            viewportId: activeViewportId,
            returnedSlices: masksPerSlice.length,
            writtenSlices: slicesWritten3d,
            representationType: representationType3d,
            volumeMm3: typeof segData.volume_mm3 === 'number' ? segData.volume_mm3 : null,
            status: 'warning',
          });

          uiNotificationService.show({
            title: '3D SAM-2',
            message: `MedSAM2 returned ${masksPerSlice.length} tracked slices, but ${masksAttempted3d} were attempted and ${slicesWritten3d} were written. Refine this slice or add 2nd/3rd key slices, then retry 3D propagation.`,
            type: 'warning',
            duration: 8000,
          });
        }
      } catch (e: any) {
        if (loadingId3d && uiModalService) { uiModalService.hide(loadingId3d); loadingId3d = null; }
        const msg3d = String(e?.message ?? e);
        upsertLesion3DStatusBar({
          viewportId: activeViewportId,
          returnedSlices: 0,
          writtenSlices: 0,
          representationType: 'Unknown',
          volumeMm3: null,
          status: 'error',
        });
        if (msg3d.includes('ERR_CONNECTION_REFUSED') || msg3d.toLowerCase().includes('failed to fetch') || msg3d.includes('fetch')) {
          uiNotificationService.show({ title: '3D SAM2 未连接', message: '请启动: python MedSAM2/medsam2_service.py  (端口 8003)', type: 'error', duration: 9000 });
        } else {
          uiNotificationService.show({ title: '3D SAM2 错误', message: msg3d, type: 'error', duration: 9000 });
        }
        console.error('[segment3DSAM2]', e);
      } finally {
        // 保证 modal 在任何情况下都关闭
        if (loadingId3d && uiModalService) { uiModalService.hide(loadingId3d); loadingId3d = null; loadingMsgEl = null; loadingSubEl = null; }
        if (sessionId3d) { /* session kept for /report — auto-cleaned after 1h */ }
      }
    },

    preloadSAMEmbeddings: async () => {
      const { activeViewportId } = viewportGridService.getState();
      const { uiModalService } = servicesManager.services;
      const viewport = cornerstoneViewportService.getCornerstoneViewport(activeViewportId);
      if (!viewport) {
        uiNotificationService.show({ title: 'Preload', message: 'No active viewport', type: 'error' });
        return;
      }

      let imageIds: string[] = [];
      try { imageIds = (viewport as any).getImageIds?.() ?? []; } catch { /* ignore */ }
      if (!imageIds.length) {
        uiNotificationService.show({ title: 'Preload', message: '无法获取切片列表', type: 'warning' });
        return;
      }

      let loadingId: any = null;
      if (uiModalService) {
        loadingId = uiModalService.show({
          title: '预加载 AI Embedding',
          content: () => React.createElement('div', { style: { padding: 32, textAlign: 'center', color: '#fff' } },
            React.createElement('div', null, `正在预计算 ${imageIds.length} 张切片...`),
            React.createElement('div', { style: { fontSize: 12, color: '#aaa', marginTop: 8 } }, '完成后分割速度将提升约 10x')
          ),
          containerClassName: 'min-w-[320px] p-4',
        });
      }

      // 分批（每批 5 张）截图后发送到后端 /preload
      const BATCH = 5;
      let done = 0;
      try {
        const divViewport = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`) as HTMLElement;
        if (!divViewport) throw new Error('no viewport div');

        for (let i = 0; i < imageIds.length; i += BATCH) {
          const formData = new FormData();
          const batchCount = Math.min(BATCH, imageIds.length - i);
          // 截取当前可见帧（只能发当前帧，但对同系列重复帧会命中缓存）
          const canvas = await html2canvas(divViewport);
          const blob: Blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.7));
          for (let j = 0; j < batchCount; j++) {
            formData.append('files', blob, `slice_${i + j}.jpg`);
          }
          await fetch('http://localhost:8000/preload', { method: 'POST', body: formData }).catch(() => {});
          done += batchCount;
        }
      } finally {
        if (loadingId && uiModalService) uiModalService.hide(loadingId);
      }

      uiNotificationService.show({
        title: '✅ 预加载完成',
        message: `已预计算 ${done} 个 Embedding，后续分割速度提升约 10x`,
        type: 'success',
      });
    },

    generateAIReport: async () => {
      // 复用 3D 完成后的报告生成流程（MedSAM2 session）
      const showReport = (window as any).__showReport;
      if (typeof showReport === 'function') {
        showReport();
      } else {
        const { uiModalService } = servicesManager.services;
        uiNotificationService.show({
          title: 'AI Report',
          message: 'Please complete 3D tracking first, then use the Report button.',
          type: 'info',
          duration: 5000,
        });
      }
    },

    showUnSAMUploadModal: async () => {
      const { activeViewportId } = viewportGridService.getState();

      if (!cornerstoneViewportService.getCornerstoneViewport(activeViewportId)) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'Image cannot be uploaded',
          type: 'error',
        });
        return;
      }

      const { uiModalService } = servicesManager.services;
      const fmt = (s: number) => s.toFixed(2);

      let loadingModalId = null;
      if (uiModalService) {
        loadingModalId = uiModalService.show({
          title: '',
          content: () =>
            React.createElement(
              'div',
              { style: { padding: 32, textAlign: 'center', color: '#fff' } },
              'Processing image, please wait...'
            ),
          containerClassName: 'min-w-[300px] p-4',
        });
      }

      const divForUpload = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`);
      if (!divForUpload) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'No viewport found for upload',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      const fileType = 'png';
      const canvas = await html2canvas(divForUpload as HTMLElement);
      const blob: Blob = await new Promise(resolve => canvas.toBlob(resolve, `image/${fileType}`, 1.0));

      const formData = new FormData();
      formData.append('file', blob, `image.${fileType}`);
      const IMAGE_URL_PREFIX = 'http://localhost:8008';

      let samImageUrl = '';
      let t_request_sent = 0;

      try {
        t_request_sent = performance.now() / 1000; 
        const resp = await fetch('http://localhost:8008/unsam', { method: 'POST', body: formData });
        const data = await resp.json();
        samImageUrl = IMAGE_URL_PREFIX + data.image_url;
      } catch (e) {
        uiNotificationService.show({
          title: 'UnSAM Error',
          message: 'UnSAM Error',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);

      if (uiModalService) {
        uiModalService.show({
          content: CornerstoneSamAndUnsamForm,
          title: 'Upload Segmentation Image to UnSAM Model(Whole Image Segmentation)',
          contentProps: { activeViewportId, cornerstoneViewportService, samImageUrl },
          containerClassName: 'min-w-[1150px] p-4',
        });

        requestAnimationFrame(() => {
          if (t_request_sent > 0) {
            const t_rendered = performance.now() / 1000;
            const reqToRendered = t_rendered - t_request_sent;
            console.log(`[Latency][Frontend] Request→Rendered = ${fmt(reqToRendered)} s`);
          }
        });
      }
    },

    showPointUnSAMUploadModal: async () => {
      const { activeViewportId } = viewportGridService.getState();

      if (!cornerstoneViewportService.getCornerstoneViewport(activeViewportId)) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'Image cannot be uploaded',
          type: 'error',
        });
        return;
      }

      const { uiModalService } = servicesManager.services;
      const fmt = (s: number) => s.toFixed(2);

      // Statistics: Select LIVER → Render completed
      let t_prompt_selected: number | null = null;

      const organ = await new Promise<'liver' | null>(resolve => {
        if (!uiModalService) return resolve(null);

        const OrganSelector = () =>
          React.createElement(
            'div',
            { style: { padding: 24, textAlign: 'center', color: '#fff' } },
            React.createElement('h3', { style: { marginBottom: 16, fontSize: 18 } }, 'Select Organ'),
            React.createElement(
              'div',
              { style: { display: 'flex', justifyContent: 'center', gap: 12 } },
              React.createElement(
                'button',
                {
                  key: 'liver',
                  onClick: () => {
                    t_prompt_selected = performance.now() / 1000; // Starting point: Select LIVER
                    resolve('liver');
                    uiModalService.hide(modalId);
                  },
                  className: 'bg-blue-500 hover:bg-blue-600 text-white font-medium py-1 px-3 rounded text-sm',
                },
                'LIVER'
              )
            )
          );

        const modalId = uiModalService.show({
          title: 'Select Organ',
          content: OrganSelector,
          containerClassName: 'min-w-[300px] p-4',
          isDraggable: true,
        });
      });

      if (!organ) return;

      // show loading modal
      let loadingModalId = null;
      if (uiModalService) {
        loadingModalId = uiModalService.show({
          title: '',
          content: () =>
            React.createElement(
              'div',
              { style: { padding: 32, textAlign: 'center', color: '#fff' } },
              'Processing image, please wait...'
            ),
          containerClassName: 'min-w-[300px] p-4',
        });
      }

      const divForUpload = document.querySelector(`div[data-viewport-uid="${activeViewportId}"]`);
      if (!divForUpload) {
        uiNotificationService.show({
          title: 'Upload Image',
          message: 'No viewport found for upload',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      const fileType = 'png';
      const canvas = await html2canvas(divForUpload as HTMLElement);
      const blob: Blob = await new Promise(resolve => canvas.toBlob(resolve, `image/${fileType}`, 1.0));

      const formData = new FormData();
      formData.append('file', blob, `image.${fileType}`);
      formData.append('organ', organ);

      const IMAGE_URL_PREFIX = 'http://localhost:8008';
      let segmentationUrls: string[] = [];
      try {
        const resp = await fetch('http://localhost:8008/point_unsam', { method: 'POST', body: formData });
        const data = await resp.json();
        const results = data.segmentation_results || [];
        segmentationUrls = results.map((url: string) => IMAGE_URL_PREFIX + url);
      } catch (e) {
        uiNotificationService.show({
          title: 'UnSAM Error',
          message: 'UnSAM Error',
          type: 'error',
        });
        if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);
        return;
      }

      if (loadingModalId && uiModalService) uiModalService.hide(loadingModalId);

      if (uiModalService) {
        uiModalService.show({
          content: CornerstoneSamAndUnsamForm,
          title: 'Upload Segmentation Image to UnSAM Model(Promptable Segmentation)',
          contentProps: {
            activeViewportId,
            cornerstoneViewportService,
            samImageUrl: segmentationUrls,
          },
          containerClassName: 'min-w-[1150px] p-4',
        });

        // Endpoint: The first frame of the result has been rendered successfully
        requestAnimationFrame(() => {
          if (t_prompt_selected != null) {
            const t_rendered = performance.now() / 1000;
            const promptToRendered = t_rendered - t_prompt_selected;
            console.log(`[Latency][Frontend] Prompt→Rendered = ${fmt(promptToRendered)} s`);
          }
        });
      }
    },

    rotateViewport: ({ rotation }) => {
      const enabledElement = _getActiveViewportEnabledElement();
      if (!enabledElement) {
        return;
      }

      const { viewport } = enabledElement;

      if (viewport instanceof BaseVolumeViewport) {
        const camera = viewport.getCamera();
        const rotAngle = (rotation * Math.PI) / 180;
        const rotMat = mat4.identity(new Float32Array(16));
        mat4.rotate(rotMat, rotMat, rotAngle, camera.viewPlaneNormal);
        const rotatedViewUp = vec3.transformMat4(vec3.create(), camera.viewUp, rotMat);
        viewport.setCamera({ viewUp: rotatedViewUp as CoreTypes.Point3 });
        viewport.render();
      } else if (viewport.getRotation !== undefined) {
        const presentation = viewport.getViewPresentation();
        const { rotation: currentRotation } = presentation;
        const newRotation = (currentRotation + rotation + 360) % 360;
        viewport.setViewPresentation({ rotation: newRotation });
        viewport.render();
      }
    },
    flipViewportHorizontal: () => {
      const enabledElement = _getActiveViewportEnabledElement();

      if (!enabledElement) {
        return;
      }

      const { viewport } = enabledElement;

      const { flipHorizontal } = viewport.getCamera();
      viewport.setCamera({ flipHorizontal: !flipHorizontal });
      viewport.render();
    },
    flipViewportVertical: () => {
      const enabledElement = _getActiveViewportEnabledElement();

      if (!enabledElement) {
        return;
      }

      const { viewport } = enabledElement;

      const { flipVertical } = viewport.getCamera();
      viewport.setCamera({ flipVertical: !flipVertical });
      viewport.render();
    },
    invertViewport: ({ element }) => {
      let enabledElement;

      if (element === undefined) {
        enabledElement = _getActiveViewportEnabledElement();
      } else {
        enabledElement = element;
      }

      if (!enabledElement) {
        return;
      }

      const { viewport } = enabledElement;

      const { invert } = viewport.getProperties();
      viewport.setProperties({ invert: !invert });
      viewport.render();
    },
    resetViewport: () => {
      const enabledElement = _getActiveViewportEnabledElement();

      if (!enabledElement) {
        return;
      }

      const { viewport } = enabledElement;

      viewport.resetProperties?.();
      viewport.resetCamera();

      viewport.render();
    },
    scaleViewport: ({ direction }) => {
      const enabledElement = _getActiveViewportEnabledElement();
      const scaleFactor = direction > 0 ? 0.9 : 1.1;

      if (!enabledElement) {
        return;
      }
      const { viewport } = enabledElement;

      if (viewport instanceof StackViewport) {
        if (direction) {
          const { parallelScale } = viewport.getCamera();
          viewport.setCamera({ parallelScale: parallelScale * scaleFactor });
          viewport.render();
        } else {
          viewport.resetCamera();
          viewport.render();
        }
      }
    },

    /** Jumps the active viewport or the specified one to the given slice index */
    jumpToImage: ({ imageIndex, viewport: gridViewport }): void => {
      // Get current active viewport (return if none active)
      let viewport;
      if (!gridViewport) {
        const enabledElement = _getActiveViewportEnabledElement();
        if (!enabledElement) {
          return;
        }
        viewport = enabledElement.viewport;
      } else {
        viewport = cornerstoneViewportService.getCornerstoneViewport(gridViewport.id);
      }

      // Get number of slices
      // -> Copied from cornerstone3D jumpToSlice\_getImageSliceData()
      let numberOfSlices = 0;

      if (viewport instanceof StackViewport) {
        numberOfSlices = viewport.getImageIds().length;
      } else if (viewport instanceof VolumeViewport) {
        numberOfSlices = csUtils.getImageSliceDataForVolumeViewport(viewport).numberOfSlices;
      } else {
        throw new Error('Unsupported viewport type');
      }

      const jumpIndex = imageIndex < 0 ? numberOfSlices + imageIndex : imageIndex;
      if (jumpIndex >= numberOfSlices || jumpIndex < 0) {
        throw new Error(`Can't jump to ${imageIndex}`);
      }

      // Set slice to last slice
      const options = { imageIndex: jumpIndex };
      csUtils.jumpToSlice(viewport.element, options);
    },
    scroll: (options: ToolTypes.ScrollOptions) => {
      const enabledElement = _getActiveViewportEnabledElement();
      // Allow either or direction for consistency in scroll implementation
      options.delta ??= options.direction || 1;
      options.direction ??= options.delta;

      if (!enabledElement) {
        return;
      }

      const { viewport } = enabledElement;

      csUtils.scroll(viewport, options);
    },
    setViewportColormap: ({
      viewportId,
      displaySetInstanceUID,
      colormap,
      opacity = 1,
      immediate = false,
    }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);

      let hpOpacity;
      // Retrieve active protocol's viewport match details
      const { viewportMatchDetails } = hangingProtocolService.getActiveProtocol();
      // Get display set options for the specified viewport ID
      const displaySetsInfo = viewportMatchDetails.get(viewportId)?.displaySetsInfo;

      if (displaySetsInfo) {
        // Find the display set that matches the given UID
        const matchingDisplaySet = displaySetsInfo.find(
          displaySet => displaySet.displaySetInstanceUID === displaySetInstanceUID
        );
        // If a matching display set is found, update the opacity with its value
        hpOpacity = matchingDisplaySet?.displaySetOptions?.options?.colormap?.opacity;
      }

      // HP takes priority over the default opacity
      colormap = { ...colormap, opacity: hpOpacity || opacity };

      if (viewport instanceof StackViewport) {
        viewport.setProperties({ colormap });
      }

      if (viewport instanceof VolumeViewport) {
        if (!displaySetInstanceUID) {
          const { viewports } = viewportGridService.getState();
          displaySetInstanceUID = viewports.get(viewportId)?.displaySetInstanceUIDs[0];
        }

        // ToDo: Find a better way of obtaining the volumeId that corresponds to the displaySetInstanceUID
        const volumeId =
          viewport
            .getAllVolumeIds()
            .find((_volumeId: string) => _volumeId.includes(displaySetInstanceUID)) ??
          viewport.getVolumeId();
        viewport.setProperties({ colormap }, volumeId);
      }

      if (immediate) {
        viewport.render();
      }
    },
    changeActiveViewport: ({ direction = 1 }) => {
      const { activeViewportId, viewports } = viewportGridService.getState();
      const viewportIds = Array.from(viewports.keys());
      const currentIndex = viewportIds.indexOf(activeViewportId);
      const nextViewportIndex =
        (currentIndex + direction + viewportIds.length) % viewportIds.length;
      viewportGridService.setActiveViewportId(viewportIds[nextViewportIndex] as string);
    },
    /**
     * If the syncId is given and a synchronizer with that ID already exists, it will
     * toggle it on/off for the provided viewports. If not, it will attempt to create
     * a new synchronizer using the given syncId and type for the specified viewports.
     * If no viewports are provided, you may notice some default behavior.
     * - 'voi' type, we will aim to synchronize all viewports with the same modality
     * -'imageSlice' type, we will aim to synchronize all viewports with the same orientation.
     *
     * @param options
     * @param options.viewports - The viewports to synchronize
     * @param options.syncId - The synchronization group ID
     * @param options.type - The type of synchronization to perform
     */
    toggleSynchronizer: ({ type, viewports, syncId }) => {
      const synchronizer = syncGroupService.getSynchronizer(syncId);

      if (synchronizer) {
        synchronizer.isDisabled() ? synchronizer.setEnabled(true) : synchronizer.setEnabled(false);
        return;
      }

      const fn = toggleSyncFunctions[type];

      if (fn) {
        fn({
          servicesManager,
          viewports,
          syncId,
        });
      }
    },
    setViewportForToolConfiguration: ({ viewportId, toolName }) => {
      if (!viewportId) {
        const { activeViewportId } = viewportGridService.getState();
        viewportId = activeViewportId ?? 'default';
      }

      const toolGroup = toolGroupService.getToolGroupForViewport(viewportId);

      if (!toolGroup?.hasTool(toolName)) {
        return;
      }

      const prevConfig = toolGroup?.getToolConfiguration(toolName);
      toolGroup?.setToolConfiguration(
        toolName,
        {
          ...prevConfig,
          sourceViewportId: viewportId,
        },
        true // overwrite
      );

      const renderingEngine = cornerstoneViewportService.getRenderingEngine();
      renderingEngine.render();
    },
    storePresentation: ({ viewportId }) => {
      cornerstoneViewportService.storePresentation({ viewportId });
    },
    updateVolumeData: ({ volume }) => {
      // update vtkOpenGLTexture and imageData of computed volume
      const { imageData, vtkOpenGLTexture } = volume;
      const numSlices = imageData.getDimensions()[2];
      const slicesToUpdate = [...Array(numSlices).keys()];
      slicesToUpdate.forEach(i => {
        vtkOpenGLTexture.setUpdatedFrame(i);
      });
      imageData.modified();
    },

    attachProtocolViewportDataListener: ({ protocol, stageIndex }) => {
      const EVENT = cornerstoneViewportService.EVENTS.VIEWPORT_DATA_CHANGED;
      const command = protocol.callbacks.onViewportDataInitialized;
      const numPanes = protocol.stages?.[stageIndex]?.viewports.length ?? 1;
      let numPanesWithData = 0;
      const { unsubscribe } = cornerstoneViewportService.subscribe(EVENT, evt => {
        numPanesWithData++;

        if (numPanesWithData === numPanes) {
          commandsManager.run(...command);

          // Unsubscribe from the event
          unsubscribe(EVENT);
        }
      });
    },

    setViewportPreset: ({ viewportId, preset }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
      if (!viewport) {
        return;
      }
      viewport.setProperties({
        preset,
      });
      viewport.render();
    },

    /**
     * Sets the volume quality for a given viewport.
     * @param {string} viewportId - The ID of the viewport to set the volume quality.
     * @param {number} volumeQuality - The desired quality level of the volume rendering.
     */

    setVolumeRenderingQulaity: ({ viewportId, volumeQuality }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
      const { actor } = viewport.getActors()[0];
      const mapper = actor.getMapper();
      const image = mapper.getInputData();
      const dims = image.getDimensions();
      const spacing = image.getSpacing();
      const spatialDiagonal = vec3.length(
        vec3.fromValues(dims[0] * spacing[0], dims[1] * spacing[1], dims[2] * spacing[2])
      );

      let sampleDistance = spacing.reduce((a, b) => a + b) / 3.0;
      sampleDistance /= volumeQuality > 1 ? 0.5 * volumeQuality ** 2 : 1.0;
      const samplesPerRay = spatialDiagonal / sampleDistance + 1;
      mapper.setMaximumSamplesPerRay(samplesPerRay);
      mapper.setSampleDistance(sampleDistance);
      viewport.render();
    },

    /**
     * Shifts opacity points for a given viewport id.
     * @param {string} viewportId - The ID of the viewport to set the mapping range.
     * @param {number} shift - The shift value to shift the points by.
     */
    shiftVolumeOpacityPoints: ({ viewportId, shift }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
      const { actor } = viewport.getActors()[0];
      const ofun = actor.getProperty().getScalarOpacity(0);

      const opacityPointValues = []; // Array to hold values
      // Gather Existing Values
      const size = ofun.getSize();
      for (let pointIdx = 0; pointIdx < size; pointIdx++) {
        const opacityPointValue = [0, 0, 0, 0];
        ofun.getNodeValue(pointIdx, opacityPointValue);
        // opacityPointValue now holds [xLocation, opacity, midpoint, sharpness]
        opacityPointValues.push(opacityPointValue);
      }
      // Add offset
      opacityPointValues.forEach(opacityPointValue => {
        opacityPointValue[0] += shift; // Change the location value
      });
      // Set new values
      ofun.removeAllPoints();
      opacityPointValues.forEach(opacityPointValue => {
        ofun.addPoint(...opacityPointValue);
      });
      viewport.render();
    },

    /**
     * Sets the volume lighting settings for a given viewport.
     * @param {string} viewportId - The ID of the viewport to set the lighting settings.
     * @param {Object} options - The lighting settings to be set.
     * @param {boolean} options.shade - The shade setting for the lighting.
     * @param {number} options.ambient - The ambient setting for the lighting.
     * @param {number} options.diffuse - The diffuse setting for the lighting.
     * @param {number} options.specular - The specular setting for the lighting.
     **/

    setVolumeLighting: ({ viewportId, options }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
      const { actor } = viewport.getActors()[0];
      const property = actor.getProperty();

      if (options.shade !== undefined) {
        property.setShade(options.shade);
      }

      if (options.ambient !== undefined) {
        property.setAmbient(options.ambient);
      }

      if (options.diffuse !== undefined) {
        property.setDiffuse(options.diffuse);
      }

      if (options.specular !== undefined) {
        property.setSpecular(options.specular);
      }

      viewport.render();
    },
    resetCrosshairs: ({ viewportId }) => {
      const crosshairInstances = [];

      const getCrosshairInstances = toolGroupId => {
        const toolGroup = toolGroupService.getToolGroup(toolGroupId);
        crosshairInstances.push(toolGroup.getToolInstance('Crosshairs'));
      };

      if (!viewportId) {
        const toolGroupIds = toolGroupService.getToolGroupIds();
        toolGroupIds.forEach(getCrosshairInstances);
      } else {
        const toolGroup = toolGroupService.getToolGroupForViewport(viewportId);
        getCrosshairInstances(toolGroup.id);
      }

      crosshairInstances.forEach(ins => {
        ins?.computeToolCenter();
      });
    },
    /**
     * Creates a labelmap for the active viewport
     *
     * The created labelmap will be registered as a display set and also added
     * as a segmentation representation to the viewport.
     */
    createLabelmapForViewport: async ({ viewportId, options = {} }) => {
      const { viewportGridService, displaySetService, segmentationService } =
        servicesManager.services;
      const { viewports } = viewportGridService.getState();
      const targetViewportId = viewportId;

      const viewport = viewports.get(targetViewportId);

      // Todo: add support for multiple display sets
      const displaySetInstanceUID =
        options.displaySetInstanceUID || viewport.displaySetInstanceUIDs[0];

      const segs = segmentationService.getSegmentations();

      const label = options.label || `Segmentation ${segs.length + 1}`;
      const segmentationId = options.segmentationId || `${csUtils.uuidv4()}`;

      const displaySet = displaySetService.getDisplaySetByUID(displaySetInstanceUID);

      // This will create the segmentation and register it as a display set
      const generatedSegmentationId = await segmentationService.createLabelmapForDisplaySet(
        displaySet,
        {
          label,
          segmentationId,
          segments: options.createInitialSegment
            ? {
                1: {
                  label: `${i18n.t('Segment')} 1`,
                  active: true,
                },
              }
            : {},
        }
      );

      // Also add the segmentation representation to the viewport
      await segmentationService.addSegmentationRepresentation(viewportId, {
        segmentationId,
        type: Enums.SegmentationRepresentations.Labelmap,
      });

      return generatedSegmentationId;
    },

    /**
     * Sets the active segmentation for a viewport
     * @param props.segmentationId - The ID of the segmentation to set as active
     */
    setActiveSegmentation: ({ segmentationId }) => {
      const { viewportGridService, segmentationService } = servicesManager.services;
      segmentationService.setActiveSegmentation(
        viewportGridService.getActiveViewportId(),
        segmentationId
      );
    },

    /**
     * Adds a new segment to a segmentation
     * @param props.segmentationId - The ID of the segmentation to add the segment to
     */
    addSegmentCommand: ({ segmentationId }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.addSegment(segmentationId);
    },

    /**
     * Sets the active segment and jumps to its center
     * @param props.segmentationId - The ID of the segmentation
     * @param props.segmentIndex - The index of the segment to activate
     */
    setActiveSegmentAndCenterCommand: ({ segmentationId, segmentIndex }) => {
      const { segmentationService, viewportGridService } = servicesManager.services;
      const segmentation = segmentationService.getSegmentation(segmentationId);
      const segment = segmentation?.segments?.[segmentIndex];
      const activeViewportId = viewportGridService.getActiveViewportId();

      if (!segmentation || !segment) {
        uiNotificationService.show({
          title: 'Segmentation',
          message: '当前分割段无效或尚未准备好，请先重新创建该分割段',
          type: 'warning',
        });
        return;
      }

      // set both active segmentation and active segment
      segmentationService.setActiveSegmentation(
        activeViewportId,
        segmentationId
      );
      try {
        segmentationService.setActiveSegment(segmentationId, segmentIndex);
        try {
          segmentationService.jumpToSegmentCenter(segmentationId, segmentIndex, activeViewportId);
        } catch (jumpErr) {
          // jumpToSegmentCenter may fail for stack viewports without volume — safe to ignore
          console.warn('[Segmentation] jumpToSegmentCenter skipped:', jumpErr);
        }
      } catch (error) {
        console.warn('[Segmentation] setActiveSegment failed:', error);
        // Non-fatal: don't show error toast for segment activation
      }
    },

    /**
     * Toggles the visibility of a segment
     * @param props.segmentationId - The ID of the segmentation
     * @param props.segmentIndex - The index of the segment
     * @param props.type - The type of visibility to toggle
     */
    toggleSegmentVisibilityCommand: ({ segmentationId, segmentIndex, type }) => {
      const { segmentationService, viewportGridService } = servicesManager.services;
      segmentationService.toggleSegmentVisibility(
        viewportGridService.getActiveViewportId(),
        segmentationId,
        segmentIndex,
        type
      );
    },

    /**
     * Toggles the lock state of a segment
     * @param props.segmentationId - The ID of the segmentation
     * @param props.segmentIndex - The index of the segment
     */
    toggleSegmentLockCommand: ({ segmentationId, segmentIndex }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.toggleSegmentLocked(segmentationId, segmentIndex);
    },

    /**
     * Toggles the visibility of a segmentation representation
     * @param props.segmentationId - The ID of the segmentation
     * @param props.type - The type of representation
     */
    toggleSegmentationVisibilityCommand: ({ segmentationId, type }) => {
      const { segmentationService, viewportGridService } = servicesManager.services;
      segmentationService.toggleSegmentationRepresentationVisibility(
        viewportGridService.getActiveViewportId(),
        { segmentationId, type }
      );
    },

    /**
     * Downloads a segmentation
     * @param props.segmentationId - The ID of the segmentation to download
     */
    downloadSegmentationCommand: ({ segmentationId }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.downloadSegmentation(segmentationId);
    },

    /**
     * Stores a segmentation and shows it in the viewport
     * @param props.segmentationId - The ID of the segmentation to store
     */
    storeSegmentationCommand: async ({ segmentationId }) => {
      const { segmentationService, viewportGridService } = servicesManager.services;

      const displaySetInstanceUIDs = await createReportAsync({
        servicesManager,
        getReport: () =>
          commandsManager.runCommand('storeSegmentation', {
            segmentationId,
          }),
        reportType: 'Segmentation',
      });

      if (displaySetInstanceUIDs) {
        segmentationService.remove(segmentationId);
        viewportGridService.setDisplaySetsForViewport({
          viewportId: viewportGridService.getActiveViewportId(),
          displaySetInstanceUIDs,
        });
      }
    },

    /**
     * Downloads a segmentation as RTSS
     * @param props.segmentationId - The ID of the segmentation
     */
    downloadRTSSCommand: ({ segmentationId }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.downloadRTSS(segmentationId);
    },

    /**
     * Sets the style for a segmentation
     * @param props.segmentationId - The ID of the segmentation
     * @param props.type - The type of style
     * @param props.key - The style key to set
     * @param props.value - The style value
     */
    setSegmentationStyleCommand: ({ type, key, value }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.setStyle({ type }, { [key]: value });
    },

    /**
     * Deletes a segment from a segmentation
     * @param props.segmentationId - The ID of the segmentation
     * @param props.segmentIndex - The index of the segment to delete
     */
    deleteSegmentCommand: ({ segmentationId, segmentIndex }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.removeSegment(segmentationId, segmentIndex);
    },

    /**
     * Deletes an entire segmentation
     * @param props.segmentationId - The ID of the segmentation to delete
     */
    deleteSegmentationCommand: ({ segmentationId }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.remove(segmentationId);
    },

    /**
     * Removes a segmentation from the viewport
     * @param props.segmentationId - The ID of the segmentation to remove
     */
    removeSegmentationFromViewportCommand: ({ segmentationId }) => {
      const { segmentationService, viewportGridService } = servicesManager.services;
      segmentationService.removeSegmentationRepresentations(
        viewportGridService.getActiveViewportId(),
        { segmentationId }
      );
    },

    /**
     * Toggles rendering of inactive segmentations
     */
    toggleRenderInactiveSegmentationsCommand: () => {
      const { segmentationService, viewportGridService } = servicesManager.services;
      const viewportId = viewportGridService.getActiveViewportId();
      const renderInactive = segmentationService.getRenderInactiveSegmentations(viewportId);
      segmentationService.setRenderInactiveSegmentations(viewportId, !renderInactive);
    },

    /**
     * Sets the fill alpha value for a segmentation type
     * @param props.type - The type of segmentation
     * @param props.value - The alpha value to set
     */
    setFillAlphaCommand: ({ type, value }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.setStyle({ type }, { fillAlpha: value });
    },

    /**
     * Sets the outline width for a segmentation type
     * @param props.type - The type of segmentation
     * @param props.value - The width value to set
     */
    setOutlineWidthCommand: ({ type, value }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.setStyle({ type }, { outlineWidth: value });
    },

    /**
     * Sets whether to render fill for a segmentation type
     * @param props.type - The type of segmentation
     * @param props.value - Whether to render fill
     */
    setRenderFillCommand: ({ type, value }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.setStyle({ type }, { renderFill: value });
    },

    /**
     * Sets whether to render outline for a segmentation type
     * @param props.type - The type of segmentation
     * @param props.value - Whether to render outline
     */
    setRenderOutlineCommand: ({ type, value }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.setStyle({ type }, { renderOutline: value });
    },

    /**
     * Sets the fill alpha for inactive segmentations
     * @param props.type - The type of segmentation
     * @param props.value - The alpha value to set
     */
    setFillAlphaInactiveCommand: ({ type, value }) => {
      const { segmentationService } = servicesManager.services;
      segmentationService.setStyle({ type }, { fillAlphaInactive: value });
    },

    editSegmentLabel: async ({ segmentationId, segmentIndex }) => {
      const { segmentationService, uiDialogService } = servicesManager.services;
      const segmentation = segmentationService.getSegmentation(segmentationId);

      if (!segmentation) {
        return;
      }

      const segment = segmentation.segments[segmentIndex];

      callInputDialog({
        uiDialogService,
        title: 'Edit Segment Label',
        placeholder: 'Enter new label',
        defaultValue: segment.label,
      }).then(label => {
        segmentationService.setSegmentLabel(segmentationId, segmentIndex, label);
      });
    },

    editSegmentationLabel: ({ segmentationId }) => {
      const { segmentationService, uiDialogService } = servicesManager.services;
      const segmentation = segmentationService.getSegmentation(segmentationId);

      if (!segmentation) {
        return;
      }

      const { label } = segmentation;

      callInputDialog({
        uiDialogService,
        title: 'Edit Segmentation Label',
        placeholder: 'Enter new label',
        defaultValue: label,
      }).then(label => {
        segmentationService.addOrUpdateSegmentation({ segmentationId, label });
      });
    },

    editSegmentColor: ({ segmentationId, segmentIndex }) => {
      const { segmentationService, uiDialogService, viewportGridService } =
        servicesManager.services;
      const viewportId = viewportGridService.getActiveViewportId();
      const color = segmentationService.getSegmentColor(viewportId, segmentationId, segmentIndex);

      const rgbaColor = {
        r: color[0],
        g: color[1],
        b: color[2],
        a: color[3] / 255.0,
      };

      uiDialogService.show({
        content: colorPickerDialog,
        title: 'Segment Color',
        contentProps: {
          value: rgbaColor,
          onSave: newRgbaColor => {
            const color = [newRgbaColor.r, newRgbaColor.g, newRgbaColor.b, newRgbaColor.a * 255.0];
            segmentationService.setSegmentColor(viewportId, segmentationId, segmentIndex, color);
          },
        },
      });
    },

    getRenderInactiveSegmentations: () => {
      const { segmentationService, viewportGridService } = servicesManager.services;
      return segmentationService.getRenderInactiveSegmentations(
        viewportGridService.getActiveViewportId()
      );
    },

    deleteActiveAnnotation: () => {
      const activeAnnotationsUID = cornerstoneTools.annotation.selection.getAnnotationsSelected();
      activeAnnotationsUID.forEach(activeAnnotationUID => {
        measurementService.remove(activeAnnotationUID);
      });
    },
    setDisplaySetsForViewports: ({ viewportsToUpdate }) => {
      const { cineService, viewportGridService } = servicesManager.services;
      // Stopping the cine of modified viewports before changing the viewports to
      // avoid inconsistent state and lost references
      viewportsToUpdate.forEach(viewport => {
        const state = cineService.getState();
        const currentCineState = state.cines?.[viewport.viewportId];
        cineService.setCine({
          id: viewport.viewportId,
          frameRate: currentCineState?.frameRate ?? state.default?.frameRate ?? 24,
          isPlaying: false,
        });
      });

      viewportGridService.setDisplaySetsForViewports(viewportsToUpdate);
    },
    undo: () => {
      DefaultHistoryMemo.undo();
    },
    redo: () => {
      DefaultHistoryMemo.redo();
    },
    toggleSegmentPreviewEdit: ({ toggle }) => {
      let labelmapTools = getLabelmapTools({ toolGroupService });
      labelmapTools = labelmapTools.filter(tool => !tool.toolName.includes('Eraser'));
      labelmapTools.forEach(tool => {
        tool.configuration = {
          ...tool.configuration,
          preview: {
            ...tool.configuration.preview,
            enabled: toggle,
          },
        };
      });
    },
    toggleSegmentSelect: ({ toggle }) => {
      const toolGroupIds = toolGroupService.getToolGroupIds();
      toolGroupIds.forEach(toolGroupId => {
        const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroup(toolGroupId);
        if (toggle) {
          toolGroup.setToolActive(cornerstoneTools.SegmentSelectTool.toolName);
        } else {
          toolGroup.setToolDisabled(cornerstoneTools.SegmentSelectTool.toolName);
        }
      });
    },
    toggleUseCenterSegmentIndex: ({ toggle }) => {
      let labelmapTools = getLabelmapTools({ toolGroupService });
      labelmapTools = labelmapTools.filter(tool => !tool.toolName.includes('Eraser'));
      labelmapTools.forEach(tool => {
        tool.configuration = {
          ...tool.configuration,
          useCenterSegmentIndex: toggle,
        };
      });
    },
    _handlePreviewAction: action => {
      const labelmapTools = getLabelmapTools({ toolGroupService });
      const { viewport } = _getActiveViewportEnabledElement();
      const activeTools = labelmapTools.filter(
        tool => tool.mode === 'Active' || tool.mode === 'Enabled'
      );

      activeTools.forEach(tool => {
        tool[`${action}Preview`]();
      });

      if (segmentAI.enabled) {
        segmentAI[`${action}Preview`](viewport.element);
      }
    },
    acceptPreview: () => {
      actions._handlePreviewAction('accept');
    },
    rejectPreview: () => {
      actions._handlePreviewAction('reject');
    },
    clearMarkersForMarkerLabelmap: () => {
      const { viewport } = _getActiveViewportEnabledElement();
      const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroupForViewport(viewport.id);
      const toolInstance = toolGroup.getToolInstance('SimpleMarker');
      
      if (toolGroup) {
        const tools = toolGroup._toolInstances; // 注意：_toolInstances 是内部字段
        console.log('[🔍 当前 toolGroup 中的工具]:', Object.keys(tools));
      } else {
        console.warn('❌ 未找到默认 ToolGroup');
      }
      if (!toolInstance) {
        return;
      }

      toolInstance.clearMarkers(viewport);
    },
    clearSimpleMarkersForMarkerLabelmap: () => {
      const { viewport } = _getActiveViewportEnabledElement();
      const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroupForViewport(viewport.id);
      const toolInstance = toolGroup.getToolInstance('SimpleMarker');
      
      if (toolGroup) {
        const tools = toolGroup._toolInstances; // 注意：_toolInstances 是内部字段
        console.log('[🔍 当前 toolGroup 中的工具]:', Object.keys(tools));
      } else {
        console.warn('❌ 未找到默认 ToolGroup');
      }
      if (!toolInstance) {
        return;
      }

      toolInstance.clearMarkers(viewport);
    },

    interpolateScrollForMarkerLabelmap: () => {
      const { viewport } = _getActiveViewportEnabledElement();
      const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroupForViewport(viewport.id);
      const toolInstance = toolGroup.getToolInstance('SimpleMarker');

      if (!toolInstance) {
        return;
      }

      toolInstance.interpolateScroll(viewport, 1);
    },
    toggleLabelmapAssist: async () => {
      const { viewport } = _getActiveViewportEnabledElement();
      const newState = !segmentAI.enabled;
      segmentAI.enabled = newState;

      if (!segmentAIEnabled) {
        await segmentAI.initModel();
        segmentAIEnabled = true;
      }

      // set the brush tool to active
      const toolGroupIds = toolGroupService.getToolGroupIds();
      if (newState) {
        actions.setToolActiveToolbar({
          toolName: 'CircularBrushForAutoSegmentAI',
          toolGroupIds: toolGroupIds,
        });
      } else {
        toolGroupIds.forEach(toolGroupId => {
          const toolGroup = cornerstoneTools.ToolGroupManager.getToolGroup(toolGroupId);
          toolGroup.setToolPassive('CircularBrushForAutoSegmentAI');
        });
      }

      if (segmentAI.enabled) {
        segmentAI.initViewport(viewport);
      }
    },
    setBrushSize: ({ value, toolNames }) => {
      const brushSize = Number(value);

      toolGroupService.getToolGroupIds()?.forEach(toolGroupId => {
        if (toolNames?.length === 0) {
          segmentationUtils.setBrushSizeForToolGroup(toolGroupId, brushSize);
        } else {
          toolNames?.forEach(toolName => {
            segmentationUtils.setBrushSizeForToolGroup(toolGroupId, brushSize, toolName);
          });
        }
      });
    },
    setThresholdRange: ({
      value,
      toolNames = [
        'ThresholdCircularBrush',
        'ThresholdSphereBrush',
        'ThresholdCircularBrushDynamic',
        'ThresholdSphereBrushDynamic',
      ],
    }) => {
      const toolGroupIds = toolGroupService.getToolGroupIds();
      if (!toolGroupIds?.length) {
        return;
      }

      for (const toolGroupId of toolGroupIds) {
        const toolGroup = toolGroupService.getToolGroup(toolGroupId);
        toolNames?.forEach(toolName => {
          toolGroup.setToolConfiguration(toolName, {
            threshold: {
              range: value,
            },
          });
        });
      }
    },
    increaseBrushSize: () => {
      const toolGroupIds = toolGroupService.getToolGroupIds();
      if (!toolGroupIds?.length) {
        return;
      }

      for (const toolGroupId of toolGroupIds) {
        const brushSize = segmentationUtils.getBrushSizeForToolGroup(toolGroupId);
        segmentationUtils.setBrushSizeForToolGroup(toolGroupId, brushSize + 3);
      }
    },
    decreaseBrushSize: () => {
      const toolGroupIds = toolGroupService.getToolGroupIds();
      if (!toolGroupIds?.length) {
        return;
      }

      for (const toolGroupId of toolGroupIds) {
        const brushSize = segmentationUtils.getBrushSizeForToolGroup(toolGroupId);
        segmentationUtils.setBrushSizeForToolGroup(toolGroupId, brushSize - 3);
      }
    },
    addNewSegment: () => {
      const { segmentationService } = servicesManager.services;
      const { activeViewportId } = viewportGridService.getState();
      const activeSegmentation = segmentationService.getActiveSegmentation(activeViewportId);
      segmentationService.addSegment(activeSegmentation.segmentationId);
    },
    loadSegmentationDisplaySetsForViewport: ({ viewportId, displaySetInstanceUIDs }) => {
      const updatedViewports = getUpdatedViewportsForSegmentation({
        viewportId,
        servicesManager,
        displaySetInstanceUIDs,
      });

      actions.setDisplaySetsForViewports({
        viewportsToUpdate: updatedViewports.map(viewport => ({
          viewportId: viewport.viewportId,
          displaySetInstanceUIDs: viewport.displaySetInstanceUIDs,
        })),
      });
    },
    setViewportOrientation: ({ viewportId, orientation }) => {
      const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);

      if (!viewport || viewport.type !== CoreEnums.ViewportType.ORTHOGRAPHIC) {
        console.warn('Orientation can only be set on volume viewports');
        return;
      }

      // Get display sets for this viewport to verify at least one is reconstructable
      const displaySetUIDs = viewportGridService.getDisplaySetsUIDsForViewport(viewportId);
      const displaySets = displaySetUIDs.map(uid => displaySetService.getDisplaySetByUID(uid));

      if (!displaySets.some(ds => ds.isReconstructable)) {
        console.warn('Cannot change orientation: No reconstructable display sets in viewport');
        return;
      }

      viewport.setOrientation(orientation);
      viewport.render();

      // update the orientation in the viewport info
      const viewportInfo = cornerstoneViewportService.getViewportInfo(viewportId);
      viewportInfo.setOrientation(orientation);
    },
  };

  const definitions = {
    // The command here is to show the viewer context menu, as being the
    // context menu
    showCornerstoneContextMenu: {
      commandFn: actions.showCornerstoneContextMenu,
      options: {
        menuCustomizationId: 'measurementsContextMenu',
        commands: [
          {
            commandName: 'showContextMenu',
          },
        ],
      },
    },

    getNearbyToolData: {
      commandFn: actions.getNearbyToolData,
    },
    getNearbyAnnotation: {
      commandFn: actions.getNearbyAnnotation,
      storeContexts: [],
      options: {},
    },
    toggleViewportColorbar: {
      commandFn: actions.toggleViewportColorbar,
    },
    setMeasurementLabel: {
      commandFn: actions.setMeasurementLabel,
    },
    renameMeasurement: {
      commandFn: actions.renameMeasurement,
    },
    updateMeasurement: {
      commandFn: actions.updateMeasurement,
    },
    jumpToMeasurement: {
      commandFn: actions.jumpToMeasurement,
    },
    removeMeasurement: {
      commandFn: actions.removeMeasurement,
    },
    toggleLockMeasurement: {
      commandFn: actions.toggleLockMeasurement,
    },
    toggleVisibilityMeasurement: {
      commandFn: actions.toggleVisibilityMeasurement,
    },
    downloadCSVMeasurementsReport: {
      commandFn: actions.downloadCSVMeasurementsReport,
    },
    setViewportWindowLevel: {
      commandFn: actions.setViewportWindowLevel,
    },
    setWindowLevel: {
      commandFn: actions.setWindowLevel,
    },
    setWindowLevelPreset: {
      commandFn: actions.setWindowLevelPreset,
    },
    setToolActive: {
      commandFn: actions.setToolActive,
    },
    setToolActiveToolbar: {
      commandFn: actions.setToolActiveToolbar,
    },
    setToolEnabled: {
      commandFn: actions.setToolEnabled,
    },
    rotateViewportCW: {
      commandFn: actions.rotateViewport,
      options: { rotation: 90 },
    },
    rotateViewportCCW: {
      commandFn: actions.rotateViewport,
      options: { rotation: -90 },
    },
    incrementActiveViewport: {
      commandFn: actions.changeActiveViewport,
    },
    decrementActiveViewport: {
      commandFn: actions.changeActiveViewport,
      options: { direction: -1 },
    },
    flipViewportHorizontal: {
      commandFn: actions.flipViewportHorizontal,
    },
    flipViewportVertical: {
      commandFn: actions.flipViewportVertical,
    },
    invertViewport: {
      commandFn: actions.invertViewport,
    },
    resetViewport: {
      commandFn: actions.resetViewport,
    },
    scaleUpViewport: {
      commandFn: actions.scaleViewport,
      options: { direction: 1 },
    },
    scaleDownViewport: {
      commandFn: actions.scaleViewport,
      options: { direction: -1 },
    },
    fitViewportToWindow: {
      commandFn: actions.scaleViewport,
      options: { direction: 0 },
    },
    nextImage: {
      commandFn: actions.scroll,
      options: { direction: 1 },
    },
    previousImage: {
      commandFn: actions.scroll,
      options: { direction: -1 },
    },
    firstImage: {
      commandFn: actions.jumpToImage,
      options: { imageIndex: 0 },
    },
    lastImage: {
      commandFn: actions.jumpToImage,
      options: { imageIndex: -1 },
    },
    jumpToImage: {
      commandFn: actions.jumpToImage,
    },
    showDownloadViewportModal: {
      commandFn: actions.showDownloadViewportModal,
    },
    storeOriginSlice: {
      commandFn: actions.storeOriginSlice,
    },
    showSAMUploadModal: {
      commandFn: actions.showSAMUploadModal,
    },
    showUnSAMUploadModal: {
      commandFn: actions.showUnSAMUploadModal,
    },
    autoSegmentLiver: {
      commandFn: actions.autoSegmentLiver,
    },
    generateAIReport: {
      commandFn: actions.generateAIReport,
    },
    preloadSAMEmbeddings: {
      commandFn: actions.preloadSAMEmbeddings,
    },
    showPointUnSAMUploadModal: {
      commandFn: actions.showPointUnSAMUploadModal,
    },
    toggleCine: {
      commandFn: actions.toggleCine,
    },
    arrowTextCallback: {
      commandFn: actions.arrowTextCallback,
    },
    setViewportActive: {
      commandFn: actions.setViewportActive,
    },
    setViewportColormap: {
      commandFn: actions.setViewportColormap,
    },
    setViewportForToolConfiguration: {
      commandFn: actions.setViewportForToolConfiguration,
    },
    storePresentation: {
      commandFn: actions.storePresentation,
    },
    attachProtocolViewportDataListener: {
      commandFn: actions.attachProtocolViewportDataListener,
    },
    setViewportPreset: {
      commandFn: actions.setViewportPreset,
    },
    setVolumeRenderingQulaity: {
      commandFn: actions.setVolumeRenderingQulaity,
    },
    shiftVolumeOpacityPoints: {
      commandFn: actions.shiftVolumeOpacityPoints,
    },
    setVolumeLighting: {
      commandFn: actions.setVolumeLighting,
    },
    resetCrosshairs: {
      commandFn: actions.resetCrosshairs,
    },
    toggleSynchronizer: {
      commandFn: actions.toggleSynchronizer,
    },
    updateVolumeData: {
      commandFn: actions.updateVolumeData,
    },
    toggleEnabledDisabledToolbar: {
      commandFn: actions.toggleEnabledDisabledToolbar,
    },
    toggleActiveDisabledToolbar: {
      commandFn: actions.toggleActiveDisabledToolbar,
    },
    updateStoredPositionPresentation: {
      commandFn: actions.updateStoredPositionPresentation,
    },
    updateStoredSegmentationPresentation: {
      commandFn: actions.updateStoredSegmentationPresentation,
    },
    createLabelmapForViewport: {
      commandFn: actions.createLabelmapForViewport,
    },
    setActiveSegmentation: {
      commandFn: actions.setActiveSegmentation,
    },
    addSegment: {
      commandFn: actions.addSegmentCommand,
    },
    setActiveSegmentAndCenter: {
      commandFn: actions.setActiveSegmentAndCenterCommand,
    },
    toggleSegmentVisibility: {
      commandFn: actions.toggleSegmentVisibilityCommand,
    },
    toggleSegmentLock: {
      commandFn: actions.toggleSegmentLockCommand,
    },
    toggleSegmentationVisibility: {
      commandFn: actions.toggleSegmentationVisibilityCommand,
    },
    downloadSegmentation: {
      commandFn: actions.downloadSegmentationCommand,
    },
    storeSegmentation: {
      commandFn: actions.storeSegmentationCommand,
    },
    downloadRTSS: {
      commandFn: actions.downloadRTSSCommand,
    },
    setSegmentationStyle: {
      commandFn: actions.setSegmentationStyleCommand,
    },
    deleteSegment: {
      commandFn: actions.deleteSegmentCommand,
    },
    deleteSegmentation: {
      commandFn: actions.deleteSegmentationCommand,
    },
    removeSegmentationFromViewport: {
      commandFn: actions.removeSegmentationFromViewportCommand,
    },
    toggleRenderInactiveSegmentations: {
      commandFn: actions.toggleRenderInactiveSegmentationsCommand,
    },
    setFillAlpha: {
      commandFn: actions.setFillAlphaCommand,
    },
    setOutlineWidth: {
      commandFn: actions.setOutlineWidthCommand,
    },
    setRenderFill: {
      commandFn: actions.setRenderFillCommand,
    },
    setRenderOutline: {
      commandFn: actions.setRenderOutlineCommand,
    },
    setFillAlphaInactive: {
      commandFn: actions.setFillAlphaInactiveCommand,
    },
    editSegmentLabel: {
      commandFn: actions.editSegmentLabel,
    },
    editSegmentationLabel: {
      commandFn: actions.editSegmentationLabel,
    },
    editSegmentColor: {
      commandFn: actions.editSegmentColor,
    },
    getRenderInactiveSegmentations: {
      commandFn: actions.getRenderInactiveSegmentations,
    },
    deleteActiveAnnotation: {
      commandFn: actions.deleteActiveAnnotation,
    },
    setDisplaySetsForViewports: actions.setDisplaySetsForViewports,
    undo: actions.undo,
    redo: actions.redo,
    interpolateLabelmap: actions.interpolateLabelmap,
    runSegmentBidirectional: actions.runSegmentBidirectional,
    downloadCSVSegmentationReport: actions.downloadCSVSegmentationReport,
    toggleSegmentPreviewEdit: actions.toggleSegmentPreviewEdit,
    toggleSegmentSelect: actions.toggleSegmentSelect,
    acceptPreview: actions.acceptPreview,
    rejectPreview: actions.rejectPreview,
    toggleUseCenterSegmentIndex: actions.toggleUseCenterSegmentIndex,
    toggleLabelmapAssist: actions.toggleLabelmapAssist,
    interpolateScrollForMarkerLabelmap: actions.interpolateScrollForMarkerLabelmap,
    clearMarkersForMarkerLabelmap: actions.clearMarkersForMarkerLabelmap,
    clearSimpleMarkersForMarkerLabelmap: actions.clearSimpleMarkersForMarkerLabelmap,
    setBrushSize: actions.setBrushSize,
    setThresholdRange: actions.setThresholdRange,
    increaseBrushSize: actions.increaseBrushSize,
    decreaseBrushSize: actions.decreaseBrushSize,
    addNewSegment: actions.addNewSegment,
    loadSegmentationDisplaySetsForViewport: actions.loadSegmentationDisplaySetsForViewport,
    setViewportOrientation: actions.setViewportOrientation,
    hydrateSecondaryDisplaySet: actions.hydrateSecondaryDisplaySet,
    getVolumeIdForDisplaySet: actions.getVolumeIdForDisplaySet,
  };

  // ── 测试：原生 Three.js overlay（使用 npm THREE）──
  (window as any).__showMeshTest = () => {
    const old = document.getElementById('mesh3d-native-overlay');
    if (old) { old.remove(); return; }

    // -- 生成测试 mesh --
    const verts: number[][] = [], faces: number[][] = [];
    const cx=220,cy=200,cz=115,rx=50,ry=40,rz=35,ls=25;
    for (let i=0;i<=ls;i++){const lat=Math.PI*(-0.5+i/ls);
      for (let j=0;j<=ls;j++){const lon=2*Math.PI*j/ls;
        verts.push([cx+rx*Math.cos(lat)*Math.cos(lon),cy+ry*Math.cos(lat)*Math.sin(lon),cz+rz*Math.sin(lat)]);}}
    for (let i=0;i<ls;i++){for (let j=0;j<ls;j++){const a=i*(ls+1)+j,b=a+ls+1;faces.push([a,b,a+1]);faces.push([b,b+1,a+1]);}}

    // -- DOM overlay --
    const overlay = document.createElement('div');
    overlay.id = 'mesh3d-native-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;flex-direction:column';
    const titleBar = document.createElement('div');
    titleBar.style.cssText = 'color:#ccc;font:14px sans-serif;margin-bottom:8px;display:flex;justify-content:space-between;width:660px';
    titleBar.innerHTML = '<span>3D Segmentation &mdash; 100 slices / 50.00 cm&sup3;</span><span style="color:#888">drag &middot; scroll zoom</span>';
    const closeBtn = document.createElement('button');
    closeBtn.textContent = 'X'; closeBtn.style.cssText = 'position:absolute;top:8px;right:8px;zIndex:1;background:rgba(0,0,0,.5);color:#fff;border:1px solid rgba(255,255,255,.2);border-radius:4px;padding:4px 10px;cursor:pointer;font-size:14px';
    closeBtn.onclick = () => overlay.remove();
    const canvas = document.createElement('canvas');
    canvas.width = 660; canvas.height = 520;
    canvas.style.cssText = 'border-radius:8px;display:block';
    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'position:relative;border-radius:8px;overflow:hidden';
    wrapper.appendChild(canvas); wrapper.appendChild(closeBtn);
    overlay.appendChild(titleBar); overlay.appendChild(wrapper);
    document.body.appendChild(overlay);

    // -- Three.js (npm) --
    const scene = new THREE.Scene(); scene.background = new THREE.Color(0x1a1a2e);
    const cam = new THREE.PerspectiveCamera(45, 660/520, 0.1, 10000); cam.position.set(300,200,400); cam.lookAt(0,0,0);
    const renderer = new THREE.WebGLRenderer({ canvas, antialias:true, alpha:false, premultipliedAlpha:false });
    renderer.setSize(660,520); renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
    scene.add(new THREE.AmbientLight(0x404060,2.5));
    const sun=new THREE.DirectionalLight(0xffffff,3);sun.position.set(1,1,1);scene.add(sun);
    const fill=new THREE.DirectionalLight(0x88aaff,1.5);fill.position.set(-1,-0.5,-0.5);scene.add(fill);
    const pos:number[]=[], idx:number[]=[];
    let sx=0,sy=0,sz=0; verts.forEach(v=>{sx+=v[0];sy+=v[1];sz+=v[2];});
    const mc=[sx/verts.length,sy/verts.length,sz/verts.length];
    verts.forEach(v=>pos.push(v[0]-mc[0],v[1]-mc[1],v[2]-mc[2]));
    for (const f of faces) if(f.length>=3) idx.push(f[0],f[1],f[2]);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos,3));
    geo.setIndex(idx); geo.computeVertexNormals();
    scene.add(new THREE.Mesh(geo, new THREE.MeshPhongMaterial({color:0x22c55e,specular:0x44ff88,shininess:40,transparent:true,opacity:0.70,side:THREE.DoubleSide})));
    scene.add(new THREE.LineSegments(new THREE.WireframeGeometry(geo), new THREE.LineBasicMaterial({color:0x16a34a,transparent:true,opacity:0.3})));

    const controls = new OrbitControls(cam, renderer.domElement);
    controls.enableDamping=true; controls.dampingFactor=0.08; controls.target.set(0,0,0); controls.update();
    const animate = () => { requestAnimationFrame(animate); controls.update(); renderer.render(scene, cam); };
    animate();
    console.log('[Test] Native Three.js overlay (npm) rendered');
  };

  // ── 测试接口：直接模拟 SAM2 完成后的 3D 切换 + mesh 叠加 ──
  (window as any).__testFullFlow = async (skipBackend = true) => {
    const { cornerstoneViewportService, viewportGridService, uiModalService } = servicesManager.services;
    const activeVpId = viewportGridService.getState().activeViewportId;
    const csVp = cornerstoneViewportService.getCornerstoneViewport(activeVpId) as any;

    // 从后端获取真实 mesh（用已知好的 bbox），skipBackend=true 跳过
    let mesh = null;
    if (!skipBackend) {
    try {
      const sid = (csVp as any)?.getImageIds?.()?.[0]
        ? await (async () => {
            const _vps = viewportGridService.getState().viewports;
            const _dsUID = (_vps.get(activeVpId) as any)?.displaySetInstanceUIDs?.[0];
            const _ds = _dsUID ? (servicesManager.services as any).displaySetService?.getDisplaySetByUID(_dsUID) : null;
            return (_ds as any)?.SeriesInstanceUID;
          })()
        : null;
      if (sid) {
        const sResp = await fetch('http://localhost:8003/session/create', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ series_instance_uid: sid, organ_hint: 'lung_r', prompt_frames: [] }) });
        const sData = await sResp.json();
        if (sData.session_id) {
          const segResp = await fetch(`http://localhost:8003/session/${sData.session_id}/segment`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ key_slice_idx: 100, bbox: [50,80,230,280], organ_hint: 'lung_r', prompt_frames: [], preview_confirmed: true }) });
          const segData = await segResp.json();
          mesh = segData.mesh;
          console.log('[TestFlow] got mesh from backend:', mesh ? `${mesh.vertices.length}v/${mesh.faces.length}f` : 'NULL');
        }
      }
    } catch(e) { console.warn('[TestFlow] backend fetch failed:', e); }
    } // end if (!skipBackend)

    // 如果后端不可用，构造合成 mesh
    if (!mesh?.vertices?.length) {
      console.log('[TestFlow] using synthetic mesh');
      const verts: number[][] = [], faces: number[][] = [];
      const cx=220, cy=200, cz=115, rx=35, ry=30, rz=25, ls=20;
      for (let i=0; i<=ls; i++) { const lat=Math.PI*(-0.5+i/ls);
        for (let j=0; j<=ls; j++) { const lon=2*Math.PI*j/ls;
          verts.push([cx+rx*Math.cos(lat)*Math.cos(lon), cy+ry*Math.cos(lat)*Math.sin(lon), cz+rz*Math.sin(lat)]); }}
      for (let i=0; i<ls; i++) { for (let j=0; j<ls; j++) { const a=i*(ls+1)+j, b=a+ls+1; faces.push([a,b,a+1]); faces.push([b,b+1,a+1]); }}
      mesh = { vertices: verts, faces: faces, dims: [512,512,240] };
    }

    // 切到 only3D
    commandsManager.runCommand('setHangingProtocol', { protocolId: 'only3D', stageIndex: 0 });
    await new Promise(r => setTimeout(r, 1500));

    const renderingEngine = cornerstoneViewportService.getRenderingEngine();
    if (!renderingEngine) return;

    // 找 volume3d 视口
    let vpId: string | null = null;
    for (const [id, vp] of (viewportGridService.getState().viewports as Map<string,any>).entries()) {
      if (vp?.viewportOptions?.viewportType === 'volume3d') { vpId = id; break; }
    }
    if (!vpId) return;

    const renderer = renderingEngine.getRenderer(vpId);
    const { vertices, faces } = mesh;
    const nv = vertices.length, nf = faces.length;
    const pts = new Float32Array(nv * 3);
    // __testFullFlow 中的 mesh 已经是物理坐标（或合成的像素坐标），直接用
    for (let i=0; i<nv; i++) { pts[i*3]=vertices[i][0]; pts[i*3+1]=vertices[i][1]; pts[i*3+2]=vertices[i][2]; }
    const pd = vtkPolyData.newInstance();
    pd.getPoints().setData(pts, 3);  // Float32Array + numComponents
    const ff = new Uint32Array(nf * 4);
    for (let i=0; i<nf; i++) { ff[i*4]=3; ff[i*4+1]=faces[i][0]; ff[i*4+2]=faces[i][1]; ff[i*4+3]=faces[i][2]; }
    pd.getPolys().setData(Uint32Array.from(ff));
    const mapper = vtkMapper.newInstance(); mapper.setInputData(pd);
    const actor = vtkActor.newInstance(); actor.setMapper(mapper);
    actor.getProperty().setColor(0.15,0.85,0.2); actor.getProperty().setOpacity(0.4);
    actor.getProperty().setEdgeVisibility(true); actor.getProperty().setEdgeColor(0.05,0.6,0.1);
    renderer.addActor(actor);
    // 相机自动适配
    try {
      if (typeof (renderer as any).resetCamera === 'function') { (renderer as any).resetCamera(); }
      else { const cam = (renderer as any).getActiveCamera?.(); if (cam) cam.resetClippingRange?.(); }
    } catch {}
    renderingEngine.renderViewport(vpId);
    console.log('[TestFlow] ✅ Mesh added to only3D viewport', nv, 'verts', nf, 'faces');
  };

  return {
    actions,
    definitions,
    defaultContext: 'CORNERSTONE',
  };
}

export default commandsModule;
