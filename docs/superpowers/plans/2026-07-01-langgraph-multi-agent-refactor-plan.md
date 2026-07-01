# LangGraph 多 Agent 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将多 Agent 编排从前端手动状态机迁移到 Python 后端 LangGraph StateGraph，实现五节点流水线（analysis → design → code → review → e2e）+ 条件回流 + Harness/Loop Engine 工程实践。

**Architecture:** LangGraph StateGraph 在 Python AI 服务中运行，通过 gRPC 流式推送节点状态变更事件。Go Gateway 将这些事件转为 SSE 推送给前端。前端简化为纯展示 + 人工介入触发 + E2E 预览区执行引擎。E2E 测试用例在 analysis 阶段生成，code 完成后在预览 iframe 中执行。

**Tech Stack:** Python 3.12+ (LangGraph, grpcio), Go (Gin, gRPC client), Vue 3 + TypeScript (Pinia, composables)

**Spec:** `docs/superpowers/specs/2026-07-01-langgraph-multi-agent-refactor-design.md`

---

## 文件结构

```
ai-design-platform-server/
├── proto/ai/v1/
│   └── generation.proto          # [改] 新增 GraphEvent 消息类型
├── gen/                          # [重新生成] proto 桩代码
├── ai-service/app/
│   ├── services/generation/
│   │   ├── servicer.py           # [改] 接入 LangGraph app
│   │   ├── graph.py              # [新] StateGraph 定义 + 节点注册 + 条件边
│   │   ├── nodes.py              # [新] 五个节点的实现
│   │   ├── harness.py            # [新] AgentHarness / LoopControl / EvalHarness
│   │   └── state.py              # [新] GenerationState TypedDict
│   └── services/llm/
│       └── provider.py           # [改] 支持结构化输出（JSON mode）
├── gateway/internal/
│   ├── handler/
│   │   ├── generation_sse.go     # [新] Graph SSE 事件转发处理器
│   │   └── e2e.go               # [新] E2E 结果回报接口
│   └── client/
│       └── ai.go                 # [改] 新增 GraphStream 调用

ai-design-platform-web/packages/ai-generation-app/src/
├── types/
│   └── generation.ts             # [改] 新增 Stage/E2E 类型定义
├── stores/
│   └── generation.ts             # [改] 扩展 state 支持五节点 + E2E
├── composables/
│   ├── useMultiAgent.ts          # [重写] 简化为 SSE 事件监听 + 状态同步
│   ├── useStreamChat.ts          # [改] 扩展 SSE 事件解析
│   ├── useE2ERunner.ts           # [新] 预览区 E2E 执行引擎
│   └── useStagePrompts.ts        # [删] prompt 模板移至后端
├── components/
│   ├── StepProgress.vue          # [改] 五节点进度条 + 回流动画
│   ├── E2EPanel.vue              # [新] E2E 测试用例列表 + 结果展示
│   └── ChatPanel.vue             # [改] 适配新的事件驱动模式
└── views/
    └── GenerationView.vue        # [改] 布局调整 + E2E 面板集成
```

---

## Phase 1: LangGraph 核心后端化

### Task 1: 定义 GenerationState 和扩展 Proto

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/state.py`
- Create: `ai-design-platform-server/ai-service/app/services/generation/__init__.py`
- Modify: `ai-design-platform-server/proto/ai/v1/generation.proto`

- [ ] **Step 1: 创建 GenerationState TypedDict**

```python
# ai-design-platform-server/ai-service/app/services/generation/state.py
from typing import TypedDict, Literal, NotRequired


class E2ETestStep(TypedDict):
    action: str          # 'click' | 'input' | 'assert' | 'wait'
    target: str          # CSS selector
    value: str | None    # input value / expected text / wait ms
    description: str


class E2ETestCase(TypedDict):
    id: str
    name: str
    description: str
    steps: list[E2ETestStep]


class E2ECaseResult(TypedDict):
    case_id: str
    passed: bool
    error: str | None
    screenshot: str | None


class FailureDetails(TypedDict):
    source: Literal["review", "e2e"]
    failed_items: list[dict]
    instruction: str
    rollback_target: Literal["code", "design"]


class RollbackRecord(TypedDict):
    rollback_id: str
    from_node: str
    to_node: str
    reason: str
    previous_output_hash: str
    token_cost: int


class GenerationState(TypedDict):
    # User input
    requirement: str
    component_lib: str
    messages: list[dict]

    # Stage outputs
    analysis_result: str | None
    design_result: str | None
    code_result: str | None
    review_result: str | None
    e2e_results: list[E2ECaseResult] | None

    # E2E test cases (generated in analysis)
    e2e_test_cases: list[E2ETestCase] | None

    # Review status
    review_passed: bool
    review_severity: str | None   # "minor" | "moderate" | "critical"

    # E2E status
    e2e_passed: bool

    # Failure details for rollback
    failure_details: FailureDetails | None

    # Loop control
    rollback_records: list[RollbackRecord]
    rollback_count: dict[str, int]
    max_rollback_per_node: int
    max_rollback_total: int
    needs_manual_review: bool
```

- [ ] **Step 2: 确认 `__init__.py` 存在**

```python
# ai-design-platform-server/ai-service/app/services/generation/__init__.py
# (empty file — package marker)
```

- [ ] **Step 3: 扩展 Proto 添加 GraphEvent 消息**

In `proto/ai/v1/generation.proto`, after the existing `GenerateResponse` message, add:

```protobuf
message GraphEvent {
  string event_type = 1;    // "stage_start" | "stage_complete" | "stage_rollback"
                            // | "e2e_execute" | "e2e_case_result" | "e2e_complete"
                            // | "human_confirm_required" | "loop_warning" | "loop_break"
  string stage = 2;         // "analysis" | "design" | "code" | "review" | "e2e"
  string data = 3;          // JSON-encoded payload (varies by event_type)
}

// Add to GenerateResponse oneof:
// GraphEvent graph_event = 5;
```

Edit the `GenerateResponse` message to include:

```protobuf
message GenerateResponse {
  oneof payload {
    Token token = 1;
    ToolCall tool_call = 2;
    GenerationComplete complete = 3;
    GenerationError error = 4;
    GraphEvent graph_event = 5;  // NEW
  }
}
```

- [ ] **Step 4: 重新生成 proto 桩代码**

Run:
```bash
cd ai-design-platform-server
# Regenerate Go stubs
protoc --go_out=gen/go --go_opt=paths=source_relative \
       --go-grpc_out=gen/go --go-grpc_opt=paths=source_relative \
       proto/ai/v1/generation.proto
# Regenerate Python stubs
python -m grpc_tools.protoc -Iproto \
       --python_out=gen/python --grpc_python_out=gen/python \
       proto/ai/v1/generation.proto
```

- [ ] **Step 5: Commit**

```bash
git add ai-service/app/services/generation/state.py \
        ai-service/app/services/generation/__init__.py \
        proto/ai/v1/generation.proto gen/
git commit -m "feat: add GenerationState TypedDict and GraphEvent proto message"
```

---

### Task 2: 实现 AgentHarness 执行壳

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/harness.py`

- [ ] **Step 1: 创建 harness.py — Tracer**

