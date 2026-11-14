"""분봉 시뮬레이터 — 규칙 하나를 하루씩 돌려 ★체결 줄★을 만든다 (분봉 백테스트 설계 §6). 순수 함수.

만드는 것은 체결 줄뿐이다. 왕복 매칭·비용·지표는 매매일지 엔진이 한다(`run` 이 넘긴다) — 백테스트와 실거래가 같은 정의를 쓴다.

**시간 의미론 — 앞보기를 구조로 막는다**
- 하루의 모든 종목 봉을 ★시각 순으로 한 번★ 돈다(같은 분 안에서는 종목 코드 순). 하루 최대 손실·동시 보유·손실 뒤 대기는
  종목을 가로지르는 상태다.
- 신호는 봉 i 의 종가까지로 계산하고(`expr` 의 인과 나무) 체결은 ★봉 i+1 의 시가★다. 신호 봉에서는 체결하지 않는다.
- 예외는 미리 걸어 둔 가격 주문뿐이다 — 손절·익절·추적 손절(진입 때 정해진 값)과 미리 건 매수(앞 봉까지로 정해진 값).
- 추적 손절의 기준 고가는 ★끝난 봉까지만★ 올린다. 미리 건 매수가 체결된 봉에서는 손절·익절을 보지 않는다(그 봉의 저가가
  진입 앞인지 뒤인지 모른다 — 세어 둔다).
- 하루를 넘기지 않는다: 그 종목의 마지막 봉에서 남은 수량을 종가에 청산한다.

**세어 두는 것** — 가정이 쓰인 횟수와 막힌 진입(`ASSUMPTIONS`). 지어내지 않은 것은 건너뛰고 사유를 남긴다(`SKIP_REASONS`).
하루 최대 손실은 ★비용 전★ 실현손익으로 본다(수수료·세금은 일지 엔진이 뒤에 계산한다) — 그것도 가정이라 문장에 적는다.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from . import expr, fills
from .types import Session


class SimError(ValueError):
    """어긋난 설정. `code` 가 사유다."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RuleSpec:
    """규칙 하나 — 표현식 나무 셋. 틀(`rules.py`)이 만들고 시뮬레이터는 이것만 본다."""

    entry: dict | None = None          # 판단 — 참인 봉의 ★다음 봉 시가★에 매수
    entry_stop: dict | None = None     # 수 — 미리 건 매수의 가격(봉 i 에서는 봉 i−1 까지로 정해진 값을 쓴다)
    exit: dict | None = None           # 판단 — 참인 봉의 다음 봉 시가에 매도


@dataclass(frozen=True)
class PositionRules:
    amount: float                              # 거래당 진입 금액(원)
    stop_pct: float | None = None              # 손절 %(진입가 대비)
    target_pct: float | None = None            # 익절 %
    trail_pct: float | None = None             # 추적 손절 %(끝난 봉까지의 고가 대비)
    time_exit: str | None = None               # "HHMM" — 이 시각 이후 첫 봉의 시가에 청산
    entry_from: str | None = None              # "HHMM" — 이 시각부터 진입
    entry_until: str | None = None             # "HHMM" — 이 시각부터는 진입하지 않는다(없으면 종가 단일가 시작)
    max_entries_per_ticker: int | None = 1     # 종목당 하루 진입 수
    max_open_positions: int | None = None      # 동시에 보유하는 종목 수
    daily_loss_limit: float | None = None      # 원 — 그날 실현손익(비용 전)이 이만큼 손실이면 새 진입 중단
    cooldown_after_loss_min: int | None = None  # 손실로 끝난 청산 뒤 이 분 동안 새 진입 금지


@dataclass(frozen=True)
class CostAssumptions:
    commission_bp: float | None = None         # 편도 수수료율 — 일지 엔진에 그대로 넘긴다(None = 모름)
    slippage_ticks: int = 1                    # 시장가 체결의 불리한 틱 수
    participation_cap: float | None = 0.1      # 그 봉 거래량 대비 체결 상한(None = 상한 없음)


@dataclass(frozen=True)
class Day:
    date: str
    sessions: dict[str, Session]
    skipped: tuple[tuple[str, str], ...] = ()  # (종목, 사유) — 봉을 준비한 쪽이 이미 건너뛴 것
    shifted: bool = False                      # 장 운영 시간이 평소와 다른 날


