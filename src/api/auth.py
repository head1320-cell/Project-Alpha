"""토큰 발급·검증과 FastAPI 의존성 — ★신원을 **관측**하는 한 곳★ (AC2)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P-1
어휘: `src/domain/auth_identity.py` (순수 계층 — 판정 함수는 거기에 있다)

## ★401 과 403 을 가른다★

    401  신원이 **없거나 검증에 실패**했다 — 누구인지 모른다
    403  신원은 **있는데 권한이 모자란다** — 누구인지는 안다

로드맵의 완료 판정이 둘을 구분해서 요구한다. 둘을 뭉치면 "인증 실패" 와 "권한 부족"
이 같은 사건이 되어, 감사할 때 침입 시도와 실수를 구분할 수 없다.

## ★거절에 사유를 붙인다★

`만료` · `서명` · `형식` · `역할` · `주체` 를 각각 다르게 말한다. 사유 없는
`"unauthorized"` 나 `{}` 는 금지(CLAUDE.md §4) — 운영자가 로그만 보고 "키가 틀렸나
시계가 틀렸나" 를 가릴 수 있어야 한다.

## ★하드코딩된 기본 비밀키를 두지 않는다★

공유된 기본 비밀은 "아무나 admin 토큰을 위조할 수 있다" 와 같고, 그것이야말로 이
모듈이 막으려는 것이다. `AUTH_SECRET` 이 없거나 너무 짧으면 **프로세스 로컬 난수**로
열화하되, 조용히 넘어가지 않는다 — 상태와 **사유**를 `GET /api/v1/auth/me` 로 읽을
수 있고 기동 시 경고 로그가 남는다. CLAUDE.md §4 의 폴백 4조건을 모두 만족한다:
⑴ 의미가 알려졌고 ⑵ 라벨이 붙고 ⑶ 동등 품질로 위장하지 않고(재시작 시 전원
로그아웃) ⑷ 관측·테스트 가능하다. `uvicorn --workers 1` 고정이라 프로세스 로컬이
실제로 성립한다.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import secrets

import jwt
from fastapi import Depends, HTTPException, Request

from src.domain.auth_identity import (
    ROLES,
    SECRET_CONFIGURED,
    SECRET_EPHEMERAL,
    SOURCE_TOKEN,
    Principal,
    can_read_user,
    is_admin,
)

logger = logging.getLogger("api.auth")

_ALGORITHM = "HS256"
#: HS256 의 권고 최소 키 길이(RFC 7518 §3.2). 이보다 짧으면 설정으로 인정하지 않는다.
_MIN_SECRET_BYTES = 32
#: 프로세스 로컬 난수 — ★import 시 한 번★. 재시작하면 이전 토큰이 전부 무효가 된다.
_EPHEMERAL_SECRET = secrets.token_urlsafe(48)

DEFAULT_TTL_HOURS = 12


class AuthError(Exception):
    """토큰을 믿을 수 없다 — 메시지가 **왜인지**를 말한다."""


# ── 비밀키 ──────────────────────────────────────────────────────────────────

def _configured_secret() -> str | None:
    """환경변수가 쓸 만한 비밀키를 주는가. 아니면 `None` 과 사유는 아래 함수가."""
    raw = os.getenv("AUTH_SECRET", "").strip()
    if not raw or len(raw.encode("utf-8")) < _MIN_SECRET_BYTES:
        return None
    return raw


def auth_secret_reason() -> str | None:
    """열화했다면 **왜** 열화했는지. 설정이 정상이면 `None`.

    ★`None` 은 "모른다" 가 아니라 "열화가 없다" 다★ — 상태와 짝으로만 읽는다.
    """
    raw = os.getenv("AUTH_SECRET", "").strip()
    if not raw:
        return ("AUTH_SECRET 이 설정되지 않아 프로세스 로컬 난수를 씁니다 — "
                "재시작하면 발급된 토큰이 모두 무효가 됩니다.")
    if len(raw.encode("utf-8")) < _MIN_SECRET_BYTES:
        return (f"AUTH_SECRET 이 {_MIN_SECRET_BYTES}바이트 미만이라 서명 키로 쓰지 "
                "않았습니다(RFC 7518 §3.2) — 프로세스 로컬 난수를 씁니다.")
    return None


def auth_secret_state() -> str:
    """`configured` | `ephemeral` — ★조용한 폴백이 아니라 관측 가능한 라벨★."""
    return SECRET_CONFIGURED if _configured_secret() else SECRET_EPHEMERAL


def _signing_secret() -> str:
    return _configured_secret() or _EPHEMERAL_SECRET


def warn_if_degraded() -> None:
    """기동 시 한 번 — 열화 상태를 로그에 남긴다(무시해도 동작은 한다)."""
    reason = auth_secret_reason()
    if reason:
        logger.warning("인증 비밀키 열화: %s", reason)


# ── 발급과 검증 ─────────────────────────────────────────────────────────────

def create_access_token(username: str, role: str,
                        ttl_hours: float = DEFAULT_TTL_HOURS, *, token_version: int = 0) -> str:
    """★`ttl_hours` 가 음수면 이미 만료된 토큰이 나온다★ — 테스트가 쓰는 길이다.

    `tv` 는 계정의 토큰 판(BS1) — 비밀번호를 바꾸면 판이 올라 옛 토큰이 `get_current_principal` 에서 죽는다.
    """
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {
            "sub": username,
            "role": role,
            "iat": now,
            "exp": now + dt.timedelta(hours=ttl_hours),
            "tv": int(token_version),
        },
        _signing_secret(),
        algorithm=_ALGORITHM,
    )


def decode_access_token(token: str) -> Principal:
    """서명·만료·형식·역할을 모두 통과한 토큰만 `Principal` 이 된다.

    ★`algorithms=[_ALGORITHM]` 을 못 박는다★ — 이것을 비우면 `alg: none` 토큰이
    통과하는 고전적 우회가 열린다.
    """
    return _decode(token)[0]


def _decode(token: str) -> tuple[Principal, int]:
    """`(신원, 토큰 판)`. `tv` 가 없는 토큰(BS1 전 발급)은 판 0 이다."""
    if not token or not token.strip():
        raise AuthError("토큰 형식 오류 — 빈 토큰입니다.")
    try:
        payload = jwt.decode(token, _signing_secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("토큰 만료 — 다시 로그인하세요.") from None
    except jwt.InvalidSignatureError:
        raise AuthError("토큰 서명 불일치 — 이 서버가 발급한 토큰이 아닙니다.") from None
    except jwt.InvalidTokenError as e:
        raise AuthError(f"토큰 형식 오류 — {e}") from None

    username = payload.get("sub")
    if not username:
        raise AuthError("토큰 주체(sub) 없음 — 누구의 토큰인지 알 수 없습니다.")

    role = payload.get("role")
    if role not in ROLES:
        # ★미상은 통과가 아니다★ — 어휘 밖의 역할을 analyst 로 접지 않는다.
        raise AuthError(f"토큰 역할이 어휘 밖입니다({role!r}) — 허용: {list(ROLES)}")

    def _iso(claim: str) -> str | None:
        raw = payload.get(claim)
        if raw is None:
            return None
        return dt.datetime.fromtimestamp(raw, dt.timezone.utc).isoformat()

    tv = payload.get("tv", 0)
    if not isinstance(tv, int) or isinstance(tv, bool):
        raise AuthError(f"토큰 판(tv)이 정수가 아닙니다({tv!r}).")
    return Principal(
        username=username, role=role, source=SOURCE_TOKEN,
        issued_at=_iso("iat"), expires_at=_iso("exp"),
    ), tv


# ── FastAPI 의존성 ──────────────────────────────────────────────────────────

def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _refuse(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_principal(request: Request) -> Principal:
    """신원이 없거나 검증에 실패하면 **401** — 사유를 함께 돌려준다.

    ★서명만으로 믿지 않는다(BS1)★ — 서명이 맞아도 ⑴ 계정이 사라졌거나 ⑵ 비밀번호를 바꿔 토큰 판이
    올랐으면 401 이다. 예전에는 비밀번호를 바꿔도 옛 토큰이 12시간 살았다. DB 에 닿지 못하면 503 —
    "확인하지 못함" 을 통과로도 거절로도 접지 않는다.
    """
    token = _bearer_token(request)
    if token is None:
        raise _refuse("인증이 필요합니다 — Authorization: Bearer <토큰> 헤더가 없습니다.")
    try:
        p, tv = _decode(token)
    except AuthError as e:
        raise _refuse(str(e)) from None
    from src.database import account_state
    try:
        acct = account_state(p.username)
    except Exception as e:  # noqa: BLE001
        logger.warning("계정 상태를 읽지 못함: %s", type(e).__name__)
        raise HTTPException(503, "계정 상태를 확인하지 못했어요 — 신원 DB 에 닿지 못했습니다.") from None
    if acct is None:
        raise _refuse("계정을 찾을 수 없어요 — 다시 로그인하세요.")
    if tv != acct["token_version"]:
        raise _refuse("비밀번호가 바뀌어 이 토큰은 더 쓸 수 없어요 — 다시 로그인하세요.")
    request.state.must_change_password = acct["must_change_password"]
    return p


def _must_change_gate(request: Request) -> None:
    """관리자가 발급·초기화한 임시 비밀번호로는 보호 라우트가 열리지 않는다 — **403**(누구인지는 안다)."""
    if getattr(request.state, "must_change_password", False):
        raise HTTPException(403, "비밀번호를 먼저 바꿔 주세요 — 관리자가 준 임시 비밀번호로는 이 화면을 열 수 없어요.")


def require_admin(request: Request, p: Principal = Depends(get_current_principal)) -> Principal:
    """신원은 확인됐으나 역할이 모자라면 **403** — 401 이 아니다."""
    _must_change_gate(request)
    if not is_admin(p):
        raise HTTPException(
            403, f"권한 부족 — 이 작업은 admin 역할이 필요합니다(현재: {p.role}).")
    return p


def require_login(request: Request, p: Principal = Depends(get_current_principal)) -> Principal:
    """로그인만 요구한다(역할 무관). 계좌·감사처럼 PII 이지만 돈을 옮기지 않는 표면."""
    _must_change_gate(request)
    return p


def require_login_to_change_password(p: Principal = Depends(get_current_principal)) -> Principal:
    """로그인만 요구하되 ★바꿀 차례여도 통과★ — 비밀번호 바꾸기 자리만 쓴다(여기를 막으면 영영 못 바꾼다)."""
    return p


def require_self_or_admin(username: str, request: Request,
                          p: Principal = Depends(get_current_principal)) -> Principal:
    """경로의 `username` 자원을 이 신원이 읽어도 되는가 — 아니면 **403**.

    `username` 은 경로 파라미터에서 FastAPI 가 채워 준다.
    """
    _must_change_gate(request)
    if not can_read_user(p, username):
        raise HTTPException(
            403, f"권한 부족 — {username!r} 의 자료는 본인 또는 admin 만 볼 수 있습니다.")
    return p
