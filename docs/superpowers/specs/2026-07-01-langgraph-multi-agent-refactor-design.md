# LangGraph 多 Agent 重构设计方案

> 日期: 2026-07-01
> 状态: 设计中

## 1. 背景与动机

### 1.1 当前状态

当前"多 Agent"系统是前端手动实现的三阶段状态机（`useMultiAgent.ts`），核心问题：

- **Orchestration 全在客户端** — 状态流转、阶段切换、上下文传递全部由 Vue composable 管理
- **严格串行** — analysis → design → code，无法回流、无法做条件路由
- **无 Agent 间通信** — 上下文通过 Pinia store 的字符串字段传递
- **无结构化输出与校验** — 阶段产出是纯 markdown，没有 schema 保证
- **后端 agent.proto 定义了但未实现** — `AgentService` 的服务端代码不存在
- **难以扩展** — 加一个新阶段需要改 `useMultiAgent.ts` + store + types + UI 多处

### 1.2 目标

将 Agent 编排迁移到 Python 后端，使用 **LangGraph StateGraph** 实现：

1. 状态机后端化：前端只做展示 + 人工介入触发
2. 五节点流水线：analysis → design → code → review → e2e
3. 条件回流：review/e2e 不通过时，根据失败原因回流到前面节点
4. E2E 测试用例在 analysis 阶段生成，在 code 完成后由前端预览区执行
5. 完整的 Harness + Loop Engine 工程实践：可观测、可收敛、可熔断

## 2. 架构设计

### 2.1 整体架构

```
┌────────────────────────────────────────────────────────┐
│                  Frontend (Vue 3)                       │
│                                                        │
│  GenerationView ─┬─ ChatPanel (对话 + 确认)             │
│                  ├─ StepProgress (五节点进度条 + 回流)   │
│                  ├─ StageOutput (文档查看/编辑)          │
│                  ├─ PreviewFrame (代码实时预览)          │
│                  └─ useE2ERunner (预览区执行测试)        │
│                        │                               │
│                   SSE ↕ HTTP                           │
└────────────────────────┼───────────────────────────────┘
                         │
┌────────────────────────┼───────────────────────────────┐
│                  Backend (Go + Python)                  │
│                                                        │
│  Go Gateway ── SSE 事件转发 ── Python AI Service        │
│                                  │                     │
│                           ┌──────▼──────────┐          │
│                           │ LangGraph App   │          │
│                           │                 │          │
│                           │ StateGraph with:│          │
│                           │ 5 nodes         │          │
│                           │ conditional     │          │
│                           │ edges           │          │
│                           │ checkpoint      │          │
│                           │ interrupt_before │         │
│                           └─────────────────┘          │
└────────────────────────────────────────────────────────┘
```

### 2.2 StateGraph 拓扑

```
                    ┌──────────────────────────────────────┐
                    │        LangGraph StateGraph           │
                    │                                       │
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│analysis │───▶│ design  │───▶│  code   │───▶│ review  │───▶│   e2e   │
│需求分析  │    │ 方案设计 │    │ 代码生成 │    │ 语义校验 │    │ 端到端  │
│+测试用例 │    │         │    │+实时预览 │    │         │    │ 验证    │
└─────────┘    └─────────┘    └────▲────┘    └────▲────┘    └────┬────┘
                                   │              │              │
                                   │  ┌───────────┘              │
                                   │  │ review失败→code          │
                                   │  │ review严重失败→design    │
                                   │  │                          │
                                   │  │  e2e失败→code            │
                                   │  │  (修复后必须过review)     │
                                   │  │                          │
                                   └──┼──────────────────────────┘
                                      │
                              pass? ──┘
                              pass → END
```

### 2.3 节点职责矩阵

| 节点 | 职责 | 核心产出 | 是否暂停等用户 | 回流来源 |
|------|------|---------|---------------|---------|
| `analysis` | 需求分析 + 生成 E2E 测试用例 | 需求文档 + `E2ETestCase[]` | 是 | — |
| `design` | 架构设计（组件树/数据流/状态管理） | 设计文档 | 是 | review |
| `code` | 代码生成 + SSE 实时推送到预览区 | Vue SFC 代码 | 否 | review, e2e |
| `review` | LLM 语义校验（匹配设计/边界情况/代码规范） | 通过 / 修正意见 + 回流目标 | 否 | — |
| `e2e` | 编排前端预览区执行测试用例 | 逐用例通过/失败结果 | 否 | — |

