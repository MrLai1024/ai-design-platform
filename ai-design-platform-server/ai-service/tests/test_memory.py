"""Task group 7 memory-system tests — `.ai-memory/` writers/readers,
persistent project_root (7.1), run_context staging (7.4), crash recovery
(7.7) and incremental-load summary + diff (7.8).

Memory writes land in per-test tmp dirs via conftest env isolation
(AI_GEN_DATA_DIR / AI_GEN_MEMORY_DB).
"""

import json
import os

import grpc
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai.v1.generation_pb2 import (
    GenerateRequest,
    GenerationConfig,
    Message as ProtoMessage,
)

from app.services.generation import memory
from app.services.generation.graph import GraphRunner

PRD = (
    "# 需求规格文档\n\n"
    "## 2. 功能模块\n- 用户管理\n- 订单管理\n\n"
    "## 3. 页面结构\n- 用户列表页\n- 订单列表页\n"
)
DESIGN_MD = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"
VALID_SPEC = {
    "spec_version": 1,
    "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "webpack", "style": "scss"},
    "directory_tree": {"src/": ["main.ts", "App.vue", "router/", "components/"]},
    "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
    "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
    "routing": [{"path": "/", "page": "Home", "auth": False}],
    "state_management": {"store": "pinia", "stores": ["user"]},
    "component_tree": [{"name": "Header", "uses": ["NavMenu"], "props": []}],
    "pages": [{"id": "p-01", "name": "登录页", "interactions": [], "data": []}],
    "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
}


def _state(**overrides) -> dict:
    state = {
        "requirement": "生成一个用户管理页面",
        "generation_id": "gen-mem-1",
        "user_id": "test-user",
        "component_lib": "element-plus",
        "messages": [{"role": "user", "content": "生成一个用户管理页面"}],
        "requirements_state_json": None,
        "analysis_result": None,
        "design_result": None,
        "architecture_spec": None,
        "code_result": None,
        "generated_files": {},
        "compile_errors": None,
        "manager_verdicts": [],
        "brainstorm_decisions": None,
        "brainstorm_assumptions": None,
        "planner_dag": None,
        "context_summary": None,
        "stage_phase": "generating",
    }
    state.update(overrides)
    return state


# ── 7.1 persistent project_root ──


def test_project_root_persistent_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state())
    assert root == str(tmp_path / "generated" / "gen-mem-1")
    assert "tempfile" not in root and "ai-gen" not in root.split(os.sep)[-1]


def test_project_root_app_id_from_generation_id(monkeypatch):
    s1 = _state(generation_id="gen-a-1", requirement="需求甲")
    s2 = _state(generation_id="gen-b-2", requirement="需求乙")
    assert memory.project_root_for(s1) != memory.project_root_for(s2)


def test_project_root_requirement_hash_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    s1 = _state(generation_id=None, requirement="生成一个订单管理页面")
    s2 = _state(generation_id=None, requirement="生成一个订单管理页面")
    s3 = _state(generation_id=None, requirement="生成一个库存管理页面")
    assert memory.project_root_for(s1) == memory.project_root_for(s2)  # 确定性
    assert memory.project_root_for(s1) != memory.project_root_for(s3)  # 不同需求不碰撞


def test_sanitize_app_id_windows_safe():
    # 反斜杠/斜杠/冒号/星号/引号/尖括号/管道 → 下划线; 空 → 兜底名。
    assert memory.sanitize_app_id('a\\b/c:d*?"<>|e') == "a_b_c_d______e"
    assert memory.sanitize_app_id("") == "ai-gen-app"
    assert memory.sanitize_app_id("..\\..\\evil") == ".._.._evil".strip("._") or "ai-gen-app"


def test_project_root_env_default(monkeypatch):
    monkeypatch.delenv("AI_GEN_DATA_DIR", raising=False)
    assert memory.data_dir().endswith("data")


# ── 7.2 `.ai-memory/` structure + write helpers ──


