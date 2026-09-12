# RA 제품 축 갭 분석 — ★기계는 있는데 표면이 없다★

> 실측 2026-09-12 · 기준 커밋 `564e035` · ★읽기 전용 감사다. 코드를 고치지 않았다.★
> 증거: [`2026-09-12-ra-benchmark-evidence-matrix.md`](2026-09-12-ra-benchmark-evidence-matrix.md) ·
> 규칙: [`2026-09-12-ra-product-rules.md`](2026-09-12-ra-product-rules.md) ·
> 저장 계층: [`DATA_PLATFORM_SPEC.md`](DATA_PLATFORM_SPEC.md)
>
> ★개수를 적지 않는다★(CLAUDE.md 헤더) — 칸마다 **소유 모듈**을 가리킨다.
> 판정: `complete` 제품으로 쓸 수 있다 · `partial` 기계는 있는데 무언가 끊겼다 ·
> `missing` 없다.

## 0. 한 문장으로

★이 저장소는 **연구 플랫폼**이고, 벤치마크 4사는 **자문·일임 제품**이다.★
그래서 갭은 "알고리즘이 약하다" 쪽이 아니라 **"사람·계좌·설명이 없다"** 쪽에
몰려 있다. 가장 많이 반복된 모양은 ★기계는 있는데 표면이 없다★ 였다.

| # | 도메인 | 판정 | 한 줄 |
|---|---|---|---|
| 1 | 데이터·신호 레지스트리 | `partial` | 카탈로그가 **다섯 갈래**, 합성 셋은 운영 차단(의도된 판정) |
| 2 | 집중도·제약 리스크 | ★`complete`★ | 그룹캡·HHI·팩터 집중·유동성까지 이미 있다 |
| 3 | 상시 리스크 감시 | `partial` | 탐지기는 다 있는데 ★도는 데몬이 없다★ |
| 4 | 보유 포트폴리오 진단 | `partial` | 기계는 있는데 **제품 표면이 없다** |
| 5 | 리밸런싱·집행 | ★`complete`★(단, 추적이 끊김) | 효용>비용 판단·불변 목표·승인 워크플로 |
| 6 | 연금·계좌 축 | `missing` | 계좌 유형·투자자 프로파일·적립·글라이드패스 전부 없음 |
| 7 | 일일 설명 | `partial` | 런 단위 5효과 귀인은 있으나 **보유 자산의 하루**를 설명하지 못함 |
| 8 | 유통·B2B | `missing` | 마켓플레이스·파트너 API 없음 — 그리고 ★선행 조건이 빠져 있다★(§9) |

---

## 1. 데이터·신호 레지스트리 — `partial`

**있는 것** — 필드/팩터 카탈로그 `src/engine/filter_ast.py`(`FIELD_CATALOG`·
`FieldMeta`)에 `fundamentals_store`·`price_factors_store`·`extended_factors_store`
가 각각 등록된다. 알파 DSL 은 `src/engine/alpha_lab.py`, 토큰은
`src/kis_strategies/factor_tokens.py`, 알파 수명주기는 `src/data/alpha_registry.py`
(draft→experimental→validated→approved→retired).

★가장 완성도 높은 것은 타이밍 쪽이다★ — `src/engine/timing_factors.py` 의
`TimingRule` 은 관측창·진입/청산·리밸런싱 주기·비용·**시점 데이터 타임스탬프**까지
한 스키마에 들고, `src/engine/timing_factor_meta.py` 가 **공표 지연과 개정 정책**을
출처에서 파생시킨다.

**끊긴 것** — ⑴ 다섯 카탈로그가 **한 어휘를 공유하지 않는다**. 어떤 신호는
`FieldMeta`(카테고리·단위·방향), 어떤 신호는 `TimingRule`(11필드), 어떤 신호는
문자열 토큰이다. ⑵ **증거 등급이 신호에 붙지 않는다** — `source_registry` 가
`E0~E3` 를 갖고 있으나 카탈로그 항목과 이어져 있지 않다.

**대체데이터** — 어댑터는 있다(`google_trends` · `naver_datalab` · `insider_flows` ·
`cb_sentiment`). 합성이었던 셋(`sentiment_worker` · `graph_store` ·
`consensus_store`)은 ★운영에서 차단된다★ — 이것은 결함이 아니라 G 작업이 내린
판정이다(합성값 금지, CLAUDE.md §6). `google_trends`/`naver_datalab` 은 클라이언트만
있고 `verified_live=False` 다.