SKIP_REASONS = {
    "no_previous_day": "전일 값이 없어 이 규칙을 적용하지 못했습니다.",
    "session_shifted": "장 운영 시간이 평소와 다른 날이라 건너뛰었습니다.",
    "empty_session": "봉이 하나도 없습니다.",
    "no_bars": "이 날짜에 이 종목의 분봉이 없습니다.",
    "defects": "봉에 결함이 있어 쓰지 않았습니다.",
    "synthetic_rows_blocked": "모의 모드에서 만든 합성 분봉이라 운영에서는 쓰지 않습니다.",
    "not_loaded": "이 날짜의 분봉이 적재돼 있지 않습니다.",
}

ASSUMPTIONS = {
    "stop_and_target_same_bar": "한 봉 안에서 손절과 익절이 함께 걸려 손절이 먼저 체결된 것으로 보았습니다.",
    "entry_bar_range_unknown": "미리 건 매수가 체결된 봉에서는 그 봉의 고가와 저가가 진입 앞인지 뒤인지 알 수 없어 손절과 익절을 보지 않았습니다.",
    "entry_skipped_no_trades": "진입할 봉에 거래가 없어 진입하지 않았습니다.",
    "entry_skipped_amount_too_small": "진입 금액으로 한 주도 살 수 없어 진입하지 않았습니다.",
    "entry_skipped_by_participation": "참여율 상한 안에서 한 주도 살 수 없어 진입하지 않았습니다.",
    "entry_cut_by_participation": "참여율 상한 때문에 진입 수량을 줄였습니다.",
    "entry_blocked_time": "진입 시각 창 밖이라 진입하지 않았습니다.",
    "entry_blocked_daily_loss": "하루 최대 손실에 닿아 진입하지 않았습니다. 손실은 비용 전 실현손익으로 판단했습니다.",
    "entry_blocked_cooldown": "손실로 끝난 청산 뒤 대기 시간이 지나지 않아 진입하지 않았습니다.",
    "entry_blocked_max_entries": "종목당 하루 진입 수를 채워 진입하지 않았습니다.",
    "entry_blocked_max_open": "동시 보유 종목 수를 채워 진입하지 않았습니다.",
    "exit_deferred_no_trades": "청산할 봉에 거래가 없어 거래가 있는 다음 봉으로 미뤘습니다.",
    "exit_deferred_thin_bar": "참여율 상한 안에서 한 주도 팔 수 없어 청산을 다음 봉으로 미뤘습니다.",
    "exit_spread_by_participation": "참여율 상한 때문에 청산을 여러 봉에 나눴습니다.",
    "forced_exit_without_trades": "마지막 봉에 거래가 없었지만 종가에 청산한 것으로 보았습니다.",
    "forced_exit_over_participation": "마지막 봉의 강제 청산이 참여율 상한을 넘었습니다.",
    "no_closing_auction_cutoff": "장 운영 시각 규칙을 읽지 못해 종가 단일가 구간의 진입 마감을 적용하지 않았습니다.",
    "etf_uses_stock_tick_table": "ETF 체결에 주식의 호가 단위 표를 적용했습니다. 실제 호가 단위와 다를 수 있습니다.",
}


# ── 설정 검사 ──────────────────────────────────────────────────────────────────────────
def _hhmm_ok(value) -> bool:
    return isinstance(value, str) and len(value) == 4 and value.isdigit() and int(value[:2]) < 24 and int(value[2:]) < 60