```python
# ai-design-platform-server/ai-service/app/services/generation/harness.py
import uuid
import hashlib
import json
import time
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Any
import structlog

from .state import GenerationState, RollbackRecord

logger = structlog.get_logger()


@dataclass
class TraceSpan:
    trace_id: str
    node_name: str
    start_time: float = 0.0
    tokens_used: int = 0
    attributes: dict = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def record_error(self, error: Exception):
        self.attributes["error"] = str(error)


class Tracer:
    def __init__(self):
        self.spans: list[TraceSpan] = []

    def span(self, node_name: str) -> TraceSpan:
        span = TraceSpan(trace_id=str(uuid.uuid4()), node_name=node_name)
        self.spans.append(span)
        return span

    def summary(self) -> dict:
        total_tokens = sum(s.tokens_used for s in self.spans)
        total_time = sum(s.attributes.get("duration_ms", 0) for s in self.spans)
        return {
            "total_spans": len(self.spans),
            "total_tokens": total_tokens,
            "total_duration_ms": total_time,
            "spans": [
                {"node": s.node_name, "tokens": s.tokens_used, "trace_id": s.trace_id}
                for s in self.spans
            ],
        }
```

- [ ] **Step 2: 添加 AgentHarness 类**

```python
# Append to harness.py

@dataclass
class RetryConfig:
    max_retries: int = 3
    backoff: float = 2.0


class AgentHarness:
    """Standard execution shell for every LangGraph node."""

    def __init__(self):
        self.tracer = Tracer()
        self.retry_config = RetryConfig()

    async def execute(
        self,
        node_name: str,
        state: GenerationState,
        handler: Callable[[GenerationState], GenerationState],
    ) -> GenerationState:
        span = self.tracer.span(node_name)
        span.set_attribute("input_hash", self._hash_state(state))
        t0 = time.time()

        last_error = None
        for attempt in range(self.retry_config.max_retries):
            try:
                result = await handler(state)
                elapsed = (time.time() - t0) * 1000
                span.set_attribute("duration_ms", elapsed)
                span.set_attribute("attempts", attempt + 1)
                logger.info(
                    "node_complete",
                    node=node_name,
                    duration_ms=elapsed,
                    attempts=attempt + 1,
                )
                return result
            except Exception as e:
                last_error = e
                span.record_error(e)
                logger.warning(
                    "node_retry",
                    node=node_name,
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < self.retry_config.max_retries - 1:
                    await asyncio.sleep(self.retry_config.backoff ** attempt)

        logger.error("node_failed", node=node_name, error=str(last_error))
        raise last_error

    def _hash_state(self, state: GenerationState) -> str:
        raw = json.dumps(state, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    def get_summary(self) -> dict:
        return self.tracer.summary()
```

- [ ] **Step 3: 添加 LoopControl 收敛控制器**

```python
# Append to harness.py

class LoopControl:
    """Convergence controller — prevents infinite rollback loops."""

    def __init__(
        self,
        max_rollback_per_node: int = 3,
        max_rollback_total: int = 10,
    ):
        self.max_rollback_per_node = max_rollback_per_node
        self.max_rollback_total = max_rollback_total

    def should_rollback(
        self, target_node: str, state: GenerationState
    ) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        allowed=False means the loop should stop (circuit break).
        """
        counts = state.get("rollback_count", {})

        # Rule 1: per-node limit
        node_count = counts.get(target_node, 0)
        if node_count >= self.max_rollback_per_node:
            return False, f"Node '{target_node}' rollback limit ({self.max_rollback_per_node}) reached"

        # Rule 2: global limit
        total = sum(counts.values())
        if total >= self.max_rollback_total:
            return False, f"Global rollback limit ({self.max_rollback_total}) reached"

        # Rule 3: no-improvement check
        records = state.get("rollback_records", [])
        if len(records) >= 2:
            last_two = records[-2:]
            if last_two[0]["to_node"] == target_node and last_two[1]["to_node"] == target_node:
                if last_two[0]["previous_output_hash"] == last_two[1]["previous_output_hash"]:
                    return False, "No improvement detected in consecutive rollbacks to same node"

        return True, ""

    def record_rollback(
        self,
        from_node: str,
        to_node: str,
        reason: str,
        previous_output_hash: str,
        token_cost: int,
    ) -> RollbackRecord:
        return RollbackRecord(
            rollback_id=str(uuid.uuid4()),
            from_node=from_node,
            to_node=to_node,
            reason=reason,
            previous_output_hash=previous_output_hash,
            token_cost=token_cost,
        )

    def apply_rollback(
        self, state: GenerationState, record: RollbackRecord
    ) -> GenerationState:
        counts = state.get("rollback_count", {})
        target = record["to_node"]
        counts[target] = counts.get(target, 0) + 1

        records = list(state.get("rollback_records", []))
        records.append(record)

        return {
            **state,
            "rollback_count": counts,
            "rollback_records": records,
        }
```

- [ ] **Step 4: 添加 EvalHarness 确定性校验**

```python
# Append to harness.py

@dataclass
class CheckResult:
    passed: bool
    errors: list[str] = field(default_factory=list)


class EvalHarness:
    """Deterministic validation — no LLM involved."""

    @staticmethod
    def code_has_content(code: str | None) -> CheckResult:
        if not code or not code.strip():
            return CheckResult(False, ["Generated code is empty"])
        return CheckResult(True)

    @staticmethod
    def code_has_vue_template(code: str) -> CheckResult:
        """Check that generated code contains a <template> tag."""
        if "<template>" not in code:
            return CheckResult(False, ["Missing <template> in generated code"])
        return CheckResult(True)

    @staticmethod
    def design_has_sections(design: str | None) -> CheckResult:
        """Check that design doc has required sections."""
        if not design:
            return CheckResult(False, ["Design document is empty"])
        required = ["组件", "数据流", "样式"]
        missing = [s for s in required if s not in design]
        if missing:
            return CheckResult(False, [f"Design missing sections: {', '.join(missing)}"])
        return CheckResult(True)

    @staticmethod
    def validate(state: GenerationState, stage: str) -> CheckResult:
        """Run all checks for a given stage."""
        if stage == "code":
            code = state.get("code_result")
            r1 = EvalHarness.code_has_content(code)
            if not r1.passed:
                return r1
            return EvalHarness.code_has_vue_template(code)
        if stage == "design":
            return EvalHarness.design_has_sections(state.get("design_result"))
        return CheckResult(True)
```

- [ ] **Step 5: Commit**

```bash
git add ai-service/app/services/generation/harness.py
git commit -m "feat: add AgentHarness, LoopControl, and EvalHarness"
```

---

### Task 3: 实现五个 LangGraph 节点

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 创建 nodes.py — LLM Provider 封装和辅助函数**

```python
# ai-design-platform-server/ai-service/app/services/generation/nodes.py
import json
import uuid
from typing import AsyncIterator

import structlog

from ..llm.provider import LLMProvider
from ..llm.router import resolve_provider
from .state import GenerationState, E2ETestCase
from .harness import EvalHarness

logger = structlog.get_logger()

# Provider singleton (replaced per request via set_provider)
_provider: LLMProvider | None = None


def set_provider(provider: LLMProvider):
    global _provider
    _provider = provider


async def _llm_generate(
    system_prompt: str,
    user_content: str,
    model: str = "glm-5.2",
) -> str:
    """Call LLM and collect full response as string."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    full_text = ""
    async for event in _provider.stream_generate(model, messages):
        if hasattr(event, "text"):
            full_text += event.text
    return full_text


async def _llm_generate_structured(
    system_prompt: str,
    user_content: str,
    output_schema: dict,
    model: str = "glm-5.2",
) -> dict:
    """Call LLM and parse response as JSON matching output_schema."""
    schema_hint = f"\n\n你必须以 JSON 格式输出，格式如下：\n{json.dumps(output_schema, ensure_ascii=False, indent=2)}\n只输出 JSON，不要有其他内容。"
    full_prompt = system_prompt + schema_hint
    raw = await _llm_generate(full_prompt, user_content, model)
    # Extract JSON from response (handle markdown code blocks)
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]
    return json.loads(raw.strip())
```

