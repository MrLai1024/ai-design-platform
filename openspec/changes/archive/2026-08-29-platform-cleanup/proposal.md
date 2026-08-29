# 平台清理与 UI 迭代

## Why

平台存在冗余资产与风格不一致:AI 对话、AI 工作流两个子应用已不再使用(仅剩基座注册链与共享代码残留);前端散落调试日志;项目空间子应用的 UI 细节(详情页 Tabs、面包屑无当前项标识、布局边界不清晰)与整体"菜单化、层次化"的风格不符;样式集中在 global.css 不利于组件内聚。

## What Changes

- **删除两个子应用**:
  - 删除 `packages/ai-chat-app/`、`packages/ai-workflow/` 整个包
  - 删除 shared 纯 chat 模块:`api/chat.ts`、`useChatStream`、`useConversation`、`types/chat.ts` 及对应测试;同步清理导出(app-names 常量、api/types/index 导出)
  - 清理注册链:micro-core apps-config、基座导航/容器/路由、Home.vue 卡片、根 dev/build 脚本、pnpm-lock
  - **保留**(存在交叉引用):`MarkdownRenderer.vue`、`useMarkdown`(被 ai-generation-app 引用)、`events.ts`(AUTH_UNAUTHORIZED 被基座使用)
  - 边界:ai-generation-app 与 project-space-app 零影响;后端 AI 链路接口(chats/conversations)不动
- **清理前端 console 日志**:全部 console.*(21 处/8 文件:子应用生命周期 log、状态打印、异常 warn),空块按 lint 约定处理;后端 slog 保留
- **UI 迭代**:
  - 项目详情页 Issue/代码仓:antd Tabs → 垂直菜单(左侧 inline 菜单 160px + 右侧内容区)
  - 面包屑当前项高亮(主题蓝 + 加粗)
  - 布局三区边界感:灰底 `rgb(134,134,134)` 画布 + 白区(侧栏/头部/内容卡片)描边与阴影
  - 组件样式 scoped 化:布局类迁入 AppLayout/ProjectDetailView `<style scoped>`,跨组件共享工具类保留 global.css
  - style-isolation-fix 扩展:从仅监听 antd `style[data-css-hash]` 扩展为 wrapper 内**所有** style 元素(覆盖 vue scoped 样式的前缀竞态)

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `project-space`:详情页菜单展示方式(垂直菜单)与面包屑当前项高亮,属 UI 展示细化;无接口/数据结构变更。

## Impact

- **前端**:删除 2 个包;shared/micro-core/main 的注册链与导出清理;4 个包(shared/main/micro-core/ai-generation/project-space)测试适配与验证;全局 console 清理;项目空间子应用样式 scoped 化与 UI 调整。
- **后端**:零改动(slog 日志保留)。
- **文档**:无规格级变更(主 specs 已与实现一致,UI 细节不进 spec)。