### 2.4 回流规则

review_severity 分级定义：

| 级别 | 含义 | 示例 | 回流目标 |
|------|------|------|---------|
| `minor` | 代码规范/小Bug | "变量命名不规范"、"缺少 loading 状态" | `code` |
| `moderate` | 结构性代码问题 | "组件拆分不合理"、"错误处理缺失" | `code` |
| `critical` | 设计层面缺陷 | "数据流设计与需求不匹配"、"缺少关键功能模块" | `design` |

```python
# review 节点后
def decide_after_review(state: GenerationState) -> str:
    if state["review_passed"]:
        return "e2e"
    if state["review_severity"] == "critical":  # 设计层面问题
        return "design"
    return "code"  # minor 或 moderate → code 修复

# e2e 节点后
def decide_after_e2e(state: GenerationState) -> str:
    if state["e2e_passed"]:
        return END
    return "code"  # 修复后必须 → review → e2e

# e2e 失败修复后必须过 review 的完整链路：
# e2e fail → code → review → e2e
```

## 3. 核心数据结构

### 3.1 LangGraph State

```python
from typing import TypedDict, Literal

class FailedScenario(TypedDict):
    case_id: str
    name: str
    error: str
    screenshot: str | None  # base64

class FailureDetails(TypedDict):
    source: Literal["review", "e2e"]
    failed_cases: list[dict]  # review 的失败项 或 e2e 的失败场景
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
    # 用户输入
    requirement: str
    component_lib: str          # tailwind | antd | element | echarts
    messages: list[dict]        # 对话历史

    # 阶段产出
    analysis_result: str | None
    design_result: str | None
    code_result: str | None
    review_result: str | None
    e2e_results: list[dict] | None

    # E2E 测试用例（analysis 阶段产出）
    e2e_test_cases: list[dict] | None

    # 校验状态
    review_passed: bool
    review_severity: str | None  # "minor" | "moderate" | "critical"
    e2e_passed: bool

    # 失败详情（回流时传递给目标节点）
    failure_details: FailureDetails | None

    # 循环控制
    rollback_records: list[RollbackRecord]
    rollback_count: dict[str, int]  # {"code": 1, "design": 0}
    max_rollback_per_node: int      # 默认 3
    max_rollback_total: int         # 默认 10
    needs_manual_review: bool       # 熔断标记
```

### 3.2 E2E 测试用例 DSL（v1 简单起步，预留扩展）

```typescript
// 前后端共享类型定义
interface E2ETestStep {
  action: 'click' | 'input' | 'assert' | 'wait'  // v1 四种基础动作
  target: string       // CSS 选择器
  value?: string       // input 输入值 / assert 期望文本 / wait 毫秒数
  description: string  // 人类可读的步骤说明
}

// 扩展预留（v2+）:
// - action: 'drag' | 'upload' | 'navigate' | 'scroll' | 'hover' | 'screenshot'
// - condition?: { if_pass: E2ETestStep[], if_fail: E2ETestStep[] }
// - retry?: { max: number, interval: number }

interface E2ETestCase {
  id: string
  name: string
  description: string
  steps: E2ETestStep[]
}
```

## 4. 前后端通信协议

### 4.1 SSE 事件类型扩展

现有事件保持不变，新增以下事件：

| 事件名 | 方向 | 载荷 | 说明 |
|--------|------|------|------|
| `stage_start` | 后端→前端 | `{stage, timestamp}` | 节点开始执行 |
| `stage_complete` | 后端→前端 | `{stage, summary}` | 节点完成 |
| `stage_rollback` | 后端→前端 | `{from, to, reason, failed_cases}` | 回流事件 |
| `e2e_execute` | 后端→前端 | `{case_id, steps: E2ETestStep[]}` | 指示前端执行单个用例 |
| `e2e_case_result` | 后端→前端 | `{case_id, passed, error?, screenshot?}` | 单用例结果（推给前端展示） |
| `e2e_complete` | 后端→前端 | `{passed, failed_count, total_count}` | E2E 阶段完成汇总 |
| `human_confirm_required` | 后端→前端 | `{stage}` | 需要用户确认才能继续 |
| `loop_warning` | 后端→前端 | `{rollback_count, max, node}` | 回流次数接近上限 |
| `loop_break` | 后端→前端 | `{reason, stage}` | 熔断：强制通过 + 标记人工 |

