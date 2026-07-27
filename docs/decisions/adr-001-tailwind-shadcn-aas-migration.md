# ADR 001 — Adopt Tailwind CSS + shadcn/ui, starting with Allocation Studio

Status: **Proposed** · Date: 2026-07-27 · Owner: platform
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
4. **Existing CSS custom properties remain the source of truth for design tokens.** The Tailwind
   theme and shadcn CSS variables are *mapped onto* them, never a parallel palette.
5. **Migrate by surface, not globally.** Order: AAS shared primitives → AAS factor/scenario
   windows → Macro and Backtester shared components where reuse is justified. Legacy routes are
   untouched until deliberately converted.
6. **Amend the `CLAUDE.md` frontend rule only after this ADR is accepted**, and amend it to state
   what is actually true, including which surfaces are migrated and which are not.

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
| Risk | Mitigation |
|---|---|
| shadcn variables collide with existing `:root` | Additive block at EOF; rule-level emitted-CSS diff each phase |
| Preflight changes legacy pages | Preflight **already applies today**; adopting shadcn adds no new global reset |
| Generated code drifts from our conventions | Vendored under `shared/ui/shadcn`, reviewed like hand-written code |
| FSD erosion | `components.json` aliases + the existing `import/no-restricted-paths` ESLint guardrail |

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

- [ ] ADR reviewed and moved to **Accepted**
- [ ] `CLAUDE.md` frontend clause amended to describe reality, in the same commit as the scaffold
- [ ] `components.json` aliases resolve into `src/shared/ui/shadcn`; no top-level `components/`
- [ ] Token bridge added at EOF of `globals.css`; the four `:root` blocks byte-unchanged
- [ ] `/dev/ui` renders the shadcn primitives beside the existing ones
- [ ] Baseline preserved: **33/33 Playwright · 1003 passed/10 skipped pytest · tsc 0 · eslint 0**
- [ ] Per-route bundle table diffed; every delta ≥4 kB explained or reverted
