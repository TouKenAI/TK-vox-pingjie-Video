#!/usr/bin/env python3
"""Validate shot geometry, blocking richness, and projected movement before rendering."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


REQUIRED_FRAMING = {"size", "angle", "camera_position", "camera_facing", "lens_behavior"}
REQUIRED_SPACE = {"environment_axis", "vanishing_point", "screen_direction"}
VALID_ROLES = {"primary", "secondary", "tertiary"}
VALID_CONSTRAINTS = {"along-environment-axis", "stationary", "free"}


def point(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, (int, float)) for item in value)
    )


def vector(a: list[float], b: list[float]) -> tuple[float, float]:
    return float(b[0] - a[0]), float(b[1] - a[1])


def magnitude(value: tuple[float, float]) -> float:
    return math.hypot(value[0], value[1])


def alignment(a: tuple[float, float], b: tuple[float, float]) -> float:
    denom = magnitude(a) * magnitude(b)
    if denom == 0:
        return 1.0
    return abs((a[0] * b[0] + a[1] * b[1]) / denom)


def validate(plan: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    canvas = plan.get("canvas", {})
    width = canvas.get("width")
    height = canvas.get("height")
    fps = plan.get("fps")
    frame_count = plan.get("frame_count")
    shots = plan.get("shots")
    if not isinstance(width, int) or width <= 0 or not isinstance(height, int) or height <= 0:
        errors.append("canvas.width and canvas.height must be positive integers")
    if not isinstance(fps, (int, float)) or fps <= 0:
        errors.append("fps must be positive")
    if not isinstance(frame_count, int) or frame_count <= 0:
        errors.append("frame_count must be a positive integer")
    if not isinstance(shots, list) or not shots:
        errors.append("shots must be a non-empty list")
        shots = []

    expected_start = 1
    for shot_index, shot in enumerate(shots, start=1):
        label = str(shot.get("id", f"shot-{shot_index}"))
        frames = shot.get("frames")
        if not (
            isinstance(frames, list)
            and len(frames) == 2
            and all(isinstance(item, int) for item in frames)
            and frames[0] <= frames[1]
        ):
            errors.append(f"{label}: frames must be [start, end] integers")
            continue
        if frames[0] != expected_start:
            errors.append(f"{label}: expected start frame {expected_start}, found {frames[0]}")
        expected_start = frames[1] + 1

        framing = shot.get("framing")
        if not isinstance(framing, dict):
            errors.append(f"{label}: framing object is required")
        else:
            missing = sorted(REQUIRED_FRAMING - set(framing))
            if missing:
                errors.append(f"{label}: framing missing {', '.join(missing)}")

        space = shot.get("space")
        if not isinstance(space, dict):
            errors.append(f"{label}: space object is required")
            continue
        missing = sorted(REQUIRED_SPACE - set(space))
        if missing:
            errors.append(f"{label}: space missing {', '.join(missing)}")
        axis = space.get("environment_axis")
        if not (isinstance(axis, list) and len(axis) == 2 and point(axis[0]) and point(axis[1])):
            errors.append(f"{label}: environment_axis must be [[near_x,near_y],[far_x,far_y]]")
            axis_vector = (0.0, 0.0)
        else:
            axis_vector = vector(axis[0], axis[1])
            if magnitude(axis_vector) < 20:
                errors.append(f"{label}: environment_axis is too short to define perspective")
        vanishing = space.get("vanishing_point")
        if not point(vanishing):
            errors.append(f"{label}: vanishing_point must be [x,y]")

        camera_position = framing.get("camera_position", "") if isinstance(framing, dict) else ""
        if "behind" in str(camera_position).lower() or "后" in str(camera_position):
            if not space.get("foreground_anchor"):
                errors.append(f"{label}: rear-observer framing requires space.foreground_anchor")
            if not space.get("eyeline_target"):
                errors.append(f"{label}: rear-observer framing requires space.eyeline_target")

        blocking = shot.get("blocking")
        if not isinstance(blocking, list) or not blocking:
            errors.append(f"{label}: blocking must contain at least one subject/action")
            blocking = []
        roles: set[str] = set()
        for item_index, item in enumerate(blocking, start=1):
            item_label = f"{label}/blocking-{item_index}"
            role = item.get("role")
            if role not in VALID_ROLES:
                errors.append(f"{item_label}: role must be primary, secondary, or tertiary")
            else:
                roles.add(role)
            if not item.get("action"):
                errors.append(f"{item_label}: action is required")
            constraint = item.get("movement_constraint")
            if constraint not in VALID_CONSTRAINTS:
                errors.append(f"{item_label}: invalid movement_constraint")
            path = item.get("path")
            if not (
                isinstance(path, list)
                and len(path) >= 2
                and all(isinstance(key, list) and len(key) == 4 for key in path)
            ):
                errors.append(f"{item_label}: path needs at least two [frame,x,y,scale] keys")
                continue
            start, end = path[0], path[-1]
            if not all(isinstance(value, (int, float)) for key in path for value in key):
                errors.append(f"{item_label}: path values must be numeric")
                continue
            if start[0] < frames[0] or end[0] > frames[1]:
                errors.append(f"{item_label}: path frames must stay within shot frames")
            motion = vector(start[1:3], end[1:3])
            if constraint == "along-environment-axis" and alignment(motion, axis_vector) < 0.65:
                errors.append(
                    f"{item_label}: path is not aligned with the projected environment axis "
                    f"(alignment={alignment(motion, axis_vector):.3f})"
                )
            if constraint == "stationary" and magnitude(motion) > 120:
                errors.append(f"{item_label}: stationary action travels {magnitude(motion):.1f}px")
            if constraint == "along-environment-axis" and point(vanishing):
                start_distance = math.dist(start[1:3], vanishing)
                end_distance = math.dist(end[1:3], vanishing)
                start_scale = float(start[3])
                end_scale = float(end[3])
                if end_distance < start_distance - 10 and end_scale >= start_scale:
                    errors.append(f"{item_label}: movement toward vanishing point must reduce scale")
                if end_distance > start_distance + 10 and end_scale <= start_scale:
                    errors.append(f"{item_label}: movement toward camera must increase scale")

        if shot.get("multi_character_scene") and not VALID_ROLES.issubset(roles):
            missing_roles = sorted(VALID_ROLES - roles)
            errors.append(f"{label}: multi-character scene missing action roles {', '.join(missing_roles)}")

        handoff = shot.get("handoff")
        if not isinstance(handoff, dict):
            errors.append(f"{label}: handoff object is required")
        else:
            for field in ("type", "anchor", "motion_vector"):
                if field not in handoff:
                    errors.append(f"{label}: handoff missing {field}")
            if "motion_vector" in handoff and not point(handoff["motion_vector"]):
                errors.append(f"{label}: handoff.motion_vector must be [dx,dy]")

    if isinstance(frame_count, int) and shots and expected_start - 1 != frame_count:
        errors.append(f"shots end at frame {expected_start - 1}, expected frame_count {frame_count}")

    return {
        "ok": not errors,
        "shot_count": len(shots),
        "frame_count": frame_count,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = validate(plan)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
