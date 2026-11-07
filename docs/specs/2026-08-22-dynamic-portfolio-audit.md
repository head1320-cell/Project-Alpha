# Dynamic Portfolio Decision Engine — 감사

> `Project_Alpha_Dynamic_Portfolio_Design_Brief.md` 에 대한 1단계 감사.
> **프로덕션 코드는 한 줄도 바뀌지 않았다.** 설계는 별도 문서
> [`2026-08-22-dynamic-portfolio-design.md`](./2026-08-22-dynamic-portfolio-design.md).

## 0. 한 문장

★파이프는 깔렸는데 아무것도 흐르지 않는다.★ M2 가 `mes_id` 배선을 이미 놓았지만
그것이 하는 일은 **능력 레벨을 도장 찍는 것뿐**이고, 국면 확률·축 점수·스트레스는
μ 나 Σ 에 **한 번도 닿지 않는다.**

---

## 1. Brief §2 의 주장을 코드로 검증했다 — 사실이다

Brief 는 현재 시스템이 `Macro → Signal/Recommendation → Weight` 이지
`Macro → 조건부 분포 → Optimizer → Weight` 가 아니라고 했다. 줄 번호로 확인된다.

| 확인 | 위치 |
|---|---|
| 공분산이 **무조건부 트레일링** — `S = _cov(R) * 252.0` | `allocation_studio.py:170` |
| μ 는 트레일링 평균 · BL 사후 · EP 사후뿐. **전부 사용자 뷰에서 오고 매크로에서 오지 않는다** | `allocation_studio.py:196` · `:254` |
| **`mes_id` 는 `capability_level`/`capability_reason` 을 스탬프만 한다** | `allocation_routes.py:402-417` |
| 매크로가 비중을 **직접** 만드는 별도 경로(선형 4계절 틸트) | `macro_allocation.py:53 macro_embedded_allocation()` |

`allocation_routes.py:410` 의 주석이 그 사실을 스스로 적어 두었다 —
"여기서는 **고정 시점의 해석**을 스탬프할 뿐".

### 핸드오프는 있다 — 무엇을 나르는지가 문제다

```
MacroCockpit "Allocation Studio에서 열기"   widgets/macro/MacroCockpit.tsx:67
  → 서버에 스냅샷 생성(regime_snapshots, rgs_*)
  → /allocation/macro?snapshot=<id>          app/allocation/macro/page.tsx:4
  → AAS 세션이 스냅샷을 참조(값 복사 아님)
  → run_analyze(mes_id=…)                    allocation_routes.py:402
       ↳ capability_level 스탬프.  μ·Σ 에는 영향 0.
```

Brief §15 가 요구한 "단순 추천 ETF 100% prefill 이 아니라 전체를 전달" 은 **경로로는
이미 성립**한다(스냅샷 ID 참조). 그러나 받은 쪽이 그것을 **분포로 바꾸지 않는다.**

---

## 2. 이미 있어서 다시 짓지 않을 것

★1차 grep 이 이 중 여럿을 0건으로 잘못 셌다★ 파일 단위로 다시 확인했다.
(지난 세션 Company ROIC 와 같은 실수 계열이라 기록한다 — 좁은 정규식 하나로
"없다" 를 결론짓지 않는다.)

| Brief 요구 | 실재 | 위치 |
|---|---|---|
| 포워드 국면분포 (1M/3M/6M) | **있음** — Dirichlet 사후예측 k-step | `regime_transitions.k_step_forecast()` |
| 전이행렬 · 신용구간 · 기대지속 | **있음** | `transition_posterior()` · `current_run_length()` |
| 국면 예측 불확실성 | **있음** — 예측집합 + **실측 커버리지** | `regime_forecast.prediction_set()` · `forecast_coverage()` |
| 모델 불일치를 평균으로 숨기지 않기 | **있음** — 정규화 엔트로피 | `macro_models/ensemble.disagreement()` |
| Entropy Pooling / BL | **있음** | `entropy_pooling.py` · `entropy_views.ep_posterior_mu()` |
| 반사실 귀인 | **있음** | `counterfactual_analyzer.py` (6파일 참조) |
| baseline 4계절 틸트 (버리지 말 것) | **있음** | `macro_allocation.py` |
| walk-forward OOS | **있음** | `allocation_backtest.walk_forward()` |
| 국면 앙상블(축·Markov·GMM) | **있음** | `regime_ensemble.py` |
| conformal | **있음** | `conformal.py` (M2-C 가 정책 백테스트에 연결) |
| 결정 재현(불변 스냅샷·버전) | **있음** | `regime_snapshots` · `target_versions` · `research_runs` |

**즉 Brief 의 P1 항목 상당수가 이미 구현돼 있다.** 없는 것은 **그것들을 배분
파이프라인에 잇는 층**이다.

---

## 3. 진짜로 없는 것

