"""실계좌(LIVE) 관문 선언 — 저장·철회·이력 (BV7)
==============================================================================
`src/domain/live_gate.py`(BV1)는 판정만 한다. 이 모듈이 그 기록을 서버에 둔다 — 운영자가 관리자 경로로 선언하고,
선언한 사람은 토큰에서 온다.

## ★지우지 않는다★

새 선언은 옛 선언을 '철회'로 닫는다(누가·언제). 철회도 행을 지우지 않는다. "무슨 근거로 누구에게 실계좌를 열었나" 는
나중에 물을 수 있어야 한다 — 보존 분류는 ② 감사(`src/data/retention.py`).

## ★불완전한 선언은 저장하지 않는다★

빠진 항목이 있으면 `ValueError(빠진 항목)` — 저장해 두고 판정에서 막는 것보다, 선언하는 순간에 무엇이 빠졌는지 말한다.
"""
from __future__ import annotations

import datetime as dt
import json

from src.database import LiveGateDeclaration, session_scope
from src.domain.live_gate import AUTH_FIELDS, LiveAuthorization


def _row_dict(r: LiveGateDeclaration) -> dict:
    return {
        "basis": r.basis, "authority": r.authority, "reference_no": r.reference_no,
        "verified_at": r.verified_at, "scope": r.scope, "allowed_users": json.loads(r.allowed_users),
        "declared_by": r.declared_by, "declared_at": r.declared_at.isoformat() if r.declared_at else None,
        "revoked_by": r.revoked_by, "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
    }


def _active(s) -> LiveGateDeclaration | None:
    return (s.query(LiveGateDeclaration).filter(LiveGateDeclaration.revoked_at.is_(None))
            .order_by(LiveGateDeclaration.id.desc()).first())


def current() -> LiveAuthorization | None:
    """지금 유효한 선언. 없으면 `None`(= 관문 닫힘)."""
    with session_scope() as s:
        r = _active(s)
        if r is None:
            return None
        d = _row_dict(r)
    return LiveAuthorization(**{k: d[k] for k in AUTH_FIELDS if k != "allowed_users"},
                             allowed_users=tuple(d["allowed_users"]))


def current_record() -> dict | None:
    """선언 + 누가·언제 선언했는지(화면·응답용)."""
    with session_scope() as s:
        r = _active(s)
        return _row_dict(r) if r else None


def declare(by: str, *, basis: str, authority: str, reference_no: str, verified_at: str, scope: str,
            allowed_users: list[str]) -> dict:
    rec = LiveAuthorization(basis=basis, authority=authority, reference_no=reference_no,
                            verified_at=verified_at, scope=scope, allowed_users=tuple(allowed_users))
    missing = rec.missing()
    if missing:
        raise ValueError(f"확인 기록이 불완전해요. 빠진 항목: {', '.join(missing)}")
    now = dt.datetime.now(dt.timezone.utc)
    with session_scope() as s:
        old = _active(s)
        if old is not None:
            old.revoked_by, old.revoked_at = by, now
        row = LiveGateDeclaration(basis=basis, authority=authority, reference_no=reference_no,
                                  verified_at=verified_at, scope=scope,
                                  allowed_users=json.dumps(list(allowed_users), ensure_ascii=False),
                                  declared_by=by, declared_at=now)
        s.add(row)
        s.flush()
        return _row_dict(row)


def revoke(by: str) -> bool:
    """지금 선언을 닫는다. 없으면 False."""
    with session_scope() as s:
        r = _active(s)
        if r is None:
            return False
        r.revoked_by, r.revoked_at = by, dt.datetime.now(dt.timezone.utc)
    return True


def history(limit: int = 50) -> list[dict]:
    """최근 선언부터."""
    with session_scope() as s:
        return [_row_dict(r) for r in
                s.query(LiveGateDeclaration).order_by(LiveGateDeclaration.id.desc()).limit(limit)]
