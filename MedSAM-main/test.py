import sys
# Windows 强制打印实时刷新，解决吞日志
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from pathlib import Path
import sys
SERVICE_DIR = Path(__file__).parent
print("=== 基础路径 ===")
print("当前脚本目录：", SERVICE_DIR)
sys.path.insert(0, str(SERVICE_DIR))

# 1. 测试torch，最容易卡死的环节
print("\n=== 测试导入torch ===")
try:
    import torch
    print("✅ torch 导入成功")
    print("torch版本:", torch.__version__)
    print("CUDA是否可用:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU名称:", torch.cuda.get_device_name(0))
except Exception as e:
    print("❌ torch 导入失败：", repr(e))
    import traceback
    traceback.print_exc()

# 2. 测试sam2导入
print("\n=== 测试导入sam2 ===")
try:
    from sam2.build_sam import build_sam2_video_predictor_npz
    print("✅ sam2 导入成功")
except Exception as e:
    print("❌ sam2 导入失败：", repr(e))
    import traceback
    traceback.print_exc()

# 3. 校验权重文件
print("\n=== 校验模型权重路径 ===")
ckpt = SERVICE_DIR / "checkpoints" / "MedSAM2_latest.pt"
print("权重完整路径：", ckpt)
print("文件是否存在：", ckpt.exists())
if ckpt.exists():
    print("文件大小(MB):", round(ckpt.stat().st_size / 1024 / 1024, 2))