# Platform Evolution — Gap 분석 + 전략 로드맵

## 현재 플랫폼 보유 역량 (Stage 1-13+)

| 영역 | 보유 기능 | 성숙도 |
|---|---|---|
| **시장 데이터** | KRX 가격/거래량, 기술지표 | ★★★☆ |
| **매크로 분석** | 4-Quadrant Regime (SPX/VIX/T10Y2Y/CU/GOLD), Systemic Risk Score | ★★★★ |
| **전략 빌더** | DAG 기반 팩터 그래프, 멀티 전략 레지스트리 | ★★★★ |
| **백테스트** | PIT-safe 일별, 5-Factor Attribution, Counterfactual, Walk-Forward | ★★★★★ |
| **현실 보정** | Market Impact, Cash Yield, Capacity, Buying Power, Regime Adaptive | ★★★★★ |
| **실거래** | KIS API, 5-layer Safety, 3-mode Router, Kill Switch, Audit | ★★★★ |
| **운영** | Reconciler, State Machine, Priority Gateway, Notifier | ★★★★ |

## 밸리AI 보유 기능 (스크린샷 기준)

| 카테고리 | 세부 기능 | 우리 보유 여부 |
|---|---|---|
| **금융시장 현황** | 금융시장 동향, 섹터 히트맵, 기술지표 탐색 | ⚠ 부분 (기술지표만) |
| **프리미엄 뉴스룸** | 실시간 속보, 실시간 내러티브, 프리미엄 뉴스 | ❌ 없음 |
| **거시경제 분석** | 국가경제 분석, 하위 요인 분석, 경제지표 일정, 사이클 분석, 자산군 밸류에이션 | ⚠ 부분 (4-Quadrant만) |
| **퀀트 탐색** | 스크리너, 백테스터 | ⚠ 백테스터만 (스크리너 없음) |
| **투자거장 분석** | 거장 매매, 거장 포트폴리오, 공통 보유종목 | ❌ 없음 |
| **종목 재무분석** | 종목 개요, 재무제표, IR자료실, 실적 및 전망, 내부자 거래, 실적 발표 일정 | ❌ 없음 |
| **종목 가치평가** | 상대가치평가, DDM, RIM, Index DCF, Reverse DCF, Simplified DCF | ❌ 없음 |
| **포트폴리오 관리** | 대시보드, 포트폴리오 분석, 관전 포인트 | ⚠ 부분 (Stage 11) |
| **산업 분석** | 인기 산업 탐색, 밸류체인 | ❌ 없음 |

## 젠포트 보유 기능 (주요)

| 카테고리 | 세부 기능 | 우리 보유 여부 |
|---|---|---|
| **자동매매** | 조건식 기반 자동 거래, 전략 마켓플레이스 | ⚠ (Stage 13은 더 정교하지만 조건식 빌더 없음) |
| **종목 스크리너** | 재무/기술 다중 조건 필터 | ❌ 없음 |
| **시뮬레이션** | 대중적 백테스트 인터페이스 | ✅ 우리가 우수 |
| **커뮤니티** | 전략 공유, 순위 | ❌ 없음 |

---

## 핵심 Gap 5가지 (우선순위 순)

### 🔴 Gap 1: 재무 데이터 + 가치평가 (가장 큰 결함)
**현재:** 가격/거래량 기반 기술적 팩터만 존재
**필요:** DART API 재무제표, PER/PBR/ROE/FCF, RIM/DCF/DDM 가치평가
**영향:** 밸류 팩터 전략이 불가능 → 전략 다양성 제약 → 백테스트 신뢰도 감소
**우선순위:** ★★★★★ (즉시 착수)

### 🔴 Gap 2: 종목 스크리너 (사용성 핵심)
**현재:** 전략 레지스트리에 종목을 수동 입력
**필요:** 재무/기술/매크로 다중 조건 필터링 + 실시간 결과
**영향:** 투자 아이디어 발굴 속도 저하, 사용자 이탈
**우선순위:** ★★★★☆

### 🟡 Gap 3: AI 내러티브 (차별화 핵심)
**현재:** 숫자만 출력
**필요:** Claude API로 "왜 이 결과인가" 자연어 해석, 자동 투자 보고서
**영향:** 밸리AI의 "실시간 내러티브" 대비 열위
**우선순위:** ★★★★☆

### 🟡 Gap 4: 경제지표 확장 (깊이 확보)
**현재:** 5개 매크로 시계열 (SPX/VIX/T10Y2Y/CU/GOLD)
**필요:** 한국 금리/환율/인플레이션, 경제지표 일정, 사이클 분석
**영향:** 국내 시장 적합도 저하
**우선순위:** ★★★☆☆

