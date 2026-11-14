"""규칙 틀 일곱 — 매개변수를 받아 표현식 나무(`RuleSpec`)를 만든다 (분봉 백테스트 설계 §7.1).

틀은 나무를 만드는 함수일 뿐이다. 시뮬레이터는 나무만 보고, 계산은 `expr`·`indicators` 가 한다. 그래서 자유 조건식을 열 때
바뀌는 것은 나무를 직접 받는 문과 편집 화면뿐이다(받은 결정 3 — 지금은 틀, 지향점은 자유 조건식).

★도구는 규칙을 추천하지 않는다.★ 틀과 매개변수는 사용자가 고른다. 기본값은 화면의 출발점일 뿐이고 "좋은 값"이라는 뜻이 아니다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .simulator import RuleSpec


class RuleError(ValueError):
    """모르는 틀 · 모르는 매개변수 · 범위 밖의 값. `code` 가 사유다."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Number:
    key: str
    label: str
    low: float
    high: float
    default: float
    integer: bool = True
    unit: str = ""


@dataclass(frozen=True)
class Choice:
    key: str
    label: str
    values: tuple[str, ...]
    labels: tuple[str, ...]
    default: str


@dataclass(frozen=True)
class Template:
    label: str
    summary: str
    params: tuple[Number | Choice, ...]
    make: Callable[..., RuleSpec]
    needs_prev: bool = False
    notes: tuple[str, ...] = ()


# ── 나무를 짓는 작은 손 ────────────────────────────────────────────────────────────────
def _ind(name: str, **params) -> dict:
    return {"ind": name, **params}


def _const(value: float) -> dict:
    return {"const": value}


def _op(name: str, *args: dict, **extra) -> dict:
    return {"op": name, "args": list(args), **extra}


_CLOSE = _ind("close")


def _range_break(minutes: int) -> dict:
    """창이 끝난 뒤 종가가 창의 고가를 처음 넘는 봉. 창이 끝난 첫 봉은 앞 봉의 범위가 미상이라 돌파로 잡히지 않는다 — 따로 본다."""
    high, done = _ind("or_high", minutes=minutes), _op("gt", _ind("or_done", minutes=minutes), _const(0.5))
    first_after = _op("and", done, _op("not", _op("held_before", done, bars=1)))
    return _op("or", _op("cross_up", _CLOSE, high), _op("and", first_after, _op("gt", _CLOSE, high)))


def _orb(minutes: int) -> RuleSpec:
    return RuleSpec(entry=_range_break(minutes))


def _vwap(bars_below: int) -> RuleSpec:
    vwap = _ind("vwap")
    return RuleSpec(entry=_op("and", _op("cross_up", _CLOSE, vwap), _op("held_before", _op("lt", _CLOSE, vwap), bars=bars_below)),
                    exit=_op("lt", _CLOSE, vwap))


def _volatility(k: float) -> RuleSpec:
    span = _op("sub", _ind("prev_high"), _ind("prev_low"))
    return RuleSpec(entry_stop=_op("add", _ind("day_open"), _op("mul", _const(k), span)))


def _gap(direction: str, gap_pct: float, minutes: int) -> RuleSpec:
    prev, opened = _ind("prev_close"), _ind("day_open")
    if direction == "follow":
        gapped = _op("ge", opened, _op("mul", prev, _const(1 + gap_pct / 100.0)))
        return RuleSpec(entry=_op("and", gapped, _range_break(minutes)))
    gapped = _op("le", opened, _op("mul", prev, _const(1 - gap_pct / 100.0)))
    return RuleSpec(entry=_op("and", gapped, _op("cross_up", _CLOSE, opened)))


def _surge(bars: int, multiple: float) -> RuleSpec:
    return RuleSpec(entry=_op("and",
                              _op("ge", _ind("volume"), _op("mul", _const(multiple), _ind("vol_avg", bars=bars))),
                              _op("gt", _CLOSE, _ind("open")),
                              _op("gt", _CLOSE, _ind("highest_close", bars=bars))))


def _rsi(n: int, oversold: float, overbought: float) -> RuleSpec:
    rsi = _ind("rsi", n=n)
    return RuleSpec(entry=_op("cross_up", rsi, _const(oversold)), exit=_op("gt", rsi, _const(overbought)))


def _bollinger(direction: str, n: int, k: float) -> RuleSpec:
    mid = _ind("bb_mid", n=n, k=k)
    if direction == "revert":
        return RuleSpec(entry=_op("cross_up", _CLOSE, _ind("bb_lower", n=n, k=k)), exit=_op("ge", _CLOSE, mid))
    return RuleSpec(entry=_op("cross_up", _CLOSE, _ind("bb_upper", n=n, k=k)), exit=_op("lt", _CLOSE, mid))


_PREV_NOTE = "전일 값은 원주가입니다. 권리락이 있던 날에는 틀릴 수 있으며 확인하지 못했습니다."
_SESSION_NOTE = "지표는 그날의 봉으로만 계산합니다. 전일 봉으로 미리 채우지 않아 처음 몇 봉은 신호가 없습니다."

