# ai-design-platform-server/ai-service/app/services/generation/nodes.py
import json
from typing import Any

import structlog

from ..llm.provider import LLMConfig, LLMProvider, ReasoningEvent, TokenEvent, Message, ToolCallEvent, CompleteEvent
from .state import GenerationState
from .planner import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_REFLECT_PROMPT,
    extract_task_dag,
    extract_reflect_decision,
    build_planner_user_prompt,
)
from .context_manager import extract_interface_contract

logger = structlog.get_logger()

# Provider singleton (set per request)
_provider: LLMProvider | None = None


def set_provider(provider: LLMProvider):
    global _provider
    _provider = provider


async def _llm_generate(
    system_prompt: str,
    user_content: str,
    model: str = "glm-5.2",
    enable_thinking: bool = True,
    on_reasoning: Any | None = None,
    on_token: Any | None = None,
) -> str:
    """Call LLM and collect full response as string.

    With enable_thinking=True, the model will think before responding.
    on_reasoning(text) is called for each reasoning chunk.
    on_token(text) is called for each content token (for real-time streaming).
    """
    if _provider is None:
        raise RuntimeError("LLM provider not set. Call set_provider() first.")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    config = LLMConfig(enable_thinking=enable_thinking)
    full_text = ""
    async for event in _provider.stream_generate(model, messages, config):
        if isinstance(event, TokenEvent):
            full_text += event.text
            if on_token:
                on_token(event.text)
        elif isinstance(event, ReasoningEvent):
            if on_reasoning:
                on_reasoning(event.text)
    logger.debug(
        "_llm_generate_result",
        text_len=len(full_text),
        text_preview=full_text[:200] if full_text else "(empty)",
    )
    return full_text


# ---- Analysis Node (direct PRD generation) ----

ANALYSIS_PRD_PROMPT = """你是一个资深产品需求分析师。根据用户的原始需求与头脑风暴澄清产物，直接生成一份完整的需求规格文档（PRD）。

## 文档结构（严格按此顺序输出）
1. **# 需求规格文档** — 文档标题
2. **## 1. 功能概述** — 项目背景、目标用户、核心问题、成功标准
3. **## 2. 功能模块** — 按优先级排列的功能清单（必须有/应该有/锦上添花）
4. **## 3. 页面结构** — 页面树形结构，标注页面类型
5. **## 4. 数据模型** — 核心数据实体及字段定义
6. **## 5. 交互行为** — 关键交互流程说明
7. **## 6. 假设清单** — 澄清中未确认、按假设处理的议程项（仅当输入提供假设清单时输出）

## 规则
- 若输入包含「澄清产物」（结构化需求 / 决策日志 / 假设清单），须以其为准：结构化需求决定功能与页面内容，决策日志如实写入相关章节，假设清单逐条列入「## 6. 假设清单」并标注（待确认，用户可纠正）
- 未提供假设清单时，可不输出第 6 节
- 用简洁专业的语言
- 不确定的地方合理推测并标注（待确认）
- 不写代码、不写技术实现、不写组件选择
- 输出纯 Markdown，不要 JSON 包裹"""


async def analysis_node(state: GenerationState) -> GenerationState:
    """需求分析节点：直接根据用户需求生成 PRD 文档."""
    logger.info("analysis_node_start")

    # Short-circuit: PRD already generated (via /api/v1/prd/stream)
    if state.get("analysis_result"):
        logger.info("analysis_node_skip — analysis_result already present")
        return {
            **state,
            "stage_phase": "complete",
        }

    requirement = state.get("requirement", "")
    messages = state.get("messages", [])
    qa_rounds = state.get("qa_rounds", 0)

    # Task group 3 (3.6): PRD 消费澄清产物（结构化需求 + 决策日志 + 假设清单）
    requirements_state_json = state.get("requirements_state_json")
    if requirements_state_json:
        parts = [
            f"用户需求：{requirement}",
            "以下为头脑风暴澄清产物，请以其为准生成完整的需求规格文档：",
            f"### 结构化需求\n{requirements_state_json}",
        ]
        decisions = state.get("brainstorm_decisions") or []
        assumptions = state.get("brainstorm_assumptions") or []
        if decisions:
            parts.append("### 决策日志\n" + json.dumps(decisions, ensure_ascii=False))
        if assumptions:
            parts.append("### 假设清单\n" + json.dumps(assumptions, ensure_ascii=False))
        user_prompt = "\n\n".join(parts)
    else:
        # Collect conversation context
        context = ""
        for m in messages:
            context += f"\n[{m.get('role', '?')}]: {m.get('content', '')}"

        user_prompt = f"用户需求：{requirement}\n\n对话上下文：{context}\n\n请生成完整的需求规格文档。"

    prd_text = await _llm_generate(
        system_prompt=ANALYSIS_PRD_PROMPT,
        user_content=user_prompt,
    )

    # E2E cases are no longer placeholder-extracted here — the Test Designer
    # (task group 6, e2e_designer) generates the real DSL cases at the e2e
    # stage from the requirement points + architecture Spec.
    return {
        **state,
        "analysis_result": prd_text,
        "qa_rounds": qa_rounds + 1,
        "stage_phase": "complete",
    }


# ---- Design Node ----

DESIGN_SYSTEM_PROMPT = """你是一个资深前端架构师。根据需求分析文档，输出详细设计方案。

## 输出格式
### 1. 组件树结构
- 用缩进列表展示组件层级关系
- 标注每个组件的职责

### 2. 数据流设计
- 组件间数据传递方式 (props / provide-inject / pinia)
- 状态管理方案

### 3. 样式方案
- 布局策略 (Flex / Grid)
- 响应式设计考虑
- 组件库使用方式

### 4. 文件拆分方案
- 建议的文件目录结构
- 每个文件的职责说明

### 5. 关键实现要点
- 核心逻辑的实现思路
- 需要注意的边界情况"""


