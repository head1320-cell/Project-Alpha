# Investment Decision Layer — 설계 명세

> Phase 2. 선행: Phase 0 감사(이 문서 §0 요약) · Phase 1 안 A 승인.
> 실측 기준 `0a300f7`. ★실데이터 검증은 GCP 이후★ — 이 문서의 모든 검증은 **E1(픽스처)** 다.

## 0. 왜 이 계층이 필요한가 — 감사가 찾은 것

★"결정 계층이 없다" 는 절반만 맞다.★ 원시함수는 대부분 있고 품질도 높다.
없는 것은 **결정이라는 객체와 그것을 잇는 합성**이다.

| # | 실측 |
|---|---|
| M1 | 결정 **객체** 없음 — Case 사슬이 `rgs_(증거) → tpv_(목표)` 로 **바로** 간다 |
| M2 | `rebalance_decision`(trade/hold/undetermined) 결과가 **어디에도 저장되지 않는다** |
| M3 | 결정 원시함수 8개가 전부 **호출부 1개 = API 라우트**. 도메인 합성 코드 0 |
| M4 | 기업 → 뷰 다리 **0개**, `company_snapshots` 에 `case_id` 없음 |
| M5 | ΔPortfolio 분해 없음 (자산별 기여만) |
| M6 | `decision_version` 축 없음 |

★이미 잘 갈라져 있는 것은 건드리지 않는다★ — `view_rows.build_view_rows` 가 P 행
단일 출처이고, `_conditional_views` 가 *"μ 를 optimizer 에 직접 대입하지 않는 이유가
이 함수의 존재 이유"* 라고 적어 뒀다. `signal → weight` 안티패턴은 **존재하지 않는다.**

---

## 1. 도메인 모델

```
investment_decisions              (부모 · 포트폴리오 1건)
├─ dec_id · as_of · case_id · scope · created_at
├─ decision_status  : trade | hold | undetermined
├─ gain_pct · cost_pct · hysteresis_mult · threshold_pct · net_pct   ★D1 정정★
├─ max_gap_pct · turnover_pct · portfolio_value
├─ gradual · triggers                                               ★D3 추가★
├─ belief     : {mu_source, prob_source, prob_usage, uncertainty_source, measured}
├─ evidence   : {mes_id, run_id, tpv_id, thesis_ids[], view_sources[]}
├─ provenance : {code_version, ruleset_version, decision_version, as_of}
└─ reason     (hold·undetermined 의 사유 — ★비면 안 된다★)

investment_decision_legs          (자식 · 자산별 N건)
├─ dec_id · ticker
├─ current_w · target_w · delta_w
├─ half_width_pct · low_pct · high_pct · outside_band                ★D2 정정★
├─ constraint_binding[]           (constrained_solve flow 에서 유도)
├─ view_refs[]                    (이 종목에 걸린 뷰의 출처: macro | company | user)
└─ contribution : {macro, company, risk_model, constraint}  ← ★대부분 null★
```

### ★S2 구현 중 확정된 사실 — leg별 제약 구속은 채울 수 없다★

`constrained_solve` 의 구속 목록은 `"종목 상한 40%"`·`"그룹 상한 IT 30%"` 같은
**포트폴리오 수준 문자열**이다. 어느 **종목**이 그 구속을 유발했는지는 재유도해야
알 수 있고 그것은 지어내기다.

→ 호출자가 준 목록은 부모의 `evidence.constraints_binding` 에 그대로 담고,
leg 의 `constraint_binding` 은 **빈 채로 둔다**. §5 귀속 표의 *"제약 기여 —
partially identifiable, 동시 구속은 분해 불가"* 와 같은 사실이다.

★`contribution` 이 대부분 `null` 인 이유★ — §5 의 식별 가능성 표가 근거다. 칸을
비워 두는 것이 없는 분해를 지어내는 것보다 낫다. `null` 옆에는 항상 사유를 둔다.

