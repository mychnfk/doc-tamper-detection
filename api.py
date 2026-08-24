# api.py — FastAPI：检测 SSE + 记录 REST
import json
import os
import pathlib
import queue
import tempfile
import threading
import time
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

import config
import pipeline
import runs_store
from agent import cv_grade
from pipeline import get_runtime
from run_inference import run_single

register_heif_opener()                      # 评委 iPhone HEIC 直传

VALID_MODES = ("agent", "direct", "cv")

# 单模型实例，请求必须串行——并发使用同一个 MPS 模型会出问题（spec §8）。
# 对应 Gradio 版的 queue(default_concurrency_limit=1) 语义。
_DETECT_LOCK = threading.Lock()


def _warmup():
    """启动即加载模型并跑一次 256x256，把首次开销提前消化掉。
    对齐 app.py::_warmup() 的行为——否则评委的第一次检测要多等约 5 秒。"""
    model, device, _ = get_runtime()
    tiny = os.path.join(tempfile.gettempdir(), "docguard_warmup.png")
    Image.new("RGB", (256, 256), "white").save(tiny)
    run_single(model, tiny, device, max_size=config.MAX_SIZE)
    if device == "mps":
        import torch
        torch.mps.empty_cache()
    print("Warmup done.", flush=True)


@asynccontextmanager
async def lifespan(_app):
    # 只在真正起服务时预热；TestClient 非上下文管理器用法不触发 lifespan，故测试不受影响
    await anyio.to_thread.run_sync(_warmup)
    yield


app = FastAPI(title="DocGuard API", lifespan=lifespan)


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
        os.unlink(tmp.name)
        raise HTTPException(400, "无法解析为图片，请上传 JPG/PNG/HEIC 格式的单据图片")

    run_id = runs_store.new_run_id()
    runs_store.create_run(run_id, file.filename or "unnamed", mode)

    # 检测在独立线程里跑完，SSE 协程只消费队列。检测与推送必须解耦：
    # 若把检测写成同步生成器直接交给 StreamingResponse，客户端中止/刷新后
    # 生成器会永远停在 yield 上没人驱动，_DETECT_LOCK 随之永不释放，
    # 后续所有检测无限排队（8-21 与 8-24 两次僵尸事故的根因）。
    # 断开后检测照常跑完并落盘，结果仍可在「记录」页回放。
    def produce(q):
        started = time.monotonic()
        meta_updates = {}
        try:
            # 锁必须覆盖整个检测过程，而不只是取 runtime——否则两个请求会并发用同一个 MPS 模型
            with _DETECT_LOCK:
                model, device, tools = get_runtime()
                for kind, item in pipeline.run_detection(tmp.name, mode, model=model,
                                                         device=device, tools=tools):
                    elapsed = int((time.monotonic() - started) * 1000)
                    if kind == "cv":
                        runs_store.save_image(run_id, "original.jpg", item["original"])
                        runs_store.save_image(run_id, "heatmap.jpg", item["heatmap"])
                        runs_store.save_image(run_id, "confidence.jpg", item["confidence"])
                        label, risk = cv_grade(item["score"])
                        data = {"run_id": run_id, "turn": 0, "type": "cv", "elapsed_ms": elapsed,
                                "payload": {"score": item["score"], "infer_size": item["infer_size"],
                                            "label": label, "risk": risk,
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
                    q.put(_sse("trace", data))

            meta_updates["duration_ms"] = int((time.monotonic() - started) * 1000)
            runs_store.finalize_run(run_id, **meta_updates)
            q.put(_sse("done", {"run_id": run_id, "duration_ms": meta_updates["duration_ms"]}))
        except Exception as e:                                     # noqa: BLE001 — 兜底转 SSE，不让连接裸断
            runs_store.finalize_run(run_id, error=str(e),
                                    duration_ms=int((time.monotonic() - started) * 1000))
            q.put(_sse("error", {"message": f"检测过程出错：{e}"}))
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
            q.put(None)                                            # 结束哨兵

    frames = queue.Queue()
    threading.Thread(target=produce, args=(frames,), daemon=True).start()

    async def stream():
        # 轮询而非 to_thread 阻塞取——断开时协程能被立即取消，不留被弃置的工作线程。
        # 事件间隔以秒计，150ms 轮询的延迟感知不到。
        while True:
            try:
                frame = frames.get_nowait()
            except queue.Empty:
                await anyio.sleep(0.15)
                continue
            if frame is None:
                break
            yield frame

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- 记录模块 + 静态托管 ----
# 路由顺序有讲究：/api/runs/{run_id}/{rel_path} 必须在 /api/runs/{run_id} 之后，
# catch-all 的 /{full_path:path} 必须在文件最末，否则会吞掉所有 API 路由。

WEB_DIST = pathlib.Path(__file__).parent / "web" / "dist"


def _safe_child(base, rel_path):
    """把 rel_path 解析到 base 之下；越界或不是文件则返回 None。
    用 is_relative_to 而非字符串 startswith——后者会让 runs/abc 读到 runs/abcdef。"""
    base = base.resolve()
    target = (base / rel_path).resolve()
    return target if target.is_relative_to(base) and target.is_file() else None


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
    target = _safe_child(runs_store.RUNS_DIR / run_id, rel_path)
    if target is None:
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


@app.get("/")
@app.get("/{full_path:path}")
def spa(full_path: str = ""):
    """托管前端构建产物；未构建时给出可操作提示而不是 500。"""
    if full_path.startswith("api/"):
        raise HTTPException(404, "未知的 API 路径")
    asset = _safe_child(WEB_DIST, full_path) if full_path else None
    if asset is not None:
        return FileResponse(asset)
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<h1>前端尚未构建</h1><p>请先执行 <code>cd web &amp;&amp; npm run build</code></p>",
                        status_code=200)
