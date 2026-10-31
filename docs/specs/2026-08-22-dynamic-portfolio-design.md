# Dynamic Portfolio Decision Engine — 설계

> 감사: [`2026-08-22-dynamic-portfolio-audit.md`](./2026-08-22-dynamic-portfolio-audit.md).
> **설계다. 구현은 승인 후.** Brief §20 의 작업 순서를 따른다.

## 0. 설계 원칙 — Brief 가 이미 정해 준 것

Brief §18: **"새 fancy model(Neural SDE/TSFM/PINN 등)을 먼저 추가하지 않는다.
현재의 모델들을 실제 portfolio decision pipeline 에 연결하는 것이 우선이다."**

감사가 이 지시를 뒷받침한다 — 없는 것은 모델이 아니라 **연결**이다. k-step 국면예측 ·
불일치 · EP/BL · 반사실 귀인 · EWMA 조건부 Σ 가 전부 이미 있는데 배분 결정에
닿지 않는다.

그래서 이 설계는 **엔진을 짓는 문서가 아니라 배선을 놓는 문서**다.

---

## 1. `PortfolioDecisionState` — 새로 발명하지 않는다

이 저장소에는 검증된 불변 상태 객체가 **둘** 있다:

| 기존 | 담는 것 | 관례 |
|---|---|---|
| `regime_snapshots.py` (MES, `rgs_*`) | as_of · 두 축 · 국면확률 · stress · confidence · observations · **조각별 `{available, reason}`** · capability_level | `_engine()` → `_ensure_table()` → raw SQL · write-once · ADD COLUMN 확장 |
| `target_versions.py` (TPV, `tpv_*`) | base/overlay/final 비중 · cash · status(`executable`/`research_only`) · 사유 · run/snapshot/ruleset/pack 사슬 | 동일 |

`PortfolioDecisionState`(`pds_*`)는 **셋째 테이블을 만들되 앞의 둘을 대체하지 않는다.**
TPV 는 계속 "실행이 보는 유일한 목표" 이고(R0 계약), PDS 는 **그 목표가 어떻게 나왔는지의
결정 상태**를 담는다. TPV 를 **감싸지 대체하지 않는다.**

| 컬럼 | 내용 | 출처 |
|---|---|---|
| `pds_id` · `created_at` · `code_version` | 신원·감사 | — |
| `as_of` | **정보집합 시각** — 이 시각 이후 정보는 안 쓴다 | Brief §7.4 |
| `case_id` · `mes_id` | 케이스·매크로 증거 | M1 사슬 |
| `universe_version` | 그 시점 투자가능 목록 | `tickers_asof` 관례 |
| `holdings` | 현재 보유 | 세션 |
| `regime` | 현재 분포 + **k-step 포워드 분포** + 전이행렬 + 기대지속 | `regime_transitions` **재사용** |
| `conditional` | **μ · Σ · tail** + `{available, reason, n_obs, method}` | §2 신규 |
| `views` | 사용자 뷰 | `build_user_views` |
| `optimizer` | 모델·제약·리스크버짓 | `allocation_studio` |
| `target` | **점 비중 + range + confidence** | §3 신규 |
| `dispersion` | 모델 간 불일치 | `allocation_studio.target_weight_range()` — §3 정정 참조 |
| `rebalance` | 거래 판정 + 사유 + 밴드 | §4 신규 |
| `tpv_id` | 컴파일된 목표 버전 | `target_versions` |

★조각별 `{available, reason}` 을 그대로 쓴다★ MES 가 세운 규칙 — **키는 값이 없어도
존재하고, 없으면 사유가 있다.** 조건부 μ 가 표본 부족으로 못 나오면 `0` 이 아니라
사유가 들어간다.

---

## 2. 조건부 μ/Σ — ★표본이 설계를 결정한다★

Brief 가 "가장 중요한 신규 엔진" 이라 부른 것. 그런데 **먼저 표본을 세야 한다.**

| 실측 | 값 |
|---|---|
| 매크로 시계열 깊이(mock) | **60개월** (`macro_collector.py:585 length=60`) |
| 실 키 기본 깊이 | **240개월** (`MACRO_HISTORY_YEARS=20`, `:67`) |
| 국면 수 | 4 |
| 매크로 자산 유니버스 | **8** (`risk_allocations.py:31` SPY·EFA·EEM·TLT·IEF·GLD·PDBC·VNQ) |

→ 국면당 관측: mock **~15** · 실 키 **~60**.
8자산 공분산은 자유도 36개를 요구한다. **국면당 15 관측으로는 Σ 가 특이에 가깝다.**

