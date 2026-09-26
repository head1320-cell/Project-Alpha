"""Allocation Studio API — 포트폴리오 구축·최적화·분석 (Two Sigma Venn 벤치마킹).

POST /api/v1/allocation/analyze      — 프론티어+클라우드+최적화+흐름+리스크+지표+MC (1콜)
POST /api/v1/allocation/factor-xray  — 포트폴리오 가중 팩터 노출 vs 유니버스/벤치마크
POST /api/v1/allocation/stress       — 가상 시나리오(M8) + 역사 리플레이
GET  /api/v1/allocation/stress-catalog — 시나리오 목록(가상 4 + 역사, 가용성 포함)

전부 기존 엔진 조립: kis_portfolio_analyzer(프론티어·리스크기여) ·
portfolio_optimizer(MC 클라우드) · allocation_studio(사용자 뷰 BL·모델 스위치) ·
quant_metrics(지표) · stress_test_analyzer(M8 충격) · 팩터 스토어(X-ray).
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from src.api.json_safe import finite_payload as _finite_payload
from src.engine.entropy_views import EPUnavailable
from src.engine.research_context import describe as _describe_context
from src.engine.research_context import now as _research_now
from src.engine.research_context import validate_as_of

logger = logging.getLogger("api.allocation")

router = APIRouter(prefix="/api/v1/allocation", tags=["allocation-studio"])

_MIN_OBS = 30          # 자산별 최소 관측일 (kis_portfolio_analyzer 관례와 동일)
_RF = 0.035            # 무위험수익률 (quant_metrics 기본과 동일)

# ── 요청 모델 ─────────────────────────────────────────────────────────────────
class AllocationView(BaseModel):
    """뷰 하나 — **절대**(`assets`) 또는 **부호 있는 조합**(`weights`).

    ★`weights` 는 상대·팩터 뷰를 위한 확장이다(T3 §6.4).★ 예전에는 P 행이 언제나
    양수 등가중이라 `(+EQ, −FI)` 같은 스프레드를 표현할 수 없었고, 그래서 T3-B/C 를
    BL·EP 어느 쪽으로도 돌릴 수 없었다.

    - `magnitude_pct` 는 **그 행의 단위**다 — 스프레드 뷰의 3% 는 "EQ−FI 스프레드가
      연 3%" 이지 "각 자산이 3%" 가 아니다(행을 재정규화하지 않기 때문).
    - `direction` 은 **Q 에만** 곱한다. 부호를 `weights` 에 이미 넣었다면
      `direction=1` 로 둔다 — 양쪽에 넣으면 상쇄된다.
    """

    # `x-ui` 는 화면용 쉬운 이름뿐이다(BJ3) — 검증 규칙·계산에 끼어들지 않는다.
    assets: list[str] | None = Field(None, min_length=1, json_schema_extra={
        "x-ui": {"label": "종목", "tier": "basic", "help": "한 종목 또는 여러 종목(평균)"}})
    weights: dict[str, float] | None = Field(None, json_schema_extra={
        "x-ui": {"label": "조합 비중", "tier": "advanced", "help": "부호 있는 조합(상대·팩터 뷰)"}})
    direction: int = Field(1, json_schema_extra={                        # +1 상회 / -1 하회
        "x-ui": {"label": "방향", "tier": "basic", "options": {"1": "오른다", "-1": "내린다"}}})
    magnitude_pct: float = Field(2.0, ge=0, le=50, json_schema_extra={   # 연간 기대수익 크기(%)
        "x-ui": {"label": "1년 기대 수익(%)", "tier": "basic"}})
    confidence: float = Field(50, ge=0, le=100, json_schema_extra={
        "x-ui": {"label": "확신(%)", "tier": "basic", "widget": "slider", "ends": ["조금", "아주"]}})
    label: str | None = Field(None, json_schema_extra={                  # 테제 문장 (표시용, 계산 미사용)
        "x-ui": {"label": "메모", "tier": "advanced"}})

    @model_validator(mode="after")
    def _exactly_one_target_form(self):
        """★둘 중 정확히 하나★ — 어느 쪽이 P 행을 정하는지 추측하게 두지 않는다."""
        if bool(self.assets) == bool(self.weights):
            raise ValueError(
                "뷰는 `assets`(절대) 또는 `weights`(부호 있는 조합) 중 **정확히 "
                "하나**를 지정해야 합니다 — 둘 다이거나 둘 다 아니면 어느 쪽이 P 행을 "
                "정하는지 모호합니다.")
        return self


class ConstraintsInput(BaseModel):
    """전부 선택 — 지정된 것만 적용 (P3 제약 엔진). 퍼센트 단위."""
    max_weight_pct: float | None = Field(None, ge=1, le=100)
    # ★음수 하한이 롱숏 의사표시다 (P3)★ 예전에는 `ge=0` 이라 롱숏을 지시할 방법이
    # 아예 없었다. 하한을 음수로 주면 `Constraints.allows_short()` 가 True 가 되고,
    # 그 목표는 실행 게이트에서 `research_only` 로 막힌다(실행 경로에 공매도 없음).
    min_weight_pct: float = Field(0.0, ge=-50, le=50)
    group_caps_pct: dict[str, float] = Field(default_factory=dict)
    turnover_cap_pct: float | None = Field(None, ge=0, le=200)
    beta_min: float | None = Field(None, ge=-2, le=3)
    beta_max: float | None = Field(None, ge=-2, le=3)
    cash_min_pct: float = Field(0.0, ge=0, le=90)
    cash_max_pct: float = Field(0.0, ge=0, le=90)
    # ── 노출 제약 (P3) ──────────────────────────────────────────────────────
    # 롱숏에서 `Σw` 하나로는 포지션 크기를 말할 수 없다 — 롱 100/숏 0 과
    # 롱 150/숏 50 은 넷이 같아도 전혀 다른 포트폴리오다.
    #   · 130/30 → gross_max_pct=160, net_min=net_max=100
    #   · 달러중립 → net_min_pct=net_max_pct=0 (+ 베타중립은 beta_min/max 로)
    # ★이 셋은 사후 변환이 아니라 최적화 제약이다 — 재최적화해도 유지된다.★
    gross_max_pct: float | None = Field(None, ge=1, le=400)
    net_min_pct: float | None = Field(None, ge=-200, le=200)
    net_max_pct: float | None = Field(None, ge=-200, le=200)


_AS_OF_PAT = r"^\d{4}-\d{2}-\d{2}$"


def _check_as_of(as_of: str | None) -> None:
    """`as_of` 는 **과거 고정**이다 — 미래 날짜는 고정이 아니라 고정한 척이다 (P1-A).

    미래를 허용하면 `end = 2099-01-01` 이 그냥 오늘과 같은 데이터를 주면서 런에는
    "2099 시점으로 고정했다" 고 적힌다. 조용히 오늘로 깎지 않고 거부한다.

    ★정책은 엔진에 있다★ 이 규칙을 아는 곳이 라우트뿐이면 다른 호출자는 모른다.
    `research_context.validate_as_of` 가 사유 문자열을 돌려주고, 여기서 그것을
    422 로 바꾼다 — 정책은 하나이되 표현은 계층마다 다르다. **동작은 불변**이다.
    """
    reason = validate_as_of(as_of)
    if reason:
        raise HTTPException(422, reason)


def _check_weight_unit(weights: dict, declared: str | None) -> None:
    """★돈을 세기 전에 단위를 확정한다★ (엔진 정책 → 422)

    `unit_reason` 이 모호하다고 하면 추측하지 않고 되돌려 준다 — 조용히 고르면
    같은 지시가 100배 다른 주문을 내고 아무도 그것을 말하지 않는다(실측).
    """
    from src.engine.portfolio_weights import unit_reason
    reason = unit_reason(weights, declared)
    if reason:
        raise HTTPException(422, reason)


def _unknown_tickers(codes) -> dict:
    """종목 마스터가 모르는 코드를 **사실로 싣는다** (막지 않는다).

    ★`excluded` 와 다른 칸이다★ `excluded` 는 "데이터가 없어 분석에서 빠졌다"
    이고, 이것은 "데이터는 있는데 그 종목이 실재하는지 모른다" 다. 실측에서
    `ZZZZZZ` 는 262행의 **합성** 이력을 갖고 최적화에서 89.18% 를 가져가면서
    `excluded: []` 였다 — 두 사실을 한 칸에 넣으면 그 구분이 사라진다.

    ★막는 것은 여기가 아니다★ `SPY` 도 마스터에는 없지만 연구 대상으로 정당하다.
    주문을 거부하는 것은 `target_versions.untradable()` 게이트의 일이다.
    """
    from src.data.mock_gate import mock_allowed
    from src.data.stock_master import unknown_codes
    bad = unknown_codes(codes)
    if not bad:
        return {"codes": [], "synthetic_data": False, "note": None}
    synthetic = mock_allowed()
    return {
        "codes": bad,
        # mock 게이트가 유일한 판정 기준 — 새 기준을 만들지 않는다.
        "synthetic_data": synthetic,
        "note": ("종목 마스터에 없는 코드입니다 — 해외 상장 등 연구용으로는 유효할 "
                 "수 있으나 실행 게이트는 이들을 거부합니다."
                 + (" mock 모드이므로 이 코드들의 가격 이력은 **합성**입니다."
                    if synthetic else "")),
    }


class AnalyzeRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=30)
    weights: dict[str, float] | None = None          # 없으면 균등
    views: list[AllocationView] | None = None
    model: str = "mvo"                                # mvo|bl|risk_parity|hrp|min_var
    delta: float = Field(2.5, ge=0.5, le=10)          # 위험회피 λ (π 스케일)
    tau: float = Field(0.05, ge=0.001, le=1.0)
    lookback_days: int = Field(756, ge=90, le=3650)   # 거래일 기준 ~3년
    # ── P1: 데이터 절단일 고정 (선택) ──────────────────────────────────────
    #   없으면 오늘. 어느 쪽이든 서버가 실제로 쓴 절단일을 coverage 에 스탬프하므로
    #   런은 항상 재현 좌표를 갖는다. 이 필드를 실제로 채워 보내는 소비자는 재현
    #   엔드포인트(`/research-runs/{id}/reproduce`)다.
    as_of: str | None = Field(None, pattern=_AS_OF_PAT)
    # ── M2-B: 이 결정이 선 **매크로 증거(MES)** ─────────────────────────────
    #   `regime_snapshot_id` 는 **세션이 붙인** 스냅샷, `mes_id` 는 **케이스가 고정한**
    #   증거다. M1-S 가 TPV 에서 두 열을 일부러 나눈 것과 같은 구분이고, 여기서도
    #   하나로 다른 하나를 채우지 않는다. 없으면 동작은 이전과 한 글자도 같다.
    mes_id: str | None = Field(None, max_length=60)
    benchmark: str = "KOSPI"
    mc_paths: int = Field(500, ge=100, le=2000)
    constraints: ConstraintsInput | None = None       # P3 — 없으면 기존 무제약 동작 불변
    # ── ResearchRun 기록 (opt-in) — 슬라이더 드래그마다 DB에 쓰지 않도록 명시 요청 시에만 ──
    record_run: bool = False
    run_name: str | None = Field(None, max_length=200)
    # ── Phase 4a: 이 결정을 내릴 때 붙어 있던 매크로 국면 스냅샷 (선택) ──
    #    런을 나중에 다시 열었을 때 "어떤 국면 아래에서 내린 결정인지" 알 수 있게 한다.
    regime_snapshot_id: str | None = Field(None, max_length=40)
    # ── Phase 7: 이 결정에 쓰인 타이밍 규칙 세트의 **버전** (선택) ──
    #    스펙 §4 는 rule version 을 재현성 ID 로 분류한다(데이터 스냅샷·엔진 버전과 나란히).
    #    버전 내용은 timing_rule_set_versions 에 불변으로 남아 있어 재열기 때 복원 가능하다.
    timing_rule_set_id: str | None = Field(None, max_length=40)
    timing_rule_set_version: int | None = Field(None, ge=1)
    # ── Phase 10b: 이 결정을 검증한 시나리오 팩 (선택) ──
    #   ★해시는 요청에서 받지 않는다★ 서버가 지금 해석한 팩의 신원을 **스탬프**한다. 클라이언트가
    #   해시를 주장할 수 있으면, 실제로 쓰지 않은 팩 버전을 썼다고 적은 런이 만들어진다.
    scenario_pack_id: str | None = Field(None, max_length=80)
    # ── P2.5: 국면조건부 μ/Σ (opt-in) ───────────────────────────────────────
    #   ★기본값이 False 인 것이 계약이다★ 켜지 않으면 이 파일의 동작은 한 글자도
    #   같다 — 응답 키조차 늘지 않는다. 조건부 경로는 매크로 수집(경로 재계산)과
    #   모델 5회 추가 최적화(목표 구간)를 부르므로 슬라이더를 드래그할 때마다
    #   따라붙어서는 안 된다.
    conditional: bool = False
    # ★미검증 매크로 차단 (P5 ③) — 기본 OFF 라 동작이 바뀌지 않는다★
    #   켜면 판정이 `positive` 가 **아니거나** 이 요청이 판정된 대상이 아닐 때
    #   조건부 μ/Σ 를 적용하지 않는다. 조용히 떨어지지 않고 사유를 남긴다.
    require_verified_macro: bool = False
    # ★기본값이 "hard" 인 것이 계약이다★ 보내지 않으면 현행 경로·현행 신뢰도 그대로.
    regime_weighting: str = Field("hard", pattern="^(hard|probabilistic)$")
    # 라이브(오늘 스냅샷) vs 백테스트(as_of 절단). 백테스트는 아직 열려 있지 않다 —
    # ECOS revision 정책 문서가 선행조건이다(계획 §1.6.2).
    regime_mode: str = Field("live", pattern="^(live|backtest)$")
    # ★홀딩 기간의 유일한 출처★ — `h_hold` 는 여기서 파생된다(M→1 · Q→3). 개월 수를
    # 자유 입력으로 받지 않는 이유는, 국면 기대 지속기간(실측 2.5~5.0개월)처럼 뜻이
    # 다른 값이 흘러들어오는 것을 막기 위해서다. `BacktestRequest.rebalance` 와 같은 규약.
    rebalance: str = Field("M", pattern="^[MQ]$")
    # ── S5: 기업 밸류에이션 뷰 (opt-in) — ★`conditional` 과 같은 이유·같은 모양★
    #   기본 거짓이면 동작도 **응답 키도** 한 글자도 같다. 종목마다 DART 재무를
    #   읽고 몬테카를로를 돌리므로 슬라이더를 드래그할 때마다 따라붙어서는 안 된다.
    #   ★`BacktestRequest` 에는 이 필드가 없다★ — 회사 뷰는 forward_only 라
    #   과거 시뮬레이션에 들어가면 그 자체가 룩어헤드다.
    use_company_views: bool = False


class BacktestRequest(BaseModel):
    """정책 walk-forward 백테스트 — /analyze 와 동일 정책(모델·뷰·제약)을 OOS로 재현."""
    tickers: list[str] = Field(..., min_length=2, max_length=30)
    model: str = "mvo"                                # mvo|bl|risk_parity|hrp|min_var
    views: list[AllocationView] | None = None
    constraints: ConstraintsInput | None = None
    benchmark: str = "KOSPI"
    rebalance: str = Field("M", pattern="^[MQ]$")     # M=월 · Q=분기
    window_days: int | None = Field(None, ge=63, le=1260)   # None=expanding, 값=rolling
    cost_bps: float = Field(10.0, ge=0, le=100)       # 편도 회전율 비용(bp)
    lookback_days: int = Field(1008, ge=252, le=3650)  # 기본 ~4년(리밸런싱 충분)
    as_of: str | None = Field(None, pattern=_AS_OF_PAT)   # P1 — 데이터 절단일 고정(선택)
    delta: float = Field(2.5, ge=0.5, le=10)
    tau: float = Field(0.05, ge=0.001, le=1.0)


# ── 팩터 기반 포트폴리오 ──────────────────────────────────────────────────────
class FactorSpec(BaseModel):
    id: str                                  # 팩터 필드 id (fundamentals/price 스토어)
    weight: float = Field(1.0, ge=0, le=10)  # 상대 가중치
    direction: int = 0                       # 0=자동(higher_better) · 1=상위선호 · -1=하위선호


class FactorPortfolioRequest(BaseModel):
    factors: list[FactorSpec] = Field(..., min_length=1, max_length=12)
    tickers: list[str] | None = None         # 후보 풀(명시) — 없으면 유니버스 표본
    top_k: int = Field(10, ge=2, le=30)
    weighting: str = "equal"                 # equal|factor_tilt|inverse_vol|risk_parity|min_var|hrp
    lookback_days: int = Field(756, ge=90, le=3650)
    sample_size: int = Field(400, ge=50, le=1500)


# ── 카나리·마켓타이밍 ────────────────────────────────────────────────────────
class ResolveNamesRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=300)


# ── 공용 헬퍼 ─────────────────────────────────────────────────────────────────
def _mock_returns_fallback(want: list[str], start: str, end: str):
    """DB 무(빈 결과)일 때 mock 모드 한정 합성 수익률 — 기존 로더 체인 재사용.

    mock_gate 원칙: KIS_USE_MOCK=1(개발 기본)에서만 합성 허용, 운영에선 빈
    결과를 그대로 정직 반환(상위에서 excluded/에러로 보고).
    """
    from src.data.mock_gate import mock_allowed
    if not mock_allowed():
        return None
    import pandas as pd

    from src.data.ohlcv_loader import load_ohlcv_unified
    cols = {}
    for t in want:
        try:
            df = load_ohlcv_unified(t, start, end, prefer="mock")
            if df is not None and len(df) > _MIN_OBS:
                cols[t] = df["close"].pct_change()
        except Exception:
            continue
    if not cols:
        return None
    return pd.DataFrame(cols).dropna(how="all")


def _load_clean_returns(tickers: list[str], benchmark: str | None, lookback_days: int,
                        as_of: str | None = None):
    """load_returns → (returns_df[keep], bench_series|None, excluded, coverage).

    `as_of` — 데이터 절단일 (P1). 없으면 오늘.

    ★왜 절단일을 coverage 에 반드시 남기는가 (P1-A)★
    예전에는 `end = date.today()` 였고 그 사실이 **어디에도 기록되지 않았다**. 그래서
    어제 만든 런을 오늘 다시 돌리면 다른 구간으로 계산되는데, 런만 보고는 그것이
    "모델이 바뀐 것"인지 "데이터가 하루 늘어난 것"인지 구분할 수 없었다.
    이제 요청이 `as_of` 를 주지 않아도 **서버가 실제로 쓴 절단일을 스탬프**한다
    (`as_of_effective`). 그래서 UI 를 하나도 바꾸지 않고 이후의 모든 런이 재현 가능해진다.
    `as_of_requested` 가 `None` 이라는 것은 "고정하지 않았다"는 별개의 사실이라 함께 남긴다.
    """
    from src.kis_portfolio_analyzer import load_returns
    end = date.fromisoformat(as_of) if as_of else date.today()
    start = end - timedelta(days=int(lookback_days * 1.6) + 30)  # 캘린더 여유
    want = list(dict.fromkeys(tickers + ([benchmark] if benchmark else [])))
    df = load_returns(want, start.isoformat(), end.isoformat())
    src_mock = False
    if df is None or df.empty:
        mock_df = _mock_returns_fallback(want, start.isoformat(), end.isoformat())
        if mock_df is not None:
            df = mock_df
            src_mock = True

    excluded = []
    bench = None
    if benchmark is not None and benchmark in getattr(df, "columns", []):
        bench = df[benchmark]
    keep = []
    for t in tickers:
        if df.empty or t not in df.columns:
            excluded.append({"ticker": t, "reason": "시세 데이터 없음"})
        elif int(df[t].dropna().shape[0]) < _MIN_OBS:
            excluded.append({"ticker": t, "reason": f"시계열 {_MIN_OBS}일 미만"})
        else:
            keep.append(t)
    if not keep:
        return None, None, excluded, {}
    returns = df[keep].dropna()
    if len(returns) > lookback_days:
        returns = returns.iloc[-lookback_days:]
    if bench is not None:
        bench = bench.reindex(returns.index).dropna()
    coverage = {
        "start": str(returns.index.min().date()) if len(returns) else None,
        "end": str(returns.index.max().date()) if len(returns) else None,
        "n_obs": int(len(returns)),
        "benchmark_available": bench is not None and len(bench) >= _MIN_OBS,
        "source": "mock" if src_mock else "db",
        # ── 재현 좌표 (P1-A) ─────────────────────────────────────────────
        # `as_of_requested` 는 사용자가 고정했는지, `as_of_effective` 는 서버가 실제로
        # 쓴 절단일. 둘은 다른 사실이다 — 후자는 항상 있고, 전자는 없을 수 있다.
        # `end`(관측 마지막 날)와도 다르다: 휴장일이면 절단일보다 앞선다.
        "as_of_requested": as_of,
        "as_of_effective": end.isoformat(),
    }
    return returns, bench, excluded, coverage


def _ep_unavailable_reason(probes: dict) -> str | None:
    """엔트로피 풀링 요건 프로브 → 못 쓰면 사유(`/analyze` 와 그래프 옵티마이저 노드 공용)."""
    ep_probe = probes.get("entropy_pooling", {})
    if not ep_probe.get("ok"):
        return ("엔트로피 풀링 엔진을 쓸 수 없습니다 — "
                f"{ep_probe.get('reason') or '요건 미가용'}")
    return None


def _apply_constraints(req, names: list[str], R: np.ndarray, opt: dict, bench) -> dict | None:
    """P3 제약 엔진 (opt-in) — 최종 optimized 가중치를 제약 해로 교체한다.

    infeasible 이면 무제약 해를 유지하되 정직 사유를 함께 반환한다(조용한 무시 금지).
    ★`/analyze` 와 AAS 그래프의 옵티마이저 노드가 이 함수 하나를 부른다★ (BI2) —
    같은 산수를 두 곳에 두면 갈라진다. `opt` 를 제자리에서 바꾼다(예전 인라인과 같다).
    """
    if req.constraints is None:
        return None
    from src.engine.constrained_opt import Constraints, constrained_solve, sector_groups_for
    cobj = Constraints(**req.constraints.model_dump())
    if not cobj.any_active():
        return None
    sol = constrained_solve(
        req.model, names, R,
        mu=np.asarray(opt["mu_used"], dtype=float),
        S=np.asarray(opt["sigma_annual"], dtype=float),
        constraints=cobj,
        w_current=req.weights,
        groups_of=sector_groups_for(names),
        bench_returns=(bench.values if bench is not None
                       and len(bench) == R.shape[0] else None),
    )
    report = {k: sol.get(k) for k in
              ("status", "violations", "binding", "relaxed",
               "notes", "reason", "projected")}
    if sol["status"] != "infeasible" and sol.get("weights") is not None:
        opt["weights"] = np.asarray(sol["weights"], dtype=float)
        opt["flow"]["optimized"] = opt["weights"]
    return report


def _series_stats(ret: np.ndarray, ppy: int = 252) -> dict:
    """일별 수익률 시리즈 → 헤드라인 지표 (연수익·변동성·Sharpe·MDD·Sortino·Calmar)."""
    r = np.asarray(ret, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return {}
    ann = float(r.mean() * ppy)
    vol = float(r.std(ddof=1) * math.sqrt(ppy))
    sharpe = (ann - _RF) / vol if vol > 0 else 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    mdd = float(dd.min())
    downside = r[r < 0]
    dvol = float(downside.std(ddof=1) * math.sqrt(ppy)) if downside.size > 1 else 0.0
    sortino = (ann - _RF) / dvol if dvol > 0 else 0.0
    calmar = ann / abs(mdd) if mdd < 0 else 0.0
    return {
        "expected_return_pct": round(ann * 100, 2),
        "volatility_pct": round(vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 2),
    }


def _labels(codes: list[str]) -> dict[str, str]:
    from src.data.stock_master import get_stock_name
    return {c: (get_stock_name(c) or c) for c in codes}


def _w_dict(names: list[str], w: np.ndarray) -> dict[str, float]:
    """비중 벡터 → 퍼센트 dict. **잡음만 거르고 부호는 가리지 않는다.**

    ★`abs()` 다 (P3)★ 예전 술어는 `w[i] > 0.0005` 였다. 임계값의 목적은 0 에
    가까운 수치 잔차를 지우는 것인데, 부호를 함께 걸러 **숏이 응답에서 통째로
    사라졌다**. 최적화가 롱숏 해를 내도 API 를 통과하면 롱온리처럼 보였고,
    R0 이 `compile_target` 주석에 남긴 "`_w_dict` 는 음수를 조용히 제외해서,
    롱숏이 아닌데 롱온리처럼 보이게 만들었다" 가 바로 이 줄이다.
    """
    return {names[i]: round(float(w[i]) * 100, 2) for i in range(len(names))
            if abs(w[i]) > 0.0005}


def _risk_contribution_report(w, S, names: list[str], *,
                              weights_source: str, sigma_source: str) -> dict:
    """오일러 리스크 기여 + ★어느 포트폴리오·어느 Σ 인지 항상 밝힌다★ (P4-b).

    이 모듈은 이미 `mu_engine`·`sigma_source` 로 "화면이 라벨을 지어내지 않도록
    서버가 답한다" 를 쓰고 있다. 리스크 기여에도 같은 규율을 적용한다 — 응답
    안에 서로 다른 포트폴리오를 설명하는 진단이 나란히 놓이기 때문이다.
    """
    from src.engine.allocation_studio import risk_contributions
    rc = risk_contributions(np.asarray(w, dtype=float),
                            np.asarray(S, dtype=float))
    label = {"weights_source": weights_source, "sigma_source": sigma_source}
    if rc["pct"] is None:
        # ★미상이어도 무엇을 재려 했는지는 남는다★
        return {**label, "portfolio_volatility_pct": None, "pct": None,
                "contribution_pct": None, "hhi": None, "max_pct": None,
                "reason": rc["reason"]}
    return {
        **label,
        "portfolio_volatility_pct": round(rc["portfolio_volatility"] * 100, 4),
        # %기여 — 합이 100 이다(오일러). 표시 반올림은 여기서만.
        "pct": {names[i]: round(float(rc["pct"][i]) * 100, 4)
                for i in range(len(names))},
        "contribution_pct": {names[i]: round(float(rc["contribution"][i]) * 100, 4)
                             for i in range(len(names))},
        "hhi": round(rc["hhi"], 6),
        "max_pct": round(rc["max_pct"] * 100, 4),
        "reason": None,
    }


def _risk_contributions_basis(user_weights) -> dict:
    """기존 `risk_contributions` 키가 **무엇을** 설명하는지 (P4-b).

    ★값은 바꾸지 않는다★ 프론트 3곳이 `Record<string, number>` 로 읽는다
    (`RiskContribDonut` 포함). 대신 그 수의 정체를 옆에 적는다 — 사용자가 비중을
    주지 않으면 `PortfolioAnalyzer` 가 **등가중**으로 떨어지므로, 도넛이
    사용자가 고른 적 없는 포트폴리오를 보여 주고 있다는 사실이 응답 어디에도
    없었다.
    """
    fallback = not user_weights
    return {
        "weights_source": "equal_weight_fallback" if fallback else "user_current",
        "sigma_source": "sample_252",
        "reason": (("요청에 비중이 없어 등가중으로 분석했습니다 — 이 값은 "
                    "사용자 포트폴리오도 추천 포트폴리오도 아닙니다")
                   if fallback else None),
        "note": ("추천 포트폴리오의 리스크 기여는 risk_contribution_optimized 에 "
                 "있습니다. 두 블록은 비중도 Σ 도 다릅니다."),
    }


def _enb_report(w, S, names: list[str]) -> dict:
    """실질 분산도 — Meucci ENB(상관 반영) vs Neff(비중 집중만). Explain 패널용."""
    from src.engine.allocation_studio import enb_report
    wa = np.asarray(w, dtype=float)
    n = len(names)
    hhi = float(np.sum(wa ** 2))
    # ★비중 집중은 Σ 없이도 잴 수 있다★ hhi 가 0 이면 비중이 전부 0 이라는 뜻이라
    # "완전 분산" 이 아니라 미상이다.
    neff = (1.0 / hhi) if hhi > 0 else None
    rep = enb_report(wa, np.asarray(S, dtype=float))
    return {"enb": (None if rep["enb"] is None else round(rep["enb"], 2)),
            "enb_reason": rep["reason"],
            "neff": (None if neff is None else round(neff, 2)),
            "neff_reason": (None if neff is not None
                            else "비중이 전부 0 이라 유효 종목수를 정의할 수 없습니다"),
            "n_assets": n,
            "note": "ENB는 상관을 반영한 실질 분산 베팅 수(≤ Neff). Neff는 비중 집중만 반영."}


# ── P2.5 조건부 μ/Σ + 검증 관문 → `allocation_pipeline` (P8 ②) ───────────────
#
# ★본문은 옮겼고 이름은 여기 남는다★ `scripts/company_view_control.py` 와 테스트
# 여러 곳이 `src.api.allocation_routes` 경로로 이 이름들을 import 하거나
# monkeypatch 한다. 재수출하지 않으면 그 계약이 조용히 끊긴다.
#
# ★다만 재수출이 패치를 대신하지는 못한다★ 호출부가 `allocation_pipeline` 에
# 있으므로 `allocation_routes` 쪽 이름을 바꿔 봐야 아무 일도 일어나지 않는다 —
# 예외도 없이. 패치는 `src.api.allocation_pipeline` 을 겨눠야 한다.
from src.api.allocation_pipeline import (  # noqa: F401
    _CONDITIONAL_MAX_CONFIDENCE,
    _HOLD_MONTHS,
    _PATH_MONTHS,
    _PIT_MARKET,
    _VIEW_MODELS,
    Belief,
    _company_view_stack,
    _conditional_block,
    _conditional_stack,
    _conditional_views,
    _forward_only,
    _freshness,
    _hard_conditional,
    _macro_verification,
    _mixture_conditional,
    _months_span,
    _pit_block,
    _regime_path_for,
    _unavailable_conditional,
    build_belief,
    macro_gate_decision,
)
from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label
from src.engine.allocation_evidence import lookahead_evidence


# ── /analyze ─────────────────────────────────────────────────────────────────
@router.post("/analyze")
def allocation_analyze(req: AnalyzeRequest):
    """포트폴리오 종합 분석 — 하나의 수익률 행렬에서 전 패널 파생 (추가 DB 조회 0)."""
    return run_analyze(req)


def run_analyze(req: AnalyzeRequest) -> dict:
    """★분석 파이프라인의 단일 출처 (P1-C)★

    재현 엔드포인트(`/research-runs/{id}/reproduce`)가 **이 함수를 그대로 부른다.**
    사본을 만들지 않는 이유는 이 저장소가 두 번 값을 치렀기 때문이다 —
    A1 의 `currentSig`/`req` 두 객체 리터럴, R0 의 오버레이 컴파일 산수가 화면과 서버에
    나뉘어 있던 것. 같은 산수를 두 곳에 두면 반드시 갈라지고, 갈라져도 타입 에러가 나지
    않는다. 재현이 원본과 **다른 코드로** 계산하면 그것은 재현이 아니다.
    """
    _check_as_of(req.as_of)
    # 스냅샷 링크 검증을 **계산 전에** 한다 — 없는 ID 를 조용히 기록하면 나중에 런을 열었을 때
    # 국면을 복원할 수 없고, 그때는 왜 비었는지 알 방법이 없다. 값비싼 계산 뒤가 아니라 앞에서 막는다.
    if req.regime_snapshot_id:
        from src.data.regime_snapshots import get_snapshot
        if get_snapshot(req.regime_snapshot_id) is None:
            raise HTTPException(
                422, f"국면 스냅샷을 찾을 수 없습니다: {req.regime_snapshot_id}. "
                     "삭제되었거나 다른 환경의 ID 일 수 있습니다."
            )
    # 규칙 세트 버전도 같은 이유로 계산 전에 검증한다 — 복원할 수 없는 버전을 가리키는 런은
    # "규칙 v2 로 계산했다" 고 적혀 있어도 그 v2 를 다시 만들어낼 수 없다.
    if req.timing_rule_set_id:
        from src.data.timing_rules import get_rule_set, get_rule_set_version
        if req.timing_rule_set_version is None:
            cur = get_rule_set(req.timing_rule_set_id)
            if cur is None:
                raise HTTPException(
                    422, f"타이밍 규칙 세트를 찾을 수 없습니다: {req.timing_rule_set_id}.")
            req.timing_rule_set_version = cur.get("version")
        elif get_rule_set_version(
                req.timing_rule_set_id, req.timing_rule_set_version) is None:
            raise HTTPException(
                422, f"타이밍 규칙 세트 버전을 찾을 수 없습니다: "
                     f"{req.timing_rule_set_id} v{req.timing_rule_set_version}. "
                     "삭제되었거나 다른 환경의 ID 일 수 있습니다."
            )
    # 시나리오 팩도 같은 이유로 계산 전에 검증하고, **현재 신원을 여기서 확정한다.**
    # 등록 팩(코드) → 저장 팩(DB) 순서는 `_resolve_pack` 과 같다 — 저장 팩이 등록 id 를 가리면
    # 런에 적힌 팩과 실제로 돌린 팩이 달라진다.
    # ── M2-B: MES 조인 + 능력 요건 게이트 ──────────────────────────────────
    #
    # ★게이트는 레벨 서수가 아니라 요건 프로브다★ 처음에는 "capability_level 이 L2
    # 미만이면 거부" 로 쓰려 했는데, 라이브로 재 보니 사다리는 **L0 이 최상단, L3 이
    # 안전 기저**이고 `resolve()` 는 요건이 모두 통과하는 **가장 높은** 레벨을 돌려준다.
    # 이 환경은 L1 — 즉 L1 은 L2 보다 **위**다.
    #
    # 더 중요한 것: `capability.py:243` 이 직접 적어 두었듯 **레벨 간 요건은 포함관계가
    # 아니다**(L1 이 L2 의 요건을 필요로 하지 않는다). L1 에 도달했다는 것이
    # `entropy_pooling` 이 있다는 뜻이 아니다. 그래서 서수가 아니라 **그 엔진이 필요로
    # 하는 요건 하나**를 본다.
    mes_block: dict[str, Any] | None = None
    if req.mes_id:
        from src.data.regime_snapshots import get_snapshot
        snap = get_snapshot(req.mes_id)
        if snap is None:
            raise HTTPException(
                422, f"매크로 증거(MES)를 찾을 수 없습니다: {req.mes_id}. "
                     "삭제되었거나 다른 환경의 ID 일 수 있습니다.")
        # ★복제하지 않고 조인해서 읽는다★ 능력 레벨의 단일 출처는 MES 행이다
        # (M1-V 가 TPV 에 세운 규칙과 같다). 여기서는 **고정 시점의 해석**을 스탬프할 뿐,
        # 지금 돌릴 수 있는지는 아래의 라이브 프로브가 답한다.
        mes_block = {
            "mes_id": req.mes_id,
            "as_of": snap.get("as_of"),
            "capability_level": snap.get("capability_level"),
            "capability_reason": snap.get("capability_reason"),
        }

    if req.model == "ep":
        from src.engine.capability import probe_all
        probes = probe_all()
        ep_why = _ep_unavailable_reason(probes)
        if ep_why:
            raise HTTPException(422, ep_why)
        if mes_block is not None:
            # ★불일치는 정보다★ MES 가 고정된 시점의 레벨과 지금 레벨이 다르면
            # 그 사실을 숨기지 않는다 — CaseBar 가 세션 스냅샷 vs 케이스 MES 에
            # 쓰는 것과 같은 패턴이다. 막지는 않는다(고정 시점의 해석일 뿐이다).
            from src.engine.capability import resolve
            live = resolve(probes)
            mes_block["live_capability_level"] = live["level"]
            if mes_block.get("capability_level") and \
                    mes_block["capability_level"] != live["level"]:
                mes_block["capability_diverged"] = (
                    f"이 증거가 고정될 때는 {mes_block['capability_level']} 였고 "
                    f"지금은 {live['level']} 입니다 — 같은 증거라도 지금 쓸 수 있는 "
                    "도구가 달라졌습니다.")

    scenario_pack_hash: str | None = None
    if req.scenario_pack_id:
        from src.engine.scenario_packs import get_pack as get_registered
        pk = get_registered(req.scenario_pack_id)
        if pk is not None:
            scenario_pack_hash = pk.content_hash
        else:
            from src.data.scenario_packs_store import get_pack as get_saved
            row = get_saved(req.scenario_pack_id)
            if row is None:
                raise HTTPException(
                    422, f"시나리오 팩을 찾을 수 없습니다: {req.scenario_pack_id}. "
                         "삭제되었거나 다른 환경의 ID 일 수 있습니다.")
            scenario_pack_hash = row.get("content_hash")

    try:
        returns, bench, excluded, coverage = _load_clean_returns(
            req.tickers, req.benchmark, req.lookback_days, as_of=req.as_of)
        if returns is None or len(returns.columns) < 2:
            return {"error": True,
                    "message": "분석 가능한 자산이 2개 미만입니다. 시세가 적재된 자산을 추가하세요.",
                    "excluded": excluded}

        names = list(returns.columns)
        R = returns.values

        # 0) P2.5 — 국면조건부 μ/Σ (요청했을 때만). 실패해도 계산은 계속되고,
        #    그 사실은 아래 `conditional` 블록이 응답에 적는다(조용한 폴백 금지).
        #    ★`/rebalance-decision` 과 **같은 문**을 지난다 (P8 ②)★ 관문도
        #    그 안에 한 번만 있다 — 예전에는 이 순서가 두 라우트에 복사돼
        #    있었고, P5 는 관문을 두 곳에 배선해야 했다.
        belief = build_belief(req, returns, names)
        cond, cond_path, cond_meta = belief.cond, belief.path, belief.meta
        s_override, extra_views = belief.s_override, belief.extra_views
        view_conf = belief.view_confidence

        # 0b) S5 — 기업 밸류에이션 뷰 (요청했을 때만). `None` 이면 응답 키도 없다.
        co_stack = _company_view_stack(req, names)

        # 1) 뷰+모델 최적화 (allocation_studio 엔진)
        from src.engine.allocation_studio import optimize
        views = [v.model_dump() for v in (req.views or [])]
        opt = optimize(req.model, names, R, views=views or None,
                       delta=req.delta, tau=req.tau,
                       s_override=s_override, extra_views=extra_views,
                       company_views=(co_stack or {}).get("views"))

        # 1b) P3 제약 엔진 (opt-in) — 최종 optimized 가중치를 제약 해로 교체.
        #     infeasible이면 무제약 해를 유지하되 정직 사유를 함께 반환(조용한 무시 금지).
        constraints_report = _apply_constraints(req, names, R, opt, bench)

        # 1c) P2.5 — 목표 비중 **구간**. 같은 Σ 를 여러 모델로 풀어 산포를 낸다.
        #     ★제약 해는 넣지 않는다★ 제약이 걸린 가중치와 무제약 가중치를 한 구간에
        #     섞으면 "모델들이 이만큼 갈린다" 가 "제약이 이만큼 눌렀다" 와 뒤섞인다.
        target_range = None
        if req.conditional:
            from src.engine.allocation_studio import target_weight_range
            target_range = target_weight_range(
                names, R, s_annual=np.asarray(opt["sigma_annual"], dtype=float),
                mu_bl=(np.asarray(opt["mu_used"], dtype=float)
                       if opt.get("mu_engine") != "mvo" else None))

        # 2) 현재(사용자) 가중치 분석 — 리스크 기여·상관 (기존 PortfolioAnalyzer)
        from src.kis_portfolio_analyzer import PortfolioAnalyzer
        user_w = None
        if req.weights:
            # ★부호 보존★ 예전에는 숏을 지우고 `Σw <= 0` 이면 "비중 없음" 으로
            # 떨어뜨렸다 — 전액 숏 북이 조용히 균등가중으로 분석되던 자리다.
            # (`PortfolioAnalyzer` 의 net 정규화가 먼저 고쳐졌기에 걷을 수 있다.)
            user_w = {t: float(req.weights.get(t, 0.0)) for t in names}
            if sum(abs(v) for v in user_w.values()) <= 0:
                user_w = None
        analyzer = PortfolioAnalyzer(returns=returns, weights=user_w)
        metrics = analyzer.analyze()

        # 3) 효율적 프론티어 곡선(SLSQP 30점, 각 점 자산별 가중치 포함)
        frontier_records = []
        try:
            ef = analyzer.efficient_frontier(n_points=30)
            if ef is not None and not ef.empty:
                frontier_records = ef.round(4).to_dict("records")
        except Exception as e:
            logger.warning(f"frontier 실패: {e}")

        # 4) MC Dirichlet 클라우드 (기존 portfolio_optimizer — 가중치 배열은 미포함)
        cloud = {"returns": [], "volatilities": [], "sharpes": []}
        try:
            from src.models.portfolio_optimizer import efficient_frontier as mc_frontier
            mc = mc_frontier(returns, n_portfolios=1500, risk_free_rate=_RF)
            f = mc.get("frontier", {}) if isinstance(mc, dict) else {}
            cloud = {"returns": f.get("returns", []),
                     "volatilities": f.get("volatilities", []),
                     "sharpes": f.get("sharpe_ratios", [])}
        except Exception as e:
            logger.warning(f"MC cloud 실패: {e}")

        # 5) 마커 포인트들 (연율 좌표: x=vol%, y=ret%)
        mu_a = opt["mu_annual"]
        S_a = opt["sigma_annual"]

        def _pt(w: np.ndarray) -> dict:
            r = float(w @ mu_a)
            v = float(np.sqrt(w @ S_a @ w))
            return {"return_pct": round(r * 100, 2), "volatility_pct": round(v * 100, 2)}

        w_cur = metrics.weights.reindex(names).fillna(0).values
        points = {
            "current": _pt(w_cur),
            "market": _pt(opt["flow"]["market"]),
            "optimal": _pt(opt["weights"]),
        }

        # 6) Sankey 3단계 흐름
        flow = {stage: _w_dict(names, w) for stage, w in opt["flow"].items()}

        # 7) 요약 지표 — 최적화 포트폴리오 vs 벤치마크 vs Active
        port_ret = returns.values @ opt["weights"]
        pf_stats = _series_stats(port_ret)
        bench_stats = {}
        active = {}
        if bench is not None and len(bench) >= _MIN_OBS:
            bench_stats = _series_stats(bench.values)
            active = {k: round(pf_stats[k] - bench_stats[k], 2)
                      for k in pf_stats if k in bench_stats}

        # quant_metrics 보강 지표 (VaR/CVaR 등 — 히스토리컬)
        from src.engine.quant_metrics import compute_metrics
        eq = np.cumprod(1.0 + port_ret)
        extra = compute_metrics(port_ret, eq, benchmark_returns=(
            bench.values if bench is not None and len(bench) == len(port_ret) else None))

        # 8) MC 1년 수익 분포 (GBM 정규근사, 시드 고정 — 결정론)
        mu_d = float(np.mean(port_ret))
        sd_d = float(np.std(port_ret, ddof=1)) if len(port_ret) > 1 else 0.0
        rng = np.random.default_rng(42)
        z = rng.standard_normal(req.mc_paths)
        term = np.exp((mu_d - 0.5 * sd_d * sd_d) * 252 + sd_d * math.sqrt(252) * z) - 1.0
        lo, hi = np.percentile(term, [0.5, 99.5])
        edges = np.linspace(lo, hi, 41)
        counts, _ = np.histogram(term, bins=edges)
        mc_dist = {
            "bins": [{"x0": round(float(edges[i]) * 100, 2),
                      "x1": round(float(edges[i + 1]) * 100, 2),
                      "count": int(counts[i])} for i in range(len(counts))],
            "expected_pct": round(float(term.mean()) * 100, 2),
            "var95_pct": round(float(-np.percentile(term, 5)) * 100, 2),
            "cvar95_pct": round(float(-term[term <= np.percentile(term, 5)].mean()) * 100, 2),
            "note": "GBM 정규근사 1년 시뮬레이션 (히스토리컬 μ·σ 기반)",
        }

        payload = {
            "error": False,
            "names": names,
            "labels": _labels(names),
            "excluded": excluded,
            "coverage": coverage,
            "model": req.model,
            "params": {"delta": req.delta, "tau": req.tau,
                       "lookback_days": req.lookback_days},
            "views_applied": opt["views_applied"],
            "skipped_views": opt["skipped_views"],
            "cap_missing": opt["cap_missing"],
            "weights": {"current": _w_dict(names, w_cur),
                        "optimized": _w_dict(names, opt["weights"])},
            "flow": flow,
            "frontier": {"curve": frontier_records, "cloud": cloud},
            "points": points,
            "risk_contributions": {k: round(float(v) * 100, 2)
                                   for k, v in metrics.risk_contributions.items()},
            # ★기존 키는 그대로 두고 정체만 옆에 적는다★ (프론트 3곳이 읽는다)
            "risk_contributions_basis": _risk_contributions_basis(user_w),
            # ★추천한 포트폴리오의 리스크를 말한다★ — 위 블록은 사용자(또는
            # 등가중) 비중을 표본 Σ 로 잰 것이라 이 엔드포인트가 내놓은 배분과
            # 다른 대상이다.
            "risk_contribution_optimized": _risk_contribution_report(
                opt["weights"], opt["sigma_annual"], names,
                weights_source="optimized",
                sigma_source=opt.get("sigma_source", "trailing")),
            "enb": {**_enb_report(opt["weights"], opt["sigma_annual"], names),
                    "weights_source": "optimized",
                    "sigma_source": opt.get("sigma_source", "trailing")},
            "correlation": metrics.correlation_matrix.round(3).to_dict(),
            "summary": {"portfolio": pf_stats, "benchmark": bench_stats or None,
                        "active": active or None,
                        "benchmark_label": req.benchmark if bench_stats else None,
                        "extra": {"var_pct": extra.get("var_pct"),
                                  "cvar_pct": extra.get("cvar_pct"),
                                  "information_ratio": extra.get("information_ratio")}},
            "mc": mc_dist,
            "constraints_report": constraints_report,
            "unknown_tickers": _unknown_tickers(req.tickers),
            # ★어느 μ 엔진이 이 숫자를 냈는지 서버가 답한다 (M2)★ 화면이 라벨을
            # 지어내지 않게 하려는 것이고, `ep` 진단(feasible·ENS·위반·신뢰도 미사용)은
            # EP 일 때만 채워진다.
            "mu_engine": opt.get("mu_engine"),
            "ep": opt.get("ep"),
            # 고정된 매크로 증거 — 없으면 `None` 이고, 그것이 "증거 없이 돌았다" 는 사실이다.
            "mes": mes_block,
            # ★`summary` 는 과거 수익률 위의 시뮬레이션 통계다★ (`_series_stats`) —
            # `MetricsTable`·`ResearchRunsPanel` 이 이 숫자를 그리면서 라벨이 없었다.
            # 표본내/표본외는 **다른 축**이고 여기서 말하지 않는다(범위 밖).
            "perf_label": backtest_label(is_mock_data=mock_allowed()).to_dict(),
        }

        # ★요청했을 때만 키가 늘어난다★ `conditional=False` 면 위 페이로드가 끝이고
        # 기존 소비자가 보는 응답은 바이트 단위로 같다.
        if req.conditional:
            payload["conditional"] = _conditional_block(
                cond or {}, cond_path or {},
                sigma_applied=s_override is not None,
                mu_as_views=int(opt.get("extra_views_used") or 0),
                view_confidence=view_conf, model=req.model, meta=cond_meta,
                universe=names, months=_months_span(returns),
                blocked_reason=belief.blocked_reason)
            payload["target_range"] = target_range

        # ★같은 규율 — 요청했을 때만 키가 늘어난다★ (S5)
        if co_stack is not None:
            payload["company_views"] = co_stack["block"]

        # ── ResearchRun 기록 (opt-in) — 서버가 계산한 결과를 서버가 스탬프.
        #    outputs는 재계산 가능한 대형 산출물(프론티어 클라우드·MC bins) 제외 요약만.
        if req.record_run:
            from src.data.research_runs import KIND_ANALYZE, record_run
            rid = record_run(
                KIND_ANALYZE,
                inputs=req.model_dump(exclude={"record_run", "run_name"}),
                outputs={"weights": payload["weights"], "flow": payload["flow"],
                         "summary": payload["summary"], "labels": payload["labels"],
                         "views_applied": payload["views_applied"],
                         # ★기록에도 종류를 남긴다★ — 이 커밋 이전에 기록된 런은
                         # 이 키가 없고, 화면은 그것을 `unknown` 으로 그린다(사실이다).
                         "perf_label": payload["perf_label"]},
                # regime_snapshot_id 를 snapshot 에도 넣는다 — list_runs 는 inputs 를 제외하고
                # snapshot 은 포함하므로(research_runs._row_to_dict, full=False), 여기 없으면
                # 런 목록에서 스냅샷을 볼 수 없어 재열기 UI 가 성립하지 않는다.
                snapshot={"coverage": coverage, "excluded": excluded,
                          "cap_missing": opt["cap_missing"],
                          "regime_snapshot_id": req.regime_snapshot_id,
                          "timing_rule_set_id": req.timing_rule_set_id,
                          "timing_rule_set_version": req.timing_rule_set_version,
                          # ★id 만으로는 부족하다★ 계수가 바뀌면 같은 id 가 다른 충격을
                          # 가리키므로, 재열기 때 "그때 그 팩인가" 를 물을 수 있어야 한다.
                          "scenario_pack_id": req.scenario_pack_id,
                          "scenario_pack_hash": scenario_pack_hash,
                          # M2-B: 어떤 매크로 증거 아래에서, 어느 μ 엔진으로 계산했는지.
                          # 능력 레벨은 **MES 행에서 조인해 읽은 값**이지 여기서 새로
                          # 판정한 것이 아니다 — 단일 출처는 계속 MES 다.
                          "mes": mes_block,
                          "mu_engine": opt.get("mu_engine")},
                name=req.run_name,
            )
            payload["run_id"] = rid              # None이면 DB 미가용 — 정직 보고
            payload["run_recorded"] = rid is not None

        return payload
    except HTTPException:
        raise
    except EPUnavailable as e:
        # ★사용자가 고른 엔진으로 계산할 수 없으면 그렇게 답한다 (M2-A)★
        # 500 으로 뭉개면 "서버 오류" 로 읽혀 사용자가 뷰를 고칠 방법을 알 수 없고,
        # 다른 엔진으로 조용히 떨어뜨리면 화면이 거짓말을 한다. 사유를 그대로 준다
        # (`compile_target` 의 ValueError→422 선례와 같은 처리).
        raise HTTPException(422, str(e))
    except Exception:
        logger.exception("allocation analyze 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /backtest — 정책 walk-forward(OOS) ────────────────────────────────────────
@router.post("/backtest")
def allocation_backtest(req: BacktestRequest):
    """정책(모델+뷰+제약+리밸런싱+비용)을 시점 밖으로 재현 — 각 리밸런싱 가중치는
    **그 시점 이전** 데이터로만 산출된다. OOS 자산곡선 + compute_metrics 지표 반환.

    ★"look-ahead 없음" 이라고 적지 않는다★ 이 문장이 예전에 여기 있었고,
    `PolicyBacktest.tsx` 가 그것을 **상수 배지**로 옮겨 적어 화면이 근거 없이
    단정하고 있었다(E). 학습창 격리는 **한 축**일 뿐이고, 이 경로는 생존편향과
    가격 정의를 아예 재지 않는다. 판정은 응답의 `lookahead_evidence` 가 한다 —
    네 축 중 둘이 미상이라 그 롤업은 `verified` 가 될 수 없다."""
    _check_as_of(req.as_of)
    try:
        returns, bench, excluded, coverage = _load_clean_returns(
            req.tickers, req.benchmark, req.lookback_days, as_of=req.as_of)
        if returns is None or len(returns.columns) < 2:
            return {"error": True, "excluded": excluded,
                    "message": "백테스트 가능한 자산이 2개 미만입니다. 시세가 적재된 자산을 추가하세요."}

        return _policy_backtest(req, returns, bench, excluded, coverage)
    except Exception:
        logger.exception("allocation backtest 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


def _policy_backtest(req: BacktestRequest, returns, bench, excluded, coverage) -> dict:
    """적재된 수익률 위에서 정책 walk-forward 를 돌리고 응답을 만든다.

    ★`/backtest` 와 AAS 그래프의 백테스트 노드가 이 함수 하나를 부른다★ (BI2).
    """
    names = list(returns.columns)
    from src.engine.allocation_backtest import walk_forward
    cobj = None
    if req.constraints is not None:
        from src.engine.constrained_opt import Constraints
        cobj = Constraints(**req.constraints.model_dump())
    views = [v.model_dump() for v in (req.views or [])]
    bench_arr = (bench.reindex(returns.index).fillna(0.0).values
                 if bench is not None else None)

    out = walk_forward(
        names, returns.values, list(returns.index),
        model=req.model, views=views or None, constraints=cobj,
        rebalance=req.rebalance, window_days=req.window_days,
        cost_bps=req.cost_bps, bench=bench_arr, delta=req.delta, tau=req.tau)

    out["excluded"] = excluded
    if not out.get("error"):
        out["labels"] = _labels(names)
        out["coverage"] = coverage
        out["benchmark_label"] = req.benchmark if out.get("bench_curve") else None
    # ★이 곡선이 무엇인지 응답이 말한다★ — mock 게이트가 유일한 데이터 판정 기준.
    out["perf_label"] = backtest_label(is_mock_data=mock_allowed()).to_dict()
    # ★룩어헤드를 어디까지 통제했는지도 응답이 말한다★ (E) — 예전에는 화면이
    # 근거 없이 "look-ahead 없음" 이라고 단정했다. 관측·기록만이고 계산은
    # 한 줄도 바뀌지 않는다.
    out["lookahead_evidence"] = lookahead_evidence(coverage)
    return out


# ── /resolve-names ───────────────────────────────────────────────────────────
@router.post("/resolve-names")
def allocation_resolve_names(req: ResolveNamesRequest):
    """코드 목록 → 종목명 라벨(단일 진실 공급원 stock_master). 초기 포트폴리오 구성 시
    종목코드 대신 종목명을 보여주기 위한 배치 해소 (검색·관심그룹·게이트 시드 공통)."""
    codes = [str(c).strip() for c in req.codes if str(c).strip()]
    return {"labels": _labels(codes)}


# ── /factor-portfolio ────────────────────────────────────────────────────────
def _factor_sample_rows(n: int) -> list[dict]:
    """유니버스 팩터 표본 행 — factor-xray와 동일 소스(snapshot_db + mock 폴백)."""
    from src.data.snapshot_db import sample_factors
    sample = sample_factors(n) or []
    if not sample:
        from src.data.mock_gate import mock_allowed
        if mock_allowed():
            from src.data.fundamentals_store import FundamentalsStore
            from src.data.price_factors_store import PriceFactorsStore
            fs = FundamentalsStore.get_default()
            ps = PriceFactorsStore.get_default()
            for i in range(80):
                code = f"{100 + i * 137 % 900:03d}{i * 41 % 1000:03d}"
                row = {"stock_code": code}
                try:
                    row.update(fs.get_factors(code, None) or {})
                    row.update(ps.get_factors(code, None) or {})
                except Exception:
                    continue
                sample.append(row)
    return sample


def _rows_for_tickers(tickers: list[str]) -> list[dict]:
    from src.data.fundamentals_store import FundamentalsStore
    from src.data.price_factors_store import PriceFactorsStore
    fs = FundamentalsStore.get_default()
    ps = PriceFactorsStore.get_default()
    rows = []
    for c in tickers:
        row: dict = {"stock_code": c}
        try:
            row.update(fs.get_factors(c, None) or {})
            row.update(ps.get_factors(c, None) or {})
        except Exception:
            pass
        rows.append(row)
    return rows


def _xf(v, transform):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if transform == "log":
        return math.log10(f) if f > 0 else None
    return f


def _factor_weights(codes: list[str], score_map: dict[str, float],
                    weighting: str, lookback: int,
                    as_of: str | None = None) -> dict[str, float]:
    """top-K 종목 → 비중(%). equal/factor_tilt는 시세 불필요, 나머지는 수익률 기반.

    ★`as_of` 를 버리지 않는다 (P2-R)★ P1-A 가 `_load_clean_returns` 에 as_of 를 넣었는데
    이 함수는 `None` 을 넘기고 있었다. 그러면 같은 as_of 로 만든 알파 점수 위에 **오늘
    기준 공분산**으로 비중을 얹게 되어, 포트폴리오의 절반만 그 시점의 것이 된다.
    """
    n = len(codes)
    if weighting == "equal" or n == 0:
        w = 1.0 / max(n, 1)
        return {c: round(w * 100, 2) for c in codes}
    if weighting == "factor_tilt":
        s = np.array([score_map.get(c, 0.0) for c in codes], dtype=float)
        s = s - s.min() + 1e-6                 # 양수 시프트(순위 보존)
        s = s / s.sum()
        return {codes[i]: round(float(s[i]) * 100, 2) for i in range(n)}
    # 수익률 기반 (inverse_vol|risk_parity|min_var|hrp) — 시세 없으면 균등 폴백
    returns, _b, _ex, _cov = _load_clean_returns(codes, None, lookback, as_of)
    if returns is None or len(returns.columns) < 2:
        w = 1.0 / n
        return {c: round(w * 100, 2) for c in codes}
    names = list(returns.columns)
    R = returns.values
    from src.engine.allocation_studio import _inverse_vol_w, weights_for_model
    wv = _inverse_vol_w(R) if weighting == "inverse_vol" else weights_for_model(weighting, R)
    return {names[i]: round(float(wv[i]) * 100, 2) for i in range(len(names))}


def factor_scores(rows: list[dict], factors: list[FactorSpec]) -> tuple[list[tuple[str, float]], list[dict], dict[str, float]]:
    """방향 인지 z-score 가중합 — `/factor-portfolio` 와 그래프 노드가 같은 함수를 부른다 (BK W2).

    반환 `(ranked, factor_meta, cov_w)` — `ranked` 는 점수 내림차순 `(코드, 점수)`, `cov_w` 는
    종목별 커버된 팩터 가중치 합(1 미만이면 일부 팩터 결측을 재정규화한 것).
    """
    from src.engine.filter_ast import FIELD_BY_ID
    total_w = sum(max(f.weight, 0.0) for f in factors) or 1.0
    scores: dict[str, float] = {}
    cov_w: dict[str, float] = {}
    factor_meta = []
    for f in factors:
        meta = FIELD_BY_ID.get(f.id)
        hb = bool(getattr(meta, "higher_better", True)) if meta else True
        direction = f.direction if f.direction in (1, -1) else (1 if hb else -1)
        pairs = [(r["stock_code"], _xf(r.get(f.id), None)) for r in rows]
        arr = np.array([v for _, v in pairs if v is not None], dtype=float)
        covered = arr.size >= 10 and float(arr.std(ddof=1)) > 1e-12
        factor_meta.append({"id": f.id, "label": getattr(meta, "label", f.id),
                            "direction": direction, "covered": covered, "n": int(arr.size)})
        if not covered:
            continue
        mean, std = float(arr.mean()), float(arr.std(ddof=1))
        wf = max(f.weight, 0.0) / total_w
        for code, v in pairs:
            if v is None:
                continue
            z = float(np.clip((v - mean) / std * direction, -3.0, 3.0))
            scores[code] = scores.get(code, 0.0) + wf * z
            cov_w[code] = cov_w.get(code, 0.0) + wf

    ranked = sorted(((c, scores[c] / cov_w[c]) for c in scores if cov_w[c] > 0),
                    key=lambda x: x[1], reverse=True)
    return ranked, factor_meta, cov_w


@router.post("/factor-portfolio")
def allocation_factor_portfolio(req: FactorPortfolioRequest):
    """팩터 기반 포트폴리오 — 방향 인지 z-score 가중합으로 후보 유니버스를 점수화하고
    상위 K종목을 선정, 지정 방식(균등/팩터틸트/역변동성/리스크패리티/최소분산/HRP)으로 비중화."""
    try:
        from src.data.stock_master import get_stock_name

        rows = _rows_for_tickers(req.tickers) if req.tickers else _factor_sample_rows(req.sample_size)
        rows = [r for r in rows if r.get("stock_code")]
        if len(rows) < max(req.top_k, 3):
            return {"error": True,
                    "message": "후보 종목이 부족합니다. 유니버스를 적재하거나 종목을 직접 지정하세요.",
                    "candidates": len(rows)}

        ranked, factor_meta, cov_w = factor_scores(rows, req.factors)
        if len(ranked) < 2:
            return {"error": True,
                    "message": "선택한 팩터로 점수화 가능한 종목이 부족합니다(팩터 데이터 결측).",
                    "factors": factor_meta, "candidates": len(rows)}

        top = ranked[: req.top_k]
        codes = [c for c, _ in top]
        score_map = {c: round(s, 3) for c, s in top}
        weights = _factor_weights(codes, score_map, req.weighting, req.lookback_days)
        holdings = [{"code": c, "name": get_stock_name(c) or c,
                     "weight": weights.get(c, 0.0), "score": score_map[c],
                     "coverage_pct": round(cov_w.get(c, 0.0) * 100, 0)}
                    for c in codes]
        holdings = [h for h in holdings if h["weight"] > 0]
        holdings.sort(key=lambda h: h["weight"], reverse=True)
        return {"error": False, "holdings": holdings, "factors": factor_meta,
                "weighting": req.weighting, "candidates": len(rows), "ranked": len(ranked),
                # ★후보풀을 남긴다 (P1-B)★ 선정된 상위 K 는 `holdings` 에 있지만, **무엇 중에서
                # 골랐는지**는 지금까지 개수(`candidates`)로만 남았다. 후보풀은
                # `_factor_sample_rows` → `sample_factors`(snapshot_db.py:165)에서 오는데
                # 그 SQL 에는 `ORDER BY` 가 없어 `list(merged.values())[:limit]` 가 안정적이지
                # 않다. **비결정성을 고치지 않고 기록한다** — `ORDER BY` 를 넣으면 500행 초과
                # 환경에서 어느 500개가 뽑히는지가 바뀌어 기업분석 퍼센타일 분포에 파급된다.
                # 재현은 "그때 그 후보풀"을 알면 성립하므로 기록이 옳은 처리다.
                "universe": {"resolved_n": len(rows),
                             "codes": [r["stock_code"] for r in rows],
                             "source": "tickers" if req.tickers else "sample",
                             "note": "표본 순서는 안정적이지 않다 — 재현하려면 이 목록을 "
                                     "tickers 로 그대로 넘겨야 한다."},
                "note": "유니버스 표본 방향 인지 z-score 가중합 → 상위 K 선정. 커버리지 <100%는 일부 팩터 결측 재정규화."}
    except Exception:
        logger.exception("factor-portfolio 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# TargetPortfolioVersion — 실행·스트레스·귀인이 참조하는 불변 목표 (R0-T)
# ─────────────────────────────────────────────────────────────────────────────
# 왜 라우트가 필요한가: 컴파일 산수를 서버에 두는 것만으로는 부족하고, **같은 목표를
# 여러 화면이 id 하나로 가리킬 수 있어야** 오버레이가 실행까지 관통한다.
# ═══════════════════════════════════════════════════════════════════════════════

class TargetVersionRequest(BaseModel):
    base_weights: dict[str, float] = Field(..., min_length=1)      # % (최적화 산출)
    overlay: dict | None = None                                    # {exposure, source}
    neutralized: bool = False                                      # 사후 중립화 적용 여부
    mode: str = "long_only"
    run_id: str | None = None
    snapshot_id: str | None = None
    ruleset_version: str | None = None
    pack_id: str | None = None
    # ── Case 사슬 (M1-V 배선) ──
    # M1-S 가 열과 `compile_target` 인자를 만들었지만 이 라우트가 넘기지 않아서, 사슬은
    # 어떤 경로로도 채워질 수 없었다. 둘 다 선택 필드이고 없으면 동작은 이전과 같다.
    # ★`mes_id` 를 `snapshot_id` 로 기본 채우지 않는다★ `snapshot_id` 는 **세션이 붙인**
    # 스냅샷이고 `mes_id` 는 **케이스가 고정한** 증거다 — 하나로 다른 하나를 채우면
    # "케이스가 고정했다" 는 없는 사실이 만들어진다.
    case_id: str | None = None
    mes_id: str | None = None
    note: str | None = None
    # ★화면 표시용 컴파일은 저장하지 않는다★ 오버레이 슬라이더를 움직일 때마다 행이
    # 쌓이면 감사 기록이 노이즈가 된다. 컴파일러는 하나로 두고 **저장 여부만** 가른다.
    dry_run: bool = False


@router.post("/target-versions")
def target_version_create(req: TargetVersionRequest):
    """오버레이까지 반영한 **최종 목표**를 컴파일해 영속화한다."""
    from src.data.target_versions import compile_target, save_target
    try:
        tv = compile_target(
            req.base_weights, req.overlay, mode=req.mode, neutralized=req.neutralized,
            run_id=req.run_id, snapshot_id=req.snapshot_id,
            ruleset_version=req.ruleset_version, pack_id=req.pack_id,
            case_id=req.case_id, mes_id=req.mes_id,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    if req.dry_run:
        # ★표시용 컴파일은 사슬을 바꾸지 않는다★ 그래도 `case_bound` 키는 낸다 —
        # 소비자가 분기마다 키 유무를 따지게 하지 않는다.
        return {"saved": False, "tpv_id": None, "dry_run": True,
                "case_bound": {"ok": False,
                               "reason": "표시용 컴파일이라 케이스 포인터를 옮기지 않았습니다."},
                **tv}
    tpv_id = save_target(tv, note=req.note)
    # ★케이스 포인터를 여기서 전진시킨다 (M2-D)★ 클라이언트가 만들고 나서 PATCH 를
    # 한 번 더 치는 방식은 반쪽 실패가 가능해, 저장되지 않은 목표를 가리키는 케이스가
    # 남는다. 저장에 성공했을 때만 옮기고, 결과를 `case_bound` 로 되돌려 준다.
    from src.data.research_cases import advance_pointer
    bound = advance_pointer(req.case_id, "tpv", tpv_id)
    if tpv_id is None:
        # ★저장 실패를 성공처럼 답하지 않는다★ 화면이 "저장됐다"고 말하면 안 된다.
        return {"saved": False, "tpv_id": None, "case_bound": bound,
                "message": "저장소 미가용 — 목표 버전이 기록되지 않았습니다.", **tv}
    return {"saved": True, "tpv_id": tpv_id, "case_bound": bound, **tv}


@router.get("/target-versions/{tpv_id}")
def target_version_get(tpv_id: str):
    from src.data.target_versions import get_target
    tv = get_target(tpv_id)
    if tv is None:
        raise HTTPException(404, "목표 버전을 찾을 수 없습니다.")
    return tv


@router.get("/target-versions")
def target_versions_list(limit: int = Query(50, ge=1, le=200)):
    """★빈 목록과 저장소 장애를 구분해 답한다 (R0-S)★
    `list_targets` 는 예외를 삼키지 않으므로 여기서 두 사실이 갈린다."""
    from src.data.target_versions import list_targets
    try:
        return {"available": True, "versions": list_targets(limit)}
    except Exception as e:
        logger.warning(f"target-versions 목록 실패: {e}")
        return {"available": False, "versions": [],
                "reason": "목표 버전 저장소를 읽을 수 없습니다 — 기록이 없는 것과 다릅니다."}


# ═══════════════════════════════════════════════════════════════════════════════
# 리밸런싱 정책 — ★거래 여부를 판단한다★ (Brief §10 · 감사 §3.1)
# ═══════════════════════════════════════════════════════════════════════════════

class RebalanceDecisionRequest(AnalyzeRequest):
    """`AnalyzeRequest` 를 그대로 물려받는다 — 유니버스·모델·절단일·조건부 스위치가
    분석과 **같은 의미**여야 두 화면의 판단이 갈리지 않는다."""
    holdings: dict[str, float] = Field(..., min_length=1)   # 현재 비중 %
    # ★단위를 말할 수 있게 한다★ 합이 1 근처면 "분수로 준 만액" 인지 "퍼센트로 준
    # 소액" 인지 알 수 없고, 두 해석은 **주문 금액이 100배 다르다**(실측).
    weight_unit: str | None = Field(None, max_length=16)     # percent|fraction
    portfolio_value: float = Field(..., gt=0)
    # 없으면 optimize 결과를 목표로 쓴다.
    target_weights: dict[str, float] | None = None
    horizon_days: int = Field(63, ge=1, le=756)             # 보유기간 가정(명시)
    hysteresis_mult: float = Field(0.5, ge=0.0, le=50.0)
    confidence: float | None = Field(None, ge=0.0, le=1.0)  # 점진 이동 α
    last_rebalance_date: str | None = Field(None, max_length=32)
    # 팩터 노출(Brief §8.4) — 매크로 회귀라 느려서 선택으로 둔다.
    factor_exposure: bool = False
    # 팩터 리스크 분해(P3-4)와 역스트레스(Brief §12). 둘 다 팩터 노출이 있어야
    # 뜻이 있으므로 `factor_exposure` 가 꺼져 있으면 무시된다.
    factor_risk: bool = False
    reverse_stress: bool = False
    # 팩터 리스크 모델(§13) — Σ_asset = BΣ_fB' + D 를 optimizer 에 넣는다.
    factor_risk_model: bool = False
    stress_loss_pct: float = Field(-15.0, ge=-90.0, le=-0.1)
    # ── 결정 기록 (opt-in) — ★`record_run` 과 **같은 이유**★ ─────────────────
    #   그 필드의 주석이 이미 답을 적어 뒀다: "슬라이더 드래그마다 DB에 쓰지 않도록
    #   명시 요청 시에만". 리밸런스 판단도 UI 상호작용마다 불릴 수 있으므로 같은
    #   규율을 쓴다 — 기본값에서는 DB 에 한 줄도 쓰지 않는다.
    record_decision: bool = False
    #   결정을 Case 증거 사슬(rc_* → rgs_/tpv_/rr_)에 건다. 없으면 사슬 밖에 남는다.
    case_id: str | None = Field(None, max_length=40)


@router.post("/rebalance-decision")
def rebalance_decision_route(req: RebalanceDecisionRequest):
    """★거래할 가치가 있는가★ — Brief §21 이 시스템에 묻는 질문.

        trade if 효용 개선 > 거래비용 × (1 + 히스테리시스)

    ★트리거만으로 거래하지 않는다★ `portfolio_rebalancer` 의 달력·drift·국면·
    변동성 트리거는 **검토 시점**을 알릴 뿐이다. 거래 근거는 편익 대 비용이고,
    조건부 μ/Σ 가 없으면 `decision="undetermined"` 로 답한다 — 편익을 모르는 채
    거래를 권하는 것이 감사가 지목한 결함이었다.

    무거래 밴드는 **자산마다** 다르다(포지션 크기에 의존). 고정 ±5% 가 아니다.
    """
    _check_as_of(req.as_of)
    _check_weight_unit(req.holdings, req.weight_unit)
    # ★이 계산이 어떤 정보집합 위에 서 있는지 응답이 말한다★ (벤치마크 §4)
    # 선언하지 않은 절단일은 **채우지 않는다** — 비어 있음은 "그 날짜로 잘랐다" 가
    # 아니라 "자른 적이 없다" 는 뜻이고, 채우면 그것이 §4 의 hidden date 다.
    # ★지킨 절단일만 선언한다★ 가격은 `_load_clean_returns(as_of=)` 가 실제로
    # 자르므로 `market_data_as_of` 는 선언할 수 있다. 매크로는 팩터 계열을 자를 수
    # 있었을 때만 아래에서 덧붙인다 — 예전에는 `information_cutoff` 만 적어 놓고
    # 팩터 계층이 오늘 데이터로 계산했다(지키지 않는 절단일을 선언한 것).
    ctx = _research_now(**({"as_of": req.as_of,
                            "market_data_as_of": req.as_of} if req.as_of else {}))
    rc = _describe_context(ctx)
    try:
        from src.engine.investment_decision import decide
        from src.engine.rebalance_policy import detect_triggers

        returns, bench, excluded, coverage = _load_clean_returns(
            req.tickers, req.benchmark, req.lookback_days, as_of=req.as_of)
        if returns is None or len(returns.columns) < 2:
            # ★모든 분기가 같은 키를 낸다★ 어떤 응답에만 `dec_id` 가 있으면 소비자가
            # `.get()` 으로 읽다가 `None` 을 거짓으로 취급한다(레지스트리
            # `not_ingested` 와 같은 규율). ★그리고 이 분기는 결정 계층에 닿지
            # 않는다★ — 문제를 세울 수조차 없었으므로 기록할 판단이 없다.
            return {"available": False, "decision": "undetermined",
                    "reason": "분석 가능한 자산이 2개 미만입니다.", "excluded": excluded,
                    "research_context": rc,
                    "dec_id": None, "persisted": False,
                    "persist_reason": ("유니버스를 세우지 못해 결정 계층에 닿지 "
                                       "않았습니다 — 기록할 판단이 없습니다.")}

        names = list(returns.columns)
        R = returns.values

        # 조건부 μ/Σ — ★`/analyze` 와 **같은 문**을 지난다 (P8 ②)★ 예전에는
        # 같은 순서가 두 번 복사돼 있어, 한쪽만 고치면 화면에 따라 다르게
        # 동작했다. 관문(P5 ③)도 그 문 안에 한 번만 있다.
        # ★`view_confidence` 는 쓰지 않는다★ 이 라우트는 예전부터 `None` 을
        # 넘겨 왔고, 벨리프가 들고 와도 그대로 안 쓴다(행동 불변).
        belief = build_belief(req, returns, names)
        cond, cond_path, cond_meta = belief.cond, belief.path, belief.meta
        s_override, extra_views = belief.s_override, belief.extra_views

        # ★§13 팩터 리스크 모델★ 켜면 표본 공분산 대신 BΣ_fB'+D 를 쓴다.
        # 실패하면 조용히 표본으로 떨어지지 않고 `applied: False` + 사유를 남긴다.
        frm_block = None
        if req.factor_risk_model:
            from src.engine.factor_risk_model import (
                asset_covariance,
                build_factor_risk_model,
            )
            frm = build_factor_risk_model(names, as_of=req.as_of)
            if frm["available"] and frm["codes"] == names:
                s_override = asset_covariance(frm)
                frm_block = {"applied": True, "reason": None,
                             "diagnostics": frm["diagnostics"],
                             "assets": frm["assets"],
                             "excluded": frm["excluded"],
                             "units": "annual", "method": frm["method"]}
            else:
                frm_block = {
                    "applied": False,
                    "reason": (frm.get("reason") or
                               "일부 자산을 추정하지 못해 자산 순서가 어긋납니다 — "
                               "표본 공분산을 그대로 씁니다"),
                    "excluded": frm.get("excluded", {}),
                    "note": "모델을 못 만들면 표본 공분산으로 계산하되 그 사실을 말합니다"}

        # ★`/analyze` 와 **같은 헬퍼**를 탄다★ — 두 화면이 갈리지 않게.
        co_stack = _company_view_stack(req, names)

        from src.engine.allocation_studio import optimize
        opt = optimize(req.model, names, R,
                       views=[v.model_dump() for v in (req.views or [])] or None,
                       delta=req.delta, tau=req.tau,
                       s_override=s_override, extra_views=extra_views,
                       company_views=(co_stack or {}).get("views"))

        if req.target_weights:
            target = {k: float(v) for k, v in req.target_weights.items()}
            target_source = "request"
        else:
            target = {n: round(float(w) * 100.0, 4)
                      for n, w in zip(names, opt["weights"], strict=False)}
            target_source = f"optimize:{req.model}"

        triggers = detect_triggers(
            req.holdings, target, as_of=req.as_of,
            last_rebalance_date=req.last_rebalance_date)

        # ★μ 를 얼마나 모르는지가 밴드를 넓힌다★ (Brief §8.3 → §10)
        # 예전에는 `uncertainty` 인자가 매달려 있었다 — 아무도 공급하지 않았다.
        from src.engine.robust_opt import mu_standard_errors, uncertainty_scalar
        est = mu_standard_errors(R)
        mu_uncertainty = (uncertainty_scalar(est["t"]) if est["available"] else None)

        # ★판단을 여기서 다시 구현하지 않는다★ `decide` 가 상류 원시함수를 부르고,
        # 상류→스토어 매핑과 leg 유도와 영속을 한 곳에서 한다. 예전에는 이 판단이
        # 응답과 함께 사라져 "왜 그때 거래하지 않았나" 를 물을 수 없었다(감사 M2).
        # ★넘기는 인자는 이전과 한 글자도 같다★ — 결정 메타만 더한다.
        decision = decide(
            req.holdings, target, portfolio_value=req.portfolio_value,
            names=names,
            mu=np.asarray(opt["mu_used"], dtype=float),
            sigma=np.asarray(opt["sigma_annual"], dtype=float),
            risk_aversion=req.delta,
            horizon_days=req.horizon_days,
            hysteresis_mult=req.hysteresis_mult,
            confidence=req.confidence,
            uncertainty=mu_uncertainty,
            triggers=triggers,
            as_of=req.as_of, case_id=req.case_id, scope="portfolio",
            belief={
                "mu_source": f"optimize:{req.model}",
                "conditional": bool(req.conditional),
                # ★불확실성이 어디서 왔는지 말한다★ 없으면 없다고 적는다.
                "uncertainty_source": ("mu_standard_errors" if mu_uncertainty is not None
                                       else None),
                "measured": mu_uncertainty is not None,
                # ★μ 가 무엇으로 세워졌는지 기록이 말한다★ (S5) — 나중에 "왜 그때
                # 그렇게 판단했나" 를 물을 때 회사 뷰가 섞였는지가 답의 일부다.
                "company_views_used": int(opt.get("company_views_used") or 0),
            },
            evidence={
                "target_source": target_source,
                "mes_id": req.mes_id,
                "regime_snapshot_id": req.regime_snapshot_id,
                "timing_rule_set_id": req.timing_rule_set_id,
                "timing_rule_set_version": req.timing_rule_set_version,
                # ★이 판단이 어떤 신선도의 데이터 위에 섰는가★ 라우트가 이미 갖고
                # 있는 `coverage` 에서 파생한다 — 나중에 "그때 데이터가 낡았나" 를
                # 물을 수 있어야 한다.
                "data_freshness": _freshness(coverage),
                # ★`constraints_binding` 은 담지 않는다★ 이 라우트는 제약을 적용하지
                # 않는다(그것은 `/analyze` 다). 없는 것을 담지 않는다.
            },
            persist=req.record_decision,
        )
        # ★leg 는 저장 관심사다★ 화면에는 `band.by_asset` 이 이미 같은 정보를 준다 —
        # 두 벌을 실으면 화면이 어느 쪽을 믿을지 갈린다(목표 포트폴리오에서 이미
        # 치른 값이다). 저장된 leg 는 스토어에서 조회한다.
        decision.pop("legs", None)

        # ★이 판단이 무엇 위에 섰는가★ (AA3) — 백테스트의 네 축은 여기서 생산되지
        # 않으므로 `pit_evidence` 를 나르지 않고, **같은 롤업 함수**로 결정 경로가
        # 아는 축 넷을 접는다. `cond_path` 의 `recomputed` 가 곧 관측된 look-ahead 다.
        from src.engine.decision_evidence import decision_evidence
        decision["evidence_rollup"] = decision_evidence(
            coverage=coverage, as_of_requested=req.as_of,
            target_source=target_source, regime_path=cond_path,
            freshness=_freshness(coverage))

        # ★자산 개수가 아니라 팩터 개수★ (Brief §8.4) — 선택.
        factors = None
        if req.factor_exposure:
            from src.engine.factor_exposure import (
                asset_factor_betas,
                factor_concentration,
                portfolio_factor_exposure,
            )
            betas = asset_factor_betas(names, as_of=req.as_of)
            expo = portfolio_factor_exposure(target, betas)
            factors = {"exposure": expo,
                       "concentration": (factor_concentration(expo)
                                         if expo.get("available") else None),
                       "sample": betas.get("sample"),
                       "unresolved": betas.get("unresolved", {})}

            # 팩터 공분산은 리스크 분해와 역스트레스가 함께 쓴다 — 한 번만 만든다.
            fcov = None
            if req.factor_risk or req.reverse_stress:
                from src.engine.factor_exposure import resolve_proxies
                from src.engine.reverse_stress import factor_covariance
                prox = resolve_proxies(as_of=req.as_of)
                fcov = factor_covariance(prox["resolved"])
                # ★지키지 않은 절단일을 선언하지 않는다★ 계열을 자르지 못했으면
                # 그 사실을 사유로 남기고 research_context 의 declared 에서 뺀다.
                # ★"지켰다" 는 두 가지를 모두 요구한다★ 요청한 절단일이 **실제로
                # 내려갔고**(`prox["as_of"] == req.as_of`) 쓰인 계열이 전부 잘렸을 것.
                # 앞의 조건이 없으면 as_of 를 안 넘겨도 `as_of_honored=True`(공허하게
                # 참)가 나와 절단하지 않은 것을 선언하게 된다 — 변이 프로브가 잡았다.
                fcov["as_of_honored"] = bool(
                    prox.get("as_of") == req.as_of
                    and prox.get("as_of_honored", False))
                factors["covariance"] = {k: fcov.get(k) for k in
                                         ("available", "reason", "n_months", "span",
                                          "shrinkage_lambda", "degenerate",
                                          "scale_normalized", "sd_raw", "excluded",
                                          "as_of_honored")}

            if req.factor_risk and fcov is not None:
                from src.engine.factor_risk import (
                    portfolio_factor_risk,
                    portfolio_monthly_returns,
                )
                series = portfolio_monthly_returns(target, as_of=req.as_of)
                factors["risk"] = portfolio_factor_risk(
                    expo, fcov,
                    total_variance=(series["variance"] if series["available"]
                                    else None))
                factors["risk"]["total_variance_source"] = (
                    {"available": series["available"],
                     "reason": series.get("reason"),
                     "coverage_pct": series.get("coverage_pct"),
                     "n_months": len(series.get("months") or [])})

            if req.reverse_stress and fcov is not None:
                from src.engine.reverse_stress import reverse_stress as _rev
                factors["reverse_stress"] = _rev(
                    expo, fcov, loss_pct=req.stress_loss_pct)

        # ★매크로 절단을 실제로 지켰을 때만 선언에 올린다★
        if req.as_of and factors is not None:
            honored = ((factors.get("covariance") or {}).get("as_of_honored")
                       if factors.get("covariance") is not None else None)
            if honored:
                rc = _describe_context(ctx.with_(macro_data_as_of=req.as_of))

        decision.update({
            "risk_model": frm_block,
            "factors": factors,
            "target_weights": target, "target_source": target_source,
            "model": req.model, "coverage": coverage, "excluded": excluded,
            # ★기대수익을 0과 구분할 수 있는가★ 못 하면 밴드가 넓어진다.
            "mu_uncertainty": (None if not est["available"] else {
                "scalar": round(mu_uncertainty, 4),
                "n_resolvable": est["n_resolvable"], "n_assets": len(names),
                "mu_over_se": {nm: round(float(v), 3)
                               for nm, v in zip(names, est["t"], strict=False)},
                "note": est["note"]}),
            # ★조건부를 못 썼으면 응답이 그 사실을 말한다★ (조용한 폴백 금지)
            # ★`/analyze` 와 **같은 수**를 쓴다★ 예전에는 여기만 `len(extra_views)`
            # 였고, 조건부 뷰가 스킵되면(유니버스 밖 자산) 쓰이지 않은 뷰를 쓰인
            # 것으로 셌다 — 과대 진술이다. `optimize` 가 출처로 센 수를 쓴다.
            "conditional": (_conditional_block(
                cond, cond_path, sigma_applied=s_override is not None,
                mu_as_views=int(opt.get("extra_views_used") or 0),
                view_confidence=None, model=req.model, meta=cond_meta,
                universe=names, months=_months_span(returns),
                blocked_reason=belief.blocked_reason)
                if req.conditional else None),
            "research_context": rc,
            "unknown_tickers": _unknown_tickers(req.tickers),
        })
        # ★같은 규율 — 요청했을 때만 키가 늘어난다★ (S5)
        if co_stack is not None:
            decision["company_views"] = co_stack["block"]
        return _finite_payload(decision)
    except HTTPException:
        raise
    except Exception:
        logger.exception("rebalance-decision 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# 경제노출 → 상장 상품 구현 계층 (Brief §7.1/7.2 · CTO §26)
# ═══════════════════════════════════════════════════════════════════════════════

class ImplementExposuresRequest(BaseModel):
    """경제노출 비중 → 상장 상품 비중."""
    exposures: dict[str, float] = Field(..., min_length=1)   # 노출명 → 비중 %
    market: str = Field("kr", max_length=8)                  # kr|us|any
    portfolio_value: float = Field(100_000_000.0, gt=0)


@router.get("/exposures")
def list_exposures():
    """★무엇을 구현할 수 있고 무엇을 모르는가★ 노출 카탈로그 (Brief §7.1).

    후보는 **KR 상장 우선**이고 해외는 `alternatives` 로 함께 나간다. 국내 후보가
    없는 노출은 `market_fallback` 사유가 붙는다 — 조용히 해외로 넘어가지 않는다.

    ★계산할 수 없는 기준은 사유와 함께 나간다★ 이 저장소에는 ETF 메타데이터가
    없어 운용보수·분배금을 낼 수 없다. 빈칸이 아니라 왜 없는지가 정보다.
    """
    try:
        from src.engine.instrument_selector import (
            EXPOSURES,
            UNAVAILABLE_CRITERIA,
            WEIGHTS,
            candidates,
        )
        rows = []
        for name in sorted(EXPOSURES):
            c = candidates(name, market="kr")
            rows.append({
                "exposure": name, "label": EXPOSURES[name]["label"],
                "kr": EXPOSURES[name]["kr"], "us": EXPOSURES[name]["us"],
                "primary": c.get("primary"), "alternatives": c.get("alternatives"),
                "market_fallback": c.get("market_fallback"),
                "note": EXPOSURES[name]["note"],
            })
        return _finite_payload({
            "available": True, "exposures": rows,
            "score_weights": dict(WEIGHTS),
            "unavailable_criteria": dict(UNAVAILABLE_CRITERIA),
            "note": ("KR 상장을 기본 구현으로 삼고 해외는 대안으로 함께 냅니다 — "
                     "환노출과 과세 체계가 다르기 때문입니다"),
        })
    except Exception:
        logger.exception("exposures 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/implement")
def implement_exposures_route(req: ImplementExposuresRequest):
    """노출 비중 → 상품 비중 + 근거 (Brief §7.1/7.2).

    ★구현하지 못한 노출의 비중은 재분배하지 않는다★ 재분배하면 사용자가 요청하지
    않은 노출이 커진다 — `unplaced_pct` 로 남긴다.

    ★상품마다 어느 노출에서 왔는지 남긴다★ 합만 맞추면 노출이 바뀌었을 때 무엇을
    갈아야 하는지 알 수 없다.

    알 수 없는 노출은 500 이 아니라 `unresolved` 에 사유와 함께 담긴다.
    """
    try:
        from src.engine.instrument_selector import implement_exposures
        out = implement_exposures(req.exposures, market=req.market,
                                  portfolio_value=req.portfolio_value)
        out["market"] = req.market
        out["price_source"] = _finite_source()
        return _finite_payload(out)
    except HTTPException:
        raise
    except Exception:
        logger.exception("implement 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


def _finite_source() -> str:
    from src.engine.instrument_selector import _source_label
    return _source_label()
