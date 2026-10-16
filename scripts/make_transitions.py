#!/usr/bin/env python3
"""在两个边界帧之间生成撕纸式转场帧(保持"每帧都是PNG"契约)。

用法:
  py -3.14 tools/make_transitions.py last_A.png first_B.png --out-dir frames_t01 \
      --mode wipeleft --count 15

mode:
  wipeleft   B 从左侧撕入向右扩展(纵向撕裂边)
  wiperight  B 从右侧撕入向左扩展(纵向撕裂边,接力右向动势)
  wipeup     B 从底部升入(横向撕裂边)
  wipediag   B 从左下角对角撕入向右上(对角接力)
  dipblack   前 40% 淡入近黑,后 60% 淡出到 B(情绪换景)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def torn_edge_mask(width: int, height: int, progress: float, axis: str, seed: int) -> np.ndarray:
    """progress 0..1:B 的覆盖比例。axis=x 为纵向撕边(wipeleft)。"""
    rng = np.random.default_rng(seed)
    if axis == "x":
        edge = int(width * progress)
        noise = rng.integers(-7, 8, size=height)
        cols = np.arange(width)[None, :] < (edge + noise[:, None])
        return cols
    edge = int(height * progress)
    noise = rng.integers(-7, 8, size=width)
    rows = np.arange(height)[:, None] >= (height - edge - noise[None, :])
    return rows


def diag_mask(width: int, height: int, progress: float, seed: int) -> np.ndarray:
    """B 从左下角沿对角线向右上生长。"""
    rng = np.random.default_rng(seed)
    xs = np.arange(width)[None, :] / width
    ys = (height - 1 - np.arange(height)[:, None]) / height
    d = (xs + ys) / 2.0 + rng.uniform(-0.03, 0.03, size=(height, width))
    return d < progress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame_a", type=Path)
    parser.add_argument("frame_b", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="trans")
    parser.add_argument("--mode", choices=["wipeleft", "wiperight", "wipeup", "wipediag", "dipblack"], default="wipeleft")
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    a = np.asarray(Image.open(args.frame_a).convert("RGB")).astype(np.float32)
    b = np.asarray(Image.open(args.frame_b).convert("RGB")).astype(np.float32)
    if a.shape != b.shape:
        raise SystemExit(f"size mismatch: {a.shape} vs {b.shape}")
    height, width = a.shape[:2]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    dark = np.array([10, 12, 24], dtype=np.float32) + np.array(
        [args.seed % 5, (args.seed // 5) % 5, (args.seed // 7) % 3], dtype=np.float32
    )
    for index in range(args.count):
        t = (index + 0.5) / args.count
        if args.mode == "dipblack":
            if t <= 0.5:
                x = t / 0.5
                u = x * x * (3 - 2 * x)
                blended = a * (1 - u) + dark * u
            else:
                x = (t - 0.5) / 0.5
                u = x * x * (3 - 2 * x)
                blended = dark * (1 - u) + b * u
        else:
            if args.mode == "wipediag":
                mask = diag_mask(width, height, t, args.seed + index)
            elif args.mode == "wiperight":
                # B 从右缘向左生长:cols >= width - edge
                rng = np.random.default_rng(args.seed + index)
                edge = int(width * t)
                noise = rng.integers(-7, 8, size=height)
                mask = np.arange(width)[None, :] >= (width - edge - noise[:, None])
            else:
                axis = "x" if args.mode == "wipeleft" else "y"
                mask = torn_edge_mask(width, height, t, axis, args.seed + index)
            if mask.ndim == 2:
                mask = mask[..., None]
            # 撕缝处压一道深色接缝线(A 侧 6px 内)
            seam = np.zeros((height, width), dtype=bool)
            if args.mode == "wipeleft":
                edge = int(width * t)
                seam[:, max(0, edge - 6) : max(0, edge)] = True
            elif args.mode == "wiperight":
                edge = width - int(width * t)
                seam[:, min(width, edge) : min(width, edge + 6)] = True
            elif args.mode == "wipeup":
                edge = int(height * (1 - t))
                seam[max(0, edge) : min(height, edge + 6), :] = True
            blended = np.where(mask, b, a)
            blended = np.where(seam[..., None], blended * 0.45, blended)
        out = Image.fromarray(blended.astype(np.uint8), "RGB")
        out.save(args.out_dir / f"{args.prefix}_{index + 1:02d}.png")
    print(f"wrote {args.count} {args.mode} frames -> {args.out_dir}")


if __name__ == "__main__":
    main()