### 🟢 Gap 5: 산업/섹터 분석 (확장)
**현재:** 없음
**필요:** 섹터 히트맵, 밸류체인, 산업별 비교
**영향:** 탑다운 접근 불가
**우선순위:** ★★☆☆☆

---

## 전략 로드맵 — 5단계

### Phase 1: Fundamental Foundation (이번 작업) ⚡
**기간:** 즉시
**목표:** 재무 데이터 수집 + 가치평가 모델 3종
**모듈:**
  - `src/data/dart_client.py` — DART OpenAPI 재무제표 수집
  - `src/engine/valuation/` — RIM, DCF, DDM 모델
  - `src/api/valuation_routes.py` — 종목 가치평가 API
  - Frontend 종목 가치평가 페이지

**산출물:** 47개 → 57개 API, 3 → 4 대시보드

### Phase 2: Smart Screening (다음)
**목표:** 다중 조건 종목 스크리너
**모듈:**
  - `src/engine/screener/` — 재무+기술+매크로 필터 엔진
  - `src/api/screener_routes.py` — 스크리너 API
  - Frontend 스크리너 페이지

### Phase 3: AI Narrative Intelligence
**목표:** Claude API 기반 자동 투자 보고서
**모듈:**
  - `src/services/narrative/` — Claude API 호출 + 프롬프트 엔지니어링
  - PDF 리포트 생성
  - 실시간 매크로 해석

### Phase 4: Macro Expansion
**목표:** 한국 금리/환율/CPI, 경제지표 일정, 사이클 분석
**모듈:**
  - `src/data/korea_macro/` — BOK API, KOSIS 연동
  - Stage 9 Regime Detector 강화

### Phase 5: Platform UI/UX Redesign
**목표:** 밸리AI급 네비게이션 + 종목 상세 + 산업 분석
**모듈:**
  - 글로벌 사이드바 네비게이션
  - 종목 상세 페이지 (재무+가치+차트+뉴스 통합)
  - 산업/섹터 밸류체인

---

## 시스템 전체 진화 맵

```
Stage 1-10  ← 이미 GCP 배포 중
    ↓
Stage 11    Multi-Strategy Backtest + 5-Factor Attribution
Stage 12    Production Realism Engine (5 hooks)
Stage 13    Live Trading + Production Hardening
    ↓
Phase 1  ✅ Fundamental + Valuation (RIM/DCF/DDM)        완료
Phase 2  ✅ Smart Screener (RIM·DCF·DDM 기반)        완료
Phase 3  ✅ AI Narrative (6 도메인 + 스트리밍)        완료
Phase 4  ✅ Macro-Quantum Integration              완료
Phase 5  ✅ Premium UX — Command Center + Palette       완료
```

## 경쟁 우위 — 우리가 밸리AI/젠포트보다 우월한 영역

| 영역 | 밸리AI | 젠포트 | **우리** |
|---|---|---|---|
| PIT-safe 백테스트 | 미확인 | 기본 | **✓ Stage 11** |
| 5-Factor Attribution | ✗ | ✗ | **✓ 유일** |
| Counterfactual 분석 | ✗ | ✗ | **✓ 유일** |
| Market Impact (√Q/ADV) | ✗ | ✗ | **✓ Almgren-Chriss** |
| Regime-Adaptive 배분 | 부분 | ✗ | **✓ EWMA+HardCap** |
| 실거래 5-layer 안전장치 | ✗ | 기본 | **✓ 10 risk checks** |
| Broker Reconciliation | ✗ | ✗ | **✓ Ghost/Missing 감지** |
| Priority Queue Gateway | ✗ | ✗ | **✓ heapq + circuit** |

**결론: 우리의 백테스트-실거래 파이프라인은 이미 기관급 수준. 부족한 것은 "데이터 폭"과 "해석 레이어".**

---

## 📌 현재 상태 (이번 통합본 기준)

| 카테고리 | 보유 기능 | 평가 |
|---|---|:---:|
| 백테스트 (PIT-safe, 5-Factor, Counterfactual, Walk-Forward) | ✅ | 기관급 |
| 멀티전략 통합 + Regime-Conditional Alpha | ✅ | 차별화 |
| Production Realism (5 hooks 모두 구현) | ✅ | 차별화 |
| 실거래 (KIS API + 5-Layer Safety + Kill Switch) | ✅ | 기관급 |
| Production Hardening (Reconciler/Gateway/State Machine/Notifier) | ✅ | 차별화 |
| 가치평가 (RIM + DCF + DDM 통합) | ✅ | 밸리AI 대응 |
| **Total** | **10/10 Phase 완료 🎉** | |

