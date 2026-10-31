# Project Alpha — Dynamic Portfolio Decision Engine Design Brief

## 0. 목적

Project Alpha의 Macro 분석 탭과 Allocation Studio(ASS)를 별도 기능으로 고도화하는 것이 아니라,
둘을 하나의 **Dynamic Portfolio Decision Engine**으로 통합한다.

핵심 질문은 다음으로 바꾼다.

> 현재 경제/시장 상태에서 미래 자산수익률·변동성·상관·꼬리위험의 조건부 분포는 어떻게 달라지는가?
> 그 불확실성을 고려했을 때 목표 포트폴리오는 무엇이며,
> 현재 포트폴리오에서 실제로 언제·얼마나 리밸런싱해야 하는가?

최종 파이프라인:

DATA → STATE ESTIMATION → REGIME DISTRIBUTION → CONDITIONAL ASSET DISTRIBUTION
→ VIEWS/PRIORS → PORTFOLIO OPTIMIZATION → TARGET RANGE
→ REBALANCING POLICY → EXECUTION PLAN → OOS EVALUATION → JOURNAL

---

## 1. 현재 코드베이스에 대한 판단

대상 브랜치:
`claude/backtest-modern-ui-refactor-akxvbc`

현재 Project Alpha는 이미 상당한 기반을 갖추고 있다.

### Macro
- 4-quadrant regime + stress
- KR/US 분리
- regime ensemble
- regime transition / forecast
- exact driver decomposition
- LATENT / TERM / CAUSAL / TAIL / VIEWS studio
- tactical allocation strategies
- macro recommendation
- macro embedded allocation

### Allocation Studio
현재 다단계 파이프라인:

`MACRO → CONSTRUCT → ALPHA LAB → THESIS → TIMING → OPTIMIZE → STRESS → ATTRIBUTION → EXECUTION → JOURNAL`

지원 모델:
- MVO
- Black-Litterman
- Entropy Pooling
- Risk Parity
- HRP
- Min Variance
- Max Diversification
- Min CVaR

추가 기반:
- user views
- factor builder
- stress scenarios
- sensitivity heatmap
- walk-forward OOS backtest
- turnover cost
- conformal prediction
- decision journal
- execution room

### 중요한 기존 설계 원칙
1. 모델/데이터가 unavailable이면 허위 숫자를 만들지 않는다.
2. frontier model과 실제 실행 가능한 substitute를 구분한다.
3. model disagreement를 평균으로 숨기지 않는다.
4. walk-forward에서 look-ahead를 막는다.
5. 설명 가능성/attribution을 유지한다.

이 원칙은 유지한다.

---

## 2. 가장 중요한 구조적 문제

현재 시스템은 사실상:

`Macro → Signal/Recommendation → Weight`

에 가깝다.

다음 단계에서는:

`Macro → Conditional Distribution → Portfolio Optimization → Rebalancing`

이어야 한다.

즉 Macro signal이 ETF weight를 직접 조절하는 구조에서,
Macro state가 **미래 기대수익률 μ, 공분산 Σ, tail risk**를 바꾸고,
그 결과 optimizer가 weight를 결정하는 구조로 전환한다.

현재 `macro_allocation.py`의 선형 4계절 틸트는 폐기하지 않는다.
오히려 **baseline allocation model**로 유지하여 새로운 모델을 검증하는 benchmark로 사용한다.

---

## 3. 최종 목표 아키텍처

```text
                        DATA
                         |
          +--------------+--------------+
          |              |              |
        Macro          Market       Cross-Asset
          +--------------+--------------+
                         |
                  STATE ENGINE
                         |
       +-----------------+-----------------+
       |                 |                 |
     Regime            Latent          Tail/Risk
    Forecast           Factors           State
       +-----------------+-----------------+
                         |
                P(REGIME future)
                         |
             CONDITIONAL MARKET MODEL
                 /        |        \
                μ         Σ        Tail
                 \        |        /
                  +-------+-------+
                          |
                     INVESTOR VIEWS
                          |
                BL / Entropy Pooling
                          |
                  PORTFOLIO OPTIMIZER
                          |
                    TARGET RANGE
                          |
                 REBALANCING POLICY
                          |
                    EXECUTION PLAN
                          |
                   OOS / JOURNAL
```

