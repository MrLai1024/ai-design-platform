# 功能实现节点 ReAct 模式 — 设计方案

> 日期: 2026-07-25
> 状态: 设计完成
> 关联: [[2026-07-22-code-stage-agent-log-design]], [[2026-07-13-full-pipeline-workflow-design]]

## 1. 背景与目标

### 1.1 当前状态

功能实现节点（code node）已完成基础 streaming 改造（`code_node_streaming` + AgentLog 三栏布局），LLM 通过工具调用循环生成多文件工程。但存在以下不足：

- **缺乏显式规划**：任务拆解隐式体现在工具调用中，不可观测、不可干预
- **上下文窗口压力**：所有文件内容 + 工具调用历史共用一个 LLM 会话
- **编译反馈滞后**：编译仅在文件完成后触发，无法边写边校验
- **生成物不标准**：缺乏 qiankun 微应用必需的生命周期文件

### 1.2 目标

将 code node 升级为**全自主 ReAct 智能体**，核心能力：

1. **ReAct 双层循环**：Planner（任务级规划与动态重规划）+ Executor（文件级代码生成与自我纠错）
2. **工具/MCP/Skill 三层体系**：标准化工具调用、MCP 外部知识（真实连接）、Skill 代码模板
3. **上下文窗口管理**：双层上下文模型 + 规则引擎压缩 + 按需检索
4. **实时编译渲染**：Chunk 级增量编译 + HMR 模块热替换
5. **微应用工程生成**：标准 qiankun 工程结构，基座动态加载

### 1.3 设计决策汇总

| 维度 | 决策 |
|------|------|
| ReAct 模式 | 双层循环：Planner (任务级) + Executor (文件级) |
| 微应用形态 | qiankun 子应用标准工程结构 |
| 上下文管理 | 分层摘要 + 滚动窗口（规则引擎压缩为主，LLM 压缩为辅） |
| 实时编译 | Chunk 级增量编译 + HMR 三级热替换 |
| MCP | 从桩实现升级为真实 MCP 连接 |
| 预览 vs 发布 | iframe Runtime Compiler (预览) + webpack 独立工程 (发布) |

---

## 2. ReAct 双循环设计

### 2.1 Planner 层（外层循环 — 任务级）

```
设计文档 → REASON → ACT (输出 Task DAG) → [Executor 执行] → OBSERVE → REFLECT
                ↑                                                          ↓
                └──────────────── 重规划 ──────────────────────────────────┘
```

**REASON 阶段**：
- 解析设计文档，识别组件依赖树、数据流、路由结构
- 评估生成策略（页面优先 vs 组件优先 vs 数据层优先）
- 任务拆解与拓扑排序

**ACT 阶段**：
- 输出结构化 Task DAG JSON：
```json
{
  "tasks": [
    {
      "id": "task-0",
      "type": "bootstrap",
      "description": "qiankun 生命周期入口",
      "deps": [],
      "files": ["src/main.ts", "src/public-path.ts"],
      "contract": { "exports": ["bootstrap", "mount", "unmount"] }
    },
    {
      "id": "task-1",
      "type": "business",
      "description": "Header 组件",
      "deps": ["task-0"],
      "files": ["src/components/Header.vue"],
      "contract": { "exports": ["Header"], "props": ["title", "user"], "events": ["logout"] }
    }
  ]
}
```

**OBSERVE 阶段**：
- 收集各 Executor task 的执行结果
- 汇总编译错误
- 执行接口契约验证（`verify_contract` 工具）

**REFLECT 阶段**：
- 全部通过 → 生成完成
- 部分失败 → 修正 DAG，重新分派
- 阻塞 → 降级策略或人工介入
- 最多重规划 3 次

### 2.2 Executor 层（内层循环 — 文件级）

```
Task 契约 → REASON → ACT (工具调用) → OBSERVE (工具结果) → REFLECT
                ↑                                               ↓
                └─────────── 编译修复循环 (最多 3 轮) ─────────────┘
```

**REASON 阶段**（以 thinking_chunk 流式输出到 AgentLog）：
- 理解子任务目标
- 查阅接口契约和依赖文件摘要
- 选择 Skill 模板
- 规划文件内容