def _clarify_blocks(state: GenerationState | None) -> list[str]:
    """澄清产物 prompt 块（结构化需求 + 决策日志 + 假设清单），供 Spec 生成消费（4.2）."""
    blocks: list[str] = []
    if not state:
        return blocks
    requirements_state_json = state.get("requirements_state_json")
    if requirements_state_json:
        try:
            pretty = json.dumps(
                json.loads(requirements_state_json),
                ensure_ascii=False, indent=2,
            )
        except (json.JSONDecodeError, TypeError):
            pretty = requirements_state_json
        blocks.append(f"头脑风暴澄清产物（结构化需求，以其为准）：\n{pretty}")
    decisions = state.get("brainstorm_decisions") or []
    if decisions:
        blocks.append("决策日志：\n" + json.dumps(decisions, ensure_ascii=False, indent=2))
    assumptions = state.get("brainstorm_assumptions") or []
    if assumptions:
        blocks.append("假设清单：\n" + json.dumps(assumptions, ensure_ascii=False, indent=2))
    return blocks


async def _spec_default_llm(system_prompt: str, user_content: str) -> str:
    """Default LLM seam for the structured Spec call: thinking off (4.2).

    The Spec is a pure JSON contract — emitted directly, no reasoning stream —
    keeping the call fast and the output clean. Tests inject their own
    ``llm_fn`` instead.
    """
    return await _llm_generate(
        system_prompt=system_prompt,
        user_content=user_content,
        enable_thinking=False,
    )


async def generate_architecture_spec(
    prd: str,
    state: GenerationState | None = None,
    llm_fn: Any | None = None,
    max_attempts: int = 2,
    feedback: str = "",
    existing_spec: dict | None = None,
) -> tuple[dict, list[str]]:
    """Generate the machine-readable architecture Spec (4.2).

    Single-turn structured LLM call with the D5 schema, via brainstorm's
    ``_llm_structured`` seam (lazy import: breaks the nodes↔brainstorm import
    cycle). Schema-validated before acceptance: an invalid result is retried
    once with the validation errors fed back into the prompt. The final result
    (possibly still invalid) is returned so the manager gate decides.

    ``llm_fn`` defaults to the singleton path with thinking off
    (``_spec_default_llm``); tests pass a fake. ``feedback`` (review fix 1) is
    the previous gate's redo reason (L1 field list / L2 missing list), fed back
    when the design re-runs after a failed gate.

    ``existing_spec`` (8.3 增量设计): the existing app's architecture.json
    summary. When provided the prompt instructs that the output MUST be the
    FULL merged spec (existing structure + the delta changes) — the memory
    write overwrites architecture.json with the merged version, so downstream
    consumers (Planner / Verifier) always see a complete document.

    Returns ``(spec, validation_errors)``.
    """
    from .brainstorm import _llm_structured  # lazy: nodes ↔ brainstorm cycle
    from .spec_schema import (
        ARCHITECTURE_SPEC_PROMPT,
        empty_spec,
        validate_spec,
    )

    fn = llm_fn if llm_fn is not None else _spec_default_llm
    parts = [f"需求分析文档（PRD）：\n{prd}"]
    parts.extend(_clarify_blocks(state))
    # 7.6: 分发约束（含长期用户偏好）消费点 — Spec prompt (方案不得推翻偏好)。
    constraints = ((state or {}).get("dispatch_contract") or {}).get("constraints") or []
    if constraints:
        parts.append(
            "## 约束（Manager 分发 + 用户历史偏好，必须遵守）\n"
            + "\n".join(f"- {c}" for c in constraints)
        )
    if existing_spec:
        # 8.3 增量设计: 合并完整 Spec —— 输出 = 已有结构 + 本次变更。
        from .memory import _architecture_summary  # lazy: same-package summary

        parts.append(
            "## 已有架构 Spec（增量开发 —— 输出必须为合并后的完整 Spec）\n"
            "以下为已有应用架构摘要，本次变更是**在其基础上叠加**：\n"
            + json.dumps(_architecture_summary(existing_spec), ensure_ascii=False, indent=2)
            + "\n\n"
            "输出规则：完整输出合并后的架构 Spec —— 既有页面/组件/数据实体/路由保持存在"
            "（必要时用 abstract 概述），本次变更涉及的模块给出完整细节；"
            "禁止只输出变更部分（下游消费方需要完整文档）。"
        )
    if feedback:
        parts.append(
            "## Manager 把关反馈（上一版方案未通过，请据此修正后重新设计）\n"
            + feedback
        )
    base_prompt = "\n\n".join(parts)

    spec: dict = {}
    errors: list[str] = []
    for attempt in range(max_attempts):
        user_prompt = base_prompt
        if attempt > 0 and errors:
            user_prompt += (
                "\n\n## 上一版 Spec 未通过字段完整性校验（必须全部修正）：\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\n## 上一版 Spec 内容：\n"
                + json.dumps(spec, ensure_ascii=False, indent=2)
                + "\n\n请修正以上问题，重新输出完整的架构 Spec JSON（所有字段非空）。"
            )
        spec = await _llm_structured(ARCHITECTURE_SPEC_PROMPT, user_prompt, empty_spec(), fn)
        errors = validate_spec(spec)
        if not errors:
            break
        logger.warning("architecture_spec_validation_failed", attempt=attempt + 1, errors=errors)
    return spec, errors


# ---- Code Node (Tool-use Loop) ----

