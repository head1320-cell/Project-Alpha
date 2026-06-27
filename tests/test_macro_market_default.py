"""매크로 ETF 기본 시장 = kr(국내 ETF 실데이터 경로).
US ETF(SPY/TLT/GLD…)는 KIS 미제공이라 실데이터 소스가 없음 → 기본을 국내 ETF 대체(kr)로.
명시 market=us는 유지(오버라이드 가능, 향후 KIS 해외주식 연동 대비)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")


def test_compute_strategies_default_market_kr():
    from src.engine.tactical_allocations import compute_strategies
    assert compute_strategies()["market"] == "kr"


def test_compute_strategies_explicit_us_kept():
    from src.engine.tactical_allocations import compute_strategies
    assert compute_strategies("us")["market"] == "us"


def test_backtest_config_default_market_kr():
    from src.engine.strategy_backtest_map import backtest_config
    from src.engine.tactical_allocations import ALL_STRATEGIES
    cfg = backtest_config(ALL_STRATEGIES[0][0])
    assert cfg is not None and cfg["market"] == "kr"


def test_macro_strategies_endpoint_default_kr():
    from fastapi.testclient import TestClient

    from main_api import app
    c = TestClient(app)
    r = c.get("/api/v1/macro/strategies")   # market 미지정 → 기본 kr
    assert r.status_code == 200
    assert r.json().get("market") == "kr"
