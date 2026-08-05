"""Tests for the agenda-driven brainstorm engine (task group 3).

Covers 3.1-3.5 (agenda model / profile / question rounds / proposal
comparison / dual-factor convergence) plus the servicer BrainstormTurn RPC,
the session→graph handoff, and 3.6 (PRD consuming 澄清产物). All LLM calls are
mocked through the ``llm_fn`` seam — no real LLM.
"""

import json
import re

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.generation.brainstorm import (
    AgendaItem,
    BrainstormSession,
    clear_sessions,
    create_session,
    coverage,
    get_or_create_session,
    get_session,
    parse_structured,
    to_requirements_state_json,
    turn,
)

from app.services.generation.requirements.state import RequirementsState

# ── Canned LLM outputs (dispatched by system-prompt content) ──

PROFILE_JSON = json.dumps({
    "requirement_type": "admin_system",
    "project_name": "后台管理系统",
    "core_problem": "缺乏统一的管理后台",
    "target_users": [{"role": "管理员", "description": "日常运营管理"}],
    "success_criteria": ["权限可配置"],
    "scope_note": "一期不含移动端",
    "ambiguities": [
        {"topic": "权限模型", "reason": "不明确会导致权限设计偏离", "impact": "design"},
        {"topic": "主界面布局", "reason": "影响界面展示结构", "impact": "ui"},
        {"topic": "数据来源", "reason": "影响数据模型设计", "impact": "tech"},
    ],
    "candidate_plans": [
        {"name": "方案A", "summary": "轻量后台", "scope": "只做核心管理", "interaction": "单页布局",
         "pros": ["快"], "costs": ["功能少"]},
        {"name": "方案B", "summary": "完整后台", "scope": "含全部管理模块", "interaction": "多页导航",
         "pros": ["全"], "costs": ["周期长"]},
    ],
    "features": [{"id": "F-01", "name": "用户管理", "description": "用户增删改查", "priority": "must"}],
    "pages": [{"id": "P-01", "name": "用户列表", "parent_id": None, "page_type": "list", "features": ["F-01"]}],
    "tech_constraints": {"framework": "vue3", "component_lib": "element-plus", "data_source": "", "special_requirements": []},
    "data_entities": [{"name": "User", "fields": [{"name": "id", "type": "string", "required": True}]}],
}, ensure_ascii=False)

QUESTIONS_JSON = json.dumps({
    "questions": [
        {"item_id": "a1", "question": "权限模型采用哪种？", "options": ["RBAC", "简单角色"]},
        {"item_id": "a2", "question": "主界面布局如何？", "options": ["多页导航", "单页仪表盘"]},
        {"item_id": "a3", "question": "数据来源是？", "options": ["本地mock", "后端接口"]},
    ],
}, ensure_ascii=False)

PROPOSALS_JSON = json.dumps({
    "proposals": [
        {"name": "方案A", "scope": "只做核心管理", "interaction": "单页布局",
         "pros": ["交付快"], "costs": ["功能有限"]},
        {"name": "方案B", "scope": "完整管理模块", "interaction": "多页导航",
         "pros": ["覆盖全"], "costs": ["周期长"]},
    ],
}, ensure_ascii=False)

REQUIREMENTS_JSON = json.dumps({
    "vision": {
        "project_name": "后台管理系统", "core_problem": "缺乏统一管理后台",
        "target_users": [{"role": "管理员", "description": "日常运营"}],
        "success_criteria": ["权限可配置"], "scope_note": "一期不含移动端",
    },
    "features": [{"id": "F-01", "name": "用户管理", "description": "增删改查",
                  "priority": "must", "completeness": 100, "confirmed": True}],
    "pages": [{"id": "P-01", "name": "用户列表", "parent_id": None,
               "page_type": "list", "features": ["F-01"]}],
    "page_details": {"P-01": {"display_fields": [{"name": "用户名", "type": "text", "required": True}],
                               "action_buttons": [{"label": "编辑", "type": "custom"}],
                               "related_data": [], "layout_notes": ""}},
    "tech_constraints": {"framework": "vue3", "component_lib": "element-plus",
                         "data_source": "", "special_requirements": []},
    "data_entities": [{"name": "User", "fields": [{"name": "id", "type": "string", "required": True}]}],
}, ensure_ascii=False)


