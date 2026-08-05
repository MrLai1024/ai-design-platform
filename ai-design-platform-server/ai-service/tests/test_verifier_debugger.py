"""Task group 5b (5.4 / 5.5 / 5.7) tests: Verifier 四层信号 / Debugger 证据链 / data-testid 埋点.

Covers:
- 5.7: verifier.scan_hooks — 关键交互元素缺 data-testid 的确定性扫描；
  EXECUTOR_SYSTEM_PROMPT 含埋点规则。
- 5.4: verifier.run_verifier — L1 编译（前端 bundler 反馈）/ L2 契约（任务
  DAG 推导的 verify_contract 兜底）/ L3 运行时（iframe 上报）；结果形状。
- 5.4 gate 集成: manager.run_l1_checks 消费 verifier_result。
- 5.5: debugger — LLM 诊断（seam）/ 重派（apply_fix_round）/ 无进展检测
  （证据签名重复停止）；executor 重派时消费 fix_instructions。
- 5.4 全链路: servicer ReportRuntimeFeedback 存到 runner registry。
"""

import asyncio
import json
import re
import tempfile

import pytest

from app.services.generation import nodes
from app.services.generation.debugger import (
    MAX_FIX_ROUNDS,
    apply_fix_round,
    build_diagnosis_prompt,
    diagnose,
    no_progress,
    record_round,
)
from app.services.generation.manager import run_l1_checks
from app.services.generation.tools.registry import ToolRegistry
from app.services.generation.verifier import (
    check_contracts,
    evidence_signature,
    run_verifier,
    scan_hooks,
)

# ── 5.7: data-testid 埋点钩子扫描 ──


class TestScanHooks:
    def test_flags_button_without_testid(self):
        files = {
            "src/pages/Home.vue": '<template>\n  <button>保存</button>\n</template>',
        }
        violations = scan_hooks(files)
        assert len(violations) == 1
        assert violations[0]["file"] == "src/pages/Home.vue"
        assert violations[0]["tag"] == "button"
        assert violations[0]["line"] == 2

    def test_passes_with_testid(self):
        files = {
            "src/pages/Home.vue": (
                '<template>\n  <button data-testid="save-button">保存</button>\n'
                '  <input data-testid="search-input" placeholder="搜索" />\n'
                "</template>"
            ),
        }
        assert scan_hooks(files) == []

    def test_flags_interactive_element_components(self):
        files = {
            "src/pages/List.vue": (
                '<el-pagination :total="100" />\n'
                '<el-dialog title="x">内容</el-dialog>\n'
                '<el-tabs><el-tab-pane label="a" /></el-tabs>\n'
            ),
        }
        tags = {v["tag"] for v in scan_hooks(files)}
        assert "el-pagination" in tags
        assert "el-dialog" in tags
        assert "el-tab-pane" in tags

    def test_skips_non_interactive_and_exemptions(self):
        files = {
            "src/pages/Home.vue": (
                '<div class="wrap"><span>标题</span></div>\n'
                '<a name="anchor"></a>\n'                        # 无 href 的 a 不算交互
                '<input type="hidden" name="token" />\n'         # hidden input 不算交互
                '<img src="x.png" />\n'
            ),
        }
        assert scan_hooks(files) == []

    def test_flags_anchor_with_href(self):
        files = {"src/pages/Home.vue": '<a href="/detail">详情</a>'}
        assert len(scan_hooks(files)) == 1

    def test_multi_line_tag_checked_as_one(self):
        files = {
            "src/pages/Home.vue": (
                '<el-pagination\n  :total="100"\n  layout="prev, pager, next"\n/>'
            ),
        }
        violations = scan_hooks(files)
        assert len(violations) == 1
        assert violations[0]["tag"] == "el-pagination"
        assert violations[0]["line"] == 1

    def test_quoted_gt_inside_attribute_does_not_split_tag(self):
        """Review fix (Minor): 属性值里的 > 不应终止标签（引号包裹整体跳过）。"""
        # 无 testid → 一个完整违规（旧正则会把标签拆成两段、漏判/误判）
        files = {
            "src/pages/Home.vue": '<button title="a > b" content="x > y">保存</button>',
        }
        violations = scan_hooks(files)
        assert len(violations) == 1
        assert violations[0]["tag"] == "button"
        assert 'content="x > y"' in violations[0]["snippet"]
        # 带 testid → 通过（旧正则会在属性区前段找不到 testid 而误报）
        files = {
            "src/pages/Home.vue": '<button data-testid="save-button" title="a > b">保存</button>',
        }
        assert scan_hooks(files) == []

    def test_el_table_and_el_tree_are_interactive(self):
        files = {
            "src/pages/List.vue": (
                '<el-table :data="rows"><el-table-column prop="name" /></el-table>\n'
                '<el-tree :data="tree" />\n'
            ),
        }
        tags = {v["tag"] for v in scan_hooks(files)}
        assert "el-table" in tags
        assert "el-tree" in tags

    def test_only_vue_files_scanned(self):
        files = {
            "src/main.ts": '<button>save</button>',   # 非 .vue 不扫
            "src/App.vue": '<button data-testid="ok">x</button>',
        }
        assert scan_hooks(files) == []

    def test_executor_prompt_mandates_testid(self):
        assert "data-testid" in nodes.EXECUTOR_SYSTEM_PROMPT
        assert "kebab-case" in nodes.EXECUTOR_SYSTEM_PROMPT
        assert "save-button" in nodes.EXECUTOR_SYSTEM_PROMPT
        assert "Verifier" in nodes.EXECUTOR_SYSTEM_PROMPT


# ── 5.4: Verifier 四层信号 ──