- [ ] **Step 2: 添加 analysis 节点**

```python
# Append to nodes.py

ANALYSIS_SYSTEM_PROMPT = """你是一个资深产品需求分析师。请分析用户需求，产出两部分内容：

## 1. 需求分析文档
- 功能概述
- 页面布局描述
- 交互行为说明
- 数据展示需求
- 技术要求

## 2. E2E 测试用例（JSON 数组）
每个用例包含：
- id: 用例编号 (如 "TC-001")
- name: 用例名称
- description: 测试目标
- steps: 步骤数组，每步包含:
  - action: "click" | "input" | "assert" | "wait"
  - target: CSS 选择器或元素文本
  - value: 输入值/期望文本/等待毫秒数
  - description: 步骤的人类可读说明

核心规则：
- 不要编写代码，只分析需求
- 测试用例应覆盖所有核心交互路径
- 测试步骤要具体、可执行，选择器要明确"""


async def analysis_node(state: GenerationState) -> GenerationState:
    """需求分析节点：产出需求文档 + E2E 测试用例。"""
    logger.info("analysis_node_start")

    harness = EvalHarness()
    result = await _llm_generate_structured(
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_content=f"用户需求：{state['requirement']}\n组件库：{state['component_lib']}",
        output_schema={
            "analysis_doc": "string (markdown 格式的需求分析文档)",
            "e2e_test_cases": [
                {
                    "id": "TC-001",
                    "name": "用例名称",
                    "description": "测试目标",
                    "steps": [
                        {
                            "action": "click",
                            "target": "css选择器",
                            "value": "可选值",
                            "description": "步骤说明",
                        }
                    ],
                }
            ],
        },
    )

    return {
        **state,
        "analysis_result": result.get("analysis_doc", ""),
        "e2e_test_cases": result.get("e2e_test_cases", []),
    }
```

- [ ] **Step 3: 添加 design 和 code 节点**

```python
# Append to nodes.py

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
- 组件库使用方式 ({component_lib})

### 4. 文件拆分方案
- 建议的文件目录结构
- 每个文件的职责说明

### 5. 关键实现要点
- 核心逻辑的实现思路
- 需要注意的边界情况"""


async def design_node(state: GenerationState) -> GenerationState:
    """方案设计节点：产出架构设计文档。"""
    logger.info("design_node_start")

    # If this is a rollback from review, include failure details
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
        system_prompt=DESIGN_SYSTEM_PROMPT.replace("{component_lib}", state.get("component_lib", "tailwind")),
        user_content=prompt,
    )

    harness = EvalHarness()
    state["design_result"] = result
    check = harness.validate(state, "design")
    if not check.passed:
        logger.warning("design_validation_failed", errors=check.errors)

    return state


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

    # If rollback from review or e2e, include failure details
    failure_details = state.get("failure_details")
    if failure_details:
        prompt = (
            f"设计方案：\n{state['design_result']}\n\n"
            f"之前的代码存在问题：\n{failure_details['instruction']}\n\n"
            f"请修复代码，确保通过校验。"
        )
    else:
        prompt = f"设计方案：\n{state['design_result']}"

    result = await _llm_generate(
        system_prompt=CODE_SYSTEM_PROMPT.replace("{component_lib}", state.get("component_lib", "tailwind")),
        user_content=prompt,
    )

    harness = EvalHarness()
    state["code_result"] = result
    check = harness.validate(state, "code")
    if not check.passed:
        logger.warning("code_validation_failed", errors=check.errors)

    return state
```

- [ ] **Step 4: 添加 review 节点**

```python
# Append to nodes.py

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
            "issues": [{"dimension": "代码规范", "description": "...", "suggestion": "..."}],
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

    # Build failure details for rollback
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
```

- [ ] **Step 5: 添加 e2e 节点（后端编排部分）**

```python
# Append to nodes.py

E2E_SYSTEM_PROMPT = """你不需要做任何事。E2E 测试用例已在需求分析阶段生成。
本节点只负责将测试用例发送到前端执行，并等待结果。"""


async def e2e_node(state: GenerationState) -> GenerationState:
    """E2E 节点：将测试用例发送给前端执行（通过 GraphEvent），收集结果。

    注意：这个函数在 LangGraph 中运行，但它不直接调用 Playwright。
    测试执行在浏览器的预览 iframe 中完成。
    本节点通过 GraphEvent 向前端发送执行指令，并通过 E2E HTTP 接口接收结果。
    """
    logger.info("e2e_node_start")

    test_cases = state.get("e2e_test_cases", [])
    if not test_cases:
        logger.warning("e2e_no_test_cases")
        return {**state, "e2e_passed": True, "e2e_results": []}

    # Results are collected by the servicer/graph runner
    # which sends e2e_execute events and waits for HTTP callbacks
    # The actual execution flow is in graph.py and servicer.py

    return state  # State is updated by the graph runner with actual results
```

- [ ] **Step 6: Commit**

```bash
git add ai-service/app/services/generation/nodes.py
git commit -m "feat: implement five LangGraph nodes (analysis, design, code, review, e2e)"
```

---

