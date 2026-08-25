# 매크로 리서치 감사 — Phase 0 (프로덕션 코드 변경 없음)

> 출처: `docs/Project_Alpha_Macro_Research_Spec.md` §28 Phase 0 · §30 · §31
> ★스펙 §2 의 규칙을 따랐다★ — *"이름에서 동작을 추론하지 말고 실제 구현을 매핑하라."*
> 아래 수치는 전부 **재실행 가능**하다. 각 절에 명령을 함께 적는다.

## 0. 한 문장

> 대체(substitute) 엔진들은 **진짜 모델이고 규율도 있다**. 문제는 그 위가 아니라
> **옆과 아래**다 — 스튜디오가 포트폴리오에 연결돼 있지 않고(결정가치를 잴 대상이
> 없다), PIT 계약이 모델에 닿지 않으며, LATENT 은 이름이 주장하는 것을 내지 않는다.

---

## 1. 현재 코드 맵

```
src/engine/macro_models/          920줄 (전부)
├── base.py            166  스튜디오 계약 · 레지스트리 · load_series
├── tsfm_latent.py     125  LATENT   — statsmodels DynamicFactor
├── neural_sde.py      135  TERM     — Nelson-Siegel 3요인
├── causal_deepm.py     63  CAUSAL   — causal_graph.granger_edges 위임
├── pinn_tail.py       131  TAIL     — scipy genpareto (POT/GPD)
├── ensemble.py        135  범주형 판정 불일치 집계
└── agentic_views.py   147  뷰 → 부등식 컴파일 (엔트로피 풀링용)
```

**소비자**
| 소비자 | 무엇을 쓰는가 |
|---|---|
| `src/api/macro_routes.py:617,629,650,704,790` | `describe_all` · `run_studio` · `load_series` · `ensemble.combine_studio_views` |
| `src/engine/regime_snapshot_builder.py:153` | `describe_all()` — **가용성만** 스냅샷에 기록 |
| `src/engine/allocation_studio.py:352-363` | ★`ensemble.disagreement()` 를 **쓰지 않는다**★ 왜 안 쓰는지 설명하는 주석만 있다 |

**테스트** `tests/test_macro_studios.py`(16건) · `tests/test_macro_ensemble.py`(11건)
— 계약·가용성·형태 중심. **밀도평가·캘리브레이션·OOS 회귀 0건.**

---

## 2. 수학 모델 맵 (실측)

```bash
KIS_USE_MOCK=1 python3 -c "
from src.engine.macro_models import run_studio
for s in ('tsfm-latent','neural-sde','causal-deepm','pinn-tail'):
    print(s, run_studio(s, months=60).get('available'))"
```

| 스튜디오 | 실제 수학 | 실행 실측 (60개월) |
|---|---|---|
| LATENT | `DynamicFactor(k_factors≤2, factor_order=1)`, 1차 차분 → 표준화, 부호 고정 | ✅ `k=1`, **`explained_var = 0.0078`**, span 59/60 |
| TERM | Nelson-Siegel 3요인. λ 는 `least_squares` 로 **전표본 1개**, β 는 시점별 OLS | ✅ `λ=0.2458`, level 4.796 / slope 0.274 / **curvature −7.296** |
| CAUSAL | `granger_edges` — 유의 간선 + 지연 | ✅ 계열 10개 |
| TAIL | POT: 90% 임계 → 초과분 → `genpareto.fit(floc=0)` → VaR/ES | ❌ **미가용** — 초과 6개 < 최소 8개 |

**프론티어 계층** (`capability.probe_all()` 실측)

| 요건 | 상태 |
|---|---|
| `torch` | ❌ 미설치 |
| `frontier_sample` | ❌ **관측 60개, 최소 240개 필요** |
| `llm` · `trends_api` | ❌ 키 없음 |
| `statsmodels`·`causal_graph`·`term_structure`·`entropy_pooling`·`conformal` | ✅ |

`base.py::frontier_block` 이 직접 적는다:
> `"요건은 충족됐지만 이 엔진의 구현은 아직 없습니다 — 계약만 존재합니다."`

★막힌 이유가 둘이고, 둘째가 더 무겁다★ **torch 를 설치해도 데이터가 4배 부족하다.**
프론티어는 "아직 안 만든 것" 이 아니라 **현재 데이터로 정당화될 수 없는 계층**이다.

---

## 3. 학술 참고문헌 맵

→ `docs/specs/2026-08-25-macro-model-reference-map.md` (별도 문서)

---

## 4. PIT / 데이터 감사

**계약은 있다** — `src/data/pit_macro.py`
```python
class ResearchUsage(str, Enum):
    BACKTEST_ELIGIBLE / FORWARD_ONLY / UNAVAILABLE
def derive_usage(*, has_vintage, depth_ok, lag_known, has_source) -> ResearchUsage
class ForwardOnlyError(ValueError):  # 경고가 아니라 거부
```

**모델은 쓰지 않는다**
```bash
grep -n "as_of" src/engine/macro_models/*.py     # → 0건
```
`base.load_series()` 는 `MacroCollector().collect_all(use_cache=True)` 를 부른다 —
**절단일 인자가 없다.** 즉 어떤 스튜디오도 "그 시점에 알 수 있었던 정보" 로 돌릴 수 없다.

