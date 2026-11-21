"""매매일지 — 비용 · 지표 · `analyze` (설계 §5.2 · §5.3)

## 손으로 계산한 표본 (거래 여섯 · 2026년 3월 — 코스피 주식 매도세 20bp · ETF 0 · 수수료 요율 10bp 가정)

| # | 종목 | 매수 | 매도 | 비용 앞 | 수수료(매수+매도) | 세금 | 비용 뒤 |
|---|---|---|---|---|---|---|---|
| 1 | A | 100주×10,000 (3/4 09:00:00) | ×10,200 (09:00:40) | +20,000 | 1,000+1,020 | 2,040 | **+15,940** |
| 2 | B | 50주×20,000 (09:10) | ×19,800 (09:13) | −10,000 | 1,000+990 | 1,980 | **−13,970** |
| 3 | A | 100주×10,100 (09:15) | ×10,050 (09:35) | −5,000 | 1,010+1,005 | 2,010 | **−9,025** |
| 4 | C | 10주×50,000 (10:00) | ×53,000 (13:00) | +30,000 | 500+530 | 1,060 | **+27,910** |
| 5 | B | 100주×19,000 (3/5 09:05) | ×19,300 (3/6 09:30) | +30,000 | 1,900+1,930 | 3,860 | **+22,310** |
| 6 | E(ETF) | 100주×30,000 (3/6 10:00) | ×29,900 (10:20) | −10,000 | 3,000+2,990 | 0 | **−15,990** |

비용 앞 합 55,000 · 수수료 16,875 · 세금 10,950 · 비용 27,825 · 비용 뒤 합 27,175.
비용 뒤: 승 3(합 66,160) · 패 3(합 −38,985) → 승률 0.5 · 평균 이익 22,053.33 · 평균 손실 12,995 · 손익비 1.69706 ·
기대값 4,529.17 · PF 1.69706 · 손익분기 승률 38,985 ÷ 105,145 = 0.37077 · 최대 연속 손실 2회(−22,995).
누적 15,940 → 1,970 → −7,055 → 20,855 → 43,165 → 27,175 · 고점 대비 하락의 최댓값 22,995.
비용 비중 27,825 ÷ 55,000 = 0.50591 · 거래 대금 16,875,000 → 대금 대비 비용 16.489bp.
"""
from __future__ import annotations

import pytest

from src.engine.trade_journal import NOT_COVERED, analyze
from src.engine.trade_journal.costs import ASSUMED, INFERRED, NOT_APPLICABLE, OBSERVED, UNKNOWN, CostOptions, cost_of
from src.engine.trade_journal.fills import normalize
from src.engine.trade_journal.metrics import HOLDING_BUCKETS, summarize


def row(at, symbol, side, qty, price, **extra) -> dict:
    return {"executed_at": at, "symbol": symbol, "side": side, "quantity": qty, "price": price, **extra}


def K(at, symbol, side, qty, price, **extra) -> dict:
    return row(at, symbol, side, qty, price, market="KOSPI", instrument="stock", **extra)


SAMPLE = [
    K("2026-03-04 09:00:00", "A", "buy", 100, 10_000), K("2026-03-04 09:00:40", "A", "sell", 100, 10_200),
    K("2026-03-04 09:10:00", "B", "buy", 50, 20_000), K("2026-03-04 09:13:00", "B", "sell", 50, 19_800),
    K("2026-03-04 09:15:00", "A", "buy", 100, 10_100), K("2026-03-04 09:35:00", "A", "sell", 100, 10_050),
    K("2026-03-04 10:00:00", "C", "buy", 10, 50_000), K("2026-03-04 13:00:00", "C", "sell", 10, 53_000),
    K("2026-03-05 09:05:00", "B", "buy", 100, 19_000), K("2026-03-06 09:30:00", "B", "sell", 100, 19_300),
    row("2026-03-06 10:00:00", "E", "buy", 100, 30_000, market="KOSPI", instrument="etf"),
    row("2026-03-06 10:20:00", "E", "sell", 100, 29_900, market="KOSPI", instrument="etf"),
]
OPTS = {"commission_bp": 10}


def fill(r: dict):
    fills, rejects = normalize([r])
    assert rejects == []
    return fills[0]


# ══ 비용과 그 근거 ════════════════════════════════════════════════════════════

def test_a_fee_in_the_file_is_observed_and_wins_over_the_rate():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "buy", 100, 10_000, fee=333)), CostOptions(commission_bp=10))
    assert (c.fee, c.fee_basis) == (333.0, OBSERVED)


