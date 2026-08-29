"""InvestmentDecision 스토어 — ★결정이 응답과 함께 사라지고 있었다★ (S1)
==============================================================================
설계: [`투자 결정 계층`](../../docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md)
관례: `research_runs` · `target_versions` · `execution_store` 의 방어적 raw-SQL idiom

## 왜 이 모듈이 생겼나

Phase 0 감사가 찾은 것: `rebalance_policy.rebalance_decision` 은 *"거래할 가치가
있는가"* 를 `효용 개선 > 비용 × (1+히스테리시스)` 로 **이미 판단하고 있었다.**
그런데 그 판단의 호출부가 API 라우트 하나뿐이고, ★결과가 어디에도 저장되지
않았다★. 응답과 함께 사라지므로 나중에 이렇게 물을 수 없다:

    "왜 그때 거래하지 않았나"
    "어느 종목이 가장 자주 무거래 밴드 밖이었나"
    "어느 제약이 가장 자주 구속했나"

## ★왜 테이블이 둘인가 — 이 저장소의 관례를 벗어난다★

이 저장소의 관례는 `execution_store` 처럼 **단일 테이블 + JSON 컬럼**이다
(`plan`·`pretrade`·`fills`·`audit`). 2테이블 선례는 **하나도 없다.**

그래도 둘로 나눈다. ★필요가 다르기 때문이다.★ `execution_plans.plan` 은 **통째로
읽히지** 계획 **간** 질의 대상이 아니다. 반면 이 계층의 존재 이유는 **결정 귀속**
이고, 위 셋째 질문("어느 종목이 가장 자주 밴드 밖이었나")은 **결정 간** 집계라
JSON 컬럼으로는 SQL 로 답할 수 없다. `tests/test_investment_decisions.py` 의
`test_legs_can_be_aggregated_across_decisions` 가 그 이유를 못 박는다 —
★그 테스트가 사라지면 두 테이블일 이유도 사라진다.★

## ★단위 — percent 이지 bps 가 아니다★

설계 초안은 `benefit_bps · cost_bps · hysteresis_bps` 라고 적었다. 상류
(`rebalance_policy`)의 실제 반환은 `benefit.gain_pct` · `cost.cost_pct` ·
`hysteresis_mult`(**배수**)다. 초안대로 만들었으면 저장 시 **100배 오류**가 조용히
들어갔을 것이다. ★상류 이름을 그대로 쓴다★ — 이름을 갈아 끼우면 상류가 바뀔 때
조용히 어긋난다.

## 이 모듈이 하지 않는 것

★계산하지 않는다.★ 받은 것을 그대로 담고 그대로 돌려준다. 결정을 **만드는** 합성
(`decide()`)은 S2 이고, 라우트 위임은 S3 다.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "investment_decisions"
_LEGS = "investment_decision_legs"

#: ★`code_version` 과 **다른 축**이다★ 전자는 빌드 식별자(GIT_SHA), 이것은 **결정
#: 로직의 판본**이다. 같은 값으로 두면 로직이 바뀌어도 기록이 그대로라 재현이
#: 거짓말이 된다. 판단 규칙(편익>비용 문턱·밴드 공식·status 의미)이 바뀌면 올린다.
DECISION_LOGIC_VERSION = "2026.1"

#: ★셋 말고는 없다★ `rebalance_policy` 의 상수와 같은 값이다. 오타가 조용히 새
#: 상태를 만들면 결정 간 질의가 갈라진다.
STATUS_TRADE = "trade"
STATUS_HOLD = "hold"
STATUS_UNDETERMINED = "undetermined"
_STATUSES = frozenset({STATUS_TRADE, STATUS_HOLD, STATUS_UNDETERMINED})

#: JSON 으로 담는 부모 필드 — 결정 **간** 질의 대상이 아닌 것들.
_JSON_PARENT = ("belief", "evidence", "gradual", "triggers")
#: 실수 컬럼 — ★전부 percent 또는 배수. 변환하지 않는다.★
_NUM_PARENT = ("gain_pct", "cost_pct", "hysteresis_mult", "threshold_pct",
               "net_pct", "max_gap_pct", "turnover_pct", "portfolio_value")

_LEG_NUM = ("current_w", "target_w", "delta_w",
            "half_width_pct", "low_pct", "high_pct")
_LEG_JSON = ("constraint_binding", "view_refs", "contribution")

_inited = False


def _engine(engine=None):
    if engine is not None:
        return engine
    try:
        from src.database import get_engine
        return get_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"엔진을 얻지 못했습니다: {e}")
        return None


def _ensure_tables(engine) -> bool:
    """두 테이블 보장. ★예외를 위로 던지지 않는다★(저장소 관례)."""
    global _inited
    from sqlalchemy import text
    try:
        with engine.begin() as c:
            c.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "dec_id VARCHAR(40) PRIMARY KEY, "
                "created_at DOUBLE PRECISION, as_of VARCHAR(10), "
                "case_id VARCHAR(40), scope VARCHAR(20), "
                "decision_status VARCHAR(16), reason TEXT, "
                "gain_pct DOUBLE PRECISION, cost_pct DOUBLE PRECISION, "
                "hysteresis_mult DOUBLE PRECISION, threshold_pct DOUBLE PRECISION, "
                "net_pct DOUBLE PRECISION, max_gap_pct DOUBLE PRECISION, "
                "turnover_pct DOUBLE PRECISION, portfolio_value DOUBLE PRECISION, "
                "belief TEXT, evidence TEXT, gradual TEXT, triggers TEXT, "
                "code_version VARCHAR(60), decision_version VARCHAR(20), note TEXT)"
            ))
            c.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_dec_case ON {_TABLE} "
                "(case_id, created_at)"))
            c.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_LEGS} ("
                "dec_id VARCHAR(40), ticker VARCHAR(12), "
                "current_w DOUBLE PRECISION, target_w DOUBLE PRECISION, "
                "delta_w DOUBLE PRECISION, half_width_pct DOUBLE PRECISION, "
                "low_pct DOUBLE PRECISION, high_pct DOUBLE PRECISION, "
                "outside_band BOOLEAN, constraint_binding TEXT, "
                "view_refs TEXT, contribution TEXT, "
                "PRIMARY KEY (dec_id, ticker))"
            ))
            c.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_leg_outside ON {_LEGS} "
                "(outside_band, ticker)"))
        _inited = True
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{_TABLE} 생성 실패: {e}")
        return False


def _new_id() -> str:
    return f"dec_{int(time.time())}_{secrets.token_hex(4)}"


def _dump(v) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _load(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return None


def _num(v) -> float | None:
    """★변환하지 않는다★ percent 를 bps 로 바꾸는 곳이 여기였다면 조용히 틀린다."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def save_decision(decision: dict[str, Any], legs: list[dict[str, Any]] | None = None, *,
                  case_id: str | None = None, note: str | None = None,
                  engine=None) -> str | None:
    """결정 + 자산별 leg 영속화. 성공 시 `dec_id`, 실패 시 `None`.

    ★거부하는 둘★
      · `decision_status` 가 셋 중 하나가 아니다
      · `reason` 이 비었다 — ★사유 없는 결정은 블랙박스다★ 나중에 "왜 거래하지
        않았나" 를 물을 수 있게 하는 것이 이 계층의 존재 이유 중 하나다.

    거부하면 **부모도 자식도 남기지 않는다**(반쪽 결정은 결정이 아니다).
    """
    from sqlalchemy import text

    status = str(decision.get("decision_status") or "")
    if status not in _STATUSES:
        logger.warning("알 수 없는 결정 상태입니다: %r — 저장하지 않습니다", status)
        return None
    reason = decision.get("reason")
    if not (isinstance(reason, str) and reason.strip()):
        logger.warning("사유 없는 결정은 저장하지 않습니다 (status=%s)", status)
        return None

    eng = _engine(engine)
    if eng is None or not _ensure_tables(eng):
        return None

    from src.engine.research_context import code_version

    dec_id = _new_id()
    parent = {
        "i": dec_id, "t": time.time(), "a": decision.get("as_of"),
        "ci": case_id if case_id is not None else decision.get("case_id"),
        "sc": decision.get("scope") or "portfolio",
        "st": status, "rs": reason.strip(),
        **{f"n_{k}": _num(decision.get(k)) for k in _NUM_PARENT},
        **{f"j_{k}": _dump(decision.get(k)) for k in _JSON_PARENT},
        "cv": code_version(), "dv": DECISION_LOGIC_VERSION, "no": note,
    }
    cols = ("dec_id, created_at, as_of, case_id, scope, decision_status, reason, "
            + ", ".join(_NUM_PARENT) + ", " + ", ".join(_JSON_PARENT)
            + ", code_version, decision_version, note")
    vals = (":i, :t, :a, :ci, :sc, :st, :rs, "
            + ", ".join(f":n_{k}" for k in _NUM_PARENT) + ", "
            + ", ".join(f":j_{k}" for k in _JSON_PARENT)
            + ", :cv, :dv, :no")

    leg_rows = []
    for leg in legs or []:
        ticker = str(leg.get("ticker") or "").strip()
        if not ticker:
            continue
        leg_rows.append({
            "i": dec_id, "tk": ticker,
            **{f"n_{k}": _num(leg.get(k)) for k in _LEG_NUM},
            "ob": bool(leg.get("outside_band")),
            **{f"j_{k}": _dump(leg.get(k)) for k in _LEG_JSON},
        })
    leg_cols = ("dec_id, ticker, " + ", ".join(_LEG_NUM)
                + ", outside_band, " + ", ".join(_LEG_JSON))
    leg_vals = (":i, :tk, " + ", ".join(f":n_{k}" for k in _LEG_NUM)
                + ", :ob, " + ", ".join(f":j_{k}" for k in _LEG_JSON))

    try:
        # ★한 트랜잭션★ 부모만 남고 자식이 사라지면 반쪽 결정이 된다.
        with eng.begin() as c:
            c.execute(text(f"INSERT INTO {_TABLE} ({cols}) VALUES ({vals})"), parent)
            if leg_rows:
                c.execute(text(f"INSERT INTO {_LEGS} ({leg_cols}) VALUES ({leg_vals})"),
                          leg_rows)
        return dec_id
    except Exception as e:  # noqa: BLE001
        logger.warning(f"결정 저장 실패: {e}")
        return None


