"""RequirementsState — 需求分析结构化状态数据模型."""

from __future__ import annotations
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetUser:
    role: str
    description: str = ""


@dataclass
class FeatureModule:
    id: str
    name: str
    description: str = ""
    priority: str = "must"  # must | should | nice
    completeness: int = 0   # 0-100
    confirmed: bool = False


@dataclass
class PageNode:
    id: str
    name: str
    parent_id: str | None = None
    page_type: str = "custom"  # list | detail | form | dashboard | custom
    features: list[str] = field(default_factory=list)


@dataclass
class FieldDef:
    name: str
    type: str = "text"
    required: bool = False


@dataclass
class ActionDef:
    label: str
    type: str = "custom"


@dataclass
class PageDetail:
    display_fields: list[FieldDef] = field(default_factory=list)
    action_buttons: list[ActionDef] = field(default_factory=list)
    related_data: list[str] = field(default_factory=list)
    layout_notes: str = ""


@dataclass
class TechConstraints:
    framework: str = ""
    component_lib: str = ""
    data_source: str = ""
    special_requirements: list[str] = field(default_factory=list)


@dataclass
class DataEntity:
    name: str
    fields: list[dict] = field(default_factory=list)


@dataclass
class VisionData:
    project_name: str = ""
    target_users: list[TargetUser] = field(default_factory=list)
    core_problem: str = ""
    success_criteria: list[str] = field(default_factory=list)
    scope_note: str = ""


@dataclass
class StateSnapshot:
    timestamp: float
    layer: int
    reason: str
    state_json: str


@dataclass
class RequirementsState:
    session_id: str = ""
    mode: str = "new"  # new | edit | append | continue
    version: int = 0
    parent_version: int | None = None
    layer: int = 0  # 0=idle, 1=vision, 2=features, 3=details
    layer_status: dict[str, str] = field(default_factory=lambda: {"1": "pending", "2": "pending", "3": "pending"})
    history: list[StateSnapshot] = field(default_factory=list)
    vision: VisionData = field(default_factory=VisionData)
    features: list[FeatureModule] = field(default_factory=list)
    pages: list[PageNode] = field(default_factory=list)
    page_details: dict[str, PageDetail] = field(default_factory=dict)
    tech_constraints: TechConstraints = field(default_factory=TechConstraints)
    data_entities: list[DataEntity] = field(default_factory=list)

    def clone(self) -> RequirementsState:
        return deepcopy(self)

    def mark_existing_as_confirmed(self) -> None:
        for f in self.features:
            f.confirmed = True

    def take_snapshot(self, reason: str) -> None:
        self.history.append(StateSnapshot(
            timestamp=time.time(),
            layer=self.layer,
            reason=reason,
            state_json=self.to_json(),
        ))

    def to_json(self) -> str:
        return json.dumps(_dataclass_to_dict(self), ensure_ascii=False)

    @staticmethod
    def from_json(json_str: str) -> RequirementsState:
        try:
            return _dict_to_requirements_state(json.loads(json_str))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for RequirementsState: {e}") from e


def _dataclass_to_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for f_name in obj.__dataclass_fields__:
            value = getattr(obj, f_name)
            result[f_name] = _dataclass_to_dict(value)
        return result
    return obj


def _valid_fields(d: dict, cls: type) -> dict:
    """Filter dict to only contain keys that are fields of the given dataclass."""
    field_names = {f.name for f in cls.__dataclass_fields__.values()}
    return {k: v for k, v in d.items() if k in field_names}


def _dict_to_requirements_state(d: dict) -> RequirementsState:
    state = RequirementsState(
        session_id=d.get("session_id", ""),
        mode=d.get("mode", "new"),
        version=d.get("version", 0),
        parent_version=d.get("parent_version"),
        layer=d.get("layer", 0),
        layer_status=d.get("layer_status", {"1": "pending", "2": "pending", "3": "pending"}),
    )
    v = d.get("vision", {})
    if v:
        state.vision = VisionData(
            project_name=v.get("project_name", ""),
            target_users=[TargetUser(**tu) for tu in v.get("target_users", [])],
            core_problem=v.get("core_problem", ""),
            success_criteria=v.get("success_criteria", []),
            scope_note=v.get("scope_note", ""),
        )
    state.features = [FeatureModule(**_valid_fields(f, FeatureModule)) for f in d.get("features", [])]
    state.pages = [PageNode(**_valid_fields(p, PageNode)) for p in d.get("pages", [])]
    pd = d.get("page_details", {})
    state.page_details = {}
    for k, v in pd.items():
        display_fields = [FieldDef(**df) for df in v.get("display_fields", [])]
        action_buttons = [ActionDef(**ab) for ab in v.get("action_buttons", [])]
        state.page_details[k] = PageDetail(
            display_fields=display_fields,
            action_buttons=action_buttons,
            related_data=v.get("related_data", []),
            layout_notes=v.get("layout_notes", ""),
        )
    tc = d.get("tech_constraints", {})
    if tc:
        state.tech_constraints = TechConstraints(**_valid_fields(tc, TechConstraints))
    state.data_entities = [DataEntity(**_valid_fields(de, DataEntity)) for de in d.get("data_entities", [])]
    for h in d.get("history", []):
        if "timestamp" in h and "layer" in h and "reason" in h and "state_json" in h:
            state.history.append(StateSnapshot(**_valid_fields(h, StateSnapshot)))
    return state
