"""Tests for NodeHandler ABC and NodeRegistry."""

import pytest
from typing import Callable

from app.services.workflow.handlers import NodeHandler
from app.services.workflow.registry import NodeRegistry
from app.services.workflow.ir_types import NodeDef


# ---------------------------------------------------------------------------
# Mock handler for testing
# ---------------------------------------------------------------------------

class MockLLMHandler(NodeHandler):
    """A real NodeHandler subclass used in tests."""

    node_type = "llm"

    async def execute(self, state: dict, config: dict) -> dict:
        return {"mock_output": "executed"}

    def compile_to_langgraph(self, node_def: NodeDef) -> Callable:
        async def node_fn(state: dict) -> dict:
            return await self.execute(state, node_def.config)
        return node_fn


class MockRouterHandler(NodeHandler):
    """Another real NodeHandler subclass for multi-handler tests."""

    node_type = "router"

    async def execute(self, state: dict, config: dict) -> dict:
        return {"route": "branch_a"}

    def compile_to_langgraph(self, node_def: NodeDef) -> Callable:
        async def node_fn(state: dict) -> dict:
            return await self.execute(state, node_def.config)
        return node_fn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNodeHandlerABC:
    """Verify that NodeHandler enforces the abstract interface."""

    def test_cannot_instantiate_abstract_handler(self):
        """Instantiating NodeHandler directly should raise TypeError."""
        with pytest.raises(TypeError):
            NodeHandler()  # type: ignore[abstract]

    def test_concrete_subclass_is_instantiable(self):
        """A subclass implementing all abstracts should instantiate fine."""
        handler = MockLLMHandler()
        assert handler.node_type == "llm"

    def test_missing_abstract_method_raises(self):
        """A subclass that doesn't implement execute should fail to instantiate."""
        with pytest.raises(TypeError):

            class _(NodeHandler):
                node_type = "broken"

            _()  # type: ignore[abstract]


class TestNodeRegistry:
    """Verify NodeRegistry register / lookup / list_types / reset."""

    def setup_method(self):
        NodeRegistry.reset()

    def teardown_method(self):
        NodeRegistry.reset()

    # -- register + lookup ---------------------------------------------------

    def test_register_and_lookup_returns_same_handler(self):
        handler = MockLLMHandler()
        NodeRegistry.register(handler)
        found = NodeRegistry.lookup("llm")
        assert found is handler

    def test_register_multiple_handlers(self):
        llm = MockLLMHandler()
        router = MockRouterHandler()
        NodeRegistry.register(llm)
        NodeRegistry.register(router)
        assert NodeRegistry.lookup("llm") is llm
        assert NodeRegistry.lookup("router") is router

    # -- unknown type --------------------------------------------------------

    def test_lookup_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown node type"):
            NodeRegistry.lookup("nonexistent")

    # -- list_types ----------------------------------------------------------

    def test_list_types_returns_all_registered_types(self):
        NodeRegistry.register(MockLLMHandler())
        NodeRegistry.register(MockRouterHandler())
        types = NodeRegistry.list_types()
        assert set(types) == {"llm", "router"}

    def test_list_types_empty_initially(self):
        assert NodeRegistry.list_types() == []

    # -- reset ---------------------------------------------------------------

    def test_reset_clears_all_handlers(self):
        NodeRegistry.register(MockLLMHandler())
        NodeRegistry.reset()
        assert NodeRegistry.list_types() == []
        with pytest.raises(ValueError):
            NodeRegistry.lookup("llm")
