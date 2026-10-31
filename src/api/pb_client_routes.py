"""PB 고객 관리 — 목록 · 더하기 · 고치기 · 보관 · 고객별 설계 문서 (CF 3부 PB3)
==============================================================================
저장·소유 확인·개인정보 모양 검사는 `src/services/pb_clients.py` 가 한다. 이 파일은 그 앞의 문이다.

## ★소유자는 토큰에서만 온다★

본문에 `owner` 같은 칸이 없다(`extra="forbid"` — 넣으면 422). 남의 고객은 ★404★ — 없는 고객과 같은 답이다.
관리자에게도 우회는 없다(이 경로는 PB 본인의 일이다).

## ★지우는 경로가 없다★

보관(`/archive`)·다시 꺼내기(`/unarchive`)만 있다. 보관한 고객은 읽기만 된다(고치면 409).
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.auth import require_login
from src.api.distribution_surface import gate_view, require_distribution_open
from src.domain.auth_identity import Principal
from src.domain.investor_profile import PROFILE_SOURCES, RISK_TOLERANCE_LEVELS, SOURCE_UNKNOWN
from src.domain.pii_guard import ALIAS_MAX
from src.services import pb_clients as svc

router = APIRouter(prefix="/api/v1/pb/clients", tags=["pb-clients"])

_NOT_FOUND = "그 고객이 없어요."
_DATE = r"^\d{4}-\d{2}-\d{2}$"
_FORBID = ConfigDict(extra="forbid")


def _past_date(v: str | None) -> str | None:
    if v is None:
        return v
    try:
        d = dt.date.fromisoformat(v)
    except ValueError as e:
        raise ValueError("평가일을 읽을 수 없어요 — YYYY-MM-DD 로 적어 주세요.") from e
    if d > dt.date.today():
        raise ValueError("평가일이 미래예요 — 성향을 평가한 날을 적어 주세요.")
    return v


class ClientIn(BaseModel):
    model_config = _FORBID
    alias: str = Field(..., min_length=1, max_length=ALIAS_MAX)
    risk_tolerance: Literal[RISK_TOLERANCE_LEVELS] | None = None
    profile_source: Literal[PROFILE_SOURCES] = SOURCE_UNKNOWN
    assessed_at: str | None = Field(None, pattern=_DATE)
    horizon_years: float | None = Field(None, ge=0, le=80)

    @field_validator("alias")
    @classmethod
    def _alias(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("별칭을 적어 주세요 — 실명·연락처 말고 PB 가 알아볼 이름이에요.")
        return v

    @field_validator("assessed_at")
    @classmethod
    def _when(cls, v: str | None) -> str | None:
        return _past_date(v)


class ClientPatch(BaseModel):
    """적은 칸만 바꾼다 — `null` 은 '모름으로 되돌리기'(별칭은 비울 수 없다)."""
    model_config = _FORBID
    alias: str | None = Field(None, min_length=1, max_length=ALIAS_MAX)
    risk_tolerance: Literal[RISK_TOLERANCE_LEVELS] | None = None
    profile_source: Literal[PROFILE_SOURCES] | None = None
    assessed_at: str | None = Field(None, pattern=_DATE)
    horizon_years: float | None = Field(None, ge=0, le=80)

    @field_validator("assessed_at")
    @classmethod
    def _when(cls, v: str | None) -> str | None:
        return _past_date(v)


class DocIn(BaseModel):
    model_config = _FORBID
    name: str = Field(..., min_length=1, max_length=svc.DOC_NAME_MAX)
    graph: dict


class DocSave(BaseModel):
    model_config = _FORBID
    graph: dict
    name: str | None = Field(None, min_length=1, max_length=svc.DOC_NAME_MAX)


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except svc.ClientNotFound:
        raise HTTPException(404, _NOT_FOUND) from None
    except (svc.ClientArchived, svc.SheetShared) as e:
        raise HTTPException(409, str(e)) from None
    except svc.DocTooLarge as e:
        raise HTTPException(413, str(e)) from None
    except svc.SheetRefused as e:
        raise HTTPException(409 if e.code == "stale" else 422, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("")
def list_clients(archived: bool = Query(False), p: Principal = Depends(require_login)):
    return {"clients": svc.list_clients(p.username, archived=archived)}


@router.post("", status_code=201)
def create_client(body: ClientIn, p: Principal = Depends(require_login)):
    return _call(svc.create, p.username, **body.model_dump())


@router.get("/{cid}")
def get_client(cid: str, p: Principal = Depends(require_login)):
    return _call(svc.get, p.username, cid)


@router.patch("/{cid}")
def update_client(cid: str, body: ClientPatch, p: Principal = Depends(require_login)):
    changes = body.model_dump(exclude_unset=True)
    if "alias" in changes:
        if changes["alias"] is None or not changes["alias"].strip():
            raise HTTPException(422, "별칭은 비울 수 없어요.")
        changes["alias"] = changes["alias"].strip()
    if "profile_source" in changes and changes["profile_source"] is None:
        changes["profile_source"] = SOURCE_UNKNOWN
    return _call(svc.update, p.username, cid, changes)


@router.post("/{cid}/archive")
def archive_client(cid: str, p: Principal = Depends(require_login)):
    return _call(svc.set_archived, p.username, cid, True)


@router.post("/{cid}/unarchive")
def unarchive_client(cid: str, p: Principal = Depends(require_login)):
    return _call(svc.set_archived, p.username, cid, False)


@router.post("/{cid}/docs", status_code=201)
def create_doc(cid: str, body: DocIn, p: Principal = Depends(require_login)):
    return _call(svc.create_doc, p.username, cid, name=body.name.strip(), graph=body.graph)


@router.get("/{cid}/docs/{did}")
def get_doc(cid: str, did: str, p: Principal = Depends(require_login)):
    return _call(svc.get_doc, p.username, cid, did)


@router.put("/{cid}/docs/{did}")
def save_doc(cid: str, did: str, body: DocSave, p: Principal = Depends(require_login)):
    return _call(svc.save_doc, p.username, cid, did, graph=body.graph,
                 name=body.name.strip() if body.name is not None else None)


# ── 고객 한 장 (PB4) ─────────────────────────────────────────────────────

class SheetIn(BaseModel):
    """한 장 만들기 — 서버가 다시 계산하고, ★모든 노드의★ `view_hash` 가 `preview`(PB 가 본 계산 — 노드 id → 해시, 계산 못 한
    노드는 null)와 같을 때만 둔다."""
    model_config = _FORBID
    graph: dict
    focus_node_id: str = Field(..., min_length=1, max_length=64)
    preview: dict[str, str | None] = Field(..., max_length=500)
    title: str = Field(..., min_length=1, max_length=svc.DOC_NAME_MAX)
    doc_id: str | None = Field(None, max_length=32)


class SheetAsk(BaseModel):
    model_config = _FORBID
    question: str = Field(..., min_length=1, max_length=300)
    previous: dict[str, str] | None = None

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문이 비어 있어요")
        return v.strip()


def _recompute(graph, focus, preview):
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    return pg.run_for_sheet(graph, focus, preview, gn.REGISTRY)


@router.post("/{cid}/snapshots", status_code=201)
def create_sheet(cid: str, body: SheetIn, p: Principal = Depends(require_login)):
    from src.api import allocation_graph_routes as graph_routes
    return _call(svc.create_sheet, p.username, cid, graph=body.graph, focus_node_id=body.focus_node_id,
                 preview=body.preview, title=body.title.strip(), doc_id=body.doc_id,
                 recompute=_recompute, kinds=graph_routes._kinds())


@router.get("/{cid}/snapshots")
def list_sheets(cid: str, p: Principal = Depends(require_login)):
    return {"sheets": _call(svc.list_sheets, p.username, cid)}


@router.get("/{cid}/snapshots/{sid}")
def get_sheet(cid: str, sid: str, p: Principal = Depends(require_login)):
    return _call(svc.get_sheet, p.username, cid, sid)


@router.delete("/{cid}/snapshots/{sid}")
def delete_sheet(cid: str, sid: str, p: Principal = Depends(require_login)):
    return _call(svc.delete_sheet, p.username, cid, sid)


@router.post("/{cid}/snapshots/{sid}/ask")
def ask_sheet(cid: str, sid: str, body: SheetAsk, p: Principal = Depends(require_login)):
    """PB 가 고객 AI 를 미리 물어본다 — 근거는 서버가 저장한 그 한 장의 줄뿐 · 고객용 고정 문장 · 한도는 PB 의 그릇."""
    from src.services.canvas_assist import service as assist
    got = _call(svc.get_sheet, p.username, cid, sid)
    return assist.ask_sheet(got["sheet"], sid, body.question, body.previous, p.username)


# ── 고객 주소 (PB6 · ★유통 관문 뒤★) ─────────────────────────────────────────
# 여는 것(만들기·다시 열기·한 장 바꾸기)은 로그인 다음 ★관문 → 조회★ 차례(`distribution_surface` — 의존성은 적힌 차례로 돈다).
# 로그인이 먼저인 까닭: 보호 등록부 계약(익명은 401). 관문은 조회보다 먼저라 닫혀 있으면 무엇이 있는지 드러내지 않는다. 닫는 것(목록·철회)은 늘 된다.

class LinkIn(BaseModel):
    model_config = _FORBID
    sheet_id: str = Field(..., min_length=1, max_length=32)
    pin: str = Field(..., min_length=1, max_length=12)
    days: int


class LinkPatch(BaseModel):
    model_config = _FORBID
    sheet_id: str = Field(..., min_length=1, max_length=32)


def _link_call(fn, *args, **kw):
    from src.services import pb_links
    try:
        return _call(fn, *args, **kw)
    except pb_links.LinkNotFound:
        raise HTTPException(404, "그 주소가 없어요.") from None
    except pb_links.LinkClosed as e:
        raise HTTPException(409, str(e)) from None


@router.post("/{cid}/share-links", status_code=201)
def create_link(cid: str, body: LinkIn, p: Principal = Depends(require_login),
                _g: dict = Depends(require_distribution_open)):
    from src.services import pb_links
    return _link_call(pb_links.create_link, p.username, cid, sheet_id=body.sheet_id, pin=body.pin, days=body.days)


@router.get("/{cid}/share-links")
def list_links(cid: str, p: Principal = Depends(require_login)):
    from src.services import pb_links
    return {"gate": gate_view(), "links": _link_call(pb_links.list_links, p.username, cid)}


@router.patch("/{cid}/share-links/{lid}")
def change_link_sheet(cid: str, lid: str, body: LinkPatch, p: Principal = Depends(require_login),
                      _g: dict = Depends(require_distribution_open)):
    from src.services import pb_links
    return _link_call(pb_links.change_sheet, p.username, cid, lid, body.sheet_id)


@router.post("/{cid}/share-links/{lid}/reopen")
def reopen_link(cid: str, lid: str, p: Principal = Depends(require_login),
                _g: dict = Depends(require_distribution_open)):
    from src.services import pb_links
    return _link_call(pb_links.reopen_link, p.username, cid, lid)


@router.post("/{cid}/share-links/{lid}/revoke")
def revoke_link(cid: str, lid: str, p: Principal = Depends(require_login)):
    from src.services import pb_links
    return _link_call(pb_links.revoke_link, p.username, cid, lid)
