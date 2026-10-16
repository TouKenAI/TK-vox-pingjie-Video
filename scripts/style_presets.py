#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.7 风格提示词库：4 主风格 + 1 贯穿层 + "反差混搭"默认新颖性机制。

每套 = 固定风格锚点词块(接进 gen_assets 的 prompt 后缀) + OKLCH 校验配色 + 动效/版式配套
      + 去AI批量感清单 + 反差元素池。按选题调性选主风格，**强制叠加 1 个反差元素**保差异。

用法:
  py style_presets.py list
  py style_presets.py get 剪纸拼贴            # 输出锚点词块+配色+动效+反差建议
  py style_presets.py suffix 国潮水墨          # 只输出可直接拼进 prompt 的风格后缀
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

# 通用负面/约束(管线友好: 无文字/无真人脸/主体清晰/边缘利落/避键色同族)
COMMON_NEG = "no text, no letters, no numbers, no watermark, no signature, no faces, no readable UI text, no oversaturation, no blur, clean hard edges, subject not touching frame edges"
# 原则: Specificity beats superlatives — 禁用 beautiful/stunning/8K masterpiece 等空泛词(gptprompts ink-wash 指南)

# V3.7 用户定版: 稳用三套 + 报纸谨慎(易画乱码字,需强负面或后期PIL覆盖)
DEFAULT_STYLES = ["剪纸拼贴", "国潮水墨", "白板手绘", "等距2.5D", "漫画网点", "浮世绘工笔"]
CAUTION_STYLES = {"复古报纸": "报纸题材易招乱码拉丁字; 用则每张目检+PIL覆盖, 或加更强 no text 负面"}
# 用户 2026-09-11 六宫格验货后钦定首选(选题命中优先用这三套, 其余按题材兜底)
PREFERRED_STYLES = ["等距2.5D", "白板手绘", "漫画网点"]

