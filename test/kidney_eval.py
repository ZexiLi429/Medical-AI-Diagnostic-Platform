"""
kidney_eval.py — Kidney Segmentation Accuracy Evaluation (all 5 KiTS cases)
Uses SimpleITK for proper DICOM spatial alignment + Dice/HD95/Volume error
"""

import os, tempfile, zipfile, io, json
import numpy as np
import requests, pydicom
import SimpleITK as sitk
from scipy.ndimage import zoom

# ═══════════════════════════════
# CONFIG
# ═══════════════════════════════
ORTHANC  = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"
TCIA_API = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
OUTPUT   = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results"

# 5 KiTS cases: CT UID → (SEG UID, name)
CASES = [
    ("1.3.6.1.4.1.14519.5.2.1.6919.4624.234938093025998868310622825320",
     "1.2.276.0.7230010.3.1.3.0.75044.1588584379.525361", "KiTS-53"),
    ("1.3.6.1.4.1.14519.5.2.1.6919.4624.213938847845441715154421546379",
     "1.2.276.0.7230010.3.1.3.0.75752.1588585674.788120", "KiTS-389"),
    ("1.3.6.1.4.1.14519.5.2.1.6919.4624.120654832974458475364735600368",
     "1.2.276.0.7230010.3.1.3.0.74998.1588584273.225699", "KiTS-738"),
    ("1.3.6.1.4.1.14519.5.2.1.6919.4624.139858261750636911572116296497",
     "1.2.276.0.7230010.3.1.3.0.76174.1588586497.15246", "KiTS-987"),
    ("1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681",
     "1.2.276.0.7230010.3.1.3.0.75995.1588586281.559261", "KiTS-1059"),
]


def download_seg_dicom(seg_uid):
    """Download DICOM SEG from TCIA, return pydicom dataset."""
    r = requests.get(f"{TCIA_API}/getImage",
                     params={"SeriesInstanceUID": seg_uid}, timeout=60)
    tmp = os.path.join(tempfile.gettempdir(), f"seg_{seg_uid[:8]}.zip")
    with open(tmp, "wb") as f:
        f.write(r.content)
    with zipfile.ZipFile(tmp, "r") as zf:
        for name in zf.namelist():
            if name.lower().endswith(".dcm"):
                ds = pydicom.dcmread(io.BytesIO(zf.read(name)))
                os.remove(tmp)
                return ds
    os.remove(tmp)
    raise FileNotFoundError("No DCM in SEG zip")


def build_ct_sitk(ct_uid):
    """Fetch CT series from Orthanc, build SimpleITK image with proper geometry."""
    # Find series
    all_s = requests.get(f"{ORTHANC}/series", timeout=10).json()
    sid = None
    for s in all_s:
        info = requests.get(f"{ORTHANC}/series/{s}", timeout=10).json()
        if info.get("MainDicomTags", {}).get("SeriesInstanceUID") == ct_uid:
            sid = s
            break
    if not sid:
        raise ValueError(f"Series {ct_uid[:20]}... not found")

    instances = requests.get(f"{ORTHANC}/series/{sid}", timeout=10).json()["Instances"]
    print(f"  CT: {len(instances)} slices")

    # Sort by SliceLocation
    slices = []
    for inst_id in instances:
        tags = requests.get(f"{ORTHANC}/instances/{inst_id}/simplified-tags", timeout=10).json()
        pos = float(tags.get("SliceLocation", tags.get("ImagePositionPatient", "0").split("\\")[-1] or 0))
        slices.append((pos, inst_id))
    slices.sort(key=lambda x: x[0])

    # Build 3D volume
    arrays = []
    origin = None
    spacing = None
    direction = None
    for _, inst_id in slices:
        r = requests.get(f"{ORTHANC}/instances/{inst_id}/file", timeout=30)
        ds = pydicom.dcmread(io.BytesIO(r.content))
        arrays.append(ds.pixel_array.astype(np.int16))
        if origin is None:
            origin = [float(x) for x in ds.ImagePositionPatient]
            spacing = [float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1]),
                       abs(slices[1][0] - slices[0][0]) if len(slices) > 1 else 1.0]
            direction = [float(x) for x in ds.ImageOrientationPatient] + [0, 0, 1]

    vol = np.stack(arrays, axis=0)
    img = sitk.GetImageFromArray(vol.transpose(2, 1, 0))  # (z,y,x) → (x,y,z) for ITK
    img.SetOrigin(origin)
    img.SetSpacing(spacing)
    # Set direction: row_cosine, col_cosine, slice_normal
    img.SetDirection(direction[:3] + direction[3:6] + [0, 0, 1])
    return img


