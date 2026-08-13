"""Workflow IR types — the JSON-based contract between frontend canvas and backend executor.

Defines dataclasses for:
- WorkflowIR: top-level workflow object
- NodeDef: individual node with typed config
- EdgeDef: connection between nodes
- WorkflowSchema: input/output schema and state variables
- LLMNodeConfig, RouterNodeConfig (RouterBranch), HumanConfirmNodeConfig
  (HumanConfirmField), CodeNodeConfig: per-node-type configuration
- resolve_template(): replaces {state.xxx} placeholders with state values
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{state\.([\w.]+)\}")


def resolve_template(template: str, state: dict[str, Any]) -> str:
    """Replace {state.xxx} placeholders with values from state dict.

    Supports dotted keys like {state.result.text}.
    Missing keys are left as-is (placeholder not replaced).
    Non-string values are stringified via str().
    """

    def _replace(match: re.Match) -> str:
        key_path = match.group(1)
        keys = key_path.split(".")
        value: Any = state
        try:
            for k in keys:
                value = value[k]
            return str(value)
        except (KeyError, TypeError):
            return match.group(0)  # keep the original placeholder

    return _TEMPLATE_RE.sub(_replace, template)


# ---------------------------------------------------------------------------
# Per-node-type config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LLMNodeConfig:
    """Configuration for an LLM call node."""

    model: str = "deepseek-v4-pro"
    system_prompt: str = ""
    user_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    output_key: str = "output"


@dataclass
class RouterBranch:
    """A single branch in a router node."""

    label: str
    condition: str  # Python expression, or "default" for the fallback branch


@dataclass
class RouterNodeConfig:
    """Configuration for a conditional routing node."""

    branches: list[dict | RouterBranch] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.branches = [
            RouterBranch(**b) if isinstance(b, dict) else b
            for b in self.branches
        ]


@dataclass
class HumanConfirmField:
    """A single field in a human confirmation form."""

    key: str
    label: str
    type: str = "text"  # "text", "textarea", "boolean", "select", etc.
    required: bool = True


@dataclass
class HumanConfirmNodeConfig:
    """Configuration for a human-in-the-loop confirmation node."""

    message: str = ""
    fields: list[dict | HumanConfirmField] = field(default_factory=list)
    timeout: int = 300  # seconds

    def __post_init__(self) -> None:
        self.fields = [
            HumanConfirmField(**f) if isinstance(f, dict) else f
            for f in self.fields
        ]


@dataclass
class CodeNodeConfig:
    """Configuration for a code execution node."""

    language: str = "python"
    code: str = ""
    timeout: int = 30  # seconds
    output_key: str = "code_output"


# ---------------------------------------------------------------------------
# Node and edge definitions
# ---------------------------------------------------------------------------


@dataclass
class NodeDef:
    """A single node in a workflow graph."""

    id: str
    type: str  # "llm" | "router" | "human_confirm" | "code"
    label: str
    position: dict[str, float]
    config: (
        dict | LLMNodeConfig | RouterNodeConfig | HumanConfirmNodeConfig | CodeNodeConfig
    ) = field(default_factory=dict)

    _TYPE_MAP: ClassVar[dict[str, type]] = {
        "llm": LLMNodeConfig,
        "router": RouterNodeConfig,
        "human_confirm": HumanConfirmNodeConfig,
        "code": CodeNodeConfig,
    }

    def __post_init__(self) -> None:
        if isinstance(self.config, dict):
            config_cls = self._TYPE_MAP.get(self.type)
            if config_cls is not None:
                self.config = config_cls(**self.config)


@dataclass
class EdgeDef:
    """A directed edge connecting two nodes in a workflow."""

    id: str
    source: str
    target: str
    condition: str | None = None


# ---------------------------------------------------------------------------
# Workflow schema
# ---------------------------------------------------------------------------


@dataclass
class WorkflowSchema:
    """Schema definition for workflow input/output and state variables."""

    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    state_variables: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Workflow IR (top-level)
# ---------------------------------------------------------------------------


@dataclass
class WorkflowIR:
    """Top-level workflow intermediate representation.

    This is the JSON-based contract between the React frontend (workflow canvas)
    and the Python backend (LangGraph executor).

    Usage:
        # From JSON
        wf = WorkflowIR.from_dict(json.loads(raw_json))

        # Back to JSON
        raw_json = json.dumps(wf.to_dict())
    """

    id: str
    name: str
    version: str = "1.0"
    description: str = ""
    schema: dict | WorkflowSchema = field(default_factory=dict)
    nodes: list[dict | NodeDef] = field(default_factory=list)
    edges: list[dict | EdgeDef] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Convert schema dict to WorkflowSchema
        if isinstance(self.schema, dict):
            self.schema = WorkflowSchema(**self.schema)

        # Convert node dicts to NodeDef objects
        self.nodes = [
            NodeDef(**n) if isinstance(n, dict) else n for n in self.nodes
        ]

        # Convert edge dicts to EdgeDef objects
        self.edges = [
            EdgeDef(**e) if isinstance(e, dict) else e for e in self.edges
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize this WorkflowIR back to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "schema": asdict(self.schema),
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WorkflowIR":
        """Create a WorkflowIR from a JSON-parsed dict.

        All nested dicts (schema, nodes, edges) are recursively parsed into
        their typed dataclass representations.
        """
        return WorkflowIR(
            id=data["id"],
            name=data["name"],
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            schema=data.get("schema", {}),
            nodes=data.get("nodes", []),
            edges=data.get("edges", []),
        )
