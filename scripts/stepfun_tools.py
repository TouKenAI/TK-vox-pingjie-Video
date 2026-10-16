#!/usr/bin/env python3
"""StepFun API 客户端 —— 为拼贴动画项目提供生图 / TTS / 音色 / ASR 调用入口。

仅依赖标准库。密钥与端点从同目录 .env 读取,也可用环境变量覆盖。
用法示例:
  py -3.14 stepfun_tools.py image --prompt "纸质拼贴风格的深夜海面" --out out.png
  py -3.14 stepfun_tools.py tts --text "深夜,一艘邮轮逼近冰山。" --out narr.mp3
  py -3.14 stepfun_tools.py preview --text "音色试听文本"
  py -3.14 stepfun_tools.py asr --file narr.mp3
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

BASE_DEFAULT = "https://api.stepfun.com/step_plan/v1"
TIMEOUT = 180


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    candidates = [Path(__file__).resolve().parent]
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents[:3]])
    for directory in candidates:
        dotenv = directory / ".env"
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    name, value = line.split("=", 1)
                    env.setdefault(name.strip(), value.strip())
            break
    return env


def setting(env: dict[str, str], name: str, fallback: str = "") -> str:
    return os.environ.get(name) or env.get(name) or fallback


class ApiError(RuntimeError):
    pass


def post_json(url: str, key: str, payload: dict, timeout: int = TIMEOUT) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {error.code} from {url}\n{detail}") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def post_audio(url: str, key: str, payload: dict, timeout: int = TIMEOUT) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {error.code} from {url}\n{detail}") from error


def post_sse(url: str, key: str, payload: dict, timeout: int = TIMEOUT) -> str:
    """流式 ASR:按事件类型解析 —— delta 事件累加增量,done 事件的 text 为准。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    deltas: list[str] = []
    final_text = ""
    raw_events: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for line in response:
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                chunk = text[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    item = json.loads(chunk)
                except json.JSONDecodeError:
                    raw_events.append(chunk)
                    continue
                kind = item.get("type", "")
                if kind.endswith(".delta") and isinstance(item.get("delta"), str):
                    deltas.append(item["delta"])
                elif kind.endswith(".done"):
                    for field in ("text", "transcript", "content"):
                        value = item.get(field)
                        if isinstance(value, str):
                            final_text = value
                            break
                else:
                    for field in ("text", "delta", "transcript", "content"):
                        value = item.get(field)
                        if isinstance(value, str):
                            deltas.append(value)
                            break
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {error.code} from {url}\n{detail}") from error
    if final_text:
        return final_text
    if deltas:
        return "".join(deltas)
    return "\n".join(raw_events)


def save_image_from_response(data: dict, out_path: Path) -> None:
    items = data.get("data") or []
    if not items:
        raise ApiError(f"响应中没有 data 字段:{json.dumps(data, ensure_ascii=False)[:800]}")
    first = items[0]
    if first.get("b64_json"):
        out_path.write_bytes(base64.b64decode(first["b64_json"]))
    elif first.get("url"):
        request = urllib.request.Request(first["url"], method="GET")
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            out_path.write_bytes(response.read())
    else:
        raise ApiError(f"data[0] 里既无 b64_json 也无 url:{json.dumps(first, ensure_ascii=False)[:400]}")


def cmd_image(args: argparse.Namespace, cfg: dict[str, str]) -> None:
    payload: dict = {"model": cfg["image_model"], "prompt": args.prompt}
    if args.size:
        payload["size"] = args.size
    if args.response_format:
        payload["response_format"] = args.response_format
    if args.ref:
        ref_path = Path(args.ref)
        suffix = ref_path.suffix.lstrip(".").lower() or "png"
        encoded = base64.b64encode(ref_path.read_bytes()).decode()
        payload["image"] = f"data:image/{suffix};base64,{encoded}"
    print(f"POST {cfg['url_images']} model={payload['model']} size={payload.get('size', '(default)')}")
    data = post_json(cfg["url_images"], cfg["key"], payload)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_image_from_response(data, out)
    usage = data.get("usage")
    print(f"saved {out} ({out.stat().st_size} bytes)" + (f" usage={json.dumps(usage)}" if usage else ""))
    verify_png(out)


def verify_png(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        print("(未安装 Pillow,跳过像素校验)")
        return
    with Image.open(path) as image:
        has_alpha = image.mode in ("RGBA", "LA") and min(image.convert("RGBA").getchannel("A").getextrema()) < 255
        print(f"PIL 校验: format={image.format} mode={image.mode} size={image.size} alpha={'有透明' if has_alpha else '无透明'}")


def cmd_tts(args: argparse.Namespace, cfg: dict[str, str]) -> None:
    payload: dict = {"model": cfg["tts_model"], "input": args.text, "voice": args.voice}
    if args.instruction:
        payload["instruction"] = args.instruction
    if args.format:
        payload["response_format"] = args.format
    if args.speed is not None:
        payload["speed"] = args.speed
    print(f"POST {cfg['url_speech']} model={payload['model']} voice={payload.get('voice', '(default)')}")
    audio, content_type = post_audio(cfg["url_speech"], cfg["key"], payload)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    print(f"saved {out} ({len(audio)} bytes, content-type={content_type})")


def cmd_preview(args: argparse.Namespace, cfg: dict[str, str]) -> None:
    payload: dict = {"model": cfg["tts_model"], "text": args.text}
    if args.voice:
        payload["voice"] = args.voice
    print(f"POST {cfg['url_voices_preview']}")
    try:
        data = post_json(cfg["url_voices_preview"], cfg["key"], payload)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    except ApiError as error:
        print(f"试听失败(端点参数可能不同):\n{error}")


def cmd_voices(args: argparse.Namespace, cfg: dict[str, str]) -> None:
    payload: dict = {"model": cfg["tts_model"]}
    if args.clone_name and args.sample:
        sample = Path(args.sample)
        encoded = base64.b64encode(sample.read_bytes()).decode()
        payload = {"model": cfg["tts_model"], "voice_name": args.clone_name, "audio_data": encoded}
        print(f"POST {cfg['url_voices']} (复刻 voice_name={args.clone_name})")
    else:
        print(f"POST {cfg['url_voices']} (查询)")
    try:
        data = post_json(cfg["url_voices"], cfg["key"], payload)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])
    except ApiError as error:
        print(f"请求失败(端点参数可能不同):\n{error}")


