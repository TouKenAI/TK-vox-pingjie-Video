#!/usr/bin/env python3
"""V6.9 polycheck 协议生成器 —— 从 scene JSON 自动生成 sut.json / cards_text.json。

polycheck_v66 依赖这两个协议文件; 本脚本消灭"手写 sut 与 scene JSON 脱节":
- sut.json: 每 chunk 的 units = 对应场景内全部文字卡(assets/text/*)的"上屏帧"
  (首个 opacity≥1 的 keyframe, 段内 0 基帧), grade 标 A —— 卡-词时间对齐即抽样子。
- cards_text.json: 优先读项目已有协议文件(卡片脚本写出的文案契约, 逐字准确);
  缺则用卡 id 占位并提示"由卡片脚本写出", 不可静默放行。
- chunk→scene 映射: 优先 chunks.json[i].scene (如 "S03"); 缺省按 chunk_0N→S0N 序数。

用法: py -3.12 <skill>/scripts/gen_sut_cards.py <项目目录> [--json-out qa/]
注意: scene JSON 帧号为段内 0 基; shot-plan 为"无转场全局帧"; splice_manifest 为"含转场全局帧"
(见 SKILL.md V6.9 三坐标系)。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

CHUNK_RE = re.compile(r"chunk_(\d+)")


def scene_no_for_chunk(chunk: dict, idx: int) -> int | None:
    sc = chunk.get("scene", "")
    m = re.fullmatch(r"[Ss](\d{2})", str(sc))
    if m:
        return int(m.group(1))
    m = CHUNK_RE.search(str(chunk.get("id", "")))
    if m:
        return int(m.group(1))
    return idx + 1


def card_enter_frame(scene: dict, card_id: str) -> int | None:
    """文字卡上屏帧 = keyframes 中首个 opacity 完全亮起(≥1.0)的帧(段内 0 基)."""
    for layer in scene.get("layers", []):
        if layer.get("id") != card_id:
            continue
        kfs = layer.get("keyframes", [])
        for kf in kfs:
            if float(kf.get("opacity", 0)) >= 1.0:
                return int(kf["frame"])
        if kfs:
            return int(kfs[0]["frame"])
    return None


def _is_design_sut(path) -> bool:
    """人工语义 SUT 的可观测特征: 单元带 visual(视觉表达描述)字段, 或存在 B/C 级。
    本工具自产的卡级视图(text 形如 't_x:t_x'、全 A)不含这些特征。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    units = [u for c in data if isinstance(c, dict) for u in c.get("units", [])]
    return any("visual" in u or u.get("grade") in ("B", "C") for u in units)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", type=Path)
    ap.add_argument("--in-place", action="store_true",
                    help="允许覆盖已存在的人工语义 sut.json(默认不覆盖, 实测帧另存 qa/sut_measured.json)")
    ap.add_argument("--json-out", type=Path, default=None,
                    help="输出目录; 默认=项目根目录(polycheck 读取位置)")
    args = ap.parse_args()
    proj: Path = args.proj

    if not (proj / "chunks.json").exists():
        print("FAIL: chunks.json 不存在——本工具按 chunk 顺序生成卡级 SUT, 需在阶段①之后", file=sys.stderr)
        return 1
    chunks = json.loads((proj / "chunks.json").read_text(encoding="utf-8-sig"))
    cards_contract = proj / "cards_text.json"

    if cards_contract.exists():
        cards_text = json.loads(cards_contract.read_text(encoding="utf-8-sig"))
    else:
        cards_text = {}

    sut, used_cards, missing = [], set(), []
    for idx, chunk in enumerate(chunks):
        n = scene_no_for_chunk(chunk, idx)
        sp = proj / f"scene_s{n:02d}.json"
        if not sp.exists():
            print(f"[SKIP] chunk={chunk.get('id')} 缺 scene_s{n:02d}.json", file=sys.stderr)
            continue
        sc = json.loads(sp.read_text(encoding="utf-8-sig"))
        events = []
        for l in sc.get("layers", []):
            if not str(l.get("path", "")).startswith("assets/text"):
                continue
            cid = l["id"]
            f = card_enter_frame(sc, cid)
            if f is None:
                continue
            events.append((f, cid))
            used_cards.add(cid)
        events.sort()
        units = [{"text": f"{cid}:{cards_text.get(cid, cid)}", "grade": "A",
                  "scene": f"S{n:02d}", "frame": f} for f, cid in events]
        if not units:
            continue
        sut.append({"chunk": chunk.get("id", f"chunk_{idx+1:02d}"),
                    "type": chunk.get("emotion", ""), "has_number": False,
                    "sentence": chunk.get("text", ""), "units": units})

    out = (args.json_out if args.json_out else proj)
    if args.json_out:
        out.mkdir(parents=True, exist_ok=True)
    target = out / "sut.json"
    # V3.16 设计 SUT 保护(playbook §51③): 本工具的卡级视图会丢掉人工 A/B/C 分级与"视觉表达描述",
    # 覆盖后 semantic_check 变成全 A 的假通过、polycheck 的 text/align 也失去比对依据。
    # 检测到语义 SUT 时默认另存实测帧文件, 只有 --in-place 才覆盖。
    if target.exists() and not args.in_place and _is_design_sut(target):
        target = out / "qa" / "sut_measured.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[保护] 检测到人工语义 SUT, 不覆盖 {out / 'sut.json'}; 实测帧已另存 -> {target}\n"
              f"       (确需覆盖请加 --in-place)", file=sys.stderr)
    target.write_text(json.dumps(sut, ensure_ascii=False, indent=2), encoding="utf-8")

    if not cards_text:
        for cid in sorted(used_cards):
            missing.append(cid)
        print("[WARN] 项目缺 cards_text.json(卡片文案契约), 已用卡 id 占位 —— "
              "polycheck --text 将全部 WARN。请由卡片脚本/项目写出逐字文案后重跑本脚本。", file=sys.stderr)

    total = sum(len(s["units"]) for s in sut)
    print(f"SUT: {len(sut)} 段 / {total} 个 A 级单元 -> {target}")
    for s in sut:
        print("  ", s["chunk"], [f"{u['scene']}@{u['frame']}" for u in s["units"]])
    if missing:
        print("缺文案的卡:", ", ".join(missing))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())