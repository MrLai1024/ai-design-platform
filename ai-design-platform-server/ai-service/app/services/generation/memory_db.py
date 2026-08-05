"""中期 + 长期记忆 — SQLite (task group 7, D8 ②③).

- ② 中期: ``generation_trajectory`` (事件流摘要, 按 generation 归档) +
  ``problem_records`` (按 generation 的问题/根因/修复归档)。
- ③ 长期用户级: ``user_preferences`` (偏好, 挂 user 维度) +
  ``failure_patterns`` (失败模式, 次数累积) + ``fix_strategies``
  (修复策略, 成功计数)。

实现:
- stdlib ``sqlite3``, 单连接 + ``threading.Lock`` (asyncio 单线程协作式,
  无并发写风险; check_same_thread=False 允许跨线程复用)。
- 路径 env ``AI_GEN_MEMORY_DB`` 可配 (默认 ``<data_dir>/memory.sqlite``)。
- 全部操作 fail-open: 失败记日志绝不抛出, 生成期轨迹写为 best-effort
  fire-and-forget (轻量同步写, 不 await 重型 IO)。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

import structlog

logger = structlog.get_logger()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_trajectory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_trajectory_gen ON generation_trajectory(generation_id);

CREATE TABLE IF NOT EXISTS problem_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    category TEXT NOT NULL,
    problem TEXT NOT NULL,
    root_cause TEXT NOT NULL DEFAULT '',
    fix TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_problems_gen ON problem_records(generation_id);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS failure_patterns (
    pattern_key TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'default',
    description TEXT NOT NULL DEFAULT '',
    fix_strategy TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (pattern_key, user_id)
);

CREATE TABLE IF NOT EXISTS fix_strategies (
    problem_category TEXT NOT NULL,
    strategy TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (problem_category, strategy)
);
"""

# 轨迹 data_json 单行上限 (字符) — 大 payload 截断存储, 保持归档轻量。
TRAJECTORY_DATA_LIMIT = 50_000


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _slug(text: str, limit: int = 48) -> str:
    import re

    s = re.sub(r"\s+", " ", (text or "")).strip()[:limit]
    return s or "unknown"


