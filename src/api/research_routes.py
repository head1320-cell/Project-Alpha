"""ResearchRun API — 연구 실행 저장·조회·비교 (Full Expansion Directive P1)

POST /api/v1/research-runs           — 실행 기록 (kind·inputs·outputs·snapshot)
GET  /api/v1/research-runs           — 목록 (kind 필터·limit, 요약)
GET  /api/v1/research-runs/{run_id}  — 단건 전체 (inputs/outputs 포함)
DELETE /api/v1/research-runs/{run_id}

기록 실패(DB 미가용)는 조용히 성공으로 위장하지 않고 recorded=False 로 정직 보고.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.research")

router = APIRouter(prefix="/api/v1/research-runs", tags=["research-runs"])


class ReproduceRequest(BaseModel):
    record: bool = False        # 재현 결과를 자식 런으로 남길지 (기본 off — 조회는 흔하다)


class RecordRunRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=40)
    name: str | None = Field(None, max_length=200)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] | None = None
    parent_run_id: str | None = None
    # Case 사슬 (M1-V 배선) — `record_run` 은 이미 받는데 라우트가 넘기지 않았다.
    case_id: str | None = Field(None, max_length=40)
    note: str | None = Field(None, max_length=2000)


@router.post("")
def create_run(req: RecordRunRequest):
    try:
        from src.data.research_runs import record_run
        rid = record_run(req.kind, req.inputs, req.outputs, snapshot=req.snapshot,
                         name=req.name, parent_run_id=req.parent_run_id,
                         case_id=req.case_id, note=req.note)
        if rid is None:
            return {"recorded": False, "run_id": None,
                    "message": "DB 미가용 — 런이 저장되지 않았습니다."}
        return {"recorded": True, "run_id": rid}
    except Exception:
        logger.exception("research run 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("")
def list_all(kind: str | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    """★빈 목록과 저장소 장애를 **다른 응답**으로 답한다 (R0-S)★

    예전에는 저장소가 죽어도 `{"runs": []}` 였고, 화면은 "기록된 런 없음" 으로 그렸다 —
    연구 기록이 사라진 것처럼 보이는 위험이 그대로 있었다. 이제 `available` 로 가른다.
    `runs` 키는 유지한다 — 기존 소비자와 스펙이 깨지지 않는다.
    HTTP 는 200 이다: 화면이 사유를 그려야 하므로(`recorded:false` 와 같은 관례).
    """
    from src.data.research_runs import list_runs
    try:
        return {"available": True, "runs": list_runs(kind=kind, limit=limit)}
    except Exception as e:
        logger.warning(f"research run 목록 실패: {e}")
        return {"available": False, "runs": [],
                "reason": "연구 기록 저장소를 읽을 수 없습니다 — 기록이 없는 것과 다릅니다."}


@router.get("/{run_id}")
def get_one(run_id: str):
    try:
        from src.data.research_runs import get_run
        d = get_run(run_id)
        if d is None:
            raise HTTPException(404, "런을 찾을 수 없습니다.")
        return d
    except HTTPException:
        raise
    except Exception:
        # ★404 로 답하지 않는다 (R0-S)★ 그러면 화면이 "그 런은 삭제됐다" 고 말한다.
        logger.warning(f"research run 조회 실패: {run_id}")
        raise HTTPException(503, "연구 기록 저장소를 읽을 수 없습니다 — 런이 없는 것과 다릅니다.")


# ── 재현 (P1-C) ───────────────────────────────────────────────────────────────
_REPRO_KIND = "allocation_analyze"
_REPRO_CHILD_KIND = "allocation_reproduce"
_TOL_PP = 0.01          # 반올림(소수 2자리 %)이 만드는 잡음 이하 → 동일로 본다


def _pick_as_of(run: dict) -> tuple[str | None, str, bool, str | None]:
    """재현 기준일을 고른다 → (as_of, basis, estimated, reason).

    ★세 단계는 서로 다른 강도의 주장이다★
      1. `inputs.as_of`         — 사용자가 그때 **고정한** 날짜. 가장 강하다.
      2. `coverage.as_of_effective` — 서버가 그때 **실제로 쓴** 절단일 (P1-A 스탬프).
      3. `coverage.end`         — 관측 마지막 날. 절단일과 다를 수 있다(휴장일이면 앞선다)
                                  → **추정 재현**이라고 화면이 말해야 한다.
    셋 다 없으면 재현하지 않는다 — 오늘로 돌려 놓고 "재현했다" 고 적는 것이 가장 나쁘다.
    """
    inp = run.get("inputs") or {}
    cov = (run.get("snapshot") or {}).get("coverage") or {}
    if inp.get("as_of"):
        return str(inp["as_of"]), "recorded_as_of", False, None
    if cov.get("as_of_effective"):
        return str(cov["as_of_effective"]), "server_stamped", False, None
    if cov.get("end"):
        return str(cov["end"]), "coverage_end", True, None
    return (None, "none", False,
            "이 런에는 재현 좌표가 없습니다 — as_of 도, 서버가 쓴 절단일도, 관측 구간도 "
            "기록돼 있지 않습니다. P1 이전에 만들어진 런일 수 있습니다.")


@router.post("/{run_id}/reproduce")
def reproduce_one(run_id: str, req: ReproduceRequest | None = None):
    """기록된 런을 **같은 코드로 다시 돌려** 결과를 대조한다 (P1-C).

    `/analyze` 와 같은 `run_analyze()` 를 부른다 — 사본을 만들면 재현이 원본과 다른
    코드로 계산하게 되고, 그것은 재현이 아니다.

    정직성 규칙 셋:
      · 재현 좌표가 없으면 `reproducible: false` + 사유. 오늘로 돌리지 않는다.
      · 기록된 비중이 없으면 `verdict: "incomparable"` + 사유. 초록으로 위장하지 않는다.
      · 자산이 유니버스에서 빠진 것은 "비중이 0 이 됐다" 가 **아니다** —
        `universe_changed` 로 따로 보고하고 `deltas` 에는 넣지 않는다.
    """
    opts = req or ReproduceRequest()
    try:
        from src.data.research_runs import get_run
        run = get_run(run_id)
    except HTTPException:
        raise
    except Exception:
        logger.warning(f"research run 조회 실패(재현): {run_id}")
        raise HTTPException(503, "연구 기록 저장소를 읽을 수 없습니다 — 런이 없는 것과 다릅니다.")
    if run is None:
        raise HTTPException(404, "런을 찾을 수 없습니다.")

    kind = run.get("kind")
    if kind != _REPRO_KIND:
        return {"reproducible": False, "run_id": run_id, "kind": kind,
                "reason": f"이 종류는 아직 재현 경로가 없습니다: {kind}. "
                          f"현재는 {_REPRO_KIND} 만 재현합니다."}

    as_of, basis, estimated, why = _pick_as_of(run)
    if as_of is None:
        return {"reproducible": False, "run_id": run_id, "kind": kind,
                "basis": basis, "reason": why}

    inputs = run.get("inputs") or {}
    try:
        from src.api.allocation_routes import AnalyzeRequest, run_analyze
        # 기록된 입력을 그대로 쓰되 절단일만 고정한다. 기록/재기록은 여기서 하지 않는다 —
        # 재현이 원본을 덮어쓰거나 새 부모 런을 만들면 안 된다.
        payload = dict(inputs)
        payload.update({"as_of": as_of, "record_run": False, "run_name": None})
        fresh = run_analyze(AnalyzeRequest(**payload))
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"재현 실행 실패: {run_id}: {e}")
        return {"reproducible": False, "run_id": run_id, "kind": kind, "basis": basis,
                "as_of": as_of, "estimated": estimated,
                "reason": f"기록된 입력으로 다시 돌리지 못했습니다: {e}"}

    if fresh.get("error"):
        return {"reproducible": False, "run_id": run_id, "kind": kind, "basis": basis,
                "as_of": as_of, "estimated": estimated,
                "reason": f"재실행이 결과를 내지 못했습니다: {fresh.get('message')}"}

    rec_w = ((run.get("outputs") or {}).get("weights") or {}).get("optimized")
    new_w = (fresh.get("weights") or {}).get("optimized") or {}
    base = {"reproducible": True, "run_id": run_id, "kind": kind, "basis": basis,
            "as_of": as_of, "estimated": estimated,
            "coverage": fresh.get("coverage"),
            "weights": {"recorded": rec_w, "fresh": new_w}}
    if not isinstance(rec_w, dict) or not rec_w:
        # ★"같다"고 말할 근거가 없다★ 비교 대상이 없는 것은 일치가 아니다.
        return {**base, "verdict": "incomparable",
                "reason": "이 런에는 최적 비중이 기록돼 있지 않아 대조할 수 없습니다."}

    # 유니버스 변화는 비중 차이와 **다른 사실**이라 섞지 않는다.
    dropped = sorted(set(rec_w) - set(new_w))
    added = sorted(set(new_w) - set(rec_w))
    deltas = []
    for c in sorted(set(rec_w) & set(new_w)):
        r, f = float(rec_w[c]), float(new_w[c])
        deltas.append({"code": c, "recorded": round(r, 2), "fresh": round(f, 2),
                       "delta_pp": round(f - r, 2)})
    deltas.sort(key=lambda d: abs(d["delta_pp"]), reverse=True)
    max_delta = max((abs(d["delta_pp"]) for d in deltas), default=0.0)
    identical = (not dropped and not added and max_delta <= _TOL_PP)

    out = {**base,
           "verdict": "identical" if identical else "drifted",
           "max_delta_pp": round(max_delta, 2),
           "deltas": deltas,
           "universe_changed": {"dropped": dropped, "added": added}}

    if opts.record:
        try:
            from src.data.research_runs import record_run
            # 재현은 그 자체로 하나의 런이고, 부모는 원본이다.
            # `parent_run_id` 컬럼은 스키마에 이미 있었고 서버 생산자가 없었다 — 첫 소비자다.
            child = record_run(
                _REPRO_CHILD_KIND,
                inputs={"source_run_id": run_id, "as_of": as_of, "basis": basis},
                outputs={"verdict": out["verdict"], "max_delta_pp": out["max_delta_pp"],
                         "deltas": deltas[:30], "universe_changed": out["universe_changed"]},
                snapshot={"coverage": fresh.get("coverage"), "estimated": estimated},
                name=f"재현 — {run.get('name') or run_id}",
                parent_run_id=run_id,
            )
            out["child_run_id"] = child
            out["child_recorded"] = child is not None
        except Exception as e:
            logger.warning(f"재현 기록 실패: {e}")
            out["child_run_id"] = None
            out["child_recorded"] = False
    return out


@router.delete("/{run_id}")
def delete_one(run_id: str):
    try:
        from src.data.research_runs import delete_run
        if not delete_run(run_id):
            raise HTTPException(404, "런을 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        # "지울 게 없었다"(404)와 "지우지 못했다"(503)는 다른 사실이다.
        logger.warning(f"research run 삭제 실패: {run_id}")
        raise HTTPException(503, "연구 기록 저장소에 접근할 수 없습니다.")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