def test_without_a_fee_column_the_users_rate_is_an_assumption():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "buy", 100, 10_000)), CostOptions(commission_bp=10))
    assert (c.fee, c.fee_basis) == (1_000.0, ASSUMED)


def test_without_a_fee_or_a_rate_the_fee_is_unknown_not_zero():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "buy", 100, 10_000)), CostOptions())
    assert (c.fee, c.fee_basis) == (None, UNKNOWN) and c.total is None


def test_a_zero_rate_is_a_real_answer():
    """수수료 0(이벤트 계좌)은 사용자가 준 값이다 — 미상과 다르다."""
    c = cost_of(fill(K("2026-03-04 09:00", "A", "buy", 100, 10_000)), CostOptions(commission_bp=0))
    assert (c.fee, c.fee_basis, c.total) == (0.0, ASSUMED, 0.0)


def test_a_buy_carries_no_sell_tax():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "buy", 100, 10_000)), CostOptions(commission_bp=10))
    assert (c.tax, c.tax_basis) == (0.0, NOT_APPLICABLE)


def test_a_tax_in_the_file_is_observed():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "sell", 100, 10_000, tax=1_999)), CostOptions(commission_bp=10))
    assert (c.tax, c.tax_basis) == (1_999.0, OBSERVED)


def test_without_a_tax_column_the_dated_table_estimates_it_and_says_where_from():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "sell", 100, 10_200)), CostOptions(commission_bp=10))
    assert (c.tax, c.tax_basis, c.tax_bp) == (2_040.0, INFERRED, 20)
    assert c.tax_rate["grade"] == "T1" and c.tax_rate["sources"] and c.tax_rate["period"]["from"] == "2026-01-01"


def test_the_estimate_follows_the_trade_date_not_a_constant():
    y25 = cost_of(fill(K("2025-06-02 09:00", "A", "sell", 100, 10_000)), CostOptions())
    y26 = cost_of(fill(K("2026-06-02 09:00", "A", "sell", 100, 10_000)), CostOptions())
    assert (y25.tax, y26.tax) == (1_500.0, 2_000.0)


def test_an_etf_sale_is_taxed_zero_and_that_is_a_value():
    c = cost_of(fill(row("2026-03-06 10:20", "E", "sell", 100, 29_900, market="KOSPI", instrument="etf")), CostOptions())
    assert (c.tax, c.tax_basis) == (0.0, INFERRED)


def test_an_unknown_market_leaves_the_tax_unknown():
    c = cost_of(fill(row("2026-03-04 09:00", "A", "sell", 100, 10_000)), CostOptions(commission_bp=10))
    assert (c.tax, c.tax_basis) == (None, UNKNOWN) and c.tax_reason == "unknown_market_or_instrument"
    assert c.total is None, "세금을 모르면 그 체결의 비용도 모른다"


def test_the_users_default_market_is_an_assumption_not_an_estimate():
    c = cost_of(fill(row("2026-03-04 09:00", "A", "sell", 100, 10_000)),
                CostOptions(unknown_market="KOSPI", unknown_instrument="stock"))
    assert (c.tax, c.tax_basis) == (2_000.0, ASSUMED)


def test_the_master_table_is_consulted_before_the_users_default():
    master = {"E": {"market": "KOSDAQ", "is_etf": True}}.get
    c = cost_of(fill(row("2026-03-04 09:00", "E", "sell", 100, 10_000)),
                CostOptions(unknown_market="KOSPI", unknown_instrument="stock", master=master))
    assert (c.tax, c.tax_basis) == (0.0, INFERRED), "마스터가 ETF 라고 아는데 사용자의 기본값(주식)으로 덮으면 안 된다"
    assert c.tax_rate["market"] == "KOSDAQ", "시장도 마스터의 것이다(코스피·코스닥 세율이 같아 금액으로는 안 갈린다)"


def test_a_date_outside_the_tax_table_is_unknown_with_the_tables_reason():
    c = cost_of(fill(K("2015-03-04 09:00", "A", "sell", 100, 10_000)), CostOptions())
    assert (c.tax, c.tax_basis, c.tax_reason) == (None, UNKNOWN, "outside_schedule")


# ══ 요약 통계 ═════════════════════════════════════════════════════════════════

NET = [15_940.0, -13_970.0, -9_025.0, 27_910.0, 22_310.0, -15_990.0]


