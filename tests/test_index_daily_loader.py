"""지수 일봉 읽기 `ohlcv_loader.load_index_daily` — 구현 계획 §7.1 '읽기' (K1).

거는 것: 운영은 저장소만 읽고 증권사를 부르지 않는다(짝: 기존 `load_ohlcv_unified(auto)` 는 덮지 못한 구간에서 지수 코드로 증권사 경로를 탄다) ·
저장소 장애 = '못 읽음'(db_error) ↔ 적재 전 = '없음' · 진짜 질의 오류가 올라온다(짝: `load_ohlcv` 는 같은 오류를 빈 프레임으로 삼킨다 — 찾은 것) ·
mock 게이트는 기존 길(합성 · 출처 mock) · 지수 둘만.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

import src.data.ohlcv_loader as L
import src.kis_backtest_engine as E

START, END = "2023-01-02", "2026-03-31"


def boom(*a, **k):
    raise AssertionError("지수 읽기가 증권사 경로에 닿았다")


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.execution.kis_client as kc
    monkeypatch.setattr(kc, "get_kis_client", boom)
    monkeypatch.setattr(L, "_kis_ohlcv_df", boom)


@pytest.fixture
def store(monkeypatch, tmp_path):
    """임시 sqlite 의 daily_prices — 행을 심는 함수를 돌려준다."""
    eng = create_engine(f"sqlite:///{tmp_path / 'prices.db'}")
    with eng.begin() as c:
        c.execute(text('CREATE TABLE daily_prices (ticker TEXT, trade_date TEXT, "open" REAL, high REAL, low REAL, close REAL, volume REAL)'))
    monkeypatch.setattr(E, "_engine_override", eng)

    def put(ticker: str, dates: list[str], closes: list[float]) -> None:
        with eng.begin() as c:
            for d, x in zip(dates, closes):
                c.execute(text('INSERT INTO daily_prices VALUES (:t, :d, :x, :x, :x, :x, 0)'), {"t": ticker, "d": d, "x": x})
    return put


def bdays(start: str, end: str) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, end)]


def test_only_the_two_indexes_are_read():
    with pytest.raises(ValueError):
        L.load_index_daily("005930", START, END)


def test_production_reads_the_store_only_and_never_reaches_the_broker(production, store):
    days = bdays(START, END)
    store("KOSPI", days, [2500.0 + i for i in range(len(days))])
    store("KOSDAQ", days[:5], [800.0] * 5)
    df = L.load_index_daily("KOSPI", START, END)
    assert len(df) == len(days) and list(df.index) == sorted(df.index)
    assert df["close"].iloc[0] == 2500.0                                   # 원값 그대로
    assert df.attrs["source"] == "db" and df.attrs["coverage_ok"] is True and "db_error" not in df.attrs


def test_the_old_path_would_call_the_broker_with_an_index_code(monkeypatch, store):
    """짝 — 왜 지수 전용 읽기인가: `load_ohlcv_unified(auto)` 는 저장소가 구간을 덮지 못하면 지수 코드로 증권사 경로를 탄다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    calls: list = []
    monkeypatch.setattr(L, "_kis_ohlcv_df", lambda code, s, e: calls.append(code))
    days = bdays("2025-06-02", END)                                       # 요청 시작보다 늦게 시작하는 적재
    store("KOSPI", days, [2500.0] * len(days))
    L.load_ohlcv_unified("KOSPI", START, END, prefer="auto")
    assert calls == ["KOSPI"]


def test_a_partial_store_says_so_and_is_not_filled(production, store):
    days = bdays("2025-06-02", END)
    store("KOSPI", days, [2500.0] * len(days))
    df = L.load_index_daily("KOSPI", START, END)
    assert len(df) == len(days) and df.attrs["coverage_ok"] is False and "시작" in df.attrs["coverage_reason"]


def test_nothing_loaded_is_nothing_and_an_outage_is_cannot_read(production, store, monkeypatch):
    empty = L.load_index_daily("KOSPI", START, END)                       # 표는 있고 행이 없다 — 없음
    assert empty.empty and "db_error" not in empty.attrs and empty.attrs["coverage_reason"] == "적재분이 없습니다."

    def down(*a, **k):
        raise L.OhlcvStoreError("커넥션 풀 고갈")
    monkeypatch.setattr(L, "_db_index_rows", down)
    out = L.load_index_daily("KOSPI", START, END)
    assert out.empty and out.attrs["db_error"] == "커넥션 풀 고갈"
    assert out.attrs["coverage_reason"] == "가격 저장소를 읽지 못했습니다." and out.attrs["source"] == "db"


def test_a_real_query_error_comes_up_where_the_engines_reader_swallows_it(production, monkeypatch, tmp_path):
    """찾은 것 — `load_ohlcv` 는 질의 오류를 빈 프레임으로 삼킨다(그래서 strict 도 못 본다). 지수 읽기는 올린다."""
    eng = create_engine(f"sqlite:///{tmp_path / 'no_table.db'}")         # daily_prices 표가 없다
    monkeypatch.setattr(E, "_engine_override", eng)
    assert E.load_ohlcv("KOSPI", START, END).empty                         # 삼킨다(관측 — 고치지 않는다)
    with pytest.raises(L.OhlcvStoreError):
        L._db_index_rows("KOSPI", START, END)
    out = L.load_index_daily("KOSPI", START, END)
    assert out.empty and out.attrs.get("db_error")


def test_no_engine_is_cannot_read_not_nothing(production, monkeypatch):
    monkeypatch.setattr(E, "_get_sync_engine", lambda: None)
    out = L.load_index_daily("KOSDAQ", START, END)
    assert out.empty and out.attrs.get("db_error")


def test_the_mock_gate_takes_the_existing_path_and_never_the_broker(monkeypatch):
    import src.execution.kis_client as kc
    monkeypatch.setattr(kc, "get_kis_client", boom)
    monkeypatch.setattr(L, "_db_ohlcv_df", lambda *a, **k: pd.DataFrame())   # 저장소에 없다 → 합성
    df = L.load_index_daily("KOSPI", "2026-01-02", "2026-03-31")
    assert not df.empty and df.attrs["source"] == "mock" and df.attrs["coverage_ok"] is False
