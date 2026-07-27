# Spec — AAS Macro/Timing Research Studio

Status: draft · Owner: platform · Scope: `/allocation` (AAS), `/macro`, `src/api`, `src/engine`
Related: [ADR 001 — Tailwind + shadcn/ui](../decisions/adr-001-tailwind-shadcn-aas-migration.md)
· [Plan](../plans/aas-macro-timing-research-studio-plan.md)

> Terminology: the business request says "ASS tab". This repository calls it **Allocation Studio**
> / **AAS**. Same product. Routes, domain types, and UI terminology are **not** renamed.

---

## 1. Problem & goals

AAS today is a capable ten-stage allocation **wizard**. It is not yet a research **workspace**:

1. **Macro is not a durable input.** `AllocationProvider.loadedStrategy` is an ephemeral
   in-memory object copied out of the Macro tab. It has no ID, no version, no as-of timestamp.
   Nothing stops historical research from being scored with today's regime classification.
2. **There is no research identity.** A user cannot tell, at a glance, which study/run they are
   in, what universe it covers, how fresh the data is, or whether the displayed result is stale
   relative to current inputs.
3. **Timing is canary-centric.** `TimingConfig` encodes one shape — canary assets plus a breadth
   count plus an overlay. There is no composable rule set, no hysteresis or cooldown, no conflict
   policy, and no explanation of *why* a decision was risk-on or risk-off.
4. **Four near-duplicate modals.** `TimingFactorModal` (156 lines), `StressScenarioModal` (126),
   `AlphaFactorModal` (140), and Backtester's `FactorPickerModal` all solve "pick a thing from a
   catalogue and configure it", each differently and none with proper focus management.

**Goal:** a coherent research workspace along
`Macro Phase → Timing Research → Construction → Optimization → Scenario Validation →
Execution Readiness → Attribution → Journal`
that is approachable for beginners, powerful for experts, reproducible, and honest about data.

### Non-negotiables
- Point-in-time correctness. Historical decisions use only data available at that decision date.
- **A missing or unavailable signal never becomes a positive signal.** Conservative fallback.
- Real / mock / delayed / stale / unavailable / partial stay visibly distinct (`mock_gate` rules).
- No automated live execution. Work ends at paper/dry-run planning and approval.
- No claim of reproducing paid or non-public strategies.
- Existing routes stay stable; existing CSS class names are Playwright contracts.
- Never render a number without its unit, as-of date, and availability status.

---

## 2. Current-state audit (measured 2026-07-27)

| Area | Reality |
|---|---|
| AAS stages | 10 + gate; `STAGES[]` in `widgets/allocation/AllocationProvider.tsx` is the single source |
| AAS widgets | 25 files / 3,818 lines |
| `AllocationProvider` | 522 lines, **one context with 40+ fields** |
| `ContextStrip.tsx` | 78 lines — a macro **indicator ribbon** (regime + 4 canaries), not research identity |
| `allocation_routes.py` | **70 KB, 17 routes** |
| `engine/timing_factors.py` | 354 lines, **12 factors**, `stamp_pit()`, `TimingRule` dataclass |
| Persistence | `timing_rule_sets`, `research_runs` tables exist (defensive raw-SQL idiom) |
| Macro API | 26 endpoints incl. `/regime`, `/snapshot` — **no versioned persisted snapshot** |
| PIT | `engine/pit_store.py` exists, screener-scoped |
| E2E | 33 tests; AAS-specific: `aas`, `stage-windows`, `timing-factors`, `allocation-backtest` |

Existing assets are **extended, not duplicated**: `TimingRule`, `timing_factors.catalog()`,
`ContextStrip` (slot + `.as-ctx*` CSS kept, content model replaced), `research_runs`,
`kr_scenario_pack.py`, `pit_store.py`, `macro_collector.py`.

---

## 3. Data model

Pydantic contracts, backend-owned. No untyped dicts where a stable domain object belongs.

### 3.1 `RegimeSnapshot` — the missing durable bridge

Immutable, versioned, referenced **by ID**. This is the object whose absence is the core gap.

```
snapshot_id, created_at, as_of
growth_axis, inflation_axis, phase_probabilities{}, stress_score, confidence
source_timestamps{series_id: observed_at}      # per-series, not one global stamp
release_effective{series_id: released_at}      # publication time, for PIT replay
data_status: real|mock|delayed|stale|partial|unavailable
model_version, engine_version, explanation
```

`as_of` is the **decision date**. `release_effective` is when each input was actually published.
Historical replay filters on `release_effective <= as_of`, which is what makes look-ahead
structurally impossible rather than merely discouraged.

### 3.2 `TimingFactorDefinition`

Catalogue metadata. Every field the brief requires, plus:

```
provenance: systrader_public | generic_public_technical | institutional_public | user_defined
use_mode:   gate | ranking | sizing | tilt | risk_off_trigger | scenario_trigger
units, allowed_range, evaluation_frequency, release_lag, revision_policy
availability: available | partial | unavailable  (+ unavailable_reason)
expected_failure_mode                             # what happens when data is missing
```

`provenance` is a required enum precisely so the UI cannot render a factor without stating where
it came from. See §6 for the labelling rules.