async def fake_llm(system_prompt: str, user_prompt: str) -> str:
    # 注意：须先匹配更具体的短语（「需求画像」也出现在方案对比/结构化整理 prompt 中）
    if "为指定议程项生成提问" in system_prompt:
        return QUESTIONS_JSON
    if "候选方案供用户选择" in system_prompt:
        return PROPOSALS_JSON
    if "整理为结构化需求" in system_prompt:
        return REQUIREMENTS_JSON
    if "需求画像" in system_prompt:
        return PROFILE_JSON
    return "{}"


def seeded_session(gid: str = "t-session") -> BrainstormSession:
    session = BrainstormSession(generation_id=gid, requirement="做一个后台管理系统", round=1)
    session.profile = json.loads(PROFILE_JSON)
    session.agenda = [
        AgendaItem(id="a1", topic="权限模型", reason="不明确会导致权限设计偏离", impact="design"),
        AgendaItem(id="a2", topic="主界面布局", reason="影响界面展示结构", impact="ui"),
        AgendaItem(id="a3", topic="数据来源", reason="影响数据模型设计", impact="tech"),
    ]
    return session


# ── 3.1 AgendaItem / session registry ──


def test_session_registry():
    clear_sessions()
    s1 = create_session()
    assert get_session(s1.generation_id) is s1
    assert get_session("nope") is None
    # get_or_create reuses existing; creates when absent
    assert get_or_create_session(s1.generation_id) is s1
    s2 = get_or_create_session(None)
    assert s2.generation_id != s1.generation_id
    clear_sessions()


def test_agenda_item_to_dict():
    item = AgendaItem(id="a1", topic="权限", reason="r", impact="design")
    d = item.to_dict()
    assert d == {"id": "a1", "topic": "权限", "reason": "r", "impact": "design",
                 "status": "pending", "answer": ""}


def test_parse_structured_fence_strip_and_failsafe():
    schema = {"a": "", "b": [""], "c": {"d": ""}}
    assert parse_structured('```json\n{"a": "x", "b": ["y"]}\n```', schema) == {
        "a": "x", "b": ["y"], "c": {"d": ""},
    }
    # invalid JSON → empty defaults mirroring the schema (fail-safe)
    assert parse_structured("not json", schema) == {"a": "", "b": [], "c": {"d": ""}}


# ── 3.2 首轮需求画像 ──


@pytest.mark.asyncio
async def test_first_turn_produces_profile_card_no_questions():
    clear_sessions()
    session = create_session()
    result = await turn(session, "我要做一个后台管理系统", llm_fn=fake_llm)

    assert result["converged"] is False
    assert len(result["events"]) == 1
    ev = result["events"][0]
    assert ev["event_type"] == "manager_message"
    assert ev["data"]["card"] == "summary_card"
    assert "需求画像" in ev["data"]["title"]
    profile = ev["data"]["data"]["profile"]
    assert profile["requirement_type"] == "admin_system"
    assert len(profile["candidate_plans"]) == 2
    # 首轮不提问
    assert all(e["data"]["card"] != "question_card" for e in result["events"])
    # 议程由模糊点种下
    assert [a.topic for a in session.agenda] == ["权限模型", "主界面布局", "数据来源"]
    assert session.requirement == "我要做一个后台管理系统"


# ── 3.3 每轮提问（按影响面排序） + 未答项 assumed ──


@pytest.mark.asyncio
async def test_question_round_asks_by_impact_design_first():
    session = seeded_session()
    result = await turn(session, "", llm_fn=fake_llm)

    cards = [e["data"] for e in result["events"] if e["data"]["card"] == "question_card"]
    assert len(cards) == 3
    assert cards[0]["data"]["item_id"] == "a1"      # design 优先
    assert cards[1]["data"]["item_id"] == "a2"      # ui 其次
    assert cards[2]["data"]["item_id"] == "a3"
    assert session.last_asked_ids == ["a1", "a2", "a3"]


@pytest.mark.asyncio
async def test_answer_via_item_id_and_assumed_marking():
    session = seeded_session()
    # 第一轮提问 a1/a2/a3
    await turn(session, "", llm_fn=fake_llm)
    # 第二轮：回答 a1 → 上一轮其余项本轮仍未答（a2/a3 保持 pending，供下一轮再问）
    r2 = await turn(session, "RBAC", item_id="a1", llm_fn=fake_llm)
    assert session.agenda[0].status == "answered"
    assert session.agenda[0].answer == "RBAC"
    # 第三轮提问（a2/a3）→ prior=[a1,a2,a3], last=[a2,a3]
    await turn(session, "", llm_fn=fake_llm)
    # 第四轮：回答 a2 → a3 被标记 assumed（用户跳过了它）
    r4 = await turn(session, "多页导航", item_id="a2", llm_fn=fake_llm)
    assert session.agenda[2].status == "assumed"
    assert any(a["item_id"] == "a3" for a in session.assumptions)
    assert r4["events"]  # 仍有卡片（question 或 ack）


