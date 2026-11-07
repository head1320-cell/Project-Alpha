"""BV1 — 실계좌(LIVE) 관문의 계약.

사용자 결정(2026-10-09): 사용자마다 자기 증권 계좌를 연결하고 모의투자/실계좌를 고른다 — ★실계좌도 만든다★.
로드맵 ⑥ "인가 없이 켜지 않는다" 는 그대로 참이어야 한다. 그래서 실계좌 집행 코드는 만들되, ★켜는 것★은
이 관문 뒤에 둔다:

  · 기본은 막힘. 운영자가 확인 기록(근거·확인 기관·번호·확인일·범위)과 ★허용할 사용자 이름★을 전부 선언해야 열린다.
  · 이름 목록인 이유 — 검색 요약(원문 미확인)으로는 KIS 오픈API 로 ★다른 사람에게★ 주문 서비스를 하려면 증권사
    제휴가 필요하고, 본인 계좌는 필요 없다. 운영자가 본인만 열 수 있게, 그리고 남에게 여는 것이 ★기록되는 행위★가
    되게 한다. 와일드카드(`*`)로 모두에게 여는 길은 없다.
  · 환경변수 뒷문 없음 · 완성된 기록을 저장소에 박지 않음(유통 관문 `distribution_gate` 와 같은 규율).
  · ★이 관문은 적법성을 판단하지 않는다★ — "확인된 적이 없다" 와 "운영자가 무엇을 근거로 열었다" 만 말한다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.live_gate import (
    AUTH_FIELDS,
    LIVE_ALLOWED,
    LIVE_BLOCKED,
    UNVERIFIED_LIVE_REASON,
    LiveAuthorization,
    live_gate,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "live_gate.py")


def _complete(**kw) -> LiveAuthorization:
    base = dict(basis="운영자가 선언한 근거", authority="운영자가 선언한 확인 기관",
                reference_no="운영자가 선언한 번호", verified_at="2026-01-01",
                scope="운영자가 선언한 범위", allowed_users=("alice",))
    return LiveAuthorization(**{**base, **kw})


# ── ★핵심★ 기본은 막힘 ───────────────────────────────────────────────────

def test_calling_the_gate_with_nothing_is_blocked():
    out = live_gate()
    assert out["state"] == LIVE_BLOCKED
    assert out["state"] != LIVE_ALLOWED
    assert set(out["missing"]) == set(AUTH_FIELDS)


def test_the_block_reason_says_it_was_never_verified_and_who_must_declare():
    out = live_gate(None, "alice")
    assert out["reason"] == UNVERIFIED_LIVE_REASON
    assert "운영자" in UNVERIFIED_LIVE_REASON
    assert "확인" in UNVERIFIED_LIVE_REASON


# ── ★짝★ 완전한 기록 + 이름이 있으면 열린다 ──────────────────────────────

def test_a_complete_record_opens_the_gate_for_a_listed_user():
    out = live_gate(_complete(), "alice")
    assert out["state"] == LIVE_ALLOWED
    assert out["missing"] == []
    assert out["reason"] is None


def test_the_open_gate_reports_which_record_it_used():
    out = live_gate(_complete(reference_no="REF-7"), "alice")
    assert out["authorization"]["reference_no"] == "REF-7"
    assert out["authorization"]["allowed_users"] == ["alice"]


# ── 이름 목록 — 남에게 여는 것은 기록되는 행위다 ─────────────────────────

def test_a_user_not_on_the_list_stays_blocked():
    out = live_gate(_complete(allowed_users=("alice",)), "bob")
    assert out["state"] == LIVE_BLOCKED
    assert "bob" in out["reason"]


def test_a_user_on_the_list_passes_while_another_does_not():
    """★짝★ — 이름을 보지 않는(늘 열림·늘 막힘) 구현을 배제한다."""
    rec = _complete(allowed_users=("alice", "minji"))
    assert live_gate(rec, "minji")["state"] == LIVE_ALLOWED
    assert live_gate(rec, "alice")["state"] == LIVE_ALLOWED
    assert live_gate(rec, "bob")["state"] == LIVE_BLOCKED


def test_names_match_exactly():
    """대소문자·공백을 맞춰 주지 않는다 — 계정 이름은 그대로 비교한다(`can_read_user` 와 같다)."""
    rec = _complete(allowed_users=("alice",))
    assert live_gate(rec, "Alice")["state"] == LIVE_BLOCKED
    assert live_gate(rec, " alice")["state"] == LIVE_BLOCKED


@pytest.mark.parametrize("username", [None, "", "   "])
def test_an_unknown_user_is_blocked(username):
    out = live_gate(_complete(), username)
    assert out["state"] == LIVE_BLOCKED
    assert "누구" in out["reason"]


@pytest.mark.parametrize("users", [("*",), ("alice", "*"), ("all",), ("",), ("  ",), ()])
def test_no_wildcard_or_blank_name_can_open_it_for_everyone(users):
    out = live_gate(_complete(allowed_users=users), "alice")
    assert out["state"] == LIVE_BLOCKED
    assert "allowed_users" in out["missing"]


# ── 부분 기록은 막힘 + ★무엇이 빠졌는지★ ────────────────────────────────

_TEXT_FIELDS = tuple(f for f in AUTH_FIELDS if f != "allowed_users")


@pytest.mark.parametrize("field", _TEXT_FIELDS)
def test_a_record_missing_any_single_field_stays_blocked(field):
    out = live_gate(_complete(**{field: None}), "alice")
    assert out["state"] == LIVE_BLOCKED
    assert field in out["missing"]
    assert field in out["reason"]


@pytest.mark.parametrize("field", _TEXT_FIELDS)
def test_a_blank_string_counts_as_missing(field):
    out = live_gate(_complete(**{field: "   "}), "alice")
    assert out["state"] == LIVE_BLOCKED
    assert field in out["missing"]


def test_a_complete_record_lists_nothing_as_missing():
    """★짝★ — 언제나 missing 을 채우는 구현을 배제한다."""
    assert _complete().missing() == []


# ── ★완성된 기록을 저장소에 박지 않았다 · 환경변수 뒷문 없음★ ──────────────

def test_no_live_authorization_is_baked_into_the_source():
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "LiveAuthorization":
                continue
            filled = [kw for kw in node.keywords
                      if isinstance(kw.value, (ast.Constant, ast.Tuple, ast.List))
                      and not (isinstance(kw.value, ast.Constant) and kw.value.value in (None, ""))]
            if filled or node.args:
                offenders.append(f"{path}: {ast.unparse(node)[:80]}")
    assert not offenders, f"소스에 실계좌 확인 기록이 박혀 있다: {offenders}"


def test_no_environment_variable_can_open_the_gate():
    text = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert name not in {"getenv", "environ"}, "관문이 환경변수를 읽는다"
    assert "os.environ" not in text and "import os" not in text


def test_the_record_cannot_carry_a_forged_state():
    assert not hasattr(LiveAuthorization(), "state")


# ── 타입 · 순수성 ─────────────────────────────────────────────────────────

def test_the_record_is_immutable():
    rec = _complete()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.allowed_users = ("bob",)  # type: ignore[misc]


def test_the_six_fields_are_the_contract():
    assert set(AUTH_FIELDS) == {"basis", "authority", "reference_no", "verified_at",
                                "scope", "allowed_users"}
    assert set(AUTH_FIELDS) == {f.name for f in dataclasses.fields(LiveAuthorization)}


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("os", "sqlalchemy", "fastapi", "requests", "src.database", "src.data", "src.execution"):
            assert name != bad and not name.startswith(bad + "."), f"순수 계층이 {name} 을 import 한다"