def _state_with_tasks(files: dict, tasks: list | None = None) -> dict:
    tasks = tasks if tasks is not None else [
        {
            "id": "task-0",
            "type": "business",
            "description": "按钮组件与首页",
            "deps": [],
            "files": list(files.keys()),
            "contract": {"exports": []},
            "status": "done",
        },
    ]
    return {
        "requirement": "测试工程",
        "design_doc": "设计方案",
        "architecture_spec": {"pages": [], "directory_tree": {}},
        "generated_files": files,
        "code_result": json.dumps(files, ensure_ascii=False),
        "compile_errors": None,
        "planner_dag": {"tasks": tasks},
        "context_summary": {"key_exports": {}, "completed_tasks": []},
        "dispatch_contract": {"task_id": "code", "roles": ["planner", "executor", "verifier", "debugger"]},
    }


class TestVerifierL1:
    @pytest.mark.asyncio
    async def test_l1_fails_on_frontend_compile_errors(self):
        state = _state_with_tasks({"src/App.vue": "<template><div>hi</div></template>"})
        registry = ToolRegistry(tempfile.mkdtemp())
        registry.report_frontend_compile(False, [
            {"file": "src/App.vue", "line": 3, "column": 5, "text": "Unexpected token"},
        ])
        result = await run_verifier(state, registry, tier="M")
        assert result["l1_ok"] is False
        assert result["passed"] is False
        assert any(
            "Unexpected token" in e.get("message", "")
            for e in result["evidence"]["compile_errors"]
        )

    @pytest.mark.asyncio
    async def test_l1_passes_without_errors(self):
        state = _state_with_tasks({"src/App.vue": "<template><div>hi</div></template>"})
        registry = ToolRegistry(tempfile.mkdtemp())
        registry.report_frontend_compile(True)
        result = await run_verifier(state, registry)
        assert result["l1_ok"] is True

    @pytest.mark.asyncio
    async def test_l1_fails_on_empty_code(self):
        state = _state_with_tasks({})
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l1_ok"] is False
        assert any(e.get("message") for e in result["evidence"]["compile_errors"])


class TestVerifierL2:
    TASK = {
        "id": "task-0",
        "type": "business",
        "description": "按钮组件",
        "deps": [],
        "files": ["src/components/MyButton.vue"],
        "contract": {"exports": ["MyButton"]},
        "status": "done",
    }

    @pytest.mark.asyncio
    async def test_l2_detects_missing_export(self):
        # 生成的文件没有导出契约要求的 MyButton
        files = {
            "src/components/MyButton.vue": '<script setup lang="ts">\nexport const NotButton = 1\n</script>',
        }
        state = _state_with_tasks(files, [dict(self.TASK)])
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l2_ok"] is False
        assert result["passed"] is False
        assert any(
            v["type"] == "missing_export"
            for v in result["evidence"]["contract_violations"]
        )

    @pytest.mark.asyncio
    async def test_l2_passes_when_contract_met(self):
        files = {
            "src/components/MyButton.vue": '<script setup lang="ts">\nexport const MyButton = 1\n</script>',
        }
        state = _state_with_tasks(files, [dict(self.TASK)])
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l2_ok"] is True

    @pytest.mark.asyncio
    async def test_l2_dep_pair_violation(self):
        task = {
            "id": "task-1",
            "type": "business",
            "description": "页面消费按钮组件",
            "deps": ["task-0"],
            "files": ["src/pages/Home.vue"],
            "contract": {"exports": [], "props": ["label"]},
            "status": "done",
        }
        dep = dict(self.TASK)
        dep["files"] = ["src/components/MyButton.vue"]
        files = {
            "src/components/MyButton.vue": '<script setup lang="ts">\nexport const MyButton = 1\n</script>',
            # 消费者没有传 prop 'label'（字符串检索不到 label 的引用形式之一）
            "src/pages/Home.vue": '<template><MyButton /></template>\n<script setup lang="ts">\nimport MyButton from "@/components/MyButton.vue"\n</script>',
        }
        state = _state_with_tasks(files, [dep, task])
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l2_ok"] is False
        assert any(
            v.get("pair", "").startswith("src/pages/Home.vue →")
            for v in result["evidence"]["contract_violations"]
        )

    @pytest.mark.asyncio
    async def test_contract_task_with_missing_files_fails(self):
        task = dict(self.TASK)
        task["files"] = ["src/components/MyButton.vue"]
        files = {}  # 契约文件一个都没生成
        state = _state_with_tasks(files, [task])
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l2_ok"] is False
        missing = [v for v in result["evidence"]["contract_violations"] if v["type"] == "missing_file"]
        assert len(missing) == 1
        assert missing[0]["file"] == "src/components/MyButton.vue"

    @pytest.mark.asyncio
    async def test_l2_flags_each_missing_file_individually(self):
        """Review fix (Important): 部分缺失也逐路径上报，不依赖全有全无。"""
        task = dict(self.TASK)
        task["files"] = ["src/components/MyButton.vue", "src/components/MyList.vue"]
        files = {"src/components/MyButton.vue": "<script setup lang=\"ts\">\nexport const MyButton = 1\n</script>"}
        state = _state_with_tasks(files, [task])
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l2_ok"] is False
        missing = [v for v in result["evidence"]["contract_violations"] if v["type"] == "missing_file"]
        assert len(missing) == 1
        assert missing[0]["file"] == "src/components/MyList.vue"
        assert "MyButton" in missing[0]["detail"] or "MyList" in missing[0]["detail"]


