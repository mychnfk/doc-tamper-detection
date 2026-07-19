# DocGuard 决赛升级（Agent Loop + 打磨 + 技术深度）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Agent 直链升级为 VLM 自主决策的真 Agent Loop（区域放大 + HiFi-Net 双工具、动态注册），配套三栏流式轨迹 UI、自建评测集与阈值校准、QA 预案，全程 Mac MPS 保底双轨。

**Architecture:** TruFor 首检产出 score/热力图/候选框 → agent.py 的 `review()` 生成器驱动最多 3 轮 JSON 协议 Loop（zoom_region / second_opinion 工具），yield TraceEvent 事件流 → app.py（Gradio Chatbot 流式渲染）与 evaluate.py（批量评测）消费同一事件流。三级降级：Agent → 直链 → CV-only。

**Tech Stack:** Python 3.12（`.venv`）、PyTorch 2.12.1（MPS/CUDA 自适应）、Gradio 6.19、DashScope qwen3.7-max 专属端点、scipy（连通域）、pytest。

## Global Constraints

- 一切命令用项目 venv：`.venv/bin/python` / `.venv/bin/pip`（工作目录 `~/Desktop/doc-tamper-detection`）。
- **坑 #2 铁律**：送入 TruFor/HiFi 检测器的图像绝不缩放；zoom 裁片仅送 VLM，从原始文件全分辨率裁取，仅当长边 >2048 时降到 2048（VLM 输入安全上限，非取证输入）。
- **坑 #4**：dashscope SDK 直连，不走 httpx/代理。
- **坑 #6**：`torch.load(..., weights_only=False)`。
- MPS 推理后调用 `torch.mps.empty_cache()`（现有代码已有，勿删）。
- VLM 端点/模型名只从 `config.py` 读：`VLM_MODEL="qwen3.7-max-2026-06-08"`，`VLM_BASE_URL="https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1"`。
- Loop 上限 `AGENT_MAX_TURNS=3`；JSON 连续解析失败 2 次回退直链；直链失败落 CV-only。
- 依赖方向：`app.py / evaluate.py → agent.py + tools.py + regions.py → config.py`；agent.py 不 import tools.py（注册表由调用方传入）；hifi_inference 仅被 tools.py 惰性 import。
- UI 文案面向财务人员（中文、无技术术语）；代码注释简洁。
- 现有 `run_inference.py` 的推理逻辑不动，只允许把 max_size 默认值接到 config。
- 每个 Task 结束必须 commit；commit message 用现有风格（`feat:`/`fix:`/`docs:` + 中文），结尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 环境变量统一 `DOCGUARD_` 前缀（`DASHSCOPE_API_KEY` 除外，已存在于 `.env`）。

---

### Task 1: 验活基线 + 依赖安装 + 原生 FC 探测

19 天未动的代码先确认能跑，再装新依赖并冻结 requirements，最后探测专属端点是否支持原生 function calling（结果只记录进 dev log 与 QA 口径，实现仍走 JSON 协议）。

**Files:**
- Create: `requirements.txt`, `scripts/probe_fc.py`, `docs/dev-log.md`
- Test: 手工冒烟（本 Task 无单测）

**Interfaces:**
- Consumes: 现有 `run_inference.py`、`app.py`、`.env`（DASHSCOPE_API_KEY）
- Produces: 可用的 venv（新增 pytest/scipy/pillow-heif）；`docs/dev-log.md` 中的 FC 探测结论

- [ ] **Step 1: 冒烟现有推理链**

```bash
cd ~/Desktop/doc-tamper-detection
.venv/bin/python run_inference.py -i "example-images/微信圖片_20260629180523_53_237.png" -o /tmp/smoke-out
```
Expected: 打印 `Model loaded (epoch ...)` 与 `Score: 0.xxxx`，`/tmp/smoke-out/` 生成 `*_heatmap.png`。失败则先修复再继续（大概率是环境漂移，对照记忆中坑 #4/#6）。

- [ ] **Step 2: 冒烟 VLM 端点**

```bash
.venv/bin/python - <<'EOF'
import os
from dotenv import load_dotenv; load_dotenv()
import dashscope
dashscope.base_http_api_url = "https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1"
r = dashscope.MultiModalConversation.call(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    model="qwen3.7-max-2026-06-08",
    messages=[{"role": "user", "content": [{"text": "回复：OK"}]}])
print(r.status_code, r.output.choices[0].message.content[0]["text"] if r.status_code == 200 else r.message)
EOF
```
Expected: `200 OK...`。403/超时 → 检查 key 与代理（坑 #4）。

- [ ] **Step 3: 安装新依赖并冻结**

```bash
.venv/bin/pip install pytest scipy pillow-heif
.venv/bin/pip freeze > requirements.txt
```
Expected: 安装成功；`requirements.txt` 含 torch/gradio/dashscope/scipy/pytest/pillow-heif。

- [ ] **Step 4: 写并运行 FC 探测脚本**

```python
# scripts/probe_fc.py — 探测专属端点是否支持原生 function calling（结果仅记录，不改架构）
import os
from dotenv import load_dotenv
load_dotenv()
import dashscope
dashscope.base_http_api_url = "https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1"

TOOLS = [{"type": "function", "function": {
    "name": "zoom_region",
    "description": "放大查看图片指定区域",
    "parameters": {"type": "object", "properties": {
        "bbox": {"type": "array", "items": {"type": "integer"},
                 "description": "[x1,y1,x2,y2] 0-1000 归一化坐标"}},
        "required": ["bbox"]}}}]

r = dashscope.MultiModalConversation.call(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    model="qwen3.7-max-2026-06-08",
    messages=[{"role": "user", "content": [{"text": "请调用工具放大图片中央区域"}]}],
    tools=TOOLS)
print("status:", r.status_code)
if r.status_code == 200:
    msg = r.output.choices[0].message
    print("tool_calls:", getattr(msg, "tool_calls", None))
    print("content:", msg.content)
else:
    print("error:", r.code, r.message)
```

```bash
.venv/bin/python scripts/probe_fc.py
```
Expected: 任一结果都可接受——`tool_calls` 非空 = 端点支持原生 FC（记录：后续可选切换）；报错/忽略 tools = 不支持（记录：JSON 协议为唯一路径）。

- [ ] **Step 5: 记录 dev log 并 commit**

`docs/dev-log.md` 新建，记录：验活结果、FC 探测输出原文、结论一句话。

```bash
git add requirements.txt scripts/probe_fc.py docs/dev-log.md
git commit -m "chore: 决赛升级基线——验活+依赖冻结+原生FC探测

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: config.py 双轨开关中心

**Files:**
- Create: `config.py`, `conftest.py`（空文件，令仓库根可被 pytest import）, `tests/test_config.py`
- Modify: `run_inference.py:202`（argparse 的 `--max-size` 默认值接 config）

**Interfaces:**
- Consumes: `.env` / 环境变量
- Produces: 模块级常量 `DEVICE_OVERRIDE:str, MAX_SIZE:int, AGENT_MAX_TURNS:int, ENABLE_HIFI:str("auto"|"on"|"off"), LOW_THRESH:float, HIGH_THRESH:float, VLM_MODEL:str, VLM_BASE_URL:str`——后续所有 Task 从 `config` 读这些名字

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
import importlib
import config


def test_defaults():
    assert config.MAX_SIZE == 1792
    assert config.AGENT_MAX_TURNS == 3
    assert config.ENABLE_HIFI == "auto"
    assert 0 < config.LOW_THRESH < config.HIGH_THRESH < 1


def test_env_override(monkeypatch):
    monkeypatch.setenv("DOCGUARD_MAX_SIZE", "2560")
    monkeypatch.setenv("DOCGUARD_ENABLE_HIFI", "on")
    importlib.reload(config)
    assert config.MAX_SIZE == 2560
    assert config.ENABLE_HIFI == "on"
    monkeypatch.delenv("DOCGUARD_MAX_SIZE")
    monkeypatch.delenv("DOCGUARD_ENABLE_HIFI")
    importlib.reload(config)
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_config.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: 实现 config.py（+ 空 conftest.py）**

```python
# config.py — 双轨开关中心：Mac/服务器差异只体现为这里的环境变量
import os
from dotenv import load_dotenv

load_dotenv()

DEVICE_OVERRIDE = os.getenv("DOCGUARD_DEVICE", "")          # "" = 自动选择 cuda>mps>cpu
MAX_SIZE = int(os.getenv("DOCGUARD_MAX_SIZE", "1792"))      # 服务器到位后提档 2560-3072
AGENT_MAX_TURNS = int(os.getenv("DOCGUARD_MAX_TURNS", "3"))
ENABLE_HIFI = os.getenv("DOCGUARD_ENABLE_HIFI", "auto")     # auto|on|off
LOW_THRESH = float(os.getenv("DOCGUARD_LOW_THRESH", "0.4"))   # 评测校准后回写 .env
HIGH_THRESH = float(os.getenv("DOCGUARD_HIGH_THRESH", "0.7"))
VLM_MODEL = os.getenv("DOCGUARD_VLM_MODEL", "qwen3.7-max-2026-06-08")
VLM_BASE_URL = os.getenv("DOCGUARD_VLM_BASE_URL",
                         "https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1")