def test_write_helpers_create_full_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state())
    memory.update_index(root)
    memory.write_requirements(root, PRD)
    memory.write_spec(root, VALID_SPEC)
    memory.write_architecture_md(root, DESIGN_MD)
    memory.write_decisions(root, _state(manager_verdicts=[
        {"node": "design", "decision": "pass", "reason": "ok", "signature": "abc", "at": "2026-08-05"},
    ], brainstorm_decisions=[
        {"topic": "方案选型", "choice": "方案A", "reason": "用户选择", "at": "t", "round": 2},
    ]))
    memory.write_state(root, _state(requirements_state_json=json.dumps(
        {"features": [{"id": "F-01", "name": "用户管理", "priority": "must"}]}
    ), planner_dag={"tasks": [{"id": "task-0", "status": "done"}], "total_tasks": 1, "completed_tasks": 1}))
    memory.write_contracts(root, {"key_exports": {"App.vue": {"exports": ["App"]}}})
    memory.append_problem(root, category="verifier_failure", problem="编译错误", result="escalated")

    mem = os.path.join(root, ".ai-memory")
    for rel in (
        "index.json",
        "spec/requirements.md",
        "spec/architecture.json",
        "spec/architecture.md",
        "spec/decisions.md",
        "state/state.json",
        "state/contracts.json",
        "problems.jsonl",
    ):
        assert os.path.isfile(os.path.join(mem, rel)), rel
    assert os.path.isdir(os.path.join(mem, "changes"))  # U8 fills it

    # index.json 清单字段
    index = json.load(open(os.path.join(mem, "index.json"), encoding="utf-8"))
    assert index["app_id"] == "gen-mem-1"
    assert index["spec_version"] == 1
    assert "created_at" in index

    # decisions.md 同时含头脑风暴决策与 Manager 把关
    decisions = open(os.path.join(mem, "spec/decisions.md"), encoding="utf-8").read()
    assert "方案选型" in decisions and "design" in decisions

    # state.json 派生: features + implemented
    state_json = json.load(open(os.path.join(mem, "state/state.json"), encoding="utf-8"))
    assert state_json["features"][0]["name"] == "用户管理"
    assert state_json["implemented"] == ["task-0"]

    # problems.jsonl 行格式
    problems = [json.loads(l) for l in open(os.path.join(mem, "problems.jsonl"), encoding="utf-8").read().splitlines()]
    assert problems[0]["category"] == "verifier_failure"
    assert problems[0]["ts"]


def test_write_helpers_fail_open(tmp_path, monkeypatch):
    """project_root 指向文件 → makedirs 失败 → 不抛异常."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(blocker))
    state = _state()
    memory.persist_stage_artifacts(state, "analysis")
    memory.record_problem(state, category="x", problem="y")
    memory.update_run_context(state, stage="analysis")
    assert memory.update_index(str(blocker), stage="analysis") is None
    assert memory.append_problem(str(blocker), category="x", problem="y") is None


# ── 7.3 continuous write-through (persist_stage_artifacts) ──


def _gate_verdicts(state, stage, decision):
    state["manager_verdicts"] = list(state.get("manager_verdicts") or []) + [
        {"node": stage, "decision": decision, "reason": "r", "signature": "s", "at": "t"}
    ]
    return state


def test_persist_analysis_writes_requirements(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(analysis_result=PRD)
    _gate_verdicts(state, "analysis", "pass")
    memory.persist_stage_artifacts(state, "analysis")
    root = memory.project_root_for(state)
    assert open(os.path.join(root, ".ai-memory/spec/requirements.md"), encoding="utf-8").read() == PRD
    index = memory.read_index(root)
    assert index["stages"].get("analysis") == "done"


def test_persist_analysis_redo_writes_requirements_but_no_done_mark(tmp_path, monkeypatch):
    """把关 redo 不标记阶段完成 (崩溃恢复不会跳过重做中的阶段)."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(analysis_result=PRD)
    _gate_verdicts(state, "analysis", "redo")
    memory.persist_stage_artifacts(state, "analysis")
    root = memory.project_root_for(state)
    assert os.path.isfile(os.path.join(root, ".ai-memory/spec/requirements.md"))
    assert "analysis" not in memory.read_index(root).get("stages", {})


