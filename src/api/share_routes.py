"""고객이 여는 경로 — 주소 + PIN → 세션 → 한 장 · 묻기 (CF 3부 PB6 · ★유통 관문 뒤★)
==============================================================================
로그인이 없다 — 고객 계정을 만들지 않는다(사용자 결정). 대신 ★매 요청 맨 앞에서 관문★(`require_distribution_open`)을 지나고,
그 뒤에 주소·PIN(열기) 또는 세션(`X-Share-Session` 머리글 — 주소에 묶인 30분 서명)을 본다. 일은 `src/services/pb_links.py`.

- 401 — 주소·PIN·세션이 맞지 않는다(늘 같은 말 — 무엇이 틀렸는지 말하지 않는다)
- 410 — 철회·만료·보관(담당 PB 에게 새 주소를) · 423 — 잠김(담당 PB 에게 다시 열어 달라고)
- 묻기 본문은 질문과 직전 문답뿐(`extra="forbid"` — 사실을 보낼 칸이 없다)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.auth import derived_key
from src.api.distribution_surface import require_distribution_open
from src.services import pb_links

router = APIRouter(prefix="/api/v1/share", tags=["share"])


def _key() -> bytes:
    return derived_key(pb_links.SESSION_PURPOSE)


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except pb_links.ShareDenied:
        raise HTTPException(401, pb_links.DENIED) from None
    except pb_links.ShareGone:
        raise HTTPException(410, pb_links.GONE) from None
    except pb_links.ShareLocked:
        raise HTTPException(423, pb_links.LOCKED) from None


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=1, max_length=128)
    pin: str = Field(..., min_length=1, max_length=12)


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=1, max_length=300)
    previous: dict[str, str] | None = None

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문이 비어 있어요")
        return v.strip()


@router.post("/open")
def open_link(body: OpenIn, _g: dict = Depends(require_distribution_open)):
    return _call(pb_links.open_session, body.token, body.pin, key=_key())


@router.get("/sheet")
def read_sheet(_g: dict = Depends(require_distribution_open),
               session: str | None = Header(None, alias="X-Share-Session")):
    return _call(pb_links.read_sheet, session, key=_key())


@router.post("/ask")
def ask(body: AskIn, _g: dict = Depends(require_distribution_open),
        session: str | None = Header(None, alias="X-Share-Session")):
    return _call(pb_links.ask, session, body.question, body.previous, key=_key())
