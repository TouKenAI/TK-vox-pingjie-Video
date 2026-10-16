# `collage-scene.json` contract

Use this file as the deterministic seam between approved creative direction and frame rendering. Paths are relative to the JSON file. Write and validate `shot-plan.json` from `camera-language.md` first; `collage-scene.json` implements that approved geometry and must not invent a different camera position, axis, or subject path.

```json
{
  "canvas": { "width": 1920, "height": 1080 },
  "fps": 30,
  "duration_s": 5,
  "seed": 1912,
  "procedural_frame_offset": 0,
  "background": {
    "path": "assets/source/background.png",
    "scale": 1.03,
    "jitter": [2, 2]
  },
  "grain_opacity": 0.09,
  "png_compress_level": 6,
  "camera_motion": {
    "fill": [11, 22, 51, 255],
    "keyframes": [
      { "frame": 0, "x": 0, "y": 0, "scale": 1.08, "rotation": 0.2, "opacity": 1 },
      { "frame": 149, "x": 0, "y": 0, "scale": 1, "rotation": 0, "opacity": 1, "ease": "ease-in-out" }
    ]
  },
  "wave_bands": [
    {
      "y": 800,
      "amplitude": 15,
      "wavelength": 360,
      "speed": 5,
      "thickness": 320,
      "color": [11, 33, 58, 225],
      "edge_color": [233, 226, 208, 150],
      "edge_width": 4
    }
  ],
  "layers": [
    {
      "id": "hero",
      "path": "assets/source/hero.png",
      "trim_alpha": true,
      "base_width": 1050,
      "anchor": [0.5, 0.75],
      "z": 10,
      "jitter": { "x": 2, "y": 2, "rotation": 0.25, "hold": 1 },
      "shadow": { "blur": 14, "offset": [14, 18], "color": [0, 0, 0, 150] },
      "keyframes": [
        { "frame": 0, "x": 300, "y": 750, "scale": 1, "rotation": 0, "opacity": 1 },
        { "frame": 149, "x": 1450, "y": 750, "scale": 1, "rotation": 0, "opacity": 1, "ease": "ease-in-out" }
      ]
    }
  ],
  "effects": [
    {
      "type": "radial-burst",
      "start_frame": 69,
      "end_frame": 110,
      "origin": [1450, 650],
      "ray_count": 13,
      "max_ray_length": 280
    },
    {
      "type": "debris",
      "source": "assets/source/fragments.png",
      "sprite_boxes": [[20, 20, 400, 220], [450, 30, 650, 390]],
      "start_frame": 69,
      "end_frame": 135,
      "origin": [1450, 650],
      "particle_count": 16,
      "max_delay": 8,
      "vx": [-17, 13],
      "vy": [-20, -6],
      "gravity": 0.58,
      "scale": [0.08, 0.18],
      "fade_after": 32
    }
  ]
}
```

## Keyframe rules

- Use frame numbers, not seconds, inside the compositor plan.
- Include `x`, `y`, `scale`, `rotation`, and `opacity` on every keyframe.
- `x`,`y` describe the layer anchor position on the output canvas.
- `base_width × scale` determines the transformed width.
- Supported eases: `linear`, `ease-in`, `ease-out`, `ease-in-out`, `ease-out-back`(过冲回弹), `ease-out-expo`(急停), `ease-spring`(弹跳).
  ⚠ 本行 V3.26 前只列了前 4 种，与 `render_sequence.py` 实际支持的 7 种不符——**按哪种缓动办事以 `style-presets.md §动画语法` 为准**：8 个风格各有其主导缓动，弹跳过冲在等距2.5D 是禁用项、在白板贴纸是正确用法。
- Keep keyframes monotonic along the dominant physical motion unless the story explicitly reverses direction.
- Use one deterministic seed. Do not call unseeded randomness.
- `procedural_frame_offset` shifts only wave phase, paper jitter, registration jitter, and grain. Use `-N` for a segment immediately before a frozen sequence and `+N` for a segment immediately after it so procedural motion continues across the splice; layer and effect keyframes remain local to the segment.
- `procedural_frame_offset` must never shift `rig_motion`; rigs use the segment-local frame so character motion does not jump when procedural texture phases are continued across a splice.
- `camera_motion` is optional and applies one full-frame transform after layers, effects, and waves but before screen-space grain. Its keyframe `opacity` blends the transformed frame over `camera_motion.fill`: `0` shows only the fill and `1` shows the transformed frame. Keep `scale >= 1` when possible so pans and rotation do not expose the canvas fill. Make the boundary camera keyframe exactly `{x:0,y:0,scale:1,rotation:0,opacity:1}` when splicing into an already accepted frame sequence.
- `wave_bands[].thickness` is the visible distance in pixels between the torn upper and lower edges of a finite band. It does not mean “fill from the wave to the bottom of the canvas.” Use a larger value for a deeper paper strip.

## Sprite-sheet rules

- Generate fragments with actual alpha and wide separation.
- Record explicit crop boxes around individual pieces.
- Keep every crop inside the sheet dimensions.
- Inspect the extracted sprites on a contrasting checkerboard before the final run.
