# 需求分析 Agent 三层对话引擎 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 prompt 驱动的需求分析节点升级为三层递进式对话引擎（愿景对齐 → 功能分解 → 细节补充），支持 NEW/EDIT/APPEND/CONTINUE 四种模式，结构化卡片实时更新，PRD 流式输出。

**Architecture:** 后端新增 `requirements/` package（LayerManager + QuestionStrategist + RequirementsState + PRDGenerator），通过 SSE 事件驱动前端卡片渲染和流式文档生成。前端新增 AnalysisPanel 组件族，扩展 useMultiAgent 和 generation store 处理需求分析事件。

**Tech Stack:** Python (LangGraph + structlog), Vue 3 (Composition API + Pinia + Tailwind CSS), TypeScript

---

## File Structure

```
后端新增:
  ai-service/app/services/generation/requirements/
  ├── __init__.py
  ├── state.py                  — RequirementsState dataclass (+ JSON 序列化)
  ├── layer_manager.py          — LayerManager: 三层状态机 + 四种模式
  ├── question_strategist.py    — 自适应提问引擎
  ├── prd_generator.py          — PRD 流式生成器 (full + diff)
  └── prompts/
      ├── vision_align.txt
      ├── feature_decompose.txt
      └── detail_fill.txt

后端修改:
  ai-service/app/services/generation/nodes.py          — analysis_node 集成 LayerManager
  ai-service/app/services/generation/graph.py          — GraphRunner 新增需求分析事件
  ai-service/app/services/generation/state.py          — GenerationState 扩展 qa_rounds → requirements_state_json

前端新增:
  ai-design-platform-web/packages/ai-generation-app/src/
  ├── types/requirements.ts                            — RequirementsState 等 TS 类型
  ├── components/AnalysisPanel.vue                     — 右侧面板容器
  ├── components/LayerProgress.vue                     — 三层进度指示器
  ├── components/ModeSelector.vue                      — 模式切换
  ├── components/cards/VisionCard.vue                  — Layer 1 卡片
  ├── components/cards/FeatureCard.vue                 — Layer 2 卡片
  ├── components/cards/DetailCard.vue                  — Layer 3 卡片
  └── components/PRDGeneratorView.vue                  — PRD 流式输出视图

前端修改:
  src/stores/generation.ts                             — 扩展 state + actions
  src/composables/useMultiAgent.ts                      — 新增 handleRequirementSSE
  src/composables/useStreamChat.ts                      — 新增需求分析事件 case
  src/views/GenerationView.vue                          — 集成 AnalysisPanel
  src/types/generation.ts                               — 新增 AnalysisPanelMode 类型
```

---

### Task 1: 后端 — RequirementsState 数据模型

**Files:**
- Create: `ai-service/app/services/generation/requirements/__init__.py`
- Create: `ai-service/app/services/generation/requirements/state.py`
- Modify: `ai-service/app/services/generation/state.py`

- [ ] **Step 1: 创建 requirements package**

```bash
mkdir -p ai-service/app/services/generation/requirements/prompts
```

- [ ] **Step 2: 创建 `requirements/__init__.py`**

```python
# ai-service/app/services/generation/requirements/__init__.py
"""需求分析 Agent — 三层递进式对话引擎."""
```

- [ ] **Step 3: 创建 `requirements/state.py` 数据模型**

```python
# ai-service/app/services/generation/requirements/state.py
"""RequirementsState — 需求分析结构化状态数据模型."""

from __future__ import annotations

import json
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
    type: str = "text"  # text | number | date | dropdown | tag | boolean | custom
    required: bool = False


@dataclass
class ActionDef:
    label: str
    type: str = "custom"  # edit | create | delete | export | custom


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
    fields: list[dict] = field(default_factory=list)  # {name, type, required}


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
    state_json: str  # JSON-serialized RequirementsState for deep copy


@dataclass
class RequirementsState:
    """需求分析全量结构化状态."""

    session_id: str = ""
    mode: str = "new"  # new | edit | append | continue
    version: int = 0
    parent_version: int | None = None
    layer: int = 0  # 0=idle, 1=vision, 2=features, 3=details
    layer_status: dict[str, str] = field(default_factory=lambda: {
        "1": "pending", "2": "pending", "3": "pending",
    })
    history: list[StateSnapshot] = field(default_factory=list)

    # Layer 1 产出
    vision: VisionData = field(default_factory=VisionData)

    # Layer 2 产出
    features: list[FeatureModule] = field(default_factory=list)
    pages: list[PageNode] = field(default_factory=list)

    # Layer 3 产出
    page_details: dict[str, PageDetail] = field(default_factory=dict)
    tech_constraints: TechConstraints = field(default_factory=TechConstraints)
    data_entities: list[DataEntity] = field(default_factory=list)

    def clone(self) -> RequirementsState:
        """深拷贝，创建独立副本用于 EDIT/APPEND 模式."""
        return deepcopy(self)

    def mark_existing_as_confirmed(self) -> None:
        """APPEND 模式：将已有模块标记为 confirmed，Agent 不再追问."""
        for f in self.features:
            f.confirmed = True

    def take_snapshot(self, reason: str) -> None:
        """保存当前状态快照到 history."""
        self.history.append(StateSnapshot(
            timestamp=0,  # 由调用方设置
            layer=self.layer,
            reason=reason,
            state_json=self.to_json(),
        ))

    def to_json(self) -> str:
        """序列化为 JSON 字符串，存入 GenerationState."""
        return json.dumps(self._to_dict(), ensure_ascii=False)

    @staticmethod
    def from_json(json_str: str) -> RequirementsState:
        """从 JSON 字符串反序列化."""
        return RequirementsState._from_dict(json.loads(json_str))

    @staticmethod
    def from_chat_context(messages: list[dict], requirement: str) -> RequirementsState:
        """从聊天上下文初始化（NEW 模式入口）."""
        state = RequirementsState(
            mode="new",
            version=0,
            layer=0,
        )
        # 尝试从用户原始输入中提取项目名称
        if requirement:
            state.vision.project_name = requirement[:80]
        return state

    def _to_dict(self) -> dict:
        """递归转换为纯 dict（dataclass → dict）."""
        return _dataclass_to_dict(self)

    @staticmethod
    def _from_dict(d: dict) -> RequirementsState:
        """从 dict 递归还原为 RequirementsState."""
        return _dict_to_requirements_state(d)


def _dataclass_to_dict(obj: Any) -> Any:
    """递归将 dataclass 转为 dict."""
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


def _dict_to_requirements_state(d: dict) -> RequirementsState:
    """将 dict 还原为 RequirementsState（含嵌套 dataclass）."""
    state = RequirementsState(
        session_id=d.get("session_id", ""),
        mode=d.get("mode", "new"),
        version=d.get("version", 0),
        parent_version=d.get("parent_version"),
        layer=d.get("layer", 0),
        layer_status=d.get("layer_status", {"1": "pending", "2": "pending", "3": "pending"}),
    )
    # Layer 1
    v = d.get("vision", {})
    if v:
        state.vision = VisionData(
            project_name=v.get("project_name", ""),
            target_users=[TargetUser(**tu) for tu in v.get("target_users", [])],
            core_problem=v.get("core_problem", ""),
            success_criteria=v.get("success_criteria", []),
            scope_note=v.get("scope_note", ""),
        )
    # Layer 2
    state.features = [FeatureModule(**f) for f in d.get("features", [])]
    state.pages = [PageNode(**p) for p in d.get("pages", [])]
    # Layer 3
    pd = d.get("page_details", {})
    state.page_details = {k: PageDetail(**v) for k, v in pd.items()}
    tc = d.get("tech_constraints", {})
    if tc:
        state.tech_constraints = TechConstraints(**tc)
    state.data_entities = [DataEntity(**de) for de in d.get("data_entities", [])]
    # History
    state.history = [StateSnapshot(**h) for h in d.get("history", [])]
    return state
```

