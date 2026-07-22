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
