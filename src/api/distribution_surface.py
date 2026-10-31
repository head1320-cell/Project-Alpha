"""유통 표면 등록부 + 관문 문 (CF 3부 PB6) — ★여는 경로는 관문 뒤에만★
==============================================================================
`src/api/protected_routes.py` 와 같은 관용구 — 흩어진 진실 대신 한 곳. `tests/test_distribution_blocked.py` 가 앱의 실제
라우트 테이블과 대조한다: 유통 형태 경로(`/share` 등 마커)는 ★전부★ 여기 있어야 하고, 여는 것은 관문을 닫은 채 부르면
★실제로★ 403 이어야 한다(동작으로 확인).

- `OPENS` — 고객에게 무엇을 보이게 하는 길(주소 만들기 · 다시 열기 · 보여 줄 한 장 바꾸기 · 고객 열기 · 한 장 · 묻기).
  ★조회보다 먼저★ `require_distribution_open` 을 지난다(닫혀 있으면 무엇이 있는지 드러내기 전에 멈춘다). 고객 경로는 맨 앞,
  PB 경로는 로그인 다음(보호 등록부 계약 — 익명은 401).
- `CLOSES` — 끄고 살피는 길(목록 · 철회). 관문과 무관하게 늘 된다(관문이 닫혀도 고객 주소를 끌 수 있어야 한다) —
  토큰·한 장(내용)을 내지 않는다.
"""
from __future__ import annotations

from fastapi import HTTPException

from src.domain.distribution_gate import DISTRIBUTION_ALLOWED
from src.services import distribution_gate_store

OPENS = "opens"
CLOSES = "closes"

DISTRIBUTION_SURFACE: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/v1/pb/clients/{cid}/share-links"):
        (OPENS, "고객 주소 만들기 — 고객이 이 한 장을 보게 된다"),
    ("POST", "/api/v1/pb/clients/{cid}/share-links/{lid}/reopen"):
        (OPENS, "잠긴 고객 주소 다시 열기 — 고객이 다시 볼 수 있게 된다"),
    ("PATCH", "/api/v1/pb/clients/{cid}/share-links/{lid}"):
        (OPENS, "고객 주소가 보여 줄 한 장 바꾸기 — 고객이 새 한 장을 보게 된다"),
    ("POST", "/api/v1/share/open"):
        (OPENS, "고객이 주소 + PIN 으로 연다 — 세션을 받는다"),
    ("GET", "/api/v1/share/sheet"):
        (OPENS, "고객이 한 장을 본다"),
    ("POST", "/api/v1/share/ask"):
        (OPENS, "고객이 한 장에게 묻는다(고객 AI)"),
    ("GET", "/api/v1/pb/clients/{cid}/share-links"):
        (CLOSES, "PB 가 주소 목록·상태·관문 판정을 본다 — 토큰·한 장을 내지 않는다"),
    ("POST", "/api/v1/pb/clients/{cid}/share-links/{lid}/revoke"):
        (CLOSES, "PB 가 주소를 끈다 — 관문이 닫혀도 늘 된다"),
}


def blocked_detail(g: dict) -> dict:
    return {"code": "distribution_blocked", "reason": g["reason"], "missing": g["missing"]}


def require_distribution_open() -> dict:
    """여는 경로의 ★첫★ 의존성 — 관문이 열려 있지 않으면 403 + 사유 + 빠진 칸. 인가 기록 값은 싣지 않는다."""
    g = distribution_gate_store.gate()
    if g["state"] != DISTRIBUTION_ALLOWED:
        raise HTTPException(403, blocked_detail(g))
    return g


def gate_view() -> dict:
    """PB 화면용 판정 — 상태 · 사유 · 빠진 칸만(인가 기록 값은 관리자 경로에서만)."""
    g = distribution_gate_store.gate()
    return {"state": g["state"], "reason": g["reason"], "missing": g["missing"]}
