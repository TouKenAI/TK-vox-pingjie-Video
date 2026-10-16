# AGENTS.md — VOX-Video-Qwen 操作契约

口播文案 → Vox 式剪纸拼贴成片（3:4 1080×1440，画面+旁白+音效）的自包含流水线。
当前规范 **V3.42**。本文件只收"会让 agent 犯错"的非显然规则，不重复 README/SKILL。
**本工作区是独立产线**（2026-10-09 用户裁定）：只管本目录，与其它 VOX 版本线无关，不要跨线借鉴或同步。

## V3.42（2026-10-09 全量审查收口）
- **工具同源改项目级隔离**：`skill_sync` 的对账目标从机器级共享包改成 `<repo>/.skill/`（详见「改动后的可复现性」）。
  这是本轮唯一的**阻断级**修复——不改，`pipeline ready` 不盖章、`render_all` 拒渲，全链跑不动。
- **新增 `text_legibility_check.py` 成品字高门**，接进 `render_all` 渲前链（`produce --skip-render` 复检表同步）。
  盘上字大 ≠ 屏上字大：渲染器把文字卡 PNG **重采样到 `base_width×图层scale`** 再乘相机 scale。
  V3.41 之前**没有一道门量过字号**（preflight 数图层、layout 量出画、clutter 量拥挤、aesthetic 打分，都不看字）。
  判据（阈值只在该文件顶部定义一次）：屏上墨高/盘上墨高 ≥0.70 · 屏上墨高 ≥20px 硬线 · <44px 亮灯 · 底衬覆盖率 ≥0.50 才算有底衬。
  **收口方式是拆卡/砍词/换底衬，不是缩字号**（缩字号只会把「看不清」换成「看不见」）。
- **字卡一律自带底衬**：`make_text_cards.make_card` 出的是**纯透明底 + 米色字**（`make_text_cards.py:43`），
  裸字压在场景上时对比度随底图变、不可控。设计期就给字卡配底衬板（墨/深板 + 反白字）。
- **`motion_similarity_check` 不再静默放行**（V3.42）：账本不存在 / 前一部抽不出缓动数据 → **FAIL**（参照坏了≠没有参照）；
  只有"账本在且确实没有更小编号条目"才当第一部放行，并明写「实测比较 0 次（不是通过）」。从零开始显式 `--allow-no-prev`。
- **门数不写死在文档里**：以 `render_all` 启动时自报那行「渲前门 N 道: …」为准。写死过 5、8、13、15，每次都过期。
- **动效能力"有但没用"是画面发死的主因（§68 口径：无代码执法的规范＝没有规范，故此条标注为设计期硬前置）**：
  渲染器实测支持 `ease-in/out/in-out/out-expo/out-back/spring` · 多平面视差 `parallax` + `camera_motion` ·
  `slam_squash`/`pop_spring`/`fly_blur`/`motion_blur` · `scale_x/scale_y` 非等比挤压 · `seq_dir` 数字滚动 ·
  `motes` 三层纵深 · `ghost` 残影。但 V3.27 复盘实测 p14/p15/p16 里 **`seq_` 滚动 0 次、`motes` 纵深 0 次、
  `ease-spring`/`ease-out-expo` 0 次、p16 视差 0 场**——能力一直在，是建场时没用。
  **KICKOFF/build_scenes 阶段必须逐场点名本场用哪几项**（每片至少覆盖：1 个非默认缓动、1 处视差或相机运动、
  1 处挤压/弹跳/拖影、≥1 处数字滚动或残影）。`motion_similarity_check` 只管"别和上一部撞"，
  **不管"本片用了多少种"**——这两件事不要混。本轮未给"使用率下限"装硬门（会造假阳性），
  是待办，不是已实现。

## 权威源顺序（冲突时按此判）
1. `scripts/*.py` 代码 — 唯一事实源（门禁实际执法值、阈值、rc 语义）
2. `SKILL.md` — 当前版规范 + 八阶段流程
3. `README.md` — 入口示例（版本号随 SKILL 一起动；逐条机制块只详列到 V3.28，V3.29 之后是摘要）
4. `references/production-playbook.md` §1–§82 — 踩坑实录与判据来历，历史块不作为现值
- 判据：凡是只写在文档里、没有任何代码校验的规范 = 没有规范（§68）。引用它前先 grep 调用点。

