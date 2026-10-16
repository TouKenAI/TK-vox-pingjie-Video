#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.4 词/短语级音画卡点（①）。

本机 StepFun ASR 只回整段文本、无词级时间戳，polycheck align 只能 char_ratio 估。
本工具用 ffmpeg silencedetect 找语音段(停顿=句/短语边界)，把 chunks 文本按标点切成短语，
按字数把短语铺到真实语音时间轴上，产出 qa/phrase_timing.json：
  {"chunk_02":[{"phrase":"...","start":1.23,"end":3.40}, ...], ...}
build_scenes 用 frame_for_phrase() 让字卡/道具在"说到那句的帧"出现，而非固定比例。

用法:
  py word_timing.py <项目目录> [--noise -30dB] [--mindur 0.22]
  # 取某短语在场景内的触发帧：
  py word_timing.py <项目> --get chunk_02 "93 万人预约" --scene-start 0 --fps 30
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

PUNCT = re.compile(r"[。！？!?；;，,、\n]+")


def _ffprobe():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from env_paths import ffprobe, ffmpeg
    return str(ffmpeg()), str(ffprobe())


def speech_segments(mp3: Path, noise: str, mindur: float):
    ffm, _ = _ffprobe()
    r = subprocess.run([ffm, "-i", str(mp3), "-af",
                        f"silencedetect=noise={noise}:d={mindur}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    dur = _dur(mp3)
    sil = []
    start = None
    for line in (r.stderr or "").splitlines():
        m = re.search(r"silence_start:\s*([\d.]+)", line)
        if m: start = float(m.group(1))
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and start is not None:
            sil.append((start, float(m.group(1)))); start = None
    # 语音段 = 静音之间的区间
    segs, pos = [], 0.0
    for s, e in sil:
        if s > pos + 0.05:
            segs.append((pos, s))
        pos = e
    if pos < dur - 0.05:
        segs.append((pos, dur))
    return segs or [(0.0, dur)], dur


def _dur(mp3: Path) -> float:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import audio_duration as A
    return A.duration(mp3)


def _pos_to_time(segs, pos):
    """把'语音累计位置'映射回真实秒(跳过静音间隙)。"""
    acc = 0.0
    for s, e in segs:
        d = e - s
        if pos <= acc + d:
            return s + (pos - acc)
        acc += d
    return segs[-1][1]


def phrase_timing(text: str, segs, dur: float):
    """按标点切短语，按字数把短语铺到语音段(段间静音自然成为停顿)。"""
    phrases = [p.strip() for p in PUNCT.split(text) if p.strip()]
    if not phrases:
        return []
    weights = [max(1, len(re.sub(r"[\s\W_]+", "", p))) for p in phrases]
    total_w = sum(weights)
    total_speech = sum(e - s for s, e in segs)
    out, cum = [], 0.0
    for p, w in zip(phrases, weights):
        span = total_speech * w / total_w
        start = _pos_to_time(segs, cum)
        end = _pos_to_time(segs, cum + span)
        out.append({"phrase": p, "start": round(max(0.0, start), 3), "end": round(min(dur, end), 3)})
        cum += span
    return out


def build(project: Path, noise: str, mindur: float):
    chunks = json.loads((project / "chunks.json").read_text(encoding="utf-8"))
    result = {}
    for c in chunks:
        mp3 = project / "assets" / "audio" / f"{c['id']}.mp3"
        if not mp3.exists():
            # V3.26: 旧版 `continue` 会让这一段**从 phrase_timing.json 里整个消失**, 下游 build_scenes
            # 的 pf() 取不到就静默退回"按字数摊派"的估算法 —— 卡点错了但没人报错。缺音频必须炸。
            raise SystemExit(f"[FAIL] 缺旁白音频 {mp3} —— 先跑 pipeline tts; 不许跳过该段"
                             f"(跳过会让 phrase_timing 少一条, 下游静默退回字数摊派)")
        segs, dur = speech_segments(mp3, noise, mindur)
        result[c["id"]] = {"dur": round(dur, 3), "phrases": phrase_timing(c["text"], segs, dur)}
    (project / "qa").mkdir(exist_ok=True)
    (project / "qa" / "phrase_timing.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def frame_for_phrase(result, chunk_id, phrase, scene_start_frame, fps=30):
    """短语 → 场景内触发帧(段内0基)。scene_start_frame 通常=0(每场独立)。"""
    for ph in result.get(chunk_id, {}).get("phrases", []):
        if phrase in ph["phrase"] or ph["phrase"] in phrase:
            return scene_start_frame + round(ph["start"] * fps)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--noise", default="-30dB")
    ap.add_argument("--mindur", type=float, default=0.22)
    ap.add_argument("--get", nargs=2, metavar=("CHUNK", "PHRASE"))
    ap.add_argument("--scene-start", type=int, default=0)
    a = ap.parse_args()
    result = build(a.project, a.noise, a.mindur)
    if a.get:
        fr = frame_for_phrase(result, a.get[0], a.get[1], a.scene_start)
        print(f"{a.get[0]} 「{a.get[1]}」 → 场景内帧 {fr}")
        return
    for cid, d in result.items():
        ps = " | ".join(f"{p['phrase'][:8]}@{p['start']:.1f}s" for p in d["phrases"])
        print(f"{cid} (dur {d['dur']}s): {ps}")


if __name__ == "__main__":
    main()
