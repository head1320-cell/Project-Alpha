"""표현식 나무 — 지표와 상수를 엮어 봉마다 참/거짓(또는 수)을 낸다 (분봉 백테스트 설계 §7.1).

    잎    {"ind": "sma", "n": 20}   {"const": 30}
    수    {"op": "add" | "sub" | "mul", "args": [수, 수]}     {"op": "where", "args": [참거짓, 수]}
    판단  {"op": "gt" | "ge" | "lt" | "le", "args": [수, 수]}      {"op": "cross_up" | "cross_down", "args": [수, 수]}
          {"op": "and" | "or", "args": [판단, 판단, …]}            {"op": "not", "args": [판단]}
          {"op": "held_before", "bars": M, "args": [판단]}          {"op": "time_between", "from": "0900", "to": "1500"}

규칙 틀 일곱은 이 나무를 만드는 함수이고 시뮬레이터는 나무만 본다 — 자유 조건식을 열 때 바뀌는 것은 이 나무를 직접 받는
문과 편집 화면뿐이다.

★모르는 값이 낀 판단은 참이 되지 않는다.★ 판단은 (값, 아는가) 두 줄로 계산한다 — 덥혀지지 않은 지표와의 비교는 '모름'이고,
`not` 으로 뒤집어도 모름이 남는다. `and`·`or` 는 세 값 논리다 — 한쪽이 거짓인 `and` 는 거짓이고 한쪽이 참인 `or` 는 참이며
(아는 쪽만으로 답이 정해진다), 그 밖에 모름이 끼면 모름이다. 모름을 거짓으로 바꾸는 자리는 ★끝★뿐이다(`evaluate` · `where` · `held_before`). 그러지 않으면 `not(종가 > 평균)` 이
평균이 아직 없는 첫 봉들에서 참이 되어 진입 신호가 난다.

인과성: 잎은 인과 지표이고(`indicators`), `cross_*` 는 앞 봉과 이 봉만, `held_before` 는 앞 봉들만 본다 — 나무 전체가 인과다.
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from . import indicators
from .types import Session

MAX_DEPTH = 12
MAX_NODES = 64

_ARITH = {"add": np.add, "sub": np.subtract, "mul": np.multiply}
_COMPARE = {"gt": np.greater, "ge": np.greater_equal, "lt": np.less, "le": np.less_equal}
_CROSS = ("cross_up", "cross_down")
_LOGIC = ("and", "or")
#: 연산 → (인자의 종류, 인자 수의 하한·상한, 결과의 종류)
_SHAPES: dict[str, tuple[tuple[str, ...] | str, int, int, str]] = {
    **{name: ("number", 2, 2, "number") for name in _ARITH},
    **{name: ("number", 2, 2, "bool") for name in (*_COMPARE, *_CROSS)},
    **{name: ("bool", 2, MAX_NODES, "bool") for name in _LOGIC},
    "not": ("bool", 1, 1, "bool"),
    "held_before": ("bool", 1, 1, "bool"),
    "where": (("bool", "number"), 2, 2, "number"),
    "time_between": ("number", 0, 0, "bool"),
}


class ExprError(ValueError):
    """어긋난 나무. `code` 가 사유다 — 조용히 거짓으로 평가하지 않는다."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _hhmm(value: Any) -> str:
    if not (isinstance(value, str) and len(value) == 4 and value.isdigit() and int(value[:2]) < 24 and int(value[2:]) < 60):
        raise ExprError("bad_time", repr(value))
    return value


