"""분봉 품질 검사 — ★고치지 않고 센다★ (분봉 백테스트 설계 W4a).

순수 함수다(입출력 없음). 받은 표를 고치지 않고, 결함을 메우지 않고, 봉을 버리지 않는다 — 무엇이 몇 개인지 세어 돌려주고
판단은 쓰는 쪽(적재 범위 보고 · 분봉 백테스트)이 한다. 세는 것은 세 갈래다:

- **결함**(`DEFECTS`) — 봉 자체가 말이 안 되는 것: 읽히지 않는 시각 · 같은 시각의 봉 둘 · 고가·저가가 시가·종가를 감싸지 못함 ·
  0 이하의 가격 · 음수 거래량 · 빈 값.
- **결함이 아닌 사정** — 거래 없는 봉(거래량 0) · 1분이 넘는 빈틈. 거래정지나 거래 없음일 수 있어 결함으로 단정하지 않는다.
- **장 운영** — 정규장 안/밖의 봉 수와 "평소와 다른 날"(`session_shifted`). ★시각으로 추론한 표시다★: 장 운영 시각은
  `market_rules.session_rules()`(증거 파일 · T1)에서 오고, 그 규칙이 없으면 가르지 않고 `None` + 사유를 준다.

봉의 시각이 그 1분의 시작인지 끝인지는 이 저장소에 근거가 없다(미상). 그래서 정규장의 양 끝 시각은 둘 다 안으로 센다.

계산 길은 하나다 — 봉마다 표시를 한 번 매기고(전 종목 하루는 백만 줄이다), 합계는 그 표시를 그대로 더하고 종목별 값은 종목으로 묶어 더한다.
`check_session` 은 종목이 하나인 하루로 같은 길을 지난다. 그래서 합계와 종목별 값이 어긋날 수 없다.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

#: 봉 자체의 결함. 봉 하나가 여러 결함을 가질 수 있다(`defect_total` 은 결함 건수의 합이다 — 봉 수가 아니다).
DEFECTS = ("bad_time", "duplicate_time", "ohlc_inconsistent", "nonpositive_price", "negative_volume", "missing_value")

#: 그날 적재된 모든 종목의 첫 봉이 평소 개장보다 이만큼(분) 넘게 늦으면 "평소와 다른 날"로 표시한다.
#: 개장이 한 시간 늦는 날(수능일 등)을 잡기 위한 값이다 — 30분은 그 절반으로 잡은 ★설정값★이고 재 본 값이 아니다.
SHIFT_MINUTES = 30

REASONS = {
    "no_session_rules": "장 운영 시각 규칙을 읽지 못해 정규장 안팎과 운영 시간 변동을 가르지 않았습니다.",
    "no_bars": "봉이 없어 운영 시간 변동을 판단하지 않았습니다.",
}

_PRICE = ("open", "high", "low", "close")


def _clock(times: pd.Series) -> tuple[pd.Series, pd.Series]:
    """`"HHMMSS"` 열 → (읽히는가, 자정부터의 분)."""
    shaped = times.str.len().eq(6) & times.str.isdigit()
    num = pd.to_numeric(times.where(shaped), errors="coerce")
    hh, mm, ss = num // 10_000, (num // 100) % 100, num % 100
    valid = shaped & (hh < 24) & (mm < 60) & (ss < 60)
    return valid, (hh * 60 + mm).where(valid)


def _rules_ok(rules: dict | None) -> bool:
    return bool(rules and rules.get("available") and rules.get("open") and rules.get("close"))


def _marks(day: pd.DataFrame, rules: dict | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """봉마다 한 줄의 표시(결함·거래 없음·정규장 안) — 합계와 종목별 값이 ★같은 표시★를 더해 나온다.

    돌려주는 것: (표시, 종목·시각, 읽히는 시각인가, 자정부터의 분)."""
    keyed = pd.DataFrame({"ticker": day["ticker"].astype(str), "time": day["time"].astype(str)})
    times = keyed["time"]
    valid, minutes = _clock(times)
    numeric = day[[*_PRICE, "volume"]].apply(pd.to_numeric, errors="coerce")
    o, h, low, c, v = (numeric[k] for k in (*_PRICE, "volume"))
    missing = numeric.isna().any(axis=1)
    wraps = (low <= o.where(o <= c, c)) & (o.where(o >= c, c) <= h)
    marks = pd.DataFrame({
        "bars": 1,
        "bad_time": ~valid,
        "duplicate_time": valid & keyed.duplicated(["ticker", "time"]),
        "ohlc_inconsistent": ~wraps & ~missing,
        "nonpositive_price": (numeric[list(_PRICE)] <= 0).any(axis=1) & ~missing,
        "negative_volume": v < 0,
        "missing_value": missing,
        "zero_volume_bars": v == 0,
        "inside": (valid & (times.str[:4] >= rules["open"]) & (times.str[:4] <= rules["close"])) if _rules_ok(rules) else False,
    }).astype(int)
    return marks, keyed, valid, minutes


def _per_ticker(marks: pd.DataFrame, keyed: pd.DataFrame, valid: pd.Series, minutes: pd.Series) -> pd.DataFrame:
    """종목마다 한 줄 — 표시의 합 + 첫·마지막 봉 + 1분이 넘는 빈틈."""
    out = marks.groupby(keyed["ticker"]).sum()
    seen = keyed[valid].assign(minutes=minutes[valid]).drop_duplicates(["ticker", "time"]).sort_values(["ticker", "minutes"])
    span = seen.groupby("ticker")["time"].agg(["min", "max"])
    step = seen.groupby("ticker")["minutes"].diff()
    long = step.where(step > 1)
    out["first"], out["last"] = span["min"], span["max"]
    out["gap_count"] = long.notna().groupby(seen["ticker"]).sum()
    out["gap_longest"] = long.groupby(seen["ticker"]).max()
    return out.fillna({"gap_count": 0, "gap_longest": 0})


def _session_dict(row: pd.Series, rules: dict | None) -> dict[str, Any]:
    defects = {name: int(row[name]) for name in DEFECTS}
    known = _rules_ok(rules)
    return {
        "bars": int(row["bars"]),
        "first": row["first"] if isinstance(row["first"], str) else None,
        "last": row["last"] if isinstance(row["last"], str) else None,
        "defects": defects, "defect_total": sum(defects.values()),
        "zero_volume_bars": int(row["zero_volume_bars"]),
        "gaps": {"count": int(row["gap_count"]), "longest_minutes": int(row["gap_longest"])},
        "regular": {"inside": int(row["inside"]), "outside": int(row["bars"] - row["inside"])} if known else None,
        "regular_reason": None if known else "no_session_rules",
    }


def check_session(bars: pd.DataFrame, rules: dict | None = None) -> dict[str, Any]:
    """한 종목의 하루치 봉(`time·open·high·low·close·volume`)을 검사한다."""
    if len(bars) == 0:
        known = _rules_ok(rules)
        return {"bars": 0, "first": None, "last": None, "defects": dict.fromkeys(DEFECTS, 0), "defect_total": 0,
                "zero_volume_bars": 0, "gaps": {"count": 0, "longest_minutes": 0},
                "regular": {"inside": 0, "outside": 0} if known else None,
                "regular_reason": None if known else "no_session_rules"}
    return _session_dict(_per_ticker(*_marks(bars.assign(ticker="_"), rules)).loc["_"], rules)


def check_day(day: pd.DataFrame, rules: dict | None = None, *, detail: Iterable[str] | None = None) -> dict[str, Any]:
    """하루치 봉 전부(`ticker`·`source` 열 포함)를 검사한다 — 합계 · 출처별 행 수 · 운영 시간 변동 · 종목별 결과.

    종목별 결과(`by_ticker`)는 `detail` 로 고른 종목만 싣는다(`None` 이면 전부). 합계는 고른 종목과 무관하게 하루 전체다."""
    counts = day["source"].value_counts() if "source" in day.columns else {}
    out: dict[str, Any] = {
        "tickers": 0, "bars": int(len(day)),
        "sources": {name: int(counts.get(name, 0)) for name in ("kis", "synthetic", "unknown")},
        "defects": dict.fromkeys(DEFECTS, 0), "defect_total": 0, "zero_volume_bars": 0, "by_ticker": {},
        "session_shifted": None, "session_shift": None, "shift_reason": None,
    }
    earliest, started = None, 0
    if len(day):
        marks, keyed, valid, minutes = _marks(day, rules)
        out["tickers"] = int(keyed["ticker"].nunique())
        out["defects"] = {name: int(marks[name].sum()) for name in DEFECTS}
        out["defect_total"] = sum(out["defects"].values())
        out["zero_volume_bars"] = int(marks["zero_volume_bars"].sum())
        if valid.any():
            earliest, started = keyed["time"][valid].min(), int(keyed["ticker"][valid].nunique())
        # 종목별 값은 고른 종목의 줄만 묶는다 — 전 종목 하루(백만 줄)에서 서른 종목을 볼 때 전부 묶지 않는다.
        rows = slice(None) if detail is None else keyed["ticker"].isin({str(t) for t in detail})
        if detail is None or rows.any():
            table = _per_ticker(marks[rows], keyed[rows], valid[rows], minutes[rows])
            out["by_ticker"] = {str(t): _session_dict(table.loc[t], rules) for t in table.index}
    out.update(_shift(earliest, started, rules))
    return out


def _shift(earliest: str | None, started: int, rules: dict | None) -> dict[str, Any]:
    if not _rules_ok(rules):
        return {"session_shifted": None, "session_shift": None, "shift_reason": "no_session_rules"}
    if earliest is None:
        return {"session_shifted": None, "session_shift": None, "shift_reason": "no_bars"}
    # 한 종목이라도 제때 시작했으면 장은 제때 열린 것이다 — 그날 가장 이른 봉으로 본다.
    late = (int(earliest[:2]) * 60 + int(earliest[2:4])) - (int(rules["open"][:2]) * 60 + int(rules["open"][2:]))
    return {"session_shifted": late > SHIFT_MINUTES, "shift_reason": None,
            "session_shift": {"earliest_first": earliest, "expected_open": rules["open"], "minutes_late": late, "tickers": started}}


def session_shift(day: pd.DataFrame, rules: dict | None = None) -> dict[str, Any]:
    """하루 전체에서 운영 시간 변동만 본다 — `check_day` 의 그 부분과 같은 답을, 봉마다 표시를 매기지 않고 낸다.

    분봉 백테스트는 고른 종목만 검사하지만 "장이 늦게 열렸는가"는 ★그날 적재된 모든 종목★으로 봐야 한다."""
    if len(day) == 0:
        return _shift(None, 0, rules)
    times = day["time"].astype(str)
    earliest = times.min()
    valid, _ = _clock(pd.Series([earliest]))
    if not bool(valid.iloc[0]):                                # 가장 작은 글자가 시각이 아니다 — 읽히는 것만 다시 본다
        ok, _ = _clock(times)
        earliest = times[ok].min() if ok.any() else None
        started = int(day["ticker"].astype(str)[ok].nunique()) if ok.any() else 0
    else:
        started = int(day["ticker"].astype(str).nunique())
    return _shift(earliest, started, rules)
