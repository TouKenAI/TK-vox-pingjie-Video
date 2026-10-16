#!/usr/bin/env python3
"""豆包适配层：ffmpeg/ffprobe 统一路径解析（R1 红线强制，单一事实源）。

背景：2026-08-25 事故——当时 PATH 上的 ffprobe 是 TRAE 自带的精简构建(--disable-everything,
无音频解码)，mp3 时长被解析成一半，整条时间轴错位、配音重叠。
旧实现(audio_duration/check_timeline_ratio)把 WinGet 绝对路径硬编码进各脚本，
换机即断；qa_deliver/mix_audio4 则直接走 PATH，违反 R1。

本模块规则(优先级从高到低)：
  1. 环境变量 FFMPEG_PATH / FFPROBE_PATH(换机/自定义零配置)
  2. 已知 WinGet 完整版安装路径(本机实测)
  3. PATH 探测(shutil.which)——找到后必须通过"完整版校验"
     (ffprobe -decoders 必须含 mp3 解码；任何无音频解码的精简构建都会被拒，与程序名无关)

校验失败=抛错并给出安装指引，绝不静默回退到可疑二进制(R2 精神)。
所有脚本一律 `from env_paths import ffmpeg, ffprobe` 取路径，禁止裸写 "ffmpeg"。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

# ── 子进程环境（单一事实源）────────────────────────────────────────────
# 2026-09-24 p19 实录：`pipeline ready` 报 "palette_oklch 配色硬门 FAIL"，但该门手动跑 rc=0、
# ΔE 全绿。真因是 Windows 中文环境下 **子进程 Python 拿 GBK 当 stdout**，一执行 `print("✓")`
# 就抛 UnicodeEncodeError 崩掉 → rc!=0 → 编排器把它读成一条**根本不存在的红**。
# 同一处还把其它门的中文输出解码成乱码，连真消息一起埋了。
# 编排器自己 `sys.stdout.reconfigure(...)` 救不到它 spawn 出来的孩子——必须显式传 env。
# 症状不止 pipeline：produce.run_retry() 会先把它当"偶发失败"重试两遍再中止(p18 追过的幽灵失败)。
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

# 已知完整版安装路径(WinGet 默认，多版本并列探测)
_WINGET_LINKS = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Microsoft" / "WinGet" / "Links"
_CANDIDATES = [
    ("FFMPEG_PATH", _WINGET_LINKS / "ffmpeg.exe"),
    ("FFPROBE_PATH", _WINGET_LINKS / "ffprobe.exe"),
]

# 镜像同一子目录下的伴生工具(WinGet 装 ffmpeg 会带 ffprobe)
_WINGET_ALT = {
    "ffmpeg.exe": ["ffmpeg.exe"],
    "ffprobe.exe": ["ffprobe.exe"],
}


def _probe_candidates(name: str) -> list[Path]:
    """返回候选路径列表：环境变量 → WinGet 目录 → 常见安装目录 → PATH。"""
    env_name, win_path = {"ffmpeg.exe": _CANDIDATES[0], "ffprobe.exe": _CANDIDATES[1]}[name]
    out: list[Path] = []
    ev = os.environ.get(env_name, "").strip()
    if ev:
        out.append(Path(ev))
    out.append(win_path)
    # WinGet Links 目录常与工具名一致；再试 cwd 父级(项目自带 ffmpeg 时)
    for base in (Path.cwd(), *Path.cwd().parents[:3]):
        cand = base / name
        if cand.exists():
            out.append(cand)
    which = shutil.which(name)
    if which:
        out.append(Path(which))
    seen: set[Path] = set()
    dedup: list[Path] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return dedup


def _is_full_build(bin_path: Path) -> bool:
    """能力校验：ffprobe -decoders 必须含 mp3 解码器。

    按名字黑名单会失效(2026-09-27 复核：当年那个 TRAE 精简版已随卸载消失，PATH 上只剩
    WinGet 完整版；但机器上还有 hermes / ms-playwright 各自自带的副本)。
    所以判据只能是"你能不能解出 mp3"——装什么新副本都不必再改代码。"""
    try:
        r = subprocess.run(
            [str(bin_path), "-hide_banner", "-decoders"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False
    decoders = r.stdout or ""
    # mp3 解码器标识：mp3float(完整) / mp3(可能精简)；两者任一即视为可解码
    return ("mp3float" in decoders) or (
        "\n A.... mp3 " in decoders or "\n A.... mp3" in decoders)


def ffprobe() -> Path:
    """返回通过完整版校验的 ffprobe 绝对路径，失败抛错。"""
    for cand in _probe_candidates("ffprobe.exe"):
        if cand.exists() and _is_full_build(cand):
            return cand.resolve()
    raise FileNotFoundError(
        "未找到完整版 ffprobe(需含 mp3 解码)。请执行:\n"
        "  winget install Gyan.FFmpeg\n"
        "或设置环境变量 FFPROBE_PATH 指向完整版 ffprobe.exe。")


def ffmpeg() -> Path:
    """返回通过完整版校验的 ffmpeg 绝对路径，失败抛错。"""
    for cand in _probe_candidates("ffmpeg.exe"):
        if cand.exists() and _is_full_build(cand):
            return cand.resolve()
    raise FileNotFoundError(
        "未找到完整版 ffmpeg(需含 mp3 解码)。请执行:\n"
        "  winget install Gyan.FFmpeg\n"
        "或设置环境变量 FFMPEG_PATH 指向完整版 ffmpeg.exe。")


def media_pair() -> tuple[Path, Path]:
    """一次取回 (ffmpeg, ffprobe)，保证来自同一校验源。"""
    return ffmpeg(), ffprobe()


if __name__ == "__main__":
    for tool, fn in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        try:
            p = fn()
            print(f"{tool} -> {p} (完整版校验通过)")
        except FileNotFoundError as e:
            print(f"{tool}: {e}")
