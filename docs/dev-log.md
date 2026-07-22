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

## Task 11: HiFi-Net 适配器（时间盒 2×2h，2026-07-23）

**结论：此 Mac 上不可行。判定用时约 15-20 分钟（远未用满第一个 2h 时间盒），证据充分、多层独立，提前止损，未死磕。**

### Step 1：安装尝试
- `pip install hifi-ifdl` → `ERROR: No matching distribution found`——确认 调研记录.md 的风险声明成立：PyPI 无包，"2 行代码" 说法只适用于拿到源码之后。
- `git clone https://github.com/CHELSEA234/HiFi_IFDL /tmp/HiFi_IFDL` 成功。阅读 README + 源码后，把这份 clone 完整 vendor 到项目根 `HiFi_IFDL/`（210MB，含 `.git`，同 `TruFor/` 先例——已入 `.gitignore`，不进版本控制）。

### 深挖：3 层独立阻塞（比"权重被墙"更根本，逐条附证据）

**1. 主权重仅有 Google Drive 文件夹链接，无法脚本化下载**
README 给的两个链接：
- 检测+定位权重（"HiFi_IFDL_weights_link"）：`https://drive.google.com/drive/folders/1v07aJ2hKmSmboceVwOhPvjebFMJFHyhm`
- 仅定位场景权重（"localization_weights_link"）：`https://drive.google.com/drive/folders/1cxCoE2hjcDj4lLrJmGEbskzPRJfoDIMJ`

`curl -sI` 两个链接均返回 Google Drive 交互式 JS 应用壳（`content-type: text/html`，`x-robots-tag: noindex`，完整的 Drive 前端资源预加载 HTML），不是文件列表或直链——需要浏览器 + Google 账号 session 才能进入文件夹点击下载，无法 `wget`/`curl` 脚本化，`gdown --folder` 对这类共享文件夹的支持也不稳定（常触发 Google 限流/验证）。文件夹内容大小未知（未登录看不到清单）。仓库自带的 `weights/` 目录只有一个 `put_weights_here` 占位文件；`center/radius_center.pth`（543B）、`center_loc/radius_center.pth`（1063B）是训练时预计算的超球体中心/半径，不是主检测权重。backbone 的 ImageNet 预训练初始化权重 `models/hrnet_w18_small_v2.pth`（16MB）已随源码一起打包在仓库里，**这个不需要单独下载**。

**2. 模型定义层硬编码 CUDA，与权重是否到手无关（本次判定的决定性证据）**
- `models/NLCDetection_api.py:205-206`，`NLCDetection.__init__`（SegNet 本体）：
  ```python
  self.split_tensor_1 = torch.tensor([1, 3]).cuda()
  self.split_tensor_2 = torch.tensor([1, 2, 1, 3]).cuda()
  ```
  Mac 的 torch 是 mps 版本，未编译 CUDA 支持，`.cuda()` 会直接 `AssertionError: Torch not compiled with CUDA enabled`——**这行代码在 `NLCDetection()` 构造时就会跑到，跟有没有权重完全无关**。
