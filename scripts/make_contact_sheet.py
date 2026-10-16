#!/usr/bin/env python3
"""Create a labeled contact sheet from selected frame numbers."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("--frames", required=True, help="Comma-separated one-based frame numbers")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--thumb-width", type=int, default=640)
    args = parser.parse_args()

    numbers = [int(value.strip()) for value in args.frames.split(",") if value.strip()]
    images = []
    for number in numbers:
        path = args.frames_dir / f"frame_{number:04d}.png"
        image = Image.open(path).convert("RGB")
        thumb_h = round(image.height * args.thumb_width / image.width)
        images.append((number, image.resize((args.thumb_width, thumb_h), Image.Resampling.LANCZOS)))
    if not images:
        raise ValueError("No frames selected")

    label_h = 52
    cell_h = images[0][1].height + label_h
    rows = (len(images) + args.columns - 1) // args.columns
    sheet = Image.new("RGB", (args.columns * args.thumb_width, rows * cell_h), "#0B1633")
    draw = ImageDraw.Draw(sheet)
    label_font = font(28)
    for index, (number, image) in enumerate(images):
        col = index % args.columns
        row = index // args.columns
        x = col * args.thumb_width
        y = row * cell_h
        sheet.paste(image, (x, y))
        draw.rectangle((x, y + image.height, x + args.thumb_width, y + cell_h), fill="#E9E2D0")
        draw.text((x + 18, y + image.height + 10), f"FRAME {number:04d}", font=label_font, fill="#1B1716")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)
    print(f"wrote {args.output} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
