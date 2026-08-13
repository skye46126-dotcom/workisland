#!/usr/bin/env python3
"""
从 Echo 生成灵动岛的 5 个状态图标（idle / running / approval / complete / error）。

这套图标和桌宠精灵图是两套独立素材：桌宠走 pet-sprites，状态图标走
island/assets/status/*.svg，同时用在「暂无会话」空状态和胶囊的状态位上。
换了桌宠不会自动带过来，所以这里单独生成，避免应用里出现两个形象。

Echo 是平涂色块（全身 4 色），最近邻降采样到小网格后按横向同色游程合并成
<rect>，既保住块状质感，文件也小。输出沿用原有约定：32x32 viewBox +
shape-rendering=crispEdges。

用法：python3 tools/make-status-icons.py [输出目录]
"""
from PIL import Image
import os, sys

ECHO = os.path.expanduser(
    "~/wenjian/echo/design/fusai-video/08-素材与参考/little-echo/clips")

GRID = 32           # viewBox 边长，与原有图标一致
BODY_COLS = 27      # Echo 身体占的格数
CHAR_COLORS = [
    ((31, 27, 22), "ink"),
    ((60, 52, 44), "lid"),
    ((248, 242, 230), "eye"),
    ((196, 69, 45), "dot"),
]
PAPER = (236, 220, 191)
TOL = 46

# 状态 → 情绪。语义要对得上：等审批是「在等你回应」，所以用好奇而不是专注。
STATES = [
    ("idle",     "echo-calm.gif",      0),
    ("running",  "echo-focused.gif",   0),
    ("approval", "echo-curious.gif",   0),
    ("complete", "echo-happy.gif",     0),
    ("error",    "echo-sad.gif",       0),
]


def dist2(a, b):
    return (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2


def keyed(frame):
    """只保留角色色，纸底与接地阴影一律透明。"""
    im = frame.convert("RGB")
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    src, dst = im.load(), out.load()
    t2 = TOL * TOL
    for y in range(im.height):
        for x in range(im.width):
            p = src[x, y]
            if dist2(p, PAPER) < t2:
                continue
            best, bd = None, None
            for c, _ in CHAR_COLORS:
                d = dist2(p, c)
                if bd is None or d < bd:
                    best, bd = c, d
            if bd < t2:
                dst[x, y] = (*best, 255)
    return out


def load_frame(gif, index):
    im = Image.open(os.path.join(ECHO, gif))
    im.seek(index % im.n_frames)
    return keyed(im.convert("RGB").copy())


def to_grid(img):
    """裁到角色包围盒，最近邻降采样到 BODY_COLS 宽，居中放进 GRID 方格。"""
    bb = img.getchannel("A").getbbox()
    crop = img.crop(bb)
    rows = max(1, round(BODY_COLS * crop.height / crop.width))
    small = crop.resize((BODY_COLS, rows), Image.NEAREST)
    cell = Image.new("RGBA", (GRID, GRID), (0, 0, 0, 0))
    cell.alpha_composite(small, ((GRID - BODY_COLS) // 2, (GRID - rows) // 2))
    return cell


def classify(p):
    if p[3] < 128:
        return None
    best, bd = None, None
    for c, name in CHAR_COLORS:
        d = dist2(p[:3], c)
        if bd is None or d < bd:
            best, bd = name, d
    return best


def to_svg(cell):
    """按横向同色游程合并成 rect，比逐像素输出小一个数量级。"""
    px = cell.load()
    parts = []
    for y in range(GRID):
        x = 0
        while x < GRID:
            cls = classify(px[x, y])
            if cls is None:
                x += 1
                continue
            run = 1
            while x + run < GRID and classify(px[x + run, y]) == cls:
                run += 1
            parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{run}" height="1"/>')
            x += run
    style = (".ink{fill:#1F1B16}.lid{fill:#3C342C}"
             ".eye{fill:#F8F2E6}.dot{fill:#C4452D}.ground{fill:#ECDCBF}")
    # 纸色底板：灵动岛背景是纯黑 #000，而 Echo 身体是墨黑 #1F1B16，
    # 直接放上去几乎看不见（原来那套忍者图标用的是浅色布料，本就为黑底设计）。
    # 底板同时让状态图标和 app 图标是同一个「Echo 在纸上」的形象。
    ground = f'<rect class="ground" x="0" y="0" width="{GRID}" height="{GRID}" rx="7"/>'
    return (f'<svg width="56" height="56" viewBox="0 0 {GRID} {GRID}" '
            f'xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">\n'
            f'  <style>{style}</style>\n  {ground}\n  '
            + "\n  ".join(parts) + "\n</svg>\n")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for state, gif, idx in STATES:
        svg = to_svg(to_grid(load_frame(gif, idx)))
        path = os.path.join(out, f"{state}.svg")
        open(path, "w").write(svg)
        print(f"  {state:<9} <- {gif:<20} {len(svg):>5} 字节")


if __name__ == "__main__":
    main()
