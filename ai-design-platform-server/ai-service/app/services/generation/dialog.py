"""Manager dialog — the Manager persona's speech and intent routing.

The Manager is the ONLY agent that speaks to the user. All Manager speech
(summaries, gate verdicts, failure diagnoses, confirmation pleas) is emitted as
a single GraphEvent type ``manager_message`` whose ``data.card`` discriminates
the structured card kind (mirroring the frontend's ``ManagerCardType``):

- ``summary_card``    — node-completed summary (after each stage completes)
- ``verdict_card``    — gate decision: pass → "通过" + reason; redo/rollback → "未通过" + reason
- ``diagnosis_card``  — failure diagnosis (L1 evidence) + recovery suggestion + options
- ``confirm_card``    — user confirmation request (agenda engine, task group 3)
- ``question_card``   — clarification question for one agenda item (agenda engine, task group 3)
- ``proposal_card``   — Manager proposal / candidate plan comparison (agenda engine, task group 3)
- ``coverage_matrix`` — E2E coverage matrix (Test Designer, task group 6)

Builders are pure functions producing ``{"event_type", "stage", "data"}`` dicts,
the same shape ``GraphRunner._make_event`` yields, so they stream unchanged over
the existing gRPC/SSE path.

``classify_intent`` is the Manager's self-routing endpoint (task 2.3): ONE
lightweight LLM call classifies the user's dialog input into
reply_qa / proceed / feedback / escalate / ask_why.
"""

import json
import re

import structlog

from ..llm.provider import LLMConfig, TokenEvent
from .nodes import _llm_generate

logger = structlog.get_logger()

# ── Card discriminators (mirror the frontend ManagerCardType) ──
CARD_SUMMARY = "summary_card"
CARD_VERDICT = "verdict_card"
CARD_DIAGNOSIS = "diagnosis_card"
CARD_CONFIRM = "confirm_card"
CARD_PROPOSAL = "proposal_card"
CARD_COVERAGE = "coverage_matrix"
CARD_QUESTION = "question_card"
CARD_FEEDBACK = "feedback_card"

STAGE_LABELS = {
    "analysis": "需求分析",
    "design": "方案设计",
    "code": "功能实现",
    "e2e": "E2E 验证",
}

# ── Intent values (mirror the frontend ManagerIntent) ──
INTENT_REPLY_QA = "reply_qa"
INTENT_PROCEED = "proceed"
INTENT_FEEDBACK = "feedback"
INTENT_ESCALATE = "escalate"
INTENT_ASK_WHY = "ask_why"
VALID_INTENTS = (
    INTENT_REPLY_QA,
    INTENT_PROCEED,
    INTENT_FEEDBACK,
    INTENT_ESCALATE,
    INTENT_ASK_WHY,
)


def _manager_message(stage: str, payload: dict) -> dict:
    """Build a ``manager_message`` GraphEvent dict."""
    return {"event_type": "manager_message", "stage": stage, "data": payload}


def summary_card_event(node: str, summary: str) -> dict:
    """Manager speech: node-completed summary (after each stage completes)."""
    label = STAGE_LABELS.get(node, node)
    return _manager_message(node, {
        "card": CARD_SUMMARY,
        "title": f"{label}阶段产出总结",
        "content": summary or "",
        "data": {"node": node},
    })


def verdict_card_event(node: str, decision: str, reason: str = "") -> dict:
    """Manager speech: gate decision — pass → "通过"; redo/rollback → "未通过"."""
    passed = decision == "pass"
    label = STAGE_LABELS.get(node, node)
    content = f"Manager 把关{'通过' if passed else '未通过'} · {label}"
    if reason:
        content += f"\n{reason}"
    return _manager_message(node, {
        "card": CARD_VERDICT,
        "title": f"Manager 把关裁决 · {label}",
        "content": content,
        "data": {
            "node": node,
            "decision": decision,
            "reason": reason,
            "passed": passed,
        },
    })


