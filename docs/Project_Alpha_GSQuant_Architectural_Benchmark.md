# Project Alpha — Goldman Sachs `gs-quant` Architectural Benchmark & Integration Specification

> **Purpose:** Claude Code가 Project Alpha를 발전시킬 때 Goldman Sachs `gs-quant`를 단순 기능 참고자료가 아니라 **도메인 모델·데이터 컨텍스트·팩터 리스크·백테스트 엔진·포트폴리오 객체·최적화 제약 설계의 architectural benchmark**로 사용하도록 하는 공식 설계 문서.
>
> **Repository:** `head1320-cell/Project-Alpha`
>
> **Target branch:** `claude/backtest-modern-ui-refactor-akxvbc`
>
> **Benchmark repository:** `goldmansachs/gs-quant` (`master`)
>
> **Important:** GS Quant의 구현을 복사하거나 Goldman Sachs의 내부 서비스/인프라에 의존하지 않는다. **설계 원칙과 공개 코드에서 확인 가능한 domain architecture만 참고하여 Project Alpha에 맞게 재설계한다.**

---

# 1. Executive Decision

`gs-quant`를 분석한 결과, Project Alpha가 가장 크게 배워야 할 것은 "더 많은 금융모델"이 아니다.

가장 중요한 교훈은 다음이다.

> **금융 데이터를 직접 계산 함수에 전달하는 수준을 넘어서, Context → Dataset → Instrument/Asset → PositionSet → Portfolio → Factor/Risk Model → Constraint → Optimizer → Event/Execution이라는 명시적인 금융 도메인 모델을 구축한다.**

Project Alpha는 이미 다음 기능들을 갖고 있다.

- Screener
- Company
- Macro
- Backtester
- Risk
- Allocation Studio
- Data Infra
- PIT-oriented backtest workflow
- BL / Entropy Pooling / RP / HRP / MinVar / MaxDiv / CVaR
- Macro regime / transition / drivers / advanced macro models
- Company valuation / financial deep analysis / risk deep analysis
- Execution / Journal / attribution 흐름

따라서 지금 필요한 것은 기능 수를 늘리는 것이 아니라:

1. **같은 금융 객체가 모든 탭에서 재사용되도록 만들고**
2. **같은 데이터 컨텍스트가 모든 계산을 통제하도록 만들고**
3. **Backtester와 Allocation의 내부 계산 경계를 명확히 하고**
4. **Company / Macro / Risk / Allocation의 공통 factor/state model을 만들고**
5. **현재 Project Alpha의 웹 제품 특성은 유지하면서 GS Quant식 domain architecture만 차용하는 것**

이다.

---

# 2. What `gs-quant` Teaches Project Alpha

Public `gs-quant` repository has explicit top-level modules for:

- `analytics`
- `backtests`
- `data`
- `entities`
- `markets`

and the backtest package itself separates:

- action handling
- events
- data handling
- data sources
- execution engine
- generic engine
- backtest objects

The markets layer separately exposes concepts such as:

- assets
- factors
- factor analytics
- optimizer
- portfolio
- portfolio manager
- position sets
- historical data
- hedge functionality

The data layer separates concepts such as:

- datasets
- queries
- fields
- coordinates
- data contexts

This separation is more important than any single algorithm.

### Project Alpha adaptation

The target architecture should become:

```text
ResearchContext
      ↓
Dataset / Snapshot
      ↓
Instrument / Asset
      ↓
Position / PositionSet
      ↓
Portfolio
      ↓
Factor / Macro State
      ↓
Risk Model
      ↓
Constraint Set
      ↓
Optimizer
      ↓
Target Position Set
      ↓
Rebalance / Execution
      ↓
Attribution / Journal
```

This becomes the domain spine connecting all seven Project Alpha tools.

---

# 3. Do NOT Clone GS Quant

## Explicit non-goals

Do not:

- copy `gs-quant` modules wholesale,
- reproduce Goldman Sachs APIs,
- depend on Marquee,
- reproduce Goldman Sachs security master,
- reproduce enterprise entitlement systems,
- add complex nested portfolio operations without a product need,
- add financial instruments merely because GS Quant supports them,
- add an external queue or infrastructure merely because GS Quant is enterprise-grade.

Project Alpha has a different purpose:

> **A public-market quantitative research and portfolio decision platform with transparent calculations, reproducibility, PIT correctness, and user-facing research workflows.**

GS Quant is a benchmark for architecture, not a feature backlog.

