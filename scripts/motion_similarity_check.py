#!/usr/bin/env python3
"""V3.31 动效同构硬门 —— 连续两部用同一主风格档时，拦住"运动语言抄上一部"。

为什么需要它(p20→p21 实录):
  主风格档连着两部选了「剪纸拼贴」。KICKOFF 的 A2b 运动语法写着"逐字抄自 style-presets
  那一行"，于是两部的运动质感/视差开关/相机规则**由模板保证逐字相同**。
  novelty_meter 的 D3 缓动余弦当时**报了 0.983 > 0.92**，但它是 advisory(rc 恒 0)，
  没人被迫处置 → 交付后用户一眼看出"这几个片子风格有点像"。

判据(只用实测产物，不用自我声明):
  1) 与上一部主风格 base(palette.json.style_primary 截主名)不同 → 直接 PASS。
     不同风格缓动本就不同，没必要拦；实测 p17→p18 0.873 / p18→p19 0.064 / p19→p20 0.185。
  2) 同 base 时，量两件事，**任一不满足即 FAIL**:
     a. 缓动分布余弦 ≤ 0.92(p20→p21 实测 0.983)
     b. 主导缓动(top-1)与上一部不同(p20/p21 同为 ease-out 0.47)

退出码约定: 0=PASS, 1=FAIL(拒渲)。挂在 render_all 渲前链里。
用法: py -3.14 scripts/motion_similarity_check.py <项目目录>
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from style_presets import base as style_base  # noqa: E402


def _num(p: Path) -> int:
    m = re.search(r"\d+", p.name)
    return int(m.group()) if m else -1


def _style_of(proj: Path) -> str:
    pal = proj / "palette.json"
    if not pal.exists():
        return ""
    try:
        return style_base(json.loads(pal.read_text(encoding="utf-8")).get("style_primary", ""))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit(f"[FAIL] {pal} 读不出 style_primary: {e!r} —— 风格连用检测不能靠猜")


def easing_hist(proj: Path) -> Counter:
    """缓动分布只认**场景 JSON**，不认 KICKOFF 里写了什么(p21 的 A2b 文本写得挺不一样，
    落地缓动却和 p20 一模一样——自我声明不是证据)。"""
    h: Counter = Counter()
    for f in sorted(proj.glob("scene_s*.json")):
        sc = json.loads(f.read_text(encoding="utf-8"))
        for l in sc.get("layers", []):
            for k in l.get("keyframes", []):
                if k.get("ease"):
                    h[k["ease"]] += 1
        for e in sc.get("effects", []):
            h["fx:" + str(e.get("type", "?"))] += 1
    return h


def cos(a: Counter, b: Counter) -> float:
    import math
    keys = set(a) | set(b)
    na = math.sqrt(sum(v * v for v in a.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return sum(a.get(k, 0) * b.get(k, 0) for k in keys) / (na * nb)


EASE_TOKENS = ["ease-in", "ease-out", "ease-in-out", "linear", "pop_spring",
               "slam_squash", "fly_blur", "peel", "drift_layer", "stagger", "orbit",
               "描边自绘", "墨晕", "旋转", "scale", "wipe", "擦除"]


def _motion_tokens(body: str) -> set:
    """最长优先匹配。`ease-in-out` 直接做子串判断会同时命中 `ease-in` 和 `ease-out`，
    于是一句只提了一个缓动的空话就能凑够"两个动效词"把门洗白(第一版实测到)。"""
    pat = "|".join(re.escape(t) for t in sorted(EASE_TOKENS, key=len, reverse=True))
    return set(m.group(0) for m in re.finditer(pat, body))


def _declared_diff(proj: Path, prev: Path) -> str:
    """KICKOFF 里的显式差异声明: `A2c · 与上一部的运动差异: …`
    必须 ≥30 字**且点名 ≥2 个场次**(S0N) + ≥2 个动效词，否则一句"本片更注重节奏"就能洗白整道门。
    找不到/不合格 → 返回空串(=不放行)。不猜、不默认放行。

    ⚠ V3.41 修的死路：旧版**一撞上含"A2c…运动差异"的行就 return**，而模板把标题与内容分成两行
      (`**A2c · …**` 换行 `> 正文`)——标题那行没有冒号，于是正文永远读不到。实测 p26 写了四条场名、
      五种动效词的真声明，门照样 FAIL：**这道硬门在正常 markdown 写法下没有出口**。
      现在改成：继续扫描所有候选，正文可取同行冒号后、也可取紧随其后的引用/正文行。"""
    k = proj / "KICKOFF.md"
    if not k.exists():
        return ""
    lines = k.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if "A2c" not in ln or "运动差异" not in ln:
            continue
        body = ""
        m = re.search(r"[:：]", ln)
        if m:
            body = ln.replace("*", "")[m.end():].strip()
        if not body:                             # 只在"同行根本没正文"时才往下看(标题+正文分两行的写法)
            # ⚠ 第一版写成 `if len(body) < 30`，实测：把标题行改成一句空话("本片更注重节奏与整体质感")
            #   后，它会把下面那段真声明合并上来凑够字数 → **偷懒写法照样放行**。合格与否只看这一处声明本身。
            nxt = []
            for follow in lines[i + 1:i + 4]:
                s = follow.strip().lstrip(">").strip().replace("*", "").strip()
                if not s:
                    continue
                if s.startswith("#") or s.startswith("**A") or s.startswith("A3"):
                    break
                nxt.append(s)
                if len(" ".join(nxt)) >= 30:
                    break
            body = (body + " " + " ".join(nxt)).strip()
        scenes = set(re.findall(r"S\d{2}", body))
        tokens = _motion_tokens(body)
        # 三个条件各挡一种敷衍: 字数挡空话、场名挡"整体更注重节奏"、动效词挡只喊一句
        if len(body) >= 30 and len(scenes) >= 2 and len(tokens) >= 2:
            return body
    return ""


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--allow-no-prev"]
    allow_no_prev = "--allow-no-prev" in sys.argv[1:]
    if not argv:
        print("用法: motion_similarity_check.py <项目目录> [--allow-no-prev]")
        return 1
    proj = Path(argv[0]).resolve()
    if not proj.exists():
        raise SystemExit(f"[FAIL] 项目目录不存在: {proj}(打错路径也报 PASS 的门比没门更糟)")
    here = easing_hist(proj)
    if not here:
        # 与 first_frame_check 同口径：零场景不是"无可比较"，是路径写错(§57⑤/§81①)。
        # 旧版对"存在但空的目录"rc=0、对"不存在的目录"FAIL——同一类输入两种相反行为。
        if not list(proj.glob("scene_s*.json")):
            print(f"✗ FAIL: {proj.name} 下没有 scene_s*.json —— 无可比较不是通过，是本门没在跑")
            return 1
        # §81：PASS（0 次）不是通过，是没跑。有场景却抽不出缓动关键帧 = 数据坏了，必须响。
        print(f"✗ FAIL: {proj.name} 有场景但抽不出缓动关键帧(实测 0 次比较) —— "
              f"渲染器要求每帧带 ease，出现此情况是场景 JSON 坏了，不是本门没事")
        return 1

    cur_style = _style_of(proj)
    root = proj.parent
    prev = max((d for d in root.glob("production*")
                if d.resolve() != proj and (d / "chunks.json").exists()
                and _num(d) >= 0 and _num(d) < _num(proj)
                and (d / "palette.json").exists()), key=_num, default=None)
    if prev is None:
        # V3.37: 历史 production* 目录已按用户裁定清空(141GB)，参照物改从 film_digest.json 取。
        # 不接这一层，本门会永远走"找不到前一部 → 放行"——门还在，但再也拦不住任何东西。
        from film_digest import LEDGER
        try:
            from film_digest import prev_entry
            ent = prev_entry(proj.name)
        except Exception as e:
            ent = None
            print(f"⚠ film_digest 不可用({e!r})")
        if not ent or not ent.get("easing"):
            # 两种情况必须分开：① 账本没建/建不起来 = 防撞机制整体不存在，不是"没有前一部"；
            # ② 账本在但确实没有更小编号的条目 = 本片就是第一部。旧版一律 return 0，
            # 于是账本一坏这道门就静默消失而全流程绿（V3.42 收口）。
            if not LEDGER.exists():
                print(f"✗ FAIL: 跨片防撞的唯一参照 {LEDGER} 不存在 —— 无可比对不是通过。"
                      f"先跑 `py -3.14 scripts/film_digest.py build`；确要从零开始加 --allow-no-prev")
                return 1 if not allow_no_prev else 0
            print(f"[SKIP] film_digest.json 在但没有编号小于本片的条目 → 本片视为第一部，"
                  f"本门实测比较 0 次（不是通过）。若这**不是**第一部，说明账本旧了："
                  f"跑 `py -3.14 scripts/film_digest.py build`")
            return 0
        from collections import Counter
        prev_name, prev_style = ent["name"], ent.get("style_primary", "")
        ph = Counter({k: int(v) for k, v in ent["easing"].items()})
        print(f"· 前一部目录已清，缓动参照取自 film_digest.json 的 {prev_name}")
    else:
        prev_name, prev_style = prev.name, _style_of(prev)
        ph = easing_hist(prev)
        if not ph:
            # §81：前一部目录在、却抽不出缓动数据 = 参照坏了，不是"没有可比的"。
            print(f"✗ FAIL: 前一部 {prev.name} 目录在但抽不出缓动数据(实测比较 0 次) —— "
                  f"参照坏了而不是没有参照，先跑 `py -3.14 scripts/film_digest.py build` 重建账本")
            return 1 if not allow_no_prev else 0
    if not cur_style:
        print(f"[FAIL] {proj.name} 的 palette.json 没有 style_primary → 无法判断是否与上一部同风格")
        return 1
    sim = cos(here, ph)
    top_cur = here.most_common(1)[0]
    top_prev = ph.most_common(1)[0]

    if cur_style != prev_style:
        # V3.41: 旧版到这里直接 return 0——把"换了风格档"当成"换了运动语言"。
        # 实测推翻了这个前提：p24(剪纸)/p25(漫画网点)/p26(国潮水墨)三部**不同风格**片，
        # 缓动余弦 0.950 / 0.962 / 0.983，全部高于 §70 当年标定的"不同风格历史对最高 0.873"，
        # 三部主导缓动还都是 ease-out。用户说的"最近几部有点像"就是这件事——**换皮没换骨**。
        # 阈值取 **0.97** 而不是 0.92/0.95：实测 p24→p25=0.9503、p25→p26=0.9827，而 p24 视差 12/12、
        # p25 视差 0/16——两部结构差得很远，只缓动分布像。**本门只量缓动、量不到结构**，
        # 把线画在 0.95 就会用窄代理否掉真做过的设计(§57 假阳性比漏报致命)。0.97 只拦"几乎同一份"。
        if sim > 0.97:
            print(f"⚠ 主风格换了({prev_style}→{cur_style})，但动法几乎是同一份")
            decl = _declared_diff(proj, prev)
            if decl:
                print("⚠ 已写明运动差异 → 降级为预警(创意决策权在人):")
                print("    " + decl)
                return 0
            print(f"FAIL: 风格档换了、缓动分布没换 = 用户眼里「还是那个节奏」")
            print(f"  - 余弦 {sim:.3f} > 0.97（本片与 {prev_name} 的运动语言几乎同一份）")
            if top_cur[0] == top_prev[0]:
                print(f"  - 主导缓动两部同为 `{top_cur[0]}`(本片 {top_cur[1]} 次 / 上一部 {top_prev[1]} 次)")
            print("  出路(任一): ① 换主导缓动——上一部 ease-out 占大头，本片就让 ease-in-out/匀速/弹簧占大头;")
            print("        ② 用上一部没用过的动效原语(slam_squash/pop_spring/fly_blur/seq_/motes 里挑没上过的);")
            print("        ③ 相机语言换一条(上一部全程缓推无平移 → 本片做真·多平面视差或景别切点);")
            print(f"        ④ 系列刻意延续 → KICKOFF 写 `A2c · 与上一部的运动差异: <≥30 字 + ≥2 场名 + ≥2 动效词>`。")
            return 1
        print(f"✓ 主风格换了且动法也不同: {prev_name}[{prev_style}] → {proj.name}[{cur_style}]"
              f"(缓动余弦 {sim:.3f} ≤0.97)")
        return 0

    errs = []
    print(f"⚠ 主风格连用两部同档: {prev_name} 与 {proj.name} 都是「{cur_style}」")
    if sim > 0.92:
        errs.append(f"缓动分布余弦 {sim:.3f} > 0.92 —— 运动语言和上一部几乎是同一份")
    if top_cur[0] == top_prev[0]:
        errs.append(f"主导缓动两部同为 `{top_cur[0]}`(本片 {top_cur[1]} 次 / 上一部 {top_prev[1]} 次)"
                    f" —— 换主缓动，或把至少一类元素改走别的曲线")
    if errs:
        decl = _declared_diff(proj, prev)
        if decl:
            print("⚠ 同档且缓动同构, 但 KICKOFF 已写明运动差异 → 降级为预警(创意决策权在人):")
            print("    " + decl)
            return 0
        print("FAIL: 同风格档 + 动效没做出区分 = 用户眼里「这几个片子一个样」")
        for e in errs:
            print("  - " + e)
        print("  出路(任一): ① 换主风格档; ② blend 一个副风格并把它的 motion 落到本片某几场;")
        print("        ③ 引入上一部没用过的动效原语/特效类型(渲染器已支持的或新写的);")
        print(f"        ④ 确实是系列刻意延续 → 在 KICKOFF 写一行"
              f"`A2c · 与上一部的运动差异: <≥30 字, 说清哪几场换了什么>` 再重跑本门。")
        return 1
    print(f"✓ 同档但动效已区分: 余弦 {sim:.3f} ≤0.92 且主导缓动 {top_prev[0]}→{top_cur[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
