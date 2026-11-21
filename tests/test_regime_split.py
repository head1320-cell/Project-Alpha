"""국면별 성과 나눔 — 순수 함수 `src.engine.regime_split.split_by_regime` (구현 계획 §7.3 · K2a).

거는 것: 손 계산 열흘(국면 둘 + 날이 없는 국면 · 확률이 없는 날 · 지수에 없는 날 · 확률 0.5 미만 · 거래 없는 날) ·
손익 · 거래 · 이긴 거래의 합계가 맞는다(국면들 + 미상 = 시행 전체 — 무작위 흐름 200개) · 거래 0 인 국면의 승률은 0% 가 아니라 `None` ·
거래 수를 남기지 않은 옛 시행 줄은 거래 · 승률이 미상 + 사유 ↔ 짝: 남긴 줄은 값 · 0.5 는 '미만'이 아니다 · 전환은 국면이 있는 날끼리만 ·
흐름의 날 수가 맞지 않으면 지어내지 않고 거절한다. 미상 묶음 · 합계 줄도 승률을 갖고(같은 규칙 — 거래 0 이면 없음) 합계의 '0.5 미만' 은 국면들의 합이다
(미상 묶음은 확률이 없어 세지 않는다) — 화면은 숫자를 셈하지 않고 이 값을 그대로 쓴다.
"""
from __future__ import annotations

import random

import pytest

from src.engine import regime_split as rs

DATES = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
         "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"]
VALUES = [100.0, -50.0, 0.0, 200.0, -100.0, 30.0, 0.0, 70.0, -20.0, 10.0]
TRADES = [2, 1, 0, 3, 1, 1, 0, 2, 1, 1]
WINS = [1, 0, 0, 2, 0, 1, 0, 1, 0, 1]
NOT_FULL = "적합 창이 덜 찼습니다(필요 750 · 있음 700)."     # 국면 엔진이 그날에 붙인 사유(그대로 싣는다)


def regime_rows() -> list[dict]:
    """국면 3개 가운데 1 · 2 만 나온 열흘 — 2026-03-06 은 확률이 없고(사유) · 2026-03-10 은 지수 자료에 없다."""
    probs = {
        "2026-03-02": [0.7, 0.2, 0.1],     # 1
        "2026-03-03": [0.4, 0.35, 0.25],   # 1 · 0.5 미만
        "2026-03-04": [0.1, 0.8, 0.1],     # 2
        "2026-03-05": [0.2, 0.45, 0.35],   # 2 · 0.5 미만
        "2026-03-09": [0.6, 0.3, 0.1],     # 1
        "2026-03-11": [0.3, 0.6, 0.1],     # 2
        "2026-03-12": [0.9, 0.05, 0.05],   # 1
        "2026-03-13": [0.2, 0.7, 0.1],     # 2
    }
    rows = []
    for d in DATES:
        if d == "2026-03-10":
            continue                                                      # 지수에 없는 날
        if d == "2026-03-06":
            rows.append({"date": d, "probs": None, "top": None, "top_prob": None, "reason": NOT_FULL})
            continue
        p = probs[d]
        top = max(range(3), key=lambda i: p[i])
        rows.append({"date": d, "probs": p, "top": top + 1, "top_prob": p[top], "reason": None})
    return rows


def daily(with_counts: bool = True) -> dict:
    out = {"basis": "net", "dates": list(DATES), "values": list(VALUES)}
    if with_counts:
        out.update(trades=list(TRADES), wins=list(WINS))
    return out


