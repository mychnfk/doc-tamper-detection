"""金融文档篡改检测 — Gradio Demo (TruFor + Qwen-VL 复核)"""
import os
import base64
import io
import tempfile

import gradio as gr
import numpy as np
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

from run_inference import select_device, load_model, run_single, TRUFOR_ROOT

# ─── Global model (loaded once) ────────────────────────────────────
DEVICE = select_device()
MODEL = load_model(DEVICE, os.path.join(TRUFOR_ROOT, 'pretrained_models', 'trufor.pth.tar'))


# ─── Heatmap rendering ─────────────────────────────────────────────
def render_heatmap(loc_map):
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm

    colored = cm.RdBu_r(loc_map)
    return Image.fromarray((colored[:, :, :3] * 255).astype(np.uint8))


def render_confidence(conf_map):
    gray = (np.clip(conf_map, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(gray, mode='L').convert('RGB')


# ─── VLM 复核 ──────────────────────────────────────────────────────
from datetime import date
VLM_SYSTEM_PROMPT = f"""你是金融文档审核 AI 助手。当前日期：{date.today().isoformat()}。你将收到：
1. 一张待审核的金融文档图片（原图）
2. CV 篡改检测工具的分析结果（热力图，红色=可疑区域）
3. CV 工具给出的篡改置信度分数（0-1，越高越可疑）

请执行以下复核流程：

Step 1 - 独立审视：先看原图，识别文档类型、关键字段（金额、日期、签名、印章等）
Step 2 - 交叉验证：对比 CV 工具标记的可疑区域——
  - 该区域确实存在视觉异常吗？（如文字风格不一致、边缘不自然、颜色差异）
  - 还是可能的误报？（水印、低质量区域、正常的格式变化）
Step 3 - 综合判定：结合 CV 像素级证据 + 你的视觉理解，给出最终判定
Step 4 - 输出审核意见：用中文，面向财务人员，不使用技术术语

输出格式：
- 审核结论（正常/疑似篡改/高度可疑）
- 异常区域及内容（如有）
- 复核依据
- 风险等级（🟢低 / 🟡中 / 🔴高）
- 建议操作"""


def image_to_base64(img):
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def vlm_review(original_img, heatmap_img, score):
    api_key = os.getenv('DASHSCOPE_API_KEY')
    if not api_key:
        return "⚠️ 未配置 DASHSCOPE_API_KEY，跳过 VLM 复核"

    import dashscope
    dashscope.base_http_api_url = "https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1"

    orig_b64 = image_to_base64(original_img)
    heat_b64 = image_to_base64(heatmap_img)

    messages = [
        {"role": "system", "content": [{"text": VLM_SYSTEM_PROMPT}]},
        {"role": "user", "content": [
            {"text": f"CV 篡改检测置信度分数：{score:.4f}（0=正常，1=篡改）\n\n请对以下文档进行复核审查："},
            {"text": "【原始文档图片】"},
            {"image": f"data:image/jpeg;base64,{orig_b64}"},
            {"text": "【CV 检测热力图（红色=可疑区域）】"},
            {"image": f"data:image/jpeg;base64,{heat_b64}"},
        ]},
    ]

    response = dashscope.MultiModalConversation.call(
        api_key=api_key,
        model="qwen3.7-max-2026-06-08",
        messages=messages,
    )

    if response.status_code != 200:
        return f"⚠️ VLM 调用失败: {response.code} - {response.message}"

    return response.output.choices[0].message.content[0]["text"]


# ─── Main pipeline ──────────────────────────────────────────────────
def analyze(image_path, enable_vlm):
    result = run_single(MODEL, image_path, DEVICE, max_size=1792)

    if DEVICE == 'mps':
        import torch
        torch.mps.empty_cache()

    score = result['score']
    loc_map = result['map']
    conf_map = result['conf']

    heatmap_img = render_heatmap(loc_map)
    conf_img = render_confidence(conf_map)

    if score > 0.7:
        verdict = f"🔴 高度可疑 (score: {score:.4f})"
    elif score > 0.4:
        verdict = f"🟡 疑似异常 (score: {score:.4f})"
    else:
        verdict = f"🟢 未见明显篡改 (score: {score:.4f})"

    info = f"推理尺寸: {result['infer_size']}"

    vlm_text = ""
    if enable_vlm:
        try:
            original_img = Image.open(image_path).convert('RGB')
            vlm_text = vlm_review(original_img, heatmap_img, score)
        except Exception as e:
            vlm_text = f"⚠️ VLM 复核失败: {e}"

    return heatmap_img, conf_img, verdict, info, vlm_text


# ─── Gradio UI ──────────────────────────────────────────────────────
with gr.Blocks(title="文档篡改检测系统") as demo:
    gr.Markdown("""
    # 🔍 文档篡改检测系统
    **CV 工具检测 + AI 独立复核验证**

    上传文档图片 → TruFor 像素级篡改检测 → Qwen-VL 多模态复核 → 输出审核意见
    """)

    with gr.Row():
        with gr.Column(scale=1):
            input_image = gr.Image(type="filepath", label="上传文档图片")
            enable_vlm = gr.Checkbox(label="启用 AI 复核（Qwen-VL）", value=True)
            submit_btn = gr.Button("开始检测", variant="primary", size="lg")

        with gr.Column(scale=2):
            with gr.Row():
                heatmap_out = gr.Image(label="篡改定位热力图（红=可疑）", type="pil")
                conf_out = gr.Image(label="置信度图（白=高置信）", type="pil")
            with gr.Row():
                verdict_out = gr.Textbox(label="检测判定", lines=1)
                info_out = gr.Textbox(label="推理信息", lines=1)

    vlm_out = gr.Markdown(label="AI 复核意见")

    submit_btn.click(
        fn=analyze,
        inputs=[input_image, enable_vlm],
        outputs=[heatmap_out, conf_out, verdict_out, info_out, vlm_out],
    )

    gr.Examples(
        examples=[
            [os.path.join("example-images", f)]
            for f in sorted(os.listdir("example-images"))
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        ] if os.path.isdir("example-images") else [],
        inputs=[input_image],
        label="示例文档",
    )


if __name__ == '__main__':
    demo.launch(server_name="0.0.0.0", server_port=7860)
