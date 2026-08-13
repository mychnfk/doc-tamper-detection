# DocGuard 前端重写实施计划 — React + FastAPI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DocGuard 的 Gradio 界面重写为 React + FastAPI 的企业级审核台，并新增自动留痕的记录模块。

**Architecture:** `review()` 是纯生成器，只 `yield TraceEvent`，从不感知消费者（现有消费者三个：Gradio / evaluate.py / smoke_agent.py）。本次新增第四个 SSE 消费者，检测与 Agent 层零改动。新增 `runs_store.py`（持久化）+ `pipeline.py`（UI 无关编排）+ `api.py`（FastAPI），前端 `web/` 独立工程。事件**先落盘再推送**，使断连不丢结果，同一套代码服务记录模块。

**Tech Stack:** FastAPI 0.138.2 / uvicorn 0.49.0（已装）· Vite + React 19 + TypeScript · Tailwind · shadcn/ui · Vercel ai-elements（vendoring）· react-compare-slider

**Spec:** `docs/superpowers/specs/2026-08-13-frontend-rewrite-design.md`
**分支:** `frontend-rewrite`（基于 `82f681d`）

---

## Global Constraints

以下每一条都隐含在每个 Task 的要求里。

1. **零改动文件**：`agent.py`、`tools.py`、`run_inference.py`、`regions.py`、`config.py`、`evaluate.py`、`app.py`。任何 Task 都不得修改它们。
2. **现有测试必须全绿**：基线 `42 passed, 1 skipped`。测试命令一律 `.venv/bin/python -m pytest tests/ -q`（**不可裸跑 `pytest`**——会撞 `TruFor/test_docker` 的收集崩溃，这是历史遗留坑）。
3. **`app.py` 保留作回退**，端口 7860 不变。`pipeline.py` 与 `app.py::analyze()` 约 30 行重复是**有意接受的**（spec §3.1），审查时不得以 DRY 为由要求收敛。
4. **不安装任何第三方 Claude skill**（spec §7）。
5. **唯一强调色**：深墨蓝 `#1B3A5C`。语义色 `#2F6B4F` / `#8A6A1F` / `#8C3A32` 属数据编码，不计为第二强调色。
6. **十条 anti-slop 禁令**（spec §5.1）对所有前端 Task 生效：禁 teal、禁第二强调色、禁紫色渐变/白底紫胶囊、禁动画状态点、容器嵌套 ≤2、禁 Inter/Roboto/Arial/system-ui 作主字体、禁三列特性网格、禁 drop shadow、禁装饰动效、必须支持 `prefers-reduced-motion`。
7. **底色 `#FAFAF8`**（微暖 off-white，不得用纯白 `#FFF`）；圆角 4px；间距 4px 基准（4/8/12/16/24/32/48）；数字一律 `font-variant-numeric: tabular-nums`。
8. **图标只用 `lucide-react` 一个家族**。
9. **`runs/` 含真实业务单据，必须 gitignore**，且不得随任何提交入库。
10. **记录回放页必须显式标注「记录回放」**，不得让人误认为实时检测。
11. **网络约束（已实测）**：本机 Node 的 `fetch` 不走 `HTTPS_PROXY`，`npx ai-elements` / `npx shadcn add <url>` 会 `ECONNRESET`；`curl` 走代理正常。凡需从远程 registry 取组件，一律用 Task 5 记录的 curl vendoring 流程。
12. 复核模式沿用 `agent` / `direct` / `cv` 三种，语义与 `agent.py::review(mode=)` 一致，不增不减。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `runs_store.py` | 记录持久化：创建 run 目录、追加事件、写 meta、列表、读取、删除。不认识 HTTP，也不认识检测逻辑 |
| `pipeline.py` | UI 无关的检测编排：CV 推理 → 渲染两张图 → 组装 `AgentContext` → 转发 `review()`。只产出 `TraceEvent`，不落盘、不管 HTTP |
| `api.py` | FastAPI：把 `pipeline` 的事件流经 `runs_store` 落盘后转成 SSE；记录模块 REST；托管 `web/dist` |
| `start-web.sh` | 一键启动：预检 → 构建（若需）→ uvicorn |
| `web/src/lib/design-tokens.css` | §5 的全部设计令牌，单一真源 |
| `web/src/lib/sse.ts` | SSE 客户端：解析 `trace`/`done` 事件，暴露回调 |
| `web/src/lib/types.ts` | `TraceEvent` / `RunMeta` 的 TS 类型，与后端字段一一对应 |
| `web/src/components/ai-elements/*` | vendoring 的 Vercel 组件（只取需要的 9 个） |
| `web/src/components/ui/*` | shadcn 基础组件 |
| `web/src/components/CompareSlider.tsx` | 原图⇄热力图对比 |
| `web/src/components/VerdictCard.tsx` | 结论卡片（视觉中心） |
| `web/src/components/TraceView.tsx` | 轨迹渲染，TraceEvent → ai-elements 组件的分派 |
| `web/src/components/TechDetails.tsx` | 技术细节折叠区 |
| `web/src/pages/DetectPage.tsx` | 检测页 |
| `web/src/pages/RunsPage.tsx` | 记录列表 + 回放 |
| `web/DESIGN.md` | 美学约束与 token 来源记账，实施者与审查者共同的验收依据 |

**依赖方向**：`api.py` → `pipeline.py` + `runs_store.py` → 现有后端。`pipeline.py` 与 `runs_store.py` **互不依赖**（前者产出事件，后者存事件，由 `api.py` 撮合）。

---

## Task 1: `runs_store.py` — 记录持久化层

**Files:**
- Create: `runs_store.py`
- Create: `tests/test_runs_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 无（纯文件系统层）
- Produces:
  - `new_run_id() -> str` — 形如 `20260813-153012-a3f9`
  - `create_run(run_id: str, image_name: str, mode: str) -> pathlib.Path` — 建目录、写初始 meta，返回目录路径
  - `append_event(run_id: str, event_dict: dict, elapsed_ms: int) -> None` — 追加一行到 `events.jsonl`
  - `save_image(run_id: str, rel_path: str, img) -> str` — 存 PIL 图，返回**可用于 URL 的相对路径**
  - `finalize_run(run_id: str, **meta_updates) -> None` — 合并写入 meta.json
  - `list_runs() -> list[dict]` — 全部 meta，按 `created_at` 倒序
  - `read_run(run_id: str) -> dict` — `{"meta": {...}, "events": [...]}`，不存在时抛 `KeyError`
  - `delete_run(run_id: str) -> None` — 不存在时抛 `KeyError`
  - 模块级 `RUNS_DIR = pathlib.Path(os.getenv("DOCGUARD_RUNS_DIR", "runs"))`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_runs_store.py`：

