"""Task group 5c (5.6) tests: L 档并行 Executor + Tester（单测/组件测试生成与执行）.

Covers:
- 5.6 Tester 生成: prompt 组装（Spec 关键段 + 文件清单）、结构化输出、垃圾
  fail-safe、落盘（含路径越界拒绝）。
- 5.6 Tester 执行: best-effort —— 环境禁用/无 node/无 vitest → 诚实的
  execution-pending；launcher 层 mock 的已执行路径；真实 vitest 往返
  （skipif 门控，环境具备时跑通）。
- 5.6 Verifier L4: 无测试产物 → True；已生成+已执行 → 按 passed；已生成+执行
  不可行 → True + l4_pending（文档化 deferral）；gate 消费 L4 失败。
- 5.6 并行 Executor（graph 驱动）: 无依赖任务并发（max_inflight ≥ 2）、依赖
  门控（consumer 等 provider 批次完成）、S/M 顺序路径无并发。
- 5.6 全链路: L 档 = 并行 + Tester（测试失败 → Debugger 修复轮 → 重测通过 →
  gate pass）；测试持续失败 → L4 无进展 → Manager 把关 redo。
"""

import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from app.services.generation import nodes, tester
from app.services.generation.debugger import build_diagnosis_prompt
from app.services.generation.manager import run_l1_checks
from app.services.generation.tools.registry import ToolRegistry
from app.services.generation.verifier import run_verifier
from app.services.llm.provider import CompleteEvent, TokenEvent, ToolCallEvent

from tests.test_implementation_tier import _spec as _spec_builder  # reuse the D5 spec builder


# ── helpers ──


def _tester_state(files: dict | None = None) -> dict:
    spec = _spec_builder(
        pages=[{"id": "p-01", "name": "登录页", "interactions": [], "data": []}],
        component_tree=[{"name": "LoginForm", "uses": [], "props": ["loading"]}],
    )
    return {
        "requirement": "测试工程",
        "architecture_spec": spec,
        "design_doc": "设计",
        "generated_files": files or {},
        "planner_dag": {"tasks": []},
        "context_summary": {"key_exports": {}, "completed_tasks": []},
    }


