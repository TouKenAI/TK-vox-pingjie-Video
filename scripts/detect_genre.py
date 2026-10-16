#!/usr/bin/env python3
"""V8.1 文案类型识别器 —— 识别文案 genre 并输出置信度与依据。

用法:
  py -3.14 scripts/detect_genre.py <项目目录>            # 读 chunks.json(text 字段)
  py -3.14 scripts/detect_genre.py --text "文案原文"      # 直接识别原文
  py -3.14 scripts/detect_genre.py <项目目录> --genre ad  # 显式指定(跳过识别,写入 qa)
  py -3.14 scripts/detect_genre.py <项目目录> --force    # 强制重跑(忽略锁定)
输出: qa/genre-detect.json {genre, confidence, scores, evidence, source}
规则: 置信度 <0.6 → WARN 提示人工 --genre 指定(禁止硬猜硬配, genre-profiles.md §0)。

V8.1 升级:
  1) chunks.json 首元素 `"genre": "knowledge"` 字段 = 显式锁定(最高优先级,跳过启发式)
  2) qa/genre-detect.json 已存在且 mtime 晚于 chunks.json → 复用缓存(避免每次 IO+打分)
  3) 加 `--force` 强制重跑启发式(用于调试/改文案后)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

# 类型识别规则(与 references/genre-profiles.md §1-5 识别特征一一对应)
GENRE_RULES: dict[str, dict] = {
    "knowledge": {
        "keywords": ["书", "作者", "方法", "概念", "研究", "政策", "文件", "通知", "原理", "定律",
                     "效应", "宝典", "解读", "为什么", "本质", "底层逻辑"],
        "weight": 1.0,
    },
    "ad": {
        "keywords": ["限时", "优惠", "折扣", "立即", "点击", "下单", "免费", "名额", "倒计时",
                     "抢购", "秒杀", "到手价", "立减", "赠品", "包邮", "抓紧"],
        "weight": 1.2,  # 促销词信号强,加权
    },
    "brand": {
        "keywords": ["我们", "品牌", "相信", "愿景", "使命", "初心", "一路", "同行", "见证",
                     "坚持", "热爱", "理想", "未来", "价值观"],
        "weight": 1.0,
    },
    "story": {
        "keywords": ["那年", "后来", "直到", "他", "她", "那天", "曾经", "记得", "故事",
                     "父亲", "母亲", "朋友", "同事", "老板", "哭着", "笑着"],
        "weight": 0.9,
    },
    "product": {
        "keywords": ["这款", "功能", "参数", "搭载", "支持", "一键", "秒", "新品", "发布",
                     "续航", "像素", "内存", "芯片", "智能", "APP", "系统"],
        "weight": 1.0,
    },
}
MIN_CONFIDENCE = 0.6


def score_text(text: str) -> dict[str, dict]:
    scores: dict[str, dict] = {}
    for genre, rule in GENRE_RULES.items():
        hits = [kw for kw in rule["keywords"] if kw in text]
        raw = len(hits) * rule["weight"]
        scores[genre] = {"hits": hits, "raw": round(raw, 2)}
    return scores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", nargs="?", type=Path, default=None)
    ap.add_argument("--text", type=str, default=None)
    ap.add_argument("--genre", type=str, default=None,
                    choices=[*GENRE_RULES], help="显式指定类型(跳过启发式)")
    ap.add_argument("--force", action="store_true",
                    help="强制重跑启发式(V8.1 新增;默认复用 qa/genre-detect.json 缓存)")
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args()

    out = a.json_out
    if out is None and a.project:
        out = a.project / "qa" / "genre-detect.json"

    # V8.1.1: chunks[0].genre 显式锁定优先于缓存(复用前先判,防旧缓存覆盖锁定)
    locked_genre = None
    if a.project and (a.project / "chunks.json").exists():
        try:
            ck = json.loads((a.project / "chunks.json").read_text(encoding="utf-8"))
            if ck and ck[0].get("genre") in GENRE_RULES:
                locked_genre = ck[0]["genre"]
        except Exception:
            locked_genre = None

    # 缓存复用(无锁定 + out 存在且晚于 chunks.json + 非 --force → 复用)
    if not a.force and locked_genre is None and out and out.exists() and a.project:
        ck_mtime = (a.project / "chunks.json").stat().st_mtime if (a.project / "chunks.json").exists() else 0
        if out.stat().st_mtime >= ck_mtime:
            cached = json.loads(out.read_text(encoding="utf-8"))
            print(f"genre={cached['genre']} confidence={cached['confidence']} source={cached.get('source','cache')} (缓存)")
            for e in cached.get("evidence", []):
                print(" ", e)
            return 0 if cached.get("source") != "heuristic" or cached.get("confidence", 0) >= MIN_CONFIDENCE else 2

    source = "explicit"
    if a.genre:
        genre, confidence, scores, evidence = a.genre, 1.0, {}, ["人工 --genre 显式指定"]
    else:
        chunks = None
        if a.project and (a.project / "chunks.json").exists():
            try:
                chunks = json.loads((a.project / "chunks.json").read_text(encoding="utf-8"))
            except Exception:
                chunks = None
        # V8.1.1(P0-2 修正版): chunks[0].genre 显式锁定最高优先(锁定+启发式/缓存互斥)
        if chunks and chunks[0].get("genre") in GENRE_RULES:
            genre = chunks[0]["genre"]
            confidence = 1.0
            scores = {}
            evidence = [f"chunks.json[0].genre='{genre}' 显式锁定"]
            source = "chunks-locked"
        else:
            # 启发式: --text 原文 或 项目 chunks 拼文, 两条路共用同一打分(V8.1.1 修 --text 分支未打分即引用 genre 的崩溃)
            if a.text:
                text = a.text
            elif chunks:
                text = "".join(c.get("text", "") for c in chunks)
            else:
                sys.exit("FAIL: 无输入(--text 或项目目录 chunks.json)")
            scores = score_text(text)
            ranked = sorted(scores.items(), key=lambda kv: -kv[1]["raw"])
            top, second = ranked[0], ranked[1]
            total = sum(v["raw"] for _, v in ranked) or 1
            genre = top[0]
            confidence = round(top[1]["raw"] / total, 2) if top[1]["raw"] > 0 else 0.0
            margin = top[1]["raw"] - second[1]["raw"]
            evidence = [f"命中[{genre}]: {'/'.join(top[1]['hits'][:8])}",
                        f"次选[{second[0]}](差 {margin:.1f})"]
            source = "heuristic"

    result = {"genre": genre, "confidence": confidence, "source": source,
              "evidence": evidence, "scores": {k: v["raw"] for k, v in scores.items()} if scores else {}}
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"genre={genre} confidence={confidence} source={source}")
    for e in evidence:
        print(" ", e)
    if source == "heuristic" and confidence < MIN_CONFIDENCE:
        print(f"WARN: 置信度 {confidence} < {MIN_CONFIDENCE}——类型特征不明显,建议人工 --genre 显式指定,禁止硬猜硬配")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
