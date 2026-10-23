"""Macro API contract + encoding regression (production hardening).

Locks the frontend↔backend contract for /macro/recommend so schema drift that would
crash the Recommend tab is caught in CI, and verifies Korean text survives JSON
serialization as UTF-8 (no mojibake) — the "corrupted Korean" class of bug.
"""
import json
import os

os.environ.setdefault("KIS_USE_MOCK", "1")


def _has_hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in s)


def test_recommend_shape_matches_frontend_requirements():
    """RecommendTab reads recommend.top.{holdings_final,name,composite,fit_score,
    cash_overlay_pct,signal,id} and recommend.regime.{quadrant_kr,stress}. A backend
    change that drops any of these must fail here (not silently crash the tab)."""
    from src.engine.macro_recommender import recommend
    r = recommend("kr")
    assert isinstance(r, dict) and not r.get("error")

    top = r.get("top")
    assert isinstance(top, dict), "recommend.top must be an object"
    assert isinstance(top.get("holdings_final"), list), "top.holdings_final must be a list"
    for k in ("name", "composite", "fit_score", "cash_overlay_pct", "signal", "id"):
        assert k in top, f"top.{k} missing — RecommendTab would break"

    regime = r.get("regime")
    assert isinstance(regime, dict) and "quadrant_kr" in regime and "stress" in regime
    assert isinstance(r.get("confidence"), (int, float))


def test_recommend_korean_utf8_roundtrip():
    """Korean fields must serialize as real UTF-8 Hangul, not escaped/garbled bytes."""
    from src.engine.macro_recommender import recommend
    r = recommend("kr")
    dumped = json.dumps(r, ensure_ascii=False)
    assert _has_hangul(dumped), "expected Hangul in recommend payload (quadrant_kr etc.)"
    assert "�" not in dumped, "replacement char = encoding corruption"
    # round-trip through bytes preserves the Hangul
    assert json.loads(dumped.encode("utf-8").decode("utf-8")) == r


def test_regime_endpoint_shape_and_encoding():
    """Regime feeds the always-mounted Overview banner; guard its core keys + encoding."""
    from src.engine.regime_analyzer import RegimeAnalyzer
    st = RegimeAnalyzer().analyze(market="kr")
    keys = ("regime", "growth_axis", "inflation_axis", "stress_score", "recommended_mode")
    for k in keys:
        assert hasattr(st, k), f"regime.{k} missing"
    snapshot = {k: getattr(st, k) for k in keys}
    assert "�" not in json.dumps(snapshot, ensure_ascii=False, default=str)