---

# 4. Highest Priority Architectural Concepts to Adapt

## Priority S

### S1. `ResearchContext` / `DataContext`

Create a single conceptual context controlling every research calculation.

Proposed shape:

```python
ResearchContext(
    as_of_date,
    information_cutoff,
    universe_id,
    market_data_as_of,
    fundamental_data_as_of,
    macro_data_as_of,
    data_snapshot_id,
    engine_version,
    risk_model_version,
)
```

Every major engine should eventually accept or derive this context:

```python
company.analyze(context)
macro.analyze(context)
screener.run(context)
risk.calculate(context)
backtest.run(context)
allocation.optimize(context)
```

### Why this matters

It prevents:

- hidden dates,
- inconsistent snapshots,
- accidental look-ahead,
- inconsistent macro state,
- inconsistent risk model dates,
- non-reproducible results.

It should become the natural home for the platform's PIT policy.

---

# 5. PIT / Information Set Is Non-Negotiable

For every research value, distinguish:

```text
observation_date
publication_date
available_at
effective_date
revision/version
```

Example:

```text
2026 Q2 financials
observation_date = 2026-06-30
publication_date = 2026-08-14
```

A simulation dated 2026-07-01 must not use the financials.

The same requirement applies to:

- DART fundamentals
- macro indicators
- factor snapshots
- universe membership
- corporate actions
- price histories
- analyst data if ever added

---

# 6. S2. Dataset Abstraction

Project Alpha currently has multiple data stores and clients.

The long-term target should be:

```text
Dataset
├── prices
├── fundamentals
├── factors
├── macro
├── universe
├── corporate_actions
└── risk
```

The consumer should not need to know whether the source is:

- PostgreSQL,
- DART,
- KIS,
- KRX,
- cached snapshot,
- local derived table.

Example:

```python
prices = datasets.prices(
    universe="kr_equity",
    start="2015-01-01",
    end="2026-08-22",
    context=context,
)
```

The dataset layer owns:

- source resolution,
- PIT filtering,
- cache selection,
- snapshot selection,
- data quality,
- provenance.

### Important

Do not create a giant generic `DataSet` abstraction that hides all semantics.

Keep domain-specific interfaces:

```text
PriceDataset
FundamentalDataset
FactorDataset
MacroDataset
UniverseDataset
RiskDataset
```

with shared context/provenance conventions.

---

# 7. S3. Canonical Instrument / Asset Model

Do not treat `ticker` as the permanent identity of a security.

Introduce a canonical instrument concept:

```text
Instrument
├── instrument_id
├── ticker
├── exchange
├── market
├── asset_class
├── currency
├── listing_status
├── valid_from
├── valid_to
├── corporate_action_state
└── data_provenance
```

This supports:

- ticker changes,
- delistings,
- listings,
- corporate actions,
- ETF lifecycle,
- survivorship-safe universes.

---

# 8. Economic Exposure vs Instrument

Create a conceptual hierarchy:

```text
Economic Exposure
        ↓
Risk Factor Exposure
        ↓
Listed Instrument
        ↓
Position
```

Example:

```text
US Large Cap Equity
       ↓
US Equity Beta / Growth / Quality
       ↓
SPY
       ↓
Portfolio position
```

or:

```text
Gold
 ↓
Inflation / commodity factor
 ↓
GLD
 ↓
Portfolio position
```

This is especially important because Project Alpha has a constraint of using listed securities/products.

The optimizer should eventually optimize economic exposures and choose practical listed instruments for implementation.

---

# 9. S4. Position and PositionSet

Create an explicit position model.

Example:

```python
Position(
    instrument_id="KR_005930",
    quantity=120,
    weight=0.14,
    market_value=...,
    average_cost=...,
)
```

And:

```python
PositionSet(
    as_of_date=...,
    positions=[...],
    cash=...,
    currency="KRW",
)
```

Use the same domain object for:

- current holdings,
- historical holdings,
- target positions,
- backtest portfolio states,
- execution proposals.

Then:

```text
CurrentPositionSet
        ↓
TargetPositionSet
        ↓
TradeSet
```

becomes the canonical portfolio transition.

---

# 10. S5. Portfolio Object

The Portfolio should become a first-class domain object, not merely a weights array.

Target concept:

```text
Portfolio
├── identity
├── PositionSet
├── PortfolioMandate
├── RiskBudget
├── FactorExposure
├── MacroExposure
├── ConstraintSet
├── PortfolioContext
├── TargetWeights
├── TargetRanges
├── RebalancePolicy
└── DecisionMetadata
```

