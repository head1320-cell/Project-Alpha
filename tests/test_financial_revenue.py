"""금융업(은행·보험·증권·지주) 펀더멘털 편입 — 매출 정의(영업수익/이자수익) 확장.

증상: 금융업은 DART 손익계산서에 "매출액" 라인이 없어 revenue=NULL로 적재됨 →
완전연도 게이트에서 탈락해 스크리너 유니버스/백테스트에서 빠짐(진단의 financial_no_revenue).
수정: 파서가 매출액 부재 시 영업수익/수입보험료/이자수익을 revenue로 매핑 +
revenue=NULL 행을 확장 파서로 재조회(refetch_revenue_null).
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.data import dart_history as dh
from src.data.dart_client import DARTClient, FinancialStatement

_BS = [("자산총계", "BS", "300,000,000,000,000"),
       ("부채총계", "BS", "270,000,000,000,000"),
       ("자본총계", "BS", "30,000,000,000,000")]


def _client(is_rows):
    c = DARTClient()
    c.api_key = "test"
    payload = {"list": [{"account_nm": a, "sj_div": sj, "thstrm_amount": amt}
                        for (a, sj, amt) in list(is_rows) + _BS]}
    c._get = lambda ep, params: payload
    c.get_dividend_info = lambda *a, **k: {}
    return c


def test_financial_revenue_maps_operating_revenue():
    """매출액 없고 영업수익만 → revenue = 영업수익."""
    c = _client([("영업수익", "IS", "5,000,000,000,000"),
                 ("영업이익", "IS", "1,000,000,000,000"),
                 ("당기순이익", "IS", "800,000,000,000")])
    fs = c.get_financial_statement_full("x", "2024")
    assert fs.revenue == 5_000_000_000_000
    assert fs.operating_profit == 1_000_000_000_000
    assert fs.net_income == 800_000_000_000
    assert fs.total_equity == 30_000_000_000_000


def test_financial_revenue_prefers_operating_over_interest():
    """영업수익·이자수익 둘 다 있으면 영업수익(더 포괄적) 우선."""
    c = _client([("이자수익", "IS", "3,000,000,000,000"),
                 ("영업수익", "IS", "5,000,000,000,000"),
                 ("당기순이익", "IS", "800,000,000,000")])
    fs = c.get_financial_statement_full("x", "2024")
    assert fs.revenue == 5_000_000_000_000


def test_bank_interest_income_fallback():
    """영업수익 없이 이자수익만(은행) → revenue = 이자수익."""
    c = _client([("이자수익", "IS", "3,000,000,000,000"),
                 ("당기순이익", "IS", "800,000,000,000")])
    fs = c.get_financial_statement_full("x", "2024")
    assert fs.revenue == 3_000_000_000_000


def test_normal_revenue_not_overridden():
    """매출액이 있으면 금융업 폴백을 쓰지 않음(제조업 회귀 안전)."""
    c = _client([("매출액", "IS", "9,000,000,000,000"),
                 ("영업수익", "IS", "1,000,000,000,000"),
                 ("당기순이익", "IS", "800,000,000,000")])
    fs = c.get_financial_statement_full("x", "2024")
    assert fs.revenue == 9_000_000_000_000


@pytest.fixture
def mem_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    yield eng
    eng.dispose()


def _make_fs(year, revenue=5000.0):
    fs = FinancialStatement(corp_code="x", corp_name="은행", bsns_year=year, reprt_code="11011")
    fs.revenue, fs.net_income = revenue, 800.0
    fs.total_assets, fs.total_equity, fs.total_liabilities = 3000.0, 300.0, 2700.0
    return fs


def test_refetch_revenue_null_updates(monkeypatch, mem_engine):
    """revenue=NULL(금융업) 행을 확장 파서로 재조회 → revenue 채워 갱신."""
    dh.ensure_history_table(mem_engine)
    with mem_engine.begin() as c:
        c.execute(text(
            "INSERT INTO financials_history (ticker, bsns_year, reprt_code, revenue, net_income, "
            "total_assets, total_equity) VALUES ('055550','2024','11011', NULL, 800.0, 3000.0, 300.0)"))

    class _Dart:
        is_configured = True

        def get_financial_statement_full(self, corp, year, reprt_code="11011"):
            return _make_fs(year, revenue=5000.0)   # 확장 파서가 영업수익을 revenue로 채움
    monkeypatch.setattr("src.data.dart_client.get_corp_code", lambda tk: "00000000")

    stats = dh.refetch_revenue_null(engine=mem_engine, client=_Dart())
    assert stats["candidates"] == 1 and stats["updated"] == 1
    snap = dh.history_snapshot("055550", "2024", "11011", engine=mem_engine)
    assert snap["revenue"] == 5000.0   # NULL → 5000 갱신됨


def test_refetch_skips_rows_with_revenue(monkeypatch, mem_engine):
    """revenue가 이미 있으면 후보 아님(멱등·쿼터 절약)."""
    dh.ensure_history_table(mem_engine)
    with mem_engine.begin() as c:
        c.execute(text(
            "INSERT INTO financials_history (ticker, bsns_year, reprt_code, revenue, net_income) "
            "VALUES ('005930','2024','11011', 1000.0, 100.0)"))
    monkeypatch.setattr("src.data.dart_client.get_corp_code", lambda tk: "x")

    class _Dart:
        is_configured = True

        def get_financial_statement_full(self, *a, **k):
            raise AssertionError("revenue 있는 행은 재조회하면 안 됨")
    stats = dh.refetch_revenue_null(engine=mem_engine, client=_Dart())
    assert stats["candidates"] == 0 and stats["updated"] == 0
