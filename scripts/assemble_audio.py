# -*- coding: utf-8 -*-
"""V8.1.7 assemble_audio.py —— 混音时间轴自动装配(P18 教训①⑤ 机制化)

读 splice_manifest(chunks scene 映射) + assets/audio 实测时长 + sut.json 数字句时间窗,
自动生成 mix_audio4.py 的 NARRATION/EVENTS/TARGET 常量区,并自动避让 SFX 与数字句/关键词重叠。

用法:
  py assemble_audio.py <项目目录>                # 打印装配结果
  py assemble_audio.py <项目目录> --write        # 直接改写项目根 mix_audio4.py 常量区(需先复制模板)
  py assemble_audio.py <项目目录> --dry          # 只打印 NARRATION/EVENTS/TARGET, 不落盘

EVENTS 默认策略(可 --sfx 覆盖次数):
  - 每场景 1 个事件(场景起始 + 15% 时长), 音效名按位置轮换 thud/pop/riser/chime/tick
  - 自动避让: sut.json 中 has_number 或含数字的单元时间窗(±0.8s 禁放), 冲突则向窗后偏移
  - 转场帧不挂音效(0.4s 气口代替音效轰炸, 红线 9)
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

try:
    from env_paths import ffprobe as _FFPROBE_FN
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from env_paths import ffprobe as _FFPROBE_FN

FPS = 30
GAP = 0.4          # 旁白起始气口(场景起点 + GAP)
SFX_POOL = ["thud", "pop", "riser", "chime", "tick"]
NUM_RE = re.compile(r"[0-9０-９%‰]|[一二三四五六七八九十百千万亿]+[个项家次倍天年元张条]|数字|百分比")


def parse_manifest(proj: Path) -> list[tuple[str, int]]:
    mp = proj / "splice_manifest.json"
    if mp.exists():
        entries = json.loads(mp.read_text(encoding="utf-8"))
        return [(str(e[0]), int(e[1])) for e in entries if isinstance(e, (list, tuple)) and len(e) >= 2]
    scenes = sorted(proj.glob("scene_s*.json"))
    if not scenes:
        raise SystemExit("[FAIL] 无 splice_manifest 且无 scene_s*.json")
    return [(s.stem.replace("scene_", "frames_"), round(json.loads(s.read_text(encoding="utf-8"))["duration_s"] * FPS))
            for s in scenes]


def load_chunks(proj: Path) -> list[dict]:
    return json.loads((proj / "chunks.json").read_text(encoding="utf-8-sig"))


def audio_duration(p: Path) -> float:
    import subprocess
    r = subprocess.run([_FFPROBE_FN(), "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                        str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise SystemExit(f"[FAIL] 无法探测音频时长: {p}")


def number_windows(proj: Path) -> list[tuple[float, float]]:
    """sut.json 中数字句/关键词单元的全局时间窗(用于 SFX 避让)"""
    sp = proj / "sut.json"
    if not sp.exists():
        return []
    try:
        data = json.loads(sp.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    units = data if isinstance(data, list) else data.get("units", [])
    wins = []
    for u in units:
        txt = str(u.get("text", ""))
        sec = u.get("sec") or u.get("start_s")
        if sec is None:
            continue
        if u.get("has_number") or NUM_RE.search(txt):
            wins.append((float(sec) - 0.8, float(sec) + 0.8))
    return wins


def build(proj: Path, sfx_count: int | None) -> dict:
    chunks = load_chunks(proj)
    manifest = parse_manifest(proj)
    total = sum(f for _, f in manifest)
    target = round(total / FPS, 3)

    # 场景(chunk)起点(含转场, 1 基帧 → 秒)
    scene_starts: dict[str, float] = {}
    t = 1
    for name, frames in manifest:
        if name.startswith("frames_s"):
            scene_starts[name.replace("frames_s", "s")] = (t - 1) / FPS
        t += frames

    narration = []
    order = []
    for i, c in enumerate(chunks, start=1):
        sc = str(c.get("scene", "") or f"s{i:02d}").lower()
        if not sc.startswith("s"):
            sc = f"s{i:02d}"
        start = scene_starts.get(sc)
        if start is None:
            raise SystemExit(f"[FAIL] chunks[{i}] scene={sc} 不在 splice_manifest 场景列表中")
        narration.append((f"chunk_{i:02d}", round(start + GAP, 3)))
        order.append(sc)
    # 金句(若有 climax_cq): 插在最后一个 chunk 结束前? —— 默认插在倒数第 2 与最后之间无法自动判断, 交由人工; 若存在则追加提示
    cq = proj / "assets/audio/climax_cq.mp3"
    extra = None
    if cq.exists():
        extra = {"name": "climax_cq", "file": cq, "dur": audio_duration(cq)}

    # EVENTS: 每场景 1 个, 避让数字窗
    events = []
    wins = number_windows(proj)
    # V3.21: 字数不设限后长稿合法, 段数可以远超音效预算。旧版 n=len(narration) 会生成
    # 21+ 条事件, 直接撞上 mix_audio4 的 R6 断言(len(EVENTS)<=20)让混音整步崩掉。
    SFX_BUDGET = 20
    n = min(sfx_count or len(narration), SFX_BUDGET)
    if n < len(narration):
        print(f"[R6] 旁白 {len(narration)} 段 > 音效预算 {n} —— 自动**全片均匀铺点**(不是只铺前 n 段), "
              f"想改密度用 --sfx N 或手写 qa/events.json")
        idxs = sorted({round(i * (len(narration) - 1) / max(1, n - 1)) for i in range(n)})
    else:
        idxs = list(range(len(narration)))
    used = set()
    for i in idxs:
        name, start = narration[i]
        t_off = 0.15 * audio_duration(proj / "assets/audio" / f"{name}.mp3")
        t0 = start + t_off
        # 避让
        guard = 0
        while any(a - 0.6 <= t0 <= b + 0.6 for a, b in wins) and guard < 8:
            t0 += 0.7
            guard += 1
        # 不越过下一段起点
        nxt = narration[i + 1][1] if i + 1 < len(narration) else target - 0.5
        if t0 > nxt - 0.5:
            t0 = start + 0.1
        ev = (SFX_POOL[i % len(SFX_POOL)], round(t0, 2), -10)
        events.append(ev)
        used.add(ev[1])

    return {"target": target, "narration": narration, "events": events,
            "total_frames": total, "extra": extra}


def render(cfg: dict) -> str:
    n = "".join(f'    ("{k}", {v:.3f}),\n' for k, v in cfg["narration"])
    e = "".join(f'    ("{k}", {v}, {db}),\n' for k, v, db in cfg["events"])
    extra = ""
    if cfg["extra"]:
        extra = (f"  # 提示: 检测到金句 {cfg['extra']['name']}({cfg['extra']['dur']:.2f}s)——"
                 f"手动加入 NARRATION 并排在对应场景旁白之后\n")
    return (f"TARGET = {cfg['target']}        # ← {cfg['total_frames']} 帧 / {FPS}\n"
            f"NARRATION = [  # ← (mp3 名, 起始秒) 自动装配\n{n}]\n"
            f"EVENTS = [  # ← (音效名, 全局秒, dB) 已避让数字句窗\n{e}]\n{extra}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--write", action="store_true", help="改写项目根 mix_audio4.py 常量区")
    ap.add_argument("--sfx", type=int, default=None, help="SFX 条数上限(默认=场景数)")
    a = ap.parse_args()
    cfg = build(a.project, a.sfx)
    text = render(cfg)
    print(text)
    if a.write:
        mp = a.project / "mix_audio4.py"
        if not mp.exists():
            print("\n[跳过] 项目根无 mix_audio4.py——先复制模板到项目根再 --write")
            return 1
        src = mp.read_text(encoding="utf-8")
        # 替换 TARGET=... 到 EVENTS=[...] 常量块(含 FINAL_TRIM 之间的内容)
        pat = re.compile(r"TARGET = [^\n]+\n(?:FINAL_TRIM_DB = [^\n]+\n\n?)?NARRATION = \[.*?\]\n\nEVENTS = \[.*?\]\n",
                         re.S)
        block = f"TARGET = {cfg['target']}        # ← 自动装配\nFINAL_TRIM_DB = 0.0\nNARRATION = [\n" + \
                "".join(f'    ("{k}", {v:.3f}),\n' for k, v in cfg["narration"]) + "]\n\nEVENTS = [\n" + \
                "".join(f'    ("{k}", {v}, {db}),\n' for k, v, db in cfg["events"]) + "]\n"
        if not pat.search(src):
            print("[跳过] mix_audio4.py 常量区结构不匹配(非模板?), 请手动改")
            return 1
        mp.write_text(pat.sub(block, src, count=1), encoding="utf-8")
        print(f"\n[OK] 已写入 {mp} 的 TARGET/NARRATION/EVENTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
