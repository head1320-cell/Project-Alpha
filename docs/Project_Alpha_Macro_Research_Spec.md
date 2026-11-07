# Project Alpha — Macro Research & Portfolio Decision Engineering Specification

This is the canonical research-engineering specification for evolving `src/engine/macro_models` into a production-quality macro state, forecasting, risk, and portfolio-decision engine.

## 1. Mission

Project Alpha's macro layer is not an academic forecasting sandbox. Its purpose is:

**point-in-time information set → macro state → probabilistic forecast → asset distribution → portfolio decision → realized outcome → attribution.**

Every model must pass four gates:

1. mathematical correctness,
2. point-in-time/data correctness,
3. out-of-sample validation,
4. demonstrable portfolio decision value.

More sophisticated is not automatically better.

## 2. Current model surface

Current macro-model modules include:

- `base.py`
- `tsfm_latent.py`
- `neural_sde.py`
- `pinn_tail.py`
- `causal_deepm.py`
- `ensemble.py`
- `agentic_views.py`

Conceptual studios:

- LATENT
- TERM
- CAUSAL
- TAIL
- VIEWS
- ENSEMBLE

The first audit must map the real implementation, not infer behavior from names.

## 3. Canonical research contract

Every result should eventually be reproducible from:

```text
ResearchContext
+
DataSnapshot
+
ModelVersion
+
Parameters
```

Conceptual context:

```python
ResearchContext(
    as_of_date,
    information_cutoff,
    macro_data_version,
    market_data_version,
    universe_version,
    model_version,
)
```

PIT metadata must distinguish:

```text
observation_date
publication_date
available_at
effective_date
revision/version
```

No historical decision may use revised information that was unavailable at the decision timestamp.

## 4. Canonical MacroState

Long-term conceptual contract:

```python
MacroState(
    as_of,
    information_cutoff,
    data_snapshot_id,
    latent_factors,
    growth_state,
    inflation_state,
    liquidity_state,
    policy_state,
    credit_state,
    financial_conditions,
    current_regime_probabilities,
    forward_regime_probabilities,
    expected_duration,
    expected_growth_distribution,
    expected_inflation_distribution,
    yield_curve_state,
    tail_state,
    asset_return_views,
    asset_risk_views,
    model_agreement,
    model_uncertainty,
    model_versions,
)
```

Do not implement this entire object blindly; first map existing outputs and boundaries.

# 5. LATENT / Dynamic Factor Model

### Primary references
- Stock & Watson (2002), *Macroeconomic Forecasting Using Diffusion Indexes*
- Giannone, Reichlin & Small (2008), *Nowcasting: The Real-Time Informational Content of Macroeconomic Data*
- Doz, Giannone & Reichlin, two-step/state-space Dynamic Factor Model work
- Bai & Ng, factor-number selection

### Required reasoning

Do not equate PCA with a Dynamic Factor Model.

Audit:

- factor dimension selection,
- factor loadings,
- idiosyncratic components,
- temporal dynamics,
- missing data,
- transformations,
- standardization,
- mixed frequency,
- release timing,
- factor identification,
- forecast horizon.

Target:

```text
Raw Macro Panel
→ PIT / Vintage Filter
→ Transformations
→ Release Alignment / Missingness
→ Standardization
→ Factor Dimension Selection
→ Dynamic Factor Model
→ Latent State
→ Forecast Distribution
```

Diagnostics:
- factor/loading stability,
- reconstruction error,
- forecast accuracy,
- pseudo-real-time stability.

Interpret latent-factor labels only when supported by loadings/economic relationships.

# 6. Real-time Nowcasting

Primary reference: Giannone, Reichlin & Small (2008).

Macro releases are asynchronous:

```text
CPI
Employment
PMI
Retail Sales
Industrial Production
GDP
```

Target:

```text
Vintage t
→ New Release
→ Update Information Set
→ Update State
→ Update Nowcast
→ Update Regime Probability
→ Update Asset View
```

Revision history must remain available.

# 7. REGIME / Markov Switching

Primary reference: Hamilton (1989), *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*.

Use:

\[
P(S_t=k|X_{1:t})
\]

and:

\[
P(S_{t+h}=j|X_t)
\]

rather than only hard labels.

Required outputs:

```text
Current regime probability
Forward regime probability
Transition matrix
Expected duration
State uncertainty
Model agreement
```

Labels such as Goldilocks/Reflation/Stagflation/Disinflation are interpretation layers, not the mathematical state itself.

