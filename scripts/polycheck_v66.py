#!/usr/bin/env python3
"""V6.6 成片级复核:时间维度与感染力四项检查。

--align?        词级音画对齐回抽: A级语义单元"视觉事件帧" vs "台词念到该句时刻", 偏差>阈值 WARN(默认0.20s≈6帧)
--transition?   转场前后构图承接: 相邻场景末/首帧的主色/明度/主体重心差, 给"延续 vs 需引导"提示(WARN)
--density?      运动密度/呼吸: 每场景动画层密度 + 尾段静置(无新事件>4s)告警
--text?         文字卡文案与原文一致性: 读 <项目>/cards_text.json({卡id:文案}) 与 chunks 原文比对, 非本工程/缺词 WARN

用法:
  py -3.14 scripts/polycheck_v66.py <项目目录> [--align] [--transition] [--density] [--text] [--json-out qa/polycheck-v66.json]
  不带子项开关 = 全开。--text 缺 cards_text.json 时静默跳过并提示。
退出码: 0 全过 / 1 有 WARN(供 CI 告警)
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

from pathlib import Path

import numpy as np
from PIL import Image

import audio_duration  # 唯一权威时长源(黄金规则 R1/R2/R3, 见 audio_duration.py)

STRIP = set("，。？！、：；“”‘’·\\s \n\t\"'()（）!?.,;:")

TRANSITION_FRAMES = 15
FPS = 30
ALIGN_THRESH = 0.20   # 秒
DENSITY_COMFORT = (0.3, 1.2)  # 下限=绝对(层/s); 上限只是**绝对地板**, 实际判据取 max(地板, 本片中位×1.6) —— 见 check_density
TAIL_CROSS = -0.5             # 尾段小于此(=关键帧越过场景末 0.5s 以上)才报, 别把正常漂移留白当事故
STATIC_GAP = 4.0      # 场景尾段无新事件告警阈值(秒)
CENTROID_SHIFT = 0.25  # 主体重心横向位移 / 画布宽 上限
LUM_DELTA = 48.0       # 明度均值差上限 /255
COLOR_DELTA = 140.0    # RGB主色欧氏差上限

warns: list = []
soft_notes: list = []   # 只报不扣分的参考项(字符比例对齐估计等), 见 check_align


def scene_map(proj: Path) -> dict[int, dict]:
    """以 splice_manifest.json 为权威读各场景帧数与全局起始帧(含转场)。"""
    mf = proj / "splice_manifest.json"
    m = {}
    if mf.exists():
        current = 1  # 全局帧号 1 基
        for d, cnt, kind in json.loads(mf.read_text(encoding="utf-8-sig")):
            if kind == "shots":
                mm = re.search(r"s(\d+)$", Path(d).stem)
                if not mm:
                    raise SystemExit(f"[polycheck] manifest 场景目录名无法解析: {d}(期望 frames_sNN 或 sNN)")
                order = int(mm.group(1))
                m[order] = {"file": proj / f"scene_s{order:02d}.json",
                            "frame_count": int(cnt), "start_global": current,
                            "start_index0": current - 1}
                current += int(cnt)
            else:  # trans
                current += int(cnt)
        if m:
            return m
    # fallback:无 manifest 时按 scene 帧数连排 + 固定转场
    files = sorted(proj.glob("scene_s*.json"))
    start, order = 1, 0
    for f in files:
        order += 1
        sc = json.loads(f.read_text(encoding="utf-8-sig"))
        fc = int(sc.get("frame_count") or sc.get("frames") or 0)
        m[order] = {"file": f, "frame_count": fc,
                    "start_global": start, "start_index0": start - 1}
        start += fc
        if order > 1:
            start += TRANSITION_FRAMES
    return m


def chunk_duration(proj: Path, chunk_id: str) -> float:
    """读旁白时长:唯一权威源 = WinGet 完整版 ffprobe(黄金规则 R1/R2)。

    失败(文件缺失/解析失败/时长异常)即抛错, 绝不静默兜底 ——
    2026-08-25 事故根因即旧实现的 py 帧扫描兜底把时长算成一半。
    """
    # V8.1.1: 多目录查找(与 asr_spotcheck 同链)——narr/ narration/ assets/audio/ audio_build/
    for d in ("narr", "narration", "assets/audio", "audio_build"):
        for ext in (".mp3", ".wav"):
            f = proj / d / f"{chunk_id}{ext}"
            if f.exists():
                return audio_duration.duration(f)
    raise FileNotFoundError(f"旁白音频未找到: {chunk_id}(查 narr/ narration/ assets/audio/ audio_build/)")


_BR_L3 = {1: 32, 2: 40, 3: 48, 4: 56, 5: 64, 6: 80, 7: 96, 8: 112, 9: 128,
          10: 160, 11: 192, 12: 224, 13: 256, 14: 320, 0: 0}
_SR = {0: 44100, 1: 48000, 2: 32000}  # MPEG1 采样率索引表;MPEG2/2.5 取半


def mp3_duration_py(path: Path) -> float:
    data = path.read_bytes()
    pos = 0
    if data[:3] == b"ID3":
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | \
               ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        pos = 10 + size
    samples_total = 0.0
    sr_known = None
    while pos + 4 <= len(data):
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        b1, b2 = data[pos + 1], data[pos + 2]
        version = (b1 >> 3) & 0x3
        layer = (b1 >> 1) & 0x3
        bri, sri, pad = (b2 >> 4) & 0xF, (b2 >> 2) & 0x3, (b2 >> 1) & 0x1
        if layer != 1 or bri == 0 or bri == 15 or sri == 3:  # 仅 Layer III, 跳过 free-format
            pos += 1
            continue
        sr = _SR.get(sri, 44100)
        bitrate = _BR_L3[bri] * 1000
        spf = 1152 if version == 3 else 576
        if version != 3:  # MPEG2/MPEG2.5 采样率与帧长系数减半
            sr //= 2
        coeff = 144 if version == 3 else 72
        frame = int(coeff * bitrate / sr) + pad
        sr_known = sr
        samples_total += spf
        pos += max(frame, 4)
    return samples_total / sr_known if sr_known and samples_total else 0.0


# ---------- ① 词级音画对齐 ----------
def base_chunk_id(cid: str) -> str:
    """sut 里可能把同一段音频的若干句拆成 chunk_02b/03c/04b —— 音频文件以基础 id(chunk_02) 命名。"""
    return re.sub(r"[A-Za-z]+$", "", cid) or cid


def norm(s: str) -> str:
    return "".join(ch for ch in s if ch not in STRIP)


def load_word_timings(proj: Path) -> dict[str, list]:
    """可选词级时间戳: proj/qa/asr_words.json(或 word_timings.json)。
    结构:{ "chunk_01": [{"w":"AI","s":0.00,"e":0.28}, ...] }。无则返回空 → 退化到字符比例估计。"""
    for name in ("qa/asr_words.json", "asr_words.json", "qa/word_timings.json", "word_timings.json"):
        f = proj / name
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    return {k: v for k, v in data.items() if isinstance(v, list)}
            except Exception:
                pass
    return {}


def word_time(words: list, text: str) -> float:
    """把某句 text(规范化)映射到词级时间戳的平均朗读时刻;找不到则近似段内中位。"""
    t = norm(text)
    if not words:
        return -1.0
    hits = []
    for k, tm in enumerate(words):
        w = norm(str(tm.get("w", "")))
        if w and w in t:
            hits.append(k)
    if hits:
        return float(np.mean([words[i].get("s", 0) for i in hits]))
    return -1.0


def check_align(proj: Path, smap: dict[int, dict], dur: dict[str, float], sut_unit_extras) -> None:
    sut_file = proj / "sut.json"
    if not sut_file.exists():
        print("  align: 跳过(无 sut.json)"); return
    sut = json.loads(sut_file.read_text(encoding="utf-8-sig"))
    if not (proj / "chunks.json").exists():
        print("  align: 跳过(有 sut.json 但缺 chunks.json, 无原文可比)"); return
    chunks = {c["id"]: c.get("text", "") for c in
              json.loads((proj / "chunks.json").read_text(encoding="utf-8-sig"))}
    words = load_word_timings(proj)
    # V3.28: `rel` 是"这句话在**本段音频**里的位置"，而 visual_sec 是**场内**帧号换算的秒。
    # 一场多段时(p15 起常态)，第二段的声音根本不在场头，中间还隔着混音器的 LEAD/GAP。
    # 旧版少了这一段偏移 → 一场 2~3 段的片子，后半段的每个 A 级单元都被报"漂移 100~300 帧"，
    # p17 实测 55 个单元误报 51 个。按 narration_layout(与混音器同源)把段起点补回来。
    from narration_layout import chunk_lead as _chunk_lead
    try:
        LEADS = _chunk_lead(proj, lambda cid: dur.get(cid, 0.0))
    except SystemExit:
        LEADS = {}
    n = bad = skipped = 0
    for item in sut:
        cid = item.get("chunk")
        base = base_chunk_id(cid)
        full = norm(chunks.get(base, ""))
        dur_t = dur.get(base, 0.0)
        item_sen = norm(item.get("sentence", ""))
        units = [u for u in item.get("units", [])
                 if u.get("grade") == "A" and u.get("scene") is not None]
        if not units or not full:
            continue
        sm0 = smap.get(int(units[0]["scene"][1:]))
        if not sm0:
            continue
        start_sec = sm0["start_index0"] / FPS
        # ① 词级路径: 有 ASR 词级时间戳则用其"念到该词"时刻
        wt = words.get(base, [])
        # ② 退化路径: 字符比例 + 旁白时长, 要求音频可信
        if not wt:
            if dur_t <= 0 or len(full) / dur_t > 14.0:  # 占位/过短音频, 无词级时间戳无法校验
                skipped += len(units)
                continue
        for k, unit in enumerate(units):
            sm = smap.get(int(unit["scene"][1:]))
            if not sm:
                continue
            visual_sec = (sm["start_index0"] + int(unit.get("frame", 0))) / FPS
            sen = unit.get("sentence", "") or item_sen
            if wt:
                rel = word_time(wt, sen)  # 秒
                use_asr = rel >= 0
                if not use_asr:
                    frac = (k + 0.5) / len(units)
                    rel = frac * dur_t if dur_t > 0 else 0.0
            else:
                off = full.find(item_sen[:6]) if item_sen else -1
                if off >= 0:
                    frac = min(1.0, (off + (k + 0.5) / len(units) * max(len(item_sen), len(sen))) / max(len(full), 1))
                else:
                    frac = (k + 0.5) / len(units)
                rel = frac * dur_t
                use_asr = False
            voiced_sec = start_sec + LEADS.get(base, 0.0) + rel
            delta = visual_sec - voiced_sec
            n += 1
            if abs(delta) > ALIGN_THRESH:
                bad += 1
                row = {"check": "align", "scene": unit["scene"], "unit": unit["text"],
                       "visual_sec": round(visual_sec, 2), "voiced_sec": round(voiced_sec, 2),
                       "delta_frames": round(delta * FPS, 1), "thresh_frames": ALIGN_THRESH * FPS,
                       "by": "asr" if use_asr else "char_ratio",
                       "note": "" if use_asr else "字符比例估计,非词级ASR;若漂移偏大请补词级时间戳(可作为基准不扣分)"}
                # V3.28: 这条 note 承诺"不扣分", 但旧版照样塞进 warns → rc=1。
                # 字符比例是把一个单元按字数**均匀撒**在整段里, 天然 ±0.5s, 而阈值只有 6 帧(0.2s):
                # 拿它当硬判据, 对任何一场多段、一段多单元的片子都必然误报(p17 实测 43/55)。
                # 有词级 ASR 时间戳时仍是 WARN; 没有就只报"参考", 不进退出码。
                (warns if use_asr else soft_notes).append(row)
    soft = sum(1 for r in soft_notes if r["check"] == "align")
    if skipped:
        print(f"  align: 校验 {n} 个 A 级单元, 超阈值 {bad-soft} 处(词级 ASR 口径) + 参考 {soft} 处(字符比例, 不扣分); 跳过 {skipped} 个(旁白为占位/过短且无词级时间戳,无法做词级校验)")
    else:
        print(f"  align: 校验 {n} 个 A 级单元, 超阈值 {bad - soft} 处"
              + (f" + 参考 {soft} 处(字符比例, 不扣分)" if soft else ""))
    if n == 0:
        print("  align: 提示: 本机缺可靠旁白音频或 ASR 词级时间戳, 词级对齐未实测。真机 TTS 后可重跑。")


# ---------- ② 转场构图承接 ----------
def check_transition(proj: Path, smap: dict[int, dict]) -> None:
    print("  transition: 检查相邻场景末→首帧承接")
    orders = sorted(smap)
    for i in orders[:-1]:
        a, b = smap[i], smap[i + 1]
        fA = a["file"].parent / "frames" / f"s{i:02d}" / f"frame_{a['frame_count']:04d}.png"
        fB = b["file"].parent / "frames" / f"s{i + 1:02d}" / "frame_0001.png"
        if not fA.exists() or not fB.exists():
            print(f"    边界 {i}→{i+1}: 缺渲染帧, 跳过"); continue
        A = np.asarray(Image.open(fA).resize((135, 180)).convert("RGB")).astype(np.float32) / 255.0
        B = np.asarray(Image.open(fB).resize((135, 180)).convert("RGB")).astype(np.float32) / 255.0
        lum_a, lum_b = float(A.mean()), float(B.mean())
        # V8.1.5a 清理：旧 color_a/color_b 同源脏代码已移除, 直接算主色差
        cdelta = float(np.linalg.norm(A.reshape(-1, 3).mean(0) - B.reshape(-1, 3).mean(0))) * 255.0
        lum = abs(lum_a - lum_b) * 255.0

        def centroid_x(img: np.ndarray) -> float:
            gray = img.mean(2)  # (180,135) 亮度
            xx = gray.sum(0)
            return float((np.arange(135) * xx).sum() / max(xx.sum(), 1e-6))

        cxs = abs(centroid_x(A) - centroid_x(B)) / 135.0
        issues = []
        if cxs > CENTROID_SHIFT:
            issues.append(f"主体重心横移 {cxs:.0%} 画布, 视觉断档")
        if lum > LUM_DELTA:
            issues.append(f"明度突变 {lum:.0f}")
        if cdelta > COLOR_DELTA:
            issues.append(f"主色剧变 Δ={cdelta:.0f}")
        if issues:
            warns.append({"check": "transition", "boundary": f"s{i:02d}→s{i+1:02d}",
                         "detail": "; ".join(issues), "centroid_shift": round(cxs, 2),
                         "lum_delta": round(lum, 1), "color_delta": round(cdelta, 1)})
        else:
            print(f"    ✓ {i}→{i+1} 承接良好(重心{round(cxs,2)}, 明度{round(lum,0)}, 主色Δ{round(cdelta,0)})")


# ---------- ③ 运动密度/呼吸 ----------
def check_density(proj: Path, smap: dict[int, dict]) -> None:
    print("  density: 运动密度与节奏")
    # V3.28: 本门全部判据的分母都是**渲出来的帧数**。首渲前 frame_count=0 → dur=0 →
    # dens 恒为 0.00、tail 恒为 -场景秒数，十场全报"密度低于下限 + 关键帧越过场景末"。
    # 那是"还没渲"被说成"渲坏了"。transition 检查早就有这道护栏，密度检查漏了。
    if all(not sm["frame_count"] for sm in smap.values()):
        print("    未渲染(无 frames_sNN 帧数) → 密度/尾段静置跳过；渲染后复跑本工具")
        return
    rows = []
    for order in sorted(smap):
        sm = smap[order]
        sc = json.loads(sm["file"].read_text(encoding="utf-8-sig"))
        fc = sm["frame_count"]
        dur = fc / FPS
        layers = sc.get("layers", [])
        animated = []
        for l in layers:
            ks = l.get("keyframes", [])
            if len(ks) < 2:
                continue
            def sig(kf):
                return (round(float(kf.get("x", 0)), 3), round(float(kf.get("y", 0)), 3),
                        round(float(kf.get("scale", 1)), 3), round(float(kf.get("rotation", 0)), 3))
            s0 = sig(ks[0])
            if any(sig(kf) != s0 for kf in ks[1:]):
                animated.append(l.get("id", "?"))
        # 特效(radial-burst 粒子爆发等)同为强视觉动态, 与动画层同口径计入密度;
        # 旧判据只数 layers, 会把"靠特效爆点"的场景误判为静态(见 2026-08-25 收口核查 s03/s06/s07)。
        fx = sc.get("effects", [])
        animated += [f"fx:{e.get('type', 'effect')}" for e in fx if isinstance(e, dict)]
        dens = len(animated) / dur if dur else 0
        # 尾段静置:最后事件帧
        last_ev = max((max(k["frame"] for k in l.get("keyframes", []) if isinstance(k, dict))
                       for l in layers if isinstance(l.get("keyframes"), list) and l["keyframes"]), default=0)
        tail = (fc - last_ev) / FPS
        rows.append((order, len(animated), dens, tail))

    # V3.21 校准: 上限旧值取**绝对** 1.2 层/s。dens=动画层数/场景秒数 → 场切得越短分越高,
    # 量的是"这场多短"不是"这屏多挤"(挤由 clutter_check 按像素判)。实测五片:
    #   p10(83.0) 0 告警 · p14(84.3 频道新高) 8/11 告警 · p13(78.3 最低) 17/20 告警
    # ——p10 与 p14 同为好片却差 8 倍, 说明绝对阈值无判别力。改"相对本片中位数"(同 V3.13
    # aesthetic_check 去风格偏置的做法), 并保留绝对下界防止整片都很静时把正常场当离群。
    med = float(np.median([r[2] for r in rows])) if rows else 0.0
    hi = max(DENSITY_COMFORT[1], 1.6 * med)
    for order, nan, dens, tail in rows:
        note = []
        if dens > hi:
            note.append(f"密度 {dens:.2f} 层/s > 本片上限 {hi:.2f}(中位 {med:.2f}×1.6),相对离群")
        elif dens < DENSITY_COMFORT[0]:
            note.append(f"密度 {dens:.2f}<下限,略静态")
        if tail > STATIC_GAP:
            note.append(f"尾段静置 {tail:.1f}s 无新事件")
        elif tail < TAIL_CROSS:
            # 负尾段=最后一个关键帧落在场景末之后 → 切点时元素仍在运动中(帧被渲掉, 硬切带残影)
            note.append(f"关键帧越过场景末 {-tail:.1f}s, 切点仍在运动中")
        if note:
            warns.append({"check": "density", "scene": f"s{order:02d}",
                         "animated": nan, "dens": round(dens, 2),
                         "tail_static": round(tail, 1), "detail": "; ".join(note)})
            print(f"    ! s{order:02d} " + "; ".join(note))
        else:
            print(f"    ✓ s{order:02d} 密度 {dens:.2f} 层/s, 尾段 {tail:.1f}s")


# ---------- ④ 文字卡文案一致性 ----------
def check_text(proj: Path) -> None:
    cf = proj / "cards_text.json"
    if not cf.exists():
        print("  text: 跳过(缺 cards_text.json 协议文件)"); return
    cards = json.loads(cf.read_text(encoding="utf-8-sig"))
    chunks_f = proj / "chunks.json"
    if not chunks_f.exists():
        print("  text: 跳过(缺 chunks.json)"); return
    corpus = "".join(c["text"] for c in json.loads(chunks_f.read_text(encoding="utf-8-sig")))
    corpus_clean = "".join(ch for ch in corpus if ch not in "，。？！、：；“”‘’· ")
    for cid, txt in cards.items():
        t = "".join(ch for ch in txt if ch not in "，。？！、：；“”‘’· ")
        missing = [ch for ch in t if len(t) > 1 and ch not in corpus_clean]
        # 只要"连续2字词"都存在即可(去除单字符噪声)
        segs = [w for w in t.split("\n")]
        for seg in segs:
            words = [ch for ch in seg if not ch.isdigit() and ch not in "＝≠→✓✔"]
            if not words:
                continue
            hits = []
            for i in range(len(words) - 1):
                bigram = words[i] + words[i + 1]
                if bigram in corpus_clean:
                    hits.append(i)
            # 若核心二元组大多命中, 视为一致
            if words and (len(words) == 1 or len(hits) < max(1, len(words) // 2)):
                warns.append({"check": "text", "card": cid, "text": txt,
                             "missing_vs_src": True})
    print(f"  text: 校验 {len(cards)} 张卡, 差异 {sum(1 for w in warns if w['check']=='text')} 处")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    for name in ("align", "transition", "density", "text"):
        ap.add_argument(f"--{name}", action="store_true", dest=f"do_{name}")
    ap.add_argument("--json-out", default="qa/polycheck-v66.json")
    args = ap.parse_args()
    proj = Path(args.project)
    smap = scene_map(proj)
    if not smap:
        # V3.26: 空项目下 smap 为空 → 四项检查各产出 0 条 WARN → 旧版 `return 1 if warns else 0`
        # 给 rc=0。"无事可查"被当成"全部通过", 项目路径写错时本门完全骗人。
        print(f"polycheck_v66: FAIL —— {proj} 下读不到任何场景(scene_s*.json/frames_s*)，"
              f"四项检查无事可执行, 这不是通过", file=sys.stderr)
        return 1
    dump = {}
    reports = {"align": [], "transition": [], "density": [], "text": []}
    if args.do_align or not (args.do_transition or args.do_density or args.do_text):
        dur = {}
        if (proj / "chunks.json").exists():
            for c in json.loads((proj / "chunks.json").read_text(encoding="utf-8-sig")):
                dur[c["id"]] = chunk_duration(proj, c["id"])
        check_align(proj, smap, dur, None)
    if args.do_transition or not (args.do_align or args.do_density or args.do_text):
        check_transition(proj, smap)
    if args.do_density or not (args.do_align or args.do_transition or args.do_text):
        check_density(proj, smap)
    if args.do_text or not (args.do_align or args.do_transition or args.do_density):
        check_text(proj)

    for w in warns:
        reports.setdefault(w["check"], []).append(w)
    reports["align_reference"] = soft_notes   # 留档可查, 但不进退出码
    out = proj / args.json_out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\npolycheck_v66: WARN {len(warns)} 处 (report→{args.json_out})")
    for w in warns:
        print("  WARN", json.dumps(w, ensure_ascii=False))
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())