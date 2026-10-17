"""ResearchRun 영속 저장 — 연구 결과의 재현성 단위 (Full Expansion Directive P1)
==============================================================================
"단순히 포트폴리오가 아니라 연구 실행(run)을 저장한다": 모든 중요한 결과가
run_id · 입력 파라미터 · 데이터 스냅샷 요약 · 코드 버전 · 생성 시각을 보존해
나중에 재조회·비교·재실행할 수 있게 한다.

설계 (기존 관례 재사용):
  · 테이블 research_runs — snapshot_db와 동일한 방어적 raw-SQL idiom.
    DB 미가용 시 조용히 실패(None/빈 목록) — 앱은 계속 동작(정직 보고는 API가).
  · inputs/outputs/snapshot 은 JSON 직렬화 TEXT. outputs 는 "재계산 가능한 큰
    산출물(프론티어 클라우드·MC bins)"을 제외한 요약만 저장 — 재현은 inputs 재실행으로.
  · run_id = "rr_" + 시각 + 난수 hex (충돌 무시 가능 수준).
  · code_version: GIT_SHA > APP_VERSION 환경변수 > "dev" (정직 — 서버가 스탬프).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "research_runs"
_inited = False
# Case 사슬 열(M1-S)이 실제로 붙었는지 — 못 붙으면 그 열 없이 동작한다.
_has_case_col = False
# 검정력 열(A5)이 실제로 붙었는지 — 같은 규율이다.
_has_power_cols = False

#: ★연구 실행의 검정력을 **질의 가능한 열**로 승격한다 (A5)★
#: JSON 안에만 있으면 "검정력 0.8 을 넘긴 런만" 같은 질문에 테이블이 답하지
#: 못하고 모든 행을 읽어 파싱해야 한다. 열은 **요약**이고 곡선·bracket·사유 같은
#: 원본은 `outputs.power_block` 에 그대로 남는다.
_POWER_COLS = [("mde", "DOUBLE PRECISION"), ("power", "DOUBLE PRECISION"),
               ("n_eff", "DOUBLE PRECISION"), ("target_power", "DOUBLE PRECISION"),
               ("seed", "BIGINT"), ("cost_bps", "DOUBLE PRECISION")]

# run 종류 (자유 문자열이지만 표준 값을 상수로 — 프론트와 계약)
KIND_ANALYZE = "allocation_analyze"
KIND_FACTOR = "factor_portfolio"
KIND_TIMING = "timing"
KIND_STRESS = "stress"


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure_table(engine) -> None:
    global _inited, _has_case_col, _has_power_cols
    if _inited:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "run_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, "
            "kind VARCHAR(40), "
            "name TEXT, "
            "inputs TEXT, "
            "outputs TEXT, "
            "snapshot TEXT, "
            "code_version VARCHAR(60), "
            "parent_run_id VARCHAR(40), "
            "note TEXT)"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_rr_kind_created ON {_TABLE} (kind, created_at)"
        ))

    # ── Case 사슬 (M1-S) ────────────────────────────────────────────────────
    # 역방향 링크. Case 는 `active_run_id` 로 지금을 가리키고, 그 Case 의 런 전체는
    # 여기서 되짚는다. `parent_run_id`(재현 사슬, P1)와는 다른 축이다 — 섞지 않는다.
    from src.data.schema_add_columns import add_columns
    _has_case_col = add_columns(engine, _TABLE, [("case_id", "VARCHAR(40)")],
                                label="research_runs.case_id")

    # ── 검정력 일급 필드 (A5) ───────────────────────────────────────────────
    # ★붙었다고 믿지 않는다★ `add_columns` 가 SELECT 로 확인해서 돌려준다.
    # 못 붙으면 그 열 없이 동작한다 — 있는 척하면 조회가 통째로 깨진다.
    _has_power_cols = add_columns(engine, _TABLE, _POWER_COLS,
                                  label="research_runs.power")
    _inited = True


# ★단일 출처★ 이 함수는 세 저장소에 **바이트 동일하게 복사**돼 있었다. 복사본이
# 넷이면 언젠가 하나는 갈라진다 — 실제로 `backtest_runs` 가 `APP_VERSION` 폴백을
# 잃은 채 갈라져 있었다. 여기서는 **재수출**한다(삭제하지 않는다) — 이 이름을
# 빌려 쓰는 호출자가 있어 공개 표면을 유지해야 한다.
from src.engine.research_context import code_version  # noqa: F401  (재수출)


def _new_run_id() -> str:
    return f"rr_{int(time.time())}_{secrets.token_hex(4)}"


def record_run(kind: str, inputs: dict[str, Any], outputs: dict[str, Any],
               snapshot: dict[str, Any] | None = None, name: str | None = None,
               parent_run_id: str | None = None, note: str | None = None,
               case_id: str | None = None, power_block: dict[str, Any] | None = None,
               seed: int | None = None, cost_bps: float | None = None) -> str | None:
    """연구 실행을 영속화. 성공 시 run_id, DB 미가용 시 None (호출자가 정직 보고).

    `power_block` 은 `research_power.power_report` 의 산출을 그대로 받는다 (A5).
    ★열은 요약이고 원본은 남는다★ — `mde`·`power`·`n_eff`·`target_power` 는
    질의 가능한 열로 올리고, 곡선·bracket·사유는 `outputs.power_block` 에 둔다.
    ★안 잰 검정력은 `None` 이다★ 0 으로 채우면 "검정력이 0 이었다" 는 하지 않은
    진술이 된다.
    """
    rid = _new_run_id()
    if power_block is not None:
        outputs = {**(outputs or {}), "power_block": power_block}
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        cols = ("run_id, created_at, kind, name, inputs, outputs, snapshot, "
                "code_version, parent_run_id, note")
        vals = ":rid, :ts, :kind, :name, :inp, :out, :snap, :ver, :parent, :note"
        extra: dict[str, Any] = {}
        if _has_case_col:
            cols += ", case_id"
            vals += ", :case"
            extra = {"case": case_id}
        if _has_power_cols:
            blk = power_block or {}
            cols += ", " + ", ".join(c for c, _ in _POWER_COLS)
            vals += ", " + ", ".join(f":{c}" for c, _ in _POWER_COLS)
            extra.update({
                "mde": blk.get("mde"), "power": blk.get("power"),
                "n_eff": blk.get("n_eff"),
                "target_power": blk.get("target_power"),
                "seed": (None if seed is None else int(seed)),
                "cost_bps": (None if cost_bps is None else float(cost_bps)),
            })
        with engine.begin() as c:
            c.execute(text(f"INSERT INTO {_TABLE} ({cols}) VALUES ({vals})"), {
                **extra,
                "rid": rid, "ts": time.time(), "kind": kind, "name": name,
                "inp": json.dumps(inputs, ensure_ascii=False, default=str),
                "out": json.dumps(outputs, ensure_ascii=False, default=str),
                "snap": json.dumps(snapshot or {}, ensure_ascii=False, default=str),
                "ver": code_version(), "parent": parent_run_id, "note": note,
            })
        return rid
    except Exception as e:
        logger.warning(f"research run 기록 실패: {e}")
        return None


_BASE_COL_LIST = ["run_id", "created_at", "kind", "name", "inputs", "outputs",
                  "snapshot", "code_version", "parent_run_id", "note"]


def _col_list() -> list[str]:
    """★위치 인덱스를 손으로 세지 않는다 (M1-S)★ `case_id`·검정력 열이 붙었는지
    여부로 인덱스가 밀리므로 이름 목록에서 파생시킨다."""
    return (_BASE_COL_LIST
            + (["case_id"] if _has_case_col else [])
            + ([c for c, _ in _POWER_COLS] if _has_power_cols else []))


def _row_to_dict(row, full: bool) -> dict[str, Any]:
    g = dict(zip(_col_list(), row, strict=False))

    def _j(raw, default):
        try:
            return json.loads(raw) if raw else default
        except Exception:
            return default

    d = {
        "run_id": g.get("run_id"), "created_at": g.get("created_at"),
        "kind": g.get("kind"), "name": g.get("name"),
        "code_version": g.get("code_version"),
        "parent_run_id": g.get("parent_run_id"), "note": g.get("note"),
        # Case 사슬 — 열이 없으면 None(있는 척하지 않는다)
        "case_id": g.get("case_id"),
        # ★검정력 — 열이 없거나 안 쟀으면 None. 0 이 아니다★
        # "검정력을 안 쟀다" 와 "검정력이 0 이었다" 는 완전히 다른 진술이다.
        **{c: g.get(c) for c, _ in _POWER_COLS},
    }
    d["snapshot"] = _j(g.get("snapshot"), {})
    if full:
        d["inputs"] = _j(g.get("inputs"), {})
        d["outputs"] = _j(g.get("outputs"), {})
    return d


def get_run(run_id: str) -> dict[str, Any] | None:
    """단건 전체 조회. **행이 없을 때만** `None` 이고, 저장소 장애는 올린다 (R0-S).

    ★예전에는 둘을 뭉갰다★ `except: return None` 이라 저장소가 죽어도 라우트가 404 로
    답했고, 화면은 "그 런은 삭제됐다" 고 말했다 — 기록은 멀쩡한데. 404 와 503 은
    사용자에게 완전히 다른 사실이므로 여기서 가른다.
    """
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    with engine.connect() as c:
        row = c.execute(text(
            f"SELECT {', '.join(_col_list())} FROM {_TABLE} WHERE run_id = :rid"
        ), {"rid": run_id}).fetchone()
    return _row_to_dict(row, full=True) if row else None


def list_runs(kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """목록 (요약 — inputs/outputs 제외, snapshot 포함). 최신순.

    ★예외를 삼키지 않는다 (R0-S)★ 예전에는 `except: return []` 이라 **저장소 장애와
    빈 목록이 같은 값**이었고, 화면은 둘 다 "기록된 런 없음" 으로 그렸다. 연구 기록이
    사라진 것처럼 보이는 것은 이 플랫폼에서 가장 겁나는 화면이다. 구분은 라우트가
    응답으로 표현한다.
    """
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    q = f"SELECT {', '.join(_col_list())} FROM {_TABLE} "
    params: dict[str, Any] = {"lim": max(1, min(int(limit), 200))}
    if kind:
        q += "WHERE kind = :kind "
        params["kind"] = kind
    q += "ORDER BY created_at DESC LIMIT :lim"
    with engine.connect() as c:
        rows = c.execute(text(q), params).fetchall()
    return [_row_to_dict(r, full=False) for r in rows]


def delete_run(run_id: str) -> bool:
    """지웠으면 True, 대상이 없으면 False. 저장소 장애는 올린다 (R0-S) —
    "지울 게 없었다" 와 "지우지 못했다" 는 다른 사실이다."""
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    with engine.begin() as c:
        res = c.execute(text(f"DELETE FROM {_TABLE} WHERE run_id = :rid"), {"rid": run_id})
    return bool(res.rowcount)
