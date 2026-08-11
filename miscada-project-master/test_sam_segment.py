"""
直接测试 LiteMedSAM /segment_dicom — 验证 SAM 真的产出了不同的分割结果
用法: python test_sam_segment.py <SOPInstanceUID> [x1 y1 x2 y2]
"""
import sys
import requests
import numpy as np
from PIL import Image
import io

ORTHANC_URL = "http://localhost:8042"
LITEMED_URL = "http://localhost:8002"

sop_uid = sys.argv[1] if len(sys.argv) > 1 else None
if not sop_uid:
    print("用法: python test_sam_segment.py <SOPInstanceUID> [x1 y1 x2 y2]")
    print("SOPInstanceUID 可以从 OHIF 的 imageId 中获取")
    sys.exit(1)

# 默认 bbox（用户的刷子 bbox）
bbox = [int(x) for x in sys.argv[2:6]] if len(sys.argv) >= 6 else [98, 145, 272, 343]
print(f"Testing with SOPInstanceUID={sop_uid}, bbox={bbox}")

# 1. 检查 LiteMedSAM 健康状态
try:
    h = requests.get(f"{LITEMED_URL}/health", timeout=5)
    print(f"LiteMedSAM health: {h.json()}")
except Exception as e:
    print(f"ERROR: LiteMedSAM not reachable: {e}")
    sys.exit(1)

# 2. 获取原始 DICOM 图像（从 Orthanc rendered）
try:
    find = requests.post(f"{ORTHANC_URL}/tools/find", json={
        "Level": "Instance", "Query": {"SOPInstanceUID": sop_uid}
    }, timeout=10)
    find.raise_for_status()
    ids = find.json()
    if not ids:
        print("ERROR: SOPInstanceUID not found in Orthanc")
        sys.exit(1)
    orthanc_id = ids[0]
    print(f"Orthanc ID: {orthanc_id}")

    img_resp = requests.get(f"{ORTHANC_URL}/instances/{orthanc_id}/rendered",
                           params={"quality": 100}, timeout=30)
    img_np = np.array(Image.open(io.BytesIO(img_resp.content)).convert("RGB"))
    print(f"DICOM image size: {img_np.shape}")

    # 保存原始图
    Image.fromarray(img_np).save("test_original.png")
    print("Saved: test_original.png")

    # 在原始图上画 bbox
    import cv2
    vis = img_np.copy()
    cv2.rectangle(vis, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
    Image.fromarray(vis).save("test_original_with_bbox.png")
    print("Saved: test_original_with_bbox.png")
except Exception as e:
    print(f"ERROR getting DICOM: {e}")
    sys.exit(1)

# 3. 调用 /segment_dicom
print(f"\nCalling /segment_dicom ...")
try:
    seg_resp = requests.post(f"{LITEMED_URL}/segment_dicom", json={
        "sop_instance_uid": sop_uid,
        "bbox": bbox,
        "orthanc_url": ORTHANC_URL,
        "orthanc_user": "",
        "orthanc_password": ""
    }, timeout=60)
    seg_resp.raise_for_status()
    data = seg_resp.json()
    print(f"Response: success={data.get('success')}")
    print(f"Volume: {data.get('volume_mm3')} mm²")
    print(f"Confidence: {data.get('confidence')}")
    print(f"Pixel spacing: {data.get('pixel_spacing')}")
    
    rle = data.get('rle')
    if rle:
        # 解码 RLE
        counts = rle['counts']
        starts_with = rle['starts_with']
        w, h = rle['width'], rle['height']
        total = w * h
        mask_flat = np.zeros(total, dtype=np.uint8)
        idx = 0
        cur = starts_with
        for cnt in counts:
            if cur == 1:
                mask_flat[idx:idx+cnt] = 1
            idx += cnt
            cur = 1 - cur
        mask = mask_flat.reshape((h, w))
        
        pixel_count = int(mask.sum())
        print(f"RLE mask size: {w}x{h}, pixels={pixel_count}")
        print(f"Bbox area: {bbox[2]-bbox[0]}x{bbox[3]-bbox[1]} = {(bbox[2]-bbox[0])*(bbox[3]-bbox[1])} pixels")
        print(f"SAM/Bbox ratio: {pixel_count / ((bbox[2]-bbox[0])*(bbox[3]-bbox[1])):.2%}")
        
        if pixel_count == 0:
            print("⚠️  SAM returned EMPTY mask!")
        elif pixel_count == (bbox[2]-bbox[0])*(bbox[3]-bbox[1]):
            print("⚠️  SAM returned FULL bbox mask (no actual segmentation)!")
        else:
            print(f"✅ SAM mask differs from bbox ({pixel_count} vs {(bbox[2]-bbox[0])*(bbox[3]-bbox[1])})")
        
        # 叠加 mask 到原图
        overlay = img_np.copy()
        overlay[mask > 0] = [255, 80, 80]  # 红色叠加
        blended = cv2.addWeighted(img_np, 0.5, overlay, 0.5, 0)
        # 画轮廓
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(blended, cnts, -1, (0, 255, 0), 2)
        Image.fromarray(blended).save("test_sam_result.png")
        print("Saved: test_sam_result.png (green=contour, red=fill)")
        
        # 单独保存 mask
        Image.fromarray(mask * 255).save("test_sam_mask.png")
        print("Saved: test_sam_mask.png")
    else:
        print("ERROR: No RLE in response")
except Exception as e:
    print(f"ERROR calling /segment_dicom: {e}")
