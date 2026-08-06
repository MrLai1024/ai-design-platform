"""User-feedback disposal (task group 10) — 反馈 → Manager 恢复决策.

10.1 迁移: ``POST /api/v1/generation/feedback`` 的反馈不再注入 Planner 自我审查
(旧 code-feedback-loop 路径), 而是进入 Manager 处置流程:

- **分类** ``classify_user_feedback`` — 三类: ``omission``(遗漏) /
  ``correction``(纠偏) / ``scope_change``(范围变更)。确定性短语优先
  (零 LLM), 模糊时走 ``_llm_structured`` seam (与 recovery/manager 同模式),
  fail-safe 回退确定性启发式 (confidence "low")。
- **处置** ``dispose_user_feedback`` — 遗漏/纠偏 → 重派功能实现 worker,
  反馈作为重派指令 (``failure_details.instruction``, U9 redo 通道) 在下次
  run/resume 入口消费; 范围变更 → ``pending_scope_change`` + confirm_card
  (U9 范围确认机制, 用户确认后才进入重派反馈)。范围确认卡「重新生成/取消」
  的拒绝标记 (``rejects_scope_change``) 不进入处置, 保持 U9 拒绝语义。
- **持久化** ``record_feedback_problem`` — 每条反馈落 problems.jsonl +
  memory_db problem_records (分类 + 处置结果), 全部 fail-open (与
  recovery._record_problem_io 同模式, 独立实现避免私有依赖)。
"""

from __future__ import annotations

import structlog

from .recovery import rejects_scope_change

logger = structlog.get_logger()

# ── 10.1 分类词表 ──
FEEDBACK_CATEGORY_LABELS = {
    "omission": "遗漏",
    "correction": "纠偏",
    "scope_change": "范围变更",
    "scope_reject": "拒绝范围变更",
}

# 确定性短语 → 类别。任一类别命中即免 LLM (确定性优先, confidence "high");
# 多类别同时命中 (如"缺少登录但新增一个功能") → 交 LLM 判断。
# 注意: 单字 "补" 已移除 — "补充登录功能" 会误命中 correction (归类歧义,
# 且 omission/correction 都路由到重派, 标签差异无行为影响)。
_DETERMINISTIC_MARKERS: dict[str, tuple[str, ...]] = {
    "omission": ("缺少", "缺失", "漏", "没有", "没实现", "不存在", "忘", "未生成"),
    "correction": ("改", "修正", "调整", "不对", "错", "问题", "不好", "优化"),
    "scope_change": ("新增", "扩展", "加上", "增加", "加一个", "加个", "新功能", "额外"),
}

# ── LLM 分类 seam (10.1, 与 recovery.CLASSIFY_SCHEMA 同模式) ──
FEEDBACK_CLASSIFY_SCHEMA: dict = {
    "category": "",
    "reason": "",
    "scope_note": "",
}

FEEDBACK_CLASSIFY_PROMPT = """你是 AI 生成流水线中 Manager 的反馈分类器。用户对已生成功能提出反馈，请判断反馈类别。

可选类别（只能输出一个）：
- omission 遗漏：反馈指出某组件/功能缺失，且属于当前需求规格已声明的范围（生成结果没做全）
- correction 纠偏：反馈要求修正生成结果的错误或调整细节（实现与需求不符、界面不对、逻辑有问题）
- scope_change 范围变更：反馈提出新增超出当前需求范围的新功能/新模块

## 判断规则
- 需求已声明但生成结果缺失 → omission
- 已有功能的实现细节需要修改 → correction
- 提出需求之外的全新功能点 → scope_change
- 只输出一个 JSON 对象，不要其他内容：
{{"category": "omission", "reason": "一句话分类理由", "scope_note": "仅范围变更时填写：需要新增的功能描述"}}

## 输入
- 反馈文本：{feedback}
- 当前阶段：{stage}"""


def _deterministic_classify(feedback: str) -> tuple[str, str] | None:
    """确定性短语分类; 命中唯一类别 → (category, reason), 模糊 → None (交 LLM)."""
    hits = [
        category for category, markers in _DETERMINISTIC_MARKERS.items()
        if any(m in feedback for m in markers)
    ]
    if len(hits) != 1:
        return None
    category = hits[0]
    marker = next(m for m in _DETERMINISTIC_MARKERS[category] if m in feedback)
    return category, f"反馈含「{marker}」短语，确定性归类为「{FEEDBACK_CATEGORY_LABELS[category]}」"


def _heuristic_category(feedback: str) -> str:
    """Fail-safe: LLM 不可用时的确定性回退 (confidence "low")."""
    if any(m in feedback for m in _DETERMINISTIC_MARKERS["omission"]):
        return "omission"
    if any(m in feedback for m in _DETERMINISTIC_MARKERS["scope_change"]):
        return "scope_change"
    return "correction"


