# Project Alpha — CTO/Quant PM Master Prompt
## Dynamic Research-to-Portfolio Platform / 7-Tool Architecture / Backtester Reliability / Company Underwriting

You are working on the private repository:

- Repository: `head1320-cell/Project-Alpha`
- Target branch: `claude/backtest-modern-ui-refactor-akxvbc`
- Product: **Project Alpha**, a quantitative investment research and portfolio decision platform.

You are not being asked to blindly add features. You are being asked to act as a **senior systematic multi-asset portfolio manager + quantitative researcher + Python performance engineer + software architect** and evolve the platform toward a coherent professional-grade Research-to-Portfolio OS.

---

# 0. FIRST PRINCIPLE

The platform's identity is NOT:

> "a collection of finance tools."

It should become:

> **A reproducible, point-in-time, research-to-portfolio decision system that connects security selection, fundamental underwriting, macro state estimation, strategy validation, risk, asset allocation, and execution.**

The desired flow is:

```text
DATA INFRA
    ↓
SCREENER
    ↓
COMPANY / MACRO
    ↓
THESIS / SIGNAL
    ↓
BACKTEST
    ↓
RISK
    ↓
ALLOCATION
    ↓
EXECUTION
    ↓
JOURNAL / ATTRIBUTION
```

The seven current tools are:

1. Screener
2. Backtester
3. Macro
4. Company
5. Risk
6. Allocation Studio
7. Data Infra

Every proposed change must strengthen this system-level coherence.

Do not optimize individual tabs in isolation.

---

# 1. MANDATORY PROJECT CONTEXT

Read these before doing any implementation:

1. `CLAUDE.md`
2. `docs/HISTORY.md`
3. all relevant files under `docs/specs/`, `docs/plans/`, `docs/decisions/`
4. the relevant backend engine/router/data files
5. the relevant frontend route/entity/widget files
6. recent commits on the target branch

`CLAUDE.md` is binding project policy.

Important existing invariants from `CLAUDE.md` include:

- FastAPI 0.111.0 is fixed.
- `uvicorn --workers 1` is currently required because process-local state/caches exist.
- API traffic goes through the runtime same-origin proxy.
- mock mode is controlled only by `src/data/mock_gate.py::mock_allowed()`.
- real trading safety invariants must not be bypassed.
- code changes follow:
  `investigate → spec → plan → TDD implementation → verification`
- do not treat documentation counts as truth; read actual registries/code.

Do not weaken these constraints merely to make the new architecture easier.

---

# 2. CRITICAL WORKFLOW RULE

## Phase A — AUDIT FIRST

For the first stage of this task:

**DO NOT MODIFY PRODUCTION CODE.**

Instead:

1. inspect the architecture,
2. trace request/data/control flow,
3. measure or identify likely bottlenecks,
4. classify what already exists,
5. identify contradictions,
6. produce an evidence-backed gap analysis.

Do NOT immediately create a replacement engine.

Do NOT rewrite the backtester in C++ simply because it is Python.

Do NOT add Redis/Celery merely because "production systems use queues."

Do NOT replace working architecture without demonstrating why it is necessary.

The first goal is to discover the **minimum architectural change that creates the largest improvement in reliability, research quality, and maintainability**.

---

# 3. REQUIRED OUTPUT OF PHASE A

Create:

`docs/specs/YYYY-MM-DD-project-alpha-vnext-audit.md`

It must contain:

## A. Current architecture map

Trace:

```text
Frontend
 → API route
 → service/router
 → engine
 → data store
 → database/cache
 → response persistence
 → frontend polling/render
```

for all seven tools, with special depth for:

- Backtester
- Company
- Data Infra
- Macro
- Allocation

## B. Capability matrix

| Capability | Exists | Partial | Missing | Duplicate | Risk | Reuse candidate |
|---|---|---|---|---|---|---|

Do not invent missing components that already exist.

## C. Backtester execution map

Show exactly:

```text
POST /backtest/runs
→ backtest_run_routes.py
→ worker lifecycle
→ screening
→ data loading
→ simulation
→ metrics
→ result serialization
→ DB persistence
→ frontend status polling
→ result fetch
```

Identify:

- CPU-bound regions
- I/O-bound regions
- DB query multiplication
- pandas/DataFrame conversion
- Python-level loops
- thread/process behavior
- memory growth
- result serialization cost
- DB connection pool contention
- polling load
- cancellation behavior
- orphan behavior
- failure recovery

