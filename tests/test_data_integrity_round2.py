"""데이터 정합성 백본 (CIO 실사 라운드2) — 회귀 방지.

Gemini/CIO 진단: ① YoY==QoQ 복사버그 ② 실데이터 팩터에 mock 성분 오염
③ 주식수/시총 액면분할 안전(파생 주식수) ④ dps 미적재 vs 무배당 구분.
전부 실데이터 경로(_source=dart_real)의 계약 — mock 모드 경로는 불변.
"""
import os
from datetime import datetime

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.fundamentals_store import FundamentalsStore  # noqa: E402

_FH_FIELDS = ("revenue", "operating_profit", "net_income", "gross_profit",
              "total_assets", "total_liabilities", "total_equity",
              "current_assets", "current_liabilities", "operating_cf", "capex",
              "shares_outstanding", "dps")


def _snap(**kw) -> dict:
    base = dict.fromkeys(_FH_FIELDS)
    base.update(kw)
    return base


def _full_year(shares=5_000_000_000, dps=1000.0, rev=3000_000e8):
    return _snap(revenue=rev, operating_profit=400_000e8, net_income=300_000e8,
                 total_assets=4000_000e8, total_liabilities=1000_000e8,
                 total_equity=3000_000e8, current_assets=2000_000e8,
                 current_liabilities=800_000e8, operating_cf=500_000e8,
                 shares_outstanding=shares, dps=dps, gross_profit=rev * 0.4)


def _install(monkeypatch, by_year: dict):
    import src.data.dart_client as dc
    import src.data.dart_history as dh
    monkeypatch.setattr(dh, "history_snapshot",
                        lambda t, y, r, engine=None: by_year.get(str(y)))

    class _Dart:
        is_configured = False
    monkeypatch.setattr(dc, "get_dart_client", lambda: _Dart())


def test_qoq_none_without_real_quarterly_data(monkeypatch):
    """실데이터 경로: 분기 원천이 없으면 revenue_qoq=None (YoY 복붙 금지 — 정직)."""
    cy = datetime.now().year - 1
    _install(monkeypatch, {str(cy): _full_year(), str(cy - 1): _full_year(rev=2800_000e8)})
    st = FundamentalsStore()
    fac = st._build_factors("910001")
    assert fac and fac["_source"] == "dart_real"
    assert fac.get("revenue_qoq") is None, "분기 미적재인데 QoQ가 YoY 복사값으로 채워짐"
    assert fac.get("revenue_growth_yoy") is not None  # YoY는 정상


def test_no_mock_components_in_real_factors(monkeypatch):
    """실데이터 팩터에 mock 난수 성분(모멘텀/PEAD/성장가속) 오염 금지 — None(정직).

    모멘텀은 가격팩터 momentum_12_1(실측)이 담당."""
    cy = datetime.now().year - 1
    _install(monkeypatch, {str(cy): _full_year()})
    st = FundamentalsStore()
    fac = st._build_factors("910002")
    assert fac["_source"] == "dart_real"
    assert fac.get("price_momentum_12_1") is None
    assert fac.get("pead_score") is None
    assert fac.get("growth_acceleration") is None


def test_shares_derived_from_mcap_when_dart_shares_inconsistent(monkeypatch):
    """액면분할 안전장치: 시총/주가 기반 파생 주식수와 DART 주식수가 2배 이상 괴리면
    파생 주식수 채택 → BPS ₩566만 같은 pre-split 오염 차단."""
    cy = datetime.now().year - 1
    # DART 주식수가 액면분할 前 값(50배 축소)으로 오염된 시나리오
    _install(monkeypatch, {str(cy): _full_year(shares=100_000_000)})  # 1억주 (실제 50억주)
    st = FundamentalsStore()
    monkeypatch.setattr(st, "_market_snapshot", lambda code: {"mcap_억": 4_000_000.0,
                                                              "price": 80_000.0})
    raw = st._real_raw_financials("910003")
    assert raw is not None
    # 파생 주식수 = 시총 4,000,000억(=400조) / 80,000원 = 50억주 → 만주 단위 500,000
    assert abs(raw["shares"] - 500_000) / 500_000 < 0.01
    fac = st._derive_factors("910003", raw)
    # BPS = 자본 300조 / 50억주 = 60,000원 (566만원 아님)
    assert 40_000 < fac["bps"] < 90_000, f"BPS {fac['bps']} — 액면분할 오염"


def test_dividend_yield_none_when_dps_unknown(monkeypatch):
    """dps 미적재(None)면 dividend_yield=None(미상) — 0%(무배당 단정)와 구분."""
    cy = datetime.now().year - 1
    _install(monkeypatch, {str(cy): _full_year(dps=None)})
    st = FundamentalsStore()
    fac = st._build_factors("910004")
    assert fac["_source"] == "dart_real"
    assert fac.get("dividend_yield") is None
    assert fac.get("payout_ratio") is None


def test_dividend_yield_zero_when_dps_zero(monkeypatch):
    """dps=0 실적재(무배당 확정)면 dividend_yield=0 (None 아님)."""
    cy = datetime.now().year - 1
    _install(monkeypatch, {str(cy): _full_year(dps=0.0)})
    st = FundamentalsStore()
    fac = st._build_factors("910005")
    assert fac.get("dividend_yield") == 0.0


# ── 수급 금액 단위 단일화 (억) — "-1519조" 100배 뻥튀기 수정 ──

def test_kis_investor_amounts_normalized_to_억():
    """KIS pbmn(백만원) → 억 (/100). 예: 1,519,000백만 = 15,190억."""
    from src.execution.kis_client import normalize_investor_rows
    rows = normalize_investor_rows([{
        "stck_bsop_date": "20260708", "prsn_ntby_qty": "1000",
        "frgn_ntby_qty": "-2000", "orgn_ntby_qty": "500",
        "prsn_ntby_tr_pbmn": "100", "frgn_ntby_tr_pbmn": "-1519000",
        "orgn_ntby_tr_pbmn": "50",
    }])
    assert rows[0]["frgn_amt"] == -15190.0   # 억
    assert rows[0]["prsn_amt"] == 1.0
    assert rows[0]["frgn_qty"] == -2000.0    # 수량은 주 단위 유지


def test_krx_flow_amounts_normalized_to_억():
    """KRX MDC 거래대금(원) → 억 (/1e8)."""
    from src.data.krx_mdc import rows_to_flow_records
    recs = rows_to_flow_records(
        [{"date": "2026-07-08", "개인": 10.0, "외국인": -5.0, "기타외국인": 0.0}],
        [{"date": "2026-07-08", "개인": 3e8, "외국인": -1.5e12, "기타외국인": 0.0}])
    assert recs[0]["prsn_amt"] == 3.0        # 3억
    assert recs[0]["frgn_amt"] == -15000.0   # -1.5조원 = -15,000억


# ── 팩터 분류: 시가총액은 규모(Size), 안정성 아님 ──

def test_market_cap_is_size_category():
    from src.engine.filter_ast import CATEGORY_LABELS, FIELD_BY_ID
    assert FIELD_BY_ID["market_cap_억"].category == "size"
    assert CATEGORY_LABELS["size"] == "규모"
