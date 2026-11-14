"""괴리 — 증권사 체결 ↔ 시뮬레이션 체결 (★순수 엔진 계약★)
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-paper-trading-monitor-design.md` §4.2 · §4.3 · 대상 `src/engine/intraday/divergence.py`

## 손으로 계산한 표본 (005930 · 2026-03-02 · 호가 단위 10원 — 5,000원 이상 20,000원 미만)

시뮬레이션: 09:02 매수 10주 @10,050 · 09:10 매도 10주 @10,100.

| 실제 체결 | 차이 | 불리함 | 틱 | bp |
|---|---|---|---|---|
| 09:03:20 매수 10주 @10,060 | +10 | +10 (비싸게 샀다) | 1.0 | 10 ÷ 10,050 × 10,000 = 9.950248… |
| 09:10:45 매도 10주 @10,090 | −10 | +10 (싸게 팔았다) | 1.0 | 10 ÷ 10,100 × 10,000 = 9.900990… |

평균 불리함 10원 · 1틱 · (9.950248 + 9.900990) ÷ 2 = 9.925619bp. 시각 차이: 매수 +1분 · 매도 0분(같은 분 안).

## 거는 것 (모두 짝과 함께)
- 같은 체결이면 차이 0 ↔ 한 틱 밀면 정확히 한 틱 · 매도는 부호가 뒤집힌다.
- 나뉜 체결은 한 덩어리(수량 합 · 수량 가중 평균가)로 견준다.
- 창 밖이면 '놓친 신호'와 '규칙 밖 매매'로 갈린다 ↔ 창을 넓히면 짝이 된다 · 창 셋의 건수를 늘 함께 낸다.
- 가까운 것부터 짝짓는다(먼저 온 것이 남의 짝을 가져가지 않는다).
- 종목 · 날짜 · 방향이 다르면 아무리 가까워도 짝이 아니다.
- 시각이 없는 줄: 전부 없으면 하루 단위로 열화 · 섞였으면 따로 빼고 센다(조용히 버리지 않는다).
- 기간 밖 · 다른 종목 · 읽지 못한 줄은 세어 적는다.
- 짝이 없으면 차이는 0 이 아니라 값 없음 + 사유.
"""
from __future__ import annotations

import pytest

from src.engine.intraday import divergence as dv

DAY = "2026-03-02"
SIM = [{"executed_at": f"{DAY} 09:02:00", "symbol": "005930", "side": "buy", "quantity": 10, "price": 10_050.0},
       {"executed_at": f"{DAY} 09:10:00", "symbol": "005930", "side": "sell", "quantity": 10, "price": 10_100.0}]


def row(at: str, side: str, qty: float, price: float, symbol: str = "005930", day: str = DAY) -> dict:
    return {"executed_at": f"{day} {at}" if at else day, "symbol": symbol, "side": side, "quantity": qty, "price": price}


def compare(actual: list[dict], sim: list[dict] | None = None, **kw) -> dict:
    return dv.compare(SIM if sim is None else sim, actual, tickers=kw.pop("tickers", ["005930"]),
                      start=kw.pop("start", DAY), end=kw.pop("end", DAY), **kw)


# ── 같은 체결 ↔ 한 틱 ────────────────────────────────────────────────────
def test_identical_fills_have_zero_gap_and_nothing_left_over():
    out = compare([row("09:02:00", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100)])
    assert out["mode"] == "timed" and out["window_minutes"] == 5
    assert out["counts"] == {"matched": 2, "sim_only": 0, "actual_only": 0}
    gap = out["price_gap"]
    assert gap["n"] == 2 and gap["mean"] == {"won": 0.0, "ticks": 0.0, "bp": 0.0}
    assert gap["adverse"] == 0 and gap["favorable"] == 0 and gap["even"] == 2
    assert out["sim_only"] == [] and out["actual_only"] == []


