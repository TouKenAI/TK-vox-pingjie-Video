#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""film_digest.py —— 把"上一部"压缩成几十 KB 的账本（V3.37）。

**为什么需要它**：`motion_similarity_check`(缓动余弦) 与 `novelty_meter`(骨架/钩子/风格连用)
都是靠扫 `../production*` 找前一部来工作的。历史片目录一旦被清（2026-09-27 用户裁定：
141 GB 历史产出全删，只留工作流），这两道门会走进 `找不到前一部可比 → 放行` 分支——
**门还在，参照物没了，于是永远绿**。这正是本仓库反复记过的病：静默放行的门比没门更危险。

所以删目录之前，先把这两道门**真正要读的那几个事实**抽出来存进根目录 `film_digest.json`：
每部片一条，含主风格档、四色、缓动分布、特效词汇、骨架、钩子、IP 在场、以及 KICKOFF 的
A1/A2/图腾原文（F 表逐项对比要用）。体积按 23 部片算约 30 KB。

用法：
  py -3.14 scripts/film_digest.py build            # 扫现存 production*，增量写入账本
  py -3.14 scripts/film_digest.py show [productionN]
  py -3.14 scripts/film_digest.py prev <本项目名>   # 查"上一部"是谁（供门调用）

退出码 0=正常 / 1=没有可入账的项目目录
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent
LEDGER = ROOT / "film_digest.json"


def _num(name: str) -> int:
    m = re.search(r"\d+", name)
    return int(m.group()) if m else -1


def _grab_kickoff(proj: Path) -> dict:
    """KICKOFF 里 F 表逐项对比要用的三句原文（A1 世界 / A2 风格三特征 / 核心图腾）。"""
    out = {"A1": "", "A2": "", "totem": ""}
    k = proj / "KICKOFF.md"
    if not k.exists():
        return out
    txt = k.read_text(encoding="utf-8")
    for key, pat in (("A1", r"\*\*A1[^\n]*\n+\**>?\s*([^\n]+)"),
                     ("A2", r"\*\*A2\b[^\n]*\n+\**>?\s*([^\n]+)"),
                     ("totem", r"图腾\s*[=＝:：]\s*\**([^\n]+)")):
        m = re.search(pat, txt)
        if m:
            out[key] = m.group(1).strip()[:220]
    return out


def record(proj: Path) -> dict:
    """一部片的指纹。缓动/风格用**门自己的函数**算，不另写一份（两份实现早晚漂移）。"""
    ent = {"num": _num(proj.name)}
    try:
        from motion_similarity_check import easing_hist, _style_of
        hist = easing_hist(proj)
        ent["style_primary"] = _style_of(proj) or ""
        ent["easing"] = dict(hist.most_common()) if hist else {}
    except Exception as e:
        ent["style_primary"] = ""
        ent["easing"] = {}
        ent["err_ms"] = repr(e)
    try:
        from novelty_meter import fingerprint
        fp = fingerprint(proj)
        ent["skeleton"] = fp.get("skeleton") or ""
        ent["hook"] = fp.get("hook") or ""
        ent["fx"] = sorted(fp.get("fx") or [])
        ent["ip"] = bool(fp.get("ip"))
        ent["metaphors"] = len(fp.get("metaphors") or [])
    except Exception as e:
        ent["err_nv"] = repr(e)
    pal = proj / "palette.json"
    if pal.exists():
        try:
            d = json.loads(pal.read_text(encoding="utf-8"))
            ent["colors"] = {k: v for k, v in d.items() if isinstance(v, str) and v.count(",") == 2}
        except Exception:
            pass
    ent.update(_grab_kickoff(proj))
    ent["has_scenes"] = bool(list(proj.glob("scene_s*.json")))
    return ent


def load() -> dict:
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"[FAIL] {LEDGER} 解析失败 —— 账本坏了要手工修，不能当空账本用")
    return {"films": {}}


def prev_entry(cur_name: str) -> dict | None:
    """给门用的查询：账本里编号小于本片的那一部（含 name 字段）。找不到返回 None。"""
    cur = _num(cur_name)
    if cur < 0:
        return None
    led = load()
    cands = [(int(e.get("num", -1)), nm, e) for nm, e in led["films"].items()
             if int(e.get("num", -1)) >= 0 and int(e.get("num", -1)) < cur]
    if not cands:
        return None
    n, nm, e = max(cands)
    out = dict(e)
    out["name"] = nm
    return out


def all_entries() -> list[dict]:
    """按编号升序返回全部入账片（novelty_meter 拿它当"邻片"列表）。"""
    led = load()
    out = []
    for nm, e in led["films"].items():
        if int(e.get("num", -1)) < 0:
            continue
        d = dict(e)
        d["name"] = nm
        out.append(d)
    out.sort(key=lambda d: d["num"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("build", "show", "prev"))
    ap.add_argument("arg", nargs="?", default="")
    a = ap.parse_args()
    led = load()

    if a.mode == "build":
        dirs = [d for d in ROOT.glob("production*")
                if d.is_dir() and _num(d.name) >= 0 and (d / "palette.json").exists()]
        if not dirs:
            print("[FAIL] 现存没有任何带 palette.json 的 production* 目录 —— 没有可入账的片")
            return 1
        for d in sorted(dirs, key=lambda x: _num(x.name)):
            led["films"][d.name] = record(d)
        LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"✓ 已入账 {len(led['films'])} 部片 → {LEDGER.name}（{LEDGER.stat().st_size/1024:.0f} KB）")
        for nm in sorted(led["films"], key=lambda n: _num(n))[-4:]:
            e = led["films"][nm]
            top = max(e.get("easing", {}).items(), key=lambda kv: kv[1]) if e.get("easing") else ("—", 0)
            print(f"  {nm:14s} 风格={e.get('style_primary') or '?':10s} 骨架={e.get('skeleton') or '?'} "
                  f"主缓动={top[0]}({top[1]}) 特效={len(e.get('fx', []))}种")
        return 0

    if a.mode == "show":
        if a.arg:
            e = led["films"].get(a.arg)
            if not e:
                raise SystemExit(f"[FAIL] 账本里没有 {a.arg}（现有 {sorted(led['films'])[-6:]}…）")
            print(json.dumps(e, ensure_ascii=False, indent=1))
            return 0
        print(f"账本 {LEDGER.name}: {len(led['films'])} 部")
        for nm in sorted(led["films"], key=lambda n: _num(n)):
            e = led["films"][nm]
            print(f"  {nm:14s} {e.get('style_primary') or '?':12s} 骨架={e.get('skeleton') or '?'} "
                  f"钩子={e.get('hook') or '?'} 缓动档={len(e.get('easing', {}))}")
        return 0

    # prev: 给门用的"上一部是谁"
    if not a.arg:
        raise SystemExit("[FAIL] prev 需要当前项目名，如 `film_digest.py prev production24`")
    cur = _num(a.arg)
    if cur < 0:
        raise SystemExit(f"[FAIL] {a.arg} 名字里没有编号，无法定位上一部")
    cands = [nm for nm, e in led["films"].items() if int(e.get("num", -1)) < cur]
    if not cands:
        print("[NONE] 账本里没有编号更小的片（第一部片，或账本未建）")
        return 0
    best = max(cands, key=lambda nm: int(led["films"][nm]["num"]))
    print(best)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
