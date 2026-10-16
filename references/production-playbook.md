# 生产手册:协议细节、踩坑实录、参数经验

来源:《精益创业》130s/3900帧成片全过程(2026-08-23)。所有结论均经实测。

## 1. StepFun API 实测协议

### 生图 `POST /step_plan/v1/images/generations`
- 入参 `{model:"step-image-edit-2", prompt, size?, response_format?}`,响应 `data[0].b64_json|url`
- 输出恒为 1024×1024 RGB PNG,**没有 alpha**——透明剪纸必须走抠图
- 提示词服从性:构图/风格服从性高;"纯洋红背景"会画成带纹理渐变的玫红纸面(≈RGB 190±20, 60±25, 110±30),**不要指望纯键色**
- 背景类提示词里写"无人物",否则它会自作主张加人,与前景剪纸打架

### TTS `POST /step_plan/v1/audio/speech`
- **voice 必填**,非法值报 `voice_id_invalid`;已验证:`cixingnansheng`(男,沉稳)、`linjiajiejie`(女)
- 可用 `instruction`(中文语气描述)与 `response_format`(mp3/wav);输出 24kHz 单声道
- 长文案按 ≤120 字分段分别合成,情绪逐段给;ffmpeg concat 前统一转 44.1k stereo
- GET `/audio/voices` 只列**复刻音色**(初始为空),预置音色不在其中
- 文档标注的 `/audio/voices/preview` 在网关上实际 404

### ASR `POST /step_plan/v1/audio/asr/sse`
- 入参是嵌套结构:`{"audio":{"data":"<base64>","input":{"transcription":{model,language,enable_itn},"format":{type,codec,rate,bits,channel}}}}`
- SSE 协议:`transcript.text.delta`(增量 delta)+ `transcript.text.done`(全文 text)
- **以 done 为准**,别把 delta 和 text 拼一起(会整句重复)
- 输入建议先 `ffmpeg -ar 16000 -ac 1 -c:a pcm_s16le` 转 WAV

## 2. 抠图经验(cutout_key.py)

- 键色 = 图像四边 band=12px 环的**中位色**,天然适配"伪洋红纸面"
- 距离度量用 Chebyshev(逐通道差取最大):单阈值带双边缘少,比欧氏好调
- 默认阈值 t0=45/t1=95;**主体含暖橙/暖红色时必须收紧到 --t0 28 --t1 60**,否则橙色系会被半透明化(loop 循环环案例:semi 从 16.5% → 0.24%)
- `--despill` 剔除"键色同族暗红"(R>1.35G ∧ R>1.15B ∧ B≥0.85G):专杀投影残留和彩边,不伤米色纸面和橙色强调色(B≥0.85G 条件保护了橙色)
- 提示词里写"无阴影无投影"能大幅减少返工,但 despill 仍是必备保险
- 每张必看 `_check.png` 棋盘目检:半透明格子纹透出来=阈值错了

## 3. 校验器规则速查(validate_shot_plan.py)

| 规则 | 数值 | 设计 path 时先自查 |
|---|---|---|
| 沿轴运动与轴线对齐 | ≥0.65 | 段内首尾位移向量 vs 轴线向量夹角 |
| 向灭点移动 | 必须缩小 | dist(end,VP) < dist(start,VP)−10 ⇒ scale_end < scale_start |
| 远离灭点移动 | 必须放大 | 反之同理 |
| stationary 位移 | ≤120px | "原地表演"别滑出去 |
| multi_character_scene=true | 三种角色齐备 | primary+secondary+tertiary |
| frames | 全片 1..N 连续无缝 | 先定音轨时长再写计划 |

坑:S02 书本"从深处推近镜头"若写成向 VP 移动+放大直接报错——改成"从 VP 附近出发远离 VP 放大"。

## 4. 渲染器内部行为(render_sequence.py)必知

- 绘制顺序:bg(jitter 会露 fill 底色发丝线,属风格)→ 后方 wave_bands → layers(z 排序)→ effects → **front wave_bands** → camera_motion → grain
- front 波带在一切图层之上:全幅压暗 veil(thickness 盖满)会把下半屏打成黑块,**禁用**;夜感用 grain_opacity 0.16–0.18 + 场景本身暗色
- keyframes 五字段全给;rotation 单位度,可 >360 做连续旋转(多段 linear)
- rig_motion:正弦叠加+shake;**会平移 effects.origin**(灯摇光晕跟着摇=免费福利);不受 procedural_frame_offset 影响
- procedural_frame_offset = 该段之前累计帧数:跨切点纸抖/颗粒相位才连续
- debris 的 sprite_boxes 坐标是相对**已 trim 的素材表文件**
- 同一素材文件可被多个 layer 引用,crop 各取所需(人群墙+跳出橙人=同一张图两层)

## 5. 音画对齐

1. 先合成全部旁白段并 ffprobe 测长
2. 分配每段画面时长 = 旁白长 + 呼吸间隙(0.5–0.8s)+ 头垫(0.8–1.2s)+ 尾垫(3s 定格 CTA)
3. 帧数取 round(dur×30),各段帧数和即全局 frame_count;shot-plan 与场景文件全部由此反推
4. 音轨用 anullsrc 生成同长静音 + concat,**总长误差控制在毫秒级**(实测 130.000113s vs 视频 130.000s)
5. mux 用 `-shortest` 兜底

## 6. QA 判读基准

- 回抽帧 mean_delta:<8/255 是 H.264 噪声级,正常;出现结构差异(>15)查编码参数
- 全局 validate_sequence 的 extreme_jump = 换景硬切是正常现象;正确流程:**逐段校验全 ok + 全局跳变帧逐一对照节拍计划**
- astats:人声 Peak −6~−3dB、RMS −23~−17dB 为健康区间
- 接触表两套:节拍帧(开场/每方法/峰值/结尾)+ 切点前后对照(N,N+4)

## 7. 已知取舍与未做清单(表现力升级方向)

- 转场全是硬切/跳切;可升级遮挡转场(front 波带扫屏)或匹配剪辑
- 无 BGM/音效层;ffmpeg amix 叠 -18dB 底乐与翻纸声可显著提质感
- 角色只有单姿态;剪纸风两帧交换(坐直↔瘫倒)即可有表演感
- 无烧录字幕;ASR done 时间戳可驱动逐句字幕
- 仅横屏;canvas 参数改 1080×1920 可出竖屏版

## 8. 抖动策略(2026-08-23 用户反馈后修订)

**为什么原来要抖**:拼贴语言契约要求"避免 PPT 感"——纸片微颤模拟手工拼贴的"活"。1–4px/帧 + <0.5° 是契约上限。

**为什么全开是错的**:所有图层同频抖动 = 观众读成"画面在震",与真实运动抢注意力;还白白推高 H.264 码率(每帧全屏变化)。实测用户直接差评。

**新默认(已写入 SKILL.md)**:
- `background.jitter = [0,0]`(背景绝对静止)
- 静态道具/文字卡 jitter 全 0
- 仅"正在表演动作的主体"给 `{x:1,y:1,rotation:0.15,hold:5}`
- grain_opacity 常规 0.05、夜戏 0.10(颗粒也闪,一并降)
- rig 振幅减半(船 bob 4→2px,灯摆 0.8°→0.4°)
原则:**抖动是表演的一部分,不是贴片纹理**。只有动作发生时才允许动。

## 9. 转场插入模式(替代硬切)

1. 相邻两段各取边界帧:段 A 末帧、段 B 首帧
2. `make_transitions.py lastA.png firstB.png --out-dir frames_tNN --mode wipeleft|wipeup|dipblack --count 15`
3. 拼接顺序:…frames_A, frames_tNN, frames_B…;全局帧数 = Σ段帧 + 6×15
4. **音轨同步**:对应切点的旁白静音间隙 +0.5s(转场吃掉的是间隙,不是台词时间)
5. 收益:换景不再产生 extreme_jump,全局校验更干净;撕缝深色接缝线自带纸感
选型:S01→S02 wipeleft;同环境跳切改 wipe 消突兀;情绪换景(S05→S06、S06→S07)用 dipblack。

## 10. 角色双姿态表演

- 提示词模板:与第一姿态**完全相同的角色描述**(服装/视角/画风),只改姿态短语("挺直腰板打字,表情专注有希望" vs "垂头丧气瘫坐")
- 抠图流程相同;两姿态尺寸不同没关系,anchor 对齐臀部/座椅接触点
- 场景内两层叠放同位置,opacity 交叉淡化 8–10 帧;换姿态帧必须踩台词重音(如"没人用"落点、"每天50次更新"转折点)

## 11. 冷开场 3 秒 与 强调色脉冲

- 冷开场:文案里最狠的数字/短语做成大字卡,f2 以 scale1.5→1.0 三帧砸下 + burst,旁白未进先给冲突;f45–60 斜向滑出让位正片标题
- 脉冲:每张关键文字卡"落地帧"配 radial-burst(ray_count 9–11,max_ray_length 90–140,origin 在卡片下沿);色彩语义全片一致:橙=行动/答案,蓝=问题/困境

## 12. 竖屏 1080×1440 布局规则

- 中轴 x=540;文字卡 base_width ≤880
- 信息栈:横幅 y≈190 / 副行 y≈290 / 表演区 y550–1000 / 底缘纸带 y1380–1395
- 方形背景(1024²)经 cover 自动裁竖幅,无需重生成;但左右信息密集的场景要检查裁切后主体是否出框
- 人物 anchor 用脚底/座椅接触点(.88–.92),y 放 950–1180

## 13. 音效套件合成(ffmpeg,零素材)

```bash
# swish(翻纸/转场):粉噪+带通+短包络
ffmpeg -f lavfi -i "anoisesrc=color=pink:d=0.35:a=0.8" -af "highpass=f=1200,lowpass=f=6000,afade=t=in:d=0.05,afade=t=out:st=0.15:d=0.2,volume=-12dB" sfx_swish.wav
# thud(砸落):55Hz 正弦衰减
ffmpeg -f lavfi -i "sine=f=55:d=0.4" -af "afade=t=out:st=0.05:d=0.35,volume=-8dB" sfx_thud.wav
# pop(跳出):上滑啁啾
ffmpeg -f lavfi -i "aevalsrc=sin(2*PI*(600+2400*t)*t):d=0.12" -af "volume=-14dB" sfx_pop.wav
# chime(CTA):双音叠
ffmpeg -f lavfi -i "sine=f=660:d=0.7" -f lavfi -i "sine=f=990:d=0.7" -filter_complex "[0][1]amix,volume=-16dB" sfx_chime.wav
# crackle(迸裂):棕噪三连短爆
ffmpeg -f lavfi -i "anoisesrc=color=brown:d=0.5:a=0.9" -af "lowpass=f=3000,afade=t=out:st=0.08:d=0.42,volume=-10dB" sfx_crackle.wav
# flame(点火):低通噪声涨落
ffmpeg -f lavfi -i "anoisesrc=color=pink:d=1.6:a=0.7" -af "lowpass=f=900,afade=t=in:d=0.4,afade=t=out:st=0.8:d=0.8,volume=-10dB" sfx_flame.wav
```
定位:`adelay=<ms>|<ms>` 逐个挂到时间点(毫秒=帧号/30×1000),最后与旁白轨 amix;单个音效电平 −8~−16dB,总轨 Peak 控制在 −3dB 内。

## 14. 同类项目借鉴清单(GitHub,2026-08-23 检索)

| 项目 | 星 | 可借鉴 |
|---|---|---|
| Anil-matcha/vox-ai-motion-graphics-generator | 169 | 开工前两道人工确认门(节拍表+风格样张);四角色分工叙事 |
| majiabin2020/paper-cutout-layered-animation-skill | 20 | 强制分层清单;透明 PNG 无脏边标准;旁白音色调色板(多性别/年龄/情绪);运动密度 QA 门 |
| cameronha/cutout-animator | – | Remotion 渲染路线(宿主支持 React 时可作替代后端) |
| quzhupeng/paper-layered-animation | – | "锁定旁白→分层资产→渲染"顺序与我们一致,可交叉验证 |

我们的差异化护城河:确定性 Pillow 渲染(无浏览器/Node 依赖)、镜头几何校验关卡、"每帧都是 PNG"的可回抽 QA 契约。

## 15. 预检修订(2026-08-23 第二次评审,四个坑)

1. **shot-plan 与转场的边界**:校验器要求 shots 连续覆盖 1..frame_count。约定:**frame_count 只含正片帧,转场帧不计入计划**,由 splice v2(支持 trans 类型目录)在装配层插入;全局帧数 = Σ段帧 + N×15。
2. **amix 归一化陷阱**:多轨混音必须 `amix=inputs=N:normalize=0`,否则总音量被除以输入数,人声会随音效数量变轻。adelay 对立体声要写两份 `adelay=ms|ms`。混完 astats 复查 Peak。
3. **双姿态一致性**:第二姿态禁止全新生成,必须 `image --ref 第一姿态.png` 图生图(提示词"同一角色,现在挺直腰板…"),否则服装/体型漂移等于换人。生成后两张并排棋盘目检。
4. **竖屏首帧预检门**:1080×1440 会裁掉方形背景左右各 ~12.5%。全量渲染前先渲染每场景首帧拼一张预检表目检(月亮/白板等关键道具是否出框),通过后再并行全渲。

SFX 时间定位表模板(转场插入后全局帧号偏移):
```
offset(k 段起点) = Σ(前 k-1 段帧数) + 15×(前面转场数)
事件时刻 ms = round(全局帧号 / 30 × 1000)
```

## 16. 音画同步标准与工作流(2026-08-24,硬性)

1. 分段旁白完成后,逐段过一遍台词,产出**台词-视觉映射表**(进 BRIEF):
   `| 关键词 | 字符位置/总字符 | 视觉事件 | 目标帧(算式见下) |`
2. 帧号换算:`入场帧 = est_frames + round(char_pos ÷ total_chars × narr_frames)`
   (est_frames=场景建立拍;char_pos 取关键词起始字符序号;narr_frames=该段实测帧数)
3. 台词点名的具体名词 → 生成专属剪纸道具(工资条/学士帽/专利证书/保单/企业大楼…),
   禁止拿泛化素材凑数;抽象名词(自由/天花板)用字卡+burst 表达。
4. 道具入场统一"落下/弹出 + 8~12 帧 scale 1.12→1.0 + opacity 0→1",配一个 tick/pop 音效。
5. 验收:接触表必须包含每个映射事件的落地帧,逐一核对时间差 ≤10 帧。

## 17. 生产实录补遗(production2《穷爸爸富爸爸》,2026-08-24)

**转场三连坑(dipblack)**:
1. 中段整帧赋成 dark 向量(H,W,3 广播缺失)→ `np.tile` 修复;
2. t=k/N 会触底:t=1 时末帧==B 首帧,拼接后字节重复;t≈0.4~0.55 的保持带经 uint8
   量化塌平成连续相同黑帧 → 改采样 `t=(k-0.5)/N`(永不触达 0/1)+ smoothstep 缓动
   (`u=x*x*(3-2x)`),sqrt 出黑太陡也会造成 max_delta 超标;
3. 两次 dipblack 的中点黑场互为同哈希 → 黑场基色加 per-seed 微偏色
   (`dark += [seed%5,(seed//5)%5,(seed//7)%3]`,视觉无感,哈希唯一)。

**其他坑**:
- JSON 里混入全角空格(\xa0)导致 json.loads 失败——所有场景 JSON 写完必须
  `json.loads()` 冒烟一次再渲染;
- 新项目初始化时,把上一项目 assets/text 里被引用的通用卡(书名/作者等)一并复制,
  否则渲染中途 FileNotFoundError;
- bash 管道后接 && 会吞掉前一段的退出码(`cmd | tail -1 && next` 在 cmd 失败时照样执行
  next)——关键链路要么 set -o pipefail,要么去掉管道;
- make_transitions.py 的 fromarray "mode" 参数在 Pillow 13 将弃用:仅警告,暂不处理。

**复用登记样例(BRIEF 用)**:bg_office 仅 S01 / bg_dark 仅 S08 / book、coins、chart、lamp、
crowd-walker、figure 为跨片复用(系列人设),其余全部本片新生成。

## 18. 变更记录
- 2026-08-23:初版(七阶段流水线+§1~7)
- 2026-08-23:§8 抖动策略修订(全画面常驻抖动废除)
- 2026-08-24:§15 预检四坑;转场插入模式 v2(manifest);音效层
- 2026-08-24:§16 音画同步硬性标准;§3 素材多样性红线(SKILL.md 阶段③);
  §17 production2 实录;dipblack 工具三修(make_transitions.py 已同步)

## 19. V5 动效库全参数(production4/5 实测关键帧)

统一约定:帧号段内 0 基;所有关键帧五字段齐全;以下给出可直接抄的参数带。

**19.1 隧道推进(背景级)** — camera_motion 而非 background.scale 抖动:
```json
"camera_motion": {"fill":[8,12,24,255], "keyframes":[
  {"frame":0,"x":0,"y":0,"scale":1.15,"rotation":0,"opacity":1},
  {"frame":539,"x":0,"y":0,"scale":1.30,"rotation":0,"opacity":1,"ease":"ease-in-out"}]}
```
S08 收尾用 1.10→1.16 更缓。scale 永远 ≥1,不露 fill。

**19.2 摇头/挣扎振荡** — 4 组来回再归零,组间隔 ≈12 帧:
`0 → +5 → −5 → +4 → −4 → +2 → 0`(度)。适用于拒绝者、日历撕页前兆。

**19.3 环旋入(变形时刻)** — 接管者与被替者同位:
```
{f:200, scale:0.5, rotation:120, opacity:0} → {f:232, scale:1.0, rotation:0, opacity:1, ease:"ease-out"}
之后持续微转 {f:374, rotation:30} 全场不归零
```

**19.4 持续旋转** — 主体中心 anchor[0.5,0.5] 固定 x/y,rotation 线性:
`{f:90,rot:0} → {f:540,rot:360} → {f:599,rot:396}`(600 帧场景转 396°,约 0.66°/帧,再快会晕)。

**19.5 轨道飞行(8 点圆周)** — 中心(cx,cy) 半径 r,θ=k·45°:
```
x=round(cx+r·cosθ), y=round(cy+r·sinθ), rotation=k·45+90(机头切线)
每点间隔 19 帧,飞 2 圈=16 关键帧;rocket scale 恒定 0.5
```
实测 r=260、cx=540、cy=780,rocket base_width=170 效果最佳。

**19.6 坠落回弹(四段式)** — drop_in() 助手:
```
{f,   y:目标−320, scale:0.85, opacity:0}
{f+8, y:目标−40,  scale:1.0,  opacity:1, ease:"ease-in"}
{f+14,y:目标+12,               ease:"ease-out"}   ← 过冲
{f+22,y:目标,                  ease:"ease-out"}   ← 回弹落定
```
MVP 三连(滑板/自行车/汽车)错 60 帧依次落地,各配 6 根 80px burst。

**19.7 柱状升起** — anchor[0.5,1.0](底边锚定):
```
{f,   y:1490(屏下), scale:柱高系数, opacity:0}
{f+26,y:1180,       scale:同,      opacity:1, ease:"ease-out"}
```
三根高度系数 0.55/0.78/1.00,错 44 帧;bar_up base_width=130。

**19.8 飞行折返(单图层 180° 掉头)** — 去 4 关键帧+rotation 0→180 在中点翻转:
去程 ease-in-out → 掉头帧 rotation 直接 180 → 回程 ease-in-out → 落定微沉。
"第二天还回来"的视觉直译,箭 anchor[0.5,0.5]。

**19.9 日历翻页** = 19.2 振荡(±7°)+ scale 0.95 脉冲;翻完归零长静。

**19.10 连发升空** — 3 副本同参数错 34 帧:
```
{f0,   y:1230, opacity:0} → {f0+6, y:1180, opacity:1}
→ {f0+56, y:420, scale:0.62→0.52, ease:"ease-in"} → {f0+74, y:260, opacity:0, ease:"ease-in"}
```

**19.11 乱箭散射+正中靶心(金句三拍)**:
拍1 三箭各 rotation 16/−12/24°,x 240→860 散飞,y 随 rotation 正负偏移,opacity 1→0 渐隐;
拍2 油灯 y 1290→1120 ease-out + flame 音效 + 12 根 240px burst;
拍3 靶心 scale 0.6→1.0 弹入,真箭 anchor[0,0.5](箭尾锚定) x 120→640 ease-in 直刺,**thud 落点=箭到位帧**。

**19.12 双姿态交叉淡化** — 两层同位:
A 层 {f:428,opacity:1}→{f:442,opacity:0,rotation:−0.8};
B 层 {f:428,opacity:0,rotation:−2}→{f:442,opacity:1,rotation:−3.5}。交叉 14 帧,踩台词重音。

**19.13 背包滑移交还** — 道具层 5 关键帧横移:
`肩上静止 → 中点 y−30(抛物线顶)+rotation−14 → 对方肩上落定+rotation−6`,
起终点 y 差模拟"递过去"的弧线;交还瞬间主角 rotation 5→0+scale 0.97→1.02(卸重挺直)。

**19.14 台阶逐级攀登** — 沿对角轴 4 停靠点:
`(250,1160)→(420,980)→(580,800)→(760,620)`,每段 ease-in-out,scale 0.65→0.58 渐小(向灭点)。
每停靠点 = 一个方法标签卡弹入帧,音效 pop 三连。

## 20. 视觉隐喻设计法(V5 核心)

**流程**:读文案 → 提取 5-8 个抽象概念 → 每个概念配"一句话能讲清"的实体隐喻 → 定一个贯穿全片的核心图腾 → 写成映射表进 BRIEF → 才允许生成素材。

**两部片实例**:
| 概念 | 被讨厌的勇气 | 精益创业 |
|---|---|---|
| 核心病灶 | 被审视的眼睛围困 | 隧道里闷头推箱 |
| 核心方法 | 背包交还(课题分离) | 直箭→循环环(不是直线是循环) |
| 心理防御 | 金盾牌龟裂坠落(免死金牌) | — |
| 行动路径 | 逆人流前行/三级台阶 | MVP 滑板→自行车→汽车 |
| 验证 | — | 柱状升起+箭折返(留存) |
| 升华 | 灯笼点金句 | 乱箭→油灯→中靶(黑暗射击不如点灯) |

**铁律**:
1. 隐喻优先级:具象道具 > 人物动作 > 抽象图形。能"递出去/摔碎/点亮"的才是好隐喻
2. 金句场景 = 隐喻的完整三拍演出( chaos → light → 一击必中),不许只放文字卡
3. 每片一个核心图腾首尾呼应(精益:循环环 S02 出现→S04 放大旋转→S06 角落小环回响)

## 21. 零复用与主角一致性(V5 红线)

- **零复用**:production5 的 18 张素材全部新造,与前 4 部片零重叠——用户两次点名"不要复用"后的最终标准。跨片复用仅在用户明示"系列片"时允许
- **主角一致性**:`stepfun_tools.py image --prompt "same character, now bowed..." --ref hero_upright_raw.png`——先文生图基准姿态,再以它为参考图生成第二姿态;同一详细造型描述("young man in mustard yellow jacket and dark navy trousers")贯穿
- **despill 误删红色主体**:production4 脸红女孩,despill 把腮红当洋红残留删成面部黑块。红色族主体(r>g·1.35 且 r>b·1.15 的正是红色)一律无 despill 抠图;半透明边 ratio 20% 但主体完整时,拼贴风格可接受
- **配色版本化**:三本书三套卡色(米橙/米青红/琥珀青冷白)。"千篇一律"一半来自配色惯性

## 22. V5 时间轴规划法(先音后画的精确版)

```
1. TTS 分段生成(每段 ≤250 字,7 段典型) → ffprobe 实测各段秒数
2. 总片长 = lead(1.0) + Σ段长 + Σ段间留白(0.3~2.4) + tail(0.5~2.5) → 取整到 0.1s
3. 场景帧分配:每场景覆盖 1-2 个旁白段,场景起点 = 段起点 −0.2~0.5s(画面先于语音);
   场景帧数 = round((场景终点−起点)×30) − 后续转场 15 帧已由拼接层注入,shot-plan 只写正片帧
4. 旁白定位:adelay=round(start×1000)|同;amix normalize=0;atrim=0:总秒数
5. SFX 锚定:事件秒 = 场景起点 + 场景内关键帧号÷30,从 build_scenes.py 抄表,不手算
```
production5 实测:7 段/136.58s 旁白 → 144.0s 成片,三方对齐误差 0.000s。

## 23. 变更记录(V5 追加)
- 2026-08-23:**V5**。零复用素材红线(替换旧"复用率≤30%");新增 §19 动效库 14 式全参数、
  §20 视觉隐喻设计法、§21 主角一致性(--ref)+despill 红主体禁用+配色版本化、
  §22 adelay 时间轴规划;QA 增 ASR 端到端回抽与帧差基准带 1.0–2.8/255;
  新模板脚本 gen_assets.py / mix_audio3.py;SKILL.md 阶段重排为①-⑧(③隐喻表 ④素材 ⑥渲染器生成器 ⑧adelay音轨)。
  生产实录:production4《被讨厌的勇气》(136s,12 新素材,40 卡)、
  production5《精益创业 V5 重制》(144s,18 新素材,42 卡,11 新动效,57 SFX)。

## 24. V6.1 增量(2026-08-24,两轮圆桌+《从0到1》实测固化)

**素材账本(V6 核心)**:`assets/ledger.jsonl` 每行 {file,sha256,production,prompt_hash,created};生图/抠图/PIL 卡全部入账(gen_assets.py 已内置 register)。
preflight_v6.py 三门禁:①引用图未登记或出生地≠本项目→fail(production6 实测当场抓到文字卡漏登);②每 120 帧滑窗必有 keyframe/effect 事件(实测密度 5.0-10.3/窗);③>600 帧场景主力动效层须 ≥6 关键帧且存在方向反转/scale 换向(防"一直走")。豁免:项目根 reuse_exemptions.json 带 reason。

**矢量接力 handoff 扩展字段**(validate 兼容):motion_vector/exit_speed/subject_momentum/next_enter_rule{angle:continue|counter,tolerance_deg:30}。接力链示例(《从0到1》):跃鱼↑→书升↑→翻页←→人潮←→棋盘↗→掀纸(对冲)→金流→→印章↓(对冲)→灯笼↑。转场按接力向选:wipeup/wipeleft/**wiperight(V6.1 新)**/**wipediag(V6.1 新)**/dipblack。

**断言冷开场帧位**:f0-15 隐喻物件怼脸特写(无字无声)→f16 反差词大字(scale1.5→1.0)→f30-60 旁白进。前 90 帧核心事件进 preflight 关注。

**文字卡四模式**(build_scenes_template.card):bounce 弹入/slide 滑移(slide_dir=接力方向)/flip 翻页(rot22°→0)/emph 两段强调;单一模式占比≤50%。**ghost(src_layer,f_exit)** 出画拖尾 2 层 opacity 递减。

**TTS 分段情绪**(generate_tts_template):chunks.json 加 emotion 字段→hook 压低/book 适中/method 提速/case 叙事/quote 一字一顿/cta 上扬。

**loudnorm 两遍验证版**(mix_audio4,踩坑实录):测量字段是 `input_i/input_tp/input_lra/input_thresh/target_offset` 且冒号前有空格(measured_* 会拿不到);linear 可行条件 LRA≤11 且 (input_tp−input_i)≤13;动态模式对语音+SFX 混合收敛偏松(I≈-13),内置 FINAL_TRIM_DB 确定性校准(production6 用 -1.5dB → I=-14.5/TP=-1.5 达标)。验收命令 ebur128=peak=true。

**两级帧审计**(成片后):硬fail=黑帧Y<16/爆闪>235/白名单外 scene>0.32/音画差>50ms;软报告=ΔY>60/pHash 重复/冻结。白名单=splice 转场区间∪场景效果帧。《从0到1》实测:0 硬 0 软。

**V6 编码命令(锁定)**:ffmpeg -framerate 30 -i frames/frame_%04d.png -i final_mix.wav -c:v libx264 -pix_fmt yuv420p -crf 18 -preset slow -r 30 -fps_mode cfr -movflags +faststart -c:a aac -b:a 192k -ar 44100 -ac 2 -shortest。断言:r=avg=30/1、nb_frames=manifest 总和、pkt_duration 唯一 0.033333。

**production6《从0到1》实录**:156.000s/4680帧/24 图+38 卡全账本/65 图层(8.1/场)/58 SFX/7 转场按接力向/I=-14.5 LUFS/两级审计零缺陷/10 点帧差 1.13-2.32/ASR 全文回抽一致(含 PayPal/eBay/15亿专有名词)。

## 25. 抽帧对比映射修正(2026-08-25,production7 实录)

MP4 内帧号 n 是 **0 基**,splice 后 PNG 命名 frame_NNNN 是 **1 基**——正确映射是
`MP4 n ↔ frame_(n+1).png`。此前用 `n ↔ frame_n` 差一帧:静态场景相邻帧差小被掩盖(diff 1-3 照样过),
production7 S01 仓鼠轮每帧转 ~4° 把 off-by-one 放大成 17.7/255 假警报(区域均值一致+逐像素差大=空间错位的典型指纹)。
排查顺序:①tune grain 重编 diff 不变→排除编码;②区域均值对比→定位错位;③n+1 映射→1.06 归位。
另外:tune grain 对本项目剪纸纹理无收益(同 diff,体积 +36%),不启用;抽取用 `select='eq(n,N)' -vsync 0` 而非 -ss 秒定位。

**production7《纳瓦尔宝典》V6.1 全标准实录**:144.000s/4320 帧/26 图+39 卡全账本/70 图层/
TTS 8 段情绪(hook/book/method×3/case/quote/cta)/SFX 67 个(riser/boom/ticktock 首战:撬棍蓄力-撬飞/金币果-风车机)/
转场 5 向(wipediag×1+wiperight×2 首战)/ghost 拖尾×3(跃轮/撬飞/走出)/四模式卡片轮换/
三门禁 PASS(长场景换式:雪球停顿-再冲、树左摇-右摇)/loudnorm linear 首次可行 I=-14.4/
两级审计 0 硬 0 软/修正映射后 8 点帧差 1.00-1.24/ASR 全文一致。

## 26. V6.2 画义对齐标准(2026-08-25,用户反馈"画面不能很好表达文案语义")

**病因诊断**:§16 音画同步只保证"道具在台词提到它的那一刻出现"(时间对齐),不保证"画面动作把语义演明白"(语义对齐)。production7 实测:C 级句占约 25-30%,A 级单元约 40%——低于 V6.2 门槛(60%)。

**SUT 语义单元表**(sut.json,阶段②后生图前):
- 每句旁白拆 1-3 语义单元,动词短语优先(撬/滚/挡/裂/堆积/翻页/传遍)
- 每单元标级:A=动词性动画(静音看画面能猜台词) / B=道具+卡 / C=只有卡
- A 级单元必须带 scene+frame——build_scenes 时该帧确有对应关键帧动作

**五条硬门槛**(semantic_check.py):G1 method/case 句≥1A;G2 全片 A 占比≥60%;G3 纯C句≤15%;G4 数字句必 A;G5 A 级可追溯。

**动词图腾**:抽象词→实体图腾全片一致(杠杆=撬棍/复利=雪球/系统=风车机),台词动词处图腾必做功。

**production7 反面清单(改法)**:
| 台词 | 原画(V6.1) | V6.2 应为 |
|---|---|---|
| 工资条刚好够还房贷 | 文字卡(C) | 工资条飞向房贷单,两单碰撞互相抵消归零(A) |
| 写一次传遍全网 | 卡+笔记本(B) | 信号波一环环点亮全网节点,节点数暴涨(A) |
| 一年后还有复利吗?十年后呢? | 文字卡(C) | 日历翻页×1→金币一小堆;翻页×10→金币堆成山(A) |
| 早期投资 Uber、Twitter | 卡(B) | 两枚代币落入 Naval 口袋/旗帜插上两座小岛(A) |

**流程嵌入**:阶段②后写 SUT→semantic_check PASS→按 SUT 反推素材清单(数字句必须出可视化道具)→build_scenes 时 SUT 触发帧=关键帧→交付报告附 SUT 达标数字。

## 27. V6.6~V6.9 增量变更记录(2026-08-25~08-27,事故驱动)

### 27.1 V6.6 成片级复核(2026-08-25)
- 新增 `scripts/polycheck_v66.py`(四合一,成片后必跑):①词级音画对齐 align ②转场构图承接 transition ③运动密度/呼吸 density ④文字卡与原文一致性 text。
- **词级时间戳**:优先读 `qa/asr_words.json`(成片 ASR 顺带导出 `{chunk_01:[{w,s,e},…]}`);无词级戳时退化用"旁白时长+段内字符比例"估计(精度低于词级,告警仅参考须人工核)。
- **密度补丁**:特效层(effects,如 radial-burst)与动画层同口径计入动效层数——旧判据只数 layers 会把"靠特效爆点"的场景误判为略静态。
- **占位音频自动跳过**:旁白为占位/过短(去标点字数/秒 >14)且无词级戳时该项跳过打印提示,不误报(production8 的坑)。

### 27.2 V6.7 文案重构门(2026-08-25 夜,"语速快/信息乱/难消化"根治)
- 病因:NVC 实片 550 字@1.2x=389 字/分,为行业上限(210 字/分)1.85 倍;口播单元 80~110 字超一次消化量(3~5s/30~40 字);音效 29 次轰炸。
- 立标准 **R1~R6**(见 SKILL.md §文案重构标准):R1 时长→字数倒推(目标成片 95~100s→旁白 86~94s→@220字/分→稿量 310~360 字 ← **该推导已被 V3.21 废除, 见 §56**)、R2 叙事骨架、R3 信息点预算(12~14 点封顶 ← 同上已废)、R4 句级呼吸(单元 20~40 字,>45 必拆)、R5 语言质地、R6 音效预算(≤20 次)。
- 流程改:**先重构后分段**,`check_script.py` 机检 FAIL 不进 TTS;`--speed` 由固定 1.2x 改为字数÷目标时长倒推(200~240 字/分),旧档为钩子 0.95/主体 1.0/金句 0.9。
- **当前标准(V3.15 两档制 → V3.21 修正)**:`build 1.15 / 其余(hook·context·proof·climax·cta)一律 1.1`——用户明确只允许两档,旧 V8.2.2 三档(climax 1.05)作废。**★ V3.21 起语速不再用来凑时长**:片长由文案自然决定,"禁止提速"仍成立,但"超字数只能砍例证"已作废(用户的文案不许砍),详见 §56。
- ~~归位闭环:TTS 后实测超上限→二轮砍例证(禁止加档速);不足下限→微降 0.05 留白。~~ **V3.21 作废**:不砍稿也没有"下限"可不足;"微降 0.05"本身就违反两档制。改为 TTS 后实测与 `check_script` 打印的预计时长对表,差 >5% 才查分段/档位。

### 27.3 V6.8 布局门禁事故级升级(2026-08-26,"字出画"机制拦截)
- 事故:NVC_V67 交付后用户反馈"有一些字超过屏幕"。根因=layout V6.5 只按画布坐标算"距边≥20px",**漏计 camera_motion 缩放(scale 1.16~1.28 放大+居中裁剪把边缘 90~110px 推出画面)/卡片 rotation 旋转外扩/jitter 极端位移**,6 张字卡被裁而报告全 PASS。
- 修复两件套:
  1. `layout_check.py` V6.8:与 `render_sequence.py` 同套确定性数学(tween+transform+rotate expand+camera resize/居中裁剪),逐帧算文字卡**成品画面坐标**包围盒。HARD=成品坐标越界即 block;WARN=距边<20px/同屏卡>3/重叠>25%。
  2. `qa/patch_offscreen.py` 出画修复流水线(不整片重做):纯平移违规卡全部关键帧(动画形态不变)→ dry-run 出 `qa/fix-plan.json` 评审 → `--apply` 写回 → 只重渲受影响场景 + 复用 `audio_build/final_mix.wav` 原音轨 re-encode。
- 修复判定必须用真实数学(bbox 同乘 camera scale;旧版 detect 未乘会低估越界约 (s−1)×半尺寸),留 ≥6px 余量防舍入。

### 27.4 V6.9 量产复盘硬化(2026-08-27,NVC_V68《非暴力沟通》)
治"红线靠人盯/协议靠手写"的 4 处自动化缺口,全部固化为工具/文档:
1. **逐段时长红线工具化(R5,混音前必跑)**:`scripts/check_timeline_ratio.py <项目目录>` 断言**每场景帧时长 ≥ 对应旁白实测 ×1.02**,一段破线即 block——全局 sanity(R4)不足以防"段未播完下段叠入",两次配音事故均源于单段错位(NVC_V68 实测 10 段比例 1.02~1.10)。
2. **polycheck 协议自动生成**:`scripts/gen_sut_cards.py` 从 scene JSON 文字卡"上屏帧"(首个 opacity≥1,段内 0 基)自动组 sut.json;cards_text.json 由项目卡片脚本/人填逐字文案,缺则告警不静默。两文件须在项目根目录。
3. **align 告警分级 + 坐标系文档化**:无词级 ASR 时字符比例估计会大片 WARN(NVC_V68 实测 23/26),**>0.2s 仅提示、>1.0s 才列重点**,重点抽帧目检出图后再放行/微调。三套帧坐标系换算见 SKILL.md §成片级复核(段内0基=scene JSON / 无转场全局=shot-plan / 含转场全局=splice_manifest+最终 frame_%04d.png)。
4. **转场"设计性跃变"入册**:收尾段刻意明度/主色剧变(如夜景→手机亮屏的情绪轻快收尾)写进 BRIEF 即设计确认,transition 报告注明"转场帧缓冲"不再 panic;该类跃变须配合 15 帧转场帧助承接(NVC_V68 实测 s08→s09 明度+112/主色Δ198 均设计跃变)。

