#!/usr/bin/env python3
"""Pixel-level regression tests for collage-scene renderer semantics."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from render_sequence import apply_camera, draw_wave_bands, render


class RenderSequenceSemanticsTest(unittest.TestCase):
    def test_camera_opacity_blends_against_fill(self) -> None:
        canvas = Image.new("RGBA", (160, 90), (220, 120, 40, 255))
        fill = (10, 20, 30, 255)
        hidden = apply_camera(
            canvas, {"x": 4, "y": 0, "scale": 1.1, "rotation": 0, "opacity": 0}, fill
        )
        visible = apply_camera(
            canvas, {"x": 4, "y": 0, "scale": 1.1, "rotation": 0, "opacity": 1}, fill
        )
        self.assertEqual(hidden.tobytes(), Image.new("RGBA", canvas.size, fill).tobytes())
        self.assertNotEqual(hidden.tobytes(), visible.tobytes())

    def test_wave_band_thickness_changes_visible_area(self) -> None:
        common = {
            "y": 45,
            "amplitude": 7,
            "wavelength": 90,
            "speed": 3,
            "color": [20, 60, 160, 255],
            "edge_color": [20, 60, 160, 255],
        }
        thin = Image.new("RGBA", (200, 140), (255, 255, 255, 255))
        thick = thin.copy()
        draw_wave_bands(thin, [common | {"thickness": 12}], frame=5, seed=9)
        draw_wave_bands(thick, [common | {"thickness": 52}], frame=5, seed=9)
        ink = lambda image: sum(1 for pixel in image.getdata() if pixel[:3] == (20, 60, 160))
        self.assertGreater(ink(thick), ink(thin) * 2)

    def test_procedural_offset_does_not_shift_rig_motion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new("RGB", (160, 90), (240, 230, 210)).save(root / "background.png")
            Image.new("RGBA", (20, 20), (180, 30, 30, 255)).save(root / "actor.png")
            plan = {
                "canvas": {"width": 160, "height": 90},
                "fps": 30,
                "duration_s": 1 / 30,
                "seed": 7,
                "procedural_frame_offset": 0,
                "background": {"path": "background.png", "scale": 1, "jitter": [0, 0]},
                "grain_opacity": 0,
                "rig_motion": {
                    "ids": ["actor"],
                    "x_terms": [{"amplitude": 20, "frequency": 0.2}],
                },
                "layers": [{
                    "id": "actor",
                    "path": "actor.png",
                    "base_width": 20,
                    "anchor": [0.5, 0.5],
                    "keyframes": [{
                        "frame": 0, "x": 80, "y": 45, "scale": 1, "rotation": 0, "opacity": 1
                    }],
                }],
            }
            first_plan = root / "first.json"
            second_plan = root / "second.json"
            first_plan.write_text(json.dumps(plan), encoding="utf-8")
            shifted = copy.deepcopy(plan)
            shifted["procedural_frame_offset"] = 100
            second_plan.write_text(json.dumps(shifted), encoding="utf-8")
            render(first_plan, root / "first", overwrite=False)
            render(second_plan, root / "second", overwrite=False)
            self.assertEqual(
                (root / "first/frame_0001.png").read_bytes(),
                (root / "second/frame_0001.png").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