def _l_state(requirement: str) -> dict:
    """L 档 state（routing auth → 权限线索）—— 与 TestGraphFixRoundLoop 同构。"""
    return {
        "requirement": requirement,
        "component_lib": "",
        "messages": [],
        "analysis_result": "PRD",
        "design_result": "设计文档",
        "design_doc": "设计文档",
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


def _s_state(requirement: str) -> dict:
    """S 档 state —— 无权限/API 层/多模块线索（≤3 页面简单表单）。"""
    state = _l_state(requirement)
    state["architecture_spec"] = {
        "spec_version": 1,
        "pages": [
            {"id": "p-01", "name": "登录页", "interactions": [], "data": []},
        ],
        "directory_tree": {"src/": ["main.ts", "App.vue"]},
    }
    return state


class TaskAwareProvider:
    """Fake provider for graph-driven tests: 按调用者任务响应的并行感知 provider.

    - planner 调用（config 无 tools）→ 返回 DAG JSON（TokenEvent）。
    - executor 首轮调用（2 条消息）→ write_code 工具轮（写任务文件清单的首个
      文件，内容来自 ``files`` 映射）；后续轮次 → ``__TASK_DONE__``。
    记录并发度（max_inflight）与 enter/exit 时间线（带任务文件元组），供断言
    并行执行与依赖门控。
    """

    def __init__(self, dag: dict, files: dict[str, str]):
        self.dag = dag
        self.files = dict(files)
        self.max_inflight = 0
        self.inflight = 0
        self.timeline: list[tuple] = []  # ("enter"|"exit", tag, files_tuple)
        self._tag = 0

    @staticmethod
    def _task_files(text: str) -> list[str]:
        m = re.search(r"## 需要生成的文件\n(\[.*?\])", text)
        return json.loads(m.group(1)) if m else []

    async def stream_generate(self, model, messages, config):
        tag = self._tag
        self._tag += 1
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        m = messages[1] if len(messages) > 1 else None
        text = m.content if hasattr(m, "content") else (m.get("content", "") if m else "")
        try:
            if not getattr(config, "tools", None):
                # planner: 返回 DAG JSON
                self.timeline.append(("enter", tag, ("planner",)))
                yield TokenEvent(text=json.dumps(self.dag), index=0)
                yield CompleteEvent(finish_reason="stop", usage={})
                return
            files = tuple(self._task_files(text))
            self.timeline.append(("enter", tag, files))
            # 打开并发窗口 —— gather 下两个任务的 stream_generate 会交错
            await asyncio.sleep(0.05)
            if len(messages) == 2:
                # 首轮: 工具轮（写任务第一个文件）
                path = files[0]
                yield ToolCallEvent(
                    call_id=f"c{tag}", name="write_code",
                    arguments=json.dumps({"path": path, "content": self.files[path]}),
                )
                yield CompleteEvent(finish_reason="stop", usage={})
            else:
                yield TokenEvent(text="__TASK_DONE__", index=0)
                yield CompleteEvent(finish_reason="stop", usage={})
        finally:
            self.inflight -= 1
            self.timeline.append(("exit", tag, files if "files" in locals() else ("?",)))


class FakeGraphLLM:
    """Graph 级 llm_fn：Tester 返回测试 JSON，Debugger 返回诊断 JSON。

    以 system prompt 内容区分角色（tester / debugger / 其他 → tests 默认）。
    """

    def __init__(self, tests: list | None = None, diagnosis: dict | None = None):
        self.tests = tests if tests is not None else []
        self.diagnosis = diagnosis or {
            "root_cause": "测试失败：组件行为与测试断言不符",
            "fix_instructions": "按测试断言修正组件",
            "affected_files": [],
        }
        self.calls: list[str] = []

    async def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append(system_prompt)
        if "Debugger" in system_prompt:
            return json.dumps(self.diagnosis)
        return json.dumps({"tests": self.tests})


class FakeLauncher:
    """tester._launch_vitest 的替身 —— 脚本化每次执行的结果。"""

    def __init__(self, results: list[dict]):
        self.results = list(results)
        self.calls = 0

    async def __call__(self, project_root: str, node: str, vitest_mjs: str) -> dict:
        r = dict(self.results[min(self.calls, len(self.results) - 1)])
        self.calls += 1
        return r


class SimpleProc:
    """create_subprocess_exec 的假进程（M5 子进程路径测试用）。"""

    def __init__(self, rc: int = 0, stderr: bytes = b""):
        self.returncode = rc
        self.stderr = stderr
        self.killed = False

    async def communicate(self):
        return b"", self.stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.rc


FAILING_TESTS = [
    {
        "path": "src/__tests__/Button.spec.ts",
        "content": (
            "import { describe, it, expect } from 'vitest'\n"
            "describe('Button', () => {\n"
            "  it('has text', () => { expect(true).toBe(false) })\n"
            "})\n"
        ),
    },
]


# ── 5.6: Tester 生成 ──


class TestTesterGenerate:
    def test_prompt_contains_spec_and_file_list(self):
        state = _tester_state({"src/components/LoginForm.vue": "<template><div/></template>"})
        prompt = tester.build_tester_prompt(state)
        assert "### pages" in prompt
        assert "登录页" in prompt
        assert "### component_tree" in prompt
        assert "LoginForm" in prompt
        assert "src/components/LoginForm.vue" in prompt

    def test_prompt_skips_empty_spec_sections(self):
        spec = _spec_builder()
        spec.pop("api_contracts", None)  # 该 Spec 无 API 层
        state = _tester_state()
        state["architecture_spec"] = spec
        prompt = tester.build_tester_prompt(state)
        assert "### api_contracts" not in prompt
        assert "（空）" in prompt  # 无生成文件时的诚实占位

    @pytest.mark.asyncio
    async def test_generate_tests_structured(self):
        async def fake_llm(system_prompt, user_prompt):
            return json.dumps({"tests": [
                {"path": "src/__tests__/Login.spec.ts", "content": "import {} from 'vitest'"},
                {"path": "src/__tests__/Other.spec.ts", "content": "x"},
            ]})

        tests = await tester.generate_tests(_tester_state(), fake_llm)
        assert [t["path"] for t in tests] == [
            "src/__tests__/Login.spec.ts", "src/__tests__/Other.spec.ts",
        ]

    @pytest.mark.asyncio
    async def test_generate_tests_failsafe_on_garbage(self):
        async def fake_llm(system_prompt, user_prompt):
            return "这不是 JSON"

        assert await tester.generate_tests(_tester_state(), fake_llm) == []

    @pytest.mark.asyncio
    async def test_generate_tests_failsafe_on_llm_error(self):
        async def fake_llm(system_prompt, user_prompt):
            raise RuntimeError("provider down")

        assert await tester.generate_tests(_tester_state(), fake_llm) == []

    @pytest.mark.asyncio
    async def test_generate_tests_drops_empty_entries(self):
        async def fake_llm(system_prompt, user_prompt):
            return json.dumps({"tests": [
                {"path": "", "content": "x"},          # 无 path
                {"path": "a.spec.ts", "content": ""},  # 无 content
                {"path": "ok.spec.ts", "content": "y"},
            ]})

        tests = await tester.generate_tests(_tester_state(), fake_llm)
        assert tests == [{"path": "ok.spec.ts", "content": "y"}]

    def test_write_tests_writes_to_disk(self):
        project_root = tempfile.mkdtemp(prefix="ai-gen-tester-")
        written = tester.write_tests(project_root, [
            {"path": "src/__tests__/Login.spec.ts", "content": "it works"},
        ])
        assert written == [{"path": "src/__tests__/Login.spec.ts", "size": 8}]
        with open(os.path.join(project_root, "src/__tests__/Login.spec.ts"), encoding="utf-8") as f:
            assert f.read() == "it works"

    def test_write_tests_rejects_traversal_and_absolute(self):
        project_root = tempfile.mkdtemp(prefix="ai-gen-tester-")
        written = tester.write_tests(project_root, [
            {"path": "../evil.ts", "content": "x"},
            {"path": "/abs/evil.ts", "content": "y"},
            {"path": "src\\..\\evil.ts", "content": "z"},
            {"path": "good.spec.ts", "content": "ok"},
        ])
        assert written == [{"path": "good.spec.ts", "size": 2}]
        assert not os.path.exists(os.path.join(project_root, "evil.ts"))
        assert not os.path.exists("/abs/evil.ts")


# ── 5.6: Tester 执行（best-effort） ──


class TestTesterExecution:
    @pytest.mark.asyncio
    async def test_pending_when_env_disabled(self, monkeypatch):
        monkeypatch.setenv("AI_GEN_TEST_EXECUTION_DISABLED", "1")
        result = await tester.run_tests(tempfile.mkdtemp())
        assert result["executed"] is False
        assert result["passed"] is None
        assert "AI_GEN_TEST_EXECUTION_DISABLED" in result["reason"]

    @pytest.mark.asyncio
    async def test_pending_when_no_node(self, monkeypatch):
        monkeypatch.setattr(tester._shutil, "which", lambda name: None)
        result = await tester.run_tests(tempfile.mkdtemp())
        assert result["executed"] is False
        assert "node" in result["reason"]

    @pytest.mark.asyncio
    async def test_pending_when_no_vitest(self, monkeypatch):
        monkeypatch.setattr(tester, "_find_vitest_dir", lambda: None)
        result = await tester.run_tests(tempfile.mkdtemp())
        assert result["executed"] is False
        assert "vitest" in result["reason"]

    @pytest.mark.asyncio
    async def test_executes_via_launcher_and_writes_config(self, monkeypatch):
        fake_dir = Path(tempfile.mkdtemp(prefix="ai-gen-vitest-"))
        calls = []

        async def fake_launch(project_root, node, vitest_mjs):
            calls.append((project_root, node, vitest_mjs))
            return {"executed": True, "passed": True, "failures": [],
                    "reason": "vitest: 1 通过 / 0 失败"}

        monkeypatch.setattr(tester, "_find_vitest_dir", lambda: fake_dir)
        monkeypatch.setattr(tester, "_launch_vitest", fake_launch)
        project_root = tempfile.mkdtemp(prefix="ai-gen-tester-")
        result = await tester.run_tests(project_root)
        assert result["executed"] is True
        assert result["passed"] is True
        assert result["runner"] == str(fake_dir / "vitest" / "vitest.mjs")
        assert len(calls) == 1
        # 配置落盘（alias 指向 workspace vitest 实体文件）
        config = Path(project_root) / "vitest.config.ts"
        assert config.is_file()
        content = config.read_text(encoding="utf-8")
        assert "vitest/dist/config.js" in content
        assert "@vue/test-utils" in content

    @pytest.mark.asyncio
    async def test_launch_timeout_kills_process(self, monkeypatch):
        """5.6 review M5: vitest 执行超时 → 终止进程 + 诚实的 pending。"""
        from app.services.generation import tester as _tester_mod

        class HangingProc:
            def __init__(self):
                self.killed = False

            async def communicate(self):
                await asyncio.sleep(3600)  # 永不返回 → wait_for 超时

            def kill(self):
                self.killed = True

            async def wait(self):
                return 0

        proc = HangingProc()

        async def fake_exec(*args, **kwargs):
            return proc

        monkeypatch.setattr(_tester_mod._asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(_tester_mod, "VITEST_TIMEOUT_S", 0.05)
        result = await _tester_mod._launch_vitest(
            tempfile.mkdtemp(), "node", "vitest.mjs"
        )
        assert result["executed"] is False
        assert "超时" in result["reason"]
        assert proc.killed is True

    @pytest.mark.asyncio
    async def test_launch_unparseable_report(self, monkeypatch):
        """报告文件存在但内容不可解析 → 诚实的 pending（不伪造结论）。"""
        from app.services.generation import tester as _tester_mod

        async def fake_exec(*args, **kwargs):
            out = args[args.index("--outputFile") + 1]
            with open(out, "w", encoding="utf-8") as f:
                f.write("not json {{{")
            return SimpleProc(rc=0)

        monkeypatch.setattr(_tester_mod._asyncio, "create_subprocess_exec", fake_exec)
        result = await _tester_mod._launch_vitest(
            tempfile.mkdtemp(), "node", "vitest.mjs"
        )
        assert result["executed"] is False
        assert "未产出可解析报告" in result["reason"]

    @pytest.mark.asyncio
    async def test_launch_missing_report_surfaces_stderr(self, monkeypatch):
        """报告未产出（如 "No test files found" 提前退出）→ stderr 细节进 reason。"""
        from app.services.generation import tester as _tester_mod

        async def fake_exec(*args, **kwargs):
            return SimpleProc(rc=1, stderr=b"No test files found, exiting with code 1")

        monkeypatch.setattr(_tester_mod._asyncio, "create_subprocess_exec", fake_exec)
        result = await _tester_mod._launch_vitest(
            tempfile.mkdtemp(), "node", "vitest.mjs"
        )
        assert result["executed"] is False
        assert "No test files found" in result["reason"]

    @pytest.mark.asyncio
    async def test_launch_cleans_up_result_file(self, monkeypatch):
        """M3a: 每次运行的 vitest-result 落到临时路径并在解析后清理。"""
        from app.services.generation import tester as _tester_mod

        written_paths = []

        async def fake_exec(*args, **kwargs):
            out = args[args.index("--outputFile") + 1]
            written_paths.append(out)
            with open(out, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "success": True, "numPassedTests": 1, "numFailedTests": 0,
                    "testResults": [{"name": "a.spec.ts", "status": "passed",
                                     "assertionResults": []}],
                }))
            return SimpleProc(rc=0)

        monkeypatch.setattr(_tester_mod._asyncio, "create_subprocess_exec", fake_exec)
        result = await _tester_mod._launch_vitest(
            tempfile.mkdtemp(), "node", "vitest.mjs"
        )
        assert result["executed"] is True
        assert result["passed"] is True
        # 唯一临时路径 + 已清理（不残留携带 failureMessages 的报告）
        assert len(written_paths) == 1
        assert "ai-gen-vitest-" in written_paths[0]
        assert not os.path.exists(written_paths[0])

    @pytest.mark.asyncio
    async def test_parse_report_empty_testresults_surfaces_message(self):
        """5.6 review M3b: testResults 为空时顶层 message 进 failures。"""
        report = {"success": False, "message": "No test files found", "testResults": []}
        passed, failures, _ = tester._parse_vitest_report(report)
        assert passed is False
        assert len(failures) == 1
        assert "No test files found" in failures[0]["message"]

    @pytest.mark.asyncio
    async def test_parse_report_assertion_failures(self):
        report = {
            "success": False, "numPassedTests": 1, "numFailedTests": 1,
            "testResults": [{
                "name": "src/__tests__/B.spec.ts",
                "assertionResults": [
                    {"fullName": "B fails", "status": "failed",
                     "failureMessages": ["expected 2 to be 3"]},
                    {"fullName": "B passes", "status": "passed", "failureMessages": []},
                ],
            }],
        }
        passed, failures, summary = tester._parse_vitest_report(report)
        assert passed is False
        assert failures[0]["file"] == "B fails"
        assert "expected 2 to be 3" in failures[0]["message"]
        assert "1 失败" in summary

    @pytest.mark.asyncio
    async def test_parse_report_file_level_resolution_failure(self):
        """import 解析失败时 assertionResults 为空 —— 从 suite message 收集。"""
        report = {
            "success": False,
            "testResults": [{
                "name": "src/__tests__/C.spec.ts",
                "status": "failed",
                "message": "Failed to resolve import \"element-plus\"",
                "assertionResults": [],
            }],
        }
        passed, failures, _ = tester._parse_vitest_report(report)
        assert passed is False
        assert len(failures) == 1
        assert "element-plus" in failures[0]["message"]

    @pytest.mark.asyncio
    async def test_run_tester_zero_tests_flow(self, monkeypatch):
        monkeypatch.setenv("AI_GEN_TEST_EXECUTION_DISABLED", "1")
        async def fake_llm(system_prompt, user_prompt):
            return json.dumps({"tests": []})

        project_root = tempfile.mkdtemp(prefix="ai-gen-tester-")
        result = await tester.run_tester(_tester_state(), project_root, fake_llm)
        assert result["generated"] == []
        assert result["executed"] is False
        assert "未生成测试" in result["reason"]

    @pytest.mark.asyncio
    async def test_run_tester_generate_write_pending(self, monkeypatch):
        """生成成功 → 落盘 → 执行被禁用 → 诚实的 execution-pending。"""
        monkeypatch.setenv("AI_GEN_TEST_EXECUTION_DISABLED", "1")

        async def fake_llm(system_prompt, user_prompt):
            return json.dumps({"tests": FAILING_TESTS})

        project_root = tempfile.mkdtemp(prefix="ai-gen-tester-")
        result = await tester.run_tester(_tester_state(), project_root, fake_llm)
        assert result["generated"] == [
            {"path": "src/__tests__/Button.spec.ts", "size": len(FAILING_TESTS[0]["content"])}
        ]
        assert result["executed"] is False
        assert result["passed"] is None
        assert "deferral" in result["reason"]
        # 测试文件确实落盘
        assert (Path(project_root) / "src/__tests__/Button.spec.ts").is_file()

    @pytest.mark.asyncio
    async def test_run_tester_executed_pass_flow(self, monkeypatch):
        async def fake_llm(system_prompt, user_prompt):
            return json.dumps({"tests": FAILING_TESTS})

        monkeypatch.setattr(tester, "_find_vitest_dir", lambda: Path(tempfile.mkdtemp()))
        monkeypatch.setattr(tester, "_launch_vitest", FakeLauncher([
            {"executed": True, "passed": True, "failures": [], "reason": "vitest: 1 通过 / 0 失败"},
        ]))
        result = await tester.run_tester(_tester_state(), tempfile.mkdtemp(), fake_llm)
        assert result["executed"] is True
        assert result["passed"] is True
        assert result["failures"] == []

    @pytest.mark.asyncio
    async def test_run_tester_executed_fail_flow(self, monkeypatch):
        async def fake_llm(system_prompt, user_prompt):
            return json.dumps({"tests": FAILING_TESTS})

        monkeypatch.setattr(tester, "_find_vitest_dir", lambda: Path(tempfile.mkdtemp()))
        monkeypatch.setattr(tester, "_launch_vitest", FakeLauncher([
            {"executed": True, "passed": False, "failures": [
                {"file": "Button has text", "message": "expected true to be false"},
            ], "reason": "vitest: 0 通过 / 1 失败"},
        ]))
        result = await tester.run_tester(_tester_state(), tempfile.mkdtemp(), fake_llm)
        assert result["executed"] is True
        assert result["passed"] is False
        assert result["failures"][0]["file"] == "Button has text"

    @pytest.mark.skipif(
        not (shutil.which("node") and tester._find_vitest_dir())
        or bool(os.environ.get("AI_GEN_TEST_EXECUTION_DISABLED")),
        reason="node/vitest 不可用或执行被禁用（AI_GEN_TEST_EXECUTION_DISABLED=1）",
    )
    @pytest.mark.asyncio
    async def test_vitest_real_execution_roundtrip(self):
        """端到端真实执行：workspace vitest 跑通生成的测试（pass）。"""
        project_root = tempfile.mkdtemp(prefix="ai-gen-tester-e2e-")
        try:
            tests = [
                {
                    "path": "src/__tests__/MyButton.spec.ts",
                    "content": (
                        "import { describe, it, expect } from 'vitest'\n"
                        "import { mount } from '@vue/test-utils'\n"
                        "import MyButton from '../components/MyButton.vue'\n"
                        "describe('MyButton', () => {\n"
                        "  it('mounts and shows label', () => {\n"
                        "    const w = mount(MyButton, { props: { label: '保存' } })\n"
                        "    expect(w.get('[data-testid=\\'my-button\\']').text()).toBe('保存')\n"
                        "  })\n"
                        "  it('emits clicked', async () => {\n"
                        "    const w = mount(MyButton, { props: { label: '保存' } })\n"
                        "    await w.get('[data-testid=\\'my-button\\']').trigger('click')\n"
                        "    expect(w.emitted('clicked')).toHaveLength(1)\n"
                        "  })\n"
                        "})\n"
                    ),
                },
            ]
            assert tester.write_tests(project_root, tests)
            component_dir = os.path.join(project_root, "src", "components")
            os.makedirs(component_dir, exist_ok=True)
            with open(os.path.join(component_dir, "MyButton.vue"), "w", encoding="utf-8") as f:
                f.write(
                    "<template>\n"
                    '  <button data-testid="my-button" @click="$emit(\'clicked\')">{{ label }}</button>\n'
                    "</template>\n"
                    "<script setup lang=\"ts\">\n"
                    "defineProps<{ label: string }>()\n"
                    "defineEmits<{ (e: 'clicked'): void }>()\n"
                    "</script>\n"
                )
            result = await tester.run_tests(project_root)
            assert result["executed"] is True
            assert result["passed"] is True
            assert result["failures"] == []
            # 报告文件不进生成项目根目录（M3a：临时路径 + 清理）
            assert not os.path.exists(os.path.join(project_root, "vitest-result.json"))
        finally:
            shutil.rmtree(project_root, ignore_errors=True)


