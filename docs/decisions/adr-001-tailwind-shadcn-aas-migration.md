# ADR 001 — Adopt Tailwind CSS + shadcn/ui, starting with Allocation Studio

Status: **Accepted** · Proposed 2026-07-27 · Accepted 2026-07-30 · Owner: platform
Supersedes: the frontend styling clause in `CLAUDE.md` §4 (절대 불변식)
Scope: `frontend/` — AAS first, other routes only by later deliberate decision

---

## 1. Context

The product brief asks for Tailwind CSS + shadcn/ui to raise the implementation quality of the
complex dialogs, tabs, sheets, command palettes, and forms the Allocation Studio needs, and states
that this requirement intentionally supersedes the current `CLAUDE.md` prohibition.

Before accepting that framing we measured the repository. **The premise of the prohibition is
already false.**

### 1.1 Tailwind is already installed and load-bearing

| Evidence | Measured |
|---|---|
| `frontend/package.json` | `tailwindcss@^3.4.1`, `postcss@^8`, `autoprefixer@^10` in devDependencies |
| `frontend/tailwind.config.js` | Exists. Custom `terminal.*` colour tokens, `fontFamily`, 3 keyframes |
| `frontend/postcss.config.js` | Exists. `{ tailwindcss: {}, autoprefixer: {} }` |
| `src/app/globals.css` L2–4 | `@tailwind base; @tailwind components; @tailwind utilities;` |
| `globals.css` `@apply` usage | `.card-sm` `.card-md` `.btn` `.input` are defined *with* `@apply` |
| Components using Tailwind utilities | **46 of 131 `.tsx` files (35%)** |
| Heaviest users | `MacroRadar` 125 utility occurrences · `ProductionMonitor` 106 · `RealismKPIs` 83 · `ScreenerPanel` 82 · `StockDetail` 78 |

Tailwind's `base` layer (preflight) has therefore been applying a global CSS reset to **every**
route in this application for as long as the file has existed.

`CLAUDE.md` currently states:

> **프론트엔드** — 순수 CSS 유지. **Tailwind·shadcn·CSS-in-JS 등 UI 프레임워크로 이전 금지.**

This is not a constraint being broken by this ADR. It is a **stale invariant that the codebase
already violates**, in the same category as the figures corrected in the Phase 1 documentation
work — where CLAUDE.md claimed "필터 13종 / FIELD_BY_ID 49개 / 라우트 223개" and the code said
11 / 157 / 268.

A supporting symptom of the config being unowned: `tailwind.config.js` still declares a
`pulse-dot` animation and `pulseDot` keyframes whose only consumer (`widgets/layout/TopNav.tsx`)
was deleted as unreachable code, and nothing failed.

### 1.2 What this changes about the decision

The real decision is **not** "should we adopt Tailwind" — that happened, undocumented, some time
ago. The decision is:

> Tailwind is present, ungoverned, and mixed with ~4,000 lines of hand-written CSS plus heavy
> inline `style={{}}` objects. Do we **formalise** it and add an accessible component layer, or
> do we remove it and return to the documented plain-CSS rule?

We choose to formalise. Removing Tailwind would mean rewriting 46 components with no product
benefit, and would still leave the accessibility gap that motivated the brief.

---

## 2. Decision

1. **Accept Tailwind CSS as an official, documented part of the frontend stack.** Keep the
   installed `3.4.x` line — it is compatible with Next 14.2.5 / React 18. Do **not** upgrade
   Next, React, TypeScript, or move to Tailwind v4 as part of this work.
2. **Adopt shadcn/ui**, generated through its CLI but **vendored into the FSD tree** at
   `frontend/src/shared/ui/shadcn/`. `components.json` aliases are configured so the CLI never
   creates a top-level `components/` island that bypasses FSD boundaries.
3. **Radix dependencies are added per component, on demand** — not as one bulk install.
   **Amended at acceptance (Phase 5):** the shadcn **CLI cannot run in this environment** — the
   agent proxy answers `403 CONNECT` for `ui.shadcn.com` (only package registries are allowlisted),
   so `shadcn add` cannot fetch component definitions. The primitives are therefore **hand-written
   against Radix following shadcn's published structure** (cva variants + `asChild`/Slot +
   `forwardRef` + `cn()`), and `components.json` is kept so a future `shadcn add` drops in cleanly
   if the host is ever reachable. The decision's intent — vendored location, per-component Radix,
   CLI never touching `globals.css`/`tailwind.config.js` — is unchanged; only the means differ.
4. **Existing CSS custom properties remain the source of truth for design tokens.** The Tailwind
   theme and shadcn CSS variables are *mapped onto* them, never a parallel palette.
5. **Migrate by surface, not globally.** Order: AAS shared primitives → AAS factor/scenario
   windows → Macro and Backtester shared components where reuse is justified. Legacy routes are
   untouched until deliberately converted.
6. **Amend the `CLAUDE.md` frontend rule only after this ADR is accepted**, and amend it to state
   what is actually true, including which surfaces are migrated and which are not.