★두 층인 이유★ `rebalance_decision` 은 포트폴리오 단위 판단(총 효용개선 vs 총비용)
이고 `dynamic_band` 는 자산별이다. 한 층에 담으면 둘 중 하나의 입도가 왜곡된다.

---

## 1.1 ★S1 구현 중 발견한 스펙 결함 5건 (정정 완료)★

스펙 초안을 코드에 대고 다시 읽어 찾았다. ★필드명을 실측하지 않고 지어낸 것이
원인이다.★

| # | 초안 | 실측 | 위험 |
|---|---|---|---|
| **D1** | `benefit_bps·cost_bps·hysteresis_bps·net_bps` | `benefit.gain_pct` · `cost.cost_pct` · **`hysteresis_mult`(배수)** · `threshold_pct` · `net_pct` | ★단위가 percent 다 — 그대로 만들었으면 **100배 오류**★ |
| **D2** | `band_lo`/`band_hi` | `half_width_pct`·`low_pct`·`high_pct` | 이름만 틀림 |
| **D3** | (없음) | `triggers`·**`gradual`**·`max_gap_pct` | `gradual`("얼마나 움직일까")은 결정의 일부인데 빠졌다 |
| **D4** | 2테이블을 당연시 | 저장소에 2테이블 선례 **0**(`execution_store` 는 단일+JSON) | 사유 없이 패턴을 늘릴 뻔했다 |
| **D5** | `decision_version` 열거만 | 정의 없음 | 무엇이 값을 정하는지 불명 |

**D4 결론** — 그래도 둘로 간다. `execution_plans.plan` 은 **통째로 읽히지** 계획
**간** 질의 대상이 아닌 반면, 이 계층의 존재 이유는 결정 귀속이고 *"어느 종목이
가장 자주 밴드 밖이었나"* 는 결정 **간** 집계라 JSON 으로는 SQL 로 답할 수 없다.
`test_legs_can_be_aggregated_across_decisions` 가 그 이유를 못 박는다 —
★그 테스트가 사라지면 두 테이블일 이유도 사라진다.★

**D5 결론** — `DECISION_LOGIC_VERSION` 은 **결정 로직의 판본**이고 빌드 식별자
`code_version`(`research_context` 단일 출처 재사용)과 **다른 축**이다. 같은 값으로
두면 로직이 바뀌어도 기록이 그대로라 재현이 거짓말이 된다.

★교훈★ 상류 이름을 그대로 쓴다. 갈아 끼우면 상류가 바뀔 때 조용히 어긋난다.

---

## 2. 인터페이스

### 2.1 도메인 합성 함수 (M3 해소)

```python
# src/engine/investment_decision.py  ★신규 — 계산은 전부 기존 것을 부른다★
def decide(*, case_id, as_of, current_weights, target_weights, names,
           mu, sigma, portfolio_value, constraints_flow=None,
           evidence: dict, risk_aversion, horizon_days) -> dict:
    """증거 → 결정. ★새 최적화기·새 μ/Σ/Ω·새 제약 엔진 없음.★

    재사용: rebalance_policy.rebalance_decision · dynamic_band ·
            execution_plan.build_plan(비용) · constrained_opt flow(구속)
    """
```

라우트(`POST /allocation/rebalance-decision`)는 **이 함수를 부르기만** 한다.

### 2.2 기업 → 뷰 다리 (안 A)

```python
# src/engine/company_views.py  ★신규★
def company_views(codes, prices, *, as_of=None) -> tuple[list[dict], dict]:
    """밸류에이션 **분포** → 자산별 절대 뷰. 새 밸류에이션 모델을 짓지 않는다.

    valuation_distribution_for(code, price) →
        magnitude_pct = (p50 − price) / price × 100        기대수익
        direction     = sign(위 값)
        confidence    = f(P10~P90 폭)                       불확실성
    반환 두 번째는 **사유 맵** — 어느 종목이 왜 뷰를 못 냈는지.
    """
```

