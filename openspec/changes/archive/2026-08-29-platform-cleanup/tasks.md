# 实施任务

> 本 change 为归档记录:全部任务已在代码中完成,此处按实施顺序记录。

## 1. 删除废弃子应用

- [x] 1.1 删除 `packages/ai-chat-app/`、`packages/ai-workflow/` 全部文件
- [x] 1.2 删除 shared 纯 chat 模块(api/chat、useChatStream、useConversation、types/chat 及 chat-types/useChatStream 测试);保留 MarkdownRenderer/useMarkdown(被 ai-generation-app 引用)与 events.ts
- [x] 1.3 清理导出:app-names 常量、api/types/index 导出、shared index.ts
- [x] 1.4 清理注册链:micro-core apps-config(保留 2 子应用)、基座 App.vue 导航/容器、router、Home.vue 卡片(grid-cols-2)、根 dev/build 脚本、pnpm-lock 更新
- [x] 1.5 测试适配:app-names/apps-config/app.test 更新;shared 46、micro-core 7、main 23、ai-generation 22 全绿;grep 残留零命中

## 2. console 日志清理

- [x] 2.1 删除全部 console.*(21 处/8 文件:ai-generation 生命周期与 warn、micro-core lifecycle、project-space main);空块按 lint 约定处理(no-op 注释或整删无副作用分支)
- [x] 2.2 验证:grep 零残留;四包测试全绿;改动文件 tsc/eslint 零新增问题;后端 slog 保留

## 3. UI 迭代

- [x] 3.1 详情页 Issue/代码仓:Tabs → 垂直菜单(inline,160px + 右侧内容区);测试改菜单断言
- [x] 3.2 面包屑当前项高亮:crumb-current class + 主题蓝/加粗样式(组合选择器提特异性)
- [x] 3.3 布局边界感:画布灰底 rgb(134,134,134)(用户定色)+ !important;白区描边与阴影(深灰画布 0.15-0.16 alpha)
- [x] 3.4 样式 scoped 化:布局类迁入 AppLayout/ProjectDetailView,共享工具类留 global.css
- [x] 3.5 style-isolation-fix 扩展:监听 wrapper 内所有 style 元素(覆盖 scoped 前缀竞态);补测试(非 data-css-hash style 也重加前缀、非 style 元素忽略)

## 4. 验证

- [x] 4.1 全包测试:shared 46 / micro-core 7 / main 23 / ai-generation 22 / project-space 87+3(3 个为既有视图改动前置失败,与本 change 无关)
- [x] 4.2 tsc 各包通过;CDP 实机验证 scoped 样式、面包屑高亮、详情垂直菜单在 qiankun 下生效且路由切换稳定