# 8. FINANCIAL CONDITIONS

Primary reference: Hatzius et al. (2010), *Financial Conditions Indexes: A Fresh Look after the Financial Crisis*.

Potential components:

```text
Rates
Credit
Equity
FX
Volatility
Liquidity
Financial Conditions
```

Estimate a financial conditions state and validate its predictive relationship to future growth/inflation.

FCI is a state variable, not automatically a trading signal.

# 9. TERM / Dynamic Nelson-Siegel

Primary reference: Diebold & Li (2006), *Forecasting the Term Structure of Government Bond Yields*.

Required state:

```text
Level
Slope
Curvature
```

Where justified also:

```text
Real Yield
Breakeven Inflation
Term Premium
```

Secondary reference: Diebold, Rudebusch & Aruoba state-space term-structure work.

Target:

```text
Yield Curve
→ State-Space Estimation
→ Level/Slope/Curvature
→ Forecast
→ Duration/Curve Return
→ Portfolio Positioning
```

Separate current curve state from forecast curve state.

# 10. ML Macro Forecasting

References:
- Coulombe et al., machine learning for macroeconomic forecasting
- Medeiros et al., *Forecasting Inflation in a Data-Rich Environment: The Benefits of Machine Learning Methods*

Benchmark ladder:

```text
Naive
→ AR
→ VAR
→ DFM
→ Elastic Net
→ Random Forest / Gradient Boosting
→ DLinear or comparable simple modern baseline
→ TSFM
```

Metrics:

Point:
- RMSE
- MAE
- OOS R²
- directional accuracy

Density:
- log score
- CRPS
- coverage
- calibration

Portfolio:
- Sharpe
- Sortino
- CVaR/ES
- MDD
- turnover
- transaction cost
- regime-conditioned P&L

# 11. TSFM / Foundation Forecasting

Research references:
- TimesFM
- Chronos
- PatchTST
- DLinear / LTSF-Linear

These are frontier benchmarks, not assumed production winners.

A TSFM must beat a strong classical/regularized/nonlinear benchmark OOS before becoming a primary production input.

Audit:
- pretraining data provenance,
- domain shift,
- zero-shot assumptions,
- missing data,
- calibration,
- horizon,
- compute cost,
- reproducibility.

# 12. Neural SDE

Mathematical contract:

\[
dX_t = \mu_	heta(X_t,t)\,dt + \sigma_	heta(X_t,t)\,dW_t
\]

Audit:
- drift,
- diffusion,
- discretization,
- objective,
- identification,
- stability,
- uncertainty,
- calibration,
- economic value.

Do not add complexity before proving that the current SDE formulation is identifiable and useful.

# 13. CAUSAL / GRANGER

Core rule:

**Granger causality is predictive temporal causality, not automatically structural causality.**

Use terminology such as:

```text
X Granger-predicts Y
```

rather than "X causes Y" unless stronger identification is available.

Reference:
- Granger causality literature
- Spirtes, Glymour & Scheines, *Causation, Prediction, and Search*

Target hierarchy:

```text
Correlation
→ Lead/Lag
→ Granger Predictability
→ Conditional Relationship
→ Structural Causal Hypothesis
```

# 14. TAIL / EVT / POT

Primary:
- McNeil (1997), *Estimating the Tails of Loss Severity Distributions Using Extreme Value Theory*

Foundation:
- McNeil, Frey & Embrechts, *Quantitative Risk Management*

Target:

```text
Returns/Losses
→ Threshold
→ Exceedances
→ GPD
→ Shape ξ
→ VaR
→ ES
→ Parameter Uncertainty
→ Tail Validation
```

Diagnostics:
- threshold sensitivity,
- stability,
- confidence intervals,
- bootstrap uncertainty,
- tail-index stability,
- ES existence,
- VaR/ES backtesting.

If parameters imply divergent ES, report unavailability rather than fabricate a number.

# 15. Growth-at-Risk

Reference:
- Adrian, Boyarchenko & Giannone, Growth-at-Risk literature.

The goal is to estimate future growth distributions, not only conditional means.

Example:

```text
Expected = +2.0%
P10 = -1.3%
P25 = +0.4%
P50 = +2.0%
P75 = +3.2%
P90 = +4.1%
```

This creates a natural bridge from LATENT + REGIME + TAIL into portfolio risk.

# 16. VIEWS / Black-Litterman / Entropy Pooling

References:
- Black & Litterman (1992), *Global Portfolio Optimization*
- Meucci (2010), Black-Litterman extensions

