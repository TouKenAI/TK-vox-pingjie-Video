#!/usr/bin/env python3
"""V8.1 文案重构校验器 —— 机检 R4 句级呼吸 / R2 骨架与 CTA / ad 类型广告法红线。

读取 chunks.json([{id, emotion, text, speed?}], 阶段①重构稿):

  ★ V3.21(用户 2026-09-20 定): **不限字数、不限时长、不设信息点上限, 以用户给的文案为准, 不砍内容。**
    R1(字数区间)与 R3(信息点封顶)因此**默认关闭**; 本工具改为只报"预计旁白/成片时长"供知情, 不判分。
    原因: R1 由"220 字/分"倒推, 而 speed 1.1/1.15 实测 4.90~5.15 字/秒(≈294~309 字/分),
    两条约束在数学上不可能同时满足(p13 为凑时长放宽门禁 → 审美 83.3→78.3)。
    需要临时套预算时显式传 --max-chars / --max-chars-hard / --min-chars / --info-pts(默认全 None=不设限)。

  保留的硬门(与片长无关, 是"读不读得懂"):
    R4 句级呼吸: 单句(去标点) > 45 字 → ERROR; > 40 字 → WARN(口播单元 20~40 字)
    R3 单段提示: 任一 chunk 去标点 > 60 字 → WARN(一段塞多个信息点, 建议拆成两口气)
    R2 骨架(轻量): 首 chunk 非 hook / 末 chunk 非 cta / 末段缺该类型 CTA 措辞 → WARN
    广告法红线: 仅 --genre ad, 命中 → ERROR

用法: py -3.14 scripts/check_script.py <项目目录> [--max-chars N] [--max-chars-hard N] [--min-chars N]
      [--max-sent N] [--info-pts N] [--json-out qa/check-script.json] [--genre knowledge|ad|brand|story|product]
退出码: 0 = PASS(无 ERROR, WARN 允许) / 1 = FAIL(有 ERROR, 阶段①不过不进 TTS)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

MAX_SENT = 45          # R4 硬上限: 单句(去标点)超此不可, 20~40 为宜
SENT_WARN = 40         # R4 WARN 线
CHARS_PER_PT = 28      # 信息点估算口径(仅用于打印, V3.21 起不再据此判分)
CHUNK_WARN = 60        # R3 WARN: 单 chunk 去标点超此 → 一段塞多信息点
# V3.21 报预计时长用: speed 1.1 实测 4.90 字/秒(1.15 档 5.15), 成片 ≈ 旁白 ×1.08(呼吸/转场/尾垫)
RATE_AT_110 = 4.90
PACE_TO_VIDEO = 1.08
PUNCT_SPLIT = re.compile(r"[。！？!?…；;\n]+")
STRIP_PUNCT = re.compile(r"[\s\W_]+")

# V8.2.2 文案类型配置(与 references/genre-profiles.md 一一对应)。
# V3.21: 这里只留"该类型怎么收尾/要不要过广告法机检"; 长度预算字段已全删——
# 留着就是下一任调用方把字数门重新装回来的入口。
GENRE_LIMITS: dict[str, dict] = {
    "knowledge": {"cta_patterns": ["关注", "收藏", "评论"], "cta_required": True, "ad_law": False},
    "ad":        {"cta_patterns": ["抢购", "下单", "点击", "领取", "购买", "立即", "链接"],
                  "cta_required": True, "ad_law": True},
    "brand":     {"cta_patterns": ["一起", "同行", "见证", "关注"], "cta_required": False, "ad_law": False},
    "story":     {"cta_patterns": ["评论", "分享", "关注"], "cta_required": False, "ad_law": False},
    "product":   {"cta_patterns": ["了解", "体验", "预约", "看看", "进店"], "cta_required": True, "ad_law": False},
}
# V8.1.1 广告法红线词(ad 类型硬机检,语义正则避免误报):
#  纯子串会把"100%确定""第一想到""唯一解"等合规表述误判, 改为带语境的模式。
AD_LAW_PATTERNS = [
    re.compile(r"(?:全网|全国|全球|史上|宇宙)(?:最低|最高|第一|唯一)"),          # 前缀+绝对化(史无前例)
    re.compile(r"最(?:低价|低价位|优惠价|便宜)"),                               # 最+价格类(确定性违规)
    re.compile(r"销量(?:第|之)?一"),                                           # 销量第一
    re.compile(r"100%(?:有效|包(?:过|治|好)|保证|成功|退款)"),                 # 100% 承诺(确定性违规)
    re.compile(r"(?:稳赚|包(?:赚|过|治|好)|永不(?:失败|亏损)|根治|特效|万能)"), # 虚假承诺
]
AD_LAW_HINT = "广告绝对化/虚假承诺用语,必须改写(保守名单,宁可漏拦不可误拦)"


def chars_of(s: str) -> int:
    """去中英文标点/空白后的"口播字数"(中文等 unicode 字符保留)。"""
    return len(STRIP_PUNCT.sub("", s))


def check(proj: Path, max_chars: int, max_chars_hard: int, min_chars: int,
          max_sent: int, info_pts: int, genre: str = "knowledge") -> tuple[list[str], list[str], dict]:
    root = proj.resolve()
    cpath = root / "chunks.json"
    if not cpath.exists():
        sys.exit("FAIL: chunks.json 不存在——阶段①重构稿缺失, 禁止进 TTS")
    chunks = json.loads(cpath.read_text(encoding="utf-8"))
    if not isinstance(chunks, list) or not chunks:
        sys.exit("FAIL: chunks.json 为空——请先执行文案重构 R1~R6")
    # V3.37 空正文守卫：`pipeline setup` 会生成 `[{"id":"chunk_01","text":"",...}]` 这样的**空桩**，
    # 段数不为 0 但正文全空。旧版只查"列表空"，于是本门对着 0 字文案打 PASS——
    # 2026-09-27 排练实录：check_script 报「字数 0 | chunk 1 → PASS」、claim_check 报「实体断言:(空) → PASS」。
    # 花钱前的门对着空稿放行 = 没有门。
    if sum(chars_of(c.get("text", "")) for c in chunks) == 0:
        sys.exit(f"FAIL: chunks.json 有 {len(chunks)} 段但**正文全空**——这是 pipeline setup 的空桩，"
                 f"阶段①的分段重构稿还没写进来。禁止带着空稿进 TTS")

    profile = GENRE_LIMITS.get(genre, GENRE_LIMITS["knowledge"])
    errors: list[str] = []
    warns: list[str] = []
    total = sum(chars_of(c.get("text", "")) for c in chunks)
    # V3.21: 不设时长门, 但必须**报**预计时长让人知情("长就长"的前提是知道多长)。
    # 逐段按各自 speed 档折算(1.1 档实测 4.90 字/秒, 1.15 档按比例 5.13)。
    narr_s = sum(chars_of(c.get("text", "")) / (RATE_AT_110 * float(c.get("speed", 1.1)) / 1.1)
                 for c in chunks)

    # R1 字数: V3.21 起**默认不设限**(见文件头)。传了 --max-chars* 才是人主动要的预算。
    # V3.21 用户决定(2026-09-20): 不限字数、不限时长, 以用户给的文案为准, 不砍内容。
    # 保留的是 R4 单句长度与 R3 单段长度——那是"读不读得懂", 与片长无关。
    if max_chars_hard is not None and total > max_chars_hard:
        errors.append(
            f"[R1] 全片 {total} 字 > 自设硬上限 {max_chars_hard}——按预算砍例证,禁止提速")
    elif max_chars is not None and total > max_chars:
        warns.append(
            f"[R1] 全片 {total} 字 > 自设软上限 {max_chars}——重复例证>同义断言>修饰词,禁止提速")
    elif min_chars is not None and total < min_chars:
        warns.append(f"[R1] 全片仅 {total} 字 < 自设下限 {min_chars}——内容偏少, 可补一个例子")

    # R3 信息点预算
    est = math.ceil(total / CHARS_PER_PT)
    if info_pts is not None:
        if est > info_pts:
            warns.append(
                f"[R3] 预期信息点 {est}(≈{CHARS_PER_PT}字/点) > {info_pts}——每点 5~7s 才来得及消化")
        if len(chunks) > info_pts:
            warns.append(f"[R3] chunk 数 {len(chunks)} > {info_pts}——段落偏多, 可考虑合并同义段")
    for c in chunks:
        n = chars_of(c.get("text", ""))
        if n > CHUNK_WARN:
            warns.append(f"[R3] {c.get('id','?')} 段 {n} 字 > {CHUNK_WARN}——一段塞多信息点, 建议拆成两口气")

    # R4 句级呼吸
    for c in chunks:
        cid = c.get("id", "?")
        for s in PUNCT_SPLIT.split(c.get("text", "")):
            n = chars_of(s)
            if n > max_sent:
                errors.append(f"[R4] {cid} 长句 {n} 字 > {max_sent}——拆成 20~40 字口播单元, 中间给句读停顿")
            elif n > SENT_WARN:
                warns.append(f"[R4] {cid} 句 {n} 字接近上限, 建议拆分留呼吸")

    # R2 骨架(轻量, WARN 级) + V8.0 CTA 类型化检查
    first, last = chunks[0], chunks[-1]
    if first.get("emotion") != "hook":
        warns.append(f"[R2] 首段 emotion={first.get('emotion')!r} 非 hook——开头 3s 需要钩子留人")
    if profile["cta_required"] and last.get("emotion") != "cta":
        warns.append(f"[R2] 末段 emotion={last.get('emotion')!r} 非 cta——{genre} 类型要求行动引导")
    if profile["cta_required"] and not any(p in last.get("text", "") for p in profile["cta_patterns"]):
        warns.append(f"[R2] 末段 CTA 未命中 {genre} 类型措辞 {profile['cta_patterns']}")

    # V8.0 广告法红线机检(仅 ad 类型)
    if profile["ad_law"]:
        for c in chunks:
            for pat in AD_LAW_PATTERNS:
                m = pat.search(c.get("text", ""))
                if m:
                    errors.append(f"[广告法] {c.get('id','?')} 含红线表述「{m.group(0)}」——{AD_LAW_HINT}")

    report = {"chars": total, "chunks": len(chunks), "info_pts_est": est, "genre": genre,
              "est_narration_s": round(narr_s, 1), "est_video_s": round(narr_s * PACE_TO_VIDEO, 1)}
    return errors, warns, report


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path, help="production 项目目录(含 chunks.json)")
    ap.add_argument("--genre", type=str, default=None, choices=[*GENRE_LIMITS],
                    help="文案类型(V8.2.2;缺省读 chunks.json 顶层 genre 或 qa/genre-detect.json,兜底 knowledge)")
    ap.add_argument("--max-chars", type=int, default=None, help="V3.21 起默认不设限; 传入才启用软上限 WARN")
    ap.add_argument("--max-chars-hard", type=int, default=None, help="V3.21 起默认不设限; 传入才启用硬上限 ERROR")
    ap.add_argument("--min-chars", type=int, default=None)
    ap.add_argument("--max-sent", type=int, default=MAX_SENT)
    ap.add_argument("--info-pts", type=int, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args(argv)

    # V8.1 genre 解析: --genre > chunks.json 顶层 genre > qa/genre-detect.json > knowledge
    genre = a.genre
    if genre is None and (a.project / "chunks.json").exists():
        try:
            genre = json.loads((a.project / "chunks.json").read_text(encoding="utf-8"))[0].get("genre")
        except Exception:
            genre = None
    if genre is None and (a.project / "qa" / "genre-detect.json").exists():
        genre = json.loads((a.project / "qa" / "genre-detect.json").read_text(encoding="utf-8")).get("genre")
    genre = genre or "knowledge"
    # V3.21(用户 2026-09-20 定): **不限字数、不限时长, 以用户给的文案为准, 不砍内容。**
    # genre 只用来决定 CTA 措辞与广告法机检, 不再决定长度预算。
    # 需要临时套预算时显式传 --max-chars / --min-chars / --info-pts 即可。
    max_chars, max_chars_hard = a.max_chars, a.max_chars_hard
    min_chars, info_pts = a.min_chars, a.info_pts

    errors, warns, report = check(a.project, max_chars, max_chars_hard, min_chars,
                                  a.max_sent, info_pts, genre)
    print(f"genre={genre} | 字数 {report['chars']} | chunk {report['chunks']} | "
          f"预计旁白 {report['est_narration_s']}s → 成片约 {report['est_video_s']}s"
          f"(V3.21: 不限时长, 此数仅供知情)")
    if info_pts is not None:
        print(f"  自设信息点预算 {info_pts} | 预期信息点 {report['info_pts_est']}")
    for w in warns:
        print("WARN:", w)
    if errors:
        print("=== FAIL ===")
        for e in errors:
            print(" ", e)
        if a.json_out:
            a.json_out.parent.mkdir(parents=True, exist_ok=True)
            a.json_out.write_text(
                json.dumps({"pass": False, "report": report,
                            "warns": warns, "errors": errors},
                           ensure_ascii=False, indent=1), encoding="utf-8")
        return 1
    ran = "R4 句级呼吸 + R2 骨架/CTA + 广告法" + (" + 自设长度预算" if any(
        v is not None for v in (max_chars, max_chars_hard, min_chars, info_pts)) else "(V3.21 未设长度限)")
    print(f"PASS: 文案机检通过[{ran}], 可进 TTS")
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(
            json.dumps({"pass": True, "report": report,
                        "warns": warns, "errors": []},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))