## D. Company execution map

Trace:

```text
Company page
→ company API
→ company_analytics
→ valuation engines
→ financial history/factor stores
→ DART/KIS/DB
→ frontend lazy tabs
```

Identify repeated calculations, duplicated data reads, missing caches, and opportunities for a canonical CompanySnapshot.

## E. Evidence-based performance diagnosis

Do not claim "server CPU" or "Python" without evidence.

Classify the bottleneck as one or more of:

- CPU saturation
- GIL / Python-level CPU loop
- process/thread contention
- memory pressure / OOM
- DB query latency
- DB pool starvation
- serialization cost
- frontend polling/network issue
- container/process lifecycle failure

Provide a confidence level for each conclusion.

---

# 4. BACKTESTER — CORE DIAGNOSIS

The current architecture includes:

- durable `backtest_runs`
- status polling
- cancellation
- retry
- progress reporting
- orphan cleanup
- a pure-Python backtest engine
- screen-to-backtest
- PIT-oriented workflow
- OOS / walk-forward infrastructure elsewhere in the platform.

The current design also uses `uvicorn --workers 1` and starts a daemon `threading.Thread` for each backtest run.

Treat this as a **critical architecture risk**.

The question is not:

> "Python or C++?"

The real question is:

> "What execution architecture is appropriate for CPU-heavy, reproducible, long-running quantitative simulations?"

---

# 5. BACKTESTER PERFORMANCE INVESTIGATION

Before changing the simulator, establish a benchmark.

Create a reproducible benchmark matrix such as:

### Small
- 5 assets
- 1 year
- simple strategy

### Medium
- 20 assets
- 5 years
- moderate strategy complexity

### Large
- 100 assets
- 10+ years
- multiple execution rules / portfolio logic

### Stress
- 200+ assets
- long history
- complex conditions
- multiple simultaneous jobs

Record:

- wall time
- CPU time
- CPU utilization
- RSS / peak memory
- DB query count
- DB query total time
- number of threads/processes
- serialization time
- result payload size
- status polling volume
- time spent per execution phase

Do not optimize blind.

---

# 6. BACKTESTER ARCHITECTURE DECISION

Evaluate at least these options:

### Option A — Bounded process worker pool in current stack
FastAPI/API process remains lightweight.
PostgreSQL stores job state.
A bounded number of separate worker processes execute simulations.

### Option B — PostgreSQL-backed job queue
Use `backtest_runs` as durable job storage and claim jobs using transactional row locking / `SKIP LOCKED` patterns.

### Option C — External queue system
Only recommend Redis/Celery/RQ/etc. if the benchmark and deployment requirements justify another infrastructure dependency.

### Option D — Dedicated simulation service
Separate simulation process/container from the API process.

Compare:

- complexity
- deployment burden
- reliability
- CPU utilization
- memory isolation
- cancellation
- retry
- checkpointing
- reproducibility
- local development
- GCP deployment
- future scaling

Do not default to the most complex architecture.

---

# 7. CPU / PYTHON / C++ DECISION RULE

Do not rewrite the whole engine in C++.

First:

1. profile the real workload,
2. identify hot functions,
3. remove unnecessary DB/I/O overhead,
4. bulk-load data,
5. reduce Python object churn,
6. use NumPy/array-based representations where appropriate,
7. use Numba for proven numeric hot loops where compatible,
8. benchmark again,
9. only then consider C++/Rust/Cython for a small stable kernel.

The default target architecture should be:

```text
Python orchestration
    +
data validation
    +
strategy definition / DSL
    +
portfolio logic
    +
metrics / analytics
    +
compiled numeric simulation kernel where justified
```

not:

```text
rewrite everything in C++
```

Do not introduce Numba everywhere. Use it only where profiling demonstrates a stable numerical hot path.

---

# 8. BACKTESTER DATA ARCHITECTURE

Investigate and, where justified, move toward:

```text
Universe
   ↓
Point-in-time Data Snapshot
   ↓
Bulk OHLCV / factor load
   ↓
Compact in-memory representation
   ↓
Simulation
```

Avoid one-query-per-ticker patterns inside hot loops where bulk loading is feasible.

Evaluate:

