"""분봉 파일 → 분봉 백테스트의 하루(`Day`) — 엔진이 파일을 모르게 하는 층 (분봉 백테스트 설계 §6.1).

엔진(`src/engine/intraday`)은 순수 함수이고 봉 배열만 받는다. 여기서 파일을 읽어 그 모양으로 옮기면서
★쓰지 않는 것을 사유와 함께 건너뛴다★ — 고치거나 메우지 않는다:

- 그 날짜에 그 종목의 분봉이 없다 → `no_bars`
- 봉에 결함이 있다(`minute_quality` 가 센 것이 하나라도) → `defects`
- 운영 게이트가 막은 합성 하루 · 읽지 못한 파일 → 그 사유 그대로(`minute_bars.DAY_REASONS`)
- 정규장 밖의 봉(장전 · 시간외)은 싣지 않는다. 장 운영 규칙을 읽지 못했으면 가르지 않고 전부 싣는다(엔진이 그것을 센다).

"장이 늦게 열린 날"은 고른 종목이 아니라 ★그날 적재된 모든 종목★으로 본다. 전일 값은 앞선 적재일의 정규장 분봉에서 얻는다 —
거래일 달력이 없으므로 "가장 가까운 앞선 적재일"이고, 닷새보다 멀면 모른다고 둔다(값이 나온 날을 함께 싣는다).
일봉에서 전일 값을 얻는 길은 넣지 않았다: 분봉과 일봉의 출처가 다를 수 있어 섞으면 무엇을 쟀는지 흐려진다.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

import src.data.minute_bars as minute_bars
from src.data.minute_quality import defect_counts, session_shift
from src.engine.intraday.simulator import Day
from src.engine.intraday.types import PrevDay, Session
from src.engine.trade_journal.costs import market_and_instrument

#: 전일 값을 찾아 거슬러 가는 달력 일수 — 주말과 짧은 연휴를 넘는 길이다. 설정값이며 거래일 달력이 아니다.
MAX_LOOKBACK_DAYS = 5


@dataclass(frozen=True)
class Plan:
    """읽기 전에 알 수 있는 것 — 적재된 날짜와 그 파일들의 크기."""

    dates: list[str]
    bytes: int


def _dates(start: date, end: date) -> Iterable[date]:
    for step in range((end - start).days + 1):
        yield start + timedelta(days=step)


def plan(start: date, end: date) -> Plan:
    """기간 안에서 분봉 파일이 있는 날짜와 그 크기. ★파일을 읽지 않는다★ — 상한을 읽기 전에 판단하기 위한 것이다."""
    found = [(d.isoformat(), minute_bars._existing_day_path(d.isoformat())) for d in _dates(start, end)]
    found = [(day, path) for day, path in found if path is not None]
    return Plan([day for day, _ in found], sum(path.stat().st_size for _, path in found))


_VALUES = ("open", "high", "low", "close", "volume")


def _split(frame, rules: dict) -> dict[str, dict[str, np.ndarray]]:
    """고른 종목의 하루치 표 → 종목마다의 배열(정규장 안의 봉만 · 시각 순). ★하루에 한 번★ 가르고 정렬한다.

    종목마다 표를 다시 거르면 종목 수만큼 하루 전체를 훑는다 — 서른 종목 × 66일에서 그것이 실행 시간의 절반이었다(잰 값은 HISTORY)."""
    tick = frame["ticker"].astype(str).to_numpy().astype("U")
    time = frame["time"].astype(str).to_numpy().astype("U")
    keep = np.ones(len(time), dtype=bool)
    if rules.get("available"):                                  # 규칙을 못 읽었으면 가르지 않고 전부 싣는다
        hhmm = time.astype("U4")
        keep = (hhmm >= rules["open"]) & (hhmm <= rules["close"])
    order = np.flatnonzero(keep)
    order = order[np.lexsort((time[order], tick[order]))]       # 종목 → 시각 (같은 시각은 파일의 순서 그대로)
    tick, time = tick[order], time[order]
    values = {k: pd.to_numeric(frame[k], errors="coerce").to_numpy(dtype=np.float64)[order] for k in _VALUES}
    source = frame["source"].astype(str).to_numpy()[order] if "source" in frame.columns else None
    names, starts = np.unique(tick, return_index=True)
    out = {}
    for name, a, b in zip(names, starts, [*starts[1:], len(tick)], strict=True):
        origins = set(source[a:b]) if source is not None else {"unknown"}
        out[str(name)] = {"time": time[a:b], **{k: values[k][a:b] for k in _VALUES},
                          "source": origins.pop() if len(origins) == 1 else "unknown"}
    return out


def _session(ticker: str, day: str, rows: dict, prev: PrevDay | None, master) -> Session:
    market, instrument = market_and_instrument(ticker, master)
    record = master(ticker) if master is not None else None
    name = record.get("name") if isinstance(record, dict) and isinstance(record.get("name"), str) else None
    return Session(ticker=ticker, date=day, time=rows["time"], **{k: rows[k] for k in _VALUES}, source=rows["source"],
                   prev=prev, market=market, instrument=instrument, name=name)


def build_days(tickers: list[str], start: date, end: date, *, rules: dict,
               master: Callable[[str], dict | None] | None = None, need_prev: bool = False) -> list[Day]:
    """기간 안의 적재된 날마다 `Day` 하나. 파일이 없는 날은 목록에 없다."""
    wanted = sorted(dict.fromkeys(str(t) for t in tickers))
    first = start - timedelta(days=MAX_LOOKBACK_DAYS) if need_prev else start
    last_seen: dict[str, PrevDay] = {}
    out: list[Day] = []
    for d in _dates(first, end):
        day = d.isoformat()
        if minute_bars._existing_day_path(day) is None:
            continue
        loaded = minute_bars.load_day_frame(day)
        in_range = d >= start
        if loaded.frame is None:
            if in_range:
                out.append(Day(day, {}, tuple((t, loaded.reason) for t in wanted)))
            continue
        asked = loaded.frame[loaded.frame["ticker"].astype(str).isin(wanted)]
        defects = defect_counts(asked, rules)                  # 봉이 하나라도 있는 종목 → 결함의 수
        parts = _split(asked, rules) if len(asked) else {}
        sessions: dict[str, Session] = {}
        skipped: list[tuple[str, str]] = []
        for ticker in wanted:
            rows = parts.get(ticker)
            reason = "no_bars" if ticker not in defects or rows is None else "defects" if defects[ticker] else None
            if reason:
                skipped.append((ticker, reason))
                last_seen.pop(ticker, None)                    # 쓰지 않은 하루는 다음 날의 '전일'도 되지 못한다
                continue
            known = last_seen.get(ticker)
            near = known is not None and (d - date.fromisoformat(known.date)).days <= MAX_LOOKBACK_DAYS
            session = _session(ticker, day, rows, known if need_prev and near else None, master)
            last_seen[ticker] = PrevDay(close=float(session.close[-1]), high=float(session.high.max()),
                                        low=float(session.low.min()), basis="minute", date=day)
            sessions[ticker] = session
        if in_range:
            shifted = session_shift(loaded.frame, rules)["session_shifted"] is True
            out.append(Day(day, sessions, tuple(skipped), shifted))
    return out
