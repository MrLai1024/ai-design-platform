"""复杂度分档 (task 5.1) — rule-based, zero-LLM S/M/L assessment.

D6: 功能实现节点按设计复杂度自适应角色配置. This module owns the
deterministic (轻量判断, no LLM) tier assessment:

- ``assess_complexity(spec, design_doc) -> "S" | "M" | "L"`` — the public,
  documented entry point.
- ``assess_complexity_detail(spec, design_doc) -> (tier, reasons)`` — same
  judgment plus the human-readable reason list, used by the graph to emit the
  ``tier_assessed`` event (``data={tier, reasons}``) so the frontend can show
  the tier without re-deriving it.
- ``TIER_ACCEPTANCE`` — per-tier role configuration (D6 table) + the
  task-level acceptance criteria shared by every tier (编译通过 / 契约一致).
- ``build_code_dispatch_contract(tier, has_spec)`` — the code-phase dispatch
  contract (D3 shape, task_id="code") with the tier + role config baked in.

判定线索 (D6 table): 页面数 / 数据实体 / 权限, plus the Spec structure
signals the Planner consumes (directory_tree → 模块数, api_contracts → API 层).

Rules (priority order, documented — the Spec is the primary source; the design
doc is a keyword-based fallback for legacy states without a Spec):

1. L — 多模块 / 权限 / API 层: any ``routing`` entry with ``auth: true``
   (or 权限 mentions in the doc), OR ≥ ``API_LAYER_THRESHOLD`` meaningful
   api_contracts entries, OR ≥ ``MODULE_THRESHOLD`` directories in
   directory_tree.
2. M — 多页面 / 数据流 / 状态管理: page count > ``PAGE_THRESHOLD``, OR
   data_model entities > ``ENTITY_THRESHOLD``, OR state_management declares
   real stores (data flow), OR 状态管理/数据流 keywords in the doc.
3. S — ≤ 3 pages, no auth, no API layer (simple form).

A Spec that is present but schema-placeholder (all-empty entries, e.g. the
structured-parse fallback) is treated as absent and the design doc is used.
"""

from __future__ import annotations

import re

TIERS = ("S", "M", "L")

# Judgment thresholds (documented in the module docstring).
PAGE_THRESHOLD = 3          # S ≤ 3 pages; M > 3 (多页面)
ENTITY_THRESHOLD = 3        # M when > 3 data entities
API_LAYER_THRESHOLD = 3     # L when ≥ 3 meaningful api_contracts entries (API 层)
MODULE_THRESHOLD = 4        # L when ≥ 4 directories in directory_tree (多模块)

# D6: per-tier role configuration + acceptance criteria.
TIER_ACCEPTANCE: dict[str, dict] = {
    "S": {
        "roles": ["planner", "executor"],
        "acceptance_criteria": ["编译通过", "契约一致"],
    },
    "M": {
        "roles": ["planner", "executor", "verifier"],
        "acceptance_criteria": ["编译通过", "契约一致"],
    },
    "L": {
        "roles": ["planner", "executor", "verifier", "debugger", "tester"],
        "acceptance_criteria": ["编译通过", "契约一致"],
    },
}

# Design-doc fallback keywords (legacy path, no Spec present).
_AUTH_RE = re.compile(r"权限|权限控制|rbac|auth|登录态", re.IGNORECASE)
_API_RE = re.compile(r"api[层]|接口层|axios|后端接口|服务端接口|restful", re.IGNORECASE)
_STATE_RE = re.compile(r"状态管理|数据流|pinia|vuex", re.IGNORECASE)
_MODULE_RE = re.compile(r"多模块|模块化|多个模块|微应用", re.IGNORECASE)
# Page-name proxy: "X页" tokens (登录页/首页/列表页…) excluding 页面/页码/分页/
# 每页 and pagination-navigation tokens (上一页/下一页/子页) so pagination
# mentions don't inflate page_count → spurious M.
_PAGE_TOKEN_RE = re.compile(r"([一-龥A-Za-z]{1,8}页)")
_PAGE_STOPLIST = {
    "页面", "页面结构", "页码", "分页", "每页", "一页", "该页", "本页",
    "上一页", "下一页", "子页",
}


# ── Spec-derived signals ──


