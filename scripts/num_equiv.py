"""V3.16 共用: ASR 数字转写等价判定。
StepFun ASR 常把"七百/四万两千/八百"转写成"700/42000/800",逐字比对会假 FAIL。
asr_final_check(整片复核) 与 asr_spotcheck(TTS 抽检) 共用本模块, 保证两处判定口径一致。
保守原则: 解析不了(如口语"两三百")一律判不等价 → 宁可人工复核, 不放过真错读。"""
from __future__ import annotations

import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉


NUMERIC_RUN = re.compile(r"[0-9零一二两三四五六七八九十百千万亿]+")
_CN_DIG = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}


def cn2num(tok: str) -> int | None:
    """保守中文数字解析: 只认 '八百/800'、'十/10'、'两千/2000' 这类规整写法;
    解析不了(如口语 '两三百')一律返回 None → 按未通过处理,宁可人工复核也不放过真错读。"""
    if tok.isdigit():
        return int(tok)
    # 口语约数("两三百""三四千"= 两三百到三百之间)无法唯一求值 → 判不可解析, 交人工复核
    if re.search(r"[一二两三四五六七八九][一二两三四五六七八九][十百千万亿]", tok):
        return None
    if any(c not in _CN_DIG and c not in _CN_UNIT for c in tok):
        return None
    total, section, num = 0, 0, 0
    seen = False
    for ch in tok:
        if ch in _CN_DIG:
            num = _CN_DIG[ch]
            seen = True
        else:
            unit = _CN_UNIT[ch]
            if unit == 10000 or unit == 100000000:
                section = (section + (num if seen else 0) or 1) * unit if not section else (section + num) * unit
                total += section
                section = 0
            else:
                section += (num if num else 1) * unit
            num, seen = 0, True
    total += section + num
    return total if total > 0 or tok in ("零",) else None


def numeric_format_only(ref: str, got: str) -> bool:
    """严格比对失败时的复核: 仅当双方差异**全部**是"同一个值的两种写法"(八百↔800、十↔10)才判格式差异。
    值不同(八百 vs 九百)、漏句、重复句一律返回 False → 仍然 BLOCK。"""
    a = re.findall(NUMERIC_RUN, ref)
    b = re.findall(NUMERIC_RUN, got)
    if not a or len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        vx, vy = cn2num(x), cn2num(y)
        if vx is None or vy is None or vx != vy:
            return False
    return True


def denorm(s: str) -> str:
    return NUMERIC_RUN.sub("#", s)


def numeric_mismatch(a: str, b: str) -> list[tuple[str, str]]:
    """两侧数字串按出现顺序配对, 返回"都能解析成数值但值不同"的对(如 313↔913)。
    LCS 相似度在长句里拦不住单个数字念错(28 字差 1 字仍有 0.96), 本函数补这条精确断言。
    任一侧不可解析(口语约数)则不计入——避免假阳性。"""
    ta, tb = NUMERIC_RUN.findall(a), NUMERIC_RUN.findall(b)
    if len(ta) != len(tb):
        return []
    out = []
    for x, y in zip(ta, tb):
        if x == y:
            continue
        vx, vy = cn2num(x), cn2num(y)
        if vx is not None and vy is not None and vx != vy:
            out.append((x, y))
    return out