# ── 5.6: Verifier L4 行为层 ──


def _verifier_state(files: dict, tester_result=None) -> dict:
    state = {
        "requirement": "测试工程",
        "design_doc": "设计方案",
        "architecture_spec": {"pages": [], "directory_tree": {}},
        "generated_files": files,
        "code_result": json.dumps(files, ensure_ascii=False),
        "compile_errors": None,
        "planner_dag": {"tasks": []},
        "context_summary": {"key_exports": {}, "completed_tasks": []},
    }
    if tester_result is not None:
        state["tester_result"] = tester_result
    return state


class TestVerifierL4:
    FILES = {"src/App.vue": "<template><div>hi</div></template>"}

    @pytest.mark.asyncio
    async def test_l4_true_without_tester_result(self):
        state = _verifier_state(self.FILES)
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="L")
        assert result["l4_ok"] is True
        assert result["l4_pending"] is False
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_l4_executed_passed(self):
        state = _verifier_state(self.FILES, tester_result={
            "generated": [{"path": "src/__tests__/A.spec.ts", "size": 5}],
            "executed": True, "passed": True, "failures": [],
            "reason": "vitest: 1 通过 / 0 失败", "runner": "x",
        })
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="L")
        assert result["l4_ok"] is True
        assert result["l4_pending"] is False
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_l4_executed_failed(self):
        state = _verifier_state(self.FILES, tester_result={
            "generated": [{"path": "src/__tests__/A.spec.ts", "size": 5}],
            "executed": True, "passed": False,
            "failures": [{"file": "A has text", "message": "expected true to be false"}],
            "reason": "vitest: 0 通过 / 1 失败", "runner": "x",
        })
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="L")
        assert result["l4_ok"] is False
        assert result["passed"] is False
        assert result["evidence"]["test_failures"] == [
            {"file": "A has text", "message": "expected true to be false"},
        ]

    @pytest.mark.asyncio
    async def test_l4_execution_pending_is_not_a_fake_pass_or_fail(self):
        """生成了测试但执行不可行（deferral）→ l4_ok True + l4_pending True。"""
        state = _verifier_state(self.FILES, tester_result={
            "generated": [{"path": "src/__tests__/A.spec.ts", "size": 5}],
            "executed": False, "passed": None, "failures": [],
            "reason": "环境无 node 可执行文件 —— 测试执行不可行（文档化 deferral）",
            "runner": None,
        })
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="L")
        assert result["l4_ok"] is True
        assert result["l4_pending"] is True
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_l4_zero_generated_is_deferred_on_l_tier(self):
        """5.6 review I2: L 档 Tester 已运行但零测试产物 → l4_pending True
        （行为层无证据，不假装"无测试预期"地静默通过）。"""
        state = _verifier_state(self.FILES, tester_result={
            "generated": [], "executed": False, "passed": None, "failures": [],
            "reason": "未生成测试（LLM 输出为空或解析失败，fail-safe）", "runner": None,
        })
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="L")
        assert result["l4_ok"] is True
        assert result["l4_pending"] is True
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_l4_zero_generated_non_l_tier_not_pending(self):
        """非 L 档（无 Tester 角色）的空 tester_result 不产生 pending（未知）。"""
        state = _verifier_state(self.FILES, tester_result={
            "generated": [], "executed": False, "passed": None, "failures": [],
            "reason": "未生成测试", "runner": None,
        })
        registry = ToolRegistry(tempfile.mkdtemp())
        result = await run_verifier(state, registry, tier="M")
        assert result["l4_ok"] is True
        assert result["l4_pending"] is False

    def test_gate_surfaces_l4_failure(self):
        from app.services.generation.manager import _output_signature

        base = _verifier_state(self.FILES)
        state = dict(base)
        state["verifier_result"] = {
            "l1_ok": True, "l2_ok": True, "l3_ok": True, "l4_ok": False,
            "hooks_ok": True, "passed": False,
            "evidence": {
                "compile_errors": [], "contract_violations": [],
                "runtime_errors": [], "test_failures": [{"file": "A", "message": "x"}],
                "hook_violations": [],
            },
            "output_signature": _output_signature(base, "code"),
        }
        errors = run_l1_checks(state, "code")
        assert any("L4 行为未通过" in e for e in errors)

    @pytest.mark.asyncio
    async def test_gate_pass_reason_carries_l4_pending_note(self):
        """5.6 review I1: l4_pending 时 pass 裁决的理由带**非失败**说明 ——
        不触发 redo，但对用户可见（verdict reason）。"""
        from app.services.generation.manager import (
            L4_PENDING_NOTE,
            _output_signature,
            evaluate_stage_l2,
        )

        base = _verifier_state(self.FILES)
        state = dict(base)
        state["verifier_result"] = {
            "l1_ok": True, "l2_ok": True, "l3_ok": True, "l4_ok": True,
            "l4_pending": True, "hooks_ok": True, "passed": True,
            "evidence": {
                "compile_errors": [], "contract_violations": [],
                "runtime_errors": [], "test_failures": [], "hook_violations": [],
            },
            "output_signature": _output_signature(base, "code"),
        }
        decision, reason, evidence, missing = await evaluate_stage_l2(state, "code")
        assert decision == "pass"
        assert reason == L4_PENDING_NOTE
        assert "deferral" in reason
        assert evidence == [] and missing == []

    @pytest.mark.asyncio
    async def test_gate_pass_reason_empty_without_pending(self):
        from app.services.generation.manager import evaluate_stage_l2

        base = _verifier_state(self.FILES)
        state = dict(base)
        state["verifier_result"] = {
            "l1_ok": True, "l2_ok": True, "l3_ok": True, "l4_ok": True,
            "l4_pending": False, "hooks_ok": True, "passed": True,
            "evidence": {
                "compile_errors": [], "contract_violations": [],
                "runtime_errors": [], "test_failures": [], "hook_violations": [],
            },
        }
        decision, reason, _, _ = await evaluate_stage_l2(state, "code")
        assert decision == "pass"
        assert reason == ""

    def test_gate_legacy_verdict_without_l4_key_does_not_block(self):
        """旧格式 verdict（无 l4_ok 键）不阻止把关 —— 与无签名 verdict 兼容哲学一致。"""
        from app.services.generation.manager import _output_signature

        base = _verifier_state(self.FILES)
        state = dict(base)
        state["verifier_result"] = {
            "l1_ok": True, "l2_ok": True, "l3_ok": True, "hooks_ok": True,
            "passed": True,
            "evidence": {"compile_errors": [], "contract_violations": [],
                         "runtime_errors": [], "hook_violations": []},
            "output_signature": _output_signature(base, "code"),
        }
        assert run_l1_checks(state, "code") == []

    def test_diagnosis_prompt_includes_test_failures(self):
        state = _tester_state()
        prompt = build_diagnosis_prompt(state, {
            "compile_errors": [], "contract_violations": [], "runtime_errors": [],
            "test_failures": [{"file": "Button has text", "message": "expected true to be false"}],
            "hook_violations": [],
        })
        assert "测试失败" in prompt
        assert "expected true to be false" in prompt


