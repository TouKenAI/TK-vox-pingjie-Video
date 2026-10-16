#!/usr/bin/env python3
"""V6.9 逐段时长红线门(防配音重叠)——拼接/混音前必跑。

读上屏清单 splice_manifest.json(场景帧数, 自动剥离转场条目) + 每段旁白实测时长,
逐段断言: 场景帧时长 × 30fps ≥ 旁白时长 × FACTOR(默认 1.02, 可 --factor)。
任何一段不满足 → 退出码 1 + 列明细, 禁止进入拼接/混音装配(事故根因=时长错位→段未播完下段叠入)。

用法: py -3.12 <skill>/scripts/check_timeline_ratio.py <项目目录> [--factor 1.02] [--json-out qa/timeline-ratio.json]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

FPS = 30
# 豆包适配：ffprobe 走 env_paths 单一事实源(环境变量优先→WinGet→PATH 完整版校验)
from env_paths import ffprobe as _ffprobe  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉
FFPROBE = _ffprobe()
FAIL_MSG = ("时长红线被破: 场景画面时长不足, 该段旁白未播完就会切走/下段叠入。"
            "严禁用提语速/压缩旁白兜底; V3.21 起文案也不许砍——唯一正确做法: 扩该场景帧数后重排时间轴。")


def audio_duration(mp3: Path) -> float:
    import subprocess
    r = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(mp3)], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"ffprobe 解析失败(禁用任何其他兜底): {mp3}\n{r.stderr}")
    return float(r.stdout.strip())


def parse_manifest(p: Path) -> list[tuple[str, int]]:
    """返回 [(场景名, 帧数)]; 只取 shots 条目, trans 转场帧不纳入."""
    manifest = json.loads(p.read_text(encoding="utf-8-sig"))
    out = []
    for item in manifest:
        if not isinstance(item, list) or len(item) < 3:
            continue
        name, frames, kind = item[0], item[1], item[2]
        if kind == "shots":
            out.append((name, int(frames)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", type=Path)
    ap.add_argument("--factor", type=float, default=1.02)
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()
    proj: Path = args.proj

    mp = proj / "splice_manifest.json"
    if mp.exists():
        manifest = parse_manifest(mp)
        if not manifest:
            print("[FAIL] splice_manifest.json 无 shots 条目", file=sys.stderr)
            return 1
    else:
        # V8.1.1: 首渲前(拼接前)无 manifest——用 scene JSON duration_s×30 推导帧数,
        # 与渲染器将产出的帧数一致;拼接后必须用实测 manifest 重跑本门(SOP R5)。
        scenes = sorted(proj.glob("scene_s*.json"))
        if not scenes:
            print("[FAIL] 无 splice_manifest 且无 scene_s*.json", file=sys.stderr)
            return 1
        manifest = [(s.stem.replace("scene_", "frames_"),
                     round(json.loads(s.read_text(encoding="utf-8"))["duration_s"] * 30))
                    for s in scenes]
        print("[提示] 拼接前校验: 帧数取自 scene JSON duration_s×30(拼接后请用实测 manifest 重跑)")

    # V8.1.1: 场景→chunk 显式映射(chunks.json 的 scene 字段优先; 无则按序号 chunk_{i:02d})
    scene_chunks: dict[str, list[str]] = {}
    if (proj / "chunks.json").exists():
        # V3.26: 旧版 `except Exception: scene_chunks = {}` 会把解析失败**变成退回按位置猜**,
        # 而这正是 p15 尾部旁白整条错位的成因。chunks.json 坏了必须当场炸, 不许降级。
        chunks = json.loads((proj / "chunks.json").read_text(encoding="utf-8-sig"))
        for i, c in enumerate(chunks, start=1):
            sc = str(c.get("scene", "") or "")
            m = re.fullmatch(r"[Ss](\d+)", sc)   # 旧版写 \d{2}, "S3"/"S100" 匹配不上会静默丢映射
            if m:
                scene_chunks.setdefault(f"S{int(m.group(1)):02d}", []).append(f"chunk_{i:02d}")

    rows, fails = [], []
    for i, (name, frames) in enumerate(manifest, start=1):
        # V3.26: 场号取自 manifest 里真实的 frames_sNN, 不取枚举位置。SKILL §58 已定死
        # "凡跨层映射必须读显式字段", 这里此前仍按位置猜: 场号一旦不连续(删过场/重编号),
        # 旁白窗口整条错位, PASS 和 FAIL 都可能是错的。
        _mn = re.fullmatch(r"frames_s(\d+)", str(name))
        if not _mn:
            fails.append(f"{name}: manifest 场景名不符合 frames_sNN, 无法确定场号(拒绝按位置猜)")
            continue
        scene_no = f"S{int(_mn.group(1)):02d}"
        chunk_names = scene_chunks.get(scene_no) or [f"chunk_{i:02d}"]
        if scene_chunks and scene_no not in scene_chunks:
            print(f"[WARN] {scene_no} 在 chunks.json 里没有任何 chunk 声明归属, 暂按位置取 "
                  f"chunk_{i:02d} —— 场号与段号不重合时这个猜测是错的")
        adur = 0.0
        for cn in chunk_names:
            cp = proj / "assets" / "audio" / f"{cn}.mp3"
            if cp.exists():
                adur += audio_duration(cp)
        sdur = frames / FPS
        ratio = sdur / adur if adur > 0 else float("inf")
        ok = (adur > 0) and (ratio >= args.factor)  # V3.1: 缺旁白=事故, 不再免费 PASS
        rows.append({"scene": name, "chunk": "+".join(chunk_names),
                     "audio_s": round(adur, 3), "scene_s": round(sdur, 3),
                     "ratio": None if adur == 0 else round(ratio, 3), "ok": ok})
        if not ok:
            fails.append(rows[-1])

    for r in rows:
        tag = "OK " if r["ok"] else "FAIL"
        print(f"  [{tag}] {r['scene']:6s} 旁白 {r['audio_s']:7.3f}s "
              f"场景 {r['scene_s']:7.3f}s 比例 {r['ratio'] if r['ratio'] is not None else '(无旁白)':>7}")

    if args.json_out:
        (proj / args.json_out).parent.mkdir(parents=True, exist_ok=True)
        (proj / args.json_out).write_text(json.dumps({"factor": args.factor, "rows": rows},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")

    if fails:
        print(f"\n[BLOCK] {len(fails)}/{len(rows)} 段不满足 场景时长≥旁白×{args.factor}:")
        for f in fails:
            if f["audio_s"] == 0:
                print(f"  {f['scene']}: 缺旁白文件(assets/audio/{f['chunk']}.mp3)——补 TTS 后重跑")
            else:
                print(f"  {f['scene']}: 场景 {f['scene_s']}s < 旁白 {f['audio_s']}s × {args.factor}")
        print(FAIL_MSG)
        return 1
    print(f"\n[PASS] 逐段时长红线 {len(rows)} 段全过(factor={args.factor}): 无配音重叠风险")
    return 0


if __name__ == "__main__":
    sys.exit(main())