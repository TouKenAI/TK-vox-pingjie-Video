#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bg_luma_check.py —— 背景亮度硬门(V3.18, production10 爆闪事故机制化)。

事故: production10 白板手绘背景灰度均值≈248, 渲染成片后 qa_deliver 抽帧判
"爆闪"(帧均值>235) HARD FAIL, 事后手动 PIL 降亮 0.85 + 全量重渲。
本门把修复前移到渲染前: 逐场检查 scene JSON 的 background.path PNG 灰度均值,
>235 就自动降亮 --dim(默认 0.85) 并复检; 降完仍 >235 才 FAIL 拒绝渲染。

幂等: 已降过的图均值<阈值, 重跑零操作(不会 0.85 连乘)。
用法:
  py bg_luma_check.py <项目目录>                # 默认自动修, 修不好 FAIL
  py bg_luma_check.py <项目目录> --no-fix       # 只报不修(降亮后也 FAIL, 用于 dry-run)
  py bg_luma_check.py <项目目录> --dim 0.9      # 自定义降亮系数
输出: 逐图 mean 行 + qa/bg-luma.json; 退出码 0=通过 / 1=有图无法压到阈值内。
被 render_all.py 的 preflight_tools 列表自动调用(第一道, 在 preflight_v6 之前)。
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
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

from PIL import Image, ImageEnhance, ImageStat


def luma_mean(p: Path) -> float:
    im = Image.open(p).convert("L")
    im.thumbnail((256, 256))  # 均值对缩放不敏感, 提速
    return ImageStat.Stat(im).mean[0]