class MemoryDB:
    """SQLite 记忆库 — 单连接 + 锁, 全部操作 fail-open.

    ``db_path`` 注入点 (测试用 tmp_path; 生产默认 env AI_GEN_MEMORY_DB
    或 <data_dir>/memory.sqlite)。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._init_schema()
        except (OSError, sqlite3.Error) as e:
            logger.warning("memory_db_init_failed", db_path=db_path, error=str(e))

    def _init_schema(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()

    # ── 底层执行 (fail-open) ──

    def _execute(self, sql: str, params: tuple = ()) -> None:
        if self._conn is None:
            return
        try:
            with self._lock:
                self._conn.execute(sql, params)
                self._conn.commit()
        except sqlite3.Error as e:
            logger.warning("memory_db_write_failed", db_path=self.db_path, error=str(e))

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self._conn is None:
            return []
        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                cols = [d[0] for d in cur.description or []]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except sqlite3.Error as e:
            logger.warning("memory_db_query_failed", db_path=self.db_path, error=str(e))
            return []

    # ── ② 中期: 运行轨迹 ──

    def append_trajectory(
        self,
        generation_id: str,
        event_type: str,
        stage: str = "",
        data: dict | None = None,
    ) -> None:
        """追加一条轨迹事件 (fire-and-forget, fail-open)."""
        payload = data or {}
        try:
            encoded = json.dumps(payload, ensure_ascii=False, default=str)
            if len(encoded) > TRAJECTORY_DATA_LIMIT:
                encoded = json.dumps(
                    {"truncated": True, "summary": str(payload)[:2000]},
                    ensure_ascii=False,
                )
        except (TypeError, ValueError):
            encoded = json.dumps({"truncated": True, "summary": str(payload)[:2000]})
        self._execute(
            "INSERT INTO generation_trajectory (generation_id, ts, event_type, stage, data_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (generation_id, _ts(), event_type, stage or "", encoded),
        )

    def list_trajectory(self, generation_id: str, limit: int | None = None) -> list[dict]:
        sql = "SELECT ts, event_type, stage, data_json FROM generation_trajectory" \
              " WHERE generation_id = ? ORDER BY id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self._query(sql, (generation_id,))
        for r in rows:
            try:
                r["data"] = json.loads(r.get("data_json") or "{}")
            except json.JSONDecodeError:
                r["data"] = {}
        return rows

    # ── ② 中期: 问题记录 ──

    def append_problem(
        self,
        generation_id: str,
        category: str,
        problem: str,
        root_cause: str = "",
        fix: str = "",
        result: str = "",
    ) -> None:
        self._execute(
            "INSERT INTO problem_records (generation_id, ts, category, problem, root_cause, fix, result)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (generation_id, _ts(), category, problem, root_cause, fix, result),
        )

    def list_problems(self, generation_id: str) -> list[dict]:
        return self._query(
            "SELECT ts, category, problem, root_cause, fix, result FROM problem_records"
            " WHERE generation_id = ? ORDER BY id",
            (generation_id,),
        )

    # ── ③ 长期用户级: 用户偏好 ──

    def upsert_preference(self, user_id: str, key: str, value: Any) -> None:
        """偏好 upsert (key 维度). value 可 JSON 序列化."""
        self._execute(
            "INSERT INTO user_preferences (user_id, key, value_json, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(user_id, key) DO UPDATE SET"
            " value_json = excluded.value_json, updated_at = excluded.updated_at",
            (user_id, key, json.dumps(value, ensure_ascii=False, default=str), _ts()),
        )

    def get_preferences(self, user_id: str) -> dict:
        rows = self._query(
            "SELECT key, value_json FROM user_preferences WHERE user_id = ?",
            (user_id,),
        )
        out: dict = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value_json"])
            except (json.JSONDecodeError, TypeError):
                out[r["key"]] = r["value_json"]
        return out

    # ── ③ 长期用户级: 失败模式 / 修复策略 ──

    def record_failure_pattern(
        self,
        user_id: str,
        pattern_key: str,
        description: str = "",
        fix_strategy: str = "",
    ) -> None:
        """失败模式 upsert — 同 key 计数 +1, 更新 last_seen."""
        key = f"{pattern_key}:{_slug(description)}"
        self._execute(
            "INSERT INTO failure_patterns (pattern_key, user_id, description, fix_strategy, count, last_seen)"
            " VALUES (?, ?, ?, ?, 1, ?)"
            " ON CONFLICT(pattern_key, user_id) DO UPDATE SET"
            " description = excluded.description, fix_strategy = excluded.fix_strategy,"
            " count = failure_patterns.count + 1, last_seen = excluded.last_seen",
            (key, user_id, description, fix_strategy, _ts()),
        )

    def get_failure_patterns(self, user_id: str | None = None) -> list[dict]:
        if user_id:
            return self._query(
                "SELECT pattern_key, user_id, description, fix_strategy, count, last_seen"
                " FROM failure_patterns WHERE user_id = ? ORDER BY count DESC",
                (user_id,),
            )
        return self._query(
            "SELECT pattern_key, user_id, description, fix_strategy, count, last_seen"
            " FROM failure_patterns ORDER BY count DESC"
        )

    def record_fix_strategy_success(self, problem_category: str, strategy: str) -> None:
        """修复策略记录 — 尝试 +1; 成功计数由 result='passed' 路径上调."""
        self._execute(
            "INSERT INTO fix_strategies (problem_category, strategy, attempt_count, success_count)"
            " VALUES (?, ?, 1, 0)"
            " ON CONFLICT(problem_category, strategy) DO UPDATE SET"
            " attempt_count = fix_strategies.attempt_count + 1",
            (problem_category or "unknown", strategy or "unknown"),
        )

    def record_fix_strategy_result(self, problem_category: str, strategy: str, success: bool) -> None:
        """按结果更新 success_count (成功修复调用, 失败不计数)."""
        if success:
            self._execute(
                "UPDATE fix_strategies SET success_count = success_count + 1"
                " WHERE problem_category = ? AND strategy = ?",
                (problem_category or "unknown", strategy or "unknown"),
            )

    def get_fix_strategies(self) -> list[dict]:
        return self._query(
            "SELECT problem_category, strategy, attempt_count, success_count"
            " FROM fix_strategies ORDER BY success_count DESC"
        )

    # ── 生命周期 ──

    def close(self) -> None:
        if self._conn is not None:
            try:
                with self._lock:
                    self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def __enter__(self) -> "MemoryDB":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ── 默认实例 (进程级缓存, 路径可注入) ──

_instances: dict[str, MemoryDB] = {}
_instances_lock = threading.Lock()


def _default_db_path() -> str:
    return os.environ.get("AI_GEN_MEMORY_DB") or os.path.join(
        _data_dir(), "memory.sqlite"
    )


def _data_dir() -> str:
    from .memory import data_dir  # lazy: 避免模块级 import 环

    return data_dir()


def get_memory_db(db_path: str | None = None) -> MemoryDB:
    """获取记忆库实例 (按路径缓存; 生产用默认路径)."""
    path = db_path or _default_db_path()
    with _instances_lock:
        inst = _instances.get(path)
        if inst is None:
            inst = MemoryDB(path)
            _instances[path] = inst
        return inst


def close_all() -> None:
    """关闭并清空全部缓存实例 (测试清理 / 优雅停机)."""
    with _instances_lock:
        for inst in _instances.values():
            inst.close()
        _instances.clear()
