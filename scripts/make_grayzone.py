"""灰区图梯度实验：三种破坏噪声一致性的手法 × 面积，找 score 落 0.4-0.7 的配方。

背景：同图 copy-move 对 TruFor 的 detection head 几乎零响应（噪声指纹相同）。
本脚本对比三条路线——合成渲染（零噪声）/ 跨图拼接（异源噪声）/ 局部去噪（噪声抹除）。

用法: .venv/bin/python scripts/make_grayzone.py [输出目录]
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SRC = "example-images/微信圖片_20260629180819_55_237.jpg"
SRC54 = "example-images/微信圖片_20260629180524_54_237.png"
FONT = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"

# 金额 "152" 的位置（目检网格定位）：数字 y=165~181，下划线 y≈181
AMT = (869, 163, 898, 183)


def sample_colors(im):
    """从金额区周边取纸面色，从数字笔画取墨色。"""
    a = np.array(im)
    paper = np.median(a[150:162, 860:960].reshape(-1, 3), axis=0).astype(int)
    band = a[165:181, 869:898].reshape(-1, 3)
    dark = band[band.sum(axis=1) < band.sum(axis=1).mean()]
    ink = np.median(dark, axis=0).astype(int)
    return tuple(paper), tuple(ink)


def synth(im, box, text, font_size, paper, ink, name, out):
    """在 box 内涂纸面色后用字体渲染文字——合成像素完全没有相机噪声。"""
    img = im.copy()
    d = ImageDraw.Draw(img)
    d.rectangle(box, fill=paper)
    f = ImageFont.truetype(FONT, font_size)
    d.text((box[0] + 1, box[1] - 1), text, font=f, fill=ink)
    return save(img, name, out)


def splice(im, src54, dst_xy, size, name, out):
    """从 54_237（同模板不同拍摄）取патч——噪声指纹异源。"""
    img = im.copy()
    w, h = size
    patch = src54.crop((480, 205, 480 + w, 205 + h))
    img.paste(patch, dst_xy)
    return save(img, name, out)


def denoise(im, box, radius, name, out):
    """中值滤波抹掉区域内的传感器噪声，纹理仍在但噪声基线断裂。"""
    img = im.copy()
    region = img.crop(box).filter(ImageFilter.MedianFilter(size=radius))
    img.paste(region, (box[0], box[1]))
    return save(img, name, out)


def save(img, name, out):
    p = os.path.join(out, f"{name}.jpg")
    img.save(p, quality=92)
    return p


def main(out="/tmp/gz"):
    os.makedirs(out, exist_ok=True)
    im = Image.open(SRC).convert("RGB")
    s54 = Image.open(SRC54).convert("RGB")
    paper, ink = sample_colors(im)
    print(f"纸面色={paper} 墨色={ink}\n")

    made = []
    # 路线 1：合成渲染，面积递增
    made.append(synth(im, (871, 165, 881, 181), "9", 17, paper, ink, "synth_a_9only", out))
    made.append(synth(im, AMT, "952", 17, paper, ink, "synth_b_952", out))
    made.append(synth(im, (860, 158, 960, 188), "952", 17, paper, ink, "synth_c_band100", out))
    made.append(synth(im, (820, 150, 1020, 200), "952", 17, paper, ink, "synth_d_band200", out))
    made.append(synth(im, (700, 140, 1060, 210), "952", 17, paper, ink, "synth_e_band360", out))
    # 路线 2：跨图拼接，面积递增
    made.append(splice(im, s54, (869, 163), (30, 22), "splice_a_30", out))
    made.append(splice(im, s54, (860, 158), (120, 36), "splice_b_120", out))
    made.append(splice(im, s54, (800, 150), (300, 50), "splice_c_300", out))
    # 路线 3：局部去噪，面积递增
    made.append(denoise(im, (860, 158, 960, 188), 3, "denoise_a_100", out))
    made.append(denoise(im, (800, 150, 1020, 200), 3, "denoise_b_220", out))
    made.append(denoise(im, (700, 140, 1060, 220), 5, "denoise_c_360", out))

    for p in made:
        print(p)
    print(f"\n共 {len(made)} 张，跑分：")
    print(f"  .venv/bin/python scripts/score_batch.py {out}/*.jpg")


if __name__ == "__main__":
    main(*sys.argv[1:])