★출력 스키마는 매크로 뷰와 **완전히 같다**★ (`{assets, direction, magnitude_pct,
confidence, source, ...}`) → 기존 `build_view_rows` → 기존 Ω → BL/EP.
**새 뷰 스키마·새 P 빌더·새 Ω 를 만들지 않는다.**

#### ★S4 구현 중 실측이 이 절을 세 번 뒤집었다★

mock 3종(`005930`/`000660`/`035420`)에 `valuation_distribution_for` 를 돌려 봤다:

| 종목 | 가격 | p50 | 총 갭 | 상대폭 | `price_percentile` |
|---|---|---|---|---|---|
| 005930 | 70,000 | 35,534 | −49.2% | 32.7% | **100.0** |
| 000660 | 130,000 | 404,322 | +211.0% | 56.3% | **0.0** |
| 035420 | 200,000 | 108,792 | −45.6% | 45.7% | **100.0** |

**⑴ ★위 의사코드의 `magnitude_pct` 는 단위가 틀렸다.★** 밸류에이션 갭은 호라이즌이
없는 **총 갭**인데 뷰의 `magnitude_pct` 는 **연간**이다(`build_user_views` 주석 ·
μ 는 `R.mean×252`). `+211` 을 그대로 넘기면 "연 211% 기대수익" 으로 읽혀 BL 사후를
지배한다 — S2 가 `benefit_bps` 로 치를 뻔한 100배 오류의 **같은 계열**이다.
→ 밸류에이션 자신의 `projection_years`(현재 10)로 **기하 연율화**하고 그 기간을
`horizon_years` 로 뷰에 함께 싣는다. ★새 하이퍼파라미터를 발명하지 않는다★ —
저장소가 이미 고른 값이다. 실측 셋이 −6.6% / +12.0% / −5.9% 로 정상 범위에 든다.

**⑵ ★`confidence = f(P10~P90 폭)` 도 절반만 맞다.★** 폭만으로는 **방향 확신**을 못
잰다 — 가격이 p50 에 딱 붙은 좁은 분포는 폭이 작아도 확신이 0 이다. 그리고
`price_percentile` 은 셋 다 정확히 0.0/100.0 으로 **포화**했다(가격이 분포 밖).
→ 갭과 폭을 **함께** 쓰는 표준화 갭 `z = (p50 − price) / 반폭` 을 쓰고,
`conf = MAX × min(|z|, 1)`. `|z|=1` 은 "가격이 90% 구간 가장자리" 라는 뜻이라
앵커를 새로 고르지 않는다. 포화는 숨기지 않고 `confidence_saturated` 로 남긴다
(mock 셋은 |z|=5.9/2.4/3.7 로 **전부** 포화 — ★E0 산물이라는 사실 자체가 보고
대상★).

**⑶ ★`as_of` 는 흉내낼 수 없다.★** `company_snapshot_builder.publication_dates()`
가 이미 `has_vintage: False` 와 *"이 스냅샷은 backtest_eligible 이 될 수 없습니다"*
를 적어 뒀고, `valuation_distribution_for` 에는 `as_of` 인자 자체가 없다. 오늘
재무로 과거 뷰를 만들면 그것이 룩어헤드다. → `as_of` 가 오면 **뷰를 하나도 내지
않고** 사유를 돌려준다. 등급은 `pit_macro.derive_usage(has_vintage=False, ...)` 로
**파생**한다 — 손으로 `"forward_only"` 를 적으면 게이트가 거짓말을 할 수 있다.

**⑷ 상한 초과는 클램프하지 않는다.** 연율화 후에도 `AllocationView` 자신의 상한
(`le=50`)을 넘으면 **뷰를 내지 않고** 사유(`magnitude_out_of_range`)를 남긴다.
잘라 내면 50%/yr 짜리 뷰가 '정상 뷰' 로 위장한다.

