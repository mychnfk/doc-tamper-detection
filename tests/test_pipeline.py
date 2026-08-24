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