class TestVerifierL3:
    @pytest.mark.asyncio
    async def test_l3_fails_on_reported_runtime_errors(self):
        state = _state_with_tasks({"src/App.vue": "<template><div>hi</div></template>"})
        registry = ToolRegistry(tempfile.mkdtemp())
        registry.report_runtime_errors([
            {"type": "console_error", "message": "Cannot read property 'x'"},
        ])
        result = await run_verifier(state, registry)
        assert result["l3_ok"] is False
        assert result["evidence"]["runtime_errors"] == [
            {"type": "console_error", "message": "Cannot read property 'x'"},
        ]

    @pytest.mark.asyncio
    async def test_l3_passes_when_empty(self):
        state = _state_with_tasks({"src/App.vue": "<template><div>hi</div></template>"})
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["l3_ok"] is True

    @pytest.mark.asyncio
    async def test_l3_clear_with_empty_batch(self):
        registry = ToolRegistry(tempfile.mkdtemp())
        registry.report_runtime_errors([{"type": "uncaught", "message": "boom"}])
        registry.report_runtime_errors([])   # 新构建加载 → 清空
        assert registry.get_runtime_errors() == []


class TestVerifierHooks:
    @pytest.mark.asyncio
    async def test_hooks_fail_and_evidence_carries_list(self):
        files = {
            "src/pages/Home.vue": '<template>\n  <button>保存</button>\n</template>',
        }
        state = _state_with_tasks(files)
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["hooks_ok"] is False
        assert result["passed"] is False
        assert result["evidence"]["hook_violations"][0]["tag"] == "button"

    @pytest.mark.asyncio
    async def test_hooks_pass_with_testid(self):
        files = {
            "src/pages/Home.vue": (
                '<template>\n  <button data-testid="save-button">保存</button>\n'
                '<a data-testid="detail-link" href="/d">详情</a>\n</template>'
            ),
        }
        state = _state_with_tasks(files)
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry)
        assert result["hooks_ok"] is True


class TestVerifierResultShape:
    @pytest.mark.asyncio
    async def test_result_shape(self):
        files = {"src/App.vue": "<template><div>hi</div></template>"}
        state = _state_with_tasks(files)
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="M")
        for key in ("l1_ok", "l2_ok", "l3_ok", "hooks_ok", "passed", "tier", "output_signature"):
            assert key in result
        assert result["tier"] == "M"
        for key in ("compile_errors", "contract_violations", "runtime_errors", "hook_violations"):
            assert key in result["evidence"]
        assert result["passed"] == (result["l1_ok"] and result["l2_ok"] and result["l3_ok"] and result["hooks_ok"])

    @pytest.mark.asyncio
    async def test_verifier_stamps_output_signature_of_verified_output(self):
        """Review fix (Critical): verdict 与它验证过的 code_result 绑定。"""
        from app.services.generation.manager import _output_signature

        files = {"src/App.vue": "<template><div>hi</div></template>"}
        state = _state_with_tasks(files)
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="M")
        assert result["output_signature"] == _output_signature(state, "code")
        # 输出变化 → 签名变化（gate 据此识别 stale verdict）
        state["code_result"] = json.dumps({"src/App.vue": "<template><div>changed</div></template>"})
        assert result["output_signature"] != _output_signature(state, "code")

    @pytest.mark.asyncio
    async def test_evidence_signature_deterministic(self):
        ev = {"compile_errors": [{"file": "a.vue", "line": 1, "message": "x"}], "hook_violations": [], "runtime_errors": [], "contract_violations": []}
        assert evidence_signature(ev) == evidence_signature(dict(ev))
        assert evidence_signature(ev) != evidence_signature({"compile_errors": [], "hook_violations": [], "runtime_errors": [], "contract_violations": []})


# ── 5.4 gate 集成: manager.run_l1_checks 消费 verifier_result ──


class TestGateConsumesVerifier:
    def _code_state(self, **overrides):
        state = {
            "analysis_result": "PRD",
            "design_result": "设计",
            "architecture_spec": {"pages": []},
            "code_result": json.dumps({"src/App.vue": "<template><div>hi</div></template>"}),
            "generated_files": {"src/App.vue": "<template><div>hi</div></template>"},
            "compile_errors": None,
            "verifier_result": None,
        }
        state.update(overrides)
        return state

    def test_pass_without_verifier_result(self):
        assert run_l1_checks(self._code_state(), "code") == []

    def test_fail_surfaces_verifier_layers(self):
        from app.services.generation.manager import _output_signature

        base = self._code_state()
        state = self._code_state(verifier_result={
            "l1_ok": True, "l2_ok": False, "l3_ok": True, "hooks_ok": False,
            "passed": False,
            "evidence": {"compile_errors": [], "contract_violations": [{"type": "x"}], "runtime_errors": [], "hook_violations": [{"file": "a.vue"}]},
            "output_signature": _output_signature(base, "code"),
        })
        errors = run_l1_checks(state, "code")
        assert any("L2 契约未通过" in e for e in errors)
        assert any("埋点钩子未通过" in e for e in errors)

    def test_pass_with_passed_verifier(self):
        state = self._code_state(verifier_result={
            "l1_ok": True, "l2_ok": True, "l3_ok": True, "hooks_ok": True,
            "passed": True, "evidence": {"compile_errors": [], "contract_violations": [], "runtime_errors": [], "hook_violations": []},
        })
        assert run_l1_checks(state, "code") == []

    def test_stale_verifier_skipped_after_regeneration(self):
        """Review fix (Critical): verifier 失败 → gate redo → code_node 整仓
        重写（code_result 签名变化）→ gate 不再复用 stale verdict → 全新 L1
        判定（否则形成永久 redo 循环）。"""
        from app.services.generation.manager import _output_signature

        old_code = json.dumps({"src/App.vue": "<template><div>old</div></template>"})
        state = self._code_state(
            code_result=old_code,
            verifier_result={
                "l1_ok": True, "l2_ok": False, "l3_ok": True, "hooks_ok": True,
                "passed": False,
                "evidence": {"compile_errors": [], "contract_violations": [{"type": "missing_export"}], "runtime_errors": [], "hook_violations": []},
                "output_signature": _output_signature(self._code_state(code_result=old_code), "code"),
            },
        )
        # 同一份输出 → verdict 生效 → redo
        assert any("L2 契约未通过" in e for e in run_l1_checks(state, "code"))

        # 代码重新生成 → 签名变化 → stale verdict 被跳过 → 全新 L1 通过
        state["code_result"] = json.dumps({"src/App.vue": "<template><div>new</div></template>"})
        assert run_l1_checks(state, "code") == []

    def test_verifier_without_signature_never_blocks_gate(self):
        """旧格式 verdict（无 output_signature）不参与把关 —— 不做假设，宁可放行由 L1 判定。"""
        state = self._code_state(verifier_result={
            "l1_ok": True, "l2_ok": False, "l3_ok": True, "hooks_ok": True,
            "passed": False, "evidence": {"compile_errors": [], "contract_violations": [], "runtime_errors": [], "hook_violations": []},
        })
        assert run_l1_checks(state, "code") == []


