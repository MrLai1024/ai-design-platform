"""Task 11.2 — 端到端全流程演练.

新需求全流程: 头脑风暴 (议程→画像→提问→方案→收敛) → 确认 → 图运行
(PRD → gate → 设计双产物 → L1/L2 gate → Planner/Executor → Verifier → gate)
→ E2E (Designer → 覆盖矩阵卡片 → 用例 → 执行交接 → Diagnoser → gate → END)。

断言:
- 对话框消息完整性 — manager_message 卡片按序 (summary_card/verdict_card ×3
  阶段 + coverage_matrix + e2e 终裁); 头脑风暴卡片 (question_card/
  proposal_card/confirm_card) 在会话事件中; worker 产物事件不出 manager_message。
- 记忆产物落盘 — requirements.md / architecture.json / architecture.md /
  decisions.md / state.json / contracts.json / index.json 阶段完成 /
  e2e/cases/*.json + manifest.json。
- 最终裁决 pass + END (e2e_passed, checkpoint 无挂起 worker)。

全部 LLM 调用走 ScriptedFlowProvider (nodes._provider), 无真实 LLM / 网络。
"""

import json
import os

import pytest

from app.services.generation import nodes
from app.services.generation.brainstorm import clear_sessions, create_session, turn as brainstorm_turn

from .drill_helpers import (
    DAG_TWO,
    DESIGN_MD,
    DESIGNER_JSON,
    FILE_APP,
    FILE_HOME,
    L2_PASS,
    MARK_DESIGN_MD,
    MARK_DESIGNER,
    MARK_L2,
    MARK_PLANNER,
    MARK_PRD,
    MARK_SPEC,
    PRD_OK,
    SPEC_SM,
    ScriptedFlowProvider,
    base_state,
    cards_of,
    events_of,
    project_root_of,
    token_turn,
)
from .test_brainstorm import PROFILE_JSON, PROPOSALS_JSON, QUESTIONS_JSON, REQUIREMENTS_JSON, fake_llm as bs_fake_llm


async def _converged_brainstorm():
    """真实头脑风暴引擎: 画像 → 提问 → 方案 → 收敛 (scripted LLM)。"""
    clear_sessions()
    session = create_session()
    events: list[dict] = []
    for text, item_id in [
        ("我要做一个后台管理系统", None),
        ("RBAC", "a1"),
        ("多页导航", "a2"),
        ("后端接口", "a3"),
        ("方案A", None),
        ("确认，可以开始", None),
    ]:
        r = await brainstorm_turn(session, text, item_id=item_id, llm_fn=bs_fake_llm)
        events.extend(r["events"])
        if r["converged"]:
            break
    return session, events


def _state_from_session(session) -> dict:
    # 用双功能点结构化需求 (F-01/F-02) 作为澄清产物 — 下游 E2E 需求点以此为 id。
    from .drill_helpers import REQUIREMENTS_STATE_JSON

    return base_state(
        requirement="我要做一个后台管理系统",
        requirements_state_json=REQUIREMENTS_STATE_JSON,
        brainstorm_decisions=list(session.decisions),
        brainstorm_assumptions=list(session.assumptions),
    )


