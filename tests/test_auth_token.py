"""AC2 — 토큰 발급·검증의 계약.

★검사하는 것은 "이 토큰을 믿어도 되는가" 다★ — 위조·만료·형식 오류가 각각
**다른 사유**로 거절되는지, 그리고 거절이 조용하지 않은지(`{}` 금지).
"""
from __future__ import annotations

import datetime as dt
import pathlib

import jwt
import pytest

from src.api.auth import (
    AuthError,
    auth_secret_reason,
    auth_secret_state,
    create_access_token,
    decode_access_token,
)
from src.domain.auth_identity import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    SECRET_CONFIGURED,
    SECRET_EPHEMERAL,
    SOURCE_TOKEN,
)

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret-do-not-ship-0123456789abcdef")
    return "test-secret-do-not-ship-0123456789abcdef"


# ── 왕복 ────────────────────────────────────────────────────────────────────

def test_a_token_round_trips_to_the_same_identity(configured):
    tok = create_access_token("alice", ROLE_ANALYST)
    p = decode_access_token(tok)
    assert p.username == "alice"
    assert p.role == ROLE_ANALYST
    assert p.source == SOURCE_TOKEN


def test_a_decoded_identity_carries_its_window(configured):
    p = decode_access_token(create_access_token("alice", ROLE_ANALYST, ttl_hours=3))
    assert p.issued_at is not None and p.expires_at is not None
    issued = dt.datetime.fromisoformat(p.issued_at)
    expires = dt.datetime.fromisoformat(p.expires_at)
    assert 2.9 < (expires - issued).total_seconds() / 3600 < 3.1


# ── 거절, 그리고 ★각각 다른 사유★ ──────────────────────────────────────────

def test_an_expired_token_is_rejected_and_says_so(configured):
    tok = create_access_token("alice", ROLE_ANALYST, ttl_hours=-1)
    with pytest.raises(AuthError) as e:
        decode_access_token(tok)
    assert "만료" in str(e.value)


def test_a_token_signed_with_another_secret_is_rejected_and_says_so(configured):
    forged = jwt.encode(
        {"sub": "alice", "role": ROLE_ADMIN,
         "iat": dt.datetime.now(dt.timezone.utc),
         "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
        "a-different-secret-0123456789abcdefghij", algorithm="HS256",
    )
    with pytest.raises(AuthError) as e:
        decode_access_token(forged)
    assert "서명" in str(e.value)


def test_garbage_is_rejected_and_says_so(configured):
    with pytest.raises(AuthError) as e:
        decode_access_token("not-a-token")
    assert "형식" in str(e.value)


def test_no_rejection_is_silent(configured):
    """★`{}` 나 사유 없는 거절 금지★(CLAUDE.md §4)."""
    for bad in ["", "   ", "a.b.c", create_access_token("x", ROLE_ANALYST, ttl_hours=-5)]:
        with pytest.raises(AuthError) as e:
            decode_access_token(bad)
        assert str(e.value).strip(), "사유 없는 거절이 있다"


def test_a_token_without_a_known_role_is_rejected(configured):
    """★미상은 통과가 아니다★ — 역할이 어휘 밖이면 거절한다."""
    tok = jwt.encode(
        {"sub": "alice", "role": "wizard",
         "iat": dt.datetime.now(dt.timezone.utc),
         "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
        configured, algorithm="HS256",
    )
    with pytest.raises(AuthError) as e:
        decode_access_token(tok)
    assert "역할" in str(e.value)


def test_a_token_without_a_subject_is_rejected(configured):
    tok = jwt.encode(
        {"role": ROLE_ADMIN,
         "iat": dt.datetime.now(dt.timezone.utc),
         "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
        configured, algorithm="HS256",
    )
    with pytest.raises(AuthError):
        decode_access_token(tok)


def test_the_alg_none_trick_is_rejected(configured):
    """★서명 없는 토큰을 받아주지 않는다★ — JWT 의 고전적 우회."""
    tok = jwt.encode(
        {"sub": "alice", "role": ROLE_ADMIN,
         "iat": dt.datetime.now(dt.timezone.utc),
         "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
        key="", algorithm="none",
    )
    with pytest.raises(AuthError):
        decode_access_token(tok)


# ── 비밀키의 상태가 ★보인다★ ───────────────────────────────────────────────

def test_a_configured_secret_is_reported_as_configured(configured):
    assert auth_secret_state() == SECRET_CONFIGURED


def test_an_absent_secret_is_reported_as_ephemeral_not_hidden(monkeypatch):
    """★짝★ — 항상-configured 구현을 배제하고, 열화를 **보이게** 한다."""
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    assert auth_secret_state() == SECRET_EPHEMERAL


def test_a_blank_secret_counts_as_absent(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "   ")
    assert auth_secret_state() == SECRET_EPHEMERAL
    assert auth_secret_reason() is not None


def test_a_too_short_secret_is_refused_with_a_reason(monkeypatch):
    """★짧은 비밀키를 조용히 받아주지 않는다★ — HS256 은 32바이트 미만을 권고 위반으로 본다.

    그렇다고 그 값으로 서명하지도, 아무 말 없이 넘어가지도 않는다: 프로세스 난수로
    **열화**하고 그 **사유**를 말한다.
    """
    monkeypatch.setenv("AUTH_SECRET", "short")
    assert auth_secret_state() == SECRET_EPHEMERAL
    reason = auth_secret_reason()
    assert reason and "32" in reason


def test_a_configured_secret_has_no_degradation_reason(configured):
    """★짝★ — 항상-사유-있음 구현을 배제한다."""
    assert auth_secret_reason() is None


def test_tokens_still_work_without_a_configured_secret(monkeypatch):
    """열화는 '망가짐' 이 아니다 — 프로세스 안에서는 동작하고, 재시작하면 무효."""
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    p = decode_access_token(create_access_token("alice", ROLE_ANALYST))
    assert p.username == "alice"


def test_a_token_issued_under_one_secret_dies_under_another(monkeypatch):
    """비밀키가 실제로 서명에 쓰인다 — 상태 문자열만 바뀌는 장식이 아니다."""
    monkeypatch.setenv("AUTH_SECRET", "secret-one-0123456789abcdefghijklmn")
    tok = create_access_token("alice", ROLE_ADMIN)
    monkeypatch.setenv("AUTH_SECRET", "secret-two-0123456789abcdefghijklmn")
    with pytest.raises(AuthError):
        decode_access_token(tok)


# ── ★하드코딩된 비밀키가 소스에 없다★ ─────────────────────────────────────

def test_no_default_secret_is_baked_into_the_source():
    """공유된 기본 비밀키는 '아무나 토큰을 위조할 수 있다' 와 같다.

    `os.getenv("AUTH_SECRET", <문자열>)` 형태가 소스 어디에도 없어야 한다.
    """
    import ast

    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name not in {"getenv", "get"}:
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "AUTH_SECRET"):
                continue
            assert len(node.args) < 2 or not isinstance(node.args[1], ast.Constant) \
                or not node.args[1].value, f"{path} 가 AUTH_SECRET 에 기본값을 박았다"