- PostgreSQL bulk queries
- columnar/array representations
- pandas only at boundaries, not necessarily inside the hottest loop
- Arrow/NumPy if useful
- caching by `(universe, start, end, data_version)`
- immutable data snapshots
- reuse of loaded datasets across strategies where safe

Never sacrifice point-in-time correctness for speed.

---

# 9. BACKTESTER JOB CONTROL

The production design must support:

- bounded concurrency
- queueing
- cancellation
- retry
- timeout
- progress
- heartbeat
- orphan detection
- restart recovery
- checkpointing where runs are long enough to justify it
- deterministic run IDs / engine version
- immutable input snapshot
- data snapshot ID
- result version
- correlation ID

A single runaway backtest must not starve:

- API requests
- Company analysis
- Macro analysis
- Screener
- Risk
- Allocation

from the same backend.

This is a hard requirement.

---

# 10. BACKTESTER PROGRESS / OBSERVABILITY

Progress must reflect actual work, not arbitrary percentages.

Instrument phase timing:

```text
validation
data preparation
data loading
strategy compilation
signal computation
simulation
metrics
attribution
serialization
persistence
```

Persist or log:

- phase start/end
- duration
- items processed
- rows processed
- estimated work
- actual work
- cache hit/miss
- query count
- error code
- worker PID / job worker identifier

The frontend should display:

- actual phase
- actual progress
- elapsed time
- last heartbeat
- queue position if available
- server execution state
- reconnection state
- cancellation state

Do not fabricate precision.

---

# 11. BACKTESTER RELIABILITY

Investigate these failure classes independently:

### A. UI polling failure
The simulation continues but status requests fail.

### B. DB contention
The simulation is healthy but progress/result persistence is blocked.

### C. Worker failure
The process/thread died.

### D. Container restart
The backend died and durable state survived.

### E. OOM
The kernel/container was killed.

### F. CPU starvation
The process remains alive but the system is saturated.

### G. Long-running request / proxy issue
The API path is not truly decoupled.

The user-visible state must clearly distinguish:

```text
RUNNING
RUNNING — STATUS CONNECTION DEGRADED
WORKER STALLED
FAILED
CANCELLED
SERVER RESTARTED — RECOVERY CHECK
```

Do not make the UI claim "the backtest stopped" if only polling failed.

---

# 12. BACKTESTER RESEARCH QUALITY

Do not optimize only for speed.

A professional backtester must preserve:

- point-in-time data
- publication/availability dates
- survivorship-safe universe membership
- adjusted price correctness
- corporate actions
- realistic fills
- transaction costs
- slippage
- liquidity constraints
- turnover
- portfolio drift
- short/long rules where supported
- cash
- benchmark
- rebalancing
- reproducible engine version
- immutable input snapshot

Backtest speed is secondary to correctness.

---

# 13. BACKTESTER FUTURE PRODUCT DIRECTION

Evolve toward:

> **Strategy Research OS**

with:

```text
Strategy Definition
    ↓
Validation / lint
    ↓
Compiled strategy representation
    ↓
Data snapshot
    ↓
Simulation
    ↓
OOS evaluation
    ↓
Robustness
    ↓
Attribution
    ↓
Research artifact
```

The user should be able to answer:

> What did I test?
> What data did I know at the time?
> What assumptions did I use?
> What were the costs?
> What happened OOS?
> Why did the result occur?
> Can I reproduce it?

---

# 14. COMPANY — PRODUCT DIRECTION

Current Company has:

- Overview
- Valuation
- Financials
- Factors
- Peers / Network
- Risk
- AI
- RIM / DCF / DDM
- sensitivity
- football field
- comps
- financial deep analysis
- risk deep analysis
- macro linkage.

Do not merely add more ratios.

Move Company from:

> **financial dashboard**

to:

> **security underwriting engine.**

---

# 15. COMPANY — CORE RESEARCH OBJECT

Introduce conceptually (and only implement after design approval):

```text
CompanySnapshot
```

containing:

- security identity
- point-in-time price
- market cap
- financial period
- publication dates
- financial statements
- factor values
- valuation assumptions
- valuation distributions
- peer set
- factor exposures
- macro sensitivities
- risk measures
- thesis
- catalysts
- kill conditions
- data provenance
- model version

This should become a stable internal contract for Company/Risk/Screener/Backtester.

