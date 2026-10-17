"""로그인과 자기 확인 — ★신원이 들어오는 유일한 문★ (AC3)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P-1
검증: `src/database.py::verify_user()` 를 **재사용**한다 — bcrypt 해시 비교와
      레거시 평문 승급이 이미 거기 있고, 인증 로직을 두 벌 만들면 둘이 갈라진다.

## ★계정 열거를 막는다★

"없는 사용자" 와 "비밀번호 틀림" 을 구분해 답하면 공격자가 응답 차이만으로 사용자
목록을 만들 수 있다. 그래서 두 경우가 **완전히 같은 401** 을 받는다.

★이것은 침묵 폴백이 아니다★ — 침묵 폴백은 실패를 성공처럼 보이게 하는 것이고,
여기서는 **실패를 실패라고 말하되 실패의 종류를 말하지 않는** 것이다. 의도이고,
`tests/test_auth_routes.py` 가 그 동일성을 고정한다.

## ★회원가입 표면을 만들지 않는다★

`create_user()` 는 있지만 공개 가입 라우트는 없다. 계정 발급은 운영 조치다 —
지금 그것을 요구한 것이 없는데 표면을 열면 그 자체가 새로운 공격면이다.

BS1(2026-09-29, 사용자 결정): 발급은 **관리자가 설정 화면에서** 한다(`POST /users`). 로그인만 하면
실계좌 잔고·주문 이력·일별 손익이 열리므로 누구나 가입하는 길은 여전히 없다. 임시 비밀번호는 응답에
**한 번만** 실리고, 받은 사람은 바꾸기 전에는 보호 라우트를 열 수 없다(`auth._must_change_gate`).

## ★비밀번호·토큰을 로그에 남기지 않는다★ — 이름만 남긴다(`tests/test_account_security.py`).
"""
from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from src.api.auth import (
    DEFAULT_TTL_HOURS,
    auth_secret_reason,
    auth_secret_state,
    create_access_token,
    get_current_principal,
    require_admin,
    require_login_to_change_password,
)
from src.database import admin_password_reason, admin_password_state
from src.domain.auth_identity import ROLE_ADMIN, ROLE_ANALYST, Principal
from src.domain.password_policy import password_problems

logger = logging.getLogger("api.auth_routes")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

#: ★두 실패가 같은 문장을 받는다★ — 여기서 갈라지면 계정 열거가 열린다.
_REFUSED = "아이디 또는 비밀번호가 올바르지 않습니다."


class LoginRequest(BaseModel):
    """★`role` 을 받지 않는다★ — 역할은 DB 가 정하고 토큰이 나른다.

    본문에 `role` 을 끼워 넣어도 pydantic 이 무시한다(추가 필드 기본 동작).
    `tests/test_auth_routes.py` 가 그 사실을 고정한다.
    """

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


@router.post("/login")
def login(req: LoginRequest):
    """자격 증명 → 토큰. 실패는 **무차별 401**."""
    from src.database import session_scope, verify_user

    if not verify_user(req.username, req.password):
        logger.info("로그인 실패: username=%r", req.username)
        raise HTTPException(401, _REFUSED)

    # 역할은 ★DB 에서 읽는다★ — 요청이 주장하는 값이 아니다.
    from src.database import User
    with session_scope() as s:
        user = s.query(User).filter_by(username=req.username).first()
        role = user.role if user and user.role else ROLE_ANALYST

    return _issue_token(req.username, role)


def _issue_token(username: str, role: str) -> dict:
    """로그인·비밀번호 바꾸기가 같은 모양으로 토큰을 준다 — 토큰 판(`tv`)과 바꿀 차례를 함께."""
    from src.api.auth import decode_access_token
    from src.database import account_state

    acct = account_state(username) or {"token_version": 0, "must_change_password": False}
    token = create_access_token(username, role, token_version=acct["token_version"])
    issued = decode_access_token(token)
    logger.info("토큰 발급: username=%r role=%r", username, role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": role,
        "issued_at": issued.issued_at,
        "expires_at": issued.expires_at,
        "ttl_hours": DEFAULT_TTL_HOURS,
        "must_change_password": bool(acct["must_change_password"]),
    }


@router.get("/me")
def me(p: Principal = Depends(get_current_principal)):
    """관측된 신원 + ★배포가 어떤 상태인지★.

    `secret_state`/`secret_reason` 과 `admin_password_state` 를 여기서 읽을 수
    있어야 운영자가 "이 배포는 안전한가" 를 화면으로 확인할 수 있다. 값을 숨기면
    열화가 있었는지 없었는지 아무도 모른다.

    ★바꿀 차례여도 열린다★ — 화면이 "비밀번호를 먼저 바꿔 주세요" 를 알아야 한다(BS1).
    """
    from src.database import account_state

    acct = account_state(p.username) or {}
    return {
        "principal": p.to_dict(),
        "must_change_password": bool(acct.get("must_change_password")),
        "password_changed_at": acct.get("password_changed_at"),
        "secret_state": auth_secret_state(),
        "secret_reason": auth_secret_reason(),
        "admin_password_state": admin_password_state(),
        "admin_password_reason": admin_password_reason(),
    }


