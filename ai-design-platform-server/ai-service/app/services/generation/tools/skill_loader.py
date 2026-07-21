"""Skill template loader — applies reusable code patterns."""

import json
import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")


class SkillLoader:
    def __init__(self):
        self._cache: dict[str, dict] = {}

    async def list_all(self) -> ToolResult:
        skills = []
        if os.path.isdir(SKILLS_DIR):
            for fn in os.listdir(SKILLS_DIR):
                if fn.endswith(".json"):
                    filepath = os.path.join(SKILLS_DIR, fn)
                    with open(filepath, "r", encoding="utf-8") as f:
                        skill = json.load(f)
                        skills.append({
                            "name": skill.get("name", fn),
                            "description": skill.get("description", ""),
                            "parameters": skill.get("parameters", {}),
                        })
        return ToolResult(ok=True, data={"skills": skills})

    async def apply(self, name: str, params: dict | None = None) -> ToolResult:
        filepath = os.path.join(SKILLS_DIR, f"{name}.json")
        if not os.path.exists(filepath):
            return ToolResult(ok=False, error=f"Skill not found: {name}")

        with open(filepath, "r", encoding="utf-8") as f:
            skill = json.load(f)

        files = []
        for tpl in skill.get("produces", []):
            template_content = tpl.get("template", f"// Generated from skill: {name}\n")
            if params:
                for k, v in (params or {}).items():
                    template_content = template_content.replace("{{" + k + "}}", str(v))
            files.append({
                "path": tpl.get("path", f"{name}.vue"),
                "content": template_content,
            })

        logger.info("skill_applied", name=name, files=len(files))
        return ToolResult(ok=True, data={"skill": name, "files": files})