The existing `PortfolioDecisionState` concept should evolve in this direction.

---

# 11. S6. Factor Object Model

Factor should become a cross-platform object.

A factor must be able to represent:

- factor definition
- category
- exposure
- return
- volatility
- covariance
- correlation
- factor portfolio / mimicking portfolio
- model version

Conceptual interface:

```python
Factor(
    id="growth",
    category="macro",
)

factor.returns(...)
factor.volatility(...)
factor.covariance(...)
factor.correlation(...)
factor.mimicking_portfolio(...)
```

Do not copy GS Quant API signatures literally.

---

# 12. Factor Architecture for Project Alpha

Project Alpha should eventually distinguish:

### Style factors
- value
- momentum
- quality
- size
- profitability
- leverage

### Macro factors
- growth
- inflation
- liquidity
- policy
- credit
- USD
- real rates

### Market factors
- equity beta
- duration
- volatility
- credit beta
- commodity beta

### Specific risk
- idiosyncratic residual

This allows:

```text
Company
→ factor exposure

Portfolio
→ factor exposure

Risk
→ factor contribution

Macro
→ factor state

Allocation
→ factor constraints
```

This is a major architectural convergence point.

---

# 13. Factor Risk Model

Project Alpha should eventually support:

\[
\Sigma_{asset}
=
B\Sigma_{factor}B^	op + D
\]

where:

- \(B\) = asset-to-factor exposures
- \(\Sigma_{factor}\) = factor covariance
- \(D\) = specific risk

This is more scalable and interpretable than treating every asset covariance as a black box.

The model should support regime-conditioned versions later:

\[
\Sigma_{factor,t}
=
f(Regime_t)
\]

---

# 14. Factor Mimicking Portfolios

This is one of the most interesting GS Quant ideas for Project Alpha.

For a factor:

```text
Growth
Inflation
Duration
Credit
```

construct a liquid listed basket that approximately expresses the factor.

Example:

```text
Growth
→ QQQ + small-cap + cyclical basket

Inflation
→ Gold + commodity + TIPS-like listed vehicles

Duration
→ Treasury ETF basket
```

The purpose is NOT to exactly replicate an institutional risk model.

The purpose is to allow the user to see:

> "What tradable portfolio expresses this macro/factor view?"

This directly bridges Macro → Allocation.

---

# 15. S7. Constraint Objects

Do not let portfolio constraints remain an unstructured dictionary forever.

Create explicit concepts:

```text
ConstraintSet
├── AssetConstraint
├── SectorConstraint
├── CountryConstraint
├── FactorConstraint
├── LiquidityConstraint
├── TurnoverConstraint
├── ConcentrationConstraint
├── CashConstraint
└── ShortingConstraint
```

Each constraint should expose:

- lower bound
- upper bound
- unit
- scope
- source
- reason
- active date/context

This will make Allocation much easier to reason about.

---

# 16. Objective-Driven Allocation

Project Alpha already contains multiple optimizers.

Do NOT add another optimizer just to match GS Quant.

Instead introduce a higher-level:

```text
PortfolioObjective
```

Example:

```text
PortfolioObjective(
    expected_return_weight,
    volatility_weight,
    cvar_weight,
    factor_risk_weight,
    turnover_weight,
    concentration_weight,
)
```

The user should eventually specify:

> "I want high risk-adjusted return while limiting factor concentration, tail risk and turnover."

rather than selecting "HRP" as the primary user-level concept.

The engine can choose among:

- MVO
- BL
- Entropy Pooling
- RP
- HRP
- MinVar
- MaxDiv
- MinCVaR
- Robust optimization

based on the mandate.

---

# 17. Backtester — GS Quant Architectural Lesson

The biggest useful lesson from `gs-quant/backtests` is decomposition.

Target Project Alpha structure:

```text
BacktestJob
    ↓
DataSnapshot
    ↓
StrategyDefinition
    ↓
Signal Engine
    ↓
Event Stream
    ↓
Action Handler
    ↓
Execution Model
    ↓
Portfolio State
    ↓
Metrics
    ↓
Attribution
```

Recommended concepts:

```text
BacktestDataHandler
BacktestDataSource
BacktestEvent
BacktestAction
BacktestExecutionModel
BacktestPortfolioState
BacktestEngine
BacktestResult
```

