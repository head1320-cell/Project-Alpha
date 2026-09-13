"""어댑터 둘 — ★계산은 각자, 어휘는 하나★ (AB3)

설계: `docs/plans` AB

## 두 어댑터는 **깊게** 다르다

| | 백테스트 하루 | 보유 하루 |
|---|---|---|
| 총변동 | `portfolio_return` 이 **독립적으로 기록돼 있다** | ★독립 관측이 없다★ |
| 잔차 | 총변동 − Σ축 = 실재하는 값 | ★계산 불가★ |

★이 차이를 가리면 거짓말이 된다★ — 보유 경로에서 "가격 기여" 를 총합이라 부르면
잔차가 **구조적으로 0** 이 되고, 그 0 은 "완전히 설명했다" 로 읽힌다. 실제로는
배당·수수료·매매가 빠진 한 축을 총합으로 승격한 것뿐이다. 이 저장소에는 체결·예수금
기록이 없어(`live_daily_pnl` 비어 있음) 진짜 총변동을 관측할 길이 없다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.domain.daily_explanation import (
    DRIVER_DIVIDEND,
    DRIVER_FEE,
    DRIVER_FX,
    DRIVER_PRICE,
    DRIVER_REBALANCE,
    DRIVER_SET_HOLDING,
    DRIVER_SET_STRATEGY,
    RESIDUAL_INTERACTION,
    RESIDUAL_UNEXPLAINED,
    STRATEGY_DRIVERS,
    fold_price_basis,
)
from src.engine.daily_explain_backtest import explain_backtest_day
from src.engine.daily_explain_holdings import explain_holdings_day


# ═══════════════════════════════════════════════════════════════════════════
# 백테스트 어댑터 — 총변동이 독립적으로 있다
# ═══════════════════════════════════════════════════════════════════════════
def _row(**over) -> dict:
    base = {"date": "2026-09-11", "portfolio_return": 0.41,
            "allocation_effect": 0.31, "selection_effect": 0.16,
            "macro_effect": -0.02, "netting_effect": 0.0, "cost_effect": -0.08,
            "regime": "GOLDILOCKS",
            "coverage": {"n_total": 5, "n_known": 5, "complete": True,
                         "missing": []}}
    base.update(over)
    return base


def test_a_complete_row_calls_its_residual_interaction():
    exp = explain_backtest_day(_row(), run_id=7)
    assert exp.driver_set == DRIVER_SET_STRATEGY
    assert exp.residual_kind == RESIDUAL_INTERACTION
    assert exp.residual_pct == pytest.approx(0.41 - (0.31 + 0.16 - 0.02 + 0.0 - 0.08),
                                             abs=1e-9)
    assert exp.missing_drivers == {}


def test_an_incomplete_row_calls_its_residual_unexplained():
    """★짝★ 커버리지가 불완전하면 복리라고 부르지 않는다."""
    exp = explain_backtest_day(
        _row(macro_effect=None,
             coverage={"n_total": 5, "n_known": 4, "complete": False,
                       "missing": ["macro_effect"]}), run_id=7)
    assert exp.residual_kind == RESIDUAL_UNEXPLAINED
    assert "macro_effect" in exp.missing_drivers
    assert exp.missing_drivers["macro_effect"]
    assert "복리" not in exp.summary_ko or "상호작용" not in exp.summary_ko


def test_an_unknown_total_makes_the_residual_incalculable():
    """★총변동을 모르면 잔차도 모른다★ — 0 으로 적지 않는다."""
    exp = explain_backtest_day(_row(portfolio_return=None), run_id=7)
    assert exp.total_change_pct is None
    assert exp.residual_pct is None and exp.residual_reason


def test_the_backtest_adapter_uses_only_strategy_drivers():
    exp = explain_backtest_day(_row(), run_id=7)
    assert set(exp.drivers) == set(STRATEGY_DRIVERS)
    assert exp.price_basis is None, "전략 분해에 가격 기준 축은 없다"


# ═══════════════════════════════════════════════════════════════════════════
# 보유 어댑터 — ★총변동을 독립적으로 관측하지 못한다★
# ═══════════════════════════════════════════════════════════════════════════
_RET = pd.DataFrame(
    {"005930": [0.010, -0.004], "000660": [-0.020, 0.006]},
    index=pd.to_datetime(["2026-09-10", "2026-09-11"]))


@pytest.fixture
def stub(monkeypatch):
    """가격·기준을 고정한다 — DB 없이 어댑터의 **논리**를 잰다."""
    monkeypatch.setattr("src.engine.daily_explain_holdings._load_returns",
                        lambda *a, **k: _RET)
    monkeypatch.setattr("src.engine.daily_explain_holdings._price_basis_of",
                        lambda *a, **k: {"basis": "uniform_raw",
                                         "state": "degraded", "reason": None})


def test_the_price_contribution_is_not_called_the_total(stub):
    """★가격 축을 총합으로 승격하지 않는다★ — 잔차가 구조적으로 0 이 된다.

    이 저장소에는 체결·예수금 기록이 없어(`live_daily_pnl` 비어 있음) 실제
    총변동을 관측할 길이 없다. 그래서 잔차는 **0 이 아니라 계산 불가**다.
    """
    exp = explain_holdings_day({"005930": 60.0, "000660": 40.0},
                               as_of="2026-09-11")
    assert exp.residual_pct is None, "잔차를 0 으로 만들었습니다"
    assert exp.residual_reason and "관측" in exp.residual_reason
    assert "총합" in exp.summary_ko or "총변동" in exp.summary_ko


def test_the_price_driver_is_the_weighted_sum(stub):
    exp = explain_holdings_day({"005930": 60.0, "000660": 40.0},
                               as_of="2026-09-11")
    expected = (0.6 * -0.004 + 0.4 * 0.006) * 100
    assert exp.drivers[DRIVER_PRICE] == pytest.approx(expected, abs=1e-9)


def test_dividend_and_fx_are_always_missing(stub):
    """⑦ 데이터가 없어서 못 잰다 — 구현이 게을러서가 아니다."""
    exp = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    for d in (DRIVER_DIVIDEND, DRIVER_FX):
        assert exp.drivers[d] is None
        assert d in exp.missing_drivers and len(exp.missing_drivers[d]) >= 30


def test_no_trades_given_is_not_no_trades(stub):
    """⑬ ★"매매 없음" 과 "매매를 못 받음" 은 다른 사실이다★"""
    unknown = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    assert unknown.drivers[DRIVER_REBALANCE] is None
    assert DRIVER_REBALANCE in unknown.missing_drivers

    none_today = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11",
                                      trades=[])
    assert none_today.drivers[DRIVER_REBALANCE] == 0.0
    assert DRIVER_REBALANCE not in none_today.missing_drivers


def test_fees_follow_the_trades(stub):
    exp = explain_holdings_day(
        {"005930": 100.0}, as_of="2026-09-11",
        trades=[{"ticker": "005930", "notional_krw": 1_000_000, "fee_krw": 1_500}],
        portfolio_value=100_000_000)
    assert exp.drivers[DRIVER_FEE] == pytest.approx(-0.0015, abs=1e-9)
    assert DRIVER_FEE not in exp.missing_drivers


def test_the_price_basis_is_declared(stub):
    """⑪ 무엇을 썼는지 **선언**한다 — 로더를 바꾸지 않는다."""
    exp = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    assert exp.price_basis["basis"] == "uniform_raw"
    assert "원주가" in exp.summary_ko


def test_a_market_holiday_keeps_both_dates(stub):
    """⑫ ★휴장일을 지어내지 않는다★ — 요청일과 실제 쓴 날을 **둘 다** 남긴다."""
    exp = explain_holdings_day({"005930": 100.0}, as_of="2026-09-13")  # 일요일
    assert exp.as_of == "2026-09-11", "가장 가까운 직전 거래일을 쓰지 않았습니다"
    assert exp.price_basis["as_of_requested"] == "2026-09-13"
    assert exp.price_basis["as_of_effective"] == "2026-09-11"


def test_no_price_row_at_all_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr("src.engine.daily_explain_holdings._load_returns",
                        lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr("src.engine.daily_explain_holdings._price_basis_of",
                        lambda *a, **k: None)
    exp = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    assert exp.drivers[DRIVER_PRICE] is None
    assert DRIVER_PRICE in exp.missing_drivers
    assert exp.total_change_pct is None


def test_the_holdings_adapter_uses_only_holding_drivers(stub):
    exp = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    assert exp.driver_set == DRIVER_SET_HOLDING
    assert not (set(exp.drivers) & set(STRATEGY_DRIVERS)), "축을 섞었습니다"


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ 가격 기준 접기 — 순수 함수
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("counts,expected", [
    ({"uniform_adjusted": 3}, "uniform_adjusted"),
    ({"uniform_raw": 3}, "uniform_raw"),
    ({"uniform_raw": 2, "uniform_adjusted": 1}, "mixed"),
    ({"mixed": 1, "uniform_adjusted": 2}, "mixed"),
    ({"unknown": 3}, "unknown"),
    ({}, "unknown"),
    (None, "unknown"),
])
def test_fold_price_basis(counts, expected):
    """★한 종목이라도 정의가 다르면 `mixed` 다★ — 전부-아니면-전무 계약."""
    assert fold_price_basis(counts) == expected


def test_fold_ignores_zero_counts():
    """0 인 칸이 판정을 바꾸면 안 된다."""
    assert fold_price_basis({"uniform_adjusted": 3, "uniform_raw": 0,
                             "mixed": 0, "unknown": 0}) == "uniform_adjusted"


def test_the_price_source_is_stated_as_a_fact_not_an_inference(stub):
    """★`load_returns` 는 `daily_prices` 한 곳만 읽는다★ — mock 폴백이 없다.

    행이 돌아왔다면 출처는 DB 다(추론이 아니라 그 함수의 유일한 경로다).
    안 돌아왔으면 출처를 **말하지 않는다**.
    """
    got = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    assert got.price_basis["source"] == "db"


def test_no_rows_means_no_source_claim(monkeypatch):
    monkeypatch.setattr("src.engine.daily_explain_holdings._load_returns",
                        lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr("src.engine.daily_explain_holdings._price_basis_of",
                        lambda *a, **k: None)
    exp = explain_holdings_day({"005930": 100.0}, as_of="2026-09-11")
    assert exp.price_basis["source"] is None


# ═══════════════════════════════════════════════════════════════════════════
# ★어댑터가 **실제로 만든** 문장을 읽는다★
# ─────────────────────────────────────────────────────────────────────────────
# 상수만 훑는 전수 검사는 f-string 으로 만들어지는 사유를 못 본다 — 실제로
# 백테스트 어댑터의 동적 사유에 대시가 하나 더 남아 있었고, 고정 사유를 넣고
# 재던 테스트는 그것을 놓쳤다. ★검사 대상은 생산물이다.★
# ═══════════════════════════════════════════════════════════════════════════
def _produced_sentences(stub_applied: bool = False) -> list[str]:
    out = [
        explain_backtest_day(_row(), run_id=7).summary_ko,
        explain_backtest_day(
            _row(macro_effect=None,
                 coverage={"n_total": 5, "n_known": 4, "complete": False,
                           "missing": ["macro_effect"]}), run_id=7).summary_ko,
        explain_backtest_day(_row(portfolio_return=None), run_id=7).summary_ko,
    ]
    if stub_applied:
        out += [
            explain_holdings_day({"005930": 100.0}, as_of="2026-09-11").summary_ko,
            explain_holdings_day({"005930": 100.0}, as_of="2026-09-11", trades=[],
                                 portfolio_value=1e8).summary_ko,
        ]
    return out


def test_produced_sentences_never_double_dash(stub):
    """★"… — … — …" 은 읽히지 않는다★ 절마다 대시는 최대 하나다."""
    for text in _produced_sentences(stub_applied=True):
        for clause in text.split(". "):
            assert clause.count(" — ") <= 1, f"대시가 둘 이상: {clause}"


def test_produced_sentences_carry_no_markdown(stub):
    for text in _produced_sentences(stub_applied=True):
        for mark in ("**", "__", "`"):
            assert mark not in text, f"{mark!r} in {text}"


def test_produced_reasons_carry_no_markdown_either(stub):
    """★사유도 API 응답이다★ — 문장에 안 꿰여도 그대로 나간다."""
    exps = [
        explain_backtest_day(
            _row(macro_effect=None,
                 coverage={"n_total": 5, "n_known": 4, "complete": False,
                           "missing": ["macro_effect"]}), run_id=7),
        explain_holdings_day({"005930": 100.0}, as_of="2026-09-11"),
    ]
    for exp in exps:
        strings = [exp.residual_reason or "", *exp.missing_drivers.values()]
        for text in strings:
            for mark in ("**", "__", "`"):
                assert mark not in text, f"{mark!r} in {text!r}"


# ═══════════════════════════════════════════════════════════════════════════
# ★변이 h 가 이 테스트를 요구했다★ — `_price_basis_of` 자체를 재지 않았다
# ─────────────────────────────────────────────────────────────────────────────
# 위 `test_the_price_basis_is_declared` 는 `_price_basis_of` 를 통째로 스텁하므로
# 어댑터가 **받은 값을 전달하는지**만 잰다. 그 함수 안에서 `fold_price_basis` 를
# 부르는지, `price_quality` 의 실측을 쓰는지는 아무도 안 봤다 — 그래서 반환값을
# `"uniform_adjusted"` 로 박아도 초록이었다. 여기서는 **한 겹 아래**를 스텁한다.
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("basis_counts,expected", [
    ({"uniform_raw": 2}, "uniform_raw"),
    ({"uniform_adjusted": 2}, "uniform_adjusted"),
    ({"uniform_raw": 1, "uniform_adjusted": 1}, "mixed"),
    ({"unknown": 2}, "unknown"),
])
def test_the_basis_probe_folds_what_price_quality_measured(
        monkeypatch, basis_counts, expected):
    """★실측을 접을 뿐 판정을 새로 만들지 않는다★"""
    from src.engine import daily_explain_holdings as hd

    monkeypatch.setattr(
        "src.data.price_quality.adj_close_coverage",
        lambda tickers, engine=None: {"available": True, "basis_by_ticker": {},
                                      "by_ticker": {}})
    monkeypatch.setattr(
        "src.data.price_quality.basis_rollup",
        lambda basis_by_ticker, adj_by_ticker: {"basis": basis_counts,
                                                "state": "degraded",
                                                "reason": "테스트"})
    got = hd._price_basis_of(["005930", "000660"])
    assert got is not None and got["basis"] == expected, got


def test_the_basis_probe_reports_none_when_it_cannot_measure(monkeypatch):
    """★재지 못했으면 `None`★ — 기본값을 지어내지 않는다."""
    from src.engine import daily_explain_holdings as hd
    monkeypatch.setattr(
        "src.data.price_quality.adj_close_coverage",
        lambda tickers, engine=None: {"available": False,
                                      "reason": "DB 엔진이 없습니다"})
    assert hd._price_basis_of(["005930"]) is None


def test_the_basis_probe_survives_a_raising_probe(monkeypatch):
    """★기준을 몰라도 설명은 나가야 한다★ — 한 축의 실패가 문단을 죽이지 않는다."""
    from src.engine import daily_explain_holdings as hd

    def _boom(*a, **k):
        raise RuntimeError("커버리지 조회 실패")

    monkeypatch.setattr("src.data.price_quality.adj_close_coverage", _boom)
    assert hd._price_basis_of(["005930"]) is None