CODE_ORCHESTRATOR_PROMPT = """你是一个资深 Vue 3 全栈工程师，使用工具链逐步构建前端工程。

## 工作流程
1. 分析设计方案，调用 list_skills 和 mcp_query 了解可用工具和模板
2. 调用 use_skill 应用代码模板生成文件骨架（优先使用模板而非从零写）
3. 调用 write_code 逐个填充代码
4. 每 3-4 个文件完成后调用 compile_project 检查
5. 有编译错误时修复后再 compile
6. 全部编译通过后输出 __CODE_GEN_DONE__

## 规则
- 每次只做一件事，保持响应简短
- 组件名使用 PascalCase，文件名使用 kebab-case
- 使用 Vue 3 Composition API
- 代码输出 Composition API (`<script setup lang="ts">`)
- 确保每个 .vue 文件有完整的 `<template>`、`<script setup>`、`<style scoped>`
- 工具调用的 arguments 必须是合法 JSON 字符串
- 如果不需要调用工具，直接输出简短文本回复
- 工具调用格式: {"tool_calls": [{"id": "call_N", "function": {"name": "...", "arguments": "{\\"key\\": \\"value\\"}"}}]}

## data-testid 埋点（5.7，必做）
- 关键交互元素（按钮/输入框/链接导航/分页/选项卡/弹窗等）必须带语义化 data-testid 钩子（kebab-case，如 save-button、pagination-next）
- 缺少 data-testid 的交互元素会被 Verifier 判为验证失败"""

EXECUTOR_SYSTEM_PROMPT = """你是一个 Vue 3 前端工程师，负责完成一个具体的代码生成任务。

## 任务信息
你会收到一个具体的 task，包含：
- 任务描述
- 需要生成的文件列表
- 接口契约（exports/props/events 要求）
- 依赖文件的接口摘要

## 工作流程
1. 理解任务目标和接口契约
2. 调用 use_skill 或 mcp_query 获取模板和文档
3. 调用 write_code 逐个生成文件
4. 全部文件生成后调用 verify_contract 校验本任务的接口契约：
   - consumer_file / provider_file 取本任务或依赖任务中相互引用的文件
   - expected_interface 取任务 contract 中的 exports/props/events（依赖任务契约同样校验）
   - 返回 violations 时修复对应文件，然后再次调用 verify_contract，直到 match=true
5. 调用 compile_project 检查编译
6. 有编译错误时修复后再 compile
7. 编译通过且契约校验通过后输出 __TASK_DONE__

## 验收标准（输出 __TASK_DONE__ 前必须全部满足）
- 文件清单：任务 files 全部生成
- 契约一致：verify_contract 校验 match=true（exports/props/events 与契约一致）
- 编译通过：compile_project 无错误
- 埋点完整：关键交互元素均带语义化 data-testid（见下方埋点规则）

## data-testid 埋点规则（5.7，必做）
- 所有关键交互元素必须带语义化 data-testid 钩子，钩子名用 kebab-case 英文（如 save-button、pagination-next、search-input、user-menu、login-submit）
- 覆盖范围：按钮（button/el-button）、输入框（input/el-input/textarea/el-select）、链接与导航（a/router-link/el-menu-item）、分页（el-pagination）、选项卡（el-tabs/el-tab-pane）、弹窗（el-dialog）、开关（el-switch）、单选复选（el-radio/el-checkbox）、上传（el-upload）、日期（el-date-picker）
- data-testid 直接写在交互元素标签上：`<button data-testid="save-button">保存</button>`；组件库组件同样直接加属性（属性会透传到根元素）
- 纯展示元素（div/span/img/标题）不需要 data-testid
- 关键交互元素缺少 data-testid 会被 Verifier 判为验证失败，必须补全后才能输出 __TASK_DONE__

## 规则
- 只生成该 task 范围内的文件
- 遵守接口契约，确保导出的 props/events/slots 与契约一致
- 每次只做一件事
- 组件名使用 PascalCase，文件名使用 kebab-case
- 使用 Vue 3 Composition API (`<script setup lang="ts">`)
- 确保每个 .vue 文件有完整的 `<template>`、`<script setup>`、`<style scoped>`
- 工具调用的 arguments 必须是合法 JSON 字符串
"""


async def code_node(state: GenerationState) -> GenerationState:
    """代码生成节点 — 工具增强的迭代式工程生成."""
    logger.info("code_node_start")

    import os as _os

    from .memory import project_root_for  # task group 7: persistent root
    project_root = project_root_for(state)

    from .tools.registry import ToolRegistry
    registry = ToolRegistry(project_root)

    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")

    tools_schema = registry.get_schema()
    system_prompt = CODE_ORCHESTRATOR_PROMPT

    if failure:
        user_msg = (
            f"设计方案：\n{design_doc}\n\n"
            f"之前的代码存在问题：\n{failure['instruction']}\n\n"
            f"请修复代码，确保通过编译和校验。"
        )
    else:
        user_msg = (
            f"设计方案：\n{design_doc}\n\n"
            f"开始生成工程代码。先调用 list_skills 了解可用模板，然后规划文件结构并逐步生成。"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    max_tool_rounds = 20
    generated_files: dict[str, str] = {}
    last_compile_errors: list[dict] | None = None

    for round_idx in range(max_tool_rounds):
        logger.info("code_tool_round", round=round_idx + 1)

        try:
            response = await _llm_generate_with_tools(
                messages=messages,
                tools=tools_schema,
                model="glm-5.2",
            )
        except Exception as e:
            logger.error("llm_tool_call_error", error=str(e))
            break

        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                result = await registry.invoke(tool_name, tool_args)

                if tool_name == "write_code" and result.ok:
                    generated_files[tool_args.get("path", "")] = tool_args.get("content", "")
                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        generated_files[f["path"]] = f["content"]
                        # Also write to disk
                        _os.makedirs(
                            _os.path.dirname(_os.path.join(project_root, f["path"])),
                            exist_ok=True,
                        )
                        with open(_os.path.join(project_root, f["path"]), "w", encoding="utf-8") as wf:
                            wf.write(f["content"])

                if tool_name == "compile_project" and not result.ok:
                    last_compile_errors = result.data.get("errors", [])

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tc],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps({
                        "ok": result.ok,
                        "data": result.data,
                        "error": result.error,
                    }, ensure_ascii=False),
                })

        elif response.get("content"):
            messages.append({"role": "assistant", "content": response["content"]})
            if "__CODE_GEN_DONE__" in (response.get("content") or ""):
                logger.info("code_gen_done_signal")
                break

        if round_idx > 0 and round_idx % 3 == 0 and generated_files:
            compile_result = await registry.invoke("compile_project", {})
            last_compile_errors = (
                compile_result.data.get("errors", [])
                if not compile_result.ok
                else []
            )
            if compile_result.ok and not last_compile_errors:
                logger.info("compile_passed_early", round=round_idx + 1)
                break

    state["code_result"] = json.dumps(generated_files, ensure_ascii=False)
    state["generated_files"] = generated_files
    state["compile_errors"] = last_compile_errors
    state["stage_phase"] = "complete"

    return state


