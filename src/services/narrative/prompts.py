"""
Prompt Templates — 6 Narrative Domains
==========================================
각 도메인별 system prompt + user prompt 생성 함수.

도메인:
  · stock           — 종목 분석 (Screener Item)
  · portfolio       — 포트폴리오 보고서 (Backtest + Attribution)
  · macro           — 매크로 브리핑 (Regime)
  · operations      — 운영 사건 분석 (Kill switch + Audit)
  · counterfactual  — What-If 시나리오 해설
  · daily_summary   — 일일 요약

설계 원칙:
  · 모든 prompt는 한국어
  · 구조화된 출력 (Markdown 헤더 + 표)
  · 인용 출처 명시 (DART / KIS / 백테스트 결과)
  · 단정 회피, 가능성/확률 표현 권장
  · 투자 권유 금지 — "분석 의견" 명시
"""

from __future__ import annotations

import json

# ═══════════════════════════════════════════════════════════════════════════════
# 공통 System Persona
# ═══════════════════════════════════════════════════════════════════════════════

QUANT_ANALYST_PERSONA = """당신은 기관급 한국 주식 퀀트 분석가입니다.

분석 원칙:
1. **숫자 기반**: 모든 결론은 제공된 수치를 인용해야 합니다.
2. **인과 분석**: "X 때문에 Y" 형태의 명확한 인과를 제시하되, 추측은 "~로 추정됩니다" 표현.
3. **균형 시각**: 강점과 약점, 기회와 위험을 모두 언급합니다.
4. **출처 명시**: DART, KIS, 백테스트 결과 등 데이터 출처를 명시합니다.
5. **투자 권유 금지**: "매수/매도하세요" 대신 "분석 결과는 ~" 또는 "~가능성이 높습니다" 사용.

출력 형식:
- Markdown 헤더 구조 (`##`, `###`)
- 핵심 지표는 표 (`|`)로 정리
- 인용은 `>` blockquote
- 마지막에 **결론** 섹션 (3-5줄 요약)

문체: 전문가가 동료에게 보고하는 어조. 한국어. 영어 용어는 괄호 병기 (예: 자기자본비용(Ke))."""


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Stock Analysis Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def stock_analysis_prompt(stock_item: dict, valuation_detail: dict) -> tuple[str, str]:
    """
    종목 분석 prompt 생성.

    Args:
        stock_item: ScreenerItem 데이터 (stock_code, corp_name, gap_pct, scores 등)
        valuation_detail: ValuationDetail (3 모델 결과 + financial_summary)
    """
    system = QUANT_ANALYST_PERSONA + """

당신의 임무: 사용자가 제공한 종목의 가치평가 결과를 분석하고, 다음 구조로 보고서를 작성합니다.

## 구조
### 1. 핵심 평가 (3-4줄)
현재가, 통합 적정가, 괴리율, 판정을 명료하게.

### 2. 가치평가 모델별 분석 (표 + 3-5줄)
RIM/DCF/DDM 각 모델의 적정가를 비교하고, 모델 간 일관성/불일치를 해설.

### 3. 재무 요인 분해
ROE, FCF, 부채비율, EPS/BPS/DPS를 근거로 저평가/고평가 원인 설명.

### 4. 위험 요인 (3-5개 항목)
정량 + 정성 위험을 균형 있게.

### 5. 결론
3-5줄로 종합 의견 (투자 권유 X, "분석 결과는 ~" 형태)"""

    user = f"""다음 종목의 통합 가치평가 결과를 분석해주세요:

## 종목 정보
- **종목명**: {stock_item.get('corp_name', '미상')}
- **종목코드**: {stock_item.get('stock_code', '?')}
- **업종**: {stock_item.get('sector', '미분류')}

## 가격 vs 가치
- 현재가: {stock_item.get('current_price', 0):,.0f}원
- 통합 적정가 (RIM·DCF·DDM 가중평균): {stock_item.get('intrinsic_value', 0):,.0f}원
- 괴리율: {stock_item.get('gap_pct', 0):+.2f}%
- 판정: {stock_item.get('verdict', '?')}

## 모델별 적정가
- RIM (잔여이익): {stock_item.get('rim_value') or 'N/A'}원
- DCF (현금흐름): {stock_item.get('dcf_value') or 'N/A'}원
- DDM (배당할인): {stock_item.get('ddm_value') or 'N/A'}원

## Composite Score Breakdown (100점 만점)
- 종합 점수: {stock_item.get('composite_score', 0):.1f}점
- 저평가 점수 (60%): {stock_item.get('gap_score', 0):.1f}점
- ROE 점수 (20%): {stock_item.get('roe_score', 0):.1f}점
- 안정성 점수 (20%): {stock_item.get('stability_score', 0):.1f}점

## 재무 지표 ({valuation_detail.get('financial_summary', {}).get('bsns_year', '?')}년 결산)
{_format_financial_summary(valuation_detail.get('financial_summary', {}))}

## 모델별 핵심 가정
{_format_model_assumptions(valuation_detail.get('models', []))}

위 데이터를 종합 분석해 보고서를 작성해주세요."""

    return system, user