```

- [ ] **Step 4: 接线 run_inference.py**

`run_inference.py` 顶部（`TRUFOR_ROOT` 定义之后）加 `import config`；argparse 行改为：

```python
    parser.add_argument('--max-size', type=int, default=config.MAX_SIZE, help='max dimension before tiled inference')
```

并将 `select_device()` 开头加设备覆盖（服务器双轨用）：

```python
def select_device():
    if config.DEVICE_OVERRIDE:
        return config.DEVICE_OVERRIDE
    if torch.cuda.is_available():
        return 'cuda:0'
    elif torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'
```

- [ ] **Step 5: 运行测试通过并 commit**

```bash
.venv/bin/python -m pytest tests/test_config.py -v
```
Expected: 2 passed

```bash
git add config.py conftest.py tests/test_config.py run_inference.py
git commit -m "feat: config.py 双轨开关中心 + 设备/max_size 接线

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: regions.py 可疑区域候选框提取

TruFor `loc_map` → 阈值化 → scipy 连通域 → top-K 候选框（0-1000 归一化），供 VLM 编号引用（bbox 画偏的兜底）。

**Files:**
- Create: `regions.py`, `tests/test_regions.py`

**Interfaces:**
- Consumes: `loc_map: np.ndarray (H,W) float 0-1`
- Produces: `extract_candidate_regions(loc_map, thresh=0.5, top_k=5, min_area_frac=0.0005) -> list[dict]`，每项 `{"id":int(从1), "bbox":[x1,y1,x2,y2] int 0-1000, "area_frac":float, "mean_score":float}`，按 mean_score 降序

- [ ] **Step 1: 写失败测试**

```python
# tests/test_regions.py
import numpy as np
from regions import extract_candidate_regions


def _map_with_blocks():
    m = np.zeros((200, 400), dtype=np.float32)
    m[20:60, 40:120] = 0.9    # 大块高分
    m[150:170, 300:340] = 0.6  # 小块中分
    m[0:2, 0:2] = 0.8          # 面积过滤应剔除 (4/80000 < 0.0005×... 视阈值)
    return m


def test_extract_basic():
    regs = extract_candidate_regions(_map_with_blocks(), thresh=0.5, top_k=5, min_area_frac=0.001)
    assert len(regs) == 2
    assert regs[0]["mean_score"] > regs[1]["mean_score"]          # 降序
    assert regs[0]["id"] == 1 and regs[1]["id"] == 2
    x1, y1, x2, y2 = regs[0]["bbox"]
    assert 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000
    assert abs(x1 - 100) <= 15 and abs(x2 - 300) <= 15            # 40/400,120/400 → 100,300


def test_empty_map():
    assert extract_candidate_regions(np.zeros((100, 100), dtype=np.float32)) == []


def test_top_k():
    m = np.zeros((100, 1000), dtype=np.float32)
    for i in range(8):
        m[10:40, i * 120 + 10: i * 120 + 60] = 0.5 + i * 0.05
    regs = extract_candidate_regions(m, thresh=0.4, top_k=3, min_area_frac=0.0001)
    assert len(regs) == 3
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_regions.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'regions'`

- [ ] **Step 3: 实现 regions.py**

```python
# regions.py — loc_map → 连通域 → top-K 候选框（0-1000 归一化，供 VLM 编号引用）
import numpy as np
from scipy import ndimage


def extract_candidate_regions(loc_map, thresh=0.5, top_k=5, min_area_frac=0.0005):
    h, w = loc_map.shape
    mask = loc_map >= thresh
    labeled, n = ndimage.label(mask)
    if n == 0:
        return []

    regions = []
    for i in range(1, n + 1):
        area = int((labeled == i).sum())
        if area / (h * w) < min_area_frac:
            continue
        ys, xs = np.where(labeled == i)
        regions.append({
            "bbox": [int(xs.min() / w * 1000), int(ys.min() / h * 1000),
                     int((xs.max() + 1) / w * 1000), int((ys.max() + 1) / h * 1000)],
            "area_frac": round(area / (h * w), 4),
            "mean_score": round(float(loc_map[labeled == i].mean()), 4),
        })

    regions.sort(key=lambda r: r["mean_score"], reverse=True)
    regions = regions[:top_k]
    for idx, r in enumerate(regions):
        r["id"] = idx + 1
    return regions
```

- [ ] **Step 4: 运行测试通过**

```bash
.venv/bin/python -m pytest tests/test_regions.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add regions.py tests/test_regions.py
git commit -m "feat: 可疑区域候选框提取（连通域 top-K，0-1000 归一化）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: tools.py — Tool 契约 + zoom_region + 动态注册表

**Files:**
- Create: `tools.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: `config.ENABLE_HIFI`；ctx 鸭子类型（需属性 `original_img: PIL.Image`, `candidates: list[dict]`, `image_path: str`）——由 Task 5 的 `AgentContext` 满足
- Produces:
  - `@dataclass ToolResult(text: str, images: list = [], error: bool = False)`
  - `class Tool: name, description, args_hint, available() -> bool, run(ctx, **kwargs) -> ToolResult`
  - `class ZoomRegionTool(Tool)`：`run(ctx, region_id=None, bbox=None)`
  - `class SecondOpinionTool(Tool)`：`run(ctx)`（惰性 import hifi_inference；Task 11 前 `available()` 恒 False）
  - `build_registry() -> list[Tool]`（仅返回 available 的工具）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools.py
from dataclasses import dataclass, field
from PIL import Image
from tools import ToolResult, ZoomRegionTool, SecondOpinionTool, build_registry


@dataclass
class FakeCtx:
    original_img: Image.Image
    candidates: list = field(default_factory=list)
    image_path: str = "/tmp/fake.png"


def _ctx(w=2000, h=1000):
    return FakeCtx(original_img=Image.new("RGB", (w, h), "white"))


def test_zoom_by_bbox_full_res():
    tool = ZoomRegionTool()
    r = tool.run(_ctx(), bbox=[100, 100, 300, 400])   # 0-1000 → 像素 200,100..600,400
    assert not r.error and len(r.images) == 1
    crop = r.images[0]
    # 8% padding：宽 400px*1.16≈464，允许 ±10
    assert abs(crop.width - 464) <= 10
    assert "放大" in r.text


def test_zoom_by_region_id():
    ctx = _ctx()
    ctx.candidates = [{"id": 1, "bbox": [500, 500, 700, 700], "area_frac": 0.01, "mean_score": 0.8}]
    r = ZoomRegionTool().run(ctx, region_id=1)
    assert not r.error and len(r.images) == 1


def test_zoom_bad_args():
    r = ZoomRegionTool().run(_ctx())                  # 无 bbox 无 region_id
    assert r.error
    r2 = ZoomRegionTool().run(_ctx(), region_id=99)   # 不存在的编号
    assert r2.error


def test_zoom_caps_at_2048():
    ctx = _ctx(w=8000, h=8000)
    r = ZoomRegionTool().run(ctx, bbox=[0, 0, 1000, 1000])
    assert max(r.images[0].size) <= 2048              # VLM 输入上限，非取证输入


def test_registry_excludes_unavailable(monkeypatch):
    monkeypatch.setattr(SecondOpinionTool, "available", lambda self: False)
    names = [t.name for t in build_registry()]
    assert "zoom_region" in names and "second_opinion" not in names
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_tools.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: 实现 tools.py**

```python
# tools.py — Agent 工具契约与注册表：工具箱随环境伸缩，协议不变
from dataclasses import dataclass, field

import config


@dataclass
class ToolResult:
    text: str
    images: list = field(default_factory=list)   # list[PIL.Image]
    error: bool = False


class Tool:
    name = ""
    description = ""      # 写给 VLM 的用途说明
    args_hint = ""        # 写给 VLM 的参数说明

    def available(self):
        return True

    def run(self, ctx, **kwargs):
        raise NotImplementedError


class ZoomRegionTool(Tool):
    name = "zoom_region"
    description = "从原始文件按全分辨率裁出指定区域的高清图，用于细看笔画边缘、字体质感、印章纹理"
    args_hint = '{"region_id": 候选区域编号} 或 {"bbox": [x1,y1,x2,y2] 0-1000归一化坐标}'

    PAD = 0.08          # 每边 8% 上下文余量
    VLM_MAX = 2048      # 仅约束送 VLM 的裁片，与取证无关

    def run(self, ctx, region_id=None, bbox=None):
        if region_id is not None:
            hit = [c for c in ctx.candidates if c["id"] == region_id]
            if not hit:
                return ToolResult(text=f"候选区域编号 {region_id} 不存在", error=True)
            bbox = hit[0]["bbox"]
        if not bbox or len(bbox) != 4:
            return ToolResult(text="缺少有效的 region_id 或 bbox 参数", error=True)

        img = ctx.original_img
        w, h = img.size
        x1, y1, x2, y2 = [v / 1000 for v in bbox]
        pw, ph = (x2 - x1) * self.PAD, (y2 - y1) * self.PAD
        px1 = max(0, int((x1 - pw) * w)); py1 = max(0, int((y1 - ph) * h))
        px2 = min(w, int((x2 + pw) * w)); py2 = min(h, int((y2 + ph) * h))
        if px2 - px1 < 8 or py2 - py1 < 8:
            return ToolResult(text="区域过小，无法放大", error=True)

        crop = img.crop((px1, py1, px2, py2))
        if max(crop.size) > self.VLM_MAX:
            crop.thumbnail((self.VLM_MAX, self.VLM_MAX))
        return ToolResult(
            text=f"已放大区域 bbox={bbox}（原图像素 {px2-px1}x{py2-py1}），请细看该高清片",
            images=[crop])


class SecondOpinionTool(Tool):
    name = "second_opinion"
    description = "调用第二个独立 CV 检测模型（HiFi-Net）对全图做交叉验证，返回其分数与热力图"
    args_hint = "{}（无参数）"

    def available(self):
        if config.ENABLE_HIFI == "off":
            return False
        try:
            import hifi_inference
            ok = hifi_inference.hifi_available()
        except ImportError:
            ok = False
        return ok if config.ENABLE_HIFI == "auto" else True

    def run(self, ctx, **kwargs):
        import hifi_inference
        try:
            result = hifi_inference.run_hifi(ctx.image_path)
            heat = hifi_inference.render_hifi_heatmap(result)
            return ToolResult(
                text=f"HiFi-Net 独立检测分数：{result['score']:.4f}（0=正常 1=篡改），热力图见图",
                images=[heat])
        except Exception as e:
            return ToolResult(text=f"HiFi-Net 调用失败：{e}", error=True)


def build_registry():
    return [t for t in (ZoomRegionTool(), SecondOpinionTool()) if t.available()]
```