핵심 공통 객체 후보:

`PortfolioDecisionState`

포함 후보:
- as_of / information-set timestamp
- investable universe version
- current holdings
- macro state
- regime probabilities
- regime transition probabilities
- market forecasts
- conditional expected returns
- conditional covariance
- tail-risk state
- factor exposures
- user views
- risk budgets
- optimization model/configuration
- target weights
- target ranges
- dynamic rebalance bands
- expected turnover
- transaction cost
- model agreement/disagreement
- confidence
- execution candidates

---

## 4. Macro vNext

### 4.1 Current regime보다 forward regime distribution이 우선

현재:
- current regime
- current probability

추가 목표:
- 1M / 3M / 6M forward regime probability
- transition matrix
- expected duration
- transition risk
- regime uncertainty

단일 HMM에 의존하지 않는다.
가능한 경우 다음을 ensemble로 유지한다.
- axis-based structural regime
- state-space / dynamic factor
- Markov/HMM transition
- market regime
- credit regime
- tail regime

모델 간 합의를 억지로 평균내지 말고 disagreement를 별도 정보로 유지한다.

### 4.2 Macro state vector

Growth / Inflation만으로 끝내지 않는다.
가능한 핵심 상태:
- Growth
- Inflation
- Liquidity
- Policy
- Credit
- Valuation
- Market Risk
- USD / FX

이 상태는 단순 dashboard 숫자가 아니라 향후 자산분포 모델의 input이 된다.

### 4.3 LATENT의 승격

DFM/TSFM latent factor는 분석 결과로 끝나지 않고:

`latent state → μ / σ / correlation forecast`

로 연결되어야 한다.

### 4.4 TERM의 승격

Nelson-Siegel / real yield / breakeven / term premium proxy를:

`yield curve state → duration expectation / bond risk`

으로 연결한다.

### 4.5 CAUSAL의 역할 재정의

Granger/causal graph를 “매매신호”로 쓰지 않는다.

대신:
- leading indicator discovery
- forecast feature selection
- causal hypothesis generation

에 사용한다.

### 4.6 TAIL의 승격

POT/EVT를 단순 VaR/ES 화면에서 끝내지 않고:

`tail state → risk budget / de-risking / optimizer penalty`

로 연결한다.

### 4.7 VIEWS의 승격

User/AI view → inequality → Entropy Pooling / BL posterior로 연결한다.

AI가 최종 weight를 직접 결정하지 않는다.
AI의 역할은:
- evidence extraction
- view proposal
- explanation

이며, 수치 결정은 deterministic/quantitative engine이 수행한다.

---

## 5. Conditional Cross-Asset Model — 최우선 신규 계층

가장 중요한 신규 엔진.

각 투자 가능 자산/경제노출에 대해:

`r_{i,t+1} | state_t, regime_t`

를 추정한다.

핵심 출력:
- conditional expected return μ
- conditional volatility σ
- conditional covariance Σ
- conditional correlation
- downside / tail parameters

가능한 구조:
- regime-conditional historical estimates
- dynamic factor model
- shrinkage covariance
- Bayesian forecast combination
- robust uncertainty intervals

자산의 macro sensitivity는 고정 coefficient 하나로 영구 고정하지 않는다.
regime/time-varying sensitivity를 고려한다.

---

## 6. Forecast Combination

단일 forecast를 믿지 않는다.

예:
- macro forecast
- trend forecast
- valuation forecast
- factor forecast
- market-implied prior

