#!/usr/bin/env python3
"""V3.14b TTS 驱动 —— stepaudio-2.5-tts 走 Step Plan 订阅端点。
payload: {"model","voice","input","instruction","speed"}(顶层 speed 生效, 不吃 parameters.speed)。
两档语速: build=1.15, 其余=1.1。返回 audio/mpeg 原始字节写 mp3。"""
from __future__ import annotations
import json, os, sys, hashlib, urllib.request, urllib.error
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets" / "audio"


def load_env() -> dict:
    for d in [ROOT, ROOT.parent, *ROOT.parents]:
        p = d / ".env"
        if p.exists():
            env: dict[str, str] = {}
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
            return env
    return {}


ENV = load_env()
KEY = os.environ.get("STEPFUN_API_KEY") or ENV.get("STEPFUN_API_KEY", "")
URL = os.environ.get("STEPFUN_URL_SPEECH") or ENV.get(
    "STEPFUN_URL_SPEECH", "https://api.stepfun.com/step_plan/v1/audio/speech")
MODEL = ENV.get("STEPFUN_TTS_MODEL", "stepaudio-2.5-tts")
VOICE = "cixingnansheng"

EMOTIONS = {
    "hook":    "沉稳克制，像压低声音说重要的事，反差词加重",
    "context": "清晰自然的介绍感，不赶",
    "build":   "干脆利落，条理清晰，关键词咬字清楚",
    "proof":   "讲故事的叙述感，语气有起伏，数字处放慢强调",
    "climax":  "一字一顿，句末留出呼吸感，像刻下结论",
    "cta":     "亲切随意，像对朋友说话，句尾微微上扬",
}
ALIAS = {"book": "context", "method": "build", "case": "proof", "quote": "climax"}
EMOTION_SPEED = {"hook": 1.1, "context": 1.1, "build": 1.15, "proof": 1.1, "climax": 1.1, "cta": 1.1}


def synth(text, instruction, speed, out: Path) -> int:
    payload = {"model": MODEL, "voice": VOICE, "input": text, "instruction": instruction, "speed": speed}
    req = urllib.request.Request(URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        ct = r.headers.get("Content-Type", "")
        raw = r.read()
    if "json" in ct.lower():
        raise RuntimeError("JSON resp: " + raw[:300].decode("utf-8", "replace"))
    if not raw or len(raw) < 200:
        raise RuntimeError("音频过小 %d" % len(raw))
    out.write_bytes(raw)
    return len(raw)


def main() -> None:
    chunks = json.loads((ROOT / "chunks.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    # V3.24 断点续跑: 本模板原先无条件重合成全部 chunk —— 中断后重跑 = 整片再扣一遍费,
    # 而 asr_spotcheck 报"只重 TTS 该段"时根本没有单段入口(只能全跑)。
    # 现按 (文本|emotion|speed) 哈希判新旧: 内容没变才跳过; 改了稿子必然换哈希, 不会留下行不对音的旧 mp3。
    only = None
    if "--only" in sys.argv:
        only = {t.strip() for t in sys.argv[sys.argv.index("--only") + 1].split(",") if t.strip()}
    force = "--force" in sys.argv
    stamps_f = OUT / ".tts_stamps.json"
    stamps = json.loads(stamps_f.read_text(encoding="utf-8")) if stamps_f.exists() else {}
    manifest = []
    reused = 0
    for c in chunks:
        emo = ALIAS.get(c.get("emotion", "context"), c.get("emotion", "context"))
        instr = EMOTIONS.get(emo, EMOTIONS["context"])
        speed = float(c.get("speed", EMOTION_SPEED.get(emo, 1.1)))
        spoken = c.get("text_with_cues") or c["text"]
        out = OUT / f"{c['id']}.mp3"
        sig = hashlib.sha256(f"{spoken}|{emo}|{speed}".encode("utf-8")).hexdigest()[:16]
        if only is not None and c["id"] not in only:
            if out.exists() and out.stat().st_size > 200:
                manifest.append({"id": c["id"], "emotion": emo, "speed": speed,
                                 "file": str(out), "bytes": out.stat().st_size})
                reused += 1
                continue
        # --only 点名的段一律重合成; 其余段仅在 (文本|情绪|语速) 哈希未变时复用
        _st = stamps.get(c["id"])
        if _st is None:                                # 该号从没合成过(新段/合并后改写的段)
            _st = {}
        if isinstance(_st, str):                       # 旧表: 只有 sig, 无法回验原文
            _st = {"sig": _st, "text": None}
        _pt = _st.get("text") if isinstance(_st, dict) else None
        if isinstance(_st, dict) and _st.get("sig") == sig and _pt is None:
            print(f"  [无法回验] {c['id']} 的旧 stamp 只存了哈希, 本次按哈希判定复用")
        # ⚠ 复用必须同时满足"哈希一致"**和**"当初写进这个文件的那句原文没变"。
        #   p21 实录: 我合并了一段并整体重编号后手移 stamps, 让 chunk_16 的 sig 指向
        #   旧 17 段, 而 chunk_16.mp3 里装的还是旧 16 段的录音 —— **12 段音频配错文本,
        #   全程没有任何一门会红**。sig 只证明"这个号当初合成时文本没变", 不证明文件对。
        if (not force and only is None and out.exists() and out.stat().st_size > 200
                and _st.get("sig") == sig and (_pt is None or _pt == spoken)):
            print(f"skip: {c['id']} (文本/情绪/语速未变)")
            manifest.append({"id": c["id"], "emotion": emo, "speed": speed,
                             "file": str(out), "bytes": out.stat().st_size})
            reused += 1
            continue
        print(f"=== {c['id']} [{emo}] speed={speed} {len(spoken)}字 ===")
        try:
            n = synth(spoken, instr, speed, out)
            print(f"    OK {n} bytes")
        except urllib.error.HTTPError as e:
            sys.exit(f"TTS HTTP {e.code} @{c['id']}: {e.read().decode('utf-8','replace')[:300]}")
        except Exception as e:
            sys.exit(f"TTS failed @{c['id']}: {e}")
        stamps[c["id"]] = {"sig": sig, "text": spoken}
        manifest.append({"id": c["id"], "emotion": emo, "speed": speed, "file": str(out), "bytes": n})
    stamps_f.write_text(json.dumps(stamps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "tts_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(manifest)} chunks -> {OUT}  (复用 {reused} 段, 本次实际合成 {len(manifest) - reused} 段)")


if __name__ == "__main__":
    main()