# ── 5.5: Debugger ──


class TestDebuggerDiagnose:
    async def _diagnose_with(self, raw: str):
        async def fake_llm(system_prompt: str, user_prompt: str) -> str:
            return raw
        state = _state_with_tasks({"src/components/MyButton.vue": "content"})
        return await diagnose(state, {"compile_errors": [], "contract_violations": [], "runtime_errors": [], "hook_violations": []}, fake_llm)

    @pytest.mark.asyncio
    async def test_diagnose_parses_structured_output(self):
        result = await self._diagnose_with(
            '{"root_cause": "MyButton 未导出", "fix_instructions": "补上 export const MyButton", "affected_files": ["src/components/MyButton.vue"]}'
        )
        assert result["root_cause"] == "MyButton 未导出"
        assert "MyButton" in result["fix_instructions"]
        assert result["affected_files"] == ["src/components/MyButton.vue"]

    @pytest.mark.asyncio
    async def test_diagnose_failsafe_on_garbage(self):
        result = await self._diagnose_with("这不是 JSON")
        assert result == {"root_cause": "", "fix_instructions": "", "affected_files": []}

    @pytest.mark.asyncio
    async def test_diagnose_prompt_contains_evidence_and_files(self):
        state = _state_with_tasks({"src/App.vue": "content"})
        evidence = {
            "compile_errors": [{"file": "src/App.vue", "line": 3, "message": "bad token"}],
            "contract_violations": [{"type": "missing_export", "file": "src/App.vue", "detail": "缺 MyButton"}],
            "runtime_errors": [{"type": "uncaught", "message": "boom"}],
            "hook_violations": [{"file": "src/App.vue", "tag": "button", "line": 5}],
        }
        prompt = build_diagnosis_prompt(state, evidence)
        assert "bad token" in prompt
        assert "missing_export" in prompt
        assert "boom" in prompt
        assert "data-testid" in prompt
        assert "### src/App.vue\ncontent" in prompt  # 相关文件内容注入


class TestDebuggerNoProgress:
    def test_same_signature_is_no_progress(self):
        state = {"debugger_rounds": [{"round": 1, "signature": "abc123", "diagnosis": {}}]}
        assert no_progress(state, "abc123") is True
        assert no_progress(state, "other") is False
        assert no_progress({}, "abc123") is False

    def test_record_round_appends(self):
        state: dict = {}
        record_round(state, "sig-1", {"root_cause": "x"})
        record_round(state, "sig-2", {"root_cause": "y"})
        assert [r["signature"] for r in state["debugger_rounds"]] == ["sig-1", "sig-2"]
        assert state["debugger_rounds"][0]["round"] == 1
        assert state["debugger_rounds"][1]["round"] == 2

    def test_max_fix_rounds_bounded(self):
        assert MAX_FIX_ROUNDS == 2


class TestApplyFixRound:
    def _dag_state(self, tasks):
        return {"planner_dag": {"tasks": tasks}, "generated_files": {}}

    def test_marks_affected_task_pending_with_instructions(self):
        tasks = [
            {"id": "t0", "files": ["a.vue"], "status": "done"},
            {"id": "t1", "files": ["b.vue"], "status": "done"},
        ]
        state = self._dag_state(tasks)
        affected = apply_fix_round(state, {
            "root_cause": "缺 data-testid",
            "fix_instructions": "给按钮补 data-testid",
            "affected_files": ["a.vue"],
        })
        assert affected == ["t0"]
        assert tasks[0]["status"] == "pending"
        assert tasks[0]["fix_instructions"] == "给按钮补 data-testid"
        assert tasks[0]["root_cause"] == "缺 data-testid"
        assert tasks[0]["compile_errors"] is None
        assert tasks[1]["status"] == "done"

    def test_fallback_to_failed_tasks(self):
        tasks = [
            {"id": "t0", "files": ["a.vue"], "status": "failed"},
            {"id": "t1", "files": ["b.vue"], "status": "done"},
        ]
        state = self._dag_state(tasks)
        affected = apply_fix_round(state, {"root_cause": "", "fix_instructions": "", "affected_files": []})
        assert affected == ["t0"]
        assert tasks[0]["status"] == "pending"

    def test_fallback_to_all_when_nothing_matches(self):
        tasks = [{"id": "t0", "files": ["a.vue"], "status": "done"}]
        state = self._dag_state(tasks)
        affected = apply_fix_round(state, {"affected_files": ["zzz.vue"], "fix_instructions": ""})
        assert affected == ["t0"]
        assert tasks[0]["status"] == "pending"

    def test_instructions_only_on_evidence_owning_tasks(self):
        """Review fix (Important): 兜底重派不复制诊断到无关任务。"""
        # fallback (c): affected_files 为空 → 全部 pending，但无任务拿到修复指令
        tasks = [
            {"id": "t0", "files": ["a.vue"], "status": "done"},
            {"id": "t1", "files": ["b.vue"], "status": "done"},
        ]
        state = self._dag_state(tasks)
        apply_fix_round(state, {"root_cause": "rc", "fix_instructions": "fi", "affected_files": []})
        assert all(t["status"] == "pending" for t in tasks)
        assert all("fix_instructions" not in t and "root_cause" not in t for t in tasks)

        # fallback (b): failed 任务不拥有证据文件 → 重派但不带指令
        tasks = [{"id": "t0", "files": ["a.vue"], "status": "failed"}]
        state = self._dag_state(tasks)
        apply_fix_round(state, {"root_cause": "rc", "fix_instructions": "fi", "affected_files": ["zzz.vue"]})
        assert tasks[0]["status"] == "pending"
        assert "fix_instructions" not in tasks[0] and "root_cause" not in tasks[0]

        # 主路径: 拥有证据文件的任务拿到指令
        tasks = [{"id": "t0", "files": ["a.vue"], "status": "done"}]
        state = self._dag_state(tasks)
        apply_fix_round(state, {"root_cause": "rc", "fix_instructions": "fi", "affected_files": ["a.vue"]})
        assert tasks[0]["fix_instructions"] == "fi"
        assert tasks[0]["root_cause"] == "rc"


