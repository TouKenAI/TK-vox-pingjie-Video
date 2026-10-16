# -*- coding: utf-8 -*-
"""V8.1.8 make_countup.py —— 数字增长动画帧序列生成器(配合渲染器 seq_dir 层)

把"72%"这类数字做成 0→目标 逐帧跳数的 PNG 序列(如 36 帧=1.2s@30fps),
渲染器以 seq_dir 层引用, 帧间数字递增+末帧定格, 末帧可附强调放大(在 scene 里用 kf scale)。

用法:
  py make_countup.py --end 72 --suffix "%" --frames 36 --out-dir assets/text/count_72 \
     --size 200 --color "233,226,208" --accent "224,122,58" --accent-at 12
参数:
  --start 起始数字(默认 0)  --end 目标数字(必填)  --suffix 后缀(如 "%"/"亿"/"" )
  --prefix 前缀(如 "$"/"" )  --frames 总帧数(默认 36)  --out-dir 输出目录(必填)
  --size 字号(默认 180)  --color 主色 R,G,B(默认 CREAM 米色)  --accent 强调色(数字到达终值后)
  --accent-at 从第几帧起用强调色(默认最后一帧)
  --decimals 小数位数(把 end 当放大 10^N 的整数): --end 102 --decimals 2 → 滚到 1.02
输出: out_dir/frame_0000.png .. frame_{frames-1}.png(自动裁透明边, 每帧独立尺寸以容纳位数增长)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    raise SystemExit("no CJK-capable bold font found")


def render_text(text: str, size: int, color: tuple[int, int, int]) -> Image.Image:
    font = load_font(size)
    probe = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), text, font=font)
    pad = round(size * 0.25)
    w = bbox[2] - bbox[0] + pad * 2
    h = bbox[3] - bbox[1] + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font,
              fill=(*color, 255))
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--frames", type=int, default=36)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--size", type=int, default=180)
    ap.add_argument("--color", default="233,226,208")
    ap.add_argument("--accent", default="224,122,58")
    ap.add_argument("--accent-at", type=int, default=None)
    ap.add_argument("--decimals", type=int, default=0,
                    help="把 start/end 当作放大 10^N 的整数来滚动, 渲染成小数。"
                         "口播说'1.02 万亿'时传 --end 102 --decimals 2 → 0.00…1.02 万亿;"
                         "没有这一格, 小数只能做成静止字卡, 数字滚动层就废了")
    a = ap.parse_args()

    color = tuple(int(v) for v in a.color.split(","))
    accent = tuple(int(v) for v in a.accent.split(","))
    accent_at = a.accent_at if a.accent_at is not None else a.frames - 1
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def disp(v):
        return f"{v / (10 ** a.decimals):.{a.decimals}f}" if a.decimals else str(v)

    span = max(1, a.end - a.start)
    probe = render_text(f"{a.prefix}{disp(a.end)}{a.suffix}", a.size, color)
    for i in range(a.frames):
        ratio = i / max(1, a.frames - 1)
        # ease-out 缓动: 前快后慢, 更符合"冲刺到顶"
        eased = 1 - (1 - ratio) ** 2
        value = round(a.start + span * eased)
        if value > a.end:
            value = a.end
        text = f"{a.prefix}{disp(value)}{a.suffix}"
        use = accent if i >= accent_at else color
        img = render_text(text, a.size, use)
        # 位宽稳定: 所有帧对齐到最长文本宽度(避免增长时跳动)
        canvas = Image.new("RGBA", (max(img.width, probe.width), max(img.height, probe.height)),
                           (0, 0, 0, 0))
        canvas.alpha_composite(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2))
        canvas.save(out / f"frame_{i:04d}.png")

    print(f"[OK] {a.frames} 帧数字增长序列 → {out}/ (0→{a.end}{a.suffix}, ease-out, 末帧强调色)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