각 forecast에 uncertainty를 붙이고 결합한다.
단순 평균보다 precision/uncertainty-aware combination을 우선 검토한다.

---

## 7. Investable Universe — 2026-08 제약

플랫폼의 기본 가정:

> **상장된 기업 및 상장 금융상품만 실제 투자 대상으로 사용할 수 있다.**

구체적으로 실제 지원 범위는 코드/데이터 소스를 조사하여 확정해야 한다.
후보:
- listed stocks
- ETFs
- ETNs/ETPs
- REITs
- listed bonds
- liquid listed commodity vehicles
- 기타 실제 거래 가능한 상장상품

### 7.1 Economic Exposure와 Instrument 분리

예:

`US Equity → SPY / VOO / IVV`

optimizer는 Economic Exposure를 결정하고,
Implementation layer가 실제 listed instrument를 선택한다.

### 7.2 Instrument selector

최소 고려:
- liquidity
- spread / estimated execution cost
- trading history
- tracking error
- expense ratio / fee where available
- data quality
- listing/active status
- corporate actions
- tax/market-specific implementation constraints where supported

### 7.3 Survivorship bias

현재 상장 목록을 과거에 그대로 적용하면 안 된다.

backtest date t의 investable universe는 **t 시점에 실제 투자 가능했던 상품**을 기준으로 해야 한다.

### 7.4 Data availability

모든 macro data에:
- observation date
- publication/availability date
- revision information where possible

를 구분한다.

의사결정 시점 t에는 `availability_date <= t`인 정보만 허용한다.

---

## 8. Allocation Optimizer vNext

현재 optimizer model zoo는 유지한다.

다만 “모델을 고르는 UI”보다 “투자 목적 + risk budget을 정의하고 적합한 optimizer를 적용”하는 구조가 우선이다.

### 8.1 Objective
가능한 objective:
- growth
- balanced
- capital preservation
- income
- inflation hedge
- tail-risk minimization
- robust allocation

### 8.2 Risk budget
λ 하나로 끝내지 않는다.

예:
- volatility budget
- max drawdown budget
- CVaR / ES budget
- concentration budget
- liquidity budget
- turnover budget

### 8.3 Robust Optimization

Expected return/covariance uncertainty set을 명시적으로 고려한다.

예:
`μ ∈ U_mu`, `Σ ∈ U_sigma`

그리고 최악조건에서도 유효한 allocation을 찾는 robust objective를 검토한다.

### 8.4 Factor-aware optimization

asset count가 아니라 factor count를 본다.

최소 고려 factor:
- equity beta
- duration
- growth
- inflation
- value
- momentum
- quality
- credit
- commodity
- USD/FX
- volatility/liquidity

추후 Factor Effective Number of Bets까지 확장한다.

---

## 9. Target Weight가 아니라 Target Range

최적 비중 하나만 제공하지 않는다.

예:
- target
- low/high range
- confidence
- model dispersion

예상:
`SPY target 30%, acceptable range 25~34%`

불확실성이 높으면 range를 넓히고 position sizing을 축소한다.

---

## 10. Rebalancing Policy Engine — 매우 중요

현재 포트폴리오에서 실제로 거래해야 하는지를 별도 판단한다.

핵심 요소:
- target weight gap
- signal confidence
- forecast change
- regime persistence
- transaction cost
- liquidity
- turnover budget
- portfolio risk impact

핵심 rule의 예:

`Trade if expected utility improvement > transaction cost + hysteresis`

### Dynamic rebalance band

고정 ±5% 같은 band를 기본값으로 두지 않는다.

`band = f(transaction_cost, volatility, uncertainty, liquidity, signal persistence)`

로 설계한다.

### Gradual rebalance

신뢰도가 낮으면 목표까지 즉시 이동하지 않는다.

`trade_target = current + α(confidence) * (target - current)`

같은 구조를 검토한다.

---

## 11. Timing은 binary signal이 아니라 Risk Budget

