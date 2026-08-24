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
    # 显式指定 created_at——两条记录若在同一秒创建，时间戳相同则排序不确定，会成为 flaky test
    older = runs_store.new_run_id()
    runs_store.create_run(older, "a.jpg", "cv")
    runs_store.finalize_run(older, created_at="2026-08-13T10:00:00", score=0.5)
    newer = runs_store.new_run_id()
    runs_store.create_run(newer, "b.jpg", "cv")
    runs_store.finalize_run(newer, created_at="2026-08-13T11:00:00", score=0.5)
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
