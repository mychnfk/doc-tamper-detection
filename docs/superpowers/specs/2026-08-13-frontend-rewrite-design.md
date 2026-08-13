# DocGuard 前端重写设计 Spec — React + FastAPI

> **背景**：现有 Gradio 界面视觉不达标（白底紫胶囊、标签压图、Gradio 默认工具栏外露、结论不在视觉中心、三图并排靠人眼对齐）。决赛窗口一个月以上，评委含顺丰科技技术领导 + 财务/业务方。
> **本 spec 只覆盖前端与其 API 层**。检测与 Agent 逻辑不在范围内。

---

## 1. 目标与非目标

**目标**
1. 把界面从"Gradio demo 感"提升到"企业级审核台"
2. 结论前置：财务评委一眼拿到「有没有问题 + 该怎么办」
3. 技术纵深可展开：技术评委能看到完整 Agent 轨迹与取证细节
4. **记录模块**：每次检测自动留痕，可列表浏览与回放，支撑"预跑 + 现场实跑 1-2 张"的演示方案

**非目标（明确不做）**
- 不做批量上传/批量跑批界面（批量 = 多次单张检测的记录累积）
- 不做双模式并排对照视图
- 不做用户系统、权限、多租户
- 不做前端单元测试（决赛项目，靠 E2E 截图核对）
- 不改动检测与 Agent 层

---

## 2. 全局约束

| 约束 | 值 |
|---|---|
| 后端零改动文件 | `agent.py` `tools.py` `run_inference.py` `regions.py` `config.py` |
| 现有测试 | 42 passed / 1 skipped 必须继续全绿 |
| Gradio 版本 | `app.py` **原封不动保留作回退**，独立端口 7860 |
| 新增 **Python** 依赖 | **零**（FastAPI 0.138.2 / uvicorn 0.49.0 已装且已在 requirements.txt）。前端 npm 依赖另计，见 §6.1 |
| 复核模式 | 沿用现有三种：`agent` / `direct` / `cv`，语义与 `agent.py::review(mode=)` 完全一致，不新增不删减 |
| 第三方 Claude skill | **一个都不装**（见 §7 供应链决策） |
| 启动 | 保持一键：`./start-web.sh` |
| 敏感数据 | `runs/` 含真实业务单据，**必须 gitignore** |

---

## 3. 架构

```
web/  Vite + React + TS + Tailwind + shadcn/ui + ai-elements
  上传 → POST /api/detect (SSE) → 流式渲染轨迹 → 结论卡片
  记录 → GET /api/runs → 列表 → GET /api/runs/{id} → 回放
                    ↕ HTTP / SSE
api.py  FastAPI
  /api/detect(SSE) · /api/runs · /api/runs/{id} · /api/runs/{id}/{file}
  兜底：静态托管 web/dist
                    ↓
pipeline.py  新增（UI 无关的检测编排）
  run_detection(image_path, mode) -> Iterator[TraceEvent]
                    ↓
agent.py / tools.py / run_inference.py / regions.py     ← 零改动

app.py  Gradio 回退版，端口 7860，本次不动
```

**关键设计依据**：`review()` 是纯生成器，只 `yield TraceEvent`，从不感知消费者。现有消费者已有三个（Gradio 渲染 / `evaluate.py` 静默排空 / `smoke_agent.py` 打印），本次新增第四个 SSE 消费者，属于既有扩展点，不是改造。

### 3.1 关于 `pipeline.py` 与 `app.py` 的重复

`pipeline.py` 的检测编排逻辑（CV 推理 → 渲染热力图/置信度图 → 组装 `AgentContext` → 转发 `review()`）与 `app.py::analyze()` 约 30 行重复。

**这是有意接受的重复**，不做 DRY 收敛。理由：回退版本的价值在于"出事时能切回一个已验证的版本"，若 `app.py` 也被改动，回退价值即打折。重复的两段均为稳定代码，过渡期漂移风险低于回退失效风险。React 版稳定并通过彩排后，可另行决定是否收敛。

---

## 4. 数据流与协议

### 4.1 SSE 事件协议

`POST /api/detect`（multipart：图片 + mode），响应 `text/event-stream`：

