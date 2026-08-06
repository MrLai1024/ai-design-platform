"""Manager (Coordinator Agent) gate — L1 deterministic + L2 LLM gating.

Manager-worker orchestration (D1/D3):

- ``manager_gate`` is a LangGraph node that runs after every worker node.
- It runs **L1 deterministic checks** (zero-LLM, reusing ``EvalHarness``)
  and — for the design stage — **L2 Manager LLM evaluation** (Spec↔PRD
  coverage, task group 4), writes a verdict into ``manager_verdicts``, and sets
  the routing decision in ``manager_next`` so the conditional edge can route to
  the next worker / rollback / END.
- Workers never pass artifacts directly to each other — everything flows back
  through the gate.

L2 is fail-closed: an unparsable or failed LLM output re-judges the stage as
"redo" with reason "L2 评估失败", so an unverifiable Spec never passes the gate.
The ``llm_fn`` seam (matching brainstorm's provider-threading pattern) lets
tests inject a fake; None falls back to the singleton ``_llm_generate`` path.
L3 (cross-node consistency) arrives in a later task group.
"""

import hashlib
import json
import time

import structlog

from .brainstorm import LLMFn, _llm_structured
from .harness import EvalHarness
from .state import GenerationState

logger = structlog.get_logger()

# Analysis acceptance keywords — mirrors the base dispatch_contract's
# acceptance_criteria ("PRD 非空且含功能模块与页面结构").
ANALYSIS_ACCEPTANCE_KEYWORDS = ("功能模块", "页面结构")

# Result field used as the output signature per worker (dedupe key).
WORKER_RESULT_FIELD = {
    "analysis": "analysis_result",
    "design": "design_result",
    "code": "code_result",
    "e2e": "e2e_results",
}

# ── L2 gate: Spec ↔ PRD coverage (4.4) ──

MANAGER_L2_SPEC_PROMPT = """你是 AI 生成流水线中的 Manager（把关人）。请核对架构 Spec 对 PRD 功能点的覆盖情况（L2 评估）。

## 输入
- PRD（需求规格文档）：功能模块 / 页面结构 / 交互行为
- 架构 Spec（JSON）：方案设计节点输出的机读架构描述
- （可能包含）澄清产物：结构化需求 / 决策日志 / 假设清单

## 核对规则
- 逐一检查 PRD 中每个已确认功能点（功能模块、页面），确认其在 Spec 的 pages 或 component_tree 中已落地
- 澄清产物的决策日志是 decisions 的依据；假设清单中的项（用户未确认）不必强制落地
- 只判断覆盖性，不评价方案优劣

## 输出格式（只输出一个 JSON 对象）
{"passed": true, "missing": [{"feature": "遗漏功能点名称", "evidence": "PRD 中何处声明、Spec 中缺少什么"}]}
- passed：PRD 全部功能点已在 Spec 落地则为 true，有遗漏为 false
- missing：遗漏清单；无遗漏时为空数组"""

# Structured-output schema for the L2 gate (parse-merge + type coercion).
L2_SPEC_SCHEMA: dict = {
    "passed": True,
    "missing": [{"feature": "", "evidence": ""}],
}

L2_EVAL_FAILED = "L2 评估失败"

# L4 行为层 deferral（5.6 review I1）的非失败说明 —— 挂在 pass 裁决的理由上，
# 对用户可见，但不影响裁决（l4_pending 不算失败，也不假装行为已验证）。
L4_PENDING_NOTE = "L4 行为未执行：测试执行环境不可用（deferral），行为层留待测试环境就绪后验证"


