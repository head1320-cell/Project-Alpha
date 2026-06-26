"""실데이터 전용 — 운영(KIS_USE_MOCK=0)서 실 호출 실패 시 합성 mock 금지(정직 None/빈값).
mock 모드(KIS_USE_MOCK=1)에선 기존대로 합성(회귀 불변).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.fundamentals_store import FundamentalsStore  # noqa: E402
from src.data.price_factors_store import PriceFactorsStore  # noqa: E402


# ── 펀더멘털 (DART 실패 시) ──
def test_fundamentals_real_mode_no_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    s = FundamentalsStore.get_default()
    monkeypatch.setattr(s, "_real_raw_financials", lambda code, item=None: None)
    assert s._build_factors("005930") == {}   # 운영 — 합성 금지


def test_fundamentals_mock_mode_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    s = FundamentalsStore.get_default()
    monkeypatch.setattr(s, "_real_raw_financials", lambda code, item=None: None)
    f = s._build_factors("005930")
    assert f and len(f) > 5    # mock 모드 — 합성 산출(회귀)


# ── 가격 팩터 (OHLCV 실패 시) ──
def test_price_factors_real_mode_empty(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    s = PriceFactorsStore.get_default()
    monkeypatch.setattr(s, "_fetch_ohlcv", lambda code: None)
    assert s._build_factors("005930") == {}


def test_price_factors_mock_mode_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    s = PriceFactorsStore.get_default()
    monkeypatch.setattr(s, "_fetch_ohlcv", lambda code: None)
    f = s._build_factors("005930")
    assert f and len(f) > 5


# ── 시장 지표/수급 (실 OHLCV 없음) ──
def test_market_indicators_real_mode_no_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.data.market_data as md
    monkeypatch.setattr(md, "_real_kis_ohlcv", lambda code, days=150: None)
    data = md.MarketDataProvider.get_default()._compute_all_indicators("005930")
    assert data["foreign_net_5d"] is None       # 수급 합성 금지
    assert data["_source"] == "unavailable"
    assert "rsi_14" not in data                 # 합성 OHLCV 미사용 → 지표 미산출


def test_market_indicators_mock_mode_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    import src.data.market_data as md
    monkeypatch.setattr(md, "_real_kis_ohlcv", lambda code, days=150: None)
    data = md.MarketDataProvider.get_default()._compute_all_indicators("005930")
    assert data["foreign_net_5d"] is not None   # mock 합성(회귀)
    assert "rsi_14" in data


# ── OHLCV 로더 (DB/KIS 모두 없음) ──
def test_ohlcv_loader_real_mode_empty(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.data.ohlcv_loader as ol
    monkeypatch.setattr(ol, "_db_ohlcv_df", lambda *a, **k: None)
    monkeypatch.setattr(ol, "_kis_ohlcv_df", lambda *a, **k: None)
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-06-01", prefer="auto")
    assert df is not None and df.empty          # 빈 df — 합성 금지


def test_ohlcv_loader_mock_mode_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    import src.data.ohlcv_loader as ol
    monkeypatch.setattr(ol, "_db_ohlcv_df", lambda *a, **k: None)
    monkeypatch.setattr(ol, "_kis_ohlcv_df", lambda *a, **k: None)
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-06-01", prefer="auto")
    assert df is not None and not df.empty      # mock df(회귀)


# ── 컨센서스 추정치 (실 소스 미연결 — 운영선 합성 금지) ──
def test_consensus_real_mode_no_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    from src.data.consensus_store import ESTIMATE_CATALOG, ConsensusStore
    s = ConsensusStore.get_default()
    est = s._build_estimates("005930")
    assert all(est.get(e.id) is None for e in ESTIMATE_CATALOG)  # 운영 — 합성 추정치 금지
    assert est["_source"] == "unavailable"


def test_consensus_mock_mode_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.data.consensus_store import ConsensusStore
    s = ConsensusStore.get_default()
    est = s._build_estimates("005930")
    assert est["_source"] == "consensus_mock"        # mock 모드 — 합성(회귀)
    assert est.get("fwd_per") is not None


# ── 확장 팩터 (합성 베이스 vs 운영) ──
def test_extended_factors_real_mode_no_synthetic_base(monkeypatch):
    from src.data.extended_factors_store import ExtendedFactorsStore
    s = ExtendedFactorsStore.get_default()
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    n_mock = len(s._build("005930"))
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    real = s._build("005930")
    assert len(real) < n_mock     # 운영 — 합성 베이스 생략(실 override만, 미충족 "—")
