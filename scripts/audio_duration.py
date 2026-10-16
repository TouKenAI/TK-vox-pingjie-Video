#!/usr/bin/env python3
"""音频/媒体时长唯一权威解析器(黄金规则 R1-R3, 2026-08-25 事故修复)。

背景: PATH 上的 ffprobe 可能是"无音频解码的精简构建"(--disable-everything 编出来的),
曾导致 mp3 时长被解析成实际一半(13.49s→6.74s), 整条时间轴错位、配音重叠。
此处是"唯一允许的时长来源", 全仓库工时相关模块(mix_audio / make_timeline /
polycheck_v66 / qa 诊断)必须经由本模块取值。

铁规则:
- R1: 只允许 WinGet 完整版 ffprobe 绝对路径, 禁止依赖 PATH 解析
- R2: 解析失败 = 抛错, 绝不静默兜底(不得回退到可能不准的 py 帧扫描)
- R3: 若调用方传纯 Python 估算值, 必须与 ffprobe 交叉校验, 误差 >5% 即抛错
"""
import json
import subprocess
import sys
from pathlib import Path

# 豆包适配(V8.1.5a)：ffprobe/ffmpeg 路径统一走 env_paths 单一事实源——
# 环境变量 FFMPEG_PATH/FFPROBE_PATH 优先 → WinGet 完整版 → PATH(须通过 mp3 解码校验)。
# R1 红线由 env_paths.ffprobe() 强制执行：解不了 mp3 的构建会被拒绝(能力判据，不看程序名)。
from env_paths import ffprobe as _ffprobe_path, ffmpeg as _ffmpeg_path  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

# 兼容旧引用：其他脚本若 import 这两个常量仍可用(等价于 env_paths 解析结果)
WIN_FFPROBE = _ffprobe_path()
WIN_FFMPEG = _ffmpeg_path()


def ffprobe() -> Path:
    """校验并返回 WinGet 完整版 ffprobe 绝对路径。"""
    if not WIN_FFPROBE.exists():
        raise FileNotFoundError(
            f"WinGet 完整版 ffprobe 不存在: {WIN_FFPROBE}\n"
            "请安装完整 ffmpeg(winget install Gyan.FFmpeg)或更新本模块路径常量。")
    return WIN_FFPROBE


def duration(path: str | Path) -> float:
    """任意媒体文件(含 mp3/wav/mp4)的权威时长(秒)。

    失败即抛错(R2), 绝不静默返回 0 或回退 py 帧扫描。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"媒体文件不存在: {p}")
    r = subprocess.run(
        [str(ffprobe()), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(p)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffprobe 测时长失败({p}): {(r.stderr or r.stdout).strip()}")
    try:
        v = float(json.loads(r.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"ffprobe 输出无法解析({p}): {r.stdout.strip()!r}") from exc
    if not v > 0:
        raise RuntimeError(f"ffprobe 返回非正时长({p}): {v}")
    return v


def crosscheck(path: str | Path, py_estimate: float | None,
               rel_err: float = 0.05) -> float:
    """R3: 纯 Python 时长估算必须与 ffprobe 交叉校验后才可用。

    误差 > rel_err(默认 5%)即抛错, 禁止使用可疑的 py 帧扫描结果。
    """
    ref = duration(path)
    if py_estimate is None:
        return ref
    if abs(py_estimate - ref) / ref > rel_err:
        raise RuntimeError(
            f"时长交叉校验失败(误差>{rel_err*100:.0f}%): {path}\n"
            f"  py      = {py_estimate:.3f}s\n"
            f"  ffprobe = {ref:.3f}s\n"
            "禁止使用 py 帧扫描结果作为时长。")
    return ref


if __name__ == "__main__":
    import sys
    demo = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if demo is not None:
        print(f"{demo}: {duration(demo):.3f}s  (源: WinGet ffprobe)")
    else:
        print(f"ffprobe: {ffprobe()}")