"""분봉 지표 등록부 — 이름 → 인과 계산 (분봉 백테스트 설계 §7.1).

★등록부의 모든 지표는 "봉 i 의 값이 봉 i 까지만으로 정해진다"는 성질을 지켜야 한다.★ 그 성질은 지표마다가 아니라
등록부 전체에 한 번 건다(`tests/test_intraday_indicators.py::test_no_indicator_looks_ahead`) — 새 지표를 더하면 자동으로 걸린다.

- 지표는 ★그날 봉으로만★ 계산한다. 전일 봉으로 덥히지 않는다(전일 값이 필요한 것은 `prev_*` 셋뿐이고 따로 받는다).
- 덥혀지지 않은 자리 · 전일 값이 없는 자리 · 0 으로 나누게 되는 자리는 `NaN` 이다(0 이나 50 같은 값으로 채우지 않는다).
- 시가 범위의 창은 ★그날 첫 봉의 시각★부터 잰다(장 운영 시각을 가정하지 않는다 — 봉 시각의 뜻이 미상이어도 성립한다).
- 이름표(`label`)와 단위(`unit`)는 화면이 조건을 짓는 데 쓴다(자유 조건식 설계 §4) — ★등록부의 지표는 전부 이름표가 있어야 한다★
  (`tests/test_intraday_custom_rules.py`). 화면이 이름을 지어내지 않는다.
- 앞 봉의 값을 이어 쓰는 지표(`carries` — 지수이동평균 · MACD · ATR · RSI)는 ★그날 첫 봉부터 다시 계산한다★. 여러 날을 이어 계산하는
  차트 도구의 값과 하루 내내 다르다 — 규칙의 주석이 그렇게 말한다(`rules.notes_of`).
- 세션 밖의 것을 읽는 지표(`context` — 하루 유형 · 시장 국면)는 ★규칙 맥락★(`Session.context`)에서 읽는다. 맥락은 문 층이 사용자의 것만 골라 싣고,
  맥락이 없으면 명시적으로 실패한다(미상으로 두면 그 조건을 쓴 규칙이 조용히 거래 0 이 된다). 맥락의 값도 봉 i 까지만 쓴다(같은 성질).
  시장 국면 확률은 그날 시가 전에 알던 값(전 거래일 종가까지 — 문 층이 K1 과 같은 함수로 짓는다)이라 첫 봉부터 하루 내내 같다.
- 매개변수는 수(`Range`) · 모형 열쇠(`Key`) · 고르기(`Pick` — 지수)다. ★기본값이 없는 칸★(모형 · 고르기 · 기본값이 `None` 인 수)은
  비었으면 거절한다(`param_missing` · `bad_model_key`) — 도구가 모형 · 지수 · 국면 수를 고르지 않는다.
"""
from __future__ import annotations

import re
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
    """매개변수 하나의 허용 범위와 기본값. 기본값이 `None` 이면 사용자가 정해야 하는 칸이다(비었으면 `param_missing`)."""

    low: float
    high: float
    default: float | None
    integer: bool = True
    label: str = ""                 # 화면의 이름표
    unit: str = ""                  # 화면의 단위(봉 · 분 · 배)


@dataclass(frozen=True)
class Key:
    """모형 열쇠를 받는 매개변수 — 수가 아니다(64자리 소문자 16진). 열쇠가 가리키는 모형은 규칙 맥락에서 읽는다.

    기본값이 없다 — 비었으면 거절한다(아무 모형이나 지어 넣지 않는다)."""

    kind: str                       # 어느 모형인가(`day_type`) — 화면이 고르기 목록을 정하는 데 쓴다
    label: str = ""


@dataclass(frozen=True)
class Pick:
    """정해진 값 가운데 하나를 고르는 매개변수(지수) — 수가 아니다. ★기본값이 없다★ — 비었으면 거절한다(도구가 고르지 않는다)."""

    choices: tuple[tuple[str, str], ...]   # (값, 이름표)
    label: str = ""

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(value for value, _ in self.choices)


