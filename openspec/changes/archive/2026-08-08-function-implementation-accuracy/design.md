## Context

当前功能实现链路（`ai-service/app/services/generation/`，工作区 @ 8dfcd79）：

- **设计节点**输出自由格式 Markdown prose（`DESIGN_SYSTEM_PROMPT`，nodes.py:183），无机器可读结构
- **Planner** 从 prose 做 LLM 有损解析，且硬编码"总是 3 个 bootstrap 任务 / 每 task ≤5 文件"（planner.py:60-62）
- **Executor** 的 user_msg 只有 task 描述 + 文件清单 + 契约（nodes.py:711-717），**看不到设计文档**；无 read/list/search 工具，全盲写作
- **compile_project** 是前端 esbuild-wasm 上报结果的透传（compile_tool.py:14-21）：前端未上报即 `ok=True`——假编译；esbuild 也不做类型检查
- 文件三处漂移：内存 dict / `tempfile.gettempdir()/ai-gen/<需求名>` / 前端 store（SSE 流式重建）；`use_skill` 文件只写盘不流式，前端预览缺文件
- Review 节点审查安全/性能/可访问性/可维护性，**不审查设计文档一致性**

已确认方向：**方案 A（最小手术）**——只改造功能实现链路，不引入 Manager 编排形态；编译落点 = **后端 node compile worker**。

可复用资产：`origin/feature/ai` 分支 commit 17d50d1「agent编排重构」已实现 `spec_schema.py`（`ARCHITECTURE_SPEC_SCHEMA`/`validate_spec`/`empty_spec`，纯 stdlib 183 行）与 Spec 消费型 Planner（planner.py diff 125 行）。本设计将其中的 Spec 相关部分搬运到当前工作区，不引入该提交的 manager-worker/记忆系统。

## Goals / Non-Goals

**Goals:**

1. 设计节点输出结构化架构 Spec（JSON）作为公共基准，Planner/Executor/验证全部以 Spec 为准
2. Executor 可见设计文档（Spec 片段 + MD 摘要）与项目现状（read/list/search 工具）
3. compile_project 返回 node worker 真实编译结果（esbuild + vue-tsc），消灭假编译
4. 项目目录持久化为单一事实源（`data/generated/<app_id>/`），修复 skill 文件不流式 bug
5. 清理死代码 `code_node` / `code_node_streaming`

**Non-Goals:**

- 不引入 Manager/coordinator 编排形态、四层记忆系统、recovery 自主闭环（属于 17d50d1 的更大重构，另行立项）
- 不引入 review 节点替代（设计文档一致性由 Executor 上下文 + Spec 驱动从源头保证）
- 不做 E2E 后端浏览器执行
- 不做运行时错误上报闭环（Verifier L3 属 17d50d1，本 change 只到编译 L1）
- 前端 esbuild-wasm 保留（即时预览），但不再是编译通过判据

## Decisions

### D1. 架构 Spec schema：直接搬运 17d50d1 的 spec_schema.py

**决策**：新增 `app/services/generation/spec_schema.py`，内容取自 17d50d1（`ARCHITECTURE_SPEC_SCHEMA` 十个字段、`validate_spec` 确定性校验、`empty_spec` 类型强制合并兜底）。不重新设计 schema——该 schema 已在 agent 编排设计中定稿，且与本仓库实际生成案例（`.ai-memory/spec/architecture.json`）结构一致。

**备选**：重新设计更细粒度 schema — 否决：既有 schema 已被 E2E/记忆/增量开发设计消费，保持一致免未来迁移。

### D2. 设计节点输出双产物，Spec 存 state

**决策**：`design_node` 在生成 MD 后追加一次结构化 Spec 生成：LLM 按 schema 输出 JSON → `validate_spec` 校验 → 失败则带错误重试一次 → 仍失败用 `empty_spec` 兜底（log 记录）。Spec 存 `state["architecture_spec"]`（dict），MD 仍存 `design_doc`。Spec 生成与 MD 生成在同一节点内完成，前端无需新增阶段。

**备选**：前端分两步展示 — 否决：用户已确认只关心保真度，Spec 是内部契约，不必暴露为独立 UI 阶段。

### D3. Planner 消费 Spec：采用 17d50d1 的 planner 改造

**决策**：按 17d50d1 的 planner.py diff 落地：`PLANNER_SYSTEM_PROMPT` 改为 Spec 驱动（任务边界←directory_tree、契约←data_model/api_contracts、依赖←component_tree、脚手架仅当 tech_stack.build 需要）；`build_planner_user_prompt(spec, design_doc, failure)` 带 Spec 时序列化 Spec 区块，无 Spec（旧状态）回退 prose 路径。`extract_task_dag` 维持现状。

### D4. Executor 可见设计文档 + 项目现状

**决策**：三处改动（都在 nodes.py executor_task）：

1. user_msg 注入：`architecture_spec` 的对应片段（组件/页面/数据模型/契约）+ `design_doc` 摘要（截断 ~2000 字符），让设计意图直达代码生成
2. 新增工具 `read_file` / `list_files` / `search_project`（tools/file_tools.py + registry.py），读取目标为持久化项目目录
3. `EXECUTOR_SYSTEM_PROMPT` 补充使用指引："写作前先 list_files 看项目现状，不确定接口时 read_file 依赖文件"

**备选**：把全量项目代码塞进上下文 — 否决：token 爆炸；按需读取才是可持续模式。

### D5. node compile worker：独立 Node HTTP 服务

