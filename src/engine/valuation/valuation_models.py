"""
Valuation Models — RIM, DCF, DDM 통합 가치평가 엔진
========================================================
밸리AI의 '종목 가치평가' 탭 (6종 모델)에 대응하는 핵심 모듈.

3가지 가치평가 모델:

① RIM (Residual Income Model, 잔여이익모델):
   V₀ = BPS₀ + Σₜ₌₁ⁿ [(ROEₜ - Kₑ) × BPSₜ₋₁] / (1+Kₑ)ᵗ + TV
   TV = [(ROEₙ - Kₑ) × BPSₙ] / [(Kₑ-g)(1+Kₑ)ⁿ]

② DCF (Discounted Cash Flow, 현금흐름할인법):
   V₀ = Σₜ₌₁ⁿ FCFₜ / (1+WACC)ᵗ + TV / (1+WACC)ⁿ
   TV = FCFₙ × (1+g) / (WACC-g)

③ DDM (Dividend Discount Model, 배당할인법):
   V₀ = Σₜ₌₁ⁿ Dₜ / (1+Kₑ)ᵗ + Pₙ / (1+Kₑ)ⁿ

통합 평가:
   가중 평균 적정가 = w_rim × V_rim + w_dcf × V_dcf + w_ddm × V_ddm
   괴리율 = (현재가 - 적정가) / 적정가 × 100

파라미터:
   Kₑ = Rf + β × (Rm - Rf)           자기자본비용 (CAPM)
   WACC = Kₑ × (E/V) + Kd(1-t)(D/V)  가중평균자본비용
   g = ROE × (1 - payout_ratio)       지속성장률
   Rf = 한국 국채 10년 (3.5% 가정)
   β = 시장 대비 변동성 (1.0 기본)
   Market Premium = 6.0% (한국 ERP)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.data.dart_client import DARTClient, FinancialStatement, get_corp_code

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValuationParams:
    """가치평가 공통 파라미터."""
    risk_free_rate:       float = 0.035    # 한국 국채 10년
    market_premium:       float = 0.060    # 시장 위험 프리미엄 (ERP)
    beta:                 float = 1.0      # CAPM 베타
    terminal_growth_rate: float = 0.02     # 영구 성장률 (명목 GDP 근사)
    projection_years:     int = 10         # 예측 기간
    tax_rate:             float = 0.22     # 법인세율

    # 가중치 (모델별)
    weight_rim:           float = 0.40
    weight_dcf:           float = 0.40
    weight_ddm:           float = 0.20

    @property
    def cost_of_equity(self) -> float:
        """CAPM: Kₑ = Rf + β(Rm-Rf)."""
        return self.risk_free_rate + self.beta * self.market_premium

    @property
    def ke(self) -> float:
        return self.cost_of_equity


@dataclass
class ValuationResult:
    """단일 모델 가치평가 결과."""
    model:          str           # "RIM" | "DCF" | "DDM"
    intrinsic_value_per_share: float   # 적정 주가
    components:     dict = field(default_factory=dict)
    assumptions:    dict = field(default_factory=dict)
    available:      bool = True
    error:          str | None = None


@dataclass
class UnifiedValuation:
    """통합 가치평가 결과 (3 모델 합산)."""
    ticker:                 str
    corp_name:              str
    current_price:          float
    intrinsic_value:        float     # 가중 평균 적정가
    gap_pct:                float     # 괴리율 (%)
    verdict:                str       # 저평가/적정/고평가
    models:                 list      # [ValuationResult × 3]

    financial_summary:      dict = field(default_factory=dict)
    params:                 dict = field(default_factory=dict)
    is_mock:                bool = False   # True면 재무 원천이 합성(mock) 데이터 — 운영에선 발생 안 함


def compute_gap_pct(current_price: float, intrinsic: float) -> float:
    """괴리율 = (현재가 - 적정가) / 적정가 × 100. 적정가 없으면 0(정의 불가)."""
    return ((current_price - intrinsic) / intrinsic * 100) if intrinsic > 0 else 0


def gap_pct_to_verdict(gap_pct: float) -> str:
    """괴리율 → 저평가/적정/고평가 판정 — evaluate()와 screener._enrich_kis_quotes(실시세
    보강 후 재판정)가 동일 임계값을 공유해 두 계산 경로가 어긋나지 않도록 한다."""
    if gap_pct <= -30:
        return "극심한 저평가"
    elif gap_pct <= -15:
        return "저평가"
    elif gap_pct <= -5:
        return "약간 저평가"
    elif gap_pct <= 5:
        return "적정"
    elif gap_pct <= 15:
        return "약간 고평가"
    elif gap_pct <= 30:
        return "고평가"
    else:
        return "극심한 고평가"


# ═══════════════════════════════════════════════════════════════════════════════
# ① RIM — 잔여이익모델
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rim(
    fs: FinancialStatement,
    params: ValuationParams,
    future_roe_trajectory: list[float] | None = None,
) -> ValuationResult:
    """
    Residual Income Model.
    V₀ = BPS₀ + Σ [(ROEₜ - Kₑ) × BPSₜ₋₁] / (1+Kₑ)ᵗ + TV
    """
    try:
        bps = fs.bps
        roe_pct = fs.roe
        if not bps or bps <= 0 or not roe_pct:
            return ValuationResult("RIM", 0, available=False, error="BPS 또는 ROE 없음")

        ke = params.ke
        g = params.terminal_growth_rate
        n = params.projection_years
        roe_decimal = roe_pct / 100

        # ROE 수렴 궤적 (현재 ROE → Ke로 점진 수렴)
        if future_roe_trajectory:
            roe_path = future_roe_trajectory[:n]
        else:
            # 선형 수렴: ROE → Ke + 약간
            target_roe = max(ke + 0.01, roe_decimal * 0.6)
            roe_path = [
                roe_decimal + (target_roe - roe_decimal) * (t / n)
                for t in range(n)
            ]

        # Residual Income 누적
        pv_ri = 0.0
        current_bps = bps
        ri_details = []

        for t in range(1, n + 1):
            roe_t = roe_path[min(t - 1, len(roe_path) - 1)]
            residual_income = (roe_t - ke) * current_bps
            pv_factor = 1 / (1 + ke) ** t
            pv_ri += residual_income * pv_factor

            ri_details.append({
                "year": t,
                "roe": round(roe_t * 100, 2),
                "bps": round(current_bps, 0),
                "residual_income": round(residual_income, 0),
                "pv_factor": round(pv_factor, 4),
            })

            # BPS 성장 (내부 유보)
            payout = (fs.payout_ratio or 30) / 100
            retention = 1 - payout
            current_bps *= (1 + roe_t * retention)

        # Terminal Value
        last_roe = roe_path[-1]
        if (ke - g) > 0.001:
            tv_ri = ((last_roe - ke) * current_bps) / (ke - g)
            pv_tv = tv_ri / (1 + ke) ** n
        else:
            pv_tv = 0

        intrinsic = bps + pv_ri + pv_tv

        return ValuationResult(
            model="RIM",
            intrinsic_value_per_share=max(0, round(intrinsic, 0)),
            components={
                "current_bps":   round(bps, 0),
                "pv_residual":   round(pv_ri, 0),
                "pv_terminal":   round(pv_tv, 0),
                "intrinsic":     round(intrinsic, 0),
            },
            assumptions={
                "ke_pct":             round(ke * 100, 2),
                "current_roe_pct":    round(roe_decimal * 100, 2),
                "terminal_roe_pct":   round(roe_path[-1] * 100, 2),
                "terminal_growth_pct": round(g * 100, 2),
                "projection_years":   n,
            },
        )
    except Exception as e:
        return ValuationResult("RIM", 0, available=False, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# ② DCF — 현금흐름할인법
# ═══════════════════════════════════════════════════════════════════════════════

def compute_dcf(
    fs: FinancialStatement,
    params: ValuationParams,
    fcf_growth_rates: list[float] | None = None,
) -> ValuationResult:
    """
    Discounted Cash Flow.
    V₀ = Σ FCFₜ / (1+WACC)ᵗ + TV / (1+WACC)ⁿ
    """
    try:
        fcf_base = fs.fcf
        shares = fs.shares_outstanding
        if not fcf_base or fcf_base <= 0 or not shares or shares <= 0:
            return ValuationResult("DCF", 0, available=False, error="FCF 또는 발행주식 없음")

        # WACC 계산
        ke = params.ke
        equity = fs.total_equity or 1
        debt = fs.total_liabilities or 0
        total_value = equity + debt
        kd = params.risk_free_rate + 0.015  # 차입 스프레드 1.5%
        wacc = ke * (equity / total_value) + kd * (1 - params.tax_rate) * (debt / total_value)
        wacc = max(wacc, 0.03)  # 최소 3%

        g = params.terminal_growth_rate
        n = params.projection_years

        # FCF 성장 궤적
        if fcf_growth_rates:
            growth_rates = fcf_growth_rates[:n]
        else:
            # 현재 성장률에서 terminal rate로 수렴
            initial_g = min(0.15, max(0.02, (fs.roe or 10) / 100 * 0.5))
            growth_rates = [
                initial_g + (g - initial_g) * (t / n)
                for t in range(n)
            ]

        # FCF 예측 + PV
        pv_fcf = 0.0
        current_fcf = fcf_base
        fcf_details = []

        for t in range(1, n + 1):
            gr = growth_rates[min(t - 1, len(growth_rates) - 1)]
            current_fcf *= (1 + gr)
            pv_factor = 1 / (1 + wacc) ** t
            pv_fcf += current_fcf * pv_factor

            fcf_details.append({
                "year": t,
                "fcf": round(current_fcf / 1e8, 1),  # 억원 단위
                "growth_pct": round(gr * 100, 2),
                "pv_factor": round(pv_factor, 4),
            })

        # Terminal Value (Gordon Growth)
        if (wacc - g) > 0.001:
            tv = current_fcf * (1 + g) / (wacc - g)
            pv_tv = tv / (1 + wacc) ** n
        else:
            pv_tv = 0

        enterprise_value = pv_fcf + pv_tv
        equity_value = enterprise_value - debt
        per_share = max(0, equity_value / shares)

        return ValuationResult(
            model="DCF",
            intrinsic_value_per_share=round(per_share, 0),
            components={
                "base_fcf_억":       round(fcf_base / 1e8, 1),
                "pv_fcf_억":         round(pv_fcf / 1e8, 1),
                "pv_terminal_억":    round(pv_tv / 1e8, 1),
                "enterprise_value_억": round(enterprise_value / 1e8, 1),
                "net_debt_억":       round(debt / 1e8, 1),
                "equity_value_억":   round(equity_value / 1e8, 1),
                "per_share":         round(per_share, 0),
            },
            assumptions={
                "wacc_pct":             round(wacc * 100, 2),
                "ke_pct":               round(ke * 100, 2),
                "kd_pct":               round(kd * 100, 2),
                "terminal_growth_pct":  round(g * 100, 2),
                "projection_years":     n,
                "initial_fcf_growth_pct": round(growth_rates[0] * 100, 2),
            },
        )
    except Exception as e:
        return ValuationResult("DCF", 0, available=False, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# ③ DDM — 배당할인법
# ═══════════════════════════════════════════════════════════════════════════════

def compute_ddm(
    fs: FinancialStatement,
    params: ValuationParams,
    dividend_growth_rate: float | None = None,
) -> ValuationResult:
    """
    Two-stage Dividend Discount Model.
    V₀ = Σₜ₌₁ⁿ Dₜ/(1+Kₑ)ᵗ + Pₙ/(1+Kₑ)ⁿ
    """
    try:
        dps = fs.dps
        if not dps or dps <= 0:
            return ValuationResult("DDM", 0, available=False, error="배당 없음 (DPS=0)")

        ke = params.ke
        g_terminal = params.terminal_growth_rate
        n = params.projection_years

        # 배당 성장률 추정
        if dividend_growth_rate is not None:
            g_high = dividend_growth_rate
        else:
            roe = (fs.roe or 10) / 100
            payout = (fs.payout_ratio or 30) / 100
            retention = 1 - payout
            g_high = min(roe * retention, 0.10)  # 최대 10%

        # Stage 1: 고성장기 (n/2 년)
        high_growth_years = max(3, n // 2)
        # Stage 2: 수렴기 → terminal
        pv_dividends = 0.0
        current_dps = dps
        div_details = []

        for t in range(1, n + 1):
            if t <= high_growth_years:
                gr = g_high
            else:
                # 선형 수렴
                progress = (t - high_growth_years) / (n - high_growth_years)
                gr = g_high + (g_terminal - g_high) * progress

            current_dps *= (1 + gr)
            pv_factor = 1 / (1 + ke) ** t
            pv_dividends += current_dps * pv_factor

            div_details.append({
                "year": t,
                "dps": round(current_dps, 0),
                "growth_pct": round(gr * 100, 2),
            })

        # Terminal price (Gordon Growth at year n)
        if (ke - g_terminal) > 0.001:
            terminal_dps = current_dps * (1 + g_terminal)
            terminal_price = terminal_dps / (ke - g_terminal)
            pv_terminal = terminal_price / (1 + ke) ** n
        else:
            pv_terminal = 0

        intrinsic = pv_dividends + pv_terminal

        return ValuationResult(
            model="DDM",
            intrinsic_value_per_share=max(0, round(intrinsic, 0)),
            components={
                "current_dps":       round(dps, 0),
                "pv_dividends":      round(pv_dividends, 0),
                "pv_terminal_price": round(pv_terminal, 0),
                "intrinsic":         round(intrinsic, 0),
            },
            assumptions={
                "ke_pct":               round(ke * 100, 2),
                "initial_div_growth_pct": round(g_high * 100, 2),
                "terminal_growth_pct":  round(g_terminal * 100, 2),
                "high_growth_years":    high_growth_years,
                "total_years":          n,
                "payout_ratio_pct":     round((fs.payout_ratio or 30), 1),
            },
        )
    except Exception as e:
        return ValuationResult("DDM", 0, available=False, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Unified Valuation Engine
# ═══════════════════════════════════════════════════════════════════════════════

class ValuationEngine:
    """
    3가지 모델을 통합 실행 + 가중 평균 적정가 산출.

    Usage:
        engine = ValuationEngine(dart_client=DARTClient())

        result = engine.evaluate(
            stock_code="005930",
            current_price=71000,
            params=ValuationParams(beta=1.1),
        )

        print(f"적정가: {result.intrinsic_value:,.0f}원")
        print(f"괴리율: {result.gap_pct:+.1f}%")
        print(f"판정: {result.verdict}")
    """

    def __init__(self, dart_client: DARTClient | None = None):
        self.dart = dart_client or DARTClient()

    def load_statement(
        self,
        stock_code: str,
        current_price: float,
        *,
        bsns_year: str | None = None,
        market_cap: float | None = None,
    ) -> dict:
        """종목 코드 → **평가 준비가 끝난** FinancialStatement.

        ★왜 따로 뽑았나 (P2-2)★
        `evaluate` 안에만 있던 준비 구간이다 — corp_code 해석 · 회계연도 기본값 ·
        DART 수집 · **mock 게이트** · 발행주식수/capex 보강 · `compute_ratios`.
        역DCF 가 같은 `fs` 를 필요로 하는데, 자기가 다시 불러오면 이 손질을
        **복제**하게 된다. 같은 산수를 두 곳에 두면 반드시 갈라지고 갈라져도 타입
        에러가 나지 않는다 — 이 저장소가 A1(`currentSig`/`req`)과 R0(오버레이
        컴파일)에서 두 번 값을 치른 실수다.

        ★mock 게이트가 여기 함께 있는 것이 핵심이다★ 운영(`mock_allowed()=False`)에서
        DART 가 실패해 합성 재무로 폴백하면 RIM/DCF/DDM 이 **조용히** 계산되던 버그가
        있었고, 그 방어가 이 함수 안에 있다. 역DCF 가 이 함수를 타는 한 같은 방어를
        공짜로 받는다 — 새 경로가 그 구멍을 다시 열지 않는다.

        Returns:
            `{available, fs, corp_name, is_mock, reason}`.
            `available:false` 면 `fs` 는 `None` 이고 `reason` 이 이유를 말한다.
        """
        # 1. Corp code 변환
        corp_code = get_corp_code(stock_code)
        if not corp_code:
            corp_code = stock_code  # Fallback: 직접 사용

        # 2. 재무제표 수집 (전체항목 — 현금흐름·유동자산 포함 → DCF용 FCF 확보)
        if bsns_year is None:
            from datetime import datetime
            bsns_year = str(datetime.now().year - 1)

        fs = self.dart.get_financial_statement_full(corp_code, bsns_year)
        if not fs:
            return {"available": False, "fs": None, "corp_name": None,
                    "is_mock": False,
                    "reason": f"{bsns_year} 회계연도 재무제표를 가져오지 못했습니다"}

        # DART가 실패해(키미설정/쿼터초과/네트워크 에러 등) 내부적으로 mock 재무제표로 폴백한
        # 경우 — fundamentals_store.py는 이미 이 플래그를 방어하지만(is_mock 체크 후 8년 재탐색
        # + mock_gate 게이트), 이 밸류에이션 엔진에는 동일 방어가 없어 운영(KIS_USE_MOCK=0)에서도
        # DART 호출이 실패하면 합성 재무로 RIM/DCF/DDM이 조용히 계산되던 버그. mock이 허용되지
        # 않는 환경(mock_gate.mock_allowed()=False)이면 "데이터 없음"과 동일한 형태로 정직하게
        # 반환(계산 안 함) — mock이 허용되는 개발/CI 환경에서는 기존처럼 계산은 진행하되
        # is_mock=True로 투명하게 표시한다.
        from src.data.mock_gate import mock_allowed
        fs_is_mock = bool(getattr(fs, "is_mock", False))
        if fs_is_mock and not mock_allowed():
            return {"available": False, "fs": None, "corp_name": None,
                    "is_mock": True,
                    "reason": ("DART 재무를 가져오지 못해 합성 재무로 폴백했고, "
                               "이 환경은 mock 을 허용하지 않습니다 — 계산하지 않습니다")}

        # 발행주식수 보강: DART 미제공 시 시총/주가로 도출 → compute_ratios가 BPS·EPS 계산
        if (not fs.shares_outstanding) and market_cap and current_price and current_price > 0:
            fs.shares_outstanding = int(market_cap * 1e8 / current_price)
        # capex 보강: 미파싱 시 투자활동현금흐름으로 근사 → FCF(=영업CF-capex) 확보 → DCF 활성
        if fs.capex is None and fs.investing_cf is not None:
            fs.capex = abs(fs.investing_cf) * 0.5

        fs.compute_ratios(current_price)
        corp_info = self.dart.get_corp_info(corp_code)
        corp_name = corp_info.corp_name if corp_info else fs.corp_name
        return {"available": True, "fs": fs, "corp_name": corp_name,
                "is_mock": fs_is_mock, "reason": None}

    def evaluate(
        self,
        stock_code: str,
        current_price: float,
        params: ValuationParams | None = None,
        bsns_year: str | None = None,
        market_cap: float | None = None,
        *,
        statement: dict | None = None,
    ) -> UnifiedValuation:
        """종목 코드 → 재무 데이터 수집 → 3 모델 평가 → 통합 결과.

        market_cap(억원)을 받으면 DART가 발행주식수를 안 줘도 시총/주가로 도출해
        BPS·EPS를 채운다 → RIM·DCF가 활성화됨(이게 없으면 '재무 데이터 부족').

        statement: `load_statement` 의 결과를 이미 갖고 있으면 넘긴다 (P2-2).
            CompanySnapshot 이 밸류에이션과 역DCF 를 **한 번의 재무 읽기**로 만들기
            위한 경로다 — P2-1 이 실측한 "딥 탭 재무이력 3회 읽기" 를 스냅샷 안에서
            되풀이하지 않는다. 안 넘기면 동작은 이전과 한 글자도 같다.
        """
        params = params or ValuationParams()

        loaded = statement or self.load_statement(
            stock_code, current_price, bsns_year=bsns_year, market_cap=market_cap)
        if not loaded["available"]:
            from src.data.stock_master import get_stock_name
            return UnifiedValuation(
                ticker=stock_code, corp_name=get_stock_name(stock_code) or stock_code,
                current_price=current_price,
                intrinsic_value=0, gap_pct=0, verdict="데이터 없음",
                models=[], is_mock=loaded["is_mock"],
            )
        fs = loaded["fs"]
        fs_is_mock = loaded["is_mock"]
        corp_name = loaded["corp_name"]

        # 3. 3 모델 실행
        rim_result = compute_rim(fs, params)
        dcf_result = compute_dcf(fs, params)
        ddm_result = compute_ddm(fs, params)

        models = [rim_result, dcf_result, ddm_result]

        # 4. 가중 평균 적정가
        total_weight = 0
        weighted_sum = 0
        weights = {
            "RIM": params.weight_rim,
            "DCF": params.weight_dcf,
            "DDM": params.weight_ddm,
        }

        for m in models:
            if m.available and m.intrinsic_value_per_share > 0:
                w = weights[m.model]
                weighted_sum += m.intrinsic_value_per_share * w
                total_weight += w

        if total_weight > 0:
            intrinsic = weighted_sum / total_weight
        else:
            intrinsic = 0

        # 5. 괴리율 + 판정
        gap_pct = compute_gap_pct(current_price, intrinsic)
        verdict = gap_pct_to_verdict(gap_pct)

        # 6. 재무 요약
        per = current_price / fs.eps if fs.eps and fs.eps > 0 else None
        pbr = current_price / fs.bps if fs.bps and fs.bps > 0 else None

        financial_summary = {
            "revenue_억":          round(fs.revenue / 1e8, 0) if fs.revenue else None,
            "operating_profit_억": round(fs.operating_profit / 1e8, 0) if fs.operating_profit else None,
            "net_income_억":       round(fs.net_income / 1e8, 0) if fs.net_income else None,
            "fcf_억":              round(fs.fcf / 1e8, 0) if fs.fcf else None,
            "total_equity_억":     round(fs.total_equity / 1e8, 0) if fs.total_equity else None,
            "roe_pct":             round(fs.roe, 2) if fs.roe else None,
            "roa_pct":             round(fs.roa, 2) if fs.roa else None,
            "debt_ratio_pct":      round(fs.debt_ratio, 1) if fs.debt_ratio else None,
            "eps":                 round(fs.eps, 0) if fs.eps else None,
            "bps":                 round(fs.bps, 0) if fs.bps else None,
            "dps":                 round(fs.dps, 0) if fs.dps else None,
            "per":                 round(per, 2) if per else None,
            "pbr":                 round(pbr, 2) if pbr else None,
            "dividend_yield_pct":  round(fs.dividend_yield, 2) if fs.dividend_yield else None,
            "payout_ratio_pct":    round(fs.payout_ratio, 1) if fs.payout_ratio else None,
            "bsns_year":           fs.bsns_year,
        }

        return UnifiedValuation(
            ticker=stock_code,
            corp_name=corp_name,
            current_price=current_price,
            intrinsic_value=round(intrinsic, 0),
            gap_pct=round(gap_pct, 2),
            verdict=verdict,
            models=models,
            financial_summary=financial_summary,
            params=params.__dict__,
            is_mock=fs_is_mock,
        )
