"""部署基线回归：新机器上的 CV 分数必须与 Mac 开发机基线在容差内。

CUDA 与 MPS 的数值实现有细微差异，小数点后几位的漂移正常；
超出容差说明环境装错（最常见：装成 CPU 版 torch 后精度路径不同）或权重不对。

退出码: 0=全部通过  1=有超容差(黄牌,人工确认)  2=跑不起来(硬失败)
用法: .venv\\Scripts\\python.exe deploy\\check_baseline.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from run_inference import TRUFOR_ROOT, load_model, run_single, select_device

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    spec = json.load(open(os.path.join(BASE, "baseline.json"), encoding="utf-8"))
    tol = spec["tolerance"]
    device = select_device()
    print(f"device={device}  max_size={config.MAX_SIZE}  容差=±{tol}")
    if device == "cpu":
        print("FAIL: 未检测到 GPU（torch 装成 CPU 版？），基线回归中止")
        return 2

    model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
    worst = 0
    for item in spec["images"]:
        path = os.path.join(BASE, item["path"])
        if not os.path.exists(path):
            print(f"FAIL: 基线图缺失 {path}")
            return 2
        t0 = time.monotonic()
        r = run_single(model, path, device, max_size=config.MAX_SIZE)
        delta = abs(r["score"] - item["expected"])
        worst = max(worst, delta)
        mark = "OK  " if delta <= tol else "WARN"
        print(f"{mark} {item['note']:<24} 实测={r['score']:.4f} 期望={item['expected']:.4f} "
              f"Δ={delta:.4f} 耗时={time.monotonic() - t0:.1f}s")
    return 0 if worst <= tol else 1


if __name__ == "__main__":
    sys.exit(main())
