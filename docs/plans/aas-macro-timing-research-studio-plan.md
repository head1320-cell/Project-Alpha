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
| Playwright | 42 passed (was 33 at Phase 0) |
| pytest | 1061 passed, 10 skipped (was 1003 at Phase 0) |
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
| 5 | ADR acceptance + shadcn scaffold | **UI** | ✅ (this commit) |
| 6 | Catalogue shell — 3 of 4 modals | **UI** | next |
| 7 | `TimingRuleSetV2` + 2 PIT signals | backend | |
| 6b | `TimingFactorModal` → shell (deferred 4th) | UI | |
| 7b | **Macro overlay semantics** (restored) | both | |
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
| ⑦ active rule set | timing **config summary** (frontend holds no saved `set_id`) | Phase 7 |
| ⑦ scenario pack | selected scenario **label** | Phase 9 |
| ⑨ rule version | omitted; snapshot/model/engine/code versions shown | Phase 7 |

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

### Phase 6 — Unified catalogue shell *(largest UI risk)*
One shadcn three-pane shell replaces the duplicate modals.

**Migrate three now, defer one.** `StressScenarioModal`, `AlphaFactorModal`, and Backtester
`FactorPickerModal` move to the shell in this phase. **`TimingFactorModal` does not** — Phase 7
reshapes the timing model underneath it, and migrating first would mean rebuilding the same window
twice. It follows immediately after Phase 7 as **6b**.
**Gate:** `.tfm-*` / `.as-*` selector updates land **atomically** with the component change;
`stage-windows.spec.ts` updated in the same commit; keyboard/focus/mobile tests added.
Not combined with any backend phase.

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

### Phase 6b — `TimingFactorModal` → catalogue shell
The deferred fourth modal, once its underlying model is stable.
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
- **Gate:** E2E asserting the three-way comparison is legible and that disabling the overlay
  visibly changes the composite state.

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
