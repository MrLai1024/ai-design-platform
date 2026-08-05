"""Task group 5a (5.1-5.3) tests: 复杂度分档 / Spec 驱动 Planner / Executor 验收.

Covers:
- 5.1: tier.py — S/M/L assessment from Spec variants + design-doc fallback,
  per-tier role config in the code dispatch contract.
- 5.2: planner.py — Spec-driven user prompt (no hardcoded bootstrap count),
  system prompt no longer hardcodes "3 bootstrap tasks" / file-count caps.
- 5.3: executor_task — verify_contract wired into the loop (registry cache
  sees in-flight files), acceptance result {files_ok, contract_ok, compile_ok},
  backward-compatible result shape.
"""

import asyncio
import json
import tempfile

import pytest

from app.services.generation.planner import (
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_prompt,
    extract_task_dag,
)
from app.services.generation.tier import (
    TIER_ACCEPTANCE,
    assess_complexity,
    assess_complexity_detail,
    build_code_dispatch_contract,
)
from app.services.generation.tools.registry import ToolRegistry
from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent


# ── Fixtures / helpers ──


def _spec(**overrides):
    """A plausible D5 spec — override fields per test."""
    spec = {
        "spec_version": 1,
        "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "webpack", "style": "scss"},
        "directory_tree": {"src/": ["main.ts", "App.vue", "router/", "components/"]},
        "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
        "api_contracts": [{"name": "user/login", "method": "POST", "request": {}, "response": {}}],
        "routing": [{"path": "/", "page": "Home", "auth": False}],
        "state_management": {"store": "pinia", "stores": []},
        "component_tree": [{"name": "Header", "uses": ["NavMenu"], "props": []}],
        "pages": [
            {"id": "p-01", "name": "登录页", "interactions": [], "data": []},
            {"id": "p-02", "name": "首页", "interactions": [], "data": []},
        ],
        "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
    }
    spec.update(overrides)
    return spec


def _pages(n):
    return [
        {"id": f"p-{i:02d}", "name": f"页面{i}", "interactions": [], "data": []}
        for i in range(1, n + 1)
    ]


def _entities(n):
    return [
        {"name": f"Entity{i}", "fields": [{"name": "id", "type": "string"}]}
        for i in range(1, n + 1)
    ]


def _api(n):
    return [
        {"name": f"api/{i}", "method": "GET", "request": {}, "response": {}}
        for i in range(1, n + 1)
    ]


def _dirs(n):
    return {
        f"src/module{i}/": ["index.ts", "components/"]
        for i in range(1, n + 1)
    }


# ── 5.1: complexity tier assessment ──


