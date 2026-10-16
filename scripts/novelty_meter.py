#!/usr/bin/env python3
"""V8.1.5 创意多样性仪表 —— 防"标准越好,片子越像"的同质化漂移。

第一性原理:门禁保下限,创意定上限。本工具提取每部片的"创意指纹"
(骨架/钩子句式/缓动分布/特效词汇/IP 出场),与邻近片比对,在**阶段①交审时**给出
多样性预警——创新问题在文案期发现,成本最低。

检查项(全部 WARN 级,不拦渲染;创意决策权在人):
  D1 骨架轮换:与上一部同骨架 → WARN("连续两片不得同骨架"规则的机器化)
  D2 钩子句式:与上一部同类(数字冲击/悬念反问/否定纠正/场景代入) → WARN
  D3 缓动分布:与邻近片余弦相似度 >0.92 → WARN(动效语言趋于模板)
  D4 特效词汇:全片仅 1 种特效类型 → WARN(视觉词汇单一)
  D5 新隐喻:metaphor_ledger 中本片概念全为历史复用 → WARN

用法:
  py -3.14 scripts/novelty_meter.py <项目目录>              # 指纹+全项检查
  py -3.14 scripts/novelty_meter.py <项目目录> --json-out qa/novelty.json
读取:chunks.json(钩子)、scene_s*.json(缓动/特效)、BRIEF.md(骨架声明)、
     palettes.json(配色)、metaphors.json(隐喻)、../production*/BRIEF.md(邻片)
退出码: 0(无 WARN 或仅提示)/ 1(有 D1-D5 WARN——交人裁决,不自动放行)
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

HOOK_TYPES = [
    ("数字冲击", r"\d"), ("悬念反问", r"[?？]"), ("否定纠正", r"不要|别再|不是|别再"),
    ("场景代入", r"你(有没有|是否|是否遇到)|想象"), ("信源引用", r"据|报道|消息|宣布"),
]


def hook_type(text: str) -> str:
    for name, pat in HOOK_TYPES:
        if re.search(pat, text[:30]):
            return name
    return "其他"


def norm_hist(hist: dict) -> dict:
    t = sum(hist.values()) or 1
    return {k: v / t for k, v in hist.items()}


def cos_sim(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values())) or 1
    nb = math.sqrt(sum(v * v for v in b.values())) or 1
    return dot / (na * nb)


def _ledger(proj: Path, fname: str):
    """跨片账本按『项目父目录 → 本脚本所在仓库根』确定性解析。
    旧版只认 proj.parent：项目建在工作区之外(或从别的目录敲 ready)时，账本读不到 →
    D5/D6 拿空集合比对，永远不报。2026-09-29 与 metaphor_ledger/palette_oklch 一起收口。"""
    for base in (proj.parent, Path(__file__).resolve().parents[1]):
        cand = base / fname
        if cand.exists():
            return cand
    return None


def fingerprint(proj: Path) -> dict:
    easings, fx = Counter(), Counter()
    for f in sorted(proj.glob("scene_s*.json")):
        sc = json.loads(f.read_text(encoding="utf-8"))
        for l in sc.get("layers", []):
            for k in l.get("keyframes", []):
                if k.get("ease"):
                    easings[k["ease"]] += 1
        for e in sc.get("effects", []):
            fx[e.get("type", "?")] += 1
    chunks = json.loads((proj / "chunks.json").read_text(encoding="utf-8"))
    skeleton = ""
    # V3.31 修死代码: 旧写法只认 BRIEF 里 `主风格: xxx` 且 xxx ∈ {cutout, chalk, popup}——
    # 五部片实测**一次都没命中过**(我们写的是中文"剪纸拼贴·背屏玻璃"这种), 所以 D6 从未生效,
    # 连用两部同风格(p20→p21)谁也没报。现改读 palette.json 的权威字段 + 主名归一。
    style = ""
    pal = proj / "palette.json"
    if pal.exists():
        try:
            sp = json.loads(pal.read_text(encoding="utf-8")).get("style_primary", "")
        except json.JSONDecodeError as e:
            raise SystemExit(f"[FAIL] {pal} 不是合法 JSON: {e}")
        if sp:
            from style_presets import base as _b
            style = _b(sp)
    brief = proj / "BRIEF.md"
    if brief.exists():
        bt = brief.read_text(encoding="utf-8")
        m = re.search(r"骨架[:：]\s*[*\s]*([A-C])", bt)
        skeleton = m.group(1) if m else ""
    palette = {}
    pp = _ledger(proj, "palettes.json")
    if pp:
        book = json.loads(pp.read_text(encoding="utf-8"))
        palette = (book.get(proj.name) or {}).get("colors", {})
    metas = []
    mp = _ledger(proj, "metaphors.json")
    if mp:
        book = json.loads(mp.read_text(encoding="utf-8"))
        metas = [c for c, v in book.items() if proj.name in (v.get("films") or [])]
    if not metas:
        # 新片的概念**还没进账本**(账本登记发生在 SUT 校验通过之后)，此时账本里查不到本片 →
        # D5 永远不触发。回落读 qa/concepts.txt(它现在也是 ready 的章输入)，让 D5 有真输入。
        cf = proj / "qa" / "concepts.txt"
        if cf.exists():
            metas = [c for c in re.split(r"[\s,、;；]+", cf.read_text(encoding="utf-8").strip()) if c]
    return {"name": proj.name, "skeleton": skeleton,
            "hook": hook_type(chunks[0].get("text", "")),
            "easing": norm_hist(dict(easings)), "fx": dict(fx),
            "palette": palette, "metaphors": metas, "style": style,
            "ip": any(l.get("id", "").startswith("ip_host")
                      for f in sorted(proj.glob("scene_s*.json"))
                      for l in json.loads(f.read_text(encoding="utf-8")).get("layers", []))}


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: novelty_meter.py <项目目录>")
        return 1
    proj = Path(sys.argv[1]).resolve()
    json_out = None
    if "--json-out" in sys.argv:
        i = sys.argv.index("--json-out")
        if i + 1 < len(sys.argv):
            json_out = Path(sys.argv[i + 1]).resolve()
    if not (proj / "chunks.json").exists():
        print("FAIL: chunks.json 不存在——阶段①交审时运行")
        return 1
    cur = fingerprint(proj)
    print(f"【{cur['name']} 创意指纹】骨架={cur['skeleton'] or '未声明!'} 钩子={cur['hook']} "
          f"特效={list(cur['fx'])} IP={'有' if cur['ip'] else '无'} 隐喻={len(cur['metaphors'])}个")

    neighbors = []
    for d in sorted(proj.parent.glob("production*")):
        if d.name == proj.name or not (d / "chunks.json").exists():
            continue
        try:
            neighbors.append(fingerprint(d))
        except Exception:
            pass
    # V8.2.1: 数字序(修复'production10'<'production2'字母序 bug)——与 palette_ledger 规则一致
    def _num_key(nm: str) -> int:
        m = re.search(r"\d+", nm)
        return int(m.group()) if m else 10 ** 9
    neighbors.sort(key=lambda n: _num_key(n["name"]))
    # V3.37: 历史 production* 目录已按用户裁定清空 → 邻片改从 film_digest.json 取。
    # 不接这层，D1/D2/D3/D6 全部走进 `prev = None` 分支静默不判——防趋同机制会整体失效，
    # 而它正是 §70 那次"用户说最近几部有点像"之后建起来的。
    if not neighbors:
        try:
            from film_digest import all_entries
            neighbors = [e for e in all_entries() if e["name"] != proj.name]
            if neighbors:
                print(f"  · 邻片目录已清，参照取自 film_digest.json（{len(neighbors)} 部入账）")
        except Exception as e:
            print(f"  ⚠ film_digest 不可用({e!r})：本片将无邻片可比")
    warns = []
    # D3/D4 量的是场景 JSON 里的缓动与特效分布; 阶段①还没建场景, 那时它们恒为 0 条,
    # 报出来必是假阳性(每次交审都响一声又没人能改)。无场景时打印"待复跑", 不计预警。
    scenes_here = bool(list(proj.glob("scene_s*.json")))
    if not scenes_here:
        print("  · D3/D4(缓动/特效多样性)需场景 JSON, 阶段①不适用 → 阶段⑥渲前复跑本工具")
    if not cur["skeleton"]:
        warns.append("D0 BRIEF 未声明叙事骨架——骨架轮换规则无法执行,先补声明")
    prev = neighbors[-1] if neighbors else None
    if prev:
        if cur["skeleton"] and cur["skeleton"] == prev["skeleton"]:
            warns.append(f"D1 骨架与上一部({prev['name']})同为 {cur['skeleton']}——违反'连续两片不同骨架',换 A/B/C")
        if cur["hook"] == prev["hook"]:
            warns.append(f"D2 钩子句式与上一部同类[{cur['hook']}]——换式:数字冲击/悬念反问/否定纠正/场景代入")
        es = cos_sim(cur["easing"], prev["easing"])
        if scenes_here and es > 0.92:
            warns.append(f"D3 缓动分布与上一部相似度 {es:.2f}>0.92——动效语言趋于模板,换主缓动或加新动效")
        if scenes_here and len(cur["fx"]) < 2:
            warns.append("D4 特效词汇仅 1 种——扩充(星尘/拼贴碎片/光带/粒子等,渲染器支持新 effect 类型)")
    _mp = _ledger(proj, "metaphors.json")
    _book = json.loads(_mp.read_text(encoding="utf-8")) if _mp else {}
    reused = [m for m in cur["metaphors"]
              if m in _book and len([f for f in _book[m].get("films", []) if f != cur["name"]]) > 0]
    if cur["metaphors"] and len(reused) == len(cur["metaphors"]):
        warns.append("D5 隐喻全部为历史复用——至少一个全新核心隐喻")
    last3 = [n for n in neighbors if n.get("style")]
    if cur.get("style"):
        last3.append({"name": cur["name"], "style": cur["style"]})
    last3 = last3[-3:]
    if len(last3) >= 3 and cur.get("style"):
        cnt = sum(1 for n in last3 if n["style"] == cur["style"])
        if cnt >= 3:
            warns.append("D6 风格连续 3 部[" + cur["style"] + "]——违反'连续 3 部同风格占比≤2/3',换风格或 BRIEF 注明'设计确认'")
    for w in warns:
        print("WARN:", w)
    result = {"project": cur["name"], "skeleton": cur["skeleton"], "hook": cur["hook"],
              "easing": cur["easing"], "fx": list(cur["fx"]), "ip": cur["ip"],
              "metaphors": cur["metaphors"], "warns": warns,
              "neighbor": prev["name"] if prev else None}
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if not warns:
        print("PASS: 多样性达标(骨架/钩子/动效/特效/隐喻有区分度)")
        return 0
    print(f"=== {len(warns)} 项多样性预警——交人裁决:系列呼应可接受时在 BRIEF 注明'设计确认',否则改稿 ===")
    # 本工具全程 advisory(交人裁决), 预警不是 FAIL。门禁退出码约定: 0=PASS(含 WARN), 1=FAIL。
    # 若在此 return 1, 一旦挂进 pipeline.run()(默认 allow=(0,))就会因一条建议性预警打死整条链。
    return 0


if __name__ == "__main__":
    sys.exit(main())