★이것은 오늘 팩터 스택에서 고친 결함과 같은 계열이다★ 그리고 직전 슬라이스에서
mock 을 **날짜 주소화**했기 때문에 이제 이 결함을 **테스트로 잡을 수 있다**
(그 전에는 어느 창을 요청해도 같은 값이 나와 측정 자체가 불가능했다).

**Gemini 지적 반영 상태** — ECOS 개정 편향은 `p4-macro-intelligence.md` 축에서
다루고 있고, `cointegration.MAX_CORE_VARS = 7` 도 반영돼 있다. 이 감사의 범위 밖.

---

## 4.4 ★PIT 는 하나가 아니라 세 속성이다 (2차 패스)★

감사 §4 는 *"모델이 `as_of` 를 안 받는다"* 까지만 적었다. 2차 패스에서 코드를 더 읽고
**셋을 분리해야 한다**는 것이 드러났다 — 한 불리언으로 합치면 "PIT 통과" 가 거짓말이 된다.

| 속성 | 뜻 | 지금 | 빈티지 시스템 필요? |
|---|---|---|---|
| `look_ahead_free` | t 이후 관측이 계산에 안 들어감 | ✅ **이미 참** | ❌ |
| `publication_lag_honored` | t 시점에 실제로 공표돼 있었는가 | ❌ 미모델 | ❌ 정적 시프트로 근사 |
| `revision_free` | t 시점에 공표된 **값**인가 | ❌ 불가능 | ✅ — **ECOS 미제공** |

증거:

```python
# src/engine/regime_axes.py::zscore_at  ← 국면 라벨의 뿌리
seg = [v for v in vals[max(0, idx - window + 1):idx + 1] if v is not None]
#                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 후행 윈도우만 — look-ahead 없음

# src/engine/regime_forecast.py::_posterior_forecast(path[:t], k)  — 절단 경로만
# src/engine/allocation_backtest.py::walk_forward  — R_win 은 리밸런싱 시점 이전만
```

★★`pit_verified` 같은 단일 불리언을 만들지 않는다★★ — 만드는 순간 revision bias 가
그 안에 숨는다. 응답·스냅샷·문서 어디서도 셋을 합치지 않으며, 화면도 **세 칸으로**
그린다. 셋은 서로 독립이고, 하나가 참이라고 나머지가 참이 되지 않는다:

| | look_ahead_free | publication_lag | revision_bias |
|---|---|---|---|
| 국면 경로(오늘) | ✅ | unspecified | unmanaged |
| 스튜디오(오늘) | ❌ (`as_of` 없음) | unspecified | unmanaged |
| 목표 (MS1-b) | ✅ | **declared** | **unmanaged (영구)** |

★마지막 칸이 영원히 `unmanaged` 라는 것이 핵심이다★ — ECOS 가 빈티지를 주지
않으므로 정적 공표지연을 아무리 정확히 선언해도 **값 자체가 사후 수정본**이다.
그래서 `publication_lag` 와 `revision_bias` 는 **다른 필드여야 한다.**

★결론: 국면 경로의 백테스트는 **완전한 빈티지 시스템 없이 look-ahead-free 로 만들 수
있다.**★ 불가능한 것은 revision-free 이고 — ECOS 는 ALFRED 같은 빈티지를 주지 않으므로
오늘 받은 2010-05 산업생산은 당시 속보치가 아니라 이후 확정치다 — 그것은 소프트웨어가
아니라 **데이터 벤더의 한계**다. `revision_bias: "unmanaged"` 를 **영구 라벨**로 붙이고
`look_ahead_free` 와 **같은 필드로 뭉개지 않는다.**

---

## 4.5 ★이 개발환경에서는 실계열이 0개다★

`probe_all()` 의 `frontier_sample` 이 그 사실을 이미 적고 있다:

```
frontier_sample False | {'observed': 60, 'required': 240,
                         'real_series': 0, 'total_series': 61, 'real_share': 0.0}
```

61개 계열 중 **실데이터 0개**다(`KIS_USE_MOCK=1` 기본값). 그래서 이 문서의 국면·
전이·적중률 수치는 전부 **mock 위에서 잰 것**이고, 다음을 뜻한다:

- ★결정가치 측정은 지금 "기계가 돈다" 는 증거지 "모델이 맞다" 는 증거가 아니다.★
  기제(mechanism)는 검증되지만 경제적 유의성은 실계열 없이 판정할 수 없다.
- 따라서 **어떤 모델도 실계열 없이 production 으로 승격하지 않는다.** 승격 판정은
  `real_share` 가 유의미해진 뒤 같은 명령을 다시 돌려서 한다.
- mock 이 날짜 주소화돼 있으므로(직전 슬라이스) 적어도 **재현은 된다** — 같은 날
  같은 수치, 다른 날 다른 수치. 문서가 수치를 못 박지 않고 명령을 못 박는 이유다.

---

## 5. ★구현 vs 논문 갭★ — 가장 중요한 절

### 5.1 LATENT — `loadings` 라는 필드에 적재가 들어간 적이 없다

```python
# tsfm_latent.py
load[i, j] = float(res.params.get(f"loading.f{j+1}.y{i+1}", np.nan)) \
    if hasattr(res.params, "get") else np.nan
```

```bash
KIS_USE_MOCK=1 python3 -c "
from statsmodels.tsa.statespace.dynamic_factor import DynamicFactor
import numpy as np; Z=np.random.randn(60,4)
r=DynamicFactor(Z,k_factors=1,factor_order=1).fit(disp=False)
print(type(r.params).__name__, hasattr(r.params,'get'))"
# → ndarray False
```

