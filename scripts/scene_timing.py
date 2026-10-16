#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.28 项目时间轴公共件 —— 帧预算与词级触发帧的**唯一算法**。

为什么从 production17/scene_timing.py 提上来：那套算法(照混音器排布反推帧预算)对每部片都一样,
留在项目里=下一部片复制一份, 改一处忘另一处, 正是本轮刚在 LEAD/GAP 上修过的同一类病。

    本场第一段起于 scene_start + LEAD，段间 GAP  →  音频结束于 LEAD + Σdur + GAP·(n-1)
    画面再留 HOLD，否则末段尾部被切、五拍第 5 拍"停住"没地方停

LEAD/GAP 不在本文件里定义，从 `narration_layout` 取(混音器同源)。
用法:
    from scene_timing import Timing
    T = Timing(Path(__file__).resolve().parent)     # 项目目录
    T.frames[1]        # S01 帧预算
    T.at(4, "总参数 1.02 万亿", 6)   # chunk_04 该短语在本场内的触发帧
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_scenes_template import load_phrase_timing  # noqa: E402
from narration_layout import GAP, LEAD  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

FPS = 30
HOLD = 0.9      # 末段说完后留给"停住，但纸还在动"的时间


class Timing:
    def __init__(self, project_dir: Path, hold: float = HOLD):
        self.root = Path(project_dir).resolve()
        chunks = json.loads((self.root / "chunks.json").read_text(encoding="utf-8-sig"))
        t = load_phrase_timing(self.root)
        if not t:
            raise SystemExit(f"[FAIL] {self.root} 缺 qa/phrase_timing.json —— 先跑 pipeline tts")
        self.dur = {}
        for c in chunks:
            cid = c["id"]
            self.dur[int(cid.split("_")[1])] = float(t[cid]["dur"])
        self.scene_of = {int(c["id"].split("_")[1]): str(c["scene"]) for c in chunks}
        self.text = {c["id"]: c["text"] for c in chunks}
        self.emotion = {c["id"]: c["emotion"] for c in chunks}
        self.phrases = {int(k.split("_")[1]): v["phrases"] for k, v in t.items()}
        groups: dict[int, list[int]] = {}
        for c in chunks:
            n = int(c["id"].split("_")[1])
            groups.setdefault(int(str(c["scene"]).lstrip("Ss")), []).append(n)
        self.chunks_of = {s: sorted(v) for s, v in sorted(groups.items())}
        self.frames = {s: round((LEAD + sum(self.dur[n] for n in sc)
                                 + GAP * (len(sc) - 1) + hold) * FPS)
                       for s, sc in self.chunks_of.items()}
        self.hold = hold

    def scene_of_chunk(self, n: int) -> int:
        return int(self.scene_of[n].lstrip("Ss"))

    def lead(self, n: int) -> float:
        """该段在本场内的起点(秒)——与 produce._narration_plan 同一条算式。"""
        s = self.scene_of_chunk(n)
        return LEAD + sum(self.dur[k] + GAP for k in self.chunks_of[s] if k < n)

    def at(self, n: int, phrase: str, off: int = 0) -> int:
        """段落 n 的锚点短语 → 本场触发帧。锚点没命中就报错，**不允许静默退回 0**
        (pf() 找不到时返回 0, 写错一个字整场就堆在第 0 帧, 而 semantic_check 只看"有没有 frame")。"""
        hits = [p for p in self.phrases[n] if phrase in p["phrase"] or p["phrase"] in phrase]
        if not hits:
            raise SystemExit(f"[FAIL] chunk_{n:02d} 锚点「{phrase}」在 phrase_timing 里找不到，"
                             f"可选：{[p['phrase'] for p in self.phrases[n]]}")
        s = self.scene_of_chunk(n)
        f = round((self.lead(n) + hits[0]["start"]) * FPS) + off
        if not 0 <= f <= self.frames[s] - 6:
            raise SystemExit(f"[FAIL] chunk_{n:02d}「{phrase}」算出 S{s:02d} f{f} 不在本场 0~{self.frames[s]-6}f 内")
        return f

    def report(self) -> str:
        lines = []
        for s, sc in self.chunks_of.items():
            audio_end = LEAD + sum(self.dur[n] for n in sc) + GAP * (len(sc) - 1)
            lines.append(f"S{s:02d} chunks={['+'.join(str(n) for n in sc)]} "
                         f"音频到 {audio_end:5.2f}s 画面 {self.frames[s]}f={self.frames[s]/FPS:5.2f}s "
                         f"余 {self.frames[s]/FPS - audio_end:.2f}s")
        tot = sum(self.frames.values())
        lines.append(f"总帧 {tot} = {tot/FPS:.2f}s   (旁白实测 {sum(self.dur.values()):.2f}s)")
        return "\n".join(lines)
