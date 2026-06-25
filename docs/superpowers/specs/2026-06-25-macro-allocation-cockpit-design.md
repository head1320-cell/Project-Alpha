# Macro Allocation Cockpit — 매크로 탭 전면 개편 설계

> Status: DESIGN (brainstorming 산출물) · Date: 2026-06-25 · Branch: claude/keen-thompson-bdk3e8

## Context (왜)
현재 `/macro` 탭은 4분면 레짐 매트릭스 + 금리·환율 스탯 몇 개만 보여준다(`frontend/src/app/macro/page.tsx`).
포트폴리오 수익률의 가장 큰 기여 요인인 **자산배분**과 **마켓타이밍**을 돕는 매크로 인텔리전스 도구로
전면 개편한다. 목표: ① 5개 API(DART·KIS·KRX·ECOS/BOK·FRED)의 실데이터를 **최대 활용**해 수많은 매크로
지표를 전문가급으로 보여주고, ② 그 분석을 기반으로 **현 시점 유리한 자산배분 전략을 추천**한다.
레퍼런스: jasan-calc(13 택티컬 전략 현재 비중), Valley AI(국면·하위요인·사이클·밸류 히트맵),
MacroMicro(지표 차트+해석).

플랫폼은 이미 강한 토대를 보유 — `MacroCollector`(BOK ECOS+FRED 실클라이언트, ~16지표),
`regime_analyzer`(4분면 성장×물가 레짐·stress·yield curve·동적파라미터), `RegimeAdaptiveAllocator`,
백테스터 `asset_alloc`(ETF 바스켓)·`market_timing`. 개편은 **이 엔진들을 연결 + 신규 전략시그널/추천
레이어 + 정교한 프론트엔드**의 결합이다.

사용자 결정: 전략 데이터 = **US ETF ⇄ 국내 ETF 토글**, 추천 = **규칙 + 백테스트 + AI 서술 3종**,
범위 = **Layer 1~4 전체 한 번에**, UI/UX = **최대한 세련·전문·기술적**, **추가 탭/창 허용**, 프론트엔드 기능 최대 활용.

## Goals / Non-goals
- Goal: 5-API 실데이터 기반 매크로 대시보드 + 국면/사이클/밸류 분석 + 13전략 시그널 + 현시점 추천(→ 백테스터 연결).
- Goal: Bloomberg/Valley-AI급 정보밀도·인터랙션의 터미널 UI(기존 "Institutional Terminal" 디자인 계승·격상).
- Non-goal: 유료 컨센서스 데이터, HFT 신호. 키 없는 환경의 실값(데이터 없으면 명확 라벨·건너뜀).

## 정보 구조 — 6개 서브탭 코크핏
상단 **고정 레짐 배너**(현재 국면·사이클·stress·추천 헤드라인) + 좌측 6 서브탭. ⌘K 지표 퀵점프.

```
[고정 배너] Stagflation · 사이클 둔화 · Stress 62 · 👉 추천: 영구포트(방어) 적합도 78
─────────────────────────────────────────────────────────────────────────────
01 Overview    핵심 게이지(성장·물가·금리·유동성·심리) 5게이지 + 추천카드 + 한미 미니맵
02 Indicators  Layer1: 6테마 지표 대시보드(한미 오버레이·sparkline·z-score 히트맵·해석)
03 Regime      Layer2: 4분면 궤적 + 경기사이클 시계 + yield curve + stress 게이지
04 Valuation   Layer2: 자산군 밸류 히트맵 + 한국 시장/섹터 밸류(DART+KRX 전종목)
05 Strategies  Layer3: 13전략 현재비중 보드(US⇄KR 토글) + 모멘텀 히트맵 + [백테스트→]
06 Recommend   Layer4: 규칙+백테스트+AI 추천카드 + 근거 + [백테스터 이식]
```

