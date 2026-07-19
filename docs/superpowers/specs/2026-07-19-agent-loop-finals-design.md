# DocGuard 决赛升级设计：Agent Loop + Demo 打磨 + 技术深度

> **状态**：设计已批准（2026-07-19，三节逐节确认）
> **背景**：已通过初赛+复赛，进入 top10 决赛。决赛评委含顺丰科技技术领导，需真实技术深度。
> **决赛形式**：未定，按最严苛标准设计（现场操作 + 评委可能动手试用）。
> **时间**：两周以上，业余时间（下周领导出差，可投入时间较多）。

---

## 1. 目标与范围

三个目标：

1. **Agent Loop 升级**：将现有 Agent 直链（query → tool use → VLM 复核 → output）升级为 VLM 自主决策的真 Agent Loop。
2. **Demo 打磨稳**：按"现场操作 + 评委动手"标准加固鲁棒性与演示体验。
3. **技术深度补强**：UI 实时 Agent 轨迹 + 答辩 QA 预案 + 自建评测集性能数据。

### 已决策的关键选择（含理由）

| 决策 | 选择 | 理由 |
|---|---|---|
| Loop 机制 | **真 Agent Loop**，VLM 每轮自主决定调用工具/终止 | 技术评委一眼能分辨真 agent 与规则升级链；真实现才经得起追问 |
| 工具集 | **区域放大重审 + HiFi-Net 第二模型**（HiFi-Net 视资源动态注册） | 每个工具提供 VLM 裸看原图拿不到的独立证据 |
| OCR 工具 | **不做** | qwen3.7-max 自身 OCR 能力足够，放大裁片后文字它自己读；独立 OCR 是重复建设 |
| TruFor 裁片重检 | **不做** | Noiseprint++ 需全图噪声基线（已知坑 #3），裁片重检分数不可信——此"为什么不做"进 QA 预案 |
| 部署 | **双轨**：Mac MPS 保底可全量演示；公司服务器（拟申请 16G 显存+32G 内存，内网）到位后升级 | 服务器尚未提申请，到位时间不可控，设计不得依赖它 |
| 协议 | **JSON 行动协议**为主，Day1 探测专属端点原生 function calling，支持则协议层切换 | 专属端点 FC 支持未验证；自管协议便于轨迹流式化与失败回退 |

---

## 2. 总体架构

```
用户上传图片 (Gradio)
  ↓
[阶段一] TruFor 首检（常驻模型，现有逻辑不动）
  → score / loc_map / conf_map / infer_size
  → loc_map 阈值化 + 连通域提取 → top-K 可疑区域候选框（新增）
  ↓
[阶段二] Agent Loop（qwen3.7-max，最多 3 轮）
  每轮输入: 原图 + 热力图 + score + 候选框列表 + 工具调用历史
  每轮输出: JSON {thought, decision, action?, verdict?}
    ├─ decision=investigate → 执行 action:
    │    · zoom_region(bbox)   → 从原始文件裁全分辨率高清片，送回下一轮
    │    · second_opinion()    → HiFi-Net 二次检测（仅当已注册）
    └─ decision=verdict → 终止，输出最终判定
  ↓
[阶段三] 最终审核意见 + 完整 Agent 轨迹（全程流式推给 UI）
```

### 文件布局（延续扁平风格）

```
app.py              改造：三栏布局 + Chatbot 轨迹面板 + 流式渲染
run_inference.py    基本不动：max_size 改为从 config 读
agent.py            新：Loop 核心——协议、循环、终止、回退
tools.py            新：Tool 契约 + 注册表 + zoom_region + second_opinion
hifi_inference.py   新：HiFi-Net 适配器（镜像 run_inference.py 接口形状）
evaluate.py         新：评测集跑分 + 阈值校准 + CV/Agent 端到端对照
config.py           新：双轨开关——MAX_SIZE / AGENT_MAX_TURNS / ENABLE_HIFI / 阈值 / 设备覆盖
eval-images/        新：评测集（6 类子目录，目录即标签）
docs/QA预案.md      新：答辩预案
start.sh            新：一键启动（环境检查 + warmup + 起服务）
```

---

## 3. 接口契约（接口先行，现在定死）