## 环境（本机实测 rc=0，2026-10-09）
- Python 一律 `py -3.14`。**勿用 `python` / `python3`**（WindowsApps 桩，exit 49）。
- **本机壳是 PowerShell，不是 bash**（2026-10-09 实测：`export` 报「术语不会被识别」，`$?` 返回 `True/False` 不是数字）。
  - 设 UTF-8：PowerShell 用 `$env:PYTHONIOENCODING="utf-8"`；bash 才用 `export PYTHONIOENCODING=utf-8`。
  - 子进程环境已由 `env_paths.CHILD_ENV` 统一，但**你的 shell 里跑脚本还是要自己设**，否则 stderr 仍会 GBK 崩。
- ffmpeg/ffprobe 只经 `scripts/env_paths.py` 解析，时长只经 `scripts/audio_duration.py`。
  **禁止按名字信任 PATH 上任何 ffmpeg 副本、禁止纯 py 帧扫描兜底**：无 mp3 解码的构建会把时长测成一半，整条时间轴静默错位（§时长可信红线）。
- 开工自检：`py -3.14 scripts/preflight_env.py`（E1–E7）；同源检查：`py -3.14 scripts/skill_sync.py check`。

## 退出码纪律（本仓反复翻车处）
- **验 rc 不许接管道**，然后读日志不读完成通知：
  - PowerShell（本机）：`py -3.14 x.py *> qa\x.log; "rc=$LASTEXITCODE" | Add-Content qa\x.log`
  - bash：`py -3.14 x.py > qa/x.log 2>&1; echo "rc=$?" >> qa/x.log`
  - **PowerShell 里 `$?` 是 `True/False`，不是退出码**——照 bash 写法抄过来会永远读到「True」，等于没验 rc。
- 非 0 即中止是编排器默认（`pipeline.run(allow=(0,))`）；只有 `detect_genre` 的 rc=2（低置信）与 `skill_sync` 的 rc=2（无镜像可比）按提示放行。
- **一条门的"通过"必须报出它查了多少次**：`PASS（0 次）`不是通过，是没跑（playbook §81）。空输入必须 FAIL。
- 单跑被拦的门修完后，必须补跑该门之后的全部门（或重跑 `produce`）——否则 `verify_ledgers` 一类被跳过（playbook §79）。
- **跨片账本按仓库根确定性解析，不随 CWD 变**（2026-09-29 修）：`metaphor_ledger`/`palette_oklch` 旧版按 `Path.cwd()` 上溯找账本，
  在别的目录敲 `pipeline ready` 就是拿空账本比对 → 假 PASS。A/B 实测：旧版错 cwd rc=0、新版同一命令 rc=1（真撞车）。

## 花钱前的两道章（硬机制，不是提醒）
- `pipeline tts` 只认 `qa/ready-tts.json`；`gen_assets` 只认 `qa/ready-assets.json`（`gen_assets.py:299` 调用）。缺章直接拒绝。
- 章输入哈希覆盖 `KICKOFF.md` + `palette.json` + `chunks.json` + `qa/concepts.txt`（assets 另加 `sut.json` + 全部 `jobs*.json`）。
  **盖章后改这些文件＝章作废**；想改就重跑 `pipeline ready`，不要手删章。（`concepts.txt` 是 2026-09-29 补进去的：
  `ready` 拿它喂 `metaphor_ledger`，但它不在章输入里时，盖章后删掉撞车概念的行就能一次编辑绕开那道花钱前的门。）
- `pipeline setup` 对**非法 `--style`** 与**指向不存在文件的 `--copy`** 直接 FAIL 并列出可用风格名。
  混搭不是 `--style A/B`（那不是合法键），而是先 `--style 主` 建 palette，再 `py -3.14 scripts/style_presets.py blend 主 副`。