## 5-API 데이터 매핑 (최대 활용 — 어떤 셀도 비우지 않기)
| 영역 | FRED(미) | ECOS/BOK(한) | KRX | DART | KIS |
|---|---|---|---|---|---|
| 성장 | GDP·PMI·산업생산·고용·소매 | 경기선행·산업생산·수출입 | 지수 장기 | — | 실시간 지수 |
| 물가 | CPI/PCE·기대인플레·유가 | CPI·수입물가 | — | — | — |
| 금리·통화 | FEDFUNDS·DGS10/2/3M·실질금리·DXY | 기준금리·국고채·원달러·M2 | — | — | 환율틱 |
| 유동성·신용 | M2·하이일드(BAML)·금융여건 | M2·신용 | — | — | — |
| 수급·심리 | VIX·T10YIE | — | 투자자 수급(과거) | — | 외국인/기관 수급(#3) |
| 밸류에이션 | 자산군 가격 z | 금리(채권) | 전종목 시총·지수 | **전종목 PER/PBR/배당** | 실시간 |
| 전략 시그널 | (자산군 가격) | — | 국내 ETF·지수 | — | **해외주식 US ETF** |

핵심: **한국 시장/섹터 밸류에이션 히트맵**은 DART 전종목 재무 + KRX 시총으로 시장 PER/PBR/배당
분포의 z-score를 산출(전종목 데이터 최대 활용). 수급 히트맵은 #3 investor_flows(KIS/KRX).

## Layer별 상세 + 시각화

### Layer 1 · Indicators (지표 대시보드)
- 6테마(성장/물가/금리·통화/유동성·신용/수급·심리/한국) 카드 그리드. 각 지표:
  **라인+한미 오버레이 차트** · **미니 sparkline** · **추세 화살표/Δ배지** · **MacroMicro식 해석 한 줄** ·
  **z-score(과열빨강↔침체파랑) 셀**.
- 상단 **지표×시점 z-score 히트맵**(Valley AI식) — 한눈에 과열/침체 스캔.
- 지표 클릭 → **드릴다운 창**(전체 시계열·역사 백분위·관련 지표·해석·데이터출처/신선도 배지).
- 데이터: FRED+ECOS 실연동. 키 없으면 "데이터 없음" 셀(합성 금지).

### Layer 2 · Regime & Valuation
- **4분면 레짐 scatter + 6개월 궤적**(성장축×물가축, 현재 점 + 화살표 트레일) — regime_analyzer.
- **경기 사이클 시계** 게이지(확장→둔화→수축→회복) + **장단기금리차 + 침체확률** + **Stress 게이지**.
- **Yield curve 차트**(3M~30Y, 역전 음영).
- **자산군 밸류 히트맵**(주식·채권·금·원자재·리츠 z-score).
- **한국 시장/섹터 밸류 히트맵**(시장 PER/PBR/배당 분포, 11섹터 grid) ← DART+KRX 전종목.

### Layer 3 · Strategies (전략 시그널 보드)
- 13+ 전략(전통/종합/가속 듀얼모멘텀·영구포트·LAA·RAA·GTAA·PAA·VAA·FAA·AAA·DAA·DGA·채권동적)의
  **현재 보유자산·비중** 실시간 룰 계산. **모멘텀 시그널** + **직전 변경**.
- **[글로벌(US ETF) ⇄ 국내(KODEX 등)] 토글** — US=KIS 해외주식, 국내=KRX/KIS, 매핑 테이블.
- 시각화: 전략별 **배분 도넛/스택바** · **모멘텀 강도 히트맵**(전략×자산) · **변경 타임라인**.
- 각 행 **[이 전략 백테스트 →]** → 백테스터 asset_alloc 프리필.

### Layer 4 · Recommendation (3종 종합)
- **규칙**: 국면·사이클·밸류 → 전략 적합도 스코어(RegimeAdaptiveAllocator + 국면→전략 매핑).
- **백테스트**: 유사/최근 국면에서 각 전략 실백테스트 성과(우리 엔진).
- **AI 서술**: Claude로 근거 설명(ANTHROPIC_API_KEY, 없으면 규칙 요약 폴백).
- 시각화: **추천 카드**(전략명 + 비중 도넛 + 적합도 게이지 + 근거 불릿) + **[백테스터로 이식]**(asset_alloc/market_timing).

## UI/UX — "Institutional Terminal" 격상 (정교·전문·기술)
- 디자인 토큰 계승(Geist+JetBrains Mono, accent #1200ff, ink #111, radius 2px, surface #fafafa). 숫자=mono.
- **정보밀도 높은 멀티페인 그리드** + 코너마크/그리드 오버레이(기존 셸). 다크 헤더 배너.
- **인터랙션**: 차트 hover 크로스헤어·툴팁, brush 줌, 비교 오버레이; 히트맵 셀 hover 상세 + 클릭 드릴다운 창;
  ⌘K 지표 퀵점프(기존 Quick Search 연계); 서브탭 전환 부드러운 전이(기존 모션 톤).
- **신선도/출처 배지**: 각 패널에 데이터원(FRED/ECOS/KRX/DART/KIS) + 갱신시각 + 실/미연동 배지(정직).
- **저장된 뷰**: 관심 지표 워치/레이아웃 저장(localStorage, 기존 프리셋 패턴).
- 반응형(1400/1100/820). 접근성(키보드 포커스 링, 색맹 안전 z-score 팔레트).
- 차트 구현: 경량 SVG 자체 컴포넌트 + 필요한 곳만 Recharts. **히트맵 그리드**는 risk-tools 패턴 재사용·일반화.

## 컴포넌트 (격리·단일책임)
프론트 `frontend/src/components/macro/`:
- `MacroCockpit.tsx`(셸+서브탭+배너), `parts/`(IndicatorCard, ZHeatmap, RegimeQuadrant, CycleClock,
  YieldCurve, Gauge, ValuationHeatmap, StrategyBoard, AllocDonut, RecommendCard, DrillDownModal).
- `frontend/src/lib/macroData.ts`(전 패널 병렬 로더 — companyData.ts 패턴), 타입 `macroTypes.ts`.
백엔드 `src/api/macro_routes.py` 확장 + 신규:
- `GET /macro/dashboard`(6테마 지표 스냅샷+시계열+z-score) — MacroCollector 확장.
- `GET /macro/valuation`(자산군 + 한국 시장/섹터 밸류) — DART/KRX 전종목.
- `GET /macro/strategies?market=us|kr`(13전략 현재비중) — 신규 `src/engine/tactical_allocations.py`.
- `GET /macro/recommend`(3종 종합) — `src/engine/macro_recommender.py`(RegimeAdaptiveAllocator+백테스트+narrative).
신규 데이터: `src/data/etf_prices.py`(US=KIS 해외주식/yfinance, KR=KRX/KIS — 토글 소스).

## 데이터/정직성
- 전부 실데이터 게이트(키): FRED/ECOS 매크로, DART/KRX 밸류, KIS/KRX 전략. 키 없으면 패널별 "미연동" 라벨(합성 금지).
- US ETF: KIS 해외주식 1순위, yfinance 폴백(클라우드 429 주의 — 캐시·일배치).

## 검증
1. 백엔드: 신규 엔드포인트 4종이 mock/키없음에서 graceful(빈/라벨) 반환·크래시 0. `tactical_allocations` 룰 단위테스트(각 전략 현재비중 산출, 합=100). `macro_recommender` 적합도 스코어 단위테스트. ruff·pytest 그린(539+).
2. 프론트: `npx tsc --noEmit` 0 · `npx next build` (페이지 수 유지) · 라이브: 6서브탭 렌더·히트맵·드릴다운·토글·추천카드.
3. 정직성: 키 없는 샌드박스에서 "미연동" 라벨 확인; 실값은 GCP(키)에서.

## 구현 순서(전체 한 번에 — 단, 안전 커밋 단위)
1) 백엔드 엔진/엔드포인트(tactical_allocations·macro_recommender·dashboard·valuation) + 테스트.
2) etf_prices 데이터 소스(US/KR 토글).
3) 프론트 MacroCockpit 셸 + 6 서브탭 + 공통 차트/히트맵 컴포넌트.
4) 각 Layer 패널 + 드릴다운 + 추천 + 백테스터 연결.
5) 검증·커밋·푸시(브랜치 claude/keen-thompson-bdk3e8).