### Task 4: 定义 StateGraph + 条件路由

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/graph.py`

- [ ] **Step 1: 创建 graph.py — 构建 StateGraph**

```python
# ai-design-platform-server/ai-service/app/services/generation/graph.py
"""
LangGraph StateGraph definition for the 5-node multi-agent pipeline.

Topology:
    analysis -> design -> code -> review -> e2e
                   ^                 ^         |
                   |                 |         |
                   +--- critical ----+         |
                   |                           |
                   +--------- e2e fail --------+
                              (via code -> review -> e2e)
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import GenerationState, RollbackRecord
from .nodes import (
    analysis_node,
    design_node,
    code_node,
    review_node,
    e2e_node,
)
from .harness import LoopControl

import structlog

logger = structlog.get_logger()


def decide_after_review(state: GenerationState) -> str:
    """Conditional edge after review node."""
    if state.get("review_passed"):
        return "e2e"

    severity = state.get("review_severity", "minor")
    if severity == "critical":
        return "design"
    return "code"


def decide_after_e2e(state: GenerationState) -> str:
    """Conditional edge after e2e node."""
    if state.get("e2e_passed"):
        return END
    return "code"


def build_graph() -> StateGraph:
    """Build and return the compiled LangGraph StateGraph."""
    workflow = StateGraph(GenerationState)

    # Add nodes
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("design", design_node)
    workflow.add_node("code", code_node)
    workflow.add_node("review", review_node)
    workflow.add_node("e2e", e2e_node)

    # Entry point
    workflow.set_entry_point("analysis")

    # Forward edges
    workflow.add_edge("analysis", "design")
    workflow.add_edge("design", "code")
    workflow.add_edge("code", "review")

    # Conditional edges
    workflow.add_conditional_edges(
        "review",
        decide_after_review,
        {
            "e2e": "e2e",
            "code": "code",
            "design": "design",
        },
    )
    workflow.add_conditional_edges(
        "e2e",
        decide_after_e2e,
        {
            END: END,
            "code": "code",
        },
    )

    # Compile with checkpointing and human-in-the-loop
    checkpointer = MemorySaver()
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["analysis", "design"],  # Pause for user confirmation
    )

    return app
```

- [ ] **Step 2: 创建 GraphRunner 封装执行逻辑**

```python
# Append to graph.py

import asyncio
import json
from typing import AsyncIterator


class GraphRunner:
    """Runs the LangGraph app and bridges gRPC streaming with frontend SSE."""

    def __init__(self):
        self.app = build_graph()
        self.loop_control = LoopControl()
        self._e2e_result_queue: asyncio.Queue | None = None

    async def run(
        self,
        state: GenerationState,
        generation_id: str,
    ) -> AsyncIterator[dict]:
        """
        Run the graph, yielding GraphEvent dicts for each state transition.
        Each dict has: {event_type, stage, data}
        """
        config = {"configurable": {"thread_id": generation_id}}
        current_state = state
        max_iterations = 50  # Safety limit
        iteration = 0

        # Stream the graph execution
        async for event in self.app.astream(current_state, config):
            iteration += 1
            if iteration > max_iterations:
                yield self._make_event("loop_break", "", {
                    "reason": f"Exceeded max iterations ({max_iterations})",
                })
                break

            for node_name, node_output in event.items():
                yield self._make_event("stage_start", node_name, {})

                # Check for human-in-the-loop (interrupt)
                if node_name in ("analysis", "design"):
                    yield self._make_event("human_confirm_required", node_name, {
                        "message": f"Please review the {node_name} output and confirm to continue.",
                    })
                    # The graph is paused here; caller must resume with app.astream(None, config)

                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

                # E2E node: send test cases for frontend execution
                if node_name == "e2e":
                    test_cases = node_output.get("e2e_test_cases", [])
                    yield self._make_event("e2e_start", "e2e", {
                        "test_cases": test_cases,
                        "total": len(test_cases),
                    })

    async def resume_with_confirmation(
        self,
        generation_id: str,
        state_update: GenerationState | None = None,
    ) -> AsyncIterator[dict]:
        """Resume a paused graph after user confirmation."""
        config = {"configurable": {"thread_id": generation_id}}
        async for event in self.app.astream(state_update, config):
            for node_name, node_output in event.items():
                yield self._make_event("stage_start", node_name, {})
                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

    async def resume_after_e2e(
        self,
        generation_id: str,
        e2e_results: list[dict],
    ) -> AsyncIterator[dict]:
        """Resume graph with E2E results and continue execution."""
        config = {"configurable": {"thread_id": generation_id}}

        # Get current state and update with e2e results
        current_state = self.app.get_state(config)
        passed = all(r.get("passed", False) for r in e2e_results)
        failed = [r for r in e2e_results if not r.get("passed", False)]

        state_update = {
            "e2e_results": e2e_results,
            "e2e_passed": passed,
        }

        if not passed:
            failed_text = "\n".join(
                f"- {r['case_id']}: {r.get('error', 'unknown error')}"
                for r in failed
            )
            state_update["failure_details"] = {
                "source": "e2e",
                "failed_items": failed,
                "instruction": f"E2E 测试失败，以下用例未通过：\n{failed_text}",
                "rollback_target": "code",
            }

            # Apply loop control
            allowed, reason = self.loop_control.should_rollback("code", current_state)
            if not allowed:
                logger.warning("loop_break", reason=reason)
                yield self._make_event("loop_break", "e2e", {"reason": reason})
                state_update["needs_manual_review"] = True
                state_update["e2e_passed"] = True  # Force pass

            yield self._make_event("e2e_complete", "e2e", {
                "passed": state_update["e2e_passed"],
                "failed_count": len(failed),
                "total_count": len(e2e_results),
            })

        config["state_update"] = state_update
        async for event in self.app.astream(None, config):
            for node_name, node_output in event.items():
                if node_name == "e2e":
                    continue  # Don't re-enter e2e
                yield self._make_event("stage_start", node_name, {})
                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

    @staticmethod
    def _make_event(event_type: str, stage: str, data: dict) -> dict:
        return {"event_type": event_type, "stage": stage, "data": data}

    @staticmethod
    def _get_summary(node_name: str, output: dict) -> str:
        """Extract a one-line summary from node output."""
        summaries = {
            "analysis": output.get("analysis_result", "")[:200] if output.get("analysis_result") else "",
            "design": output.get("design_result", "")[:200] if output.get("design_result") else "",
            "code": f"Generated {len(output.get('code_result', ''))} chars of code",
            "review": output.get("review_result", ""),
            "e2e": f"E2E: {'pass' if output.get('e2e_passed') else 'fail'}",
        }
        return summaries.get(node_name, "")
```

- [ ] **Step 3: Commit**

```bash
git add ai-service/app/services/generation/graph.py
git commit -m "feat: define LangGraph StateGraph with conditional edges and GraphRunner"
```

---

### Task 5: 改造 GenerationServicer 接入 LangGraph

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/servicer.py`

- [ ] **Step 1: 重写 servicer.py**

The existing servicer directly calls `provider.stream_generate()`. Replace with LangGraph integration:

```python
# ai-design-platform-server/ai-service/app/services/generation/servicer.py
"""
GenerationServicer — gRPC service implementation, now powered by LangGraph.
"""

import json
from typing import AsyncIterator

import grpc
from ai.v1.generation_pb2 import (
    GenerateRequest,
    GenerateResponse,
    GraphEvent as ProtoGraphEvent,
    CancelRequest,
    CancelResponse,
)
import structlog

from ..llm.router import resolve_provider
from .graph import GraphRunner
from .nodes import set_provider
from .state import GenerationState

logger = structlog.get_logger()


class GenerationServicer:
    def __init__(self):
        self._active_runs: dict[str, GraphRunner] = {}

    async def StreamGenerate(
        self,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Stream generation powered by LangGraph StateGraph."""
        generation_id = request.generation_id
        logger.info("stream_generate_start", generation_id=generation_id)

        # Set up LLM provider
        provider = resolve_provider(request.model)
        set_provider(provider)

        # Build initial state
        user_messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
        ]
        user_content = next(
            (m["content"] for m in user_messages if m["role"] == "user"), ""
        )

        state: GenerationState = {
            "requirement": user_content,
            "component_lib": request.metadata.get("component_lib", "tailwind"),
            "messages": user_messages,
            "analysis_result": None,
            "design_result": None,
            "code_result": None,
            "review_result": None,
            "e2e_results": None,
            "e2e_test_cases": None,
            "review_passed": False,
            "review_severity": None,
            "e2e_passed": False,
            "failure_details": None,
            "rollback_records": [],
            "rollback_count": {},
            "max_rollback_per_node": 3,
            "max_rollback_total": 10,
            "needs_manual_review": False,
        }

        runner = GraphRunner()
        self._active_runs[generation_id] = runner

        try:
            async for event in runner.run(state, generation_id):
                # Forward token events from nodes (code generation streaming)
                # Graph events become SSE events
                yield self._to_graph_response(event)

                # Check for cancellation
                if context.cancelled():
                    logger.info("stream_cancelled", generation_id=generation_id)
                    break

            # Send completion
            yield GenerateResponse(
                complete=GenerateResponse.GenerationComplete(
                    finish_reason="stop",
                    usage={"total_tokens": 0},
                )
            )

        except Exception as e:
            logger.error("stream_error", generation_id=generation_id, error=str(e))
            yield GenerateResponse(
                error=GenerateResponse.GenerationError(
                    code="GENERATION_ERROR",
                    message=str(e),
                )
            )
        finally:
            self._active_runs.pop(generation_id, None)

    async def CancelGeneration(
        self, request: CancelRequest, context: grpc.aio.ServicerContext
    ) -> CancelResponse:
        """Cancel an active generation."""
        run = self._active_runs.pop(request.generation_id, None)
        if run:
            logger.info("generation_cancelled", generation_id=request.generation_id)
            return CancelResponse(success=True)
        return CancelResponse(success=False)

    def get_runner(self, generation_id: str) -> GraphRunner | None:
        """Get active runner for external operations (E2E result, confirmation)."""
        return self._active_runs.get(generation_id)

    @staticmethod
    def _to_graph_response(event: dict) -> GenerateResponse:
        """Convert a GraphRunner event dict to a GenerateResponse."""
        return GenerateResponse(
            graph_event=ProtoGraphEvent(
                event_type=event["event_type"],
                stage=event["stage"],
                data=json.dumps(event["data"], ensure_ascii=False),
            )
        )
