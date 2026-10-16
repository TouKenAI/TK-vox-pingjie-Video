#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regen_check.py <项目目录> —— 场景 JSON 重生成对账(p25 复盘机制化，V3.41 重写)。

p25 做法: 渲染期的 JSON 手修(开场空台/出画让位/补层/label)必须镜像进项目的
build_scenes.py，否则重跑生成器即回退、且没有任何门会发现。本门把"镜像是否忠实"
变成程序化断言: 逐场跑项目生成器，与盘上 scene_s*.json 的 **layers** 结构化对比
(camera/背景等 split_beats 产物不在对比范围——split_beats 只动相机段不动图层)。

⚠ V3.41 修掉本门自己的两个缺陷（都是"检查器说谎"那一族）：
① 旧版文档写"只读不写"，实际**调用 sNN() 会让生成器把盘上 JSON 重写一遍**
   （p26 的 emit() 在 sNN() 里直接 write_text）。真危险的地方在于：如果生成器已经和
   盘上漂移（正是本门要抓的事），跑一次就把盘上的手修**覆盖掉**，第二次跑必然 PASS——
   **一个会把证据抹掉的探测器**。现在把模块的 HERE 重定向到临时目录，并留逐字节还原兜底。
② 旧版假设 sNN() 返回 dict；p26 的形状是"sNN() 内部 emit 写盘、返回 None" →
   `d["layers"]` 直接 TypeError，rc=1 是**崩出来的红**不是判据红。现在两种形状都支持。

退出码 0=可复现 / 1=不可复现或无法对账（都带可读原因，不吐裸 traceback）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # NameError(漏 import sys)必须响，不能装死


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    a = ap.parse_args()
    proj = a.project.resolve()
    if not proj.is_dir():
        print(f"FAIL: 项目目录不存在: {proj}", file=sys.stderr)
        return 1
    gen = proj / "build_scenes.py"
    if not gen.exists():
        print(f"FAIL: {gen} 不存在 —— 本门对账的是『项目生成器 vs 盘上场景』", file=sys.stderr)
        return 1
    paths = {int(f.stem.replace("scene_s", "")): f for f in sorted(proj.glob("scene_s*.json"))}
    if not paths:
        print(f"FAIL: {proj} 盘上没有 scene_s*.json —— 无东西可对账不是通过", file=sys.stderr)
        return 1
    raw = {i: p.read_bytes() for i, p in paths.items()}          # 兜底还原用
    disk = {i: json.loads(b.decode("utf-8")) for i, b in raw.items()}

    spec = importlib.util.spec_from_file_location(f"_regen_{proj.name}", gen)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fns = {i: getattr(mod, f"s{i:02d}", None) for i in disk}
    missing = [i for i, fn in fns.items() if fn is None]
    if missing:
        print(f"FAIL: build_scenes.py 缺场景函数 s{min(missing):02d} 等 {len(missing)} 个", file=sys.stderr)
        return 1
    has_postfix = hasattr(mod, "_postfix")

    tmp = Path(tempfile.mkdtemp(prefix="regen_"))
    try:
        if hasattr(mod, "HERE"):
            mod.HERE = tmp            # 把"调用即写盘"的生成器引到临时目录，项目一个字节都不动
        bad = []
        for i in sorted(disk):
            try:
                d = fns[i]()
                if isinstance(d, dict):
                    if has_postfix:
                        mod._postfix(i, d)
                else:
                    # 生成器形状二：sNN() 内部 emit 写盘、返回 None → 从临时目录读回它刚产出的
                    f = tmp / f"scene_s{i:02d}.json"
                    if not f.exists():
                        bad.append(i)
                        print(f"  S{i:02d} 生成器既不返回 dict 也没写出 scene_s{i:02d}.json —— 无法对账(不是可复现)")
                        continue
                    d = json.loads(f.read_text(encoding="utf-8"))
                got, want = d.get("layers"), disk[i].get("layers")
                if got is None or want is None:
                    bad.append(i)
                    print(f"  S{i:02d} 缺 layers 字段(gen={got is not None} disk={want is not None}) —— 无法对账")
                    continue
                if json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
                    bad.append(i)
                    gids, dids = [l.get("id") for l in got], [l.get("id") for l in want]
                    hint = "" if gids == dids else f"(图层集合也不同: gen={len(gids)} disk={len(dids)})"
                    print(f"  S{i:02d} layers 与盘上不一致 {hint} —— 手修没镜像进生成器, 或盘上被改过")
            except Exception as e:
                bad.append(i)
                print(f"  S{i:02d} 重生成抛错: {type(e).__name__}: {e}")
        # 兜底：万一生成器无视 HERE 直接写项目目录 → 逐字节还原并说出来
        touched = [i for i in raw if paths[i].read_bytes() != raw[i]]
        for i in touched:
            paths[i].write_bytes(raw[i])
        if touched:
            print(f"⚠ 生成器无视 HERE 重定向，写了 {len(touched)} 个盘上 JSON —— 已逐字节还原"
                  f"（该生成器请改成用模块级 HERE 拼路径，否则本门永远在改你的项目）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if bad:
        print(f"=== FAIL === {len(bad)} 场不可复现/无法对账: {['S%02d' % i for i in bad]}", file=sys.stderr)
        return 1
    print(f"PASS: {len(disk)} 场 layers 与生成器产出逐场一致 —— 交付态可复现"
          + ("" if has_postfix else "（该项目无 _postfix，手修须直接写进 sNN()）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
