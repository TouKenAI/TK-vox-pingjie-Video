#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bg_plan_check.py —— 背景是"每场一个空间"还是"一张墙纸轮用"（V3.34）。

**这道门量的就是用户那句"后面做的都没有比 p11 更好"里可量化的那一半。**
2026-09-27 对 12 部已交付片实测（背景复用率 = 独立背景数 / 场数）：

    p11 1.00   p12 1.00   p13 0.75   p14 1.00   p15 1.00   p16 1.00     ← 用户认可的年代
    p18 0.19   p19 0.15   p20 0.29   p21 0.25   p22 0.36   p23 0.45     ← 用户说变差的年代

分界干净得没有重叠。p18–p23 同一张"墙"在一部片里出现 5–10 次：观众在第 3 次看到它时，
这场戏就失去了"这是哪儿"的信息，画面自然显得薄。p11 每场一张专属背景，而且因为
**每场都要重新描述那个空间**，背景生图被迫画出摊位/柜台内景/房间这类有内部体积的结构
（目检 p11 bg_s08 与 p23 bg_store_front 的差异正是这个：一个是建筑，一面是贴了装饰的墙）。

所以这条门同时管住两件事：数量（每场一张）与动机（逼出"这场发生在哪个空间"的 prompt）。

两个时机：
  --plan   花钱前（pipeline ready --stage assets 调）：jobs_bg 里的背景条目数 ≥ chunks.json 的场数。
           少了就是打算复用，当场拦下，别等生完图才发现。
  默认     建场后（render_all 渲前链调）：从 scene_s*.json 量真实复用率，< min-uniq 拒渲。

书面豁免（创意决策权在人）：KICKOFF.md 一行 `bg_reuse_ok: <理由>`，空理由不算（有 RED 探针）。

退出码 0=过 / 1=拦 / 2=没有可量的输入（空项目，拒绝假装通过）
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass

EXEMPT_RE = re.compile(r"^\s*[`*>#\-\s]*bg_reuse_ok\s*[:：]\s*(.*?)\s*[`*]*\s*$", re.M)
BAD_WHY = {"豁免", "无", "N/A", "na", "-", "ok", "好"}


def scene_count(proj: Path) -> int:
    cj = proj / "chunks.json"
    if not cj.exists():
        return 0
    chunks = json.loads(cj.read_text(encoding="utf-8-sig"))
    return len({str(c.get("scene", "")).lower() for c in chunks if str(c.get("scene", "")).strip()})


def bg_jobs(proj: Path) -> list[str]:
    names = []
    for jf in sorted(proj.glob("jobs_bg*.json")) + sorted(proj.glob("jobs.json")):
        try:
            jobs = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        names += [str(j.get("name", "")) for j in jobs if str(j.get("name", "")).lower().startswith("bg")]
    return names


def read_exempt(proj: Path) -> tuple[bool, str]:
    k = proj / "KICKOFF.md"
    if not k.exists():
        return False, ""
    m = EXEMPT_RE.search(k.read_text(encoding="utf-8"))
    if not m:
        return False, ""
    why = m.group(1).strip().strip("「」\"'")
    if len(why) < 6 or why.lower() in BAD_WHY:
        return False, f"KICKOFF 写了 bg_reuse_ok 但理由不成立（{why!r}）——豁免必须说清为什么这部片允许背景墙轮用"
    return True, why


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--plan", action="store_true",
                    help="花钱前模式：只比 jobs_bg 背景条目数与 chunks.json 场数")
    ap.add_argument("--min-uniq", type=float, default=0.75,
                    help="独立背景数/场数 下限，默认 0.75（p13 实测 0.75 过，p23 的 0.45 拦）")
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args()
    proj = a.project.resolve()

    if a.plan:
        n_sc = scene_count(proj)
        if n_sc == 0:
            raise SystemExit(f"[FAIL] {proj}/chunks.json 没有带 scene 字段的段 —— 不知道要几个背景，拒绝放行生图")
        names = bg_jobs(proj)
        if not names:
            raise SystemExit(f"[FAIL] 没有 jobs_bg*.json / jobs.json 里的 bg 条目 —— 背景计划还没写")
        if len(names) < n_sc:
            # 书面豁免在两个时机都有效：单一空间题材（全片就在一个房间/一家店）本来就不该被逼着生 N 张
            exempt, why = read_exempt(proj)
            if exempt:
                print(f"⚠ [EXEMPT] 背景计划 {len(names)} 张 < 场数 {n_sc}，KICKOFF 已书面豁免：{why}")
                return 0
            raise SystemExit(
                f"[FAIL] 背景计划 {len(names)} 张 < 场数 {n_sc} —— 打算一张墙轮用 {n_sc} 场。\n"
                f"  p18–p23 六部'显得薄'的片复用率 0.15–0.45，p11–p16 全是 1.00（每场一个空间）。\n"
                f"  补到每场一张：背景 prompt 写清**这场发生在哪个空间**（柜台内景/货架间/售后窗口/…），\n"
                f"  而不是换一张墙纸。确实要复用就在 KICKOFF 写 `bg_reuse_ok: 理由`。")
        print(f"✓ 背景计划 {len(names)} 张 ≥ 场数 {n_sc}（每场一个空间）")
        return 0

    scenes = sorted(proj.glob("scene_s*.json"))
    if not scenes:
        raise SystemExit(f"[FAIL] {proj} 下没有 scene_s*.json —— 没东西可量，拒绝报 PASS")
    cnt: collections.Counter = collections.Counter()
    for sp in scenes:
        plan = json.loads(sp.read_text(encoding="utf-8-sig"))
        cnt[Path(plan["background"]["path"]).name] += 1
    uniq = len(cnt)
    ratio = uniq / len(scenes)
    top, tn = cnt.most_common(1)[0]
    rep = {"scenes": len(scenes), "unique_bg": uniq, "ratio": round(ratio, 3),
           "most_used": [top, tn], "per_bg": dict(cnt)}
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    line = (f"背景复用率 {uniq}/{len(scenes)} = {ratio:.2f}（门槛 {a.min_uniq}）"
            f"；最复用 {top}×{tn}")
    if ratio >= a.min_uniq:
        print(f"✓ {line}")
        return 0
    exempt, why = read_exempt(proj)
    if exempt:
        print(f"⚠ [EXEMPT] {line} —— KICKOFF 书面豁免：{why}")
        return 0
    print(f"[BLOCK] {line}")
    if why:
        print(f"  ⚠ {why}")
    print("  同一张背景在一部片里出现 3 次以上，观众就不再相信'这是另一个地方'，画面显薄。\n"
          "  修法：给被复用的场各生一张专属背景（prompt 写这场自己的空间），或把这场改到已有\n"
          "  的另一个空间里演；确实要复用（如全片就在一个房间）→ KICKOFF 写 `bg_reuse_ok: 理由`。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
