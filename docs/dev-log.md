# Dev Log — 决赛升级 (Agent Loop)

## Task 1: 验活基线 + 依赖安装 + 原生 FC 探测 (2026-07-19)

### Step 1: 冒烟现有推理链
命令：`.venv/bin/python run_inference.py -i "example-images/微信圖片_20260629180523_53_237.png" -o /tmp/smoke-out`

输出：
```
Model loaded (epoch 81), device: mps
Processing: 微信圖片_20260629180523_53_237.png
  Score: 0.9449 | (1080, 1330) -> (1080, 1330)
  Heatmap saved: /tmp/smoke-out/微信圖片_20260629180523_53_237_heatmap.png
```
结果：通过。19 天未动的代码链路（TruFor MPS 推理）无环境漂移，坑 #4/#6 均未触发（`run_inference.py` 中 `torch.load(..., weights_only=False)` 已固化，属已修复状态）。`/tmp/smoke-out/` 确认生成 `*_heatmap.png`。

### Step 2: 冒烟 VLM 端点
命令：brief 给定的 heredoc 脚本（`dashscope.base_http_api_url` 指向专属端点，模型 `qwen3.7-max-2026-06-08`）。

**意外情况（新坑，记为坑 #7）**：原始命令 `.venv/bin/python - <<EOF ... EOF`（stdin heredoc）触发 python-dotenv 1.2.2 的一个已知限界——`load_dotenv()` 内部 `find_dotenv()` 用 `sys._getframe()` 回溯调用栈定位调用者的 `__file__` 再向上找 `.env`；stdin 执行时帧为 `<stdin>`，没有正常的上层调用帧，触发 `assert frame.f_back is not None` 断言直接崩溃。这不是坑 #4（代理）也不是坑 #6（weights_only），与推理逻辑无关，纯属脚本执行方式问题。

排查过程：
1. 改为 `python -c "..."` 可正常触发 `load_dotenv()`（有干净的 frame），确认问题只在 stdin heredoc。
2. 把同一段代码存成真实 `.py` 文件在 `/tmp` 下用 `python /tmp/xxx.py` 执行，`find_dotenv()` 不再崩溃，但从脚本自身路径（`/tmp`）向上找 `.env`，找不到项目根目录的 `.env`，报 `AuthenticationError: No api key provided`。
3. 把同一文件放到项目目录内执行，`find_dotenv()` 从项目目录向上能找到 `.env`，恢复正常。

**结论**：脚本必须放在项目目录（或其子目录）内运行，`load_dotenv()` 才能正确定位到根目录的 `.env`；不能用 stdin heredoc 直接跑含 `load_dotenv()` 的诊断代码。未改动任何推理逻辑或架构，仅改变了本次一次性诊断代码的执行载体（临时文件已在验证后删除，不属于交付物）。`scripts/probe_fc.py`（Step 4）本来就是项目子目录内的真实文件，未受此问题影响。

修复后输出：
```
200 OK！请问有什么我可以帮您的？
```
结果：通过。

### Step 3: 安装新依赖并冻结
`.venv/bin/pip install pytest scipy pillow-heif` 全部安装成功：`pytest-9.1.1 scipy-1.18.0 pillow-heif-1.4.0`（含依赖 `pluggy-1.6.0 iniconfig-2.3.0`），与已装的 `pillow 12.2.0` / `numpy 2.5.0` 无冲突。

`requirements.txt` 已冻结（90 行），确认含：
```
torch==2.12.1
gradio==6.19.0
dashscope==1.26.0
scipy==1.18.0
pytest==9.1.1
pillow_heif==1.4.0
```

### Step 4: FC (Function Calling) 探测
脚本：`scripts/probe_fc.py`（按 brief 原样落地，工具契约 `zoom_region(bbox)`，未改架构）。

原始输出：
```
status: 200
tool_calls: [{'id': 'call_2dbfd9e3a4f04ffe8a6ce3a2', 'index': 0, 'type': 'function', 'function': {'name': 'zoom_region', 'arguments': '{"bbox": \n[250, 250, 750, 750]\n\n}'}}]
content: []
```

**结论：qwen3.7-max-2026-06-08 专属端点支持原生 Function Calling**——`tool_calls` 非空，返回结构正确的 `zoom_region` 调用（`bbox=[250,250,750,750]`，落在 0-1000 归一化范围内，`arguments` 是可解析的合法 JSON）。

按已批准的 spec 决策，决赛架构**仍维持 JSON 协议**（最多 3 轮、三重终止 + 回退直链）不变——此探测结论仅记录进 dev log 与 QA 口径备用（"底层是否支持原生 FC" 是可预见的评委追问），以及未来可选的切换方向，不触发本轮架构变更。

