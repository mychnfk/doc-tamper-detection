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


def _seed(name="doc.jpg", rid=None):
    rid = rid or runs_store.new_run_id()
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
    """必须用 %2e%2e%2f：httpx 会按 RFC 3986 把裸 `..` 在客户端折叠掉，那样根本测不到服务端。"""
    rid = _seed()
    assert client.get(f"/api/runs/{rid}/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd").status_code == 404


def test_sibling_run_with_shared_prefix_blocked(client):
    """字符串前缀判断会漏掉这一条：abc 的请求不得读到 abcdef 的原图。"""
    _seed("victim.jpg", rid="abcdef")
    _seed("attacker.jpg", rid="abc")
    assert client.get("/api/runs/abc/%2e%2e%2fabcdef/original.jpg").status_code == 404


def test_safe_child_rejects_escapes(tmp_path):
    """直接锁死自研逻辑——不依赖 httpx/starlette 的 URL 规范化行为。"""
    base = tmp_path / "abc"
    (base / "img").mkdir(parents=True)
    (base / "img" / "ok.jpg").write_bytes(b"x")
    sibling = tmp_path / "abcdef"
    sibling.mkdir()
    (sibling / "secret.jpg").write_bytes(b"x")

    assert api._safe_child(base, "img/ok.jpg") is not None
    assert api._safe_child(base, "../abcdef/secret.jpg") is None      # 共享前缀的兄弟目录
    assert api._safe_child(base, "../../etc/passwd") is None
    assert api._safe_child(base, "img") is None                       # 目录不是文件
    assert api._safe_child(base, "missing.jpg") is None


def test_delete_run(client):
    rid = _seed()
    assert client.delete(f"/api/runs/{rid}").json() == {"deleted": rid}
    assert client.get(f"/api/runs/{rid}").status_code == 404
    assert client.delete(f"/api/runs/{rid}").status_code == 404


def test_root_without_build_does_not_crash(client):
    r = client.get("/")
    assert r.status_code in (200, 404)
