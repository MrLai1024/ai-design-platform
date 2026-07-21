# 需求分析 Agent 设计方案

> 日期: 2026-07-09
> 状态: 设计中
> 关联: [[2026-06-30-multi-agent-generation-design]], [[2026-07-01-langgraph-multi-agent-refactor-design]]

## 1. 背景与动机

### 1.1 当前状态

Multi-Agent 代码生成流水线中，第 1 阶段"需求分析 Agent"目前使用简单的 system prompt 驱动：要求 Agent 每轮提 1-2 个问题，约 2-4 轮后输出需求规格文档。该实现存在以下不足：

- **策略粗放**：Agent 不知道什么该问、什么该跳，缺乏系统性的提问策略
- **缺乏结构化追踪**：需求信息散落在聊天消息中，无法跟踪完整度
- **无自适应能力**：对技术/非技术用户采用相同的提问方式
- **线性不可回溯**：PRD 生成后无法补充修改，不支持增量迭代
- **无进度感知**：用户不知道还需要回答多少问题

### 1.2 目标

将需求分析 Agent 升级为**三层递进式对话引擎**：

1. 用户在聊天中逐步澄清需求，Agent 自适应提问
2. 右侧面板实时展示结构化卡片（项目愿景 → 功能页面 → 细节补充）
3. 每层卡片用户确认后进入下一层，最终流式生成完整 PRD
4. 支持增量需求：PRD 生成后可回退编辑、追加新模块、会话恢复

### 1.3 设计决策

| 维度 | 决策 |
|------|------|
| 目标用户 | 混合（非技术 PM + 技术开发者），Agent 自适应 |
| 分析终点 | 输出结构化 PRD 文档 |
| 交互方式 | 分阶段混合：聊天收集 → 结构化卡片 review |
| 系统定位 | 升级现有 Multi-Agent 流水线中第 1 阶段需求分析 Agent |
| PRD 输出 | 需求分析 Agent 面板内流式输出 |

## 2. 方案选型

### 2.1 方案对比

| 维度 | A: 维度清单 BFS | B: 自适应深度优先 | C: 分层递进 (选中) |
|------|---------------|-----------------|------------------|
| 覆盖完整性 | 高（预定义清单） | 中（需要安全网） | 高（维度内嵌于三层） |
| 对话自然度 | 低（机械感强） | 高（聚焦关键模糊点） | 高（由粗到细天然节奏） |
| 实现复杂度 | 低 | 高（需不确定性建模） | 中 |
| 增量需求支持 | 弱（重新跑清单） | 中 | 强（直接切入对应层） |
| 用户进度感知 | 强（百分比） | 弱（无清晰边界） | 强（三层里程碑） |
| 与现有交互模式匹配 | 弱 | 中 | 强（天然匹配分阶段混合模式） |

选择**方案 C：分层递进 + 回答驱动模板**。

### 2.2 推荐理由

1. 三层结构天然匹配"聊天收集 → 卡片确认"的分阶段交互模式
2. 每层有明确的退出条件和可确认的产出，用户始终知道在哪个阶段
3. 专业技术用户可快速跳过 Layer 1，非技术用户可在每层慢慢聊
4. 增量需求可直接切入对应层（追加功能 → Layer 2，补充细节 → Layer 3）
5. 可复用现有 StepProgress 组件展示层次进度

## 3. 核心引擎：三层对话引擎

### 3.1 架构

