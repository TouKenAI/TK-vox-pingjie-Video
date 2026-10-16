#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景指纹 —— "这批帧是用哪个版本的**场景 JSON + 资产 + 渲染器**渲出来的"。

为什么要比 `sha256(scene.json)` 更宽：V3.24⑭ 记过一个盲区——只按场景 JSON 判"要不要重渲"，
**换背景/换道具/改渲染器都看不见**。p23 实录两笔：
  · 重抠 `prop_phone_hero`（--despill 改 hsv）bbox 从 1220 变成 1226，坐标夹取跟着变，
    而场景 JSON 一个字没改 → 只看 JSON 的戳会说"帧是新的"，成片用的还是旧素材的帧；
  · `bg_store_finale` 重抽了一版（中心那架纸飞机换成整幅撕纸条），同样不动 JSON。

所以指纹 = 场景 JSON 字节 + 每个被引用资产的内容哈希 + 渲染器自身哈希。
资产哈希走 `qa/asset_hashes.json` 缓存（键 = 相对路径 + 字节数 + mtime_ns），
第二次跑同一部片几乎零成本；只有真被改写的文件才重算。

产物两个戳，都在 `qa/frame_stamps/`：
  frames_sNN.hash  sha256(scene json)[:16]          —— 旧格式，produce 向后兼容继续认
  frames_sNN.fp    fingerprint()[:16]               —— 新格式，含资产与渲染器

⚠ 戳必须由**产出帧的那一方**写（V3.24 教训：只有 render_all 盖章时，单场手工重渲就留了旧戳）。
   render_sequence / render_all 都调 write_stamps()，实现只有这一份。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RENDERER = HERE / "render_sequence.py"


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _load_cache(proj: Path) -> dict:
    c = proj / "qa" / "asset_hashes.json"
    if c.exists():
        try:
            return json.loads(c.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}          # 缓存坏了就重算，不是失败
    return {}


def _save_cache(proj: Path, cache: dict) -> None:
    c = proj / "qa" / "asset_hashes.json"
    c.parent.mkdir(parents=True, exist_ok=True)
    c.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def asset_refs(plan: dict) -> list[str]:
    """场景里所有会被渲染器读盘的相对路径（背景 / 图层 / seq 目录 / debris 源）。"""
    refs: list[str] = []
    bg = (plan.get("background") or {}).get("path")
    if bg:
        refs.append(str(bg))
    for lay in plan.get("layers", []):
        if lay.get("path"):
            refs.append(str(lay["path"]))
        if lay.get("seq_dir"):
            refs.append(str(lay["seq_dir"]))          # 目录：下面按 *.png 展开
        if lay.get("sprite_sheet"):
            refs.append(str(lay["sprite_sheet"]))
    for ef in plan.get("effects", []):
        if isinstance(ef, dict) and ef.get("source"):
            refs.append(str(ef["source"]))
    out, seen = [], set()
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return sorted(out)


def fingerprint(scene_path: Path, proj: Path | None = None, cache: dict | None = None,
                write_cache: bool = False) -> str:
    """场景 JSON + 全部引用资产 + 渲染器 的联合指纹（十六进制全长）。"""
    scene_path = Path(scene_path)
    proj = Path(proj) if proj else scene_path.resolve().parent
    own = cache if cache is not None else _load_cache(proj)
    parts = ["scene:" + hashlib.sha256(scene_path.read_bytes()).hexdigest()]
    if RENDERER.exists():
        parts.append("renderer:" + _sha_file(RENDERER))
    plan = json.loads(scene_path.read_text(encoding="utf-8-sig"))
    for rel in asset_refs(plan):
        p = (proj / rel)
        if p.is_dir():
            files = sorted(p.glob("*.png"))
            if not files:
                parts.append(f"{rel}:EMPTY_DIR")
            for f in files:
                parts.append(f"{rel}/{f.name}:" + _hashed(f, rel + "/" + f.name, own))
        elif p.exists():
            parts.append(f"{rel}:" + _hashed(p, rel, own))
        else:
            parts.append(f"{rel}:MISSING")     # 缺资产由 preflight 报错，这里只保证指纹会变
    if cache is None and write_cache:
        _save_cache(proj, own)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _probe(p: Path) -> str:
    """内容探针：头 4KB + 尾 4KB 的摘要。PNG 是熵编码流，改一个字节会让尾部完全变样，
    所以"改内容但 size/mtime 不变"这种缓存投毒，靠探针就能抓到。"""
    with open(p, "rb") as fh:
        h = fh.read(4096)
        try:
            fh.seek(-4096, 2)
            t = fh.read(4096)
        except OSError:
            t = b""
    return hashlib.sha256(h + b"|" + t).hexdigest()


