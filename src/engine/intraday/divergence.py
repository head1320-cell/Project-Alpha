"""괴리 — 증권사 체결 ↔ 시뮬레이션 체결 (설계 W5 §4.2 · §4.3)
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-paper-trading-monitor-design.md`. ★순수 함수★ — 읽지도 쓰지도 않는다.

답하는 물음은 하나다: **백테스트가 가정한 체결과 실제 체결이 얼마나 다른가.** 권고는 만들지 않는다(관측만).

## 정의
- **덩어리**: 종목 · 방향 · 같은 분에 든 체결 줄을 하나로 묶는다(수량 합 · 수량 가중 평균가). 시뮬레이션은 한 봉에 한 체결이고
  실제 주문은 여러 번에 나뉘어 체결되기 때문이다.
- **짝**: 종목 · 날짜 · 방향이 같고 시각 차이가 허용 창 안인 것끼리 ★가까운 것부터★ 1:1 로 맺는다(먼저 온 신호가 남의 짝을
  가져가지 않는다). 같은 거리면 이른 것이 먼저다.
- **불리함**: 매수는 비싸게, 매도는 싸게 체결된 만큼이 양수다(원 · 틱 · bp — 기준은 시뮬레이션 체결가).
- **갈래 셋**: 짝지은 것 · 시뮬레이션에만 있는 것(놓친 신호) · 실제에만 있는 것(규칙 밖 매매 — 규칙의 종목 안에서).

## 값이 없을 때
- 짝이 없으면 차이는 0 이 아니라 **값 없음 + 사유**다.
- 체결 시각이 하나도 없는 파일은 ★하루 단위로 열화★한다(`mode="daily"` + 사유). 일부만 없으면 그 줄을 따로 빼고 센다.
- 기간 밖 · 다른 종목 · 읽지 못한 줄은 `set_aside` 에 세어 적는다 — 조용히 버리지 않는다.

허용 창은 사용자의 선언이다(근거가 있는 것은 "봉 주기 1분보다 가는 차이는 구분할 수 없다"뿐). 그래서 창 셋(1 · 5 · 15분)의
건수를 늘 함께 낸다.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, median

from src.data.market_rules import tick_size
from src.engine.trade_journal.fills import Fill, normalize

WINDOWS = (1, 5, 15)
DEFAULT_WINDOW = 5
MAX_WINDOW = 60
_EVEN = 1e-9

REASONS: dict[str, str] = {
    "no_pairs": "짝지은 체결이 없어 체결가 차이를 계산하지 못했습니다.",
    "no_times": "파일에 체결 시각이 없어 하루 단위로 견줬습니다. 체결가는 그날의 수량 가중 평균입니다.",
    "cost_unknown": "한쪽의 비용을 알 수 없어 비용 후 차이를 계산하지 못했습니다.",
    "bad_window": "짝짓기 허용 시간은 1분 이상 60분 이하의 정수여야 합니다.",
}


class DivergenceError(ValueError):
    """받은 설정이 어긋났다. `code` 는 `REASONS` 의 열쇠다."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or REASONS.get(code, code))
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class _Lump:
    symbol: str
    side: str
    at: datetime                 # 그 분의 시작(하루 단위에서는 그날 0시)
    quantity: float
    price: float                 # 수량 가중 평균가
    parts: int                   # 묶인 체결 줄 수


def _minute(f: Fill) -> datetime:
    return f.at.replace(second=0, microsecond=0)


def _day(f: Fill) -> datetime:
    return f.at.replace(hour=0, minute=0, second=0, microsecond=0)


def _lumps(fills: Iterable[Fill], bucket: Callable[[Fill], datetime]) -> list[_Lump]:
    groups: dict[tuple[str, str, datetime], list[Fill]] = defaultdict(list)
    for f in fills:
        groups[(f.symbol, f.side, bucket(f))].append(f)
    out = []
    for (symbol, side, at), rows in groups.items():
        qty = sum(r.quantity for r in rows)
        out.append(_Lump(symbol, side, at, qty, sum(r.quantity * r.price for r in rows) / qty, len(rows)))
    return sorted(out, key=lambda x: (x.at, x.symbol, x.side))


