"""국면별 성과 나눔 — 시행 줄의 일별 흐름을 그날의 시장 국면(가장 큰 확률)별로 나눈다 (구현 계획 §7.3 · K2a).

순수 함수다(읽기 · 쓰기 · 난수 없음). ★관측이며 결정에 쓰지 않는다★ — 국면 조건을 넣으면 나아진다는 뜻이 아니다.

- `daily`: 시행 줄의 흐름 `{basis, dates, values, trades?, wins?}`. 값의 순서는 `sorted(set(dates))`(`validation.daily_values` 와 같은 규칙).
  `trades` · `wins`(날마다의 거래 · 이긴 거래)는 K2 부터 남는다 — 없는 옛 줄은 거래 · 이긴 거래 · 승률이 미상 + 사유다(0 으로 채우지 않는다).
- `regime_days`: 시장 국면 엔진의 날 줄 `{date, probs, top, top_prob, reason}` — 그날 시가 전에 아는 값(전 거래일 종가까지)이다.
- 그날의 국면이 없거나(엔진의 사유 그대로) 지수 자료에 그날이 없으면 '국면 미상' 묶음이다. ★국면들 + 미상 = 시행 전체★(날 · 손익 · 거래 · 이긴 거래).
- 국면마다 가장 큰 확률이 0.5 미만이었던 날을 센다(그 국면이 근소하게 가장 컸던 날). 0.5 는 미만이 아니다.
- 승률 = 이긴 거래 ÷ 거래 — 거래가 0 이면 없음이다(0% 가 아니다). 국면마다 · 미상 묶음 · 합계 줄 모두 같은 규칙이다.
- 합계 줄의 '0.5 미만' 날 수는 국면들의 합이다(미상 묶음은 확률이 없어 세지 않는다). 화면은 숫자를 셈하지 않고 이 값들을 그대로 쓴다.
- 전환 = 시행의 거래일 가운데 국면이 있는 날끼리 가장 큰 국면이 바뀐 횟수.
- 흐름의 길이가 날 수와 맞지 않거나(`flow_mismatch`) 값에 NaN · 무한대가 있거나(`non_finite` — 더하면 합계가 그 값이 된다) 국면 번호가 1 ~ k 밖이면(`state_out_of_range`)
  지어내지 않고 `ValueError` 다.
"""
from __future__ import annotations

import math
from typing import Any

#: 가장 큰 확률이 이보다 ★작은★ 날을 국면마다 따로 센다.
LOW_CONF = 0.5

REASONS = {
    "no_index_day": "그날의 지수 일봉이 없어 국면을 알 수 없습니다.",
    "no_regime": "그날의 국면을 알 수 없습니다.",
    "no_trade_counts": "이 시행의 기록에는 날마다의 거래 수가 없습니다(국면별 나눔이 생기기 전의 실행). "
                       "같은 설정으로 다시 실행하면 남고 시행 수는 늘지 않습니다.",
}


def split_by_regime(daily: dict, regime_days: list[dict], k: int) -> dict[str, Any]:
    days = sorted(set(daily["dates"]))
    values = [float(v) for v in daily["values"]]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("non_finite")
    counted = daily.get("trades") is not None and daily.get("wins") is not None
    trades = [int(n) for n in daily["trades"]] if counted else None
    wins = [int(n) for n in daily["wins"]] if counted else None
    if len(values) != len(days) or (counted and (len(trades) != len(days) or len(wins) != len(days))):
        raise ValueError("flow_mismatch")

    def bucket() -> dict[str, Any]:
        return {"days": 0, "trades": 0 if counted else None, "wins": 0 if counted else None, "pnl": 0.0}

    states = [{"state": s, "low_conf_days": 0, **bucket()} for s in range(1, k + 1)]
    unknown, total = bucket(), bucket()
    reasons: dict[str, int] = {}
    tops: list[int] = []
    by_date = {r["date"]: r for r in regime_days}
    for i, d in enumerate(days):
        row = by_date.get(d)
        top = row.get("top") if row is not None else None
        if top is not None:
            if not 1 <= top <= k:
                raise ValueError("state_out_of_range")
            into = states[top - 1]
            if row["top_prob"] < LOW_CONF:
                into["low_conf_days"] += 1
            tops.append(top)
        else:
            into = unknown
            why = REASONS["no_index_day"] if row is None else (row.get("reason") or REASONS["no_regime"])
            reasons[why] = reasons.get(why, 0) + 1
        for b in (into, total):
            b["days"] += 1
            b["pnl"] += values[i]
            if counted:
                b["trades"] += trades[i]
                b["wins"] += wins[i]
    for b in (*states, unknown, total):
        b["win_rate"] = (b["wins"] / b["trades"]) if counted and b["trades"] else None
    total["low_conf_days"] = sum(s["low_conf_days"] for s in states)
    unknown["reasons"] = [{"reason": why, "days": n} for why, n in reasons.items()]
    return {"basis": daily.get("basis"), "states": states, "unknown": unknown, "total": total,
            "transitions": sum(1 for a, b in zip(tops, tops[1:]) if a != b),
            "trades_known": counted, "trades_reason": None if counted else REASONS["no_trade_counts"]}
