"""논지 → 신호 → 백테스트 (P3-1 커밋 ①)

로드맵 P3-1: "kill 조건이 `buy/sell_conditions` 로 들어간다. **새 다리를 놓지 않고
있는 다리에 올린다.**" 다리는 이미 있다 —
`screener_routes._screen_to_backtest_core` 가 `sell_conditions` 와
`allow_snapshot_fundamentals` 를 받아 `run_backtest` 로 넘긴다. 이 모듈은
**실행 경로를 새로 짓지 않고** 논지를 그 입력으로 바꾼다.

★실측이 정한 것 — 돌릴 수는 있으나 대개 퇴화한다★
`005930` · 2024-01-01~06-30 · 130봉:

    kill 조건            opt-in off     opt-in on
    ROE ≤ 8 (거짓)        0 / 130       0 / 130
    ROE ≤ 25 (참)         0 / 130     130 / 130

좌하단이 함정이다 — opt-in 이 꺼져 있으면 백테스트가 **깨끗한 결과를 돌려주지만
kill 조건을 한 번도 평가하지 않았다.** 그래서 tier 2 가 하나라도 있으면 자동으로
켜고 크게 라벨한다.

★그런데 켜도 퇴화한다★ 스냅샷 상수는 창 전체에서 항상 참이거나 항상 거짓이다
(130/130 이 그 증거). `_precompute_ticker` 가 매도를 우선시키므로(`codes[sell_hit]=2`)
결과는 **거래 0건**(항상 참) 또는 **순수 바이앤홀드**(항상 거짓) 둘 중 하나다.
어느 쪽도 논지를 검증하지 않는다. 그러므로 이 모듈의 산출물은 "돌렸다" 가 아니라
**"돌렸고, 이 실행이 퇴화했는지 말한다"** 이다.
"""
from __future__ import annotations

from typing import Any

from src.engine.company_thesis import (
    OPT_IN_FLAG,
    TIER_LOOKAHEAD,
    thesis_to_sell_conditions,
)

# ★진입 규칙★ 논지에는 kill(매도) 조건만 있다. 매수 조건이 0개면
# `buy_hit = any_valid & all_ok` 가 항상 False 라 한 번도 진입하지 않는다
# (`condition_strategy.py:650`). 논지의 의미 — "이 주장 때문에 보유하고 kill
# 조건에서 정리한다" — 에 맞는 진입은 **첫 봉 진입 후 보유**다.
# `BASE_TOKENS` 의 `종가` 로 항상 참인 조건을 만든다. ★새 토큰 0★
ENTRY_TOKEN = "종가"
ENTRY_CONDITION: dict[str, Any] = {
    "factor_token": ENTRY_TOKEN, "function_id": "base", "op": "gte", "rhs": 0,
}
ENTRY_NOTE = ("논지에는 매도(kill) 조건만 있어 진입 규칙을 붙였습니다 — "
              "첫 봉 진입 후 kill 조건까지 보유합니다")

# 스크리너를 그대로 통과시키는 빈 필터. `is_empty()==True`·`validate()==None` 이고
# `custom_tickers` 가 유니버스를 정하므로 필터를 지어낼 필요가 없다(실측).
EMPTY_FILTER_AST: dict[str, Any] = {"logic": "AND", "conditions": [], "groups": []}

# 퇴화 종류 — 둘 다 "논지가 검증되지 않았다" 는 같은 결론에 이른다.
DEGENERATE_NO_ENTRY = "no_entry"
DEGENERATE_NEVER_EXITS = "never_exits"

# `overrides` 로 덮어쓸 수 있는 것 — 유니버스 인자는 받지 않는다(단일 종목 계약).
_OVERRIDABLE = frozenset({
    "initial_capital", "commission_rate", "slippage_rate",
    "stop_loss_pct", "take_profit_pct", "trailing_stop_pct",
    "buy_fill_type", "sell_fill_type", "signal_lag", "liquidate_at_end",
})