#: 모형 열쇠의 꼴 — 하루 유형 모형의 열쇠(`day_types.model_key` · sha256 16진)와 같다.
MODEL_KEY = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Indicator:
    fn: Callable[..., np.ndarray]
    params: dict[str, Range | Key | Pick]
    needs_prev: bool = False        # 전일 값이 없으면 전부 NaN 이 되는 지표
    label: str = ""                 # 화면의 이름표
    unit: str = ""                  # 값의 단위 — `UNITS` 의 열쇠
    carries: bool = False           # 앞 봉의 값을 이어 쓰는 지표 — 그날 첫 봉의 영향이 하루 내내 남는다
    context: str | None = None      # 규칙 맥락에서 읽는 것(`RuleContext` 의 칸 이름) — 없으면 세션의 봉만 본다
    check: Callable[[dict], None] | None = None   # 매개변수끼리의 검사(칸 하나로는 못 보는 것) — 어긋나면 `IndicatorError`
    text: Callable[[dict], str] | None = None     # 규칙의 글 — 없으면 '이름표(값단위, …)'
    slots: tuple[str, ...] | None = None          # 쓸 수 있는 규칙의 자리 — `None` 이면 어디나(자리 검사는 `rules` 가 한다)


#: 지표 값의 단위 → 이름표. 화면이 "가격과 거래량을 견주고 있다" 같은 것을 알려 줄 때 쓴다(막지는 않는다).
UNITS = {"price": "가격(원)", "volume": "거래량(주)", "minute": "시각(자정부터의 분)", "index": "지수(0~100)", "flag": "여부(1 또는 0)",
         "prob": "확률(0~1)"}


def minutes_of(time: np.ndarray) -> np.ndarray:
    """`"HHMMSS"` 배열 → 자정부터의 분."""
    if len(time) == 0:
        return np.zeros(0)
    # 앞 네 글자(HHMM)를 글자 넷의 코드값으로 펴서 한 번에 센다. 숫자가 아니거나 네 글자가 안 되면 ValueError 다
    # (봉마다 `int()` 로 읽던 때와 같은 실패 — 틀린 시각을 0 으로 읽지 않는다).
    digits = np.ascontiguousarray(np.asarray(time).astype("U4")).view(np.uint32).reshape(len(time), 4).astype(np.int64) - 48
    if ((digits < 0) | (digits > 9)).any():
        raise ValueError("시각을 읽지 못했다 — HHMM 으로 시작하는 숫자여야 한다")
    return (digits[:, 0] * 600 + digits[:, 1] * 60 + digits[:, 2] * 10 + digits[:, 3]).astype(float)


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