def test_the_summary_matches_the_hand_computation():
    s = summarize(NET)
    assert (s["n"], s["wins"], s["losses"], s["flats"]) == (6, 3, 3, 0)
    assert s["win_rate"] == 0.5 and s["total"] == 27_175.0
    assert s["gross_profit"] == 66_160.0 and s["gross_loss"] == -38_985.0
    assert s["avg_win"] == pytest.approx(22_053.3333, abs=1e-3) and s["avg_loss"] == 12_995.0
    assert s["payoff"] == pytest.approx(1.697063, abs=1e-6)
    assert s["expectancy"] == pytest.approx(4_529.1667, abs=1e-3)
    assert s["profit_factor"] == pytest.approx(1.697063, abs=1e-6)
    assert s["breakeven_win_rate"] == pytest.approx(38_985 / 105_145, abs=1e-9)
    assert s["edge_over_breakeven"] == pytest.approx(0.5 - 38_985 / 105_145, abs=1e-9)
    assert s["max_losing_streak"] == {"count": 2, "amount": -22_995.0}
    assert s["small_sample"] is True


def test_no_trades_means_no_numbers_not_zeros():
    s = summarize([])
    assert s["n"] == 0
    for k in ("win_rate", "avg_win", "avg_loss", "payoff", "expectancy", "profit_factor", "breakeven_win_rate", "edge_over_breakeven"):
        assert s[k] is None, f"{k} 가 거래 0건에서 값을 냈다: {s[k]!r}"
    assert s["total"] == 0.0 and s["max_losing_streak"] == {"count": 0, "amount": 0.0}


def test_without_a_loss_the_ratios_that_divide_by_losses_are_unknown():
    s = summarize([100.0, 50.0])
    assert s["win_rate"] == 1.0 and s["avg_loss"] is None and s["payoff"] is None and s["profit_factor"] is None
    assert s["breakeven_win_rate"] is None


def test_without_a_win_the_payoff_is_unknown_and_the_profit_factor_is_zero():
    s = summarize([-100.0, -50.0])
    assert s["avg_win"] is None and s["payoff"] is None and s["profit_factor"] == 0.0 and s["win_rate"] == 0.0
    assert s["breakeven_win_rate"] is None and s["edge_over_breakeven"] is None


def test_breakeven_win_rate_accounts_for_flat_trades():
    """본전 거래가 있으면 '몇 할을 이겨야 본전인가'가 줄어든다 — (1 − 본전 비율) ÷ (1 + 손익비).

    그래야 ★승률 − 손익분기 승률의 부호가 기대값의 부호와 같다★(본전을 빼지 않으면 기대값이 0 인데 차이가 음수로 나온다).
    """
    s = summarize([100.0, 0.0, -100.0, 0.0])
    assert s["expectancy"] == 0.0 and s["payoff"] == 1.0
    assert s["breakeven_win_rate"] == 0.25 and s["edge_over_breakeven"] == 0.0


@pytest.mark.parametrize("pnls", [[300.0, -100.0, 0.0, 0.0, -100.0], [100.0, -300.0, 0.0, 100.0], [50.0, 0.0, -20.0],
                                  [10.0, -10.0, -10.0, 0.0, 0.0, 0.0, 25.0]])
def test_the_edge_has_the_sign_of_the_expectancy(pnls):
    s = summarize(pnls)
    assert (s["edge_over_breakeven"] > 0) == (s["expectancy"] > 0) and (s["edge_over_breakeven"] < 0) == (s["expectancy"] < 0)


def test_a_flat_trade_is_neither_a_win_nor_a_loss_but_counts_in_the_rate():
    s = summarize([100.0, 0.0, -100.0, 0.0])
    assert (s["wins"], s["losses"], s["flats"], s["win_rate"]) == (1, 1, 2, 0.25)


def test_a_flat_trade_does_not_break_a_losing_streak_but_a_win_does():
    assert summarize([-1.0, 0.0, -2.0, 5.0, -4.0])["max_losing_streak"] == {"count": 2, "amount": -3.0}


def test_thirty_trades_is_no_longer_a_small_sample():
    assert summarize([1.0] * 29)["small_sample"] is True and summarize([1.0] * 30)["small_sample"] is False


# ══ analyze — 표본 전체 ═══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def out():
    return analyze(SAMPLE, OPTS)


def test_inputs_are_counted(out):
    assert out["inputs"] == {"rows": 12, "fills": 12, "rejected": 0, "symbols": 4,
                             "first": "2026-03-04T09:00:00", "last": "2026-03-06T10:20:00"}