def _window(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_WINDOW:
        raise DivergenceError("bad_window", repr(value))
    return value


def _pair_timed(sim: Sequence[_Lump], actual: Sequence[_Lump], window: int) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    """가까운 것부터 1:1 — `(짝의 (시뮬레이션 번호, 실제 번호), 남은 시뮬레이션, 남은 실제)`."""
    by_key: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for j, a in enumerate(actual):
        by_key[(a.symbol, a.side, a.at.date().isoformat())].append(j)
    candidates = []
    for i, s in enumerate(sim):
        for j in by_key.get((s.symbol, s.side, s.at.date().isoformat()), ()):
            minutes = int((actual[j].at - s.at).total_seconds() // 60)
            if abs(minutes) <= window:
                candidates.append((abs(minutes), s.at, actual[j].at, i, j))
    used_s: set[int] = set()
    used_a: set[int] = set()
    pairs = []
    for _dist, _s_at, _a_at, i, j in sorted(candidates):
        if i in used_s or j in used_a:
            continue
        used_s.add(i)
        used_a.add(j)
        pairs.append((i, j))
    return pairs, set(range(len(sim))) - used_s, set(range(len(actual))) - used_a


def _pair_daily(sim: Sequence[_Lump], actual: Sequence[_Lump]) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    where = {(a.symbol, a.side, a.at): j for j, a in enumerate(actual)}
    pairs = [(i, where[(s.symbol, s.side, s.at)]) for i, s in enumerate(sim) if (s.symbol, s.side, s.at) in where]
    return pairs, set(range(len(sim))) - {i for i, _ in pairs}, set(range(len(actual))) - {j for _, j in pairs}


def _stamp(at: datetime, daily: bool) -> str:
    return at.date().isoformat() if daily else at.isoformat()


def _pair_row(s: _Lump, a: _Lump, daily: bool) -> dict:
    adverse = a.price - s.price if s.side == "buy" else s.price - a.price
    return {
        "symbol": s.symbol, "side": s.side, "date": s.at.date().isoformat(),
        "sim_at": _stamp(s.at, daily), "actual_at": _stamp(a.at, daily),
        "minutes": None if daily else int((a.at - s.at).total_seconds() // 60),
        "sim_price": s.price, "actual_price": a.price,
        "adverse": adverse, "ticks": adverse / tick_size(s.price), "bp": adverse / s.price * 10_000,
        "sim_quantity": s.quantity, "actual_quantity": a.quantity, "quantity_diff": a.quantity - s.quantity,
        "parts": a.parts,
    }


def _alone(x: _Lump, daily: bool) -> dict:
    return {"symbol": x.symbol, "side": x.side, "at": _stamp(x.at, daily), "price": x.price, "quantity": x.quantity,
            "parts": x.parts}


def _price_gap(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "reason": "no_pairs", "message": REASONS["no_pairs"]}

    def stat(pick) -> dict:
        return {key: pick([r[field] for r in rows]) for key, field in (("won", "adverse"), ("ticks", "ticks"), ("bp", "bp"))}

    return {
        "n": len(rows), "mean": stat(mean), "median": stat(median),
        "worst": max(rows, key=lambda r: r["adverse"]),
        "adverse": sum(1 for r in rows if r["adverse"] > _EVEN),
        "favorable": sum(1 for r in rows if r["adverse"] < -_EVEN),
        "even": sum(1 for r in rows if abs(r["adverse"]) <= _EVEN),
    }


def _time_gap(rows: list[dict]) -> dict | None:
    late = [abs(r["minutes"]) for r in rows if r["minutes"] is not None]
    if not late:
        return None
    return {"mean_minutes": mean(late), "median_minutes": median(late), "max_minutes": max(late)}


def compare(sim_rows: Sequence[dict], actual_rows: Sequence[dict], *, tickers: Sequence[str], start: str, end: str,
            window_minutes: int = DEFAULT_WINDOW) -> dict:
    """시뮬레이션 체결 줄 · 올린 체결 줄 → 괴리.

    `tickers` 는 규칙의 종목이다 — 그 밖의 종목은 견주지 않고 세어 적는다. `start`·`end` 는 `YYYY-MM-DD`(양 끝 포함).
    시뮬레이션 줄이 온전하지 않으면 `ValueError` 다(시뮬레이터의 결함이지 사용자의 입력이 아니다 — 삼키지 않는다).
    """
    window = _window(window_minutes)
    sim, broken = normalize(list(sim_rows))
    if broken or any(not f.has_time for f in sim):
        raise ValueError(f"시뮬레이션 체결 줄이 온전하지 않다: {broken[:3]!r}")

    fills, rejects = normalize(list(actual_rows))
    inside = [f for f in fills if start <= f.at.date().isoformat() <= end]
    wanted = set(tickers)
    mine = [f for f in inside if f.symbol in wanted]
    others = [f for f in inside if f.symbol not in wanted]
    timed = [f for f in mine if f.has_time]
    untimed = [f for f in mine if not f.has_time]
    daily = bool(mine) and not timed                         # 시각이 하나도 없다 → 하루 단위로 열화

    if daily:
        sim_l, act_l = _lumps(sim, _day), _lumps(untimed, _day)
        pairs, sim_left, act_left = _pair_daily(sim_l, act_l)
        by_window: list[dict] = []                           # 창은 시각이 있어야 뜻이 있다
    else:
        sim_l, act_l = _lumps(sim, _minute), _lumps(timed, _minute)
        pairs, sim_left, act_left = _pair_timed(sim_l, act_l, window)
        by_window = []
        for minutes in sorted({*WINDOWS, window}):
            p, s_left, a_left = (pairs, sim_left, act_left) if minutes == window else _pair_timed(sim_l, act_l, minutes)
            by_window.append({"minutes": minutes, "matched": len(p), "sim_only": len(s_left), "actual_only": len(a_left),
                              "chosen": minutes == window})

    matched = sorted((_pair_row(sim_l[i], act_l[j], daily) for i, j in pairs),
                     key=lambda r: (r["sim_at"], r["symbol"], r["side"]))
    return {
        "mode": "daily" if daily else "timed",
        "degraded": {"reason": "no_times", "message": REASONS["no_times"]} if daily else None,
        "window_minutes": window,
        "counts": {"matched": len(matched), "sim_only": len(sim_left), "actual_only": len(act_left)},
        "by_window": by_window,
        "matched": matched,
        "sim_only": [_alone(sim_l[i], daily) for i in sorted(sim_left)],
        "actual_only": [_alone(act_l[j], daily) for j in sorted(act_left)],
        "price_gap": _price_gap(matched),
        "time_gap": _time_gap(matched),
        "quantity_gap": {"differs": sum(1 for r in matched if abs(r["quantity_diff"]) > _EVEN)},
        "set_aside": {
            "rejected": rejects,
            "outside_period": len(fills) - len(inside),
            "other_symbols": {"rows": len(others), "symbols": sorted({f.symbol for f in others})},
            "untimed": 0 if daily else len(untimed),
        },
        "inputs": {"sim_fills": len(sim), "actual_rows": len(actual_rows), "actual_fills": len(act_l)},
    }


def rows_in_scope(actual_rows: Sequence[dict], tickers: Sequence[str], start: str, end: str) -> list[dict]:
    """견주는 범위의 줄 — 읽을 수 있고 · 기간 안이고 · 규칙의 종목인 것(시각이 없는 줄도 든다). 받은 순서 그대로다.

    실제 쪽 손익을 ★견준 것과 같은 줄★로 계산하려고 둔다(다른 종목 · 기간 밖의 매매가 차이에 섞이지 않게).
    """
    rows = list(actual_rows)
    fills, _rejects = normalize(rows)
    wanted = set(tickers)
    keep = sorted(f.row for f in fills if f.symbol in wanted and start <= f.at.date().isoformat() <= end)
    return [rows[i] for i in keep]


def _totals(journal: dict) -> dict:
    summary = journal["summary"]
    net = summary.get("net")
    known = net is not None and not summary.get("net_excluded")      # 일부만 아는 합은 견줄 수 없다
    return {"gross": summary["gross"]["total"], "net": net["total"] if known else None, "trades": summary["gross"]["n"]}


def pnl_gap(simulated: dict, actual: dict) -> dict:
    """두 매매일지(같은 엔진 · 같은 정의)의 실현손익과 그 차이(실제 − 시뮬레이션). 갈래별로 쪼개지 않는다."""
    sim, act = _totals(simulated), _totals(actual)
    unknown = sim["net"] is None or act["net"] is None
    return {
        "simulated": sim, "actual": act,
        "gap": {"gross": act["gross"] - sim["gross"], "net": None if unknown else act["net"] - sim["net"]},
        "net_reason": "cost_unknown" if unknown else None,
        "net_message": REASONS["cost_unknown"] if unknown else None,
    }
