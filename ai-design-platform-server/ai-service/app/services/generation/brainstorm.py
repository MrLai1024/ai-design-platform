"""Agenda-driven brainstorm engine (task group 3).

Replaces the fixed 3-layer clarification state machine (requirements/) with an
agenda-driven exploratory clarification:

- **Agenda is the core state** (D4): ``AgendaItem = {id, topic, reason(缺失后果),
  impact(影响面), status: answered|assumed|conflict, answer}``.
- **First round**: the Manager analyses the requirement (需求画像) — requirement
  type, ambiguities, 2~3 candidate plan sketches — and asks NO questions.
- **Subsequent rounds**: the Manager asks 1~3 questions by impact
  (方案设计 > 界面展示 > …); unanswered items get marked ``assumed`` and surface
  in the PRD 假设清单.
- **Proposal comparison** before convergence: a proposal_card with 2~3 candidate
  plans (范围取舍 + 交互形态, each with pros/costs); the user's choice is
  recorded in the decision log.
- **Dual-factor convergence**: agenda coverage >= threshold AND user confirm.
  Outputs = structured requirement (RequirementsState) + decisions + assumptions.

All LLM calls are single-turn with explicit JSON output schemas; the ``llm_fn``
seam is monkeypatched in tests (no real LLM).

Sessions live in an in-memory registry keyed by generation_id (persistence is
task group 7).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from .dialog import (
    confirm_card_event,
    proposal_card_event,
    question_card_event,
    summary_card_event,
    _manager_message,
)
from ..llm.provider import LLMConfig, TokenEvent
from .nodes import _llm_generate
from .requirements.state import (
    RequirementsState,
    VisionData,
    TargetUser,
    FeatureModule,
    PageNode,
    PageDetail,
    FieldDef,
    ActionDef,
    TechConstraints,
    DataEntity,
)

logger = structlog.get_logger()

# ── Tunables ──
COVERAGE_THRESHOLD = 0.8          # 议程覆盖度阈值（双因子之一）
MAX_QUESTIONS_PER_ROUND = 3       # 每轮最多提问数
STAGE_ANALYSIS = "analysis"

# 影响面排序：优先问"方案设计"，其次"界面展示"（spec 场景：关键路径问题优先）
IMPACT_RANK = {
    "design": 0,
    "ui": 1,
    "scope": 2,
    "tech": 3,
    "vision": 4,
}

# 用户显式确认收敛的短语（确定性判定，替代 LLM 自评分作为唯一退出依据）
CONFIRM_PHRASES = (
    "可以开始", "开始吧", "开始设计", "开始生成",
    "确认", "没问题", "可以了", "就这样", "就按这个", "准备好了",
)

# AgendaItem 状态
STATUS_PENDING = "pending"
STATUS_ANSWERED = "answered"
STATUS_ASSUMED = "assumed"
STATUS_CONFLICT = "conflict"

LLMFn = Callable[[str, str], Awaitable[str]]


# ── 3.1 AgendaItem 数据模型 ──


@dataclass
class AgendaItem:
    """一个议程项：主题 + 缺失后果 + 影响面 + 状态 + 答案."""

    id: str
    topic: str
    reason: str = ""                       # 缺失后果
    impact: str = "design"                 # 影响面: design|ui|scope|tech|vision
    status: str = STATUS_PENDING          # pending|answered|assumed|conflict
    answer: str = ""
    question: str = ""                     # 最近一次提问的文案
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "reason": self.reason,
            "impact": self.impact,
            "status": self.status,
            "answer": self.answer,
        }


@dataclass
class BrainstormSession:
    """头脑风暴会话：议程 + 画像 + 决策日志 + 假设清单 + 收敛标志."""

    generation_id: str
    user_id: str = "default"            # 长期用户级记忆维度 (task group 7.6)
    requirement: str = ""
    round: int = 0
    profile: dict | None = None            # 首轮需求画像（结构化）
    agenda: list[AgendaItem] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)      # 决策日志
    assumptions: list[dict] = field(default_factory=list)    # 假设清单
    proposal_shown: bool = False           # 方案对比卡片已输出
    proposal_decided: bool = False         # 用户已选择方案
    proposals: list[dict] = field(default_factory=list)
    user_confirmed: bool = False           # 用户显式确认收敛
    converged: bool = False
    requirements_state_json: str | None = None   # 收敛产物：结构化需求
    last_asked_ids: list[str] = field(default_factory=list)   # 本轮提问的项
    prior_asked_ids: list[str] = field(default_factory=list)  # 上一轮提问的项


# ── Session registry (in-memory; persistence = task group 7) ──

_SESSIONS: dict[str, BrainstormSession] = {}


def create_session(user_id: str = "default") -> BrainstormSession:
    gid = uuid.uuid4().hex
    session = BrainstormSession(generation_id=gid, user_id=user_id or "default")
    _SESSIONS[gid] = session
    logger.info("brainstorm_session_created", generation_id=gid, user_id=session.user_id)
    return session


def get_session(generation_id: str | None) -> BrainstormSession | None:
    if not generation_id:
        return None
    return _SESSIONS.get(generation_id)


def get_or_create_session(
    generation_id: str | None,
    user_id: str = "default",
) -> BrainstormSession:
    session = get_session(generation_id)
    if session is None:
        session = create_session(user_id=user_id)
    return session


def clear_sessions() -> None:
    """Test helper — drop the in-memory registry."""
    _SESSIONS.clear()


# ── Structured-output LLM helper (single-turn, explicit JSON schema) ──


def _empty_like(schema: Any) -> Any:
    """Build an empty-value mirror of the schema (defaults for missing keys)."""
    if isinstance(schema, dict):
        return {k: _empty_like(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return []
    if isinstance(schema, bool):
        return False
    if isinstance(schema, (int, float)):
        return 0
    return ""


def _merge_schema(obj: Any, schema: Any) -> Any:
    """Merge parsed JSON with the schema: missing keys take empty defaults and
    wrong-typed values are coerced (never crash on valid-JSON/wrong-type LLM
    output).

    An empty-dict schema means "dynamic map" (e.g. ``page_details`` keyed by
    page id) — the parsed dict is kept as-is.
    """
    if isinstance(schema, dict):
        if not isinstance(obj, dict):
            return _empty_like(schema)
        if not schema:
            return obj
        merged: dict = {}
        for key, sub_schema in schema.items():
            if key in obj:
                merged[key] = _merge_schema(obj[key], sub_schema)
            else:
                merged[key] = _empty_like(sub_schema)
        return merged
    if isinstance(schema, list):
        if not isinstance(obj, list):
            return []
        # 列表元素按 schema 首元素类型逐项归并（类型不符的元素取 schema 空默认值）
        element_schema = schema[0] if schema else ""
        return [_merge_schema(item, element_schema) for item in obj]
    if isinstance(schema, str):
        if isinstance(obj, str):
            return obj
        return str(obj) if isinstance(obj, (int, float, bool)) else ""
    if isinstance(schema, bool):
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float)):
            return obj != 0
        if isinstance(obj, str):
            return obj.strip().lower() in ("true", "1", "yes", "是")
        return False
    if isinstance(schema, (int, float)):
        try:
            return type(schema)(obj)
        except (TypeError, ValueError):
            return 0
    return obj


def parse_structured(raw: str, schema: dict) -> dict:
    """Parse the LLM's JSON output: fence-strip + first-brace extraction +
    schema-merge with type coercion; fail-safe to empty defaults."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    # 提取第一个 JSON 对象块（容错：LLM 在代码块后追加说明文字会零化解析）
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("brainstorm_structured_parse_failed", raw_preview=raw[:200])
        return _empty_like(schema)
    return _merge_schema(obj, schema)