1. **DetectorBackend**：`run(image_path) → {score, map, conf, infer_size}`
   TruFor 现有返回即此形状；HiFi-Net 适配为同形状；未来换/加模型走同一个口。
2. **Tool**：`name / description（写给 VLM）/ args_schema / available() / run(ctx, **args) → ToolResult{text, images[]}`
   注册表启动时逐个探测 `available()`；Mac 上 HiFi-Net 探测失败自动摘除。**工具箱随环境伸缩，Agent 协议不变**——双轨核心机制。
3. **Trace 事件**：`{turn, type: thought|tool_call|tool_result|verdict, payload}`
   `agent.py` 以生成器 yield 事件；`app.py` 消费渲染；`evaluate.py` 静默消费同一事件流。**Loop 与 UI 彻底解耦，评测与 Demo 共用同一代码路径**（数字可信的前提）。

---

## 4. Agent Loop 协议细节

- **bbox 表达**：VLM 用 0-1000 归一化坐标（qwen-vl 系训练充分）；裁片**从原始上传文件取全分辨率像素**——坑 #2 铁律：取证证据不得经过任何缩放。
- **候选框兜底**：VLM 可直接选用 TruFor 连通域 top-K 候选框（编号引用）而非自由画框，防 bbox 画偏。
- **终止条件（三重保险）**：① VLM 主动给出 verdict；② 达最大轮数（默认 3）强制收敛；③ JSON 连续解析失败 2 次 → 整体回退直链模式。
- **回退链**：现有 `vlm_review()` 直链路径保留不删，作为二级形态；直链再失败 → CV-only 结果。每层失败都落回上一届已实战验证的形态。
- **大图（坑 #3）缓解**：切片推理的图在 ctx 中告知 VLM"全局分数可信度低"，引导 investigate + 放大重审；服务器到位后 `MAX_SIZE` 提档（实测 2560-3072），3456px 图力争整图直推。

### 错误处理

| 故障 | 处理 |
|---|---|
| VLM API 失败 | 重试 1 次 → 回退直链 → 最差 CV-only 照常展示 |
| JSON 解析失败 | 带格式提醒重试 → 2 次失败回退直链 |
| 工具执行异常 | 包成 ToolResult(error) 交还 VLM 裁决，UI 不炸 |
| 非金融文档图 | VLM 首轮识别文档类型，温和拒绝并提示 |

---

## 5. UI 设计

三栏布局（Gradio Blocks，不换框架）：

```
┌────────────┬──────────────────┬──────────────────────┐
│ 上传区      │  CV 取证结果       │  AI 审核过程（新）      │
│ 图片上传    │  热力图 / 置信度图  │  gr.Chatbot 轨迹流:    │
│ 模式选择    │  score + 判定色标  │   💭 思考(折叠块)       │
│ 开始检测    │  推理信息          │   🔧 工具调用徽章       │
│ 示例图集    │                   │   🖼️ 高清裁片内嵌       │
│            │                   │   ✅ 最终审核意见卡     │
└────────────┴──────────────────┴──────────────────────┘
```

- 轨迹用 `gr.Chatbot` + metadata 折叠块（Gradio 6.19 原生），放大裁片以图片消息内嵌轨迹。
- handler 改生成器，消费 Trace 事件流逐条 yield；TruFor 阶段显示"像素级取证中…"。
- **模式 Radio 三档**：`Agent 复核（默认）/ 快速复核（直链）/ 仅 CV`——三条路径本就存在，暴露成开关后可现场对照演示（同一误报图：快速模式标红 → Agent 模式放大重审排除）。

---

## 6. 评测集与阈值校准

### 评测集（13-15 张，目录即标签）

```
eval-images/
├── normal/     正常单据 ×3-4（真实脱敏样张，业务组员提供）
├── amount/     PS 改金额 ×2-3
├── date/       PS 改日期 ×2
├── seal/       PS 改印章 ×2
├── aigc/       AI inpaint 重绘 ×2
└── copymove/   复制粘贴 ×2
```

- 篡改样本**分两档手艺**：粗改（演示直观）+ 精改（贴字体羽化边缘，指标可信）。
- **指标口径（对评委主动讲明）**：图级检出率/误报率为主；定位效果定性展示热力图对照，不做像素级定位 F1（需 mask 标注，两周内做是伪严谨）。

