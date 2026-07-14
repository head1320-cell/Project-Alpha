"""_evaluate_one_safe가 PIT(as_of_date) 평가 시 ValuationEngine.evaluate()에 그 시점에
실제로 공시됐을 bsns_year를 전달하는지 확인 — wall-clock 연도로 미래 재무가 새던
look-ahead bias 수정.

배경: evaluate()는 bsns_year가 None이면 datetime.now().year-1로 폴백한다. PIT 경로의
유일한 호출부(_evaluate_one_safe)가 이 값을 전달하지 않아, as_of_date가 과거여도
RIM/DCF/DDM 계산은 항상 "현재" 연도 재무를 썼다. 이 테스트는 그 배선을 고정한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.screener import ValuationScreener  # noqa: E402
from src.engine.valuation.valuation_models import UnifiedValuation, ValuationParams  # noqa: E402


class _SpyEngine:
    """evaluate() 호출 인자를 기록만 하는 가짜 엔진 — 실제 DART/가격 계산 없음."""

    def __init__(self):
        self.calls = []

    def evaluate(self, stock_code, current_price, params=None, bsns_year=None, market_cap=None):
        self.calls.append({"stock_code": stock_code, "bsns_year": bsns_year})
        return UnifiedValuation(
            ticker=stock_code, corp_name="테스트", current_price=current_price,
            intrinsic_value=100_000, gap_pct=-10.0, verdict="약간 저평가", models=[],
            financial_summary={"roe_pct": 10.0},
        )


def test_pit_evaluate_receives_asof_bsns_year():
    spy = _SpyEngine()
    screener = ValuationScreener(valuation_engine=spy)
    screener._active_asof = "2024-05-20"
    item = screener._evaluate_one_safe("005930", ValuationParams())
    assert item is not None
    # 2024-05-20 시점엔 2024 1분기(annual_only 무시)가 아니라 annual_only=True라
    # 직전 연간(2023)이 선택됨 — pit_store._period_asof 테스트에서 검증된 값과 일치.
    assert spy.calls[0]["bsns_year"] == "2023"


def test_non_pit_evaluate_bsns_year_stays_none():
    spy = _SpyEngine()
    screener = ValuationScreener(valuation_engine=spy)
    # _active_asof 미설정(run() 호출 전, 또는 실시간 평가) — 기존처럼 bsns_year 미지정
    item = screener._evaluate_one_safe("005930", ValuationParams())
    assert item is not None
    assert spy.calls[0]["bsns_year"] is None


def test_pit_evaluate_skips_without_wallclock_fallback_on_invalid_asof():
    # as_of_date 파싱 실패 시 datetime.now() 폴백 대신 평가 자체를 스킵 —
    # look-ahead 재발 방지가 핵심 불변식(정직하게 실패, 조용히 오염되지 않음).
    spy = _SpyEngine()
    screener = ValuationScreener(valuation_engine=spy)
    screener._active_asof = "not-a-date"
    item = screener._evaluate_one_safe("005930", ValuationParams())
    assert item is None
    assert spy.calls == []