TEMPLATES: dict[str, Template] = {
    "opening_range_breakout": Template(
        "시가 범위 돌파", "장 시작 뒤 정한 시간의 고가를 봉 종가가 넘으면 다음 봉 시가에 매수합니다.",
        (Number("minutes", "범위를 재는 시간", 1, 120, 30, unit="분"),), _orb,
        notes=("범위는 그날 첫 봉의 시각부터 잽니다.",)),
    "vwap_cross": Template(
        "VWAP 상향 돌파", "종가가 당일 VWAP 아래에 머물다가 위로 올라서면 다음 봉 시가에 매수하고, 다시 아래로 내려가면 청산합니다.",
        (Number("bars_below", "아래에 머문 봉 수", 1, 60, 5, unit="봉"),), _vwap,
        notes=("VWAP 은 봉의 고가, 저가, 종가 평균에 거래량을 곱해 누적한 분봉 근사입니다.",)),
    "volatility_breakout": Template(
        "변동성 돌파", "당일 시가에 전일 범위의 일정 비율을 더한 값에 미리 매수 주문을 걸어 둡니다.",
        (Number("k", "전일 범위에 곱하는 비율", 0.1, 1.0, 0.5, integer=False, unit="배"),), _volatility, needs_prev=True,
        notes=("널리 알려진 꼴은 다음 날 시가에 팝니다. 이 도구는 하루를 넘겨 보유하지 않으므로 그 꼴과 다릅니다.",
               "주문은 둘째 봉부터 유효합니다. 첫 봉의 시가를 본 뒤에야 값이 정해지기 때문입니다.", _PREV_NOTE)),
    "gap": Template(
        "갭", "시가가 전일 종가와 크게 벌어진 날에만 진입합니다. 추종은 갭 상승 뒤의 범위 돌파를, 되돌림은 갭 하락 뒤 시가 회복을 봅니다.",
        (Choice("direction", "방향", ("follow", "fade"), ("갭 상승 추종", "갭 하락 되돌림"), "follow"),
         Number("gap_pct", "갭의 크기", 0.5, 20.0, 2.0, integer=False, unit="%"),
         Number("minutes", "범위를 재는 시간(추종)", 1, 120, 15, unit="분")), _gap, needs_prev=True,
        notes=(_PREV_NOTE,)),
    "volume_surge": Template(
        "거래량 급증", "봉 거래량이 직전 평균의 몇 배를 넘고 양봉이며 종가가 직전 최고 종가를 넘으면 다음 봉 시가에 매수합니다.",
        (Number("bars", "견주는 직전 봉 수", 2, 120, 20, unit="봉"),
         Number("multiple", "평균 대비 배수", 1.5, 20.0, 3.0, integer=False, unit="배")), _surge,
        notes=(_SESSION_NOTE,)),
    "rsi_reversal": Template(
        "RSI", "RSI 가 과매도선 아래에 있다가 위로 올라서면 다음 봉 시가에 매수하고, 과매수선을 넘으면 청산합니다.",
        (Number("n", "RSI 기간", 2, 60, 14, unit="봉"),
         Number("oversold", "과매도선", 5, 45, 30, integer=False),
         Number("overbought", "과매수선", 55, 95, 70, integer=False)), _rsi,
        notes=(_SESSION_NOTE,)),
    "bollinger": Template(
        "볼린저 밴드", "되돌림은 종가가 하단 밴드 아래로 내려갔다가 다시 안으로 들어올 때, 돌파는 종가가 상단 밴드를 넘을 때 다음 봉 시가에 매수합니다.",
        (Choice("direction", "방향", ("revert", "breakout"), ("하단 되돌림", "상단 돌파"), "revert"),
         Number("n", "기간", 5, 120, 20, unit="봉"),
         Number("k", "표준편차 배수", 0.5, 4.0, 2.0, integer=False, unit="배")), _bollinger,
        notes=("되돌림은 종가가 중심선에 닿으면, 돌파는 종가가 중심선 아래로 내려가면 청산합니다.", _SESSION_NOTE)),
}


def resolve(kind: str, params: dict | None = None) -> dict:
    """매개변수를 검사하고 기본값을 채운 ★하나의 꼴★ — 같은 설정은 늘 같은 사전이 된다(시행 횟수 기록이 이것으로 가른다)."""
    template = TEMPLATES.get(kind)
    if template is None:
        raise RuleError("unknown_kind", repr(kind))
    given = dict(params or {})
    extra = set(given) - {p.key for p in template.params}
    if extra:
        raise RuleError("unknown_param", f"{kind}: {sorted(extra)}")
    out: dict = {}
    for p in template.params:
        value = given.get(p.key, p.default)
        if isinstance(p, Choice):
            if not isinstance(value, str) or value not in p.values:
                raise RuleError("bad_choice", f"{kind}.{p.key}={value!r}")
            out[p.key] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuleError("param_not_number", f"{kind}.{p.key}={value!r}")
        if p.integer and int(value) != value:
            raise RuleError("param_not_integer", f"{kind}.{p.key}={value!r}")
        if not p.low <= value <= p.high:
            raise RuleError("param_out_of_range", f"{kind}.{p.key}={value!r} ({p.low}~{p.high})")
        out[p.key] = int(value) if p.integer else float(value)
    return out


def build(kind: str, params: dict | None = None) -> RuleSpec:
    """틀과 매개변수 → 나무 셋."""
    return TEMPLATES[kind].make(**resolve(kind, params)) if kind in TEMPLATES else resolve(kind, params)


def describe() -> list[dict]:
    """화면이 틀을 그리는 데 필요한 것 전부."""
    out = []
    for kind, t in TEMPLATES.items():
        params = []
        for p in t.params:
            if isinstance(p, Choice):
                params.append({"key": p.key, "label": p.label, "type": "choice", "default": p.default,
                               "choices": [{"value": v, "label": name} for v, name in zip(p.values, p.labels, strict=True)]})
            else:
                params.append({"key": p.key, "label": p.label, "type": "int" if p.integer else "float", "min": p.low,
                               "max": p.high, "default": p.default, "unit": p.unit})
        out.append({"kind": kind, "label": t.label, "summary": t.summary, "needs_prev": t.needs_prev, "params": params,
                    "notes": list(t.notes)})
    return out
