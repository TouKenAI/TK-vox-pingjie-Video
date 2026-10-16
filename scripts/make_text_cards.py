#!/usr/bin/env python3
"""生成拼贴动画用的文字卡 PNG(RGBA,米色字+微纸感),输出到 production/assets/text/。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

OUT = Path("production/assets/text")
MANIFEST = []   # V3.39: card_text_check 的登记账——临时补卡不回写本脚本, 渲前门当场拦
FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
]
CREAM = (233, 226, 208, 255)
ORANGE = (224, 122, 58, 255)
INK = (27, 23, 22, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    raise SystemExit("no CJK-capable bold font found")


def make_card(name: str, text: str, size: int = 110, color=CREAM, pad: int = 30) -> None:
    font = load_font(size)
    probe = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + pad * 2
    height = bbox[3] - bbox[1] + pad * 2
    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=color)
    OUT.mkdir(parents=True, exist_ok=True)
    card.save(OUT / f"{name}.png")
    MANIFEST.append({"name": name, "text": text, "blank": False})
    print(f"{name}: {card.size}")


def blank_panel(name: str, w: int, h: int, panel=(242, 238, 228, 255), stroke=(20, 20, 22, 255)) -> None:
    """无字实体板(如"隔离房间四壁"): 圆角面板+描边, manifest 声明 blank=true。"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([6, 6, w - 6, h - 6], 16, fill=panel, outline=stroke, width=7)
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / f"{name}.png")
    MANIFEST.append({"name": name, "text": "", "blank": True})
    print(f"{name}: {im.size} (blank)")


def main() -> None:
    make_card("t_title_a", "用 AI 3 分钟", 96, ORANGE)
    make_card("t_title_b", "掌握《精益创业》", 128)
    make_card("t_title_c", "让你少走 6 个月弯路", 84)
    make_card("t_waste_label", "创业最大的浪费不是钱", 88)
    make_card("t_waste_big", "是做了没人要的东西", 132, ORANGE)
    make_card("t_book", "《精益创业》", 110)
    make_card("t_book_author", "ERIC RIES · IMVU 创始人", 60)
    make_card("t_m1", "① 别等完美 先做最小验证", 92)
    make_card("t_m1_sub", "两周内能完成的最小测试：顾客真的需要吗？", 58)
    make_card("t_m2", "② 开发 → 测量 → 认知", 92)
    make_card("t_m2_sub", "从想法到用户反馈，不超过一周", 58)
    make_card("t_m3", "③ 别看总数据 看第一批人", 92)
    make_card("t_m3_sub", "多少人在用核心功能？第二天还回来吗？", 58)
    make_card("t_case_lesson", "花 6 个月做的功能 没人用", 76)
    make_card("t_case_turn", "每天发布近 50 次更新 把「快」刻进 DNA", 66, ORANGE)
    make_card("t_quote", "在黑暗中射击", 120)
    make_card("t_quote2", "不如先点一盏灯", 132, ORANGE)
    make_card("t_quote3", "创业不是赌命 是科学验证", 72)
    make_card("t_cta", "关注我 下期继续读透一本好书", 68)


if __name__ == "__main__":
    main()
    mf = Path("production/qa/card_manifest.json")
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps({"cards": MANIFEST}, ensure_ascii=False, indent=1))
    print(f"{mf}: {len(MANIFEST)} 条")
