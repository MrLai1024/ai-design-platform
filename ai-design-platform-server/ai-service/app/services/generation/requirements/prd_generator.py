"""PRDGenerator — 从 RequirementsState 流式生成 PRD 文档."""

from __future__ import annotations

import structlog

from .state import RequirementsState

logger = structlog.get_logger()

PRD_SYSTEM_PROMPT = """你是一个资深产品需求文档撰写专家。根据结构化需求数据，生成一份完整的需求规格文档。

## 文档结构（严格按此顺序输出）
1. **# 需求规格文档** — 文档标题
2. **## 1. 功能概述** — 项目背景、核心问题、目标用户、成功标准、范围边界
3. **## 2. 功能模块** — 按优先级排列的功能模块清单（must → should → nice），每个模块含名称、描述、子功能点
4. **## 3. 页面结构** — 页面树形结构，标注页面类型（列表/详情/表单/仪表盘）
5. **## 4. 数据模型** — 核心数据实体及字段定义
6. **## 5. 交互行为** — 关键页面的操作流程和交互说明

## 规则
- 用简洁专业的语言，每条一句话
- 数据实体使用表格展示字段
- 不写代码，不写技术实现，不写组件选择
- 不确定的地方标注（待确认）
"""


async def generate_prd_full(state: RequirementsState, llm_generate) -> str:
    """从完整 state 流式生成 PRD（NEW/EDIT 模式）。

    Args:
        state: 完成三层收集的 RequirementsState
        llm_generate: Callable[[str, str], Awaitable[str]]
                      传入 system_prompt 和 user_prompt，返回完整生成文本。
                      流式输出在 GraphRunner SSE 层处理，此处仅等待完整结果。

    Returns:
        完整的 PRD markdown 字符串

    Raises:
        ValueError: 如果 state 未完成收集（layer < 3 且缺少 features/pages）
    """
    if state.layer < 3 and not (state.features or state.pages):
        raise ValueError(
            f"RequirementsState 收集未完成 (layer={state.layer})，"
            f"至少需要完成 Layer 2 收集或达到 layer >= 3 才能生成 PRD"
        )

    context = _build_context(state)
    user_prompt = f"请根据以下结构化需求数据生成需求规格文档：\n\n{context}"

    full_text = await llm_generate(PRD_SYSTEM_PROMPT, user_prompt)

    logger.info("prd_generated", length=len(full_text), mode="full")
    return full_text


async def generate_prd_diff(
    current: RequirementsState,
    parent: RequirementsState,
    llm_generate,
) -> str:
    """从两个版本 state 生成增量 PRD diff（APPEND 模式）。

    Args:
        current: 当前（新版本）RequirementsState
        parent: 父版本 RequirementsState
        llm_generate: Callable[[str, str], Awaitable[str]]
                      传入 system_prompt 和 user_prompt，返回完整生成文本。
                      流式输出在 GraphRunner SSE 层处理，此处仅等待完整结果。

    Returns:
        增量 PRD markdown 字符串（仅包含新增/变更内容）
    """
    diff_system_prompt = PRD_SYSTEM_PROMPT + f"""

## 增量模式
用户已有一个 PRD v{parent.version}，现在要在此基础之上追加新功能模块。

## 输出要求
1. 对于**没有变化**的章节（如功能概述、已有功能模块），输出一句简短说明即可
2. 对于**新增或变化**的章节，正常展开描述
3. 在文档开头注明这是增量更新版本

请按此格式输出。"""

    context_current = _build_context(current)
    context_parent = _build_context(parent)
    user_prompt = (
        f"原始需求（v{parent.version}）：\n{context_parent}\n\n"
        f"新增需求（v{current.version}）：\n{context_current}\n\n"
        f"请输出增量变更的 PRD 文档，聚焦于新增和修改的部分。"
    )

    full_text = await llm_generate(diff_system_prompt, user_prompt)

    logger.info("prd_generated", length=len(full_text), mode="diff",
                from_version=parent.version, to_version=current.version)
    return full_text


def _build_context(state: RequirementsState) -> str:
    """将 RequirementsState 转为 LLM 可读的文本上下文."""
    parts = []

    # Layer 1: Vision
    v = state.vision
    parts.append("## 项目愿景")
    parts.append(f"- 名称: {v.project_name or '未命名项目'}")
    if v.target_users:
        parts.append(f"- 目标用户: {', '.join(t.role for t in v.target_users)}")
    if v.core_problem:
        parts.append(f"- 核心问题: {v.core_problem}")
    if v.success_criteria:
        parts.append(f"- 成功标准: {'; '.join(v.success_criteria)}")
    if v.scope_note:
        parts.append(f"- 范围: {v.scope_note}")

    # Layer 2: Features
    if state.features:
        parts.append("\n## 功能模块")
        sorted_features = sorted(
            state.features,
            key=lambda x: {"must": 0, "should": 1, "nice": 2}.get(x.priority, 3)
        )
        for f in sorted_features:
            parts.append(f"- [{f.priority}] {f.name}: {f.description} (完整度: {f.completeness}%)")

    # Layer 2: Pages
    if state.pages:
        parts.append("\n## 页面结构")
        for p in state.pages:
            indent = "  " if p.parent_id else ""
            parts.append(f"{indent}- {p.name} ({p.page_type})")

    # Layer 3: Page Details
    if state.page_details:
        parts.append("\n## 页面详情")
        for pid, pd in state.page_details.items():
            parts.append(f"\n### {pid}")
            if pd.display_fields:
                parts.append("展示字段:")
                for df in pd.display_fields:
                    req = " *" if df.required else ""
                    parts.append(f"  - {df.name} ({df.type}){req}")
            if pd.action_buttons:
                parts.append(f"操作: {', '.join(a.label for a in pd.action_buttons)}")
            if pd.related_data:
                parts.append(f"关联数据: {', '.join(pd.related_data)}")
            if pd.layout_notes:
                parts.append(f"布局: {pd.layout_notes}")

    # Layer 3: Tech Constraints
    tc = state.tech_constraints
    has_tech = any([tc.framework, tc.component_lib, tc.data_source, tc.special_requirements])
    if has_tech:
        parts.append("\n## 技术约束")
        parts.append(f"- 框架: {tc.framework or '待确认'}")
        parts.append(f"- 组件库: {tc.component_lib or '待确认'}")
        parts.append(f"- 数据源: {tc.data_source or '待确认'}")
        if tc.special_requirements:
            parts.append(f"- 特殊要求: {', '.join(tc.special_requirements)}")

    # Layer 3: Data Entities
    if state.data_entities:
        parts.append("\n## 数据实体")
        for de in state.data_entities:
            parts.append(f"\n### {de.name}")
            if de.fields:
                parts.append("| 字段 | 类型 | 必填 |")
                parts.append("|------|------|------|")
                for fl in de.fields:
                    req = "是" if fl.get("required") else "否"
                    parts.append(f"| {fl.get('name', '?')} | {fl.get('type', 'string')} | {req} |")

    return "\n".join(parts)