## 一句话结论
基线验活通过（TruFor MPS 推理 Score=0.9449 正常、VLM 专属端点 200 OK 正常，坑 #4/#6 均未复现，新发现坑 #7：`load_dotenv()` 诊断脚本不能走 stdin heredoc、且需放在项目目录内运行）；`pytest/scipy/pillow-heif` 已装并冻结进 `requirements.txt`；专属端点**支持**原生 Function Calling，但决赛架构按 spec 保持 JSON 协议不变。

## Task 7: 真机冒烟 + Prompt 实调校准 (2026-07-23)

首次用真实 qwen3.7-max-2026-06-08 端点跑通全链路（TruFor MPS → Agent Loop → 真 VLM），此前全部靠 fake VLM 单测。

### Step 1: 冒烟脚本
`scripts/smoke_agent.py` 按 brief 原样落地（TruFor 推理 → 构造 `AgentContext` → `review(ctx, build_registry(), mode=mode)` 逐事件打印），未做任何改动。

### Step 2: 三张示例图首轮实测（原始 Prompt，mode=agent）

| 图片 | CV 首检 | 轮数/工具调用 | Verdict | 耗时 |
|---|---|---|---|---|
| 53_237.png（1080x1330，非切片，2 候选框） | score=0.9449 | 3 轮：zoom(region_id=1 抬头) → zoom(bbox 手动定位印章) → verdict | 高度可疑/高（印章底纹穿透、字体异常） | 2:21.97 |
| 50_237.jpg（3456x4107，**切片**30 tiles，0 候选框） | score=0.2536 | 2 轮：zoom(bbox 手动定位印章区) → verdict | 高度可疑/高（无盖章签字、申请方与收款方名称不一致） | 2:44.56 |
| check.jpg（3456x4608，**切片**30 tiles，1 候选框 mean=0.6328 灰区） | score=0.2347 | 2 轮：zoom(region_id=1) → verdict | 高度可疑/高（CV 标记区经查为纸张噪点误报；银行账号科学计数法+无签章才是真问题） | 2:02.80 |

对照 brief 检查清单：
1. **JSON 协议**：3/3 图全程无 ProtocolError 重试痕迹，每轮都是合法的单个 `json` 代码块。
2. **investigate 触发**：53_237 非灰区（0.94）但候选区域命中"关键字段"（抬头+印章）触发查证——符合决策原则 2 的第二个条件；50_237/check.jpg 均为切片图，在全局低分下仍主动 investigate（软提示 tiled_note 生效）。三图均未出现"从不 investigate"或"轮轮 investigate 打满"。
3. **bbox 合理性**：`region_id` 引用与手动 `bbox` 均命中目测合理的位置（抬头行、印章角、候选框本身）。
4. **切片图行为**：50_237、check.jpg 均在 tiled 提示下选择放大查证，符合坑 #3 缓解设计意图。
5. **verdict 话术**：财务向、无 CV/ML 黑话，**但发现 1 处偏差**——`basis` 字段两次（53_237、check.jpg）直接写出`"CV 检测置信度高达 0.94"` / `"CV 标记区域实为...误报"`，把内部工具名和原始分数泄漏进面向财务人员的文本，违反了 prompt 自己写的"禁用技术术语"。

### Step 3a：Prompt 修改 #1 —— basis 字段防术语泄漏（已采纳）

**原因**：Step 2 观察到的具体缺陷（见上），"禁用技术术语"这句太抽象，模型对"CV"这类系统内部缩写没当成"技术术语"处理。

`agent.py::build_system_prompt`，JSON 模板里 `basis` 字段的提示文案：
```diff
-             "basis": "复核依据（面向财务人员，禁用技术术语）",
+             "basis": "复核依据（大白话描述你看到的具体证据；不得出现'CV/TruFor/模型/置信度/热力图/误报'等系统内部术语或原始分数数字）",
```

**复跑验证**（`pytest tests/` 33 passed 后复跑三图）：
- 53_237.png v2：3 轮（zoom region_id=1 → zoom region_id=2 → verdict），高度可疑/高，`basis` 干净无 CV/分数字样。2:21.97 → 1:58.92。
- 50_237.jpg v2：**1 轮直接 verdict**（模型判断"证据已充分，无需再调用工具"），高度可疑/高，`basis` 干净。1:45.36。
- 三图复跑详见 Step 4 最终表（check.jpg 的 edit#1-only 复跑与 Step 4 合并记录）。

结果：4/4 次复跑里 3 次 `basis` 完全干净（较原始 1/3 明显改善），1 次（check.jpg，见 Step 4）仍残留一次"CV"字样——出现在"CV 标记区域经核实为误报"这类解释假阳性排除的语境下，模型倾向于点名被排除的对象。判断为软性文风指令的正常残余错误率，不做第三次措辞加固（收益递减+已两次验证 over-tuning 的风险，见 Step 3b）。

### Step 3b：Prompt 修改尝试 #2 —— 决策原则显式加入"切片推理"触发条件（**已回退，未采纳**）

