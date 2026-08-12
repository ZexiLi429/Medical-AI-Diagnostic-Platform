"""
Evaluate Agent — Validates segmentation metrics and report consistency.
Pure rule engine, no external API dependencies.
"""
from typing import Dict, Any, List
import math


class EvaluateAgent:
    """Validates segmentation metrics for numerical and medical plausibility."""

    ORGAN_VOLUME_RANGES = {
        "liver": (0.01, 5000),
        "lung": (0.01, 2000),
        "kidney": (0.01, 3000),
        "brain": (0.01, 500),
        "pancreas": (0.01, 500),
        "spleen": (0.01, 2000),
        "thyroid": (0.01, 200),
        "bone": (0.01, 5000),
        "default": (0.01, 10000),
    }

    def validate(
        self,
        metrics: Dict[str, Any],
        seg_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        vol_cm3 = float(metrics.get("volume_cm3", 0))
        area_cm2 = float(metrics.get("max_slice_area_cm2", 0))
        slices = int(metrics.get("slices_with_lesion", 0))
        total_slices = int(metrics.get("total_slices_in_series", 0))
        sphericity = float(metrics.get("sphericity", 0))
        spacing = metrics.get("pixel_spacing", (1.0, 1.0))
        thickness = float(metrics.get("slice_thickness", 1.0))
        organ = str(metrics.get("organ_hint", "")).lower()

        # 1. Volume consistency: sum(slice_area x thickness) ~ reported volume
        masks = seg_result.get("masks_per_slice", [])
        total_px = sum(
            s.get("pixel_count") or (s.get("rle", {}).get("pixel_count", 0))
            for s in masks
        )
        voxel_vol = spacing[0] * spacing[1] * thickness
        expected_vol = total_px * voxel_vol / 1000  # mm3 -> cm3
        vol_diff = abs(vol_cm3 - expected_vol) / max(expected_vol, 1e-6)

        checks.append({
            "id": "volume_consistency",
            "pass": vol_diff < 0.05,
            "expected_cm3": round(expected_vol, 2),
            "actual_cm3": vol_cm3,
            "diff_pct": round(vol_diff * 100, 1),
            "msg": f"Volume consistency: {vol_diff*100:.1f}% deviation"
            if vol_diff < 0.05
            else f"Volume deviation {vol_diff*100:.1f}% > 5%, verify calculation",
        })

        # 2. Volume within organ-specific expected range
        rng = self.ORGAN_VOLUME_RANGES.get(
            organ, self.ORGAN_VOLUME_RANGES["default"]
        )
        vol_in_range = rng[0] <= vol_cm3 <= rng[1]
        checks.append({
            "id": "volume_range",
            "pass": vol_in_range,
            "range_cm3": rng,
            "msg": f"Volume {vol_cm3:.1f} cm3 within {organ} expected range {rng}"
            if vol_in_range
            else f"Volume {vol_cm3:.1f} cm3 outside {organ} reference range {rng}",
        })

        # 3. Slice proportion is reasonable
        if total_slices > 0:
            ratio = slices / total_slices
            checks.append({
                "id": "slice_ratio",
                "pass": 0.005 <= ratio <= 0.95,
                "ratio": round(ratio, 3),
                "msg": f"Lesion spans {ratio*100:.1f}% of total slices",
            })

        # 4. Sphericity within valid range
        checks.append({
            "id": "sphericity",
            "pass": 0 <= sphericity <= 1.0,
            "value": sphericity,
            "msg": f"Sphericity {sphericity:.2f}"
            + (" (near-spherical)" if sphericity > 0.8 else ""),
        })

        # 5. Volume-to-area ratio is plausible
        if vol_cm3 > 0 and area_cm2 > 0:
            r_eff = math.sqrt(area_cm2 / math.pi)  # cm
            min_vol = (4 / 3) * math.pi * (r_eff ** 3)
            ratio_ok = vol_cm3 >= min_vol * 0.3
            checks.append({
                "id": "volume_area_ratio",
                "pass": ratio_ok,
                "min_expected_vol": round(min_vol, 2),
                "msg": "Volume-to-area ratio is plausible" if ratio_ok
                else f"Volume {vol_cm3:.1f} cm3 appears low relative to max area {area_cm2:.1f} cm2",
            })

        # 6. Slice thickness is plausible
        if thickness < 0.1 or thickness > 20:
            warnings.append({
                "id": "slice_thickness",
                "msg": f"Slice thickness {thickness} mm is unusual (typical range 0.5-10 mm)",
            })

        # Summary
        all_pass = all(c["pass"] for c in checks)
        critical_fails = [c for c in checks if not c["pass"] and c["id"] in (
            "volume_consistency", "volume_range"
        )]

        return {
            "all_pass": all_pass,
            "checks": checks,
            "warnings": warnings,
            "critical_fails": len(critical_fails),
        }


def run_evaluate(metrics, seg_result):
    """Convenience entry point."""
    agent = EvaluateAgent()
    return agent.validate(metrics, seg_result)