async def _llm_structured(
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    llm_fn: LLMFn | None = None,
) -> dict:
    """Single-turn structured LLM call with an explicit JSON output schema.

    ``llm_fn`` defaults to the graph-path ``_llm_generate`` (singleton provider);
    tests pass a fake function.
    """
    fn = llm_fn if llm_fn is not None else _llm_generate
    raw = await fn(system_prompt, user_prompt)
    return parse_structured(raw, schema)


async def _llm_generate_with_provider(
    provider: Any,
    system_prompt: str,
    user_prompt: str,
    model: str = "glm-5.2",
) -> str:
    """Single-turn LLM call through an explicit provider instance.

    Mirrors ``dialog._generate_with_provider``: never touches the shared
    ``_provider`` singleton, so a brainstorm turn running concurrently with a
    graph stream cannot swap the provider mid-stream (fix #4).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    config = LLMConfig(enable_thinking=False)
    full_text = ""
    async for event in provider.stream_generate(model, messages, config):
        if isinstance(event, TokenEvent):
            full_text += event.text
    return full_text


def _provider_llm_fn(provider: Any, model: str = "glm-5.2") -> LLMFn:
    """Wrap an explicit provider instance into an ``llm_fn`` for ``turn()``."""
    async def _fn(system_prompt: str, user_prompt: str) -> str:
        return await _llm_generate_with_provider(provider, system_prompt, user_prompt, model)
    return _fn


# ── Card builders ──


def _profile_card(session: BrainstormSession) -> dict:
    """首轮需求画像卡片：需求类型 + 模糊点 + 候选方案雏形（结构化入 data）. """
    profile = session.profile or {}
    ambiguities = [
        {"id": a.id, "topic": a.topic, "reason": a.reason, "impact": a.impact}
        for a in session.agenda
    ]
    content_lines = [
        f"需求类型：{profile.get('requirement_type', '未识别')}",
        f"核心问题：{profile.get('core_problem', '')}",
        f"目标用户：{', '.join(u.get('role', '') for u in profile.get('target_users', [])) or '未明确'}",
    ]
    cands = profile.get("candidate_plans", []) or []
    if cands:
        content_lines.append("\n候选方案雏形：")
        for c in cands:
            content_lines.append(
                f"- {c.get('name', '')}: {c.get('summary', '')}（{c.get('scope', '')}）"
            )
    if ambiguities:
        content_lines.append("\n已识别的模糊点：")
        for a in ambiguities:
            content_lines.append(f"- {a['topic']}（影响面：{a['impact']}）")
    return _manager_message(STAGE_ANALYSIS, {
        "card": "summary_card",
        "title": "需求画像 · 头脑风暴",
        "content": "\n".join(content_lines),
        "options": [],
        "data": {
            "node": STAGE_ANALYSIS,
            "profile": profile,
            "agenda": ambiguities,
        },
    })


def _coverage_insufficient_card(
    session: BrainstormSession,
    blocker: str = "coverage",
) -> dict:
    """收敛阻塞提示：覆盖不足（列出剩余关键议程项）或方案未选定（真实阻塞点）."""
    remaining = [a.to_dict() for a in session.agenda if a.status != STATUS_ANSWERED]
    if blocker == "proposal":
        title = "还需选定方案"
        lines = [
            f"议程覆盖度已达 {coverage(session):.0%}（阈值 {COVERAGE_THRESHOLD:.0%}），"
            "但方案尚未选定：请先选择候选方案（或指定混合 / 要求调整后重出），"
            "选定后才能开始设计。",
        ]
    else:
        title = "澄清尚未收敛"
        lines = [
            f"当前议程覆盖度 {coverage(session):.0%}，未达到收敛阈值"
            f"（{COVERAGE_THRESHOLD:.0%}），还不能开始设计。以下关键项仍需确认：",
        ]
        for a in remaining:
            lines.append(f"- {a['topic']}（{a['impact']}）")
        lines.append("我们可以继续澄清这些项。")
    return _manager_message(STAGE_ANALYSIS, {
        "card": "summary_card",
        "title": title,
        "content": "\n".join(lines),
        "options": [],
        "data": {
            "node": STAGE_ANALYSIS,
            "remaining": remaining,
            "coverage": coverage(session),
            "threshold": COVERAGE_THRESHOLD,
            "blocker": blocker,
        },
    })


def _converged_card(session: BrainstormSession) -> dict:
    """收敛确认卡片：澄清结束，产物就绪，点击开始设计."""
    return confirm_card_event(
        STAGE_ANALYSIS,
        "需求澄清已收敛：结构化需求、决策日志与假设清单已生成。"
        "点击「🚀 开始设计」进入需求分析阶段。",
        ["确认开始", "还有疑问"],
    )


# ── 3.2 首轮需求画像 ──

PROFILE_PROMPT = """你是 AI 生成流水线中的 Manager（项目负责人）。用户刚提交了一段需求描述，请主动分析并输出结构化「需求画像」，**不要提问**。