# ── 5.6: 并行 Executor（graph 驱动） ──


GOOD_BUTTON = '<template>\n  <button data-testid="btn">B</button>\n</template>\n<script setup lang="ts">\n</script>'
GOOD_LIST = '<template>\n  <input data-testid="search-input" />\n</template>\n<script setup lang="ts">\n</script>'


def _two_task_dag():
    return {
        "reasoning": "parallel test",
        "tasks": [
            {"id": "task-0", "type": "business", "description": "按钮组件",
             "deps": [], "files": ["src/components/Button.vue"], "contract": {}, "status": "pending"},
            {"id": "task-1", "type": "business", "description": "列表页",
             "deps": [], "files": ["src/pages/List.vue"], "contract": {}, "status": "pending"},
        ],
    }


def _gated_dag():
    return {
        "reasoning": "gating test",
        "tasks": [
            # 消费者在列表最前 —— 依赖门必须等 provider 批次完成
            {"id": "task-1", "type": "business", "description": "消费者页面",
             "deps": ["task-0"], "files": ["src/pages/Consumer.vue"], "contract": {}, "status": "pending"},
            {"id": "task-0", "type": "business", "description": "提供者组件",
             "deps": [], "files": ["src/components/Provider.vue"], "contract": {}, "status": "pending"},
            {"id": "task-2", "type": "business", "description": "独立列表页",
             "deps": [], "files": ["src/pages/List.vue"], "contract": {}, "status": "pending"},
        ],
    }