```
┌──────────────────────────────────────────────────────┐
│  RequirementsAnalysisAgent                           │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │  LayerManager (三层状态机)                     │    │
│  │                                              │    │
│  │  Layer 1: VisionAligner   愿景对齐            │    │
│  │  Layer 2: FeatureDecomposer 功能分解          │    │
│  │  Layer 3: DetailFiller   细节补充             │    │
│  │                                              │    │
│  │  每层: 对话收集 → 卡片更新 → 用户确认 → 下层  │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │  QuestionStrategist (提问策略引擎)             │    │
│  │  - 自适应判断: 用户技术水平? 需求复杂度?       │    │
│  │  - 优先级排序: 当前层内哪个维度最模糊?         │    │
│  │  - 问题生成: 多选引导 / 开放追问 / 跳过建议   │    │
│  │  - 防过载: 每轮最多 2 个问题, 可选跳过        │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │  RequirementsState (需求状态存储)             │    │
│  │  - 结构化存储: 功能/角色/页面/数据/交互/技术  │    │
│  │  - 每项有: content, confidence, source, gaps │    │
│  │  - 增量更新, 支持回退修改                     │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │  PRDGenerator (文档生成器)                    │    │
│  │  - 从 RequirementsState 拼装 PRD              │    │
│  │  - 流式输出 SSE 事件到前端面板                │    │
│  │  - 结构化 Markdown: 概述/功能/页面/数据/交互  │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 3.2 三层定义

```
Layer 1: 愿景对齐（1-3 轮）
├── 问题领域: 谁？解决什么问题？成功标准？范围边界？
├── 输出卡片: 项目愿景卡片（名称/用户/问题/成功标准/范围）
└── 退出条件: 核心问题 + 目标用户 + 成功标准均已明确

Layer 2: 功能分解（2-5 轮）
├── 问题领域: 有哪些功能模块？页面结构树？
├── 输出卡片: 功能模块列表 + 页面结构树
└── 退出条件: 所有 must-have 功能模块完整度 ≥ 80%

Layer 3: 细节补充（1-3 轮）
├── 问题领域: 关键页面交互细节、数据字段、技术约束
├── 输出卡片: 页面详描 + 技术约束 + 数据实体
└── 退出条件: 关键页面字段和操作已覆盖 OR 用户主动生成
```

### 3.3 LayerManager 状态机

```
IDLE
  ├── NEW ──▶ Layer1 → (确认) → Layer2 → (确认) → Layer3 → (确认) → PRD_GENERATING → DONE
  ├── EDIT ──▶ 用户选择层 → (修改) → PRD_GENERATING → DONE
  ├── APPEND ──▶ Layer2(追加模式) → Layer3(追加模式) → PRD_GENERATING → DONE
  └── CONTINUE ──▶ 从 DB 恢复 → 断点所在层继续 → ...

任意层可被用户中断/回退
```

### 3.4 防过载机制

- **每轮最多 2 个问题**，第二个标注"(可选)"
- **进度感知**：问题后附上 "当前进度: Layer 2/3 · 功能模块已明确 4 个 · 还有 2 个待确认"
- **跳过策略**：每个问题提供 "先跳过" 选项
- **复杂度自适应**：简单需求快速模式（每层 1-2 轮），复杂需求全量模式

## 4. 增量需求支持

### 4.1 四种进入模式

| 模式 | 入口 | 行为 | 适用场景 |
|------|------|------|---------|
| NEW | 用户输入新需求 | 空白状态，从 Layer 1 开始 | 全新项目 |
| EDIT | PRD 生成后点击"编辑补充" | 携带现有 state，用户选择从哪层切入 | 遗漏补充 |
| APPEND | 已有 PRD，输入"再加一个模块" | 保留现有 state，跳到 Layer 2，只追问新增部分 | 迭代增强 |
| CONTINUE | 打开历史会话 | 从 DB 恢复 state，断点继续 | 会话恢复 |

### 4.2 APPEND 模式关键逻辑

```python
# layer_manager.py
def enter_mode(self, mode: str, existing_state: RequirementsState = None):
    if mode == 'append':
        self.state = existing_state.clone()
        self.state.mode = 'append'
        self.state.version += 1
        self.state.parent_version = existing_state.version
        self.current_layer = 2  # 跳过愿景对齐
        self.state.mark_existing_as_confirmed()  # 已有内容不可编辑
        # Agent 只对新增模块提问
```

### 4.3 增量 PRD 生成

```
APPEND 模式 PRD 事件流:
  ◀── SSE: prd_diff_start {parent_version: 1, new_version: 2}
  ◀── SSE: prd_diff {change: "unchanged", section: "overview", ...}   → 前端折叠
  ◀── SSE: prd_diff {change: "added", section: "features", ...}       → 前端高亮 🆕
  ◀── SSE: prd_diff {change: "modified", section: "pages", ...}       → 前端标记 ✏️
  ◀── SSE: prd_diff_done {version: 2, summary: "新增 1 个功能模块、2 个页面"}
