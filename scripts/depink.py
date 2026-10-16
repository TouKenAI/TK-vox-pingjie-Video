#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""depink.py —— 把道具**内部**的洋红反弹光压回中性纸色（V3.34 从 production23 提升为共享工具）。

为什么需要：StepFun 的洋红底会把粉光弹到物体上。`cutout_key --despill` 只削**边缘半透明带**，
体内实心像素它不动，于是浅色底上一眼看出"这道具是粉紫的"。p23 实测 prop_hourglass 体内
1337px、prop_blinds 387px、prop_colorcard 307px 是洋红族。

判据是"G 为最小通道且 R、B 同时高于它"这条洋红/紫罗兰签名，实测要松到 R>G+10 且 B>G+6
才盖得住**软粉反弹光**（收紧到 +22/+18 时撕边上的淡紫与粉雾都还在）。

⚠ 它是**修**不是**门**：粉色主体（百叶的粉叶片、粉色价签）体内本来就有洋红族像素，
所以"体内有洋红"不能当 FAIL 判据（标定过，会误伤）。--check 只报数并标出"仍偏高"的件，
改不改由人看棋盘图决定。

用法:
  py -3.14 scripts/depink.py <项目>                # 就地改 assets/source/prop_*.png，旧版进 qa/prev_assets/
  py -3.14 scripts/depink.py <项目> --check        # 只报数不改
  py -3.14 scripts/depink.py <项目> --glob 'prop_phone_*.png'
  py -3.14 scripts/depink.py <项目> --json-out qa/depink.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def pink_mask(rgb) -> np.ndarray:
    """⚠ 必须先升位宽：uint8 下 `g + 22` 在 g>233 时**回绕成小数**，
    于是"米白纸张"整片被判成洋红(p23 首版 --check 报 prop_ticket 13 万 px 假污染)。"""
    r, g, b = (rgb[:, :, i].astype(np.int16) for i in range(3))
    return (r > g + 10) & (b > g + 6)


def depink_array(rgba: np.ndarray) -> tuple[np.ndarray, int]:
    out = rgba.astype(np.int16).copy()
    rgb = out[:, :, :3]
    al = out[:, :, 3]
    m = pink_mask(rgb) & (al > 200)
    if not m.any():
        return out, 0
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    drop_r = np.maximum(r[m] - (g[m] + 6), 0)
    drop_b = np.maximum(b[m] - (g[m] + 4), 0)
    r[m] = r[m] - drop_r
    b[m] = b[m] - drop_b
    g[m] = np.clip(g[m] + (drop_r + drop_b) // 2, 0, 255)   # 补回明度，避免染成灰洞
    return out, int(m.sum())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--check", action="store_true", help="只报数，不写盘")
    ap.add_argument("--glob", default="prop_*.png", help="assets/source 下的匹配模式，默认 prop_*.png")
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args()

    src = a.project.resolve() / "assets" / "source"
    files = sorted(src.glob(a.glob))
    if not files:
        # 空输入必须 FAIL：路径打错时"0 个道具 0 污染 PASS"是最骗人的绿
        raise SystemExit(f"[FAIL] {src} 下没有匹配 {a.glob} 的文件 —— 先跑抠图，或检查 --glob")
    bak = a.project.resolve() / "qa" / "prev_assets"
    rows, changed = [], 0
    for p in files:
        before = np.array(Image.open(p).convert("RGBA"))
        n0 = int((pink_mask(before[:, :, :3]) & (before[:, :, 3] > 200)).sum())
        out, _ = depink_array(before)
        after = int((pink_mask(out[:, :, :3]) & (out[:, :, 3] > 200)).sum())
        flag = ""
        if n0 > 120 and after > n0 * 0.25:
            flag = "  <-- 仍偏高：要么重抽图，要么这件本来就是粉色主体(看棋盘图再定)"
        print(f"{p.name:26s} 体内粉紫 {n0:6d} → {after:6d}{flag}")
        rows.append({"file": p.name, "before": n0, "after": after})
        if n0 and after < n0 and not a.check:
            bak.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, bak / p.name)
            Image.fromarray(out.astype(np.uint8), "RGBA").save(p)
            changed += 1
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps({"glob": a.glob, "rows": rows}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    if a.check:
        print("(--check: 未写盘)")
        return 0
    print(f"✓ 去粉染写回 {changed} 个道具（旧版在 qa/prev_assets/）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