def build_backtest_request(thesis: dict, *, code: str, start_date: str,
                           end_date: str, **overrides: Any) -> dict:
    """논지 → `ScreenToBacktestRequest` 페이로드.

    ★산수를 여기에 짓지 않는다★ 조건 변환은 P2-5 의 `thesis_to_sell_conditions`
    가 하고, 실행은 있는 다리가 한다. 이 함수는 **배선**만 한다.
    """
    lifted = thesis_to_sell_conditions(thesis, code=code)
    sell = lifted["conditions"]
    if not sell:
        # ★돌리지도 기록하지도 않는다★ 올릴 조건이 없는 실행은 논지의 백테스트가
        # 아니라 그냥 바이앤홀드다 — 그것을 논지 검증이라 부르면 거짓이다.
        return {"available": False,
                "reason": lifted["reason"] or "백테스트에 올릴 kill 조건이 없습니다",
                "lift": lifted, "request": None}

    bad = sorted(set(overrides) - _OVERRIDABLE)
    if bad:
        return {"available": False,
                "reason": f"덮어쓸 수 없는 설정입니다: {', '.join(bad)}",
                "lift": lifted, "request": None}

    # ★자동으로 켜고 크게 라벨한다★ 끄면 조건이 조용히 무시된다(실측 0/130) —
    # 사용자가 논지를 검증했다고 믿게 되는 것이 가장 나쁜 결과다.
    lookahead = bool(lifted["lookahead"])
    request: dict[str, Any] = {
        "custom_tickers": [str(code)],
        "filter_ast": dict(EMPTY_FILTER_AST),
        "strategy_name": "Condition",
        "buy_conditions": [dict(ENTRY_CONDITION)],
        "sell_conditions": sell,
        OPT_IN_FLAG: lookahead,
        "start_date": start_date,
        "end_date": end_date,
        "max_tickers": 1,
        "max_positions": 1,
    }
    request.update(overrides)

    return {
        "available": True,
        "reason": None,
        "request": request,
        "lift": lifted,
        "code": str(code),
        "entry": {"condition": dict(ENTRY_CONDITION), "note": ENTRY_NOTE},
        "lookahead": lookahead,
        "auto_enabled_opt_in": lookahead,
        "lookahead_reason": (
            f"kill 조건 중 {lifted['counts'][TIER_LOOKAHEAD]}건이 스냅샷 상수라 "
            f"{OPT_IN_FLAG} 를 자동으로 켰습니다 — 켜지 않으면 그 조건이 조용히 "
            "무시되고, 켜면 look-ahead 근사입니다") if lookahead else None,
    }


def _load_bars(code: str, start_date: str, end_date: str):
    from src.data.ohlcv_loader import load_ohlcv_unified
    return load_ohlcv_unified(str(code), start_date, end_date, prefer="auto")