@pytest.mark.asyncio
async def test_answer_supersedes_assumption():
    session = seeded_session()
    session.agenda[2].status = "assumed"
    session.assumptions = [{"item_id": "a3", "topic": "数据来源", "assumption": "默认", "status": "assumed"}]

    result = await turn(session, "后端接口", item_id="a3", llm_fn=fake_llm)
    assert session.agenda[2].status == "answered"
    assert session.agenda[2].answer == "后端接口"
    assert all(a["item_id"] != "a3" for a in session.assumptions)
    assert result["converged"] is False


@pytest.mark.asyncio
async def test_answering_different_answer_marks_conflict():
    session = seeded_session()
    session.agenda[0].status = "answered"
    session.agenda[0].answer = "RBAC"

    await turn(session, "简单角色", item_id="a1", llm_fn=fake_llm)
    assert session.agenda[0].status == "conflict"
    assert session.agenda[0].answer == "简单角色"  # 最新答案为准


# ── 3.4 方案对比卡片 ──


@pytest.mark.asyncio
async def test_proposal_round_shown_when_coverage_reached():
    session = seeded_session()
    for i, item in enumerate(session.agenda):
        item.status = "answered"
        item.answer = f"答案{i}"

    result = await turn(session, "", llm_fn=fake_llm)
    cards = [e["data"] for e in result["events"]]
    assert cards[0]["card"] == "proposal_card"
    proposals = cards[0]["data"]["proposals"]
    assert len(proposals) == 2
    for p in proposals:
        assert p["scope"] and p["interaction"] and p["pros"] and p["costs"]
    assert "混合方案" in cards[0]["options"]
    assert "重新生成方案" in cards[0]["options"]


@pytest.mark.asyncio
async def test_proposal_choice_records_decision_and_offers_confirm():
    session = seeded_session()
    for i, item in enumerate(session.agenda):
        item.status = "answered"
        item.answer = f"答案{i}"
    await turn(session, "", llm_fn=fake_llm)  # 方案对比
    assert session.proposal_shown and not session.proposal_decided

    result = await turn(session, "方案A", llm_fn=fake_llm)
    assert session.proposal_decided is True
    assert session.decisions and session.decisions[-1]["topic"] == "方案选型"
    assert session.decisions[-1]["choice"] == "方案A"
    # 选择落定 → 输出收敛确认卡片（等待用户确认，双因子之二）
    cards = [e["data"] for e in result["events"]]
    assert any(c["card"] == "confirm_card" for c in cards)
    assert result["converged"] is False  # 覆盖度达标但用户未确认 → 不收敛


@pytest.mark.asyncio
async def test_proposal_regenerate():
    session = seeded_session()
    for item in session.agenda:
        item.status = "answered"
    await turn(session, "", llm_fn=fake_llm)

    result = await turn(session, "重新生成方案", llm_fn=fake_llm)
    assert session.proposal_decided is False
    cards = [e["data"] for e in result["events"]]
    assert cards[0]["card"] == "proposal_card"


# ── 3.5 双因子收敛 ──


@pytest.mark.asyncio
async def test_coverage_insufficient_does_not_converge():
    """覆盖不足 + 用户要求开始 → 提示剩余关键议程项并继续澄清（spec 场景）."""
    session = seeded_session()
    session.agenda[0].status = "answered"   # 1/3 < 80%
    session.agenda[0].answer = "RBAC"

    result = await turn(session, "可以开始了吗", llm_fn=fake_llm)
    assert result["converged"] is False
    cards = [e["data"] for e in result["events"]]
    assert any("尚未收敛" in c["title"] for c in cards)
    assert any(c["card"] == "question_card" for c in cards)  # 继续澄清


