#!/usr/bin/env python3
"""背景契约注入的回归测试(离线, 不打 API)。

跑法: py -3.14 scripts/test_bg_contract.py
断言两件事:
  1. 病灶可复现: p16 的 jobs_bg.json 里被判"自相矛盾"的, 必须**恰好**是 clutter 点名的那 4 张。
  2. 契约不带画风: 尾巴里不许出现任何颜色词或流派名词, 颜色只能来自 palette.json 参数。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gen_assets import BG_SHEET_ROLE, bg_contract  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

# clutter 点名的四场里, **真正自相矛盾**的三张: 图纸本身就是主体。
# bg17(夹板从左下角探进来)不算矛盾 —— 夹板待在边缘合法, 它的问题是"画过头", 由密度预算管。
# 判据混了两种失效, 门就会给出错误的修复建议(第一版我就把 clipboard 塞进了触发词表)。
P16_EXPECTED_CONFLICT = {"bg03_unit_opened.png", "bg04_layer_slice.png", "bg10_repo_open.png"}
# 契约里一旦混进这些词, 就等于把某一片的画风焊死给以后所有片(p12 是深酒红底, 会被"no dark
# background"直接毁掉)。它们只能出现在 palette 注入的那一句里。
BANNED_IN_TAIL = re.compile(
    r"\b(vintage|sepia|warm paper|cream|dark background|watercolor|ukiyo|ukiyo-e|noir|"
    r"blueprint|halftone|cel[\s-]?shade|ink wash|pastel|muted|neon)\b", re.I)


# 契约尾巴里出现两个词以上的全大写片段, 就会被模型当成标签/钢印**画进画面**(p16 bg17 实证:
# `CRITICAL COMPOSITION:` 变成右上角红印章)。契约只能是小写散文。
CAPS_LABEL = re.compile(r"\b[A-Z]{2,}[A-Z\s:()]{2,}\b")


def tail_of(name, role=None, ground=""):
    body = ("a wide field with small marks at the edges" if role is None
            else "a tall rectangular cross-section diagram of a service unit")
    _, added, _, _ = bg_contract(name, body, role, ground)
    return added[0] if added else ""


def main() -> int:
    fails = []

    # V3.37 仓库清理删掉了 production* 目录, 本测试曾硬依赖 p16/jobs_bg.json → 必然
    # FileNotFoundError 且 rc=1(回归测试永远红=没人再看它)。实录回归降级为"有文件才跑"。
    p16_jobs = ROOT / "production16" / "jobs_bg.json"
    if p16_jobs.exists():
        jobs = json.loads(p16_jobs.read_text(encoding="utf-8"))
        hit = {j["name"] for j in jobs if bg_contract(j["name"], j["prompt"], j.get("bg_role"))[2]}
        if hit != P16_EXPECTED_CONFLICT:
            fails.append(f"p16 矛盾判定漂移: 期望 {sorted(P16_EXPECTED_CONFLICT)}, 实得 {sorted(hit)}")
        print(f"  p16 jobs_bg: {len(hit)}/{len(jobs)} 张判自相矛盾 → {sorted(hit)}")

        # 声明 bg_role=sheet 后必须放行(否则契约就是死路, 没人能用)
        p04 = next(j["prompt"] for j in jobs if j["name"] == "bg04_layer_slice.png")  # 按名取, 不按序号
        ok = bg_contract("bg04_layer_slice.png", p04, BG_SHEET_ROLE)[2]
        if ok:
            fails.append(f"声明 bg_role=sheet 仍被拒: {ok[0][:80]}")
    else:
        print("  SKIP: production16 已清空(V3.37), p16 实录回归不可用——冲突判据由下方合成正控覆盖")

    # 合成正控(p16 缺位时冲突判据的唯一覆盖): 正文要求实体剖面图却没声明 bg_role=sheet → 必须拒
    _c = bg_contract("bg99_synthetic.png",
                     "a tall rectangular cross-section diagram of a service unit", None)[2]
    if not _c:
        fails.append("合成正控失效: 正文要求剖面实体却未声明 bg_role=sheet, 契约竟放行")

    for name in ("bg05_envelope_path.png", "prop_shell_lid.png", "ip_wave.png", "sfx_whoosh.png"):
        r = bg_contract(name, "whatever the author wrote", None)[2]
        if r:
            fails.append(f"{name} 不该被背景契约管, 却报错: {r[0][:60]}")

    for role in (None, BG_SHEET_ROLE):
        t = tail_of("bg99_x.png", role)
        if CAPS_LABEL.search(t):
            fails.append(f"{role or 'stage'} 尾巴含全大写标题片段 {CAPS_LABEL.findall(t)} —— "
                         f"模型会把它当钢印画进画面(p16 bg17 实证)")
        if BANNED_IN_TAIL.search(t):
            fails.append(f"{role or 'stage'} 契约尾巴混进了画风词: "
                         f"{BANNED_IN_TAIL.findall(t)} —— 会把某一片的画风焊给以后所有片")
        if "#" in t:
            fails.append(f"{role or 'stage'} 尾巴在没有 palette 的情况下出现了十六进制色")

    t = tail_of("bg99_x.png", None, " The background field colour is #2A141A;")
    if "#2A141A" not in t:
        fails.append("palette 注入没生效: 地色没进尾巴")

    # 夹板/清单板待在边缘是合法的, 不该被当成"主体自相矛盾"(第一版的 clipboard 就是假阳性)
    cb = bg_contract("bg17_checklist.png",
                     "a clipboard outline entering from the lower left with three empty checkbox squares",
                     None)
    if cb[2]:
        fails.append(f"边缘物件被误判为矛盾: {cb[2][0][:70]}")

    # 两条尾巴都必须带**数值**密度预算 —— "标记只放边缘"管不住边缘本身能画多密(bg17 实证)
    for role in (None, BG_SHEET_ROLE):
        if "one tenth" not in tail_of("bg99_y.png", role):
            fails.append(f"{role or 'stage'} 尾巴缺数值密度预算, 拦不住 bg17 那种'画过头'")

    print("  契约尾巴画风词扫描: " + ("干净" if not any("画风词" in f for f in fails) else "有污染"))
    for f in fails:
        print("FAIL:", f)
    print("PASS: 背景契约只带骨架, 皮肤归 --style + palette.json" if not fails else f"{len(fails)} 条断言失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
