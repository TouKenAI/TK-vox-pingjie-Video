#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.8 一键编排器（②）：从"场景 JSON 已生成"跑到"成片+交付+拥挤度检测"。

流程: split_beats → render_all → gen_transitions(硬切为主) → splice → check_timeline_ratio
      → mix_audio(自动或读 qa/events.json) → 编码(带重试) → qa_deliver → clutter_check
      → aesthetic_check → asr_final_check(V3.18 整片 ASR 硬门, FAIL 不交付)
前置: 项目已有 chunks.json + assets/audio/*.mp3 + scene_s*.json。

用法:
  py produce.py <项目> [--at 4,8] [--dipblack-at 8] [--jobs 2] [--threshold 8] [--skip-render]
      [--cq-at 84.1] [--skip-asr]
退出码 0=成片通过 qa_deliver + 整片 ASR 复核。
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

# 子进程必须强制 UTF-8：中文环境下子进程默认 GBK stdout，门一 print ✓ 就崩 → 被读成假红，
# run_retry 还会先当"偶发失败"重试两遍再中止(p18 追过的幽灵失败 / p19 实录于 pipeline)。
from env_paths import CHILD_ENV

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(cmd, what):
    print("\n=== " + what + " ===")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=CHILD_ENV)
    out = (r.stdout or "") + (r.stderr or "")
    print("\n".join(out.strip().splitlines()[-6:]))
    if r.returncode != 0:
        print("❌ " + what + " 失败, 中止")
        sys.exit(1)
    return out


def run_retry(cmd, what, tries=2):
    for k in range(tries):
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=CHILD_ENV)
        if r.returncode == 0:
            print("\n=== " + what + " ===")
            print("\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-4:]))
            return (r.stdout or "") + (r.stderr or "")
        print("⚠ " + what + " 第" + str(k + 1) + "次失败(偶发?), 重试…")
    print("❌ " + what + " 多次失败, 中止")
    sys.exit(1)


def verify_ledgers(proj):
    """V3.35 交付前硬门：本片必须已登记进**两本跨片账本**。

    这两本账是"防撞车"的唯一依据——配色不登记，下一部的 `palette_ledger check` 就比不到它；
    概念不登记，`metaphor_ledger check` 同理。登记此前**全靠我手工做**，而它已经漏过一次：
    2026-09-27 实测 p22 在 `palettes.json` 里、**不在 `metaphors.json` 里**。
    手工纪律 + 没有门 = 迟早漏，漏了以后没有任何一处会红。

    判据是结构化的（palettes 查键、metaphors 查 `films` 列表），不用子串——
    "production2" 是 "production23" 的子串，按子串判会把没登记的判成登记过。
    """
    roots = [proj] + list(proj.parents)
    found = {}
    for name in ("palettes.json", "metaphors.json"):
        for base in roots:
            p = base / name
            if p.exists():
                found[name] = p
                break
    missing = []
    for name in ("palettes.json", "metaphors.json"):
        p = found.get(name)
        if p is None:
            missing.append(f"{name}(账本文件本身不存在，工作区根应有)")
            continue
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        if name == "palettes.json":
            ok = proj.name in d
        else:
            ok = any(proj.name in (v.get("films") or []) for v in d.values() if isinstance(v, dict))
        if not ok:
            missing.append(name)
    if missing:
        raise SystemExit(
            f"[FAIL] {proj.name} 未登记进跨片账本: {', '.join(missing)}\n"
            f"  → 不登记，下一部的撞车检查就比不到本片（p22 的隐喻账就是这么漏的）。\n"
            f"  → 补登记：\n"
            f"     py -3.14 scripts/palette_ledger.py add <本片四色 hex> --film {proj.name}\n"
            f"     py -3.14 scripts/metaphor_ledger.py add <本片概念词...> --film {proj.name}\n"
            f"     (概念词直接读 {proj}/qa/concepts.txt，一行一个)")
    print("✓ 跨片账本已登记（palettes + metaphors）")


def verify_frames_match_scenes(proj):
    """V3.16 顺序守卫(playbook §51⑤): --skip-render 复用已有帧前, 校验帧是否由当前场景 JSON 渲出。
    渲染后若又跑过 split_beats / 改过 build_scenes, 帧与 JSON 会错位 → 成片画面与门禁结论全部失真。
    无戳的历史项目只告警不阻断(向后兼容)。

    V3.34 加严: 同时校验**资产级指纹**(.fp)。旧判据只看场景 JSON，于是"重抠了一个道具 / 重抽了
    一张背景"完全隐形——p23 实录 prop_phone_hero 重抠后 bbox 1220→1226、bg_store_finale 整张换掉，
    JSON 一个字没改。现在这两类都会被拦下。"""
    import hashlib
    stamps = proj / "qa" / "frame_stamps"
    stale, unverified, asset_stale = [], [], []
    for scene in sorted(proj.glob("scene_s*.json")):
        out = proj / f"frames_{scene.stem.split('_')[-1]}"
        if not out.exists():
            continue
        stamp = stamps / f"{out.name}.hash"
        if not stamp.exists():
            unverified.append(out.name)
            continue
        if stamp.read_text(encoding="utf-8").strip() != hashlib.sha256(scene.read_bytes()).hexdigest()[:16]:
            stale.append(out.name)
            continue
        fp_file = stamps / f"{out.name}.fp"
        if fp_file.exists():
            try:
                from scene_fingerprint import fingerprint, frames_complete
                if not frames_complete(out, scene):
                    asset_stale.append(f"{out.name}(帧数不齐)")
                elif fp_file.read_text(encoding="utf-8").strip() != fingerprint(scene, proj)[:16]:
                    asset_stale.append(out.name)
            except ImportError:
                pass          # 指纹模块不在（旧便携包）→ 退回只看 JSON 戳，不假装更严
    if unverified:
        print(f"WARN: {len(unverified)} 场无渲染戳({','.join(unverified[:4])}…), 无法校验帧↔JSON 一致性(历史项目正常)")
    if asset_stale:
        raise SystemExit(f"[FAIL] {len(asset_stale)} 场的**素材/渲染器**在渲染之后被改过: {','.join(asset_stale)}\n"
                         f"  → 帧还是旧素材渲的(重抠道具/重抽背景/改渲染器都不动场景 JSON, 只看 JSON 的旧判据查不出来)。\n"
                         f"  → 跑 `py scripts/render_all.py {proj} --jobs 4`(增量, 只重渲这些场), 再 --skip-render")
    if stale:
        raise SystemExit(f"[FAIL] {len(stale)} 场场景 JSON 比其帧更新: {','.join(stale)}\n"
                         f"  → 帧是旧的(split_beats/改场后未重渲)。先跑 "
                         f"`py render_sequence.py scene_sNN.json --output frames_sNN --overwrite` 重渲这些场, 再 --skip-render")


def _narration_plan(project: Path, starts, scene_nos):
    """NARRATION 按 chunks.json 的 scene 归属摆段。

    旧版写死 `chunk_(i+1) @ starts[i]` —— 等于假设"第 N 段旁白 = 第 N 场"。p15 第一次出现
    一场两段(S02=chunk_02+03, S03=chunk_04+05), 于是从 S02 起整条时间轴逐段后移,
    尾部金句 chunk_16 与 CTA chunk_17 **根本没进混音**; 成片只是"结尾没词", 全程无人报错。

    V3.26 补: 场号改从 splice_manifest 的真实 `frames_sNN` 名取, **不再用"第 i 个槽位 = 第 i+1 场"**。
    上一版只修了 chunk↔场, 槽位↔场号仍是按位置推 —— 场号一旦有洞(删过场/重编号), 旁白会整条
    静默错位一格, 和 p15 是同一类病。现在场号有洞会直接 FAIL, 不会错着渲完。"""
    import re as _re
    from audio_duration import duration as _adur
    if len(scene_nos) != len(starts):
        raise SystemExit(f"[FAIL] 场数不匹配: manifest 有 {len(scene_nos)} 场({scene_nos}), "
                         f"scene_starts 有 {len(starts)} 个起点 —— 两者必须由同一次 gen_transitions 生成")
    chunks = json.loads((project / "chunks.json").read_text(encoding="utf-8-sig"))
    by_scene: dict[int, list] = {}
    for c in chunks:
        m = _re.search(r"(\d+)", str(c.get("scene", "")))
        if not m:
            raise SystemExit(f"[FAIL] chunks.json {c.get('id')} 缺 scene 字段, 无法决定它在混音里的起点")
        by_scene.setdefault(int(m.group(1)), []).append(c["id"])
    plan = []
    # V3.28: LEAD/GAP 从 narration_layout 取——polycheck_v66 的画音对齐检查用同一组常数，
    # 两边各写一份的话，改混音器不会通知检查器，检查器就会开始给"正确对齐"的片子挑错。
    from narration_layout import GAP as _GAP, LEAD as _LEAD
    for num, sc0 in zip(scene_nos, starts):
        t = float(sc0) + _LEAD
        for cid in by_scene.get(num, []):
            mp3 = project / "assets" / "audio" / f"{cid}.mp3"
            if not mp3.exists():
                raise SystemExit(f"[FAIL] 缺旁白音频 {mp3} —— 先跑 pipeline tts")
            plan.append((cid, round(t, 3)))
            t += _adur(mp3) + _GAP
    missing = sorted({c["id"] for c in chunks} - {cid for cid, _ in plan})
    if missing:
        raise SystemExit(f"[FAIL] 旁白段 {missing} 的 scene 编号对不上任何场(现有场号 {scene_nos}), 不会进混音")
    return plan


def _patch(src: str, marker: str, repl: str) -> str:
    """字符串打补丁必须校验命中。mix_audio4.py 那两行一旦被重排/改默认值, `.replace()` 会静默
    不生效, 项目里的 mix_audio.py 就悄悄留着 TARGET=144.0 —— 混音长度错了也没人报。"""
    if marker not in src:
        raise SystemExit(f"[FAIL] mix_audio4.py 里找不到锚点 {marker!r} —— 模板被改过, 拒绝用错参数混音")
    return src.replace(marker, repl)


def _sub(src: str, pattern: str, repl: str, what: str) -> str:
    out = re.sub(pattern, repl, src, count=1, flags=re.S)
    if out == src:
        raise SystemExit(f"[FAIL] mix_audio4.py 里没替换掉 {what} —— 模板结构变了, 拒绝带着旧值混音")
    return out


def build_mix(project, starts, at_set, target_s, scene_nos):
    s = (HERE / "mix_audio4.py").read_text(encoding="utf-8")
    s = _patch(s, "TARGET = 144.0        # ← 总帧数/30", "TARGET = " + str(target_s))
    s = _patch(s, "FINAL_TRIM_DB = -1.5", "FINAL_TRIM_DB = 0")
    plan = _narration_plan(project, starts, scene_nos)
    narr = "NARRATION = [\n" + ",\n".join('    ("%s",%.3f)' % (cid, t) for cid, t in plan) + "\n]"
    s = _sub(s, r"NARRATION = \[.*?\n\]", narr, "NARRATION")
    ef = project / "qa" / "events.json"
    if ef.exists():
        raw = [list(e) for e in json.loads(ef.read_text(encoding="utf-8"))]
        # V3.28: 允许按 **(音效名, 场号, 场内秒, dB)** 写——音效属于"那一下动作", 不属于成片时间轴坐标。
        # 转场时长要等 gen_transitions 之后才知道，让作者先算全局秒等于逼他把音效挂在场景边界上
        # (p17 的 10 个事件音全部落在场边界，卡片拍下/锁落下/数字滚到一个都没有声)。
        start_of = dict(zip(scene_nos, [float(x) for x in starts]))
        ev = []
        for e in raw:
            if len(e) == 4:
                name, sc, local, db = e
                if int(sc) not in start_of:
                    raise SystemExit(f"[FAIL] events.json 第 {sc} 场不在 splice_manifest 的场号里"
                                     f"(现有 {sorted(start_of)}) —— 这条音效会被丢掉还是报错，必须说清")
                ev.append((str(name), round(start_of[int(sc)] + float(local), 3), int(db)))
            elif len(e) == 3:
                ev.append((str(e[0]), float(e[1]), int(e[2])))
            else:
                raise SystemExit(f"[FAIL] events.json 条目格式应为 (名,场号,场内秒,dB) 或 (名,全局秒,dB)，实得 {e}")
    else:
        ev = [("pop", starts[0] + 1.0, -12)]
        for k in range(1, len(starts)):
            ev.append(("swish" if (k in at_set) else "pop", starts[k] + (0.0 if k in at_set else 1.2), -13))
        ev = ev[:20]
    evs = "EVENTS = [\n" + ",\n".join('    ("%s",%.2f,%d)' % (n, t, d) for n, t, d in ev) + "\n]"
    s = _sub(s, r"EVENTS = \[.*?\n\]", evs, "EVENTS")
    (project / "mix_audio.py").write_text(s, encoding="utf-8")
    return len(ev)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--at", default="")
    ap.add_argument("--dipblack-at", default="")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--threshold", type=float, default=8.0)
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--cq-at", default="", help="金句/方言独立切段复核起始秒, 透传 asr_final_check")
    ap.add_argument("--skip-asr", action="store_true",
                    help="V3.18 跳过整片 ASR 硬门(应急;默认必跑, FAIL 不交付)")
    a = ap.parse_args()
    proj = a.project.resolve()
    at_set = {int(x) for x in a.at.split(",") if x.strip()}
    # dipblack 只是"创意转场用哪种模式", 生成与否由 --at 决定。序号只写在 --dipblack-at 里
    # 会被静默降级成硬切(你要求压黑, 得到硬切, 全程无人报错)。花钱前就拦下。
    orphan = {int(x) for x in a.dipblack_at.split(",") if x.strip()} - at_set
    if orphan:
        raise SystemExit(f"[FAIL] --dipblack-at {sorted(orphan)} 不在 --at {sorted(at_set) or '(空)'} 内 —— "
                         f"创意转场只为 --at 列出的边界生成, 这些序号会被静默降级成硬切。"
                         f"修法: 把它们同时加进 --at")

    # 毫秒级的检查不该用 196 秒的装配去换(§58⑥)。verify_ledgers 原本只在最后一行，
    # p26 实录：produce① 已 DELIVER PASS + 整片 ASR 全过，只死在最后这一步"没登记进 palettes.json"，
    # 于是补两行账本 → 整条 splice+混音+编码+三项 QC 白跑第二遍(196s)。
    # 现在开头先查一次(两次毫秒级文件写)，末尾那道照旧保留——前移不是放松交付门。
    verify_ledgers(proj)          # V3.35: 交付前最后一道——本片必须进两本跨片账本

    if not a.skip_render:
        # §66 名字对账门：渲染是这一步之前最贵的一脚(数千帧)，而它查的正是"念到谁、屏上是不是谁"。
        # 前 17 部片没有任何一道门量过这件事——p17 可以每道门全绿地把 Flash 讲成 Pro。
        # NAMES.json 不存在时本门只 WARN 返回 0(历史片没建名单，拦它们是误伤)。
        run([PY, str(HERE / "name_ledger.py"), str(proj)], "name_ledger 名字对账(§66 硬门)")
        run([PY, str(HERE / "split_beats.py"), str(proj), "--threshold", str(a.threshold)], "split_beats 拆长镜头")
        run([PY, str(HERE / "render_all.py"), str(proj), "--jobs", str(a.jobs), "--overwrite"], "render_all 渲染")
    else:
        # --skip-render 复用旧帧: render_all 的渲前门禁这一趟完全没跑, 只校验帧↔JSON 哈希是不够的
        # (哈希看不见资产被换/背景未降亮/字卡出画)。复用帧前把渲前门禁按同口径重跑一遍。
        verify_frames_match_scenes(proj)
        # 与 render_all 的渲前链同口径：V3.34 的 skill_sync 与 V3.39 的 card_text_check
        # 当时只挂进了 render_all，这张复用旧帧的复检表没跟上 → 走 --skip-render 时
        # "工具漂移"和"空白字卡"两类缺陷一道都不查(p25 那 30/55 张坏卡正是后者管的东西)。
        # rc=2 = 无项目级镜像（便携包场景），按"无可比对"放行，不是失败。
        run([PY, str(HERE / "skill_sync.py"), "check", "--quiet"], "skill_sync 工具同源(复用旧帧前复检)",
            allow=(0, 2))
        for tool, extra in (("first_frame_check.py", []), ("card_text_check.py", []),
                            ("bg_luma_check.py", ["--no-fix"]),
                            ("preflight_v6.py", []), ("check_timeline_ratio.py", []),
                            ("motion_similarity_check.py", []), ("bg_plan_check.py", []),
                            ("text_legibility_check.py", []),
                            ("layout_check.py", []), ("name_ledger.py", [])):
            run([PY, str(HERE / tool), str(proj), *extra], f"{tool} 复用旧帧前复检")
    run([PY, str(HERE / "gen_transitions.py"), str(proj), "--at", a.at, "--dipblack-at", a.dipblack_at], "gen_transitions 硬切为主")
    starts = json.loads((proj / "qa" / "scene_starts.json").read_text(encoding="utf-8"))
    # 场号取自 manifest 里真实的 frames_sNN 名, 不按"第 i 个槽位=第 i+1 场"猜(场号有洞会整条静默错位)
    _mf = json.loads((proj / "splice_manifest.json").read_text(encoding="utf-8-sig"))
    scene_nos = [int(re.search(r"frames_s(\d+)", n).group(1)) for n, _c, k in _mf if k != "trans"]
    # V3.39(p24 实录): --at 是"创意转场标记"时代的遗留——硬切为主时每个 at 不再物理加 10 帧,
    # 但这里仍 +10*len(at_set) → TARGET 比 manifest 多 10 帧/个, mix 断言当场拦下(p24 --at 89 白跑一轮)。
    # 总帧的权威就是 splice_manifest(gen_transitions 刚写的), 直接读它, 不再估算。
    try:
        total = int(json.loads((proj / "splice_manifest.json").read_text(encoding="utf-8"))["total"])
    except Exception:
        total = sum(json.loads((proj / "qa" / "actual_counts.json").read_text(encoding="utf-8"))) + len(at_set) * 10
    run([PY, str(HERE / "splice_frames.py"), "--root", str(proj), "--manifest", str(proj / "splice_manifest.json")], "splice 拼接")
    run([PY, str(HERE / "check_timeline_ratio.py"), str(proj)], "check_timeline_ratio 逐段时长")
    nev = build_mix(proj, starts, at_set, round(total / 30, 3), scene_nos)
    run([PY, str(proj / "mix_audio.py")], "mix_audio 混音(%d 音效)" % nev)
    from env_paths import ffmpeg
    ffm = str(ffmpeg())
    import os as _os
    _eq = _os.environ.get("EQ_SAT", "1.14")  # 高饱和风格(漫画网点/波普)传 1.08, 防 qa⑤ 回抽色差>5 误 FAIL(§44)
    (proj / "output").mkdir(exist_ok=True)
    run_retry([ffm, "-y", "-framerate", "30", "-start_number", "1", "-i", str(proj / "frames" / "frame_%04d.png"),
               "-i", str(proj / "audio_build" / "final_mix.wav"), "-vf", "eq=saturation=" + _eq,
               "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-preset", "medium",
               "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
               str(proj / "output" / "final.mp4")], "编码成片")
    # 显式指定要审的成片: qa_deliver 不给 --mp4 时会 glob output/*.mp4 取 sorted()[0],
    # 双版本(v1/v2)交付时审的可能是另一支(编码写的是 final.mp4, 审的却是别的)。
    _final = proj / "output" / "final.mp4"
    run([PY, str(HERE / "qa_deliver.py"), str(proj), "--mp4", str(_final)], "qa_deliver 交付门禁")
    run([PY, str(HERE / "clutter_check.py"), str(proj)], "clutter_check 拥挤度双向检测")
    run([PY, str(HERE / "aesthetic_check.py"), str(proj)], "aesthetic_check 审美视觉QC(报告)")
    # V3.18 整片 ASR 硬门(p10 "两个配音"事故机制化): 混音+编码后的最终听感逐段回抽, FAIL 不交付
    if a.skip_asr:
        print("\n⚠ --skip-asr: 跳过整片 ASR 复核(应急模式, 交付风险自担)")
    else:
        cmd = [PY, str(HERE / "asr_final_check.py"), str(proj), "--mp4", str(_final)]
        if a.cq_at:
            cmd += ["--cq-at", a.cq_at]
        run(cmd, "asr_final_check 整片 ASR 复核(硬门)")
    verify_ledgers(proj)          # V3.35: 交付前最后一道——本片必须进两本跨片账本
    print("\n✅ 成片: " + str(proj / "output" / "final.mp4") + "  总帧≈%d = %.1fs" % (total, total / 30))


if __name__ == "__main__":
    main()
