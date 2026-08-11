"""dice_1059.py — Dice for KiTS-1059"""
import requests, json, numpy as np
from scipy.ndimage import zoom

uid = "1.3.6.1.4.1.14519.5.2.1.6919.4624.138851628559747228095359380681"
gt_path = "c:/Users/Dell/Desktop/miscada-project-master/kits151_gt.npy"

print("[1/3] Running /segment_mask (may take ~6 min) ...")
r = requests.post("http://localhost:8004/segment_mask",
                  json={"series_instance_uid": uid}, timeout=900)
data = r.json()
print(f"  Pred shape: {data['shape']}, file: {data.get('file_path','')}")

pred = np.load(data["file_path"])
print(f"  Loaded pred: {pred.shape}")

print("[2/3] Loading GT ...")
gt = np.load(gt_path)
print(f"  GT shape: {gt.shape}")

# Find kidney and mass label IDs
kidney_ids = []
mass_ids = []
for lid, name in zip(data["labels"], data["label_names"]):
    nl = name.lower()
    if "kidney" in nl and "tumor" not in nl and "mass" not in nl:
        kidney_ids.append(lid)
    if "mass" in nl or ("kidney" in nl and "tumor" in nl):
        mass_ids.append(lid)
print(f"  Kidney IDs: {kidney_ids}")
print(f"  Mass IDs: {mass_ids}")

pred_k = np.isin(pred, kidney_ids).astype(np.float32)
pred_m = np.isin(pred, mass_ids).astype(np.float32)
gt_k = (gt == 1).astype(np.float32)
gt_m = (gt == 2).astype(np.float32)

# Resample
print("[3/3] Resampling & computing Dice ...")
z = [gt_k.shape[i] / pred_k.shape[i] for i in range(3)]
print(f"  Zoom factors: {[round(x,3) for x in z]}")
pred_k = zoom(pred_k, z, order=0)
pred_m = zoom(pred_m, z, order=0)

def dice(p, g):
    i = (p * g).sum()
    d = p.sum() + g.sum()
    return round(float(2 * i / d if d > 0 else 0), 4)

kd = dice(pred_k, gt_k)
md = dice(pred_m, gt_m)

print()
print("=" * 50)
print(f"  Kidney Dice:  {kd}")
print(f"  Mass Dice:    {md}")
print(f"  Average:      {(kd+md)/2:.4f}")
print("=" * 50)

result = {"case": "KiTS-1059", "kidney_dice": kd, "mass_dice": md}
with open("c:/Users/Dell/Desktop/miscada-project-master/experiment_results/dice_1059.json", "w") as f:
    json.dump(result, f, indent=2)
print("\nSaved: experiment_results/dice_1059.json")
