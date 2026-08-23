"""정직 카운터 — universe_size(유니버스 총원) / ingested_count / evaluated_actual(실평가) / capped(상한 발동)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.screener import ValuationScreener  # noqa: E402


def test_universe_size_and_evaluated_actual():
    sc = ValuationScreener()
    r = sc.run(universe="kospi50", filter_ast=None, liquidity_floor="off", limit=100)
    assert r.universe_size == 50                    # 프리셋 총원
    assert r.evaluated_actual == 50 - r.failures    # 실제 산출 아이템 수(게이트 전)
    assert r.capped is False
    assert r.total_passed == r.evaluated_actual     # 게이트 off + 무필터 → 표시==평가


def test_capped_flag_when_over_live_compute(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_LIVE_COMPUTE", "10")
    sc = ValuationScreener()
    codes = [f"90{i:04d}" for i in range(30)]       # 합성 30종목 (mock 결정론 평가)
    r = sc.run(universe=codes, filter_ast=None, liquidity_floor="off", limit=100)
    assert r.universe_size == 30
    assert r.capped is True
    assert r.evaluated_actual <= 10                 # 상한만큼만 실평가


def test_gate_on_reduces_passed_not_evaluated():
    sc = ValuationScreener()
    r = sc.run(universe="kospi50", filter_ast=None, liquidity_floor="relaxed", limit=100)
    assert r.evaluated_actual == 50 - r.failures    # 평가는 게이트와 무관
    assert r.total_passed <= r.evaluated_actual     # 게이트가 표시만 줄임
