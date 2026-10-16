#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.12 animatic 预览门：全量渲染前，低清+跳帧快速预渲每场，抓构图/遮挡/动效/字出画问题。

产出:
  qa/animatic/frames_sNN/  每场跳帧低清帧
  qa/animatic/filmstrip.png 每场一条时间带(横向抽样) 拼成总览
  qa/animatic/preview.mp4   快速预览片(低帧率, 只为看动效节奏)

用法: py animatic.py <项目> [--step 6] [--scale 0.4] [--fps 5]
退出码 0=已生成(供人/审美QC判读), 非门禁(不阻断), 是"省时防翻车"的预览。
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw

# 子进程强制 UTF-8：默认 GBK 下 render_sequence 一 print ✓ 就崩 → 预渲失败(见 env_paths 顶部)
from env_paths import CHILD_ENV

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

HERE = Path(__file__).resolve().parent
PY = sys.executable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--step", type=int, default=6)
    ap.add_argument("--scale", type=float, default=0.4)
    ap.add_argument("--fps", type=int, default=5)
    a = ap.parse_args()
    proj = a.project.resolve()
    out = proj / "qa" / "animatic"
    out.mkdir(parents=True, exist_ok=True)
    scenes = sorted(proj.glob("scene_s*.json"))
    if not scenes:
        print("无 scene_s*.json"); return 1
    strips = []
    for sp in scenes:
        sdir = out / ("frames_" + sp.stem.split("_")[1])
        cmd = [PY, str(HERE / "render_sequence.py"), str(sp), "--output", str(sdir),
               "--overwrite", "--step", str(a.step), "--scale", str(a.scale)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=CHILD_ENV)
        frames = sorted(sdir.glob("frame_*.png"))
        if not frames:
            print(f"⚠ {sp.name} 预渲失败: {(r.stderr or r.stdout).strip()[-160:]}"); continue
        # 该场抽样横向拼成一条带(最多 8 格)
        picks = frames if len(frames) <= 8 else [frames[int(i*(len(frames)-1)/7)] for i in range(8)]
        w, h = Image.open(picks[0]).size
        strip = Image.new("RGB", (w*len(picks), h+18), (255, 255, 255))
        d = ImageDraw.Draw(strip)
        for i, f in enumerate(picks):
            strip.paste(Image.open(f).convert("RGB"), (i*w, 0))
        d.text((4, h+2), f"{sp.stem}  {len(frames)}帧/step{a.step}", fill=(0, 0, 0))
        strips.append((sp.stem, strip))
        print(f"✓ {sp.stem}: {len(frames)} 预览帧")

    # 总览: 每条带缩到统一宽, 纵向堆叠
    if strips:
        tw = 900
        rows = []
        for name, st in strips:
            sc = tw / st.width
            rows.append(st.resize((tw, max(1, round(st.height*sc)))))
        H = sum(r.height for r in rows)
        sheet = Image.new("RGB", (tw, H), (230, 230, 230))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y)); y += r.height
        sheet.save(out / "filmstrip.png")
        print(f"总览 → {out/'filmstrip.png'}")

    # 快速预览 mp4(可选, 有 ffmpeg 才做): 用 concat list 把所有预览帧按序编码
    try:
        sys.path.insert(0, str(HERE))
        from env_paths import ffmpeg
        ffm = str(ffmpeg())
        allf = []
        for sdir in sorted(out.glob("frames_s*")):
            allf += sorted(sdir.glob("frame_*.png"))
        if allf:
            lst = out / "_list.txt"
            with lst.open("w", encoding="utf-8") as fh:
                for f in allf:
                    fh.write(f"file '{f.as_posix()}'\nduration {1.0/a.fps}\n")
                fh.write(f"file '{allf[-1].as_posix()}'\n")
            # 预览帧是 float scale 出来的，高/宽可能是奇数(如 0.22 倍 → 238×317)。
            # libx264 + yuv420p 直接拒绝奇数尺寸 → 旧版 rc 不查、只查 exists()，
            # 于是 preview.mp4 留一个 0 字节文件还打印"预览片 →"(p26 实录；p24/p25 的
            # 0.35 倍恰好 378×504 偶数才一直没暴露)。修：向下取偶 + 查 rc + 查大小。
            pv = out / "preview.mp4"
            r = subprocess.run([ffm, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                                "-vf", f"fps={a.fps},scale=trunc(iw/2)*2:trunc(ih/2)*2",
                                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                "-crf", "28", str(pv)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0 or not pv.exists() or pv.stat().st_size < 1024:
                print(f"✗ 预览片编码失败 rc={r.returncode} size="
                      f"{pv.stat().st_size if pv.exists() else 'NOFILE'} —— 预览门没有产物, 别当成看过了")
                print("  " + ((r.stderr or "").strip().splitlines() or ["(无 stderr)"])[-1])
                return 1
            print(f"预览片 → {pv} ({pv.stat().st_size//1024} KB)")
    except Exception as e:
        print(f"✗ 预览 mp4 生成异常: {e} —— 预览门没有产物")
        return 1
    print("\nANIMATIC 完成: 目检 filmstrip.png / preview.mp4, 再跑全量 render_all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