_PARENT_COLS = (["dec_id", "created_at", "as_of", "case_id", "scope",
                 "decision_status", "reason"] + list(_NUM_PARENT)
                + list(_JSON_PARENT) + ["code_version", "decision_version", "note"])
_LEG_COLS = (["dec_id", "ticker"] + list(_LEG_NUM) + ["outside_band"]
             + list(_LEG_JSON))


def _parent_row(r) -> dict[str, Any]:
    d = dict(zip(_PARENT_COLS, r, strict=True))
    for k in _JSON_PARENT:
        d[k] = _load(d[k])
    return d


def _leg_row(r) -> dict[str, Any]:
    d = dict(zip(_LEG_COLS, r, strict=True))
    d["outside_band"] = bool(d["outside_band"])
    for k in _LEG_JSON:
        d[k] = _load(d[k])
    return d


def get_decision(dec_id: str, *, engine=None) -> dict[str, Any] | None:
    """결정 하나 + 그 leg 전부. 없으면 `None`."""
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None or not _ensure_tables(eng):
        return None
    try:
        with eng.connect() as c:
            row = c.execute(text(
                f"SELECT {', '.join(_PARENT_COLS)} FROM {_TABLE} WHERE dec_id = :i"),
                {"i": str(dec_id)}).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"결정 조회 실패: {e}")
        return None
    if row is None:
        return None
    out = _parent_row(row)
    out["legs"] = legs_of(dec_id, engine=eng)
    return out


