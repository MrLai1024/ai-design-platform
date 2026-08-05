"""Problem recovery (task group 9) — 失败分类 / 恢复阶梯 / 自主闭环红线 / 历史复用.

D10 决策落实:

- **9.1 失败分类** ``classify_failure`` — 六类: ``llm_error`` / ``format_invalid`` /
  ``compile`` / ``drift`` / ``contradiction`` / ``no_convergence``。
  **确定性优先** (证据决定性时零 LLM): 编译错误 → compile; JSON/解析/契约校验
  失败 → format_invalid; LLM 异常 → llm_error; Verifier 无进展 (证据签名在
  debugger_rounds 重复) → no_convergence; L2 契约违约 → contradiction。
  仅证据不充分时 (设计 L2 缺失清单 / E2E 真实回归 / L3·埋点钩子) 走 LLM
  (``_llm_structured`` seam), fail-safe 回退证据启发式 (confidence "low")。
  结果记录进 ``state.recovery_events``。

- **9.2 恢复阶梯** ``choose_strategy`` — 重派(带反馈) → 拆分(并行子任务) →
  回退(更早节点) → 上报(转人工)。阶梯第一级即既有 redo 路径: 决策被形式化,
  分类理由作为反馈进入下一轮生成 (verdict reason → design_gate_feedback)。

- **9.3 红线** — 每问题自主尝试 ≤ ``MAX_AUTONOMOUS_ATTEMPTS`` (2) 轮
  (``problem_attempts``, 以证据签名为键 — 同签名跨重派轮次计数, 即 9.4 的
  "跨阶梯无改进检测"); 超限强制求援。诊断建议范围变更 → 必须 confirm_card
  (``pending_scope_change``), 用户确认 (resume) 后才进入下一轮反馈
  (``scope_change_approved``)。

- **9.5 持久化 + 复用** — 每次分类写 problems.jsonl + memory_db
  (problem_records / failure_patterns / fix_strategies), fail-open;
  ``retrieve_fix_strategies`` 检索历史策略 (分类时 → suggested_fix,
  Debugger 诊断 prompt → 历史策略块); gate 通过时未决恢复事件闭环
  (``resolve_recovery_outcomes``: 最新 → resolved, 其余 → stale, 成功计数)。
"""

from __future__ import annotations

import hashlib
import json
import time

import structlog

from .verifier import evidence_signature  # noqa: F401  (re-exported for callers)

logger = structlog.get_logger()

# ── 9.1 分类词表 ──
CATEGORIES = (
    "llm_error",
    "format_invalid",
    "compile",
    "drift",
    "contradiction",
    "no_convergence",
)

CATEGORY_LABELS = {
    "llm_error": "LLM 调用错误",
    "format_invalid": "输出格式非法",
    "compile": "编译失败",
    "drift": "内容跑偏",
    "contradiction": "前后矛盾",
    "no_convergence": "多次无收敛",
}

# ── 9.2 恢复阶梯 ──
STRATEGY_LABELS = {
    "redispatch": "重派（带反馈）",
    "split": "拆分（并行子任务）",
    "rollback": "回退（更早节点）",
    "escalate": "上报（转人工）",
}

# ── 9.3 红线 ──
# 每问题自主闭环 ≤ 2 轮; 第 3 次出现同一证据签名 → 强制求援。
MAX_AUTONOMOUS_ATTEMPTS = 2

# 求援 / 范围确认卡选项 (frontend 已支持)。
RESCUE_OPTIONS = ("继续自主", "转人工")
SCOPE_OPTIONS = ("确认", "重新生成")

# 范围确认卡「重新生成/取消」的反馈文本标记 — resume 携带该反馈 (gateway
# code_feedback 元数据注入) 时视为拒绝范围变更, 不得批准。
REJECT_SCOPE_MARKERS = ("重新生成", "取消", "重来", "不要")

# ── LLM 分类 seam (9.1) ──
CLASSIFY_SCHEMA: dict = {
    "category": "",
    "reason": "",
    "scope_change": {"required": False, "note": ""},
}

