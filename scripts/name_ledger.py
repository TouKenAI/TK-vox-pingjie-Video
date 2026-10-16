#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.28 §66 名字对账门：口播点到某个名字的那几秒，画面上必须是**那个名字**。

起因（p17 实录，用户原话"讲的是 flash，画面显示的是 PRO"）：全产线的门量的都是
"帧内自不自洽"——密度、越界、对比度、撞色——**没有一扇门量"像不像旁白说的"**。
所以一部片可以每一道门都绿，然后把 A 讲成 B。

本门把"谁在什么时候被点名"从文案里抽出来（NAMES.json，**必须在设计场景之前写**），
再拿真实场景 JSON 的可见层去对：

  R1 身份先于属性   名字被念到的那一段，可见层里必须有一层的 label 含这个名字。
  R2 排他           那一段里若只有它的**同类兄弟名**在屏上 → FAIL（讲 A 屏上只有 B）。
  R3 兄弟须同时可分 同框多个兄弟名允许（对比场本来就要两个都带名），但主名必须在。
  R5 撞名门         裸写型号不带厂牌（"18 Pro"/"Max"/"17 Pro" 而没有"小米"/"iPhone"）= FAIL。
  R0 反空转         场景里一个 label 都没有 → FAIL。没有登记的对账等于没对，
                    这条专门防"门建了但永远绿"。

退出码沿用全仓约定：**0 = PASS(含 WARN)，1 = FAIL**。
NAMES.json 不存在时只 WARN 不拦——历史片没建名单，拦它们是把真红当假红的教科书式误伤。

用法: py scripts/name_ledger.py production19 [--verbose]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from scene_timing import Timing, FPS  # noqa: E402

OP_VISIBLE = 0.5      # 与 semantic_check 同口径：opacity 过半才算"在屏上"
COVER_MIN = 0.6       # 名字要盖住这段点名的 60% 以上，不能靠一帧闪过去
BRANDS = ("小米", "iPhone", "苹果")
BARE_MODELS = ("18 Pro", "18 Pro Max", "17 Pro", "Max")


def name_in_label(name, label):
    """名字必须作为**独立词**出现在 label 里，不能只是某个更长词的一块。

    ⚠ 2026-09-25 p20 实测到的假绿：口播念「应用」，屏上只有「应用商店」，
    旧版 `name in label` 直接判通过——**这正是本门要抓的那种错**，只不过换到了子串层面。
    规则：只看**后一个字**——紧跟汉字说明它是某个更长词的前缀（应用→应用商店），不算；
    前一个字不看，中文里「那块背屏」「能交互的应用」都是正当提及。
    """
    if not label:
        return False
    if label.strip() == name.strip():
        return True
    i = label.find(name)
    while i >= 0:
        j = i + len(name)
        after = label[j] if j < len(label) else ""
        if after == "" or not ("一" <= after <= "鿿"):
            return True
        i = label.find(name, i + 1)
    return False


def layer_visible(layer, frame):
    """线性插值该帧的 opacity；keyframes 未覆盖时按最后一段取值。"""
    kfs = sorted(layer.get("keyframes", []), key=lambda k: k["frame"])
    if not kfs:
        return False
    if frame <= kfs[0]["frame"]:
        return float(kfs[0].get("opacity", 1.0)) >= OP_VISIBLE
    op = float(kfs[-1].get("opacity", 1.0))
    for a, b in zip(kfs, kfs[1:]):
        if a["frame"] <= frame <= b["frame"]:
            t = (frame - a["frame"]) / max(1, b["frame"] - a["frame"])
            op = a.get("opacity", 1.0) + (b.get("opacity", 1.0) - a.get("opacity", 1.0)) * t
            break
    return float(op) >= OP_VISIBLE