7. **Styling work runs immediately after the vertical slice, ahead of all remaining backend.**
   The review's P1 correctly moved styling off the critical path of research correctness — the
   slice (`PIT → RegimeSnapshot → Macro bridge → Research Context`) reuses existing unstyled
   components and lands first. But the P1 revision then buried Tailwind/shadcn behind five
   phases, which understated how explicitly it was requested. Corrected sequencing:
   **scaffold at Plan Phase 5, catalogue shell at Phase 6**, both **before** the remaining
   backend work (7, 8, 8b, 9).
   The shell migrates **three** of the four duplicate modals. `TimingFactorModal` is deferred to
   **Phase 6b**, after Phase 7 reshapes `TimingRuleSetV2` underneath it — migrating first would
   mean building that window twice.

### 2.1 Token mapping

`globals.css` defines the design language across four `:root` blocks. shadcn expects HSL triplets
in variables such as `--background`, `--foreground`, `--border`, `--ring`, `--radius`.

The bridge is additive: a shadcn variable block is appended that **references existing tokens**
rather than redefining them.

| Existing token | shadcn variable | Note |
|---|---|---|
| `--t-bg` | `--background` | |
| `--t-ink` | `--foreground` | |
| `--t-surface` | `--muted`, `--card` | |
| `--t-border` | `--border`, `--input` | |
| `--t-accent` | `--primary`, `--ring` | institutional blue `#1200ff` |
| `--t-muted` | `--muted-foreground` | |
| `--danger` / `--color-bear` | `--destructive` | |

Hard constraint: **the four existing `:root` blocks are not edited or reordered.** The Step 1e
incident — where splitting `globals.css` shipped a broken build and the verification compared a
stale artifact — is the precedent. Additions go at the end of the file, and every change is
proved with a rule-level diff of the emitted stylesheet.

### 2.2 What "institutional, data-dense" means here

shadcn ships a generic SaaS look. We override defaults so migrated surfaces keep the current
research-terminal direction: compact spacing scale, existing mono/sans pairing, restrained colour
with status semantics carrying the signal, no decorative shadows or oversized card padding.
shadcn is adopted for **behaviour and accessibility** (focus traps, ARIA, keyboard navigation),
not for its default visual style.

---

## 3. Consequences

### Positive
- Dialog / Sheet / Command / Popover / Tooltip / Select get correct focus management and ARIA
  without hand-rolling them — the current modals do not have this.
- One catalogue-picker shell can replace four near-duplicate modals (`TimingFactorModal`,
  `StressScenarioModal`, `AlphaFactorModal`, Backtester `FactorPickerModal`).
- A documented owner for `tailwind.config.js`, which currently drifts unnoticed.
- Reduces the inline `style={{}}` load and slows `globals.css` growth.

### Negative / accepted costs
- ~12–18 `@radix-ui/*` packages plus `class-variance-authority` and `tailwind-merge`. Measured
  per phase against the per-route bundle table; ≥4 kB unexplained growth is reverted.
- A transitional period with two styling idioms. Bounded by rule 5 and by the requirement that no
  component keeps both a plain-CSS and a Tailwind implementation permanently.
- **CSS class names are live Playwright contracts** (`.as-*`, `.tfm-*`, `.brun-*`, `.tstate-*`;
  the suite uses no `data-testid`). Any selector change ships in the **same commit** as the
  component change, with the spec updated atomically.

### Risks and mitigations

> **Scoped after review (P2).** Tailwind's pre-existence removes exactly **one** risk — a new
> global reset — and no others. shadcn CSS variables, Radix portals, and the Playwright class
> contracts are independent risks that the pre-existing install says nothing about. The earlier
> "materially de-risks" framing was too broad; it is narrowed here.

| Risk | Reduced by Tailwind already existing? | Mitigation |
|---|---|---|
| New global reset on legacy pages | **Yes** — preflight already applies to every route today | None needed; verified by rule-level CSS diff |
| Build pipeline / PostCSS integration | **Yes** — already working | — |
| shadcn CSS variables colliding with the four `:root` blocks | **No** | Additive block at EOF; four `:root` blocks must stay byte-identical |
| **Radix portals** rendering outside the React tree | **No** | See below — affects live Playwright selectors |
| Playwright class contracts (`.as-*`, `.tfm-*`, no `data-testid`) | **No** | Selector updates ship atomically with component changes |
| Bundle growth from Radix | **No** | Per-route table each phase; ≥4 kB unexplained reverted |
| Generated code drifting from our conventions | **No** | Vendored under `shared/ui/shadcn`, reviewed like hand-written code |
| FSD erosion | **No** | `components.json` aliases + existing `import/no-restricted-paths` rule |

#### Radix portals — a concrete, already-observed hazard
Radix `Dialog`, `Popover`, `Tooltip`, and `Select` render their content into a portal attached to
`document.body`, **outside** the component's DOM subtree. Any Playwright assertion scoped to a
container will stop matching once a modal becomes a Radix `Dialog`.

This is not hypothetical for this repository: `e2e/dev-ui.spec.ts` was deliberately rewritten to
scope every count assertion to the `.devui` root. Those assertions would silently under-count
portalled content. The migration must therefore either keep portalled content assertions
page-rooted, or set an explicit portal container. Decided per component in the POC, not improvised.

