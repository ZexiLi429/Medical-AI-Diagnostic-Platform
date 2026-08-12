"""
Analyze Agent — 收集分割数据，计算结构化指标。
纯计算，不依赖外部 API。
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import numpy as np


@dataclass
class LesionMetrics:
    """结构化病灶指标"""
    # 体积
    volume_mm3: float = 0.0
    volume_cm3: float = 0.0

    # 面积
    total_area_mm2: float = 0.0       # 所有切片累计面积
    max_slice_area_mm2: float = 0.0   # 最大单切片面积
    max_slice_area_cm2: float = 0.0

    # 切片统计
    total_slices_in_series: int = 0
    slices_with_lesion: int = 0
    lesion_slice_range: tuple = (0, 0)  # (min_slice, max_slice)

    # 位置与尺寸
    organ_hint: str = ""
    pixel_bbox: tuple = (0, 0, 0, 0)    # (x1,y1,x2,y2) px
    physical_size_mm: tuple = (0.0, 0.0)  # (width, height) mm

    # 形态
    sphericity: float = 0.0        # 球形度 (0-1, 1=完美球)
    mean_intensity_hu: Optional[float] = None

    # 像素间距
    pixel_spacing: tuple = (1.0, 1.0)
    slice_thickness: float = 1.0


class AnalyzeAgent:
    """分割结果 → 结构化指标"""

    def run(
        self,
        masks_per_slice: List[Dict[str, Any]],
        pixel_spacing: List[float],
        slice_thickness: float,
        total_slices: int,
        organ_hint: str = "",
        bbox: Optional[List[int]] = None,
        intensity_stats: Optional[Dict[str, float]] = None,
    ) -> LesionMetrics:
        m = LesionMetrics()

        # — 基础参数 —
        m.pixel_spacing = (pixel_spacing[0], pixel_spacing[1])
        m.slice_thickness = slice_thickness
        m.total_slices_in_series = total_slices
        m.organ_hint = organ_hint or "unspecified"

        # — 切片统计 —
        slice_indices = [s["slice_idx"] for s in masks_per_slice if "slice_idx" in s]
        m.slices_with_lesion = len(slice_indices)
        if slice_indices:
            m.lesion_slice_range = (min(slice_indices), max(slice_indices))

        # — Bbox 物理尺寸 —
        if bbox and len(bbox) == 4:
            m.pixel_bbox = tuple(bbox)
            w_px = bbox[2] - bbox[0]
            h_px = bbox[3] - bbox[1]
            m.physical_size_mm = (
                round(w_px * pixel_spacing[0], 1),
                round(h_px * pixel_spacing[1], 1),
            )

        # — 面积计算 —
        px_area_per_slice = []
        for s in masks_per_slice:
            px = s.get("pixel_count") or (s.get("rle", {}).get("pixel_count", 0))
            area_mm2 = px * pixel_spacing[0] * pixel_spacing[1]
            px_area_per_slice.append(area_mm2)

        if px_area_per_slice:
            m.max_slice_area_mm2 = max(px_area_per_slice)
            m.max_slice_area_cm2 = round(m.max_slice_area_mm2 / 100, 2)
            m.total_area_mm2 = sum(px_area_per_slice)

        # — 体积 —
        voxel_vol_mm3 = pixel_spacing[0] * pixel_spacing[1] * slice_thickness
        total_px = sum(
            s.get("pixel_count") or (s.get("rle", {}).get("pixel_count", 0))
            for s in masks_per_slice
        )
        m.volume_mm3 = round(total_px * voxel_vol_mm3, 2)
        m.volume_cm3 = round(m.volume_mm3 / 1000, 2)

        # — 球形度 —
        if m.volume_mm3 > 0 and m.max_slice_area_mm2 > 0:
            # 等效球半径 r = (3V/4π)^(1/3)
            r = (3 * m.volume_mm3 / (4 * np.pi)) ** (1 / 3)
            sphere_x_area = np.pi * r * r
            m.sphericity = round(min(sphere_x_area / max(m.max_slice_area_mm2, 1e-6), 1.0), 3)

        # — CT 密度 —
        if intensity_stats:
            m.mean_intensity_hu = intensity_stats.get("mean")

        return m


def run_analyze(seg_data: dict, ct_params: dict, bbox: Optional[list] = None) -> dict:
    """快捷入口，返回 dict"""
    agent = AnalyzeAgent()
    metrics = agent.run(
        masks_per_slice=seg_data.get("masks_per_slice", []),
        pixel_spacing=ct_params.get("pixel_spacing", [1.0, 1.0]),
        slice_thickness=ct_params.get("slice_thickness", 1.0),
        total_slices=seg_data.get("total_slices", 0),
        organ_hint=ct_params.get("organ_hint", ""),
        bbox=bbox,
        intensity_stats=ct_params.get("intensity_stats"),
    )
    return asdict(metrics)