### 4.2 前端→后端 HTTP 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/e2e/result` | 单用例执行结果回报 `{case_id, passed, error?, screenshot?}` |
| POST | `/api/v1/generation/confirm` | 用户确认继续（analysis/design 阶段后） |
| POST | `/api/v1/generation/start` | 启动生成流程 |
| POST | `/api/v1/generation/cancel` | 取消生成 |

### 4.3 E2E 执行时序

```
Backend (LangGraph)               SSE                    Frontend (Vue)
─────────────────                 ───                    ───────────────

e2e_node 启动
  e2e_start ─────────────────────────────────────▶ 展示测试用例列表
  {test_cases: [...], total: 5}

  for case in test_cases:
    e2e_execute ─────────────────────────────────▶ useE2ERunner.executeCase(case)
    {case_id, steps}                                   │
                                                    在 PreviewFrame iframe 中
    ◀── POST /api/v1/e2e/result ─────────────────────┘   执行步骤，回报结果
    {case_id, passed, error, screenshot}

    e2e_case_result ──────────────────────────────▶ 更新UI (✅/❌)
    {case_id, passed, error, screenshot}

  e2e_complete ───────────────────────────────────▶ 汇总展示
  {passed, failed_count, total_count}

  if not passed:
    stage_rollback ───────────────────────────────▶ StepProgress 回流动画
    {from: "e2e", to: "code", reason: "..."}
```

## 5. Harness 实践

### 5.1 Agent Harness（统一执行壳）

```python
class AgentHarness:
    """每个 LangGraph 节点执行时经过的标准化外壳"""

    def __init__(self):
        self.tracer = Tracer()            # trace_id, span
        self.retry_config = RetryConfig(max_retries=3, backoff=2.0)
        self.schema_validator = SchemaValidator()
        self.token_counter = TokenCounter()

    async def execute(self, node_name: str, state: GenerationState,
                      handler: Callable) -> GenerationState:
        with self.tracer.span(node_name) as span:
            span.set_attribute("input_hash", hash(state))

            for attempt in range(self.retry_config.max_retries):
                try:
                    result = await handler(state)
                    self.schema_validator.validate(result, GenerationState)
                    span.set_attribute("tokens", self.token_counter.used)
                    return result
                except LLMError as e:
                    span.record_exception(e)
                    if attempt == self.retry_config.max_retries - 1:
                        raise
                    await asyncio.sleep(self.retry_config.backoff ** attempt)
```

### 5.2 Eval Harness（校验分层）

```python
# 确定性校验 — 不依赖 LLM
class EvalHarness:
    def compile_check(self, code: str) -> CheckResult:
        """代码能否编译"""
        ...

    def render_check(self, code: str) -> CheckResult:
        """页面能否渲染"""
        ...

# LLM 语义校验 — review 节点
class ReviewAgent:
    def review(self, code: str, design: str) -> ReviewResult:
        """LLM 判断代码是否匹配设计、边界情况、代码规范"""
        ...

# review 节点结合两者：先跑确定性校验，再跑 LLM 语义校验
```

### 5.3 E2E Harness（前端预览区执行引擎）

```typescript
// composables/useE2ERunner.ts
export function useE2ERunner(previewFrameRef: Ref<HTMLIFrameElement>) {
  const results = ref<E2ECaseResult[]>([])
  const running = ref(false)

  async function executeCase(testCase: E2ETestCase): Promise<E2ECaseResult> {
    const iframe = previewFrameRef.value
    if (!iframe?.contentDocument) {
      return { caseId: testCase.id, passed: false, error: 'Preview iframe not available' }
    }

    const doc = iframe.contentDocument
    try {
      for (const step of testCase.steps) {
        await executeStep(doc, step)
      }
      return { caseId: testCase.id, passed: true }
    } catch (e: any) {
      const screenshot = await captureScreenshot(iframe)
      return { caseId: testCase.id, passed: false, error: e.message, screenshot }
    }
  }

  async function executeStep(doc: Document, step: E2ETestStep): Promise<void> {
    const el = doc.querySelector(step.target)
    if (!el && step.action !== 'wait') {
      throw new Error(`Element not found: ${step.target}`)
    }
    switch (step.action) {
      case 'click': (el as HTMLElement).click(); break
      case 'input':
        const input = el as HTMLInputElement
        input.value = step.value || ''
        input.dispatchEvent(new Event('input', { bubbles: true }))
        break
      case 'assert':
        if (!el?.textContent?.includes(step.value || '')) {
          throw new Error(`Expected "${step.value}" in ${step.target}, got "${el?.textContent}"`)
        }
        break
      case 'wait': await new Promise(r => setTimeout(r, Number(step.value) || 1000)); break
    }
  }

  return { results, running, executeCase }
}
```