Target:

```text
Market Prior
→ Macro State
→ Investor View
→ View Confidence
→ Posterior Distribution
→ Portfolio Optimization
```

LLM output may summarize/evidence/propose views. It must not directly determine portfolio weights.

# 17. ENSEMBLE / Model Risk

`ensemble.py` should evolve into a formal forecast-combination and model-risk layer.

Candidate methods:

```text
Equal Weight
Inverse Recent Error
Rolling OOS Performance
Bayesian Model Averaging
Regime-Conditional Weighting
Uncertainty / Precision Weighting
```

Ensemble weights must themselves be selected OOS.

Model disagreement must remain visible:

```text
Consensus
Dispersion
Confidence
Model Coverage
```

High disagreement may be used to reduce portfolio conviction, not to hide uncertainty.

# 18. Four-Level Model Evaluation

Every model is evaluated at:

### Level 1 — Statistical
RMSE, MAE, OOS R², log score, CRPS, calibration, coverage

### Level 2 — Economic
growth, inflation, recession, regime, yield-curve forecasts

### Level 3 — Portfolio
return, Sharpe, Sortino, CVaR/ES, MDD, turnover, transaction cost

### Level 4 — Decision Value
Did the model:
- improve allocation?
- reduce drawdown?
- reduce tail exposure?
- reduce false regime changes?
- improve rebalance decisions?

Level 4 is the ultimate criterion.

# 19. Pseudo-Real-Time / Walk-Forward

Use rolling or expanding windows.

No test-set tuning.

All model selection and hyperparameter selection must occur inside training/validation procedures.

A historical decision must only see information available at the decision date.

# 20. Macro → Asset Distribution

Long-term target:

\[
\mu_{asset,t+h}=f(MacroState_t)
\]

\[
\Sigma_{asset,t+h}=f(MacroState_t)
\]

\[
Tail_{asset,t+h}=f(MacroState_t)
\]

Pipeline:

```text
MacroState
→ Regime Distribution
→ Conditional Asset Return Distribution
→ Risk
→ Allocation
```

Keep the existing linear macro-allocation model as a baseline.

Do not delete it merely because newer models exist.

# 21. Regime-Conditional Asset Model

Long-term target:

\[
\mu_{i,r},\quad
\sigma_{i,r},\quad
ho_{ij,r}
\]

for asset `i,j` and regime `r`.

This allows different expected returns, volatility and correlation across economic states.

# 22. Macro State Expansion

Candidate dimensions:

```text
Growth
Inflation
Liquidity
Policy
Credit
Financial Conditions
USD
Real Rates
Volatility
Valuation
```

Do not add variables without evidence of economic/statistical/portfolio value.

# 23. Research / Model Provenance

Every model result should retain:

```text
as_of
information_cutoff
data_snapshot_id
model_version
training_window
parameters
feature_version
forecast_horizon
benchmark_model
validation_period
```

# 24. UI Contract

Model output should be presented as:

```text
CONCLUSION
↓
EVIDENCE
↓
UNCERTAINTY
↓
MODEL AGREEMENT
↓
PORTFOLIO IMPLICATION
```

Example:

```text
CURRENT STATE
Reflation 54%

WHY
Growth ↑
Inflation ↑
FCI neutral

CONFIDENCE
63%

RISK
Stagflation transition 15%

PORTFOLIO
Equity +3%
Duration -4%
Gold +2%
```

Do not present model output as certainty.

# 25. Performance

Classify models:

```text
Realtime / request-time
Short background
Long research job
Offline training
```

Heavy computation must not block the API process.

Cache expensive immutable outputs where safe.

Cache keys should include:

```text
data snapshot
model version
parameters
horizon
universe
as_of
```

# 26. Failure Handling

Every model must support:

```text
available = false
```

with explicit reason such as:

- insufficient observations
- missing series
- unstable estimation
- failed convergence
- invalid parameter regime
- missing dependency
- data quality failure

Never manufacture plausible-looking numbers.

# 27. Test Requirements

### Unit
- transformations
- parameter validation
- numerical edge cases
- missing data
- horizon

### Statistical
- synthetic recovery
- limiting cases
- known benchmark data

### Integration
- PIT data pipeline
- API contract
- serialization
- MacroState contract

### OOS regression
Use fixed historical windows and tolerance bands.

### Calibration
For probabilistic models:
- coverage,
- interval width,
- CRPS/log score.

# 28. Implementation Order

## Phase 0 — Audit
No production changes.

