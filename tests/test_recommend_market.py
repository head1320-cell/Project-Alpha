"""recommend() — market 국면 연결(버그) + 신뢰도 반영."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.engine.macro_recommender as mr  # noqa: E402


def test_recommend_threads_market_into_analyze(monkeypatch):
    """US 탭 추천이 실제 US 국면을 쓰는지 — 과거엔 analyze()가 market 없이 항상 KR이었음."""
    seen: list[str] = []   # recommend 외에 black_litterman 등도 analyze를 부르므로 전부 기록

    class _FakeState:
        regime = "Goldilocks"
        growth_axis = 0.3
        inflation_axis = -0.2
        stress_score = 40.0
        confidence = 0.8

    class _FakeAnalyzer:
        def analyze(self, snapshot=None, market="kr"):
            seen.append(market)
            return _FakeState()

    import src.engine.regime_analyzer as ra
    monkeypatch.setattr(ra, "RegimeAnalyzer", lambda: _FakeAnalyzer())  # 정의처 패치(함수 내 지역 import)
    out = mr.recommend("us")
    assert "us" in seen                    # recommend가 market=us를 analyze로 전달(버그 수정 전엔 kr뿐)
    assert out["market"] == "us"


def test_recommend_returns_confidence_and_overlay():
    out = mr.recommend("kr")
    assert "confidence" in out                                  # 신뢰도 노출
    assert 0.0 <= out["confidence"] <= 1.0
    top = out["top"]
    assert "holdings_final" in top and "cash_overlay_pct" in top
    assert isinstance(out["low_conviction"], bool)
    assert out.get("data_lag_note")                             # 후행성 주석
    # 저확신이면 현금 앵커가 최종 배분에 등장
    if out["confidence"] < 0.99 and top["holdings_final"]:
        assert abs(round(sum(h["weight"] for h in top["holdings_final"]), 1) - 100.0) < 0.5
