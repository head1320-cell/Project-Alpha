# 애드덤 채점표 — ★애드덤이 정한 기준으로 이 저장소를 잰다★

> 실측 2026-09-12 · 기준 커밋 `bd109f1` + Y1 · ★읽기 전용 감사 + 안전 3종 수정★
> 원문: [`../Project_Alpha_RA_Product_Master_Prompt.md`](../Project_Alpha_RA_Product_Master_Prompt.md) 의 **ADDENDUM** ·
> 증거: [`2026-09-12-ra-benchmark-evidence-matrix.md`](2026-09-12-ra-benchmark-evidence-matrix.md) ·
> 갭: [`2026-09-12-ra-gap-analysis.md`](2026-09-12-ra-gap-analysis.md) ·
> 규칙: [`2026-09-12-ra-product-rules.md`](2026-09-12-ra-product-rules.md)

## 0. 왜 문서 9개가 아니라 채점표 한 장인가

애드덤은 `docs/` 에 문서 9개를 새로 만들라고 한다. 그런데 주제가 기존 스펙과 크게
겹친다 — `data-lineage` 는 `DATA_PLATFORM_SPEC` + `run_evidence` 가, `backtest-validation`
은 사전등록 JSON 과 `2026-08-22-backtest-reliability-design` 이 이미 답한다.
★같은 것을 두 번 적으면 반드시 갈라진다★(CLAUDE.md 헤더).

그래서 **채점하고 가리킨다**. 빈 칸만 새로 쓴다.

---

## 1. ★합격 기준 13개★ (애드덤 §9.3) — 실측

판정: `통과` · `부분` · `미달`. ★근거는 파일 경로다.★

