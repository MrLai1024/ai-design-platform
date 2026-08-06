"""Task 11.4 — 增量开发演练.

已有应用加功能 → diff → manifest → 回归对账:

1. **完整生成** (真实编排, 持久化记忆): 头脑风暴产物 → PRD → Spec → 实现 →
   E2E Designer 出用例落盘 (requirements.md / architecture.json / state.json /
   index 阶段 done / e2e/cases + manifest.json)。
2. **增量入口** (同 generation_id, incremental_mode): diff 卡片 (新增 数据看板)
   → manifest 确认卡 → 历史用例处置清单 (既有用例 keep) → 逐级确认。
3. **增量流水线**: delta PRD (增量上下文 + manifest 框定) → 合并 Spec →
   delta 实现 (只动受影响模块 — 存量文件字节不动, 断言文件清单) → gate 通过。
4. **回归对账**: e2e 回归模式保留既有用例 + 新增用例 → 结果全通过 →
   regression accounting → changes/ 记录定稿 + state.json 功能推进 + index 版本。
"""

import json
import os

import pytest

from app.services.generation import nodes
from app.services.generation.graph import GraphRunner
from app.services.generation.incremental import load_e2e_manifest, read_change_record

from .drill_helpers import (
    DAG_INC_DELTA,
    DAG_TWO,
    DESIGN_MD,
    DESIGNER_INC_JSON,
    FILE_APP,
    FILE_BOARD,
    FILE_HOME,
    L2_PASS,
    MANIFEST_JSON,
    MARK_DESIGN_MD,
    MARK_DESIGNER,
    MARK_L2,
    MARK_MANIFEST,
    MARK_PLANNER,
    MARK_PRD,
    MARK_SPEC,
    PRD_INC,
    PRD_OK,
    REQUIREMENTS_STATE_INC_JSON,
    REQUIREMENTS_STATE_JSON,
    SPEC_INC,
    SPEC_SM,
    ScriptedFlowProvider,
    base_state,
    cards_of,
    events_of,
    project_root_of,
    token_turn,
)

GID = "gen-inc-drill"


def _full_gen_provider() -> ScriptedFlowProvider:
    """完整生成 + 增量流水线的全 LLM 脚本。"""
    provider = ScriptedFlowProvider()
    provider.script(MARK_PRD,
                    token_turn(PRD_OK),             # [1] 首轮完整 PRD (F-01/F-02)
                    token_turn(PRD_INC))            # [6] 增量 PRD (含 F-03)
    provider.script(MARK_DESIGN_MD,
                    token_turn(DESIGN_MD),          # [2] 首轮设计
                    token_turn(DESIGN_MD))          # [7] 增量设计
    provider.script(MARK_SPEC,
                    token_turn(json.dumps(SPEC_SM, ensure_ascii=False)),   # [3]
                    token_turn(json.dumps(SPEC_INC, ensure_ascii=False)))  # [8] 合并 Spec
    provider.script(MARK_L2,
                    token_turn(L2_PASS),            # [4]
                    token_turn(L2_PASS))            # [9]
    provider.script(MARK_PLANNER,
                    token_turn(DAG_TWO),            # [5] 首轮任务 (App.vue + Home.vue)
                    token_turn(DAG_INC_DELTA))      # [10] 增量 delta 任务 (仅新文件)
    provider.files = {
        "src/App.vue": FILE_APP,
        "src/pages/Home.vue": FILE_HOME,
        "src/pages/DataBoard.vue": FILE_BOARD,
    }
    provider.enable_executor_heuristic()
    provider.script(MARK_MANIFEST, token_turn(MANIFEST_JSON))   # [6] 变更 manifest
    provider.script(MARK_DESIGNER, token_turn(DESIGNER_INC_JSON))  # [11] 回归模式 Designer
    return provider


