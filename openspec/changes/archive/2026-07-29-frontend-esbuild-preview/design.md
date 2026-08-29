## Context

功能开发节点经过 Planner/Executor ReAct 改造后，生成物是完整 qiankun 微应用工程（`src/main.ts` 入口、`App.vue` + `<router-view/>`、pinia store、`@/` 别名、动态 import）。但两处架构仍停留在单组件时代：

- **后端校验**：[compile_tool.py](../../../ai-design-platform-server/ai-service/app/services/generation/tools/compile_tool.py) 仅 `f.read()` 检查文件可读，LLM 永远收到 "0 errors"。
- **前端预览**：[compileSFC.ts](../../../ai-design-platform-web/packages/ai-generation-app/src/utils/compileSFC.ts) 用正则把 import 改写为 `__DEPS__[...]` 查表，而 `__DEPS__ = {}` 为空；[useMultiCompiler.ts](../../../ai-design-platform-web/packages/ai-generation-app/src/composables/useMultiCompiler.ts) 多文件合并产物不被收集；只支持编译单个 `.vue`。

约束：后端服务机器不引入 Node 运行时；预览保真度要求为"完整应用"（路由跳转、多页面、真实数据流）。

## Goals / Non-Goals

**Goals:**
- 浏览器内 esbuild-wasm 真打包生成的完整工程，iframe 中原样渲染完整应用
- esbuild 精确报错（file:line:column）反馈给后端 Executor，自我纠错闭环真实生效
- 流式生成过程中的增量预览（文件陆续到达时持续重建，可恢复错误不打扰用户）
- wasm 初始化失败时降级回现有单组件预览路径

**Non-Goals:**
- 不改动 Planner/Executor 的任务拆解与 ReAct 循环逻辑本身
- 不改变生成物的 qiankun 工程结构（main.ts/webpack/package.json 模板保持不变）
- 不做生产构建（`pnpm build`、产物部署）——本次只解决开发预览
- 不引入后端 Node 运行时做编译

## Decisions

### D1: 打包放浏览器（esbuild-wasm），不放后端 Node

**选择**：`esbuild-wasm` 在前端初始化（`esbuild.initialize({ wasmURL })`），wasm 文件随 ai-generation-app 静态资源分发，浏览器缓存。

**替代方案**：后端 Node 子进程跑 esbuild，产物推给 iframe。否决原因：后端需装 Node（用户明确拒绝）；打包与预览跨进程传递，错误展示与反馈不同源。

**权衡**：wasm ~8MB 首次加载，可通过 preload + 浏览器缓存摊销；后续增量 rebuild（esbuild 增量 API）耗时 <100ms 级。

### D2: 内存文件系统 resolver 插件

生成文件在 `store.generatedFiles`（内存 Map），esbuild 浏览器版无磁盘访问。写 esbuild plugin：

- `onResolve`：
  - `vue` / `vue-router` / `pinia` / 组件库包 → `external: true`（交给 iframe import map）
  - `@/xxx` → `src/xxx`（别名）
  - `./xxx`、`../xxx` → 相对 importer 在内存 Map 中解析，依次尝试 `xxx`、`xxx.vue`、`xxx.ts`、`xxx.js`、`xxx/index.ts`
- `onLoad`：
  - `.vue` → `vue/compiler-sfc` 编译（compileScript + compileTemplate + compileStyle），返回 `loader: 'js'`；style 内容单独收集合并注入 iframe `<style>`
  - `.ts` → `loader: 'ts'`（esbuild 原生处理）
  - `.css` → `loader: 'css'`

**替代方案**：继续用正则变换 import（现状）。否决原因：不支持 import 图、动态 import、别名、目录 index，已被证实是断裂根源。

### D3: 依赖外置 + import map，不打进 bundle

iframe HTML 模板：

```html
<script type="importmap">
{ "imports": {
    "vue": "https://esm.sh/vue@3",
    "vue-router": "https://esm.sh/vue-router@4",
    "pinia": "https://esm.sh/pinia@2"
} }
</script>
<script type="module" src="<blob:bundle.js>"></script>
```

bundle 只含业务代码（通常 <100KB），rebuild 快；CDN 依赖浏览器级缓存。**风险**：esm.sh 不可达时需降级（见 D6）。生成的 qiankun 工程用的 `vue-router`/`pinia` 版本与 CDN 主版本对齐即可，不做精确锁定。

### D4: 入口即 `src/main.ts`，原样 mount

生成的 `src/main.ts` 含 `if (!window.__POWERED_BY_QIANKUN__) render()`——iframe 中无该标记，自动执行 `createApp(App).use(pinia).use(router).mount('#app')`。**完整工程零改动预览**，这是本设计的关键对齐点：预览消费的就是发布物本身，不存在"预览专用版本"。

无 `src/main.ts`（旧格式生成物）时 fallback 合成入口：内存中生成 `__preview_entry__.ts` = `createApp(App).mount('#app')`。

### D5: 编译错误反馈闭环（前端 → 后端 → Executor）

```
esbuild build() 抛 BuildFailure
  → errors[]: { file, line, column, text }
  → 前端结构化后 POST /api/v1/generation/compile_feedback { generation_id, errors, phase }
  → gateway 转发 AI service
  → servicer 写入该 generation 的 GraphRunner 持有的 state.pending_compile_errors
  → Executor 下一轮 LLM 调用前，把真实错误注入 messages
```

后端 `compile_project` 工具改造：不再做 `f.read()`，改为返回最近一次前端上报的错误（若有）；Executor 的 compile 分支消费真实错误驱动 `fix_error`。流式生成途中依赖未齐的 `Could not resolve` 类错误标记为 partial，**不上报**，仅等更多文件到达后重建。

**替代方案**：后端 Python 做语法检查（tree-sitter/esprima）。否决原因：无法校验 import 图与类型，与预览编译结果不同源——"后端说过了、预览是坏的"割裂正是本次要消灭的 bug。

### D6: 失败降级

esbuild-wasm 初始化失败（wasm 加载失败、浏览器不支持、CDN 不可达）→ 捕获后回退现有 `useMultiCompiler` + `compileSFC` 单组件路径，UI 标注"降级预览"。旧代码路径保留不删。

## Risks / Trade-offs

- **wasm 8MB 首载慢** → 应用 idle 时 `requestIdleCallback` 预加载 + HTTP 缓存；加载期间显示"编译器初始化中"
- **esm.sh CDN 不可达（内网/离线）** → 依赖外置改为从本地 `node_modules` 构建产物外链，或降级单组件预览
- **生成代码引用未生成文件（流式中途）** → `Could not resolve` 归类 partial，静默等待；完成信号后仍报错才上报
- **esbuild rebuild 频繁触发（每个 file_chunk）** → debounce 300ms + esbuild 增量 rebuild；chunk 级更新只更新虚拟 FS，不 rebuild
- **浏览器兼容**（esbuild-wasm 需 WebAssembly + Worker）→ 目标浏览器均为现代 Chromium，可接受

## Migration Plan

1. 新增 bundler 模块与依赖（`esbuild-wasm`），不改现有路径
2. `PreviewFrame` 增加 bundler 优先 / compileSFC 降级的双路径开关
3. 后端 compile_feedback 端点 + compile_tool 改造
4. 验证完整应用预览 + 错误反馈修复循环后，单组件路径保留为降级分支

## Open Questions

- esm.sh 是否允许作为生产依赖源，还是必须自托管/本地化？（影响 D3 fallback 实现量）
- 编译错误反馈是否需要在 AgentLog 中同步展示为红色卡片？（倾向：是，与现有 compile 卡片样式一致）