Do not necessarily create all classes immediately.

First determine which current modules already fill these roles.

---

# 18. Backtester — Reliability Is More Important Than Feature Count

The current Project Alpha backtester has a durable run state, status polling, cancellation, retry and orphan handling.

The main risk is execution architecture:

```text
FastAPI process
    ↓
daemon threading.Thread per run
    ↓
CPU-heavy pure-Python simulation
```

combined with `uvicorn --workers 1`.

Treat this as an architecture issue.

Do not assume the root cause is:

> "Python is slow."

Diagnose separately:

- CPU saturation
- Python/GIL contention
- DB query latency
- DB pool contention
- memory pressure
- result serialization
- status polling
- worker/container failure.

---

# 19. Backtester — Required Investigation Before Optimization

Create a benchmark matrix:

### Small
5 assets × 1 year

### Medium
20 assets × 5 years

### Large
100 assets × 10+ years

### Stress
200+ assets × long history × complex rules

Measure:

- wall time
- CPU time
- peak RSS
- DB queries
- DB query duration
- data conversion time
- simulation time
- metrics time
- serialization time
- persistence time
- concurrent run behavior

Only after measurement decide:

- bounded process workers,
- PostgreSQL-backed queue,
- dedicated simulation service,
- NumPy optimization,
- Numba,
- C++/Rust/Cython.

Do not start with C++.

---

# 20. Backtester — Data Loading

Prefer:

```text
N ticker queries
```

→

```text
one/few bulk queries
```

→

```text
compact in-memory arrays
```

→

```text
simulation
```

where correctness permits.

The DataSnapshot should have:

```text
snapshot_id
universe_version
data_version
as_of
availability_cutoff
price_adjustment_policy
source
```

This makes the backtest both faster and reproducible.

---

# 21. Backtester — Event Model

Potential event vocabulary:

```text
MarketEvent
SignalEvent
OrderEvent
FillEvent
RebalanceEvent
CorporateActionEvent
CashEvent
```

The strategy should produce signals/actions.

The execution model decides:

- whether the order can fill,
- what price it receives,
- slippage,
- fees,
- partial fills,
- liquidity constraints.

Do not conflate strategy correctness with fill mechanics.

This separation will also help later performance optimization.

---

# 22. Backtester — Result Model

Create a stable `BacktestResult`.

It should include:

```text
run_id
engine_version
data_snapshot_id
input_snapshot
portfolio_curve
returns
trades
exposures
factor_exposures
regime_exposure
drawdown
risk_metrics
cost_breakdown
attribution
OOS metrics
validation status
```

The frontend should consume this canonical result rather than depending on engine-internal structures.

---

# 23. Company — GS Quant Lesson

The main lesson is not "add more valuation models."

The lesson is:

> **Represent securities, data context, factors, exposures and analytics as reusable domain objects.**

Project Alpha Company should become:

> **Security Underwriting Engine**

rather than only a dashboard.

---

# 24. CompanySnapshot

Create a canonical CompanySnapshot concept:

```text
CompanySnapshot
├── security identity
├── as_of / information cutoff
├── price
├── market cap
├── financial periods
├── publication dates
├── financial statements
├── factor exposures
├── valuation assumptions
├── valuation distribution
├── peer set
├── macro sensitivities
├── risk measures
├── thesis
├── catalysts
├── kill conditions
├── provenance
└── model versions
```

All Company tabs should read from/reuse this model where possible.

---

# 25. Company — Valuation Upgrades

Priority features:

### Reverse DCF

Infer what the current market price assumes about:

- growth
- margin
- WACC
- terminal growth
- reinvestment

### Probabilistic valuation

Return:

```text
P10 / P25 / P50 / P75 / P90
```

rather than one intrinsic value.

### Sensitivity decomposition

Explain which assumptions contribute most to valuation uncertainty.

Do not use AI to generate the valuation numbers.

AI may explain the quantitative result.

---

# 26. Company — Earnings Quality

Evaluate:

- earnings vs cash flow
- accruals
- working capital
- one-offs
- FCF conversion
- margin durability
- capex intensity
- debt burden
- cash conversion

Existing Altman/Beneish become components of a broader underwriting framework.

---

# 27. Company — Capital Allocation

Analyze:

\[
ROIC \quad vs \quad WACC
\]

and:

- reinvestment
- M&A
- buybacks
- dividends
- debt repayment
- cash accumulation

The question is:

> Is incremental capital creating value?

