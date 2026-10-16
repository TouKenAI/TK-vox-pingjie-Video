#!/usr/bin/env python3
"""V5 批量生图运行器 —— 读 jobs.json,逐张调 StepFun 生图,断点续跑。

jobs.json 格式(放项目根):
[
  {"name": "bg_tunnel.png", "prompt": "paper cutout collage style, ..."},
  {"name": "hero.png",      "prompt": "...", "ref": "assets/raw/hero_base.png"}   # 可选:参考图保角色一致
]
用法:
  py -3.14 scripts/gen_assets.py jobs.json --raw-dir assets/raw
已存在的同名文件自动跳过(断点续跑);失败即停,修好 prompt 重跑即可。

V8.1.8 素材 prompt 契约(光照统一):
- 所有场景/道具 prompt 统一声明光源方向: "主光源从画面左上 45° 打光, 阴影落向右下"
- 同一部片内全部素材(背景/道具/IP)光源方向一致, 消"拼凑感"; 视觉指纹字段记录光源方向
- 前景道具可加 "轻微地面接触阴影" 增强落地感(渲染器 shadow 已默认开启)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

HERE = Path(__file__).resolve().parent
MAG = "centered on pure solid magenta background color FF00FF filling entire frame, no text, no shadow"

# V3.16 素材 prompt 契约(playbook §51②): 剪纸道具缺任一条都会造成"灰投影残留/渐变底抠不净/半透明"。
# 漏写不再靠人记忆——prop_* 任务自动补全并打印提示。
PROP_CONTRACT_CHECKS = (
    # ⚠ 判据必须是**整条键色底条款**，不能只查子串 "magenta"。
    #   p21 实录：三张样张的 prompt 写了 "absolutely no pink or magenta cast"，
    #   旧判据看见 "magenta" 就以为键色底已声明、**没有补全**，于是模型把道具放在
    #   摄影灰底上；样张白边与灰底亮度差只有 31(<t0=45)，抠图会把白边直接抠穿。
    ("solid magenta #ff00ff background", "isolated on pure solid magenta #FF00FF background filling entire frame"),
    ("no ground shadow", "no ground shadow"),
    ("single ", "single object"),  # 兼容 'single object' / 'single group'
    ("upper-left", "main light upper-left 45deg"),
)


def enforce_prop_contract(name: str, prompt: str) -> tuple[str, list[str]]:
    """返回 (补全后的 prompt, 被补上的条款)。仅对 prop_* 生效;背景/人物/IP 不加洋红契约。"""
    if not name.startswith("prop_"):
        return prompt, []
    low = prompt.lower()
    added = [clause for key, clause in PROP_CONTRACT_CHECKS if key not in low]
    if not added:
        return prompt, []
    return prompt + ", " + ", ".join(added), added


# V3.25 背景契约注入(与 prop 对称)。**背景原来完全没有注入机制**——尾巴是我每张手抄的,
# 于是 p12 十二张十二种尾巴、p13 十五张十四种。但真正的病灶不是漂移, 是**内容自相矛盾**:
# 旧尾巴写 `absolutely no objects`, 正文却要求"画一个剖面图/摊开的册页/夹板清单"。
# p16 有 4/19 张踩中, 而那 4 张正是 clutter 当场点名的 s03/s04/s10/s17 —— 一一对应, 无一例外。
# 模型只能自己猜哪条优先, 猜法每张不同 → 同一片背景密度离散 5.0×(五部片里最散)。
#
# ── 硬规矩：契约只准带"骨架", 皮肤归 `--style` + `palette.json` ──
# 两条契约按"这张图自己是不是主体"分: stage(默认)=它只是台面, 中心留给前景剪贴件;
# sheet=它本身就是那张图纸, 中心可以有线稿, 但密度要有数值预算。
# 允许进契约的只有三样, 且都与画风无关: ①构图职责 ②数值密度预算 ③"边框须来自本片地色"。
# 反面教训(我第一版就栽了): 把 `vintage engineering service-manual` + `warm paper` +
# `no dark background` 写了进去——那是 p16 的画风和浅色纸底, 套到 p12(浮世绘工笔·深酒红底)
# 上会直接毁掉它的底子。**任何颜色词、任何流派名词都不许出现在契约里。**
BG_SHEET_ROLE = "sheet"
BG_ROOM_ROLE = "room"
_CONTRADICTORY_CLAUSE = "absolutely no objects"
# "这张图本身就是主体"的措辞族。命中却没声明 bg_role=sheet → 与 stage 契约打架, 拒生图。
# ⚠ 触发词要**窄**: 我第一版放了 "clipboard"/"checklist", 于是把 bg17(夹板从左下角探进来三个空
# 方框)也判成矛盾。但夹板待在边缘完全合法 —— 它的问题是**画过头**, 不是自相矛盾。
# 判据混了两种失效, 门就会给出错误的修复建议。
_SHEET_HINTS = ("cross-section", "exploded assembly", "open book", "page edges",
                "schematic", "diagram", "ledger spread", "layer slice")
# 程度副词是密度失控的入口(`hatched densely` 那个 densely 就是我自己写的)。只 WARN 不 FAIL:
# 它有时是合法修辞, 判死会假阳性——而假阳性比漏报更致命(§57)。
_DENSITY_ADVERBS = ("densely", "dense ", "heavily hatch", "intricate", "highly detailed", "busy")
# 构图职责与画风无关所以能写死; 颜色走 {ground_clause} 占位, 由本片 palette 决定或整条省略。
# 两条尾巴**都带数值密度预算**: bg17 证明"标记只放边缘"管不住边缘本身能画多密。
# ⚠ 措辞必须是**小写散文**, 不能出现两个词以上的全大写片段。实测: 我写 `CRITICAL COMPOSITION:`
# 和 `SPARSITY BUDGET (hard):`, 模型就把 "CRITICAL COMPOSITION" 当成红色钢印文字**画进了画面右上角**
# (p16 bg17 第二次抽图, 那张图直接废)。"no text" 挡不住它 —— 它把指令本身当成了标签。
# test_bg_contract.py 里有对应断言, 防止以后又有人往契约里加大写标题。
_STAGE_TAIL = ("composition rule: the entire middle 65 percent of the frame stays completely bare "
               "and empty, reserved for foreground cutouts, with every mark sitting only at the outer "
               "edges like marginalia. keep those edge marks very light, so that together they cover "
               "less than one tenth of the frame, drawn as thin linework. no standalone rendered "
               "objects, no people, no lettering or labels of any kind, no watermark, no frame border."
               "{ground_clause}")
# V3.27 第三种背景角色：`room`。前两种都判不了"场面"——stage 要求中心 65% 全空且"no standalone
# rendered objects"，sheet 要求"thin linework only, no filled shapes"。而 §61 开工模板把世界定死成
# "有光、有空间、有前后层的场面"，等距 2.5D 的背景**就是一间房**：有台面、有灯、有台后堆叠。
# 两条契约与创作标准直接对撞，缺这一格，"先填 KICKOFF 再生图"的流程走不到生图。
# 与另两种一样：只带构图职责 + 数值密度预算 + 地色，不带任何颜色词与流派名词。
# ⚠ 必须**显式声明** bg_role=room，不设为默认——默认仍是 stage，历史项目行为不变。
_ROOM_TAIL = ("composition rule: this frame is one continuous room or stage rather than a sheet of "
              "paper. keep the lower middle third of the floor or counter surface completely clear of "
              "any object edge, so that cut-out pieces can be placed there later, and let everything "
              "described stand behind that clear band. keep those standing forms together covering less "
              "than one third of the frame. read the space in three depth layers: a far side along the "
              "top, the lit surface across the middle, an empty near edge along the bottom. one visible "
              "light source pools onto the lit surface, and every shadow falls the same way, toward the "
              "lower right. no people, no lettering or labels of any kind, no watermark, no frame border."
              "{ground_clause}")
# ⚠ 这句原来写的是 `hard edged shadows falling to the lower right`——"hard edged" 是我给等距 2.5D
# 写 room 角色时混进去的**风格词**, 而契约的规矩是"只带骨架, 皮肤归 --style + palette"。
# 它和国潮水墨的 soft bleeding edges 直接对撞(p18 实录), 模型只能自己猜哪条优先——正是 V3.25
# 立这条规矩时要防的那个病。契约只管**光往哪来**, 软硬交给风格锚点。
_SHEET_TAIL = ("this sheet is itself the drawing, rendered as thin linework only. keep the ink very "
               "sparse, so that the drawn strokes together cover less than one tenth of the image, "
               "with at least four times as much empty field showing between strokes as ink. "
               "no filled shapes, no solid dark blocks, no people, no lettering or labels of any kind, "
               "no watermark, no frame border.{ground_clause}")
_GROUND_CLAUSE = (" the background field colour of this image is {hex}, and it must reach all four "
                  "edges of the frame; do not add any cover, mat, desk, border or vignette that is not "
                  "already part of the described subject.")


def film_ground_clause(proj_dir: Path) -> str:
    """从本片 palette.json 取地色 → 生成"铺到四边"条款。读不到就返回空串, **绝不退回写死的默认色**。"""
    pf = Path(proj_dir) / "palette.json"
    if not pf.exists():
        return ""
    try:
        r, g, b = (int(x) for x in str(json.loads(pf.read_text(encoding="utf-8-sig"))["bg"]).split(","))
    except Exception:
        return ""
    return _GROUND_CLAUSE.format(hex="#%02X%02X%02X" % (r, g, b))


def bg_contract(name: str, prompt: str, role: str | None,
                ground_clause: str = "") -> tuple[str, list[str], list[str], list[str]]:
    """返回 (补全后的 prompt, 注入的条款, 致命冲突, 措辞提醒)。
    只对 bg* 生效; 道具/人物/IP 不走这条。

    ⚠ FAIL 只判**一件事**: 正文要求画可数实体、却没声明 bg_role=sheet。
    旧条款 `absolutely no objects` 在 p16 十九张的手抄尾巴里**全都有**, 光凭它判矛盾会把整批
    拦死(测试第一版就这么红给我看: 期望 4 张、实得 19 张)。它是"该被契约接管"的信号, 不是错误。
    """
    if not (name.startswith("bg") and (name[2:3] == "_" or name[2:3].isdigit())):
        return prompt, [], [], []
    low = prompt.lower()
    warns = []
    if _CONTRADICTORY_CLAUSE in low:
        warns.append(f"手抄尾巴里还留着旧条款 {_CONTRADICTORY_CLAUSE!r}; 契约已接管构图, 建议从正文删掉")
    if role == BG_SHEET_ROLE:
        tail, has = _SHEET_TAIL, "this sheet is itself the drawing" in low
    elif role == BG_ROOM_ROLE:
        # room 的作者正文本来就该写"这是一间房/台面"，它不与 center-clear 冲突：冲突的是
        # stage 尾巴里的 `no standalone rendered objects`。所以这里注入的是 room 尾巴，不判 hint。
        tail, has = _ROOM_TAIL, ("one continuous room or stage" in low or "three depth layers" in low)
    elif role:
        return prompt, [], [f"bg_role={role!r} 不认识, 只支持 {BG_SHEET_ROLE!r} / {BG_ROOM_ROLE!r} "
                            f"或留空(stage)"], warns
    else:
        hit = [h for h in _SHEET_HINTS if h in low]
        if hit:
            return prompt, [], [f"正文要求画出实体 {hit}, 但 stage 契约要求\"中心留给前景、不许有物件\" "
                                f"—— 两条直接矛盾, 模型只能自己猜哪条优先(p16 的 bg03/04/10 就是这么"
                                f"抽出 5.0× 密度离散度的)。这张图自己就是主体的话, 在 job 里加 "
                                f"\"bg_role\": \"{BG_SHEET_ROLE}\"; 不是主体的话, 把实体挪到画面边缘。"], warns
        tail, has = _STAGE_TAIL, "middle 65 percent" in low or "empty center" in low
    tail = tail.format(ground_clause=ground_clause)
    warns += [f"用了程度副词 {w!r} —— 模型会自由发挥到任意密度, 建议换成数值预算"
              f"(如 ink under one tenth / at most 4 lines)" for w in _DENSITY_ADVERBS if w in low]
    return (prompt if has else prompt + ", " + tail), ([] if has else [tail]), [], warns


# V3.24 键色带冲突门。`cutout_key --hsv` 把 PIL H∈195-248(≈275°-350°) 的高饱和像素判成**背景**
# (洋红/粉紫底族)。道具 prompt 里写死这个色带内的十六进制色, 等于让模型把"要被抠掉的色"画进主体,
# 抠图必把那块抠穿——不报错, 只是道具上凭空多个洞。钢印/红笔/勾这类几何标记应走 PIL 直绘进 assets/lines/。
KEY_BAND_H = (195, 248)
_HEX_RE = re.compile(r"#([0-9a-fA-F]{6})\b")


def key_band_conflicts(prompt: str, allow: tuple[str, ...] = ("ff00ff",)) -> list[str]:
    """道具 prompt 里"会被抠穿"的带内色。

    ⚠ 第二版假阳性(p20 实录): 道具契约**要求**作者写清纯洋红底, 于是 `#FF00FF`
    出现在自己写的 prompt 里, 被这道门当场拦死。键色底不是画在主体上的颜色,
    它本来就该被抠掉 —— 所以只放行 DEFAULT_KEY 本身, 其余带内色(如 p16 的
    accent2 品红 #E4377B 画在道具上)照旧 FAIL。
    """
    import numpy as np
    from PIL import Image
    bad = []
    for m in _HEX_RE.finditer(prompt):
        h = m.group(1)
        if h.lower() in allow:
            continue
        rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        ph, ps, _pv = (int(v) for v in np.asarray(
            Image.fromarray(np.uint8([[rgb]])).convert("HSV"))[0, 0])
        if KEY_BAND_H[0] <= ph <= KEY_BAND_H[1] and ps > 64:
            bad.append(f"#{h}(PIL_H={ph}, 落在键色带 {KEY_BAND_H[0]}-{KEY_BAND_H[1]})")
    return bad


def load_env_key() -> str:
    import os
    for directory in [HERE, HERE.parent, HERE.parent.parent, *Path.cwd().resolve().parents[:3]]:
        dotenv = directory / ".env"
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("STEPFUN_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("STEPFUN_API_KEY", "")


def _style_base(name: str) -> str:
    """「剪纸拼贴·背屏玻璃」/「复古报纸（只借…）」→ 取库里的风格主名。
    归一只有 style_presets.base() 这一份实现——两处各写一遍截法, 迟早一处截出
    「剪纸拼贴」另一处截出「剪纸拼贴·背屏玻璃」, 于是"连用两部同风格"谁也发现不了。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from style_presets import base as _b
    return _b(name)


def _assert_style_declared(args, jobs, style_suffix: str) -> None:
    """palette.json 声明了主风格却没 `--style` → 拒生图。

    p20 实录: 四张背景 prompt 自写成"产品摄影"口径, 又没带风格锚点, 模型就画回
    写实的 iPhone(刘海/灵动岛/三角三摄)。契约里"皮肤归 --style"这一条**从来没被
    任何一处代码执行过**, 所以整批素材跑偏到渲染阶段才肉眼发现——白花的钱和返工。
    """
    proj = Path(args.jobs).resolve().parent
    palette = next((p for p in [proj, *proj.parents] if (p / "palette.json").exists()), None)
    if palette is None:
        print("[风格门] 找不到 palette.json, 跳过(未声明风格)")
        return
    declared = _style_base(json.loads((palette / "palette.json").read_text(encoding="utf-8"))
                           .get("style_primary", ""))
    if not declared:
        return
    if style_suffix:
        return
    if all(job.get("style") for job in jobs):
        return
    sys.exit(
        f"[FAIL 风格门] palette.json 声明主风格「{declared}」, 但本次生图既没传 --style,"
        f" jobs 里也没有逐条 style 字段。\n"
        f"  锚点词块(paper craft / 撕边 / 层间投影 …)不会进 prompt, 模型会按 prompt 字面意思出图。\n"
        f"  正确写法: py -3.14 gen_assets.py {args.jobs} --style {declared}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", type=Path)
    parser.add_argument("--raw-dir", type=Path, default=Path("assets/raw"))
    parser.add_argument("--base-url", default="https://api.stepfun.com/step_plan/v1")
    parser.add_argument("--style", default="", help="V3.7 风格库名(如 剪纸拼贴/国潮水墨/复古报纸/白板手绘), 自动追加 proven 锚点词块")
    parser.add_argument("--overwrite", action="store_true",
                        help="V3.24: 重生同名素材(改 prompt 后重出图)。默认**跳过已存在文件**是断点续跑的正确行为, "
                             "但那样改完 prompt 重跑会静默拿到旧图——旧版只能靠手删文件(不可逆)。")
    parser.add_argument("--only", default="",
                        help="V3.33: 只跑逗号分隔的这几个 name(与 --overwrite 配合=单张重生)。"
                             "p23 实录: 只想改 1 张背景, --overwrite 把整批 6 张全重生, 多烧 5 次额度。")
    args = parser.parse_args()
    _style_suffix = ""
    if args.style:
        import importlib.util as _iu
        _sp = HERE / "style_presets.py"
        _spec = _iu.spec_from_file_location("style_presets", _sp)
        _m = _iu.module_from_spec(_spec); _spec.loader.exec_module(_m)
        _style_suffix = _m.suffix(args.style)

    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        have = [j["name"] for j in jobs]
        miss = sorted(want - set(have))
        if miss:
            raise SystemExit(f"[FAIL] --only 里 {miss} 不在 {args.jobs} 的 jobs 里(可用: {have})")
        jobs = [j for j in jobs if j["name"] in want]
        print(f"[--only] 只跑 {len(jobs)}/{len(have)} 项: {[j['name'] for j in jobs]}")
    _assert_style_declared(args, jobs, _style_suffix)
    import os
    _proj = args.jobs.parent.resolve()
    # V3.27 编排钩子: 生图是第二次花钱。阶段③④的门(语义动效/配色/隐喻/多样性)此前只以 print 提示
    # 存在, 从没被任何编排器调用过。现在统一由 `pipeline ready --stage assets` 跑完并盖章,
    # 这里只认章 —— 没章、或盖章后输入又改了, 一律拒绝生图。
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pipeline import require_ready as _require_ready
    _root = next((p for p in [_proj] + list(_proj.parents) if (p / "KICKOFF.md").exists()), _proj)
    _require_ready(_root, "assets")
    _typed = args.raw_dir if args.raw_dir.is_absolute() else (Path.cwd() / args.raw_dir).resolve()
    os.chdir(args.jobs.parent)  # 豆包适配: 以 jobs.json 所在目录为项目根, 消除 cwd 假设
    # chdir 后相对 --raw-dir 变成"相对项目根"。从仓库根敲 `production13/assets/raw` 会被再拼
    # 一层成 production13/production13/assets/raw 且日志全程报成功(p12/p13 两次实录)。
    # 判据: 按 shell CWD 解析得到的路径本就在项目根内, 而朴素拼接指向别处 → 采用前者。
    if not args.raw_dir.is_absolute():
        _naive = _proj / args.raw_dir
        if _typed.is_relative_to(_proj) and _typed != _naive.resolve():
            print(f"[路径归一] --raw-dir 按命令行 CWD 指向 {_typed},朴素拼接会得到 {_naive}"
                  f"(嵌套目录) → 采用前者")
            args.raw_dir = _typed
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    key = load_env_key()
    if not key:
        sys.exit("缺少 STEPFUN_API_KEY(.env 或环境变量)")

    # V8.0 模型通用性:生图模型名配置化(.env STEPFUN_IMAGE_MODEL,任何兼容端点可换)
    import os
    image_model = os.environ.get("STEPFUN_IMAGE_MODEL", "")
    if not image_model:
        for directory in [HERE, HERE.parent, HERE.parent.parent, *Path.cwd().resolve().parents[:3]]:
            dotenv = directory / ".env"
            if dotenv.exists():
                for line in dotenv.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("STEPFUN_IMAGE_MODEL="):
                        image_model = line.split("=", 1)[1].strip()
                        break
            if image_model:
                break
    image_model = image_model or "step-image-edit-2"

    import urllib.request
    import urllib.error

    def post(payload: dict) -> dict:
        request = urllib.request.Request(
            f"{args.base_url}/images/generations",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            sys.exit(f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:400]}")

    import hashlib
    import time
    project = Path.cwd().resolve().name
    ledger = Path.cwd().resolve() / "assets" / "ledger.jsonl"

    def register(p: Path, prompt: str, origin: str = "gen") -> None:
        cwd = Path.cwd().resolve()
        rel = p if not p.is_absolute() else (p.relative_to(cwd) if p.is_relative_to(cwd) else p)
        entry = {"file": rel.as_posix(),
                 "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                 "production": project,
                 "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
                 "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "origin": origin}
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # 地色来自本片 palette.json(chdir 后 cwd 就是项目根)。读不到就整条省略, 不写死默认色。
    _ground_clause = film_ground_clause(Path.cwd().resolve())

    for job in jobs:
        name, prompt = job["name"], job["prompt"]
        _st = job.get("style", args.style)
        if _st and _st != "none":
            import importlib.util as _iu2
            if not _style_suffix or _st != args.style:
                _sp2 = HERE / "style_presets.py"; _sc = _iu2.spec_from_file_location("sp2", _sp2); _mm = _iu2.module_from_spec(_sc); _sc.loader.exec_module(_mm)
                prompt = prompt + ", " + _mm.suffix(_st)
            else:
                prompt = prompt + ", " + _style_suffix
        prompt, added = enforce_prop_contract(name, prompt)
        if added:
            print(f"  [契约补全] {name} 缺 {len(added)} 条道具光照/底约束, 已自动追加: "
                  + "; ".join(a[:48] for a in added))
        # 背景契约。冲突/密度判定只看**作者自己写的** prompt —— 与上面键色带门同一条教训:
        # `--style` 注入的画风锚点里合法地带颜色词与流派名词, 拿它去查会假阳性拦死整批图。
        _, bg_added, bg_fails, bg_warns = bg_contract(name, job["prompt"], job.get("bg_role"), _ground_clause)
        if bg_fails:
            print(f"[FAIL] {name}: {bg_fails[0]}")
            sys.exit(1)
        for w in bg_warns:
            print(f"  [背景措辞] {name}: {w}")
        if bg_added:
            prompt = prompt + ", " + bg_added[0]
            print(f"  [背景契约] {name} 注入 {job.get('bg_role') or 'stage'}"
                  f" 尾巴({len(bg_added[0])} 字符)" + ("，含本片地色" if _ground_clause else "，无 palette 故不含颜色"))
        if name.startswith("prop_"):
            # 只查**作者自己写的** prompt。契约追加的 #FF00FF 是键色底, 它本来就该被抠掉,
            # 拿带内色去查它会 100% 假阳性(第一版就栽在这, 直接拦死了整批道具)。
            bad = key_band_conflicts(job["prompt"])
            if bad:
                print(f"[FAIL] {name} 的 prompt 含键色带内的颜色: {'; '.join(bad)}\n"
                      f"  → --hsv 抠图把 H≈275°-350° 高饱和像素判成背景, 这个色会被直接抠穿成洞。\n"
                      f"  → 这类标记改由 PIL 直绘进 assets/lines/(钢印/红笔/勾都是几何), 或把色相挪出带外。")
                sys.exit(1)
        out = args.raw_dir / name
        out.parent.mkdir(parents=True, exist_ok=True)  # name 允许带子目录(bg/x.png); 不建目录会在**已扣费拿到图之后**写盘崩溃
        if out.exists() and out.stat().st_size > 0:
            if not args.overwrite:
                # V3.26: 旧版这里仍调 register(out, prompt) —— prompt 是**本次改过的新串**, 文件却是
                # 上一版的旧图, 于是账本给一张旧图盖了"由新提示词生成"的假章(还写 prompt_hash)。
                # 跳过重生可以, 但绝不能伪造出处。
                print(f"skip: {name} —— 盘上已有图, 未重生, **不更新账本出处**; "
                      f"它可能不是当前 prompt 的产物。要真重生请加 --overwrite(旧图自动进 qa/prev_assets/)")
                continue
            # 重生前把旧图挪进 qa/prev_assets/(可逆)。直接覆盖 = 上一版好图找不回来;
            # 手删文件才能重跑 = 不可逆, 不该是重生的前置动作。
            bak = args.raw_dir.parent.parent / "qa" / "prev_assets"
            bak.mkdir(parents=True, exist_ok=True)
            old = bak / (out.stem + ".v" + hashlib.sha256(out.read_bytes()).hexdigest()[:8] + out.suffix)
            out.rename(old)
            print(f"overwrite: {name} 旧图 → {old.relative_to(args.raw_dir.parent.parent)}")
        payload = {"model": image_model, "prompt": prompt,
                   "response_format": "b64_json"}
        if job.get("size"):
            payload["size"] = job["size"]  # ⚠️ height x width! 竖版传 "1184x896" → 896x1184
        if job.get("ref"):
            ref = Path(job["ref"])
            suffix = ref.suffix.lstrip(".").lower() or "png"
            payload["image"] = f"data:image/{suffix};base64,{base64.b64encode(ref.read_bytes()).decode()}"
        print(f"gen: {name}{' (+ref)' if job.get('ref') else ''}")
        data = post(payload)
        items = data.get("data") or []
        if not items or not items[0].get("b64_json"):
            sys.exit(f"响应无图: {json.dumps(data, ensure_ascii=False)[:300]}")
        out.write_bytes(base64.b64decode(items[0]["b64_json"]))
        register(out, prompt)
        print(f"  -> {out} ({out.stat().st_size} bytes) +ledger")
    print(f"\n完成 {len(jobs)} 项 -> {args.raw_dir}(账本 {ledger})")


if __name__ == "__main__":
    main()