async def code_node_streaming(
    state: GenerationState,
    queue,
) -> GenerationState:
    """代码生成节点 — streaming 版本，每步工具调用通过 queue 实时发射事件."""

    import os as _os, json as _json

    from .memory import project_root_for  # task group 7: persistent root
    project_root = project_root_for(state)

    from .tools.registry import ToolRegistry

    try:
        registry = ToolRegistry(project_root)
    except Exception as e:
        logger.error("tool_registry_init_failed", error=str(e))
        queue.put_nowait(_make_queue_event("code_gen_done", "code", {
            "total_files": 0, "compile_errors": 1,
        }))
        state["generated_files"] = {}
        state["compile_errors"] = [{"file": "", "line": 0, "message": str(e)}]
        state["code_result"] = "{}"
        state["stage_phase"] = "complete"
        return state

    tools_schema = registry.get_schema()

    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")
    system_prompt = CODE_ORCHESTRATOR_PROMPT

    if failure:
        user_msg = (
            f"设计方案：\n{design_doc}\n\n"
            f"之前的代码存在问题：\n{failure['instruction']}\n\n"
            f"请修复代码，确保通过编译和校验。"
        )
    else:
        user_msg = (
            f"设计方案：\n{design_doc}\n\n"
            f"开始生成工程代码。先调用 list_skills 了解可用模板，然后规划文件结构并逐步生成。"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    max_tool_rounds = 20
    generated_files: dict[str, str] = {}
    last_compile_errors: list[dict] | None = None

    planned_files = _estimate_files(design_doc)
    queue.put_nowait(_make_queue_event("code_gen_start", "code", {
        "files": planned_files,
    }))

    for round_idx in range(max_tool_rounds):
        logger.info("code_tool_round", round=round_idx + 1)

        def on_thinking(text: str):
            queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

        try:
            response = await _llm_generate_with_tools_streaming(
                messages=messages,
                tools=tools_schema,
                model="glm-5.2",
                on_thinking=on_thinking,
            )
        except Exception as e:
            logger.error("llm_tool_call_error", error=str(e))
            break

        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = _json.loads(tc["function"]["arguments"])
                except _json.JSONDecodeError:
                    tool_args = {}

                queue.put_nowait(_make_queue_event("tool_call", "code", {
                    "tool": tool_name,
                    "args": tool_args,
                    "status": "running",
                }))

                result = await registry.invoke(tool_name, tool_args)

                queue.put_nowait(_make_queue_event("tool_result", "code", {
                    "tool": tool_name,
                    "ok": result.ok,
                    "detail": result.data,
                }))

                if tool_name in ("create_file", "write_code") and result.ok:
                    path = tool_args.get("path", "")
                    content = tool_args.get("content", "")
                    if tool_name == "write_code" and content:
                        generated_files[path] = content
                        queue.put_nowait(_make_queue_event("file_start", "code", {"path": path}))
                        chunk_size = 200
                        for i in range(0, len(content), chunk_size):
                            queue.put_nowait(_make_queue_event("file_chunk", "code", {
                                "path": path,
                                "content": content[i:i + chunk_size],
                            }))
                        queue.put_nowait(_make_queue_event("file_complete", "code", {"path": path}))

                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        path = f["path"]
                        content = f["content"]
                        # Write to disk
                        _os.makedirs(_os.path.dirname(_os.path.join(project_root, path)), exist_ok=True)
                        with open(_os.path.join(project_root, path), "w", encoding="utf-8") as wf:
                            wf.write(content)
                        # Track file (don't emit frontend events — write_code handles that)
                        if path not in generated_files:
                            generated_files[path] = content

                elif tool_name == "compile_project":
                    errors = result.data.get("errors", []) if not result.ok else []
                    last_compile_errors = errors if not result.ok else None
                    queue.put_nowait(_make_queue_event("compile_status", "code", {
                        "ok": result.ok,
                        "errors": errors,
                    }))

                messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                    "content": _json.dumps({"ok": result.ok, "data": result.data, "error": result.error},
                    ensure_ascii=False)})

        elif response.get("content"):
            messages.append({"role": "assistant", "content": response["content"]})
            if "__CODE_GEN_DONE__" in (response.get("content") or ""):
                break

        if round_idx > 0 and round_idx % 3 == 0 and generated_files:
            compile_result = await registry.invoke("compile_project", {})
            ok = compile_result.ok
            errors = compile_result.data.get("errors", []) if not ok else []
            queue.put_nowait(_make_queue_event("compile_status", "code", {
                "ok": ok, "errors": errors,
            }))
            if ok and not errors:
                break

    queue.put_nowait(_make_queue_event("code_gen_done", "code", {
        "total_files": len(generated_files),
        "compile_errors": len(last_compile_errors) if last_compile_errors else 0,
    }))

    state["generated_files"] = generated_files
    state["compile_errors"] = last_compile_errors
    state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)
    state["stage_phase"] = "complete"
    return state


