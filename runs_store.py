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
    return sorted(metas, key=lambda m: (m.get("created_at", ""), m.get("run_id", "")), reverse=True)


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
