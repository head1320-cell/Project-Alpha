"""AC1 — 신원 어휘의 계약 (순수 계층).

★여기서 검사하는 것은 "누구인가" 를 **어떻게 표현하는가** 뿐이다★ — 토큰도 DB 도
이 모듈은 모른다. 판정 함수 둘(`is_admin`·`can_read_user`)에는 반드시 **짝**을 붙여
항상-True·항상-False 구현을 배제한다(CLAUDE.md §5).
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.auth_identity import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLES,
    SECRET_CONFIGURED,
    SECRET_EPHEMERAL,
    SOURCE_ABSENT,
    SOURCE_TOKEN,
    Principal,
    can_read_user,
    is_admin,
)

_MODULE = pathlib.Path(__file__).resolve().parents[1] / "src" / "domain" / "auth_identity.py"


def _p(username: str, role: str) -> Principal:
    return Principal(username=username, role=role, source=SOURCE_TOKEN)


# ── 어휘 ────────────────────────────────────────────────────────────────────

def test_the_two_roles_are_the_only_roles():
    assert ROLES == (ROLE_ADMIN, ROLE_ANALYST)
    assert ROLE_ADMIN == "admin"
    assert ROLE_ANALYST == "analyst"


def test_the_source_of_an_identity_is_part_of_the_vocabulary():
    """★"어떻게 알았나" 를 값에 남긴다★ — 토큰에서 관측했는지, 제시가 없었는지."""
    assert SOURCE_TOKEN == "token"
    assert SOURCE_ABSENT == "absent"
    assert SOURCE_TOKEN != SOURCE_ABSENT


def test_the_secret_state_is_part_of_the_vocabulary():
    """비밀키가 설정됐는지 프로세스 로컬 난수인지 — ★조용한 폴백이 아니라 라벨★."""
    assert SECRET_CONFIGURED == "configured"
    assert SECRET_EPHEMERAL == "ephemeral"


# ── is_admin 과 그 짝 ───────────────────────────────────────────────────────

def test_an_admin_is_admin():
    assert is_admin(_p("alice", ROLE_ADMIN)) is True


def test_an_analyst_is_not_admin():
    """★짝★ — 항상-True 구현을 배제한다."""
    assert is_admin(_p("bob", ROLE_ANALYST)) is False


def test_an_unknown_role_is_not_admin():
    """미상은 통과가 아니다(CLAUDE.md §4)."""
    assert is_admin(_p("carol", "wizard")) is False


# ── can_read_user 와 그 짝 ─────────────────────────────────────────────────

def test_one_can_read_ones_own_records():
    assert can_read_user(_p("alice", ROLE_ANALYST), "alice") is True


def test_one_cannot_read_someone_elses_records():
    """★완료 판정의 403 이 여기서 결정된다★."""
    assert can_read_user(_p("alice", ROLE_ANALYST), "bob") is False


def test_an_admin_can_read_someone_elses_records():
    """★짝★ — 항상-False 구현을 배제한다."""
    assert can_read_user(_p("root", ROLE_ADMIN), "bob") is True


@pytest.mark.parametrize("target", ["", "   ", None])
def test_an_empty_target_is_never_readable(target):
    """빈 username 을 '자기 자신' 으로 접지 않는다."""
    assert can_read_user(_p("alice", ROLE_ANALYST), target) is False


def test_the_comparison_does_not_collapse_case_or_whitespace():
    """★`Alice` 와 `alice` 를 같다고 지어내지 않는다★ — username 은 PK 이고 DB 는 구분한다."""
    assert can_read_user(_p("alice", ROLE_ANALYST), "Alice") is False
    assert can_read_user(_p("alice", ROLE_ANALYST), " alice") is False


# ── 타입 ───────────────────────────────────────────────────────────────────

def test_a_principal_is_immutable():
    """신원을 통과 중에 고쳐 쓸 수 없다."""
    p = _p("alice", ROLE_ANALYST)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.role = ROLE_ADMIN  # type: ignore[misc]


def test_a_principal_carries_its_token_window_when_known():
    p = Principal(
        username="alice", role=ROLE_ANALYST, source=SOURCE_TOKEN,
        issued_at="2026-09-13T00:00:00+00:00", expires_at="2026-09-13T12:00:00+00:00",
    )
    assert p.issued_at and p.expires_at
    d = p.to_dict()
    assert d["username"] == "alice" and d["role"] == ROLE_ANALYST
    assert d["source"] == SOURCE_TOKEN


def test_a_principal_without_a_window_says_none_not_zero():
    """미상 ≠ 0 — 모르는 시각을 epoch 으로 접지 않는다."""
    p = _p("alice", ROLE_ANALYST)
    assert p.issued_at is None and p.expires_at is None


# ── 순수성 ─────────────────────────────────────────────────────────────────

_FORBIDDEN = ("sqlalchemy", "fastapi", "requests", "jwt", "bcrypt", "src.database")


def test_the_domain_module_stays_pure():
    """★src/domain 은 순수 타입이다★ — DB·HTTP·암호 라이브러리를 import 하지 않는다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in _FORBIDDEN:
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"


# ── 관측된 행위자 vs 자칭 행위자 (AC5) ─────────────────────────────────────

def test_the_observed_actor_is_the_token_not_the_body():
    """★감사 로그에 적히는 이름은 **토큰에서 관측된** 것이다★."""
    from src.domain.auth_identity import observed_actor

    out = observed_actor(_p("alice", ROLE_ADMIN), claimed="someone_else")
    assert out["actor"] == "alice"
    assert out["actor_source"] == "authenticated"


def test_a_conflicting_claim_is_kept_side_by_side_not_erased():
    """★거짓말을 지우지 않고 나란히 기록한다★ — 그것이 감사 로그가 할 일이다."""
    from src.domain.auth_identity import observed_actor

    out = observed_actor(_p("alice", ROLE_ADMIN), claimed="someone_else")
    assert out["claimed_actor"] == "someone_else"


def test_a_matching_claim_leaves_no_conflict_record():
    """★짝★ — 언제나 claimed_actor 를 남기는 구현을 배제한다."""
    from src.domain.auth_identity import observed_actor

    out = observed_actor(_p("alice", ROLE_ADMIN), claimed="alice")
    assert out["claimed_actor"] is None


def test_an_absent_claim_is_not_a_conflict():
    """본문이 아무 이름도 주장하지 않았으면 충돌이 아니다 — 기본값도 마찬가지."""
    from src.domain.auth_identity import observed_actor

    for claimed in [None, "", "   ", "user", "admin"]:
        out = observed_actor(_p("alice", ROLE_ADMIN), claimed=claimed)
        assert out["actor"] == "alice"
        assert out["claimed_actor"] is None, claimed


def test_the_observed_actor_never_returns_the_claim_as_actor():
    """변이 g(자칭을 다시 넘김)를 죽인다 — 어떤 입력에도 actor 는 토큰의 이름이다."""
    from src.domain.auth_identity import observed_actor

    for claimed in [None, "", "admin", "root", "alice", "../../etc/passwd"]:
        assert observed_actor(_p("carol", ROLE_ANALYST), claimed=claimed)["actor"] == "carol"
