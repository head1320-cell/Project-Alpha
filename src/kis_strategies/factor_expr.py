# 대상 경로: src/kis_strategies/factor_expr.py
#
# 자유 산술 팩터식 (젠포트 조건식 좌변) — 가이드 명세 그대로:
#   · 좌변: 사칙연산 +,-,*,/ 와 괄호, 팩터 {토큰}, 함수, 숫자 상수
#   · 인용부호 '...'는 중첩 인자 묶음 (괄호와 동일하게 처리)
#   · 기간 인자 {N일}/{N년}/{N}, 정렬 인자 {내림차순}/{오름차순}
# 예: ({분기영업현금흐름}-{분기순이익}) > 0
#     {종가} / 과거값('최고값({고가},{40일})',{1일}) >= 1.2
#     (1/표준편차({일별주가상승률},{20일}))*100 < 5
#     순위오름차순('{시가총액}*1') <= 30
#
# eval/exec 없음 — 토큰 9종의 재귀 하강 파서(결정적, 길이 제한, 한국어 오류).
# 평가는 ConditionStrategy가 ctx(토큰·횡단면·함수 적용기)를 주입해 수행 —
# 미해석 토큰이 하나라도 있으면 식 전체가 None(해당 봉 건너뜀, 기존 정책).

from __future__ import annotations

import re

import numpy as np
import pandas as pd

_MAX_LEN = 600
_MAX_TOKENS = 250

# 함수명(한·영) → (fn_id, 시그니처) — 시그니처: e=식, n=기간, v=값, d=정렬
_FUNCTIONS: dict[str, tuple[str, str]] = {
    "과거값": ("past", "en"), "past": ("past", "en"),
    "이동평균": ("ma", "en"), "ma": ("ma", "en"),
    "최고값": ("max", "en"), "max": ("max", "en"),
    "최저값": ("min", "en"), "min": ("min", "en"),
    "변화량_기간": ("delta", "en"), "delta": ("delta", "en"),
    "변화율_기간": ("pct", "en"), "pct": ("pct", "en"),
    "기간총합": ("sum", "en"), "sum": ("sum", "en"),
    "표준편차": ("std", "en"), "std": ("std", "en"),
    "평균모멘텀스코어": ("ams", "en"), "ams": ("ams", "en"),
    "절대값": ("abs", "e"), "abs": ("abs", "e"),
    "비교": ("cmp", "ee"), "cmp": ("cmp", "ee"),
    "큰값": ("gt", "ee"), "작은값": ("lt", "ee"),
    "변화율_팩터": ("pctf", "ee"), "pctf": ("pctf", "ee"),
    "큰개수": ("cntgt", "env"), "작은개수": ("cntlt", "env"),
    "순위": ("rank", "ed"), "비율": ("ratio", "ed"),
    "순위내림차순": ("rank", "e:DESC"), "순위오름차순": ("rank", "e:ASC"),
    "비율내림차순": ("ratio", "e:DESC"), "비율오름차순": ("ratio", "e:ASC"),
}
CROSS_FNS = {"rank", "ratio"}

_TOKEN_RE = re.compile(
    r"\s*(\{[^{}]+\}|'|[A-Za-z가-힣_][A-Za-z가-힣_0-9./]*|\d+\.?\d*|[()+\-*/,])")


def _tokenize(text: str) -> list[str]:
    if len(text) > _MAX_LEN:
        raise ValueError("식이 너무 깁니다")
    out, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise ValueError(f"해석할 수 없는 문자: '{text[pos:pos + 8]}'")
        out.append(m.group(1))
        pos = m.end()
        if len(out) > _MAX_TOKENS:
            raise ValueError("식이 너무 깁니다")
    return out


def _brace_kind(tok: str) -> tuple[str, object]:
    """{…} 분류: 기간({20일}/{1년}/{5}) | 정렬 | 팩터 토큰."""
    inner = tok[1:-1].strip()
    if inner in ("내림차순", "DESC"):
        return ("dir", "DESC")
    if inner in ("오름차순", "ASC"):
        return ("dir", "ASC")
    m = re.fullmatch(r"(\d+)\s*(일|년|개월)?", inner)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "년":
            n *= 252       # 거래일 환산 (가격 시계열 기준 — 재무 스냅샷엔 의미 제한)
        elif unit == "개월":
            n *= 21
        return ("period", n)
    return ("token", inner)


