"""Tester — L 档验收先行测试生成与执行 (task 5.6, design D6).

L 档角色配置含 ``tester``（tier.py TIER_ACCEPTANCE["L"].roles），在 Verifier
L1-L3（+Debugger 修复轮）收敛后运行：**验收先行**生成单测/组件测试并尽力执行，
测试产物作为 Verifier 的 **L4 行为层** 证据（verifier.run_verifier 消费
``state["tester_result"]``）。

流程:

1. **生成** — LLM（llm_fn seam，``_llm_structured`` 结构化输出，fail-safe 到
   ``{"tests": []}``）依据架构 Spec（component_tree/pages/data_model）与已生成
   文件清单，输出 ``{path, content}`` 列表（vitest + @vue/test-utils 风格，
   ``src/__tests__/<Component>.spec.ts``）。断言验收先行：组件可挂载、关键
   props/emits 行为、关键交互元素存在（data-testid 选择器）。
2. **落盘** — 写入项目根目录（路径越界条目拒绝）。
3. **执行（best-effort）** — 环境可行性探测：``node`` 可执行文件 +
   monorepo web workspace 的 vitest（``ai-design-platform-web/packages/
   ai-generation-app/node_modules`` 自带 vitest / @vue/test-utils / happy-dom /
   @vitejs/plugin-vue）。可行则生成 ``vitest.config.ts``（alias 指到 workspace
   的 node_modules，已验证可跑），用 ``node <vitest>/vitest.mjs run
   --reporter=json`` 执行并解析 JSON 报告。**不可行/超时/崩溃 → 诚实的
   execution-pending 路径**（``executed: False + reason``），绝不假装成功，
   也不把"无法执行"算作失败（Verifier 记 ``l4_pending`` 文档化 deferral）。
   deferral 文档：生成项目无 node_modules，真实执行依赖 workspace 的 vitest
   存在；生成项目获得自有工具链后本执行机制自然变稳。

结果形状（``state["tester_result"]``，graph 以 ``tester_result`` 事件发射）::

    {
      "generated": [{"path": "src/__tests__/Login.spec.ts", "size": 123}],
      "executed": bool, "passed": bool | None,
      "failures": [{"file": ..., "message": ...}],
      "reason": str,          # deferral / 执行摘要（人类可读，诚实）
      "runner": str | None,   # vitest.mjs 绝对路径（已执行时）
    }

测试文件写入项目磁盘用于执行，但**不进** ``generated_files``/``code_result``：
``code_result`` 保持与 Verifier 验证过的代码绑定（output_signature 语义），
测试产物由 ``tester_result`` 状态字段与事件承载。

环境开关（文档化）:

- ``AI_GEN_TEST_EXECUTION_DISABLED=1`` — 强制 execution-pending（CI 确定性）。
- ``AI_GEN_VITEST_DIR`` — 覆盖 vitest node_modules 目录探测。
"""

from __future__ import annotations

import asyncio as _asyncio
import json as _json
import os as _os
import shutil as _shutil
import tempfile as _tempfile
import uuid as _uuid
from pathlib import Path

import structlog

from .brainstorm import _llm_structured

logger = structlog.get_logger()

# 执行超时（秒）—— 超出视为执行不可行（honest pending，不伪造结果）。
VITEST_TIMEOUT_S = 120

TESTER_PROMPT = """你是一个资深前端测试工程师，为 AI 生成的前端工程编写验收先行（acceptance-first）的单元/组件测试。

## 输入
- 架构 Spec（页面清单 / 组件树 / 数据模型 / API 契约）
- 已生成的文件清单（只测已生成的文件）

## 测试要求
- 技术栈：vitest + @vue/test-utils（import { describe, it, expect } from 'vitest'；import { mount } from '@vue/test-utils'）
- 测试文件放在 src/__tests__/<组件名>.spec.ts（与组件同名）
- 验收先行：断言组件能 mount（不抛错）、关键 props/emits 行为正确、关键交互元素存在（用 data-testid 选择器定位，如 wrapper.get('[data-testid="save-button"]')）
- 数据模型/工具逻辑（stores、api 模块的纯函数）写单测断言输入输出
- 不测未生成的文件；不 mock 组件库本身；断言用 expect(...).toBe(...) 风格
- 测试必须能独立运行（vitest 环境是 happy-dom）

## 输出格式（只输出一个 JSON 对象）
{"tests": [{"path": "src/__tests__/Login.spec.ts", "content": "<完整可执行的测试文件内容>"}]}
- path 必须是 src/__tests__/ 下的相对路径
- content 是完整测试文件（可直接被 vitest 执行）
- 无法生成任何测试时输出 {"tests": []}"""

