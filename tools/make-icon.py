#!/usr/bin/env python3
"""
从 Echo 形象生成 macOS 应用图标。

直接合成形象源文件的图层（body / eyes），而不是另画一套几何 ——
重画出来的东西会丢掉 Echo 宽扁身形和方眼这两个识别特征。
回响粒改为按版面重新摆放：源文件里的粒子位置是为 1034x432 宽画布设计的，
套进方形图标会被圆角切掉，看起来像失误。

修掉旧图标的两个硬伤：
  1. 旧图 alpha 全为 255（不透明白底），Dock/Finder 里露白边
  2. 旧图内容 907x937 且下边贴底，不在 Apple 的 824/1024 网格上

用法：python3 tools/make-icon.py [输出目录.iconset]
"""
from PIL import Image, ImageDraw, ImageFilter
import math, os, subprocess, sys

ECHO = os.path.expanduser(
    "~/wenjian/echo/design/fusai-video/08-素材与参考/little-echo")

S = 1024                 # 画布
PLATE = 824              # Apple 规范：圆角矩形 824，四边留白 100
PAD = (S - PLATE) // 2
BODY_BOX = (106, 40, 924, 421)   # 源文件里身体的实际包围盒
BODY_RATIO = 0.88                # 身体宽度占圆角矩形的比例

PAPER = (236, 220, 191, 255)     # #ECDCBF 纸底，形象的原生底色
VERMIL = (196, 69, 45, 255)      # #C4452D 朱砂


def squircle_points(size, n=5.0, k=2048):
    """超椭圆，比 rounded-rect 更接近 macOS 图标轮廓。"""
    a = size / 2
    pts = []
    for i in range(k):
        t = 2 * math.pi * i / k
        ct, st = math.cos(t), math.sin(t)
        pts.append((a * math.copysign(abs(ct) ** (2 / n), ct) + a,
                    a * math.copysign(abs(st) ** (2 / n), st) + a))
    return pts


def build(z=2, body_ratio=BODY_RATIO, dots=True):
    plate = Image.new("RGBA", (PLATE * z, PLATE * z), (0, 0, 0, 0))
    ImageDraw.Draw(plate).polygon(squircle_points(PLATE * z), fill=PAPER)
    mask = plate.getchannel("A")

    # 身体 + 眼睛，按身体包围盒对中
    char = Image.open(f"{ECHO}/echo-body.png").convert("RGBA")
    char.alpha_composite(Image.open(f"{ECHO}/echo-eyes.png").convert("RGBA"))
    bw = BODY_BOX[2] - BODY_BOX[0]
    scale = (PLATE * z * body_ratio) / bw
    char = char.resize((int(char.width * scale), int(char.height * scale)),
                       Image.LANCZOS)
    bcx = (BODY_BOX[0] + BODY_BOX[2]) / 2 * scale
    bcy = (BODY_BOX[1] + BODY_BOX[3]) / 2 * scale
    ox = int(PLATE * z / 2 - bcx)
    oy = int(PLATE * z / 2 - bcy) - int(PLATE * z * 0.015)   # 略微上移，给阴影留地

    # 接地阴影：源素材里有这层，缺了会显得 Echo 飘着
    body_h = (BODY_BOX[3] - BODY_BOX[1]) * scale
    sh = Image.new("RGBA", plate.size, (0, 0, 0, 0))
    sw = int(PLATE * z * body_ratio * 0.78)
    shh = int(body_h * 0.13)
    sx = int(PLATE * z / 2 - sw / 2)
    sy = int(oy + bcy + body_h / 2 - shh * 0.35)
    ImageDraw.Draw(sh).ellipse([sx, sy, sx + sw, sy + shh], fill=(31, 27, 22, 58))
    sh = sh.filter(ImageFilter.GaussianBlur(radius=PLATE * z * 0.018))
    plate.alpha_composite(sh)
    plate.alpha_composite(char, (ox, oy))

    # 回响粒：按图标版面重摆，全部留在圆角安全区内
    if not dots:
        plate.putalpha(mask)
        img = Image.new("RGBA", (S * z, S * z), (0, 0, 0, 0))
        img.paste(plate, (PAD * z, PAD * z), plate)
        return img.resize((S, S), Image.LANCZOS)
    dot = int(PLATE * z * body_ratio * 0.051)
    d = ImageDraw.Draw(plate)
    # 身体纵向占 0.28~0.69，粒子只能落在上下两条空带里，压到身上会像失误
    for fx, fy in ((0.135, 0.212), (0.248, 0.132), (0.818, 0.752)):
        x, y = int(PLATE * z * fx), int(PLATE * z * fy)
        d.rectangle([x, y, x + dot, y + dot], fill=VERMIL)

    plate.putalpha(mask)                     # 任何出血都裁进圆角
    img = Image.new("RGBA", (S * z, S * z), (0, 0, 0, 0))
    img.paste(plate, (PAD * z, PAD * z), plate)
    return img.resize((S, S), Image.LANCZOS)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "icon.iconset"
    img = build()
    # 16/32px 用更紧的构图并去掉回响粒：Echo 是 2.15:1 的宽形，
    # 按大图等比缩到 16px 只剩一条细杠。.icns 本就允许逐尺寸换图稿。
    tight = build(body_ratio=1.16, dots=False)
    os.makedirs(out, exist_ok=True)
    img.save(out.replace(".iconset", "") + "-1024.png")
    for px, name in [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"),
                     (64, "32x32@2x"), (128, "128x128"), (256, "128x128@2x"),
                     (256, "256x256"), (512, "256x256@2x"), (512, "512x512"),
                     (1024, "512x512@2x")]:
        src = tight if px <= 32 else img
        src.resize((px, px), Image.LANCZOS).save(f"{out}/icon_{name}.png")
    icns = out.replace(".iconset", ".icns")
    subprocess.run(["iconutil", "-c", "icns", out, "-o", icns], check=True)
    print(f"已生成 {icns}")


if __name__ == "__main__":
    main()
