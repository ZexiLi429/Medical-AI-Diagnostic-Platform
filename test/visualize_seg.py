"""
visualize_seg.py — 把 /segment_mask 结果叠加到 CT 原图上可视化
Usage: python visualize_seg.py
"""

import requests, json, base64, io, numpy as np
from PIL import Image, ImageDraw, ImageFont
import pydicom
from io import BytesIO

TOTALSEG = "http://localhost:8004"
ORTHANC = "http://localhost:8042"

# KiTS-1059
UID = "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681"

print("Getting label map for KiTS-1059 (may take ~6 min) ...")
r = requests.post(f"{TOTALSEG}/segment_mask",
                  json={"series_instance_uid": UID}, timeout=600)
data = r.json()
buf = io.BytesIO(base64.b64decode(data["data_b64"]))
buf.seek(0)
pred = np.load(buf)
print(f"Label map: {pred.shape}, labels: {data['labels'][:10]}...")

# 从 Orthanc 取几层 CT 原图
print("Fetching CT slices from Orthanc ...")
# 找到 series
all_s = requests.get(f"{ORTHANC}/series", timeout=10).json()
sid = None
for s in all_s:
    info = requests.get(f"{ORTHANC}/series/{s}", timeout=10).json()
    if info.get("MainDicomTags", {}).get("SeriesInstanceUID") == UID:
        sid = s
        break

instances = requests.get(f"{ORTHANC}/series/{sid}", timeout=10).json()["Instances"]
print(f"  {len(instances)} slices")

# 取中间几层
slice_indices = [len(instances)//4, len(instances)//2, 3*len(instances)//4]
n_slices = pred.shape[0]
seg_indices = [min(i * n_slices // len(instances), n_slices-1) for i in slice_indices]

out_dir = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results/"
colors = {
    1: (255, 80, 80),    # red - kidney right?
    2: (80, 80, 255),    # blue - kidney left?
    5: (80, 200, 80),    # green - liver
    12: (255, 200, 50),  # gold - spleen
}

for si, seg_i in zip(slice_indices, seg_indices):
    # CT slice
    inst_id = instances[si]
    r = requests.get(f"{ORTHANC}/instances/{inst_id}/file", timeout=30)
    ds = pydicom.dcmread(BytesIO(r.content))
    ct = ds.pixel_array.astype(np.float32)

    # 归一化到 0-255
    ct = np.clip((ct - ct.min()) / (ct.max() - ct.min()) * 255, 0, 255).astype(np.uint8)
    ct_rgb = np.stack([ct, ct, ct], axis=-1)

    # 分割掩码 (可能需要重采样到 CT 尺寸)
    seg = pred[seg_i]
    if seg.shape != ct.shape:
        from scipy.ndimage import zoom
        z = [ct.shape[i]/seg.shape[i] for i in range(2)]
        seg = zoom(seg.astype(float), z, order=0).astype(seg.dtype)

    # 叠加
    for label, color in colors.items():
        mask = (seg == label)
        alpha = 0.4
        ct_rgb[mask] = (ct_rgb[mask] * (1-alpha) + np.array(color) * alpha).astype(np.uint8)

    # 保存
    img = Image.fromarray(ct_rgb)
    out = f"{out_dir}seg_overlay_1059_slice{si}.png"
    img.save(out)
    print(f"Saved: {out}")

print("Done — check experiment_results/ for overlay images")
