# 本机适配说明（QwenWork 环境）· ADAPTATION

本便捷包已在 **本机 / 千问办公（QwenWork）** 环境下完成适配性改造并通过自检。原始包依赖同级技能
`create-collage-animation` 提供核心渲染器，扁平复制到本工作区后该假设失效——已改为**真正自包含**。

## 环境（本机实测）

| 项 | 值 | 结论 |
|---|---|---|
| Python | 3.14.5（`py -3.14` / `py`） | ✓（本机无 3.12，脚本内部走 `sys.executable`，无需改码） |
| `python` 命令 | 是 WindowsStore 别名，**勿用** | 一律 `py -3.14` |
| Pillow / numpy | 12.2.0 / 2.5.0 | ✓ |
| ffmpeg / ffprobe | WinGet 完整版 8.1.1（含 mp3 解码） | ✓ `env_paths.py` 自动解析并校验，R1 红线满足 |
| StepFun API | `.env` 内置 key | ✓ TTS / 生图 / 抠图 / 时长 实测端到端跑通 |

> SKILL.md / README 里出现的 `py -3.12` 是给“外部 Agent”的占位指引；本机执行统一用 **`py -3.14`**。

## 改造内容

1. **补入核心渲染器与配套脚本**（从 `create-collage-animation` 拷入 `scripts/`，均为纯标准库+PIL，无二次依赖）：
   `render_sequence.py`（渲染器）、`validate_sequence.py`、`validate_shot_plan.py`、`build_hyperframes_player.py`、
   `make_contact_sheet.py`、`test_render_sequence.py`。
2. **补入创意契约三份**（拷入 `references/`，SKILL 依赖）：`camera-language.md`、`collage-language.md`、`scene-plan.md`。
3. **渲染器路径改本地优先**（保留旧同级布局作回退）：`render_all.py`、`layout_check.py`、`test_layout_parity.py`。
4. **`preflight_env.py` 对齐扁平布局**：`ROOT` 指向包根（`.env`/账本/`productionN` 所在），E7 渲染器检查接受本地 `scripts/render_sequence.py`。
5. **账本自动建**：`metaphors.json` / `palettes.json` / `ip_registry.json` 首次 `add` 时生成，缺失非阻断。

## 自检结果（全绿）

```
preflight_env.py        → PASS（E1–E7 全过）
test_layout_parity.py   → PASS（ease 对拍 8 名 × 101 点一致；V300 缓动生效）
test_render_sequence.py → OK（渲染器自测 3 例通过，真实出帧）
StepFun TTS / 生图 / cutout_key / audio_duration → 实测端到端跑通
42 个脚本 compileall → 全通过
```

## 安全 / 交付约定

- `.env` 含私人 API key，勿外传、勿上传公开仓库。
- 成片渲染走确定性 Pillow（无浏览器/Remotion 依赖），与千问办公自带 image/video/music 生成工具相互独立——**本包固定使用 StepFun**，因其提示词、抠图、时长链是按 StepFun 调校的。
- 任何 scene/素材/字卡改动后，必须重渲受影响场景并重跑 `qa_deliver.py` 才可交付（禁“改源不重渲”）。