def test_net_summary_matches_the_hand_computation(out):
    s = out["summary"]["net"]
    assert s["n"] == 6 and s["total"] == 27_175.0 and s["win_rate"] == 0.5
    assert s["payoff"] == pytest.approx(1.697063, abs=1e-6) and s["max_losing_streak"]["amount"] == -22_995.0
    assert out["summary"]["net_excluded"] == 0 and out["basis"]["pnl_basis"] == "net"


def test_gross_summary_is_before_costs(out):
    s = out["summary"]["gross"]
    assert s["total"] == 55_000.0 and s["gross_profit"] == 80_000.0 and s["gross_loss"] == -25_000.0
    assert s["payoff"] == pytest.approx((80_000 / 3) / (25_000 / 3))


def test_costs_are_broken_down_and_shared(out):
    c = out["summary"]["costs"]
    assert (c["fees"], c["taxes"], c["total"]) == (16_875.0, 10_950.0, 27_825.0)
    assert c["share_of_gross"] == pytest.approx(27_825 / 55_000)
    assert c["turnover"] == 16_875_000.0 and c["bp_of_turnover"] == pytest.approx(16.4889, abs=1e-4)
    assert c["per_trade"] == pytest.approx(27_825 / 6)


def test_the_basis_block_counts_how_each_cost_was_known(out):
    b = out["basis"]
    assert b["fee"] == {OBSERVED: 0, ASSUMED: 12, UNKNOWN: 0}
    assert b["tax"] == {OBSERVED: 0, INFERRED: 6, ASSUMED: 0, UNKNOWN: 0, NOT_APPLICABLE: 6}
    assert b["commission_bp"] == 10
    rates = {(r["market"], r["instrument"]): r["bp"] for r in b["tax_rates"]}
    assert rates == {("KOSPI", "stock"): 20, ("KOSPI", "etf"): 0}
    assert all(r["grade"] == "T1" and r["sources"] for r in b["tax_rates"])


def test_the_curve_and_its_drawdown(out):
    c = out["curve"]
    assert c["basis"] == "net"
    assert [p["cum"] for p in c["points"]] == [15_940.0, 1_970.0, -7_055.0, 20_855.0, 43_165.0, 27_175.0]
    assert [p["drawdown"] for p in c["points"]] == [0.0, 13_970.0, 22_995.0, 0.0, 0.0, 15_990.0]
    assert c["max_drawdown"] == 22_995.0 and c["points"][0]["at"] == "2026-03-04T09:00:40"


def test_holding_time_buckets(out):
    rows = {r["key"]: r for r in out["breakdowns"]["holding"]}
    assert list(rows) == [k for k, _label, _lo, _hi in HOLDING_BUCKETS]
    assert {k: r["n"] for k, r in rows.items()} == {"lt_1m": 1, "1m_5m": 1, "5m_30m": 2, "30m_day": 1, "overnight": 1}
    assert rows["5m_30m"]["total"] == -9_025.0 - 15_990.0 and rows["5m_30m"]["win_rate"] == 0.0
    assert all(r["label"] for r in rows.values())


def test_entry_hour_weekday_symbol_and_day(out):
    b = out["breakdowns"]
    assert {r["key"]: r["n"] for r in b["hour"]} == {9: 4, 10: 2}
    assert {r["label"]: r["n"] for r in b["weekday"]} == {"수": 4, "목": 1, "금": 1}
    assert {r["key"]: r["total"] for r in b["symbol"]} == {"C": 27_910.0, "B": 8_340.0, "A": 6_915.0, "E": -15_990.0}
    assert [(r["key"], r["n"], r["total"]) for r in b["daily"]] == [("2026-03-04", 4, 20_855.0), ("2026-03-06", 2, 6_320.0)]


@pytest.mark.parametrize("name", ["holding", "hour", "weekday", "symbol", "daily"])
def test_every_breakdown_adds_up_to_the_whole(out, name):
    rows = out["breakdowns"][name]
    assert sum(r["n"] for r in rows) == 6 and sum(r["total"] for r in rows) == pytest.approx(27_175.0)


def test_entries_right_after_a_loss_are_set_apart(out):
    a = out["breakdowns"]["after_loss"]
    assert a["within_minutes"] == 10
    assert (a["after"]["n"], a["after"]["total"], a["after"]["win_rate"]) == (1, -9_025.0, 0.0)
    assert (a["other"]["n"], a["other"]["total"]) == (5, 27_175.0 + 9_025.0)