---

# 28. Company — Macro Sensitivity

Build quantitative bridges:

```text
GDP -2σ       → EPS / fair value impact
Inflation +2σ → margin / valuation impact
10Y +100bp    → fair value impact
USD +10%      → earnings impact
Commodity +30%→ margin impact
Credit spread → financing impact
```

The output should be numerical and reproducible.

---

# 29. Company — Thesis Object

Create a structured thesis model:

```text
InvestmentThesis
├── why_now
├── mispricing_mechanism
├── expected_catalysts
├── fundamental_drivers
├── macro_dependencies
├── target_case
├── bear_case
├── kill_conditions
└── confidence
```

Later:

```text
Thesis
→ Signal
→ Backtest
→ Risk
→ Allocation
```

This is a key differentiator for Project Alpha.

---

# 30. Analytics / Processor Pattern

Learn from the separation in GS Quant's analytics layer.

Target:

```text
Raw Engine Result
       ↓
Analytics Processor
       ↓
Canonical Result Model
       ↓
Frontend Widget / DataGrid
```

This prevents individual frontend widgets from encoding financial logic.

Good candidates:

- valuation processor
- factor processor
- risk processor
- backtest attribution processor
- portfolio exposure processor.

---

# 31. Portfolio Context

Create a common portfolio context:

```text
PortfolioContext
├── portfolio_id
├── pricing_date
├── market_data_as_of
├── macro_state_id
├── risk_model_id/version
├── universe_id/version
├── data_snapshot_id
└── engine_version
```

This allows the system to explain:

> Why did today's portfolio risk differ from yesterday?

because the system can identify exactly what changed:

- market prices,
- macro state,
- risk model,
- holdings,
- data snapshot.

---

# 32. Research Workflow — Project Alpha Must Go Beyond GS Quant

GS Quant is the benchmark, but Project Alpha has a product advantage:

```text
Screener
→ Company
→ Macro
→ Thesis
→ Backtest
→ Risk
→ Allocation
→ Execution
→ Journal
```

This research workflow should remain Project Alpha's own identity.

Do not turn Project Alpha into a generic quant Python SDK.

The goal is:

> **GS Quant-like domain rigor + Project Alpha's research workflow and user-facing decision system.**

---

# 33. Seven-Tool Convergence

Target:

```text
                         Data Infra
                              │
                 ┌────────────┴────────────┐
                 ↓                         ↓
              Screener                  Macro
                 │                         │
                 ↓                         ↓
              Company                Market State
                 │                         │
                 └────────────┬────────────┘
                              ↓
                           Thesis
                              ↓
                          Backtester
                              ↓
                             Risk
                              ↓
                         Allocation
                              ↓
                         Execution
                              ↓
                     Attribution / Journal
```

Shared domain primitives:

```text
ResearchContext
Dataset
Instrument
Factor
Position
PositionSet
Portfolio
RiskModel
ConstraintSet
PortfolioObjective
BacktestResult
InvestmentThesis
```

These are more important than adding another tab.

---

# 34. Recommended Implementation Order

## Phase 0 — Architectural Audit

Do not modify production code yet.

Map current Project Alpha modules to:

```text
Context
Dataset
Instrument
Position
Portfolio
Factor
Risk
Constraint
Backtest
Execution
Analytics
```

Classify each as:

- exists
- partial
- missing
- duplicated
- unsafe
- candidate for reuse.

---

## Phase 1 — Context + Data Foundation

Implement only the minimum required foundation:

- ResearchContext
- canonical as-of semantics
- data snapshot/provenance contract
- canonical instrument identity
- dataset interfaces where justified.

Do not rewrite every data source.

---

## Phase 2 — Backtester Architecture

Before performance optimization:

- separate data handling
- separate event model
- separate execution model
- separate portfolio state
- separate metrics/result.

Then benchmark.

---

## Phase 3 — Backtester Performance

Only after profiling:

- bulk data loading
- bounded worker processes
- memory reduction
- NumPy/Numba where justified
- compiled kernel only if needed.

---

## Phase 4 — Factor/Risk Foundation

Build:

- Factor
- FactorExposure
- FactorRiskModel
- Factor covariance
- Factor contribution
- factor constraints.

---

## Phase 5 — Company Underwriting

Build:

- CompanySnapshot
- Reverse DCF
- valuation distribution
- earnings quality
- capital allocation
- macro sensitivity
- thesis / kill conditions.

---