def test_ten_days_by_hand():
    out = rs.split_by_regime(daily(), regime_rows(), k=3)
    s1, s2, s3 = out["states"]
    # 국면 1: 3/02 · 3/03(0.5 미만) · 3/09 · 3/12
    assert s1 == {"state": 1, "days": 4, "low_conf_days": 1, "trades": 5, "wins": 2, "win_rate": pytest.approx(0.4), "pnl": 60.0}
    # 국면 2: 3/04(거래 없음) · 3/05(0.5 미만) · 3/11 · 3/13
    assert s2 == {"state": 2, "days": 4, "low_conf_days": 1, "trades": 6, "wins": 4, "win_rate": pytest.approx(4 / 6), "pnl": 280.0}
    # 국면 3: 날이 없다 — 승률은 0% 가 아니라 없음
    assert s3 == {"state": 3, "days": 0, "low_conf_days": 0, "trades": 0, "wins": 0, "win_rate": None, "pnl": 0.0}
    # 미상: 3/06(확률 없음 · 거래 1 · 진 거래) · 3/10(지수에 없음 · 거래 없음) — 승률은 0/1 = 0% (거래가 있으니 없음이 아니다)
    assert out["unknown"] == {"days": 2, "trades": 1, "wins": 0, "win_rate": 0.0, "pnl": -100.0,
                              "reasons": [{"reason": NOT_FULL, "days": 1}, {"reason": rs.REASONS["no_index_day"], "days": 1}]}
    # 합계: 0.5 미만은 국면들의 합(1 + 1 + 0) · 승률 6/12
    assert out["total"] == {"days": 10, "low_conf_days": 2, "trades": 12, "wins": 6, "win_rate": pytest.approx(0.5), "pnl": 240.0}
    assert out["transitions"] == 5                                        # 국면이 있는 날끼리: 1 1 2 2 1 2 1 2
    assert (out["basis"], out["trades_known"], out["trades_reason"]) == ("net", True, None)


def test_an_old_record_without_trade_counts_leaves_trades_unknown_not_zero():
    """K2 앞의 시행 줄에는 날마다의 거래 수가 없다 — 0 으로 채우지 않는다(미상 + 사유) ↔ 짝: 남긴 줄은 값."""
    out = rs.split_by_regime(daily(with_counts=False), regime_rows(), k=3)
    assert out["trades_known"] is False and out["trades_reason"] == rs.REASONS["no_trade_counts"]
    for row in [*out["states"], out["unknown"], out["total"]]:
        assert row["trades"] is None and row["wins"] is None and row["win_rate"] is None
    assert out["total"]["low_conf_days"] == 2                            # 확률은 거래 수와 무관하게 센다
    assert [s["days"] for s in out["states"]] == [4, 4, 0] and [s["pnl"] for s in out["states"]] == [60.0, 280.0, 0.0]
    assert out["total"]["pnl"] == 240.0                                   # 손익 · 날 수는 그대로 나뉜다


def test_a_regime_with_days_but_no_trades_has_no_win_rate():
    rows = [{"date": d, "probs": [0.9, 0.1], "top": 1, "top_prob": 0.9, "reason": None} for d in DATES[:3]]
    flow = {"basis": "gross", "dates": DATES[:3], "values": [0.0, 0.0, 0.0], "trades": [0, 0, 0], "wins": [0, 0, 0]}
    out = rs.split_by_regime(flow, rows, k=2)
    s1 = out["states"][0]
    assert (s1["days"], s1["trades"], s1["win_rate"]) == (3, 0, None)
    assert (out["total"]["trades"], out["total"]["win_rate"]) == (0, None)   # 합계도 같은 규칙


def test_unknown_days_without_trades_have_no_win_rate_but_with_trades_they_do():
    """미상 묶음의 승률 — 거래가 0 이면 없음(0% 가 아니다) ↔ 짝: 거래가 있으면 이긴 거래 ÷ 거래."""
    flow = {"basis": "net", "dates": DATES[:2], "values": [5.0, -5.0], "trades": [0, 0], "wins": [0, 0]}
    assert rs.split_by_regime(flow, [], k=2)["unknown"]["win_rate"] is None
    flow.update(trades=[2, 2], wins=[1, 2])
    unknown = rs.split_by_regime(flow, [], k=2)["unknown"]
    assert (unknown["days"], unknown["trades"], unknown["wins"], unknown["win_rate"]) == (2, 4, 3, pytest.approx(0.75))