def build_fallback_dag(spec: dict | None, design_doc: str) -> dict:
    """5.2: Planner parse-failure fallback — derived from the Spec.

    A single business task covering the Spec's ``directory_tree`` files, with
    the contract annotated from ``data_model``/``pages``. No hardcoded
    bootstrap heuristics (the old fallback re-created qiankun/webpack tasks
    regardless of the Spec, contradicting 5.2). Falls back to
    ``_estimate_files`` when the Spec is absent (legacy path).
    """
    if spec:
        files: list[str] = []
        for entries in (spec.get("directory_tree") or {}).values():
            for entry in entries or []:
                if isinstance(entry, str) and entry and not entry.endswith("/"):
                    if entry not in files:
                        files.append(entry)
        contract: dict = {}
        data_entities = [
            e.get("name") for e in (spec.get("data_model") or [])
            if isinstance(e, dict) and e.get("name")
        ]
        pages = [
            p.get("name") for p in (spec.get("pages") or [])
            if isinstance(p, dict) and p.get("name")
        ]
        if data_entities:
            contract["data_entities"] = data_entities
        if pages:
            contract["pages"] = pages
        reasoning = "Fallback due to parse error — 依据架构 Spec 的 directory_tree/data_model/pages 推导"
        if not files:
            files = _estimate_files(design_doc)
    else:
        files = _estimate_files(design_doc)
        contract = {}
        reasoning = "Fallback due to parse error"
    return {
        "reasoning": reasoning,
        "tasks": [
            {
                "id": "task-code-0",
                "type": "business",
                "description": "Main app component and all business code",
                "deps": [],
                "files": files,
                "contract": contract,
                "status": "pending",
            },
        ],
    }


async def planner_node(
    state: GenerationState,
    queue,
) -> GenerationState:
    """Planner Agent — REASON→ACT: 依据架构 Spec 拆解 Task DAG (task 5.2).

    Incremental mode (8.3): the prompt switches to the delta-framed
    ``build_incremental_planner_prompt`` (existing file inventory + change
    manifest → tasks touching only the affected modules) and the existing
    ``generated_files`` are NOT wiped (they stay as the executor context).
    """
    logger.info("planner_node_start")

    spec = state.get("architecture_spec")
    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")
    reflect_count = state.get("planner_reflect_count", 0)

    incremental = bool(state.get("incremental_mode") and state.get("change_manifest"))
    if incremental:
        from .planner import build_incremental_planner_prompt

        inc_ctx = state.get("incremental_context") or {}
        user_prompt = build_incremental_planner_prompt(
            spec,
            design_doc,
            state.get("change_manifest"),
            inc_ctx.get("generated_files") or {},
        )
    else:
        user_prompt = build_planner_user_prompt(spec, design_doc, failure)

    # REASON + ACT: 一次性输出 DAG
    def on_thinking(text: str):
        queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

    queue.put_nowait(_make_queue_event("planner_start", "code", {
        "phase": "planning",
        "message": "正在分析设计方案，拆解任务...",
    }))

    raw_response = await _llm_generate(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_content=user_prompt,
        enable_thinking=True,
        on_reasoning=on_thinking,
    )

    try:
        dag = extract_task_dag(raw_response)
    except Exception as e:
        logger.error("planner_extract_failed", error=str(e))
        # Fallback: single business task derived from the Spec — no hardcoded
        # bootstrap heuristics (task 5.2).
        dag = build_fallback_dag(spec, design_doc)

    task_dag = {
        "tasks": dag["tasks"],
        "generated_at": str(round(__import__("time").time())),
        "total_tasks": len(dag["tasks"]),
        "completed_tasks": 0,
    }

    queue.put_nowait(_make_queue_event("planner_dag", "code", {
        "tasks": dag["tasks"],
        "reasoning": dag.get("reasoning", ""),
    }))

    state["planner_dag"] = task_dag
    state["planner_reflect_count"] = reflect_count
    state["context_summary"] = {"key_exports": {}, "completed_tasks": []}
    if not incremental:
        # 增量模式保留已有文件（8.3 只动受影响模块 —— 已有文件是执行上下文）;
        # 全量模式从空开始。
        state["generated_files"] = {}

    return state