class TestDebuggerFixRoundIntegration:
    """5.5 闭环: 验证失败 → 诊断 → 重派 → 修复后重新验证通过。

    模拟 graph phase 3 的修复轮（证据链 → apply_fix_round → 重跑受影响
    executor 任务 → run_verifier），不驱动完整 graph（planner 等无关环节）。
    """

    TASK = {
        "id": "task-0",
        "type": "business",
        "description": "按钮组件",
        "deps": [],
        "files": ["src/components/MyButton.vue"],
        "contract": {"exports": ["MyButton"]},
        "status": "done",
    }

    @pytest.mark.asyncio
    async def test_fix_round_contract_violation_repairs_and_passes(self):
        from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent

        class ScriptedProvider:
            def __init__(self, turns):
                self.turns = list(turns)
                self.calls = 0
                self.prompts = []

            async def stream_generate(self, model, messages, config):
                self.prompts.append(messages)
                if self.calls >= len(self.turns):
                    yield TokenEvent(text="__TASK_DONE__", index=0)
                    yield CompleteEvent(finish_reason="stop", usage={})
                    return
                for ev in self.turns[self.calls]:
                    yield ev
                self.calls += 1

        def tool_turn(name, args, call_id="call_1"):
            return [ToolCallEvent(call_id=call_id, name=name, arguments=json.dumps(args)),
                    CompleteEvent(finish_reason="stop", usage={})]

        def done_turn():
            return [TokenEvent(text="__TASK_DONE__", index=0),
                    CompleteEvent(finish_reason="stop", usage={})]

        BAD = '<template><div>bad</div></template>\n<script setup lang="ts">\nexport const NotMyButton = 1\n</script>'
        GOOD = '<template><MyButton /></template>\n<script setup lang="ts">\nexport const MyButton = 1\n</script>'

        # 每个 LLM 轮次一个动作：工具调用轮次后跟独立的 __TASK_DONE__ 文本轮次。
        provider = ScriptedProvider([
            tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": BAD}, "c1"),
            done_turn(),
            tool_turn("write_code", {"path": "src/components/MyButton.vue", "content": GOOD}, "c2"),
            done_turn(),
        ])

        old = nodes._provider
        nodes._provider = provider
        try:
            project_root = tempfile.mkdtemp(prefix="ai-gen-test-")
            registry = ToolRegistry(project_root)
            task = json.loads(json.dumps(self.TASK))
            state = {
                "requirement": "测试工程",
                "design_doc": "设计",
                "planner_dag": {"tasks": [task]},
                "context_summary": {"key_exports": {}, "completed_tasks": []},
                "generated_files": {},
                "dispatch_contract": {"task_id": "code", "roles": ["planner", "executor", "verifier", "debugger"]},
                "code_result": "{}",
            }

            # ── 第一轮: 生成缺失导出的文件 ──
            queue = asyncio.Queue()
            result = await nodes.executor_task(state, task, queue, project_root, registry)
            assert result["status"] == "done"
            for path, content in result["generated_files"].items():
                state["generated_files"][path] = content
            state["code_result"] = json.dumps(state["generated_files"], ensure_ascii=False)

            # ── 验证失败（L2 契约违约） ──
            verifier = await run_verifier(state, registry, tier="L")
            assert verifier["l2_ok"] is False
            assert verifier["passed"] is False

            # ── 诊断（fake LLM）+ 重派 ──
            async def fake_llm(system_prompt, user_prompt):
                return ('{"root_cause": "MyButton 未导出", '
                        '"fix_instructions": "补上 export const MyButton", '
                        '"affected_files": ["src/components/MyButton.vue"]}')
            diagnosis = await diagnose(state, verifier["evidence"], fake_llm)
            affected = apply_fix_round(state, diagnosis)
            assert affected == ["task-0"]
            assert task["status"] == "pending"

            # ── 修复轮: 重跑受影响任务（prompt 含修复指令） ──
            queue = asyncio.Queue()
            result = await nodes.executor_task(state, task, queue, project_root, registry)
            assert result["status"] == "done"
            assert "补上 export const MyButton" in provider.prompts[-1][1].content
            for path, content in result["generated_files"].items():
                state["generated_files"][path] = content
            state["code_result"] = json.dumps(state["generated_files"], ensure_ascii=False)

            # ── 重新验证通过 ──
            verifier = await run_verifier(state, registry, tier="L")
            assert verifier["passed"] is True
        finally:
            nodes._provider = old

    @pytest.mark.asyncio
    async def test_fix_round_hooks_violation_repairs_and_passes(self):
        """5.7 闭环: 缺 data-testid → 修复轮补钩子 → 重新验证通过。"""
        from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent

        class ScriptedProvider:
            def __init__(self, turns):
                self.turns = list(turns)
                self.calls = 0

            async def stream_generate(self, model, messages, config):
                if self.calls >= len(self.turns):
                    yield TokenEvent(text="__TASK_DONE__", index=0)
                    yield CompleteEvent(finish_reason="stop", usage={})
                    return
                for ev in self.turns[self.calls]:
                    yield ev
                self.calls += 1

        def tool_turn(name, args, call_id="call_1"):
            return [ToolCallEvent(call_id=call_id, name=name, arguments=json.dumps(args)),
                    CompleteEvent(finish_reason="stop", usage={})]

        def done_turn():
            return [TokenEvent(text="__TASK_DONE__", index=0),
                    CompleteEvent(finish_reason="stop", usage={})]

        BAD = '<template>\n  <button>保存</button>\n</template>'
        GOOD = '<template>\n  <button data-testid="save-button">保存</button>\n</template>'

        # 每个 LLM 轮次一个动作：工具调用轮次后跟独立的 __TASK_DONE__ 文本轮次。
        provider = ScriptedProvider([
            tool_turn("write_code", {"path": "src/pages/Home.vue", "content": BAD}, "c1"),
            done_turn(),
            tool_turn("write_code", {"path": "src/pages/Home.vue", "content": GOOD}, "c2"),
            done_turn(),
        ])

        old = nodes._provider
        nodes._provider = provider
        try:
            project_root = tempfile.mkdtemp(prefix="ai-gen-test-")
            registry = ToolRegistry(project_root)
            task = {
                "id": "task-0",
                "type": "business",
                "description": "首页",
                "deps": [],
                "files": ["src/pages/Home.vue"],
                "contract": {},
                "status": "done",
            }
            state = {
                "requirement": "测试工程",
                "design_doc": "设计",
                "planner_dag": {"tasks": [task]},
                "context_summary": {"key_exports": {}, "completed_tasks": []},
                "generated_files": {},
                "dispatch_contract": {"task_id": "code", "roles": ["planner", "executor", "verifier", "debugger"]},
                "code_result": "{}",
            }

            queue = asyncio.Queue()
            result = await nodes.executor_task(state, task, queue, project_root, registry)
            for path, content in result["generated_files"].items():
                state["generated_files"][path] = content
            state["code_result"] = json.dumps(state["generated_files"], ensure_ascii=False)

            verifier = await run_verifier(state, registry, tier="M")
            assert verifier["hooks_ok"] is False
            assert verifier["evidence"]["hook_violations"][0]["tag"] == "button"

            async def fake_llm(system_prompt, user_prompt):
                return ('{"root_cause": "保存按钮缺 data-testid", '
                        '"fix_instructions": "给按钮补 data-testid=save-button", '
                        '"affected_files": ["src/pages/Home.vue"]}')
            diagnosis = await diagnose(state, verifier["evidence"], fake_llm)
            apply_fix_round(state, diagnosis)
            assert task["status"] == "pending"

            queue = asyncio.Queue()
            result = await nodes.executor_task(state, task, queue, project_root, registry)
            for path, content in result["generated_files"].items():
                state["generated_files"][path] = content
            state["code_result"] = json.dumps(state["generated_files"], ensure_ascii=False)

            verifier = await run_verifier(state, registry, tier="M")
            assert verifier["hooks_ok"] is True
            assert verifier["passed"] is True
        finally:
            nodes._provider = old


