"""Verifier — 四层验证信号 (task 5.4 / 5.7).

Runs after the code phase's executor rounds (before the final gate). All four
signals are deterministic (zero-LLM) — the Verifier is the independent
backstop the reviewers asked for: the Executor self-checks per task (5.3),
the Verifier re-checks the whole code phase:

- **L1 编译**: EvalHarness content/template checks + the ``compile_project``
  tool (which surfaces the real esbuild errors the frontend bundler reported
  via ``ReportCompileFeedback`` → ``registry.get_frontend_compile_errors()``).
- **L2 契约**: for each task with a contract, ``verify_contract`` re-run over
  the generated files — self-exports check + consumer/provider pairs from the
  task's deps. (The rule-engine is shared with the executor's own check; the
  Verifier's job is that the check actually ran and passed on final output.)
- **L3 运行时**: runtime errors reported by the preview iframe (console
  errors / uncaught exceptions / failed network requests) via
  ``ReportRuntimeFeedback`` → ``registry.get_runtime_errors()``. Empty = pass.
- **L4 行为** (5.6, 仅 L 档): Tester 的单测/组件测试执行结果
  (``state["tester_result"]``)。语义（诚实，见 tester.py）:
  - 无 tester_result（L4 以下档位）→ ``l4_ok: True``（无测试预期）。
  - 测试已生成且已执行 → ``l4_ok = passed``；失败进 evidence.test_failures。
  - 测试已生成但执行不可行（环境无 node/vitest，文档化 deferral）→
    ``l4_ok: True`` 且 ``l4_pending: True`` —— 不把"无法执行"当作失败，
    也不假装成功（deferral 记录在 tester_result.reason / l4_pending 字段）。
  - 测试生成失败（LLM fail-safe 空 / 路径被拒）→ 同 deferred（无 L4 证据）。
- **埋点钩子** (5.7): scan generated ``.vue`` files — key interactive
  elements (buttons, inputs, links/nav, pagination, tabs, dialogs…) missing a
  semantic ``data-testid`` are violations. Implemented as its own
  ``hooks_ok`` signal (dedicated layer, distinct ``hook_violations`` evidence).

Result shape (stored in state as ``verifier_result``):

    {
      "l1_ok": bool, "l2_ok": bool, "l3_ok": bool, "l4_ok": bool,
      "l4_pending": bool, "hooks_ok": bool,
      "evidence": {
        "compile_errors": [{"file", "line", "message"}],
        "contract_violations": [{"type", "task_id", "file", "detail"}],
        "runtime_errors": [{"type", "message", "stack"?}],
        "test_failures": [{"file", "message"}],   # L4（Tester 产物）
        "hook_violations": [{"file", "tag", "line", "snippet"}],
      },
      "passed": bool,           # all five signals (L1-L4 + hooks)
      "tier": str | None,
    }

The code gate (``manager.run_l1_checks``) consumes ``verifier_result``: any
failed signal surfaces as an L1 gate error with evidence, so a verifier
failure redo carries the diagnosis card.
"""

from __future__ import annotations

import hashlib
import json
import re

import structlog

from .harness import EvalHarness

logger = structlog.get_logger()

# 关键交互元素（5.7）—— 语义化 data-testid 钩子埋点范围。Vue 原生标签 +
# Element Plus 交互组件（generated code 中出现的原始标签形式）。
_INTERACTIVE_TAGS = (
    "button", "input", "select", "textarea", "nav", "a",
    "el-button", "el-input", "el-select", "el-pagination", "el-tabs",
    "el-tab-pane", "el-dialog", "el-menu", "el-menu-item", "el-link",
    "el-radio", "el-checkbox", "el-switch", "el-date-picker", "el-upload",
    "el-dropdown", "el-dropdown-item", "el-color-picker", "el-rate",
    "el-slider", "el-cascader", "el-input-number", "el-autocomplete",
    "el-table", "el-tree",
    "router-link",
)

# `<tag` + 属性区 —— 属性值中的 `>` 不终止标签（引号包裹的内容整体跳过）；
# re.S 允许跨行标签。属性区不含 data-testid 即为违规。
_INTERACTIVE_TAG_RE = re.compile(
    r"<(?P<tag>" + "|".join(_INTERACTIVE_TAGS) + r")\b(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)>",
    re.S,
)


