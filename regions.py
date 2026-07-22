# regions.py — loc_map → 连通域 → top-K 候选框（0-1000 归一化，供 VLM 编号引用）
import numpy as np
from scipy import ndimage


def extract_candidate_regions(loc_map, thresh=0.5, top_k=5, min_area_frac=0.0005):
    h, w = loc_map.shape
    mask = loc_map >= thresh
    labeled, n = ndimage.label(mask)
    if n == 0:
        return []

    regions = []
    for i in range(1, n + 1):
        area = int((labeled == i).sum())
        if area / (h * w) < min_area_frac:
            continue
        ys, xs = np.where(labeled == i)
        regions.append({
            "bbox": [int(xs.min() / w * 1000), int(ys.min() / h * 1000),
                     int((xs.max() + 1) / w * 1000), int((ys.max() + 1) / h * 1000)],
            "area_frac": round(area / (h * w), 4),
            "mean_score": round(float(loc_map[labeled == i].mean()), 4),
        })

    regions.sort(key=lambda r: r["mean_score"], reverse=True)
    regions = regions[:top_k]
    for idx, r in enumerate(regions):
        r["id"] = idx + 1
    return regions