- [ ] **Step 4: 扩展 `state.py` 的 GenerationState 新增字段**

In `ai-service/app/services/generation/state.py`, add to `GenerationState`:

```python
class GenerationState(TypedDict):
    # ... existing fields remain unchanged ...

    # 新增: 需求分析结构化状态 (JSON 序列化 RequirementsState)
    requirements_state_json: str | None
```

- [ ] **Step 5: 写单元测试验证序列化往返**

Create a temporary test script to verify serialization round-trip:

```bash
cd ai-service && python -c "
from app.services.generation.requirements.state import RequirementsState, VisionData, FeatureModule
state = RequirementsState(mode='new', layer=1)
state.vision = VisionData(project_name='Test', core_problem='Testing')
state.features.append(FeatureModule(id='f1', name='Customer Mgmt', completeness=80))
json_str = state.to_json()
restored = RequirementsState.from_json(json_str)
assert restored.vision.project_name == 'Test'
assert restored.features[0].name == 'Customer Mgmt'
assert restored.features[0].completeness == 80
print('OK: RequirementsState serialization round-trip passed')
"
```

- [ ] **Step 6: 在 servicer.py 中初始化 requirements_state_json**

In `ai-service/app/services/generation/servicer.py`, in `_stream_graph()`, add to the initial state dict:

```python
from .requirements.state import RequirementsState

# Inside _stream_graph, after building state dict:
req_state = RequirementsState(mode="new")
state["requirements_state_json"] = req_state.to_json()
state["qa_rounds"] = 0  # existing field, ensure initialized
```

---

### Task 2: 后端 — Prompt 模板

**Files:**
- Create: `ai-service/app/services/generation/requirements/prompts/vision_align.txt`
- Create: `ai-service/app/services/generation/requirements/prompts/feature_decompose.txt`
- Create: `ai-service/app/services/generation/requirements/prompts/detail_fill.txt`

- [ ] **Step 1: 创建 `vision_align.txt` (Layer 1)**

```text
你是一个资深产品需求分析师，正在进行 **第一阶段：愿景对齐**。

## 你的任务
通过提问了解项目的核心愿景。当前阶段你需要搞清楚：
1. 项目名称
2. 目标用户角色（谁在用？）
3. 核心解决的问题（为什么需要这个系统？）
4. 成功标准（做到什么程度算成功？）
5. 范围边界（本期做什么，不做什么？）

## 当前状态
用户已经提供的信息在下方以 JSON 格式给出。你需要根据当前信息的完整程度决定下一步。

## 规则
- 每轮最多问 **1 个问题**，提供 2-4 个选项让用户选择
- 如果某个维度已经明确，不要重复提问
- 对于简单需求（如"一个登录页"），可以快速通过
- 对于复杂需求（如"一个ERP系统"），需要深入追问

## 输出格式
你必须以 JSON 格式输出：
{
  "layer_done": false,
  "question": "你的问题文本",
  "options": ["选项A", "选项B", "选项C"],
  "skippable": true,
  "card_update": {
    "project_name": "确认的项目名称",
    "target_users": [{"role": "角色", "description": "说明"}],
    "core_problem": "核心问题描述",
    "success_criteria": ["成功标准1"],
    "scope_note": "范围说明"
  },
  "progress": {
    "layer": 1,
    "total_layers": 3,
    "done_count": 2,
    "pending_count": 1
  }
}

## 退出条件
当 project_name + target_users + core_problem + success_criteria（至少 1 条）均已明确时，
设置 layer_done: true。

只输出 JSON，不要有其他内容。
```

- [ ] **Step 2: 创建 `feature_decompose.txt` (Layer 2)**

```text
你是一个资深产品需求分析师，正在进行 **第二阶段：功能分解**。

## 你的任务
基于已确认的项目愿景，帮助用户拆解功能模块和页面结构。

## 当前状态
- 项目愿景：{vision_json}
- 已有的功能模块：{features_json}
- 已有的页面结构：{pages_json}

## 规则
- 每轮最多问 **2 个问题**（关于功能模块和页面结构各 1 个，第二个标注可选）
- 为每个功能模块评估完整度（completeness 0-100%）
- 自动推导页面结构树（从功能模块关联到页面）
- 功能模块的 priority: must（必须有）/ should（应该有）/ nice（锦上添花）

## 输出格式
你必须以 JSON 格式输出：
{
  "layer_done": false,
  "questions": [
    {
      "text": "问题文本",
      "options": ["选项A", "选项B"],
      "skippable": true
    }
  ],
  "card_update": {
    "features": [
      {
        "id": "feat-1",
        "name": "功能模块名",
        "description": "简要说明",
        "priority": "must",
        "completeness": 80
      }
    ],
    "pages": [
      {
        "id": "page-1",
        "name": "页面名",
        "parent_id": null,
        "page_type": "list",
        "features": ["feat-1"]
      }
    ]
  },
  "progress": {
    "layer": 2,
    "total_layers": 3,
    "done_count": 4,
    "pending_count": 2
  }
}

## 退出条件
所有 priority == "must" 的功能模块 completeness >= 80%时，设置 layer_done: true。

只输出 JSON，不要有其他内容。
```

- [ ] **Step 3: 创建 `detail_fill.txt` (Layer 3)**

```text
你是一个资深产品需求分析师，正在进行 **第三阶段：细节补充**。

## 你的任务
为关键页面补充交互细节、数据字段、技术约束。

## 当前状态
- 项目愿景：{vision_json}
- 功能模块：{features_json}
- 页面结构：{pages_json}

## 规则
- 每轮最多问 **2 个问题**，第二个标注可选
- 聚焦用户最关心的 1-3 个核心页面，不为所有页面提问
- 技术约束（框架、组件库、数据来源）如果用户已提及则直接确认
- 页面详情中的字段类型推测要合理

## 输出格式
你必须以 JSON 格式输出：
{
  "layer_done": false,
  "questions": [
    {
      "text": "问题文本",
      "options": ["选项A", "选项B"],
      "skippable": true
    }
  ],
  "card_update": {
    "page_details": {
      "page-1": {
        "display_fields": [
          {"name": "字段名", "type": "text", "required": true}
        ],
        "action_buttons": [
          {"label": "编辑", "type": "edit"}
        ],
        "related_data": ["关联的数据实体"],
        "layout_notes": "布局说明"
      }
    },
    "tech_constraints": {
      "framework": "vue3",
      "component_lib": "tailwind",
      "data_source": "REST API",
      "special_requirements": []
    },
    "data_entities": [
      {
        "name": "实体名",
        "fields": [
          {"name": "字段名", "type": "string", "required": true}
        ]
      }
    ]
  },
  "progress": {
    "layer": 3,
    "total_layers": 3,
    "done_count": 3,
    "pending_count": 1
  }
}

## 退出条件
核心页面的字段和操作已覆盖 OR layer_done 设为 true 让用户决定。

只输出 JSON，不要有其他内容。
```

---

### Task 3: 后端 — QuestionStrategist 提问引擎

**File:** Create: `ai-service/app/services/generation/requirements/question_strategist.py`

- [ ] **Step 1: 创建 `question_strategist.py`**