- `HiFi_Net.py::HiFi_Net.__init__` 硬编码 `torch.device('cuda:0')` + `nn.DataParallel(FENet)/nn.DataParallel(SegNet)`。
- `utils/utils.py` 模块级 `device = torch.device('cuda:0')`；`restore_weight_helper()` 硬编码 `torch.load(weight_path, map_location='cuda:0')`；`load_center_radius_api()` 用该全局 `device` 做 `.to(device)`。
  **已实测验证**（用仓库自带的小文件，不需要主权重）：
  ```
  torch.load('HiFi_IFDL/center/radius_center.pth')                    → RuntimeError: Attempting to deserialize object on
                                                                          a CUDA device but torch.cuda.is_available() is False...
  torch.load('HiFi_IFDL/center/radius_center.pth', map_location='cpu') → 成功（dict, keys=['center','radius']，tensor 形状 [18]/[]）
  ```
  即：连一个 543B 的小文件都是用 CUDA 张量序列化的，不显式 `map_location='cpu'` remap 就读不出来——这不是"忘记传 device 参数"的小问题，是训练/导出时全程假设 CUDA 环境的产物。
  
  这与 TruFor 的封装方式本质不同：TruFor 的 `get_model(config)` 返回设备无关的 `nn.Module`，设备选择完全在我们自己的 `run_inference.py::select_device()/load_model()` 里做（`model.to(device)`，`device` 可以是 `cuda:0`/`mps`/`cpu`）。HiFi-Net 把 `.cuda()` 写死在模型类定义（`NLCDetection.__init__`）和工具函数（`restore_weight_helper`/`load_center_radius_api`）内部，不 fork 上游源码无法在 MPS/CPU 上运行。判定为 HiFi-Net 自身的内部契约（同坑 #2 免责条款的同类情况：模型自己的强约束，记录清楚即可，不算适配器缺陷）——服务器（16G VRAM，真实 CUDA）天然满足这一契约，Mac 天然不满足，这不是"服务器算力更强"的问题，是"有没有 CUDA"的问题。

  **延伸风险（未验证，标记供服务器侧关注）**：坑 #6 之前在 TruFor 上发现过"旧 checkpoint 需要 `torch.load(..., weights_only=False)`"（`run_inference.py` 已固化此修复）。HiFi-Net 的主权重文件（`weights/HRNet/750001.pth`、`weights/NLCDetection/750001.pth`）用 `restore_weight_helper()` 加载，取的是 `['model']` 键，可能不止包含裸 tensor（训练年代 torch~1.11，无 `weights_only` 概念）。用仓库自带的小 `center/radius_center.pth` 实测，torch 2.12.1 默认 `weights_only=True` 反而**没有**报 weights_only 相关错误（只报 CUDA map_location 错误，说明这个小文件的 pickle 内容在允许列表内）——但主权重文件内容未知，不能类推，服务器侧拿到真实权重后如果 `torch.load` 报 `weights_only`/`UnpicklingError`，按坑 #6 同样加 `weights_only=False` 即可。

**3. 额外依赖，独立于 CUDA/权重问题**
即使只是 `import HiFi_Net`（不触发任何 `.cuda()` 调用），也会经 `HiFi_Net.py` 顶部 `from utils.utils import *` 无条件拉入：`kmeans_pytorch`（PyPI 有，但只发布过 3 个版本 0.1/0.2/0.3，最后一次发布年代久远，Python 3.12 兼容性未知，未安装验证）、`einops`（维护良好，无忧）、`scikit-learn`（`from sklearn import metrics`）、`imageio`。这 4 个都不在项目当前 `requirements.txt` 里；`yacs`（HRNet 配置用）项目已有，无需重装。**本次未安装**——因为即便装上，第 2 点的 CUDA 硬编码依然会让 `HiFi_Net()` 构造失败，装这些依赖对本次判定没有增量信息，属于时间盒范围内应该省略的一步（不为验证不了的路径铺路）。

**4.（次要）环境版本落差**
`environment.yml` 锁定 Python 3.7.16 + PyTorch~1.11 + torchvision 0.12.0 + cudatoolkit 11.3，与项目当前 Python 3.12.13 + torch 2.12.1 相差 4 个大版本以上，存在未知 API 漂移风险（如 `imageio.imread` 顶层调用在 imageio v3 里的变化）。非决定性因素，仅供服务器侧排查参考。

