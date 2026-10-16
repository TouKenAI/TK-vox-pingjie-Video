# -*- coding: utf-8 -*-
"""V8.1.7 asr_final_check.py —— 成片整片 ASR 预演(P18 教训⑤ 机制化)

交付前从成片按场景窗口切段做 ASR 回抽,提前暴露"平台字幕可能出错"的位置。
与 asr_spotcheck(逐段 TTS)互补:本脚本看"混音+编码后"的最终听感。

已知限制(勿误判):
- 场景边界/金句衔接处(旁白尾音 + 下一段首音)ASR 可能合并转写——复核以"单段 TTS ASR"为准
- SFX 与关键词重叠处可能干扰 ASR——混音装配时已自动避让数字句窗(assemble_audio)

用法:
  py asr_final_check.py <项目目录> --mp4 成片.mp4
  py asr_final_check.py <项目目录> --mp4 成片.mp4 --cq-at 84.1   # 金句独立切段复核
退出码: 0=全过(相似度≥0.90) / 1=有重点段(需人工听+重 TTS 或调混音)
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from num_equiv import NUMERIC_RUN, cn2num, numeric_format_only, numeric_mismatch, denorm
from asr_alias import canon as canon_alias, fired_rules, load_alias
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
try:
    from env_paths import ffmpeg as _FFMPEG_FN, ffprobe as _FFPROBE_FN
except ImportError:
    from env_paths import ffmpeg as _FFMPEG_FN, ffprobe as _FFPROBE_FN
import stepfun_tools as sf  # noqa: E402

FPS = 30
NON_WORD = re.compile(r"[\s\W_]+", re.UNICODE)


def audio_duration(p: Path) -> float:
    r = subprocess.run([_FFPROBE_FN(), "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                        str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


def norm(s: str) -> str:
    return NON_WORD.sub("", s).lower()


def lcs_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1] / max(len(a), len(b))


def _narration_starts(proj: Path) -> tuple[dict[str, float], str]:
    """混音真值: 项目 mix_audio.py 的 NARRATION = [("chunk_01", 0.400), …] 就是每段旁白的实际起始秒。
    读它而不是再推一遍——推第二遍就会和混音对不上(p15 实录)。"""
    import re
    for f in ("mix_audio.py", "mix_audio4.py"):
        p = proj / f
        if not p.exists():
            continue
        m = re.search(r"NARRATION\s*=\s*\[(.*?)\n\]", p.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        got = {}
        for cid, sec in re.findall(r'"([A-Za-z0-9_]+)"\s*,\s*([0-9.]+)', m.group(1)):
            got[cid] = float(sec)
        if got:
            return got, f
    return {}, ""


def scene_windows(proj: Path, chunks: list[dict]) -> list[tuple[str, float, float]]:
    """按**场景**定窗口, 一场可以覆盖多段旁白。

    旧版写死 `dur_map["s02"] = chunk_02 时长` —— 即假设"第 N 场 = 第 N 段"。
    p15 第一次出现一场两段(S02=chunk_02+03, S03=chunk_04+05), 于是每场少算一段,
    窗口越往后越早, s04 的窗里听到的是 s03 的台词, 14/15 段相似度掉到 0.04。
    真值优先取混音 NARRATION 的实际起始秒; 取不到再退回 splice_manifest 场景起点 + 该场旁白总长。
    """
    import json
    by_scene: dict[str, list[str]] = {}
    for c in chunks:
        sc = str(c.get("scene", "")).lower()
        if sc:
            by_scene.setdefault(sc, []).append(c["id"])
    durs: dict[str, float] = {}
    for cid in {x for v in by_scene.values() for x in v}:
        p = proj / "assets/audio" / f"{cid}.mp3"
        if p.exists():
            durs[cid] = audio_duration(p)
    starts, src = _narration_starts(proj)

    if src:
        # 逐场先算"旁白实际起止", 再把尾沿**卡在下一场第一句之前**。
        # 定值 +0.35s 的尾巴在段间留白 <0.4s 时会伸进下一句(实测 s04 听到"写图"、s09 听到"但注意",
        # 词全对却把相似度从 1.0 拉到 0.895 → 假 FAIL)。
        spans = []
        for sc in sorted(by_scene):
            ids = [i for i in by_scene[sc] if i in starts]
            if not ids:
                continue
            s0 = min(starts[i] for i in ids)
            s1 = max(starts[i] + durs.get(i, 0.0) for i in ids)
            spans.append([sc, s0, s1])
        wins = []
        for k, (sc, s0, s1) in enumerate(spans):
            nxt = spans[k + 1][1] if k + 1 < len(spans) else None
            prev = spans[k - 1][2] if k else None
            # 头部保护带: 窗口沿贴着旁白起点会把首音节起沿裁掉半个(AAC seek 粒度 + TTS 软起音),
            # ASR 就地丢字 → 假 FAIL(p25 实录: s04 "接着试" 被听成 "这是" 0.846<0.9; 前置余量后
            # 完整转出 "接着是", 音频本来就完好)。尾部同类问题已由 +0.35 处理, 头部同理。
            w0 = s0 - 0.25 if prev is None else max(s0 - 0.25, prev + 0.02)
            w1 = s1 + 0.35 if nxt is None else min(s1 + 0.35, nxt - 0.05)
            wins.append((sc, round(w0, 3), round(max(w1, w0 + 0.5), 3)))
        return wins

    # 退回: splice_manifest 场景起点帧/30 + 该场旁白总长
    mp = proj / "splice_manifest.json"
    entries = json.loads(mp.read_text(encoding="utf-8"))
    segs = [(str(e[0]), int(e[1])) for e in entries if isinstance(e, (list, tuple)) and len(e) >= 2]
    wins, t = [], 0.0
    for name, frames in segs:
        if name.startswith("frames_s"):
            sc = name.replace("frames_s", "s")
            span = sum(durs.get(i, 0.0) for i in by_scene.get(sc, [])) or frames / FPS
            wins.append((sc, round(t + 0.15, 3), round(t + span + 0.5, 3)))
        t += frames / FPS
    return wins


def cut_seg(mp4: Path, start: float, end: float) -> Path:
    tmp = Path(tempfile.mkstemp(suffix=".wav", prefix="asrfc_")[1])
    subprocess.run([_FFMPEG_FN(), "-y", "-v", "error", "-ss", str(start), "-to", str(end),
                    "-i", str(mp4), "-ar", "16000", "-ac", "1", str(tmp)], check=True)
    return tmp


def asr(wav: Path) -> str:
    env = sf.load_env()
    base = sf.setting(env, "STEPFUN_BASE_URL", sf.BASE_DEFAULT).rstrip("/")
    cfg = {"key": sf.setting(env, "STEPFUN_API_KEY"),
           "asr_model": sf.setting(env, "STEPFUN_ASR_MODEL", "stepaudio-2.5-asr"),
           "url_asr_sse": sf.setting(env, "STEPFUN_URL_ASR_SSE", f"{base}/audio/asr/sse")}
    payload = {"audio": {"data": base64.b64encode(wav.read_bytes()).decode(),
                         "input": {"transcription": {"model": cfg["asr_model"], "language": "zh",
                                                     "enable_itn": True},
                                   "format": {"type": "wav", "codec": "pcm_s16le",
                                              "rate": 16000, "bits": 16, "channel": 1}}}}
    out = sf.post_sse(cfg["url_asr_sse"], cfg["key"], payload)
    return str(out)


def _cq_reference(proj: Path, chunks: list[dict], cq_at: float, explicit: str,
                  explicit_dur: float = 0.0) -> tuple[str, float, str]:
    """金句独立切段的**参考文本 + 窗长**。

    V3.34 之前这里传的是空串：`ratio is None` → `strict_ok = True` → 打成 `相似度 N/A` 却恒判 OK。
    一条量不到的检查打成通过，比不检查更糟（§57「假 PASS」同一类）。p23 的 cq_golden 就是这么
    "PASS" 的，而真实原因是 ASR 把「防窥」转写成「王」（同音死区），根本没在量。
    现在参考文本按优先级取：`--cq-text` > 落在 cq_at 那一刻的那一段旁白原文（由混音 NARRATION
    起点 + mp3 实测时长定位）。取不到就 FAIL 并把候选起点列出来，不再猜。
    """
    starts, _src = _narration_starts(proj)
    durs = {}
    for c in chunks:
        p = proj / "assets/audio" / f"{c['id']}.mp3"
        if p.exists():
            durs[c["id"]] = audio_duration(p)
    if explicit:
        win = float(explicit_dur or 0.0)
        src = "显式 --cq-dur"
        if win <= 0:
            cq_mp3 = proj / "assets/audio/climax_cq.mp3"
            if cq_mp3.exists():
                win, src = audio_duration(cq_mp3), "climax_cq.mp3 实测"
        if win <= 0:
            hit = next((cid for cid in durs if starts.get(cid, -1e9) <= cq_at < starts[cid] + durs[cid]), "")
            if hit:
                win, src = durs[hit], f"{hit} 的 mp3 实测"
        if win <= 0:
            raise SystemExit(f"[FAIL] --cq-text 给了但算不出窗长：climax_cq.mp3 不存在、"
                             f"cq_at={cq_at} 也落不进任何一段旁白 —— 补 --cq-dur，别让我猜")
        return explicit, win, f"显式 --cq-text（窗长取{src}）"
    hit = next((cid for cid in sorted(durs, key=lambda k: starts.get(k, 0))
                if starts.get(cid, -1e9) <= cq_at < starts[cid] + durs[cid]), "")
    if not hit:
        cand = ", ".join(f"{cid}@{starts[cid]:.2f}s({next((c.get('emotion','') for c in chunks if c['id']==cid),'')})"
                         for cid in sorted(starts, key=lambda k: starts[k]) if cid in durs)
        raise SystemExit(f"[FAIL] --cq-at {cq_at} 落不进任何一段旁白的实际播放区间 —— 拿不到参考文本，"
                         f"拒绝用空文本冒充通过。\n  候选起点: {cand}")
    text = next((c.get("text_with_cues") or c["text"] for c in chunks if c["id"] == hit), "")
    emo = next((c.get("emotion", "") for c in chunks if c["id"] == hit), "")
    cq_mp3 = proj / "assets/audio/climax_cq.mp3"
    win = audio_duration(cq_mp3) if cq_mp3.exists() else durs[hit]
    note = f"{hit}(emotion={emo or '未标'})"
    if emo != "climax":
        note += " ⚠ 不是金句段——确认 --cq-at 秒数是否指错"
    return text, win, note


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--mp4", required=True)
    ap.add_argument("--cq-at", type=float, default=None, help="重庆话/独立金句起始秒, 单独切段复核")
    ap.add_argument("--cq-text", default="", help="V3.34: 金句段的参考文本(不给就按 cq-at 自动定位那一段旁白)")
    ap.add_argument("--cq-dur", type=float, default=0.0,
                    help="V3.34: 配 --cq-text 用的窗长(秒)。缺省取 climax_cq.mp3 实测或 cq-at 所在段的 mp3 时长")
    ap.add_argument("--thresh", type=float, default=0.90)
    a = ap.parse_args()

    # V3.26 路径归一: 旧版无条件 `a.project / a.mp4`, 于是从仓库根敲
    # `--mp4 production16/output/final.mp4` 会拼成 production16/production16/output/... → 假报"成片不存在"
    # (与 §54 gen_assets --raw-dir 同一类病)。绝对路径与"当前目录下确实存在的路径"必须原样用。
    mp4 = Path(a.mp4)
    if not mp4.exists():
        mp4 = a.project / a.mp4
    if not mp4.exists():
        raise SystemExit(f"[FAIL] 成片不存在: 原样试过 {a.mp4}, 挂项目目录试过 {mp4}")

    _cj = a.project / "chunks.json"
    if not _cj.exists():
        # 旧版在这里直接 read_text → FileNotFoundError traceback。缺参考稿是"没稿可比", 不是崩溃。
        raise SystemExit(f"[FAIL] {_cj} 不存在 —— 整片 ASR 需要参考文本逐段比对, 拒绝在没有 chunks.json 时假装通过")
    chunks = json.loads(_cj.read_text(encoding="utf-8-sig"))
    wins = scene_windows(a.project, chunks)
    # 一场多段时参考文本要**拼接**(旧版 dict 推导让同 scene 的后一段覆盖前一段 → 参考文本缺半句)
    text_by_scene: dict[str, str] = {}
    for c in chunks:
        sc = str(c.get("scene", "")).lower()
        if sc:
            text_by_scene[sc] = (text_by_scene.get(sc, "") + " " +
                                 (c.get("text_with_cues") or c["text"])).strip()

    segs = []
    for sc, s0, s1 in wins:
        segs.append((sc, s0, s1, text_by_scene.get(sc, "")))
    if a.cq_at is not None:
        cq_ref, cq_dur, cq_note = _cq_reference(a.project, chunks, a.cq_at, a.cq_text, a.cq_dur)
        print(f"[cq] 参考文本取自 {cq_note}: 「{cq_ref[:36]}…」 窗长 {cq_dur:.2f}s")
        segs.append(("cq_golden", a.cq_at - 0.15, a.cq_at + cq_dur + 0.3, cq_ref))
    # V3.34: 没有参考文本的窗口一律不许进比对——旧版 ref="" 时 ratio=None → strict_ok=True，
    # 打成"相似度 N/A"却算通过。量不到就是量不到，必须响。
    empty = [sc for sc, _, _, ref in segs if not ref.strip()]
    if empty:
        raise SystemExit(f"[FAIL] {len(empty)} 个窗口拿不到参考文本: {empty} —— "
                         f"chunks.json 里这些场没有 text，或 scene 字段对不上；拒绝用空文本冒充通过")

    fails, rows = [], []
    AMAP = load_alias(a.project)
    for sc, s0, s1, ref in segs:
        wav = cut_seg(mp4, s0, s1)
        try:
            got = asr(wav)
        finally:
            try:
                wav.unlink(missing_ok=True)
            except PermissionError:
                pass  # Windows 句柄暂锁, Temp 目录残留无害
        ratio = lcs_ratio(norm(ref), norm(got)) if ref else None
        nratio = lcs_ratio(denorm(norm(ref)), denorm(norm(got))) if ref else None
        strict_ok = ratio is None or ratio >= a.thresh
        # 复核放行需同时满足: ①所有数字串数值等价(八百↔800 可, 八百↔九百 不可) ②非数字残差本身达标
        numeric_only = (not strict_ok) and nratio is not None and nratio >= a.thresh \
            and numeric_format_only(norm(ref), norm(got))
        mism = numeric_mismatch(norm(ref), norm(got)) if ref else []
        # 念对但 ASR 转写不同(英文专名同音拼写 / 中文同音代词) → 只认项目内显式声明的别名, 且必须打印命中项
        aratio = lcs_ratio(canon_alias(norm(ref), AMAP), canon_alias(norm(got), AMAP)) \
            if ref and not strict_ok and not numeric_only and not mism else ratio
        alias_only = bool(aratio is not None and aratio >= a.thresh
                          and not strict_ok and not numeric_only and not mism)
        if mism:
            print(f"  [FAIL] {sc:8s} 数字对不上: " + " ".join(f"{x}≠{y}" for x, y in mism)
                  + f"(相似度 {ratio:.3f} 偏高不足以暴露, 由精确断言拦截)")
        ok = (strict_ok or numeric_only or alias_only) and not mism
        tag = "OK " if ok else "FAIL"
        if not ok:
            fails.append(sc)
        rows.append({"scene": sc, "window_s": [s0, s1], "ref": ref[:60], "asr": got[:120],
                     "ratio": round(ratio, 3) if ratio is not None else None,
                     "ratio_numeric_norm": round(nratio, 3) if nratio is not None else None,
                     "ratio_alias_norm": round(aratio, 3) if aratio is not None else None,
                     "alias_rules": fired_rules(norm(ref), norm(got), AMAP) if alias_only else [],
                     "numeric_mismatch": [list(m) for m in mism]})
        note = ""
        if strict_ok and not mism:
            note = ""
        elif numeric_only and not mism:
            note = "  ←数字转写归一后达标(ASR 把 十/八百 转成 10/800)"
        elif alias_only:
            note = "  ←专名转写别名归一后达标: " + " ".join(fired_rules(norm(ref), norm(got), AMAP))
        print(f"  [{tag}] {sc:8s} 相似度 {ratio if ratio is not None else 'N/A':>7}{note} | {got.strip()[:80]}")

    (a.project / "qa").mkdir(exist_ok=True)
    (a.project / "qa/asr-final-check.json").write_text(
        json.dumps({"thresh": a.thresh, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    if fails:
        print(f"\n[BLOCK] {len(fails)} 段相似度<{a.thresh}: {fails}")
        print("  → 先听该段(或对单段 TTS 做 asr_spotcheck 复核); 若单段完美则多为边界/音效重叠, 以听感为准")
        return 1
    print(f"\n[PASS] 成片整片 ASR 预演通过(阈值 {a.thresh})——平台字幕出错风险位已覆盖")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