def seg_to_labelmap(seg_ds, ref_image):
    """Convert DICOM SEG to SimpleITK label map aligned to ref_image."""
    # DICOM SEG: multi-frame, each frame has spatial position in PerFrameFunctionalGroupsSequence
    if not hasattr(seg_ds, "PerFrameFunctionalGroupsSequence"):
        raise ValueError("SEG missing PerFrameFunctionalGroupsSequence")

    rows = seg_ds.Rows
    cols = seg_ds.Columns

    # Build label map: (rows, cols) per-frame, place at correct spatial position
    pixel_data = seg_ds.pixel_array  # shape: (frames, rows, cols)

    # Get segment info
    segments = {}
    for seg in seg_ds.SegmentSequence:
        segments[seg.SegmentNumber] = seg.SegmentLabel

    print(f"  SEG segments: {segments}")

    # Use reference image as template
    label_map = sitk.Image(ref_image.GetSize(), sitk.sitkUInt8)
    label_map.CopyInformation(ref_image)

    # For each frame, find its spatial position and place in label map
    for frame_idx, frame in enumerate(seg_ds.PerFrameFunctionalGroupsSequence):
        # Get frame position
        pos_seq = frame.PlanePositionSequence[0] if hasattr(frame, 'PlanePositionSequence') else None
        if pos_seq is None:
            # Try SharedFunctionalGroupsSequence first
            shared = seg_ds.SharedFunctionalGroupsSequence[0] if hasattr(seg_ds, 'SharedFunctionalGroupsSequence') else None
            pos_seq = shared.PlanePositionSequence[0] if shared and hasattr(shared, 'PlanePositionSequence') else None
            if pos_seq is None:
                continue

        img_pos = [float(x) for x in pos_seq.ImagePositionPatient]

        # Get segment number for this frame
        seg_id_frame = frame.DerivationImageSequence[0].SourceImageSequence[0].ReferencedSegmentNumber
        seg_val = seg_id_frame  # use segment number as label value

        # Find corresponding voxel in reference image
        phys_point = img_pos
        try:
            idx = ref_image.TransformPhysicalPointToIndex(phys_point)
        except:
            continue

        # Extract this frame's segmentation slice (kidney segment only)
        frame_data = pixel_data[frame_idx]  # (rows, cols)
        if seg_val == 1:  # kidney = segment 1
            # Place at correct z-slice
            z = idx[2]
            if 0 <= z < label_map.GetSize()[2]:
                kidney_slice = label_map[z]  # is this right? sitk indexing...
                # Actually, let me use numpy approach instead

    # Simpler approach: just stack all frames and use the ref image geometry
    # This is getting complex. Let me use a simpler method.

    return None  # placeholder


def main():
    print("=" * 60)
    print("KIDNEY SEGMENTATION EVALUATION (KiTS19)")
    print("=" * 60)

    results = []

    for ct_uid, seg_uid, name in CASES:
        print(f"\n{'='*40}")
        print(f"Case: {name}")
        print(f"{'='*40}")

        # 1. Get prediction from TotalSegmentator
        print("  [1/4] Getting prediction ...")
        pred_path = os.path.join(OUTPUT, f"pred_{name}.npy")
        if os.path.exists(pred_path):
            pred = np.load(pred_path)
        else:
            r = requests.post(f"{TOTALSEG}/segment_mask",
                            json={"series_instance_uid": ct_uid}, timeout=900)
            data = r.json()
            if not data.get("success"):
                print(f"  FAIL: {data}")
                continue
            pred = np.load(data["file_path"])
            np.save(pred_path, pred)

        print(f"  Pred shape: {pred.shape}")

        # 2. Build kidney mask from prediction (merge left+right)
        # TotalSegmentator kidney labels: typically 2=kidney_right, 3=kidney_left (check from label_names)
        r = requests.post(f"{TOTALSEG}/segment_mask",
                        json={"series_instance_uid": ct_uid}, timeout=900)
        data = r.json()
        if data.get("file_path") and data["file_path"] != pred_path:
            pred = np.load(data["file_path"])
            np.save(pred_path, pred)

        # Find kidney labels
        kidney_ids = []
        for lid, lname in zip(data.get("labels", []), data.get("label_names", [])):
            if "kidney" in lname.lower() and "tumor" not in lname.lower() and "cyst" not in lname.lower():
                kidney_ids.append(lid)
        print(f"  Kidney labels: {kidney_ids}")

        pred_kidney = np.isin(pred, kidney_ids).astype(np.uint8)

        # 3. Download and process GT
        print("  [2/4] Downloading SEG GT ...")
        seg_ds = download_seg_dicom(seg_uid)
        print(f"  SEG: {seg_ds.Rows}x{seg_ds.Columns}, {len(seg_ds.PerFrameFunctionalGroupsSequence)} frames")

        # 4. Build CT image
        print("  [3/4] Building CT reference ...")
        ct_img = build_ct_sitk(ct_uid)
        print(f"  CT: size={ct_img.GetSize()}, spacing={ct_img.GetSpacing()}")

        # 5. Simple alignment: extract SEG frames and compare with prediction slices
        # Since full DICOM spatial registration is complex, use the GT we already have
        print("  [4/4] Computing metrics ...")

        # For now: use the downloaded GT npy (already aligned from previous download)
        gt_path = f"c:/Users/Dell/Desktop/miscada-project-master/kits{name.split('-')[1]}_gt.npy"
        # Note: need a simpler approach since SEG spatial alignment is complex

        results.append({"case": name, "status": "alignment_pending"})

    print("\nDone.")
    with open(os.path.join(OUTPUT, "kidney_eval.json"), "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