```python
# ai-service/app/services/generation/requirements/question_strategist.py
"""QuestionStrategist — 自适应提问引擎."""

from __future__ import annotations

import json
import structlog

from .state import RequirementsState

logger = structlog.get_logger()

# Prompt 模板路径
_PROMPT_DIR = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "prompts"
)


def _load_prompt(filename: str) -> str:
    with open(__import__("os").path.join(_PROMPT_DIR, filename), "r", encoding="utf-8") as f:
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
        """根据当前层生成下一轮提问。

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

    async def _ask_layer1(self, state, user_input, llm) -> StrategistOutput:
        user_prompt = (
            f"用户输入: {user_input}\n\n"
            f"当前愿景信息:\n{json.dumps(state.vision._to_dict() if hasattr(state.vision, '_to_dict') else {}, ensure_ascii=False)}\n"
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

    async def _ask_layer2(self, state, user_input, llm) -> StrategistOutput:
        features_json = json.dumps([_feat_to_dict(f) for f in state.features], ensure_ascii=False)
        pages_json = json.dumps([_page_to_dict(p) for p in state.pages], ensure_ascii=False)
        vision_json = json.dumps(_vision_to_dict(state.vision), ensure_ascii=False)

        user_prompt = (
            f"用户输入: {user_input}\n\n"
            f"项目愿景: {vision_json}\n"
            f"已有的功能模块: {features_json}\n"
            f"已有的页面结构: {pages_json}\n"
        )
        raw = await llm(
            self._feature_prompt,
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

    async def _ask_layer3(self, state, user_input, llm) -> StrategistOutput:
        features_json = json.dumps([_feat_to_dict(f) for f in state.features], ensure_ascii=False)
        pages_json = json.dumps([_page_to_dict(p) for p in state.pages], ensure_ascii=False)
        vision_json = json.dumps(_vision_to_dict(state.vision), ensure_ascii=False)

        user_prompt = (
            f"用户输入: {user_input}\n\n"
            f"项目愿景: {vision_json}\n"
            f"功能模块: {features_json}\n"
            f"页面结构: {pages_json}\n"
        )
        raw = await llm(
            self._detail_prompt,
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
```

---

### Task 4: 后端 — LayerManager 状态机

**File:** Create: `ai-service/app/services/generation/requirements/layer_manager.py`

- [ ] **Step 1: 创建 `layer_manager.py`**

```python
# ai-service/app/services/generation/requirements/layer_manager.py
"""LayerManager — 三层状态机 + 四种进入模式."""

from __future__ import annotations

import json
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
        self.state = existing_state.clone()
        self.state.mode = "edit"
        self.state.layer = target_layer
        self.state.layer_status[str(target_layer)] = "active"
        self.state.take_snapshot("edit_start")
        return self.state

    def enter_append(self, existing_state: RequirementsState, append_input: str) -> RequirementsState:
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
        if layer == 1:
            self._apply_vision_update(card_update)
        elif layer == 2:
            self._apply_feature_update(card_update)
        elif layer == 3:
            self._apply_detail_update(card_update)

    def _apply_vision_update(self, update: dict) -> None:
        if "project_name" in update:
            self.state.vision.project_name = update["project_name"]
        if "target_users" in update:
            self.state.vision.target_users = [
                TargetUser(role=tu["role"], description=tu.get("description", ""))
                for tu in update["target_users"]
            ]
        if "core_problem" in update:
            self.state.vision.core_problem = update["core_problem"]
        if "success_criteria" in update:
            self.state.vision.success_criteria = update["success_criteria"]
        if "scope_note" in update:
            self.state.vision.scope_note = update["scope_note"]

    def _apply_feature_update(self, update: dict) -> None:
        if "features" in update:
            new_features = []
            for f in update["features"]:
                existing = next(
                    (fe for fe in self.state.features if fe.id == f.get("id")), None
                )
                if existing and existing.confirmed:
                    new_features.append(existing)  # APPEND 模式：保留已确认的
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
        if "page_details" in update:
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
            # Layer 3 由用户决定是否完成（LLM 的 layer_done 信号 + 用户确认）
            return False
        return False
```

---

### Task 5: 后端 — PRDGenerator 流式文档生成

**File:** Create: `ai-service/app/services/generation/requirements/prd_generator.py`

- [ ] **Step 1: 创建 `prd_generator.py`**

```python
# ai-service/app/services/generation/requirements/prd_generator.py
"""PRDGenerator — 从 RequirementsState 流式生成 PRD 文档."""

from __future__ import annotations

import json
import structlog

from .state import RequirementsState

logger = structlog.get_logger()

PRD_SYSTEM_PROMPT = """你是一个资深产品需求文档撰写专家。根据结构化需求数据，生成一份完整的需求规格文档。

## 文档结构（严格按此顺序输出）
1. **# 需求规格文档** — 文档标题
2. **## 1. 功能概述** — 项目背景、核心问题、目标用户、成功标准、范围边界
3. **## 2. 功能模块** — 按优先级排列的功能模块清单（must → should → nice），每个模块含名称、描述、子功能点
4. **## 3. 页面结构** — 页面树形结构，标注页面类型（列表/详情/表单/仪表盘）
5. **## 4. 数据模型** — 核心数据实体及字段定义
6. **## 5. 交互行为** — 关键页面的操作流程和交互说明

## 规则
- 用简洁专业的语言，每条一句话
- 数据实体使用表格展示字段
- 不写代码，不写技术实现，不写组件选择
- 不确定的地方标注（待确认）
"""


async def generate_prd_full(
    state: RequirementsState,
    llm_generate,
    on_section,
) -> str:
    """从完整 state 流式生成 PRD（NEW/EDIT 模式）。

    Args:
        state: 完成三层收集的 RequirementsState
        llm_generate: async fn(system_prompt, user_prompt) -> str
        on_section: async callback(section_key, content_chunk) — 每段内容推送

    Returns:
        完整的 PRD markdown 字符串
    """
    context = _build_context(state)
    user_prompt = f"请根据以下结构化需求数据生成需求规格文档：\n\n{context}"

    full_text = ""
    async for chunk in llm_generate(PRD_SYSTEM_PROMPT, user_prompt):
        full_text += chunk
        # 按段落分发给回调
        await on_section("content", chunk)

    return full_text


async def generate_prd_diff(
    current: RequirementsState,
    parent: RequirementsState,
    llm_generate,
    on_diff,
) -> str:
    """从两个版本 state 生成增量 PRD diff（APPEND 模式）。

    Args:
        current: 当前（新版本）RequirementsState
        parent: 父版本 RequirementsState
        llm_generate: async fn(system_prompt, user_prompt) -> str
        on_diff: async callback(change_type, section_key, content) — 每段 diff 推送

    Returns:
        diff 摘要字符串
    """
    diff_system = PRD_SYSTEM_PROMPT + """
## 增量模式
用户已有一个 PRD v{parent_version}，现在要追加新功能。你需要：
1. 对于未变化的部分，标记为 unchanged
2. 对于新增的部分，标记为 added
3. 对于修改的部分，标记为 modified

输出格式：
```json
{
  "sections": [
    {"change": "unchanged|added|modified", "section": "功能概述", "content": "..."}
  ]
}
```"""

    context_current = _build_context(current)
    context_parent = _build_context(parent)
    user_prompt = (
        f"原始需求（v{parent.version}）：\n{context_parent}\n\n"
        f"更新后需求（v{current.version}）：\n{context_current}\n\n"
        f"请输出增量 diff，仅包含新增和修改的部分。"
    )

    full_text = ""
    # For diff mode, we stream the raw output and parse on the fly
    async for chunk in llm_generate(diff_system, user_prompt):
        full_text += chunk
        # Simplified: send as raw chunk; frontend parses sections
        await on_diff("stream", "", chunk)

    return full_text


def _build_context(state: RequirementsState) -> str:
    """将 RequirementsState 转为 LLM 可读的文本上下文."""
    parts = []

    # Layer 1
    v = state.vision
    parts.append(f"## 项目愿景\n- 名称: {v.project_name}\n- 目标用户: {', '.join(t.role for t in v.target_users)}")
    parts.append(f"- 核心问题: {v.core_problem}\n- 成功标准: {'; '.join(v.success_criteria)}")
    parts.append(f"- 范围: {v.scope_note}")

    # Layer 2
    parts.append("\n## 功能模块")
    for f in sorted(state.features, key=lambda x: {"must": 0, "should": 1, "nice": 2}.get(x.priority, 3)):
        parts.append(f"- [{f.priority}] {f.name}: {f.description} (完整度: {f.completeness}%)")

    parts.append("\n## 页面结构")
    for p in state.pages:
        indent = "  " * (0 if p.parent_id else 0)
        parts.append(f"{indent}- {p.name} ({p.page_type})")

    # Layer 3
    if state.page_details:
        parts.append("\n## 页面详情")
        for pid, pd in state.page_details.items():
            parts.append(f"\n### {pid}")
            if pd.display_fields:
                parts.append("展示字段:")
                for df in pd.display_fields:
                    parts.append(f"  - {df.name} ({df.type}) {'*' if df.required else ''}")
            if pd.action_buttons:
                parts.append(f"操作: {', '.join(a.label for a in pd.action_buttons)}")

    tc = state.tech_constraints
    parts.append(f"\n## 技术约束\n- 框架: {tc.framework or '待确认'}\n- 组件库: {tc.component_lib or '待确认'}\n- 数据源: {tc.data_source or '待确认'}")

    if state.data_entities:
        parts.append("\n## 数据实体")
        for de in state.data_entities:
            parts.append(f"\n### {de.name}")
            for fl in de.fields:
                parts.append(f"  - {fl['name']}: {fl['type']} {'(必填)' if fl.get('required') else ''}")

    return "\n".join(parts)
```

