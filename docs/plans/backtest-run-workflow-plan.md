# Implementation Plan — Backtest Run Workflow + AAS/Macro hardening

Companion to `docs/specs/backtest-run-workflow.md`. Independently testable phases, small
commits, TDD where practical. Sequence (user-chosen): **bugs first, then backtest.**

## Reuse map (do not reinvent)
- Durable persistence idiom: `src/data/research_runs.py`, `src/data/execution_store.py`,
  `src/data/journal_store.py` (DB-optional raw-SQL, honest failure → `None`).
- Threaded background job + status polling: `main_api.py`
  `_INGEST_TARGETS/_INGEST_STATUS/_INGEST_RUNNING` + `ingest_trigger`.
- Engine progress channel: `kis_backtest_engine.py::_emit`,
  `screener_routes._screen_to_backtest_core(progress_cb=...)`, `/screen-to-backtest-stream`.
- Result rendering already built in `TerminalBacktester.tsx` (equity/benchmark curve,
  drawdown, monthly heatmap, `SymbolPerfTable`, trade drill-down) → extract into results.
- Multi-backtest persistence reference: `multibacktest_schema.py`, `stage11_routes.py`.
- API base/proxy: `src/lib/apiBase.ts`, `app/api/backend/[...path]/route.ts`.
- CSS tokens: `.tbt-*/.bsc-*/.as-*`, skeletons `tshimmer/tspin/tbt-stages`, `tdata-badge`.

## Phase 2 — E2E harness (prerequisite for the lock-in tests)
- Add `@playwright/test` devDependency; `frontend/playwright.config.ts`; `frontend/e2e/`.
- `frontend/e2e/fixtures/stub-backend.*`: formalize the session stub — a small FastAPI app
  that mounts the **real** routers (macro, allocation family, screener/backtest) with
  SQLite + `KIS_USE_MOCK=1`, so E2E exercises real code paths with deterministic mock data.
  A global-setup boots stub(:8000) + `next start`(:3000, `BACKEND_URL`), teardown kills.
- `package.json` `test:e2e`; CI job in `.github/workflows/ci.yml` (chromium at
  `PLAYWRIGHT_BROWSERS_PATH`, no download).
- Rollback: additive; removing the devDep + e2e/ reverts.

## Phase 3 — Macro hardening + honest states + regression
- Files: `frontend/src/components/macro/*` (sub-tab parts), `frontend/src/lib/macroData.ts`,
  optionally `src/api/macro_routes.py` (only if a real-data null path needs a safe default).
- Work: null/shape guards on every field consumed from macro payloads (real BOK/FRED can be
  null where mock is not); five honest states (loaded/loading/recoverable-error/
  unavailable/no-data) rendered from the data itself, no blanket ErrorBoundary.
- Tests: backend contract test asserting each macro endpoint's shape + nullable fields;
  `e2e/macro.spec.ts` (happy path renders all sub-tabs; forced-error + unavailable states;
  Korean labels visible & correctly encoded).
- Risk: over-guarding hides real bugs → guards render an explicit unavailable state, never
  silently blank.

## Phase 4 — AAS 404 reliability + regression
- Files: `frontend/src/components/allocation/AllocationProvider.tsx` (validate `lastPos` &
  cached ids against known STAGES routes before push), `GoalGate.tsx` (Resume guard), the
  `*Api.ts` clients (surface backend error + correlation/request id instead of a generic
  message), possibly `app/api/backend/[...path]/route.ts` (trailing-slash/path-encode
  hardening if evidence shows it).
- Tests: `e2e/aas.spec.ts` clicks **every** AAS action across all stages, asserts 0×404 and
  0 console errors; unit test for the route-validation helper (stale/renamed route → safe
  fallback, never a dead push).
- Risk: none functional; changes are defensive.

## Phase 5 — BacktestRun workflow (TDD, sub-phased)

### 5a Domain (`src/data/backtest_runs.py`, `tests/test_backtest_runs.py`)
Raw-SQL table `backtest_runs`; `create/get/get_status/list/transition/set_result/
set_error/cancel/expire`. `_TRANSITIONS` map enforces the status model; illegal transitions
rejected. Tests first (legal path, each illegal transition, terminal immutability).

### 5b API + background exec (`src/api/backtest_run_routes.py`, `tests/test_backtest_run_routes.py`)
`POST /runs` validates + creates `queued` + spawns a worker thread (pattern from
`_INGEST_STATUS`) that drives the existing `_screen_to_backtest_core` with a `progress_cb`
that writes stage/progress to the run row; returns `{run_id}` immediately. `GET
/runs/{id}/status`, `GET /runs/{id}`, `POST /runs/{id}/cancel|retry`, `GET /runs`. Register
in `main_api.py`. Tests: create→poll→complete; failure sets `failed`+error; refresh-recovery
(status read via a fresh engine/connection); cancel; retry idempotency; contract shapes for
metadata/metrics/trades/charts/error.

### 5c Loading route + submission (frontend)
`lib/backtestRunApi.ts`; `app/backtest/runs/[runId]/loading/page.tsx`;
`components/backtest/RunMonitor.tsx`. Change `TerminalBacktester` Backtest button:
local-validate → `POST /runs` → on real `run_id` `router.push(loading)`. **Remove** in-page
final-result rendering from the execution mode (keep config UI). Loading page per spec §4;
poll via react-query `refetchInterval`; `completed` → `router.replace(results)`.

### 5d Results workspace (frontend)
`app/backtest/runs/[runId]/results/page.tsx` + `components/backtest/results/*` — extract &
reuse existing chart/table components into Header/Overview/Performance/Trades/Timeline/
Exposure/Attribution sections per spec §5. Omit unavailable metrics; honesty+PIT badges;
return-to-editor/duplicate/export. `.brun-*` CSS additions.

### 5e Compare (if feasible)
`app/backtest/runs/compare` picker + overlay; not-comparable warning.

### E2E (full flow)
`e2e/backtest.spec.ts`: create → loading (real status) → auto-nav results → refresh OK →
trade detail → return to editor → failed-run state.

## Migration / rollback
- New `backtest_runs` table is created lazily (idempotent); no destructive migration.
- Old in-page execution path can remain until 5c/5d land, switched by route, avoiding a
  big-bang cutover. Each sub-phase is a focused, revertible commit.
- Background worker runs in the single uvicorn process (`--workers 1`); run state persists
  to DB so refresh/other-connection recovers. If multi-worker is ever needed, the DB-backed
  state already supports it (no in-memory-only run state).

## Verification (every phase)
`KIS_USE_MOCK=1 pytest tests/` green · `ruff check` · `tsc --noEmit` 0 · `next build` ·
`playwright test` · screenshots/browser-evidence for loading, results, AAS, Macro.
Report separates: logic-on-mock vs real-wired vs unavailable-pending-provider vs needs-PIT.