## 정직한 한계
- 샌드박스는 키/네트워크 없어 실 매크로 값·US ETF는 GCP에서 실측 — 여기선 로직·게이트·빌드·라벨 검증.
- 미래 실적/컨센서스는 유료라 제외(추천은 매크로 국면 기반).
- yfinance는 클라우드 IP 429 가능 — KIS 해외주식 우선, 캐시/일배치로 완화.

## 구현 진행 (Implementation Progress) — ★압축 후 이어가기용★
브랜치 `claude/keen-thompson-bdk3e8`. 검증/커밋 패턴: 단계마다 `python -m ruff check <files>` +
`KIS_USE_MOCK=1 python -m pytest tests/ -q`(기준 544 passed/10 skipped) + 프론트는
`cd frontend && npx tsc --noEmit`(0) + `npx next build`. 커밋 트레일러
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`.
모델ID 커밋 금지. 푸시 `git push -u origin claude/keen-thompson-bdk3e8`. 결정: US⇄KR 토글·추천3종·전체범위·정교한 터미널 UI.

✅ 완료(커밋):
- Phase 1 `23e9e7b`: `src/data/etf_prices.py`(US 24 + KR 매핑 US_TO_KR, monthly_closes/daily_closes via load_ohlcv_unified) ·
  `src/engine/tactical_allocations.py`(헬퍼 _ret/_score_13612/_accel/_above_ma_m/_above_ma_d + 13전략 s_* + `compute_strategies(market)`) ·
  `GET /macro/strategies?market=us|kr`(macro_routes.py) · `tests/test_tactical_allocations.py`.
- Phase 2 `37e2d75`: `src/engine/macro_recommender.py`(`recommend(market)` → regime+13랭킹+top+narrative, _ARCHETYPE/_FIT 국면×아키타입) ·
  `GET /macro/recommend?market=us|kr`. narrative는 ANTHROPIC_API_KEY 있으면 Claude(claude_client) 없으면 규칙.

⏳ 남음:
- **Phase 3 (백엔드 엔드포인트)** — macro_routes.py에 추가:
  · `GET /macro/dashboard?market=` : `MacroCollector.get_default().collect_all()`의 series를 6테마(성장/물가/금리·통화/유동성·신용/수급·심리/한국)로 그룹화 + 각 지표 최근값·Δ·z-score·sparkline(최근 N) 반환. (BOK_INDICATORS/FRED_INDICATORS 메타 활용, macro_collector.py:139/212.)
  · `GET /macro/valuation` : 자산군(주식/채권/금/원자재/리츠) z-score(가격/금리) + 한국 시장·섹터 밸류(시장 PER/PBR/배당 분포 + 11섹터) — `snapshot_db.sample_factors()` 또는 fundamentals_store 집계 + genport_themes 섹터.
- **Phase 4 (프론트 — 대규모)**:
  · `frontend/src/lib/macroData.ts`(병렬 로더, companyData.ts 패턴) + `frontend/src/components/macro/macroTypes.ts`.
  · `screenerApi.ts`(analysisApi)에 macro API 추가: macroStrategies(market)·macroRecommend(market)·macroDashboard(market)·macroValuation(). 이미 macroRegime() 있음.
  · `frontend/src/components/macro/MacroCockpit.tsx` — 6 서브탭(01 Overview·02 Indicators·03 Regime·04 Valuation·05 Strategies·06 Recommend) + 고정 레짐 배너.
  · `parts/` 컴포넌트: IndicatorCard·ZHeatmap(risk-tools 히트맵 패턴 재사용)·RegimeQuadrant(scatter+궤적)·CycleClock·YieldCurve·Gauge·ValuationHeatmap·StrategyBoard(US⇄KR 토글, [백테스트→])·AllocDonut·RecommendCard·DrillDownModal.
  · `frontend/src/app/macro/page.tsx`를 MacroCockpit 렌더로 교체(현재 4분면만). 디자인 토큰: globals.css "Institutional Terminal"(Geist+JetBrains Mono, accent #1200ff, radius 2px), 숫자=mono.
  · 백테스터 이식: `backtestBridgeApi.screenToBacktest`의 `asset_alloc`(basket) / `market_timing` 필드에 추천 배분 프리필 → router.push("/backtest").
- 검증: tsc 0 · next build(현재 16페이지) · 라이브 6서브탭. 정직성: 키 없으면 패널별 "미연동" 라벨(합성 금지).