---

### Task 6: 后端 — 改造 analysis_node 集成 LayerManager

**File:** Modify: `ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 重写 `analysis_node` 函数**

Replace the existing `analysis_node` function with the new version that uses LayerManager, QuestionStrategist, and PRDGenerator:

```python
# ai-service/app/services/generation/nodes.py
# --- Analysis Node (rewritten) ---

from .requirements.state import RequirementsState as ReqState
from .requirements.layer_manager import LayerManager as ReqLayerManager
from .requirements.question_strategist import QuestionStrategist, StrategistOutput
from .requirements.prd_generator import generate_prd_full, generate_prd_diff

# 全局状态保持（在 GraphRunner 的单个 run 中）
_layer_manager: ReqLayerManager | None = None
_strategist = QuestionStrategist()


def _get_layer_manager() -> ReqLayerManager:
    global _layer_manager
    if _layer_manager is None:
        _layer_manager = ReqLayerManager()
    return _layer_manager


async def analysis_node(state: GenerationState) -> GenerationState:
    """需求分析节点：三层递进式对话引擎，替换原有简单 Q&A.

    流程:
    1. 首次进入: NEW 模式，初始化 LayerManager
    2. 后续轮次: 根据 state 恢复，QuestionStrategist 提问
    3. Layer 1/2/3 对话流: 提问 → 用户回答 → 卡片更新 → 判断层完成
    4. Layer 3 确认后: PRDGenerator 流式输出 PRD
    """
    logger.info("analysis_node_start", qa_rounds=state.get("qa_rounds", 0))

    mgr = _get_layer_manager()
    qa_rounds = state.get("qa_rounds", 0)

    # 从 state 恢复 RequirementsState
    req_json = state.get("requirements_state_json")
    if req_json:
        req_state = ReqState.from_json(req_json)
    else:
        req_state = ReqState(mode="new")

    # 首次进入
    if qa_rounds == 0:
        req_state = mgr.enter_new(state["requirement"])
        return _emit_question(state, req_state, mgr, qa_rounds)

    # 获取用户最新输入
    messages = state.get("messages", [])
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = m.get("content", "")
            break

    current_layer = req_state.layer

    # 使用 QuestionStrategist 生成下一轮问题
    output: StrategistOutput = await _strategist.ask(
        req_state,
        last_user,
        _llm_generate_structured,
    )

    # 应用卡片更新
    mgr.state = req_state
    mgr.apply_card_update(output.card_update)
    req_state = mgr.state

    # 判断层是否完成
    if output.layer_done or mgr.is_layer_done():
        if current_layer == 3:
            # 最后一层完成 → 生成 PRD
            return await _generate_prd(state, req_state, qa_rounds)
        else:
            # 推进到下一层
            advanced = mgr.advance_layer()
            if advanced:
                req_state = mgr.state
                return _emit_layer_done(state, req_state, current_layer, qa_rounds)
            else:
                return await _generate_prd(state, req_state, qa_rounds)

    # 层未完成，继续提问
    return _emit_question(state, req_state, mgr, qa_rounds)


def _emit_question(
    state: GenerationState,
    req_state: ReqState,
    mgr: ReqLayerManager,
    qa_rounds: int,
) -> GenerationState:
    """发射提问相关事件（通过 GraphEvent）."""
    req_state.take_snapshot(f"qa_round_{qa_rounds + 1}")
    return {
        **state,
        "requirements_state_json": req_state.to_json(),
        "qa_rounds": qa_rounds + 1,
        # analysis_result 存放当前要展示的问题文本
        "analysis_result": _format_questions(req_state),
    }


def _emit_layer_done(
    state: GenerationState,
    req_state: ReqState,
    completed_layer: int,
    qa_rounds: int,
) -> GenerationState:
    """发射层完成事件."""
    return {
        **state,
        "requirements_state_json": req_state.to_json(),
        "qa_rounds": qa_rounds + 1,
        "analysis_result": f"__LAYER_DONE__:{completed_layer}",
    }


async def _generate_prd(
    state: GenerationState,
    req_state: ReqState,
    qa_rounds: int,
) -> GenerationState:
    """流式生成 PRD 文档."""
    full_prd = ""
    async def on_section(section_key: str, chunk: str):
        nonlocal full_prd
        full_prd += chunk

    await generate_prd_full(
        req_state,
        lambda sys, usr: _llm_generate(sys, usr),  # 复用现有 LLM 调用
        on_section,
    )

    return {
        **state,
        "requirements_state_json": req_state.to_json(),
        "analysis_result": full_prd,
        "e2e_test_cases": _extract_e2e_cases(full_prd),
        "qa_rounds": qa_rounds + 1,
    }


def _format_questions(req_state: ReqState) -> str:
    """将当前层待问问题格式化为展示文本."""
    layer_names = {1: "愿景对齐", 2: "功能分解", 3: "细节补充"}
    current = layer_names.get(req_state.layer, "未知")
    progress = f"[Layer {req_state.layer}/3 {current}]"
    return f"{progress}\n"  # QuestionStrategist 的问题通过 card_update 在前端渲染


def _extract_e2e_cases(prd: str) -> list[dict]:
    """从 PRD 中提取 E2E 测试用例骨架（保持向后兼容）."""
    # 简化版：生成基本用例
    return [
        {
            "id": "TC-001",
            "name": "页面加载验证",
            "description": "验证核心页面能正常加载",
            "steps": [
                {"action": "wait", "target": "body", "value": "2000", "description": "等待页面加载"},
                {"action": "assert", "target": "body", "value": "", "description": "页面已加载"},
            ],
        }
    ]