@pytest.mark.asyncio
async def test_full_lifecycle_to_convergence():
    clear_sessions()
    session = create_session()

    # 1) 首轮画像
    r1 = await turn(session, "我要做一个后台管理系统", llm_fn=fake_llm)
    assert len(r1["events"]) == 1 and r1["events"][0]["data"]["card"] == "summary_card"

    # 2) 回答 a1 → 提问 a2/a3
    r2 = await turn(session, "RBAC", item_id="a1", llm_fn=fake_llm)
    assert any(e["data"]["card"] == "question_card" for e in r2["events"])

    # 3) 回答 a2 → 覆盖 2/3 < 80% → 继续提问
    r3 = await turn(session, "多页导航", item_id="a2", llm_fn=fake_llm)
    assert any(e["data"]["card"] == "question_card" for e in r3["events"])
    assert coverage(session) < 1.0

    # 4) 回答 a3 → 覆盖达标 → 收敛前方案对比
    r4 = await turn(session, "后端接口", item_id="a3", llm_fn=fake_llm)
    assert any(e["data"]["card"] == "proposal_card" for e in r4["events"])
    assert coverage(session) == 1.0

    # 5) 选择方案 → 决策日志 + 收敛确认卡片
    r5 = await turn(session, "方案A", llm_fn=fake_llm)
    assert session.proposal_decided
    assert any(e["data"]["card"] == "confirm_card" for e in r5["events"])

    # 6) 用户确认 → 双因子满足 → 收敛
    r6 = await turn(session, "确认，可以开始", llm_fn=fake_llm)
    assert r6["converged"] is True
    assert session.requirements_state_json is not None
    # 收敛产物 = 结构化需求 + 决策日志 + 假设清单
    state = json.loads(session.requirements_state_json)
    assert state["vision"]["project_name"] == "后台管理系统"
    assert state["features"][0]["name"] == "用户管理"
    assert session.decisions
    assert session.assumptions is not None


@pytest.mark.asyncio
async def test_converged_session_idempotent():
    """收敛后再跑一轮（如用户继续输入）不破坏收敛状态与产物."""
    clear_sessions()
    session = create_session()
    await turn(session, "做一个后台管理系统", llm_fn=fake_llm)
    await turn(session, "RBAC", item_id="a1", llm_fn=fake_llm)
    await turn(session, "多页导航", item_id="a2", llm_fn=fake_llm)
    await turn(session, "后端接口", item_id="a3", llm_fn=fake_llm)
    await turn(session, "方案A", llm_fn=fake_llm)
    r = await turn(session, "确认，可以开始", llm_fn=fake_llm)
    assert r["converged"] is True
    state_json = session.requirements_state_json

    r2 = await turn(session, "随便再说一句", llm_fn=fake_llm)
    assert r2["converged"] is True
    assert session.requirements_state_json == state_json


# ── 收敛产物：to_requirements_state ──


@pytest.mark.asyncio
async def test_to_requirements_state_json_builds_requirements_state():
    session = seeded_session()
    state_json = await to_requirements_state_json(session, llm_fn=fake_llm)
    rs = RequirementsState.from_json(state_json)
    assert rs.vision.project_name == "后台管理系统"
    assert rs.vision.target_users[0].role == "管理员"
    assert rs.features[0].name == "用户管理"
    assert rs.features[0].confirmed is True
    assert rs.pages[0].page_type == "list"
    assert rs.page_details["P-01"].display_fields[0].name == "用户名"
    assert rs.data_entities[0].name == "User"


@pytest.mark.asyncio
async def test_to_requirements_state_json_falls_back_on_llm_failure():
    """LLM 结构化失败 → 降级为画像字段的最小状态，不阻塞收敛."""
    session = seeded_session()

    async def broken_llm(system_prompt: str, user_prompt: str) -> str:
        return "不认识的输出！！！"

    state_json = await to_requirements_state_json(session, llm_fn=broken_llm)
    rs = RequirementsState.from_json(state_json)
    # fallback 仍带有画像中的 vision 与 features
    assert rs.vision.project_name == "后台管理系统"
    assert rs.features[0].name == "用户管理"


# ── Servicer: BrainstormTurn RPC ──


def _make_servicer():
    from app.services.generation.servicer import GenerationServicer
    return GenerationServicer()


def _brainstorm_context():
    import grpc
    context = MagicMock(spec=grpc.aio.ServicerContext)
    context.cancelled.return_value = False
    return context


async def fake_llm_provider(provider, system_prompt: str, user_prompt: str, model: str = "glm-5.2") -> str:
    """_llm_generate_with_provider 的测试替身：忽略 provider 参数，复用 fake_llm 分发."""
    return await fake_llm(system_prompt, user_prompt)