@pytest.mark.parametrize("top_prob, low", [(0.5, 0), (0.49, 1)])
def test_half_is_not_below_half(top_prob, low):
    p = [top_prob, (1 - top_prob) * 0.6, (1 - top_prob) * 0.4]
    rows = [{"date": DATES[0], "probs": p, "top": 1, "top_prob": top_prob, "reason": None}]
    flow = {"basis": "net", "dates": DATES[:1], "values": [1.0], "trades": [1], "wins": [1]}
    assert rs.split_by_regime(flow, rows, k=3)["states"][0]["low_conf_days"] == low


def test_dates_are_aligned_like_the_recorded_flow():
    """시행 줄의 값은 `sorted(set(dates))` 순서다(`validation.daily_values`) — 같은 규칙으로 맞춘다."""
    flow = daily()
    flow["dates"] = list(reversed(DATES)) + [DATES[0]]                    # 순서가 섞이고 겹쳐도 값의 순서는 정렬된 날
    assert rs.split_by_regime(flow, regime_rows(), k=3) == rs.split_by_regime(daily(), regime_rows(), k=3)


@pytest.mark.parametrize("cut", ["values", "trades", "wins"])
def test_a_flow_whose_lengths_do_not_match_is_refused_not_guessed(cut):
    flow = daily()
    flow[cut] = flow[cut][:-1]
    with pytest.raises(ValueError, match="flow_mismatch"):
        rs.split_by_regime(flow, regime_rows(), k=3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_flow_with_a_non_finite_value_is_refused_not_summed(bad):
    """NaN · 무한대가 섞인 흐름을 더하면 합계가 그 값이 되고 답이 JSON 으로 나가지 못한다 — 더하지 않고 거절한다."""
    flow = daily()
    flow["values"][3] = bad
    with pytest.raises(ValueError, match="non_finite"):
        rs.split_by_regime(flow, regime_rows(), k=3)


def test_a_regime_row_outside_k_is_refused():
    rows = regime_rows()
    rows[0] = {**rows[0], "top": 4}
    with pytest.raises(ValueError, match="state_out_of_range"):
        rs.split_by_regime(daily(), rows, k=3)


def test_the_parts_always_add_up_to_the_whole():
    """국면들 + 미상 = 시행 전체(손익 · 거래 · 이긴 거래 · 날 수) — 무작위 흐름 200개."""
    rng = random.Random(11)
    for _ in range(200):
        n, k = rng.randint(1, 30), rng.randint(2, 4)
        dates = [f"2026-04-{i + 1:02d}" for i in range(n)]
        trades = [rng.randint(0, 4) for _ in range(n)]
        flow = {"basis": "net", "dates": dates, "values": [round(rng.uniform(-500, 500), 2) for _ in range(n)],
                "trades": trades, "wins": [rng.randint(0, t) for t in trades]}
        rows = []
        for d in dates:
            roll = rng.random()
            if roll < 0.1:
                continue                                                  # 지수에 없는 날
            if roll < 0.2:
                rows.append({"date": d, "probs": None, "top": None, "top_prob": None, "reason": "사유"})
                continue
            raw = [rng.random() for _ in range(k)]
            p = [x / sum(raw) for x in raw]
            top = max(range(k), key=lambda i: p[i])
            rows.append({"date": d, "probs": p, "top": top + 1, "top_prob": p[top], "reason": None})
        out = rs.split_by_regime(flow, rows, k=k)
        for key in ("days", "trades", "wins"):
            assert sum(s[key] for s in out["states"]) + out["unknown"][key] == out["total"][key] == (
                n if key == "days" else sum(flow[key]))
        assert sum(s["pnl"] for s in out["states"]) + out["unknown"]["pnl"] == pytest.approx(out["total"]["pnl"])
        assert sum(s["low_conf_days"] for s in out["states"]) == out["total"]["low_conf_days"]
        for row in [*out["states"], out["unknown"], out["total"]]:
            assert row["win_rate"] == (pytest.approx(row["wins"] / row["trades"]) if row["trades"] else None)
        assert out["total"]["pnl"] == pytest.approx(sum(flow["values"]))
        assert sum(r["days"] for r in out["unknown"]["reasons"]) == out["unknown"]["days"]
