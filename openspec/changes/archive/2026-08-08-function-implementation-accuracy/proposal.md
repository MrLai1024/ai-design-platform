## Why

功能实现节点生成的代码与设计文档出入大。根因是保真度链条上的多个断裂：设计文档是自由格式 prose（无机器可读结构）；Planner 从 prose 做有损 LLM 解析，且掺杂硬编码 bootstrap 启发式；Executor 看不到设计文档本身，只能盲写文件（无 read/list/search 工具）；compile_project 只是前端 esbuild 上报结果的透传，前端未上报即返回"编译通过"，假编译使自我纠错闭环形同虚设；生成文件在内存 dict、临时目录、前端 store 三处漂移，无单一事实源。

已确认方向：**方案 A（最小手术）** —— 只改造功能实现链路，不引入 Manager 编排形态；编译落点采用**后端 node compile worker**，前端 esbuild 保留用于即时预览但降级为辅助信号。

## What Changes

- **设计节点输出结构化架构 Spec（JSON）**：设计节点双产物——人读 MD + 机读 `architecture.json`（复用 `origin/feature/ai` 分支 17d50d1 中已定稿的 `spec_schema.py`：`ARCHITECTURE_SPEC_SCHEMA`/`validate_spec`/`empty_spec`）。Spec 是 Planner 拆解、Executor 验收、编译验证的公共基准。
- **Planner 基于 Spec 拆解 Task DAG**：输入从 prose 设计文档改为架构 Spec；删除硬编码"总是包含 3 个 bootstrap 任务 / 每 task ≤5 文件"启发式，任务边界从 directory_tree / data_model / component_tree 推导。
- **Executor 可见设计文档与项目现状**：Executor 上下文注入设计文档引用（相关 Spec 段 + 人读 MD 摘要）；新增 `read_file` / `list_files` / `search_project` 工具，LLM 写作前可查看项目现状。
- **compile_project 改为真实编译**：新增后端 node compile worker（esbuild bundle 校验 + vue-tsc `--noEmit` 类型检查），`compile_project` 直接调用 worker 返回真实错误；前端 esbuild-wasm 反馈降级为"即时预览 + 辅助信号"，不再作为编译通过的唯一判据。
- **项目目录持久化为单一事实源**：project_root 从 `tempfile.gettempdir()/ai-gen/<需求名>` 迁移到 `data/generated/<app_id>/`；修复 `use_skill` 生成的文件不流式给前端导致预览缺文件的 bug。
- **清理死代码**：删除已不被 graph 调用的 `code_node` / `code_node_streaming` 旧路径。

## Capabilities

### New Capabilities
- `architecture-spec`: 设计节点输出结构化架构 Spec（JSON schema + 人读文档），作为 Planner 拆解与验证的公共接口
- `node-compile-worker`: 后端 Node 编译服务——esbuild bundle + vue-tsc 类型检查，对持久化项目目录做真实编译，返回结构化错误

### Modified Capabilities
- `function-implementation`: 功能实现节点保真度改造——Planner 消费 Spec 拆解、Executor 获得项目读取工具与设计文档引用、compile 接入真实编译
- `compile-feedback`: 前端 esbuild 反馈从 Executor 唯一编译信号降级为辅助信号（即时预览 + 补充错误来源），编译通过判据改为 node worker 结果

## Impact

- **后端 ai-service（Python）**：
  - `nodes.py` — 设计节点输出 Spec；Executor 上下文与工具调用改造；删除 code_node/code_node_streaming
  - `planner.py` — Spec 驱动的 DAG 拆解
  - `graph.py` — project_root 持久化到 `data/generated/<app_id>/`
  - `tools/registry.py` + `tools/file_tools.py` — 新增 read_file/list_files/search_project；compile_project 指向 node worker
  - 新增 `spec_schema.py`（从 origin/feature/ai 17d50d1 搬运）
- **新增 node-compiler 服务（Node.js）**：小型 HTTP 服务，esbuild + vue-tsc；docker-compose 新增容器；gateway 转发编译请求
- **前端（ai-generation-app）**：PreviewFrame 编译卡片来源区分（worker 编译 vs 预览 esbuild）；skill 文件事件流修复
- **环境**：Node 运行时（本机 v24.15.0 可用；生产经 docker 容器）