### 3.3 `TimingRuleSetV2`

Extends the existing `TimingRule` dataclass — which already carries `universe`,
`observation_window`, `entry_condition`, `exit_condition`, `risk_off_asset`,
`rebalance_or_holding_period`, `position_sizing`, `leverage_cap`,
`transaction_cost_and_slippage`, and `point_in_time_data_timestamp`.

Added: `version`, `provenance`, `benchmark_series`, `normalization`, `hysteresis`, `cooldown`,
`conflict_policy`, `use_mode`, `data_status`.

Combination methods: `all` · `any` · `k_of_n` · `weighted` · `regime_conditioned` · `continuous`.

**Conservative fallback is part of the type, not the prose:** the evaluator returns a three-state
`SignalState = risk_on | risk_off | unavailable`, and `unavailable` resolves to `risk_off` in
composition. There is no boolean that a missing value can default to `true`.

### 3.4 Others
`TimingEvaluation` (per-factor state, composite state, transitions, exposure, **explanation
string**) · `ScenarioPackV2` (§5) · `DataLineage` · `ResearchContext` (§4) ·
`ResearchRun` extensions (snapshot ID, rule-set version, scenario pack, engine version).

---

## 4. Research Context

A **compact persistent strip**, not a dashboard. Replaces the content of `ContextStrip.tsx` while
keeping the `.as-ctx*` class contract and its slot in the AAS layout.

Shows: active ResearchRun / saved-study identity · portfolio or sleeve · market & universe ·
as-of timestamp · data status · Macro phase snapshot + confidence · active rule set & scenario
pack · **pending input changes vs last calculated result** · reproducibility IDs (data snapshot,
rule version, engine version).

`AllocationProvider.isResultStale` already computes the pending-changes signal; it is surfaced
rather than reinvented.

---

## 5. Scenario research

`ScenarioPackV2` extends the existing stress catalogue and `kr_scenario_pack.py`. Every pack
declares `model_type: historical_replay | hypothetical` and renders that label wherever results
appear — **a hypothetical shock is never presented as a historical fact.**

Required families: historical replays · growth/inflation regime shocks · correlation convergence
and stock-bond hedge failure · volatility shock and liquidity vacuum · credit/financial-conditions
tightening · KRW shock and foreign-flow reversal · Korea semiconductor value-chain selloff ·
value-up unwind · earnings-season dispersion · retail deleveraging / leveraged-ETF stress ·
short-selling and borrow-regime change (**only where data is reliable**) · user-authored.

Hedge suggestions are **research notes**, never trade instructions.

---

## 6. Factor catalogue & provenance labelling

Two clearly separated groups, because conflating them would be a false claim:

**Systrader-derived, publicly documented concepts** — average absolute momentum with continuous
sizing, dual momentum, accelerating dual momentum, MA trend filters, Defense First (an explicitly
*inverse* risk-on interpretation), dynamic multi-asset allocation, vol/correlation-aware
allocation. Labelled `systrader_public`.

**Generic public technical families** — disparity, channel breakout, volatility breakout,
overnight return/reversal, mean-reversion bands, drawdown/recovery filters. Labelled
`generic_public_technical`, all parameters user-configurable.

> The UI must not state or imply that generic disparity / breakout / overnight / reversal rules
> replicate Baekseokkkun's paid strategies. This is a correctness requirement, not a style note.

### 6.1 Institutional factors — measured availability

`src/services/macro_collector.py` already integrates **BOK ECOS + FRED** (SQLite cache, rate-limit
handling, mock fallback): 19 FRED series and 6 ECOS series, including `DGS3MO/2/10/30`, `T10Y2Y`,
`DFII10`, `T10YIE`, `BAMLH0A0HYM2`, `VIXCLS`, and ECOS `722Y001 · 817Y002/003 · 901Y009 · 731Y001`.

| Factor group | Status | Source |
|---|---|---|
| Yield-curve level / slope / slope change | **available** | FRED (already collected) |
| Real yields, inflation breakeven | **available** | FRED `DFII10`, `T10YIE` |
| Credit spread | **available** | FRED `BAMLH0A0HYM2` |
| VIX level | **available** | FRED `VIXCLS` |
| USD/KRW, KR policy rate, KTB, CPI | **available** | ECOS |
| Financial conditions (NFCI) | **add series** | FRED `NFCI` |
| VIX term structure | **add series** | FRED `VXVCLS` vs `VIXCLS` |
| Foreign / institutional flows | **partial** | `data/kis_flows.py` — KIS TR returns only ~30 business days; **no deep history**. Forward research only, and the UI must say so |
| ETF premium/discount, liquidity, capacity | **partial** | `data/etf_prices.py` DB→KIS→mock; US ETFs mock in sandbox |
| VIX skew, borrow / short interest, option-implied correlation, crowding, news/alt-data | **unavailable** | No source. Catalogue-visible, **non-enableable**, with a concrete reason |

Phase-1 factors (built first, all from data on hand): time-series momentum across asset classes ·
relative momentum · equity breadth incl. equal- vs cap-weight · realized vol, vol regime,
target-vol sizing · drawdown, drawdown speed, recovery state · rolling stock-bond and cross-asset
correlation · Korea set (KOSPI/KOSDAQ relative strength, sector dispersion, USD/KRW trend).