---

# 16. COMPANY — VALUATION ADVANCEMENT

Current DCF/RIM/DDM and sensitivity analysis should evolve toward:

### A. Reverse DCF

Given current price:

infer market-implied:

- revenue growth
- operating margin
- FCF margin
- WACC
- terminal growth
- reinvestment

Show:

```text
CURRENT PRICE
↓
MARKET-IMPLIED ASSUMPTIONS
↓
THESIS: conservative / reasonable / aggressive
```

### B. Probabilistic valuation

Instead of one intrinsic value:

```text
P10
P25
P50
P75
P90
```

through uncertainty over:

- growth
- margin
- WACC
- terminal growth
- tax
- capex
- working capital
- reinvestment

### C. Valuation decomposition

Show which assumptions drive the value most.

---

# 17. COMPANY — EARNINGS QUALITY

Build toward underwriting-grade diagnostics:

- net income vs CFO
- accrual intensity
- cash conversion
- working-capital behavior
- one-off items
- margin durability
- revenue quality
- capex intensity
- stock compensation where available
- debt refinancing risk
- lease burden where available

Existing Altman/Beneish should become components, not the entire risk story.

---

# 18. COMPANY — CAPITAL ALLOCATION

Explicitly analyze:

```text
ROIC
vs
WACC
```

and capital deployment:

- reinvestment
- capex
- M&A
- dividends
- buybacks
- debt repayment
- cash accumulation

The question is:

> "Is management creating or destroying value with incremental capital?"

---

# 19. COMPANY — MACRO SENSITIVITY

Connect Company to Macro through exposures such as:

- growth
- inflation
- real yields
- nominal yields
- USD
- commodities
- credit
- liquidity

Desired output:

```text
+100bp 10Y → fair value -8.4%
GDP -2σ    → EPS -11.2%
USD +10%   → EPS +4.7%
Oil +30%   → EBIT +5.1%
```

These must be modeled/calculated, not narrated by AI.

---

# 20. COMPANY — THESIS ENGINE

Add a structured investment thesis model:

```text
WHY NOW?
WHY MISPRICED?
WHAT CHANGES?
CATALYSTS
KEY RISKS
KILL CONDITIONS
```

Example:

```text
Thesis:
Margin normalization

Catalyst:
Next 2 earnings cycles

Expected mechanism:
Operating margin 11% → 14%

Kill condition:
ROIC < WACC for 4 consecutive quarters
```

The thesis must be machine-readable enough to pass into Backtester / Risk / Allocation later.

---

# 21. COMPANY → BACKTESTER BRIDGE

The platform should ultimately support:

```text
Company thesis
    ↓
Formalized signal
    ↓
Backtest across historical universe
    ↓
OOS performance
    ↓
Risk / factor attribution
```

Example:

```text
"Margin recovery"
→ ΔOperatingMargin > threshold
→ rank within sector
→ long top decile
→ evaluate alpha / turnover / drawdown / regime behavior
```

This is much more valuable than adding another chart.

---

# 22. COMPANY → MACRO BRIDGE

Company should answer:

> "Does the current macro state strengthen or weaken my thesis?"

Potential output:

```text
Current Macro Regime:
Reflation

Impact:
Revenue             +0.4
Margin              +0.7
Valuation multiple  -0.2
Net Thesis Score    +0.5
```

Do not collapse all this into a black-box AI score.

---

# 23. 7-TOOL INTEGRATION TARGET

The future system should look like:

```text
                         DATA INFRA
                             │
                ┌────────────┴────────────┐
                ↓                         ↓
             SCREENER                  MACRO
                │                         │
                ↓                         ↓
             COMPANY                 MARKET STATE
                │                         │
                └────────────┬────────────┘
                             ↓
                          THESIS
                             ↓
                         BACKTEST
                             ↓
                           RISK
                             ↓
                        ALLOCATION
                             ↓
                         EXECUTION
                             ↓
                    ATTRIBUTION / JOURNAL
```

The same underlying entities should be reused instead of each tab inventing its own data model.

---

# 24. DATA INFRA — LONG-TERM REQUIREMENTS

Data Infra should become the platform's source of truth.

Conceptually:

```text
Raw Data
↓
Normalized Data
↓
Point-in-Time Store
↓
Universe Membership
↓
Factors
↓
Market Data
↓
Fundamentals
↓
Data Quality
↓
Provenance / Snapshot
```

