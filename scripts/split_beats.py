#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.3 长镜头自动拆子镜头（beat 重取景）。

抖音信息镜头经验值 3–8s 一切；单场旁白 >8s 时，画面若一镜到底会稀释完播、读作"没变化"。
本工具对 duration_s > 阈值的 scene_sNN.json，每 ~beat 秒注入一次 camera punch-in + 交替平移，
让构图每隔几秒"换镜"（纪录片 punch-in 手法），确定性、复用同一背景、不需额外素材。

**V3.28：换镜时机可以跟着语义走，不跟着秒表走。**
若项目里有 `qa/beats.json`，本工具按它给的**语义切点**换镜，而不是套固定网格：
    {"max_scale": 1.06, "scenes": {"S05": [5.6], "S13": [4.2, 6.8]}}
秒数是**场内 0 基秒**，应当来自 KICKOFF B 表那一列（"第四张卡落定之后""说完这句之前"）。
切点落在本场时长之外 → **直接 FAIL 并指名这场只有多少秒**：p17 实测有 4/10 场的切点
是按预估时长写的、根本不在自己场次内，静默忽略等于把创意决定丢掉。
`max_scale` 是给运动语法留的口子（国潮水墨要求幅度全风格最小，不该被默认的 1.11 顶穿）。
没有这个文件时行为与旧版完全一致（等间隔网格）。

用法:
  py split_beats.py <项目目录> [--threshold 8] [--beat 4] [--dry-run]
默认就地改写 scene_sNN.json（首次自动备份 .prebeats.json）；--dry-run 只报告不改。
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉


def load_authored(root: Path):
    """读 qa/beats.json；没有就返回 None(退回网格)。"""
    f = root / "qa" / "beats.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    scenes = d.get("scenes")
    if not isinstance(scenes, dict):
        raise SystemExit(f"[FAIL] {f} 缺 'scenes' 字典(格式 {{\"scenes\": {{\"S05\": [5.6]}}}})")
    return {"scenes": {str(k).upper(): [float(x) for x in v] for k, v in scenes.items()},
            "max_scale": float(d.get("max_scale", 1.11))}


def build_from_cuts(dur: float, cuts: list[float], max_scale: float):
    """按语义切点换镜：每个切点一次 punch-in，方向交替。"""
    frames = round(dur * 30)
    pts = [0.0] + sorted(c for c in cuts if c > 0) + [dur]
    if any(c >= dur for c in cuts):
        raise SystemExit(f"[FAIL] 切点 {[c for c in cuts if c >= dur]} 不在本场时长内(这场只有 {dur:.2f}s) "
                         f"—— KICKOFF 的切点必须按实测时长回填, 不许按预估写")
    kfs = []
    n = len(pts) - 1
    for i in range(len(pts)):
        f = min(frames - 1, round(pts[i] * 30)) if i < len(pts) - 1 else frames - 1
        t = i / n
        # 奇数段推近一档、偶数段退回缓推位；总幅度封顶在 max_scale
        scale = 1.0 + (max_scale - 1.0) * (t if i % 2 == 0 else min(1.0, t + 0.45 / n * 2))
        x = 0 if i == 0 else (34 if i % 2 == 1 else -34)
        kfs.append({"frame": f, "x": x, "y": 0, "scale": round(scale, 3),
                    "rotation": 0, "opacity": 1, "ease": "ease-in-out"})
    prev = -1
    for k in kfs:
        if k["frame"] < prev:
            raise SystemExit(f"[FAIL] 生成的相机关键帧乱序 {prev}→{k['frame']}")
        prev = k["frame"]
    return frames, n, kfs


def build_beats(dur: float, beat: float):
    frames = round(dur * 30)
    n = max(2, math.ceil(dur / beat))
    kfs = []
    for i in range(n + 1):
        # V3.26 修末帧 off-by-one: 渲染器 frame_count=round(fps*duration) 且循环是 range(frame_count),
        # 最大帧号 = frames-1。旧写法末拍落在 f=frames, **永远渲不到**, 最后一拍的终态姿态从不出现
        # (tween 在 frame>=keys[-1] 处静默钳位, 不报错)。实测 p14 s04 最大关键帧 268 / 只有 268 张图。
        f = round(i * (frames - 1) / n)
        t = i / n
        scale = 1.0 + 0.05 * t + (0.06 if i % 2 == 1 else 0.0)   # 缓推 + 奇数拍 punch-in
        x = 0 if i == 0 else (34 if i % 2 == 1 else -34)         # 交替水平重取景
        kfs.append({"frame": f, "x": x, "y": 0, "scale": round(scale, 3),
                    "rotation": 0, "opacity": 1, "ease": "ease-in-out"})
    return frames, n, kfs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--threshold", type=float, default=8.0)
    ap.add_argument("--beat", type=float, default=4.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = a.project.resolve()
    authored = load_authored(root)
    changed = skipped_no_beat = 0
    for sp in sorted(root.glob("scene_s*.json")):
        d = json.loads(sp.read_text(encoding="utf-8"))
        dur = float(d.get("duration_s", 0))
        key = "S" + (sp.stem.replace("scene_s", "") or "?")
        cuts = authored["scenes"].get(key) if authored else None
        if cuts is None and authored:
            # 项目声明了语义切点，却没给这一场 → 不悄悄退回网格，那等于"写了等于没写"没人知道
            skipped_no_beat += 1
            print(f"  [无切点] {key} {dur:.1f}s 未在 qa/beats.json 里声明 → 本场保持一镜到底")
            continue
        if dur <= a.threshold and not cuts:
            continue
        if cuts:
            frames, n, kfs = build_from_cuts(dur, cuts, authored["max_scale"])
            tag = f"{sp.name} {dur:.1f}s → 按语义切点 {cuts} 换 {n} 镜"
        else:
            frames, n, kfs = build_beats(dur, a.beat)
            tag = f"{sp.name} {dur:.1f}s → {n} 子镜头(每~{dur/n:.1f}s 网格)"
        if a.dry_run:
            print("[dry]", tag); changed += 1; continue
        bak = sp.with_suffix(".json.bak")
        if not bak.exists():
            bak.write_text(sp.read_text(encoding="utf-8"), encoding="utf-8")
        d["camera_motion"] = {"fill": [12, 16, 26, 255], "keyframes": kfs}
        sp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("✓", tag); changed += 1
    if not changed and not skipped_no_beat:
        print(f"无 >{a.threshold}s 的场景需要拆分")
    else:
        print(f"{'将' if a.dry_run else '已'}处理 {changed} 个长场景"
              + (f"，{skipped_no_beat} 场无切点保持一镜" if skipped_no_beat else "")
              + ("（dry-run 未改盘）" if a.dry_run else "；重渲受影响场景后生效"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
