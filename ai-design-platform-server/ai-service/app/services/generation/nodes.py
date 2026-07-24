# ai-design-platform-server/ai-service/app/services/generation/nodes.py
import asyncio
import json
from typing import Any

import structlog

from ..llm.provider import LLMConfig, LLMProvider, ReasoningEvent, TokenEvent, Message, ToolCallEvent, CompleteEvent
from .state import GenerationState
from .harness import EvalHarness

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


async def _llm_generate_structured(
    system_prompt: str,
    user_content: str,
    output_schema: dict[str, Any],
    model: str = "glm-5.2",
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

    return state


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
- 工具调用格式: {"tool_calls": [{"id": "call_N", "function": {"name": "...", "arguments": "{\\"key\\": \\"value\\"}"}}]}"""


async def code_node(state: GenerationState) -> GenerationState:
    """代码生成节点 — 工具增强的迭代式工程生成."""
    logger.info("code_node_start")

    import tempfile
    import os as _os

    project_root = _os.path.join(
        tempfile.gettempdir(),
        "ai-gen",
        state.get("requirement", "project")[:20].replace(" ", "_"),
    )

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

    import tempfile, os as _os, json as _json, re

    _raw_name = state.get("requirement", "project")[:30]
    _safe_name = re.sub(r'[^\w]', '_', _raw_name)[:30].strip('_') or "ai-gen-project"
    project_root = _os.path.join(tempfile.gettempdir(), "ai-gen", _safe_name)

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
