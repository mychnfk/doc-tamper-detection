import json
import time

import pytest
from fastapi.testclient import TestClient

import api
import runs_store


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_store, "RUNS_DIR", tmp_path / "runs")


@pytest.fixture
def client():
    return TestClient(api.app)


def _create_run(id_="test1", filename="doc.jpg", mode="agent", **meta):
    runs_store.create_run(id_, filename, mode)
    if meta:
        runs_store.finalize_run(id_, **meta)


def test_list_runs_empty(client):
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json()["runs"] == []


def test_list_runs_sorted_newest_first(client):
    now = int(time.time())
    _create_run("r1", created_at=now - 10)
    _create_run("r2", created_at=now)
    _create_run("r3", created_at=now - 5)
    r = client.get("/api/runs")
    ids = [x["run_id"] for x in r.json()["runs"]]
    assert ids == ["r2", "r3", "r1"]


def test_get_run_with_events(client):
    _create_run("r1", score=0.5, conclusion="正常")
    runs_store.append_event("r1", {"type": "cv", "payload": {"score": 0.5}}, 100)
    r = client.get("/api/runs/r1")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["score"] == 0.5
    assert len(body["events"]) == 1


def test_get_run_not_found(client):
    r = client.get("/api/runs/noexist")
    assert r.status_code == 404


def test_delete_run_removes_dir(client):
    _create_run("r1")
    r = client.delete("/api/runs/r1")
    assert r.status_code == 200
    assert client.get("/api/runs/r1").status_code == 404


def test_delete_run_not_found(client):
    r = client.delete("/api/runs/noexist")
    assert r.status_code == 404


def test_static_file_original_jpg(client, tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(runs_store, "RUNS_DIR", tmp_path / "runs")
    _create_run("r1")
    runs_store.save_image("r1", "original.jpg", Image.new("RGB", (8, 8), "red"))
    r = client.get("/api/runs/r1/original.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_static_file_not_found(client):
    _create_run("r1")
    r = client.get("/api/runs/r1/noexist.jpg")
    assert r.status_code == 404
