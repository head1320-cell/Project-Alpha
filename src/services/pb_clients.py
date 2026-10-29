"""PB 고객·고객별 설계 문서 (CF 3부 PB3) — ★PB 본인 고객만 · 별칭만 · 지우지 않고 보관★
==============================================================================
계획 PB3 · 사용자 결정(2026-10-23): 고객 자료는 서버 DB 새 표(`pb_clients`·`pb_client_docs`) — PB 가 정한 별칭만.

## ★모든 조회가 소유자로 거른다★

`_owned` 하나가 고객 행을 꺼낸다 — 소유자가 다르거나 없는 고객이면 똑같이 `ClientNotFound`(경로가 404 로 옮긴다 — 있는지조차
드러내지 않는다). 문서는 ★그 고객의 문서일 때만★ 꺼낸다(같은 PB 라도 다른 고객의 문서 id 로는 꺼내지 않는다).

## ★개인정보 모양은 받지 않는다★

별칭 · 문서 이름 · 문서 안 고객 노드(`client_profile`)의 별칭에 전화·이메일·주민번호·긴 숫자열 모양이면 `ValueError(사유)`.
실명은 모양으로 알 수 없다 — 화면이 적지 말라고 안내한다(`src/domain/pii_guard.py`).

## ★지우지 않는다 · 보관하면 읽기만★

지우는 함수가 없다. 보관한 고객은 목록에서 숨고, 고치기·문서 만들기·저장은 `ClientArchived` 로 막힌다(읽기는 된다).

## 문서는 그대로 둔다

그래프 문서 모양(format·version·nodes·edges)만 확인한다 — 검증 오류가 있는 작업 중 그래프도 저장된다(계산하면 서버가 말한다).
직렬화한 크기 512KB 상한.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from typing import Any

from src.database import PbClient, PbClientDoc, session_scope
from src.domain.pii_guard import ALIAS_MAX, pii_reason
from src.engine import portfolio_graph as pg

#: 문서 한 개의 직렬화 크기 상한(바이트).
DOC_MAX_BYTES = 512 * 1024
#: 문서 이름 길이 상한(표의 열 폭과 같다).
DOC_NAME_MAX = 80
#: 고칠 수 있는 고객 칸 — 그 밖의 칸은 서비스가 받지 않는다(소유자·보관은 따로).
CLIENT_FIELDS = ("alias", "risk_tolerance", "profile_source", "assessed_at", "horizon_years")


class ClientNotFound(LookupError):
    """그런 고객(또는 그 고객의 문서)이 없다 — 남의 것이어도 같다."""


class ClientArchived(RuntimeError):
    """보관한 고객이라 고칠 수 없다."""


class DocTooLarge(ValueError):
    """문서가 상한보다 크다."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime | None) -> str | None:
    return t.isoformat() if t else None


def _age_days(assessed_at: str | None) -> int | None:
    if not assessed_at:
        return None
    return (dt.date.today() - dt.date.fromisoformat(assessed_at)).days


def _check_text(what: str, text: str, max_len: int = ALIAS_MAX) -> None:
    why = pii_reason(text, label=what, max_len=max_len)
    if why:
        raise ValueError(why)


def _check_graph(graph: Any) -> str:
    """모양 확인 + 문서 안 고객 노드 별칭 확인 → 직렬화한 문자열."""
    errs = pg._document_errors(graph)
    if errs:
        raise ValueError(" ".join(e["message"] for e in errs))
    for n in graph["nodes"]:
        if isinstance(n, dict) and n.get("type") == "client_profile":
            alias = (n.get("params") or {}).get("alias")
            if isinstance(alias, str):
                _check_text("문서 안 고객 노드의 별칭", alias)
    text = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    size = len(text.encode("utf-8"))
    if size > DOC_MAX_BYTES:
        raise DocTooLarge(f"문서가 {size // 1024}KB 예요 — 고객 문서는 {DOC_MAX_BYTES // 1024}KB 까지 둘 수 있어요.")
    return text


def _client_dict(r: PbClient, docs: list[PbClientDoc]) -> dict:
    return {
        "client_id": r.client_id, "alias": r.alias, "risk_tolerance": r.risk_tolerance,
        "profile_source": r.profile_source, "assessed_at": r.assessed_at, "assessed_age_days": _age_days(r.assessed_at),
        "horizon_years": r.horizon_years, "archived": r.archived_at is not None, "archived_at": _iso(r.archived_at),
        "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
        "doc_count": len(docs), "last_doc_at": _iso(max((d.updated_at for d in docs), default=None)),
    }


def _doc_meta(d: PbClientDoc) -> dict:
    return {"doc_id": d.doc_id, "client_id": d.client_id, "name": d.name,
            "created_at": _iso(d.created_at), "updated_at": _iso(d.updated_at)}


