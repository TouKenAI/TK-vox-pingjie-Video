#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旁白在时间轴上的摆法 —— 单一事实源。

混音器按这个规则放声音，任何"画面有没有对上口播"的检查都必须按同一个规则算，
否则两边各写一份常数，改一边就静默错位。

    本场第一段起于 scene_start + LEAD
    之后每段之间留 GAP

produce.py 用它摆 NARRATION；polycheck_v66 用它把"念到某句的时刻"换算到场内坐标。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

LEAD = 0.3
GAP = 0.12


def scene_chunks(project: Path) -> dict[int, list[str]]:
    """场号 → 该场内按口播顺序排列的 chunk id 列表。"""
    out: dict[int, list[str]] = {}
    for c in json.loads((project / "chunks.json").read_text(encoding="utf-8-sig")):
        m = re.search(r"(\d+)", str(c.get("scene", "")))
        if not m:
            raise SystemExit(f"[FAIL] chunks.json {c.get('id')} 缺 scene 字段")
        out.setdefault(int(m.group(1)), []).append(c["id"])
    return out


def chunk_lead(project: Path, duration_of) -> dict[str, float]:
    """chunk id → 它在本场内的起点(秒)。duration_of(cid) 给该段旁白实测秒数。"""
    lead: dict[str, float] = {}
    for _sc, ids in scene_chunks(project).items():
        t = LEAD
        for cid in ids:
            lead[cid] = t
            t += duration_of(cid) + GAP
    return lead