**⑸ 불확실성 전달은 BL 전용이다.** `entropy_views` 가 `confidence_used: False` 를
이미 선언한다 — EP 의 부등식 뷰는 경성 제약이라 신뢰도를 쓰지 않는다. 즉 여기서
만든 신뢰도는 EP 경로에서 **아무 일도 하지 않는다**. 뷰의 `note` 가 그렇게 말한다.

### 2.3 활성화 — opt-in

`AnalyzeRequest.use_company_views: bool = False`.
★기본 거짓★ 이므로 기존 호출부·백테스트·골든이 **바이트 동일**하게 유지된다.
음성 통제는 이 플래그를 그대로 팔로 쓴다.

#### ★T1~T3 — S6 의 발견을 코드에 고정하고, 남은 것을 정직하게 적는다★

**⑴ ★자기참조 편익을 신고한다 — 규칙은 그대로.★** S6 의 "셔플 200개가 전부
`trade`" 를 실측이 설명했다: 편익은 `utility(w_target, μ) − utility(w_current, μ)`
인데 그 `μ` 가 **바로 `w_target` 을 고른 BL 사후분포**다(`opt["mu_used"]`).
`w_target` 은 그 μ 아래 효용 최대해이므로 **같은 μ 로 재면 이득이 구조적으로
보장된다** — 어떤 뷰든(진짜든 셔플이든) 자기 신념 아래서는 크게 이득이다.

★규칙 자체는 옳다★ 자기 사후분포 아래 기대효용은 의사결정 이론의 정석이다. 틀린
것은 응답이 그 숫자를 **독립적 증거처럼** 적는다는 점이다. 그래서 편익 산식을
건드리지 않고 `benefit.provenance` 와 저장되는 `belief.benefit_provenance` 에
`self_referential` · `evaluated_under` · 사유를 싣는다. 판정은 라우트가 이미 넘기는
`evidence["target_source"]`(`"optimize:*"` vs `"request"`)에서 **파생**한다.

★미상 ≠ 아니오★ 출처를 선언하지 않으면 `None` + 사유다. `False` 로 적으면 순환인
판단이 순환이 아닌 것처럼 기록된다(변이 M3 가 그 자리를 지킨다).

**⑵ 공시 비대칭을 없앴다.** `/rebalance-decision` 은 `mu_as_views=len(extra_views)`
를, `/analyze` 는 `opt["extra_views_used"]` 를 썼다. 조건부 뷰가 스킵되면(유니버스 밖
자산) 전자는 **쓰이지 않은 뷰를 쓰인 것으로 센다**. 후자로 통일했다.

**⑶ 결정 기록에 데이터 신선도.** 라우트가 이미 갖고 있는 `coverage`(`end` ·
`as_of_effective` · `source` · `n_obs`)에서 파생해 `evidence.data_freshness` 로
담는다. ★날짜를 못 구하면 `stale_days: None` + 사유★ — 0 으로 채우면 "오늘
데이터다" 로 읽힌다(변이 M7).

#### ★막힌 것 — 다음 세션이 또 파보지 않게★

| 항목 | 막은 것 | 종류 |
|---|---|---|
| P4 ETF 메타데이터 · P5 DART 공시 기업행위 | 제공자 키 | 외부(키가 오면 해제) |
| Track B B1/B2/B3/B5 | GCP 키 | 외부(키가 오면 해제) |
| 기업 뷰 ③ 예측 스킬 · ④ 경제적 가치 | 빈티지 재무 부재 → 표본외 수익 불가 | ★영구(제공자)★ |
| `weighting="hard"` 계약 강제 | 배분 정책 변경 | ★별도 승인 대기★ |
| `s_black_litterman` "중복" | — | ★문제가 아니었다★ — 8-ETF 전용 별도 전략이고 배분 경로에서 도달하지 않는다 |

#### ★S6 실측 — 음성 통제가 답한 것과 답하지 못한 것★

mock 8종목·BL·셔플 널 200회(가능한 치환 40,319개 중 표집):

