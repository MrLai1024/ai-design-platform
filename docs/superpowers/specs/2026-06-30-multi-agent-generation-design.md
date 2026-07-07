# Multi-Agent AI Generation — 多智能体代码生成设计文档

> 日期: 2026-06-30 | 状态: 设计完成，待计划

## 1. 概述

将 AI 生成子应用从单次问答模式升级为多智能体编排模式，分三个阶段：
需求分析 → 详细设计 → 代码实现。前端编排，用户在每阶段可查看产出、编辑修改，确认后推动到下一阶段。

## 2. 状态机

```
用户输入需求
    ↓
[① 需求分析] ⇄ 多轮问答（Agent 提问，用户回答）
    ↓ 需求足够清晰
输出需求规格文档
    ⏸ 用户查看/编辑 → 确认推进
    ↓
[② 详细设计] → Agent 输出设计方案文档
    ⏸ 用户查看/编辑 → 确认推进
    ↓
[③ 代码实现] → Agent 流式生成代码 → 实时预览
    ✨ 完成
```

## 3. 架构

- **编排位置**: 前端 (Vue 3 composable)
- **编排方式**: 新增 `useMultiAgent` composable，管理三阶段状态机
- **API 复用**: 每个阶段调用现有 `POST /api/v1/chat/stream`，传递不同的 system prompt 和上下文
- **后端变更**: 无（纯前端编排）

## 4. 组件结构

```
GenerationView.vue
├── ChatPanel (左侧 40%)
│   ├── 聊天消息列表（消息带阶段标签）
│   └── ChatInput（含确认推进按钮）
└── 右侧 (60%)
    ├── StepProgress          ← 新增：三节点步骤条
    ├── StageOutput           ← 新增：需求分析/详细设计阶段展示产出
    │   ├── MarkdownRenderer  （规格/方案文档渲染）
    │   └── 编辑模式           （可修改产出后重新提交）
    ├── TabBar                ← 新增：代码实现阶段水平 Tab
    │   ├── Tab "实时预览" (默认)
    │   └── Tab "工程文件"
    ├── PreviewFrame          （Tab1 内容：实时预览 iframe）
    └── FileExplorer          ← 新增：Tab2 内容，文件树 + 代码查看器
```

## 5. 步骤条组件 (StepProgress)

```
┌───────────────────────────────────────────────┐
│  ① 需求分析 ──── ② 详细设计 ──── ③ 代码实现  │
│     ✓ 完成        ◉ 进行中         ○ 待开始   │
└───────────────────────────────────────────────┘
```

### 节点状态

| 状态 | 样式 | 点击行为 |
|------|------|---------|
| pending | 灰色圆点 + 灰色文字 | 无反应 |
| active | 蓝色圆点 + 蓝色粗体 + 脉冲动画 | 无反应 |
| done | 绿色对勾 + 正常文字 | 展示该阶段产出 |

### 连线

- done→done: 绿色实线
- done→active: 绿色实线（动画进度）
- active→pending: 灰色虚线

## 6. 三个 Agent 设计

### 6.1 需求分析 Agent

System Prompt 核心指令:
- 角色: 资深产品需求分析师
- 理解用户输入，识别不明确的地方
- 每次最多提 1-2 个具体问题，引导用户选择/补充
- 约 2-4 轮问答后，当信息足够时输出格式化文档

输出格式:
```markdown
## 需求规格文档
- 功能概述: ...
- 页面布局: ...
- 交互行为: ...
- 数据展示要求: ...
- 技术要求（组件库/框架）: ...
```

### 6.2 详细设计 Agent

System Prompt 核心指令:
- 角色: 资深前端架构师
- 基于需求规格文档，只输出设计方案，不写代码

输出格式:
```markdown
## 详细设计方案
- 组件树结构: ...
- 数据流设计 (props/events/store): ...
- 样式方案 (响应式/布局): ...
- 文件拆分方案: ...
- 关键实现要点: ...
```

