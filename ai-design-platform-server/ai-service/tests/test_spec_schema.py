"""Tests for the architecture Spec schema (task 4.1) and the app-memory write (4.5).

Covers validate_spec (full / partial / invalid / wrong-type cases), the
empty_spec fallback shape, and write_spec_to_memory.
"""

import json

from app.services.generation.spec_schema import (
    ARCHITECTURE_SPEC_SCHEMA,
    REQUIRED_SPEC_FIELDS,
    empty_spec,
    validate_spec,
    write_spec_to_memory,
)

VALID_SPEC = {
    "spec_version": 1,
    "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "webpack", "style": "scss"},
    "directory_tree": {"src/": ["main.ts", "App.vue", "router/", "components/"]},
    "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
    "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
    "routing": [{"path": "/", "page": "Home", "auth": False}],
    "state_management": {"store": "pinia", "stores": ["user"]},
    "component_tree": [{"name": "Header", "uses": ["NavMenu"], "props": []}],
    "pages": [{"id": "p-01", "name": "登录页", "interactions": [], "data": []}],
    "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
}


# ── 4.1 validate_spec ──


def test_validate_spec_full_valid():
    assert validate_spec(VALID_SPEC) == []
    assert validate_spec(dict(ARCHITECTURE_SPEC_SCHEMA)) == []


def test_validate_spec_missing_field():
    spec = dict(VALID_SPEC)
    spec.pop("directory_tree")
    problems = validate_spec(spec)
    assert any("directory_tree" in p for p in problems)
    assert len(problems) == 1


def test_validate_spec_empty_value():
    # Empty container counts as missing per the L1 rule ("任一必需字段缺失或为空").
    spec = dict(VALID_SPEC)
    spec["pages"] = []
    problems = validate_spec(spec)
    assert any("pages" in p and "为空" in p for p in problems)


def test_validate_spec_missing_spec_version():
    spec = dict(VALID_SPEC)
    spec.pop("spec_version")
    problems = validate_spec(spec)
    assert any("spec_version" in p for p in problems)


def test_validate_spec_wrong_type():
    spec = dict(VALID_SPEC)
    spec["directory_tree"] = ["src/"]  # must be an object
    problems = validate_spec(spec)
    assert any("directory_tree" in p and "类型不合法" in p for p in problems)

    spec2 = dict(VALID_SPEC)
    spec2["data_model"] = "users"  # must be an array
    problems2 = validate_spec(spec2)
    assert any("data_model" in p and "类型不合法" in p for p in problems2)

    spec3 = dict(VALID_SPEC)
    spec3["spec_version"] = "1"  # must be a number
    problems3 = validate_spec(spec3)
    assert any("spec_version" in p and "类型不合法" in p for p in problems3)


def test_validate_spec_not_a_dict():
    for bad in (None, "", [], "not a spec", 42):
        assert validate_spec(bad) == ["架构 Spec 为空"]


def test_validate_spec_reports_all_missing_fields():
    # A dict-shaped spec with every field empty reports one problem per field.
    problems = validate_spec({"spec_version": None})
    assert len(problems) == len(REQUIRED_SPEC_FIELDS)
    # A totally empty dict short-circuits to a single "Spec 为空" problem.
    assert validate_spec({}) == ["架构 Spec 为空"]


def test_empty_spec_shape():
    spec = empty_spec()
    assert set(spec.keys()) == set(REQUIRED_SPEC_FIELDS)
    assert spec["spec_version"] == 1
    assert isinstance(spec["tech_stack"], dict)
    assert isinstance(spec["directory_tree"], dict)
    for field in ("data_model", "api_contracts", "routing", "component_tree", "pages", "decisions"):
        assert isinstance(spec[field], list)


def test_empty_spec_keys_match_reference_schema():
    """Review minor 4: empty_spec() and ARCHITECTURE_SPEC_SCHEMA hand-mirror
    each other (schema / prompt example / empty defaults / field list) — the
    key sets must stay in sync."""
    assert set(empty_spec().keys()) == set(ARCHITECTURE_SPEC_SCHEMA.keys())
    assert set(empty_spec().keys()) == set(REQUIRED_SPEC_FIELDS)


# ── 4.5 write_spec_to_memory ──


def test_write_spec_to_memory_writes_file(tmp_path):
    path = write_spec_to_memory(VALID_SPEC, str(tmp_path))
    assert path == str(tmp_path / ".ai-memory" / "spec" / "architecture.json")
    with open(path, encoding="utf-8") as f:
        written = json.load(f)
    assert written == VALID_SPEC


def test_write_spec_to_memory_keeps_unicode(tmp_path):
    spec = dict(VALID_SPEC)
    spec["pages"] = [{"id": "p-01", "name": "登录页", "interactions": [], "data": []}]
    write_spec_to_memory(spec, str(tmp_path))
    raw = (tmp_path / ".ai-memory" / "spec" / "architecture.json").read_text(encoding="utf-8")
    assert "登录页" in raw  # ensure_ascii=False


def test_write_spec_to_memory_fail_open(tmp_path):
    # project_root pointing at a file → makedirs fails → None, no raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    assert write_spec_to_memory(VALID_SPEC, str(blocker)) is None