def legs_of(dec_id: str, *, engine=None) -> list[dict[str, Any]]:
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None or not _ensure_tables(eng):
        return []
    try:
        with eng.connect() as c:
            rows = c.execute(text(
                f"SELECT {', '.join(_LEG_COLS)} FROM {_LEGS} "
                "WHERE dec_id = :i ORDER BY ticker"), {"i": str(dec_id)}).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"leg 조회 실패: {e}")
        return []
    return [_leg_row(r) for r in rows]


def list_decisions(*, case_id: str | None = None, status: str | None = None,
                   limit: int = 50, engine=None) -> list[dict[str, Any]]:
    """결정 **간** 질의. leg 는 붙이지 않는다(필요하면 `legs_of`)."""
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None or not _ensure_tables(eng):
        return []
    where, params = [], {"lim": max(1, int(limit))}
    if case_id:
        where.append("case_id = :ci")
        params["ci"] = str(case_id)
    if status:
        where.append("decision_status = :st")
        params["st"] = str(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        with eng.connect() as c:
            rows = c.execute(text(
                f"SELECT {', '.join(_PARENT_COLS)} FROM {_TABLE}{clause} "
                "ORDER BY created_at DESC LIMIT :lim"), params).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"결정 목록 조회 실패: {e}")
        return []
    return [_parent_row(r) for r in rows]


def outside_band_counts(*, case_id: str | None = None,
                        engine=None) -> dict[str, int]:
    """★두 테이블의 존재 이유★ — *"어느 종목이 가장 자주 무거래 밴드 밖이었나."*

    JSON 컬럼이었다면 SQL 로 답할 수 없는 질문이다. 이 함수가 사라지면 자식
    테이블을 따로 둘 이유도 사라진다.
    """
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None or not _ensure_tables(eng):
        return {}
    params: dict[str, Any] = {}
    join = ""
    if case_id:
        join = f" JOIN {_TABLE} p ON p.dec_id = l.dec_id AND p.case_id = :ci"
        params["ci"] = str(case_id)
    try:
        with eng.connect() as c:
            rows = c.execute(text(
                f"SELECT l.ticker, COUNT(*) FROM {_LEGS} l{join} "
                "WHERE l.outside_band = :ob GROUP BY l.ticker"),
                {**params, "ob": True}).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"밴드 이탈 집계 실패: {e}")
        return {}
    return {str(r[0]): int(r[1]) for r in rows}
