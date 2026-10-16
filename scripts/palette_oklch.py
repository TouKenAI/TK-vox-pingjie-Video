#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.3 OKLCH 感知均匀配色系统 + palette_check 门禁（纯标准库，确定性）。

为什么：旧 palette_ledger 用 HSL 加权欧氏距离判"撞色"，HSL 非感知均匀——
"米白 vs 纯白"数值差很小却肉眼不同、"高饱和 vs 低饱和同色相"数值差大却像同族。
OKLab/OKLCH 是感知均匀色彩空间：ΔE 越大=肉眼越不同，L 差=明度差(可读性关键)。

能力:
  rgb↔oklch 换算 · oklab ΔE(感知色差) · WCAG 对比度 · 明度可读性(ΔL)
  ramp: 从主色派生明度色阶/类比色(建配色方案)
  check <项目>: 门禁——①片内 文字/背景 对比度达标 ②与近邻片调色板感知差异足够(防撞色)

用法:
  py palette_oklch.py rgb 200,40,52
  py palette_oklch.py delta 200,40,52 224,106,32
  py palette_oklch.py contrast 236,233,225 30,40,55          # 文字色 背景色
  py palette_oklch.py ramp 200,40,52 --steps 5
  py palette_oklch.py check <项目目录> --palette production2/palette.json
退出码: check 全过 0 / 有 HARD 1。
palette.json 约定: {"bg":"R,G,B","fg":"R,G,B","accent":"R,G,B", "text_on_bg":[["R,G,B","R,G,B"],...]}
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

# ---------- 核心换算 ----------
def _srgb_to_linear(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def _linear_to_srgb(c):
    v = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0, min(255, round(v * 255)))

def rgb_to_oklab(rgb):
    r, g, b = [(_srgb_to_linear(x)) for x in rgb]
    l = 0.4122214708*r + 0.5363325363*g + 0.0514459929*b
    m = 0.2119034982*r + 0.6806995451*g + 0.1073969566*b
    s = 0.0883024619*r + 0.2817188376*g + 0.6299787005*b
    l_, m_, s_ = l ** (1/3) if l > 0 else 0, m ** (1/3) if m > 0 else 0, s ** (1/3) if s > 0 else 0
    L = 0.2104542553*l_ + 0.7936177850*m_ - 0.0040720468*s_
    A = 1.9779984951*l_ - 2.4285922050*m_ + 0.4505937099*s_
    B = 0.0259040371*l_ + 0.7827717662*m_ - 0.8086757660*s_
    return (L, A, B)

def oklab_to_rgb(lab):
    L, A, B = lab
    l_ = L + 0.3963377774*A + 0.2158037573*B
    m_ = L - 0.1055613458*A - 0.0638541728*B
    s_ = L - 0.0894841775*A - 1.2914855480*B
    l, m, s = l_**3, m_**3, s_**3
    r = +4.0767416621*l - 3.3077115913*m + 0.2309699292*s
    g = -1.2684380046*l + 2.6097574011*m - 0.3413193965*s
    b = -0.0041960863*l - 0.7034186147*m + 1.7076147010*s
    return (_linear_to_srgb(r), _linear_to_srgb(g), _linear_to_srgb(b))

def rgb_to_oklch(rgb):
    L, A, B = rgb_to_oklab(rgb)
    C = math.hypot(A, B)
    H = math.degrees(math.atan2(B, A)) % 360
    return (L, C, H)

def oklab_delta(rgb1, rgb2):
    a, b = rgb_to_oklab(rgb1), rgb_to_oklab(rgb2)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def wcag_lum(rgb):
    r, g, b = [_srgb_to_linear(x) for x in rgb]
    return 0.2126*r + 0.7152*g + 0.0722*b

def wcag_contrast(fg, bg):
    l1, l2 = wcag_lum(fg), wcag_lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

