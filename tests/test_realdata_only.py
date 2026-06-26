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


# ── 수급 재배선 (investor_flows 금액 + DART 내부자) ──
def test_market_supply_real_mode_from_flows(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import pandas as pd

    import src.data.market_data as md
    # investor_flows 금액 시리즈 stub (last-5 합)
    def fake_series(ticker, field, engine=None):
        base = {"frgn_amt": [10, 20, 30, 40, 50], "orgn_amt": [1, 2, 3, 4, 5],
                "prsn_amt": [-5, -5, -5, -5, -5]}.get(field)
        return pd.Series(base) if base else None
    monkeypatch.setattr("src.data.kis_flows.load_flows_series", fake_series)
    # 실 OHLCV 존재 → close 확보 → 내부자 가격주입 경로 작동
    df = pd.DataFrame({"open": [50000] * 150, "high": [51000] * 150, "low": [49000] * 150,
                       "close": [50000] * 150, "volume": [1000] * 150})
    monkeypatch.setattr(md, "_real_kis_ohlcv", lambda code, days=150: df)
    monkeypatch.setattr("src.data.insider_flows.insider_net",
                        lambda code, days=20, price=None, as_of=None: 7.0)
    data = md.MarketDataProvider.get_default()._compute_all_indicators("005930")
    assert data["foreign_net_5d"] == 150       # 10+20+30+40+50 (금액)
    assert data["institution_net_5d"] == 15
    assert data["retail_net_5d"] == -25
    assert data["insider_net_20d"] == 7.0      # close 주입 후 set
    assert data["_source"] == "kis_real"


def test_market_supply_real_mode_empty_flows(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.data.market_data as md
    monkeypatch.setattr("src.data.kis_flows.load_flows_series", lambda *a, **k: None)
    monkeypatch.setattr(md, "_real_kis_ohlcv", lambda code, days=150: None)  # OHLCV 없음
    data = md.MarketDataProvider.get_default()._compute_all_indicators("005930")
    assert data["foreign_net_5d"] is None       # 미적재 → 정직 None
    assert data["insider_net_20d"] is None      # 가격 없음(OHLCV None) → 주입 안 됨
    assert data["_source"] == "unavailable"


def test_price_supply_uses_amt_and_new_fields(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import pandas as pd

    from src.data.price_factors_store import PRICE_FACTOR_BY_ID, PriceFactorsStore
    # 신규 필드 메타 등록 확인
    assert "retail_net_5d" in PRICE_FACTOR_BY_ID
    assert "retail_net_20d" in PRICE_FACTOR_BY_ID
    assert "insider_net_20d" in PRICE_FACTOR_BY_ID
    seen = {}

    def fake_series(ticker, field, engine=None):
        seen[field] = True
        return pd.Series([1, 2, 3, 4, 5]) if field.endswith("_amt") else None
    monkeypatch.setattr("src.data.kis_flows.load_flows_series", fake_series)
    s = PriceFactorsStore.get_default()
    out = s._supply_factors("005930")
    assert out["foreign_net_5d"] == 15        # amt 합 (qty 아님)
    assert out["retail_net_5d"] == 15
    assert "frgn_amt" in seen and "prsn_amt" in seen   # 금액 컬럼 사용
    assert "frgn_qty" not in seen                       # qty 미사용


def test_behavioral_signal_real_path(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    from src.data.market_data import eval_behavioral_signal
    # 내부자 매수 + 개인 매도 → insider_buy_retail_sell 참
    ind = {"insider_net_20d": 5.0, "retail_net_5d": -10.0,
           "foreign_net_5d": 0, "institution_net_5d": 0}
    assert eval_behavioral_signal(ind, "insider_buy_retail_sell") is True
    # 데이터 없음(None) → 시그널 거짓 (정직, 합성 안 함)
    empty = {"insider_net_20d": None, "retail_net_5d": None,
             "foreign_net_5d": None, "institution_net_5d": None}
    assert eval_behavioral_signal(empty, "insider_buy_retail_sell") is False
