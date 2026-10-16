#!/usr/bin/env python3
"""按清单把分段帧(可夹转场帧目录)拼接为全局连续帧序列。

用法:
  py -3.14 tools/splice_frames.py --root production2 --manifest production2/splice_manifest.json

清单为 [目录, 期望帧数, 类型] 数组;类型 shots 匹配 frame_*.png,trans 匹配 trans_*.png。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    out = root / "frames"
    # 拼接前清理旧全局帧, 防止上次重跑残留的越界帧混入(2026-08-25 遗留风险):
    # 若新总帧数 < 旧总帧数, 旧的高位编号帧会静默残留并被当作成品帧。
    out.mkdir(exist_ok=True)
    for stale in out.glob("frame_*.png"):
        stale.unlink()
    segments = json.loads(args.manifest.read_text(encoding="utf-8"))

    global_index = 0
    report = []
    for seg_dir, expected, kind in segments:
        pattern = "frame_*.png" if kind == "shots" else "trans_*.png"
        frames = sorted((root / seg_dir).glob(pattern))
        if len(frames) != expected:
            raise SystemExit(f"{seg_dir}: expected {expected} frames, found {len(frames)}")
        for source in frames:
            global_index += 1
            shutil.copyfile(source, out / f"frame_{global_index:04d}.png")
        report.append({seg_dir: expected})
    print(json.dumps({"total": global_index, "segments": report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