def test_the_hand_computed_sample():
    out = compare([row("09:03:20", "buy", 10, 10_060), row("09:10:45", "sell", 10, 10_090)])
    assert out["counts"] == {"matched": 2, "sim_only": 0, "actual_only": 0}
    buy, sell = out["matched"]
    assert (buy["side"], buy["sim_at"], buy["actual_at"]) == ("buy", f"{DAY}T09:02:00", f"{DAY}T09:03:00")
    assert (buy["sim_price"], buy["actual_price"], buy["adverse"], buy["ticks"]) == (10_050.0, 10_060.0, 10.0, 1.0)
    assert buy["bp"] == pytest.approx(10 / 10_050 * 10_000) and buy["minutes"] == 1
    assert (sell["adverse"], sell["ticks"], sell["minutes"]) == (10.0, 1.0, 0)          # 싸게 판 것도 불리함은 양수다
    assert sell["bp"] == pytest.approx(10 / 10_100 * 10_000)
    gap = out["price_gap"]
    assert gap["mean"]["won"] == 10.0 and gap["mean"]["ticks"] == 1.0
    assert gap["mean"]["bp"] == pytest.approx((10 / 10_050 + 10 / 10_100) / 2 * 10_000)
    assert gap["median"]["won"] == 10.0 and gap["adverse"] == 2 and gap["favorable"] == 0 and gap["even"] == 0
    assert out["time_gap"] == {"mean_minutes": 0.5, "median_minutes": 0.5, "max_minutes": 1}


def test_a_better_fill_is_favourable_not_adverse():
    out = compare([row("09:02:10", "buy", 10, 10_040), row("09:10:10", "sell", 10, 10_120)])
    buy, sell = out["matched"]
    assert buy["adverse"] == -10.0 and sell["adverse"] == -20.0                          # 싸게 샀고 비싸게 팔았다
    gap = out["price_gap"]
    assert gap["favorable"] == 2 and gap["adverse"] == 0 and gap["mean"]["won"] == -15.0
    assert gap["worst"]["side"] == "buy" and gap["worst"]["adverse"] == -10.0            # 가장 불리한 것 = 덜 유리한 것


def test_the_worst_pair_is_the_most_adverse_one():
    out = compare([row("09:02:10", "buy", 10, 10_080), row("09:10:10", "sell", 10, 10_090)])
    assert out["price_gap"]["worst"]["side"] == "buy" and out["price_gap"]["worst"]["adverse"] == 30.0
    assert out["price_gap"]["worst"]["ticks"] == 3.0


# ── 나뉜 체결 ───────────────────────────────────────────────────────────
def test_fills_split_within_one_minute_are_compared_as_one_lump():
    out = compare([row("09:03:05", "buy", 4, 10_060), row("09:03:40", "buy", 6, 10_070),
                   row("09:10:00", "sell", 10, 10_100)])
    assert out["counts"]["matched"] == 2 and out["inputs"] == {"sim_fills": 2, "actual_rows": 3, "actual_fills": 2}
    buy = out["matched"][0]
    assert buy["actual_quantity"] == 10 and buy["parts"] == 2
    assert buy["actual_price"] == pytest.approx((4 * 10_060 + 6 * 10_070) / 10)          # 10,066
    assert buy["adverse"] == pytest.approx(16.0) and buy["ticks"] == pytest.approx(1.6)
    assert buy["quantity_diff"] == 0


def test_a_different_quantity_is_reported_not_hidden():
    out = compare([row("09:02:30", "buy", 7, 10_050), row("09:10:00", "sell", 7, 10_100)])
    assert [m["quantity_diff"] for m in out["matched"]] == [-3, -3]
    assert out["quantity_gap"] == {"differs": 2}


# ── 창 ──────────────────────────────────────────────────────────────────
def test_outside_the_window_splits_into_missed_and_off_rule():
    actual = [row("09:09:00", "buy", 10, 10_090), row("09:10:00", "sell", 10, 10_100)]   # 매수가 7분 늦었다
    out = compare(actual)
    assert out["counts"] == {"matched": 1, "sim_only": 1, "actual_only": 1}
    assert out["sim_only"][0]["side"] == "buy" and out["sim_only"][0]["at"] == f"{DAY}T09:02:00"
    assert out["actual_only"][0]["side"] == "buy" and out["actual_only"][0]["at"] == f"{DAY}T09:09:00"
    wide = compare(actual, window_minutes=15)
    assert wide["counts"] == {"matched": 2, "sim_only": 0, "actual_only": 0} and wide["window_minutes"] == 15


