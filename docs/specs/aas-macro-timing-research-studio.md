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

### 3.1 Point-in-time correctness — `MacroObservation`

> **Corrected after review (P0).** An earlier draft of this spec proposed filtering on
> `release_effective <= as_of`. That is **not sufficient and was not even implementable** with
> the current collector. Recorded here rather than quietly edited, because the failure is
> instructive.

Verified in `src/services/macro_collector.py` (`FredClient.fetch_series`, L277–300):

```python
params = {"series_id": …, "observation_start": start,
          "observation_end": end, "frequency": "m"}
…
for o in obs:
    timestamps.append(o["date"]); values.append(float(o["value"]))
```

Three defects for PIT purposes:

1. **No `realtime_start` / `realtime_end`.** The FRED `series/observations` endpoint defaults to
   *today's* real-time period, so it returns the **latest revised vintage**. Asking for
   observations dated 2020 returns 2020 periods **as revised today**, not as published in 2020.
   GDP, CPI, PAYEMS and INDPRO are all heavily revised — this leaks the future directly into
   historical values.
2. **`o["realtime_start"]` is discarded**, so there is no per-observation publication timestamp
   to filter on. The proposed `release_effective` field had no data source; populating it would
   have meant inventing it — the exact dishonesty this spec exists to prevent.
3. **`frequency: "m"`** aggregates server-side, destroying intra-month release timing.

**Correct design.** Every macro datum is a `MacroObservation` with six *independent* timestamps:

```
series_id
observation_period      # the period the number describes  (FRED "date")
release_timestamp       # when this value was first published (ALFRED realtime_start)
vintage_id              # which revision this is            (ALFRED realtime period)
retrieved_at            # when we fetched it
market_cutoff           # last market time usable for a decision at as_of
execution_timestamp     # when a decision on it could actually be acted on
value, data_status
```

Historical replay selects, for each `series_id`, the row maximising `release_timestamp` subject to
`release_timestamp <= as_of` — i.e. **the vintage as known then**, not the period filter alone.
Fetching uses ALFRED semantics (`realtime_start`/`realtime_end`, or `vintage_dates`) and drops
`frequency` aggregation.

**Mandatory validation test (written before the implementation):** for a heavily revised series
(`GDPC1`), assert that a snapshot at `as_of = T` reproduces the *originally published* value and
**not** the current revision, and that no row with `release_timestamp > T` is reachable. A test
that only checks `observation_period <= as_of` does not satisfy this and must not be written.

`RegimeSnapshot` then references observations rather than embedding bare numbers:

```
snapshot_id, created_at, as_of
growth_axis, inflation_axis, phase_probabilities{}, stress_score, confidence
observations[]: MacroObservation      # full identity per input series
data_status, model_version, engine_version, explanation
```

Immutable, versioned, referenced **by ID**. This is the object whose absence is the core gap.

#### ALFRED cost, stated honestly
Vintage-correct history costs more API calls and storage than the current single-vintage pull, and
ECOS has no comparable public vintage API — Korean series therefore get
`data_status = partial` with `vintage_id = null` and are **excluded from historical simulation**
under §3.5, rather than being silently treated as revision-free.

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

### 3.5 "Fetchable" ≠ "backtest-eligible"

> Added after review (P1). Being able to *retrieve* a series says nothing about whether it may be
> used in a **historical simulation**. Conflating the two is how revision bias and short-history
> bias enter a backtest.

Two orthogonal enums, both required on every factor and every observation:

```
DataStatus     = real | mock | delayed | stale | partial | unavailable
ResearchUsage  = backtest_eligible | forward_only | unavailable
```

`ResearchUsage` is **derived, never hand-set**, from three properties:

| Condition | Result |
|---|---|
| No vintage history (revisions cannot be reconstructed) | `forward_only` |
| History shorter than the requested simulation window | `forward_only` |
| Publication lag unknown or unmodelled | `forward_only` |
| Vintage-correct, lag modelled, sufficient depth | `backtest_eligible` |
| No source | `unavailable` |

**Enforcement is structural, not advisory.** The historical-simulation endpoint rejects any rule
set containing a `forward_only` factor with an explicit error naming the factor and the reason.
It does not warn and proceed.