**ACT 阶段**：
- `use_skill` → 生成代码骨架
- `mcp_query` → 获取组件 API 文档
- `create_file` / `write_code` → 逐 chunk 写入文件
- `compile_project` → 编译检查

**OBSERVE 阶段**：
- 工具返回结果 → 状态更新
- 编译错误 → 定位文件/行号

**REFLECT 阶段**：
- 编译通过 → task 完成
- 编译错误 → `fix_error` → 重新 `compile`（最多 3 轮）
- 超轮次 → 返回当前最佳状态 + 标注未完成

### 2.3 每步动作体现

工具调用链在 AgentLog 中完整展示，每步包含：
- 💭 思考文本（流式累加）
- 🔧 工具调用卡片（工具名 + 参数 + 状态）
- 📄 文件生成进度（chunk 流式 + 完成标记）
- ⚡ 编译结果（绿色通过 / 红色错误列表）
- 📊 阶段汇总（文件数 + 错误数）

---

## 3. 工具/MCP/Skill 三层体系

### 3.1 三层架构

```
Tool Layer  — 原子操作: create_file, write_code, compile, lint, dev-server,
                        summarize_context, retrieve_context, verify_contract
Skill Layer — 代码模板: qiankun-app, vue-component, pinia-store, api-service,
                        router-config, form-dialog, table-list, chart-dashboard 等 12 个
MCP Layer   — 外部知识: component-docs (TDesign/Element+), design-tokens,
                        type-registry (已生成文件的 TS 类型)
```

### 3.2 各层职责

| 层 | Planner 使用 | Executor 使用 | 调用频率 |
|----|-------------|---------------|---------|
| Tool | summarize_context, retrieve_context, verify_contract | create_file, write_code, compile, lint | Executor 每轮 1-3 次 |
| Skill | list_skills | use_skill | 每 task 开始 1 次 |
| MCP | — | mcp_query | 按需 |

### 3.3 新增工具

**summarize_context** — 上下文压缩（规则引擎为主，LLM 为辅）
```
输入:  { files: Record<string, string>, max_tokens: number }
输出:  { summary, key_exports: {...}, dropped_details: [...] }
```

**retrieve_context** — 按需检索已生成文件的上下文
```
输入:  { query: string }
输出:  { results: [{file, content_snippet, relevance}] }
```

**verify_contract** — 跨文件接口契约校验
```
输入:  { consumer_file, provider_file, expected_interface }
输出:  { match: boolean, violations: [{type, detail}] }
```

### 3.4 MCP 升级

从桩实现升级为真实 MCP 连接：
- **component-docs**: 通过 `npx @anthropic/mcp-server-tdesign` 或 `@element-plus/mcp` 提供真实组件 API 文档查询
- **design-tokens**: 连接项目设计令牌服务，查询色彩/间距/圆角/阴影值
- **type-registry**: 内部实现，索引已生成文件的 TypeScript 类型定义

---

## 4. 上下文窗口管理

### 4.1 双层上下文模型

**Planner 上下文**（长期记忆，< 60K tokens）：
- 固定保留区：设计文档（完整）、任务 DAG（当前状态）、全局摘要（渐进更新）、关键接口契约（永不删除）
- 滚动窗口区：最近 3 个 task 的完整执行结果、最近编译状态汇总、最近 5 轮对话
- 触发压缩：Planner 上下文 > 70% 窗口限制，或工具调用累积 > 50 次

**Executor 上下文**（短期记忆，< 30K tokens）：
- 加载内容：该 task 的接口契约、依赖文件的接口摘要、最近 10 轮工具调用、该 task 内文件的完整内容
- 不加载：其他 task 的完整文件、历史 task 的工具调用细节、全局摘要中未涉及的无关文件

### 4.2 上下文压缩流水线

```
已完成 Task 结果
  → 1. 提取接口契约 (规则引擎: 解析 SFC/TS 的 export/props/events/slots)
  → 2. 生成文件摘要 (规则引擎: 路径 + 行数 + 核心职责)
  → 3. 合并到全局摘要 (规则引擎: upsert 到 key_exports map)
  → 4. LLM 压缩对话历史 (仅在触发压缩条件时，压缩为 3-5 句关键决策)
```

步骤 1-3 是确定性的，不消耗 LLM token。步骤 4 只在必要时触发。

### 4.3 长文件分段策略