def test_the_three_windows_are_always_reported_together():
    out = compare([row("09:09:00", "buy", 10, 10_090), row("09:10:00", "sell", 10, 10_100)], window_minutes=3)
    assert out["by_window"] == [
        {"minutes": 1, "matched": 1, "sim_only": 1, "actual_only": 1, "chosen": False},
        {"minutes": 3, "matched": 1, "sim_only": 1, "actual_only": 1, "chosen": True},
        {"minutes": 5, "matched": 1, "sim_only": 1, "actual_only": 1, "chosen": False},
        {"minutes": 15, "matched": 2, "sim_only": 0, "actual_only": 0, "chosen": False},
    ]


def test_exactly_at_the_window_edge_is_a_pair_and_one_minute_past_is_not():
    edge = compare([row("09:07:59", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100)])      # 09:07 − 09:02 = 5분
    assert edge["counts"]["matched"] == 2
    past = compare([row("09:08:00", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100)])      # 6분
    assert past["counts"] == {"matched": 1, "sim_only": 1, "actual_only": 1}


def test_an_earlier_actual_fill_can_pair_too():
    out = compare([row("09:00:30", "buy", 10, 10_040), row("09:10:00", "sell", 10, 10_100)])
    assert out["matched"][0]["minutes"] == -2 and out["counts"]["matched"] == 2
    assert out["time_gap"] == {"mean_minutes": 1.0, "median_minutes": 1.0, "max_minutes": 2}   # 이른 것도 떨어진 만큼이다(부호를 상쇄하지 않는다)


def test_the_nearest_pair_wins_not_the_first_signal():
    sim = [{**SIM[0], "executed_at": f"{DAY} 09:01:00"}, {**SIM[0], "executed_at": f"{DAY} 09:05:00"}]
    out = compare([row("09:05:10", "buy", 10, 10_050)], sim=sim)
    assert out["counts"] == {"matched": 1, "sim_only": 1, "actual_only": 0}
    assert out["matched"][0]["sim_at"] == f"{DAY}T09:05:00"                               # 09:01 이 남의 짝을 가져가지 않는다
    assert out["sim_only"][0]["at"] == f"{DAY}T09:01:00"


# ── 짝이 아닌 것 ────────────────────────────────────────────────────────
def test_side_symbol_and_date_must_agree():
    out = compare([row("09:02:00", "sell", 10, 10_050),                                   # 방향이 다르다
                   row("09:10:00", "sell", 10, 10_100, day="2026-03-03")],                # 날이 다르다
                  end="2026-03-03")
    assert out["counts"] == {"matched": 0, "sim_only": 2, "actual_only": 2}


def test_no_pairs_means_no_gap_value_with_a_reason_not_zero():
    out = compare([row("10:30:00", "buy", 10, 10_050)])
    assert out["counts"]["matched"] == 0
    assert out["price_gap"] == {"n": 0, "reason": "no_pairs", "message": dv.REASONS["no_pairs"]}
    assert out["time_gap"] is None


def test_other_symbols_are_set_aside_and_counted():
    out = compare([row("09:02:00", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100),
                   row("09:02:00", "buy", 5, 80_000, symbol="000660")])
    assert out["counts"] == {"matched": 2, "sim_only": 0, "actual_only": 0}
    assert out["set_aside"]["other_symbols"] == {"rows": 1, "symbols": ["000660"]}


def test_rows_outside_the_period_are_counted_and_not_compared():
    out = compare([row("09:02:00", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100),
                   row("09:02:00", "buy", 10, 10_050, day="2026-02-27"), row("09:02:00", "buy", 10, 10_050, day="2026-03-03")])
    assert out["set_aside"]["outside_period"] == 2 and out["counts"]["actual_only"] == 0


