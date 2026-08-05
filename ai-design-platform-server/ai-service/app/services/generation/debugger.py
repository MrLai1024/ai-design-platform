"""Debugger — 证据链根因修复 (task 5.5).

When the Verifier fails (or executor tasks fail with evidence), the Debugger:

1. **诊断**: LLM reads the evidence (compile errors / contract violations /
   runtime errors / hook violations) + the failing task contracts + relevant
   file contents, and outputs ``{root_cause, fix_instructions, affected_files}``
   (structured JSON via brainstorm's ``_llm_structured`` seam — fail-safe to
   empty defaults on unparsable output).
2. **重派**: ``apply_fix_round`` maps ``affected_files`` → owning tasks in the
   task DAG and marks them pending, threading the fix instructions into the
   executor prompt (graph phase 3 re-runs the affected tasks).
3. **无进展检测**: the same evidence signature (``verifier.evidence_signature``)
   across fix rounds means fixing is not making progress → stop and escalate
   to the Manager gate (verdict redo with evidence) instead of looping.

Fix rounds are bounded (``MAX_FIX_ROUNDS = 2``) and tracked in state
``debugger_rounds`` (round / signature / diagnosis).
"""

from __future__ import annotations

import time

import structlog

from .verifier import evidence_signature  # noqa: F401  (re-exported for callers)

logger = structlog.get_logger()

# 5.5: 修复轮次上限（每 phase-3 pass 最多 2 轮，之后交给 Manager 把关）。
MAX_FIX_ROUNDS = 2

# Structured-output schema for the diagnosis (fail-safe defaults).
DEBUGGER_SCHEMA: dict = {
    "root_cause": "",
    "fix_instructions": "",
    "affected_files": [],
}

DEBUGGER_PROMPT = """你是 AI 生成流水线中的 Debugger（修复专家）。代码生成验证失败后，基于证据链定位根因并输出修复指令。

## 输入
- 验证失败证据：编译错误（file/line/message）、契约违约（consumer/provider/detail）、运行时错误（type/message）、埋点缺失（file/tag/line）
- 失败任务的任务描述与接口契约
- 相关生成文件内容

## 修复原则
- 根因从证据反推：编译错误→语法/导入问题；契约违约→导出名/props/事件不一致；运行时错误→组件挂载/数据访问问题；埋点缺失→交互元素补 data-testid（语义化 kebab-case）
- affected_files 只列必须修改的文件（重派范围最小化）
- 修复指令必须具体可执行（指明文件、修改点、目标状态）

## 输出格式（只输出一个 JSON 对象）
{"root_cause": "根因一句话", "fix_instructions": "逐步修复指令", "affected_files": ["src/components/Header.vue"]}
- affected_files：待修复文件路径列表；无明确文件时给空数组"""


def no_progress(state: dict, signature: str) -> bool:
    """无进展检测 — 该证据签名已在之前的修复轮中出现过。

    同一失败不得以相同方式重复执行（spec 5.5）: evidence 未变化说明修复
    无效，停止自动修复，升级为 Manager 恢复决策。
    """
    rounds = state.get("debugger_rounds") or []
    return any(r.get("signature") == signature for r in rounds)