class TestAssessComplexity:
    def test_s_simple_form_spec(self):
        assert assess_complexity(_spec(), "design doc") == "S"

    def test_s_with_state_framework_but_no_stores(self):
        # D5 requires state_management non-empty; the bare framework name alone
        # must not escalate to M.
        assert assess_complexity(_spec(), "") == "S"

    def test_m_multi_page(self):
        assert assess_complexity(_spec(pages=_pages(5)), "") == "M"

    def test_m_many_entities(self):
        assert assess_complexity(_spec(data_model=_entities(5)), "") == "M"

    def test_m_state_stores(self):
        spec = _spec(state_management={"store": "pinia", "stores": ["user", "cart"]})
        assert assess_complexity(_spec(), "") == "S"
        assert assess_complexity(spec, "") == "M"

    def test_l_permissions(self):
        spec = _spec(routing=[{"path": "/admin", "page": "Admin", "auth": True}])
        assert assess_complexity(spec, "") == "L"

    def test_l_api_layer(self):
        assert assess_complexity(_spec(api_contracts=_api(3)), "") == "L"

    def test_l_multi_module(self):
        assert assess_complexity(_spec(directory_tree=_dirs(4)), "") == "L"

    def test_l_priority_over_m(self):
        # auth present AND multi-page → L wins (priority order).
        spec = _spec(pages=_pages(6), routing=[{"path": "/a", "page": "A", "auth": True}])
        assert assess_complexity(spec, "") == "L"

    def test_single_api_entry_is_not_api_layer(self):
        assert assess_complexity(_spec(api_contracts=_api(2)), "") == "S"

    def test_fallback_doc_plain_is_s(self):
        doc = "## 3. 页面结构\n- 登录页\n- 首页"
        assert assess_complexity(None, doc) == "S"

    def test_fallback_doc_permissions_is_l(self):
        assert assess_complexity(None, "包含权限控制模块，需要 RBAC") == "L"

    def test_fallback_doc_state_management_is_m(self):
        assert assess_complexity(None, "多页面应用，使用 Pinia 状态管理") == "M"

    def test_fallback_doc_multi_module_is_l(self):
        assert assess_complexity(None, "工程为多模块设计，包含多个业务模块") == "L"

    def test_placeholder_spec_falls_back_to_doc(self):
        from app.services.generation.spec_schema import empty_spec
        # Schema-shaped placeholder Spec (structured-parse fallback) is treated
        # as absent → the design doc decides.
        assert assess_complexity(empty_spec(), "包含权限控制模块") == "L"
        assert assess_complexity(empty_spec(), "登录页、首页，简单表单") == "S"

    def test_detail_returns_reasons(self):
        tier, reasons = assess_complexity_detail(_spec(routing=[{"path": "/a", "page": "A", "auth": True}]), "")
        assert tier == "L"
        assert any("权限" in r for r in reasons)

    def test_build_code_dispatch_contract(self):
        contract = build_code_dispatch_contract("M", has_spec=True)
        assert contract["task_id"] == "code"
        assert contract["input_ref"] == "architecture_spec"
        assert contract["acceptance_criteria"] == ["编译通过", "契约一致"]
        assert contract["tier"] == "M"
        assert "verifier" in contract["roles"]
        assert contract["roles"] == TIER_ACCEPTANCE["M"]["roles"]

        legacy = build_code_dispatch_contract("S", has_spec=False)
        assert legacy["input_ref"] == "design_result"
        assert legacy["roles"] == ["planner", "executor"]

    def test_invalid_tier_defaults_to_s(self):
        assert build_code_dispatch_contract("XX", True)["tier"] == "S"


# ── 5.2: Spec-driven Planner ──


class TestPlannerSpecDriven:
    def test_system_prompt_no_hardcoded_heuristics(self):
        assert "3 个 bootstrap" not in PLANNER_SYSTEM_PROMPT
        assert "文件数不超过 5 个" not in PLANNER_SYSTEM_PROMPT
        # Spec-derived inputs are now the decomposition sources.
        for key in ("directory_tree", "data_model", "component_tree", "tech_stack"):
            assert key in PLANNER_SYSTEM_PROMPT

    def test_user_prompt_built_from_spec(self):
        prompt = build_planner_user_prompt(_spec(), "design doc")
        assert "## 架构 Spec" in prompt
        assert "### directory_tree" in prompt
        assert "### data_model" in prompt
        assert "### component_tree" in prompt
        assert "### tech_stack" in prompt
        assert "3 个 bootstrap" not in prompt
        # The old hardcode ("必须包含 qiankun 微应用必需的 3 个 bootstrap 任务")
        # is gone; qiankun now only appears as a generic derivation example.
        assert "必需的 3 个 bootstrap" not in prompt

    def test_user_prompt_spec_with_qiankun_build(self):
        spec = _spec(tech_stack={"framework": "vue3", "component_lib": "", "build": "qiankun", "style": ""})
        prompt = build_planner_user_prompt(spec, "")
        # The spec's build config is serialized for the planner to derive
        # bootstrap tasks from (derive, don't hardcode).
        assert '"build": "qiankun"' in prompt
        assert "directory_tree" in prompt

    def test_user_prompt_fallback_to_design_doc(self):
        prompt = build_planner_user_prompt(None, "设计方案文本内容")
        assert "设计方案" in prompt
        assert "设计方案文本内容" in prompt
        assert "3 个 bootstrap" not in prompt
        assert "必须包含 qiankun" not in prompt

    def test_user_prompt_with_failure(self):
        failure = {"instruction": "Header 组件未导出 title prop"}
        prompt = build_planner_user_prompt(_spec(), "design doc", failure)
        assert "Header 组件未导出 title prop" in prompt

    def test_extract_task_dag_unchanged(self):
        raw = (
            '```json\n{"reasoning": "r", "tasks": ['
            '{"id": "task-0", "type": "business", "description": "d", "files": ["a.vue"]}'
            "]}\n```"
        )
        dag = extract_task_dag(raw)
        assert dag["reasoning"] == "r"
        task = dag["tasks"][0]
        assert task["id"] == "task-0"
        assert task["status"] == "pending"      # defaults applied
        assert task["deps"] == []
        assert task["contract"] == {}