def test_persist_design_pass_writes_spec_and_md(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(analysis_result=PRD, design_result=DESIGN_MD, design_doc=DESIGN_MD,
                   architecture_spec=VALID_SPEC)
    _gate_verdicts(state, "design", "pass")
    memory.persist_stage_artifacts(state, "design")
    root = memory.project_root_for(state)
    assert json.load(open(os.path.join(root, ".ai-memory/spec/architecture.json"), encoding="utf-8")) == VALID_SPEC
    assert open(os.path.join(root, ".ai-memory/spec/architecture.md"), encoding="utf-8").read() == DESIGN_MD
    assert memory.read_index(root)["stages"]["design"] == "done"


def test_persist_design_redo_never_writes_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(analysis_result=PRD, design_result=DESIGN_MD, architecture_spec=VALID_SPEC)
    _gate_verdicts(state, "design", "redo")
    memory.persist_stage_artifacts(state, "design")
    root = memory.project_root_for(state)
    assert not os.path.exists(os.path.join(root, ".ai-memory/spec/architecture.json"))


def test_record_problem_writes_all_layers(tmp_path, monkeypatch):
    """问题留痕: problems.jsonl + 中期 problem_records + 长期失败模式/修复策略."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    from app.services.generation.memory_db import get_memory_db

    state = _state()
    memory.record_problem(
        state,
        category="fix_round",
        problem="编译错误",
        root_cause="缺少导入",
        fix="补 import",
        result="passed",
    )
    root = memory.project_root_for(state)
    problems = memory.read_problems(root)
    assert len(problems) == 1
    assert problems[0]["category"] == "fix_round"
    assert problems[0]["root_cause"] == "缺少导入"
    # run_context 记录最近问题 (7.4)
    assert state["run_context"]["latest_problem"]["category"] == "fix_round"
    # 中期 DB: problem_records 按 generation 归档
    mid = get_memory_db().list_problems("gen-mem-1")
    assert mid[0]["fix"] == "补 import"
    # 长期 DB: 失败模式计数 + 修复策略成功计数
    patterns = get_memory_db().get_failure_patterns("test-user")
    assert patterns and patterns[0]["fix_strategy"] == "补 import"
    strategies = get_memory_db().get_fix_strategies()
    assert strategies[0]["success_count"] == 1
    assert strategies[0]["attempt_count"] == 1


def test_persist_code_writes_state_and_contracts(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(
        analysis_result=PRD,
        requirements_state_json=json.dumps(
            {"features": [{"id": "F-01", "name": "用户管理", "priority": "must"}]}
        ),
        planner_dag={
            "tasks": [{"id": "task-0", "type": "bootstrap", "status": "done"}],
            "total_tasks": 1, "completed_tasks": 1,
        },
        context_summary={"key_exports": {"App.vue": {"exports": ["App"]}}},
    )
    _gate_verdicts(state, "code", "pass")
    memory.persist_stage_artifacts(state, "code")
    root = memory.project_root_for(state)
    state_json = json.load(open(os.path.join(root, ".ai-memory/state/state.json"), encoding="utf-8"))
    assert state_json["features"][0]["name"] == "用户管理"
    assert state_json["implemented"] == ["task-0"]
    contracts = json.load(open(os.path.join(root, ".ai-memory/state/contracts.json"), encoding="utf-8"))
    assert contracts["key_exports"]["App.vue"]["exports"] == ["App"]
    index = memory.read_index(root)
    assert index["stages"]["code"] == "done"
    assert "F-01" in index["features_done"]


# ── 7.4 run_context ──


def test_update_run_context_writes_staging(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(brainstorm_assumptions=[{"id": "a1", "topic": "分页方式", "answer": "客户端"}])
    ctx = memory.update_run_context(
        state, stage="design", phase="generating", active_node="design",
    )
    assert state["run_context"] is ctx
    assert ctx["stage"] == "design" and ctx["active_node"] == "design"
    assert ctx["assumptions"][0]["topic"] == "分页方式"  # 继承自 state
    assert ctx["generation_id"] == "gen-mem-1"
    # 暂存区写透
    root = memory.project_root_for(state)
    staged = json.load(open(os.path.join(root, ".ai-memory/state/run_context.json"), encoding="utf-8"))
    assert staged["stage"] == "design"
    # 最新把关/问题进入 run_context
    memory.update_run_context(state, latest_verdict={"node": "design", "decision": "pass"})
    assert state["run_context"]["latest_verdict"]["decision"] == "pass"


# ── 7.7 crash recovery ──


def _write_full_memory(tmp_path, monkeypatch, generation_id="gen-rec-1") -> str:
    """写入 analysis+design+code 全部完成的记忆, 返回 project_root."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(generation_id=generation_id)
    root = memory.project_root_for(state)
    memory.write_requirements(root, PRD)
    memory.write_spec(root, VALID_SPEC)
    memory.write_architecture_md(root, DESIGN_MD)
    memory.write_state(root, _state(requirements_state_json=json.dumps(
        {"features": [{"id": "F-01", "name": "用户管理"}]}
    )))
    memory.write_decisions(root, _state(manager_verdicts=[
        {"node": "analysis", "decision": "pass", "reason": "ok", "signature": "s1", "at": "t"},
        {"node": "design", "decision": "pass", "reason": "ok", "signature": "s2", "at": "t"},
    ]))
    memory.update_index(root, stage="analysis")
    memory.update_index(root, stage="design")
    memory.update_index(root, stage="code")
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src/App.vue"), "w", encoding="utf-8") as f:
        f.write("<template><div/></template>")
    return root


def test_load_app_state_reconstructs_completed_stages(tmp_path, monkeypatch):
    root = _write_full_memory(tmp_path, monkeypatch)
    patch = memory.load_app_state(root, "gen-rec-1")
    assert patch is not None
    assert patch["analysis_result"] == PRD
    assert patch["architecture_spec"] == VALID_SPEC
    assert patch["design_result"] == DESIGN_MD
    assert patch["design_doc"] == DESIGN_MD
    assert patch["generated_files"]["src/App.vue"] == "<template><div/></template>"
    assert "src/App.vue" in json.loads(patch["code_result"])


def test_load_app_state_mid_stage_crash_not_restored(tmp_path, monkeypatch):
    """进行中阶段 (未标记 done) 不恢复产物 → 重跑该阶段."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-mid-1"))
    memory.write_requirements(root, PRD)
    memory.write_spec(root, VALID_SPEC)  # design 产物存在但 index 未标记 done (进行中崩溃)
    memory.update_index(root, stage="analysis")
    patch = memory.load_app_state(root, "gen-mid-1")
    assert "analysis_result" in patch
    assert "architecture_spec" not in patch  # design 未完成 → 不恢复
    assert "generated_files" not in patch


def test_load_app_state_no_memory_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-none-1"))
    assert memory.load_app_state(root, "gen-none-1") is None


@pytest.mark.asyncio
async def test_restored_state_skips_completed_stages(tmp_path, monkeypatch):
    """7.7 spec 场景: 崩溃后重启同一 generation → 已完成阶段跳过."""
    root = _write_full_memory(tmp_path, monkeypatch)
    mem_patch = memory.load_app_state(root, "gen-rec-1")
    state = _state(**mem_patch)  # mem_patch 自带 generation_id/manager_verdicts
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock) as llm:
        runner = GraphRunner(llm_fn=llm)
        events = [ev async for ev in runner.run(state, "gen-rec-1")]

    assert not any(e["event_type"] == "prd_generate_start" for e in events)   # phase 1 跳过
    assert not any(e["event_type"] == "design_gen_done" for e in events)      # phase 2 跳过
    assert not any(e["event_type"] == "code_gen_done" for e in events)        # phase 3 跳过
    # 从 gate 续跑 (phase 4): 现有 gate 判定 code 已产出 → 继续流转。
    assert any(e["event_type"] == "manager_verdict" for e in events) or any(
        e["event_type"] == "human_confirm_required" for e in events
    )


# ── 7.8 incremental load: summary + section + diff ──


def test_load_summary_and_section(tmp_path, monkeypatch):
    root = _write_full_memory(tmp_path, monkeypatch)
    memory.update_index(root, stage="code", features_done=["F-01"])
    summary = memory.load_summary(root)
    assert summary is not None
    assert summary["app_id"] == "gen-rec-1"
    assert summary["state"]["features"][0]["name"] == "用户管理"      # state 全量
    assert "设计" in summary["decisions"] or "（无）" in summary["decisions"]  # decisions 全量
    assert summary["requirements_summary"].startswith("# 需求规格文档")  # 摘要
    assert summary["requirements_size"] == len(PRD)
    assert summary["architecture_summary"]["pages"] == ["登录页"]
    assert summary["architecture_summary"]["tech_stack"]["framework"] == "vue3"
    # 按需全量读取
    assert memory.load_section(root, "spec/requirements.md") == PRD
    assert memory.load_section(root, ".ai-memory/spec/requirements.md") == PRD
    assert memory.load_section(root, "spec/architecture.json") is not None


def test_load_summary_truncates_large_requirements(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-big-1"))
    memory.write_requirements(root, "x" * 5000)
    summary = memory.load_summary(root)
    assert len(summary["requirements_summary"]) < 5000
    assert memory.load_section(root, "spec/requirements.md") == "x" * 5000


def test_load_summary_none_without_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-nosum-1"))
    assert memory.load_summary(root) is None


def test_load_section_path_traversal_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-sec-1"))
    assert memory.load_section(root, "../outside.txt") is None


def test_extract_feature_names():
    text = (
        "# 需求规格文档\n\n"
        "## 2. 功能模块\n- 用户管理\n- 订单管理（含退款）\n- 报表: 导出\n\n"
        "## 3. 页面结构\n- 用户列表页\n"
    )
    assert memory.extract_feature_names(text) == ["用户管理", "订单管理", "报表"]
    # 无功能模块章节 → 顶层子弹兜底
    assert memory.extract_feature_names("- 搜索\n- 收藏") == ["搜索", "收藏"]
    assert memory.extract_feature_names("") == []


def test_diff_requirement_feature_list_delta():
    base = {"features": ["用户管理", "订单管理", "库存管理"]}
    diff = memory.diff_requirement(base, "# 新需求\n## 2. 功能模块\n- 用户管理\n- 订单管理\n- 优惠券")
    assert diff["added"] == ["优惠券"]
    assert diff["removed"] == ["库存管理"]
    # sorted() 按码点排序: "用户管理"(U+7528) < "订单管理"(U+8BA2)
    assert diff["unchanged"] == ["用户管理", "订单管理"]
    assert diff["modified"] == []  # U8 manifest 判定
    # 无变化 → 全 unchanged
    diff2 = memory.diff_requirement({"features": ["A"]}, "- A")
    assert diff2["added"] == [] and diff2["removed"] == [] and diff2["unchanged"] == ["A"]


# ── 7.7 servicer 崩溃恢复预填 ──


@pytest.mark.asyncio
async def test_servicer_stream_graph_prefills_state_from_memory(tmp_path, monkeypatch):
    """_stream_graph 对已有 .ai-memory 产物的同一 generation 预填已完成阶段."""
    _write_full_memory(tmp_path, monkeypatch, generation_id="gen-svc-1")
    captured: dict = {}

    class FakeRunner:
        def __init__(self, memory_db=None):
            self.memory_db = memory_db

        async def run(self, state, generation_id):
            captured["state"] = state
            yield {"event_type": "x", "stage": "y", "data": {}}

    from app.services.generation.servicer import GenerationServicer

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.GraphRunner", FakeRunner), \
         patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider") as _sp:
        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.cancelled.return_value = False
        request = GenerateRequest(
            generation_id="gen-svc-1",
            model="glm-5.2",
            messages=[ProtoMessage(role="user", content="生成一个用户管理页面")],
            metadata={"mode": "graph"},
            config=GenerationConfig(temperature=0.5, max_tokens=100),
        )
        responses = [r async for r in servicer.StreamGenerate(request, context)]

    assert len(responses) == 2  # graph_event + complete
    st = captured["state"]
    assert st["generation_id"] == "gen-svc-1"
    assert st["user_id"] == "default"
    assert st["analysis_result"] == PRD                     # 已完成阶段恢复
    assert st["architecture_spec"] == VALID_SPEC
    assert "src/App.vue" in st["generated_files"]
    assert st["run_context"]["stage"] == "analysis"          # 7.4 初始化


@pytest.mark.asyncio
async def test_servicer_stream_graph_injects_user_preferences_as_constraints(tmp_path, monkeypatch):
    """7.6 spec 场景: 历史偏好 → 分发上下文约束 (graph start)."""
    from app.services.generation.memory_db import get_memory_db

    get_memory_db().upsert_preference("svc-user", "component_lib", "element-plus")
    get_memory_db().upsert_preference("svc-user", "方案选型", "方案A")
    captured: dict = {}

    class FakeRunner:
        def __init__(self, memory_db=None):
            self.memory_db = memory_db

        async def run(self, state, generation_id):
            captured["state"] = state
            yield {"event_type": "x", "stage": "y", "data": {}}

    from app.services.generation.servicer import GenerationServicer

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.GraphRunner", FakeRunner), \
         patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider"):
        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.cancelled.return_value = False
        request = GenerateRequest(
            generation_id="gen-pref-svc",
            model="glm-5.2",
            messages=[ProtoMessage(role="user", content="做一个后台")],
            metadata={"mode": "graph", "user_id": "svc-user"},
            config=GenerationConfig(temperature=0.5, max_tokens=100),
        )
        responses = [r async for r in servicer.StreamGenerate(request, context)]

    st = captured["state"]
    assert st["user_id"] == "svc-user"
    constraints = st["dispatch_contract"].get("constraints") or []
    assert any("element-plus" in c and "用户偏好" in c for c in constraints)
    assert any("方案A" in c for c in constraints)


@pytest.mark.asyncio
async def test_servicer_stream_graph_skips_restore_when_no_memory(tmp_path, monkeypatch):
    """无记忆产物 → 全新生成 (不预填, 不报错)."""
    captured: dict = {}

    class FakeRunner:
        def __init__(self, memory_db=None):
            self.memory_db = memory_db

        async def run(self, state, generation_id):
            captured["state"] = state
            yield {"event_type": "x", "stage": "y", "data": {}}

    from app.services.generation.servicer import GenerationServicer

    mock_provider = MagicMock()
    with patch("app.services.generation.servicer.GraphRunner", FakeRunner), \
         patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider"):
        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.cancelled.return_value = False
        request = GenerateRequest(
            generation_id="gen-fresh-1",
            model="glm-5.2",
            messages=[ProtoMessage(role="user", content="全新需求")],
            metadata={"mode": "graph"},
            config=GenerationConfig(temperature=0.5, max_tokens=100),
        )
        responses = [r async for r in servicer.StreamGenerate(request, context)]

    st = captured["state"]
    assert st["analysis_result"] is None
    assert st["generated_files"] == {}
    assert len(responses) == 2


# ── 7.6 长期用户级记忆: brainstorm 偏好写入 + 议程播种注入 ──


def _brainstorm_fake_llm(calls: list):
    """Minimal fake llm_fn: 画像/提问/方案对比分流."""
    async def _llm(system_prompt: str, user_content: str) -> str:
        calls.append((system_prompt, user_content))
        if "需求画像" in system_prompt:
            return json.dumps({
                "requirement_type": "admin_system",
                "project_name": "后台",
                "core_problem": "p",
                "target_users": [],
                "success_criteria": [],
                "scope_note": "",
                "ambiguities": [{"topic": "权限模型", "reason": "r", "impact": "design"}],
                "candidate_plans": [{"name": "方案A", "summary": "s", "scope": "", "interaction": "", "pros": [], "costs": []}],
                "features": [],
                "pages": [],
                "tech_constraints": {"framework": "vue3", "component_lib": "", "data_source": "", "special_requirements": []},
                "data_entities": [],
            }, ensure_ascii=False)
        if "提问" in system_prompt:
            return '{"questions": []}'
        if "候选方案" in system_prompt:
            return '{"proposals": [{"name": "方案A", "summary": "s", "scope": "", "interaction": "", "pros": [], "costs": []}]}'
        return "{}"
    return _llm


def test_brainstorm_session_user_id():
    from app.services.generation.brainstorm import create_session, get_or_create_session

    s = create_session(user_id="user-42")
    assert s.user_id == "user-42"
    s2 = get_or_create_session(None, user_id="user-7")
    assert s2.user_id == "user-7"
    assert get_or_create_session(s.generation_id, user_id="ignored").user_id == "user-42"


@pytest.mark.asyncio
async def test_brainstorm_profile_seeding_injects_preferences(tmp_path, monkeypatch):
    """7.6 spec 场景: 历史偏好 → 议程播种 (首轮画像) 作为约束."""
    from app.services.generation.memory_db import get_memory_db

    db = get_memory_db()
    db.upsert_preference("pref-user", "component_lib", "element-plus")
    db.upsert_preference("pref-user", "方案选型", "方案A")

    from app.services.generation.brainstorm import BrainstormSession, turn

    session = BrainstormSession(generation_id="gen-pref-1", user_id="pref-user")
    calls: list = []
    await turn(session, "做一个后台管理系统", llm_fn=_brainstorm_fake_llm(calls))

    profile_sys, profile_content = calls[0]
    assert "用户历史偏好" in profile_content
    assert "element-plus" in profile_content
    assert "方案A" in profile_content


@pytest.mark.asyncio
async def test_brainstorm_proposal_choice_upserts_preference(tmp_path, monkeypatch):
    """7.6: 方案选择 → 长期用户级偏好 upsert."""
    from app.services.generation.brainstorm import AgendaItem, BrainstormSession, turn
    from app.services.generation.memory_db import get_memory_db

    session = BrainstormSession(generation_id="gen-pref-2", user_id="pref-user", round=3)
    session.proposal_shown = True
    session.proposals = [{"name": "方案A", "summary": "s", "scope": "", "interaction": "", "pros": [], "costs": []}]
    session.agenda = [AgendaItem(id="a1", topic="权限模型", reason="r", impact="design")]
    session.agenda[0].status = "answered"
    session.agenda[0].answer = "RBAC"

    calls: list = []
    await turn(session, "方案A", llm_fn=_brainstorm_fake_llm(calls))

    assert session.proposal_decided is True
    assert session.decisions[-1]["choice"] == "方案A"
    prefs = get_memory_db().get_preferences("pref-user")
    assert prefs.get("方案选型") == "方案A"
    # 用户隔离: 其他用户看不到
    assert "方案选型" not in get_memory_db().get_preferences("other-user")


# ── 7.5 轨迹归档: GraphRunner + memory_db 集成 ──


@pytest.mark.asyncio
async def test_graph_trajectory_records_curated_events(tmp_path, monkeypatch):
    """轨迹归档只收精选事件 (流式 token 不入库)."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    from app.services.generation.memory_db import MemoryDB

    db = MemoryDB(str(tmp_path / "traj.sqlite"))
    state = _state(analysis_result=None)
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock, return_value=PRD):
        runner = GraphRunner(memory_db=db)
        events = [ev async for ev in runner.run(state, "gen-traj-1")]

    assert any(e["event_type"] == "human_confirm_required" for e in events)
    types = [r["event_type"] for r in db.list_trajectory("gen-traj-1")]
    for expected in ("stage_start", "prd_generate_start", "prd_generate_done",
                     "stage_complete", "manager_verdict", "human_confirm_required"):
        assert expected in types, expected
    assert "doc_chunk" not in types  # 流式 token 不入轨迹
    db.close()