- [ ] **Step 4: 运行测试通过**

```bash
.venv/bin/python -m pytest tests/test_tools.py -v
```
Expected: 5 passed（此阶段 hifi_inference 不存在 → SecondOpinionTool 经 ImportError 自然不可用，正是动态注册的设计行为）

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools.py
git commit -m "feat: Tool 契约 + zoom_region 全分辨率裁片 + 动态注册表

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: agent.py（一）协议层——事件/上下文/解析/Prompt/VLM 封装 + 直链迁移

**Files:**
- Create: `agent.py`, `tests/test_agent_protocol.py`
- Modify: 无（app.py 的直链代码此 Task 只是"复制迁移"进 agent.py，app.py 本体到 Task 8 才改）

**Interfaces:**
- Consumes: `config.*`；`tools.ToolResult` 形状（仅鸭子使用 `.text/.images/.error`，不 import tools）
- Produces（Task 6/7/8/10 依赖的确切名字）:
  - `@dataclass TraceEvent(turn: int, type: str, payload: dict)`，type ∈ `"stage"|"thought"|"tool_call"|"tool_result"|"verdict"|"fallback"`
  - `@dataclass AgentContext(image_path: str, original_img, heatmap_img, score: float, infer_size: str, tiled: bool, candidates: list)`
  - `class ProtocolError(Exception)`
  - `call_vlm(messages: list) -> str`（dashscope 封装，非 200 抛 RuntimeError）
  - `parse_turn(raw: str) -> dict`（校验 decision 字段，失败抛 ProtocolError）
  - `build_system_prompt(tools: list) -> str`、`build_first_user_content(ctx) -> list`、`tool_result_content(name: str, tr) -> list`
  - `format_verdict(v: dict) -> str`（结构化 verdict → 财务话术 markdown）
  - `image_to_base64(img) -> str`、`direct_review(ctx) -> str`（原 app.py `vlm_review` 迁移版）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agent_protocol.py
import pytest
from agent import parse_turn, ProtocolError, build_system_prompt, format_verdict


class FakeTool:
    name = "zoom_region"
    description = "放大"
    args_hint = "{...}"


def test_parse_valid_investigate():
    raw = '前置解释文字\n```json\n{"thought":"分数灰区","decision":"investigate",' \
          '"action":{"tool":"zoom_region","args":{"region_id":1}}}\n```'
    d = parse_turn(raw)
    assert d["decision"] == "investigate"
    assert d["action"]["tool"] == "zoom_region"


def test_parse_valid_verdict():
    raw = '```json\n{"thought":"x","decision":"verdict","verdict":{"conclusion":"正常",' \
          '"risk":"低","regions":"无","basis":"...","advice":"..."}}\n```'
    assert parse_turn(raw)["verdict"]["conclusion"] == "正常"


def test_parse_picks_last_json_block():
    raw = '```json\n{"decision":"investigate","thought":"旧"}\n```\n改主意\n' \
          '```json\n{"thought":"新","decision":"verdict","verdict":{"conclusion":"正常"}}\n```'
    assert parse_turn(raw)["decision"] == "verdict"


@pytest.mark.parametrize("raw", [
    "没有 json 块",
    '```json\n{"thought":"缺 decision"}\n```',
    '```json\n{"decision":"investigate"}\n```',          # investigate 但缺 action
    '```json\n{decision: 不是合法json}\n```',
])
def test_parse_errors(raw):
    with pytest.raises(ProtocolError):
        parse_turn(raw)


def test_system_prompt_lists_tools():
    p = build_system_prompt([FakeTool()])
    assert "zoom_region" in p and "```json" in p


def test_format_verdict():
    md = format_verdict({"conclusion": "疑似篡改", "risk": "中", "regions": "金额栏",
                         "basis": "字体不一致", "advice": "人工核实"})
    assert "疑似篡改" in md and "🟡" in md
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_agent_protocol.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: 实现 agent.py 协议层**

```python
# agent.py — VLM 复核层：JSON 行动协议 Loop + 直链回退（Loop 与 UI 通过 TraceEvent 解耦）
import io
import json
import base64
import re
from dataclasses import dataclass, field
from datetime import date

import config


# ─── 数据结构 ──────────────────────────────────────────────────────
@dataclass
class TraceEvent:
    turn: int
    type: str      # stage|thought|tool_call|tool_result|verdict|fallback
    payload: dict


@dataclass
class AgentContext:
    image_path: str
    original_img: object          # PIL.Image（原始全分辨率）
    heatmap_img: object           # PIL.Image
    score: float
    infer_size: str
    tiled: bool
    candidates: list = field(default_factory=list)


class ProtocolError(Exception):
    pass


# ─── VLM 调用封装 ───────────────────────────────────────────────────
def image_to_base64(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def call_vlm(messages):
    import os
    import dashscope
    dashscope.base_http_api_url = config.VLM_BASE_URL
    resp = dashscope.MultiModalConversation.call(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        model=config.VLM_MODEL,
        messages=messages)
    if resp.status_code != 200:
        raise RuntimeError(f"VLM 调用失败: {resp.code} - {resp.message}")
    return resp.output.choices[0].message.content[0]["text"]


# ─── JSON 行动协议 ──────────────────────────────────────────────────
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def parse_turn(raw):
    blocks = _JSON_BLOCK.findall(raw)
    if not blocks:
        raise ProtocolError("未找到 ```json 代码块")
    try:
        d = json.loads(blocks[-1])
    except json.JSONDecodeError as e:
        raise ProtocolError(f"JSON 解析失败: {e}")
    if d.get("decision") not in ("investigate", "verdict"):
        raise ProtocolError("decision 字段缺失或非法")
    if d["decision"] == "investigate" and not d.get("action", {}).get("tool"):
        raise ProtocolError("investigate 必须携带 action.tool")
    if d["decision"] == "verdict" and not d.get("verdict", {}).get("conclusion"):
        raise ProtocolError("verdict 必须携带 verdict.conclusion")
    return d


def build_system_prompt(tools):
    tool_lines = "\n".join(
        f"- {t.name}: {t.description}\n  参数: {t.args_hint}" for t in tools)
    return f"""你是金融文档审核 AI Agent。当前日期：{date.today().isoformat()}。
你先收到 CV 篡改检测工具（TruFor）的首检结果（热力图、置信度分数、可疑区域候选框），\
你的职责是像审核员一样层层求证，最终给出财务人员可执行的审核结论。

可用工具：
{tool_lines}

每轮你必须输出且只输出一个 ```json 代码块，形如：
```json
{{"thought": "本轮分析（简要）",
 "decision": "investigate 或 verdict",
 "action": {{"tool": "工具名", "args": {{...}}}},
 "verdict": {{"conclusion": "正常/疑似篡改/高度可疑/无法审核(非金融单据)",
             "risk": "低/中/高",
             "regions": "异常区域及内容，无则写'无'",
             "basis": "复核依据（面向财务人员，禁用技术术语）",
             "advice": "建议操作"}}}}
```
decision=investigate 时必须给 action 且不给 verdict；decision=verdict 时必须给 verdict。

决策原则：
1. 先独立审视原图（文档类型、金额/日期/印章/签名等关键字段）；若并非金融单据，直接 verdict=无法审核。
2. CV 分数处于灰区（{config.LOW_THRESH}~{config.HIGH_THRESH}）、或标记区域涉及关键字段、或你与 CV 结论矛盾时，优先 investigate 查证。
3. 每次工具结果都要与已有证据交叉验证；证据充分即尽快 verdict，最多 {config.AGENT_MAX_TURNS} 轮。"""