async def executor_task(
    state: GenerationState,
    task: dict,
    queue,
    project_root: str,
    registry,
) -> dict:
    """
    Executor Agent — 为单个 task 运行 REASON→ACT→OBSERVE→REFLECT loop.
    Returns: {task_id, status, generated_files, compile_errors, summary}
    """
    task_id = task["id"]
    logger.info("executor_task_start", task_id=task_id, desc=task.get("description", ""))

    queue.put_nowait(_make_queue_event("task_start", "code", {
        "task_id": task_id,
        "description": task.get("description", ""),
        "files": task.get("files", []),
    }))

    # Build Executor context — include dependency contracts from context_summary
    context_summary = state.get("context_summary", {})
    deps_info = ""
    for dep_id in task.get("deps", []):
        for t in state.get("planner_dag", {}).get("tasks", []):
            if t["id"] == dep_id and t.get("status") == "done":
                deps_info += f"\n依赖 {dep_id} ({t['description']}): {json.dumps(t.get('contract', {}), ensure_ascii=False)}"
                # Include key exports for dependency files
                for f in t.get("files", []):
                    if f in context_summary.get("key_exports", {}):
                        deps_info += f"\n  {f} 接口: {json.dumps(context_summary['key_exports'][f], ensure_ascii=False)}"

    files_to_generate = task.get("files", [])
    contract = task.get("contract", {})

    system_prompt = EXECUTOR_SYSTEM_PROMPT
    # 5.5: Debugger 修复轮的重派上下文 —— 失败证据链（根因 + 修复指令）
    # 由 graph phase 3 写入 task["fix_instructions"] / task["root_cause"]，
    # 首次执行时为空（无修复上下文）。
    fix_context = task.get("fix_instructions") or ""
    if task.get("root_cause"):
        fix_context = f"根因：{task['root_cause']}\n" + fix_context
    user_msg = (
        f"## 任务\n{task.get('description', '')}\n\n"
        f"## 需要生成的文件\n{json.dumps(files_to_generate, ensure_ascii=False)}\n\n"
        f"## 接口契约要求\n{json.dumps(contract, ensure_ascii=False)}"
        f"{deps_info}\n\n"
        f"## 验收标准（任务完成前必须全部满足）\n"
        f"1. 文件清单：{json.dumps(files_to_generate, ensure_ascii=False)} 全部生成\n"
        f"2. 契约一致：调用 verify_contract 校验本任务与依赖任务的接口契约，violations 修复到 match=true\n"
        f"3. 编译通过：compile_project 无错误\n"
        f"4. 埋点完整：关键交互元素均带语义化 data-testid（kebab-case）\n"
        + (f"\n## Debugger 修复指令（上一轮验证失败，必须落实）\n{fix_context}\n" if fix_context else "")
        + f"\n开始生成。先调用 list_skills 了解可用模板。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    max_rounds = 12
    generated_files: dict[str, str] = {}
    deleted_files: list[str] = []
    compile_errors: list[dict] | None = None
    # 5.3: verify_contract 结果收集（任务级验收 — 契约一致）
    contract_results: list[dict] = []
    # 5.3/5.6 (并行纪律, review M1): 本任务写入的文件**逐路径**实时同步进
    # registry 缓存（registry.merge_generated_files({path: content})），使
    # verify_contract / retrieve_context 能查到刚写入的文件；绝不整包合并或
    # 全量替换 —— 整包合并会把同批任务已写入的路径回退成启动时快照的旧值。

    for round_idx in range(max_rounds):
        def on_thinking(text: str):
            queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

        try:
            response = await _llm_generate_with_tools_streaming(
                messages=messages,
                tools=registry.get_schema(),
                model="glm-5.2",
                on_thinking=on_thinking,
            )
        except Exception as e:
            logger.error("executor_llm_error", task_id=task_id, error=str(e))
            break

        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                queue.put_nowait(_make_queue_event("tool_call", "code", {
                    "tool": tool_name,
                    "args": tool_args,
                    "task_id": task_id,
                }))

                result = await registry.invoke(tool_name, tool_args)

                queue.put_nowait(_make_queue_event("tool_result", "code", {
                    "tool": tool_name,
                    "ok": result.ok,
                    "detail": result.data,
                    "task_id": task_id,
                }))

                if tool_name in ("create_file", "write_code") and result.ok:
                    path = tool_args.get("path", "")
                    content = tool_args.get("content", "")
                    # 5.6 review (deferred 5a item): create_file 现在也进缓存与
                    # 文件追踪 —— 骨架内容与 file_tools.create_file 一致，避免
                    # "文件已建但 missing_files 仍报缺失"的假阳性（并行下更易
                    # 触发缓存陈旧）。已存在的文件（created=False）不重写，
                    # 不追踪。delete_file 走下方分支同步移除缓存。
                    if tool_name == "create_file" and not content:
                        if result.data.get("created", False):
                            content = f"// {path}\n"
                        else:
                            content = ""
                    if content:
                        generated_files[path] = content
                        registry.merge_generated_files({path: content})
                        queue.put_nowait(_make_queue_event("file_start", "code", {"path": path}))
                        chunk_size = 200
                        for i in range(0, len(content), chunk_size):
                            queue.put_nowait(_make_queue_event("file_chunk", "code", {
                                "path": path,
                                "content": content[i:i + chunk_size],
                                "chunk_index": i // chunk_size,
                                "is_last_chunk_for_file": (i + chunk_size >= len(content)),
                            }))
                        queue.put_nowait(_make_queue_event("file_complete", "code", {"path": path}))

                elif tool_name == "delete_file" and result.ok:
                    path = tool_args.get("path", "")
                    if path:
                        generated_files.pop(path, None)
                        registry.remove_generated_file(path)
                        deleted_files.append(path)
                        queue.put_nowait(_make_queue_event("file_deleted", "code", {
                            "path": path,
                            "task_id": task_id,
                        }))

                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        fpath = f["path"]
                        fcontent = f["content"]
                        import os as _os
                        _os.makedirs(_os.path.dirname(_os.path.join(project_root, fpath)), exist_ok=True)
                        with open(_os.path.join(project_root, fpath), "w", encoding="utf-8") as wf:
                            wf.write(fcontent)
                        if fpath not in generated_files:
                            generated_files[fpath] = fcontent
                            registry.merge_generated_files({fpath: fcontent})

                elif tool_name == "verify_contract":
                    # 5.3: 收集契约校验结果 — 任务级验收的「契约一致」判定来源。
                    # expected_interface/error 记录用于区分真实校验与空校验
                    # （未提供 expected_interface 会被工具拒绝，见 context_manager）。
                    data = result.data or {}
                    contract_results.append({
                        "consumer_file": tool_args.get("consumer_file", ""),
                        "provider_file": tool_args.get("provider_file", ""),
                        "expected_interface": tool_args.get("expected_interface"),
                        "match": bool(data.get("match", False)),
                        "violations": data.get("violations", []),
                        "error": result.error,
                    })
                    queue.put_nowait(_make_queue_event("contract_status", "code", {
                        "task_id": task_id,
                        "ok": bool(data.get("match", False)),
                        "violations": data.get("violations", []),
                        "error": result.error,
                    }))

                elif tool_name == "compile_project":
                    data = result.data or {}
                    errors = data.get("errors", []) if not result.ok else []
                    compile_errors = errors if not result.ok else None
                    queue.put_nowait(_make_queue_event("compile_status", "code", {
                        "ok": result.ok,
                        "errors": errors,
                        "task_id": task_id,
                    }))

                messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                    "content": json.dumps({"ok": result.ok, "data": result.data, "error": result.error},
                    ensure_ascii=False)})

        elif response.get("content"):
            content = response["content"]
            messages.append({"role": "assistant", "content": content})
            if "__TASK_DONE__" in content:
                break

        # Auto-compile every 4 rounds
        if round_idx > 0 and round_idx % 4 == 0 and generated_files:
            compile_result = await registry.invoke("compile_project", {})
            ok = compile_result.ok
            errors = compile_result.data.get("errors", []) if not ok else []
            queue.put_nowait(_make_queue_event("compile_status", "code", {
                "ok": ok, "errors": errors, "task_id": task_id,
            }))
            if ok and not errors:
                break

    # Build summary
    summary = f"Task {task_id} done: {len(generated_files)} files"
    compile_err_count = len(compile_errors) if compile_errors else 0

    # 5.3: 任务级验收 — 文件清单 + 契约一致 + 编译通过。
    # contract_ok = 最后一次 verify_contract 的自检结果（violations 修复到
    # match=true 才算通过；中途失败的校验被修复后不判定任务失败）。
    missing_files = [f for f in files_to_generate if f not in generated_files]
    contract_ok: bool | None = (
        contract_results[-1]["match"] if contract_results else None
    )
    acceptance = {
        "files_ok": len(missing_files) == 0,
        "contract_ok": contract_ok,   # None = verify_contract 未被调用（未知）
        "compile_ok": not compile_errors,
        "details": {
            "missing_files": missing_files,
            "contract_results": contract_results,
        },
    }

    queue.put_nowait(_make_queue_event("task_complete", "code", {
        "task_id": task_id,
        "summary": summary,
        "file_count": len(generated_files),
        "compile_errors": compile_err_count,
    }))

    queue.put_nowait(_make_queue_event("task_acceptance", "code", {
        "task_id": task_id,
        "files_ok": acceptance["files_ok"],
        "contract_ok": acceptance["contract_ok"],
        "compile_ok": acceptance["compile_ok"],
        "missing_files": missing_files,
    }))

    return {
        "task_id": task_id,
        "status": "done" if not compile_errors else "failed",
        "generated_files": generated_files,
        "compile_errors": compile_errors,
        "summary": summary,
        # 5.3: additive — existing consumers (graph.py phase 3) keep reading
        # task_id/status/generated_files/compile_errors/summary unchanged.
        "acceptance": acceptance,
        # 5.6: additive — 任务内 delete_file 删除的路径（runner 从共享
        # generated_files 中移除，保证并行批次合并后删除不残留）。
        "deleted_files": deleted_files,
    }