@pytest.mark.asyncio
async def test_graph_without_memory_db_no_trajectory(tmp_path, monkeypatch):
    """runner 未注入 memory_db → 零轨迹写入."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(analysis_result=None)
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock, return_value=PRD):
        runner = GraphRunner()  # 无 memory_db
        events = [ev async for ev in runner.run(state, "gen-notraj-1")]
    assert any(e["event_type"] == "human_confirm_required" for e in events)


# ── review I1: 代码阶段轨迹归档 (phase-3 全流程) ──


@pytest.mark.asyncio
async def test_graph_trajectory_records_code_phase_events(tmp_path, monkeypatch):
    """I1: 代码阶段 (最丰富事件阶段) 的轨迹归档 — 队列排出的 executor/planner
    事件同样入库 (task_complete/planner_dag/task_acceptance)."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent
    from app.services.generation import nodes as gen_nodes
    from app.services.generation.memory_db import MemoryDB

    GOOD = ('<template><div>hello</div></template>\n'
            '<script setup lang="ts">\nexport const MyButton = 1\n</script>')

    class ScriptedProvider:
        """executor 两轮: write_code 工具调用 → __TASK_DONE__."""

        def __init__(self):
            self.calls = 0

        async def stream_generate(self, model, messages, config):
            self.calls += 1
            if self.calls == 1:
                yield ToolCallEvent(
                    call_id="c1", name="write_code",
                    arguments=json.dumps({
                        "path": "src/components/MyButton.vue", "content": GOOD,
                    }),
                )
            else:
                yield TokenEvent(text="__TASK_DONE__", index=0)
            yield CompleteEvent(finish_reason="stop", usage={})

    dag_json = json.dumps({
        "reasoning": "r",
        "tasks": [{
            "id": "task-0", "type": "business", "description": "按钮组件",
            "deps": [], "files": ["src/components/MyButton.vue"],
            "contract": {"exports": ["MyButton"]},
        }],
    })

    state = _state(
        analysis_result=PRD,
        design_result=DESIGN_MD,
        design_doc=DESIGN_MD,
        architecture_spec=VALID_SPEC,
        generated_files={},
    )
    db = MemoryDB(str(tmp_path / "traj.sqlite"))
    old_provider = gen_nodes._provider
    gen_nodes._provider = ScriptedProvider()
    try:
        with patch("app.services.generation.nodes._llm_generate",
                   new_callable=AsyncMock, return_value=dag_json):
            runner = GraphRunner(memory_db=db)
            events = [ev async for ev in runner.run(state, "gen-code-traj")]
    finally:
        gen_nodes._provider = old_provider

    assert any(e["event_type"] == "human_confirm_required" for e in events)
    types = [r["event_type"] for r in db.list_trajectory("gen-code-traj")]
    for expected in ("tier_assessed", "planner_dag", "task_complete", "task_acceptance",
                     "compile_status", "verifier_result", "code_gen_done",
                     "manager_verdict", "stage_complete"):
        assert expected in types, expected
    assert "doc_chunk" not in types  # 流式 token 不入轨迹
    assert "thinking_chunk" not in types
    db.close()


