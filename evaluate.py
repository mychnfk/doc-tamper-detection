# evaluate.py — 自建评测集：批量跑分 / 阈值校准 / CV vs Agent 端到端对照
import argparse
import csv
import os

import numpy as np

import config

CATEGORIES = ("normal", "amount", "date", "seal", "aigc", "copymove")
_VERDICT_BIN = {"高度可疑": 1, "疑似篡改": 1, "疑似异常": 1, "正常": 0, "未见明显篡改": 0}


def verdict_to_bin(conclusion):
    for k, v in _VERDICT_BIN.items():
        if k in (conclusion or ""):
            return v
    return None                       # 无法审核等 → 排除出指标


def collect_dataset(root="eval-images"):
    items = []
    for cat in CATEGORIES:
        d = os.path.join(root, cat)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.startswith(".") or "_orig" in f:
                continue
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                items.append((os.path.join(d, f), 0 if cat == "normal" else 1, cat))
    return items


def sweep(rows, step=0.02):
    pos = [r for r in rows if r["label"] == 1]
    neg = [r for r in rows if r["label"] == 0]
    table = []
    for t in np.arange(0.0, 1.0 + step, step):
        tpr = sum(r["score"] >= t for r in pos) / max(len(pos), 1)
        fpr = sum(r["score"] >= t for r in neg) / max(len(neg), 1)
        table.append({"thresh": round(float(t), 2), "tpr": round(tpr, 3), "fpr": round(fpr, 3)})
    return table


def suggest_thresholds(rows):
    neg = sorted(r["score"] for r in rows if r["label"] == 0)
    pos = sorted(r["score"] for r in rows if r["label"] == 1)
    low = round(min(neg[-1] + 0.05, (neg[-1] + pos[0]) / 2 + 0.02), 2) if neg and pos else config.LOW_THRESH
    high = round(float(np.percentile(pos, 30)), 2) if pos else config.HIGH_THRESH
    if low >= high:
        low = round(high - 0.1, 2)
    return low, high


def run_batch(mode, out_csv):
    from PIL import Image
    from run_inference import select_device, load_model, run_single, TRUFOR_ROOT
    from regions import extract_candidate_regions
    from tools import build_registry
    from agent import AgentContext, review

    device = select_device()
    model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
    tools = build_registry()
    rows = []
    for path, label, cat in collect_dataset():
        result = run_single(model, path, device, max_size=config.MAX_SIZE)
        if device == "mps":
            import torch
            torch.mps.empty_cache()
        row = {"path": path, "label": label, "category": cat,
               "score": round(float(result["score"]), 4), "verdict_bin": "", "source": "cv"}
        if mode == "agent":
            import matplotlib
            matplotlib.use("agg")
            import matplotlib.cm as cm
            heat = Image.fromarray((cm.RdBu_r(result["map"])[:, :, :3] * 255).astype("uint8"))
            ctx = AgentContext(path, Image.open(path).convert("RGB"), heat,
                               result["score"], str(result["infer_size"]),
                               "tiled" in str(result["infer_size"]),
                               extract_candidate_regions(result["map"]))
            final = list(review(ctx, tools, mode="agent"))[-1].payload
            concl = (final["verdict"] or {}).get("conclusion", "") if final["verdict"] else final["text"][:20]
            row["verdict_bin"] = verdict_to_bin(concl)
            row["source"] = final["source"]
        rows.append(row)
        print(f"[{cat}] {os.path.basename(path)} score={row['score']}"
              + (f" agent={row['verdict_bin']}({row['source']})" if mode == "agent" else ""))

    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} 张已写入 {out_csv}")


def calibrate(csv_path):
    with open(csv_path) as f:
        rows = [{"score": float(r["score"]), "label": int(r["label"]), "category": r["category"]}
                for r in csv.DictReader(f)]
    print("\n各类分数分布：")
    for cat in CATEGORIES:
        ss = [r["score"] for r in rows if r["category"] == cat]
        if ss:
            print(f"  {cat:9s} n={len(ss)}  {sorted(ss)}")
    print("\n阈值扫描（thresh / TPR / FPR）：")
    for t in sweep(rows):
        print(f"  {t['thresh']:.2f}  {t['tpr']:.3f}  {t['fpr']:.3f}")
    low, high = suggest_thresholds(rows)
    print(f"\n建议阈值：LOW={low} HIGH={high}")
    print(f"人工确认后写入 .env：\nDOCGUARD_LOW_THRESH={low}\nDOCGUARD_HIGH_THRESH={high}")
    _plot_distribution(rows, os.path.join(os.path.dirname(csv_path) or ".", "score_dist.png"))


def _plot_distribution(rows, out_png):
    """各类 score 散点分布图（答辩/PPT 素材）。"""
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, cat in enumerate(CATEGORIES):
        ss = [r["score"] for r in rows if r["category"] == cat]
        ax.scatter([i] * len(ss), ss, s=60, alpha=0.7,
                   color="#2a9d8f" if cat == "normal" else "#e76f51")
    ax.set_xticks(range(len(CATEGORIES)), CATEGORIES)
    ax.set_ylabel("TruFor score")
    ax.set_ylim(0, 1)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    print(f"分布图已保存: {out_png}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cv", "agent"])
    ap.add_argument("--out", default="eval-report/results.csv")
    ap.add_argument("--calibrate")
    a = ap.parse_args()
    if a.calibrate:
        calibrate(a.calibrate)
    else:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        run_batch(a.mode or "cv", a.out)
