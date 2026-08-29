# 设计:平台清理与 UI 迭代

## Context

平台前端经过多轮迭代后存在冗余与风格不一致:两个废弃子应用(ai-chat-app/ai-workflow)仍挂在注册链上;共享包残留纯 chat 模块;项目空间子应用 UI 细节未达"菜单化、层次化"标准;样式全部堆在 global.css。本次为纯前端清理与 UI 迭代,后端零改动。

## Goals / Non-Goals

**Goals:**
- 移除废弃子应用及全部相关前端代码,消除注册链噪音
- 前端无任何 console 调试日志(后端 slog 保留,运维日志不受影响)
- 项目空间 UI 统一:详情页垂直菜单、面包屑当前项高亮、布局三区层次分明
- 组件样式内聚(scoped),共享工具类保留 global.css
- 不影响 ai-generation-app 与 project-space-app 的功能与测试

**Non-Goals:**
- 不删后端 chat/conversation 接口(平台 AI 能力,与子应用解耦)
- 不改其他子应用的行为与样式(仅删除/清理涉及它们的注册链)

## Decisions

### D1: 删除边界 —— 保留交叉引用资产

删除 ai-chat-app/ai-workflow 时发现 `MarkdownRenderer.vue` 与 `useMarkdown` 被 **ai-generation-app 的 StageOutput.vue** 引用(初查漏检:grep 模式未含组件名)。处理:仅删**纯 chat 文件**(api/chat、useChatStream、useConversation、types/chat 及测试),保留 MarkdownRenderer/useMarkdown/setup.ts/events.ts。删除前必须全量 grep 引用(含组件名/组合式函数名,不限于 chat 字样)。

### D2: 样式 scoped 化 + 前缀竞态加固

样式归属规则:
- **组件独有样式**(布局三区、面包屑高亮、详情页菜单)→ 组件 `<style scoped>`,antd 组件根元素经 data-v 属性可匹配,必要时用 `:deep`
- **跨组件共享工具类**(`.page-*`、`.clickable-item`、`.join-*` 等)→ 保留 global.css

**关键加固**:scoped 样式(vue-loader)同样会因 HMR 重写文本而丢失 qiankun 前缀(坑 2 变体),故 style-isolation-fix 的 MutationObserver 从 `style[data-css-hash]` 扩展为 **wrapper 内所有 style 元素**,needsPrefix/prefixCss 复用既有实现(幂等、@media 递归、@keyframes 跳过)。

### D3: UI 细节

- 详情页:antd Tabs → `mode="inline"` 菜单(左 160px + 右内容区,flex 布局),测试断言改为 `.ant-menu-item`/`.ant-menu-item-selected`
- 面包屑:当前项(无 path 的 span)加 `crumb-current` class,主题蓝 + 600 字重,组合选择器提特异性防 antd last-child 覆盖
- 布局:画布灰底 `rgb(134,134,134)`(用户定色)+ `!important` 防前缀竞态;白区描边 + 阴影(深灰画布上 0.15-0.16 alpha 才有可见层次)

## Risks / Trade-offs

- [误删交叉引用资产] → D1 全量 grep 含组件名;实施中"发现引用即停"上报
- [scoped 样式踩前缀竞态] → D2 扩展 fix 覆盖所有 style,补测试
- [`!important` 依赖] → 仅布局背景一处,注释说明原因(坑 2 竞态),后续 qiankun 升级可移除
- [空块处理] → 删 console 后空 if/catch 按 lint 约定处理(注释 no-op 或整删无副作用分支)

## Migration Plan

已完成(归档记录):删除包与注册链 → shared 导出清理 → console 清理 → UI 迭代 → 样式 scoped 化 + fix 扩展 → 全包测试验证 → grep 残留确认。

## Open Questions

- 无
