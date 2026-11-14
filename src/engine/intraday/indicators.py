"""분봉 지표 등록부 — 이름 → 인과 계산 (분봉 백테스트 설계 §7.1).

★등록부의 모든 지표는 "봉 i 의 값이 봉 i 까지만으로 정해진다"는 성질을 지켜야 한다.★ 그 성질은 지표마다가 아니라
등록부 전체에 한 번 건다(`tests/test_intraday_indicators.py::test_no_indicator_looks_ahead`) — 새 지표를 더하면 자동으로 걸린다.

- 지표는 ★그날 봉으로만★ 계산한다. 전일 봉으로 덥히지 않는다(전일 값이 필요한 것은 `prev_*` 셋뿐이고 따로 받는다).
- 덥혀지지 않은 자리 · 전일 값이 없는 자리 · 0 으로 나누게 되는 자리는 `NaN` 이다(0 이나 50 같은 값으로 채우지 않는다).
- 시가 범위의 창은 ★그날 첫 봉의 시각★부터 잰다(장 운영 시각을 가정하지 않는다 — 봉 시각의 뜻이 미상이어도 성립한다).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .types import Session


class IndicatorError(ValueError):
    """모르는 지표 · 모르는 매개변수 · 범위 밖의 값. `code` 가 사유다."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Range:
    """매개변수 하나의 허용 범위와 기본값."""

    low: float
    high: float
    default: float
    integer: bool = True


@dataclass(frozen=True)
class Indicator:
    fn: Callable[..., np.ndarray]
    params: dict[str, Range]
    needs_prev: bool = False        # 전일 값이 없으면 전부 NaN 이 되는 지표


def minutes_of(time: np.ndarray) -> np.ndarray:
    """`"HHMMSS"` 배열 → 자정부터의 분."""
    return np.array([int(t[:2]) * 60 + int(t[2:4]) for t in time], dtype=float)


def _windows(a: np.ndarray, n: int) -> np.ndarray:
    """길이 n 의 창을 한 줄씩 — 줄 j 는 `a[j:j+n]`. 창마다 따로 도는 대신 한 번에 줄인다(77만 봉에서 차이가 크다)."""
    return np.lib.stride_tricks.sliding_window_view(np.asarray(a, dtype=float), n)


def _rolling(a: np.ndarray, n: int, fn: Callable[..., np.ndarray]) -> np.ndarray:
    """자기 봉을 포함한 n 봉 — 덜 찬 창은 NaN."""
    out = np.full(len(a), np.nan)
    if len(a) >= n:
        out[n - 1:] = fn(_windows(a, n), axis=1)
    return out


def _before(a: np.ndarray, n: int, fn: Callable[..., np.ndarray]) -> np.ndarray:
    """자기 봉을 뺀 직전 n 봉."""
    out = np.full(len(a), np.nan)
    if len(a) > n:
        out[n:] = fn(_windows(a[:-1], n), axis=1)
    return out


def _vwap(s: Session) -> np.ndarray:
    typical = (s.high + s.low + s.close) / 3.0
    cum_v = np.cumsum(s.volume)
    cum_pv = np.cumsum(typical * s.volume)
    return np.divide(cum_pv, cum_v, out=np.full(len(cum_v), np.nan), where=cum_v > 0)


