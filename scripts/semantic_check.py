#!/usr/bin/env python3
"""V8.1.2 画义对齐校验器 —— 校验 sut.json（语义单元表）是否达标。

sut.json 格式（阶段②TTS 后、生图前产出，进 BRIEF）:
[
  {
    "chunk": "chunk_04",
    "sentence": "管人得先当上领导，用钱生钱得先证明你会赚钱",
    "type": "method",            // hook|book|method|case|quote|cta
    "has_number": false,          // 句中含关键数字则 true(V8.1 自动识别,无需手填)
    "units": [
      {"text": "管人→得先当上领导", "grade": "A",
       "visual": "人群抬石被门槛墙挡住,墙上领导帽剪影", "scene": "S04", "frame": 96},
      {"text": "钱生钱→先证明会赚钱", "grade": "A",
       "visual": "金币堆前横一道纸门槛墙", "scene": "S04", "frame": 288}
    ]
  }
]

校验规则（V6.2 硬门槛）:
G1 method/case 句 每个 ≥1 个 A 级单元
G2 全片 A 级单元占比 ≥60%
G3 纯 C 级句子占比 ≤15%
G4 数字句(has_number)必须 ≥1 个 A 级
G5 每个 A 级单元必须带 scene+frame（可追溯到关键帧）
G6(V8.1.2) IP 角色单元(units[].ip=true)必须能在 scene JSON 中找到覆盖该帧的
   ip_host* 出场层(opacity≥0.5)——消灭"角色演错语义但五门禁全绿"真空带;
   场景 JSON 尚未生成时(阶段③)自动跳过,向后兼容旧稿

V8.1.1 升级(修 V8.1 中文数字虚指误报——实测"进一步/一开始/十分关键/万能钥匙"全被误判数字句):
  ① 中文数字必须带量词/单位语境才计数(三条/五年/万人/十分钟/百分之四十/翻了三倍/第4次),
    "进一步/十分/统一/万能"等虚指不再命中;GPT-6 类型号不计数字句(排除前置字母)。
  ② has_number 显式填写时以人工为准(true/false 都尊重);仅字段缺失时才自动识别——
    自动识别仍纳入 G4(≥1 A 级可视化),人工确认非数字句可填 false 豁免。
用法: python semantic_check.py <项目目录>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

A_MIN_RATIO = 0.60
C_MAX_SENT_RATIO = 0.15

# V8.1.1 数字句自动识别正则(8 类;中文数字必须带量词/单位语境,虚指不误报)
NUM_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9-])\d+\.?\d*[%‰亿万千百]?"),   # ① 阿拉伯数字(排除 GPT-6/A4 类型号: 前邻字母/数字/连字符)
    re.compile(r"百分之[一二两三四五六七八九十百千万亿]+"),      # ② 中文百分比(百分之四十)
    re.compile(r"[一二两三四五六七八九十]+分之[一二两三四五六七八九十]+"),  # ③ 中文分数(十分之一)
    re.compile(r"(?<!第)[一二两三四五六七八九十百千万亿]+[个次回趟条位名件页章行字倍成折轮场杯栋层辆台款项人年月日天周%‰]"),  # ④ 中文数+量词/单位(三条/五年/万人; "第X层"结构序数不计)
    re.compile(r"[一二两三四五六七八九十百千万亿]+(?:分钟|小时|秒钟)"),  # ⑤ 中文时长(十分钟; "十分"副词不命中)
    re.compile(r"第[一二三四五六七八九十百千\d]+[次遍回趟个]"),  # ⑥ 序数(第4次)
    re.compile(r"[翻涨跌增降]了?(?:\d+\.?\d*|[一二两三四五六七八九十百千万亿]+)倍"),  # ⑦ 倍数(翻了三倍)
    re.compile(r"\d+\s*[年月日天小时分秒]"),                  # ⑧ 阿拉伯时段(2024年)
]


# V8.1.1: 成语/口语虚指数词白名单(这些含数字汉字但不是"数字句", 不触发 G4)
IDIOM_VAGUE = ["万一", "三心二意", "十全十美", "九牛一毛", "四面八方", "五花八门",
               "七上八下", "一心一意", "三番五次", "九死一生", "十拿九稳", "一目十行",
               "五颜六色", "七嘴八舌", "千辛万苦", "百折不挠", "一日千里", "十万火急"]


def is_number_sentence(sentence: str) -> bool:
    """V8.1.1:先挖掉成语/虚指词再匹配 8 类正则。
    修白名单短路洞:旧逻辑"句中含任一成语即 return False"会把"千辛万苦中增长了40%"
    这类成语+真数字同句一起豁免 G4;挖除后匹配则两全——成语不再误报,真数字不再漏报。
    """
    s = sentence
    for w in IDIOM_VAGUE:
        if w in s:
            s = s.replace(w, "、")  # 用标点占位,防止挖词后左右字符拼出新数字串
    return any(pat.search(s) for pat in NUM_PATTERNS)


def _scene_has_ip_at(root: Path, scene: str, frame: int):
    """G6 辅助:scene JSON 中是否存在 ip_host* 层在指定帧 opacity≥0.5。
    返回 True/False;场景文件不存在返回 None(调用方决定跳过)。"""
    p = root / f"scene_{scene.lower()}.json"
    if not p.exists():
        return None
    try:
        sc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    for l in sc.get("layers", []):
        if not str(l.get("id", "")).startswith("ip_host"):
            continue
        ks = sorted(l.get("keyframes", []), key=lambda k: k["frame"])
        if not ks:
            continue
        if frame <= ks[0]["frame"]:
            op = ks[0].get("opacity", 0)
        elif frame >= ks[-1]["frame"]:
            op = ks[-1].get("opacity", 0)
        else:
            for a, b in zip(ks, ks[1:]):
                if a["frame"] <= frame <= b["frame"]:
                    t = (frame - a["frame"]) / max(1, b["frame"] - a["frame"])
                    op = a.get("opacity", 0) + (b.get("opacity", 0) - a.get("opacity", 0)) * t
                    break
        if op >= 0.5:
            return True
    return False


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sut_path = root / "sut.json"
    if not sut_path.exists():
        sys.exit("FAIL: sut.json 不存在——阶段②后必须先写语义单元表再生图(V6.2)")
    rows = json.loads(sut_path.read_text(encoding="utf-8"))
    errors, warns = [], []

    total_units = a_units = 0
    c_sentences = total_sentences = 0
    auto_num_hits = 0  # V8.1 统计:自动识别的数字句数(原 has_number 漏标)
    for row in rows:
        units = row.get("units", [])
        sentence = row.get("sentence", "?")
        tag = f"[{row.get('chunk','?')}|{row.get('type','?')}] {sentence[:18]}…"
        total_sentences += 1
        if not units:
            errors.append(f"{tag} 无语义单元")
            continue
        grades = [u.get("grade", "?") for u in units]
        for u in units:
            total_units += 1
            if u.get("grade") == "A":
                a_units += 1
                if not (u.get("scene") and u.get("frame") is not None):
                    errors.append(f"{tag} A级单元缺 scene/frame 追溯: {u.get('text','?')}")
        if all(g == "C" for g in grades):
            c_sentences += 1
        if row.get("type") in ("method", "case") and "A" not in grades:
            errors.append(f"{tag} method/case 句无 A 级表达")
        # V8.1.1 G4: has_number 显式填写以人工为准; 仅字段缺失时自动识别(虚指不再误报)
        manual_num = row.get("has_number")
        if manual_num is None:
            has_num = is_number_sentence(sentence)
            if has_num:
                auto_num_hits += 1
                warns.append(f"{tag} has_number 字段缺失,V8.1.1 自动识别为数字句(已纳入 G4;人工确认非数字句可填 false 豁免)")
        else:
            has_num = bool(manual_num)
        if has_num and "A" not in grades:
            errors.append(f"{tag} 数字句无 A 级可视化")
        # G6(V8.1.2): IP 角色单元 ↔ 场景 ip_host 层交叉验证
        for u in units:
            if not u.get("ip"):
                continue
            if not (u.get("scene") and u.get("frame") is not None):
                errors.append(f"{tag} IP 单元缺 scene/frame 追溯: {u.get('text','?')}")
                continue
            ok = _scene_has_ip_at(root, str(u["scene"]), int(u["frame"]))
            if ok is False:
                errors.append(f"{tag} IP 单元「{u.get('text','?')}」在 {u['scene']} f{u['frame']} 无出场层"
                              f"(场景中无 ip_host* 层覆盖该帧或该帧透明)——角色演错语义")
            elif ok is None:
                warns.append(f"{tag} {u['scene']} JSON 不存在,G6 暂缓(阶段③属正常)")
        if "B" in grades and "A" not in grades and row.get("type") == "hook":
            warns.append(f"{tag} hook 句仅 B 级,建议至少一个动词性画面")

    a_ratio = a_units / total_units if total_units else 0
    c_ratio = c_sentences / total_sentences if total_sentences else 0
    if a_ratio < A_MIN_RATIO:
        errors.append(f"A 级单元占比 {a_ratio:.0%} < {A_MIN_RATIO:.0%}——把 B 级升级为动词性动画")
    if c_ratio > C_MAX_SENT_RATIO:
        errors.append(f"纯 C 级句占比 {c_ratio:.0%} > {C_MAX_SENT_RATIO:.0%}")

    print(f"句子 {total_sentences} | 语义单元 {total_units} | A 级 {a_units}({a_ratio:.0%}) | 纯C句 {c_sentences}({c_ratio:.0%}) | V8.1.1 自动识别数字句 {auto_num_hits}")
    for w in warns:
        print("WARN:", w)
    if errors:
        print("=== FAIL ===")
        for e in errors:
            print(" ", e)
        sys.exit(1)
    print("PASS: 画义对齐达标")


if __name__ == "__main__":
    main()