```

- [ ] **Step 2: Commit**

```bash
git add ai-service/app/services/generation/servicer.py
git commit -m "feat: rewrite GenerationServicer to use LangGraph GraphRunner"
```

---

### Task 6: Go Gateway 适配 GraphEvent

**Files:**
- Create: `ai-design-platform-server/gateway/internal/handler/generation_sse.go`
- Modify: `ai-design-platform-server/gateway/cmd/server/main.go`

- [ ] **Step 1: 创建 generation_sse.go — Graph SSE 处理器**

```go
// ai-design-platform-server/gateway/internal/handler/generation_sse.go
package handler

import (
	"encoding/json"
	"net/http"

	"github.com/gin-gonic/gin"
)

// GraphSSEHandler handles streaming LangGraph events to the frontend via SSE.
type GraphSSEHandler struct {
	aiClient *AIClient // reuse existing gRPC client
}

func NewGraphSSEHandler(aiClient *AIClient) *GraphSSEHandler {
	return &GraphSSEHandler{aiClient: aiClient}
}

// StreamGeneration handles POST /api/v1/generation/stream
// It starts a LangGraph run and forwards all GraphEvents as SSE.
func (h *GraphSSEHandler) StreamGeneration(c *gin.Context) {
	var req ChatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	generationID := newUUID()
	protoStrings := buildProtoMessages(req.Messages)

	grpcReq := &pb.GenerateRequest{
		GenerationId: generationID,
		Model:        req.Model,
		Messages:     protoMessages,
		Metadata: map[string]string{
			"component_lib": req.ComponentLib,
		},
	}

	// Set SSE headers
	c.Writer.Header().Set("Content-Type", "text/event-stream")
	c.Writer.Header().Set("Cache-Control", "no-cache")
	c.Writer.Header().Set("Connection", "keep-alive")
	c.Writer.Header().Set("X-Accel-Buffering", "no")

	// Send meta event with generation_id
	writeSSE(c, "", map[string]string{"_t": "meta", "generation_id": generationID})
	c.Writer.Flush()

	stream, err := h.aiClient.StreamGenerate(c.Request.Context(), grpcReq)
	if err != nil {
		writeSSE(c, "", map[string]string{"_t": "error", "message": err.Error()})
		c.Writer.Flush()
		return
	}

	for {
		resp, err := stream.Recv()
		if err != nil {
			break
		}

		// Handle existing event types (token, reasoning, complete, error)
		if token := resp.GetToken(); token != nil {
			if token.ReasoningContent != "" {
				writeSSE(c, "", map[string]interface{}{
					"_t":   "reasoning",
					"text": token.ReasoningContent,
					"index": token.Index,
				})
			} else {
				writeSSE(c, "", map[string]interface{}{
					"_t":   "token",
					"text": token.Text,
					"index": token.Index,
				})
			}
		}

		if complete := resp.GetComplete(); complete != nil {
			writeSSE(c, "", map[string]interface{}{
				"_t":            "complete",
				"finish_reason": complete.FinishReason,
			})
			c.Writer.Flush()
			return
		}

		if errResp := resp.GetError(); errResp != nil {
			writeSSE(c, "", map[string]interface{}{
				"_t":      "error",
				"code":    errResp.Code,
				"message": errResp.Message,
			})
			c.Writer.Flush()
			return
		}

		// NEW: Handle GraphEvent
		if graphEvent := resp.GetGraphEvent(); graphEvent != nil {
			payload := map[string]interface{}{
				"_t":    graphEvent.EventType,
				"stage": graphEvent.Stage,
			}
			// Merge data JSON into payload
			var data map[string]interface{}
			if err := json.Unmarshal([]byte(graphEvent.Data), &data); err == nil {
				for k, v := range data {
					payload[k] = v
				}
			}
			writeSSE(c, "", payload)
		}

		c.Writer.Flush()
	}
}

// buildProtoMessages converts ChatMessage slice to proto Message slice.
func buildProtoMessages(msgs []ChatMessage) []*pb.Message {
	result := make([]*pb.Message, len(msgs))
	for i, m := range msgs {
		result[i] = &pb.Message{
			Role:    m.Role,
			Content: m.Content,
		}
	}
	return result
}
```

- [ ] **Step 2: 注册新路由**

In `gateway/cmd/server/main.go`, add:

```go
// After existing route registration:
graphHandler := handler.NewGraphSSEHandler(aiClient)
router.POST("/api/v1/generation/stream", graphHandler.StreamGeneration)
router.POST("/api/v1/generation/confirm", graphHandler.ConfirmStage)
```

- [ ] **Step 3: Commit**

```bash
git add gateway/internal/handler/generation_sse.go gateway/cmd/server/main.go
git commit -m "feat: add Go handler for LangGraph SSE event forwarding"
```

---

## Phase 2: E2E 节点

### Task 7: E2E 结果回报 + 确认接口

**Files:**
- Create: `ai-design-platform-server/gateway/internal/handler/e2e.go`
- Modify: `ai-design-platform-server/gateway/cmd/server/main.go`

- [ ] **Step 1: 创建 e2e.go**

```go
// ai-design-platform-server/gateway/internal/handler/e2e.go
package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// E2EResultRequest is the payload from frontend after executing a test case.
type E2EResultRequest struct {
	GenerationID string `json:"generation_id" binding:"required"`
	CaseID       string `json:"case_id" binding:"required"`
	Passed       bool   `json:"passed"`
	Error        string `json:"error,omitempty"`
	Screenshot   string `json:"screenshot,omitempty"` // base64
}

// ConfirmRequest is the payload when user confirms analysis/design stage.
type ConfirmRequest struct {
	GenerationID string `json:"generation_id" binding:"required"`
	Stage        string `json:"stage" binding:"required"` // "analysis" | "design"
}

// E2EHandler handles E2E test result reporting and stage confirmation.
type E2EHandler struct {
	graphHandler *GraphSSEHandler
}

func NewE2EHandler(graphHandler *GraphSSEHandler) *E2EHandler {
	return &E2EHandler{graphHandler: graphHandler}
}

// SubmitE2EResult handles POST /api/v1/e2e/result
// Frontend reports the result of a single E2E test case execution.
func (h *E2EHandler) SubmitE2EResult(c *gin.Context) {
	var req E2EResultRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Store result (in production: use Redis or in-memory queue)
	// For now, route to the active generation's E2E handler
	c.JSON(http.StatusOK, gin.H{"status": "received"})
}

// ConfirmStage handles POST /api/v1/generation/confirm
// User confirms analysis/design output and triggers next stage.
func (h *E2EHandler) ConfirmStage(c *gin.Context) {
	var req ConfirmRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"status": "confirmed", "next_stage": req.Stage})
}
```

- [ ] **Step 2: 注册 E2E 路由**

In `gateway/cmd/server/main.go`, add:

```go
e2eHandler := handler.NewE2EHandler(graphHandler)
router.POST("/api/v1/e2e/result", e2eHandler.SubmitE2EResult)
router.POST("/api/v1/generation/confirm", e2eHandler.ConfirmStage)
```

- [ ] **Step 3: Commit**

```bash
git add gateway/internal/handler/e2e.go gateway/cmd/server/main.go
git commit -m "feat: add E2E result and stage confirmation HTTP endpoints"
```

---

### Task 8: 前端 useE2ERunner 执行引擎

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/composables/useE2ERunner.ts`