### POC gate before any bulk migration

Migration does **not** begin with the four-modal merge. It begins with a single POC converting
**one** AAS component set — `Dialog` + `Sheet` + `Tabs` + `Command` inside the Timing factor
window — with these exit criteria, all of which must pass before further conversion:

1. `.tfm-*` and `.as-*` contracts either preserved or updated atomically with their specs.
2. Portal behaviour resolved and documented; the affected specs pass.
3. **Visual-regression check on non-migrated routes.** The suite asserts classes and geometry, not
   pixels, so it cannot catch a cascade change on its own. The POC captures Playwright screenshots
   of three representative unmigrated routes (`/screener`, `/backtest`, `/macro`) before and
   after, and diffs them. This is the only gate that can catch a global-cascade regression.
4. Emitted-CSS rule-level diff shows **additions only** — zero removals, zero modifications to
   existing rules.
5. Per-route bundle table: no unexplained growth ≥4 kB.
6. Baseline preserved: 33/33 Playwright · tsc 0 · eslint 0.

**Explicit rollback criteria.** Abandon the shadcn migration (keeping Tailwind) if any of:
a rule-level CSS diff shows unintended removals or modifications that cannot be contained;
the POC needs more than ~15 changed selectors to stay green; portal behaviour forces rewriting
unrelated specs; or bundle growth exceeds 15 kB on any AAS route without a clear cause.

### Amendment (Phase A) — the bundle threshold is measured on **first load**

Radix `Dialog` was excluded because converting a modal in place cost **+20 kB/route**, over the
15 kB rollback line. That measurement was re-run in Phase A and **reproduced exactly**:
`/backtest` 128 → 148 kB, `/macro` 243 → 263 kB. The figure was right.

What was missing is that the threshold was being applied to a cost that **does not have to land on
first load**. A modal is closed by default; `next/dynamic` moves its chunk out of the initial
payload entirely. After doing that, both routes came back **at or below** their pre-change
baseline — `/backtest` **126 kB** (−2 vs baseline), `/macro` **243 kB** (level).

So the rule is amended, not weakened:

> The ≥4 kB / 15 kB limits are measured on **First Load JS per route**. A dependency that only
> loads on user intent (a closed-by-default dialog, an editor opened from a button) is measured
> where it actually lands. Adopting Radix for such a surface is permitted **only with** the
> dynamic import in the same commit and the before/after route table in the commit message.

This does not reopen bulk Radix adoption. `Tooltip` stays rejected on design grounds (§8.1 puts
reasons in the visible row, not behind hover), and always-mounted surfaces are still bound by the
original limits.

**Second finding, recorded because it is a trap the next migration will hit.** With the dialog
behind `next/dynamic`, Radix's own close-autofocus restores to the wrong element — at click time
the dialog is not mounted, so the element it remembers is not the trigger. The fix is explicit:
`onCloseAutoFocus={(e) => e.preventDefault()}` plus a trigger ref refocused in
`requestAnimationFrame` (focusing in the same tick loses to Radix's focus guard). Covered by
`e2e/radix-dialogs.spec.ts`.

### Rollback
Each phase is one commit on a feature branch. Rolling back the ADR means reverting the shadcn
scaffold commit and the `CLAUDE.md` amendment; Tailwind itself is **not** rolled back, because it
predates this decision and 46 components depend on it.

---

## 4. Alternatives considered

- **Keep the plain-CSS rule and remove Tailwind.** Rejected: rewrites 46 working components for
  no product gain and leaves the accessibility gap unaddressed.
- **Tailwind only, no shadcn.** Rejected: the brief explicitly asks for accessible primitives, and
  hand-rolling focus traps and ARIA for Dialog/Command/Popover is exactly the work shadcn removes.
- **Radix directly, no shadcn CLI.** Viable and lower-dependency, but re-solves styling shadcn has
  already solved. Reconsider if generated-code drift becomes a real problem.
- **Tailwind v4.** Rejected for now: it changes the config format and PostCSS pipeline, and the
  brief forbids incidental upgrades.

---

## 5. Acceptance criteria

- [x] ADR reviewed and moved to **Accepted**
- [x] `CLAUDE.md` frontend clause amended to describe reality, in the same commit as the scaffold
- [x] `components.json` aliases resolve into `src/shared/ui/shadcn`; no top-level `components/`
- [x] Token bridge added at EOF of `globals.css`; the four `:root` blocks byte-unchanged
      (verified by SHA-256: `b63f4712473253dd · 1ea923a7464c4904 · df52007da8fac3fc · 9ae56319aa96c99c`
      identical before and after; a 5th block appended at EOF)
- [x] `/dev/ui` renders the shadcn primitives beside the existing ones
      (separate `.devui-shadcn` / `.devui-sitem` classes so the `.devui-item` count contract is untouched)
- [x] Baseline preserved: **42/42 Playwright · 1061 passed/10 skipped pytest · tsc 0 · eslint 0**
      (the original text said 33/1003 — true at Phase 0, never refreshed; corrected here)
- [x] Per-route bundle table diffed; every delta ≥4 kB explained or reverted
