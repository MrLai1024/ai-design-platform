"""LayerManager — 三层状态机 + 四种进入模式."""

from __future__ import annotations

import structlog

from .state import (
    RequirementsState,
    FeatureModule,
    PageNode,
    PageDetail,
    FieldDef,
    ActionDef,
    TechConstraints,
    DataEntity,
    VisionData,
    TargetUser,
)

logger = structlog.get_logger()


class LayerManager:
    """管理需求分析的 4 种进入模式和三层递进流程."""

    def __init__(self):
        self.state: RequirementsState = RequirementsState()

    def enter_new(self, user_requirement: str) -> RequirementsState:
        """NEW 模式：空白状态，从 Layer 1 开始."""
        self.state = RequirementsState(mode="new", version=1, layer=1)
        self.state.layer_status["1"] = "active"
        self.state.vision.project_name = user_requirement[:80]
        return self.state

    def enter_edit(self, existing_state: RequirementsState, target_layer: int) -> RequirementsState:
        """EDIT 模式：携带现有 state，从指定层切入."""
        if target_layer not in (1, 2, 3):
            raise ValueError(f"target_layer must be 1, 2, or 3, got {target_layer}")
        self.state = existing_state.clone()
        self.state.mode = "edit"
        self.state.layer = target_layer
        self.state.layer_status[str(target_layer)] = "active"
        self.state.take_snapshot("edit_start")
        return self.state

    def enter_append(self, existing_state: RequirementsState) -> RequirementsState:
        """APPEND 模式：保留现有 state，跳到 Layer 2，只追问新增部分."""
        self.state = existing_state.clone()
        self.state.mode = "append"
        self.state.version = existing_state.version + 1
        self.state.parent_version = existing_state.version
        self.state.layer = 2
        self.state.layer_status["2"] = "active"
        self.state.mark_existing_as_confirmed()
        self.state.take_snapshot("append_start")
        return self.state

    def enter_continue(self, saved_state_json: str) -> RequirementsState:
        """CONTINUE 模式：从 DB 恢复，断点继续."""
        self.state = RequirementsState.from_json(saved_state_json)
        self.state.mode = "continue"
        return self.state

    def advance_layer(self) -> bool:
        """推进到下一层。返回 True 表示成功推进，False 表示已在最后一层."""
        current = self.state.layer
        if current >= 3:
            return False
        self.state.layer_status[str(current)] = "done"
        next_layer = current + 1
        self.state.layer = next_layer
        self.state.layer_status[str(next_layer)] = "active"
        self.state.take_snapshot(f"layer_{current}_done")
        return True

    def apply_card_update(self, card_update: dict) -> None:
        """将 LLM 返回的 card_update 合并到 RequirementsState."""
        layer = self.state.layer
        if layer == 0:
            logger.warning("apply_card_update called while layer==0 (idle), ignoring")
            return
        if layer == 1:
            self._apply_vision_update(card_update)
        elif layer == 2:
            self._apply_feature_update(card_update)
        elif layer == 3:
            self._apply_detail_update(card_update)

    def _apply_vision_update(self, update: dict) -> None:
        if "project_name" in update and update["project_name"]:
            self.state.vision.project_name = update["project_name"]
        if "target_users" in update and isinstance(update["target_users"], list):
            self.state.vision.target_users = [
                TargetUser(role=tu["role"], description=tu.get("description", ""))
                for tu in update["target_users"]
            ]
        if "core_problem" in update and update["core_problem"]:
            self.state.vision.core_problem = update["core_problem"]
        if "success_criteria" in update:
            self.state.vision.success_criteria = update["success_criteria"]
        if "scope_note" in update and update["scope_note"]:
            self.state.vision.scope_note = update["scope_note"]

    def _apply_feature_update(self, update: dict) -> None:
        if "features" in update and isinstance(update["features"], list):
            new_features = []
            for f in update["features"]:
                existing = next(
                    (fe for fe in self.state.features if fe.id == f.get("id")), None
                )
                if existing and existing.confirmed:
                    new_features.append(existing)  # APPEND: preserve confirmed
                else:
                    new_features.append(FeatureModule(
                        id=f.get("id", ""),
                        name=f.get("name", ""),
                        description=f.get("description", ""),
                        priority=f.get("priority", "must"),
                        completeness=f.get("completeness", 0),
                        confirmed=existing.confirmed if existing else False,
                    ))
            self.state.features = new_features
        if "pages" in update:
            self.state.pages = [
                PageNode(
                    id=p.get("id", ""),
                    name=p.get("name", ""),
                    parent_id=p.get("parent_id"),
                    page_type=p.get("page_type", "custom"),
                    features=p.get("features", []),
                )
                for p in update["pages"]
            ]

    def _apply_detail_update(self, update: dict) -> None:
        if "page_details" in update and isinstance(update["page_details"], dict):
            for page_id, pd in update["page_details"].items():
                self.state.page_details[page_id] = PageDetail(
                    display_fields=[
                        FieldDef(name=f.get("name", ""), type=f.get("type", "text"),
                                 required=f.get("required", False))
                        for f in pd.get("display_fields", [])
                    ],
                    action_buttons=[
                        ActionDef(label=a.get("label", ""), type=a.get("type", "custom"))
                        for a in pd.get("action_buttons", [])
                    ],
                    related_data=pd.get("related_data", []),
                    layout_notes=pd.get("layout_notes", ""),
                )
        if "tech_constraints" in update:
            tc = update["tech_constraints"]
            self.state.tech_constraints = TechConstraints(
                framework=tc.get("framework", ""),
                component_lib=tc.get("component_lib", ""),
                data_source=tc.get("data_source", ""),
                special_requirements=tc.get("special_requirements", []),
            )
        if "data_entities" in update:
            self.state.data_entities = [
                DataEntity(name=de["name"], fields=de.get("fields", []))
                for de in update["data_entities"]
            ]

    def is_layer_done(self) -> bool:
        """检查当前层是否完成（基于退出条件）."""
        layer = self.state.layer
        if layer == 1:
            return (
                bool(self.state.vision.project_name)
                and len(self.state.vision.target_users) > 0
                and bool(self.state.vision.core_problem)
                and len(self.state.vision.success_criteria) > 0
            )
        if layer == 2:
            must_features = [f for f in self.state.features if f.priority == "must"]
            if not must_features:
                return False
            return all(f.completeness >= 80 for f in must_features)
        if layer == 3:
            return False  # Layer 3 completion determined by user
        return False
