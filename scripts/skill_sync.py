#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_sync.py —— 仓库 `scripts/`+`references/` 与**项目级技能包镜像**的同源对账（V3.42）。

**为什么要这道门**：同一套工具有两份拷贝就必须有机制对账，否则"修好的门下一部片没生效，
而全流程一片绿"（V3.34 首次实测 5 个脚本 + playbook 漂移）。

**V3.42 改口径（项目级隔离，2026-10-09）**：对账目标从**机器级共享包**
`~/.agents/skills/produce-collage-video` 改为**本项目自带镜像** `<repo>/.skill/`。
原因（实测）：机器级共享包会被**其它版本线**整体覆盖——本仓查到的那份是 V21.2，
带 `plan_check.py`/`text_legibility_check.py`/`make_subtitles.py` 等本仓没有的脚本，
还留着 `*.v21x-not-mine-*.bak`。于是 `check` 常年红 46 处，`pipeline ready` 不盖章、
`render_all` 直接拒渲——**全链被别人的包卡死**；而按旧文档 `push` 又会砸掉对方的包。
本项目自包含（渲染器/契约/工具全在仓内，produce/render_all 跑的都是 `HERE/` 那份），
所以对账只对**本项目自己的镜像**，不再读、不再写任何机器级共享目录。
确要动机器级包时显式加 `--global`（极少用，且自担跨线污染风险）。

用法：
  py -3.14 scripts/skill_sync.py check          # 只报漂移，有漂移 rc=1
  py -3.14 scripts/skill_sync.py push           # 仓库 → .skill/（仓库是权威；镜像不存在则创建）
  py -3.14 scripts/skill_sync.py pull           # .skill/ → 仓库（只在改过镜像时用）
  py -3.14 scripts/skill_sync.py check --skill <路径>     # 显式指定对账目标
  py -3.14 scripts/skill_sync.py check --global           # 显式对账机器级共享包（慎用）
  py -3.14 scripts/skill_sync.py check --json-out qa/skill-sync.json

退出码：0=一致 / 1=有漂移 / 2=无镜像可比（本项目自包含、且还没建 .skill/ →
        调用方按"无可比对"放行，**不是通过**；要建立对账就跑一次 `push`）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass

HERE = Path(__file__).resolve().parent          # <repo>/scripts
REPO = HERE.parent
SKILL_NAME = "produce-collage-video"
SUBDIRS = ("scripts", "references")
SUFFIXES = {".py", ".md", ".json"}
SKIP_DIRS = {"__pycache__", ".git", "qa", ".skill"}


def skill_root(explicit: Path | None = None, allow_global: bool = False) -> Path | None:
    """对账目标解析。V3.42：默认只认**项目级镜像** `<repo>/.skill/`。

    机器级共享目录（~/.agents、~/.qoder-cn）只在 `--global` 时才探测——它们会被其它
    版本线整体覆盖，当默认目标会让本仓被别人的包卡死（实测红 46 处、全链断）。
    """
    if explicit is not None:
        return explicit
    mirror = REPO / ".skill"
    if (mirror / "SKILL.md").exists():
        return mirror
    if allow_global:
        for c in (Path.home() / ".agents" / "skills" / SKILL_NAME,
                  Path.home() / ".qoder-cn" / "skills" / SKILL_NAME):
            if (c / "SKILL.md").exists():
                return c
    return None


def walk(root: Path) -> dict[str, str]:
    """相对路径 → md5。只比工具与文档，不比项目产物。"""
    out: dict[str, str] = {}
    for sub in SUBDIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in SUFFIXES:
                continue
            # 只按**相对路径**判 SKIP_DIRS：拿绝对路径 parts 判会把 `.skill/` 镜像自身的
            # 全部内容过滤掉（`.skill` 在 <repo>/.skill/... 的 parts 里），
            # 于是 push 报"同步 83 个文件"而镜像里只有 SKILL.md 一个（2026-10-09 实测）。
            if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            out[p.relative_to(root).as_posix()] = hashlib.md5(p.read_bytes()).hexdigest()
    sk = root / "SKILL.md"
    if sk.exists():
        out["SKILL.md"] = hashlib.md5(sk.read_bytes()).hexdigest()
    return out


def compare(repo: Path, skill: Path) -> dict:
    a, b = walk(repo), walk(skill)
    return {
        "only_repo": sorted(set(a) - set(b)),
        "only_skill": sorted(set(b) - set(a)),
        "diff": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
        "same": len([k for k in set(a) & set(b) if a[k] == b[k]]),
        "repo_total": len(a), "skill_total": len(b),
    }


def sync(repo: Path, skill: Path, rep: dict, direction: str) -> int:
    src, dst = (repo, skill) if direction == "push" else (skill, repo)
    n = 0
    for rel in rep["diff"] + rep["only_repo" if direction == "push" else "only_skill"]:
        s, d = src / rel, dst / rel
        if not s.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        print(f"  {'→' if direction == 'push' else '←'} {rel}")
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("check", "push", "pull"))
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--skill", type=Path, default=None,
                    help="显式指定对账目标；默认 <repo>/.skill（项目级镜像）")
    ap.add_argument("--global", dest="allow_global", action="store_true",
                    help="允许探测机器级共享包 ~/.agents|~/.qoder-cn（慎用：会被其它版本线覆盖）")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    skill = skill_root(a.skill, a.allow_global)
    if skill is None or not skill.exists():
        if a.mode == "push":
            # 项目级镜像不存在 = 第一次建立。push 的语义就是"仓库是权威，把它落地成镜像"。
            skill = (a.skill or (a.repo / ".skill")).resolve()
            print(f"[建镜像] {skill} 不存在 —— 按仓库内容创建项目级镜像")
        else:
            print(f"[N/A] 无项目级镜像 {a.repo / '.skill'}（本项目自包含，未建镜像 = 无可比对，"
                  f"**不等于一致**）。要建立对账跑 `py -3.14 scripts/skill_sync.py push`；"
                  f"确要对账机器级共享包加 --global")
            return 2
    rep = compare(a.repo, skill)

    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps({"repo": str(a.repo), "skill": str(skill), **rep},
                                         ensure_ascii=False, indent=1), encoding="utf-8")

    drift = rep["only_repo"] + rep["only_skill"] + rep["diff"]
    if a.mode == "check":
        if not drift:
            if not a.quiet:
                print(f"✓ 仓库与技能包同源（{rep['same']} 个文件一致）")
            return 0
        print(f"❌ 仓库与技能包漂移 {len(drift)} 处（仓库 {rep['repo_total']} / 技能包 {rep['skill_total']} 文件）")
        for rel in rep["diff"]:
            print(f"   内容不同  {rel}")
        for rel in rep["only_repo"]:
            print(f"   仅仓库有  {rel}")
        for rel in rep["only_skill"]:
            print(f"   仅技能包有 {rel}")
        print("   → 仓库是权威：`py -3.14 scripts/skill_sync.py push`；"
              "改过工具却不 push，下一部片跑的是旧门（p23 实录 5 处）。")
        return 1

    n = sync(a.repo, skill, rep, a.mode)
    left = compare(a.repo, skill)
    still = left["only_repo"] + left["only_skill"] + left["diff"]
    print(f"{'push 仓库→技能包' if a.mode == 'push' else 'pull 技能包→仓库'}: 同步 {n} 个文件，"
          f"复检剩余漂移 {len(still)} 处" + (f" → {still}" if still else ""))
    return 0 if not still else 1


if __name__ == "__main__":
    raise SystemExit(main())