| # | 기준 | 판정 | 근거 / 왜 그 판정인가 |
|---|---|---|---|
| 1 | paper trading 이 기본 실행 모드 | **통과** | 기본은 PAPER 보다 **더 안전한 `SHADOW`** — `order_executor.ExecutorState.mode`. 더해 `trading_engine.SafetyConfig.dry_run=True` · `kis_client` 팩터리 `KIS_IS_PAPER` 기본 `"1"` · `mock_gate.mock_allowed()` 기본 `"1"`. ★단 모드는 프로세스 로컬이라 재시작하면 `SHADOW` 로 되돌아간다★(영속 아님) |
| 2 | 실제 브로커 주문이 호출되지 않는다 | **통과**(Y1 이후) | ★직전까지 미달이었다★ — `_execute_paper` 가 클라이언트를 확인하지 않아 `KIS_USE_MOCK=0`+`KIS_IS_PAPER=0` 이면 PAPER 가 실주문을 냈다. `execution/client_realism.py` + `tests/test_paper_mode_is_simulated.py` 가 막는다. LIVE 는 설계상 가능하되 확인 토큰 필요 |
| 3 | 모든 성과에 상태 라벨 | **부분**(Z 이후) | ★직전까지 미달이었다★ — 종류 축이 공용 컴포넌트로 없었다. 이제 `src/domain/perf_kind.py` 가 어휘를 갖고 **응답 9경로**가 `perf_label` 을 싣고 `shared/ui/PerfLabel.tsx` 가 그린다(부착 10화면 · 트립와이어 `tests/test_perf_label_contract.py`). ★`부분` 인 이유 둘★: ⑴ 기존 배지 넷(`brun-badge` PIT · `tbt-prov` 데이터 · `as-bt-badge` OOS · 인라인 모드)이 그대로라 **같은 화면에 축이 다른 배지가 둘 이상** 보일 수 있다. ⑵ 사유가 적힌 허용 목록 8건이 남아 있다(랜딩 데모 · 리얼리즘 둘 · 종목 위험지표 · 상태 제공자 · 기존 배지 셋) |
| 4 | 백테스트가 PIT 제약 적용 | **부분**(AG 이후) | `engine/run_evidence.py` 4축(price·universe·macro·fundamentals) · `data/pit_macro.accumulate_for_bars` · `dart_history` 빈티지. ★직전까지 `signal_lag` 기본이 `0` 이었다★ — 신호를 당일 종가에서 뽑고 그 종가에 체결했다(종가 확정 전에는 낼 수 없는 주문). 이제 기본이 `1` 이고 `src/domain/execution_assumption.py` 가 단일 출처이며, 결과가 `execution_assumption` 블록으로 `precomputable`/`same_bar`/`unrecorded` 를 **선언**한다(`lag=0` 은 금지가 아니라 라벨된다). ★`부분` 인 이유 둘★: ⑴ **데이터 누출 축이 여전히 없다**(§4 — GARCH·DCC 등 전체표본 적합). ⑵ 기록 이전 런은 재현 조건을 몰라 `unrecorded` 이고, 그것은 통과가 아니다 |
| 5 | look-ahead 검사 존재 | **통과** | 위 4축 + `AXIS_UNKNOWN` 이 ★통과가 아님★을 명시. `regime_probability` 가 평활 확률의 배분 사용을 거부. AH 이후 **추정기 수준 누출**도 축이 생겼다(§4) — 다만 ★관측이지 수정이 아니다★. 그리고 AH 가 찾은 것 하나: 백테스트의 `allow_snapshot_fundamentals` 옵트인을 켜면 오늘의 재무가 과거 전 구간에 방송되는데, ★그렇게 돈 실행의 결과가 깨끗한 실행과 구별되지 않았다★ — 이제 `estimator_leakage` 블록이 말한다 |
| 6 | 거래비용·슬리피지 반영 | **부분** | 반영은 된다. ★그런데 비용 모델이 넷이고 수수료 기본값이 10배 다르다★ — `kis_backtest_engine` `0.0015` vs `multi_strategy_backtest`·`realism_engine` `0.00015`. 단일 출처를 자처하는 `data/market_rules.py` 를 **어느 백테스트도 읽지 않는다**(세금·스프레드·호가단위·가격제한 전부 백테스트 미적용) |
| 7 | 전략·모델·데이터 버전 추적 | **부분** | `code_version`(git SHA)이 `research_runs`·`backtest_runs`·`target_versions`·`regime_snapshots` 에 박힌다. `timing_rule_set_versions`·`scenario_pack_versions` 는 내용까지 보존. ★없는 것★: `strategy_version`·`feature_version`·`universe_version`·`cost_model_version`·모델 레지스트리 |
| 8 | 리밸런싱 제안에 reason code | **통과**(AA) | ★직전까지 미달이었다★ — `rebalance_policy` 의 `reason` 은 자유 문자열뿐이었다. 이제 `src/domain/rebalance_reason.py` 가 **두 축**을 갖고(trigger ⟂ decision reason) `rebalance_decision` 의 6개 종료 분기가 각자 `reason_code` 를 낸다. `investment_decisions.reason_code` 컬럼까지 이어지고, ★AST 트립와이어가 7번째 분기를 막는다★(`tests/test_rebalance_reason.py`). ★생산자 없는 상수 넷은 만들지 않았다★ — 설계 문서의 제안이었을 뿐이다 |
| 9 | 집중도·팩터 노출 계산 | **통과** | `engine/factor_exposure.factor_concentration` · `robust_opt`/`allocation_studio`/`collinearity_analyzer` 의 HHI·유효N · `constrained_opt.Constraints.group_caps_pct` · `liquidity_gate` |
| 10 | 모든 주문 제안에 data lineage | **부분**(AA) | ★직전까지 미달이었다★. `src/engine/decision_evidence.py` 가 결정측 축 넷(`price`·`as_of`·`target`·`macro`)을 세우고 **`run_evidence` 와 같은 롤업 함수**를 부른다. `execution_plans.dec_id` 로 주문이 판단을 가리키고 끊긴 계보는 사유와 함께 보고된다. ★`부분` 인 이유★: 결정측 축은 백테스트의 네 축과 **다른 것을 잰다** — 식별자 사슬은 이어졌지만 데이터 빈티지 시점 자체가 주문을 따라가는 것은 아니다 |
| 11 | live 전환이 기본 차단 | **통과** | `set_mode(LIVE, confirm_token="EXPLICIT_LIVE_CONFIRMED")` 없이는 `ValueError`. ★P-1(AC) 이후 그 라우트에 `require_admin` 이 붙었다★ — `confirm_token` 은 상수라 비밀이 아니었고, 이제 **admin 토큰**이 선행한다. 감사 로그의 행위자도 자칭이 아니라 토큰에서 관측된다 |
| 12 | kill switch 작동 | **부분**(AI) | 구조는 있고 `is_active()` 가 DB 실패 시 `True`(페일세이프). ★실측 정정(AF, 2026-09-13)★ — 자동 트리거는 AF 시점에 **4개 중 4개가 불능**이었다(그 직전 서술은 둘이라 적었다): `auto_dd`·`auto_cb` 는 `live_daily_pnl` 미기록, `auto_risk` 는 국면 점수 미상, `auto_api` 는 `api_failure_count` 를 아무도 안 채운다. ★그리고 `auto_api` 는 그 값을 `.get(…, 0)` 으로 읽어 **미상을 0 으로 접고** 있었고(P1-a 규율이 이 분기에만 빠져 있었다) `unverified_checks()` 목록에도 없어 못 재고 있다는 사실조차 보이지 않았다★ — AF 가 둘 다 고쳤다. `gradual` 청산은 ★1/5 만 팔고 **완료로 보고했다**★(`live_kill_events.n_positions_closed` 까지 그 거짓이 갔다) — AF 가 회계를 정직하게 했다(주문 로직은 불변). ★`부분` 인 이유★: 넷은 **여전히 발동할 수 없고** `gradual` 은 **여전히 1/5 만 판다**. AF 는 그 사실을 `GET /api/v1/live/kill-switch/readiness` 로 **보이게** 했을 뿐 고치지 않았다 | ★AI(2026-09-14) 이후★ — `live_daily_pnl` 에 **쓰는 코드**가 생겨(`src/execution/equity_history.py`, 감시 데몬이 매 틱 기록) `auto_dd`·`auto_cb` 가 **잴 수 있게** 됐다. 표·리더·보존정책은 원래 다 있었고 ★쓰는 코드만 없었다★. 다만 `MockKISClient.get_balance()` 가 완전 합성이라 출처를 함께 적고(`equity_source`, 어휘는 `src/domain/equity_observation.py`), 리더가 **브로커 행만** 계열에 넣는다 — 섞이면 `mixed_equity_source` 로 **거절**한다(조용히 고르지 않는다). ★`부분` 인 이유 셋★: ⑴ **넷 중 둘**만 무장했다(`auto_risk` 국면 점수·`auto_api` 실패 횟수는 그대로). ⑵ 자동 발동은 여전히 `RISK_MONITOR_AUTOTRIGGER="1"` 에서만이다 — ★재는 것과 막는 것은 다르다★. ⑶ mock 게이트 안에서만 검증했고 **실잔고로 확인하지 않았다**. |
| 13 | 테스트와 문서가 함께 생성 | **통과** | 저장소 관례 — 커밋마다 변이 배터리 + HISTORY + 스펙. 이 문서 자체가 그 예다 |