**Missing institutional data is never backfilled with fabricated values.**

---

## 7. API direction

New routers rather than growing the 70 KB `allocation_routes.py`; registered in
`app_factory.ROUTER_MODULES`:

- `src/api/regime_snapshot_routes.py` — create / get / list / compare snapshots
- `src/api/timing_routes.py` — catalogue, preview, evaluate, compare, historical simulation,
  rule-set CRUD

Extended in place: scenario pack save/run/compare (allocation), research-context attach/detach and
run reproducibility export (research). Contracts are defined from the research workflow — **not**
one endpoint per frontend component.

---

## 8. UI information architecture

New stage `/allocation/macro` (Macro Phase). **Existing route paths and stage numbering are
unchanged** — `STAGES` indices, `stageComplete[]`, and the Resume `lastPos` sessionStorage values
all stay valid. The mission's ordering is the documented narrative, not a physical reshuffle.

Per-stage requirements (Overview, Construct, Alpha Lab, Thesis, Timing, Optimize, Stress,
Attribution, Execution, Journal) follow the brief. Two that drive the most change:

- **Timing** becomes the central research desk: rule-set composition, per-factor state, composite
  state, historical transitions, exposure effect, and an explanation for every risk-on/risk-off
  decision. Supports baseline vs timing-only vs timing+macro comparison.
- **Optimize** takes timing output as explicit constraints/overlays/target-risk adjustments and
  **never silently overwrites strategic weights**; before/after weights, turnover, concentration,
  beta, factor exposures, and infeasibility reasons are all shown.

Macro Phase Analysis is an **optional overlay**, not an opaque override. Conflicts are stated in
plain language — e.g. "추세는 risk-on이지만 매크로 신뢰도가 낮고 금융환경이 긴축적입니다."

### 8.1 Catalogue-picker shell

One reusable Tailwind + shadcn three-pane shell replaces the four duplicate modals:
**left** filters (search, families, availability, source, market, tags) · **middle** searchable
catalogue with provenance and data badges · **right** configuration, formula explanation,
parameter inputs, historical preview (value / threshold / signal state / number of state changes),
lineage, limitations, impact preview.

Built on shadcn `Dialog`/`Sheet`, `Command`, `Tabs`, `ScrollArea`, `Tooltip`, `Badge`, `Select`,
`Slider`, form primitives. Requires keyboard navigation, focus trapping, Escape close, accessible
labels, responsive layout, KO/EN search, parameter validation, saved presets, draft-vs-active
comparison, and a warning when factor sampling frequency conflicts with rebalance frequency.

---

## 9. Acceptance criteria

**Backend** — no look-ahead per factor · macro publication lag and revision behaviour · correct
signal direction (especially Defense First's inversion) · frequency alignment and rebalance dates ·
missing-data conservative behaviour · rule combination, hysteresis, cooldown · scenario assumption
and historical/hypothetical labelling · ResearchRun reproducibility · infeasible optimisation and
long-only safety.

**Frontend** — a Macro snapshot can be selected in Macro and reopened in AAS · factor picker
supports search/filter/configure/preview/apply/save/reload · scenario picker matches that quality ·
baseline vs timing vs timing+macro is understandable · **zero API 404s and zero unhandled console
errors** from every actionable AAS control · unavailable data is visible and never shown as
neutral or positive · modal keyboard navigation and mobile layout work · Backtester/Macro/AAS/
execution behaviour intact · no styling regression on non-migrated routes.

**Command gate** — `make all` · `npx tsc --noEmit` · `npx next build` · `npx playwright test`.
Baseline to preserve: **33/33 Playwright · 1003 passed / 10 skipped pytest · tsc 0 · eslint 0**.
Backend tests must be run as `/usr/local/bin/python3 -m pytest`; bare `pytest` resolves to a
uv-isolated tool without numpy and produces 71 spurious collection errors.

---

## 10. References

Public design and research references. Cited as interaction / information-architecture and
methodology sources only — **no claim of replicating proprietary implementations.**

- AQR, *A Century of Evidence on Trend-Following Investing* —
  https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing
- Man Group, *Trend Following, Equity and Bond Crisis Alpha* —
  https://www.man.com/insights/trend-following-equity-and-bond-crisis-alpha
- BlackRock Systematic Investing — https://www.blackrock.com/us/individual/investment-ideas/systematic-investing
- BlackRock Factor Investing — https://www.blackrock.com/us/individual/investment-ideas/factor-investing
- MSCI Factor Indexes — https://www.msci.com/indexes/factor-indexes/msci-factor-indexes
- FRED NFCI (Chicago Fed National Financial Conditions Index) — https://fred.stlouisfed.org/series/nfci
- GenPort — https://genport.newsystock.com/Main.aspx
- Venn by Two Sigma — https://www.venn.twosigma.com/

ValueAI / Valley: referenced only via publicly observable UX patterns or user-supplied material.
No assumptions are made about their stack, strategy logic, or proprietary features.
