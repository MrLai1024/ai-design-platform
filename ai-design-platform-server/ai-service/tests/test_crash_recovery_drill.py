"""Task 11.5 (含 11.3-d) — 崩溃恢复演练.

代码节点中断后重启恢复:
1. 跑通 分析+设计 (落盘: requirements.md / architecture.json / index 阶段 done);
2. 代码阶段中途"进程崩溃" (abandon runner — 执行器写完首个文件后不再消费,
   无 gate 裁决, 代码阶段未标记完成);
3. 新 runner 同一 generation_id → ``load_app_state`` 重建已完成阶段 →
   阶段 1/2 跳过 → 代码阶段续跑至完成 → 产物一致。

断言: index.json 阶段推进 (analysis/design 恢复, code 完成)、恢复运行无
prd_generate_start/design_gen_done、最终 gate pass、state.json/contracts.json
落盘、磁盘代码产物与 code_result 一致。全部 LLM 走 ScriptedFlowProvider。
"""

import json

import pytest

from app.services.generation import nodes
from app.services.generation.graph import GraphRunner
from app.services.generation.memory import load_app_state, read_index

from .drill_helpers import (
    DAG_ONE,
    DESIGN_MD,
    FILE_APP,
    L2_PASS,
    MARK_DESIGN_MD,
    MARK_L2,
    MARK_PLANNER,
    MARK_PRD,
    MARK_SPEC,
    PRD_OK,
    SPEC_SM,
    ScriptedFlowProvider,
    base_state,
    events_of,
    project_root_of,
    token_turn,
)


def _script_full_provider(provider: ScriptedFlowProvider) -> ScriptedFlowProvider:
    provider.script(MARK_PRD, token_turn(PRD_OK))
    provider.script(MARK_DESIGN_MD, token_turn(DESIGN_MD))
    provider.script(MARK_SPEC, token_turn(json.dumps(SPEC_SM, ensure_ascii=False)))
    provider.script(MARK_L2, token_turn(L2_PASS))
    # planner 两次: 崩溃前阶段 3 + 恢复后阶段 3
    provider.script(MARK_PLANNER, token_turn(DAG_ONE), token_turn(DAG_ONE))
    provider.files = {"src/App.vue": FILE_APP}
    provider.enable_executor_heuristic()
    return provider


@pytest.mark.asyncio
async def test_crash_mid_code_resume_completes_pipeline():
    gid = "gen-crash-1"
    provider = _script_full_provider(ScriptedFlowProvider())
    old = nodes._provider
    nodes._provider = provider
    try:
        # ── 1. 分析 + 设计跑通 (落盘) ──
        state = base_state(generation_id=gid)
        runner = GraphRunner()
        [ev async for ev in runner.run(state, gid)]
        [ev async for ev in runner.resume(gid)]

        root = project_root_of(state)
        index = read_index(root)
        assert index["stages"].get("analysis") == "done"
        assert index["stages"].get("design") == "done"
        assert "code" not in index["stages"]

        # ── 2. 代码阶段"崩溃": 执行器写完首文件后 abandon runner ──
        # (进程死亡语义: 无 gate 裁决、无 code 阶段完成标记、runner 丢弃)
        crashed_events = []
        async for ev in runner.resume(gid):
            crashed_events.append(ev)
            if ev.get("event_type") == "task_complete":
                break  # 模拟中断: 不再消费 (runner 丢弃, 不 aclose 不继续)
        assert any(e["event_type"] == "task_complete" for e in crashed_events)
        del runner  # 进程死亡: runner 对象废弃

        index2 = read_index(root)
        assert index2["stages"].get("analysis") == "done"
        assert index2["stages"].get("design") == "done"
        assert "code" not in index2["stages"]       # 中断: 代码未完成
        assert state.get("code_result") is None     # 无 gate 裁决产物

        # ── 3. 重启: 新 runner 同 generation → load_app_state 恢复 ──
        patch = load_app_state(root, gid)
        assert patch is not None
        assert "analysis_result" in patch           # 已完成阶段恢复
        assert "architecture_spec" in patch
        assert patch["architecture_spec"] == SPEC_SM
        assert "generated_files" not in patch       # 未完成阶段不恢复

        state2 = base_state(generation_id=gid, requirement=state["requirement"])
        state2.update(patch)
        runner2 = GraphRunner()
        events = []
        async for ev in runner2.run(state2, gid):
            events.append(ev)
            if ev.get("event_type") == "manager_verdict" and ev.get("data", {}).get("node") == "code":
                break

        # 已完成阶段跳过: 无 PRD/设计重生成
        assert not events_of(events, "prd_generate_start")
        assert not events_of(events, "design_gen_done")
        # 代码阶段续跑至通过
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "code"
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert state2["analysis_result"] == PRD_OK
        assert state2["architecture_spec"] == SPEC_SM
    finally:
        nodes._provider = old

    # ── 4. 最终产物一致 ──
    index3 = read_index(root)
    assert index3["stages"].get("analysis") == "done"
    assert index3["stages"].get("design") == "done"
    assert index3["stages"].get("code") == "done"
    # 裁决历史完整 (恢复的 analysis/design + 续跑的 code)
    assert [v.get("node") for v in index3.get("verdicts", [])] == ["analysis", "design", "code"]
    import os

    assert os.path.isfile(os.path.join(root, ".ai-memory", "spec", "requirements.md"))
    assert os.path.isfile(os.path.join(root, ".ai-memory", "spec", "architecture.json"))
    assert os.path.isfile(os.path.join(root, ".ai-memory", "state", "state.json"))
    assert os.path.isfile(os.path.join(root, ".ai-memory", "state", "contracts.json"))
    # 磁盘代码产物 = code_result (7.7 恢复一致性)
    files = json.loads(state2["code_result"])
    assert set(files) == {"src/App.vue"}
    with open(os.path.join(root, "src", "App.vue"), encoding="utf-8") as f:
        assert f.read() == files["src/App.vue"]
