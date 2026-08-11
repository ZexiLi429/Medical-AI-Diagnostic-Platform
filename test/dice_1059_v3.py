"""dice_1059_v3.py — brute-force alignment search"""
import numpy as np

pred = np.load("c:/Users/Dell/Desktop/miscada-project-master/experiment_results/pred_27a3a67f-4fc.npy")
gt_raw = np.load("c:/Users/Dell/Desktop/miscada-project-master/kits151_gt.npy")

pred_k = (pred == 2).astype(np.float64)  # kidney
gt_k = (gt_raw == 1).astype(np.float64)

def dice(p, g):
    i = (p*g).sum(); d = p.sum()+g.sum()
    return 2*i/d if d>0 else 0

# Try all axis permutations + flips
best = 0
best_name = ""
for axes in [(0,1,2), (0,2,1), (1,0,2), (1,2,0), (2,0,1), (2,1,0)]:
    for fx in [False, True]:
        for fy in [False, True]:
            for fz in [False, True]:
                gt_t = gt_k.transpose(axes).copy()
                if fx: gt_t = gt_t[::-1]
                if fy: gt_t = gt_t[:,::-1]
                if fz: gt_t = gt_t[:,:,::-1]
                # Resize to match pred if needed
                if gt_t.shape != pred_k.shape:
                    from scipy.ndimage import zoom
                    z = [pred_k.shape[i]/gt_t.shape[i] for i in range(3)]
                    gt_t = zoom(gt_t, z, order=0)
                d = dice(pred_k, gt_t)
                if d > best:
                    best = d
                    best_name = f"axes={axes} flip=({fx},{fy},{fz}) shape={gt_t.shape}"

print(f"Best alignment: {best_name}")
print(f"Kidney Dice: {best:.4f}")
