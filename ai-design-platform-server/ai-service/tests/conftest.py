"""Test-wide memory isolation (task group 7).

The memory system writes persistently (7.1): ``AI_GEN_DATA_DIR``
(``data/generated/<app_id>/``) and ``AI_GEN_MEMORY_DB`` (SQLite). Every test
gets its own tmp dirs so nothing lands in the repo working tree; open SQLite
connections are closed after each test so tmp cleanup never hits locked files
(Windows).
"""

import pytest


@pytest.fixture(autouse=True)
def _memory_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AI_GEN_MEMORY_DB", str(tmp_path / "memory.sqlite"))
    yield
    # Close cached MemoryDB connections (their sqlite files live in tmp dirs).
    try:
        from app.services.generation.memory_db import close_all

        close_all()
    except Exception:
        pass
