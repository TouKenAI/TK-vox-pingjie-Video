#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.6 审稿前编排器（B）：把"建项目→类型→结构档"和"审稿后→TTS→词级卡点→ASR"两段机械步自动化。
人只保留三件: 联网核实事实+写重构稿/事实点清单/隐喻/配色(创意) + 审稿 + SUT/build_scenes。

用法:
  # 阶段0-①(审稿前机械步): 建项目 + 存文案 + 类型 + 结构档建议
  py pipeline.py setup --root <工作区> --name productionN --copy <文案.txt> [--energy 标准] [--genre knowledge]
  #   → 然后你去: 联网核实事实、写 chunks.json + palette.json + BRIEF、交用户审稿
  # 阶段②(审稿通过后): TTS + word_timing + asr_spotcheck
  py pipeline.py tts <项目目录>
  #   → 然后你去: SUT + semantic_check、build_scenes(motion/pf)、produce.py 一键成片
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

HERE = Path(__file__).resolve().parent
PY = sys.executable
# 所有门禁子进程一律在仓库根下跑：metaphor_ledger / palette_ledger 这类跨片账本
# 历史上是按 Path.cwd() 上溯找的，从别的目录敲 `pipeline ready` 就会拿空账本比对 →
# 报"未撞车 rc=0"。CWD 不该决定"跟谁比"，所以在这里钉死。
_REPO_ROOT = str(HERE.parent)

# 子进程编码：本文件上面那行 reconfigure 只救自己，**救不到 subprocess 生出来的孩子**。
# Windows 中文环境下子进程默认拿 GBK stdout，任何门一 print ✓/✗ 就 UnicodeEncodeError 崩掉，
# 于是 pipeline 把它读成 rc!=0 → 报"配色硬门没过"这种**根本不存在的红**（2026-09-24 p19 实录）。
# 定义收在 env_paths.CHILD_ENV（单一事实源，produce/render_all/animatic 同源）。
from env_paths import CHILD_ENV


def run(cmd, what, show=6, allow=(0,)):
    """allow 显式声明可接受的退出码。
    旧版写死 `not in (0, 1)` 当"WARN 级交人判读"放过——但 check_script/claim_check/asr_spotcheck
    的 FAIL 就是 rc=1(V3.21 审查实录: p14 之前一直是这么跑的), 于是"花钱前硬门"形同虚设,
    文案没过也照样 TTS 计费。默认 allow=(0,) = 非 0 即中止。"""
    print("\n=== " + what + " ===")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=CHILD_ENV, cwd=_REPO_ROOT)
    out = (r.stdout or "") + (r.stderr or "")
    print("\n".join(out.strip().splitlines()[-show:]))
    if r.returncode not in allow:
        print(f"❌ {what} 失败(rc={r.returncode}, 允许 {list(allow)}) —— 后续步骤不执行")
        sys.exit(1)
    return out


def _kickoff_state(proj: Path) -> tuple[bool, list[str]]:
    """KICKOFF.md 是否填完——可机械判定的部分(§62 判据: 能机械判定的就别靠人盯)。
    查三件事: 文件在 / 没有残留 `______` 空格 / 每条 `| S0N` 场次行的 8 个格子都填了。
    只查这三件, 是为了**绝不误伤**: 填法自由, 但空着过不了。"""
    import re as _re
    k = proj / "KICKOFF.md"
    if not k.exists():
        return False, [f"{k} 不存在——复制 references/kickoff-template.md 过来"]
    txt = k.read_text(encoding="utf-8")
    bad = []
    if _re.search(r"_{4,}", txt):
        bad.append("还有未填的下划线空位(`______`)")
    # 只数 **B 段内**的场次行。E 段"渲完第一眼检查"、F 段差异表同样以 `| S01 |` 开头，
    # 但那是 3~4 格的复盘记录，不是 8 格开工行——混在一起数，渲完填了 E 的片子会被判
    # "格数不足"这种**根本不存在的红**（2026-09-24 在已交付的 p18 上实测到）。
    in_b, rows = False, []
    for ln in txt.splitlines():
        if ln.startswith("#"):
            in_b = bool(_re.match(r"#+\s*B[\.、\s]", ln.strip()))
        elif in_b and _re.match(r"\|\s*S\d+", ln):
            rows.append(ln)
    if not rows:
        bad.append("B 逐场表一行都没填(`| S01 |` 开头的行)")
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 8:
            bad.append(f"B 表行格数不足(得 {len(cells)}/8): {ln[:40]}…")
        elif any(not c for c in cells):
            bad.append(f"B 表 {cells[0]} 还有空格子——写不出动作的场要合并或重想")
    return (not bad), bad