```
event: trace
data: {"run_id":"20260813-153012-a3f9","turn":2,"type":"tool_call","payload":{...}}

event: done
data: {"run_id":"20260813-153012-a3f9","duration_ms":114320}
```

- `type` 沿用现有六种：`stage` `thought` `tool_call` `tool_result` `verdict` `fallback`
- **不变量继承**：最后一个 `trace` 事件恒为 `type=verdict`（`agent.py` 已有回归测试保障）
- payload 中的 PIL 图片**不内联 base64**，落盘后替换为 URL：
  `{"images": ["/api/runs/20260813-153012-a3f9/img/t2-0.jpg"]}`

### 4.2 落盘先于推送

每个事件**先写入 `events.jsonl`，再推送 SSE**。

这样断连（含彩排要测的物理断网）不会丢失已完成的检测——前端重连后可从 `/api/runs/{id}` 恢复完整轨迹。这同时是记录模块的写入路径，一套代码两个用途。

### 4.3 记录目录结构

```
runs/20260813-153012-a3f9/
  meta.json        # mode, score, infer_size, conclusion, risk, duration_ms, source, image_name, created_at
  original.jpg
  heatmap.jpg
  confidence.jpg
  events.jsonl     # 每行一个 TraceEvent + elapsed_ms，图片已替换为相对路径
  img/t2-0.jpg     # 轨迹中的 zoom 裁剪图，t{turn}-{idx}
```

`events.jsonl` 每行额外带 `elapsed_ms`（距本次检测开始的毫秒数）。**这是 §6.2 "按原始节奏重放" 的前提**——没有它就只能等间隔回放，还原不出"CV 等 80 秒、思考 30 秒、工具返回瞬间"的真实节奏差异。

**失败与降级的检测同样记录**：`fallback` 事件与最终 verdict 一并落盘，`meta.json` 的 `source` 字段区分 `agent` / `agent-forced` / `direct` / `cv`。降级案例是彩排与 QA 的证据材料，不能因"跑得不完美"就不留痕。

`run_id` 格式 `YYYYMMDD-HHMMSS-{4位随机}`，天然按时间排序。存储用文件系统，**不引入数据库**（规模为几十条，YAGNI）。

### 4.4 API 清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/detect` | multipart 上传 + mode，返回 SSE 流 |
| GET | `/api/runs` | 记录列表，返回各 run 的 meta.json 摘要 |
| GET | `/api/runs/{id}` | 单条记录的 meta + 全部 events |
| GET | `/api/runs/{id}/{file}` | 静态文件（原图/热力图/裁剪图） |
| DELETE | `/api/runs/{id}` | 删除单条记录（演示前清理用） |

---

## 5. 美学方向（按 remix 方法逐层仲裁）

方法来自 `rohitg00/awesome-claude-design` 的 remix recipe：**逐层从单一来源取，不做层内混合**。

**参考锚点**：A = Linear（排版纪律、冷中性、高信息密度）　B = Stripe Dashboard（金融语义、表格数据、可信感）

| 层 | 来源 | 决策 |
|---|---|---|
| **排版** | 整体取 B 方向 | 中文 **HarmonyOS Sans SC**（开源免费商用，非 system font）；拉丁与数字 **IBM Plex Sans / IBM Plex Mono**。数字一律 `font-variant-numeric: tabular-nums` |
| **中性色** | A | 底色 `#FAFAF8` 微暖 off-white（**不用纯白 #FFF**），文本冷灰阶 |
| **强调色** | B | **深墨蓝 `#1B3A5C`，全站唯一强调色** |
| **语义色** | 独立 | 判定三态低饱和：正常 `#2F6B4F` / 疑似 `#8A6A1F` / 高度可疑 `#8C3A32`。**属数据编码，不计为第二强调色** |
| **间距** | 取更严格者 | 4px 基准：4/8/12/16/24/32/48 |
| **圆角** | 匹配所选排版 | 4px 小圆角（IBM Plex 的工业感） |
| **深度** | 取更克制者 | **border-based，全站禁用 drop shadow** |
| **图标** | 显式指定 | **Lucide 唯一家族**——anti-slop 禁的是"无指定时默认落到 Lucide"，显式选定即满足"每项目恰好一个图标家族" |