**요약** — 통과 **7** · 부분 **6** · 미달 **0**(AA 이후. Z 시점: 통과 6 · 부분 5 · 미달 2). ★미달은 이제 없다. 다만 `부분` 여섯이 남았고, 그것들은
전부 P2 가 집는다.★

---

## 2. ★매핑★ — 애드덤이 요구한 문서 9개는 어디에 있나

| 애드덤 문서 | 이미 답하는 곳 | 빈 곳 |
|---|---|---|
| `quant-research-integrity.md` | `CLAUDE.md` §2·§4 · [`2026-08-27-capability-lineage-audit.md`](2026-08-27-capability-lineage-audit.md) §0 · [`INGESTION_ARCHITECTURE_V2.md`](INGESTION_ARCHITECTURE_V2.md) | 추정기 수준 누출 규율 → §4 |
| `backtest-validation.md` | [`2026-08-22-backtest-reliability-design.md`](2026-08-22-backtest-reliability-design.md) · `macro_gate_preregistration.json` · `macro_gate_verdict.json` · `engine/research_preregistration.py` | PBO·deflated Sharpe 부재 → §4 |
| `performance-analytics.md` | `engine/quant_metrics.py`(단일 출처) · `engine/attribution_decomposer.py` | Treynor · 평균보유기간 · 국가/FX/현금 귀인 부재 → §4 |
| `execution-safety.md` | `2026-09-12-ra-product-rules.md` §1 · 이 문서 §5 | ★모드 어휘 여섯 종 지도★ → §5 |
| `regulatory-domain.md` | — | ★전무★ — [`갭 §9`](2026-09-12-ra-gap-analysis.md) · P-1 선행 |
| `data-lineage.md` | [`DATA_PLATFORM_SPEC.md`](DATA_PLATFORM_SPEC.md) · `engine/run_evidence.py` · [`INGESTION_ARCHITECTURE_V2.md`](INGESTION_ARCHITECTURE_V2.md) | 주문 제안까지의 연결 → 기준 #10 |
| `model-governance.md` | `data/alpha_registry.py`(5단계) · `engine/strategy_health.py`(5상태) · `engine/research_context.code_version` | 승인자·승인시각·롤백 기록 부재 → §5 |
| `strategy-lifecycle.md` | `alpha_registry.STATUSES` + `_PROMOTE_NEXT` + `USABLE_STATUS` | 애드덤의 11단계와 우리 5단계의 차이 → §5 |
| `company-claim-verification.md` | [`2026-09-12-ra-benchmark-evidence-matrix.md`](2026-09-12-ra-benchmark-evidence-matrix.md) §7(필드 확장) | 없음 |

