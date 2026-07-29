"""ToolRegistry — 注册/查找/调用工具."""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from typing import Any, Callable, Awaitable
import structlog

logger = structlog.get_logger()


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable['ToolResult']]
    category: str  # "file" | "compile" | "mcp" | "skill"


@dataclass
class ToolResult:
    ok: bool
    data: Any | None = None
    error: str | None = None


class ToolRegistry:
    """Manages all available tools for the LLM orchestrator."""

    def __init__(self, project_root: str = "/tmp/ai-gen"):
        self.project_root = project_root
        self._generated_files: dict[str, str] = {}
        # 前端 bundler 上报的真实编译错误（esbuild 精确报错）
        self._frontend_compile_errors: list[dict] = []
        self._tools: dict[str, ToolDef] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        from .file_tools import create_file, write_code, delete_file
        from .compile_tool import compile_project, get_compile_errors
        from .skill_loader import SkillLoader
        from .mcp_bridge import MCPBridge

        self._skill_loader = SkillLoader()
        self._mcp_bridge = MCPBridge()

        self.register(ToolDef(
            name="create_file",
            description="创建一个新文件。用于初始化工程文件骨架。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，如 components/Header.vue"},
                    "language": {"type": "string", "description": "文件语言: vue | ts | js | css"},
                },
                "required": ["path"],
            },
            handler=lambda **kw: create_file(self.project_root, **kw),
            category="file",
        ))

        self.register(ToolDef(
            name="write_code",
            description="向文件写入代码。可以创建新文件或覆盖已有文件内容。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的完整代码"},
                },
                "required": ["path", "content"],
            },
            handler=lambda **kw: write_code(self.project_root, **kw),
            category="file",
        ))

        self.register(ToolDef(
            name="delete_file",
            description="删除一个文件。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件路径"},
                },
                "required": ["path"],
            },
            handler=lambda **kw: delete_file(self.project_root, **kw),
            category="file",
        ))

        self.register(ToolDef(
            name="compile_project",
            description="编译整个前端工程，返回编译错误列表。错误来自前端 esbuild 真实打包结果。",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: compile_project(self.project_root, frontend_errors=self._frontend_compile_errors, **kw),
            category="compile",
        ))

        self.register(ToolDef(
            name="get_compile_errors",
            description="获取最近一次编译的错误详情。",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: get_compile_errors(self.project_root, frontend_errors=self._frontend_compile_errors, **kw),
            category="compile",
        ))

        self.register(ToolDef(
            name="mcp_query",
            description="查询外部 MCP 服务获取组件文档、API 规范等。可用服务: component-docs, design-tokens, type-registry。",
            parameters={
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务名"},
                    "query": {"type": "string", "description": "查询内容"},
                },
                "required": ["server", "query"],
            },
            handler=lambda **kw: self._mcp_bridge.query(**kw),
            category="mcp",
        ))

        self.register(ToolDef(
            name="use_skill",
            description="应用一个 Skill 模板生成代码骨架。可用 Skills: crud-page, form-validation, data-dashboard, auth-guard, file-upload, responsive-layout。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill 名称"},
                    "params": {"type": "object", "description": "Skill 参数"},
                },
                "required": ["name"],
            },
            handler=lambda **kw: self._skill_loader.apply(**kw),
            category="skill",
        ))

        self.register(ToolDef(
            name="list_skills",
            description="列出所有可用的 Skill 模板。",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: self._skill_loader.list_all(),
            category="skill",
        ))

        from ..context_manager import summarize_context as _summarize_ctx
        from ..context_manager import retrieve_context as _retrieve_ctx
        from ..context_manager import verify_contract as _verify_contract

        self.register(ToolDef(
            name="summarize_context",
            description="将已生成的文件压缩为结构化摘要，释放上下文窗口。用于上下文过长时降低 token 消耗。",
            parameters={
                "type": "object",
                "properties": {
                    "max_tokens": {
                        "type": "integer",
                        "description": "摘要目标 token 数，默认 8000",
                        "default": 8000,
                    },
                },
            },
            handler=lambda **kw: _summarize_ctx(self._generated_files or {}, **kw),
            category="context",
        ))

        self.register(ToolDef(
            name="retrieve_context",
            description="从已生成文件中检索相关上下文。用于需要了解其他文件接口时按需查询。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询，如 'Header props 定义'"},
                },
                "required": ["query"],
            },
            handler=lambda **kw: _retrieve_ctx(self._generated_files or {}, **kw),
            category="context",
        ))

        self.register(ToolDef(
            name="verify_contract",
            description="校验两个文件之间的接口契约是否一致。用于验证消费者组件正确使用了提供者组件的导出。",
            parameters={
                "type": "object",
                "properties": {
                    "consumer_file": {"type": "string", "description": "消费方文件路径"},
                    "provider_file": {"type": "string", "description": "提供方文件路径"},
                    "expected_interface": {
                        "type": "object",
                        "description": "期望的接口定义，如 {props: ['title'], events: ['submit']}",
                    },
                },
                "required": ["consumer_file", "provider_file"],
            },
            handler=lambda **kw: _verify_contract(self._generated_files or {}, **kw),
            category="context",
        ))

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool
        logger.info("tool_registered", name=tool.name, category=tool.category)

    def get_schema(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def invoke(self, name: str, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        try:
            result = await tool.handler(**args)
            return result
        except Exception as e:
            logger.error("tool_invoke_error", name=name, error=str(e))
            return ToolResult(ok=False, error=str(e))

    def set_generated_files(self, files: dict[str, str]) -> None:
        """Update the generated files cache for context tools and MCP type-registry."""
        self._generated_files = files
        if hasattr(self, '_mcp_bridge'):
            self._mcp_bridge.set_type_registry(files)

    def report_frontend_compile(self, ok: bool, errors: list[dict] | None = None) -> None:
        """Store real compile feedback reported by the frontend bundler."""
        if ok:
            self._frontend_compile_errors = []
        else:
            self._frontend_compile_errors = errors or []

    def get_frontend_compile_errors(self) -> list[dict]:
        """Return the latest frontend-reported compile errors (empty if last build ok)."""
        return self._frontend_compile_errors