남은 Phase 2~5는 본 ROADMAP에 명시. 즉시 시작 가능 모듈 모두 구현됨.

---

## 🔨 Screener V2 — Macro-Aware Visual Screener (진행 중)

| Milestone | 내용 | 상태 |
|---|---|:---:|
| **M1** | Filter Engine Core — AST(AND/OR 중첩 + 절대값/상대랭킹) + 3 API | ✅ |
| **M2** | Visual Filter Builder (3단 UI + 디바운스 count) | ✅ |
| **M3** | Macro-Adaptive Intelligence (국면 동적 가중 + 추천 배너) | ✅ |
| **M4** | Ecosystem Linkage (거장 프리셋 + 백테스터 + AI 브리핑) | ✅ |

### M1 산출물
- `src/engine/filter_ast.py` — FilterCondition/FilterGroup + 2-Pass 평가 (14필드 카탈로그)
- `src/engine/screener.py` — run()에 filter_ast 통합 (하위호환)
- `src/api/screener_routes.py` — fields / run-advanced / count 엔드포인트
- `frontend/src/lib/screenerApi.ts` — FilterGroupNode 타입 + runAdvanced/count/fields
- 검증: 상위 N% 랭킹 · 3-depth 중첩 · 성능 0.031s(kospi200) · 하위호환 100%

### M2 산출물
- `frontend/src/components/screener/FilterBuilder.tsx` — 3단 빌더 (CategorySidebar + ConditionEditor + FilterStack)
- `frontend/src/app/screener/page.tsx` — 간편/고급 모드 토글 + AdvancedResults leaderboard
- 디바운스 300ms count · 실시간 통과 종목 수 TickValue flash · 조건 칩 fade-in
- 검증: TypeScript 0 errors · Next.js 14/14 · /screener 16.5 kB

### M3 산출물 (독점 무기)
- `src/engine/screener.py` — `_regime_weights()` 국면별 동적 가중 + `use_macro` 옵션
- `src/api/screener_routes.py` — `macro-guidance` API (국면별 추천 팩터 + 가중치)
- `frontend/src/components/screener/FilterBuilder.tsx` — MacroGuidanceBanner (추천 적용 + 국면 가중 토글)
- Phase 4 `get_regime_state()` 재사용 · 국면별 점수 차이 평균 2.4점 입증
- 검증: Reflation→저PER·저PBR 추천 · TypeScript 0 errors · Next.js 14/14

### M4 산출물 (생태계 통합 — Screener V2 완성)
- `src/engine/screener_presets.py` — 9개 프리셋 (거장4·국면2·테마3)
- `src/api/screener_routes.py` — presets / presets/{id} / presets/{id}/run (3 API)
- `frontend/src/components/screener/EcosystemPanel.tsx` — PresetGallery + EcosystemActions
- 백테스터 연동: 통과 종목 → /admin/multi-backtest?tickers=... (Stage 11 재사용)
- AI 브리핑: 통과 종목 + 현재 국면 → narrativeApi.macro (Phase 3 재사용)
- 검증: 그레이엄 42/50·마법공식 9/50 통과 · TypeScript 0 errors · Next.js 14/14 · /screener 18.1kB

**Screener V2 (M1-M4) 완료** — 80 신규 API · 밸리AI/버틀러/젠포트 능가

---

## 🚀 Screener V2: The Alpha Creator (진행 중)

| Milestone | 내용 | 상태 |
|---|---|:---:|
| **V2-M1** | Formula Engine + Peer-Relative (kind 디스패처) | ✅ |
| **V2-M2** | AI Natural Language Copilot (NL2AST) | ✅ |
| **V2-M3** | Technical/Alt Indicators + Event-Driven | ✅ |
| **V2-M4** | Point-in-Time Screening (타임머신) | ✅ |

### V2-M1 산출물
- `src/engine/formula_parser.py` — 안전한 AST 수식 파서 (eval 금지, 화이트리스트, 인젝션 차단)
- `src/engine/filter_ast.py` — FilterCondition v2 (`kind` 디스패처: field/formula/peer) + `build_peer_context` (섹터 통계 2-Pass)
- `src/api/screener_routes.py` — validate-formula / peer-groups API
- `frontend/src/components/screener/FilterBuilder.tsx` — ConditionEditor 4모드 (절대값/랭킹/Peer/수식) + 실시간 수식 검증
- `frontend/src/lib/screenerApi.ts` — screenerV2Api + conditionLabelV2
- 검증: 인젝션 차단(`__import__`/`eval`/속성접근) · 수식 평가 · 섹터 평균/중앙값/상위% 비교 · 복합필터 0.007s · 하위호환