单文件 > 500 行时，`write_code` 分段输出（每段约 150 行），每段 `file_chunk` 后 PreviewFrame 尝试增量编译。语法不完整时标注 `partial` 继续等待。

---

## 5. 边生成、边编译、边渲染

### 5.1 三阶段流水线

```
Stage 1: 代码生成 (LLM write_code) → SSE file_chunk (200 chars)
  → Stage 2: 增量编译 (iframe 内 Vue SFC Runtime Compiler)
  → Stage 3: HMR 渲染 (模块热替换)
```

### 5.2 iframe 内增量编译器

- **IncrementalCompiler**: 累积 file_chunk，文件完成后触发完整编译
- **ModuleRegistry**: 维护 `modules: Map<path, {compiled, hot, deps[]}>`
- **HotReloader**: 编译完成 → 注册模块 → 通知依赖重渲染

### 5.3 HMR 三级替换策略

| 变更类型 | HMR 策略 | 延迟 |
|---------|---------|------|
| `.css` / `<style>` | 热替换 — 替换 `<style>` 文本 | 即时 |
| `.vue` 组件 (template) | 热重渲染 — 重新编译 SFC → forceUpdate | < 200ms |
| `.ts` / `.js` (逻辑) | 温重载 — 重新执行模块 → 重渲染依赖树 | ~500ms |
| `router` / 入口文件 | 全量刷新 — iframe reload | 完整刷新 |

### 5.4 错误分级

- **可恢复错误**（partial）: "Unexpected end of input", "Unterminated string/template", "Unclosed tag/brace" → 等待更多 chunk
- **硬错误**: 明确的语法/类型错误 → AgentLog 红色卡片 → 触发 Executor 修复

---

## 6. 微应用工程生成

### 6.1 标准 qiankun 工程结构

```
generated-app/
├── package.json
├── tsconfig.json
├── webpack/webpack.common.js        ← UMD 输出配置
├── src/
│   ├── main.ts                       ← qiankun 生命周期导出
│   ├── public-path.ts               ← __webpack_public_path__
│   ├── App.vue
│   ├── router/index.ts
│   ├── stores/                       ← Pinia (按需)
│   ├── services/                     ← API 层 (按需)
│   ├── composables/                  ← 组合式函数 (按需)
│   ├── components/                   ← 业务组件
│   └── assets/
└── index.html
```

### 6.2 内置任务

Planner 自动注入 3 个强制 Task（代码由模板生成，非 LLM）：

- **Task: qiankun-bootstrap** — `main.ts`, `public-path.ts`（qiankun 生命周期 100% 正确）
- **Task: webpack-config** — `webpack/webpack.common.js`（UMD 输出）
- **Task: package-config** — `package.json`, `tsconfig.json`

新增 Skill 模板 `qiankun-app.json` 产出以上文件。

### 6.3 预览 vs 发布双模式

| 模式 | 编译环境 | 加载方式 | 用途 |
|------|---------|---------|------|
| 预览模式 | iframe 内 Vue SFC Runtime Compiler | PreviewFrame 直接渲染 | 开发阶段实时预览 |
| 发布模式 | 完整工程 → webpack build | qiankun 基座动态加载 | 正式运行 |

### 6.4 基座动态注册

生成完成后：
1. 自动启动 dev server（端口从 8100 递增）
2. 动态注入 qiankun 注册配置：`{name, entry: '//localhost:{port}', container, activeRule}`
3. 用户访问 `/generated/{appName}` → qiankun 加载 UMD bundle → 微应用渲染

---

## 7. Planner-Executor 协作流程总览

```
设计文档
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ Planner (ReAct 外层)                                  │
│                                                       │
│ REASON: 解析设计 → 识别组件树 → 评估策略 → 任务拆解      │
│ ACT:    输出 Task DAG JSON (含 bootstrap 内置任务)      │
│                                                       │
│    ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│    │ Executor │  │ Executor │  │ Executor │  ...      │
│    │ Task#0   │  │ Task#1   │  │ Task#2   │          │
│    │ REASON   │  │ REASON   │  │ REASON   │          │
│    │  → ACT   │  │  → ACT   │  │  → ACT   │          │
│    │  → OBS   │  │  → OBS   │  │  → OBS   │          │
│    │  → REFL  │  │  → REFL  │  │  → REFL  │          │
│    └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│         │             │             │                 │
│    OBSERVE: 收集结果 + 编译汇总 + 契约校验              │
│    REFLECT: 通过? → 完成 / 失败? → 重规划              │
└─────────────────────────────────────────────────────┘
    │
    ▼
生成完成 → [下一步 ▸] → review node
```

