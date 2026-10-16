#!/usr/bin/env python3
"""V6.1 音轨装配模板（已实测验证）—— adelay 旁白 + 9 种 SFX + loudnorm 两遍法。

复制到项目根改三处: NARRATION / EVENTS / TARGET。
V6.1 相对 V6 的固化点:
- loudnorm 测量字段 = input_i/input_tp/input_lra/input_thresh/target_offset(冒号前有空格)
- linear 可行性自动判别: LRA≤11 且 (input_tp - input_i) ≤ 13,否则 dynamic
- 动态模式对混合素材收敛偏松(I≈-13):内置确定性后置增益 FINAL_TRIM_DB 校准
  (先用 ebur128 实测一次,把 trim 调到 |I+14|≤0.5 且 TP≤-1.0)
- SFX 库 9 种: swish/thud/pop/chime/crackle/flame/tick + 新增 riser/boom/ticktock
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys as _sys
from pathlib import Path
import sys   # ⚠ 别名 import(import sys as _sys)不绑定裸 sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

# 豆包适配(V8.1.5a)：ffmpeg 走 env_paths 单一事实源(修 R1 违规, 旧版走 PATH)。
# 本脚本是模板, 复制到项目根后 env_paths.py 不在同目录——向上搜索 scripts/ 定位后装载。
try:
    from env_paths import ffmpeg as _ffmpeg
except ImportError:
    _ffmpeg = None
    for _base in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents[:4]]:
        _cand = _base / "scripts" / "env_paths.py"
        if _cand.exists():
            _spec = importlib.util.spec_from_file_location("env_paths", _cand)
            _mod = importlib.util.module_from_spec(_spec)
            _sys.modules["env_paths"] = _mod
            _spec.loader.exec_module(_mod)
            _ffmpeg = _mod.ffmpeg
            break
    if _ffmpeg is None:
        raise ImportError("env_paths.py 未找到——请把技能 scripts/ 目录放到项目上级, 或设置 FFMPEG_PATH 环境变量")

FFMPEG_BIN = str(_ffmpeg())

ROOT = Path(__file__).resolve().parent
if (ROOT / "render_sequence.py").exists():
    # 模板守卫: 本文件是"复制到项目根再跑"的模板。在技能 scripts/ 里直接跑会把
    # audio_build/ 和派生 wav 写进 scripts/(V3.21 审查实录: --help 冒烟即中招)。
    raise SystemExit(f"[模板守卫] mix_audio4.py 须复制到项目根后再运行; 当前 {ROOT} 是技能 scripts/, 在此运行会污染技能目录")
BUILD = ROOT / "audio_build"
SR = 44100
TARGET = 144.0        # ← 总帧数/30
FINAL_TRIM_DB = -1.5  # ← 手动覆盖增益(非 0 时首轮一次性施加, 之后转 auto)。**0 不是"跳过", 0 = 直接走 auto**
                      # (V3.26 修正注释: 旧注释写"0 表示跳过", 但下方 `if trim != 0.0` 的 else 分支就是 auto;
                      #  produce.py 恒把本行替换成 0, 所以生产路径一直是 auto, 手动分支只在人改模板时生效)

NARRATION = [  # ← (mp3 名, 起始秒)
    ("chunk_01", 1.000),
]

EVENTS = [  # ← (音效名, 全局秒, dB)
    ("thud", 0.2, -8),
]

# V6.7 R6 硬预算: 全片音效 ≤20 次(治"音效轰炸"→认知噪音; 转场 0.4s 气口代替音效)。
assert len(EVENTS) <= 20, (
    f"[V6.7 R6] SFX 超预算: {len(EVENTS)} > 20 —— 砍到 ≤20, "
    "转场用 0.4s 呼吸代替音效, 金句前后清声"
)

# V8.1.1 S3: TARGET 与 splice_manifest 总帧交叉校验——TARGET 手填错 = 音频截尾/垫长,
# 旧版要等 qa_deliver 三方对齐(⑧末尾)才发现;本断言把发现点前移到混音入口。
# splice_manifest.json 格式: [[帧目录名, 帧数, 类型], ...](shots+transitions 全计入)
_manifest = ROOT / "splice_manifest.json"
if _manifest.exists():
    _entries = json.loads(_manifest.read_text(encoding="utf-8"))
    _total = sum(e[1] for e in _entries if isinstance(e, (list, tuple)) and len(e) >= 2)
    assert abs(TARGET * 30 - _total) <= 1, (
        f"[V8.1.1] TARGET={TARGET}s×30={TARGET * 30:.0f}帧 ≠ splice_manifest 总帧 {_total} "
        f"—— 先把 TARGET 改成 总帧/30 = {_total / 30:.4f}")


def usable(p: Path) -> bool:
    """V3.16 中断恢复守卫(playbook §51④): 进程被杀/断电会留下全零字节派生 wav,
    旧逻辑"文件存在即跳过"会静默复用坏文件 → ffmpeg 'Invalid data found' 或整段静音。
    派生音频一律"存在且非空"才算可复用。"""
    return p.exists() and p.stat().st_size > 0


def run(cmd, what=""):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed {what}:\n{r.stderr[-800:]}")
    return r


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    sfx = BUILD / "sfx"
    sfx.mkdir(exist_ok=True)

    ins, parts = [], []
    for i, (name, t) in enumerate(NARRATION):
        wav = BUILD / f"{name}.wav"
        if not usable(wav):
            run([FFMPEG_BIN, "-y", "-v", "error", "-i", str(ROOT/"assets"/"audio"/f"{name}.mp3"),
                 "-ar", str(SR), "-ac", "2", str(wav)])
        ins += ["-i", str(wav)]
    # V3.14c 根治"两个配音": 旁白不再 adelay+amix 叠加(stepaudio 时长波动会溢出到下一槽→两段同时响)。
    # 改为每段 apad 补静音到"其场景槽时长"(=下一段起点-本段起点), 再 concat 顺序拼接 → 物理上不可能重叠, 且仍对齐场景边界。
    N = len(NARRATION)
    parts = []
    for i, (name, t) in enumerate(NARRATION):
        slot = (NARRATION[i + 1][1] - t) if i + 1 < N else max(0.5, TARGET - t)
        parts.append(f"[{i}:a]apad=whole_dur={slot:.3f}[a{i}]")
    filt = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(N)) + f"concat=n={N}:v=0:a=1[m]"
    run([FFMPEG_BIN, "-y", "-v", "error", *ins, "-filter_complex", filt,
         "-map", "[m]", "-c:a", "pcm_s16le", str(BUILD/"pre_mix.wav")])

    recipes = {
        "swish":   (["anoisesrc=color=pink:d=0.35:a=0.8"], "highpass=f=1200,lowpass=f=6000,afade=t=in:d=0.05,afade=t=out:st=0.15:d=0.2,volume=-12dB"),
        "thud":    (["sine=f=55:d=0.4"], "afade=t=out:st=0.05:d=0.35,volume=-8dB"),
        "pop":     (["aevalsrc=sin(2*PI*(600+2400*t)*t):d=0.12"], "volume=-14dB"),
        "crackle": (["anoisesrc=color=brown:d=0.5:a=0.9"], "lowpass=f=3000,afade=t=out:st=0.08:d=0.42,volume=-10dB"),
        "flame":   (["anoisesrc=color=pink:d=1.6:a=0.7"], "lowpass=f=900,afade=t=in:d=0.4,afade=t=out:st=0.8:d=0.8,volume=-10dB"),
        "tick":    (["sine=f=1500:d=0.06"], "volume=-16dB"),
        # ---- V6.1 新增 3 种 ----
        "riser":   (["anoisesrc=color=pink:d=0.9:a=0.9"], "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.75,afade=t=out:st=0.78:d=0.12,volume=-11dB"),
        "boom":    (["sine=f=42:d=0.9", "anoisesrc=color=brown:d=0.5:a=0.5"], "[0][1]amix=inputs=2:normalize=0,afade=t=out:st=0.08:d=0.8,volume=-9dB"),
        "ticktock":(["sine=f=1100:d=0.05", "sine=f=800:d=0.05"], "[0]adelay=0|0[a];[1]adelay=180|180[b];[a][b]amix=inputs=2:normalize=0,volume=-15dB"),
    }
    for name, (srcs, af) in recipes.items():
        o = sfx / f"{name}.wav"
        if usable(o):
            continue
        if name == "chime":
            continue
        ii = []
        for s in srcs:
            ii += ["-f", "lavfi", "-i", s]
        if name == "boom" or name == "ticktock":
            run([FFMPEG_BIN, "-y", "-v", "error", *ii, "-filter_complex", af,
                 "-ar", str(SR), "-ac", "2", str(o)])
        else:
            run([FFMPEG_BIN, "-y", "-v", "error", *ii, "-af", af, "-ar", str(SR), "-ac", "2", str(o)])
    chime = sfx / "chime.wav"
    if not usable(chime):
        run([FFMPEG_BIN, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=660:d=0.7",
             "-f", "lavfi", "-i", "sine=f=990:d=0.7",
             "-filter_complex", "[0][1]amix=inputs=2:normalize=0,volume=-16dB",
             "-ar", str(SR), "-ac", "2", str(chime)])

    inputs = ["-i", str(BUILD/"pre_mix.wav")]
    for n, _, _ in EVENTS:
        inputs += ["-i", str(sfx/f"{n}.wav")]
    parts = []
    for idx, (_, when, db) in enumerate(EVENTS, 1):
        ms = round(when*1000)
        parts.append(f"[{idx}:a]adelay={ms}|{ms},volume={db}dB[s{idx}]")
    mi = "[0:a]" + "".join(f"[s{i}]" for i in range(1, len(EVENTS)+1))
    filt = ";".join(parts) + f";{mi}amix=inputs={len(EVENTS)+1}:normalize=0:duration=first,atrim=0:{TARGET}[v]"
    stage1 = BUILD / "loud_stage1.wav"
    run([FFMPEG_BIN, "-y", "-v", "error", *inputs, "-filter_complex", filt,
         "-map", "[v]", "-c:a", "pcm_s16le", str(stage1)], "sfx")

    # ---- 响度目标(一处定义, loudnorm / alimiter / auto-trim 三处共用) ----
    # V3.24: 原来 loudnorm 的 TP、alimiter 的 limit、闭环的 tp_cap 是**三个各自写死的数**
    # (−1.0 / −1.0 / −1.6)。优化器在追一个天花板, 前面的级却在削另一个 → 自我设限且互相打架。
    # qa_deliver 量的是**编码后的 MP4 音轨**, AAC 有 inter-sample 溢出(p16 实测 WAV −1.5→MP4 −0.9,
    # 涨 0.6dB), 所以混音侧的天花板必须比门限低 TP_HEADROOM_DB, 而这个余量要用**实测值**不是保险数。
    TP_GATE_DB = -1.0        # qa_deliver 的削波门
    # 实测 WAV→MP4 真峰上涨量：p24 +0.2 / p25 +0.1 / p26 +0.10 dB（2026-09-29 用 env_paths
    # 解析出的 WinGet ffmpeg 逐片复测）。旧值 0.6 是 §59⑬ 当年在 p16 上测的，**多让了约 0.5 dB**
    # ——响度 I 不受影响，但爆点被压得比允许上限轻半格。取 0.3 = 三部最大值 0.2 + 0.1 余量；
    # 万一某片涨更多，qa_deliver 的 -1.0 门会当场拦下(不会发出削波片)，按当片实测再调这一个数。
    TP_HEADROOM_DB = 0.3     # 实测 WAV→MP4 真峰上涨量(见上；三处共用，别再写第二个数)
    tp_cap = TP_GATE_DB - TP_HEADROOM_DB
    I_TARGET, I_LO, I_HI = -14.0, -14.5, -13.5

    # ---- loudnorm 两遍法(验证版) ----
    p1 = run([FFMPEG_BIN, "-i", str(stage1), "-af",
              f"loudnorm=I={I_TARGET}:TP={tp_cap}:LRA=11:print_format=json", "-f", "null", "-"], "measure")
    m = {k: float(v) for k, v in re.findall(
        r'"(input_i|input_tp|input_lra|input_thresh|target_offset)"\s*:\s*"(-?[\d.]+)"', p1.stderr)}
    if not m:
        # V3.26: 旧版在这里**编造一组测量值**(-16.0/-3.0/8.0/...)喂给第二遍 loudnorm, 然后 exit 0。
        # 解析失败意味着 loudnorm 的输出格式变了或 ffmpeg 不是完整版——那正是本文件开头 R2 红线
        # ("解析失败=抛错, 绝不静默兜底")禁止的事。拿假数字混出来的片子会安静地交付出去。
        raise SystemExit("[FAIL] loudnorm 第一遍没解析出 input_i/input_tp/input_lra —— "
                         "ffmpeg 版本或输出格式变了, 拒绝用编造的测量值混音")
    linear_ok = (m["input_lra"] <= 11) and (m["input_tp"] - m["input_i"] <= 13.0)
    print("measured:", m, "| linear:", linear_ok)
    ln = (f"loudnorm=I={I_TARGET}:TP={tp_cap}:LRA=11:"
          f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m['target_offset']}:linear={'true' if linear_ok else 'false'},"
          # V3.24: alimiter 的 level(自动电平)默认 true, 会**反向回抬增益**
          # (正弦实测 −5.1 → 关掉后 −6.1, 差 1.0dB), 把 limit 的封顶抵消掉。必须显式关掉。
          f"alimiter=level=disabled:limit={tp_cap}dB")
    final = BUILD / "final_mix.wav"
    # V3.24: `apad=whole_dur=TARGET` 原来**只存在于 auto-trim 那条命令里**。于是"round0 就达标"
    # 的片子(响度和峰值一次做对)会 break 掉整个循环 → 音频停在 concat 的自然长度(实测比画面短
    # 170ms) → qa_deliver 判"音画差 > 50ms" FAIL。**垫齐时长是交付要求, 不是增益的副作用。**
    run([FFMPEG_BIN, "-y", "-v", "error", "-i", str(stage1),
         "-af", ln + f",apad=whole_dur={TARGET}",
         "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(final)], "loudnorm")
    # ---- auto-trim 闭环(V7.0): loudnorm 输出后自动测量→算增益→复验,最多 2 轮 ----
    # FINAL_TRIM_DB 手动覆盖仍可用(非 0 时跳过 auto 直接用该值)
    def measure(path):
        r = run([FFMPEG_BIN, "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], "verify")
        # ebur128 先逐行输出后给汇总——必须取最后一次匹配(汇总值),首个是起始静音行
        mi = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", r.stderr)
        mp = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", r.stderr)
        return (float(mi[-1]), float(mp[-1])) if mi and mp else (None, None)

    trim = FINAL_TRIM_DB
    for round_i in range(3):
        i_db, tp_db = measure(final)
        if i_db is None:
            break
        over = tp_db > tp_cap
        ok = (I_LO <= i_db <= I_HI) and not over
        print(f"trim round{round_i}: I={i_db} TP={tp_db} ->", "达标" if ok else ("只压峰" if over else "只提响度"))
        if ok:
            break
        # V3.24 修双重施加: 每轮的 `volume=` 是**作用在上一轮产物上**的, 所以增益必须是**增量**。
        # 旧写法在 trim!=0 的分支里累加历史增益 → 第 2 轮起把已调过的文件再乘一次
        # (p16 把循环从 2 轮放宽到 3 轮才暴露: I 一路 −13.0→−15.5→−17.0, 越调越轻)。
        if trim != 0.0:      # 手动覆盖: 一次性施加, 不迭代
            gain, trim = trim, 0.0
        else:                # auto: 只按 I 算增益, 峰值交给下面那道 limiter 兜
            gain = round(I_TARGET - i_db, 2)
        # V3.24: 旧写法 gain≈0 就 break, 于是"响度已达标、峰值超上限"这一格**永远修不掉**
        # (p16 实录: I=-14.0 正好在目标上、TP=-1.0 > cap=-1.6、gain=0 → break → 成片 max -0.9 判削波)。
        # 超峰值必须能单独走一道"只限幅不加压"的通过。
        if abs(gain) < 0.05 and not over:
            print(f"  增益增量为 0 且 TP 已在上限内 -> 停在 I={i_db} TP={tp_db}")
            break
        tmp = BUILD / "final_trim.wav"
        run([FFMPEG_BIN, "-y", "-v", "error", "-i", str(final),
             "-af", f"volume={gain}dB,alimiter=level=disabled:limit={tp_cap}dB,apad=whole_dur={TARGET}",
             "-c:a", "pcm_s16le", str(tmp)], "trim")
        tmp.replace(final)
    i_db, tp_db = measure(final)
    print(f"final: I={i_db} LUFS, Peak={tp_db} dBFS")
    print(f"final_mix.wav ({TARGET}s, {len(EVENTS)} SFX) — 用以下命令验收:")
    print(f"  ffmpeg -i {final} -af ebur128=peak=true -f null - 2>&1 | grep -E 'I:|Peak:'")
    print(f"  目标: I∈[{I_LO},{I_HI}] LUFS, WAV 峰值≤{tp_cap}(=qa_deliver 门 {TP_GATE_DB} 再留实测 {TP_HEADROOM_DB}dB 编码余量)")


if __name__ == "__main__":
    main()