### V2-M2 산출물 (독점 무기)
- `src/services/screener_copilot.py` — NL2AST (Claude 재사용 + 규칙 기반 Mock fallback)
- `src/api/screener_routes.py` — nl2ast / nl2ast/examples API
- `frontend/src/components/screener/FilterBuilder.tsx` — CopilotBar (자연어 입력 + 미리보기 + human-in-the-loop)
- 신뢰 경계: validate() 강제 + 1회 재시도 + 미리보기 후 명시적 적용
- 검증: "부채 적고 배당 높은 방어주"→2조건 · "PER이 섹터 평균보다 낮은"→peer kind 생성 · 전 예시 유효 AST · Mock fallback


### V2-M3 산출물 (데이터 레이어 신설)
- `src/data/market_data.py` — RSI(14)/MACD/이격도/수급 + deterministic mock + 6시간 캐시
- `src/data/event_calendar.py` — 실적/배당락 캘린더 (mock + DART 연동 여지)
- `src/engine/filter_ast.py` — technical/event kind + lazy 평가 (조건 있을 때만 시계열 계산)
- `src/api/screener_routes.py` — indicators / events-catalog API
- `frontend/.../FilterBuilder.tsx` — 통합 카탈로그(기술지표/수급/이벤트 카테고리) + 전용 에디터
- 검증: RSI<30 과매도 · 실적 14일 이내 · 복합 0.006s · lazy 미발동시 0.0003s · 하위호환

### V2-M4 산출물 (타임머신 — Screener V2 완성)
- `src/engine/pit_store.py` — 시점별 재무/가격 스냅샷 (공시시차 45일, look-ahead 차단)
- `src/engine/screener.py` — run(as_of_date) + PIT 재무 후처리 + 정렬 결정성
- `src/api/screener_routes.py` — run-pit / pit-dates API
- `frontend/.../FilterBuilder.tsx` — TimeMachineBar (과거 시점 선택 + 현재 대비)
- 검증: 2020-03-31 PIT(SK하이닉스 PER 7.3→2.4) · 미래 차단 · 결정성 재현 · 하위호환

**Screener V2: The Alpha Creator (M1-M4) 완료** — 6대 킬러 피처 + 14 신규 API

---

## 🌌 Screener V3: The Ultimate Alpha (진행 중)

조건(kind 디스패처) vs 후처리(analyzers) 레이어 이분화. 11 작업단위.

| Phase | Milestone | 레이어 | 상태 |
|---|---|:---:|:---:|
| **0** | **M0: Mock Store 베이스 + Analyzer 골격** | 공통 | ✅ |
| **1** | M1: Forward Estimates / M2: Z-Score | 조건 | ✅ |
| **1.5** | Liquidity & Tradability Gate (Gemini 비평 수용) | 게이트 | ✅ |
| **2** | M3: Behavioral / M4a·M4b: Graph | 조건 | ✅ |
| **3** | M5: Sentiment / M6: Vector | 조건 | ✅ |
| **4** | M7: Collinearity→최적화 / M8: Stress-Test / M9: 마감 | 후처리 | ✅ |

### Phase 0 산출물 (공통 인프라)
- `src/data/mock_base.py` — DeterministicMockStore (해시 시드 + RNG + 캐시, 5개 신규 스토어 부모)
- `src/engine/filter_ast.py` — LAZY_CONTEXT_BUILDERS + EVAL_DISPATCH_V3 등록 테이블 + register_kind (신규 kind 자동 통합)
- `src/engine/analyzers.py` — 후처리 파이프라인 (M7/M8 토대, kind와 분리), ANALYZER_REGISTRY + run_analyzers
- `src/api/screener_routes.py` — run-advanced에 analyzers 훅 + /analyzers API
- 검증: MockStore 결정성 · analyzer 골격(미등록/빈집합 방어) · V2 하위호환 100% · TypeScript 0

### Phase 1 산출물 (Fundamental Evolution)
- `src/data/consensus_store.py` — M1 Forward Estimates (DeterministicMockStore 상속): 선행EPS변화/선행PER/리비전/목표가
- `src/engine/z_score.py` — M2 시계열 Z-Score (Mean Reversion, 양방향 결정론적 시계열)
- `src/engine/filter_ast.py` — estimate/z_score kind + register_kind 자동 등록
- `src/api/screener_routes.py` — estimates-catalog API
- `frontend/.../FilterBuilder.tsx` — 추정치 카테고리 + Z-Score 모드 (3/5/10년 + σ 임계)
- 검증: 선행EPS>10% · PER -1.5σ 저평가 16종목 · ROE +1σ 개선 · lazy 미발동 0.0003s · V2 하위호환