```

- [ ] **Step 2: 在 servicer.py 中初始化 LayerManager**

In `ai-service/app/services/generation/servicer.py`, modify `_stream_graph` to inject the current stage:

```python
# Add to the state dict in _stream_graph:
from .requirements.state import RequirementsState
req_state = RequirementsState(mode="new")
req_state.vision.project_name = user_content[:80]
state["requirements_state_json"] = req_state.to_json()
```

---

### Task 7: 后端 — GraphRunner 新增需求分析事件

**File:** Modify: `ai-service/app/services/generation/graph.py`

- [ ] **Step 1: 在 GraphRunner 中为 analysis 阶段发射专用事件**

Modify the `run` method to detect analysis stage and emit requirement events:

```python
# In GraphRunner.run(), replace the analysis stage handling:

for node_name, node_output in event.items():
    yield self._make_event("stage_start", node_name, {})

    if node_name == "analysis":
        analysis_result = node_output.get("analysis_result", "")
        req_state_json = node_output.get("requirements_state_json", "")

        if analysis_result and analysis_result.startswith("__LAYER_DONE__"):
            # Layer completed
            layer_done = int(analysis_result.split(":")[1])
            yield self._make_event("requirement_layer_done", "analysis", {
                "layer": layer_done,
                "summary": f"Layer {layer_done} completed",
            })
        elif req_state_json:
            req_state = RequirementsState.from_json(req_state_json)
            # Emit card update
            yield self._make_event("requirement_card_update", "analysis", {
                "layer": req_state.layer,
                "card_type": {1: "vision", 2: "features", 3: "details"}.get(req_state.layer, "vision"),
                "fields": json.loads(req_state.to_json()),
            })
            # Emit question
            yield self._make_event("requirement_question", "analysis", {
                "questions": [],  # questions are rendered from card_update + chat
                "progress": {
                    "layer": req_state.layer,
                    "total_layers": 3,
                    "layer_status": req_state.layer_status,
                },
            })

    if node_name in ("analysis", "design"):
        yield self._make_event("human_confirm_required", node_name, {
            "message": f"Please review the {node_name} output and confirm to continue.",
        })

    yield self._make_event("stage_complete", node_name, {
        "summary": self._get_summary(node_name, node_output),
    })
```

---

### Task 8: 前端 — TypeScript 类型定义

**File:** Create: `ai-design-platform-web/packages/ai-generation-app/src/types/requirements.ts`

- [ ] **Step 1: 创建 `requirements.ts` 类型定义**

```typescript
// src/types/requirements.ts — 需求分析结构化类型

export type AnalysisMode = 'new' | 'edit' | 'append' | 'continue'

export interface TargetUser {
  role: string
  description: string
}

export interface FeatureModule {
  id: string
  name: string
  description: string
  priority: 'must' | 'should' | 'nice'
  completeness: number
  confirmed: boolean
}

export interface PageNode {
  id: string
  name: string
  parent_id: string | null
  page_type: 'list' | 'detail' | 'form' | 'dashboard' | 'custom'
  features: string[]
}

export interface FieldDef {
  name: string
  type: 'text' | 'number' | 'date' | 'dropdown' | 'tag' | 'boolean' | 'custom'
  required: boolean
}

export interface ActionDef {
  label: string
  type: 'edit' | 'create' | 'delete' | 'export' | 'custom'
}

export interface PageDetail {
  display_fields: FieldDef[]
  action_buttons: ActionDef[]
  related_data: string[]
  layout_notes: string
}

export interface TechConstraints {
  framework: string
  component_lib: string
  data_source: string
  special_requirements: string[]
}

export interface DataEntity {
  name: string
  fields: Array<{ name: string; type: string; required: boolean }>
}

export interface VisionData {
  project_name: string
  target_users: TargetUser[]
  core_problem: string
  success_criteria: string[]
  scope_note: string
}

export interface RequirementsState {
  session_id: string
  mode: AnalysisMode
  version: number
  parent_version: number | null
  layer: number
  layer_status: Record<string, 'pending' | 'active' | 'done'>
  history: StateSnapshot[]
  vision: VisionData
  features: FeatureModule[]
  pages: PageNode[]
  page_details: Record<string, PageDetail>
  tech_constraints: TechConstraints
  data_entities: DataEntity[]
}

export interface StateSnapshot {
  timestamp: number
  layer: number
  reason: string
  state_json: string
}

export interface PRDGenerateStart {
  mode: 'full' | 'diff'
  sections_count: number
  parent_version: number | null
}

export interface PRDDiffSegment {
  change: 'added' | 'modified' | 'unchanged'
  section: string
  content: string
}

export interface RequirementQuestion {
  text: string
  options?: string[]
  skippable: boolean
}

export interface LayerProgress {
  layer: number
  total_layers: number
  done_count: number
  pending_count: number
}

export type AnalysisPanelMode = 'card' | 'prd'
```

---

### Task 9: 前端 — generation store 扩展

**File:** Modify: `ai-design-platform-web/packages/ai-generation-app/src/stores/generation.ts`

- [ ] **Step 1: 在 store 中新增需求分析相关的 state 和 actions**

Add imports at the top:

```typescript
import type { RequirementsState, AnalysisPanelMode, PRDDiffSegment, AnalysisMode } from '@/types/requirements'
```

Add new state:

```typescript
// ── 需求分析面板状态 ──
const requirementsState = ref<RequirementsState | null>(null)
const analysisPanelMode = ref<AnalysisPanelMode>('card')
const prdStreamingContent = ref('')
const prdCurrentSection = ref<string | null>(null)
const prdVersion = ref(0)
```

Add new actions:

```typescript
// ── 需求分析 Actions ──

function setRequirementsState(s: RequirementsState): void {
  requirementsState.value = s
}

function patchRequirementsState(fields: Partial<RequirementsState>): void {
  if (!requirementsState.value) {
    requirementsState.value = fields as RequirementsState
  } else {
    Object.assign(requirementsState.value, fields)
  }
}

function setAnalysisPanelMode(mode: AnalysisPanelMode): void {
  analysisPanelMode.value = mode
}

function appendPRDContent(content: string): void {
  prdStreamingContent.value += content
}

function appendPRDDiff(change: string, section: string, content: string): void {
  // 增量模式下追加 diff 段落，带标记
  const prefix = change === 'added' ? '\n\n🆕 **新增** ' : change === 'modified' ? '\n\n✏️ **修改** ' : '\n\n'
  prdStreamingContent.value += `${prefix}${section}: ${content}`
}

function setPRDCurrentSection(section: string | null): void {
  prdCurrentSection.value = section
}

function setPRDComplete(fullContent: string): void {
  prdStreamingContent.value = fullContent
}

