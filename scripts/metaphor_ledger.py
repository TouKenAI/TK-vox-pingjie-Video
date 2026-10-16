#!/usr/bin/env python3
"""V8.0 隐喻概念账本 —— 防跨片"概念撞车" + 语义撞车(V7.1.1 加 narrative_semantic 字段)。

metaphors.json 格式(账号级共享,放工作区根):
{
  "天平": {"films": ["production8"], "semantic": "tilt/倾斜叙事"},
  "日历": {"films": ["production5","production7","production8"], "semantic": "时间线/历史"},
  ...
}

用法:
  python metaphor_ledger.py check 天平 日历               # 写 SUT 前查重
  python metaphor_ledger.py check 天平 --semantic 倾斜      # 查语义撞车(V7.1.1)
  python metaphor_ledger.py add 王冠 --film production9 --semantic 王权/象征
  python metaphor_ledger.py list --film production9
"""
from __future__ import annotations

import argparse
import json
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

from pathlib import Path


def load(p: Path) -> dict:
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        # 兼容老格式 {概念: [films]} → {概念: {films, semantic}}
        normed = {}
        for k, v in raw.items():
            if isinstance(v, list):
                normed[k] = {"films": v, "semantic": ""}
            else:
                normed[k] = v
        return normed
    return {}


def word_match(word: str, concept: str) -> bool:
    """子串双向匹配(check 原判据, 抽出来只为可读)。"""
    return word in concept or concept in word


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["check", "add", "list"])
    ap.add_argument("concepts", nargs="*", help="概念词(check/add)")
    ap.add_argument("--film", required=True, help="production 目录名")
    ap.add_argument("--semantic", default="", help="本概念的场景用途语义(如 倾斜/时间线/王权)")
    ap.add_argument("--ledger", type=Path, default=None)
    a = ap.parse_args()

    ledger_path = a.ledger
    if ledger_path is None:
        # 确定性解析：先本脚本所在仓库根(便携包/技能包都成立)，再退回 CWD 上溯。
        # 旧版只从 Path.cwd() 上溯——在别的目录跑 `pipeline ready` 就等于拿空账本比对，
        # 实测把已登记的概念判成"未撞车 rc=0"。CWD 不该参与"跟谁比"的决定。
        root_cand = Path(__file__).resolve().parents[1] / "metaphors.json"
        if root_cand.exists():
            ledger_path = root_cand
        else:
            for base in [Path.cwd(), *Path.cwd().parents]:
                cand = base / "metaphors.json"
                if cand.exists():
                    ledger_path = cand
                    break
                if (base / ".env").exists():
                    ledger_path = base / "metaphors.json"
                    break
            ledger_path = ledger_path or Path.cwd() / "metaphors.json"
    if a.action == "check" and not ledger_path.exists():
        # add 允许账本不存在(首次生成)；check 不行——"没有账本"和"没有撞车"是两件事。
        print(f"✗ FAIL: 隐喻账本不存在: {ledger_path} —— 无账本可比，不报 PASS")
        raise SystemExit(1)

    book = load(ledger_path)

    if a.action == "check":
        # 1) 概念名撞车(子串双向匹配)
        #    2026-09-27 production24 实录: check 收了 --film 却从不用它 → 本片 add 之后
        #    复查 ready --stage assets 必红(自己撞自己), 只能"先盖章后补登记"绕过。
        #    判据: 撞车只算**别的片**名下的登记; 只登记在本片名下的概念既不算撞车也不算新概念。
        used, fresh, own = {}, [], []
        for w in a.concepts:
            m_all = {c: v for c, v in book.items() if word_match(w, c)}
            cross = {c: v for c, v in m_all.items() if set(v.get("films", [])) - {a.film}}
            if cross:
                used.update(cross)
            elif m_all:
                own.extend(c for c in m_all if c not in own)
            else:
                fresh.append(w)
        print(f"新概念 {len(fresh)}: {'、'.join(fresh) if fresh else '(无)'}")
        if own:
            print(f"本片已登记 {len(own)}: {'、'.join(sorted(own))}(不算撞车)")
        if used:
            print("概念名撞车(换隐喻或做实质差异化):")
            for c, v in used.items():
                print(f"  ✗ {c} ({v.get('semantic','?')}): {', '.join(v.get('films',[]))}")
        # 2) 语义撞车(V7.1.1 新增,按 --semantic 查询;V8.1.1 修:未传 --semantic 时 sem_hit 未定义即引用 → 崩溃)
        sem_hit = {}
        if a.semantic:
            keyword = a.semantic
            sem_hit = {c: v for c, v in book.items()
                       if v.get("semantic") and (keyword in v["semantic"] or v["semantic"] in keyword)}
            if sem_hit:
                print(f"语义撞车(关键词: {keyword}):")
                for c, v in sem_hit.items():
                    print(f"  ! {c} ({v['semantic']}): {', '.join(v.get('films',[]))}")
                print("  → 你的 --semantic 与历史用法重叠,可能产生相同叙事,建议换角度")
        if not fresh and not used and not own:
            # 空清单不是"通过"。p17–p21 五部片就是这么一路 rc=0 走过来的: ready 里那条
            # `metaphor_ledger check --film X` 从不带概念参数 → 永远打印"新概念 0: (无) PASS"。
            # §57⑤ 的同一类病(空目录探针报 PASS)在 first_frame_check 上堵过, 这里漏了。
            print("FAIL: 概念清单为空 → 无从判撞车。写法: "
                  "metaphor_ledger check <概念1> <概念2> … --film <本片>(把本片 SUT 的视觉概念全列上)")
            sys.exit(1)
        if used or sem_hit:
            sys.exit(1)
        print("PASS: 全部概念+语义未撞车")
    elif a.action == "add":
        for c in a.concepts:
            entry = book.setdefault(c, {"films": [], "semantic": ""})
            if a.film not in entry["films"]:
                entry["films"].append(a.film)
            if a.semantic:
                entry["semantic"] = a.semantic
        ledger_path.write_text(json.dumps(book, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"added {len(a.concepts)} concepts for {a.film}" + (f' (semantic: {a.semantic})' if a.semantic else ''))
    else:  # list
        target = {c: v for c, v in sorted(book.items()) if a.film in v.get("films", [])}
        if not target:
            print(f"{a.film}: 无登记")
        for c, v in target.items():
            print(f"  {c}" + (f'  [semantic: {v["semantic"]}]' if v.get("semantic") else ''))


if __name__ == "__main__":
    main()
