"""KIS 투자자별 수급 적재 + 수급 토큰 해석 단위 테스트.

normalize(KIS 응답 정규화) → 적재(UPSERT/멱등) → load_flows_series →
resolve_flow_token(df.attrs 종목 식별, NaN 비-ffill) 전 경로를 fixture로 검증.
엔진이 의존하는 'pandas attrs가 슬라이스에 보존' 동작도 회귀 가드.
"""
import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.data import kis_flows as kf
from src.execution.kis_client import normalize_investor_rows
from src.kis_strategies import factor_tokens as ft


# ─── KIS 응답 정규화 ──────────────────────────────────────────────────────────
def kis_row(date: str, frgn="1,234", orgn="-567", prsn="100",
            frgn_amt="88,800", orgn_amt="-40,000", prsn_amt="7,200") -> dict:
    return {
        "stck_bsop_date": date, "stck_clpr": "70,000",
        "prsn_ntby_qty": prsn, "frgn_ntby_qty": frgn, "orgn_ntby_qty": orgn,
        "prsn_ntby_tr_pbmn": prsn_amt, "frgn_ntby_tr_pbmn": frgn_amt,
        "orgn_ntby_tr_pbmn": orgn_amt,
    }


def test_normalize_investor_rows():
    rows = normalize_investor_rows([
        kis_row("20240105"),                 # KIS는 최신→과거 순
        kis_row("20240104", frgn="-2,000"),
        {"stck_bsop_date": "bad"},           # 이상 행 skip
    ])
    assert [r["date"] for r in rows] == ["2024-01-04", "2024-01-05"]  # 과거→현재 반전
    assert rows[1]["frgn_qty"] == 1234.0 and rows[1]["orgn_qty"] == -567.0
    assert rows[0]["frgn_qty"] == -2000.0
    assert rows[1]["frgn_amt"] == 88800.0


# ─── 적재 (sqlite in-memory) ──────────────────────────────────────────────────
@pytest.fixture
def mem_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    yield eng
    eng.dispose()
    kf._series_cache.clear()


class FakeFlowsKIS:
    """2종목 × 2일 수급을 주는 가짜 클라이언트 (실키 경로 시뮬)."""
    def __init__(self):
        self.calls = []

    def get_investor_daily(self, ticker):
        self.calls.append(ticker)
        if ticker == "000000":
            return []
        return normalize_investor_rows([kis_row("20240105"), kis_row("20240104", frgn="-2,000")])

    def throttle(self):
        pass


def test_sync_upsert_and_idempotent(mem_engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    client = FakeFlowsKIS()
    stats = kf.sync_investor_flows(tickers=["005930", "000660", "000000"],
                                   engine=mem_engine, client=client)
    assert not stats.get("error")
    assert stats["loaded"] == 2 and stats["rows"] == 4   # 빈 응답 종목 제외

    # 재실행(UPSERT 멱등) — 행 수 불변
    kf.sync_investor_flows(tickers=["005930"], engine=mem_engine, client=client)
    with mem_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM investor_flows")).scalar()
    assert n == 4


def test_sync_guard_in_mock_mode(mem_engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    stats = kf.sync_investor_flows(tickers=["005930"], engine=mem_engine, client=FakeFlowsKIS())
    assert stats.get("error") and "mock" in stats["message"].lower()


def test_load_flows_series(mem_engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    kf.sync_investor_flows(tickers=["005930"], engine=mem_engine, client=FakeFlowsKIS())
    kf._series_cache.clear()
    s = kf.load_flows_series("005930", "frgn_qty", engine=mem_engine)
    assert s is not None and len(s) == 2
    assert float(s.loc["2024-01-05"]) == 1234.0
    assert kf.load_flows_series("없는종목", "frgn_qty", engine=mem_engine) is None
    kf._series_cache.clear()
    assert kf.load_flows_series("005930", "잘못된필드", engine=mem_engine) is None


# ─── 수급 토큰 해석 (df.attrs 종목 식별) ─────────────────────────────────────
def stock_df(days: list[str]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(days)
    c = pd.Series([100.0] * len(days), index=idx)
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": c})
    df.attrs["ticker"] = "005930"
    return df


def test_resolve_flow_token_aligns_without_ffill(monkeypatch):
    flow = pd.Series([1234.0, -2000.0],
                     index=pd.DatetimeIndex(["2024-01-04", "2024-01-05"]))
    monkeypatch.setattr("src.data.kis_flows.load_flows_series",
                        lambda t, f, engine=None: flow if t == "005930" else None)
    df = stock_df(["2024-01-04", "2024-01-05", "2024-01-08"])  # 1/8은 미적재일
    s = ft.resolve_flow_token(df, "외국인순매수량")
    assert float(s.loc["2024-01-05"]) == -2000.0
    assert pd.isna(s.loc["2024-01-08"])                 # ffill 안 함 → 그 봉은 건너뜀

    df_no_attr = stock_df(["2024-01-04"])
    df_no_attr.attrs.clear()
    assert ft.resolve_flow_token(df_no_attr, "외국인순매수량") is None  # 종목 식별 불가
    assert ft.resolve_flow_token(df, "연기금순매수량") is None          # 미지원 주체


def test_pandas_attrs_survive_loc_slice():
    """엔진 의존 동작 가드 — ohlcv_map df의 attrs가 .loc 슬라이스에도 남아야 함."""
    df = stock_df(["2024-01-04", "2024-01-05", "2024-01-08"])
    sliced = df.loc[:pd.Timestamp("2024-01-05")]
    assert sliced.attrs.get("ticker") == "005930"


# ─── 지원 맵 반영 ─────────────────────────────────────────────────────────────
def test_token_support_flow_and_fred():
    ts = ft.token_support()
    assert ts["supported"].get("외국인순매수량") == "flow"
    assert ts["supported"].get("US국채(10년)") == "macro"     # FRED로 활성
    assert "US국채(10년)" not in ts["unsupported"]
    assert "연기금순매수량" in ts["unsupported"]               # KIS 3주체 한계 명시
    assert "공매도비중" in ts["unsupported"]
    assert "flow_note" in ts