| Brief 요구 | 실측 | 심각도 |
|---|---|---|
| **조건부 μ/Σ/tail** `r_{i,t+1} \| state_t, regime_t` | **0건** | **최상** — Brief 가 "가장 중요한 신규 엔진" 이라 부른 것 |
| **Target range** (목표 + 상하한 + 신뢰도) | **0건** — `optimize()` 는 점 비중 하나 | 상 |
| **Rebalancing Policy Engine** | **0건** | **상** |
| 연속 risk budget ∈ [0,1] | 사실상 없음(이진 타이밍) | 중 |
| **경제노출 ↔ 상품 분리** | **0건** | 상 |
| optimizer 수준 model dispersion → position sizing | 없음(불일치는 매크로 탭에만) | 중 |
| forecast combination (precision-weighted) | 없음 | 중 |

### 3.1 리밸런싱 — 거래 **여부**를 아무도 판단하지 않는다

`execution_plan.build_plan()`(`:49`)은 목표비중을 받아 **곧장** 주문 diff·비용·참여율을
만든다. 없는 것:

- 노-트레이드 밴드 / 히스테리시스
- `거래 = 기대효용개선 > 거래비용` 판정
- 신호 지속성·불확실성에 따른 부분 이동(`α(confidence)`)

즉 목표가 0.3%p 움직여도 주문이 나간다. Brief §10 이 "매우 중요" 라고 표시한 자리다.

### 3.2 유니버스 — 증상이 데이터에 남아 있다

`etf_prices.py:65` 가 **`VNQ`(미국 리츠)와 `REM`(모기지 리츠)을 같은 종목
182480(TIGER 미국리츠)** 에 매핑한다. 서로 다른 경제노출이 한 상품으로 접힌다.
분리 계층이 없다는 사실이 데이터에 그대로 드러난 자리다.

매크로 자산군은 미국 티커 프록시(`SPY`·`TIP`·`GLD`·`DBC`·`VNQ`·`BIL`,
`macro_visuals.py:95` · `risk_allocations.py:31`)로 표현되고, optimizer 는
경제노출이 아니라 **상품**을 직접 최적화한다.

---

## 4. ★배분 계통이 둘이다 — 통합 판단★

| 계통 | 구성 | 소비자 | 조건부 Σ |
|---|---|---|---|
| **AAS** | `allocation_studio.py` — MVO/BL/EP/HRP/RP/MinVar/MaxDiv/MinCVaR | Allocation Studio 11스테이지 | **없음**(무조건부 트레일링) |
| **다전략** | `MultiStrategyAllocator` + `regime_adaptive_allocator.py` | `realism_engine` · `stage12_routes` | **있음 — EWMA(λ=0.85) + 상관붕괴 감지 + 3모드** |

★후자에 Brief 가 원하는 것의 절반이 이미 있다★ `RegimeAdaptiveAllocator` 는
리스크 수준에 따라 **NORMAL / CAUTIOUS(EWMA Σ) / DEFENSIVE(하드캡+현금버퍼)** 로
갈리고, 클러스터 수·평균 상관·최대 고유값 비중으로 **상관붕괴를 감지**한다.

**판단**: 새 조건부 Σ 엔진을 백지에서 짓지 않는다. 이 계통의 **EWMA·상관진단 로직을
추출해 자산 레벨에서 재사용**하고, AAS 의 `S = _cov(R)*252` 자리에 주입 가능한
형태로 만든다. 두 계통을 합치지는 않는다 — 소비자와 계약이 다르다.

---

## 5. Brief 대비 gap matrix 요약

| 축 | 있음 | 부분 | 없음 |
|---|---|---|---|
| Macro 상태추정 | 축·Markov·GMM · 드라이버 Shapley · 전이·k-step · 불일치 | 상태벡터가 성장·물가 중심(유동성·정책·신용은 개별 지표로만) | — |
| 조건부 시장모형 | — | 다전략 계통의 EWMA Σ | **조건부 μ · 조건부 상관 · tail** |
| 뷰/사전분포 | BL · EP · 뷰 컴파일러 | — | AI 뷰 제안(텍스트→뷰는 `available:false`) |
| 최적화 | 모델 8종 · 제약 · 롱숏(연구) | — | **robust(불확실성 집합)** · 팩터 인지 |
| 목표 | 점 비중 | — | **range · dispersion · confidence** |
| 리밸런싱 | 주문 diff · 비용 · 참여율 | — | **정책 엔진 전체** |
| 실행 | TPV 게이트 · paper-only | — | — |
| 평가 | walk-forward · conformal · 반사실 | — | 정책 수준 비교 UI |
| 재현 | 불변 스냅샷 · 케이스 사슬 · reproduce | — | — |

---

## 6. 이 감사가 **반증한** 것

- "핸드오프가 ETF 100% prefill 이다" — **아니다.** 스냅샷 ID 참조로 이미 넘어간다.
- "포워드 국면분포가 없다" — **있다**(`k_step_forecast`).
- "모델 불일치를 평균으로 숨긴다" — **숨기지 않는다**(`disagreement()`).
- "반사실 귀인이 없다" — **있다**(`counterfactual_analyzer.py`).

문제는 이 조각들이 **없다는 것이 아니라, 배분 결정에 연결되지 않았다는 것**이다.
Brief §18 이 "새 fancy model 을 먼저 추가하지 않는다 — 현재 모델들을 실제 portfolio
decision pipeline 에 연결하는 것이 우선" 이라고 한 것과 정확히 일치한다.