def _format_financial_summary(fin: dict) -> str:
    rows = []
    items = [
        ("매출액", "revenue_억", "억"),
        ("영업이익", "operating_profit_억", "억"),
        ("순이익", "net_income_억", "억"),
        ("FCF (잉여현금흐름)", "fcf_억", "억"),
        ("ROE", "roe_pct", "%"),
        ("ROA", "roa_pct", "%"),
        ("EPS", "eps", "원"),
        ("BPS", "bps", "원"),
        ("DPS (배당)", "dps", "원"),
        ("PER", "per", "배"),
        ("PBR", "pbr", "배"),
        ("배당수익률", "dividend_yield_pct", "%"),
        ("부채비율", "debt_ratio_pct", "%"),
    ]
    for label, key, unit in items:
        val = fin.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            rows.append(f"- {label}: {val:,.2f}{unit}" if unit == "%" or unit == "배"
                          else f"- {label}: {val:,.0f}{unit}")
        else:
            rows.append(f"- {label}: {val}{unit}")
    return "\n".join(rows) if rows else "- 데이터 없음"


def _format_model_assumptions(models: list) -> str:
    out = []
    for m in models:
        if not m.get("available"):
            continue
        out.append(f"\n### {m.get('model', '?')}")
        for k, v in (m.get("assumptions") or {}).items():
            out.append(f"  - {k}: {v}")
    return "\n".join(out) if out else "  - 가정 정보 없음"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Portfolio Report Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def portfolio_report_prompt(backtest_result: dict, attribution: dict) -> tuple[str, str]:
    """
    백테스트 결과 + 5-Factor Attribution 기반 포트폴리오 보고서.
    """
    system = QUANT_ANALYST_PERSONA + """

당신의 임무: 멀티 전략 백테스트 결과를 5-Factor Attribution과 함께 분석합니다.

## 구조
### 1. 종합 성과 요약 (표)
누적 수익률, 연환산, Sharpe, MDD, Calmar 등.

### 2. 5-Factor Attribution 해석
각 요인(Allocation/Selection/Macro/Netting/Cost)의 기여도를 분석하고,
"왜 그 결과가 나왔는지"를 데이터로 설명.

### 3. Regime별 성과 (4-Quadrant)
Goldilocks/Reflation/Stagflation/Deflation 별 alpha 비교.

### 4. 강점 + 약점 + 개선점
- 강점 3-5개 (어떤 환경에서 강했는지)
- 약점 3-5개 (어떤 시기에 손실)
- 개선 제안 (구체적 행동 가능 항목)

### 5. 결론
포트폴리오 등급(우수/양호/보통/부적합) + 다음 단계 권고."""

    user = f"""다음 멀티 전략 백테스트 결과를 분석해주세요:

## 백테스트 메타
- 기간: {backtest_result.get('start_date', '?')} ~ {backtest_result.get('end_date', '?')}
- 거래일: {backtest_result.get('n_days', 0)}일
- 전략 수: {backtest_result.get('n_strategies', 0)}개
- 초기 자본: {backtest_result.get('initial_capital', 0):,.0f}원

## 성과 지표
- 누적 수익률: {backtest_result.get('total_return_pct', 0):+.2f}%
- 연환산 수익률: {backtest_result.get('cagr_pct', 0):+.2f}%
- Sharpe 비율: {backtest_result.get('sharpe_ratio', 0):.3f}
- 최대 낙폭 (MDD): {backtest_result.get('max_drawdown_pct', 0):.2f}%
- Calmar 비율: {backtest_result.get('calmar_ratio', 0):.3f}
- Sortino 비율: {backtest_result.get('sortino_ratio', 0):.3f}
- 승률: {backtest_result.get('win_rate_pct', 0):.1f}%

## 5-Factor Attribution (단위: %p)
{_format_attribution(attribution)}

## Regime별 Alpha (4-Quadrant)
{_format_regime_alpha(attribution.get('regime_alpha', {}))}

위 데이터를 기반으로 포트폴리오 분석 보고서를 작성해주세요."""

    return system, user