class TestExecutorFixContext:
    """5.5: 重派时 executor 消费 task 上的 fix_instructions。"""

    TASK = {
        "id": "task-0",
        "type": "business",
        "description": "按钮组件与首页",
        "deps": [],
        "files": ["src/components/MyButton.vue"],
        "contract": {},
        "status": "pending",
        "fix_instructions": "给按钮补 data-testid=save-button",
        "root_cause": "埋点缺失",
    }

    @pytest.mark.asyncio
    async def test_fix_instructions_threaded_into_prompt(self):
        from app.services.llm.provider import CompleteEvent, TokenEvent

        class ScriptedProvider:
            async def stream_generate(self, model, messages, config):
                self.seen_messages = messages
                yield TokenEvent(text="__TASK_DONE__", index=0)
                yield CompleteEvent(finish_reason="stop", usage={})

        provider = ScriptedProvider()
        old = nodes._provider
        nodes._provider = provider
        try:
            project_root = tempfile.mkdtemp(prefix="ai-gen-test-")
            registry = ToolRegistry(project_root)
            queue = asyncio.Queue()
            state = {
                "requirement": "测试工程",
                "design_doc": "设计",
                "planner_dag": {"tasks": [dict(self.TASK)]},
                "context_summary": {"key_exports": {}, "completed_tasks": []},
                "generated_files": {},
            }
            await nodes.executor_task(state, self.TASK, queue, project_root, registry)
        finally:
            nodes._provider = old

        user_msg = provider.seen_messages[1].content
        assert "Debugger 修复指令" in user_msg
        assert "data-testid=save-button" in user_msg
        assert "埋点缺失" in user_msg


