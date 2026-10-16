#!/usr/bin/env python3
"""V3.31 彩带按本片配色重绘 —— 终结"五部片甩同一张 confetti_sheet.png"。

起因: `new_project.py` 把 `scripts/_templates/confetti_sheet.png` **按字节拷**进每个项目，
并在账本里写 `production=<本片>`、`origin="template"`。于是 preflight 的"跨片复用"门
(比 `ent['production']`) 被账本自己**撒的谎**遮住了: 文件确实 5 部全同，账本却说它出生在本片。
p17→p21 实测 md5 全等。

用法:
  py -3.14 scripts/make_confetti.py <项目目录>          # 按 palette.json 重绘并改写账本
  py -3.14 scripts/make_confetti.py <项目目录> --check   # 只判: 有 palette 却仍是模板原件 → rc=1
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "_templates" / "confetti_sheet.png"
sys.path.insert(0, str(HERE))
# 精灵盒从 motes() 的**真实产物**读, 不在这里再抄一份字面量。
# (第一版我按"500 宽 ÷ 60 步进"自己推, 推出第 9 格 x=494 越界 IndexError——
#  凡"两处描述同一几何"的门, 必有一处先腐烂。见 playbook §59⑩ 同族。)
from build_scenes_template import motes as _motes  # noqa: E402
SPRITES = [list(b) for b in _motes(0, 1)["sprite_boxes"]]


def _mix(c, t, target=255):
    return tuple(round(a + (target - a) * t) for a in c) if t >= 0 else tuple(round(a * (1 + t)) for a in c)


def palette_colors(pal: dict) -> list[tuple[int, int, int]]:
    """8 格彩带 → 主强调/副强调/墨/纸白 + 四个派生明度。全部由本片配色算出，
    所以任何两部片的彩带 md5 不可能相同(配色门已保证四色不撞)。"""
    def rgb(k, d):
        raw = pal.get(k) or d
        return tuple(int(v) for v in str(raw).replace(" ", "").split(","))
    accent, accent2, ink = rgb("accent", "224,106,32"), rgb("accent2", "58,140,90"), rgb("fg", "43,34,26")
    bg = rgb("bg", "243,236,221")
    return [accent, accent2, ink, _mix(bg, 0.55),
            _mix(accent, 0.35), _mix(accent2, 0.40), _mix(accent, -0.35), _mix(accent2, -0.30)]


def _tpl_hash() -> str:
    return hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()


def current(project: Path) -> Path:
    return project / "assets" / "source" / "confetti_sheet.png"


def check(project: Path) -> int:
    dst, pal = current(project), project / "palette.json"
    if not dst.exists():
        print("[SKIP] 本片没有 confetti_sheet.png —— 不用彩带就无需重绘")
        return 0
    if not pal.exists():
        print("[SKIP] 还没有 palette.json → 暂不能重绘(建配色后重跑本工具)")
        return 0
    if hashlib.sha256(dst.read_bytes()).hexdigest() == _tpl_hash():
        print("FAIL: 彩带还是模板原件(与其余各片逐字节相同) —— 跑 "
              f"`py -3.14 {Path(__file__).name} {project.name}`")
        return 1
    print("✓ 彩带已按本片配色重绘")
    return 0


def retint(project: Path) -> int:
    dst, pal = current(project), project / "palette.json"
    if not TEMPLATE.exists():
        raise SystemExit(f"[FAIL] 模板缺失: {TEMPLATE}(便携包版本过旧?)")
    if not pal.exists():
        raise SystemExit(f"[FAIL] {pal} 不存在 —— 彩带配色必须由本片 palette.json 派生, 不许用模板默认色")
    cols = palette_colors(json.loads(pal.read_text(encoding="utf-8")))
    out = Image.open(TEMPLATE).convert("RGBA")
    px = out.load()
    for i, box in enumerate(SPRITES):
        tgt = cols[i % len(cols)]
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                if px[x, y][3] > 0:
                    px[x, y] = (*tgt, px[x, y][3])
    out.save(dst)
    # 账本必须跟着改: 旧条目写着模板的 sha256 + origin=template, 留着就是"账本与像素不一致"
    led = project / "assets" / "ledger.jsonl"
    sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    lines = []
    if led.exists():
        for ln in led.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                lines.append(ln); continue
            if e.get("file", "").endswith("confetti_sheet.png"):
                e.update(sha256=sha, origin="palette_tinted", created=time.strftime("%Y-%m-%dT%H:%M:%S"))
                ln = json.dumps(e, ensure_ascii=False)
            lines.append(ln)
        led.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ 彩带已按 {pal.name} 重绘: 8 格 <- {[('#%02X%02X%02X' % c) for c in cols[:4]]} + 4 派生")
    print(f"  sha256={sha[:16]}…  账本已同步 {'(ledger 已更新)' if led.exists() else '(无 ledger 文件)'}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    proj = Path(sys.argv[1]).resolve()
    if not proj.exists():
        raise SystemExit(f"[FAIL] 项目目录不存在: {proj}")
    return check(proj) if "--check" in sys.argv[1:] else retint(proj)


if __name__ == "__main__":
    sys.exit(main())