Critical metadata:

- observation_date
- publication_date
- available_at
- effective_date
- source
- revision/version
- corporate-action state
- data quality status

This is especially important for Backtester and Company.

---

# 25. POINT-IN-TIME IS NON-NEGOTIABLE

A dataset labeled:

> "2025 Q2 financials"

does NOT mean it was knowable on 2025-06-30.

If published on 2025-08-15, it cannot be used in a 2025-07-01 simulation.

Build all future research features around the distinction:

```text
observation date
vs
publication / availability date
```

The same rule applies to:

- financial statements
- analyst data if introduced
- macro data
- factor snapshots
- universe membership
- delistings
- corporate actions

---

# 26. INVESTABLE UNIVERSE

Assume the platform is constrained to **listed, publicly tradable securities/products**.

Design an investable universe layer separating:

### Economic exposure
- equity
- rates
- credit
- inflation
- commodity
- FX
- real estate
- alternative beta

### Risk factor exposure
- growth
- inflation
- duration
- credit
- value
- momentum
- quality
- liquidity
- USD
- volatility

### Actual instrument
- listed stock
- ETF
- ETN
- REIT
- ETP
- listed bond, where supported.

This should eventually allow:

```text
Economic target
→ best listed implementation
```

rather than treating every ETF as its own unrelated asset.

---

# 27. ALLOCATION CONNECTION

Do not duplicate the existing Dynamic Portfolio Decision design.

The long-term target is:

```text
Macro State
→ Regime Distribution
→ Conditional μ / Σ / Tail
→ Investor Views
→ BL / Entropy Pooling / Robust Optimizer
→ Target Weight Range
→ Current Portfolio
→ Transaction Cost / Liquidity
→ Dynamic Rebalance Decision
```

Allocation already contains many of these components.

Prefer integration over duplication.

---

# 28. RISK CONNECTION

Move toward:

- factor risk
- regime-conditional covariance
- stress correlation
- tail dependence
- CVaR
- reverse stress
- liquidity risk
- turnover risk
- concentration risk

The real question is:

> "What can hurt this portfolio, under what macro state, and how much capital is at risk?"

---

# 29. ENGINEERING PRINCIPLES

Use these rules:

### Reuse before rewrite
Search existing code and tests before creating new modules.

### Measure before optimize
Performance work requires profiling or benchmark evidence.

### Separate orchestration from computation
API code should not own CPU-heavy simulation.

### Determinism
Same input snapshot + same engine version should produce the same result.

### Small cohesive modules
Do not make giant god classes.

### No fake values
Unavailable data should be represented honestly.

### Backward compatibility
Preserve existing API contracts unless a migration plan exists.

### Feature flags where appropriate
For risky infrastructure changes, permit controlled rollout.

### Test at boundaries
Include unit, integration, regression, concurrency, and performance tests.

---

# 30. OBSERVABILITY REQUIREMENTS

For Backtester at minimum collect:

- queue wait
- execution duration
- CPU time
- peak RSS
- worker identifier
- DB query count/time
- cache hit rate
- rows loaded
- simulation steps
- result size
- failure code
- cancellation reason

For Company:

- cold load latency
- warm load latency
- DART calls
- KIS calls
- DB reads
- valuation calculation time
- cache hit/miss
- payload size
- unavailable-data counts.

No optimization should be accepted without before/after measurements.

---

# 31. IMPLEMENTATION PRIORITY

Do not build everything.

Recommend a staged roadmap.

## P0 — Reliability first

Backtester:

- benchmark/profiling harness
- bounded worker architecture
- data bulk loading
- phase telemetry
- concurrency limits
- robust failure/recovery

Success criterion:

> A heavy backtest cannot starve unrelated API operations, and its state survives frontend disconnects/backend restart as far as the architecture allows.

## P1 — Backtest performance

- optimize actual hot path
- NumPy/Numba where justified
- reduce object churn
- cache/reuse datasets
- compact result representation

## P2 — Company underwriting

- CompanySnapshot
- Reverse DCF
- probabilistic valuation
- earnings quality
- capital allocation
- macro sensitivity
- thesis/kill conditions

## P3 — Research integration

- Company thesis → formal signal
- Backtest → risk attribution
- Macro → conditional forecasts
- Company factor exposure → portfolio factor risk

