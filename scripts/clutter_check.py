#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.5 画面拥挤度量化门（①）：从渲染帧测"像素级忙乱度"，补 polycheck 只数图层的盲区。

指标(每场采样若干帧取中位):
  edge_density  平均梯度幅值(归一化0-1)——越高越"满/杂"
  ink_ratio     前景像素占比(与该场最暗背景色差异大的像素)——越高越挤
判读(V3.22 起**只按本片自身中位数判相对值**): rel>2.0 过载(HARD) / >1.5 偏忙 / <0.62(fill) 或 <0.6(edge) 偏空。
绝对阈值(edge>0.18 / ink>0.55 那一档)**已废且代码从未使用**——V3.22 五片回放证明它无判别力:
p14(频道最好)被判 8/11 场"过载"、p13(最差)反而比 p10 干净, 量的是画风不是拥挤度(playbook §57④)。
⚠ 已知盲区(不是 bug, 是相对门的固有代价): 全片一致偏挤时 rel≡1.0 → 判 OK。绝对下限已试过、已否。
产物: qa/clutter-report.json + qa/clutter_montage.png(每场最忙一帧)。

用法: py clutter_check.py <项目目录> [--samples 5]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死


def metrics(p: Path):
    im = Image.open(p).convert("L"); a = np.asarray(im).astype(np.float32)
    gx = np.abs(np.diff(a, axis=1)).mean(); gy = np.abs(np.diff(a, axis=0)).mean()
    edge = float((gx + gy) / 2.0 / 255.0 * 4)
    rgb = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
    bg = np.median(rgb.reshape(-1, 3), axis=0)
    dist = np.abs(rgb - bg).sum(axis=2)
    inkmask = dist > 90
    ink = float(inkmask.mean())
    # 网格占位率: 6x8 格中有多少格含 >6% 前景(元素铺得越满越忙)
    H, W = inkmask.shape; gr, gc = 6, 8; filled = 0
    for r in range(gr):
        for c in range(gc):
            cell = inkmask[r * H // gr:(r + 1) * H // gr, c * W // gc:(c + 1) * W // gc]
            if cell.mean() > 0.06:
                filled += 1
    return edge, ink, filled / (gr * gc)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--samples", type=int, default=5)
    a = ap.parse_args()
    proj = a.project.resolve()
    scenes = sorted(d for d in proj.glob("frames_s*") if d.is_dir())
    if not scenes:
        # 没渲帧时旧版会走到拼图montage→PIL "cannot write empty image" 崩栈
        sys.exit(f"FAIL: {proj} 下无 frames_s* 目录——本门在渲染之后跑")
    raw, worst, empty = [], [], []
    for d in scenes:
        fr = sorted(d.glob("frame_*.png"))
        if not fr:
            # V3.26: 旧版直接 continue, 把"目录在但没帧"的场**悄悄从统计里摘掉**。
            # 6 场空 + 1 场有帧时, 中位数只由那 1 场算出 → rel≡1.0 → 全场 OK → 假 PASS。
            empty.append(d.name)
            continue
        idxs = np.linspace(0, len(fr) - 1, min(a.samples, len(fr))).astype(int)
        ms = [metrics(fr[i]) for i in idxs]
        edge, ink, gfill = [float(np.median([m[k] for m in ms])) for k in range(3)]
        raw.append({"scene": d.name, "edge": edge, "ink": ink, "grid_fill": gfill})
        wi = int(np.argmax([m[2] for m in ms])); worst.append(fr[idxs[wi]])  # 最"铺满"的一帧
    if empty:
        sys.exit(f"FAIL: {len(empty)} 个 frames_s*/ 目录里没有 frame_*.png({','.join(empty[:6])}"
                 f"{'…' if len(empty) > 6 else ''}) —— 未渲或渲到一半; 摘掉它们会让中位数失真、本门假 PASS")
    if not raw:
        # 目录在但没帧(未渲/渲到一半)时报清楚, 别让 np.median([]) 和 PIL 空图去猜
        sys.exit(f"FAIL: {proj} 下 frames_s*/ 里没有 frame_*.png——先渲染再跑本门")
    med_edge = float(np.median([r["edge"] for r in raw])) or 1e-6
    med_gf = float(np.median([r["grid_fill"] for r in raw])) or 1e-6
    rows = []
    for r in raw:
        rf, re_ = r["grid_fill"] / med_gf, r["edge"] / med_edge
        tag = "OK"
        if rf > 2.0 or re_ > 2.0: tag = "过载(相对)"
        elif rf > 1.5 or re_ > 1.5: tag = "偏忙(相对)"
        elif rf < 0.62 or re_ < 0.6: tag = "偏空(相对)——元素太少, 建议补"
        rows.append({"scene": r["scene"], "edge": round(r["edge"], 3), "ink": round(r["ink"], 2),
                     "grid_fill": round(r["grid_fill"], 2), "rel_fill": round(rf, 2), "rel_edge": round(re_, 2), "verdict": tag})
    (proj / "qa").mkdir(exist_ok=True)
    (proj / "qa" / "clutter-report.json").write_text(json.dumps({"median_edge": round(med_edge, 3), "median_grid_fill": round(med_gf, 2), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = 5; cw, ch = 200, 267; rws = (len(worst) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rws * ch), (20, 20, 20))
    for i, p in enumerate(worst):
        sheet.paste(Image.open(p).convert("RGB").resize((cw, ch)), ((i % cols) * cw, (i // cols) * ch))
    sheet.save(proj / "qa" / "clutter_montage.png")
    hard = [r for r in rows if "过载" in r["verdict"]]; warn = [r for r in rows if "偏忙" in r["verdict"]]; sparse = [r for r in rows if "偏空" in r["verdict"]]
    for r in rows:
        print(f"  {r['scene']}: edge={r['edge']:.3f} ink={r['ink']:.2f} 铺满={r['grid_fill']:.2f} (相对 fill×{r['rel_fill']} edge×{r['rel_edge']}) → {r['verdict']}")
    print(f"\nclutter(相对本片): {len(hard)} 过载 / {len(warn)} 偏忙 / {len(rows)} 场  (report→qa/clutter-report.json, 每场最忙帧→qa/clutter_montage.png)")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