```

## 5. 前端设计

### 5.1 页面布局

```
┌──────────────────────────────────────────────────────────┐
│  StepProgress: ① 需求分析 ◉ ── ② 详细设计 ○ ── ③ 代码实现 ○ │
├──────────────────────────┬───────────────────────────────┤
│  ChatPanel (左 40%)       │  AnalysisPanel (右 60%)        │
│                          │                               │
│  聊天消息列表              │  [🆕 新建] [✏️ 编辑] [➕ 追加]    │
│  (消息带层标签)            │                               │
│                          │  ┌ 层进度 ──────────────────┐  │
│                          │  │ ● 愿景  ○ 功能  ○ 细节    │  │
│                          │  └──────────────────────────┘  │
│                          │                               │
│                          │  ┌ 当前卡片 ────────────────┐  │
│                          │  │ (按层动态渲染)            │  │
│                          │  └──────────────────────────┘  │
│                          │                               │
│  ┌──────────────────┐   │  ┌ PRD 生成面板 (流式输出) ───┐  │
│  │ 输入框            │   │  │ ## 需求规格文档             │  │
│  │ [确认进入下一步]   │   │  │ ## 1. 功能概述              │  │
│  └──────────────────┘   │  │ 客户管理系统旨在... █         │  │
│                          │  └─────────────────────────────┘  │
└──────────────────────────┴───────────────────────────────┘
```

右侧面板两种模式：
- **卡片模式**（Layer 1-3 进行中）：层进度 + 当前卡片 + 编辑/确认按钮
- **生成模式**（PRD 生成中）：流式 Markdown 渲染，完成后显示操作栏

### 5.2 三层卡片设计

**Layer 1 — 项目愿景卡片**

```
┌────────────────────────────────────┐
│ ● 愿景对齐    ○ 功能分解    ○ 细节补充 │
├────────────────────────────────────┤
│ 📋 项目名称                         │
│ ┌────────────────────────────────┐ │
│ │ 客户关系管理系统 (CRM)          │ │
│ └────────────────────────────────┘ │
│                                    │
│ 👥 目标用户                         │
│ ┌────────────────────────────────┐ │
│ │ ✓ 内部销售团队                  │ │
│ │ ✓ 销售管理者（看报表）           │ │
│ │ + 添加                          │ │
│ └────────────────────────────────┘ │
│                                    │
│ 🎯 核心问题                         │
│ ┌────────────────────────────────┐ │
│ │ 销售团队客户跟进不及时，          │ │
│ │ 缺乏统一的客户信息管理工具        │ │
│ └────────────────────────────────┘ │
│                                    │
│ ✅ 成功标准                         │
│ ┌────────────────────────────────┐ │
│ │ ✓ 销售可在一屏完成客户跟进       │ │
│ │ ○ 管理者可查看团队业绩报表       │ │
│ │ + 添加                          │ │
│ └────────────────────────────────┘ │
│                                    │
│ 📐 范围说明                         │
│ ┌────────────────────────────────┐ │
│ │ 本期只做客户管理和销售跟进，      │ │
│ │ 合同管理和数据分析下期再做        │ │
│ └────────────────────────────────┘ │
│                                    │
│ [✏️ 编辑]              [确认进入 →] │
└────────────────────────────────────┘
```

**Layer 2 — 功能模块 + 页面结构卡片**

```
┌────────────────────────────────────┐
│ ✓ 愿景对齐    ● 功能分解    ○ 细节补充 │
├────────────────────────────────────┤
│ 🗂️ 功能模块                   完整度  │
│ ┌────────────────────────────────┐ │
│ │ 客户管理    ████████░░ 80%      │ │
│ │  ├ 客户列表/搜索/筛选           │ │
│ │  ├ 客户详情查看                 │ │
│ │  └ 客户信息编辑                 │ │
│ │                                │ │
│ │ 销售跟进    ████░░░░░░ 40%  [补]│ │
│ │  ├ 跟进记录                     │ │
│ │  └ ?                           │ │
│ │                                │ │
│ │ 数据报表    ░░░░░░░░░░  0%  [补]│ │
│ │                                │ │
│ │ + 添加功能模块                   │ │
│ └────────────────────────────────┘ │
│                                    │
│ 🗺️ 页面结构                        │
│ ┌────────────────────────────────┐ │
│ │ 📄 首页 (dashboard)             │ │
│ │  ├── 📄 客户列表 (list)         │ │
│ │  │    └── 📄 客户详情 (detail)  │ │
│ │  ├── 📄 跟进看板 (dashboard)    │ │
│ │  └── 📄 业绩报表 (dashboard)    │ │
│ │                                │ │
│ │ [+ 添加页面]                    │ │
│ └────────────────────────────────┘ │
│                                    │
│ [✏️ 编辑]              [确认进入 →] │
└────────────────────────────────────┘
```

**Layer 3 — 页面详情 + 技术约束 + 数据实体卡片**

```
┌────────────────────────────────────┐
│ ✓ 愿景对齐    ✓ 功能分解    ● 细节补充 │
├────────────────────────────────────┤
│ 📝 页面详情                [客户详情]│
│ ┌────────────────────────────────┐ │
│ │ 展示字段:                       │ │
│ │ 客户名称  文本  ✓               │ │
│ │ 联系电话  文本  ✓               │ │
│ │ 所属行业  下拉  ✓               │ │
│ │ 客户等级  标签  ✓               │ │
│ │ 创建时间  日期  ✓               │ │
│ │ + 添加字段                      │ │
│ │                                │ │
│ │ 操作按钮:                       │ │
│ │ [编辑] [添加跟进] [删除]        │ │
│ │ + 添加操作                      │ │
│ │                                │ │
│ │ 关联数据:                       │ │
│ │ 跟进记录列表 · 合同列表         │ │
│ └────────────────────────────────┘ │
│                                    │
│ 🔧 技术约束                        │
│ ┌────────────────────────────────┐ │
│ │ 前端框架:  Vue 3                │ │
│ │ 组件库:    待确认               │ │
│ │ 数据来源:  REST API             │ │
│ │ 特殊要求:  需支持移动端          │ │
│ └────────────────────────────────┘ │
│                                    │
│ 📊 数据实体                        │
│ ┌────────────────────────────────┐ │
│ │ 客户: 名称/电话/行业/等级/...   │ │
│ │ 跟进记录: 时间/内容/类型/...     │ │
│ │ + 添加实体                      │ │
│ └────────────────────────────────┘ │
│                                    │
│ [✏️ 编辑]          [生成需求文档 →] │
└────────────────────────────────────┘
```

### 5.3 组件树

```
GenerationView (已有)
├── ChatPanel (修改: 消息带层标签、确认推进按钮)
└── RightPanel (修改: 替换原有右侧内容)
    ├── AnalysisPanel (新增)
    │   ├── LayerProgress       — 三层进度指示器
    │   ├── ModeSelector        — 新建/编辑/追加 模式切换
    │   ├── VisionCard          — Layer 1 项目愿景卡片
    │   ├── FeatureCard         — Layer 2 功能模块 + 页面树卡片
    │   ├── DetailCard          — Layer 3 页面详情 + 技术约束 + 数据实体卡片
    │   └── PRDGeneratorView    — PRD 流式生成 + 完成后操作栏
    └── (已有: StageOutput, TabBar, PreviewFrame, FileExplorer)