★`res.params` 는 `ndarray` 라 `.get` 이 없다 → 가드가 항상 거짓 → 전부 `nan` →
**상관 폴백이 100% 항상 탄다.**★ 그래서:

- `loadings` 필드에는 **적재가 아니라 상관계수**가 들어간다. 한 번도 예외가 없다.
- 코드 주석은 *"상관으로 대체하고 그 사실을 적는다"* 고 하지만
  **그 사실을 적는 출력 필드가 없다.** `note` 는 두 경우에 동일하다.

실측이 이것을 확증한다 — `KR_3Y` 적재가 **정확히 1.0**:
```
{'KR_3Y': 1.0, 'KR_CPI': 0.2646, 'KR_LEADING_CYCLE': 0.2236, 'KR_IP': 0.1799,
 'KOSPI': 0.0747, 'KR_10Y': -0.1054, 'USD_KRW': -0.1054}
```
상관 1.0 은 **필터된 요인이 곧 KR_3Y 의 차분계열**이라는 뜻이다.
그리고 `explained_var = 0.0078` — 공통요인이 분산의 **0.78%** 만 설명한다.

**결론**: 지금의 LATENT 은 "여러 지표가 공유하는 잠재 상태" 가 아니라
**단기금리의 재표현**이다. 화면 질문(`"여러 매크로 지표가 공유하는 잠재 상태는
무엇인가?"`)에 답하지 못한다.

#### ★감사 중 세 번째 정정 (2026-08-25 2차 패스)★

위의 *"loadings 에 상관이 들어간다"* 는 **문자 그대로는 맞지만 결론이 과했다.**
파라미터를 직접 덤프해 확인했다:

```
정확한 적재 (res.model.param_names 로 읽음):
  loading.f1.y1 KOSPI            -0.072191     sigma2.y1  0.977557
  loading.f1.y2 KR_10Y            0.101825     sigma2.y2  0.972129
  loading.f1.y3 KR_3Y            -0.966294     sigma2.y3  0.000000   ← ★
  loading.f1.y4 KR_CPI           -0.255677     sigma2.y4  0.914223
  loading.f1.y5 KR_IP            -0.173839     sigma2.y5  0.951220
  loading.f1.y6 KR_LEADING_CYCLE -0.216045     sigma2.y6  0.933916
  loading.f1.y7 USD_KRW           0.101880     sigma2.y7  0.972120

상관 폴백:  [-0.0747, 0.1054, -1.0, -0.2646, -0.1799, -0.2236, 0.1054]
비율 corr/load ≈ 1.035 = 1/√var(f̂),  var(f̂) = 1.071  →  ★전 계열 동일 비율★
```

★표준화 입력 + 단위분산 요인 정규화 아래서 상관은 적재의 **상수배**다★ — 모양은
보존되고 스케일만 틀린다. 그래서 화면의 **순위와 부호는 옳았고**, 아무도 못 잡았다.

**진짜 결함은 `sigma2.y3 = 0.000000` — Heywood 케이스다.** KR_3Y 의 고유분산이 0으로
추정됐다는 것은 "공통 요인" 이 사실 **KR_3Y 한 계열 그 자체**라는 뜻이고, 그래서
상관이 정확히 1.0 이 나온 것이다. `explained_var = 0.0078` 이 그 자백이다.
★출력 어디에도 이 사실이 없다.★

**부수 결함 — 이름과 계산이 다르다.** `explained_var = 1 − var(res.resid)/var(Z)` 인데
`res.resid` 는 **1기 앞 예측오차**다. 분산분해가 아니라 **예측 R²** 다(합성 강요인
데이터에서 0.387 — 요인은 강한데 값은 낮다). `one_step_r2` 로 개명해야 한다.

#### k = 1 / 2 / 3 을 비교했다 — "요인을 늘려 고친다" 는 근거가 없다

(T=59 · N=7 · ‖S‖=2.7851 · `factor_order=1` · `maxiter=500`)

| k | loglik | AIC | BIC | 재구성/‖S‖ | min σ² | **Heywood 계열 수** | resid var |
|---|---|---|---|---|---|---|---|
| **1** | −575.55 | **1181.10** ★ | **1212.26** ★ | 0.2397 | 0.000000 | **1** (KR_3Y) | 0.9753 |
| **2** | −567.79 | 1185.57 | 1237.51 | **0.1755** ★ | 0.000000 | **2** (KR_3Y · USD_KRW) | 0.9572 |
| **3** | −556.68 | 1187.36 | 1264.23 | 0.1806 | 0.000016 | 0 (경계) | 0.9063 |

- **AIC·BIC 둘 다 `k=1`** — 현행 기본값이 정보기준 최적이다.
- ★**Heywood 는 k 를 늘려도 안 없어진다**★ — `k=2` 에서 **둘로 늘어난다.**
  요인수 문제가 아니라는 강한 증거다.
- 재구성은 `k=2` 최선이나 정보기준이 벌점 — 과적합(`k=3` 은 파라미터 31 / 관측 59).
- ★잔여분산 0.91~0.98★ — **어느 k 에서도 공통요인이 분산의 10% 도 설명 못 한다.**