# ── 5.3: Executor acceptance + verify_contract wiring ──


class ScriptedProvider:
    """Fake LLM provider: yields scripted ToolCall/Token events per turn."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0
        self.seen_messages = None

    async def stream_generate(self, model, messages, config):
        self.seen_messages = messages
        if self.calls >= len(self.turns):
            yield TokenEvent(text="__TASK_DONE__", index=0)
            yield CompleteEvent(finish_reason="stop", usage={})
            return
        for ev in self.turns[self.calls]:
            yield ev
        self.calls += 1


def _tool_turn(name: str, args: dict, call_id: str = "call_1"):
    return [ToolCallEvent(call_id=call_id, name=name, arguments=json.dumps(args)),
            CompleteEvent(finish_reason="stop", usage={})]


def _text_turn(text: str):
    return [TokenEvent(text=text, index=0), CompleteEvent(finish_reason="stop", usage={})]


MY_BUTTON_OK = """<script setup lang="ts">
export const MyButton = () => "button"
</script>"""

HOME_PAGE = """<template><MyButton label="ok" /></template>
<script setup lang="ts">
import MyButton from '@/components/MyButton.vue'
const label = 'ok'
</script>"""


def _executor_state(task: dict) -> dict:
    return {
        "requirement": "测试工程",
        "design_doc": "设计方案",
        "planner_dag": {"tasks": [task]},
        "context_summary": {"key_exports": {}, "completed_tasks": []},
        "generated_files": {},
    }


async def _run_executor(task: dict, turns: list):
    """Run executor_task with a scripted provider; returns (result, events, registry, provider)."""
    from app.services.generation import nodes

    provider = ScriptedProvider(turns)
    old = nodes._provider
    nodes._provider = provider
    try:
        project_root = tempfile.mkdtemp(prefix="ai-gen-test-")
        registry = ToolRegistry(project_root)
        queue = asyncio.Queue()
        result = await nodes.executor_task(
            _executor_state(task), task, queue, project_root, registry
        )
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return result, events, registry, provider
    finally:
        nodes._provider = old


class TestExecutorAcceptance:
    TASK = {
        "id": "task-0",
        "type": "business",
        "description": "按钮组件与首页",
        "deps": [],
        "files": ["src/components/MyButton.vue", "src/pages/Home.vue"],
        "contract": {"exports": ["MyButton"], "props": {"label": "string"}},
        "status": "pending",
    }

    @pytest.mark.asyncio
    async def test_contract_violation_then_fix_then_pass(self):
        # Turn 1: write provider WITHOUT the required export (violation).
        # Turn 2: verify_contract → violations reported.
        # Turn 3: fix provider + write consumer (prop 'label' now in consumer).
        # Turn 4: verify_contract → match.
        # Turn 5: compile ok. Turn 6: __TASK_DONE__.
        bad_provider = """<script setup lang="ts">