@pytest.mark.asyncio
async def test_servicer_brainstorm_turn_creates_session_and_continues():
    from ai.v1.generation_pb2 import BrainstormTurnRequest

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.brainstorm._llm_generate_with_provider",
               new_callable=AsyncMock, side_effect=fake_llm_provider) as mock_llm:
        servicer = _make_servicer()
        # 首轮：创建会话
        r1 = await servicer.BrainstormTurn(
            BrainstormTurnRequest(text="我要做一个后台管理系统"), _brainstorm_context()
        )
    assert r1.generation_id
    assert r1.converged is False
    assert len(r1.events) == 1
    assert r1.events[0].event_type == "manager_message"
    data = json.loads(r1.events[0].data)
    assert data["card"] == "summary_card"
    assert data["data"]["profile"]["requirement_type"] == "admin_system"
    # fix #4：显式 provider 被线程化进 turn，而不是 set_provider 共享单例
    assert mock_llm.await_args.args[0] is mock_provider

    gid = r1.generation_id
    # 后续轮：带 session id 继续
    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.brainstorm._llm_generate_with_provider",
               new_callable=AsyncMock, side_effect=fake_llm_provider):
        r2 = await servicer.BrainstormTurn(
            BrainstormTurnRequest(text="RBAC", generation_id=gid, item_id="a1"),
            _brainstorm_context(),
        )
    assert r2.generation_id == gid
    assert any(
        json.loads(e.data)["card"] == "question_card" for e in r2.events
    )


@pytest.mark.asyncio
async def test_servicer_brainstorm_turn_does_not_touch_provider_singleton():
    """fix #4：BrainstormTurn 绝不调用 set_provider（共享单例不被并发换掉）."""
    from ai.v1.generation_pb2 import BrainstormTurnRequest

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider") as mock_set_provider, \
         patch("app.services.generation.brainstorm._llm_generate_with_provider",
               new_callable=AsyncMock, side_effect=fake_llm_provider):
        servicer = _make_servicer()
        await servicer.BrainstormTurn(
            BrainstormTurnRequest(text="做一个后台管理系统"), _brainstorm_context()
        )
    mock_set_provider.assert_not_called()


@pytest.mark.asyncio
async def test_servicer_brainstorm_turn_error_propagates():
    """LLM 抛错 → RPC 异常向上抛（gateway 转 502），会话不受污染."""
    from ai.v1.generation_pb2 import BrainstormTurnRequest

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.brainstorm._llm_generate_with_provider",
               new_callable=AsyncMock, side_effect=RuntimeError("provider down")):
        servicer = _make_servicer()
        with pytest.raises(RuntimeError):
            await servicer.BrainstormTurn(
                BrainstormTurnRequest(text="做一个后台"), _brainstorm_context()
            )


@pytest.mark.asyncio
async def test_stream_graph_loads_brainstorm_session_products():
    """_stream_graph 携带 brainstorm 会话 id → requirements_state_json/决策/假设 进入初始 state."""
    from ai.v1.generation_pb2 import GenerateRequest, Message as ProtoMessage
    from app.services.generation import brainstorm

    clear_sessions()
    session = brainstorm.create_session()
    session.converged = True
    session.requirements_state_json = REQUIREMENTS_JSON
    session.decisions = [{"topic": "方案选型", "choice": "方案A"}]
    session.assumptions = [{"item_id": "a3", "topic": "数据来源", "status": "assumed"}]

    captured: dict = {}

    class FakeRunner:
        def __init__(self, memory_db=None):
            self.memory_db = memory_db

        async def run(self, state, generation_id):
            captured["state"] = state
            captured["generation_id"] = generation_id
            yield {"event_type": "complete", "stage": "analysis", "data": {}}

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider"), \
         patch("app.services.generation.servicer.GraphRunner", FakeRunner):
        servicer = _make_servicer()
        request = GenerateRequest(
            generation_id=session.generation_id,
            model="glm-5.2",
            messages=[ProtoMessage(role="user", content="做一个后台管理系统")],
        )
        responses = []
        async for resp in servicer._stream_graph(session.generation_id, request, _brainstorm_context()):
            responses.append(resp)

    state = captured["state"]
    assert state["requirements_state_json"] == REQUIREMENTS_JSON
    assert state["brainstorm_decisions"] == session.decisions
    assert state["brainstorm_assumptions"] == session.assumptions
    assert responses  # 事件正常流出


@pytest.mark.asyncio
async def test_stream_graph_without_session_keeps_legacy_path():
    """无 brainstorm 会话（旧路径）→ requirements_state_json 保持 None."""
    from ai.v1.generation_pb2 import GenerateRequest, Message as ProtoMessage

    captured: dict = {}

    class FakeRunner:
        def __init__(self, memory_db=None):
            self.memory_db = memory_db

        async def run(self, state, generation_id):
            captured["state"] = state
            yield {"event_type": "complete", "stage": "analysis", "data": {}}

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider"), \
         patch("app.services.generation.servicer.GraphRunner", FakeRunner):
        servicer = _make_servicer()
        request = GenerateRequest(
            generation_id="no-session-123",
            model="glm-5.2",
            messages=[ProtoMessage(role="user", content="做一个后台管理系统")],
        )
        async for _ in servicer._stream_graph("no-session-123", request, _brainstorm_context()):
            pass
    assert captured["state"]["requirements_state_json"] is None