def run_l1_checks(state: GenerationState, stage: str) -> list[str]:
    """Deterministic L1 checks (no LLM involved).

    Returns a list of error strings; an empty list means the stage passed.
    """
    if stage == "analysis":
        prd = state.get("analysis_result") or ""
        errors = []
        if not prd.strip():
            errors.append("PRD 为空")
        for kw in ANALYSIS_ACCEPTANCE_KEYWORDS:
            if kw not in prd:
                errors.append(f"PRD 缺少关键章节：{kw}")
        return errors

    if stage == "design":
        # 4.3: L1 for design = MD sections + Spec field completeness (both
        # deterministic, zero-LLM). The Spec is the Manager's gating object.
        errors = list(EvalHarness.design_has_sections(state.get("design_result")).errors)
        errors += list(EvalHarness.spec_has_required_fields(state.get("architecture_spec")).errors)
        return errors

    if stage == "code":
        errors = list(EvalHarness.validate(state, "code").errors)
        compile_errors = state.get("compile_errors") or []
        if compile_errors:
            errors.append(f"编译未通过（{len(compile_errors)} 处错误）")
        # 5.4: Verifier 四层信号汇入 L1 —— 任一信号失败即把关失败，
        # 失败项随 evidence 进入 diagnosis card。
        # Review fix (Critical): 只在当前 code_result 与 Verifier 实际验证过
        # 的输出一致时消费 verdict。代码被重新生成（redo → code_node 整仓重写）
        # 后签名变化 → 跳过 stale verdict，用全新 L1 判定 —— 否则 verifier 失败
        # 会形成"重新生成 → 复用失败裁决 → 再 redo"的无限循环。
        verifier = state.get("verifier_result")
        if (
            verifier
            and not verifier.get("passed")
            and verifier.get("output_signature") == _output_signature(state, "code")
        ):
            layer_labels = (
                ("l1_ok", "L1 编译"),
                ("l2_ok", "L2 契约"),
                ("l3_ok", "L3 运行时"),
                ("l4_ok", "L4 行为"),
                ("hooks_ok", "埋点钩子"),
            )
            for key, label in layer_labels:
                if key == "l4_ok" and key not in verifier:
                    # 旧格式 verdict 无 L4（Tester 是 5.6 新增字段）→ 视为未知，
                    # 不阻止把关（与 test_verifier_without_signature_never_blocks_gate
                    # 的兼容哲学一致）。
                    continue
                if not verifier.get(key):
                    errors.append(f"{label}未通过（Verifier）")
        return errors

    if stage == "e2e":
        results = state.get("e2e_results") or []
        if not results:
            return []
        # 6.3/6.7: skipped_requires_browser cases are not failures; 6.4: when
        # the Test Diagnoser ran, ONLY real-regression cases
        # (rollback_case_ids) count as failures — expected_broken /
        # selector_coupled do NOT trigger the code rollback alone, including
        # when the diagnosis found ZERO real regressions (all-expected_broken
        # run). No diagnosis present → legacy semantics (every non-passed
        # case is a failure).
        diag = state.get("e2e_diagnosis")
        if diag:
            rollback_ids = set(diag.get("rollback_case_ids") or [])
            failed = [
                r for r in results
                if not r.get("passed", False)
                and r.get("status") != "skipped_requires_browser"
                and r.get("case_id") in rollback_ids
            ]
        else:
            failed = [
                r for r in results
                if not r.get("passed", False)
                and r.get("status") != "skipped_requires_browser"
            ]
        if failed:
            return [f"E2E 有 {len(failed)} 个用例未通过（真实回归）"]
        return []

    return []


def last_design_verdict(state: GenerationState) -> dict | None:
    """The most recent gate verdict for the design stage, or None."""
    verdicts = state.get("manager_verdicts") or []
    return next((v for v in reversed(verdicts) if v.get("node") == "design"), None)


def last_analysis_verdict(state: GenerationState) -> dict | None:
    """The most recent gate verdict for the analysis stage, or None."""
    verdicts = state.get("manager_verdicts") or []
    return next((v for v in reversed(verdicts) if v.get("node") == "analysis"), None)


def analysis_gate_feedback(state: GenerationState) -> str:
    """Redo feedback for the PRD re-run (I3 — mirror of design_gate_feedback).

    An analysis redo verdict clears ``analysis_result`` (graph phase 1), so the
    resume path re-generates the PRD; the failed gate's reason (L1 error list +
    恢复阶梯反馈, task group 9) is fed back into the regeneration prompt.
    Returns "" when the last analysis verdict passed or none exists.
    """
    verdict = last_analysis_verdict(state)
    if verdict and verdict.get("decision") in ("redo", "rollback"):
        return verdict.get("reason", "")
    return ""