- [ ] **Step 1: 创建 useE2ERunner.ts**

```typescript
// ai-design-platform-web/packages/ai-generation-app/src/composables/useE2ERunner.ts
import { ref, type Ref } from 'vue'

export interface E2ETestStep {
  action: 'click' | 'input' | 'assert' | 'wait'
  target: string
  value?: string
  description: string
}

export interface E2ETestCase {
  id: string
  name: string
  description: string
  steps: E2ETestStep[]
}

export interface E2ECaseResult {
  caseId: string
  passed: boolean
  error?: string
  screenshot?: string  // base64 data URL
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function captureScreenshot(iframe: HTMLIFrameElement): Promise<string> {
  // Use html2canvas or a simple DOM snapshot as fallback
  try {
    const doc = iframe.contentDocument
    if (!doc) return ''
    const html = doc.documentElement.outerHTML
    return `data:text/html;base64,${btoa(unescape(encodeURIComponent(html)))}`
  } catch {
    return ''
  }
}

async function executeStep(doc: Document, step: E2ETestStep): Promise<void> {
  const el = doc.querySelector(step.target) as HTMLElement | null

  if (!el && step.action !== 'wait') {
    throw new Error(`Element not found: ${step.target}`)
  }

  switch (step.action) {
    case 'click': {
      el!.click()
      // Wait a tiny bit for reactivity
      await sleep(100)
      break
    }
    case 'input': {
      const input = el as HTMLInputElement
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      )?.set
      nativeInputValueSetter?.call(input, step.value || '')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      await sleep(100)
      break
    }
    case 'assert': {
      const text = el?.textContent || ''
      const expected = step.value || ''
      if (!text.includes(expected)) {
        throw new Error(
          `Assertion failed: expected "${expected}" in "${step.target}", got "${text.slice(0, 100)}"`
        )
      }
      break
    }
    case 'wait': {
      const ms = parseInt(step.value || '1000', 10) || 1000
      await sleep(ms)
      break
    }
    // Future extensions:
    // case 'drag': ...
    // case 'upload': ...
    // case 'navigate': ...
    // case 'scroll': ...
    // case 'hover': ...
    default:
      throw new Error(`Unknown action: ${(step as E2ETestStep).action}`)
  }
}

export function useE2ERunner(previewFrameRef: Ref<HTMLIFrameElement | null>) {
  const results = ref<E2ECaseResult[]>([])
  const currentCaseIndex = ref(-1)
  const isRunning = ref(false)

  async function executeCase(testCase: E2ETestCase): Promise<E2ECaseResult> {
    const iframe = previewFrameRef.value
    if (!iframe?.contentDocument) {
      return {
        caseId: testCase.id,
        passed: false,
        error: 'Preview iframe not available',
      }
    }

    const doc = iframe.contentDocument
    try {
      for (const step of testCase.steps) {
        await executeStep(doc, step)
      }
      return { caseId: testCase.id, passed: true }
    } catch (e: any) {
      const screenshot = await captureScreenshot(iframe)
      return {
        caseId: testCase.id,
        passed: false,
        error: e.message || 'Unknown error',
        screenshot,
      }
    }
  }

  async function executeAll(
    testCases: E2ETestCase[],
    onCaseComplete: (result: E2ECaseResult) => void,
  ): Promise<E2ECaseResult[]> {
    isRunning.value = true
    results.value = []

    for (let i = 0; i < testCases.length; i++) {
      currentCaseIndex.value = i
      const result = await executeCase(testCases[i])
      results.value.push(result)
      onCaseComplete(result)
    }

    isRunning.value = false
    currentCaseIndex.value = -1
    return results.value
  }

  function reset() {
    results.value = []
    currentCaseIndex.value = -1
    isRunning.value = false
  }

  return {
    results,
    currentCaseIndex,
    isRunning,
    executeCase,
    executeAll,
    reset,
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add ai-generation-app/src/composables/useE2ERunner.ts
git commit -m "feat: add useE2ERunner — preview iframe E2E test execution engine"
```

---

## Phase 3: 前端适配

### Task 9: 扩展类型定义和 Pinia Store

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/types/generation.ts`
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/stores/generation.ts`

- [ ] **Step 1: 扩展 generation.ts 类型**

Add new types after existing `StepNode`:

```typescript
// Add to generation.ts

// Extended stage type with two new stages
export type Stage = 'idle' | 'analysis' | 'design' | 'code' | 'review' | 'e2e'

// E2E types (shared with backend DSL)
export interface E2ETestStep {
  action: 'click' | 'input' | 'assert' | 'wait'
  target: string
  value?: string
  description: string
}

export interface E2ETestCase {
  id: string
  name: string
  description: string
  steps: E2ETestStep[]
}

export interface E2ECaseResult {
  caseId: string
  passed: boolean
  error?: string
  screenshot?: string
}

// Rollback event from backend
export interface RollbackEvent {
  from: string
  to: string
  reason: string
  failedCases?: E2ECaseResult[]
}

// Graph event stream state
export type GraphEventType =
  | 'stage_start'
  | 'stage_complete'
  | 'stage_rollback'
  | 'e2e_start'
  | 'e2e_execute'
  | 'e2e_case_result'
  | 'e2e_complete'
  | 'human_confirm_required'
  | 'loop_warning'
  | 'loop_break'
  | 'token'
  | 'complete'
  | 'error'
```

- [ ] **Step 2: 扩展 Pinia Store state**

In `stores/generation.ts`, add to the state interface:

```typescript
// Add to state:
e2eTestCases: [] as E2ETestCase[],
e2eResults: [] as E2ECaseResult[],
e2eRunning: false,
rollbackEvents: [] as RollbackEvent[],
needsManualReview: false,
loopBreakReason: null as string | null,
```

Add actions:

```typescript
// Add to actions:
setE2ETestCases(cases: E2ETestCase[]) {
  this.e2eTestCases = cases
},
addE2EResult(result: E2ECaseResult) {
  this.e2eResults.push(result)
},
clearE2EResults() {
  this.e2eResults = []
  this.e2eRunning = false
},
addRollbackEvent(event: RollbackEvent) {
  this.rollbackEvents.push(event)
},
setNeedsManualReview(needs: boolean) {
  this.needsManualReview = needs
},
setLoopBreakReason(reason: string | null) {
  this.loopBreakReason = reason
},
```

Update `resetAll()` to clear new fields:

```typescript
// In resetAll(), add:
this.e2eTestCases = []
this.e2eResults = []
this.e2eRunning = false
this.rollbackEvents = []
this.needsManualReview = false
this.loopBreakReason = null
```

Update `currentStepNodes` getter to include all five nodes:

```typescript
// currentStepNodes getter — expand to 5 nodes:
get currentStepNodes(): StepNode[] {
  const nodes: StepNode[] = [
    { key: 'analysis', label: '需求分析', status: this.stageStatus.analysis || 'pending' },
    { key: 'design', label: '方案设计', status: this.stageStatus.design || 'pending' },
    { key: 'code', label: '代码生成', status: this.stageStatus.code || 'pending' },
    { key: 'review', label: '质量校验', status: this.stageStatus.review || 'pending' },
    { key: 'e2e', label: 'E2E验证', status: this.stageStatus.e2e || 'pending' },
  ]
  return nodes
}
```

