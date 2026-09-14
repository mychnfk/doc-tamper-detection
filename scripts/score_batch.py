"""一次性加载模型，对一批图片跑 CV 首检打分（灰区图制作用）。

用法: .venv/bin/python scripts/score_batch.py <图片路径...>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from regions import extract_candidate_regions
from run_inference import TRUFOR_ROOT, load_model, run_single, select_device


def main(paths):
    device = select_device()
    model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
    print(f"device={device} max_size={config.MAX_SIZE} "
          f"灰区={config.LOW_THRESH}~{config.HIGH_THRESH}\n")
    for p in paths:
        t0 = time.monotonic()
        r = run_single(model, p, device, max_size=config.MAX_SIZE)
        cands = extract_candidate_regions(r["map"])
        score = r["score"]
        zone = ("灰区 ✅" if config.LOW_THRESH <= score <= config.HIGH_THRESH
                else ("高 " if score > config.HIGH_THRESH else "低 "))
        print(f"{os.path.basename(p):<28} score={score:.4f} {zone} "
              f"size={r['infer_size']} 候选={len(cands)} {time.monotonic()-t0:.1f}s")
        for c in cands[:3]:
            print(f"    #{c['id']} bbox={c['bbox']} 面积={c['area_frac']:.2%} 均分={c['mean_score']}")
        if device == "mps":
            import torch
            torch.mps.empty_cache()


if __name__ == "__main__":
    main(sys.argv[1:])
