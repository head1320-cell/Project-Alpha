# BK 설계 — 레포의 분석 도구를 전부 캔버스 노드로

상태: 승인됨(2026-09-25). 이 문서는 승인된 계획의 사본이다 — 웨이브가 진행되며 `docs/HISTORY.md` 에 실제 결과를 적는다.

## Context

BJ(토스식 워크플로우 UX)는 끝났다(`7d4c757`). 사용자 요청: *"기존 레포에 있는 모든 툴을 다
커스텀해서 간편하게 사용할 수 있게 고도화"*. 확인한 뜻: **캔버스 팔레트에서 원래 있던 분석
도구를 자유롭게 골라 노드로 놓고 잇는다.** 지금 노드는 핵심 사슬 7개뿐이고, 나머지 도구(스트레스·
시나리오·스크리너·알파·타이밍·국면·실행 계획·저널 …)는 마법사 화면에만 있다.

**사용자 결정 (이번 질문)**
- 순서: **안전한 것부터** — W1 확인하기 → W2 신호·후보 → W3 거시·타이밍 → W4 실행·기록 → W5
  전략·기업 → W6 정리(마법사 제거는 별도 결정).
- 저장: **'계산하기'는 절대 DB 에 쓰지 않는다. 저장은 노드 안 '저장하기' 버튼**(기존 저장 경로 1회).
  실제 주문은 어느 노드에도 없다.
- 타이밍·국면: **보는 노드 + '비중에 적용하는 노드'를 퀀트 고객 입장에서 고도화해 만든다.** 이 답을
  CLAUDE.md §3 의 Macro→Allocation 별도 승인으로 기록한다. 범위는 **기존 함수 재사용뿐**:
  `timing_rules_v2.combine`·`macro_overlay.three_way`·`target_versions.compile_target`
  (`final = base × exposure`, 나머지는 현금). `MODE_CAP`·`REGIME_TILTS`·임계값·레거시 `/timing`·
  `constrained_solve`·`hrp_macro` 는 한 줄도 바꾸지 않는다.

**감사로 확인한 위험 (계획이 막는다)**
1. 회사 뷰·조건부 추정이 Views 포트로 들어가면 `_backtest` 가 `req.views` 를 그대로 넘겨
   (`allocation_graph_nodes.py:303`) **전망 전용(forward-only) 값이 백테스트에 샌다**.
2. 오늘 계산한 타이밍 노출을 적용한 비중을 백테스트하면 **오늘 판단을 과거 전체에 쓰는 룩어헤드**다.
3. `/stress` 역사 분기·`/timing` 경로는 mock 이어도 응답에 표시가 없다(노드는 자기 출처를 단다).
4. `/graph/run` 은 매번 모든 노드를 돈다 → 쓰는 노드는 쓰기를 run 밖으로 빼야 한다.
5. `TargetVersionRequest.dry_run` 기본 False(저장함) — 노드는 `compile_target` 만 부른다.
6. 금지 어휘(`test_distribution_blocked.py`: subscribe·publish·provider·/share …)를 노드·라우트
   이름에 쓰지 않는다. `OrderExecutor`·`TradingEngine` 을 import 하지 않는다.

## 설계

### 1. 공통 계약 (BK0 — 엔진·계약만, 노드 0개 추가)
- **출처 태그가 포트를 따라 흐른다**: 노드 결과의 `provenance` 에 `pit: "pit"|"forward_only"|
  "unknown"`·`practice: bool`(= `mock_allowed()` 경로로 합성값을 썼는가)·`sources[]` 를 두고,
  엔진이 **하류로 합친다**(가장 약한 값이 이긴다: forward_only > unknown > pit, practice OR).
  구현: `portfolio_graph.run` 이 입력 포트 값의 태그를 모아 노드 결과에 `lineage` 로 싣는다.
