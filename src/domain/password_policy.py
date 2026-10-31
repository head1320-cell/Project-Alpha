"""새 비밀번호 규칙 — ★왜 안 되는지를 규칙마다 말한다★ (BS1)
==============================================================================
소비자: `src/api/auth_routes.py` (서버 판정) · `frontend/src/features/settings/passwordRules.ts`
        (입력하는 동안 같은 규칙을 미리 보인다 — `tests/test_account_security_frontend.py` 가
        알려진 기본값 목록이 두 곳에서 같은지 본다).

## 규칙이 적은 이유

길이 한 줄과 "알려진 값 아님" 이 실제로 막는 것의 대부분이다. 대문자·특수문자 섞기 같은 구성 규칙은
사람이 예측 가능한 변형(`Password1!`)을 고르게 만들 뿐이라 넣지 않았다(NIST SP 800-63B §5.1.1.2).

## ★순수 계층★ — DB·bcrypt·FastAPI 를 모른다.
"""
from __future__ import annotations

MIN_LENGTH = 8
#: bcrypt 는 72바이트 뒤를 잘라 버린다 — 넘기면 "뒤가 달라도 같은 비밀번호" 가 된다.
MAX_BYTES = 72
#: 이 저장소가 스스로 만든 적이 있는 값 — 누구나 코드에서 읽을 수 있다.
#: `frm123!`(admin 기본값, `src/database.py`) · `temp`(예전 옆문 계정) · `changeme`(이관 스크립트).
KNOWN_DEFAULTS = ("frm123!", "temp", "changeme")


def password_problems(new: str, *, current: str | None, username: str) -> list[str]:
    """새 비밀번호가 규칙에 어긋나는 이유들. 빈 목록이면 쓸 수 있다."""
    problems: list[str] = []
    if len(new) < MIN_LENGTH:
        problems.append(f"{MIN_LENGTH}자 이상이어야 해요.")
    if len(new.encode("utf-8")) > MAX_BYTES:
        problems.append(f"{MAX_BYTES}바이트를 넘으면 뒤가 잘려요 — 더 짧게 정해 주세요.")
    if current is not None and new == current:
        problems.append("지금 비밀번호와 달라야 해요.")
    if new.strip().lower() == username.strip().lower():
        problems.append("아이디와 달라야 해요.")
    if new.strip().lower() in KNOWN_DEFAULTS:
        problems.append("알려진 기본 비밀번호는 쓸 수 없어요.")
    return problems
