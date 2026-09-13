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
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth import (
    DEFAULT_TTL_HOURS,
    auth_secret_reason,
    auth_secret_state,
    create_access_token,
    get_current_principal,
)
from src.database import admin_password_state
from src.domain.auth_identity import ROLE_ANALYST, Principal

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

    token = create_access_token(req.username, role)
    from src.api.auth import decode_access_token
    issued = decode_access_token(token)
    logger.info("로그인 성공: username=%r role=%r", req.username, role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": role,
        "issued_at": issued.issued_at,
        "expires_at": issued.expires_at,
        "ttl_hours": DEFAULT_TTL_HOURS,
    }


@router.get("/me")
def me(p: Principal = Depends(get_current_principal)):
    """관측된 신원 + ★배포가 어떤 상태인지★.

    `secret_state`/`secret_reason` 과 `admin_password_state` 를 여기서 읽을 수
    있어야 운영자가 "이 배포는 안전한가" 를 화면으로 확인할 수 있다. 값을 숨기면
    열화가 있었는지 없었는지 아무도 모른다.
    """
    return {
        "principal": p.to_dict(),
        "secret_state": auth_secret_state(),
        "secret_reason": auth_secret_reason(),
        "admin_password_state": admin_password_state(),
    }