export default { name: 'MyButton' }
</script>"""
        turns = [
            _tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": bad_provider}, "c1"),
            _tool_turn("write_code", {"path": "src/pages/Home.vue", "content": HOME_PAGE}, "c2"),
            _tool_turn("verify_contract", {
                "consumer_file": "src/pages/Home.vue",
                "provider_file": "src/components/MyButton.vue",
                "expected_interface": {"exports": ["MyButton"], "props": {"label": "string"}},
            }, "c3"),
            _tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": MY_BUTTON_OK}, "c4"),
            _tool_turn("verify_contract", {
                "consumer_file": "src/pages/Home.vue",
                "provider_file": "src/components/MyButton.vue",
                "expected_interface": {"exports": ["MyButton"], "props": {"label": "string"}},
            }, "c5"),
            _tool_turn("compile_project", {}, "c6"),
            _text_turn("__TASK_DONE__"),
        ]
        result, events, registry, provider = await _run_executor(self.TASK, turns)

        # Backward-compat: existing consumers' keys unchanged.
        for key in ("task_id", "status", "generated_files", "compile_errors", "summary"):
            assert key in result
        assert result["status"] == "done"

        # Acceptance: files + contract + compile all ok.
        assert result["acceptance"]["files_ok"] is True
        assert result["acceptance"]["contract_ok"] is True
        assert result["acceptance"]["compile_ok"] is True
        assert result["acceptance"]["details"]["missing_files"] == []

        # verify_contract results actually landed (first violated, then matched).
        contract_status = [e for e in events if e["event_type"] == "contract_status"]
        assert len(contract_status) == 2
        assert contract_status[0]["data"]["ok"] is False
        assert contract_status[0]["data"]["violations"]
        assert contract_status[1]["data"]["ok"] is True

        # task_acceptance event emitted with the same verdict.
        acceptance_events = [e for e in events if e["event_type"] == "task_acceptance"]
        assert len(acceptance_events) == 1
        assert acceptance_events[0]["data"]["contract_ok"] is True
        assert acceptance_events[0]["data"]["files_ok"] is True

        # Registry cache was synced with in-flight writes — verify_contract
        # found the provider file written mid-task (would have errored
        # "File not found" otherwise, breaking contract_ok).
        cache = registry.get_generated_files()
        assert "src/components/MyButton.vue" in cache
        assert "src/pages/Home.vue" in cache

        # Prompt drives the acceptance flow: system prompt mentions
        # verify_contract + 验收标准.
        system_prompt = provider.seen_messages[0].content
        user_msg = provider.seen_messages[1].content
        assert "verify_contract" in system_prompt
        assert "验收标准" in system_prompt
        assert "验收标准" in user_msg

    @pytest.mark.asyncio
    async def test_contract_failure_recorded_in_acceptance(self):
        # Model never fixes the contract — acceptance.contract_ok False even
        # though compile passes (task status stays compile-driven).
        bad_provider = """<script setup lang="ts">