def probe(cmd, what):
    """与 run() 的区别: **不中止**, 只回报成败。ready 要把所有门一次跑完再汇总,
    否则第一条失败就把剩下的藏起来(§62① 刚为 preflight 记过同一类病)。"""
    print("\n=== " + what + " ===")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=CHILD_ENV, cwd=_REPO_ROOT)
    out = (r.stdout or "") + (r.stderr or "")
    print("\n".join(out.strip().splitlines()[-6:]))
    return r.returncode == 0


def _stamp_of(proj: Path, stage: str) -> str:
    import hashlib
    inputs = [proj / "KICKOFF.md", proj / "palette.json", proj / "chunks.json",
              # §75 判据：ready 拿 qa/concepts.txt 喂 metaphor_ledger 查重，但它不在章输入里
              # → 盖章后删掉撞车的概念行，require_ready 照过、gen_assets 照花钱。
              proj / "qa" / "concepts.txt"]
    if stage == "assets":
        inputs.append(proj / "sut.json")
        # V3.35: 背景计划必须进章。`ready --stage assets` 跑过 bg_plan_check --plan 之后
        # 把 jobs_bg.json 从 11 张改成 6 张，旧盖章不会失效 → 那道花钱前的门**一次编辑就绕过**。
        inputs += sorted({*proj.glob("jobs*.json")})
    h = hashlib.sha256()
    for p in inputs:
        h.update(p.name.encode())
        h.update(p.read_bytes() if p.exists() else b"<MISSING>")
    return h.hexdigest()[:16]