```

### 5.4 技术选型

| 层 | 选型 | 理由 |
|----|------|------|
| 状态管理 | Redux Toolkit (已有) | 扩展 generation store |
| 卡片 UI | 自定义 Vue 组件 + Tailwind | 可编辑字段、动态表单、拖拽排序 |
| Markdown 渲染 | markdown-it (已有) | PRD 流式渲染 |
| SSE 客户端 | event-source-polyfill (已有) | 与 ai-generation-app 保持一致 |

## 6. 数据模型

### 6.1 RequirementsState（核心状态）

```typescript
// types/requirements.ts

interface RequirementsState {
  // 元信息
  session_id: string
  mode: 'new' | 'edit' | 'append' | 'continue'
  version: number
  parent_version: number | null
  layer: 0 | 1 | 2 | 3
  layer_status: Record<string, 'pending' | 'active' | 'done'>
  history: StateSnapshot[]

  // Layer 1: 愿景对齐
  vision: {
    project_name: string
    target_users: { role: string; description: string }[]
    core_problem: string
    success_criteria: string[]
    scope_note: string
  }

  // Layer 2: 功能分解
  features: FeatureModule[]
  pages: PageNode[]

  // Layer 3: 细节补充
  page_details: Record<string, PageDetail>
  tech_constraints: TechConstraints
  data_entities: DataEntity[]
}

