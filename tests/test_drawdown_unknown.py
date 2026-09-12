"""드로다운은 ★모르면 `None` 이다★ — 0 이 아니다 (P1-a)

## 무엇이 문제였나 (실측)

`order_executor._fetch_account_state()` 가 드로다운 두 칸을 **하드코딩 0** 으로
돌려줬다(`# TODO: live monitor에서 계산`). 그 딕트를 두 안전장치가 함께 읽는다:

    kill_switch.should_auto_trigger()      auto_dd(누적 -10%) · auto_cb(일중 -5%)
    risk_gateway._tier2_dynamic_checks() ⑨ daily_loss_limit · cumulative_dd_limit

0 은 어떤 임계값도 못 넘으므로 ★둘 다 구조적으로 발동할 수 없었다★. 게다가 예외
경로도 같은 0 을 돌려줘 **조회 실패가 "손실 0" 으로 보였다**.

CLAUDE.md §4 가 금지한 *"타당성을 조용히 제조"* 다. R 작업에서 `adj_status_of` 가
조회 실패를 `missing` 으로 보고하던 것과 같은 부류.

## 이 파일이 못 박는 것

    ★이력이 없으면 `None` + 사유. 있으면 숫자. 조회 실패는 또 다른 사유.★
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.execution.drawdown import (  # noqa: E402
    REASON_FETCH_FAILED,
    REASON_NO_HISTORY,
    drawdown_from_history,
)
from src.execution.live_schemas import init_live_trading_schema  # noqa: E402


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng


def _row(eng, date: str, start: float, end: float) -> None:
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO live_daily_pnl (trade_date, starting_equity_krw, ending_equity_krw) "
            "VALUES (:d, :s, :e)"), {"d": date, "s": start, "e": end})


# ═══════════════════════════════════════════════════════════════════════════
# ① 이력이 없으면 ★None + 사유★
# ═══════════════════════════════════════════════════════════════════════════

def test_no_history_is_unknown_not_zero(engine):
    dd = drawdown_from_history(engine)
    assert dd.intraday_pct is None, "이력이 없는데 숫자가 나왔다"
    assert dd.cumulative_pct is None
    assert dd.reason == REASON_NO_HISTORY
    assert dd.reason and len(dd.reason) > 3


def test_the_unknown_is_not_silently_falsy(engine):
    """★`None` 과 `0.0` 은 다르다★ — 호출부가 구분할 수 있어야 한다."""
    dd = drawdown_from_history(engine)
    assert dd.intraday_pct is not 0 and dd.intraday_pct != 0.0  # noqa: F632
    assert dd.is_known is False


# ═══════════════════════════════════════════════════════════════════════════
# ② ★짝★ — 이력이 있으면 숫자가 나온다 (항상-None 구현 배제)
# ═══════════════════════════════════════════════════════════════════════════

def test_history_produces_numbers(engine):
    _row(engine, "2026-09-01", 100_000_000, 100_000_000)
    _row(engine, "2026-09-02", 100_000_000, 90_000_000)
    dd = drawdown_from_history(engine)
    assert dd.is_known is True
    assert dd.reason is None
    assert dd.cumulative_pct == pytest.approx(0.10), "정점 1억 → 9천만이면 누적 10%"
    assert dd.intraday_pct == pytest.approx(0.10), "시작 1억 → 마감 9천만이면 일중 10%"


def test_a_flat_history_is_zero_drawdown_not_unknown(engine):
    """★0 을 못 쓰게 만든 것이 아니다★ — 진짜 0 은 0 이어야 한다."""
    _row(engine, "2026-09-01", 100_000_000, 100_000_000)
    dd = drawdown_from_history(engine)
    assert dd.is_known is True
    assert dd.cumulative_pct == pytest.approx(0.0)


def test_recovery_from_a_peak_still_counts_the_peak(engine):
    """정점 이후 회복해도 ★정점 대비★ 로 잰다."""
    _row(engine, "2026-09-01", 100_000_000, 120_000_000)   # 정점 1.2억
    _row(engine, "2026-09-02", 120_000_000, 108_000_000)
    dd = drawdown_from_history(engine)
    assert dd.cumulative_pct == pytest.approx(0.10)


# ═══════════════════════════════════════════════════════════════════════════
# ③ 조회 실패는 ★또 다른 사유★ — "잔고 0" 과 섞이지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_broken_engine_reports_fetch_failed(engine):
    class _Boom:
        def connect(self):
            raise RuntimeError("DB 연결 끊김")

    dd = drawdown_from_history(_Boom())
    assert dd.is_known is False
    assert dd.reason.startswith(REASON_FETCH_FAILED), dd.reason
    assert "DB 연결 끊김" in dd.reason, "★사유에 원인이 실려야 한다★"


def test_fetch_failure_and_no_history_are_different_reasons(engine):
    class _Boom:
        def connect(self):
            raise RuntimeError("x")

    assert drawdown_from_history(engine).reason != drawdown_from_history(_Boom()).reason


def test_zero_equity_history_is_not_an_error(engine):
    """★에쿼티가 0 인 것과 이력이 없는 것은 다르다.★"""
    _row(engine, "2026-09-01", 0.0, 0.0)
    dd = drawdown_from_history(engine)
    assert dd.is_known is False
    assert "equity" in (dd.reason or ""), dd.reason
