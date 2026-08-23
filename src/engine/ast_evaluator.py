"""
AST Rule Evaluator — Enterprise Grade
=======================================
Condition 노드의 연산자/비교값을 안전하게 평가하여
DataFrame Boolean Mask를 생성합니다.

보안: eval() 절대 사용 금지.
방법: Python 내장 operator 모듈 + pandas 벡터화 연산.

사용법:
    mask = evaluate_condition(series, operator=">", value=70)
    mask = evaluate_crossover(series_a, series_b, direction="above")
    mask = combine_masks([mask1, mask2], logic="AND")
"""

from __future__ import annotations

import operator as op
from typing import Union

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Operator Registry — eval() 대신 operator 모듈 사용
# ═══════════════════════════════════════════════════════════════════════════════

# 비교 연산자 → Python operator 함수 매핑 (안전)
_COMPARISON_OPS = {
    ">":   op.gt,
    "<":   op.lt,
    ">=":  op.ge,
    "<=":  op.le,
    "==":  op.eq,
    "!=":  op.ne,
}

# 크로스오버 연산자 (별도 처리)
_CROSSOVER_OPS = {"crosses_above", "crosses_below"}

# 전체 유효 연산자 집합
VALID_OPERATORS = set(_COMPARISON_OPS.keys()) | _CROSSOVER_OPS


def validate_operator(operator_str: str) -> None:
    """연산자 유효성 검증. 유효하지 않으면 ValueError."""
    if operator_str not in VALID_OPERATORS:
        raise ValueError(
            f"Invalid operator: '{operator_str}'. "
            f"Valid operators: {sorted(VALID_OPERATORS)}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 단일 조건 평가 — 벡터화 Boolean Mask 생성
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_condition(
    series: pd.Series,
    operator_str: str,
    value: Union[float, pd.Series],
) -> pd.Series:
    """
    시리즈와 값(또는 다른 시리즈)을 비교하여 Boolean Mask 생성.

    Args:
        series:       평가 대상 시리즈 (예: RSI 값)
        operator_str: 비교 연산자 (">", "<", ">=", "<=", "==", "!=",
                      "crosses_above", "crosses_below")
        value:        비교 기준값 (float) 또는 다른 시리즈

    Returns:
        pd.Series[bool] — True인 행에서 조건 충족

    Raises:
        ValueError: 유효하지 않은 연산자
        TypeError:  시리즈가 아닌 입력
    """
    validate_operator(operator_str)

    if not isinstance(series, pd.Series):
        raise TypeError(f"Expected pd.Series, got {type(series)}")

    # NaN 안전 처리 — NaN이 포함된 행은 항상 False
    safe_series = series.fillna(np.nan)

    # ── 크로스오버 연산자 ──────────────────────────────────────────
    if operator_str == "crosses_above":
        return _crossover(safe_series, value, direction="above")
    elif operator_str == "crosses_below":
        return _crossover(safe_series, value, direction="below")

    # ── 비교 연산자 (벡터화) ──────────────────────────────────────
    op_func = _COMPARISON_OPS[operator_str]

    if isinstance(value, pd.Series):
        # 두 시리즈 비교 — 인덱스 정렬 후 벡터화
        aligned_series, aligned_value = safe_series.align(value.fillna(np.nan))
        result = op_func(aligned_series, aligned_value)
    else:
        # 시리즈 vs 스칼라 — 순수 벡터화
        result = op_func(safe_series, float(value))

    # NaN 전파 방지 — NaN이 있던 위치는 False
    return result.fillna(False).astype(bool)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 크로스오버 감지 — 벡터화 구현
# ═══════════════════════════════════════════════════════════════════════════════

def _crossover(
    series: pd.Series,
    threshold: Union[float, pd.Series],
    direction: str,
) -> pd.Series:
    """
    크로스오버/크로스언더 감지.

    crosses_above: 이전 봉에서 threshold 이하 → 현재 봉에서 초과
    crosses_below: 이전 봉에서 threshold 이상 → 현재 봉에서 미만

    100% 벡터화 — for 루프 없음.
    """
    if isinstance(threshold, pd.Series):
        prev_series = series.shift(1)
        prev_threshold = threshold.shift(1)
    else:
        prev_series = series.shift(1)
        prev_threshold = float(threshold)

    if direction == "above":
        # 이전: series <= threshold AND 현재: series > threshold
        was_below = prev_series <= prev_threshold
        is_above  = series > threshold
        return (was_below & is_above).fillna(False).astype(bool)

    elif direction == "below":
        # 이전: series >= threshold AND 현재: series < threshold
        was_above = prev_series >= prev_threshold
        is_below  = series < threshold
        return (was_above & is_below).fillna(False).astype(bool)

    raise ValueError(f"Invalid crossover direction: '{direction}'")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 복합 조건 결합 — AND / OR
# ═══════════════════════════════════════════════════════════════════════════════

def combine_masks(
    masks: list[pd.Series],
    logic: str = "AND",
) -> pd.Series:
    """
    여러 Boolean Mask를 AND/OR로 결합.

    Args:
        masks:  Boolean Series 리스트
        logic:  "AND" 또는 "OR"

    Returns:
        결합된 pd.Series[bool]
    """
    if not masks:
        raise ValueError("Empty mask list")

    if len(masks) == 1:
        return masks[0].fillna(False).astype(bool)

    if logic == "AND":
        result = masks[0]
        for m in masks[1:]:
            result = result & m
    elif logic == "OR":
        result = masks[0]
        for m in masks[1:]:
            result = result | m
    else:
        raise ValueError(f"Invalid logic: '{logic}'. Must be 'AND' or 'OR'.")

    return result.fillna(False).astype(bool)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 지표별 기본 임계값 — 조건 노드 없이 직접 연결 시 사용
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_THRESHOLDS = {
    "rsi":   {"buy_op": "<",  "buy_val": 30,   "sell_op": ">",  "sell_val": 70},
    "stoch": {"buy_op": "<",  "buy_val": 20,   "sell_op": ">",  "sell_val": 80},
    "cci":   {"buy_op": "<",  "buy_val": -100, "sell_op": ">",  "sell_val": 100},
    "mfi":   {"buy_op": "<",  "buy_val": 20,   "sell_op": ">",  "sell_val": 80},
    "adx":   {"buy_op": ">",  "buy_val": 25,   "sell_op": "<",  "sell_val": 20},
}


def get_default_masks(
    indicator_id: str,
    series: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """
    지표 기본 임계값으로 매수/매도 마스크 생성.

    Returns:
        (buy_mask, sell_mask) — 조건 노드 없이 직접 연결 시 사용
    """
    thresholds = DEFAULT_THRESHOLDS.get(indicator_id)

    if thresholds is None:
        # 기본 임계값 없는 지표 (SMA, EMA 등) → 빈 마스크
        empty = pd.Series(False, index=series.index)
        return empty, empty

    buy_mask  = evaluate_condition(series, thresholds["buy_op"],  thresholds["buy_val"])
    sell_mask = evaluate_condition(series, thresholds["sell_op"], thresholds["sell_val"])

    return buy_mask, sell_mask