CLASSIFY_PROMPT = """你是 AI 生成流水线中 Manager 的失败分类器。请根据节点产物、失败证据与需求内容判断失败类别。

可选类别（只能输出一个）：
- drift 内容跑偏：产物与用户需求存在整体性偏离（如设计遗漏需求功能点、实现与需求行为不符）
- contradiction 前后矛盾：产物与自身或与上游约束矛盾（如组件契约不一致、与已确认决策冲突）
- compile 编译失败
- format_invalid 输出格式非法
- no_convergence 多次无收敛（反复尝试无进展）
- llm_error LLM 调用错误

## 判断规则
- 设计↔PRD 缺口/偏离 → drift；产物与已确认决策冲突 → contradiction
- 代码与需求行为不符（E2E 真实回归）→ 偏离为 drift，矛盾为 contradiction
- 只输出一个 JSON 对象，不要其他内容：
{"category": "drift", "reason": "一句话根因描述", "scope_change": {"required": false, "note": "如修复必须删减功能范围则 required=true 并说明删减内容"}}
- scope_change：只有修复必然要求修改需求范围时才置 required=true，否则 false"""

# 确定性启发式标记 — 输出契约校验失败的提示词 (M1: 覆盖为空/empty/缺少 —
# "PRD 为空" / "PRD 缺少关键章节" 不花 LLM 调用, 直接判格式非法)。
_FORMAT_MARKERS = (
    "解析失败", "无法解析", "JSON 解析", "字段 ", "字段缺失",
    "Design missing", "missing sections", "为空", "empty", "缺少",
)


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── 证据收集 / 签名 ──


def _gather_evidence(state: dict, node: str, missing: list | None = None, reason: str = "") -> dict:
    """From state, build the structured evidence dict for the node being judged.

    code → verifier evidence (compile/contract/runtime/test/hook); e2e →
    diagnosis + failed results; design/analysis → reason + missing list.
    """
    if node == "code":
        evidence = (state.get("verifier_result") or {}).get("evidence") or {}
        # 兼容 phase-3 legacy 来源: verifier 未跑时 state.compile_errors 兜底。
        if not evidence.get("compile_errors") and state.get("compile_errors"):
            evidence = {**evidence, "compile_errors": list(state["compile_errors"])}
        return evidence
    if node == "e2e":
        diag = state.get("e2e_diagnosis") or {}
        failed = [
            r for r in (state.get("e2e_results") or [])
            if not r.get("passed", False) and r.get("status") != "skipped_requires_browser"
        ]
        return {
            "diagnosis": diag,
            "failed": failed,
            "rollback_case_ids": diag.get("rollback_case_ids") or [],
        }
    return {"reason": reason, "missing": missing or []}