async def planner_reflect_node(
    state: GenerationState,
    queue,
) -> GenerationState:
    """
    Planner REFLECT — 收集所有 Executor 结果，决定下一步。
    Returns updated state with decision baked in.
    """
    logger.info("planner_reflect_start")

    dag = state.get("planner_dag", {})
    context_summary = state.get("context_summary", {})
    generated_files = state.get("generated_files", {})
    compile_errors = state.get("compile_errors")

    # Update context_summary with latest file contracts
    key_exports = context_summary.get("key_exports", {})
    for path, content in generated_files.items():
        key_exports[path] = extract_interface_contract(path, content)
    context_summary["key_exports"] = key_exports

    # 5.3: 契约验收不过的任务按失败处理（contract_ok is False → failed，走
    # 自动重试路径）。contract_ok is None（从未调用 verify_contract）仅告警，
    # 不判失败 —— 5.4 Verifier 是确定性的兜底。
    for t in dag.get("tasks", []):
        acceptance = t.get("acceptance") or {}
        if t.get("status") == "done":
            if acceptance.get("contract_ok") is False:
                logger.warning("task_contract_failed", task_id=t.get("id"))
                t["status"] = "failed"
            elif acceptance.get("contract_ok") is None:
                logger.warning("task_contract_unverified", task_id=t.get("id"))

    # Check if all tasks are done
    all_done = all(
        t.get("status") in ("done", "failed")
        for t in dag.get("tasks", [])
    )
    failed_tasks = [
        t for t in dag.get("tasks", [])
        if t.get("status") == "failed"
    ]

    if all_done and not failed_tasks and not compile_errors:
        # All good
        queue.put_nowait(_make_queue_event("planner_reflect", "code", {
            "decision": "done",
            "reason": "所有任务完成，编译通过",
        }))
        state["context_summary"] = context_summary
        state["stage_phase"] = "complete"
        return state

    if all_done and failed_tasks:
        # Some tasks failed — auto-retry once
        queue.put_nowait(_make_queue_event("planner_reflect", "code", {
            "decision": "has_failures",
            "failed_task_ids": [t["id"] for t in failed_tasks],
        }))

        for t in dag.get("tasks", []):
            if t.get("status") == "failed":
                t["status"] = "pending"
                t["compile_errors"] = None

        state["planner_reflect_count"] = state.get("planner_reflect_count", 0) + 1
        state["context_summary"] = context_summary
        return state

    state["context_summary"] = context_summary
    return state


def _estimate_files(design_doc: str) -> list[str]:
    """Estimate the file list from design doc."""
    files = []
    for line in design_doc.split("\n"):
        line = line.strip()
        if line.endswith(".vue") or line.endswith(".ts") or line.endswith(".js"):
            if line not in files:
                files.append(line)
    if not files:
        files = ["App.vue", "components/Header.vue"]
    return files


def _make_queue_event(event_type: str, stage: str, data: dict) -> dict:
    return {"event_type": event_type, "stage": stage, "data": data}