## 输出要求（只输出一个 JSON 对象，不要其他内容）
{
  "requirement_type": "需求类型（如 admin_system / ecommerce / dashboard / tool / landing 等）",
  "project_name": "项目名",
  "core_problem": "核心问题一句话",
  "target_users": [{"role": "目标用户角色", "description": "说明"}],
  "success_criteria": ["成功标准"],
  "scope_note": "范围边界说明",
  "ambiguities": [
    {"topic": "模糊点主题", "reason": "缺失后果（如果不澄清会导致什么）", "impact": "design|ui|scope|tech|vision"}
  ],
  "candidate_plans": [
    {"name": "方案A", "summary": "一句话概括", "scope": "范围取舍描述", "interaction": "交互形态描述", "pros": ["优点"], "costs": ["代价"]}
  ],
  "features": [{"id": "F-01", "name": "功能名", "description": "说明", "priority": "must|should|nice"}],
  "pages": [{"id": "P-01", "name": "页面名", "parent_id": null, "page_type": "list|detail|form|dashboard|custom", "features": []}],
  "tech_constraints": {"framework": "vue3", "component_lib": "element-plus", "data_source": "", "special_requirements": []},
  "data_entities": [{"name": "实体名", "fields": [{"name": "字段", "type": "string", "required": false}]}]
}