def window(T, chunk, phrase):
    """点名窗口（本场帧号）：该短语 start..end，含 LEAD 偏移。"""
    hits = [p for p in T.phrases[chunk] if phrase in p["phrase"] or p["phrase"] in phrase]
    if not hits:
        raise SystemExit(f"[FAIL] chunk_{chunk:02d} 锚点「{phrase}」在 phrase_timing 里找不到")
    p = hits[0]
    lead = T.lead(chunk)
    return round((lead + p["start"]) * FPS), round((lead + p["end"]) * FPS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    proj = a.project.resolve()

    nf = proj / "NAMES.json"
    if not proj.is_dir():
        # 路径写错时旧版报"没有 NAMES.json，本门跳过"并 rc=0——那是对着一个不存在的项目
        # 打绿(§81①"PASS 0 次不是通过")。"没建名单"只对历史片豁免，"项目不存在"没有豁免理由。
        print(f"✗ FAIL: 项目目录不存在: {proj} —— 路径写错，不是'本片没有 NAMES.json'")
        return 1
    if not nf.exists():
        print(f"WARN: {proj.name} 没有 NAMES.json —— 未建名单，本门跳过。"
              f"（新片必须先写名单再设计场景，见 playbook §66）")
        return 0
    names = json.loads(nf.read_text(encoding="utf-8"))["names"]
    T = Timing(proj)

    scenes = {}
    for f in sorted(proj.glob("scene_s*.json")):
        n = int(f.stem.replace("scene_s", ""))
        scenes[n] = json.loads(f.read_text(encoding="utf-8"))
    if not scenes:
        print("[FAIL] 一帧场景 JSON 都没有——本门要在 build_scenes 之后跑，现在没东西可对")
        return 1

    errors, warns, oklines = [], [], []
    for n, sc in scenes.items():
        labs = [L for L in sc.get("layers", []) if L.get("label")]
        if not labs:
            errors.append(f"S{n:02d} 一个 label 都没登记（{len(sc.get('layers', []))} 层全是无名层）"
                          f" —— 没有登记的对账等于没对，见 R0")

    for e in names:
        # V3.40 修空转：旧版要求 `kind=="named"`，而 p24/p25 的 NAMES.json 从没写过这个字段
        # → 全部条目被 continue 跳过 → 0 次点名 → 报 PASS。缺省即视为具名条目，只有显式
        # 声明的非具名 kind 才跳过。真正的"没在查"由下面的 0-check 守卫兜住。
        if e.get("kind") not in (None, "named"):
            continue
        if "spoken_in" not in e:
            # 缺字段要报得懂，不许抛 KeyError：p22 实录——NAMES.json 用了 `scenes` 而不是
            # `spoken_in`，整道门以 traceback 收场，看不出是"我的表写错"还是"门坏了"。
            raise SystemExit(f"[FAIL] NAMES.json 条目「{e.get('name','?')}」缺 `spoken_in`"
                             f"（该名字被念到的 chunk 号列表，1 基）。现有字段: {sorted(e)}")
        name, sibs = e["name"], e.get("must_not_show_instead", [])
        for raw_chunk in e["spoken_in"]:
            # V3.40: spoken_in 历史上既写过 1 也写过 "chunk_01"（p24/p25 全是后者），
            # 旧版直接把字符串喂给 scene_of_chunk → KeyError 崩栈。两种都收。
            chunk = int(str(raw_chunk).split("_")[-1])
            s = T.scene_of_chunk(chunk)
            if s not in scenes:
                errors.append(f"「{name}」点名在 chunk_{chunk:02d} → S{s:02d}，但没有 scene_s{s:02d}.json")
                continue
            # 点名窗口：优先用 NAMES 里显式声明的 anchor；再退到"名字的任何词素出现在哪句"。
            # anchor 可以是字符串(该名字每处点名都说这个短语)，也可以是 {段号: 短语}
            # ——同一个名字在不同段里被说成不同字面时（如"透明特别版"在收尾被缩略成"透明版"）用后者。
            # ⚠ 不再静默回退到该段第一句：p19 实录——口播把「透明特别版」说成「透明版就是收藏」，
            #    字面匹配失败后旧版拿第一句当窗口，等于**去查了错误的时刻**还报 FAIL，
            #    把画面问题误报成名字问题。定位不到就明说，让人补 anchor。
            anch = e.get("anchor")
            ph = anch.get(str(chunk)) if isinstance(anch, dict) else anch
            if ph and not any(ph in p["phrase"] or p["phrase"] in ph for p in T.phrases[chunk]):
                raise SystemExit(f"[FAIL] 「{name}」的 anchor「{ph}」不在 chunk_{chunk:02d} 的短语里，"
                                 f"可选：{[p['phrase'] for p in T.phrases[chunk]]}")
            if not ph:
                # V3.40: 先要"整名在短语里"，再退到"每个词素都在"。旧版用 any()，
                # 「10 万份」的词素 10 撞上「9 月 28 号到 10 月 7 号」→ 去查了错误的时刻。
                toks = [t for t in name.split() if t]
                ph = next((q["phrase"] for q in T.phrases[chunk] if name in q["phrase"]), None)                     or next((q["phrase"] for q in T.phrases[chunk]
                             if toks and all(t in q["phrase"] for t in toks)), None)
            if not ph:
                errors.append(f"「{name}」在 chunk_{chunk:02d} 里找不到点名窗口——"
                              f"口播可能把它缩略说了；给 NAMES.json 这条补 `anchor` "
                              f"（可选：{[p['phrase'] for p in T.phrases[chunk]]}）")
                continue
            f0, f1 = window(T, chunk, ph)
            span = max(1, f1 - f0)
            frames = [f0 + round(i * span / 10) for i in range(11)]
            vis_names, cover = [], 0
            for fr in frames:
                got = [L["label"] for L in scenes[s].get("layers", [])
                       if L.get("label") and layer_visible(L, fr)]
                if any(name_in_label(name, g) for g in got):
                    cover += 1
                vis_names += got
            ratio = cover / len(frames)
            uniq = sorted(set(vis_names))
            if ratio < COVER_MIN:
                only_sib = [v for v in uniq if any(sb in v for sb in sibs)]
                msg = (f"「{name}」在 chunk_{chunk:02d}(S{s:02d} f{f0}~{f1}) 只有 {ratio*100:.0f}% 的时间"
                       f"带着这个名字在屏上")
                if only_sib and not any(name_in_label(name, v) for v in uniq):
                    errors.append(msg + f" —— 而屏上站着它的同类兄弟 {only_sib}。"
                                        f"这正是「讲 A 屏上是 B」的形状")
                else:
                    errors.append(msg + f"（该窗可见 label: {uniq or '无'}）")
            else:
                oklines.append(f"  ✓ {name:16s} chunk_{chunk:02d} S{s:02d} f{f0}~{f1} "
                               f"{ratio*100:3.0f}%  可见={uniq}")

    # R5 撞名门：任何写着型号的字面卡，必须同时带厂牌
    for n, sc in scenes.items():
        for L in sc.get("layers", []):
            lab = L.get("label") or ""
            if not lab:
                continue
            if any(m in lab for m in BARE_MODELS) and not any(b in lab for b in BRANDS):
                errors.append(f"S{n:02d} 层 {L.get('id')} 的 label「{lab}」裸写型号不带厂牌"
                              f" —— 同期在售 iPhone 18 Pro 与它撞名(R5)")

    print(f"name_ledger: {len(names)} 条名字 / {len(scenes)} 场场景")
    if a.verbose:
        print("\n".join(oklines))
    for w in warns:
        print("  WARN:", w)
    if errors:
        print(f"\n❌ [FAIL] {len(errors)} 处名字没对上（§66 的形状）:")
        for e in errors:
            print("   -", e)
        return 1
    if names and not oklines:
        # V3.40 空转守卫：有名单、无错误、却一次都没查 = 门没吃到输入(字段名/kind/格式对不上)。
        # §57⑤/§70 的老病：空输入报 PASS 比没门更危险，因为它让人以为查过了。
        print(f"\n❌ [FAIL] NAMES.json 有 {len(names)} 条名字，但实际点名检查 0 次 —— "
              f"门在空转，不是通过。逐条核对字段：`kind` 只接受缺省或 \"named\"，"
              f"`spoken_in` 必须是 1 基 chunk 号(1 或 \"chunk_01\" 均可)。")
        return 1
    print(f"✅ PASS: 每个被点名的名字，都在被点名的那几秒带着自己的名字在屏上"
          f"（{len(oklines)} 次点名，覆盖率 ≥{COVER_MIN*100:.0f}%）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
