# Plan — AAS Macro/Timing Research Studio

Spec: [aas-macro-timing-research-studio.md](../specs/aas-macro-timing-research-studio.md)
ADR: [adr-001-tailwind-shadcn-aas-migration.md](../decisions/adr-001-tailwind-shadcn-aas-migration.md)
Branch: `claude/backtest-modern-ui-refactor-akxvbc`

## Ground rules

1. **Phase 0 is documentation only.** No product code until the spec and ADR are approved.
2. One phase = one focused commit. **Never** combine refactoring, backend redesign, and UI
   restyling in a single commit.
3. TDD where practical — backend correctness properties (look-ahead, direction, missing-data) get
   a failing test before the implementation.
4. Verification gate runs **every** phase, not just at the end. Report exit codes, not grep hits.
5. Any Playwright selector change ships in the same commit as the component change.

### Baseline to preserve

| Gate | Baseline |
|---|---|
| Playwright | 33 passed |
| pytest | 1003 passed, 10 skipped |
| `tsc --noEmit` | 0 errors |
| `eslint src` | 0 errors (28 pre-existing warnings) |
| `next build` | exit 0 |
| Bundle | per-route table diffed; ≥4 kB unexplained growth reverted |

Backend tests run as `/usr/local/bin/python3 -m pytest tests/ -q`. Bare `pytest` resolves to a
uv-isolated tool without numpy → 71 spurious collection errors.

---

## Phases

> **Restructured after review (P1).** The original 0–9 breakdown was feature-horizontal: nothing
> was end-to-end usable until very late. Phases 1–4 below are now a **thin vertical slice** —
> `RegimeSnapshot → 2 PIT signals → TimingRuleSet → AAS integration → ResearchRun save/refresh` —
> that a user can actually exercise. Catalogue breadth, scenarios, and the shadcn migration come
> *after* that slice proves the architecture.
>
> Consequence: the shadcn/ADR work moved from Phase 1 to Phase 6. The vertical slice reuses the
> **existing** modal and strip components, unstyled-migration, so styling risk never blocks
> research correctness.

### Phase 0 — Documentation (this commit)
Spec, plan, ADR. No code. **Stop for approval.**

### Phase 0.5 — De-index the wizard *(prerequisite, no feature)*
Replace positional stage indexing with href-keyed lookup. Fixes three silent-break couplings
found in the audit: `stageComplete[9]` hardcoded at `WizardTracker.tsx:36`, the positional
10-entry subtitle array at `WizardTracker.tsx:28–37`, and `PHASES[].steps` index arrays at
`AllocationProvider.tsx:58–62`.
**Why first:** inserting any stage today breaks these **without a compile error**. After this,
adding a stage is a one-line `STAGES` edit.
**Gate:** 33/33 E2E unchanged; no route or class changes; pure refactor.

### Phase 1 — PIT foundation *(vertical slice, step 1)*
ALFRED-correct fetching in `macro_collector.py`: `realtime_start`/`realtime_end`, drop
`frequency` aggregation, persist the full `MacroObservation` identity (spec §3.1).
**TDD, test written first:** `GDPC1` at `as_of = T` reproduces the **originally published** value,
not today's revision, and no row with `release_timestamp > T` is reachable.
**Gate:** pytest. Also lands the `DataStatus` / `ResearchUsage` enums (§3.5) with the
`forward_only` rejection path on the historical-simulation endpoint.

### Phase 2 — `RegimeSnapshot` *(slice step 2)*
Model, `regime_snapshots` persistence (reuse the `research_runs` raw-SQL idiom),
`regime_snapshot_routes.py` in `ROUTER_MODULES`. Snapshots reference observations from Phase 1.

### Phase 3 — Two PIT signals + minimal `TimingRuleSetV2` *(slice step 3)*
Exactly **two** factors — one price-based (TSMOM, no revision problem) and one macro-based (curve
slope, exercises the vintage path). Three-state `SignalState`, `unavailable → risk_off`,
`k_of_n` combination, hysteresis, cooldown.
**Deliberately not** the full catalogue: the goal is to prove the contract end-to-end.

### Phase 4 — AAS integration + ResearchRun round-trip *(slice step 4 — first user-visible value)*
Adds `/allocation/macro`, "Open in Allocation Studio" from Macro with mapping preview, Research
Context content in `ContextStrip` (keeping `.as-ctx*`), and ResearchRun save → **refresh recovery**.
**Gate:** new E2E — create a snapshot in `/macro`, open it in AAS, save a run, reload the browser,
and reopen the identical run with the same snapshot ID and rule-set version.
**This is the milestone that proves the architecture.** Everything after it is breadth.