## 规则
- ambiguities 中每条必须给出 reason（缺失后果）与 impact（影响面），优先覆盖影响「方案设计(design)」与「界面展示(ui)」的项
- candidate_plans 给 2~3 个候选方案雏形，含范围取舍与交互形态
- 用简洁专业的中文"""


def _profile_schema() -> dict:
    return {
        "requirement_type": "",
        "project_name": "",
        "core_problem": "",
        "target_users": [{"role": "", "description": ""}],
        "success_criteria": [""],
        "scope_note": "",
        "ambiguities": [{"topic": "", "reason": "", "impact": "design"}],
        "candidate_plans": [
            {"name": "", "summary": "", "scope": "", "interaction": "",
             "pros": [""], "costs": [""]},
        ],
        "features": [
            {"id": "", "name": "", "description": "", "priority": "must"},
        ],
        "pages": [
            {"id": "", "name": "", "parent_id": None, "page_type": "custom", "features": []},
        ],
        "tech_constraints": {
            "framework": "", "component_lib": "", "data_source": "",
            "special_requirements": [""],
        },
        "data_entities": [{"name": "", "fields": [{"name": "", "type": "", "required": False}]}],
    }


async def _generate_profile(session: BrainstormSession, llm_fn: LLMFn | None) -> dict:
    # 7.6: 用户历史偏好注入议程播种 (首轮需求画像) — 作为约束, 不提问。
    user_content = f"用户需求描述：\n{session.requirement}"
    prefs = _load_user_preferences(session)
    if prefs:
        user_content += (
            "\n\n## 用户历史偏好（长期记忆, 作为约束优先遵循）\n"
            + json.dumps(prefs, ensure_ascii=False, indent=2)
        )
    raw = await _llm_structured(
        PROFILE_PROMPT,
        user_content,
        _profile_schema(),
        llm_fn,
    )
    session.agenda = [
        AgendaItem(
            id=a.get("id") or f"a{i + 1}",
            topic=a.get("topic") or f"模糊点{i + 1}",
            reason=a.get("reason", ""),
            impact=a.get("impact", "design"),
        )
        for i, a in enumerate(raw.get("ambiguities") or [])
    ]
    logger.info(
        "brainstorm_profile_generated",
        generation_id=session.generation_id,
        agenda_items=len(session.agenda),
        candidates=len(raw.get("candidate_plans") or []),
    )
    return raw


# ── Agenda helpers ──


def _impact_key(item: AgendaItem) -> tuple[int, str]:
    return (IMPACT_RANK.get(item.impact, 99), item.topic)


def coverage(session: BrainstormSession) -> float:
    """议程覆盖度 = 已答（含冲突）项 / 总项数.

    空议程返回 0.0：没有已确认的议程项时不得算作覆盖达标（否则首轮画像
    无模糊点会立刻通过覆盖度因子）。
    """
    if not session.agenda:
        return 0.0
    answered = sum(
        1 for a in session.agenda if a.status in (STATUS_ANSWERED, STATUS_CONFLICT)
    )
    return answered / len(session.agenda)


def _mark_assumed(session: BrainstormSession, item: AgendaItem) -> None:
    """未答项标 assumed，并写入假设清单（spec：用户未答项标记假设）."""
    item.status = STATUS_ASSUMED
    item.answer = ""
    session.assumptions = [
        a for a in session.assumptions if a.get("item_id") != item.id
    ]
    session.assumptions.append({
        "item_id": item.id,
        "topic": item.topic,
        "reason": item.reason,
        "impact": item.impact,
        "assumption": f"{item.topic}（用户未确认，暂按默认理解处理）",
        "status": STATUS_ASSUMED,
    })
    logger.info("brainstorm_item_assumed", item_id=item.id, topic=item.topic)


def _assume_stale(session: BrainstormSession) -> None:
    """把上一轮提问过、本轮仍未回答的项标记为 assumed（用户跳过了它们）."""
    for item in session.agenda:
        if item.status == STATUS_PENDING and item.id in session.prior_asked_ids:
            _mark_assumed(session, item)


def _find_option_match(session: BrainstormSession, text: str) -> AgendaItem | None:
    """返回命中选项的待答/假设项（点选或复述选项），无命中返回 None."""
    for a in session.agenda:
        if a.status in (STATUS_PENDING, STATUS_ASSUMED) and a.options:
            if any(opt and (text.startswith(opt) or opt in text) for opt in a.options):
                return a
    return None


def _has_pending(session: BrainstormSession) -> bool:
    return any(a.status == STATUS_PENDING for a in session.agenda)


def _apply_answer(
    session: BrainstormSession,
    text: str,
    item_id: str = "",
    item: AgendaItem | None = None,
) -> bool:
    """把用户本轮输入落到议程项上；返回是否落到了某个项。

    ``item`` 优先（调用方已用 ``_find_option_match`` 预匹配时传入，避免重复扫描）。
    """
    if not text:
        return False

    if item is None and item_id:
        item = next(
            (a for a in session.agenda
             if a.id == item_id and a.status
             in (STATUS_PENDING, STATUS_ASSUMED, STATUS_ANSWERED, STATUS_CONFLICT)),
            None,
        )
    if item is None:
        # 用户点选/输入与某已提问项的选项匹配 → 落到该项
        item = _find_option_match(session, text)
    if item is None:
        # 自由文本 → 回答第一个待答项（影响面优先）
        item = next(
            (a for a in sorted(session.agenda, key=_impact_key)
             if a.status == STATUS_PENDING),
            None,
        )
    if item is None:
        return False

    if item.status == STATUS_ANSWERED and item.answer != text:
        item.status = STATUS_CONFLICT      # 用户改口 → 冲突，最新答案为准
        logger.info("brainstorm_item_conflict", item_id=item.id, topic=item.topic)
    else:
        item.status = STATUS_ANSWERED
    item.answer = text
    # 已被假设的项被用户回答 → 从假设清单移除（用户纠正了假设）
    session.assumptions = [
        a for a in session.assumptions if a.get("item_id") != item.id
    ]
    _assume_stale(session)
    logger.info("brainstorm_item_answered", item_id=item.id, topic=item.topic)
    return True


def _is_confirm(text: str) -> bool:
    """用户显式确认收敛（确定性判定，不用 LLM 自评）.

    只匹配**整条消息**式的简短确认：≤8 字，且文本等于某个确认短语或以
    确认短语开头。普通回答中的"确认"字样（如"确认收货流程"）不命中——
    配合 turn() 的「有待答项时优先当作回答」规则，防止误收敛。
    """
    text = (text or "").strip()
    if not text or len(text) > 8:
        return False
    if text == "确认开始":
        return True  # 确认卡的显式选项
    return any(text == p or text.startswith(p) for p in CONFIRM_PHRASES)


def _looks_like_confirm_request(text: str) -> bool:
    """确认请求式疑问句（如「可以开始了吗」）→ 提示覆盖不足而非当作回答."""
    return bool(text) and text.endswith(("吗", "？", "?")) and _is_confirm(text)


# ── 3.3 每轮提问（按影响面排序选 1~3 个） ──

QUESTION_PROMPT = """你是 AI 生成流水线中的 Manager。基于当前澄清议程，为指定议程项生成提问。

每个提问需：
- 具体、可回答，带 2~4 个选项（也允许用户自由输入）
- 选项是中文短语，能直接作为答案理解

## 输出格式（只输出一个 JSON 对象）
{"questions": [{"item_id": "议程项id", "question": "问题", "options": ["选项A", "选项B"]}]}

