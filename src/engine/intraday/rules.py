"""규칙 틀 일곱 — 매개변수를 받아 표현식 나무(`RuleSpec`)를 만든다 (분봉 백테스트 설계 §7.1).

틀은 나무를 만드는 함수일 뿐이다. 시뮬레이터는 나무만 보고, 계산은 `expr`·`indicators` 가 한다. 그래서 자유 조건식을 열 때
바뀌는 것은 나무를 직접 받는 문과 편집 화면뿐이다(받은 결정 3 — 지금은 틀, 지향점은 자유 조건식).

여덟째 종류 `custom`(직접 구성 — 자유 조건식 설계 §4)은 틀이 아니다: 매개변수가 ★나무 셋 그 자체★다. 틀과 같은 두 함수
(`resolve` · `build`)를 지나므로 문 · 시행 기록 · 가동 · 관제가 규칙을 읽는 길은 그대로 하나다.

★도구는 규칙을 추천하지 않는다.★ 틀과 매개변수 · 조건은 사용자가 고르고 짓는다. 기본값은 화면의 출발점일 뿐이고 "좋은 값"이라는 뜻이 아니다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import expr, indicators
from .simulator import RuleSpec

#: 직접 구성한 규칙의 종류 이름.
CUSTOM = "custom"
#: 나무가 놓이는 자리 셋 — (열쇠, 값의 종류, 이름표, 종류가 틀렸을 때의 사유 · 시뮬레이터의 검사가 내는 것과 같은 코드).
SLOTS = (("entry", "bool", "진입 조건", "entry_not_a_condition"),
         ("entry_stop", "number", "미리 건 매수 가격", "entry_stop_not_a_price"),
         ("exit", "bool", "청산 조건", "exit_not_a_condition"))


class RuleError(ValueError):
    """모르는 틀 · 모르는 매개변수 · 범위 밖의 값 · 어긋난 나무. `code` 가 사유이고 `slot` 은 어긋난 나무의 자리다(있으면)."""

    def __init__(self, code: str, detail: str = "", slot: str | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.slot = slot


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


# ── 직접 구성(custom) — 매개변수가 나무 셋 ─────────────────────────────────────────────────
_OP_EXTRA = {"held_before": ("bars",), "time_between": ("from", "to")}
_TRIAL_NOTE = ("조건을 변경해 실행할 때마다 시행으로 기록됩니다. 시행 횟수가 늘수록 시행 횟수 보정 관문은 엄격해집니다. "
               "검사는 시행으로 기록되지 않습니다.")
_WARMUP_NOTE = "지표는 그날의 봉으로만 계산합니다. 창이 N봉인 지표는 처음 N봉 동안 값이 없으며, 값이 없는 조건은 충족으로 보지 않습니다."
_ENTRY_RULE = "진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 합니다."
RULE_TEXT_UNREADABLE = "이 설정의 규칙을 지금의 문법으로 읽지 못했습니다."


def _normal(node: dict) -> dict:
    """검사를 지난 마디 → ★하나의 꼴★: 상수는 `float` · 지표는 기본값을 채운 매개변수 · 연산은 아는 열쇠만.

    연산 마디의 모르는 열쇠는 조용히 버리지 않는다(검사기는 그것을 보지 않는다) — 사유와 함께 거절한다."""
    if "const" in node:
        return {"const": float(node["const"])}
    if "ind" in node:
        return {"ind": node["ind"], **indicators.resolve(node["ind"], {k: v for k, v in node.items() if k != "ind"})}
    name = node["op"]
    extra = _OP_EXTRA.get(name, ())
    unknown = sorted(set(node) - {"op", "args", *extra})
    if unknown:
        raise RuleError("unknown_key", f"{name}: {unknown}")
    return {"op": name, "args": [_normal(arg) for arg in node.get("args", [])], **{key: node[key] for key in extra}}


def _resolve_custom(params: dict | None) -> dict:
    """나무 셋을 검사하고 하나의 꼴로 — 빈 자리는 뺀다. 마디 수는 ★셋을 합쳐★ 상한을 본다."""
    given = dict(params or {})
    extra = set(given) - {key for key, *_ in SLOTS}
    if extra:
        raise RuleError("unknown_param", f"{CUSTOM}: {sorted(extra)}")
    out: dict = {}
    nodes = 0
    for key, wanted, _, wrong in SLOTS:
        tree = given.get(key)
        if tree is None:
            continue
        try:
            got = expr.validate(tree)
        except expr.ExprError as err:
            raise RuleError(err.code, err.detail, slot=key) from None
        except OverflowError:                                    # 실수로 옮길 수 없는 큰 정수 — 검사기의 유한성 검사가 던진다
            raise RuleError("bad_const", "너무 큰 수", slot=key) from None
        if got != wanted:
            raise RuleError(wrong, slot=key)
        try:
            out[key] = _normal(tree)
        except RuleError as err:
            raise RuleError(err.code, err.detail, slot=key) from None
        nodes += expr.size(tree)[0]
    if "entry" not in out and "entry_stop" not in out:
        raise RuleError("no_entry")
    if nodes > expr.MAX_NODES:
        raise RuleError("too_many_nodes", f"{nodes} > {expr.MAX_NODES}")
    return out


def as_custom(spec: RuleSpec) -> dict:
    """나무 셋(틀이 만든 것 포함) → `custom` 의 매개변수(하나의 꼴). '틀에서 출발하기'가 이것이다."""
    return _resolve_custom({key: getattr(spec, key) for key, *_ in SLOTS})


def resolve(kind: str, params: dict | None = None) -> dict:
    """매개변수를 검사하고 기본값을 채운 ★하나의 꼴★ — 같은 설정은 늘 같은 사전이 된다(시행 횟수 기록이 이것으로 가른다)."""
    if kind == CUSTOM:
        return _resolve_custom(params)
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
    """틀과 매개변수 → 나무 셋. `custom` 이면 받은 나무 셋(하나의 꼴)이 그대로 규칙이다."""
    if kind == CUSTOM:
        return RuleSpec(**resolve(kind, params))
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
                    "notes": list(t.notes), "custom": False})
    # 여덟째 — 매개변수 칸이 없다(나무를 짓는다). 전일 값이 필요한지는 조건에 따라 달라 미리 말하지 않는다(`None`).
    out.append({"kind": CUSTOM, "label": "직접 구성", "summary": "진입 조건, 미리 건 매수 가격, 청산 조건을 지표와 연산으로 직접 구성합니다.",
                "needs_prev": None, "params": [], "notes": [_TRIAL_NOTE, _WARMUP_NOTE], "custom": True})
    return out


def grammar() -> dict:
    """화면이 조건을 짓는 데 필요한 것 전부 — 자리 · 지표 · 연산 · 단위 · 상한. ★등록부에서 읽는다★(사본을 두지 않는다)."""
    listed = []
    for name, spec in indicators.INDICATORS.items():
        listed.append({"name": name, "label": spec.label, "unit": spec.unit, "needs_prev": spec.needs_prev,
                       "params": [{"key": key, "label": r.label, "type": "int" if r.integer else "float", "min": r.low,
                                   "max": r.high, "default": r.default, "unit": r.unit} for key, r in spec.params.items()]})
    fields = {"held_before": [{"key": "bars", "label": "직전 봉 수", "type": "int", "min": expr.HELD_BARS[0],
                               "max": expr.HELD_BARS[1], "unit": "봉"}],
              "time_between": [{"key": "from", "label": "시작 시각", "type": "time"}, {"key": "to", "label": "종료 시각", "type": "time"}]}
    ops = []
    for name, (wants, low, high, gives) in expr.shapes().items():
        fixed = low == high
        kinds = ([wants] * low if isinstance(wants, str) else list(wants)) if fixed else []
        ops.append({"name": name, "label": expr.OP_LABELS[name], "symbol": expr.OP_SYMBOLS.get(name), "gives": gives, "args": kinds,
                    "variadic": None if fixed else {"kind": wants, "min": low, "max": high}, "extra": fields.get(name, [])})
    return {"slots": [{"key": key, "label": label, "kind": kind} for key, kind, label, _ in SLOTS], "entry_rule": _ENTRY_RULE,
            "indicators": listed, "ops": ops, "units": dict(indicators.UNITS),
            "limits": {"nodes": expr.MAX_NODES, "depth": expr.MAX_DEPTH}}


# ── 규칙의 글 — 조건 줄과 같은 순서(좌변 · 연산 · 우변)로 한 줄 ─────────────────────────────────
def _fmt(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _number_text(node: dict, top: bool = False) -> str:
    if "const" in node:
        return _fmt(node["const"])
    if "ind" in node:
        spec = indicators.INDICATORS[node["ind"]]
        params = indicators.resolve(node["ind"], {k: v for k, v in node.items() if k != "ind"})
        shown = ", ".join(f"{_fmt(params[key])}{r.unit}" for key, r in spec.params.items())
        return f"{spec.label}({shown})" if shown else spec.label
    name, args = node["op"], node["args"]
    if name == "where":
        body = f"{_judge_text(args[0], inner=True)} 충족 시 {_number_text(args[1])}"
    else:
        body = f"{_number_text(args[0])} {expr.OP_SYMBOLS[name]} {_number_text(args[1])}"
    return body if top else f"({body})"                          # 안쪽의 계산은 늘 괄호 — 다른 나무가 같은 글이 되지 않게


def _judge_text(node: dict, inner: bool = False) -> str:
    name, args = node["op"], node.get("args", [])
    if name == "time_between":
        return f"시각 {node['from'][:2]}:{node['from'][2:]}~{node['to'][:2]}:{node['to'][2:]}"
    if name in ("and", "or"):
        joined = (" 그리고 " if name == "and" else " 또는 ").join(_judge_text(arg, inner=True) for arg in args)
        return f"({joined})" if inner else joined                # 안쪽 묶음은 괄호
    if name == "not":
        return f"아님({_judge_text(args[0])})"
    if name == "held_before":
        return f"직전 {node['bars']}봉 동안({_judge_text(args[0])})"
    word = expr.OP_SYMBOLS.get(name) or expr.OP_LABELS[name]     # 비교는 기호 · 돌파는 이름표
    return f"{_number_text(args[0])} {word} {_number_text(args[1])}"


def text_of(spec: RuleSpec) -> str:
    """규칙의 글(한 줄) — 목록 · 가동 줄 · 캔버스가 같은 글을 쓴다. 검사를 지난 나무에만 쓴다."""
    parts = []
    for key, kind, label, _ in SLOTS:
        tree = getattr(spec, key)
        if tree is not None:
            parts.append(f"{label}: {_judge_text(tree) if kind == 'bool' else _number_text(tree, top=True)}")
    return " · ".join(parts)


def notes_of(spec: RuleSpec) -> list[str]:
    """그 나무들이 알아야 할 것 — 덥혀지지 않은 지표(늘) · 전일 값(쓰는 지표가 있을 때)."""
    uses_prev = any(expr.uses_prev(tree) for tree in (spec.entry, spec.entry_stop, spec.exit) if tree is not None)
    return [_WARMUP_NOTE, *([_PREV_NOTE] if uses_prev else [])]


def rule_text(rule: Any) -> dict:
    """저장된 규칙(`{"kind", "params"}`) → 글. 지금의 문법으로 읽히지 않으면 글은 `None` 이고 사유가 붙는다(종류 이름으로 때우지 않는다)."""
    try:
        return {"rule_text": text_of(build(rule["kind"], rule["params"])), "rule_text_reason": None}
    except (ValueError, KeyError, TypeError):                    # 엔진의 거절(`RuleError` · `ExprError` 는 ValueError) · 깨진 사본
        return {"rule_text": None, "rule_text_reason": RULE_TEXT_UNREADABLE}
