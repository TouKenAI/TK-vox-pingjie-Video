#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.5 结构多样守卫（③）：防"每条片都14场/100s"的宏观趋同。

按内容强度选结构档，并检查与近几片是否结构雷同。
档位: 快评 8-10场 · 标准 12-14场 · 深度 15-18场(V3.21 起这些**只是防趋同的场数参考**;
秒数是历史档位的量级标注, 不再作为片长目标——时长由文案字数自然决定)。

用法:
  py structure_plan.py recommend --chars 360 --energy 标准     # 给结构建议
  py structure_plan.py check <工作区根>                          # 扫各 productionN 场数/时长, 提示趋同
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

TIERS = {"快评": (8, 10, 55, 70), "标准": (12, 14, 90, 100), "深度": (15, 18, 110, 135)}
RATE_AT_110 = 4.90     # 字/秒 @speed 1.1(V3.21 实测口径, 同 check_script)
PACE_TO_VIDEO = 1.08


def recommend(chars, energy):
    """V3.21: 场数只是**防趋同的参考**; 时长不再规定, 由文案字数折算出来给人看。
    旧版打印"建议 12-14 场、成片 90-100s"读起来像配额, 而字数不设限后它必然与真实片长打架。"""
    sc_lo, sc_hi = TIERS.get(energy, TIERS["标准"])[:2]
    est_scenes = max(6, min(20, round(chars / 27)))  # ~每信息点一场
    narr = chars / RATE_AT_110
    print(f"内容 {chars} 字 / 强度 {energy} → 结构参考 {sc_lo}-{sc_hi} 场(防趋同用, 不是配额)")
    print(f"预计旁白 {narr:.0f}s → 成片约 {narr * PACE_TO_VIDEO:.0f}s(V3.21 不限时长, 由文案自然决定)")
    print(f"按字数自然分场≈{est_scenes} 场。")
    if not (sc_lo <= est_scenes <= sc_hi):
        print(f"  提示: 自然场数 {est_scenes} 与该档不符 → 按内容怎么分就怎么分, 别硬凑/硬砍成'{energy}{sc_hi}场'。")
    return 0


def check(root: Path):
    rows = []
    for proj in sorted(root.glob("production*")):
        if not (proj / "chunks.json").exists():
            continue
        n = len(list(proj.glob("scene_s*.json")))
        seg = proj / "splice_manifest.json"
        dur = None
        if seg.exists():
            dur = round(sum(e[1] for e in json.loads(seg.read_text(encoding="utf-8"))) / 30, 1)
        rows.append((proj.name, n, dur))
    for name, n, dur in rows:
        print(f"  {name}: {n} 场  {dur}s")
    # 空输入必须 FAIL(§77②)：一行都没有 = root 指错了目录，不是"没有趋同"。
    # 旧版这里无条件 return 0——本门在任何输入下都不会红，等于没有门。
    if not rows:
        print(f"✗ FAIL: {root} 下没有任何含 chunks.json 的 production* 目录 —— 无可比较, 这不是通过")
        return 1
    ns = [n for _, n, _ in rows if n]
    if len(ns) < 3:
        print(f"✗ FAIL: 只有 {len(ns)} 部片有场景数据(需 ≥3) —— 样本不足不报'多样性 OK'")
        return 1
    if max(ns) - min(ns) <= 1:
        print(f"⚠ 结构趋同: 近 {len(ns)} 片场数都在 {min(ns)}-{max(ns)}。下条按内容换档(快评/深度)，别都做成同一形状。")
        return 1
    print("结构多样性 OK（场数有变化）")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recommend"); r.add_argument("--chars", type=int, required=True); r.add_argument("--energy", default="标准", choices=list(TIERS))
    c = sub.add_parser("check"); c.add_argument("root", type=Path)
    a = ap.parse_args()
    if a.cmd == "recommend":
        sys.exit(recommend(a.chars, a.energy))
    sys.exit(check(a.root))


if __name__ == "__main__":
    main()