```python
import json
import pytest
from PIL import Image

import runs_store


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_store, "RUNS_DIR", tmp_path / "runs")


def test_run_id_format_and_uniqueness():
    a, b = runs_store.new_run_id(), runs_store.new_run_id()
    assert a != b
    date, time, suffix = a.split("-")
    assert len(date) == 8 and len(time) == 6 and len(suffix) == 4


def test_create_append_finalize_roundtrip():
    rid = runs_store.new_run_id()
    runs_store.create_run(rid, "check.jpg", "agent")
    runs_store.append_event(rid, {"turn": 1, "type": "thought", "payload": {"thought": "看一眼"}}, 1200)
    runs_store.append_event(rid, {"turn": 2, "type": "verdict", "payload": {"text": "正常"}}, 45000)
    runs_store.finalize_run(rid, score=0.1138, conclusion="正常", risk="低",
                            duration_ms=45000, source="agent", infer_size="(1080, 1088)")

    got = runs_store.read_run(rid)
    assert got["meta"]["image_name"] == "check.jpg"
    assert got["meta"]["mode"] == "agent"
    assert got["meta"]["score"] == 0.1138
    assert got["meta"]["source"] == "agent"
    assert [e["type"] for e in got["events"]] == ["thought", "verdict"]
    assert [e["elapsed_ms"] for e in got["events"]] == [1200, 45000]   # 回放节奏依赖此字段


def test_save_image_returns_relative_path_and_writes_file():
    rid = runs_store.new_run_id()
    runs_store.create_run(rid, "x.jpg", "agent")
    rel = runs_store.save_image(rid, "img/t2-0.jpg", Image.new("RGB", (8, 8), "white"))
    assert rel == "img/t2-0.jpg"
    assert (runs_store.RUNS_DIR / rid / "img" / "t2-0.jpg").exists()


def test_list_runs_sorted_newest_first():
    for name in ("a.jpg", "b.jpg"):
        rid = runs_store.new_run_id()
        runs_store.create_run(rid, name, "cv")
        runs_store.finalize_run(rid, score=0.5)
    names = [m["image_name"] for m in runs_store.list_runs()]
    assert names == ["b.jpg", "a.jpg"]


def test_list_runs_empty_when_no_dir():
    assert runs_store.list_runs() == []


def test_read_and_delete_missing_run_raises():
    with pytest.raises(KeyError):
        runs_store.read_run("nope")
    with pytest.raises(KeyError):
        runs_store.delete_run("nope")


def test_delete_removes_everything():
    rid = runs_store.new_run_id()
    runs_store.create_run(rid, "x.jpg", "cv")
    runs_store.delete_run(rid)
    assert not (runs_store.RUNS_DIR / rid).exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_runs_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'runs_store'`

- [ ] **Step 3: 实现 `runs_store.py`**

```python
# runs_store.py — 检测记录持久化（文件系统，无数据库；规模为几十条）
import json
import os
import pathlib
import secrets
import shutil
from datetime import datetime

RUNS_DIR = pathlib.Path(os.getenv("DOCGUARD_RUNS_DIR", "runs"))


def new_run_id():
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def _dir(run_id):
    return RUNS_DIR / run_id


def create_run(run_id, image_name, mode):
    d = _dir(run_id)
    (d / "img").mkdir(parents=True, exist_ok=True)
    _write_meta(run_id, {"run_id": run_id, "image_name": image_name, "mode": mode,
                         "created_at": datetime.now().isoformat(timespec="seconds")})
    return d


def append_event(run_id, event_dict, elapsed_ms):
    """落盘先于推送：SSE 推之前必须先调用这里，断连才不会丢结果。"""
    line = json.dumps({**event_dict, "elapsed_ms": elapsed_ms}, ensure_ascii=False)
    with open(_dir(run_id) / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_image(run_id, rel_path, img):
    p = _dir(run_id) / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(p, quality=90)
    return rel_path


def finalize_run(run_id, **meta_updates):
    _write_meta(run_id, {**_read_meta(run_id), **meta_updates})


def list_runs():
    if not RUNS_DIR.is_dir():
        return []
    metas = []
    for d in RUNS_DIR.iterdir():
        f = d / "meta.json"
        if f.is_file():
            metas.append(json.loads(f.read_text(encoding="utf-8")))
    return sorted(metas, key=lambda m: m.get("created_at", ""), reverse=True)


def read_run(run_id):
    meta = _read_meta(run_id)
    events_file = _dir(run_id) / "events.jsonl"
    events = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if events_file.is_file() else []
    return {"meta": meta, "events": events}


def delete_run(run_id):
    d = _dir(run_id)
    if not d.is_dir():
        raise KeyError(run_id)
    shutil.rmtree(d)


def _write_meta(run_id, meta):
    (_dir(run_id) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_meta(run_id):
    f = _dir(run_id) / "meta.json"
    if not f.is_file():
        raise KeyError(run_id)
    return json.loads(f.read_text(encoding="utf-8"))
```

**注意**：`list_runs` 按 `created_at` 倒序，但同一秒创建的两条会并列。测试里两条记录的 `run_id` 随机后缀不同，`created_at` 可能相同——若测试不稳定，改用 `sorted(..., key=lambda m: (m.get("created_at",""), m.get("run_id","")), reverse=True)` 并同步更新测试断言。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_runs_store.py -q`
Expected: PASS，7 passed

- [ ] **Step 5: gitignore 保护**

在 `.gitignore` 的 `# Data` 段之后追加：

```
# 检测记录（含真实业务单据原图，严禁入库）
runs/

# 前端构建产物
web/node_modules/
web/dist/
```

- [ ] **Step 6: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `49 passed, 1 skipped`（42 基线 + 7 新增）

```bash
git add runs_store.py tests/test_runs_store.py .gitignore
git commit -m "feat: 检测记录持久化层 runs_store

事件逐条落盘（含 elapsed_ms 供回放还原节奏），文件系统存储不引入数据库。
runs/ 含真实业务单据已加入 gitignore。"
```

---

## Task 2: `pipeline.py` — UI 无关的检测编排

**Files:**
- Create: `pipeline.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `run_inference.run_single/select_device/load_model/TRUFOR_ROOT`、`regions.extract_candidate_regions`、`agent.AgentContext/review`、`tools.build_registry`
- Produces:
  - `render_heatmap(loc_map) -> PIL.Image`
  - `render_confidence(conf_map) -> PIL.Image`
  - `get_runtime() -> tuple[model, device, tools]` — 懒加载单例，进程内只加载一次模型
  - `run_detection(image_path, mode, *, model, device, tools, vlm=None) -> Iterator[tuple[str, object]]`
    产出 `("cv", cv_result_dict)` 一次，随后逐个产出 `("trace", TraceEvent)`。
    `cv_result_dict` 形如 `{"score": float, "infer_size": str, "heatmap": PIL.Image, "confidence": PIL.Image, "candidates": list, "original": PIL.Image}`。
    `vlm=None` 时不传该参数给 `review()`，即使用其默认的 `call_vlm`。

**为什么先产出 CV 结果再产出事件**：热力图与置信度图必须在 Agent 开始前就落盘并推给前端（否则用户要等完整 Agent 跑完才看到图）。这与 `app.py::analyze()` 的两段式 yield 语义一致。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_pipeline.py`：

