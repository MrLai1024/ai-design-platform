"""Tests for the Manager dialog module: card builders + intent classification."""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.generation import dialog
from app.services.generation.dialog import (
    classify_intent,
    confirm_card_event,
    coverage_matrix_event,
    diagnosis_card_event,
    feedback_disposition_card_event,
    gate_speech_events,
    proposal_card_event,
    summary_card_event,
    verdict_card_event,
)


# ---------------------------------------------------------------------------
# Card event builders (task 2.1 / 2.4)
# ---------------------------------------------------------------------------


def test_card_events_share_single_event_type_shape():
    """All card builders produce the manager_message event dict shape."""
    for ev in (
        summary_card_event("analysis", "PRD 完成"),
        verdict_card_event("design", "pass"),
        diagnosis_card_event("code", ["编译未通过"], "建议重新执行"),
        confirm_card_event("e2e", "确认继续？", ["确认"]),
        proposal_card_event("code", "建议重构", ["接受", "拒绝"]),
        coverage_matrix_event("e2e", {"TC-001": "pass"}),
    ):
        assert ev["event_type"] == "manager_message"
        assert set(ev.keys()) == {"event_type", "stage", "data"}
        assert isinstance(ev["data"], dict)
        assert "card" in ev["data"]


def test_summary_card_event():
    ev = summary_card_event("analysis", "PRD 前三段…")
    assert ev["stage"] == "analysis"
    assert ev["data"]["card"] == "summary_card"
    assert ev["data"]["content"] == "PRD 前三段…"
    assert "需求分析" in ev["data"]["title"]


def test_verdict_card_event_pass_and_fail():
    ok = verdict_card_event("code", "pass", "")
    assert ok["data"]["card"] == "verdict_card"
    assert ok["data"]["data"]["passed"] is True
    assert "通过" in ok["data"]["content"]

    bad = verdict_card_event("code", "redo", "编译未通过（2 处错误）")
    assert bad["data"]["data"]["passed"] is False
    assert bad["data"]["data"]["decision"] == "redo"
    assert "未通过" in bad["data"]["content"]
    assert "编译未通过（2 处错误）" in bad["data"]["content"]

    rollback = verdict_card_event("e2e", "rollback", "E2E 有 1 个用例未通过")
    assert rollback["data"]["data"]["passed"] is False


def test_diagnosis_card_event():
    ev = diagnosis_card_event("code", ["PRD 为空", "PRD 缺少关键章节：功能模块"], "将返工重做", ["继续自主", "转人工"])
    assert ev["data"]["card"] == "diagnosis_card"
    assert ev["data"]["content"] == "PRD 为空\nPRD 缺少关键章节：功能模块"
    assert ev["data"]["options"] == ["继续自主", "转人工"]
    assert ev["data"]["data"]["suggestion"] == "将返工重做"

    # single-string evidence is accepted too
    ev2 = diagnosis_card_event("code", "编译失败")
    assert ev2["data"]["content"] == "编译失败"
    assert ev2["data"]["options"] == []


def test_confirm_and_proposal_and_coverage_builders():
    ev = confirm_card_event("e2e", "确认开始 E2E 验证？", ["确认"])
    assert ev["data"]["card"] == "confirm_card"
    assert ev["data"]["options"] == ["确认"]

    ev2 = proposal_card_event("code", "建议拆分组件", ["接受", "调整"])
    assert ev2["data"]["card"] == "proposal_card"
    assert ev2["data"]["options"] == ["接受", "调整"]

    ev3 = coverage_matrix_event("e2e", {"TC-001": "pass", "TC-002": "fail"})
    assert ev3["data"]["card"] == "coverage_matrix"
    assert ev3["data"]["data"]["matrix"]["TC-001"] == "pass"


def test_feedback_disposition_card_collapsed():
    """8.5 (code-feedback-loop spec): 反馈处置结果卡默认折叠 —
    卡片只携带折叠摘要行 (反馈摘要 + 处置动作 + 结果), 处置过程
    (分类/重派任务/验证结果) 进 data 供展开渲染。"""
    ev = feedback_disposition_card_event("code", "缺少订单列表组件", {
        "category": "omission",
        "category_label": "遗漏",
        "reason": "需求已声明但未生成",
        "action": "重派功能实现任务（携带反馈）",
        "result": "dispatched",
    })
    data = ev["data"]
    assert data["card"] == "feedback_card"
    # 折叠行摘要: 反馈文本 + 处置动作 + 结果
    assert data["data"]["feedback"] == "缺少订单列表组件"
    assert data["data"]["action"] == "重派功能实现任务（携带反馈）"
    assert data["data"]["result"] == "dispatched"
    # 展开详情: 分类 + 理由 (重派任务/验证结果由同流把关裁决卡呈现)
    assert data["data"]["category"] == "omission"
    assert data["data"]["category_label"] == "遗漏"
    assert data["data"]["reason"] == "需求已声明但未生成"
    assert data["data"]["node"] == "code"
    # 折叠语义: 不携带大段 content (前端完全由 data 派生渲染)
    assert not data.get("content")