def _evidence_signature(state: dict, node: str, evidence: dict, reason: str) -> str:
    """Per-problem attempt key: the verifier evidence signature when available
    (the debugger's no-progress key), else a deterministic hash of node+reason."""
    if isinstance(evidence, dict) and evidence:
        return evidence_signature(evidence)
    raw = json.dumps(
        {"node": node, "reason": reason, "missing": evidence.get("missing") if isinstance(evidence, dict) else None},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def evidence_refs(evidence: dict, reason: str = "") -> list[str]:
    """证据 → 人类可读摘要的唯一映射 (M4): 诊断卡 evidence_refs 与 problems.jsonl
    problem 文本共用, 不再维护第二份映射 (graph._evidence_summary 委托于此)."""
    refs: list[str] = []
    if isinstance(evidence, dict):
        for key, label in (
            ("compile_errors", "编译错误"),
            ("contract_violations", "契约违约"),
            ("runtime_errors", "运行时错误"),
            ("test_failures", "测试失败"),
            ("hook_violations", "埋点缺失"),
        ):
            items = evidence.get(key) or []
            if items:
                refs.append(f"{label} {len(items)} 处")
        if evidence.get("rollback_case_ids"):
            refs.append(f"E2E 真实回归 {len(evidence['rollback_case_ids'])} 例")
        if evidence.get("missing"):
            refs.append(f"需求↔设计缺口 {len(evidence['missing'])} 项")
    if reason and not refs:
        refs.append(reason)
    return refs or ["证据为空"]


# ── 9.1 确定性分类 (zero-LLM) ──


def _format_invalid_reason(reason: str) -> bool:
    return any(m in (reason or "") for m in _FORMAT_MARKERS)


def _deterministic_classify(
    state: dict,
    node: str,
    decision: str,
    reason: str,
    evidence: dict,
    signature: str,
    hint: str | None,
) -> tuple[str, str, str] | None:
    """Deterministic-first classification; None → ambiguous, go to LLM."""
    if hint == "llm_error":
        return "llm_error", "high", "LLM 调用异常（重试后仍失败）"
    if hint == "loop_control_blocked":
        return "no_convergence", "high", "回退循环控制熔断：继续自主无法收敛"
    if hint == "debugger_no_progress":
        return "no_convergence", "high", "Debugger 证据链无进展（同一证据签名重复出现）"

    if node == "code":
        # 同一证据签名已在修复轮中出现 → 无收敛 (5.5 无进展检测的升级语义)。
        # 优先于类别细分 — 修复没在推进比"这次是什么错"更关键。
        if any(r.get("signature") == signature for r in (state.get("debugger_rounds") or [])):
            return "no_convergence", "high", "证据链无进展：同一证据签名重复出现"
        if evidence.get("compile_errors"):
            return "compile", "high", f"编译失败：{len(evidence['compile_errors'])} 处错误"
        if evidence.get("contract_violations"):
            return "contradiction", "high", f"接口契约违约：{len(evidence['contract_violations'])} 处"
        if not evidence:
            # 无 Verifier 证据 → L1 结构性失败 (空输出 / 缺 template / 契约
            # 字段缺失) — 输出契约校验失败, 确定性分类, 无需 LLM。
            if "empty" in (reason or "").lower() or "template" in (reason or "").lower() or "缺失" in (reason or ""):
                return "format_invalid", "high", reason or "代码未通过契约校验"
        return None  # 仅 L3 运行时 / 埋点钩子 → LLM 判断

    if node == "design":
        if evidence.get("missing"):
            return None  # L2 缺失清单 → LLM 判断 drift / contradiction
        if _format_invalid_reason(reason):
            return "format_invalid", "high", reason or "Spec 未通过契约校验"
        return None

    if node == "analysis":
        if not (reason or "").strip() or _format_invalid_reason(reason):
            return "format_invalid", "high", reason or "PRD 未通过契约校验"
        return None

    if node == "e2e":
        return None  # 真实回归 → LLM 判断 drift / contradiction

    return None


# ── 9.1 LLM 分类 + fail-safe 启发式 ──


def _heuristic_category(node: str, evidence: dict) -> str:
    """Fail-safe: LLM 分类不可用时的证据启发式 (confidence "low")."""
    if node == "code":
        if evidence.get("compile_errors"):
            return "compile"
        if evidence.get("contract_violations"):
            return "contradiction"
        if any(k for k in ("runtime_errors", "hook_violations", "test_failures") if evidence.get(k)):
            return "drift"
        return "no_convergence"
    if node == "design":
        return "drift" if evidence.get("missing") else "format_invalid"
    if node == "e2e":
        return "drift"
    return "format_invalid"


async def _llm_classify(
    state: dict,
    node: str,
    reason: str,
    evidence: dict,
    llm_fn,
) -> tuple[str, str, str, bool, str]:
    """LLM judgment for ambiguous cases (drift vs contradiction etc.), with the
    scope-change proposal (9.3 red line: never self-approved, only surfaced).

    Fail-safe: any LLM/parse error → evidence heuristics, confidence "low".
    """
    from .brainstorm import _llm_structured

    user_parts = [
        f"当前节点：{node}",
        f"失败证据：\n{json.dumps(evidence, ensure_ascii=False, default=str)[:3000]}",
    ]
    if reason:
        user_parts.append(f"把关理由：{reason}")
    try:
        raw = await _llm_structured(CLASSIFY_PROMPT, "\n\n".join(user_parts), CLASSIFY_SCHEMA, llm_fn)
    except Exception as e:
        logger.warning("recovery_classify_llm_failed", node=node, error=str(e))
        raw = {}

    category = str(raw.get("category", "")).strip()
    if category not in CATEGORIES:
        category = _heuristic_category(node, evidence)
        confidence = "low"
        cls_reason = str(raw.get("reason", "")).strip() or (
            f"LLM 分类不可用，按证据启发式判定为「{CATEGORY_LABELS[category]}」"
        )
    else:
        confidence = "medium"
        cls_reason = str(raw.get("reason", "")).strip() or CATEGORY_LABELS[category]

    scope = raw.get("scope_change") or {}
    scope_change = bool(scope.get("required")) if isinstance(scope, dict) else False
    scope_note = str(scope.get("note", "")).strip() if isinstance(scope, dict) else ""
    return category, confidence, cls_reason, scope_change, scope_note


# ── 9.5 历史策略检索 ──


def retrieve_fix_strategies(state: dict, category: str | None = None, limit: int = 3) -> list[dict]:
    """Long-term memory retrieval: fix_strategies rows, optionally filtered by
    the failure category, best (success_count desc) first. Fail-open → []."""
    try:
        from .memory_db import get_memory_db

        rows = get_memory_db().get_fix_strategies() or []
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("recovery_strategies_retrieve_failed", error=str(e))
        return []
    if category:
        rows = [r for r in rows if r.get("problem_category") == category]
    return rows[:limit]


def _suggested_fix(state: dict, category: str) -> str:
    """Best historical strategy for the category (9.5 reuse), or ""."""
    rows = retrieve_fix_strategies(state, category=category, limit=1)
    if not rows:
        return ""
    r = rows[0]
    return f"{r.get('strategy', '')}（历史成功 {r.get('success_count', 0)} 次）"


def history_strategies_block(state: dict, limit: int = 5) -> str:
    """Prompt block of historical fix strategies (long-term memory) for the
    Debugger's diagnosis prompt (9.5). Empty when no history exists."""
    rows = retrieve_fix_strategies(state, category=None, limit=limit)
    if not rows:
        return ""
    lines = ["## 历史修复策略（长期记忆，优先参考同类策略）"]
    for r in rows:
        lines.append(
            f"- [{r.get('problem_category', '?')}] {r.get('strategy', '')}"
            f"（尝试 {r.get('attempt_count', 0)} 次，成功 {r.get('success_count', 0)} 次）"
        )
    return "\n".join(lines)


def split_instruction_block(state: dict) -> str:
    """I4: 恢复阶梯「拆分」策略的指令块 — 最近一次代码阶段恢复决策为 split 时,
    Debugger 诊断 prompt 携带"缩小修复范围"的指令 (重派反馈已含分类理由;
    这里是给下一轮定向修复的独立消费点)。非 split → 空串。"""
    last = state.get("recovery_last") or {}
    if last.get("node") != "code" or (last.get("strategy") or {}).get("strategy") != "split":
        return ""
    reason = last.get("reason") or ""
    return (
        "## 恢复策略：拆分修复范围（并行子任务）\n"
        "上一轮重派未通过，Manager 判定问题集中在具体文件。本次诊断必须：\n"
        "- affected_files 只列证据点名的必须修改文件（范围最小化）\n"
        "- 修复指令按文件拆分，每步可独立验证\n"
        + (f"- 背景：{reason}\n" if reason else "")
    ).rstrip()


def rejects_scope_change(feedback: str) -> bool:
    """I5: 范围确认卡「重新生成/取消」判定 — 精确匹配选项文本 (或以其开头),
    不再用子串匹配 (避免普通反馈文本含"不要"被误判为拒绝)。"""
    text = (feedback or "").strip().strip("。！!？?，,、 \t")
    if not text:
        return False
    return text in REJECT_SCOPE_MARKERS or text.startswith("重新生成")


# ── 9.1 分类主入口 ──


async def classify_failure(
    state: dict,
    *,
    node: str,
    decision: str = "redo",
    reason: str = "",
    evidence: dict | None = None,
    missing: list | None = None,
    llm_fn=None,
    hint: str | None = None,
) -> dict:
    """9.1 失败分类 — deterministic-first, LLM only for ambiguous evidence.

    ``hint`` — deterministic override from call sites that already know the
    failure class (``llm_error`` / ``loop_control_blocked`` /
    ``debugger_no_progress``); None → classification proceeds on evidence.

    Returns ``{node, category, confidence, reason, evidence_refs, signature,
    output_signature, scope_change, scope_change_note, suggested_fix}``.
    """
    if evidence is None:
        evidence = _gather_evidence(state, node, missing, reason)
    signature = _evidence_signature(state, node, evidence, reason)

    deterministic = _deterministic_classify(state, node, decision, reason, evidence, signature, hint)
    if deterministic is not None:
        category, confidence, cls_reason = deterministic
        scope_change, scope_note = False, ""
    else:
        category, confidence, cls_reason, scope_change, scope_note = await _llm_classify(
            state, node, reason, evidence, llm_fn
        )

    from .manager import _output_signature

    return {
        "node": node,
        "category": category,
        "confidence": confidence,
        "reason": cls_reason,
        "evidence_refs": evidence_refs(evidence, reason),
        "signature": signature,
        "output_signature": _output_signature(state, node),
        "scope_change": scope_change,
        "scope_change_note": scope_note,
        "suggested_fix": _suggested_fix(state, category),
    }


# ── 9.3 红线: 每问题自主尝试计数 ──


def bump_problem_attempts(state: dict, signature: str) -> int:
    """Record one autonomous attempt for the problem (keyed by evidence
    signature). Returns the new count."""
    attempts = dict(state.get("problem_attempts") or {})
    attempts[signature] = attempts.get(signature, 0) + 1
    state["problem_attempts"] = attempts
    return attempts[signature]


def red_line_hit(state: dict, signature: str) -> bool:
    """9.3: 该问题自主处理已超 2 轮 → 必须强制求援 (同一签名跨重派轮次计数,
    即跨阶梯无改进检测 — 9.4)。"""
    return (state.get("problem_attempts") or {}).get(signature, 0) > MAX_AUTONOMOUS_ATTEMPTS


def reset_problem_attempts(state: dict, signature: str | None = None) -> None:
    """「继续自主」后的计数重置 (9.3): 清除该签名 (或全部) 的自主尝试计数。"""
    attempts = dict(state.get("problem_attempts") or {})
    if signature is None:
        attempts.clear()
    else:
        attempts.pop(signature, None)
    state["problem_attempts"] = attempts


def consume_escalation_reset(state: dict) -> bool:
    """9.3 求援 → 「继续自主」: 清除熔断标记并重置该问题自主尝试计数。

    Called at the run/resume entry — the user's resume after a rescue card
    authorizes further autonomous rounds with a fresh counter. The reset
    covers BOTH red-line counters: per-problem attempts (9.3) AND the
    LoopControl rollback counters (9.4) — those limits bound *autonomous*
    rounds; an explicit 继续自主 re-authorizes them. The last verdict's
    escalate flag is cleared so the gate's verdict-reuse path does not
    re-escalate the same output into a dead loop.
    """
    sig = state.get("escalated_signature")
    if not sig:
        return False
    reset_problem_attempts(state, sig)
    state.pop("escalated_signature", None)
    state["rollback_count"] = {}
    state["rollback_records"] = []
    verdicts = state.get("manager_verdicts") or []
    if verdicts and isinstance(verdicts[-1], dict):
        rec = verdicts[-1].get("recovery")
        if isinstance(rec, dict):
            rec["escalate"] = False
    logger.info("recovery_continue_autonomous", signature=sig)
    return True


def consume_scope_confirmation(state: dict) -> bool:
    """9.3 范围变更红线: 用户 resume (确认卡后继续) → 范围变更获批。

    The approved note lands in ``scope_change_approved`` and is consumed by
    ``manager.design_gate_feedback`` into the re-run prompt. Without an
    explicit resume the pending proposal never self-applies.
    """
    pending = state.get("pending_scope_change")
    if not pending or state.get("scope_change_approved"):
        return False
    state["scope_change_approved"] = str(pending.get("note", "")).strip() or True
    state.pop("pending_scope_change", None)
    logger.info("recovery_scope_change_approved", note=pending.get("note", ""))
    return True


# ── 9.2 恢复阶梯决策 ──


def choose_strategy(
    state: dict,
    classification: dict,
    *,
    attempts: int,
    red_line: bool,
) -> dict:
    """9.2 恢复阶梯 — 重派(带反馈) → 拆分(并行子任务) → 回退(更早节点) → 上报。

    - redispatch: 同一问题第 1 轮 (既有 redo 路径, 分类理由作为反馈);
    - split: 第 2 轮且问题集中在具体文件 (compile / contradiction) → 拆分修复;
    - rollback: drift/contradiction 指向更早节点 → 回退该节点重生成;
    - escalate: 红线 (第 3 轮) 或 no_convergence → 上报求援。

    Returns ``{strategy, target, reason}``.
    """
    category = classification["category"]
    node = classification["node"]

    if red_line or category == "no_convergence":
        reason = (
            "自主闭环超 2 轮红线，必须向用户汇报"
            if red_line else "多次无收敛：继续自主无法闭环，转人工"
        )
        return {"strategy": "escalate", "target": None, "reason": reason}

    if category in ("llm_error", "format_invalid"):
        return {"strategy": "redispatch", "target": node,
                "reason": "重派同一 worker（携带失败反馈）"}

    if category in ("compile", "contradiction"):
        if attempts >= 2:
            # 拆分: 重派已失败一轮, 问题集中在具体文件 → 缩小修复范围
            # (planner 重规划 / debugger 定向修复轮)。
            return {"strategy": "split", "target": node,
                    "reason": "重派一轮未通过，问题集中在具体文件 → 拆分修复范围（并行子任务）"}
        return {"strategy": "redispatch", "target": node,
                "reason": "重派同一 worker（携带编译/契约证据反馈）"}

    if category == "drift":
        earlier = {"design": "design", "code": "design", "e2e": "code", "analysis": "analysis"}.get(node, "design")
        if node == "e2e":
            return {"strategy": "rollback", "target": "code",
                    "reason": "E2E 真实回归 → 回退功能实现节点重新生成（携带失败证据）"}
        if attempts >= 2:
            return {"strategy": "rollback", "target": earlier,
                    "reason": "内容偏离指向更早节点 → 回退重新生成（携带失败证据）"}
        return {"strategy": "redispatch", "target": node,
                "reason": "重派同一 worker（携带偏离反馈）"}

    return {"strategy": "redispatch", "target": node, "reason": "重派同一 worker"}


def _recovery_signature(recovery: dict | None) -> str | None:
    """Signature from a run_recovery result or a stored verdict recovery dict."""
    if not isinstance(recovery, dict):
        return None
    if recovery.get("signature"):
        return recovery["signature"]
    cls = recovery.get("classification") or {}
    return cls.get("signature") or None


def gate_loop_check(
    state: dict,
    worker: str,
    recovery: dict | None,
    target: str | None = "code",
) -> tuple[bool, dict]:
    """9.4 把关 redo/rollback 路由必须过 LoopControl (每节点 ≤3 / 总数 ≤10 /
    无改进熔断) — 之前的 gate redo 路径绕过了它。红线 (9.3) 或熔断 → 转求援。

    Returns ``(escalated, state)``; escalated=True 时调用方不得再自主派发
    worker — 停在中断处, runner 以 ``escalated_signature`` 发射求援卡。
    ``target=None`` → 跳过 LoopControl (该阶段无重跑动作, 不计数)。
    """
    from .harness import LoopControl

    if recovery and recovery.get("escalate"):
        state["needs_manual_review"] = True
        sig = _recovery_signature(recovery)
        if sig and not state.get("escalated_signature"):
            state["escalated_signature"] = sig
        return True, state

    if target is None:
        return False, state

    loop = LoopControl()
    allowed, lc_reason = loop.should_rollback(target, state)
    if not allowed:
        state["needs_manual_review"] = True
        sig = _recovery_signature(recovery)
        if sig:
            state["escalated_signature"] = sig
        # 同步 recovery_last 与当前裁决的 recovery dict — 卡面发射/消费方
        # (I2: _manager_verdict_events 读 verdict.recovery.escalate) 看到
        # escalate 状态, 不再出现"裁决卡是普通诊断卡、求援卡另行发射"的两张卡。
        if isinstance(state.get("recovery_last"), dict) and not state["recovery_last"].get("escalate"):
            state["recovery_last"]["escalate"] = True
        verdicts = state.get("manager_verdicts") or []
        if verdicts and isinstance(verdicts[-1], dict):
            rec = verdicts[-1].get("recovery")
            if isinstance(rec, dict):
                rec["escalate"] = True
        logger.warning(
            "recovery_loop_control_blocked",
            worker=worker, target=target, reason=lc_reason,
        )
        return True, state

    if recovery is not None:
        # In-place equivalent of LoopControl.apply_rollback (the gate mutates
        # state in place; a returned copy would be discarded by callers).
        record = loop.record_rollback(
            from_node=worker,
            to_node=target,
            reason=recovery.get("classification", {}).get("reason", "") or "把关未通过回退",
            previous_output_hash=_recovery_signature(recovery) or "",
            token_cost=0,
        )
        counts = dict(state.get("rollback_count") or {})
        counts[target] = counts.get(target, 0) + 1
        records = list(state.get("rollback_records") or [])
        records.append(record)
        state["rollback_count"] = counts
        state["rollback_records"] = records
    return False, state


def build_recovery_feedback(classification: dict, strategy: dict) -> str:
    """重派/拆分/回退的反馈文本 — 随 verdict reason 进入下一轮生成
    (design_gate_feedback / 重派 prompt 消费), 含分类理由与历史策略参考。"""
    target = strategy.get("target")
    target_label = target or "人工"
    parts = [
        f"[恢复策略：{STRATEGY_LABELS.get(strategy['strategy'], strategy['strategy'])}"
        f" → {target_label}] 失败分类：{CATEGORY_LABELS.get(classification['category'], classification['category'])}"
        f"（置信 {classification['confidence']}）\n{classification['reason']}"
    ]
    if classification.get("suggested_fix"):
        parts.append(f"历史修复策略参考：{classification['suggested_fix']}")
    return "\n".join(parts)


# ── 恢复事件 / 持久化 ──


def record_recovery_event(
    state: dict,
    node: str,
    classification: dict,
    strategy: dict,
    attempts: int,
    result: str = "pending",
) -> None:
    """追加一条恢复事件 (9.1/9.2 留痕, 消费方: resolve_recovery_outcomes)."""
    events = list(state.get("recovery_events") or [])
    events.append({
        "ts": _ts(),
        "node": node,
        "category": classification["category"],
        "confidence": classification["confidence"],
        "reason": classification["reason"],
        "signature": classification["signature"],
        "output_signature": classification["output_signature"],
        "strategy": strategy["strategy"],
        "target": strategy.get("target"),
        "attempts": attempts,
        "result": result,
    })
    state["recovery_events"] = events


def _strategy_label(strategy: dict) -> str:
    label = STRATEGY_LABELS.get(strategy["strategy"], strategy["strategy"])
    if strategy.get("target"):
        label += f" → {strategy['target']}"
    return label


def _record_problem_io(
    state: dict,
    *,
    category: str,
    problem: str,
    root_cause: str = "",
    fix: str = "",
    result: str = "",
) -> None:
    """9.5 恢复链路的统一问题落库: problems.jsonl + run_context + memory_db
    problem_records — 不写 failure_patterns / fix_strategies (调用方按需自写),
    避免重复行 (I6: 一次失败只落一条稳定键的失败模式)。fail-open。"""
    try:
        from .memory import append_problem, project_root_for, update_run_context

        append_problem(
            project_root_for(state),
            category=category, problem=problem, root_cause=root_cause,
            fix=fix, result=result,
        )
        update_run_context(state, latest_problem={
            "category": category, "problem": (problem or "")[:200], "result": result,
        })
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("recovery_problem_append_failed", error=str(e))
    try:
        from .memory_db import get_memory_db

        get_memory_db().append_problem(
            state.get("generation_id") or "unknown",
            category, problem, root_cause, fix, result,
        )
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("recovery_problem_db_failed", error=str(e))


def _persist_recovery(state: dict, classification: dict, strategy: dict, result: str) -> None:
    """9.5 持久化: problems.jsonl + memory_db problem_records / failure_patterns /
    fix_strategies 尝试计数 (全部 fail-open, 绝不阻断流水线).

    I6: failure_patterns 只写一次, 键 = 类别 + 证据签名前缀 (每问题稳定,
    同问题重复失败在同一行累积计数) — 不再经 memory.record_problem 造成第二行
    近唯一键的重复模式。
    """
    fix = _strategy_label(strategy)
    problem = f"{classification['node']} 失败：{classification['reason']}"
    _record_problem_io(
        state, category=classification["category"], problem=problem,
        root_cause=classification["reason"], fix=fix, result=result,
    )
    try:
        from .memory_db import get_memory_db

        db = get_memory_db()
        db.record_failure_pattern(
            state.get("user_id") or "default",
            f"{classification['category']}:{classification['signature'][:8]}",
            description=classification["reason"],
            fix_strategy=fix,
        )
        db.record_fix_strategy_success(classification["category"], fix)
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("recovery_pattern_record_failed", error=str(e))


def resolve_recovery_outcomes(state: dict, node: str) -> None:
    """9.5 闭环: gate pass → 该节点未决恢复事件收口 — 最新一条 → resolved
    (策略成功), 其余 → stale (被后续重跑取代)。resolved 记 problems.jsonl
    结果并给 fix_strategies 成功计数 (fail-open)。"""
    events = list(state.get("recovery_events") or [])
    pending = [
        i for i, ev in enumerate(events)
        if ev.get("node") == node and ev.get("result") == "pending"
    ]
    if not pending:
        return
    resolved_idx = pending[-1]
    resolved = None
    for i in pending:
        events[i] = dict(events[i])
        events[i]["result"] = "resolved" if i == resolved_idx else "stale"
        if i == resolved_idx:
            resolved = events[i]
    state["recovery_events"] = events

    if resolved is None:
        return
    # 与分类时 _persist_recovery 的 fix 键一致 (label → target), 成功计数
    # 才能落到同一 fix_strategies 行。
    fix = _strategy_label({"strategy": resolved.get("strategy", ""), "target": resolved.get("target")})
    _record_problem_io(
        state, category=resolved["category"],
        problem=f"{node} 恢复闭环：{resolved['reason']}",
        root_cause=resolved["reason"], fix=fix, result="resolved",
    )
    try:
        from .memory_db import get_memory_db

        get_memory_db().record_fix_strategy_result(resolved["category"], fix, success=True)
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("recovery_strategy_success_failed", error=str(e))


# ── 9.1-9.3 one-shot 编排 (manager_gate / _gate_manual_stage 消费) ──


async def run_recovery(
    state: dict,
    *,
    node: str,
    decision: str = "redo",
    reason: str = "",
    evidence: dict | None = None,
    missing: list | None = None,
    llm_fn=None,
    hint: str | None = None,
) -> dict:
    """9.1-9.3/9.5 one-shot: 分类 → 尝试计数 → 阶梯决策 → 事件记录 → 持久化.

    Writes ``state.recovery_last`` (card emission), ``problem_attempts``,
    ``recovery_events`` and the problems/memory records (fail-open).
    Returns ``{"classification", "strategy", "escalate", "attempts"}``.
    """
    classification = await classify_failure(
        state, node=node, decision=decision, reason=reason,
        evidence=evidence, missing=missing, llm_fn=llm_fn, hint=hint,
    )
    attempts = bump_problem_attempts(state, classification["signature"])
    red_line = red_line_hit(state, classification["signature"])
    strategy = choose_strategy(state, classification, attempts=attempts, red_line=red_line)
    escalate = strategy["strategy"] == "escalate"
    result = "escalated" if escalate else "pending"
    record_recovery_event(state, node, classification, strategy, attempts, result=result)
    _persist_recovery(state, classification, strategy, result)

    state["recovery_last"] = {
        "node": node,
        "category": classification["category"],
        "confidence": classification["confidence"],
        "reason": classification["reason"],
        "strategy": strategy,
        "attempts": attempts,
        "escalate": escalate,
        "scope_change": bool(classification.get("scope_change")),
        "scope_change_note": classification.get("scope_change_note", ""),
        "suggested_fix": classification.get("suggested_fix", ""),
        "signature": classification["signature"],
    }
    logger.info(
        "recovery_decided",
        node=node, category=classification["category"],
        strategy=strategy["strategy"], attempts=attempts,
        escalate=escalate, confidence=classification["confidence"],
    )
    return {
        "classification": classification,
        "strategy": strategy,
        "escalate": escalate,
        "attempts": attempts,
    }
