# code-feedback-interaction Tasks

## 1. 后端：feedback fresh-start 现场提取与注入（servicer.py）

- [x] 1.1 `Generate` 的 fresh-start 分支：在 `runner = GraphRunner()` 覆盖 `_active_runners[gid]` **之前**，从 `existing_runner._state` 提取 `compile_errors` 与失败任务摘要（`planner_dag.tasks` 中 status=failed 的 id/description/failure_kind/missing_paths），以结构化字段 `feedback_history` 注入新 state；runner 不存在时不伪造，仅保留空结构
- [x] 1.2 单测：有旧 runner 时提取注入；无 runner 时 feedback_history 为空、不报错

## 2. 后端：现场恢复（graph.py Phase 3 入口）

- [x] 2.1 Phase 3 入口（`if not state.get("generated_files")` 分支内）：`code_result` 非空且为合法 JSON → 反序列化恢复 `generated_files`；否则从 `resolve_project_root` 持久化目录扫描磁盘兜底（跳过点目录如 `.ai-memory`，文件数上限 500）
- [x] 2.2 单测：code_result 反序列化恢复 / 损坏 JSON 走磁盘兜底 / 磁盘扫描排除点目录与超限

## 3. 后端：空 delta 容错（graph.py）

- [x] 3.1 反馈场景（`code_feedback` 非空）下 planner 输出**解析成功且空列表**的 delta → emit planner_reflect（decision=no_changes）+ 正常收尾，不报 "Planner produced no tasks"；增量 replan 路径（Step 3.6 / 修复循环）同样适用
- [x] 3.2 解析失败（`extract_task_dag` 异常兜底为空）不得静默收尾 → 照常报错；无反馈的首次规划空 delta 保持报错
- [x] 3.3 单测：反馈+空 delta 容错、解析失败不静默、无反馈空 delta 报错

## 4. 后端：Planner 现场注入 + agent_message（nodes.py）

- [x] 4.1 planner_node code_feedback 分支：prompt 注入现场 —— 已生成文件清单（大小从磁盘计算）+ 上次编译错误（feedback_history）+ 失败任务列表；反馈文本原样附后，不解析不匹配
- [x] 4.2 executor_task：每轮 `response["content"]` 非空且非纯 `__TASK_DONE__` → emit `agent_message` 事件（text 为模型原文，展示时去除 `__TASK_DONE__` 标记）
- [x] 4.3 单测：反馈 prompt 含现场三块信息；content 事件发出 / 纯标记与空白不发事件

## 5. 后端事件零口吻 + 前端渲染分工

- [x] 5.1 graph.py：删除 planner_reflect（replan_missing_files / final_compile_*）与 7.16 修复循环事件的后端拼接 `message` 字段，事件只留 decision/missing_files/failed_task_ids/errors 等数据；planner_dag 的 reasoning（模型输出）保留
- [x] 5.2 前端 useCodeStream：planner_reflect 按 decision 渲染短状态文本（replan_missing_files → "增量重规划:缺 N 个文件"、final_compile_repair → "最终编译修复"、no_changes → "检查完毕,无需修改"、未知 decision 显示 key）
- [x] 5.3 前端 AgentLog：新增 agent 消息气泡条目类型（agent_message 事件渲染，视觉与 thinking/tool_call 区分）
- [x] 5.4 前端测试：agent_message 事件 → 气泡条目；planner_reflect 各 decision 渲染文案

## 6. 回归与收尾

- [x] 6.1 全链路回归：后端 pytest（含新增用例）+ node-compiler + 前端 vitest 全绿
- [x] 6.2 更新 archive 主 spec 记录（如适用）

## 7. 联调修复：planner 输出截断导致硬编码脚手架兜底

