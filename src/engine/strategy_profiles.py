"""전략 상세 카탈로그 — 22전략 큐레이션 설명 + 레퍼런스 + 성과곡선/국면적합도 병합
==========================================================================
05 Strategies 카드 클릭 시 모달이 쓰는 단일 소스. 정적 프로파일(개념·작동방식·근거·국면·
파라미터·레퍼런스) + 라이브(보유·시그널·국면적합도·현재비중 과거성과 곡선) 병합.
과거 성과 곡선 = 현재 비중 고정 월리밸런스 buy&hold(전략 동적 리밸런싱 풀백테스트 아님).
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta


# ── 22 전략 큐레이션 프로파일 ──────────────────────────────────────────────────
def _ref(authors: str, year: str, title: str, venue: str = "") -> dict:
    return {"authors": authors, "year": year, "title": title, "venue": venue}


PROFILES: dict[str, dict] = {
    # ── 모멘텀 13 ──
    "classic_dm": {
        "concept": "절대 모멘텀(추세 필터)과 상대 모멘텀(승자 선택)을 결합해 한 자산에 집중하는 가장 단순한 듀얼모멘텀.",
        "mechanism": ["미국주식(SPY)의 12개월 수익률이 0보다 크면(절대 모멘텀) 위험자산 보유, 아니면 채권(AGG)으로 회피.",
                      "위험자산일 때는 미국(SPY)·선진국(EFA) 중 12개월 수익률이 높은 쪽을 선택(상대 모멘텀)."],
        "rationale": "추세 지속성(모멘텀)은 행동재무학적 과소반응·군집에서 비롯되는 가장 강건한 시장 이상현상. 절대 모멘텀이 약세장 큰 손실을 차단한다.",
        "regime_note": "추세가 분명한 리플레이션·과열 국면에 강함. 급반전(휩쏘) 구간에서 약함.",
        "params": {"룩백": "12개월 절대/상대", "유니버스": "SPY·EFA·AGG", "리밸런스": "월간"},
        "references": [_ref("Gary Antonacci", "2014", "Dual Momentum Investing", "McGraw-Hill")],
    },
    "composite_dm": {
        "concept": "주식·채권·부동산·대체 4개 슬리브 각각에 듀얼모멘텀을 적용해 분산된 듀얼모멘텀.",
        "mechanism": ["4슬리브(주식 SPY/EFA · 신용 HYG/LQD · 부동산 REM/VNQ · 실물 GLD/PDBC) 각각에서 상대 승자 선택.",
                      "각 슬리브 승자의 12개월 절대 모멘텀이 음수면 그 슬리브는 현금(BIL)으로.",
                      "슬리브당 25% 동일 배분."],
        "rationale": "단일자산 듀얼모멘텀의 집중 위험을 자산군 분산으로 완화하면서 추세 추종의 이점은 유지.",
        "regime_note": "여러 자산군에 추세가 동시에 살아있는 국면에 유리. 전 자산군 무추세면 현금 비중↑.",
        "params": {"룩백": "12개월", "유니버스": "4슬리브 8종", "리밸런스": "월간"},
        "references": [_ref("Gary Antonacci", "2012", "Risk Premia Harvesting Through Dual Momentum", "SSRN")],
    },
    "accel_dm": {
        "concept": "1·3·6개월 단기 모멘텀을 합산(가속)해 추세 전환에 더 빠르게 반응하는 듀얼모멘텀.",
        "mechanism": ["SPY·선진소형(SCZ)의 (1개월+3개월+6개월) 수익률 합으로 승자 선택.",
                      "승자의 가속 모멘텀이 0보다 크면 보유, 아니면 장기채(TLT)로 회피."],
        "rationale": "장기(12개월) 모멘텀보다 짧은 창을 가중해 추세 전환 시점을 앞당겨 포착 — 반응성↑.",
        "regime_note": "국면 전환이 잦은 환경에서 12개월 모멘텀보다 민첩. 노이즈가 큰 구간에선 과민 반응 위험.",
        "params": {"룩백": "1+3+6개월 합", "유니버스": "SPY·SCZ·TLT", "리밸런스": "월간"},
        "references": [_ref("EngineeredPortfolio", "2018", "Accelerating Dual Momentum", "실무 블로그")],
    },
    "permanent": {
        "concept": "어떤 경제 국면에도 견디도록 주식·장기채·금·현금을 25%씩 고정 보유하는 영구 포트폴리오.",
        "mechanism": ["주식(SPY)·장기국채(TLT)·금(GLD)·현금(BIL) 각 25% 고정.",
                      "예측 없이 정기 리밸런스로 비중 복원."],
        "rationale": "4자산이 호황·불황·인플레·디플레 각 국면에서 번갈아 방어 — 예측 불요의 항상성 분산.",
        "regime_note": "전 국면에 무난(특정 국면 최적화 아님). 강세장에선 주식 100% 대비 후행.",
        "params": {"비중": "25/25/25/25 고정", "유니버스": "SPY·TLT·GLD·BIL", "리밸런스": "분기/연간"},
        "references": [_ref("Harry Browne", "1999", "Fail-Safe Investing (Permanent Portfolio)", "St. Martin's")],
    },
    "laa": {
        "concept": "정적 3자산 + 경기 신호 1자산으로, 경기·추세가 동시에 꺾일 때만 방어로 전환하는 게으른 배분.",
        "mechanism": ["가치주(IWD)·금(GLD)·중기채(IEF) 각 25% 고정.",
                      "나머지 25%는 경기 스위치: SPY가 200일선 위면 나스닥(QQQ), 아래면 단기채(SHY)."],
        "rationale": "잦은 매매를 피하면서(게으름) 추세(200일선)가 명확히 꺾일 때만 위험을 줄여 거래비용·휩쏘 최소화.",
        "regime_note": "느린 국면 전환에 적합. 급락엔 200일선 신호가 후행해 한 박자 늦음.",
        "params": {"고정": "IWD·GLD·IEF 75%", "스위치": "SPY 200일선 → QQQ/SHY", "리밸런스": "월간 점검"},
        "references": [_ref("Philosophical Economics", "2016", "Growth-Trend Timing", "실무 연구")],
    },
    "raa": {
        "concept": "여러 자산에 절대 모멘텀을 적용해 추세가 살아있는 것만 동일가중 보유하는 강건한 배분.",
        "mechanism": ["나스닥(QQQ)·소형가치(IWN)·중기채(IEF)·장기채(TLT)·금(GLD) 각각 12개월 절대 모멘텀 점검.",
                      "양(+)인 자산만 보유, 음(−)이면 그 몫은 현금(BIL). 보유분 동일가중."],
        "rationale": "단순·투명한 규칙으로 과최적화를 피하고(robust) 약세 자산을 자동 배제.",
        "regime_note": "다자산 추세 환경에 강건. 전 자산 약세면 현금화로 방어.",
        "params": {"룩백": "12개월 절대", "유니버스": "5자산", "리밸런스": "월간"},
        "references": [_ref("Wesley Gray & Jack Vogel", "2015", "DIY Financial Advisor — Robust Asset Allocation", "Wiley")],
    },
    "gtaa": {
        "concept": "5개 자산군을 10개월 이동평균 위/아래로 켜고 끄는 Faber의 글로벌 택티컬 자산배분.",
        "mechanism": ["미국주식(SPY)·선진국(EFA)·중기채(IEF)·실물(PDBC)·부동산(VNQ) 각 20%.",
                      "각 자산이 10개월 이동평균 위면 보유, 아래면 그 몫 현금(BIL)."],
        "rationale": "10개월(≈200일) 이동평균은 장기 추세의 단순·강건한 대용치 — 큰 하락장 회피에 효과적.",
        "regime_note": "추세 추종형 — 지속 추세에 유리, 횡보장 휩쏘에 약함.",
        "params": {"신호": "10개월 이동평균", "유니버스": "5자산", "리밸런스": "월간"},
        "references": [_ref("Meb Faber", "2007", "A Quantitative Approach to Tactical Asset Allocation", "J. of Wealth Management")],
    },
    "paa": {
        "concept": "위험자산 중 추세가 살아있는 비율(breadth)로 채권 보호 강도를 조절하는 보호적 자산배분.",
        "mechanism": ["위험자산(SPY·IWM·QQQ·EWJ·EEM)의 12개월 이동평균 상회 개수로 '나쁜 자산' 비율 산정.",
                      "나쁜 자산이 많을수록 채권(IEF) 보호 비중↑, 좋은 자산은 동일가중 보유."],
        "rationale": "시장 폭(breadth)이 약해질수록 점진적으로 방어를 강화 — 단계적 디리스킹.",
        "regime_note": "하락 진입을 폭으로 조기 감지해 방어. 강세 지속 시 보호비용으로 다소 후행.",
        "params": {"신호": "12개월 이동평균 breadth", "보호자산": "IEF", "리밸런스": "월간"},
        "references": [_ref("Wouter Keller & Jan Keuning", "2016", "Protective Asset Allocation (PAA)", "SSRN")],
    },
    "vaa": {
        "concept": "공격 자산 전부가 양의 모멘텀일 때만 공격, 하나라도 음이면 방어로 전환하는 민감한 카나리아 전략.",
        "mechanism": ["공격(SPY·EFA·EEM·AGG)의 13612W 가속모멘텀이 모두 양(+)이면 그 중 최고 1종 보유.",
                      "하나라도 음(−)이면 방어(LQD·IEF·SHY) 중 최고로 전량 회피."],
        "rationale": "13612W(12·r1+4·r3+2·r6+1·r12)는 최근 가중 모멘텀 — 카나리아(조기 경보)로 약세를 빠르게 차단.",
        "regime_note": "방어 전환이 매우 민감 — 급락 방어에 강하나 잦은 전환으로 휩쏘 가능.",
        "params": {"신호": "13612W 가속", "카나리아": "공격 4종 전부 양", "리밸런스": "월간"},
        "references": [_ref("Wouter Keller & Jan Keuning", "2017", "Breadth Momentum and Vigilant Asset Allocation (VAA)", "SSRN")],
    },
    "faa": {
        "concept": "모멘텀·변동성·상관을 함께 본 일반화 모멘텀으로 상위 자산을 고르는 유연한 자산배분.",
        "mechanism": ["8자산(VTI·EFA·EEM·IEF·TLT·GLD·PDBC·VNQ)의 4개월 모멘텀 상위 3종 선택.",
                      "선택분 중 모멘텀이 양(+)인 것만 동일가중, 없으면 현금."],
        "rationale": "수익(모멘텀)뿐 아니라 위험(변동성)·분산(상관)을 결합해 더 안정적인 상위 선택.",
        "regime_note": "다자산 추세 환경에 유리. 단기(4개월) 신호라 반응성↑·노이즈 노출도↑.",
        "params": {"룩백": "4개월", "선택": "상위 3 동일가중", "리밸런스": "월간"},
        "references": [_ref("Wouter Keller & Hugo van Putten", "2012", "Generalized Momentum and Flexible Asset Allocation (FAA)", "SSRN")],
    },
    "aaa": {
        "concept": "13612W 모멘텀 상위 자산을 고르되 위험회피 시 방어자산으로 전환하는 적응형 자산배분.",
        "mechanism": ["8자산의 13612W 점수 상위 중 양(+)인 것 최대 4종 선택·동일가중.",
                      "양의 자산이 2개 미만이면 방어(IEF 중심 + 소량 PDBC)로 전환."],
        "rationale": "추세 강도에 따라 공격 자산 수를 적응적으로 조절 — 약세엔 자연히 방어로 수렴.",
        "regime_note": "광범위 추세에 공격적, 추세 소멸 시 방어. 중간 국면에 균형적.",
        "params": {"신호": "13612W", "선택": "상위 ≤4", "리밸런스": "월간"},
        "references": [_ref("Butler, Philbrick & Gordillo", "2012", "Adaptive Asset Allocation", "SSRN/ReSolve")],
    },
    "daa": {
        "concept": "카나리아(EEM·AGG) 신호로 공격/방어를 결정하는 방어 특화 자산배분.",
        "mechanism": ["카나리아(EEM·AGG)의 13612W가 모두 양(+)이면 공격(7자산 상위 2종).",
                      "하나라도 음(−)이면 방어(IEF·LQD·SHY 중 최고)로 회피."],
        "rationale": "신흥국·채권을 조기 경보로 삼아 VAA보다 매매를 줄이면서 약세를 방어.",
        "regime_note": "급락 방어에 강하고 VAA보다 거래 빈도↓. 강세 초기 진입이 다소 보수적.",
        "params": {"카나리아": "EEM·AGG", "공격": "7자산 상위 2", "리밸런스": "월간"},
        "references": [_ref("Wouter Keller & Jan Keuning", "2018", "Defensive Asset Allocation (DAA)", "SSRN")],
    },
    "bond_dynamic": {
        "concept": "채권 섹터(장기·하이일드·신흥·중기·IG) 간 모멘텀 로테이션.",
        "mechanism": ["TLT·HYG·EMB·IEF·LQD의 6개월 모멘텀 상위 3종 선택.",
                      "양(+)인 것만 동일가중, 전부 음이면 현금(BIL)."],
        "rationale": "금리·신용 사이클에 따라 우위 채권 섹터가 바뀌므로 모멘텀으로 추종.",
        "regime_note": "금리 추세가 분명한 국면에 유리. 금리 급변동 구간에 취약.",
        "params": {"룩백": "6개월", "유니버스": "채권 5종", "리밸런스": "월간"},
        "references": [_ref("Gary Antonacci", "2014", "Dual Momentum Investing (채권 적용)", "McGraw-Hill")],
    },
    # ── 리스크/최적화 9 ──
    "equal_weight": {
        "concept": "모든 자산을 동일 비중으로 보유하는 1/N 나이브 분산 — 최적화 전략의 벤치마크.",
        "mechanism": ["유니버스 N개 자산을 각 100/N% 보유.", "정기 리밸런스로 동일가중 복원."],
        "rationale": "추정오차가 없는 단순 규칙. DeMiguel(2009)은 1/N이 표본외에서 다수 최적화를 이기기 어렵다고 보고.",
        "regime_note": "특정 국면 최적화 없음 — 비교 기준선. 분산 효과가 살아있는 정상 국면에 무난.",
        "params": {"비중": "1/N", "유니버스": "크로스에셋 8종", "리밸런스": "정기"},
        "references": [_ref("DeMiguel, Garlappi & Uppal", "2009", "Optimal Versus Naive Diversification", "Review of Financial Studies")],
    },
    "risk_parity": {
        "concept": "각 자산의 리스크 기여를 동일하게 맞추는 리스크 패리티 — Bridgewater All Weather의 사상.",
        "mechanism": ["일간 수익률로 공분산 추정.", "각 자산의 한계 리스크 기여가 같아지도록 반복(risk-budgeting)으로 비중 산출.",
                      "변동성 낮은 자산(채권)에 더 큰 비중이 배분됨."],
        "rationale": "시가총액·금액이 아니라 '리스크'를 균등 배분 → 소수 고변동 자산의 위험 독식을 방지, 진정한 분산.",
        "regime_note": "분산이 작동하는 정상 국면에 강함. 전 자산 동반 하락(상관 1 수렴) 시 약화.",
        "params": {"추정": "일간 공분산", "방식": "동일 리스크 기여(ERC)", "리밸런스": "월간"},
        "references": [_ref("Edward Qian", "2005", "Risk Parity Portfolios", "PanAgora"),
                       _ref("Ray Dalio (Bridgewater)", "1996", "All Weather", "")],
    },
    "hrp": {
        "concept": "상관 계층 클러스터링 + 재귀이분으로 행렬역산 없이 견고한 분산을 만드는 계층적 리스크 패리티.",
        "mechanism": ["상관행렬을 거리로 변환해 계층 클러스터링(자산을 닮은 것끼리 묶음).",
                      "유사 자산을 인접 배치(quasi-diagonalization) 후 재귀이분으로 역분산 비중 배분."],
        "rationale": "공분산 역행렬의 불안정성(추정오차 증폭)을 피해 표본외 성과가 우월(López de Prado 2016).",
        "regime_note": "추정오차에 강건 — 자산 수가 많거나 공분산이 불안정할 때 특히 유리.",
        "params": {"클러스터": "single linkage", "배분": "재귀이분 역분산", "리밸런스": "월간"},
        "references": [_ref("Marcos López de Prado", "2016", "Building Diversified Portfolios that Outperform Out of Sample", "J. of Portfolio Management")],
    },
    "min_var": {
        "concept": "포트폴리오 전체 분산(변동성)을 최소화하는 최소분산 포트폴리오.",
        "mechanism": ["수축추정(Ledoit-Wolf) 공분산으로 long-only·합1 제약 하에 wᵀΣw 최소화(SLSQP)."],
        "rationale": "저변동성 이상현상 — 변동성 낮은 자산이 위험대비 더 나은 성과를 내는 경향을 활용.",
        "regime_note": "방어적 — 약세·고변동 국면에 상대적으로 강함. 강세장에선 상승 추종이 약함.",
        "params": {"추정": "Ledoit-Wolf 수축", "목적": "분산 최소", "리밸런스": "월간"},
        "references": [_ref("Clarke, de Silva & Thorley", "2006", "Minimum-Variance Portfolios in the U.S. Equity Market", "J. of Portfolio Management"),
                       _ref("Harry Markowitz", "1952", "Portfolio Selection", "J. of Finance")],
    },
    "max_div": {
        "concept": "분산비율(가중평균 변동성 / 포트 변동성)을 최대화하는 최대분산 — TOBAM의 사상.",
        "mechanism": ["수축 공분산으로 분산비율 DR=(wᵀσ)/√(wᵀΣw)을 최대화(long-only, SLSQP)."],
        "rationale": "상관이 낮은 자산에 비중을 실어 분산 효과를 극대화 — '분산을 명시적 목표로' 삼는다.",
        "regime_note": "분산이 작동하는 국면에 효과적. 전 자산 동조화 시 분산비율이 낮아져 효과↓.",
        "params": {"목적": "분산비율 최대", "추정": "Ledoit-Wolf", "리밸런스": "월간"},
        "references": [_ref("Choueifaty & Coignard", "2008", "Toward Maximum Diversification", "J. of Portfolio Management (TOBAM)")],
    },
    "max_sharpe": {
        "concept": "기대수익/위험 비율(샤프)을 최대화하는 탄젠시 포트폴리오 — Markowitz 평균-분산의 정점.",
        "mechanism": ["트레일링 평균수익 μ와 수축 공분산 Σ로 (wᵀμ)/√(wᵀΣw) 최대화(long-only).",
                      "수축추정으로 코너 솔루션 쏠림을 완화."],
        "rationale": "이론적으로 위험대비 최적 — 단, 기대수익 추정오차에 민감해 수축·제약으로 보정 필수.",
        "regime_note": "추세·수익 추정이 안정적인 국면에 유리. 추정오차가 큰 전환기엔 불안정.",
        "params": {"목적": "샤프 최대(탄젠시)", "추정": "Ledoit-Wolf + 트레일링 μ", "리밸런스": "월간"},
        "references": [_ref("Harry Markowitz", "1952", "Portfolio Selection", "J. of Finance")],
    },
    "black_litterman": {
        "concept": "시장균형 기대수익에 투자자 '뷰'를 베이지안으로 결합하는 블랙-리터만 — 여기선 매크로 국면을 뷰로 주입.",
        "mechanism": ["시장 비중에서 역산한 균형수익(prior)을 기준선으로.",
                      "regime_analyzer의 국면 틸트(성장주·채권·원자재 등 ++/--)를 뷰로 변환해 결합.",
                      "사후 기대수익으로 최적 비중 산출."],
        "rationale": "순수 평균-분산의 극단적·불안정한 해를 시장균형 anchor로 완화하고, 매크로 견해를 체계적으로 반영.",
        "regime_note": "★현재 국면이 바뀌면 뷰가 바뀌어 배분이 따라 움직임 — 콕핏 국면 분석과 직접 연동.",
        "params": {"prior": "시장균형(역최적화)", "뷰": "regime 국면 틸트", "리밸런스": "월간"},
        "references": [_ref("Fischer Black & Robert Litterman", "1992", "Global Portfolio Optimization", "Financial Analysts Journal")],
    },
    "managed_futures": {
        "concept": "자산별 추세를 변동성으로 스케일링해 추종하는 시계열 모멘텀(매니지드 퓨처스/CTA) — long-flat 버전.",
        "mechanism": ["각 자산의 12개월 추세가 양(+)이면 보유, 음(−)이면 현금(여기선 숏 대신 회피).",
                      "보유 자산은 역변동성으로 비중 스케일링(저변동 자산에 더 큰 비중)."],
        "rationale": "시계열 모멘텀은 자산군 전반에서 검증된 강건한 프리미엄(Moskowitz 2012). 변동성 타깃으로 위험 균질화.",
        "regime_note": "추세가 분명한 국면(인플레·위기 추세)에 'crisis alpha'. 급반전엔 약함. 2022 인플레서 CTA 대활약.",
        "params": {"신호": "12개월 시계열 추세", "스케일": "역변동성", "리밸런스": "월간"},
        "references": [_ref("Moskowitz, Ooi & Pedersen", "2012", "Time Series Momentum", "J. of Financial Economics")],
    },
    "kelly": {
        "concept": "장기 자산 성장률(로그효용)을 최대화하는 켈리 기준 — 성장최적 비중.",
        "mechanism": ["기대수익 μ와 공분산 Σ로 성장최적 방향 Σ⁻¹μ 산출.",
                      "long-only로 음수 클립·정규화(완전투자형). 풀켈리의 과대레버리지는 제약으로 완화."],
        "rationale": "복리 성장률을 이론적으로 극대화하는 비중. 추정오차에 민감해 보수적(하프켈리·long-only) 적용이 표준.",
        "regime_note": "수익 추정이 안정적인 추세 국면에 공격적. 추정 불안정기엔 변동성↑ 주의.",
        "params": {"목적": "로그성장 최대(Σ⁻¹μ)", "제약": "long-only 정규화", "리밸런스": "월간"},
        "references": [_ref("John Kelly", "1956", "A New Interpretation of Information Rate", "Bell System Technical J."),
                       _ref("Edward Thorp", "2006", "The Kelly Capital Growth Criterion", "")],
    },
}


def get_profile(sid: str) -> dict | None:
    return PROFILES.get(sid)


# ── 동적 전략 백테스트 (★매월 전략 로직 재평가·리밸런스·복리 — buy&hold 아님★) ──
_BACKTEST_MONTHS = 48


def _curve_summary(vals: list[float], port: list[float], months: int) -> dict:
    today = datetime.now()
    n = len(vals)
    curve = [{"t": (today - timedelta(days=(n - 1 - i) * 30)).strftime("%y.%m"), "v": round(v, 1)}
             for i, v in enumerate(vals)]
    total = vals[-1] / vals[0] - 1 if vals[0] > 0 else 0.0
    years = months / 12.0
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1 if (years > 0 and vals[0] > 0) else 0.0
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak)
    mean = sum(port) / len(port) if port else 0.0
    var = sum((x - mean) ** 2 for x in port) / len(port) if port else 0.0
    vol = math.sqrt(var) * math.sqrt(12)
    recent12 = (vals[-1] / vals[-13] - 1) if len(vals) >= 13 else None
    return {"curve": curve, "summary": {
        "total_return_pct": round(total * 100, 1), "cagr_pct": round(cagr * 100, 1),
        "mdd_pct": round(mdd * 100, 1), "vol_pct": round(vol * 100, 1),
        "recent_12m_pct": round(recent12 * 100, 1) if recent12 is not None else None,
    }}


def backtest_strategy(sid: str, mk: str, months: int = _BACKTEST_MONTHS) -> dict:
    """동적 백테스트 — 매월 그 시점 데이터로 전략 비중을 재계산(as_of)하고 다음 달 수익을 복리.

    전략의 실제 리밸런싱(모멘텀 로테이션·타이밍 전환)을 재현 — 현재 비중 buy&hold가 아님.
    각 월 m: as_of(m)로 m개월 전 시점 비중 산출 → 그 비중으로 m→m-1 실현수익 적립.
    """
    from src.data import etf_prices
    from src.data.etf_prices import US_UNIVERSE, monthly_closes
    from src.engine.tactical_allocations import ALL_STRATEGIES
    entry = next((s for s in ALL_STRATEGIES if s[0] == sid), None)
    if not entry:
        return {"curve": [], "summary": {}}
    fn = entry[4]
    mk = "kr" if mk == "kr" else "us"
    # 유니버스 월말 종가(오프셋 없음) 선계산 → 실현수익 조회용
    closes: dict[str, list[float]] = {}
    for tk in US_UNIVERSE:
        c = monthly_closes(tk, mk, months + 3)
        if len(c) >= 2:
            closes[tk] = c
    if not closes:
        return {"curve": [], "summary": {}}
    avail = min(len(c) for c in closes.values())
    span = min(months, avail - 1)
    if span < 6:
        return {"curve": [], "summary": {}}
    vals, port = [100.0], []
    for m in range(span, 0, -1):
        with etf_prices.as_of(m):  # m개월 전 시점 비중
            try:
                w = fn(mk)
            except Exception:
                w = {"BIL": 100.0}
        wsum = sum(v for v in w.values() if v > 0) or 1.0
        pr = 0.0
        for tk, wt in w.items():
            if wt <= 0:
                continue
            c = closes.get(tk)
            if c and len(c) > m and c[-m - 1] > 0:  # m→m-1 실현수익
                pr += (wt / wsum) * (c[-m] / c[-m - 1] - 1.0)
        vals.append(vals[-1] * (1 + pr))
        port.append(pr)
    return _curve_summary(vals, port, span)


# ── 국면 적합도 (recommender 아키타입 × 국면) ────────────────────────────────────
def _regime_fit(sid: str) -> list[dict]:
    from src.engine.macro_recommender import _ARCHETYPE, _FIT, _QUAD_KR
    arch = _ARCHETYPE.get(sid, "diversified")
    out = []
    for quad in ("Goldilocks", "Reflation", "Stagflation", "Disinflation"):  # 명명 통일(regime_axes)
        fit = _FIT.get(quad, {}).get(arch, 0.5)
        out.append({"quadrant": quad, "quadrant_kr": _QUAD_KR.get(quad, quad), "fit": round(fit, 2)})
    return out


# ── 라이브 보유 (단일 전략만 평가 — 22개 전체 평가 회피) ──────────────────────────
def _strategy_holdings(sid: str, mk: str):
    from src.data.etf_prices import US_UNIVERSE, resolve
    from src.engine.tactical_allocations import ALL_STRATEGIES
    entry = next((s for s in ALL_STRATEGIES if s[0] == sid), None)
    if not entry:
        return None, None, None
    _id, name, _desc, family, fn = entry
    try:
        weights = fn(mk)
    except Exception:
        weights = {"BIL": 100.0}
    holdings = [{"ticker": resolve(t, mk)[0], "label": resolve(t, mk)[1],
                 "us_ticker": t, "us_label": US_UNIVERSE.get(t, t), "weight": w}
                for t, w in sorted(weights.items(), key=lambda x: -x[1])]
    return name, family, holdings


_ARCH_KR = {"aggressive": "공격", "defensive": "방어", "income": "인컴", "diversified": "분산"}


def build_detail(sid: str, market: str = "kr") -> dict | None:
    """전략 상세 = 정적 프로파일 + 라이브 보유·시그널 + 국면적합도 + 과거성과 곡선."""
    prof = get_profile(sid)
    if prof is None:
        return None
    mk = "kr" if market == "kr" else "us"
    name, family, holdings = _strategy_holdings(sid, mk)
    if holdings is None:
        return None
    from src.engine.macro_recommender import _ARCHETYPE
    from src.engine.tactical_allocations import _signal
    weights = {h["us_ticker"]: h["weight"] for h in holdings}
    arch = _ARCHETYPE.get(sid, "diversified")
    perf = backtest_strategy(sid, mk)
    return {
        "id": sid, "name": name, "family": family,
        "signal": _signal(weights), "archetype": arch, "archetype_kr": _ARCH_KR.get(arch, arch),
        "holdings": holdings, "profile": prof,
        "regime_fit": _regime_fit(sid), "perf": perf,
        "recent_return_12m": perf["summary"].get("recent_12m_pct"),
        "sources": {"prices": bool(os.getenv("KIS_APP_KEY"))},
    }