class TestParallelExecutors:
    @pytest.mark.asyncio
    async def test_two_independent_tasks_run_concurrently(self, monkeypatch):
        """L 档: 无依赖任务并行 —— max_inflight ≥ 2（批次 gather）。"""
        from app.services.generation.graph import GraphRunner

        provider = TaskAwareProvider(_two_task_dag(), {
            "src/components/Button.vue": GOOD_BUTTON,
            "src/pages/List.vue": GOOD_LIST,
        })
        old = nodes._provider
        nodes._provider = provider
        runner = GraphRunner(llm_fn=FakeGraphLLM(tests=[]))
        try:
            state = _l_state("并测双任务并发")
            events = []
            async for ev in runner.run(state, "gen-parallel-2"):
                events.append(ev)
        finally:
            nodes._provider = old

        # 两个 executor 的 stream_generate 确实并发进入
        assert provider.max_inflight >= 2
        # 两个文件都生成
        assert "src/components/Button.vue" in state["generated_files"]
        assert "src/pages/List.vue" in state["generated_files"]
        # registry 缓存最终一致（并行合并纪律：不丢同批写入）
        cache = runner._active_registry.get_generated_files()
        assert "src/components/Button.vue" in cache
        assert "src/pages/List.vue" in cache
        # 验证通过 → gate pass（L 档角色含 tester → tester_result 事件发射）
        verifier_events = [e for e in events if e["event_type"] == "verifier_result"]
        # I2: 零测试产物也要重新验证（l4_pending 并入裁决）→ 两次 verifier 事件
        assert len(verifier_events) == 2
        assert verifier_events[-1]["data"]["passed"] is True
        assert verifier_events[-1]["data"]["l4_pending"] is True
        tester_events = [e for e in events if e["event_type"] == "tester_result"]
        assert len(tester_events) == 1
        assert tester_events[0]["data"]["generated"] == []  # fake llm 零测试
        # I1: 零测试产物的 deferral 对前端可见 —— code_gen_done 带 l4_pending，
        # gate pass 裁决的理由带非失败说明。
        gen_done = [e for e in events if e["event_type"] == "code_gen_done"]
        assert gen_done[-1]["data"]["l4_pending"] is True
        verdicts = [e for e in events if e["event_type"] == "manager_verdict"]
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert "L4 行为未执行" in verdicts[-1]["data"]["reason"]

    @pytest.mark.asyncio
    async def test_consumer_waits_for_provider_batch(self, monkeypatch):
        """并行模式依赖门控: consumer 在 provider 批次完成后才启动。"""
        from app.services.generation.graph import GraphRunner

        provider = TaskAwareProvider(_gated_dag(), {
            "src/components/Provider.vue": GOOD_BUTTON,
            "src/pages/Consumer.vue": GOOD_LIST,
            "src/pages/List.vue": GOOD_LIST,
        })
        old = nodes._provider
        nodes._provider = provider
        try:
            state = _l_state("并测依赖门控")
            runner = GraphRunner(llm_fn=FakeGraphLLM(tests=[]))
            async for _ev in runner.run(state, "gen-parallel-gated"):
                pass
        finally:
            nodes._provider = old

        # 批次 1 = [task-0, task-2] 并发；consumer 的 enter 必须在 provider 的
        # 最后一次 exit 之后（严格批次，不是同批）。
        def _hits(tag: str, path: str) -> list[int]:
            return [i for i, e in enumerate(provider.timeline)
                    if e[0] == tag and any(path in f for f in e[2])]

        provider_enters = _hits("enter", "Provider.vue")
        provider_exits = _hits("exit", "Provider.vue")
        consumer_enters = _hits("enter", "Consumer.vue")
        assert provider_enters and provider_exits and consumer_enters
        assert consumer_enters[0] > provider_exits[-1]
        # 批次内仍有并发（task-0 与 task-2）
        assert provider.max_inflight >= 2
        # 三个文件全部生成
        for f in ("src/components/Provider.vue", "src/pages/Consumer.vue", "src/pages/List.vue"):
            assert f in state["generated_files"]
        assert state["verifier_result"]["passed"] is True

    @pytest.mark.asyncio
    async def test_s_tier_sequential_no_overlap(self, monkeypatch):
        """S 档: 顺序执行 —— 无任何并发（max_inflight == 1），行为与旧循环一致。"""
        from app.services.generation.graph import GraphRunner

        provider = TaskAwareProvider(_two_task_dag(), {
            "src/components/Button.vue": GOOD_BUTTON,
            "src/pages/List.vue": GOOD_LIST,
        })
        old = nodes._provider
        nodes._provider = provider
        try:
            state = _s_state("顺序档双任务")
            runner = GraphRunner(llm_fn=FakeGraphLLM(tests=[]))
            events = []
            async for ev in runner.run(state, "gen-sequential-s"):
                events.append(ev)
        finally:
            nodes._provider = old

        assert provider.max_inflight == 1
        assert state["verifier_result"]["passed"] is True
        # S 档角色无 tester → 无 tester_result 事件
        assert not any(e["event_type"] == "tester_result" for e in events)


