from datetime import date

import pytest
from PIL import Image

import agent
from agent import (parse_turn, ProtocolError, build_system_prompt, format_verdict,
                    DIRECT_SYSTEM_PROMPT, direct_review, AgentContext)


class FakeTool:
    name = "zoom_region"
    description = "放大"
    args_hint = "{...}"


def test_parse_valid_investigate():
    raw = '前置解释文字\n```json\n{"thought":"分数灰区","decision":"investigate",' \
          '"action":{"tool":"zoom_region","args":{"region_id":1}}}\n```'
    d = parse_turn(raw)
    assert d["decision"] == "investigate"
    assert d["action"]["tool"] == "zoom_region"


def test_parse_valid_verdict():
    raw = '```json\n{"thought":"x","decision":"verdict","verdict":{"conclusion":"正常",' \
          '"risk":"低","regions":"无","basis":"...","advice":"..."}}\n```'
    assert parse_turn(raw)["verdict"]["conclusion"] == "正常"


def test_parse_picks_last_json_block():
    raw = '```json\n{"decision":"investigate","thought":"旧"}\n```\n改主意\n' \
          '```json\n{"thought":"新","decision":"verdict","verdict":{"conclusion":"正常"}}\n```'
    assert parse_turn(raw)["decision"] == "verdict"


@pytest.mark.parametrize("raw", [
    "没有 json 块",
    '```json\n{"thought":"缺 decision"}\n```',
    '```json\n{"decision":"investigate"}\n```',          # investigate 但缺 action
    '```json\n{decision: 不是合法json}\n```',
    '```json\n{"decision":"investigate","action":null}\n```',           # action 非 dict（null）
    '```json\n{"decision":"verdict","verdict":null}\n```',              # verdict 非 dict（null）
    '```json\n{"decision":"investigate","action":"zoom_region"}\n```',  # action 非 dict（字符串）
])
def test_parse_errors(raw):
    with pytest.raises(ProtocolError):
        parse_turn(raw)


def test_system_prompt_lists_tools():
    p = build_system_prompt([FakeTool()])
    assert "zoom_region" in p and "```json" in p


def test_format_verdict():
    md = format_verdict({"conclusion": "疑似篡改", "risk": "中", "regions": "金额栏",
                         "basis": "字体不一致", "advice": "人工核实"})
    assert "疑似篡改" in md and "🟡" in md


def _direct_ctx():
    img = Image.new("RGB", (400, 300), "white")
    return AgentContext(image_path="/tmp/x.png", original_img=img, heatmap_img=img,
                        score=0.5, infer_size="400x300", tiled=False)


def test_direct_system_prompt_interpolates_date_at_call_time(monkeypatch):
    # 常量本身只是模板，不应在 import 时就烤入日期
    assert "{today}" in DIRECT_SYSTEM_PROMPT
    assert date.today().isoformat() not in DIRECT_SYSTEM_PROMPT

    captured = {}

    def fake_call_vlm(messages):
        captured["messages"] = messages
        return "ok"

    monkeypatch.setattr(agent, "call_vlm", fake_call_vlm)
    direct_review(_direct_ctx())
    system_text = captured["messages"][0]["content"][0]["text"]
    assert date.today().isoformat() in system_text