For each:
`base.py`, `tsfm_latent.py`, `neural_sde.py`, `pinn_tail.py`, `causal_deepm.py`, `ensemble.py`, `agentic_views.py`

produce:
- behavior,
- mathematical contract,
- dependencies,
- academic lineage,
- assumptions,
- test gaps,
- data requirements,
- portfolio outputs,
- limitations.

## Phase 1 — Contract stabilization
Refine:
- common context,
- result schema,
- metadata,
- failure reasons,
- provenance.

Do not change model math unless required for correctness.

## Phase 2 — Classical benchmarks
Establish:
- Naive,
- AR/VAR,
- DFM,
- Dynamic Nelson-Siegel,
- Granger,
- EVT/POT,
- Black-Litterman/Entropy Pooling.

## Phase 3 — OOS evaluation framework
Build shared rolling/expanding/pseudo-real-time and density-evaluation tooling.

## Phase 4 — Frontier models
Evaluate:
- TSFM,
- neural SDE,
- advanced causal,
- PINN/advanced tail models.

## Phase 5 — Ensemble / model risk
Add:
- combination,
- disagreement,
- calibration,
- confidence.

## Phase 6 — Portfolio integration
Standardize:
```text
MacroState
→ conditional μ
→ conditional Σ
→ tail
→ risk budget
→ allocation
```

# 29. Non-Goals

Do not:
- replace classical models with neural models because they are newer,
- call Granger output structural causality,
- tune on the final OOS set,
- use revised macro data in historical decisions,
- hide unavailable output,
- let an LLM directly determine portfolio weights,
- remove strong baseline models,
- optimize in-sample fit at the expense of OOS portfolio performance,
- add complex infrastructure before measuring the need.

# 30. Required First-Session Deliverables

Before production implementation, create:

```text
docs/specs/YYYY-MM-DD-macro-research-audit.md
docs/specs/YYYY-MM-DD-macro-model-reference-map.md
docs/specs/YYYY-MM-DD-macro-validation-framework.md
docs/plans/YYYY-MM-DD-macro-vnext-plan.md
```

The audit must contain:
1. current code map,
2. mathematical model map,
3. academic reference map,
4. PIT/data audit,
5. implementation-vs-paper gap analysis,
6. benchmark hierarchy,
7. OOS methodology,
8. portfolio-economic-value methodology,
9. model-risk framework,
10. priority order.

# 31. Claude Code First-Session Instruction

Read:

```text
CLAUDE.md
docs/Project_Alpha_CTO_QuantPM_Master_Prompt.md
docs/Project_Alpha_GSQuant_Architectural_Benchmark.md
docs/Project_Alpha_Macro_Research_Spec.md
```

Then:

```text
DO NOT modify production code.

Audit the full macro-model research architecture.

Scope:
- src/engine/macro_models/
- backend routes/services consuming these models
- Macro frontend
- Macro → Allocation handoff
- relevant data/PIT contracts
- model tests
- recent relevant commits

For every model:
1. identify its real mathematical method,
2. identify its actual implementation,
3. identify its academic lineage,
4. identify the strongest primary reference,
5. compare code to the mathematical reference,
6. identify data/PIT assumptions,
7. identify uncertainty/calibration gaps,
8. identify OOS validation gaps,
9. identify portfolio use,
10. identify computational cost,
11. recommend baseline / production / research-only / redesign.

Create a matrix:

Model
Current implementation
Academic reference
Mathematical correctness
PIT readiness
OOS readiness
Uncertainty quality
Portfolio relevance
Performance cost
Recommendation

Also design the benchmark hierarchy and portfolio-embedded economic-value methodology.

Create the four required audit/spec/plan documents.

Identify the smallest production-grade macro vertical slice.

Stop after the audit/design/plan and report findings.

Do not implement until explicitly approved.
```

# 32. Final North Star

```text
POINT-IN-TIME DATA
        ↓
INFORMATION SET
        ↓
LATENT / TERM / FCI STATE
        ↓
REGIME DISTRIBUTION
        ↓
DENSITY / TAIL FORECAST
        ↓
ASSET μ / Σ / TAIL
        ↓
RISK
        ↓
ALLOCATION
        ↓
REBALANCE
        ↓
REALIZED P&L
        ↓
ATTRIBUTION
        ↓
MODEL LEARNING
```

The goal is not:

> the most sophisticated macro model.

The goal is:

> **the most defensible macro-to-portfolio decision process Project Alpha can build from transparent, reproducible, point-in-time data.**