- [ ] **Step 3: Commit**

```bash
git add ai-generation-app/src/types/generation.ts ai-generation-app/src/stores/generation.ts
git commit -m "feat: extend types and store for 5-node pipeline with E2E support"
```

---

### Task 10: 重写 useStreamChat 扩展 SSE 事件解析

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/composables/useStreamChat.ts`

- [ ] **Step 1: 扩展 SSE 事件处理**

In the SSE event dispatch section (`if (event._t === 'token')` block), add new event handlers:

```typescript
// Add after existing event handlers in the SSE reader loop:

switch (event._t) {
  case 'token':
    store.appendToLastMessage(event.text)
    break

  case 'reasoning':
    store.appendReasoning(event.text)
    break

  case 'stage_start':
    store.setStageStatus(event.stage, 'active')
    store.setStage(event.stage as Stage)
    break

  case 'stage_complete':
    store.setStageStatus(event.stage, 'done')
    // Save stage output if present
    if (event.summary) {
      store.setStageOutput(event.stage as Stage, event.summary)
    }
    break

  case 'stage_rollback':
    store.addRollbackEvent({
      from: event.from,
      to: event.to,
      reason: event.reason,
      failedCases: event.failed_cases,
    })
    // Update stage statuses for rollback animation
    store.setStageStatus(event.from, 'pending')
    store.setStage(event.to as Stage)
    store.setStageStatus(event.to, 'active')
    break

  case 'e2e_start':
    store.setE2ETestCases(event.test_cases || [])
    store.clearE2EResults()
    store.setStageStatus('e2e', 'active')
    break

  case 'e2e_execute':
    // Triggers useE2ERunner.executeCase()
    // Handled in GenerationView via event bus / callback
    break

  case 'e2e_case_result':
    store.addE2EResult({
      caseId: event.case_id,
      passed: event.passed,
      error: event.error,
      screenshot: event.screenshot,
    })
    break

  case 'e2e_complete':
    store.setStageStatus('e2e', event.passed ? 'done' : 'pending')
    store.e2eRunning = false
    break

  case 'human_confirm_required':
    // Pause, show confirm button — handled by useMultiAgent
    break

  case 'loop_warning':
    console.warn(`Loop warning: ${event.reason}`)
    break

  case 'loop_break':
    store.setNeedsManualReview(true)
    store.setLoopBreakReason(event.reason)
    break

  case 'complete':
    store.finishReasoning()
    store.finalizeLastMessage()
    break

  case 'error':
    streamError.value = event.message
    break
}
```

- [ ] **Step 2: Commit**

```bash
git add ai-generation-app/src/composables/useStreamChat.ts
git commit -m "feat: extend SSE parser with GraphEvent and E2E event handlers"
```

---

### Task 11: 重写 useMultiAgent 为事件驱动

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/composables/useMultiAgent.ts`

- [ ] **Step 1: 重写 useMultiAgent.ts**

```typescript
// ai-design-platform-web/packages/ai-generation-app/src/composables/useMultiAgent.ts
import { ref } from 'vue'
import { useGenerationStore } from '../stores/generation'
import { useStreamChat } from './useStreamChat'
import type { Stage, ComponentLibrary } from '../types/generation'

export function useMultiAgent() {
  const store = useGenerationStore()
  const { send, cancel: cancelStream } = useStreamChat()

  const isTransitioning = ref(false)
  const streamError = ref<string | null>(null)

  async function startGeneration(content: string, lib: ComponentLibrary) {
    store.resetAll()
    store.setComponentLib(lib)
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setRightPanelView('stage-output')

    isTransitioning.value = true
    try {
      await send({
        content,
        lib,
        stage: 'analysis',
      })
    } catch (e: any) {
      streamError.value = e.message || 'Generation failed'
    } finally {
      isTransitioning.value = false
    }
  }

  async function confirmStage(stage: Stage) {
    // POST /api/v1/generation/confirm
    // Backend resumes the graph from interrupt point
    isTransitioning.value = true
    try {
      const response = await fetch('/api/v1/generation/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          stage,
        }),
      })
      if (!response.ok) throw new Error('Confirmation failed')
    } catch (e: any) {
      streamError.value = e.message
    } finally {
      isTransitioning.value = false
    }
  }

  async function submitE2EResults(results: E2ECaseResult[]) {
    // Send all E2E results to backend, which resumes the graph
    isTransitioning.value = true
    try {
      for (const result of results) {
        await fetch('/api/v1/e2e/result', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            generation_id: store.currentGenerationId,
            case_id: result.caseId,
            passed: result.passed,
            error: result.error,
            screenshot: result.screenshot,
          }),
        })
      }
    } catch (e: any) {
      streamError.value = e.message
    } finally {
      isTransitioning.value = false
    }
  }

  function cancel() {
    cancelStream()
  }

  return {
    isTransitioning,
    streamError,
    startGeneration,
    confirmStage,
    submitE2EResults,
    cancel,
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add ai-generation-app/src/composables/useMultiAgent.ts
git commit -m "feat: rewrite useMultiAgent as event-driven with confirm and E2E submit"
```

---

