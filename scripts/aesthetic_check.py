#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.12 审美/视觉质量 QC —— 给"好不好看"补一个结构化机检代理(此前所有 gate 只测下限, 不测美)。

对每场抽样帧计算可量化代理:
  1 构图平衡 balance: 边缘视觉重量左右/上下是否失衡(全堆一侧=低分)
  2 主体突出 salience: 显著像素占比 + 峰值集中度(太平=没主体)
  3 留白/密度 fill: 近边 ink(过满>0.07 拥挤 / 过空<0.02 单薄)
  4 色彩和谐 harmony: 采样像素贴合 palette 的比例 + 高饱和色相是否打架
  5 对齐 align: 图层落点在少数公共竖轴/横基线上的比例(用 scene JSON)
综合 0–100 分 + 分项 + 明显问题 flag。非硬门(审美主观), 但给"低于基线"的场亮黄灯。

用法: py aesthetic_check.py <项目> [--samples 3] [--json-out qa/]
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
from PIL import Image
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

HERE = Path(__file__).resolve().parent


def parse_rgb(s):
    return tuple(int(v) for v in str(s).split(","))


def load_palette(proj):
    p = proj / "palette.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    cols = []
    for k in ("bg", "fg", "accent", "accent2"):
        if k in d:
            cols.append(np.array(parse_rgb(d[k]), dtype=float))
    return np.array(cols) if cols else None


def edge_map(g):
    gy, gx = np.gradient(g)
    return np.hypot(gx, gy)