def diagnosis_card_event(
    node: str,
    evidence: list[str] | str,
    suggestion: str = "",
    options: list[str] | None = None,
    missing: list[dict] | None = None,
) -> dict:
    """Manager speech: failure diagnosis (L1 evidence) + recovery suggestion.

    ``options`` powers the dialog 求援 card (task 2.5): ["继续自主", "转人工"].
    ``missing`` (task 4.4): the design L2 gate's missing list
    [{feature, evidence}] — rides in ``data`` for the frontend, no new card.
    """
    label = STAGE_LABELS.get(node, node)
    if isinstance(evidence, (list, tuple)):
        content = "\n".join(str(e) for e in evidence) if evidence else "未提供诊断细节"
    else:
        content = str(evidence)
    return _manager_message(node, {
        "card": CARD_DIAGNOSIS,
        "title": f"Manager 诊断 · {label}",
        "content": content,
        "options": options or [],
        "data": {
            "node": node,
            "evidence": evidence,
            "suggestion": suggestion,
            "missing": missing or [],
        },
    })


def confirm_card_event(
    node: str,
    message: str,
    options: list[str] | None = None,
) -> dict:
    """Manager speech: user confirmation request (agenda engine, task group 3)."""
    label = STAGE_LABELS.get(node, node)
    return _manager_message(node, {
        "card": CARD_CONFIRM,
        "title": f"确认 · {label}",
        "content": message,
        "options": options or [],
        "data": {"node": node},
    })


def question_card_event(
    node: str,
    question: str,
    options: list[str] | None = None,
    item_id: str = "",
) -> dict:
    """Manager speech: clarification question for one agenda item (task group 3).

    ``item_id`` ties the card back to the agenda item so the user's option
    click can be routed to the right item on the next brainstorm turn.
    """
    label = STAGE_LABELS.get(node, node)
    return _manager_message(node, {
        "card": CARD_QUESTION,
        "title": f"澄清提问 · {label}",
        "content": question,
        "options": options or [],
        "data": {"node": node, "item_id": item_id},
    })


def proposal_card_event(
    node: str,
    proposal: str,
    options: list[str] | None = None,
) -> dict:
    """Manager speech: proposal for the user to accept/adjust.

    Real emission: brainstorm proposal comparison (task group 3) — 2~3
    candidate plans (范围取舍 + 交互形态, pros/costs) with choice options.
    """
    label = STAGE_LABELS.get(node, node)
    return _manager_message(node, {
        "card": CARD_PROPOSAL,
        "title": f"Manager 建议 · {label}",
        "content": proposal,
        "options": options or [],
        "data": {"node": node},
    })


def coverage_matrix_event(
    node: str,
    matrix: dict | list,
    content: str = "",
    extra: dict | None = None,
) -> dict:
    """Manager speech: E2E coverage matrix (real emission: task group 6).

    ``matrix`` — requirement-point → coverage mapping for the card body
    (dict keyed by requirement id; the frontend renders entries as
    key → JSON). ``content`` — human-readable summary (gap list); ``extra`` —
    additional card data (passed / gaps / counts) merged into ``data``.
    """
    label = STAGE_LABELS.get(node, node)
    data = {"node": node, "matrix": matrix}
    if extra:
        data.update(extra)
    return _manager_message(node, {
        "card": CARD_COVERAGE,
        "title": f"E2E 覆盖矩阵 · {label}",
        "content": content or "",
        "data": data,
    })