즉 고칠 대상은 요인수가 아니라 **전처리 또는 데이터**다. 자세한 조사 순서는
`docs/plans/2026-08-25-macro-vnext-plan.md` §3.3 (W-DFM 워크스트림).

★그리고 이 사실이 회귀 테스트 설계를 바꾼다★ — 적재와 상관이 k=1 에서 비례하므로,
**k=1 로 세운 가드는 상관 폴백을 잡지 못한다**(등가 변이). 판별하려면 k=2 fixture 가
필요하다. 실측 판별비: k=1 에서 1.01(실패) · k=2 에서 42.4(성공).
→ `docs/plans/2026-08-25-macro-vnext-plan.md` §3.3

### 5.2 LATENT — Stock–Watson / Doz 대비 빠진 것

| 논문이 요구 | 코드 |
|---|---|
| Bai–Ng 요인수 선택 | ❌ 사용자 인자 `n_factors`, 상한 2 |
| 결측 처리(칼만이 native 지원) | ❌ 최소 길이로 **절단** |
| 혼합주기 | ❌ 월간만 |
| 릴리스 타이밍 정렬 | ❌ 없음 |
| 요인 안정성 진단 | ❌ 없음 |

### 5.3 TERM — Diebold–Li 의 절반

NS **적합**은 정확하다(기저 `[1, (1−e^{−λτ})/(λτ), 그것−e^{−λτ}]`, τ→0 가드 포함).
그러나 Diebold–Li(2006)의 요지는 **β 를 AR/VAR 로 예측**해 곡선을 예측하는 것이다.
★코드에는 예측 단계가 없다★ — 현재 상태만 낸다. 스펙 §9 가 *"현재 곡선 상태와 예측
곡선 상태를 분리하라"* 고 한 그 분리에서 **예측 쪽이 비어 있다**.

★규율은 오히려 모범적이다★ 독스트링:
> *"Nelson-Siegel 은 곡선의 모양을 기술할 뿐 무차익 조건을 걸지 않는다. …
> 그래서 필드 이름을 `slope`·`term_premium_proxy` 로 두고 노트에 '대용' 이라고
> 적는다. **이름이 곧 주장이다.**"*

만기가 4개(3M·2Y·10Y·30Y)뿐이라 3파라미터 NS 는 거의 정확결정계다 — `rmse_pp` 가
작게 나오는 것을 적합도의 증거로 읽으면 안 된다. 감사는 이 점을 기록한다.

### 5.4 TAIL — McNeil 대비

적합·VaR/ES 공식은 정확하고, ★`ξ ≥ 1` 이면 ES 를 내지 않는다★(스펙 §14 요구 충족).
빠진 것: **임계 민감도 · 파라미터 신뢰구간 · 부트스트랩 · 꼬리지수 안정성 ·
VaR/ES 백테스팅**. 그리고 현재 데이터로는 **아예 돌지 않는다**(초과 6 < 8).

### 5.5 REGIME — 4국면 중 둘은 구조적으로 확률 0

`src/engine/regime_ensemble.py` 는 `MarkovRegression(k_regimes=2,
switching_variance=True)` 로 **성장축만** 상태전환시키고, 물가는
`infl_up = i_hist[-1] >= 0` 라는 **결정적 부호**로 가른다:

```python
probs = {"Reflation":   p_expand      if infl_up else 0.0,
         "Goldilocks":  0.0           if infl_up else p_expand,
         "Stagflation": (1-p_expand)  if infl_up else 0.0,
         "Disinflation":0.0           if infl_up else (1-p_expand)}
```

즉 **항상 두 국면의 확률이 정확히 `0.0`** 이다. Hamilton 4상태 사슬이 아니라
2상태 × 하드 부호다. 이것을 "4국면 확률분포" 로 읽으면 안 된다.

★감사 중 내가 한 번 틀렸다 — 정정을 남긴다★
처음에 *"`smoothed_marginal_probabilities` 를 쓰므로 look-ahead"* 라고 판단했다.
**틀렸다.** 마지막 시점 T 에서는 뒤에 관측이 없어 `smoothed[-1] == filtered[-1]`
이므로 **현재 국면 호출에는 look-ahead 가 아니다.** 다만 같은 함수로 **과거 경로**를
만들면(각 t 에서 `smoothed[t]`) 그때는 look-ahead가 된다 — 현재 그렇게 쓰는 곳은
없지만, 재사용 시 주의해야 할 지점이라 적어 둔다.

★감사 중 내가 두 번째로 틀렸다 — 이것도 정정한다★
처음에 *"예측 국면확률 `P(S_{t+h}=j|X_t)` 가 없다(`matrix_power` 사용처 0)"* 라고
적었다. **틀렸다.** `matrix_power` 를 안 쓸 뿐, 앞으로 굴리는 코드는 **있다**:

| 코드 | 무엇을 하는가 |
|---|---|
| `regime_transitions.py:178 k_step_forecast` | 행별 Dirichlet **사후에서 행렬을 4000회 뽑아** 거듭제곱 — k개월 뒤 분포 + 90% 신용구간 |
| `regime_transitions.py:276` | 그 예측을 `/macro/regime-explain` 응답의 `forecast` 로 실제 노출 |
| `regime_transitions.py:160` | `expected_duration_months = 1/(1-p_stay)` — 국면별 기대 지속기간 |
| `regime_forecast.py` + `macro_routes.py:749` | **워크포워드 실측 적중률** — 각 t 에서 t 까지의 경로만으로 사후를 세워 t+k 를 채점 |

