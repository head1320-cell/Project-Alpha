"""리스크·최적화 기반 자산배분 9전략 — 단위 검증 (mock 가격, 결정론적).

검증 계약: 모든 전략은 long-only·합100·결정론. + 전략별 행동(균등/현금/뷰 이동).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.risk_allocations import RISK_STRATEGIES  # noqa: E402

EXPECTED_IDS = {
    "equal_weight", "risk_parity", "hrp", "min_var", "max_div",
    "max_sharpe", "black_litterman", "managed_futures", "kelly",
}
_BY_ID = {s[0]: s[4] for s in RISK_STRATEGIES}


def _sum(weights):
    return round(sum(weights.values()), 1)


def test_registry_has_9_strategies():
    assert len(RISK_STRATEGIES) == 9
    assert {s[0] for s in RISK_STRATEGIES} == EXPECTED_IDS
    for sid, name, desc, family, fn in RISK_STRATEGIES:
        assert name and desc and family and callable(fn), f"{sid} 메타 불완전"


def test_all_sum_to_100_long_only_us():
    for sid, fn in _BY_ID.items():
        w = fn("us")
        assert w, f"{sid} 빈 결과"
        assert abs(_sum(w) - 100.0) <= 0.5, f"{sid} 합 {_sum(w)} != 100"
        assert all(v >= 0 for v in w.values()), f"{sid} 음수 비중"


def test_all_sum_to_100_long_only_kr():
    # KR 토글은 compute_strategies에서 티커 매핑 — 함수 자체는 US 티커 반환하되 mk 인자로 시세 경로 전환
    for sid, fn in _BY_ID.items():
        w = fn("kr")
        assert abs(_sum(w) - 100.0) <= 0.5, f"{sid}(kr) 합 {_sum(w)}"
        assert all(v >= 0 for v in w.values())


def test_deterministic():
    for sid, fn in _BY_ID.items():
        assert fn("us") == fn("us"), f"{sid} 비결정론적"


def test_holdings_are_known_tickers():
    from src.data.etf_prices import US_UNIVERSE
    for sid, fn in _BY_ID.items():
        for t in fn("us"):
            assert t in US_UNIVERSE, f"{sid} 미지 티커 {t}"


def test_equal_weight_is_uniform():
    w = _BY_ID["equal_weight"]("us")
    vals = list(w.values())
    assert len(w) >= 5
    assert max(vals) - min(vals) <= 0.3, "1/N 비균등"


def test_risk_parity_diversifies():
    # ERC는 본질적으로 분산 → 다수 자산 보유
    w = _BY_ID["risk_parity"]("us")
    assert len(w) >= 4, f"리스크패리티 집중됨: {w}"


def test_managed_futures_goes_cash_when_no_trend(monkeypatch):
    import src.engine.risk_allocations as ra
    monkeypatch.setattr(ra, "_mf_return", lambda t, mk: -0.1)  # 전 자산 추세 음수
    w = _BY_ID["managed_futures"]("us")
    assert w == {"BIL": 100.0}, f"전 자산 하락추세인데 현금 아님: {w}"


def test_black_litterman_falls_back_to_prior_without_regime(monkeypatch):
    import src.engine.risk_allocations as ra
    monkeypatch.setattr(ra, "_regime_tilts", lambda: None)  # 국면 조회 실패
    w = _BY_ID["black_litterman"]("us")
    assert abs(_sum(w) - 100.0) <= 0.5
    assert len(w) >= 4, "prior 폴백이 분산 배분이어야 함"


def test_black_litterman_view_shifts_allocation(monkeypatch):
    import src.engine.risk_allocations as ra
    monkeypatch.setattr(ra, "_regime_tilts", lambda: None)
    prior = _BY_ID["black_litterman"]("us")
    monkeypatch.setattr(ra, "_regime_tilts",
                        lambda: {"growth_stocks": "++", "value_stocks": "0",
                                 "bonds": "--", "commodities": "0", "cash": "0"})
    tilted = _BY_ID["black_litterman"]("us")
    # 성장주 강세(++) + 채권 약세(--) 뷰 → 성장 버킷(SPY+EEM) 비중이 prior 이상
    growth_prior = prior.get("SPY", 0) + prior.get("EEM", 0)
    growth_tilted = tilted.get("SPY", 0) + tilted.get("EEM", 0)
    assert growth_tilted >= growth_prior - 0.01, \
        f"성장 뷰가 성장 버킷 비중을 못 올림: prior {growth_prior} → tilted {growth_tilted}"
