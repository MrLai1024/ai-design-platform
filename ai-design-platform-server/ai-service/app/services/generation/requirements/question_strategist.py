"""QuestionStrategist — 自适应提问引擎."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import structlog

from .state import RequirementsState

logger = structlog.get_logger()

LLMStructuredFn = Callable[..., Any]

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _load_prompt(filename: str) -> str:
    with open(os.path.join(_PROMPT_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


class QuestionStrategist:
    """自适应提问引擎：根据当前层和状态生成下一轮问题."""

    def __init__(self):
        self._vision_prompt = _load_prompt("vision_align.txt")
        self._feature_prompt = _load_prompt("feature_decompose.txt")
        self._detail_prompt = _load_prompt("detail_fill.txt")

    async def ask(
        self,
        state: RequirementsState,
        user_input: str,
        llm_generate_structured,
    ) -> StrategistOutput:
        """根据当前层生成下一轮提问.

        Args:
            state: 当前需求分析状态
            user_input: 用户本轮输入
            llm_generate_structured: async fn(system_prompt, user_prompt, output_schema) -> dict

        Returns:
            StrategistOutput: 包含 layer_done, questions, card_update, progress
        """
        layer = state.layer
        if layer == 1:
            return await self._ask_layer1(state, user_input, llm_generate_structured)
        elif layer == 2:
            return await self._ask_layer2(state, user_input, llm_generate_structured)
        elif layer == 3:
            return await self._ask_layer3(state, user_input, llm_generate_structured)
        else:
            raise ValueError(f"Unknown layer: {layer}")

    async def _ask_layer1(
        self, state: RequirementsState, user_input: str, llm: LLMStructuredFn,
    ) -> StrategistOutput:
        vision_json = json.dumps(_vision_to_dict(state.vision), ensure_ascii=False)
        user_prompt = (
            f"用户输入: {user_input}\n\n"
            f"当前愿景信息:\n{vision_json}\n"
        )
        raw = await llm(
            self._vision_prompt,
            user_prompt,
            output_schema={
                "layer_done": False,
                "question": "...",
                "options": ["...", "..."],
                "skippable": True,
                "card_update": {"project_name": "...", "target_users": [], "core_problem": "", "success_criteria": [], "scope_note": ""},
                "progress": {"layer": 1, "total_layers": 3, "done_count": 0, "pending_count": 0},
            },
        )
        return StrategistOutput(
            layer_done=raw.get("layer_done", False),
            questions=[{
                "text": raw.get("question", ""),
                "options": raw.get("options", []),
                "skippable": raw.get("skippable", True),
            }],
            card_update=raw.get("card_update", {}),
            progress=raw.get("progress", {}),
        )

    async def _ask_layer2(
        self, state: RequirementsState, user_input: str, llm: LLMStructuredFn,
    ) -> StrategistOutput:
        features_json = json.dumps([_feat_to_dict(f) for f in state.features], ensure_ascii=False)
        pages_json = json.dumps([_page_to_dict(p) for p in state.pages], ensure_ascii=False)
        vision_json = json.dumps(_vision_to_dict(state.vision), ensure_ascii=False)

        prompt = self._feature_prompt.format(
            vision_json=vision_json,
            features_json=features_json,
            pages_json=pages_json,
        )
        user_prompt = (
            f"用户输入: {user_input}\n\n"
            f"项目愿景: {vision_json}\n"
            f"已有的功能模块: {features_json}\n"
            f"已有的页面结构: {pages_json}\n"
        )
        raw = await llm(
            prompt,
            user_prompt,
            output_schema={
                "layer_done": False,
                "questions": [{"text": "...", "options": [], "skippable": True}],
                "card_update": {"features": [], "pages": []},
                "progress": {"layer": 2, "total_layers": 3, "done_count": 0, "pending_count": 0},
            },
        )
        return StrategistOutput(
            layer_done=raw.get("layer_done", False),
            questions=raw.get("questions", []),
            card_update=raw.get("card_update", {}),
            progress=raw.get("progress", {}),
        )

    async def _ask_layer3(
        self, state: RequirementsState, user_input: str, llm: LLMStructuredFn,
    ) -> StrategistOutput:
        features_json = json.dumps([_feat_to_dict(f) for f in state.features], ensure_ascii=False)
        pages_json = json.dumps([_page_to_dict(p) for p in state.pages], ensure_ascii=False)
        vision_json = json.dumps(_vision_to_dict(state.vision), ensure_ascii=False)

        prompt = self._detail_prompt.format(
            vision_json=vision_json,
            features_json=features_json,
            pages_json=pages_json,
        )
        user_prompt = (
            f"用户输入: {user_input}\n\n"
            f"项目愿景: {vision_json}\n"
            f"功能模块: {features_json}\n"
            f"页面结构: {pages_json}\n"
        )
        raw = await llm(
            prompt,
            user_prompt,
            output_schema={
                "layer_done": False,
                "questions": [{"text": "...", "options": [], "skippable": True}],
                "card_update": {"page_details": {}, "tech_constraints": {}, "data_entities": []},
                "progress": {"layer": 3, "total_layers": 3, "done_count": 0, "pending_count": 0},
            },
        )
        return StrategistOutput(
            layer_done=raw.get("layer_done", False),
            questions=raw.get("questions", []),
            card_update=raw.get("card_update", {}),
            progress=raw.get("progress", {}),
        )


class StrategistOutput:
    """提问策略输出."""
    def __init__(self, *, layer_done: bool, questions: list[dict], card_update: dict, progress: dict):
        self.layer_done = layer_done
        self.questions = questions
        self.card_update = card_update
        self.progress = progress


# --- Serialization helpers for prompt context ---

def _feat_to_dict(f) -> dict:
    return {"id": f.id, "name": f.name, "description": f.description,
            "priority": f.priority, "completeness": f.completeness, "confirmed": f.confirmed}


def _page_to_dict(p) -> dict:
    return {"id": p.id, "name": p.name, "parent_id": p.parent_id,
            "page_type": p.page_type, "features": p.features}


def _vision_to_dict(v) -> dict:
    return {
        "project_name": v.project_name,
        "target_users": [{"role": t.role, "description": t.description} for t in v.target_users],
        "core_problem": v.core_problem,
        "success_criteria": v.success_criteria,
        "scope_note": v.scope_note,
    }