def build_first_user_content(ctx):
    cand = "无" if not ctx.candidates else "\n".join(
        f"  #{c['id']}: bbox={c['bbox']} 面积占比={c['area_frac']:.2%} 区域均分={c['mean_score']}"
        for c in ctx.candidates)
    tiled_note = ("\n注意：该图超出单次推理上限，为切片推理结果，全局分数可信度较低，" 
                  "建议对关键区域放大查证。") if ctx.tiled else ""
    return [
        {"text": f"CV 首检结果——整体篡改置信度：{ctx.score:.4f}（0=正常 1=篡改），"
                 f"推理尺寸：{ctx.infer_size}。{tiled_note}\n可疑区域候选框（0-1000 归一化）：\n{cand}"},
        {"text": "【原始文档图片】"},
        {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.original_img)}"},
        {"text": "【CV 检测热力图（红=可疑）】"},
        {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.heatmap_img)}"},
    ]


def tool_result_content(name, tr):
    content = [{"text": f"工具 {name} 返回：{tr.text}"}]
    for img in tr.images:
        content.append({"image": f"data:image/jpeg;base64,{image_to_base64(img)}"})
    return content


RISK_EMOJI = {"低": "🟢", "中": "🟡", "高": "🔴"}


def format_verdict(v):
    emoji = RISK_EMOJI.get(v.get("risk", ""), "⚪")
    return (f"### 审核结论：{v.get('conclusion', '')}\n\n"
            f"**风险等级**：{emoji} {v.get('risk', '—')}\n\n"
            f"**异常区域**：{v.get('regions', '无')}\n\n"
            f"**复核依据**：{v.get('basis', '')}\n\n"
            f"**建议操作**：{v.get('advice', '')}")


# ─── 直链回退（自 app.py 迁移，初复赛实战验证过的路径）────────────────
DIRECT_SYSTEM_PROMPT = f"""你是金融文档审核 AI 助手。当前日期：{date.today().isoformat()}。你将收到：
1. 一张待审核的金融文档图片（原图）
2. CV 篡改检测工具的分析结果（热力图，红色=可疑区域）
3. CV 工具给出的篡改置信度分数（0-1，越高越可疑）

请执行以下复核流程：

Step 1 - 独立审视：先看原图，识别文档类型、关键字段（金额、日期、签名、印章等）
Step 2 - 交叉验证：对比 CV 工具标记的可疑区域——
  - 该区域确实存在视觉异常吗？（如文字风格不一致、边缘不自然、颜色差异）
  - 还是可能的误报？（水印、低质量区域、正常的格式变化）
Step 3 - 综合判定：结合 CV 像素级证据 + 你的视觉理解，给出最终判定
Step 4 - 输出审核意见：用中文，面向财务人员，不使用技术术语

输出格式：
- 审核结论（正常/疑似篡改/高度可疑）
- 异常区域及内容（如有）
- 复核依据
- 风险等级（🟢低 / 🟡中 / 🔴高）
- 建议操作"""


def direct_review(ctx):
    messages = [
        {"role": "system", "content": [{"text": DIRECT_SYSTEM_PROMPT}]},
        {"role": "user", "content": [
            {"text": f"CV 篡改检测置信度分数：{ctx.score:.4f}（0=正常，1=篡改）\n\n请对以下文档进行复核审查："},
            {"text": "【原始文档图片】"},
            {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.original_img)}"},
            {"text": "【CV 检测热力图（红色=可疑区域）】"},
            {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.heatmap_img)}"},
        ]},
    ]
    return call_vlm(messages)
```

- [ ] **Step 4: 运行测试通过**

```bash
.venv/bin/python -m pytest tests/test_agent_protocol.py -v
```
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent_protocol.py
git commit -m "feat: Agent 协议层——TraceEvent/JSON 解析/Prompt/VLM 封装 + 直链迁移

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: agent.py（二）Loop 主体与三模式 review()

**Files:**
- Modify: `agent.py`（追加 `review()` 及内部 `_agent_loop()`）
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: Task 5 全部；`tools: list[Tool]`（调用方传入）
- Produces: `review(ctx: AgentContext, tools: list, mode: str = "agent", vlm=call_vlm) -> Generator[TraceEvent]`
  - mode ∈ `"agent"|"direct"|"cv"`；`vlm` 参数注入以便测试
  - 保证：最后一个事件 type 必为 `"verdict"`；其 payload 结构 `{"verdict": dict|None, "text": str, "source": "agent"|"agent-forced"|"direct"|"cv"}`
  - 回退时先 yield `type="fallback"`（payload `{"reason": str}`）再走直链

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agent_loop.py
import pytest
from PIL import Image
from agent import AgentContext, TraceEvent, review


def _ctx(score=0.55, tiled=False):
    img = Image.new("RGB", (400, 300), "white")
    return AgentContext(image_path="/tmp/x.png", original_img=img, heatmap_img=img,
                        score=score, infer_size="400x300", tiled=tiled,
                        candidates=[{"id": 1, "bbox": [100, 100, 300, 300],
                                     "area_frac": 0.02, "mean_score": 0.8}])


class FakeTool:
    name = "zoom_region"
    description = "放大"
    args_hint = "{}"

    def available(self):
        return True

    def run(self, ctx, **kw):
        from tools import ToolResult
        return ToolResult(text="裁片完成", images=[Image.new("RGB", (50, 50))])


def _scripted_vlm(responses):
    it = iter(responses)

    def vlm(messages):
        return next(it)
    return vlm


INVESTIGATE = ('```json\n{"thought":"灰区需查证","decision":"investigate",'
               '"action":{"tool":"zoom_region","args":{"region_id":1}}}\n```')
VERDICT = ('```json\n{"thought":"证据充分","decision":"verdict","verdict":'
           '{"conclusion":"疑似篡改","risk":"中","regions":"金额栏","basis":"字体不一致","advice":"人工核实"}}\n```')


def _types(events):
    return [e.type for e in events]


def test_investigate_then_verdict():
    evs = list(review(_ctx(), [FakeTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, VERDICT])))
    t = _types(evs)
    assert t == ["stage", "thought", "tool_call", "tool_result", "thought", "verdict"]
    assert evs[-1].payload["source"] == "agent"
    assert evs[-1].payload["verdict"]["conclusion"] == "疑似篡改"
    assert "疑似篡改" in evs[-1].payload["text"]


def test_max_turns_forces_verdict():
    evs = list(review(_ctx(), [FakeTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, INVESTIGATE, INVESTIGATE, VERDICT])))
    assert _types(evs)[-1] == "verdict"
    assert evs[-1].payload["source"] == "agent-forced"


def test_parse_fail_twice_falls_back():
    calls = {"n": 0}

    def vlm(messages):
        calls["n"] += 1
        if calls["n"] <= 2:
            return "不是 json"
        return "直链的自由文本审核意见"        # 第三次调用来自直链

    evs = list(review(_ctx(), [FakeTool()], mode="agent", vlm=vlm))
    assert "fallback" in _types(evs)
    assert evs[-1].type == "verdict" and evs[-1].payload["source"] == "direct"
    assert evs[-1].payload["text"] == "直链的自由文本审核意见"


def test_vlm_dead_falls_back_to_cv_only():
    def vlm(messages):
        raise RuntimeError("网络挂了")

    evs = list(review(_ctx(score=0.85), [FakeTool()], mode="agent", vlm=vlm))
    assert evs[-1].type == "verdict" and evs[-1].payload["source"] == "cv"
    assert "0.85" in evs[-1].payload["text"] or "高度可疑" in evs[-1].payload["text"]


def test_tool_error_returned_to_vlm():
    class BadTool(FakeTool):
        def run(self, ctx, **kw):
            from tools import ToolResult
            return ToolResult(text="炸了", error=True)

    evs = list(review(_ctx(), [BadTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, VERDICT])))
    tr = [e for e in evs if e.type == "tool_result"][0]
    assert tr.payload["error"] is True
    assert evs[-1].type == "verdict"          # loop 未中断


def test_mode_direct_and_cv():
    evs = list(review(_ctx(), [], mode="direct", vlm=lambda m: "直链意见"))
    assert _types(evs) == ["stage", "verdict"] and evs[-1].payload["source"] == "direct"

    evs = list(review(_ctx(score=0.2), [], mode="cv"))
    assert evs[-1].payload["source"] == "cv" and "未见明显篡改" in evs[-1].payload["text"]
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_agent_loop.py -v
```
Expected: FAIL `ImportError: cannot import name 'review'`

- [ ] **Step 3: 在 agent.py 追加 Loop 实现**

```python
# ─── Loop 主体与三模式入口 ───────────────────────────────────────────
def _cv_only_verdict(ctx):
    if ctx.score > config.HIGH_THRESH:
        label, risk = "高度可疑", "高"
    elif ctx.score > config.LOW_THRESH:
        label, risk = "疑似异常", "中"
    else:
        label, risk = "未见明显篡改", "低"
    text = (f"### 审核结论：{label}\n\n**CV 置信度分数**：{ctx.score:.4f}\n\n"
            f"**风险等级**：{RISK_EMOJI[risk]} {risk}\n\n"
            f"（AI 复核暂不可用，以上为 CV 工具独立判定，建议结合人工审核）")
    return {"verdict": None, "text": text, "source": "cv"}