★새 파일을 만들지 않았다★ — 빈 곳은 이 문서의 §4·§5 와 로드맵이 집는다.

---

## 3. Factuality Risk Register (애드덤 §10-C)

| Risk ID | Claim | Risk | Evidence Gap | Mitigation |
|---|---|---|---|---|
| FR-01 | "Q-X 가 스트레스 시 방어자산으로 전환" | 확인되지 않은 동작을 우리 국면 로직의 **근거**로 인용 | 1차 출처(`quantec.co.kr`) egress 차단 | 매트릭스 `QT-02` 를 `SRC_UNKNOWN`·`DO_NOT_IMPLEMENT` 로 고정. 우리 근거는 `regime_adaptive_allocator` 자신 |
| FR-02 | "퀀팃 = TDF 글라이드패스" | 없는 근거로 기능을 정당화 | 검색이 일반 TDF 설명만 반환 | `QI-02` `SRC_UNKNOWN`. 로드맵에 **"연금 계좌에 필요한 기능"** 으로 근거를 바꿔 기재 |
| FR-03 | 코스콤 통과율 | 출처마다 다른 수치 중 하나를 사실로 인용 | 분모 정의 미확인 | `KS-01` `SRC_UNKNOWN` + 세 URL 병기. ★하나를 고르지 않는다★ |
| FR-04 | "AI Quantec" 과 "Quantit" | 상호가 닮아 **다른 회사의 기능을 섞는다** | — | 매트릭스 §0-1 경고 + 한국어 상호를 1차 표기로 |
| FR-05 | `SRC_VERIFIED` 0건 | 독자가 "4사가 불투명하다" 로 오독 | ★이 환경이 1차 출처를 못 연다★ | 매트릭스 §0-2 + §6 승급 대기 URL 목록 |
| FR-06 | 회사 고유명 | 제품명이 내부 식별자로 굳는다 | — | 실측 0건 확인 + §7-2 중립 명칭 매핑 |
| FR-07 | 성과 수치 | 백테스트 값이 실적으로 읽힌다 | ★완화됨(Z)★ — 응답이 종류를 선언하고 화면이 그린다. 남은 위험은 허용 목록 8건과 축이 다른 배지의 공존 | 규칙 §3 의 4종 분리 + `perf_kind` 어휘 + 트립와이어 |