## Phase 6 — Portfolio Domain Model

Build:

- Position
- PositionSet
- Portfolio
- PortfolioContext
- ConstraintSet
- PortfolioObjective.

Then connect to the existing Allocation optimizers.

---

## Phase 7 — Dynamic Allocation

Integrate:

```text
Macro regime
→ conditional μ / Σ / tail
→ factors
→ investor views
→ optimizer
→ target range
→ rebalance policy
```

---

# 35. What NOT to Implement From GS Quant

Do not port:

- Goldman-specific APIs
- Marquee authentication/session
- enterprise entitlements
- Goldman asset identifiers as a dependency
- Goldman portfolio storage
- institutional workflows irrelevant to the product
- complex derivatives/pricing engines unless Project Alpha has a concrete requirement.

---

# 36. Acceptance Tests

Any architecture inspired by this document must satisfy:

### Reproducibility

Same:

```text
ResearchContext
+
DataSnapshot
+
ModelVersion
+
Inputs
```

→ same result.

### PIT

No future information leakage.

### Domain reuse

The same Instrument/Factor/Position concepts are reusable across tools.

### Backtest isolation

A heavy backtest must not starve Company/Macro/API operations.

### Performance

Before/after benchmark must prove improvement.

### Explainability

Every major result can identify:

- data source
- snapshot
- model version
- assumptions
- unavailable components.

### Product coherence

Company and Macro results can become Backtest/Risk/Allocation inputs without manual re-encoding.

---

# 37. Claude Code Operating Rules

When implementing this specification:

1. Inspect current code before creating new abstractions.
2. Prefer reuse and adapters over rewrites.
3. Do not create `GSQuantLike*` naming or copy GS Quant structure literally.
4. Keep domain objects small and composable.
5. Keep the API/frontend contracts stable where practical.
6. Use tests before implementation changes.
7. Add performance benchmarks before and after performance work.
8. Do not infer performance bottlenecks without measurement.
9. Do not use AI-generated numbers as the source of quantitative decisions.
10. Preserve mock-data honesty and PIT/data-safety rules.
11. Keep execution/trading safety unchanged.
12. Stop after design review if the architectural change is broad enough to warrant approval.

---

# 38. Final Architectural North Star

The strongest synthesis of Project Alpha and GS Quant is:

```text
                      RESEARCH CONTEXT
                              │
                      DATASET / SNAPSHOT
                              │
                       INSTRUMENT MASTER
                              │
          ┌───────────────────┼───────────────────┐
          ↓                   ↓                   ↓
       COMPANY              MACRO              MARKET
          ↓                   ↓                   ↓
      FACTORS             STATE VECTOR       PRICES
          └───────────────────┼───────────────────┘
                              ↓
                           THESIS
                              ↓
                    SIGNAL / STRATEGY
                              ↓
                    BACKTEST ENGINE
                              ↓
               RETURNS / FACTOR / RISK
                              ↓
                         PORTFOLIO
                              ↓
                  OBJECTIVE + CONSTRAINTS
                              ↓
                         OPTIMIZER
                              ↓
                     TARGET POSITIONS
                              ↓
                     REBALANCE POLICY
                              ↓
                        TRADE SET
                              ↓
                         JOURNAL
```

The end product should answer one integrated question:

> **Given the information actually available at the decision date, what do we believe about the security/market, how strong is the thesis, how has that thesis performed historically, what risks and factors drive it, how should capital be allocated, and is changing the portfolio justified after uncertainty, liquidity and transaction costs?**

That is the standard Project Alpha should aim for.

---

# 39. Immediate Task for Claude Code

Before any production implementation:

1. Read this specification.
2. Read `CLAUDE.md`.
3. Read the existing Project Alpha architecture docs.
4. Inspect the actual source code.
5. Map existing components against:
   - ResearchContext
   - Dataset
   - Instrument
   - Position/PositionSet
   - Portfolio
   - Factor
   - RiskModel
   - ConstraintSet
   - BacktestEngine
   - AnalyticsProcessor
6. Map each relevant Project Alpha module against the corresponding `gs-quant` concept.
7. Produce a gap matrix.
8. Identify reusable existing modules.
9. Identify the smallest viable first vertical slice.
10. Do not implement the full architecture until the gap analysis and migration plan are reviewed.

The objective is not to make Project Alpha look like Goldman Sachs code.

The objective is to make Project Alpha **architecturally rigorous enough to support its own Research-to-Portfolio vision.**