A8 이 4상태 HMM(관측 48 / 모수 32)을 과적합으로 기각한 것과 **같은 표본 문제**다.
같은 판단을 여기서도 한다:

### 설계 결정 셋

1. **축소추정(shrinkage)을 기본값으로.** Ledoit-Wolf 형태의 대각/평균상관 목표로
   수축한다. numpy/scipy 로 충분 — 새 의존성 0.
2. **표본 하한을 게이트로.** 국면당 관측 < `k · n_assets` 이면 **숫자를 내지 않고
   사유를 반환**한다. 이것이 정직성 급소다 — 국면별 μ 는 표본이 얇을수록 매력적으로
   보이는 방향으로 틀리기 쉽다.
3. **조건부 Σ 를 백지에서 짓지 않는다.** `regime_adaptive_allocator` 의 EWMA(λ=0.85)와
   상관붕괴 진단(클러스터 수 · 평균 상관 · 최대 고유값 비중)을 **추출해 자산 레벨에서
   재사용**한다. 두 계통을 합치지는 않는다(소비자·계약이 다르다).
4. **μ 는 Σ 보다 더 보수적으로.** 기대수익 추정오차가 최적화 결과를 지배한다는 것은
   잘 알려져 있다. 국면조건부 μ 는 **뷰로 취급해 EP/BL 을 통과**시킨다 —
   `ep_posterior_mu()`(M2-A)가 이미 그 자리를 갖고 있고, 그러면 매크로가 **사전분포를
   덮어쓰지 않고 갱신**한다.

★★이 결정 4가 이 문서에서 가장 중요한 한 줄이다★★ 매크로를 μ 에 **직접 대입**하면
"매크로 신호 → 비중" 이라는 지금 구조를 이름만 바꿔 되풀이한다. 뷰로 태우면
불확실성이 명시되고, 뷰가 사전분포보다 강하면 **ENS 붕괴로 드러난다**(M2-A 가
이미 그 진단을 낸다).

### 인터페이스

```
conditional_market_model(mes_id | regime_probs, returns, as_of)
  → {available, method, n_obs_per_regime,
     mu:  {asset: annual} | None,
     sigma: [[...]] | None,
     tail: {...} | None,
     shrinkage: float, reason?: str}
```

`available:false` 이면 **호출부는 무조건부 경로로 폴백하되 화면에 그 사실을 적는다** —
조용한 폴백은 금지(M2-A 의 `feasible:false` 처리와 동일 원칙).

---

## 3. Target range — 이미 있는 불일치에서 유도한다

Brief §9: 점 비중 하나가 아니라 `target · low/high · confidence · dispersion`.

**새 통계를 만들지 않는다.** 이미 있는 것을 쓴다:

1. 같은 입력을 **여러 모델**로 푼다(MVO/BL/EP/HRP/MinVar — 전부 존재).
2. 자산별 비중 분포의 산포가 곧 `range`.
3. ~~`ensemble.disagreement()`(정규화 엔트로피)로 **합의도**를 낸다~~
   **★구현하며 정정(2026-08-22)★** 이 재사용은 **불가능하다.**
   `macro_models/ensemble.disagreement(verdicts: list[str])` 는 **범주형 판정**의
   정규화 엔트로피다. 가중치 산포는 수치이므로 그 함수로 잴 수 없다. 함수 이름이
   맞아 보였을 뿐 계약이 다르다 — 재사용을 계획할 때 시그니처를 보지 않은 것이
   원인이다. `disagreement()` 는 매크로 탭에서 하던 일을 계속한다.
   → 대신 `allocation_studio.target_weight_range()` 가 자산별 `[min, max]` 와 산포
   스칼라(자산별 폭의 평균·최대)를 직접 낸다. 20줄이고 새 의존성은 없다.
4. `confidence` 가 낮으면 **range 를 넓히고 §4 의 이동폭을 줄인다**(Brief §9 마지막 줄).

★평균으로 접지 않는다★ Brief §13 · CLAUDE.md 의 일관된 원칙. 모델별 원값을 남긴다.

---

## 4. Rebalancing Policy Engine — 없는 것 중 가장 값싼 것

지금은 `build_plan()`(`execution_plan.py:49`)이 목표비중을 받아 **곧장** 주문을 만든다.
그 **앞에** 판정 층을 하나 넣는다. `build_plan` 은 손대지 않는다.

```
rebalance_decision(current, target_range, cost_model, state)
  → {trade: bool, reason, band, moved_fraction, expected_gain, expected_cost}
```

규칙(Brief §10):