## 6. Loop Engine 收敛策略

### 6.1 收敛规则

```python
# 规则1：单节点最大回退次数
if rollback_count[node] >= max_rollback_per_node:
    force_pass_with_manual_review(node)

# 规则2：全局最大回退次数
if sum(rollback_count.values()) >= max_rollback_total:
    force_pass_with_manual_review("global")

# 规则3：无改进检测
if current_output_hash == previous_output_hash:
    stop_loop("no improvement detected")

# 规则4：渐进式收紧
# 每次回流到同一节点，降低阈值
# 第1次：严格要求 → 第2次：放宽到严重问题 → 第3次：只要求没有致命问题
```

### 6.2 熔断处理

```python
def force_pass_with_manual_review(state: GenerationState, reason: str):
    state["needs_manual_review"] = True
    state["loop_break_reason"] = reason
    # SSE 推送 loop_break 事件给前端
    # 前端展示：该阶段已通过（需人工复核）
```

### 6.3 可观测性

```python
# 每次回流记录到 RollbackRecord 列表
# 汇总指标：
#  - 平均回流次数 per 阶段
#  - 最常见的回流原因分布 → 用于优化 prompt
#  - 额外 token 成本
#  - 整体通过率
```

## 7. 现有代码改动范围

### 7.1 后端新增/改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `ai-service/app/services/generation/` | **新增** `graph.py` | LangGraph StateGraph 定义 |
| `ai-service/app/services/generation/` | **新增** `nodes.py` | 五个节点的实现 |
| `ai-service/app/services/generation/` | **新增** `harness.py` | AgentHarness / LoopControl |
| `ai-service/app/services/generation/servicer.py` | **改** | 接入 LangGraph app，替换直接的 LLM 调用 |
| `ai-service/app/services/llm/` | **改** | 支持结构化输出（JSON mode），tool calling |
| `gateway/internal/handler/chat.go` | **改** | 新增 SSE 事件类型转发 |
| `gateway/internal/handler/` | **新增** `e2e.go` | E2E 结果回报接口 |
| `proto/ai/v1/generation.proto` | **改** | 扩展消息定义支持新事件 |

### 7.2 前端改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/composables/useMultiAgent.ts` | **重写** | 简化为 SSE 事件监听 + 状态同步 |
| `src/composables/useStreamChat.ts` | **改** | 扩展 SSE 事件解析 |
| `src/composables/` | **新增** `useE2ERunner.ts` | 预览区 E2E 执行引擎 |
| `src/stores/generation.ts` | **改** | 扩展 state 支持五节点 + 测试用例 |
| `src/types/generation.ts` | **改** | 新增类型定义 |
| `src/components/StepProgress.vue` | **改** | 五节点进度条 + 回流动画 |
| `src/components/GenerationView.vue` | **改** | 新增 E2E 测试面板 |
| `src/views/GenerationView.vue` | **改** | 布局调整 |

### 7.3 保持不变

- 微前端架构（qiankun）
- Go Gateway + Python gRPC 整体架构
- PreviewFrame 预览机制
- CodeParser / MultiCompiler 管道
- ChatPanel / ChatInput 对话交互
- 组件库选择（Tailwind/Antd/Element/ECharts）

## 8. 实施路径

分三个阶段渐进式实施，每阶段可独立验证：

### Phase 1：LangGraph 核心后端化
- 搭建 LangGraph StateGraph（5 个节点 + 条件边）
- 实现 AgentHarness（日志/重试/schema 校验）
- 实现 LoopControl 收敛策略
- 保持前后端 SSE 协议兼容（新增事件，不删旧事件）
- **验证标准**：后端能独立跑通 5 节点流水线（用 Python 脚本直接调）

### Phase 2：E2E 节点
- analysis 节点生成测试用例
- 前后端 E2E 通信协议（e2e_execute / e2e_result）
- 前端 useE2ERunner 实现
- **验证标准**：生成一个简单组件，E2E 自动在预览区跑测试

### Phase 3：前端适配 + 回流 UI
- StepProgress 五节点 + 回流动画
- E2E 测试面板（用例列表 + 结果展示）
- 人工确认/熔断提示
- **验证标准**：完整跑通 analysis→design→code→review→e2e→回流→修复→通过的闭环
