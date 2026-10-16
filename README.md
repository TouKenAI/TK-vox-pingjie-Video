# VOX 拼贴短视频工作流便捷包 · V3.41

**copy 即用**：把整个文件夹复制到任何电脑 / 新工作区 / 另一个 Agent 软件，即可跑通"文案 → 配音 → 生图 → 剪纸 → 场景动效 → 渲染 → 成片 → 质检"全流程。**自包含**（含渲染器、创意契约、全部工具），不依赖外部技能目录。

## 目录结构
```
VOX便携包/
├── README.md            ← 本说明
├── .env.example         ← StepFun API 配置模板（复制为 .env 并填入自己的 key）
├── SKILL.md             ← 工作流总规范(V3.41, 八阶段管线 + 版本记录)
├── ADAPTATION.md        ← 本机(win32)适配要点
├── AGENTS.md            ← 操作契约(命令口径/两道章/rc 纪律)——与本文冲突时以它和 scripts/ 代码为准
├── ip_assets/           ← IP 讲书人素材(本人照片+设定板+三姿态剪纸), ip_registry 指向此处
├── references/          ← 生产手册§36-81/开工模板 kickoff-template.md/类型档案/风格导演/风格提示词库/三份创意契约 等
└── scripts/             ← 全部可执行脚本(自包含, 含渲染器 + animatic/aesthetic 新工具) + _templates/confetti
```

## 环境要求（新电脑首次）
1. **Python 3.12+**（本机验证 3.14）。Windows 建议 `py -3.14`（`python` 常是坏别名）。
2. **完整版 ffmpeg/ffprobe**（必须，含 mp3 解码）：`winget install Gyan.FFmpeg`。脚本经 `scripts/env_paths.py` 自动解析+校验，无需手配。
3. **Pillow + numpy**：`py -3.14 -m pip install pillow numpy`
4. **跑脚本前设 UTF-8**（多数脚本已内置 stdout 保护，仍建议）：PowerShell `$env:PYTHONIOENCODING="utf-8"`；bash `export PYTHONIOENCODING=utf-8`。**验 rc 也要按壳来**：PowerShell 读 `$LASTEXITCODE`，`$?` 是 True/False 不是退出码。
5. **配置密钥**：`cp .env.example .env`，然后填入自己的 `STEPFUN_API_KEY`（模板里 base/模型/端点已配好 Step Plan 订阅通道）。

## 一键流程（V3.42）
```bash
# ① 建项目+类型+结构档+风格(可 主/副 混搭)
py scripts/pipeline.py setup --root <工作区> --name productionN --copy 文案.txt --energy 标准 --style 等距2.5D/白板手绘
#   → 人做(V3.26 硬前置): 填 `productionN/KICKOFF.md`(**V3.27 起 setup 自动把模板复制进项目**)——题材三问→世界/风格三特征/逐场动作/五拍/F 对上一部查差异
#   → 人做: 联网核实事实 → 写 chunks.json + palette.json + BRIEF → 交用户审稿(硬门)
# ① 盖章(V3.27·第一次花钱前): 一次跑完 KICKOFF 完成度 + palette_oklch + metaphor_ledger + novelty_meter
py scripts/pipeline.py ready productionN --stage tts
# ② 审稿通过后: TTS + 词级卡点 + ASR        （无 qa/ready-tts.json 直接拒绝合成）
py scripts/pipeline.py tts productionN
#   → 人做: 写 sut.json(逐句演语义) → build_scenes(motion/pf/slam_squash/fly_blur/parallax, 每场≥7元素)
# ③ 盖章(V3.27·第二次花钱前): 再加 semantic_check 语义动效硬门；**无章 gen_assets 拒绝生图**
py scripts/pipeline.py ready productionN --stage assets
py scripts/split_beats.py productionN            # 长镜头拆子镜头
py scripts/animatic.py productionN --step 8 --scale 0.35   # V3.12 预览门: 低清快渲, 目检 filmstrip/preview 再全渲
py scripts/render_all.py productionN --jobs 2 --overwrite  # 三道门禁+并行渲染
# ⑦⑧ 一键: 硬切转场+拼接+混音+编码+交付门禁+拥挤度+审美QC
EQ_SAT=1.08 py scripts/produce.py productionN --at 9,12,18 --dipblack-at 12 --jobs 2   # 高饱和风格传1.08, 冷色省略=默认1.14
```