function setPRDVersion(version: number): void {
  prdVersion.value = version
}
```

Update `resetAll` to include new state:

```typescript
function resetAll(): void {
  // ... existing reset code ...
  requirementsState.value = null
  analysisPanelMode.value = 'card'
  prdStreamingContent.value = ''
  prdCurrentSection.value = null
  prdVersion.value = 0
}
```

Update the return object to export new state and actions:

```typescript
return {
  // ... existing returns ...
  // 需求分析
  requirementsState, analysisPanelMode, prdStreamingContent, prdCurrentSection, prdVersion,
  setRequirementsState, patchRequirementsState, setAnalysisPanelMode,
  appendPRDContent, appendPRDDiff, setPRDCurrentSection, setPRDComplete, setPRDVersion,
}
```

---

### Task 10: 前端 — AnalysisPanel 组件族

**Files:** Create 6 Vue components and the LayerProgress component

- [ ] **Step 1: 创建 `LayerProgress.vue`**

```vue
<!-- src/components/LayerProgress.vue -->
<template>
  <div class="flex items-center gap-2 text-sm">
    <div
      v-for="(layer, idx) in layers"
      :key="idx"
      class="flex items-center"
    >
      <span
        :class="{
          'w-2 h-2 rounded-full': true,
          'bg-blue-500': layer.status === 'active',
          'bg-green-500': layer.status === 'done',
          'bg-gray-300': layer.status === 'pending',
        }"
      />
      <span
        :class="{
          'ml-1': true,
          'text-blue-600 font-medium': layer.status === 'active',
          'text-gray-400': layer.status === 'pending',
          'text-green-600': layer.status === 'done',
        }"
      >{{ layer.label }}</span>
      <span v-if="idx < layers.length - 1" class="mx-1 text-gray-300">→</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

const layers = computed(() => {
  const status = store.requirementsState?.layer_status ?? {}
  return [
    { label: '愿景对齐', status: status['1'] ?? 'pending' },
    { label: '功能分解', status: status['2'] ?? 'pending' },
    { label: '细节补充', status: status['3'] ?? 'pending' },
  ]
})
</script>
```

- [ ] **Step 2: 创建 `ModeSelector.vue`**

```vue
<!-- src/components/ModeSelector.vue -->
<template>
  <div class="flex gap-1 mb-3">
    <button
      v-for="mode in modes"
      :key="mode.key"
      class="px-2 py-1 text-xs rounded border"
      :class="active === mode.key
        ? 'bg-blue-500 text-white border-blue-500'
        : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100'"
      @click="$emit('select', mode.key)"
    >{{ mode.label }}</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ active: string }>()
defineEmits<{ select: [mode: string] }>()

const modes = [
  { key: 'new', label: '🆕 新建' },
  { key: 'edit', label: '✏️ 编辑' },
  { key: 'append', label: '➕ 追加' },
]
</script>
```

- [ ] **Step 3: 创建 `cards/VisionCard.vue`**

```vue
<!-- src/components/cards/VisionCard.vue -->
<template>
  <div class="bg-white rounded-lg border p-4">
    <h3 class="text-base font-medium mb-3">📋 项目愿景</h3>

    <div class="space-y-3">
      <div>
        <label class="text-xs text-gray-500">项目名称</label>
        <input
          :value="vision?.project_name ?? ''"
          class="w-full border rounded px-2 py-1 text-sm mt-1"
          @input="emit('update:vision', { ...vision, project_name: ($event.target as HTMLInputElement).value })"
        />
      </div>

      <div>
        <label class="text-xs text-gray-500">👥 目标用户</label>
        <div v-for="(user, i) in vision?.target_users ?? []" :key="i" class="flex gap-1 mt-1">
          <input
            :value="user.role"
            class="flex-1 border rounded px-2 py-1 text-sm"
            placeholder="角色"
            @input="updateUser(i, 'role', ($event.target as HTMLInputElement).value)"
          />
          <input
            :value="user.description"
            class="flex-1 border rounded px-2 py-1 text-sm"
            placeholder="描述"
            @input="updateUser(i, 'description', ($event.target as HTMLInputElement).value)"
          />
          <button class="text-red-400 text-sm" @click="removeUser(i)">✕</button>
        </div>
        <button class="text-blue-500 text-xs mt-1" @click="addUser">+ 添加</button>
      </div>

      <div>
        <label class="text-xs text-gray-500">🎯 核心问题</label>
        <textarea
          :value="vision?.core_problem ?? ''"
          class="w-full border rounded px-2 py-1 text-sm mt-1"
          rows="2"
          @input="emit('update:vision', { ...vision, core_problem: ($event.target as HTMLTextAreaElement).value })"
        />
      </div>

      <div>
        <label class="text-xs text-gray-500">✅ 成功标准</label>
        <div v-for="(c, i) in vision?.success_criteria ?? []" :key="i" class="flex gap-1 mt-1">
          <input
            :value="c"
            class="flex-1 border rounded px-2 py-1 text-sm"
            @input="updateCriterion(i, ($event.target as HTMLInputElement).value)"
          />
          <button class="text-red-400 text-sm" @click="removeCriterion(i)">✕</button>
        </div>
        <button class="text-blue-500 text-xs mt-1" @click="addCriterion">+ 添加</button>
      </div>

      <div>
        <label class="text-xs text-gray-500">📐 范围说明</label>
        <textarea
          :value="vision?.scope_note ?? ''"
          class="w-full border rounded px-2 py-1 text-sm mt-1"
          rows="2"
          @input="emit('update:vision', { ...vision, scope_note: ($event.target as HTMLTextAreaElement).value })"
        />
      </div>
    </div>

    <div class="flex justify-between mt-4 pt-3 border-t">
      <button class="text-sm text-gray-500 hover:text-gray-700">✏️ 编辑</button>
      <button class="px-3 py-1 bg-blue-500 text-white text-sm rounded hover:bg-blue-600" @click="emit('confirm')">确认进入 →</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { VisionData } from '@/types/requirements'
import { useGenerationStore } from '@/stores/generation'

const props = defineProps<{ vision: VisionData | null }>()
const emit = defineEmits<{
  'update:vision': [data: VisionData]
  'confirm': []
}>()

const store = useGenerationStore()

function updateUser(index: number, field: string, value: string) {
  if (!props.vision) return
  const users = [...props.vision.target_users]
  users[index] = { ...users[index], [field]: value }
  emit('update:vision', { ...props.vision, target_users: users })
}

function addUser() {
  if (!props.vision) return
  emit('update:vision', {
    ...props.vision,
    target_users: [...props.vision.target_users, { role: '', description: '' }]
  })
}

function removeUser(index: number) {
  if (!props.vision) return
  const users = props.vision.target_users.filter((_, i) => i !== index)
  emit('update:vision', { ...props.vision, target_users: users })
}

function updateCriterion(index: number, value: string) {
  if (!props.vision) return
  const criteria = [...props.vision.success_criteria]
  criteria[index] = value
  emit('update:vision', { ...props.vision, success_criteria: criteria })
}

function addCriterion() {
  if (!props.vision) return
  emit('update:vision', { ...props.vision, success_criteria: [...props.vision.success_criteria, ''] })
}

