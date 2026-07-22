# agent.py — VLM 复核层：JSON 行动协议 Loop + 直链回退（Loop 与 UI 通过 TraceEvent 解耦）
import io
import json
import base64
import re
from dataclasses import dataclass, field
from datetime import date

import config


# ─── 数据结构 ──────────────────────────────────────────────────────
@dataclass
class TraceEvent:
    turn: int
    type: str      # stage|thought|tool_call|tool_result|verdict|fallback
    payload: dict


@dataclass
class AgentContext:
    image_path: str
    original_img: object          # PIL.Image（原始全分辨率）
    heatmap_img: object           # PIL.Image
    score: float
    infer_size: str
    tiled: bool
    candidates: list = field(default_factory=list)


class ProtocolError(Exception):
    pass


# ─── VLM 调用封装 ───────────────────────────────────────────────────
def image_to_base64(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def call_vlm(messages):
    import os
    import dashscope
    dashscope.base_http_api_url = config.VLM_BASE_URL
    resp = dashscope.MultiModalConversation.call(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        model=config.VLM_MODEL,
        messages=messages)
    if resp.status_code != 200:
        raise RuntimeError(f"VLM 调用失败: {resp.code} - {resp.message}")
    return resp.output.choices[0].message.content[0]["text"]


# ─── JSON 行动协议 ──────────────────────────────────────────────────
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def parse_turn(raw):
    blocks = _JSON_BLOCK.findall(raw)
    if not blocks:
        raise ProtocolError("未找到 ```json 代码块")
    try:
        d = json.loads(blocks[-1])
    except json.JSONDecodeError as e:
        raise ProtocolError(f"JSON 解析失败: {e}")
    if d.get("decision") not in ("investigate", "verdict"):
        raise ProtocolError("decision 字段缺失或非法")
    if d["decision"] == "investigate" and not d.get("action", {}).get("tool"):
        raise ProtocolError("investigate 必须携带 action.tool")
    if d["decision"] == "verdict" and not d.get("verdict", {}).get("conclusion"):
        raise ProtocolError("verdict 必须携带 verdict.conclusion")
    return d


def build_system_prompt(tools):
    tool_lines = "\n".join(
        f"- {t.name}: {t.description}\n  参数: {t.args_hint}" for t in tools)
    return f"""你是金融文档审核 AI Agent。当前日期：{date.today().isoformat()}。
你先收到 CV 篡改检测工具（TruFor）的首检结果（热力图、置信度分数、可疑区域候选框），\
你的职责是像审核员一样层层求证，最终给出财务人员可执行的审核结论。

可用工具：
{tool_lines}

每轮你必须输出且只输出一个 ```json 代码块，形如：
```json
{{"thought": "本轮分析（简要）",
 "decision": "investigate 或 verdict",
 "action": {{"tool": "工具名", "args": {{...}}}},
 "verdict": {{"conclusion": "正常/疑似篡改/高度可疑/无法审核(非金融单据)",
             "risk": "低/中/高",
             "regions": "异常区域及内容，无则写'无'",
             "basis": "复核依据（面向财务人员，禁用技术术语）",
             "advice": "建议操作"}}}}
```
decision=investigate 时必须给 action 且不给 verdict；decision=verdict 时必须给 verdict。

决策原则：
1. 先独立审视原图（文档类型、金额/日期/印章/签名等关键字段）；若并非金融单据，直接 verdict=无法审核。
2. CV 分数处于灰区（{config.LOW_THRESH}~{config.HIGH_THRESH}）、或标记区域涉及关键字段、或你与 CV 结论矛盾时，优先 investigate 查证。
3. 每次工具结果都要与已有证据交叉验证；证据充分即尽快 verdict，最多 {config.AGENT_MAX_TURNS} 轮。"""


def build_first_user_content(ctx):
    cand = "无" if not ctx.candidates else "\n".join(
        f"  #{c['id']}: bbox={c['bbox']} 面积占比={c['area_frac']:.2%} 区域均分={c['mean_score']}"
        for c in ctx.candidates)
    tiled_note = ("\n注意：该图超出单次推理上限，为切片推理结果，全局分数可信度较低，"
                  "建议对关键区域放大查证。") if ctx.tiled else ""
    return [
        {"text": f"CV 首检结果——整体篡改置信度：{ctx.score:.4f}（0=正常 1=篡改），"
                 f"推理尺寸：{ctx.infer_size}。{tiled_note}\n可疑区域候选框（0-1000 归一化）：\n{cand}"},
        {"text": "【原始文档图片】"},
        {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.original_img)}"},
        {"text": "【CV 检测热力图（红=可疑）】"},
        {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.heatmap_img)}"},
    ]


def tool_result_content(name, tr):
    content = [{"text": f"工具 {name} 返回：{tr.text}"}]
    for img in tr.images:
        content.append({"image": f"data:image/jpeg;base64,{image_to_base64(img)}"})
    return content


RISK_EMOJI = {"低": "🟢", "中": "🟡", "高": "🔴"}


def format_verdict(v):
    emoji = RISK_EMOJI.get(v.get("risk", ""), "⚪")
    return (f"### 审核结论：{v.get('conclusion', '')}\n\n"
            f"**风险等级**：{emoji} {v.get('risk', '—')}\n\n"
            f"**异常区域**：{v.get('regions', '无')}\n\n"
            f"**复核依据**：{v.get('basis', '')}\n\n"
            f"**建议操作**：{v.get('advice', '')}")


# ─── 直链回退（自 app.py 迁移，初复赛实战验证过的路径）────────────────
DIRECT_SYSTEM_PROMPT = f"""你是金融文档审核 AI 助手。当前日期：{date.today().isoformat()}。你将收到：
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


def direct_review(ctx):
    messages = [
        {"role": "system", "content": [{"text": DIRECT_SYSTEM_PROMPT}]},
        {"role": "user", "content": [
            {"text": f"CV 篡改检测置信度分数：{ctx.score:.4f}（0=正常，1=篡改）\n\n请对以下文档进行复核审查："},
            {"text": "【原始文档图片】"},
            {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.original_img)}"},
            {"text": "【CV 检测热力图（红色=可疑区域）】"},
            {"image": f"data:image/jpeg;base64,{image_to_base64(ctx.heatmap_img)}"},
        ]},
    ]
    return call_vlm(messages)
