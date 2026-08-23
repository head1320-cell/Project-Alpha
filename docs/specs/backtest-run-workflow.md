# Spec — Persistent Backtest Run Workflow (+ AAS reliability, Macro recovery)

Status: draft · Owner: platform · Scope: `/backtest`, `/allocation` (AAS), `/macro`

## 1. Problem & goals

Today the Backtest tab runs synchronously and renders results **in-page under the config
form** (`TerminalBacktester.run()` → `screen-to-backtest-stream` SSE → local React state).
There is no durable run identity, no shareable/refreshable results URL, and no dedicated
loading experience. A browser refresh loses everything.

**Goal:** change the flow from
`configure → click Backtest → loading + results below the form`
to
`configure → create BacktestRun → dedicated loading page → dedicated results page`,
where the results live at a **stable URL** that can be refreshed, bookmarked, shared
internally, and reopened later.

Two production incidents ride along: intermittent AAS button **HTTP 404s**, and a **Macro
Analysis** tab error.

### Non-negotiables (from the brief)
- Preserve the existing **plain-CSS** architecture. No Tailwind/shadcn/CSS-in-JS/new UI fw.
- Do **not** fix failures by hiding buttons, adding a blanket ErrorBoundary, swallowing
  exceptions, or replacing real data with mock.
- Never render final results underneath the configuration form.
- Never navigate before a valid `run_id`; never invent progress or completion %.
- Distinguish on screen: **real / mock / delayed / unavailable** data.
- No feature wording implies investment advice or guaranteed returns.

## 2. Phase-0 reproduction findings (evidence)

Ran the real backend (`main_api`, 267 routes, `KIS_USE_MOCK=1`) + `next start` with the
same-origin proxy; drove both tabs in a real browser.

- **Macro:** all 21 macro endpoints return HTTP 200 with valid payloads; all 8 sub-tabs
  (Overview…Timing) + US toggle render with **0 page/console errors** (only an unrelated
  external Google-Fonts connection-reset from the sandbox). Not reproducible on HEAD.
- **AAS:** every client endpoint maps to a registered route; the runtime proxy
  (`app/api/backend/[...path]/route.ts`) exports all HTTP methods; walking every wizard
  stage + firing each primary action produced **0 API 404s / 0 console errors**. Not
  reproducible on HEAD.
