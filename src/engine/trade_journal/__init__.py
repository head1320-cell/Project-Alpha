"""매매일지 — 체결 내역을 넣으면 어디서 벌고 어디서 새는지. `analyze(rows, options)` 하나가 입구다.

설계: `docs/superpowers/specs/2026-11-14-trade-journal-design.md`.

★관측만 한다★ — 올린 파일 안에서 일어난 일의 집계다. 추천도 예측도 아니다. 저장하지 않는다(입출력이 없다 — 세율표 파일을 읽는 것뿐).
값마다 근거가 따라간다(`basis`): 비용이 파일의 값인지(관측) · 세율표로 산출했는지(추론) · 사용자가 넣은 요율인지(가정) · 모르는지(미상).
★미상은 0 이 아니다★ — 비용을 모르는 거래는 '비용 뒤' 통계에서 빠지고, 빠진 수를 적는다.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from datetime import timedelta

from src.engine.trade_journal.costs import (
    ASSUMED,
    INFERRED,
    NOT_APPLICABLE,
    OBSERVED,
    TAX_UNKNOWN_MESSAGES,
    UNKNOWN,
    CostOptions,
    FillCost,
    cost_of,
    master_flags_of,
)
from src.engine.trade_journal.fills import REJECT_REASONS, normalize
from src.engine.trade_journal.matching import Trade, match
from src.engine.trade_journal.metrics import (
    AFTER_LOSS_MINUTES,
    HOLDING_BUCKETS,
    WEEKDAYS,
    bucket_row,
    cumulative,
    holding_bucket,
    summarize,
)

#: 이 도구가 ★다루지 않는 것★ — 결과에 그대로 싣는다(없는 것을 있는 것처럼 읽지 않게).
NOT_COVERED: tuple[str, ...] = (
    "미청산 수량의 평가 손익(미실현 손익): 시세를 쓰지 않음",
    "수익률(%)·MDD(%): 계좌 평가금액 미상",
    "공매도·신용·대주 거래",
    "선물·옵션·해외 종목",
    "유관기관 제비용",
    "양도소득세·대주주 과세 등 세후 계산",
    "파일에 없는 체결: 이 파일이 계좌 전체인지는 확인하지 않음",
)

TRADES_LIMIT = 500          # 거래 표에 싣는 건수(청산 순으로 앞에서부터)
SAMPLE_LIMIT = 50           # 버린 줄 · 매수 없는 매도의 표본 건수
EXTREMES_LIMIT = 5          # 가장 큰 손실 · 이익 거래의 건수

UNMATCHED_SELL_MESSAGE = "이 매도에 맞출 매수 기록이 파일에 없습니다(파일 시작 전의 매수 또는 공매도). 손익을 계산하지 않았습니다."


def _prorated(trade: Trade, costs: dict[int, FillCost]) -> tuple[float | None, float | None]:
    """거래에서 ★맞춘 수량의 몫만큼★의 (수수료, 세금). 성분을 하나라도 모르면 그 성분은 `None`."""
    fees, taxes = 0.0, 0.0
    fee_unknown = tax_unknown = False
    for m in trade.matches:
        for f in (m.buy, m.sell):
            cost, share = costs[f.row], m.quantity / f.quantity
            if cost.fee is None:
                fee_unknown = True
            else:
                fees += cost.fee * share
            if cost.tax is None:
                tax_unknown = True
            else:
                taxes += cost.tax * share
    return (None if fee_unknown else fees), (None if tax_unknown else taxes)


def _trade_row(trade: Trade, fees: float | None, taxes: float | None, name: str | None) -> dict:
    gross = trade.realized_gross
    cost = None if fees is None or taxes is None else fees + taxes
    buy_qty, sell_qty = trade.buy_quantity, trade.sell_quantity
    return {
        "symbol": trade.symbol, "name": name,
        "opened_at": trade.opened_at.isoformat(), "closed_at": trade.closed_at.isoformat(),
        "has_time": trade.has_time, "holding_seconds": trade.holding_seconds, "same_day": trade.same_day,
        "quantity": buy_qty, "fills": len(trade.fills),
        "buy_amount": trade.buy_amount, "sell_amount": trade.sell_amount,
        "avg_buy": trade.buy_amount / buy_qty, "avg_sell": trade.sell_amount / sell_qty,
        "gross": gross, "fees": fees, "taxes": taxes, "cost": cost,
        "net": None if cost is None else gross - cost,
    }


def _after_loss(trades: list[Trade], pnls: list[float]) -> list[bool | None]:
    """거래마다 '손실로 끝난 다른 거래의 청산 뒤 `AFTER_LOSS_MINUTES` 분 안에 시작했는가'. 시각이 없으면 `None`."""
    window = timedelta(minutes=AFTER_LOSS_MINUTES)
    loss_closes = sorted(t.closed_at for t, p in zip(trades, pnls, strict=True) if p < 0 and t.has_time)
    out: list[bool | None] = []
    for t, p in zip(trades, pnls, strict=True):
        if not t.has_time:
            out.append(None)
            continue
        hits = bisect_right(loss_closes, t.opened_at) - bisect_left(loss_closes, t.opened_at - window)
        own = 1 if p < 0 and t.closed_at == t.opened_at else 0      # 자기 자신의 청산은 세지 않는다
        out.append(hits - own > 0)
    return out


def _basis_block(fills, costs: dict[int, FillCost], options: CostOptions, pnl_basis: str) -> dict:
    fee = {OBSERVED: 0, ASSUMED: 0, UNKNOWN: 0}
    tax = {OBSERVED: 0, INFERRED: 0, ASSUMED: 0, UNKNOWN: 0, NOT_APPLICABLE: 0}
    rates: dict[tuple, dict] = {}
    unknown_reasons: dict[str, dict] = {}
    for f in fills:
        c = costs[f.row]
        fee[c.fee_basis] += 1
        tax[c.tax_basis] += 1
        if c.tax_basis in (INFERRED, ASSUMED):
            r = c.tax_rate
            key = (r["market"], r["instrument"], r["period"]["from"], c.tax_basis)
            row = rates.setdefault(key, {"market": r["market"], "instrument": r["instrument"], "bp": r["bp"], "parts": r["parts"],
                                         "period": r["period"], "grade": r["grade"], "sources": r["sources"], "note": r["note"],
                                         "basis": c.tax_basis, "fills": 0})
            row["fills"] += 1
        elif c.tax_basis == UNKNOWN:
            # 세율표가 답하지 못한 것이면 세율표의 문장을, 시장을 몰라 묻지도 못한 것이면 이 모듈의 문장을 쓴다.
            message = c.tax_rate["message"] if c.tax_rate else TAX_UNKNOWN_MESSAGES[c.tax_reason]
            unknown_reasons.setdefault(c.tax_reason, {"reason": c.tax_reason, "count": 0, "message": message})["count"] += 1
    return {
        "pnl_basis": pnl_basis,
        "fee": fee, "tax": tax,
        "commission_bp": options.commission_bp,
        "unknown_market": options.unknown_market, "unknown_instrument": options.unknown_instrument,
        "tax_rates": [rates[k] for k in sorted(rates)],
        "tax_unknown": [unknown_reasons[r] for r in sorted(unknown_reasons)],
    }


def analyze(rows: list[dict], options: dict | None = None, *, master: Callable[[str], dict | None] | None = None) -> dict:
    """정규화한 체결 줄 → 매매일지. `options`: `commission_bp` · `unknown_market` · `unknown_instrument`(없으면 모름).

    `master` 는 종목 → 마스터 플래그(시장 · 그룹 코드 · 이름)를 주는 함수다 — 부르는 쪽이 넣는다(이 모듈은 저장소를 읽지 않는다).
    잘못된 옵션은 `ValueError` — 조용히 무시하지 않는다.
    """
    opts = options or {}
    cost_options = CostOptions(commission_bp=opts.get("commission_bp"), unknown_market=opts.get("unknown_market"),
                               unknown_instrument=opts.get("unknown_instrument"), master=master)
    fills, rejects = normalize(rows)
    matched = match(fills)
    costs = {f.row: cost_of(f, cost_options) for f in fills}

    def name_of(trade: Trade) -> str | None:
        name = trade.name or master_flags_of(trade.symbol, cost_options).get("name")
        return name if isinstance(name, str) and name.strip() else None

    closed = [t for t in matched.trades if t.closed]
    still_open = [t for t in matched.trades if not t.closed]
    records = [_trade_row(t, *_prorated(t, costs), name_of(t)) for t in closed]

    gross = [r["gross"] for r in records]
    net_known = [r["net"] for r in records if r["net"] is not None]
    excluded = len(records) - len(net_known)
    # 곡선·묶음의 기준 — 모든 거래의 비용을 알 때만 '비용 뒤'. 일부만 알면 섞지 않고 '비용 앞'으로 통일한다.
    pnl_basis = "net" if excluded == 0 else "gross"
    pnls = [r[pnl_basis] for r in records]

    # ── 비용 ──
    n = len(records)
    fees = None if any(r["fees"] is None for r in records) else sum(r["fees"] for r in records)
    taxes = None if any(r["taxes"] is None for r in records) else sum(r["taxes"] for r in records)
    cost_total = None if fees is None or taxes is None else fees + taxes
    gross_total = sum(gross) if gross else 0.0
    turnover = sum(r["buy_amount"] + r["sell_amount"] for r in records)
    if n == 0:
        share, share_reason = None, "no_trades"
    elif cost_total is None:
        share, share_reason = None, "cost_unknown"
    elif gross_total <= 0:
        share, share_reason = None, "gross_not_positive"
    else:
        share, share_reason = cost_total / gross_total, None
    cost_block = {
        "fees": fees, "taxes": taxes, "total": cost_total,
        "share_of_gross": share, "share_reason": share_reason,
        "turnover": turnover,
        "bp_of_turnover": cost_total / turnover * 10_000 if cost_total is not None and turnover > 0 else None,
        "per_trade": cost_total / n if cost_total is not None and n else None,
    }

    # ── 미청산 — 평가하지 않는다. 이미 판 몫의 실현 손익만 따로 적는다 ──
    open_rows = []
    for t in still_open:
        o_fees, o_taxes = _prorated(t, costs)
        o_cost = None if o_fees is None or o_taxes is None else o_fees + o_taxes
        realized = t.realized_gross
        open_rows.append({
            "symbol": t.symbol, "name": name_of(t), "opened_at": t.opened_at.isoformat(),
            "open_quantity": t.open_quantity, "buy_quantity": t.buy_quantity, "sold_quantity": t.sell_quantity,
            "open_amount": t.buy_amount - sum(m.quantity * m.buy.price for m in t.matches),
            "realized_gross": realized, "realized_cost": o_cost,
            "realized_net": None if o_cost is None else realized - o_cost,
        })
    open_realized = {
        "n": len(open_rows), "gross": sum(r["realized_gross"] for r in open_rows) if open_rows else 0.0,
        "net": None if any(r["realized_net"] is None for r in open_rows) else (sum(r["realized_net"] for r in open_rows) if open_rows else 0.0),
    }

    # ── 묶음 ──
    after_flags = _after_loss(closed, pnls)
    for r, flag in zip(records, after_flags, strict=True):
        r["after_loss"] = flag

    timed = [(t, p) for t, p in zip(closed, pnls, strict=True) if t.has_time]
    holding: dict[str, list[float]] = {key: [] for key, *_ in HOLDING_BUCKETS}
    hours: dict[int, list[float]] = {}
    for t, p in timed:
        holding[holding_bucket(t.holding_seconds, t.same_day)].append(p)
        hours.setdefault(t.opened_at.hour, []).append(p)
    weekdays: dict[int, list[float]] = {}
    days: dict[str, list[float]] = {}
    symbols: dict[str, list[dict]] = {}
    for t, r, p in zip(closed, records, pnls, strict=True):
        weekdays.setdefault(t.opened_at.weekday(), []).append(p)
        days.setdefault(t.closed_at.date().isoformat(), []).append(p)
        symbols.setdefault(t.symbol, []).append(r)

    def symbol_row(symbol: str, rs: list[dict]) -> dict:
        known = all(r["cost"] is not None for r in rs)
        return bucket_row(symbol, symbol, [r[pnl_basis] for r in rs], name=next((r["name"] for r in rs if r["name"]), None),
                          gross=sum(r["gross"] for r in rs), cost=sum(r["cost"] for r in rs) if known else None)

    breakdowns = {
        "basis": pnl_basis,
        "holding": [bucket_row(key, label, holding[key]) for key, label, *_ in HOLDING_BUCKETS],
        "hour": [bucket_row(h, f"{h}시", hours[h]) for h in sorted(hours)],
        "weekday": [bucket_row(d, WEEKDAYS[d], weekdays[d]) for d in sorted(weekdays)],
        "symbol": sorted((symbol_row(s, rs) for s, rs in symbols.items()), key=lambda r: (-r["total"], r["key"])),
        "daily": [bucket_row(d, d, days[d]) for d in sorted(days)],
        "after_loss": {
            "within_minutes": AFTER_LOSS_MINUTES,
            "after": bucket_row("after", f"손실 뒤 {AFTER_LOSS_MINUTES}분 안", [p for p, f in zip(pnls, after_flags, strict=True) if f is True]),
            "other": bucket_row("other", "그 밖", [p for p, f in zip(pnls, after_flags, strict=True) if f is False]),
        },
        "without_time": len(closed) - len(timed),
    }

    curve = cumulative([(t.closed_at, p) for t, p in zip(closed, pnls, strict=True)])
    losers = sorted((r for r in records if r[pnl_basis] < 0), key=lambda r: r[pnl_basis])
    winners = sorted((r for r in records if r[pnl_basis] > 0), key=lambda r: -r[pnl_basis])

    by_reason: dict[str, dict] = {}
    for r in rejects:
        by_reason.setdefault(r["reason"], {"count": 0, "message": REJECT_REASONS[r["reason"]]})["count"] += 1

    return {
        "inputs": {
            "rows": len(rows), "fills": len(fills), "rejected": len(rejects),
            "symbols": len({f.symbol for f in fills}),
            "first": fills[0].at.isoformat() if fills else None, "last": fills[-1].at.isoformat() if fills else None,
        },
        "rejects": {"count": len(rejects), "by_reason": by_reason, "sample": rejects[:SAMPLE_LIMIT]},
        "basis": _basis_block(fills, costs, cost_options, pnl_basis),
        "summary": {
            "gross": summarize(gross),
            # 거래가 있는데 비용을 아는 거래가 하나도 없으면 '비용 뒤'는 없다(None) — 0건의 요약과 다르다.
            "net": summarize(net_known) if net_known or not records else None,
            "net_excluded": excluded,
            "costs": cost_block,
            "open_realized": open_realized,
        },
        "curve": {"basis": pnl_basis, **curve},
        "breakdowns": breakdowns,
        "extremes": {"basis": pnl_basis, "limit": EXTREMES_LIMIT, "worst": losers[:EXTREMES_LIMIT], "best": winners[:EXTREMES_LIMIT]},
        "trades": records[:TRADES_LIMIT], "trades_total": len(records), "trades_limit": TRADES_LIMIT,
        "open_positions": open_rows,
        "unmatched_sells": {
            "count": len(matched.unmatched_sells),
            "sample": [{**u, "message": UNMATCHED_SELL_MESSAGE} for u in matched.unmatched_sells[:SAMPLE_LIMIT]],
        },
        "not_covered": list(NOT_COVERED),
    }
