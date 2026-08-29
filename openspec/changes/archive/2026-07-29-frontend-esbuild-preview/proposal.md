## Why

功能开发节点（code node）生成的代码质量不稳定，且生成后无法预览，根因是两个断裂：

1. **后端假编译**：`compile_project` 工具只检查文件能否读取（`f.read()`），不做任何语法/类型/import 校验。LLM 的 Executor 在 ReAct 循环中永远收到"0 errors"，自我纠错闭环形同虚设，语法错误原样交付。
2. **预览架构与生成物形态不匹配**：预览系统停留在单组件形态（`compileSFC` + 正则 import 变换 + 空 `__DEPS__` 表），而 Planner/Executor 生成的是完整 qiankun 微应用工程（vue-router、pinia、`@/` 别名、动态 import），预览时全部解析失败，实时预览区白屏。

用户已确认需求：预览必须看到**完整应用**（路由跳转、多页面、真实数据流）；打包放在**浏览器前端**完成，后端不引入 Node 运行时。

## What Changes

- **前端打包管线**：浏览器内 esbuild-wasm 真打包生成的完整工程，替代现有 `useMultiCompiler` + `compileSFC` 单组件编译路径：
  - 内存文件系统 resolver 插件——从 `store.generatedFiles` 解析 import（`@/` 别名 → `src/`、相对路径、目录 index）
  - `.vue` 文件 load hook——用 `vue/compiler-sfc` 编译为 JS
  - vue / vue-router / pinia 标记 external，iframe 内 import map 指向 esm.sh CDN
  - 入口 `src/main.ts` 利用其 `__POWERED_BY_QIANKUN__` 判断在 iframe 中自动 mount，完整工程原样预览
- **编译错误反馈闭环**：esbuild 精确报错（file:line:column）经前端 POST 回后端，注入 Executor 的 Observe 阶段；后端 `compile_project` 工具改为返回前端上报的真实错误，自我纠错闭环真实生效。
- **边界处理**：流式中途依赖文件未齐时 resolve 失败标记为 partial（等待更多文件而非报错）；无 `src/main.ts` 时 fallback 合成入口；esbuild-wasm 初始化失败时降级回现有单组件预览路径。

## Capabilities

### New Capabilities

- `frontend-bundler`: 浏览器内 esbuild-wasm 打包管线——内存 FS 解析、Vue SFC 编译、CDN 依赖外置、增量重建、完整应用 iframe 预览渲染。
- `compile-feedback`: 编译错误反馈闭环——前端打包错误结构化上报后端、注入 Executor ReAct Observe 阶段、后端 compile 工具返回真实错误。

### Modified Capabilities

（无现有 spec，不涉及修改）

## Impact

- **前端**（`ai-generation-app`）：新增 `useBundler.ts`（esbuild-wasm 封装）、`bundlerPlugin.ts`（内存 FS + vue plugin）；改造 `PreviewFrame.vue`（替换 compileSFC 路径）、`useMultiCompiler.ts`（被 bundler 替代或移除）；iframe HTML 模板改为 import map + ES module 加载；新增 esbuild-wasm 依赖（wasm ~8MB，浏览器缓存）。
- **后端**（`ai-service`）：`compile_tool.py` 改造为读取前端上报错误；新增 `compile_feedback` 事件/端点接收前端上报；`executor_task` 的 compile 分支对接真实错误。
- **网关**（gateway）：新增 `POST /api/v1/generation/compile_feedback` 转发端点。
- **降级路径保留**：esbuild-wasm 初始化失败时回退现有 `compileSFC` 单组件预览，不做 **BREAKING** 移除。