## 规则
- 只对传入的待提问议程项生成问题，每项一条
- 问题要紧扣该议程项的 topic 与缺失后果（reason）"""


async def _question_round(session: BrainstormSession, llm_fn: LLMFn | None) -> list[dict]:
    """按影响面排序选 1~3 个未答议程项，LLM 生成问题，逐项输出 question_card."""
    pending = sorted(
        [a for a in session.agenda if a.status == STATUS_PENDING],
        key=_impact_key,
    )[:MAX_QUESTIONS_PER_ROUND]
    if not pending:
        # 无待答项但有假设项（覆盖不足）→ 针对假设项追问，让用户有机会纠正
        pending = sorted(
            [a for a in session.agenda if a.status == STATUS_ASSUMED],
            key=_impact_key,
        )[:MAX_QUESTIONS_PER_ROUND]
    if not pending:
        return []

    schema = {"questions": [{"item_id": "", "question": "", "options": [""]}]}
    items_text = "\n".join(
        f"- {a.id}: {a.topic}（缺失后果：{a.reason}，影响面：{a.impact}）"
        for a in pending
    )
    context = (
        f"当前议程（待提问）：\n{items_text}\n\n"
        f"已答议程：\n{_agenda_brief(session)}"
    )
    raw = await _llm_structured(QUESTION_PROMPT, context, schema, llm_fn)

    session.prior_asked_ids = list(session.last_asked_ids)
    session.last_asked_ids = []
    events: list[dict] = []
    for q in raw.get("questions") or []:
        item = next((a for a in session.agenda if a.id == q.get("item_id")), None)
        if item is None or item.status != STATUS_PENDING:
            continue
        item.question = q.get("question", "")
        item.options = [str(o) for o in (q.get("options") or []) if o]
        session.last_asked_ids.append(item.id)
        events.append(question_card_event(
            STAGE_ANALYSIS,
            q.get("question", item.topic),
            item.options,
            item_id=item.id,
        ))
        if len(events) >= MAX_QUESTIONS_PER_ROUND:
            break
    session.round += 1
    logger.info(
        "brainstorm_questions_emitted",
        generation_id=session.generation_id,
        count=len(events),
    )
    return events


def _agenda_brief(session: BrainstormSession) -> str:
    if not session.agenda:
        return "（无）"
    return "\n".join(
        f"- {a.id}: {a.topic} [{a.status}]" + (f" 答案：{a.answer}" if a.answer else "")
        for a in session.agenda
    )


# ── 3.4 方案对比卡片 ──

PROPOSAL_PROMPT = """你是 AI 生成流水线中的 Manager。澄清即将收敛，请基于需求画像与用户已确认的信息，生成 2~3 个候选方案供用户选择。

每个方案必须从两个维度描述：
- scope（范围取舍）：做什么/不做什么，功能边界取舍
- interaction（交互形态）：关键交互形态差异（如 单页向导 vs 多页列表；抽屉 vs 独立页）
并给出优点（pros）与代价（costs）。

## 输出格式（只输出一个 JSON 对象）
{"proposals": [{"name": "方案A", "scope": "...", "interaction": "...", "pros": ["..."], "costs": ["..."]}]}

## 规则
- 2~3 个方案，方案间差异显著（范围或交互形态层面）
- 用简洁专业的中文"""


async def _proposal_round(
    session: BrainstormSession,
    llm_fn: LLMFn | None,
    feedback: str = "",
) -> list[dict]:
    """收敛前输出方案对比卡片（2~3 候选方案 + 优点/代价 + 选项）.

    ``feedback``：用户对上一版方案的意见（fix #2）——非选项文本在方案对比
    悬而未决时视为方案反馈，带反馈重新生成方案，绝不落成议程答案。
    """
    _assume_stale(session)  # 进入方案对比前，仍未回答的已提问项 → 假设
    proposals = await _generate_proposals(session, llm_fn, feedback)
    session.proposals = proposals
    session.proposal_shown = True
    options = [p.get("name") or f"方案{i + 1}" for i, p in enumerate(proposals)]
    options += ["混合方案", "重新生成方案"]

    content_lines = ["请从以下候选方案中选择（可混合），或要求调整后重出："]
    if feedback:
        content_lines.append(f"\n（已根据你的反馈调整：{feedback}）")
    for i, p in enumerate(proposals):
        name = p.get("name") or f"方案{i + 1}"
        content_lines.append(
            f"\n### {name}\n"
            f"- 范围取舍：{p.get('scope', '')}\n"
            f"- 交互形态：{p.get('interaction', '')}\n"
            f"- 优点：{', '.join(p.get('pros') or [])}\n"
            f"- 代价：{', '.join(p.get('costs') or [])}"
        )
    ev = proposal_card_event(
        STAGE_ANALYSIS,
        "\n".join(content_lines),
        options,
    )
    ev["data"]["data"] = {"node": STAGE_ANALYSIS, "proposals": proposals}
    logger.info(
        "brainstorm_proposal_shown",
        generation_id=session.generation_id,
        count=len(proposals),
        feedback=bool(feedback),
    )
    return [ev]


async def _generate_proposals(
    session: BrainstormSession,
    llm_fn: LLMFn | None,
    feedback: str = "",
) -> list[dict]:
    schema = {"proposals": [
        {"name": "", "scope": "", "interaction": "", "pros": [""], "costs": [""]},
    ]}
    context = (
        f"需求画像：\n{json.dumps(session.profile or {}, ensure_ascii=False)}\n\n"
        f"议程（含答案）：\n{_agenda_brief(session)}\n\n"
        f"决策日志：\n{json.dumps(session.decisions, ensure_ascii=False)}"
    )
    if feedback:
        context += f"\n\n用户对上一版方案的反馈（请据此调整方案）：\n{feedback}"
    raw = await _llm_structured(PROPOSAL_PROMPT, context, schema, llm_fn)
    proposals = raw.get("proposals") or []
    for i, p in enumerate(proposals):
        if not p.get("name"):
            p["name"] = f"方案{chr(ord('A') + i)}"
    return proposals


def _is_exact_choice(name: str, text: str) -> bool:
    """方案选择判定：整句等于方案名（trim 尾标点后）。

    「方案A 但首页做简单点」这类带意见的文本**不是**选择——它是方案反馈
    （fix #2），不得提前落定选择。
    """
    norm = (text or "").strip().strip("。！!？?，,、 \t")
    return bool(name) and norm == name


async def _handle_proposal_choice(
    session: BrainstormSession,
    text: str,
    llm_fn: LLMFn | None,
) -> list[dict] | None:
    """处理用户在方案对比卡上的选择；不匹配时返回 None 走方案反馈路径."""
    text = (text or "").strip()
    if not text:
        return None

    # 重新生成方案
    if "重新生成" in text or "都不要" in text or "重出" in text:
        return await _proposal_round(session, llm_fn)

    # 混合方案
    if "混合" in text:
        _record_decision(session, "方案选型", "混合方案", text)
        session.proposal_decided = True
        _upsert_user_preference(session, "方案选型", "混合方案")
        return []

    # 匹配具体方案（整句选择，见 _is_exact_choice）
    for p in session.proposals:
        name = p.get("name", "")
        if _is_exact_choice(name, text):
            _record_decision(session, "方案选型", name, text)
            session.proposal_decided = True
            _upsert_user_preference(session, "方案选型", name)
            return []

    return None


def _record_decision(session: BrainstormSession, topic: str, choice: str, reason: str) -> None:
    session.decisions.append({
        "topic": topic,
        "choice": choice,
        "reason": reason,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "round": session.round,
    })
    logger.info("brainstorm_decision_recorded", topic=topic, choice=choice)


def _load_user_preferences(session: BrainstormSession) -> dict:
    """7.6 长期用户级记忆: 加载该用户的历史偏好 (fail-open)."""
    try:
        from .memory_db import get_memory_db

        return get_memory_db().get_preferences(session.user_id)
    except Exception as e:  # fail-open: 记忆不可用不阻塞澄清
        logger.warning("preferences_load_failed", user_id=session.user_id, error=str(e))
        return {}


def _upsert_user_preference(session: BrainstormSession, key: str, value: Any) -> None:
    """7.6 偏好写回 (用户在头脑风暴中的选择 → 长期记忆, fail-open)."""
    try:
        from .memory_db import get_memory_db

        get_memory_db().upsert_preference(session.user_id, key, value)
        logger.info("preference_upserted", user_id=session.user_id, key=key)
    except Exception as e:  # fail-open
        logger.warning("preference_upsert_failed", user_id=session.user_id, error=str(e))


# ── 3.5 双因子收敛 + 收敛产物 ──

TO_REQUIREMENTS_PROMPT = """你是 AI 生成流水线中的需求分析师。头脑风暴已收敛，请把澄清产物整理为结构化需求。

