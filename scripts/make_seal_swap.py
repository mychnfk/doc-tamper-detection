"""灰区图定版：公章掉包（抹除原章 + 加盖异源印章）。

剧情：委托收款函抬头写「杭州博雅电子商务有限公司」，但所盖公章为
「深圳市牛马成群有限公司」——章证不符，财务人员的典型红旗。

手法刻意做精细，这正是灰区的来源：
- 抹除原章用同图干净纸面克隆（噪声同源，不留合成痕迹）
- 加盖只搬印油像素（按 redness 算 alpha），不搬矩形背景，无粘贴白边
- 强度分档，用于把 CV 全局分从 0.81（粗暴矩形粘贴）压进 0.4-0.7 灰区

用法: .venv/bin/python scripts/make_seal_swap.py [输出目录]
"""
import os
import sys

import numpy as np
from PIL import Image

DST = "example-images/微信圖片_20260629180819_55_237.jpg"
SRC = "example-images/微信圖片_20260629180524_54_237.png"

DST_SEAL = (592, 720, 832, 952)      # 55_237 原章（杭州博雅）
SRC_SEAL = (671, 855, 916, 1118)     # 54_237 来源章（深圳牛马成群）
CLEAN_PAPER = (150, 760, 450, 1010)  # 55_237 签字框内空白纸面，作克隆源


def redness(a):
    return a[:, :, 0].astype(float) - (a[:, :, 1].astype(float) + a[:, :, 2].astype(float)) / 2


def erase_seal(im):
    """用同图干净纸面平铺覆盖原章区域——噪声与全图同源，不引入合成痕迹。"""
    img = im.copy()
    x1, y1, x2, y2 = DST_SEAL
    pad = 12
    box = (x1 - pad, y1 - pad, x2 + pad, y2 + pad)
    w, h = box[2] - box[0], box[3] - box[1]
    clean = im.crop(CLEAN_PAPER)
    tile = Image.new("RGB", (w, h))
    for oy in range(0, h, clean.height):
        for ox in range(0, w, clean.width):
            tile.paste(clean, (ox, oy))
    # 边缘羽化，避免克隆块自身留下硬边
    mask = np.zeros((h, w), dtype=np.float32)
    mask[pad:-pad, pad:-pad] = 1.0
    for i in range(pad):
        v = (i + 1) / (pad + 1)
        mask[i, :] = np.maximum(mask[i, :], v); mask[-1 - i, :] = np.maximum(mask[-1 - i, :], v)
        mask[:, i] = np.maximum(mask[:, i], v); mask[:, -1 - i] = np.maximum(mask[:, -1 - i], v)
    img.paste(tile, (box[0], box[1]), Image.fromarray((mask * 255).astype(np.uint8)))
    return img


def stamp(base, strength, blur=0.0):
    """只搬印油像素：alpha 由 redness 归一化而来，无矩形边界。"""
    src = Image.open(SRC).convert("RGB").crop(SRC_SEAL)
    tw, th = DST_SEAL[2] - DST_SEAL[0], DST_SEAL[3] - DST_SEAL[1]
    src = src.resize((tw, th), Image.LANCZOS)
    sa = np.array(src)

    alpha = np.clip((redness(sa) - 12) / 55.0, 0, 1) * strength
    if blur:
        from PIL import ImageFilter
        alpha = np.array(Image.fromarray((alpha * 255).astype(np.uint8))
                         .filter(ImageFilter.GaussianBlur(blur))) / 255.0

    out = np.array(base).astype(float)
    reg = out[DST_SEAL[1]:DST_SEAL[3], DST_SEAL[0]:DST_SEAL[2]]
    a3 = alpha[:, :, None]
    out[DST_SEAL[1]:DST_SEAL[3], DST_SEAL[0]:DST_SEAL[2]] = reg * (1 - a3) + sa.astype(float) * a3
    return Image.fromarray(out.astype(np.uint8))


def main(out="/tmp/gz3"):
    os.makedirs(out, exist_ok=True)
    im = Image.open(DST).convert("RGB")
    erased = erase_seal(im)
    erased.save(os.path.join(out, "swap_00_erased_only.jpg"), quality=92)

    made = ["swap_00_erased_only"]
    for s, b, q in [(1.0, 0, 92), (0.85, 0, 92), (0.85, 0.6, 92),
                    (0.7, 0.6, 92), (0.85, 0.6, 85), (1.0, 0, 85)]:
        name = f"swap_s{int(s*100)}_b{b}_q{q}"
        stamp(erased, s, b).save(os.path.join(out, f"{name}.jpg"), quality=q)
        made.append(name)

    for n in made:
        print(f"{out}/{n}.jpg")


if __name__ == "__main__":
    main(*sys.argv[1:])
