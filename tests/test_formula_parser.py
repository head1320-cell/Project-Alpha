"""사용자 정의 수식 조건(`kind="formula"`)의 파서 — ★임포트되고 · 계산하고 · 위험한 식을 거절한다★ (2026-11-13).

이 모듈은 시험이 없었다. 허용 노드 표에 `ast.Num`(파이썬 3.12 에서 제거)이 남아 있어, 런타임을 3.14 로 올린 뒤로
★임포트 자체가 실패★했다 — 수식 조건이 든 요청은 검증 단계에서 예외로 죽었다(뭉뚱그린 500). 과거 시점 스크리닝의
조건 검사(`tests/test_pit_asof_block.py`)가 수식 속 필드를 읽으려다 찾았다.
"""
from __future__ import annotations

import pytest

FIELDS = {"per", "pbr", "roe_pct"}


def test_the_module_imports_on_this_runtime():
    import src.engine.formula_parser as fp
    assert callable(fp.validate_formula) and callable(fp.safe_eval_formula) and callable(fp.extract_fields)


def test_a_valid_formula_validates_and_evaluates():
    from src.engine.formula_parser import extract_fields, safe_eval_formula, validate_formula
    ok, err, used = validate_formula("(per*0.4)+(pbr*0.6)-1", FIELDS)
    assert ok and err is None and used == {"per", "pbr"}
    assert safe_eval_formula("(per*0.4)+(pbr*0.6)-1", {"per": 10.0, "pbr": 2.0}) == pytest.approx(4.2)
    assert safe_eval_formula("-per/2", {"per": 10.0}) == pytest.approx(-5.0)
    assert extract_fields("(per*0.4)+(roe_pct*0.6)") == {"per", "roe_pct"}


def test_unknown_fields_and_unsafe_expressions_are_refused():
    """★짝★ — 늘 통과시키는 파서가 아니다: 모르는 필드 · 함수 호출 · 속성 접근은 거절한다."""
    from src.engine.formula_parser import validate_formula
    assert validate_formula("per + nope", FIELDS)[0] is False
    assert validate_formula("__import__('os').system('x')", FIELDS)[0] is False
    assert validate_formula("per.__class__", FIELDS)[0] is False
    assert validate_formula("per +", FIELDS)[0] is False


def test_a_missing_value_gives_no_result_not_a_number():
    """값이 없는 필드가 낀 수식은 계산하지 않는다(0 으로 채우지 않는다 — 미상 ≠ 0)."""
    from src.engine.formula_parser import safe_eval_formula
    assert safe_eval_formula("per*2", {"per": None}) is None
    assert safe_eval_formula("per/pbr", {"per": 1.0, "pbr": 0.0}) is None


def test_a_formula_condition_passes_request_validation():
    """요청 검증까지 — 수식 조건이 든 조건 묶음이 검증에서 예외 없이 통과한다(예전엔 여기서 죽었다)."""
    from src.engine.filter_ast import parse_group
    g = parse_group({"logic": "AND", "groups": [], "conditions": [
        {"field": "__formula__", "kind": "formula", "formula": "(per*0.4)+(pbr*0.6)", "op": "lt", "value": 10}]})
    assert g.validate() is None
    bad = parse_group({"logic": "AND", "groups": [], "conditions": [
        {"field": "__formula__", "kind": "formula", "formula": "per + nope", "op": "lt", "value": 10}]})
    assert "수식 오류" in (bad.validate() or "")
