#!/usr/bin/env python3
"""Build a minimal HyperFrames composition that displays one PNG per frame."""

from __future__ import annotations

import argparse
import html
from pathlib import Path

from PIL import Image


def build(frames_dir: Path, output: Path, fps: int, composition_id: str) -> None:
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise FileNotFoundError(f"No frame_*.png files in {frames_dir}")
    first = Image.open(frames[0])
    width, height = first.size
    expected = [f"frame_{index:04d}.png" for index in range(1, len(frames) + 1)]
    actual = [path.name for path in frames]
    if actual != expected:
        raise ValueError("Frame names must be contiguous from frame_0001.png")
    duration = len(frames) / fps
    rel_base = Path(".") / Path(frames_dir.relative_to(output.parent))
    tags = []
    for index, path in enumerate(frames):
        src = html.escape((rel_base / path.name).as_posix())
        initial = " frame--active" if index == 0 else ""
        tags.append(
            "      <img "
            f'id="collage-frame-{index + 1:04d}" class="frame{initial}" src="{src}" '
            'loading="eager" decoding="sync" alt="" />'
        )
    switches = []
    for index in range(1, len(frames)):
        start = index / fps
        switches.append(
            f'      tl.set("#collage-frame-{index:04d}", '
            f'{{ autoAlpha: 0 }}, {start:.10f});'
        )
        switches.append(
            f'      tl.set("#collage-frame-{index + 1:04d}", '
            f'{{ autoAlpha: 1 }}, {start:.10f});'
        )
    document = f"""<!doctype html>
<html lang="en" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <title>Frame-by-frame collage sequence</title>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: #0b1633; }}
      #root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
      .stage-fill {{ position: absolute; inset: 0; background: #0b1633; }}
      #sequence {{ position: absolute; inset: 0; }}
      .frame {{ position: absolute; inset: 0; width: {width}px; height: {height}px; object-fit: cover; opacity: 0; visibility: hidden; }}
      .frame--active {{ opacity: 1; visibility: visible; }}
      #seek-sentinel {{ position: absolute; left: 0; top: 0; width: 1px; height: 1px; background: transparent; opacity: 0.21; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="{html.escape(composition_id)}" data-start="0" data-width="{width}" data-height="{height}" data-duration="{duration:.10f}" data-fps="{fps}">
      <div class="stage-fill"></div>
      <div id="sequence" class="clip" data-start="0" data-duration="{duration:.10f}" data-track-index="1">
{chr(10).join(tags)}
        <span id="seek-sentinel" aria-hidden="true"></span>
      </div>
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
{chr(10).join(switches)}
      // HyperFrames' layout sweep cannot fingerprint pixel-only <img> replacements.
      // This unpainted span supplies a seek witness without changing rendered pixels.
      tl.fromTo("#seek-sentinel", {{ x: 0, opacity: 0.21 }}, {{ x: 100, opacity: 0.29, duration: {duration:.10f}, ease: "none" }}, 0);
      window.__timelines["{html.escape(composition_id)}"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
    output.write_text(document, encoding="utf-8")
    print(f"wrote {output} with {len(frames)} preloaded PNGs and hard frame switches at {fps} fps")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--composition-id", default="collage-main")
    args = parser.parse_args()
    build(args.frames_dir.resolve(), args.output.resolve(), args.fps, args.composition_id)


if __name__ == "__main__":
    main()