def feedback_disposition_card_event(
    stage: str,
    feedback: str,
    disposition: dict,
) -> dict:
    """Manager speech: 反馈处置结果卡片 (10.2, 对话框折叠摘要)。

    折叠行 = 反馈摘要 + 处置动作 + 结果; 展开 (前端渲染 data) = 处置过程
    (分类、重派任务、验证结果)。随反馈消费在 run/resume 入口发射。
    不携带 content — 前端 feedback_card 完全由 data 派生渲染 (40 字摘要 +
    分类 + 结果标签), 重复的 content 串无人消费 (review fix)。

    NOTE (spec drift, review): spec 场景 "处置与重派执行完成 THEN 卡片" —
    实现在反馈消费点 (run/resume 入口) 即发射, 结果字段为处置决策
    (dispatched/awaiting_confirm); 重派后的验证结果由同流后续把关裁决卡呈现。
    """
    label = STAGE_LABELS.get(stage, stage)
    category = disposition.get("category") or ""
    return _manager_message(stage, {
        "card": CARD_FEEDBACK,
        "title": f"反馈处置 · {label}",
        "data": {
            "node": stage,
            "feedback": feedback,
            "category": category,
            "category_label": disposition.get("category_label") or category,
            "reason": disposition.get("reason") or "",
            "action": disposition.get("action") or "",
            "result": disposition.get("result") or "",
        },
    })


def gate_speech_events(
    stage: str,
    decision: str,
    reason: str,
    summary: str,
    evidence: list[str],
    missing: list[dict] | None = None,
) -> list[dict]:
    """Manager speech for one gate run (task 2.4).

    pass → summary_card + verdict_card; redo/rollback → diagnosis_card.
    ``missing`` (task 4.4) rides on the diagnosis card for design L2 failures.
    """
    if decision == "pass":
        return [
            summary_card_event(stage, summary),
            verdict_card_event(stage, decision, reason),
        ]
    return [
        diagnosis_card_event(
            stage,
            evidence,
            suggestion=_recovery_suggestion(stage, decision),
            missing=missing,
        ),
    ]


def _recovery_suggestion(stage: str, decision: str) -> str:
    """Next-step copy for the diagnosis card — aligned with what the flow
    actually does on confirm (review fix 1: design redo re-runs phase 2 with
    the gate's feedback; other stages' redo does not re-run today)."""
    label = STAGE_LABELS.get(stage, stage)
    if decision == "rollback":
        return f"{label} 未通过验收，流程将回滚到代码阶段重新执行。"
    if stage == "design":
        return f"{label} 未通过验收，已清空设计方案产物，确认后将重新执行方案设计阶段。"
    if stage == "code":
        return f"{label} 未通过验收，确认后将重新执行功能实现阶段。"
    return f"{label} 产出未通过验收，确认后将进入下一阶段。"


# ── 增量开发卡片内容渲染 (8.1/8.2/8.4, task group 8) ──


def render_existing_summary(context: dict) -> str:
    """summary_card content: 当前功能清单 + 已完成状态."""
    summary = context.get("summary") or {}
    state_json = summary.get("state") or {}
    lines = ["**当前应用状态**（已从 .ai-memory 加载）"]
    features = state_json.get("features") or []
    if features:
        lines.append("已规划功能点：")
        lines.extend(
            f"- {f.get('name', '?')}（{f.get('status', 'planned')}）"
            for f in features if isinstance(f, dict) and f.get("name")
        )
    else:
        lines.append("已规划功能点：无（记忆为空）")
    implemented = state_json.get("implemented") or []
    if implemented:
        lines.append(f"已完成实现任务：{', '.join(str(i) for i in implemented)}")
    milestones = state_json.get("milestones") or {}
    if milestones:
        lines.append(
            f"里程碑：{milestones.get('completed_tasks', 0)}/{milestones.get('total_tasks', 0)} 任务完成"
        )
    return "\n".join(lines)