### 输出契约核对（对照 brief 的 DetectorBackend 形状，即便跑不了也要核对清楚）
读源码（`HiFi_Net.py`）确认的真实 API，和 brief 骨架里的占位 API（`hifi_net.HiFi(weights=...)`）不同：
- `score`：`HiFi_Net.detect(path)` 返回 `(res, prob)` 二元组，`res` 是 0/1 决策，`prob` 已经是 `[0,1]` 浮点（README 示例注释 `# print(res3, prob3) 1 1.0`）——取 `prob` 作为 `score`，符合 `0.0~1.0` 契约，不需要额外归一化。
- `map`：`HiFi_Net.localize(path)` 返回**二值 mask**（对超球体距离做 `>=2.3` 硬阈值，`custom_loss.py` 里写死），不是 TruFor 那种连续 softmax 概率图。`ndim==2` 仍满足结构契约，但"热力图"渲染出来是非黑即白的二值分割块，不是渐变置信度——两者的"热力图"视觉语义不同，需要在 UI/话术里讲清楚，避免误以为可以直接比较数值。
- `infer_size`：`_transform_image()` 把任意输入 `resize((256,256), resample=Image.BICUBIC)` 后才送进网络——不是"服务器算力更好就能保留原分辨率"的问题，是模型训练时就固定的输入尺寸（同坑 #2 的另一实例：模型自己的固定预处理契约）。因此 HiFi 的 score/map 证据粒度是"256x256 缩略图级"，比 TruFor 的"原图/切片级"粗得多——这是两个检测器与生俱来的能力差异，不是可调参数。财务单据上的小字/印章细节缩到 256x256 基本丢失，"第二意见"的实际参考价值可能有限，建议 Task 12 QA 时如实说明这个局限，不要只展示分数。

### 已实现（真代码，不是占位符）
`hifi_inference.py` 按上面读源码得到的真实 API 编写（不是 brief 骨架里的占位 `hifi_net`/`HiFi(weights=...)`）：
- `hifi_available()`：分层真实探测——① `hifi_weights/HRNet/750001.pth` + `hifi_weights/NLCDetection/750001.pth` 是否都在（文件名/子目录名抄自上游 `restore_weight_helper()` 的真实调用参数，非猜测）；② `HiFi_IFDL/` 仓库目录是否在；③ `torch.cuda.is_available()`（上游硬编码 CUDA，见上文第 2 点）；④ `importlib.import_module("HiFi_Net")` 是否成功（catch `ImportError`）。任一不满足即返回 `False`，且都是可读的真实原因，不是硬编码。
- `_load()`：chdir 到 `HiFi_IFDL/`（上游 `restore_weight_helper` 用仓库相对路径 `"weights/HRNet"`，同 `run_inference.py::load_model` 对 TruFor 的 chdir 处理方式），把 `hifi_weights/{HRNet,NLCDetection}` 软链到仓库自己的 `weights/{HRNet,NLCDetection}`（桥接"本项目权重统一放 `hifi_weights/`"的约定和上游硬编码相对路径的要求，避免复制权重文件），再 `from HiFi_Net import HiFi_Net; HiFi_Net()`。权重未就绪时提前抛出清晰的 `FileNotFoundError`（而非放任跑到 `.cuda()` 深处炸出难懂的报错，也避免留下悬空软链）。
- `run_hifi()`/`render_hifi_heatmap()`：按真实 API 组装 `{score, map, conf, infer_size}`，`conf` 恒为 `None`（HiFi 无独立置信度图，与 TruFor 不同）。

**已用真实（非 monkeypatch）路径验证过降级行为**：临时设 `config.ENABLE_HIFI="on"`（强制路径，绕过 `hifi_available()`）+ 真实 `FakeCtx(image_path=...)`，`SecondOpinionTool().run()` 返回 `ToolResult(error=True, text="HiFi-Net 调用失败：HiFi-Net 权重未就绪：.../hifi_weights/HRNet/750001.pth ... 需存在（见 docs/dev-log.md Task 11）")`；`os.chdir` 前后 CWD 正确恢复；未在 `HiFi_IFDL/` 里留下悬空软链（首次实现时踩过这个坑，见下方"自查发现并修复"）。

**自查发现并修复**：`_load()` 最初实现里，`_ensure_weights_symlink()` 会在检查权重是否就绪之前就先建软链——权重不在时会在 `HiFi_IFDL/weights/` 下留下指向不存在目标的悬空软链（`HRNet -> hifi_weights/HRNet`，目标不存在）。已修复为：`_load()` 开头先检查 `_weights_ready()`，不满足直接抛 `FileNotFoundError` 并返回，不做任何文件系统改动。

