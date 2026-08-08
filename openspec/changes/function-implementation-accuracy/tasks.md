## 1. 后端：架构 Spec 落地

- [x] 1.1 从 17d50d1 搬运 `spec_schema.py`（ARCHITECTURE_SPEC_SCHEMA / validate_spec / empty_spec）到 `app/services/generation/spec_schema.py`，保持纯 stdlib 无内部 import
- [x] 1.2 新增单测 `tests/test_spec_schema.py`：schema 校验通过/字段缺失/类型错误/empty_spec 合并四类用例
- [x] 1.3 `design_node` 生成 MD 后追加 Spec 生成：LLM 按 schema 输出 JSON → validate_spec → 失败重试一次 → empty_spec 兜底；结果存 `state["architecture_spec"]`
- [x] 1.4 `state.py` GenerationState 增加 `architecture_spec` 字段
- [x] 1.5 单测：design_node 双产物（MD + architecture_spec）且字段校验通过；LLM 输出非法 JSON 时兜底生效

## 2. 后端：Planner 消费 Spec

- [x] 2.1 按 17d50d1 planner.py diff 改造：PLANNER_SYSTEM_PROMPT Spec 驱动（任务边界←directory_tree、契约←data_model/api_contracts、依赖←component_tree、脚手架仅当 tech_stack.build 需要），删除硬编码"3 bootstrap / ≤5 文件"
- [x] 2.2 `build_planner_user_prompt(spec, design_doc, failure)`：有 Spec 序列化 Spec 区块，无 Spec 回退 prose 路径
- [x] 2.3 `planner_node` 传入 architecture_spec；单测：Spec→DAG 对齐（directory_tree 目录产生对应任务、依赖符合 component_tree、无硬编码 bootstrap 任务）

## 3. 后端：Executor 可见设计文档与项目现状

- [x] 3.1 executor_task user_msg 注入 Spec 对应片段 + design_doc 摘要（截断 ~2000 字符）
- [x] 3.2 新增 `read_file` / `list_files` / `search_project` 工具（file_tools.py + registry.py），读写目标为持久化项目目录，路径安全防护（复用 safe_project_path 思路）
- [x] 3.3 EXECUTOR_SYSTEM_PROMPT 补充工具使用指引（写作前 list_files、不确定接口时 read_file）
- [x] 3.4 单测：工具行为（list_files 返回清单、read_file 命中/缺失、search_project 命中文件与片段）

## 4. 新增 node-compiler 服务

- [x] 4.1 新建 `ai-design-platform-server/node-compiler/`：package.json（esbuild、typescript、vue-tsc）+ 目录结构
- [x] 4.2 实现 HTTP 服务 `/compile`：`{project_root, entry?, full}` → `{ok, errors:[{file,line,column,message,source}]}`；esbuild bundle 校验 + full=true 时 vue-tsc --noEmit
- [x] 4.3 依赖策略：内置 vue/vue-router/pinia 类型 stub；esbuild external 与前端一致
- [x] 4.4 node-compiler 单元测试：语法错误检出、类型错误检出、编译通过、空项目显式错误
- [x] 4.5 gateway 新增 `POST /api/v1/generation/compile` 转发端点（模式参照 compile_feedback）
- [x] 4.6 docker-compose 新增 node-compiler 容器；README 补充启动说明

## 5. 后端：compile_project 接真实编译

- [x] 5.1 `compile_tool.compile_project` 改为直接调用 compile worker（ai-service → node-compiler HTTP；gateway 提供转发端点供调试）：错误→ok=False；worker 不可达/超时→ok=False+原因；空项目→显式错误
- [x] 5.2 分层编译时机：executor 中途 compile 用 full=false（esbuild 快校验），graph 最终编译用 full=true（esbuild + vue-tsc）
- [x] 5.3 前端 `ReportCompileFeedback` 通道保留但降级为展示（AgentLog 辅助卡片，标注"预览"来源），不作为编译通过判据
- [x] 5.4 单测：compile_tool 对 worker 响应/不可达/HTTP 错误的三种结果