def render_diff_card(diff: dict) -> str:
    """diff confirm_card content: 新增/修改/删除功能点清单."""
    lines = ["**增量变更清单（diff）**"]
    added = diff.get("added") or []
    removed = diff.get("removed") or []
    modified = diff.get("modified") or []
    unchanged = diff.get("unchanged") or []
    lines.append(f"🆕 新增功能点（{len(added)}）")
    if added:
        lines.extend(f"- {n}" for n in added)
    else:
        lines.append("- （无）")
    lines.append(f"✏️ 行为变更（{len(modified)}）")
    if modified:
        for m in modified:
            lines.append(f"- {m.get('name', '?')}: {m.get('from', '')} → {m.get('to', '')}")
    else:
        lines.append("- （无）")
    lines.append(f"🗑️ 删除功能点（{len(removed)}）")
    if removed:
        lines.extend(f"- {n}" for n in removed)
    else:
        lines.append("- （无）")
    if unchanged:
        lines.append(f"✅ 保持不变（{len(unchanged)}）: {', '.join(unchanged[:8])}")
    lines.append("\n确认后生成变更 manifest；选择「重新生成」将重新执行本步。")
    return "\n".join(lines)


def render_manifest_card(manifest: dict) -> str:
    """manifest confirm_card content."""
    type_labels = {
        "new_feature": "新增功能",
        "behavior_change": "行为变更",
        "refactor": "重构（行为不变）",
        "visual": "视觉改版",
    }
    lines = [
        "**变更 manifest**",
        f"变更 ID：{manifest.get('change_id', '?')}",
        f"变更类型：{type_labels.get(manifest.get('type', ''), manifest.get('type', '?'))}",
    ]
    modules = manifest.get("affected_modules") or []
    lines.append(f"涉及模块：{', '.join(modules) or '（未判定）'}")
    points = manifest.get("affected_requirement_points") or []
    lines.append(f"受影响需求点：{', '.join(points) or '（未判定）'}")
    bcs = manifest.get("behavior_changes") or []
    if bcs:
        lines.append("行为变更清单：")
        lines.extend(f"- {b.get('point', '?')}: {b.get('from', '')} → {b.get('to', '')}" for b in bcs)
    lines.append("\n确认后分析历史用例影响；选择「重新生成」将重新生成 manifest。")
    return "\n".join(lines)


def render_disposition_card(dispositions: list[dict]) -> str:
    """disposition confirm_card content: 历史用例处置清单 + 理由."""
    labels = {
        "keep": "保持",
        "update": "重设计",
        "retire": "停用",
        "fix-selector": "修选择器",
    }
    lines = ["**历史用例处置清单（Test Impact）**"]
    if not dispositions:
        lines.append("- （无历史用例，无需处置）")
    for d in dispositions:
        lines.append(
            f"- {d.get('case_id', '?')} [{d.get('requirement_id', '')}] "
            f"→ {labels.get(d.get('disposition', ''), d.get('disposition', '?'))}：{d.get('reason', '')}"
        )
    lines.append("\n确认后执行增量回归；选择「重新生成」将重新分析用例影响。")
    return "\n".join(lines)


# ── Intent classification (task 2.3) ──

# 4.x (review M4): 高频确认/修改短语精确匹配短路 —— 跳过 LLM 调用。
_QUICK_INTENTS: dict[str, str] = {
    "确认": INTENT_PROCEED, "可以": INTENT_PROCEED, "同意": INTENT_PROCEED,
    "没问题": INTENT_PROCEED, "继续": INTENT_PROCEED, "下一步": INTENT_PROCEED,
    "开始": INTENT_PROCEED, "好的": INTENT_PROCEED, "行": INTENT_PROCEED,
    "yes": INTENT_PROCEED, "confirm": INTENT_PROCEED, "continue": INTENT_PROCEED, "ok": INTENT_PROCEED,
    "修改": INTENT_FEEDBACK, "不对": INTENT_FEEDBACK, "改一下": INTENT_FEEDBACK,
    "重新生成": INTENT_FEEDBACK, "重来": INTENT_FEEDBACK, "no": INTENT_FEEDBACK,
}