interface FeatureModule {
  id: string
  name: string
  description: string
  priority: 'must' | 'should' | 'nice'
  completeness: number              // 0-100, Agent 评估
  confirmed: boolean                // APPEND 模式下已有模块标记 confirmed
}

interface PageNode {
  id: string
  name: string
  parent_id: string | null
  page_type: 'list' | 'detail' | 'form' | 'dashboard' | 'custom'
  features: string[]                // 关联的功能模块 id
}

interface PageDetail {
  display_fields: FieldDef[]
  action_buttons: ActionDef[]
  related_data: string[]
  layout_notes: string
}

interface FieldDef {
  name: string
  type: 'text' | 'number' | 'date' | 'dropdown' | 'tag' | 'boolean' | 'custom'
  required: boolean
}

interface ActionDef {
  label: string
  type: 'edit' | 'create' | 'delete' | 'export' | 'custom'
}

interface TechConstraints {
  framework: string
  component_lib: string
  data_source: string
  special_requirements: string[]
}

interface DataEntity {
  name: string
  fields: { name: string; type: string; required: boolean }[]
}

interface StateSnapshot {
  timestamp: number
  layer: number
  reason: string                     // 为什么创建快照 (layer_done / edit / append)
  state: RequirementsState           // 深拷贝
}
```

### 6.2 generation store 扩展

```typescript
// 现有 store 新增字段
{
  // 新增
  requirementsState: RequirementsState | null
  analysisPanelMode: 'card' | 'prd'           // 右侧面板模式
  prdStreamingContent: string                 // PRD 流式累积内容
  prdCurrentSection: string | null            // 当前正在生成的章节名
  prdVersion: number                          // 当前 PRD 版本

  // 修改 stageOutputs.analysis 语义
  // 旧: stageOutputs.analysis: string | null
  // 新: stageOutputs.analysis: {
  //       requirements: RequirementsState
  //       prd_markdown: string
  //     } | null
}
```

## 7. SSE 事件协议

### 7.1 需求分析新增事件

| 事件 | 方向 | 载荷 | 前端行为 |
|------|------|------|---------|
| `requirement_mode_set` | ← | `{mode: "new", version: 1}` | 设置模式标签 |
| `requirement_layer_start` | ← | `{layer: 1, label: "愿景对齐", total_layers: 3}` | 更新层进度指示器 |
| `requirement_card_update` | ← | `{layer: 1, card_type: "vision", fields: {...}}` | 增量覆盖卡片字段 |
| `requirement_question` | ← | `{questions: [{text, options?, skippable}], progress: {...}}` | ChatPanel 渲染问题 |
| `requirement_layer_done` | ← | `{layer: 1, summary: "..."}` | 层标记完成，等待用户确认 |
| `prd_generate_start` | ← | `{mode: "full"\|"diff", sections_count: 5, parent_version: null\|1}` | 右侧切换到生成模式 |
| `prd_section` | ← | `{section_key: "overview", content: "..."}` | 流式追加 Markdown 片段 |
| `prd_section_complete` | ← | `{section_key: "overview"}` | 标记该章节完成 |
| `prd_diff` | ← | `{change: "added"\|"modified"\|"unchanged", section: "...", content: "..."}` | 增量渲染，新增/修改高亮 |
| `prd_diff_done` | ← | `{version: 2, summary: "新增 1 个模块、2 个页面"}` | 展示变更摘要 |
| `prd_generate_done` | ← | `{version: 2, full_content: "...", duration_ms: 2300}` | 展示完整文档 + 操作栏 |

### 7.2 时序

```
用户输入 "我想做一个客户管理系统"
    │