```python
import numpy as np
import pytest
from PIL import Image

import pipeline
from agent import TraceEvent


class _FakeTool:
    name = "zoom_region"
    description = "放大"
    args_schema = {}

    def available(self):
        return True

    def run(self, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(text="放大结果", images=[], error=False)


VERDICT = '```json\n{"thought":"看完了","decision":"verdict",' \
          '"verdict":{"conclusion":"正常","risk":"低","regions":"无",' \
          '"basis":"字体一致","advice":"可正常入账"}}\n```'


def _fake_run_single(model, image_path, device, max_size=None):
    return {"score": 0.1138,
            "map": np.zeros((16, 16), dtype=np.float32),
            "conf": np.ones((16, 16), dtype=np.float32),
            "np++": None,
            "infer_size": (1080, 1088)}


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "doc.jpg"
    Image.new("RGB", (32, 32), "white").save(p)
    return str(p)


def test_yields_cv_first_then_traces(monkeypatch, img):
    monkeypatch.setattr(pipeline, "run_single", _fake_run_single)
    out = list(pipeline.run_detection(img, "agent", model=None, device="cpu",
                                      tools=[_FakeTool()], vlm=lambda m: VERDICT))
    kinds = [k for k, _ in out]
    assert kinds[0] == "cv"
    assert set(kinds[1:]) == {"trace"}

    cv = out[0][1]
    assert cv["score"] == 0.1138
    assert isinstance(cv["heatmap"], Image.Image)
    assert isinstance(cv["confidence"], Image.Image)
    assert isinstance(cv["original"], Image.Image)
    assert cv["infer_size"] == "(1080, 1088)"


def test_last_trace_is_always_verdict(monkeypatch, img):
    """继承 agent.review() 的不变量；前端结论卡片依赖它。"""
    monkeypatch.setattr(pipeline, "run_single", _fake_run_single)
    out = list(pipeline.run_detection(img, "agent", model=None, device="cpu",
                                      tools=[_FakeTool()], vlm=lambda m: VERDICT))
    traces = [e for k, e in out if k == "trace"]
    assert isinstance(traces[-1], TraceEvent)
    assert traces[-1].type == "verdict"


def test_cv_mode_needs_no_vlm(monkeypatch, img):
    monkeypatch.setattr(pipeline, "run_single", _fake_run_single)
    out = list(pipeline.run_detection(img, "cv", model=None, device="cpu", tools=[]))
    assert [e for k, e in out if k == "trace"][-1].type == "verdict"


def test_render_helpers_return_rgb_images():
    loc = np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8)
    assert pipeline.render_heatmap(loc).mode == "RGB"
    assert pipeline.render_confidence(loc).mode == "RGB"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: 实现 `pipeline.py`**

```python
# pipeline.py — UI 无关的检测编排：CV 首检 → 渲染 → Agent 复核事件流
#
# 与 app.py::analyze() 存在约 30 行重复，这是有意为之：app.py 是已验证的回退版本，
# 不因本次重写而改动（见 spec §3.1）。不要以 DRY 为由收敛。
import os

import numpy as np
from PIL import Image

import config
from agent import AgentContext, review
from regions import extract_candidate_regions
from run_inference import TRUFOR_ROOT, load_model, run_single, select_device
from tools import build_registry

_RUNTIME = None


def get_runtime():
    """懒加载单例：模型只在进程内加载一次（实测加载 4.9s）。"""
    global _RUNTIME
    if _RUNTIME is None:
        device = select_device()
        model = load_model(device, os.path.join(TRUFOR_ROOT, "pretrained_models", "trufor.pth.tar"))
        _RUNTIME = (model, device, build_registry())
    return _RUNTIME


def render_heatmap(loc_map):
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(loc_map)[:, :, :3] * 255).astype(np.uint8))