## 6. 后端：持久化项目目录 + skill 文件事件修复

- [x] 6.1 project_root 迁移到 `data/generated/<app_id>/`（`resolve_project_root` 统一解析，app_id 路径安全化），graph.py / nodes.py / ToolRegistry 统一使用
- [x] 6.2 修复 `use_skill` 文件事件：executor_task 补发 file_start/file_chunk/file_complete（code_node_streaming 已随死代码删除）
- [x] 6.3 验证：单测 test_executor_skill_events 确认 skill 文件进入 generated_files 并发射 file 事件

## 7. 清理与收尾

- [x] 7.1 删除死代码 `code_node` / `code_node_streaming` / `_llm_generate_with_tools`；LangGraph "code" 节点替换为 `code_passthrough_node`（Phase 3 已生成代码，不重复生成）
- [x] 7.2 前端 PreviewFrame 编译卡片来源标注（preview 标签），`_frontend_compile_errors` 降级为展示用
- [x] 7.3 全链路回归：后端 102 测试 + node-compiler 6 测试 + 前端 16 测试 + gateway go vet/build 全绿（真实 LLM 全链路需联调环境执行）
- [x] 7.4 `pytest` + 前端单测全绿
- [x] 7.5 运行时修复（联调发现）：Spec 生成关 thinking + max_tokens 8192 + 解析器花括号匹配提取（GLM 思考模式吃 token 导致 JSON 截断/落入 reasoning_content）；Planner 对业务无效 Spec 回退 prose 路径，不再空任务死路
- [x] 7.6 交互延迟修复（联调发现）：架构 Spec 原来在 Phase 2 同步生成（卡确认按钮）+ Phase 2.5 再同步生成一次（卡进入 code 节点）。改为设计流式完成后立即起**后台任务**生成 Spec，用户审阅设计文档期间完成；Phase 2.5 只 await 已有任务（极快）或同步兜底；cancel 时取消后台任务；design_node 已有 Spec 不重复生成
- [x] 7.7 延迟根因深挖（联调仍卡）：前端 `confirmStage` 的 fresh-start 分支**不带 generation_id** → gateway 每次 `newUUID()` → 后台 Spec 任务按旧 gid 存、Phase 2.5 按新 gid 查 → 永远 miss → 每次同步重生成。修复：(a) 前端 fresh-start 也携带 `store.currentGenerationId`；(b) 后端 `_await_background_spec` 三级取 Spec——per-generation 缓存 → 后台任务 → 同步兜底，结果按 gid 缓存跨阶段复用（design 确认 → code 确认不再重复生成）。新增 test_spec_background_cache.py 4 用例
- [x] 7.8 延迟彻底消除（联调仍卡）：即使后台任务命中，点下一步后 Phase 2.5 的 await 仍阻塞在 `stage_start(code)` 事件之前。改为**阶段入口事件先行**：graph Phase 3 先 emit `stage_start(code)`（前端立即切换到功能开发节点，显示"规划中"），Spec 获取移入 planner_node 内部任务（缓存 → 后台任务 → 同步三级链），`generation_id` 经 state 传入。用户感知：点下一步 → 立即进入功能开发节点，无等待。缓存/取消逻辑迁至 nodes.py（`await_architecture_spec`/`cancel_background_spec`）。test_spec_background_cache.py 增至 5 用例
- [x] 7.9 跨进程路径修复（联调报错"项目目录不存在"）：`resolve_project_root` 返回相对路径 `data/generated/<gid>`，发给 node-compiler（独立进程、cwd 不同）后找不到目录。修复：`resolve_project_root` 强制 `os.path.abspath`（所有下游——写盘/读工具/compile worker 统一绝对路径）；compile_tool 发送前 `_ensure_absolute` 兜底。新增 test_project_root.py 5 用例
- [x] 7.10 环境/代码错误区分（7.9 暴露的连锁问题）：环境错误（worker 不可达/目录不存在/空项目/无入口，`source=node-compiler` 且无 file）曾混入 LLM 修复循环——LLM 对着"项目目录不存在"反复重写代码浪费轮次，且依赖门控下业务任务全挂。修复：compile_tool 给环境错误打 `kind="env"`（`_env_error`/`is_env_error`）；executor 收到纯环境错误时**不进 LLM 修复循环**，重试 2 次后直接标记任务 failed（依赖门控照常触发），auto-compile 分支同样处理。新增 test_env_error_classification.py 5 用例
- [x] 7.11 规划空窗消除（用户反馈 stage_start 后长时间无反应）：stage_start(code) 之后 planner 要串行 await Spec + 生成 DAG（两次 LLM 调用），期间零事件输出。修复：(a) `planner_start` 事件提前到 await Spec 之前发出（"正在准备架构规格与任务规划..."），前端立即有规划反馈；(b) `generate_architecture_spec` 支持 `on_reasoning` 回调，Spec 思考流经 `thinking_chunk` 实时显示在 AgentLog——空窗变可见进度。移除 DAG 生成前的重复 planner_start 发射
- [x] 7.12 依赖未齐误判硬错误（联调报 Could not resolve + Cannot find module）：main.ts（bootstrap 任务）import 业务文件（App.vue/router，后续任务），bootstrap 编译时依赖未齐被 node-compiler 当硬错误 → 任务 failed → 依赖门控跳过业务任务 → 业务文件永不生成。修复：(a) node-compiler quick 检查（full=false）对全部 "Could not resolve" 错误返回 `partial`（对齐前端 bundler 语义），final 编译（full=true）仍报硬错误；compile_tool 将 partial 转为 ok=True（executor 继续生成）；vuePlugin 未找到 .vue 的错误文本统一为 "Could not resolve" 措辞以便 partial 检测；(b) vue stub 补 `App` 类型及 `createApp` 返回类型自洽（TS2614/TS2739）。node-compiler 测试更新为 quick/full 双模式，全链路验证：阶段1 partial → 阶段2 full 通过
- [x] 7.13 执行反馈驱动重规划（ReAct 闭环补全）：当前"分层 ReAct"缺执行→规划反馈——任务失败只机械重试，规划漏文件（代码 import 了无任务生产的文件）时业务链死路。修复：(a) 编译错误分类 `classify_compile_errors` → env/missing_file/code；`extract_missing_paths` 从 esbuild/vue-tsc 错误提取缺失路径（引号与非引号两种格式）；(b) executor_task 返回 `failure_kind` + `missing_paths`；(c) planner_reflect 对 missing_file 类失败生成 `replan_request`（保留 failed 不机械重置），code/env 类照旧重置重试；(d) graph.py 循环新增 Step 3.5：消费 replan_request → `build_incremental_planner_prompt`（缺失文件证据 + 已有文件只读）→ 增量 planner 输出 delta 任务 → 合并进 DAG 继续执行（task id 去重防冲突），AgentLog 发 replan 卡片。新增 test_replan_feedback.py（11 用例）+ test_replan_integration.py（2 用例）
- [x] 7.14 partial 信号打通 replan + 第三方依赖支持（联调仍缺文件）：(a) **partial 断层**——依赖未齐被转 ok=True 后，缺失文件信号被吞，done 任务永不触发 replan（main.ts 引用的 ./router 无任务生产 → 最终编译才暴露）。修复：node-compiler partial 返回 `partial_paths`（仅 ./ ../ 相对导入，第三方包排除）；executor 收集进任务结果；graph 新增 **Step 3.5 规划缺口检查**——done 任务的 partial_paths 对照全任务规划文件集，未规划者合并进 replan_request（与 reflect 的 missing_file 统一走增量 replan）。(b) **第三方依赖**：esbuild EXTERNAL 加 element-plus/@element-plus/icons-vue（预览 CDN import map 提供）；vue-tsc paths 中 @element-plus/icons-vue 指向真实包类型（dist/types/index.d.ts，小包直接安装），element-plus 保留精简 stub（模板标签无需类型）。(c) **TS2339 模板绑定假阳性根治**：手写 vue/vue-router/pinia stub 太薄（模板 ctx 塌缩为 {}），改为 paths 指向 node-compiler 自身 node_modules 的**真实类型文件**（vue/dist/vue.d.ts、vue-router/dist/vue-router.d.mts、pinia/dist/pinia.d.ts），删除三个手写 stub；RouteLocationRaw 接受 string（TS2559）。端到端验证：真实生成项目（main.ts+Header.vue+App.vue+router）full 编译通过。node-compiler 测试 7 用例、后端 131 用例全绿
- [x] 7.15 `@/` 别名缺失信号修复（联调仍缺 App.vue/@/views/home-view.vue）：增量 replan 补出 router 后，router import `@/views/home-view.vue`（项目内别名 → src/），但提取函数只认 `./`/`../` 前缀，把 `@/` 当第三方包排除 → 页面文件信号再次丢失。修复：node-compiler `partialPaths` 与后端 `extract_missing_paths` 均识别 `@/` 前缀并归一化为 `src/`（与规划文件集匹配），裸包名（无 ./ ../ @/ 前缀）才排除。新增 node-compiler 用例（@/ 别名 partial + src 归一化）与后端用例（@/ 提取）。node-compiler 8 用例、后端 132 用例全绿
- [x] 7.16 最终编译失败不再停摆（用户反馈：所有任务跑完后若业务代码没生成全，不会重新检查重规划持续完善）：最终 full 编译（esbuild + vue-tsc）是最后一道闸——类型错误只有 full 模式才暴露（executor quick 检查跳过 vue-tsc），未规划缺失文件也在此暴露，但此前失败后直接结束。修复：(a) planner.py 新增 `plan_final_compile_fix`（错误分类 → replan/fix/abort 决策，纯函数）与 `build_fix_task`（code 错误 → 修复任务，错误列表进 contract，executor 可见）；(b) graph.py Step 4 改为修复循环（max 3 轮）：full 编译失败 → missing_file → 增量 replan 补 delta 任务；code → 修复任务，且以 `compile_full=True` 执行（executor 内部编译全部走 full 模式，vue-tsc 类型错误在其工作期间即可见可验证）；每轮执行完新任务后重新 full 编译仲裁，直至通过 / 无新工作 / 轮次耗尽；(c) `merge_delta_tasks` 替代原 id 去重跳过——增量 planner 任务 id 从 task-0 重启与既有任务撞 id 时**重编号而非丢弃**（丢弃 = 缺失文件永不生成，主循环与修复循环共用）；(d) executor_task 增加 `compile_full` 参数；graph.py 抽出 `_stream_executor_events`/`_apply_task_result` 供两处循环共用（消除重复执行块）；(e) 前端 planner_reflect 卡片显示 `reason || message`（此前重规划卡片文案为空）。新增 test_final_compile_loop.py 12 用例（决策/修复任务/delta 合并重编号）。后端 143 用例、node-compiler 8 用例、前端 16 用例全绿
- [x] 7.16b 运行时崩溃修复（联调报 UnboundLocalError: cannot access local variable 'errors'）：executor_task 的环境错误记录逻辑在**首个工具调用就是失败的非编译工具**时读未绑定的 `errors`（LLM 幻觉工具名 → registry ok=False+error；或 write_code 被路径安全检查拒绝）。`errors` 只在 compile_project 分支与自动编译分支赋值，首个失败工具调用即触发。修复：tool-call 循环顶部按次绑定 `errors = []`（env 错误判定语义保持：工具失败 + 无编译错误 + 有 error → 记 env 错误）。新增 test_executor_failing_tool.py 回归用例。后端 144 用例全绿
