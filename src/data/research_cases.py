"""ResearchCase — 연구 질문 하나를 감싸는 서버 영속 작업 단위 (M1-S)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
지금까지 "무엇을 연구 중인가"를 들고 있는 것은 **브라우저의 Study**(`storage.ts`,
`as_<ms>`, localStorage, 최대 30개)뿐이었다. 그래서 다른 브라우저에서 열면 진행 중인
연구가 사라지고, 서버에 있는 MES·TPV·Run 을 무엇이 묶는지 아무도 모른다.

`ResearchCase` 는 그 묶음을 서버에 둔다. Case 하나가 **연구 질문 하나**이고, 그 아래로
증거 사슬이 붙는다:

    rc_*  (질문)
      ├── rgs_*  MacroEvidenceSnapshot   — 결정 시점의 매크로 증거 (불변)
      ├── tpv_*  TargetPortfolioVersion  — 실행이 볼 목표 (불변)
      └── rr_*   ResearchRun             — 재현 가능한 실행 (P1)

★Study 와 합치지 않는다★
------------------------------------------------------------------------------
`as_*` 는 브라우저 로컬 초안이고 `rc_*` 는 서버 연구 단위다. 둘을 한 개념으로 합치면
"브라우저에만 있는 것"과 "서버에 있는 것"의 경계가 사라진다. 그 경계는 P4 가 Research
Index 에서 **라벨로** 지켜 온 계약이다(브라우저-로컬 스터디는 그렇게 적혀 있다).

★포인터는 현재값, 사슬은 역방향 컬럼★
------------------------------------------------------------------------------
이 테이블은 `active_*` 로 **지금**을 가리키고, 과거 전체는 `research_runs.case_id` ·
`target_portfolio_versions.case_id` 가 역방향으로 갖는다. 조인 테이블을 따로 두지 않는
이유는 그것이 세 번째 진실 공급원이 되기 때문이다.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "research_cases"
_inited = False

STATUS_OPEN = "open"
STATUS_ARCHIVED = "archived"


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure_table(engine) -> None:
    global _inited
    if _inited:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "case_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, "
            "updated_at DOUBLE PRECISION, "
            "name TEXT, "
            "question TEXT, "
            "status VARCHAR(16), "
            "market VARCHAR(16), "
            "universe_ref VARCHAR(80), "
            "active_mes_id VARCHAR(60), "
            "active_tpv_id VARCHAR(40), "
            "active_run_id VARCHAR(40), "
            "code_version VARCHAR(60), "
            "note TEXT)"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_rc_status_updated ON {_TABLE} (status, updated_at)"
        ))
    _inited = True


def _new_id() -> str:
    return f"rc_{int(time.time())}_{secrets.token_hex(4)}"


_COLS = ("case_id", "created_at", "updated_at", "name", "question", "status",
         "market", "universe_ref", "active_mes_id", "active_tpv_id",
         "active_run_id", "code_version", "note")

# `active_*` 만 갱신 대상이다. 질문·시장은 Case 의 신원이라 갱신 API 로 바꾸지 않는다 —
# 질문이 바뀌면 그건 **다른 연구**이고 새 Case 다.
_MUTABLE = ("name", "status", "active_mes_id", "active_tpv_id", "active_run_id", "note")


def _row_to_dict(row) -> dict[str, Any]:
    return dict(zip(_COLS, row, strict=False))


def create_case(name: str, question: str, *, market: str = "kr",
                universe_ref: str | None = None, note: str | None = None) -> str | None:
    """Case 를 만든다. 성공 시 `rc_*`, DB 미가용 시 None (호출자가 정직 보고)."""
    from src.data.research_runs import code_version

    cid = _new_id()
    now = time.time()
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} (case_id, created_at, updated_at, name, question, "
                "status, market, universe_ref, active_mes_id, active_tpv_id, active_run_id, "
                "code_version, note) VALUES "
                "(:i, :ca, :ua, :n, :q, :s, :m, :u, NULL, NULL, NULL, :cv, :note)"
            ), {"i": cid, "ca": now, "ua": now, "n": name.strip() or cid,
                "q": question.strip(), "s": STATUS_OPEN, "m": market,
                "u": universe_ref, "cv": code_version(), "note": note})
        return cid
    except Exception as e:
        logger.warning(f"research case 생성 실패: {e}")
        return None


def get_case(case_id: str) -> dict[str, Any] | None:
    """단건. **행이 없을 때만** None 이고 저장소 장애는 올린다 (R0-S 가 세운 분기).

    404 와 503 은 사용자에게 완전히 다른 사실이다 — "그 연구는 삭제됐다" 와
    "지금 읽지 못한다" 를 한 값으로 뭉개지 않는다.
    """
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    with engine.connect() as c:
        row = c.execute(text(
            f"SELECT {', '.join(_COLS)} FROM {_TABLE} WHERE case_id = :i"
        ), {"i": case_id}).fetchone()
    return _row_to_dict(row) if row else None


def list_cases(status: str | None = STATUS_OPEN, limit: int = 50) -> list[dict[str, Any]]:
    """최신순 목록. ★예외를 삼키지 않는다★ — 저장소 장애와 빈 목록은 다른 사실이고,
    그 구분은 라우트가 `available` 로 표현한다 (R0-S)."""
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    q = f"SELECT {', '.join(_COLS)} FROM {_TABLE} "
    params: dict[str, Any] = {"lim": max(1, min(int(limit), 200))}
    if status:
        q += "WHERE status = :st "
        params["st"] = status
    q += "ORDER BY updated_at DESC LIMIT :lim"
    with engine.connect() as c:
        rows = c.execute(text(q), params).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_case(case_id: str, **fields: Any) -> bool:
    """`_MUTABLE` 만 갱신. 대상이 없으면 False, 저장소 장애는 올린다.

    ★질문과 시장은 갱신하지 않는다★ 질문이 바뀌면 그것은 다른 연구다. 같은 Case 안에서
    질문을 갈아끼우면 그 아래 붙은 MES·TPV·Run 이 **무엇에 대한 증거인지** 사라진다.
    """
    use = {k: v for k, v in fields.items() if k in _MUTABLE}
    if not use:
        return False
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    sets = ", ".join(f"{k} = :{k}" for k in use)
    with engine.begin() as c:
        res = c.execute(text(
            f"UPDATE {_TABLE} SET {sets}, updated_at = :ua WHERE case_id = :i"
        ), {**use, "ua": time.time(), "i": case_id})
    return bool(res.rowcount)