- KICKOFF **B 表第 8 列（>6s 的景别切点）现在会被 `preflight_v6` 逐场对账**：声明了切点而相机只 2 段 = 拒渲（判据 `2+N`，实测与 `split_beats` 产出一致）。
  真要做就写 `qa/beats.json` 再跑 `split_beats`；确要一镜到底就在 KICKOFF 写 `cuts_waived: <≥20 字理由>`。
- `motion_similarity_check` **不再因换风格档而放行**：跨片缓动余弦 >0.97 即拒渲，差异声明走 KICKOFF `A2c`（标题与正文分两行也算）。
- 跨片账本 `palettes.json` / `metaphors.json` / `film_digest.json` 是防撞门的**唯一参照**（历史 production 目录已清）。
  `pipeline ready --stage assets` 需要 `productionN/qa/concepts.txt`（一行一个概念，零概念判 FAIL）。

## 长度与口径（用户裁定 V3.21，高于本文其余一切长度规定）
不限字数、不限时长、不砍用户文案、不压缩重构——阶段①只做分段与标点。语速只有 **1.1 / 1.15** 两档，且不用来凑时长。
不为讨好检查器改口播措辞：ASR 专名转写差异用 `qa/asr_alias.json` 声明别名（规范名须拉丁 token）；同音死区先做只加标点的最小干预，三滚结果相同就不要再滚，去查测量。
`aesthetic_check` 分数**不是尺子**（playbook §69）：报告照出，不得据此调坐标；要改从"这片发生在什么地方"改，验收交回用户眼睛并排看。

## 改动后的可复现性
- 改过场景或资产后**不要相信"复用旧帧"**：`py -3.14 scripts/render_all.py <proj> --force-all --jobs 3` 后重出 MP4。
  交付物 mtime 必须晚于最后一次内容修改。
- 渲染期手修（空台/出画/补层/label）必须镜像进 `build_scenes.py` 的 `_postfix(i,d)`，并跑 `py -3.14 scripts/regen_check.py <proj>` 断言（该门未接线，靠人跑）。
- 改过任何门禁脚本或 `references/*.md`，必须 `py -3.14 scripts/skill_sync.py push`。
  **V3.42 起同步目标是项目级镜像 `<repo>/.skill/`，不再是 `~/.agents/skills/produce-collage-video`**。
  原因（2026-10-09 实测）：机器级共享包会被**其它版本线**整体覆盖——本仓查到那份是 V21.2，带
  `plan_check.py`/`text_legibility_check.py` 等本仓没有的脚本，于是 `check` 常年红 46 处、
  `pipeline ready` 不盖章、`render_all` 拒渲，**全链被别人的包卡死**；按旧口径 `push` 又会砸掉对方的包。
  本项目自包含（`produce`/`render_all` 跑的都是 `HERE/` 那份），对账只对**本项目自己的镜像**。
  确要动机器级共享包：显式 `--global`，且自担跨线污染风险。rc=2 = 无镜像可比（**不是通过**）。
- 零调用点的既有能力（**实测 10 个**，编排器不会自动跑，必须手动执行）：
  `animatic.py` 预览门 · `polycheck_v66.py` 成片级复核 · `preflight_env.py` 开工自检 ·
  `palette_ledger.py check` 跨片配色 · `regen_check.py` 场景重生成对账 · `validate_sequence.py` ·
  `validate_shot_plan.py`（还需 `shot-plan.json`，`ready` 只 WARN）· `detect_style.py` ·
  `gen_sut_cards.py` · `make_contact_sheet*.py`。
  **新增门要接进 `render_all` 渲前链或 `pipeline ready` 才算存在**；没接线的门 = 没有门。

## 需要用户点头才做
- 删 `productionN/frames_s*`（p26 实测单场 347–928 MB，一部片约 4–6 GB）或任何历史片目录；重打便携包 zip；改用户文案的措辞或口径；
  替换/删除已交付的 `output/*.mp4`（改出 v2 时与 v1 并排、中性交付，不替用户选版）。
- `.env` 含私人 StepFun key：不外传、不上传公开仓库、不打印值。