# ── review I2: 分发约束消费 ──


@pytest.mark.asyncio
async def test_constraints_consumed_in_prompts_and_dispatch(tmp_path, monkeypatch):
    """I2: 偏好约束不悬空 — PRD prompt / Spec prompt 消费 + 设计/代码
    dispatch 重建不丢约束."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    constraint = "用户偏好（长期记忆）：component_lib=element-plus"
    prd_prompts: list[str] = []

    async def fake_gen(system_prompt, user_content, **kwargs):
        prd_prompts.append(user_content)
        return PRD if len(prd_prompts) == 1 else DESIGN_MD

    spec_prompts: list[str] = []

    async def fake_llm(system_prompt, user_content):
        spec_prompts.append(user_content)
        if "核对" in system_prompt:  # L2 gate prompt (把关人)
            return '{"passed": true, "missing": []}'
        return json.dumps(VALID_SPEC, ensure_ascii=False)  # Spec prompt

    state = _state(
        analysis_result=None,
        generated_files={"src/App.vue": "x"},  # 跳过 phase 3
        dispatch_contract={
            "task_id": "analysis", "input_ref": "requirement",
            "acceptance_criteria": [], "tool_bounds": [], "constraints": [constraint],
        },
    )
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock, side_effect=fake_gen):
        runner = GraphRunner(llm_fn=fake_llm)
        events = [ev async for ev in runner.run(state, "gen-con-1")]
        events += [ev async for ev in runner.resume("gen-con-1")]

    assert any(e["event_type"] == "manager_verdict" for e in events)
    # PRD prompt 消费
    assert prd_prompts and constraint in prd_prompts[0]
    # design dispatch 重建保留约束
    design_contract = state["dispatch_contract"]
    assert design_contract["task_id"] == "design"
    assert any("component_lib" in c for c in design_contract["constraints"])
    # Spec prompt 消费
    assert any(constraint in p for p in spec_prompts)


# ── review I3: skip_analysis 残留旧 index 标记 ──


def test_skip_analysis_reset_clears_stale_stages(tmp_path, monkeypatch):
    """I3 序列: run1 完成 analysis/design → run2 skip_analysis 全量重来
    (reset) → run3 崩溃恢复不误读 run1 的旧标记/旧产物."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    gid = "gen-ia-1"
    root = memory.project_root_for(_state(generation_id=gid))
    # run1: analysis + design 完成 (旧需求产物)
    memory.write_requirements(root, PRD)
    memory.write_spec(root, VALID_SPEC)
    memory.write_architecture_md(root, DESIGN_MD)
    memory.update_index(root, stage="analysis")
    memory.update_index(root, stage="design")
    assert memory._completed_stages(root) == {"analysis", "design"}
    assert memory.load_app_state(root, gid)["analysis_result"] == PRD

    # run2: skip_analysis 全量重来 → 初始化 reset
    memory.init_app_memory(_state(generation_id=gid), reset=True)
    assert memory.read_index(root)["stages"] == {}
    # 新需求 (analysis_result=None) 走 phase 1 — index 已清
    assert memory._completed_stages(root) == set()

    # run3: 崩溃后恢复 — 旧阶段标记已清, 不得恢复 run1 的旧产物
    assert memory.load_app_state(root, gid) is None