Risk-On / Risk-Off 하나로 끝내지 않는다.

`RiskBudget ∈ [0,1]`

으로 만들고 optimizer의 risk capacity를 조절한다.

예:
- 0.85 = risk assets에 높은 capacity
- 0.45 = defensive tilt + lower beta

---

## 12. Stress / Scenario Engine vNext

현재 stress/sensitivity 기반을 유지하고 확장한다.

### Forward shock
- growth shock
- inflation shock
- real yield shock
- credit spread shock
- USD shock
- oil/commodity shock
- equity crash
- correlation breakdown

### Joint scenario
단일 shock을 넘어 realistic joint macro scenarios를 정의한다.

### Reverse stress

“포트폴리오가 -15% 손실을 보려면 어떤 macro shock 조합이 필요한가?”를 계산한다.

---

## 13. Model Risk / Model Dispersion

여러 optimizer/forecast의 차이를 정보로 취급한다.

예:

Model A 40%
Model B 20%
Model C 35%
Model D 12%

→ dispersion high
→ confidence down
→ position size / rebalance intensity down

합의 평균만 보여주지 말고:
- model range
- dispersion
- agreement score
- disagreement drivers

를 보여준다.

---

## 14. Policy Backtest / OOS Credibility

현재 walk-forward backtest를 핵심 validation engine으로 유지한다.

비교 대상은 단순 전략이 아니라 **전체 policy**다.

`Model + Views + Constraints + Rebalancing + Costs + Universe`

평가:
- CAGR
- Sharpe
- Sortino
- Calmar
- MDD
- VaR/CVaR/ES
- turnover
- transaction cost
- regime-wise P&L
- tail loss
- recovery time
- forecast error

### Counterfactual attribution

반드시 비교 가능해야 한다.
- actual
- without macro
- without timing
- without views
- without risk overlay

이로써 각 시스템 component가 실제로 alpha/risk reduction을 만들었는지 검증한다.

---

## 15. Frontend UX 방향

### Macro top-level
정보를 모두 첫 화면에 넣지 않는다.
최상위 화면은:
1. current state
2. forward regime distribution
3. model agreement/disagreement
4. portfolio implications
5. link to Allocation

중심으로 재편한다.

### Allocation top-level
사용자가 “MVO냐 HRP냐”부터 고르는 것이 아니라:
- investment objective
- horizon
- risk budget
- universe
- constraints
- rebalance philosophy

를 정의하고, 적절한 model을 아래에서 선택/비교하게 한다.

### Macro → Allocation handoff
현재 handoff를 유지하되 단순 “추천 ETF 100% prefill”이 아니라:

`Macro state snapshot → regime probabilities → expected distribution → risk budget → thesis/views → optimizer inputs`

전체를 전달한다.

---

## 16. Decision State / Research Reproducibility

모든 투자 결정은 재현 가능해야 한다.

저장해야 할 것:
- decision timestamp
- information set
- model versions
- data versions/snapshot IDs
- universe version
- macro state
- regime distribution
- forecasts
- views
- constraints
- optimizer config
- target range
- trade decision
- expected outcome
- realized outcome
- review

과거 날짜의 결정을 현재 데이터로 다시 계산하는 구조를 만들지 않는다.

---

## 17. AI 원칙

AI는 deterministic numerical engine의 대체재가 아니다.

AI의 역할:
- evidence extraction
- text → structured view proposal
- scenario hypothesis generation
- explanation
- research assistance

AI가 직접:
`SPY = 31.7%`
같은 최종 비중을 결정하지 않는다.

최종 weight는 quantitative engine에서 계산되고 provenance가 남아야 한다.

---

## 18. 우선순위

### P0
1. Architecture audit + common decision state 설계
2. Investable universe / survivorship / availability-date audit
3. Macro → conditional μ/Σ 연결 설계

