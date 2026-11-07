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
    """★출처를 안 적는 행★ — AI 이전에 쓰였을 법한 모양이다.

    예전에는 이것이 곧 "실제 이력" 을 뜻했다(리더에 필터가 아예 없었으니까).
    이제는 **미상**이고, 미상은 브로커가 아니다 — 그 사실을
    `test_an_undeclared_source_is_not_treated_as_broker` 가 건다.
    실제 조회 이력을 뜻하려면 `_broker()` 를 쓴다.
    """
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO live_daily_pnl (trade_date, starting_equity_krw, ending_equity_krw) "
            "VALUES (:d, :s, :e)"), {"d": date, "s": start, "e": end})


def _broker(eng, date: str, start: float, end: float) -> None:
    """브로커에서 **실제로 조회한** 잔고 행 — 드로다운 계열에 들어갈 수 있는 유일한 것."""
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO live_daily_pnl (trade_date, starting_equity_krw, "
            "ending_equity_krw, equity_source) VALUES (:d, :s, :e, 'broker')"),
            {"d": date, "s": start, "e": end})


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
    _broker(engine, "2026-09-01", 100_000_000, 100_000_000)
    _broker(engine, "2026-09-02", 100_000_000, 90_000_000)
    dd = drawdown_from_history(engine)
    assert dd.is_known is True
    assert dd.reason is None
    assert dd.cumulative_pct == pytest.approx(0.10), "정점 1억 → 9천만이면 누적 10%"
    assert dd.intraday_pct == pytest.approx(0.10), "시작 1억 → 마감 9천만이면 일중 10%"


def test_a_flat_history_is_zero_drawdown_not_unknown(engine):
    """★0 을 못 쓰게 만든 것이 아니다★ — 진짜 0 은 0 이어야 한다."""
    _broker(engine, "2026-09-01", 100_000_000, 100_000_000)
    dd = drawdown_from_history(engine)
    assert dd.is_known is True
    assert dd.cumulative_pct == pytest.approx(0.0)


def test_recovery_from_a_peak_still_counts_the_peak(engine):
    """정점 이후 회복해도 ★정점 대비★ 로 잰다."""
    _broker(engine, "2026-09-01", 100_000_000, 120_000_000)   # 정점 1.2억
    _broker(engine, "2026-09-02", 120_000_000, 108_000_000)
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
    _broker(engine, "2026-09-01", 0.0, 0.0)
    dd = drawdown_from_history(engine)
    assert dd.is_known is False
    assert "equity" in (dd.reason or ""), dd.reason


# ═══════════════════════════════════════════════════════════════════════════
# ★AI4 — 출처로 거른다★ 합성 잔고로 킬스위치를 발동시키지 않는다
#
# `MockKISClient.get_balance()` 는 `self.cash` 로 만든 **완전 합성** 값이다
# (`kis_client.py:804`). 그것이 계열에 들어가면 `auto_dd`·`auto_cb` 가 지어낸
# 숫자로 발동한다 — CLAUDE.md §6 을 가장 위험한 자리에서 어기는 것이다.
#
# ★리더에는 원래 아무 필터도 없었다★ — `SELECT … ORDER BY trade_date` 가 전부였다.
# ═══════════════════════════════════════════════════════════════════════════

def _sourced(eng, date: str, start: float, end: float, source: str) -> None:
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO live_daily_pnl (trade_date, starting_equity_krw, "
            "ending_equity_krw, equity_source) VALUES (:d, :s, :e, :src)"),
            {"d": date, "s": start, "e": end, "src": source})


def test_mock_only_history_is_unknown_not_a_number(engine):
    """★핵심★ 합성만 있으면 드로다운은 **미상**이다 — 0 도 숫자도 아니다."""
    from src.execution.drawdown import REASON_MOCK_ONLY
    _sourced(engine, "2026-09-01", 100.0, 100.0, "mock")
    _sourced(engine, "2026-09-02", 100.0, 80.0, "mock")
    dd = drawdown_from_history(engine)
    assert not dd.is_known
    assert dd.intraday_pct is None and dd.cumulative_pct is None
    assert dd.reason == REASON_MOCK_ONLY


def test_broker_only_history_produces_numbers(engine):
    """★짝★ 실제 조회 이력은 숫자가 된다 — 필터가 모든 것을 막지는 않는다."""
    _sourced(engine, "2026-09-01", 100.0, 100.0, "broker")
    _sourced(engine, "2026-09-02", 100.0, 80.0, "broker")
    dd = drawdown_from_history(engine)
    assert dd.is_known, dd.reason
    assert dd.intraday_pct == pytest.approx(0.20)
    assert dd.cumulative_pct == pytest.approx(0.20)