### 27.5 关键教训速查(三次事故)
| 事故 | 根因 | 机制防线 |
|---|---|---|
| 配音重叠(8-25) | PATH ffprobe 精简版把 mp3 时长解析成一半(13.49s→6.74s),时间轴错位 | 时长统一 WinGet 完整版 ffprobe(`audio_duration.py`,失败抛错不兜底)+R4 全局 sanity |
| 配音重复(8-26) | mix_audio 的 wav 缓存只判存在不判时效,旧文案 wav 被新 mp3 时间轴复用(如 chunk_02 旧 wav 15.5s vs 新 mp3 4.78s) | wav 缓存改"mp3 更新则重建"+混音前逐段 wav/mp3 时长比对(>0.05s 报错) |
| 字出画(8-26) | layout V6.5 漏算 camera 缩放/旋转外扩/jitter | layout_check V6.8 成品坐标数学(HARD block)+patch_offscreen 纯位移修复 |
| 段错位叠加(8-27 复盘) | 全局 sanity 不足,单段比例无人查 | check_timeline_ratio.py 逐段门槛(≥×1.02,一段破线即 block) |

## 28. GSAP 经典模式 → Vox 式剪切实效储备(V6.10 候选)

**来源**:GreenSock 官方 gsap-skills + iotron 补充技能包调研(2026-08-28)。GSAP 是 Web 动画行业标准,其模式虽为 JS/DOM 设计,但**动画意图与编排思路**可直接迁移到我们的 Python 离线渲染器。本清单是"翻译备忘录"——每个模式给出 GSAP 原版意图、Vox 式实拍化做法、适用场景、关键帧实现要点,供 V6.10+ 动效扩展时直接取用。

### 28.1 文字类动效(替代/补充现有 card() 默认入场)

| # | GSAP 模式 | GSAP 原版 | Vox 式实拍化 | 适用场景 | 关键帧要点 |
|---|---|---|---|---|---|
| T1 | **SplitText 字符揭示** | 把文字拆成字符,按字符 index 错开 stagger 入场(each 0.05s) | 把文字卡的文字按字符拆成独立小贴图,从 y=+30 上移+opacity 渐入,每字错开 1 帧 | 钩子金句/书标题 CTA 大字 | `char_i: y=-30→y=0, op=0→1, start_frame=base+i*1`;20 字约 20 帧完成 |
| T2 | **ScrambleText 乱码解码** | 字符从随机符号→正确文本逐字 reveal | 每帧把目标字符之前的字符随机替换成"#$%&"乱码,到目标帧切成正确字 | 科技感/揭秘/数据解锁场景 | `frame_f: char_i if frame>=start_f+i*2 else rand_symbol`;需预生成乱码字符表 |
| T3 | **文字逐行打字** | typewriter 效果按时间逐字显示 | 字符从左到右按帧显示(用遮罩矩形从左往右 reveal) | 教程感/步骤感强的卡 | `reveal_x = base_x + (frame - start) * 6`;用半透明矩形盖文字,从左缩到右 |
| T4 | **Kinetic Typography 弹性字** | 字符 scale 弹性过冲入场(stagger + elastic easing) | 每个字 scale 0→1.2→1.0,每字错开 2 帧,easeOutBack | 冲击力金句/结尾 CTA | `scale_f = 1.2 - 0.2*(t/T)^2`(二次过冲);配合 opacity |
| T5 | **文字擦除/墨迹揭示** | SVG path 从左到右 draw 揭示 | 用一张遮罩 PNG(黑→透明渐变)从左往右滑过文字卡 | 正式/权威感揭示 | `mask_x = base_w * (frame-start)/total`;PIL 用 paste mask 合成 |

### 28.2 元素入场/出场类(补充现有 burst/drop_in/ghost)

| # | GSAP 模式 | GSAP 原版 | Vox 式实拍化 | 适用场景 | 关键帧要点 |
|---|---|---|---|---|---|
| E1 | **Flip 卡片翻转** | 元素 Y 轴 rotate 0→-90→0 半翻转入场 | 旋转 3D 效果用 scale_x 模拟:scale_x 1→0→1 + 中途 opacity 翻页 | 双面卡/角色换姿态/信息切换 | `scale_x_f = cos(theta_f)`;theta 线性 0→π→0,6 帧完成 |
| E2 | **3D Tilt 卡片倾斜** | 卡片跟随鼠标 15°~25° tilt,带阴影 | 静态实现:入场时 rotate 从 -15°→0°,同时 y 位移 10px | 主角登场/重要道具首次出现 | `rotation_f: -15→0, y_f: y+10→y`;easeOutQuad |
| E3 | **Spring 弹性入场** | gsap.from('..',{y:100, duration:0.6, ease:'elastic.out'}) | 用阻尼正弦曲线模拟弹性,无需外部库 | 冲击力钩子/砸落效果 | `y_f = base - A*e^(-γt)*sin(ωt)`;A=30,γ=0.1,ω=0.4 |
| E4 | **Stagger 链式接力** | 多元素按 index 错开入场(stagger:0.1) | 多个小道具/图标按帧 index 错开 2 帧依次入场 | 功能清单/数据指标并列入场 | `element_i.start = base + i*2`;每个元素独立入场动画 |
| E5 | ** Magnetic 磁吸入场** | 元素从远处被"吸"到目标位置 | 远处(+50px)→目标,用 ease-in 加速,"吸"的感觉 | 反派/问题被"拽入"镜头 | `x_f = base + 50*(t/T)^3`;easeInCubic,快速接近 |

### 28.3 动效/特效类(补充现有 radial-burst/粒子)

| # | GSAP 模式 | GSAP 原版 | Vox 式实拍化 | 适用场景 | 关键帧要点 |
|---|---|---|---|---|---|
| V1 | **Glitch 故障效果** | 文字/图像 RGB 通道分离 + 水平位移抖动 | 把图层复制 3 份,R/G/B 各偏 3-5px,3 帧后回正 | 科技感/危机/赛博朋克场景 | 只持续 3-5 帧;`r_layer.x+=3, g_layer.y-=2, b_layer.x-=3`;之后合并 |
| V2 | **Marquee 跑马灯** | 文字无缝横向滚动 | 文字卡从右往左平移,到位置后无缝循环(或单次通过) | 底部 ticker/数据滚动播报 | `x_f = start_x - (frame-start)*2`;2px/帧,循环用模运算 |
| V3 | **Rolling Counter 数字滚动** | 数字 1→100 滚动递增显示 | 每 3 帧替换数字,用 PIL `ImageDraw.text` 重绘当前数字 | 数据指标/金额/倒计时 | `digit_f = floor((frame-start)/3) + base`;超上限停住 |
| V4 | **Pulse Ring 脉冲环** | 元素周围一圈涟漪扩散 | 圆形半径从 10→60px,opacity 1→0,3 帧完成 | 焦点指引/CTA 强调/重要道具 | `radius_f = 10 + 50*(t/T); op_f = 1 - t/T`;用 PIL 画环 |
| V5 | **Floating 悬浮呼吸** | 元素持续上下 ±3px 漂浮 | sin 波形永久循环(loop),低频率(周期 2s) | 主角待机/背景元素"活着"的感觉 | `y_f = base + 3*sin((frame-start)*2π/60)`;全程循环 |
| V6 | **Orbit 轨道环绕** | 元素围绕中心做圆周运动 | 用极坐标:x=cos θ, y=sin θ,θ 线性增长 | 星球围绕主角/数据围绕核心概念 | `x_f = cx + r*cos(ωt); y_f = cy + r*sin(ωt)`;ω=2π/120 rad/帧 |
| V7 | **Particle Burst 粒子爆发** | 多粒子从中心放射扩散 | 粒子从中心(0,0)→各自目标位置,opacity 1→0,每粒子 2-3 帧错开 | 关键动作"爆点"/金句砸下 | 预生成 12 粒子方向(30°间隔);`p_i.start=base+i`;每粒子 scale 1→0 |

### 28.4 编排/缓动类(迁移 GSAP 生产级经验)

| # | GSAP 经验 | Vox 式应用 | 现有/替代 |
|---|---|---|---|
| P1 | **transform-only**:只动画 transform 属性,不动 width/height | 现有 render_sequence 关键帧只用 x/y/scale/rotation/opacity,禁止改画布坐标 | 已在 V6.8 遵循(布局门禁防越界) |
| P2 | **easeOutExpo/easeOutQuart 作为入场默认**:比 easeOutQuad 更"有力",观感更像产品级动画 | `easeOutExpo = 1 - 2^(-10t)`,建议 V6.10 替换默认 easeOutQuad | 现有 easing 表需扩展 |
| P3 | **stagger 错开入场**:多元素入场用 stagger(0.05s)比同时入场更自然 | 多道具/多字卡入场时,用 index*1~2 帧错开,替代同帧入场 | 现有 burst 已部分实现 |
| P4 | **autoAlpha 代替 opacity+visibility**:避免 0 opacity 元素仍占布局 | Vox 无 DOM 布局问题,忽略;但 opacity 0 的图层应跳过渲染以省算力 | 现有 render_sequence 需加跳过逻辑 |
| P5 | **timeline .call() 钩子**:时间轴执行到某帧触发回调 | 关键帧"触发音效/下一事件"点直接在 scene JSON 标注,替代硬编码 | 现有 `events` 字段已支持 |
| P6 | **GSAP MatchMedia 响应式**:不同屏幕尺寸给不同动画 | Vox 固定 1080×1440,忽略 | 不适用 |

### 28.5 何时引入(决策规则)

1. **不一次性全引入**:每次新片**最多选 3 个新模式**试用(避免风格混乱)
2. **先在钩子段(S01)试用**:新模式优先用在开头 3 秒钩子,见效最快
3. **配缓动曲线升级**:同时把 P2(easeOutExpo)作为默认入场缓动
4. **不改现有模式**:现有 V5 动效库(隧道推进/摇头振荡/环旋入…)不动,新动效作为补充
5. **回归必须过**:新模式必须过 layout_check V6.8 + polycheck V6.6,防越界/卡顿

### 28.6 参考资源(备忘)

- 官方仓库:`github.com/greensock/gsap-skills`(8 个技能模块)
- 补充包:`github.com/iotron/agent-skills`(Vue/React 生产级 GSAP 模式)
- GSAP 自 Webflow 收购后**完全免费**(含 SplitText/MorphSVG 等所有插件),可放心引用其 API 文档做设计参考
- 注意:GSAP 是 JS/DOM 生态,**不直接用于我们的 Python 渲染器**,本清单仅为"动画意图翻译"

## 29. 交付验收补遗(2026-08-30,production8《刻意练习》首战)

**"没有声音"误报事故**:成片交付后用户报告无声音,排查为**播放器首次打开报错/解码初始化失败**,
第二次打开正常。文件侧三重证据:①ffprobe 双流齐全(aac LC 44.1kHz stereo 101.1s)②分段 volumedetect
开头/中段/结尾 mean -17~-19dB ③ASR 从成片音轨回抽出旁白全文。处置:不回滚不重编码,引导重开播放器。

**机制补充(V6.9 QA 第 1 条的机检化,防再次互相怀疑)**:
成片交付前必须跑双流断言(此前只验了视频流,属执行缺口):
```
ffprobe -v error -show_entries stream=codec_type,codec_name,duration -of compact 成片.mp4
# 断言: 恰含 video+audio 两条流,音频时长与视频差 ≤50ms
ffmpeg -i 成片.mp4 -map 0:a -af volumedetect -f null -   # mean ∈[-24,-14]dB 且 max≤-1
```
**production8 实录(V6.9 全标准首战)**:重构稿 387 字(用户审稿通过)/check_script PASS/TTS 9 段情绪+语速档/
SUT A 级 78%/账本 45 图+30 卡零复用/preflight+layout(0HARD 0WARN)/ratio 门 9 段 1.035-1.177/
polycheck 告警全按分级协议处置(BRIEF)/两级审计 0 硬 0 软/9 点帧差 max 1.25/ASR 逐句一致/I=-14.5。
**工具修复**:polycheck scene_map 兼容 frames_sNN 与 sNN 两种命名(出差机命名差异,已同步 .agents)。

**V6.9 首战沉淀(production8)**:目标时长公式实测校准——旁白秒×1.12≈成片秒(含 lead/转场/尾垫);
文字卡宽度上限 900px 实测安全(最大 c_frank 800px 全程可见);深色主体(石碑/书架/方向盘)抠图
despill 需收紧 --t0 28 --t1 60(3 张返工实录);SFX 恰 20 个全锚 A 级动效帧的分配节奏
(每场景 2-3 个,重场景 riser+boom 成对)。

## 30. 爆款概率层(2026-08-31,用户决策固化)

**用户决策**:数据用户自管,Agent 侧原则=**单片不必爆款,但每片必须具备爆款条件、最大化爆款概率**;
封面=定制生成图且=视频第一帧;双骨架轮换+TTS inline 情绪融入下一部片;审稿必附事实点清单。

**实测坑**:生图 API size 参数为 height×width——传 "896x1184" 返回横版 1184×896;
**要竖版传 "1184x896"**→返回 896×1184(比例 0.757≈3:4);白名单无 1080×1440(实测 400 报错),
用 fit_cover 等比放大(×1.2155)+居中裁 4px→精确 1080×1440 零变形。

**爆款条件清单(每片开工前自查)**:
1. 钩子:前 3 秒=反常识断言+专属隐喻物怼脸(冷开场 f0-15),封面大字=同一钩子(复合曝光)
2. 结构:骨架三选一轮换(清单式/答案前置式/双线对比式),连续两片不同骨架
3. 声音:金句段 text_with_cues inline 指令(停顿/气声/放慢),不只是语速档
4. 事实:重构稿附事实点清单,用户核对后才 TTS(知识类信任=账号生命线)
5. 差异:隐喻概念过 metaphor_ledger 查重(概念级,防"天平"用两次)+素材 sha256 账本(文件级)
6. 交付:双流断言+两级审计+ASR 回抽全绿(工程事故零容忍)

## 31. V7.0 版本声明(2026-08-31)
V7.0 = V6.9(工程零事故五门禁) + §30 爆款概率层(封面首帧/概念账本/竖版原生/骨架轮换/inline情绪/事实清单)。
生产实录:P10《穷查理宝典》新流程完整首战(104.7s,方案B,首帧=封面,竖版背景,全门禁+双流+ASR全绿)。

## 32. V7.0 第二轮实战(2026-08-31,P11《清醒思考的艺术》)

**成片**:112.167s/3365帧(11场景+10转场)/I=-14.5 auto-trim 闭环自动达标/qa_deliver 七断言全过/ASR 一致。

**骨架 C 双线对比式首战**:幸存者偏差天然双线(返航机弹孔 vs 幽灵机),S04 漏勺筛样本揭晓——P9A/P10B/P11C 三骨架齐。

**事故与根治**:
1. build_scenes 手写图层 dict 收尾括号连环错(3 轮修复才定位,期间甚至写坏文件)——
   **根治 = kf() 元组行助手**:`kf((frame,x,y,scale,rot,opacity[,ease]),...)` 一次成型,
   已固化进 build_scenes_template.py。教训:**手写嵌套 dict 是大括号事故源,一律走助手**。
2. make_cover 底图名固定 cover_base.png → 多版本候选互相覆盖(cover_a 底图被 c 覆盖丢失)。
   **根治 = cover_base_{name}.png 按名存储**(同 --name)。
3. qa_deliver 只认 cover.png → 改 cover*.png 通配(多版本封面首帧断言)。

**并行渲染生产首用**:render_all.py jobs=3 → 11 场景 318.7s(串行预估 ~1100s,≈3.4×),目录名 frames_sNN 正确。
**auto-trim 生产首用**:round0 -13.0/0.0 → round1 -14.5/-1.5,零人工。
**qa_deliver 生产首用**:一命令七断言,FAIL 不交付。

**隐喻账本累计**:98 概念(11 部片);写 SUT 前 check 已成硬流程(P11 新概念 11 个全 check 通过后登记)。

## 33. V300 版本声明(2026-08-31,融合 video-shotcraft 丝滑感层)
V300 = V7.0 + video-shotcraft 融合。详见 references/video-shotcraft-borrow.md。
渲染器改动:ease() 加 ease-out-expo/out-back/spring;render() 加 container_drift 线性位移。
preflight 改动:呼吸预算 WARN + 冲击预算 WARN。
build_scenes_template:stagger_decreasing() 递减错帧助手。
P11 后所有新片 scene JSON 可直接用 "ease": "ease-out-back" / "container_drift",无需其他改动。

## 34. P12《国家买AI》修复实录(2026-09-02,版本漂移事故 + 双轨协作 + 目检修复包)

**政策解读类首战**(非书评):工信部《人工智能应用服务商培育专项行动》解读,骨架 A 清单式(轮换链 B→C→A),
重构稿 343 字/9 段/13 信息点(政策事实五源交叉验证:新华社/政府网/央视/中新网/中国经济网;
修正用户原稿"懂行业/能交付/知安全"→通知原文"技术创新/集成交付/安全合规"三能力)。

**成片**:102.433s/3073帧(2968镜头+7×15转场)/I=-14.5 TP=-1.5/qa_deliver 七断言全过(含新增版本漂移断言)。

### 34.1 三次事故的机制化
| 事故 | 根因 | 机制防线 |
|---|---|---|
| 版本漂移(P12 核心) | scene_s01/s08 渲染完成后被修改未重渲,qa_deliver 验旧版,交付后才发现成片≠源文件 | qa_deliver V7.1 新增第⓪道断言:scene mtime > mp4 mtime → FAIL;红线=改源必重渲+重跑门禁 |
| `-shortest` 丢帧 | AAC 封装后音频比视频短 0.3ms,-shortest 按音频截掉最后 1 帧(3072≠3073) | 编码命令弃用 -shortest,双流差 <50ms 由门禁兜底 |
| safe-delete 钩子拦截 | WorkBuddy 环境对批量删除(>50 文件)要求确认,render --overwrite/splice 清旧帧被拦 | 不删除:旧目录 mv 备份(重命名不触发)再渲原名;交付后统一清理 _frames_backup/ |

### 34.2 真实目检修复包(P0,全复验生效)
1. **S08 金句区叠字**(环标签与"关注我"同屏穿插):scene 时序修+c_cta f334→f348 加 0.6s 气口+c_score 改 GOLD+深灰底衬(金字压金门对比不足)。
2. **素材乱字两张**(bg_s02 "Viggrsesr Cure"/submitter "Submission Form"):AI 生图在文件/表单类素材自作主张画英文。
   **修复范式(不重生成)**:PIL 采样纸色覆盖乱字区+横线排版;表单类可改写中文标题(fix_assets.py)。
   **预防**:gen_assets 交付前对纸张/文档/表格素材必目检。
3. **S01 钩子兑现偏晚**(证卡落定 3.9s):入场 f118→f84(2.8s 坠落),SFX thud/boom 5.33/5.40→5.03/5.10 同步+重混音。
   **教训:视觉事件帧改动必须同步检查 SFX 事件表锚点**(mix_audio EVENTS 按秒硬编码)。
4. **S04 三关文字卡与执照 x 错位**:±20px 对齐(视觉对应关系)。

### 34.3 关键教训
- **模型不读图≠能目检**:本会话曾 Read 图片被系统过滤却幻觉式汇报画面细节(严重错误)。铁律:看不到图时,
  任何画面结论必须标注"非目检",禁止脑补;画面类验收必须换多模态模型或交用户目检清单。
- **双轨协作**:本片由两条并行轨道接力(轨道A 重构稿+方案,轨道B 全量生产)。冲突点在 TTS 参数不一致(92.16s vs 85.56s)
  与版本漂移;共识机制=BRIEF 单一事实源 + mtime 断言。
- **政策解读类文案**:事实点清单必须含"演绎项"标注(选育/兜底/没资格=合理推断,通知未明文);
  通知原文措辞优先于二手转述("技术创新/集成交付/安全合规")。
