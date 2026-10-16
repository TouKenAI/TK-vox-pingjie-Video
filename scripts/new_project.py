#!/usr/bin/env python3
"""豆包适配(V8.1.5a)：新片项目脚手架 —— 一键生成 productionN 目录骨架。

为什么需要: 外部 Agent 工作流靠文档描述"建目录"; 豆包每次开工新片, 用本脚本
零歧义落盘标准骨架, 避免手建目录缺文件导致门禁误报。

生成内容(production<NN>/, 默认取工作区最大序号+1):
  chunks.json           空 chunks 数组(占位, 重构稿定稿后填)
  BRIEF.md              骨架声明模板(含四维权重/系列线/设计确认区)
  qa/                   polycheck/genre 等报告输出目录
  assets/audio/         旁白 mp3 输出目录
  assets/raw/           生图原始素材目录
  assets/source/        抠图/封面成品目录
  assets/text/          文字卡 PNG 目录
  assets/ledger.jsonl   素材账本(初始化空文件, preflight 账本门需要)
  .gitkeep              空目录占位

用法: python scripts/new_project.py [<工作区根>] [--name production18]
      <工作区根> 默认 = 脚本父目录的父目录(即技能所在工作区根)
      --name 显式指定项目名(默认自动取 production<max+1>)
退出码: 0 = 骨架已建(打印目录树) / 1 = 已存在同名项目(不覆盖, 防误伤)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

HERE = Path(__file__).resolve().parent

SKELETON_DIRS = [
    "qa", "assets/audio", "assets/raw", "assets/source", "assets/text",
]

BRIEF_TEMPLATE = """# {name} 制作 BRIEF（骨架声明）

> 由 new_project.py 生成，阶段①重构稿交审时填写以下字段。

## 定位校验（选题三问）
- 与账号定位（AI/IT/科技）关系：
- 系列线 / 话题矩阵归属：
- 疲劳度检查（与最近 3 片话题间隔）：

## 类型声明（detect_genre 结果）
- genre: （knowledge / ad / brand / story / product）
- 置信度: （≥0.6 或人工指定）

## 叙事骨架（三选一，本片声明）
- 骨架: （A 清单式 / B 层递式 / C 对比式）——连续两片不得同骨架

## 精选四维自检（BRIEF 阶段）
- 获得感（专业深度）：
- 表达力：
- 惊喜感（赛道内换角度）：
- 感染力（专业热情，非煽情）：

## 创意必交区（V8.1.7，每片必须填满三行，灵感纪律化）
- **本片惊喜点**（至少 1 个：语言/视觉/结构任选——方言、数据动效、反差开场、彩蛋等；参考前片"第一次"清单避免重复）：
- **本片真实细节**（至少 1 句：你亲历的观察/数字/场景，改为第一人称入稿；没有则向用户索取，不编造）：
- **本片"第一次"**（至少 1 个从未用过的表现手法；查 novelty_meter 特效词汇与历片指纹）：
- **视觉风格（V8.2 必填，detect_style 自动匹配后确认）**：主风格（cutout/chalk/popup）+ 客串元素（若有须注语义动机，主≥70%/客≤30%）：
- 视觉指纹（色调方向/主色-强调色/镜头语言，与邻片差异≥30% 且可被 palette_ledger 验证）：

## 视觉方向
- 隐喻概念（查 metaphor_ledger）：
- 配色方案（查 palette_ledger，与邻近片差异≥30%）：
- IP 出场（讲书人？需要用户照片）：

## 设计确认区（novelty_meter WARN 时裁决）
- 多样性预警项：
- 裁决：系列呼应接受 / 改稿
"""

CHUNKS_TEMPLATE = """[
  {"id": "chunk_01", "text": "", "emotion": "hook", "scene": "S01"}
]
"""


def next_project_name(root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    nums = []
    for d in root.iterdir():
        m = re.fullmatch(r"production(\d+)", d.name)
        if m and d.is_dir():
            nums.append(int(m.group(1)))
    return f"production{max(nums) + 1 if nums else 1}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", nargs="?", type=Path, default=None,
                    help="工作区根(含 metaphors.json/palettes.json 的目录)")
    ap.add_argument("--name", type=str, default=None, help="项目名(默认 production<max+1>)")
    a = ap.parse_args()

    root = (a.root or HERE.parent).resolve()
    if not (root / "metaphors.json").exists() and not (root / ".env").exists():
        print(f"[WARN] {root} 看起来不是工作区根(无 metaphors.json/.env)——按给定路径继续")
    name = next_project_name(root, a.name)
    if not re.fullmatch(r"production\d+", name):
        sys.exit(f"项目名必须形如 production<数字>, 收到: {name!r}")

    proj = root / name
    if proj.exists():
        sys.exit(f"FAIL: {proj} 已存在——不覆盖(防误伤已有工程), 换 --name")

    proj.mkdir(parents=True)
    for d in SKELETON_DIRS:
        (proj / d).mkdir(parents=True, exist_ok=True)
    (proj / "chunks.json").write_text(CHUNKS_TEMPLATE, encoding="utf-8")
    (proj / "BRIEF.md").write_text(BRIEF_TEMPLATE.format(name=name), encoding="utf-8")
    (proj / "assets" / "ledger.jsonl").write_text("", encoding="utf-8")
    # V3.5 预置 motes 纸屑精灵表(根治每片手拷+登记的重复坑)
    tpl = HERE / "_templates" / "confetti_sheet.png"
    if tpl.exists():
        import shutil as _sh, hashlib as _h, json as _j, time as _t
        dst = proj / "assets" / "source" / "confetti_sheet.png"
        _sh.copy(tpl, dst)
        ent = {"file": "assets/source/confetti_sheet.png",
               "sha256": _h.sha256(dst.read_bytes()).hexdigest(),
               "production": name, "origin": "template",
               "created": _t.strftime("%Y-%m-%dT%H:%M:%S")}
        with (proj / "assets" / "ledger.jsonl").open("a", encoding="utf-8") as _fh:
            _fh.write(_j.dumps(ent, ensure_ascii=False) + chr(10))

    print(f"骨架已建: {proj}")
    print("  ├─ BRIEF.md        ← 骨架声明(交审时填)")
    print("  ├─ chunks.json     ← 空占位(重构稿定稿后填, 含 emotion/speed/scene)")
    print("  ├─ qa/             ← 门禁报告输出")
    print("  ├─ assets/")
    print("  │   ├─ audio/  raw/  source/  text/")
    print("  │   └─ ledger.jsonl   ← 素材账本(空, gen_assets 开始登记)")
    print("下一步: 阶段① detect_genre → 重构稿+事实点清单 → 用户审稿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
