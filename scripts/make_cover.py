#!/usr/bin/env python3
"""封面帧生成器 —— 封面图 = 视频第一帧(抖音封面+首帧复合决策)。

流程:StepFun 生竖版无字底图(1184x896 参数,返回 896x1184 ≈3:4)→放大 1080x1440
→PIL 叠大字钩子(描边+投影,信息流缩略图可读)→存 assets/source/cover.png。
配套 build_scenes 约定:S01 最顶层加 cover 层,f0 全屏静止,f8 后 12 帧淡出进正片——
第一帧即封面,不改变片长与音画同步。

用法:
  python make_cover.py --prompt "..." --line1 "夸孩子聪明" --line2 "反而害了他" \
      --film productionN [--accent 255,190,88]
底图 prompt 建议:矛盾最强的视觉+大面积留白给文字(上 1/3 或下 1/3 空区),no text。
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

PY = sys.executable
STEPTOOLS_CANDIDATES = [
    Path.cwd() / "stepfun_tools.py",
    Path(__file__).resolve().parent.parent.parent / "stepfun_tools.py",
]
FONTS = [Path("C:/Windows/Fonts/msyhbd.ttc"), Path("C:/Windows/Fonts/msyh.ttc")]


def key() -> str:
    env = Path.cwd()
    for base in [env, *env.parents]:
        f = base / ".env"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("STEPFUN_API_KEY="):
                    return line.split("=", 1)[1].strip()
    sys.exit("no .env key")


def gen_base(prompt: str, out: Path) -> None:
    req = urllib.request.Request(
        "https://api.stepfun.com/step_plan/v1/images/generations",
        data=json.dumps({"model": "step-image-edit-2", "prompt": prompt,
                         "size": "1184x896",  # height x width -> 896x1184 竖版
                         "response_format": "b64_json"}).encode(),
        headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    b64 = (data.get("data") or [{}])[0].get("b64_json")
    if not b64:
        sys.exit(f"no image: {json.dumps(data)[:200]}")
    out.write_bytes(base64.b64decode(b64))


def fit_cover_1080x1440(img):
    """等比放大 + 居中微裁到精确 1080x1440(比例零变形,宽度仅裁 0.87%)。
    API 无 1080x1440 档,896x1184(≈3:4)是最接近白名单尺寸。"""
    from PIL import Image
    W, H = 1080, 1440
    s = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.Resampling.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def compose(base: Path, line1: str, line2: str, accent: tuple, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    img = fit_cover_1080x1440(Image.open(base).convert("RGB"))
    base_font = ImageFont.truetype(str(FONTS[0] if FONTS[0].exists() else FONTS[1]), size=170)

    def fitted_font(text, max_width=1000):
        """自适应字号:行宽 ≤1000px(画布 1080 留 40px 边距),防大字裁切。"""
        size = 170
        while size > 60:
            f = ImageFont.truetype(str(FONTS[0] if FONTS[0].exists() else FONTS[1]), size=size)
            bb = f.getbbox(text)
            if bb[2] - bb[0] <= max_width:
                return f
            size -= 6
        return f

    def text_size(f, t):
        bb = f.getbbox(t)
        return bb[2] - bb[0], bb[3] - bb[1]

    rows = [(line1, 700), (line2, 930)]
    draw = ImageDraw.Draw(img)
    # 底部暗带提升文字可读性(半透明黑,叠在生图上)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, 610, 1080, 1120], fill=(10, 10, 24, 130))
    overlay = overlay.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(img)
    for text, cy in rows:
        font = fitted_font(text)
        tw, th = text_size(font, text)
        x = (1080 - tw) // 2
        # 描边 + 投影 + 主体
        for dx, dy, col in [(-6, 0, (0, 0, 0, 220)), (6, 0, (0, 0, 0, 220)), (0, -6, (0, 0, 0, 220)),
                            (0, 6, (0, 0, 0, 220)), (8, 10, (0, 0, 0, 120))]:
            draw.text((x + dx, cy + dy), text, font=font, fill=col)
        draw.text((x, cy), text, font=font, fill=accent)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=95)
    print(f"cover -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--film", required=True, help="production 目录")
    ap.add_argument("--prompt", required=True, help="底图视觉 prompt(英文,矛盾最强视觉+留白,no text)")
    ap.add_argument("--line1", required=True, help="钩子第一行(≤8字)")
    ap.add_argument("--line2", required=True, help="钩子第二行(≤8字)")
    ap.add_argument("--accent", default="255,210,96", help="主文字颜色 RGB")
    ap.add_argument("--name", default="cover", help="输出名(多版本候选: cover_a/cover_b/cover_c)")
    ap.add_argument("--no-regen", action="store_true", help="复用已有底图,只重排版")
    a = ap.parse_args()
    root = Path(a.film).resolve()
    raw = root / "assets" / "raw" / f"cover_base_{a.name}.png"  # 底图按 name 存,多版本互不覆盖
    out = root / "assets" / "source" / f"{a.name}.png"
    if a.no_regen:
        if not raw.exists():
            # 兼容首版命名
            legacy = root / "assets" / "raw" / "cover_base.png"
            if legacy.exists():
                raw = legacy
            else:
                sys.exit("no base image; 先不带 --no-regen 跑一次")
    else:
        gen_base(a.prompt, raw)
    compose(raw, a.line1, a.line2, tuple(int(v) for v in a.accent.split(",")), out)
    # 登记
    import hashlib, time
    led = root / "assets" / "ledger.jsonl"
    with led.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"file": f"assets/source/{a.name}.png",
                             "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                             "production": root.name, "prompt_hash": "cover",
                             "created": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
    print("registered + ledger. build_scenes 约定: S01 顶层加 cover 层(f0 静止,f8 后 12 帧淡出)")


if __name__ == "__main__":
    main()
