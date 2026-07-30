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
| Playwright | 50 passed (was 33 at Phase 0) |
| pytest | 1142 passed, 10 skipped (was 1003 at Phase 0; 1061 before Phase 7) |
| `tsc --noEmit` | 0 errors |
| `eslint src` | 0 errors (28 pre-existing warnings) |
| `next build` | exit 0 |
| Bundle | per-route table diffed; ≥4 kB unexplained growth reverted |

Backend tests run as `/usr/local/bin/python3 -m pytest tests/ -q`. Bare `pytest` resolves to a
uv-isolated tool without numpy → 71 spurious collection errors.

---

## Execution order

| # | Phase | Kind | Status |
|---|---|---|---|
| 0 | Documentation (spec · plan · ADR) | docs | ✅ `6dec39a` `e2e4a7d` |
| 0.5 | De-index the wizard | refactor | ✅ `279ef60` |
| 1 | PIT foundation (ALFRED vintages) | backend | ✅ `1dcfdbd` |
| 2 | `RegimeSnapshot` persistence + API | backend | ✅ `d331e96` |
| 3a | Macro→AAS bridge — builder + `from-current` | backend | ✅ `84d6180` |
| 3b | Macro→AAS bridge — client · action · preview | **frontend** | ✅ `813cec2` |
| 4 | Research Context + ResearchRun round-trip | frontend | ✅ `3afe2d8` `ac04674` +4c |
| 5 | ADR acceptance + shadcn scaffold | **UI** | ✅ `8df9c7b` |
| 6 | Catalogue shell — **2 AAS modals** | **UI** | ✅ `515cfb1` |
| 7 | `TimingRuleSetV2` + 2 PIT signals | backend | ✅ `ea59e8a` |
| 6b | `TimingFactorModal` → shell + §8.1 items 4·13 | UI | |
| 6c | `FactorPickerModal` → shell (**E2E first**) | UI | |
| 6d | Presets + draft-vs-active comparison (§8.1 11·12) | UI | |
| 7b | **Macro overlay semantics** (restored) + `regime_conditioned` | both | |
| 7c | Rule-version display in `ContextStrip` (§4 item ⑨) | **frontend** | |
| 8 | Factor catalogue breadth | backend | |
| 8b | Data-source extension (NFCI · VXVCLS) | backend | |
| 9 | `ScenarioPackV2` | both | |
| 10 | Stage wiring (Optimize · Attribution · Execution · Journal) | both | |

## Phases

> **Two revisions to the original ordering.**
>
> **(1) Vertical slice first (review P1).** The original 0–9 breakdown was feature-horizontal —
> nothing was end-to-end usable until very late. Phases 1–4 are a thin vertical slice a user can
> actually exercise.
>
> **(2) UI work pulled ahead of the remaining backend (user request).** Tailwind/shadcn was the
> most explicitly stated requirement in the mission brief, and the P1 revision had pushed it
> behind five phases. It now runs at 5–6, immediately after the slice completes and **ahead of**
> all remaining backend work (7, 8, 8b, 9). The one dependency this creates is handled by
> splitting the catalogue-shell migration: three modals at Phase 6, and `TimingFactorModal` at 6b
> after Phase 7 reshapes the model underneath it — otherwise that window would be built twice.

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

### Phase 3 — Macro → AAS bridge *(slice step 3)*

> **Numbering correction.** This slot originally read "Two PIT signals + minimal
> `TimingRuleSetV2`". What actually shipped in `84d6180` — and was labelled "Phase 3a" in its
> commit message — is the Macro→AAS bridge backend, i.e. the old Phase 4's territory. The timing
> signals were **not** built. Rather than leave the record wrong, the bridge keeps slot 3 and the
> timing work moves to Phase 7. Commits referencing "Phase 3a" mean the bridge backend.

- **3a — done (`84d6180`).** `src/engine/regime_snapshot_builder.py` +
  `POST /regime-snapshots/from-current`. Snapshots from the live engine are honestly
  `forward_only` + `partial` (the collector is not vintage-aware until Phase 8b).
  Also fixed: `LookAheadError` was reported as 500 instead of 422.
