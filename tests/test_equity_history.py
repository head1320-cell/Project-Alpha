"""AI3 — ★쓰는 코드★ 에쿼티 이력을 하루 한 행으로 남긴다.

표(`live_daily_pnl`)도 리더(`drawdown_from_history`)도 보존정책도 다 있었는데
★쓰는 코드가 저장소에 없었다★(`drawdown.py:18` 이 스스로 그렇게 적어 뒀다).
그래서 킬스위치의 `auto_dd`·`auto_cb` 가 발동할 수 없었다.

이 파일이 거는 계약:
  · 하루 한 행 — 같은 날 여러 틱은 `ending` 만 갱신한다
  · ★`starting` 은 그날 첫 관측에만★ — 나중 틱이 덮으면 일중 드로다운이 정의상
    0 으로 수렴한다(`(start-end)/start`)
  · ★조회 실패는 행을 만들지 않는다★ — 0 으로 적으면 `_fetch_account_state` 가
    애써 지킨 "실패 ≠ 잔고 0" 구분이 무너진다
  · 출처를 **함께** 적는다 — mock 도 기록하되 라벨한다
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from src.domain.equity_observation import SOURCE_BROKER, SOURCE_MOCK
from src.execution.drawdown import drawdown_from_history
from src.execution.equity_history import record_observation
from src.execution.live_schemas import init_live_trading_schema


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng


def _rows(eng) -> list[tuple]:
    with eng.connect() as c:
        return list(c.execute(text(
            "SELECT trade_date, starting_equity_krw, ending_equity_krw, "
            "equity_source, execution_mode FROM live_daily_pnl ORDER BY trade_date")))


def _state(equity):
    return {"equity_krw": equity}


# ═══════════════════════════════════════════════════════════════════════════
# ① 한 번 관측하면 한 행이 생긴다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_first_observation_writes_one_row(engine):
    out = record_observation(engine, account_state=_state(100.0),
                             execution_mode="SHADOW", source=SOURCE_BROKER,
                             trade_date="2026-09-14")
    assert out["written"] is True
    rows = _rows(engine)
    assert len(rows) == 1
    assert rows[0][1] == 100.0 and rows[0][2] == 100.0   # starting == ending
    assert rows[0][3] == SOURCE_BROKER and rows[0][4] == "SHADOW"


# ═══════════════════════════════════════════════════════════════════════════
# ②③ ★하루 한 행★ — `ending` 만 갱신, `starting` 은 불변
# ═══════════════════════════════════════════════════════════════════════════

def test_a_second_tick_updates_ending_only(engine):
    record_observation(engine, account_state=_state(100.0), execution_mode="SHADOW",
                       source=SOURCE_BROKER, trade_date="2026-09-14")
    record_observation(engine, account_state=_state(80.0), execution_mode="SHADOW",
                       source=SOURCE_BROKER, trade_date="2026-09-14")
    rows = _rows(engine)
    assert len(rows) == 1, "같은 날에 행이 둘 생겼다"
    assert rows[0][2] == 80.0, "ending 이 갱신되지 않았다"


def test_the_starting_equity_never_moves(engine):
    """★일중 드로다운이 정의상 0 으로 수렴하는 것을 막는다★

    `(start - end) / start` 이므로 매 틱 `start` 를 덮으면 언제나 start==end 가
    되어 일중 드로다운이 **영원히 0** 이다 — `auto_cb` 가 다시 발동 불능이 된다.
    """
    record_observation(engine, account_state=_state(100.0), execution_mode="SHADOW",
                       source=SOURCE_BROKER, trade_date="2026-09-14")
    for equity in (95.0, 90.0, 85.0):
        record_observation(engine, account_state=_state(equity), execution_mode="SHADOW",
                           source=SOURCE_BROKER, trade_date="2026-09-14")
    rows = _rows(engine)
    assert rows[0][1] == 100.0, f"starting 이 덮였다: {rows[0][1]}"
    assert rows[0][2] == 85.0


def test_a_new_day_starts_a_new_row(engine):
    record_observation(engine, account_state=_state(100.0), execution_mode="SHADOW",
                       source=SOURCE_BROKER, trade_date="2026-09-14")
    record_observation(engine, account_state=_state(90.0), execution_mode="SHADOW",
                       source=SOURCE_BROKER, trade_date="2026-09-15")
    rows = _rows(engine)
    assert len(rows) == 2
    assert rows[1][1] == 90.0, "새 날의 starting 은 그날 첫 관측값이다"


# ═══════════════════════════════════════════════════════════════════════════
# ④ ★조회 실패는 행을 만들지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_failed_fetch_writes_nothing(engine):
    """★`None` 을 0 으로 적으면 "실패" 가 "잔고 0" 이 된다★"""
    out = record_observation(engine, account_state={"equity_krw": None},
                             execution_mode="SHADOW", source=SOURCE_BROKER,
                             trade_date="2026-09-14")
    assert out["written"] is False
    assert out["reason"]
    assert _rows(engine) == []


@pytest.mark.parametrize("bad", [{}, {"equity_krw": "많음"}, {"equity_krw": float("nan")}])
def test_an_unusable_equity_writes_nothing(engine, bad):
    """★모양이 다르면 지어내지 않는다★ — 숫자가 아니면 행이 없다."""
    out = record_observation(engine, account_state=bad, execution_mode="SHADOW",
                             source=SOURCE_BROKER, trade_date="2026-09-14")
    assert out["written"] is False and out["reason"]
    assert _rows(engine) == []


def test_a_written_row_is_not_always_refused(engine):
    """★짝★ 언제나 거절하는 구현을 배제한다."""
    assert record_observation(engine, account_state=_state(1.0),
                              execution_mode="SHADOW", source=SOURCE_BROKER,
                              trade_date="2026-09-14")["written"] is True


# ═══════════════════════════════════════════════════════════════════════════
# ⑤ ★출처를 함께 적는다★ — mock 도 기록하되 라벨한다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_mock_observation_is_recorded_and_labelled(engine):
    record_observation(engine, account_state=_state(100.0), execution_mode="SHADOW",
                       source=SOURCE_MOCK, trade_date="2026-09-14")
    rows = _rows(engine)
    assert len(rows) == 1, "mock 이라고 기록을 안 하면 그날의 사실이 사라진다"
    assert rows[0][3] == SOURCE_MOCK


def test_mock_rows_do_not_produce_a_drawdown(engine):
    """★끝에서 끝까지★ mock 으로 쓴 이력은 킬스위치에 숫자를 주지 않는다."""
    from src.execution.drawdown import REASON_MOCK_ONLY
    record_observation(engine, account_state=_state(100.0), execution_mode="SHADOW",
                       source=SOURCE_MOCK, trade_date="2026-09-14")
    record_observation(engine, account_state=_state(50.0), execution_mode="SHADOW",
                       source=SOURCE_MOCK, trade_date="2026-09-15")
    dd = drawdown_from_history(engine)
    assert not dd.is_known
    assert dd.reason == REASON_MOCK_ONLY


def test_broker_rows_do_produce_a_drawdown(engine):
    """★짝★ 실제 조회 이력을 쓰면 드로다운이 **숫자가 된다** — 이 작업의 요점."""
    record_observation(engine, account_state=_state(100.0), execution_mode="LIVE",
                       source=SOURCE_BROKER, trade_date="2026-09-14")
    record_observation(engine, account_state=_state(100.0), execution_mode="LIVE",
                       source=SOURCE_BROKER, trade_date="2026-09-15")
    record_observation(engine, account_state=_state(80.0), execution_mode="LIVE",
                       source=SOURCE_BROKER, trade_date="2026-09-15")
    dd = drawdown_from_history(engine)
    assert dd.is_known, dd.reason
    assert dd.cumulative_pct == pytest.approx(0.20)
    assert dd.intraday_pct == pytest.approx(0.20)


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ 기록이 감시를 막지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_broken_engine_does_not_raise(engine):
    """★기록 실패가 판정을 막으면 안 된다★ (`risk_monitor.py:118` 의 관용구)"""
    class _Broken:
        def begin(self):
            raise RuntimeError("DB 없음")
        def connect(self):
            raise RuntimeError("DB 없음")

    out = record_observation(_Broken(), account_state=_state(100.0),
                             execution_mode="SHADOW", source=SOURCE_BROKER,
                             trade_date="2026-09-14")
    assert out["written"] is False
    assert "DB 없음" in out["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ ★출처는 mock 게이트가 정한다★ — 라벨을 손으로 고르지 않는다
#
# `get_kis_client()` 가 `mock_allowed()` 로 클라이언트를 고르므로, 출처도 **같은
# 게이트**를 읽어야 한다. 두 곳이 따로 판단하면 mock 클라이언트가 준 값에
# `broker` 라벨이 붙는 순간이 생긴다.
# ═══════════════════════════════════════════════════════════════════════════

def test_the_source_follows_the_mock_gate(monkeypatch):
    import src.data.mock_gate as gate
    import src.execution.equity_history as eh

    monkeypatch.setattr(gate, "mock_allowed", lambda: True)
    assert eh.current_source() == SOURCE_MOCK
    monkeypatch.setattr(gate, "mock_allowed", lambda: False)
    assert eh.current_source() == SOURCE_BROKER


def test_the_source_is_never_hardcoded_broker(monkeypatch):
    """★짝★ 언제나 `broker` 를 찍는 구현을 배제한다 — 그것이 가장 위험한 변이다."""
    import src.data.mock_gate as gate
    import src.execution.equity_history as eh

    monkeypatch.setattr(gate, "mock_allowed", lambda: True)
    assert eh.current_source() != SOURCE_BROKER


def test_the_source_reads_the_gate_not_the_env(monkeypatch):
    """★`mock_allowed()` 가 유일한 판정 기준★ (CLAUDE.md §6) — env 를 직접 안 읽는다."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "execution" / "equity_history.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Attribute) and node.attr in ("getenv", "environ"):
            raise AssertionError("환경변수를 직접 읽는다 — mock_gate 를 우회했다")
    assert "mock_allowed" in src, "게이트를 아예 안 읽는다 — 이 검사가 공허하다"