def test_the_trade_table_lists_closed_trades_in_closing_order(out):
    assert out["trades_total"] == 6
    t = out["trades"][0]
    assert (t["symbol"], t["gross"], t["fees"], t["taxes"], t["cost"], t["net"]) == ("A", 20_000.0, 2_020.0, 2_040.0, 4_060.0, 15_940.0)
    assert (t["opened_at"], t["closed_at"], t["holding_seconds"], t["same_day"]) == ("2026-03-04T09:00:00", "2026-03-04T09:00:40", 40, True)
    assert [x["net"] for x in out["trades"]] == [15_940.0, -13_970.0, -9_025.0, 27_910.0, 22_310.0, -15_990.0]


def test_what_is_not_covered_is_listed(out):
    assert out["not_covered"] == list(NOT_COVERED) and len(NOT_COVERED) >= 5
    assert any("양도" in s for s in NOT_COVERED) and any("미실현" in s or "미청산" in s for s in NOT_COVERED)


# ══ analyze — 모르는 것 · 버린 것 · 끝나지 않은 것 ════════════════════════════

def test_when_fees_are_unknown_net_is_unavailable_and_gross_drives_the_rest():
    o = analyze(SAMPLE, {})
    assert o["summary"]["net"] is None and o["summary"]["net_excluded"] == 6
    assert o["basis"]["pnl_basis"] == "gross" and o["curve"]["basis"] == "gross"
    assert o["summary"]["gross"]["total"] == 55_000.0
    assert o["summary"]["costs"]["total"] is None and o["summary"]["costs"]["share_of_gross"] is None
    assert o["trades"][0]["net"] is None and o["trades"][0]["cost"] is None and o["trades"][0]["fees"] is None
    assert o["trades"][0]["taxes"] == 2_040.0, "아는 성분은 그대로 보여 준다"


def test_a_trade_with_unknown_cost_is_left_out_of_net_and_counted():
    rows = [*SAMPLE[:4], row("2026-03-04 09:15:00", "Z", "buy", 1, 100), row("2026-03-04 09:16:00", "Z", "sell", 1, 110)]
    o = analyze(rows, OPTS)                      # Z 는 시장을 모른다 → 세금 미상
    assert o["summary"]["gross"]["n"] == 3 and o["summary"]["net"]["n"] == 2 and o["summary"]["net_excluded"] == 1
    assert o["basis"]["pnl_basis"] == "gross", "일부만 비용을 알면 곡선·묶음은 비용 앞 기준이다(섞지 않는다)"
    assert o["basis"]["tax"][UNKNOWN] == 1


def test_rejected_rows_come_back_with_reasons_and_counts():
    o = analyze([*SAMPLE, row("어제", "A", "buy", 1, 1), row("2026-03-04 09:00", "A", "buy", 0, 1),
                 row("2026-03-04 09:00", "A", "buy", -1, 1)], OPTS)
    assert o["inputs"]["rows"] == 15 and o["inputs"]["rejected"] == 3
    assert o["rejects"]["count"] == 3
    assert {k: v["count"] for k, v in o["rejects"]["by_reason"].items()} == {"bad_datetime": 1, "bad_quantity": 2}
    assert o["rejects"]["sample"][0] == {"row": 12, "reason": "bad_datetime", "message": "체결 일시를 읽지 못했습니다."}
    assert o["summary"]["net"]["total"] == 27_175.0, "버린 줄이 나머지 계산을 바꾸면 안 된다"


def test_an_open_position_is_reported_apart_and_not_scored():
    o = analyze([*SAMPLE, K("2026-03-06 11:00:00", "D", "buy", 10, 1_000), K("2026-03-06 11:30:00", "D", "sell", 4, 1_100)], OPTS)
    assert o["summary"]["net"]["n"] == 6, "미청산 거래는 승패에 넣지 않는다"
    assert len(o["open_positions"]) == 1
    p = o["open_positions"][0]
    assert (p["symbol"], p["open_quantity"], p["realized_gross"]) == ("D", 6.0, 400.0)
    # 실현분의 비용: 매수 수수료 10,000×0.1%×(4/10)=4 + 매도 수수료 4.4 + 세금 8.8
    assert p["realized_cost"] == pytest.approx(17.2) and p["realized_net"] == pytest.approx(382.8)
    assert o["summary"]["open_realized"] == {"n": 1, "gross": 400.0, "net": pytest.approx(382.8)}


def test_sells_without_a_buy_are_counted_apart():
    o = analyze([K("2026-03-04 09:00:00", "Q", "sell", 5, 100), *SAMPLE], OPTS)
    assert o["unmatched_sells"]["count"] == 1 and o["unmatched_sells"]["sample"][0]["symbol"] == "Q"
    assert o["summary"]["net"]["total"] == 27_175.0