POST /api/v1/chat/stream  ──▶  RequirementsAnalysisAgent 启动
    │                           ├── 评估: NEW 模式
    ◀── SSE: requirement_mode_set {mode: "new", version: 1}
    ◀── SSE: requirement_layer_start {layer: 1, ...}
    ◀── SSE: requirement_question {questions: [{text: "主要给谁用？", options: [...]}]}
    ◀── SSE: requirement_card_update {layer: 1, card_type: "vision", fields: {...}}
    │
用户回答 "内部销售团队"
    │
POST /api/v1/chat/stream  ──▶  Agent 处理回答 → 更新 state → 判断层未完成
    ◀── SSE: requirement_question {questions: [{text: "核心解决的问题？"}]}
    ◀── SSE: requirement_card_update {layer: 1, ...}
    │
用户回答 "客户跟进不及时..."
    │
POST /api/v1/chat/stream  ──▶  Agent 判断 Layer 1 完成
    ◀── SSE: requirement_layer_done {layer: 1, summary: "..."}
    │
用户点击 "确认进入下一步"
    │
POST /api/v1/chat/stream  ──▶  Agent 进入 Layer 2
    ◀── SSE: requirement_layer_start {layer: 2, ...}
    ◀── SSE: requirement_question {questions: [{text: "核心功能模块有哪些？"}]}
    ◀── SSE: requirement_card_update {layer: 2, card_type: "features", fields: {...}}
    │
    ... (Layer 2 对话 + Layer 3 对话类似)
    │
用户点击 "生成需求文档"
    │
POST /api/v1/chat/stream  ──▶  PRDGenerator 启动
    ◀── SSE: prd_generate_start {mode: "full", sections_count: 5}
    ◀── SSE: prd_section {section_key: "overview", content: "## 1. 功能概述\n..."}
    ◀── SSE: prd_section {section_key: "overview", content: "..."}
    ◀── SSE: prd_section_complete {section_key: "overview"}
    ◀── SSE: prd_section {section_key: "features", content: "## 2. 功能模块\n..."}
    ... (流式输出所有章节)
    ◀── SSE: prd_generate_done {version: 1, full_content: "...", duration_ms: 2300}
    │
用户看到完整 PRD，可 [📝 编辑补充] [🔀 进入详细设计] [📥 导出]

--- 增量追加场景 ---

用户点击 "📝 编辑补充" → 选择 "添加新功能模块" → 输入 "再加一个审批模块"
    │
POST /api/v1/chat/stream  ──▶  Agent 进入 APPEND 模式
    ◀── SSE: requirement_mode_set {mode: "append", version: 2}
    ◀── SSE: requirement_layer_start {layer: 2, ...}
    (跳到 Layer 2, 已有功能标记 confirmed, 只问审批模块)
    ...
    用户确认 → 生成
    ◀── SSE: prd_generate_start {mode: "diff", sections_count: 5, parent_version: 1}
    ◀── SSE: prd_diff {change: "unchanged", section: "overview", ...}
    ◀── SSE: prd_diff {change: "added", section: "features", content: "### 审批模块..."}
    ◀── SSE: prd_diff_done {version: 2, summary: "新增 1 个功能模块、2 个页面"}
```

## 8. 系统集成

### 8.1 useMultiAgent 改造

```typescript
// composables/useMultiAgent.ts