- **Conclusion:** on the current branch neither incident is present. This points to a **GCP
  deployment mismatch** (a frontend carrying P4–P6 buttons against a backend image
  predating those routes would 404 exactly those newer buttons — "some buttons work
  sometimes"). Remedy #1 is a clean same-commit redeploy. The two bug phases therefore
  become **defensive hardening + regression lock-in** (below), which is what the brief
  asks for ("regression coverage so these failures cannot silently return"). We do not
  fabricate a fix for a non-reproducing crash.

## 3. BacktestRun domain

Durable object persisted server-side (raw-SQL, DB-optional idiom shared with
`research_runs`/`execution_store`). A refresh, direct URL visit, or transient network drop
must recover state from the backend, not in-memory React state.

Fields: `run_id`, `strategy_name`, `status`, `progress_percent`, `current_stage`,
`status_message`, `created_at/started_at/completed_at`, `requested_by`, `input_snapshot`,
`parameter_snapshot`, `data_snapshot_id`, `engine_version`, `result_version`, `error_code`,
`error_message`, `correlation_id`, `is_mock_data`, `is_pit_verified`, `result` (JSON).

### Status model
`draft → queued → validating → loading_data → simulating → calculating_metrics →
persisting_results → completed`
Terminal: `failed`, `cancelled`, `expired`.
Illegal transitions are rejected. `cancel` allowed only from non-terminal states and only
if the engine can honor it. `retry` creates/repromotes idempotently.

### API
- `POST /api/v1/backtest/runs` → validate config, create `queued`, spawn a background
  worker (same threading pattern as `main_api` `_INGEST_STATUS`) that runs the existing
  engine and **persists** stage/progress to the run row via the engine's `_emit` channel;
  returns `{run_id}` immediately.
- `GET /api/v1/backtest/runs/{run_id}/status` → light status/progress/stage (poll target).
- `GET /api/v1/backtest/runs/{run_id}` → full run incl. `result` when completed.
- `POST /api/v1/backtest/runs/{run_id}/cancel` → cancel if supported.
- `POST /api/v1/backtest/runs/{run_id}/retry` → idempotent re-run.
- `GET /api/v1/backtest/runs` → recent runs (history / compare picker).

### Routes (frontend)
- `/backtest` — configuration workspace (unchanged config UI).
- `/backtest/runs/{run_id}/loading` — dedicated job monitor.
- `/backtest/runs/{run_id}/results` — dedicated results workspace.
Error is an in-page state on the loading/results route (not a separate route) unless
evidence shows a dedicated `/error` reads better.

## 4. Loading page behavior

A quant job monitor, not a bare spinner. Shows: strategy name + run id; submitted config
summary (universe, date range, benchmark, rebalance, initial capital, fee & slippage
assumptions); data source + snapshot status; **real** current stage from the backend; real
progress only when the backend can provide it; started + elapsed time; a compact activity
timeline (validating → resolving universe → loading PIT data → simulating orders/fills →
applying costs/corporate actions → computing metrics → persisting result); a real/mock/
sample honesty badge; safe cancel (only if backend supports); retry (only when idempotent);
useful non-secret error details. Polls status; `completed` → replace with results route;
`failed/cancelled` → full error state. No endless spinner, no fake percentage.

## 5. Results page IA

Separate professional workspace (not the config clutter). A metric is **omitted** if its
data is unavailable; every metric has a tooltip. Real/mock/PIT badges throughout.
- **Header:** strategy, run id, status, date range, universe, benchmark, snapshot date,
  engine version, created/completed time, data badge, PIT badge, actions (export,
  duplicate config, compare, return to editor) where supported.
- **Overview:** initial/ending equity, total return, CAGR, benchmark & active return, max
  drawdown, volatility, Sharpe, Sortino, Calmar, win rate, profit factor, #trades, avg
  holding, turnover, fees, slippage, exposure summary.
- **Performance:** equity vs benchmark, cumulative vs benchmark, drawdown/underwater,
  monthly heatmap, rolling return/vol/Sharpe (where supported), period tables, cost-adjusted
  vs pre-cost when both exist.
- **Trades:** high-perf sortable/filterable table (id, symbol, side, entry/exit ts+price,
  qty, gross/net PnL, return %, fees, slippage, holding, exit reason, MFE/MAE, signal ref);
  select → detail drill-down (price chart with markers, holding PnL, costs, conditions).
- **Price/Execution timeline:** entry/exit/cover/stop/TP/rebalance markers, duration,
  volume + indicators, zoom/pan/crosshair, missing-bar/corporate-action/suspension/
  delisting treatment.
- **Exposure & Holdings:** gross/net exposure, cash, position count, top weights, sector
  exposure, long/short, concentration, liquidity/capacity warnings when supported.
- **Attribution & Diagnostics (only what the engine computes honestly):** symbol/sector/
  long-short/timing/selection/cost contribution where supported, best/worst trades,
  streaks, parameter snapshot, data-quality + bias warnings (survivorship, look-ahead,
  missing corporate actions, borrow unavailable, mock execution), reproducibility details.
- **Compare (if feasible this phase):** metric deltas, equity/drawdown overlay, trade/
  turnover deltas, parameter & snapshot diffs, not-comparable warning.

## 6. AAS reliability requirements

Every actionable AAS control must have: an existing client route, an existing backend
route, matching HTTP method, correct prefix/base, URL-encoded dynamic params, consistent
trailing-slash, a payload matching the server schema, and error handling that **preserves
the backend error + correlation id** (never collapses to a generic 404). Stale client
state / cached IDs / localStorage must not create dead URLs (validate against known routes
before navigate/fetch). Production build routing must match dev. Acceptance: an E2E clicks
**every** AAS action and asserts **zero** 404 and **zero** unhandled console errors.

## 7. Macro recovery requirements

Fix the real failure at its source (render/schema/null/date/env/stale-state — not a
blanket ErrorBoundary). The tab must present: correct loaded state, meaningful loading
state, recoverable API-error state, unavailable-data state, no-data state — all with
correct Korean (UTF-8). Add a regression test that would have caught the failure. Because
HEAD does not reproduce the crash, hardening targets are real-data shapes the mock path
never emits (nullable BOK/FRED/DART fields) — guard those and render the honest states.

## 8. Data honesty & correctness

- Labels **real / mock / delayed / unavailable** on every data-bearing surface; server logs
  are never confused with UI rendering; Korean encoding verified end-to-end (source UTF-8,
  response headers, JSON serialization, fixtures, E2E visible-label assertions).
- Any ratio that can exceed 1 is **named** a ratio with unit+range in schema+tooltip
  (e.g. `tail_dependency` lower-tail co-exceedance ratio); probabilities are clamped [0,1].
- Long-only beta-neutrality: engine returns explicit infeasibility (`long_only_feasible=
  false`); the UI must **block applying** an infeasible (negative-weight) result to a
  long-only portfolio and require explicit long/short + borrow before enabling it.

## 9. Acceptance criteria & test matrix

| Area | Test | Level |
|---|---|---|
| BacktestRun | legal/illegal status transitions | unit |
| BacktestRun API | create→poll→complete; failure; cancel; retry; refresh-recovery | integration |
| BacktestRun API | run metadata / metrics / trades / charts / error payload contracts | contract |
| Loading UI | create → loading route → real status → auto-nav to results | e2e |
| Results UI | refresh results OK; open trade detail; return to editor; failed-run state | e2e |
| AAS | click every action button → 0×404, 0 console errors | e2e |
| Macro | happy path renders; unavailable + error states; Korean labels visible | e2e + contract |
| Encoding | Korean UTF-8 preserved through API + fixtures | unit + e2e |
| Correctness | tail ratio naming/range; long-only infeasibility blocks apply | unit |
| Build | tsc 0, next build, ruff, full pytest, playwright | ci |

Completion is claimed only with direct evidence, and always separating: logic-validated-on-
mock vs real-data-wired vs unavailable-pending-provider vs needs-PIT.