## 核心机制（V3.1–V3.42 固化，详见 SKILL.md 版本块 + playbook §36–§82）
- **★ V3.42（2026-10-09 全量审查收口，三条都是"跑不动/看不见"级别的）**：① **工具同源改项目级隔离**——
  `skill_sync` 对账目标从机器级共享包 `~/.agents/skills/produce-collage-video` 改成**本项目镜像 `<repo>/.skill/`**。
  实测那份共享包已被**其它版本线**覆盖成 V21.2（带 `plan_check.py`/`text_legibility_check.py` 等本仓没有的脚本），
  于是 `check` 常年红 46 处 → `pipeline ready` 不盖章 → `render_all` 拒渲，**全链被别人的包卡死**；而按旧口径 `push`
  又会砸掉对方的包。本项目自包含，改完脚本 `push` 即可（rc=2=无镜像可比，**不是通过**）。② **新增 `text_legibility_check.py`
  成品字高门**并接进 `render_all` 渲前链——渲染器会把文字卡 PNG **重采样到 `base_width×图层scale`** 再乘相机 scale，
  **盘上字大≠屏上字大**；此前数图层/量出画/量拥挤/打分，**没有一道门量过字号**。判据：屏上墨高/盘上墨高 ≥0.70、
  屏上墨高 ≥20px 硬线（<44px 亮灯）、底衬覆盖率 ≥0.50 才算有底衬。**收口靠拆卡/砍词/换底衬，不许缩字号**。
  ③ **`motion_similarity_check` 不再静默放行**——账本缺失/参照抽不出缓动数据一律 FAIL（参照坏了≠没有参照），
  从零开始显式 `--allow-no-prev`。另：门数不再写死在文档里，以 `render_all` 启动自报「渲前门 N 道」为准。
- **★ V3.29–V3.41（2026-09-26→29，p20–p26 复盘 + 第三遍审查；细节见 playbook §68–§82）**：① 生图**风格硬门**——`palette.json` 声明了 `style_primary` 却不传 `--style` → `gen_assets` 拒生图（p20 四张背景全被画成写实 iPhone 的根治）；② **`card_text_check`**（V3.39）——每张文字卡必须在 `qa/card_manifest.json` 有条目 + 面板卡腐蚀 13px 后内部确有墨，p25「30/55 张卡是坏的而全部门禁绿灯」从此拦在渲前；③ **`name_ledger`**（§66，V3.40 起「有名单却检查 0 次」直接 FAIL）——口播点名那几秒屏上必须是那个名字；④ **增量渲染**（V3.34 `scene_fingerprint`）——场景 JSON+全部引用资产+渲染器联合指纹，命中即跳场（p23 863s→2s；V3.40 缓存加头尾 4KB 内容探针，防"同尺寸同 mtime"投毒）；⑤ **`skill_sync`**——仓库 `scripts/`+`references/` 与已安装技能包漂移即拒渲拒盖章（`push` 一行同步）；⑥ **`motion_similarity_check`**（V3.31 立 / V3.41 扩到跨风格）——同风格档且余弦>0.92 或主导缓动相同 → 拒渲；**换了风格档但余弦>0.97 同样拒渲**（"风格雷同"量出来在**运动**不在颜色，换皮不等于换骨）；⑦ **`bg_plan_check`**（V3.34）——背景每场一个空间，复用率<0.75 拒渲；⑧ **`pipeline ready` 的章输入含 `jobs*.json`**（V3.36，防盖章后改清单绕门）。**V3.28 及更早的版本块留在下面作历史。** V3.41 的四件事（六处假 PASS 堵住 / animatic 奇偶数把预览门杀了 / 切点声明与相机段数对账成硬门 / `verify_ledgers` 从 produce 末尾前移）见 playbook §82。
- **★ V3.28 p17 首跑：预览门才是构图问题的拦截器（playbook §64）**：`animatic` 低清跳帧看片抓出 5 个缺陷——
  图腾只占 16% 宽(自己 KICKOFF 的 D1 写的是 ≥40%)、`seq(hold=True)` 三层同 y 叠成糊、竖白线读起来像坏帧、
  空心矩形演不出"不用下载"这种 absence、底部装饰带被相机推近裁出画外。**没有一条能靠"元素数≥7/对比度≥4.5"逼出来，
  全是摆放问题。** 两条坐标系教训：相机推到 `bg_end` 时可见纵向只剩 `720±720/s`(全仓 142 条 `wave_bands` 有 68 条在裁剪外)，
  **抽图也要按成片取景框判**(`cover()` scale 1.12 只取源图中央 686×914)。新增 `bg_role: "room"`(旧契约只有"空中心"和"细线稿"，
  与 §61"有光有空间有前后层"直接对撞)、`make_countup --decimals`(口播第一句就是"1.02 万亿")、
  `scripts/narration_layout.py`(LEAD/GAP 单一事实源；`polycheck` 的画音对齐此前**漏算段起点**，对完全同步的片子误报 51/55)。
  帧预算改由项目内 `scene_timing.py` 照混音器排布反推(+0.9s "停住"余量)——旧的 `ceil(dur·30·1.03)` 让 p17 十场、p16 十九场**全部**短于自己的旁白，切掉的是 TTS 尾部静音。