# ── 3.6 PRD 消费澄清产物 ──


@pytest.mark.asyncio
async def test_graph_phase1_prd_consumes_clarification_products():
    """graph phase-1 的 PRD 提示词包含结构化需求 + 决策日志 + 假设清单."""
    from app.services.generation.graph import GraphRunner

    captured: dict = {}

    async def fake_prd_llm(system_prompt, user_content, **kwargs):
        captured["user_prompt"] = user_content
        return ("# 需求规格文档\n## 1. 功能概述\n...\n"
                "## 2. 功能模块\n...\n## 3. 页面结构\n...\n")

    state = {
        "requirement": "做一个后台管理系统",
        "messages": [{"role": "user", "content": "做一个后台管理系统"}],
        "requirements_state_json": REQUIREMENTS_JSON,
        "brainstorm_decisions": [{"topic": "方案选型", "choice": "方案A"}],
        "brainstorm_assumptions": [{"item_id": "a3", "topic": "数据来源", "status": "assumed"}],
    }
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock, side_effect=fake_prd_llm):
        runner = GraphRunner()
        events = []
        async for ev in runner.run(state, "gen-prd-test"):
            events.append(ev)

    assert captured["user_prompt"]
    assert "后台管理系统" in captured["user_prompt"]
    assert "澄清产物" in captured["user_prompt"] or "结构化需求" in captured["user_prompt"]
    assert "假设清单" in captured["user_prompt"]
    assert "决策日志" in captured["user_prompt"]
    # 事件流正常：PRD 生成完成并停等确认
    assert any(e["event_type"] == "prd_generate_done" for e in events)
    assert any(e["event_type"] == "human_confirm_required" for e in events)


@pytest.mark.asyncio
async def test_graph_phase1_prd_legacy_prompt_without_products():
    """无澄清产物 → 走旧的对话上下文提示词（向后兼容）."""
    from app.services.generation.graph import GraphRunner

    captured: dict = {}

    async def fake_prd_llm(system_prompt, user_content, **kwargs):
        captured["user_prompt"] = user_content
        return "# 需求规格文档\n## 1. 功能概述\n...\n## 2. 功能模块\n...\n## 3. 页面结构\n...\n"

    state = {
        "requirement": "做一个后台管理系统",
        "messages": [{"role": "user", "content": "做一个后台管理系统"}],
        "requirements_state_json": None,
    }
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock, side_effect=fake_prd_llm):
        runner = GraphRunner()
        async for _ in runner.run(state, "gen-prd-legacy"):
            pass
    assert "对话上下文" in captured["user_prompt"]
    assert "澄清产物" not in captured["user_prompt"]


@pytest.mark.asyncio
async def test_analysis_node_consumes_clarification_products():
    from app.services.generation.nodes import analysis_node

    captured: dict = {}

    async def fake_prd_llm(system_prompt, user_content, **kwargs):
        captured["user_prompt"] = user_content
        return "# 需求规格文档\n## 2. 功能模块\n...\n## 3. 页面结构\n...\n"

    state = {
        "requirement": "做一个后台管理系统",
        "messages": [{"role": "user", "content": "做一个后台管理系统"}],
        "requirements_state_json": REQUIREMENTS_JSON,
        "brainstorm_decisions": [{"topic": "方案选型", "choice": "方案A"}],
        "brainstorm_assumptions": [{"item_id": "a3", "topic": "数据来源", "status": "assumed"}],
        "qa_rounds": 0,
    }
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock, side_effect=fake_prd_llm):
        out = await analysis_node(state)

    assert "假设清单" in captured["user_prompt"]
    assert "决策日志" in captured["user_prompt"]
    assert out["stage_phase"] == "complete"


def test_analysis_prd_prompt_mentions_assumptions_section():
    """ANALYSIS_PRD_PROMPT 要求「## 6. 假设清单」章节（有假设时）."""
    from app.services.generation.nodes import ANALYSIS_PRD_PROMPT
    assert "## 6. 假设清单" in ANALYSIS_PRD_PROMPT


# ── 代码评审修复回归测试（fix #1/#2/#5/#6/#10） ──


