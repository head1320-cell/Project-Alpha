"""유통 관문 선언 — 저장·철회·이력 (CF 3부 PB5 · BV7 `live_gate_store` 와 같은 모양)
==============================================================================
`src/domain/distribution_gate.py`(AE1)는 판정만 한다. 이 모듈이 그 기록을 서버에 둔다 — 운영자가 관리자 경로로 선언하고,
선언한 사람은 토큰에서 온다. 유통 표면(PB6 고객 주소·고객 화면·고객 AI)은 ★매 요청 맨 앞에서 `gate()` 를 지난다★.

## ★판정은 관문이 한다★

`gate()` 는 지금 행을 `LicenseRecord` 로 옮겨 `distribution_gate` 에 넘길 뿐이다 — 손으로 넣은 빈 칸이 든 행도 관문이 막는다.
행이 없으면 `distribution_gate()`(인자 없음) = 막힘. 환경변수는 읽지 않는다(뒷문 없음).

## ★지우지 않는다 · 불완전한 선언은 저장하지 않는다★

새 선언은 옛 선언을 '철회'로 닫는다(누가·언제). 철회도 행을 지우지 않는다 — 보존 ② 감사(`src/data/retention.py`).
빠진 항목이 있으면 `ValueError(빠진 항목)` — 선언하는 순간에 무엇이 빠졌는지 말한다.
"""
from __future__ import annotations

import datetime as dt

from src.database import DistributionGateDeclaration, session_scope
from src.domain.distribution_gate import LICENSE_FIELDS, LicenseRecord, distribution_gate


def _row_dict(r: DistributionGateDeclaration) -> dict:
    return {
        **{k: getattr(r, k) for k in LICENSE_FIELDS},
        "declared_by": r.declared_by, "declared_at": r.declared_at.isoformat() if r.declared_at else None,
        "revoked_by": r.revoked_by, "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
    }


def _active(s) -> DistributionGateDeclaration | None:
    return (s.query(DistributionGateDeclaration).filter(DistributionGateDeclaration.revoked_at.is_(None))
            .order_by(DistributionGateDeclaration.id.desc()).first())


def current() -> LicenseRecord | None:
    """지금 유효한 선언. 없으면 `None`(= 관문 닫힘)."""
    with session_scope() as s:
        r = _active(s)
        if r is None:
            return None
        d = _row_dict(r)
    return LicenseRecord(**{k: d[k] for k in LICENSE_FIELDS})


def gate() -> dict:
    """유통해도 되는가 — 지금 선언으로 `distribution_gate` 가 판정한다. 유통 경로는 이것을 맨 앞에서 부른다."""
    return distribution_gate(current())


def current_record() -> dict | None:
    """선언 + 누가·언제 선언했는지(응답용)."""
    with session_scope() as s:
        r = _active(s)
        return _row_dict(r) if r else None


def declare(by: str, **fields: str) -> dict:
    rec = LicenseRecord(**{k: fields.get(k) for k in LICENSE_FIELDS})
    missing = rec.missing()
    if missing:
        raise ValueError(f"인가 기록이 불완전해요. 빠진 항목: {', '.join(missing)}")
    now = dt.datetime.now(dt.timezone.utc)
    with session_scope() as s:
        old = _active(s)
        if old is not None:
            old.revoked_by, old.revoked_at = by, now
        row = DistributionGateDeclaration(**rec.to_dict(), declared_by=by, declared_at=now)
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
                s.query(DistributionGateDeclaration).order_by(DistributionGateDeclaration.id.desc()).limit(limit)]
