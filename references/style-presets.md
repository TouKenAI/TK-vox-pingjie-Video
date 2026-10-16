# 风格提示词库 V3.26（7 主风格 + 1 贯穿层 + 反差混搭默认机制）

> 机器可读源：`scripts/style_presets.py`（`list` / `get <风格>` / `suffix <风格>`）。本文是人读版。
> 用法：阶段①按**选题调性选 1 主风格** → 取 `suffix` 拼进 `gen_assets` 的 prompt → 用其 `palette` 建 `palette.json` 跑 `palette_oklch check` → **强制叠加 1 个反差元素**（保新颖/防同质）→ 动效按"动效配套"选。

## 五维选型依据（研究：animiz/accio/huxiu/csdn 2025–2026）
①抖音流量 ②精选契合 ③匹配我们主题+语音 ④视觉动效丰富 ⑤**创意新颖/差异**。关键：高流量常=高同质（扁平/黏土/玻璃拟态已劝退）；精选**奖励差异+真实感+去AI批量感**，故⑤权重压过①。

## 四主风格

### 1. 剪纸拼贴（主力）— 商业/科技/时事
- 锚点：`premium paper-cutout collage, layered torn paper, hard-edge drop shadows, halftone/newsprint texture, slight color misregistration, light upper-left 45°`
- 配色：奶油底 243,236,221 / 墨 43,34,26 / 橙 224,106,32 / 墨绿 58,140,90
- 动效：drop_in / rise / orbit / 撕纸擦除 / 描边揭示
- 去AI感：保留撕边不完美、纸纤维、套印错位
- 反差池：+像素故障 / +霓虹数据流 / +手绘涂鸦批注 / +真实照片贴图

### 2. 国潮水墨 × 信息可视化（新颖王牌）— 人文/历史/本土；科技做古今反差
- 锚点：`Chinese ink-wash (shuimo/sumi-e) meets modern infographic, expressive brush strokes, rice-paper texture, ink bleed and feibai dry-brush, generous negative space (liubai), vermilion seal accent, monochrome + one accent`
- 配色：宣纸 240,235,222 / 墨 28,28,30 / 朱砂 190,45,40 / 黛蓝 40,70,110
- 动效：墨晕线自绘 / 笔触划出 / 印章砸落 / 留白入场
- 去AI感：笔触飞白、浓淡不匀，忌数码平滑
- 反差池：+霓虹数据流(古今) / +等距机械 / +荧光图表 / +故障艺术

### 3. 复古报纸/档案拼贴 — 时事/调查/历史/深度
- 锚点：`vintage newspaper archive collage, aged kraft and tabloid paper, halftone dots, typewriter and clipping layout, red rubber stamp, coffee stains, torn edges, muted sepia + red accent`
- 配色：牛皮 224,210,180 / 墨 40,36,30 / 朱红 170,45,40 / 档案蓝 50,70,110
- 动效：剪报飞入 / 图钉摁下 / 印章砸落 / 翻页 / 高亮划线
- 去AI感：真实做旧、折痕污渍、不规则裁边
- 反差池：+手绘圈点 / +现代UI截图框 / +霓虹关键词 / +老胶片颗粒

### 4. 白板手绘/粉笔 — 科普/原理/流程（获得感最强）
- 锚点：`hand-drawn whiteboard explainer, sketchy marker strokes, doodles, arrows, sticky notes, imperfect hand lines, high contrast, one or two accent colors`
- 配色：白板 248,248,244 / 墨 30,34,40 / 蓝 20,110,190 / 红 220,70,60
- 动效：描边自绘 / 箭头生长 / 贴纸弹入 / 圈点强调
- 去AI感：故意手抖、涂改痕迹、笔迹不均
- 反差池：+真实照片贴图 / +3D小道具 / +剪纸层 / +霓虹高亮

### 5. 等距 2.5D（isometric）— 科技架构/系统/流程/供应链
- 锚点：`isometric illustration, isometric view, no perspective distortion, miniature diorama, detailed miniature, cross-section, clean vector shapes, game asset style, soft ambient lighting`
- 配色：冷浅底 234,238,244 / 墨 28,36,52 / 电光蓝 35,105,215 / 青柠 130,190,60
- 动效：模块 rise 堆叠 / 沿轴推进 / cross-section 剖开 / 数据流沿线跑
- 去AI感：保留微缩景深与手工装配感，忌塑料光滑
- 反差池：+手绘标注 / +剪纸层叠 / +霓虹数据流 / +真实照片贴图

### 6. 漫画网点（pop-art comic）— 时事/冲突/争议/戏剧
- 锚点：`retro pop art comic illustration, Ben-Day halftone dots, bold black outlines, flat primary colors, dynamic action lines, vintage comic panel, high contrast`
- 配色：奶白 250,240,222 / 墨 20,20,22 / 波普红 225,50,45 / 蓝 40,90,200
- 动效：分格砸入 / 速度线 / 对话气泡弹入 / 网点闪动 / 撞色 burst
- 去AI感：网点与套色错位保留印刷味
- 反差池：+水墨笔触(东西撞) / +数据图表 / +真实照片分格 / +故障glitch

