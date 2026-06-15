/**
 * 设备性能检测和3D渲染自适应配置
 * 
 * 用途: 根据用户设备GPU性能自动调整3D渲染质量
 * 解决低端设备3D加载失败、卡顿问题
 */

export type DeviceCapability = 'low' | 'medium' | 'high';

interface RenderingConfig {
  volumeRenderingPreset: string;
  blendMode: string;
  preferSizeOverAccuracy: boolean;
  gpuMemoryMB: number;
  targetFrameRate: number;
  useLOD: boolean;
  maxTextureSize: number;
}

/**
 * 检测设备GPU性能等级
 * @returns {DeviceCapability} 'low' | 'medium' | 'high'
 */
export function detectDeviceCapability(): DeviceCapability {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    
    if (!gl) {
      console.warn('[DeviceDetection] WebGL不可用，使用低端配置');
      return 'low';
    }

    // 检测WebGL版本
    const isWebGL2 = gl instanceof WebGL2RenderingContext;
    
    // 获取GPU信息
    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    let renderer = 'Unknown';
    
    if (debugInfo) {
      renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
      console.log('[DeviceDetection] GPU:', renderer);
    }

    // 检测最大纹理尺寸
    const maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    console.log('[DeviceDetection] 最大纹理尺寸:', maxTextureSize);

    // 检测显存（近似）
    const memoryInfo = (gl as any).getExtension('WEBGL_debug_renderer_info');
    
    // 规则1: 低端设备判断（集成显卡）
    const lowEndGPUs = [
      'Intel HD Graphics',
      'Intel UHD Graphics 620',
      'Intel UHD Graphics 630',
      'Intel Iris',
      'Mali-G',
      'Adreno',
    ];
    
    if (lowEndGPUs.some(gpu => renderer.includes(gpu))) {
      console.log('[DeviceDetection] 检测到低端集成显卡');
      return 'low';
    }

    // 规则2: 高端设备判断（独立显卡）
    const highEndGPUs = [
      'NVIDIA GeForce RTX',
      'NVIDIA GeForce GTX 16',
      'NVIDIA GeForce GTX 20',
      'NVIDIA GeForce GTX 30',
      'AMD Radeon RX',
      'AMD Radeon Pro',
    ];
    
    if (highEndGPUs.some(gpu => renderer.includes(gpu))) {
      console.log('[DeviceDetection] 检测到高端独立显卡');
      return 'high';
    }

    // 规则3: 基于纹理大小和WebGL版本推断
    if (!isWebGL2 || maxTextureSize < 8192) {
      console.log('[DeviceDetection] WebGL1或纹理支持较弱');
      return 'low';
    }

    if (maxTextureSize >= 16384) {
      console.log('[DeviceDetection] 大纹理支持，判定为中端以上');
      return 'medium';
    }

    // 默认中端
    console.log('[DeviceDetection] 默认判定为中端设备');
    return 'medium';
    
  } catch (error) {
    console.error('[DeviceDetection] 检测失败:', error);
    return 'low';  // 出错时保守处理
  }
}

/**
 * 根据设备性能生成3D渲染配置
 * @param capability 设备性能等级
 * @returns {RenderingConfig} 渲染配置对象
 */
export function apply3DRenderingConfig(capability: DeviceCapability): RenderingConfig {
  const configs: Record<DeviceCapability, RenderingConfig> = {
    low: {
      volumeRenderingPreset: 'CT-Bone',  // 简单预设，计算量最小
      blendMode: 'MAXIMUM_INTENSITY_PROJECTION',  // MIP模式，性能最优
      preferSizeOverAccuracy: true,  // 牺牲精度保证流畅度
      gpuMemoryMB: 128,  // 严格限制显存使用
      targetFrameRate: 15,  // 降低帧率目标
      useLOD: true,  // 启用LOD分层渲染
      maxTextureSize: 512,  // 限制纹理尺寸
    },
    
    medium: {
      volumeRenderingPreset: 'CT-Chest-Contrast-Enhanced',
      blendMode: 'AVERAGE_INTENSITY_PROJECTION',  // AIP模式，性能和质量平衡
      preferSizeOverAccuracy: false,
      gpuMemoryMB: 512,
      targetFrameRate: 30,
      useLOD: true,
      maxTextureSize: 1024,
    },
    
    high: {
      volumeRenderingPreset: 'Custom',
      blendMode: 'COMPOSITE_AVERAGE',  // 完整体绘制，质量最高
      preferSizeOverAccuracy: false,
      gpuMemoryMB: 2048,
      targetFrameRate: 60,
      useLOD: false,  // 高端设备不需要LOD
      maxTextureSize: 2048,
    }
  };

  const config = configs[capability];
  console.log(`[DeviceDetection] 应用${capability}端配置:`, config);
  
  return config;
}

