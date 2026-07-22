import pytest
from PIL import Image
from agent import AgentContext, TraceEvent, review


def _ctx(score=0.55, tiled=False):
    img = Image.new("RGB", (400, 300), "white")
    return AgentContext(image_path="/tmp/x.png", original_img=img, heatmap_img=img,
                        score=score, infer_size="400x300", tiled=tiled,
                        candidates=[{"id": 1, "bbox": [100, 100, 300, 300],
                                     "area_frac": 0.02, "mean_score": 0.8}])


class FakeTool:
    name = "zoom_region"
    description = "放大"
    args_hint = "{}"

    def available(self):
        return True

    def run(self, ctx, **kw):
        from tools import ToolResult
        return ToolResult(text="裁片完成", images=[Image.new("RGB", (50, 50))])


def _scripted_vlm(responses):
    it = iter(responses)

    def vlm(messages):
        return next(it)
    return vlm


INVESTIGATE = ('```json\n{"thought":"灰区需查证","decision":"investigate",'
               '"action":{"tool":"zoom_region","args":{"region_id":1}}}\n```')
VERDICT = ('```json\n{"thought":"证据充分","decision":"verdict","verdict":'
           '{"conclusion":"疑似篡改","risk":"中","regions":"金额栏","basis":"字体不一致","advice":"人工核实"}}\n```')


def _types(events):
    return [e.type for e in events]


def test_investigate_then_verdict():
    evs = list(review(_ctx(), [FakeTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, VERDICT])))
    t = _types(evs)
    assert t == ["stage", "thought", "tool_call", "tool_result", "thought", "verdict"]
    assert evs[-1].payload["source"] == "agent"
    assert evs[-1].payload["verdict"]["conclusion"] == "疑似篡改"
    assert "疑似篡改" in evs[-1].payload["text"]


def test_max_turns_forces_verdict():
    evs = list(review(_ctx(), [FakeTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, INVESTIGATE, INVESTIGATE, VERDICT])))
    assert _types(evs)[-1] == "verdict"
    assert evs[-1].payload["source"] == "agent-forced"


def test_parse_fail_twice_falls_back():
    calls = {"n": 0}

    def vlm(messages):
        calls["n"] += 1
        if calls["n"] <= 2:
            return "不是 json"
        return "直链的自由文本审核意见"        # 第三次调用来自直链

    evs = list(review(_ctx(), [FakeTool()], mode="agent", vlm=vlm))
    assert "fallback" in _types(evs)
    assert evs[-1].type == "verdict" and evs[-1].payload["source"] == "direct"
    assert evs[-1].payload["text"] == "直链的自由文本审核意见"


def test_vlm_dead_falls_back_to_cv_only():
    def vlm(messages):
        raise RuntimeError("网络挂了")

    evs = list(review(_ctx(score=0.85), [FakeTool()], mode="agent", vlm=vlm))
    assert evs[-1].type == "verdict" and evs[-1].payload["source"] == "cv"
    assert "0.85" in evs[-1].payload["text"] or "高度可疑" in evs[-1].payload["text"]


def test_tool_error_returned_to_vlm():
    class BadTool(FakeTool):
        def run(self, ctx, **kw):
            from tools import ToolResult
            return ToolResult(text="炸了", error=True)

    evs = list(review(_ctx(), [BadTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, VERDICT])))
    tr = [e for e in evs if e.type == "tool_result"][0]
    assert tr.payload["error"] is True
    assert evs[-1].type == "verdict"          # loop 未中断


def test_mode_direct_and_cv():
    evs = list(review(_ctx(), [], mode="direct", vlm=lambda m: "直链意见"))
    assert _types(evs) == ["stage", "verdict"] and evs[-1].payload["source"] == "direct"

    evs = list(review(_ctx(score=0.2), [], mode="cv"))
    assert evs[-1].payload["source"] == "cv" and "未见明显篡改" in evs[-1].payload["text"]


# ─── Review 追加：三个 reviewer finding 的回归测试 ──────────────────────

def test_vlm_exception_falls_back_to_cv():
    def vlm(messages):
        raise ConnectionError("网络挂了")

    evs = list(review(_ctx(), [], mode="agent", vlm=vlm))
    assert evs[-1].type == "verdict"
    assert evs[-1].payload["source"] == "cv"


def test_vlm_retry_once_then_success():
    calls = {"n": 0}

    def vlm(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("网络抖动")
        return VERDICT

    evs = list(review(_ctx(), [FakeTool()], mode="agent", vlm=vlm))
    assert evs[-1].type == "verdict"
    assert evs[-1].payload["source"] == "agent"
    assert calls["n"] == 2


def test_tool_raise_wrapped_not_crash():
    class RaisingTool(FakeTool):
        def run(self, ctx, **kw):
            raise TypeError("bbox 含非数字项")

    evs = list(review(_ctx(), [RaisingTool()], mode="agent",
                      vlm=_scripted_vlm([INVESTIGATE, VERDICT])))
    tr = [e for e in evs if e.type == "tool_result"][0]
    assert tr.payload["error"] is True
    assert evs[-1].type == "verdict"
    assert evs[-1].payload["source"] == "agent"


FORCED_NONDICT = ('```json\n{"thought":"继续查证","decision":"investigate",'
                  '"verdict":"看起来正常","action":{"tool":"zoom_region","args":{"region_id":1}}}\n```')


def test_forced_turn_nondict_verdict_no_crash():
    evs = list(review(_ctx(), [FakeTool()], mode="agent",
                      vlm=lambda messages: FORCED_NONDICT))
    assert evs[-1].type == "verdict"
    assert evs[-1].payload["source"] == "agent-forced"
