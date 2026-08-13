#!/usr/bin/env python3
"""
把 Echo 的情绪 GIF 转成桌宠精灵图。

输出符合 orca 原生协议：1024x896，7 行状态 x 8 帧，cell 128x128，透明底。
行序必须与 src/renderer/pet/model.mjs 的 STATUS_ROWS 一致。

去背说明：
GIF 是纸底平涂（#ECDCBF）且带一层接地阴影，按背景色抠会在阴影处留渐变毛边。
Echo 全身只有 4 个颜色，所以改为「按角色色保留」——只留下足够接近
墨/盖沿/眼/朱砂的像素，其余一律透明。GIF 量化到 64 色 + 有序抖动，
因此用带阈值的最近邻分类而不是精确相等。

用法：python3 tools/make-pet-sprite.py [输出.png]
"""
from PIL import Image, ImageSequence
import os, sys

ECHO = os.path.expanduser(
    "~/wenjian/echo/design/fusai-video/08-素材与参考/little-echo/clips")

CELL = 128
FRAMES = 16          # 每行帧数。加载器按 floor(图宽/cell) 推断，加宽即可
                     # 8 帧从 90-180 帧的源里抽，动作跳跃感明显
CHAR_COLORS = [
    (31, 27, 22),    # 墨
    (60, 52, 44),    # 盖沿
    (248, 242, 230),  # 眼（宣纸白）
    (196, 69, 45),   # 朱砂
]
PAPER = (236, 220, 191)
TOL = 46            # 到角色色的最大距离；再大就会把纸底的抖动噪点吃进来

# 行序 = STATUS_ROWS。情绪与状态的对应关系：
ROWS = [
    ("idle",      "echo-calm.gif"),      # 平静待机
    ("play",      "echo-fond-hop.gif"),  # 招牌组合：好感 + 小跳
    ("sleep",     "echo-doze.gif"),      # 打盹
    ("running",   "echo-focused.gif"),   # 专注
    ("attention", "echo-curious.gif"),   # 好奇 —— 等你回应
    ("complete",  "echo-happy.gif"),     # 欣喜
    ("drag",      "echo-stumble.gif"),   # 重心一晃，正好是被拖拽的感觉
]


def dist2(a, b):
    return (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2


def keyed(frame):
    """只保留角色色，其余透明。"""
    im = frame.convert("RGB")
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    src, dst = im.load(), out.load()
    t2 = TOL * TOL
    paper2 = dist2  # 局部别名
    for y in range(im.height):
        for x in range(im.width):
            p = src[x, y]
            if paper2(p, PAPER) < t2:          # 明确是纸底，直接丢
                continue
            best, bd = None, None
            for c in CHAR_COLORS:
                d = dist2(p, c)
                if bd is None or d < bd:
                    best, bd = c, d
            if bd < t2:
                dst[x, y] = (best[0], best[1], best[2], 255)
    return out


def pick_frames(path, n):
    """在整段循环里等距取 n 帧，保证取到的是完整一圈。"""
    gif = Image.open(path)
    total = gif.n_frames
    idx = [round(i * total / n) % total for i in range(n)]
    frames = []
    for i in idx:
        gif.seek(i)
        frames.append(gif.convert("RGB").copy())
    return frames


def union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def fit_cell(img, box):
    """
    用全局包围盒做统一裁切与缩放。
    不能按每帧各自的 bbox 缩放 —— 回响粒会飘进飘出，逐帧 bbox 不同，
    缩放比就会逐帧变化，播放时 Echo 会一跳一跳地抖。
    """
    crop = img.crop(box)
    m = int(CELL * 0.05)
    avail = CELL - m * 2
    s = min(avail / crop.width, avail / crop.height)
    crop = crop.resize((max(1, int(crop.width * s)),
                        max(1, int(crop.height * s))), Image.LANCZOS)
    cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    cell.alpha_composite(crop, ((CELL - crop.width) // 2,
                                (CELL - crop.height) // 2))
    return cell


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "echo.png"
    # 先抠完所有帧并求全局包围盒，再统一裁切，保证各行各帧同一比例
    keyed_rows = []
    box = None
    for status, gif in ROWS:
        frames = [keyed(f) for f in pick_frames(os.path.join(ECHO, gif), FRAMES)]
        for f in frames:
            box = union(box, f.getchannel("A").getbbox())
        keyed_rows.append((status, gif, frames))
    print(f"  全局包围盒 {box}  ({box[2]-box[0]}x{box[3]-box[1]})")

    sheet = Image.new("RGBA", (CELL * FRAMES, CELL * len(ROWS)), (0, 0, 0, 0))
    for r, (status, gif, frames) in enumerate(keyed_rows):
        for c, f in enumerate(frames):
            sheet.alpha_composite(fit_cell(f, box), (c * CELL, r * CELL))
        print(f"  行 {r} {status:<10} <- {gif}")
    sheet.save(out)
    print(f"已生成 {out}  {sheet.width}x{sheet.height}")


if __name__ == "__main__":
    main()
