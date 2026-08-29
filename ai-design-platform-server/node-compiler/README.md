# node-compiler

服务端真实编译 worker —— 对 AI 生成的 Vue 工程执行 esbuild bundle 校验（语法 / import 解析 / SFC 编译）+ vue-tsc 类型检查（`--noEmit`）。

## 为什么存在

前端 esbuild-wasm 只做语法与 import 解析，**不做类型检查**；且前端反馈是"透传信号"——前端未上报即被认为编译通过（假编译）。node-compiler 是 Executor `compile_project` 的真实编译源，消灭假编译。

## 接口

`POST /compile`

```jsonc
{
  "project_root": "D:/.../data/generated/<app_id>",
  "full": false,        // true 时追加 vue-tsc 类型检查
  "entry": "src/main.ts" // 可选，默认自动探测
}
```

响应：

```jsonc
{
  "ok": true,
  "errors": [
    { "file": "src/main.ts", "line": 2, "column": 16,
      "message": "...", "source": "esbuild" | "vue-tsc" }
  ]
}
```

- `full=false`（Executor 中途快速校验）：esbuild bundle，毫秒级
- `full=true`（最终编译检查）：esbuild + vue-tsc `--noEmit`
- 项目目录不存在 / 为空 / 无入口 → 显式错误，**绝不返回"通过"**

## 依赖解析规则

- `.vue` SFC：`@vue/compiler-sfc` 编译（与前端 bundler 的 vuePlugin 同规则）
- `@/` 别名 → `src/`；相对路径支持扩展名补全（`.vue`/`.ts`/`.js`/目录 index）
- `vue` / `vue-router` / `pinia` 标记 external（bundle 不打包框架）
- 类型检查用内置类型 stub（`src/shims/`）——生成工程没有自己的 node_modules

## 开发

```bash
npm install
npm run dev      # http://localhost:5199
npm test         # node --test
```

## 部署

docker-compose 已包含 `node-compiler` 服务（端口 5199）。ai-service 通过
`NODE_COMPILER_ADDR`（默认 `http://localhost:5199`，容器内 `http://node-compiler:5199`）
调用；gateway 提供 `POST /api/v1/generation/compile` 转发（调试/前端用）。