Worked consequence — KIS investor flows: `src/data/kis_flows.py` documents that the KIS TR
(`FHKST01010900`) returns only **~30 business days**. That is `forward_only`. It may drive a live
signal or a forward paper study; it is **blocked from historical backtesting**, and the UI shows
`forward_only` on the factor card rather than hiding the limit in a tooltip. ECOS-sourced Korean
macro is `forward_only` for the same structural reason (no public vintage API, §3.1).

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

> **Implementation note (Phase 4, `ac04674`).** Three of these elements ship as honest proxies
> because their underlying models do not exist yet. The strip labels each as such rather than
> implying more than it knows:
>
> | Element | Shipped as | Full form owned by |
> |---|---|---|
> | market & **universe** | `market` + holdings count — AAS has no sleeve/universe entity; holdings are a flat list | a future sleeve model |
> | active **rule set** | timing **config summary** — the frontend holds no saved `set_id`, only unsaved `timingCfg`, and `timing_rule_sets` has no `version` column | Phase 7 (`TimingRuleSetV2`) |
> | **scenario pack** | selected scenario's **label** — no pack entity exists | Phase 9 (`ScenarioPackV2`) |
>
> Regime value precedence is centralised in `widgets/allocation/useResearchRegime.ts`:
> **an attached snapshot wins; live is the fallback and the strip says which is showing**
> (`PINNED` / `LIVE`). When a snapshot ID is attached but unreadable, it does **not** fall back to
> live — showing today's numbers while the user believes the regime is pinned would be the exact
> failure this spec exists to prevent.

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

Availability and *research usage* (§3.5) are separate columns, because they genuinely differ:

| Factor group | Fetchable | Usage | Source / note |
|---|---|---|---|
| Yield-curve level / slope / slope change | yes | `backtest_eligible`¹ | FRED, already collected |
| Real yields, inflation breakeven | yes | `backtest_eligible`¹ | `DFII10`, `T10YIE` |
| Credit spread | yes | `backtest_eligible`¹ | `BAMLH0A0HYM2` |
| VIX level | yes | `backtest_eligible`¹ | `VIXCLS` (not revised, but see §6.2 on timing) |
| USD/KRW, KR policy rate, KTB, CPI | yes | **`forward_only`** | ECOS — no public vintage API (§3.1) |
| Financial conditions (NFCI) | add series | `backtest_eligible`¹ | FRED `NFCI` — **weekly, revised**; vintage required |
| VIX term structure | add series | `backtest_eligible`¹ | See §6.2 — needs a real definition, not just a series |
| Foreign / institutional flows | partial | **`forward_only`** | `data/kis_flows.py` — KIS TR returns ~30 business days. Blocked from historical simulation |
| ETF premium/discount, liquidity, capacity | partial | **`forward_only`** | `data/etf_prices.py` DB→KIS→mock; US ETFs mock in sandbox |
| VIX skew, borrow / short interest, option-implied correlation, crowding, alt-data | no | `unavailable` | No source. Catalogue-visible, **non-enableable**, concrete reason shown |

¹ `backtest_eligible` **only after** the ALFRED vintage work in §3.1 lands. Until then every FRED
series is `forward_only`. Marking them eligible on the strength of the current single-vintage
collector would reintroduce exactly the revision bias §3.1 exists to remove.

### 6.2 VIX term structure — definition, not just a series

> Added after review (P2). "Add `VXVCLS`" is a data task, not a factor definition.

- **`VIXCLS`** = 30-day implied vol. **`VXVCLS`** = 3-month implied vol. Both are CBOE indices
  republished by FRED.
- **Form:** the factor is the **ratio** `VIXCLS / VXVCLS`, not the spread. The ratio is unit-free
  and comparable across volatility levels; a spread of 2 points means something different at
  VIX 12 than at VIX 45. Ratio `< 1` = contango (calm), `> 1` = backwardation (stress). The
  spread variant is offered as a separate, explicitly-labelled factor for users who want it.
- **Timezone alignment — a look-ahead vector.** Both are **US close** values. A Korean trading
  decision on date `D` must use the US close of `D-1`, because `D`'s US close occurs *after* the
  KRX session ends. Using same-calendar-date US close in a KR backtest is look-ahead. This is
  encoded in `market_cutoff` / `execution_timestamp` (§3.1), and asserted by a dedicated PIT test
  using a KR holiday and a US holiday to force the edge cases apart.