export default { name: 'MyButton' }
</script>"""
        turns = [
            _tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": bad_provider}, "c1"),
            _tool_turn("write_code", {"path": "src/pages/Home.vue", "content": HOME_PAGE}, "c2"),
            _tool_turn("verify_contract", {
                "consumer_file": "src/pages/Home.vue",
                "provider_file": "src/components/MyButton.vue",
                "expected_interface": {"exports": ["MyButton"]},
            }, "c3"),
            _tool_turn("compile_project", {}, "c4"),
            _text_turn("__TASK_DONE__"),
        ]
        result, _, _, _ = await _run_executor(self.TASK, turns)

        assert result["status"] == "done"          # compile passed
        assert result["acceptance"]["contract_ok"] is False
        assert result["acceptance"]["compile_ok"] is True
        assert result["acceptance"]["files_ok"] is True
        assert result["acceptance"]["details"]["contract_results"][0]["violations"]

    @pytest.mark.asyncio
    async def test_contract_never_checked_is_unknown(self):
        turns = [
            _tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": MY_BUTTON_OK}, "c1"),
            _tool_turn("write_code", {"path": "src/pages/Home.vue", "content": HOME_PAGE}, "c2"),
            _tool_turn("compile_project", {}, "c3"),
            _text_turn("__TASK_DONE__"),
        ]
        result, _, _, _ = await _run_executor(self.TASK, turns)
        assert result["acceptance"]["contract_ok"] is None
        assert result["acceptance"]["files_ok"] is True

    @pytest.mark.asyncio
    async def test_missing_files_detected(self):
        # Task declares two files but the model only writes one.
        turns = [
            _tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": MY_BUTTON_OK}, "c1"),
            _tool_turn("compile_project", {}, "c2"),
            _text_turn("__TASK_DONE__"),
        ]
        result, events, _, _ = await _run_executor(self.TASK, turns)
        assert result["acceptance"]["files_ok"] is False
        assert result["acceptance"]["details"]["missing_files"] == ["src/pages/Home.vue"]
        acceptance_events = [e for e in events if e["event_type"] == "task_acceptance"]
        assert acceptance_events[0]["data"]["missing_files"] == ["src/pages/Home.vue"]

    @pytest.mark.asyncio
    async def test_vacuous_verify_contract_rejected(self):
        # verify_contract WITHOUT expected_interface must not pass vacuously:
        # the tool rejects it, acceptance records the failure (contract_ok
        # False) and the details distinguish the vacuous call.
        turns = [
            _tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": MY_BUTTON_OK}, "c1"),
            _tool_turn("write_code", {"path": "src/pages/Home.vue", "content": HOME_PAGE}, "c2"),
            _tool_turn("verify_contract", {
                "consumer_file": "src/pages/Home.vue",
                "provider_file": "src/components/MyButton.vue",
            }, "c3"),
            _tool_turn("compile_project", {}, "c4"),
            _text_turn("__TASK_DONE__"),
        ]
        result, events, _, _ = await _run_executor(self.TASK, turns)
        assert result["acceptance"]["contract_ok"] is False
        entry = result["acceptance"]["details"]["contract_results"][0]
        assert entry["expected_interface"] is None
        assert "expected_interface" in (entry["error"] or "")
        contract_status = [e for e in events if e["event_type"] == "contract_status"]
        assert contract_status[0]["data"]["ok"] is False


# ── 5.3 review: acceptance has teeth (planner_reflect consumes it) ──


class TestReflectConsumesAcceptance:
    def _dag_task(self, status: str, acceptance: dict | None) -> dict:
        return {
            "id": "task-0",
            "type": "business",
            "description": "t",
            "deps": [],
            "files": ["a.vue"],
            "contract": {},
            "status": status,
            "acceptance": acceptance,
        }

    async def _reflect(self, task: dict) -> dict:
        from app.services.generation import nodes
        dag = {"tasks": [task], "total_tasks": 1, "completed_tasks": 0}
        state = {
            "planner_dag": dag,
            "context_summary": {"key_exports": {}, "completed_tasks": []},
            "generated_files": {},
            "compile_errors": None,
            "planner_reflect_count": 0,
        }
        queue = asyncio.Queue()
        return await nodes.planner_reflect_node(state, queue)

    @pytest.mark.asyncio
    async def test_contract_false_marks_task_failed_and_retries(self):
        # contract_ok=False → the done task is flipped to failed, which the
        # reflect's auto-retry path resets to pending (retry once).
        task = self._dag_task("done", {
            "files_ok": True, "contract_ok": False, "compile_ok": True,
        })
        state = await self._reflect(task)
        retried = state["planner_dag"]["tasks"][0]
        assert retried["status"] == "pending"       # failed → auto-retry reset
        assert state["planner_reflect_count"] == 1
        assert state.get("stage_phase") != "complete"

    @pytest.mark.asyncio
    async def test_contract_none_does_not_fail(self):
        # verify_contract never called (contract_ok None) → warning only,
        # task stays done and the phase completes (5.4 Verifier is the backstop).
        task = self._dag_task("done", {
            "files_ok": True, "contract_ok": None, "compile_ok": True,
        })
        state = await self._reflect(task)
        assert state["planner_dag"]["tasks"][0]["status"] == "done"
        assert state.get("stage_phase") == "complete"

    @pytest.mark.asyncio
    async def test_contract_true_stays_done(self):
        task = self._dag_task("done", {
            "files_ok": True, "contract_ok": True, "compile_ok": True,
        })
        state = await self._reflect(task)
        assert state["planner_dag"]["tasks"][0]["status"] == "done"
        assert state.get("stage_phase") == "complete"


# ── 5.2 review: parse-failure fallback derived from the Spec ──


class TestFallbackDag:
    def test_fallback_from_spec_no_bootstrap_hardcode(self):
        from app.services.generation.nodes import build_fallback_dag
        spec = _spec()  # plain vue3/webpack spec, no qiankun
        dag = build_fallback_dag(spec, "design doc")
        assert len(dag["tasks"]) == 1
        task = dag["tasks"][0]
        assert task["type"] == "business"
        assert task["deps"] == []
        # files come from the Spec's directory_tree (leaf entries, as declared
        # by the Spec — "src/" maps to ["main.ts", "App.vue", ...]).
        assert "main.ts" in task["files"]
        assert "App.vue" in task["files"]
        assert "router/" not in task["files"]          # dirs excluded
        # contract annotated from the spec's data_model/pages.
        assert task["contract"]["data_entities"] == ["User"]
        assert task["contract"]["pages"] == ["登录页", "首页"]
        # no qiankun/bootstrap anywhere in the fallback.
        assert not any("bootstrap" in t["id"] for t in dag["tasks"])
        assert "qiankun" not in json.dumps(dag, ensure_ascii=False)
        assert "webpack/webpack.common.js" not in json.dumps(dag, ensure_ascii=False)

    def test_fallback_legacy_design_doc(self):
        from app.services.generation.nodes import build_fallback_dag
        dag = build_fallback_dag(None, "App.vue\ncomponents/Header.vue")
        assert dag["tasks"][0]["files"] == ["App.vue", "components/Header.vue"]
        assert dag["tasks"][0]["contract"] == {}
        assert "qiankun" not in json.dumps(dag, ensure_ascii=False)

    def test_fallback_empty_directory_tree_estimates(self):
        from app.services.generation.nodes import build_fallback_dag
        dag = build_fallback_dag({"directory_tree": {}}, "no files here")
        # no file-like lines → _estimate_files default
        assert dag["tasks"][0]["files"] == ["App.vue", "components/Header.vue"]


# ── 5.3 review: verify_contract vacuous-pass hole + events check ──


class TestVerifyContractHardening:
    @pytest.mark.asyncio
    async def test_missing_expected_interface_rejected(self):
        from app.services.generation.context_manager import verify_contract
        files = {"a.ts": "export const a = 1", "b.ts": "import { a } from './a'"}
        result = await verify_contract(files, "b.ts", "a.ts")     # omitted
        assert result.ok is False
        assert "expected_interface" in (result.error or "")
        result2 = await verify_contract(files, "b.ts", "a.ts", {})  # empty dict
        assert result2.ok is False
        assert "expected_interface" in (result2.error or "")

    @pytest.mark.asyncio
    async def test_events_checked(self):
        from app.services.generation.context_manager import verify_contract
        provider = "const x = 1\nconst emits = defineEmits<('submit' | 'cancel')>"
        consumer = "<Comp @submit='onSubmit' @cancel='onCancel' />"
        files = {"p.vue": provider, "c.vue": consumer}
        ok = await verify_contract(files, "c.vue", "p.vue", {"events": ["submit"]})
        assert ok.data["match"] is True
        bad = await verify_contract(files, "c.vue", "p.vue", {"events": ["refresh"]})
        assert bad.data["match"] is False
        assert bad.data["violations"][0]["type"] == "missing_event"
        assert "refresh" in bad.data["violations"][0]["detail"]

    @pytest.mark.asyncio
    async def test_events_checked_through_registry_schema(self):
        # The tool schema marks expected_interface as required.
        registry = ToolRegistry(tempfile.mkdtemp(prefix="ai-gen-test-"))
        schema = {t["function"]["name"]: t["function"]["parameters"].get("required", [])
                  for t in registry.get_schema()}
        assert schema["verify_contract"] == ["consumer_file", "provider_file", "expected_interface"]


# ── 5.1 review: exact-boundary thresholds + pagination stoplist ──


class TestTierBoundaries:
    def test_boundary_pages(self):
        assert assess_complexity(_spec(pages=_pages(3)), "") == "S"   # ≤3
        assert assess_complexity(_spec(pages=_pages(4)), "") == "M"   # >3

    def test_boundary_entities(self):
        assert assess_complexity(_spec(data_model=_entities(3)), "") == "S"  # ≤3
        assert assess_complexity(_spec(data_model=_entities(4)), "") == "M"  # >3

    def test_boundary_dirs(self):
        assert assess_complexity(_spec(directory_tree=_dirs(3)), "") == "S"  # <4
        assert assess_complexity(_spec(directory_tree=_dirs(4)), "") == "L"  # ≥4

    def test_boundary_api(self):
        assert assess_complexity(_spec(api_contracts=_api(2)), "") == "S"    # <3
        assert assess_complexity(_spec(api_contracts=_api(3)), "") == "L"    # ≥3

    def test_pagination_tokens_do_not_inflate_page_count(self):
        doc = "## 页面结构\n- 登录页\n- 首页\n分页组件：上一页 / 下一页 / 子页"
        # Without the stoplist these tokens would push page_count > 3 → spurious M.
        assert assess_complexity(None, doc) == "S"
