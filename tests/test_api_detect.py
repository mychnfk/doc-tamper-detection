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
    # 非上下文管理器用法：不触发 lifespan，故不会加载真实模型
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