실측(재현 명령은 §11):
```
current=Goldilocks  n_transitions=52  span=202204~202608 (53개월, 7개월 결측 제외)
기대 지속기간  Goldilocks 5.0 · Reflation 3.2 · Stagflation 3.8 · Disinflation 2.5 (개월)
k=3 예측  Goldilocks 0.601 [0.409, 0.788] · Disinflation 0.169 · Reflation 0.133 · Stagflation 0.097
워크포워드 적중률  k=1 → 0.966 (집합크기 2.72/4, n=29)   k=3 → 0.889 (집합크기 3.81/4, n=27)
```

#### ★네 개의 "지금 국면 확률" 이 공존한다 (2차 패스 실측)★

같은 4국면 분류체계 위에 확률 객체가 **셋** 있고, 포트폴리오는 **넷째**를 쓴다:

| # | 이름 | 코드 | 오늘 Goldilocks | 성격 |
|---|---|---|---|---|
| 1 | 축 확률 | `regime_axes.quadrant_probs(g, i, se_g, se_i)` | **0.535** | 오늘 축 z 와 **그 표준오차** → 사분면 확률 |
| 2 | Markov filtered | `regime_ensemble._markov_probs` | **0.964** (2국면 정확히 0.0) | 성장축 2상태 × 물가 하드 부호 |
| 3 | k단계 예측 | `regime_transitions.k_step_forecast` | **0.601** [0.409, 0.788] | 사분면 경로 Dirichlet 사후예측 |
| 4 | **하드 라벨 ← 포트폴리오** | `regime_path(...)["points"][-1]["regime"]` | **1.000** | 결정적. 불확실성 0 |

★한 문장: 저장소는 "지금 Goldilocks 일 확률" 에 0.535 · 0.964 · 0.601 세 답을 갖고
있는데, 최적화기에는 **1.000** 을 보낸다.★

`smoothed_marginal_probabilities` 는 다섯 번째 후보가 아니라 **금지 대상**이다 —
마지막 시점에서만 filtered 와 같으므로(위 정정), 과거 경로를 `smoothed[t]` 로 만들면
look-ahead 다. 계약은 `docs/plans/2026-08-25-macro-vnext-plan.md` §1.5 에 있다.

**그래서 실제 결함은 다른 세 가지다**
- ★예측이 조건부 μ/Σ 에 **닿지 않는다**★ `allocation_routes.py:673-676` 은
  `cond_path["points"][-1]["regime"]` — **오늘의 점 라벨** 하나로 조건부를 만든다.
  4000회 사후예측도, 신용구간도, 기대 지속기간도 포트폴리오에 전달되지 않는다.
- ★k=3 에서 예측이 **날카롭지 않다**★ 적중률 0.889 는 목표 0.9 에 붙지만
  **평균 집합 크기가 3.81/4** 다 — 4국면 중 거의 전부를 담아야 맞힌다. 즉 3개월
  지평에서 국면 예측은 **정보가 거의 없다**. 그런데 조건부 μ/Σ 는 오늘 국면을
  **확률 1** 로 취급한다. 데이터가 뒷받침하지 않는 확신이다.
- 두 국면 시스템이 공존한다 — Markov(`regime_ensemble`, 성장축 2상태 × 물가 부호)와
  사분면 경로(`regime_transitions`, 결정적 규칙). **전이·예측·지속기간은 전부
  후자**에서 나오고, 전자의 전이행렬은 화면에만 간다. 라벨 분류체계(4국면)는 같지만
  **생성 기제가 다르고 서로를 모른다.**

★잘 되어 있는 것★ 전이행렬 **방향**(statsmodels 는 열이 출발)을 주석과 테스트로
못박고, 헷갈릴 수 없는 이름(`p_exp_to_con`)으로 한 번 더 낸다. 과거에 프론트가
방향을 뒤집어 그린 사고가 있었고 그 재발을 막고 있다.

### 5.6 ENSEMBLE — 스펙이 말하는 것과 다른 물건

