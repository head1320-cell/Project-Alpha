"""cached() 빈값 영속 방지 — DART 쿼터 소진 시 빈 팩터가 DB에 고정(오염)되던 문제의 회귀 방지."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.mock_base as mb  # noqa: E402
from src.data.mock_base import DeterministicMockStore  # noqa: E402


class _Store(DeterministicMockStore):
    PERSIST = True


def _persist_on(monkeypatch, store, writes: list):
    """persist 경로 강제 활성 + snapshot_db write/bulk_read를 가짜로 대체."""
    monkeypatch.setattr(store, "_persist_on", lambda: True)
    import src.data.snapshot_db as sdb
    monkeypatch.setattr(sdb, "write", lambda k, v: writes.append((k, v)))
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl: {})
    return store


def test_empty_result_not_persisted(monkeypatch):
    writes: list = []
    st = _persist_on(monkeypatch, _Store(), writes)
    assert st.cached("ffl:900001", lambda: {}) == {}
    assert writes == []                          # 빈 팩터는 영속 금지 (쿼터 회복 후 재시도 가능)


def test_empty_result_retries_after_short_ttl(monkeypatch):
    writes: list = []
    st = _persist_on(monkeypatch, _Store(), writes)
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return {} if calls["n"] == 1 else {"roe": 5.0}

    assert st.cached("ffl:900002", builder) == {}
    # 빈값의 in-memory TTL을 지난 것으로 시뮬레이션
    with st._lock:
        ts, v = st._cache["ffl:900002"]
        st._cache["ffl:900002"] = (ts - (mb.EMPTY_RETRY_TTL + 1), v)
    assert st.cached("ffl:900002", builder) == {"roe": 5.0}   # 재시도로 실값 획득
    assert writes and writes[-1][1] == {"roe": 5.0}           # 실값만 영속


def test_persisted_empty_hit_treated_as_miss(monkeypatch):
    writes: list = []
    st = _persist_on(monkeypatch, _Store(), writes)
    import src.data.snapshot_db as sdb
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl: {k: {} for k in keys})  # 오염된 빈 히트
    assert st.cached("ffl:900003", lambda: {"pbr": 1.2}) == {"pbr": 1.2}  # miss 취급 → 재계산


def test_normal_value_persisted_once(monkeypatch):
    writes: list = []
    st = _persist_on(monkeypatch, _Store(), writes)
    assert st.cached("ffl:900004", lambda: {"per": 9.9}) == {"per": 9.9}
    assert len(writes) == 1 and writes[0][0] == "ffl:900004"