function removeCriterion(index: number) {
  if (!props.vision) return
  const criteria = props.vision.success_criteria.filter((_, i) => i !== index)
  emit('update:vision', { ...props.vision, success_criteria: criteria })
}
</script>
```

- [ ] **Step 4: 创建 `cards/FeatureCard.vue`**

```vue
<!-- src/components/cards/FeatureCard.vue -->
<template>
  <div class="bg-white rounded-lg border p-4">
    <h3 class="text-base font-medium mb-3">🗂️ 功能模块</h3>

    <div class="space-y-2 mb-4">
      <div v-for="feat in features" :key="feat.id" class="border rounded p-2">
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium">{{ feat.name }}</span>
          <span
            class="text-xs px-1.5 py-0.5 rounded"
            :class="{
              'bg-red-100 text-red-700': feat.priority === 'must',
              'bg-yellow-100 text-yellow-700': feat.priority === 'should',
              'bg-gray-100 text-gray-500': feat.priority === 'nice',
            }"
          >{{ { must: '必须', should: '应该', nice: '锦上添花' }[feat.priority] }}</span>
        </div>
        <p class="text-xs text-gray-500 mt-1">{{ feat.description }}</p>
        <div class="mt-1 bg-gray-100 rounded-full h-1.5">
          <div class="bg-blue-500 rounded-full h-1.5" :style="{ width: feat.completeness + '%' }" />
        </div>
        <span class="text-xs text-gray-400">{{ feat.completeness }}%</span>
        <button
          v-if="feat.completeness < 80"
          class="ml-2 text-xs text-blue-500"
          @click="emit('supplement', feat.id)"
        >补充</button>
      </div>
    </div>

    <button class="text-sm text-blue-500 hover:text-blue-700" @click="emit('addFeature')">+ 添加功能模块</button>

    <h3 class="text-base font-medium mt-4 mb-2">🗺️ 页面结构</h3>
    <div class="pl-2 border-l-2 border-gray-200">
      <div v-for="page in pages" :key="page.id" class="text-sm py-0.5" :class="{ 'ml-4': page.parent_id }">
        📄 {{ page.name }}
        <span class="text-xs text-gray-400">({{ page.page_type }})</span>
      </div>
    </div>
    <button class="text-sm text-blue-500 hover:text-blue-700 mt-1" @click="emit('addPage')">+ 添加页面</button>

    <div class="flex justify-between mt-4 pt-3 border-t">
      <button class="text-sm text-gray-500">✏️ 编辑</button>
      <button class="px-3 py-1 bg-blue-500 text-white text-sm rounded" @click="emit('confirm')">确认进入 →</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { FeatureModule, PageNode } from '@/types/requirements'

defineProps<{
  features: FeatureModule[]
  pages: PageNode[]
}>()

const emit = defineEmits<{
  'supplement': [featureId: string]
  'addFeature': []
  'addPage': []
  'confirm': []
}>()
</script>
```

- [ ] **Step 5: 创建 `cards/DetailCard.vue`**

```vue
<!-- src/components/cards/DetailCard.vue -->
<template>
  <div class="bg-white rounded-lg border p-4">
    <h3 class="text-base font-medium mb-3">📝 页面详情</h3>

    <div class="mb-4">
      <select class="border rounded px-2 py-1 text-sm w-full" @change="selectPage(($event.target as HTMLSelectElement).value)">
        <option value="">选择页面...</option>
        <option v-for="p in pages" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div v-if="selectedPageId && pageDetail" class="space-y-3">
      <div>
        <label class="text-xs text-gray-500">展示字段</label>
        <div v-for="(f, i) in pageDetail.display_fields" :key="i" class="flex gap-1 mt-1 text-sm">
          <span class="w-24">{{ f.name }}</span>
          <span class="text-gray-400">{{ f.type }}</span>
          <span v-if="f.required" class="text-red-400">*</span>
        </div>
        <button class="text-xs text-blue-500 mt-1">+ 添加字段</button>
      </div>

      <div>
        <label class="text-xs text-gray-500">操作按钮</label>
        <div class="flex gap-1 mt-1 flex-wrap">
          <span v-for="(a, i) in pageDetail.action_buttons" :key="i"
            class="px-2 py-0.5 bg-gray-100 rounded text-sm">{{ a.label }}</span>
        </div>
        <button class="text-xs text-blue-500 mt-1">+ 添加操作</button>
      </div>

      <div>
        <label class="text-xs text-gray-500">关联数据</label>
        <div class="text-sm text-gray-600">{{ pageDetail.related_data.join(' · ') || '无' }}</div>
      </div>
    </div>

    <h3 class="text-base font-medium mt-4 mb-2">🔧 技术约束</h3>
    <div class="grid grid-cols-2 gap-2 text-sm">
      <div>
        <label class="text-xs text-gray-500">前端框架</label>
        <div class="border rounded px-2 py-1">{{ techConstraints?.framework || '待确认' }}</div>
      </div>
      <div>
        <label class="text-xs text-gray-500">组件库</label>
        <div class="border rounded px-2 py-1">{{ techConstraints?.component_lib || '待确认' }}</div>
      </div>
      <div>
        <label class="text-xs text-gray-500">数据来源</label>
        <div class="border rounded px-2 py-1">{{ techConstraints?.data_source || '待确认' }}</div>
      </div>
    </div>

    <h3 class="text-base font-medium mt-4 mb-2">📊 数据实体</h3>
    <div v-for="e in dataEntities" :key="e.name" class="border rounded p-2 mb-1 text-sm">
      <span class="font-medium">{{ e.name }}:</span>
      <span class="text-gray-500">{{ e.fields.map(f => f.name).join(' / ') }}</span>
    </div>

    <div class="flex justify-between mt-4 pt-3 border-t">
      <button class="text-sm text-gray-500">✏️ 编辑</button>
      <button class="px-3 py-1 bg-green-500 text-white text-sm rounded" @click="emit('generate')">生成需求文档 →</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { PageNode, PageDetail, TechConstraints, DataEntity } from '@/types/requirements'

const props = defineProps<{
  pages: PageNode[]
  pageDetails: Record<string, PageDetail>
  techConstraints: TechConstraints
  dataEntities: DataEntity[]
}>()

const emit = defineEmits<{ 'generate': [] }>()

const selectedPageId = ref('')

function selectPage(id: string) {
  selectedPageId.value = id
}

const pageDetail = computed(() => {
  if (!selectedPageId.value) return null
  return props.pageDetails[selectedPageId.value] ?? null
})
</script>
```

- [ ] **Step 6: 创建 `PRDGeneratorView.vue`**

```vue
<!-- src/components/PRDGeneratorView.vue -->
<template>
  <div class="bg-white rounded-lg border p-4 h-full overflow-auto">
    <div class="prose prose-sm max-w-none" v-html="renderedContent" />
    <div v-if="isStreaming" class="text-blue-500 text-sm mt-2">▊ 生成中...</div>
    <div v-if="!isStreaming && content" class="flex gap-2 mt-4 pt-3 border-t">
      <button class="px-3 py-1 text-sm border rounded hover:bg-gray-50" @click="$emit('edit')">📝 编辑补充</button>
      <button class="px-3 py-1 text-sm border rounded hover:bg-gray-50" @click="$emit('next')">🔀 进入详细设计</button>
      <button class="px-3 py-1 text-sm border rounded hover:bg-gray-50" @click="$emit('export')">📥 导出</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'

defineEmits<{ 'edit': []; 'next': []; 'export': [] }>()

const store = useGenerationStore()
const content = computed(() => store.prdStreamingContent)
const isStreaming = computed(() => store.isStreaming)