> **없어서 못 하는 것** — "이 신호가 어떤 데이터에 기대고 그 데이터가 몇 등급인가"
> 를 **한 번에 답할 자리가 없다**. 솔루션퀀트식 `SignalRegistry` 의 값어치가 거기 있다.

---

## 2. 집중도·제약 리스크 — ★`complete`★

**있는 것** — `src/engine/constrained_opt.py` 의 `Constraints` 가 종목 상·하한,
**그룹 상한**(`group_caps_pct`), 회전율 상한, 베타 밴드, 현금·총/순노출을 한
자리에 들고 `constrained_solve()` 가 푼다. HHI 와 유효 종목 수는
`src/engine/robust_opt.py`·`allocation_studio.py`·`collinearity_analyzer.py` 가 재고,
**팩터 수준 집중**은 `src/engine/factor_exposure.py::factor_concentration()` 이
따로 낸다. 유동성은 `src/engine/liquidity_gate.py` + `liquidity_capacity.py`,
자산군 분류는 `src/data/exposure_taxonomy.py`(계약 문서까지 있다).

★솔루션퀀트의 "10종목 · 업스트림 80% · 1위 25%" 같은 규칙은 새 엔진이 필요 없다★ —
`group_caps_pct` + 종목 상한으로 **지금 표현 가능한 모양**이다.

**끊긴 것(사소)** — 그 제약을 **전략 메타데이터로 저장**하는 자리가 없다. 요청마다
넘긴다. §6 의 `StrategyMetadata` 가 그 자리다.

---

## 3. 상시 리스크 감시 — `partial` ★도는 데몬이 없다★

**있는 것** — 국면 판정(`src/engine/regime_*.py`, `NORMAL`/`CAUTIOUS`/`DEFENSIVE`),
국면별 노출 배수(`macro_overlay.py`), 방어 전환 규칙(`regime_adaptive_allocator.py`,
`realism_engine.py` 의 `defensive_risk_threshold`·하드캡·현금 버퍼),
리밸런싱 트리거(`portfolio_rebalancer.py` — `regime_change`·`volatility_spike`),
3상태 타이밍 신호(`timing_rules_v2.py`, `unavailable → risk_off` 불변식),
킬스위치 자동 발동 판정(`execution/kill_switch.py::should_auto_trigger()`),
브로커 대사 주기 루프(`engine/reconciler.py::start_periodic_sync()`).

**끊긴 것 — ★실측★**

```
should_auto_trigger  호출부  ⇒ 클래스 docstring 의 사용 예시 한 곳뿐
                              (주석은 "모니터링 루프에서 호출" 이라 적혀 있다 — 그 루프가 없다)
apscheduler          src/ 안 사용처 ⇒ 0 (requirements.txt 에는 선언돼 있다)
start_periodic_sync  기동 시퀀스에서 호출 ⇒ 없음. 수동 엔드포인트로만 켜진다
```

`src/startup/lifecycle.py` 가 띄우는 데몬은 **전부 데이터 적재**(KRX 백필 · 매크로
빈티지 · OHLCV/ETF 예열 · DART 재무 · 수급 동기화 · 고아 실행 정리)다.
★리스크를 감시하는 데몬은 하나도 없다.★

> **없어서 못 하는 것** — 콴텍의 Q-X 가 하는 일("24시간 모니터링")을 이 저장소는
> **요청이 들어올 때만** 한다. 사용자가 앱을 안 열면 아무도 보지 않는다.
> ★부품이 아니라 배선이 빠진 것이므로, 이것은 비교적 싼 작업이다.★

---

## 4. 보유 포트폴리오 진단 — `partial` ★기계는 있는데 표면이 없다★

**있는 것** — `factor_exposure.portfolio_factor_exposure()` 는 **임의의 비중 딕트**의
팩터 노출을 낸다. 위험 기여도는 `allocation_studio.risk_contributions()` 와
`kis_portfolio_analyzer`. 보유는 `src/database.py` 의 `portfolios` 테이블과
`src/api/account_order_routes.py` 의 브로커 잔고 조회로 **읽을 수 있다**.