def scan_hooks(files: dict[str, str]) -> list[dict]:
    """5.7 埋点钩子检查 — 扫描 .vue 文件，返回缺 data-testid 的违规列表。

    Deterministic, no LLM. Each violation: ``{file, tag, line, snippet}``.
    启发式边界（文档化）：对源码做正则扫描 —— 模板字符串 / v-html 内容中的
    交互标签会被误报（倾向多报 → 引导补钩子，符合"关键交互元素缺少
    data-testid 视为验证失败项"）；``<a>`` 无 href、``<input type=hidden>``
    不算关键交互元素，跳过。
    """
    violations: list[dict] = []
    for path, content in files.items():
        if not path.endswith(".vue"):
            continue
        for m in _INTERACTIVE_TAG_RE.finditer(content):
            tag = m.group("tag")
            attrs = m.group("attrs") or ""
            if "data-testid" in attrs:
                continue
            # 非关键交互元素过滤
            if tag == "a" and not re.search(r"\bhref=", attrs):
                continue
            if tag == "input" and re.search(r"type\s*=\s*[\"']hidden[\"']", attrs):
                continue
            line = content.count("\n", 0, m.start()) + 1
            snippet = m.group(0).strip()[:120]
            violations.append({"file": path, "tag": tag, "line": line, "snippet": snippet})
    return violations


async def check_contracts(state: dict, files: dict[str, str]) -> list[dict]:
    """L2 契约验证 — 对每个带契约的任务做独立兜底校验。

    Pairs are derived deterministically from the task DAG (task deps +
    self-exports), mirroring the executor's own verify_contract usage:
    consumer = 任务第一个已生成文件, provider = 依赖任务第一个已生成文件。
    """
    from .context_manager import verify_contract as _verify_contract

    violations: list[dict] = []
    dag = state.get("planner_dag") or {}
    for task in dag.get("tasks", []):
        contract = task.get("contract") or {}
        if not contract:
            continue
        task_id = task.get("id", "?")
        task_files = [f for f in (task.get("files") or []) if f in files]
        # Review fix (Important): 逐路径标记缺失 —— executor 可能在文件缺失时
        # 仍返回 done（files_ok 未被消费），全有全无判断会漏掉部分缺失。
        for missing in (task.get("files") or []):
            if missing not in files:
                violations.append({
                    "type": "missing_file",
                    "task_id": task_id,
                    "file": missing,
                    "detail": f"任务 {task_id} 的契约文件未生成：{missing}",
                })
        if not task_files:
            continue  # 无已生成文件可做契约比对（缺失项已逐条上报）
        consumer = task_files[0]

        # 自身导出契约自检：contract.exports 必须出现在生成文件中。
        expected_exports = contract.get("exports") or []
        if expected_exports:
            res = await _verify_contract(
                files, consumer, consumer, {"exports": expected_exports}
            )
            if not res.ok:
                violations.append({
                    "type": "verify_error", "task_id": task_id, "file": consumer,
                    "detail": res.error or "契约自检失败",
                })
            else:
                for v in (res.data or {}).get("violations", []):
                    violations.append({**v, "task_id": task_id, "file": consumer})

        # 依赖对：consumer = 本任务文件, provider = 依赖任务文件。
        for dep_id in task.get("deps") or []:
            dep_task = next(
                (t for t in dag.get("tasks", []) if t.get("id") == dep_id), None
            )
            if not dep_task:
                continue
            dep_files = [f for f in (dep_task.get("files") or []) if f in files]
            if not dep_files:
                continue
            res = await _verify_contract(files, consumer, dep_files[0], contract)
            if not res.ok:
                violations.append({
                    "type": "verify_error", "task_id": task_id, "file": consumer,
                    "detail": res.error or "依赖契约校验失败",
                })
                continue
            for v in (res.data or {}).get("violations", []):
                violations.append({
                    **v, "task_id": task_id, "file": consumer,
                    "pair": f"{consumer} → {dep_files[0]}",
                })
    return violations


