# scripts/smoke_agent.py — 真机全链路：TruFor → Agent Loop → 事件流打印
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

import config
from run_inference import select_device, load_model, run_single, TRUFOR_ROOT
from regions import extract_candidate_regions
from tools import build_registry
from agent import AgentContext, review


def main(image_path, mode="agent"):
    device = select_device()
    model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
    result = run_single(model, image_path, device, max_size=config.MAX_SIZE)
    if device == "mps":
        import torch
        torch.mps.empty_cache()

    ctx = AgentContext(
        image_path=image_path,
        original_img=Image.open(image_path).convert("RGB"),
        heatmap_img=_render_heatmap(result["map"]),
        score=result["score"],
        infer_size=str(result["infer_size"]),
        tiled="tiled" in str(result["infer_size"]),
        candidates=extract_candidate_regions(result["map"]),
    )
    print(f"\n=== CV: score={ctx.score:.4f} size={ctx.infer_size} candidates={len(ctx.candidates)} ===\n")
    for ev in review(ctx, build_registry(), mode=mode):
        images = ev.payload.get("images", [])
        brief = {k: v for k, v in ev.payload.items() if k != "images"}
        print(f"[turn {ev.turn}] {ev.type}: {brief}" + (f" (+{len(images)} 图)" if images else ""))
    print()


def _render_heatmap(loc_map):
    import numpy as np
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(loc_map)[:, :, :3] * 255).astype("uint8"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "agent")