@pytest.mark.asyncio
async def test_incremental_full_cycle_drill():
    from app.services.generation.memory import read_index

    provider = _full_gen_provider()
    old = nodes._provider
    nodes._provider = provider
    try:
        # ── 1. 完整生成 (持久化记忆) ──
        state = base_state(
            generation_id=GID,
            requirements_state_json=REQUIREMENTS_STATE_JSON,   # F-01/F-02 (既有应用)
            brainstorm_decisions=[{"topic": "方案选型", "choice": "方案A"}],
            brainstorm_assumptions=[{"item_id": "a3", "topic": "数据来源", "status": "assumed"}],
        )
        runner = GraphRunner()
        [ev async for ev in runner.run(state, GID)]                              # 阶段 1
        [ev async for ev in runner.resume(GID)]                                  # 阶段 2
        [ev async for ev in runner.resume(GID)]                                  # 阶段 3
        [ev async for ev in runner.resume(GID)]                                  # 阶段 4 入口
        events = [ev async for ev in runner.resume(GID)]                         # e2e Designer
        assert events_of(events, "e2e_cases_gen_done")

        root = project_root_of(state)
        index = read_index(root)
        assert index["stages"].get("analysis") == "done"
        assert index["stages"].get("design") == "done"
        assert index["stages"].get("code") == "done"
        manifest0 = load_e2e_manifest(root)
        assert manifest0.get("tc-f01-1") == "active"
        assert manifest0.get("tc-f02-1") == "active"
        existing_app = {
            rel: content
            for rel, content in json.loads(state["code_result"]).items()
        }

        # ── 2. 增量入口: diff → manifest → 处置 (逐级确认) ──
        state2 = base_state(
            generation_id=GID,
            requirement="新需求：\n- 用户管理\n- 订单管理\n- 数据看板",
            requirements_state_json=REQUIREMENTS_STATE_INC_JSON,  # F-01/F-02/F-03
            incremental_mode=True,
        )
        runner2 = GraphRunner()
        events = [ev async for ev in runner2.run(state2, GID)]
        cards = cards_of(events)
        assert any("增量变更清单" in (c.get("content") or "") for c in cards)
        assert state2["incremental_diff"]["added"] == ["数据看板"]           # 8.1 diff
        assert "数据看板" in (cards[-1].get("content") or "")

        # manifest 确认 (provider 第 6 轮)
        events = [ev async for ev in runner2.resume(GID)]
        cards = cards_of(events)
        assert any("变更 manifest" in (c.get("content") or "") for c in cards)
        assert state2["change_manifest"]["type"] == "new_feature"
        assert state2["change_manifest"]["affected_modules"] == ["src/pages/DataBoard.vue"]
        assert read_change_record(root, state2["change_id"])["status"] == "draft"  # 草稿记录

        # 历史用例处置清单: 既有 active 用例 keep (8.4)
        events = [ev async for ev in runner2.resume(GID)]
        cards = cards_of(events)
        assert any("历史用例处置清单" in (c.get("content") or "") for c in cards)
        dispositions = {d["case_id"]: d for d in state2["incremental_dispositions"]}
        assert dispositions["tc-f01-1"]["disposition"] == "keep"
        assert dispositions["tc-f02-1"]["disposition"] == "keep"

        # ── 3. 增量流水线: delta PRD → 合并 Spec → delta 实现 ──
        events = [ev async for ev in runner2.resume(GID)]                       # 阶段 1 (delta PRD)
        assert events_of(events, "prd_generate_done")
        prd_prompts = [t for m, t in zip(provider.calls, provider.user_texts) if m == MARK_PRD]
        assert "增量开发上下文" in prd_prompts[-1]                              # delta 框定 (8.3)
        assert "数据看板" in prd_prompts[-1]

        events = [ev async for ev in runner2.resume(GID)]                       # 阶段 2 (增量设计)
        assert events_of(events, "design_gen_done")
        spec_prompts = [t for m, t in zip(provider.calls, provider.user_texts) if m == MARK_SPEC]
        assert "已有架构 Spec（增量开发" in spec_prompts[-1]                    # 合并 Spec 指令
        assert state2["architecture_spec"]["pages"][1]["name"] == "数据看板"

        events = [ev async for ev in runner2.resume(GID)]                       # 阶段 3 (delta 实现)
        assert events_of(events, "task_complete")
        verifier_events = events_of(events, "verifier_result")
        assert verifier_events and verifier_events[-1]["data"]["passed"] is True
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "code"
        assert verdicts[-1]["data"]["decision"] == "pass"

        # 存量文件不动 (8.3): 文件清单 = 旧 + 新; 旧文件内容字节一致
        after = state2["generated_files"]
        assert set(after) == set(existing_app) | {"src/pages/DataBoard.vue"}
        for rel, content in existing_app.items():
            assert after[rel] == content, f"存量文件被改动: {rel}"

        # ── 4. e2e 回归 + 对账 + changes/ 记录 ──
        [ev async for ev in runner2.resume(GID)]                                # 阶段 4 入口
        events = [ev async for ev in runner2.resume(GID)]                       # 回归模式 Designer
        assert events_of(events, "e2e_cases_gen_done")
        case_ids = events_of(events, "e2e_cases_gen_done")[-1]["data"]["cases"]
        assert [c["id"] for c in case_ids] == ["tc-f01-1", "tc-f02-1", "tc-f03-1"]
        [ev async for ev in runner2.resume(GID, e2e_confirmed=True)]            # 执行交接
        results = [
            {"case_id": "tc-f01-1", "passed": True, "status": "passed"},
            {"case_id": "tc-f02-1", "passed": True, "status": "passed"},
            {"case_id": "tc-f03-1", "passed": True, "status": "passed"},
        ]
        events = [ev async for ev in runner2.resume_after_e2e(GID, results)]    # 对账 → END
        accounting = events_of(events, "e2e_regression_accounting")
        assert accounting and accounting[0]["data"]["counts"]["passed"] == 3
        assert events_of(events, "e2e_complete")[-1]["data"]["passed"] is True
        final_verdict = events_of(events, "manager_verdict")[-1]
        assert final_verdict["data"]["node"] == "e2e"
        assert final_verdict["data"]["decision"] == "pass"
    finally:
        nodes._provider = old

    # ── 5. changes/ 记录 + state.json 推进 + index 版本 (8.6) ──
    from app.services.generation import memory as mem

    record = read_change_record(root, state2["change_id"])
    assert record is not None and record["status"] == "completed"
    assert record["verdict"]["decision"] == "pass"
    state_json = mem._read_json(root, mem.STATE_JSON_PATH)
    ids = {f["id"] for f in state_json["features"]}
    assert "F-01" in ids and "F-03" in ids                 # 新功能进入功能状态
    index3 = read_index(root)
    assert index3["change_revision"] == 1
    assert index3["last_change_id"] == state2["change_id"]
    # 新用例入库
    manifest3 = load_e2e_manifest(root)
    assert manifest3.get("tc-f03-1") == "active"
    assert os.path.isfile(os.path.join(root, "src", "pages", "DataBoard.vue"))