INTENT_CLASSIFY_PROMPT = """你是 AI 生成流水线中 Manager 助手的对话意图分类器。用户正在与 Manager 对话，请判断用户这次发言的意图。

可选意图（只能输出一个）：
- reply_qa: 用户在回答 Manager 提出的澄清问题（例如回答需求追问）
- proceed: 用户表示认可/同意当前产出，希望继续下一步（例如"开始""可以了""没问题""继续"）
- feedback: 用户对当前阶段产出提出修改意见、问题或补充要求
- escalate: 用户想自己接手控制流程、停止自动化（例如"我自己来""转人工""停一下"）
- ask_why: 用户在询问某个决策或产出"为什么"（例如"为什么这么设计""理由是什么"）

## 输出格式
只输出一个 JSON 对象，不要其他内容：
{"intent": "reply_qa", "reason": "一句话说明判断依据"}"""


def _parse_intent(raw: str) -> tuple[str, str]:
    """Parse the classifier's JSON output; fail-safe to reply_qa."""
    text = (raw or "").strip()
    # Strip markdown code fences if present (case-insensitive: ```JSON / ```Json)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        intent = str(obj.get("intent", "")).strip()
        reason = str(obj.get("reason", "")).strip()
        if intent in VALID_INTENTS:
            return intent, reason
        logger.warning("intent_classify_out_of_vocab", intent=intent, raw=raw[:200])
        return INTENT_REPLY_QA, f"分类器返回了未知意图：{intent}"
    except (json.JSONDecodeError, AttributeError):
        logger.warning("intent_classify_parse_failed", raw=raw[:200])
        return INTENT_REPLY_QA, "意图分类输出无法解析，回退为回复澄清问题"


async def _generate_with_provider(
    provider,
    system_prompt: str,
    user_content: str,
) -> str:
    """Single-turn LLM call through an explicit provider instance.

    Used by ``classify_intent`` when the caller passes a provider, so intent
    classification never touches the module-level ``_provider`` singleton that
    running graph streams read on every ``_llm_generate`` call.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    config = LLMConfig(enable_thinking=False)
    full_text = ""
    async for event in provider.stream_generate("glm-5.2", messages, config):
        if isinstance(event, TokenEvent):
            full_text += event.text
    return full_text


async def classify_intent(
    text: str,
    stage: str = "",
    generation_id: str = "",
    provider=None,
) -> dict:
    """Classify the user's dialog input with ONE lightweight LLM call.

    ``provider`` — an explicit LLM provider instance (recommended; avoids the
    shared singleton). When omitted, falls back to ``_llm_generate`` (the
    graph-path singleton) for convenience/back-compat.

    Returns ``{"intent", "reason"}`` with intent in
    reply_qa / proceed / feedback / escalate / ask_why.
    """
    text = (text or "").strip()
    if not text:
        logger.info("intent_classified_empty", stage=stage, generation_id=generation_id)
        return {"intent": INTENT_REPLY_QA, "reason": "空输入，回退为回复澄清问题"}

    # review M4: 高频短语精确匹配短路 — 确认/修改类指令不依赖 LLM 分类。
    quick = _QUICK_INTENTS.get(text.lower())
    if quick:
        logger.info("intent_classified_quick", stage=stage, intent=quick, text=text[:20])
        return {"intent": quick, "reason": "高频确认短语精确匹配（免 LLM）"}

    user_content = f"用户输入：{text}\n当前阶段：{stage or '（未指定）'}"
    if provider is not None:
        raw = await _generate_with_provider(provider, INTENT_CLASSIFY_PROMPT, user_content)
    else:
        raw = await _llm_generate(
            system_prompt=INTENT_CLASSIFY_PROMPT,
            user_content=user_content,
            enable_thinking=False,
        )
    intent, reason = _parse_intent(raw)
    logger.info(
        "intent_classified",
        stage=stage,
        generation_id=generation_id,
        intent=intent,
        reason=reason,
    )
    return {"intent": intent, "reason": reason}
