"""고객 별칭의 개인정보 모양 검사 — ★별칭만 받는다★ (CF 3부 PB)
==============================================================================
사용자 결정(2026-10-23): 고객 자료는 PB 가 정한 별칭만 둔다 — 실명·연락처·주민번호·계좌번호를 받지 않는다.

## 이 검사가 하는 것 · 하지 않는 것

★모양만 본다★ — 전화번호(010-1234-5678 · 01012345678) · 이메일 · 주민등록번호(6자리-7자리) · 8자리가 넘는 숫자열(계좌번호
모양). 이런 모양이면 별칭으로 받지 않고 사유를 말한다.

★실명은 모양으로 알 수 없다★ — "홍길동" 이 사람 이름인지 별칭인지 이 코드는 판단하지 못한다. 그것은 화면의 안내 문구("실명·
연락처를 적지 마세요")와 PB 의 몫이고, 이 검사는 그렇다고 주장하지 않는다. 짧은 숫자·하이픈이 든 별칭("고객 A-12" ·
"2026 정기점검")은 막지 않는다.
"""
from __future__ import annotations

import re

#: 별칭 길이 상한 — 별칭이지 메모가 아니다.
ALIAS_MAX = 40

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_RRN = re.compile(r"\d{6}\s*-?\s*[1-8]\d{6}")
_PHONE = re.compile(r"(?<!\d)0\d{1,2}[\s.-]?\d{3,4}[\s.-]?\d{4}(?!\d)")
#: 숫자만 9자리 이상 이어지면(하이픈·공백을 빼고) 계좌번호·전화번호 모양으로 본다.
_LONG_DIGITS = re.compile(r"\d{9,}")


def pii_reason(text: str | None, *, label: str = "별칭", max_len: int = ALIAS_MAX) -> str | None:
    """개인정보 모양이면 사유, 아니면 `None`. 빈 값은 문제 삼지 않는다(별칭은 선택).
    `label` 은 사유 문장의 칸 이름(PB3 — 문서 이름·문서 안 고객 노드 별칭도 같은 검사), `max_len` 은 그 칸의 길이 상한."""
    if not text or not text.strip():
        return None
    s = text.strip()
    if len(s) > max_len:
        return f"{label}은 {max_len}자까지예요 — 메모나 실명을 적는 칸이 아니에요."
    if _EMAIL.search(s):
        return f"{label}에 이메일 모양이 있어요 — 연락처는 적지 않아요."
    if _RRN.search(s):
        return f"{label}에 주민등록번호 모양이 있어요 — 개인정보는 적지 않아요."
    if _PHONE.search(s):
        return f"{label}에 전화번호 모양이 있어요 — 연락처는 적지 않아요."
    if _LONG_DIGITS.search(re.sub(r"[\s-]", "", s)):
        return f"{label}에 긴 숫자열(계좌번호 모양)이 있어요 — 계좌번호는 적지 않아요."
    return None