输入包含：需求画像、议程（含用户答案）、决策日志、假设清单。
请输出结构化需求规格（JSON），覆盖功能模块、页面结构、页面详情、技术约束与数据实体；未确认项按假设处理并如实保留在假设清单中。

## 输出格式（只输出一个 JSON 对象）
{
  "vision": {"project_name": "...", "target_users": [{"role": "...", "description": "..."}], "core_problem": "...", "success_criteria": ["..."], "scope_note": "..."},
  "features": [{"id": "F-01", "name": "...", "description": "...", "priority": "must|should|nice", "completeness": 100, "confirmed": true}],
  "pages": [{"id": "P-01", "name": "...", "parent_id": null, "page_type": "list|detail|form|dashboard|custom", "features": []}],
  "page_details": {"P-01": {"display_fields": [{"name": "...", "type": "text", "required": false}], "action_buttons": [{"label": "...", "type": "custom"}], "related_data": [], "layout_notes": ""}},
  "tech_constraints": {"framework": "vue3", "component_lib": "element-plus", "data_source": "", "special_requirements": []},
  "data_entities": [{"name": "...", "fields": [{"name": "...", "type": "string", "required": false}]}]
}

## 规则
- 与议程中用户答案一致，不得臆造
- 用简洁专业的中文"""


def _to_requirements_schema() -> dict:
    return {
        "vision": {
            "project_name": "", "core_problem": "",
            "target_users": [{"role": "", "description": ""}],
            "success_criteria": [""], "scope_note": "",
        },
        "features": [{
            "id": "", "name": "", "description": "", "priority": "must",
            "completeness": 100, "confirmed": True,
        }],
        "pages": [{"id": "", "name": "", "parent_id": None, "page_type": "custom", "features": []}],
        "page_details": {},
        "tech_constraints": {
            "framework": "", "component_lib": "", "data_source": "",
            "special_requirements": [],
        },
        "data_entities": [{"name": "", "fields": [{"name": "", "type": "", "required": False}]}],
    }


def _build_requirements_state(session: BrainstormSession, raw: dict) -> RequirementsState:
    """把 LLM 整理出的结构化需求映射回 RequirementsState dataclass（复用 requirements/state.py）."""
    rs = RequirementsState(
        session_id=session.generation_id,
        mode="new",
        version=1,
        layer=3,
        layer_status={"1": "done", "2": "done", "3": "done"},
    )

    v = raw.get("vision") or {}
    rs.vision = VisionData(
        project_name=v.get("project_name", ""),
        target_users=[
            TargetUser(role=u.get("role", ""), description=u.get("description", ""))
            for u in (v.get("target_users") or [])
        ],
        core_problem=v.get("core_problem", ""),
        success_criteria=list(v.get("success_criteria") or []),
        scope_note=v.get("scope_note", ""),
    )
    rs.features = [
        FeatureModule(
            id=f.get("id", f"F-{i + 1:02d}"),
            name=f.get("name", ""),
            description=f.get("description", ""),
            priority=f.get("priority", "must"),
            completeness=int(f.get("completeness", 100) or 100),
            confirmed=bool(f.get("confirmed", True)),
        )
        for i, f in enumerate(raw.get("features") or [])
    ]
    rs.pages = [
        PageNode(
            id=p.get("id", f"P-{i + 1:02d}"),
            name=p.get("name", ""),
            parent_id=p.get("parent_id"),
            page_type=p.get("page_type", "custom"),
            features=list(p.get("features") or []),
        )
        for i, p in enumerate(raw.get("pages") or [])
    ]
    for pid, pd in (raw.get("page_details") or {}).items():
        rs.page_details[pid] = PageDetail(
            display_fields=[
                FieldDef(name=f.get("name", ""), type=f.get("type", "text"),
                         required=bool(f.get("required", False)))
                for f in (pd.get("display_fields") or [])
            ],
            action_buttons=[
                ActionDef(label=a.get("label", ""), type=a.get("type", "custom"))
                for a in (pd.get("action_buttons") or [])
            ],
            related_data=list(pd.get("related_data") or []),
            layout_notes=pd.get("layout_notes", ""),
        )
    tc = raw.get("tech_constraints") or {}
    rs.tech_constraints = TechConstraints(
        framework=tc.get("framework", ""),
        component_lib=tc.get("component_lib", ""),
        data_source=tc.get("data_source", ""),
        special_requirements=list(tc.get("special_requirements") or []),
    )
    rs.data_entities = [
        DataEntity(name=de.get("name", ""), fields=list(de.get("fields") or []))
        for de in (raw.get("data_entities") or [])
    ]
    return rs


async def to_requirements_state_json(
    session: BrainstormSession,
    llm_fn: LLMFn | None = None,
) -> str:
    """收敛产物：结构化需求（RequirementsState JSON，复用 requirements/state.py dataclasses）."""
    raw = await _llm_structured(
        TO_REQUIREMENTS_PROMPT,
        "需求画像：\n"
        + json.dumps(session.profile or {}, ensure_ascii=False)
        + "\n\n议程（含答案）：\n" + _agenda_brief(session)
        + "\n\n决策日志：\n" + json.dumps(session.decisions, ensure_ascii=False)
        + "\n\n假设清单：\n" + json.dumps(session.assumptions, ensure_ascii=False),
        _to_requirements_schema(),
        llm_fn,
    )
    try:
        rs = _build_requirements_state(session, raw)
    except Exception as e:  # fail-safe：LLM 结构化失败时不阻塞收敛
        logger.warning("brainstorm_requirements_build_failed", error=str(e))
        rs = _fallback_requirements_state(session)
    _enrich_from_profile(rs, session)
    state_json = rs.to_json()
    logger.info(
        "brainstorm_requirements_state_built",
        generation_id=session.generation_id,
        features=len(rs.features),
        pages=len(rs.pages),
    )
    return state_json


def _enrich_from_profile(rs: RequirementsState, session: BrainstormSession) -> None:
    """LLM 结构化结果为空/失败时，用需求画像中的字段兜底（不阻塞流水线）."""
    if not session.profile:
        return
    profile_state = _fallback_requirements_state(session)
    if not rs.vision.project_name and profile_state.vision.project_name:
        rs.vision = profile_state.vision
    if not rs.features:
        rs.features = profile_state.features
    if not rs.pages:
        rs.pages = profile_state.pages
    if not rs.data_entities:
        rs.data_entities = profile_state.data_entities
    if not rs.tech_constraints.framework:
        rs.tech_constraints = profile_state.tech_constraints


def _fallback_requirements_state(session: BrainstormSession) -> RequirementsState:
    """降级：仅用需求画像中的字段构造最小结构化状态（不阻塞流水线）."""
    profile = session.profile or {}
    rs = RequirementsState(
        session_id=session.generation_id,
        mode="new",
        version=1,
        layer=3,
        layer_status={"1": "done", "2": "done", "3": "done"},
    )
    rs.vision = VisionData(
        project_name=profile.get("project_name", ""),
        target_users=[
            TargetUser(role=u.get("role", ""), description=u.get("description", ""))
            for u in (profile.get("target_users") or [])
        ],
        core_problem=profile.get("core_problem", ""),
        success_criteria=list(profile.get("success_criteria") or []),
        scope_note=profile.get("scope_note", ""),
    )
    rs.features = [
        FeatureModule(
            id=f.get("id", f"F-{i + 1:02d}"),
            name=f.get("name", ""),
            description=f.get("description", ""),
            priority=f.get("priority", "must"),
            completeness=100,
            confirmed=True,
        )
        for i, f in enumerate(profile.get("features") or [])
    ]
    rs.pages = [
        PageNode(
            id=p.get("id", f"P-{i + 1:02d}"),
            name=p.get("name", ""),
            parent_id=p.get("parent_id"),
            page_type=p.get("page_type", "custom"),
            features=list(p.get("features") or []),
        )
        for i, p in enumerate(profile.get("pages") or [])
    ]
    tc = profile.get("tech_constraints") or {}
    rs.tech_constraints = TechConstraints(
        framework=tc.get("framework", ""),
        component_lib=tc.get("component_lib", ""),
        data_source=tc.get("data_source", ""),
        special_requirements=list(tc.get("special_requirements") or []),
    )
    rs.data_entities = [
        DataEntity(name=de.get("name", ""), fields=list(de.get("fields") or []))
        for de in (profile.get("data_entities") or [])
    ]
    return rs


# ── Main turn entry ──


async def turn(
    session: BrainstormSession,
    text: str = "",
    item_id: str = "",
    llm_fn: LLMFn | None = None,
    provider: Any | None = None,
) -> dict:
    """跑一轮头脑风暴，返回 Manager 消息事件列表 + 收敛状态.

    ``llm_fn`` — LLM 调用注入点（测试用 fake）；``provider`` — 显式 LLM
    provider 实例（与 ``classify_intent`` 同模式：不触碰共享单例，避免并发
    graph 流式过程中被换掉）。两者都缺省时回退到 ``_llm_generate`` 单例。

    Returns:
        {
          "generation_id": str,
          "events": [manager_message 事件 dict, ...],
          "converged": bool,
          "coverage": float,
          "requirements_state_json": str | None,
        }
    """
    events: list[dict] = []
    text = (text or "").strip()
    if llm_fn is None and provider is not None:
        llm_fn = _provider_llm_fn(provider)

    # 1) 首轮：需求画像（不提问，3.2）
    if session.round == 0 and session.profile is None:
        session.requirement = text
        session.profile = await _generate_profile(session, llm_fn)
        session.round = 1
        events.append(_profile_card(session))
        return _result(session, events)

    # 2) 待决方案选择（3.4）：用户正对着方案对比卡做选择
    if session.proposal_shown and not session.proposal_decided:
        choice_events = await _handle_proposal_choice(session, text, llm_fn)
        if choice_events is not None:
            events.extend(choice_events)
            if not session.proposal_decided:
                return _result(session, events)
            # 选择文本不当作议程答案（例如「方案A」不能被落成某议程项的回答）
            text = ""
        # 选择落定（decision 已记录）→ 继续走收敛判定；不匹配 → 落到方案反馈

    # 3) 用户输入分流（3.1/3.3）。
    #    优先级：卡片 item_id → 选项复述 → 确认卡选项 → 方案反馈（fix #2）
    #    → 有待答项时优先当作回答（fix #1：普通回答里的"确认"字样不误收敛）
    #    → 短整句确认（fix #1：≤8 字且等于/以确认短语开头）。
    confirm_requested = False
    proposal_feedback = None
    want_more_questions = False
    if text:
        if item_id:
            # 问题卡选项点击：精确落回议程项
            _apply_answer(session, text, item_id)
        else:
            matched = _find_option_match(session, text)
            if matched is not None:
                # 复述/点选已提问项的选项 → 回答（不重复扫描选项，fix #11）
                _apply_answer(session, text, item=matched)
            elif text == "确认开始":
                confirm_requested = True          # 确认卡显式选项（无论是否有待答项）
            elif text == "还有疑问":
                want_more_questions = True        # 确认卡"还有疑问" → 走提问轮
            elif session.proposal_shown and not session.proposal_decided:
                # 方案对比悬而未决：非选项文本 = 方案反馈（绝不落成议程答案，fix #2）
                proposal_feedback = text
            elif _has_pending(session):
                if _looks_like_confirm_request(text):
                    confirm_requested = True      # 「可以开始了吗」→ 覆盖不足提示
                else:
                    _apply_answer(session, text)  # 有待答项 → 优先当作回答
            elif _is_confirm(text):
                confirm_requested = True          # 无待答项 + 短整句确认
            else:
                _apply_answer(session, text)      # 无待答项的自由文本 → 尝试落项

    # 4) 用户显式确认（双因子之一）
    if confirm_requested:
        if session.proposal_decided and coverage(session) >= COVERAGE_THRESHOLD:
            session.user_confirmed = True
        elif coverage(session) >= COVERAGE_THRESHOLD:
            # 覆盖达标但方案未选定 → 真实阻塞点是方案选型（fix #10）
            events.append(_coverage_insufficient_card(session, blocker="proposal"))
        else:
            # 覆盖不足（spec：覆盖不足不收敛）→ 提示剩余关键议程项并继续澄清
            events.append(_coverage_insufficient_card(session, blocker="coverage"))

    # 4b) 方案反馈（fix #2）：带反馈重出方案对比
    if proposal_feedback:
        events.extend(await _proposal_round(session, llm_fn, feedback=proposal_feedback))
        return _result(session, events)

    # 5) 收敛判定（3.5：覆盖度 + 用户确认，双因子）
    if session.proposal_decided:
        if session.user_confirmed:
            session.converged = True
            if session.requirements_state_json is None:
                session.requirements_state_json = await to_requirements_state_json(
                    session, llm_fn
                )
            events.append(_converged_card(session))
            return _result(session, events)
        if coverage(session) >= COVERAGE_THRESHOLD and not want_more_questions:
            events.append(confirm_card_event(
                STAGE_ANALYSIS,
                "需求澄清已基本收敛，准备生成需求规格文档？",
                ["确认开始", "还有疑问"],
            ))
            return _result(session, events)

    # 6) 覆盖达标 → 方案对比（收敛前最后一轮；方案对比缺席时不得收敛）
    if coverage(session) >= COVERAGE_THRESHOLD and not session.proposal_shown:
        events.extend(await _proposal_round(session, llm_fn))
        return _result(session, events)

    # 7) 默认：按影响面排序提问 1~3 项（3.3）
    question_events = await _question_round(session, llm_fn)
    if question_events:
        events.extend(question_events)
    elif not events:
        # 无更多可问项且无事发生 → 给用户一个可读的反馈（fix #10：方案未定说方案）
        if session.proposal_shown and not session.proposal_decided:
            events.append(summary_card_event(
                STAGE_ANALYSIS,
                "请从候选方案中选择其一（或指定混合 / 要求调整后重出）。",
            ))
        else:
            events.append(summary_card_event(
                STAGE_ANALYSIS,
                f"已记录你的回答。当前议程覆盖度 {coverage(session):.0%}"
                f"（阈值 {COVERAGE_THRESHOLD:.0%}）。",
            ))
    return _result(session, events)


def _result(session: BrainstormSession, events: list[dict]) -> dict:
    return {
        "generation_id": session.generation_id,
        "events": events,
        "converged": session.converged,
        "coverage": coverage(session),
        "requirements_state_json": session.requirements_state_json,
    }
