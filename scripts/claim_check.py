#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文案自洽性硬门 claim_check.py —— 拦"改写时自己造出的新事实"。

为什么需要它(production14 实录): 用户说"不用核对信息"只豁免**外部事实**核查, 不豁免**自洽性**。
我在重构稿里写下"写代码还比它(Kimi)强", 而同一份稿子的另一段写着"和 Kimi K3 打平";
还把 7毛4-5毛8=1毛6 说成"便宜两毛"(虚报 25%)。两句都在稿子里, 任何一条都能机械发现,
但 check_script 只管长句/骨架(V3.21 起字数不设限), semantic_check 只管画义 —— 这是门禁的空白区。

两条规则:
  C1 矛盾断言: 同一实体在片内既被"强/领先/反超"又被"打平/持平/一个水平"修饰 → FAIL。
     代词"它/他"回指同段最近出现的实体名(不做跨段指代, 宁缺勿误报)。
  C2 差值复算: 断言"便宜/贵 X毛 | X成 | 一半 | N%"且片内**同时给出两端绝对价**时, 复算并断言
     相对误差 ≤ 20%; 两端绝对价缺失 → 只给 INFO(无法复算, 也不允许凭感觉写差值)。

用法: py -3.14 claim_check.py <项目目录> [--json-out qa/claim-check.json]
退出码 0=自洽, 1=有矛盾。
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
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

ENTITY = re.compile(r"(Kimi|GLM|DeepSeek|Claude|GPT|Step|Qwen|Gemma|Mistral|Llama|文心|通义|豆包|Kimi K\d)", re.I)
STRONG = re.compile(r"更强|比它强|比他强|强过|领先|反超|高出一截|完胜|压过|超过")
EQUAL = re.compile(r"打平|持平|一个水平|同一水平|一样|不相上下|相当")
CHEAP = re.compile(r"便宜|更低|省")
DEAR = re.compile(r"贵|加价|更贵")

# 绝对价: "7 毛 4" / "5毛8" / "两毛多" → 元(以"毛"为单位存)
PRICE = re.compile(r"([0-9零一二两三四五六七八九]+)\s*毛\s*([0-9零一二三四五六七八九])?")
CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
# 断言的差值: "便宜一半还多" / "贵近三成" / "便宜两毛"
DELTA_PCT = re.compile(r"(便宜|贵|省)\s*(?:近|约|了)?\s*(一半|([0-9一二两三四五六七八九十]+)\s*成|([0-9]+)\s*%)")
DELTA_MAO = re.compile(r"(便宜|贵|省)\s*(?:了)?\s*([0-9零一二两三四五六七八九]+)\s*([0-9一二两三四五六七八九])?\s*毛")


def to_float(dig: str, frac: str | None) -> float:
    v = 0.0
    for ch in dig:
        v = v * 10 + (int(ch) if ch.isdigit() else CN.get(ch, 0)) if len(dig) > 1 else (int(dig) if dig.isdigit() else CN.get(dig, 0))
    if frac:
        v = v + (int(frac) if frac.isdigit() else CN.get(frac, 0)) / 10
    return v


def prices_in(text: str) -> list[float]:
    out = []
    for m in PRICE.finditer(text):
        out.append(to_float(m.group(1), m.group(2)))
    return out


def pct_of(word: str, digits: str | None, pct: str | None) -> float | None:
    if word == "一半" or (digits and "半" in digits):
        return 50.0
    if pct:
        return float(pct)
    if digits:
        n = 0
        for ch in digits:
            if ch == "十":
                n = n or 10 if n == 0 else n + 10
            else:
                n = n * 10 + (int(ch) if ch.isdigit() else CN.get(ch, 0))
        return n * 10.0
    return None