def cmd_asr(args: argparse.Namespace, cfg: dict[str, str]) -> None:
    audio_path = Path(args.file)
    encoded = base64.b64encode(audio_path.read_bytes()).decode()
    kind = audio_path.suffix.lstrip(".").lower()
    fmt = {
        "wav": {"type": "wav", "codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1},
        "pcm": {"type": "pcm", "codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1},
        "mp3": {"type": "mp3", "codec": "mp3", "rate": 44100, "bits": 0, "channel": 1},
    }.get(kind, {"type": kind or "mp3"})
    payload = {
        "audio": {
            "data": encoded,
            "input": {
                "transcription": {"model": cfg["asr_model"], "language": args.language, "enable_itn": True},
                "format": fmt,
            },
        }
    }
    print(f"POST {cfg['url_asr_sse']} model={cfg['asr_model']} file={audio_path.name}")
    try:
        text = post_sse(cfg["url_asr_sse"], cfg["key"], payload)
        print(f"识别结果:\n{text}")
    except ApiError as error:
        print(f"识别失败(端点入参可能不同):\n{error}")


def main() -> None:
    env = load_env()
    base = setting(env, "STEPFUN_BASE_URL", BASE_DEFAULT).rstrip("/")
    cfg = {
        "key": setting(env, "STEPFUN_API_KEY"),
        "base": base,
        "image_model": setting(env, "STEPFUN_IMAGE_MODEL", "step-image-edit-2"),
        "tts_model": setting(env, "STEPFUN_TTS_MODEL", "stepaudio-2.5-tts"),
        "asr_model": setting(env, "STEPFUN_ASR_MODEL", "stepaudio-2.5-asr"),
        "url_images": setting(env, "STEPFUN_URL_IMAGES", f"{base}/images/generations"),
        "url_speech": setting(env, "STEPFUN_URL_SPEECH", f"{base}/audio/speech"),
        "url_voices_preview": setting(env, "STEPFUN_URL_VOICES_PREVIEW", f"{base}/audio/voices/preview"),
        "url_voices": setting(env, "STEPFUN_URL_VOICES", f"{base}/audio/voices"),
        "url_asr_sse": setting(env, "STEPFUN_URL_ASR_SSE", f"{base}/audio/asr/sse"),
    }
    if not cfg["key"]:
        sys.exit("缺少 STEPFUN_API_KEY:请检查 .env 或环境变量")

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_image = sub.add_parser("image", help="生成/编辑图片 (step-image-edit-2)")
    p_image.add_argument("--prompt", required=True)
    p_image.add_argument("--out", required=True)
    p_image.add_argument("--size", help="如 1024x1024、2048x2048")
    p_image.add_argument("--ref", help="参考图路径(图生图/编辑)")
    p_image.add_argument("--response-format", choices=["url", "b64_json"])
    p_image.set_defaults(func=cmd_image)

    p_tts = sub.add_parser("tts", help="语音合成 (stepaudio-2.5-tts)")
    p_tts.add_argument("--text", required=True)
    p_tts.add_argument("--out", required=True)
    p_tts.add_argument("--voice", default="cixingnansheng", help="音色ID,如 cixingnansheng / linjiajiejie")
    p_tts.add_argument("--instruction", help="语气/语速控制,如 '语气温柔,语速偏慢'")
    p_tts.add_argument("--format", dest="format", help="如 mp3/wav/opus")
    p_tts.add_argument("--speed", type=float)
    p_tts.set_defaults(func=cmd_tts)

    p_preview = sub.add_parser("preview", help="音色试听 (/audio/voices/preview)")
    p_preview.add_argument("--text", default="这是一段音色试听文本。")
    p_preview.add_argument("--voice")
    p_preview.set_defaults(func=cmd_preview)

    p_voices = sub.add_parser("voices", help="查询/复刻音色 (/audio/voices)")
    p_voices.add_argument("--clone-name", help="复刻的音色名称")
    p_voices.add_argument("--sample", help="复刻用的音频样本路径")
    p_voices.set_defaults(func=cmd_voices)

    p_asr = sub.add_parser("asr", help="语音识别 (/audio/asr/sse)")
    p_asr.add_argument("--file", required=True)
    p_asr.add_argument("--language", default="zh")
    p_asr.set_defaults(func=cmd_asr)

    args = parser.parse_args()
    try:
        args.func(args, cfg)
    except ApiError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