- **3b — next.** `entities/regime-snapshot` client; Macro action carrying `?snapshot=<id>` in the
  **URL** (not the `sessionStorage` handoff used for the Backtester — the spec forbids browser
  storage as the source of truth); mapping preview in AAS with Apply/Dismiss; `ContextStrip`
  shows the attached ID, `as_of`, and `research_usage` badge (`.as-ctx*` contract preserved);
  `/allocation/macro` stage added (safe now that Phase 0.5 de-indexed the wizard).
  **Gate:** E2E must prove **durability across a browser reload**, not just navigation — a test
  that only checks the button routes would pass against the old ephemeral behaviour.

### Phase 4 — Research Context + ResearchRun round-trip — **done**

- **4a `3afe2d8`** — `regime` / `recommended_mode` promoted to columns (they had lived only inside
  the `explanation` string); analyze accepts `regime_snapshot_id` and stamps it into the run's
  `snapshot` as well as `inputs`, because `list_runs` omits `inputs`.
- **4b `ac04674`** — `useResearchRegime()` puts one precedence rule in one place: **attached
  snapshot wins, live is the labelled fallback**. All three call sites consume it. Strip renders
  spec §4 items ①–⑨. Added `activeStudy` (item ① had no state at all).
- **4c** — `reopenRun` + reload round-trip E2E gate.

**Gate met, with one clause re-homed:** reopening restores the same run ID, snapshot ID, and
holdings across a browser reload. The "rule-set version" half moved to **Phase 7** (drift D2) —
no rule-set version exists yet and building one here would breach the scope wall.

**Spec §4 proxies shipped in Phase 4** (decided with the user, not silently):

| Spec item | Phase 4 shows | Full form owned by |
|---|---|---|
| ③ market & universe | `market` + holdings count | a future sleeve/universe model |
| ⑦ active rule set | timing **config summary** (frontend holds no saved `set_id`) | Phase 7 backend ✅ · display 7c |
| ⑦ scenario pack | selected scenario **label** | Phase 9 |
| ⑨ rule version | omitted; snapshot/model/engine/code versions shown | Phase **7c** (backend ✅ in 7) |

### Phase 5 — ADR acceptance + shadcn scaffold
Amend the `CLAUDE.md` frontend clause to state what is true (Tailwind already present, 46
components, AAS migrating, legacy plain-CSS untouched). Add `components.json` aliased to
`src/shared/ui/shadcn`, the token bridge appended at EOF of `globals.css`, and 2–3 primitives
rendered on `/dev/ui` beside existing ones.
**Gate:** four `:root` blocks byte-unchanged (SHA-verified); rule-level emitted-CSS diff shows only
additions; **42/42 E2E**; no legacy visual diff.
**Rollback:** revert one commit; Tailwind is untouched.
**Note (Phase 5 실측):** shadcn CLI 는 이 환경에서 쓸 수 없다 — 프록시가 `ui.shadcn.com` 을
`403 CONNECT` 로 거부한다(패키지 레지스트리만 허용). 프리미티브는 shadcn 공개 구조대로
손으로 작성했고 `components.json` 은 유지했다(ADR 001 결정 3 각주 참조).

### Phase 6 — Unified catalogue shell *(largest UI risk)* — **done**
`features/catalogue-shell/CatalogueShell.tsx` replaces the shared skeleton of the two AAS modals.

