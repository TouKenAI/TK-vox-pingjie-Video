#!/usr/bin/env python3
"""V7.0 一键交付门禁 —— 成片不出这七道断言不算做完。

用法: python qa_deliver.py <项目目录> [--mp4 输出.mp4]
自动: ①三方对齐(帧数=manifest和, 音画差≤50ms) ②双流齐全 ③音轨电平(mean∈[-24,-14], max≤-1)
     ④两级帧审计(白名单程序化生成自 manifest) ⑤抽帧回抽(n↔frame_(n+1), <5/255)
     ⑥首帧=封面(存在 cover.png 时) ⑦报告落 qa/deliver-report.json
退出码 0=全过 / 1=有 HARD 失败。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

import tempfile
from pathlib import Path

from PIL import Image, ImageChops

# 豆包适配(V8.1.5a)：ffmpeg/ffprobe 一律走 env_paths 单一事实源(修 R1 违规——
# 旧版走 PATH, 若被 TRAE 精简版劫持则交付门禁全部时长/抽帧断言静默失真)。
from env_paths import ffmpeg as _ffmpeg, ffprobe as _ffprobe, CHILD_ENV


def sh(cmd, **kw):
    # 默认按 UTF-8 解子进程输出并强制子进程用 UTF-8 写：中文环境下不设这两项，
    # 被检工具的 ✓ 会直接把它打崩，rc 于是变成一条**根本不存在的红**。
    kw.setdefault("env", CHILD_ENV)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main() -> int:
    ffmpeg_bin = str(_ffmpeg())
    ffprobe_bin = str(_ffprobe())
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--mp4", type=Path, default=None)
    ap.add_argument("--samples", type=int, default=10)
    a = ap.parse_args()
    root = a.project.resolve()
    mp4 = a.mp4
    if mp4 is None:
        mp4s = sorted((root / "output").glob("*.mp4")) if (root / "output").exists() else []
        mp4 = mp4s[0] if mp4s else None

    # ⓪ 版本漂移断言(V7.1, P12 事故机制化): 源文件 mtime 晚于成片 = 改源未重渲, FAIL。
    # V8.1.1 补: 该断言此前只在文档承诺、未落代码——P15 复盘实测场景重生成后门禁无反应, 故落地。
    if mp4 is not None:
        mp4_mtime = Path(mp4).stat().st_mtime
        stale = []
        for pat in ("scene_s*.json", "splice_manifest.json", "cards_text.json"):
            stale += [q for q in sorted(root.glob(pat)) if q.stat().st_mtime > mp4_mtime + 2]
        if stale:
            print("=== FAIL === 改源未重渲(V7.1 ⓪道 mtime 断言):")
            for q in stale[:8]:
                print("  ", q.name, "mtime 晚于成片——重渲受影响场景后重跑 qa_deliver")
            return 1
        print("✓ ⓪ mtime: 源文件均早于成片, 无版本漂移")
    if not mp4 or not mp4.exists():
        sys.exit("FAIL: 找不到成片 mp4(--mp4 指定)")
    fails, warns = [], []
    report = {"mp4": str(mp4)}

    # ① 三方对齐 + ② 双流
    mf = root / "splice_manifest.json"
    # V3.26: 缺 manifest 以前是 `manifest_total=None` → ①道帧数断言静默不跑, 交付照样 PASS。
    # "门禁因缺文件而被跳过"是 render_all 已经修过的同一类病, 这里同样按 FAIL 处理。
    if mf.exists():
        manifest_total = sum(int(c) for _, c, _ in json.loads(mf.read_text(encoding="utf-8-sig")))
    else:
        manifest_total = None
        fails.append("缺 splice_manifest.json —— 三方对齐断言无法执行, 不许当 PASS")
    probe = sh([ffprobe_bin, "-v", "error", "-show_entries",
                "stream=codec_type,duration,nb_frames", "-of", "json", str(mp4)])
    streams = json.loads(probe.stdout)["streams"]
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    au = next((s for s in streams if s["codec_type"] == "audio"), None)
    if not v or not au:
        fails.append(f"双流缺失: video={bool(v)} audio={bool(au)}")
    else:
        nb = int(v.get("nb_frames", 0))
        report["nb_frames"] = nb
        if manifest_total is not None and nb != manifest_total:
            fails.append(f"帧数 {nb} ≠ manifest {manifest_total}")
        gap_ms = abs(float(v["duration"]) - float(au["duration"])) * 1000
        report["av_gap_ms"] = round(gap_ms, 1)
        if gap_ms > 50:
            fails.append(f"音画差 {gap_ms:.0f}ms > 50ms")

    # ③ 音轨电平
    vd = sh([ffmpeg_bin, "-i", str(mp4), "-map", "0:a", "-af", "volumedetect", "-f", "null", "-"]).stderr
    mv = re.search(r"mean_volume:\s*(-?[\d.]+)", vd)
    xv = re.search(r"max_volume:\s*(-?[\d.]+)", vd)
    if mv and xv:
        mean_v, max_v = float(mv.group(1)), float(xv.group(1))
        report["audio_mean"] = mean_v
        report["audio_max"] = max_v
        if not (-24 <= mean_v <= -14):
            fails.append(f"音轨 mean {mean_v}dB 出带[-24,-14]")
        if max_v > -1.0:
            fails.append(f"音轨 max {max_v}dB 削波风险")

    # ④ 两级帧审计(白名单程序化生成)
    bounds, cur = [], 0
    if mf.exists():
        for d, cnt, kind in json.loads(mf.read_text(encoding="utf-8-sig")):
            if kind == "trans":
                bounds.append((cur, cur + cnt))
            cur += int(cnt)

    # V8.1.1 补: 封面淡出窗([0,25))为设计内跳变——封面=第一帧(V7.0)在 f0-22 淡出必然逐帧大变,
    # 另一会话去 i<=24 硬编码时误伤此场景;以有名豁免恢复,并注明出处(非任意魔法数)。
    bounds.append((0, 25))

    def in_trans(i):
        return any(x <= i < y for x, y in bounds)  # 白名单 = manifest 转场区间 + 封面淡出窗

    sc = sh([ffmpeg_bin, "-v", "info", "-i", str(mp4),
             "-vf", "select='gte(scene,0.32)',showinfo", "-f", "null", "-"]).stderr
    for m in re.finditer(r"n:\s*(\d+) pts", sc):
        f = int(m.group(1))
        (warns if in_trans(f) else fails).append(f"scene跳变@{f}" + ("(白名单内,正常)" if in_trans(f) else ""))
    raw = subprocess.run([ffmpeg_bin, "-v", "error", "-i", str(mp4), "-vf", "fps=10,scale=54:72",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    g = raw.stdout
    n = len(g) // (54 * 72)
    prev = None
    hard_frames = 0
    # V3.26: 曝光/清晰度/ΔY 三项**改为汇总一行**。它们与好不好看无判别力(清晰度告警与审美相关仅
    # +0.10, 且审美最低的两部片报警最少), 属第 6 个弱代理门; 但每次交付吐 500+ 行会把真告警埋掉。
    # 保留测量值供人判读, 不再逐帧刷屏。硬门(黑帧/爆闪/纯色空白帧)一律不动。
    n_expo = n_soft = n_dy = 0
    max_mean, min_grad = 0.0, 999.0
    for i in range(n):
        ch = g[i * 54 * 72:(i + 1) * 54 * 72]
        mean = sum(ch) / len(ch)
        gf = i * 3
        if mean < 16 and not in_trans(gf):
            fails.append(f"黑帧~帧{gf}")
            hard_frames += 1
        if mean > 235:
            fails.append(f"爆闪~帧{gf}")
            hard_frames += 1
        # V8.1.1 补(P15 事故机制化): 空白帧像素门——camera kf 缺 opacity 曾把整帧 blend 成纯 fill,
        # mean/stdev 双低的"纯色帧"逃过黑帧检查;灰度 stddev<6 即纯色(噪声底), 非转场/封面区即 FAIL。
        var = sum((b - mean) ** 2 for b in ch) / len(ch)
        if var ** 0.5 < 6.0 and not in_trans(gf):
            fails.append(f"纯色空白帧~帧{gf}(stddev={var ** 0.5:.1f})")
            hard_frames += 1
        # V8.1.3 视觉质量基线(参考资料): 曝光带(不过曝不欠曝) + 清晰度(梯度下限)
        max_mean = max(max_mean, mean)
        if (mean < 25 or mean > 215) and not in_trans(gf):
            n_expo += 1
        grad = sum(abs(ch[j + 1] - ch[j]) for j in range(0, len(ch) - 1, 3)) / (len(ch) / 3)
        min_grad = min(min_grad, grad)
        if grad < 6.0 and not in_trans(gf):
            n_soft += 1
        if prev is not None and abs(mean - prev) > 60 and not in_trans(gf):
            n_dy += 1
        prev = mean

    # 唯一有行动价值的两个数: 离爆闪硬门还剩多少余量, 以及最软的一帧有多软(汇总, 不刷屏)
    if n_expo or n_soft or n_dy:
        warns.append(
            f"画面统计(仅参考, 非缺陷): 曝光越界 {n_expo} 帧(最高均色 {max_mean:.0f}, 距爆闪硬门 235 剩 {235 - max_mean:.0f})"
            f" · 低梯度 {n_soft} 帧(最低 {min_grad:.1f}) · ΔY {n_dy} 帧"
            + ("  ⚠ 余量 <15 说明本片地色偏亮, 换浅色底前先看这个数" if 235 - max_mean < 15 else ""))

    # ⑤ 抽帧回抽
    frames_dir = root / "frames"
    mx = 0.0
    if frames_dir.exists() and v:
        total = int(v.get("nb_frames", 0))
        step = max(1, total // a.samples)
        for k in range(a.samples):
            n0 = min(total - 2, k * step)  # V8.1.1: 抽帧从 0 起, 覆盖开头钩子区
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp = tf.name
            sh([ffmpeg_bin, "-y", "-v", "error", "-i", str(mp4),
                "-vf", f"select='eq(n,{n0})'", "-vsync", "0", "-frames:v", "1", tmp])
            src = frames_dir / f"frame_{n0 + 1:04d}.png"  # 0基/1基映射
            if src.exists():
                x = Image.open(tmp).convert("RGB").resize((108, 144))
                y = Image.open(src).convert("RGB").resize((108, 144))
                d = sum(sum(t) for t in ImageChops.difference(x, y).getdata()) / (108 * 144 * 3)
                mx = max(mx, d)
            Path(tmp).unlink(missing_ok=True)
    report["roundtrip_max"] = round(mx, 2)
    if mx >= 5:
        fails.append(f"抽帧回抽 max {mx:.2f} ≥5/255")

    # ⑥ 首帧=封面
    covers = sorted((root / "assets" / "source").glob("cover*.png")) if (root / "assets" / "source").exists() else []
    cover = covers[0] if covers else None
    if cover is not None and cover.exists() and frames_dir.exists():
        f1 = frames_dir / "frame_0001.png"
        if f1.exists():
            x = Image.open(f1).convert("RGB").resize((108, 144))
            y = Image.open(cover).convert("RGB").resize((108, 144))
            d = sum(sum(t) for t in ImageChops.difference(x, y).getdata()) / (108 * 144 * 3)
            report["cover_first_frame_diff"] = round(d, 2)
            if d >= 20:  # cover 源图与成片画布比例/缩放不同(cover 6张版 600x800→1080x1440),P95 缩放误差约 15
                fails.append(f"首帧≠封面(diff {d:.2f}>=20)")

    report["fails"] = fails
    report["warns"] = warns
    (root / "qa").mkdir(exist_ok=True)
    (root / "qa" / "deliver-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"成片: {mp4.name} | 帧数 {report.get('nb_frames')} | 音画差 {report.get('av_gap_ms')}ms | "
          f"音轨 {report.get('audio_mean')}dB/max {report.get('audio_max')}dB | 回抽 max {report.get('roundtrip_max')} | "
          f"首帧封面 diff {report.get('cover_first_frame_diff', 'n/a')}")
    for w in warns:
        print("WARN:", w)
    if fails:
        print("=== DELIVER FAIL ===")
        for f in fails:
            print("  ✗", f)
        return 1
    print("DELIVER PASS: 七道断言全过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