function useMultiAgent() {
  // --- 现有逻辑保留 ---

  // --- 新增：需求分析 SSE 事件处理 ---
  function handleRequirementSSE(event: SSEEvent) {
    const store = useGenerationStore()

    switch (event.type) {
      case 'requirement_mode_set':
        store.requirementsState.mode = event.mode
        store.requirementsState.version = event.version
        break

      case 'requirement_layer_start':
        store.requirementsState.layer = event.layer
        store.requirementsState.layer_status[event.layer] = 'active'
        break

      case 'requirement_card_update':
        // 增量合并卡片字段到 requirementsState
        store.patchRequirementsState(event.fields)
        break

      case 'requirement_question':
        // 问题通过现有 ChatPanel 消息流展示
        // progress 信息更新到 AnalysisPanel
        break

      case 'requirement_layer_done':
        store.requirementsState.layer_status[event.layer] = 'done'
        break

      case 'prd_generate_start':
        store.analysisPanelMode = 'prd'
        store.prdStreamingContent = ''
        break

      case 'prd_section':
        store.prdStreamingContent += event.content
        break

      case 'prd_section_complete':
        store.prdCurrentSection = null
        break

      case 'prd_diff':
        // 增量模式: 按 change 类型追加并标记
        store.appendPRDDiff(event.change, event.section, event.content)
        break

      case 'prd_diff_done':
        store.prdVersion = event.version
        break

      case 'prd_generate_done':
        store.prdVersion = event.version
        store.stageOutputs.analysis = {
          requirements: store.requirementsState,
          prd_markdown: event.full_content,
        }
        break
    }
  }
}
```

### 8.2 后端新增模块

```
ai-service/app/services/generation/
├── requirements/                           ← 新增 package
│   ├── __init__.py
│   ├── layer_manager.py                   ← LayerManager: 三层状态机 + 模式路由
│   ├── question_strategist.py             ← QuestionStrategist: 自适应提问引擎
│   ├── requirements_state.py              ← RequirementsState: 数据模型 + 序列化
│   ├── prd_generator.py                   ← PRDGenerator: 流式文档生成 (full + diff)
│   └── prompts/                           ← 每层 system prompt 模板
│       ├── vision_align.txt               ← Layer 1: 愿景对齐 prompt
│       ├── feature_decompose.txt          ← Layer 2: 功能分解 prompt
│       └── detail_fill.txt               ← Layer 3: 细节补充 prompt
├── nodes.py                                ← 修改: analysis_node 集成 requirements/ 模块
└── servicer.py                             ← 修改: 新增 SSE 事件类型