### 5.1 强制禁令（anti-slop，逐条可自审）

1. ❌ teal（`#16d5e6` 及邻近）作强调色
2. ❌ 第二个强调色（唯一强调色只有深墨蓝）
3. ❌ 紫色渐变 / 白底紫胶囊标签（**现版本的病根**）
4. ❌ 动画状态点、闪烁灯、pulsing orb → 状态一律用**静态字形 + 明确文字**
5. ❌ 容器嵌套深度 > 2；❌ card-on-card
6. ❌ Inter / Roboto / Arial / system-ui 作主字体
7. ❌ 三列特性网格
8. ❌ drop shadow 制造层次（改用 border 或色调差）
9. ❌ 装饰性动效（浮动粒子、视差）
10. ✅ 全站 `prefers-reduced-motion` 必须生效

### 5.2 动效预算

仅两处，其余静态：
- 轨迹条目流入：staggered `animation-delay`，单条 ≤160ms
- 结论卡片出现：一次淡入 + 轻微上移，≤200ms

### 5.3 Token 来源记账

remix 方法要求给出血统占比，实施完成后在 `web/DESIGN.md` 记录实际 token 计数（预估 A≈45% / B≈55%）。

---

## 6. 界面结构

```
┌──────────────────────────────────────────────────────┐
│ DocGuard 文档篡改审核台      [检测] [记录]    模式 ▾ │
├────────────────────────┬─────────────────────────────┤
│                        │  ┌───────────────────────┐  │
│  拖拽上传区            │  │ ● 正常      风险 低   │  │ 结论卡片
│   ↓ 检测后             │  │ 建议：可进入财务流程  │  │ 视觉中心
│  原图 ⇄ 热力图         │  └───────────────────────┘  │
│  对比滑块              │                             │
│                        │  审核轨迹                   │
│  [ 开始检测 ]          │   Reasoning  第1轮·思考     │
│                        │   Tool       第2轮·放大查证 │
│                        │   ▸ 为什么这么判            │
├────────────────────────┴─────────────────────────────┤
│ ▸ 技术细节   置信度图 · 分数 0.1138 · 1080×1088      │
└──────────────────────────────────────────────────────┘
```

**渐进式披露三层**：结论（永远可见）→ 轨迹（默认展开）→ 技术细节（默认收起）。

### 6.1 组件映射（Vercel `ai-elements`，npm 依赖非 skill）

| TraceEvent | 组件 |
|---|---|
| `thought` | `Reasoning` / `Chain of Thought` |
| `tool_call` | `Tool` |
| `tool_result` | `Tool` + `Image` |
| `verdict` | `Message` + 自建结论卡片 |
| `stage` | `Task` + `Shimmer`（治大图 CV 阶段的长静止） |
| `fallback` | `Confirmation` |

原图⇄热力图对比滑块用 `react-compare-slider`（`ai-elements` 无对应组件）。

**前端 npm 依赖清单**（全部为构建期/运行期前端依赖，不影响 Python 环境）：

| 包 | 用途 | 出处 |
|---|---|---|
| `react` / `react-dom` / `typescript` / `vite` | 工程基座 | — |
| `tailwindcss` | 样式 | — |
| shadcn/ui 组件 | 基础组件（拷贝进仓库，无运行时依赖） | `npx shadcn@latest add` |
| `ai-elements` | Agent 轨迹组件 | **Vercel 官方**，周下载 4.4 万 |
| `react-compare-slider` | 原图⇄热力图对比 | — |
| `lucide-react` | 唯一图标家族（§5 显式指定） | shadcn 默认 |

字体（HarmonyOS Sans SC / IBM Plex）**自托管并子集化**，不走 CDN——演示机可能无外网，且 §11 已列为已知取舍。

### 6.2 记录页

表格列：缩略图 / 文件名 / 时间 / 模式 / CV 分数 / 判定 / 风险 / 轮数 / 耗时。可按分数与时间排序，按判定筛选。点击行进入回放——顺序渲染 `events.jsonl`，**支持按原始节奏重放**（还原流式观感，零 API 消耗），页面须**明确标注"记录回放"**，不得让人误认为实时检测。