def _check(node: Any, depth: int, count: list[int]) -> str:
    count[0] += 1
    if count[0] > MAX_NODES:
        raise ExprError("too_many_nodes", str(MAX_NODES))
    if depth > MAX_DEPTH:
        raise ExprError("too_deep", str(MAX_DEPTH))
    if not isinstance(node, dict) or sum(k in node for k in ("ind", "const", "op")) != 1:
        raise ExprError("not_a_node", repr(node)[:80])
    if "const" in node:
        value = node["const"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or len(node) != 1:
            raise ExprError("bad_const", repr(node)[:80])
        return "number"
    if "ind" in node:
        try:
            indicators.resolve(node["ind"], {k: v for k, v in node.items() if k != "ind"})
        except indicators.IndicatorError as err:
            raise ExprError(err.code, err.detail) from None
        return "number"
    name = node["op"]
    if name not in _SHAPES:
        raise ExprError("unknown_op", repr(name))
    wants, low, high, gives = _SHAPES[name]
    args = node.get("args", [])
    if not isinstance(args, list) or not low <= len(args) <= high:
        raise ExprError("wrong_arity", f"{name}: {len(args) if isinstance(args, list) else args!r}")
    kinds = [_check(arg, depth + 1, count) for arg in args]
    expected = [wants] * len(args) if isinstance(wants, str) else list(wants)
    if kinds != expected:
        raise ExprError("wrong_kind", f"{name}: {kinds} (필요: {expected})")
    if name == "held_before":
        bars = node.get("bars")
        if isinstance(bars, bool) or not isinstance(bars, int) or not 1 <= bars <= 240:
            raise ExprError("bad_bars", repr(bars))
    if name == "time_between" and not _hhmm(node.get("from")) <= _hhmm(node.get("to")):
        raise ExprError("bad_time", f"{node.get('from')} > {node.get('to')}")
    return gives


def validate(tree: Any) -> str:
    """나무를 검사하고 그것이 내는 값의 종류(`"bool"` · `"number"`)를 돌려준다. 어긋나면 `ExprError`."""
    return _check(tree, 1, [0])


def canonical(tree: Any) -> str:
    """같은 나무는 같은 글 — 열쇠 순서와 무관하다(시행 횟수 기록이 설정을 가르는 데 쓴다)."""
    return json.dumps(tree, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def uses_prev(tree: Any) -> bool:
    """전일 값을 쓰는 지표가 나무 어디엔가 있는가."""
    if not isinstance(tree, dict):
        return False
    if "ind" in tree:
        spec = indicators.INDICATORS.get(tree["ind"])
        return bool(spec and spec.needs_prev)
    return any(uses_prev(arg) for arg in tree.get("args", []))


def _number(node: dict, s: Session, cache: dict) -> np.ndarray:
    if "const" in node:
        return np.full(len(s.close), float(node["const"]))
    if "ind" in node:
        key = canonical(node)
        if key not in cache:
            cache[key] = indicators.compute(s, node["ind"], {k: v for k, v in node.items() if k != "ind"})
        return cache[key]
    name, args = node["op"], node["args"]
    if name == "where":
        value, known = _judge(args[0], s, cache)
        return np.where(value & known, _number(args[1], s, cache), np.nan)
    return _ARITH[name](_number(args[0], s, cache), _number(args[1], s, cache))


def _judge(node: dict, s: Session, cache: dict) -> tuple[np.ndarray, np.ndarray]:
    """(값, 아는가)."""
    name, args, n = node["op"], node.get("args", []), len(s.close)
    if name == "time_between":
        hhmm = np.array([t[:4] for t in s.time], dtype=object) if n else np.array([], dtype=object)
        return (hhmm >= node["from"]) & (hhmm <= node["to"]) if n else np.zeros(0, bool), np.ones(n, bool)
    if name in _COMPARE or name in _CROSS:
        a, b = _number(args[0], s, cache), _number(args[1], s, cache)
        known = ~(np.isnan(a) | np.isnan(b))
        with np.errstate(invalid="ignore"):
            if name in _COMPARE:
                return _COMPARE[name](a, b), known
            above, below = (a > b), (a <= b)
            if name == "cross_down":
                above, below = (a < b), (a >= b)
        value, both = np.zeros(n, bool), np.zeros(n, bool)
        value[1:] = above[1:] & below[:-1]
        both[1:] = known[1:] & known[:-1]
        return value, both
    parts = [_judge(arg, s, cache) for arg in args]
    if name == "not":
        value, known = parts[0]
        return ~value, known
    if name == "held_before":
        value, known = parts[0]
        bars, held, sure = node["bars"], np.zeros(n, bool), np.zeros(n, bool)
        for i in range(bars, n):
            sure[i] = known[i - bars:i].all()
            held[i] = sure[i] and value[i - bars:i].all()
        return held, sure
    # 세 값 논리 — 아는 쪽만으로 답이 정해지면 모름이 그 답을 흐리지 않는다.
    all_known = np.logical_and.reduce([k for _, k in parts])
    if name == "and":
        any_false = np.logical_or.reduce([k & ~v for v, k in parts])        # 한쪽이 거짓이면 거짓
        return np.logical_and.reduce([v & k for v, k in parts]), all_known | any_false
    any_true = np.logical_or.reduce([v & k for v, k in parts])              # 한쪽이 참이면 참
    return any_true, all_known | any_true


def evaluate(tree: Any, session: Session, cache: dict | None = None) -> np.ndarray:
    """나무를 한 종목의 하루에 대해 계산한다 — 판단이면 `bool` 배열(모름은 거짓), 수면 `float` 배열(모름은 NaN)."""
    kind = validate(tree)
    cache = {} if cache is None else cache
    if kind == "number":
        return _number(tree, session, cache)
    value, known = _judge(tree, session, cache)
    return value & known