### 7. 浮世绘工笔（ukiyo-e/gongbi）— 人文/历史/文化/东方叙事
- 锚点：`ukiyo-e Japanese woodblock print, flat color areas, bold keylines, Hokusai style, mineral pigment colors, subtle washi paper grain, gongbi meticulous detail, elegant composition`
- 配色：和纸 238,232,214 / 墨 32,30,34 / 普鲁士蓝 30,80,150 / 藤紫 150,90,160
- 动效：浪/云平移涌起 / 描边揭示 / 印章落 / 卷轴展开
- 去AI感：木版套色错位与和纸纹理，忌照片写实
- 反差池：+霓虹数据流(古今) / +等距机械 / +现代UI框 / +漫画网点

## 贯穿层 8. 醒目动态字体（叠加在主风格上）
- 做法：PIL 字卡——超大醒目字 + 撞色底衬 + 逐词弹入(typewriter) + shimmer 扫光 + scale 砸入。
- 用途：金句 / CTA / 情绪重音；手写体×粗黑体混排增"人味"。

## 默认机制：反差混搭（新颖性引擎）
每片选主风格后，**必须从其"反差池"取 1 个元素叠加**（古今/新旧/手绘×高精/水墨×霓虹/剪纸×故障），并用 `novelty_meter` 记录、`metaphor_ledger` 防撞。目的：直接对冲"高流量=高同质"，制造精选要的**惊喜感**。

## 动画语法（V3.26 新增·每风格一份，build_scenes 时对着填）

> 为什么要有这一节：`collage-language.md` 是**剪纸专属**契约，但库里有 8 个风格。过去所有片子共用一套运动假设，
> 结果是"风格贴在表面上、运动语法全都一样"。**运动质感才是观众分辨"像不像那个风格"的第一线索。**
> 下表字段全部是渲染器**现有能力**（已逐个核对，见文末能力清单），不需要写新代码。

| 风格 | 运动质感 | 主导缓动 | 该用的运动词汇 | 一眼假（禁用） | 相机·纵深 | 抖动·颗粒 |
|---|---|---|---|---|---|---|
| **剪纸拼贴** | 有停顿的手工感，不是匀速滑行 | `ease-out` 落点 + `slam_squash` 压扁回弹；少用 `ease-in-out` 的均匀呼吸 | `drop_in` / `scatter` / `fly` / `motes` 三层 / `ghost` 残影 | 物体匀速平移到定位；爆点盖住主体；撕边被抠干净（契约明令保留毛边） | **视差必开**（这风格的纵深靠它）；推拉幅度小 | `jitter.hold=3~5` 让纸纹几帧才变一次＝定格味；颗粒 0.05–0.10 |
| **国潮水墨** | 书写式：起笔慢·行笔快·收笔提 | 描边 `ease-in`→`ease-out` 接续；墨晕只走 `opacity` 不走 `scale` | 描边自绘 / `rise` 极缓 / 印章 `slam_squash`（全片唯一允许的重缓动） | 整图数码平滑渐显；笔触等粗等浓（要飞白浓淡）；给水墨加 3D 旋转 | 极缓推，幅度全风格最小；**视差关**（平面卷轴语言） | 抖动关；颗粒低 |
| **复古报纸档案** | 同剪纸但更"重"——剪报是甩上来的 | `ease-out` 短促到位 + 落定小幅 `ease-out-back` 回弹 | `fly` 带旋转 / `drop_in` 图钉摁下 / `band` 铺色带底衬 / 印章砸落 | 卡片对齐网格滑入（那是 MG 不是档案）；纸片无投影无折痕 | 俯视台面感，轻推拉；视差小开 | `jitter.hold=3~5`；颗粒 0.08–0.10 做旧 |
| **白板手绘粉笔** | **必须"正在被画出来"** | 描边近匀速；贴纸用 `pop_spring`（此风格允许过冲） | 描边自绘 / 箭头生长 / 圈点强调 / `pop_spring` 弹入 | **整幅淡入或直接 scale 出现**（最常见的一条，一眼假）；线条等宽无手抖；擦除方向与书写方向相反 | 小幅横移"跟手"；**视差关** | 靠线条自身手抖，图层不抖；颗粒低 |
| **等距 2.5D** | **机械精确，越顺越贵**（唯一以顺滑为卖点的风格） | `ease-in-out` 对称；多模块用 `stagger_decreasing` 等间隔连击 | `rise` 堆叠 / 沿轴推进 / `cross-section` 剖开 / 数据流沿线跑 | 给架构件加 `ease-spring`/`ease-out-back` 弹跳（立刻变卡通）；随机漂浮；任何旋转破坏等距角 | **视差必开**；推拉匀速、幅度中等 | **抖动必关**（抖一下精度就毁）；颗粒 0 |
| **漫画网点** | 有限动画：**静止→突然爆发**，中间过程可以没有 | **不用缓动**：`linear` 硬切到位（impact frame），爆发后立刻 hold | `drop_in` 分格砸入 / `burst` 撞色 / `ghost` 残影拖尾 / rig 的 `shake` 震屏 | 连续平滑位移（那是 MG 不是漫画）；分格内元素各自乱动；速度线方向与运动方向不一致 | 急推（snap zoom）比缓推对；**视差关** | 只在蓄力/震屏时抖，平时不抖；颗粒 0.05（网点已供纹理） |
| **浮世绘工笔** | 平面滑动——浪/云/人是平移的色块，不做透视 | 极缓 `ease-in-out` 长尾；卷轴展开用 `linear` | 平移涌起 / 描边揭示 / 印章落 | 3D 旋转或缩放（木版画没有透视）；弹跳过冲；给平面色块加真实投影 | **只横移不推拉**（画卷横向读）；视差关 | 关；颗粒 0.04–0.06（和纸纹） |
| **动态字体（贯穿层）** | 字就是动作本体；到位要"钉住"，不许飘 | `ease-out` 极短或 `linear`；出现即 hold，退场硬切 | 逐词 `stagger_decreasing` 错帧弹入 / `scale` 砸入 / `band` 撞色底衬 / `seq` 数字滚动 | 淡入淡出；缓慢漂移；**字卡拉宽超过原生 PNG 宽**（糊＋压字幕带） | **字卡层不参与相机推拉**（会被放大到出画） | 关 |