스펙 §17 은 **예측 결합 + 모델리스크 계층**(BMA·역오차·OOS가중)을 요구한다.
`ensemble.py` 는 **범주형 판정의 불일치 집계**다(정규화 엔트로피, "도구 2개 이상이
전부 같아야 합의"). 가중치도 밀도결합도 없다.

★그런데 결합 기계는 이미 저장소에 있다★ — `src/engine/forecast_combination.py`
(비음수 최소분산 결합, 중첩 상관 처리). 매크로 쪽에 연결돼 있지 않을 뿐이다.

`allocation_studio.py:352-363` 이 이 구분을 **이미 정확히 적어 두었다**:
> *"설계 문서 §3 은 이 자리에서 `macro_models.ensemble.disagreement()` 를
> 재사용한다고 적었는데 **틀렸다** — 그 함수는 범주형 판정의 정규화 엔트로피다.
> 가중치 산포는 수치이므로 그 함수로 잴 수 없다."*

### 5.7 없는 것 (구현이 아예 부재)

나우캐스팅/빈티지 갱신 · **FCI**(Hatzius) · **Growth-at-Risk**(Adrian 등) ·
NS 예측 단계(적합만 있고 β 예측이 없다) · Bai–Ng 요인수 선택 · 혼합주기 처리.

★"검증이 없다" 고는 쓰지 않는다 — 한 곳에는 있다★ 국면 경로에는 워크포워드
적중률(`regime_forecast.forecast_coverage`)이 **이미** 있고 look-ahead 를 피하는
이유까지 주석에 적혀 있다. 없는 것은 **나머지 전부**다 — 스튜디오 5종(LATENT ·
TERM · CAUSAL · TAIL · ENSEMBLE)에는 워크포워드도 밀도평가(CRPS/로그점수)도 없다
(스튜디오 테스트 27건 중 밀도평가 0건). 그래서 필요한 것은 프레임워크의 **발명**이
아니라 이미 증명된 패턴의 **확장**이다.

---

## 6. ★스튜디오는 포트폴리오에 연결돼 있지 않다★ (핵심 결론)

실제 조건부 μ/Σ 경로는 스튜디오를 **지나지 않는다**:

```
regime_path (사분면 규칙, regime_transitions.py)
  → regime_by_month_from_path
  → conditional_moments (conditional_market.py)
  → optimize(s_override=Σ_cond)      ← allocation_routes.py:669-676
```

스튜디오가 하는 일은 **화면에 답을 그리는 것**뿐이고, `regime_snapshot_builder` 는
그 **가용성만** 스냅샷에 적는다.

★그래서 Level 4(결정가치)로 평가할 대상이 사실상 없다.★ 스펙 §18 이 "궁극 기준" 이라
한 층에서 현재 측정 가능한 스튜디오는 **0개**다. 이것이 이 감사의 가장 중요한 발견이고,
최소 수직 슬라이스를 고르는 기준이 된다.

---

## 7. 벤치마크 위계 · 8. OOS 방법론 · 9. 모델리스크

→ `docs/specs/2026-08-25-macro-validation-framework.md` (별도 문서)

---

## 10. 모델 매트릭스 · 우선순위

| 모델 | 구현 | 1차 문헌 | 수학 정합 | PIT | OOS | 불확실성 | 포트폴리오 관련성 | 비용 | **권고** |
|---|---|---|---|---|---|---|---|---|---|
| **LATENT (DFM)** | statsmodels DFM | Stock–Watson 2002 | ⚠️ 적합은 맞으나 `loadings`가 상관 · 설명분산 0.78% | ❌ | ❌ | ❌ | ❌ 미연결 | 낮음 | **redesign** |
| **TERM (NS)** | NS 3요인 적합 | Diebold–Li 2006 | ✅ 적합 정확 · **예측 단계 부재** | ❌ | ❌ | ❌ | ⚠️ 미연결 | 낮음 | **baseline 유지 + 예측 추가** |
| **CAUSAL (Granger)** | granger_edges | Granger · Spirtes 등 | ✅ + 면책 명시 | ❌ | ❌ | ⚠️ p값만 | ❌ 미연결 | 낮음 | **research-only** |
| **TAIL (POT/GPD)** | scipy genpareto | McNeil 1997 | ✅ 공식 정확 · ES 발산 거부 | ❌ | ❌ | ❌ CI/부트스트랩 없음 | ⚠️ 미연결 | 낮음 | **baseline** (표본 확보 후) |
| **REGIME (Markov)** | MarkovRegression k=2 | Hamilton 1989 | ⚠️ 4국면 중 2개 확률 0 · 전이행렬이 화면에서 끝난다 | ❌ | ❌ | ⚠️ p만 | ⚠️ 화면만 | 낮음 | **research-only** |
| **REGIME (사분면 경로)** | 결정적 규칙 + Dirichlet 전이 | Markov 사슬 표준 | ✅ 사후예측·신용구간 정확 | ❌ | ✅ **워크포워드 적중률 실측** | ✅ 신용구간 | ⚠️ **점 라벨만** 전달 | 낮음 | **production 승격 대상** |
| **ENSEMBLE** | 범주형 불일치 | (스펙 §17과 다름) | ✅ 자기 목적엔 정확 | n/a | n/a | ✅ 불일치 노출 | ❌ | 낮음 | **research-only** |
| **AGENTIC** | 뷰→부등식 | Black–Litterman · Meucci | ✅ 경계 명시 | n/a | n/a | ✅ `feasible: null` | ⚠️ EP 경유 | 낮음 | **research-only** |
| **프론티어 5종** | **없음(계약만)** | TimesFM·Chronos 등 | n/a | n/a | n/a | n/a | n/a | 높음 | **보류** — 240개월 전까지 불가 |

### 우선순위

1. ★**이미 있는 예측 국면분포를 조건부 μ/Σ 에 연결**★ — 새 모델을 들이지 않는다.
   `k_step_forecast` 의 4000회 사후예측이 이미 있고, 워크포워드 적중률까지 측정돼
   있는데, 포트폴리오는 **오늘의 점 라벨**만 받는다. 결정가치(Level 4)를 즉시 잴 수
   있는 유일한 후보다. → `docs/plans/2026-08-25-macro-vnext-plan.md`
2. **PIT** — 매크로 모델에 `as_of` 관통(기본값 = 현행 동작).
3. **LATENT redesign** — `loadings` 이름 정정 + Bai–Ng + 결측 처리.
4. **TERM 예측 단계** — β 의 AR/VAR.
5. **검증 프레임워크** — 워크포워드 + 밀도평가.
6. 프론티어 — 데이터가 240개월을 채우기 전에는 착수하지 않는다.

---

## 11. 재현 명령 (이 문서의 수치는 전부 여기서 나왔다)

★"이렇다더라" 를 쓰지 않기 위한 절이다★ 아래를 그대로 돌리면 위 표의 숫자가 다시 나온다.
매크로 계열은 mock 이 날짜 주소화돼 있으므로 같은 날에는 같은 값이, 날이 바뀌면
`span.last` 가 따라 움직인다 — **수치를 못 박지 말고 명령을 못 박는다.**

```bash
cd /home/user/Project-Alpha

# (1) 프론티어가 막힌 두 이유 — torch 부재 AND 표본 60 < 240
KIS_USE_MOCK=1 python3 -c "
from src.engine.capability import probe_all
for k, v in probe_all().items():
    print(k, v.get('ok'), '|', v.get('detail') or v.get('reason'))"

# (2) 스튜디오별 available / reason
KIS_USE_MOCK=1 python3 -c "
from src.engine.macro_models.base import STUDIOS, run_studio
for st in STUDIOS():
    r = run_studio(st.id)
    print(st.id, r.get('available'), '|', r.get('reason'))"

# (3) 전이·기대지속기간·k단계 예측 (§5.5 의 수치)
KIS_USE_MOCK=1 python3 -c "
import json
from src.services.macro_collector import MacroCollector
from src.engine.regime_transitions import regime_transitions
sm = getattr(MacroCollector.get_default().collect_all(use_cache=True), 'series', {})
r = regime_transitions(sm, market='kr', months=60)
print(r['current'], r['n_transitions'], r['span'])
for row in r['rows']:
    print(row['from'], row['n'], row['expected_duration_months'], row['shrunk'])
print(json.dumps(r['forecast'], ensure_ascii=False))"

# (4) 워크포워드 실측 적중률 (§5.5 의 0.966 / 0.889)
KIS_USE_MOCK=1 python3 -c "
import json
from src.services.macro_collector import MacroCollector
from src.engine.regime_transitions import regime_path
from src.engine.regime_forecast import forecast_coverage
sm = getattr(MacroCollector.get_default().collect_all(use_cache=True), 'series', {})
path = [p['regime'] for p in regime_path(sm, 'kr', 60)['points']]
for k in (1, 3):
    c = forecast_coverage(path, k=k, alpha=0.1)
    print(k, round(c['coverage'], 4), round(c['mean_set_size'], 3), c['n_eval'])"

# (5) PIT — 매크로 모델에 as_of 가 하나도 없다는 사실
grep -n "as_of" src/engine/macro_models/*.py | wc -l   # → 0

# (6) 포트폴리오는 점 라벨만 받는다
sed -n '669,677p' src/api/allocation_routes.py
```

### 11.1 2차 설계 패스(MS1 심층)의 재현 명령

```bash
cd /home/user/Project-Alpha

# (7) DFM 이 Heywood 케이스라는 사실 — sigma2.y3 = 0.000000 (§5.1 정정 3)
KIS_USE_MOCK=1 python3 -c "
import numpy as np
from src.engine.macro_models.base import load_series
from statsmodels.tsa.statespace.dynamic_factor import DynamicFactor
keys=('KR_LEADING_CYCLE','KR_IP','KOSPI','KR_CPI','KR_3Y','KR_10Y','USD_KRW')
s=load_series(keys,60); names=sorted(s); n=min(len(v) for v in s.values())
X=np.column_stack([np.asarray(s[k][-n:],float) for k in names])
D=np.diff(X,axis=0); sd=D.std(0,ddof=1); keep=sd>1e-12
Z=(D[:,keep]-D[:,keep].mean(0))/sd[keep]
r=DynamicFactor(Z,k_factors=1,factor_order=1).fit(disp=False,maxiter=200)
for nm,v in zip(r.model.param_names, np.asarray(r.params)):
    if nm.startswith(('loading','sigma2')): print(f'{nm:22s}{v: .6f}')"

# (8) 재구성 검정이 k=1 에서는 판별하지 못한다는 사실 (§5.1 → 계획 §3.3)
#     k=1 실데이터 → 0.6677 vs 0.6763 (비 1.01)  ·  k=2 합성 → 0.116 vs 4.916 (비 42.4)

# (9) 네 확률 객체 (§5.5)
KIS_USE_MOCK=1 python3 -c "
import json
from src.services.macro_collector import MacroCollector
from src.engine.regime_ensemble import regime_ensemble
from src.engine.regime_transitions import regime_transitions
sm=getattr(MacroCollector.get_default().collect_all(use_cache=True),'series',{})
e=regime_ensemble(sm,'kr',60); t=regime_transitions(sm,'kr',60)
print('axis    ', e['tools']['axis']['probs'])
print('markov  ', e['tools']['markov']['probs'])
print('forecast', t['forecast']['mean'])
print('hard    ', t['current'], '-> 1.000')"

# (10) 국면 라벨이 후행 윈도우만 본다는 증거 (§4.4)
sed -n '/def zscore_at/,/return (x - mean)/p' src/engine/regime_axes.py

# (11) 혼합 공분산의 지평 스케일 — 시뮬레이션으로 h·W+h²·D 를 확인
#      (계획 §1.3 의 표. 2자산·2국면·12만 경로)
```

### 11.2 3차 패스(계약 확정)의 재현 명령

```bash
cd /home/user/Project-Alpha

# (12) ★혼합 공분산 정확식★ — h²D 는 상한이지 답이 아니다 (계획 §1.3.2)
python3 -c "
import numpy as np
rng=np.random.default_rng(11)
P=np.array([[0.85,0.15],[0.25,0.75]]); pi0=np.array([0.6,0.4]); h=3
M=np.array([[0.015,-0.002],[-0.008,0.006]])
Sg=np.array([[[0.0025,0.0005],[0.0005,0.0009]],[[0.0049,-0.0010],[-0.0010,0.0016]]])
pis=[pi0@np.linalg.matrix_power(P,j) for j in range(1,h+1)]; E=[p@M for p in pis]
W=sum(np.einsum('s,sij->ij',p,Sg) for p in pis); A=np.zeros((2,2))
for j in range(h):
    for k in range(h):
        T=np.linalg.matrix_power(P,abs(k-j))
        J=np.einsum('s,st->st',pis[j],T) if k>=j else np.einsum('t,ts->st',pis[k],T)
        A+=np.einsum('st,si,tj->ij',J,M,M)-np.outer(E[j],E[k])
D=sum(pi0[i]*np.outer(M[i],M[i]) for i in range(2))-np.outer(pi0@M,pi0@M)
Wm=np.einsum('s,sij->ij',pi0,Sg)
out=np.empty((200000,2))
for i in range(len(out)):
    s=rng.choice(2,p=pi0); t=np.zeros(2)
    for _ in range(h):
        s=rng.choice(2,p=P[s]); t+=rng.multivariate_normal(M[s],Sg[s])
    out[i]=t
np.set_printoptions(precision=6,suppress=True)
print('sim      ',np.cov(out,rowvar=False,ddof=1).ravel())
print('W_h+A_h  ',(W+A).ravel())
print('h W+h^2D ',(h*Wm+h*h*D).ravel())
print('h(W+D)   ',(h*(Wm+D)).ravel())
print('h^2D/A   ',np.round(np.diag(h*h*D)/np.diag(A),3))"
# → sim 과 W_h+A_h 가 일치하고, h²D 가 A 를 1.489배 과대추정한다

# (13) DFM k=1/2/3 비교 (§5.1) — AIC·BIC 는 k=1, Heywood 는 k=2 에서 둘로 는다
KIS_USE_MOCK=1 python3 -c "
import numpy as np, warnings; warnings.simplefilter('ignore')
from src.engine.macro_models.base import load_series
from statsmodels.tsa.statespace.dynamic_factor import DynamicFactor
keys=('KR_LEADING_CYCLE','KR_IP','KOSPI','KR_CPI','KR_3Y','KR_10Y','USD_KRW')
s=load_series(keys,60); names=sorted(s); n=min(len(v) for v in s.values())
X=np.column_stack([np.asarray(s[k][-n:],float) for k in names])
Dm=np.diff(X,axis=0); sd=Dm.std(0,ddof=1); keep=sd>1e-12
Z=(Dm[:,keep]-Dm[:,keep].mean(0))/sd[keep]; N=Z.shape[1]
S=np.cov(Z,rowvar=False,ddof=1); nS=np.sqrt((S**2).sum())
for k in (1,2,3):
    r=DynamicFactor(Z,k_factors=k,factor_order=1).fit(disp=False,maxiter=500)
    pn=r.model.param_names; p=np.asarray(r.params)
    L=np.array([[p[pn.index(f'loading.f{j+1}.y{i+1}')] for j in range(k)] for i in range(N)])
    psi=np.array([p[pn.index(f'sigma2.y{i+1}')] for i in range(N)])
    f=np.asarray(r.factors.filtered).T.reshape(Z.shape[0],-1)
    Om=np.cov(f,rowvar=False,ddof=1).reshape(k,k)
    rec=float(np.sqrt((((L@Om@L.T+np.diag(psi))-S)**2).sum()))
    print(k, round(r.llf,2), round(r.aic,2), round(r.bic,2), round(rec/nS,4),
          round(psi.min(),6), int((psi<1e-6).sum()), round(float(np.nanvar(r.resid)),4))"

# (14) ★신뢰도 — 휴리스틱 vs Ω 분해★ (계획 §1.5.3)
python3 -c "
import numpy as np
tau=0.05; Sii=np.array([0.16,0.04,0.07])**2; D=np.array([0.0047,0.0002,0.0008])
for nm in (15,32,60):
    om=D+Sii*(12.0/nm); sc=om/(tau*Sii)
    print(nm, np.round(om,5), np.round(100/(1+sc),2))
print('legacy 50*(1-0.2) =', 50*0.8)"
# → 분해는 n_months 에 따라 4.84 → 11.53 으로 움직이고, legacy 는 항상 40.0
```

★이 감사에서 내가 **세 번** 틀렸고 세 번 다 본문에 정정을 남겼다★ (§5.1·§5.5) —
`smoothed` look-ahead 판단 · "예측 국면확률 부재" 판단 · "loadings 가 상관이라 결함"
판단이다. 셋 다 **코드를 읽고 고쳤다.** 감사 문서에서 정정을 지우면 다음 사람이 같은
오독을 반복한다 — 특히 세 번째는 **회귀 테스트를 k=1 에 세우게 만드는** 오독이라
비용이 크다.