def parse_expr(text: str) -> tuple:
    """산술 팩터식 → AST.

    노드: ("num", x) | ("token", 이름) | ("neg", x) | ("bin", "+|-|*|/", l, r)
          | ("call", fn_id, [식 인자들], {"n":…, "v":…, "dir":…})"""
    toks = _tokenize(text or "")
    if not toks:
        raise ValueError("식이 비어 있습니다")
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        t = peek()
        if t is not None:
            pos[0] += 1
        return t

    def expect(t: str, what: str):
        if take() != t:
            raise ValueError(what)

    def parse_add() -> tuple:
        node = parse_mul()
        while peek() in ("+", "-"):
            op = take()
            node = ("bin", op, node, parse_mul())
        return node

    def parse_mul() -> tuple:
        node = parse_unary()
        while peek() in ("*", "/"):
            op = take()
            node = ("bin", op, node, parse_unary())
        return node

    def parse_unary() -> tuple:
        if peek() == "-":
            take()
            return ("neg", parse_unary())
        return parse_atom()

    def parse_atom() -> tuple:
        t = peek()
        if t is None:
            raise ValueError("식이 끝났습니다 — 피연산자가 필요합니다")
        if t == "(":
            take()
            node = parse_add()
            expect(")", "괄호 ')'가 닫히지 않았습니다")
            return node
        if t == "'":          # 인용부호 — 닫힘까지를 하위 식으로
            take()
            node = parse_add()
            expect("'", "인용부호(')가 닫히지 않았습니다")
            return node
        if re.fullmatch(r"\d+\.?\d*", t):
            take()
            return ("num", float(t))
        if t.startswith("{"):
            take()
            kind, val = _brace_kind(t)
            if kind != "token":
                raise ValueError(f"{t}은(는) 이 위치에 올 수 없습니다 — 기간·정렬은 함수 인자로만 사용")
            return ("token", val)
        if t in _FUNCTIONS:
            take()
            return parse_call(t)
        raise ValueError(f"알 수 없는 이름 '{t}' — 함수명 또는 {{팩터}} 형식이어야 합니다")

    def parse_call(name: str) -> tuple:
        fn_id, sig = _FUNCTIONS[name]
        expect("(", f"{name}(…) 형식이어야 합니다")
        # 인자 수집: 식 | {기간} | {정렬} — 쉼표 구분
        exprs: list[tuple] = []
        params: dict = {}
        fixed_dir = sig.split(":")[1] if ":" in sig else None
        if fixed_dir:
            params["dir"] = fixed_dir
        while True:
            t = peek()
            if t is None:
                raise ValueError(f"{name}(…)의 괄호가 닫히지 않았습니다")
            if t.startswith("{"):
                kind, val = _brace_kind(t)
                if kind == "period":
                    take()
                    if "n" in params:
                        params["v"] = float(val)  # 두 번째 기간형 인자 = 비교값 (가이드 {0} 표기)
                    else:
                        params["n"] = val
                elif kind == "dir":
                    take()
                    params["dir"] = val
                else:
                    exprs.append(parse_add())
            else:
                exprs.append(parse_add())
            nxt = take()
            if nxt == ")":
                break
            if nxt != ",":
                raise ValueError(f"{name}(…) 인자 사이에는 쉼표가 필요합니다")
        return _validate_call(name, fn_id, sig.split(":")[0], exprs, params)

    def _validate_call(name, fn_id, sig, exprs, params) -> tuple:
        need_e = sig.count("e")
        if len(exprs) != need_e:
            raise ValueError(f"{name}은(는) 팩터식 인자 {need_e}개가 필요합니다")
        if "n" in sig and "n" not in params:
            raise ValueError(f"{name}에 기간 인자({{N일}})가 필요합니다 — 예: {name}(…, {{20일}})")
        if "v" in sig:
            # 값 인자: 마지막 식이 숫자 상수면 v로 (큰개수({F},{10일},{0}) 형태는 {0}이 기간으로
            # 들어오므로 두 번째 period를 v로 재해석)
            if "v" not in params:
                if len(exprs) == 2 and exprs[1][0] == "num":
                    params["v"] = exprs.pop(1)[1]
                else:
                    raise ValueError(f"{name}에 비교값 인자가 필요합니다 — 예: {name}({{종가}}, {{10일}}, 0)")
        if "d" in sig and "dir" not in params:
            params["dir"] = "DESC"
        return ("call", fn_id, exprs, params)

    ast = parse_add()
    if peek() is not None:
        raise ValueError(f"식 끝에 해석할 수 없는 부분이 남았습니다: '{' '.join(toks[pos[0]:])}'")
    if not _has_factor(ast):
        raise ValueError("식에 팩터가 없습니다 — {팩터} 토큰을 포함해야 합니다")
    return ast