def design_gate_feedback(state: GenerationState) -> str:
    """Redo feedback for the design re-run (review fix 1).

    A design redo verdict clears the dual product (graph phase 2), so the
    resume path re-generates the design; the failed gate's reason (L1 field
    list / L2 missing list + 恢复阶梯反馈, task group 9) is fed back into the
    regeneration prompt. Returns "" when the last design verdict passed or
    none exists.

    Task group 9 (9.3 red line): a scope change is appended ONLY after the
    user confirmed it (``scope_change_approved`` via the confirm_card
    resume) — an unconfirmed scope proposal never enters the re-run prompt.
    """
    verdict = last_design_verdict(state)
    feedback = ""
    if verdict and verdict.get("decision") in ("redo", "rollback"):
        feedback = verdict.get("reason", "")
    approved = state.get("scope_change_approved")
    if approved:
        note = approved if isinstance(approved, str) else ""
        if note:
            feedback += "\n\n## 用户已确认的范围变更（必须遵守）\n" + note
    return feedback


async def run_l2_checks(
    stage: str,
    state: GenerationState,
    llm_fn: LLMFn | None = None,
) -> dict:
    """L2 per-stage Manager LLM evaluation (D3 / 4.4).

    Only the design stage has an L2 gate in this group: the Manager compares
    the architecture Spec against the PRD's confirmed feature points and
    returns the missing list. Other stages pass L2 trivially (no L2 yet).

    Fail-closed: an LLM error or unparsable output yields
    ``{"passed": False, "missing": [], "reason": "L2 评估失败"}`` — the gate
    never lets an unverifiable Spec through, and L1-only evaluation never
    happens implicitly for design. The LLM call is retried once (max 2 calls)
    before failing closed — a transient flake must not force a full design
    regeneration through the redo path (review fix 3).

    Returns ``{"passed": bool, "missing": [{"feature", "evidence"}], "reason": str}``.
    """
    if stage != "design":
        return {"passed": True, "missing": [], "reason": ""}

    spec = state.get("architecture_spec")
    parts = [
        f"PRD（需求规格文档）：\n{state.get('analysis_result') or ''}",
        f"架构 Spec（JSON）：\n{json.dumps(spec, ensure_ascii=False, indent=2)}",
    ]
    requirements_state_json = state.get("requirements_state_json")
    if requirements_state_json:
        parts.append(f"澄清产物（结构化需求）：\n{requirements_state_json}")
    decisions = state.get("brainstorm_decisions") or []
    if decisions:
        parts.append("决策日志：\n" + json.dumps(decisions, ensure_ascii=False))
    assumptions = state.get("brainstorm_assumptions") or []
    if assumptions:
        parts.append("假设清单：\n" + json.dumps(assumptions, ensure_ascii=False))

    raw: dict | None = None
    last_error: Exception | None = None
    for attempt in range(2):  # one retry, then fail-closed
        try:
            raw = await _llm_structured(
                MANAGER_L2_SPEC_PROMPT,
                "\n\n".join(parts),
                L2_SPEC_SCHEMA,
                llm_fn,
            )
            break
        except Exception as e:
            last_error = e
            logger.warning("manager_l2_eval_retry", stage=stage, attempt=attempt + 1, error=str(e))
    if raw is None:
        logger.warning("manager_l2_eval_failed", stage=stage, error=str(last_error))
        return {"passed": False, "missing": [], "reason": L2_EVAL_FAILED}

    passed = bool(raw.get("passed", False))
    missing = raw.get("missing") or []
    if not isinstance(missing, list):
        missing = []
    if not passed and not missing:
        # LLM said "not passed" but gave no missing list → fail-closed.
        return {"passed": False, "missing": [], "reason": L2_EVAL_FAILED}
    logger.info(
        "manager_l2_verdict",
        stage=stage,
        passed=passed,
        missing_count=len(missing),
    )
    return {"passed": passed, "missing": missing, "reason": ""}