def _agent_loop(ctx, tools, vlm):
    """真 Agent Loop。异常向上抛，由 review() 统一降级。"""
    messages = [{"role": "system", "content": [{"text": build_system_prompt(tools)}]},
                {"role": "user", "content": build_first_user_content(ctx)}]
    tool_map = {t.name: t for t in tools}
    parse_fails = 0

    for turn in range(1, config.AGENT_MAX_TURNS + 2):     # +1 轮用于强制收敛
        forced = turn > config.AGENT_MAX_TURNS
        if forced:
            messages.append({"role": "user", "content": [
                {"text": "已到最大查证轮数，请立即输出 decision=verdict 的最终判定。"}]})
        raw = vlm(messages)
        try:
            d = parse_turn(raw)
        except ProtocolError as e:
            parse_fails += 1
            if parse_fails >= 2:
                raise
            messages.append({"role": "assistant", "content": [{"text": raw}]})
            messages.append({"role": "user", "content": [
                {"text": f"输出格式错误（{e}）。请严格按系统提示，只输出一个 ```json 代码块。"}]})
            continue
        parse_fails = 0
        messages.append({"role": "assistant", "content": [{"text": raw}]})

        yield TraceEvent(turn, "thought", {"thought": d.get("thought", "")})

        if d["decision"] == "verdict" or forced:
            v = d.get("verdict") or {"conclusion": "无法判定", "risk": "中",
                                     "regions": "—", "basis": "模型未给出结构化结论", "advice": "建议人工审核"}
            yield TraceEvent(turn, "verdict", {"verdict": v, "text": format_verdict(v),
                                               "source": "agent-forced" if forced else "agent"})
            return

        name = d["action"]["tool"]
        args = d["action"].get("args", {}) or {}
        yield TraceEvent(turn, "tool_call", {"tool": name, "args": args})
        tool = tool_map.get(name)
        if tool is None:
            # 鸭子构造，保持 agent 不 import tools 的依赖方向
            tr = type("TR", (), {"text": f"工具 {name} 不存在", "images": [], "error": True})()
        else:
            tr = tool.run(ctx, **args)
        yield TraceEvent(turn, "tool_result", {"tool": name, "text": tr.text,
                                               "images": list(tr.images), "error": tr.error})
        messages.append({"role": "user", "content": tool_result_content(name, tr)})

    # 理论不可达（forced 分支必 return），防御性兜底
    raise ProtocolError("loop 未收敛")


def review(ctx, tools, mode="agent", vlm=call_vlm):
    """统一入口：mode=agent|direct|cv。保证最后一个事件必为 verdict。"""
    yield TraceEvent(0, "stage", {"stage": "vlm_review", "mode": mode})

    if mode == "cv":
        yield TraceEvent(0, "verdict", _cv_only_verdict(ctx))
        return

    if mode == "agent":
        try:
            yield from _agent_loop(ctx, tools, vlm)
            return
        except (ProtocolError, RuntimeError) as e:
            yield TraceEvent(0, "fallback", {"reason": f"Agent 模式失败（{e}），回退直链复核"})

    # mode == "direct"，或 agent 回退至此
    try:
        text = direct_review(ctx) if vlm is call_vlm else vlm(None)
        yield TraceEvent(0, "verdict", {"verdict": None, "text": text, "source": "direct"})
    except Exception:
        yield TraceEvent(0, "verdict", _cv_only_verdict(ctx))
```

注意 `review()` 中 direct 路径对注入 vlm 的处理：测试注入的 fake 直接调用 `vlm(None)`；真实路径走 `direct_review(ctx)`。

- [ ] **Step 4: 运行全部测试**

```bash
.venv/bin/python -m pytest tests/ -v
```
Expected: 全部 passed（config 2 + regions 3 + tools 5 + protocol 8 + loop 7 = 25）

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent_loop.py
git commit -m "feat: Agent Loop 主体——三模式 review()/强制收敛/三级降级

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 真机冒烟——qwen 实调校准 Prompt（关键风险闸门）

最大的未知数是 qwen3.7-max 对 JSON 协议的遵循度与 bbox 质量。UI 动工前先用真实 API 全链路验证，必要时在此调 Prompt。

**Files:**
- Create: `scripts/smoke_agent.py`
- Test: 人工检视输出（integration 冒烟）

**Interfaces:**
- Consumes: `run_inference` 全套、`agent.review`、`tools.build_registry`、`regions.extract_candidate_regions`
- Produces: 验证过的 Prompt（如有修改，落在 agent.py 并 commit）；dev-log 记录每张示例图的行为

- [ ] **Step 1: 写冒烟脚本**

```python
# scripts/smoke_agent.py — 真机全链路：TruFor → Agent Loop → 事件流打印
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

import config
from run_inference import select_device, load_model, run_single, TRUFOR_ROOT
from regions import extract_candidate_regions
from tools import build_registry
from agent import AgentContext, review


def main(image_path, mode="agent"):
    device = select_device()
    model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
    result = run_single(model, image_path, device, max_size=config.MAX_SIZE)
    if device == "mps":
        import torch
        torch.mps.empty_cache()

    ctx = AgentContext(
        image_path=image_path,
        original_img=Image.open(image_path).convert("RGB"),
        heatmap_img=_render_heatmap(result["map"]),
        score=result["score"],
        infer_size=str(result["infer_size"]),
        tiled="tiled" in str(result["infer_size"]),
        candidates=extract_candidate_regions(result["map"]),
    )
    print(f"\n=== CV: score={ctx.score:.4f} size={ctx.infer_size} candidates={len(ctx.candidates)} ===\n")
    for ev in review(ctx, build_registry(), mode=mode):
        images = ev.payload.get("images", [])
        brief = {k: v for k, v in ev.payload.items() if k != "images"}
        print(f"[turn {ev.turn}] {ev.type}: {brief}" + (f" (+{len(images)} 图)" if images else ""))
    print()


def _render_heatmap(loc_map):
    import numpy as np
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(loc_map)[:, :, :3] * 255).astype("uint8"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "agent")
```

- [ ] **Step 2: 逐张跑通示例图**

```bash
.venv/bin/python scripts/smoke_agent.py "example-images/微信圖片_20260629180523_53_237.png"
.venv/bin/python scripts/smoke_agent.py "example-images/微信圖片_20260629180505_50_237.jpg"   # 3456px 切片图（坑#3 主角）
.venv/bin/python scripts/smoke_agent.py example-images/check.jpg
```
Expected 检查清单（人工判断）：
1. 每轮输出合法 JSON（无 ProtocolError 重试痕迹）；
2. 灰区图确实触发 investigate + zoom（若从不 investigate 或永远 investigate → 调整系统提示"决策原则"措辞并重跑）；
3. zoom 的 region_id/bbox 落在合理位置（对照热力图目测）；
4. 切片图（50_237）收到 tiled 提示后倾向放大查证；
5. verdict 话术面向财务、无技术术语。

- [ ] **Step 3: 按需微调 Prompt 并复跑**

只允许改 `agent.py` 的 `build_system_prompt`/`build_first_user_content` 文案；每次修改后复跑 Step 2 三张图 + `pytest tests/`（防协议破坏）。

- [ ] **Step 4: 记录 dev-log 并 commit**

`docs/dev-log.md` 追加：三张图各自的轮数/工具调用/结论、Prompt 修改点及原因。

```bash
git add scripts/smoke_agent.py agent.py docs/dev-log.md
git commit -m "feat: Agent Loop 真机冒烟通过 + Prompt 实调校准

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: app.py 三栏流式 UI + start.sh

**Files:**
- Modify: `app.py`（整体重写，直链/加载逻辑已迁至 agent.py）
- Create: `start.sh`
- Test: 人工冒烟清单（UI 无单测）；`pytest tests/` 回归

**Interfaces:**
- Consumes: `agent.review/AgentContext`、`tools.build_registry`、`regions.extract_candidate_regions`、`run_inference.*`、`config.*`
- Produces: `http://localhost:7860` 三栏界面；`start.sh` 一键启动

- [ ] **Step 1: 重写 app.py**