class TestGraphFixRoundLoop:
    """Review fix (Minor 8): 驱动真实 graph.py phase-3 修复轮 —— 不手动
    重实现循环。覆盖: 依赖顺序重派、no-progress 熔断 → Manager 把关。"""

    DAG = {
        "reasoning": "test",
        "tasks": [
            # 消费者排在列表最前 —— 依赖顺序不按列表序，按 deps_ok 门
            {"id": "task-1", "type": "business", "description": "消费者页面",
             "deps": ["task-0"], "files": ["src/pages/Consumer.vue"], "contract": {}, "status": "pending"},
            {"id": "task-0", "type": "business", "description": "提供者组件",
             "deps": [], "files": ["src/components/Provider.vue"], "contract": {}, "status": "pending"},
        ],
    }

    BAD_PROVIDER = "<template>\n  <button>P</button>\n</template>"
    BAD_CONSUMER = '<template>\n  <input placeholder="c" />\n</template>'
    GOOD_PROVIDER = '<template>\n  <button data-testid="p-button">P</button>\n</template>'
    GOOD_CONSUMER = '<template>\n  <input data-testid="c-input" placeholder="c" />\n</template>'

    @staticmethod
    def _state(requirement: str) -> dict:
        return {
            "requirement": requirement,
            "component_lib": "",
            "messages": [],
            "analysis_result": "PRD",
            "design_result": "设计文档",
            "design_doc": "设计文档",
            # routing auth → L 档（角色含 debugger）
            "architecture_spec": {
                "spec_version": 1,
                "routing": [{"path": "/admin", "page": "Admin", "auth": True}],
            },
            "generated_files": {},
            "compile_errors": None,
            "manager_verdicts": [],
            "stage_phase": "generating",
            "context_summary": None,
            "planner_dag": None,
        }

    @pytest.mark.asyncio
    async def test_fix_round_respects_dep_order_and_passes(self):
        from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent

        from app.services.generation.graph import GraphRunner

        class ScriptedProvider:
            def __init__(self, turns):
                self.turns = list(turns)
                self.calls = 0
                self.user_prompts = []

            async def stream_generate(self, model, messages, config):
                # planner 走 _llm_generate（dict 消息），executor 走 Message 对象
                m = messages[1] if len(messages) > 1 else None
                self.user_prompts.append(
                    m.content if hasattr(m, "content") else (m.get("content", "") if m else "")
                )
                if self.calls >= len(self.turns):
                    yield TokenEvent(text="__TASK_DONE__", index=0)
                    yield CompleteEvent(finish_reason="stop", usage={})
                    return
                for ev in self.turns[self.calls]:
                    yield ev
                self.calls += 1

        def tool_turn(name, args, call_id="call_1"):
            return [ToolCallEvent(call_id=call_id, name=name, arguments=json.dumps(args)),
                    CompleteEvent(finish_reason="stop", usage={})]

        def text_turn(text):
            return [TokenEvent(text=text, index=0), CompleteEvent(finish_reason="stop", usage={})]

        turns = [
            text_turn(json.dumps(self.DAG)),  # planner
            tool_turn("write_code", {"path": "src/components/Provider.vue", "content": self.BAD_PROVIDER}, "c1"),
            text_turn("__TASK_DONE__"),
            tool_turn("write_code", {"path": "src/pages/Consumer.vue", "content": self.BAD_CONSUMER}, "c2"),
            text_turn("__TASK_DONE__"),
            # 修复轮：先 provider（consumer 依赖它）后 consumer
            tool_turn("write_code", {"path": "src/components/Provider.vue", "content": self.GOOD_PROVIDER}, "c3"),
            text_turn("__TASK_DONE__"),
            tool_turn("write_code", {"path": "src/pages/Consumer.vue", "content": self.GOOD_CONSUMER}, "c4"),
            text_turn("__TASK_DONE__"),
        ]
        provider = ScriptedProvider(turns)
        old = nodes._provider
        nodes._provider = provider
        try:
            state = self._state("图测依赖顺序fix")

            async def fake_diagnose(system_prompt, user_prompt):
                return ('{"root_cause": "缺 data-testid", '
                        '"fix_instructions": "给交互元素补 data-testid", '
                        '"affected_files": ["src/components/Provider.vue", "src/pages/Consumer.vue"]}')

            runner = GraphRunner(llm_fn=fake_diagnose)
            events = []
            async for ev in runner.run(state, "gen-fix-dep"):
                events.append(ev)
        finally:
            nodes._provider = old

        # 修复轮重派顺序：provider（无依赖）先于 consumer（依赖 provider）。
        # 从 prompt 的"需要生成的文件"段解析任务文件清单（consumer 的依赖
        # 摘要也会提到 Provider.vue，不能按文件名匹配）。
        fix_runs: list[tuple] = []
        for p in provider.user_prompts:
            if "Debugger 修复指令" not in p:
                continue
            m = re.search(r"## 需要生成的文件\n(\[.*?\])", p)
            files = tuple(json.loads(m.group(1))) if m else ()
            if not fix_runs or fix_runs[-1] != files:
                fix_runs.append(files)
        assert fix_runs == [
            ("src/components/Provider.vue",),
            ("src/pages/Consumer.vue",),
        ]

        # 事件链：verifier 先失败 → debugger 一轮 → 重新验证通过 → gate pass
        # （5.6 review I2: 修复后 L 档 Tester 运行，零测试产物（fake llm 的
        # fail-safe）也触发一次重新验证把 l4_pending 并入裁决 → 第 3 个事件。）
        verifier_events = [e for e in events if e["event_type"] == "verifier_result"]
        assert len(verifier_events) == 3
        assert verifier_events[0]["data"]["passed"] is False
        assert verifier_events[1]["data"]["passed"] is True
        assert verifier_events[2]["data"]["passed"] is True
        assert verifier_events[2]["data"]["l4_pending"] is True
        assert len([e for e in events if e["event_type"] == "debugger_diagnosis"]) == 1
        verdicts = [e for e in events if e["event_type"] == "manager_verdict"]
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert len(state["debugger_rounds"]) == 1
        assert state["verifier_result"]["passed"] is True

    @pytest.mark.asyncio
    async def test_fix_round_no_progress_breaks_and_gate_redoes(self):
        from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent

        from app.services.generation.graph import GraphRunner

        class ScriptedProvider:
            def __init__(self, turns):
                self.turns = list(turns)
                self.calls = 0

            async def stream_generate(self, model, messages, config):
                if self.calls >= len(self.turns):
                    yield TokenEvent(text="__TASK_DONE__", index=0)
                    yield CompleteEvent(finish_reason="stop", usage={})
                    return
                for ev in self.turns[self.calls]:
                    yield ev
                self.calls += 1

        def tool_turn(name, args, call_id="call_1"):
            return [ToolCallEvent(call_id=call_id, name=name, arguments=json.dumps(args)),
                    CompleteEvent(finish_reason="stop", usage={})]

        def text_turn(text):
            return [TokenEvent(text=text, index=0), CompleteEvent(finish_reason="stop", usage={})]

        turns = [
            text_turn(json.dumps(self.DAG)),
            tool_turn("write_code", {"path": "src/components/Provider.vue", "content": self.BAD_PROVIDER}, "c1"),
            text_turn("__TASK_DONE__"),
            tool_turn("write_code", {"path": "src/pages/Consumer.vue", "content": self.BAD_CONSUMER}, "c2"),
            text_turn("__TASK_DONE__"),
            # 修复轮重写同样的坏内容 → 证据不变 → 第 2 轮 no-progress
            tool_turn("write_code", {"path": "src/components/Provider.vue", "content": self.BAD_PROVIDER}, "c3"),
            text_turn("__TASK_DONE__"),
            tool_turn("write_code", {"path": "src/pages/Consumer.vue", "content": self.BAD_CONSUMER}, "c4"),
            text_turn("__TASK_DONE__"),
        ]
        provider = ScriptedProvider(turns)
        old = nodes._provider
        nodes._provider = provider
        try:
            state = self._state("图测无进展fix")

            async def fake_diagnose(system_prompt, user_prompt):
                return ('{"root_cause": "缺 data-testid", '
                        '"fix_instructions": "补 data-testid", '
                        '"affected_files": ["src/components/Provider.vue", "src/pages/Consumer.vue"]}')

            runner = GraphRunner(llm_fn=fake_diagnose)
            events = []
            async for ev in runner.run(state, "gen-fix-noprogress"):
                events.append(ev)
        finally:
            nodes._provider = old

        # 无进展熔断：只诊断一次，第 2 轮直接 debugger_stopped → gate redo
        assert len([e for e in events if e["event_type"] == "debugger_diagnosis"]) == 1
        stopped = [e for e in events if e["event_type"] == "debugger_stopped"]
        assert len(stopped) == 1
        assert "无进展" in stopped[0]["data"]["reason"]
        verdicts = [e for e in events if e["event_type"] == "manager_verdict"]
        assert verdicts[-1]["data"]["decision"] == "redo"
        assert "埋点钩子未通过" in verdicts[-1]["data"]["reason"]
        assert len(state["debugger_rounds"]) == 1
        assert state["verifier_result"]["passed"] is False