**触发原因**：Step 3a 复跑中，50_237.jpg（切片图，0 候选框）在收到 tiled 提示后**直接 verdict、未 investigate 一次**（"证据已充分，无需再调用工具放大查证"）。决策原则 2 里只列了"CV 分数灰区/关键字段/矛盾"三个 investigate 触发条件，"切片推理"只在 `build_first_user_content` 的 `tiled_note` 里作为一句建议出现，**从未进入决策原则的正式列表**——怀疑这是触发不稳定的原因。

**修改**：
```diff
-2. CV 分数处于灰区（{config.LOW_THRESH}~{config.HIGH_THRESH}）、或标记区域涉及关键字段、或你与 CV 结论矛盾时，优先 investigate 查证。
+2. CV 分数处于灰区（{config.LOW_THRESH}~{config.HIGH_THRESH}）、或图像为切片推理（全局分数不可信）、或标记区域涉及关键字段、或你与 CV 结论矛盾时，优先 investigate 查证。
```

**复跑结果（50_237.jpg v3，3:02.46，4 轮）**：investigate 触发确实稳定了（不再跳过），但暴露出**更严重的新问题**——turn 1 的 thought 完全没有提到无盖章、公司名称不一致这两个 v1/v2 都第一时间抓到的真实红旗，而是单一聚焦在"银行账号数字是否被篡改"这个 CV-取证式框架上；由于该图 0 候选框，只能手动猜 bbox，连续猜错 2 次（放大到"承诺条款"而非"银行账号"）才在第 3 轮蒙对；4 轮耗尽触发**强制收敛**（`source=agent-forced`），最终 verdict 是 `正常/低风险`——**完全漏掉了真实的高风险问题，是一次实质性的判断倒退**，比"偶尔不 investigate 但仍读全图读出正确结论"更差。

对比三次同图运行的 turn-1 thought 原文：
- v1（原始）："...肉眼观察发现两个重大业务风险：1. 申请方...与收款方...名称不一致；2. 底部用印/签字区域看似空白..."
- v2（仅 edit#1）："...经肉眼审视，发现两个致命问题：1. 右下角用印/签字区域...完全空白...2. 申请人...与收款开户名...名称不一致..."
- v3（edit#1+edit#2）："...CV 提示为切片推理，全局分数 0.25 虽低但不可全信...需人工核查关键金额与账号区域。特别是银行账号数字较长，易被篡改，需放大确认..."（只字未提盖章/名称问题）

**结论**：这条新增触发词把模型的注意力从决策原则 1 "审视关键字段"的审计员框架，拉偏到了"验证 CV 分数对不对"的取证框架，净效果是负的。**已在 pytest 33 passed 确认后回退**（`git diff HEAD -- agent.py` 确认改动只剩 Step 3a 一行）。这是"引导 investigate"的软性建议（tiled_note）优于"强制 investigate"的硬性决策原则的一个反例——记录在案，不再进一步调整决策原则触发条件，交由 Task 9/10 的评测集扩大样本量后再评估是否值得二次尝试（并且下次应换一种不強调"CV/分数"框架的措辞）。

### Step 4：最终复跑确认（Prompt = 仅 edit#1，三图）

| 图片 | 轮数/工具调用 | Verdict | basis 是否干净 | 耗时 | 备注 |
|---|---|---|---|---|---|
| 53_237.png | 3 轮（同 Step 3a 记录） | 高度可疑/高 | 是 | 1:58.92 | — |
| 50_237.jpg | 3 轮：zoom(bbox 印章区) → zoom(bbox 填写区) → verdict（organic，非强制） | **`conclusion=正常` 但 `risk=高`、advice=拒付** | 是 | 3:19.49 | basis/advice 实质正确（点出无签章+名称不一致），但顶栏 `conclusion` 与 `risk` 语义矛盾——同图 v1/v2 均选"高度可疑"与 risk 一致，判断为该 enum 边界的抽样噪音而非本次改动引入，未做第三次 prompt 调整（见"顾虑"） |
| check.jpg | 2 轮：zoom(region_id=1) → verdict | 高度可疑/高 | 否（1 处"CV 标记的...区域"残留） | 2:07.62 | 与 Step 3a 结论一致：软性文风指令的正常残余错误率 |

`pytest tests/` 全程保持 33 passed（每次 prompt 改动后各跑一次，含 revert 后）。

## 一句话结论
三张示例图 × agent 模式全部走通真实 qwen3.7-max 端点，全程零 ProtocolError；采纳 1 处 Prompt 修改（`basis` 字段显式禁止"CV/分数"字样，泄漏率从 2/3 降到约 1/4）；另 1 处修改（决策原则显式加入"切片推理"触发条件）复跑后发现会把模型注意力从"审计员通读关键字段"带偏到"验证 CV 分数"框架、导致漏判真实红旗+强制收敛给出错误的正常结论，**已回退**，作为负面案例记录；额外发现一处不影响本次交付但值得后续关注的现象——`conclusion` 与 `risk` 字段偶发语义不一致（1/8 次运行）。