def stage_metrics(p: Path, want_ground=None):
    """V3.24 空舞台判据。返回 (中心墨密度, 边缘墨密度, 主色与声明底色的最大偏移)。

    为什么不用"中位数当底色": production16 的 bg08 生成成了 78% 纯黑, 中位数即黑色,
    于是"离中位数够远=有墨"把整片黑判成空白 —— 指标在最坏样本上打了满分。
    现按 16×16×16 分箱取**众数箱均值**当地色, 再量"离地色够远"的像素; 地色本身另判一道。
    """
    import numpy as np
    a = np.asarray(Image.open(p).convert("RGB"), dtype=float)
    b = (a // 16).astype(np.int32)
    key = (b[:, :, 0] << 8) | (b[:, :, 1] << 4) | b[:, :, 2]
    vals, cnt = np.unique(key.ravel(), return_counts=True)
    top = int(vals[cnt.argmax()])
    ground = a[key == top].mean(axis=0)
    ink = (np.abs(a - ground).max(axis=2) > 24)
    h, w = ink.shape
    c = ink[int(h * .25):int(h * .75), int(w * .25):int(w * .75)]
    m = ink.copy()
    m[int(h * .25):int(h * .75), int(w * .25):int(w * .75)] = False
    delta = float(np.abs(ground - np.asarray(want_ground, dtype=float)).max()) if want_ground else 0.0
    return float(c.mean()), float(m.mean()), delta


def border_measure(p: Path, want, ring: float = 0.04):
    """量"外圈有多少像素不是声明地色", 并给出纸面 bbox。**只是测量, 不是门**——
    拿 `share > 0.20` 当硬门在 p12-p15 四部已交付片上点亮 19 张背景(p12 6 张 / p13 6 张 /
    p14 6 张 / p15 1 张), 因为"边上有东西"本来就是这部片子的视觉语言(撕边带、钢印、深色浮世绘底)。
    第五个标定失败的弱代理门, 见 playbook §57/§59。判"边框是不是画坏了"要看得懂画面, 交人。
    需要时用 `--trim-border` 手动裁, 它只裁不判。
    """
    import numpy as np
    if not want:
        return 0.0, None
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
    H, W, _ = a.shape
    dist = np.abs(a - np.array(want, dtype=np.int16)).sum(axis=2)
    off = dist > 120
    b = max(2, int(min(H, W) * ring))
    rm = np.zeros((H, W), bool)
    rm[:b, :] = rm[-b:, :] = rm[:, :b] = rm[:, -b:] = True
    share = float(off[rm].mean())
    ys, xs = np.where(~off)
    if len(xs) < 16 or (int(xs.max()) + 1 - int(xs.min())) * (int(ys.max()) + 1 - int(ys.min())) < 0.5 * H * W:
        return share, None
    return share, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def _bak(bak: Path, p: Path) -> Path:
    """旧图归档名。同一张图可能被"裁→再填→再裁"多次, 只按内容哈希命名会在**还原过备份**的
    场景撞名(p16 实录: 从 prev_assets 复原后又触发第二次备份 → FileExistsError)。"""
    import hashlib
    dst = bak / (p.stem + ".v" + hashlib.sha256(p.read_bytes()).hexdigest()[:8] + p.suffix)
    i = 1
    while dst.exists():
        dst = bak / (p.stem + f".v{i}" + hashlib.sha256(p.read_bytes()).hexdigest()[:8] + p.suffix)
        i += 1
    return dst


def trim_border(proj: Path, name: str, want) -> int:
    """`--trim-border bg10_repo_open.png` —— 人看完图判定"这圈深色是画坏的封面", 才用它裁到纸面。"""
    p = next((q for q in (proj / "assets" / "raw").glob(name) if q.is_file()), None)
    if p is None:
        return print(f"FAIL: 找不到 {name}") or 1
    share, bbox = border_measure(p, want)
    print(f"{p.name}: 外圈非地色 {share:.0%}, 纸面 bbox={bbox}")
    if not bbox:
        return print("FAIL: 纸面不足半幅或无声明地色——这该重抽图, 不该裁") or 1
    bak = proj / "qa" / "prev_assets"
    bak.mkdir(parents=True, exist_ok=True)
    dst = _bak(bak, p)
    p.rename(dst)
    Image.open(dst).convert("RGB").crop(bbox).save(p)
    s2, _ = border_measure(p, want)
    print(f"旧图 → {dst.relative_to(proj)}; 裁后 {bbox[2]-bbox[0]}×{bbox[3]-bbox[1]}, 外圈非地色 {s2:.0%}")
    return 0


def paint_border(proj: Path, name: str, want, frac: float = 0.04) -> int:
    """`--paint-border bg10_repo_open.png` —— 把与画面外圈连通的深色"封面/桌面"填成纸色。
    p16 实录: StepFun 画"摊开的册页"时两轮都自作主张加一圈深色封面当边框, 契约写死"纸铺到四边、
    no dark background"也压不住。裁切会把四角的页缘一起裁掉(实测裁后 fill=0.00, 概念丢了),
    填色才只去掉违规的那圈黑。取中心区**实际众数纸色**而不是 palette 声明值, 避免填出一块偏色矩形。
    """
    import numpy as np
    from collections import Counter

    p = next((q for q in (proj / "assets" / "raw").glob(name) if q.is_file()), None)
    if p is None:
        print(f"FAIL: 找不到 {name}")
        return 1
    im = Image.open(p).convert("RGB")
    W, H = im.size
    a = np.asarray(im).astype(np.float32)
    cy0, cy1, cx0, cx1 = H // 4, H * 3 // 4, W // 4, W * 3 // 4
    patch = a[cy0:cy1, cx0:cx1].reshape(-1, 3)
    paper = np.array(Counter(tuple(int(v) for v in q) for q in patch[::7]).most_common(1)[0][0], dtype=np.float32)
    # 边缘带羽化重涂: 距边 band 内全涂纸色, 再向内 band 线性淡出。
    # 不用 floodfill —— 书脊/桌面阴影是**渐变**, 阈值泛洪会在渐变前停下(p16 实测外圈仍剩 5% 黑,
    # 左侧书脊整条没掉)。羽化对渐变有效, 且四角页缘(距边 >8%)不受影响。
    band = max(6, int(min(W, H) * (frac or 0.04)))
    ys = np.minimum(np.arange(H), np.arange(H)[::-1])[:, None].astype(np.float32)
    xs = np.minimum(np.arange(W), np.arange(W)[::-1])[None, :].astype(np.float32)
    edge = np.minimum(ys, xs)
    w = np.clip(1.0 - (edge - band) / band, 0.0, 1.0)[:, :, None]
    off = (np.abs(a - paper).sum(axis=2, keepdims=True) > 90).astype(np.float32)
    out = np.where(off > 0, a + (paper - a) * w, a)
    im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    n = int((w.squeeze(-1) > 0.5).sum())
    if not n:
        print(f"{p.name}: 无边缘带, 跳过")
        return 0
    bak = proj / "qa" / "prev_assets"
    bak.mkdir(parents=True, exist_ok=True)
    dst = _bak(bak, p)
    p.rename(dst)
    im.save(p)
    share, _ = border_measure(p, want or [int(v) for v in paper])
    print(f"{p.name}: 边缘带 {band}px 羽化重涂为纸色 {tuple(int(v) for v in paper)}; "
          f"旧图 {dst.relative_to(proj)}; 复测外圈非纸色 {share:.0%}")
    return 0


def density_gate(proj: Path, files, ratio_max: float = 2.0, report_only: bool = False) -> list[str]:
    """V3.25 渲前背景密度一致性门。判据: **该张 edge ÷ 本片背景 edge 中位 > ratio_max** → 指名重抽那一张。

    为什么值得做(p16 实测): clutter 报 s04/s10 过载时我先怀疑门, 用四种统计量 + 58 场语料回放证明
    门是对的(s04 0.096 / s10 0.093 高于全部 58 场最大值 0.083), 根因是**背景自己差 6 倍**
    (bg10 是自家背景中位的 2.82×)。而这件事在阶段④量 19 张 PNG 只要 3 秒, 我却是在
    435s 渲染 + 一次装配之后才发现的 —— 本门就是把那次测量挪到花钱之前。

    为什么它不会重演"边框门点亮 19 张": 它**只判同一片内部的一致性**, 不判"这张好不好看",
    所以与画风、与深浅底都无关。五部已交付片实测 max/median:
        p12 1.84  p14 1.76  p15 1.69   → 绿
        p13 2.11 (审美 78.3, 五片最低)  p16 2.25 (79.8, 次低)  → 红
    阈值 2.0 恰好把"历史上最不一致的两片"圈出来, 而这两片也正是审美最低的两片 —— 有质量锚点。
    """
    import statistics
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from clutter_check import metrics

    rows = []
    for f in files:
        try:
            rows.append((Path(f), metrics(f)[0]))
        except Exception as e:
            print(f"[bg-density] ⚠ 读不了 {f}: {e}")
    if len(rows) < 4:
        print(f"[bg-density] 背景不足 4 张({len(rows)}), 中位数不可用, 跳过密度门")
        return []
    med = statistics.median(e for _, e in rows) or 1e-9
    bad = []
    for f, e in sorted(rows, key=lambda r: -r[1]):
        r = e / med
        mark = ""
        if r > ratio_max:
            mark = "  ← 超本片中位 %.1f×, 重抽这一张(prompt 里给数值密度预算, 别用 densely 这类副词)" % ratio_max
            bad.append(f.name)
        elif r > ratio_max * 0.8:
            mark = "  (接近)"
        print(f"  [bg-density] {f.name:30s} edge={e:.4f} 本片x{r:4.2f}{mark}")
    if bad and not report_only:
        print(f"[bg-density] FAIL: {len(bad)} 张背景比本片中位密 >{ratio_max}×: {', '.join(bad)}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--threshold", type=float, default=235.0,
                    help="灰度均值上限, 对齐 qa_deliver 爆闪门(>235 判爆闪)")
    ap.add_argument("--dim", type=float, default=0.85,
                    help="自动降亮系数(production10 实证值)")
    ap.add_argument("--no-fix", action="store_true",
                    help="只报不修; 有超阈图直接 FAIL")
    ap.add_argument("--no-stage", action="store_true",
                    help="关掉 V3.24 空舞台判据(只跑爆闪门)")
    ap.add_argument("--no-density", action="store_true",
                    help="关掉 V3.25 背景密度一致性门")
    ap.add_argument("--density-max", type=float, default=2.0,
                    help="单张背景 edge 相对本片中位的上限倍数(五片标定值)")
    ap.add_argument("--center-max", type=float, default=0.06,
                    help="画面中心 50%% 方框内允许的墨色占比上限(前景道具要留台)")
    ap.add_argument("--trim-border", metavar="BG", default=None,
                    help="只裁不判: 人判定背景外圈是画坏的深色封面后, 把它裁到纸面(旧图进 qa/prev_assets/)")
    ap.add_argument("--paint-border", metavar="BG", default=None,
                    help="只填不判: 把与外圈连通的深色封面/桌面填成纸色, 保留四角页缘(裁切会连内容一起裁掉)")
    a = ap.parse_args()
    proj = a.project.resolve()
    want = None
    pf = proj / "palette.json"
    if pf.exists() and not a.no_stage:
        try:
            want = [int(x) for x in json.loads(pf.read_text(encoding="utf-8-sig"))["bg"].split(",")]
        except Exception:
            want = None

    scenes = sorted(proj.glob("scene_s*.json"))
    if a.paint_border:
        return paint_border(proj, a.paint_border, want)
    if a.trim_border:
        return trim_border(proj, a.trim_border, want)
    if not scenes:
        # V3.25: 以前这里直接 return 0。但背景在**阶段④**就产出了, 等场景 JSON 等于等到渲完
        # 才知道素材有问题。没有场景 JSON 时改为扫 assets/raw/bg*.png, 只跑密度门(它不需要场景)。
        bgs = sorted((proj / "assets" / "raw").glob("bg*.png"))
        if not bgs:
            # V3.26: 无场景**也无背景**时旧版 return 0 —— "项目路径写错"恰好就是这个样子,
            # 于是本门在空目录上假 PASS。什么都没得查不是通过, 是调用出错。
            print(f"[bg-luma] FAIL: {proj} 下既无 scene_s*.json 也无 assets/raw/bg*.png"
                  f" —— 本门无事可读, 十有八九是项目路径写错", file=sys.stderr)
            return 1
        if a.no_density:
            print("[bg-luma] 素材阶段模式: --no-density 显式关闭密度门, 本次不判(人为主动选择)")
            return 0
        print(f"[bg-luma] 素材阶段模式(无 scene JSON): 扫 {len(bgs)} 张背景, 只跑密度门")
        return 1 if density_gate(proj, bgs, a.density_max) else 0

    seen, rows, srows, fails = set(), [], [], []
    for sc in scenes:
        try:
            plan = json.loads(sc.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"[bg-luma] ⚠ {sc.name} 解析失败: {e}")
            continue
        bg = (plan.get("background") or {}).get("path")
        if not bg or bg in seen:
            continue
        seen.add(bg)
        p = proj / bg
        if not p.exists():
            print(f"[bg-luma] ⚠ 背景缺失(账本门会拦): {bg}")
            continue
        m = luma_mean(p)
        status, note = "OK", ""
        if m > a.threshold:
            if a.no_fix:
                status, fails = "FAIL", fails + [bg]
                note = f"> {a.threshold} (--no-fix 不修)"
            else:
                im = Image.open(p).convert("RGB")
                im = ImageEnhance.Brightness(im).enhance(a.dim)
                im.save(p)
                m2 = luma_mean(p)
                if m2 > a.threshold:
                    status, fails = "FAIL", fails + [bg]
                    note = f"降亮 {a.dim} 后仍 {m2:.1f} > {a.threshold}"
                else:
                    status = "DIMMED"
                    note = f"{m:.1f} → {m2:.1f} (×{a.dim})"
                    m = m2
        print(f"  [{status:6s}] {bg:36s} mean={m:6.1f} {note}")
        rows.append({"bg": bg, "mean": round(m, 1), "status": status})
        if not a.no_stage:
            cen, edg, dgr = stage_metrics(p, want)
            srows.append({"bg": bg, "center": round(cen, 3), "edge": round(edg, 3), "ground_delta": round(dgr, 1)})
            # 只报不判: 拿 p12/p13/p14/p15 四部已交付好片回放过, 中心墨密度与主色偏离在深色底/带颗粒的
            # 风格上全线亮红(p15 中心 0.998、p12 片内主色偏离 198), 换成梯度能量同样分不开
            # (p13 中位 1.71 比 p16 的坏样本还高, 而纯黑那张梯度最低 0.08)。判据不通用 → 当门就是假阳性。
            flag = "  ← 目检确认中心有没有被画实" if cen > a.center_max or (want and dgr > 40) else ""
            print(f"           · 诊断: 中心墨 {cen:.3f} 边缘 {edg:.3f} 地色Δ {dgr:.1f}{flag}")

    dbad = [] if a.no_density else density_gate(proj, [proj / b for b in sorted(seen)], a.density_max)

    qa = proj / "qa"
    qa.mkdir(exist_ok=True)
    (qa / "bg-luma.json").write_text(
        json.dumps({"threshold": a.threshold, "center_max": a.center_max,
                    "density_max": None if a.no_density else a.density_max,
                    "density_outliers": dbad, "rows": rows, "stage_diag": srows}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    if fails:
        print(f"[bg-luma] FAIL: {len(fails)} 张背景压不进 {a.threshold} → 拒绝渲染: {fails}")
        return 1
    if dbad:
        print(f"[bg-luma] FAIL: {len(dbad)} 张背景比本片中位密 >{a.density_max}× → 拒绝渲染: {dbad}")
        return 1
    print(f"[bg-luma] PASS (爆闪阈值 {a.threshold}"
          + ("" if a.no_density else f" / 密度上限 本片x{a.density_max}") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