def test_a_mixed_history_refuses_rather_than_quietly_picking(engine):
    """★섞였으면 거절한다★ — broker 행만 조용히 고르지 않는다.

    섞였다는 사실 자체가 사용자가 알아야 할 상태다(mock 으로 돌린 날이 이력에
    남아 있다는 뜻). 조용히 골라 쓰면 그 사실이 사라진다.
    """
    from src.execution.drawdown import REASON_MIXED_SOURCE
    _sourced(engine, "2026-09-01", 100.0, 100.0, "broker")
    _sourced(engine, "2026-09-02", 100.0, 80.0, "mock")
    dd = drawdown_from_history(engine)
    assert not dd.is_known
    assert dd.reason == REASON_MIXED_SOURCE


def test_an_undeclared_source_is_not_treated_as_broker(engine):
    """★미상 ≠ 브로커★ 출처를 안 적은 옛 행을 실제 조회로 읽지 않는다."""
    from src.execution.drawdown import REASON_UNDECLARED_SOURCE
    _row(engine, "2026-09-01", 100.0, 100.0)      # equity_source 없음
    _row(engine, "2026-09-02", 100.0, 80.0)
    dd = drawdown_from_history(engine)
    assert not dd.is_known
    assert dd.reason == REASON_UNDECLARED_SOURCE


def test_the_four_refusals_are_all_different(engine):
    """★짝★ 네 사유가 한 문자열로 뭉개지지 않는다."""
    from src.execution.drawdown import (
        REASON_MIXED_SOURCE,
        REASON_MOCK_ONLY,
        REASON_NO_HISTORY,
        REASON_UNDECLARED_SOURCE,
    )
    assert len({REASON_NO_HISTORY, REASON_MOCK_ONLY,
                REASON_MIXED_SOURCE, REASON_UNDECLARED_SOURCE}) == 4


def test_the_filter_reuses_the_domain_verdict(engine):
    """★판정을 두 곳에 두지 않는다★ — `usable_for_drawdown` 이 단일 출처다."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "execution" / "drawdown.py").read_text(encoding="utf-8")
    imported = {n.module: {a.name for a in n.names}
                for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.ImportFrom) and n.module}
    assert "usable_for_drawdown" in imported.get("src.domain.equity_observation", set()), (
        "출처 판정을 복사했다 — 한쪽만 고쳐도 타입 에러가 안 난다")


def test_a_table_without_the_source_column_is_unknown(tmp_path):
    """★컬럼이 없으면 어느 행이 실제 조회인지 **가릴 수 없다**★

    변이 배터리에서 "컬럼이 없을 때 필터를 건너뛴다" 가 **살아남았다** — 픽스처가
    언제나 컬럼을 만들어 주어 이 분기를 아무도 밟지 않았기 때문이다. 운영 DB 는
    `CREATE TABLE IF NOT EXISTS` 로는 칸을 얻지 못하므로(`add_columns` 경로가
    막히면) 실제로 이 상태가 될 수 있다.

    ★그때 숫자를 내면 "출처를 확인했다" 는 없는 사실이 생긴다.★
    """
    from src.execution.drawdown import REASON_NO_SOURCE_COLUMN
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE live_daily_pnl (trade_date DATE PRIMARY KEY, "
                       "starting_equity_krw REAL, ending_equity_krw REAL)"))
        c.execute(text("INSERT INTO live_daily_pnl VALUES ('2026-09-01', 100.0, 100.0)"))
        c.execute(text("INSERT INTO live_daily_pnl VALUES ('2026-09-02', 100.0, 80.0)"))
    dd = drawdown_from_history(eng)
    assert not dd.is_known, "출처를 가릴 수 없는데 숫자를 냈다"
    assert dd.reason == REASON_NO_SOURCE_COLUMN


def test_the_no_column_path_is_not_the_only_outcome(tmp_path):
    """★짝★ 컬럼이 있으면 그 사유가 나오지 않는다 — 언제나 거절하는 구현 배제."""
    from src.execution.drawdown import REASON_NO_SOURCE_COLUMN
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    _broker(eng, "2026-09-01", 100.0, 100.0)
    _broker(eng, "2026-09-02", 100.0, 80.0)
    dd = drawdown_from_history(eng)
    assert dd.reason != REASON_NO_SOURCE_COLUMN
    assert dd.is_known
