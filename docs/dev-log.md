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