- **백테스트 문지기**(`_backtest`): 입력 Weights/Views 계보에 `forward_only` 가 있거나 Weights 에
  노출 오버레이가 있으면 **실패 + 쉬운 사유**("오늘의 판단을 과거 전체에 쓰면 미래를 보고 한 계산이
  돼요 — '시점별 타이밍 시뮬레이션' 노드를 쓰세요"). 조용히 벗겨 내지 않는다.
- **저장 액션**: 새 문 `POST /api/v1/allocation/graph/nodes/{type}/save` — 그 노드를 **한 번 더
  계산**해 미리보기와 같은지(해시) 확인한 뒤 기존 저장 함수(`save_target`·`create_plan`·journal·
  `record_run`)를 한 번 부른다. `NodeSpec` 에 `save: Callable | None`. run 은 저장 함수를 부를 수
  없다(AST 트립와이어: 노드 run 경로에서 save_*/create_*/record_* 호출 0).
- **새 포트 타입**(색·쉬운 이름 포함): `Scenario`(시나리오) · `StressReport`(충격 결과) ·
  `Scores`(점수) · `RegimeState`(경기 국면) · `TimingSignal`(타이밍 신호) · `Trades`(주문 목록) ·
  `TargetVersion`(실행 목표) · `StrategyResult`(전략 묶음 성과).
- 모든 새 노드는 BJ 계약을 따른다: `stage`·쉬운 이름·파라미터 `x-ui`·`explain`·금지어 전수 테스트·
  기존 라우트와 **같은 수**(골든).

### 2. 웨이브 (각 웨이브 = TDD → 골든 → 변이 → E2E → 전체 게이트 → 커밋)

| 웨이브 | 노드 (쉬운 이름) | 입력 → 출력 | 감싸는 함수 |
|---|---|---|---|
| **W1 확인하기** | 과거 위기에 넣어 보기 · 가상 충격 주기 · 한국 시나리오 · 상관이 치솟으면 · 생각을 바꾸면 비중은? · 시나리오 고르기 | Weights(+Returns) → StressReport, (Returns+Views) → 민감도 | `allocation_stress_routes` 의 historical 경로·`_stock_shock`·`kr_scenario_pack.run_scenario`·`PortfolioRiskModel`·`sensitivity_matrix`·`scenario_packs` |
| **W2 신호·후보** | 조건으로 종목 거르기(스크리너) · 알파 점수 · 점수로 비중 · 팩터 포트폴리오 · 슬리브 합치기 · 중립화 | Universe → Universe/Scores → Weights | `ValuationScreener.run`(수정 금지, 조건은 `FIELD_BY_ID` 로 만든 조건 편집기) · `score_alpha`·`combine_alphas`·`_factor_weights` · `combine_sleeves`·`neutralize_portfolio` |
| **W3 거시·타이밍** | 지금 경기 국면(스냅샷) · 타이밍 신호 · 세 갈래 비교 · **노출 조절(비중에 적용)** · 시점별 타이밍 시뮬레이션 | → RegimeState, → TimingSignal, Weights+TimingSignal(+RegimeState) → Weights | `regime_snapshot_builder`·`get_snapshot` · `rule_set_from_specs`·`combine`·`three_way`·`overlay_from_snapshot` · `compile_target` · `simulate_rule_set` |
| **W4 실행·기록** | 주문 목록 미리보기 · 실행 목표 만들기 · 결정 기록 · 연구 기록 | Weights(+지금 비중) → Trades / TargetVersion | `build_plan`·`pre_trade_checks` · `compile_target`(저장은 버튼 → `save_target`) · journal·`record_run`(버튼) |
| **W5 전략·기업** | 전략 묶음 백테스트 · 기업 전망(뷰) · 가치평가 점검 · 성과 귀인 | 전략 id → StrategyResult, Universe → Views(forward_only) | `MultiStrategyBacktester`(`hrp_macro` 는 정직하게 거부 그대로) · `company_views` · valuation · `compute_attribution` |
| **W6 정리** | 팔레트 규모 대응 · 템플릿 4종 · 마법사 도구 대응표 | — | 마법사 제거는 **별도 승인 전까지 하지 않는다** |

### 3. '노출 조절' 노드 — 퀀트 고객 입장의 고도화 (W3 의 중심)
- **어느 판단을 따를지 고른다**(선택 카드): ① 타이밍만 ② 타이밍 + 경기 국면 ③ 직접 정함(%).
  세 갈래(`three_way`)를 노드 안에서 나란히 보여 주고 고른 것만 적용 — 충돌하면
  `conflict_explanation` 문장을 그대로.
- **적용 강도**(전문가 칸, 기본 100%): `exposure' = 1 − s·(1 − exposure)`. 100% 는 기존 규칙과 정확히
  같고(골든), 그 밖의 값은 출처에 "강도 s%" 로 남는다. 노출을 **키우는 쪽으로는 절대 못 간다**(0~1 클램프,
  one-way 불변식 테스트).
- **줄인 만큼은 현금**(`compile_target` 그대로, 재정규화 금지) — 카드 헤드라인: "주식 100% → 60%,
  현금 40%". 롱숏이면 gross 축소로 말한다.
- **정직성**: 매크로를 못 읽으면 조정하지 않고 "몰라요"(기존 `usable`). 직접 정함은 출처 "직접 정함 —
  근거 없음" 으로 가정 칩. 국면 스냅샷은 forward_only 라 결과 비중에 태그가 붙고 백테스트 문지기가
  막는다 → 과거 검증은 '시점별 타이밍 시뮬레이션' 노드로 안내(`simulate_rule_set`,
  `backtest_eligible` 이 거짓이면 그대로 거부).
- **실행 연결**: 결과 Weights 는 W4 '실행 목표 만들기'로 이어져 `status`(executable/research_only)와
  사유를 그대로 보인다.

### 4. 화면 (frontend-design — BJ 토큰 재사용, 강한 요소는 여전히 관문 레일 하나)
- **팔레트 규모**: 단계 그룹 접기·펼치기(노드 수 표시) · 검색은 쉬운 이름·설명·태그 · "곧 추가돼요" 는
  웨이브마다 줄어든다.
- **결과 렌더러를 포트 타입별로**(자세히 탭): StressReport(손실 막대 + 기여 표) · Scores(순위 막대) ·
  RegimeState(국면 확률 막대 + 기준일) · TimingSignal(상태 칩 + 켜짐/꺼짐 수) · 노출 조절(**전·후 비중
  이중 막대 + 현금 칸** — W3 의 유일한 새 시각 요소) · Trades(매수/매도 표 + 사전 점검 체크) ·
  StrategyResult(누적 곡선).
- **저장하기 버튼**(설정 탭 맨 아래, 실행·기록 노드만): "이 미리보기를 한 번 저장해요" → 결과 줄 "저장했어요 ·
  번호 tpv_…". 계산 결과가 낡았으면 버튼이 잠긴다("다시 계산한 뒤 저장할 수 있어요").
- **스크리너 조건 편집기**: 기본 칸은 프리셋 칩("싼 종목"·"꾸준히 버는"·"거래 많은"), 전문가는 서버
  `/screener/fields` 카탈로그로 조건 줄 추가(필드·비교·값). 규칙은 서버 `validate()` 만.
- 템플릿: 기본 사슬 · 스트레스 점검 · 스크리너 → 배분 · 타이밍 적용 → 실행 목표.

### 5. 마법사 도구 대응표 (W6 · 코드의 단일 출처는 `frontend/src/app/allocation/wizardNodeMap.ts`)

| 마법사 단계 | 캔버스 노드 |
|---|---|
| 00 OVERVIEW | — (캔버스 전체가 그 자리) |
| 0M MACRO PHASE | 경기 국면 불러오기(`regime`) |
| 01 CONSTRUCT | 종목 고르기 · 수익률 불러오기 · 조건으로 종목 거르기 · 팩터로 점수 매기기 · 점수로 비중 정하기 · 묶음 합치기 |
| 02 ALPHA LAB | 알파 식으로 점수 매기기 |
| 03 THESIS | 내 생각 넣기 · 기업 전망 넣기 · 기대 수익 추정 |
| 04 TIMING | 타이밍 신호 · 노출 조절(비중에 적용) · 시점별 타이밍 시뮬레이션 |
| 05 OPTIMIZE | 비중 계산 · 흔들림 나눠 보기 · 치우침 없애기 · 과거로 돌려 보기 |
| 06 STRESS | 상황에 넣어 보기 · 상관이 치솟으면 · 기대수익이 틀리면? · 어떤 성격인가요? |
| 07 ATTRIBUTION | 결정 되짚기 |
| 08 EXECUTION | 주문 목록 미리보기 · 실행 목표 만들기 |
| 09 JOURNAL | 결정 기록 남기기 |

마법사 밖 도구: 전략 묶음 돌려 보기(멀티전략 백테스트 화면) · 가치평가로 점수 매기기(가치평가 화면).

## 재사용
엔진 `src/engine/portfolio_graph.py`(Registry·run·NodeFailure) · 노드 패턴 `src/api/allocation_graph_nodes.py`
(`_subset`·`_ui`·`STAGES`·`PORT_TYPES`) · 설명 `src/api/allocation_graph_explain.py` · 관문
`src/domain/workflow_gates.py` · 위 표의 엔진 함수 · 프런트 `widgets/portfolio-graph/*`(GraphNode·
SettingsPanel·StoryPanel·NodeResultPanel) · e2e `helpers.ts`(`contrastAudit`·`trackErrors`).

## 하지 않는 것
기존 규칙·임계값·최적화기 의미 변경 · 실제 주문·승인·체결 입력 노드 · 레거시 `/timing` 병합 ·
`hrp_macro` 우회 · 라우트 응답 형식 변경(라우트의 mock 무표시는 따로 과제로 남긴다) · 마법사 제거 ·
서버 그래프 저장 · 파라미터 스윕.

## 검증 (웨이브마다)
- 백엔드: 노드 ↔ 기존 라우트 **같은 수 골든** · 출처 태그 합성 테스트(짝: pit 끼리는 pit) · 백테스트
  문지기(짝: 오버레이 없는 비중은 통과) · run 경로 쓰기 0(AST) · 저장 액션은 미리보기 해시 일치 때만 ·
  금지어·금지 import 전수 · 노출 조절 100% == `compile_target` 골든 · one-way 불변식 · 변이 배터리 ·
  ruff · `KIS_USE_MOCK=1 pytest tests/` 전체 단독.
- 프런트: tsc · eslint · next build(`/allocation` 119 kB 기준, 캔버스 청크 증가 기록) · Playwright
  portfolio-graph + allocation 관련 전부 · 새 노드 E2E(팔레트 → 잇기 → 계산 → 이야기·자세히) · 라이트·다크
  대비 · 실물 스크린샷.
- 커밋 BK0, W1…W6 → `claude/backtest-modern-ui-refactor-akxvbc` 푸시(PR 없음). 웨이브 사이에 사용자에게
  스크린샷과 함께 보고한다.