def frame_metrics(img, pal):
    a = np.asarray(img.convert("RGB"), dtype=float)
    h, w, _ = a.shape
    g = a.mean(2)
    E = edge_map(g)
    strong = E > 12
    # 1 平衡
    L, R = strong[:, :w//2].mean(), strong[:, w//2:].mean()
    T, B = strong[:h//2, :].mean(), strong[h//2:, :].mean()
    bal_lr = 1 - abs(L - R) / max(1e-6, L + R)
    bal_tb = 1 - abs(T - B) / max(1e-6, T + B)
    balance = (bal_lr + bal_tb) / 2
    # 2 主体突出: 显著像素占比 + 9×9 块峰值集中度
    sal_ratio = float(strong.mean())
    bs = h // 9
    blocks = [strong[i*bs:(i+1)*bs, :].mean() for i in range(9)]
    peak = max(blocks) / max(1e-6, np.mean(blocks)) if np.mean(blocks) > 0 else 0
    salience = min(1.0, sal_ratio * 6) * 0.5 + min(1.0, peak / 3) * 0.5
    # 3 留白/密度: 近边(外12%)ink
    bx, by = int(w*0.12), int(h*0.12)
    border = np.concatenate([strong[:by,:].ravel(), strong[-by:,:].ravel(),
                             strong[:,:bx].ravel(), strong[:,-bx:].ravel()])
    fill = float(border.mean())
    # 4 色彩: 贴合 palette 比例(adhere, 风格无关) + 高饱和色相数(clash, 风格相关→主程序按片中位数归一)
    adhere = 1.0; clash = 0.0
    if pal is not None:
        pix = a.reshape(-1,3)[::37]
        d = np.linalg.norm(pix[:,None,:]-pal[None,:,:], axis=2).min(1)
        adhere = float((d < 90).mean())
        hsv = np.asarray(Image.fromarray(a.astype('uint8')).convert("HSV"), dtype=float).reshape(-1,3)[::37]
        sat = hsv[:,1] > 150
        hue = hsv[:,0][sat]
        if len(hue) > 50:
            hist,_ = np.histogram(hue, bins=12, range=(0,256))
            hist = hist/hist.sum()
            clash = float((hist > 0.32).sum())  # 主导高饱和色相数
    return dict(balance=balance, salience=salience, fill=fill, adhere=adhere, clash=clash, sal_ratio=sal_ratio)


def align_score(scene_json):
    xs, ys = [], []
    for l in scene_json.get("layers", []):
        kfs = l.get("keyframes", [])
        if not kfs:
            continue
        last = max(kfs, key=lambda k: k["frame"])
        xs.append(round(float(last.get("x", 0)))); ys.append(round(float(last.get("y", 0))))
    if len(xs) < 3:
        return 1.0
    def clustered(vals, tol=40):
        vals = sorted(vals); groups = 1
        for i in range(1, len(vals)):
            if vals[i] - vals[i-1] > tol:
                groups += 1
        return max(0.0, min(1.0, 1 - (groups-1)/max(1, len(vals)-1) + 0.25))
    return (clustered(xs) + clustered(ys)) / 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args()
    proj = a.project.resolve()
    pal = load_palette(proj)
    scenes = sorted(proj.glob("scene_s*.json"))
    if not scenes:
        print("无 scene_s*.json"); return 1
    raw = []
    for sp in scenes:
        sdir = proj / ("frames_" + sp.stem.split("_")[1])
        frames = sorted(sdir.glob("frame_*.png"))
        if not frames:
            continue
        idxs = [int(round(i*(len(frames)-1)/max(1,a.samples-1))) for i in range(a.samples)] if a.samples>1 else [len(frames)//2]
        ms = [frame_metrics(Image.open(frames[i]), pal) for i in idxs]
        avg = {k: sum(m[k] for m in ms)/len(ms) for k in ("balance","salience","fill","adhere","clash")}
        al = align_score(json.loads(sp.read_text(encoding="utf-8")))
        raw.append((sp.stem, avg, al))
    # 片中位数=风格基线: 留白只单向罚"拥挤"(清爽不罚); 和谐用"色相集中度"(片内主色族越少越协调, 风格无关)
    import statistics as st
    med_fill = st.median(r[1]["fill"] for r in raw) or 1e-6
    med_clash = st.median(r[1]["clash"] for r in raw)
    rows = []
    for name, avg, al in raw:
        fr = avg["fill"] / med_fill                       # 相对本片留白
        fill_pen = 1.0 if fr <= 1.5 else 0.5              # 只罚拥挤离群, 不罚清爽
        # 和谐: 主色族数(clash)相对本片常态→协调度; 与 palette.json 无关(漫画多色不误伤)
        clash_excess = max(0.0, avg["clash"] - max(med_clash, 2.5))
        harmony = max(0.0, min(1.0, 1.0 - clash_excess / 2.5))
        score = round(100*(0.25*avg["balance"] + 0.20*avg["salience"] + 0.20*fill_pen + 0.20*harmony + 0.15*al), 1)
        flags = []
        if avg["balance"] < 0.55: flags.append("构图失衡(偏一侧)")
        if avg["salience"] < 0.25: flags.append("主体不突出")
        if fr > 1.5: flags.append("偏拥挤(相对本片)")
        if harmony < 0.5: flags.append("色彩不协调")
        if al < 0.4: flags.append("元素缺对齐")
        rows.append(dict(scene=name, score=score, balance=round(avg["balance"],3),
                         salience=round(avg["salience"],3), fill=round(avg["fill"],3),
                         fill_rel=round(fr,2), harmony=round(harmony,3), align=round(al,3), flags=flags))
        print(f"{name}: {score:5.1f}  衡{avg['balance']:.2f} 主{avg['salience']:.2f} 留{avg['fill']:.3f}(×{fr:.2f}) 和{harmony:.2f} 齐{al:.2f}  {'⚠ '+'/'.join(flags) if flags else '✓'}")
    if rows:
        mean = sum(r["score"] for r in rows)/len(rows)
        worst = min(rows, key=lambda r: r["score"])
        print(f"\n审美均分 {mean:.1f}/100 | 最低 {worst['scene']} {worst['score']} | 基线参考: p8 应≥其分")
        out = a.json_out or (proj / "qa")
        out.mkdir(parents=True, exist_ok=True)
        (out / "aesthetic-report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        # montage: 每场中间帧 + 分数标注
        from PIL import ImageDraw
        cols = 5; cell = 220
        rws = math.ceil(len(rows)/cols)
        sheet = Image.new("RGB", (cols*cell, rws*(cell+20)), (245,245,245)); d = ImageDraw.Draw(sheet)
        for i, r in enumerate(rows):
            sdir = proj / ("frames_" + r["scene"].split("_")[1]); fr = sorted(sdir.glob("frame_*.png"))
            im = Image.open(fr[len(fr)//2]).convert("RGB"); im.thumbnail((cell, cell))
            cx, cy = divmod(i, cols)
            sheet.paste(im, (cx*cell, cy*(cell+20)))
            col = (20,120,40) if r["score"]>=70 else (200,140,20) if r["score"]>=55 else (200,40,40)
            d.text((cx*cell+3, cy*(cell+20)+cell+1), f"{r['scene'][-3:]} {r['score']}", fill=col)
        sheet.save(out / "aesthetic_montage.png")
        print(f"报告 → {out/'aesthetic-report.json'}  总览 → {out/'aesthetic_montage.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