def confirm_window_session(gid: str = "t-confirm") -> BrainstormSession:
    """构造「方案已定、覆盖达标（4/5=80%）、a5 待答」的收敛确认窗口会话."""
    session = seeded_session(gid)
    session.agenda.append(AgendaItem(id="a4", topic="报表", reason="r", impact="ui"))
    session.agenda.append(AgendaItem(id="a5", topic="消息通知", reason="r", impact="tech"))
    for i, item in enumerate(session.agenda[:4]):
        item.status = "answered"
        item.answer = f"答案{i}"
    session.proposal_shown = True
    session.proposal_decided = True
    session.proposals = [
        {"name": "方案A", "scope": "s", "interaction": "i", "pros": ["p"], "costs": ["c"]},
        {"name": "方案B", "scope": "s", "interaction": "i", "pros": ["p"], "costs": ["c"]},
    ]
    return session


@pytest.mark.asyncio
async def test_answer_containing_confirm_does_not_converge():
    """fix #1：普通回答里的"确认"字样（如"确认收货流程"）不得触发收敛，须落成议程答案."""
    session = confirm_window_session()

    result = await turn(session, "确认收货流程", llm_fn=fake_llm)
    assert result["converged"] is False
    # 文本落到了待答项 a5，而不是触发确认
    assert session.agenda[4].status == "answered"
    assert session.agenda[4].answer == "确认收货流程"
    assert session.user_confirmed is False
    # 仍停在确认窗口（重新发确认卡）
    assert any(e["data"]["card"] == "confirm_card" for e in result["events"])


@pytest.mark.asyncio
async def test_short_pure_confirm_converges():
    """fix #1：无待答项时的短整句确认（"确认，可以开始"）→ 收敛."""
    session = confirm_window_session()
    session.agenda[4].status = "answered"   # 无待答项

    result = await turn(session, "确认，可以开始", llm_fn=fake_llm)
    assert result["converged"] is True
    assert session.requirements_state_json is not None


@pytest.mark.asyncio
async def test_confirm_card_option_converges_even_with_pending():
    """fix #1：确认卡显式选项「确认开始」即使有待答项也视为确认（覆盖度已达标）."""
    session = confirm_window_session()      # a5 仍待答，覆盖 4/5=80% 达标

    result = await turn(session, "确认开始", llm_fn=fake_llm)
    assert result["converged"] is True
    assert session.user_confirmed is True


@pytest.mark.asyncio
async def test_confirm_card_option_does_not_skip_coverage_factor():
    """fix #1/#5：确认卡选项也不能绕过覆盖度因子（双因子收敛）."""
    session = confirm_window_session()
    session.agenda.append(AgendaItem(id="a6", topic="导出", reason="r", impact="scope"))
    # 覆盖 4/6 ≈ 66.7% < 80% → 即便点「确认开始」也不收敛
    result = await turn(session, "确认开始", llm_fn=fake_llm)
    assert result["converged"] is False
    assert session.user_confirmed is False


@pytest.mark.asyncio
async def test_proposal_phase_free_text_is_feedback_not_answer():
    """fix #2：方案对比悬而未决时，非选项文本 = 方案反馈 → 带反馈重出方案，绝不落成议程答案."""
    session = seeded_session()
    for item in session.agenda:
        item.status = "answered"
        item.answer = "已答"
    await turn(session, "", llm_fn=fake_llm)          # 出方案对比
    assert session.proposal_shown and not session.proposal_decided
    before = [a.answer for a in session.agenda]

    captured: list[tuple[str, str]] = []

    async def recording_llm(system_prompt: str, user_prompt: str) -> str:
        captured.append((system_prompt, user_prompt))
        return await fake_llm(system_prompt, user_prompt)

    result = await turn(session, "方案A 但首页做简单点", llm_fn=recording_llm)
    # 议程答案未被污染
    assert [a.answer for a in session.agenda] == before
    assert all(a.status == "answered" for a in session.agenda)
    # 重新输出方案对比，且反馈进入了 LLM 上下文
    assert any(e["data"]["card"] == "proposal_card" for e in result["events"])
    assert any(
        "方案A 但首页做简单点" in up for _, up in captured
    )
    assert session.proposal_decided is False


async def dynamic_questions_llm(system_prompt: str, user_prompt: str) -> str:
    """为 user_prompt 中列出的待提问项（- aN: ...）动态生成问题."""
    if "为指定议程项生成提问" in system_prompt:
        item_ids = re.findall(r"- (a\d+):", user_prompt)
        return json.dumps({
            "questions": [
                {"item_id": i, "question": f"{i} 的提问", "options": ["选项A", "选项B"]}
                for i in item_ids
            ],
        }, ensure_ascii=False)
    return await fake_llm(system_prompt, user_prompt)