def evidence_signature(evidence: dict) -> str:
    """Hash of the verifier evidence — the Debugger's no-progress detection key.

    Same evidence across fix rounds (compile errors / contract violations /
    runtime errors / hook violations all identical) ⇒ fixing is not making
    progress ⇒ escalate to the Manager gate instead of looping.
    """
    raw = json.dumps(evidence, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


async def run_verifier(
    state: dict,
    registry,
    tier: str | None = None,
    llm_fn=None,  # kept for signature symmetry; all four signals are deterministic
) -> dict:
    """Run the four-layer verification (+ hooks) over the code phase's output.

    ``registry`` is the active code-phase ToolRegistry (compile feedback +
    runtime feedback channels live on it). L4 行为 (tests) is consumed from
    ``state["tester_result"]`` — produced by the Tester (5.6, L 档), whose
    honest execution-pending path maps to ``l4_pending`` (not a failure, not
    a fake pass — see module docstring for the semantics).
    """
    files = state.get("generated_files") or {}

    # ── L1 编译（确定性的第一道信号） ──
    l1_errors: list[dict] = []
    harness = EvalHarness.validate(state, "code")
    for e in harness.errors:
        l1_errors.append({"file": "", "line": 0, "message": e})
    compile_result = await registry.invoke("compile_project", {})
    if not compile_result.ok:
        for err in (compile_result.data or {}).get("errors", []) or []:
            if isinstance(err, dict):
                l1_errors.append({
                    "file": err.get("file", ""),
                    "line": err.get("line", 0),
                    "message": err.get("text") or err.get("message", ""),
                })
    # 前端 bundler 实时上报的错误（与 compile_project 同源，去重保留）。
    seen = {(e.get("file"), e.get("line"), e.get("message")) for e in l1_errors}
    for err in registry.get_frontend_compile_errors():
        norm = {
            "file": err.get("file", ""),
            "line": err.get("line", 0),
            "message": err.get("text") or err.get("message", ""),
        }
        key = (norm["file"], norm["line"], norm["message"])
        if key not in seen:
            l1_errors.append(norm)
            seen.add(key)
    l1_ok = not l1_errors

    # ── L2 契约 ──
    contract_violations = await check_contracts(state, files)
    l2_ok = not contract_violations

    # ── L3 运行时（前端 sandbox 上报） ──
    runtime_errors = list(registry.get_runtime_errors() or [])
    l3_ok = not runtime_errors

    # ── L4 行为（5.6：Tester 产物，仅 L 档产生） ──
    # 语义（诚实）：无测试产物 → True（无测试预期）；已生成+已执行 → 按
    # passed 判定；已生成+执行不可行（deferral）→ True + l4_pending（不把
    # "无法执行"当作失败，也不假装成功）。
    tester_result = state.get("tester_result")
    test_failures: list[dict] = []
    l4_pending = False
    if tester_result and tester_result.get("generated"):
        if tester_result.get("executed"):
            l4_ok = bool(tester_result.get("passed"))
            for f in tester_result.get("failures") or []:
                if isinstance(f, dict):
                    test_failures.append({"file": f.get("file", ""), "message": f.get("message", "")})
                else:
                    test_failures.append({"file": "", "message": str(f)})
        else:
            # 执行不可行（环境无 node/vitest 等，tester_result.reason 已记录）。
            l4_ok = True
            l4_pending = True
    elif tier == "L" and tester_result is not None:
        # 5.6 review I2（docstring/实现对齐）: L 档 Tester 已运行但零测试产物
        # （LLM fail-safe 空 / 路径被拒）—— 行为层无任何证据，诚实记为
        # pending，而不是假装"无测试预期"地静默通过。
        l4_ok = True
        l4_pending = True
    else:
        l4_ok = True
        l4_pending = False

    # ── 埋点钩子（5.7） ──
    # 8.3 (review I2): 增量模式只扫描本次变更触碰的文件 —— 存量文件只做
    # 编译回归 (L1, 全项目), 埋点钩子检查不做 (旧版生成的应用可能早于 5.7
    # 埋点标准, 全量扫描会把"未触碰存量"误判为本次实现失败, 触发整仓重生成,
    # 违反"只动受影响模块")。L2 契约本就按 delta 任务文件校验, 天然增量。
    if state.get("incremental_mode"):
        existing = ((state.get("incremental_context") or {}).get("generated_files")) or {}
        scan_files = {
            path: content for path, content in files.items()
            if path not in existing or existing.get(path) != content
        }
    else:
        scan_files = files
    hook_violations = scan_hooks(scan_files)
    hooks_ok = not hook_violations

    # 5.4 review fix (Critical): 把裁决与它验证过的输出绑定 —— output_signature
    # 与 manager._output_signature(state, "code") 同源（code_result 的 hash）。
    # 代码被重新生成（如 gate redo → code_node 整仓重写）后签名变化，gate 不再
    # 消费这份 stale verdict —— 否则 verifier 失败会形成永久的 redo 循环。
    from .manager import _output_signature

    result = {
        "l1_ok": l1_ok,
        "l2_ok": l2_ok,
        "l3_ok": l3_ok,
        "l4_ok": l4_ok,
        "l4_pending": l4_pending,
        "hooks_ok": hooks_ok,
        "evidence": {
            "compile_errors": l1_errors,
            "contract_violations": contract_violations,
            "runtime_errors": runtime_errors,
            "test_failures": test_failures,
            "hook_violations": hook_violations,
        },
        "passed": l1_ok and l2_ok and l3_ok and l4_ok and hooks_ok,
        "tier": tier,
        "output_signature": _output_signature(state, "code"),
    }
    logger.info(
        "verifier_result",
        l1_ok=l1_ok, l2_ok=l2_ok, l3_ok=l3_ok, l4_ok=l4_ok, hooks_ok=hooks_ok,
        l4_pending=l4_pending,
        compile_errors=len(l1_errors), contract_violations=len(contract_violations),
        runtime_errors=len(runtime_errors), test_failures=len(test_failures),
        hook_violations=len(hook_violations),
    )
    return result
