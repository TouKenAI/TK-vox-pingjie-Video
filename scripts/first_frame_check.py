#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开场空台门 —— 结构判据, 秒级, 不渲染。

规则: 每一场的**第 0 帧**必须至少有一个 opacity>=0.3 的图层在场。
第 0 帧空台 = 开头若干帧只剩裸背景。裸背景会不会被 qa_deliver 判"纯色空白帧"取决于背景纹理
+ 编码链(4:2:0 色度抽样/饱和滤镜), **在 PNG 层面预测不出来**(p14 实测: 源图 std 40.9、渲染 PNG
54x72 缩略 std 17.3, 而 qa_deliver 在解码帧上测到 5.5) —— 所以本门不猜阈值, 只断言结构事实。

为什么它同时是镜头语言问题: 舞台元素(白板/桌面/墙面)是**持续存在**的, 不该每场重新"淡入诞生"。
只有全片第一次登场才值得从 scale 0 砸入。
p14 实录: 11 场里 10 场让白板从 scale 0 入场, s02/s08 开头 1-4 帧空台, 渲完 669s + 编码后才被
qa_deliver 拦下, 白烧一整轮渲染。

用法: py -3.14 first_frame_check.py <项目目录>
退出码 0=每场第 0 帧都有内容, 1=有空台场。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

OP_SEEN = 0.3


def visible_at(scene: dict, frame: int = 0) -> list:
    """第 frame 帧已在场且不透明的图层 id。"""
    out = []
    for l in scene.get("layers", []):
        # 只收 dict 关键帧: 裸元组(helper 漏走 kf())会让 .get() 崩栈, 本门就跑在 preflight 前面
        kfs = sorted([k for k in (l.get("keyframes") or []) if isinstance(k, dict)],
                     key=lambda k: k.get("frame", 0))
        if not kfs:
            if float(l.get("opacity", 1)) >= OP_SEEN:
                out.append(l.get("id", "?"))
            continue
        k0 = kfs[0]
        if int(k0.get("frame", 0)) <= frame and float(k0.get("opacity", 1)) >= OP_SEEN:
            out.append(l.get("id", "?"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    a = ap.parse_args()
    scenes = sorted(a.project.glob("scene_s*.json"))
    if not scenes:
        # 零场景必须 FAIL: 路径打错时报 PASS 是个会骗人的门(V3.21 审查实录: 空目录返回 PASS)
        print("FAIL: 未找到 scene_s*.json——项目路径写错? 本门无场景时不得报 PASS", file=sys.stderr)
        return 1
    bad, rows = [], []
    for sp in scenes:
        d = json.loads(sp.read_text(encoding="utf-8"))
        vis = visible_at(d, 0)
        rows.append((sp.name, len(vis), vis[0] if vis else "-"))
        if not vis and d.get("intro_empty_ok"):
            print(f"  [INFO] {sp.name} 冷开场刻意空台 {d['intro_empty_ok']} 帧(已声明: 舞台从画外砸入的第一拍)")
            continue
        if not vis:
            first = min((int(k.get("frame", 0)) for l in d.get("layers", [])
                         for k in l.get("keyframes", []) if float(k.get("opacity", 1)) >= OP_SEEN),
                        default=None)
            bad.append(f"{sp.name} 第 0 帧空台(最早可见图层在第 {first} 帧) -> 开头 {first} 帧只剩裸背景; "
                       f"平涂底会被 qa_deliver 判纯色空白帧。修法: 舞台元素第 0 帧即 opacity=1"
                       f"(只保留挤压回弹定住), 只有全片第一次登场才从 scale 0 砸入")
    for name, n, first in rows:
        print(f"  {'[  ok]' if n else '[FAIL]'} {name:16s} 第0帧在场图层 {n:>2} 个 (首个: {first})")
    if bad:
        print("=== FAIL ===")
        for m in bad:
            print("  " + m)
        return 1
    print("PASS: 每场第 0 帧都有内容在场")
    return 0


if __name__ == "__main__":
    sys.exit(main())
