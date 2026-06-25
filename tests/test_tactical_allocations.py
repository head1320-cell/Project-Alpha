"""택티컬 자산배분 13전략 엔진 — 단위 검증 (mock 가격, 결정론적)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.tactical_allocations import STRATEGIES, compute_strategies  # noqa: E402


def _sum(holdings):
    return round(sum(h["weight"] for h in holdings), 1)


def test_all_strategies_sum_to_100_us():
    r = compute_strategies("us")
    assert r["market"] == "us"
    assert len(r["strategies"]) == len(STRATEGIES) == 13
    for s in r["strategies"]:
        assert abs(_sum(s["holdings"]) - 100.0) <= 0.5, f"{s['name']} sum {_sum(s['holdings'])}"
        assert s["holdings"] and all("ticker" in h and "weight" in h for h in s["holdings"])
        assert s["signal"]


def test_kr_toggle_maps_tickers():
    r = compute_strategies("kr")
    assert r["market"] == "kr"
    for s in r["strategies"]:
        assert abs(_sum(s["holdings"]) - 100.0) <= 0.5
        # 국내 매핑이면 6자리 코드 또는 원본 티커(매핑 없을 때)
        for h in s["holdings"]:
            assert h["us_ticker"]  # 원본 티커는 항상 보존


def test_permanent_is_static_quarters():
    r = compute_strategies("us")
    perm = next(s for s in r["strategies"] if s["id"] == "permanent")
    by = {h["us_ticker"]: h["weight"] for h in perm["holdings"]}
    assert by == {"SPY": 25.0, "TLT": 25.0, "GLD": 25.0, "BIL": 25.0}


def test_deterministic():
    a = compute_strategies("us")
    b = compute_strategies("us")
    assert [h["weight"] for s in a["strategies"] for h in s["holdings"]] == \
           [h["weight"] for s in b["strategies"] for h in s["holdings"]]


def test_recommend_structure():
    from src.engine.macro_recommender import recommend
    r = recommend("us")
    assert r["regime"]["quadrant"] in ("Reflation", "Overheating", "Stagflation", "Disinflation")
    assert len(r["ranking"]) == 13
    assert r["ranking"][0]["id"] == r["top"]["id"]
    assert r["narrative"] and r["narrative_source"] in ("rule", "claude")
    assert r["top"]["holdings"] and r["top"]["fit_score"] is not None