@pytest.mark.asyncio
async def test_have_questions_triggers_question_round_not_confirm():
    """fix #2：确认卡「还有疑问」→ 走提问轮而不是重发确认卡."""
    session = confirm_window_session()      # a5 待答

    result = await turn(session, "还有疑问", llm_fn=dynamic_questions_llm)
    assert result["converged"] is False
    assert any(e["data"]["card"] == "question_card" for e in result["events"])
    assert not any(e["data"]["card"] == "confirm_card" for e in result["events"])


def test_parse_structured_first_brace_extraction():
    """fix #5：JSON 对象块后的说明文字不影响解析."""
    schema = {"a": ""}
    raw = '```json\n{"a": "x"}\n```\n（说明文字跟在后面，不应影响解析）'
    assert parse_structured(raw, schema) == {"a": "x"}


def test_parse_structured_coerces_wrong_types():
    """fix #5：合法 JSON 但类型不符 → 按 schema 类型归并，不崩溃."""
    from app.services.generation.brainstorm import _profile_schema

    schema = _profile_schema()
    parsed = parse_structured(json.dumps({
        "requirement_type": 123,
        "target_users": ["管理员"],
        "success_criteria": "快",
        "candidate_plans": "不要",
        "ambiguities": [{"topic": "权限", "reason": "r", "impact": "design"}],
    }), schema)
    assert parsed["requirement_type"] == "123"
    assert parsed["target_users"] == [{"role": "", "description": ""}]   # 非 dict 元素 → 空默认值
    assert parsed["success_criteria"] == []
    assert parsed["candidate_plans"] == []
    assert parsed["ambiguities"][0]["topic"] == "权限"


@pytest.mark.asyncio
async def test_profile_card_survives_wrong_typed_llm_output():
    """fix #5：首轮画像 LLM 输出类型错乱 → 画像卡片正常构建（不再 502）."""
    clear_sessions()
    session = create_session()

    async def bad_profile_llm(system_prompt: str, user_prompt: str) -> str:
        if "为指定议程项生成提问" in system_prompt:
            return QUESTIONS_JSON
        return json.dumps({
            "requirement_type": "admin_system",
            "target_users": ["管理员"],
            "success_criteria": "快",
            "ambiguities": [{"topic": "权限模型", "reason": "不明确会导致权限设计偏离", "impact": "design"}],
        }, ensure_ascii=False)

    result = await turn(session, "做一个后台管理系统", llm_fn=bad_profile_llm)
    assert len(result["events"]) == 1
    profile = result["events"][0]["data"]["data"]["profile"]
    assert profile["requirement_type"] == "admin_system"
    assert profile["target_users"] == [{"role": "", "description": ""}]
    assert len(session.agenda) == 1


@pytest.mark.asyncio
async def test_empty_agenda_coverage_zero_does_not_converge():
    """fix #6：首轮画像无模糊点（空议程）→ 覆盖度 0.0，不得借覆盖度因子收敛."""
    clear_sessions()
    session = create_session()

    async def empty_profile_llm(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "requirement_type": "tool",
            "project_name": "", "core_problem": "", "target_users": [],
            "success_criteria": [], "scope_note": "", "ambiguities": [],
            "candidate_plans": [], "features": [], "pages": [],
            "tech_constraints": {}, "data_entities": [],
        })

    result = await turn(session, "做一个工具", llm_fn=empty_profile_llm)
    assert coverage(session) == 0.0
    assert result["coverage"] == 0.0
    assert result["converged"] is False


@pytest.mark.asyncio
async def test_confirm_request_blocker_proposal_when_coverage_met():
    """fix #10：覆盖达标但方案未定时，确认请求提示真实阻塞点（方案选型）."""
    session = seeded_session()
    for i, item in enumerate(session.agenda):
        item.status = "answered"
        item.answer = f"答案{i}"

    result = await turn(session, "可以开始了吗", llm_fn=fake_llm)
    cards = [e["data"] for e in result["events"]]
    blockers = [c for c in cards if c.get("data", {}).get("blocker") == "proposal"]
    assert blockers, "应输出 blocker=proposal 的提示卡"
    assert blockers[0]["title"] == "还需选定方案"
    assert any(c["card"] == "proposal_card" for c in cards)  # 方案对比随之而来