def test_date_only_fills_are_kept_out_of_time_statistics():
    rows = [K("2026-03-04", "A", "buy", 100, 10_000), K("2026-03-04", "A", "sell", 100, 10_200), *SAMPLE[2:4]]
    o = analyze(rows, OPTS)
    assert o["summary"]["net"]["n"] == 2
    assert sum(r["n"] for r in o["breakdowns"]["holding"]) == 1 and sum(r["n"] for r in o["breakdowns"]["hour"]) == 1
    assert o["breakdowns"]["without_time"] == 1
    assert sum(r["n"] for r in o["breakdowns"]["symbol"]) == 2, "시각이 없어도 종목·일별 집계에는 들어간다"


def test_an_empty_file_is_an_answer_with_nothing_in_it():
    o = analyze([], OPTS)
    assert o["inputs"]["fills"] == 0 and o["summary"]["gross"]["n"] == 0 and o["summary"]["net"]["n"] == 0
    assert o["curve"]["points"] == [] and o["curve"]["max_drawdown"] is None and o["trades"] == []


def test_holding_bucket_edges():
    def one(seconds: int, days: int = 0) -> str:
        from datetime import datetime, timedelta
        start = datetime(2026, 3, 4, 9, 0, 0)
        end = start + timedelta(days=days, seconds=seconds)
        o = analyze([K(start.strftime("%Y-%m-%d %H:%M:%S"), "A", "buy", 1, 100),
                     K(end.strftime("%Y-%m-%d %H:%M:%S"), "A", "sell", 1, 101)], OPTS)
        return next(r["key"] for r in o["breakdowns"]["holding"] if r["n"] == 1)
    assert [one(59), one(60), one(299), one(300), one(1_799), one(1_800), one(6 * 3600)] == \
        ["lt_1m", "1m_5m", "1m_5m", "5m_30m", "5m_30m", "30m_day", "30m_day"]
    assert one(60, days=1) == "overnight"


def test_after_loss_window_edge():
    def after(minutes_later: int) -> int:
        rows = [K("2026-03-04 09:00:00", "A", "buy", 1, 100), K("2026-03-04 09:10:00", "A", "sell", 1, 90),
                K(f"2026-03-04 09:{10 + minutes_later:02d}:00", "B", "buy", 1, 100), K("2026-03-04 10:30:00", "B", "sell", 1, 110)]
        return analyze(rows, OPTS)["breakdowns"]["after_loss"]["after"]["n"]
    assert [after(0), after(10), after(11)] == [1, 1, 0]


def test_a_win_before_does_not_make_the_next_entry_an_after_loss_entry():
    rows = [K("2026-03-04 09:00:00", "A", "buy", 1, 100), K("2026-03-04 09:10:00", "A", "sell", 1, 130),
            K("2026-03-04 09:12:00", "B", "buy", 1, 100), K("2026-03-04 09:30:00", "B", "sell", 1, 90)]
    assert analyze(rows, OPTS)["breakdowns"]["after_loss"]["after"]["n"] == 0


# ══ 가장자리 ══════════════════════════════════════════════════════════════════

def test_a_first_losing_trade_is_a_drawdown_from_the_starting_line():
    rows = [K("2026-03-04 09:00:00", "A", "buy", 1, 100), K("2026-03-04 09:10:00", "A", "sell", 1, 90),
            K("2026-03-04 09:20:00", "B", "buy", 1, 100), K("2026-03-04 09:30:00", "B", "sell", 1, 104)]
    c = analyze(rows, {"commission_bp": 0, "unknown_market": None})["curve"]
    # 세금 20bp: 90×0.002=0.18 · 104×0.002=0.208 → 비용 뒤 −10.18 · +3.792
    assert [p["drawdown"] for p in c["points"]] == pytest.approx([10.18, 10.18 - 3.792])
    assert c["max_drawdown"] == pytest.approx(10.18) and c["max_drawdown_at"] == "2026-03-04T09:10:00"


def test_the_worst_and_best_trades_are_set_out(out):
    e = out["extremes"]
    assert [t["net"] for t in e["worst"]] == [-15_990.0, -13_970.0, -9_025.0], "손실 거래만 · 큰 손실부터"
    assert [t["net"] for t in e["best"]] == [27_910.0, 22_310.0, 15_940.0]
    assert e["worst"][0]["symbol"] == "E" and e["limit"] == 5


def test_extremes_are_capped():
    rows = []
    for i in range(8):
        rows += [K(f"2026-03-04 09:{i:02d}:00", f"S{i}", "buy", 1, 1_000), K(f"2026-03-04 10:{i:02d}:00", f"S{i}", "sell", 1, 900 - i)]
    e = analyze(rows, OPTS)["extremes"]
    assert len(e["worst"]) == 5 and e["best"] == [] and e["worst"][0]["symbol"] == "S7"


