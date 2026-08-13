# pipeline.py — UI 无关的检测编排：CV 首检 → 渲染 → Agent 复核事件流
#
# 与 app.py::analyze() 存在约 30 行重复，这是有意为之：app.py 是已验证的回退版本，
# 不因本次重写而改动（见 spec §3.1）。不要以 DRY 为由收敛。
import os

import numpy as np
from PIL import Image

import config
from agent import AgentContext, review
from regions import extract_candidate_regions
from run_inference import TRUFOR_ROOT, load_model, run_single, select_device
from tools import build_registry

_RUNTIME = None


def get_runtime():
    """懒加载单例：模型只在进程内加载一次（实测加载 4.9s）。"""
    global _RUNTIME
    if _RUNTIME is None:
        device = select_device()
        model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
        _RUNTIME = (model, device, build_registry())
    return _RUNTIME


def render_heatmap(loc_map):
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(loc_map)[:, :, :3] * 255).astype(np.uint8))


def render_confidence(conf_map):
    gray = (np.clip(conf_map, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(gray, mode="L").convert("RGB")


def run_detection(image_path, mode, *, model, device, tools, vlm=None):
    """先产出 ("cv", dict) 一次，再逐个产出 ("trace", TraceEvent)。"""
    result = run_single(model, image_path, device, max_size=config.MAX_SIZE)
    if device == "mps":
        import torch
        torch.mps.empty_cache()

    original = Image.open(image_path).convert("RGB")
    heatmap = render_heatmap(result["map"])
    confidence = render_confidence(result["conf"])
    infer_size = str(result["infer_size"])
    candidates = extract_candidate_regions(result["map"])

    yield "cv", {"score": result["score"], "infer_size": infer_size,
                 "heatmap": heatmap, "confidence": confidence,
                 "candidates": candidates, "original": original}

    ctx = AgentContext(image_path=image_path, original_img=original, heatmap_img=heatmap,
                       score=result["score"], infer_size=infer_size,
                       tiled="tiled" in infer_size, candidates=candidates)

    kwargs = {"vlm": vlm} if vlm is not None else {}
    for ev in review(ctx, tools, mode=mode, **kwargs):
        yield "trace", ev