# Structured-output schema（fail-safe 默认：垃圾输出 → 空 tests 列表）。
TESTER_SCHEMA: dict = {"tests": [{"path": "", "content": ""}]}

# vitest 配置模板 —— alias 指向 workspace node_modules 的实体文件
# （package.json exports 子路径无法用绝对路径 import，实验验证用 dist 实体文件）。
# 生成项目无 node_modules，测试文件里的 'vitest'/'vue'/'@vue/test-utils' 由此解析。
VITEST_CONFIG_TEMPLATE = """import {{ defineConfig }} from '{vitest}/vitest/dist/config.js'
import vue from '{vitest}/@vitejs/plugin-vue/dist/index.mjs'
import path from 'path'

export default defineConfig({{
  plugins: [vue()],
  test: {{
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts'],
  }},
  resolve: {{
    alias: {{
      '@': path.resolve(__dirname, 'src'),
      'vitest': '{vitest}/vitest/dist/index.js',
      'vue': '{vitest}/vue/dist/vue.runtime.esm-bundler.js',
      '@vue/test-utils': '{vitest}/@vue/test-utils/dist/vue-test-utils.cjs.js',
    }},
  }},
}})
"""


def build_tester_prompt(state: dict) -> str:
    """组装 Tester 的输入：Spec 关键段 + 已生成文件清单（不含全文，控 token）。"""
    parts = ["## 架构 Spec（关键段）"]
    spec = state.get("architecture_spec") or {}
    for key in ("tech_stack", "pages", "component_tree", "data_model", "api_contracts"):
        if spec.get(key) not in (None, {}, [], ""):
            parts.append(f"### {key}\n{_json.dumps(spec[key], ensure_ascii=False, indent=2)}")
    files = state.get("generated_files") or {}
    if files:
        listing = "\n".join(f"- {p}（{len(c)} 字符）" for p, c in files.items())
        parts.append(f"## 已生成的文件清单\n{listing}")
    else:
        parts.append("## 已生成的文件清单\n（空）")
    return "\n\n".join(parts)


async def generate_tests(state: dict, llm_fn=None) -> list[dict]:
    """LLM 生成测试（结构化输出，fail-safe）。``llm_fn`` 走 brainstorms 的
    ``_llm_structured`` seam（None → 单例 provider 路径），测试传 fake。
    """
    try:
        structured = await _llm_structured(
            TESTER_PROMPT, build_tester_prompt(state), TESTER_SCHEMA, llm_fn
        )
    except Exception as e:
        logger.warning("tester_generate_failed", error=str(e))
        return []
    tests = structured.get("tests") or []
    return [
        t for t in tests
        if isinstance(t, dict) and (t.get("path") or "").strip() and (t.get("content") or "")
    ]


