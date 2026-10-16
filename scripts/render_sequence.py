#!/usr/bin/env python3
"""Render a deterministic, flattened PNG collage sequence from a small JSON plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉


RESAMPLE = Image.Resampling.LANCZOS


def stable_int(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def ease(name: str, t: float) -> float:
    t = max(0.0, min(1.0, t))
    if name == "ease-in":
        return t * t * t
    if name == "ease-out":
        return 1 - (1 - t) ** 3
    if name == "ease-in-out":
        return 4 * t**3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
    if name == "ease-out-expo":
        return 1 - 2 ** (-10 * t) if t < 1 else 1
    if name == "ease-out-back":
        c1, c3 = 1.70158 * 0.7, 1.70158 * 0.7 + 1  # 0.7 系数=轻微过冲(约1.02)
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
    if name == "ease-spring":
        d = 0.3
        return 1 - (1 - t) ** 3 * ((1 - d) * (1 - t) + d) if t < 1 else 1
    return t


def tween(keys: list[dict], frame: int) -> dict:
    if not keys:
        raise ValueError("Every image layer needs at least one keyframe")
    keys = sorted(keys, key=lambda item: item["frame"])
    if frame <= keys[0]["frame"]:
        return dict(keys[0])
    if frame >= keys[-1]["frame"]:
        return dict(keys[-1])
    for left, right in zip(keys, keys[1:]):
        if left["frame"] <= frame <= right["frame"]:
            span = max(1, right["frame"] - left["frame"])
            t = ease(right.get("ease", "linear"), (frame - left["frame"]) / span)
            result: dict = {"frame": frame}
            for field in ("x", "y", "scale", "rotation", "opacity"):
                a = float(left.get(field, right.get(field, 0)))
                b = float(right.get(field, a))
                result[field] = a + (b - a) * t
            # V3.12 挤压拉伸: 端点带 scale_x/scale_y 才插值(缺省→等比, 旧场景不变)
            for field in ("scale_x", "scale_y"):
                if field in left or field in right:
                    a = float(left.get(field, right.get(field, right.get("scale", 1))))
                    b = float(right.get(field, a))
                    result[field] = a + (b - a) * t
            return result
    return dict(keys[-1])


def trim_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    return rgba.crop(bbox) if bbox else rgba


def cover(image: Image.Image, size: tuple[int, int], scale: float = 1.0) -> Image.Image:
    target_w, target_h = size
    factor = max(target_w / image.width, target_h / image.height) * scale
    resized = image.resize((round(image.width * factor), round(image.height * factor)), RESAMPLE)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h)).convert("RGBA")


def _layer_src(layer: dict, layer_sources: dict, seq_sources: dict, frame: int) -> Image.Image:
    """V8.1.8: 数字增长序列层按帧取图(seq_rate 帧换 1 张, 末帧定格); 普通层返回原图"""
    sid = layer["id"]
    if sid in seq_sources:
        frames = seq_sources[sid]
        rate = max(1, int(layer.get("seq_rate", 4)))
        idx = min(len(frames) - 1, frame // rate)
        return frames[idx]
    return layer_sources[sid]


def transformed(image: Image.Image, width: float, scale: float, rotation: float, opacity: float,
                scale_x: float | None = None, scale_y: float | None = None) -> Image.Image:
    # V3.12 挤压拉伸: 传 scale_x/scale_y 走非等比(面积守恒感), 否则等比 scale
    if scale_x is not None or scale_y is not None:
        sx = float(scale_x) if scale_x is not None else float(scale)
        sy = float(scale_y) if scale_y is not None else float(scale)
        out_w = max(1, round(width * sx))
        out_h = max(1, round(image.height * (width / max(1, image.width)) * sy))
        result = image.resize((out_w, out_h), RESAMPLE)
    else:
        out_w = max(1, round(width * scale))
        out_h = max(1, round(image.height * out_w / image.width))
        result = image.resize((out_w, out_h), RESAMPLE)
    if abs(rotation) > 0.001:
        result = result.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True)
    if opacity < 0.999:
        alpha = result.getchannel("A").point(lambda value: round(value * max(0.0, opacity)))
        result.putalpha(alpha)
    return result


def apply_camera(canvas: Image.Image, state: dict, fill: tuple[int, int, int, int]) -> Image.Image:
    """Apply one deterministic full-frame camera transform around canvas center."""
    scale = float(state.get("scale", 1))
    rotation = float(state.get("rotation", 0))
    x = float(state.get("x", 0))
    y = float(state.get("y", 0))
    opacity = max(0.0, min(1.0, float(state.get("opacity", 1))))
    if scale <= 0:
        raise ValueError("camera scale must be positive")
    if abs(scale - 1) < 1e-9 and abs(rotation) < 1e-9 and abs(x) < 1e-9 and abs(y) < 1e-9:
        moved_to_canvas = canvas
    else:
        width, height = canvas.size
        moved = canvas
        if abs(scale - 1) >= 1e-9:
            moved = moved.resize((max(1, round(width * scale)), max(1, round(height * scale))), RESAMPLE)
        if abs(rotation) >= 1e-9:
            moved = moved.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=fill)

        left = round((moved.width - width) / 2 - x)
        top = round((moved.height - height) / 2 - y)
        right = left + width
        bottom = top + height
        if left >= 0 and top >= 0 and right <= moved.width and bottom <= moved.height:
            moved_to_canvas = moved.crop((left, top, right, bottom))
        else:
            moved_to_canvas = Image.new("RGBA", (width, height), fill)
            src_left = max(0, left)
            src_top = max(0, top)
            src_right = min(moved.width, right)
            src_bottom = min(moved.height, bottom)
            if src_right > src_left and src_bottom > src_top:
                piece = moved.crop((src_left, src_top, src_right, src_bottom))
                moved_to_canvas.alpha_composite(piece, (max(0, -left), max(0, -top)))

    if opacity >= 0.999:
        return moved_to_canvas
    return Image.blend(Image.new("RGBA", canvas.size, fill), moved_to_canvas, opacity)


def paste_layer(canvas: Image.Image, layer_image: Image.Image, state: dict, layer: dict) -> None:
    anchor = layer.get("anchor", [0.5, 0.5])
    x = round(state["x"] - layer_image.width * anchor[0])
    y = round(state["y"] - layer_image.height * anchor[1])
    shadow = layer.get("shadow")
    if shadow:
        alpha = layer_image.getchannel("A")
        blur = alpha.filter(ImageFilter.GaussianBlur(float(shadow.get("blur", 10))))
        color = tuple(shadow.get("color", [0, 0, 0, 150]))
        shadow_rgba = Image.new("RGBA", layer_image.size, color)
        shadow_rgba.putalpha(blur.point(lambda value: round(value * color[3] / 255)))
        offset = shadow.get("offset", [12, 16])
        canvas.alpha_composite(shadow_rgba, (x + int(offset[0]), y + int(offset[1])))
    canvas.alpha_composite(layer_image, (x, y))


def draw_wave_bands(canvas: Image.Image, bands: list[dict], frame: int, seed: int) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    width, height = canvas.size
    for index, band in enumerate(bands):
        y0 = float(band["y"])
        amplitude = float(band.get("amplitude", 18))
        wavelength = float(band.get("wavelength", 320))
        speed = float(band.get("speed", 5))
        thickness = max(0.0, float(band.get("thickness", 120)))
        rng = random.Random(seed + index * 1009)
        points = []
        for x in range(-80, width + 121, 40):
            torn = rng.uniform(-7, 7)
            y = y0 + math.sin((x + frame * speed) / wavelength * math.tau) * amplitude + torn
            points.append((x, y))
        lower_points = [(x, y + thickness) for x, y in reversed(points)]
        polygon = points + lower_points
        draw.polygon(polygon, fill=tuple(band.get("color", [11, 33, 58, 225])))
        edge = tuple(band.get("edge_color", [233, 226, 208, 150]))
        draw.line(points, fill=edge, width=int(band.get("edge_width", 4)), joint="curve")


def oscillation(terms: list[dict], frame: int) -> float:
    return sum(
        float(term["amplitude"])
        * math.sin(float(term["frequency"]) * frame + float(term.get("phase", 0)))
        for term in terms
    )


def rig_offset(rig: dict, frame: int) -> tuple[float, float, float]:
    dx = oscillation(rig.get("x_terms", []), frame)
    dy = oscillation(rig.get("y_terms", []), frame)
    rotation = oscillation(rig.get("rotation_terms", []), frame)
    shake = rig.get("shake")
    if shake and int(shake["start_frame"]) <= frame <= int(shake["end_frame"]):
        age = frame - int(shake["start_frame"])
        span = max(1, int(shake["end_frame"]) - int(shake["start_frame"]) + 1)
        decay = max(0.0, 1 - age / span)
        dx += float(shake.get("x_amplitude", 0)) * math.sin(float(shake.get("x_frequency", 2)) * age) * decay
        dy += float(shake.get("y_amplitude", 0)) * math.cos(float(shake.get("y_frequency", 2)) * age) * decay
        rotation += (
            float(shake.get("rotation_amplitude", 0))
            * math.sin(float(shake.get("rotation_frequency", 2)) * age)
            * decay
        )
    return dx, dy, rotation


def draw_burst(canvas: Image.Image, effect: dict, frame: int, seed: int) -> None:
    start = int(effect["start_frame"])
    end = int(effect["end_frame"])
    if frame < start or frame > end:
        return
    age = frame - start
    origin = effect["origin"]
    rng = random.Random(seed + stable_int("burst"))
    draw = ImageDraw.Draw(canvas, "RGBA")
    count = int(effect.get("ray_count", 13))
    for index in range(count):
        angle = rng.uniform(-2.6, 1.25)
        delay = rng.randint(0, 8)
        local_age = max(0, age - delay)
        length = min(float(effect.get("max_ray_length", 280)), local_age * rng.uniform(9, 17))
        if length <= 0:
            continue
        x1 = origin[0] + math.cos(angle) * 24
        y1 = origin[1] + math.sin(angle) * 24
        x2 = origin[0] + math.cos(angle) * length
        y2 = origin[1] + math.sin(angle) * length
        alpha = max(0, 210 - age * 4)
        # color 字段此前被忽略(硬编码砖红), 深色底的片子等于爆了个看不见的烟花。
        # 默认值保持原样 → 旧场景逐字节不变。
        col = tuple(effect.get("color", (163, 59, 52))[:3]) + (alpha,)
        draw.line((x1, y1, x2, y2), fill=col, width=rng.randint(4, 12))


def make_sprite(sheet: Image.Image, box: list[int]) -> Image.Image:
    return trim_alpha(sheet.crop(tuple(int(v) for v in box)))


def draw_debris(
    canvas: Image.Image,
    effect: dict,
    frame: int,
    seed: int,
    sprite_cache: dict[str, list[Image.Image]],
    base_dir: Path,
) -> None:
    start = int(effect["start_frame"])
    end = int(effect["end_frame"])
    if frame < start or frame > end:
        return
    source = str((base_dir / effect["source"]).resolve())
    if source not in sprite_cache:
        sheet = Image.open(source).convert("RGBA")
        sprite_cache[source] = [make_sprite(sheet, box) for box in effect["sprite_boxes"]]
    sprites = sprite_cache[source]
    origin_x, origin_y = effect["origin"]
    for index in range(int(effect.get("particle_count", len(sprites)))):
        rng = random.Random(seed + stable_int(f"particle-{index}"))
        delay = rng.randint(0, int(effect.get("max_delay", 8)))
        age = frame - start - delay
        if age < 0:
            continue
        sprite = sprites[index % len(sprites)]
        vx = rng.uniform(*effect.get("vx", [-15, 15]))
        vy = rng.uniform(*effect.get("vy", [-19, -5]))
        gravity = float(effect.get("gravity", 0.55))
        x = origin_x + vx * age
        y = origin_y + vy * age + 0.5 * gravity * age * age
        scale = rng.uniform(*effect.get("scale", [0.08, 0.19]))
        rotation = rng.uniform(-30, 30) + age * rng.uniform(-8, 8)
        opacity = max(0.0, 1 - max(0, age - int(effect.get("fade_after", 30))) / 24)
        piece = transformed(sprite, sprite.width, scale, rotation, opacity)
        canvas.alpha_composite(piece, (round(x - piece.width / 2), round(y - piece.height / 2)))


def add_grain(canvas: Image.Image, frame: int, seed: int, opacity: float) -> Image.Image:
    if opacity <= 0:
        return canvas
    small_w = max(32, canvas.width // 8)
    small_h = max(18, canvas.height // 8)
    rng = random.Random(seed + frame * 7919)
    noise = Image.frombytes("L", (small_w, small_h), rng.randbytes(small_w * small_h))
    noise = noise.resize(canvas.size, Image.Resampling.BILINEAR)
    tint = Image.new("RGBA", canvas.size, (233, 226, 208, 0))
    tint.putalpha(noise.point(lambda value: round(abs(value - 128) * opacity)))
    return Image.alpha_composite(canvas, tint)


def render(plan_path: Path, output_dir: Path, overwrite: bool, step: int = 1, out_scale: float = 1.0) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base_dir = plan_path.parent
    width = int(plan["canvas"]["width"])
    height = int(plan["canvas"]["height"])
    fps = int(plan["fps"])
    duration = float(plan["duration_s"])
    frame_count = round(fps * duration)
    if frame_count <= 0:
        raise ValueError("fps * duration_s must be positive")
    existing = sorted(output_dir.glob("frame_*.png")) if output_dir.exists() else []
    if existing and not overwrite:
        raise FileExistsError(f"{output_dir} already contains {len(existing)} frames; pass --overwrite")
    output_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for path in existing:
            path.unlink()

    seed = int(plan.get("seed", 1))
    procedural_frame_offset = int(plan.get("procedural_frame_offset", 0))
    background = Image.open(base_dir / plan["background"]["path"]).convert("RGB")
    background = cover(background, (width, height), float(plan["background"].get("scale", 1.0)))
    layer_sources = {}
    seq_sources: dict[str, list[Image.Image]] = {}
    for layer in plan.get("layers", []):
        if layer.get("seq_dir"):  # V8.1.8 数字增长序列层: 目录内按文件名序加载全部帧
            seq_path = base_dir / layer["seq_dir"]
            if not seq_path.exists():
                raise FileNotFoundError(f"[V8.1.8] seq_dir 不存在: {seq_path}")
            seq_sources[layer["id"]] = [
                trim_alpha(Image.open(p).convert("RGBA")) if layer.get("trim_alpha", True)
                else Image.open(p).convert("RGBA")
                for p in sorted(seq_path.glob("*.png"))
            ]
            if not seq_sources[layer["id"]]:
                raise FileNotFoundError(f"[V8.1.8] seq_dir 无 PNG: {seq_path}")
            continue
        image = Image.open(base_dir / layer["path"]).convert("RGBA")
        if layer.get("crop"):
            image = image.crop(tuple(int(value) for value in layer["crop"]))
        layer_sources[layer["id"]] = trim_alpha(image) if layer.get("trim_alpha", True) else image
    sprite_cache: dict[str, list[Image.Image]] = {}
    rig = plan.get("rig_motion", {})
    rig_ids = set(rig.get("ids", []))

    out_idx = 0
    for frame in range(frame_count):
        if step > 1 and frame % step != 0:
            continue
        procedural_frame = frame + procedural_frame_offset
        canvas = background.copy()
        bg_jitter = plan.get("background", {}).get("jitter", [0, 0])
        if bg_jitter != [0, 0]:
            rng = random.Random(seed + stable_int("background") + procedural_frame)
            xj = round(rng.uniform(-bg_jitter[0], bg_jitter[0]))
            yj = round(rng.uniform(-bg_jitter[1], bg_jitter[1]))
            canvas = Image.new("RGBA", (width, height), (11, 22, 51, 255))
            canvas.alpha_composite(background, (xj, yj))

        wave_bands = plan.get("wave_bands", [])
        draw_wave_bands(
            canvas,
            [band for band in wave_bands if band.get("stage") != "front"],
            procedural_frame,
            seed,
        )

        # V3.12 视差(仅 opt-in): 背景定版为背景层, 图层/特效/前波带画到透明前景层, 末尾两平面分别位移。
        # 无视差时 canvas 仍是"背景+图层"合并图, 走原单相机路径 → 旧场景逐字节不变。
        par = plan.get("parallax")
        if par:
            bg_plane = canvas
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        rig_dx, rig_dy, rig_rotation = rig_offset(rig, frame)

        # V300: container_drift — 场景级线性漂移,与图层动画独立(video-shotcraft list-reveal 卡)
        drift = plan.get("container_drift", {})
        drift_x = 0.0
        drift_y = 0.0
        if drift:
            total = plan.get("canvas", {}).get("width", 1080)  # 用帧数更好,但近似即可
            fr_total = plan.get("duration_s", 10) * 30
            t = min(1.0, frame / max(1, fr_total))
            dx = drift.get("x", [0, 0])
            dy = drift.get("y", [0, 0])
            drift_x = dx[0] + (dx[1] - dx[0]) * t
            drift_y = dy[0] + (dy[1] - dy[0]) * t

        for layer in sorted(plan.get("layers", []), key=lambda item: item.get("z", 0)):
            state = tween(layer["keyframes"], frame)
            if layer["id"] in rig_ids:
                state["x"] += rig_dx
                state["y"] += rig_dy
                state["rotation"] += rig_rotation
            if drift and not layer["id"].startswith(("cover", "echo")):
                state["x"] += drift_x
                state["y"] += drift_y
            jitter = layer.get("jitter", {})
            hold = max(1, int(jitter.get("hold", 1)))
            rng = random.Random(seed + stable_int(layer["id"]) + procedural_frame // hold)
            state["x"] += rng.uniform(-float(jitter.get("x", 0)), float(jitter.get("x", 0)))
            state["y"] += rng.uniform(-float(jitter.get("y", 0)), float(jitter.get("y", 0)))
            state["rotation"] += rng.uniform(
                -float(jitter.get("rotation", 0)), float(jitter.get("rotation", 0))
            )
            src = _layer_src(layer, layer_sources, seq_sources, procedural_frame)
            image = transformed(
                src,
                float(layer["base_width"]),
                float(state.get("scale", 1)),
                float(state.get("rotation", 0)),
                float(state.get("opacity", 1)),
                state.get("scale_x"),
                state.get("scale_y"),
            )
            # V3.12 运动模糊: 快速移动层按帧间速度方向做时间拖影(确定性)
            mb = layer.get("motion_blur")
            if mb and frame > 0:
                prev = tween(layer["keyframes"], frame - 1)
                vx = state["x"] - float(prev.get("x", state["x"]))
                vy = state["y"] - float(prev.get("y", state["y"]))
                speed = math.hypot(vx, vy)
                thr = float(mb.get("min_speed", 26))
                if speed > thr:
                    sub = int(mb.get("samples", 3))
                    for i in range(1, sub + 1):
                        frac = i / (sub + 1)
                        ghost = dict(state)
                        ghost["x"] = state["x"] - vx * frac
                        ghost["y"] = state["y"] - vy * frac
                        ghost_img = transformed(
                            src, float(layer["base_width"]), float(state.get("scale", 1)),
                            float(state.get("rotation", 0)),
                            float(state.get("opacity", 1)) * (0.32 / sub),
                            state.get("scale_x"), state.get("scale_y"))
                        paste_layer(canvas, ghost_img, ghost, layer)
            paste_layer(canvas, image, state, layer)

        for effect in plan.get("effects", []):
            runtime_effect = effect
            if effect.get("follow_rig", True) and effect.get("origin"):
                runtime_effect = dict(effect)
                runtime_effect["origin"] = [effect["origin"][0] + rig_dx, effect["origin"][1] + rig_dy]
            if effect["type"] == "radial-burst":
                draw_burst(canvas, runtime_effect, frame, seed)
            elif effect["type"] == "debris":
                draw_debris(canvas, runtime_effect, frame, seed, sprite_cache, base_dir)

        draw_wave_bands(
            canvas,
            [band for band in wave_bands if band.get("stage") == "front"],
            procedural_frame,
            seed,
        )

        camera = plan.get("camera_motion")
        if camera and par:
            # V3.12 视差: 背景与前景按 depth 施加不同相机位移(远慢近快), 各自变换后合成
            camera_state = tween(camera["keyframes"], frame)
            fill = tuple(camera.get("fill", [11, 22, 51, 255]))
            cx = float(camera_state.get("x", 0)); cy = float(camera_state.get("y", 0))
            bgd = float(par.get("bg_depth", 0.5)); fgd = float(par.get("fg_depth", 1.0))
            bg_st = dict(camera_state); bg_st["x"] = cx * bgd; bg_st["y"] = cy * bgd
            fg_st = dict(camera_state); fg_st["x"] = cx * fgd; fg_st["y"] = cy * fgd
            out = apply_camera(bg_plane, bg_st, fill)
            fg_t = apply_camera(canvas, fg_st, (0, 0, 0, 0))
            out.alpha_composite(fg_t)
            canvas = out
        elif camera:
            camera_state = tween(camera["keyframes"], frame)
            fill = tuple(camera.get("fill", [11, 22, 51, 255]))
            canvas = apply_camera(canvas, camera_state, fill)
        elif par:
            # V3.26 补第三条: 旧版只有 `camera and par` 与 `elif camera`, 于是
            # **有 parallax 但没 camera_motion** 时两条都不进 → 上面腾空的 bg_plane 被整个丢弃,
            # 图层画在透明底上 → 该场渲成全黑/全透明, 且全程零报错。现在按"无视差合成"补回。
            merged = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            merged.alpha_composite(bg_plane)
            merged.alpha_composite(canvas)
            canvas = merged

        canvas = add_grain(
            canvas,
            procedural_frame,
            seed,
            float(plan.get("grain_opacity", 0.10)),
        )
        out_img = canvas.convert("RGB")
        if out_scale and out_scale != 1.0:
            out_img = out_img.resize(
                (max(1, round(width * out_scale)), max(1, round(height * out_scale))), RESAMPLE)
        out_img.save(
            output_dir / f"frame_{out_idx + 1:04d}.png",
            format="PNG",
            compress_level=int(plan.get("png_compress_level", 6)),
        )
        out_idx += 1

    print(f"rendered {out_idx} frames (step={step}, scale={out_scale}) to {output_dir}")

    # V3.24 帧↔JSON 一致性戳**由产出帧的这一方写**, 不能只由 render_all 写。
    # p16 实录: 改完 3 场构图后直接调 render_sequence 单场重渲, 戳里还是旧 JSON 的哈希,
    # produce --skip-render 正确地拒用旧帧 —— 门没错, 错的是"只有某条调用路径才盖章"。
    # 预览渲染(--step/--scale)不配当成品戳: 它渲的不是完整帧集, 盖了戳等于给旧 JSON 发通行证。
    if step == 1 and abs(out_scale - 1.0) < 1e-9:
        try:
            from scene_fingerprint import write_stamps
            write_stamps(plan_path, output_dir)      # .hash(旧) + .fp(含资产/渲染器)
        except OSError:
            pass
        except ImportError as e:                     # 缺模块=戳写不上，宁可响，不能静默少盖一章
            print(f"[WARN] 帧戳未写（scene_fingerprint 不可用: {e!r}）—— produce --skip-render 会拒用这批帧")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path, help="Path to collage-scene.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--step", type=int, default=1, help="每 N 帧渲一张(animatic 提速), 默认1=全帧")
    parser.add_argument("--scale", type=float, default=1.0, help="输出降采样比例(预览用), 默认1.0")
    args = parser.parse_args()
    render(args.plan.resolve(), args.output.resolve(), args.overwrite,
           step=max(1, args.step), out_scale=args.scale)


if __name__ == "__main__":
    main()
