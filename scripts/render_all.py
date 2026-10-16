#!/usr/bin/env python3
"""V8.1 并行渲染调度器 —— 全场景并行(SKILL 写了并行标准,P8-P10 实际都在串行,本工具终结之)。

渲染器是确定性的,各场景独立输出目录无共享状态,可安全并行。
用法: python render_all.py <项目目录> [--jobs 3] [--overwrite] [--skip-preflight] [--skip-layout]
  --jobs 并行数(默认 3;CPU 核多可 4-5,磁盘慢会互相拖)
  --skip-preflight 跳过门禁(默认先跑五门禁+ratio,失败不渲染,V7.1.1 修"门禁过但没渲染")
  --skip-layout 跳过 layout_check(V8.1 新增;layout_check 跑全场景耗 ~30s,debug 时可跳过)
输出: 每场景完成行 + 总耗时;任一场景失败退出码 1。

V8.1 升级:preflight 钩子补 layout_check.py(V6.8 第 4 道 HARD 门),
  防止"门禁过但字出画"事故——layout_check 是文字卡出画的唯一拦截器。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 子进程强制 UTF-8：默认 GBK 下门一 print ✓ 就崩 → 被读成假红/零帧(见 env_paths 顶部说明)
from env_paths import CHILD_ENV

HERE = Path(__file__).resolve().parent
# 便捷包已自带渲染器(scripts/render_sequence.py);优先本地,再退回旧的同级技能布局
RENDER = HERE / "render_sequence.py"
if not RENDER.exists():
    RENDER = HERE.parent.parent / "create-collage-animation" / "scripts" / "render_sequence.py"
if not RENDER.exists():
    RENDER = Path("create-collage-animation/scripts/render_sequence.py")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="跳过 preflight(默认必跑;P14 教训:门禁过但没渲染, 失败不渲染)")
    ap.add_argument("--skip-layout", action="store_true",
                    help="V8.1 新增:跳过 layout_check(debug 时用;默认开,字出画 HARD block)")
    ap.add_argument("--renderer", type=Path, default=RENDER)
    ap.add_argument("--force-all", action="store_true",
                    help="V3.34: 无视帧戳，全部重渲。默认是增量的——场景 JSON、被引用的资产、"
                         "渲染器三者都没变的场直接复用旧帧(p23 改一轮坐标全量重渲 863s，实际只需渲 1 场)")
    a = ap.parse_args()

    root = a.project.resolve()
    scenes = sorted(root.glob("scene_s*.json"))
    if not scenes:
        sys.exit("FAIL: 无 scene_s*.json")
    py = sys.executable

    # V8.1: 渲染前自动跑门禁, 失败直接退出 1(修 P14"门禁过但没渲染"事故 + 字出画事故)
    # first_frame_check.py(V3.20): 每场第 0 帧须有不透明图层, 否则渲完+编码完才被 qa_deliver 判空白帧(p14 白渲 669s)
    # bg_luma_check.py(V3.18): 背景 PNG 灰度均值>235 自动降亮0.85并复检(production10 爆闪事故前移)
    # preflight_v6.py: 账本/节奏密度/长场景换式
    # check_timeline_ratio.py: 逐段帧时长 ≥ 旁白×1.02(防配音重叠)
    # layout_check.py(V6.8): 文字卡成品坐标整屏可见 HARD block(防字出画)
    if not a.skip_preflight:
        # V3.34 工具同源门（放在最前，0.3s）：仓库与技能包漂移时，改过的门可能根本没在这条路径上跑。
        # rc=2 = 找不到已安装技能包（便携包），只响不拦；rc=1 = 确有漂移，拒绝渲染并给出一行修法。
        ss = HERE / "skill_sync.py"
        if ss.exists():
            r = subprocess.run([py, str(ss), "check", "--quiet"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=CHILD_ENV)
            if r.returncode == 1:
                print("❌ 仓库 scripts/references 与已安装技能包漂移，拒绝渲染")
                print((r.stdout or "").strip()[-800:])
                sys.exit(1)
            elif r.returncode == 2:
                print("⚠ skill_sync: 找不到已安装技能包，无镜像可对账（便携包场景），继续")
        preflight_tools = ["first_frame_check.py", "card_text_check.py", "bg_luma_check.py",
                           "preflight_v6.py", "check_timeline_ratio.py",
                           "motion_similarity_check.py", "bg_plan_check.py",
                           # V3.42: 成品字高门。此前数图层/量出画/量拥挤/打分，**没有一道量字号**，
                           # 而渲染器会把文字卡 PNG 重采样到 base_width×scale——盘上字大≠屏上字大。
                           "text_legibility_check.py"]
        if not a.skip_layout:
            preflight_tools.append("layout_check.py")
        # 门数以本行为准（自报），文档里不要再写死道数——写死过 5、8、13、15，每次都过期。
        print(f"渲前门 {len(preflight_tools)} 道: " + " → ".join(
            t.replace(".py", "") for t in preflight_tools))
        here = Path(__file__).resolve().parent
        for tool in preflight_tools:
            # 旧版在 ("scripts","..","../scripts") 三处试, 全都不存在就静默跳过一道门(且仓库根的陈旧
            # 副本会遮蔽 scripts/ 新版)。渲染前门禁必须只有唯一路径, 缺门文件=拒绝渲染。
            cand = here / tool
            if not cand.exists():
                print(f"❌ 渲染前门禁 {tool} 不存在于 {cand} —— 缺门比不过门更危险, 拒绝渲染")
                sys.exit(1)
            r = subprocess.run([py, str(cand), str(root)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=CHILD_ENV)
            if r.returncode != 0:
                print(f"❌ {tool} 失败, 拒绝渲染")
                print(r.stdout[-500:]); print(r.stderr[-200:])
                sys.exit(1)
            print(f"✓ {tool} 通过")
            # V3.35: 门禁通过时也要把它自己汇总的那一行抬上来。旧版成功就只打"✓ 通过"，
            # 于是 layout_check 每片 187~312 条 WARN(平台按钮区压卡、读数压道具…)一条都没进过人眼。
            for _ln in (r.stdout or "").splitlines():
                if _ln.startswith("SUMMARY "):
                    print("   " + _ln)

    def run_one(scene: Path):
        idx = scene.stem.replace("scene_s", "s")      # scene_s01 -> s01
        out = root / f"frames_{scene.stem.split('_')[-1]}"  # scene_s01 -> frames_s01
        cmd = [py, str(a.renderer), str(scene), "--output", str(out)]
        # V3.34: 到这里的一定是"需要重渲"的场，旧帧必须清掉（渲染器见非空目录不带 --overwrite 会抛
        # FileExistsError）。所以覆盖与否由帧目录决定，不再由命令行旗标决定。
        if a.overwrite or out.exists():
            cmd.append("--overwrite")
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=CHILD_ENV)
        if r.returncode == 0:
            # V3.16 帧↔JSON 一致性戳(playbook §51⑤) + V3.34 资产级指纹：
            # 存 qa/frame_stamps/ 而非帧目录, 避免杂散文件被任何 *.png 扫描误计。
            # 实现只在 scene_fingerprint 里一份，render_sequence 单场重渲走同一个函数。
            try:
                from scene_fingerprint import write_stamps
                write_stamps(scene, out, root)
            except OSError:
                pass
        return idx, r.returncode, time.time() - t0, (r.stdout or r.stderr).strip().splitlines()[-1:]

    # V3.34 增量渲染：指纹（场景 JSON + 引用资产 + 渲染器）命中且帧数齐 → 复用旧帧。
    # 判据只认盘上事实；"没有戳"一律当不可复用（旧项目第一轮会全渲一次，之后才吃到加速）。
    from scene_fingerprint import reusable
    todo, skipped = [], []
    for s in scenes:
        out = root / f"frames_{s.stem.split('_')[-1]}"
        ok, why = (False, "--force-all") if a.force_all else reusable(s, out, root)
        (todo if not ok else skipped).append((s, why))
    for s, why in skipped:
        print(f"↷ {s.stem.replace('scene_', '')} 复用旧帧（{why}）")
    for s, why in todo:                              # 为什么重渲也要能读出来，别只报"要渲"
        out = root / f"frames_{s.stem.split('_')[-1]}"
        if not a.force_all and out.exists():         # 首渲（无帧目录）不刷噪音
            print(f"↻ {s.stem.replace('scene_', '')} 需重渲（{why}）")
    if not todo:
        print(f"\n{len(scenes)} 场全部命中帧戳，无需渲染（要强制重渲: --force-all）")
        print("ALL RENDERED ✓")
        return 0

    t0 = time.time()
    fails = []
    (root / 'frames').mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_one, s): s for s, _ in todo}
        done = 0
        for fut in as_completed(futs):
            idx, code, secs, line = fut.result()
            done += 1
            mark = "✓" if code == 0 else "✗"
            print(f"[{done}/{len(todo)}] {mark} S{idx} {secs:.1f}s  {line[0] if line else ''}")
            if code != 0:
                fails.append(idx)
    total = time.time() - t0
    print(f"\n渲染 {len(todo)}/{len(scenes)} 场（复用 {len(skipped)} 场）并行(jobs={a.jobs}) 总耗时 {total:.1f}s")
    if fails:
        print("FAIL:", ",".join(fails))
        return 1
    print("ALL RENDERED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