**끊긴 것** — 그 둘을 잇는 코드가 없다. *"로그인한 사용자의 보유를 읽어 팩터·집중도
진단을 돌려주는 엔드포인트"* 가 없고, 화면도 없다. HHI 진단 문구
(`분산이 양호합니다 …`)는 `src/portfolio_manager.py` 에 있는데 ★그 모듈을
임포트하는 곳이 저장소에 없다★ — FastAPI 앱 기준으로 죽은 코드다.

> **없어서 못 하는 것** — 콴텍이 제품으로 파는 **진단보고서**. 우리는 계산기는
> 있는데 *"누구의 무엇을 진단하는가"* 가 정의돼 있지 않다(→ §6, §9).

---

## 5. 리밸런싱·집행 — ★`complete`★ (단, 추적이 백테스트에서 끊긴다)

**있는 것 — 이 저장소에서 가장 성숙한 영역**

| 층 | 모듈 | 무엇 |
|---|---|---|
| 판단 | `src/engine/rebalance_policy.py` | ★효용 개선 > 거래비용★ 일 때만 거래. **동적 밴드**(고정 ±5% 를 의도적으로 대체) |
| 구성 | `src/engine/investment_decision.py` | before/after **레그** 생성, 근거(`run_id`·`tpv_id`) 동반 |
| 목표 | `src/data/target_versions.py` | ★불변 목표 한 개★ — 세 화면이 서로 다른 목표를 보던 결함을 고친 자리 |
| 집행 | `src/data/execution_store.py` | `draft→reviewed→approved→paper_submitted→…→reconciled`. 사전점검 `block` 이면 `approved` 로 못 간다 |
| 안전 | `src/engine/trading_engine.py` · `src/execution/*` | `dry_run=True` · `SHADOW` · 킬스위치는 DB 실패 시 **작동 중으로 간주**(페일세이프) |

**끊긴 것 둘**

1. ★데이터→실행 추적이 백테스트 런에서 끝난다.★ `src/engine/run_evidence.py` 가
   가격·유니버스·매크로·재무 4축을 굴려 `pit_evidence` 를 내고
   `backtest_runs.is_pit_verified` 에 적지만, **그 빈티지 시점이 주문 제안까지 따라가지
   않는다**. `AuditTrail.log_signal()` 은 신호를 적지 그 신호가 **언제 알 수 있던
   데이터**였는지를 적지 않는다. 퀀팃식 `DataToExecutionTrace` 의 값어치가 여기다.
2. ★사유가 열거돼 있지 않다.★ `rebalance_policy` 가 만드는 `reason` 은 자유
   문자열이다. 화면·리포트·감사가 같은 사유를 **같은 이름으로** 부르지 못한다.

---

## 6. 연금·계좌 축 — `missing` (가장 큰 공백)

grep 결과 `IRP` · `ISA` · `연금` · `account_type` · `risk_tolerance` · `투자성향` ·
`글라이드` · `적립` 전부 **0건**이다. `contribution` 은 전부 *risk* contribution 이다.

| 없는 것 | 지금 그 자리에 있는 것 | 없어서 못 하는 것 |
|---|---|---|
| 계좌 유형(일반·연금저축·IRP·ISA) | `portfolios`(`username`+`ticker`) — **계좌 차원이 없다** | 계좌별 세제·상품 제약을 반영한 배분. 핀트의 축이 바로 이것이다 |
| `InvestorProfile` | `risk_aversion`·`horizon_days` 가 **요청별 인자** | 같은 사람에게 일관된 목표·위험 성향을 적용하지 못한다. ★코스콤 심사 항목에 "투자자 성향 분석 반영" 이 있다★ |
| 적립 스케줄러 | 없음(`apscheduler` 는 미사용) | 월 납입·정기 매수 |
| 글라이드패스 | 없음 | 은퇴 시점 기반 위험자산 축소 |
| 브로커 계좌 | 환경변수 **단일 계좌**(`KIS_ACCOUNT_NO`) | 다계좌 운용 |

---

## 7. 일일 설명 — `partial`

**있는 것** — `src/engine/attribution_decomposer.py` 가 5효과
(`allocation`/`selection`/`macro`/`netting`/`cost`)를 한국어 라벨과 함께 분해하고,
`multibacktest_daily` 가 일별로 그것을 적재한다. 화면도 있다
(`frontend/src/app/allocation/explain` · `journal`). 서술 생성기
`src/services/narrative/narrators` 에 `DailyNarrator` 가 있다.

