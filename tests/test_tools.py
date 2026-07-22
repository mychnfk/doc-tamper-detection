import sys
from dataclasses import dataclass, field
from PIL import Image

import config
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


def test_second_opinion_missing_module_wrapped_error(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_HIFI", "on")
    monkeypatch.setitem(sys.modules, "hifi_inference", None)
    r = SecondOpinionTool().run(None)
    assert r.error and r.text
