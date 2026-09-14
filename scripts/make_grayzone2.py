"""灰区图梯度实验 第二轮：大面积 + 真实欺诈剧情。

第一轮结论：score 基本只跟异常区面积走，小面积文字改写在检测下限以下
（160px² 到 580px² 与基线无差别，25200px² 才到 0.30）。
本轮验证两件事：① 面积继续放大能否进 0.4-0.7 ② 真实剧情的大面积篡改分数落点。

用法: .venv/bin/python scripts/make_grayzone2.py [输出目录]
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SRC = "example-images/微信圖片_20260629180819_55_237.jpg"
SRC54 = "example-images/微信圖片_20260629180524_54_237.png"
SRC_CHECK = "example-images/check.jpg"
FONT = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"
PAPER = (163, 160, 155)
INK = (106, 103, 99)

# 55_237 版面关键区（目检）
ACCOUNT_BLOCK = (250, 230, 800, 330)   # 开户名/银行账号/开户行 三行，550x100
SEAL = (700, 720, 1030, 1050)          # 公章 330x330


def save(img, name, out, q=92):
    p = os.path.join(out, f"{name}.jpg")
    img.save(p, quality=q)
    return p


def synth_band(im, box, name, out):
    img = im.copy()
    d = ImageDraw.Draw(img)
    d.rectangle(box, fill=PAPER)
    d.text((box[0] + 8, box[1] + 8), "952", font=ImageFont.truetype(FONT, 17), fill=INK)
    return save(img, name, out)


def splice_from(im, src, src_box, dst_xy, name, out):
    img = im.copy()
    img.paste(src.crop(src_box), dst_xy)
    return save(img, name, out)


def main(out="/tmp/gz2"):
    os.makedirs(out, exist_ok=True)
    im = Image.open(SRC).convert("RGB")
    s54 = Image.open(SRC54).convert("RGB")
    chk = Image.open(SRC_CHECK).convert("RGB")

    made = []
    # ① 面积继续放大（合成渲染，纯粹测曲线）
    made.append(synth_band(im, (600, 130, 1060, 250), "synth_f_460x120", out))
    made.append(synth_band(im, (400, 120, 1060, 320), "synth_g_660x200", out))
    made.append(synth_band(im, (200, 100, 1060, 400), "synth_h_860x300", out))

    # ② 真实剧情：整体替换收款账户三行（异源噪声，来自 54_237 同模板不同拍摄）
    made.append(splice_from(im, s54, (250, 270, 800, 370), (250, 230), "real_a_account", out))
    # ③ 真实剧情：替换公章（面积 330x330，典型"章是P上去的"）
    made.append(splice_from(im, s54, (700, 880, 1030, 1210), (700, 720), "real_b_seal", out))
    # ④ 异源程度拉满：从完全不同的单据(check.jpg)取材
    made.append(splice_from(im, chk, (500, 500, 1050, 600), (250, 230), "real_c_account_chk", out))
    made.append(splice_from(im, chk, (500, 500, 830, 830), (700, 720), "real_d_seal_chk", out))

    for p in made:
        print(p)
    print(f"\n共 {len(made)} 张")


if __name__ == "__main__":
    main(*sys.argv[1:])
