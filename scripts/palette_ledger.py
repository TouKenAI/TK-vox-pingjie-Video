#!/usr/bin/env python3
"""V8.1 配色账本 —— 防"换汤不换药"(隐喻账本防概念撞车,palette 防配色撞车)。

V8.1 升级:颜色距离从一维色相换成 HSL 三维加权(色相/饱和度/明度)——V7.1.1 只用色相会
  漏判"同色不同明度"或"同明度不同色相"的撞色(米白+米橙与纯红+深红差异被高估)。
HSL 权重: h=0.5(主导) / s=0.25(色彩浓度) / v=0.25(明度差异)
阈值: 相似度 ≥0.7 = 撞色(总距离 ≤0.30)

每个 production 一个 palette.json(放 assets/ 下),格式:
{
  "colors": {
    "主色1": "#FFC75A",
    "主色2": "#728CB1",
    "主色3": "#46A39A",
    "主色4": "#F5F0E4",
    "强调色": "#E6554B"
  },
  "type": "knowledge"  // 复用 detect_genre 类型
}
账本: 账号级 palettes.json(工作区根),格式:
{
  "production13": {"colors": {"主色1": "#FFC75A", ...}, "preview": "palettes_preview/production13.png"},
  "production14": {...}
}

V8.1.1 修复(一次性原理审查):
  ① add 模式此前完全不可用:argparse 位置参数贪婪吞掉后置 --film(bpo-9338)→ 改
    parse_intermixed_args,色值与 --film/--ledger 可任意顺序混排;
    preview 色条 Image.new 把颜色三元组当尺寸传 → ValueError,已改 (宽, 高, 颜色)。
  ② check 邻片从"字母序末 3"改为"片名数字序最近 3"(旧版 production9 会排在
    production14 之后,把 12 部片前的老片当邻居、真邻居反被排除)。

用法(色值位置参数传 4~5 个,与选项任意顺序混排):
  python palette_ledger.py check "#FFC75A" "#728CB1" "#46A39A" "#F5F0E4" "#E6554B" --film production15
  → 与最近 3 片的配色比对;HSL 相似度 ≥0.7 提示换主色
  python palette_ledger.py add "#FFC75A" "#728CB1" "#46A39A" "#F5F0E4" "#E6554B" --film production15
"""
from __future__ import annotations

import argparse
import json
import re
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hsv(r: int, g: int, b: int) -> tuple:
    mx, mn = max(r, g, b), min(r, g, b)
    df = mx - mn
    if mx == mn:
        h = 0
    elif mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = 60 * ((b - r) / df) + 120
    else:
        h = 60 * ((r - g) / df) + 240
    s = 0 if mx == 0 else df / mx
    v = mx / 255
    return h, s, v


def palette_distance(pa: dict, pb: dict) -> float:
    """V8.1:HSL 三维加权距离(0-1,越小越相似)。
    权重 h=0.5/s=0.25/v=0.25。返回 5 色(4 主色+1 强调色)的平均距离。
    """
    if not pa or not pb: return 1.0
    ca = list(pa.values())
    cb = list(pb.values())
    if len(ca) != len(cb): return 1.0
    W_H, W_S, W_V = 0.5, 0.25, 0.25
    diffs = []
    for a, b in zip(ca, cb):
        ha, sa, va = rgb_to_hsv(*hex_to_rgb(a))
        hb, sb, vb = rgb_to_hsv(*hex_to_rgb(b))
        # 色相差:取最短弧(0-180 → 0-1)
        dh = min(abs(ha - hb), 360 - abs(ha - hb)) / 180.0
        ds = abs(sa - sb)
        dv = abs(va - vb)
        d = (W_H * dh + W_S * ds + W_V * dv) / (W_H + W_S + W_V)
        diffs.append(d)
    return sum(diffs) / len(diffs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["check", "add"])
    ap.add_argument("hexes", nargs="*", help="色值列表(check/add 共用,4~5 个 #RRGGBB,位置参数)")
    ap.add_argument("--film", required=True)
    ap.add_argument("--ledger", type=Path, default=None)
    # V8.1.1: parse_intermixed_args 修位置参数贪婪吞掉 --film 的 argparse 贪婪匹配问题
    a = ap.parse_intermixed_args()

    ledger_path = a.ledger
    if ledger_path is None:
        for base in [Path.cwd(), *Path.cwd().parents]:
            if (base / "palettes.json").exists():
                ledger_path = base / "palettes.json"
                break
            if (base / ".env").exists():
                ledger_path = base / "palettes.json"
                break
        ledger_path = ledger_path or Path.cwd() / "palettes.json"

    book = {}
    if ledger_path.exists():
        book = json.loads(ledger_path.read_text(encoding="utf-8"))

    if a.action == "add":
        if not a.hexes or len(a.hexes) < 4:
            sys.exit('用法: add "#RRGGBB"x4~5 --film productionN [--ledger 路径]')
        colors = {"主色1": a.hexes[0], "主色2": a.hexes[1], "主色3": a.hexes[2], "主色4": a.hexes[3]}
        if len(a.hexes) >= 5: colors["强调色"] = a.hexes[4]
        # preview 外置到 palettes_preview/{film}.png, 账本只存路径(防账本体积随片数膨胀)
        preview_path = ledger_path.parent / "palettes_preview" / f"{a.film}.png"
        if Image and a.hexes:
            strip = Image.new("RGB", (800, 80))
            cw = 800 // len(a.hexes)
            for i, hx in enumerate(a.hexes):
                # V8.1.1: Image.new 第三参才是颜色——旧版把颜色三元组当尺寸传 → ValueError
                strip.paste(Image.new("RGB", (cw, 80), hex_to_rgb(hx)), (i*cw, 0, (i+1)*cw, 80))
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            strip.save(preview_path)
        entry = {"colors": colors, "preview": preview_path.as_posix()}
        book[a.film] = entry
        ledger_path.parent.mkdir(exist_ok=True, parents=True)
        ledger_path.write_text(json.dumps(book, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"recorded {a.film}: {colors}")
    else:  # check
        if len(a.hexes) < 4:
            # 旧版只挡 0 个色值, 传 1~3 个会在下一行 IndexError 崩栈
            sys.exit(f"用法: check #FFAABB #BBCCDD #DDCCBB #AAFFBB --film productionN (至少 4 色, 现得到 {len(a.hexes)})")
        cur = {"主色1": a.hexes[0], "主色2": a.hexes[1], "主色3": a.hexes[2], "主色4": a.hexes[3]}
        if len(a.hexes) >= 5: cur["强调色"] = a.hexes[4]
        print(f"输入色: {cur}")
        # V8.1.1: 按片名内嵌数字取最近 3 片(旧版字母序会让 production9 排在 production14 后, 邻居选错)
        def _film_num(k: str) -> int:
            m = re.search(r"(\d+)", k)
            return int(m.group(1)) if m else 0
        neighbors = sorted((k for k in book if k != a.film), key=_film_num)[-3:]
        flagged = False
        for prev in neighbors:
            prev_colors = book[prev].get("colors", {})
            dist = palette_distance(cur, prev_colors)
            sim = 1 - dist
            mark = "✓" if sim < 0.7 else "⚠️"
            if sim >= 0.7: flagged = True
            print(f"  {mark} vs {prev} ({dist:.2f} 距离 / 相似度 {sim:.0%})")
        if flagged:
            print("\n⚠️ 相似度 >70% — 建议调整主色之一")
            sys.exit(1)
        print("PASS: 与邻近片配色差异足")


if __name__ == "__main__":
    main()
