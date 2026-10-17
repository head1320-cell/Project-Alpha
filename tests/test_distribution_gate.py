"""AE1 — 유통 관문의 계약.

로드맵이 P4 를 막아 둔 이유는 기능이 아니라 **업권**이다:

> 외부 전략을 고객에게 유통하는 것은 기능 문제가 아니라 업권 문제다. (…)
> 이 저장소는 그것을 확인한 적이 없다.

★그 경고가 지금은 산문이고, 산문은 코드가 조용히 지나간다.★ 이 파일은 그것을
**기계가 읽는 관문**으로 바꾼 뒤, 관문이 실제로 닫혀 있는지 고정한다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.distribution_gate import (
    DISTRIBUTION_ALLOWED,
    DISTRIBUTION_BLOCKED,
    LICENSE_FIELDS,
    UNVERIFIED_REASON,
    LicenseRecord,
    distribution_gate,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "distribution_gate.py")


def _complete(**kw) -> LicenseRecord:
    base = dict(authority="운영자가 선언한 기관", license_kind="운영자가 선언한 종류",
                license_no="운영자가 선언한 번호", verified_at="2026-01-01",
                scope="운영자가 선언한 범위")
    return LicenseRecord(**{**base, **kw})


# ── ★핵심★ 기본은 막힘 ───────────────────────────────────────────────────

def test_calling_the_gate_with_nothing_is_blocked():
    """★인자 없이 부르면 언제나 막힌다★ — 이 파일의 단 하나의 불변식."""
    out = distribution_gate()
    assert out["state"] == DISTRIBUTION_BLOCKED
    assert out["state"] != DISTRIBUTION_ALLOWED


def test_the_block_reason_names_the_licensing_question_and_who_must_answer():
    out = distribution_gate()
    assert out["reason"] == UNVERIFIED_REASON
    assert "업권" in UNVERIFIED_REASON
    assert "운영자" in UNVERIFIED_REASON


def test_an_explicit_none_is_the_same_as_nothing():
    assert distribution_gate(None)["state"] == DISTRIBUTION_BLOCKED


# ── ★짝★ 완전한 기록이면 열린다 (항상-blocked 배제) ──────────────────────

def test_a_complete_license_record_opens_the_gate():
    out = distribution_gate(_complete())
    assert out["state"] == DISTRIBUTION_ALLOWED
    assert out["missing"] == []


def test_the_open_gate_reports_which_record_it_used():
    """★어느 인가로 열었는지★ — 나중에 '무슨 근거로 유통했나' 를 물을 수 있어야 한다."""
    out = distribution_gate(_complete(license_no="ABC-123"))
    assert out["license"]["license_no"] == "ABC-123"
    assert out["license"]["verified_at"] == "2026-01-01"


# ── 부분 기록은 막힘 + ★무엇이 빠졌는지★ ────────────────────────────────

@pytest.mark.parametrize("field", LICENSE_FIELDS)
def test_a_record_missing_any_single_field_stays_blocked(field):
    """★전수★ — 다섯 필드 중 하나만 비어도 막힌다."""
    out = distribution_gate(_complete(**{field: None}))
    assert out["state"] == DISTRIBUTION_BLOCKED
    assert field in out["missing"]


@pytest.mark.parametrize("field", LICENSE_FIELDS)
def test_the_blocked_reason_names_the_missing_field(field):
    out = distribution_gate(_complete(**{field: None}))
    assert field in out["reason"], out["reason"]


def test_a_blank_string_counts_as_missing():
    """공백만 넣어 관문을 여는 길을 막는다."""
    out = distribution_gate(_complete(authority="   "))
    assert out["state"] == DISTRIBUTION_BLOCKED
    assert "authority" in out["missing"]


def test_an_empty_record_lists_every_field_as_missing():
    out = distribution_gate(LicenseRecord())
    assert set(out["missing"]) == set(LICENSE_FIELDS)


def test_a_complete_record_lists_nothing_as_missing():
    """★짝★ — 언제나 missing 을 채우는 구현을 배제한다."""
    assert distribution_gate(_complete())["missing"] == []


# ── ★인가를 저장소에 체크인하지 않았다★ ────────────────────────────────

def test_no_license_record_is_baked_into_the_source():
    """★전수★ — 소스 어디에도 완성된 `LicenseRecord(...)` 리터럴이 없다.

    있으면 이 저장소가 "우리는 인가가 있다" 고 **주장**하는 것이고, 그것은
    확인된 적이 없는 사실이다(AD 의 법규 수치와 같은 규율).
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "LicenseRecord":
                continue
            filled = [kw for kw in node.keywords
                      if isinstance(kw.value, ast.Constant) and kw.value.value]
            if filled or node.args:
                offenders.append(f"{path}: {ast.unparse(node)[:80]}")
    assert not offenders, f"소스에 인가 기록이 박혀 있다: {offenders}"


def test_no_environment_variable_can_open_the_gate():
    """★플래그 하나로 업권 관문이 열리면 그것은 관문이 아니다★.

    `os.getenv("DISTRIBUTION_...")` 류가 이 모듈에 없어야 한다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert name not in {"getenv", "environ"}, "관문이 환경변수를 읽는다"
    assert "os.environ" not in _MODULE.read_text(encoding="utf-8")


def test_the_gate_ignores_a_forged_state_field():
    """기록에 `state` 를 끼워 넣어도 관문 판정을 덮어쓰지 못한다."""
    assert not hasattr(LicenseRecord(), "state")


# ── 타입 ────────────────────────────────────────────────────────────────────

def test_the_license_record_is_immutable():
    rec = _complete()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.authority = "다른 기관"  # type: ignore[misc]


def test_the_five_fields_are_the_contract():
    assert set(LICENSE_FIELDS) == {"authority", "license_kind", "license_no",
                                   "verified_at", "scope"}
    assert set(LICENSE_FIELDS) == {f.name for f in dataclasses.fields(LicenseRecord)}


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "src.database", "src.data"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"