### Phase 1.5 산출물 (Liquidity Gate — 퀀트 비평 수용)
- `src/engine/liquidity_gate.py` — ADV·시총·스프레드·거래정지 hard gate (모든 필터보다 먼저)
- `src/engine/screener.py` — run(liquidity_floor) 기본 "standard" (기관급 디폴트)
- `src/data/mock_base.py` — _maybe_missing (결측치 내성 — 실데이터 정합성)
- `src/data/consensus_store.py` — 결측치 시뮬 적용 (컨센서스 미커버)
- `src/api/screener_routes.py` — liquidity-profiles API + 게이트 통계 응답
- `frontend/.../FilterBuilder.tsx` — LiquidityGateBar (off/relaxed/standard/institutional)
- 검증: institutional 65종목(비유동 135 제거) · 결측치 9종목 무붕괴 · 게이트 우선순위 · 3-레이어(Gate→Condition→Analyzer)

**아키텍처 진화: 3-레이어 확립** — Gate(거래가능성) → Condition(kind) → Analyzer(후처리)

### Phase 2 산출물 (Relational & Behavioral)
- `src/data/market_data.py` — M3 내부자/개인 수급 + BEHAVIOR_SIGNALS 4종 + 복합 신호 평가기
- `src/engine/graph_store.py` — M4 경량 인메모리 지식 그래프 (BFS, supplier/customer/competitor, 24노드)
- `src/engine/filter_ast.py` — behavioral/graph kind + register_kind 자동 등록
- `src/api/screener_routes.py` — behavior-signals/graph-meta/graph-search/graph-relations API
- `frontend/.../FilterBuilder.tsx` — 행동재무 카테고리 + 공급망 그래프 에디터(타겟 검색+관계+depth)
- 검증: 행동신호 4종 · 삼성전자 공급사 1-hop 3개→2-hop 8개 · 그래프 필터 0.0002s · lazy 미발동 · V2 하위호환

### Phase 3 산출물 (Unstructured AI Intelligence)
- `src/services/sentiment_worker.py` — M5 NLP 센티먼트 (사전계산 DB 격리, Claude 미호출, 정성적 맥락 필터)
- `src/engine/vector_store.py` — M6 8차원 임베딩 + 코사인 유사도 (Twin 종목 탐색)
- `src/engine/filter_ast.py` — sentiment/vector_sim kind + register_kind 자동 등록
- `src/api/screener_routes.py` — sentiment-catalog/vector-meta API
- `frontend/.../FilterBuilder.tsx` — AI 센티먼트 카테고리 + 유사 종목 에디터(종목 검색+유사도 슬라이더)
- 검증: 긍정뉴스 53종목 0.0098s · 자기유사도=1 · Twin 7종목 · threshold 0.95→1종목 · lazy 미발동 · Gemini ④ 격리 수용

**Gemini 비평 ④ 수용**: 센티먼트는 정성적 맥락 필터(HFT 알파 아님), 사전계산 DB로 스크리닝 격리

### Phase 4 산출물 (Meta-Analytics & Risk Control — V3 완성)
- `src/engine/collinearity_analyzer.py` — M7 팩터 상관 매트릭스 + 편향 경고 + **Inverse-Variance 포트폴리오 최적화** (Gemini ③ 수용)
- `src/engine/stress_test_analyzer.py` — M8 4개 시나리오(금리/유가/환율/침체) 생존 시뮬 (Phase 4 매크로 역이용)
- `src/engine/analyzers.py` — M7/M8 자동 등록
- `src/engine/screener_presets.py` — M9 V3 프리셋 3종 (역발상 내부자/역사적 저평가/우량주+센티먼트)
- `src/api/screener_routes.py` — stress-scenarios API + analyzer_params
- `frontend/.../AnalyzerPanel.tsx` — M7 상관 히트맵+비중 / M8 생존율 게이지
- 검증: M7 PER↔PBR 0.99 포착+비중제안 · M8 시나리오별 차등(침체100%~환율37.5%) · 13 kind 전수 · 3-레이어 통합

**★ Screener V3: The Ultimate Alpha 완성 ★** — 3-레이어(Gate→Condition×13→Analyzer×2), 11 작업단위, Gemini 비평 4종 수용

---

## 📊 스크리너 기술지표 대폭 확장 (백테스터 통합)

스크리너 기술지표를 백테스터의 `kis_indicators.py`와 통합하여 6개 → 27개로 확장.
**동일한 계산 공식 재사용**으로 백테스터-스크리너 간 지표 정합성 보장.