**Scope narrowed from three modals to two (drift D6-1).** `StressScenarioModal` (126→108) and
`AlphaFactorModal` (140→127) migrated. **`FactorPickerModal` moved to 6c** — measurement showed it
is the *riskiest*, not the safest: 477 lines, 76 inline styles, **zero E2E coverage**, and **two**
consumers (`FormulaBuilder` **and** Screener's `TerminalScreener`, 694 lines), with a two-step
wizard shape that the three-pane spec does not describe. `TimingFactorModal` stays deferred to 6b.

**`.tfm-*` classes were preserved rather than renamed.** So `stage-windows.spec.ts` and
`timing-factors.spec.ts` both pass **with zero selector edits** — that is the "no capability lost"
proof, stronger than updating assertions to match new markup.

**Primitives built: only `ToggleGroup`** (drift D6-3). Deliberately *not* added:
`Tooltip` (both modals use `title=` **zero** times — reasons go in the list row on purpose, an
existing honesty design), `Select`/`Slider` (native elements already accessible),
`Command`/`Sheet`/`ScrollArea` (not needed by these two).

**New capabilities:** Escape-to-close (previously backdrop-click only), arrow-key roving focus on
the family filter, `role=dialog`/`aria-modal`/`listbox`/`option`/`aria-selected`, mobile viewport
reachability. 5 new tests.

**Bundle note (honest):** `/allocation/alphalab` +17 kB, `/allocation/stress` +16 kB — **above the
ADR's 15 kB line, but with a clear and quantified cause**: these routes previously imported *zero*
Radix and now pull 16 packages (Dialog's 10 shared + ToggleGroup's 6 unique: toggle-group,
direction, roving-focus, collection, use-is-hydrated, toggle). Shared chunk unchanged at 87.3 kB.
If that cost is judged too high, the alternative is a hand-rolled roving tabindex (~20 lines, 0 kB)
— but that contradicts ADR §2.2's stated rationale for adopting shadcn ("behaviour and
accessibility … keyboard navigation").

### Phase 6c — `FactorPickerModal` → catalogue shell *(re-homed from Phase 6, drift D6-1)*
**E2E coverage first**, then migrate. It has none today, and it is consumed by both Backtester
(`FormulaBuilder.tsx:152`) and Screener (`TerminalScreener.tsx:691`) — a silent regression in
nested functions or two-factor operands (`TWO_FACTOR_IDS = cmp/gt/lt/pctf`) is otherwise
undetectable. Its two-step-wizard shape may warrant a shell variant rather than the three-pane form.

### Phase 6d — catalogue shell: presets + draft-vs-active comparison *(re-homed, drift D6-4)*
Spec §8.1 requirements **11** (saved presets) and **12** (draft-vs-active comparison) exist in **none**
of the four modals — they are net-new features, not migrations. Kept out of Phase 6 so its gate
could stay "no capability lost". This phase owns them.

### Phase 7 — `TimingRuleSetV2` + two PIT signals *(the deferred slice step)*
Exactly **two** factors — one price-based (TSMOM, no revision problem) and one macro-based (curve
slope, exercises the vintage path). Three-state `SignalState`, `unavailable → risk_off`,
`k_of_n` combination, hysteresis, cooldown, conflict policy.
**Deliberately not** the full catalogue: the goal is to prove the contract end-to-end.
**TDD:** direction (esp. Defense First inversion), frequency alignment, missing-data behaviour.
**Gate (re-homed from Phase 4, drift D2):** `timing_rule_sets` has no `version` column today
(`set_id · created_at · updated_at · name · market · rules · gate · notes`). Versioning belongs to
`TimingRuleSetV2`, so **this phase owns** the reproducibility clause the Phase 4 gate could not
satisfy: reopening a run must restore the same **rule-set version**, and spec §4 item 9's
"rule version" becomes displayable here. Phase 4 shipped the timing *config summary* instead and
said so on screen.

**Shipped.** `src/engine/timing_rules_v2.py` (three-state `SignalState`, five combination methods,
hysteresis, cooldown, frequency conflicts, `TimingRuleV2`/`TimingRuleSetV2`), `curve_slope` in the
`timing_factors` catalogue, `timing_rule_sets.version` + `timing_rule_set_versions`, rule-set version
stamped into `ResearchRun`. **81 new tests**, 1142 pytest total. Four mutation probes, each caught.

**This phase wires the first production callers of Phase 1's PIT foundation.** Until now
`fetch_observations` and `assert_backtest_eligible` had **zero** callers outside tests — Phase 1's
commit said so honestly. `read_curve_slope` consumes the former; `evaluate_rule_set(..., mode=
"backtest")` calls the latter before any value is scored.

**Re-homed out of this phase (decided drifts D7-2 / D7-4):**
- `regime_conditioned` → **7b**. It means "weight rules by macro regime", which *is* the overlay
  semantics 7b owns. `combine()` keeps the enum member and raises with "Phase 7b" in the message —
  it never silently substitutes another method, because a user must not get a composite decision
  from a combination they did not request.
- Rule-version **display** in the Research Context strip → **7c**. Phase 7 is backend-only; the
  backend half (version column, stamped into runs, restorable on reopen) ships here.

**Two further drifts found during implementation and decided in-phase:**
- **D7-5 — a version *counter* cannot satisfy "restore on reopen".** Spec §4 lists rule version among
  **reproducibility IDs**. Bumping a number while overwriting content in place means a run recording
  "v2" points at content that no longer exists, so reopening would restore the *current* rules under
  an old version label — worse than showing nothing, because it looks correct. Shipped the
  reproducible reading: `timing_rule_set_versions` holds each version's content immutably, and
  `get_rule_set_version` returns `None` for an unknown version rather than falling back to the latest.
- **D7-6 — cooldown direction was underspecified.** The spec names cooldown without defining whether
  it is symmetric. Shipped: symmetric across signal flips (blocking only re-entry still burns the
  exit leg of every whipsaw), but **never** applied to a transition into `unavailable` — losing data
  is not a signal flip, and holding `risk_on` through it leaves the book exposed on a value we no
  longer have.

**Honest limitation:** without a `FRED_API_KEY` the curve-slope factor resolves to `unavailable` →
`risk_off`. That is the designed conservative behaviour, not a failure; tests cover the vintage path
and the unavailable path via a stubbed `_http_get`. Live values need a key.

### Phase 6b — `TimingFactorModal` → catalogue shell
The deferred fourth modal, once its underlying model is stable.
**Also owns spec §8.1 requirements 4 and 13** *(re-homed from Phase 6, drift D6-2)*: the right-pane
historical preview (value / threshold / **signal state** / # state changes) and the **factor-sampling
vs rebalance frequency conflict warning**. Both need `SignalState` and `evaluation_frequency` from
Phase 7's `TimingRuleSetV2`, and "signal state" is meaningless for a scenario or alpha catalogue.
`CatalogueShell` already exposes them as **optional slots** (`previewSlot`, `frequencyWarningSlot`)
that Phase 6 leaves unfilled — filling them with placeholder states was rejected on the honesty rule.
**Gate:** `timing-factors.spec.ts` updated atomically.

### Phase 7b — Macro overlay semantics *(restored — was missing from this plan)*

> This was in the spec (§8, lines 365–372) but had **no phase**. It is the semantic half of
> "Macro Phase Analysis Integration" and three of the mission's nine requirements for it:
> optional overlay, three-way comparison, conflict explanation. Phase 7 is the first point where
> it is buildable, because all three need a rule set to compare against.

- **Optional overlay, not an opaque override.** Macro adjusts a rule set; it never silently
  replaces it. The user can see and disable the overlay independently of the rules.
- **Three-way comparison in the Timing desk** — baseline vs timing-only vs timing+macro.
  The mission asks for this in **two** places; the Timing desk is the primary one, and Phase 9's
  Stress comparison reuses this machinery rather than reinventing it.
- **Conflict explanation in plain language** — e.g. "추세는 risk-on이지만 매크로 신뢰도가 낮고
  금융환경이 긴축적입니다." Every risk-on/risk-off decision carries its reason.
- **Also owns `regime_conditioned`** *(re-homed from Phase 7, drift D7-2)*: the sixth combination
  method in spec §3.3. `timing_rules_v2.combine()` ships the other five and raises
  `NotYetImplementedError` naming this phase; implementing it here means removing that guard and the
  test that asserts it fires, in the same commit.
- **Gate:** E2E asserting the three-way comparison is legible and that disabling the overlay
  visibly changes the composite state.

### Phase 7c — rule-version display in the Research Context strip
*(re-homed from Phase 7, drift D7-4 — Phase 7 was scoped backend-only.)*
Spec §4 item ⑨ wants the **rule version** shown beside the snapshot/model/engine/code versions the
strip already carries. The backend half is done: `timing_rule_sets.version`,
`timing_rule_set_versions` for content, and `timing_rule_set_id`/`timing_rule_set_version` on
`AnalyzeRequest`, stamped into the run's `snapshot` (not only `inputs`, since `list_runs` omits
`inputs`). Remaining work is `ContextStrip` + the `.as-ctx*` E2E assertions.
**Honesty requirement:** when the stored version no longer resolves, the strip must say so rather
than showing the current version under the old label — `get_rule_set_version` already returns `None`
instead of falling back.

### Phase 8 — Factor catalogue breadth
The remaining Phase-1 factors: relative momentum, breadth (incl. equal- vs cap-weight), realized
vol / vol regime / target-vol sizing, drawdown + speed + recovery, rolling correlation, Korea set.
(TSMOM and curve slope ship in Phase 7.) **TDD per factor.**

### Phase 8b — Data-source extension
Add FRED `NFCI` (weekly, **revised** — requires the Phase 1 vintage path) and `VXVCLS` to
`macro_collector.py`. Implement the VIX term-structure factor to the spec §6.2 definition:
**ratio** `VIXCLS/VXVCLS`, US-close→KR next-session alignment, no forward-fill of missing dates.
Surface `kis_flows` `forward_only` and ETF mock status as first-class UI labels.
**Gate:** pytest incl. cache, rate-limit, missing-API-key fallback, a **KR-holiday / US-holiday
alignment test**, and rejection of `forward_only` factors by the historical-simulation endpoint.

### Phase 9 — `ScenarioPackV2`
Extend the stress catalogue and `kr_scenario_pack.py`. Baseline vs timing-adjusted vs
macro-conditioned comparison in Stress — **reusing the Phase 7b comparison machinery**, not a
second implementation. Historical/hypothetical labelling enforced in the type.
**Re-homed from Phase 4 (drift D3):** scenario **pack identity** for spec §4 item 7. Phase 4 shows
the selected scenario's *label* only, because no pack entity exists yet; this phase gives packs an
identity the Research Context strip can display.

### Phase 10 — Stage wiring
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
| `forward_only` data used in a backtest | 1, 8b | `ResearchUsage` derived, not hand-set; simulation endpoint **rejects** with a named reason |
| Look-ahead via US-close in a KR session | 8b | `market_cutoff`/`execution_timestamp`; KR+US holiday alignment test |
| Missing signal read as positive | 7 | Three-state `SignalState`; no boolean can default true |
| Selector break across modal migrations | 6, 6b | Atomic spec+component commits; POC gate first |
| **Radix portals** escaping container-scoped assertions | 5, 6, 6b | Resolved in the POC; `dev-ui.spec.ts` is already container-scoped and would under-count |
| Cascade regression on unmigrated routes | 5, 6, 6b | Screenshot diff of `/screener`, `/backtest`, `/macro` — the suite checks classes, not pixels |
| Mock result mistaken for validation | all | `mock_gate`; unavailable factors non-enableable |
| Bundle growth from Radix | 5, 6, 6b | Per-route table each phase; ≥4 kB reverted, >15 kB aborts the migration |
| `kis_flows` shallow history misread as deep | 8b | `forward_only` label in UI **and** enforced server-side |
| **Timing window built twice** — shell migrated before its model changes | 6, 6b | `TimingFactorModal` deliberately deferred to 6b, after Phase 7 |
| **Macro overlay silently overriding rules** — the requirement this plan had lost | 7b | Overlay is separately disableable; three-way comparison makes its effect visible |