### Task 12: 更新 StepProgress 为五节点 + 回流动画

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/components/StepProgress.vue`

- [ ] **Step 1: 更新 StepProgress.vue**

```vue
<template>
  <div class="step-progress">
    <div
      v-for="(node, index) in nodes"
      :key="node.key"
      class="step-node-wrapper"
    >
      <!-- Connector line (except last) -->
      <div
        v-if="index < nodes.length - 1"
        class="step-connector"
        :class="{
          'connector-done': node.status === 'done' && nodes[index + 1].status !== 'pending',
          'connector-active': node.status === 'active',
          'connector-rollback': isRollingBack && node.key === rollbackTarget,
        }"
      />

      <!-- Step circle + label -->
      <div class="step-node" :class="nodeClass(node)">
        <div class="step-circle">
          <span v-if="node.status === 'done'" class="step-check">✓</span>
          <span v-else-if="node.status === 'active'" class="step-spinner" />
          <span v-else class="step-number">{{ index + 1 }}</span>
        </div>
        <span class="step-label">{{ node.label }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { StepNode } from '../types/generation'

const props = defineProps<{
  nodes: StepNode[]
  currentStage: string
  isRollingBack?: boolean
  rollbackTarget?: string
}>()

const emit = defineEmits<{
  (e: 'node-click', stage: string): void
}>()

function nodeClass(node: StepNode) {
  return {
    'node-done': node.status === 'done',
    'node-active': node.status === 'active',
    'node-pending': node.status === 'pending',
    'node-rollback': props.isRollingBack && node.key === props.rollbackTarget,
  }
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add ai-generation-app/src/components/StepProgress.vue
git commit -m "feat: update StepProgress to 5 nodes with rollback animation support"
```

---

### Task 13: 创建 E2EPanel 组件

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/E2EPanel.vue`

- [ ] **Step 1: 创建 E2EPanel.vue**

```vue
<template>
  <div class="e2e-panel">
    <div class="e2e-header">
      <h3>🧪 E2E 测试</h3>
      <span class="e2e-summary">
        {{ passedCount }} / {{ totalCount }} 通过
      </span>
    </div>

    <div class="e2e-list">
      <div
        v-for="(testCase, index) in testCases"
        :key="testCase.id"
        class="e2e-case"
        :class="caseClass(testCase.id)"
      >
        <div class="e2e-case-header">
          <span class="e2e-case-icon">{{ caseIcon(testCase.id) }}</span>
          <span class="e2e-case-name">{{ testCase.name }}</span>
        </div>
        <p class="e2e-case-desc">{{ testCase.description }}</p>

        <!-- Show error detail for failed cases -->
        <div
          v-if="failedResult(testCase.id)"
          class="e2e-case-error"
        >
          <p>{{ failedResult(testCase.id)?.error }}</p>
          <img
            v-if="failedResult(testCase.id)?.screenshot"
            :src="failedResult(testCase.id)?.screenshot"
            class="e2e-screenshot"
            alt="失败截图"
          />
        </div>

        <!-- Running indicator -->
        <div
          v-if="isCaseRunning(index)"
          class="e2e-case-running"
        >
          执行中...
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { E2ETestCase, E2ECaseResult } from '../types/generation'

const props = defineProps<{
  testCases: E2ETestCase[]
  results: E2ECaseResult[]
  currentCaseIndex: number
  isRunning: boolean
}>()

const totalCount = computed(() => props.testCases.length)
const passedCount = computed(() => props.results.filter((r) => r.passed).length)

function caseResult(caseId: string): E2ECaseResult | undefined {
  return props.results.find((r) => r.caseId === caseId)
}

function failedResult(caseId: string): E2ECaseResult | undefined {
  const r = caseResult(caseId)
  return r && !r.passed ? r : undefined
}

function caseClass(caseId: string) {
  const r = caseResult(caseId)
  if (!r) return ''
  return r.passed ? 'case-passed' : 'case-failed'
}

function caseIcon(caseId: string): string {
  const r = caseResult(caseId)
  if (!r) return '⬜'
  return r.passed ? '✅' : '❌'
}

function isCaseRunning(index: number): boolean {
  return props.isRunning && props.currentCaseIndex === index
}
</script>

<style scoped>
.e2e-panel {
  padding: 16px;
  height: 100%;
  overflow-y: auto;
}
.e2e-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.e2e-header h3 {
  margin: 0;
  font-size: 16px;
}
.e2e-summary {
  font-size: 14px;
  color: var(--text-secondary);
}
.e2e-case {
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 8px;
  border: 1px solid var(--border-color);
}
.case-passed {
  border-color: var(--success-color);
  background: var(--success-bg);
}
.case-failed {
  border-color: var(--error-color);
  background: var(--error-bg);
}
.e2e-case-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.e2e-case-desc {
  margin: 4px 0 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}
.e2e-case-error {
  margin-top: 8px;
  padding: 8px;
  background: rgba(255, 0, 0, 0.05);
  border-radius: 4px;
  font-size: 12px;
}
.e2e-screenshot {
  max-width: 100%;
  margin-top: 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}
.e2e-case-running {
  margin-top: 8px;
  font-size: 12px;
  color: var(--primary-color);
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add ai-generation-app/src/components/E2EPanel.vue
git commit -m "feat: add E2EPanel component for test case list and results"
```

---

### Task 14: 更新 GenerationView 集成 E2E + 五节点

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/views/GenerationView.vue`
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/components/ChatPanel.vue`

- [ ] **Step 1: 更新 GenerationView.vue 模板**

Add E2EPanel to the right panel, shown during e2e stage:

```vue
<!-- In the right panel area, add after the existing conditional blocks: -->

<!-- E2E Stage: show test panel -->
<div v-if="store.stage === 'e2e'" class="e2e-container">
  <E2EPanel
    :test-cases="store.e2eTestCases"
    :results="store.e2eResults"
    :current-case-index="e2eCurrentIndex"
    :is-running="store.e2eRunning"
  />
</div>

<!-- Manual review needed banner -->
<div v-if="store.needsManualReview" class="manual-review-banner">
  ⚠️ 自动流程已熔断，请人工复核
  <span v-if="store.loopBreakReason">原因：{{ store.loopBreakReason }}</span>
</div>
```

Import E2EPanel:

```typescript
import E2EPanel from '../components/E2EPanel.vue'
```

- [ ] **Step 2: 集成 useE2ERunner**

In the `<script setup>` section:

```typescript
import { useE2ERunner } from '../composables/useE2ERunner'
import { useMultiAgent } from '../composables/useMultiAgent'

const { submitE2EResults } = useMultiAgent()
const previewFrameRef = ref<HTMLIFrameElement | null>(null)
const { results, currentCaseIndex, isRunning, executeAll } = useE2ERunner(previewFrameRef)
const e2eCurrentIndex = computed(() => currentCaseIndex.value)

// Watch for e2e_start event from SSE to trigger execution
watch(
  () => store.e2eTestCases,
  async (cases) => {
    if (cases.length > 0 && store.stage === 'e2e') {
      store.e2eRunning = true
      const allResults = await executeAll(cases, (result) => {
        store.addE2EResult(result)
        // Optionally send individual result immediately
      })
      store.e2eRunning = false
      await submitE2EResults(allResults)
    }
  },
)
```

- [ ] **Step 3: 更新 ChatPanel 适配新的确认流程**

In `ChatPanel.vue`, update the confirm button handler to call `confirmStage()`:

```typescript
// Replace existing confirmAnalysis/confirmDesign calls:
const { confirmStage } = useMultiAgent()

async function handleConfirm() {
  const currentStage = store.stage
  if (currentStage === 'analysis' || currentStage === 'design') {
    await confirmStage(currentStage)
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add ai-generation-app/src/views/GenerationView.vue \
        ai-generation-app/src/components/ChatPanel.vue
git commit -m "feat: integrate E2E panel and 5-node pipeline in GenerationView"
```

---

### Task 15: 清理 useStagePrompts（prompt 已迁移到后端）

**Files:**
- Remove: `ai-design-platform-web/packages/ai-generation-app/src/composables/useStagePrompts.ts`

- [ ] **Step 1: 删除 useStagePrompts.ts 并清理引用**

```bash
rm ai-generation-app/src/composables/useStagePrompts.ts
```

Remove all imports of `useStagePrompts` in:
- `useMultiAgent.ts` (already done in Task 11 rewrite)

- [ ] **Step 2: Commit**

```bash
git rm ai-generation-app/src/composables/useStagePrompts.ts
git commit -m "refactor: remove useStagePrompts, prompts now managed by backend LangGraph nodes"
```

---

## Plan Checklist

| # | Task | Phase | Status |
|---|------|-------|--------|
| 1 | GenerationState + Proto 扩展 | Phase 1 | [ ] |
| 2 | AgentHarness 执行壳 | Phase 1 | [ ] |
| 3 | 五个 LangGraph 节点 | Phase 1 | [ ] |
| 4 | StateGraph + 条件路由 | Phase 1 | [ ] |
| 5 | GenerationServicer 接入 LangGraph | Phase 1 | [ ] |
| 6 | Go Gateway GraphEvent 转发 | Phase 1 | [ ] |
| 7 | E2E 结果回报 + 确认接口 | Phase 2 | [ ] |
| 8 | useE2ERunner 执行引擎 | Phase 2 | [ ] |
| 9 | 类型定义 + Pinia Store 扩展 | Phase 3 | [ ] |
| 10 | useStreamChat SSE 事件扩展 | Phase 3 | [ ] |
| 11 | useMultiAgent 事件驱动重写 | Phase 3 | [ ] |
| 12 | StepProgress 五节点 + 回流动画 | Phase 3 | [ ] |
| 13 | E2EPanel 组件 | Phase 3 | [ ] |
| 14 | GenerationView 集成 | Phase 3 | [ ] |
| 15 | 清理 useStagePrompts | Phase 3 | [ ] |