async def evaluate_stage_l2(
    state: GenerationState,
    stage: str,
    llm_fn: LLMFn | None = None,
) -> tuple[str, str, list[str], list[dict]]:
    """L1 + (design) L2 evaluation for a completed stage.

    Returns ``(decision, reason, evidence, missing)``:

    - ``evidence`` feeds the Manager's diagnosis card: the L1 error list on L1
      failure, the formatted L2 missing list on L2 failure.
    - ``missing`` is the raw L2 missing list ``[{feature, evidence}]`` (4.4),
      carried on the verdict/diagnosis card data for the frontend.

    Both lists are empty on pass.
    """
    errors = run_l1_checks(state, stage)
    if errors:
        if stage == "e2e":
            return "rollback", "；".join(errors), errors, []
        return "redo", "；".join(errors), errors, []

    if stage == "design":
        l2 = await run_l2_checks(stage, state, llm_fn)
        if not l2["passed"]:
            missing = l2.get("missing") or []
            if missing:
                reason = "L2：" + "；".join(
                    f"{m.get('feature', '?')}（{m.get('evidence', '')}）"
                    for m in missing
                )
                evidence = [
                    f"- {m.get('feature', '?')}: {m.get('evidence', '')}"
                    for m in missing
                ]
            else:
                reason = l2.get("reason") or L2_EVAL_FAILED
                evidence = [reason]
            return "redo", reason, evidence, missing

    if stage == "code":
        # 5.6 review I1: L1-L3 已过而 L4 处于 pending（测试执行不可行 / 零测试
        # 产物）—— 不算失败，但 deferral 必须对用户可见：pass 裁决的理由携带
        # 非失败说明（verdict_card 展示），前端 code_gen_done 事件另带 l4_pending。
        verifier = state.get("verifier_result")
        if verifier and verifier.get("l4_pending"):
            return "pass", L4_PENDING_NOTE, [], []

    return "pass", "", [], []


def _output_signature(state: GenerationState, node: str) -> str:
    """Short hash of the worker's result field — dedupe key for gate verdicts."""
    field = WORKER_RESULT_FIELD.get(node)
    raw = state.get(field) if field else None
    if node == "design":
        # The design worker's output is the dual product (MD + Spec, 4.2) — a
        # Spec change must invalidate a reused verdict.
        raw = {"doc": raw, "spec": state.get("architecture_spec")}
    if raw is None:
        raw = ""
    return hashlib.md5(
        json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:8]