def test_cost_share_says_why_it_is_missing():
    lose = [K("2026-03-04 09:00:00", "A", "buy", 1, 100), K("2026-03-04 09:10:00", "A", "sell", 1, 90)]
    assert analyze(lose, OPTS)["summary"]["costs"]["share_reason"] == "gross_not_positive"
    assert analyze(lose, OPTS)["summary"]["costs"]["share_of_gross"] is None
    assert analyze(SAMPLE, {})["summary"]["costs"]["share_reason"] == "cost_unknown"
    assert analyze([], OPTS)["summary"]["costs"]["share_reason"] == "no_trades"
    assert analyze(SAMPLE, OPTS)["summary"]["costs"]["share_reason"] is None


def test_buys_only_leave_an_open_position_and_no_trades():
    o = analyze([K("2026-03-04 09:00:00", "A", "buy", 3, 100), K("2026-03-04 09:05:00", "A", "buy", 2, 110)], OPTS)
    assert o["summary"]["gross"]["n"] == 0 and o["trades"] == [] and o["curve"]["points"] == []
    p = o["open_positions"][0]
    assert (p["open_quantity"], p["open_amount"], p["realized_gross"], p["realized_cost"], p["realized_net"]) == (5.0, 520.0, 0.0, 0.0, 0.0)


def test_what_is_left_open_is_carried_at_what_was_paid_for_the_remaining_lots():
    """선입선출 — 먼저 산 것부터 팔렸으니 남은 것은 나중에 산 것이다."""
    o = analyze([K("2026-03-04 09:00:00", "A", "buy", 3, 100), K("2026-03-04 09:05:00", "A", "buy", 2, 110),
                 K("2026-03-04 09:10:00", "A", "sell", 4, 120)], OPTS)
    p = o["open_positions"][0]
    assert (p["open_quantity"], p["open_amount"]) == (1.0, 110.0)
    assert p["realized_gross"] == 3 * 20 + 1 * 10


def test_an_oversold_fill_charges_the_trade_only_for_the_matched_part():
    """보유 6주에 10주 매도 — 맞춘 6주의 몫만 이 거래의 비용이다(나머지 4주는 매수 없는 매도)."""
    o = analyze([K("2026-03-04 09:00:00", "A", "buy", 6, 1_000), K("2026-03-04 09:10:00", "A", "sell", 10, 1_100)], OPTS)
    t = o["trades"][0]
    assert t["gross"] == 600.0
    assert t["fees"] == pytest.approx(6.0 + 11.0 * 0.6) and t["taxes"] == pytest.approx(22.0 * 0.6)
    assert o["unmatched_sells"]["count"] == 1 and o["unmatched_sells"]["sample"][0]["quantity"] == 4.0
    assert o["unmatched_sells"]["sample"][0]["message"]


def test_names_come_from_the_file_first_and_then_from_the_master():
    rows = [K("2026-03-04 09:00:00", "005930", "buy", 1, 100, name="파일의 이름"), K("2026-03-04 09:10:00", "005930", "sell", 1, 110),
            K("2026-03-04 09:00:00", "000660", "buy", 1, 100), K("2026-03-04 09:20:00", "000660", "sell", 1, 110),
            K("2026-03-04 09:00:00", "999999", "buy", 1, 100), K("2026-03-04 09:30:00", "999999", "sell", 1, 110)]
    master = {"005930": {"name": "마스터의 이름"}, "000660": {"name": "SK하이닉스"}}.get
    names = {t["symbol"]: t["name"] for t in analyze(rows, OPTS, master=master)["trades"]}
    assert names == {"005930": "파일의 이름", "000660": "SK하이닉스", "999999": None}, "모르는 종목의 이름을 지어내지 않는다"


def test_the_master_classifies_only_what_it_actually_knows():
    """마스터가 'ETF 아님'이라고만 알면 주식이라고 단정하지 않는다(ETN·ELW 일 수 있다) — 그룹 코드가 ST 일 때만 주식이다."""
    sell = row("2026-03-04 09:00", "X", "sell", 100, 10_000)
    def tax(flags):
        return cost_of(fill(sell), CostOptions(master={"X": flags}.get))
    assert tax({"market": "KOSPI", "is_etf": False}).tax_basis == UNKNOWN
    assert tax({"market": "KOSPI", "group_code": "EN"}).tax_basis == UNKNOWN
    assert (tax({"market": "KOSPI", "group_code": "ST"}).tax, tax({"market": "KOSPI", "group_code": "ST"}).tax_basis) == (2_000.0, INFERRED)
    assert tax({"market": "KOSDAQ", "group_code": "EF"}).tax == 0.0
    assert tax({"market": "나스닥", "group_code": "ST"}).tax_basis == UNKNOWN


