"""Task group 7 memory-system tests — mid-term (7.5) + long-term user (7.6)
SQLite memory (memory_db.py). All DBs use tmp_path injection; thread-safety
smoke included.
"""

import json
import os
import threading

import pytest

from app.services.generation import memory_db
from app.services.generation.memory_db import MemoryDB, get_memory_db


@pytest.fixture
def db(tmp_path) -> MemoryDB:
    return MemoryDB(str(tmp_path / "memory.sqlite"))


# ── 7.5 mid-term: generation trajectory ──


def test_trajectory_append_and_list(db):
    db.append_trajectory("gen-1", "stage_complete", "analysis", {"summary": "ok"})
    db.append_trajectory("gen-1", "manager_verdict", "analysis", {"decision": "pass"})
    db.append_trajectory("gen-2", "stage_start", "design", {})
    rows = db.list_trajectory("gen-1")
    assert [r["event_type"] for r in rows] == ["stage_complete", "manager_verdict"]
    assert rows[0]["data"]["summary"] == "ok"
    assert rows[0]["stage"] == "analysis"
    assert rows[0]["ts"]
    # 按 generation 归档: 互不可见
    assert [r["event_type"] for r in db.list_trajectory("gen-2")] == ["stage_start"]


def test_trajectory_limit(db):
    for i in range(10):
        db.append_trajectory("gen-1", "event", "", {"i": i})
    assert len(db.list_trajectory("gen-1")) == 10
    assert len(db.list_trajectory("gen-1", limit=3)) == 3


def test_trajectory_data_truncated(db):
    db.append_trajectory("gen-1", "verifier_result", "code", {"big": "x" * 100_000})
    row = db.list_trajectory("gen-1")[0]
    assert row["data"].get("truncated") is True
    assert len(json.dumps(row["data_json"])) < 100_000


# ── 7.5 mid-term: problem records ──


def test_problem_records_crud(db):
    db.append_problem("gen-1", "verifier_failure", "编译错误", "缺少导入", "补 import", "escalated")
    db.append_problem("gen-1", "fix_round", "仍失败", "类型错误", "改类型", "still_failing")
    db.append_problem("gen-2", "verifier_failure", "别的项目", "", "", "")
    rows = db.list_problems("gen-1")
    assert len(rows) == 2
    assert rows[0]["category"] == "verifier_failure"
    assert rows[0]["root_cause"] == "缺少导入"
    assert rows[0]["fix"] == "补 import"
    assert [r["problem"] for r in db.list_problems("gen-2")] == ["别的项目"]


# ── 7.6 long-term user: preferences ──


def test_preferences_upsert_and_get(db):
    db.upsert_preference("user-a", "方案选型", "方案A")
    db.upsert_preference("user-a", "component_lib", "element-plus")
    db.upsert_preference("user-b", "方案选型", "方案B")
    assert db.get_preferences("user-a") == {"方案选型": "方案A", "component_lib": "element-plus"}
    assert db.get_preferences("user-b") == {"方案选型": "方案B"}
    # upsert 覆盖
    db.upsert_preference("user-a", "方案选型", "混合方案")
    assert db.get_preferences("user-a")["方案选型"] == "混合方案"
    # 无记录用户 → 空
    assert db.get_preferences("nobody") == {}


def test_preferences_isolated_per_user(db):
    db.upsert_preference("u1", "k", "v1")
    assert "k" not in db.get_preferences("u2")


# ── 7.6 long-term user: failure patterns / fix strategies ──


def test_failure_pattern_counts(db):
    db.record_failure_pattern("user-a", "verifier_failure", "编译错误", "补导入")
    db.record_failure_pattern("user-a", "verifier_failure", "编译错误", "补导入")
    db.record_failure_pattern("user-a", "contract_failure", "契约违约", "改导出")
    rows = db.get_failure_patterns("user-a")
    by_key = {r["pattern_key"]: r for r in rows}
    assert len(rows) == 2
    compile_key = next(k for k in by_key if k.startswith("verifier_failure:"))
    assert by_key[compile_key]["count"] == 2
    assert by_key[compile_key]["fix_strategy"] == "补导入"
    # 全局视图含全部用户
    db.record_failure_pattern("user-b", "verifier_failure", "编译错误", "补导入")
    assert len(db.get_failure_patterns()) == 3


def test_fix_strategies_success_counts(db):
    db.record_fix_strategy_success("verifier_failure", "补导入")
    db.record_fix_strategy_success("verifier_failure", "补导入")
    db.record_fix_strategy_success("contract_failure", "改导出")
    db.record_fix_strategy_result("verifier_failure", "补导入", success=True)
    rows = {r["problem_category"]: r for r in db.get_fix_strategies()}
    assert rows["verifier_failure"]["attempt_count"] == 2
    assert rows["verifier_failure"]["success_count"] == 1
    assert rows["contract_failure"]["attempt_count"] == 1


# ── registry / fail-open / thread safety ──


def test_get_memory_db_caches_by_path(tmp_path):
    p1 = str(tmp_path / "a.sqlite")
    p2 = str(tmp_path / "b.sqlite")
    assert get_memory_db(p1) is get_memory_db(p1)
    assert get_memory_db(p1) is not get_memory_db(p2)
    memory_db.close_all()


def test_memory_db_init_fail_open(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    db = MemoryDB(str(blocker / "memory.sqlite"))  # 父路径是文件 → 初始化失败
    db.append_trajectory("gen-1", "e", "s", {})    # 不抛异常 (fail-open)
    assert db.list_trajectory("gen-1") == []
    assert db.get_preferences("u") == {}
    db.close()


def test_thread_safety_smoke(tmp_path):
    db = MemoryDB(str(tmp_path / "threads.sqlite"))
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            for i in range(20):
                db.append_trajectory("gen-t", "event", "code", {"n": n, "i": i})
                db.upsert_preference("user-t", f"key-{n}", i)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(db.list_trajectory("gen-t")) == 80
    assert len(db.get_preferences("user-t")) == 4
    db.close()


def test_default_db_path_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_MEMORY_DB", str(tmp_path / "custom.sqlite"))
    assert memory_db._default_db_path() == str(tmp_path / "custom.sqlite")
    monkeypatch.delenv("AI_GEN_MEMORY_DB")
    assert memory_db._default_db_path().endswith("memory.sqlite")