STYLES = {
  "剪纸拼贴": {
    "适配": "商业/科技/时事解读(主力)",
    "anchor": "paper craft, paper cut art, layered cut paper with visible paper edges, subtle shadows between layers, textured paper, depth through stacking, editorial collage, main light upper-left 45 degrees",
    "palette": {"bg": "243,236,221", "ink": "43,34,26", "accent": "224,106,32", "accent2": "58,140,90"},
    "motion": "drop_in 坠落回弹 / rise 升起 / orbit 环绕 / 撕纸擦除转场 / 描边揭示",
    "去AI感": "保留撕边不完美、纸纤维、轻微套印错位; 忌过度光滑",
    "反差池": ["+像素故障glitch", "+霓虹数据流", "+手绘涂鸦批注", "+真实照片贴图"],
  },
  "国潮水墨": {
    "适配": "人文/历史/本土话题; 科技解读做古今反差也强",
    "anchor": "traditional East Asian ink-wash brush painting (shuimo/sumi-e), black ink with varying dilutions, rice paper texture, ink bleed and feibai dry-brush, generous negative space, minimalist, one vermilion seal accent",
    "palette": {"bg": "240,235,222", "ink": "28,28,30", "accent": "190,45,40", "accent2": "40,70,110"},
    "motion": "墨晕揭示(线自绘) / 笔触划出 / 印章砸落 / 留白入场",
    "去AI感": "笔触留飞白/浓淡不匀; 忌数码平滑渐变",
    "反差池": ["+霓虹数据流(古今)", "+等距机械", "+荧光色图表", "+故障艺术"],
  },
  "复古报纸": {
    "适配": "时事/调查/历史/深度",
    "anchor": "vintage risograph print collage, halftone dots, misregistration, aged newspaper and kraft paper, typewriter clipping layout, red rubber stamp, coffee stains, torn edges, muted sepia with red accent",
    "palette": {"bg": "224,210,180", "ink": "40,36,30", "accent": "170,45,40", "accent2": "50,70,110"},
    "motion": "剪报飞入 / 图钉摁下 / 印章砸落 / 翻页 / 高亮划线",
    "去AI感": "真实做旧、折痕污渍、不规则裁边",
    "反差池": ["+手绘涂鸦圈点", "+现代UI截图框", "+霓虹关键词", "+老胶片颗粒"],
  },
  "白板手绘": {
    "适配": "科普/原理/流程(获得感最强)",
    "anchor": "hand-drawn sketchnote whiteboard explainer, visual note-taking, clean marker strokes, doodles, arrows, educational diagram, sticky notes, imperfect hand lines, high contrast on whiteboard, one or two accent colors",
    "palette": {"bg": "248,248,244", "ink": "30,34,40", "accent": "20,110,190", "accent2": "220,70,60"},
    "motion": "描边自绘(line-draw) / 箭头生长 / 贴纸弹入 / 圈点强调",
    "去AI感": "故意手抖、涂改痕迹、笔迹不均",
    "抠图策略": "细马克线易丢像素→生图用粗笔画, 或干脆PIL矢量画线/箭头/圈(不走洋红抠)",
    "动效套件": "描边自绘line-draw / 箭头生长 / 便利贴peel弹入 / 圈点强调 / 逐词手写",
    "反差池": ["+真实照片贴图", "+3D小道具", "+剪纸层", "+霓虹高亮"],
  },
  "等距2.5D": {
    "适配": "科技架构/系统/流程/供应链/数据空间感",
    "anchor": "isometric illustration, axonometric projection, 30-degree isometric angle, no perspective distortion, flat shading, soft contact shadows, miniature diorama, detailed miniature, clean vector shapes, game asset style",
    "palette": {"bg": "234,238,244", "ink": "28,36,52", "accent": "35,105,215", "accent2": "130,190,60"},
    "motion": "模块 rise 升起堆叠 / 沿轴推进 / cross-section 剖开 / 数据流沿线跑",
    "去AI感": "保留微缩景深(tilt-shift)与手工装配感; 忌过度光滑塑料质感",
    "抠图策略": "等距体边缘利落+matte平涂→despill可; 避大渐变高光; 投影交给渲染器shadow, 别画进图",
    "动效套件": "模块沿轴rise堆叠 / cross-section剖开 / 数据沿轴流 / 相机缓推微缩景深",
    "反差池": ["+手绘标注涂鸦", "+剪纸层叠", "+霓虹数据流", "+真实照片贴图"],
  },
  "漫画网点": {
    "适配": "时事/冲突/争议/人物/戏剧张力",
    "anchor": "retro pop art comic in Roy Lichtenstein style, Ben-Day registration dots, bold black outlines, flat primary colors, speech bubble, dynamic action lines, vintage comic panel, high contrast",
    "palette": {"bg": "250,240,222", "ink": "20,20,22", "accent": "225,50,45", "accent2": "40,90,200"},
    "motion": "分格砸入 / 速度线 / 对话气泡弹入 / 网点闪动 / 撞色 burst",
    "去AI感": "网点与套色错位保留印刷味; 忌数码平滑",
    "抠图策略": "粗黑边+平涂三原色→抠图最干净(高对比边缘); Ben-Day网点作纹理OK",
    "动效套件": "分格砸入 / 速度线放射 / 对话泡弹入 / 网点闪动 / 撞色burst",
    "反差池": ["+水墨笔触(东西撞)", "+数据图表", "+真实照片分格", "+故障glitch"],
  },
  "浮世绘工笔": {
    "适配": "人文/历史/文化/本土/东方叙事",
    "anchor": "ukiyo-e Japanese woodblock print, flat color areas, bold keylines, Hokusai style, mineral pigment colors, subtle washi paper grain, gongbi meticulous detail, elegant composition",
    "palette": {"bg": "238,232,214", "ink": "32,30,34", "accent": "30,80,150", "accent2": "150,90,160"},
    "motion": "浪/云 平移涌起 / 描边揭示 / 印章落 / 卷轴展开",
    "去AI感": "保留木版套色错位与和纸纹理; 忌照片级写实",
    "反差池": ["+霓虹数据流(古今)", "+等距机械", "+现代UI框", "+漫画网点"],
  },
  "动态字体": {  # 贯穿层, 叠加在主风格上
    "适配": "所有片: 金句/CTA/情绪重音",
    "anchor": "(PIL 字卡层, 非生图) 超大醒目字 + 撞色块 + 逐词弹入 + shimmer 扫光",
    "palette": {"ink": "240,238,230", "accent": "224,106,32"},
    "motion": "逐词 typewriter / scale 砸入 / shimmer 扫光 / 撞色底衬",
    "去AI感": "手写体×粗黑体混排; 关键手写批注",
    "反差池": ["手写×工业黑", "撞色块×留白"],
  },
}


