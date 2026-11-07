# 매크로 모델 ↔ 학술 문헌 대응표

> 출처: `docs/Project_Alpha_Macro_Research_Spec.md` §5~§17
> ★스펙이 준 참고문헌을 **실제 코드에 대한 관련성으로 검증**했다★ — 스펙 §31 의 지시.
> 관련 없는 문헌은 "해당 없음" 으로 적는다. 목록을 채우려고 남겨 두지 않는다.

## 읽는 법

| 열 | 뜻 |
|---|---|
| **코드** | 실제 파일·심볼 |
| **1차 문헌** | 그 구현이 실제로 따르는 가장 강한 참조 |
| **★갈리는 지점★** | 코드가 논문과 **어디서** 달라지는가 |

---

## LATENT — 동적 요인모형

- **코드** `src/engine/macro_models/tsfm_latent.py::run` → `statsmodels.tsa.statespace.dynamic_factor.DynamicFactor`
- **1차 문헌** Stock & Watson (2002), *Macroeconomic Forecasting Using Diffusion Indexes*
- **보조** Doz, Giannone & Reichlin (2단계/상태공간 DFM) · Bai & Ng (요인수 선택)

★갈리는 지점★
| 논문 | 코드 |
|---|---|
| 요인수를 **정보기준으로 선택**(Bai–Ng) | 사용자 인자 `n_factors`, 상한 2 |
| 결측을 칼만 필터가 native 처리 | 최소 길이로 **절단** (`n = min(len)`) |
| 혼합주기 허용 | 월간 단일주기 |
| 적재(loading)를 추정치로 보고 | ★`res.params.get` 이 항상 실패해 **상관계수**를 `loadings` 로 낸다★ |

★"PCA = DFM 이 아니다" 는 스펙 §5 의 경고를 코드는 지켰다★ — 실제로 상태공간 DFM 이다.
다만 **설명분산 0.78%** 라 요인이 공통성분을 잡지 못하고 있다(감사 §5.1).

---

## TERM — Nelson-Siegel

- **코드** `src/engine/macro_models/neural_sde.py::run` (파일명과 달리 NS 다)
- **1차 문헌** Diebold & Li (2006), *Forecasting the Term Structure of Government Bond Yields*
- **보조** Diebold, Rudebusch & Aruoba (상태공간 기간구조)

★갈리는 지점★
| 논문 | 코드 |
|---|---|
| β(수준·기울기·곡률)를 **AR/VAR 로 예측** → 곡선 예측 | ★예측 단계 **없음** — 현재 상태만★ |
| λ 를 고정(0.0609/월) 또는 추정 | `least_squares` 로 전표본 1개 추정 (λ=0.2458 실측) |
| 다수 만기 | 4개(3M·2Y·10Y·30Y) — 3파라미터에 대해 거의 정확결정 |

★코드가 논문보다 **더** 조심스러운 지점★ 무차익 조건이 없으므로 결과를 위험가격
$\lambda_t$ 라 부르지 않고 `term_premium_proxy` 로 둔다. 스펙 §9 의 요구를 넘어선다.

**프론티어 계약**(무차익 Neural SDE)의 수학적 대응은 스펙 §12 의
$dX_t = \mu_\theta dt + \sigma_\theta dW_t$ 이나 **구현이 없다** — 문헌 대응은
계약 수준에서만 성립한다.

---

## CAUSAL — Granger

- **코드** `src/engine/macro_models/causal_deepm.py::run` → `src/engine/causal_graph.py::granger_edges`
- **1차 문헌** Granger 인과 문헌 · Spirtes, Glymour & Scheines, *Causation, Prediction, and Search*

★갈리는 지점★ 없음 — 코드는 Granger 를 Granger 라고 부르고, 노트에
*"개입 인과가 아니다 · 공통 원인이 있으면 양쪽이 유의하다"* 를 적는다.
스펙 §13 의 위계(상관 → 선행 → Granger 예측성 → 조건부 → 구조가설)에서
**"Granger 예측성" 까지만** 주장한다. 정확한 자기제한이다.

**미구현** 조건부 독립 검정 · 구조적 식별(PC/FCI 등). 프론티어 DeePM 은 계약만.

---

## TAIL — EVT / POT

- **코드** `src/engine/macro_models/pinn_tail.py::run` → `scipy.stats.genpareto`
- **1차 문헌** McNeil (1997), *Estimating the Tails of Loss Severity Distributions Using EVT*
- **기초** McNeil, Frey & Embrechts, *Quantitative Risk Management*

