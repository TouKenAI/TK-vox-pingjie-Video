#!/usr/bin/env python3
"""Validate frame count, dimensions, uniqueness, continuity, and black frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect(
    frames_dir: Path,
    expected_count: int,
    expected_size: tuple[int, int],
    min_delta: float,
    max_delta: float,
) -> dict:
    frames = sorted(frames_dir.glob("frame_*.png"))
    names_expected = [f"frame_{index:04d}.png" for index in range(1, expected_count + 1)]
    errors: list[str] = []
    if [path.name for path in frames] != names_expected:
        errors.append(f"expected contiguous frame_0001..frame_{expected_count:04d}; found {len(frames)}")
    wrong_size = []
    black_frames = []
    hashes = []
    previews = []
    for path in frames:
        with Image.open(path) as image:
            if image.size != expected_size:
                wrong_size.append({"file": path.name, "size": list(image.size)})
            gray = image.convert("L").resize((320, 180), Image.Resampling.BILINEAR)
            mean_luma = ImageStat.Stat(gray).mean[0]
            if mean_luma < 2.0:
                black_frames.append(path.name)
            previews.append(gray.copy())
        hashes.append(digest(path))
    if wrong_size:
        errors.append(f"{len(wrong_size)} frames have wrong dimensions")
    if black_frames:
        errors.append(f"{len(black_frames)} frames are effectively black")

    adjacent_exact_duplicates = []
    deltas = []
    for index in range(1, len(frames)):
        if hashes[index] == hashes[index - 1]:
            adjacent_exact_duplicates.append([frames[index - 1].name, frames[index].name])
        diff = ImageChops.difference(previews[index - 1], previews[index])
        deltas.append(ImageStat.Stat(diff).mean[0])
    low_motion = [index + 2 for index, value in enumerate(deltas) if value < min_delta]
    extreme_jumps = [index + 2 for index, value in enumerate(deltas) if value > max_delta]
    if adjacent_exact_duplicates:
        errors.append(f"{len(adjacent_exact_duplicates)} adjacent frame pairs are byte-identical")
    duplicate_hashes = [value for value, count in Counter(hashes).items() if count > 1]
    if duplicate_hashes:
        errors.append(f"{len(duplicate_hashes)} frame hashes occur more than once")
    if low_motion:
        errors.append(f"{len(low_motion)} adjacent pairs fall below min_delta={min_delta}")
    if extreme_jumps:
        errors.append(f"{len(extreme_jumps)} adjacent pairs exceed max_delta={max_delta}")

    return {
        "ok": not errors,
        "frame_count": len(frames),
        "expected_count": expected_count,
        "dimensions": list(expected_size),
        "wrong_size": wrong_size,
        "black_frames": black_frames,
        "adjacent_exact_duplicates": adjacent_exact_duplicates,
        "duplicate_hash_groups": len(duplicate_hashes),
        "low_motion_frame_numbers": low_motion,
        "extreme_jump_frame_numbers": extreme_jumps,
        "delta": {
            "min": min(deltas) if deltas else None,
            "median": statistics.median(deltas) if deltas else None,
            "max": max(deltas) if deltas else None,
            "mean": statistics.fmean(deltas) if deltas else None,
        },
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--min-delta", type=float, default=0.05)
    parser.add_argument("--max-delta", type=float, default=45.0)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = inspect(
        args.frames_dir.resolve(),
        args.count,
        (args.width, args.height),
        args.min_delta,
        args.max_delta,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_out:
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
