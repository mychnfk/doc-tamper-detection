# scripts/probe_fc.py — 探测专属端点是否支持原生 function calling（结果仅记录，不改架构）
import os
from dotenv import load_dotenv
load_dotenv()
import dashscope
dashscope.base_http_api_url = "https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1"

TOOLS = [{"type": "function", "function": {
    "name": "zoom_region",
    "description": "放大查看图片指定区域",
    "parameters": {"type": "object", "properties": {
        "bbox": {"type": "array", "items": {"type": "integer"},
                 "description": "[x1,y1,x2,y2] 0-1000 归一化坐标"}},
        "required": ["bbox"]}}}]

r = dashscope.MultiModalConversation.call(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    model="qwen3.7-max-2026-06-08",
    messages=[{"role": "user", "content": [{"text": "请调用工具放大图片中央区域"}]}],
    tools=TOOLS)
print("status:", r.status_code)
if r.status_code == 200:
    msg = r.output.choices[0].message
    print("tool_calls:", getattr(msg, "tool_calls", None))
    print("content:", msg.content)
else:
    print("error:", r.code, r.message)