### Phase 5 — ADR acceptance + shadcn scaffold
Amend the `CLAUDE.md` frontend clause to state what is true (Tailwind already present, 46
components, AAS migrating, legacy plain-CSS untouched). Add `components.json` aliased to
`src/shared/ui/shadcn`, the token bridge appended at EOF of `globals.css`, and 2–3 primitives
rendered on `/dev/ui` beside existing ones.
**Gate:** four `:root` blocks byte-unchanged; rule-level emitted-CSS diff shows only additions;
33/33 E2E; no legacy visual diff.
**Rollback:** revert one commit; Tailwind is untouched.

### Phase 6 — Unified catalogue shell *(largest UI risk)*
One shadcn three-pane shell replaces `TimingFactorModal`, `StressScenarioModal`,
`AlphaFactorModal`, and Backtester `FactorPickerModal`.
**Gate:** `.tfm-*` / `.as-*` selector updates land **atomically** with the component change;
`stage-windows.spec.ts` and `timing-factors.spec.ts` updated in the same commit; keyboard/focus/
mobile tests added. Not combined with any backend phase.

### Phase 7 — Factor catalogue breadth
The remaining Phase-1 factors: relative momentum, breadth (incl. equal- vs cap-weight), realized
vol / vol regime / target-vol sizing, drawdown + speed + recovery, rolling correlation, Korea set.
(TSMOM and curve slope already shipped in Phase 3.) **TDD per factor.**

### Phase 7b — Data-source extension
Add FRED `NFCI` (weekly, **revised** — requires the Phase 1 vintage path) and `VXVCLS` to
`macro_collector.py`. Implement the VIX term-structure factor to the spec §6.2 definition:
**ratio** `VIXCLS/VXVCLS`, US-close→KR next-session alignment, no forward-fill of missing dates.
Surface `kis_flows` `forward_only` and ETF mock status as first-class UI labels.
**Gate:** pytest incl. cache, rate-limit, missing-API-key fallback, a **KR-holiday / US-holiday
alignment test**, and rejection of `forward_only` factors by the historical-simulation endpoint.

### Phase 8 — `ScenarioPackV2`
Extend the stress catalogue and `kr_scenario_pack.py`. Baseline vs timing-adjusted vs
macro-conditioned comparison in Stress. Historical/hypothetical labelling enforced in the type.

### Phase 9 — Stage wiring
Optimize (timing as explicit constraint/overlay, before/after + infeasibility reasons),
Attribution (allocation / timing / selection / factor / cost / residual; ex-ante vs ex-post),
Execution (paper-only preview, costs, liquidity, borrow, approval states — **no live orders**),
Journal (one ResearchRun holds snapshot + rule set + scenario pack + constraints + rationale).

### Deferred
`AllocationProvider` (522 lines, 40+ context fields) splits into slices — study context, timing,
scenarios, run history — as its **own** phase. Folding it into Phase 4 would entangle a state
refactor with a UI change.

---

## Per-phase report format

What changed · why it was necessary · files and routes affected · migration and rollback notes ·
test evidence (exit codes) · real-data limitations · remaining risks · next proposed phase.

## Risk register

| Risk | Phase | Mitigation |
|---|---|---|
| **Revision bias** — FRED returns today's vintage, so history is scored with revised data | 1 | ALFRED `realtime_*` fetching; `GDPC1` originally-published test written **before** the code |
| Silent stage-index break on insert | 0.5 | De-index to href-keyed lookup before any stage is added |
| `forward_only` data used in a backtest | 1, 7b | `ResearchUsage` derived, not hand-set; simulation endpoint **rejects** with a named reason |
| Look-ahead via US-close in a KR session | 7b | `market_cutoff`/`execution_timestamp`; KR+US holiday alignment test |
| Missing signal read as positive | 3 | Three-state `SignalState`; no boolean can default true |
| Selector break across 4 modal migrations | 6 | Atomic spec+component commits; POC gate first |
| **Radix portals** escaping container-scoped assertions | 5, 6 | Resolved in the POC; `dev-ui.spec.ts` is already container-scoped and would under-count |
| Cascade regression on unmigrated routes | 5, 6 | Screenshot diff of `/screener`, `/backtest`, `/macro` — the suite checks classes, not pixels |
| Mock result mistaken for validation | all | `mock_gate`; unavailable factors non-enableable |
| Bundle growth from Radix | 5, 6 | Per-route table each phase; ≥4 kB reverted, >15 kB aborts the migration |
| `kis_flows` shallow history misread as deep | 7b | `forward_only` label in UI **and** enforced server-side |