| 카테고리 | 지표 |
|---|---|
| 모멘텀 (10) | RSI(14), RSI(7), 스토캐스틱 %K/%D, StochRSI, Williams %R, CCI, MFI, ROC, 모멘텀 |
| 추세 (7) | MACD 히스토그램, ADX, Aroon Up/Down, 이격도(20/60/120일) |
| 변동성 (4) | 볼린저 %B, 볼린저 밴드폭, ATR 비율, 변동성(10일) |
| 거래량·가격 (5) | 거래량 비율, 수익률(5/20/60일), VWAP 이격도 |
| 수급 (2) | 외국인/기관 5일 순매수 |

- `src/data/market_data.py` — INDICATOR_CATALOG 27개 + `_mock_ohlcv`(OHLCV DataFrame) + kis_indicators 재사용
- 정규화: bb_width·momentum을 %로 변환하여 종목 간 비교 가능
- 프론트엔드: 동적 카탈로그 병합 구조라 백엔드 확장만으로 UI 5개 카테고리 자동 표시
- 융합 강점: "저PER 가치주 + RSI 과매도 반등" 같은 펀더멘털×기술 조합 (백테스터엔 없는 교차 필터)

---

## 📐 Fundamental Factor Library (FFL) — 학술 펀더멘털 팩터 35종

DART 원천 재무 데이터에서 유명 논문·퀀트 플랫폼 수준의 펀더멘털 팩터 35개를 도출.
모두 `field` kind로 통합 → 13 kind 아키텍처 무변경. peer/z_score/formula 전 모드 호환.

### 팩터 카테고리 (5종)
| 카테고리 | 대표 팩터 (출처) |
|---|---|
| 수익성·퀄리티 (8) | **GP/A (Novy-Marx 2013)**, ROIC, 듀폰분해, 마진 3종, FCF마진 |
| 밸류에이션(고급) (10) | EV/EBITDA·EV/Sales·EV/FCF, **PEG(Lynch)**, **Acquirer's Multiple(Carlisle)**, **Shareholder Yield(Faber)**, FCF Yield |
| 성장성·모멘텀 (7) | 매출/영업이익/EPS 성장률(YoY·CAGR), **12-1 모멘텀(Jegadeesh-Titman)**, **PEAD(Bernard-Thomas)** |
| 안정성·건전성 (7) | **Altman Z(1968)**, **Beneish M(1999)**, **Accruals(Sloan 1996)**, 유동/당좌비율, 이자보상배율 |
| 종합 팩터 (3) | **F-Score(Piotroski 2000)**, **QMJ(Asness/AQR 2019)**, **Magic Formula(Greenblatt)** |

### 학술 팩터 프리셋 (10종)
마법공식 · 노비-마르크스 퀄리티 · 피오트로스키 F-Score · 인수자의 배수 · QMJ · 주주환원수익률 · GARP(Lynch) · 철벽 우량주 · 고퀄리티 컴파운더 · 딥 밸류

### 산출물
- `src/data/fundamentals_store.py` — FundamentalsStore (DeterministicMockStore 상속), 35팩터 도출 로직
- `src/engine/filter_ast.py` — FIELD_CATALOG 자동 병합 (14→49 field)
- `src/engine/screener.py` — attach_fundamentals (게이트 후 동적 속성 주입), to_dict 확장
- `src/engine/screener_presets.py` — 학술 프리셋 10종 (총 22개)
- `src/api/screener_routes.py` — fundamentals-catalog API
- `frontend/.../FilterBuilder.tsx` — 펀더멘털 5개 카테고리 동적 병합
- 검증: 35팩터 필터 작동 · 펀더멘털×기술/추정/Peer 융합 · z_score/formula 호환 · 하위호환

**아키텍처 우월성 입증**: 50+ 팩터 추가에도 `field` kind 하나로 통합 → kind 디스패처·analyzer·게이트 무변경

---

## 🔌 실데이터 연동 (DART + KIS) — mock에서 도구로

플랫폼의 가장 치명적 결함(전부 mock)을 해소. 키 유무에 따라 자동 분기하는 실데이터 파이프라인 구축.

### 연동 구조
| 데이터 | 소스 | 진입점 | 결과 |
|---|---|---|---|
| 재무제표 | DART OpenAPI | `dart_client.get_financial_statement_full` | 35개 학술 팩터 실데이터화 |
| 시세·일봉 | KIS OpenAPI | `kis_client.get_daily_ohlcv` + `get_kis_client` 팩토리 | 시총·PER·PBR·27 기술지표·백테스트 |

