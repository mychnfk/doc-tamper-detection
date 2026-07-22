"""金融文档篡改检测 — Gradio Demo (TruFor 首检 + Agent Loop 复核)"""
import os
import tempfile

import gradio as gr
import numpy as np
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()                       # 评委 iPhone HEIC 直传

import config
from run_inference import select_device, load_model, run_single, TRUFOR_ROOT
from regions import extract_candidate_regions
from tools import build_registry
from agent import AgentContext, review

# ─── Global model（启动即加载 + warmup）────────────────────────────
DEVICE = select_device()
MODEL = load_model(DEVICE, os.path.join(TRUFOR_ROOT, 'pretrained_models', 'trufor.pth.tar'))
TOOLS = build_registry()


def _warmup():
    tiny = Image.new('RGB', (256, 256), 'white')
    p = os.path.join(tempfile.gettempdir(), 'docguard_warmup.png')
    tiny.save(p)
    run_single(MODEL, p, DEVICE, max_size=config.MAX_SIZE)
    if DEVICE == 'mps':
        import torch
        torch.mps.empty_cache()
    print('Warmup done.')


_warmup()

# ─── 渲染 ──────────────────────────────────────────────────────────
def render_heatmap(loc_map):
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(loc_map)[:, :, :3] * 255).astype(np.uint8))


def render_confidence(conf_map):
    gray = (np.clip(conf_map, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(gray, mode='L').convert('RGB')


def _verdict_str(score):
    if score > config.HIGH_THRESH:
        return f"🔴 高度可疑 (score: {score:.4f})"
    if score > config.LOW_THRESH:
        return f"🟡 疑似异常 (score: {score:.4f})"
    return f"🟢 未见明显篡改 (score: {score:.4f})"


def _save_tmp(img):
    f = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
    img.convert('RGB').save(f.name, quality=90)
    return f.name


EVENT_TITLE = {
    'thought': '💭 第{turn}轮·思考',
    'tool_call': '🔧 第{turn}轮·调用工具',
    'tool_result': '📎 第{turn}轮·工具返回',
    'fallback': '⚠️ 已切换复核方式',
}

MODE_MAP = {'Agent 复核（推荐）': 'agent', '快速复核': 'direct', '仅 CV 检测': 'cv'}


# ─── 主流程（生成器：流式驱动三栏）───────────────────────────────────
def analyze(image_path, mode_label):
    chat = [{"role": "assistant", "content": "🔬 阶段一：像素级取证中（TruFor）…"}]
    yield None, None, "", "", chat

    result = run_single(MODEL, image_path, DEVICE, max_size=config.MAX_SIZE)
    if DEVICE == 'mps':
        import torch
        torch.mps.empty_cache()

    heatmap_img = render_heatmap(result['map'])
    conf_img = render_confidence(result['conf'])
    verdict = _verdict_str(result['score'])
    info = f"推理尺寸: {result['infer_size']}（阈值经自建业务评测集校准）"
    chat.append({"role": "assistant", "content": f"✅ 取证完成，置信度 {result['score']:.4f}，进入 AI 复核"})
    yield heatmap_img, conf_img, verdict, info, chat

    ctx = AgentContext(
        image_path=image_path,
        original_img=Image.open(image_path).convert('RGB'),
        heatmap_img=heatmap_img,
        score=result['score'],
        infer_size=str(result['infer_size']),
        tiled='tiled' in str(result['infer_size']),
        candidates=extract_candidate_regions(result['map']),
    )

    for ev in review(ctx, TOOLS, mode=MODE_MAP.get(mode_label, 'agent')):
        if ev.type == 'stage':
            continue
        if ev.type == 'verdict':
            chat.append({"role": "assistant", "content": ev.payload['text']})
        elif ev.type == 'tool_result':
            body = ev.payload['text']
            chat.append({"role": "assistant", "content": body,
                         "metadata": {"title": EVENT_TITLE['tool_result'].format(turn=ev.turn)}})
            for img in ev.payload.get('images', []):
                chat.append({"role": "assistant", "content": {"path": _save_tmp(img)}})
        elif ev.type == 'fallback':
            chat.append({"role": "assistant", "content": ev.payload['reason'],
                         "metadata": {"title": EVENT_TITLE['fallback']}})
            if ev.payload.get('detail'):        # 原始报错折叠收纳，彩排排障用，默认不示人
                chat.append({"role": "assistant", "content": ev.payload['detail'],
                             "metadata": {"title": "⚙️ 技术详情", "status": "done"}})
        else:
            title = EVENT_TITLE.get(ev.type, ev.type).format(turn=ev.turn)
            body = ev.payload.get('thought') or ev.payload.get('reason') or \
                f"{ev.payload.get('tool')} {ev.payload.get('args', '')}"
            chat.append({"role": "assistant", "content": str(body), "metadata": {"title": title}})
        yield heatmap_img, conf_img, verdict, info, chat


# ─── UI ────────────────────────────────────────────────────────────
FORCE_LIGHT = "() => { document.body.classList.remove('dark'); }"

with gr.Blocks(title="DocGuard 文档篡改智能审核", theme=gr.themes.Soft(), js=FORCE_LIGHT) as demo:
    gr.Markdown("""
    # 🔍 DocGuard — 文档篡改智能审核系统
    **像素级取证（TruFor）+ AI Agent 自主复核** &nbsp;|&nbsp; 上传单据 → CV 取证 → AI 层层求证 → 审核意见
    """)

    with gr.Row():
        with gr.Column(scale=1):
            input_image = gr.Image(type="filepath", label="上传文档图片")
            mode = gr.Radio(list(MODE_MAP.keys()), value="Agent 复核（推荐）", label="复核模式")
            submit_btn = gr.Button("开始检测", variant="primary", size="lg")
            gr.Examples(
                examples=[[os.path.join("example-images", f)]
                          for f in sorted(os.listdir("example-images"))
                          if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                if os.path.isdir("example-images") else [],
                inputs=[input_image], label="示例文档")

        with gr.Column(scale=2):
            with gr.Row():
                heatmap_out = gr.Image(label="篡改定位热力图（红=可疑）", type="pil")
                conf_out = gr.Image(label="置信度图（白=高置信）", type="pil")
            verdict_out = gr.Textbox(label="CV 检测判定", lines=1)
            info_out = gr.Textbox(label="推理信息", lines=1)

        with gr.Column(scale=2):
            trace_out = gr.Chatbot(label="AI 审核过程（实时）", height=560)

    submit_btn.click(fn=analyze, inputs=[input_image, mode],
                     outputs=[heatmap_out, conf_out, verdict_out, info_out, trace_out])

if __name__ == '__main__':
    demo.queue(default_concurrency_limit=1, max_size=8)
    demo.launch(server_name="0.0.0.0", server_port=7860)
