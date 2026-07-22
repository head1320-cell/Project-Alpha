"""Alpha Lab API — 표현식 lint·검증·레지스트리·승격 (Full Expansion P2)

GET  /api/v1/alpha-lab/fields              — 피처 카탈로그 + 연산자 문서 (빌더 UI용)
POST /api/v1/alpha-lab/lint                — 저장 전 필수 검사 (미래참조·중복·스케일)
POST /api/v1/alpha-lab/validate            — IC/ICIR/Decay/분위/IS-OOS 검증 (+run 기록)
GET  /api/v1/alpha-registry                — 알파 목록 (템플릿 시드 멱등 포함)
POST /api/v1/alpha-registry                — 생성/수정 (수정 시 lint 통과 필수)
POST /api/v1/alpha-registry/{aid}/promote  — 상태 전이 (요건 미충족 시 정직 사유)
DELETE /api/v1/alpha-registry/{aid}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.alpha")

router = APIRouter(prefix="/api/v1", tags=["alpha-lab"])

_MAX_UNIVERSE = 200


class LintRequest(BaseModel):
    expr: str = Field(..., min_length=1, max_length=1000)


class ValidateRequest(BaseModel):
    expr: str = Field(..., min_length=1, max_length=1000)
    tickers: list[str] | None = None          # 명시 유니버스 (우선)
    universe: str = "kospi50"                 # 프리셋 (tickers 없을 때)
    months: int = Field(24, ge=6, le=60)
    quantiles: int = Field(5, ge=3, le=10)
    alpha_id: str | None = None               # 레지스트리 알파에 검증 결과 연결
    record_run: bool = True                   # ResearchRun 영속 (기본 on — 검증은 중요한 결과)


class AlphaUpsertRequest(BaseModel):
    alpha_id: str | None = None
    name: str = Field(..., min_length=1, max_length=120)
    expr: str = Field("", max_length=1000)
    description: str = Field("", max_length=1000)
    universe: str = "kospi200"
    tags: list[str] = Field(default_factory=list)
    notes: str = Field("", max_length=2000)


class PromoteRequest(BaseModel):
    to_status: str
    note: str = Field("", max_length=1000)


@router.get("/alpha-lab/fields")
def alpha_fields():
    from src.engine.alpha_lab import FIELDS, FUNCS_1, FUNCS_2
    return {
        "fields": [{"id": f[0], "label": f[1], "family": f[2], "desc": f[3]} for f in FIELDS],
        "functions": [
            {"id": "rank", "label": "rank(x)", "desc": "크로스섹션 [0,1] 순위"},
            {"id": "zscore", "label": "zscore(x)", "desc": "크로스섹션 표준화"},
            {"id": "winsorize", "label": "winsorize(x)", "desc": "상하위 5% 클립"},
            {"id": "sector_neutralize", "label": "sector_neutralize(x)", "desc": "섹터 그룹 내 demean"},
            {"id": "abs", "label": "abs(x)", "desc": "절대값"},
            {"id": "sign", "label": "sign(x)", "desc": "부호"},
            {"id": "log1p_abs", "label": "log1p_abs(x)", "desc": "부호 보존 로그 압축"},
            {"id": "min2", "label": "min2(a,b)", "desc": "원소별 최소"},
            {"id": "max2", "label": "max2(a,b)", "desc": "원소별 최대"},
        ],
        "allowed": {"funcs1": list(FUNCS_1), "funcs2": list(FUNCS_2)},
        "notes": ["시계열 연산(ts_*)은 피처 정의에 내장 — 표현식 레벨 ts_*는 v2.",
                  "펀더멘털 필드는 연간 보고서 + 공시랙 적용 (PIT 근사, lint가 안내)."],
    }


@router.post("/alpha-lab/lint")
def alpha_lint(req: LintRequest):
    try:
        from src.data.alpha_registry import list_alphas
        from src.engine.alpha_lab import lint_alpha
        existing = [a["expr"] for a in list_alphas(limit=300) if a["expr"]]
        return lint_alpha(req.expr, existing_exprs=existing)
    except Exception:
        logger.exception("alpha lint 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


def _resolve_universe_capped(req: ValidateRequest) -> list[str]:
    if req.tickers:
        return [t.strip() for t in req.tickers if t.strip()][:_MAX_UNIVERSE]
    try:
        from src.engine.screener import resolve_universe
        u = resolve_universe(req.universe) or []
        return list(u)[:_MAX_UNIVERSE]
    except Exception:
        return []


@router.post("/alpha-lab/validate")
def alpha_validate(req: ValidateRequest):
    try:
        from src.engine.alpha_lab import lint_alpha, validate_alpha
        lint = lint_alpha(req.expr)
        if not lint["ok"]:
            return {"error": True, "message": "lint 실패 — 식을 수정하세요.", "lint": lint}

        tickers = _resolve_universe_capped(req)
        if len(tickers) < 8:
            return {"error": True,
                    "message": f"유니버스 해소 실패 ({len(tickers)}종목) — tickers를 직접 지정하세요."}

        report = validate_alpha(req.expr, tickers, months=req.months, quantiles=req.quantiles)
        if report.get("error"):
            return report
        report["lint"] = lint

        if req.record_run:
            from src.data.research_runs import record_run
            rid = record_run(
                "alpha_validate",
                inputs={"expr": req.expr, "universe": req.universe,
                        "tickers_n": len(tickers), "months": req.months,
                        "quantiles": req.quantiles, "alpha_id": req.alpha_id},
                outputs={k: report[k] for k in
                         ("ic", "decay", "is_oos", "quantiles", "long_short",
                          "turnover_proxy", "n_periods", "avg_coverage") if k in report},
                snapshot={"period_start": report.get("period_start"),
                          "period_end": report.get("period_end"),
                          "universe_size": report.get("universe_size")},
                name=f"알파 검증 — {req.expr[:60]}",
            )
            report["run_id"] = rid
            report["run_recorded"] = rid is not None
            if req.alpha_id and rid:
                from src.data.alpha_registry import attach_validation
                attach_validation(req.alpha_id, rid)
        return report
    except Exception:
        logger.exception("alpha validate 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/alpha-registry")
def alpha_registry_list(status: str | None = Query(None)):
    try:
        from src.data.alpha_registry import list_alphas, seed_templates
        seed_templates()   # 멱등
        return {"alphas": list_alphas(status=status)}
    except Exception:
        logger.exception("alpha registry 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/alpha-registry")
def alpha_registry_upsert(req: AlphaUpsertRequest):
    try:
        from src.data.alpha_registry import upsert_alpha
        from src.engine.alpha_lab import lint_alpha
        if req.expr.strip():
            lint = lint_alpha(req.expr)
            if not lint["ok"]:
                return {"error": True, "message": "lint 실패 — 저장 불가.", "lint": lint}
        a = upsert_alpha(req.alpha_id, req.name, req.expr, description=req.description,
                         universe=req.universe, tags=req.tags, notes=req.notes)
        if a is None:
            raise HTTPException(404 if req.alpha_id else 500,
                                "알파를 찾을 수 없거나 저장 실패.")
        return {"error": False, "alpha": a}
    except HTTPException:
        raise
    except Exception:
        logger.exception("alpha upsert 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/alpha-registry/{alpha_id}/promote")
def alpha_promote(alpha_id: str, req: PromoteRequest):
    try:
        from src.data.alpha_registry import promote_alpha
        return promote_alpha(alpha_id, req.to_status, note=req.note)
    except Exception:
        logger.exception("alpha promote 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.delete("/alpha-registry/{alpha_id}")
def alpha_delete(alpha_id: str):
    try:
        from src.data.alpha_registry import delete_alpha
        if not delete_alpha(alpha_id):
            raise HTTPException(404, "알파를 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("alpha delete 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
