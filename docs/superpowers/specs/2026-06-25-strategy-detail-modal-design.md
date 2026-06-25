# 전략 상세 모달 — 22전략 큐레이션 설명 + 레퍼런스 + 시각화 + AI 심층분석

> 매크로 콕핏 05 Strategies의 전략 카드를 클릭하면 모달이 열려 해당 전략의 개념·작동방식·
> 경제적 근거·국면 적합도·현재 보유·과거 성과 곡선·학술 레퍼런스·AI 심층분석을 보여준다.
> 백엔드 큐레이션 카탈로그(단일 소스)가 라이브 데이터와 병합되어 한 번의 호출로 제공.

날짜: 2026-06-25 · 브랜치: `claude/keen-thompson-bdk3e8`

---

## 1. 배경 / 목표
05 Strategies 탭의 22개 카드는 이름·시그널·한 줄 설명·보유만 보여준다. 사용자는 각 전략을
**깊이 이해**하고 싶다 — 무엇이고, 어떻게 작동하며, 왜 통하고, 언제 유리하며, 누가 만들었는지.
카드 클릭 → 풀 상세 모달. 콘텐츠는 백엔드 카탈로그(단일 소스, AI 재사용)에 두고 라이브 데이터와 병합.

## 2. 백엔드

### 2.1 신규 `src/engine/strategy_profiles.py` — 큐레이션 카탈로그
`PROFILES: dict[str, dict]` — 22 전략 id 전부. 각 항목 스키마:
- `concept: str` — 1~2문장 개념.
- `mechanism: list[str]` — 작동 규칙 단계(평이한 한국어).
- `rationale: str` — 경제적 근거(왜 통하는가).
- `regime_note: str` — 유리/불리 국면.
- `params: dict` — 핵심 파라미터(룩백·유니버스·리밸런스 주기).
- `references: list[{authors, year, title, venue}]` — 학술/실무 출처(≥1).
- `get_profile(sid) -> dict | None`.

레퍼런스(정확성 확인됨):
- classic_dm: Antonacci (2014), *Dual Momentum Investing*, McGraw-Hill.
- composite_dm: Antonacci (2012), "Risk Premia Harvesting Through Dual Momentum," SSRN.
- accel_dm: EngineeredPortfolio (2018), "Accelerating Dual Momentum" (실무).
- permanent: Browne (1999), *Fail-Safe Investing* (Permanent Portfolio).
- laa: Philosophical Economics (2016), "Growth-Trend Timing" (LAA의 경기 스위치 근거).
- raa: Gray & Vogel (2015), *DIY Financial Advisor* — Robust Asset Allocation.
- gtaa: Faber (2007), "A Quantitative Approach to Tactical Asset Allocation," J. Wealth Mgmt.
- paa: Keller & Keuning (2016), "Protective Asset Allocation (PAA)," SSRN.
- vaa: Keller & Keuning (2017), "Breadth Momentum and Vigilant Asset Allocation (VAA)," SSRN.
- faa: Keller & van Putten (2012), "Generalized Momentum and Flexible Asset Allocation (FAA)," SSRN.
- aaa: Butler, Philbrick & Gordillo (2012), "Adaptive Asset Allocation," SSRN.
- daa: Keller & Keuning (2018), "Defensive Asset Allocation (DAA)," SSRN.
- bond_dynamic: 채권 듀얼모멘텀 로테이션 (Antonacci 듀얼모멘텀의 채권 적용).
- equal_weight: DeMiguel, Garlappi & Uppal (2009), "Optimal Versus Naive Diversification," RFS.
- risk_parity: Qian (2005), "Risk Parity Portfolios," PanAgora; Bridgewater *All Weather* (Dalio).
- hrp: López de Prado (2016), "Building Diversified Portfolios that Outperform Out of Sample," JPM.
- min_var: Clarke, de Silva & Thorley (2006), "Minimum-Variance Portfolios," JPM; Markowitz (1952).
- max_div: Choueifaty & Coignard (2008), "Toward Maximum Diversification," JPM (TOBAM).
- max_sharpe: Markowitz (1952), "Portfolio Selection," J. Finance (탄젠시).
- black_litterman: Black & Litterman (1992), "Global Portfolio Optimization," FAJ.
- managed_futures: Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum," JFE.
- kelly: Kelly (1956), Bell System Tech. J.; Thorp (2006), "The Kelly Capital Growth Criterion."

### 2.2 과거 성과 곡선 — `_perf_curve(holdings, mk)` (★strategy_profiles.py에 위치, 자기완결★)
현재 비중을 과거 ETF 월수익에 적용(월 리밸런스 가정) → 자산곡선:
- 각 holding의 `monthly_closes`(~60M) → 월수익. 포트 월수익 = Σ(weight×assetReturn).
- 누적곱 → equity 곡선(start=100), `[{t, v}]`.
- 요약: total_return_pct, cagr_pct, mdd_pct, vol_pct, recent_12m_pct.
- ★현재 비중 고정 buy&hold — 전략의 동적 리밸런싱 재현 아님(그건 백테스터 이식). "현재 배분 기준" 라벨.

### 2.3 국면 적합도 — `_regime_fit(sid)`
`macro_recommender._ARCHETYPE[sid]` → archetype → `_FIT[quadrant][archetype]`를 4국면에 대해 추출
→ `[{quadrant, quadrant_kr, fit}]` (0~1). 현재 국면 강조용으로 현재 quadrant도 포함.