★갈리는 지점★
| 논문 | 코드 |
|---|---|
| 임계 선택을 민감도로 정당화 | 90% 분위 **고정** |
| 파라미터 신뢰구간 · 부트스트랩 | ❌ |
| 꼬리지수 안정성 플롯 | ❌ |
| VaR/ES 백테스팅 | ❌ (단, `src/models/backtest.py` 에 Kupiec 이 별도로 있다) |

★논문 정신을 지킨 지점★ `ξ ≥ 1` 이면 ES 가 발산하므로 **숫자를 내지 않는다**.
스펙 §14 의 *"발산하면 조작하지 말고 미가용을 보고하라"* 를 그대로 구현했다.

---

## REGIME — Markov 상태전환

- **코드** `src/engine/regime_ensemble.py` → `statsmodels.tsa.regime_switching.markov_regression.MarkovRegression`
  (★`macro_models/` 밖에 있다★ — 스튜디오가 아니다)
- **1차 문헌** Hamilton (1989), *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*

★갈리는 지점★
| 논문/스펙 §7 | 코드 |
|---|---|
| $P(S_t=k\mid X_{1:t})$ 필터확률 | `smoothed[-1]` — **T 에서는 동일**하므로 현재 호출은 정당 |
| $P(S_{t+h}=j\mid X_t)$ 예측확률 | ★**없음**★ 전이행렬을 내되 굴리지 않는다 |
| 기대 지속기간 $1/(1-p_{ii})$ | Markov 기준으로는 없음. 사분면 경로 기준 값이 `regime_transitions.py:168` 에 별도 존재 |
| k-상태 사슬 | k=2(성장축) × **결정적 물가부호** → 4국면 중 2개는 항상 확률 0 |

라벨(Goldilocks/Reflation/…)은 스펙 §7 이 말한 대로 **해석층**이며, 코드도 그렇게
다룬다(상태 평균으로 확장/수축을 데이터가 정하게 하고 순서를 가정하지 않는다).

---

## VIEWS — Black-Litterman / Entropy Pooling

- **코드** `src/engine/macro_models/agentic_views.py::compile_views` ·
  `src/engine/entropy_pooling.py` · `src/engine/entropy_views.py`
- **1차 문헌** Black & Litterman (1992) · Meucci (2010) 엔트로피 풀링

★갈리는 지점★ 뷰를 **부등식**으로 컴파일하고 실행가능성을 확인하지 않았으면
`feasible: null` 로 답한다(`true` 로 두지 않는다). 스펙 §16 의
*"LLM 은 뷰를 제안할 수 있으나 비중을 결정할 수 없다"* 는 **환경적으로도** 지켜진다 —
`llm`·`trends_api` 요건이 둘 다 미충족이라 그 경로가 아예 돌지 않는다.

---

## ENSEMBLE — 모델 결합 / 모델리스크

- **코드** `src/engine/macro_models/ensemble.py`(범주형 불일치) ·
  ★`src/engine/forecast_combination.py`(비음수 최소분산 결합 — **매크로에 미연결**)★
- **1차 문헌** 예측결합 문헌(Bates–Granger 계열) · BMA

★갈리는 지점★ 스펙 §17 이 요구하는 **가중 결합**은 `ensemble.py` 에 없다.
그것은 판정 불일치 집계다. 결합 기계는 저장소에 이미 있으나 다른 모듈에 있다.

---

## ML / TSFM / Neural SDE / PINN — 계약만

- **스펙 문헌** Coulombe 등 · Medeiros 등 · TimesFM · Chronos · PatchTST · DLinear
- **코드** ❌ **없음.** `Engine(...)` 선언과 `requires` 튜플뿐이다.

★관련성 판정★ 이 문헌들은 **현재 코드에 대응물이 없다.** 스펙 §31 이 "관련성을
검증하라" 고 했으므로, 대응 없음을 그대로 적는다. 그리고 `frontier_sample` 요건이
**관측 60 / 최소 240** 으로 미충족이라, 문헌을 적용할 **데이터 조건 자체가** 아직 없다.

---

## 스펙이 요구했으나 코드에 대응물이 전혀 없는 주제

| 주제 | 스펙 | 상태 |
|---|---|---|
| 실시간 나우캐스팅 | §6 (Giannone–Reichlin–Small 2008) | ❌ 없음 |
| 금융환경지수 FCI | §8 (Hatzius 등 2010) | ❌ 없음 |
| Growth-at-Risk | §15 (Adrian–Boyarchenko–Giannone) | ❌ 없음 |
| 국면조건부 자산 μ/σ/ρ | §21 | ⚠️ `conditional_market` 에 부분 존재(스튜디오 밖) |