### 핵심 설계
- **자동 분기**: 키 있으면 실데이터, 없으면 mock fallback (코드 무수정 전환)
- **DART corpCode.xml 자동 다운로드**: 전체 상장사 종목코드→고유번호 매핑 (캐시)
- **KIS 통합 팩토리** `get_kis_client()`: KIS_USE_MOCK/IS_PAPER로 mock/모의/실계좌 자동 선택, 토큰 싱글톤 캐시(1분 1회 제한 대응)
- **시총 우선 주입**: `_enrich_kis_quotes`로 KIS 실시세 → fundamentals 계산 입력
- **출처 표시**: API 응답 `data_source`로 실데이터/mock 명시

### 산출물
- `src/execution/kis_client.py` — get_daily_ohlcv·get_price 확장·get_kis_client 팩토리
- `src/data/dart_client.py` — get_financial_statement_full·corpCode.xml 자동 매핑
- `src/data/fundamentals_store.py` — _real_raw_financials (DART 실연동, mock fallback)
- `src/data/market_data.py` — _real_kis_ohlcv (KIS 일봉, mock fallback)
- `src/engine/screener.py` — _enrich_kis_quotes (실시세 보강)
- `verify_connection.py` — 단계별 연동 검증 스크립트
- `REAL_DATA_SETUP.md` — 키 발급→.env→검증→실행 완전 가이드
- 검증: 키 없을 때 100% mock fallback · 키 있을 때 자동 실데이터 전환 · 전체 회귀 무손상

---

## 🔁 스크리너 → 백테스터 원클릭 연결 (2순위)

스크리닝과 백테스트가 분리돼 있던 구조를 잇고, 백테스트 데이터 공급을 일원화.

### 핵심 갭 해소
- **문제**: load_ohlcv가 DB(daily_prices)에서만 읽는데, DB를 채우는 파이프라인이 없어 항상 "No OHLCV data"
- **해결**: load_ohlcv_unified — DB → KIS 실시간 → mock 자동 우선순위. KIS 성공 시 DB 자동 적재(다음 백테스트 가속)

### 산출물
- `src/data/ohlcv_loader.py` — load_ohlcv_unified(DB→KIS→mock), ingest_to_db(배치 적재)
- `src/kis_backtest_engine.py` — 통합 로더 사용하도록 run() 패치
- `src/api/screener_routes.py` — POST /screen-to-backtest (스크리닝→백테스트 원클릭), GET /backtest-strategies
- `frontend/.../BacktestPanel.tsx` — 통과 종목 백테스트 UI (전략/기간/종목수 선택, 4대 지표+자산곡선)
- `frontend/.../FilterBuilder.tsx` — 스크리닝 실행 후 BacktestPanel 렌더
- `screenerApi.ts` — backtestBridgeApi

### 워크플로우
스크리닝(유동성 게이트+펀더멘털) → 통과 상위 N종목 추출 → 선택 전략으로 백테스트 → 수익률·CAGR·샤프·소르티노·MDD·승률·자산곡선 산출. 10개 전략(골든크로스·모멘텀·이격도·평균회귀 등) 지원.

### 검증
여러 전략(GoldenCross/Disparity/MeanReversion)이 각기 다른 수익률 산출 확인. mock fallback 정상. 실데이터 연동 시 동일 엔진이 실제 OHLCV로 백테스트.

---

## 🤖 실거래 자동매매 (3순위) — 젠포트의 해자

스크리너/전략 → KIS 실주문의 전 과정을 안전장치와 함께 구축. 실제 자금 거래.

### 핵심 설계 — 안전 최우선
6중 안전장치로 실투자 리스크 통제:
1. **Kill Switch** — 전역 주문 차단
2. **일일 손실 한도** — -X% 도달 시 신규 매수 중단
3. **주문 금액 상한** — 종목당 최대 투자금
4. **일일 투자 한도** — 하루 총 신규 투자 상한
5. **포지션 수 제한** — 동시 보유 종목 수
6. **Dry-run 기본** — 실주문 없이 시뮬 (명시적 해제 필요)

추가로 모드 명시(mock/paper/real), 중복 매수 방지, 실계좌 확인 체크.

### 산출물
- `src/engine/trading_engine.py` — TradingEngine(오케스트레이터), SafetyConfig(6중 안전장치), 포지션 사이징
- `src/kis_order_executor.py` — _send_order를 place_order API로 재작성, get_balance 연동
- `src/api/trading_routes.py` — status·mode·execute·screen-to-trade·kill-switch (5개)
- `frontend/.../LiveTradingPanel.tsx` — 모드 인식 UI, 안전장치 컨트롤, 실계좌 확인
- main_api 등록 (106 endpoints)

