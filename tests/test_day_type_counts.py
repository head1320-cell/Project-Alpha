"""하루 유형 센 값의 저장소 — `src/data/day_type_counts.py` (구현 계획 2026-11-16 §7.6 · K5).

거는 약속:
- (주인, 모형, 날, 종목) 이 한 줄이다 — ★주인이 열쇠에 든다★(남의 센 값은 오지 않는다 · 모형은 주인마다다).
- 같은 (주인, 모형, 날, 종목)을 다시 적으면 그 줄이 바뀐다(다시 센 값 · 서명이 따라간다).
- 한 줄은 유형(1 이상의 정수)과 사유 가운데 꼭 하나 — 어긋난 줄은 쓰지 않고 `ValueError`(지어내지 않는다).
- 운영 게이트에서는 출처가 합성인 줄을 돌려주지 않는다 ↔ mock 은 그대로.
- 서명은 그날 일파일(크기 · 고친 시각) · 정규장 시각 · 게이트 · 판이 바뀌면 바뀐다 ↔ 그대로면 같다.
- 읽거나 쓰지 못하면 `None` — 빈 값(`{}` · 0줄)과 다르다.
- 보존 ④ 재생성 가능 · 지우는 길이 없다.
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import pytest
from sqlalchemy import text

import src.data.minute_bars as mb
import src.database as dbmod
from src.data import day_type_counts as counts
from src.data import retention
from src.engine.intraday import day_types as dt

KEY = "a" * 64
OTHER = "b" * 64
DAY = "2026-05-04"
RULES = {"available": True, "open": "0900", "close": "1530"}
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]


@pytest.fixture()
def db(monkeypatch, tmp_path):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    dbmod.reset_session()
    mb.clear_cache()
    yield tmp.name
    mb.clear_cache()
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def row(ticker: str, label: int | None = None, reason: str | None = None, source: str | None = "kis") -> dict:
    return {"ticker": ticker, "label": label, "reason": reason, "source": source if label is not None else None}


def table_rows() -> int:
    with dbmod.get_engine().connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {counts._TABLE}")).scalar())


def write_day(day: str, source: str = "kis", close: float = 10_010.0) -> None:
    recs = [("005930", "090000", 10_000.0, close, 10_000.0, close, 1_000.0, source)]
    mb._write_day_file(pd.DataFrame(recs, columns=COLS), day)


# ── 쓰기 · 읽기 ─────────────────────────────────────────────────────────────────────────
def test_counted_rows_read_back_with_their_signature(db):
    assert counts.put("alice", KEY, DAY, [row("005930", 2), row("000660", reason="short_window")], "sig-1") == 2
    got = counts.get("alice", KEY, DAY, DAY)
    assert set(got) == {(DAY, "005930"), (DAY, "000660")}
    assert got[(DAY, "005930")]["label"] == 2 and got[(DAY, "005930")]["reason"] is None
    assert got[(DAY, "005930")]["source"] == "kis" and got[(DAY, "005930")]["sig"] == "sig-1"
    assert got[(DAY, "000660")]["label"] is None and got[(DAY, "000660")]["reason"] == "short_window"
    assert got[(DAY, "000660")]["source"] is None
    assert isinstance(got[(DAY, "005930")]["counted_at"], float)


def test_nothing_counted_is_an_empty_map_not_none(db):
    assert counts.get("alice", KEY, DAY, DAY) == {}


def test_the_range_is_inclusive_and_bounded(db):
    for d in ("2026-05-01", "2026-05-04", "2026-05-05", "2026-05-06"):
        counts.put("alice", KEY, d, [row("005930", 1)], "s")
    got = counts.get("alice", KEY, "2026-05-04", "2026-05-05")
    assert sorted(d for d, _ in got) == ["2026-05-04", "2026-05-05"]


def test_counting_again_replaces_the_row(db):
    counts.put("alice", KEY, DAY, [row("005930", 2)], "old")
    counts.put("alice", KEY, DAY, [row("005930", reason="no_bars")], "new")
    got = counts.get("alice", KEY, DAY, DAY)[(DAY, "005930")]
    assert (got["label"], got["reason"], got["sig"]) == (None, "no_bars", "new")
    assert table_rows() == 1


def test_another_owner_or_another_model_does_not_see_the_rows(db):
    counts.put("alice", KEY, DAY, [row("005930", 2)], "s")
    counts.put("bob", KEY, DAY, [row("005930", 3)], "s")
    assert counts.get("alice", KEY, DAY, DAY)[(DAY, "005930")]["label"] == 2
    assert counts.get("bob", KEY, DAY, DAY)[(DAY, "005930")]["label"] == 3
    assert counts.get("alice", OTHER, DAY, DAY) == {}
    assert counts.get("carol", KEY, DAY, DAY) == {}


@pytest.mark.parametrize("bad", [row("005930", 2, reason="no_bars"), row("005930"), row("005930", 0), row("", 1),
                                 {"ticker": "005930", "label": True, "reason": None, "source": "kis"},
                                 {"ticker": "005930", "label": 1, "reason": None, "source": "made-up"},
                                 {"ticker": "005930", "label": None, "reason": "", "source": None}])
def test_an_inconsistent_row_is_refused_and_nothing_is_written(db, bad):
    with pytest.raises(ValueError):
        counts.put("alice", KEY, DAY, [row("000660", 1), bad], "s")
    assert counts.get("alice", KEY, DAY, DAY) == {}


def test_a_day_that_is_not_an_iso_date_is_refused(db):
    with pytest.raises(ValueError):
        counts.put("alice", KEY, "2026-5-4", [row("005930", 1)], "s")


# ── 운영 게이트 ─────────────────────────────────────────────────────────────────────────
def test_the_production_gate_hides_rows_counted_from_synthetic_bars(db, monkeypatch):
    counts.put("alice", KEY, DAY, [row("005930", 2, source="synthetic"), row("000660", 1, source="kis")], "s")
    assert set(counts.get("alice", KEY, DAY, DAY)) == {(DAY, "005930"), (DAY, "000660")}      # mock — 그대로
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert set(counts.get("alice", KEY, DAY, DAY)) == {(DAY, "000660")}                       # 운영 — 합성 줄은 오지 않는다


# ── 서명 ────────────────────────────────────────────────────────────────────────────────
def test_the_signature_is_stable_while_nothing_changes(db):
    write_day(DAY)
    assert counts.day_sig(DAY, RULES) == counts.day_sig(DAY, RULES)


def test_the_signature_changes_when_the_day_file_is_rewritten(db):
    write_day(DAY, close=10_010.0)
    before = counts.day_sig(DAY, RULES)
    path = mb._existing_day_path(DAY)
    st = path.stat()
    write_day(DAY, close=10_020.0)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # 같은 크기여도 고친 시각이 다르면 다르다
    assert counts.day_sig(DAY, RULES) != before


def test_the_signature_of_a_missing_file_differs_from_a_loaded_one(db):
    missing = counts.day_sig(DAY, RULES)
    write_day(DAY)
    assert counts.day_sig(DAY, RULES) != missing and "none" in missing


@pytest.mark.parametrize("other", [{"available": True, "open": "0900", "close": "1520"},
                                   {"available": True, "open": "1000", "close": "1530"},
                                   {"available": False, "open": None, "close": None}])
def test_the_signature_changes_with_the_session_rules(db, other):
    write_day(DAY)
    assert counts.day_sig(DAY, RULES) != counts.day_sig(DAY, other)


def test_the_signature_changes_with_the_gate(db, monkeypatch):
    write_day(DAY)
    mock = counts.day_sig(DAY, RULES)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert counts.day_sig(DAY, RULES) != mock


def test_the_signature_carries_the_versions(db, monkeypatch):
    write_day(DAY)
    base = counts.day_sig(DAY, RULES)
    mine, theirs = counts.VERSION, dt.VERSION
    monkeypatch.setattr(counts, "VERSION", mine + 1)                 # 이 저장소의 판(센 값의 뜻이 바뀌면 올린다)
    assert counts.day_sig(DAY, RULES) != base
    monkeypatch.setattr(counts, "VERSION", mine)
    assert counts.day_sig(DAY, RULES) == base                        # 짝 — 되돌리면 같다
    monkeypatch.setattr(dt, "VERSION", theirs + 1)                   # 하루 유형의 판(창 · 배정이 바뀌면 오른다)
    assert counts.day_sig(DAY, RULES) != base


# ── 장애 · 보존 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("call", ["put", "get"])
def test_a_broken_store_answers_none_not_empty(db, monkeypatch, call):
    def broken():
        raise RuntimeError("DB 없음")
    monkeypatch.setattr(counts, "_engine", broken)
    if call == "put":
        assert counts.put("alice", KEY, DAY, [row("005930", 1)], "s") is None
    else:
        assert counts.get("alice", KEY, DAY, DAY) is None


def test_the_table_is_regenerable_and_has_no_delete_path():
    assert counts._TABLE in retention.REGENERABLE
    assert "다시 센다" in retention.REGENERABLE[counts._TABLE]
    with open(counts.__file__, encoding="utf-8") as f:
        assert "DELETE" not in f.read().upper()


def test_the_reasons_are_sentences():
    assert counts.REASONS["store_unavailable"].endswith("다).") or counts.REASONS["store_unavailable"].endswith("다.")
    assert "세지 않았다는 뜻이 아닙니다" in counts.REASONS["store_unavailable"]
