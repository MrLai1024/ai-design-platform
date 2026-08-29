# project-space Specification

## Purpose

项目空间子应用 UI 展示细化:详情页菜单展示方式与面包屑当前项标识。接口与数据结构不变。

## MODIFIED Requirements

### Requirement: 项目详情菜单留白

系统 SHALL 提供项目详情页,包含 Issue、代码仓两个菜单项,菜单内容本期留白(占位)。

#### Scenario: 详情页菜单结构

- **WHEN** 用户点击任一项目进入项目详情
- **THEN** 详情页以垂直菜单展示 Issue、代码仓两个菜单项(左侧竖排,定宽约 160px,右侧为内容区),可点击切换,两个菜单内容区均为占位状态

### Requirement: 面包屑逐级导航

子应用头部面包屑 SHALL 按路由层级逐级展示且可点击跳转,当前项 SHALL 高亮标识。

#### Scenario: 面包屑当前项高亮

- **WHEN** 面包屑渲染完成
- **THEN** 当前激活项(末级,不可点击)文字以主题色高亮并加粗,与可点击的上级项视觉区分