def _parse_rgb(s):
    s = str(s).strip().lstrip("#")
    if "," in s:
        parts = [x.strip() for x in s.split(",")]
        # 只认"三个十进制数"这种 RGB。palette.json 里的散文字段(如 style_primary)
        # 常带中文逗号分隔的说明, 旧版直接 int() 会把配色门整个崩掉(V3.22 审查后 p15 首次触发)。
        if len(parts) < 3 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts[:3]):
            raise ValueError(f"不是合法 RGB 三元组: {s!r}")
        return tuple(int(x) for x in parts[:3])
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) == 6:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    raise ValueError(f"无法解析颜色: {s!r}")

def _is_rgbish(v):
    try:
        _parse_rgb(v); return True
    except Exception:
        return False

def ramp(rgb, steps=5, dl=0.14):
    """从主色沿 OKLCH 派生明度色阶(等 ΔL)，用于卡片底/文字/强调的成套色。"""
    L, C, H = rgb_to_oklch(rgb)
    out = []
    for i in range(steps):
        Li = max(0.05, min(0.99, L + (i - steps // 2) * dl))
        out.append(oklab_to_rgb((Li, C * math.cos(math.radians(H)), C * math.sin(math.radians(H)))))
    return out

# ---------- 门禁 ----------
def check_palette(proj: Path, palette_file: Path):
    hard, warn, info = [], [], []
    # 项目参数不是装饰：旧版只用 proj.parent 去找 palettes.json，找不到就回退 CWD，
    # 于是 `check 随便一个不存在的目录 --palette 真配色` 会拿 CWD 的账本比、报 rc=0 PASS。
    if not proj.is_dir():
        print(f"✗ FAIL: 项目目录不存在: {proj} —— 路径写错不算通过"); return 1
    pal = json.loads(palette_file.read_text(encoding="utf-8"))
    # ① 片内可读性: 每对 文字/背景 需 WCAG≥3(大字) 且 OKLCH ΔL≥0.4
    pairs = pal.get("text_on_bg", [])
    if "fg" in pal and "bg" in pal:
        pairs.append([pal["fg"], pal["bg"]])
    for pr in pairs:
        fg, bg = _parse_rgb(pr[0]), _parse_rgb(pr[1])
        cr = wcag_contrast(fg, bg)
        dl = abs(rgb_to_oklch(fg)[0] - rgb_to_oklch(bg)[0])
        name = f"{pr[0]}on{pr[1]}"
        if cr < 3.0:
            hard.append(f"[可读性] {name}: WCAG {cr:.2f} < 3 文字看不清(必须改)")
        elif cr < 4.5 or dl < 0.4:
            warn.append(f"[可读性] {name}: WCAG {cr:.2f} ΔL {dl:.2f}——大字强调可用,正文偏小建议提对比")
        else:
            info.append(f"可读性 {name}: WCAG {cr:.2f} ΔL {dl:.2f} ✓")
    # ② 与近邻片调色板感知差异(读 palettes.json, 用 OKLab ΔE)
    # 账本一律按"项目父目录 → 本脚本所在仓库根"确定性解析，**绝不回退 CWD**：
    # 回退 CWD 等于"在别的目录跑就拿空账本比"，那是 PASS(0 次)。
    pl = proj.parent / "palettes.json"
    if not pl.exists():
        pl = Path(__file__).resolve().parents[1] / "palettes.json"
    if not pl.exists():
        hard.append("[账本] 找不到 palettes.json —— 跨片撞色无从比较，先跑 palette_ledger.py add")
    if pl.exists():
        data = json.loads(pl.read_text(encoding="utf-8"))
        cur = [_parse_rgb(v) for k, v in pal.items()
               if k not in ("text_on_bg", "film", "semantic") and isinstance(v, str) and _is_rgbish(v)]
        films = [f for f in data.keys() if f != pal.get("film")]
        for f in films[-3:]:
            entry = data[f]
            color_map = entry.get("colors") if isinstance(entry, dict) and isinstance(entry.get("colors"), dict) else entry
            other = []
            for k, v in color_map.items():
                if isinstance(v, str) and k not in ("film", "preview"):
                    try:
                        other.append(_parse_rgb(v))
                    except Exception:
                        pass
            if not other:
                continue
            # 只用有彩色(彩度 C≥0.05)判撞色——中性白/黑/灰两片都有, 不该算撞
            chrom_cur = [c for c in cur if rgb_to_oklch(c)[1] >= 0.05]
            chrom_other = [o for o in other if rgb_to_oklch(o)[1] >= 0.05]
            if not chrom_cur or not chrom_other:
                continue
            dists = [min(oklab_delta(c, o) for o in chrom_other) for c in chrom_cur]
            avg = sum(dists) / len(dists)
            if avg < 0.08:
                hard.append(f"[撞色] 与 {f} 平均感知差 ΔE {avg:.3f} < 0.08——太像,换主色/强调色")
            elif avg < 0.15:
                warn.append(f"[撞色] 与 {f} 平均 ΔE {avg:.3f}(<0.15 偏近)")
            else:
                info.append(f"与 {f} ΔE {avg:.3f} ✓")
    for i in info: print("  ✓", i)
    for w in warn: print("  WARN", w)
    for h in hard: print("  ✗", h)
    if not (info or warn or hard):
        # §81①: PASS(0 次) 不是通过。palette.json 里既没有 text_on_bg 也没有 fg/bg 时，
        # 旧版一条对比都没算过却打印 "=== palette_check PASS ==="。
        print(f"✗ FAIL: 本门 0 次判定 —— {palette_file} 里没有可解析的 text_on_bg / fg+bg 色对，"
              f"配色未声明，不是通过"); return 1
    if hard:
        print("=== palette_check FAIL ==="); return 1
    print("=== palette_check PASS === 配色感知区分度 + 可读性达标")
    return 0

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("rgb"); p.add_argument("color")
    p = sub.add_parser("delta"); p.add_argument("a"); p.add_argument("b")
    p = sub.add_parser("contrast"); p.add_argument("fg"); p.add_argument("bg")
    p = sub.add_parser("ramp"); p.add_argument("color"); p.add_argument("--steps", type=int, default=5)
    p = sub.add_parser("check"); p.add_argument("project", type=Path); p.add_argument("--palette", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "rgb":
        print("OKLCH:", [round(x, 3) for x in rgb_to_oklch(_parse_rgb(a.color))])
    elif a.cmd == "delta":
        d = oklab_delta(_parse_rgb(a.a), _parse_rgb(a.b))
        tag = "肉眼明显不同" if d > 0.15 else ("可辨差异" if d > 0.08 else "偏近/易混")
        print(f"ΔE_oklab = {d:.3f}  → {tag}")
    elif a.cmd == "contrast":
        cr = wcag_contrast(_parse_rgb(a.fg), _parse_rgb(a.bg))
        dl = abs(rgb_to_oklch(_parse_rgb(a.fg))[0] - rgb_to_oklch(_parse_rgb(a.bg))[0])
        print(f"WCAG {cr:.2f} ({'AA正文✓' if cr>=4.5 else '大字✓' if cr>=3 else '不达标✗'})  ΔL {dl:.2f}")
    elif a.cmd == "ramp":
        for c in ramp(_parse_rgb(a.color), a.steps):
            print(f"  rgb{c}  OKLCH{[round(x,2) for x in rgb_to_oklch(c)]}")
    elif a.cmd == "check":
        # V3.26: 旧版把 palette 读不到/色值解析不了的**裸 traceback** 直接甩给用户
        # (§57⑤ 那批"缺输入即吐 traceback"的漏网之鱼)。rc 仍是 1(fail-closed), 但要看得懂。
        try:
            sys.exit(check_palette(a.project, a.palette))
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            print(f"[FAIL] 配色门禁无法执行 —— {type(e).__name__}: {e}\n"
                  f"  palette={a.palette}  项目={a.project}\n"
                  f"  要求: palette.json 存在且 bg/fg/accent/accent2 均为『三个 0-255 十进制数』"
                  f"(如 \"233,231,222\"); 带逗号的散文字段会被误当 RGB(§58④ 已修过一次)", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