def render_confidence(conf_map):
    gray = (np.clip(conf_map, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(gray, mode="L").convert("RGB")


def run_detection(image_path, mode, *, model, device, tools, vlm=None):
    """先产出 ("cv", dict) 一次，再逐个产出 ("trace", TraceEvent)。"""
    result = run_single(model, image_path, device, max_size=config.MAX_SIZE)
    if device == "mps":
        import torch
        torch.mps.empty_cache()

    original = Image.open(image_path).convert("RGB")
    heatmap = render_heatmap(result["map"])
    confidence = render_confidence(result["conf"])
    infer_size = str(result["infer_size"])
    candidates = extract_candidate_regions(result["map"])

    yield "cv", {"score": result["score"], "infer_size": infer_size,
                 "heatmap": heatmap, "confidence": confidence,
                 "candidates": candidates, "original": original}

    ctx = AgentContext(image_path=image_path, original_img=original, heatmap_img=heatmap,
                       score=result["score"], infer_size=infer_size,
                       tiled="tiled" in infer_size, candidates=candidates)

    kwargs = {"vlm": vlm} if vlm is not None else {}
    for ev in review(ctx, tools, mode=mode, **kwargs):
        yield "trace", ev
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: PASS，4 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `53 passed, 1 skipped`

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline.py——UI 无关的检测编排

产出 (\"cv\", dict) + (\"trace\", TraceEvent) 两类事件，供 SSE 与未来消费者复用。
继承 review() 的不变量：最后一个 trace 恒为 verdict。
与 app.py 的约 30 行重复为有意接受（保回退版本完整性，见 spec 3.1）。"
```

---

## Task 3: `api.py` — SSE 检测端点

**Files:**
- Create: `api.py`
- Create: `tests/test_api_detect.py`

**Interfaces:**
- Consumes: `pipeline.run_detection/get_runtime`、`runs_store.*`
- Produces:
  - `app` — FastAPI 实例
  - `POST /api/detect`：multipart `file` + form `mode`（默认 `agent`），返回 `text/event-stream`
  - SSE 帧：`event: trace` + `data: {"run_id","turn","type","payload","elapsed_ms"}`；
    结束帧 `event: done` + `data: {"run_id","duration_ms"}`；
    失败帧 `event: error` + `data: {"message"}`
  - `serialize_event(run_id, ev, elapsed_ms) -> dict` — payload 中 PIL 图片替换为 URL 列表

**关键顺序**：每个事件必须 `runs_store.append_event(...)` **成功之后**才 `yield` SSE 帧。断连时已落盘的部分可由 Task 4 的 `/api/runs/{id}` 取回。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_api_detect.py`：

```python
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api
import pipeline
import runs_store
from agent import TraceEvent


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_store, "RUNS_DIR", tmp_path / "runs")


@pytest.fixture
def client():
    return TestClient(api.app)


def _upload():
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(buf, format="JPEG")
    return {"file": ("doc.jpg", buf.getvalue(), "image/jpeg")}


def _fake_detection(image_path, mode, **kw):
    yield "cv", {"score": 0.1138, "infer_size": "(1080, 1088)",
                 "heatmap": Image.new("RGB", (8, 8), "red"),
                 "confidence": Image.new("RGB", (8, 8), "gray"),
                 "candidates": [], "original": Image.new("RGB", (8, 8), "white")}
    yield "trace", TraceEvent(1, "thought", {"thought": "看一眼"})
    yield "trace", TraceEvent(2, "tool_result", {"text": "放大结果",
                                                 "images": [Image.new("RGB", (4, 4), "blue")]})
    yield "trace", TraceEvent(2, "verdict", {"verdict": {"conclusion": "正常", "risk": "低"},
                                             "text": "全文", "headline": "一句话", "detail": "依据",
                                             "source": "agent"})


def _parse_sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            out.append((ev, data))
    return out


def test_detect_streams_cv_then_traces_then_done(client, monkeypatch):
    monkeypatch.setattr(api, "get_runtime", lambda: (None, "cpu", []))
    monkeypatch.setattr(pipeline, "run_detection", _fake_detection)

    r = client.post("/api/detect", files=_upload(), data={"mode": "agent"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(r.text)
    kinds = [k for k, _ in frames]
    assert kinds[0] == "trace" and kinds[-1] == "done"
    types = [d["type"] for k, d in frames if k == "trace"]
    assert types[0] == "cv" and types[-1] == "verdict"


def test_images_become_urls_not_base64(client, monkeypatch):
    monkeypatch.setattr(api, "get_runtime", lambda: (None, "cpu", []))
    monkeypatch.setattr(pipeline, "run_detection", _fake_detection)

    frames = _parse_sse(client.post("/api/detect", files=_upload(), data={"mode": "agent"}).text)
    tool_result = next(d for k, d in frames if k == "trace" and d["type"] == "tool_result")
    urls = tool_result["payload"]["images"]
    assert urls and all(u.startswith("/api/runs/") for u in urls)
    assert "base64" not in json.dumps(tool_result)


def test_events_persisted_before_stream_ends(client, monkeypatch):
    """落盘先于推送：跑完后 runs/ 里必须已有完整轨迹。"""
    monkeypatch.setattr(api, "get_runtime", lambda: (None, "cpu", []))
    monkeypatch.setattr(pipeline, "run_detection", _fake_detection)

    frames = _parse_sse(client.post("/api/detect", files=_upload(), data={"mode": "agent"}).text)
    run_id = next(d["run_id"] for k, d in frames if k == "done")

    stored = runs_store.read_run(run_id)
    assert [e["type"] for e in stored["events"]] == ["cv", "thought", "tool_result", "verdict"]
    assert stored["meta"]["conclusion"] == "正常"
    assert stored["meta"]["risk"] == "低"
    assert stored["meta"]["score"] == 0.1138
    assert stored["meta"]["duration_ms"] >= 0
    assert all("elapsed_ms" in e for e in stored["events"])


def test_rejects_non_image(client, monkeypatch):
    monkeypatch.setattr(api, "get_runtime", lambda: (None, "cpu", []))
    r = client.post("/api/detect",
                    files={"file": ("a.txt", b"not an image", "text/plain")},
                    data={"mode": "agent"})
    assert r.status_code == 400
    assert "图片" in r.json()["detail"]


def test_rejects_unknown_mode(client, monkeypatch):
    monkeypatch.setattr(api, "get_runtime", lambda: (None, "cpu", []))
    r = client.post("/api/detect", files=_upload(), data={"mode": "hack"})
    assert r.status_code == 400
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_api_detect.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 3: 实现 `api.py`（本 Task 只做 detect 端点）**

```python
# api.py — FastAPI：检测 SSE + 记录 REST
import json
import os
import tempfile
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

import pipeline
import runs_store
from pipeline import get_runtime

register_heif_opener()                      # 评委 iPhone HEIC 直传

app = FastAPI(title="DocGuard API")

VALID_MODES = ("agent", "direct", "cv")


def serialize_event(run_id, ev, elapsed_ms):
    """payload 中的 PIL 图片落盘并替换为 URL——SSE 帧里不内联 base64。"""
    payload = dict(ev.payload)
    images = payload.get("images")
    if images:
        urls = []
        for i, img in enumerate(images):
            rel = runs_store.save_image(run_id, f"img/t{ev.turn}-{i}.jpg", img)
            urls.append(f"/api/runs/{run_id}/{rel}")
        payload["images"] = urls
    return {"run_id": run_id, "turn": ev.turn, "type": ev.type,
            "payload": payload, "elapsed_ms": elapsed_ms}


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/detect")
async def detect(file: UploadFile = File(...), mode: str = Form("agent")):
    if mode not in VALID_MODES:
        raise HTTPException(400, f"未知的复核模式：{mode}")

    raw = await file.read()
    suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(raw)
    tmp.close()
    try:
        Image.open(tmp.name).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "无法解析为图片，请上传 JPG/PNG/HEIC 格式的单据图片")

    run_id = runs_store.new_run_id()
    runs_store.create_run(run_id, file.filename or "unnamed", mode)

    def stream():
        started = time.monotonic()
        model, device, tools = get_runtime()
        meta_updates = {}
        try:
            for kind, item in pipeline.run_detection(tmp.name, mode, model=model,
                                                     device=device, tools=tools):
                elapsed = int((time.monotonic() - started) * 1000)
                if kind == "cv":
                    runs_store.save_image(run_id, "original.jpg", item["original"])
                    runs_store.save_image(run_id, "heatmap.jpg", item["heatmap"])
                    runs_store.save_image(run_id, "confidence.jpg", item["confidence"])
                    data = {"run_id": run_id, "turn": 0, "type": "cv", "elapsed_ms": elapsed,
                            "payload": {"score": item["score"], "infer_size": item["infer_size"],
                                        "candidates": item["candidates"],
                                        "original": f"/api/runs/{run_id}/original.jpg",
                                        "heatmap": f"/api/runs/{run_id}/heatmap.jpg",
                                        "confidence": f"/api/runs/{run_id}/confidence.jpg"}}
                    meta_updates.update(score=item["score"], infer_size=item["infer_size"])
                else:
                    data = serialize_event(run_id, item, elapsed)
                    if item.type == "verdict":
                        v = item.payload.get("verdict") or {}
                        meta_updates.update(conclusion=v.get("conclusion", ""),
                                            risk=v.get("risk", ""),
                                            source=item.payload.get("source", ""))
                runs_store.append_event(run_id, data, elapsed)     # 落盘先于推送
                yield _sse("trace", data)

            meta_updates["duration_ms"] = int((time.monotonic() - started) * 1000)
            runs_store.finalize_run(run_id, **meta_updates)
            yield _sse("done", {"run_id": run_id, "duration_ms": meta_updates["duration_ms"]})
        except Exception as e:                                     # noqa: BLE001 — 兜底转 SSE，不让连接裸断
            runs_store.finalize_run(run_id, error=str(e),
                                    duration_ms=int((time.monotonic() - started) * 1000))
            yield _sse("error", {"message": f"检测过程出错：{e}"})
        finally:
            os.unlink(tmp.name)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_api_detect.py -q`
Expected: PASS，5 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `58 passed, 1 skipped`

```bash
git add api.py tests/test_api_detect.py
git commit -m "feat: api.py 检测 SSE 端点

事件落盘先于推送——断连不丢已完成的检测。
payload 中的图片落盘换 URL，SSE 帧不内联 base64。
异常统一转 error 帧，不让连接裸断。"
```

---

## Task 4: `api.py` — 记录 REST + 静态托管

**Files:**
- Modify: `api.py`（追加路由，不改 Task 3 已有代码）
- Create: `tests/test_api_runs.py`

**Interfaces:**
- Consumes: `runs_store.list_runs/read_run/delete_run/RUNS_DIR`
- Produces:
  - `GET /api/runs` → `{"runs": [meta, ...]}`
  - `GET /api/runs/{run_id}` → `{"meta": {...}, "events": [...]}`；不存在 → 404
  - `GET /api/runs/{run_id}/{path:path}` → 文件；越界或不存在 → 404
  - `DELETE /api/runs/{run_id}` → `{"deleted": run_id}`；不存在 → 404
  - `GET /` 与 `GET /{full_path:path}` → 托管 `web/dist`（不存在时返回提示文案，不崩）

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_api_runs.py`：

```python
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api
import runs_store


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_store, "RUNS_DIR", tmp_path / "runs")


@pytest.fixture
def client():
    return TestClient(api.app)


def _seed(name="doc.jpg"):
    rid = runs_store.new_run_id()
    runs_store.create_run(rid, name, "agent")
    runs_store.append_event(rid, {"turn": 1, "type": "verdict", "payload": {"text": "正常"}}, 900)
    runs_store.save_image(rid, "original.jpg", Image.new("RGB", (8, 8), "white"))
    runs_store.finalize_run(rid, score=0.11, conclusion="正常", risk="低", duration_ms=900)
    return rid


def test_list_runs(client):
    _seed("a.jpg")
    _seed("b.jpg")
    body = client.get("/api/runs").json()
    assert len(body["runs"]) == 2
    assert {r["image_name"] for r in body["runs"]} == {"a.jpg", "b.jpg"}


def test_list_runs_empty(client):
    assert client.get("/api/runs").json() == {"runs": []}


def test_read_run_returns_meta_and_events(client):
    rid = _seed()
    body = client.get(f"/api/runs/{rid}").json()
    assert body["meta"]["conclusion"] == "正常"
    assert body["events"][0]["elapsed_ms"] == 900      # 回放节奏依赖


def test_read_missing_run_404(client):
    assert client.get("/api/runs/nope").status_code == 404


def test_serve_run_file(client):
    rid = _seed()
    r = client.get(f"/api/runs/{rid}/original.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_path_traversal_blocked(client):
    rid = _seed()
    assert client.get(f"/api/runs/{rid}/../../../etc/passwd").status_code == 404


def test_delete_run(client):
    rid = _seed()
    assert client.delete(f"/api/runs/{rid}").json() == {"deleted": rid}
    assert client.get(f"/api/runs/{rid}").status_code == 404
    assert client.delete(f"/api/runs/{rid}").status_code == 404


def test_root_without_build_does_not_crash(client):
    r = client.get("/")
    assert r.status_code in (200, 404)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_api_runs.py -q`
Expected: FAIL — 404 / AttributeError（路由未定义）

- [ ] **Step 3: 追加路由到 `api.py` 末尾**

```python
import pathlib

from fastapi.responses import FileResponse, HTMLResponse

WEB_DIST = pathlib.Path(__file__).parent / "web" / "dist"


@app.get("/api/runs")
def list_runs():
    return {"runs": runs_store.list_runs()}


@app.get("/api/runs/{run_id}")
def read_run(run_id: str):
    try:
        return runs_store.read_run(run_id)
    except KeyError:
        raise HTTPException(404, f"记录不存在：{run_id}")


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    try:
        runs_store.delete_run(run_id)
    except KeyError:
        raise HTTPException(404, f"记录不存在：{run_id}")
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}/{rel_path:path}")
def run_file(run_id: str, rel_path: str):
    base = (runs_store.RUNS_DIR / run_id).resolve()
    target = (base / rel_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():   # 目录穿越防护
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


@app.get("/")
@app.get("/{full_path:path}")
def spa(full_path: str = ""):
    """托管前端构建产物；未构建时给出可操作提示而不是 500。"""
    if full_path.startswith("api/"):
        raise HTTPException(404, "未知的 API 路径")
    candidate = (WEB_DIST / full_path).resolve() if full_path else None
    if candidate and str(candidate).startswith(str(WEB_DIST.resolve())) and candidate.is_file():
        return FileResponse(candidate)
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<h1>前端尚未构建</h1><p>请先执行 <code>cd web &amp;&amp; npm run build</code></p>",
                        status_code=200)
```

**路由顺序要点**：`/api/runs/{run_id}/{rel_path:path}` 必须写在 `/api/runs/{run_id}` 之后；catch-all 的 `/{full_path:path}` 必须在文件末尾，否则会吞掉所有 API 路由。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_api_runs.py -q`
Expected: PASS，8 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `66 passed, 1 skipped`

```bash
git add api.py tests/test_api_runs.py
git commit -m "feat: 记录 REST 端点 + 前端静态托管

含目录穿越防护；未构建前端时返回可操作提示而非 500。"
```

---

## Task 5: 前端工程脚手架 + 设计令牌

**Files:**
- Create: `web/`（Vite 工程）
- Create: `web/src/lib/design-tokens.css`
- Create: `web/src/lib/types.ts`
- Create: `web/DESIGN.md`
- Create: `scripts/vendor_ai_elements.py`
- Create: `start-web.sh`

**Interfaces:**
- Produces：可运行的 `npm run dev`；`web/src/components/ai-elements/*` 已就位；全部设计令牌以 CSS 变量暴露

- [ ] **Step 1: 创建 Vite 工程**

```bash
cd /Users/jintianzhang/Desktop/doc-tamper-detection
npm create vite@latest web -- --template react-ts
cd web && npm install
npm install tailwindcss @tailwindcss/vite react-compare-slider lucide-react clsx tailwind-merge
```

Expected: `web/package.json` 生成，`npm install` 无报错。

- [ ] **Step 2: 配置 Tailwind + 后端代理**

覆盖 `web/vite.config.ts`：

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
```

- [ ] **Step 3: 写设计令牌（spec §5 的单一真源）**

创建 `web/src/lib/design-tokens.css`：

```css
/* DocGuard 设计令牌 — 唯一真源。任何组件不得硬编码颜色/间距/圆角。
   remix: Linear(中性色/间距纪律) × Stripe(强调色/金融语义) — 见 web/DESIGN.md */
:root {
  /* 中性 —— 底色为微暖 off-white，禁用纯白 #FFF */
  --bg:          #FAFAF8;
  --surface:     #FFFFFF;   /* 仅用于内容卡面，不作页面底色 */
  --border:      #E4E3DE;
  --border-strong:#CFCEC7;
  --text:        #1C1C1A;
  --text-muted:  #6B6B66;

  /* 唯一强调色 —— 全站只有这一个，不得引入第二个 */
  --accent:      #1B3A5C;
  --accent-weak: #E8EDF3;

  /* 语义色（数据编码，非品牌强调色） */
  --ok:      #2F6B4F;
  --warn:    #8A6A1F;
  --danger:  #8C3A32;
  --ok-bg:   #EDF3EF;
  --warn-bg: #F5F0E4;
  --danger-bg:#F6EBE9;

  /* 间距 4px 基准 */
  --s1: 4px;  --s2: 8px;  --s3: 12px; --s4: 16px;
  --s6: 24px; --s8: 32px; --s12: 48px;

  --radius: 4px;

  --font-cn: 'HarmonyOS Sans SC', sans-serif;
  --font-en: 'IBM Plex Sans', sans-serif;
  --font-mono: 'IBM Plex Mono', monospace;
}

html { background: var(--bg); color: var(--text); }
body { font-family: var(--font-cn), var(--font-en); }

/* 数字一律等宽对齐——分数/坐标/耗时要能上下对齐 */
.num, table td, table th { font-variant-numeric: tabular-nums; font-family: var(--font-mono); }

/* 层次一律靠 border 或色调差，全站禁用 drop shadow */
* { box-shadow: none !important; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

在 `web/src/main.tsx` 顶部加入 `import './lib/design-tokens.css'`。

- [ ] **Step 4: 写共享类型（与后端字段一一对应）**

创建 `web/src/lib/types.ts`：

```ts
export type TraceType =
  | 'cv' | 'stage' | 'thought' | 'tool_call' | 'tool_result' | 'verdict' | 'fallback'

export interface TraceEvent {
  run_id: string
  turn: number
  type: TraceType
  elapsed_ms: number
  payload: Record<string, unknown>
}

export interface CvPayload {
  score: number
  infer_size: string
  candidates: { id: number; bbox: number[]; area_frac: number; mean_score: number }[]
  original: string
  heatmap: string
  confidence: string
}

export interface VerdictPayload {
  verdict: { conclusion: string; risk: string; regions?: string; basis?: string; advice?: string } | null
  text: string
  headline?: string
  detail?: string
  source: string
}

export interface RunMeta {
  run_id: string
  image_name: string
  mode: 'agent' | 'direct' | 'cv'
  created_at: string
  score?: number
  infer_size?: string
  conclusion?: string
  risk?: string
  source?: string
  duration_ms?: number
  error?: string
}
```

- [ ] **Step 5: vendoring AI Elements 组件**

⚠️ 本机 Node 的 `fetch` 不走代理，`npx ai-elements` 会 `ECONNRESET`（已实测）；`curl` 正常。用脚本绕开 CLI。

创建 `scripts/vendor_ai_elements.py`：

```python
# scripts/vendor_ai_elements.py — 从 registry JSON 提取需要的组件源码
# 用法：curl -s -o /tmp/ai-elements-registry.json https://elements.ai-sdk.dev/api/registry/all.json
#       .venv/bin/python scripts/vendor_ai_elements.py /tmp/ai-elements-registry.json
import json
import pathlib
import sys

WANTED = ["reasoning", "chain-of-thought", "tool", "task", "message",
          "image", "conversation", "confirmation", "shimmer"]
OUT = pathlib.Path("web/src/components/ai-elements")


def main(registry_path):
    data = json.loads(pathlib.Path(registry_path).read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for f in data["files"]:
        stem = f["path"].split("/")[-1].replace(".tsx", "")
        if stem in WANTED:
            (OUT / f"{stem}.tsx").write_text(f["content"], encoding="utf-8")
            written.append(stem)
    missing = sorted(set(WANTED) - set(written))
    print(f"已写入 {len(written)} 个组件到 {OUT}")
    if missing:
        print(f"⚠️ registry 中未找到：{missing}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
```

执行：

```bash
cd /Users/jintianzhang/Desktop/doc-tamper-detection
curl -s --max-time 60 -o /tmp/ai-elements-registry.json https://elements.ai-sdk.dev/api/registry/all.json
.venv/bin/python scripts/vendor_ai_elements.py /tmp/ai-elements-registry.json
```

Expected: `已写入 9 个组件到 web/src/components/ai-elements`

**只装这 9 个组件实际用到的 npm 依赖，不要装 registry 里 `all` 声明的 18 个**（`@xyflow/react`、`media-chrome`、`@rive-app/react-webgl2` 等是 canvas/音频/动画组件的依赖，我们用不到）。逐个打开 vendoring 出来的 `.tsx` 看其 `import`，只补缺失的包。预期需要：`motion`、`nanoid`、`@radix-ui/react-use-controllable-state`、`use-stick-to-bottom`。缺哪个装哪个，装完 `npm run build` 必须零报错。

- [ ] **Step 6: 补齐 shadcn 基础组件**

vendoring 出的组件会 import `@/components/ui/*`。逐个打开确认实际用到哪些，只补这些（预期：`badge` `button` `collapsible` `separator` `tooltip` `card` `scroll-area`）。同样受 Node 代理问题影响，`npx shadcn add` 若失败，从 `https://ui.shadcn.com/r/styles/new-york/<name>.json` 用 `curl` 取 JSON 后手动落盘到 `web/src/components/ui/`。

创建 `web/src/lib/utils.ts`（shadcn 组件依赖）：

```ts
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 7: 写 `web/DESIGN.md`（验收依据）**

内容必须包含：spec §5 的完整令牌表、§5.1 的十条禁令逐条列出、token 来源记账（Linear 侧 vs Stripe 侧的实际计数）。这份文件是 Task 13 自审时逐条打勾的清单，也是审查者判断"美学是否达标"的唯一客观依据。

- [ ] **Step 8: 写 `start-web.sh`**

```bash
#!/usr/bin/env bash
# start-web.sh — 新版前端一键启动（Gradio 回退版仍用 ./start.sh，端口 7860）
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "缺少 .env（需 DASHSCOPE_API_KEY）"; exit 1; }
grep -qE '^DASHSCOPE_API_KEY=..+' .env || { echo ".env 缺少有效的 DASHSCOPE_API_KEY"; exit 1; }
[ -f TruFor/TruFor_train_test/pretrained_models/trufor.pth.tar ] || { echo "缺少 TruFor 权重"; exit 1; }
command -v node >/dev/null || { echo "缺少 node（需 v20+）"; exit 1; }
[ -d web/dist ] || { echo "前端未构建，正在构建…"; (cd web && npm run build); }
echo "启动 DocGuard Web（http://localhost:8000）"
exec .venv/bin/python -u -m uvicorn api:app --host 0.0.0.0 --port 8000
```

`chmod +x start-web.sh`。

注意用了 `python -u`：`start.sh` 缺这个参数导致非交互启动时日志全卡在缓冲区（已知问题），新脚本不重复该坑。

- [ ] **Step 9: 验证并提交**

```bash
cd web && npm run build && cd ..
.venv/bin/python -m pytest tests/ -q
```
Expected: 构建成功产出 `web/dist/`；测试 `66 passed, 1 skipped`

```bash
git add web scripts/vendor_ai_elements.py start-web.sh
git commit -m "feat: 前端工程脚手架 + 设计令牌 + AI Elements vendoring

Node fetch 不走代理导致 npx ai-elements ECONNRESET，改用 curl+脚本提取组件源码。
只 vendoring 需要的 9 个组件，不装 all 包的 18 个依赖。
start-web.sh 带 python -u，不重复 start.sh 的日志缓冲坑。"
```

---

## Task 6: SSE 客户端与检测页骨架

**Files:**
- Create: `web/src/lib/sse.ts`
- Create: `web/src/pages/DetectPage.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `types.ts` 的 `TraceEvent`
- Produces:
  - `runDetection(file: File, mode: string, handlers: {onTrace, onDone, onError}): () => void`
    返回一个中止函数；内部用 `fetch` + `ReadableStream` 手工解析 SSE（`EventSource` 不支持 POST 与 multipart）

- [ ] **Step 1: 实现 SSE 客户端**

创建 `web/src/lib/sse.ts`：

```ts
import type { TraceEvent } from './types'

interface Handlers {
  onTrace: (e: TraceEvent) => void
  onDone: (d: { run_id: string; duration_ms: number }) => void
  onError: (msg: string) => void
}

/** EventSource 不支持 POST/multipart，故手工解析 SSE 帧。返回中止函数。 */
export function runDetection(file: File, mode: string, h: Handlers): () => void {
  const ctrl = new AbortController()
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)

  ;(async () => {
    try {
      const resp = await fetch('/api/detect', { method: 'POST', body: form, signal: ctrl.signal })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
        h.onError(body.detail ?? `HTTP ${resp.status}`)
        return
      }
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() ?? ''
        for (const block of blocks) {
          let ev = '', data = ''
          for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) ev = line.slice(7)
            else if (line.startsWith('data: ')) data = line.slice(6)
          }
          if (!ev || !data) continue
          const parsed = JSON.parse(data)
          if (ev === 'trace') h.onTrace(parsed)
          else if (ev === 'done') h.onDone(parsed)
          else if (ev === 'error') h.onError(parsed.message)
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        h.onError('连接中断，已完成的部分可在「记录」页找回')
      }
    }
  })()

  return () => ctrl.abort()
}
```

**"连接中断"的文案不是随口写的**：后端事件落盘先于推送，所以断连时已产生的事件确实在 `runs/` 里，用户去记录页能找回。文案与真实行为必须一致。

- [ ] **Step 2: 检测页骨架**

创建 `web/src/pages/DetectPage.tsx`，实现：拖拽/点击上传 → 模式选择（三种）→「开始检测」→ 状态机（idle / running / done / error）→ 事件累积进 `TraceEvent[]`。

布局按 spec §6：左栏上传与图片区，右栏结论卡片 + 轨迹，底部技术细节折叠。**不得用三列网格**（禁令 7）。上传后立即读取图片尺寸，若长边 > 1792 显示"大图需切片推理，约需 1-2 分钟"，否则"约需 10 秒"。

`web/src/App.tsx` 改为两个页签：「检测」与「记录」，用 `useState` 切换即可（不引入路由库，YAGNI）。

- [ ] **Step 3: 手工验证**

```bash
./start-web.sh &          # 终端 A
cd web && npm run dev     # 终端 B，访问 http://localhost:5173
```
用 `example-images/微信圖片_20260629180819_55_237.jpg`（1080×1088，CV 约 4 秒）跑「仅 CV 检测」模式，确认：上传→提示"约需 10 秒"→事件流到达→无控制台报错。

- [ ] **Step 4: 提交**

```bash
git add web/src
git commit -m "feat: SSE 客户端 + 检测页骨架"
```

---

## Task 7: 轨迹渲染（TraceEvent → AI Elements）

**Files:**
- Create: `web/src/components/TraceView.tsx`
- Modify: `web/src/pages/DetectPage.tsx`

**Interfaces:**
- Consumes: `TraceEvent[]`、`web/src/components/ai-elements/*`
- Produces: `<TraceView events={TraceEvent[]} />`

- [ ] **Step 1: 实现分派**

映射关系（spec §6.1）：

| `type` | 组件 | 渲染内容 |
|---|---|---|
| `stage` | `Task` + `Shimmer` | 阶段名 + 预期耗时，检测中显示占位 |
| `thought` | `Reasoning` | `payload.thought`，标题「第 N 轮 · 思考」 |
| `tool_call` | `Tool` | `payload.tool` + `payload.args` |
| `tool_result` | `Tool` + `Image` | `payload.text` + `payload.images`（URL 数组，直接 `<img src>`） |
| `fallback` | `Confirmation` | `payload.reason` 为正文；`payload.detail` 收进「技术详情」折叠，**默认收起** |
| `verdict` | 交给 `VerdictCard`（Task 8） | 不在 TraceView 内渲染 |

轨迹条目流入用 staggered `animation-delay`，单条 ≤160ms（spec §5.2）。`prefers-reduced-motion` 下不生效（已由令牌文件的媒体查询兜底）。

- [ ] **Step 2: 手工验证降级路径**

临时把 `.env` 的 `DASHSCOPE_API_KEY` 改成无效值，跑「Agent 复核」模式，确认：出现 `fallback` 气泡、文案是友好中文、原始异常在折叠块里**默认收起**、最终仍出结论（CV-only）。验证后立刻改回。

**这是坑 #8 的回归点**——Gradio 版曾因未设 `status:"done"` 导致折叠块默认展开，React 版需自行确保初始 collapsed。

- [ ] **Step 3: 提交**

```bash
git add web/src/components/TraceView.tsx web/src/pages/DetectPage.tsx
git commit -m "feat: Agent 轨迹渲染——TraceEvent 分派到 AI Elements 组件"
```

---

## Task 8: 结论卡片 + 对比滑块 + 技术细节折叠

**Files:**
- Create: `web/src/components/VerdictCard.tsx`
- Create: `web/src/components/CompareSlider.tsx`
- Create: `web/src/components/TechDetails.tsx`
- Modify: `web/src/pages/DetectPage.tsx`

**Interfaces:**
- Produces:
  - `<VerdictCard payload={VerdictPayload} />` — 一句话结论（含风险与建议）+「为什么这么判」折叠（默认收起）
  - `<CompareSlider original={string} heatmap={string} />` — 用 `react-compare-slider`
  - `<TechDetails cv={CvPayload} durationMs={number} />` — 置信度图 + 分数 + 推理尺寸 + 候选区表格，**默认收起**

- [ ] **Step 1: 结论卡片**

风险等级映射到语义色：`低 → var(--ok)`、`中 → var(--warn)`、`高 → var(--danger)`。**状态指示只能用静态字形 + 文字，禁止动画点/脉冲圆**（禁令 4）。

`payload.headline` 存在时用它，否则回退到 `payload.text` 整段渲染（direct/cv-only 链路无结构化字段——这与后端 `app.py` 的分支逻辑一致）。

- [ ] **Step 2: 对比滑块**

`react-compare-slider` 承载原图与热力图。两图尺寸不同（热力图按 `loc_map` 分辨率渲染），需 `object-fit: contain` 并统一容器宽高比，否则拖动时会错位。

- [ ] **Step 3: 技术细节折叠**

候选区表格列：`#id` / `bbox` / `面积占比` / `区域均分`。数字列必须 `tabular-nums`（令牌文件的 `.num` 类）。

- [ ] **Step 4: 手工验证**

用 `55_237.jpg` 跑 Agent 模式，对照已知底数确认渲染正确：CV 分数 **0.1138**、**4 个候选区**、区域均分 **0.814 / 0.759 / 0.727 / 0.706**。

- [ ] **Step 5: 提交**

```bash
git add web/src/components web/src/pages
git commit -m "feat: 结论卡片 + 原图热力图对比滑块 + 技术细节折叠"
```

---

## Task 9: 记录页 — 列表与回放

**Files:**
- Create: `web/src/pages/RunsPage.tsx`
- Create: `web/src/components/ReplayView.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/runs`、`GET /api/runs/{id}`、`DELETE /api/runs/{id}`
- Produces: 列表视图 + 回放视图

- [ ] **Step 1: 列表**

列：缩略图（`/api/runs/{id}/original.jpg`）/ 文件名 / 时间 / 模式 / CV 分数 / 判定 / 风险 / 耗时。支持按分数与时间排序、按判定筛选、单条删除。

**禁止用等宽卡片网格**（禁令：数据异构时不得用统一宽高比的卡片网格）——用表格。

- [ ] **Step 2: 回放**

点击行 → 拉 `/api/runs/{id}` → 按 `elapsed_ms` 的**相对间隔**依次渲染事件，还原真实节奏（CV 等 80 秒、思考 30 秒、工具返回瞬间的差异）。提供「跳过动画直接看全部」按钮。

⚠️ **页面顶部必须常驻显著标识「记录回放 · 非实时检测」**（spec §11 第 3 条）。这是自保：现场若让评委误以为实时，被戳穿的代价远大于收益。

- [ ] **Step 3: 手工验证**

先跑 2-3 次检测积累记录，再打开记录页确认：列表有数据、缩略图能显示、回放节奏与原始耗时一致、「记录回放」标识明显、删除后列表即时更新。

- [ ] **Step 4: 提交**

```bash
git add web/src
git commit -m "feat: 记录页——列表 + 按原始节奏回放

回放页常驻「记录回放·非实时检测」标识，不得让人误认为实时。"
```

---

## Task 10: 字体自托管与子集化

**Files:**
- Create: `web/public/fonts/`
- Modify: `web/src/lib/design-tokens.css`

**Interfaces:**
- Produces: `@font-face` 声明，字体文件本地托管

- [ ] **Step 1: 取字体**

HarmonyOS Sans SC（开源免费商用）与 IBM Plex Sans/Mono（OFL）。用 `curl` 下载（Node 工具链的代理问题不影响 curl）。**不得走 CDN**——演示机可能无外网。

- [ ] **Step 2: 子集化**

中文全字重 3-8MB，直接加载会拖垮首屏。用 `fonttools` 子集化：

```bash
.venv/bin/pip install fonttools brotli
.venv/bin/pyftsubset HarmonyOS_Sans_SC_Regular.ttf \
  --text-file=<(cat web/src/**/*.tsx | grep -oP '[\x{4e00}-\x{9fff}]' | sort -u | tr -d '\n') \
  --flavor=woff2 --output-file=web/public/fonts/harmonyos-sc-subset.woff2
```

子集化后应在 200KB 以内。**注意**：子集只覆盖当前界面文案；VLM 输出的中文是动态的，必须保留一个兜底字重或在 `font-family` 末尾附系统中文字体作 fallback（这不违反禁令 6——禁的是系统字体作**主字体**，作 fallback 是必要的）。

- [ ] **Step 3: 声明与验证**

在 `design-tokens.css` 顶部加 `@font-face`。验证：断网状态下打开页面，字体仍正确渲染；DevTools Network 面板无 CDN 请求。

- [ ] **Step 4: 提交**

```bash
git add web/public/fonts web/src/lib/design-tokens.css
git commit -m "feat: 字体自托管与子集化——断网可用，首屏不被拖垮"
```

---

## Task 11: 美学自审与截图核对

**Files:**
- Modify: `web/DESIGN.md`（补 token 来源记账与自审结论）
- Create: `docs/screenshots/`（三态截图）

- [ ] **Step 1: 逐条自审十禁令**

对照 spec §5.1，逐条检查并在 `web/DESIGN.md` 记录结论（通过/不通过 + 证据）：

1. 无 teal（`#16d5e6` 及邻近）→ `grep -ri "16d5e6\|teal" web/src`
2. 无第二强调色 → `grep -o "#[0-9A-Fa-f]\{6\}" web/src/**/*.{css,tsx} | sort -u` 结果必须全部在令牌表内
3. 无紫色渐变/白底紫胶囊 → `grep -ri "purple\|violet\|gradient" web/src`
4. 无动画状态点 → `grep -ri "animate-pulse\|animate-ping" web/src`
5. 容器嵌套 ≤2 → 人工检查三处主要区域
6. 主字体非 Inter/Roboto/Arial/system-ui → 检查 `--font-cn` / `--font-en` 实际值
7. 无三列特性网格 → `grep -ri "grid-cols-3" web/src`
8. 无 drop shadow → `grep -ri "shadow-" web/src`（令牌文件已全局禁用，此处查是否有 `!important` 覆盖）
9. 无装饰动效 → 人工确认动效只在轨迹流入与结论出现两处
10. `prefers-reduced-motion` 生效 → DevTools 开启 reduce motion 后确认动画停止

- [ ] **Step 2: 三态截图**

用 playwright 对三个状态截图存入 `docs/screenshots/`：
- `01-idle.png` 初始态
- `02-running.png` 检测中（轨迹流式）
- `03-verdict.png` 结论态，**「为什么这么判」折叠块必须处于收起状态**（坑 #8 回归点）

- [ ] **Step 3: token 来源记账**

按 remix 方法要求，在 `web/DESIGN.md` 记录实际 token 计数与占比（预估 Linear 侧 ≈45% / Stripe 侧 ≈55%）。

- [ ] **Step 4: 全量回归 + 提交**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `66 passed, 1 skipped`

```bash
git add web/DESIGN.md docs/screenshots
git commit -m "docs: 美学十禁令逐条自审 + 三态截图存档"
```

---

## Task 12: 端到端验收与文档更新

**Files:**
- Modify: `README.md`
- Modify: `docs/dev-log.md`

- [ ] **Step 1: 真机端到端**

`./start-web.sh` 启动，逐项确认：

| 检查项 | 判据 |
|---|---|
| 小图 Agent 模式 | `55_237.jpg` 全流程，分数 0.1138，4 候选区，轨迹完整，结论卡片正常 |
| 大图切片 | `check.jpg` 分数 0.2347，等待期有"约需 1-2 分钟"提示与 Shimmer 占位 |
| 三种模式 | agent / direct / cv 均能出结论 |
| HEIC 上传 | iPhone HEIC 图片能正常解析 |
| 断连恢复 | 检测中途关闭页面，记录页能找到该 run 的已完成部分 |
| 非法上传 | 上传 `.txt` 得到 400 与明确中文提示，页面不跳转 |
| 回退版本 | `./start.sh` 仍能在 7860 正常工作 |

- [ ] **Step 2: 更新 README**

补「两种启动方式」小节：`./start.sh`（Gradio 回退版，7860）与 `./start-web.sh`（新版，8000），说明各自定位。

- [ ] **Step 3: dev-log 词条**

记录：Node fetch 不走代理的坑与 curl vendoring 解法（**这是本项目第 9 个已知坑，须写入**）、只 vendoring 9 个组件而非 all 包的原因、字体子集化的动态中文 fallback 处理。

- [ ] **Step 4: 最终回归 + 提交**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `66 passed, 1 skipped`

```bash
git add README.md docs/dev-log.md
git commit -m "docs: README 双启动方式 + dev-log 补录前端重写的三个坑"
```

---

## 自审记录（写计划时执行）

**1. Spec 覆盖检查**

| Spec 章节 | 对应 Task |
|---|---|
| §3 架构（pipeline/api/web 三层） | Task 2 / 3-4 / 5-10 |
| §3.1 有意重复 | Task 2 代码注释 + Global Constraints 3 |
| §4.1 SSE 协议 | Task 3 |
| §4.2 落盘先于推送 | Task 1（`append_event`）+ Task 3（调用顺序）+ Task 3 测试 |
| §4.3 记录目录结构与 `elapsed_ms` | Task 1 |
| §4.4 API 清单 | Task 3（detect）+ Task 4（其余四个） |
| §5 美学令牌与 remix 仲裁 | Task 5（令牌）+ Task 10（字体）+ Task 11（自审记账） |
| §5.1 十条禁令 | Global Constraints 6 + Task 11 逐条核查 |
| §5.2 动效预算 | Task 7（轨迹）+ Task 8（结论卡片） |
| §6 界面结构与渐进式披露 | Task 6 / 7 / 8 |
| §6.1 组件映射与 npm 依赖 | Task 5 / 7 |
| §6.2 记录页与回放 | Task 9 |
| §6.3 等待期反馈 | Task 6（尺寸提示）+ Task 7（Shimmer） |
| §7 供应链决策 | Global Constraints 4 + Task 5 vendoring 流程 |
| §8 错误处理与降级 | Task 3（error 帧）+ Task 6（连接中断文案）+ Task 7（fallback 渲染）+ Task 12（验收表） |
| §9 测试策略 | 各 Task 的测试步骤 + Task 11 截图 + Task 12 端到端 |
| §10 交付与启动 | Task 5（`start-web.sh`）+ Task 1（gitignore） |
| §11 已知取舍 | Task 2 注释 / Task 10 字体 / Task 9 回放标识 / Task 12 验收 |

无遗漏。

**2. 占位符扫描**：无 TBD/TODO；每个改代码的步骤都给了完整代码或明确的可执行命令。Task 6/7/8/9 的 React 组件给的是渲染契约与约束而非逐行代码——这是有意的：组件实现细节由 AI Elements 的实际 API 决定，vendoring 后才能确知，硬写会变成猜测。每个此类 Task 都配了可验证的手工验收判据。

**3. 类型一致性**：`runs_store` 的函数名在 Task 1 定义、Task 3/4 引用一致；`run_detection` 的 `("cv", dict)` / `("trace", TraceEvent)` 二元组契约在 Task 2 定义、Task 3 消费一致；`TraceEvent` 的 TS 类型（Task 5）与后端 `serialize_event` 产出（Task 3）字段一一对应（`run_id`/`turn`/`type`/`payload`/`elapsed_ms`）。

**4. 测试基线递增**：42（现有）→ 49（+7 Task 1）→ 53（+4 Task 2）→ 58（+5 Task 3）→ 66（+8 Task 4）→ 后续 Task 不新增 Python 测试，保持 66。