### 워크플로우
스크리닝 → 통과 종목을 균등 비중 매수 시그널로 변환 → 6중 안전장치 검증 → KIS 주문(dry-run/paper/real) → 체결. 기존 order_tracker(상태머신)·portfolio_rebalancer와 연계 가능.

### 모드별 동작
| KIS_USE_MOCK | KIS_IS_PAPER | 모드 | 동작 |
|---|---|---|---|
| 1 | - | mock | 가짜 데이터, 실주문 없음 |
| 0 | 1 | paper | 모의투자 계좌, 가상 자금 |
| 0 | 0 | real | ⚠ 실계좌, 실제 자금 |

### 검증
6중 안전장치 차단 작동 · Kill Switch · screen-to-trade 5종목→주문 · dry-run 기본 안전 · 전체 회귀 무손상.

**⚠ 실거래 주의**: dry_run=false + real 모드는 실제 자금이 거래됩니다. 반드시 모의투자(paper)에서 충분히 검증 후 사용하세요.

---

## 🔧 데이터 인프라 QA (4순위) — Unknown Corp 박멸 + 품질 검증

플랫폼 신뢰도의 마지막 조각. 가짜 종목코드와 데이터 품질 문제를 해소.

### 핵심 발견 & 해결
- **문제**: KOSPI200 = 실제 50개 + 가짜 150개(100000~100149) → 결과의 75%가 "Unknown Corp"
- **해결**: 중앙 종목 마스터(실제 KOSPI 129종목) 구축 → 가짜 코드를 실제 종목으로 교체, 종목명 100% 해소

### 산출물
- `src/data/stock_master.py` — 중앙 종목 마스터(코드↔명↔섹터), DART corpCode 역매핑, 데이터 품질 검증기
- `src/engine/screener.py` — KOSPI200을 실제 마스터 종목으로 재구성, _to_item 종목명 해소
- `src/api/screener_routes.py` — data-quality(품질 리포트), stock-master/stats
- `verify_connection.py` — DART 종목명 캐시 자동 생성 (전체 상장사)
- `frontend/.../DataQualityPanel.tsx` — 품질 점수·종목명 해소율·이상치·출처 표시

### 데이터 품질 검증기
- **종목명 해소율**: Unknown Corp 0% 목표
- **이상치 탐지**: 15개 필드 합리적 범위 검사 (PER -1000~1000, PBR 0~100, RSI 0~100 등)
- **결측 검사**: 핵심 필드(PER/PBR/ROE/시총) 누락 점검
- **품질 점수**: 0~100 (이슈 -15, 결측 -10), 건강도 4단계(excellent/good/fair/poor)

### 효과
- Unknown Corp 130종목 → **0종목** (100% 실명화)
- M7/M8 analyzer 결과도 실제 종목명 (스트레스 취약종목 실명 표시)
- DART_API_KEY 설정 시 전체 상장사 종목명 자동 캐시

### 검증
종목 마스터 129개 · Unknown 0% · 품질 90점(excellent) · 전 기능 무손상

---

## 🎨 Variant "Institutional Terminal" 디자인 — 5개 탭 전면 적용

플랫폼 UI를 Variant 시안 기반 블룸버그 터미널풍 디자인으로 전환. 좌측 사이드바 + 5개 동등 모듈.

### 디자인 시스템
- 폰트: Geist(본문) + JetBrains Mono(숫자/메타)
- 색: accent #1200ff, ink #111111, muted #71717a, border #e5e5e5, surface #fafafa, radius 2px
- 셸: TerminalShell.tsx (좌측 사이드바 5모듈 + 시스템상태 + 코너마크 + 그리드 오버레이)
- layout.tsx가 기존 TopNav를 TerminalShell로 교체

### 5개 탭 (전부 실데이터 연결)
1. Screener — 3-pane 워크스페이스 + 라이브 카운트 + 결과 테이블
2. Backtester — 설정 패널 + 5개 지표 카드 + 자산곡선 SVG + 구성종목 (run ~15초)
3. Macro — 4-quadrant 국면도 + 실제 거시지표 + 자산배분
4. Company — 기업헤더 + 메트릭바 + RIM/DCF/DDM 내재가치 + 점수분해
5. Risk — 스트레스 시나리오 버튼 + 생존율 + 취약종목 테이블

### 검증
TypeScript 0 errors · next build 전체 통과 · 4개 신규 탭 라이브 렌더링 확인 · 실제 백엔드 데이터 연결 (mock 모드)