| 통계 | 진짜 팔 | 널 min | 널 p50 | 널 max | 분위 | 방향 | 널 범위 밖 |
|---|---|---|---|---|---|---|---|
| `w_l1_vs_off` | 0.797 | 0.851 | 1.122 | 1.369 | **0.0** | below | ★예★ |
| `turnover_pct` | 65.79 | 66.75 | 105.14 | 138.99 | **0.0** | below | ★예★ |
| `corr_q_dw` | 0.808 | 0.239 | 0.723 | **0.833** | 96.5 | above | 아니오 |
| `max_weight` | 0.419 | 0.342 | 0.469 | 0.754 | 18.0 | inside | 아니오 |
| `enb` | 2.997 | 1.330 | 3.412 | 6.000 | 39.0 | inside | 아니오 |

**⑴ ★판단 층은 신호를 전혀 구분하지 못한다.★** 셔플 팔 **200개가 전부 `trade`**
를 냈고 진짜 팔도 `trade` 다. 즉 "거래할까 말까" 수준에서 결정 계층은 뷰의 내용에
**무등감**하다. `company-neutral`(내용을 상수로)만 `hold` 로 갈리므로, 갈리는 것은
"내용이 있는가" 이지 "그 내용이 무엇인가" 가 아니다. ★이것이 S6 의 핵심 산출이고
가중치 거리로는 보이지 않는다.★

**⑵ 전달 상관은 진짜 뷰를 구분하지 못한다.** `corr(Q, Δw)` 가 96.5분위로 임계치를
넘지만 ★널의 **max 가 진짜 팔보다 크다**★ — 무작위로 재배치한 뷰 중에 **더 강하게**
전달된 것이 있다. 그래서 `beyond_null_range: false` 를 분위와 **따로** 싣는다:
꼬리에 겨우 걸친 것과 널이 아예 도달하지 못한 것은 증거의 세기가 다르다.

**⑶ 구분된다는 것이 좋다는 뜻이 아니다.** 진짜 팔은 셔플 팔들보다 포트폴리오를
**덜** 움직였고(분위 0.0) 회전율도 낮았다. 방향(`side`)을 안 적으면 이 사실이
"통제를 통과했다" 로 둔갑한다.

**⑷ 두 채널이 죽어 있다.** 신뢰도가 전부 포화(50.0)라 `evidence-stripped` 가
`company-on` 과 **동일 입력**이고(`inert_channels` 로 신고), 무뷰 해가 균등가중이라
기준선이 **퇴화**했다(`baseline.degenerate`). 둘 다 E0 표본의 성질이다.

**⑸ ★이 하네스는 ③·④ 에 답하지 않는다.★** 기업 뷰는 `forward_only` 라 표본외
수익이 없다. `claims.predictive_skill`·`economic_value` 를 **`None` + 사유**로
구조적으로 비워 둔다 — 산문이 아니라 값으로(문장을 검사하는 테스트는 문장만 바꾸면
통과한다).

**⑹ 팔 변환은 프로덕션 옆에 두지 않는다.** `src/api/` 가
`company_view_controls` 를 import 하지 않는 것을 **정적으로 강제**한다 —
`OrderExecutor` 우회 방지 가드와 같은 장치이고, 가드가 실제 위반을 잡는지 확인하는
짝도 함께 둔다.

#### ★S5 구현 중 확정된 사실 — 공시가 거짓말을 할 참이었다★

**⑴ `optimize` 의 `extra_views_used` 는 길이로 세고 있었다.**

```python
"extra_views_used": len(extra_views or []) - (conditional 스킵)
```

이 수를 `/analyze` 가 `_mu_disclosure(mu_as_views=…)` 로 넘기고 그 문장이
*"조건부 μ 를 자산 **N개**의 절대 뷰로 태웠습니다"* 다. 회사 뷰가 같은 목록에
실리는 순간 **N 이 회사 뷰까지 센다** — 매크로가 하지 않은 일을 했다고 적는
조용한 거짓말이다. ★두 겹으로 막았다★:

1. **별도 인자** `optimize(company_views=…)` — 호출자의 의도가 코드에 드러나고
   회사 뷰 전용 카운트를 정직하게 낼 수 있다(계산 경로는 완전히 같다: 둘 다
   `all_views` 로 합쳐져 같은 Ω 를 탄다).
2. **출처로 세기** — 두 카운트를 **`all_views` 전체**에 대해 `source` 로 센다.
   그래서 누가 1번을 우회해 회사 뷰를 `extra_views` 에 섞어 넣어도 각 공시가 제
   몫만 센다. 사용자 뷰는 `source` 칸 자체가 없어 어느 쪽에도 잡히지 않는다.

기본값에서는 숫자가 바뀌지 않는다(`extra_views` 에는 조건부 뷰만 들어가고 전부
`source: "conditional"` 이다) — 짝 테스트가 그 불변을 못 박는다.

**⑵ 가격 해석을 세 번째로 만들지 않았다.** 저장소에 이미 두 벌이 있다
(`execution_plan._last_close` · `company_snapshot_builder._resolve_price`).
기업 도메인의 것을 쓴다 — ★"창의 끝은 **오늘**이어야 한다"★ 는 실측 교훈(2099년
종가 409원을 잡던 버그)을 담고 있고 출처 라벨까지 준다. `prices_for()` 는
**S4 의 `company_views()` 를 한 글자도 바꾸지 않는다** — 가격 자동 해석을 그 안에
넣으면 S4 가 못 박은 `KIND_NO_PRICE` 계약이 무너진다.

**⑶ 백테스트에는 새지 않는다.** `BacktestRequest` 는 `AnalyzeRequest` 를 상속하지
않고 `allocation_backtest._weights_at` 의 `optimize` 호출도 건드리지 않았다. 회사
뷰는 `forward_only` 라 과거 시뮬레이션에 들어가면 그 자체가 룩어헤드다.
★선언만 두지 않는다★ — `walk_forward` 를 실제로 돌려 `optimize` 가 받은 인자를
스파이로 검사하는 테스트가 있다.

**⑷ 남은 비대칭(고치지 않음).** `/rebalance-decision` 의 조건부 공시는
`opt["extra_views_used"]` 가 아니라 `len(extra_views or [])` 를 직접 쓴다. 회사
뷰가 그 목록에 들어가지 않으므로 지금은 오염되지 않지만, `/analyze` 와 세는
방식이 다르다. ★관측했고 이번 범위에서는 고치지 않았다★ — 기존 공시 숫자를
바꾸는 일이라 별개 판단이 필요하다.

### ★S3 구현 중 확정된 사실 — 기록도 opt-in, 그리고 모든 분기가 같은 키를 낸다★

**⑴ 결정 기록은 기본 꺼짐이다.** `/rebalance-decision` 은 UI 상호작용마다 불릴 수
있다. 저장소가 같은 우려를 이미 풀어 뒀다 — `AnalyzeRequest.record_run` 의 주석:
*"슬라이더 드래그마다 DB에 쓰지 않도록 명시 요청 시에만"*. 결정 계층도 **같은
모양**을 쓴다: `record_decision: bool = False`. ★변이 V1(항상 저장)이 `record_run`
이 막으려 한 바로 그것을 결정 계층에서 되살리는 변이이고, W1 이 그것을 죽인다.★

**⑵ `case_id` 를 요청 모델에 더했다.** `RebalanceDecisionRequest` 는
`AnalyzeRequest` 를 물려받아 `as_of`·`mes_id`·`regime_snapshot_id`·
`timing_rule_set_id`/`_version` 을 **이미** 갖고 있었다. 없던 것은 `case_id` 하나
(그 필드는 `TargetVersionRequest` 에만 있었다) — 결정을 Case 사슬에 걸려면 필요하다.