### 三条通用规矩
1. **混搭主/副时，运动质感以主风格为准。** 例：等距2.5D 主 + 手绘批注 副 → 批注线条可以手抖，但整体缓动仍走等距的精确对称。**副风格只借"元素语言"，不借"运动语法"。**
2. **`jitter.hold` 是现成的"定格味"开关**（渲染器 `procedural_frame // hold`）：hold=5 → 纸纹每 5 帧才变一次，就是手翻书/定格动画的顿挫感，**不改帧率、不改文件、成片仍 30fps**。剪纸/报纸/漫画三类默认 hold=3~5；其余风格保持 1。
3. **每片在 KICKOFF 的 A2 里必须写明"本片走哪几条"**，并在 B 表逐场标主导缓动。选了风格却不走它的运动语法 = 风格只贴在表面上。

### 能力核对（V3.26 逐个查过源码，别照旧文档办事）
- 渲染器支持 **7 种缓动**：`linear / ease-in / ease-out / ease-in-out / ease-out-back / ease-out-expo / ease-spring`。
  **`scene-plan.md` 只列了 4 种，是旧的**（已同步修正）。
- 现成运动助手（`build_scenes_template.py`）：`drop_in / rise / climb / fly / scatter / orbit / relay / motes / ghost / band / burst / seq / stagger_decreasing / slam_squash / pop_spring / fly_blur / verb_to_motion`。
  - `seq(...)` = **V8.1.8 数字滚动层**（`make_countup` 产物，id 必须 `seq_` 前缀）；
  - `ghost(src,f_exit,n,decay,lag)` = 出画残影拖尾；`band(y,color)` = 横向色带底衬；`relay(...)` = handoff 交接速记；
  - **`verb_to_motion(verb)` 就是"语义动词→动作"的现成映射**——KICKOFF B 表"演什么动作"那一列应该由它落地，不靠现场想。
  - ⚠ `shake` 只在 **rig（角色绑定）** 上生效，普通图层没这个字段。

### ⚠ 由此修正我自己先前的一个说法
我此前说"p16 特效只剩 1 种、渲染器词汇不够"。查完源码与三部片的场景 JSON，**准确的表述是**：
**能力一直在，是没用。** p14/p15/p16 三部实测——
`seq_` 数字滚动层 **0 次** · `motes` 三层纵深 **0 次** · `ease-spring`/`ease-out-expo` **0 次** · `ghost` 仅 p15 用过 3 次 · `parallax` p16 **0 场**。
所以"画面平、数字不演、没纵深"**不是缺工具，是 18 个助手只用了其中三四个**。这一条比任何新门禁都值钱：**下一部片什么都不用新增，只要把这些现成词汇用起来。**

---

## 管线约束（选风格时牢记）
StepFun 出图 1024²、无 alpha、洋红抠图、3:4 → **忌大渐变/深色主体/画面含文字**（抠图翻车，红心教训）。四套主风格均刻意规避：利落边缘、避键色同族、禁画面文字。每片仍走 `palette_oklch check`（可读性+与近片撞色）。

## 已劝退（不进库）
扁平MG、3D黏土（⑤新颖垫底=同质）；玻璃拟态/弥散光、赛博霓虹（AI批量感 + 抠图翻车）。