# ── 5.4 全链路: servicer ReportRuntimeFeedback → runner → registry ──


class TestRuntimeFeedbackServicer:
    @pytest.mark.asyncio
    async def test_report_runtime_feedback_stores_on_runner(self):
        from unittest.mock import MagicMock

        import grpc
        from ai.v1.generation_pb2 import RuntimeError, RuntimeFeedbackRequest

        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()
        registry = ToolRegistry(tempfile.mkdtemp())

        class FakeRunner:
            def __init__(self):
                self.calls = []

            def report_runtime_errors(self, errors):
                self.calls.append(list(errors))
                registry.report_runtime_errors(errors)
                return True

        runner = FakeRunner()
        servicer._active_runners["gen-runtime-1"] = runner
        context = MagicMock(spec=grpc.aio.ServicerContext)

        resp = await servicer.ReportRuntimeFeedback(
            RuntimeFeedbackRequest(
                generation_id="gen-runtime-1",
                errors=[
                    RuntimeError(type="console_error", message="Cannot read 'x'"),
                    RuntimeError(type="uncaught", message="boom", stack="at fn (a.vue:1)", url="src/App.vue"),
                ],
            ),
            context,
        )
        assert resp.received is True
        assert runner.calls == [[
            {"type": "console_error", "message": "Cannot read 'x'", "stack": "", "url": ""},
            {"type": "uncaught", "message": "boom", "stack": "at fn (a.vue:1)", "url": "src/App.vue"},
        ]]
        assert registry.get_runtime_errors()[1]["stack"] == "at fn (a.vue:1)"

    @pytest.mark.asyncio
    async def test_report_runtime_feedback_no_runner_returns_false(self):
        from unittest.mock import MagicMock

        import grpc
        from ai.v1.generation_pb2 import RuntimeFeedbackRequest

        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        resp = await servicer.ReportRuntimeFeedback(
            RuntimeFeedbackRequest(generation_id="missing-gen", errors=[]),
            context,
        )
        assert resp.received is False

    def test_graph_runner_reports_to_registry(self):
        import tempfile

        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        registry = ToolRegistry(tempfile.mkdtemp())
        runner._active_registry = registry
        assert runner.report_runtime_errors([{"type": "uncaught", "message": "boom"}]) is True
        assert registry.get_runtime_errors() == [{"type": "uncaught", "message": "boom"}]
        assert runner.report_runtime_errors([]) is True
        assert registry.get_runtime_errors() == []
        # 无活动 registry → 返回 False（与 compile feedback 一致）
        runner2 = GraphRunner(llm_fn=lambda *a: "")
        assert runner2.report_runtime_errors([{"type": "x", "message": "y"}]) is False