**⑶ `evidence.constraints_binding` 은 여기서 담지 않는다.** 이 라우트는
`optimize(...)` 만 부르고 `constrained_solve` 를 부르지 않는다(그것은 `/analyze`).
★없는 것을 담지 않는다.★

**⑷ `legs` 는 응답에 싣지 않는다.** 저장 관심사다. 화면에는 `band.by_asset` 이 이미
같은 정보를 준다 — 두 벌을 실으면 화면이 어느 쪽을 믿을지 갈린다.

**⑸ ★조기 반환 분기도 같은 키를 낸다.★** 자산이 2개 미만이면 라우트는 결정 계층에
**닿기 전에** 반환한다. 그 응답이 `dec_id`/`persisted`/`persist_reason` 을 빼먹으면
소비자가 `.get()` 으로 읽다가 `None` 을 거짓으로 취급한다(레지스트리
`not_ingested` 가 같은 이유로 모든 분기에서 나온다). 그 분기는 **기록되지 않는 것이
맞다** — 문제를 세울 수조차 없었으므로 기록할 판단이 없고, `persist_reason` 이 그
사실을 말한다.

**⑹ ★`None` 을 돌려주는 실패와 예외를 던지는 실패는 다르다.★** 처음 쓴 저장-실패
테스트는 `_engine` 이 `None` 인 경로만 지났고, 그때 스토어는 방어적으로 `None` 을
돌려주므로 `decide()` 의 `try/except` 는 **한 번도 실행되지 않았다** — 그 `except`
를 지워도 테스트는 통과했다(변이 V6 **생존**). 그런데 라우트의 바깥 `except` 는
예외를 **500** 으로 바꾼다: 이미 난 판단까지 잃는다. 예외를 던지는 스토어에 대한
짝 테스트를 더해 그 경로를 실제로 지나게 했다.

---

## 3. 데이터 흐름

```
[증거]  MES(rgs_) · ResearchRun(rr_) · thesis · 가격
           ↓
[믿음]  매크로: regime_path → conditional_moments(μ,Σ) → _conditional_views
        기업  : valuation_distribution_for → company_views      ← 신규, opt-in
           ↓
[구성]  build_view_rows → Ω → BL/EP → optimizer → constrained_solve → target_w
           ↓
[결정]  decide(current_w, target_w, μ, Σ, 비용, 구속, 증거)
           → investment_decisions + legs   ← ★신규 영속★
           ↓
[실행]  build_plan → pre_trade_checks → order_executor
           ↓
[사후]  compute_attribution · journal_store  (dec_id 로 연결)
```

---

## 4. 불확실성 — ★어디서 오고, 무엇이 측정된 것인가★

| 출처 | 측정 여부 | 근거 |
|---|---|---|
| 매크로 μ/Σ 산포 | 부분 | `conditional_moments` 표본, `_shrunk_cov` λ |
| 국면 확률 | **계약 있음** | `RegimeProbabilities.usage`. 단 `weighting="hard"` 는 계약 우회(§6) |
| Ω (뷰 신뢰도) | 유도 | `view_omega_terms` + `implied_confidence` |
| **기업 밸류에이션 폭** | ★**측정 안 됨**★ | `repo_widths()` 가 스스로 적어 뒀다 — *"이 폭 중 측정된 것은 하나도 없다 … β 와 상관계수는 순수한 가정이다"*, 각 항목 `"measured": False` |

★그래서 결정 객체는 `belief.uncertainty_source` 와 `belief.measured` 를 **함께**
싣는다★ — 기업 뷰의 confidence 는 *가정된 폭*에서 나온 것이고, 그 사실을 전파하지
않으면 §18 의 "confidence 날조" 를 한 단계 건너뛰어 저지르는 것이 된다.

---

## 5. 귀속 경계 (§10) — 지어내지 않는다

