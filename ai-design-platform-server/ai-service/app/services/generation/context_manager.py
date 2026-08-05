"""Context Manager — summarize and retrieve context for LLM sessions."""

import re
import structlog
from .tools.registry import ToolResult

logger = structlog.get_logger()

# Match Vue SFC exports: export default defineComponent, defineProps, defineEmits
_EXPORT_RE = re.compile(
    r'(export\s+(?:default\s+)?(?:defineComponent|function|class|const|let|var)\s+(\w+))|'
    r'(defineProps<([^>]+)>)|'
    r'(defineEmits<([^>]+)>)',
    re.MULTILINE,
)


def extract_interface_contract(file_path: str, content: str) -> dict:
    """Extract exports/props/events from a source file using regex (rule-engine, no LLM)."""
    contract = {
        "file": file_path,
        "exports": [],
        "props": None,
        "events": [],
    }

    for match in _EXPORT_RE.finditer(content):
        if match.group(2):  # export const/function/class name
            contract["exports"].append(match.group(2))
        if match.group(3):  # defineProps<...>
            contract["props"] = match.group(3).strip()

    # Check defineEmits specifically
    for m in re.finditer(r'defineEmits<([^>]+)>', content):
        contract["events"] = [e.strip() for e in m.group(1).split(",")]

    return contract


async def summarize_context(files: dict[str, str], max_tokens: int = 8000) -> ToolResult:
    """
    Compress generated files into structured summary.
    Uses rule-engine for contract extraction (no LLM tokens consumed).
    """
    summary_parts = []
    key_exports = {}
    total_lines = 0
    dropped_details = []

    for path, content in files.items():
        lines = content.count("\n") + 1
        total_lines += lines
        contract = extract_interface_contract(path, content)
        key_exports[path] = contract

        summary_parts.append(
            f"- {path}: {lines} lines, "
            f"exports={contract['exports']}, "
            f"props={contract['props']}, "
            f"events={contract['events']}"
        )

        if lines > 300:
            dropped_details.append({
                "file": path,
                "reason": f"Large file ({lines} lines), only interface contract retained",
            })

    summary = {
        "total_files": len(files),
        "total_lines": total_lines,
        "key_exports": key_exports,
        "file_list": summary_parts,
        "dropped_details": dropped_details,
    }

    return ToolResult(ok=True, data=summary)


async def retrieve_context(files: dict[str, str], query: str) -> ToolResult:
    """
    Search generated files for relevant context matching the query.
    Simple keyword-based retrieval (upgradeable to embedding-based).
    """
    query_lower = query.lower()
    query_terms = query_lower.split()
    results = []

    for path, content in files.items():
        content_lower = content.lower()
        score = sum(1 for term in query_terms if term in content_lower)
        if score > 0 or any(term in path.lower() for term in query_terms):
            # Extract relevant snippet
            idx = content_lower.find(query_terms[0]) if query_terms else 0
            start = max(0, idx - 100)
            end = min(len(content), idx + 500)
            snippet = content[start:end]
            results.append({
                "file": path,
                "content_snippet": snippet,
                "relevance": score,
            })

    results.sort(key=lambda r: r["relevance"], reverse=True)
    return ToolResult(ok=True, data={"results": results[:10]})


async def verify_contract(
    files: dict[str, str],
    consumer_file: str,
    provider_file: str,
    expected_interface: dict | None = None,
) -> ToolResult:
    """
    Verify that consumer_file correctly uses provider_file's exports.
    Checks: exports present, props passed, event names match.
    """
    # 5.3: expected_interface 必须显式提供 — 缺失时"零 violations → match=true"
    # 是空校验漏洞（vacuous pass），一律拒绝并给出明确错误。
    if not expected_interface or not isinstance(expected_interface, dict):
        return ToolResult(
            ok=False,
            error="expected_interface 未提供或为空：契约校验必须声明期望接口（exports/props/events）",
        )

    consumer_content = files.get(consumer_file, "")
    provider_content = files.get(provider_file, "")

    if not consumer_content or not provider_content:
        return ToolResult(ok=False, error="File not found in generated files")

    provider_contract = extract_interface_contract(provider_file, provider_content)
    violations = []

    # Check props
    if expected_interface:
        expected_props = expected_interface.get("props", {})
        if isinstance(expected_props, dict):
            for prop_name in expected_props:
                if prop_name not in consumer_content:
                    violations.append({
                        "type": "missing_prop",
                        "detail": f"{consumer_file} may not pass prop '{prop_name}' to {provider_file}",
                    })
        elif isinstance(expected_props, list):
            for prop_name in expected_props:
                if prop_name not in consumer_content:
                    violations.append({
                        "type": "missing_prop",
                        "detail": f"{consumer_file} may not pass prop '{prop_name}' to {provider_file}",
                    })

        # Check exports
        expected_exports = expected_interface.get("exports", [])
        for export_name in expected_exports:
            if export_name not in provider_contract["exports"]:
                violations.append({
                    "type": "missing_export",
                    "detail": f"{provider_file} missing expected export '{export_name}'",
                })

        # Check events — provider must emit the expected events (5.3 / 5a
        # review): defineEmits<('submit' | 'cancel')> → {'submit', 'cancel'}.
        expected_events = expected_interface.get("events", [])
        if isinstance(expected_events, list):
            provider_events = _normalized_event_names(provider_contract["events"])
            for event_name in expected_events:
                if event_name not in provider_events:
                    violations.append({
                        "type": "missing_event",
                        "detail": f"{provider_file} missing expected event '{event_name}'",
                    })

    match = len(violations) == 0
    return ToolResult(ok=True, data={"match": match, "violations": violations})


def _normalized_event_names(events: list) -> set[str]:
    """Normalize defineEmits expressions: ('submit' | 'cancel') → {submit, cancel}.

    Handles quoted union syntax (``'submit' | 'cancel'``, ``"submit"``) and
    paren-wrapped unions; object-literal emit types are a known heuristic miss
    (rule-engine, no LLM).
    """
    names: set[str] = set()
    for expr in events or []:
        for raw in str(expr).replace("|", ",").split(","):
            token = raw.strip().strip("'\"`()[] ")
            if token:
                names.add(token)
    return names