def ready(proj_path, stage="tts"):
    """V3.27 缺失的编排: 阶段③④⑤ 的门以前只以 print 提示存在, 从没被任何编排器调用过。
    本命令一次跑完并盖章; tts / gen_assets 只认章, 没章或输入变了就拒花用户的钱。"""
    proj = Path(proj_path).resolve()
    pal = proj / "palette.json"
    if not pal.exists():
        print(f"[提示] 还没有 {pal} —— 配色门要等声明后才能跑" +
              ("" if stage != "assets" else "; 生图前必须补上"))
    _k_ok, _k_why = _kickoff_state(proj)
    results = [("KICKOFF 开工模板已填完", _k_ok, "; ".join(_k_why))]
    # V3.34 工具同源门：仓库 scripts/+references/ 与已安装技能包必须逐字节一致。
    # 首次实测就有 5 个脚本 + playbook 漂移（含 p23 刚修的 preflight_v6 R1 与 gen_assets --only）——
    # 修好的门和写下的教训没进技能包，下一部片跑的是旧工具，而全流程一片绿。
    _ss = HERE / "skill_sync.py"
    if _ss.exists():
        _rc = subprocess.run([PY, str(_ss), "check"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", env=CHILD_ENV).returncode
        if _rc == 2:
            print("[N/A] 找不到已安装技能包 —— 无镜像可对账（便携包场景），本项不计入")
        else:
            results.append(("工具同源(仓库 ↔ 技能包 skill_sync)", _rc == 0,
                            "" if _rc == 0 else "跑 `py -3.14 scripts/skill_sync.py push`（仓库是权威）"))
    if pal.exists():
        results.append(("palette_oklch check 配色硬门",
                        probe([PY, str(HERE / "palette_oklch.py"), "check",
                               "--palette", str(pal), str(proj)], "palette_oklch"), ""))
    concepts = [c for c in re.split(r"[\s,、;；]+",
                  (proj / "qa" / "concepts.txt").read_text(encoding="utf-8").strip())
                if c] if (proj / "qa" / "concepts.txt").exists() else []
    if concepts:
        results.append(("metaphor_ledger check 隐喻防撞",
                        probe([PY, str(HERE / "metaphor_ledger.py"), "check", *concepts,
                               "--film", proj.name], "metaphor_ledger"),
                        f"{len(concepts)} 个概念已对账"))
    else:
        results.append(("metaphor_ledger check 隐喻防撞", False,
                        "缺 qa/concepts.txt(本片视觉隐喻概念一行一个)——"
                        "旧写法 check 不带概念时打印「新概念 0: (无) PASS」空转, p17–p21 就这么连过五部"))
    results.append(("novelty_meter 创意多样性",
                    probe([PY, str(HERE / "novelty_meter.py"), str(proj)], "novelty_meter"), ""))
    if stage == "assets":
        # V3.34 花钱前：背景必须"每场一个空间"。p18–p23 六部显得薄的片复用率 0.15–0.45，
        # p11–p16 全是 1.00；等生完图再发现复用就晚了，所以放在生图章之前。
        results.append(("bg_plan_check --plan 背景每场一个空间",
                        probe([PY, str(HERE / "bg_plan_check.py"), str(proj), "--plan"], "bg_plan_check"), ""))
        results.append(("semantic_check 语义动效(阶段③)",
                        probe([PY, str(HERE / "semantic_check.py"), str(proj)], "semantic_check"), ""))
        # V3.39(p25): 字卡内容存在性门——30/55 张坏卡(奶油字画奶油板+id 文案)六道门全绿的盲区。
        # 卡是本地零成本素材, 但坏了的代价是整轮渲染+交付白跑; 放进 assets 章在渲染前拦。
        results.append(("card_text_check 字卡登记与内容存在性",
                        probe([PY, str(HERE / "card_text_check.py"), str(proj)], "card_text_check"), ""))
        # V3.31: 彩带是 new_project 按字节拷的模板件, p17→p21 五部逐字节相同,
        # 而账本 origin=template 把 preflight 的跨片复用门遮住了 → 有配色就必须重绘过。
        rc = subprocess.run([PY, str(HERE / "make_confetti.py"), str(proj), "--check"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=CHILD_ENV).returncode
        results.append(("confetti 已按本片配色重绘(跨片零复用)", rc == 0,
                        "" if rc == 0 else "跑 make_confetti.py " + proj.name))
        if not (proj / "shot-plan.json").exists():
            print("[WARN] 阶段⑤ 未执行: 没有 shot-plan.json —— validate_shot_plan 因此没东西可校验。"
                  "九部片 0 份分镜是事实; 本门只报不拦(拦了会停掉整条产线), 但每部都该补")

    print("\n=== pipeline ready 汇总 ===")
    for name, ok, why_ in results:
        print(("  ✓ " if ok else "  ✗ ") + name + (f"  ← {why_}" if (not ok and why_) else ""))
    bad = [n for n, ok, _ in results if not ok]
    if bad:
        print(f"\n❌ {len(bad)} 项未过 —— 不盖章, tts / 生图 会被拒。补齐后重跑本命令(一轮就能看全)")
        return 1
    stamp = _stamp_of(proj, stage)
    (proj / "qa").mkdir(exist_ok=True)
    (proj / f"qa/ready-{stage}.json").write_text(
        json.dumps({"stage": stage, "stamp": stamp}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 已盖章 qa/ready-{stage}.json (stamp={stamp})")
    return 0


def require_ready(proj: Path, stage: str):
    """tts / gen_assets 的前置: 必须有**当前输入下**有效的章。改过 KICKOFF/配色/分段/语义表即作废。"""
    f = proj / f"qa/ready-{stage}.json"
    if not f.exists():
        raise SystemExit(f"[FAIL] 缺 qa/ready-{stage}.json —— 先跑 "
                         f"`py pipeline.py ready {proj.name} --stage {stage}`。它把 "
                         f"KICKOFF/配色/隐喻/多样性{'+语义动效' if stage == 'assets' else ''} 一次跑完; "
                         f"这些门此前只以 print 提示存在, 从没被编排器调用过")
    got = json.loads(f.read_text(encoding="utf-8")).get("stamp")
    want = _stamp_of(proj, stage)
    if got != want:
        raise SystemExit(f"[FAIL] qa/ready-{stage}.json 已过期(盖章时 {got}, 按当前输入应为 {want}) —— "
                         f"KICKOFF/配色/分段/语义表改过了, 重跑 `pipeline.py ready --stage {stage}`")


def _prev_film(proj: Path):
    """编号严格小于本片、且有 palette.json 的最近一部 production*。"""
    import re as _re

    def num(p: Path) -> int:
        m = _re.search(r"\d+", p.name)
        return int(m.group()) if m else -1
    cands = [d for d in proj.parent.glob("production*")
             if d.resolve() != proj.resolve() and num(d) >= 0 and num(d) < num(proj)
             and (d / "palette.json").exists()]
    return max(cands, key=num) if cands else None


def _prev_style(prev: Path) -> str:
    try:
        sp = json.loads((prev / "palette.json").read_text(encoding="utf-8")).get("style_primary", "")
    except (json.JSONDecodeError, OSError):
        return ""
    sys.path.insert(0, str(HERE))
    from style_presets import base as _b   # 主名归一只有这一份实现
    return _b(sp)


def setup(root, name, copy_file, energy, genre, style=""):
    proj = Path(root) / name
    # 参数校验必须在**建骨架之前**。第一版把这两个守卫放在 new_project 之后，于是打印的
    # "拒绝建项目"是句假话：骨架、KICKOFF.md、genre-detect.json 已经落盘，而改正参数后
    # 用同一个 --name 重试会被 new_project 的"目录已存在(防误伤)"挡死(2026-09-29 实测)。
    if copy_file and not Path(copy_file).exists():
        print(f"❌ --copy 指向的文件不存在: {copy_file} —— 不建项目"
              f"(空桩 chunks.json 会让花钱前的门对着空稿打 PASS，§77②)")
        sys.exit(1)
    _mm = None
    if style:
        import importlib.util as _iu
        _sc = _iu.spec_from_file_location("sp", str(HERE / "style_presets.py"))
        _mm = _iu.module_from_spec(_sc); _sc.loader.exec_module(_mm)
        if style not in _mm.STYLES:
            # README 的旗舰第一条命令曾写着 `--style 等距2.5D/白板手绘`——那不是合法键，
            # 旧版没有 else 分支：不写 palette.json、不重绘彩带、不报错、exit 0。
            print(f"❌ --style '{style}' 不是合法风格档。可用: {', '.join(_mm.STYLES)}")
            print("   混搭请分两步: 先 `--style 主风格` 建 palette.json，"
                  "再 `py -3.14 scripts/style_presets.py blend 主 副` 取叠加语言。")
            sys.exit(1)
    run([PY, str(HERE / "new_project.py"), str(root), "--name", name], "new_project 建骨架")
    # V3.27: 开工模板必须**自动落到项目里**——只写在文档里"记得去复制"的规矩一定会漏(§62 同一类病)。
    kt = HERE.parent / "references" / "kickoff-template.md"
    if kt.exists():
        if not (proj / "KICKOFF.md").exists():
            (proj / "KICKOFF.md").write_text(kt.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✓ 开工模板已复制 → {proj / 'KICKOFF.md'}(逐条填完才能 `pipeline ready`)")
    else:
        print(f"[WARN] 找不到 {kt} —— 开工模板钩子失效(便携包版本过旧, 需重打)")
    text = Path(copy_file).read_text(encoding="utf-8") if copy_file else ""
    if text:
        (proj / "qa").mkdir(exist_ok=True)
        (proj / "qa" / "source-copy.txt").write_text(text, encoding="utf-8")
        g = genre or "auto"
        cmd = [PY, str(HERE / "detect_genre.py"), str(proj)] + ([] if genre else ["--text", text])
        if genre:
            cmd = [PY, str(HERE / "detect_genre.py"), str(proj), "--genre", genre, "--force"]
        # rc=2 只是"置信度低, 建议人工 --genre"的提示, 不该把已经建好的骨架废掉
        run(cmd, "detect_genre 类型识别(低置信度=提示)", allow=(0, 2))
        chars = len(re.sub(r"\s", "", text))
        run([PY, str(HERE / "structure_plan.py"), "recommend", "--chars", str(chars), "--energy", energy], "structure_plan 结构档")
    if style:
        # 合法性已在建骨架前查过(_mm 那时已加载)，这里只负责落地配色与彩带。
        pal = dict(_mm.STYLES[style]["palette"]); pal["film"] = name
        (proj / "palette.json").write_text(json.dumps(pal, ensure_ascii=False, indent=1), encoding="utf-8")
        print("【风格档 " + style + "】palette.json 已生成; 生图: gen_assets jobs.json --style " + style)
        print("  反差池(强制叠1个):", _mm.STYLES[style]["反差池"])
        # V3.31: 彩带必须在配色落地这一刻重绘——它是 new_project 按字节拷的模板件,
        # 五部片逐字节相同(p17→p21 实测), 而账本写着 origin=template 把 preflight 的跨片复用门遮住了。
        rc = subprocess.run([PY, str(HERE / "make_confetti.py"), str(proj)],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=CHILD_ENV, cwd=_REPO_ROOT).returncode
        print(("  ✓ " if rc == 0 else "  ✗ ") + "confetti 已按本片配色重绘"
              + ("" if rc == 0 else "(改配色后需手跑 make_confetti.py)"))
    if style:
        prev = _prev_film(proj)
        cur_base = _mm.base(style)
        p_st, p_name = None, None
        if prev is not None:
            p_st, p_name = _prev_style(prev), prev.name
        else:
            # V3.37: 历史 production* 已清空 → 上一部的风格档从 film_digest.json 取，
            # 否则这条"两部会同风格"的最早提醒会永久静默。
            try:
                from film_digest import prev_entry
                ent = prev_entry(proj.name)
                if ent:
                    p_st, p_name = _mm.base(ent.get("style_primary", "")), ent["name"]
            except Exception:
                pass
        if p_st and p_st == cur_base:
            print(f"\n⚠ 主风格档与上一部({p_name})同为「{cur_base}」——两部会像。"
                  f"\n  要么换档, 要么 `style_presets blend {style} <副风格>` 借副风格的 motion 落到某几场。"
                  f"\n  渲前 `motion_similarity_check.py` 会按**实测缓动**硬拦(同档且余弦>0.92 即拒渲)。")
    print("\n【下一步·人做】填 KICKOFF.md(题材三问→世界/风格三特征/逐场动作/F 对上一部查差异) → "
          "联网核实事实 → 写 chunks.json + palette.json + BRIEF(事实点清单/隐喻/四维) → 交用户审稿。")
    print("【然后·机器】审稿通过后跑 `py pipeline.py ready <项目> --stage tts` 盖章"
          "(它跑 KICKOFF 完成度 + palette_oklch + metaphor_ledger + novelty_meter), 再 `pipeline tts`。")
    return 0


def tts(proj_path):
    proj = Path(proj_path).resolve()
    # V3.27: TTS 是第一次花钱。开工模板/配色/隐喻/多样性四道门此前只在 setup 末尾 print 一句
    # "下一步·人做", 从没被调用过 —— 现在收进来了, 没盖章不给合成。
    require_ready(proj, "tts")
    # 花钱前的两道文案硬门: R1-R6 机检 + 自洽性机检(矛盾断言/差值复算)。
    # 之前只在人脑里过, p14 实录: "比 Kimi 强"与"和 Kimi 打平"同片并存、差价 1毛6 写成"两毛"。
    g = ""
    gd = proj / "qa" / "genre-detect.json"
    if gd.exists():
        g = json.loads(gd.read_text(encoding="utf-8")).get("genre", "")
    cmd = [PY, str(HERE / "check_script.py"), str(proj)] + (["--genre", g] if g else [])
    run(cmd, "check_script 文案重构机检(硬门)")
    run([PY, str(HERE / "claim_check.py"), str(proj),
         "--json-out", str(proj / "qa" / "claim-check.json")], "claim_check 文案自洽机检(硬门)")
    gt = proj / "generate_tts.py"
    src = HERE / "generate_tts_template.py"
    s = src.read_text(encoding="utf-8").replace(
        'STEPFUN = Path(__file__).resolve().parent / "stepfun_tools.py"',
        'STEPFUN = Path(r"' + str(HERE / "stepfun_tools.py") + '")')
    gt.write_text(s, encoding="utf-8")
    run([PY, str(gt)], "TTS 全量合成")
    run([PY, str(HERE / "word_timing.py"), str(proj)], "word_timing 词级卡点")
    run([PY, str(HERE / "asr_spotcheck.py"), str(proj)], "asr_spotcheck 发音抽检")
    print("\n【下一步·人做】写 sut.json(逐句标 A 级演语义) → build_scenes(motion/pf, 每场≥7 元素)。")
    print("【生图前·机器】`py pipeline.py ready <项目> --stage assets` 盖章"
          "(再加 semantic_check)——**没章 gen_assets 拒绝生图**, 语义动效门此前从没被调用过。")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup"); s.add_argument("--root", type=Path, required=True); s.add_argument("--name", required=True)
    s.add_argument("--copy", default=""); s.add_argument("--energy", default="标准", choices=["快评", "标准", "深度"]); s.add_argument("--genre", default="")
    s.add_argument("--style", default="", help="V3.7 风格库名, 自动写 palette.json + 提示锚点")
    t = sub.add_parser("tts"); t.add_argument("project", type=Path)
    r = sub.add_parser("ready"); r.add_argument("project", type=Path)
    r.add_argument("--stage", choices=["tts", "assets"], default="tts",
                   help="tts=TTS 花钱前(模板/配色/隐喻/多样性); assets=生图前(再加语义动效)")
    a = ap.parse_args()
    if a.cmd == "setup":
        sys.exit(setup(a.root, a.name, a.copy, a.energy, a.genre, a.style))
    if a.cmd == "ready":
        sys.exit(ready(a.project, a.stage))
    sys.exit(tts(a.project))


if __name__ == "__main__":
    main()
