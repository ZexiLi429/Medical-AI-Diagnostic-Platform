"""Run TotalSegmentator on KiTS NIfTI, compare with GT segmentation"""
import os, numpy as np, nibabel as nib, requests, json
from scipy.ndimage import zoom

nii_path = "c:/Users/Dell/Desktop/miscada-project-master/kits19_gt/case_00095_imaging.nii.gz"
seg_path = "c:/Users/Dell/Desktop/miscada-project-master/kits19_gt/case_00095.nii.gz"

# Call TotalSegmentator API by saving as temp DICOM won't work.
# Instead: upload to Orthanc as a series, then call /segment_mask
# Actually simpler: directly use the TotalSegmentator Python API

print("Loading NIfTI...")
img_nii = nib.load(nii_path)
img_data = img_nii.get_fdata().astype(np.int16)
print(f"  Image: {img_data.shape}")

# Upload to Orthanc as DICOM? No - it's NIfTI, not DICOM.
# Alternative: use the totalseg_service's internal function
# But we need the Docker container's totalsegmentator

# Let's try the service's /segment_mask with the existing UID
# The case_00095 CT is already in Orthanc as 314 slices
# Prediction already cached

# Load prediction (already cached from previous run)
pred_path = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results/pred_KiTS-314.npy"
labels_path = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results/labels_KiTS-314.json"

if not os.path.exists(pred_path):
    print("Getting prediction from API...")
    r = requests.post("http://localhost:8004/segment_mask",
                     json={"series_instance_uid": "1.3.6.1.4.1.14519.5.2.1.6919.4624.321986215317450174304381809203"},
                     timeout=900)
    data = r.json()
    np.save(pred_path, np.load(data["file_path"]))
    with open(labels_path, "w") as f:
        json.dump({"labels": data["labels"], "label_names": data["label_names"]}, f)

pred = np.load(pred_path)
with open(labels_path) as f:
    lm = json.load(f)
kid_ids = [l for l, n in zip(lm["labels"], lm["label_names"])
           if "kidney" in n.lower() and "tumor" not in n.lower()]

# Load GT
gt_nii = nib.load(seg_path)
gt_data = gt_nii.get_fdata().astype(np.uint8)
gt_kidney = (gt_data == 1).astype(np.uint8)

# The prediction is (314, 512, 512) from TS on DICOM
# The GT NIfTI is (512, 512, 314) -- same as GitHub, needs transpose
# The imaging NIfTI is (512, 512, 314) -- same convention

# Key insight: BOTH GitHub seg and HF imaging use same NIfTI convention
# But our prediction is from DICOM with different convention
# 
# The imaging NIfTI shape is (512, 512, 314) = (z, y, x) where z=slice
# So transpose imaging to (314, 512, 512) to match pred
# Then run TS directly on imaging (not via DICOM)

print(f"GT NIfTI: {gt_data.shape}, Imaging NIfTI: {img_data.shape}")
print(f"Pred from DICOM: {pred.shape}")

# The fix: run TotalSegmentator directly on the NIfTI imaging data
# Transpose imaging to match TS expected format (z, y, x) = (314, 512, 512)
img_for_ts = img_data.transpose(2, 1, 0).copy()  # (314, 512, 512)
print(f"Imaging for TS: {img_for_ts.shape}")

# Now we need to call TotalSegmentator on this numpy array
# Save as temp NIfTI, call via subprocess or API
import tempfile, subprocess
tmpdir = tempfile.mkdtemp()
tmp_nii = os.path.join(tmpdir, "input.nii.gz")
nib.save(nib.Nifti1Image(img_for_ts.astype(np.int16), np.eye(4)), tmp_nii)

# Call totalsegmentator via Docker
# Actually, we can't easily do this from the host.
# Instead, let's add an endpoint to the service.

print("Need to call TotalSegmentator on NIfTI directly.")
print(f"Saved temp NIfTI to: {tmp_nii}")
print("Run: docker exec <totalseg_container> TotalSegmentator -i /path/input.nii.gz -o /path/output --task total --fast")
