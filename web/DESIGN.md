# DocGuard 前端设计规范

本文件是**验收依据**，不是风格建议。第 3 节每条禁令都配一条可执行命令，
Task 11 自审时逐条跑，全绿才算达标。判断"好不好看"没有客观标准，
判断"有没有紫色渐变"有。

规范来源：`docs/superpowers/specs/2026-08-13-frontend-rewrite-design.md` §5。

---

## 1. 仲裁方法

用 remix recipe：**逐层从单一来源取，不做层内混合**。混合会得到"哪都像、哪都不像"的
平均脸——正是 AI 生成界面的典型病征。

**参考锚点**：A = Linear（排版纪律、冷中性、高信息密度）　B = Stripe Dashboard（金融语义、表格数据、可信感）

| 层 | 取自 | 决策 |
|---|---|---|
| 排版 | **B** | 中文 HarmonyOS Sans SC（开源可商用，非 system font）；拉丁与数字 IBM Plex Sans / IBM Plex Mono |
| 中性色 | **A** | 底色 `#FAFAF8` 微暖 off-white（不用纯白），文本冷灰阶 |
| 强调色 | **B** | 深墨蓝 `#1B3A5C`，全站唯一 |
| 语义色 | 独立 | 判定三态低饱和；属数据编码，不计为第二强调色 |
| 间距 | **A** | 4px 基准，取更严格者 |
| 圆角 | **B** | 4px 小圆角，匹配 IBM Plex 的工业感 |
| 深度 | **A** | border-based，禁 drop shadow |
| 图标 | 独立 | Lucide 唯一家族（显式指定即满足"每项目恰好一个图标家族"） |

---

## 2. 令牌

唯一真源：`src/lib/design-tokens.css`。任何组件不得出现十六进制字面量。

### 2.1 原始令牌

| 令牌 | 值 | 用途 | 血统 |
|---|---|---|---|
| `--bg` | `#FAFAF8` | 页面底色 | A |
| `--surface` | `#FFFFFF` | 内容卡面（**不作页面底色**） | A |
| `--surface-sunk` | `#F1F0EC` | 凹陷底：代码块、hover、次要区块 | A |
| `--border` | `#E4E3DE` | 常规分隔 | A |
| `--border-strong` | `#CFCEC7` | 强调分隔 | A |
| `--text` | `#1C1C1A` | 正文 | A |
| `--text-muted` | `#6B6B66` | 次要文字 | A |
| `--accent` | `#1B3A5C` | **全站唯一强调色** | B |
| `--accent-weak` | `#E8EDF3` | 强调色浅底 | B |
| `--ok` / `--ok-bg` | `#2F6B4F` / `#EDF3EF` | 判定：正常 | 独立 |
| `--warn` / `--warn-bg` | `#8A6A1F` / `#F5F0E4` | 判定：疑似 | 独立 |
| `--danger` / `--danger-bg` | `#8C3A32` / `#F6EBE9` | 判定：高度可疑 | 独立 |
| `--s1`…`--s12` | 4/8/12/16/24/32/48 | 间距，4px 基准 | A |
| `--radius` | `4px` | 全站统一圆角 | B |
| `--font-cn` / `--font-en` / `--font-mono` | HarmonyOS Sans SC / IBM Plex Sans / IBM Plex Mono | 字体 | B |

### 2.2 消费层：为什么用 shadcn 的语义名

`src/index.css` 的 `@theme` 把上表映射成 shadcn 的语义名
（`primary` / `muted` / `accent` / `destructive` …）。这样 vendored 组件
（badge、button、collapsible、ai-elements）**零改动**就用上我们的配色，
自研组件也用同一套名字，不存在两套命名。

⚠️ **两个必须记住的命名陷阱**（映射错不会报错，只会静默变丑）：

| shadcn 名 | 它的真实语义 | 不是 |
|---|---|---|
| `accent` | **悬停态浅底色** → 映射到 `--surface-sunk` | 品牌强调色 |
| `muted` | **浅灰底色** → 映射到 `--surface-sunk` | 次要文字色（那是 `muted-foreground`） |

品牌强调色一律走 `primary`。若把 `--color-accent` 映射成 `--accent`（深墨蓝），
所有 `hover:bg-accent` 会变成深蓝实底。

---

## 3. 十条禁令与自审命令

在 `web/` 目录下执行。全部应输出 0 或空。