| 성분 | 판정 | 이유 |
|---|---|---|
| 자산별 수익 기여 · 사전/사후 · 비용 | **supported** | `attribution` · `build_plan` |
| 제약 기여 | **partially** | `flow` 전후 차분 가능. **동시 구속**은 분해 불가 |
| 매크로 기여 | **partially** | `-const` 가 타이밍/수준은 가름. 국면↔Ω↔공분산 동시 변동은 불가 |
| 기업 기여 | **partially** (신규) | `company-on/off/neutral` 팔로 **가를 수 있게 된다** |
| 리스크모델 기여 | **not identifiable** | 공분산만 고립시키는 팔 없음 |
| 실행 효과 | **partially** | dec_id ↔ 체결 연결이 생기면 개선 |

---

## 6. 오류·폴백 의미론

- ★`undetermined` 는 실패가 아니라 답이다★ — 편익을 계산할 수 없으면 거래를
  권하지 않는다. 사유 필수.
- 기업 뷰: DART 키 없음·재무제표 없음·분포 무효 → **뷰 0개 + 종목별 사유**.
  ★0 으로 채우지 않는다★(중립 뷰도 만들지 않는다 — 그것은 정보다).
- 증거 참조가 깨지면 **계산 전에** 거부(`/analyze` 의 기존 관례와 동일).
- 결정 저장 실패가 계산을 되돌리지 않는다. 대신 `persisted:false` + 사유를 낸다.

---

## 7. 테스트 전략

**계약** 부모/자식 불변식 · 모든 분기가 `decision_status`·`reason` 을 낸다 ·
`undetermined` 전파 · provenance 완전성 · Case 사슬 왕복.

**★음성 통제★** (§13)

| 팔 | 무엇을 가르나 |
|---|---|
| `company-on` / `company-off` | 기업 뷰의 기여 |
| ★`company-neutral`★ magnitude=0, **같은 Ω** | 뷰 **기하** vs 기업 **정보** |
| `company-shuffled` 종목 라벨 셔플 | 정보인가 분산 효과인가 |
| `macro-on/off/-const` | 기존 팔 재사용 |
| `evidence-stripped` | 증거를 지우면 `undetermined` 로 떨어지는가 |

★`company-neutral` 이 핵심★ — 뷰를 넣는 행위 자체가 Ω 를 통해 포트폴리오를
움직인다. 그것을 빼지 않으면 "기업 리서치가 기여했다" 를 잘못 말한다
(`-const` 가 국면에서 막은 것과 같은 계열).

**변이** 기업 뷰가 confidence 를 상수로 · 분포 폭을 무시 · `measured` 라벨 누락 ·
`hold` 를 저장 안 함 · opt-in 기본값이 참 · 밴드를 고정 ±5% 로.

**불변** `use_company_views=False` 에서 `/analyze`·`walk_forward`·골든 3종이
**바이트 동일**.

---

## 8. 실데이터 경계

★이 사이클 범위 밖★ — KRX·KIS·FRED/ALFRED·ECOS·DART 실적재/검증 · 증거등급 상향 ·
예측 스킬·알파·라이브 성과 주장.

현재 실측: 제공자 키 **8개 전부 미설정**, FRED/ECOS 호스트 도달 불가,
`real_share=0.0`, 빈티지 0건, capability **L1**. ★DART 키가 없으므로 기업 뷰는 이
환경에서 **구조적으로 0개**★ — `load_statement` 의 mock 게이트를 그대로 물려받는다.

**GCP 후 검증할 것**: 기업 뷰가 실제로 몇 종목에 붙는가 · 분포 폭이 현실적인가 ·
결정이 `trade` 로 바뀌는 빈도 · 음성 통제가 실데이터에서도 가르는가.

---

## 9. 하지 않는 것

새 최적화기 · 새 μ/Σ/Ω · 새 제약 엔진 · 새 기업 점수 체계 · ΔPortfolio 분해
(식별 가능성 논증 전) · Ω/BL 이중화 정리(별도 항목으로 기록) · 무관 모듈 리팩터 ·
`weighting="hard"` 계약 강제(별도 승인).