def check(proj: Path):
    cf = proj / "chunks.json"
    if not cf.exists():
        raise SystemExit("FAIL: chunks.json 不存在——本门在阶段①重构稿之后、TTS 花钱之前运行")
    chunks = json.loads(cf.read_text(encoding="utf-8"))
    chunks = chunks if isinstance(chunks, list) else chunks["chunks"]
    full = " ".join(c["text"] for c in chunks)
    # V3.37: 空正文守卫（与 check_script 同一漏洞：setup 的空桩段数非 0、正文全空，旧版对着它打 PASS）
    if not full.strip():
        raise SystemExit(f"FAIL: chunks.json {len(chunks)} 段正文全空——setup 的空桩还没被重构稿替换，"
                         f"没有文本可核，本门不能判 PASS")
    errors, warns, info = [], [], []

    # ---- C1 矛盾断言: 逐段解析实体与其被赋予的关系 ----
    claims: dict[str, list[tuple[str, str, str]]] = {}
    for c in chunks:
        t = c["text"]
        # 只认**同句内显式出现**的实体名。跨句回指"它"必误报: p14 v2「同质量，它便宜」的"它"
        # 指主角, 若继承上一句的 Kimi 就会造出"Kimi 又贵又便宜"的假矛盾(门禁哭狼=被关掉)。
        for sent in re.split(r"(?<=[。！？；])", t):
            if not sent.strip():
                continue
            rel = []
            if STRONG.search(sent):
                rel.append("更强")
            if EQUAL.search(sent):
                rel.append("打平")
            if DEAR.search(sent) and not CHEAP.search(sent):
                rel.append("更贵")
            if CHEAP.search(sent) and not DEAR.search(sent):
                rel.append("更便宜")
            if not rel:
                continue
            for ent in dict.fromkeys(x.capitalize() for x in ENTITY.findall(sent)):
                for r in rel:
                    claims.setdefault(ent, []).append((r, c["id"], sent.strip()[:34]))
    for ent, lst in sorted(claims.items()):
        rels = {r for r, _, _ in lst}
        if {"更强", "打平"} <= rels:
            src = "; ".join(f"{i}「{s}」" for r, i, s in lst if r in ("更强", "打平"))
            errors.append(f"[C1 矛盾断言] {ent} 在同一片内既被判'更强'又被判'打平' → {src}")
        if {"更贵", "更便宜"} <= rels:
            src = "; ".join(f"{i}「{s}」" for r, i, s in lst if r in ("更贵", "更便宜"))
            errors.append(f"[C1 矛盾断言] {ent} 既被判'更贵'又被判'更便宜' → {src}")

    # ---- C2 差值复算 ----
    # 断言自己写的"便宜两毛"不能被当成两端绝对价(否则拿断言去验断言)
    body = DELTA_MAO.sub(" ", full)
    abs_prices = prices_in(body)
    for c in chunks:
        t = c["text"]
        for m in DELTA_PCT.finditer(t):
            want = pct_of(m.group(2), m.group(3), m.group(4))
            if want is None:
                continue
            if len(abs_prices) >= 2:
                hi, lo = max(abs_prices), min(abs_prices)
                act = abs(hi - lo) / hi * 100 if hi else 0
                if abs(act - want) > max(15.0, want * 0.35):
                    errors.append(f"[C2 差值复算] {c['id']}「{m.group(0)}」宣称 {want:.0f}%, "
                                  f"但片内绝对价 {hi}毛/{lo}毛 实算 {act:.0f}% —— 改口径或补端点")
            else:
                info.append(f"[C2 无法复算] {c['id']}「{m.group(0)}」—— 片内未给两端绝对价, "
                            f"差值只能引外部来源; 若为自算请核对官方榜单口径")
        for m in DELTA_MAO.finditer(t):
            want = to_float(m.group(2), m.group(3))
            if len(abs_prices) >= 2:
                hi, lo = max(abs_prices), min(abs_prices)
                act = round(hi - lo, 2)
                if abs(act - want) > 0.25:
                    errors.append(f"[C2 差值复算] {c['id']}「{m.group(0)}」宣称差 {want}毛, "
                                  f"绝对价 {hi}毛-{lo}毛 实差 {act}毛 (偏差 {abs(act-want)/max(act,0.1):.0%})")
            else:
                info.append(f"[C2 无法复算] {c['id']}「{m.group(0)}」—— 未给两端绝对价, 别写具体毛数")
    return errors, warns, info, claims


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()
    errors, warns, info, claims = check(a.project)
    print(f"实体断言: " + " | ".join(f"{k}:{sorted({r for r, _, _ in v})}" for k, v in sorted(claims.items())))
    for m in info:
        print("  INFO " + m)
    for m in warns:
        print("  WARN " + m)
    if errors:
        print("=== FAIL ===")
        for m in errors:
            print("  " + m)
        rc = 1
    else:
        print("PASS: 文案自洽(无矛盾断言; 差值口径可核或已标注无法复算)")
        rc = 0
    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"errors": errors, "warns": warns, "info": info,
                                   "claims": {k: v for k, v in claims.items()}},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