def record_verdict(
    state: GenerationState,
    node: str,
    decision: str,
    reason: str,
) -> GenerationState:
    """Append a gate verdict to ``manager_verdicts`` (skeleton for problem records).

    Each verdict carries an ``signature`` of the worker's output so the gate can
    recognize a re-judged, unchanged output and dedupe.
    """
    verdicts = list(state.get("manager_verdicts") or [])
    verdicts.append({
        "node": node,
        "decision": decision,
        "reason": reason,
        "signature": _output_signature(state, node),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    state["manager_verdicts"] = verdicts
    return state


def infer_last_worker(state: GenerationState) -> str:
    """Infer which worker most recently produced output, from state alone.

    Used on first gate entry (before any routing decision exists); afterwards
    the gate prefers the worker it routed to last (``manager_next``).
    """
    if state.get("e2e_results") or state.get("e2e_passed"):
        return "e2e"
    if state.get("code_result") or state.get("generated_files"):
        return "code"
    if state.get("design_result"):
        return "design"
    if state.get("analysis_result"):
        return "analysis"
    # Nothing produced yet — first dispatch targets the code worker.
    return "code"


async def manager_gate(
    state: GenerationState,
    llm_fn: LLMFn | None = None,
) -> GenerationState:
    """Coordinator gate (LangGraph node) — L1 + L2 gating + verdict memory + routing.

    Runs after every worker node: L1 deterministic checks for every stage;
    for the design stage also L2 Manager LLM evaluation (Spec↔PRD coverage,
    4.4). ``llm_fn`` is the LLM seam (tests inject a fake; None falls back to
    the singleton ``_llm_generate`` path, matching brainstorm's pattern).

    The gate is idempotent per worker output: if the last verdict for the same
    worker carries the same output signature (e.g. the manual code phase was
    already gated and phase-4 re-judges the identical output), the existing
    decision is reused and no second verdict is recorded.
    """
    prev_next = state.get("manager_next")
    if prev_next == "e2e":
        worker = "e2e"
    elif prev_next == "code":
        worker = "code"
    else:
        worker = infer_last_worker(state)

    signature = _output_signature(state, worker)
    verdicts = state.get("manager_verdicts") or []
    last_for_node = next(
        (v for v in reversed(verdicts) if v.get("node") == worker),
        None,
    )
    if last_for_node and last_for_node.get("signature") == signature:
        # Same output already judged — reuse the decision, don't re-record.
        decision = last_for_node.get("decision", "pass")
        reason = last_for_node.get("reason", "")
        recovery = last_for_node.get("recovery")
        logger.info(
            "manager_gate_reuse_verdict",
            worker=worker,
            decision=decision,
            reason=reason,
        )
    else:
        decision, reason, _evidence, _missing = await evaluate_stage_l2(state, worker, llm_fn)
        recovery = None
        verdict_reason = reason
        if decision in ("redo", "rollback"):
            # ── Task group 9: 失败分类 → 尝试计数 → 恢复阶梯 → 持久化 ──
            # 阶梯第一级 (重派) = 既有 redo 路径; 分类理由 + 历史策略作为
            # 反馈进入下一轮生成 (9.2 形式化)。红线 (9.3) / 熔断 → escalate。
            from .recovery import build_recovery_feedback, run_recovery

            recovery = await run_recovery(
                state, node=worker, decision=decision, reason=reason,
                missing=_missing, llm_fn=llm_fn,
            )
            if not recovery["escalate"]:
                verdict_reason = reason + "\n" + build_recovery_feedback(
                    recovery["classification"], recovery["strategy"]
                )
        record_verdict(state, worker, decision, verdict_reason)
        if recovery is not None:
            state["manager_verdicts"][-1]["recovery"] = {
                "category": recovery["classification"]["category"],
                "reason": recovery["classification"]["reason"],
                "strategy": recovery["strategy"],
                "attempts": recovery["attempts"],
                "escalate": recovery["escalate"],
                "scope_change": bool(recovery["classification"].get("scope_change")),
                "scope_change_note": recovery["classification"].get("scope_change_note", ""),
                "suggested_fix": recovery["classification"].get("suggested_fix", ""),
                "signature": recovery["classification"]["signature"],
            }
        elif decision == "pass":
            # 9.5: gate 通过 → 该节点未决恢复事件闭环 (resolved / stale,
            # fix_strategies 成功计数)。
            from .recovery import resolve_recovery_outcomes

            resolve_recovery_outcomes(state, worker)

    # ── Routing decision ──
    if decision in ("redo", "rollback"):
        # 9.3 红线 / 9.4 熔断: 不再自主派发 worker — 停在目标 worker 中断处,
        # runner 以 escalated_signature 发射求援卡 (继续自主/转人工)。
        # 9.4: 把关 redo/rollback 路由必须过 LoopControl (每节点 ≤3 / 总数
        # ≤10 / 无改进熔断) — 之前的 gate redo 路径绕过了它。
        from .recovery import gate_loop_check

        escalated, state = gate_loop_check(state, worker, recovery, target="code")
        if not escalated and state.get("scope_change_approved"):
            # M5: 用户已确认的范围变更进入 code 重跑 prompt (failure_details
            # 通道 — code_node 的重派指令消费点)。10.1: 带去重守卫 — resume
            # 入口可能已把确认范围注入 checkpoint failure_details, 防重复。
            note = state["scope_change_approved"]
            if isinstance(note, str) and note.strip():
                fd = dict(state.get("failure_details") or {})
                instruction = fd.get("instruction", "")
                block = f"[用户已确认的范围变更] {note.strip()}"
                if block not in instruction:
                    fd["instruction"] = (instruction + "\n" if instruction else "") + block
                    fd.setdefault("source", "code")
                    fd.setdefault("failed_items", [])
                    fd.setdefault("rollback_target", "code")
                    state["failure_details"] = fd
        state["manager_next"] = (
            worker if escalated and worker in ("code", "e2e") else "code"
        )
    elif state.get("e2e_passed"):
        state["manager_next"] = "end"
    elif worker == "e2e":
        # Group 6 routing: distinguish e2e awaiting confirmation / execution
        # from e2e failed. e2e_results is None until the frontend runner
        # POSTs them (resume_after_e2e) — cases generated but not yet
        # confirmed/executed pause at the e2e worker interrupt instead of
        # rolling back to the code worker. Once results exist and the gate
        # did not pass them, the real-regression path rolls back to code.
        # NOTE (defensive): an EMPTY list (e2e_results == []) — "executed with
        # no results" — is treated as done-but-failed and rolls back to code.
        # In practice resume_after_e2e always writes a non-empty list (the
        # runner submits every case incl. skipped ones), so this branch is
        # dead-defensive rather than a real path.
        if state.get("e2e_results") is None:
            state["manager_next"] = "e2e"       # awaiting confirmation / execution
        else:
            state["manager_next"] = "code"      # executed & failed → rollback to code
    else:
        state["manager_next"] = "e2e"           # dispatch the next worker

    logger.info(
        "manager_gate_verdict",
        worker=worker,
        decision=decision,
        reason=reason,
        next=state["manager_next"],
    )
    return state