def _format_attribution(attr: dict) -> str:
    factors = attr.get("factors", {})
    if not factors:
        return "- 데이터 없음"
    return "\n".join(
        f"- **{name}**: {val:+.2f}%p"
        for name, val in factors.items()
    )


def _format_regime_alpha(regime_alpha: dict) -> str:
    if not regime_alpha:
        return "- 데이터 없음"
    return "\n".join(
        f"- **{regime}**: alpha {val:+.2f}%p"
        for regime, val in regime_alpha.items()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Macro Briefing Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def macro_briefing_prompt(regime_state: dict) -> tuple[str, str]:
    """매크로 환경 + Regime 판정 → 시장 시사점."""
    system = QUANT_ANALYST_PERSONA + """

당신의 임무: 현재 매크로 환경을 진단하고 시장 시사점을 제공합니다.

## 구조
### 1. 현재 국면 진단
4-Quadrant Regime + Systemic Risk Score + 핵심 매크로 지표 5종 표.

### 2. 국면 해석 (왜 이 국면인가)
각 매크로 지표가 어떤 신호를 보내는지 분석.

### 3. 자산군별 시사점
- 주식: 적정 노출도
- 채권: 듀레이션 권고
- FX: KRW 전망
- 원자재: Gold/Oil 포지셔닝

### 4. 모니터링 트리거
다음 국면 전환을 감지할 핵심 지표 3-5개 + 임계값.

### 5. 결론
현재 권고 모드 (Risk-On/Neutral/Risk-Off) + 다음 점검 시점."""

    user = f"""현재 매크로 환경 데이터:

## Regime 판정
- 현재 국면: **{regime_state.get('regime', '?')}**
- Systemic Risk Score: {regime_state.get('systemic_risk_score', 0):.1f} / 100
- 모드: {regime_state.get('mode', 'NORMAL')} (NORMAL/CAUTIOUS/DEFENSIVE)

## 5종 매크로 지표
- SPX (미국 주식): {regime_state.get('spx', 0):,.2f}, 추세 {regime_state.get('spx_trend', '?')}
- VIX (변동성): {regime_state.get('vix', 0):.2f} (5년 평균 18.5)
- T10Y2Y Spread: {regime_state.get('t10y2y_bps', 0):+.1f}bp
- DXY (달러 인덱스): {regime_state.get('dxy', 0):.2f}
- Gold (금): ${regime_state.get('gold', 0):.0f}/oz

## 신호 패턴
- VIX 신호: {regime_state.get('vix_signal', '?')}
- 금리 신호: {regime_state.get('rate_signal', '?')}
- USD 신호: {regime_state.get('usd_signal', '?')}

위 환경 데이터를 종합 분석해 매크로 브리핑을 작성해주세요."""

    return system, user


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Operations Analysis Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def operations_analysis_prompt(events: list, audit_summary: dict) -> tuple[str, str]:
    """Kill switch + 운영 audit log → 사후 분석."""
    system = QUANT_ANALYST_PERSONA + """

당신의 임무: 실거래 운영 중 발생한 사건을 사후 분석합니다.

## 구조
### 1. 사건 개요
- 발생 시각, 트리거 종류, 자산 영향
- 5-Layer Safety 중 어느 단계에서 차단됐는지

### 2. 인과 분석
1) 직접 트리거 (구체적 임계값)
2) 선행 신호 (사건 직전 24시간의 audit log 패턴)
3) 시장 환경 (VIX, regime, drift 등)

### 3. 시스템 반응 평가
- 자동 액션이 적절했는지 (취소/청산 모드)
- 알림 발송 / 로깅이 정상이었는지
- 복구 시간

### 4. 권고 조치
- 즉시 조치: 시스템 점검 항목
- 단기 (1주일): 룰 보강
- 장기 (1개월): 아키텍처 개선

### 5. 결론
재발 방지 전략 요약."""

    user = f"""실거래 운영 사건 데이터:

## 발생한 이벤트
{json.dumps(events, ensure_ascii=False, indent=2, default=str)[:3000]}

## Audit Summary (해당 기간)
- 총 이벤트: {audit_summary.get('total_events', 0)}
- INFO: {audit_summary.get('by_severity', {}).get('INFO', 0)}
- WARN: {audit_summary.get('by_severity', {}).get('WARN', 0)}
- ERROR: {audit_summary.get('by_severity', {}).get('ERROR', 0)}
- CRITICAL: {audit_summary.get('by_severity', {}).get('CRITICAL', 0)}

## 카테고리별 분포
{json.dumps(audit_summary.get('by_category', {}), ensure_ascii=False, indent=2)}

위 데이터를 기반으로 운영 사건 사후 분석 보고서를 작성해주세요."""

    return system, user


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Counterfactual Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def counterfactual_prompt(actual: dict, scenarios: list[dict]) -> tuple[str, str]:
    """What-If 시나리오 비교 → 의사결정 가치 정량화."""
    system = QUANT_ANALYST_PERSONA + """

당신의 임무: 실제 실행 결과 vs N가지 가상 시나리오를 비교하여 각 의사결정의 가치를 정량화합니다.

## 구조
### 1. 실제 vs 가상 시나리오 비교 표
모든 시나리오의 핵심 지표 (수익률/Sharpe/MDD)를 한 표에.

### 2. 각 시나리오 해석
"만약 X를 안 했다면 Y"의 형태로 각 시나리오의 의미를 설명.

### 3. 결정 가치 (Decision Value)
실제 시스템의 핵심 결정들이 얼마만큼의 가치를 만들었는지 정량 평가.

### 4. 학습 포인트
- 어떤 결정이 가장 큰 가치를 만들었나
- 어떤 결정이 효과가 작았나 (제거 검토)
- 추가로 검증할 가설

### 5. 결론
실제 시스템의 우수 의사결정 3개 + 개선 여지 2개."""

    user = f"""Counterfactual 분석 데이터:

## 실제 실행 결과
- 총 수익률: {actual.get('total_return_pct', 0):+.2f}%
- Sharpe: {actual.get('sharpe_ratio', 0):.3f}
- MDD: {actual.get('max_drawdown_pct', 0):.2f}%

## 가상 시나리오 ({len(scenarios)}개)
{_format_scenarios(scenarios)}

위 데이터를 기반으로 counterfactual 분석을 작성해주세요."""

    return system, user


def _format_scenarios(scenarios: list[dict]) -> str:
    if not scenarios:
        return "- 시나리오 없음"
    out = []
    for i, s in enumerate(scenarios, 1):
        out.append(f"""
### 시나리오 {i}: {s.get('name', '?')}
- 설명: {s.get('description', '?')}
- 총 수익률: {s.get('total_return_pct', 0):+.2f}%
- Sharpe: {s.get('sharpe_ratio', 0):.3f}
- MDD: {s.get('max_drawdown_pct', 0):.2f}%
- 실제 대비 차이: {s.get('delta_return_pct', 0):+.2f}%p""")
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Daily Summary Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def daily_summary_prompt(activities: dict) -> tuple[str, str]:
    """모든 활동 통합 일일 요약."""
    system = QUANT_ANALYST_PERSONA + """

당신의 임무: 하루의 모든 활동을 통합 요약합니다.

## 구조
### 1. 한 줄 요약 (Hero)
오늘의 가장 중요한 한 가지.

### 2. 운영 현황
- Live trading 모드
- 발주 / 체결 / 거부 통계
- Kill switch 활성 여부
- API 호출 통계

### 3. 시장 환경 변화
어제 → 오늘 regime/risk score 변화.

### 4. 포트폴리오 변동
잔고 변화, 신규 포지션, 청산.

### 5. 알림 / 경고
WARN/CRITICAL 이벤트 요약.

### 6. 내일 점검 사항
- 자동 룰 다음 트리거 시점
- 사용자 확인 필요 항목

문체: 간결하고 사실 위주. 모든 섹션은 짧고 명료하게."""

    user = f"""오늘의 활동 데이터:

## 운영 통계
{json.dumps(activities.get('operations', {}), ensure_ascii=False, indent=2)[:1500]}

## 시장 환경
{json.dumps(activities.get('market', {}), ensure_ascii=False, indent=2)[:1000]}

## 포트폴리오
{json.dumps(activities.get('portfolio', {}), ensure_ascii=False, indent=2)[:1000]}

## 알림
{json.dumps(activities.get('alerts', []), ensure_ascii=False, indent=2, default=str)[:1500]}

위 데이터를 기반으로 일일 요약 보고서를 작성해주세요."""

    return system, user