def _meaningful(entries: list) -> list:
    """Filter schema-placeholder entries (empty name) out of a spec list."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("id") or entry.get("path") or ""
        if isinstance(name, str) and name.strip():
            out.append(entry)
    return out


def _spec_signals(spec: dict) -> tuple[dict, bool]:
    """Extract numeric/boolean signals from the Spec.

    Returns (signals, usable) — ``usable`` is False when the Spec is entirely
    schema-placeholder (e.g. the structured-parse fallback), meaning the
    caller should fall back to the design doc.
    """
    pages = _meaningful(spec.get("pages", []))
    entities = _meaningful(spec.get("data_model", []))
    api_contracts = _meaningful(spec.get("api_contracts", []))
    directory_tree = spec.get("directory_tree") or {}
    routing = spec.get("routing") or []
    state_mgmt = spec.get("state_management") or {}

    auth = any(
        isinstance(r, dict) and r.get("auth") is True
        for r in routing
        if isinstance(r, dict)
    )
    # state_mgmt counts actual store modules only (D5 requires the field
    # non-empty, so the bare framework name must not trigger M on its own).
    stores = [s for s in (state_mgmt.get("stores") or []) if isinstance(s, str) and s.strip()]
    state_mgmt_real = bool(stores)

    signals = {
        "page_count": len(pages),
        "entity_count": len(entities),
        "api_count": len(api_contracts),
        # 已知启发式局限：module_count 仅统计 directory_tree 的顶层目录数，
        # 不展开子目录深度（足够区分单模块/多模块）。
        "module_count": len(directory_tree),
        "auth": auth,
        "state_mgmt": state_mgmt_real,
    }
    usable = (
        bool(pages)
        or bool(entities)
        or bool(api_contracts)
        or bool(directory_tree)
        or any(isinstance(r, dict) and (r.get("path") or "") for r in routing)
    )
    return signals, usable


# ── Design-doc fallback signals ──


def _doc_signals(design_doc: str) -> dict:
    text = design_doc or ""
    lower = text.lower()
    page_tokens = {
        m.group(1)
        for m in _PAGE_TOKEN_RE.finditer(text)
        if m.group(1) not in _PAGE_STOPLIST and m.group(1) != "页面"
    }
    return {
        "page_count": len(page_tokens),
        "entity_count": 0,   # not reliably countable from a free-form doc
        "api_count": 0,
        "module_count": 0,
        "auth": bool(_AUTH_RE.search(lower)),
        "state_mgmt": bool(_STATE_RE.search(lower)),
        "_doc_api_layer": bool(_API_RE.search(lower)),
        "_doc_multi_module": bool(_MODULE_RE.search(lower)),
    }


# ── Assessment ──


def assess_complexity_detail(spec: dict | None, design_doc: str) -> tuple[str, list[str]]:
    """S/M/L judgment with reasons (the graph's tier event source)."""
    signals: dict = {}
    if spec:
        signals, usable = _spec_signals(spec)
        if not usable:
            # 占位 Spec 正常不会出现：phase 2 的 Manager L1 把关会拦截字段
            # 不全的设计产物；此处回退仅防御异常路径。
            signals = _doc_signals(design_doc)
            source = "design_doc (Spec 为空占位，回退)"
        else:
            source = "architecture_spec"
    else:
        signals = _doc_signals(design_doc)
        source = "design_doc (无 Spec，回退)"

    reasons: list[str] = []

    # L — 多模块 / 权限 / API 层
    if signals.get("auth"):
        reasons.append("存在权限/登录态要求")
    if signals.get("api_count", 0) >= API_LAYER_THRESHOLD:
        reasons.append(f"api_contracts 含 {signals['api_count']} 个接口（API 层）")
    if signals.get("module_count", 0) >= MODULE_THRESHOLD:
        reasons.append(f"directory_tree 含 {signals['module_count']} 个目录（多模块）")
    if signals.get("_doc_multi_module"):
        reasons.append("设计文档提及多模块")
    if signals.get("_doc_api_layer"):
        reasons.append("设计文档提及 API 层")
    if reasons:
        return "L", [f"[{source}]"] + reasons

    # M — 多页面 / 数据流 / 状态管理
    if signals.get("page_count", 0) > PAGE_THRESHOLD:
        reasons.append(f"页面数 {signals['page_count']} > {PAGE_THRESHOLD}（多页面）")
    if signals.get("entity_count", 0) > ENTITY_THRESHOLD:
        reasons.append(f"数据实体 {signals['entity_count']} 个（数据模型复杂）")
    if signals.get("state_mgmt"):
        reasons.append("存在数据流/状态管理")
    if reasons:
        return "M", [f"[{source}]"] + reasons

    return "S", [f"[{source}] 页面数 ≤ {PAGE_THRESHOLD}、无权限与 API 层线索（简单表单）"]


def assess_complexity(spec: dict | None, design_doc: str) -> str:
    """Public entry point (task 5.1): S/M/L from the Spec, design-doc fallback."""
    tier, _ = assess_complexity_detail(spec, design_doc)
    return tier


# ── Code-phase dispatch contract (D3 shape, task_id="code") ──


def build_code_dispatch_contract(tier: str, has_spec: bool) -> dict:
    """5.1: the code phase's dispatch contract with the tier + roles baked in.

    Shape mirrors DESIGN_DISPATCH_CONTRACT (state.py) plus ``tier`` and
    ``roles`` (D6 角色配置进 dispatch). ``input_ref`` points at the Spec when
    present, otherwise at the design doc (legacy).
    """
    tier = tier if tier in TIER_ACCEPTANCE else "S"
    return {
        "task_id": "code",
        "input_ref": "architecture_spec" if has_spec else "design_result",
        "acceptance_criteria": list(TIER_ACCEPTANCE[tier]["acceptance_criteria"]),
        "tool_bounds": [],
        "constraints": [],
        "tier": tier,
        "roles": list(TIER_ACCEPTANCE[tier]["roles"]),
    }
