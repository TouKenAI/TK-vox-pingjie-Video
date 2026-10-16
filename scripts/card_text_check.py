#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""card_text_check.py <项目目录> —— 字卡内容存在性门(p25 复盘机制化)。

p25 事故: 55 张字卡里 30 张是坏的——20 张奶油面板画奶油字(生成器把 CREAM 当墨字传给
panel=True → 隐形), 10 张临时补卡把文件名 id 当文案。六道渲前门+渲染+qa_deliver 全绿:
**没有任何门查"卡上有没有字/是不是登记过的卡"**, 是纯测试盲区, 目检接触表才抓住。

本门只做两类**存在性判据**(判"字对不对"无 OCR 门, 归接触表人眼——本门同时产出接触表):
  1) 登记完整性: assets/text/*.png 顶层每张必须在 qa/card_manifest.json 有条目,
     manifest 由卡片生成脚本落盘(p25 教训: 临时补的卡不回写生成脚本, 重跑即回退)。
     有条目但盘上无文件 = 生成器与账本漂移, 同样 FAIL。
  2) 内容存在性:
     - 面板卡(opaque≥75%): 把 alpha 向内腐蚀 13px 取**内部**(排除面板自己的描边),
       内部必须有"墨"——与面板填充色 maxΔRGB>60 的像素 ≥0.5%。奶油字画奶油板(Δ=0)
       在这里当场红; 红字/墨字正常过。无此腐蚀, 黑描边自己就冒充墨(字与描边同色)。
     - 裸字卡(opaque<75%): 须有不透明像素, 且不透明像素平均亮度须离开 film 底色
       (palette.json 的 bg, 只认三个 0-255 十进制数)±50 —— 深字画深底在这里红。
     - manifest 声明 "blank": true 的卡(实体板, 如 p25 的四壁)跳过内容检查。

退出码: 任何 FAIL → 1。qa/card_manifest.json 缺失 = FAIL(生成器未接 manifest,
先升级生成器再渲——没有账本的门是空转)。
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from PIL import Image, ImageFilter

ERODE_PX = 13          # 面板描边宽 7 + AA ≈ 13, 腐蚀掉边框环
INK_DELTA = 60         # 与面板填充色的 maxΔRGB 阈值
# p25 全卡标定: 有字卡内部墨占比最小 15.1%(c_human), 坏卡(奶油字画奶油板)0-0.3%。
# 0.02 居中取值: 对真实卡 7.5× 余量, 对 AA 噪声 7× 余量。
INK_SHARE = 0.02
BG_LUMA_GAP = 50       # 裸字卡与 film 底色的最小亮度差
PANEL_OPAQUE = 0.75    # opaque 占比 ≥ 此值按面板卡判


def _parse_bg(palette_path: Path) -> tuple[int, int, int]:
    """palette.json 的 bg 只认三个 0-255 十进制数(palette_oklch 同款规矩)。"""
    try:
        raw = json.loads(palette_path.read_text(encoding="utf-8")).get("bg", "")
        parts = [p for p in str(raw).split(",")]
        if len(parts) == 3:
            vals = [int(p.strip()) for p in parts]
            if all(0 <= v <= 255 for v in vals):
                return vals[0], vals[1], vals[2]
    except Exception:
        pass
    return 26, 28, 38


def _luma(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def analyze(path: Path, bg_luma: float) -> dict:
    im = Image.open(path).convert("RGBA")
    alpha = im.getchannel("A")
    px = im.load()
    w, h = im.size
    opaque = [(x, y) for y in range(0, h, 2) for x in range(0, w, 2) if px[x, y][3] >= 200]
    total = (w // 2 + 1) * (h // 2 + 1)
    ratio = len(opaque) / max(1, total)
    info = {"file": path.name, "opaque_ratio": round(ratio, 3)}
    if ratio < 0.02:
        info["verdict"] = "empty"
        return info
    if ratio >= PANEL_OPAQUE:
        # 面板卡: 腐蚀 alpha 取内部, 内部找与填充色不同的墨
        eroded = alpha.filter(ImageFilter.MinFilter(ERODE_PX * 2 + 1))
        ep = eroded.load()
        inner = [(x, y) for (x, y) in opaque if ep[x, y] >= 200]
        if len(inner) < 50:
            info["verdict"] = "no_interior"
            return info
        fills = collections.Counter(px[x, y][:3] for (x, y) in inner[::3])
        fill = fills.most_common(1)[0][0]
        ink = sum(1 for (x, y) in inner
                  if max(abs(px[x, y][0] - fill[0]), abs(px[x, y][1] - fill[1]),
                         abs(px[x, y][2] - fill[2])) > INK_DELTA)
        info.update(fill=fill, ink_share=round(ink / len(inner), 4),
                    verdict="ok" if ink / len(inner) >= INK_SHARE else "invisible_ink")
        return info
    # 裸字卡: 有内容且与深底可读
    lum = sum(_luma(px[x, y][:3]) for (x, y) in opaque) / len(opaque)
    info.update(luma=round(lum, 1),
                verdict="ok" if abs(lum - bg_luma) >= BG_LUMA_GAP else "low_contrast")
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    a = ap.parse_args()
    proj = a.project.resolve()
    text_dir = proj / "assets" / "text"
    pngs = sorted(text_dir.glob("*.png"))
    if not pngs:
        print("FAIL: assets/text/ 无字卡——无东西可判不报 PASS(§77②)", file=sys.stderr)
        return 1
    mf = proj / "qa" / "card_manifest.json"
    if not mf.exists():
        print(f"FAIL: {mf} 不存在——卡片生成器未接 manifest(p25 教训: 没有账本的门是空转)。"
              f"在生成脚本里收集 (name, text, blank) 并写本文件后再渲。", file=sys.stderr)
        return 1
    manifest = {c["name"]: c for c in json.loads(mf.read_text(encoding="utf-8"))["cards"]}
    bg_luma = _luma(_parse_bg(proj / "palette.json"))

    errors, rows = [], []
    for p in pngs:
        name = p.stem
        ent = manifest.pop(name, None)
        if ent is None:
            errors.append(f"{name}.png 未登记在 card_manifest.json —— 临时补的卡必须回写生成脚本"
                          f"(p25: 10 张 id 文案卡全部来自脚本外临时生成)")
            rows.append((name, "UNREGISTERED"))
            continue
        if ent.get("blank"):
            rows.append((name, "blank(声明)"))
            continue
        info = analyze(p, bg_luma)
        v = info["verdict"]
        rows.append((name, f"{v} {info.get('ink_share', info.get('opaque_ratio'))}"))
        if v == "invisible_ink":
            errors.append(f"{name}.png 面板内部无墨(墨像素 {info['ink_share']:.1%} < {INK_SHARE:.1%})"
                          f" —— 字与面板同色(隐形)或漏画, p25 的 20 张空白卡即此签名")
        elif v == "low_contrast":
            errors.append(f"{name}.png 裸字平均亮度 {info['luma']} 距 film 底色不足 {BG_LUMA_GAP}"
                          f" —— 深字画深底不可读")
        elif v == "empty":
            errors.append(f"{name}.png 几乎全透明(empty)却未声明 blank —— 漏画")
        elif v == "no_interior":
            errors.append(f"{name}.png 找不到面板内部(腐蚀后无像素) —— 面板过小或异形, 人工核")
    for name in sorted(manifest):
        errors.append(f"card_manifest.json 登记了 {name} 但 assets/text/{name}.png 不在盘上 —— 账实漂移")
        rows.append((name, "MISSING"))

    # 接触表(诊断件): 判"文案对不对"只能靠人眼, 本门不装 OCR 假门
    try:
        cols, cw, chh, lab = 8, 240, 110, 22
        rows_n = (len(pngs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rows_n * (chh + lab)), (26, 28, 38))
        from PIL import ImageDraw
        d = ImageDraw.Draw(sheet)
        for i, p in enumerate(pngs):
            im = Image.open(p).convert("RGBA")
            im.thumbnail((cw - 12, chh - 12))
            x, y = (i % cols) * cw, (i // cols) * (chh + lab)
            sheet.paste(im, (x + 6, y + 6), im)
            d.text((x + 6, y + chh + 2), p.stem, fill=(255, 255, 120))
        sheet.save(proj / "qa" / "card_text_sheet.png")
    except Exception as e:
        print(f"  [WARN] 接触表生成失败: {e}")

    for name, verdict in rows:
        print(f"  [{'  ok' if 'ok' in verdict or 'blank' in verdict else 'FAIL'}] {name:16s} {verdict}")
    n_blank = sum(1 for _, v in rows if 'blank' in v)
    print(f"SUMMARY card_text: {len(pngs)} 张 (blank声明 {n_blank}) | "
          f"unreg/missing={sum(1 for _, v in rows if v in ('UNREGISTERED', 'MISSING'))} "
          f"invisible={sum(1 for _, v in rows if v.startswith('invisible'))}")
    if errors:
        print("=== FAIL ===")
        for m in errors:
            print("  " + m)
        return 1
    print("PASS: 字卡登记完整, 面板有墨/裸字可读(文案对错请目检 qa/card_text_sheet.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