def _number_ok(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _kind(tree, wanted: str, code: str) -> None:
    try:
        got = expr.validate(tree)
    except expr.ExprError as err:
        raise SimError(err.code, err.detail) from None
    if got != wanted:
        raise SimError(code)


def validate(rule: RuleSpec, position: PositionRules, costs: CostAssumptions) -> None:
    if rule.entry is None and rule.entry_stop is None:
        raise SimError("no_entry")
    if rule.entry is not None:
        _kind(rule.entry, "bool", "entry_not_a_condition")
    if rule.entry_stop is not None:
        _kind(rule.entry_stop, "number", "entry_stop_not_a_price")
    if rule.exit is not None:
        _kind(rule.exit, "bool", "exit_not_a_condition")
    if not (_number_ok(position.amount) and position.amount > 0):
        raise SimError("bad_amount", "amount")
    if position.daily_loss_limit is not None and not (_number_ok(position.daily_loss_limit) and position.daily_loss_limit > 0):
        raise SimError("bad_amount", "daily_loss_limit")
    for name in ("stop_pct", "target_pct", "trail_pct"):
        value = getattr(position, name)
        if value is not None and not (_number_ok(value) and 0 < value < 100):
            raise SimError("bad_percent", name)
    for name in ("time_exit", "entry_from", "entry_until"):
        value = getattr(position, name)
        if value is not None and not _hhmm_ok(value):
            raise SimError("bad_time", name)
    for name in ("max_entries_per_ticker", "max_open_positions", "cooldown_after_loss_min"):
        value = getattr(position, name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise SimError("bad_count", name)
    if isinstance(costs.slippage_ticks, bool) or not isinstance(costs.slippage_ticks, int) or costs.slippage_ticks < 0:
        raise SimError("bad_slippage")
    cap = costs.participation_cap
    if cap is not None and not (_number_ok(cap) and 0 < cap <= 1):
        raise SimError("bad_participation")
    if costs.commission_bp is not None and not (_number_ok(costs.commission_bp) and costs.commission_bp >= 0):
        raise SimError("bad_commission")


# ── 상태 ───────────────────────────────────────────────────────────────────────────────
@dataclass
class _Position:
    qty: int
    entry: float
    stop: float | None
    target: float | None
    trail_high: float | None
    skip_bar: int = -1                 # 미리 건 매수가 체결된 봉 — 그 봉의 고가·저가는 쓰지 않는다
    exiting: str | None = None         # 시장가 청산이 걸려 있다(종류)
    realized: float = 0.0


@dataclass
class _Ticker:
    session: Session
    entry_sig: np.ndarray | None
    exit_sig: np.ndarray | None
    levels: np.ndarray | None
    index: dict[str, int]
    pos: _Position | None = None
    pending_entry: bool = False
    pending_exit: str | None = None
    entries: int = 0
    told: set = field(default_factory=set)     # 미리 건 매수가 막힌 사유 — 종목·하루에 한 번만 센다


@dataclass
class _DayState:
    realized: float = 0.0
    open: int = 0
    block_until: int = -1
    halted: bool = False


class _Run:
    def __init__(self, rule: RuleSpec, position: PositionRules, costs: CostAssumptions, rules: dict | None) -> None:
        self.rule, self.position, self.costs = rule, position, costs
        self.cutoff = position.entry_until or (rules["closing_auction_from"] if rules and rules.get("available") else None)
        self.needs_prev = any(expr.uses_prev(t) for t in (rule.entry, rule.entry_stop, rule.exit) if t is not None)
        self.protected = any(v is not None for v in (position.stop_pct, position.target_pct, position.trail_pct))
        self.fills: list[dict] = []
        self.events: list[dict] = []
        self.skipped: list[dict] = []
        self.counters: Counter = Counter()
        self.counts = {"days": 0, "sessions": 0, "bars": 0, "entries": 0, "exits": 0}
        self.sources = {"kis": 0, "synthetic": 0, "unknown": 0}

    # 하루 ─────────────────────────────────────────────────────────────────────────────
    def day(self, day: Day) -> None:
        for ticker, reason in day.skipped:
            self.skipped.append({"date": day.date, "ticker": ticker, "reason": reason})
        live: dict[str, _Ticker] = {}
        for ticker in sorted(day.sessions):
            s = day.sessions[ticker]
            reason = ("session_shifted" if day.shifted else "empty_session" if len(s.time) == 0
                      else "no_previous_day" if self.needs_prev and s.prev is None else None)
            if reason:
                self.skipped.append({"date": day.date, "ticker": ticker, "reason": reason})
                continue
            cache: dict = {}
            live[ticker] = _Ticker(
                session=s,
                entry_sig=expr.evaluate(self.rule.entry, s, cache) if self.rule.entry is not None else None,
                exit_sig=expr.evaluate(self.rule.exit, s, cache) if self.rule.exit is not None else None,
                levels=expr.evaluate(self.rule.entry_stop, s, cache) if self.rule.entry_stop is not None else None,
                index={str(t): i for i, t in enumerate(s.time)})
            self.sources[s.source if s.source in self.sources else "unknown"] += 1
        if not live:
            return
        self.counts["days"] += 1
        self.counts["sessions"] += len(live)
        if self.cutoff is None:
            self.counters["no_closing_auction_cutoff"] += 1
        state = _DayState()
        for label in sorted({str(t) for tk in live.values() for t in tk.session.time}):
            for ticker in live:                                   # 같은 분 안에서는 종목 코드 순
                i = live[ticker].index.get(label)
                if i is not None:
                    self.bar(day.date, live[ticker], i, label, state)

    # 봉 하나 ──────────────────────────────────────────────────────────────────────────
    def bar(self, date: str, tk: _Ticker, i: int, label: str, state: _DayState) -> None:
        s = tk.session
        o, h, low, c, v = (float(a[i]) for a in (s.open, s.high, s.low, s.close, s.volume))
        hhmm, minute = label[:4], int(label[:2]) * 60 + int(label[2:4])
        ctx = (date, tk, i, label, state, minute)
        self.counts["bars"] += 1
        acted = False

        if tk.pos is not None:
            pos = tk.pos
            timed = self.position.time_exit is not None and hhmm >= self.position.time_exit
            due = pos.exiting or tk.pending_exit or ("time_exit" if timed else None)
            if due:
                tk.pending_exit = None
                if v > 0:
                    self.sell(ctx, fills.sell_market(o, self.costs.slippage_ticks), v, due)
                else:
                    self.counters["exit_deferred_no_trades"] += 1
                    pos.exiting = due
                acted = True
            else:
                acted = self.protect(ctx, o, h, low, v)
        elif tk.pending_entry:
            tk.pending_entry = False
            acted = self.enter(ctx, "entry_signal", o, v, hhmm)
            if acted:
                self.protect(ctx, o, h, low, v)                    # 시가에 들어갔으니 이 봉의 범위는 진입 뒤다
        elif tk.levels is not None and i >= 1 and v > 0:
            level = float(tk.levels[i - 1])                        # 앞 봉까지로 정해진 값
            if level > 0 and not math.isnan(level):
                price = fills.stop_buy(level, bar_open=o, bar_high=h, ticks=self.costs.slippage_ticks)
                if price is not None and self.enter(ctx, "entry_stop", price, v, hhmm):
                    acted = True
                    tk.pos.skip_bar = i
                    if self.protected:
                        self.counters["entry_bar_range_unknown"] += 1

        # 봉이 끝났다 — 다음 봉을 위한 판단
        if tk.pos is not None:
            pos = tk.pos
            if pos.trail_high is not None and i != pos.skip_bar:
                pos.trail_high = max(pos.trail_high, h)
            if pos.exiting is None and tk.exit_sig is not None and tk.exit_sig[i]:
                tk.pending_exit = "rule_exit"
        elif tk.entry_sig is not None and tk.entry_sig[i]:
            tk.pending_entry = True

        if i == len(s.time) - 1:                                   # 하루를 넘기지 않는다
            tk.pending_entry = False
            if tk.pos is not None:
                if v <= 0:
                    self.counters["forced_exit_without_trades"] += 1
                elif fills.capped(tk.pos.qty, bar_volume=v, cap=self.costs.participation_cap) < tk.pos.qty:
                    self.counters["forced_exit_over_participation"] += 1
                self.sell(ctx, fills.sell_market(c, self.costs.slippage_ticks), None, "session_end")

    # 진입 ─────────────────────────────────────────────────────────────────────────────
    def enter(self, ctx, kind: str, raw: float, volume: float, hhmm: str) -> bool:
        date, tk, i, label, state, minute = ctx
        p = self.position
        blocked = ("entry_blocked_time" if (p.entry_from is not None and hhmm < p.entry_from)
                   or (self.cutoff is not None and hhmm >= self.cutoff)
                   else "entry_blocked_daily_loss" if state.halted
                   else "entry_blocked_cooldown" if minute < state.block_until
                   else "entry_blocked_max_entries" if p.max_entries_per_ticker is not None and tk.entries >= p.max_entries_per_ticker
                   else "entry_blocked_max_open" if p.max_open_positions is not None and state.open >= p.max_open_positions
                   else "entry_skipped_no_trades" if volume <= 0 else None)
        price = wanted = qty = 0
        if blocked is None:
            price = fills.buy_market(raw, self.costs.slippage_ticks) if kind == "entry_signal" else raw
            wanted = fills.quantity(p.amount, price)
            qty = fills.capped(wanted, bar_volume=volume, cap=self.costs.participation_cap)
            blocked = ("entry_skipped_amount_too_small" if wanted == 0 else "entry_skipped_by_participation" if qty == 0 else None)
        if blocked is not None:
            if kind == "entry_signal" or blocked not in tk.told:   # 미리 건 매수는 봉마다 다시 걸린다 — 한 번만 센다
                self.counters[blocked] += 1
                tk.told.add(blocked)
            return False
        if qty < wanted:
            self.counters["entry_cut_by_participation"] += 1
        self.emit(ctx, "buy", qty, price, kind)
        tk.pos = _Position(qty=qty, entry=price,
                           stop=fills.stop_level(price, p.stop_pct) if p.stop_pct is not None else None,
                           target=fills.target_level(price, p.target_pct) if p.target_pct is not None else None,
                           trail_high=price if p.trail_pct is not None else None)
        tk.entries += 1
        state.open += 1
        self.counts["entries"] += 1
        return True

    # 손절 · 익절 · 추적 손절 ────────────────────────────────────────────────────────────
    def protect(self, ctx, o: float, h: float, low: float, v: float) -> bool:
        tk = ctx[1]
        pos = tk.pos
        if pos is None or v <= 0:
            return False
        trail = fills.stop_level(pos.trail_high, self.position.trail_pct) if pos.trail_high is not None else None
        stops = [x for x in (pos.stop, trail) if x is not None]
        stop = max(stops) if stops else None
        target = fills.limit_sell(pos.target, bar_open=o, bar_high=h) if pos.target is not None else None
        if stop is not None and low <= stop:
            if target is not None:
                self.counters["stop_and_target_same_bar"] += 1     # 봉 안의 순서를 모른다 — 손절 먼저
            kind = "trail" if trail is not None and trail == stop and (pos.stop is None or trail > pos.stop) else "stop"
            self.sell(ctx, fills.stop_sell(stop, bar_open=o, bar_low=low, ticks=self.costs.slippage_ticks), v, kind)
            return True
        if target is not None:
            self.sell(ctx, target, v, "target")
            return True
        return False

    # 매도 ─────────────────────────────────────────────────────────────────────────────
    def sell(self, ctx, price: float, volume: float | None, kind: str) -> None:
        """`volume` 이 `None` 이면 상한 없이 전량(마지막 봉의 강제 청산)."""
        date, tk, i, label, state, minute = ctx
        pos = tk.pos
        qty = pos.qty if volume is None else fills.capped(pos.qty, bar_volume=volume, cap=self.costs.participation_cap)
        if qty == 0:
            self.counters["exit_deferred_thin_bar"] += 1
            pos.exiting = kind
            return
        self.emit(ctx, "sell", qty, price, kind)
        pnl = (price - pos.entry) * qty
        pos.qty -= qty
        pos.realized += pnl
        state.realized += pnl
        limit = self.position.daily_loss_limit
        if limit is not None and state.realized <= -limit:
            state.halted = True
        if pos.qty > 0:
            self.counters["exit_spread_by_participation"] += 1
            pos.exiting = "exit_remainder"
            return
        if pos.realized < 0 and self.position.cooldown_after_loss_min is not None:
            state.block_until = max(state.block_until, minute + self.position.cooldown_after_loss_min)
        tk.pos = None
        state.open -= 1
        self.counts["exits"] += 1

    def emit(self, ctx, side: str, qty: int, price: float, kind: str) -> None:
        date, tk, i, label, state, minute = ctx
        s = tk.session
        if s.instrument == "etf":
            self.counters["etf_uses_stock_tick_table"] += 1
        self.events.append({"row": len(self.fills), "date": date, "ticker": s.ticker, "bar": label, "kind": kind})
        self.fills.append({"executed_at": f"{date} {label[:2]}:{label[2:4]}:{label[4:6]}", "symbol": s.ticker, "side": side,
                           "quantity": int(qty), "price": float(price), "market": s.market, "instrument": s.instrument,
                           "name": s.name})


def simulate(days: Sequence[Day], rule: RuleSpec, position: PositionRules, costs: CostAssumptions, *,
             rules: dict | None = None) -> dict:
    """규칙 하나를 날마다 돌린다. `rules` 는 `market_rules.session_rules()` 의 답(없으면 종가 단일가 진입 마감을 적용하지 않고 센다)."""
    validate(rule, position, costs)
    run = _Run(rule, position, costs, rules)
    for day in days:
        run.day(day)
    return {"fills": run.fills, "events": run.events, "skipped": run.skipped, "assumptions": dict(run.counters),
            "counts": run.counts, "sources": run.sources}
