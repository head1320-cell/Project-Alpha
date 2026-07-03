"""신뢰도 가중 디리스킹 — 저확신 국면일수록 위험 배분을 현금성 앵커로 축소.

기관 크리틱: "신뢰도 27%인데 위험자산 고비중". confidence_overlay가 이를 자동 완화한다."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.macro_recommender import confidence_overlay  # noqa: E402

H = [{"us_ticker": "SPY", "us_label": "S&P500", "weight": 60.0},
     {"us_ticker": "EEM", "us_label": "신흥국", "weight": 40.0}]


def _sum(hs):
    return round(sum(h["weight"] for h in hs), 2)


def test_low_confidence_adds_cash():
    out = confidence_overlay(H, 0.27, max_derisk=0.6)
    cash = next(h for h in out if h["us_ticker"] == "BIL")
    assert abs(cash["weight"] - 44.0) < 0.5           # (1-0.27)*0.6 = 0.438 → ~44%
    assert _sum(out) == 100.0                          # 합 보존
    spy = next(h for h in out if h["us_ticker"] == "SPY")
    assert abs(spy["weight"] - 60.0 * 0.562) < 0.5     # 위험자산 비례 축소


def test_high_confidence_near_original():
    out = confidence_overlay(H, 0.80, max_derisk=0.6)
    cash = next((h for h in out if h["us_ticker"] == "BIL"), None)
    assert cash is not None and abs(cash["weight"] - 12.0) < 0.5   # (1-0.8)*0.6 = 0.12


def test_full_confidence_unchanged():
    out = confidence_overlay(H, 1.0, max_derisk=0.6)
    assert not any(h["us_ticker"] == "BIL" for h in out)
    assert _sum(out) == 100.0 and out[0]["weight"] == 60.0


def test_zero_confidence_max_derisk():
    out = confidence_overlay(H, 0.0, max_derisk=0.6)
    cash = next(h for h in out if h["us_ticker"] == "BIL")
    assert abs(cash["weight"] - 60.0) < 0.5            # cash = max_derisk


def test_existing_anchor_merges():
    h2 = H + [{"us_ticker": "BIL", "us_label": "현금성", "weight": 0.0}]
    out = confidence_overlay(h2, 0.5, max_derisk=0.6)
    bils = [h for h in out if h["us_ticker"] == "BIL"]
    assert len(bils) == 1                              # 중복 앵커 합산(단일)
    assert _sum(out) == 100.0


def test_empty_safe():
    assert confidence_overlay([], 0.3) == []