```python
"""金融文档篡改检测 — Gradio Demo (TruFor 首检 + Agent Loop 复核)"""
import os
import tempfile

import gradio as gr
import numpy as np
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()                       # 评委 iPhone HEIC 直传

import config
from run_inference import select_device, load_model, run_single, TRUFOR_ROOT
from regions import extract_candidate_regions
from tools import build_registry
from agent import AgentContext, review

# ─── Global model（启动即加载 + warmup）────────────────────────────
DEVICE = select_device()
MODEL = load_model(DEVICE, os.path.join(TRUFOR_ROOT, 'pretrained_models', 'trufor.pth.tar'))
TOOLS = build_registry()


def _warmup():
    tiny = Image.new('RGB', (256, 256), 'white')
    p = os.path.join(tempfile.gettempdir(), 'docguard_warmup.png')
    tiny.save(p)
    run_single(MODEL, p, DEVICE, max_size=config.MAX_SIZE)
    if DEVICE == 'mps':
        import torch
        torch.mps.empty_cache()
    print('Warmup done.')


_warmup()

# ─── 渲染 ──────────────────────────────────────────────────────────
def render_heatmap(loc_map):
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(loc_map)[:, :, :3] * 255).astype(np.uint8))


def render_confidence(conf_map):
    gray = (np.clip(conf_map, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(gray, mode='L').convert('RGB')


def _verdict_str(score):
    if score > config.HIGH_THRESH:
        return f"🔴 高度可疑 (score: {score:.4f})"
    if score > config.LOW_THRESH:
        return f"🟡 疑似异常 (score: {score:.4f})"
    return f"🟢 未见明显篡改 (score: {score:.4f})"


def _save_tmp(img):
    f = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
    img.convert('RGB').save(f.name, quality=90)
    return f.name


EVENT_TITLE = {
    'thought': '💭 第{turn}轮·思考',
    'tool_call': '🔧 第{turn}轮·调用工具',
    'tool_result': '📎 第{turn}轮·工具返回',
    'fallback': '⚠️ 降级',
}

MODE_MAP = {'Agent 复核（推荐）': 'agent', '快速复核': 'direct', '仅 CV 检测': 'cv'}


# ─── 主流程（生成器：流式驱动三栏）───────────────────────────────────
def analyze(image_path, mode_label):
    chat = [{"role": "assistant", "content": "🔬 阶段一：像素级取证中（TruFor）…"}]
    yield None, None, "", "", chat

    result = run_single(MODEL, image_path, DEVICE, max_size=config.MAX_SIZE)
    if DEVICE == 'mps':
        import torch
        torch.mps.empty_cache()

    heatmap_img = render_heatmap(result['map'])
    conf_img = render_confidence(result['conf'])
    verdict = _verdict_str(result['score'])
    info = f"推理尺寸: {result['infer_size']}（阈值经自建业务评测集校准）"
    chat.append({"role": "assistant", "content": f"✅ 取证完成，置信度 {result['score']:.4f}，进入 AI 复核"})
    yield heatmap_img, conf_img, verdict, info, chat

    ctx = AgentContext(
        image_path=image_path,
        original_img=Image.open(image_path).convert('RGB'),
        heatmap_img=heatmap_img,
        score=result['score'],
        infer_size=str(result['infer_size']),
        tiled='tiled' in str(result['infer_size']),
        candidates=extract_candidate_regions(result['map']),
    )

    for ev in review(ctx, TOOLS, mode=MODE_MAP.get(mode_label, 'agent')):
        if ev.type == 'stage':
            continue
        if ev.type == 'verdict':
            chat.append({"role": "assistant", "content": ev.payload['text']})
        elif ev.type == 'tool_result':
            body = ev.payload['text']
            chat.append({"role": "assistant", "content": body,
                         "metadata": {"title": EVENT_TITLE['tool_result'].format(turn=ev.turn)}})
            for img in ev.payload.get('images', []):
                chat.append({"role": "assistant", "content": {"path": _save_tmp(img)}})
        else:
            title = EVENT_TITLE.get(ev.type, ev.type).format(turn=ev.turn)
            body = ev.payload.get('thought') or ev.payload.get('reason') or \
                f"{ev.payload.get('tool')} {ev.payload.get('args', '')}"
            chat.append({"role": "assistant", "content": str(body), "metadata": {"title": title}})
        yield heatmap_img, conf_img, verdict, info, chat


# ─── UI ────────────────────────────────────────────────────────────
FORCE_LIGHT = "() => { document.body.classList.remove('dark'); }"

with gr.Blocks(title="DocGuard 文档篡改智能审核", theme=gr.themes.Soft(), js=FORCE_LIGHT) as demo:
    gr.Markdown("""
    # 🔍 DocGuard — 文档篡改智能审核系统
    **像素级取证（TruFor）+ AI Agent 自主复核** &nbsp;|&nbsp; 上传单据 → CV 取证 → AI 层层求证 → 审核意见
    """)

    with gr.Row():
        with gr.Column(scale=1):
            input_image = gr.Image(type="filepath", label="上传文档图片")
            mode = gr.Radio(list(MODE_MAP.keys()), value="Agent 复核（推荐）", label="复核模式")
            submit_btn = gr.Button("开始检测", variant="primary", size="lg")
            gr.Examples(
                examples=[[os.path.join("example-images", f)]
                          for f in sorted(os.listdir("example-images"))
                          if f.lower().endswith(('.jpg', '.jpeg', '.png'))],
                inputs=[input_image], label="示例文档")

        with gr.Column(scale=2):
            with gr.Row():
                heatmap_out = gr.Image(label="篡改定位热力图（红=可疑）", type="pil")
                conf_out = gr.Image(label="置信度图（白=高置信）", type="pil")
            verdict_out = gr.Textbox(label="CV 检测判定", lines=1)
            info_out = gr.Textbox(label="推理信息", lines=1)

        with gr.Column(scale=2):
            trace_out = gr.Chatbot(label="AI 审核过程（实时）", type="messages", height=560)

    submit_btn.click(fn=analyze, inputs=[input_image, mode],
                     outputs=[heatmap_out, conf_out, verdict_out, info_out, trace_out])

if __name__ == '__main__':
    demo.queue(default_concurrency_limit=1, max_size=8)
    demo.launch(server_name="0.0.0.0", server_port=7860)
```

实施注意（执行者必读）：Gradio 6.19 的 Chatbot messages 富媒体格式以运行时行为为准——若 `{"path": ...}` 图片消息不渲染，改用备选：`gr.Image` 存 `gr.File` 不行时，将裁片以 `<img src="data:image/jpeg;base64,...">` HTML 内嵌进 content 字符串（Chatbot 支持 HTML）。二选一验证后保留其一。

- [ ] **Step 2: 写 start.sh**

```bash
#!/usr/bin/env bash
# start.sh — 一键启动（环境检查 + 起服务；warmup 在 app.py 内完成）
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "缺少 .env（需 DASHSCOPE_API_KEY）"; exit 1; }
grep -q DASHSCOPE_API_KEY .env || { echo ".env 缺少 DASHSCOPE_API_KEY"; exit 1; }
[ -f TruFor/TruFor_train_test/pretrained_models/trufor.pth.tar ] || { echo "缺少 TruFor 权重"; exit 1; }
echo "启动 DocGuard（http://localhost:7860 ，浏览器请带 ?__theme=light）"
exec .venv/bin/python app.py
```

```bash
chmod +x start.sh
```

- [ ] **Step 3: 人工冒烟清单**

```bash
./start.sh
```
浏览器 `http://localhost:7860/?__theme=light` 逐项检查：
1. 启动日志出现 `Warmup done.`；
2. 上传示例灰区图，三栏就位：左上传、中热力图先出、右轨迹逐条流式追加（思考折叠块 + 工具徽章 + 裁片图内嵌）；
3. 三种模式各跑一次同一张图，行为差异符合预期（agent 有轨迹 / direct 单条意见 / cv 秒出）；
4. 把 `.env` 的 key 临时改错重启 → agent 模式显示"⚠️ 降级"并落 CV-only（改回后复原）；
5. 上传一张手机 HEIC 照片可正常处理；
6. 上传非单据图（如风景照）→ verdict 为"无法审核(非金融单据)"；
7. 双开两个浏览器页同时提交 → 第二个排队不崩；
8. 上传损坏文件（`echo bad > /tmp/bad.jpg`）→ 界面显示错误提示，服务不崩、后续请求正常。

- [ ] **Step 4: 回归 + Commit**

```bash
.venv/bin/python -m pytest tests/ -v
```
Expected: 25 passed

```bash
git add app.py start.sh
git commit -m "feat: 三栏流式 UI——Chatbot Agent 轨迹 + 三模式 + HEIC/warmup/队列

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: 评测集脚手架 + 制作指引（人工并行线，今天就启动）

**Files:**
- Create: `eval-images/README.md`、六个子目录的 `.gitkeep`
- 无代码测试；产出为素材收集的启动

**Interfaces:**
- Produces: `eval-images/{normal,amount,date,seal,aigc,copymove}/` 目录约定——Task 10 的 `collect_dataset()` 依赖"目录即标签"（normal=0，其余=1）

- [ ] **Step 1: 建目录与制作指引**

```bash
mkdir -p eval-images/{normal,amount,date,seal,aigc,copymove}
touch eval-images/{normal,amount,date,seal,aigc,copymove}/.gitkeep
```

```markdown
# eval-images/README.md — 评测集制作指引

目标 13-15 张，目录即标签（normal=负样本，其余=篡改正样本）。

| 目录 | 内容 | 数量 | 来源 |
|---|---|---|---|
| normal | 未修改的真实单据（脱敏） | 3-4 | 业务组员提供（立刻发起收集！） |
| amount | PS 修改金额 | 2-3 | 自制 |
| date | PS 修改日期 | 2 | 自制 |
| seal | PS 拼接/替换印章 | 2 | 自制 |
| aigc | AI inpaint 重绘区域 | 2 | 即梦/SD inpaint |
| copymove | 复制粘贴条目 | 2 | 自制 |