def diagnose_signals(conditions: list[dict], *, code: str, start_date: str,
                     end_date: str, allow_snapshot: bool,
                     entry: list[dict] | None = None) -> dict:
    """★라벨을 측정으로 바꾼다★ 신호를 **실제로** 태워 퇴화 여부를 판정한다.

    "look-ahead 근사입니다" 는 말이고, `sell_bars == total_bars` 는 증거다.
    스냅샷 상수는 창 전체에서 값이 변하지 않으므로 kill 조건이 항상 참이거나 항상
    거짓이 된다. 전자는 진입 자체가 없고(매도 우선), 후자는 순수 바이앤홀드다 —
    **어느 쪽도 논지를 검증하지 않는다.**
    """
    entry = [dict(ENTRY_CONDITION)] if entry is None else entry
    try:
        df = _load_bars(code, start_date, end_date)
    except Exception as e:  # noqa: BLE001
        return {"available": False,
                "reason": f"시세를 불러오지 못했습니다: {type(e).__name__}"}
    if df is None or len(df) == 0:
        return {"available": False, "reason": "이 기간의 시세가 없습니다"}

    total = int(len(df))
    try:
        from src.kis_strategies.condition_strategy import ConditionStrategy
        strat = ConditionStrategy(buy_conditions=entry, sell_conditions=conditions,
                                  allow_snapshot_fundamentals=bool(allow_snapshot))
        strat.precompute_signals({str(code): df.copy()})
        series = strat._sig.get(str(code))
    except Exception as e:  # noqa: BLE001
        return {"available": False,
                "reason": f"신호를 평가하지 못했습니다: {type(e).__name__}"}
    if series is None:
        return {"available": False, "total_bars": total,
                "reason": "이 종목의 신호가 사전계산되지 않았습니다"}

    # 1=BUY · 2=SELL (`_precompute_ticker` — 매도 우선). 이름을 손으로 세지 않는다.
    buy_bars = int((series == 1).sum())
    sell_bars = int((series == 2).sum())

    rows = []
    for c in conditions:
        rows.append(_diagnose_one(c, df, code, allow_snapshot, entry, total))

    if sell_bars == total:
        degenerate, reason = DEGENERATE_NO_ENTRY, (
            "kill 조건이 전 구간에서 참이라 한 번도 진입하지 않았습니다 — "
            "거래 0건은 '손실 없음' 이 아니라 '논지가 검증되지 않음' 입니다")
    elif sell_bars == 0:
        degenerate, reason = DEGENERATE_NEVER_EXITS, (
            "kill 조건이 전 구간에서 거짓이라 한 번도 청산하지 않았습니다 — "
            "결과는 순수 바이앤홀드이고 논지는 검증되지 않았습니다")
    else:
        degenerate, reason = None, None

    return {
        "available": True,
        "total_bars": total, "buy_bars": buy_bars, "sell_bars": sell_bars,
        "rows": rows,
        "degenerate": degenerate,
        "reason": reason,
        "allow_snapshot_fundamentals": bool(allow_snapshot),
        "note": ("스냅샷 상수 조건은 창 전체에서 값이 변하지 않아 항상 참이거나 "
                 "항상 거짓이 됩니다 — 그것이 look-ahead 의 관측 가능한 형태입니다"),
    }


def _diagnose_one(cond: dict, df, code: str, allow_snapshot: bool,
                  entry: list[dict], total: int) -> dict:
    """조건 하나만 태워 그 조건이 창 전체에서 상수인지 본다."""
    row: dict[str, Any] = {"condition": cond,
                           "factor_token": cond.get("factor_token"),
                           "lookahead": bool(cond.get("lookahead"))}
    try:
        from src.kis_strategies.condition_strategy import ConditionStrategy
        one = ConditionStrategy(buy_conditions=entry, sell_conditions=[cond],
                                allow_snapshot_fundamentals=bool(allow_snapshot))
        one.precompute_signals({str(code): df.copy()})
        ser = one._sig.get(str(code))
    except Exception as e:  # noqa: BLE001
        row.update(available=False,
                   reason=f"이 조건을 평가하지 못했습니다: {type(e).__name__}")
        return row
    if ser is None:
        row.update(available=False, reason="이 조건의 신호가 사전계산되지 않았습니다")
        return row

    hits = int((ser == 2).sum())
    row.update(available=True, sell_bars=hits, total_bars=total,
               # ★상수면 look-ahead 가 관측된 것이다★ 전 봉 참이거나 전 봉 거짓.
               constant_over_window=(hits == total or hits == 0),
               always_true=(hits == total), always_false=(hits == 0))
    if not row["constant_over_window"]:
        row["reason"] = None
    elif hits == total:
        row["reason"] = "이 조건은 전 구간에서 참입니다 — 진입을 막습니다"
    else:
        row["reason"] = "이 조건은 전 구간에서 거짓입니다 — 한 번도 발동하지 않습니다"
    return row