---

## 4. 퀀트 무결성 평가 (애드덤 §10-D)

| 항목 | 판정 | 실측 |
|---|---|---|
| point-in-time 데이터 | **부분** | 4축 증거 + 빈티지 두 계열(재무·매크로). `signal_lag` 기본은 `1`(AG — 결정이 장 시작 전 계산 가능)이고 실행마다 `execution_assumption` 으로 기록된다. ★기록 이전 런은 `unrecorded`★ |
| bias 검사 | **부분**(AH 이후) | look-ahead·생존편향은 축으로 존재하고, 이제 **데이터 누출 축**도 있다(`src/domain/estimator_fit.py` 어휘 + `src/engine/estimator_evidence.py` 롤업 — 판정은 `run_evidence.rollup` 공유). ★직전 문장은 사실이 아니었다★ — 여기 이름을 댔던 일곱 계열(`GARCH`·`DCC`·`MarkovRegression`·`GaussianMixture`·`DynamicFactor`·`genpareto`·`LedoitWolf`)은 **전부 리포트 전용**이고 백테스트·배분 결정에 닿지 않는다(`arch_model` 은 저장소에 아예 없고, `regime_ensemble` 은 스스로 *"배분에 쓰이지 않습니다"* 라고 적어 두었다). 실제로 결정에 닿는 자리는 `LEAKAGE_SITES` 의 여섯이고 `EXCLUDED_SITES` 가 안 잰 일곱을 사유와 함께 든다. ★`부분` 인 이유 둘★: ⑴ **관측만 했고 고치지 않았다**(사용자 결정 — 배분 경로 동작 변경은 별도 승인). ⑵ 축은 **창 ⟂ 빈티지** 두 축뿐이라 모형 설정 누출(하이퍼파라미터 선택 등)은 여전히 안 본다 |
| 비용 모델 | **부분** | 넷이 공존, 10배 불일치(기준 #6). ★사용자 결정: 이번엔 기록만★ |
| walk-forward | **통과** | `plan_walk_forward`/`simulate_walk_forward` 분리 + AST 테스트가 강제. rolling/expanding 선택 |
| 표본외 | **통과** | OOS 어휘가 화면까지 나간다(`PolicyBacktest` 의 "OOS · look-ahead 없음"). `company_view_control` 은 ★표본외가 없음을 스스로 밝힌다★ |
| 귀인 | **부분** | 5효과 + 커버리지 측정 + 잔차 라벨. ★FX·국가·현금 기여 없음★, 수수료는 `cost_effect` 하나로 뭉쳐 있다 |
| 과최적화 진단 | **부분** | PBO·deflated Sharpe·Bonferroni/FDR **없음**. 대신 ★Hansen SPA · 서러게이트 널(shift/markov/block) · power·MDE · 사전등록 지문(널 생성기까지 해시)★ 이 있다. 판정 어휘도 `evidence_of_no_effect` 와 `no_evidence` 를 구분한다 |
| 랜덤 K-fold 금지 | **통과** | `KFold`·`TimeSeriesSplit`·`cross_val` **저장소 전체 0건**. `src/models/` 세 학습기 모두 시간순 분할 + 스케일러를 train 에만 적합 |

---

## 5. 실행·규제 안전 평가 (애드덤 §10-E)

### 5-1. ★모드 어휘가 여섯 종이다★ (지도만, 통합은 별도 승인)

| # | 어휘 | 값 | 기본 | 전이 검증 |
|---|---|---|---|---|
| ① | `execution/order_executor.ExecutionMode` | SHADOW·PAPER·LIVE | `SHADOW` | ✗(LIVE 만 토큰) |
| ② | `engine/trading_engine.SafetyConfig.dry_run` → 모드 문자열 | dry_run·paper·real (+`get_account_status` 는 mock·paper·real) | `dry_run=True` | ✗(요청별 불리언) |
| ③ | `data/execution_store.STATUSES` | draft→…→reconciled 9종 | `draft` | ✔ 전이표 + 승인 게이트 |
| ④ | `engine/order_tracker.OrderState` | PENDING→…→SHADOW_LOGGED 10종 | `PENDING` | ✔ 전이표. ★기본 실행기가 이 기계를 안 쓴다★ |
| ⑤ | `KIS_IS_PAPER` · `mock_allowed()` | mock·paper·real | 둘 다 `"1"` | ✗(기동 시 env) |
| ⑥ | `state/trading_state.trading_config` | auto_trading | `False` | ✗ (★키 불일치 버그★) |

★"paper" 가 세 가지 뜻이다★ — KIS 모의투자 엔드포인트(⑤) · `dry_run` 아님(②) ·
`ExecutionMode.PAPER`(①). ①과 ⑤의 불일치가 기준 #2 의 결함이었고 Y1 이 그것을 막았다.
**여섯을 하나로 합치는 것은 실거래 안전 영역이라 별도 승인 사항이다.**

### 5-2. 그 밖에 측정된 것

- ★보강된 실행기가 기본 경로가 아니다★ — `stage13_routes.get_executor()` 가 평범한
  `OrderExecutor` 를 만든다. 대사 선동기화·상태기계·알림(`order_executor_v2`)은
  HTTP API 로 **도달할 수 없다**.
- `live_orders` 상태를 기본 실행기가 **raw UPDATE** 로 쓴다(④의 전이표 우회).
- ★규제 도메인 전무★ — 적합성·적정성·위험감수능력·투자목적·상품적격성·동의·
  개인정보 어느 것도 `src/` 에 없다(전수 grep 0건). ★선행 조건인 인증은 P-1(AC)
  에서 생겼다★ — 다만 그것은 문을 연 것이지 규제 도메인을 만든 것이 아니다.
- 감사 추적에 **위변조 방지가 없다**(해시 체인·서명·시퀀스 없음). 보존은
  `data/retention.py` 가 `AUDIT` 로 분류해 삭제를 금지하지만, ★법적 보존 요건은
  명시된 미상★이다.
- `trading_config` 키 불일치로 `/ws/live-risk` 첫 틱이 `KeyError` 이고 빈 `except` 가
  삼킨다. 그 소켓은 `random.normalvariate` 로 가격을 만드는 **데모 피드**다.

---

## 6. ★이 채점이 주장하지 않는 것★

- **애드덤을 이행한 것이 아니다.** 채점했고, 안전 셋을 고쳤고, 나머지는 *어느 단계가
  집는지*까지 적었다. 통과 7 · 부분 6 · 미달 0 은 **지금 상태**다(AA 이후).
- ★**미달 0 이 "애드덤을 이행했다" 는 뜻이 아니다**★ — `부분` 여섯은 각각
  남은 것을 적고 있고, 그중 비용 모델 10배 불일치와 추정기 수준 누출은
  **측정된 채로 남아 있다**.
- **`통과` 가 "투자에 쓸 수 있다" 는 뜻이 아니다.** 기준을 만족한다는 뜻이고,
  ★이 저장소는 경제적 가치 관문을 통과한 적이 없다★(CLAUDE.md §1).
- **비용 모델을 고치지 않았다.** 10배 불일치는 ★측정된 채로 남는다★ — 어느 값이
  맞는지 이 저장소가 잰 적이 없어서, 고치는 것보다 보이게 하는 것이 먼저다.
- **모드 어휘를 정리하지 않았다.** 여섯은 그대로다.
- **PAPER 가 이제 안전하다고 말하지 않는다.** 한 경로를 막았다. ★"누구나 모드를
  바꿀 수 있다" 는 P-1(AC)에서 해소됐다★ — 이제 admin 토큰이 필요하고 누가 바꿨는지
  감사 로그가 **관측**한다. 그러나 그것은 접근을 통제한 것이지 PAPER 경로의 정확성을
  검증한 것이 아니다.
- **규제 준수를 평가한 것이 아니다.** 코드에 무엇이 없는지를 셌을 뿐이고,
  ★업권·인가 판단은 이 저장소가 할 수 있는 일이 아니다★.
