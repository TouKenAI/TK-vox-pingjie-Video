#!/usr/bin/env python3
"""V8.2 视觉风格识别器 —— 按选题类型/内容自动匹配三风格(cutout/chalk/popup)。

用法:
  py -3.14 scripts/detect_style.py <项目目录>            # 读 chunks.json(text 字段)
  py -3.14 scripts/detect_style.py <项目目录> --style popup  # 显式指定(跳过识别,写入 qa)
  py -3.14 scripts/detect_style.py <项目目录> --force    # 强制重跑(忽略锁定)
输出: qa/style-detect.json {style, confidence, scores, evidence, source}
规则(与 references/style-director.md §2 一一对应):
  - chunks.json 首元素 `"style"` 字段 = 显式锁定(最高优先级)
  - qa/style-detect.json 已存在且 mtime 晚于 chunks.json → 复用缓存
  - 置信度 <0.6 → WARN 提示人工 --style 指定(禁止硬猜硬配)
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

STYLE_RULES: dict[str, dict] = {
    "chalk": {  # 技术原理科普: 机制解释/为什么/原理心智
        "keywords": ["原理", "为什么", "本质", "机制", "怎么工作", "如何", "接龙", "比喻",
                     "理解", "算法", "训练", "推理", "token", "参数", "概率", "模型", "大模型"],
        "weight": 1.0,
    },
    "popup": {  # 供应链/制造/拆解: 层级展开/工艺流程
        "keywords": ["沙子", "芯片", "晶圆", "光刻", "封装", "供应链", "制造", "工厂",
                     "从", "到", "一层", "拆开", "打开", "流程", "工序", "诞生", "台积电", "代工",
                     "原材料", "提纯", "生产", "组装"],
        "weight": 1.1,
    },
    "cutout": {  # 政策/宏观/战局/事件快评: 默认线
        "keywords": ["政策", "万亿", "数据局", "国家队", "战略", "格局", "战局", "巨头",
                     "对标", "围剿", "反超", "突发", "热搜", "趋势", "统计", "排行", "涨幅",
                     "行业", "市场", "监管", "文件", "通知"],
        "weight": 0.9,
    },
}


def score_text(text: str) -> dict:
    scores = {}
    evidence = {}
    for style, rule in STYLE_RULES.items():
        hits = [k for k in rule["keywords"] if k.lower() in text.lower()]
        scores[style] = round(len(hits) * rule["weight"], 2)
        evidence[style] = hits
    return scores, evidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path, nargs="?", default=None)
    ap.add_argument("--text", type=str, default=None)
    ap.add_argument("--style", type=str, default=None,
                    choices=["cutout", "chalk", "popup"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    if a.project is None and not a.text:
        sys.exit("用法: detect_style.py <项目目录> 或 --text <文案> 或 --style <人工指定>")

    # 数据来源: 项目 chunks.json / --text
    locked = None
    text = None
    src = "text"
    if a.project:
        proj = a.project.resolve()
        chunks_p = proj / "chunks.json"
        if not chunks_p.exists():
            sys.exit(f"FAIL: {chunks_p} 不存在")
        chunks = json.loads(chunks_p.read_text(encoding="utf-8"))
        if not chunks:
            sys.exit("FAIL: chunks.json 为空——先填文案")
        if isinstance(chunks[0], dict) and chunks[0].get("style"):
            locked = chunks[0]["style"]
        text = " ".join(c.get("text", "") for c in chunks if isinstance(c, dict))
        src = "chunks"
    else:
        text = a.text

    out_p = (proj / "qa" / "style-detect.json") if a.project else None
    if out_p and out_p.exists() and not a.force and not a.style and not locked:
        m = out_p.stat().st_mtime
        if m > chunks_p.stat().st_mtime:
            cached = json.loads(out_p.read_text(encoding="utf-8"))
            print(f"[缓存] style={cached['style']} conf={cached['confidence']} (晚于 chunks.json)")
            return 0

    if a.style:
        result = {"style": a.style, "confidence": 1.0, "scores": {}, "evidence": {},
                  "source": "manual"}
        print(f"人工指定: style={a.style}")
    elif locked:
        result = {"style": locked, "confidence": 1.0, "scores": {}, "evidence": {},
                  "source": "locked"}
        print(f"锁定: style={locked} (chunks[0].style)")
    else:
        scores, evidence = score_text(text)
        best = max(scores, key=scores.get)
        second = sorted(scores, key=scores.get, reverse=True)[1]
        margin = scores[best] - scores[second]
        conf = round(min(0.95, 0.3 + scores[best] / 6 + margin / 4), 2)
        if conf < 0.6:
            print(f"[WARN] 置信度 {conf}<0.6, 请人工 --style 指定(规则见 style-director.md §2)")
        result = {"style": best, "confidence": conf, "scores": scores,
                  "evidence": evidence, "source": "heuristic"}
        print(f"识别: style={best} conf={conf} scores={scores}")
        print(f"  依据: chalk={evidence['chalk'][:5]} popup={evidence['popup'][:5]} cutout={evidence['cutout'][:5]}")

    if out_p:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入 {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
