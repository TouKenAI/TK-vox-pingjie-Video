#!/usr/bin/env python3
"""V8.1.1 ease 对拍测试 —— layout_check 与 render_sequence 必须是同一套缓动数学。

背景:V300 给渲染器加了 ease-out-back/expo/spring,layout_check 未同步(未知名按 linear
算),V6.8"同一套数学"承诺被打破 → 用 V300 缓动的文字卡可能实际过冲出画而 layout 假 PASS
(P14 实测文字卡 28 处关键帧踩此盲区)。V8.1.1 起 layout_check 直接导入渲染器的 ease;
本测试锁死两边一致——以后渲染器加缓动而门禁没跟上,立即 FAIL 而不是静默漂移。

用法: py -3.12 scripts/test_layout_parity.py   (退出码 0=一致 / 1=漂移,可挂 CI)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

HERE = Path(__file__).resolve().parent
RENDERER = HERE / "render_sequence.py"
if not RENDERER.exists():
    RENDERER = HERE.parent.parent / "create-collage-animation" / "scripts" / "render_sequence.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    if not RENDERER.exists():
        print(f"FAIL: 找不到渲染器 {RENDERER}")
        return 1
    rs = load("_rs_parity", RENDERER)
    lc = load("_lc_parity", HERE / "layout_check.py")

    names = ["linear", "ease-in", "ease-out", "ease-in-out",
             "ease-out-expo", "ease-out-back", "ease-spring", "unknown-name"]
    bad = 0
    for name in names:
        for i in range(101):
            t = i / 100
            a, b = rs.ease(name, t), lc.ease(name, t)
            if abs(a - b) > 1e-9:
                print(f"DRIFT: ease({name!r}, {t}) renderer={a:.6f} layout={b:.6f}")
                bad += 1
    if bad:
        print(f"=== FAIL === {bad} 处漂移 —— layout_check 的 ease 与渲染器不一致, 修复前禁止渲染")
        return 1

    v300 = [n for n in ("ease-out-back", "ease-out-expo", "ease-spring")
            if abs(rs.ease(n, 0.5) - rs.ease("linear", 0.5)) > 1e-9]
    # V8.1.1 扩展:tween 对拍(五字段插值数学,含 V300 缓动的过冲区间)
    layer_keys = [
        {"frame": 0, "x": 100, "y": 200, "scale": 0.96, "rotation": -3, "opacity": 0},
        {"frame": 30, "x": 540, "y": 700, "scale": 1.0, "rotation": 2, "opacity": 1, "ease": "ease-out-back"},
        {"frame": 60, "x": 900, "y": 1100, "scale": 1.04, "rotation": 0, "opacity": 1, "ease": "ease-spring"},
        {"frame": 90, "x": 400, "y": 900, "scale": 0.98, "rotation": 1.5, "opacity": 0.6, "ease": "ease-out-expo"},
    ]
    for fr in range(0, 91, 3):
        a, b = rs.tween(layer_keys, fr), lc.tween(layer_keys, fr)
        for field in ("x", "y", "scale", "rotation", "opacity"):
            if abs(float(a[field]) - float(b[field])) > 1e-9:
                print(f"DRIFT: tween(f={fr}).{field} renderer={a[field]} layout={b[field]}")
                bad += 1
    if bad:
        print("=== FAIL === tween 漂移见上, 修复前禁止渲染")
        return 1
    # 过冲验证: ease-out-back 必须有超过 1.0 的过冲点(否则包围盒会低估)
    overshoot = max(rs.ease("ease-out-back", i / 100) for i in range(101))
    print(f"PASS: ease 对拍 {len(names)} 名 × 101 点 + tween 31 帧 × 5 字段全一致; "
          f"V300 生效: {','.join(v300)}; back 过冲峰值 {overshoot:.4f}")
    if overshoot <= 1.0:
        print("WARN: ease-out-back 未检测到过冲——渲染器公式可能已变更, 检查是否仍是轻微过冲设计")
    return 0


if __name__ == "__main__":
    sys.exit(main())