def test_gate_speech_events_pass_and_fail():
    passed = gate_speech_events("analysis", "pass", "", "PRD 总结", [])
    assert [e["data"]["card"] for e in passed] == ["summary_card", "verdict_card"]
    assert passed[0]["data"]["content"] == "PRD 总结"

    failed = gate_speech_events("code", "redo", "编译未通过", "", ["编译未通过（1 处错误）"])
    assert len(failed) == 1
    assert failed[0]["data"]["card"] == "diagnosis_card"
    assert failed[0]["data"]["data"]["suggestion"]
    assert "编译未通过（1 处错误）" in failed[0]["data"]["content"]

    rolled = gate_speech_events("e2e", "rollback", "", "", ["E2E 有 1 个用例未通过"])
    assert rolled[0]["data"]["card"] == "diagnosis_card"
    assert "回滚" in rolled[0]["data"]["data"]["suggestion"]


# ---------------------------------------------------------------------------
# Intent classification (task 2.3) — LLM monkeypatched, no network
# ---------------------------------------------------------------------------


def _patch_llm(raw: str):
    return patch(
        "app.services.generation.dialog._llm_generate",
        new_callable=AsyncMock,
        return_value=raw,
    )


@pytest.mark.asyncio
async def test_classify_intent_plain_json():
    with _patch_llm('{"intent": "proceed", "reason": "用户表示可以继续"}') as m:
        result = await classify_intent("可以了", "analysis", "gen-1")
    assert result == {"intent": "proceed", "reason": "用户表示可以继续"}
    m.assert_awaited_once()
    # lightweight call: no thinking
    assert m.await_args.kwargs["enable_thinking"] is False


@pytest.mark.asyncio
async def test_classify_intent_fenced_json():
    with _patch_llm('```json\n{"intent": "feedback", "reason": "用户提出修改意见"}\n```'):
        result = await classify_intent("这里应该加个搜索功能", "design")
    assert result["intent"] == "feedback"


@pytest.mark.asyncio
async def test_classify_intent_all_vocab():
    cases = {
        "reply_qa": "是的，我指的是后台管理模块",
        "proceed": "开始吧",
        "feedback": "样式不太好看，改一下",
        "escalate": "我自己来改",
        "ask_why": "为什么这么设计？",
    }
    for intent, text in cases.items():
        with _patch_llm(f'{{"intent": "{intent}", "reason": "依据"}}'):
            result = await classify_intent(text)
        assert result["intent"] == intent


@pytest.mark.asyncio
async def test_classify_intent_quick_match_short_circuits_llm():
    """review M4: 高频确认/修改短语精确匹配短路 — 不触发 LLM 调用."""
    with _patch_llm('{"intent": "reply_qa", "reason": "不应到达"}'):
        result = await classify_intent("确认", "analysis", "gen-1")
    assert result["intent"] == "proceed"
    with _patch_llm('{"intent": "reply_qa", "reason": "不应到达"}'):
        result = await classify_intent("重新生成", "analysis", "gen-1")
    assert result["intent"] == "feedback"


@pytest.mark.asyncio
async def test_classify_intent_with_explicit_provider():
    """Explicit provider instance is used directly — the graph singleton is untouched."""
    from app.services.llm.provider import TokenEvent

    class FakeProvider:
        def __init__(self, text: str):
            self._text = text

        async def stream_generate(self, model, messages, config):
            assert model == "glm-5.2"
            yield TokenEvent(text=self._text, index=0)

    with _patch_llm("this must not be called") as m:
        result = await classify_intent(
            "可以了", "analysis", "gen-1",
            provider=FakeProvider('{"intent": "proceed", "reason": "用户表示可以继续"}'),
        )
    assert result == {"intent": "proceed", "reason": "用户表示可以继续"}
    m.assert_not_awaited()


@pytest.mark.asyncio
async def test_classify_intent_empty_text_short_circuits():
    """Empty input returns reply_qa without any LLM call."""
    with _patch_llm("this must not be called") as m:
        result = await classify_intent("   ", "analysis", "gen-1")
    assert result["intent"] == "reply_qa"
    assert "空输入" in result["reason"]
    m.assert_not_awaited()


@pytest.mark.asyncio
async def test_classify_intent_parse_failure_falls_back():
    with _patch_llm("抱歉，我不太确定。"):
        result = await classify_intent("随便说点什么")
    assert result["intent"] == "reply_qa"
    assert "解析" in result["reason"]


@pytest.mark.asyncio
async def test_classify_intent_out_of_vocab_falls_back():
    with _patch_llm('{"intent": "sing_dance", "reason": "未知"}') as m:
        result = await classify_intent("唱歌跳舞")
    assert result["intent"] == "reply_qa"
    assert "未知意图" in result["reason"]


def test_parse_intent_handles_whitespace_and_partial():
    assert dialog._parse_intent('  {"intent": "ask_why", "reason": "r"}  ') == ("ask_why", "r")
    assert dialog._parse_intent('{"intent": "proceed"}') == ("proceed", "")
    assert dialog._parse_intent("not json at all")[0] == "reply_qa"