- [x] 7.1 联调发现：生成的工程与方案设计目录树严重不符 —— 设计是 Vite（api/assets/components/views/stores/types/utils），实际落盘是 qiankun/webpack 工程（main.ts + public-path.ts + webpack/webpack.common.js + Header.vue）。根因：planner 的 `_llm_generate` 仍用默认 max_tokens=4096 + enable_thinking（Spec 生成曾因同样配置截断，修复为 8192，planner 漏改）——18 任务 DAG JSON 超出上限被截断 → `extract_task_dag` 解析失败 → 落入**硬编码 qiankun/webpack fallback DAG**（nodes.py 旧兜底），生成的工程与 Spec 完全矛盾
- [x] 7.2 修复：(a) planner `_llm_generate` max_tokens → 8192（与 Spec 一致）；(b) `extract_task_dag` 改用容错解析（fence 剥离 → 完整 JSON → 平衡花括号块 → **截断补全**：从最后一个完整 `}` 截断并补 `]}`/`}` 等括号，恢复被截断的任务列表）；(c) fallback 改为 **Spec 驱动**（`build_spec_fallback_dag`：按 directory_tree 展开文件 → 顶层目录分组生成 business 任务），删除硬编码 qiankun/webpack 模板 —— 无 Spec 时返回空 DAG 由 graph 显式报错，绝不生成与 Spec 矛盾的工程。新增测试：截断 JSON 恢复 / 前后文本包裹 / 非法 JSON 仍报错 / directory_tree 兜底任务 / 嵌套子目录展开 / 无 Spec 空兜底。后端 174 用例全绿
- [x] 7.3 入口缺失死路修复（联调报 "No entry file"）：planner 拆解正确（11 任务，入口在 task-10 依赖链末端），但 stores 任务失败 → 依赖门控跳过 views → **入口任务从未执行** → 最终编译缺入口 → 修复循环 classify=env → abort（旧设计把"未找到入口文件"当环境错误）。且 executor 任务中途编译时入口本就未生成（入口任务在链尾）→ env 错误 → 任务失败 → 链式断裂。修复：(a) **node-compiler quick 检查**：有文件但无入口 → `partial`（入口是后续任务生成，依赖未齐非失败），partial_paths 带入口候选供规划缺口检查；(b) **compile_tool 入口缺失改判 missing_file**（非 env）：`_MISSING_ENTRY_RE`/`_MISSING_ENTRY_PATHS_RE` 识别"未找到入口文件"并提取 "src/main.ts 或 App.vue" → 最终编译缺入口 → 增量 replan 补入口任务（死路打通）。新增测试：node-compiler quick 无入口 partial（full 仍硬错误）/ env 改判 / classify missing_file / 入口候选提取。node-compiler 9 用例、后端 177 用例全绿
- [x] 7.4 失败任务分级重试 + 修复循环出口（用户问"有报错为什么不再继续规划"）：此前 code/env 类失败只重置重试，3 轮耗尽即放弃 —— 失败任务的 files 从未进入重规划池；修复循环耗尽后直接收尾无出口。修复：(a) **分级重试**（planner_reflect）：code/env 失败首次 → 重置 pending + `retry_count=1`（保留一次同 executor 带历史重试，修手滑）；重试后仍失败（retry_count≥1）→ **该任务自己的 files 合并进 replan_request** + 保持 failed —— 增量 planner 以全新上下文生成 delta 任务重新产出这些文件（原 executor 12 轮修不好 = 上下文已废，重复修不收敛）；missing_file 类不变（直接 replan）。(b) **修复循环出口**（graph.py）：修复循环耗尽/中止且仍有编译错误 → emit `planner_reflect(decision=needs_feedback, error_count)`，前端状态卡显示"仍有 N 个错误未解决，可在下方输入修改意见让 agent 继续完善" —— 用户可继续反馈驱动（反馈 → 现场恢复 → 重规划链路已通）。新增测试：code/env 首次重试带 retry_count / 重试后 files 进 replan 保持 failed / needs_feedback 渲染。后端 179 用例、前端 28 用例全绿
- [x] 7.5 截断静默丢任务 + AgentLog 任务视图被重置（联调：生成 6 个文件就结束，界面"只剩 2 个文件"）：两个问题叠加。(a) **7.2 截断补全的副作用** —— 补全"成功"即静默：planner 输出在 tasks 数组中间截断时，补全恢复出前 3 个任务（6 个文件），系统无从知道任务列表不完整 → 执行循环正常结束 → 修复循环 replan 同样截断 → 0 产出。修复：**截断感知** —— `extract_task_dag` 完整解析失败走容错补全时返回 `truncated: True` 标记；planner_node 检测到截断 → 提示 + **重试一次**（prompt 附加"上次输出被截断，请输出完整 JSON"）；修复循环两处 replan 检测截断 → logger.warning 不静默（下一轮编译兜底）；planner max_tokens 8192 → **16384**（thinking 吃 token 是截断主因，Spec 教训在 planner 上复发）。(b) **前端 setPlannerTasks 整体重置**（AgentLog 只剩 delta 任务的直接原因）—— 增量 replan/修复循环 emit planner_dag(仅 delta 任务)→ setPlannerTasks 替换任务列表 + 清空 taskGroups（旧任务日志全丢）。修复：**合并语义** —— 按 id 合并（旧任务保留+状态原位更新、entries 不丢），delta 任务追加。新增测试：截断标记 / 完整 JSON 无标记 / store 合并保留历史 / 状态原位更新。后端 180 用例、前端 30 用例全绿
- [x] 7.6 前端预览入口解析崩溃（联调报 "Cannot read directory '.'/'src': not implemented on js" + "Could not resolve 'src/main.ts'"）：esbuild-wasm 的默认解析器无法读目录（wasm 限制），而 entryPoints 用 "src/main.ts"（无 ./ 前缀）→ 入口解析落进默认解析器 → 三个错误。此前预览从未正常显示过入口工程（或从未有带入口的完整工程触发该路径）。修复：**memfs 插件 catch-all 入口解析**（最后一个 onResolve，`importer === ''` 时 tryResolve 并返回 memfs namespace；非入口放行给前面的 filter）—— 入口从内存文件系统解析，不再触达 wasm 默认解析器。新增测试：src/main.ts / 根 main.ts 入口解析 / 非入口放行 / 缺失入口显式错误。前端 34 用例全绿
