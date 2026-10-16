#!/usr/bin/env python3
"""在碎片素材表上按网格检测分离纸片的包围盒,输出 render_sequence 可用的 sprite_boxes。

用法:
  py -3.14 tools/sprite_boxes.py dryrun/assets/source/fragments.png --grid 4x4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def detect(path: Path, grid_x: int, grid_y: int, min_opaque: float = 0.04) -> list[list[int]]:
    rgba = np.asarray(Image.open(path).convert("RGBA"))
    alpha = rgba[..., 3]
    height, width = alpha.shape
    boxes: list[list[int]] = []
    for gy in range(grid_y):
        for gx in range(grid_x):
            x0, x1 = width * gx // grid_x, width * (gx + 1) // grid_x
            y0, y1 = height * gy // grid_y, height * (gy + 1) // grid_y
            cell = alpha[y0:y1, x0:x1]
            if float((cell > 40).mean()) < min_opaque:
                continue
            ys, xs = np.nonzero(cell > 8)
            pad = 6
            box = [
                max(0, x0 + int(xs.min()) - pad),
                max(0, y0 + int(ys.min()) - pad),
                min(width, x0 + int(xs.max()) + pad),
                min(height, y0 + int(ys.max()) + pad),
            ]
            if box[2] - box[0] >= 24 and box[3] - box[1] >= 24:
                boxes.append(box)
    return boxes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sheet", type=Path)
    parser.add_argument("--grid", default="4x4")
    parser.add_argument("--min-opaque", type=float, default=0.04)
    args = parser.parse_args()
    grid_x, grid_y = (int(v) for v in args.grid.lower().split("x"))
    boxes = detect(args.sheet, grid_x, grid_y, args.min_opaque)
    print(json.dumps({"sheet": str(args.sheet), "count": len(boxes), "sprite_boxes": boxes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
