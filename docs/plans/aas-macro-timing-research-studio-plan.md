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

### Phase 0 — Documentation (this commit)
Spec, plan, ADR. No code. **Stop for approval.**

### Phase 1 — ADR acceptance + shadcn scaffold
Amend the `CLAUDE.md` frontend clause to state what is true (Tailwind already present, 46
components, AAS migrating, legacy plain-CSS untouched). Add `components.json` aliased to
`src/shared/ui/shadcn`, the token bridge appended at EOF of `globals.css`, and 2–3 primitives
rendered on `/dev/ui` beside existing ones.
**Gate:** four `:root` blocks byte-unchanged; rule-level emitted-CSS diff shows only additions;
33/33 E2E; no legacy visual diff.
**Rollback:** revert one commit; Tailwind is untouched.

### Phase 2 — `RegimeSnapshot` backend
Pydantic model, `regime_snapshots` persistence (reuse the `research_runs` raw-SQL idiom),
`regime_snapshot_routes.py` registered in `ROUTER_MODULES`.
**TDD:** look-ahead test first — a snapshot with `as_of = T` must never include a series whose
`release_effective > T`, including revised values.
**Gate:** pytest; route parity check.

### Phase 3 — Macro → AAS bridge
"Open in Allocation Studio" action in Macro, mapping preview before apply, AAS references the
snapshot **by ID**. `loadedStrategy`'s ephemeral path is replaced, not duplicated.
**Gate:** new E2E — snapshot created in `/macro` reopens in AAS after a reload.

### Phase 4 — Research Context strip
Rewrite `ContextStrip` content; keep `.as-ctx*` classes and the layout slot. Surface the existing
`isResultStale` as the pending-changes indicator.
**Gate:** E2E asserts identity, as-of, data status, and reproducibility IDs are visible.

### Phase 5 — `TimingRuleSetV2` + evaluation engine
Extend the `TimingRule` dataclass; add combination methods, hysteresis, cooldown, conflict policy.
**TDD:** three-state `SignalState` with `unavailable → risk_off`; Defense First inversion;
frequency alignment; k-of-N and weighted composition.
**Gate:** pytest. Highest research risk in the plan — no UI work in this commit.

### Phase 6 — Unified catalogue shell *(largest UI risk)*
One shadcn three-pane shell replaces `TimingFactorModal`, `StressScenarioModal`,
`AlphaFactorModal`, and Backtester `FactorPickerModal`.
**Gate:** `.tfm-*` / `.as-*` selector updates land **atomically** with the component change;
`stage-windows.spec.ts` and `timing-factors.spec.ts` updated in the same commit; keyboard/focus/
mobile tests added. Not combined with any backend phase.

### Phase 7 — Phase-1 institutional factors
TSMOM, relative momentum, breadth (incl. equal- vs cap-weight), realized vol / vol regime /
target-vol sizing, drawdown + speed + recovery, rolling correlation, Korea set. All from data
already on hand. **TDD per factor.**

### Phase 7b — Data-source extension
Add FRED `NFCI` and `VXVCLS` to `macro_collector.py`; wire curve / real-yield / credit /
financial-conditions factors. Surface the `kis_flows` **~30 business day** limit and ETF mock
status in the UI as first-class labels.
**Gate:** pytest incl. cache, rate-limit, and missing-API-key fallback paths.

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
| Selector break across 4 modal migrations | 6 | Atomic spec+component commits; className-multiset comparison |
| Look-ahead slipping into historical replay | 2, 5, 7 | `release_effective <= as_of` filter enforced in the type, test-first |
| Missing signal read as positive | 5 | Three-state enum; no boolean can default true |
| Mock result mistaken for validation | all | `mock_gate`; unavailable factors non-enableable |
| shadcn variables colliding with `:root` | 1 | Additive EOF block; rule-level CSS diff |
| Bundle growth from Radix | 1, 6 | Per-route table each phase; ≥4 kB reverted |
| `kis_flows` shallow history misread as deep | 7b | 30-day limit shown in UI, not only in docs |