# ── 비밀번호 바꾸기 (BS1) ────────────────────────────────────────────────────

#: 지금 비밀번호를 연달아 틀린 시각 — ★프로세스 로컬★(`uvicorn --workers 1` 고정이라 성립한다).
_FAILURES: dict[str, list[float]] = {}
_FAIL_LIMIT = 5
_FAIL_WINDOW_S = 15 * 60


def _reset_password_failures() -> None:
    """테스트가 문을 새로 시작할 때 쓴다."""
    _FAILURES.clear()


def _recent_failures(username: str, now: float) -> list[float]:
    keep = [t for t in _FAILURES.get(username, []) if now - t < _FAIL_WINDOW_S]
    _FAILURES[username] = keep
    return keep


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


@router.post("/password")
def change_password(req: PasswordChange, p: Principal = Depends(require_login_to_change_password)):
    """지금 비밀번호를 확인하고 바꾼다 → 토큰 판이 올라 ★옛 토큰은 모두 죽고★ 새 토큰을 준다(이 창은 이어진다)."""
    from src.database import set_password, verify_user

    now = time.monotonic()
    fails = _recent_failures(p.username, now)
    if len(fails) >= _FAIL_LIMIT:
        wait = max(1, int((_FAIL_WINDOW_S - (now - fails[0])) // 60) + 1)
        raise HTTPException(429, f"지금 비밀번호를 {_FAIL_LIMIT}번 틀려 잠시 막았어요 — 약 {wait}분 뒤에 다시 해 주세요.")
    if not verify_user(p.username, req.current_password):
        fails.append(now)
        logger.info("비밀번호 바꾸기 거절(지금 비밀번호 틀림): username=%r", p.username)
        raise HTTPException(400, "지금 비밀번호가 맞지 않아요.")
    problems = password_problems(req.new_password, current=req.current_password, username=p.username)
    if problems:
        raise HTTPException(400, "새 비밀번호를 쓸 수 없어요 — " + " ".join(problems))
    if set_password(p.username, req.new_password, must_change=False) is None:
        raise HTTPException(401, "계정을 찾을 수 없어요 — 다시 로그인하세요.")
    _FAILURES.pop(p.username, None)
    logger.info("비밀번호를 바꿈: username=%r", p.username)
    return _issue_token(p.username, p.role)


# ── 관리자 발급 (BS1) ────────────────────────────────────────────────────────

#: 아이디 — 영문·숫자·`._-` 1~64자. 공백·한글은 받지 않는다(로그·URL 경로에 그대로 실린다).
_USERNAME = r"^[A-Za-z0-9._-]{1,64}$"


class IssueAccount(BaseModel):
    username: str = Field(..., pattern=_USERNAME)
    role: Literal["admin", "analyst"] = ROLE_ANALYST


@router.get("/users")
def list_users(_: Principal = Depends(require_admin)):
    """계정 목록 — ★해시·비밀번호를 싣지 않는다★."""
    from src.database import list_accounts
    return {"users": list_accounts(), "roles": [ROLE_ADMIN, ROLE_ANALYST]}


@router.post("/users", status_code=201)
def issue_user(req: IssueAccount, p: Principal = Depends(require_admin)):
    """계정 발급 — 임시 비밀번호는 ★이 응답에만★ 실린다. 받은 사람은 처음 로그인 뒤 바꿔야 한다."""
    from src.database import issue_account

    temp = issue_account(req.username, req.role)
    if temp is None:
        raise HTTPException(409, f"이미 있는 아이디예요({req.username}).")
    logger.info("계정 발급: username=%r role=%r by=%r", req.username, req.role, p.username)
    return {"username": req.username, "role": req.role, "temporary_password": temp,
            "must_change_password": True}


@router.post("/users/{username}/reset-password")
def reset_user_password(username: str = Path(..., pattern=_USERNAME), p: Principal = Depends(require_admin)):
    """비밀번호 초기화 — 새 임시 비밀번호 · 바꿀 차례 · ★그 사람의 토큰이 모두 죽는다★."""
    from src.database import reset_account_password

    temp = reset_account_password(username)
    if temp is None:
        raise HTTPException(404, f"그 아이디의 계정이 없어요({username}).")
    logger.info("비밀번호 초기화: username=%r by=%r", username, p.username)
    return {"username": username, "temporary_password": temp, "must_change_password": True}
