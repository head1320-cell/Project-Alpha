"""
Safe Formula Parser — Screener V2 Milestone 1
==========================================================================
사용자 수식을 안전하게 파싱/평가하는 엔진.

보안 원칙 (코드 인젝션 차단):
  · Python `ast` 모듈로 파싱 → 화이트리스트 노드만 허용
  · eval/exec 절대 사용 안 함
  · 허용: 사칙연산(+, -, *, /), 거듭제곱(**), 괄호, 단항 부호(-), 숫자, 필드명(Name)
  · 금지: 함수 호출, 속성 접근(.), 인덱싱([]), import, lambda, comprehension 등

예시:
  "(per * 0.4) + (pbr * 0.6)"
  "roe_pct / debt_ratio_pct"
  "(gap_score + roe_score + stability_score) / 3"
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)

# 허용 AST 노드 (화이트리스트)
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,        # 이항 연산
    ast.UnaryOp,      # 단항 (-x)
    ast.Num,          # 숫자 (3.8 호환)
    ast.Constant,     # 숫자 (3.8+)
    ast.Name,         # 변수 (필드명)
    ast.Load,
    ast.USub,         # 단항 마이너스
    ast.UAdd,         # 단항 플러스
    # 이항 연산자
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
)

_ALLOWED_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)


class FormulaError(Exception):
    """수식 파싱/평가 오류."""
    pass


def validate_formula(expr: str, allowed_fields: set[str]) -> tuple[bool, str | None, set[str]]:
    """
    수식을 검증하고 사용된 필드명을 추출.

    Returns:
        (is_valid, error_message, used_fields)
    """
    if not expr or not expr.strip():
        return False, "수식이 비어있습니다", set()

    if len(expr) > 500:
        return False, "수식이 너무 깁니다 (최대 500자)", set()

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return False, f"구문 오류: {e.msg}", set()

    used_fields: set[str] = set()

    # 모든 노드 검증
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return False, f"허용되지 않은 연산: {type(node).__name__}", set()

        # 함수 호출/속성 접근 등은 위 화이트리스트에 없으므로 자동 차단됨
        if isinstance(node, ast.Name):
            field_name = node.id
            if field_name not in allowed_fields:
                return False, f"알 수 없는 필드: '{field_name}'", set()
            used_fields.add(field_name)

    if not used_fields:
        return False, "수식에 필드가 하나 이상 필요합니다", set()

    return True, None, used_fields


def safe_eval_formula(expr: str, field_values: dict[str, float | None]) -> float | None:
    """
    검증된 수식을 필드값으로 평가.

    Args:
        expr: 수식 문자열
        field_values: {필드명: 값} — None이면 평가 불가
    Returns:
        계산 결과 (실패 시 None — 0으로 나누기, None 필드 등)
    """
    try:
        tree = ast.parse(expr, mode="eval")
        return _eval_node(tree.body, field_values)
    except (FormulaError, ZeroDivisionError, TypeError, ValueError, OverflowError):
        return None
    except Exception as e:
        logger.debug(f"수식 평가 실패 ({expr}): {e}")
        return None


def _eval_node(node, fv: dict) -> float:
    """AST 노드 재귀 평가 (화이트리스트만)."""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise FormulaError("숫자가 아닌 상수")
        return float(node.value)

    if isinstance(node, ast.Num):  # 3.8 호환
        return float(node.n)

    if isinstance(node, ast.Name):
        val = fv.get(node.id)
        if val is None:
            raise FormulaError(f"필드값 없음: {node.id}")
        return float(val)

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, fv)
        right = _eval_node(node.right, fv)
        op = node.op
        if isinstance(op, ast.Add):  return left + right
        if isinstance(op, ast.Sub):  return left - right
        if isinstance(op, ast.Mult): return left * right
        if isinstance(op, ast.Div):
            if abs(right) < 1e-12:
                raise ZeroDivisionError()
            return left / right
        if isinstance(op, ast.Mod):
            if abs(right) < 1e-12:
                raise ZeroDivisionError()
            return left % right
        if isinstance(op, ast.Pow):
            # 거듭제곱 제한 (과도한 연산 방지)
            if abs(right) > 10:
                raise FormulaError("거듭제곱 지수 과다")
            return left ** right
        raise FormulaError(f"미지원 연산자: {type(op).__name__}")

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, fv)
        if isinstance(node.op, ast.USub): return -operand
        if isinstance(node.op, ast.UAdd): return operand
        raise FormulaError("미지원 단항 연산자")

    raise FormulaError(f"미지원 노드: {type(node).__name__}")


def extract_fields(expr: str) -> set[str]:
    """수식에서 필드명만 추출 (검증 없이)."""
    try:
        tree = ast.parse(expr, mode="eval")
        return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    except SyntaxError:
        return set()