def test_unreadable_rows_keep_their_reason():
    out = compare([row("09:02:00", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100),
                   {"executed_at": "언제였더라", "symbol": "005930", "side": "buy", "quantity": 1, "price": 1},
                   {"executed_at": f"{DAY} 09:20:00", "symbol": "005930", "side": "buy", "quantity": 0, "price": 10_000}])
    assert [(r["row"], r["reason"]) for r in out["set_aside"]["rejected"]] == [(2, "bad_datetime"), (3, "bad_quantity")]
    assert out["counts"]["matched"] == 2 and out["inputs"]["actual_rows"] == 4


# ── 시각이 없는 줄 ──────────────────────────────────────────────────────
def test_a_file_without_times_degrades_to_one_comparison_per_day():
    out = compare([row("", "buy", 4, 10_060), row("", "buy", 6, 10_070), row("", "sell", 10, 10_090)])
    assert out["mode"] == "daily" and out["degraded"] == {"reason": "no_times", "message": dv.REASONS["no_times"]}
    assert out["counts"] == {"matched": 2, "sim_only": 0, "actual_only": 0}
    buy, sell = out["matched"]
    assert buy["actual_at"] == DAY and buy["sim_at"] == DAY and buy["minutes"] is None
    assert buy["actual_price"] == pytest.approx(10_066.0) and buy["adverse"] == pytest.approx(16.0)
    assert sell["adverse"] == 10.0
    assert out["time_gap"] is None and out["by_window"] == []                              # 창은 시각이 있어야 뜻이 있다


def test_a_daily_comparison_lumps_the_simulated_side_too():
    sim = SIM + [{**SIM[0], "executed_at": f"{DAY} 13:00:00", "price": 10_150.0},
                 {**SIM[1], "executed_at": f"{DAY} 13:30:00", "price": 10_200.0}]
    out = compare([row("", "buy", 20, 10_100), row("", "sell", 20, 10_150)], sim=sim)
    buy = out["matched"][0]
    assert buy["sim_quantity"] == 20 and buy["sim_price"] == pytest.approx(10_100.0) and buy["adverse"] == 0.0
    assert out["matched"][1]["sim_price"] == pytest.approx(10_150.0)


def test_mixed_files_compare_the_timed_rows_and_count_the_rest():
    out = compare([row("09:02:00", "buy", 10, 10_050), row("09:10:00", "sell", 10, 10_100), row("", "buy", 3, 10_000)])
    assert out["mode"] == "timed" and out["degraded"] is None
    assert out["counts"] == {"matched": 2, "sim_only": 0, "actual_only": 0}
    assert out["set_aside"]["untimed"] == 1


# ── 입력 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [0, 61, -1, 2.5, True, "5", None])
def test_a_window_that_is_not_a_whole_number_of_minutes_in_range_is_refused(bad):
    with pytest.raises(dv.DivergenceError) as err:
        compare([row("09:02:00", "buy", 10, 10_050)], window_minutes=bad)
    assert err.value.code == "bad_window"


def test_a_malformed_simulated_row_is_a_bug_and_is_not_swallowed():
    with pytest.raises(ValueError):
        compare([row("09:02:00", "buy", 10, 10_050)], sim=[{"executed_at": "?", "symbol": "005930", "side": "buy"}])


def test_nothing_to_compare_on_either_side_is_still_an_answer():
    out = compare([row("09:02:00", "buy", 10, 10_050, symbol="000660")], sim=[])
    assert out["counts"] == {"matched": 0, "sim_only": 0, "actual_only": 0}
    assert out["price_gap"]["reason"] == "no_pairs" and out["set_aside"]["other_symbols"]["rows"] == 1