def _has_factor(ast: tuple) -> bool:
    k = ast[0]
    if k == "token":
        return True
    if k == "num":
        return False
    if k == "neg":
        return _has_factor(ast[1])
    if k == "bin":
        return _has_factor(ast[2]) or _has_factor(ast[3])
    return any(_has_factor(a) for a in ast[2]) or True  # call은 팩터 함수


def expr_tokens(ast: tuple) -> set[str]:
    k = ast[0]
    if k == "token":
        return {ast[1]}
    if k in ("num",):
        return set()
    if k == "neg":
        return expr_tokens(ast[1])
    if k == "bin":
        return expr_tokens(ast[2]) | expr_tokens(ast[3])
    out: set[str] = set()
    for a in ast[2]:
        out |= expr_tokens(a)
    return out


def expr_lookback(ast: tuple) -> int:
    """워밍업 산정 — 중첩 경로의 기간 합 (보수적)."""
    k = ast[0]
    if k in ("token", "num"):
        return 0
    if k == "neg":
        return expr_lookback(ast[1])
    if k == "bin":
        return max(expr_lookback(ast[2]), expr_lookback(ast[3]))
    inner = max((expr_lookback(a) for a in ast[2]), default=0)
    return int(ast[3].get("n", 0)) + inner


def collect_cross(ast: tuple, out: list | None = None) -> list[tuple]:
    """횡단면(순위/비율) 노드 수집 → [(키, fn_id, dir, 내부 AST)] — 패널 사전계산용."""
    if out is None:
        out = []
    k = ast[0]
    if k == "neg":
        collect_cross(ast[1], out)
    elif k == "bin":
        collect_cross(ast[2], out)
        collect_cross(ast[3], out)
    elif k == "call":
        if ast[1] in CROSS_FNS:
            out.append((canonical(ast), ast[1], ast[3].get("dir", "DESC"), ast[2][0]))
        for a in ast[2]:
            collect_cross(a, out)
    return out


def canonical(ast: tuple) -> str:
    """AST의 안정적 문자열 키 (패널 캐시용)."""
    k = ast[0]
    if k == "num":
        return f"#{ast[1]:g}"
    if k == "token":
        return "{" + ast[1] + "}"
    if k == "neg":
        return f"-({canonical(ast[1])})"
    if k == "bin":
        return f"({canonical(ast[2])}{ast[1]}{canonical(ast[3])})"
    params = ast[3]
    ps = ",".join(f"{key}={params[key]}" for key in sorted(params))
    return f"{ast[1]}({','.join(canonical(a) for a in ast[2])};{ps})"


def eval_expr(ast: tuple, ctx: dict):
    """AST 평가 → pd.Series | float | None(미해석 토큰 — 조건 건너뜀).

    ctx: token(이름)→Series|None · cross(키)→Series|None
         · apply(series, fn_id, params)→Series|None · two(s1, s2, fn_id)→Series|None"""
    k = ast[0]
    if k == "num":
        return float(ast[1])
    if k == "token":
        return ctx["token"](ast[1])
    if k == "neg":
        v = eval_expr(ast[1], ctx)
        return None if v is None else -v
    if k == "bin":
        l = eval_expr(ast[2], ctx)
        r = eval_expr(ast[3], ctx)
        if l is None or r is None:
            return None
        op = ast[1]
        with np.errstate(divide="ignore", invalid="ignore"):
            if op == "+":
                out = l + r
            elif op == "-":
                out = l - r
            elif op == "*":
                out = l * r
            else:
                out = l / r
        if isinstance(out, pd.Series):
            out = out.replace([np.inf, -np.inf], np.nan)
        return out
    # call
    fn_id, args, params = ast[1], ast[2], ast[3]
    if fn_id in CROSS_FNS:
        return ctx["cross"](canonical(ast))
    vals = [eval_expr(a, ctx) for a in args]
    if any(v is None for v in vals):
        return None
    if len(vals) == 2:  # 두 피연산자 함수 (cmp/gt/lt/pctf)
        s1, s2 = vals
        if not isinstance(s1, pd.Series) and isinstance(s2, pd.Series):
            s1 = pd.Series(float(s1), index=s2.index)
        if isinstance(s1, pd.Series) and not isinstance(s2, pd.Series):
            s2 = pd.Series(float(s2), index=s1.index)
        if not isinstance(s1, pd.Series):
            return None
        return ctx["two"](s1.astype(float), s2.astype(float), fn_id)
    s = vals[0] if vals else None
    if not isinstance(s, pd.Series):
        return None
    p = {}
    if "n" in params:
        p["n"] = params["n"]
    if "v" in params:
        p["v"] = params["v"]
    return ctx["apply"](s.astype(float), fn_id, p)