@pytest.mark.asyncio
async def test_full_flow_dialog_and_memory():
    from app.services.generation.graph import GraphRunner
    from app.services.generation.incremental import load_e2e_manifest
    from app.services.generation.memory import read_index

    # ── 1. 头脑风暴 (真实引擎 + scripted LLM) ──
    session, bs_events = await _converged_brainstorm()
    assert session.converged
    bs_cards = [e["data"]["card"] for e in bs_events if e["event_type"] == "manager_message"]
    # 画像卡片 + 提问卡片 + 方案对比 + 收敛确认
    assert "summary_card" in bs_cards
    assert "question_card" in bs_cards
    assert "proposal_card" in bs_cards
    assert "confirm_card" in bs_cards

    # ── 2. 图运行 (真实 GraphRunner + ScriptedFlowProvider) ──
    provider = ScriptedFlowProvider()
    provider.script(MARK_PRD, token_turn(PRD_OK))
    provider.script(MARK_DESIGN_MD, token_turn(DESIGN_MD))
    provider.script(MARK_SPEC, token_turn(json.dumps(SPEC_SM, ensure_ascii=False)))
    provider.script(MARK_L2, token_turn(L2_PASS))
    provider.script(MARK_PLANNER, token_turn(DAG_TWO))
    provider.files = {"src/App.vue": FILE_APP, "src/pages/Home.vue": FILE_HOME}
    provider.enable_executor_heuristic()
    provider.script(MARK_DESIGNER, token_turn(DESIGNER_JSON))

    old = nodes._provider
    nodes._provider = provider
    try:
        state = _state_from_session(session)
        gid = "gen-e2e-flow"
        state["generation_id"] = gid
        runner = GraphRunner()
        all_events: list[dict] = []   # 全流程事件汇总 (worker 发言不变式断言)

        async def _collect(agen):
            evs = [ev async for ev in agen]
            all_events.extend(evs)
            return evs

        # run #1 — 阶段 1: PRD + analysis gate pass → 停等确认
        events = await _collect(runner.run(state, gid))
        assert events_of(events, "prd_generate_done")
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[0]["data"]["node"] == "analysis"
        assert verdicts[0]["data"]["decision"] == "pass"
        assert events_of(events, "human_confirm_required")
        assert [c["card"] for c in cards_of(events)] == ["summary_card", "verdict_card"]

        # run #2 — 阶段 2: 设计双产物 + L1/L2 gate pass
        events = await _collect(runner.resume(gid))
        assert events_of(events, "design_gen_done")
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "design"
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert [c["card"] for c in cards_of(events)] == ["summary_card", "verdict_card"]

        # run #3 — 阶段 3: Planner → Executor×2 → Verifier → gate pass
        events = await _collect(runner.resume(gid))
        assert events_of(events, "planner_dag")
        assert len(events_of(events, "task_complete")) == 2
        verifier_events = events_of(events, "verifier_result")
        assert verifier_events and verifier_events[-1]["data"]["passed"] is True
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "code"
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert [c["card"] for c in cards_of(events)] == ["summary_card", "verdict_card"]
        # dispatch 契约: 验收标准 + 工具边界 (1.3/1.4)
        dc = state.get("dispatch_contract") or {}
        assert dc.get("task_id") == "code"
        assert dc.get("acceptance_criteria")
        assert isinstance(dc.get("tool_bounds"), list)
        assert dc.get("tier") == "S"

        # run #4 — 阶段 4 入口: gate (code pass 裁决去重) → 停在 e2e 中断处
        events = await _collect(runner.resume(gid))
        confirms = events_of(events, "human_confirm_required")
        assert confirms and confirms[0]["stage"] == "e2e"
        assert "把关通过" in confirms[0]["data"]["message"]

        # run #5 — e2e Designer → 覆盖矩阵 → gate pass → 停等用例确认
        events = await _collect(runner.resume(gid))
        assert events_of(events, "e2e_cases_gen_done")
        coverage = cards_of(events, "coverage_matrix")
        assert coverage and coverage[0]["data"]["matrix"]["F-01"]["case_ids"] == ["tc-f01-1"]
        assert coverage[0]["data"]["passed"] is True      # 全需求点覆盖 (5.2)
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "e2e"
        assert verdicts[-1]["data"]["decision"] == "pass"
        # 消息序列: coverage_matrix 先于 e2e 裁决卡
        seq = [c["card"] for c in cards_of(events)]
        assert seq == ["coverage_matrix", "summary_card", "verdict_card"]

        # run #6 — 用例确认 → 执行交接 (无二次确认)
        events = await _collect(runner.resume(gid, e2e_confirmed=True))
        exec_start = events_of(events, "e2e_execute_start")
        assert exec_start and exec_start[0]["data"]["test_cases"][0]["id"] == "tc-f01-1"
        assert not events_of(events, "human_confirm_required")

        # run #7 — 执行结果 (全部通过) → Diagnoser (无失败) → gate → END
        results = [
            {"case_id": "tc-f01-1", "passed": True, "status": "passed"},
            {"case_id": "tc-f02-1", "passed": True, "status": "passed"},
        ]
        events = await _collect(runner.resume_after_e2e(gid, results))
        complete = events_of(events, "e2e_complete")
        assert complete and complete[-1]["data"]["passed"] is True
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "e2e"
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert [c["card"] for c in cards_of(events)] == ["summary_card", "verdict_card"]

        # 终态: e2e 通过 + 无挂起 worker (END)
        config = {"configurable": {"thread_id": gid}}
        snap = runner.app.get_state(config)
        assert snap.values["e2e_passed"] is True
        assert not snap.next

        # ── 3. worker 不直接发言 (1.2): 产物事件 ≠ 对话框消息 ──
        # 全流程 (7 段 run/resume) 汇总: manager_message 只携带 Manager 卡片
        # 类型 — worker 产出 (doc_chunk/file_chunk/e2e_cases_gen_done 等) 永不
        # 作为对话框消息出现。顺序断言由各 run 的卡片序列检查覆盖。
        card_types = {e["data"]["card"] for e in all_events if e["event_type"] == "manager_message"}
        assert card_types <= {"summary_card", "verdict_card", "coverage_matrix"}
        # 顺序执行纪律 (5.6 S/M 档): 无并行 executor — provider 并发窗口恒为 1
        assert provider.max_inflight == 1
    finally:
        nodes._provider = old

    # ── 4. 记忆产物 (7.2/7.3/4.5) ──
    root = project_root_of(state)
    mem = os.path.join(root, ".ai-memory")
    assert os.path.isfile(os.path.join(mem, "index.json"))
    assert os.path.isfile(os.path.join(mem, "spec", "requirements.md"))
    with open(os.path.join(mem, "spec", "requirements.md"), encoding="utf-8") as f:
        assert f.read() == PRD_OK
    with open(os.path.join(mem, "spec", "architecture.json"), encoding="utf-8") as f:
        assert json.load(f) == SPEC_SM
    assert os.path.isfile(os.path.join(mem, "spec", "architecture.md"))
    assert os.path.isfile(os.path.join(mem, "spec", "decisions.md"))
    assert os.path.isfile(os.path.join(mem, "state", "state.json"))
    assert os.path.isfile(os.path.join(mem, "state", "contracts.json"))
    index = read_index(root)
    assert index["stages"].get("analysis") == "done"
    assert index["stages"].get("design") == "done"
    assert index["stages"].get("code") == "done"
    # 决策日志包含头脑风暴决策与 Manager 把关 (3.8)
    decisions = open(os.path.join(mem, "spec", "decisions.md"), encoding="utf-8").read()
    assert "方案选型" in decisions
    # e2e 用例入库 (5.12)
    cases_dir = os.path.join(root, "e2e", "cases")
    assert os.path.isdir(cases_dir)
    case_files = [f for f in os.listdir(cases_dir) if f.endswith(".json")]
    assert len(case_files) == 2
    manifest = load_e2e_manifest(root)
    assert manifest.get("tc-f01-1") == "active"
    assert manifest.get("tc-f02-1") == "active"
    # 生成文件落盘 (执行产物)
    assert os.path.isfile(os.path.join(root, "src", "App.vue"))
    assert os.path.isfile(os.path.join(root, "src", "pages", "Home.vue"))


@pytest.mark.asyncio
async def test_brainstorm_cards_present_in_full_flow():
    """头脑风暴卡片类型存在性 — 与全流程演练共享, 单独可快速回归。"""
    session, events = await _converged_brainstorm()
    assert session.converged
    assert session.requirements_state_json
    assert session.decisions
    cards = [e["data"]["card"] for e in events if e["event_type"] == "manager_message"]
    for expected in ("summary_card", "question_card", "proposal_card", "confirm_card"):
        assert expected in cards, f"缺失 {expected}: {cards}"