def _hashed(p: Path, key: str, cache: dict) -> str:
    """缓存只做"同一次跑动里同一资产不重复哈希"(105 张 × 16 场的引用重复)，
    命中条件必须含内容探针——V3.40 前只看 size+mtime_ns，实测可被假绿：
    生成器重写同尺寸同 mtime 的 PNG 时，旧哈希被端回来，reusable() 报"指纹命中"。"""
    st = p.stat()
    prb = _probe(p)
    ent = cache.get(key)
    if (ent and ent.get("size") == st.st_size and ent.get("mtime_ns") == st.st_mtime_ns
            and ent.get("probe") == prb):
        return ent["sha"]
    sha = _sha_file(p)
    cache[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "probe": prb, "sha": sha}
    return sha


def expected_frames(scene_path: Path) -> int:
    plan = json.loads(Path(scene_path).read_text(encoding="utf-8-sig"))
    return round(int(plan["fps"]) * float(plan["duration_s"]))


def frames_complete(out_dir: Path, scene_path: Path) -> bool:
    """帧数与场景时长对得上才算"这批帧可用"（半截渲染/被 step 渲过的预览不算）。"""
    if not out_dir.exists():
        return False
    n = len(list(out_dir.glob("frame_*.png")))
    return n == expected_frames(scene_path)


def write_stamps(scene_path: Path, out_dir: Path, proj: Path | None = None) -> None:
    scene_path = Path(scene_path)
    out_dir = Path(out_dir)
    proj = Path(proj) if proj else out_dir.parent
    stamps = proj / "qa" / "frame_stamps"
    stamps.mkdir(parents=True, exist_ok=True)
    (stamps / f"{out_dir.name}.hash").write_text(
        hashlib.sha256(scene_path.read_bytes()).hexdigest()[:16], encoding="utf-8")
    (stamps / f"{out_dir.name}.fp").write_text(
        fingerprint(scene_path, proj, write_cache=True)[:16], encoding="utf-8")


def read_fp(out_dir: Path, proj: Path | None = None) -> str:
    out_dir = Path(out_dir)
    proj = Path(proj) if proj else out_dir.parent
    p = proj / "qa" / "frame_stamps" / f"{out_dir.name}.fp"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def reusable(scene_path: Path, out_dir: Path, proj: Path | None = None) -> tuple[bool, str]:
    """这批帧能不能直接复用？返回 (能/不能, 原因)。原因必须是可判读的具体事实，不写"可能"。"""
    scene_path, out_dir = Path(scene_path), Path(out_dir)
    proj = Path(proj) if proj else out_dir.parent
    if not out_dir.exists():
        return False, "无帧目录"
    n = len(list(out_dir.glob("frame_*.png")))
    if n == 0:
        return False, "帧目录为空"
    want = expected_frames(scene_path)
    if n != want:
        return False, f"帧数 {n} ≠ 应有 {want}（半截渲染或 animatic 预览）"
    old = read_fp(out_dir, proj)
    if not old:
        return False, "无资产级帧戳（旧版渲的，无法证明资产没换过）"
    new = fingerprint(scene_path, proj, write_cache=True)[:16]
    if old != new:
        return False, f"指纹变了 {old}→{new}（场景 JSON / 资产 / 渲染器 之一被改过）"
    return True, f"指纹命中 {new}，{n} 帧齐"