### 服务器接手清单（照此配置，理论上"同一份 `hifi_inference.py` 直接可用"，不需要再读一遍上游源码）
1. **硬件**：需要真实 CUDA GPU（不是"MPS 性能更好"能解决的，见上文第 2 点，模型定义层硬编码 `.cuda()`）。VRAM 估算（**未实测，架构推算**）：backbone 是 HRNet-w18-small（轻量级，16MB checkpoint），固定 256x256 单图输入，模型体量小、输入分辨率低，推理显存占用量级估计在 1-3GB——16G VRAM 应有充足余量，甚至可以和 TruFor 同时常驻（TruFor 才是这台服务器上真正吃显存的那个）。**以实测为准**。
2. **依赖安装**（服务器 venv，不要改本 Mac 的 `requirements.txt`，两边环境已分叉）：
   ```
   pip install kmeans-pytorch einops scikit-learn imageio
   ```
   （PyPI 包名 `kmeans-pytorch`，import 名 `kmeans_pytorch`；`yacs`/`torch`/`torchvision`/`numpy`/`pillow`/`matplotlib` 项目已有同名依赖，无需重装。）
3. **仓库**：`git clone https://github.com/CHELSEA234/HiFi_IFDL HiFi_IFDL`（放项目根目录，已在 `.gitignore`，同 `TruFor/` 先例）。backbone 初始化权重 `models/hrnet_w18_small_v2.pth` 随仓库一起有，不需要单独下载。
4. **主权重**（需要人工登录 Google 账号，浏览器下载，无法脚本化）：
   `https://drive.google.com/drive/folders/1v07aJ2hKmSmboceVwOhPvjebFMJFHyhm`（README "HiFi_IFDL_weights_link"）。
   下载后放到（本适配器统一约定的项目级路径，`_load()` 会自动软链桥接到仓库自己期望的相对路径，不需要手动处理软链）：
   `hifi_weights/HRNet/750001.pth`
   `hifi_weights/NLCDetection/750001.pth`
5. **可能需要的额外修复**：若 `torch.load` 主权重时报 `weights_only`/`UnpicklingError`，按坑 #6 同样在 `utils/utils.py::restore_weight_helper()` 加 `weights_only=False`（本次用小文件实测未触发，但主权重内容未知，不能类推，见上文第 2 点延伸风险）。
6. **验证步骤**：权重+依赖+CUDA 就位后，直接跑：
   ```
   .venv/bin/python -m pytest tests/test_hifi_adapter.py -v      # hifi_available() 应转 True，test_run_hifi_shape 从 skip 转真实执行
   .venv/bin/python -c "import time,hifi_inference as h; t=time.time(); r=h.run_hifi('example-images/check.jpg'); print(r['score'], time.time()-t)"
   ```
   按 brief Step4 判据（单张 ≤60s 且不 OOM）确认后，`.env` 大概率不需要改动（见下方"关于 `.env` 的决定"，`config.py` 默认值 `auto` 配合本次实现的真实探测，届时会自动转为可用）。
7. **产品/评测层面的延伸问题**（不在本次时间盒范围内，供 Task 12 参考）：HiFi 固定 256x256 输入会让财务单据上的小字/印章细节大量丢失，直接整图缩放可能让"第二意见"参考价值有限；是否要在送检前先做关键区域裁剪（复用 `zoom_region` 已有的裁剪逻辑）再单独跑 HiFi，是一个值得评估的产品问题，本次不处理。

### 关于 `.env` 的决定（与 brief 字面不同，记录原因）
brief Step 4 判据"否则 `.env` 写 `DOCGUARD_ENABLE_HIFI=off`"，前提是"已经跑起来但太慢/OOM"的场景。本次实测发现的是更早期的阻塞（权重拿不到 + 模型定义层硬编码 CUDA），`hifi_available()` 已经能在多层（权重文件→仓库目录→CUDA→依赖）如实探测出 `False`，`config.py` 现有默认值 `"auto"` 配合这个真实探测，已经产生正确行为——已验证 `tools.build_registry()` 在此 Mac 上只返回 `['zoom_region']`。

