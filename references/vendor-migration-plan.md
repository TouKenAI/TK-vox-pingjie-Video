# 供应商迁移方案（阶跃星辰 → MiMo / 腾讯云 / 商汤 SenseNova）

**执行窗口：2026-09-29 ~ 09-30**（StepFun token plan 到期日）。在此之前**继续全量使用阶跃星辰，不改任何代码**。
本文件是待执行清单，不是当前状态描述。细则权威源仍是 `SKILL.md` + `references/production-playbook.md`。

---

## 0. 已定选型

| 能力 | 现供应商 | 迁往 | 状态 |
|---|---|---|---|
| TTS 旁白 | stepaudio-2.5-tts | **MiMo `mimo-v2.5-tts`** | 已验证可用 |
| ASR 质检 | stepaudio-2.5-asr | **腾讯云一句话识别** `SentenceRecognition` | 已验证可用 |
| ASR 词级时间戳 | 无（silencedetect 估） | 同上 `WordInfo=2` | 新增能力 |
| 生图 | step-image-edit-2 | **商汤 `sensenova-u1.5-lite`（背景）/ `-u1.5-fast`（道具）** | 已验证可用 |
| 封面图 | step-image-edit-2 | 同生图 | ⚠️ `make_cover.py` 独立调用，别漏 |
| 看图 | step-3.7-flash | **取消**，由执行主模型直接看帧 | 无需替换 |
| chat / realtime / voices | — | **死配置**，无脚本调用 | 无需替换 |

能力上只有 **TTS / ASR / 生图** 三项要换，没有第四项。

---

## 1. 代码触点（共 8 个文件）

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `.env` | 新增 `MIMO_*` / `TX_SECRET_*` / `SENSNOVA_*` 段；保留 STEPFUN_* 到 9/30 |
| 2 | `scripts/stepfun_tools.py` | 拆成 provider 层（`tts()` / `asr()` / `image()` 各带后端选择），别再和厂商名绑定 |
| 3 | `scripts/generate_tts_template.py` | 换 chat/completions 载荷 + base64 解码 + wav→mp3 转码 + **429 退避** |
| 4 | `scripts/asr_spotcheck.py` | `asr()` 改调腾讯 |
| 5 | `scripts/asr_final_check.py` | `asr()` 改调腾讯；`norm()` 加异体字归一 |
| 6 | `scripts/gen_assets.py` | base-url / 模型名 / `watermark:false` / **size 串对调** |
| 7 | `scripts/make_cover.py` | 同上（第 46 行独立硬编码了 stepfun 端点） |
| 8 | `scripts/preflight_env.py` | 环境门现在只查 `STEPFUN_API_KEY`，不换检查项会在迁移后假通过或误 FAIL |

新增：`scripts/word_timing.py` 改读腾讯词表并产出 `qa/asr_words.json`（`polycheck_v66.py:145` 早就留了这个入口）。

---

## 2. 三家已实测的硬约束

**MiMo TTS**
- base `https://api.xiaomimimo.com`，**只有 `/v1/chat/completions`**（`/audio/speech` 全 404）
- `messages` 必须含 `assistant` 角色：assistant = 待读文本，user = 自然语言风格指令
- 响应 base64 在 `choices[0].message.audio.data`，**24kHz wav** → 需转 mp3
- **`audio.speed` 参数无效**；语速写进指令文本，且过冲非线性（写"1.3倍"实得≈1.44×）→ `EMOTION_SPEED` 的 1.1/1.15 数值语义作废
- **QPS 极低，连调必 429**，实测需 ~75s 间隔 → 批量必须串行 + 退避
- 端到端回读（MiMo→腾讯 ASR）三段 sim = 0.980 / 0.922 / 0.951，全过 0.90 线；时长与 StepFun 基线差 4% 以内
- 音色克隆可用：`audio.voice` 传 DataURL，12s 参考音即出

**腾讯云 ASR**
- base `asr.tencentcloudapi.com`，version `2019-06-14`，TC3-HMAC-SHA256 签名，region `ap-shanghai`
- 用 `SentenceRecognition`（**不要** `CreateRecTask`，它在 chunk_03 上稳定丢字）
- 参数：`EngSerViceType=16k_zh`、`SourceType=1`(base64，**0 才是 URL**，与旧文档相反)、`VoiceFormat=wav`、`WordInfo=2`
- 返回 `WordList[{Word,StartTime,EndTime}]` 毫秒，含标点占位；≤60s / ≤3MB；免费 5000 次/月按重置
- 参数名和 Go SDK 文档不一致（`CreateRecTask` 用 `EngineModelType`，`SentenceRecognition` 用 `EngSerViceType`）
- 已知词位弱点："先看"会被听成"新款 / Sann看"（确定性，3/3）

**商汤 SenseNova**
- base **`https://token.sensenova.cn`**（不是 platform 域名），OpenAI 兼容 `/v1/images/generations`
- `response_format=b64_json` 直接支持 → `gen_assets.py` 契约不用改
- **默认烧"日日新 sensenova"水印**，`"watermark": false` 可关（必须写进默认载荷）
- **size 语义与 StepFun 相反**：同一串 `"1184x896"`，StepFun 出 896×1184 竖版，商汤出 1184×896 横版
- 默认 2048×2048（~6MB），道具需显式传 `size:"1024x1024"`
- **不支持图生图**：三个出图模型 input 全是 `['text']`，传 `image` 字段不报错但被完全忽略

---

## 3. 规范冲突（必须先裁决，否则迁移后 SKILL 自相矛盾）

`SKILL.md:101` 和 `production-playbook.md:302` 把**主角一致性**写成规则：先文生图基准姿态，再用 `image --ref 基准图` 生成第二姿态。

**商汤做不到**——传 ref 会静默生成一张无关新图。p8–p11 实际 0 次使用 ref，所以没暴雷，但规则还在。

迁移前三选一：
- (a) 改 SKILL：主角一致性改用"同一详细造型描述词块逐字复用"（p8–p11 实际在用的做法）；
- (b) 另找支持图生图的供应商补这一项；
- (c) 保留一条 stepfun 按量余额只用于 `--ref`（到期后 key 是否还能按量计费需确认）。

推荐 (a)：成本零，且与实际做法一致。

---

## 4. 执行顺序建议

1. 先做**生图**（最独立，失败只影响素材，可单场回测）
2. 再做 **ASR + word_timing**（不动产线主流程，只改质检和卡点）
3. 最后做 **TTS**（牵一发动全身：时长→场景→渲染→质检）
4. 每步之后跑一部完整片回归，**与 p11 成片对版**再进下一步

迁移完成前不要动 `SKILL.md` 的版本号；全部通过后一并升版。

---

## 5. 文档待同步

`README.md:22,58`、`SKILL.md:34,35,67,101,386`、`references/production-playbook.md:302,608,859`、`VOX工作流教程_V3.14.html:108,129-132` 里写死的"阶跃星辰 / api.stepfun.com"表述，迁移后一并改。

## 6. 安全

三组密钥（StepFun / MiMo / 腾讯 / 商汤）在对话里明文出现过。迁移完成后建议轮换，并确认 `.env` 不进任何公开仓库或便携包 zip。