## P4 — Portfolio decision engine

- conditional μ/Σ
- robust optimization
- dynamic rebalance bands
- model disagreement
- transaction-cost-aware trade decisions

## P5 — advanced compute

Only if benchmark evidence supports it:
- compiled kernel
- dedicated simulation service
- Redis/Celery or equivalent
- horizontal worker scaling.

---

# 32. HARD NON-GOALS

Unless explicitly approved later:

- do NOT rewrite the whole project in C++
- do NOT add an external queue just because it is fashionable
- do NOT add AI-generated investment decisions as a substitute for quantitative engines
- do NOT replace existing engines without benchmark evidence
- do NOT add dozens of UI controls without improving decision quality
- do NOT destroy existing PIT/data honesty
- do NOT weaken trading safety
- do NOT increase Uvicorn worker count until process-local state is redesigned
- do NOT solve a performance issue by hiding it behind larger timeouts
- do NOT solve polling issues by merely increasing polling frequency
- do NOT fabricate progress percentages
- do NOT break E2E CSS contracts casually.

---

# 33. ACCEPTANCE CRITERIA FOR THE FIRST ARCHITECTURAL MILESTONE

Before production implementation, the design must answer:

### Performance
- What is slow?
- Why?
- What is CPU vs I/O vs DB?
- What is the measured bottleneck?

### Reliability
- Can multiple jobs run safely?
- What happens if one worker dies?
- What happens if the container restarts?
- Can the user cancel?
- Can the run resume or restart deterministically?

### Research correctness
- Is every input PIT-safe?
- Is the universe survivorship-safe?
- Are prices/corporate actions correct?
- Is the engine deterministic?

### Product coherence
- How does Company feed Backtester?
- How does Macro feed Risk/Allocation?
- How does Backtester feed Risk?
- How does Allocation feed Execution?

### Maintainability
- Are existing modules reused?
- Are new contracts clear?
- Are tests covering regression and performance?

---

# 34. REQUIRED DELIVERABLES FROM THE FIRST SESSION

Do not start implementation until the audit/design gate is complete.

Produce:

1. `docs/specs/YYYY-MM-DD-project-alpha-vnext-audit.md`
2. `docs/specs/YYYY-MM-DD-backtest-reliability-design.md`
3. `docs/specs/YYYY-MM-DD-company-underwriting-design.md`
4. `docs/plans/YYYY-MM-DD-project-alpha-vnext-plan.md`

The audit must include:

- architecture map
- capability matrix
- performance bottleneck hypothesis table
- measured benchmark plan/results if runnable
- 2–3 architecture options
- recommendation
- risk register
- migration strategy
- test strategy
- success metrics.

---

# 35. DECISION GATE

After producing the audit/spec/plan:

STOP.

Do not implement the next phase automatically.

Present:

1. what is already strong,
2. what is actually broken,
3. what is missing,
4. what should NOT be changed,
5. recommended architecture,
6. first implementation slice,
7. estimated risk/complexity,
8. verification plan.

Wait for explicit approval before production implementation.

---

# 36. IMPLEMENTATION RULE AFTER APPROVAL

Only after approval:

1. Use the project's brainstorming/design workflow.
2. Write/update the formal spec.
3. Write an implementation plan.
4. Use TDD.
5. Make small commits.
6. Run:
   - backend tests
   - performance benchmark
   - frontend typecheck/build
   - relevant Playwright tests
7. Compare performance before/after.
8. Perform a code review pass.
9. Verify the exact changed behavior before claiming completion.

---

# 37. FINAL ENGINEERING NORTH STAR

The final product should feel like:

> **A quant research lab that can turn an investment idea into a reproducible security thesis, validate it historically without look-ahead bias, understand its macro/factor/risk context, size it in a portfolio, and produce a disciplined rebalance/execution decision.**

The platform should not merely answer:

> "What is this stock worth?"
> "Did this strategy make money?"
> "What is the current macro regime?"
> "What portfolio weights should I use?"

It should ultimately answer:

> **"Given the information that was actually available at this point in time, what is the investment thesis, how reliable is it, how does it behave across regimes, what is the portfolio-level risk, and is the expected benefit of changing the portfolio large enough to justify the trading cost and uncertainty?"**

Build toward that system.