def write_tests(project_root: str, tests: list[dict]) -> list[dict]:
    """把测试文件写入项目根目录（路径越界/绝对路径条目拒绝）。

    返回 ``[{path, size}]``（实际落盘的条目）。路径防护复用
    ``file_tools.safe_project_path``（单一来源，review M4）。
    """
    from .tools.file_tools import safe_project_path

    written: list[dict] = []
    for t in tests or []:
        path = (t.get("path") or "").strip()
        content = t.get("content") or ""
        full = safe_project_path(project_root, path)
        if full is None:
            logger.warning("tester_path_rejected", path=path)
            continue
        _os.makedirs(_os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        written.append({"path": path, "size": len(content)})
    return written


def _find_vitest_dir() -> Path | None:
    """定位含 vitest 的 node_modules 目录（best-effort runner 的依赖源）。

    候选（按序）：``AI_GEN_VITEST_DIR`` 环境变量 → 向上逐级找
    ``ai-design-platform-web/packages/ai-generation-app/node_modules``
    （该 workspace 自带 vitest / @vue/test-utils / happy-dom / plugin-vue）。
    """
    env = _os.environ.get("AI_GEN_VITEST_DIR")
    if env:
        p = Path(env)
        if (p / "vitest").is_dir():
            return p
    for anc in Path(__file__).resolve().parents:
        cand = anc / "ai-design-platform-web" / "packages" / "ai-generation-app" / "node_modules"
        if (cand / "vitest").is_dir():
            return cand
    return None


def write_vitest_config(project_root: str, vitest_dir: Path) -> str:
    """生成项目的 vitest.config.ts（alias → workspace node_modules 实体文件）。

    返回配置文件路径。模板已实验验证：生成的测试项目能在无 node_modules
    的情况下用 workspace vitest 真实执行。
    """
    config_path = _os.path.join(project_root, "vitest.config.ts")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(VITEST_CONFIG_TEMPLATE.format(vitest=vitest_dir.as_posix()))
    return config_path


def _parse_vitest_report(report: dict) -> tuple[bool, list[dict], str]:
    """从 vitest JSON 报告解析 (passed, failures, summary)。

    失败收集三层：断言级（assertionResults 中非 passed 项）+ 文件级解析失败
    （如 import 无法解析 —— 此时 assertionResults 为空但 suite 状态为 failed
    且带 message）+ 报告级（testResults 为空时暴露顶层 message，如
    "No test files found"，让 gate 理由 / Debugger 拿到细节）。报告不可解析/
    为空 → 视为执行异常（failures 空、passed False、reason 记录），诚实反映
    "有执行但无结论"。
    """
    failures: list[dict] = []
    for suite in report.get("testResults") or []:
        for a in suite.get("assertionResults") or []:
            if a.get("status") not in ("passed", "skipped", "pending", "todo"):
                failures.append({
                    "file": a.get("fullName") or a.get("title") or "",
                    "message": ((a.get("failureMessages") or [""])[0] or "")[:1000],
                })
        if suite.get("status") == "failed" and suite.get("message") and not (
            suite.get("assertionResults")
        ):
            failures.append({
                "file": suite.get("name") or "",
                "message": (suite.get("message") or "")[:1000],
            })
    summary = (
        f"vitest: {report.get('numPassedTests', 0)} 通过 / "
        f"{report.get('numFailedTests', 0)} 失败"
    )
    if not report.get("testResults"):
        # 5.6 review M3b: 报告级失败（无 testResults）→ 顶层 message 进 failures。
        msg = report.get("message") or "测试未执行（vitest 报告无 testResults）"
        failures.append({"file": "", "message": (msg or "")[:1000]})
        return False, failures, summary
    passed = bool(report.get("success", False)) and not failures
    return passed, failures, summary


async def _launch_vitest(project_root: str, node: str, vitest_mjs: str) -> dict:
    """启动 vitest 子进程并解析 JSON 报告（测试可 monkeypatch 此函数模拟执行）。

    返回 ``{executed, passed, failures, reason}``。报告写到系统临时目录的
    每运行唯一路径，解析后清理 —— 生成项目根目录不残留携带 failureMessages
    的 vitest-result.json（review M3a）。
    """
    # 每运行唯一：并发 generation 不会互相覆盖输出文件。
    result_path = _os.path.join(
        _tempfile.gettempdir(),
        f"ai-gen-vitest-{_os.getpid()}-{_uuid.uuid4().hex[:8]}.json",
    )
    args = [
        node, vitest_mjs, "run",
        # vitest 的 root 默认取进程 cwd（非 config 位置）—— 显式指向生成项目，
        # 否则 include 会相对 ai-service 的 cwd 扫描，永远"找不到测试文件"。
        "--root", project_root,
        "--config", _os.path.join(project_root, "vitest.config.ts"),
        "--reporter", "json",
        "--outputFile", result_path,
    ]
    try:
        try:
            proc = await _asyncio.create_subprocess_exec(
                *args,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return {
                "executed": False, "passed": None, "failures": [],
                "reason": f"vitest 无法启动：{e}（文档化 deferral）",
            }
        try:
            _stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=VITEST_TIMEOUT_S)
        except _asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "executed": False, "passed": None, "failures": [],
                "reason": f"vitest 执行超时（>{VITEST_TIMEOUT_S}s，已终止）（文档化 deferral）",
            }
        if proc.returncode not in (0, 1):
            return {
                "executed": False, "passed": None, "failures": [],
                "reason": f"vitest 进程异常退出（exit={proc.returncode}）："
                          f"{(stderr or b'')[:400].decode(errors='replace')}（文档化 deferral）",
            }
        try:
            with open(result_path, encoding="utf-8") as f:
                report = _json.load(f)
        except (OSError, _json.JSONDecodeError) as e:
            # 报告未产出/不可解析（如 "No test files found" 提前退出）——
            # stderr 尾部进 reason，让 gate 理由 / Debugger 拿到细节（M3b）。
            return {
                "executed": False, "passed": None, "failures": [],
                "reason": f"vitest 未产出可解析报告：{e}；"
                          f"stderr: {(stderr or b'')[:300].decode(errors='replace')}（文档化 deferral）",
            }
        passed, failures, summary = _parse_vitest_report(report)
        return {"executed": True, "passed": passed, "failures": failures, "reason": summary}
    finally:
        if _os.path.exists(result_path):
            try:
                _os.remove(result_path)
            except OSError:
                pass