**决策**：新增 `ai-design-platform-server/node-compiler/`（Node 24 + esbuild + typescript/vue-tsc），HTTP 服务（`/compile` POST：`{project_root, entry?, full: bool}` → `{ok, errors:[{file,line,column,message,source}]}`）。执行链：esbuild bundle（语法/import/SFC，快）→ `vue-tsc --noEmit`（类型，`full=true` 时）。ai-service 经 gateway 转发调用（gateway 已有 `POST /api/v1/generation/compile_feedback` 同款转发模式，新增 `POST /api/v1/generation/compile`）。

**为什么 HTTP 而非进程内**：Python 进程内无法跑 vue-tsc；独立进程避免污染 ai-service 依赖；docker 单独容器（生产）或本机 `node`（开发）均可。

**备选**：前端 esbuild-wasm + 无类型检查 — 否决（用户已拍板 node worker）；ai-service 内嵌 node subprocess — 否决（跨语言进程管理复杂，不如独立服务清晰）。

### D6. compile_project 真实调用 + 前端反馈降级

**决策**：`compile_tool.compile_project` 改为调用 compile worker：worker 返回错误 → `ok=False, errors`；worker 不可达/超时 → `ok=False` + 明确错误（消灭"未编译即通过"）；空项目目录 → 显式错误。前端 `ReportCompileFeedback` 通道保留：错误仍进 AgentLog 展示（辅助），但不作为编译通过判据；`registry._frontend_compile_errors` 降级为展示用。

**时机**：最终编译检查（graph.py:388）与 executor 自动 compile 均走 worker。为控制实时性，中途 compile 用 `full=false`（esbuild 快速校验），最终 compile 用 `full=true`（esbuild + vue-tsc）。

### D7. 持久化项目目录 = 单一事实源

**决策**：project_root 由 `tempfile.gettempdir()/ai-gen/<需求名>` 迁移为 `data/generated/<app_id>/`（app_id = generation_id 或需求名 hash，路径安全化）。所有写盘、read/list/search 工具、compile worker 均以该目录为准。**修复 skill 文件事件流 bug**：`use_skill` 分支补发 `file_start`/`file_chunk`/`file_complete` 事件（nodes.py:522-532 / 782-791 两处），保证前端预览拿到全部文件。

**备选**：维持 temp 目录 + 前端流式 — 否决：temp 无持久性、无法支撑 worker 编译与增量开发。

### D8. 清理死代码

**决策**：删除 `code_node` / `code_node_streaming`（nodes.py:288-571）——graph Phase 3 已走 planner+executor，这两条路径不被调用（graph.py:264-416 自实现 Phase 3）。删除后 `code_result` 仍由 graph 设置，前端事件协议不变。

## Risks / Trade-offs

- [node worker 增加部署面（新服务 + 新容器）] → docker-compose 加一个轻量容器（Node 24 slim）；开发环境本机 `npm run dev` 启动；worker 不可达时 compile 显式失败并引导排查，不会静默假通过
- [vue-tsc 全量类型检查慢（秒级），拖慢 Executor 循环] → 分层：中途 `full=false` 只跑 esbuild（毫秒级），仅最终编译跑 vue-tsc；后续可做增量/缓存
- [Spec 生成质量不稳（LLM 输出空壳）] → validate_spec 确定性兜底 + 重试一次 + empty_spec 合并；spec 质量下限从"空"提升到"结构完整"，配合 D3/D4 让 Executor 拿到的是结构化的"设计意图"而非纯 prose
- [vue-tsc 对缺 node_modules 的项目误报（import 第三方库）] → worker 预置 vue/vue-router/pinia 类型 stub 或 CDN 对应 d.ts；esbuild 侧 external 保持与前端一致
- [从 17d50d1 搬运代码与当前分支冲突] → 以文件粒度搬运（spec_schema.py / planner.py diff / verifier 的 check_contracts 可后置），逐文件 review 后合入，不整 commit cherry-pick
- [持久化目录增长无人清理] → `data/generated/` 现有目录结构（app_id 子目录）天然支持按 app 清理，后续任务加清理策略即可

## Migration Plan

1. 后端：落地 spec_schema.py → design_node 双产物 → planner Spec 驱动 → executor 上下文与工具 → compile_tool 接 worker → project_root 持久化 + skill 事件修复 → 删死代码
2. 新增 node-compiler 服务：目录 + package.json + HTTP 编译服务 + gateway 转发端点
3. 前端：PreviewFrame 编译卡片来源标注（worker 编译 vs 预览 esbuild）；skill 文件事件消费无需改（协议不变）
4. 环境：docker-compose 加 node-compiler 容器；README/文档更新

**回滚**：本 change 无 BREAKING 协议变更（文件事件协议、SSE 事件、state 字段均向后兼容；`architecture_spec` 为新字段）。回滚 = 撤掉 node-compiler 容器 + 恢复 compile_tool 透传 + planner 回退 prose（planner 保留 fallback 分支，天然可回退）。

## Open Questions

- vue-tsc 的 node_modules 依赖策略：worker 内置 stub vs 生成工程自带 package.json 由 worker `npm install`（慢）— 实现期先内置 stub
- `architecture_spec` 是否需要前端展示（设计阶段右侧产物区）— 本期不展示，后续增量开发功能再定
- search_project 的检索深度（关键词子串 vs 简单 token 打分）— 先子串 + 文件名命中，与现有 retrieve_context 同级别
