"""기업분석 심화 API — 탭당 1콜 (스펙 2026-07-09).

GET /api/v1/company/{code}/valuation-sandbox  — 샌드박스+민감도+풋볼필드+Comps
GET /api/v1/company/{code}/financial-deep     — QoE·NWC·워터폴·듀폰
GET /api/v1/company/{code}/risk-deep          — Altman·Beneish·커버리지·스트레스
GET /api/v1/company/{code}/reverse-dcf       — 역DCF: 시장이 믿고 있는 가정 (P2-2)
GET /api/v1/company/{code}/valuation-distribution — 적정가 P10~P90 (P2-3)
GET /api/v1/company/{code}/macro-sensitivity — 금리 충격 → 적정가치 (P2-4)
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.company")

router = APIRouter(prefix="/api/v1/company", tags=["company-deep"])


@router.get("/{code}/valuation-sandbox")
def company_valuation_sandbox(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    rf: float | None = Query(None, ge=0, le=0.15),
    beta: float | None = Query(None, ge=0.1, le=3.0),
    erp: float | None = Query(None, ge=0, le=0.15),
    g: float | None = Query(None, ge=0, le=0.05),
    years: int | None = Query(None, ge=3, le=20),
):
    """가정 샌드박스 + Ke×g 민감도 + Football Field + Comps (Valuation 탭 1콜)."""
    try:
        from src.engine import company_analytics as ca
        overrides = {k: v for k, v in
                     {"rf": rf, "beta": beta, "erp": erp, "g": g, "years": years}.items()
                     if v is not None}
        out = ca.valuation_sandbox(code, price, overrides)
        out["football_field"] = ca.football_field(code, price)
        out["comps"] = ca.comps_table(code)
        return out
    except Exception:
        logger.exception("valuation-sandbox 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/financial-deep")
def company_financial_deep(code: str):
    """QoE·NWC·자본배치 워터폴·듀폰 (Financials 탭 1콜)."""
    try:
        from src.engine import company_analytics as ca
        return ca.financial_deep(code)
    except Exception:
        logger.exception("financial-deep 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/risk-deep")
def company_risk_deep(code: str, price: float = Query(..., gt=0)):
    """Altman 분해·Beneish 8지수·커버리지·금리 스트레스 (Risk 탭 1콜)."""
    try:
        from src.engine import company_analytics as ca
        return ca.risk_deep(code, price)
    except Exception:
        logger.exception("risk-deep 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/reverse-dcf")
def company_reverse_dcf(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    market_cap: float | None = Query(None, gt=0, description="시총(억) — 발행주식수 보강용"),
    bracket_lo: float = Query(-0.50, gt=-1.0, le=1.0),
    bracket_hi: float = Query(0.50, gt=-1.0, le=5.0),
):
    """★값이 아니라 **가정**을 되짚는다★ 시장가를 정당화하는 FCF 성장률 (P2-2).

    "적정가 83,000원" 은 우리 가정의 결과일 뿐이다. "시장은 향후 10년 FCF 연 11.4%
    성장을 믿고 있다" 는 **반증 가능한 명제**이고, 그것이 언더라이팅의 출발점이다.

    산출 불가는 200 + `{available:false, reason}` 이다 — 적자·마이너스 FCF 기업에서
    근이 존재하지 않는 것은 서버 장애가 아니라 **그 기업에 대한 사실**이므로 500 이나
    422 로 뭉개지 않는다. 근이 브래킷 밖이면 `direction` 이 어느 쪽인지 말한다.
    """
    try:
        from src.engine.valuation.reverse_dcf import reverse_dcf_for
        return reverse_dcf_for(code, price, market_cap=market_cap,
                               bracket=(bracket_lo, bracket_hi))
    except Exception:
        logger.exception("reverse-dcf 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/valuation-distribution")
def company_valuation_distribution(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    n: int = Query(2000, ge=100, le=20000, description="표본 수"),
):
    """★점 하나를 확률 진술로★ 적정가 P10~P90 + **현재 주가의 분위** (P2-3).

    통합값만이 아니라 **모델별 분포**와 모델 불일치를 함께 낸다 — 실측에서 모델
    불일치(2.94배)가 파라미터 불확실성(P90/P10 = 1.36)보다 크므로, 통합값 하나만
    내면 더 큰 쪽이 평균에 지워진다.

    ★폭 중 측정된 것은 하나도 없다★ `widths[*].measured` 가 전부 false 이고, 지배
    파라미터(`dominant_driver`)는 실측에서 β 였다 — 폭이 순수한 가정인 바로 그 항목.
    둘을 함께 읽어야 분포의 의미를 오해하지 않는다.

    표본 부족·TV 발산 기각은 200 + `{available:false, reason}` 이다.
    """
    try:
        from src.engine.valuation.valuation_distribution import valuation_distribution_for
        return valuation_distribution_for(code, price, n=n)
    except Exception:
        logger.exception("valuation-distribution 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/macro-sensitivity")
def company_macro_sensitivity(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    statistical: bool = Query(True, description="매크로 계열 회귀도 함께 낼지"),
):
    """★서술이 아니라 수치★ `+100bp 10Y → 적정가치 −9.5%` (P2-4).

    ★두 블록은 섞이지 않는다★
      · `structural` — rf → ke/kd 채널의 **항등식**. 표본도 표준오차도 없다.
        양방향을 따로 내고(비대칭은 실측 1.22배) 모델별 반응을 함께 낸다.
      · `statistical` — 코어 5계열과의 월별 회귀. **유의한 것만 고르지 않고**
        전부 보고하며, 다중검정과 "상관은 인과가 아니다" 를 라벨로 단다.

    설계 문서가 예로 든 GDP→EPS · USD→EPS · Oil→EBIT 는 `structural.unavailable`
    에서 **사유와 함께** 나간다 — 채널이 없거나(EPS 는 모델의 입력이다) 계열 자체가
    없다(유가). 빈칸이 아니라 왜 없는지가 언더라이팅의 정보다.
    """
    try:
        from src.engine.valuation.macro_sensitivity import (
            macro_sensitivity_for,
            statistical_sensitivity,
        )
        out = macro_sensitivity_for(code, price)
        if statistical:
            out["statistical"] = statistical_sensitivity(code)
        return out
    except Exception:
        logger.exception("macro-sensitivity 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class ThesisCheckRequest(BaseModel):
    """논지 원문 — ★자유 텍스트가 아니라 구조★ 그래야 검증할 수 있다."""
    claim: str = Field("", max_length=4000)
    evidence: list[dict] = Field(default_factory=list)
    catalysts: list[dict] = Field(default_factory=list)
    kill_conditions: list[dict] = Field(default_factory=list)


@router.post("/{code}/thesis-check")
def company_thesis_check(code: str, req: ThesisCheckRequest):
    """★굳히기 전에★ 논지를 검증하고 kill 조건을 3단으로 분류한다 (P2-5).

    논지를 다듬는 반복이 스냅샷을 더럽히지 않게 하는 것이 이 엔드포인트의 목적이다
    — 저장하지 않는다.

    kill 조건은 `filter_ast` 의 `FIELD_BY_ID` 로 검증한다(**새 DSL 이 없다**).
    분류 3단은 다리의 폭을 정직하게 말한다:
      · `backtestable` — PIT 토큰 + 재무 시계열 적재 → 룩어헤드 없이 백테스트 가능
      · `screen_only_backtest_lookahead` — 스냅샷 상수 폴백이라 **룩어헤드 근사**
      · `screen_only` — 조건식 토큰이 없어 백테스트에 못 올린다

    검증 실패는 500 이 아니라 200 + `{available:false, reason, errors}` 다.
    """
    try:
        from src.engine.company_thesis import (
            thesis_to_sell_conditions,
            validate_thesis,
        )
        thesis = req.model_dump()
        out = validate_thesis(thesis, code=code)
        out["sell_conditions"] = thesis_to_sell_conditions(thesis, code=code)
        return out
    except Exception:
        logger.exception("thesis-check 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class ThesisBacktestRequest(ThesisCheckRequest):
    """논지 + 백테스트 설정. ★유니버스 인자는 없다★ 논지는 기업 하나에 대한 것이다."""
    start_date: str = Field("2023-01-01", max_length=32)
    end_date: str = Field("2024-12-31", max_length=32)
    initial_capital: float = Field(100_000_000, gt=0)
    snapshot_id: str | None = Field(None, max_length=40)
    case_id: str | None = Field(None, max_length=40)
    record_run: bool = True


_THESIS_RUN_KIND = "thesis_backtest"

_SUMMARY_KEYS = ("total_return_pct", "cagr", "max_drawdown_pct", "sharpe_ratio",
                 "win_rate", "num_trades", "volatility_pct", "sortino_ratio")


def _finite(payload, _path=""):
    """비유한 float → None, 그리고 ★어느 키가 그랬는지 이름을 남긴다★

    백테스트 통계는 정당하게 무한할 수 있다(손실 거래가 0이면 `profit_factor`
    가 `inf`). JSON 이 그것을 실을 수 없으므로 None 으로 바꾸되, 조용히 지우면
    "값이 없다" 와 "무한이다" 가 같아 보인다 — 이 저장소의 관례대로 사유를 남긴다.
    """
    dropped: list[str] = []

    def walk(o, path):
        if isinstance(o, float):
            if math.isfinite(o):
                return o
            dropped.append(f"{path.lstrip('.')}={o}")
            return None
        if isinstance(o, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(o)]
        return o

    return walk(payload, _path), dropped


@router.post("/{code}/thesis-backtest")
def company_thesis_backtest(code: str, req: ThesisBacktestRequest):
    """★논지가 그대로 백테스트가 된다★ 있는 다리에 올린다 (P3-1).

    kill 조건 → `sell_conditions` → `_screen_to_backtest_core` → `rr_*` 기록.
    실행 경로를 새로 짓지 않으므로 리스크 룰·체결 모델이 우회되지 않는다.

    ★두 가지를 숨기지 않는다★
      · **룩어헤드** — tier 2 kill 조건이 있으면 `allow_snapshot_fundamentals` 를
        자동으로 켠다. 끄면 그 조건이 조용히 무시되어(실측 0/130) 사용자가 논지를
        검증했다고 믿게 되는데, 그것이 가장 나쁜 결과다.
      · **퇴화** — 스냅샷 상수 조건은 창 전체에서 항상 참이거나 항상 거짓이라
        거래 0건 또는 순수 바이앤홀드로 떨어진다. `diagnostics.degenerate` 가
        그것을 말한다. **거래 0건은 "손실 없음" 이 아니라 "검증되지 않음" 이다.**

    검증 실패·리프트 불가는 500 이 아니라 200 + `{available:false, reason}` 이고,
    그 경우 **백테스트도 기록도 하지 않는다.**
    """
    try:
        from src.engine.company_thesis import validate_thesis
        from src.engine.thesis_backtest import build_backtest_request, diagnose_signals

        thesis = {k: getattr(req, k) for k in
                  ("claim", "evidence", "catalysts", "kill_conditions")}
        checked = validate_thesis(thesis, code=code)
        built = build_backtest_request(thesis, code=code,
                                       start_date=req.start_date,
                                       end_date=req.end_date,
                                       initial_capital=req.initial_capital)
        if not built["available"]:
            # 돌릴 것이 없다 — 빈 실행을 성공으로 보고하지 않고 기록도 남기지 않는다.
            return {"available": False, "reason": built["reason"],
                    "thesis": checked, "lift": built["lift"], "run_id": None}

        from src.api.screener_routes import ScreenToBacktestRequest, _screen_to_backtest_core
        result = _screen_to_backtest_core(
            ScreenToBacktestRequest(**built["request"]))

        diagnostics = diagnose_signals(
            built["request"]["sell_conditions"], code=code,
            start_date=req.start_date, end_date=req.end_date,
            allow_snapshot=built["lookahead"])

        out = {
            "available": not result.get("error"),
            "reason": result.get("message") if result.get("error") else None,
            "code": str(code),
            "thesis": checked,
            "lift": built["lift"],
            "entry": built["entry"],
            "lookahead": built["lookahead"],
            "auto_enabled_opt_in": built["auto_enabled_opt_in"],
            "lookahead_reason": built["lookahead_reason"],
            "diagnostics": diagnostics,
            "backtest": result.get("backtest"),
            "screened_count": result.get("screened_count"),
        }
        out["run_id"] = _record_thesis_run(req, code, thesis, built,
                                           diagnostics, out)
        out["recorded"] = out["run_id"] is not None
        if req.case_id:
            from src.data.research_cases import advance_pointer
            out["case_bound"] = advance_pointer(req.case_id, "run", out["run_id"])
        out, dropped = _finite(out)
        if dropped:
            out["non_finite"] = dropped
        return out
    except HTTPException:
        raise
    except Exception:
        logger.exception("thesis-backtest 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


def _record_thesis_run(req, code: str, thesis: dict, built: dict,
                       diagnostics: dict, out: dict) -> str | None:
    """`rr_*` 사슬에 남긴다 — ★입력을 되살릴 수 있게 적는다★ (alpha_routes 관례).

    논지 원문·tier 분류·리프트된 조건·자동 opt-in 여부까지 남겨야 "그때 무엇을
    믿었고 무엇으로 검증했는가" 를 나중에 되짚을 수 있다.
    """
    if not req.record_run:
        return None
    stats = ((out.get("backtest") or {}).get("statistics") or {})
    try:
        from src.data.research_runs import record_run
        return record_run(
            _THESIS_RUN_KIND,
            inputs={
                "code": str(code), "thesis": thesis,
                "kill_conditions": built["lift"]["counts"],
                "lifted_conditions": built["request"]["sell_conditions"],
                "excluded_conditions": built["lift"]["excluded"],
                "entry_condition": built["entry"]["condition"],
                "start_date": req.start_date, "end_date": req.end_date,
                "initial_capital": req.initial_capital,
                "snapshot_id": req.snapshot_id,
                # ★자동으로 켰다는 사실 자체가 입력의 일부다★
                "allow_snapshot_fundamentals": built["lookahead"],
                "auto_enabled_opt_in": built["auto_enabled_opt_in"],
            },
            outputs={
                "statistics": {k: stats[k] for k in _SUMMARY_KEYS if k in stats},
                "backtest_id": (out.get("backtest") or {}).get("id"),
                "diagnostics": {k: diagnostics.get(k) for k in
                                ("degenerate", "reason", "buy_bars", "sell_bars",
                                 "total_bars")},
                "lookahead": built["lookahead"],
            },
            snapshot={"screened_count": out.get("screened_count"),
                      "lookahead_reason": built["lookahead_reason"]},
            name=f"논지 백테스트 — {code}",
            case_id=req.case_id,
        )
    except Exception as e:  # noqa: BLE001 — 기록 실패가 실행을 무효화하지 않는다
        logger.warning(f"논지 백테스트 기록 실패: {e}")
        return None