async def run_tests(project_root: str) -> dict:
    """Best-effort 执行：探测环境 → 写配置 → 启动 vitest → 解析报告。

    任一环节不可行都走诚实的 execution-pending 路径（``executed: False`` +
    ``reason``），不伪造成功。deferral 文档见模块 docstring。
    """
    if _os.environ.get("AI_GEN_TEST_EXECUTION_DISABLED"):
        return {
            "executed": False, "passed": None, "failures": [],
            "reason": "测试执行已禁用（AI_GEN_TEST_EXECUTION_DISABLED=1）—— 文档化 deferral",
        }
    node = _shutil.which("node")
    if not node:
        return {
            "executed": False, "passed": None, "failures": [],
            "reason": "环境无 node 可执行文件 —— 测试执行不可行（文档化 deferral）",
        }
    vitest_dir = _find_vitest_dir()
    if vitest_dir is None:
        return {
            "executed": False, "passed": None, "failures": [],
            "reason": "未找到可用 vitest（AI_GEN_VITEST_DIR 或 web workspace node_modules 均无）"
                      "—— 测试执行不可行（文档化 deferral）",
        }
    vitest_mjs = vitest_dir / "vitest" / "vitest.mjs"
    write_vitest_config(project_root, vitest_dir)
    result = await _launch_vitest(project_root, node, str(vitest_mjs))
    result["runner"] = str(vitest_mjs)
    logger.info(
        "tester_execution",
        executed=result["executed"], passed=result["passed"],
        failures=len(result["failures"]), reason=result["reason"],
    )
    return result


async def run_tester(state: dict, project_root: str, llm_fn=None) -> dict:
    """L 档 Tester 全流程：生成 → 落盘 → 尽力执行 → 结果。

    ``llm_fn`` 线程 graph 的 provider seam（None → 单例）。返回
    ``tester_result`` 形状（见模块 docstring），graph 以此发 ``tester_result``
    事件并存 ``state["tester_result"]`` 供 Verifier L4 消费。
    """
    tests = await generate_tests(state, llm_fn)
    if not tests:
        logger.warning("tester_no_tests_generated")
        return {
            "generated": [], "executed": False, "passed": None, "failures": [],
            "reason": "未生成测试（LLM 输出为空或解析失败，fail-safe）—— 无 L4 证据",
            "runner": None,
        }
    generated = write_tests(project_root, tests)
    if not generated:
        return {
            "generated": [], "executed": False, "passed": None, "failures": [],
            "reason": "测试生成后全部被路径校验拒绝（越界/绝对路径）—— 无 L4 证据",
            "runner": None,
        }
    exec_result = await run_tests(project_root)
    return {
        "generated": generated,
        "executed": exec_result["executed"],
        "passed": exec_result["passed"],
        "failures": exec_result["failures"],
        "reason": exec_result["reason"],
        "runner": exec_result.get("runner"),
    }