# ── 5.6: 全链路（并行 + Tester + Debugger + gate） ──


class TestFullLLoop:
    @pytest.mark.asyncio
    async def test_tester_failure_debugger_fix_retest_pass(self, monkeypatch):
        """L 档全链路: 并行生成 → L1-L3 通过 → Tester 测试失败（L4）→
        Debugger 修复轮 → 重测通过 → gate pass。"""
        from app.services.generation.graph import GraphRunner

        provider = TaskAwareProvider(_two_task_dag(), {
            "src/components/Button.vue": GOOD_BUTTON,
            "src/pages/List.vue": GOOD_LIST,
        })
        launcher = FakeLauncher([
            # 首测失败（L4 证据）→ Debugger 修复轮 → 重测通过
            {"executed": True, "passed": False, "failures": [
                {"file": "Button has text", "message": "expected true to be false"},
            ], "reason": "vitest: 0 通过 / 1 失败"},
            {"executed": True, "passed": True, "failures": [], "reason": "vitest: 1 通过 / 0 失败"},
        ])
        fake_llm = FakeGraphLLM(tests=FAILING_TESTS, diagnosis={
            "root_cause": "测试断言与组件行为不符",
            "fix_instructions": "修正组件行为以匹配测试",
            "affected_files": ["src/components/Button.vue", "src/pages/List.vue"],
        })
        monkeypatch.setattr(tester, "_find_vitest_dir", lambda: Path(tempfile.mkdtemp()))
        monkeypatch.setattr(tester, "_launch_vitest", launcher)

        old = nodes._provider
        nodes._provider = provider
        try:
            state = _l_state("全链测试修复")
            runner = GraphRunner(llm_fn=fake_llm)
            events = []
            async for ev in runner.run(state, "gen-full-loop"):
                events.append(ev)
        finally:
            nodes._provider = old

        # 并行执行成立
        assert provider.max_inflight >= 2
        # 事件链: verifier 通过(L1-L3) → tester 失败 → L4 验证失败 → debugger
        # 修复轮（重测）→ L4 验证通过
        verifier_events = [e for e in events if e["event_type"] == "verifier_result"]
        assert [e["data"]["passed"] for e in verifier_events] == [True, False, True]
        tester_events = [e for e in events if e["event_type"] == "tester_result"]
        assert len(tester_events) == 2
        assert [t["data"]["passed"] for t in tester_events] == [False, True]
        assert [t["data"]["executed"] for t in tester_events] == [True, True]
        # 修复轮诊断一次 + 执行两次（首测 + 重测）
        assert len([e for e in events if e["event_type"] == "debugger_diagnosis"]) == 1
        assert launcher.calls == 2
        # 修复轮重派了受影响任务：Button.vue 任务的 executor 每轮 2 次 provider
        # 调用（write 轮 + done 轮），首轮 + 修复轮 = 4 次 enter。
        button_enters = [e for e in provider.timeline
                         if e[0] == "enter" and any("Button.vue" in f for f in e[2])]
        assert len(button_enters) == 4
        # gate pass + 状态一致
        verdicts = [e for e in events if e["event_type"] == "manager_verdict"]
        assert verdicts[-1]["data"]["decision"] == "pass"
        assert state["verifier_result"]["passed"] is True
        assert state["tester_result"]["passed"] is True
        assert len(state["debugger_rounds"]) == 1

    @pytest.mark.asyncio
    async def test_tester_failure_no_progress_escalates_to_gate(self, monkeypatch):
        """测试持续失败: 修复轮后重测仍失败 → L4 证据未变 → 无进展熔断 →
        Manager 把关 redo（带 L4 证据）。"""
        from app.services.generation.graph import GraphRunner

        provider = TaskAwareProvider(_two_task_dag(), {
            "src/components/Button.vue": GOOD_BUTTON,
            "src/pages/List.vue": GOOD_LIST,
        })
        launcher = FakeLauncher([
            {"executed": True, "passed": False, "failures": [
                {"file": "Button has text", "message": "expected true to be false"},
            ], "reason": "vitest: 0 通过 / 1 失败"},
        ])
        fake_llm = FakeGraphLLM(tests=FAILING_TESTS, diagnosis={
            "root_cause": "测试断言与组件行为不符",
            "fix_instructions": "修正组件行为以匹配测试",
            "affected_files": ["src/components/Button.vue", "src/pages/List.vue"],
        })
        monkeypatch.setattr(tester, "_find_vitest_dir", lambda: Path(tempfile.mkdtemp()))
        monkeypatch.setattr(tester, "_launch_vitest", launcher)

        old = nodes._provider
        nodes._provider = provider
        try:
            state = _l_state("全链测试无进展")
            runner = GraphRunner(llm_fn=fake_llm)
            events = []
            async for ev in runner.run(state, "gen-full-noprogress"):
                events.append(ev)
        finally:
            nodes._provider = old

        verifier_events = [e for e in events if e["event_type"] == "verifier_result"]
        # 通过(L1-L3) → L4 失败 → 修复轮重测仍失败 → L4 失败
        assert [e["data"]["passed"] for e in verifier_events] == [True, False, False]
        # 只诊断一次，第 2 轮无进展熔断
        assert len([e for e in events if e["event_type"] == "debugger_diagnosis"]) == 1
        stopped = [e for e in events if e["event_type"] == "debugger_stopped"]
        assert len(stopped) == 1
        assert "无进展" in stopped[0]["data"]["reason"]
        # gate redo（L4 证据进 diagnosis）
        verdicts = [e for e in events if e["event_type"] == "manager_verdict"]
        assert verdicts[-1]["data"]["decision"] == "redo"
        assert "L4 行为未通过" in verdicts[-1]["data"]["reason"]
        assert state["verifier_result"]["passed"] is False
        assert len(state["debugger_rounds"]) == 1