- **★ V3.27 编排补全 + 8 风格动画语法（playbook §62/§63）**：① `pipeline ready --stage tts|assets` 把**从没被调用过**的四道门（KICKOFF 完成度 / `palette_oklch` / `metaphor_ledger` / `novelty_meter`，assets 阶段再加 `semantic_check`）一次跑完并盖章，`pipeline tts` 与 `gen_assets` **只认章**，输入一改即作废——阶段③④⑤ 此前只以 print 提示"下一步·人做"存在。② `pipeline setup` 自动把开工模板复制进新项目。③ 四个假 PASS 边界已堵（`bg_luma_check`/`polycheck_v66` 空目录返回 0、`asr_final_check` 路径重拼、`palette_oklch` 裸 traceback）。④ **每个风格各一份"动画语法"**（`references/style-presets.md §动画语法`）：运动质感/主导缓动/禁用项/视差开关/`jitter.hold`/相机逐风格列明——过去 8 个风格共用 1 份剪纸专属契约。**实测结论：p14/p15/p16 里 `seq_` 数字滚动 0 次、`motes` 纵深 0 次、`ease-spring`/`ease-out-expo` 0 次、p16 视差 0 场——能力一直在，是没用。**
- **★ V3.26 创作层开工模板（playbook §61）**：新建项目后复制 `references/kickoff-template.md` 为 `productionN/KICKOFF.md`，**不填完不进生图**。它管"画什么、怎么动"，不管检测：题材三问（主角物 / 物理动作 / 情绪温度）→ **世界必须是"有光、有空间、有前后层的场面"，禁止"一张纸上画几笔"** → 逐场填**动作七选一**（拼装/撕开/滑动/砸下/折叠/散开/沉落，写不出动作=静止 PPT）+ 哪个词被演出来 + 视差 + 相机推拉 + >6s 景别切点 → 每场五拍（亮相→新东西→重的一下→后果→停住但纸还在动）→ **F 差异表对上一部逐项查**（世界/风格三特征/主色/骨架/核心图腾/主导动作分布，六项最多 1 项相同且须用户确认）防千篇一律。**判定：门禁与元素数量守的是下限；上限在模型出的那张图、设计期的摆放、和有没有人当观众看过一遍。**
- **语义动效铁律(§36)**：每场主导动作演出台词动词（涨=升/降=沉/塞=fly/缠=orbit/砸=drop_in）；金句三拍 chaos→light→一击；图层≥7/场、countup≥3、motes 三层纵深、drift≥4、spring≥3。
- **V3.12 动画+视觉升级(§47, 全向后兼容·旧场景逐字节不变)**：①多平面视差 `scene(parallax=(bg_depth,fg_depth),cam_pan=(dx,dy))` 相机平移出 2.5D 纵深；②动效库 `slam_squash`(落地挤压回弹)/`pop_spring`(弹跳过冲)/`fly_blur`(运动模糊飞入)，渲染器新字段 `scale_x/scale_y`、`motion_blur`；③`animatic.py` 预览门(渲前低清跳帧抓错)；④`aesthetic_check.py` 审美QC(构图/主体/留白/色彩/对齐 0–100 报告，p8 基线 73.9)。
- **风格提示词库(§43-44, `style_presets.py`)**：6 主风格(剪纸/水墨/白板/等距2.5D/漫画网点/浮世绘)+1慎(报纸)+1贯穿(动态字体)，每套 proven 锚点+OKLCH配色+抠图策略+动效套件+去AI感+反差池。**混搭**：背景 `--style 主`、前景道具 `--style 副`。
- **OKLCH 配色门禁(`palette_oklch.py`)**：片内可读性 + 跨片有彩色撞色检测。
- **元素下限(`preflight_v6.py`)**：每场 <7 图层直接 block 渲染（V3.12 由 6 提到 7，锁 p8 密度地板）。
- **拥挤度(`clutter_check.py`)**：像素级边缘/铺满，相对本片中位数判过载/偏空。
- **结构多样(`structure_plan.py`)**：快评/标准/深度档 + 近片场数趋同预警。
- **一键编排(`produce.py`/`pipeline.py`)**：机械步自动化，人只做核实/创意/审稿。编码带 `-start_number 1`；高饱和风格(漫画/波普)`EQ_SAT=1.08`（防 qa ⑤ 回抽误 FAIL + 过艳）。
- **质量基线(§46)**：p8 为地板，后续每条内容/质量/视觉不得低于 p8。
- **V3.16 机制化门禁**：道具 prompt 缺"纯洋红满幅/无投影/光照契约"由 `gen_assets` 自动补全；红主体抠图走 `cutout_key --hsv`；`gen_sut_cards` 不再覆盖人工语义 SUT；混音只复用非空派生音频；`produce --skip-render` 用渲染戳校验帧↔JSON 一致；`asr_final_check` 区分数字写法差异与真错读。中断恢复见 SKILL「中断恢复 SOP」。
- **V3.17（p12 复盘）**：`--hsv` 转正为暖色/红系道具默认路径；SUT 帧号统一由 `pf(phrase_timing)` 生成（p12 polycheck align 零告警、审美 83.3 频道新高）；改完工具必须跑一次真实 CLI（等价单测会漏 NameError）。
- **V3.18（手动教训机制化）**：`bg_luma_check.py` 背景亮度硬门前移到 render_all preflight 第一道（>235 自动降亮 0.85、幂等复检）；整片 ASR `asr_final_check` 收进 `produce.py` 收尾硬门，FAIL 不交付——p10"两个配音"式缺陷流程上不可能再漏检。
- **V3.21 长度规范废除（用户裁定 2026-09-20）**：**不限字数、不限时长，以用户给的文案为准，不砍内容**；阶段① 只做分段与标点，不做压缩重构。`check_script` 默认不套字数上下限/信息点封顶（genre 只管 CTA 措辞与广告法），改按实测语速打印**预计旁白/成片时长**。保留 R4 单句 ≤45 字与 R6 音效 ≤20（与代码执法值一致）；语速仍只 1.1 / 1.15 两档，且**不再用来凑时长**。
- **V3.22 全量审查修复（2026-09-20）**：花钱前硬门曾因 `pipeline.run()` 放过 rc=1 而形同虚设（文案没过也照计费）；`first_frame_check` 建好了却从未被任何编排器调用；`produce --skip-render` 绕过全渲前门禁；`render_all` 找不到门禁文件就**静默少跑一道**。另把 `polycheck` 运动密度上限从绝对 1.2 层/s 改成本片相对中位数（旧阈值把频道最好的 p14 判 8/11 场"过载"、把最差的 p13 判得比 p10 干净——量的是场景长短不是画面拥挤度）。六处缺输入即吐 traceback、空目录假 PASS、模板在技能目录写脏文件，一并修。详见 playbook §57。
- **V3.20（p14 复盘）**：`claim_check.py` 文案自洽门（矛盾断言 + 差值复算，挂进花钱前）；`asr_alias.py` 专名转写别名归一（念对不再被误判念错，不许为讨好检查器改口播）；`first_frame_check.py` 开场空台门（舞台元素第 0 帧即在场，只有第一次登场才从 scale 0 砸入）；标注层与文字卡分目录。
- **V3.19（p13 复盘）**：`gen_assets --raw-dir` 路径归一门（防 `productionN/productionN/` 静默嵌套）；`preflight_v6` effects 结构门（图层误入 `E` 不再半路 KeyError）；`clamp_card_in()` 把呼吸门 R1 前移到设计期；门禁 WARN 处置口径与 ASR 专名转写差异口径写死进 SKILL。