def record_round(state: dict, signature: str, diagnosis: dict) -> None:
    """Append one fix round to ``debugger_rounds`` (证据签名 + 诊断)."""
    rounds = list(state.get("debugger_rounds") or [])
    rounds.append({
        "round": len(rounds) + 1,
        "signature": signature,
        "diagnosis": diagnosis,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    state["debugger_rounds"] = rounds


def build_diagnosis_prompt(state: dict, evidence: dict) -> str:
    """Assemble the diagnosis input: evidence + failing contracts + file contents.

    File contents are the files named in the evidence (compile errors /
    hook violations / contract violations), capped per file — keep the
    diagnosis call small.
    """
    parts = [
        "## 验证失败证据",
        "### 编译错误",
        "\n".join(
            f"- {e.get('file', '?')}:{e.get('line', '?')} {e.get('message', '')}"
            for e in (evidence.get("compile_errors") or [])
        ) or "- 无",
        "### 契约违约",
        "\n".join(
            f"- [{v.get('type', '?')}] {v.get('file', '?')}: {v.get('detail', '')}"
            for v in (evidence.get("contract_violations") or [])
        ) or "- 无",
        "### 运行时错误",
        "\n".join(
            f"- [{e.get('type', '?')}] {e.get('message', '')} {e.get('url', '')}"
            for e in (evidence.get("runtime_errors") or [])
        ) or "- 无",
        "### 测试失败（L4 行为层，Tester 产物）",
        "\n".join(
            f"- {f.get('file', '?')}: {f.get('message', '')}"
            for f in (evidence.get("test_failures") or [])
        ) or "- 无",
        "### 埋点缺失",
        "\n".join(
            f"- {v.get('file', '?')}:{v.get('line', '?')} <{v.get('tag', '?')}> 缺 data-testid"
            for v in (evidence.get("hook_violations") or [])
        ) or "- 无",
    ]

    dag = state.get("planner_dag") or {}
    failed_or_related = [
        t for t in dag.get("tasks", [])
        if t.get("status") == "failed" or (t.get("contract") or {})
    ][:3]
    if failed_or_related:
        parts.append("## 失败/带契约任务")
        for t in failed_or_related:
            parts.append(
                f"- {t.get('id', '?')}（{t.get('description', '')}）"
                f" 契约: {t.get('contract', {})}"
            )

    files = state.get("generated_files") or {}
    evidence_files: list[str] = []
    for e in (evidence.get("compile_errors") or []):
        if e.get("file"):
            evidence_files.append(e["file"])
    for v in (evidence.get("contract_violations") or []):
        if v.get("file"):
            evidence_files.append(v["file"])
    for v in (evidence.get("hook_violations") or []):
        if v.get("file"):
            evidence_files.append(v["file"])
    relevant = []
    for f in dict.fromkeys(evidence_files):
        content = files.get(f)
        if content is not None:
            relevant.append(f"### {f}\n{content[:2000]}")
    if relevant:
        parts.append("## 相关文件内容")
        parts.extend(relevant)

    # 9.5: 历史修复策略检索 — 长期记忆 (fix_strategies) 供诊断参考。
    try:
        from .recovery import history_strategies_block

        strategies = history_strategies_block(state)
        if strategies:
            parts.append(strategies)
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("debugger_history_strategies_failed", error=str(e))

    # I4: 恢复阶梯「拆分」策略 — 上一轮重派未通过 (split) → 本次定向修复携带
    # 缩小范围的指令 (与 gate 的重派反馈互为补充)。
    try:
        from .recovery import split_instruction_block

        split_block = split_instruction_block(state)
        if split_block:
            parts.append(split_block)
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("debugger_split_instruction_failed", error=str(e))

    return "\n\n".join(parts)


async def diagnose(
    state: dict,
    evidence: dict,
    llm_fn=None,
) -> dict:
    """LLM 根因诊断 — 输出 {root_cause, fix_instructions, affected_files}.

    ``llm_fn`` threads the provider seam (brainstorm's pattern; None falls
    back to the graph singleton). Fail-safe: unparsable/LLM error → empty
    defaults, the fix round then falls back to re-running failed tasks.
    """
    from .brainstorm import _llm_structured

    try:
        return await _llm_structured(
            DEBUGGER_PROMPT,
            build_diagnosis_prompt(state, evidence),
            DEBUGGER_SCHEMA,
            llm_fn,
        )
    except Exception as e:
        logger.warning("debugger_diagnose_failed", error=str(e))
        return dict(DEBUGGER_SCHEMA)


def apply_fix_round(state: dict, diagnosis: dict) -> list[str]:
    """把诊断映射回任务 DAG：affected_files → 拥有该文件的任务置为 pending。

    Returns the affected task ids. 兜底链（文档化）:
    1. diagnosis.affected_files 命中任务 files → 只重派这些任务;
    2. 空/无命中 → 重派所有 failed 任务;
    3. 仍无 → 重派全部任务（最终兜底, 保证修复轮有实际动作）。
    """
    dag = state.get("planner_dag") or {}
    tasks = dag.get("tasks", [])
    affected_files = {
        f for f in (diagnosis.get("affected_files") or []) if isinstance(f, str)
    }

    matched = []
    for t in tasks:
        owns = set(t.get("files") or []) & affected_files
        if owns:
            matched.append(t)
    if not matched:
        matched = [t for t in tasks if t.get("status") == "failed"]
    if not matched:
        matched = list(tasks)

    fix_instructions = diagnosis.get("fix_instructions") or ""
    root_cause = diagnosis.get("root_cause") or ""
    affected_ids: list[str] = []
    for t in matched:
        # Review fix (Important): 修复指令只挂到证据点名的文件所属任务 ——
        # 兜底重派（failed/全部任务）不是证据所有者，不复制诊断内容，
        # 避免无关任务被错误指令驱动。
        owns_evidence = bool(set(t.get("files") or []) & affected_files)
        t["status"] = "pending"
        t["compile_errors"] = None
        t["acceptance"] = None
        if owns_evidence and fix_instructions:
            t["fix_instructions"] = fix_instructions
        if owns_evidence and root_cause:
            t["root_cause"] = root_cause
        affected_ids.append(t["id"])
    logger.info(
        "debugger_apply_fix_round",
        affected=affected_ids,
        affected_files=sorted(affected_files),
    )
    return affected_ids
