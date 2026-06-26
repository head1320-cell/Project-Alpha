"""KRX MDC 수급 백필 어댑터 테스트 — 파싱·주체 합산 정합·UPSERT 소스 분리.

비공식 엔드포인트라 실호출 없이 응답 구조 fixture(pykrx 1.2.8 스펙 전사)로 검증.
핵심 불변식: KRX 백필(full)이 채운 세부 주체를 KIS 일별 적재(3주체)가 덮지 않는다.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.data import kis_flows as kf
from src.data import krx_mdc as km


# ─── 응답 파싱 ────────────────────────────────────────────────────────────────
def mdc_row(date: str, vals: list) -> dict:
    row = {"TRD_DD": date}
    for i, v in enumerate(vals, start=1):
        row[f"TRDVAL{i}"] = v
    row["TRDVAL_TOT"] = "0"
    return row


# 금융투자,보험,투신,사모,은행,기타금융,연기금,기타법인,개인,외국인,기타외국인
QTY_0105 = ["100", "10", "20", "5", "3", "2", "60", "-30", "-500", "300", "30"]
AMT_0105 = ["1,000", "100", "200", "50", "30", "20", "600", "-300", "-5,000", "3,000", "300"]


def test_parse_investor_detail():
    rows = km.parse_investor_detail({"output": [
        mdc_row("2024/01/05", QTY_0105),
        mdc_row("2024/01/04", ["1"] * 11),
        {"TRD_DD": "bad"},
    ]})
    assert [r["date"] for r in rows] == ["2024-01-04", "2024-01-05"]  # 과거→현재 정렬
    assert rows[1]["연기금"] == 60.0 and rows[1]["기타외국인"] == 30.0
    assert rows[1]["개인"] == -500.0


def test_rows_to_flow_records_aggregation():
    """기관계 = 7주체 합, 외국인 = 외국인+기타외국인 — KIS 3주체와 의미 정합."""
    qty = km.parse_investor_detail({"output": [mdc_row("2024/01/05", QTY_0105)]})
    amt = km.parse_investor_detail({"output": [mdc_row("2024/01/05", AMT_0105)]})
    [rec] = km.rows_to_flow_records(qty, amt)
    assert rec["orgn_qty"] == pytest.approx(100 + 10 + 20 + 5 + 3 + 2 + 60)  # 200
    assert rec["frgn_qty"] == pytest.approx(300 + 30)
    assert rec["prsn_qty"] == -500.0
    assert rec["pension_qty"] == 60.0 and rec["pension_amt"] == 600.0
    assert rec["trust_qty"] == 20.0 and rec["pe_qty"] == 5.0
    assert rec["othercorp_amt"] == -300.0


# ─── 백필 + UPSERT 소스 분리 ─────────────────────────────────────────────────
@pytest.fixture
def mem_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    yield eng
    eng.dispose()
    kf._series_cache.clear()


def fake_fetcher(isin, start, end, value_type):
    vals = QTY_0105 if value_type == "qty" else AMT_0105
    return km.parse_investor_detail({"output": [mdc_row("2024/01/05", vals)]})


def test_backfill_flows_krx(mem_engine, monkeypatch):
    monkeypatch.setattr("src.data.stock_master.load_master_flags",
                        lambda: {"005930": {"isin": "KR7005930003", "group_code": "ST"},
                                 "999999": {"isin": "", "group_code": "ST"}})
    stats = km.backfill_flows_krx("2024-01-01", "2024-01-31",
                                  tickers=["005930", "999999"],
                                  engine=mem_engine, fetcher=fake_fetcher)
    assert not stats.get("error")
    assert stats["loaded"] == 1 and stats["no_isin"] == 1
    with mem_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT orgn_qty, pension_qty, pension_amt FROM investor_flows "
            "WHERE ticker='005930'")).fetchone()
    assert row[0] == 200.0 and row[1] == 60.0 and row[2] == 600.0


def test_kis_daily_upsert_preserves_krx_detail(mem_engine, monkeypatch):
    """핵심 불변식: KIS 3주체 일별 적재가 KRX 세부 주체 컬럼을 NULL로 덮지 않는다."""
    monkeypatch.setattr("src.data.stock_master.load_master_flags",
                        lambda: {"005930": {"isin": "KR7005930003", "group_code": "ST"}})
    km.backfill_flows_krx("2024-01-01", "2024-01-31", tickers=["005930"],
                          engine=mem_engine, fetcher=fake_fetcher)

    # 같은 날짜에 KIS 일별 적재(3주체) 덮어쓰기
    kf.bulk_upsert_flows(mem_engine, "005930", [{
        "date": "2024-01-05", "prsn_qty": -555.0, "frgn_qty": 333.0, "orgn_qty": 222.0,
        "prsn_amt": None, "frgn_amt": None, "orgn_amt": None,
    }], full=False)

    with mem_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT frgn_qty, pension_qty, trust_amt FROM investor_flows "
            "WHERE ticker='005930' AND trade_date='2024-01-05'")).fetchone()
    assert row[0] == 333.0          # 3주체는 KIS 값으로 갱신
    assert row[1] == 60.0           # 세부 주체는 보존 ✓
    assert row[2] == 200.0


def test_backfill_requires_master(mem_engine, monkeypatch):
    monkeypatch.setattr("src.data.stock_master.load_master_flags", lambda: {})
    stats = km.backfill_flows_krx("2024-01-01", engine=mem_engine, fetcher=fake_fetcher)
    assert stats.get("error") and "collect-master" in stats["message"]


# ─── 적재 현황(flows_status) — API/UI 점검용 ──────────────────────────────────
def test_flows_status_empty(mem_engine):
    kf.ensure_flows_table(mem_engine)
    st = kf.flows_status(mem_engine)
    assert st["rows"] == 0 and st["tickers"] == 0 and st["has_detail"] is False
    assert st["min_date"] is None and st["max_date"] is None


def test_flows_status_after_backfill(mem_engine, monkeypatch):
    monkeypatch.setattr("src.data.stock_master.load_master_flags",
                        lambda: {"005930": {"isin": "KR7005930003", "group_code": "ST"}})
    km.backfill_flows_krx("2024-01-01", "2024-01-31", tickers=["005930"],
                          engine=mem_engine, fetcher=fake_fetcher)
    st = kf.flows_status(mem_engine)
    assert st["rows"] == 1
    assert st["tickers"] == 1
    assert st["max_date"] == "2024-01-05"
    assert st["has_detail"] is True       # KRX 백필 → 세부 주체(연기금 등) 채워짐


def test_date_chunks():
    chunks = list(km._date_chunks("2015-01-01", "2018-12-31"))
    assert len(chunks) >= 2 and chunks[0][0] == "2015-01-01" and chunks[-1][1] == "2018-12-31"
    # 경계 연속성 (빈틈·중복 없음)
    for (a, b), (c, d) in zip(chunks, chunks[1:]):
        import datetime as dt
        assert (dt.date.fromisoformat(c) - dt.date.fromisoformat(b)).days == 1


# ─── 세부 주체 토큰 지원 전환 ─────────────────────────────────────────────────
def test_detail_flow_tokens_supported(monkeypatch):
    import pandas as pd

    from src.kis_strategies import factor_tokens as ft
    ts = ft.token_support()
    assert ts["supported"].get("연기금순매수량") == "flow"
    assert ts["supported"].get("사모펀드순매수금액") == "flow"
    assert "연기금순매수량" not in ts["unsupported"]

    flow = pd.Series([60.0], index=pd.DatetimeIndex(["2024-01-05"]))
    monkeypatch.setattr("src.data.kis_flows.load_flows_series",
                        lambda t, f, engine=None: flow if f == "pension_qty" else None)
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                       "volume": [1.0]}, index=pd.DatetimeIndex(["2024-01-05"]))
    df.attrs["ticker"] = "005930"
    s = ft.resolve_flow_token(df, "연기금순매수량")
    assert float(s.iloc[0]) == 60.0