**끊긴 것** — ⑴ 이 5효과는 **전략 수준**이고 **백테스트 안**에서 계산된다. 보유
자산의 하루를 설명하지 않는다. ⑵ ★가격·환율·배당·리밸런스 분해가 없다★ — 환효과와
배당효과는 저장소 어디에도 없다. ⑶ `realism_engine` 은 `selection_effect` 를
0 으로 둔다.

> 핀트의 "오늘 내 자산이 움직인 이유" 와 비교하면, 우리는 **연구 결과를 설명**하고
> 그쪽은 **고객 잔고를 설명**한다. 재료의 절반(배분·비용·매크로)은 이미 있다.

---

## 8. 유통·B2B — `missing`

마켓플레이스: `provider`·`subscription`·`scorecard` 어느 것도 없다. 다만 **자기
알파용 거버넌스**는 있다 — `alpha_registry` 의 5단계 승격과
`src/engine/strategy_health.py` 의 5상태(`healthy`/`watch`/`de_risk`/`paused`/
`retired`). ★후자는 핀트 셀렉션의 "수익률·안정성·운용 일관성 검증" 과 같은 종류의
물건이다★ — 대상이 자기 알파일 뿐이다. `auto_alpha` 는 후보를 만들되 `experimental`
위로 **자동 승격하지 않는다**(거버넌스 천장).

파트너 API: 테넌트·API 키 발급·레이트리밋·버전 계약 전부 없다. 라우트 버전 표기도
섞여 있다(`/api/v1/...` 과 무버전이 공존).

---

## 9. ★선행 조건 — 인증 계층이 통째로 없다★

§4·§6·§8 은 전부 *"누가 보느냐"* 가 정의돼야 성립한다. 실측한 현황:

| 확인한 것 | 결과 |
|---|---|
| `src/api/` 의 `Depends(` | ★0건★ |
| JWT 발급·검증(`jwt.`·`HTTPBearer`·`OAuth2`) | ★0건★ |
| 로그인·가입 라우트 | ★0건★ |
| `database.authenticate_user()` 호출부 | ★0건★ — 함수는 있는데 아무도 부르지 않는다 |
| `bcrypt` · `PyJWT` | requirements.txt 에 **선언돼 있다**(37·38행) |
| CORS | `CORS_ORIGINS` 에 `"*"` 가 들어 있고(`# 개발/배포 임시 허용`) `allow_credentials=True` |
| 사용자 지정 조회 | `GET /trade-history/{username}` — 경로 파라미터만으로 남의 기록 |

★이것은 갭이 아니라 블로커다.★ 멀티계좌 허브·마켓플레이스 구독·B2B 파트너 API 는
인증 없이는 **설계할 수는 있어도 켤 수 없다**. 그래서 로드맵에서 단계가 아니라
**선행 관문(P-1)** 으로 둔다.

**한계 표시** — 이 절은 `src/api/`·`src/app_factory.py` 를 훑은 결과다.
배포 단에 리버스 프록시 인증이 있을 수 있고, ★그건 이 저장소에서 확인할 수 없다.★
없다고 단정한 것은 **애플리케이션 코드 안**의 이야기다.

---

## ★이 감사가 주장하지 않는 것★

- **4사보다 낫다/못하다고 말하지 않는다.** 대상이 다르다 — 저쪽은 자문·일임
  제품이고 이쪽은 연구 플랫폼이다.
- **`missing` 을 "만들어야 한다" 로 읽지 않는다.** 순서와 선행 조건은
  [로드맵](../plans/2026-09-12-ra-product-roadmap.md)이 정한다. `missing` 중
  일부는 **인가 없이는 만들면 안 되는 것**이다.
- **`complete` 를 "투자에 쓸 수 있다" 로 읽지 않는다.** 기능이 있다는 뜻이고,
  ★이 저장소는 경제적 가치 관문을 통과한 적이 없다★(CLAUDE.md §1).
- **보안 감사를 한 것이 아니다.** §9 는 **한 가지 결여**를 관측한 것이고,
  취약점 전수 조사가 아니다.