---

## 8. SSE 事件协议扩展

### 8.1 新增事件

| 事件 | 载荷 | 触发时机 | 前端行为 |
|------|------|---------|---------|
| `planner_start` | `{tasks: [...], summary: "..."}` | Planner 输出 Task DAG | AgentLog 展示任务列表 |
| `task_start` | `{task_id, description, files}` | Executor 开始执行 task | AgentLog 展开 task 分组 |
| `task_complete` | `{task_id, summary}` | Executor 完成任务 | AgentLog 标记 task ✅ |
| `task_failed` | `{task_id, reason}` | Executor 失败 | AgentLog 标记 task ❌ |
| `planner_reflect` | `{decision, reason}` | Planner 重规划决策 | AgentLog 📊 汇总卡片 |
| `contract_verify` | `{match, violations}` | 契约校验结果 | AgentLog 校验卡片 |
| `context_summarized` | `{before_tokens, after_tokens}` | 上下文压缩完成 | AgentLog 信息卡片 |

### 8.2 现有事件扩展

| 事件 | 新增字段 |
|------|---------|
| `compile_status` | `is_partial: boolean` — 标识编译是否因文件不完整而跳过 |
| `file_chunk` | `chunk_index: number, is_last_chunk_for_file: boolean` |
| `code_gen_done` | `app_entry: string, app_port: number` — 微应用入口 URL |

---

## 9. 实施计划概要

### Phase 1: Planner Agent 实现（3-4 天）
- 新增 `planner_node` 或改造 `code_node_streaming` 为 Planner + Executor 模式
- 实现 Task DAG 数据结构（`state.py` 新增字段）
- 实现 Planner Prompt 模板
- 前端 AgentLog 新增 task 分组展示

### Phase 2: Executor 独立上下文（2-3 天）
- Executor 会话工厂：每个 task 创建独立 LLM 会话
- 上下文管理工具：`summarize_context`, `retrieve_context`
- 后端上下文压缩流水线（规则引擎部分）

### Phase 3: 微应用工程模板（2 天）
- 新增 Skill: `qiankun-app.json`
- 内置 Task 模板（main.ts, webpack config, package.json）
- 基座动态注册逻辑

### Phase 4: iframe 增量编译 + HMR（3-4 天）
- IncrementCompiler + ModuleRegistry + HotReloader
- HMR 三级替换策略实现
- 可恢复错误 vs 硬错误判断逻辑
- PreviewFrame 与 AgentLog 编译卡片联动

### Phase 5: MCP 真实连接（1-2 天）
- component-docs MCP server 真实连接
- type-registry 内部实现

### 文件改动总览

| 类型 | 后端 | 前端 |
|------|------|------|
| 新建 | `planner.py`, `context_manager.py`, `contract_verifier.py` | — |
| 重写 | `nodes.py` (code_node → planner + executor), `graph.py` (Phase 3) | `AgentLog.vue` (task 分组), `PreviewFrame.vue` (HMR) |
| 扩展 | `state.py` (Task DAG), `tools/registry.py` (新工具), `tools/mcp_bridge.py` (真实连接), `tools/skill_loader.py` (qiankun-app) | `CodeStagePanel.vue`, `useCodeStream.ts`, `generation.ts` |
| 新增 Skill | `skills/qiankun-app.json` | — |

**总工期估算**：11-15 天

---

## 10. 风险与边界

| 风险 | 缓解措施 |
|------|---------|
| Planner 任务拆解不合理 | Prompt Engineering + 设计文档结构化约束（组件树、数据流必须明确） |
| Executor 上下文过小导致生成质量下降 | 接口契约摘要保持足够的类型信息，关键依赖代码片段保留 |
| HMR 编译性能问题 | iframe 内编译仅处理当前变更文件，不重编译整个工程 |
| qiankun 动态注册端口冲突 | 端口自动检测 + 递增分配（8100-8199） |
| MCP 服务不可用 | 降级到 LLM 记忆生成（当前行为），AgentLog 标注超时 |