ai-service/app/db/                          ← 可选: RequirementsState 持久化
└── requirements_repo.py                   ← 新增: save/load state for CONTINUE 模式
```

### 8.3 复用现有基础设施

| 现有模块 | 复用方式 |
|---------|---------|
| `useMultiAgent` (composable) | 扩展 SSE 事件处理，增加需求分析事件分支 |
| `StepProgress` (组件) | 用于展示三层进度（①→②→③） |
| `StageOutput` (组件) | 可复用 Markdown 渲染部分给 PRDGeneratorView |
| `ChatPanel` (组件) | 消息增加层标签，支持 `requirement_question` 渲染 |
| `generation store` | 扩展 state 字段 |
| `GenerationState` (后端) | 原有字段不变，新增 requirements 相关字段 |
| `GraphSSEHandler` (Gateway) | 复用 SSE 事件转发机制 |
| `_llm_generate()` (后端) | QuestionStrategist 和 PRDGenerator 调用 LLM |

## 9. 安全考量

### 9.1 Prompt 注入防护

- QuestionStrategist 的用户输入在拼入 prompt 前做转义
- 卡片编辑内容通过 `{state.xxx}` 模板安全注入，不直接拼接

### 9.2 数据安全

- RequirementsState 仅包含需求描述，不包含可执行代码
- PRDGenerator 输出纯 Markdown，无 XSS 风险（前端 markdown-it 渲染前做 sanitize）

## 10. 实施路径

### Phase 1: 后端核心 — RequirementsState + LayerManager + QuestionStrategist

- 实现 `requirements_state.py`（数据模型 + JSON 序列化）
- 实现 `question_strategist.py`（自适应提问 + 完整度评估）
- 实现 `layer_manager.py`（状态机 + 3 层流转逻辑）
- 实现 3 个 prompt 模板
- 修改 `nodes.py` 的 `analysis_node`，集成 LayerManager
- **验证标准**: 用 Python 脚本模拟对话，Agent 能按三层递进提问，正确评估完整度并流转

### Phase 2: 后端 PRD 生成 — PRDGenerator + SSE 事件

- 实现 `prd_generator.py`（full 模式流式生成 + diff 模式增量生成）
- 修改 `servicer.py` 新增 SSE 事件类型
- 实现 APPEND 模式的 state 差异计算
- **验证标准**: 从完整的 RequirementsState 能流式生成 PRD；从增量 state 能正确输出 diff

### Phase 3: 前端分析面板 — 卡片 + SSE 消费

- 新增 `AnalysisPanel` 组件 + 三个卡片子组件 (`VisionCard`, `FeatureCard`, `DetailCard`)
- 新增 `PRDGeneratorView` 组件（流式 Markdown 渲染 + 完成后操作栏）
- 新增 `LayerProgress` + `ModeSelector` 组件
- 扩展 `useMultiAgent` 的 SSE 事件处理
- 扩展 `generation store`
- **验证标准**: 端到端对话 → 卡片实时更新 → 层确认流转 → PRD 流式输出

### Phase 4: 增量需求 + 会话恢复

- 实现 EDIT / APPEND / CONTINUE 三种模式的完整链路
- 实现 `requirements_repo.py`（DB 持久化）
- 实现 PRD diff 渲染（前端高亮新增/修改）
- **验证标准**: 在已有 PRD 上追加新模块 → Agent 只问新模块 → PRD diff 正确展示

## 11. 文件改动清单

### 后端新增

| 文件 | 说明 |
|------|------|
| `ai-service/app/services/generation/requirements/__init__.py` | 新 package |
| `ai-service/app/services/generation/requirements/requirements_state.py` | RequirementsState 数据模型 |
| `ai-service/app/services/generation/requirements/layer_manager.py` | 三层状态机 + 模式路由 |
| `ai-service/app/services/generation/requirements/question_strategist.py` | 自适应提问引擎 |
| `ai-service/app/services/generation/requirements/prd_generator.py` | 流式 PRD 生成器 |
| `ai-service/app/services/generation/requirements/prompts/vision_align.txt` | Layer 1 prompt |
| `ai-service/app/services/generation/requirements/prompts/feature_decompose.txt` | Layer 2 prompt |
| `ai-service/app/services/generation/requirements/prompts/detail_fill.txt` | Layer 3 prompt |
| `ai-service/app/db/requirements_repo.py` | RequirementsState DB 持久化 |

### 后端修改

| 文件 | 变更 |
|------|------|
| `ai-service/app/services/generation/nodes.py` | `analysis_node()` 集成 LayerManager 替代裸 prompt |
| `ai-service/app/services/generation/servicer.py` | 新增 requirement_* 和 prd_* SSE 事件 |
| `ai-service/app/services/generation/graph.py` | 扩展 GenerationState 包含 requirements 相关字段 |

### 前端新增

> 所有前端文件位于 `ai-design-platform-web/packages/ai-generation-app/` 下，以下使用包内相对路径。

| 文件 | 说明 |
|------|------|
| `src/components/AnalysisPanel.vue` | 需求分析右侧面板容器 |
| `src/components/LayerProgress.vue` | 三层进度指示器 |
| `src/components/ModeSelector.vue` | 新建/编辑/追加 模式选择 |
| `src/components/cards/VisionCard.vue` | Layer 1 项目愿景卡片 |
| `src/components/cards/FeatureCard.vue` | Layer 2 功能模块 + 页面树卡片 |
| `src/components/cards/DetailCard.vue` | Layer 3 页面详情 + 技术约束 + 数据实体卡片 |
| `src/components/PRDGeneratorView.vue` | PRD 流式生成视图 |
| `src/types/requirements.ts` | RequirementsState 等类型定义 |

### 前端修改

| 文件 | 变更 |
|------|------|
| `src/views/GenerationView.vue` | 右侧面板集成 AnalysisPanel / PRDGeneratorView |
| `src/composables/useMultiAgent.ts` | 扩展需求分析 SSE 事件处理 |
| `src/stores/generation.ts` | 新增 requirementsState、analysisPanelMode 等字段 |
| `src/components/ChatPanel.vue` | 消息带层标签，支持 requirement_question 渲染 |
| `src/components/StepProgress.vue` | 可能无需改动（已支持三层节点） |
