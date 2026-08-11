"""
experiment_runner.py — 实验数据自动采集
跑 5 组 KiTS 数据，自动记录 Table II + Section 4.2 所需全部数据

Usage: python experiment_runner.py
"""

import requests
import time
import json
import csv
import os
from datetime import datetime

# ═══════════════════════════════
# CONFIG
# ═══════════════════════════════
TOTALSEG_URL = "http://localhost:8004"
OUTPUT_DIR = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 从 Orthanc 扫描到的真实病例 ──
CASES = [
    {
        "name": "KiTS-53",
        "uid": "1.3.6.1.4.1.14519.5.2.1.6919.4624.234938093025998868310622825320",
        "slices": 53,
        "desc": "late phase, very small (matches kits64_gt.npy)"
    },
    {
        "name": "KiTS-389",
        "uid": "1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379",
        "slices": 389,
        "desc": "arterial phase, small"
    },
    {
        "name": "KiTS-738",
        "uid": "1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368",
        "slices": 738,
        "desc": "arterial phase, medium"
    },
    {
        "name": "KiTS-987",
        "uid": "1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497",
        "slices": 987,
        "desc": "arterial phase, large"
    },
    {
        "name": "KiTS-1059",
        "uid": "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681",
        "slices": 1059,
        "desc": "arterial phase, very large"
    },
]

# 关注器官
ORGANS = ["liver", "spleen", "kidney_right", "kidney_left",
          "lung_right", "lung_left", "stomach", "pancreas",
          "aorta", "heart_myocardium"]

# 参考区间 (mL) — Wasserthal 2023
REF = {
    "liver": (1200,1800), "spleen": (80,300),
    "kidney_right": (100,220), "kidney_left": (100,220),
    "lung_right": (800,2000), "lung_left": (700,1800),
    "stomach": (80,400), "pancreas": (50,120),
    "heart_myocardium": (180,350),
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def run_one(case):
    """Run /segment_3d on one case, return results dict."""
    log(f"▶ {case['name']} ({case['slices']} slices, {case['desc']})")

    result = {
        "case": case["name"],
        "slices": case["slices"],
        "desc": case["desc"],
        "timestamp": datetime.now().isoformat(),
        "status": "error",
    }

    # ── Call API ──
    t0 = time.time()
    try:
        resp = requests.post(
            f"{TOTALSEG_URL}/segment_3d",
            json={"series_instance_uid": case["uid"]},
            timeout=7200,  # 2 hours max
        )
        wall_time = time.time() - t0
    except requests.exceptions.Timeout:
        result["error"] = "Timeout (>2h)"
        log(f"  ✗ TIMEOUT")
        return result
    except Exception as e:
        result["error"] = str(e)
        log(f"  ✗ {e}")
        return result

    if resp.status_code != 200:
        result["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        log(f"  ✗ {result['error']}")
        return result

    data = resp.json()

    # ── Timing ──
    result["status"] = "ok"
    result["T_wall_seconds"] = round(wall_time, 1)
    result["T_wall_minutes"] = round(wall_time / 60, 1)
    result["T_infer_seconds"] = round(data.get("elapsed_s", 0), 1)  # API reported
    result["total_organs"] = data.get("total_organs", 0)

    # ── Was downsampling triggered? (infer from N > 400) ──
    result["downsampled"] = case["slices"] > 400
    if result["downsampled"]:
        result["downsample_factor"] = round(400 / case["slices"], 3)

    # ── Organ volumes from meshes ──
    volumes = {}
    for m in data.get("meshes", []):
        name = m.get("name", "")
        vol = m.get("volume_cm3", 0)
        if name in ORGANS:
            volumes[name] = round(vol, 2)
    result["volumes_ml"] = volumes

    # ── Volume sanity check ──
    warnings = []
    for org, vol in volumes.items():
        if org in REF:
            lo, hi = REF[org]
            if vol < lo:
                warnings.append(f"{org}={vol}mL < ref [{lo},{hi}]")
            elif vol > hi:
                warnings.append(f"{org}={vol}mL > ref [{lo},{hi}]")
    result["warnings"] = warnings

    # ── Lesion info ──
    result["lesions"] = data.get("available_lesions", [])

    log(f"  ✓ {wall_time/60:.1f} min | {result['total_organs']} organs | "
        f"warnings={len(warnings)} | lesions={result['lesions']}")

    return result


def main():
    log("=" * 60)
    log("MISCADA Experiment Runner")
    log(f"API: {TOTALSEG_URL}")
    log(f"Cases: {len(CASES)}")
    log("=" * 60)

    all_results = []
    for i, case in enumerate(CASES):
        res = run_one(case)
        all_results.append(res)

        # Save intermediate after each case (safety)
        tmp = os.path.join(OUTPUT_DIR, f"intermediate_{i+1}of{len(CASES)}.json")
        with open(tmp, "w") as f:
            json.dump(all_results, f, indent=2)
        log(f"  [saved {tmp}]")

        time.sleep(10)  # cooldown

    # ═══════════════════════════════
    # FINAL OUTPUTS
    # ═══════════════════════════════

    # ── Full JSON ──
    json_path = os.path.join(OUTPUT_DIR, "experiment_full.json")
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)
    log(f"\nSaved: {json_path}")

    # ── Table II: Timing ──
    t2 = os.path.join(OUTPUT_DIR, "table_II_timing.csv")
    with open(t2, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Case", "Slices", "Downsampled", "T_wall(min)", "T_infer(s)",
                    "Organs", "Lesions", "Warnings"])
        for r in all_results:
            w.writerow([
                r["case"], r["slices"],
                "YES" if r.get("downsampled") else "no",
                r.get("T_wall_minutes", ""),
                r.get("T_infer_seconds", ""),
                r.get("total_organs", ""),
                ";".join(r.get("lesions", [])),
                len(r.get("warnings", [])),
            ])
    log(f"Saved: {t2}")

    # ── Section 4.2: Volumes ──
    vp = os.path.join(OUTPUT_DIR, "section_4_2_volumes.csv")
    with open(vp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Case", "Slices"] + ORGANS + ["Warnings"])
        for r in all_results:
            vols = r.get("volumes_ml", {})
            w.writerow(
                [r["case"], r["slices"]] +
                [vols.get(o, "-") for o in ORGANS] +
                ["; ".join(r.get("warnings", []))]
            )
    log(f"Saved: {vp}")

    # ── Print summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in all_results:
        if r["status"] == "ok":
            print(f"  {r['case']:18s} | {r['slices']:4d} slices | "
                  f"{r['T_wall_minutes']:5.1f} min | "
                  f"organs={r['total_organs']:2d} | "
                  f"warnings={len(r.get('warnings',[]))}")
        else:
            print(f"  {r['case']:18s} | ✗ FAILED: {r.get('error','?')[:60]}")

    print(f"\nOutput: {OUTPUT_DIR}/")
    log("DONE")


if __name__ == "__main__":
    main()
