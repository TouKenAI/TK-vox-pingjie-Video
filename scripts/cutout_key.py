#!/usr/bin/env python3
"""把纯色背景的生图抠成透明剪纸 RGBA(依赖 Pillow + numpy)。

用法:
  py -3.14 tools/cutout_key.py dryrun/raw_ship.png --out dryrun/ship.png

流程:边框中位色自动采样键色 → Chebyshev 距离双阈值映射 alpha →
可选去染(--despill,剔除键色同族的暗红投影/彩边)→ bbox 裁剪 →
输出棋盘检查图供目检。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

DEFAULT_KEY = (255, 0, 255)


def sample_border_key(rgb: np.ndarray, band: int = 12) -> tuple[int, int, int]:
    ring = np.concatenate(
        [rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3), rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)]
    )
    median = np.median(ring, axis=0)
    return tuple(int(round(v)) for v in median)


def make_checker(size: tuple[int, int], cell: int = 24) -> Image.Image:
    yy, xx = np.mgrid[0 : size[1], 0 : size[0]]
    mask = ((xx // cell + yy // cell) % 2 == 0).astype(np.uint8) * 40 + 70
    board = np.stack([mask, mask, mask], axis=-1)
    return Image.fromarray(board, "RGB")


def hsv_bg_alpha(rgb: np.ndarray) -> np.ndarray:
    """V3.16 HSV 色相带抠图(playbook §51①)。
    键色法在"红主体 + 粉洋红底"上天然失效: StepFun 常把 #FF00FF 画成 (200,60,140),
    红主体 (230,90,85) 与键色欧氏距离仅 ≈82,正落在 t0-t1 过渡带 → 主体被吃成半透明;
    --despill 更糟(其 crimson_family 判据会把红主体整块删成空洞)。
    本模式按色相判背景(PIL HSV 中 H 0-255 对应 0-360°): 洋红/粉紫族一律透明,
    红(≈0-10°)/蓝/青/黄主体完整保留。"""
    from PIL import ImageFilter
    hsv = np.asarray(Image.fromarray(rgb.astype(np.uint8)).convert("HSV")).astype(np.int32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    magenta = (h >= 195) & (h <= 248) & (s > 64)                 # 275°-350° 高饱和: 洋红/粉底
    dark_pink = (h >= 212) & (s >= 38) & (s <= 64) & (v < 191)    # 粉底投影/暗角(低饱和偏紫)
    alpha = np.where(magenta | dark_pink, 0, 255).astype(np.uint8)
    img = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.0))
    return np.asarray(img).astype(np.int32)


def key_out(raw_path: Path, out_path: Path, check_path: Path, key_arg: tuple[int, int, int] | None,
            t0: int, t1: int, despill: bool, mode: str = "key") -> dict:
    image = Image.open(raw_path).convert("RGB")
    rgb = np.asarray(image).astype(np.int32)
    key = key_arg if key_arg else sample_border_key(rgb)

    distance = np.max(np.abs(rgb - np.array(key)), axis=-1)
    span = max(1, t1 - t0)
    alpha = np.clip((distance - t0) * 255 / span, 0, 255)
    if mode == "hsv":
        alpha = hsv_bg_alpha(rgb)

    if despill:
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        crimson_family = (r > g * 1.35) & (r > b * 1.15) & (b >= g * 0.85)
        alpha[crimson_family] = 0

    rgba = np.dstack([rgb.astype(np.uint8), alpha.astype(np.uint8)])
    ys, xs = np.nonzero(rgba[..., 3] > 8)
    if len(ys):
        top, bottom = int(ys.min()), int(ys.max()) + 1
        left, right = int(xs.min()), int(xs.max()) + 1
        rgba = rgba[top:bottom, left:right]

    if not len(ys):
        # V3.26: 旧版在这种情况下照样存盘 —— 产出一张 100% 全透明的"素材", 退出码 0,
        # 直到渲出来才发现场上少个主体。键色/色相带判错应当场报错, 不是写一张空图。
        raise SystemExit("[FAIL] 抠完一个不透明像素都没有(整张透明) —— 键色或 HSV 色相带判错了, 拒绝写空图")

    out_image = Image.fromarray(rgba, "RGBA")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # V3.26: 抠图是整条素材链里唯一**不可逆**的一步 —— 覆写会把上一版好图永久毁掉。
    # gen_assets / bg_luma_check 都会先把旧图挪进 qa/prev_assets/, 此前只有这个脚本没有。
    if out_path.exists() and out_path.stat().st_size > 0:
        _self = out_path.resolve()
        _proj = next((p for p in [_self] + list(_self.parents) if (p / "assets").is_dir()), _self.parent)
        bak = _proj / "qa" / "prev_assets"
        bak.mkdir(parents=True, exist_ok=True)
        dst = bak / (_self.stem + ".pre-cut" + _self.suffix)
        _k = 2
        while dst.exists():                       # p16 实录过 FileExistsError, 撞名就加序号
            dst = bak / (_self.stem + f".pre-cut{_k}" + _self.suffix)
            _k += 1
        _self.rename(dst)
        print(f"  旧图已备份 → {dst}")
    out_image.save(out_path)

    check = make_checker(out_image.size)
    check.paste(out_image, (0, 0), out_image)
    check.save(check_path)

    total = float(distance.size)
    return {
        "out": str(out_path),
        "mode": mode,
        "key": list(key),
        "size": list(out_image.size),
        "transparent_ratio": round(float((alpha == 0).sum()) / total, 4),
        "opaque_ratio": round(float((alpha >= 250).sum()) / total, 4),
        "semi_edge_ratio": round(float(((alpha > 0) & (alpha < 250)).sum()) / total, 4),
        "despill": despill,
    }


def measure(raw_path: Path, palette: list[tuple[int, int, int]] | None = None,
            t0: int = 45, t1: int = 95) -> dict:
    """V3.34 选模式前的**证据表**（只读，不写盘）。

    p23 为选 key/hsv/despill 手工量了三轮（边缘带洋红数、体内粉染数、半透明带占比）。
    这里一次给全。⚠ **本工具不替你选模式**：标定过——"体内/残留洋红族像素"这一个数，
    在 prop_awning 上是键色法的粉残留（该用 hsv），在 prop_blinds 上是百叶自己的粉叶片
    （用了 hsv 就把主体抠穿）。同一个数字在两件道具上含义相反，任何自动阈值都会误伤，
    所以只给证据，决定在人（看 _check.png 棋盘图）。
    """
    rgb = np.asarray(Image.open(raw_path).convert("RGB")).astype(np.int32)
    band = 12
    border = np.concatenate([rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                             rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)])
    hb = np.asarray(Image.fromarray(border.astype(np.uint8)).convert("HSV")).astype(np.int32)
    edge_magenta = int(((hb[..., 0] >= 195) & (hb[..., 0] <= 248) & (hb[..., 1] > 64)).sum())
    key = sample_border_key(rgb)
    dist = np.max(np.abs(rgb - np.array(key)), axis=-1)
    a_key = np.clip((dist - t0) * 255 / max(1, t1 - t0), 0, 255)
    a_hsv = hsv_bg_alpha(rgb)
    hsv = np.asarray(Image.fromarray(rgb.astype(np.uint8)).convert("HSV")).astype(np.int32)
    mg = (hsv[..., 0] >= 195) & (hsv[..., 0] <= 248) & (hsv[..., 1] > 64)
    conflicts = []
    for c in (palette or []):
        h = np.asarray(Image.fromarray(np.uint8([[list(c)]]).reshape(1, 1, 3)).convert("HSV")).astype(np.int32)[0, 0]
        if 195 <= h[0] <= 248 and h[1] > 64:
            conflicts.append(list(c))
    return {
        "raw": str(raw_path),
        "border_key": list(key),
        "edge_magenta_px": edge_magenta,
        "edge_magenta_ratio": round(edge_magenta / max(1, border.shape[0]), 3),
        "key_opaque": round(float((a_key >= 250).mean()), 4),
        "key_semi_edge": round(float(((a_key > 0) & (a_key < 250)).mean()), 4),
        "key_residual_magenta_opaque": int(((a_key >= 250) & mg).sum()),
        "hsv_opaque": round(float((a_hsv >= 250).mean()), 4),
        "hsv_holes_non_magenta": int(((a_hsv < 50) & ~mg).sum()),
        "palette_in_hsv_band": conflicts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("--out", type=Path, required=False)
    parser.add_argument("--check", type=Path, help="棋盘检查图路径,默认 out 同名 _check.png")
    parser.add_argument("--key", type=int, nargs=3, default=None, metavar=("R", "G", "B"), help="手动键色;缺省自动采样")
    parser.add_argument("--t0", type=int, default=45)
    parser.add_argument("--t1", type=int, default=95)
    parser.add_argument("--despill", action="store_true", help="剔除与键色同族的红色投影残留(⚠ 红/暖色主体禁用,会把主体删成空洞)")
    parser.add_argument("--hsv", action="store_true", help="V3.16 色相带模式: 红主体+粉洋红底时改用(H∈275°-350° 判背景),键色法在此场景会把主体吃成半透明")
    parser.add_argument("--measure", action="store_true",
                        help="V3.34 只打印选模式证据表(边缘洋红/键色残留/hsv挖洞/配色撞带), 不写盘不抠图")
    parser.add_argument("--palette", type=Path, default=None,
                        help="palette.json: --measure 时把声明色代入 hsv 色相带冲突检查")
    args = parser.parse_args()

    if args.measure:
        pal = []
        if args.palette and args.palette.exists():
            pj = json.loads(args.palette.read_text(encoding="utf-8"))
            for v in pj.values():
                if isinstance(v, str) and v.count(",") == 2:
                    try:
                        pal.append(tuple(int(x) for x in v.split(",")))
                    except ValueError:
                        pass
        rep = measure(args.raw, pal, args.t0, args.t1)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        edge = rep["edge_magenta_ratio"]
        print("\n判读提示（决定在人，本工具不替选）:")
        print(f"  · 边缘洋红占比 {edge:.1%} —— 接近 0 说明生图没给洋红底，键色法的前提不成立，先看生图契约")
        print(f"  · key 残留洋红 {rep['key_residual_magenta_opaque']}px vs hsv 挖洞 {rep['hsv_holes_non_magenta']}px")
        print("    两者都大 = 这件道具自己带粉色：两种模式都会留痕，考虑重抽图或改主体配色")
        if rep["palette_in_hsv_band"]:
            print(f"  · ⚠ 声明色 {rep['palette_in_hsv_band']} 落在 hsv 色相带内 —— 用 --hsv 会把主体抠穿成洞")
        return

    if not args.out:
        parser.error("--out 必填（除非 --measure）")
    check = args.check or args.out.with_name(args.out.stem + "_check.png")
    report = key_out(args.raw, args.out, check, tuple(args.key) if args.key else None,
                     args.t0, args.t1, args.despill, "hsv" if args.hsv else "key")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
