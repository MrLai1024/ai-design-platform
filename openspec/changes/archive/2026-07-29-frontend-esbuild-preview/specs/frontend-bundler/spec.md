## ADDED Requirements

### Requirement: 浏览器内完整工程打包

系统 SHALL 在浏览器内使用 esbuild-wasm 对功能开发节点生成的完整工程文件进行真实打包，产出可在 iframe 中直接执行的 ES module bundle。

#### Scenario: 完整工程打包成功

- **WHEN** 生成的工程包含 `src/main.ts` 入口、`App.vue`、路由、store、多个视图组件
- **THEN** 打包器将入口及其完整 import 图打包为单个 ES module，包含全部业务代码

#### Scenario: 入口文件自动执行

- **WHEN** bundle 在预览 iframe 中以 `<script type="module">` 加载
- **THEN** 生成的 `src/main.ts` 因不存在 `__POWERED_BY_QIANKUN__` 标记而自动执行 `createApp(...).mount('#app')`，完整应用渲染

### Requirement: 内存文件系统模块解析

打包器 SHALL 通过 esbuild 插件从内存中的生成文件集合解析 import，支持 `@/` 别名（映射至 `src/`）、相对路径、扩展名补全（`.vue`/`.ts`/`.js`）与目录 `index` 文件。

#### Scenario: 别名解析

- **WHEN** 某文件包含 `import Home from '@/views/Home.vue'`
- **THEN** 打包器从内存文件集合中的 `src/views/Home.vue` 解析该模块

#### Scenario: 相对路径与扩展名补全

- **WHEN** 某文件包含 `import Header from './components/Header'`
- **THEN** 打包器依次尝试 `./components/Header.vue`、`.ts`、`.js`、`./components/Header/index.ts` 直至命中

### Requirement: Vue SFC 编译

打包器 SHALL 使用 `vue/compiler-sfc` 在 `.vue` 文件 load hook 中编译 script 与 template 为 JavaScript，并将 style 内容收集后注入预览文档。

#### Scenario: SFC 编译为可执行模块

- **WHEN** 打包过程遇到 `.vue` 文件
- **THEN** 该文件被编译为含 render 函数的 JS 模块，scoped 样式带 scope id，样式内容合并进预览文档 `<style>` 标签

### Requirement: 第三方依赖外置

打包器 SHALL 将 `vue`、`vue-router`、`pinia` 标记为 external，由预览 iframe 的 import map 从 CDN 提供，bundle 仅包含业务代码。

#### Scenario: 依赖经 import map 解析

- **WHEN** 业务代码 import `vue`/`vue-router`/`pinia`
- **THEN** bundle 保留裸模块标识符，iframe 通过 import map 从 CDN 加载对应 ESM 版本

### Requirement: 增量重建与防抖

打包器 SHALL 在生成文件变化后防抖触发增量重建（rebuild），单个文件内容更新不重排整个 import 图。

#### Scenario: 文件变化后自动重建

- **WHEN** 生成文件集合中任一文件完成或更新
- **THEN** 打包器在防抖窗口后执行增量 rebuild 并刷新预览，期间不阻塞 UI

### Requirement: 可恢复错误静默

打包器 SHALL 将流式生成过程中因依赖文件尚未生成导致的 `Could not resolve` 类错误归类为 partial，静默等待更多文件到达后重试，不向用户展示也不上报后端。

#### Scenario: 流式中途依赖缺失

- **WHEN** 文件 A 已生成且 import 了尚未生成的文件 B
- **THEN** 打包失败被标记为 partial，预览保持最近一次成功结果，不显示错误

### Requirement: 无入口文件降级

当生成工程缺少 `src/main.ts` 时，打包器 SHALL 在内存中合成默认入口（`createApp(App).mount('#app')`）完成预览。

#### Scenario: 旧格式生成物预览

- **WHEN** 生成文件包含 `App.vue` 但无 `src/main.ts`
- **THEN** 打包器合成入口模块引用 `App.vue`，应用正常渲染

### Requirement: 初始化失败降级

当 esbuild-wasm 初始化失败（wasm 加载失败或环境不支持）时，系统 SHALL 回退到既有单组件编译预览路径，并在 UI 标注降级状态。

#### Scenario: wasm 加载失败

- **WHEN** esbuild-wasm 初始化抛出异常
- **THEN** 预览组件切换到单组件编译路径，界面显示"降级预览"标识
