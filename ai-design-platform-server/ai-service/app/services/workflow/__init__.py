"""Workflow package — IR types, validator, and LangGraph compiler.

The workflow module defines the JSON-based "Workflow IR" contract between
the React frontend (workflow canvas) and the Python backend (LangGraph executor).
"""

from .ir_types import (
    CodeNodeConfig,
    EdgeDef,
    HumanConfirmField,
    HumanConfirmNodeConfig,
    LLMNodeConfig,
    NodeDef,
    RouterBranch,
    RouterNodeConfig,
    WorkflowIR,
    WorkflowSchema,
    resolve_template,
)

__all__ = [
    "CodeNodeConfig",
    "EdgeDef",
    "HumanConfirmField",
    "HumanConfirmNodeConfig",
    "LLMNodeConfig",
    "NodeDef",
    "RouterBranch",
    "RouterNodeConfig",
    "WorkflowIR",
    "WorkflowSchema",
    "resolve_template",
]
