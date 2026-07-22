import pytest
from agent import parse_turn, ProtocolError, build_system_prompt, format_verdict


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
