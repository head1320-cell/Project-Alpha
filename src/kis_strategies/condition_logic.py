# 대상 경로: src/kis_strategies/condition_logic.py
#
# 논리 조건식 (젠포트 가이드 "논리 연산 및 팩터 함수" 시트의 논리 레이어).
#
#   조건에 위치 기반 라벨 A, B, C…를 붙이고 자유 결합:
#     논리연산자  : and / or / not(A) (또는 not A)
#     논리 함수   : before(A,n)  n거래일 전 성립
#                   any(A,n)     n거래일 이내 한번이라도 성립 (당일 포함)
#                   every(A,n)   n거래일 동안 매일 성립 (당일 포함)
#   예: every(A,3) and (B or C),  not(any(A,5)) and B
#
# 평가는 Kleene 3치 논리 — 각 조건은 봉마다 {1=충족, 0=불충족, 0.5=평가불가}.
#   and=min, or=max, not=1-x.  every=rolling min, any=rolling max, before=shift
#   (워밍업·결측은 0.5).  최종 액션은 식 값이 정확히 1일 때만 발동 —
#   평가 불가가 결과를 좌우하면 보류(미지(未知)로는 매매하지 않음).
#
# 젠포트 대비 확장: 가이드 Tip 4는 before/any/every의 상호 중첩을 금지하고 과거값
# 우회를 안내하지만, 여기서는 합성이 자연스러우므로 중첩 허용(상위 호환) —
# before(every(A,2),1) == 가이드의 과거값 우회 패턴과 동일 의미.
#
# 문자열 파싱이지만 eval/exec 없음 — 토큰 6종 키워드 + 라벨 + 괄호 + 정수의
# 재귀 하강 파서(결정적, 입력 길이 제한).

from __future__ import annotations

import re

import numpy as np
import pandas as pd

_KEYWORDS = {"and", "or", "not", "before", "any", "every"}
_QUANTS = {"before", "any", "every"}
_TOKEN_RE = re.compile(r"\s*([A-Za-z]+|\d+|\(|\)|,)")
_MAX_TOKENS = 200
_MAX_PERIOD = 500


def _tokenize(expr: str) -> list[str]:
    out, pos = [], 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            rest = expr[pos:].strip()
            raise ValueError(f"해석할 수 없는 문자: '{rest[:10]}'")
        tok = m.group(1)
        out.append(tok)
        pos = m.end()
        if len(out) > _MAX_TOKENS:
            raise ValueError("논리 조건식이 너무 깁니다")
    return out


def parse_logic(expr: str, n_conditions: int) -> tuple:
    """논리 조건식 → AST. 문법·라벨 오류는 ValueError(한국어 메시지).

    AST 노드: ("label", idx) | ("not", x) | ("and", l, r) | ("or", l, r)
              | ("before"|"any"|"every", x, n)
    """
    toks = _tokenize(expr or "")
    if not toks:
        raise ValueError("논리 조건식이 비어 있습니다")
    pos = [0]

    def peek() -> str | None:
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take() -> str | None:
        t = peek()
        if t is not None:
            pos[0] += 1
        return t

    def expect(t: str, what: str):
        if take() != t:
            raise ValueError(what)

    def parse_or() -> tuple:
        node = parse_and()
        while peek() is not None and peek().lower() == "or":
            take()
            if peek() is None:
                raise ValueError("'or' 뒤에 조건이 필요합니다")
            node = ("or", node, parse_and())
        return node

    def parse_and() -> tuple:
        node = parse_unary()
        while peek() is not None and peek().lower() == "and":
            take()
            if peek() is None:
                raise ValueError("'and' 뒤에 조건이 필요합니다")
            node = ("and", node, parse_unary())
        return node

    def parse_unary() -> tuple:
        t = peek()
        if t is None:
            raise ValueError("조건이 필요합니다")
        low = t.lower()
        if low == "not":
            take()
            return ("not", parse_unary())
        if low in _QUANTS:
            take()
            expect("(", f"{low}(조건, 기간) 형식이어야 합니다 — 예: {low}(A, 3)")
            inner = parse_or()
            expect(",", f"{low}(조건, 기간) 형식이어야 합니다 — 쉼표 뒤에 기간을 넣어 주세요")
            n_tok = take()
            if n_tok is None or not n_tok.isdigit():
                raise ValueError(f"{low}의 기간은 정수여야 합니다 — 예: {low}(A, 3)")
            n = int(n_tok)
            if not (1 <= n <= _MAX_PERIOD):
                raise ValueError(f"기간은 1~{_MAX_PERIOD} 사이여야 합니다")
            expect(")", f"{low}(...)의 괄호가 닫히지 않았습니다")
            return (low, inner, n)
        if t == "(":
            take()
            node = parse_or()
            expect(")", "여는 괄호가 닫히지 않았습니다")
            return node
        if len(t) == 1 and t.isalpha():
            take()
            idx = ord(t.upper()) - 65
            if idx >= n_conditions:
                have = f"A~{chr(64 + n_conditions)}" if n_conditions > 0 else "없음"
                raise ValueError(
                    f"조건 {t.upper()}이(가) 없습니다 — 사용 가능한 조건: {have}")
            return ("label", idx)
        raise ValueError(
            f"알 수 없는 키워드 '{t}' — and/or/not/before/any/every와 조건 라벨(A~Z)만 사용할 수 있습니다")

    ast = parse_or()
    if peek() is not None:
        raise ValueError(f"식 끝에 해석할 수 없는 부분이 남았습니다: '{' '.join(toks[pos[0]:])}'")
    return ast


def max_lookback(ast: tuple) -> int:
    """시간 한정사가 요구하는 추가 룩백 봉 수 (워밍업 산정용, 보수적)."""
    kind = ast[0]
    if kind == "label":
        return 0
    if kind == "not":
        return max_lookback(ast[1])
    if kind in ("and", "or"):
        return max(max_lookback(ast[1]), max_lookback(ast[2]))
    return int(ast[2]) + max_lookback(ast[1])  # before/any/every


def eval_logic(ast: tuple, env: list[np.ndarray]) -> np.ndarray:
    """AST를 3치 배열({0, 0.5, 1})로 평가. env[i] = 조건 i의 봉별 3치 배열."""
    kind = ast[0]
    if kind == "label":
        return env[ast[1]]
    if kind == "not":
        return 1.0 - eval_logic(ast[1], env)
    if kind == "and":
        return np.minimum(eval_logic(ast[1], env), eval_logic(ast[2], env))
    if kind == "or":
        return np.maximum(eval_logic(ast[1], env), eval_logic(ast[2], env))
    x = pd.Series(eval_logic(ast[1], env))
    n = int(ast[2])
    if kind == "every":
        out = x.rolling(n).min()
    elif kind == "any":
        out = x.rolling(n).max()
    else:  # before — 정확히 n봉 전의 성립 여부
        out = x.shift(n)
    return out.fillna(0.5).to_numpy()
