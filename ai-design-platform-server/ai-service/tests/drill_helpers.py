"""Task 11 shared drill helpers — scripted LLM provider + canned fixtures.

The 11.2-11.5 drills drive the REAL orchestration (GraphRunner / brainstorm
engine / memory / incremental) with scripted providers — no real LLM, no
network. A single ``ScriptedFlowProvider`` installed as ``nodes._provider``
serves every LLM call of a run:

- Prompt-marker dispatch: each distinct system prompt registers an ordered
  queue of event-lists (PRD / design MD / spec / L2 gate / planner / designer /
  manifest / tester / classification).
- Executor rounds use the message-count heuristic (2 messages = first round →
  ``write_code`` tool call writing the task's first file from ``files``; more
  messages = subsequent round → ``__TASK_DONE__``), mirroring
  ``test_tester_parallel.TaskAwareProvider``. Mutating ``provider.files[path]``
  between runs simulates a Debugger fix.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

from app.services.generation.tools.registry import ToolRegistry, ToolResult

# ── Prompt markers (system-prompt substrings for dispatch) ──

MARK_PRD = "根据用户的原始需求与头脑风暴澄清产物"
MARK_DESIGN_MD = "根据需求分析文档，输出详细设计方案"
MARK_SPEC = "机器可读的架构 Spec（JSON）"
MARK_L2 = "核对架构 Spec 对 PRD 功能点的覆盖情况"
MARK_PLANNER = "将架构 Spec 拆解为可独立执行的任务"
MARK_EXECUTOR = "负责完成一个具体的代码生成任务"
MARK_DESIGNER = "你是一个资深 QA 测试工程师（Test Designer）"
MARK_MANIFEST = "你是增量开发架构师"
MARK_TESTER = "为 AI 生成的前端工程编写验收先行"
MARK_CLASSIFY = "对流程中的失败进行分类"

# ── Canned outputs ──

PRD_OK = (
    "# 需求规格文档\n\n"
    "## 1. 功能概述\n后台管理系统，目标用户为管理员，核心问题是缺乏统一管理后台。\n"
    "## 2. 功能模块\n- 用户管理（必须有）：用户的增删改查\n"
    "- 订单管理（必须有）：订单列表与状态流转\n"
    "## 3. 页面结构\n- 用户列表页（list）\n- 订单列表页（list）\n"
    "## 4. 数据模型\n- User: id/name/role\n- Order: id/status\n"
    "## 5. 交互行为\n- 用户列表支持分页与搜索\n"
)

DESIGN_MD = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"

# S/M 档 Spec — 无 auth (避免 L 档 Tester 噪音), 页面 ≤3, 无 store 声明。
SPEC_SM = {
    "spec_version": 1,
    "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "vite", "style": "scss"},
    "directory_tree": {"src/": ["main.ts", "App.vue", "pages/", "components/"]},
    "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
    "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
    "routing": [{"path": "/", "page": "Home", "auth": False}],
    "state_management": {"store": "pinia", "stores": []},
    "component_tree": [{"name": "Header", "uses": [], "props": []}],
    "pages": [{"id": "p-01", "name": "首页", "interactions": [], "data": []}],
    "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
}

# L 档 Spec — routing auth → L (角色含 debugger/tester, 触发恢复阶梯)。
SPEC_L = {
    **SPEC_SM,
    "routing": [{"path": "/", "page": "Home", "auth": False},
                {"path": "/admin", "page": "Admin", "auth": True}],
}

L2_PASS = '{"passed": true, "missing": []}'
L2_FAIL_ORDER = json.dumps({"passed": False, "missing": [
    {"feature": "订单管理", "evidence": "PRD 声明，Spec pages 无对应页面"},
]}, ensure_ascii=False)

DAG_TWO = json.dumps({"reasoning": "由 Spec 拆解", "tasks": [
    {"id": "task-0", "type": "business", "description": "入口组件与首页",
     "deps": [], "files": ["src/App.vue"], "contract": {}, "status": "pending"},
    {"id": "task-1", "type": "business", "description": "用户列表页面",
     "deps": ["task-0"], "files": ["src/pages/Home.vue"], "contract": {}, "status": "pending"},
]}, ensure_ascii=False)

DAG_ONE = json.dumps({"reasoning": "由 Spec 拆解", "tasks": [
    {"id": "task-0", "type": "business", "description": "入口组件",
     "deps": [], "files": ["src/App.vue"], "contract": {}, "status": "pending"},
]}, ensure_ascii=False)

FILE_APP = "<template><div data-testid=\"app-root\">hello</div></template>\n"
FILE_HOME = (
    "<template>\n  <button data-testid=\"save-button\">保存</button>\n"
    "  <input data-testid=\"search-input\" placeholder=\"搜索\" />\n</template>\n"
)
# 编译错误注入目标: 内容含 BAD 标记 → FailingCompileRegistry 判定编译失败。
FILE_APP_BAD = "<template>\n  <div>BAD token !!!</div>\n</template>\n"

DESIGNER_JSON = json.dumps({
    "cases": [
        {"id": "tc-f01-1", "requirement_id": "F-01", "scenario": "用户列表加载",
         "steps": [
             {"action": "wait", "target": {"by": "css", "value": "#app"}},
             {"action": "assert", "target": {"by": "testid", "value": "app-root"},
              "assertion": "exists"},
         ], "requires_browser": False},
        {"id": "tc-f02-1", "requirement_id": "F-02", "scenario": "订单列表加载",
         "steps": [
             {"action": "assert", "target": {"by": "text", "value": "订单"},
              "assertion": "contains"},
         ], "requires_browser": False},
    ],
    "coverage_matrix": {"F-01": ["tc-f01-1"], "F-02": ["tc-f02-1"]},
}, ensure_ascii=False)

# 增量 drill 回归模式的 Designer 输出: 保留既有用例 + 新增数据看板用例。
DESIGNER_INC_JSON = json.dumps({
    "cases": [
        {"id": "tc-f01-1", "requirement_id": "F-01", "scenario": "用户列表加载",
         "steps": [
             {"action": "wait", "target": {"by": "css", "value": "#app"}},
             {"action": "assert", "target": {"by": "testid", "value": "app-root"},
              "assertion": "exists"},
         ], "requires_browser": False},
        {"id": "tc-f02-1", "requirement_id": "F-02", "scenario": "订单列表加载",
         "steps": [
             {"action": "assert", "target": {"by": "text", "value": "订单"},
              "assertion": "contains"},
         ], "requires_browser": False},
        {"id": "tc-f03-1", "requirement_id": "F-03", "scenario": "数据看板加载",
         "steps": [
             {"action": "assert", "target": {"by": "testid", "value": "board-refresh"},
              "assertion": "exists"},
         ], "requires_browser": False},
    ],
    "coverage_matrix": {
        "F-01": ["tc-f01-1"], "F-02": ["tc-f02-1"], "F-03": ["tc-f03-1"],
    },
}, ensure_ascii=False)

# 结构化需求 (两功能点) — 全流程 drill 注入 session 产物时使用。
REQUIREMENTS_STATE_JSON = json.dumps({
    "vision": {
        "project_name": "后台管理系统", "core_problem": "缺乏统一管理后台",
        "target_users": [{"role": "管理员", "description": "日常运营"}],
        "success_criteria": ["权限可配置"], "scope_note": "一期不含移动端",
    },
    "features": [
        {"id": "F-01", "name": "用户管理", "description": "用户增删改查",
         "priority": "must", "completeness": 100, "confirmed": True},
        {"id": "F-02", "name": "订单管理", "description": "订单列表与状态流转",
         "priority": "must", "completeness": 100, "confirmed": True},
    ],
    "pages": [
        {"id": "P-01", "name": "用户列表", "parent_id": None,
         "page_type": "list", "features": ["F-01"]},
        {"id": "P-02", "name": "订单列表", "parent_id": None,
         "page_type": "list", "features": ["F-02"]},
    ],
    "page_details": {
        "P-01": {"display_fields": [{"name": "用户名", "type": "text", "required": True}],
                 "action_buttons": [{"label": "编辑", "type": "custom"}],
                 "related_data": [], "layout_notes": ""},
        "P-02": {"display_fields": [{"name": "订单号", "type": "text", "required": True}],
                 "action_buttons": [], "related_data": [], "layout_notes": ""},
    },
    "tech_constraints": {"framework": "vue3", "component_lib": "element-plus",
                         "data_source": "", "special_requirements": []},
    "data_entities": [{"name": "User", "fields": [{"name": "id", "type": "string", "required": True}]}],
}, ensure_ascii=False)

# 增量 drill: 三功能点结构化需求 (新增 数据看板 F-03)。
REQUIREMENTS_STATE_INC_JSON = json.dumps({
    "vision": {
        "project_name": "后台管理系统", "core_problem": "缺乏统一管理后台",
        "target_users": [{"role": "管理员", "description": "日常运营"}],
        "success_criteria": ["权限可配置"], "scope_note": "一期不含移动端",
    },
    "features": [
        {"id": "F-01", "name": "用户管理", "description": "用户增删改查",
         "priority": "must", "completeness": 100, "confirmed": True},
        {"id": "F-02", "name": "订单管理", "description": "订单列表与状态流转",
         "priority": "must", "completeness": 100, "confirmed": True},
        {"id": "F-03", "name": "数据看板", "description": "运营数据概览",
         "priority": "should", "completeness": 100, "confirmed": True},
    ],
    "pages": [
        {"id": "P-01", "name": "用户列表", "parent_id": None,
         "page_type": "list", "features": ["F-01"]},
        {"id": "P-02", "name": "订单列表", "parent_id": None,
         "page_type": "list", "features": ["F-02"]},
        {"id": "P-03", "name": "数据看板", "parent_id": None,
         "page_type": "dashboard", "features": ["F-03"]},
    ],
    "page_details": {
        "P-01": {"display_fields": [{"name": "用户名", "type": "text", "required": True}],
                 "action_buttons": [{"label": "编辑", "type": "custom"}],
                 "related_data": [], "layout_notes": ""},
        "P-02": {"display_fields": [{"name": "订单号", "type": "text", "required": True}],
                 "action_buttons": [], "related_data": [], "layout_notes": ""},
        "P-03": {"display_fields": [{"name": "指标", "type": "text", "required": True}],
                 "action_buttons": [], "related_data": [], "layout_notes": ""},
    },
    "tech_constraints": {"framework": "vue3", "component_lib": "element-plus",
                         "data_source": "", "special_requirements": []},
    "data_entities": [{"name": "User", "fields": [{"name": "id", "type": "string", "required": True}]}],
}, ensure_ascii=False)

# 增量 PRD: 完整文档 (下游不变式), 含新增 数据看板。
PRD_INC = (
    "# 需求规格文档\n\n"
    "## 1. 功能概述\n后台管理系统，管理员日常运营管理。\n"
    "## 2. 功能模块\n- 用户管理（必须）：用户的增删改查（已有功能，未变更）\n"
    "- 订单管理（必须）：订单列表与状态流转（已有功能，未变更）\n"
    "- 数据看板（应有）：运营数据概览（本次新增）\n"
    "## 3. 页面结构\n- 用户列表页（list）\n- 订单列表页（list）\n- 数据看板页（dashboard）\n"
    "## 4. 数据模型\n- User: id/name/role\n- Order: id/status\n"
    "## 5. 交互行为\n- 数据看板支持按日刷新\n"
)

# 增量合并 Spec: 既有结构 + 新增 数据看板 页。
SPEC_INC = {
    **SPEC_SM,
    "directory_tree": {"src/": ["main.ts", "App.vue", "pages/", "components/"]},
    "pages": [
        {"id": "p-01", "name": "首页", "interactions": [], "data": []},
        {"id": "p-02", "name": "数据看板", "interactions": [{"trigger": "refresh", "effect": "reload"}],
         "data": []},
    ],
    "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
}

# 增量 delta DAG: 只含新增模块任务 (Planner delta prompt 产物)。
DAG_INC_DELTA = json.dumps({"reasoning": "增量任务", "tasks": [
    {"id": "task-inc-0", "type": "business", "description": "数据看板页面",
     "deps": [], "files": ["src/pages/DataBoard.vue"], "contract": {}, "status": "pending"},
]}, ensure_ascii=False)

FILE_BOARD = (
    "<template>\n  <button data-testid=\"board-refresh\">刷新</button>\n"
    "  <div data-testid=\"board-root\">指标区</div>\n</template>\n"
)

MANIFEST_JSON = json.dumps({
    "type": "new_feature",
    "affected_modules": ["src/pages/DataBoard.vue"],
    "affected_requirement_points": ["F-03"],
    "behavior_changes": [],
}, ensure_ascii=False)

CLASSIFY_DRIFT = json.dumps({
    "category": "drift", "reason": "Spec 遗漏功能点 订单管理",
    "scope_change": {"required": False, "note": ""},
}, ensure_ascii=False)

DIAGNOSIS_FIX = ('{"root_cause": "编译错误", '
                 '"fix_instructions": "修正语法错误", '
                 '"affected_files": ["src/App.vue"]}')


def token_turn(text: str):
    """One plain-text LLM turn: TokenEvent + CompleteEvent."""
    from app.services.llm.provider import CompleteEvent, TokenEvent

    return [TokenEvent(text=text, index=0), CompleteEvent(finish_reason="stop", usage={})]


def tool_turn(name: str, args: dict, call_id: str = "call_1"):
    """One tool-call LLM turn: ToolCallEvent + CompleteEvent."""
    from app.services.llm.provider import CompleteEvent, ToolCallEvent

    return [ToolCallEvent(call_id=call_id, name=name, arguments=json.dumps(args, ensure_ascii=False)),
            CompleteEvent(finish_reason="stop", usage={})]


def done_turn():
    """Executor termination turn."""
    return token_turn("__TASK_DONE__")


def write_code_turn(path: str, content: str, call_id: str = "call_1"):
    return tool_turn("write_code", {"path": path, "content": content}, call_id)


class ScriptedFlowProvider:
    """Scripted provider installed as ``nodes._provider`` for the drills.

    ``script(marker, *turns)`` registers an ordered queue per prompt marker;
    unregistered prompts fail loudly. Executor prompts (``MARK_EXECUTOR``) are
    served by the message-count heuristic — the first call of a task (2
    messages) writes its first file from ``self.files``, later calls emit
    ``__TASK_DONE__``.
    """

    def __init__(self):
        self.turns: dict[str, list[list[Any]]] = {}
        self.files: dict[str, str] = {}
        self.calls: list[str] = []          # markers served, in order
        self.user_texts: list[str] = []     # user message per call (assertion hooks)
        self._queues: dict[str, list[list[Any]]] = {}
        self.max_inflight = 0
        self._inflight = 0
        self._executor_enabled = False

    def script(self, marker: str, *turns: list[Any]) -> "ScriptedFlowProvider":
        self.turns.setdefault(marker, []).extend(list(t) for t in turns)
        return self

    def enable_executor_heuristic(self) -> "ScriptedFlowProvider":
        """Opt-in: 允许消息数启发式服务 executor 调用 (工具轮 + __TASK_DONE__)。

        Executor 由消息数启发式驱动而非脚本队列 — 未显式启用时 executor
        prompt 视为未脚本 → fail loudly (绝不静默误服务意外出现的代码阶段)。
        """
        self._executor_enabled = True
        return self

    def _marker_for(self, system: str) -> str | None:
        # Executor 不 script (消息数启发式驱动) — 启用后才可识别 (review nit:
        # 未启用时 fail-loud 契约完整, 意外 executor 调用不会被静默服务)。
        if MARK_EXECUTOR in system and self._executor_enabled:
            return MARK_EXECUTOR
        hits = [m for m in self.turns if m in system]
        if not hits:
            return None
        return max(hits, key=len)

    @staticmethod
    def _task_files(text: str) -> list[str]:
        m = re.search(r"## 需要生成的文件\n(\[.*?\])", text)
        return json.loads(m.group(1)) if m else []

    async def stream_generate(self, model, messages, config):
        m0 = messages[0] if messages else {}
        system = m0.content if hasattr(m0, "content") else (m0.get("content", "") if m0 else "")
        self._inflight += 1
        self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            marker = self._marker_for(system)
            self.calls.append(marker or "?")
            m1 = messages[1] if len(messages) > 1 else None
            self.user_texts.append(
                m1.content if hasattr(m1, "content") else (m1.get("content", "") if m1 else "")
            )
            if marker is None:
                raise AssertionError(f"unscripted LLM call: system={system[:100]!r}")

            # Executor: 2 messages = first round of a task (tool call); else done.
            if marker == MARK_EXECUTOR:
                m1 = messages[1] if len(messages) > 1 else None
                text = m1.content if hasattr(m1, "content") else (m1.get("content", "") if m1 else "")
                files = self._task_files(text)
                if len(messages) == 2 and files and files[0] in self.files:
                    for ev in write_code_turn(files[0], self.files[files[0]]):
                        yield ev
                    return
                for ev in done_turn():
                    yield ev
                return

            queue = self._queues.setdefault(marker, [])
            if not queue:
                # 首次使用: 把该 marker 的脚本轮次搬入队列。
                queue.extend(self.turns.get(marker, []))
            if not queue:
                raise AssertionError(
                    f"script exhausted for marker={marker!r} calls={self.calls} "
                    f"system_prompt={system[:200]!r}"
                )
            for ev in queue.pop(0):
                yield ev
        finally:
            self._inflight -= 1


class FailingCompileRegistry(ToolRegistry):
    """Test double of the frontend bundler channel: ``compile_project`` fails
    while a marker file ("BAD") exists in the generated set, passes once the
    marker is gone — the same semantics as ``report_frontend_compile``
    (errors reported by the real bundler). Used to inject compile failures
    into the real phase-3 pipeline.
    """

    def __init__(self, project_root: str, bad_marker: str = "BAD"):
        super().__init__(project_root)
        self.bad_marker = bad_marker

    async def invoke(self, name: str, args: dict) -> ToolResult:
        if name == "compile_project":
            files = self._generated_files
            if any(self.bad_marker in content for content in files.values()):
                return ToolResult(ok=False, data={"errors": [
                    {"file": "src/App.vue", "line": 2, "column": 5,
                     "text": "Unexpected token — 注入的编译错误（前端 bundler 上报）"},
                ]})
            return ToolResult(ok=True, data={"errors": []})
        return await super().invoke(name, args)


def events_of(events: list[dict], event_type: str) -> list[dict]:
    return [e for e in events if e["event_type"] == event_type]


def cards_of(events: list[dict], card: str | None = None) -> list[dict]:
    out = [e["data"] for e in events if e["event_type"] == "manager_message"]
    if card is not None:
        out = [d for d in out if d.get("card") == card]
    return out


def base_state(**overrides) -> dict:
    """GraphRunner 初始 state (servicer 形状的子集)。"""
    state = {
        "requirement": "做一个后台管理系统",
        "component_lib": "element-plus",
        "messages": [{"role": "user", "content": "做一个后台管理系统"}],
        "requirements_state_json": None,
        "brainstorm_decisions": None,
        "brainstorm_assumptions": None,
        "analysis_result": None,
        "design_result": None,
        "design_doc": None,
        "architecture_spec": None,
        "code_result": None,
        "generated_files": {},
        "compile_errors": None,
        "e2e_results": None,
        "e2e_test_cases": None,
        "e2e_passed": False,
        "failure_details": None,
        "qa_rounds": 0,
        "rollback_records": [],
        "rollback_count": {},
        "max_rollback_per_node": 3,
        "max_rollback_total": 10,
        "needs_manual_review": False,
        "stage_phase": "generating",
        "e2e_test_cases_md": None,
        "e2e_user_confirmed": False,
        "dispatch_contract": {
            "task_id": "analysis",
            "input_ref": "requirement",
            "acceptance_criteria": ["PRD 非空且含功能模块与页面结构"],
            "tool_bounds": [],
            "constraints": [],
        },
        "manager_verdicts": [],
        "planner_dag": None,
        "context_summary": None,
        "incremental_mode": False,
        "user_id": "drill-user",
    }
    state.update(overrides)
    return state


async def collect(agen) -> list[dict]:
    """Drain an async generator into a list."""
    return [ev async for ev in agen]


def project_root_of(state: dict) -> str:
    from app.services.generation.memory import project_root_for

    return project_root_for(state)