async def _llm_generate_with_tools_streaming(
    messages: list[dict],
    tools: list[dict],
    model: str = "glm-5.2",
    on_thinking=None,
) -> dict:
    """Call LLM with native function calling — streaming via callback."""

    if _provider is None:
        raise RuntimeError("LLM provider not set.")

    # Convert dict messages to Message objects
    provider_messages = []
    for m in messages:
        content = m.get("content")
        tc_list = m.get("tool_calls")
        if tc_list:
            # Assistant message with tool_calls
            provider_messages.append(Message(
                role=m.get("role", "assistant"),
                content=json.dumps(tc_list, ensure_ascii=False) if content is None else (content or ""),
            ))
        else:
            provider_messages.append(Message(
                role=m.get("role", "user"),
                content=content or "",
            ))

    config = LLMConfig(enable_thinking=True, tools=tools)

    # Collect response
    full_content = ""
    tool_calls_list: list[dict] = []
    current_tool_call: dict | None = None

    async for event in _provider.stream_generate(model, provider_messages, config):
        if isinstance(event, TokenEvent):
            full_content += event.text
        elif isinstance(event, ReasoningEvent):
            if on_thinking:
                on_thinking(event.text)
        elif isinstance(event, ToolCallEvent):
            # Accumulate tool call deltas
            if current_tool_call and current_tool_call.get("id") == event.call_id:
                current_tool_call["function"]["arguments"] += (event.arguments or "")
            else:
                if current_tool_call:
                    tool_calls_list.append(current_tool_call)
                current_tool_call = {
                    "id": event.call_id or "",
                    "function": {
                        "name": event.name or "",
                        "arguments": event.arguments or "",
                    },
                }
        elif isinstance(event, CompleteEvent):
            if current_tool_call:
                tool_calls_list.append(current_tool_call)

    if tool_calls_list:
        return {"content": None, "tool_calls": tool_calls_list}

    return {"content": full_content.strip(), "tool_calls": None}


async def _llm_generate_with_tools(
    messages: list[dict],
    tools: list[dict],
    model: str = "glm-5.2",
) -> dict:
    """Call LLM with function calling support. Returns {"content": ..., "tool_calls": ...}.

    Uses a prompt-based approach: injects tool schema into system prompt
    and parses the response for tool_calls JSON.
    """
    tool_prompt = (
        "\n\n你可以调用以下工具函数。要调用工具，在回复中输出 JSON：\n"
        '{"tool_calls": [{"id": "call_1", "function": {"name": "工具名", "arguments": "{\\"key\\": \\"value\\"}"}}]}\n'
        "可用工具：\n" + json.dumps(tools, ensure_ascii=False, indent=2) + "\n"
        "如果不需要调用工具，直接输出文本回复。"
    )

    messages_with_tools = list(messages)
    if messages_with_tools and messages_with_tools[0]["role"] == "system":
        messages_with_tools[0] = {
            "role": "system",
            "content": messages_with_tools[0]["content"] + tool_prompt,
        }
    else:
        messages_with_tools.insert(0, {"role": "system", "content": tool_prompt})

    prompt_text = ""
    for m in messages_with_tools:
        role = m.get("role", "?")
        content = m.get("content", "")
        if content is None and m.get("tool_calls"):
            content = json.dumps(m["tool_calls"], ensure_ascii=False)
        prompt_text += f"\n[{role}]: {content or ''}"

    raw = await _llm_generate(
        system_prompt=prompt_text[:500],
        user_content=prompt_text[500:],
        model=model,
    )

    try:
        parsed = json.loads(raw.strip())
        if "tool_calls" in parsed:
            return {"content": None, "tool_calls": parsed["tool_calls"]}
    except (json.JSONDecodeError, KeyError):
        pass

    return {"content": raw.strip(), "tool_calls": None}


# ---- E2E Node (two-phase: Test Designer → user confirm → frontend runner) ----
# Task group 6: phase 1 invokes the Test Designer (e2e_designer) which emits a
# coverage matrix + structured DSL cases (6.1), applies selector priority
# (6.2), gates coverage completeness (6.5), writes cases into the repo (6.6)
# and annotates requires_browser (6.7). The rendered MD summary keeps the
# existing frontend doc display; the DSL list is the canonical artifact.


async def e2e_node(state: GenerationState) -> GenerationState:
    """E2E 节点 — 两阶段：Test Designer 生成覆盖矩阵 + DSL 用例 → 用户确认 → 前端 Runner 执行.

    Incremental mode (8.3/8.4 回归模式): the Designer receives the preserved
    historical cases (dispositions keep/fix-selector) and ADDS cases for the
    changed/new requirement points — retired/updated cases stay out (retire →
    archived / update → expected_broken were applied at the disposition
    confirmation step).
    """

    e2e_confirmed = state.get("e2e_user_confirmed", False)

    if not e2e_confirmed:
        # Phase 1: Test Designer — coverage matrix + DSL cases.
        logger.info("e2e_phase1_design_cases")

        # Idempotence: the gate may route back to the e2e worker while cases
        # await confirmation — never regenerate already-designed cases.
        if state.get("e2e_test_cases"):
            logger.info("e2e_phase1_skip_designer_cases_exist")
            return {
                **state,
                "stage_phase": "reviewing",
            }

        from .e2e_designer import project_root_for, run_e2e_designer

        project_root = project_root_for(state)
        preserved_cases = None
        if state.get("incremental_mode") and state.get("test_dispositions"):
            # 8.3 regression mode: 保留 keep/fix-selector 历史用例, update/retire
            # 不保留 (update 由 Designer 重设计, retire 已归档)。
            from .incremental import load_existing_cases  # lazy: no module cycle

            disp_by_id = {
                d.get("case_id"): d.get("disposition")
                for d in (state.get("test_dispositions") or [])
                if isinstance(d, dict)
            }
            existing = load_existing_cases(project_root)
            preserved_cases = [
                c for c in existing
                if disp_by_id.get(c.get("id"), "keep") in ("keep", "fix-selector")
            ]
            logger.info(
                "e2e_incremental_designer",
                preserved=len(preserved_cases), total=len(existing),
            )

        report = await run_e2e_designer(
            state,
            llm_fn=None,
            project_root=project_root,
            existing_cases=preserved_cases,
        )

        return {
            **state,
            "e2e_designer_report": report,
            "e2e_coverage_matrix": report["coverage"],
            "e2e_test_cases": report["cases"],
            "e2e_test_cases_md": report["md"],
            "stage_phase": "reviewing",
        }

    else:
        # Phase 2: pass-through — execution stays frontend-driven (the graph
        # emits e2e_execute_start; the frontend runner POSTs results back via
        # ResumeAfterE2E → Test Diagnoser → gate routing).
        logger.info("e2e_phase2_execute")
        return {
            **state,
            "stage_phase": "complete",
            "e2e_test_cases": state.get("e2e_test_cases", []),
        }