```bash
# 1. 禁 teal 作强调色
grep -rniE '#(16d5e6|0d9488|14b8a6|2dd4bf)|\bteal-' src/ | grep -v DESIGN.md

# 2. 禁第二强调色：源码不得出现十六进制字面量（颜色只能来自令牌）
grep -rnE '#[0-9a-fA-F]{6}\b' src/ --include='*.tsx' --include='*.ts'

# 3. 禁紫色渐变 / 白底紫胶囊
grep -rniE 'purple|violet|fuchsia|#(a{2}3bff|c084fc|8b5cf6)|bg-gradient' src/

# 4. 禁动画状态点（状态一律静态字形 + 文字）
grep -rnE 'animate-(ping|pulse|bounce|spin)' src/

# 5. 容器嵌套 ≤2，禁 card-on-card
grep -rn 'rounded-\[?var(--radius)' src/ | wc -l   # 人工核对：卡片不得互相包含

# 6. 禁 Inter / Roboto / Arial / system-ui 作主字体
grep -rniE "font-family:[^;}]*(inter|roboto|arial|system-ui)" src/

# 7. 禁三列特性网格
grep -rnE 'grid-cols-3' src/

# 8. 禁 drop shadow（焦点环除外——Tailwind 的 ring 也走 box-shadow）
grep -rnE '\bshadow-(sm|md|lg|xl|2xl)?\b' src/ --include='*.tsx'

# 9. 禁装饰性动效（浮动粒子、视差）
grep -rniE 'parallax|particle|float-anim' src/

# 10. prefers-reduced-motion 必须生效（应输出 1）
grep -c 'prefers-reduced-motion' src/lib/design-tokens.css
```

构建产物侧的校验（`npm run build` 之后）：

```bash
css=$(ls dist/assets/*.css)
grep -oE '\.shadow[a-z0-9\\:-]*\{' "$css"   # 应为空：无 drop shadow 工具类
grep -c 'ring-shadow' "$css"                 # 应 ≥1：焦点环保留，键盘可访问
grep -coiE 'aa3bff|c084fc' "$css"            # 应为 0
```

### 3.1 第 8 条的实施偏离（重要）

spec 原文是"全站禁用 drop shadow"，最初实现为 `* { box-shadow: none !important }`。
**这条会连键盘焦点环一起干掉**——Tailwind 的 `ring-*` 同样基于 `box-shadow`。
一个要交给评委操作的审核台，Tab 导航看不见焦点位置是硬伤。

改为只清 drop shadow 的变量、保留 ring 的变量：

```css
* { --tw-shadow: 0 0 #0000 !important; }
```

同时从 `button.tsx` / `badge.tsx` 移除了 vendored 源码自带的 `shadow` / `shadow-sm` 类。

---

## 4. 动效预算

仅两处，其余一律静态：

- 轨迹条目流入：staggered `animation-delay`，单条 ≤160ms
- 结论卡片出现：一次淡入 + 轻微上移，≤200ms

`prefers-reduced-motion: reduce` 下两者都降为 0.01ms（见 `design-tokens.css` 末尾）。

---

## 5. Token 血统记账

remix recipe 要求给出血统占比。三个口径都列出来，因为它们会得出不同结论——
只报一个数字容易自我欺骗。

| 口径 | A(Linear) | B(Stripe) | 独立 | 说明 |
|---|---|---|---|---|
| **决策层**（8 层仲裁） | 3 层 37.5% | 3 层 37.5% | 2 层 25% | 中性/间距/深度 vs 排版/强调/圆角 |
| **令牌计数**（26 个） | 14 个 54% | 6 个 23% | 6 个 23% | 间距有 7 个令牌，把 A 拉高了 |
| **排除独立层后** | 70% | 30% | — | 同上原因 |

spec §5.3 预估 A≈45% / B≈55%，实际偏向 A。

**偏差原因**：预估是按"视觉印象权重"估的，而实际按令牌数算时，间距体系（7 个令牌，
全部来自 A 的 4px 纪律）在计数上等价于 7 个颜色令牌，但它对视觉印象的贡献远小于
强调色那 1 个令牌。

**结论**：以**决策层口径**（A/B 各 37.5%）为准——它对应 remix recipe 的原意
"逐层仲裁"，且不受某层令牌数量多寡的干扰。视觉上确实是 B 主导（字体和强调色最抢眼），
与预估一致。

---

## 6. 依赖取舍记录

AI Elements 官方给 48 个组件，我们只 vendoring **3 个**（`scripts/vendor_ai_elements.py`）。

| 组件 | 决定 | 原因 |
|---|---|---|
| chain-of-thought | ✅ 留 | 轨迹主体，零重依赖 |
| task | ✅ 留 | 步骤列表，零重依赖 |
| conversation | ✅ 留 | 自动粘底滚动 |
| message / reasoning | ❌ 弃 | 拖入 streamdown 全家桶（mermaid 流程图 + KaTeX 公式），检测报告用不到 |
| reasoning / shimmer | ❌ 弃 | 依赖 `motion`，与禁令 9「禁装饰动效」冲突 |
| tool | ❌ 弃 | props 绑死 AI SDK 的 `ToolUIPart`，与自有 `TraceEvent` 不兼容 |
| image | ❌ 弃 | 渲染 base64 data URL，与「图片落盘只传 URL」架构相反 |
| confirmation | ❌ 弃 | 无用户确认交互场景 |

净增 npm 依赖 4 个（原方案 11 个）：`@radix-ui/react-use-controllable-state`、
`use-stick-to-bottom`、`react-markdown`、`remark-gfm`。

`conversation.tsx` 的 `ConversationDownload`（唯一依赖 AI SDK 的部分）由 vendoring
脚本自动裁掉。**本地补丁写在脚本里而非手改文件**——否则重跑 vendoring 会被上游原文覆盖。
上游若重构掉裁剪锚点，脚本会硬失败而不是静默产出半残文件。