def _pick(name):
    """风格名必须精确命中键。写错一个字(如"等距 2.5D"多一个空格)此前是裸 KeyError,
    生图跑到这一步才炸——已经在花钱了才知道。现在直接列出可选名。"""
    if name not in STYLES:
        raise SystemExit(f"[FAIL] 风格名 {name!r} 不存在。可用: {' / '.join(STYLES)}"
                         f"(须与键逐字相同, 别加空格)")
    return STYLES[name]


def base(name):
    """风格全名 → 主风格名。「剪纸拼贴·背屏玻璃」/「等距 2.5D·深夜服务台(主风格)」→ 主名。

    单一事实源: gen_assets 的风格声明门、novelty 的连用检测、渲前的动效同构门都走这里。
    各写一份截法, 迟早一份截出「剪纸拼贴」一份截出「剪纸拼贴·背屏玻璃」,
    于是"连用两部同风格"谁也发现不了(p20→p21 实测)。
    截断符之后**再去掉所有空白**——「等距 2.5D」和「等距2.5D」必须归一到同一个键。"""
    s = (name or "").strip()
    for cut in ("·", "（", "(", "/"):
        s = s.split(cut)[0]
    return "".join(s.split())


def suffix(name):
    st = _pick(name)
    return st["anchor"] + ", " + COMMON_NEG


def blend(primary, secondary):
    """混搭: 主风格定背景/美术皮肤, 副风格定叠加元素的抠图+动效; 配色取主。"""
    a, b = STYLES[primary], STYLES[secondary]
    return {
        "主风格(背景/美术)": primary,
        "生图": f"gen_assets --style {primary}  (背景与主体皮肤)",
        "副风格(叠加元素)": secondary,
        "叠加元素抠图": b.get("抠图策略", b["motion"]),
        "叠加元素动效": b["motion"],
        "配色(palette.json)": a["palette"],
        "混搭提示": f"背景={primary}的质感, 前景标注/道具/字卡用{secondary}的语言, 制造层次反差=惊喜感",
        "执行法": "背景 jobs 用 --style " + primary + "; 前景道具 jobs 用 --style " + secondary + " (gen_assets 支持逐 job style 字段); 字卡/配色取主",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    g = sub.add_parser("get"); g.add_argument("style")
    s = sub.add_parser("suffix"); s.add_argument("style")
    bl = sub.add_parser("blend"); bl.add_argument("primary"); bl.add_argument("secondary")
    a = ap.parse_args()
    if a.cmd == "list":
        for k, v in STYLES.items():
            mark = " ★首选" if k in PREFERRED_STYLES else ("  ⚠谨慎" if k in CAUTION_STYLES else "")
            print(f"{k} — {v['适配']}{mark}")
        print("\n默认机制: 选1主风格 + 强制叠1个反差元素; 可 `blend 主 副` 混搭两套(主定背景, 副定叠加元素语言)。")
    elif a.cmd == "suffix":
        print(suffix(a.style))
    elif a.cmd == "blend":
        for k, v in blend(a.primary, a.secondary).items():
            print(f"{k}: {v}")
    elif a.cmd == "get":
        v = _pick(a.style)
        print("适配:", v["适配"]); print("锚点词块:", v["anchor"], "+", COMMON_NEG)
        print("OKLCH配色(palette.json用):", json.dumps(v["palette"], ensure_ascii=False))
        print("抠图策略:", v.get("抠图策略", "—"))
        print("动效套件:", v.get("动效套件", v["motion"]))
        print("去AI感:", v["去AI感"]); print("反差元素池:", v["反差池"])


if __name__ == "__main__":
    main()