## 交付分工
画幅固定 **3:4（1080×1440）**，上下留白供发布端加标题/字幕；字幕/BGM/竖屏由发布端处理；本包交付**画面+旁白+音效**成片（qa_deliver 7 断言 + polycheck + clutter 通过）。

## 创意红线
**同一套标准，不同的创意**——每片按文案重设计隐喻/配色/结构档/风格，至少 1 个新动效组合，杜绝千篇一律。
**V3.26 起这条不再只靠自觉**：由 `productionN/KICKOFF.md` 的 **F 差异表**逐片落实——世界 / 风格三特征 / 主色 / 骨架 / 核心图腾 / 主导动作分布，六项**最多 1 项**与上一部相同且须用户确认；上一部最常用的那个动作，本部 ≤1/3 场。

## 安全提醒
本仓库**不含任何密钥与真人素材**：真实 `.env`（含 `STEPFUN_API_KEY`）、`ip_assets/`（IP 真人照片+姿态剪纸）、`ip_registry.json`（身份注册表）均被 `.gitignore` 排除。首次使用请复制 `.env.example` 为 `.env` 并填入自己的 key。**切勿把填了 key 的 `.env` 提交进仓库或外传。**

## 从 Git 仓库部署（新机 / 新 Agent）
```bash
git clone <本仓库> VOX-Video && cd VOX-Video
# 1) 重建项目级技能镜像（V3.42 起 skill_sync 对账目标，clone 后必须先跑一次）
py -3.14 scripts/skill_sync.py push
# 2) 开工自检（E1–E7：Python/ffmpeg/Pillow/密钥/渲染器）
py -3.14 scripts/preflight_env.py
```