def _smooth(a: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """이어 쓰는 평균 — 첫 값은 값 n 개가 쌓인 봉에서 그 n 개의 단순평균, 그 뒤 `앞 값 + (값 − 앞 값) × alpha`.

    지수이동평균은 alpha = 2/(n+1), Wilder 평활은 alpha = 1/n 이다. 앞머리의 미상은 건너뛰고 ★값이 처음 난 봉부터★ 센다
    (MACD 신호선이 MACD 가 처음 난 봉부터 세도록). 값이 n 개에 못 미치면 끝까지 미상이다 — 짧은 평균으로 때우지 않는다."""
    a = np.asarray(a, dtype=float)
    out = np.full(len(a), np.nan)
    known = np.flatnonzero(~np.isnan(a))
    if not len(known) or len(a) - known[0] < n:
        return out
    start = int(known[0])
    value = a[start:start + n].mean()
    out[start + n - 1] = value
    for i in range(start + n, len(a)):
        value = value + (a[i] - value) * alpha
        out[i] = value
    return out


def _ema(a: np.ndarray, n: int) -> np.ndarray:
    return _smooth(a, n, 2.0 / (n + 1))


def _macd(s: Session, fast: int, slow: int) -> np.ndarray:
    """단기 지수이동평균 − 장기 지수이동평균 — 둘 다 있는 봉부터 난다. 단기가 더 길어도 정의는 그대로다(부호가 뒤집힌다)."""
    return _ema(s.close, fast) - _ema(s.close, slow)


def _macd_signal(s: Session, fast: int, slow: int, signal: int) -> np.ndarray:
    return _ema(_macd(s, fast, slow), signal)


def _macd_hist(s: Session, fast: int, slow: int, signal: int) -> np.ndarray:
    line = _macd(s, fast, slow)
    return line - _ema(line, signal)


def _true_range(s: Session) -> np.ndarray:
    """진폭 = max(고가 − 저가, |고가 − 앞 봉 종가|, |저가 − 앞 봉 종가|). ★첫 봉은 앞 봉이 없어 고가 − 저가다★ — 전일 종가를 쓰지 않는다
    (지표는 그날 봉으로만 계산한다 · 전일 값은 원주가라 권리락이 있던 날에 틀릴 수 있다)."""
    spread = (s.high - s.low).astype(float)
    if len(spread) > 1:
        before = s.close[:-1]
        spread[1:] = np.maximum(spread[1:], np.maximum(np.abs(s.high[1:] - before), np.abs(s.low[1:] - before)))
    return spread


def _day_type_is(s: Session, model: str, type: int) -> np.ndarray:    # 매개변수 이름 = 나무 잎의 열쇠(`type`)
    """그날의 장 초반 유형이 `type` 인가 — 맥락의 모형으로 ★세션 자신의 첫 N 봉★을 센다(T1 의 특징 · 배정 그대로).

    창의 마지막 봉(첫 봉 + N − 1)부터 하루 끝까지 1 또는 0, 그 앞 봉은 NaN(아직 모른다). 창이 어긋난 날(빠진 분 · 0 이하 가격 ·
    봉이 N 개 미만)은 하루 내내 NaN 이다. 창 뒤의 봉은 읽지 않는다 — 잘린 세션도 같은 앞부분을 낸다."""
    from . import day_types  # 꾸러미가 다 읽힌 뒤에 부른다(day_types → simulator → expr → 이 모듈)

    ref = s.context.day_types.get(model) if s.context is not None else None
    if ref is None:
        raise IndicatorError("rule_context_missing", f"day_type_is: {model[:8]}")
    if type > ref.k:
        raise IndicatorError("day_type_out_of_range", f"day_type_is.type={type} > {ref.k}")
    out = np.full(len(s.close), np.nan)
    vec, _reason = day_types.window(s, ref.minutes)
    if vec is not None:
        label = int(day_types.assign(ref.centroids, vec[None, :])[0])       # 0 부터 — 유형 번호는 1 부터
        out[ref.minutes - 1:] = 1.0 if label == type - 1 else 0.0
    return out


#: 시장 국면의 지수 — 시장 국면 문(`intraday_market_regime_routes.INDEXES`)과 같다(시험이 건다 · 이 모듈은 문 층을 들이지 않는다).
REGIME_INDEXES = (("KOSPI", "코스피"), ("KOSDAQ", "코스닥"))
_REGIME_NAMES = dict(REGIME_INDEXES)


def _regime_prob(s: Session, index: str, k: int, state: int) -> np.ndarray:
    """그날의 시장 국면 소속 확률(국면 `state`) — 맥락의 값(그날 시가 전에 알던 값 · 전 거래일 종가까지)이라 ★첫 봉부터 하루 내내 같다★.

    그날 값이 없으면(적합 창이 덜 찬 달 · 지수 일봉이 없는 날) 하루 내내 NaN — 조건을 충족하지 않는다(0 이나 균등 확률로 채우지 않는다).
    맥락에 그 (지수, 국면 수)가 없으면 명시적으로 실패한다. 봉을 읽지 않는다 — 잘린 세션도 같은 앞부분을 낸다."""
    ref = s.context.regimes.get((index, k)) if s.context is not None else None
    if ref is None:
        raise IndicatorError("rule_context_missing", f"regime_prob: {index}·{k}")
    probs = ref.probs.get(s.date)
    return np.full(len(s.close), np.nan if probs is None else float(probs[state - 1]))


def _regime_check(p: dict) -> None:
    """국면 번호는 그 국면 수까지다(칸 하나로는 볼 수 없는 것)."""
    if p["state"] > p["k"]:
        raise IndicatorError("regime_state_out_of_range", f"regime_prob.state={p['state']} > k={p['k']}")


def _regime_text(p: dict) -> str:
    return f"{_REGIME_NAMES[p['index']]} 국면 {p['state']} 확률(국면 {p['k']}개)"


_N = Range(1, 240, 20, label="기간", unit="봉")
_K = Range(0.5, 4.0, 2.0, integer=False, label="표준편차 배수", unit="배")
_OR = Range(1, 120, 30, label="범위를 재는 시간", unit="분")
_BARS = Range(1, 240, 20, label="직전 봉 수", unit="봉")
_FAST = Range(1, 240, 12, label="단기 기간", unit="봉")
_SLOW = Range(1, 240, 26, label="장기 기간", unit="봉")
_SIGNAL = Range(1, 60, 9, label="신호 기간", unit="봉")

INDICATORS: dict[str, Indicator] = {
    "open": Indicator(lambda s: s.open.astype(float), {}, label="시가", unit="price"),
    "high": Indicator(lambda s: s.high.astype(float), {}, label="고가", unit="price"),
    "low": Indicator(lambda s: s.low.astype(float), {}, label="저가", unit="price"),
    "close": Indicator(lambda s: s.close.astype(float), {}, label="종가", unit="price"),
    "volume": Indicator(lambda s: s.volume.astype(float), {}, label="거래량", unit="volume"),
    "minute": Indicator(lambda s: minutes_of(s.time), {}, label="봉 시각", unit="minute"),
    "day_open": Indicator(lambda s: np.full(len(s.close), s.open[0] if len(s.open) else np.nan, dtype=float), {},
                          label="당일 시가", unit="price"),
    # 당일 고가 · 저가는 ★그 봉을 포함한다★(그 봉까지의 값) — 직전까지의 값은 연산 'N봉 전 값'으로 얻는다.
    "day_high": Indicator(lambda s: np.maximum.accumulate(s.high.astype(float)), {}, label="당일 고가", unit="price"),
    "day_low": Indicator(lambda s: np.minimum.accumulate(s.low.astype(float)), {}, label="당일 저가", unit="price"),
    "vwap": Indicator(_vwap, {}, label="VWAP", unit="price"),
    "or_high": Indicator(lambda s, minutes: _opening_range(s, minutes)[0], {"minutes": _OR}, label="시가 범위 고가", unit="price"),
    "or_low": Indicator(lambda s, minutes: _opening_range(s, minutes)[1], {"minutes": _OR}, label="시가 범위 저가", unit="price"),
    "or_done": Indicator(lambda s, minutes: _opening_range(s, minutes)[2], {"minutes": _OR}, label="시가 범위 종료", unit="flag"),
    "sma": Indicator(lambda s, n: _rolling(s.close, n, np.mean), {"n": _N}, label="이동평균", unit="price"),
    "ema": Indicator(lambda s, n: _ema(s.close, n), {"n": _N}, label="지수이동평균", unit="price", carries=True),
    "bb_mid": Indicator(lambda s, n, k: _rolling(s.close, n, np.mean), {"n": _N, "k": _K}, label="볼린저 중심선", unit="price"),
    "bb_upper": Indicator(lambda s, n, k: _band(s, n, k, +1), {"n": _N, "k": _K}, label="볼린저 상단", unit="price"),
    "bb_lower": Indicator(lambda s, n, k: _band(s, n, k, -1), {"n": _N, "k": _K}, label="볼린저 하단", unit="price"),
    "rsi": Indicator(_rsi, {"n": Range(2, 60, 14, label="기간", unit="봉")}, label="RSI", unit="index", carries=True),
    "macd": Indicator(_macd, {"fast": _FAST, "slow": _SLOW}, label="MACD", unit="price", carries=True),
    "macd_signal": Indicator(_macd_signal, {"fast": _FAST, "slow": _SLOW, "signal": _SIGNAL}, label="MACD 신호선", unit="price", carries=True),
    "macd_hist": Indicator(_macd_hist, {"fast": _FAST, "slow": _SLOW, "signal": _SIGNAL}, label="MACD 오실레이터", unit="price", carries=True),
    "atr": Indicator(lambda s, n: _smooth(_true_range(s), n, 1.0 / n), {"n": Range(1, 240, 14, label="기간", unit="봉")},
                     label="ATR", unit="price", carries=True),
    "vol_avg": Indicator(lambda s, bars: _before(s.volume, bars, np.mean), {"bars": _BARS}, label="직전 평균 거래량", unit="volume"),
    "highest_close": Indicator(lambda s, bars: _before(s.close, bars, np.max), {"bars": _BARS}, label="직전 최고 종가", unit="price"),
    "prev_close": Indicator(lambda s: _prev(s, "close"), {}, needs_prev=True, label="전일 종가", unit="price"),
    "prev_high": Indicator(lambda s: _prev(s, "high"), {}, needs_prev=True, label="전일 고가", unit="price"),
    "prev_low": Indicator(lambda s: _prev(s, "low"), {}, needs_prev=True, label="전일 저가", unit="price"),
    # 하루 유형(T2) — 유형 번호의 상한 16 은 `day_types.MAX_K` 와 같다(시험이 건다 · 이 모듈은 그 모듈을 미리 들이지 않는다).
    "day_type_is": Indicator(_day_type_is, {"model": Key("day_type", label="모형"),
                                            "type": Range(1, 16, 1, label="유형 번호", unit="번")},
                             label="하루 유형", unit="flag", context="day_types"),
    # 시장 국면(K3) — 국면 수 2 ~ 4 는 `market_regime.K_RANGE` 와 같다(시험이 건다). 지수 · 국면 수 · 번호는 기본값이 없다(도구가 고르지 않는다).
    # 진입 조건에서만 쓴다(`slots`) — 국면 조건의 꼴은 `rules._check_regime` 이 본다.
    "regime_prob": Indicator(_regime_prob, {"index": Pick(REGIME_INDEXES, label="지수"),
                                            "k": Range(2, 4, None, label="국면 수", unit="개"),
                                            "state": Range(1, 4, None, label="국면 번호", unit="번")},
                             label="시장 국면 확률", unit="prob", context="regimes", check=_regime_check, text=_regime_text,
                             slots=("entry",)),
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
        if isinstance(rng, Key):                                # 모형 열쇠 — 기본값이 없다(비었으면 거절)
            value = given.get(key)
            if not (isinstance(value, str) and MODEL_KEY.fullmatch(value)):
                raise IndicatorError("bad_model_key", f"{name}.{key}={value!r}"[:120])
            out[key] = value
            continue
        if isinstance(rng, Pick):                               # 고르기 — 기본값이 없다(비었으면 거절 · 모르는 값도 거절)
            value = given.get(key)
            if value is None:
                raise IndicatorError("param_missing", f"{name}.{key}")
            if not (isinstance(value, str) and value in rng.values):
                raise IndicatorError("bad_choice", f"{name}.{key}={value!r}"[:120])
            out[key] = value
            continue
        value = given.get(key, rng.default)
        if value is None and rng.default is None:               # 기본값이 없는 수 칸 — 비었으면 거절(지어 넣지 않는다)
            raise IndicatorError("param_missing", f"{name}.{key}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IndicatorError("param_not_integer" if rng.integer else "param_not_number", f"{name}.{key}={value!r}")
        if rng.integer and int(value) != value:
            raise IndicatorError("param_not_integer", f"{name}.{key}={value!r}")
        if not rng.low <= value <= rng.high:
            raise IndicatorError("param_out_of_range", f"{name}.{key}={value!r} ({rng.low}~{rng.high})")
        out[key] = int(value) if rng.integer else float(value)
    if spec.check is not None:
        spec.check(out)
    return out


def compute(session: Session, name: str, params: dict | None = None) -> np.ndarray:
    """지표 값 — 봉마다 하나(봉 수와 길이가 같다)."""
    return INDICATORS[name].fn(session, **resolve(name, params)) if name in INDICATORS else resolve(name, params)