/**
 * 检测设备内存大小
 * @returns {number} 内存大小(GB)，检测失败返回0
 */
export function detectDeviceMemory(): number {
  try {
    // @ts-ignore - navigator.deviceMemory 是实验性API
    const memory = navigator.deviceMemory || 0;
    console.log(`[DeviceDetection] 设备内存: ${memory}GB`);
    return memory;
  } catch (error) {
    console.warn('[DeviceDetection] 无法检测内存大小');
    return 0;
  }
}

/**
 * 综合评分（0-100），用于动态调整
 * @returns {number} 性能分数
 */
export function calculatePerformanceScore(): number {
  const capability = detectDeviceCapability();
  const memory = detectDeviceMemory();
  
  let score = 0;
  
  // GPU等级得分
  switch (capability) {
    case 'high':
      score += 60;
      break;
    case 'medium':
      score += 40;
      break;
    case 'low':
      score += 20;
      break;
  }
  
  // 内存加分
  if (memory >= 16) {
    score += 20;
  } else if (memory >= 8) {
    score += 10;
  } else if (memory >= 4) {
    score += 5;
  }
  
  // 浏览器加分（Chrome/Edge性能最优）
  const userAgent = navigator.userAgent;
  if (userAgent.includes('Chrome') && !userAgent.includes('Edg')) {
    score += 10;
  } else if (userAgent.includes('Edg')) {
    score += 10;
  } else if (userAgent.includes('Firefox')) {
    score += 5;
  }
  
  // WebGL2支持加分
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2');
  if (gl) {
    score += 10;
  }
  
  console.log(`[DeviceDetection] 性能综合评分: ${score}/100`);
  return Math.min(score, 100);
}

/**
 * 显示性能警告（如果设备性能不足）
 */
export function showPerformanceWarning(capability: DeviceCapability) {
  if (capability === 'low') {
    const message = `
      检测到您的设备GPU性能较低，3D渲染可能会受限。
      建议：
      1. 关闭其他占用GPU的程序
      2. 启用浏览器硬件加速
      3. 降低浏览器缩放比例到100%
      4. 使用"MIP模式"查看3D图像（已自动启用）
    `;
    
    console.warn('[DeviceDetection]', message);
    
    // 可选：弹出通知
    // uiNotificationService.show({
    //   title: '性能提示',
    //   message,
    //   type: 'warning',
    //   duration: 5000
    // });
  }
}

/**
 * 导出设备信息用于调试
 */
export function getDeviceInfo() {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
  
  if (!gl) {
    return { error: 'WebGL不可用' };
  }
  
  const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
  
  return {
    capability: detectDeviceCapability(),
    performanceScore: calculatePerformanceScore(),
    memory: detectDeviceMemory(),
    webglVersion: gl instanceof WebGL2RenderingContext ? 'WebGL 2.0' : 'WebGL 1.0',
    vendor: debugInfo ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) : 'Unknown',
    renderer: debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : 'Unknown',
    maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
    maxViewportDims: gl.getParameter(gl.MAX_VIEWPORT_DIMS),
    userAgent: navigator.userAgent,
  };
}

// 示例用法
if (typeof window !== 'undefined') {
  // 在浏览器环境中自动执行检测
  window.onload = () => {
    const info = getDeviceInfo();
    console.log('[设备信息]', JSON.stringify(info, null, 2));
  };
}