def _opening_range(s: Session, minutes: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(고가, 저가, 창이 끝났는가). 창 = 첫 봉 시각부터 `minutes` 분 — 창 안에서는 고가·저가가 미상이다."""
    clock = minutes_of(s.time)
    n = len(clock)
    hi, lo, done = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
    if n:
        inside = clock < clock[0] + minutes
        after = ~inside
        if after.any():
            hi[after], lo[after], done[after] = s.high[inside].max(), s.low[inside].min(), 1.0
    return hi, lo, done


def _rsi(s: Session, n: int) -> np.ndarray:
    """Wilder RSI — 첫 값은 변화 n 개가 쌓인 봉(n 번째 봉)에서 난다."""
    out = np.full(len(s.close), np.nan)
    change = np.diff(s.close)
    if len(change) < n:
        return out
    gain, loss = np.clip(change, 0, None), np.clip(-change, 0, None)
    avg_gain, avg_loss = gain[:n].mean(), loss[:n].mean()
    for i in range(n, len(s.close)):
        if i > n:
            avg_gain = (avg_gain * (n - 1) + gain[i - 1]) / n
            avg_loss = (avg_loss * (n - 1) + loss[i - 1]) / n
        if avg_loss > 0:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        elif avg_gain > 0:
            out[i] = 100.0                                     # 하락이 없었다 — 100 이라는 값
        # 둘 다 0(움직임 없음)이면 정의되지 않는다 — NaN 으로 둔다
    return out


def _band(s: Session, n: int, k: float, side: int) -> np.ndarray:
    mid = _rolling(s.close, n, np.mean)
    return mid + side * k * _rolling(s.close, n, np.std)        # 모표준편차(ddof=0)


def _prev(s: Session, field: str) -> np.ndarray:
    return np.full(len(s.close), getattr(s.prev, field) if s.prev is not None else np.nan, dtype=float)


_N = Range(1, 240, 20)
_K = Range(0.5, 4.0, 2.0, integer=False)
_OR = Range(1, 120, 30)
_BARS = Range(1, 240, 20)

INDICATORS: dict[str, Indicator] = {
    "open": Indicator(lambda s: s.open.astype(float), {}),
    "high": Indicator(lambda s: s.high.astype(float), {}),
    "low": Indicator(lambda s: s.low.astype(float), {}),
    "close": Indicator(lambda s: s.close.astype(float), {}),
    "volume": Indicator(lambda s: s.volume.astype(float), {}),
    "minute": Indicator(lambda s: minutes_of(s.time), {}),
    "day_open": Indicator(lambda s: np.full(len(s.close), s.open[0] if len(s.open) else np.nan, dtype=float), {}),
    "vwap": Indicator(_vwap, {}),
    "or_high": Indicator(lambda s, minutes: _opening_range(s, minutes)[0], {"minutes": _OR}),
    "or_low": Indicator(lambda s, minutes: _opening_range(s, minutes)[1], {"minutes": _OR}),
    "or_done": Indicator(lambda s, minutes: _opening_range(s, minutes)[2], {"minutes": _OR}),
    "sma": Indicator(lambda s, n: _rolling(s.close, n, np.mean), {"n": _N}),
    "bb_mid": Indicator(lambda s, n, k: _rolling(s.close, n, np.mean), {"n": _N, "k": _K}),
    "bb_upper": Indicator(lambda s, n, k: _band(s, n, k, +1), {"n": _N, "k": _K}),
    "bb_lower": Indicator(lambda s, n, k: _band(s, n, k, -1), {"n": _N, "k": _K}),
    "rsi": Indicator(_rsi, {"n": Range(2, 60, 14)}),
    "vol_avg": Indicator(lambda s, bars: _before(s.volume, bars, np.mean), {"bars": _BARS}),
    "highest_close": Indicator(lambda s, bars: _before(s.close, bars, np.max), {"bars": _BARS}),
    "prev_close": Indicator(lambda s: _prev(s, "close"), {}, needs_prev=True),
    "prev_high": Indicator(lambda s: _prev(s, "high"), {}, needs_prev=True),
    "prev_low": Indicator(lambda s: _prev(s, "low"), {}, needs_prev=True),
}


def resolve(name: str, params: dict | None = None) -> dict:
    """매개변수를 검사하고 기본값을 채운다. 어긋나면 `IndicatorError`(조용히 고쳐 쓰지 않는다)."""
    spec = INDICATORS.get(name)
    if spec is None:
        raise IndicatorError("unknown_indicator", name)
    given = dict(params or {})
    extra = set(given) - set(spec.params)
    if extra:
        raise IndicatorError("unknown_param", f"{name}: {sorted(extra)}")
    out = {}
    for key, rng in spec.params.items():
        value = given.get(key, rng.default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IndicatorError("param_not_integer" if rng.integer else "param_not_number", f"{name}.{key}={value!r}")
        if rng.integer and int(value) != value:
            raise IndicatorError("param_not_integer", f"{name}.{key}={value!r}")
        if not rng.low <= value <= rng.high:
            raise IndicatorError("param_out_of_range", f"{name}.{key}={value!r} ({rng.low}~{rng.high})")
        out[key] = int(value) if rng.integer else float(value)
    return out


def compute(session: Session, name: str, params: dict | None = None) -> np.ndarray:
    """지표 값 — 봉마다 하나(봉 수와 길이가 같다)."""
    return INDICATORS[name].fn(session, **resolve(name, params)) if name in INDICATORS else resolve(name, params)
