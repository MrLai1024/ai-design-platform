## 1. 前端打包基础设施

- [x] 1.1 安装 `esbuild-wasm` 依赖到 ai-generation-app，配置 wasm 文件静态分发
- [x] 1.2 新建 `src/bundler/memfsPlugin.ts`：内存 FS resolver（`@/` 别名 → `src/`、相对路径、扩展名补全 `.vue`/`.ts`/`.js`、目录 index）+ external 标记（vue/vue-router/pinia）
- [x] 1.3 新建 `src/bundler/vuePlugin.ts`：`.vue` load hook 用 `vue/compiler-sfc` 编译 script/template，style 收集返回供注入
- [x] 1.4 新建 `src/bundler/useBundler.ts`：esbuild-wasm 初始化（requestIdleCallback 预加载）、build/rebuild 封装、增量 rebuild、partial 错误分类（`Could not resolve`）、合成入口 fallback（无 `src/main.ts` 时生成 `__preview_entry__`）
- [x] 1.5 新增 wasm 初始化失败降级逻辑：捕获后回退 `useMultiCompiler` + `compileSFC` 单组件路径，UI 显示"降级预览"标识

## 2. 预览渲染管线替换

- [x] 2.1 新建 `src/bundler/previewTemplate.ts`：iframe HTML 模板（import map 指向 esm.sh CDN：vue/vue-router/pinia、blob URL 加载 bundle、style 注入槽位、onerror 回传）
- [x] 2.2 改造 `PreviewFrame.vue`：主路径改为 bundler——监听 `store.generatedFiles` 变化防抖触发 rebuild，bundle 以 blob URL 注入 iframe；保留 compileSFC 降级路径
- [ ] 2.3 验证完整应用预览：含路由跳转、多页面、pinia 数据流的生成工程在 iframe 中原样渲染并可交互

## 3. 编译错误反馈闭环

- [x] 3.1 前端 `useBundler.ts` 增加错误上报：硬错误（非 partial）结构化（file/line/column/text + generation_id）POST 至 `/api/v1/generation/compile_feedback`
- [x] 3.2 gateway 新增 `POST /api/v1/generation/compile_feedback` 端点，转发至 AI service
- [x] 3.3 AI service servicer 接收上报并写入对应 GraphRunner 持有的 generation state（`pending_compile_errors`）
- [x] 3.4 改造后端 `tools/compile_tool.py`：`compile_project` 返回前端上报的真实错误（不再做 `f.read()` 假检查）；无上报时按最近一次打包结果返回
- [x] 3.5 对接 Executor：`executor_task` 的 compile 分支消费真实错误驱动 fix_error 循环，AgentLog 同步展示真实编译结果
- [x] 3.6 AgentLog 编译卡片接入 bundler 结果：成功绿色/失败红色 + 错误条目点击跳转文件

## 4. 验证与清理

- [ ] 4.1 端到端验证：设计文档 → Planner/Executor 生成完整工程 → 预览区实时渲染完整应用（路由可跳转）
- [ ] 4.2 端到端验证：注入语法错误的生成代码 → 预览报错 + 错误反馈后端 → Executor 修复 → 预览恢复
- [ ] 4.3 验证降级路径：模拟 wasm 初始化失败 → 单组件预览正常 + "降级预览"标识展示
- [ ] 4.4 验证 partial 静默：流式中途不展示 `Could not resolve` 错误、不上报，文件齐后自动重建成功