### P1
4. forward regime distribution
5. forecast combination
6. factor-aware risk model
7. robust optimizer
8. target range + model dispersion

### P2
9. dynamic rebalance policy
10. scenario + reverse stress
11. economic exposure → instrument selector
12. policy-level OOS evaluation / counterfactual attribution

### P3
13. decision state/versioning hardening
14. advanced AI
15. RL / multi-period optimization

**새로운 fancy model(Neural SDE/TSFM/PINN 등)을 먼저 추가하지 않는다.**
현재의 모델들을 실제 portfolio decision pipeline에 연결하는 것이 우선이다.

---

## 19. 반드시 지킬 원칙

1. 현재 코드의 실제 동작을 먼저 읽고 제안한다.
2. 기존 엔진을 중복 구현하지 않는다.
3. baseline model을 버리지 않는다.
4. unavailable data/model을 숫자로 위조하지 않는다.
5. look-ahead bias를 허용하지 않는다.
6. survivorship bias를 허용하지 않는다.
7. model disagreement를 숨기지 않는다.
8. AI를 숫자 결정의 단일 출처로 사용하지 않는다.
9. “최고 백테스트 수익률”만으로 모델을 선택하지 않는다.
10. 모든 결과에 provenance와 uncertainty를 남긴다.
11. 실거래 기능은 existing safety gate를 우회하지 않는다.
12. 하나의 거대한 리팩터링으로 가지 말고 작은 vertical slice로 검증한다.

---

## 20. Claude Code에 기대하는 작업 순서

이 문서는 **즉시 구현 명령서가 아니다.**

먼저 현재 브랜치의 실제 코드를 전부 감사한다.
특히 다음 연결을 추적한다.

`Macro API → Macro entities → Macro widgets → Macro handoff`

`Allocation API → allocation engine → AllocationProvider → each Allocation stage → backtest`

그 다음:

1. 현재 architecture map 작성
2. 기존 기능 중 재사용 가능한 것 식별
3. 위 목표와 현재 코드의 gap matrix 작성
4. 2~3개 구현 전략 제안
5. 추천 전략 선택 이유 제시
6. 하나의 좁은 vertical slice를 첫 구현 단위로 정의
7. TDD-first 계획 작성
8. 계획 승인 전에는 코드를 수정하지 않는다.

특히 첫 vertical slice는 가능하면:

`Macro State / Regime → Conditional μ/Σ → Allocation optimizer → target range`

의 최소 end-to-end 경로가 되어야 한다.

그 후 rebalancing policy를 붙인다.

---

## 21. 성공 기준

기능이 많아지는 것이 성공이 아니다.

다음 질문에 시스템이 실제 코드로 답할 수 있어야 한다.

> “2026-08-17 시점에 공개시장 상장상품으로만 투자한다고 할 때,
> 현재 macro/market state를 고려해 어떤 경제적 노출을 가져가야 하는가?
> 그 기대수익률과 위험은 무엇인가?
> 모델들이 얼마나 동의하는가?
> 현재 portfolio에서 무엇을 얼마만큼 바꿔야 하는가?
> 거래비용을 고려하면 실제로 거래할 가치가 있는가?
> 그 판단은 과거에도 out-of-sample에서 유효했는가?
> 그리고 3개월 뒤에 우리가 틀렸다면 왜 틀렸는가?”

이 질문에 재현 가능하고 수치적으로 검증 가능한 답을 제공하는 것이 Project Alpha vNext의 목표다.

---

## 22. 외부 참고 방향

외부 연구/기관 자료는 구현 결정을 위한 근거이지 복제 대상이 아니다.
주요 참고 주제:
- total portfolio approach
- macro regime diversification
- conditional asset return/covariance modeling
- robust portfolio optimization
- scenario-driven risk workflow
- trend following / liquid alternative diversification
- dynamic rebalancing / regime transition

외부 자료의 최신성은 구현 시점에 다시 검증한다.