const renderedContent = computed(() => {
  // 简单的 markdown 渲染 — 实际应使用 markdown-it
  return content.value
    .replace(/### (.*)/g, '<h3 class="text-lg font-medium mt-4 mb-1">$1</h3>')
    .replace(/## (.*)/g, '<h2 class="text-xl font-bold mt-5 mb-2">$1</h2>')
    .replace(/# (.*)/g, '<h1 class="text-2xl font-bold mt-6 mb-3">$1</h1>')
    .replace(/- (.*)/g, '<li class="ml-4 text-sm">$1</li>')
    .replace(/\n\n/g, '<br/><br/>')
})
</script>
```

- [ ] **Step 7: 创建 `AnalysisPanel.vue`**

```vue
<!-- src/components/AnalysisPanel.vue -->
<template>
  <div class="h-full p-4 bg-gray-50 overflow-auto">
    <ModeSelector :active="mode" @select="onModeSelect" />
    <LayerProgress />

    <!-- Card Mode -->
    <div v-if="panelMode === 'card'" class="mt-4">
      <VisionCard
        v-if="currentLayer === 1"
        :vision="requirementsState?.vision ?? null"
        @update:vision="onVisionUpdate"
        @confirm="onLayerConfirm"
      />
      <FeatureCard
        v-else-if="currentLayer === 2"
        :features="requirementsState?.features ?? []"
        :pages="requirementsState?.pages ?? []"
        @supplement="onSupplement"
        @addFeature="onAddFeature"
        @addPage="onAddPage"
        @confirm="onLayerConfirm"
      />
      <DetailCard
        v-else-if="currentLayer === 3"
        :pages="requirementsState?.pages ?? []"
        :page-details="requirementsState?.page_details ?? {}"
        :tech-constraints="requirementsState?.tech_constraints ?? {} as any"
        :data-entities="requirementsState?.data_entities ?? []"
        @generate="onGeneratePRD"
      />
    </div>

    <!-- PRD Mode -->
    <PRDGeneratorView
      v-else-if="panelMode === 'prd'"
      @edit="onEditPRD"
      @next="onGoNextStage"
      @export="onExportPRD"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import type { VisionData } from '@/types/requirements'
import LayerProgress from './LayerProgress.vue'
import ModeSelector from './ModeSelector.vue'
import VisionCard from './cards/VisionCard.vue'
import FeatureCard from './cards/FeatureCard.vue'
import DetailCard from './cards/DetailCard.vue'
import PRDGeneratorView from './PRDGeneratorView.vue'

const store = useGenerationStore()

const requirementsState = computed(() => store.requirementsState)
const panelMode = computed(() => store.analysisPanelMode)
const currentLayer = computed(() => store.requirementsState?.layer ?? 1)
const mode = computed(() => store.requirementsState?.mode ?? 'new')

function onModeSelect(m: string) {
  // 发送模式切换事件 — 通过 ChatPanel 发送模式切换消息
  console.log('Mode selected:', m)
}

function onVisionUpdate(data: VisionData) {
  store.patchRequirementsState({ vision: data } as any)
}

function onLayerConfirm() {
  // 发送确认推进请求
  const { confirmStage } = (window as any).__multiAgent || {}
  if (confirmStage) confirmStage('analysis')
}

function onSupplement(featureId: string) {
  // 补充功能模块
  console.log('Supplement feature:', featureId)
}

function onAddFeature() {
  console.log('Add feature')
}

function onAddPage() {
  console.log('Add page')
}

function onGeneratePRD() {
  // 发送生成 PRD 请求
  onLayerConfirm()
}

function onEditPRD() {
  store.setAnalysisPanelMode('card')
}

function onGoNextStage() {
  onLayerConfirm()
}

function onExportPRD() {
  const blob = new Blob([store.prdStreamingContent], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'PRD.md'
  a.click()
  URL.revokeObjectURL(url)
}
</script>
```

---

### Task 11: 前端 — useStreamChat 扩展需求分析事件

**File:** Modify: `ai-design-platform-web/packages/ai-generation-app/src/composables/useStreamChat.ts`

- [ ] **Step 1: 在 SSE 事件 switch 中新增需求分析事件处理**

Add new cases in the `switch (eventType)` block inside `send()`:

```typescript
// --- 需求分析事件 ---

case 'requirement_layer_start':
  if (!store.requirementsState) break
  store.requirementsState.layer = event.layer
  store.requirementsState.layer_status[String(event.layer)] = 'active'
  break

case 'requirement_card_update':
  if (event.fields) {
    store.patchRequirementsState(event.fields)
  }
  break

case 'requirement_question':
  // 问题在 ChatPanel 消息中展示，progress 更新到 AnalysisPanel
  break

case 'requirement_layer_done':
  if (store.requirementsState) {
    store.requirementsState.layer_status[String(event.layer)] = 'done'
  }
  break

case 'prd_generate_start':
  store.setAnalysisPanelMode('prd')
  store.prdStreamingContent = ''
  break

case 'prd_section':
  store.appendPRDContent(event.content || '')
  break

case 'prd_section_complete':
  store.setPRDCurrentSection(null)
  break

case 'prd_diff':
  store.appendPRDDiff(event.change, event.section, event.content || '')
  break

case 'prd_diff_done':
  store.setPRDVersion(event.version)
  break

case 'prd_generate_done':
  store.setPRDVersion(event.version)
  store.setPRDComplete(event.full_content || '')
  store.setStageOutput('analysis', event.full_content || '')
  break
```

---

### Task 12: 前端 — GenerationView 集成 AnalysisPanel

**File:** Modify: `ai-design-platform-web/packages/ai-generation-app/src/views/GenerationView.vue`

- [ ] **Step 1: 在需求分析阶段显示 AnalysisPanel**

Find the right-side panel rendering in GenerationView.vue and add a condition for analysis stage:

```vue
<!-- In right panel area -->
<AnalysisPanel v-if="store.stage === 'analysis'" />
<StageOutput v-else-if="store.rightPanelView === 'stage-output'" ... />
<PreviewFrame v-else-if="store.rightPanelView === 'preview'" ... />
<FileExplorer v-else-if="store.rightPanelView === 'files'" ... />
```

Add the import:

```typescript
import AnalysisPanel from '@/components/AnalysisPanel.vue'
```

---

### Task 13: 端到端验证

- [ ] **Step 1: 启动后端验证导入无错误**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.requirements.state import RequirementsState; print('OK')"
python -c "from app.services.generation.requirements.layer_manager import LayerManager; print('OK')"
python -c "from app.services.generation.requirements.question_strategist import QuestionStrategist; print('OK')"
python -c "from app.services.generation.requirements.prd_generator import generate_prd_full; print('OK')"
```

- [ ] **Step 2: 启动前端验证编译无错误**

```bash
cd ai-design-platform-web
npx turbo run dev --filter=ai-generation-app
# 检查控制台无 import 错误
```

- [ ] **Step 3: 端到端测试脚本 — NEW 模式完整流程**

Write a test script to simulate a complete 3-layer dialogue:

```python
# test_requirements_flow.py
import asyncio
from app.services.generation.requirements.state import RequirementsState
from app.services.generation.requirements.layer_manager import LayerManager

def test_new_mode_flow():
    mgr = LayerManager()
    state = mgr.enter_new("我想做一个客户管理系统")

    assert state.mode == "new"
    assert state.layer == 1
    assert state.version == 1
    assert state.layer_status["1"] == "active"
    assert state.vision.project_name == "我想做一个客户管理系统"

    # Simulate Layer 1 completion
    state.vision.project_name = "CRM"
    state.vision.target_users = [{"role": "销售", "description": "销售团队"}]
    state.vision.core_problem = "客户跟进不及时"
    state.vision.success_criteria = ["一屏完成跟进"]

    assert mgr.is_layer_done() == True

    # Advance to Layer 2
    assert mgr.advance_layer() == True
    assert state.layer == 2

    # APPEND mode
    mgr2 = LayerManager()
    state2 = mgr2.enter_append(state, "再加一个审批模块")
    assert state2.mode == "append"
    assert state2.version == 2
    assert state2.parent_version == 1
    assert state2.layer == 2

    # Existing features should be confirmed
    assert len(state2.features) == len(state.features)

    print("PASS: All state machine tests passed")

test_new_mode_flow()
```

- [ ] **Step 4: 运行验证**

```bash
cd ai-design-platform-server/ai-service
python test_requirements_flow.py
```

Expected: `PASS: All state machine tests passed`
