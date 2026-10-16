#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.2 转场/拼接清单/时间轴一体化生成器（production2 教训固化）。

根因：转场边界帧、splice_manifest、旁白起始秒都必须来自各场**实际渲染帧数**，
手工硬编码帧数数组会取错边界（production2 实测踩坑：复用上一片 FR 数组导致
部分转场失败/取到场景中段帧）。本工具一律从 frames_sNN 目录实测，杜绝此类 bug。

用法(V3.3 默认硬切为主, 创意转场 ≤3):
  py gen_transitions.py <项目目录> [--at 7,12] [--mode wipeleft] [--dipblack-at 7] [--count 10]
  --at 指定哪些边界加创意转场(默认空=全硬切); --all-boundaries 回到旧行为(每边界都转场)。
产物:
  frames_tNN/（N-1 段转场）· splice_manifest.json · qa/actual_counts.json · qa/scene_starts.json
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉


def scene_counts(root: Path) -> dict[int, int]:
    out = {}
    for d in sorted(root.glob("frames_s*")):
        n = len(list(d.glob("frame_*.png")))
        if n:
            out[int(d.name[-2:])] = n
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--mode", default="wipeleft")
    ap.add_argument("--at", default="", help="逗号分隔的边界序号 k——只有这些边界加创意转场; 默认空=全硬切(精选导向:硬切为主)")
    ap.add_argument("--max-creative", type=int, default=3, help="创意转场上限(精选经验 ≤3)")
    ap.add_argument("--all-boundaries", action="store_true", help="旧行为: 每个边界都加转场")
    ap.add_argument("--dipblack-at", default="", help="逗号分隔的边界序号 k(第k场→第k+1场用dipblack)")
    ap.add_argument("--py", default=sys.executable)
    a = ap.parse_args()
    root = a.project.resolve()
    dip = {int(x) for x in a.dipblack_at.split(",") if x.strip()}
    counts = scene_counts(root)
    idxs = sorted(counts)
    if len(idxs) < 2:
        sys.exit("FAIL: frames_sNN 目录不足 2 个")
    boundaries = [k for k in idxs[:-1]]  # 第 k 场→第 k+1 场的边界
    if a.all_boundaries:
        at_set = set(boundaries)
    else:
        at_set = {int(x) for x in a.at.split(",") if x.strip()}
    if len(at_set) > a.max_creative:
        print(f"WARN: 创意转场 {len(at_set)} 个 > 精选建议上限 {a.max_creative}——建议只留情绪节点(进金句/大转折)")
    at_set &= set(boundaries)
    # dipblack 只是"这个创意转场用哪种模式", 不单独决定生成与否。序号只写在 --dipblack-at 里
    # 会被静默忽略(要压黑却得到硬切, 全程无人报错)。现在直接 FAIL, 不猜你的意图。
    orphan = dip - at_set
    if orphan:
        sys.exit(f"FAIL: --dipblack-at {sorted(orphan)} 不在创意转场序号 {sorted(at_set) or '(空)'} 内 —— "
                 f"把这些序号同时写进 --at, 否则 dipblack 会被静默降级成硬切")
    mt = Path(__file__).resolve().parent / "make_transitions.py"
    if not mt.exists():
        mt = root.parent / "scripts" / "make_transitions.py"

    segs, starts, cum = [], [], 0
    for pos, k in enumerate(idxs):
        segs.append([f"frames_s{k:02d}", counts[k], "shots"])
        starts.append(round(cum / 30.0, 4))
        cum += counts[k]
        if pos < len(idxs) - 1 and k in at_set:
            nxt = idxs[pos + 1]
            fa = root / f"frames_s{k:02d}" / f"frame_{counts[k]:04d}.png"
            fb = root / f"frames_s{nxt:02d}" / "frame_0001.png"
            tdir = root / f"frames_t{k:02d}"
            mode = "dipblack" if k in dip else a.mode
            r = subprocess.run([a.py, str(mt), str(fa), str(fb), "--out-dir", str(tdir),
                                "--mode", mode, "--count", str(a.count)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                print(f"FAIL t{k:02d}: {r.stderr[-200:]}"); return 1
            segs.append([f"frames_t{k:02d}", a.count, "trans"])
            cum += a.count

    (root / "splice_manifest.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
    (root / "qa").mkdir(exist_ok=True)
    (root / "qa" / "actual_counts.json").write_text(json.dumps([counts[k] for k in idxs]), encoding="utf-8")
    (root / "qa" / "scene_starts.json").write_text(json.dumps(starts), encoding="utf-8")
    hard = (len(idxs) - 1) - len(at_set)
    print(f"{len(idxs)} 场 · 创意转场 {len(at_set)} 段 + 硬切 {hard} 处 · 总帧 {cum} = {cum/30:.2f}s")
    print("场景起始秒:", starts)
    print("已写 splice_manifest.json / qa/scene_starts.json / qa/actual_counts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