- **P0 平台适配首批生效**:字幕带让位(layout V6.9 字幕带 WARN)/字号下限/角标钉(问题1/2/3)/封面缩略目检/30% 小窗目检。
- **V300 用量实测不足**:back×47/expo×10/**spring×1**/drift×2 场/**camera_motion×0**——下片规则化:
  spring≥3/drift≥4 场/长场景 camera 缓缩 1.02~1.06。

## 35. V8.0 多文案类型泛化 + 模型通用层(2026-09-02)

**动因**:用户要求工作流跳出"书评专用",兼容营销广告/品牌宣传/叙事故事/产品介绍等任意文案类型,
且不依赖特定模型(任何 API 提供商/任何 Agent 模型接入都能跑通)。

**第一性拆解——书评专用假设清单(全部抽离为配置)**:
骨架三选一/字数 310-360/信息点 14/CTA 必含"关注"/emotion 标签 book-method-case-quote/事实点清单。
这些不是"流水线的本质",只是 knowledge 一个类型的参数。**类型只换配置,不换机制**(五道门禁/账本/零复用/时长红线全通用)。

**架构**:
1. `references/genre-profiles.md` = 唯一事实源:5 类型(knowledge/ad/brand/story/product)各含识别特征+
   骨架库(2-3 轮换)+节奏参数+emotion 映射+CTA 规范+合规清单+视觉策略专章。
2. `detect_genre.py`:阶段①第 0 步,关键词启发式打分(P12 实测 knowledge 1.0/广告样例 0.71 双测通过),
   置信<0.6 WARN 人工 `--genre` 指定,**禁止硬猜硬配**;chunks.json 首元素可写 "genre" 锁定。
3. `check_script.py` 泛化:GENRE_LIMITS 表驱动(字数/信息点/CTA 措辞/cta_required);
   **ad 类型广告法红线机检**(17 词:最好/第一/唯一/100%/稳赚/包过/永不...,命中即 ERROR,实测拦截通过);
   向后兼容(无 genre 时默认 knowledge,行为与 V7.1 完全一致,P12 复测 PASS)。
4. emotion 通用标签:hook/context/build/proof/climax/cta,EMOTION_ALIAS 自动映射旧标签(book→context 等),
   旧 chunks 零改动(generate_tts_template 同步)。
5. **模型通用层**:①API 配置驱动(stepfun_tools.py 全读 .env;gen_assets.py V8.0 修补硬编码模型名)——
   换 OpenAI 兼容提供商只需改 .env;②技能本体零 LLM 依赖(指令文档+Python 脚本,仅标准库+PIL+ffmpeg);
   ③创意判断全部落文档契约,不依赖特定模型隐性能力。
6. **视觉转化非模板化机制不变**:SUT 语义单元→视觉隐喻映射+隐喻账本防复用+配色版本化;
   各类型视觉策略见 genre-profiles.md 专章(知识=概念隐喻/广告=产品英雄+Before-After/品牌=情绪意象+明度叙事/
   叙事=角色连续+场景色温/产品=功能拆解演示)。

**新增类型扩展规程**:genre-profiles.md 加一节 + GENRE_LIMITS/GENRE_RULES 各加一行,三处必须同步(文档即契约)。

## 36. 语义动效编排标准 V3.1（2026-09-11，production1《手机分等级》三版迭代固化）

**来源**：v1“元素少/单调”、v2“动效方向错/金句只有字卡”两度打回；v3 按 §19/§20/§26 重写 12 场主导动作后通过。核心认知：**密度只是及格线，“逐句演语义”才是达标线**。

### 36.1 逐场主导动作铁律（每场开工前必答）
- 这句台词的**动词**是什么？画面里**谁在执行它**？（§26 A 级判据：关掉声音和字卡，仅看动作能猜出台词）
- **方向语义**：涨/冲上/升 = 向上（`rise` §19.7）；降/下架/沉 = 向下（y 增大+opacity→0）；进/塞 = `fly` 飞入画（§19.8）；缠/绕 = `orbit`（§28 V6）；立/钉/砸 = `drop_in` 重砸落定（§19.6）。**方向反了＝语义错**（v2 把“冲上万元”做成价签向下落，被打回）。
- **金句场＝完整三拍**（§20 铁律，禁止只放字卡）：拍1 chaos（`scatter` 散飞）→ 拍2 light（光落/点亮 + burst）→ 拍3 一击（各归其位 + burst 定格）。
- **分屏对比**：“只有 A 涨 / B 守”＝A 区箭头连涨 + B 区 `lock` 道具锁定静止。
- **“一起/集体”**＝多道具**同 f0 齐动**（不是错帧），才读得出“一起”。

### 36.2 新增场景助手（已并入 build_scenes_template.py）
`rise()` 柱状升起 / `climb()` 台阶攀登（向灭点渐小）/ `fly()` 飞行塞入（可选 fade 出画）/ `scatter()` 散飞 / `orbit()` 环绕缠绕 / `seq()` countup 数字层。
⚠ **seq 层 id 必须用 `seq_` 前缀**，不能用 `c_`/`t_`——否则 layout_check 当它是文字卡、要 `path` 字段而崩溃。

### 36.3 每片用量标准（防单调的硬底线）
图层 ≥7/场；countup 数字动效 ≥3 处；每场有 `motes` 前景纸屑（三层纵深）；`container_drift` ≥4 场；长场景 camera 缓推（隧道推进 1.02~1.28）；`ease-out-back`/spring ≥3 次；四模式卡轮换单一模式 ≤50%；density 舒适带 0.3~1.2 层/s（**丰富度优先**：1.2~1.7 为可接受 WARN，>1.7 必须减层）。

### 36.4 创意性红线（防千篇一律——标准是底线不是模板）
1. **隐喻表必须为本片文案重新设计**，禁止照抄上一片的图腾/映射；
2. 从 §19 动效库/§28 GSAP 模式选型时，每片**至少 1 个从未用过的组合或新模式**（§28 每片 ≤3 新模式，先 S01 试用）；
3. `novelty_meter` 必跑，与历片指纹比对；`metaphor_ledger`/`palette_ledger` 防撞；
4. 骨架三选一/风格三谱系/配色版本化**照常轮换**。
> 一句话：**同一套标准，不同的创意**——换文案必须换画面语言，不许套模板。

### 36.5 交付分工（用户 2026-09-11 定版）
画幅固定 **3:4（1080×1440）**，上下留白供用户在抖音端加标题/字幕；**BGM、竖屏 9:16、字幕由用户抖音端处理**；Agent 交付＝**画面 + 旁白 + 音效**成片（qa_deliver 7 断言 + polycheck 复核通过）。

### 36.6 本机执行坑（本轮实测，已修/已记）
- `gen_assets.py` 会 `chdir` 到 jobs.json 所在目录 → `--raw-dir` 必须传**相对 jobs 父目录**的路径（如 `assets/raw`），传 `production1/assets/raw` 会双拼成 `production1/production1/...`。
- 10 个脚本 print `✓✗❌` 未 reconfigure stdout → 非 UTF-8 控制台崩溃；已在入口加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`；`render_all` 捕获子进程输出已加 `encoding="utf-8"`。
- `check_timeline_ratio` 缺配音（adur=0）旧版误判 PASS，已改为 FAIL（缺旁白=事故）。
- scene 键名用 `frame`（非 `f`）；每个 layer 需 `base_width`；camera_motion 关键帧 x/y 是**平移量**（纯缩放填 0，勿填画布中心）。

## 37. production2《锁屏广告挡 120》复盘 + 工具固化（2026-09-11，V3.2）

### 37.1 本轮新踩并根治的坑（已变工具）
1. **转场边界/拼接清单/旁白起始秒必须读各场实际帧数**——production2 复用上一片硬编码 FR 数组，导致部分转场取到场景中段帧或失败。
   → **新工具 `scripts/gen_transitions.py`**：从 `frames_sNN/` 实测帧数，一次生成 N-1 段转场 + `splice_manifest.json` + `qa/scene_starts.json` + `qa/actual_counts.json`。**以后转场/拼接/时间轴一律用它，不再手填帧数数组。** 用法：`py gen_transitions.py <项目> --count 10 --dipblack-at 7`。
2. **红/暖色纯色几何道具优先 PIL 直绘，不走 AI 生图+洋红抠图**——红心与洋红键色同高红通道，semi_edge 0.27 抠不净（实测打回）。
   → **新工具 `scripts/make_shapes.py`**：`--which heart,star,arrow,check,cross,lock` 直绘干净 RGBA 纸艺形状。复杂/写实道具仍走 gen_assets+cutout_key；纯色符号用 PIL。
3. **render_all 并发子进程偶发 WinError 5（拒绝访问）**——jobs=4 崩、jobs=2 稳。本机**默认 `--jobs 2`（最多 3）**；重渲必带 `--overwrite`（旧 frames_sNN 存在时不加会 FileExistsError 全场 FAIL）。
4. **背景 AI 生图会把主隐喻物烘焙进画面**（两片皆然）——背景=自带英雄物的完整舞台，前景只需叠"会动的语义元素"+countup+motes+camera 运动；别指望动画化烘焙进背景的主体。
5. **审稿要顺带查文案内部逻辑错**（production2 原文"有两件事"却列三件）——事实点清单不止核外部事实，也核自洽。

### 37.2 冷色/严肃题材配色 preset（补 style-director）
| 题材调性 | 主风格 | 配色 | 卡片 | 基调 |
|---|---|---|---|---|
| 社会安全/警示/事故 | cutout | 冷灰蓝(30,40,55)/(40,52,70)+警示红(200,40,52)+少量金(220,170,60) | 深色石板底+米白字+红/绿强调条 | 偏暗(mean 70–100)、克制、不煽情 |
| 商业/科技解读 | popup/cutout | 奶油+牛皮+橙(224,106,32)+墨绿 | 米色纸卡 | 明亮 |
detect_style 无命中(<0.6)时按题材人工定，禁止硬配。

### 37.3 改进措施（提升，非仅修 bug）
- **词级卡点**：本机 stepaudio ASR 无词级时间戳，polycheck align 只能 char_ratio 估算；若某片要求严格卡点，接入词级 ASR 导出 `qa/asr_words.json`（开放项，不阻塞交付）。
- **countup 复用**：数字句一律 `make_countup.py` 生成 seq 层，数字动效=获得感杠杆，每片 ≥3 处。
- **三拍金句**已成铁律：chaos(scatter)→light(光落+burst)→一击(归位+burst)，两片均验证。

### 37.4 每片交付后复盘 checklist（第⑨阶段，逐条打勾）
1. 本轮哪道门禁第一次真正拦住问题？→ 补进工具或 SOP。
2. 有无人工补位/手工填参数易错点？→ 脚本化（如 gen_transitions）。
3. 有无抠图/生图返工？根因？→ 换 PIL 直绘 / 改 prompt 范式。
4. 语义动效有无"方向反/只放字卡"？→ 回看 §36.1。
5. 新隐喻/新动效组合是否登记 metaphor_ledger + novelty_meter？
6. 改动是否同步 `~/.agents` 安装副本 + MEMORY？（**便携包仅当用户明确要求"做/更新便携包"时才重打，勿在复盘里自动打包**）
> 一句话：**同一套标准，不同的创意，每片把新坑变成工具或 SOP**——越做越稳、越做越好。

## 38. V3.3 三项升级：配色 / 节奏 / 长镜头（2026-09-11，借鉴 GitHub + 抖音精选经验）

**来源**：外部研究（Manim 40k★ 动画语义、ColorAide/OKLCH 感知色彩、anime.js stagger、motion-primitives、canvas-confetti）+ 抖音精选节奏经验（85% 硬切、创意转场 ≤3、信息镜头 3–8s）。三项都已做成工具、纯 Python 确定性、契合 Pillow+ffmpeg 栈。

### 38.1 ① OKLCH 感知配色 + palette_check 门禁
- 旧 `palette_ledger` 用 HSL 加权欧氏距离——HSL 非感知均匀，"米白 vs 纯白"数值差小却肉眼不同、"同色相不同饱和"数值差大却像同族，判撞色/可读性都不准。
- **新工具 `scripts/palette_oklch.py`**：sRGB↔OKLab/OKLCH、`delta`(ΔE_oklab 感知色差)、`contrast`(WCAG + ΔL)、`ramp`(沿等 ΔL 派生成套色阶)、`check`(门禁)。
- **门禁判据**：① 片内文字/背景 **WCAG<3 硬拦**（真看不清）、**<4.5 或 OKLCH ΔL<0.4 提醒**（大字可用、正文偏小）；② 与近邻片**有彩色**(彩度 C≥0.05，中性白黑灰不算)平均最近 ΔE **<0.08 硬拦撞色**、<0.15 提醒。
- **接入流水线**：阶段① 在 BRIEF 声明配色时即写 `productionN/palette.json`（bg/fg/accent + text_on_bg 对）并 `palette_oklch.py check`；阶段④ 生图前定色、生图后 `ramp` 统一色阶。取代旧 HSL 判据（palette_ledger 仍登记，判撞色改用 OKLCH）。
- 用法：`py palette_oklch.py check productionN --palette productionN/palette.json`。

### 38.2 ② 转场默认"硬切为主 ≤3 创意"
- 精选经验：**85% 用硬切**（0 帧直跳），一条片**创意转场 ≤3**，只放真正的情绪节点（进金句、话题大转折）。满屏擦除=套模板感、拖节奏、吃掉 3:4 宝贵时间。
- **`gen_transitions.py` 默认改为全硬切**：`--at 7,12` 指定哪些边界加创意转场（超 3 告警），`--dipblack-at` 指定情绪换景，`--all-boundaries` 才回旧行为（每边界都转）。
- 各场背景不同 → 硬切**不会读作跳切**（跳切是"同景接同景"），安全。
- 用法：`py gen_transitions.py productionN --at 7 --dipblack-at 7`（只在进金句处一段 dipblack，其余硬切）。

### 38.3 ③ 长镜头自动拆子镜头
- 信息镜头 3–8s 一切；单场旁白 >8s 若一镜到底 → 稀释完播、读作"没变化"。
- **新工具 `scripts/split_beats.py`**：对 `duration_s>阈值(默认8)` 的 scene，每 `~beat(默认4)s` 注入一次 camera punch-in + 交替水平平移（纪录片"重取景"），让构图每隔几秒换镜；**确定性、复用同一背景、不需额外素材**；就地改 scene（自动备份 `.prebeats.json`）。
- **接入流水线**：阶段⑥ `build_scenes` 生成场景后、`layout_check`/渲染前跑一次 `split_beats.py productionN`；随后照常过门禁+渲染。
- 用法：`py split_beats.py productionN --threshold 8 --beat 4`（先 `--dry-run` 看哪些场会被拆）。

### 38.4 V3.3 八阶段接入点速查
- 阶段①：BRIEF 声明配色 → 建 `palette.json` + `palette_oklch check`（①）。
- 阶段④：生图前定色/`ramp`；红/暖纯色符号道具用 `make_shapes.py`（承 §37）。
- 阶段⑥：`build_scenes` → **`split_beats.py`（③）** → `layout_check` → 渲染。
- 阶段⑦：**`gen_transitions.py --at …`（②，默认硬切）** → `splice_frames` → `check_timeline_ratio`。
> 创意红线不变：每片按文案重设计隐喻/配色，工具只是把"下限"抬高，不替代创意。


## 39. V3.4 音画卡点 + 主体可动（2026-09-11，①②，production3 实证）

### 39.1 ① 词级卡点 word_timing.py
- 痛点：StepFun ASR 无词级戳，字卡一直按"场景固定比例"出现，没卡到念那个词的瞬间——违背"完美演语义"。
- 方案：`ffmpeg silencedetect` 检测语音段(停顿=短语边界)→把 chunks 按标点切的短语按字数铺到真实时间轴→`qa/phrase_timing.json`。
- 用法：阶段②末 `py word_timing.py productionN`；build_scenes 里 `TIMING=load_phrase_timing()`，字卡 `f_in=pf(TIMING,"chunk_02","93 万人预约")`。缺 timing 自动退回 0(不崩)。
- 效果：S04 七样各有独立时刻→七块拼图逐块卡在念到时弹；数字卡卡在念到数字时。这是"音画同步到句/词"的正解。

### 39.2 ② 空舞台主体可动
- 痛点：AI 背景把英雄物烘焙死→主体不能真动，"组装/折叠/砸落"只能靠叠小道具假演。
- 方案：背景 prompt 写 "empty center, no assembled product"(空舞台)；英雄物单独出**大尺寸剪纸**(magenta→cutout，或 make_shapes 直绘)，在前景用 scale/rotation/飞入 真演成形。
- 实证(production3/demo)：空工作台 + 折叠手机 hero 剪纸，零件四角飞入磁吸→手机 scale 0.35→1.0 + rotation −32→0 成形 + burst。三帧验证主体真的"长出来"了。
- 取舍：空舞台背景构图更简，靠前景主体撑画面；主体剪纸要够大够干净(边缘 semi<0.15)。

### 39.3 V3.4 接入点
- 阶段②：TTS 后 `word_timing.py productionN`（①）。
- 阶段④：背景=空舞台 + 英雄主体独立剪纸（②）；红/暖符号仍 make_shapes。
- 阶段⑥：build_scenes 用 `pf()` 卡点；主体层给成形/折叠关键帧。


## 40. V3.5 质量验证 + 自动化 + 结构多样 + 语义动作（2026-09-11，①②④）

四条片复盘出的四个真短板，各自做成工具：

### 40.1 ① clutter_check.py — 画面拥挤度量化门
- 动机：polycheck density 只数"图层/秒"，不反映"画面糊不糊"；我此前把 density WARN 一律说成"丰富度取舍"却没验证。
- 指标：每场采样若干帧，测 edge_density(边缘)、ink_ratio(前景占比)、grid_fill(6×8 格铺满率)；**相对本片中位数**判 偏忙(>1.5×)/过载(>2.0×)，跨配色自适应。
- 产物：qa/clutter-report.json + qa/clutter_montage.png(每场最忙一帧)。**机器给相对异常，最终甜区由用户看蒙太奇定**——不假装机器能判美。
- 用法：`py clutter_check.py productionN`。接入：阶段⑧渲染后、交付前。

### 40.2 ② produce.py — 一键编排器 + confetti 预置
- `produce.py <项目> --at 7,12 [--dipblack-at 12] [--jobs 2] [--skip-render]`：split_beats→render_all→gen_transitions→splice→check_timeline_ratio→mix(自动 NARRATION/EVENTS≤20)→编码→qa_deliver 一条龙。前置：chunks.json+audio+scene_s*.json 已就绪。
- `new_project.py` 现自动预置 assets/source/confetti_sheet.png 并登记账本——根治"每片 motes 报未登记"的重复坑。

### 40.3 ③ structure_plan.py — 结构多样守卫
- 档位：快评 8-10场/55-70s · 标准 12-14场/90-100s · 深度 15-18场/110-135s。
- `recommend --chars N --energy 快评` 给结构建议；`check <根>` 扫近几片场数，**趋同(极差≤1)即预警**。本会话实测已抓出"4 片都 14-15 场"。
- 用法：阶段① 选题后先定结构档，别默认每条都 14 场 100s。

### 40.4 ④ motion() — 语义→动作预设
- build_scenes_template 新增 `verb_to_motion(verb)` + `motion(verb, path, w, x, y, f0, f1, cx, cy)`：涨/升→rise、降/沉→sink、塞/进→fly、抄/拼/组装→assemble、缠/绕/锁→orbit、砸/立→slam、分/岔→split、转/竞赛→spin、爆/亮→pop。
- 让"演语义"从"逐帧手摆"变成"给动词出配方"，减少方向反/漏演的老错。词级仍到短语级(真词级需 forced alignment，列为后续)。

### 40.5 V3.5 新流程顺序
选题→**structure_plan 定档**→重构稿+审稿→TTS→**word_timing**→SUT→素材(空舞台+make_shapes)→**build_scenes 用 motion()/pf()**→split_beats→门禁→**produce.py 一键成片**→**clutter_check 定标**→交付。


## 41. V3.6 丰富度下限硬门禁（2026-09-11，治"越做越薄"）

**事故**：P1→P5 每场图层 7.7→7.5→5.1→4.3→3.7 一路下滑，用户肉眼发现"变少了"。
**根因（诚实）**：① 我把"跑得快/门禁全绿"当目标，"画面满不满"丢了；② qa/layout/preflight 只查**对不对**不查**满不满**；③ 我做的 clutter_check 只设上限防"太挤"、没设下限防"太空"；④ motion() 一次一层，我调用越来越少；⑤ 把"快评"错当成"每场也要薄"。本质违反工作流铁律"红线靠机制不靠人盯"——丰富度只靠我自觉，一偷懒就退化。

**治本（把下限做成机制）**：
1. `preflight_v6` 新增**元素下限**：每场 `len(layers) < MIN_LAYERS(默认6)` → **FAIL block 渲染**。环境变量 `MIN_LAYERS` 可调。
2. `clutter_check` 新增**偏空下限**：某场 grid_fill 或 edge 相对本片中位数 <0.6× → 报"偏空——元素太少"。
3. 原则**"快评≠薄"**：快评=更少场、更短时长、**每场照样堆满**（主体+2-3配角+双卡+彩屑+camera+burst），不是每场都空。
4. build_scenes 每场默认目标 **≥7 元素**；motion() 只出一个图层，**必须多调用**堆够。

**验证**：P5 按此重做 3.7→8.2 图层/场，qa_deliver 7/7、clutter 0 过载/0 偏空、画面饱满。
**教训入 §37.4 复盘 checklist**：每片交付后必查"每场元素数是否≥6、clutter 有无偏空"，防退化。


## 42. V3.6 编排器补全（A+B，2026-09-11）
把流程真正自动化到底，人只做"核实/创意/审稿"三件机器替不了的事。
- **A. produce.py 补全**：① 编码 `run_retry`(偶发 WinError/失败自动重试一次)；② `qa/events.json` 存在则用手放 EVENTS(更贴语义)，否则自动 swish/pop；③ 收尾自动跑 `clutter_check`(双向)。至此 produce.py = gen_transitions→splice→check_ratio→mix→encode→qa→clutter 一条命令。
- **B. pipeline.py 审稿前编排**：
  - `pipeline.py setup --root <工作区> --name productionN --copy 文案.txt --energy 标准 [--genre knowledge]`：建骨架(含 confetti 预置)+存文案+detect_genre+structure_plan 建议；**然后人做**：联网核实→写 chunks/palette/BRIEF→交审稿。
  - `pipeline.py tts <项目>`：审稿通过后一键 TTS+word_timing+asr_spotcheck；**然后人做**：SUT+build_scenes(motion/pf,每场≥7元素)→produce.py。
- **一条片的人机分工**：pipeline setup →【人:核实+重构稿+审稿】→ pipeline tts →【人:SUT+场景】→ produce.py →【人:看 clutter/蒙太奇定标】→ 交付+§37.4复盘。


## 43. V3.7 风格提示词库（2026-09-11，"文生图风格=最高杠杆换视觉皮肤"落地）
- 认知: 视频风格=三层(美术风格[文生图提示词] + 动效[build_scenes] + 版式[卡片]), 提示词管第一层、最高性价比但非全部。
- 五维选型(①流量②精选契合③配主题+语音④视觉动效⑤**新颖差异**); 关键: 高流量常=高同质, 精选奖励差异+真实+去AI批量感, 故⑤权重压。
- 库: `scripts/style_presets.py` + `references/style-presets.md`。**6 主风格**(剪纸拼贴/国潮水墨×信息可视化/白板手绘/等距2.5D/漫画网点/浮世绘工笔)+1 贯穿层(醒目动态字体)+复古报纸(谨慎,易画乱字)。proven 锚点经 gptprompts isometric/ink-wash/paper-craft + Ben-Day/ukiyo-e 指南校准。选题映射: 商业→剪纸、科技架构→等距、时事冲突→漫画、人文历史→浮世绘/水墨、科普原理→白板。每套=锚点词块+OKLCH配色+动效配套+去AI感清单+反差池。
- **默认机制"反差混搭"**: 每片选主风格后强制叠加1个反差元素(古今/手绘×高精/水墨×霓虹/剪纸×故障), novelty_meter记录——直接制造惊喜感、对冲同质。
- 管线约束: 忌大渐变/深色/含文字风(洋红抠图翻车); 四套均规避。每片仍过 palette_oklch check。
- 已劝退: 扁平MG/3D黏土(新颖垫底=同质)、玻璃拟态/赛博霓虹(AI批量感+抠图难)。
- 用法(代码级已接): `pipeline setup --style <风格>` 自动建 palette.json; 生图 `gen_assets jobs.json --style <风格>` 自动追加 proven 锚点词块; `style_presets get/suffix <风格>` 手动查。三套 proven token 经 gptprompts/risograph/whiteboard 指南校准(禁 beautiful/8K 空泛词)。


## 44. V3.8 首选三套"套件化"+ 混搭机制（2026-09-11）
用户六宫格验货后钦定首选:**等距2.5D(第1) > 白板手绘 / 漫画网点(第2)**。三套从"只给锚点"升级为**完整套件**(加硬 proven 锚点 + 抠图策略 + 动效套件 + 配色 + 去AI感 + 反差池 + 可混搭),`style_presets get <风格>` 可查。
- 加硬锚点: 等距+axonometric/flat-shading/soft-contact-shadows; 白板+sketchnote/visual-note-taking/educational-diagram; 漫画+Roy Lichtenstein/Ben-Day registration dots/speech bubble。
- 抠图要点: 漫画(粗黑边平涂,最好抠) > 等距(matte平涂避大渐变,投影交渲染器) > 白板(细线易丢→粗笔画或PIL矢量画)。
- **混搭机制 `blend 主 副`（V3.9 已可执行）**: 主风格定背景美术, 副风格定前景叠加元素(道具/字卡)的语言与动效, 配色取主 → 层次反差造惊喜。**执行法**: 背景 jobs 用 `--style 主`、前景道具 jobs 用 `--style 副`(gen_assets 支持逐 job `style` 字段); 或 `pipeline setup --style 主/副` 一次记录两套。例: 漫画网点背景 × 等距前景道具; 白板底 × 等距小道具。
- **教训(production6)**: 曾声称 blend 却实际全用单风格——打印配方 ≠ 真混用。以后凡"混搭"必须落到"背景主/前景副"两套 gen_assets 生成, 不能只跑一次 --style。
- 选题→首选: 科技架构/系统/流程→等距2.5D; 时事/冲突/争议→漫画网点; 科普/原理/方法→白板手绘; 商业/人文→剪纸/水墨/浮世绘兜底。
- **高饱和风格(漫画网点/波普)编码 eq 饱和降到 1.08**(默认1.14会把三原色推太艳+撑大 qa ⑤ 回抽色差超5致误FAIL); qa ⑤ 用饱和后成片比未饱和源PNG, 是已知度量偏差(待改比亮度/匹配饱和)。

## §45 production7 复盘（V3.10：一键成片两处坑机制化 + 系列续集法）

- **坑1 produce.py 编码缺 `-start_number 1`（已修）**：splice_frames 产出的 `frames/frame_*.png` 是 **1 基**（frame_0001 起），而 ffmpeg image2 解包器默认 start_number=0 会找 frame_0000.png → "No such file" → 编码三次失败中止。修复：produce.py 编码命令加 `-start_number 1`。**教训**：run_retry 只在成功时打印 tail，失败时吞掉 ffmpeg stderr，导致"多次失败"看不出根因——排错时直接手敲编码命令看真实报错。
- **坑2 硬编码饱和不可配（已修）**：produce.py 曾写死 `eq=saturation=1.14`，与 §44"高饱和风格用 1.08"冲突。改为读环境变量 `EQ_SAT`（默认 1.14）：`EQ_SAT=1.08 py produce.py <proj> --skip-render --at 12`。把"每片手选饱和"变成"一条 env 传参"。
- **坑3 ip_host() 路径双前缀（用法）**：`build_scenes_template.ip_host(png,...)` 内部拼 `assets/source/ip_{png}.png`，故 png 参数传 **`host_wave`**（→ ip_host_wave.png），**不能**传 `ip_host_wave`（→ ip_ip_host_wave.png 未登记 preflight FAIL）。
- **系列续集法（production6→7 实践）**：同一热点多幕连载时——① 主风格/配色沿用前作做"系列视觉签名"(palette_ledger 允许系列呼应，靠副风格+IP+新视角造差异，非千篇一律)；② 开场"昨天封面回放卡 + 24h 剧情反转"承接；③ CTA"去主页两条连着看"闭环导流；④ 骨架必须与前作不同(p6 对比式 → p7 层递式)。
- **审稿口径(时事类)**：外媒原话统一标「据公开报道」；股市数字标日期且用"一度/盘中"对冲快照分歧(不同源盘前/夜盘 % 会漂)；把"负面势力"等演绎词改回外媒原文"阴谋"；观点框架(三层博弈等)明确标"分析/演绎"不伪装硬事实。
- **深度档长度**（**V3.21 后重写**）：~~用 `check_script --info-pts 20 --max-chars 560 --max-chars-hard 600` 放开 knowledge 默认 14 点/414 字硬门~~ —— 默认**已无**字数/信息点硬门可放，该行在 V3.21 后照抄会以为"还有 414 字上限要申请放开"。现在深度档只管场数节奏（`structure_plan` 的 15-18 场是防趋同参考，不是配额），文案多长就多长。`--max-chars/--info-pts` 等参数仍保留，用途是**人主动临时套预算**（如客户要求 60s 硬顶），不是绕过门禁。场景帧数一律 `ceil(旁白×30×1.03)` 留 1.02 时间轴安全余量，勿写死 1.0×。

## §46 production8 质量基线（V3.11：用户钦定新标杆，后续不得低于）

> 2026-09-16 用户明确 production8（AI 智能体手机）是其**目前最满意**的一条，定为硬基线：以后每条"内容效果+质量+视觉效果"不得低于 p8。以下为 p8 达标要素，逐条可机检/可对照。

- **密度基线**：每场 **7–8 图层**（preflight_v6 `MIN_LAYERS` 默认已从 6 提到 **7**）；clutter_check 目标 **0 过载 + 0 偏空/偏忙**（p8 达成，p7 有 1 偏空=未达基线）。
- **逐句演出**：semantic_check A 级单元 **100%**（p8 44/44），每个语义单元配"演语义"的道具动作，不是居中卡淡入。
- **词级卡点**：字卡/道具触发帧一律走 `pf(TIMING, chunk, 短语)`，说到那句才出现。
- **数字获得感**：关键数字（价格/预约/跌幅）用 `make_countup` 帧序列滚动到位（p8: 36万 / 4500 / 3万台）。
- **真·风格混搭**：主风格定背景、副风格定前景道具，**落到两套 gen_assets**（背景 `--style 主` + 前景 job `style:副`），打印配方≠真混用（§44 教训）；配色取主、跨片 ΔE≥0.08（palette_oklch 校验）。
- **骨架去趋同**：连续两片不同骨架（p7 层递式 → p8 对比式）；structure_plan 判档后按档分场，不硬凑/硬砍。
- **强事实核实（时事/产品类红线）**：多源交叉；**警惕代际/时间线混淆**（一代翻车史被安到二代头上）、价格是否对应正确机型、"全球首款"等绝对化宣传词改"号称/官方称"、未证实数字标"以官方为准"或删；观点框架标"分析/演绎"。**审稿硬门：这些改动须经用户确认才进 TTS。**
- **编码**：高饱和风格(漫画网点/波普) `EQ_SAT=1.08`；等距/白板等冷色默认 1.14。produce.py 已带 `-start_number 1`（§45）。
- **交付口径**：1080×1440 / 30fps / H.264+AAC / 混音 -14.5 LUFS·TruePeak≤-1.0 / qa_deliver 7/7。
- 复刻 p8 的最省力路径：直接以 `production8/` 为模板（build_scenes.py 的场景写法、make_cards/make_extra_shapes 的 PIL 符号、jobs_bg+jobs_props 的主副双风格清单）照抄改写。
- **工作区约定（2026-09-16 清理后）**：production1–7 已删，**production8 为唯一留存样例=下限参考模板**，新片照它改写。IP 讲书人素材统一放 **`ip_assets/`**（ref_photo/setting_board/三姿态剪纸），`ip_registry.json` 已指向此处——删旧片不再丢用户照片；便携包 v3.12 已含 ip_assets。metaphors.json/palettes.json 保留 p1–7 历史条目（供跨片防撞车/撞色），不随目录删除。

## §47 V3.12 动画+视觉升级（p8 定为地板后继续抬天花板）

> 用户 2026-09-16：p8 是"最满意的一条"=**地板**，且"动画+视觉"要持续优化。四项引擎级升级，全部**向后兼容**（旧场景重渲逐字节不变，回归 0 差异已实测；`ImageDraw` 画波带/爆裂是替换非叠加，故视差双平面路径仅在 `parallax` 存在时启用，默认路径不碰）。

- **① 多平面视差背景**：`scene(..., parallax=(bg_depth, fg_depth), cam_pan=(dx, dy))`。原理：图层/特效画到透明前景层，末尾对背景层施加 `cam*bg_depth`、前景层 `cam*fg_depth`（如 0.5 / 1.0），相机平移时远景慢、近景快 → 2.5D 纵深。**要点**：视差靠**相机平移**产生，纯缩放无效果；`cam_pan` 给 ±40~80px 缓漂即可；长场景 split_beats 注入的 ±34 平移会自动吃到视差。bg 需 `scale≥1.25` 留平移余量防露边。
- **② 增强动效库**（build_scenes_template）：
  - `slam_squash(path,w,x,y,f0)`：坠落→落地**挤压**(scale_y 0.76/scale_x 1.20)→**拉伸回弹**(0.90/1.14)→定住。给"砸/落/盖章"类道具重量感，替代匀速 drop_in。
  - `pop_spring(path,w,x,y,f0,f1)`：弹入过冲 + 回弹二次运动（ease-out-back→ease-spring）。比 pop 多一点"活"。
  - `fly_blur(path,w,x0,y0,x1,y1,f0,dur)`：高速飞入带**运动模糊**拖影（方向=帧间速度矢量，`min_speed` 以下不糊、落定不糊）。
  - 渲染器新字段：图层 keyframe 可带 `scale_x/scale_y`（非等比，缺省=等比不变）；图层可带 `motion_blur:{samples,min_speed}`。
- **③ animatic 预览门** `animatic.py <项目> [--step 8 --scale 0.35]`：全量渲染前低清跳帧快渲每场，出 `qa/animatic/filmstrip.png`（每场一条时间带）+ `preview.mp4`（低帧率快览动效节奏）。**流程位置**：build_scenes→split_beats→preflight→layout→**animatic 目检**→render_all 全量。省时防翻车（p8 全量 561s，animatic 仅数十秒）。非门禁，不阻断。渲染器加 `--step`（跳帧，真省算力）/`--scale`（降采样）。
- **④ 审美视觉 QC** `aesthetic_check.py <项目>`：补此前所有 gate 只测下限、不测"美"的盲区。每场抽 3 帧算五分项→0–100：构图平衡(边缘视觉重量左右/上下)、主体突出(显著像素占比+峰值集中)、留白密度(近边 ink，理想 0.02–0.07)、色彩和谐(采样贴合 palette 比例+高饱和色相是否打架)、对齐(图层落点公共轴比例)。出 `qa/aesthetic-report.json` + `aesthetic_montage.png`。**报告级非硬门**（审美主观），但给"低于基线"的场亮黄灯。**p8 实测均分 73.9/100（最低 S10 56.9）= 新基线参考**；已接入 produce.py 末尾自动出报告。
- **回归纪律**：改渲染器必做"旧场景重渲逐像素 diff=0"（本会话用 p8 S01 336 帧抽样 26 帧比对，max delta 0 才继续）。
- **MIN_LAYERS 6→7**：preflight 元素下限默认提到 7，锁 p8 密度地板。
- 用法建议：下一条片起，主视觉尽量上"视差 + 至少 1 个 slam_squash/fly_blur"，渲前跑 animatic、渲后看 aesthetic 分，逐片把均分往 73.9 之上推。

## §48 production9 复盘（V3.13：审美代理去风格偏置 + produce 路径 bug + 双版本对比法）

- **审美代理指标的风格偏置（真 bug，已修）**：aesthetic_check 首版用**绝对阈值**判"留白"（fill>0.07=拥挤）、用"贴合 palette.json 4 色"判"色彩和谐"。结果**漫画网点/波普等满底放射线风格被系统性低估**——p9 漫画风首测 64.2，远低于 p8 等距冷底的 73.9，但画面其实不差。修正为**风格无关**：①留白改**相对本片中位数**且**只单向罚拥挤**（fr>1.5 才罚，清爽不罚——整洁不是缺点）；②和谐改**色相集中度**（片内主导高饱和色族数相对中位数，越少越协调），**不再要求贴合 4 色 palette**（多色风格不误伤）。修后 p9 v1=82.0。**教训**：跨风格可比的指标必须归一到"片内相对/风格基线"，不能用偏爱极简风的绝对值。
- **⚠ 基线重标**：p8 的 73.9 是**旧指标**测的，新指标下会不同（p8 帧已删，需重渲才能重测）。**新可比基线**：p9 v1/v2 在 V3.13 公平指标下 = **82.0 / 82.3**。以后以"同指标跨片"为准比较。
- **produce.py 路径 bug（已修）**：加 aesthetic 步骤时误写 `str(proj / "output" + "/final.mp4")`——`WindowsPath + str` 抛 TypeError（成片已编码、qa/clutter/aesthetic 都跑完，只最后打印崩）。改回 `proj / "output" / "final.mp4"`。**教训**：改脚本收尾行也要跑一遍冒烟，别只测新步骤。
- **`_pad` 补层的拥挤副作用**：V3.12 用 `_pad` 给 <7 层场景补角标星/闪电保密度地板，但落在**边框带**会抬高"留白"edge 值。B 优化=缩小(110→82)+移到非边缘空位(300/780,360/540)。**教训**：为过地板补的元素要放"空位+小尺寸"，别制造新拥挤。
- **双版本对比法（用户偏好）**：改动幅度大/不确定时，保留 v1 命名件、另出 v2，两版并排给用户对比再定夺——比单版交付更稳。命名规范：`final_<主题>.mp4`(v1) / `final_<主题>_v2.mp4`。**两条铁律**：①**两版中性交付，agent 不替用户推荐用哪版**——用户自己播放按发布效果选更优的；②**v2 必须是"当前源码可复现"的那版**（改了 build_scenes 就重渲出 v2，让选定版与源码一致，别留一个源码已产不出的旧版）；③若 B 只是边角微调、C 只改打分工具（不碰画面），要如实说明"两版画面几乎无差"，不为凑对比制造"看起来有两个版本"的错觉。
- **ip_host 双前缀坑复现**：p9 又写成 `ip_host("ip_host_point")`→`ip_ip_host_point.png` 未登记。参数只传 `host_point`（模板内部已拼 `ip_`）。已 §45 记过，仍踩——**下次直接照抄 p8 的 `host_present/host_wave/host_point`**。
- **时事/科技核实再证**：p9"韬(τ)定律"我一度疑心杜撰，查证=真实（何庭波团队提出）；但纠出"全系搭载"（实为 Pro/RS 首发）、"功耗66%"（实 NPU66/GPU58）、"对标18A/3nm"（媒体解读）三处口径。**结论**：可疑名词先查再判，别凭印象否掉，也别照单全收。

## §49 production10 复盘（V3.14：StepFun step_plan 通道 + TTS 新格式 + 管线三坑 + AIGC 角标进渲染）

> p10《现在都烫，iPhone Duo 明年夏天怎么办》成片 `final_iPhoneDuo过热_明年夏天.mp4`（1080×1440/30fps/2′12″，qa_deliver 7/7、审美均分 83.0 > 公平基线 82.0、clutter 0 过载 1 偏忙）。主=白板手绘背景 × 副=漫画网点道具真混搭。复盘 7 条：

- **① StepFun 扣费通道看 Base URL，不看 key**：`https://api.stepfun.com/step_plan/v1` 走 Step Plan 订阅额度（token plan），`https://api.stepfun.com/v1` 走按量余额。工作区 `.env` 已配 `step_plan/v1` + 完整有效 key，chat/TTS/生图/ASR 全走订阅、不扣按量。截图里 key 打码 ≠ `.env` 里 key 不完整，**别去猜/重录 key**（猜出来的必 401）。
- **② stepaudio-2.5-tts 的正确 payload 是顶层字段**：`{"model":"stepaudio-2.5-tts","voice":"cixingnansheng","input":"…","instruction":"…"}`，返回 `audio/mpeg` 原始字节直接写 mp3。旧 step-tts 的 `parameters.voice_type`+`instructions` 嵌套格式 StepFun 认不出 → 掉按量 → **假报 "Insufficient balance 0.00 yuan"**（本会话差点误判成"要充值"）。stepaudio 不吃数值 speed，语速靠 instruction 自然语言控制。
- **③ ⚠ `pipeline tts` 会把 `chunks.json` 重置回占位**：改稿后别经 `pipeline tts`（它覆盖你写的 chunks），直接跑项目 `generate_tts.py`。
- **④ ⚠ 抠图道具必须并入 `assets/source/`**：渲染器 `SRC_DIR` 找 `assets/source/`，只放 `assets/cutout/` 会 preflight 账本 FAIL。cutout 后 `cp assets/cutout/prop_*.png assets/source/` 再 `register_assets`。
- **⑤ `style_presets` 键名精确**：`--style 漫画网点`（不是 list 显示的 `漫画网点pop-art`，`pop-art` 只是别名后缀，`suffix()` 用精确 key 会 KeyError）。
- **⑥ 长场换式（>600f）**：preflight 要求存在一个**关键帧≥6 且 x/scale 带方向反转**的贯穿动效层，入场即静止的层不算。用 `drift_layer(png,w,[(frame,x,y,scale,rot,op)×6+])` 手写 kf 满足。
- **⑦【已作废·反转】成片不加任何「AI 生成」角标**：用户 2026-09-18 明确——发布端自带平台 AI 标签，Agent 交付画面保持干净。旧"角标进 build_scenes 常驻层"作废（详见 §50④）。
- 通用：本机 `python`/`py -3.12` 是 WindowsApps 桩(exit49)，跑脚本一律 `py -3.14`。

## §50 production10 重做复盘（V3.15：旁白 concat 混音根治"两个配音" + 白板降亮防爆闪 + 去 AI 角标）

> 用户反馈成片"两个配音/重复语音"，删库重做。根因与修复：

- **① 旁白混音必须 concat 顺序拼接（根治"两个配音"）**：`mix_audio4.py` 原用 `adelay+amix` 把 8 段旁白叠加。stepaudio 每段时长有波动，某段溢出到下一段场景槽 → amix 把两段同时混 = 两个声音叠着说。**单段 ASR 查不出**（每段自身干净），只有整条成片 ASR 通读或耳朵能发现。修复：每段 `apad=whole_dur=<场景槽时长>`(下一段起点−本段起点) 补静音到不重叠，再 `concat` 顺序拼接 → 物理上不可能叠加。
- **② 交付前必做整条成片音频 ASR 复核**：produce 出片后、present 前，把成片音频提取整条 ASR，逐字比对 = 各段文案顺序拼接、无重复句/双声，通过才交付。
- **③ 白板/高亮背景降亮防爆闪**：白板手绘 bg L0.95 近纯白，元素稀疏帧（长场开头旁白未入场段）灰度 mean>235 → qa_deliver 判"爆闪" HARD 中止。修复：bg png 用 `PIL ImageEnhance.Brightness(im).enhance(0.85)` 降亮(248→211)，既过爆闪门又更像纸质手绘。
- **④ 成片不加任何「AI 生成」角标**：用户发布自带平台 AI 标签，交付画面保持干净（覆盖 §49⑦ 旧规定）。
- **⑤ stepaudio-2.5-tts 顶层 speed 生效**：两档 build=1.15 / 其余=1.1（`parameters.speed` 嵌套无效）。
- **⑥ 后处理 ffmpeg 命令别混 rm**：`rm 相对路径/中文名` 会被工作区安全策略拦截、中断整条 `;` 链，导致 ffmpeg 输出损坏半截 mp4（moov not found）。覆盖用 `ffmpeg -y` 或 `cp -f`，不要先 rm。

## §51 production11 复盘（V3.16：红色主体抠图根治 + 道具光照契约漏写 + 中断恢复 SOP + ASR 数字归一机制化）

> p11《同门新机，一降一涨》(iPhone 18 Pro 破发 / Pro Max 加价)。11 场 / 3233 帧 / 107.8s，主=剪纸 × 副=等距2.5D（剪纸首次当主风格），C 对比式，深度档。qa_deliver 7/7、clutter 0 过载、整片 ASR PASS。双版本中性交付 v1/v2 审美 81.0/81.2。复盘 8 条：

- **① 红主体 + 粉洋红底 = 键色抠图天然失效**：StepFun 常把 `#FF00FF` 渲染成偏粉的 (200,60,140)，红主体 (230,90,85) 与键色欧氏距离仅 ≈82，正落在 t0-t1 过渡带 → 主体被吃成半透明（`--despill` 更糟，整块红消失）。**根治优先级：生成端保证纯洋红满幅 > HSV 色相带掩膜（H∈275°–350° 且 S>0.25 判背景，红/蓝/青主体全保） > 调阈值**。半透明只能靠目检棋盘图发现，`semi_edge_ratio` 会漏报。
- **② 道具 prompt 的光照契约条款不可省**：漏写 `no ground shadow` → 灰色投影与渐变底残留，抠图后成"阴影块跟着飞"。标准句式（照抄，勿简写）：`isolated on pure solid magenta #FF00FF background filling entire frame, single object, no ground shadow, main light upper-left 45deg`。**人形道具禁用大面积奶白/奶油色**（近键色易被误吃），改饱和纯色（青蓝衣 + 朱红头）。
- **③ `gen_sut_cards.py` 会覆盖设计 SUT**：它按场景 JSON 的文字卡上屏帧重建 sut.json，但把语义单元降级成 `t_xxx:t_xxx`、分级一律 A —— **丢 A/B/C 与文案，画义契约就没了**。正确用法：只把它当"实测帧追溯件"另存（如 `qa/sut_card_frames_measured.json`），设计 SUT 的帧号用 `pf(phrase_timing)` 反查校正，保持 `semantic_check` 有效。
- **④ 中断恢复 SOP（重启/断电/杀进程后）**：produce 被打断会在 `audio_build/` 留下**全零字节 wav**，而混音按"文件已存在即跳过"复用 → `Invalid data found when processing input` 静默失败。恢复动作：①盘点各 `frames_sNN` 帧数是否齐 → ②全项目扫 `st_size==0` 文件 → ③清空 `audio_build/`（纯派生，源在 `assets/audio/*.mp3`）→ ④`produce <项目> --skip-render` 续跑。
- **⑤ `split_beats` 幂等但必须在渲染前**：它按 `duration_s` 重算 `camera_motion`（同输入同输出，可安全重跑），但会就地改写场景 JSON —— 渲染后再跑会造成**帧与 JSON 错位**。正确顺序：build_scenes → split_beats → layout/preflight 复检 → render。改场重渲时只重渲变化的 `scene_sNN`（`render_sequence --overwrite`），并用 md5 比对确认其余场景 JSON 逐字节未变。
- **⑥ `asr_final_check` 数字转写假阳性已机制化**：ASR 把"十/八百"转写成"10/800"，逐字比对掉到 0.88 → 误 BLOCK。新增复核：仅当**①所有数字串数值等价**（`cn2num` 保守解析，解析不了如口语"两三百"一律不放行）**且②非数字残差本身达标**才判格式差异放行。对抗测试：八百↔800 放行；八百→900 仍 BLOCK；漏句仍 BLOCK。价格类选题必须保住这条底线。
- **⑦ 审美分数对事后调坐标不敏感，要在设计期定构图**：v1→v2 只把 s09 背景价牌 760→560、s10 三卡 790→730，均分仅 81.0→81.2，最低场 s10 77.7 纹丝不动。其"衡/齐"短板源于**三张卡同列右置**的结构，事后挪位无效 —— 下片设计期就该把"同列卡数≤2 / 卡分散到不同锚线"写进 SUT 视觉描述。
- **⑧ IP 出场帧必须早于其演出的语义帧**：`ip_host()` 有 28 帧淡入，`semantic_check` G6 按帧检查透明度。实测抓到 S10 指路牌 f27 时 IP 在 f37 才入、S11 投票箱 f108 时 IP 在 f255 —— 全部判"角色演错语义"。规则：**IP 的 f_in ≤ SUT 单元帧 − 28**。
- 通用：本机 `python`/`py -3.12` 是 WindowsApps 桩，跑脚本一律 `py -3.14`；`produce.py` 被杀后 `splice_manifest.json` 仍有效，`--skip-render` 续跑不破坏三方对齐。

## §52 production12 复盘（V3.17：--hsv 转正为暖色道具默认 + 渲染戳盲区 + 工具改动必须跑真实 CLI）

> p12《AI 工具静默上传代码？你的代码正在被整箱托运》。12 场 / 3592 帧 / **119.73s**，主=浮世绘工笔 × 副=国潮水墨，**频道首支深色底片**，A 清单式（三问提为脊柱）。qa_deliver 7/7、整片 ASR 12/12 全 1.0、clutter 0 过载、**审美 83.3（新高，> p10 83.0 > p9 82.0）**、polycheck **align 零告警**（p11 曾 20+）。复盘 6 条：

- **① `--hsv` 应从"补救"转正为暖色/红系道具的默认路径**：25 张道具 prompt **全部写全**了 `pure solid magenta #FF00FF filling entire frame` 契约，模型仍输出粉洋红底 (≈200,60,110)——浮世绘"矿物颜料/washi"倾向尤甚。结论：契约条款防的是"投影与渐变"，**防不住底色偏移**；红/橙/粉/奶白主体一律直接 `cutout_key --hsv`，键色法只留给冷色主体。本场 `--hsv` 后 semi 0.008-0.037 且逐张目检实心。
- **② 渲染戳只覆盖场景 JSON，不覆盖素材文件**（V3.16 §51④ 的残留盲区）：本场在渲染中途改了 `prop_declaration_form.png`（盖掉模型画的乱码英文），只因"该场尚未开始渲染"才侥幸一致。**规则：素材一旦进入渲染阶段即冻结**；要改就改完重渲该场。下片把资产 sha256 并入 `qa/frame_stamps/` 或在 produce 侧做资产 mtime/hash 快照比对。
- **③ 模型会在"空白纸面"道具上自作主张画字**：申报单出现乱码"CORMES PAWE"，风格锚点里的 `no text, no letters` 拦不住。修法（无需重生图）：按深色像素自动定位文字包围盒再用纸面中位色覆盖——`lum<130 & 不透明` 取 rows/cols 并集，只处理上部 35% 以保留下方横线。
- **④ 改完工具必须跑一次真实 CLI，单元级 harness 会漏**：我给 `asr_final_check` 加数字断言时，替换脚本有一处锚点未命中（`mism` 未定义），自写的对抗 harness 走的是自己拼的 decide()，**没触发真实 main()**，直到 p12 正式跑才 NameError。教训：工具改动后的验收 = 跑真项目真命令，不是跑等价单测。
- **⑤ SUT 帧号由 `pf(phrase_timing)` 生成才是正解**：本场项目内写 `gen_sut.py`，语义单元帧与 build_scenes 同源 → polycheck align **零告警**（p11 手估帧造成 20+ 条系统性偏差）。比"事后用 gen_sut_cards 校正"更干净，且保住了 A/B/C 分级与文案。
- **⑥ 深色底的门禁影响**：不触发爆闪门（mean 远低于 235），但**开头几帧易被判空白/偏空**（stddev<6 / clutter 偏空下限）——bg 要有纹理与月亮/波浪等主体，S01 首帧即放箱子+衣物。本场 clutter 0 偏空、审美反创新高，说明"浅色纸底"从来不是质量的必要条件。
- 通用：`rise/pop_spring/fly/fly_blur/climb/orbit/slam_squash` 自带 `SRC_DIR` 前缀，调用**只传裸文件名**；`prop()`/`cover_layer()` 自建路径才需要完整前缀。

## §53 两条手动教训机制化（V3.18：背景亮度硬门前移 + 整片 ASR 收进 produce 硬门）

2026-09-19 把 p10/p12 两次"事后人肉补救"变成自动门禁：

- **① `scripts/bg_luma_check.py` 背景亮度硬门**：渲染前逐场读 scene JSON 的 `background.path` PNG 灰度均值，>235 自动 `ImageEnhance.Brightness(0.85)` 降亮并复检，压不进阈值才 FAIL 拒渲（对齐 qa_deliver 爆闪门 235）。**幂等**（已降图均值<阈值，重跑零操作，不会 0.85 连乘）；`--no-fix` 只报不修、`--dim` 自定系数；报告写 `qa/bg-luma.json`。已挂进 `render_all.py` preflight_tools **第一道**（在 preflight_v6 之前）。回归：p12 十二张背景全 OK 无操作；合成 251 白底自动 DIMMED 251→213；--no-fix 正确 FAIL。
- **② `asr_final_check` 收进 `produce.py` 收尾硬门**：aesthetic_check 之后自动跑 `asr_final_check <项目> --mp4 output/final.mp4`，FAIL 则 produce 退出码非 0、不出"✅ 成片"行——p10 "两个配音"式缺陷自此**流程上不可能漏检**（以前靠人记得手动跑）。新增 `--cq-at <秒>` 透传金句独立切段、`--skip-asr` 应急逃生（默认必跑）。注意：每次 produce 会多消耗 ~N 段 ASR API 调用（step_plan 通道）。回归：p12 成片 12 段全 PASS。
- **背景太白的设计层建议不变**：门只兜底，白板手绘等浅底风格生成时仍优先在 prompt 锚点里压亮度（纸纹理/阴影线），别依赖门救。

## §54 production13 复盘（V3.19：gen_assets chdir 路径坑 + 账本前缀归一 + 门禁 WARN 处置口径）

- **① `gen_assets.py` 会 `os.chdir(jobs文件所在目录)`**：所以 `--raw-dir` 必须写**相对项目根的路径**（`assets/raw`），写成 `production13/assets/raw` 会生成嵌套目录 `production13/production13/assets/raw`，日志还全程报成功。同类坑：账本 file 字段会带上 `production13/` 前缀，preflight 账本门按 `assets/raw/...` 找 → 全部判"未登记"。**修法**：`--raw-dir assets/raw` 在 jobs 文件所在目录语义下传参；已生成则把 PNG 上移一级 + 用脚本把 ledger 里 `production13/` 前缀剥掉再跑 `register_assets.py`。
- **② `preflight_v6` 的 effects 只接受带 `start_frame` 的效果字典**：把 `fly_blur()`（返回**图层**）误塞进 `E=[...]` 会让 preflight 直接 `KeyError: 'start_frame'` 崩在半路。图层一律进 `L`，`E` 只放 `burst/motes`。
- **③ 呼吸门(R1)统一夹帧**：短场（<3s）里"说到才出"的字卡天然贴着场景末。做法：build_scenes 内包一层 `card()`，把入场帧夹到 `场景末-56f`（bounce/emph 落定约 14-20f，留 30f 呼吸）。
- **④ 门禁 WARN 处置口径（写死，免得每片重议）**：
  - `PLATFORM_CAPTION/PLATFORM_RAIL`（字卡进字幕带/右侧按钮区）= **必修**，改 y/x 或缩幅，本片全部修到 0。
  - `OCCLUDE` 若来自 `rise/slam_squash/drop_in/climb` 的**入场路径穿过字卡**（z 序字卡在上、穿过即数帧）= 设计内，可留 WARN；若来自**静止重叠**（同框常驻）= 必修。
  - `OVERLAP` 两张常驻字卡 >0.25 必修（错帧退场或换锚位）。
- **⑤ 整片 ASR 硬门在专名上的正确姿势**：StepFun ASR 会把 `Apache→阿帕奇`、`Claude→Cloud`、`魔搭→某达`、`Xing→Sing/C` 转写成同音字，逐段 spotcheck 相似度掉到 0.77-0.94 属**转写差异非错读**。处置：旁白文本改写成能读对且能转写对的中文形态（如"星辰 Xing 4.0，29B 参数"），准确型号名交给**字卡**显示，别硬改 TTS 参数。
- **⑥ 两档语速落地**：18-20 段长稿按 `build 1.15 / 其余 1.1`，实测 511-514 字 → 旁白 104-105s、成片约 110s，与 knowledge 深度档目标一致，不需要第三档。

## §55 production14 复盘（V3.20：文案自洽门 + 转写别名门 + 开场空台门）

p14《比 DeepSeek 强，比 Kimi 便宜，它来了》71.7s / 审美 **84.3（频道新高，最低场 81.1 即 11 场无短板）**。四条：

- **① `claim_check.py` 文案自洽硬门（新）**。用户说"不用核对信息"只豁免**外部事实**核查，**不豁免稿内自洽**——我在重构稿里写出"写代码还比它(Kimi)强"，而同一稿另一段是"和 Kimi K3 打平"；又把 7毛4−5毛8=1毛6 写成"便宜两毛"（虚报 25%）。两句都在稿子里，机器完全能发现，但 check_script 只管字数/长句、semantic_check 只管画义，这是门禁空白区。规则 C1 矛盾断言（同一实体既"强/领先/反超"又"打平/持平/一个水平"→FAIL）、C2 差值复算（断言"便宜X毛/贵X成/一半"且片内给了两端绝对价→复算断言）。**已接进 `pipeline tts` 成为花钱前的硬门。** 验证：RED=我 v1 真实致败两句全部拦下；GREEN=p14 v2 现稿放行；对抗=已交付的 p13 无误报。**关键教训：跨句回指代词必误报**——第一版把"它"继承成上一句的 Kimi，于是 p14 现稿被判"Kimi 又贵又便宜"假矛盾；改成只认**同句内显式出现的实体名**，宁漏不误报（门禁哭狼=被关掉）。
- **② `asr_alias.py` 转写别名归一（新）**。StepFun ASR 把 `Claude→Cloud`、`Xing→Sing`、`魔搭→某达`，旁白念对了却假 FAIL（p14 s07 86.96%）。§54⑤ 的旧处置是"改旁白去讨好检查器"——那是**牺牲口播质量换门禁绿灯**，方向错了。新方案：项目内 `qa/asr_alias.json` 显式声明变体，归一后达标才放行且**必须打印命中规则**（`✓(转写别名 cloud↔claude 它↔他)`）。三条硬约束防门禁被自己人废掉：只认声明过的、**变体必须是拉丁/数字 token**（否则有人能声明"贵→便宜"清空门禁）、放行必须可见。中文同音代词（它/她→他）走内置固定表不可扩展。RED→GREEN + 三条对抗例（型号念错仍 FAIL／数字念错仍报 `23≠22`／声明中文实词被拒）。
- **③ `first_frame_check.py` 开场空台门（新）+ 一条镜头语言规则**。我让 11 场里 10 场把白板从 scale 0 砸入 → s02/s08 开头 1-4 帧只剩裸背景，渲完 669s + 编码后才被 qa_deliver 判纯色空白帧，白烧一轮。**规则：舞台元素（白板/桌面/墙面）是持续存在的，第 0 帧即满不透明、只保留挤压回弹定住；只有全片第一次登场才值得从 scale 0 砸入。** 冷开场要空台就得在场景 JSON 里显式声明 `intro_empty_ok: N`，不许门自动放过第 1 场。
- **④ 弱代理门宁可不写（本门自己的踩坑实录）。** 第一版用"背景 PNG 的灰度 std"当阈值判据 → 源图 40.9 全绿而 qa_deliver 实测 5.5；第二版改成"渲真帧测 54×72 缩略 std"仍假阴性——**PNG 层面的 std 预测不了解码后的 std**（4:2:0 色度抽样 + 饱和滤镜会再抹平）。结论：这条路径根本不该猜阈值，最后落成确定性结构判据（第 0 帧有没有不透明图层在场）。**一个会说 PASS 的假门比没有门更糟**——它让人跳过真正的人工目检。
- **⑤ 其他机制化**：`register_assets.py` 不扫 `assets/lines/`（白板标注层被判"未登记"）→ 已纳入；`gen_assets` 的 `name` 带子目录会在**已扣费拿到图之后**写盘崩溃 → 补 `out.parent.mkdir`；**标注层必须与文字卡分目录**，因为 `layout_check` 按 `path.startswith("assets/text/")` 认卡，混放会让 DENSITY 冒出 41 条假告警（s04 单场 31 条）。
- **⑥ 预设库的隐性撞色**：`style_presets get 白板手绘` 给出的四色与账本里 **p10 完全同一组**（#F8F8F4/#1E2228/#146EBE/#DC463C）——预设把某片历史配色固化了，照抄必撞。已改判：主风格=漫画网点深紫场、白板降为叠加语言，配色 `#2B2140/#F2EAD8/#3CB4FF/#B0E23C`，与近三片相似度 42-55%（对照：已交付的 p12 与 p13 互相 72%）。
- **⑦ 字数上限与时长目标是数学冲突，不是我的取舍失误**：R1 字数上限按 220 字/分推导，但两档 speed(1.1/1.15) 实测 **4.90 字/秒 ≈ 294 字/分**（p13/p14 双点校准一致）→ 同一份稿子不可能既守 product 档 360 字、又坐进 80~100s。p13 的处置是放宽到 620 字（审美随之 83.3→78.3）。本片选**守字数**、时长做在下沿（71.7s）。**待用户裁决是否修订各 genre 的字数区间或改用时长按。**

## §56 规范变更 V3.21：取消字数与时长门禁（用户裁定）

p14 交付后暴露的是**规范自身的矛盾**，不是执行失误。R1 的字数上限按 220 字/分推导（310~360 字 → 86~94s 旁白），但两档 speed 实测 **4.90 字/秒（1.1）/ 5.15（1.15）≈ 294~309 字/分**（p13、p14 双点校准一致）。同一份稿子**不可能既守 genre 的字数上限、又坐进它的时长区间**：p13 放宽字数换时长（审美 83.3→78.3），p14 守字数把时长压到 71.7s（落 80~100s 下沿，审美 84.3）。两条路都在拿质量换合规，说明错的是规则。

用户裁定（2026-09-20）：**不限字数、不限时长，以用户给的文案为准；配音速度保持两档 1.1 / 1.15。**

落地：
- `check_script` 默认不再套 `min_chars/max_chars/max_chars_hard/max_info`。需要临时套预算显式传 `--max-chars/--min-chars/--info-pts`。**V3.22 追加**：`GENRE_LIMITS` 里那四个预算字段已**整段删除**（留着就是下一任调用方把字数门装回来的入口），genre 现在只提供 CTA 措辞与广告法开关；`MAX_CHARS/MIN_CHARS/MAX_INFO_PTS` 常量同删。
- 曾加过一个 `--use-genre-budget` 开关，因它并不能真正还原旧判据（R3 已从 error 降为 warn）而**删除**——不留名不副实的兼容开关。
- **保留**：R4 单句 ≤45 字（拆不过就断句加停顿）、R3 单段 >60 字提示、R2 骨架与 CTA 机检、R5 语言质地、R6 音效 ≤20（**V3.22 校正**：本行曾误记 18；代码 `mix_audio4` 断言、`produce` 截断、SKILL R6 行一致为 20）。这些是「读不读得懂」与「认知噪音预算」，与片长无关。
- 阶段① 职责改写：**只做分段与标点，不删内容**；照旧报预计成片时长，长就长。
- **副作用待观察**：长文案出长片后，`clutter`/`polycheck` 的节奏阈值是否需要同步放宽，以及完播表现。**下一片起留意并回记本节。**（→ 节奏阈值一项已在 §57④ 用五片回放数据解决；完播表现仍待观察。）

## §57 V3.22 全量工作流审查（2026-09-20，p14 交付后用户令"全面审查、修 bug、重打便携包"）

审查方法记在第一位，因为它决定了这一节哪些结论是**测出来的**、哪些是**猜的**：
- 有效手段：① `compileall` + 逐脚本 `--help` 冒烟；② 拿**空项目目录**当探针打每个门禁，看谁吐 traceback、谁假 PASS；③ 拿 p10–p14 **五部已交付片**回放每个门禁，用"好片不该被告警"当判据；④ 读编排器调用点核对门禁真接线。
- **无效手段（本轮实录，务必记住）**：派 subagent 做"给我列缺陷"式审查。两个 agent 交回来的报告里，`pipeline tts` 把花钱前硬门放到 TTS 之后、`--probe` 参数是空壳、`word_timing --mp3-dir` 与 `asr_final_check` 重叠判据、`preflight` 把 background 计入元素下限 —— **这五条在本仓库代码里根本不存在**（`pipeline.py:71-81` 硬门就在 TTS 前；全仓库无 `--probe`；所有门禁统一 glob `scene_s*.json`；下限只数 `layers`）。行号也是编的（文件才 103 行，报告写 129/131/140）。**结论：agent 的清单只能当"待验证假设"，每条必须自己 `grep`/`sed` 复现才允许动手。** 反过来 empirical 探针（②③）没有一条误报。

### ① 花钱前的硬门不硬（本轮最严重）
`pipeline.run()` 写死 `if r.returncode not in (0, 1)` 注释"1 可能是 WARN 级, 交人判读"。但 `check_script`/`claim_check`/`asr_spotcheck` 的 **FAIL 恰好就是 rc=1**（PASS/WARN 都是 0）。后果：文案机检 FAIL，TTS 照跑、钱照扣，p14 之前一直如此。同时 `detect_genre` 的低置信度提示用 rc=2，反而把已经建好骨架的 `pipeline setup` 直接打死。
- 修：`run(cmd, what, allow=(0,))` —— 默认非 0 即中止；只有 advisory 步骤显式放宽（`detect_genre` 传 `allow=(0, 2)`）。**新加门禁进编排器时，别再依赖"rc=1 当警告"的旧习惯。**

### ② 建了没接线的门 = 没有门
`first_frame_check.py` 是 V3.20 为 p14"渲完 669s + 编码完才被 qa_deliver 判空白帧"专门写的秒级门，SKILL 写着"已挂 render_all preflight"，**代码里 `render_all` 的门禁清单根本没有它**（全仓库零调用点）。同函数的查找逻辑 `for sub in ("scripts","..","../scripts")` 还有两个坑：全不存在时**静默少跑一道门**、仓库根那份陈旧副本会**遮蔽** `scripts/` 新版。
- 修：`first_frame_check` 挂进渲前链首位；查找改单一 `HERE/tool`，**缺文件即拒渲**（"缺门"比"没过门"更危险）。渲前链现为 first_frame → bg_luma → preflight_v6 → check_timeline_ratio → layout。

### ③ `produce --skip-render` 是全门禁旁路
§51④ 的中断恢复 SOP 指定用 `--skip-render`，但该分支只跑 `verify_frames_match_scenes()`——它比的是场景 JSON 的 sha256，**看不见资产被换过、背景没降亮、字卡出画**（正是 V3.17② 渲染期冻结素材的盲区）。
- 修：复用旧帧前把四道渲前门按同口径重跑一遍（`bg_luma_check --no-fix`，只报不修，免得在已有帧之下改 PNG 造成新的不一致）。

### ④ 运动密度门无判别力（"弱代理门"再现，用五片数据定性）
`polycheck density = 动画层数 / 场景秒数`，绝对上限 1.2 层/s。分母是**场景时长** → 场切得越短分越高，它量的是"这场多短"不是"这屏多挤"（挤不挤由 `clutter_check` 按像素判，那把才是好尺子）。五片回放：p10(83.0) **0** 告警、p14(84.3 频道新高) **8/11 假告警**、p13(78.3 最低) 17/20 —— 同为好片的 p10/p14 差 8 倍，阈值毫无判别力；且 `tail` 算出**负数**（p10 s01 = -3.2s）只当怪数打印，把"关键帧越过场景末、切点仍在运动中"这个真问题藏了。
- 修：上限改 `max(1.2, 本片中位数 × 1.6)`（同 §V3.13 `aesthetic_check` 去风格偏置的思路：绝对阈值跨片不成立就用片内相对）；负尾段 < -0.5s 变成真告警。同五片回放 → p12/p14 **0**、p10 1（那条正是 s01 关键帧越界 3.2s 的真发现）、p13 8。**告警终于落在该落的那部片上。**
- 通用判据（写死）：**任何"分数型"门禁上线路径 = 拿历史已交付片回放，把"频道最好的片子不该红、最差的片子必须红"当验收；做不到就不如不写。** 参见 §55④（PNG std 预测不了解码 std 的假门）。

### ⑤ 缺输入即崩栈 / 空目录假 PASS
`claim_check`、`polycheck_v66`(两处)、`gen_sut_cards` 缺 `chunks.json` 吐 traceback；`clutter_check` 无帧时走到 PIL `cannot write empty image`；`palette_ledger check` 传 1~3 个色值 `IndexError`（旧版只挡 0 个）；`preflight_v6` 在"图层误塞 effects"已知之后仍对 list 调 `.get()`；**`first_frame_check` 项目路径写错、零场景时打印 PASS**（空目录骗人）。
- 全修成干净 FAIL + rc=1。另：`mix_audio4.py` 是"复制到项目根再跑"的模板，`ROOT = __file__.parent`，在技能 `scripts/` 下直接调用会往**技能目录**写 `audio_build/`（本轮 `--help` 冒烟就中招，顺手清掉），已加模板守卫。

### ⑥ V3.21 口径清账（上一版决定没铺到所有落点）
- `check_script` 的 PASS 行原本写"R1/R3/R4 机检通过"——R1/R3 默认根本没跑，**门禁在报告里说自己查了没查的东西**；打印行还留 `(封顶 None)`。现改为按实测语速打印**预计旁白/成片时长**（p14：预估 72.3s vs 实测 71.667s，差 0.9%，两档折算口径可用），PASS 行列真跑过的规则。
- `structure_plan recommend` 原样输出"建议 12-14 场、成片 90-100s"——字数不设限后这句必然与真实片长打架，读起来像配额。改为"结构参考 12-14 场(防趋同用, 不是配额) + 预计成片约 Xs"。
- `check_timeline_ratio` 的修法提示含"砍该段例证"，V3.21 不许砍文案 → 只剩"扩该场景帧数"一条合法出路。
- `assemble_audio` 自动铺音效按 `n = len(narration)` **无上限**：长稿（≥21 段）合法后必然撞 `mix_audio4` 的 R6 断言让混音整步崩掉。现封顶 20 且**全片均匀铺点**（旧写法会只铺前 20 段、长片后半程光秃）。顺带清账：R6 预算代码 20 / 我 V3.21 文档写 18 —— 统一回 **20**。

### ⑦ 本轮同时确认没问题的（避免下轮重复怀疑）
两份脚本副本（工作区 `scripts/` 与安装副本）逐文件比对除 `references/vendor-migration-plan.md` 未同步外**零漂移**；`test_render_sequence` / `test_layout_parity` 全绿；p14 全门禁重跑复现 **84.3**、qa_deliver 七断言 PASS、`audio_duration` 全仓库唯一时长源未破功（剩余 ffprobe 直调只在 `asr_final_check` 取流探测，可接受）。

### ⑧ 遗留（未做，理由记下）
- `first_frame_check` 只断言"第 0 帧有不透明图层"，**不判"主体是否够突出"**——p14 的审美瓶颈仍在 salience/align，那要靠设计不靠门（见 MEMORY）。
- 8 处 `mkdir(exist_ok=True)` 缺 `parents=True`、`env_paths.py:26` 硬编码用户目录、`lcs_ratio/norm` 四份实现、`clutter_check` 顶部死常量 —— 都属"能跑对但不干净"，本轮不改以免动刀过大；等真踩到再收。
- 完播率对长片的影响：V3.21 之后才有的变量，下一片发数据回来记 §56 本节。

## §58 production15 复盘（V3.23：七条工具级静默失效，全部由"一场多 chunk"和"渲染器读键名"暴露）

p15《不用抠图了！阿里开源生图模型免费》87.3s / 15 场 / 17 chunk / 423 字，审美 **83.1**（最低场 73.8），qa_deliver 七断言 PASS，整片 ASR 15/15 窗 ≥0.941。这一片的价值不在分数，在于它是**第一部"场数 ≠ chunk 数"的片子**（S02、S03 各 2 条 chunk），于是把三处一直靠巧合成立的代码打回原形。

### ① 序号对齐假设：`build_mix` 让最后两条旁白凭空消失（本轮最严重）
`produce.py::build_mix` 生成混音脚本时写死 `("chunk_%02d", starts[i]) % (i+1)` —— 第 i 场的起点配第 i 条 chunk。17 chunk / 15 场下时间轴整体错位，**chunk_16 金句 + chunk_17 CTA 根本没进混音**：成片最后 12 秒无旁白。
- **为什么没被任何门拦住**：`qa_deliver` 查帧数/音画差/响度/黑帧，`clutter`/`aesthetic` 只看像素，`asr_final_check` 当时也在按同一套 1:1 假设切窗（见 ②）——**没有任何一环知道"该说的话有几句"**。
- 修：`_narration_plan()` 按 chunk 的 `scene` 字段分组、实测时长 +0.12s 顺铺、**有 chunk 没排上就硬 FAIL**。p14 回归 11 条起点逐字节不变。
- **通用判据**：语音单元（chunk）与画面单元（场）是**两个层级**，任何跨层映射必须读显式字段，序号对齐一律视为 bug 候选。

### ② 同一假设的第二处：`asr_final_check::scene_windows` 自我验证
`dur_map["s02"] = chunk_02 的时长` → 一场两 chunk 时窗口只剩半长且与下一场重叠，14/15 段相似度 0.04。**检查器用被检查对象的错误假设构造自己的输入**，等于没有检查器。
- 修：按场分组 chunk、从生成的 `mix_audio.py` 里读**实际** `NARRATION` 起点、窗口尾夹到下一场首条旁白前。p15 15 窗 0 重叠、p14 11 窗 0 重叠。

### ③ 渲染器静默吞掉不认识的键（两条同型）
- `draw_burst` 读 `max_ray_length`，我传 `length` → 15 场爆点全部退回默认 **280px**，无报错。
- `draw_burst` **根本不读 `color`**（硬编码砖红）→ 深酒红底上爆点几乎不可见；p12/p14 也一直在传、一直一直被忽略。
- 修：渲染器认 `color`，默认值保持砖红 → 旧场景逐字节不变（`test_render_sequence` 3 项仍 OK）。`preflight_v6` 新增 **`EFFECT_REQUIRED`/`EFFECT_OPTIONAL` 表**：缺必需键=ERROR 拒渲，出现渲染器不读的键=WARN（拼错必静默退默认值）。`debris` 缺 `source`/`sprite_boxes` 会让整场渲到一半 `KeyError`（s12 只渲出 130/260 帧），现在开工前就拦。
- **判据**：任何"传了不认识的键也不报错"的接口，必须在**上游**加键名白名单门。这比修单个 bug 值钱。

### ④ 模板库里的类型炸弹：`build_scenes_template.fly(fade=True)`
把裸元组 `append` 进 `keyframes`（一个 dict 列表）→ 场景 JSON 结构损坏，`preflight`/`first_frame_check`/`layout_check`/渲染器全部 `.get()` 崩栈。**这颗雷从写下那天就在，p15 第一次调用到这条分支。**
- 修：改走 `kf()`。教训同上条——模板函数里"只有一条分支会跑到的路径"必须自己调一次冒烟，别等生产片踩。

### ⑤ 配色硬门被散文字段崩掉：`palette_oklch._parse_rgb`
"带逗号就按 RGB 解析" → `palette.json` 里 `style_primary: "赛璐珞分层·暗房显影(主风格, 频道首用)"` 直接崩掉整道门。改为**仅三个 0–255 十进制数才算 RGB**，调用处跳过非色值字段。

### ⑥ 转写别名门把正确的别名全杀了：`asr_alias.load_alias`
约束加在了**变体**上（`_LATIN_ONLY.match(vk)`），而 `{"Alpha": ["阿尔法"]}` 这种"英文专名→中文音译"的合法别名恰好变体是中文 → 全被丢弃。约束应该加在**规范名**上（防止拿别名把"贵→便宜"这类语义改写洗白）。修后 RED/GREEN 双分支验证，p14 的 `{"Claude":["Cloud"]}` 回归通过。

### ⑦ 布局：网格吸附换来 align，赔掉 salience（设计教训，非 bug）
`build_scenes.py` 的 `card()` 夹取原本写死像素边距 → 把 s13 两张并排卡挤到同一位置叠印。改为**读盘上真实 PNG 尺寸、按成品坐标（相机 scale 反推）夹四边、留 20px 余量**；再加三列四行网格吸附（`COLS/ROWS`），但**只吸静止位、按元素自身安全边界过滤行列、文字卡完全跳过**（三列网格放不下两张 340 宽的并排卡）。align **0.618 → 0.909**，layout HARD/WARN 全 0。
- 但成片 **83.1 < p14 84.3**：拆解是 align +0.224 / **salience −0.077**，s03/s05/s10 三场"偏拥挤"正是元素挤进同列的结果。
- **下一片打法**：先按 salience 定主体（够大、够孤立），再让次要元素吸附，**不要把主体也吸进网格**。

### ⑧ 目检改设计（一次真救命）
animatic 首版棋盘格舞台 860 宽、格 40px、灰度 214/168，**几乎铺满每一帧**，灰网格成了主角。改 560 宽、格 26px、压暗 126/96、alpha 150、下移 y=930。若不改，渲完必然又是一堆"主体不突出"——**这正是本片要攻的 salience 短板**。
- 反向教训：我的"内部粉渗"自动扫描在本片**不可用**，判据 `g 最小且 b>g 且 r>g+12` 与本片深酒红 `#2A141A` 同签名，把 prop 误报成 19.7% 渗色。**指标假阳性，结论只能靠目检。**

### ⑨ 流程纪律（我自己这两轮犯的）
- **两次浪费整轮渲染/装配**：装配前没做"窗口重叠自检"、网格吸附无脑全量应用。→ **渲染提交前必须从场景 JSON 纯数学算出 align 与窗口非重叠**，这两项都是毫秒级计算，不该用 669s 的渲染去换。
- **验证退出码时不许接管道**：`render_all | tail -12` 把 rc 换成了 `tail` 的 0，让我误判"render_all 有退出码 bug"并在日志里写了错误结论。它其实正确打印了 `FAIL: s12` 并 `return 1`。
- **没跑完不许写"已完成"**：我在 BRIEF 里写"已删到 20 以内"时还没跑 `make_events.py`；跑完发现断言正确地拦在 22。**自述与盘上事实分离，写完立刻验证。**

### ⑩ 账本与口径
`palettes.json` 缺 production14（**第四次账本复发**）已补登；p15 双账本（8 隐喻 + 4 色）已在交付时登记。**开工/交付两处自检必须两项都查**，光查 metaphors 会被旧结论骗过去。

## §59 production16 复盘（V3.24：门放了人、指标骗人、以及"编码后才测"的那 0.6 dB）

p16《偷传代码被抓后，智谱把源码全开源了》是 **p12《AI 工具静默上传代码》同一事件的续集**（事件 9/18，本片讲 9/21 的整改结果，隔 4 天）。骨架 **C 双线对比式**（智谱的账 × 你的账，中点"但这事，不是个例"）；主风格 **工程爆炸图·维修手册** × 副 **质检钢印 + 红笔批注**；账纸白 `#E9E7DE` / 墨 `#171A22` / 靛紫 `#6A4CFF` / 品红 `#E4377B`。

### ① 事实核实：22 条里 19 条完全对上，三条口径有问题（这是本片最有价值的部分）
用户稿的技术细节罕见地硬，逐条核下来**全中**：信封加密（`AES-256-CTR` 临时对称密钥 + `RSA-OAEP-SHA256` 封装 + **私钥保存在云端** + 直传**阿里云 OSS**）、`42411` 个文件、`.git` 占 `86.6%`、`564 次全部失败才留证`、信通院"云端零数据"、绿盟"数据对象**连同存储桶本身**都已删除…未找到仍能触发本地仓库快照或文件外发的路径"、每月公布代码安全审计报告 + 常态化漏洞报告机制、**Claude Code 官方"不允许训练=30 天保留 / 允许=5 年保留"**。
三处必须处置：
- **错时（最严重）**：稿中"…有公司当场停用，智谱港股**当天**跌了 4%"紧跟在道歉与发函之后，读者会理解成 9/18。实测：跌 **4.23% 发生在 9/21 早盘**（盘中一度跌超 5%，市值 3642 亿港元），**当天下午因开源消息拉升翻红**。→ 这是对上市公司的错时归属。**处置：口播一字不动，字卡钉死"智谱港股 · 9/21 早盘 −4.23%（盘中 −5%+）"。**
- **无据**："有公司**当场**停用"——原文只到"据记者了解，目前已有公司内部停用"。→ 字卡加"据媒体报道"。
- **核不到原句**："整个项目核心资产差点被端"（虎嗅原文被反爬挡住）。核到的是函件"要求 12 项答复 / 说明是否跨境传输"。→ 字卡用可核事实承接；口播是转述（"**说**整个项目…"），归属清楚，保留。
- 另：Cursor 官方 Data Use 页证实"不开 Privacy Mode 会 *train our models*"，但**"个人版默认是否开启"的分档表没取到** → 字卡写"以你账号 设置→Privacy Mode 实测为准"。
> **通用做法**：涉实名企业/上市公司，**口播是用户底稿一字不动，屏幕上的字负责把日期、来源、适用范围钉准**。这比改词更安全，也比"什么都不加"更诚实。

### ② 时长口径：`phrase_timing.dur` 不是文件时长（本轮最隐蔽）
`word_timing` 写的 `dur` 是 **ASR 语音跨度**（首字起音→末字收音），系统性短于 mp3 实测：p16 25 段里 **15 段偏短，最多差 1.97s**（chunk_23 3.96 vs 5.928）。`build_scenes` 用它算帧预算 → 13 场画面比旁白短 → `check_timeline_ratio` 判"旁白未播完就切走"。**p15 不是对，只是 ×1.03 的余量刚好盖住了。**
- 修：在 `load_phrase_timing()` **入口**用唯一时长权威 `audio_duration.py` 覆盖 `dur`（ASR 原值留 `asr_dur`），所有调用方自动修正，不改一处漏一处。
- **规则**：任何帧预算只认 mp3 实测时长；两个来源打架时，在**最上游**统一，不在下游各修各的。

### ③ TTS 完全没有断点续跑（真金白银）
`generate_tts_template.py` 每次运行无条件重合成**全部** chunk。本轮后果两次：首轮在 chunk_15 网络超时中断，重跑把已存在的 1–14 **又扣一遍费**；`asr_spotcheck` 的提示写着"错读则只重 TTS 该段"，**但根本没有单段入口**。
- 修：按 `(文本|emotion|speed)` sha256 存 `assets/audio/.tts_stamps.json`，**内容没变才复用**（改了稿必然换哈希，不会留下"行不对音"的旧 mp3）；新增 `--only chunk_16[,…]` 与 `--force`。实测 `复用 24 段, 本次实际合成 1 段`。
- 注意 `if p.exists()` 那行是 `.env` 查找，**不是**跳过保护——读代码时差点被它骗过去。

### ④ 键色带冲突：配色可以离"抠图键色带"太近（新门 + 我自己的假阳性）
`cutout_key --hsv` 把 **PIL H∈195–248（≈275°–350°）高饱和像素判成背景**。本片 accent2 品红 `#E4377B` 色相 **336°（PIL_H=238）正落在带内**——进了生成道具就被抠穿成洞。
- 修：`gen_assets.key_band_conflicts()`，prop prompt 里出现带内十六进制色即 **FAIL 拒生图**（花钱前拦）。这类标记（钢印环、红笔下划线、勾、日期戳）本来就该是**纯几何 → PIL 直绘进 `assets/lines/`**，p15 已有 18 件先例。
- **⚠ 我第一版把它写成了假阳性**：它连 `enforce_prop_contract` 自己追加的 `#FF00FF` 键色底一起拦，**当场挡死整批 20 张道具**。改成只查作者写的 `job["prompt"]`、不看注入后的 `prompt`。这是 §57"假阳性比漏报更致命"的又一次现场教学——**新门上线必须先跑一遍自己的正常流程**。

### ⑤ 抠图模式不能照抄上一片
p15 的结论"`--hsv` 是暖/红主体的默认路径"**不能反着推**。p16 主体是冷色深墨 + 靛紫，`--hsv` 的 `dark_pink` 判据（H≥212 且 V<191）反而把**暗部抠成麻点**：不透明占比 0.354→0.572、半透明像素 13.6%→3.7%。
- 修：冷色主体用**默认键色法 + `--despill`**。despill 只削掉 1.3 万像素（那团粉洋红落地影），主体白色麻点是原图镀锌桶身纹理，两版一致——**先量化再决定，不靠感觉**。

### ⑥ 想给"空舞台"加门，标定后自己否掉了（第四个弱代理门实例）
背景出图后目检发现 8/19 张把主角画进了中心，其中一张整张底色是黑的。试着机械化，做了四版判据：
| 判据 | 结果 |
|---|---|
| 中心墨密度（参照=**中位数**） | bg08 判 0.000「干净」——那张 **78.6% 是黑的，中位数就是黑**，于是把整片黑当成空白。**指标在最坏样本上打了满分** |
| 中心墨密度（参照=**16³ 分箱众数箱均值**） | 正确抓出 bg08（地色 Δ228），但 p15 全线中心 0.998、p12/p13 地色 Δ200（`palette.bg` 是场景填充色不是 PNG 地色）→ **跨风格不成立** |
| 中心/边缘**梯度能量比** | 纯黑那张比值 **0.08（全场最低，看着最干净）**；p13 中位 1.71、p15 max 4.61，比 p16 的坏样本还高 → **完全分不开** |
| 同片内主色离群 | p12 偏离 198 / p13 197 / p14 99 / p15 64 → 场景本就该有暗房、亮板、发光台之分，**不成立** |
- 结论：`bg_luma_check` 只打印三个诊断数，**永不因空舞台 FAIL**（爆闪门不动，那条标定过）。按 §57 的规矩："做不到'最好那片不该红'的判据，就不许当门写。"
- **但诊断数 + 目检互补有效**：目检判错的 bg09/bg10，指标说中心干净（省掉 2 张重烧）；目检漏掉的 bg15，指标抓到了。**这一层不能省，也不能只靠一边。**
- 最终 19 张全部合格。措辞上有效的是 `CRITICAL COMPOSITION RULE: the entire middle 65 percent of the frame is completely bare empty paper` + 显式点名 `no container / no appliance / no box / no device`；bg08 连烧三次，最后一版靠 `a single continuous warm cream sheet filling the ENTIRE frame — there is no dark background anywhere` 才压住黑底。

### ⑦ 交付门抓到的那 0.6 dB：WAV 达标 ≠ 成片达标
`qa_deliver` 判 FAIL：`音轨 max -0.9dB 削波风险`（门限 −1.0）。但混音自己的复验日志写着 `round1: I=-14.5 TP=-1.5 -> 达标`——**WAV 是合格的**。差在 **AAC 编码的 inter-sample 溢出**（−1.5 → −0.9，涨 0.6 dB）。
- 两个真缺陷：① `alimiter` 的 `level`（自动电平）**默认 true，会反向回抬增益**（正弦实测 −5.1 → 关掉后 −6.1，差 1.0 dB），把 `limit=-1.0dB` 的封顶抵消掉 → 显式 `level=disabled`；② auto-trim 的 TP 上限 −1.5 **只比门限多 0.5 dB**，贴着门做必然被有损编码顶穿 → 上限改 `TP_GATE_DB(-1.0) - TP_HEADROOM_DB(1.5) = -2.5`，循环 2 轮放宽到 3 轮。
- **规则**：凡是"门在下游测、上游做优化"的量（响度、峰值、时长、帧数），上游目标**必须留出门限到实测点之间的实测余量**，并把这个余量写成具名常量，不要写魔数。

### ⑧ 流程纪律：同一条错误我犯了两次
§58⑨ 刚写"验证退出码时不许接管道"，本轮后台命令写成 `cmd > log; echo rc=$?; tail log`，**shell 最终退出码取的是 `tail` 的 0**，于是完成通知连着两次报"exit code 0"，而日志里明明是 `TTS rc=1` / `PRODUCE rc=1`。
- 固定写法：`cmd > log 2>&1; echo "rc=$?" >> log`，**读日志，不读通知**。
- 另一条：SUT 的 `SPEC` 我按**场**编号、循环按 **chunk** 迭代 → 从 chunk_04 起整体错位一格。加了一行 `assert scene_no == [k for k,v in SC_CH.items() if cid in v][0]` 后当场拦下。**凡是两套编号体系交汇的表，写表时就交叉断言。**

### ⑨ ASR 同音字死区：处置顺序（不要放宽别名门）
chunk_16「但这事不是孤例」转写成「但这是不是孤立」(0.71)。按 p15 判据**同文本重录再看转写** → take2 转成「但这事不是鼓励」。**两取互异却同族 → 音是对的**，`事/是` 与 `孤例/孤立/鼓励` 全是同音。
1. 先做**只加标点**的最小干预（阶段① 授权范围内）：「但这事，不是孤例。」让"事"收在话题位，与"是不是"分开 → 0.71→0.86；
2. 剩下的 `例/立` 是**声调都相同的完全同音字**，任何重录都救不了；
3. **交用户裁决**换词（`孤例→个例`，转写 100%）。这一处是改词不是改标点，**已记录在 BRIEF**。
- **没有放宽 `asr_alias` 的"规范名必须拉丁"**。那条件是防"拿别名洗白语义改写"（贵→便宜）的自缚门，为了过检把它松开，损失的是门的意义。附带收益：`孤例` 是生僻书面词，观众在纯音频里同样会听成"孤立/鼓励"——**门和观众是一次一起修好的**。

### ⑩ 主角吸附豁免是死代码：`src()` 把作者给的 id 丢了
交付前的 clutter 双峰逼出这条：`build_scenes.py` 的 `src(pid, …)` 调模板 `pop_spring(...)`，而**模板动效 helper 自造 id**（`"p_sp"+文件名+触发帧`），`pid` 参数从签名到函数体**一次都没被使用**。于是 `emit()` 里 `if l.get("id") in hero_ids: l["hero"]=True` 恒 False → **p16 十九场里九场的主角从未被豁免过**，全被吸进中轴列（s03 十层里八层静止 x=540 就是这么来的）。五道渲前门、clutter、aesthetic 全绿，没有任何一处会红。
- 修：加 `_named(lay, pid)`，三处 helper 入口（`src` / 裸 `slam_squash` / 裸 `fly`）统一改名。修完 19/19 主角 id 命中。
- **门禁**：`emit()` 现在逐场断言 ①图层 id 唯一 ②`HERO[s]` 里每个 id 都能在本场图层里找到，找不到就 `sys.exit`。**"配置表引用了一个运行时才生成的名字"这类错，只能在生成的那一刻对账，下游门看不见。**
- 通用判据：**凡是"我传进一个标识符、下游按它查"的 helper，必须验证这个标识符真的落在了产物上。** 参数被静默丢弃 = 该参数的一切效果同时变成死代码。

### ⑪ clutter 门四种统计量标定：减法更差，现有门报的全是真缺陷
门判 `2 过载 / 1 偏忙`（s04 edge×2.17、s10 edge×2.12、s03 偏空）后，先怀疑门，再改片。
1. **回放四部已交付片**：p12/p13/p14/p15 在 `med5`、`hold`（稳定段中位）、`max` 三种统计量下都是 **0 过载 / 0 偏忙** → 门不是乱咬。`hold` 顺手修掉了 p12 的 2 个假"偏空"（med5 把入场空帧算进中位），但它**不改变 p16 的任何判定**，所以拿它"让我过关"是假的。
2. **试第四种统计量：层贡献 = 成片帧指标 − 该场背景自身指标**（想把"壁纸有花纹"和"元素太多"分开）。**结果灾难**：p13 亮 5 过载/5 偏忙/5 偏空，p14 亮 4 过载，p15 亮 2 过载，全是用户验收过的片子。**两个大数相减，残差里噪声比信号大。** 弃。
3. **语料绝对带**（p12–p15 共 58 场）：absolute edge p50 0.040 / p90 0.056 / **max 0.083**。p16 s04=0.096、s10=0.093 **高于全部 58 场最大值**；s17=0.075 在带内（所以它只是偏忙）；s03 grid_fill 0.27 **低于语料最小值 0.52**。→ **四条报警全是真缺陷。**
4. **根因在素材不在构图**：bg10 的 edge 是自家背景中位的 **2.82×**、bg17 2.25×、bg04 2.12×，而 bg03/bg08/bg14 铺满 **0.00**（整张白纸）。同一条契约产出的背景密度差 6 倍，这才是"本片双峰"的来源。
5. **改素材，不改阈值**：bg04 重出（`WIDELY SPACED thin diagonal hatch lines` + `SPARSITY BUDGET: total drawn ink must cover less than one tenth of the image`）edge 0.082→0.051；bg10 重出 + 去边框 edge 0.077→0.034。**最终 0 过载 / 1 偏忙 / rc=0，clutter_check 一个字没动。**
- **prompt 教训**：`one dominant lower stratum hatched densely` 里那个 **densely 是我自己写的**，模型忠实照办。抱怨产物之前先把自家动词读一遍。
- **量具**：新增 `productionN/scene_geom.py save|diff`，改完 `build_scenes.py` 先算"哪几场的落盘几何真的变了"，只重渲那些（p16 实测一次 12 处坐标改动只影响 1 场，省掉 435s 全量）。**它的盲区要说清：只覆盖 scene JSON，背景/道具 PNG 换了它看不见**——本轮 s04/s10 就是 JSON 未变、素材变了。

### ⑫ 第五个标定失败的弱代理门：背景"深色边框"门
`--paint-border` 修 bg10 时顺手想把"外圈不是声明地色"做成硬门（契约明写纸要铺到四边，且 StepFun 画"摊开的册页"连抽两轮都加一圈深色封面）。回放到 p12–p15：**点亮 19 张背景**（p12 6 / p13 6 / p14 6 / p15 1）——四部好片全被判画坏，因为"边上有色块"本来就是这部片子的视觉语言（撕边带、钢印、深色浮世绘底）。
- 按 §57 规矩**退回工具**：`--trim-border` / `--paint-border` 只裁/只填，**不判、不 FAIL**；旧图一律进 `qa/prev_assets/`（可逆）。
- 这是**第五个**同类失败（PNG std、density 绝对阈值、内部粉渗、空舞台墨密度、背景边框）。累计规律已经够写死：**判据一旦依赖"这块区域应该长什么样"的画面语义，就没有能跨风格通用的**；能通用的只有"根本不该有 X"的存在性判据（爆闪 mean>235、键色带内十六进制、零字节派生文件）。
- 两个实现细节：① 阈值泛洪（`ImageDraw.floodfill`）修不掉**书脊渐变阴影**——它在渐变前就停了，外圈仍剩 5% 黑；改成**边缘带羽化重涂**（band 内全涂、band 外线性淡出，且只涂离纸色足够远的像素）才干净，四角页缘不受影响。② 备份名按内容哈希，**"从 prev_assets 复原后再修同一张图"会撞名 `FileExistsError`** → `_bak()` 加序号。
- 顺带：`gen_assets.py` 原来**没有重生入口**（同名文件一律 skip），改 prompt 后重跑会静默拿到旧图，只能手删文件（不可逆）。现加 `--overwrite`，旧图自动进 `qa/prev_assets/`。`register_assets.py` 的 `lines/` 扫描嵌在 `if txt.exists()` 里，没有文字卡的片子会整目录漏登 → 已提为独立分支（p16 实录：`l_sheets.png` 未登记被账本门拦下，**门是对的**）。

## §60 V3.25 效率归因与素材层三道前置（2026-09-22，用户问"做过这么多成片为什么还这么慢"）

### ① 先用日志时间戳归因，不凭印象
p16 后段 `21:47 → 23:14` 共 87 分钟。逐段：
| 时段 | 分钟 | 在干什么 | 性质 |
|---|---|---|---|
| 21:47–22:04 | 17 | 主角 id 死代码修复 + 19 场全量重渲 435s | 真缺陷，必要 |
| 22:04–22:40 | 36 | clutter 标定（4 种统计量 + 58 场语料）+ 背景重出 + 去边框 | 标定必要；**bg10 前三次尝试白做** |
| 22:40–22:44 | 4 | produce v8 → **DELIVER PASS** | 已经是可以交付的片子 |
| 22:44–23:14 | **30** | produce v9/v10/v11，追 1 LU 响度差 | **全是我自己造的** |

**34% 的时间花在一部已经跑绿的片子上，去修一个我自己设错的常量。** 而且我把 `final.mp4` 覆盖了三次，没留任何回退点。

### ② 错误分类：可预防的 vs 真方差
- **可预防（约 4/5）**：`TP_HEADROOM_DB` 拍成 1.5（实测只有 0.6）；12 处坐标改动没先算网格可达性不等式 → 白渲一轮；bg10 连试"重抽→裁→泛洪"三步都没先看下游门到底消费什么；退出码接管道（同型错误第二次）。
- **真方差（约 1/5）**：模型给"摊开的册页"加深色封面边框、把主角画进背景中心。
共同点：**这些都是"先动再测"**。用户的要求不是"一次完美"，是"少犯错、少返工"——方向正确。

### ③ 推翻我自己的一个说法
我先前说"素材每片全新且禁止复用，所以是抽奖"。查出来：**背景契约从来没有注入机制**（`enforce_prop_contract` 只管 `prop_`），尾巴是我每张手抄的——p12 十二张十二种、p13 十五张十四种、**p16 十九张一种（历史上最统一）**。可 p16 偏偏是密度离散最严重的一片（5.0×，同门 2.7–4.4×）。**所以"统一提示词"并不能解决它**，继续打磨措辞的收益比我说的小。真正的杠杆是**出图后立刻量、只重抽离群那一张**。

### ④ 病灶能 1:1 对上：契约自相矛盾
旧尾巴里的 `absolutely no objects` 与正文要求的"剖面图 / 摊开的册页 / 爆炸装配图"直接打架。p16 **3/19** 张踩中：bg03、bg04、bg10——**正是 clutter 点名的 s03、s04、s10**。（bg17/s17 不算矛盾，夹板待在边缘合法，它属于另一种失效：单纯画过头。）

### ⑤ 用户当场拦下我的一个严重错误
我第一版把 `vintage engineering service-manual` + `warm paper` + **`no dark background`** 写死进契约。那是 p16 的画风与浅纸底。**套到 p12（浮世绘工笔·深酒红底）上会直接毁掉它的底子。** 用户问"以后风格都千篇一律吗"才暴露这个问题。
修正后的硬规矩：**契约只准带骨架**（构图职责、数值密度预算、"边框须来自本片地色"），**皮肤归 `--style` + `palette.json`**；契约里不许出现任何颜色词或流派名词，地色从本片 palette 取，取不到就整条省略，绝不退回写死的默认色。`scripts/test_bg_contract.py` 用正则守这条。

### ⑥ 新契约自己造了一个新 bug，被新流程当场抓住
我写的 `CRITICAL COMPOSITION:` 和 `SPARSITY BUDGET (hard):` 是全大写标签形状，模型**把 "CRITICAL COMPOSITION" 当成红色钢印画进了画面右上角**。`no text` 挡不住——它把指令本身当成了标签。改成小写散文后消失。
这条的价值不在 bug 本身，在于**它是在"重渲之前"被发现的**：出图 → 目检 → 重抽，全程没碰渲染。

### ⑦ 渲前背景密度一致性门（第一个通过标定的素材级门）
`bg_luma_check.density_gate`：`该张 edge ÷ 本片背景 edge 中位 > 2.0` → FAIL 并指名重抽那一张。
- **为什么它过得了解定而"边框门"过不了**：它只判**同一片内部的一致性**，不判"这张好不好看"，所以与画风、深浅底完全无关。
- 五片实测 max/median：p12 1.84 / p14 1.76 / p15 1.69 **绿**；p13 2.11、p16 2.25 **红**。而 p13、p16 正是审美最低的两片（78.3 / 79.8，同门 83–84）。**有质量锚点，不是假阳性机器。**
- 触发点前移：`bg_luma_check` 原来没有 scene JSON 就 `return 0`；现在改为扫 `assets/raw/bg*.png` 只跑密度门。**量 19 张背景只要 3 秒，而 p16 是在 435s 渲染 + 一次装配之后才发现同一件事。**
- 触发词要窄：第一版把 `clipboard` 当实体触发词，误判 bg17。**判据混了两种失效（自相矛盾 / 画过头），门就会给出错误的修复建议。**

### ⑧ 实测收益
bg17 从 2.25× → **1.47×**，s17 从"偏忙"→ **OK**，p16 首次做到 **0 过载 / 0 偏忙**（与 p12–p15 画像一致）。代价：1 次重抽 + 1 场重渲（317 帧）+ 1 次装配，且每一步都在花钱之前先测过。

### ⑨ 沉淀成规矩的三条
1. **跑绿之后要动共享模板，先把成片复制进 `qa/prev_assets/` 再动。**
2. **余量/阈值类常量必须来自实测**，不许拍一个"看起来更安全"的数。
3. **任何能在秒级纯数学判定的事，不许用渲染或装配去换。**

---

## §61 V3.26 创作层开工模板与"补丁不抬上限"的判定（2026-09-22，用户令"全面审查工作流"）

### ① 用户裁定（优先级高于本文一切工具性建议）
- **每一部必须比上一部好**；历史分数不作依据，只看最新标准。
- **风格 / 元素 / 视觉效果必须随文案题材适配**，禁止千篇一律。
- 明确反对"用检测、用元素多少"这类治标不治本的提法。

### ② 审查判定：补丁守下限，抬不了上限
V3.12→V3.25 共 14 个版本，投入几乎全部在"别退步、别把坏片子发出去"。这类投入是必要的（本轮就查出对外交付的是已知缺陷版、便携包落后 15 个脚本），**但它不会让下一部更好看**。
片子质量由三件事决定，三件都在流水线之外：
1. **模型出的那张图**——背景占画面七成观感，没有任何门能改变模型吐什么；
2. **设计期的摆放**——本手册 §51⑦「审美分对事后调坐标不敏感」、§57⑧「那要靠设计不靠门」已经自证；
3. **有没有人当观众看过一遍**——16 部片零播放数据，"更好"这个词在房间内没有定义。

### ③ 本轮落地：`references/kickoff-template.md`（挂进 SKILL 阶段①，不填完不进生图）
- **0 适配起点**：`detect_genre` 取本类型视觉策略当**起点**（不是答案）；题材三问 = 主角物 / 物理动作 / 情绪温度 → 决定世界、配色温度、动效快慢。
- **A 全片三定**：世界必须是"有光、有空间、有前后层的场面"，禁止"一张纸上画几笔"；风格拆成 3 个看得见的特征；全片一次情绪打断。
- **B 逐场表**：动作七选一（拼装/撕开/滑动/砸下/折叠/散开/沉落）、哪个词被演出来（滚/堆/喷）、重的那一下在第几秒、视差开关、相机推拉、>6s 的景别切点。**写不出动作的场 = 静止 PPT，合并或重想。**
- **C 每场五拍**：亮相 → 进来一个新东西 → 重的那一下 → 后果 → 停住但纸还在动；落地必须压扁回弹，不许匀速飘入。
- **D 画面硬规矩**：主体 ≥40% 画面宽；底部装饰带取本片配色；背景 scale ≥1.10 给相机留余量。
- **F 防千篇一律差异表**：对上一部 `KICKOFF.md` 逐项查 世界 / 风格三特征 / 主色 / 骨架 / 核心图腾 / 主导动作分布，**六项最多 1 项相同且须用户确认**；上一部最常用的动作本部 ≤1/3 场；核心图腾必须换。**本部填完的汇总就是下一部的对照——链条自续，不新增需要人工维护的账本。**
- **E 第一眼检查**：渲完低清整片过一遍，逐场问"观众第一眼看哪里"，不是主体就重摆，不靠加元素救。

### ④ 审查查出、本轮未处置的事实（留待用户决定，不擅自改动交付物）
- **对外交付的 p16 是缺陷版**：`output/偷传代码…_p16.mp4` 与 `qa/prev_assets/final_bg17dense_p16.mp4` md5 相同（即 V3.25 专门修掉的那一版）；修好的 `output/final.mp4` 已于 00:39–00:40 重跑 deliver/clutter/aesthetic/asr 四份报告且 `fails=[]`，但从未改名交付。**属交付动作遗漏，不是代码缺陷。**
- **`VOX-便携包-v3.22.zip` 落后 15 个脚本**（含 render_sequence / mix_audio4 / produce / preflight_v6 / layout_check / asr_final_check / bg_luma_check / gen_assets）。README 称"copy 即用"——照它跑会复活 V3.23–V3.25 修掉的缺陷。
- **阶段⑤ 镜头计划从未产出过 `shot-plan.json`**（9 部现存片全查无此文件），`validate_shot_plan.py` 零调用。产线实际是"一场一镜"，无景别、无轴线设计。
- **`wave_bands` 九部片逐字节相同**（深蓝 `[18,30,58,205]`），而九部声明的配色里**无一部含深蓝** → 模板常量从未随片改过。配色门只比对 `palette.json` 的声明色、不比对画面实际出现的颜色，所以永远不会红。
- **`清晰度 grad<6` 与绝对 `曝光带 25~215` 两个 WARN 标定不通过**：清晰度告警与审美相关仅 +0.10（p10 后），且**审美最低的两片告警最少**（p8 0.1%、p13 0.8%），按 §57 的验收判据属反方向失效 = **第 6 个弱代理门**；曝光带上限与浅色纸地色结构性冲突（10 个登记配色里 6 个地色本身 >235，p16 实测最高帧亮度 227，距硬门仅 8）。**本轮只记录，未删未改。**
- **`palettes.json` 缺 production6 / production7**（metaphors 有），而 §46 line 827 声称"保留 p1–7"——文档陈述与盘上不符。
- **16 部片零真实播放数据**；§57⑧ line 989 那个"下一片发数据回来记"的占位从未回填。

### ⑤ 下一部的三件实验（用户用眼睛验收，不用尺子）
1. **背景每张出 3–4 张候选，拼一起挑一张**，而不是第一张就用。杠杆最大，成本约 20 秒/张。
2. **全片挑一场"英雄时刻"真设计**：出两三个方案、选一个、磨它。片子被记住靠最好那场，被划走靠最差那场。
3. **交付前把成片当观众完整看一遍**——`collage-language.md` 契约原文就要求 "a contact sheet and 1x playback"，这条从未执行。

**验收方式**：与上一部并排，用户用眼睛判。若这样还看不出差别，说明瓶颈更靠前（选题与文案），转去那里找。

---

## §62 V3.26 第二轮全面审查：13 处修复 + 一类已交付片里的真实视觉缺陷（2026-09-22）

用户令"再次全面审查检测，先修不合理的地方"。四路并行读源码 + **每条结论自己复核后才采信**（§59 记过 subagent 编造缺陷的前科）。

### ① 最严重：关键帧写成乱序 → 元素在入场前就被画满（已交付片里真实存在）

`render_sequence.py:45` 会把 `keyframes` **先 sorted 再"第 0 帧钳到首帧姿态"**。所以图层关键帧的 frame 一旦不是升序，排序后的首帧就是它在第 0 帧的样子——**若那个姿态 opacity≥0.4，元素就从第 0 帧全程可见**，设计的入场时间完全失效。

实测 9 部片 1019 个多关键帧图层，**18 个顺序非升序，其中 12 个真会提前露出**，跨 p11/p13/p14/p15/p16 五部已交付片。

**铁证（不是推理）**：`production14/scene_s01.json` 图层 `g_cross`（`assets/lines/wb_cross.png`，z=8，全场唯一用这张图的层）关键帧写作 `[197,199,196,200]`，排序后首帧 = 196 且 `opacity=1.0` → 设计入场 **6.5 秒**，实际从第 0 帧就在画面里。我直接看了 `frames_s01/frame_0050.png`：**白板上那对交叉箭头在第 1.7 秒就已经在那儿了**。

**为什么两道门都没拦，而且方向相反**：
- `first_frame_check` 只断言"第 0 帧有不透明图层"——这个 bug 让它**更容易绿**；
- `layout_check:160` 用未排序的 `keyframes[0]["frame"]` 当入场帧，把入场**之前**那段（正是"字卡从画外飞进来"要抓的区间）整段 `continue` 跳过 → 假 PASS。

**修法（已做）**：`preflight_v6` 新增 `[关键帧顺序]` **ERROR**（非升序 / 负帧号一律拒渲）+ `[关键帧越界]` WARN；`layout_check` 两处改用 `min(frame)`。
回放结果：p8/p9/p10/p12 **rc=0 不受影响**；p11(3) p13(4) p14(2) p15(4) p16(7) 现在会红——**这是正确的**，它们里面确有 12 个这样的图层。**旧片一律不动**（用户令：喊重做才重做），但谁再渲这几部就会被拦下，这是事实不是误报。

**顺带查出**：p16 有 4 个 `ip_host_*` 图层末关键帧落在 1038~1088 帧，而所在场只有 84~265 帧 → **把全片时间轴的数字当成场内帧号用了**，那 4 次 IP 角色退场动画一次都没播过。

### ② 另外 12 处修复（每条都做了回放验证）

| # | 位置 | 缺陷 | 修法 |
|---|---|---|---|
| 2 | `mix_audio4.py:176` | loudnorm 第一遍解析失败时**编造一组测量值**（−16/−3/8/…）喂给第二遍并 exit 0 —— 违反本文件自己写的 R2"解析失败=抛错" | 改成 `raise SystemExit` |
| 3 | `render_sequence.py:472` | 有 `parallax` 但**没有** `camera_motion` 时，`camera and par` / `elif camera` 两条都不进 → 背景平面被整个丢弃、图层画在透明底上 → **该场全黑，零报错** | 补第三条 `elif par` 合成 |
| 4 | `check_timeline_ratio.py:87` | 场号按 `enumerate` 位置猜，`name` 读了不用；且 `except Exception: scene_chunks={}` 把 chunks.json 解析失败**降级成按位置猜** —— 正是 §58 定死的"跨层映射必须读显式字段"的反例 | 场号取自 `frames_sNN`；解析失败不再吞；`\d{2}`→`\d+` |
| 5 | `preflight_v6.py:166` | 节奏滑窗 `range(0, total-WINDOW+1, 60)` 在 total=159 时只得 st=0 → **尾部最多 59 帧无人看守**，与文档"任意 120 帧滑窗"不符 | 补贴尾窗 |
| 6 | `preflight_v6.py` 末尾 | `if errors: sys.exit(1)` 排在打印 warns **之前** → 门一红所有 WARN 消失，修完才发现第二批，白跑一轮（本轮我自己撞上） | warns 先打印再退出，并给 ERROR/WARN 计数 |
| 7 | `split_beats.py:23` | 末拍 `f=round(i*frames/n)` 落在 `frames`，而渲染循环是 `range(frames)` → **最后一拍终态永远渲不到**，tween 静默钳位（p14 s04 实测最大关键帧 268 / 只有 268 张图） | 改 `frames-1` |
| 8 | `word_timing.py:99` | 缺 mp3 时 `continue` → 该段从 `phrase_timing.json` 消失，下游 `pf()` 静默退回字数摊派 | 改成 raise |
| 9 | `cutout_key.py:81` | 抠图直接覆写注册过的素材且**无备份**——这是素材链里唯一不可逆的一步（`gen_assets`/`bg_luma_check` 都会先挪进 `qa/prev_assets/`） | 补备份（含撞名加序号） |
| 10 | `cutout_key.py:75` | 抠完全透明时照样存盘、exit 0 → 场上悄悄少个主体 | 空图直接 FAIL |
| 11 | `gen_assets.py:306` | 文件已存在时 skip 重生，却**仍用本次的新 prompt 去 register** → 账本给旧图盖了"由新提示词生成"的假章（还写 prompt_hash） | skip 时不再登记出处，并打警告 |
| 12 | `register_assets.py:44` | `endswith("_check")` 永远不成立（文件叫 `X_check.png`）→ 棋盘调试图一直被当正式素材入账（p16 账本实测 21 条） | 改 `_check.png` |
| 13 | `clutter_check.py:60` | 空 `frames_sNN/` 目录被 `continue` 悄悄摘掉 → 6 空 1 有帧时中位数只由那 1 场算出，rel≡1.0 → **假 PASS** | 空场点名 FAIL |
| 14 | `clutter_check.py:24` | `EDGE_WARN/EDGE_HARD/INK_WARN/INK_HARD` 四个常量**代码里从未使用**，而 docstring 宣称按它们判读 | 删死常量 + docstring 改成如实描述相对判据，并写明"全片一致偏挤时 rel≡1.0 判 OK"是相对门的固有盲区 |
| 15 | `qa_deliver.py:70` | 缺 `splice_manifest.json` 时 `manifest_total=None` → ①道帧数断言**静默不跑**，照样 PASS。与 §57② 修过的"缺文件就静默少跑一道门"同一类病 | 缺 manifest 直接记 FAIL |
| 16 | `qa_deliver.py:144-150` | 清晰度/曝光/ΔY 逐帧刷 WARN（p16 实测 **614 行**），把真告警埋掉 | 合并成 1 行汇总，并把唯一有行动价值的数提出来：**距爆闪硬门的余量** |
| 17 | `mix_audio4.py:50` | 注释写"0 表示跳过"，但 `if trim != 0.0` 的 else 分支就是 auto → **0 是 auto 不是跳过**，且 produce 恒传 0，手动分支在生产路径不可达 | 注释改成真话 |

### ③ 验证证据（不采信未验证的结论）

- `compileall scripts/` rc=0；`test_layout_parity` / `test_bg_contract` / `test_render_sequence` 全过。
- **改过的门在 9 部片上全量回放**：p8/p9/p10/p12 preflight 仍 rc=0（无误伤）；p11/p13/p14/p15/p16 转红且**新增失败 100% 只来自 `[关键帧顺序]`**，没有别的错误类别混进来。
- `qa_deliver` 降噪前后对比：**fails 集合完全一致（0 条）**、`nb_frames/av_gap/audio_mean/audio_max/roundtrip` 五项数值零漂移、scene 跳变仍 10 条、**warns 614 → 11**、结论仍 DELIVER PASS。
- 我自己的两个操作失误，如实记：① 第一次测退出码时接了 `tail` 管道（§59⑨ 刚记过的错），得到假的 rc=0，重测；② 测 `gen_transitions` 合法分支时真跑了一遍，改写了 p16 的 `splice_manifest.json` mtime → 之后 `qa_deliver` ⓪ 号断言正确地拦下"改源未重渲"。已核实 manifest 内容与成片帧数一致（3761=3761）且转场帧同 seed 逐字节相同，故把 mtime 复原后重跑通过。**p16 的画面与两支 mp4 的 md5 全程未变。**

### ④ 本轮仍未处理（如实留档）

- 12 个乱序关键帧图层分布在 5 部**已交付**片里 —— 按用户令不动，只保证新片被门拦下。
- 245 处"末关键帧 = 场帧数"的 off-by-one 惯例（只差 33ms，全库通行写法）—— 故意**不报**，报出来会淹掉真信号；`split_beats` 那处已按正确写法修掉。
- 审美仪器三项（harmony 89% 冻结 / fill_pen 二值悬崖 / balance↔salience 相关 −0.30）—— 用户裁定不动："尺子的事不管"。
- `shot-plan.json` 9 部片 0 份；③④⑤ 三个阶段仍零编排；`palette_oklch`/`metaphor_ledger`/`semantic_check`/`polycheck_v66`/`novelty_meter` 仍只以 print 提示存在。
- 那条 9 部片逐字节相同的深蓝 `wave_bands`。
- 便携包 v3.22 落后 15 个脚本（现在更多）。
- `palettes.json` 缺 p6/p7，且已无法考证（目录已删）—— 永久缺口，不编造。

### ⑤ 一句话结论

本轮查出的最值钱一条，不是任何新门禁，而是：**渲染器会替你把写乱的关键帧排序，于是"入场时间"这种最基本的创意决定，可以静默失效 6.5 秒，而两道门一道更容易绿、另一道直接跳过那段不测。** 这类"门检查的是代理、不是产物本身"的漏洞，比缺功能危险得多。

---

## §63 V3.27 边界假 PASS 与"把没人调用的工具接进流水线"（2026-09-22，用户令"确认未深查脚本的边界 + 补缺失的编排钩子"）

### ① 空目录探针（§57⑤ 用过、零误报的方法）查出四个边界

| 位置 | 现象 | 为什么危险 | 修法 |
|---|---|---|---|
| `bg_luma_check.py:247` | 无 scene **且** 无 `assets/raw/bg*.png` → `return 0` 打"跳过" | **项目路径写错恰好就是这个样子**——门在空目录上假 PASS | 改 FAIL；但"背景 <4 张"仍 rc=0（短片不该被拦，已复测不误伤） |
| `polycheck_v66.py:407` | `return 1 if warns else 0`，空项目读不到场景 → 0 告警 → rc=0 | 同上，"无事可查"被当"全部通过" | `scene_map()` 为空即 FAIL |
| `asr_final_check.py:175` | `mp4 = a.project / a.mp4` **无条件再拼项目目录** | 从仓库根敲 `--mp4 production16/output/final.mp4` → 变成 `production16/production16/...` → 假报"成片不存在"。与 §54 `gen_assets --raw-dir` 同一类路径病（produce 传绝对路径所以生产没炸，人手工传就炸） | 先按原样试，不存在再挂项目目录 |
| `palette_oklch.py:191` | 缺 palette / 色值不是"三个 0–255 数" → 裸 traceback | rc 仍是 1（fail-closed），但看不懂。§57⑤ 那批"缺输入即吐 traceback"的漏网之鱼 | 分发处兜住，打干净 FAIL + 说明要求 |

**同时确认没问题的**（实测，不靠猜）：`splice_frames` 帧数不符 → **rc=1 且不产出任何帧**（fail-closed，我一开始误读成 rc=0 是因为**又接管道了**，见 §59⑨）；`render_sequence` 零帧场 / 空 keyframes / 缺素材 → 三条都 rc=1 干净报错。

### ② 补上缺失的编排：`pipeline ready`（本轮真正的交付物）

**事实**：`semantic_check` / `palette_oklch` / `metaphor_ledger` / `novelty_meter` / `validate_shot_plan` 在三个编排器里**零调用**，只以 `print("下一步·人做")` 存在。SKILL 写的"八阶段每阶段都有硬关卡"对③④⑤ 不成立。

**接线前先测**（不测就接=把流水线搞坏）：`semantic_check` / `novelty_meter` / `metaphor_ledger check` / `palette_oklch check` / `register_assets` 在 p16 上全部 rc=0、各 <1 秒 → 可安全接成硬门；`palette_ledger check --film` 的 rc=1 是**用法错**（要求把四个 hex 作为位置参数传入）；`polycheck_v66` 在 p16 上 rc=1 是**它自己那批 align 弱代理告警**（其输出自注"字符比例估计,非词级 ASR"）→ **不接成硬门**。

**新机制**：
- `pipeline ready <项目> --stage tts` = KICKOFF 完成度 + `palette_oklch` + `metaphor_ledger` + `novelty_meter`；`--stage assets` 再加 `semantic_check`。
- 全过才写 `qa/ready-<stage>.json`，stamp = sha256(KICKOFF.md + palette.json + chunks.json [+ sut.json])。
- `pipeline tts` 与 `gen_assets` **只认章**：没章、或盖章后输入改过 → 拒绝，且**在发起任何 API 调用之前**就拒（实测零扣费）。
- `pipeline setup` **自动把开工模板复制进新项目**——"记得去复制"的规矩一定会漏。
- 缺 `shot-plan.json` 只 **WARN 不拦**：九部片 0 份分镜是事实，硬拦会停掉整条产线。这是有意的取舍，不是遗漏。

**"一轮看全"原则**：`ready` 用不中止的 `probe()` 收集全部门禁再汇总。因为 `run()` 第一条失败就把剩下的藏起来——**§62① 刚为 `preflight` 记过同一类病（门一红 warns 全消失），本轮我自己又撞上才发现。**

### ③ 两个独立旁证：信息一直在，只是没人调用产生它的工具

- 接上 `novelty_meter` 后它**当场报**"D4 特效词汇仅 1 种"——与我逐帧看成片得出的"p16 动效词汇只剩 1 种"完全同一结论。
- `polycheck_v66` 早就打印过 s06/s13/s18/s19 的 `"tail_static": -27.1/-31.8/-29.1/-27.4`（"关键帧越过场景末 27~32 秒，切点仍在运动中"）——**正是 §62① 我独立查出的那 4 个 `ip_host` 越界层**。两个互不知情的工具同一结论。

### ④ 本轮验证与自报失误

- `compileall scripts/` rc=0；`test_layout_parity` / `test_bg_contract` / `test_render_sequence` 全 rc=0。
- 四个边界修复**复测通过**且**不误伤**：空目录 bg_luma/polycheck 由 0→1；背景 2 张仍 0；p16 全链复跑结论不变；`asr_final_check` 相对路径由"假报不存在"→ rc=0。
- `pipeline ready production16` 实测：四道门一次跑完汇总、KICKOFF 缺失那条给出可执行指引、rc=1、**不盖章**。
- 生图钩子实测：无章时 `gen_assets` rc=1 并输出可执行指引，**未发起任何 API 调用**（用空 jobs 文件在隔离目录测，测完即删）。
- **自报**：① 我又犯了一次"验证退出码时接管道"（§59⑨ 第三次），把 `splice_frames` 的 rc=1 读成 rc=0，差点误判成缺陷；② 第一版 `ready()` 里我用了根本不存在的 `run(...).returncode_ok`，且 `run()` 失败即 `sys.exit` 无法汇总——编译期没抓到的逻辑错，靠实跑抓出来。

### ⑤ 仍然没接的（如实）

`polycheck_v66`（弱代理，不接为硬门）、`animatic`（预览工具，非门）、`detect_style`、`make_countup`/`gen_sut_cards`/`assemble_audio`/`cutout_key` 等仍是人驱动。**`KICKOFF` 的 F 差异表仍无机械校验**（要读上一部 KICKOFF 才知道"像不像"，这一步留给人）。

---

## §64 V3.28 production17 首跑：创作层改动抓到的东西，和四处"工具在骗人"（2026-09-23）

p17 是 §61 开工模板 + §63 盖章编排**第一次真正走完全程**的一部片。收获分两类：门禁抓不到的（只有眼睛能抓）与门禁自己在骗人的。

### ① 预览门(animatic)抓到的五个构图缺陷 —— 全部**不可能**由任何现有门禁发现

渲前用 `animatic --step 8 --scale 0.35` 看了一遍，改完再看一遍。第一轮的问题：

| 症状 | 根因 | 修法 |
|---|---|---|
| 四张问题卡（全片图腾）是画面里最看不清的东西 | 每张 176px / 1080 宽 = 16%，而 KICKOFF D1 自己写的是"主体 ≥40%" | 205px×4 摊开成 76% 宽；同时**删掉**内容重复的 `c_four_q` 字卡（卡上本来就写着那四问） |
| 三档参数数字糊成一团 | `seq(hold=True)` 末帧定格**不会自己退场**，三档又都写在同一个 y | 竖排成一张参数单（y 330/430/530）——叠字变成清单 |
| 画面里出现一根白色竖条，像坏帧 | 用竖向 `v_caliper` 去"量"两台机器的高度差 | 删线。一高一矮并排本身已经说完，线只会挡道具 |
| "不用下载"演不出来 | 画了一个空心矩形表示"这里没有安装包"——**观众读不出 absence** | 改成动作：纸箱往下落，落到一半被推回画外。"没有"→"被拒绝了" |
| 底部装饰带九部片都没人看见过 | 见 ② | 带子 y 从 1392 移到 1268 |

> **判定**：§61 模板把"画什么"往前推了一步，但**上限仍然只体现在眼睛能看到的那张图上**。这五条没有一条能被"元素数≥7""关键帧升序""对比度≥4.5"这类判据逼出来——它们全是**摆放**问题。预览门不是可选步骤。

**①-b 全分辨率回看又抓出三条，其中一条是门的盲区**（成片 1080×1440 抽帧，非 animatic）：

| 抓到的 | 为什么门没响 |
|---|---|
| S02 三档 `seq_` 数字压在 Flash 菜单牌上 | `layout_check` 的卡×卡门只认 `c_/t_` 前缀的字卡；**`seq_` 层和道具不在它的比对集合里**。数字×道具的叠印目前**没有任何机检覆盖** |
| S03 "图/视频/音频" 与 "便宜" 两张字卡同区叠印 | 两张卡**入场时刻不同**，检查按各自入场帧取样，没撞上；成片里前一张还没退场就被后一张压住。→ 给前一张补 `f_out` 让位 |
| S10 收尾四张问题卡全是同一张 `prop_card_q4` | 复用同一素材的 id 不同、路径相同，任何几何门都看不出"内容重复"。**这是只有眼睛能发现的**：观众看到的是"④④④④" |

> **两条方法论**：① animatic 的 `--scale 0.35` 看不清"四张卡各写着什么"这类**文字级**缺陷，全分辨率回看是独立的一道，不能省；
> ② 但也**别只看一帧就下结论**——我在 10.9s 抽帧看到"第四张卡不见了"，实际那一帧它 `opacity=0` 刚要入场（11.4s 落定），换到 11.9s 四张齐全。**判"缺失"要先确认不是采样采在了淡入前。**

### ② 量出来的事实：相机推近会把内容裁出画外（此前无人算过）

`camera_motion` 以画布中心缩放，推到 `bg_end` 时可见纵向区间只剩 `720 ± 720/s`。全仓 142 条 `wave_bands` 里 **68 条**落在自己那场相机推到最远之后的可见区外；p17 有 5/10 场（bg_end ≥1.14）把底部带整个裁掉。**先别改判据，先确认判的是不是同一个坐标系**——`layout_check` 早就建模了相机缩放（所以它按含阴影+推近后的 bbox 判），而 `wave_bands` 的 y 一直是按画布坐标手写的，没人把两边对起来过。

同理，**抽图必须按成片取景框判，不能看整图**：`bg_stacks_a` 缩略图最好看，但 `cover()` 在 scale 1.12 下只取源图中央 686×914，它左缘那列纸箱（正是选它的理由）被整列裁掉。落选候选留在 `assets/raw/candidates/`，不删。

### ③ 帧预算要照混音器算，不照"×1.03"猜

`build_scenes_template` 的惯例是 `ceil(dur·30·1.03)` 累加。混音器实际摆法是**本场第一段 +0.3s、段间 +0.12s**。拿混音器的排布去量：p17 十场**全部**短 0.03–0.23s，p16 十九场**同样全部**短。切掉的正是 TTS 尾部静音（实测各段 0.1–0.5s），所以历部片子听感无碍、`check_timeline_ratio` 也是绿的——它只断言"场景 ≥ 音频和×1.02"，**不含 LEAD/GAP**，比它把关的对象本身松。
p17 改成项目内 `scene_timing.py`：帧预算 = `LEAD + Σdur + GAP·(n-1) + HOLD(0.9s)`，`HOLD` 就是五拍里"停住，但纸还在动"那拍的时间。**没有把它改成 `check_timeline_ratio` 的硬门**：差额是尾部静音，改判据会让 9 部已交付片集体转红，而"假阳性比漏报更致命"（§57/§59）。

### ④ 四处"工具在骗人"（都带实测数字）

1. **`polycheck_v66` 的画音对齐漏算段起点**。`voiced_sec = 场景起点 + 该句在本段音频内的相对位置`，但一场多段时第二段的声音根本不在场头。p17 实测 55 个 A 级单元误报 **51** 个"漂移 100–300 帧"，p16 误报 38/41——**而动画是按真词级时间戳做的，完全同步**。谁去"修"这个警告，就会把对的改错。
   → 新增 `scripts/narration_layout.py`（`LEAD`/`GAP` 单一事实源），`produce.py` 与 `polycheck_v66` 同时改用它；补回段起点后误报降到 43，且那 43 个全部是"字符比例"估计（把单元按字数均匀撒在整段里，天然 ±0.5s，而阈值只有 6 帧）。
   → 该检查的 note 本来就写着"可作为基准**不扣分**"，但旧版照样塞进 `warns` 参与退出码。现在字符比例项进 `align_reference` 留档、不进退出码；有词级 ASR 时仍是 WARN。
2. **`polycheck_v66` 的 density 检查在首渲前必然胡说**。分母是**渲出来的帧数**，未渲时 `frame_count=0` → `dens` 恒 0.00、`tail` 恒 `-场景秒数`，十场全报"密度低于下限 + 关键帧越过场景末"。`transition` 检查早就有"缺渲染帧则跳过"的护栏，密度检查漏了 → 补同一道护栏。
3. **背景契约没有"场面"这一格**。§61 把世界定死成"有光、有空间、有前后层的场面"，而 `bg_contract` 只有 `stage`（中心 65% 必须全空 + `no standalone rendered objects`）和 `sheet`（只能细线稿、不许实心块）。**两条都与创作标准直接对撞**——等距 2.5D 的背景就是一间房。缺这格，"先填 KICKOFF 再生图"根本走不到生图。→ 新增 `bg_role: "room"`（仍须显式声明，默认还是 stage，历史项目行为不变）。
4. **小数滚不了**。`make_countup` 只有整数，而本片口播第一句就是"1.02 万亿"。→ 加 `--decimals`（`--end 102 --decimals 2` → 0.00…1.02）。顺带：`style_presets.suffix()` 风格名写错（"等距 2.5D" 多一个空格）是裸 `KeyError`，会在**已经准备花钱生图**时才炸 → 改为列出可用名。

### ⑤ 本片实测产出与仍未做的

10 场 / 21 段 / 3121f = 104.03s；每场 ≥7 层（7–16）；5 处 `seq_` 数字滚动（过去三部片 0 次）、`motes` 1 次、视差 8/10、全片零 `ease-spring`/`ease-out-back`/旋转/jitter、grain 0。**KICKOFF 的"景别切点"列有 4 处按 94s 预估写，实测 90.72s 后落在自己场次之外**（写了 13.5s 的切点、那场只有 12.6s）→ 已全部回填为 `scene_timing.py` 真值。
仍没做：`shot-plan.json` 依旧 0 份；便携包落后更多脚本；F 差异表仍无机械校验；`--decimals`/`bg_role=room` 只在本片用过一次，第二次的价值才算数。

---

## §65 V3.28 production18：两项承诺的改进落地，和三个"我以为对了其实错了"（2026-09-23）

p18 是 §64 之后立刻做的一部，用来验证"改进到底有没有用"。改进落地了两项，同时我自己犯了三个错，都记下来。

### ① 兑现的两项产线改进（都在生产里跑通）

- **换镜跟着语义走**：`split_beats` 新增读 `qa/beats.json`（`{"max_scale":1.06,"scenes":{"S05":[9.93]}}`）。
  切点由 `make_timeline_extras.py` **从 phrase_timing 取该场 55% 处的真实短语边界**，不填预估值。
  三条护栏：切点越出本场时长 → **FAIL 并打印这场只有几秒**；`max_scale` 给运动语法留口子
  （国潮水墨要求幅度全风格最小，不该被默认 1.11 顶穿）；**项目一旦提供该文件，未声明的场次明确打印
  "保持一镜到底"**，不偷偷退回固定网格——静默降级比没有功能更坏。p18 实测 10 场拿到切点、6 场 ≤6s 明确一镜。
- **音效挂在动作上**：`produce.py` 的 `qa/events.json` 现支持 `(名, 场号, 场内秒, dB)` 四元组，由 produce 换算成全局秒。
  **为什么要按场内秒**：转场时长要等 `gen_transitions` 之后才知道，逼作者先算全局秒，等于逼他把音效摆在场景边界上。
  p17 的 10 个事件音**全部**落在场边界，卡片拍下/锁落下/数字滚到一个都没有声。
  p18 实测 18 个音效（≤R6 预算 20），落在 22.33/24.43、69.93/71.23 这类**成对的动作时刻**。

### ② 我自己犯的三个错（每个都是"以为对了"）

1. **把 `produce.py` 的正确退出码读成 0**。后台任务通知写"exit code 0"，我就以为装配成功；
   实际命令是 `produce.py … > log 2>&1; echo "rc=$?"`——**0 是那条 `echo` 的退出码**，produce 真值是 1，
   日志里明明白白 `FAIL: s03,s16` + `❌ 中止`。这是 §59⑨"验证退出码时接管道"的**同一件事换了张皮**
   （管道 → 后台包装命令）。**判据：只要命令里还有第二个进程或第二条命令，通知里的 exit code 就不是我要的那个。**
   这次我在动手改代码前先 `cat` 了任务输出，看到 `rc=1`，才没去"修一个不存在的 bug"。
2. **把图层 `jitter` 写成 list**。渲染器对**图层** jitter 读 `jitter.get("hold")`（dict `{x,y,rotation,hold}`，模板 `JIT`），
   对**背景** jitter 才用 list `[0,0]`。我为了"关掉水墨抖动"写 `s["jitter"]=[0,0]`，s03/s16 在渲染器里
   `AttributeError` 崩掉 → **431 秒并行渲染跑完才发现那两场是 0 帧**。
   关抖动的正确做法是**删键**（缺省 `{}` → 幅度 0）。已加 `preflight_v6` 的 `[jitter形状]` ERROR 门：
   注入即红、p11–p17 零误报。**这条纯形状判定不该用一次渲染去换**（§63 的"秒级能判定的不许用渲染换"）。
3. **道具摆在哪，我是猜的**。animatic 第一次看：全片道具浮在半空。量了才知道案面在**成片坐标** y≈905(bench)/805(scroll)，
   而我按"画面中间≈675"摆——中间是墙和晾纸架。测量方法：`render_sequence.cover()` 实际裁出那一幅，逐行求亮度，
   取下半部最亮的横带。**"画面中间"不是案面；背景里能站东西的那条带子要用裁完的图量。**

### ③ 预览门 + 全分辨率回看，这两轮各抓到什么

- **animatic（0.35 倍、每 8 帧取 1）抓到**：道具整体浮空（上面 ②3）、S05 后半段 4 秒零事件、两处卡×卡叠印。
- **全分辨率抽帧抓到 animatic 抓不到的**：
  ① **S13「在 GitHub 搜索」根本没被演出来**——我拿一根 `progress` 红线代表"正在输入的文字"，
  观众看到的是空盒子加一条线。改成把 `dive-into-llms` / `动手学大模型` 两串字**从左往右擦出来**
  （`reveal()` = `scale_x` 从 0.02 长到 1.0，锚点在左），"打字"这个动作才成立。
  ② 手绘窗框/代码框 5–6px 白细线在 1080 宽暗底上**几乎不可见**（S06/S08/S09/S13 全受影响）→ 加粗到 11–12px。
  > 0.35 倍缩略图**看不出"线太细"**，因为细线在缩略时被平均成灰。这类"尺度相关"的缺陷只有全分辨率能抓。
- **一条假阳性，我选择不修**：S13 的窗口内打字卡被 R1 呼吸门当字幕卡算，报"落定帧距场次末仅 1f"。
  移到 `assets/lines/` 能消警，但会同时失去 `layout_check` 对文字卡出画/压带的全部保护——
  **用一个假阳性换掉一道真门，不划算**，接受并写进 BRIEF。

### ④ 本片与上一部的实际反差（F 表落地情况）

p17 等距2.5D/深夜服务台/视差 8 开/grain 0/ease-in-out 对称/砸下靠硬停；
p18 国潮水墨·传拓作坊/**视差 16 场全关**/grain 0.04/书写式三段/**slam_squash 全片只 2 次**（且必须删掉它自带的 jitter）。
F 表六项 0 项相同。**"每部比上一部好"这次的可验证部分**：新增两项产线能力（语义切点、动作音效）、
新加一道 jitter 形状门、以及第一次在渲染前就用 `cover()` 量过承载面。

---

## §66 V3.28 用户看片指出的缺陷：画面没演出来，还演错了（讲 Flash 屏上是 Pro）（2026-09-24，p17/p18 复盘）

用户原话：**"画面的展示没有很好地表达文案的意思+语义，也就是没演出来，有时还演错了，讲的是 flash，画面显示的是 Pro。"**
不重做，记下来下次纠正。我把这句话**定位到了具体秒**，根因比"演得不够"具体得多，也**可机检**得多：

| 位置 | 旁白在说 | 画面上实际有什么 | 错在哪 |
|---|---|---|---|
| p17 **S08 第 0.0s** | 「注意免费的是 **Flash**」 | 只有 `p_pro_board`（写着 **Pro**），**整场没有 Flash 板** | 头 2 秒观众听到 Flash、看到 Pro |
| p17 **S03** | 「**Flash** 是 309B 的小一号版本」 | 两台机器**都没贴名字** | 演了"小一号"，没演"哪一台是 Flash" |
| p17 **S09** | 「Pro 顶配…输入 3 块」/「Flash 便宜够用…输入 1 块」 | 四张价签烤的是「输入/输出」+ 数字 3/6/1/2 | **没有任何一处标明哪一列是 Pro、哪一列是 Flash** |

**根因（一句话）**：给道具烤字时烤的是**属性**（输入/输出、数字），没烤**名字**（Pro/Flash）。
口播点到名字的那几秒，画面上要么没有那个名字，要么站着**另一个**名字。

**这不是"创意不够"，是映射缺项**——`sut.json` 里我确实写了"哪个词被演出来"，但
**没有一处把"口播提到的专有名词"和"画面上带这个名字的层"对上账**，所以 semantic_check 全绿、A 级 97% 也照样演错。
（p18 同类：`prop_block_chNN` 烤了章名，但 S02「两门课」的两摞讲义、S13 搜索框里的字，都靠字卡说，道具本身没带身份。）

### 下一部片起执行的三条（前两条可机检）

1. **身份先于属性**：凡口播会点名的对象（型号/产品/机构/人名/章节名），**该对象在画面上的第一次出场就必须带着这个名字**，
   属性字（数字、输入/输出、价格）是第二层。做 `bake()` 时先问"这东西会被点名吗"。
2. **对账门（要写）**：从 `chunks.json` 抽出每段的专有名词与数字，按 `scene_timing` 算出该段的**场内时间窗**，
   断言"窗口内至少有一个可见层的 `label` 含该名字"；**若窗口内出现了同类的另一个名字 → 直接 FAIL**（这就是 Pro/Flash 那一格）。
   需要给层加一个 `label` 字段（bake 时顺手登记，成本极低）。
3. **交片前做一次"静音看"**：不看声音只按时间轴读画面，逐场问"这段在讲谁"。
   我此前的抽帧回看是**按语义点抽样**（12 帧/112s），只查构图与可读性，**没查"名字对不对得上"**——
   因为我根本不知道旁白那一刻在说哪个名字。这条是方法论缺口，不是密度缺口。

**为什么我这次没能自己发现**：我的全部判据（A 级占比、关键帧升序、卡×卡叠印、拥挤度、对比度）
测的都是**画面内部是否自洽**，没有一个测**画面对旁白是否忠实**。用户一听就听见了。

---

## §67 · p19 实录：§66 的门落地了，以及"门自己会撒谎"的四种形态

p19（小米 18 Pro 评测）是第一部**带着名字对账门跑完**的片。`scripts/name_ledger.py` 在真实场景数据上
一次抓出 3 处 §66 形状缺陷——念"小屏 18 Pro 5999 起"时屏上只有"价格"；念"透明版就是收藏"的头 19 帧
屏上站着兄弟名"小米 18 Pro"；MiMo 徽章只盖住 45%。**前 17 部片没有任何一道门能发现这三件事。**
门已焊进 `produce.py` 的渲前门链（NAMES.json 不存在时只 WARN，不误伤历史片）。

**这一节真正要记的是另一件事：抓出第三处缺陷的过程中，门自己暴露了 bug。**
口播把「透明特别版」缩略说成「透明版就是收藏」，字面匹配失败，旧版**静默回退到该段第一句**当窗口——
于是它去查了错误的时刻，还把"画面没问题、名字没被说"误报成 FAIL。
教训：**任何"找不到就退到默认值"的兜底，在门禁里都是造假机器**。改成定位不到就明说、要求补 `anchor`。

同类"门在撒谎"这一部又撞见三种：

1. **GBK 假红**（最贵的一种）。中文环境子进程默认 GBK stdout，门一 `print("✓")` 就抛
   UnicodeEncodeError 崩掉 → 编排器读成 rc≠0 → 报一条**根本不存在的配色 FAIL**；同一处还把别的门的
   中文输出解成乱码，连真消息一起埋了。`produce.run_retry` 更糟：先当"偶发失败"重试两遍再中止
   （p18 我追过的幽灵失败就是它）。根因收进 `env_paths.CHILD_ENV` 单一事实源，
   并一次给 36 个脚本补了 `sys.stdout.reconfigure` 兜底——**编排器传 env 救不了"从 shell 直接跑"**。
2. **开工模板假阳性**。§61 的完成度门用 `| S0N` 正则数 B 表行，结果 E 段"渲完第一眼检查"的 3 格复盘行
   被当成没填满的 8 格开工行，**已交付的 p18 被判红**。修成只在 `## B.` 段内数。
   修完双向验过：真空格仍会红，p17/p18 转绿。
3. **账本门 124 条"未登记"**。生图的 16 张自动入账，但 PIL 产的字卡/线/抠好的道具 412 条从没进过
   `register_assets.py`。时机写在它自己的 docstring 里（cutout+make_cards 之后、render_all 之前），
   只是我这次跳过了。

**生图模型的两个默认偏差**（都是目检抓到、指标抓不到的）：
- 让它画"智能手机背面"，它默认画 **iPhone，还带苹果 logo**。p19 主角机第一次出图就有咬合苹果。
  必须在 prompt 里写死 `generic Android-style slab, NOT an iPhone, no apple logo, no bitten-fruit mark`
  并把镜头排布指定成"横排"（三角三摄 = iPhone Pro 语言）。撞名题材（同期在售 iPhone 18 Pro）里这是硬风险。
- **洋红底会把白色主体染成粉色**。要"浅灰机身"的道具全部出成粉机身。修法：prompt 里显式钉死主体色
  并加 `absolutely no pink or magenta cast on the object itself`。

**背景一律出真竖版**：`gen_assets` 的 `size` 是 **HxW**，传 `"1184x896"` 得 896×1184 竖图。
方图 1024² 在 1080×1440 上 cover + scale 1.10 后**横向只有 68% 在画内**（设计在画外的 32% 全是白做）；
竖版是 90%×91%。这条直接改变"按裁切窗口判候选"的工作量——可见区几乎等于整图。

**白板题材特有的一条**：全片前景都"念到才画出来"，于是 13 场第 0 帧全是裸背景，被
`first_frame_check` 整体拒绝渲染。解法不是加装饰，而是让**图腾兼任舞台锚点**——那支橙红马克笔
从第 0 帧就躺在板槽里、opacity=1，要画才抬起来。

**还有一处只有眼睛能看见的错误**：字卡里把数字烤死了（"5999""45%""7000 毫安"），滚数层又在滚同一个数，
于是**片子里每个数字都出现两遍**，九处全中。规则：**数值一律只由 `seq_` 滚，卡上只留名字/配置/单位**。


---

## §68 · p20 素材阶段：一条只写在文档里的规范，和四处"修复其实是死代码"（2026-09-25）

p20《小米 18 背屏是刚需还是智商税》。世界 = **整块画面就是那块背屏**。这一轮的钱和時間
全花在**素材**上：9 张图重出、5 处抠图改判据、6 道渲前门从 21 条 HARD 打到 0。
成片数据见交付后补记。

### 1. 四张背景全是 iPhone——规范没被任何代码执行过

拿到手的 `bg_panel_a/b/c` + `bg_desk_a`：一张刘海屏、一张灵动岛、两张三角三摄 + LiDAR 的
**写实苹果产品照**。而全片主风格是**剪纸拼贴**，世界设定是"一块深色玻璃面板"。

两个根因，都不是模型的错：

1. **prompt 里出现了 `smartphone` / `phone`。** 这一个词就把模型拉回"手机产品摄影"的先验，
   后面写多少 `shown straight on as a flat backdrop` 都拉不回来。改法：通篇只说
   "一块深色**剪纸面板**"（`a flat rectangle of deep blue-black matte card stock, die-cut
   with visible paper fibre edges`），设备名词一个不留，另加 `no notch, no dynamic island,
   no camera bump, no brand marks`。
2. **`--style 剪纸拼贴` 我根本没传。** `style_presets.suffix()` 会追加
   `paper craft, paper cut art, layered cut paper with visible paper edges, subtle shadows
   between layers, …` + COMMON_NEG。这一串一个字都没进 prompt。

`gen_assets.py` 第 65 行的注释写着"契约只准带骨架，**皮肤归 `--style` + `palette.json`**"。
这条契约**从来没有被任何一处代码校验过**。所以：整批素材跑偏，六道渲前门全绿，
一直到我把图拼成 contact sheet 用眼睛看才发现。

**机制化**：`gen_assets._assert_style_declared()`——`palette.json` 有 `style_primary`
且（没传 `--style` 且 jobs 没有逐条 `style`）→ `sys.exit` 拒生图。风格名按 `·`/`（` 截主名
（`剪纸拼贴·背屏玻璃` → `剪纸拼贴`）。RED/GREEN 双向验过：p20 未传 → RED；传了 → GREEN；
逐条带 style → GREEN；未声明风格 → 放行（不假红）。

> **判据**：凡是只写在文档/注释里、没有任何一处代码校验的规范，等于没有规范。
> 它不会保护你，只会在事后让你觉得自己粗心。

### 2. `import sys` 漏了 9 个脚本：UTF-8 修复一直是死代码

V3.22 之后我给一批脚本加了
```python
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
```
但 **9 个文件根本没有 `import sys`**（`aesthetic_check / asr_alias / env_paths / make_countup /
make_text_cards / narration_layout / num_equiv / render_sequence / cutout_key`）。
`sys.stdout` 抛 NameError → 被 `except Exception: pass` 吞掉 → **这段"修复"从未执行过**。

发现过程很偶然：`cutout_key.py --help` 在我这个 shell 里直接崩栈（argparse 往 GBK stdout
写 `⚠`）。也就是说 §67 里那条"GBK 假红"的根治，在九分之一的面积上根本没生效。

**两处一起改**：补 `import sys`；guard 收紧成 `except (AttributeError, ValueError)`，
让 NameError 必须响。63 个文件的 guard 全部收紧。

### 3. 最贵的一处：帧预算被一个兜底静默降级

`audio_duration.py` 是同一个病。而 `build_scenes_template.load_phrase_timing()` 写着：
```python
try:    from audio_duration import duration as _ad
except Exception: _ad = None
if _ad is None:
    print("⚠ audio_duration 不可用 → 只能用 ASR 语音跨度做帧预算, 画面会偏短")
    return timing
```
V3.24① 用整节写"`dur` 是 ASR 语音跨度、系统性短于 mp3 实测，拿它做帧预算 → 画面比旁白短"。
**然后一个 `except Exception` 把这个教训整条绕过了**，还只 print 一行 ⚠。

改为：导入失败 → `SystemExit`；任何一段缺 mp3 → `SystemExit`。

**回放已交付的三部片**（p17/p18/p19，共 59 段）：`phrase_timing.dur` 与 mp3 实测差
**最大 0.000s**。因为 `word_timing.py` 写盘时用的就是 mp3 值，V3.24① 的覆盖逻辑其实是
一道**空转的保险**。所以已交付的片子没有偏短——这条我量过才写。

> **判据（用户原话）**：门里不许有"找不到就退默认值"的兜底。
> `except Exception` 会把你的修复和修复的失败一起吞掉。

### 4. `key_band_conflicts` 第二版假阳性

V3.24④ 修过一次（"只查作者写的 prompt，不查注入后的"）。这次它拦住了**作者自己写的
`#FF00FF`**——而道具契约的 `PROP_CONTRACT_CHECKS` 恰恰**要求**作者写
`isolated on pure solid magenta #FF00FF background`。于是整批道具当场被挡死。

现只放行 DEFAULT_KEY 本身；其余落在键色带（PIL H 195–248 且 S>64）的十六进制照旧 FAIL。
双向验：`#FF00FF` → 放行；p16 那个真缺陷 `#E4377B` → 拦；两者混写 → 只报 E4377B。

### 5. `layout_check` 的字卡判据：我差点给未来造 7 条假阳性

原判据 `"c_" in id or path.startswith("assets/text/")`。p20 的报纸栏底片 id 叫 `c_data`
（在 `assets/lines/` 下、无 label），被 `c_ in id` 当成字卡，于是压在它上面的机型名牌
`c_17pro` 被判 **SEVERE_OVERLAP 1.0**。

我第一版把它改成按数据判：`assets/text/` **或带 label**。听着讲道理。**回放 p17/p18/p19：**
p19 从 hard=0 变成 **hard=7**——因为 p19 给道具也登记了 label（`p_phone_big` 等），
带 label 的**道具**被当字卡量矩形。p17/p18 也各少 1~2 层（`p_doc_in`、`p_arc_over` 原来被误算）。

退回原判据，只加一条显式退出 `decor: True`。三个历史片复核：hard 0 / 0 / 0，与改动前一致。

> **判据（用户原话）**：假阳性比漏报更致命。改判据必须**回放历史片**，
> 一个"更讲道理"的判据如果让三部已交付的片子凭空多 7 条红，那它就是错的。

### 6. 抠图：粉洋红**渐变**底必须走 `--hsv`

V3.16①/V3.17① 说 `--hsv` 用于"红主体 + 粉洋红底"。p20 补上另一半：
StepFun 这次输出的底不是纯色，是 (201,45,103) 的**渐变 + 光柱**。边框中位键色法
（Chebyshev 距采样中位）对渐变无能为力——5/5 张道具全留下**粉色光柱和粉边**。
`--hsv` 按色相带判背景，光柱全净；代价是外缘变毛糙。

**毛糙在这个风格里不是缺陷**：剪纸的语言就是撕边。半透明像素占比 13.6%→3.7%。
反向仍成立：`prop_paper_ball` 的底是**中性灰**（S≈0），`--hsv` 完全判不出背景，
必须走键色法。**结论：看底的饱和度选抠图法，不看主体颜色。**

### 7. 建场阶段的机械修复（21 条 HARD → 0）

| 现象 | 根因 | 改法 |
|---|---|---|
| 一次 21 条 SEVERE_OVERLAP | `land()` 从 **360px 高空**砸下，卡片在半空**穿过它头顶的标题**；layout_check 按每帧 bbox 判 | 落程 150。挤压回弹照样读得出重量 |
| S03 一次中 9 条 | "折走"写成**原件 land + 折件 fold 两张同位**，自己坐在自己身上 | `land_fold()`：一张卡自己砸下来、自己折走 |
| S12 一叠卡互相吞 | 往上摞，后落的必然穿过先落的 | 改成**从下方摞上来**（slide，起点在目标下方 110px） |
| 一次报 41 个假"越界" | `_CUR["bg"]` 只在 `build()` 里设，而层是在 `build()` **之前**构造的 → 全场拿**上一场**的可写区夹帧 | 每场第一行必须 `begin(s, bg)`；`build()` 断言两者一致 |
| 滑入变成"原地淡入" | `clamp_xy` 把 slide 的**起点**也夹进可写区 | `allow_off`：起点允许在画外，落点仍夹 |
| chunk_12 有 1.5s 旁白没画面 | 我为了消一条同位重叠，把 `c_use` 删了，没给它替代动作 | `punch()`：主摄原地放大顶到眼前。`preflight [节奏]` 门当场报了这条 ERROR |

### 8. 两份清单从不互查

`bg_desk_a` 里已经画了一块桌上的圆角面板，我又为同一主体生成 `prop_phone_facedown`
——同一空间里两台设备，道具无处可用，废 1 张图。**根因：背景清单和道具清单没有任何
一处会互查。** 开工前把两张单子对一遍。

### 9. 我自己又犯了一次 §58⑨

判 `name_ledger` 退出码时写成 `py name_ledger.py … | tail -30; echo rc=$?` →
拿到的是 `tail` 的 0，而它其实 rc=1。**第三次了。** 固定写法：
`cmd > log 2>&1; echo "rc=$?" >> log`，读日志不读通知。

---

## §69 · p21 素材与音频阶段：一条子串把契约判成"已声明"，和一次静默的 12 段配错音（2026-09-26）

p21《腾讯新出的生图模型，限时免费》（Hy Image 3.5 Preview，12 场 / 28 chunk，成片 107.4s，
审美 79.4，整片 ASR 12/12=1.0，六门全绿）。这一轮的价值全在**"检查器自己判绿了而事实是错的"**
一类事故上——五处，其中一处如果没被 `asr_spotcheck` 拦住，会直接交付一部**口播和画面说的不是一回事**的片子。

### 1. `enforce_prop_contract` 用子串判"是否已声明键色底"——三张样张差点被抠穿

道具契约要求每条 prop prompt 必须声明洋红底，代码写的是：

```python
if "magenta" not in p.lower():   # 不通过就自动追加条款
```

我给三张"打印样张"写的 prompt 里有一句 **`no pink or magenta cast`**（本意是"别给纸面染色"）。
子串命中 → **它以为作者声明过了**，一条追加也没做。生出来的底是**摄影棚中性灰**。

后果不是"难看"而是**功能性报废**：样张是白边相纸，白边 vs 灰底的亮度差只有 **31**，
而键色法的中位距离阈值 `t0 = 45`——**白边会被当成背景直接抠穿**，四张白框全空。

修法：判据从子串改成**整条条款** `solid magenta #ff00ff background`；RED/GREEN 双向验
（写 `no pink or magenta cast` → RED；写正规条款 → GREEN；漏写 → 自动补）。6 张道具全部重生。

> **判据**：契约检查**不许用关键词子串命中**。一个"`X` 出现即算声明"的门，会被
> `no X`、`avoid X`、`X-free` 这类**否定句**骗过去。要么匹配整条条款，要么匹配肯定句式。
> 这和 §68① 的 `smartphone` 是同族——**门读的是字面，不是意图。**

### 2. `bulldog clip` 生成了一只货真价实的斗牛犬

`prop_clip` 的 prompt 我写的是 "a paper bulldog clip"（燕尾夹的英文就叫 bulldog clip）。
模型忠实输出：**一只斗牛犬**。删掉所有动物词，只给几何描述
（`two triangular wire handles hinged to a flat rectangular base, black matte wire`）即对。

这是 §68① "一个名词就把模型拉回整个先验"的第二次实录，且**更难防**：
`smartphone` 我知道危险，`bulldog clip` 是一个**我以为自己在说五金件**的词。

> **补进生图规则**：道具命名遇到"**复合名词里藏着一个生物/品牌/产品名**"时（bulldog、
> python、turkey、jaguar、camel、mercury…），一律**拆成几何描述**，一条词都不留。

### 3. 最贵的一处：12 段旁白配错了音频，而且**一声不响**

为了修一段坏的 TTS，我把 chunk_16 并回 chunk_15，**后面所有段号整体前移一位**。
然后我手工把 `assets/audio/.tts_stamps.json` 的 key 改对了，却**没有重命名 mp3 文件**。
`generate_tts` 的复用逻辑是：

```python
if out.exists() and stamps[c["id"]]["sig"] == sig:   # 按段号找文件
    复用
```

段号 16 的哈希恰好和旧 16 的哈希不同（文本变了），但我改 stamps 时**把 sig 也一起搬过去了**——
于是 12 段全部"命中复用"，**每一段配的都是隔壁那句的口播**。

六道渲前门 + 渲染 + 混音 + aesthetic + clutter **全绿**。它们没有一个会去听"这段音频在说什么"。
抓住它的是 `asr_spotcheck`——它是全产线**唯一**把音频转回文字再比对原文的门。

**两处机制化**（`generate_tts_template.py`，已回填 p21）：

```python
stamps[c["id"]] = {"sig": sig, "text": spoken}      # 复用时连原文一起验
...
if ... and _st.get("sig") == sig and (_pt is None or _pt == spoken):
```

即：**sig 对上还不够，原文必须逐字相等**才允许复用。改稿必然换文本 → 不可能留下"行不对音"的旧 mp3。
旧格式（裸字符串 sig）走 `_pt is None` 分支放行并当场补写，不假红历史项目。

顺带扫出同类假绿 3 个文件：`import sys as _sys` **不绑定裸 `sys`**，
所以 `sys.stdout.reconfigure(...)` 里的 `sys` 仍然是 NameError，仍然被 §68 收紧前的
`except Exception: pass` 吞着。`mix_audio4.py` / `production19/mix_audio.py` / `production21/mix_audio.py`
补成 `import sys`。

> **判据（本条最一般化的一句）**：**凡是"改一个编号体系"的操作，必须同时改所有以该编号为文件名的东西。**
> 只改台账不改实体 = 台账全绿、实体全错。跨层级映射禁用序号对齐（§58①）在**手工编辑**上的翻版。

### 4. TTS 的 5 字孤句：先截断、再凭空多念两声"哈哈"

chunk_16「国内直接用」（5 字）独立成段。第一 take 时长 **0.72s 且尾部无静音**——句子被吞了。
重录 → 模型**凭空多念了两声"哈哈"**。两取互异，且都不是文案。

修法不是继续重录，而是**并回上一段**（只改分段、不改一个字）。并段后一次过，相似度 1.0。

> **规则**：同一短句**重录两次仍失败**即判为结构性问题（韵律缺上下文），转**分段修法**。
> 这和 §59⑧「同音字死区」的处置顺序是一对：那类**音对字错**先做只加标点的最小干预；
> 这类**音本身就不对**要动分段。两者的共同底线是**不为讨好检查器改口播措辞**。

### 5. 我杀了一个正在跑的 `produce`，代价是四场坏帧——以及省下的 300s

`produce.py` 我漏传 `--skip-render`，它从第 1 场开始重渲。我发现后直接杀掉，于是
**scene 01–04 的帧序列被写到一半**（后半段还是新帧、前半是旧帧的混合体）。

恢复流程里真正有价值的是**先测再动**：我担心重渲必须全量，就先用 md5 比对
`split_beats` 跑前跑后的全部场景 JSON——**逐字节相同，确认幂等**。既然幂等且 JSON 没变，
只需重渲损坏的 4 场（约 120s）而不是全量 420s，**省 300s**。

> **判据**：遇到"我搞坏了中间产物"，第一动作是**量化损坏范围**（哈希/逐帧比对），
> 不是"保险起见全部重做"。效率是用户硬约束，而"全部重做"看着稳，其实是把判断外包给了算力。

### 6. 三轮构图调整，零收益：三个假设全部被我自己证伪

p20 归因说"深色大面板 + 小纸卡"导致 balance/salience 掉。p21 我据此换了世界设定
（暖白相纸地 + 样张占画面 40–55%），又追加两轮定向修法。**结果 79.6 → 79.4，没起来。**

| 假设 | 做法 | 实测 |
|---|---|---|
| ① 地色太深、主体太小 | 换暖白地、主体放大到 40–55% | balance +0.014 / salience +0.027 / align **−0.046** → 净 +0.2 |
| ② 元素分布太集中 | 量三片 39 场的元素中心离散度 | **假设当场作废**：p21 X 离散度 232 是**三片最大**（p19 219、p20 197） |
| ③ 内容左倾、右半空 | 抽 36 个"名字时刻"拼一张图，肉眼确认左倾后把行组推到中轴、比较条移右 | 审美 **−0.2** |

唯一量出来的相关是 `在场层数 ↔ 审美分 r = +0.413`（三片 39 场合并）。但 p21 平均层数 8.5
夹在 p20(7.4) 与 p19(9.2) 之间，**分数却和 p20 一样**——层数也只是相关不是因。

真正的短板是 **align 0.632，三片最低**，而它是**我自己换来的**：§59⑤ 记过"吸附网格买 align、
赔 salience"，p21 为了保 salience 故意把元素摆离网格轴。**这是同一笔交易，不是 bug。**

> **结论（写给自己的，也是 §57④"弱代理门宁可不写"的延伸）**：
> aesthetic 这条尺子奖励"**多、小、对齐网格**"的布局，而我这两部在做"**少、大、手工摆位**"的拼贴。
> **再对着分数调坐标，就是拿内部尺子改创作**（用户 2026-09 明令禁止）。
> **p22 起不再为 aesthetic 分改构图。** 要改，就从"这片发生在什么地方"改；
> 验收交回用户的眼睛，两部并排看。

---

## §70 · 用户看片指出"最近几部风格有点像"——量完之后：颜色不背这个锅，门才是（2026-09-26，p20→p21 之后）

用户问："你是在偷懒吗？" 我去量了，没有靠印象回答。**结论是三条，只有一条算偷懒。**

### 1. 先否掉我自己的第一条解释（我猜错了）

我最初的判断是"KICKOFF 的 A2b 运动语法写着**逐字抄自 style-presets 那一行**，
所以同风格 = 动效词汇表相同"。把五部片的 A2b 表解析出来逐行 diff：

| 相邻对 | 预设列相同 | **本片填列相同** |
|---|---|---|
| p17→p18 | 0 | 0 |
| p18→p19 | 0 | 0 |
| p19→p20 | 0 | 0 |
| p20→p21 | **5/6** | **0** |

预设列确实逐字相同（同风格必然如此），但**"本片填"那一列六行全不一样**——
我在纸面上做了差异（吐片节奏、全片禁 `ease-in-out`、视差三层分配、颗粒 0.08 vs 0.07、相机按场型分）。
**所以"我没差异化"这个指责不成立；成立的是"差异化没落到缓动上"。**

再量成片像素（每部抽 14 帧、5bit 量化色分布、直方图交集，1.0=同分布）：

| 对 | 色分布相似度 | 主风格 |
|---|---|---|
| p17–p20 | **0.802** | 等距2.5D / 剪纸拼贴 |
| p18–p20 | **0.792** | 水墨 / 剪纸拼贴 |
| p17–p18 | **0.784** | 等距2.5D / 水墨 |
| p19–p21 | 0.576 | 白板 / 剪纸拼贴 |
| **p20–p21** | **0.331** | 剪纸拼贴 / 剪纸拼贴 |

**最像的三对是那三部深色台子**（深夜服务台 / 传拓作坊 / 黑玻璃背屏），
而 p20↔p21 的颜色差别是全场第二大。**跨片资产 md5：p20/p21 之间 0 个重复。**
所以用户眼睛看到的相似，**既不是颜色也不是素材**——是**运动语言**。

### 2. 唯一算偷懒的一条：主风格档连用了两部，我没主动换

p17 等距2.5D → p18 水墨 → p19 白板 → p20 剪纸拼贴 → **p21 剪纸拼贴**。
四连换档之后我第五次没换。世界设定换了（背屏玻璃→冲印打样台），**档没换**。
这不是模板逼的，是我在 `pipeline setup --style` 那一步顺手又填了同一个词。

### 3. 最贵的发现：**门早就报了，是我把 WARN 吞了**

`novelty_meter.py` 的 D3（缓动分布与上一部余弦 >0.92 判"动效语言趋于模板"）**在 p20 和 p21 各报过一次**：

```
WARN: D3 缓动分布与上一部相似度 0.98>0.92——动效语言趋于模板,换主缓动或加新动效
```

而 D3 的实测分离度非常干净——**不同风格的历史对最高 0.873，同风格的 p20→p21 是 0.983**：

| 相邻对 | 缓动余弦 | 同主风格档？ |
|---|---|---|
| p17→p18 | 0.873 | 否 |
| p18→p19 | 0.064 | 否 |
| p19→p20 | 0.185 | 否 |
| **p20→p21** | **0.983** | **是** |

**这个门有判别力、零假阳性、而且已经点亮过两次。**它拦不住的唯一原因是：
文件头写着"全部 WARN 级，不拦渲染"，`main()` 结尾 `return 0` —— **它咬不了人。**
（§57① "门禁退出码"、§62① "门建了没接线"的第三次同族事故：接了线、也报了警，
但退出码被设计成恒 0，于是报警等于没报。）

### 4. 顺手挖出的另外三处空转

| 空转 | 实测 |
|---|---|
| **D6 风格连用检测是死代码** | 它读 BRIEF 的 `主风格: xxx`，且只认 `cutout/chalk/popup` 三个英文字面。五部片**命中 0 次**（我们写的是「剪纸拼贴·背屏玻璃」这种中文），所以 D6 从来没跑起来过 |
| **彩带五部片逐字节相同** | `new_project.py` 把 `_templates/confetti_sheet.png` 按字节拷进每个项目，p17→p21 md5 全等；而账本写 `production=<本片>`、`origin=template` → **preflight 那条"出生地≠本片即跨片复用"的门被账本自己撒的谎遮住了** |
| **隐喻防撞门从不真跑** | `pipeline ready` 调的是 `metaphor_ledger check --film X`，**不带概念参数** → 永远打印"新概念 0: (无) PASS"。p17/p18/p19/p21 在账本里 0 条概念，p20 有 5 条但键写成 `p20`（其余全是 `productionNN`），归一比对对不上。§57⑤ 给 `first_frame_check` 堵过的"空输入报 PASS"，这里原封不动存在 |

### 5. 修了什么（每条都做了 RED/GREEN 双向 + 历史回放）

1. **`style_presets.base()`** —— 风格主名归一的**唯一实现**（截 `·（(/` 再去掉所有空白，
   所以「等距 2.5D」与「等距2.5D」同键）。`gen_assets._style_base`、`novelty_meter`、
   新门三处全部改为调用它。13 部历史片回归：只有 `剪纸`(p11 旧名)、`赛璐珞分层`(p15)、
   `工程爆炸图`(p16) 不在 STYLES 键里——**这三条是"频道首用风格没进预设库"**，已记录不硬改。
2. **新硬门 `motion_similarity_check.py`**（挂进 `render_all` 渲前链）：
   主风格 base 不同 → 直接放行；**同 base 且 缓动余弦 >0.92 或 主导缓动相同 → rc=1 拒渲**。
   回放：p18/p19/p20 **全绿**，p21 **红**（余弦 1.000/0.983 + 主导 `ease-out` 同为两部第一）。
   出路四条写在报错里。逃生口 `A2c · 与上一部的运动差异:` 需**≥30 字 + ≥2 个场名 + ≥2 个动效词**，
   实测四种偷懒写法（无声明/只 1 场/只 1 个动效词/短空话）全部仍红，合格写法才降为预警。
   - 动效词匹配用**最长优先**：第一版直接子串判断，`ease-in-out` 同时命中 `ease-in`+`ease-out`，
     一句只提一个缓动的空话就凑满"两个动效词"把门洗白——**这是我给逃生口写出的第一个假绿，自己测出来的。**
3. **`make_confetti.py`**：彩带按本片 `palette.json` 的 accent/accent2/fg/bg 派生 8 格重绘，
   并**改写账本**（sha256 跟着变、`origin=palette_tinted`）。接进 `pipeline setup`（配色落地那一刻），
   `ready --stage assets` 加 `--check`（有配色却仍是模板原件 → 红）。
   精灵盒从 `build_scenes_template.motes()` 的**真实产物**读，不再抄第二份字面量
   （第一版我按"500 宽 ÷ 60 步"自己推，推出第 9 格越界 `IndexError`——§59⑩ 同族）。
4. **`novelty_meter` D6 复活**：风格改读 `palette.json.style_primary` + `base()`；
   `pipeline setup --style` 现在**当场**提示"主风格档与上一部同为 X"，不等渲染。
5. **隐喻门接上真输入**：`ready` 改读 `productionN/qa/concepts.txt`（一行一个概念）传给
   `metaphor_ledger check`；`check` 在**零概念时改判 FAIL**（空输入不是通过）。
   账本里 `p20` 的 5 条键归一为 `production20`，并回填 p17/p18/p19/p21 共 14 个核心图腾概念。
   回放：拿 p21 的三个概念去给新片盖章 → **红，且精确列出撞在 production21 名下**。

### 6. 判据

> **用户看到的"像"，通常不在你最容易想到的那一层（颜色/素材），而在时间维度上（运动）。**
> 所以查相似要按 像素→素材→运动 三层分别量，别用一层的结论替另一层辩护。
>
> **一条 WARN 如果被设计成 rc=0，它就等于没有。** 已经有判别力、已经点亮过的门，
> 优先给它牙齿，而不是再写第六道新门。（本轮 D3 就是现成的：0.873 与 0.983 之间干净分离，
> 历史上零假阳性——我不需要发明任何新指标。）

---

## §71 · p22《AI 自己找到了一套新酶系统》：V3.31 那三扇新门第一次真上岗（2026-09-26）

p22 是 V3.31 之后第一部片。**这轮不报新工具，只报"新门到底咬没咬到"**——
上一轮为"用户说几部片风格有点像"装了三样东西：`motion_similarity_check`、
`make_confetti`、配色双门。答案：咬到了，而且咬的地方和我预判的不完全一样。

### 1. 换档真的换了：审美 87.9（频道新高，前高 p19 84.6；p20/p21 都是 79.4）

主风格档从连用两部的「剪纸拼贴」换成**从没当过主风格的「复古报纸」**，
世界 = 一间没窗的档案库房 + 卡片目录柜。11 场 / 30 段 / 129.3s / −14.0 LUFS /
七道渲前门全绿 / 整片 ASR 11/11 ≥0.955 / TTS 抽检 **30/30 = 100%**（含 ART、CRISPR、
Harrington、Token 四个专名，历史上第一次一段都没掉）。

**但"换档"本身不值分——换档 + 换配色才值分。** 我第一版四色是
暖纸 202,196,178 + 砖红 142,38,33 + 绿 36,124,88，`palette_oklch` 当场 WARN：
**与 p21 平均 ΔE 只有 0.111（<0.15 判撞色）**。也就是说：世界换了、风格档换了，
**颜色上还站在 p21 的地上**。换成橄榄褐 150,150,120 + 黄铜 246,222,104 + 酒红 96,28,30 后
ΔE 抬到 **0.276–0.314**，两道配色门同时绿。

> **判据**：`palette_ledger`（旧 HSL 门）在 p22 第一版上判"与 p21 相似度 70%"——**它是对的**，
> 不是假阳性。我一开始想按 §68⑤ 的规矩"回放历史片、怀疑门"，
> 结果用 OKLab 逐位距离量了全部 21 部才发现：**我的候选确实和 p21 同族**。
> 先量再下结论，别先怀疑门。

### 2. 三条新门/新账本的战果

| 门 | 战果 |
|---|---|
| `motion_similarity_check` | 主风格 base 不同 → 直接放行（**这是正确行为，不是没抓到**）。它只在"同档连用"时咬人；p22 因为换了档，本来就该绿 |
| `make_confetti --check` | 拦下一次：`pipeline setup` 时 palette.json 还没写，彩带按**预设旧四色**重绘了；我后来手改配色 → `ready` 判"仍是模板之外的颜色"不成立但彩带确实对不上 → **重跑 `make_confetti` 才盖章**。教训：**改完配色必须重跑彩带**，已写进 setup 的提示 |
| 隐喻账本接上真输入 | p22 交 8 个概念 → 绿；我拿 p21 的三个概念（出纸口吐片/红笔批注/打样条）冒充 p22 去盖章 → **红，并精确列出撞在 `production21` 名下**。这道门从"永远 新概念 0: (无) PASS"变成有判别力 |
| 配色账本补登记 | 发现 `palettes.json` 只登记到 p16，**p17–p21 五部的配色从没进账** → 补登，并把 p22 也登记。现在门比的是 20 部，不是 6 部 |

### 3. 建场阶段被门拦下的六类错（全部是**我的错**，不是门的错）

| 现象 | 门 | 根因 |
|---|---|---|
| 16 处"念了名字但屏上没有" | `name_ledger` | 承载名字的卡我用了 `tap()`——它 **19 帧后淡出**，而门要求点名窗口内可见 ≥60%。**"闪一下"≠"说出来时它在"** |
| 改成常驻后 12 条 SEVERE_OVERLAP | `layout_check` | 还是 §64 那条：`land()` 的 150px 落程让卡在半空穿过它头顶的卡。**解法不是缩短落程，是定车道**：x∈{330,780}、y∈{400,660,920,1160}，卡半宽≤215、半高≤130 → 相邻车道几何上不可能相交；下排卡改走**从下方升起**的 `slide` |
| `assets/text/agents950 目录不存在` | `preflight [账本]` | `num()` 自己会加 `seq_` 前缀，我又传了带前缀的名字 → 目录与 id 两处口径不一致 |
| `tap() got an unexpected keyword 'label'` | Python | 原语签名漏了 `label`——**§66 要求每层都能带 label，原语必须逐个支持**，否则名字只能挂在少数几种动作上 |
| 41 个 anchor 里 10 个对不上短语 | `gen_names` 自检 | 我截锚点短语时把标点也截进去（「智能体，连」）。改成**截到标点为止**后 0 失配 |
| `name_ledger` 抛 `KeyError: 'spoken_in'` | 门自己 | 我的 NAMES.json 用了 `scenes` 不是 `spoken_in` → **门以 traceback 收场，看不出是表写错还是门坏了**。已给门加显式 schema 报错（§57④ 同族） |

### 4. 两条"门不查、只能靠眼睛"的（第 N 次确认）

1. **`seq_` 读数与字卡的重叠，七道门一道都不查**（layout_check 的比对集合里没有 seq 层，§64 就记过）。
   这次是全分辨率抽帧看到「21 小时」正压在「AI 筛完，人接着验」卡上，把字遮掉一半。
   重渲一场（560 帧 ≈ 150s）+ 重出片才修掉。**别假设这条已经被修好了——它还在。**
2. **背景上的同色压印假字（「DOCATEM」），差值掩膜抓不住**。
   我先按"暗笔画"抹 → 命中 37 像素，字几乎没动（它是**比纸还亮的浮雕**）；
   再按"亮笔画"抹 → 残留 9.3%，并且**留下一块比原字更显眼的补丁**。
   正解：**重生那一张** + prompt 写死 `ABSOLUTELY NO LETTERING ANYWHERE … no embossed words, no debossed letters`。
   > **判据**：手涂是把一个缺陷换成另一个**更明显的**缺陷。
   > 素材级的问题回素材层解决；只有"尺寸/位置"这类几何问题才值得在 JSON 层改。

### 5. 效率账

- 全量渲染 3879 帧 / jobs 4 = **676s**；改一张背景只重渲用它的 2 场（942 帧 ≈ 150s），改一处读数只重渲 1 场（560 帧）。
- 出图 12 张 → 目检发现 2 类缺陷（道具底是奶白不是洋红 ×2、背景长假字 ×1）→ 重生 3 张。
  **`enforce_prop_contract` 这次没放人**（V3.30 改成整条条款匹配后，洋红底全部到位），
  但**"底是不是洋红"这件事门查的是 prompt 文本，不是像素**——奶白底那两张是**外圈中位色**量出来的。
  > 下一步该补的门：**生成后量道具外圈 12px 带的中位色，不是洋红即 FAIL**。本轮先手工拦。

---

## §72 · p23《小米 18 Pro 翻车》：用户把 p11 定为下限，我去量"下限"到底是什么（2026-09-27）

用户原话两句，构成本轮的全部判据：
> 「按照 production11 的画面的风格做视频。其他按照最新标准做！」
> 「我说过 P11 是下限……结果后面做的，都没有觉得比 P11 更好，不仅没有更好，反而还有很多的错误。」

**审美分在这件事上已经作废**：p22 拿 87.9（当时的频道新高），用户仍然觉得不如 12 部之前的 p11。
所以本轮第一件事不是"做片子"，是**把 p11 的"满"拆成可核对的数字**。

### 1. p11 的"满"不是元素堆得多，是"一伙会反复出现的实体道具"

对 `production11/scene_s*.json` 逐场统计（不是我印象，是脚本数出来的）：

| 指标 | p11 | p22（87.9 那部） | 差异 |
|---|---|---|---|
| 层/场 | 7.9（最低 7，最高 12） | 11.2 | p22 更多 |
| **道具层占比** | **48%**（42/87） | **15%** | **p11 是 3.2 倍** |
| 文字层占比 | 46% | — | |
| 纸人主持 | 4 层在场 | 0 | |
| 视差场数 | 3/11 | — | |
| `motes` / `seq_` | 0 / 0 | 有 | p22 反而更强 |
| 背景 scale | 1.06–1.12（4 场 <1.10） | — | |

再看 p11 的素材清单：19 个道具被复用成 42 层（`prop_phone_pro`/`prop_phone_max`/`prop_shelf_full`/
`prop_crowd_a` 这些**跨场反复在场**）。而近期片子是"一件道具演一个概念，用完就换"。

> **结论（写进创作层，不是检测层）**：观众说的"满"= **同一批有名有姓的实体物贯穿全片**，
> 不是每场塞更多小图标。**堆图标只会让 clutter 门报警，不会让画面变厚。**
> 所以 p23 的做法是：先定 21 个实体道具（比 p11 多 2 个），再规定它们**跨场返场**，
> S11 结尾让星、百叶、取号单、沙漏全部回到画面。
> p23 实测：**13.4 层/场、道具占比 51%、纸人 11 场在场、视差 11/11、背景 scale 全场 1.12**。

### 2. 抠图：`--despill` 管边缘，管不到"体内粉染"——这是 V3.16 那条的漏掉的一半

StepFun 的洋红底会把**粉光弹进物体内部**。p23 实测（实心像素里 R、B 同时高于 G 的洋红族）：
`prop_hourglass` 1337px、`prop_colorcard` 721px、`prop_blinds` 649px、`prop_counter` 142px。
`--despill` 只削半透明边缘带，**这些实心像素它一个都不动**，于是浅绿底上一眼看出"这道具是粉紫的"。

→ 项目内新增 `depink.py`：判据 = **G 是最小通道且 R、B 同时高于它**（洋红/紫罗兰签名），
只压 R/B 并把压掉的量补回 G（保明度，不染成灰洞）。本片四色逐个核过不落进该带：
琥珀橙 B≪G、薄荷绿与深墨蓝 R<G、纸白 R−G≤2。

> **判据要松到 `R>G+10 且 B>G+6` 才盖得住软粉反弹光。**
> 我第一版写成 +22/+18，柜台撕边那道淡紫和纸筒左半的粉雾**全都漏网**——
> 收紧的门不是"保守"，是"这条缺陷它抓不到"。

### 3. `hsv` 与 `despill` 必须**逐物体**按像素选，不能按"冷色/暖色"经验一刀切

V3.17 说"`--hsv` 是暖/红主体的默认路径"，V3.24⑤ 说"冷色主体用键色法 + `--despill`"。
p23 把两条都跑了一遍，量**边缘带里的洋红族像素数**：

| 道具 | despill | hsv | 选 |
|---|---|---|---|
| `prop_awning` | 517px | **3px** | hsv |
| `prop_phone_edge` | 178px | **2px** | hsv |
| `prop_phone_hero` | 35px | **0px** | hsv |
| `prop_crowd_row` | 80px | **0px**（且 opaque 0.42→0.59） | hsv |
| `prop_blinds` | **23px** | 118px | **despill** |
| `prop_hourglass` | 61px | 42px | despill |

> **判据**：不是"这是什么色系"，是"**这一张的边缘带里有多少洋红族像素**"。
> 一片之内两种判法并存才是常态。经验话（"冷色就 despill"）在 blinds 上直接选错。

### 4. 两扇门修好了：一扇恒亮红，一扇只 WARN

**(a) `preflight_v6` 的 R1 呼吸门是恒亮红灯。**
它取"最后一个不透明关键帧"，而模板每张卡都以 `[场景末, opacity 1]` 收尾 →
**永远报"距场景末 1f"**。已交付的 p22 与本片刻各刷 11 条一模一样的 WARN。
改成量**进场帧** `min(opaque frame)`。RED 探针（把卡挪到 225f 进场）确认真能红，
回放 p22 → **0 条**。
> **一条永远亮红的门等于没有门**（§57 的规矩：假门比没门更糟）。
> 判据错了不是阈值错了——阈值调大只会把真缺陷也放走。

**(b) 平台安全区不该只是 WARN。**
`layout_check` 的 `PLATFORM_RAIL`（右侧 130px 互动按钮区）与 `PLATFORM_CAPTION`（y>1160 自动字幕带）
是 WARN(rc=0) → 按 §57 口径就是**没有门**。p23 一次亮 16 条。
解法不是"渲完再挪"，是**把它写进设计期的夹取框**：`BOARD` 右界 1010→880、下界 1240→1080
（含相机 1.06 推近 + 阴影 12px 的余量）。改完 layout **hard=0、平台类 WARN 归零**。
> **判据**：凡是"最终画面会被平台 UI 盖住"的判据，都必须能在**设计期**拦住，
> 而不是渲完再告诉我。能算出来的别等渲染（§58⑥a 同一族）。

### 5. `name_ledger` 的覆盖率判据把我打回原形（5 处，全是真错）

第一次 `produce` 在"复用旧帧前复检"里被 `name_ledger` 拦停（COVER_MIN=0.6）：
「酷安」点名窗内只有 18%、「6.4」27%、「防窥」两处 **0%**、「小米之家」27%。
根因是同一个：**我把卡安排在"说到那个词时才进场"**，而门要的是
"**念到名字的那几秒，名字已经在屏上**"。`land()` 要 22 帧落程、`drop_on()` 要 20 帧，
所以入场帧必须**提前一个落程**：`f_store = A(23,"先去小米之家") - 22`。
> 这条与 §71 第 3 节的 `tap()` 19 帧淡出是**同一件事的两面**：
> 一面是"别闪一下就退场"，另一面是"别等念到才出现"。**名字卡的可见窗要罩住整句点名。**

### 6. 工具账

- **`gen_assets --overwrite` 没有单文件过滤**：只想改 1 张背景，整批 6 张全重生，多烧 5 次额度。
  已加 `--only name1,name2`（与 `generate_tts --only` 对称）。
- **uint8 溢出会让颜色判据整片假阳**：`g + 22` 在 g>233 时回绕成小数，米白纸面被整片判成洋红
  （`--check` 一度报 `prop_ticket` 13 万 px 假污染）。任何"颜色通道 + 常数"的比较必须先升位宽。
- **重抠图会改 bbox 长宽比 → 场景几何跟着变**：`prop_phone_hero` 换 hsv 后高度 1220→1226，
  `verify()` 当场报"坐标被夹过"。**资产一改，几何必须重算**，不能假设只有改 JSON 才算改设计。

### 恢复说明与两条元教训（2026-09-27，本节曾佚失 24 小时）
本节正文在 2026-09-26/27 的 playbook 尾部编辑中被误删，当时判为"无备份可恢复"并留了墓碑。
2026-09-27 清理仓库时复查发现：**上一轮会话的 JSONL 转录仍在盘上**（`~/.qoder-cn/projects/<项目>/<会话id>.jsonl`），
按行解析 JSON、取写入工具入参里的原文即可完整还原（本节 3620 字符 / 100 行，尾部 shell 终止符已剔除并核对）。
- **文档尾部被误删时，第一恢复源是会话转录，不是"算了吧"**。写盘动作在转录里是完整的字符串，比任何人工记忆可靠。
- **跨节引用的编号必须能反查**：`grep -o '§[0-9]\+' | sort -u` 对照标题清单跑一遍，就知道 §72 被三处引用却缺席。
  本次隔了 24 小时才察觉，纯粹因为没有任何一处做这个检查。**动 playbook 尾部前先 `cp` 一份**（本次已照做）。

---

## §73 V3.34 工作流升级（2026-09-27，p23 交付后；用户指令：不重做 MP4，把经验变成质量+效率）

用户原话：「结合最新的工作流经验，改善优化提升。不仅视频质量+视觉效果等方方面面的改善优化提升，还要提升整个工作流的效率！」
本轮**没有重渲任何一帧**；所有改动落在工具与门禁上，并用 RED 探针 / 12 部片语料标定逐条验过。

### 73.1 增量渲染：863s → 2s（效率主项）
- 新 `scripts/scene_fingerprint.py`。指纹 = 场景 JSON 字节 + 每个被引用资产（背景/图层/seq 目录/debris 源）的**内容哈希** + `render_sequence.py` 自身哈希。资产哈希缓存 `qa/asset_hashes.json`（键=路径+字节数+mtime_ns），p23 冷 0.16s / 热 0.02s。
- `render_all` 先判 `reusable()`：指纹命中且帧数齐 → 跳场；否则打印**为什么重渲**（旧版只报"要渲"，读不出原因）。p23 补戳后 11 场全跳，整链 2s。
- RED 探针 6 条全过：改资产内容（JSON 不动）只渲该场 / 改 JSON 只渲该场 / 删一帧按"帧数不齐"重渲 / 改渲染器全片重渲 / `--force-all` 全渲 / 旧项目只有 `.hash` 没有 `.fp` 时退回旧判据不误报。
- `produce.verify_frames_match_scenes` 加严：`.fp` 存在且与当前指纹不符 → FAIL 指名哪几场"素材在渲染后被改"。这关掉 §59⑭ 的盲区（scene_geom 只覆盖 JSON，换背景/换道具看不见）。
- **教训复述**：戳必须由产出帧的那一方写。`write_stamps()` 只有一份实现，`render_sequence` 与 `render_all` 都调它。

### 73.2 工具同源门：修好的门没进技能包 = 下一部片跑旧门
- 首次 `skill_sync check` 实测漂移 8 处：`preflight_v6`（R1 呼吸门刚修）、`gen_assets --only`（单张重生，p23 为它白烧 5 次额度）、`produce/render_all/render_sequence`、**`production-playbook.md`（§72 根本没进技能包）**。
- 挂两处：`render_all` 渲前链第一道 + `pipeline ready` 盖章前。漂移 rc=1 拒渲/拒盖章；便携包无镜像 rc=2 只响不拦。
- 它当场证明了自己：我补 stderr 重配造成 57 处漂移，下一轮 `render_all` 立刻拒渲并给出一行修法。

### 73.3 背景每场一个空间（质量主项，唯一标定成功的画面判据）
12 部片实测 独立背景数/场数：
```
p11 1.00  p12 1.00  p13 0.75  p14 1.00  p15 1.00  p16 1.00   ← 用户认可的年代
p18 0.19  p19 0.15  p20 0.29  p21 0.25  p22 0.36  p23 0.45   ← 用户说变差的年代
```
分界无重叠。新门 `bg_plan_check.py`：`--plan`（生图章前，jobs_bg 条目数 ≥ 场数）+ 渲前链（真实复用率 ≥0.75）。
**为什么它比"密度/层数/审美分"更接近用户的眼睛**：每场都要重新描述空间，背景生图被迫画出有内部体积的结构。
目检对照：p11 `bg_s08` 是一个摊位（雨棚+立柱+凹进去的内景+柜台=建筑），p23 `bg_store_front` 是一面贴了撕纸条和价签的墙。
p23 已按事实补记豁免：全片锁定同一家门店的门头视角当主舞台，其余 4 张是特写机位；新标准对后续新片生效。

### 73.4 两个标定失败的门：量不出判别力就退回诊断（第六、七个实例）
1. **stage_scale_check（家具级半幅实体物）——已删除。** §72 记的债是"至少一场让家具级实体物占半幅"。做成门后回放 12 部片：
   p11 最大实体物只覆盖 **43.5% 幅宽 / 9.5% 面积（全语料最低）**，p23 反而 100%（那条是撕纸雨棚装饰带）。
   换面积判据再标定：p14 96%、p23 72%（全幅装饰层主导），p11 依旧最低。**判据与用户的眼睛反着走 → 删。**
   真因在 73.3：p11 的"满"来自背景是建筑，不来自前景有个大家具。
2. **cutout_key 自动选模式——不建。** 证据表（`--measure`）里同一个数在两件道具上含义相反：
   "体内/残留洋红族像素"在 prop_awning 上是键色法的粉残留（该 hsv），在 prop_blinds 上是百叶自己的粉叶片（hsv 会抠穿主体）。
   任何阈值都会误伤其中一件 → 只给证据表，决定在人（看 `_check.png` 棋盘图）。
- 累计七个实例后的规律补一条：**"哪个模式/哪件物体更好"这类比较级判据没有跨片通用的；能通用的只有存在性判据（该有 X 没有 / 不该有 X 有了）和"分界无重叠"的计数判据（73.3）。**

### 73.5 asr_final_check 金句段：N/A 不是结果，是没在量
旧版 `--cq-at` 传空参考文本 → `ratio=None` → `strict_ok=True` → 打"相似度 N/A"却算 PASS。
p23 用新代码重跑：金句「防窥能关，这块屏的性格关不掉」**实测 1.0**，11 场全 ≥0.9615。
§72 里"cq_golden N/A（防→王 同音死区）"是**假残留**——不是 ASR 读不出，是那段从来没被比对过。
新规则：参考文本 `--cq-text` > 混音 NARRATION 起点+mp3 实测时长自动定位；定位不到 FAIL 并列全部候选起点；空参考窗口一律拒比。

### 73.6 两条 p23 手工学费进模板
- `clamp_center/CARD_EDGE/STAGE_EDGE/stage_or_card`：文字卡躲平台互动区(右130px)+字幕带(y>1160)，舞台件允许出血。p23 58→0 次夹取失败、16→0 条 PLATFORM 告警是手工清的，现在一行调用。
- `name_lead(f_anchor, mode)`：名字卡入场帧 = 念到帧 − 落定行程。p23 name_ledger 五处 FAIL（酷安 18%/6.4 27%/防窥 0%×2/小米之家 27%）全因"说到才出"，落定完这句话也念完了。

### 73.7 stderr 也要 UTF-8
57 个脚本只重配了 stdout。FAIL 信息走 **stderr**，管道/日志里是 GBK 乱码——
"验证退出码读日志不读通知"这条纪律，曾被乱码废掉一半（日志读不出内容就等于没有日志）。一行修复，全树扫。

### 73.8 本轮效率账
| 项 | 旧 | 新 |
|---|---|---|
| 改一轮坐标后的重渲 | 全量 863s | 只渲变化的场（p23 全命中时 2s） |
| 换道具/换背景后 | 看不见，静默用旧帧 | 指纹变 → 重渲；渲染后被改 → produce FAIL |
| 单张背景重生 | `--overwrite` 整批 6 张（烧 5 次额度） | `--overwrite --only 名字` |
| 选抠图模式 | 手工量三轮 | `cutout_key --measure` 一次 |
| 工具是否同步 | 无机制，漂移 8 处无人知 | `skill_sync check` 0.3s，漂移即拒渲 |
| 金句是否被检查 | 恒 PASS（N/A） | 真比对（p23 实测 1.0） |

---

## §74 V3.35 第二轮深审与执行（2026-09-27，接 §73）

用户指令：「全面+深度的审查最新工作流 V3.34，从第一性原理出发…给出推荐结论建议」→「按照你的合理建议，执行更新工作流！更新完后，再审查一次！」
本轮**仍然没有重渲任何一帧**；p23 成片 md5 未变。

### 74.1 审查先立坐标：一部片的观感由六层决定，逐层问"谁在管/管到什么程度/漏口在哪"
| 层 | 管它的 | 漏口（实测） |
|---|---|---|
| 内容→画面忠实 | name_ledger + SUT | 只查**名字在不在屏**，查不出"这场的主体没被演" |
| 空间（背景） | bg_plan_check（新） | 文件名唯一 ≠ 视觉不同：p16 两张不同名背景缩略图 MAD 仅 **2.5** |
| 布局几何 | layout_check | **seq_ 读数层此前完全隐形**；平台安全区只是 WARN |
| 镜头语言 | validate_shot_plan | **17 部片 0 份 shot-plan，0 调用点** = 挂着假标准 |
| 节奏 | split_beats + beats.json | 已落地（p18 起语义切点） |
| 声音 | mix_audio4 + qa_deliver | 硬门齐全，但**我听不见音轨**，落点舒适度只能用户判 |
| 验收 | 抽帧拼表 | 1x 完整播放从未执行（能力限制） |

效率侧实测：**渲前 8 道门合计 6.8s**（最贵 bg_luma 2.2s / name_ledger 1.8s）。门禁从来不是瓶颈，瓶颈是渲染 863s 与返工次数。

### 74.2 读数层进几何门（本轮主修）
`layout_check.card_png_wh` 只读 `layer["path"]`，而 seq 层带 `seq_dir` → 它既进不了 card 集合、也进不了 others（`path` 取不到被 `exists()` 滤掉）。**p17 那两条"数字压在菜单牌上""四档读数同 y 叠成糊"的可见缺陷，从此有地方报。**
- **分级是标定逼出来的，不是我定的**：第一版把 seq×卡 也判 HARD → 回放 13 部片 **4 部亮红**：p20 `bar_a`×`seq_users_400w`(0.73)、p21 `p_ref`×`seq_ref5`(0.67)、p23 `seq_score64`×`t_dark0`(0.74)。逐条看画面语义：**全是"数字标在它所属的卡上"的合法设计**——重叠比的分母是 `min(面积)`，小数字整块落进大卡框就等于 1.0。
- 终判：**seq×seq = HARD `READOUT_COLLIDE`**（两个实心读数互咬没有合理解释）；**seq×卡 = WARN `READOUT_ON_CARD`**；**seq×道具 = WARN `READOUT_ON_PROP`**（道具上有没有烤字，纯几何判不出）。
- 复跑：13 部片 **hard 全 0**、warn 每片 +3~+12；RED 探针（合成两场同 y 读数）确认 HARD 真能红。
- 同屏密度 DENSITY 排除 seq（同一个数字在滚，不是又一张卡）。

### 74.3 WARN 隐形：一条都没进过人眼的 312 条警告
`render_all` 在门禁 rc=0 时只打"✓ 通过"，把 stdout 整段丢掉。实测 `layout_check` 每片 **187–312 条 WARN**（p19 234、p22 300、p21 258）。
→ 门禁通过时打印带 `SUMMARY ` 前缀的分类汇总行；KICKOFF 加 **E3 分诊**（逐类回答"有没有真缺陷"，不许整类忽略）。
**元结论复述（§62）：先怀疑"信息没人看"，再怀疑"缺门"。**

### 74.4 我自己否掉的两条建议（数据否的，不是感觉）
1. **"平台安全区升 HARD"**：回放会判红 p19(29)/p21(14)/p22(15)——**p22 是频道最高分那片**。右 130px 是半透明按钮区，压上去是风险不是缺陷。留在设计期 `CARD_EDGE` 解决。
2. **"背景视觉相似度门"**（补 §73.3 的洞）：MAD 判据被**稀疏度**混淆——p16 那两张被判"几乎相同"其实是因为**两张都太空**（大面墙+一个小元素），不是同一张图。第八个弱代理门候选，不建；改由 A1b 的"背景三要素 + contact sheet 目检"在创作层收。

### 74.5 创作动作写进开工表（写了才会做，没写就会被跳过）
- **D4 英雄时刻**：情绪最高点那场建场前先写 2–3 方案再选一个磨它。**p17 做过一次，p18–p23 六部全部直接进建场** → 六部没有一处让人记住的画面。这是全产线唯一一次"为惊喜而设计"的动作，此前只存在于口头承诺。
- **A1b 背景三要素**：每张背景 prompt 必须写 ①光从哪来 ②地平线/台面在哪 ③哪块地板站得下人；出图拼 contact sheet 逐张问"能在这场里站着演吗"。
- **E2 静音看**：关声音逐场问"这一场在讲谁"，答不出或答成另一个名字 = 语义没演出来。这是 §66 那条用户投诉里 `name_ledger` 至今查不出的那一半。
- **shot-plan 降级为可选**：17 部 0 份、0 调用点，真在管景别/切点的是 B 表 + beats.json。**挂着从未执行的规范，代价是未来的自己以为它被检查过。**

### 74.6 接线补漏
`produce --skip-render` 复检链补 `bg_plan_check`（V3.34 只挂了 `render_all`）；`layout_check` 新增 `--report-dir`，**回放历史片时不再覆盖已交付片的 QA 记录**。

### 74.7 WARN 洪水的第一批清理（同轮追加）
`layout_check` 的 DENSITY 是**逐 6 帧采样**判的，一场能刷 176 条。改成**每场只报最挤那一帧**并给出 hint 指向 E3 分诊。
清理后每片 WARN 总量：p23 **190→21**、p19 **255→87**、p22 **312→54**、p14 **41→4**、p11 43→22。
**判据一个字没动**（还是"同屏 >3 张字卡"），只是不再把同一个事实重复 176 遍。13 部片 hard 仍全 0。
> 与 §62 那次 `qa_deliver` 614 行 WARN 合并成 1 行是同一件事：**警告的可读性是警告的一部分。**

---

## §75 V3.36 第三遍审查：查门的**可绕过性**与交付物完整性（2026-09-27）

前两遍查"门有没有放人"，这一遍换个问法：**门建好之后，改一个文件能不能绕过去？承诺的交付物真的交了吗？**

### 75.1 我自己 V3.34 建的门，被自己的盖章机制绕过
`bg_plan_check --plan` 挂在 `pipeline ready --stage assets`，而 `require_ready` 只验章。
**章的输入是 `KICKOFF/palette/chunks/sut`——不含 `jobs_bg.json`。**
所以：按 11 张背景盖章 → 把清单改成 6 张 → `gen_assets` 照跑，门一个字都不会响。
修：`jobs*.json` 进 assets 阶段的章输入。实测 p23：删掉 1 条背景任务 → 章 `f04d00a1→b5edaa4e` 失效，还原 → 复原。
> **判据（新）：任何"在 X 时刻检查 Y 文件"的门，Y 必须进入 X 的盖章输入。** 否则检查的是历史快照，不是当前决定。
> 这条对 V3.27 之后所有挂在 `ready` 上的门都成立——已复核其余四道(palette_oklch/metaphor/novelty/semantic)的输入源都在章里。

### 75.2 跨片账本：手工登记已经漏过一部片
两本账（`palettes.json`/`metaphors.json`）是防撞车的唯一依据，此前**全靠我交付后手工 add**。
2026-09-27 实测 15 部有配色的片：**p22 在配色账里，但不在隐喻账里**（8 个概念白登）。
修：`produce.verify_ledgers` 成交付前最后一道硬门（结构化判定：palettes 查键、metaphors 查 `films` 列表——**不用子串**，"production2" 是 "production23" 的子串，按子串判会把没登记的判成登记过）。p22 已补登记。

### 75.3 承诺过但从没交过的交付物：可编辑播放器
`SKILL.md` 的 description 写着交付"MP4+旁白+**可编辑播放器**"，`build_hyperframes_player.py` 存在。
实测：**17 部片的 output/ 里 0 个 html**，`produce.py` 里 0 个调用点。
这是第三例"挂着从未执行的能力"（前有 shot-plan 已降级）。**待用户裁定**：接进 produce（每片多一步构建）还是把承诺从 description 里删掉。**我不擅自删用户要的交付定义，也不假装它存在。**

### 75.4 磁盘：帧目录是体积主体，删了也不破坏增量渲染
p23 实测 `frames_s01` = **396MB**，11 场 ≈ 4GB/部。V3.35 的资产级指纹让"删帧后只重渲缺的场"仍然成立（`reusable()` 见无帧目录 → 判不可复用 → 渲）。
建议（未做，等用户点头）：交付后保留 `assets/ + scene JSON + qa/ + output/`，删 `frames_s*`；`qa/frame_stamps/*.fp` 保留，重开时能立刻指出哪几场需要重渲。

### 75.5 调用图复查
零编排器引用：`depink`(设计如此，素材阶段手工)、`make_contact_sheet_win`、`preflight_env`、`detect_style`(仅 1 处)。
**有产物证据、确实在跑的**：animatic 预览门近 6 部每部都有 filmstrip/preview 产物——它不是假门，只是没有强制门。

---

## §76 仓库清理与"历史参照物"账本（2026-09-27）

用户裁定：「以前的历史产出没有用了，留着干什么？」→ **16 个 production 目录 + 13 份文案/脚本 txt + 2 个便携包 zip 全删**。
**141.30 GB → 9 MB**（帧目录占 135.7 GB = 96%，纯衍生物）。顶层只剩工作流：`scripts/ references/ SKILL.md README.md ADAPTATION.md ip_assets/ ip_registry.json palettes.json metaphors.json film_digest.json _pack_portable.py .env`。

### 76.1 删历史会静默杀掉三道门——先接账本再删
`motion_similarity_check`(缓动余弦)、`novelty_meter`(D1 骨架/D2 钩子/D3 缓动/D6 风格连用)、`pipeline setup` 的风格连用提醒，
都是靠扫 `../production*` 找"上一部"。目录清空后它们会走进 `找不到前一部 → 放行/SKIP` 分支——**门还在，参照物没了，于是永远绿**。
这正是 §70 那次"用户说最近几部有点像"之后建起来的机制，不能死于一次磁盘清理。
→ 新 `scripts/film_digest.py`：把每部片**门真正要读的那几个事实**（主风格档、四色、缓动分布、特效词汇、骨架、钩子、IP 在场、KICKOFF 的 A1/A2/图腾原文）抽进根目录 `film_digest.json`。15 部片 **11 KB**。
三道门改为：目录在 → 读目录；目录没了 → 读账本并**明说**"参照取自 film_digest.json"；两处都没有 → 才放行，且提示"若非第一部片说明账本没建"。
- 验证方式：把 scripts + 账本复制进隔离目录、只放一个 probe 项目（模拟"历史已清"）→ `motion_similarity_check` 报出"与 production23 同为剪纸拼贴且主导缓动同为 ease-out → FAIL rc=1"，`novelty_meter` 报"D1 骨架与 production23 同为 A"。**门有牙齿，参照物没丢。**
- 途中修掉一个真 bug：`motion_similarity_check` 里两处 `prev.name` 在账本路径下 `prev is None` → AttributeError 崩栈（第一次跑就崩，靠隔离测试抓到）。
- **判据：删任何"历史数据"之前，先 grep 谁在读它。** 读目录的门会把"没有目录"当成"没有可比对象"，静默放行。

### 76.2 被误删的文档，第一恢复源是会话转录
清理时发现 playbook §72 是**墓碑**（"p23 复盘正文佚失，无备份可恢复"，24 小时无人察觉）。
实际可恢复：`~/.qoder-cn/projects/<项目>/<会话id>.jsonl` 里，写盘动作是完整的 JSON 字符串——**按行 `json.loads` 解析、取写入工具入参里的原文**即可完整还原（本节捞回 3620 字符 / 100 行，尾部 shell 终止符 `MDEOF` 已剔除并核对末行）。
两条规矩：
- **动 playbook 尾部前先 `cp` 一份**（本次已照做，验证通过后才删备份）。
- **编号引用要能反查**：`^##\s+(?:§)?(\d+)` 取标题节号、`§(\d+)` 取引用节号，做差集即知有无悬空。
  注意本仓 playbook 早期标题是 `## 44.` 不是 `## §44`，只按 `## §N` 匹配会误报 17 个"悬空引用"——**检查器自己也要先被验一遍**。现 75 节，悬空 0。

### 76.3 清完之后仓库里剩什么
`SKILL.md`(V3.37) / `README.md` / `ADAPTATION.md` / `references/`(9 份，playbook 到 §76) / `scripts/`(80 个工具) /
`palettes.json`(21 部配色) / `metaphors.json`(174 概念) / `film_digest.json`(15 部指纹) /
`ip_assets/` + `ip_registry.json`(跨片白名单 IP 角色) / `_pack_portable.py` / `.env`(私人 key，只留本机)。
**新片不再有任何"上一部目录"可抄**——这本来就是目的：防趋同靠账本与门，不靠翻旧片。

---

## §77 清空历史后的环境与全流程排练（2026-09-27，V3.38）

用户问的是："下次给文案，你能不能直接做出高质量视频？"——这题不能用嘴答，所以做两件事：**环境依赖逐项实测** + **不花钱的全流程排练**。

### 77.1 环境依赖实测（全绿）
| 依赖 | 实测 |
|---|---|
| Python | `py -3.14` → 3.14.5，绝对路径 `…\Python314\python.exe`（不是 WindowsApps 桩） |
| Pillow / numpy | 12.2.0 / 2.5.0 |
| ffmpeg / ffprobe | WinGet 完整版 8.1.1，`env_paths.ffmpeg()` 解析到 `…Gyan.FFmpeg…\bin\`；**判据是"能否解码 mp3"的能力自检，不是程序名黑名单** |
| `.env` | 15 个键齐全（`STEPFUN_API_KEY` 65 字符 + base/tts/asr/image/chat/vision 模型 + 5 条 URL） |
| 网络 | `api.stepfun.com:443` TCP 可达 |
| 创意契约技能 | `~/.agents/skills/create-collage-animation/` 在位 |
| IP 素材 | `ip_registry.json` 引用的 4 个 png 全在 `ip_assets/`，缺失 0 |
| 磁盘 | H: 剩余 1573 GB（一部片约 4 GB 帧，够用几百部） |

### 77.2 排练抓到一条真缺陷：**花钱前的门对着空稿打 PASS**
`pipeline setup` 生成的 `chunks.json` 是 `[{"id":"chunk_01","text":"",…}]` —— **段数非 0、正文全空**。
`check_script` 与 `claim_check` 旧版只查"列表为空"，于是排练实录：
- `check_script`：「字数 0 | chunk 1 → **PASS**，可进 TTS」
- `claim_check`：「实体断言: (空) → **PASS**，文案自洽」

这两道是 V3.20 起就写着的"花钱前硬门"。**对着空稿放行 = 没有门**，而且是 §57「假 PASS」那一类的最纯形态：它不是判错，是根本没东西可判却报告通过。
→ 两处都加空正文守卫（正文折算字数为 0 即 FAIL，并指名"这是 setup 的空桩，阶段①重构稿还没写进来"）。RED 探针：空桩 rc=1 两处都拦住；GREEN：真稿 rc=0。

### 77.3 排练全程结果（离线，零计费调用）
`pipeline setup --style 剪纸拼贴` → 建项 + palette + confetti 重绘 + **风格连用提醒（参照取自 film_digest 的 production23）**
→ 填 KICKOFF（含 V3.35 新加的 A1b/D4/E2/E3 行，`_kickoff_state` 判"已填完"，证明新行可满足没卡死）
→ `check_script` / `claim_check` rc=0
→ `pipeline ready --stage tts`：第一次被 **skill_sync 漂移**拦下（我刚改了两个门）→ push 后重跑 → **✅ 盖章 `qa/ready-tts.json`**。
配色门顺带演示了它的工作方式：第一版四色与 p21 ΔE 0.031 → **FAIL**；换色后与 p21 偏近(0.084 WARN)、与 p22/p23 0.199/0.222 → **PASS**。
**历史目录已清空，配色与缓动的跨片比对仍然有效**——因为参照物在 `palettes.json` / `metaphors.json` / `film_digest.json` 三本账里，不在旧片目录里。
排练项目 `production24` 与脚本已删除；两本账零污染（palettes 21 部 / metaphors 174 概念未变）。

### 77.4 下次给文案的实际路径（已验证可走）
`setup → 填 KICKOFF(含 A1b 每场一个空间、D4 英雄时刻) → 分段重构稿进 chunks.json → 离线三门 → ready 盖章 → 审稿门停下等你点头 → TTS/生图 → 建场 → 渲前 8 门 → animatic 目检 → 增量渲染 → produce 一键 → 交付 + 与 p11 并排抽帧`。
**唯一不能自动化的一环仍是验收**：画面薄不薄、节奏拖不拖，由你的眼睛和耳朵判，我提供并排抽帧图。

---

## §78 "精简版 ffmpeg"到底是什么，以及它现在还在不在（2026-09-27 复核）

用户问「什么是精简版？可以删除了，免得引起误会歧义」。查完的结论是**没东西可删，该删的是文档里的现在时说法**。

**"精简版"指什么**：编译时带 `--disable-everything` 的 ffmpeg 构建——只开极少数封装/解码器，**不含音频解码器**。
用它测 mp3 时长不会报错，只会**静默给出约实际一半的数字**（2026-08-25 实录 13.49s→6.74s），
于是整条"时长驱动帧预算"的时间轴错位、旁白重叠成"多声齐响"。它坏就坏在**不报错**。

**实测现状（2026-09-27）**：
- `which -a ffmpeg ffprobe` → **只有** `WinGet\Links\{ffmpeg,ffprobe}`，都是 `8.1.1-full_build`（完整版）。
- 当年那个精简版随 **TRAE 一起卸载消失**了（`AppData/Local/*TRAE*` 已不存在）。
- 机器上另有两份自带副本，都不在 PATH、都不是我们的依赖：
  `AppData/Local/hermes/tools/ffmpeg-9.0.1-win32-x64/bin/`（实测 `-codecs` 含 3 个 mp3 解码器，**是完整版**）、
  `AppData/Local/ms-playwright/ffmpeg-1011/`（Playwright 自带，删了会坏它自己的功能）。
- **所以：无可删之物。** 删别的程序的二进制是越界且危险的（它们不在我们依赖链上，删了只会让别的工具坏）。

**为什么规则要留着、说法要改**：`env_paths._is_full_build()` 的判据是**能力自检**——
逐个候选跑 `ffprobe -hide_banner -decoders`，输出里没有 mp3 解码器就跳过，全部不合格就抛错并提示 `winget install Gyan.FFmpeg`。
它**不看程序名、不看目录**，所以明天任何安装程序往 PATH 塞一个精简构建，都不需要再改代码。
据此把 SKILL(4 处)/`env_paths`(3 处)/`audio_duration`(2 处)/§77 表格(1 处) 里"PATH 上是 TRAE 精简版"这类**现在时断言**
改成"任何无音频解码的构建都会被拒"；历史事故记录保留原文并标注"该程序已消失，机制保留"。
> **元规则：文档里凡是"机器上现在有个坏程序"的断言都会过期，机制里的判据不会。写机制，别写通缉令。**

## §79 · p24《免费打平GPT-6》首跑 V3.38 产线的实录与四笔学费（2026-09-27）

**成片**: 95.5s / 12 场 16 chunk / 全门绿（七断言 + clutter 0/0 + 整片 ASR 1.0）。等距 2.5D 首次主档。

① **asr_alias.json 的格式是「规范名: [变体列表]」，不是「变体: 规范名」**——写反了不会报错：
  load_alias 把键当规范名（拉丁校验照样过），同名键互相覆盖、最后写入者生效，结果是**把正确的
  转写改写成错的**。p24 实录：Vercel 被听成 Verse/Verso/World sale/Versal 四种，倒序表 + 逐个补录
  导致 mapping['vercel'] 最终 = 'versal'，s01 从 1.0 掉到 0.865。**方向一反，别名就从"救假红"变成
  "洗白真错"**。修法：按文档格式写规范名为键；改表后先自测 `canon(got)==canon(ref)` 再进产线。
② **封面层必须按 f0 相机倍率预缩**：渲染器的相机是**整画布后置变换**（apply_camera 画在合成之后），
  没有单层豁免——封面 base_width=1080 会被 S01 的 bg scale(1.14) 放大裁切，qa 首帧≠封面 diff 26~55。
  正解：**cover 层 base_width = 1080 / bg_scale**（层先缩、相机放大、净变换=恒等），首帧与 cover.png
  逐像素重合。"把内容画进安全盒"没用——门比的是像素对齐，不是构图。
③ **produce 的 `--at` 是创意转场时代的遗留**：硬切为主时 at 标记不再物理加帧，但 total 仍
  +10×len(at_set) → TARGET 虚高、mix 断言拦下（p24 --at 89 白跑一轮混音）。已修：total 改读
  splice_manifest.json 的权威值，不再估算。
④ **默认音效铺点会压旁白起音**：每场 starts[k]+1.2 的默认 pop 正好砸在 LEAD=0.3 起的旁白第一口上，
  ASR 连"一"都听不见（p24 s09 实录）。正解=写 qa/events.json 把 SFX 锚到动作落点（落地/翻面/撞线），
  全片 ≤20 个；整片 ASR 段首丢字，先查音效表再怀疑配音。
⑤ **花钱前的门本片四次全部拦对**：jobs_bg_alt.json 落进章输入 glob → 章失效（0 元）；
  meter 重生 → 章失效；--at 虚高 → mix 断言；配色账漏登 → 交付门拦下。**资产生效链与花钱前断言
  各拦一次，全是设计内行为**——这轮的经验不是"加门"，是"照着门走就对了"。

## §80 · p25《OpenAI 紧急停训》交付实录与机制化清单（2026-09-28，V3.39）

p25 是 22 chunk/16 场、141.2s 的漫画网点片（深底 26,28,38 + 奶油面板卡 + 波普红带）。交付状态：
qa_deliver 七断言 PASS、clutter 0/0、审美 84.7、整片 ASR 16/16 ≥0.923。本轮六道渲前门拦了
空台×6、节奏窗×1、布局 HARD×6，全部修完渲完——但**最大的缺陷（30/55 张字卡是坏的）一道门都没拦**，
是目检接触表抓的。教训全部机制化如下。

### ① 字卡内容存在性门 `card_text_check.py`（本轮最重要）
- **事故**：`make_local_assets.py` 把 CREAM 当墨字传给 panel=True → 奶油字画奶油板=隐形 20 张；
  10 张临时补卡把文件名 id 当文案（c_ann0、c_wall0…）。渲染、编码、qa_deliver、审美、clutter
  全绿——**没有任何门查卡上有没有字**，也没有门发现"临时补的卡没回写生成脚本"。
- **门的两类存在性判据**（§59⑫ 规矩：能通用的只有"根本不该有 X"）：
  1) 登记完整性：assets/text/*.png 每张必须在 qa/card_manifest.json（由生成器落盘）有条目，
     账上有盘上无同样 FAIL——临时补卡不回写脚本，这里当场拦；
  2) 内容存在性：面板卡把 alpha 腐蚀 13px 取**内部**（排除面板自己的黑描边——不腐蚀，
     描边就冒充墨），内部与填充色 maxΔRGB>60 的像素 ≥2% 才算有字；裸字卡要求不透明像素
     平均亮度离开 film 底色 ±50。
- **标定**（p25 全卡）：有字卡内部墨占比最小 15.1%（c_human），坏卡 0–0.3%，阈值 0.02 居中。
- **判"文案对不对"无 OCR 门、也不装**：门同时产出 qa/card_text_sheet.png 接触表，归人眼。
- **空白面板合法化路径**：生成器 `blank_panel()` / manifest `"blank": true`（p25 的四壁是实体板）。
- 挂载：render_all 渲前链第 2 位 + `pipeline ready --stage assets`。

### ② layout_check `card_bbox_sim` 顶边取错分量（真 bug，非标定问题）
- mn[1] 写成 `min(y for _, y in ys)`——ys 元组是 (顶,底)，取到了**底边最小值**；顶部出画/贴边
  从此永远检不出（假阴性）。本片 4 条出画 HARD 的 bbox 高度只有 1–4px 就是签名（顶边从未进入
  统计）。修复：`min(y for y, _ in ys)`。修复后本片 16 场无新增顶部违规（顶边本来就都在界内）。

### ③ asr_final_check 窗口头沿零保护带（假 FAIL）
- 窗口 `w0 = s0`（旁白起点）——尾部早有 +0.35s 保护，头部为零。AAC seek 粒度 + TTS 软起音把
  首音节裁掉半个 → ASR 丢"接"听成"这是"，s04 0.846<0.9 假 FAIL；三滚稳定复现（不是轮间抖动）。
- **诊断手法（可复用）**：同窗口加 0.5s 前置余量重新 ASR——转出全句即证明成片音频完好，
  是测量问题；原始 mp3 的 asr_spotcheck（0.9231 PASS）是第二证据。
- ⚠ **波形直相关对 loudnorm 混音不可用**（成片 vs mp3 直相关 ≈0.03，连对照组 chunk_01 也 0.002），
  别再试这条路，ASR 前置余量才是对的仪器。
- 修复：`w0 = s0 - 0.25`（钳位 prev_end+0.02）——修测量不修阈值。修复后 16/16 PASS。

### ④ 同音死区的处置边界
- "接着试/接着是"完全同音：重录必无用（V3.24⑧ 结论再次成立）；拉丁变体照旧走别名账
  （Bing→Bin 已入 p25 的 asr_alias.json）。ASR 三滚结果相同时**不要再滚**——稳定复现的
  FAIL 要去查测量，不是掷骰子。

### ⑤ `regen_check.py`：交付态可复现断言
- p25 的渲染期手修（空台/出画/补层/label）全部镜像进 build_scenes.py 的 `_postfix(i, d)`，
  并用本门逐场断言"生成器+_postfix 的 layers == 盘上 JSON"。没有这一步，重跑生成器即回退，
  且没有任何门会发现（split_beats 产物不在对比范围）。跳过产出修：镜像进源码，不靠记忆。

### ⑥ 流程：手动复跑单道门 ≠ 交付
- produce 在 asr_final FAIL 处中止后，**手动把 asr 跑 PASS 不等于 produce 通过**——排在它后面的
  `verify_ledgers`（跨片账本，V3.36②）被跳过，p25 因此漏登 palettes.json（事后补登+补预览图）。
- 规矩：**单跑被拦的门修完后，必须把 produce 该门之后的剩余门全部补跑**（或重跑 produce）。

### ⑦ 一条自我更正：读日志别只看尾巴
- 本轮曾误诊"first_frame_check 分批报错、一轮只报 3 场"——重读源码发现它是全量收集，
  是我 `tail -30` 只看到末尾 3 条（S13 首轮报的就是"最早可见图层在第 0 帧"变体，可证 6 场同列）。
  机制没病，诊断过程有病：**结论先于机制化之前，先把日志读全**（§58⑨"读日志不读通知"的姊妹条）。

### ⑧ 本轮验证有效的既有机制（继续用）
- events.json 锚动作落点（§79 #4）：15 条 SFX 全避开段首，整片 ASR 无音效压字；
- 指纹增量渲染：三轮渲染分别复用 7/2 场，改一轮坐标只重渲受影响场；
- 资产指纹对"换卡"敏感：c_bot_label 重生成逐字节一致（md5 不变）→ 零重渲，
  说明 PIL 同参数生成是确定性的，可用"重生成后比对 md5"来决定要不要重渲。

## §81 V3.40 两道"会撒谎的门"（2026-09-29，p26 交付中；用户指令：按建议继续执行，要成品）

p26 建场后我改了 3 处（卡面文字「绿盟科技」→口播用词「绿盟」、数字层后缀「8 张」→「8 张卡」、给 seq 层挂 label），
然后 `render_all` 报"16 场全部命中帧戳，无需渲染"，`name_ledger` 报"✅ PASS（0 次点名）"。
两条门都在**说谎**。逐条定位、复现、修复：

### 81.1 `name_ledger` 恒绿空转（§57⑤/§70 同族的第 N 次复发）
- **根因**：主循环 `if e.get("kind") != "named": continue`，而**没有任何一部片的 NAMES.json 写过 `kind` 字段**
  （p24/p25 的条目只有 name/spoken_in/card）→ 全部条目被跳过 → `oklines` 为空 → 无 error → 打印 PASS。
- **复验**：修好后跑 p25，暴露出「Google」「IP」「Hugging Face」三处**0% 在屏**——这部已交付的片子
  当年根本没被查过。§66 建的门，自建立起就没工作过。
- **第二个 bug（门自己选错时刻）**：锚点匹配用 `any(tok in phrase)`，「10 万份」的词素 `10` 撞上
  「9 月 28 号到 **10** 月 7 号」→ 去查了错误的窗口，报出假 FAIL。改成**整名优先、再退到全词素 `all()`**。
- **修法**：`kind` 缺省即视为具名条目（向后兼容）；`spoken_in` 同时接受 `1` 与 `"chunk_01"`
  （旧版喂字符串给 `scene_of_chunk` 直接 KeyError 崩栈）；**末尾加空转守卫**：有名单、无 error、
  却 0 次检查 → 判 FAIL 并说明怎么核对字段。
- **判据（复述并加严）：一条门的"通过"必须报出它查了多少次。`PASS（0 次）` 不是通过，是没跑。**

### 81.2 `scene_fingerprint` 缓存投毒式假绿（增量渲染的命门）
- **根因**：`_hashed()` 的缓存命中条件是 `size + mtime_ns` 相同。生成器重写一张 PNG（内容变了、
  字节数恰好没变、mtime 被同秒覆盖或复制时间戳）→ 端回**旧哈希** → `fingerprint()` 不变 →
  `reusable()` 报"指纹命中"→ 用旧帧出了新内容的片子。§73.1 吹的"关掉换素材看不见"的盲区，被它自己的缓存重新打开。
- **RED 探针（隔离沙盒，可复跑）**：造 30 帧小项目 → 写戳 → **改资产一个字节、把 mtime_ns 复原、size 不变**
  → 修复前 `reusable=True`（★假绿），修复后 `reusable=False 指纹变了`。
- **修法**：缓存命中再加**内容探针**——头 4KB + 尾 4KB 的 sha256。PNG 是熵编码流，改一个字节尾部面目全非，
  探针必然变。代价实测：16 场全量指纹 0.20s → **0.22s**（缓存仍做"同一次跑动内不重复哈希"，105 张资产）。
- **判据：缓存的键必须包含它能证明"内容没变"的最小充分证据。** 用 size+mtime 当"内容没变"的证据，
  等于用"包裹一样重"证明"里面是同一件东西"。

### 81.3 流程侧结论
- 改过场景/资产后**不要相信"复用旧帧"**：p26 用 `--force-all` 重渲了全片，并让 produce 重出 MP4。
  旧 `final.mp4` 是修正前那批帧出的——**交付物的时间戳必须晚于最后一次内容修改**，这条以后进 qa_deliver 的候选门。
- 门改了必须 `skill_sync push`（否则 §73.2 的同源门会拒渲，这次它是对的）。

## §82 · V3.41 第三遍审查：假 PASS、一个奇偶数、和两处"用分钟换毫秒"（2026-09-29）

来源：用户"再次全面+深度审查，各种维度"。分六个维度跑（假 PASS 探针 / 可绕过性 / 死代码 / 文档↔代码 / p26 时间归因 / 账本完整性），
批准范围＝"零风险批 + 效率批 + 装切点硬门"。改动 9 个文件，每条都带 RED/GREEN 或 A/B 证据。**subagent 报告一律先复现再采信**（本仓 §64 已有先例）。

### 82.1 六处假 PASS（同一族：门在跑，但跑的对象不存在）
| 门 | 病 | 修法与实测 |
|---|---|---|
| `palette_oklch check` | 项目参数是装饰性的：找不到账本回退 `Path("palettes.json")`(=CWD)；palette 里没有可解析色对时 **0 次判定仍打印 PASS** | 路径不存在 FAIL、0 次判定 FAIL、账本改"项目父目录→仓库根"确定性解析。真项目仍 rc=0 |
| `metaphor_ledger check` | 账本按 `Path.cwd()` 上溯找 → 在别的目录敲 `pipeline ready` 就是拿**空账本**比对 | 仓库根优先解析；`check` 时账本不存在即 FAIL（`add` 仍可首建）。**A/B 铁证**：技能包里的旧版在错 cwd 把已登记概念「黄铜闸刀」判 rc=0，新版同一命令 rc=1 |
| `structure_plan check` | **任何输入都不返回 1**（0 行也"多样性 OK"） | 空目录/不足 3 部即 FAIL；p24/25/26(12/16/16 场) 实测仍绿 |
| `name_ledger` | 无 `is_dir` 守卫：路径打错=对不存在的项目打绿 | 不存在 FAIL；"存在但没 NAMES.json"仍按历史片口径 WARN |
| `motion_similarity_check` | 对"存在但空的目录"rc=0、对"不存在的目录"FAIL——**同门两种相反行为** | 零场景 FAIL；p26 rc=0 不变 |
| `pipeline setup` | 非法 `--style`（README 旗舰命令写的 `等距2.5D/白板手绘` 就不是合法键）静默不写 palette.json、不重绘彩带、exit 0；`--copy` 指错文件 → 空桩继续 | 两者直接 FAIL 并列可用键；合法 `--style 国潮水墨` 实测仍 rc=0 |

**判据：门禁的"输入是否真的存在"不是前置检查，是判据的一部分。** 一个拿不到对象还能报绿的门，比没有门更糟——它让人以为查过了。

### 82.2 一个奇偶数把预览门杀了两个月（本轮最意外）
`animatic` 的预览帧尺寸是 float scale 算的：p26 用 `--scale 0.22` → **238×317，高度是奇数**，libx264 + yuv420p 直接拒绝
（`error code -22 (Invalid argument)`，"Nothing was written into output file"）。而旧代码**不查 ffmpeg rc、只查 `preview.mp4.exists()`**
→ 0 字节文件照样打印"预览片 →"。**同一份 `_list.txt` 实测：旧命令 rc=3752568763 / size=0；新命令 rc=0 / size=569KB。**
p24/p25 恰好用了 0.35 倍 → 378×504 全是偶数，所以这个 bug 躲过了两个多月、只在 p26 中招，且**没有任何一处会红**。
修：编码前 `scale=trunc(iw/2)*2:trunc(ih/2)*2` + 查 rc + 查 size≥1KB，失败即 rc=1。
**判据：派生文件必须查"有没有内容"，不能只查"在不在"——本仓早就把"零字节派生文件"列为存在性判据(§51④)，这次是同一个病没铺到 animatic。**
**判据：产物尺寸由 float 缩放算出来时，凡下游要求偶数/对齐，上游必须显式取整。**

### 82.3 切点声明从此有人对账（标定通过才装）
`preflight_v6 [切点丢失]` 旧版只在 `qa/beats.json` 存在时生效；**p26 既没写 beats.json 也没跑 split_beats**（无 `.prebeats.json`），
于是这道门整场空转——而 KICKOFF B 表 16/16 场都填了「>6s 的景别切点」。实测 p26 有 11 场 >6s，其中 **5 场相机只有 2 段关键帧(一镜到底)**：
S01(7.4s) S04(7.3s) S09(7.7s) S11(6.9s) S12(7.6s)。
标定（判据＝B 表声明 vs 相机段数≥3）：**p24 声明 7 / 未落地 0，p25 5 / 0，p26 11 / 5** → 零假阳性、坏的那片必须红，符合 §57 装门标准。
书面豁免 `cuts_waived:` 第一版只要求 ≥6 字，**"全片一镜到底"六个字当场把门洗白**（§70 同一类病）→ 抬到 ≥20 字 + 套话黑名单，四种偷懒写法实测全红。
**⚠ 副作用要记账**：已交付的 p26 现在渲前链会红。它不该被"为了让门绿"而改——要出 v2 就补 `qa/beats.json` + `split_beats` 真把那 5 场切出来，或写一条合格的 `cuts_waived` 理由。

### 82.4 两处"用分钟换毫秒"（p26 时间归因）
总墙钟 89m11s，**≈957s(18%) 是纯重复劳动**：
- **produce② 的 196s 完全可避免**：produce① 已 `DELIVER PASS` + 整片 ASR 全过，只死在最后一行 `verify_ledgers`「未登记进 palettes.json」，
  而那是两次毫秒级文件写。→ `verify_ledgers` 前移到 produce 开头（末尾那道保留，前移不是放松交付门）。
- **render 轮2 的 491.1s + produce③ 的 190s**：由 §81 那两道说谎的门（`name_ledger` 恒绿空转、指纹缓存投毒）触发；**增量渲染本轮省了 0 秒**（两轮都"复用 0 场"）。
- 其余实测：p26 每帧 0.127–0.141s vs 仓内基线 0.116s(§59⑭)，慢 9–21%，`--jobs 6/8` 未实测（要测再定，不猜）。
- `produce --skip-render` 的复检表补 `skill_sync` + `card_text_check`：V3.34/V3.39 装门时只挂了 `render_all`，走 skip-render 就绕开。

### 82.5 我这轮自己写出的 bug（记下来，因为它正是本仓反复报的那一种）
新切点门第一版用了 `_re`，而 `preflight_v6.py` **从来没有 `import re`** → 跑起来 `NameError`，**rc=1 是崩出来的红、不是门报的红**。
这比漏报更糟：崩溃的 rc=1 与判据的 rc=1 在编排器里长得一模一样，人会以为门有判别力。补 import 后重跑，RED/GREEN 才第一次真正成立。
顺手用 AST 全仓复验"用了 `sys` 却没绑定"的文件 → **0 个**（§29/§30 那类死代码没复发）；`compileall scripts` rc=0；p26 渲前链 8 道逐条复跑除新门全绿。
**判据：新门第一次跑就红，要先问"是判据红了还是它崩了"——看 stderr，别只看 rc。**

### 82.6 第四轮：审我自己刚写的 V3.41（同日，四条都成立）
- **部分 beats.json 静默关掉新门**：第一版 `if not _cuts:` 是 all-or-nothing。实测在临时副本里放一份只声明 `S02` 的 `qa/beats.json`，S01 在 B 表声明的切点**一个字都不查**。修法＝逐场合并（beats 优先、缺的回落 B 表）。**判据：新增的"回落路径"必须和被它替代的旧路径**逐场**合并，不能整文件二选一。**
- **段数判据从 ≥N+1 收紧为 2+N**：实测 p24/p25 的 (声明切点数, 相机段数) 分布 = `{(0,2), (1,3)}`，即 split_beats 每加一个切点恰好多一段。旧判据 `n_cam < N+1` 对 1 个切点只要求 2 段，而 2 段=一条线性推镜=**没有切**——**这道 2020 年就写下的门，判据本身就漏了半格**。回归：p24 对账 7 场 rc=0、p25 对账 8 场 rc=0、p26 红。
- **`setup` 的校验排在建骨架之后**：上一轮我加的 `--copy/--style` 守卫打印"拒绝建项目"，但 `run(new_project)` 在它前面——目录、KICKOFF.md、genre-detect.json 已落盘，改对参数重试还会被 `new_project` 的"目录已存在(防误伤)"挡死。**判据：加了 FAIL 就顺手确认它在副作用之前。**
- **`novelty_meter` 还在用 `proj.parent` 找账本**：与本轮刚修的 metaphor_ledger/palette_oklch 同一类病，漏改。现统一走"项目父目录→仓库根"；另外 D5 的输入来自账本里本片的条目，**新片还没登记时 metas 恒空 → D5 永远不触发**，已回落读 `qa/concepts.txt`。
- **一条被我自己否掉的指控**：subagent 报"p26 有 4 个音效撞在旁白首音节上(0.02/0.04s)"。我用真实首音节(按旁白名义起点后第一个持续 RMS 越阈点)逐个复算：**0/16 落在 ±0.15s 内**——它量的是"音节攻击"不是"语句起点"，结论不成立。**但指控的另一半成立**：15/16 个音效都在"名义起点+0.90s"这个常数上(偏差 ≤0.003s)、全片只有一种 `pop`，且 p26 没有 `qa/events.json`(p24/p25 都有)——**§60 的"音效锚到动作落点"在 p26 退化成网格**。
- **一个常量该更新了**：`mix_audio4.py:176 TP_HEADROOM_DB=0.6`(§59⑬ 当年在 p16 实测)。**p26 实测 WAV −1.6 → MP4 −1.5，只涨 +0.10 dB**，即现在多让出约 0.5 dB 峰值余量(响度 I 不受影响，仍是 −14.0)。这属于混音链常量，改它要重跑混音才见效——留到下一部，且按 §59⑬ 的规矩**用当片实测值**而不是再拍一个保险数。
- **一条待裁定的门设计**：`motion_similarity_check` 是"主风格 base 与上一部不同 → 直接放行"。实测三部**不同风格**片的缓动余弦 p24·p25 **0.950**、p24·p26 **0.962**、p25·p26 **0.983**，全部高于 §70 当年标定的"不同风格历史对最高 0.873"，且三部主导缓动都是 `ease-out`。**换风格档已经不等于运动不雷同**——门的前提被这三行数字推翻了一半。

### 82.7 两件待办的落地（2026-09-29 用户裁定"两件都改"）
- **跨风格也比对运动**：`motion_similarity_check` 旧逻辑"主风格 base 不同 → 直接 return 0"。实测 p24→p25 余弦 **0.9503**、p25→p26 **0.9827**，都高于 §70 当年标定的"不同风格历史对最高 0.873"，且三部主导缓动全是 `ease-out`。**门的前提（换风格≈换运动）被这三行数字推翻。**
- **阈值为什么取 0.97 而不是 0.92/0.95**：本门只量缓动分布，**量不到结构**——p24 视差 12/12、p25 视差 0/16，两部其实差得很远，只差缓动直方图像。把线画在 0.95 会判红 p24→p25 这一对（没人抱怨过它），属于**用窄代理否掉真做过的设计**(§57 假阳性比漏报致命)。0.97 只拦"几乎同一份"：标定 p24 绿 / p25 绿 / **p26 红(0.9827)**，与 §70 用户抱怨的 p20→p21(0.983) 同高。
- **动效词表口径（更正我上一版的错话）**：`EASE_TOKENS` 不只认缓动名，含 `slam_squash`/`pop_spring`/`fly_blur`/`drift_layer`/`stagger`/`wipe`/`peel`/`orbit`/`linear`/`scale` 与"墨晕/描边自绘/擦除/旋转"等；合规=≥30 字 + ≥2 个 `S0N` 场名 + ≥2 个词表命中，最长优先匹配防 `ease-in-out` 被拆成 `ease-in`+`ease-out`。
- **`_declared_diff` 是一条死路（本轮最值钱的一条）**：旧版一撞上含 `A2c…运动差异` 的行就 `return`，而模板把标题与正文分成两行(`**A2c · …**` + `> 正文`)——标题行没有冒号 → 正文永远读不到。实测 p26 写了 S03/S06/S11/S15 四个场名、ease-in/slam_squash/stagger/fly_blur 等五种词汇的真声明，门照样 FAIL。**一道硬门如果在模板自己的写法下没有出口，它就不是"严格"，是"只能改代码才能过"。**修法=扫描所有候选、同行无正文时才往下看。第一版写成"正文不足 30 字就往下合并"，RED 探针当场抓到反向漏洞：标题行改成一句空话时，下面那段真声明会被合并上来凑够字数 → 偷懒照样放行。终态四种写法实测：同行空话拦 / 同行真声明放行 / 长而无动效词拦 / 标题+下一行真声明放行。**判据：书面豁免的解析器必须同时测"太短"和"分行"两种形态，只测一种会修出反向漏洞。**
- **`TP_HEADROOM_DB` 0.6 → 0.3**：实测 WAV→MP4 真峰上涨 p24 +0.2 / p25 +0.1 / p26 +0.10 dB(用 `env_paths` 解析的 WinGet ffmpeg 逐片复测)。旧值是 §59⑬ 在 p16 上测的 0.6，**多让约 0.5 dB**：响度 I 不受影响(仍 −14.0)，但砸下/爆点比允许上限轻半格。取 0.3 = 三部最大值 + 0.1 余量；若某片涨更多，`qa_deliver` 的 −1.0 门会当场拦下(发不出削波片)。**判据：余量常量要带"在哪几部上测的"，跨设备/跨编码器时它就不是常数。**

### 82.8 `patch_offscreen.py`：查过能不能捞回，结论是删承诺（2026-09-29）
- **捞不回来**：`~/.qoder-cn/projects/H--VOX-Video-Qwen/*.jsonl` 里 53 处 `patch_offscreen` 全是**引用**（文档句、我的思考文本、命令回显），按 §77 的恢复法逐行解析写盘入参，**没有一条带脚本正文**。所以"补回 scripts/"实际等于"新写一个再冒充恢复"——不做。
- **它的存在理由已经消失**（两条都是本仓自己后来的改动）：① 它当年解决"不想整片重做"，现在 `scene_fingerprint` 增量渲染让"只重渲受影响场"成为默认（p23 实测 863s→2s）；② 它直接改 scene JSON 的关键帧，而 V3.39 的 `regen_check` 逐场比对"生成器+`_postfix` 的 layers vs 盘上 JSON"——**手工位移必须回写 `build_scenes.py` 才能过门**，于是它想省的那一步现在省不掉，反而多一道返工。
- **正解三步**（写进 SKILL 阶段⑥ 与工具清单）：设计期 `CARD_EDGE`/`STAGE_EDGE`/`clamp_card_in` 挡住 → 渲前 `layout_check` 的 HARD 报数用来**改生成器常量**（不是在 JSON 上平移）→ 增量重渲 + 复用音轨 + `regen_check` 复验。
- **一般判据**：删一个能力时，除了 grep 谁在读它（§76），还要问"**它解决的问题现在还存在吗**"——若已被后来的机制顶掉，正确动作是删承诺，而不是恢复工具。

### 82.9 回归自己改出来的东西时，抓到 `regen_check` 两条"检查器说谎"（2026-09-29 收尾）
用户要求"再审查一遍，不要改错了"。把当天改过的门在 p24/p25/p26 上全跑一遍，抓到的不是我改坏的东西，而是**一个从没真跑过的门自己在说谎**：
- **① 它文档写"只读不写"，实际会把项目 JSON 重写一遍**：旧版直接调用项目的 `s01()..sNN()`，而 p26 的 `emit()` 在 `sNN()` 里就 `write_text` → 跑一次对账，16 个 scene JSON 的 mtime 全被刷新（实测）。**真正的危险不是 mtime**：如果生成器已经和盘上漂移（正是本门要抓的事），跑一次就把盘上的手修覆盖掉，**第二次跑必然 PASS——一个会把证据抹掉的探测器**。
- **② 它假设 `sNN()` 返回 dict**：p26 的形状是"内部写盘、返回 None" → `d["layers"]` 抛 `TypeError`，rc=1 是**崩出来的红**（当天第三次犯同一族错：`_re` 未导入、`BANNED_FILE_PREFIX` 未定义、这次是别人的假设）。
- **修法**：把模块的 `HERE` 重定向到临时目录（生成器写哪儿由我们定）+ 两种形状都支持（返回 dict 直接用；返回 None 就从临时目录读回它刚产出的）+ **兜底逐字节还原**（万一生成器无视 HERE 直写项目，还原并点名）。
- **复验**：p24/p25/p26 全部 `PASS`（12/16/16 场 layers 与生成器逐场一致＝**三部已交付片都可复现**），且 md5 与 mtime 双证"跑前跑后一个字节没动"；空目录/不存在路径都干净 rc=1、无 traceback。
- **判据：探测器必须验证"自己不改被检测对象"。** 一个会写盘的只读检查，比没有检查更坏——它会在你看到问题之前把问题抹平。
