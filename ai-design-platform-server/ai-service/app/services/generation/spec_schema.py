"""Architecture Spec schema — the design node's machine-readable output contract.

The Spec is the shared contract of the implementation chain: the Planner's
decomposition input, the Executor's design reference and the compile
verification baseline. This module owns:

- ``ARCHITECTURE_SPEC_SCHEMA`` — the 定稿 schema (dict-based reference).
- ``validate_spec`` — deterministic field-completeness validation (zero-LLM).
- ``empty_spec`` — schema-shaped empty defaults, doubles as the merge schema
  for structured-LLM parse fallback (type-coercing, never crashes).
- ``ARCHITECTURE_SPEC_PROMPT`` — the design node's structured-LLM prompt.

The module is pure stdlib (no intra-package imports) so every consumer can
import it without import cycles.

Source: adapted from the agent-orchestration refactor (origin/feature/ai
17d50d1 spec_schema.py); memory-delegation parts are out of scope for this
change (project persistence lands with the project-root migration).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger()

SPEC_VERSION = 1

# Required non-empty fields: spec_version + 9 business fields.
REQUIRED_SPEC_FIELDS = (
    "spec_version",
    "tech_stack",
    "directory_tree",
    "data_model",
    "api_contracts",
    "routing",
    "state_management",
    "component_tree",
    "pages",
    "decisions",
)

# Per-field expected container types (wrong type → "invalid" validation error).
SPEC_FIELD_TYPES: dict[str, type] = {
    "tech_stack": dict,
    "directory_tree": dict,
    "data_model": list,
    "api_contracts": list,
    "routing": list,
    "state_management": dict,
    "component_tree": list,
    "pages": list,
    "decisions": list,
}


# ── Schema (定稿) ──


ARCHITECTURE_SPEC_SCHEMA: dict = {
    "spec_version": 1,
    "tech_stack": {
        "framework": "vue3",
        "component_lib": "element-plus",
        "build": "webpack",
        "style": "scss",
    },
    "directory_tree": {
        "src/": ["main.ts", "App.vue", "router/", "components/", "stores/", "api/"],
    },
    "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
    "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
    "routing": [{"path": "/", "page": "Home", "auth": False}],
    "state_management": {"store": "pinia", "stores": ["user", "cart"]},
    "component_tree": [{"name": "Header", "uses": ["NavMenu"], "props": []}],
    "pages": [{"id": "p-01", "name": "登录页", "interactions": [], "data": []}],
    "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
}

ARCHITECTURE_SPEC_PROMPT = """你是 AI 生成流水线中的资深前端架构师。根据需求分析文档（PRD）与设计方案文档，输出一份机器可读的架构 Spec（JSON）——它是后续功能实现（Planner 拆解）与验证的唯一工程输入。

## 输出要求（只输出一个 JSON 对象，不要 Markdown 代码块、不要其他内容）
{
  "spec_version": 1,
  "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "webpack", "style": "scss"},
  "directory_tree": {"src/": ["main.ts", "App.vue", "router/", "components/", "stores/", "api/"]},
  "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
  "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
  "routing": [{"path": "/", "page": "Home", "auth": false}],
  "state_management": {"store": "pinia", "stores": ["user", "cart"]},
  "component_tree": [{"name": "Header", "uses": ["NavMenu"], "props": []}],
  "pages": [{"id": "p-01", "name": "登录页", "interactions": [], "data": []}],
  "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}]
}

## 规则
- 9 个业务字段全部必须非空：tech_stack / directory_tree / data_model / api_contracts / routing / state_management / component_tree / pages / decisions —— 空对象、空数组、空字符串均不合格
- tech_stack、state_management、directory_tree 必须是对象（directory_tree：目录 → 该目录下的文件/子目录清单）；其余业务字段必须是数组
- data_model / api_contracts / routing / component_tree / pages 必须与 PRD 功能模块及设计文档一一对应，不得遗漏设计文档中定义的功能点、页面与数据实体
- 文件路径（directory_tree 与后续 pages/组件归属）必须落在 src/ 内；页面 id 用 p-01 风格
- decisions 记录关键技术选型及理由；设计文档中已确认的方案选择必须原样写入（后续节点不得推翻）
- 用简洁专业的中文"""


# ── Validation (deterministic, zero-LLM) ──


def _is_empty(value: Any) -> bool:
    """None / empty str / empty list / empty dict / falsy scalar → empty."""
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) == 0
    return not bool(value)  # 0 / 0.0 / False


def validate_spec(spec: Any) -> list[str]:
    """Completeness validation: every required field present, non-empty, and
    of the expected container type.

    Returns a list of human-readable problems; an empty list means the Spec
    passes. Deterministic, zero-LLM.
    """
    if not isinstance(spec, dict) or not spec:
        return ["架构 Spec 为空"]

    problems: list[str] = []
    for field in REQUIRED_SPEC_FIELDS:
        value = spec.get(field)
        if _is_empty(value):
            problems.append(f"字段 {field} 缺失或为空")
            continue
        if field == "spec_version":
            # bool is an int subclass — reject it explicitly.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append("字段 spec_version 类型不合法（期望数字）")
        else:
            expected = SPEC_FIELD_TYPES[field]
            if not isinstance(value, expected):
                problems.append(f"字段 {field} 类型不合法（期望 {expected.__name__}）")
    return problems


# ── Empty-schema defaults (structured-parse fallback) ──


def empty_spec() -> dict:
    """Schema-shaped empty Spec — doubles as the merge schema for structured
    LLM parse fallback: missing keys take empty defaults and wrong-typed values
    are coerced (never crashes on valid-JSON/wrong-type LLM output).

    ``directory_tree`` is an empty dict on purpose: in merge semantics an empty
    dict means "dynamic map" (dir → file list), so a parsed dict passes through.
    """
    return {
        "spec_version": SPEC_VERSION,
        "tech_stack": {"framework": "", "component_lib": "", "build": "", "style": ""},
        "directory_tree": {},
        "data_model": [{"name": "", "fields": [{"name": "", "type": ""}]}],
        "api_contracts": [{"name": "", "method": "GET", "request": {}, "response": {}}],
        "routing": [{"path": "", "page": "", "auth": False}],
        "state_management": {"store": "", "stores": [""]},
        "component_tree": [{"name": "", "uses": [""], "props": [""]}],
        "pages": [{"id": "", "name": "", "interactions": [""], "data": [""]}],
        "decisions": [{"topic": "", "choice": "", "reason": ""}],
    }


def merge_into_spec(parsed: Any) -> dict:
    """Merge an LLM-parsed JSON value into the schema shape.

    Type-coercing, never crashes: wrong-typed or missing keys take the
    schema-shaped empty defaults; valid dict/list values pass through.
    """
    base = empty_spec()
    if not isinstance(parsed, dict):
        return base
    for field in REQUIRED_SPEC_FIELDS:
        value = parsed.get(field)
        if value is None:
            continue
        if field == "spec_version":
            base[field] = value
        else:
            expected = SPEC_FIELD_TYPES[field]
            if isinstance(value, expected):
                base[field] = value
    return base


def spec_to_json(spec: dict) -> str:
    """Serialize a Spec to pretty JSON (frontend/planner/worker consumption)."""
    return json.dumps(spec, ensure_ascii=False, indent=2)