### 6.3 等待期反馈

CV 阶段耗时随图尺寸相差 8 倍（1080px 约 10s / 3456px 切片约 80s）。上传后立即读取图片尺寸，显示预期耗时与切片片数，配 `Shimmer` 占位。

---

## 7. 供应链决策

审计后**不安装任何第三方 Claude skill**：

| 候选 | 决定 | 依据 |
|---|---|---|
| `nathanonn/claude-skills-ai-elements` | ❌ | 1★/2 commits；所需能力由 npm 包 `ai-elements` 直接提供 |
| `mattbx/shadcn-skills` | ❌ | 15★；proactive 主动插入、强加风格规则、会直接改文件 |
| `Leonxlnx/taste-skill` | ❌ | 默认参数 8/6/4 与本项目定位相反；且指示"不再征求许可自行决策"，与项目 CLAUDE.md 冲突 |
| `frontend-design`（Anthropic 官方） | ✅ 已装 | 65k★ 官方 |
| `awesome-claude-design` | ✅ 仅取文本 | MIT 纯 prompt，规则已并入本 spec §5，无需安装 |
| Vercel `ai-elements` | ✅ npm 依赖 | 官方、周下载 4.4 万 |
| shadcn 官方 MCP | ✅ 可选 | `npx shadcn@latest mcp init` |

**原则：能用依赖解决的不用 skill 解决。** 依赖有版本、lockfile、下载量与审计工具；skill 是注入模型行为的自由文本，无版本锁也无可观测性。

---

## 8. 错误处理与降级

| 场景 | 行为 |
|---|---|
| VLM 不可用 | 后端三级降级已有（Agent → 直链 → CV-only），前端只需渲染 `fallback` 事件的友好文案，原始异常收进可展开的「技术详情」 |
| API key 未配置 | 启动预检失败并给出明确提示（沿用 `start.sh` 的检查逻辑） |
| SSE 断连 | 前端提示"连接中断"，提供"从记录恢复"入口；因落盘先于推送，已产生的事件不丢 |
| 上传非图片/损坏文件 | 后端 400 + 明确原因，前端就地提示不跳转 |
| 图片过大 | 沿用现有切片路径，仅在 UI 上提示预期耗时 |
| 并发 | 单模型实例，后端串行化处理（沿用 Gradio `concurrency_limit=1` 的语义） |

---

## 9. 测试策略

| 层 | 方式 |
|---|---|
| 现有 42 测试 | 必须继续全绿，作为"后端未被破坏"的判据 |
| `pipeline.py` | 新增单测：stub VLM 下事件序列正确、末事件恒为 verdict |
| `api.py` | 新增单测：SSE 事件格式、`runs/` 落盘与读取、断连后可恢复、非法上传返回 400 |
| 前端 | 不做单测。用 playwright 对三个关键态截图核对：初始态 / 检测中（轨迹流式）/ 结论态（含折叠块**默认收起**——坑 #8 的回归点） |
| 美学 | 按 §5.1 十条禁令逐条自审，附截图证据 |

---

## 10. 交付与启动

```
./start.sh       # Gradio 回退版，端口 7860，不动
./start-web.sh   # 新版：构建 web/dist（若无）→ uvicorn api:app，端口 8000
```

`start-web.sh` 沿用现有预检（`.env` 中 `DASHSCOPE_API_KEY`、TruFor 权重），另加 `web/dist` 存在性检查与 node 版本检查。

**新增 gitignore**：`runs/`、`web/node_modules/`、`web/dist/`。

---

## 11. 已知取舍

1. **`pipeline.py` 与 `app.py` 约 30 行重复** —— 为保住回退版本完整性有意接受，见 §3.1
2. **中文字体需自托管**（HarmonyOS Sans SC 约 3-8MB/字重）—— 本地演示可接受，需在构建时子集化以免首屏过慢
3. **记录回放不是实时检测** —— 必须在 UI 上明示，避免演示中被质疑"预录"
4. **`runs/` 累积真实业务单据** —— 已 gitignore，但演示机上仍为明文，彩排前需人工清理无关记录