尝试按字面在 `.env` 写入 `DOCGUARD_ENABLE_HIFI=off` 后，发现会导致既有测试 `tests/test_config.py::test_defaults`（断言默认值是 `"auto"`）失败——这条测试保护的是"没人显式设置时应该是 `auto`"这个不变式；写死 `off` 是一个需要人记得以后手动改回来的多余状态，而 `auto` 本身已经能在服务器权重/依赖/CUDA 全部就绪的那一刻自动转为可用，不需要人工干预，且不会破坏既有测试契约。

**最终决定：不修改 `.env`**（保留仅 `DASHSCOPE_API_KEY` 一行）。`.env` 本身在 `.gitignore` 里、不进版本控制，这个决定只影响本机运行时状态，不影响仓库/commit。

### Step 4（Mac 可行性实测）
```
.venv/bin/python -m pytest tests/test_hifi_adapter.py -v
```
→ `test_available_is_bool` PASSED，`test_run_hifi_shape` SKIPPED（`hifi_available()==False`，双轨合法状态，reason: "HiFi-Net 未就绪（合法的双轨状态）"）。未能进行真实单图耗时测量——模型在此 Mac 上无法加载（见上文三层阻塞），这本身就是判定结果，不是判定过程的缺失。

### Step 5（端到端验证，降级分支）
不可用分支——本节即降级记录。`tools.build_registry()` 在此 Mac 上验证只含 `zoom_region`；`SecondOpinionTool` 的降级路径（模块缺失/权重缺失两种真实失败模式）已用真实代码路径验证过（见上文"已用真实路径验证过降级行为"），未额外重跑 `scripts/smoke_agent.py`——Task 4/6/7 已充分覆盖 HiFi 缺失时 agent 不会尝试调用不存在工具的回归行为，此处不需要重复真机冒烟。

### 测试结果
`.venv/bin/python -m pytest tests/ -v` → **39 passed, 1 skipped**（38 条既有 + 2 条新增 `test_hifi_adapter.py`，其中 1 条按设计 skip）。`test_second_opinion_missing_module_wrapped_error`（`sys.modules["hifi_inference"]=None` 回归测试）与 `test_registry_excludes_unavailable` 均保持通过。

### 一句话结论
HiFi-Net 在此 Mac（M3/MPS/CPU）上**不可行**：PyPI 无包（确认风险声明）；主权重仅有 Google Drive 文件夹链接，无法脚本化下载；更根本的是，上游源码在**模型定义层**（`NLCDetection.__init__`、`HiFi_Net.__init__`、`utils/utils.py` 模块级 device）硬编码 CUDA——已用仓库自带小文件实测证实（`torch.load` 不加 `map_location='cpu'` 直接报 CUDA 反序列化错误），这与 TruFor 干净的 device 参数化风格本质不同，即便权重到手也无法在 MPS/CPU 上跑，需要服务器真实 CUDA GPU。`hifi_inference.py` 已按读源码得到的真实 API（而非 brief 骨架的占位 API）完整实现，`hifi_available()` 做真实分层探测（非硬编码 False），已用真实（非 monkeypatch）路径验证过 `ENABLE_HIFI=on` 强制模式下的清晰错误信息与 CWD/文件系统副作用安全；`HiFi_IFDL/` 仓库已 vendor 到项目根（gitignored，同 `TruFor/` 先例）供服务器复用/参考。全测试套件 39 passed, 1 skipped，`build_registry()` 在此 Mac 上正确只含 `zoom_region`。`.env` 未按 brief 字面写 `off`——现有 `auto` 默认值配合本次真实探测已经正确工作，写死 `off` 反而会破坏既有 `test_config.py::test_defaults` 且需要日后手动改回，已在上文详细记录原因。时间盒：预算 2×2h，实际用时约 15-20 分钟即得出充分、多层独立的判定证据，未触发第二个 2h，提前止损。