### 2.4 엔드포인트 (`src/api/macro_routes.py`)
- `GET /macro/strategy/{sid}?market=us|kr` — **모달 열 때(싸다)**. 병합 반환:
  `{id, name, family, signal, archetype_kr, holdings, profile{concept,mechanism,rationale,regime_note,params,references},
    regime_fit[], perf{curve, summary}, recent_return_12m, sources}`. 알 수 없는 sid → 404.
- `POST /macro/strategy/{sid}/ai?market=` — **버튼 클릭 시만**. 프로파일+현재 국면+보유 컨텍스트로 Claude 생성
  (기존 `src.services.narrative.claude_client` 재사용). 키 없으면 `{error}` 친절 폴백. `{content, tokens, cost_krw, cached, error}`.

병합 소스: `compute_strategies(market)`에서 sid의 holdings/signal/family, `strategy_profiles.get_profile(sid)`,
`_regime_fit`, `_perf_curve`. 라이브 국면은 `regime_analyzer`.

## 3. 프론트엔드

### 3.1 `screenerApi.ts` + `macroData.ts`
- 타입: `StrategyReference`, `StrategyProfile`, `RegimeFit`, `PerfSummary`, `StrategyDetail`, `StrategyAI`.
- analysisApi: `macroStrategyDetail(sid, market)`, `macroStrategyAI(sid, market)`.
- macroData: `loadStrategyDetail(sid, mk)`, `loadStrategyAI(sid, mk)` (둘 다 catch→null).

### 3.2 신규 `components/macro/StrategyModal.tsx`
큰 모달(스크롤). DrillDownModal 셸 패턴. 섹션:
1. 헤더 — 이름 · family 배지 · SignalBadge · 아키타입 · 닫기(X).
2. 개념 → 작동 방식(번호 단계 리스트) → 경제적 근거 → 유리/불리 국면.
3. 국면 적합도 — 4분면 막대(현재 국면 하이라이트).
4. 현재 보유 — HoldingsDonut(재사용) + 비중 표.
5. 과거 성과 — recharts AreaChart(자산곡선 start=100) + 요약 카드(총수익·CAGR·MDD·변동성·최근12M) + "현재 배분 기준" 배지.
6. 레퍼런스 — 저자·연도·제목·게재처 리스트.
7. AI 심층분석 — 버튼(생성 전 안내) → 클릭 시 `loadStrategyAI` → 본문 + 토큰·비용·캐시 표기(Company AI 패턴).
로딩: detail 로드 전 스피너. 데이터 없으면 "불러오기 실패".

### 3.3 `MacroCockpit.tsx` 연결
- `StrategiesTab`/`StrategyCard`: 카드 본문 클릭 → `onOpen(sid)` (기존 [백테스트] 버튼은 stopPropagation으로 유지).
- MacroCockpit: `const [stratModal, setStratModal] = useState<{sid; detail; loading} | null>(null)` +
  열 때 `loadStrategyDetail(sid, market)`; `<StrategyModal>` 렌더. 시장 토글 반영(현재 market 전달).

## 4. 검증 (TDD)
### 4.1 단위 (`tests/test_strategy_profiles.py` 신규, red→green)
- `PROFILES`: 22 id == ALL_STRATEGIES id 집합과 일치. 각 concept/mechanism(≥1)/rationale/references(≥1) 완비.
- `_perf_curve`: 곡선 길이>0, start≈100, summary 수치 유한, 빈 holdings → 빈 곡선.
- `_regime_fit`: 4국면, fit ∈ [0,1].
- detail 병합(엔드포인트 함수): 22 전부 성공·holdings 존재·profile 존재, 알 수 없는 id → None/404.
- 결정론.
### 4.2 게이트
- `ruff` · `KIS_USE_MOCK=1 pytest`(566 + 신규) · `tsc 0` · `next build`(16/16, /macro).
- 회귀 불변: 기존 8탭·22전략·566 테스트.

## 5. 구현 순서 (안전 커밋 단위)
1. `strategy_profiles.py`(22 카탈로그) + `_perf_curve`/`_regime_fit` + `test_strategy_profiles.py`(TDD) + 엔드포인트 2개. (커밋①)
2. 프론트 `StrategyModal.tsx` + `screenerApi`/`macroData` + 카드 클릭 연결. tsc/build. (커밋②)
3. 검증·푸시. 트레일러 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` +
   `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`. 모델ID 커밋 금지.

## 6. 정직한 한계
- 과거 성과 곡선 = **현재 비중 고정 월리밸런스 buy&hold** — 전략 동적 리밸런싱 풀백테스트 아님(백테스터 탭 이식 사용). 라벨 명시.
- mock 시세에선 곡선·국면 적합도 절대수치 합성(구조·로직 검증) — 실값은 GCP 실시세.
- AI는 ANTHROPIC_API_KEY 있을 때만(없으면 규칙 폴백 안내). 토큰 비용 발생 → 온디맨드.
- 레퍼런스는 큐레이션(정적). 외부 링크는 신뢰 가능한 것만(과장 금지).

## 7. 비범위 (YAGNI)
- 전략별 풀 동적 백테스트(리밸런싱 재현) — 백테스터 탭 이식으로 충분.
- 전략 간 다중 비교 모달 — StrategyComparison(백테스터)과 중복, 제외.
- 레퍼런스 PDF 임베드 — 제목·출처 텍스트로 충분.