- **Missing dates:** US and KR holiday calendars differ. Missing values are **not**
  forward-filled into a signal; the factor returns `unavailable`, which composes to `risk_off`
  (§3.3). Forward-filling would manufacture a stale-but-confident signal.

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

New stage `/allocation/macro` (Macro Phase).

> **Corrected after review (P1).** An earlier draft claimed "stage numbering is unchanged" while
> also describing the new stage as "00.5" — i.e. inserted before `Construct`. Those cannot both be
> true. The audit below shows insertion is genuinely unsafe today, so the spec now requires a
> de-indexing step *before* the route is added.

**Measured index coupling** (`widgets/allocation/`):

| Coupling | Location | Breaks on insert? |
|---|---|---|
| `stageComplete[9]` hardcoded for Journal | `WizardTracker.tsx:36` | **Yes — silently.** No type error, the badge just reads the wrong stage |
| Positional 10-entry subtitle array | `WizardTracker.tsx:28–37` | **Yes — silently.** Every label shifts by one |
| `PHASES[].steps` = `[1]`, `[2,3,4,5]`, `[6,7,8]` | `AllocationProvider.tsx:58–62` | **Yes.** Phase membership becomes wrong |
| `stageComplete` positional array literal | `AllocationProvider.tsx:488` | Yes |
| `isKnownAllocationRoute` / `stageIndex` | `AllocationProvider.tsx:94–110` | No — derived from `STAGES` |
| Resume `lastPos` (sessionStorage) | `AllocationProvider.tsx:123` | No — stores **href**, not index |

So Resume and route-validation are safe, but three positional couplings would break **without a
compile error**. That is the real hazard, and it exists independently of this feature.

**Resolution — de-index first, then add the stage.** A preparatory phase (Plan 0.5) replaces
positional indexing with href-keyed lookup: `stageComplete` becomes
`Record<StageHref, boolean>`, `PHASES[].steps` holds hrefs, and the `WizardTracker` subtitle array
is keyed by href. After that, inserting a stage anywhere is a one-line `STAGES` edit and
*numbering genuinely stops mattering*. This is a small, independently testable refactor that
removes a whole class of silent bug.

The alternative the reviewer raised — embedding Macro Phase as a Sheet or sub-route under
Timing/Thesis — needs no `STAGES` change at all and is a legitimate cheaper option. It is not
chosen because the mission calls for Macro Phase Analysis as a first-class stage and the user
selected the dedicated route; the de-indexing work is justified on its own merits regardless.

Existing route paths remain stable throughout; only the internal indexing changes.

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

> **Ownership map (Phase 6, `features/catalogue-shell/CatalogueShell.tsx`).** The shell shipped with
> the two AAS modals; the rest is re-homed in writing so nothing is silently dropped:
>
> | Requirement | Owner | Note |
> |---|---|---|
> | three-pane layout · search · families · badges · config · lineage/limitations · keyboard · focus trap · Escape · ARIA · responsive · KO/EN search · validation | **Phase 6** | `.tfm-*` classes preserved, so both existing specs pass with **zero selector edits** |
> | historical preview (value / threshold / **signal state** / # state changes) | **Phase 6b** | needs `SignalState` from Phase 7; meaningless for scenario/alpha. Shell exposes `previewSlot`, left unfilled — placeholder states rejected on the honesty rule |
> | frequency-conflict warning | **Phase 6b** | needs `evaluation_frequency` + rebalance alignment (Phase 7). Shell exposes `frequencyWarningSlot` |
> | saved presets · draft-vs-active comparison | **Phase 6d** | net-new features, absent from all four modals — kept out so Phase 6's gate stayed "no capability lost" |
> | `FactorPickerModal` migration | **Phase 6c** | 477 lines, 76 inline styles, **zero E2E**, two consumers (Backtester + Screener). E2E coverage lands first |
>
> **Primitives:** only `ToggleGroup` was added. `Tooltip` was **deliberately not** adopted — both
> modals use `title=` zero times, putting unavailability reasons in the list row instead; that is an
> existing honesty design, and a tooltip would hide what is currently visible.
> `Select`/`Slider` stayed native (already accessible); `Command`/`Sheet`/`ScrollArea` are unused by
> these two and are built when a phase needs them.

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