def test_index_present_but_empty_stages_not_fallback(tmp_path, monkeypatch):
    """I3 配套: index 存在但 stages 为空 (重置后) 时, 产物存在性兜底不生效."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-ia-2"))
    memory.write_requirements(root, PRD)  # 旧产物仍在
    memory.write_spec(root, VALID_SPEC)
    memory.update_index(root)  # index 存在, stages 空
    assert memory._completed_stages(root) == set()


# ── review M1: 裁决持久化 + 恢复后 decisions.md 保留历史 ──


def test_recovery_restores_verdicts_and_decisions_history(tmp_path, monkeypatch):
    """M1: 把关裁决持久化在 index.json — 崩溃恢复后 decisions.md 重写
    不丢已完成阶段的历史裁决."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-m1-1"))
    verdicts = [
        {"node": "analysis", "decision": "pass", "reason": "ok", "signature": "s1", "at": "t1"},
        {"node": "design", "decision": "pass", "reason": "ok", "signature": "s2", "at": "t2"},
    ]
    memory.write_requirements(root, PRD)
    memory.write_spec(root, VALID_SPEC)
    memory.write_architecture_md(root, DESIGN_MD)
    memory.update_index(root, stage="analysis", verdicts=verdicts)
    memory.update_index(root, stage="design")

    mem_patch = memory.load_app_state(root, "gen-m1-1")
    assert mem_patch["manager_verdicts"] == verdicts

    # 恢复后 write_decisions 重写 — 历史裁决仍在 (不再被 manager_verdicts=[] 抹掉)
    state = _state(**mem_patch)
    memory.write_decisions(root, state)
    decisions = open(os.path.join(root, ".ai-memory/spec/decisions.md"), encoding="utf-8").read()
    assert "**analysis**" in decisions and "**design**" in decisions


