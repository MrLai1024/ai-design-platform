import uuid
import hashlib
import json
import time
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Any
from collections.abc import Awaitable
import structlog

from .state import GenerationState, RollbackRecord

logger = structlog.get_logger()


@dataclass
class TraceSpan:
    trace_id: str
    node_name: str
    start_time: float = 0.0
    tokens_used: int = 0
    attributes: dict = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def record_error(self, error: Exception):
        self.attributes["error"] = str(error)


class Tracer:
    def __init__(self):
        self.spans: list[TraceSpan] = []

    def span(self, node_name: str) -> TraceSpan:
        span = TraceSpan(trace_id=str(uuid.uuid4()), node_name=node_name)
        self.spans.append(span)
        return span

    def summary(self) -> dict:
        total_tokens = sum(s.tokens_used for s in self.spans)
        total_time = sum(s.attributes.get("duration_ms", 0) for s in self.spans)
        return {
            "total_spans": len(self.spans),
            "total_tokens": total_tokens,
            "total_duration_ms": total_time,
            "spans": [
                {"node": s.node_name, "tokens": s.tokens_used, "trace_id": s.trace_id}
                for s in self.spans
            ],
        }


@dataclass
class RetryConfig:
    max_retries: int = 3
    backoff: float = 2.0


class AgentHarness:
    """Standard execution shell for every LangGraph node."""

    def __init__(self):
        self.tracer = Tracer()
        self.retry_config = RetryConfig()

    async def execute(
        self,
        node_name: str,
        state: GenerationState,
        handler: Callable[[GenerationState], Awaitable[GenerationState]],
    ) -> GenerationState:
        span = self.tracer.span(node_name)
        span.set_attribute("input_hash", self._hash_state(state))
        t0 = time.time()
        span.start_time = t0

        last_error = None
        for attempt in range(self.retry_config.max_retries):
            try:
                result = await handler(state)
                elapsed = (time.time() - t0) * 1000
                span.set_attribute("duration_ms", elapsed)
                span.set_attribute("attempts", attempt + 1)
                logger.info(
                    "node_complete",
                    node=node_name,
                    duration_ms=elapsed,
                    attempts=attempt + 1,
                )
                return result
            except Exception as e:
                last_error = e
                span.record_error(e)
                logger.warning(
                    "node_retry",
                    node=node_name,
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < self.retry_config.max_retries - 1:
                    await asyncio.sleep(self.retry_config.backoff ** attempt)

        logger.error("node_failed", node=node_name, error=str(last_error))
        raise last_error

    def _hash_state(self, state: GenerationState) -> str:
        raw = json.dumps(state, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    def get_summary(self) -> dict:
        return self.tracer.summary()


class LoopControl:
    """Convergence controller — prevents infinite rollback loops."""

    def __init__(
        self,
        max_rollback_per_node: int = 3,
        max_rollback_total: int = 10,
    ):
        self.max_rollback_per_node = max_rollback_per_node
        self.max_rollback_total = max_rollback_total

    def should_rollback(
        self, target_node: str, state: GenerationState
    ) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        allowed=False means the loop should stop (circuit break).
        """
        counts = state.get("rollback_count", {})

        # Rule 1: per-node limit
        node_count = counts.get(target_node, 0)
        if node_count >= self.max_rollback_per_node:
            return False, f"Node '{target_node}' rollback limit ({self.max_rollback_per_node}) reached"

        # Rule 2: global limit
        total = sum(counts.values())
        if total >= self.max_rollback_total:
            return False, f"Global rollback limit ({self.max_rollback_total}) reached"

        # Rule 3: no-improvement check
        records = state.get("rollback_records", [])
        if len(records) >= 2:
            last_two = records[-2:]
            if last_two[0]["to_node"] == target_node and last_two[1]["to_node"] == target_node:
                if last_two[0]["previous_output_hash"] == last_two[1]["previous_output_hash"]:
                    return False, "No improvement detected in consecutive rollbacks to same node"

        return True, ""

    @staticmethod
    def record_rollback(
        from_node: str,
        to_node: str,
        reason: str,
        previous_output_hash: str,
        token_cost: int,
    ) -> RollbackRecord:
        return RollbackRecord(
            rollback_id=str(uuid.uuid4()),
            from_node=from_node,
            to_node=to_node,
            reason=reason,
            previous_output_hash=previous_output_hash,
            token_cost=token_cost,
        )

    @staticmethod
    def apply_rollback(
        state: GenerationState, record: RollbackRecord
    ) -> GenerationState:
        counts = state.get("rollback_count", {})
        target = record["to_node"]
        counts[target] = counts.get(target, 0) + 1

        records = list(state.get("rollback_records", []))
        records.append(record)

        return {
            **state,
            "rollback_count": counts,
            "rollback_records": records,
        }


@dataclass
class CheckResult:
    passed: bool
    errors: list[str] = field(default_factory=list)


class EvalHarness:
    """Deterministic validation — no LLM involved."""

    @staticmethod
    def code_has_content(code: str | None) -> CheckResult:
        if not code or not code.strip():
            return CheckResult(False, ["Generated code is empty"])
        return CheckResult(True)

    @staticmethod
    def code_has_vue_template(code: str) -> CheckResult:
        """Check that generated code contains a <template> tag."""
        if "<template>" not in code:
            return CheckResult(False, ["Missing <template> in generated code"])
        return CheckResult(True)

    @staticmethod
    def design_has_sections(design: str | None) -> CheckResult:
        """Check that design doc has required sections."""
        if not design:
            return CheckResult(False, ["Design document is empty"])
        required = ["组件", "数据流", "样式"]
        missing = [s for s in required if s not in design]
        if missing:
            return CheckResult(False, [f"Design missing sections: {', '.join(missing)}"])
        return CheckResult(True)

    @staticmethod
    def validate(state: GenerationState, stage: str) -> CheckResult:
        """Run all checks for a given stage."""
        if stage == "code":
            code = state.get("code_result")
            r1 = EvalHarness.code_has_content(code)
            if not r1.passed:
                return r1
            return EvalHarness.code_has_vue_template(code)
        if stage == "design":
            return EvalHarness.design_has_sections(state.get("design_result"))
        return CheckResult(True)