def _owned(s, owner: str, client_id: str) -> PbClient:
    r = s.query(PbClient).filter(PbClient.client_id == client_id, PbClient.owner_username == owner).first()
    if r is None:
        raise ClientNotFound(client_id)
    return r


def _writable(s, owner: str, client_id: str) -> PbClient:
    r = _owned(s, owner, client_id)
    if r.archived_at is not None:
        raise ClientArchived("보관한 고객이에요 — 다시 꺼낸 뒤 고쳐 주세요.")
    return r


def _docs_of(s, client_id: str) -> list[PbClientDoc]:
    return s.query(PbClientDoc).filter(PbClientDoc.client_id == client_id).order_by(PbClientDoc.updated_at.desc()).all()


# ── 고객 ────────────────────────────────────────────────────────────────

def create(owner: str, *, alias: str, risk_tolerance: str | None = None, profile_source: str = "unknown",
           assessed_at: str | None = None, horizon_years: float | None = None) -> dict:
    _check_text("별칭", alias)
    now = _now()
    with session_scope() as s:
        r = PbClient(client_id="cl_" + secrets.token_hex(8), owner_username=owner, alias=alias,
                     risk_tolerance=risk_tolerance, profile_source=profile_source, assessed_at=assessed_at,
                     horizon_years=horizon_years, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        return _client_dict(r, [])


def list_clients(owner: str, *, archived: bool = False) -> list[dict]:
    with session_scope() as s:
        q = s.query(PbClient).filter(PbClient.owner_username == owner)
        q = q.filter(PbClient.archived_at.isnot(None) if archived else PbClient.archived_at.is_(None))
        return [_client_dict(r, _docs_of(s, r.client_id)) for r in q.order_by(PbClient.updated_at.desc()).all()]


def get(owner: str, client_id: str) -> dict:
    with session_scope() as s:
        r = _owned(s, owner, client_id)
        docs = _docs_of(s, r.client_id)
        return {**_client_dict(r, docs), "docs": [_doc_meta(d) for d in docs]}


def update(owner: str, client_id: str, changes: dict) -> dict:
    """`changes` 에 든 칸만 바꾼다 — `None` 은 '모름으로 되돌리기'(별칭은 비울 수 없다)."""
    unknown = set(changes) - set(CLIENT_FIELDS)
    if unknown:
        raise ValueError(f"고칠 수 없는 칸이에요: {', '.join(sorted(unknown))}")
    if "alias" in changes:
        _check_text("별칭", changes["alias"])
    with session_scope() as s:
        r = _writable(s, owner, client_id)
        for k, v in changes.items():
            setattr(r, k, v)
        r.updated_at = _now()
        s.flush()
        return _client_dict(r, _docs_of(s, r.client_id))


def set_archived(owner: str, client_id: str, archived: bool) -> dict:
    with session_scope() as s:
        r = _owned(s, owner, client_id)
        r.archived_at = _now() if archived else None
        s.flush()
        return _client_dict(r, _docs_of(s, r.client_id))


# ── 설계 문서 ────────────────────────────────────────────────────────────

def create_doc(owner: str, client_id: str, *, name: str, graph: Any) -> dict:
    _check_text("문서 이름", name, DOC_NAME_MAX)
    text = _check_graph(graph)
    now = _now()
    with session_scope() as s:
        c = _writable(s, owner, client_id)
        d = PbClientDoc(doc_id="cd_" + secrets.token_hex(8), client_id=c.client_id, name=name, graph=text,
                        created_at=now, updated_at=now)
        s.add(d)
        c.updated_at = now
        s.flush()
        return _doc_meta(d)


def _owned_doc(s, owner: str, client_id: str, doc_id: str) -> tuple[PbClient, PbClientDoc]:
    c = _owned(s, owner, client_id)
    d = s.query(PbClientDoc).filter(PbClientDoc.doc_id == doc_id, PbClientDoc.client_id == c.client_id).first()
    if d is None:
        raise ClientNotFound(doc_id)
    return c, d


def get_doc(owner: str, client_id: str, doc_id: str) -> dict:
    with session_scope() as s:
        c, d = _owned_doc(s, owner, client_id, doc_id)
        return {**_doc_meta(d), "graph": json.loads(d.graph), "client_alias": c.alias,
                "client_archived": c.archived_at is not None}


def save_doc(owner: str, client_id: str, doc_id: str, *, graph: Any, name: str | None = None) -> dict:
    if name is not None:
        _check_text("문서 이름", name, DOC_NAME_MAX)
    text = _check_graph(graph)
    with session_scope() as s:
        c, d = _owned_doc(s, owner, client_id, doc_id)
        if c.archived_at is not None:
            raise ClientArchived("보관한 고객이에요 — 다시 꺼낸 뒤 고쳐 주세요.")
        d.graph = text
        if name is not None:
            d.name = name
        d.updated_at = c.updated_at = _now()
        s.flush()
        return _doc_meta(d)