def test_lists_are_in_time_order():
    sim = [{**SIM[0], "executed_at": f"{DAY} 11:00:00"}, {**SIM[0], "executed_at": f"{DAY} 09:30:00"}]
    out = compare([row("14:00:00", "sell", 1, 10_000), row("13:00:00", "buy", 1, 10_000)], sim=sim)
    assert [r["at"] for r in out["sim_only"]] == [f"{DAY}T09:30:00", f"{DAY}T11:00:00"]
    assert [r["at"] for r in out["actual_only"]] == [f"{DAY}T13:00:00", f"{DAY}T14:00:00"]


# ── 손익 견주기 ─────────────────────────────────────────────────────────
def _journal(gross: float | None, net: float | None, n: int) -> dict:
    return {"summary": {"gross": {"total": gross, "n": n}, "net": None if net is None else {"total": net, "n": n},
                        "net_excluded": 0 if net is not None else n}}


def test_pnl_gap_is_actual_minus_simulated_for_both_bases():
    out = dv.pnl_gap(_journal(500.0, 300.0, 1), _journal(200.0, -50.0, 1))
    assert out["simulated"] == {"gross": 500.0, "net": 300.0, "trades": 1}
    assert out["actual"] == {"gross": 200.0, "net": -50.0, "trades": 1}
    assert out["gap"] == {"gross": -300.0, "net": -350.0} and out["net_reason"] is None


def test_an_unknown_cost_on_either_side_leaves_the_net_gap_unknown_not_zero():
    out = dv.pnl_gap(_journal(500.0, None, 1), _journal(200.0, -50.0, 1))
    assert out["gap"] == {"gross": -300.0, "net": None}
    assert out["net_reason"] == "cost_unknown" and out["net_message"] == dv.REASONS["cost_unknown"]
    other = dv.pnl_gap(_journal(500.0, 300.0, 1), _journal(200.0, None, 1))
    assert other["gap"]["net"] is None and other["net_reason"] == "cost_unknown"


def test_a_partly_known_net_total_is_not_comparable_either():
    partial = {"summary": {"gross": {"total": 200.0, "n": 2}, "net": {"total": 90.0, "n": 1}, "net_excluded": 1}}
    out = dv.pnl_gap(_journal(500.0, 300.0, 1), partial)
    assert out["actual"]["net"] is None and out["gap"]["net"] is None and out["net_reason"] == "cost_unknown"


def test_rows_in_scope_are_the_readable_rows_of_the_rules_tickers_inside_the_period():
    rows = [row("09:02:00", "buy", 10, 10_050), row("", "sell", 10, 10_100),                 # 시각이 없어도 손익에는 든다
            row("09:02:00", "buy", 5, 80_000, symbol="000660"), row("09:02:00", "buy", 1, 10_000, day="2026-02-27"),
            {"executed_at": "?", "symbol": "005930", "side": "buy", "quantity": 1, "price": 1}]
    got = dv.rows_in_scope(rows, ["005930"], DAY, DAY)
    assert got == rows[:2] and got[0] is rows[0]                                             # 받은 줄 그대로 · 받은 순서


# ── 문장은 관측만 한다 (설계 §4.3 · §8 — 도구는 규칙을 추천하지 않는다) ──────────────

ADVICE = ("추천", "권장", "권합", "권고", "바람직", "십시오")


def _advice_in(text: str) -> list[str]:
    return [w for w in ADVICE if w in text]


def test_every_sentence_the_engine_can_say_only_observes():
    said = list(dv.REASONS.values())
    said.append(compare([row("", "buy", 10, 10_050)])["degraded"]["message"])                   # 시각 없는 파일
    said.append(compare([])["price_gap"]["message"])                                           # 짝 없음
    said.append(dv.pnl_gap(_journal(1.0, None, 1), _journal(1.0, 1.0, 1))["net_message"])      # 비용 미상
    assert len(said) == len(dv.REASONS) + 3 and all(isinstance(m, str) and m for m in said)
    assert [m for m in said if _advice_in(m)] == []


def test_the_advice_check_catches_a_recommendation():
    assert _advice_in("슬리피지 가정을 2틱으로 올리십시오.") == ["십시오"]
    assert _advice_in("이 규칙을 추천합니다.") == ["추천"]