async def classify_user_feedback(
    feedback: str,
    stage: str = "",
    llm_fn=None,
) -> dict:
    """10.1 反馈分类 — 确定性优先, LLM 仅处理模糊输入。

    ``llm_fn`` — LLM seam (brainstorm 模式; None → 单例 ``_llm_generate`` 路径)。
    Returns ``{category, reason, confidence, scope_note}``。
    """
    text = (feedback or "").strip()
    deterministic = _deterministic_classify(text)
    if deterministic is not None:
        category, reason = deterministic
        return {"category": category, "reason": reason, "confidence": "high", "scope_note": ""}

    from .brainstorm import _llm_structured

    user_parts = [f"反馈文本：{text}", f"当前阶段：{stage or '（未指定）'}"]
    try:
        raw = await _llm_structured(
            FEEDBACK_CLASSIFY_PROMPT.format(feedback=text, stage=stage or "（未指定）"),
            "\n".join(user_parts),
            FEEDBACK_CLASSIFY_SCHEMA,
            llm_fn,
        )
    except Exception as e:
        logger.warning("feedback_classify_llm_failed", error=str(e))
        raw = {}

    category = str(raw.get("category", "")).strip()
    if category not in FEEDBACK_CATEGORY_LABELS:
        category = _heuristic_category(text)
        confidence = "low"
        reason = str(raw.get("reason", "")).strip() or (
            f"LLM 分类不可用，按短语启发式判定为「{FEEDBACK_CATEGORY_LABELS[category]}」"
        )
    else:
        confidence = "medium"
        reason = str(raw.get("reason", "")).strip() or FEEDBACK_CATEGORY_LABELS[category]
    scope_note = str(raw.get("scope_note", "")).strip()
    return {"category": category, "reason": reason, "confidence": confidence, "scope_note": scope_note}


# ── 10.1 持久化 (problems.jsonl + memory_db, fail-open) ──


def record_feedback_problem(
    generation_id: str,
    feedback: str,
    classification: dict,
    action: str,
    result: str,
) -> None:
    """反馈处置落库: problems.jsonl (project_root 派生) + memory_db
    problem_records — 分类 + 处置结果, 与 recovery._persist_recovery 同模式。
    fail-open, 绝不阻断反馈链路。"""
    category = classification["category"]
    problem = f"用户反馈：{feedback[:200]}"
    root_cause = classification.get("reason") or ""
    try:
        from .memory import append_problem, app_dir_for

        append_problem(
            app_dir_for(generation_id),
            category="user_feedback",
            problem=problem,
            root_cause=root_cause,
            fix=action,
            result=result,
        )
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("feedback_problem_append_failed", error=str(e))
    try:
        from .memory_db import get_memory_db

        get_memory_db().append_problem(
            generation_id,
            "user_feedback", problem, root_cause, action, result,
        )
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("feedback_problem_db_failed", error=str(e))


# ── 10.1 处置主入口 ──


async def dispose_user_feedback(
    runner,
    generation_id: str,
    stage: str,
    feedback: str,
    llm_fn=None,
) -> dict:
    """Manager 处置一条用户反馈 — 分类 → 记录 → 挂起 (下次 run/resume 消费)。

    Returns the disposition dict (RPC 响应载荷)::
        {category, category_label, action, result, reason, feedback, scope_note}

    - 范围确认卡「重新生成/取消」拒绝标记 (rejects_scope_change) → 不处置,
      保持 U9 的 resume 拒绝语义 (metadata code_feedback → resume 消费)。
    - 遗漏/纠偏 → 挂起重派: runner._pending_feedback 被下次 run/resume 入口
      消费 (failure_details.instruction 注入 + 重派执行 + 处置卡)。
    - 范围变更 → 挂起范围确认: 下次入口发射 confirm_card (pending_scope_change),
      用户确认后才进入重派反馈。
    """
    text = (feedback or "").strip()
    if not text:
        return {
            "category": "", "category_label": "无效反馈",
            "action": "忽略空反馈", "result": "rejected", "reason": "反馈文本为空",
        }

    # 范围确认卡拒绝标记 → 保持 U9 语义, 不进入处置。
    if rejects_scope_change(text):
        return {
            "category": "scope_reject",
            "category_label": FEEDBACK_CATEGORY_LABELS["scope_reject"],
            "action": "拒绝范围变更（范围确认卡选项）",
            "result": "rejected",
            "reason": "范围确认卡「重新生成/取消」— 范围变更不被批准",
        }

    # review fix: 上一条反馈尚未消费 (run/resume 入口处置中) → busy 拒绝,
    # 绝不覆盖挂起处置 (否则第一条已回执 "dispatched" 却从未重派)。
    if runner._pending_feedback is not None:
        logger.warning(
            "feedback_busy_pending",
            generation_id=generation_id,
            pending=runner._pending_feedback.get("feedback", "")[:40],
        )
        return {
            "category": "",
            "category_label": "处置中",
            "action": "上一条反馈尚未处置完成，请稍后重试",
            "result": "busy",
            "reason": "上一条反馈已受理，正在等待重派/确认流程",
        }

    classification = await classify_user_feedback(text, stage, llm_fn=llm_fn)
    category = classification["category"]
    if category == "scope_change":
        action = "范围变更待确认（confirm_card）"
        result = "awaiting_confirm"
    else:
        action = "重派功能实现任务（携带反馈）"
        result = "dispatched"

    record_feedback_problem(
        generation_id, text, classification, action, result,
    )
    runner._pending_feedback = {
        "feedback": text,
        "stage": stage,
        "category": category,
        "reason": classification["reason"],
        "confidence": classification["confidence"],
        "scope_note": classification.get("scope_note", ""),
        "action": action,
        "result": result,
        "category_label": FEEDBACK_CATEGORY_LABELS.get(category, category),
    }
    logger.info(
        "feedback_disposed",
        generation_id=generation_id,
        category=category,
        result=result,
        feedback_len=len(text),
    )
    return dict(runner._pending_feedback)
