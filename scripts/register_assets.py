#!/usr/bin/env python3
"""V8.1.2 资产账本补登 —— 派生资产自动登记进 assets/ledger.jsonl(幂等)。
V8.1.2(W5): ip_*.png 自动打 role=ip_host 标签(角色级粒度,配合 ip_registry.json 跨集复用)。
用法: py -3.14 scripts/register_assets.py <项目目录>
时机: 阶段④ cutout_key + make_cards + make_cover 完成后、render_all 之前。
退出码: 0 = 已全部登记 / 1 = 无项目或无 ledger。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: register_assets.py <项目目录>")
        return 1
    proj = Path(sys.argv[1]).resolve()
    led = proj / "assets" / "ledger.jsonl"
    if not led.exists():
        print(f"FAIL: {led} 不存在——先跑 gen_assets 生成原始登记")
        return 1

    have = {}
    for line in led.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                e = json.loads(line)
                have[e["file"]] = e
            except Exception:
                pass

    derived: list[Path] = []
    src = proj / "assets" / "source"
    txt = proj / "assets" / "text"
    lin = proj / "assets" / "lines"      # V3.19: 白板标注层目录(不扫会被 preflight 判"未登记")
    if src.exists():
        # V3.26 修死条件: cutout_key 产的是 `<stem>_check.png`, 而 `endswith("_check")` 永远不成立
        # (文件名以 .png 结尾) → 棋盘调试图一直被当正式素材入账。p16 账本里实测 21 条这种条目。
        derived += [p for p in sorted(src.glob("*.png")) if not p.name.endswith("_check.png")]
    if txt.exists():
        derived += sorted(txt.rglob("*.png"))  # V8.2.2 递归覆盖 countup 序列子目录
    if lin.is_dir():
        # V3.24: 原来这行缩进在 `if txt.exists()` 里面 —— 没有文字卡的片子 lines/ 会整体漏登,
        # preflight 再把每个引用判"未登记"。三目录互相独立, 不该嵌套。
        derived += sorted(lin.glob("*.png"))

    add = 0
    NL = chr(10)
    with led.open("a", encoding="utf-8") as fh:
        for p in derived:
            f = "assets/" + p.relative_to(proj / "assets").as_posix()
            if f in have:
                continue
            entry = {"file": f, "production": proj.name,
                     "sha256": sha256(proj / f), "origin": "derived"}
            if p.name.startswith("ip_"):
                entry["role"] = "ip_host"  # V8.1.2 角色级粒度
            fh.write(json.dumps(entry, ensure_ascii=False) + NL)
            add += 1
    print(f"账本补登 {add} 条(扫描 {len(derived)} 个派生资产, 已有 {len(have)} 条)")
    print("PASS: 账本完备, preflight 账本门可过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