### evaluate.py 四件事

1. 批量跑 TruFor → score 落 CSV + 分布图（正常 vs 各篡改类）→ 答辩素材。
2. 阈值扫描（TPR/FPR）→ 用分布分位数替换拍脑袋的 0.4/0.7，回写 `config.py`；灰区宽度直接决定 Agent 进 Loop 频率。
3. `--mode cv|agent` 端到端对照：CV 单独 vs 完整 Agent 链路各跑一遍——**误报率下降即 VLM 复核价值的最硬数字**。
4. （服务器后）HiFi-Net 同集跑分 → 两模型一致性/互补性数据。

---

## 7. Demo 打磨清单

| 类别 | 项目 |
|---|---|
| 输入防护 | HEIC 支持（`pillow-heif`，评委 iPhone 图）；非单据图温和拒绝；损坏/超大文件友好提示 |
| 并发 | `queue(concurrency=1)` 单卡串行 + 排队提示 |
| 延迟感知 | 启动 warmup（首次推理编译开销不能落在演示上）；流式轨迹 |
| 兜底 | 三级降级链（Agent → 直链 → CV-only），断网也出热力图 |
| 彩排 | 评测集全量预跑记录预期行为；4 张剧本图：重度篡改秒判 / **灰区图触发 Loop 放大改判（核心桥段）** / 误报被 Agent 排除 / 正常图快速通过 |
| 视觉 | 固定浅色主题（投影仪）、字号、判定卡配色 |
| 启动 | `start.sh` 一键起 |

---

## 8. QA 预案骨架（docs/QA预案.md，每问 3-5 句口径 + 指向证据）

- **架构类**：为什么双层不端到端；终止条件/防死循环；JSON 协议 vs 原生 FC（按 Day1 探测结果定口径）；工具扩展机制。
- **CV 类**：TruFor 双分支原理（RGB + Noiseprint++，SegFormer-B2）；为什么绝不缩放（自测 0.945→0.177）；大图切片局限与三层对策；HiFi-Net 互补性；误报来源。
- **指标类**：自建集数字解读；小样本可信度的诚实口径（域内点估计 + DOCFORGE-BENCH 校准依据）；对抗性边界（AI 辅助人工而非替代）。
- **数据安全类（预判最凶一问）**：财务文档送外部 API 必被追问。口径：Demo 阶段公有云 API 快速验证；VLM 客户端已抽象，生产态可替换内网自部署开源 Qwen-VL；服务器内网部署即该路径的第一步。

---

## 9. 里程碑（两周+）与风险

```
Day 1        验活 + 探测：app.py 复跑（19 天未动）、原生 FC 探测、HEIC
Day 2-5      Loop 核心：agent.py / tools.py(zoom) / config.py + 回退链，CLI 冒烟
Day 5-8      UI 改造：三栏 + Chatbot 流式 + 三模式 Radio
Day 6-9 ∥    评测线（并行）：样张收集 → 篡改样本制作（两档）→ evaluate.py → 校准回写
服务器轨 ∥    申请立刻提交（审批为别人的时间，只能靠早触发）
             到位后：环境搭建 → HiFi-Net 适配+注册 → MAX_SIZE 提档实测 → 内网部署
最后 3-4 天   QA 预案写作 + 剧本彩排 + buffer
```

**关键路径风险**：
1. 服务器审批时长 → 设计不依赖，Mac 全量可演；HiFi-Net 在 Mac 8GB 实测不可行则为服务器专属工具。
2. 业务样张到位时间 → 评测线上游，立刻向业务组员发起收集。
3. qwen bbox 画偏 → 候选框编号引用兜底。

---

## 10. 明确不做（YAGNI）

- OCR 独立工具（VLM 自身覆盖）
- TruFor 裁片重检（噪声基线原理性不可行）
- 像素级定位 F1 评测（mask 标注成本不匹配）
- ForensicHub 多方法对比实验、TextIn 商用 API 对标（时间不可控，边际收益低；进度超前时再议）
- 自部署 VLM（Demo 阶段 API 即可，仅作为 QA 口径中的生产态路径）
- 前端框架更换（Gradio 够用且已熟）