制作规则（两档手艺，缺一不可）：
1. **粗改**每类 1 张：肉眼可对照，演示直观。
2. **精改**每类 1 张：字体贴合、边缘羽化——指标才可信。
3. 保存格式与原件一致（jpg 存 jpg，quality≥90），**绝不缩放**（坏噪声指纹=评测作废）。
4. 每张篡改图在文件名记录改动点，如 `amount_5000to50000_fine.jpg`。
5. 原件留档 `_orig` 后缀放同目录（评测脚本按前缀去重跳过 `_orig`）。
```

- [ ] **Step 2: Commit 并立刻向业务组员发起样张收集**

```bash
git add eval-images/
git commit -m "chore: 评测集脚手架与制作指引（6 类，两档手艺）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
同时（计划外人工动作）：向业务组员要 normal 真实脱敏样张；服务器申请单也在今天提交。

---

### Task 10: evaluate.py — 批量评测 + 阈值校准 + CV/Agent 对照

**Files:**
- Create: `evaluate.py`, `tests/test_evaluate.py`
- Modify: 校准后回写 `.env`（`DOCGUARD_LOW_THRESH/HIGH_THRESH`）

**Interfaces:**
- Consumes: `eval-images/` 目录约定、`run_inference.*`、`agent.review`（mode="cv"|"agent"）
- Produces:
  - `collect_dataset(root="eval-images") -> list[tuple[str, int, str]]`（path, label, category；跳过 `_orig`/`.gitkeep`）
  - `sweep(rows: list[dict]) -> list[dict]`（每行 `{"thresh","tpr","fpr"}`，rows 元素含 `score:float,label:int`）
  - `suggest_thresholds(rows) -> tuple[float, float]`
  - CLI：`--mode cv|agent --out results.csv`；`--calibrate results.csv`
  - CSV 列：`path,label,category,score,verdict_bin,source`

- [ ] **Step 1: 写失败测试（纯逻辑部分）**

```python
# tests/test_evaluate.py
from evaluate import sweep, suggest_thresholds, verdict_to_bin


def _rows():
    normals = [{"score": s, "label": 0} for s in (0.05, 0.12, 0.2, 0.31)]
    tampers = [{"score": s, "label": 1} for s in (0.45, 0.6, 0.72, 0.88, 0.93)]
    return normals + tampers


def test_sweep_monotonic_ends():
    table = sweep(_rows())
    assert table[0]["thresh"] == 0.0 and table[0]["tpr"] == 1.0 and table[0]["fpr"] == 1.0
    assert table[-1]["tpr"] == 0.0 and table[-1]["fpr"] == 0.0


def test_suggest_thresholds_separates():
    low, high = suggest_thresholds(_rows())
    assert 0.31 < low < high < 0.72      # low 高于全部 normal，high 落在篡改分布下沿（P30≈0.62）


def test_verdict_to_bin():
    assert verdict_to_bin("高度可疑") == 1
    assert verdict_to_bin("疑似篡改") == 1
    assert verdict_to_bin("正常") == 0
    assert verdict_to_bin("无法审核(非金融单据)") is None
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_evaluate.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'evaluate'`

- [ ] **Step 3: 实现 evaluate.py**

```python
# evaluate.py — 自建评测集：批量跑分 / 阈值校准 / CV vs Agent 端到端对照
import argparse
import csv
import os

import numpy as np

import config

CATEGORIES = ("normal", "amount", "date", "seal", "aigc", "copymove")
_VERDICT_BIN = {"高度可疑": 1, "疑似篡改": 1, "疑似异常": 1, "正常": 0, "未见明显篡改": 0}


def verdict_to_bin(conclusion):
    for k, v in _VERDICT_BIN.items():
        if k in (conclusion or ""):
            return v
    return None                       # 无法审核等 → 排除出指标


def collect_dataset(root="eval-images"):
    items = []
    for cat in CATEGORIES:
        d = os.path.join(root, cat)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.startswith(".") or "_orig" in f:
                continue
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                items.append((os.path.join(d, f), 0 if cat == "normal" else 1, cat))
    return items


def sweep(rows, step=0.02):
    pos = [r for r in rows if r["label"] == 1]
    neg = [r for r in rows if r["label"] == 0]
    table = []
    for t in np.arange(0.0, 1.0 + step, step):
        tpr = sum(r["score"] >= t for r in pos) / max(len(pos), 1)
        fpr = sum(r["score"] >= t for r in neg) / max(len(neg), 1)
        table.append({"thresh": round(float(t), 2), "tpr": round(tpr, 3), "fpr": round(fpr, 3)})
    return table


def suggest_thresholds(rows):
    neg = sorted(r["score"] for r in rows if r["label"] == 0)
    pos = sorted(r["score"] for r in rows if r["label"] == 1)
    low = round(min(neg[-1] + 0.05, (neg[-1] + pos[0]) / 2 + 0.02), 2) if neg and pos else config.LOW_THRESH
    high = round(float(np.percentile(pos, 30)), 2) if pos else config.HIGH_THRESH
    if low >= high:
        low = round(high - 0.1, 2)
    return low, high


def run_batch(mode, out_csv):
    from PIL import Image
    from run_inference import select_device, load_model, run_single, TRUFOR_ROOT
    from regions import extract_candidate_regions
    from tools import build_registry
    from agent import AgentContext, review

    device = select_device()
    model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
    tools = build_registry()
    rows = []
    for path, label, cat in collect_dataset():
        result = run_single(model, path, device, max_size=config.MAX_SIZE)
        if device == "mps":
            import torch
            torch.mps.empty_cache()
        row = {"path": path, "label": label, "category": cat,
               "score": round(float(result["score"]), 4), "verdict_bin": "", "source": "cv"}
        if mode == "agent":
            import matplotlib
            matplotlib.use("agg")
            import matplotlib.cm as cm
            heat = Image.fromarray((cm.RdBu_r(result["map"])[:, :, :3] * 255).astype("uint8"))
            ctx = AgentContext(path, Image.open(path).convert("RGB"), heat,
                               result["score"], str(result["infer_size"]),
                               "tiled" in str(result["infer_size"]),
                               extract_candidate_regions(result["map"]))
            final = list(review(ctx, tools, mode="agent"))[-1].payload
            concl = (final["verdict"] or {}).get("conclusion", "") if final["verdict"] else final["text"][:20]
            row["verdict_bin"] = verdict_to_bin(concl)
            row["source"] = final["source"]
        rows.append(row)
        print(f"[{cat}] {os.path.basename(path)} score={row['score']}"
              + (f" agent={row['verdict_bin']}({row['source']})" if mode == "agent" else ""))

    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} 张已写入 {out_csv}")


def calibrate(csv_path):
    with open(csv_path) as f:
        rows = [{"score": float(r["score"]), "label": int(r["label"]), "category": r["category"]}
                for r in csv.DictReader(f)]
    print("\n各类分数分布：")
    for cat in CATEGORIES:
        ss = [r["score"] for r in rows if r["category"] == cat]
        if ss:
            print(f"  {cat:9s} n={len(ss)}  {sorted(ss)}")
    print("\n阈值扫描（thresh / TPR / FPR）：")
    for t in sweep(rows):
        print(f"  {t['thresh']:.2f}  {t['tpr']:.3f}  {t['fpr']:.3f}")
    low, high = suggest_thresholds(rows)
    print(f"\n建议阈值：LOW={low} HIGH={high}")
    print(f"人工确认后写入 .env：\nDOCGUARD_LOW_THRESH={low}\nDOCGUARD_HIGH_THRESH={high}")
    _plot_distribution(rows, os.path.join(os.path.dirname(csv_path) or ".", "score_dist.png"))


def _plot_distribution(rows, out_png):
    """各类 score 散点分布图（答辩/PPT 素材）。"""
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, cat in enumerate(CATEGORIES):
        ss = [r["score"] for r in rows if r["category"] == cat]
        ax.scatter([i] * len(ss), ss, s=60, alpha=0.7,
                   color="#2a9d8f" if cat == "normal" else "#e76f51")
    ax.set_xticks(range(len(CATEGORIES)), CATEGORIES)
    ax.set_ylabel("TruFor score")
    ax.set_ylim(0, 1)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    print(f"分布图已保存: {out_png}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cv", "agent"])
    ap.add_argument("--out", default="eval-report/results.csv")
    ap.add_argument("--calibrate")
    a = ap.parse_args()
    if a.calibrate:
        calibrate(a.calibrate)
    else:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        run_batch(a.mode or "cv", a.out)
```

- [ ] **Step 4: 逻辑测试通过 + Commit（代码部分）**

```bash
.venv/bin/python -m pytest tests/test_evaluate.py -v
```
Expected: 3 passed

