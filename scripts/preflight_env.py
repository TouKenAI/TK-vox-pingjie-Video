#!/usr/bin/env python3
"""豆包适配(V8.1.5a)：生产环境自检器 —— 每部片开工前跑一次, 30 秒内给出全部前提条件结论。

为什么需要: 外部 Agent 软件的工作流假设"环境早已配好"; 豆包每次会话是全新上下文,
开工前必须机械确认: 解释器/ffmpeg/ffprobe/Pillow/numpy/StepFun key/账本文件/技能目录。

检查项:
  E1 Python 版本 ≥3.12(本机 3.14.5)
  E2 ffmpeg + ffprobe 完整版(含 mp3 解码, 走 env_paths 单一事实源)
  E3 Pillow / numpy 可导入
  E4 .env 存在且含 STEPFUN_API_KEY / BASE_URL(不打印 key 本身)
  E5 账本文件存在: metaphors.json / palettes.json / ip_registry.json(缺失仅提示)
  E6 技能目录完整: produce-collage-video/scripts、create-collage-animation/scripts(核心脚本抽查)

用法: python scripts/preflight_env.py
退出码: 0 = 全部通过 / 1 = 存在阻断项(修复后重跑, 禁止带病开工)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # 便捷包自包含:.env/账本/productionN 都在包根(scripts 的父目录)

# 必需脚本清单(存在性; 语法编译则覆盖 scripts/ 下**全部** .py, 见 E6)。
# V3.22 补全: 旧清单停在 V8.1.5a, V3.18-V3.22 新增的门禁(bg_luma/claim_check/asr_alias/
# first_frame_check/asr_final_check)与两个编排器(produce/pipeline)一个都没列, 于是
# "少文件的便携包"自检照样打 ✓ —— 便携包自检验不出缺件就等于没自检。
REQUIRED_SCRIPTS = [
    # 阶段① 文案
    "check_script.py", "claim_check.py", "detect_genre.py", "structure_plan.py",
    "metaphor_ledger.py", "palette_ledger.py", "palette_oklch.py", "novelty_meter.py",
    # 阶段② 旁白
    "stepfun_tools.py", "generate_tts_template.py", "asr_spotcheck.py", "asr_alias.py",
    "word_timing.py", "audio_duration.py",
    # 阶段③④ 语义与素材
    "semantic_check.py", "gen_sut_cards.py", "register_assets.py", "gen_assets.py",
    "cutout_key.py", "make_shapes.py", "make_text_cards.py", "make_cover.py", "make_countup.py",
    # 阶段⑤⑥ 场景与渲前链(render_all 实跑顺序)
    "build_scenes_template.py", "split_beats.py", "first_frame_check.py", "bg_luma_check.py",
    "preflight_v6.py", "check_timeline_ratio.py", "layout_check.py", "animatic.py",
    "text_legibility_check.py",
    "render_sequence.py", "render_all.py",
    # 阶段⑦⑧ 装配与交付
    "gen_transitions.py", "splice_frames.py", "make_transitions.py", "assemble_audio.py",
    "mix_audio4.py", "build_hyperframes_player.py", "produce.py", "pipeline.py",
    "qa_deliver.py", "clutter_check.py", "aesthetic_check.py", "polycheck_v66.py",
    "asr_final_check.py",
    # 支撑
    "env_paths.py", "preflight_env.py", "new_project.py", "style_presets.py",
    "num_equiv.py", "validate_sequence.py", "validate_shot_plan.py",
    "test_layout_parity.py", "test_render_sequence.py",
]


def check(label: str, ok: bool, detail: str = "") -> tuple[bool, str]:
    print(f"  [{'✓' if ok else '✗'}] {label}" + (f" — {detail}" if detail else ""))
    return ok, detail


def main() -> int:
    print("== 豆包生产环境自检 (V8.1.5a) ==")
    fails: list[str] = []

    # E1 Python
    ver = sys.version_info
    ok, _ = check("E1 Python", ver >= (3, 12), f"{ver.major}.{ver.minor}.{ver.micro} @ {sys.executable}")
    if not ok:
        fails.append("E1")

    # E2 ffmpeg/ffprobe 完整版
    try:
        sys.path.insert(0, str(HERE))
        from env_paths import ffmpeg, ffprobe
        ffm = str(ffmpeg())
        fpr = str(ffprobe())
        check("E2 ffmpeg/ffprobe 完整版", True, f"ffmpeg={ffm.split(chr(92))[-1]} | ffprobe={fpr.split(chr(92))[-1]}")
    except Exception as e:
        check("E2 ffmpeg/ffprobe 完整版", False, str(e)[:120])
        fails.append("E2")

    # E3 Pillow / numpy
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
        check("E3 Pillow + numpy", True, f"Pillow {Image.__version__ if hasattr(Image,'__version__') else ''} / numpy {numpy.__version__}")
    except Exception as e:
        check("E3 Pillow + numpy", False, str(e)[:120])
        fails.append("E3")

    # E4 .env / StepFun key
    env_p = ROOT / ".env"
    if env_p.exists():
        key_ok = "STEPFUN_API_KEY=" in env_p.read_text(encoding="utf-8")
        base_ok = "STEPFUN_BASE_URL=" in env_p.read_text(encoding="utf-8")
        check("E4 StepFun 配置", key_ok and base_ok, f".env 存在; key={'有' if key_ok else '缺'} base={'有' if base_ok else '缺'}(key 值不打印)")
        if not (key_ok and base_ok):
            fails.append("E4")
    else:
        check("E4 StepFun 配置", False, ".env 不存在")
        fails.append("E4")

    # E5 账本
    for name in ("metaphors.json", "palettes.json", "ip_registry.json"):
        p = ROOT / name
        if p.exists():
            try:
                json.loads(p.read_text(encoding="utf-8"))
                check(f"E5 {name}", True)
            except Exception as e:
                check(f"E5 {name}", False, f"JSON 损坏: {e}")
                fails.append(f"E5-{name}")
        else:
            check(f"E5 {name}", True, "缺失(仅提示, 非阻断)")

    # E6 必需脚本存在 + 全量语法编译
    missing = [t for t in REQUIRED_SCRIPTS if not (HERE / t).exists()]
    if missing:
        check("E6 必需脚本存在", False, "缺: " + ", ".join(missing[:8]))
        fails.append("E6")
    else:
        # 编译覆盖整个 scripts/:  zip 半路截断/漏拷的文件往往就在这一步现形
        allpy = sorted(p.name for p in HERE.glob("*.py"))
        bad = []
        for tool in allpy:
            r = subprocess.run([sys.executable, "-m", "py_compile", str(HERE / tool)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                bad.append(tool)
        check("E6 必需脚本存在+全量语法", not bad,
              f"必需 {len(REQUIRED_SCRIPTS)} / 目录共 {len(allpy)} 个脚本; 编译失败: {', '.join(bad) if bad else '无'}")
        if bad:
            fails.append("E6")

    renderer = next((p for p in (
        HERE / "render_sequence.py",
        ROOT / "create-collage-animation" / "scripts" / "render_sequence.py",
        ROOT.parent / "create-collage-animation" / "scripts" / "render_sequence.py",
    ) if p.exists()), None)
    check("E7 渲染器存在", renderer is not None, str(renderer) if renderer else "缺失")
    if renderer is None:
        fails.append("E7")

    print()
    if fails:
        print(f"=== FAIL === 阻断项: {', '.join(fails)} —— 修复后重跑, 禁止带病开工 ===")
        return 1
    print("=== PASS === 环境全部就绪, 可以开工 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
