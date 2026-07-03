"""KR/US 국면 분리 + 축이 regime_axes 기반으로 계산되는지."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.regime_analyzer import RegimeAnalyzer, get_regime_states  # noqa: E402

REGIMES = ("Goldilocks", "Reflation", "Stagflation", "Deflation", "데이터 부족")


def test_analyze_market_param():
    a = RegimeAnalyzer()
    snap = a.collector.collect_all(use_cache=True)
    kr = a.analyze(snap, market="kr")
    us = a.analyze(snap, market="us")
    assert kr.regime in REGIMES and us.regime in REGIMES
    assert kr.market == "kr" and us.market == "us"


def test_get_regime_states_both():
    states = get_regime_states()
    assert set(states.keys()) == {"kr", "us"}
    assert states["kr"].market == "kr" and states["us"].market == "us"