```bash
git add evaluate.py tests/test_evaluate.py
git commit -m "feat: evaluate.py——批量评测/阈值扫描/CV-Agent 对照

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5:（素材齐后）实跑校准并回写阈值**

```bash
.venv/bin/python evaluate.py --mode cv --out eval-report/results_cv.csv
.venv/bin/python evaluate.py --calibrate eval-report/results_cv.csv
# 人工确认建议值后写入 .env，重启服务生效；随后跑 Agent 对照：
.venv/bin/python evaluate.py --mode agent --out eval-report/results_agent.csv
```
Expected: 拿到答辩三数字——CV 检出率/误报率@校准阈值、Agent 链路对照（重点看误报是否下降）。结果摘要记入 `docs/dev-log.md`，`eval-report/*.csv` 与 `.env` 变更 commit：

```bash
git add eval-report/ docs/dev-log.md
git commit -m "feat: 评测实跑与阈值校准（自建业务集，CV vs Agent 对照）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: hifi_inference.py — HiFi-Net 适配器（探索性，时间盒 2×2h）

**风险声明**：调研记录称 HiFi-Net "pip + 2 行代码"（`HiFi.detect()/HiFi.localize()`，repo: CHELSEA234/HiFi_IFDL，MIT）。安装路径需现场验证；**时间盒 2 次 × 2 小时**，超时即置 `DOCGUARD_ENABLE_HIFI=off` 记录 dev-log，转服务器专属工具，不阻塞主线。

**Files:**
- Create: `hifi_inference.py`, `tests/test_hifi_adapter.py`
- Modify: `.env`（按实测结果设 `DOCGUARD_ENABLE_HIFI`）

**Interfaces:**
- Consumes: HiFi-Net 包/仓库；`config.DEVICE_OVERRIDE`
- Produces（Task 4 的 SecondOpinionTool 已按此消费）:
  - `hifi_available() -> bool`（权重+依赖探测，不加载模型）
  - `run_hifi(image_path: str) -> dict`（`{score: float, map: np.ndarray, conf: None, infer_size: str}`——DetectorBackend 形状）
  - `render_hifi_heatmap(result: dict) -> PIL.Image`

- [ ] **Step 1: 安装尝试（按序，成功即止）**

```bash
# 尝试 1：pip（如 PyPI 有包）
.venv/bin/pip install hifi-ifdl || true
# 尝试 2：源码
git clone https://github.com/CHELSEA234/HiFi_IFDL /tmp/HiFi_IFDL && \
  ls /tmp/HiFi_IFDL  # 阅读其 README 确认权重下载方式与推理入口
```
按仓库 README 下载权重到 `hifi_weights/`（加入 .gitignore）。**若两条路径 2h 内都不通 → 直接跳到 Step 5 的降级分支。**

- [ ] **Step 2: 写适配器测试（结构测试，模型可选跳过）**

```python
# tests/test_hifi_adapter.py
import pytest
import hifi_inference


def test_available_is_bool():
    assert isinstance(hifi_inference.hifi_available(), bool)


@pytest.mark.skipif(not hifi_inference.hifi_available(), reason="HiFi-Net 未就绪（合法的双轨状态）")
def test_run_hifi_shape():
    r = hifi_inference.run_hifi("example-images/check.jpg")
    assert set(r) >= {"score", "map", "conf", "infer_size"}
    assert 0.0 <= r["score"] <= 1.0
    assert r["map"].ndim == 2
```

- [ ] **Step 3: 实现适配器（骨架固定，内部按实际 API 填充）**

```python
# hifi_inference.py — HiFi-Net 第二意见适配器（DetectorBackend 形状；随环境动态可用）
import os

import numpy as np

import config

_WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "hifi_weights")
_model = None


def hifi_available():
    if not os.path.isdir(_WEIGHTS_DIR) or not os.listdir(_WEIGHTS_DIR):
        return False
    try:
        import importlib
        importlib.import_module("hifi_net")   # 以实际包名为准，安装后修正
        return True
    except ImportError:
        return False


def _load():
    global _model
    if _model is None:
        # 以 HiFi_IFDL README 的实际加载方式为准填充；设备遵循 config.DEVICE_OVERRIDE
        from hifi_net import HiFi              # 以实际 API 为准
        _model = HiFi(weights=_WEIGHTS_DIR)
    return _model


def run_hifi(image_path):
    m = _load()
    score = float(m.detect(image_path))        # 以实际 API 为准
    loc = np.asarray(m.localize(image_path), dtype=np.float32)
    if loc.max() > 1.0:
        loc = loc / 255.0
    return {"score": score, "map": loc, "conf": None,
            "infer_size": f"{loc.shape[1]}x{loc.shape[0]} (hifi)"}


def render_hifi_heatmap(result):
    from PIL import Image
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(result["map"])[:, :, :3] * 255).astype("uint8"))
```

- [ ] **Step 4: Mac 可行性实测**

```bash
.venv/bin/python -m pytest tests/test_hifi_adapter.py -v
.venv/bin/python - <<'EOF'
import time, hifi_inference
if hifi_inference.hifi_available():
    t = time.time()
    r = hifi_inference.run_hifi("example-images/check.jpg")
    print(f"score={r['score']:.4f} 耗时={time.time()-t:.1f}s")
else:
    print("HiFi 不可用（双轨降级状态）")
EOF
```
判定：单张 ≤60s 且不 OOM → Mac 可用（`.env` 留 auto）；否则 `.env` 写 `DOCGUARD_ENABLE_HIFI=off`，服务器到位再开。

- [ ] **Step 5: 端到端验证 + Commit（含降级分支）**

可用时：跑 `scripts/smoke_agent.py` 灰区图，确认 Agent 会在合适时机调用 `second_opinion` 且轨迹含 HiFi 热力图。
不可用时：dev-log 记录卡点与降级决定（这也是 QA 素材："工具动态注册在真实环境的实际发挥"）。

```bash
git add hifi_inference.py tests/test_hifi_adapter.py .gitignore docs/dev-log.md
git commit -m "feat: HiFi-Net 第二意见适配器（动态可用，双轨降级）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: QA 预案 + 演示剧本 + 彩排

**Files:**
- Create: `docs/QA预案.md`, `docs/演示剧本.md`

**Interfaces:**
- Consumes: Task 10 的实测数字、Task 1/7/11 的 dev-log、spec 第 8 节骨架

- [ ] **Step 1: 写 docs/QA预案.md**

按 spec 第 8 节四类问题逐问写"3-5 句口径 + 指向证据"。硬性要求：
1. 每个口径必须引用真实产出（评测 CSV 数字、dev-log 的 FC 探测结论、代码文件名），禁止编造未做过的实验；
2. 数据安全问必须含三层：Demo 用公有云 API 的原因 → `agent.py call_vlm()` 单点抽象 → 服务器内网自部署开源 Qwen-VL 的替换路径；
3. "为什么绝不缩放"必须引用自测数字 0.945→0.177（坑 #2）；
4. "小样本可信度"承认域内点估计属性，引 DOCFORGE-BENCH 校准依据；
5. JSON 协议 vs 原生 FC 按 Task 1 探测结论写实际口径。

- [ ] **Step 2: 写 docs/演示剧本.md**

从评测集实跑记录中选 4 张剧本图并记录预期行为（score、轮数、工具调用、结论）：
1. 重度篡改 → 高分秒判；2. **灰区图 → Loop 放大改判（核心桥段）**；3. 误报图 → Agent 排除（快速模式 vs Agent 模式对照演示）；4. 正常图 → 快速通过。
附现场检查单：start.sh 启动 → warmup 完成 → 浏览器 ?__theme=light → 备用 4G 热点 → 断网降级预演。

- [ ] **Step 3: 全流程彩排一遍并 commit**

按剧本完整走一遍（含降级预演），偏差记录并修复或改剧本。

```bash
git add docs/QA预案.md docs/演示剧本.md
git commit -m "docs: 答辩 QA 预案 + 演示剧本（含降级预演）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 附录：服务器轨清单（到位后执行，全部为配置级变更）

1. 环境：Python 3.12 venv + `pip install -r requirements.txt`（CUDA 版 torch 按服务器驱动另装）；rsync 项目 + TruFor 权重。
2. 验证 DashScope 内网可达（`scripts/probe_fc.py` 跑一遍）。
3. `.env`：`DOCGUARD_DEVICE=cuda:0`；`DOCGUARD_MAX_SIZE` 从 1792 逐档实测 2048→2560→3072（用 50_237.jpg 验证坑 #3 是否被整图推理终结，记录 dev-log）。
4. `DOCGUARD_ENABLE_HIFI=on`（Task 11 若在 Mac 降级）。
5. `nohup ./start.sh` 或 systemd 常驻；内网 URL 分发验证。
6. 评测集在服务器复跑 `evaluate.py`，若 MAX_SIZE 提档改变分数分布则重新校准阈值。
7. HiFi-Net 同集跑分（spec §6-④）：`for path,_,_ in collect_dataset(): run_hifi(path)` 落 CSV，与 TruFor 分数并排出两模型一致/互补统计（一致率、TruFor 漏检中 HiFi 检出数）→ "为什么多模型"的答辩数字。

## 里程碑对照（spec 第 9 节）

- Task 1 ↔ Day 1 验活/探测；Task 2-6 ↔ Day 2-5 Loop 核心；Task 7 为 UI 前置风险闸门；Task 8 ↔ Day 5-8 UI；Task 9-10 ↔ Day 6-9 评测线（Task 9 今天启动人工收集）；Task 11 ↔ HiFi（Mac 时间盒 / 服务器轨）；Task 12 ↔ 最后 3-4 天 QA/彩排；附录 ↔ 服务器轨。
