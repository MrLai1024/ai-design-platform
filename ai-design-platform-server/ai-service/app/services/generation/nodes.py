# ai-design-platform-server/ai-service/app/services/generation/nodes.py
import json
from typing import Any

import structlog

from ..llm.provider import LLMConfig, LLMProvider, ReasoningEvent, TokenEvent
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
    enable_thinking: bool = False,
) -> str:
    """Call LLM and collect full response as string.

    By default disables thinking mode — the analysis/design/review prompts
    already instruct the model to produce structured output, and enabling
    thinking can cause the model to emit all content as reasoning_content
    with an empty content field.
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
        elif isinstance(event, ReasoningEvent):
            # GLM may emit content as reasoning even with thinking disabled;
            # collect it as fallback to avoid empty responses
            full_text += event.text
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

    requirement = state.get("requirement", "")
    messages = state.get("messages", [])

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
        "qa_rounds": 1,
    }


# Remove old helper functions — no longer needed
# _emit_requirements_state, _handle_prd_generation, _user_wants_prd, _strategist, etc.


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
    check = EvalHarness.validate(state, "design")
    if not check.passed:
        logger.warning("design_validation_failed", errors=check.errors)

    return state


# ---- Code Node ----

CODE_SYSTEM_PROMPT = """你是一个资深 Vue 3 全栈工程师。根据设计方案生成完整的 Vue 3 单文件组件代码。

## 要求
- 使用 Composition API (`<script setup lang="ts">`)
- 使用 {component_lib} 组件库
- 代码必须有完整的 <template>、<script setup>、<style scoped>
- 一个 .vue 文件包含所有逻辑，不要拆分多个文件
- 确保代码可以直接运行

## 输出格式
```vue
<template>
  ...
</template>

<script setup lang="ts">
...
</script>

<style scoped>
...
</style>
```"""


async def code_node(state: GenerationState) -> GenerationState:
    """代码生成节点：产出 Vue SFC 代码。"""
    logger.info("code_node_start")

    failure_details = state.get("failure_details")
    if failure_details:
        prompt = (
            f"设计方案：\n{state['design_result']}\n\n"
            f"之前的代码存在问题：\n{failure_details['instruction']}\n\n"
            f"请修复代码，确保通过校验。"
        )
    else:
        prompt = f"设计方案：\n{state['design_result']}"

    lib = state.get("component_lib", "tailwind")
    result = await _llm_generate(
        system_prompt=CODE_SYSTEM_PROMPT.replace("{component_lib}", lib),
        user_content=prompt,
    )

    state["code_result"] = result
    check = EvalHarness.validate(state, "code")
    if not check.passed:
        logger.warning("code_validation_failed", errors=check.errors)

    return state


# ---- Review Node ----

REVIEW_SYSTEM_PROMPT = """你是一个资深前端代码审查专家。审查生成的代码是否匹配设计方案。

## 审查维度
1. **设计匹配度**: 代码是否完整实现了设计方案中的所有功能模块
2. **边界情况**: 错误处理、空状态、加载状态是否覆盖
3. **代码规范**: 命名是否清晰、组件职责是否单一
4. **可维护性**: 代码是否易于理解和修改

## 输出格式（JSON）
{
  "passed": true/false,
  "severity": "minor" | "moderate" | "critical",
  "issues": [
    {
      "dimension": "设计匹配度 | 边界情况 | 代码规范 | 可维护性",
      "description": "问题描述",
      "suggestion": "修改建议"
    }
  ],
  "summary": "一句话总结审查结果"
}

## severity 定义
- minor: 代码规范问题，不影响功能（如变量命名）
- moderate: 结构性代码问题（如缺少错误处理、组件拆分不合理）
- critical: 设计层面缺陷（如缺少关键功能模块、数据流不匹配）"""


async def review_node(state: GenerationState) -> GenerationState:
    """语义校验节点：LLM 审查代码质量。"""
    logger.info("review_node_start")

    result = await _llm_generate_structured(
        system_prompt=REVIEW_SYSTEM_PROMPT,
        user_content=(
            f"## 设计方案\n{state['design_result']}\n\n"
            f"## 生成的代码\n{state['code_result']}"
        ),
        output_schema={
            "passed": False,
            "severity": "minor",
            "issues": [
                {"dimension": "代码规范", "description": "...", "suggestion": "..."}
            ],
            "summary": "...",
        },
    )

    passed = result.get("passed", False)
    severity = result.get("severity", "minor")
    issues = result.get("issues", [])

    if passed:
        return {
            **state,
            "review_passed": True,
            "review_severity": None,
            "review_result": result.get("summary", ""),
            "failure_details": None,
        }

    issues_text = "\n".join(
        f"- [{i['dimension']}] {i['description']} → {i['suggestion']}"
        for i in issues
    )

    return {
        **state,
        "review_passed": False,
        "review_severity": severity,
        "review_result": result.get("summary", ""),
        "failure_details": {
            "source": "review",
            "failed_items": issues,
            "instruction": f"审查发现以下问题需要修复：\n{issues_text}",
            "rollback_target": "design" if severity == "critical" else "code",
        },
    }


# ---- E2E Node ----

E2E_SYSTEM_PROMPT = """你不需要做任何事。E2E 测试用例已在需求分析阶段生成。
本节点只负责将测试用例发送到前端执行，并等待结果。"""


async def e2e_node(state: GenerationState) -> GenerationState:
    """E2E 节点：将测试用例发送给前端执行，收集结果。

    注意：这个函数在 LangGraph 中运行，但不直接调用 Playwright。
    测试执行在浏览器的预览 iframe 中完成。
    本节点通过 GraphEvent 向前端发送执行指令。
    """
    logger.info("e2e_node_start")

    test_cases = state.get("e2e_test_cases", [])
    if not test_cases:
        raise ValueError(
            "E2E node reached with no test cases — analysis stage may have failed"
        )

    # Results are collected by the GraphRunner which sends e2e_execute
    # events and waits for HTTP callbacks from the frontend
    return state