def test_the_fills_own_market_wins_over_the_master():
    c = cost_of(fill(row("2026-03-04 09:00", "X", "sell", 100, 10_000, market="KOSPI", instrument="stock")),
                CostOptions(master={"X": {"market": "KOSDAQ", "is_etf": True}}.get))
    assert (c.tax, c.tax_basis) == (2_000.0, INFERRED) and c.tax_rate["market"] == "KOSPI"


@pytest.mark.parametrize("bad", [{"commission_bp": -1}, {"commission_bp": float("nan")}, {"commission_bp": "10"},
                                 {"unknown_market": "NASDAQ"}, {"unknown_instrument": "etn"}])
def test_bad_options_are_refused_not_ignored(bad):
    with pytest.raises(ValueError):
        analyze(SAMPLE, bad)


def test_a_tax_written_on_a_buy_row_is_kept_as_observed():
    c = cost_of(fill(K("2026-03-04 09:00", "A", "buy", 100, 10_000, tax=0)), CostOptions(commission_bp=10))
    assert (c.tax, c.tax_basis) == (0.0, OBSERVED)


def test_the_response_is_plain_json(out):
    import json
    assert json.loads(json.dumps(out)) == out, "날짜·튜플 같은 것이 섞이면 응답 모양이 달라진다"


def test_a_losing_trade_opened_and_closed_in_the_same_second_is_not_after_itself():
    rows = [K("2026-03-04 09:00:00", "A", "buy", 1, 100), K("2026-03-04 09:00:00", "A", "sell", 1, 90)]
    a = analyze(rows, OPTS)["breakdowns"]["after_loss"]
    assert (a["after"]["n"], a["other"]["n"]) == (0, 1)


def test_long_lists_are_capped_and_the_full_counts_stay():
    rows = []
    for i in range(501):
        day = f"2026-03-{4 + i // 200:02d}"
        rows += [K(f"{day} 09:{i % 60:02d}:{i // 60 % 60:02d}", f"S{i}", "buy", 1, 100), K(f"{day} 14:00:00", f"S{i}", "sell", 1, 101)]
    rows += [row("모름", "A", "buy", 1, 1)] * 60 + [K("2026-03-04 08:00:00", f"Q{i}", "sell", 1, 100) for i in range(55)]
    o = analyze(rows, OPTS)
    assert (len(o["trades"]), o["trades_total"], o["trades_limit"]) == (500, 501, 500)
    assert (len(o["rejects"]["sample"]), o["rejects"]["count"]) == (50, 60)
    assert (len(o["unmatched_sells"]["sample"]), o["unmatched_sells"]["count"]) == (50, 55)
    assert o["summary"]["net"]["n"] == 501 and len(o["curve"]["points"]) == 501, "요약과 곡선은 자르지 않는다"


def test_of_two_equally_long_losing_streaks_the_costlier_one_is_reported():
    assert summarize([-1.0, -1.0, 5.0, -10.0, -10.0])["max_losing_streak"] == {"count": 2, "amount": -20.0}
    assert summarize([-10.0, -10.0, 5.0, -1.0, -1.0])["max_losing_streak"] == {"count": 2, "amount": -20.0}


def test_sentences_shown_on_screen_carry_no_dash_and_the_basis_words_are_the_repositorys():
    """화면 문체 규칙(ADR 005) — 줄표(— –)를 쓰지 않는다. 근거의 낱말은 저장소의 증거 어휘(관측·추론·가정·미상)에 맞춘 열쇠다."""
    from src.engine.trade_journal import UNMATCHED_SELL_MESSAGE
    from src.engine.trade_journal.costs import TAX_UNKNOWN_MESSAGES
    from src.engine.trade_journal.fills import REJECT_REASONS
    for s in [*NOT_COVERED, UNMATCHED_SELL_MESSAGE, *TAX_UNKNOWN_MESSAGES.values(), *REJECT_REASONS.values()]:
        assert "—" not in s and "–" not in s, s
    assert (OBSERVED, INFERRED, ASSUMED, UNKNOWN, NOT_APPLICABLE) == ("observed", "inferred", "assumed", "unknown", "not_applicable")