### 6.3 代码实现 Agent

System Prompt 核心指令:
- 角色: 资深 Vue 3 前端全栈工程师
- 基于需求规格 + 设计方案，输出可运行代码
- 简单应用 → 单文件 SFC；复杂应用 → 多文件工程

文件标记格式（复用现有 parseMultiSFC）:
```markdown
## src/App.vue
` ``vue
<template>...</template>
` ``

## src/components/Table.vue
` ``vue
...
` ``
```

工程能力: Vue 3 SFC、vue-router、Pinia、组件库集成、工具函数

## 7. 数据模型 (generation store 新增字段)

```typescript
// 阶段状态
stage: 'idle' | 'analysis' | 'design' | 'code'
stageStatus: Record<string, 'pending' | 'active' | 'done'>

// 各阶段产出
stageOutputs: {
  analysis: string | null    // 需求规格文档
  design: string | null      // 设计方案文档
}

// 代码实现阶段的 Tab
codeViewTab: 'preview' | 'files'  // 默认 'preview'

// 右侧展示区当前视图（需求分析/设计阶段为 'stage-output'，代码实现阶段由 codeViewTab 控制）
rightPanelView: 'stage-output' | 'preview' | 'files'
```

## 8. ChatPanel 增强

- 消息列表中的每条消息标注所属阶段
- 需求分析阶段：聊天框中 Agent 提问，用户回答
- 每个阶段完成后：在消息末尾显示"确认并进入下一阶段"按钮
- 用户可编辑 StageOutput 中的内容后再确认推进

## 9. TabBar 组件（代码实现阶段）

- 水平分布两个 Tab：`实时预览` | `工程文件`
- 默认选中"实时预览"
- 点击切换，无需额外按钮

### Tab2: 工程文件

- 左侧文件树（基于 store.files 构建目录结构）
- 右侧代码查看器（只读高亮，复用 highlight.js）

## 10. 上下文传递

```typescript
// 进入详细设计阶段时
const designMessages = [
  { role: 'system', content: designAgentPrompt },
  { role: 'user', content: `需求规格文档：\n${stageOutputs.analysis}` },
]

// 进入代码实现阶段时
const codeMessages = [
  { role: 'system', content: codeAgentPrompt + '\n' + componentDocs },
  { role: 'user', content: `需求规格：\n${stageOutputs.analysis}\n\n设计方案：\n${stageOutputs.design}` },
]
```

## 11. 文件清单

### 新增文件

| 文件 | 用途 |
|------|------|
| `src/composables/useMultiAgent.ts` | 三阶段状态机编排、prompt 构建、阶段切换 |
| `src/components/StepProgress.vue` | 步骤条组件 |
| `src/components/StageOutput.vue` | 阶段产出查看/编辑器（需求分析+详细设计阶段使用） |
| `src/components/TabBar.vue` | 水平 Tab 切换组件 |
| `src/components/FileExplorer.vue` | 文件树 + 代码查看器（代码实现阶段 Tab2） |
| `src/composables/useStagePrompts.ts` | 三个 Agent 的 system prompt 模板 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/views/GenerationView.vue` | 新布局：ChatPanel + 右侧 StepProgress + StageOutput/TabBar + PreviewFrame/FileExplorer |
| `src/stores/generation.ts` | 新增 stage、stageStatus、stageOutputs、codeViewTab 等字段和 actions |
| `src/types/generation.ts` | 新增 Stage、StageStatus、StageOutputs 等类型 |
| `src/components/ChatPanel.vue` | 消息带阶段标签、确认推进按钮 |
| `src/composables/useStreamChat.ts` | 支持外部传入 messages（适配多阶段上下文） |

## 12. 不修改的部分

- 后端 Go gateway (chat.go)
- 后端 AI service (Python gRPC)
- 共享 `useChatStream` composable（ai-chat-app 继续使用）
- `useCodeParser` / `useMultiCompiler` / `usePreviewRenderer` composable（继续工作）