- `거래 = 기대효용개선 > 거래비용 + 히스테리시스`
- `band = f(cost, vol, uncertainty, liquidity, persistence)` — **고정 ±5% 를 기본값으로
  두지 않는다**(Brief 명시).
- 신뢰도가 낮으면 부분 이동: `trade_target = current + α(confidence)·(target − current)`.
- 비용 모델은 **이미 있다** — `build_plan` 이 수수료·세금·스프레드·시장충격
  (`market_rules`)을 계산한다. 그것을 **판정에 재사용**한다.

★거래하지 않기로 한 결정도 기록한다★ PDS 에 `trade:false` 와 사유가 남아야
"왜 안 바꿨는가" 를 나중에 되짚을 수 있다. 저널이 이미 그 자리를 갖고 있다.

---

## 5. 경제노출 ↔ 상품 분리

Brief §7.1 · `.md` §26. 지금은 optimizer 가 **상품**(SPY·VNQ…)을 직접 최적화한다.

```
경제노출(equity_dm · equity_em · duration · credit · inflation · commodity · reit · cash)
   ↓  optimizer 는 여기까지 결정한다
상품 선택기(유동성 · 스프레드 · 추적오차 · 보수 · 상장상태 · 거래이력)
   ↓
실제 상장상품(KR ETF)
```

- 매핑 원천은 **이미 있다** — `etf_prices.py` 의 미국 티커 ↔ KR ETF 딕셔너리.
  평면 딕셔너리를 **2계층으로 승격**하는 일이지 새 데이터가 필요한 일이 아니다.
- ★첫 수정 대상★ `etf_prices.py:65` 가 `VNQ`(리츠)와 `REM`(모기지 리츠)을 같은
  종목에 매핑한다. 분리 계층이 생기면 이 충돌이 **드러나서 고쳐진다.**
- **생존편향**: 시점 t 의 투자가능 목록은 `tickers_asof()` 관례를 따른다(이미 있음).

---

## 6. ★첫 수직 슬라이스★ (Brief §20 이 지정)

```
Macro State/Regime  →  조건부 μ/Σ  →  optimizer  →  target range
```

**이 슬라이스만 한다.** 리밸런싱 정책(§4)과 노출↔상품 분리(§5)는 다음 슬라이스다.

고른 이유: 감사가 찾은 **"파이프는 깔렸는데 안 흐른다"** 를 정확히 닫는 최소 조각이고,
`mes_id` 배선(M2-B)·EP 경로(M2-A)·`build_user_views`/`bl_posterior` 가 이미 있어
**새로 짓는 것이 조건부 추정기와 산포 계산 둘**뿐이다(당초 "하나" 로 적었으나,
위 §3 정정에 따라 산포는 재사용이 아니라 신규다).

### 수용 기준

1. **★같은 입력에 국면을 바꾸면 μ 가 실제로 달라진다★** — 안 달라지면 배선이 또
   도장만 찍는 것이다. (짝 단언: 국면을 안 주면 기존 무조건부 결과와 **바이트 동일**.)
2. **표본이 얇으면 숫자가 아니라 사유가 나온다** — 국면당 관측 < 하한이면
   `available:false` + `n_obs_per_regime`.
3. **조용한 폴백 금지** — 무조건부로 떨어지면 화면이 그 사실을 말한다.
4. **target range 가 모델 산포에서 나온다** — 모델 하나만 가용하면 range 없이
   그 사실을 적는다(가짜 구간 금지).
5. 기존 8개 모델의 무조건부 결과가 **한 자리도 바뀌지 않는다**.
6. pytest / Playwright 감소 없음.

### 변이 프로브 (승인 후)

| 되돌릴 것 | 빨개져야 할 것 |
|---|---|
| 조건부 μ 를 무조건부로 고정 | 1 |
| 표본 하한 게이트 제거 | 2 |
| `available:false` 에서 조용히 폴백 | 3 |
| 모델 1개로 range 를 지어냄 | 4 |

---

## 7. 하지 않는 것

- **AI 가 최종 비중을 정하는 것**(Brief §17). AI 는 뷰 제안까지고, `agentic_views` 의
  텍스트→뷰 단계는 지금 `available:false` 다 — 그 상태를 유지한다.
- **새 fancy model**(Neural SDE · TSFM · PINN · RL) — Brief §18 이 명시적 후순위.
- **baseline 폐기** — `macro_allocation.py` 의 선형 4계절 틸트는 **벤치마크로 유지**
  (Brief §2 명시).
- **두 배분 계통 통합** — 로직을 추출해 재사용하되 계통을 합치지 않는다.
- **TPV 대체** — PDS 는 감싼다. 실행이 보는 목표는 계속 TPV 하나다(R0 계약).
