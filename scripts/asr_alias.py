#!/usr/bin/env python3
"""ASR 质检的"念对但转写不同"别名归一 —— 与 num_equiv 的数字归一同一套设计。

背景(playbook §54⑤ 实录): StepFun ASR 会把英文专名转写成同音/近形拼写
  Claude→Cloud、Apache→阿帕奇、Xing→Sing。旁白发音是对的, 逐段相似度却掉到阈值以下 →
  假 FAIL。旧处置是"把旁白改成能转写对的写法", 那是**为了讨好检查器而牺牲口播质量**。

三条设计约束(与数字归一一致, 防门禁被自己人废掉):
  1) 只归一**项目内显式声明**过的变体(qa/asr_alias.json), 不猜;
  2) 声明的变体必须是拉丁/数字 token —— 禁止声明中文实词(否则有人能声明"贵→便宜"把门禁清空);
     中文纯同音代词(它/她→他)走内置固定表, 不接受项目扩展;
  3) 放行必须打印命中的具体规则, 不允许静默通过。

用法:
  from asr_alias import load_alias, canon, fired_rules
  amap = load_alias(proj)
  if lcs_ratio(ref, got) < thresh:
      r2 = lcs_ratio(canon(ref, amap), canon(got, amap))   # r2 达标 → 判"转写别名"放行
      tag = fired_rules(ref, got, amap)                     # 打印用
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

# 中文第三人称同音: ASR 按语境随机选字, 对"发音是否念对"这件事三者等价。固定表, 不可被项目扩展。
BUILTIN_HOMOPHONE = {"它": "他", "她": "他"}
_LATIN_ONLY = re.compile(r"^[a-z0-9]+$")


def _norm_key(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE).lower()


def load_alias(proj: Path) -> dict[str, str]:
    """读 <项目>/qa/asr_alias.json → {变体: 规范名}(均为归一后形态)。

    文件格式: {"Claude": ["Cloud", "克劳德"], "DeepSeek": ["deep seek"]}  # 规范名: [ASR 可能写法]
    中文值一律丢弃(不可声明), 只保留拉丁 token; 文件不存在则只有内置同音表。
    """
    mapping = dict(BUILTIN_HOMOPHONE)
    f = Path(proj) / "qa" / "asr_alias.json"
    if not f.exists():
        return mapping
    raw = json.loads(f.read_text(encoding="utf-8"))
    dropped: list[str] = []
    for canon_name, variants in raw.items():
        ck = _norm_key(canon_name)
        # 约束 2(判据在 V3.22 从"变体"挪到"规范名"): **规范名必须是拉丁/数字 token**。
        # 原意是防"贵→便宜"这类把中文实词互相映射、从而清空门禁的声明; 卡规范名同样挡得住,
        # 却不再误伤 StepFun 最常见的假 FAIL —— Alpha→阿尔法、Apache→阿帕奇(英文词被转写成中文)。
        # 中文规范名(如 魔搭→某达)仍拒绝: 那种与"真错读"在文本上不可区分, 该走重录而不是声明。
        if not _LATIN_ONLY.match(ck):
            dropped.append(f"{canon_name}(规范名非拉丁, 中文专名请重录或改由字卡承载)")
            continue
        for v in (variants if isinstance(variants, list) else [variants]):
            vk = _norm_key(str(v))
            if not vk or vk == ck:
                continue
            mapping[vk] = ck
    if dropped:
        print(f"  [别名表] 忽略 {len(dropped)} 条声明(规范名必须是拉丁/数字 token, 防把中文实词互相映射掏空门禁): "
              + "; ".join(dropped[:6]))
    return mapping


def canon(text: str, mapping: dict[str, str]) -> str:
    """把文本里出现的已声明变体替换成规范形态。按变体长度降序替换, 防短串先吃长串。"""
    out = text
    for variant in sorted(mapping, key=len, reverse=True):
        if variant:
            out = out.replace(variant, mapping[variant])
    return out


def fired_rules(ref: str, got: str, mapping: dict[str, str]) -> list[str]:
    """返回本段实际命中的别名(给打印用)。要求**成对**出现: 一侧写变体、另一侧写规范名。
    只按"变体是否只出现在一侧"会误报——例如映射 {她:他} 与 它→他 共享规范名"他",
    原文用"它"、ASR 写"他"时不能把"她↔他"也报出来。"""
    hits = []
    for variant, canonical in mapping.items():
        if variant == canonical:
            continue
        if (variant in ref and canonical in got) or (variant in got and canonical in ref):
            hits.append(f"{variant}↔{canonical}")
    return sorted(hits)
