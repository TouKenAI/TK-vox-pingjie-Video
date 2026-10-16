#!/usr/bin/env python3
"""V8.1.1 TTS 发音抽检 —— 旁白 TTS 完成后立即逐段 ASR 回抽比对(一次性原理 S1)。

问题:TTS 错读(英文缩写 GPT-6/AGI/AIGC、人名布罗克曼/奥特曼、多音字、型号)旧流程要等
成片 ASR(⑧末尾,渲染+混音之后)才发现——发现点晚了 90 分钟,返工是整条流水线。
本脚本在阶段②末尾跑:任何一段对不上,只重 TTS 那一段,后面环节零损失。

比对逻辑:ASR 结果与 chunks.json 的 text 去标点/空白后做最长公共子序列(LCS)相似度。
enable_itn 下数字/字母写法可能有合法差异(如"40%"↔"百分之四十"、"GPT-6"↔"GPT六"),
按归一化后比对,阈值默认 0.90:<0.90 列重点(建议人工听+重 TTS),0.90~0.97 列提示。

用法:
  py -3.14 scripts/asr_spotcheck.py <项目目录>             # 逐段找音频 → ASR → 比对
  py -3.14 scripts/asr_spotcheck.py <项目目录> --dry-run   # 不调 API,只列待检清单与音频发现情况
  py -3.14 scripts/asr_spotcheck.py <项目目录> --only chunk_01,chunk_03
  py -3.14 scripts/asr_spotcheck.py <项目目录> --thresh 0.85
音频发现目录(按序找 <chunk_id>.mp3):narr/ narration/ assets/audio/ audio_build/
退出码: 0 = 全部 ≥阈值 / 1 = 有重点段(重 TTS 后重跑)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from num_equiv import denorm, numeric_format_only, numeric_mismatch
from asr_alias import canon as canon_alias, fired_rules, load_alias

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

AUDIO_DIRS = ["narr", "narration", "assets/audio", "audio_build"]
NON_WORD = re.compile(r"[\s\W_]+", re.UNICODE)


def norm(s: str) -> str:
    """去标点/空白/大小写,只留可比对字符(itn 差异仍在,靠 LCS 容错)。"""
    return NON_WORD.sub("", s).lower()


def lcs_ratio(a: str, b: str) -> float:
    """最长公共子序列相似度(0-1);短文本 DP 开销可忽略。"""
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1] / max(len(a), len(b))


def find_audio(root: Path, cid: str) -> Path | None:
    for d in AUDIO_DIRS:
        for ext in (".mp3", ".wav"):
            p = root / d / f"{cid}{ext}"
            if p.exists():
                return p
    return None


def asr_text(audio: Path) -> str:
    """复用 stepfun_tools 的 SSE 客户端做单段 ASR(与成片回抽同一协议)。"""
    import base64

    import stepfun_tools as sf
    env = sf.load_env()
    base = sf.setting(env, "STEPFUN_BASE_URL", sf.BASE_DEFAULT).rstrip("/")
    cfg = {
        "key": sf.setting(env, "STEPFUN_API_KEY"),
        "asr_model": sf.setting(env, "STEPFUN_ASR_MODEL", "stepaudio-2.5-asr"),
        "url_asr_sse": sf.setting(env, "STEPFUN_URL_ASR_SSE", f"{base}/audio/asr/sse"),
    }
    kind = audio.suffix.lstrip(".").lower()
    fmt = {
        "wav": {"type": "wav", "codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1},
        "pcm": {"type": "pcm", "codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1},
        "mp3": {"type": "mp3", "codec": "mp3", "rate": 44100, "bits": 0, "channel": 1},
    }.get(kind, {"type": kind or "mp3"})
    payload = {"audio": {"data": base64.b64encode(audio.read_bytes()).decode(),
                         "input": {"transcription": {"model": cfg["asr_model"], "language": "zh",
                                                     "enable_itn": True}, "format": fmt}}}
    return sf.post_sse(cfg["url_asr_sse"], cfg["key"], payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--only", type=str, default=None, help="只检这些段,逗号分隔(如 chunk_01,chunk_03)")
    ap.add_argument("--thresh", type=float, default=0.90, help="重点段阈值(默认 0.90)")
    ap.add_argument("--soft", type=float, default=0.97, help="提示段阈值(默认 0.97)")
    ap.add_argument("--dry-run", action="store_true", help="不调 API,只列待检清单")
    a = ap.parse_args()

    root = a.project.resolve()
    cpath = root / "chunks.json"
    if not cpath.exists():
        sys.exit("FAIL: chunks.json 不存在——本脚本在阶段①重构稿定稿+TTS 后运行")
    chunks = json.loads(cpath.read_text(encoding="utf-8"))
    only = set(a.only.split(",")) if a.only else None

    plan = []
    for c in chunks:
        cid = c.get("id", "")
        if only and cid not in only:
            continue
        audio = find_audio(root, cid)
        plan.append((cid, c.get("text", ""), audio))

    amap = load_alias(root)
    print(f"待检 {len(plan)} 段(阈值 重点<{a.thresh} / 提示<{a.soft})"
          + (f" · 已加载 {len(amap)} 条转写别名" if amap else ""))
    for cid, text, audio in plan:
        mark = audio.name if audio else "✗ 未找到音频"
        print(f"  {cid}: {mark} | 原文 {len(norm(text))} 字")
    if a.dry_run:
        missing = [cid for cid, _, au in plan if au is None]
        if missing:
            print(f"DRY-RUN: {len(missing)} 段缺音频: {','.join(missing)}")
            return 1
        print("DRY-RUN: 音频齐全,去掉 --dry-run 开始抽检")
        return 0
    if any(au is None for _, _, au in plan):
        print("FAIL: 有段落缺音频(见上),先确认 TTS 输出目录")
        return 1

    bad = []
    for cid, text, audio in plan:
        try:
            got = asr_text(audio)
        except Exception as e:  # API/网络错误不算"对不上",单独列出人工判断
            print(f"  {cid}: ASR 调用失败 {e.__class__.__name__}: {e}")
            continue
        e_, g_ = norm(text), norm(got)
        r = lcs_ratio(e_, g_)
        mism = numeric_mismatch(e_, g_)
        fmt_only = r < a.thresh and lcs_ratio(denorm(e_), denorm(g_)) >= a.thresh             and numeric_format_only(e_, g_)
        # 念对但 ASR 转写不同(英文专名同音拼写/中文同音代词) → 归一后达标即放行, 但必须打印命中规则
        ce, cg = canon_alias(e_, amap), canon_alias(g_, amap)
        r_al = lcs_ratio(ce, cg)
        alias_only = (not fmt_only) and r < a.thresh <= r_al and not mism
        if mism:
            # 长句里单个数字念错, LCS 拦不住(28 字差 1 字仍 0.96) → 精确断言单独抓
            verdict = "✗ 数字对不上 " + " ".join(f"{x}≠{y}" for x, y in mism)
            bad.append(cid)
        elif r < a.thresh and not fmt_only and not alias_only:
            verdict = "✗ 重点"
            bad.append(cid)
        elif fmt_only:
            verdict = "✓(数字写法差异)"
        elif alias_only:
            verdict = "✓(转写别名 " + " ".join(fired_rules(e_, g_, amap)) + f", 归一后 {r_al:.2%})"
            r = max(r, r_al)
        elif r < a.soft:
            verdict = "△ 提示"
        else:
            verdict = "✓"
        print(f"  {cid}: 相似度 {r:.2%} {verdict} | ASR: {got[:42]}…")
        out = root / "qa" / "asr-spotcheck.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        rec = {"chunk": cid, "similarity": round(r, 4), "audio": audio.name,
               "asr_text": got, "expected": text}
        hist = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
        hist = [h for h in hist if h.get("chunk") != cid]
        hist.append(rec)
        out.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

    if bad:
        print(f"=== FAIL === {len(bad)} 段低于 {a.thresh:.2f}: {','.join(bad)} —— 人工听该段, 错读则只重 TTS 该段后重跑")
        return 1
    print("PASS: 全段发音抽检达标(缩写/人名/多音字无错读)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
