# ai-design-platform-server/ai-service/app/services/generation/nodes.py
import asyncio
import json
from typing import Any

import structlog

from ..llm.provider import LLMConfig, LLMProvider, ReasoningEvent, TokenEvent, Message, ToolCallEvent, CompleteEvent
from .state import GenerationState
from .harness import EvalHarness
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
    model: str = "deepseek-v4-pro",
    enable_thinking: bool = True,
    max_tokens: int = 4096,
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
    config = LLMConfig(enable_thinking=enable_thinking, max_tokens=max_tokens)
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


async def _llm_generate_structured(
    system_prompt: str,
    user_content: str,
    output_schema: dict[str, Any],
    model: str = "deepseek-v4-pro",
) -> dict[str, Any]:
    """Call LLM and parse response as JSON matching output_schema."""
    schema_hint = (
        f"\n\n你必须以 JSON 格式输出，格式如下：\n"
        f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}\n"
        f"只输出 JSON，不要有其他内容。"
    )
    full_prompt = system_prompt + schema_hint
    raw = await _llm_generate(full_prompt, user_content, model)
    # Extract JSON from response (handle markdown code blocks)
    raw_lower = raw.lower()
    if "```json" in raw_lower:
        idx = raw_lower.index("```json")
        fence_tag = raw[idx : idx + len("```json") + 2]  # capture exact tag incl. any trailing ws
        raw = raw.split(fence_tag, 1)[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```")[0]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.error(
            "structured_parse_failed",
            raw_text=raw[:500],
        )
        raise ValueError(
            f"Failed to parse structured JSON from LLM response. "
            f"Raw text (first 500 chars): {raw[:500]}"
        )


# ---- Analysis Node (direct PRD generation) ----

ANALYSIS_PRD_PROMPT = """你是一个资深产品需求分析师。根据用户的原始需求，直接生成一份完整的需求规格文档（PRD）。

## 文档结构（严格按此顺序输出）
1. **# 需求规格文档** — 文档标题
2. **## 1. 功能概述** — 项目背景、目标用户、核心问题、成功标准
3. **## 2. 功能模块** — 按优先级排列的功能清单（必须有/应该有/锦上添花）
4. **## 3. 页面结构** — 页面树形结构，标注页面类型
5. **## 4. 数据模型** — 核心数据实体及字段定义
6. **## 5. 交互行为** — 关键交互流程说明

## 规则
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

    # Collect conversation context
    context = ""
    for m in messages:
        context += f"\n[{m.get('role', '?')}]: {m.get('content', '')}"

    user_prompt = f"用户需求：{requirement}\n\n对话上下文：{context}\n\n请生成完整的需求规格文档。"

    prd_text = await _llm_generate(
        system_prompt=ANALYSIS_PRD_PROMPT,
        user_content=user_prompt,
    )

    e2e_cases = _extract_e2e_cases(prd_text)

    return {
        **state,
        "analysis_result": prd_text,
        "e2e_test_cases": e2e_cases,
        "qa_rounds": qa_rounds + 1,
        "stage_phase": "complete",
    }


# Remove old helper functions — no longer needed
# _emit_requirements_state, _handle_prd_generation, _user_wants_prd, _strategist, etc.


def _extract_e2e_cases(prd: str) -> list[dict]:
    """从 PRD 中提取 E2E 测试用例骨架."""
    return [
        {
            "id": "TC-001",
            "name": "页面加载验证",
            "description": "验证核心页面能正常加载",
            "steps": [
                {"action": "wait", "target": "body", "value": "2000", "description": "等待页面加载"},
                {"action": "assert", "target": "body", "value": "", "description": "页面已加载"},
            ],
        }
    ]


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


async def generate_architecture_spec(
    analysis_result: str,
    design_doc: str,
    retries: int = 1,
    on_reasoning: Any | None = None,
    on_token: Any | None = None,
) -> dict:
    """Generate the structured architecture Spec (JSON) from PRD + design doc.

    Flow: LLM outputs schema-shaped JSON → ``validate_spec`` → on failure retry
    once with validation feedback → final fallback merges into ``empty_spec``
    (structurally complete, never crashes). Returns the spec dict.

    on_reasoning(text): forwarded to the LLM call so the spec's thinking
    stream can be shown in the AgentLog (kills the "no feedback" dead air
    between stage_start and planner_start).
    on_token(text): forwarded too — spec generation runs with thinking
    disabled, so tokens are the only visible progress; both streams feed
    the AgentLog.
    """
    from .spec_schema import (
        ARCHITECTURE_SPEC_PROMPT,
        merge_into_spec,
        validate_spec,
    )

    user_content = (
        f"## 需求分析文档（PRD）\n{analysis_result[:6000]}\n\n"
        f"## 设计方案文档\n{design_doc[:8000]}"
    )

    def _parse_json(raw: str) -> dict | None:
        """Parse LLM output as JSON — fences, leading text, truncation tolerant.

        Strategies in order: strip ```json fences → raw json.loads → extract
        the first balanced {...} block (handles preamble/truncated-tail text).
        """
        raw = (raw or "").strip()
        if not raw:
            return None
        raw_lower = raw.lower()
        if "```json" in raw_lower:
            raw = raw.split("```json", 1)[1].split("```")[0].strip()
        elif "```" in raw_lower:
            raw = raw.split("```", 1)[1].split("```")[0].strip()
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        # Fallback: first balanced {...} block — tolerant of leading prose and
        # trailing text after the JSON.
        start = raw.find("{")
        if start >= 0:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(raw)):
                ch = raw[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(raw[start : i + 1])
                            return parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            return None
        return None

    last_raw = ""
    for attempt in range(retries + 1):
        try:
            raw_text = await _llm_generate(
                system_prompt=ARCHITECTURE_SPEC_PROMPT,
                user_content=user_content,
                # Structured output: no thinking (GLM thinking often consumes
                # the token budget or emits JSON into reasoning_content), and a
                # larger budget so a full Spec isn't truncated mid-JSON.
                # on_reasoning still surfaces whatever reasoning the model
                # streams, so the AgentLog shows live progress.
                enable_thinking=False,
                max_tokens=8192,
                on_reasoning=on_reasoning,
                on_token=on_token,
            )
            last_raw = raw_text
            parsed = _parse_json(raw_text)
            if parsed is None:
                if attempt >= retries:
                    break
                user_content += "\n\n上次输出不是合法 JSON，请只输出一个 JSON 对象。"
                continue
            problems = validate_spec(parsed)
            if not problems:
                return parsed
            logger.warning(
                "architecture_spec_invalid",
                attempt=attempt + 1,
                problems=problems,
            )
            if attempt < retries:
                user_content += (
                    f"\n\n校验未通过，请修正后重新输出完整 Spec：\n" + "\n".join(problems)
                )
        except Exception as e:
            logger.error("architecture_spec_generate_error", attempt=attempt + 1, error=str(e))
            if attempt >= retries:
                break

    # Final fallback: type-coercing merge, never crashes
    fallback = merge_into_spec(_parse_json(last_raw) if last_raw else None)
    logger.warning("architecture_spec_fallback", has_raw=bool(last_raw))
    return fallback


async def design_node(state: GenerationState) -> GenerationState:
    """方案设计节点：产出架构设计文档。"""
    logger.info("design_node_start")

    failure_details = state.get("failure_details")
    if failure_details and failure_details["source"] == "review":
        prompt = (
            f"原需求分析：\n{state['analysis_result']}\n\n"
            f"之前的设计方案存在问题，review 反馈如下：\n"
            f"{failure_details['instruction']}\n\n"
            f"请修改设计方案，解决上述问题。"
        )
    else:
        prompt = f"需求分析文档：\n{state['analysis_result']}"

    result = await _llm_generate(
        system_prompt=DESIGN_SYSTEM_PROMPT,
        user_content=prompt,
    )

    state["design_result"] = result
    state["design_doc"] = result
    state["stage_phase"] = "complete"
    check = EvalHarness.validate(state, "design")
    if not check.passed:
        logger.warning("design_validation_failed", errors=check.errors)

    # Structured architecture spec — the machine-readable design contract.
    # Only when the PRD is available and no spec exists yet (the main flow
    # generates it in graph Phase 2.5; this covers the LangGraph rollback path
    # where design regenerates — don't regenerate an existing spec).
    if state.get("analysis_result") and not state.get("architecture_spec"):
        spec = await generate_architecture_spec(
            analysis_result=state["analysis_result"],
            design_doc=result,
        )
        state["architecture_spec"] = spec
        state["spec_validation"] = EvalHarness.validate_spec_result(spec)

    return state


EXECUTOR_SYSTEM_PROMPT = """你是一个 Vue 3 前端工程师，负责完成一个具体的代码生成任务。

## 任务信息
你会收到一个具体的 task，包含：
- 任务描述
- 需要生成的文件列表
- 接口契约（exports/props/events 要求）
- 架构 Spec 相关片段（组件树/页面/数据模型/API 契约）与设计文档摘要
- 依赖文件的接口摘要

## 工作流程
1. 理解任务目标、接口契约与架构 Spec 片段
2. 调用 list_files 查看项目现状（**只调用一次**；项目为空是正常的初始状态，直接开始生成，不要反复查询、不要空转）
3. 需要了解已有文件接口时，调用 read_file 读取
4. 调用 use_skill 或 mcp_query 获取模板和文档
5. 调用 write_code 逐个生成文件（只生成 task 范围内的文件）——**每次工具调用都必须推进任务：查询类工具最多用 1-2 次，之后必须调用 write_code 生成文件，禁止只查询不生成**
6. 全部文件写完后输出 __TASK_DONE__

## 编译（可选工具，自行决定时机）
- compile_project 用于验证代码：import 路径、接口契约、类型是否正确。需要验证时自行调用查看结果；调用后发现错误，自行决定是否修复后再结束
- full=true 时包含 vue-tsc 类型检查（较慢），需要验证类型时用 full=true；平时用默认（快速检查）即可
- 不要每轮都调用编译；系统会在所有任务结束后统一执行全量编译，任务完成后仍存在的问题会进入系统修复流程——**任务完成不要求编译通过**

## 规则
- 只生成该 task 范围内的文件
- 生成代码必须与架构 Spec 片段一致：页面/组件/数据模型/API 契约不得遗漏或偏离
- 遵守接口契约，确保导出的 props/events/slots 与契约一致
- 每次只做一件事
- 组件名使用 PascalCase，文件名使用 kebab-case
- 使用 Vue 3 Composition API (`<script setup lang="ts">`)
- 确保每个 .vue 文件有完整的 `<template>`、`<script setup>`、`<style scoped>`
- 工具调用的 arguments 必须是合法 JSON 字符串
"""


async def code_passthrough_node(state: GenerationState) -> GenerationState:
    """LangGraph 'code' node — code generation is handled by graph Phase 3
    (Planner + Executor streaming). This passthrough preserves the already
    generated files so the graph can proceed to review without regenerating.
    """
    logger.info("code_passthrough_node")
    return {
        **state,
        "stage_phase": "complete",
    }


# Background architecture-spec generation, keyed by generation_id. Started
# right after the design stream completes (graph Phase 2); the planner awaits
# it inside its own task — the frontend already shows "功能开发 / 规划中" by
# then, so the confirm click is never blocked by spec generation. Results are
# cached per generation_id to survive across fresh-start confirms.
_spec_background_tasks: dict[str, asyncio.Task] = {}
_spec_results: dict[str, dict] = {}
# Per-generation chunk queues: the background task streams its reasoning and
# token chunks here; the planner drains them while awaiting so the AgentLog
# shows the spec being generated instead of dead air.
_spec_event_queues: dict[str, asyncio.Queue] = {}


def start_background_spec(
    generation_id: str,
    analysis_result: str,
    design_doc: str,
) -> None:
    """Kick off architecture-spec generation with a per-generation event
    queue. The planner drains the queue while awaiting the task, so the
    spec's generation stream reaches the AgentLog (thinking_chunk events)."""
    q: asyncio.Queue = asyncio.Queue()
    _spec_event_queues[generation_id] = q
    _spec_background_tasks[generation_id] = asyncio.create_task(
        generate_architecture_spec(
            analysis_result=analysis_result,
            design_doc=design_doc,
            on_reasoning=q.put_nowait,
            on_token=q.put_nowait,
        )
    )
    logger.info("architecture_spec_background_started gen=%s", generation_id)


async def await_architecture_spec(
    generation_id: str | None,
    analysis_result: str,
    design_doc: str,
    on_reasoning: Any | None = None,
) -> dict:
    """Get the architecture spec, cheapest source first.

    1. cached result from a previous phase (e.g. code-confirm re-entry),
    2. the in-flight background task started during the design phase,
    3. synchronous generation (no task was ever started).
    The result is cached under generation_id so later phases reuse it.
    on_reasoning is the AgentLog sink: the in-flight background task's queued
    chunks (reasoning + tokens) are drained and forwarded to it while
    awaiting; a synchronous generation streams directly into it.
    """
    if generation_id and generation_id in _spec_results:
        logger.info("architecture_spec_cached gen=%s", generation_id)
        return _spec_results[generation_id]

    task = _spec_background_tasks.get(generation_id) if generation_id else None
    if task is not None:
        q = _spec_event_queues.get(generation_id) if generation_id else None
        if q is not None:
            # Forward the spec's generation stream to the AgentLog while the
            # task runs — without this the planner_start message is followed
            # by minutes of silence (spec generation runs with thinking off,
            # so tokens are the only visible progress).
            while not task.done():
                try:
                    text = await asyncio.wait_for(q.get(), timeout=0.1)
                    if text and on_reasoning:
                        on_reasoning(text)
                except asyncio.TimeoutError:
                    pass
            while not q.empty():
                text = q.get_nowait()
                if text and on_reasoning:
                    on_reasoning(text)
            _spec_event_queues.pop(generation_id, None)
        try:
            spec = await task
            if generation_id:
                _spec_results[generation_id] = spec
                _spec_background_tasks.pop(generation_id, None)
            logger.info("architecture_spec_background_done gen=%s", generation_id)
            return spec
        except Exception as e:
            logger.warning("background_spec_task_failed", generation_id=generation_id, error=str(e))
            _spec_background_tasks.pop(generation_id, None)

    logger.info("architecture_spec_sync gen=%s", generation_id)
    spec = await generate_architecture_spec(
        analysis_result=analysis_result,
        design_doc=design_doc,
        on_reasoning=on_reasoning,
        on_token=on_reasoning,
    )
    if generation_id:
        _spec_results[generation_id] = spec
    return spec


def cancel_background_spec(generation_id: str) -> None:
    """Cancel a pending background spec task (generation cancelled/abandoned)."""
    task = _spec_background_tasks.pop(generation_id, None)
    if task is not None and not task.done():
        task.cancel()
    _spec_results.pop(generation_id, None)
    _spec_event_queues.pop(generation_id, None)


async def planner_node(
    state: GenerationState,
    queue,
) -> GenerationState:
    """Planner Agent — REASON→ACT: 解析设计文档，输出 Task DAG."""
    logger.info("planner_node_start")

    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")
    reflect_count = state.get("planner_reflect_count", 0)
    code_feedback = state.get("code_feedback", "")
    architecture_spec = state.get("architecture_spec")

    # Tell the user planning started BEFORE any awaiting — otherwise the stage
    # entry (stage_start) is followed by long dead air while the Spec awaits.
    queue.put_nowait(_make_queue_event("planner_start", "code", {
        "phase": "planning",
        "message": "正在准备架构规格与任务规划...",
    }))

    # Spec consumption happens INSIDE the planner task — by the time this runs,
    # the frontend already shows the code stage ("规划中"), so the user never
    # waits on the confirm click. Uses the cached / background / sync chain.
    # Spec thinking is streamed to the AgentLog so the wait is visible.
    def on_spec_thinking(text: str):
        queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

    if not architecture_spec and state.get("analysis_result"):
        architecture_spec = await await_architecture_spec(
            state.get("generation_id"),
            analysis_result=state["analysis_result"],
            design_doc=design_doc,
            on_reasoning=on_spec_thinking,
        )

    # Resilience: a business-invalid Spec (e.g. empty placeholder fallback)
    # must NOT dead-end the pipeline — fall back to the prose design-doc path
    # so code generation still happens.
    if architecture_spec:
        from .spec_schema import validate_spec

        spec_problems = validate_spec(architecture_spec)
        if spec_problems:
            logger.warning(
                "planner_spec_invalid_fallback_to_prose",
                problems=spec_problems[:5],
            )
            architecture_spec = None

    user_prompt = build_planner_user_prompt(architecture_spec, design_doc, failure)

    # Self-review mode: user feedback replans against the project's ACTUAL
    # state — recovered files, last compile errors, failed tasks (injected by
    # the servicer on fresh-start). Any input goes through this same path; the
    # agent decides what needs doing. No keyword matching.
    if code_feedback:
        from .planner import build_feedback_planner_prompt
        from .state import resolve_project_root

        user_prompt = build_feedback_planner_prompt(
            design_doc=design_doc,
            generated_files=state.get("generated_files") or {},
            feedback_history=state.get("feedback_history"),
            code_feedback=code_feedback,
            project_root=resolve_project_root(
                state.get("generation_id"), state.get("requirement", ""),
            ),
        )

    # REASON + ACT: 一次性输出 DAG (planner_start already emitted at the top)
    def on_thinking(text: str):
        queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

    # The DAG JSON is LARGER than the Spec JSON (each task carries
    # files/contract/deps) AND thinking consumes budget — 16k gives both room
    # (8192 still truncated a 11-task DAG with thinking enabled). The
    # tolerant parser + truncated flag below handle any remaining truncation.
    raw_response = await _llm_generate(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_content=user_prompt,
        enable_thinking=True,
        max_tokens=16384,
        on_reasoning=on_thinking,
    )

    # Empty response (DeepSeek thinking can consume the whole budget, or the
    # API returns a transient empty completion) — same failure class as the
    # incremental replan. Retry once with a nudge; persistent emptiness falls
    # through to the existing fallback below instead of silently degrading to
    # a spec-fallback DAG on the first empty.
    if not raw_response.strip():
        logger.warning("planner_empty_retry gen=%s", state.get("generation_id"))
        queue.put_nowait(_make_queue_event("thinking_chunk", "code", {
            "text": "任务规划输出为空，重新生成完整任务列表...",
        }))
        raw_response = await _llm_generate(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_content=user_prompt + "\n\n注意：你上次的输出为空。请重新输出完整的 JSON 任务列表。",
            enable_thinking=True,
            max_tokens=16384,
            on_reasoning=on_thinking,
        )

    try:
        dag = extract_task_dag(raw_response)
        if dag.pop("truncated", False):
            # Output hit the token ceiling — a repaired tail is silently
            # INCOMPLETE (only the leading tasks survived). Never accept a
            # partial DAG quietly: retry once with an explicit completeness
            # hint (a second generation usually fits — the model has seen
            # the shape). Still truncated → keep the best result; the
            # final-compile repair loop replans whatever surfaces missing.
            logger.warning("planner_dag_truncated_retry gen=%s", state.get("generation_id"))
            queue.put_nowait(_make_queue_event("thinking_chunk", "code", {
                "text": "任务规划输出不完整（被截断），重新生成完整任务列表...",
            }))
            retry_prompt = (
                f"{user_prompt}\n\n"
                f"注意：你上次的输出被截断了（只输出了部分任务）。请重新输出【完整】的 JSON："
                f"包含全部任务，不要省略任何任务。"
            )
            raw_retry = await _llm_generate(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_content=retry_prompt,
                enable_thinking=True,
                max_tokens=16384,
                on_reasoning=on_thinking,
            )
            try:
                retry_dag = extract_task_dag(raw_retry)
                if not retry_dag.pop("truncated", False):
                    dag = retry_dag
                else:
                    dag = retry_dag  # still truncated — keep the fuller attempt
            except Exception:
                pass  # retry unusable — keep the truncated first result
    except Exception as e:
        logger.error("planner_extract_failed", error=str(e))
        # Spec-driven fallback — one business task per top-level directory
        # group from directory_tree. NEVER a hardcoded scaffold: the old
        # hardcoded qiankun/webpack template generated a project that
        # contradicted the Spec (Vite). Empty when no Spec — graph.py
        # surfaces the explicit "no tasks" error instead of a wrong project.
        from .planner import build_spec_fallback_dag

        dag = build_spec_fallback_dag(architecture_spec, design_doc)
        if not dag["tasks"]:
            logger.error("planner_fallback_empty spec_missing=%s", architecture_spec is None)

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
    state["generated_files"] = {}

    return state


async def run_incremental_replan(
    system_prompt: str,
    replan_prompt: str,
    max_tokens: int = 16384,
    retries: int = 1,
) -> dict:
    """Incremental replan LLM call — retry on empty/parse failure.

    DeepSeek thinking consumes the SAME max_tokens budget: the planner main
    path needs 16384, and so does this one — 4096 (the ``_llm_generate``
    default) lets reasoning eat the whole budget and the response comes back
    EMPTY, which ``extract_task_dag`` cannot parse and dead-ends generation.
    A single retry (with feedback) absorbs transient empty/invalid responses;
    bounded, so a persistently failing model surfaces as an explicit error
    (never a silent empty DAG).
    """
    last_raw = ""
    for attempt in range(retries + 1):
        raw = await _llm_generate(
            system_prompt=system_prompt,
            user_content=replan_prompt,
            enable_thinking=True,
            max_tokens=max_tokens,
        )
        last_raw = raw
        if not (raw or "").strip():
            if attempt < retries:
                replan_prompt += "\n\n注意：你上次的输出为空。请重新输出完整的 JSON 任务列表。"
                continue
            break
        try:
            return extract_task_dag(raw)
        except Exception:
            if attempt < retries:
                replan_prompt += (
                    "\n\n注意：你上次的输出不是合法 JSON，请只输出一个 JSON 对象。"
                    f"上次输出前 200 字：{(raw or '')[:200]}"
                )
                continue
            raise
    raise ValueError(f"增量重规划输出为空：{(last_raw or '')[:200]}")


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

    Compilation is at the LLM's own discretion: the executor never triggers
    compile_project automatically — the model calls it as a tool when it
    wants to verify, and the final full compile (graph Step 4) is the
    system-level gate after all tasks complete.
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

    # Design context: architecture spec fragments + design doc summary, so the
    # generated code stays aligned with the design (not just the task contract).
    spec_context = _build_executor_spec_context(state.get("architecture_spec"), task)
    design_doc = state.get("design_doc") or state.get("design_result", "")

    system_prompt = EXECUTOR_SYSTEM_PROMPT
    user_msg = (
        f"## 任务\n{task.get('description', '')}\n\n"
        f"## 需要生成的文件\n{json.dumps(files_to_generate, ensure_ascii=False)}\n\n"
        f"## 接口契约要求\n{json.dumps(contract, ensure_ascii=False)}"
        f"{deps_info}\n\n"
        f"{spec_context}"
        f"## 设计文档摘要\n{design_doc[:2000]}\n\n"
        f"开始生成。先调用 list_files 查看项目现状，然后调用 list_skills 了解可用模板。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    max_rounds = 12
    generated_files: dict[str, str] = {}
    compile_errors: list[dict] | None = None
    env_blocked = False  # environment error — skip LLM repair, fail task fast
    partial_paths: list[str] = []  # unresolved imports (deps of later tasks)

    from .tools.compile_tool import (
        ENV_ERROR_KIND,
        _env_error,
        classify_compile_errors,
        extract_missing_paths,
        is_env_error,
    )

    for round_idx in range(max_rounds):
        if env_blocked:
            break
        def on_thinking(text: str):
            queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

        try:
            response = await _llm_generate_with_tools_streaming(
                messages=messages,
                tools=registry.get_schema(),
                model="deepseek-v4-pro",
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

                # Bound per tool call: the env-error check below reads `errors`
                # even for non-compile tools — a failing FIRST tool call (e.g.
                # LLM hallucinated a tool name → registry ok=False + error)
                # must not crash with UnboundLocalError before any assignment.
                errors: list[dict] = []

                queue.put_nowait(_make_queue_event("tool_call", "code", {
                    "tool": tool_name,
                    "args": tool_args,
                    "task_id": task_id,
                }))

                if not tool_name:
                    # Empty tool name (broken streamed delta that survived
                    # aggregation) — never invoke "" (registry would fail as
                    # "Unknown tool" and sink the task via the env path). Tell
                    # the LLM the call was invalid so it can retry properly.
                    messages.append({"role": "assistant", "content": None, "tool_calls": [tc],
                                     "reasoning_content": response.get("reasoning_content")})
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": json.dumps(
                                         {"ok": False, "data": {}, "error": "工具名为空(模型输出异常),请重新调用"},
                                         ensure_ascii=False)})
                    continue

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
                    if tool_name == "write_code" and content:
                        generated_files[path] = content
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

                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        fpath = f["path"]
                        fcontent = f["content"]
                        import os as _os
                        _os.makedirs(_os.path.dirname(_os.path.join(project_root, fpath)), exist_ok=True)
                        with open(_os.path.join(project_root, fpath), "w", encoding="utf-8") as wf:
                            wf.write(fcontent)
                        # Emit file events so the frontend preview receives
                        # skill-generated files too (was a blind spot before —
                        # preview bundling missed them → partial/empty builds).
                        if fpath not in generated_files:
                            generated_files[fpath] = fcontent
                        queue.put_nowait(_make_queue_event("file_start", "code", {"path": fpath}))
                        chunk_size = 200
                        for i in range(0, len(fcontent), chunk_size):
                            queue.put_nowait(_make_queue_event("file_chunk", "code", {
                                "path": fpath,
                                "content": fcontent[i:i + chunk_size],
                                "chunk_index": i // chunk_size,
                                "is_last_chunk_for_file": (i + chunk_size >= len(fcontent)),
                            }))
                        queue.put_nowait(_make_queue_event("file_complete", "code", {"path": fpath}))

                elif tool_name == "compile_project":
                    data = result.data or {}
                    errors = data.get("errors", []) if not result.ok else []
                    compile_errors = errors if not result.ok else None
                    # Partial: unresolved imports of files not generated yet.
                    # Record which paths were missing — graph.py checks whether
                    # they're planned by ANY task; if not, it's a planning gap
                    # → incremental replan (not a silent "all good").
                    if data.get("partial"):
                        for p in data.get("partial_paths", []):
                            p_clean = p.lstrip("./")
                            if p_clean and p_clean not in partial_paths:
                                partial_paths.append(p_clean)
                    queue.put_nowait(_make_queue_event("compile_status", "code", {
                        "ok": result.ok,
                        "errors": errors,
                        "task_id": task_id,
                    }))

                    # Environment errors (worker unreachable / missing dir /
                    # empty project) have no code to fix — do NOT feed them
                    # into the LLM repair loop (it would burn rounds rewriting
                    # valid files). Retry briefly; if still broken, fail the
                    # task so the dependency gate / planner reflect handles it.
                    if errors and all(is_env_error(e) for e in errors):
                        for attempt in range(2):
                            await asyncio.sleep(1.0)
                            # Retry at the same level the LLM asked for — no
                            # forced mode override (compile timing/mode is the
                            # model's own decision).
                            retry = await registry.invoke("compile_project", {"full": tool_args.get("full", False)})
                            if retry.ok:
                                compile_errors = None
                                queue.put_nowait(_make_queue_event("compile_status", "code", {
                                    "ok": True, "errors": [], "task_id": task_id,
                                }))
                                break
                            errors = retry.data.get("errors", []) if not retry.ok else []
                            compile_errors = errors
                        else:
                            logger.warning(
                                "executor_env_error_task_failed",
                                task_id=task_id, errors=[e.get("message") for e in errors][:3],
                            )
                            env_blocked = True

                messages.append({"role": "assistant", "content": None, "tool_calls": [tc],
                                 "reasoning_content": response.get("reasoning_content")})
                # Worker unreachable or empty project — explicit failure
                if not result.ok and not errors and result.error:
                    compile_errors = [_env_error(result.error)]
                    queue.put_nowait(_make_queue_event("compile_status", "code", {
                        "ok": False, "errors": compile_errors, "task_id": task_id,
                    }))
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                    "content": json.dumps({"ok": result.ok, "data": result.data, "error": result.error},
                    ensure_ascii=False)})

        elif response.get("content"):
            content = response["content"]
            messages.append({"role": "assistant", "content": content})
            # The agent's own words, streamed verbatim — the dialogue surface.
            # Internal markers and blank text never reach the UI.
            text = content.replace("__TASK_DONE__", "").strip()
            if text:
                queue.put_nowait(_make_queue_event("agent_message", "code", {
                    "text": text,
                    "task_id": task_id,
                }))
            if "__TASK_DONE__" in content:
                break

        # No automatic compile trigger here — compile timing is at the LLM's
        # own discretion (compile_project tool). The system-wide full compile
        # runs in graph Step 4 after ALL tasks complete.

    # Build summary
    summary = f"Task {task_id} done: {len(generated_files)} files"
    compile_err_count = len(compile_errors) if compile_errors else 0
    failure_kind = "done"
    missing_paths: list[str] = []
    if compile_errors:
        failure_kind = classify_compile_errors(compile_errors)
        if failure_kind == "missing_file":
            missing_paths = extract_missing_paths(compile_errors)

    queue.put_nowait(_make_queue_event("task_complete", "code", {
        "task_id": task_id,
        "summary": summary,
        "file_count": len(generated_files),
        "compile_errors": compile_err_count,
        "failure_kind": failure_kind,
    }))

    return {
        "task_id": task_id,
        "status": "done" if not compile_errors else "failed",
        "generated_files": generated_files,
        "compile_errors": compile_errors,
        "summary": summary,
        "failure_kind": failure_kind,
        "missing_paths": missing_paths,
        "partial_paths": partial_paths,
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
        # All good — event carries only the decision; the frontend renders
        # the status card text (backend events have zero voice).
        queue.put_nowait(_make_queue_event("planner_reflect", "code", {
            "decision": "done",
        }))
        state["context_summary"] = context_summary
        state["stage_phase"] = "complete"
        return state

    if all_done and failed_tasks:
        # Classify failures — three tiers:
        #   missing_file  → PLANNING gap (imports a file no task produces):
        #                   files enter the replan pool immediately.
        #   code/env      → first failure: retry once (same executor, its
        #                   message history intact — fixes slips). Still
        #                   failing after the retry: the retried executor's
        #                   context is exhausted (12 rounds), repeating it
        #                   won't converge — hand the task's OWN files to the
        #                   incremental planner so a FRESH task/executor
        #                   regenerates them with a clean context.
        missing_paths: list[str] = []
        retryable: list[dict] = []
        replan_files: list[str] = []
        for t in failed_tasks:
            kind = t.get("failure_kind") or "code"
            if kind == "missing_file":
                missing_paths.extend(t.get("missing_paths") or [])
            elif t.get("retry_count", 0) >= 1:
                replan_files.extend(t.get("files") or [])
            else:
                retryable.append(t)

        retryable_ids = {t["id"] for t in retryable}

        # Merge retried-but-failing tasks' files into the replan pool
        if replan_files:
            missing_paths.extend(replan_files)
        if missing_paths:
            # Dedup, keep order
            seen: set[str] = set()
            missing_paths = [p for p in missing_paths if not (p in seen or seen.add(p))]
            state["replan_request"] = {
                "missing_files": missing_paths,
                "failed_task_ids": [t["id"] for t in failed_tasks],
            }
            queue.put_nowait(_make_queue_event("planner_reflect", "code", {
                "decision": "replan_missing_files",
                "missing_files": missing_paths,
                "failed_task_ids": [t["id"] for t in failed_tasks],
            }))

        if retryable:
            queue.put_nowait(_make_queue_event("planner_reflect", "code", {
                "decision": "has_failures",
                "failed_task_ids": sorted(retryable_ids),
            }))
            # Replan-covered tasks (missing_file, retried-once) stay failed;
            # first-time code/env failures reset to pending with retry_count
            # incremented — one retry, then the replan pool takes over.
            for t in dag.get("tasks", []):
                if t.get("status") == "failed" and t.get("id") in retryable_ids:
                    t["status"] = "pending"
                    t["compile_errors"] = None
                    t["retry_count"] = t.get("retry_count", 0) + 1

        state["planner_reflect_count"] = state.get("planner_reflect_count", 0) + 1
        state["context_summary"] = context_summary
        return state

    state["context_summary"] = context_summary
    return state


def _build_executor_spec_context(spec: dict | None, task: dict) -> str:
    """Serialize the Spec sections relevant to a task into the Executor prompt.

    Sections: component_tree / pages / data_model / api_contracts (+ the task's
    files). The task's own contract is already in the prompt; these fragments
    give the Executor the design intent behind the contract.
    """
    if not spec:
        return ""
    sections = []
    for key in ("component_tree", "pages", "data_model", "api_contracts"):
        value = spec.get(key)
        if value:
            sections.append(f"### {key}\n{json.dumps(value, ensure_ascii=False, indent=2)}")
    # Attach the task's own files to pages/component tree context implicitly —
    # the full fragments above already cover them. Keep the block compact.
    return f"## 架构 Spec 相关片段（设计意图，代码必须与此一致）\n" + "\n".join(sections) + "\n\n"


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
    model: str = "deepseek-v4-pro",
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
            # Assistant message with tool_calls — the STANDARD OpenAI payload
            # field. (Previously serialized into content; DeepSeek strictly
            # requires the real tool_calls field to see the calls.) The prior
            # round's reasoning_content must be passed back verbatim in
            # thinking mode (DeepSeek 400 without it).
            provider_messages.append(Message(
                role=m.get("role", "assistant"),
                content=content or "",
                tool_calls=tc_list,
                reasoning_content=m.get("reasoning_content"),
            ))
        else:
            provider_messages.append(Message(
                role=m.get("role", "user"),
                content=content or "",
                tool_call_id=m.get("tool_call_id"),
            ))

    # DeepSeek reasoning models consume thinking tokens from the SAME
    # max_tokens budget — 4096 left too little for "think + write file
    # content", forcing the model into tiny (query-only) actions. Generous
    # budget so a write_code round survives its own reasoning.
    config = LLMConfig(enable_thinking=True, max_tokens=8192, tools=tools)

    # Collect response
    full_content = ""
    full_reasoning = ""
    tool_calls_list: list[dict] = []
    current_tool_call: dict | None = None

    async for event in _provider.stream_generate(model, provider_messages, config):
        if isinstance(event, TokenEvent):
            full_content += event.text
        elif isinstance(event, ReasoningEvent):
            if on_thinking:
                on_thinking(event.text)
            # 累积思考内容 — DeepSeek 思考模式要求把上一轮的 reasoning_content
            # 原样回传(否则 400 "reasoning_content must be passed back")
            full_reasoning += event.text
        elif isinstance(event, ToolCallEvent):
            # Accumulate tool call deltas. OpenAI-compatible streams put the
            # id/name on the FIRST chunk of an index; later chunks often carry
            # ONLY arguments (no id). An id-less chunk CONTINUES the current
            # call — opening a new entry on it produced empty-named tool
            # invocations (`tool: ""` → unknown tool → task failure). A
            # late-arriving name fills the current call.
            if current_tool_call and (event.call_id == current_tool_call.get("id") or not event.call_id):
                if event.arguments:
                    current_tool_call["function"]["arguments"] += event.arguments
                if event.name and not current_tool_call["function"].get("name"):
                    current_tool_call["function"]["name"] = event.name
            else:
                if current_tool_call:
                    tool_calls_list.append(current_tool_call)
                current_tool_call = {
                    "id": event.call_id or "",
                    "type": "function",  # OpenAI 标准字段 — DeepSeek 严格校验(400 missing field `type`)
                    "function": {
                        "name": event.name or "",
                        "arguments": event.arguments or "",
                    },
                }
        elif isinstance(event, CompleteEvent):
            if current_tool_call:
                tool_calls_list.append(current_tool_call)

    if tool_calls_list:
        return {"content": None, "tool_calls": tool_calls_list,
                "reasoning_content": full_reasoning or None}

    return {"content": full_content.strip(), "tool_calls": None,
            "reasoning_content": full_reasoning or None}


# ---- Multi-Agent Review Node ----

REVIEW_AGENTS = {
    "security": {
        "name": "安全审查",
        "icon": "\U0001f512",
        "system_prompt": (
            "你是前端安全专家。审查以下代码的安全问题：\n"
            "1. XSS 风险（v-html、innerHTML、未转义用户输入）\n"
            "2. 敏感数据暴露（API key、token、密码明文字段）\n"
            "3. CSRF 防护缺失\n"
            "4. 不安全的路由守卫\n"
            '输出 JSON: {"issues": [{"severity": "critical|high|medium|low", "file": "...", "line": 0, "title": "...", "description": "...", "fix": "..."}]}'
        ),
    },
    "performance": {
        "name": "性能分析",
        "icon": "⚡",
        "system_prompt": (
            "你是前端性能专家。审查以下代码的性能问题：\n"
            "1. 不必要的重渲染（computed/watch 滥用）\n"
            "2. 大列表未虚拟滚动\n"
            "3. 图片/资源未懒加载\n"
            "4. 打包体积过大风险\n"
            '输出 JSON: {"issues": [...]}'
        ),
    },
    "accessibility": {
        "name": "可访问性",
        "icon": "♿",
        "system_prompt": (
            "你是 Web 可访问性专家。审查代码的 A11y 问题：\n"
            "1. ARIA 属性缺失或错误\n"
            "2. 键盘导航不完整\n"
            "3. 颜色对比度不足\n"
            "4. 屏幕阅读器兼容性\n"
            '输出 JSON: {"issues": [...]}'
        ),
    },
    "maintainability": {
        "name": "可维护性",
        "icon": "\U0001f9e9",
        "system_prompt": (
            "你是代码质量专家。审查可维护性问题：\n"
            "1. 组件过大（>300 行）\n"
            "2. 重复代码\n"
            "3. 硬编码魔法数字\n"
            "4. 类型定义缺失或不完整\n"
            '输出 JSON: {"issues": [...]}'
        ),
    },
}


def _build_review_html(agent_results: list[dict], all_issues: list[dict]) -> str:
    """Build merged HTML review report."""
    issue_html = ""
    for issue in all_issues:
        sev_color = {"critical": "#dc2626", "high": "#ea580c", "medium": "#ca8a04", "low": "#2563eb"}
        color = sev_color.get(issue.get("severity", "low"), "#6b7280")
        issue_html += f"""
        <div style="border-left: 4px solid {color}; margin: 8px 0; padding: 8px 12px; background: #f9fafb;">
          <strong>[{issue.get('severity', '?').upper()}] {issue.get('title', 'Issue')}</strong>
          <br><small>{issue.get('file', '?')}:{issue.get('line', 0)}</small>
          <p>{issue.get('description', '')}</p>
          <p><strong>修复建议:</strong> {issue.get('fix', 'N/A')}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>质量评审报告</title>
<style>body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
h2 {{ margin-top: 24px; }}
.agent {{ margin: 12px 0; padding: 12px; border-radius: 8px; background: #f3f4f6; }}
.passed {{ color: #16a34a; }} .failed {{ color: #dc2626; }}</style></head>
<body>
<h1>🔍 质量评审报告</h1>
<p>审查维度：安全 · 性能 · 可访问性 · 可维护性</p>
<p>共发现 <strong>{len(all_issues)}</strong> 个问题</p>
{issue_html}
</body></html>"""


async def _run_single_agent(agent_key: str, agent_def: dict, design_doc: str, code_context: str) -> dict:
    """Run a single review agent."""
    try:
        raw = await _llm_generate_structured(
            system_prompt=agent_def["system_prompt"],
            user_content=f"## 设计方案\n{design_doc[:3000]}\n\n## 代码\n{code_context[:8000]}",
            output_schema={"issues": []},
        )
        return {
            "agent_key": agent_key,
            "name": agent_def["name"],
            "icon": agent_def["icon"],
            "issues": raw.get("issues", []),
        }
    except Exception as e:
        logger.error("review_agent_error", agent=agent_key, error=str(e))
        return {
            "agent_key": agent_key,
            "name": agent_def["name"],
            "icon": agent_def["icon"],
            "issues": [],
            "error": str(e),
        }


async def review_node(state: GenerationState) -> GenerationState:
    """多 Agent 并行审查 → 合并 HTML 报告."""

    files = state.get("generated_files", {})
    design_doc = state.get("design_doc") or state.get("design_result", "")

    code_context = "\n\n".join(
        f"### {path}\n```\n{content[:2000]}\n```" if len(content) > 2000
        else f"### {path}\n```\n{content}\n```"
        for path, content in files.items()
    )

    if not code_context and state.get("code_result"):
        code_context = state["code_result"][:8000]

    # Run 4 agents in parallel
    tasks = [
        _run_single_agent(key, agent_def, design_doc, code_context)
        for key, agent_def in REVIEW_AGENTS.items()
    ]
    agent_results = await asyncio.gather(*tasks)

    # Collect all issues
    all_issues = []
    for ar in agent_results:
        all_issues.extend(ar.get("issues", []))

    critical = [i for i in all_issues if i.get("severity") == "critical"]
    passed = len(critical) == 0

    if not passed:
        severity = "critical"
        rollback_target = "code"
    elif all_issues:
        severity = "moderate"
        rollback_target = "code"
    else:
        severity = None
        rollback_target = ""

    report_html = _build_review_html(agent_results, all_issues)

    fix_instruction = None
    if all_issues:
        issues_text = "\n".join(
            f"- [{i.get('severity', '?')}] {i.get('file', '?')}:{i.get('line', 0)} — {i.get('title', '')} → {i.get('fix', '')}"
            for i in all_issues[:20]
        )
        fix_instruction = f"审查发现 {len(all_issues)} 个问题需要修复：\n{issues_text}"

    return {
        **state,
        "review_agent_results": agent_results,
        "review_report_html": report_html,
        "review_issues": all_issues,
        "review_passed": passed,
        "review_severity": severity,
        "review_result": f"Found {len(all_issues)} issues, {len(critical)} critical",
        "failure_details": {
            "source": "review",
            "failed_items": all_issues,
            "instruction": fix_instruction or "",
            "rollback_target": rollback_target,
        } if all_issues else None,
        "stage_phase": "complete",
    }


# ---- E2E Node (two-phase) ----

E2E_CASES_PROMPT = """你是一个资深 QA 测试工程师。根据需求文档和生成的代码，编写 E2E 自动化测试用例。

## 输出格式（Markdown）
# E2E 测试用例

## TC-001: 用例名称
- **前置条件**: ...
- **测试步骤**:
  1. 打开页面
  2. 点击某个按钮
  3. 验证结果
- **预期结果**: ...

## TC-002: ...

## 规则
- 每个用例测试一个功能点
- 用例需覆盖核心用户流程
- 步骤用自然语言描述
- 输出纯 Markdown，不要 JSON 包裹"""


async def e2e_node(state: GenerationState) -> GenerationState:
    """E2E 节点 — 两阶段：生成测试用例 → 用户确认 → 自动执行."""

    e2e_confirmed = state.get("e2e_user_confirmed", False)

    if not e2e_confirmed:
        # Phase 1: Generate test cases MD
        logger.info("e2e_phase1_generate_cases")

        requirement = state.get("analysis_result", "")
        generated_files = state.get("generated_files", {})

        code_summary = "\n".join(f"- {path}" for path in generated_files.keys())

        user_prompt = (
            f"## 需求文档\n{requirement[:5000]}\n\n"
            f"## 生成的文件列表\n{code_summary}\n\n"
            f"请根据以上信息编写 E2E 测试用例。"
        )

        test_cases_md = await _llm_generate(
            system_prompt=E2E_CASES_PROMPT,
            user_content=user_prompt,
        )

        return {
            **state,
            "e2e_test_cases_md": test_cases_md,
            "stage_phase": "reviewing",
        }

    else:
        # Phase 2: Execute tests (pass-through to frontend)
        logger.info("e2e_phase2_execute")
        return {
            **state,
            "stage_phase": "complete",
            "e2e_test_cases": state.get("e2e_test_cases", []),
        }