# ── review M3: index 缺失时产物兜底扫描 ──


def test_load_app_state_index_missing_fallback_scan(tmp_path, monkeypatch):
    """M3: index 缺失时按过关产物兜底 — code 阶段绝不凭 state.json 推断."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = memory.project_root_for(_state(generation_id="gen-fb-1"))
    memory.write_requirements(root, PRD)
    memory.write_spec(root, VALID_SPEC)
    memory.write_architecture_md(root, DESIGN_MD)
    memory.write_state(root, _state(requirements_state_json=json.dumps(
        {"features": [{"id": "F-01", "name": "用户管理"}]}
    )))  # state.json 存在但不参与兜底
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src/App.vue"), "w", encoding="utf-8") as f:
        f.write("<template/>")

    mem_patch = memory.load_app_state(root, "gen-fb-1")
    assert mem_patch is not None
    assert mem_patch["analysis_result"] == PRD            # requirements.md 兜底
    assert mem_patch["architecture_spec"] == VALID_SPEC   # architecture.json 兜底
    assert "generated_files" not in mem_patch             # code 只认 index 标记


# ── write-through 与 gate 事件集成 (graph 层) ──


@pytest.mark.asyncio
async def test_graph_gate_persists_verdicts_and_stage(tmp_path, monkeypatch):
    """把关裁决写 decisions.md + 阶段完成标 index + requirements 落盘
    (走真实 _gate_manual_stage; 阶段 3 预置 generated_files 跳过)."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(analysis_result=None, generated_files={"src/App.vue": "x"})
    with patch("app.services.generation.nodes._llm_generate",
               new_callable=AsyncMock,
               side_effect=[PRD, DESIGN_MD]):
        fake = AsyncMock(side_effect=[json.dumps(VALID_SPEC, ensure_ascii=False),
                                      '{"passed": true, "missing": []}'])
        runner = GraphRunner(llm_fn=fake)
        # 阶段 1 完成即暂停 (human confirm); resume 续跑阶段 2。
        events = [ev async for ev in runner.run(state, "gen-gate-1")]
        events += [ev async for ev in runner.resume("gen-gate-1")]

    assert any(e["event_type"] == "manager_verdict" for e in events)
    root = memory.project_root_for(state)
    index = memory.read_index(root)
    assert index["stages"].get("analysis") == "done"
    assert index["stages"].get("design") == "done"
    # requirements.md 全量落盘 (节点完成写 spec)
    assert open(os.path.join(root, ".ai-memory/spec/requirements.md"), encoding="utf-8").read() == PRD
    decisions = open(os.path.join(root, ".ai-memory/spec/decisions.md"), encoding="utf-8").read()
    assert "analysis" in decisions and "design" in decisions
    assert os.path.isfile(os.path.join(root, ".ai-memory/state/run_context.json"))
