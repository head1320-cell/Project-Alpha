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
| Playwright | 98 passed (33 at Phase 0 · 93 before Phase 10) |
| pytest | 1487 passed, 10 skipped (1003 at Phase 0 · 1449 before Phase 10) |
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
| 6b | `TimingFactorModal` → shell + §8.1 item 13 | UI | ✅ `18a77ff` |
| 6b-2 | §8.1 item 4 — factor historical preview | backend+UI | ✅ `2ff6570` `16bdca3` `b54a1a4` |
| 6c | `FactorPickerModal` — E2E net + dialog contract (**Tailwind 전환 미완**) | UI | ⚠️ `8c608a2` `55ed5c2` `9421a1f` |
| 6c-2 | 인라인 스타일 76개 → Tailwind (`style={{` 76→1) | UI | ✅ `dc8a286` |
| 6d | Presets + draft-vs-active comparison (§8.1 11·12) | UI | ✅ (이번 커밋) |
| 7b | **Macro overlay semantics** (restored) + `regime_conditioned` | both | ✅ `e6e05c1` `8ef491f` `e695ecc` |
| 7c | Rule-version display in `ContextStrip` (§4 item ⑨) | **frontend** | ✅ `8c8db18` |
| 8 | Factor catalogue breadth | backend | ✅ (이번 커밋) |
| 8b | Data-source extension (NFCI · VXVCLS) | backend | ✅ (이번 커밋) |
| 9 | `ScenarioPackV2` | both | ✅ (이번 커밋) |
| 10 | Stage wiring (Optimize · Attribution · Journal) **+ 팩 CRUD** | both | ✅ 10a–10d |

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

**Shipped.** `features/catalogue-shell/cataloguePresets.ts` (네임스페이스 하나로 세 창이 공유하는
localStorage 저장소) + 셸의 `presets`/`comparison` 프롭. 세 창(타이밍 팩터·스트레스 시나리오·
알파 팩터)이 모두 채웠다. E2E 7건, 뮤테이션 프로브 3건 전부 잡힘.

**두 개의 "같아 보이지만 다른 사실"을 구분한 것이 이 단계의 핵심이다.**
- *비교 대상 없음* ≠ *차이 없음*. 처음 담는 팩터에 "적용본과 같습니다" 라고 말하면 사용자는
  이미 담은 줄 안다. (타입이 먼저 막는다 — `active: Record | null` 이라 null 을 diff 에 넘기면
  컴파일이 안 된다. 프로브로 확인했고, 그래서 문구 분기를 따로 검증했다.)
- *프리셋* ≠ *룰셋 버전(7c)*. 프리셋은 이 브라우저에만 있고 어떤 런도 가리키지 않는다.
  둘을 같은 말로 적으면 재현 가능하다고 오해한다 — 화면에 그대로 적었다.

비교는 **바뀐 항목만** 나열한다. 전부 나열하면 무엇이 바뀌었는지 묻힌다(프로브 P1 이 이걸 잡는다).

**AlphaFactorModal 의 모드 검증에서 실수 하나.** 프리셋을 되먹일 때 `add`/`replace` 만
허용하도록 손으로 적었는데 실제 union 은 `add|sub|replace|wrap` 이라 두 모드가 조용히 버려졌다.
`MODE_LABEL`(단일 출처)의 키로 검사하도록 고쳤다 — 목록을 손으로 복제하면 늘 때 빠진다.

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

**Shipped: the migration + requirement 13. Requirement 4 re-homed to 6b-2 (drift D6b-1, decided
with the user.)** The plan marked this phase "UI", but **neither** re-homed requirement was
buildable as UI-only — the assumption that Phase 7 would supply everything held only halfway:

| Needed | Phase 7 gave | Gap found at `d7b86ba` |
|---|---|---|
| req 13 — factor sampling frequency | `frequency_conflicts()` (the judge) | the **metadata it reads** was absent: catalogue had no frequency field at all |
| req 4 — historical preview | `SignalState` | no per-factor **time series** anywhere; `evaluate()` returns one current scalar |

Req 13's gap was small and data-shaped, so it ships here: `evaluation_frequency` on all 13 catalogue
entries, plus `frequency_ranks` and `rebalance_options` published **in the catalogue response** so the
rank table stays single-sourced in Python instead of being duplicated in TypeScript. Req 4's gap needs
a rolling historical evaluator — new engine work, and PIT-sensitive — so it becomes **6b-2** rather
than being crammed into a UI commit (ground rule 2). `previewSlot` stays honestly unfilled, exactly
as Phase 6 left it.

**Also fixed here, found by the migration:** `curve_slope` (added to the catalogue in Phase 7) is an
`as_of` factor, and the canary evaluation path `evaluate(id, ticker, market, params)` has nowhere to
put a timestamp — so adding it as a canary rule would have silently created a rule whose value is
always missing, i.e. permanently risk-off. It now renders **visible but not addable**, with the reason
in the row. Hiding it was rejected: a catalogued factor that simply isn't there gives the user no way
to learn why.

### Phase 6c 후속 — Tailwind 전환은 미완으로 남는다 (정직한 기록)

두 번 시도해 두 번 창을 깨뜨렸고, 둘 다 되돌렸다. 브랜치는 검증된 상태(`9421a1f`, 7/7)다.

| 시도 | 결과 | 비용/증거 |
|---|---|---|
| Radix `Dialog` 교체 (`dc2551a`) | 창이 열리지 않음 → revert `9421a1f` | `[role=dialog]`·`.shad-content` 0개, JS 에러 0건. 라우트당 **+20 kB** (`/backtest` 134→154 · `/screener` 122→142) |
| 인라인 스타일 76개 → Tailwind 일괄 | 7/7 실패 → revert | `style={{` 76→1 달성했으나 동작 불가 |
| **배치 1만** (backdrop `style`→`className`) | **7/7 실패** | 동일 스크립트 대조군(되돌린 파일) **7/7 통과** |

**한 줄까지 좁혔다.** 트리거는 backdrop 래퍼 한 곳이다:
`style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.45)",zIndex:1000,display:"flex",…}}`
→ `className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/45 p-[18px]"`

증상은 `getByPlaceholder(...)` **element(s) not found** — 즉 컴포넌트가 렌더되지 않는다.
**원인은 규명하지 못했다.** 확인한 것만 적는다:
- 해당 유틸리티는 빌드된 CSS 에 **실제로 생성되어 있다**(`z-\[1000\]`·`bg-black\/45` 확인) —
  누락된 클래스 문제가 아니다.
- tsc 0 · eslint 0 · `next build` 정상. 컴파일 단계에서는 드러나지 않는다.
- 대조 실험으로 하네스 불안정성은 배제했다(동일 스크립트, 되돌린 파일 → 통과).
- 별도 프로브에서 `Minified React error #423`(하이드레이션 실패 → 루트 전체 클라이언트
  렌더 전환)이 관측된 바 있으나, 그 관측은 스테일 청크 상황에서 나온 것이라 이 실패와
  같은 원인이라고 단정할 수 없다.

**다음에 할 때의 교훈(내 실수):**
1. 76개를 한 번에 바꾸고 마지막에 검증했다 — 4단계로 나눴다고 말했지만 배치마다 초록불을
   확인하지 않았다. 배치 검증을 했더니 **첫 배치에서 즉시** 범위가 한 줄로 좁혀졌다.
2. 디버깅 중 스테일 빌드에 두 번 오진했다. Playwright `reuseExistingServer` 가 남은
   `next start` 를 잡는다 — **실행 전 포트 확인을 절차에 넣어야 한다**
   (`scratchpad/vfp.sh` 가 그 절차: 포트 비우기 → 빌드 → 재확인 → 스펙).

   **7b 에서 같은 함정에 세 번째로 빠졌다 — 이번엔 원인을 정확히 특정했다.**
   `pkill -9 -x next-server` 는 **이 프로세스를 잡지 못한다.** 실제 프로세스명이
   `next-server (v14.2.5)` 라서 `-x`(이름 전체 일치)가 맞지 않는다. 그래서 "포트를
   비웠다" 고 믿은 채 옛 서버가 계속 떠 있었고, 새 빌드가 청크 해시를 바꾸자 옛 서버가
   SSR 한 HTML 이 사라진 해시를 참조해 400 → `ChunkLoadError` → 하이드레이션 실패 →
   모든 선택자 not found 가 됐다(증상이 "컴포넌트가 렌더되지 않는다" 와 구별되지 않는다).

   탐지도 못 믿는다: 이 컨테이너에서 `lsof -t -i:3000` 과 `ss -ltnp` 는 서버가 멀쩡히
   응답하는 동안에도 **빈 결과**를 돌려준다. `fuser -n tcp 3000` 만 실제 PID 를 찾았다.

   → 절차를 **이름 기준에서 포트 기준으로** 바꿨다: `scratchpad/freeport.sh` 가
   `fuser -k -9 -n tcp` 로 3000·8000 을 비우고 실제로 비었는지 재확인한다.
   백엔드(8000)도 함께 비운다 — 라우트를 추가해도 옛 uvicorn 이 살아 있으면 404 가 난다.
   실제로 이번 3자 비교 엔드포인트가 그 404 를 맞았다.

   교훈의 일반형: **"고쳤다" 는 관측이 아니다.** 죽였다고 믿은 프로세스는 죽었는지
   확인해야 하고, 적용했다고 믿은 뮤테이션은 적용됐는지 단언해야 한다(같은 세션에서
   중첩 따옴표 때문에 적용되지 않은 뮤테이션을 "프로브 통과" 로 잘못 읽은 일이 있다).

**6c 가 실제로 남긴 것:** E2E 안전망 6건(이전엔 0건)과 `role`/`aria-modal`/Escape/autoFocus.
안전망이 두 번의 파손을 모두 잡아냈다 — 없었다면 모르고 푸시했을 것이다.
**포커스 트랩은 여전히 없다** — FactorPicker 도, CatalogueShell 기반 AAS 창 3개도.
스펙 §8.1 요구사항이므로 미충족으로 남는다.

### Phase 6b-2 — factor historical preview (§8.1 requirement 4) — **done**
*(re-homed from 6b, drift D6b-1.)* Right-pane preview of value / threshold / **signal state** /
number of state changes over a window. Needs a **new** rolling evaluator (`evaluate()` is
current-value-only) plus an endpoint, and it is **look-ahead sensitive** — the preview must score each
historical point with what was knowable then, which is exactly the trap Phase 1 exists to prevent.
Backend-then-UI, TDD with a mutation probe, and honest `unavailable` where history is too short.

- **Backend `2ff6570`.** `src/engine/timing_factor_history.py` +
  `GET /allocation/timing-factors/{factor_id}/history`. **No new truncation machinery was built** —
  `etf_prices.as_of(months_back)` already provides thread-local point-in-time truncation, so each
  point is evaluated inside it. State judgement reuses Phase 7's three-state rules rather than
  reimplementing them.
- **Frontend (this commit).** `TimingFactorPreview` fills `previewSlot`; changing threshold, direction
  or ticker re-scores the preview because those values are in the query key.

**Honest limitations, carried in the payload's `limitations[]` and rendered verbatim:**

| Limitation | Why it is stated rather than hidden |
|---|---|
| sampling step is **monthly** (`as_of` is month-granular) | a daily factor's flip count is therefore **undersampled**; the note is attached only to day/overnight factors |
| factors with no canary evaluator (`curve_slope`) return a **reason**, not an empty chart | an empty chart looks like a bug and tells the user nothing |
| the endpoint answers **200 + reason**, never 4xx, when a preview cannot be built | "no preview available" is a state, not a request error — a 4xx would make the UI show an error banner |
| missing samples are drawn as **gaps**, never as 0 | a zero bar asserts a value we do not have; `unavailable` also gets its own colour, distinct from `risk_off` |
| state changes are counted **skipping** missing points | treating a gap as a state makes one data hole read as two flips, i.e. "the signal was thrashing" |

**A real product bug surfaced by this phase's gate (fixed in `b54a1a4`).** `WizardTracker` bound
keydown on `window` and navigated stages on ←/→, exempting only `INPUT`/`TEXTAREA`/`SELECT` — **not
open modals**. With any catalogue window open, an arrow key on a list row or family chip navigated the
page and unmounted the dialog, discarding in-progress configuration. Measured:
`/allocation/stress` → `/allocation/explain`, modal count 0. It breaks spec §8.1's keyboard-navigation
and focus-trap requirements and predates 6b-2, affecting all four modals.

It had been masquerading as a flaky test since Phase 6: the assertion passed whenever focus reached
the next chip before React unmounted, so the suite reported "keyboard navigation works" on a race it
won about 20% of the time. **One green run would never have found it** — only repeated runs did.

Two process notes worth keeping, because both nearly shipped a false green:
- **A pipeline ending in `tail` reports `tail`'s exit code.** `npx playwright test | tail` exited 0
  while 4 tests failed. Capture the runner's own status, and read the summary line.
- **The mutation probe caught the regression test guarding nothing.** With the fix reverted the new
  test still passed, twice over: focus was aimed at a non-focusable `div` so it stayed on the
  auto-focused search `input` (already exempt), and two keypresses were asserted immediately so
  `toBeVisible()` won the race before unmount. **A negative assertion needs a settle period.**

**Deliberately not done:** day-granular `as_of`. It would give exact flip counts, but `as_of` is a
shared PIT primitive that live strategy backtests depend on, so widening it belongs in its own phase
with its own regression evidence — not inside a preview feature.

### Phase 6c — `FactorPickerModal`: E2E first, then Tailwind + Radix in place

**Drift D6c-1 (decided with the user): do not migrate to `CatalogueShell`.** The picker fits the
shell on **1 of 6** requirements — two-step flow with a gated STEP2, nested categories with
per-category support counts, recursive factor selection (`innerFunctionId` plus a second factor
operand), a second browsable list pane for functions, `tone`, and `allowNesting` all have no home in
a single-pane shell. Forcing it would cost capability (breaching Phase 6's "no capability lost" gate)
or inflate a shared component with a mode the other three modals never use. Only the availability +
reason surface maps.

**Correction to a wrong claim I made mid-phase.** I asserted that styling this file with Tailwind
would "breach the ADR", and proposed pure CSS. That was wrong on both counts:

- **ADR 001 decision 5** sets the order as AAS shared primitives → AAS factor/scenario windows →
  **Macro and Backtester shared components where reuse is justified**, and says legacy routes are
  untouched *"until deliberately converted"* — a **sequencing rule, not a prohibition**.
  `FactorPickerModal` is shared by Backtester **and** Screener, so it is exactly the next surface in
  that order.
- The `Tailwind·shadcn·CSS-in-JS 이전 금지` line I cited is the **old** `CLAUDE.md` rule that ADR 001
  explicitly records as a *stale invariant the codebase already violates* (§1). I quoted a retired
  rule as if it were live.
- `CSS-in-JS 금지` does hold, but it only justifies **removing** the 76 inline style objects; it says
  nothing about the replacement being pure CSS.

`CLAUDE.md`'s `AAS만 이전, 레거시는 순수 CSS` is a **snapshot of what had migrated as of Phase 5**,
and ADR decision 6 requires amending it whenever a new surface migrates — which this phase does.

**Therefore:** Tailwind utilities over the mapped `--t-*` tokens, and the **vendored Radix
`Dialog`** (`shared/ui/shadcn/dialog.tsx`) for the dialog chrome. Radix supplies a real focus trap,
Escape, and `role`/`aria-modal`, replacing the hand-rolled versions committed in `55ed5c2` — focus
trapping becomes assertable for the first time, where before it simply did not exist.

**Steps.** ① E2E safety net first (`8c608a2`, 6 behavioural tests for a modal that had none, both
consumers) → ② dialog contract (`55ed5c2`, superseded in part by Radix) → ③ Radix `Dialog` +
Tailwind conversion, with the E2E suite as the no-capability-lost gate and `CLAUDE.md` amended per
decision 6.

**Stated honestly:** the E2E gate is behavioural. It proves nothing functional broke; it **cannot**
prove the visuals are unchanged. No visual-regression tooling exists in this repo, so that limit is
real and is not papered over.

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

#### 7b 실행 기록 — **done** (엔진 `e6e05c1` · 표면 `8ef491f` · UI 이번 커밋)

엔진은 `e6e05c1` 에서 만들었지만 **HTTP 표면이 없어 UI 에서 닿을 수 없었다.**
그 배선(`POST /allocation/timing/three-way`)을 하는 순간 엔진의 결함 세 개가 드러났다 —
단위 테스트 20개는 전부 초록이었는데도.

| 결함 | 실제 | `MacroOverlay` 가 기대하던 것 | 결과 |
|---|---|---|---|
| 모드 어휘 | `NORMAL`/`CAUTIOUS`/`DEFENSIVE` (`regime_analyzer.py:65`) | `risk_on`/`neutral`/`risk_off` (이 코드베이스에 없는 어휘) | 표를 빗나감 |
| 스트레스 단위 | **0~100** (`regime_analyzer.py:56`) | 0~1 분수 | 51.8 → 1.0 클램프 |
| 모르는 라벨 | — | `MODE_CAP.get(mode, 0.0)` | 조용히 "전액 방어" |

앞의 두 개가 겹쳐 **첫 실호출이 모든 포트폴리오를 노출 0 으로 떨어뜨렸다.** 단위 테스트가
통과한 이유는 테스트가 내가 지어낸 어휘와 단위를 그대로 먹여 줬기 때문이다 — 자기 일관적이고
현실과 무관했다. CLAUDE.md 의 "수치는 문서가 아니라 코드가 진실입니다" 가 정확히 이 경우다.

부수적으로 고친 것: 충돌 판정이 라벨 문자열(`!= "risk_on"`)을 보고 있어 무해한 `NORMAL` 을
충돌로 보고했다 → **실제로 상한을 걸었는지**로 바꿨다. `to_dict()` 에 `usable` 을 실었다 —
없으면 소비자가 "매크로를 못 읽었다" 와 "매크로가 중립이다" 를 구별할 수 없다.

**사용자 임계 존중** — 3자 비교가 카탈로그 기본 임계로만 채점하고 있었다. 바로 옆의 과거
미리보기(6b-2)는 사용자 임계로 채점하므로, 같은 노브가 두 패널에서 다른 뜻이 될 뻔했다.
`TimingRuleV2.threshold` 로 배선했다. **방향(direction)은 카탈로그가 계속 소유한다** —
`defense_first` 는 음수일 때 위험-온이고, 그건 사용자가 뒤집을 값이 아니다.

**게이트는 한 번 헛돌았다.** 첫 통과 때 타이밍 단독이 0% 라 "끄면 같아진다" 가 0 == 0 으로
참이 됐다 — 통과했지만 아무것도 증명하지 못했다. 스펙에 그 경우를 드러내는 분기를 남기고,
E2E 가 임계를 낮춰 타이밍이 반드시 통과하도록 조건을 고정했다. 토글이 요청에 반영되지 않게
하는 뮤테이션으로 게이트가 실제로 잡는지 확인했다.

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

#### 7c 실행 기록 — **done**

계획은 "백엔드 절반은 끝났고 남은 건 ContextStrip + E2E" 라고 적었는데, **틀렸다.**
`saveTimingRules()` 는 클라이언트에만 있고 **호출자가 없었다** — UI 에서 룰셋을 만들 방법이
아예 없었으므로 `activeRuleSet` 은 런 재열기 말고는 채워질 길이 없었다. 그래서 이 단계는
표시만이 아니라 **생산 경로**까지 만들어야 했다:

- `ThreeWayPanel` 에 "룰셋으로 저장 / 갱신(버전 +1)" 액션. 저장 전 `timingCfg` 는 이 브라우저의
  임시 상태일 뿐이고 런에 박을 좌표가 없다 — 컨텍스트 스트립도 그 둘을 다른 모양으로 적는다.
- `POST /timing-rules` 가 **기록한 버전을 함께 반환**하도록 했다. id 만으로는 "어떤 룰이었는지"
  를 지목할 수 없다(룰셋은 갱신되니까). 버전 열이 degraded 면 **None** 을 준다 — 1 로 지어내면
  복원 불가능한데 복원 가능한 척하게 된다.
- `GET /timing-rules/{set_id}/versions` — 스트립이 **박힌 버전이 아직 실재하는지** 확인한다.
  이 확인이 없으면 삭제된 버전 번호를 그대로 그리게 되고, 그건 "재현됐다" 는 거짓 신호다.
  확인이 끝나기 전에는 단정하지 않는다(로딩 중에 "미상" 이라 적으면 잘못된 경보다).

세 가지 표시를 구분한다: `v3`(확인됨) · `v3 확인 불가`(서버에 없음) · `버전 미기록`(애초에
버전이 없음). 셋을 한 모양으로 적으면 사용자는 구별할 수 없다.

**게이트:** 룰셋 왕복(새로고침 후 되돌리기 → 같은 id·버전) + **사라진 버전이 현재 버전으로
대체되지 않는지**. 후자는 저장된 룰셋을 API 로 삭제한 뒤 화면이 "확인 불가" 를 말하는지 본다 —
이 분기를 테스트 없이 두면 정직성 주장이 코드 주석에만 남는다.

**또 같은 픽스처 함정에 걸렸다.** `_has_version=False` 로 degraded DB 를 흉내 내려 했지만
`_ensure()` 가 테이블을 version 열까지 새로 만들며 플래그를 True 로 되돌린다 —
regime_snapshots 에서 겪은 것과 **같은 패턴**이다. 일반화하면: **초기화 함수가 다시 쓰는
플래그는 픽스처가 미리 내려 봐야 소용없다.** 초기화 이후에 내려야 한다.

### Phase 8 — Factor catalogue breadth
The remaining Phase-1 factors: relative momentum, breadth (incl. equal- vs cap-weight), realized
vol / vol regime / target-vol sizing, drawdown + speed + recovery, rolling correlation, Korea set.
(TSMOM and curve slope ship in Phase 7.) **TDD per factor.**

**Shipped — 12 팩터, 카탈로그 13 → 25.** 패밀리 4개(`breadth·volatility·drawdown·correlation`)를
추가했다. `regime` 에 몰아넣으면 그 패밀리가 15개짜리 잡동사니가 되어 패밀리 필터가 쓸모없어진다.

| 스펙 항목 | 구현 |
|---|---|
| 상대 모멘텀 | `relative_momentum` |
| 브레드스 · 동일가중 vs 시총가중 | `breadth_above_ma` · `equal_vs_cap` |
| 실현변동성 · 변동성국면 · 목표변동성 사이징 | `realized_vol` · `vol_regime` · `target_vol_size` |
| 낙폭 · 속도 · 회복 | `drawdown` · `drawdown_speed` · `recovery_state` |
| 롤링 상관(주식-채권·크로스에셋) | `rolling_correlation` (벤치마크가 파라미터라 한 팩터가 둘 다 커버) |
| 한국: 코스닥/코스피 상대강도 · 원달러 추세 | `kospi_kosdaq_rs` · `usdkrw_trend` (**ETF 프록시**) |
| 한국: 섹터 디스퍼전 | **8b 로 재배치** — 섹터 지수 시계열이 없다(Drift 8-1) |

**Drift 8-5 — 날짜 없는 접근자.** `daily_closes()` 는 값만 준다. 두 종목의 꼬리를 zip 하면
거래일이 같다고 가정하게 되는데 한·미 휴장일과 상장일이 달라 실제로는 다른 날짜끼리 짝지어진다.
`daily_closes_indexed()` 를 추가(가법적, 캐시·as_of 관례 동일)해 **겹치는 날짜만** 쓴다.

**뮤테이션 프로브 5건 전부 잡힘** — vol_regime 0 나눗셈 가드, 상관 0 표준편차 가드, 낙폭 부호,
읽지 못한 바스켓 종목을 '이탈'로 세기, 상관의 날짜 조인을 naive zip 으로 바꾸기.

**내 테스트에서 발견한 결함 2건.**
- 날짜 정렬 테스트(이 접근자의 **존재 이유**)가 아무것도 검증하지 못했다. 어긋난 쪽을 정렬된
  쪽의 **접미사**로 만들었더니 naive zip 도 우연히 맞아떨어져, 조인을 zip 으로 바꾸는 뮤테이션이
  53개 테스트를 전부 통과했다. 실제 휴장일은 **가운데**에 생긴다 — 그렇게 다시 만들었더니
  조인 1.0 vs naive zip 0.918 로 갈렸다.
- 값을 대칭으로 만든 상관은 −1 이 아니라 −0.9996 이다(퍼센트 수익률은 기준이 서로 다르다).
  거짓 전제 위의 단언을 참인 주장으로 바꿨다.

**기존 결함 1건을 기록으로 남겼다.** `indicator` 는 카탈로그에 있는데 `evaluate()` 분기가 없어
V2 경로에서 영원히 unavailable 이다(레거시 카나리 경로에서만 동작). 새 무결성 테스트가 잡았고,
제대로 고치려면 시점 기반 매크로 리더가 필요해 **8b** 소관이다 — 면제 목록에 사유와 함께 남겼다.

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

#### 9 실행 기록 — **done** (엔진 `b5aae9e` · API `0ace764` · UI 이번 커밋)

앞선 커밋에서 **historical simulation 엔드포인트**(`c557403`)를 먼저 붙였다 — 스펙 §7 이
`timing_routes.py` 에 배정한 7/8 이 있었고 이것만 없었다. 리스크 레지스터가 이 엔드포인트에
할당한 `forward_only` 차단이 여기서 실제로 걸린다.

**드리프트 4건은 사용자에게 물었다** (계획 가드레일 4번):

| 드리프트 | 결정 |
|---|---|
| §5 의 12 패밀리 중 3종이 비어 있음 | 새 팩 3 + 국면 팩 1 추가, 12종 전부 선언 |
| `user-authored` 는 저장을 함의 | 인라인 전용, **CRUD 는 Phase 10 으로 재배치** |
| 3자 비교(노출) × 시나리오(손실) 합성 형태 | `충격 × 노출`, 나머지는 현금 |
| mock 환경에서 백테스트 모드가 항상 거부 | 두 모드, 기본은 `backtest` |

**뮤테이션 프로브가 이번에도 실제 결함을 잡았다 — 그중 둘은 내 코드의 것이다.**

1. **판정하지 못한 다리에 0% 손실.** 스냅샷이 없으면 `timing_macro` 는 노출 0 의
   `unavailable` 인데, 곱셈만 하면 -0.0% 로 나와 **만들지 못한 비교가 셋 중 가장 안전해
   보였다.** 노출 0(현금)과 "알 수 없음" 은 다른 사실이다. 테스트가 아니라 실제 응답을 눈으로
   보고 발견했다.
2. **NaN 이 전액 노출로 둔갑.** `max(0, min(1, nan))` 은 **1.0** 이다(NaN 비교가 전부 False
   라 `min` 이 첫 인자를 그대로 낸다). 값을 얻지 못한 다리가 조용히 최대 손실로 채점되고,
   NaN 은 JSON 에도 그대로 실려 나가 엄격한 파서를 깨뜨린다.
3. **합성 테스트가 헛돌고 있었다.** 판정된 다리가 전부 노출 1.0 이라 곱셈이 항등이었다 —
   곱셈을 통째로 지워도 통과했다. 노출 0.5 를 만들어 다시 세웠다(7b 와 같은 함정).

**정직하게 밝히는 두 가지.** (1) `tsc` 는 `22f3a61`(Debt 3) 시점에 **깨끗하지 않았다** —
`admin-data.spec.ts` 에 암묵적 `any` 가 하나 있었는데 그 커밋에서 "clean" 이라고 보고했다.
이번에 고쳤다. (2) 국내팩을 고르면 컨텍스트 스트립이 `scenario`(= `/stress` 실행 가능 id)를
읽어 **활성 시나리오를 잘못 적고 있었다.** 팩 신원을 붙이면서 `scenarioPackId` 를 별도로 들게
했다.

### Phase 10 — Stage wiring
**시나리오 팩 CRUD** *(Phase 9 에서 재배치 — `user-authored` 는 인라인 실행만 도착했다)*:
저장·목록·버전·삭제. `timing_rule_sets` 의 관례를 따르되, 저장된 팩도 `model_type` 은 서버가
정한다(사용자가 역사적 사실을 주장할 수 있으면 §5 가 무의미해진다).
Optimize (timing as explicit constraint/overlay, before/after + infeasibility reasons),
Attribution (allocation / timing / selection / factor / cost / residual; ex-ante vs ex-post),
Execution (paper-only preview, costs, liquidity, borrow, approval states — **no live orders**),
Journal (one ResearchRun holds snapshot + rule set + scenario pack + constraints + rationale).

#### 10 실행 기록 — **done** (10a `7263211` · 10b `a3fd9ca` · 10c `5f5ca47` · 10d `f582f1d`)

**먼저 측정한 것이 이 페이즈의 모양을 바꿨다.** 네 스테이지(Optimize·Attribution·Execution·
Journal)는 이미 실동작 백엔드를 갖고 있었다 — Phase 10 은 **배선**이지 신축이 아니다.

| 요구 | 실측 | 결과 |
|---|---|---|
| R1 팩 CRUD | 없음(인라인 전용) | **10a** |
| R2 Optimize — 전략 비중을 조용히 덮어쓰지 않는다 | ◐ 제약·리포트는 있고 **타이밍이 입력이 아니었다** | **10c** |
| R3 Attribution 6분해 | ◐ cost·residual ✅, Brinson 4종 `None` | **10d** (timing 만) |
| R4 Execution | ✅ **이미 충족** — 비용·유동성·차입(정직 미상)·승인 전이·실주문 없음 | 작업 없음 |
| R5 Journal — 런이 전부를 든다 | ◐ 스냅샷·룰셋·제약 ✅, **팩·근거 ❌** | **10b** |

**R4 는 이미 충족돼 있어 아무것도 하지 않았다.** 페이즈 제목을 채우려고 일을 지어내지 않는다.

**계획의 전제 하나가 코드와 접촉해 무너졌다(10c).** 초안은 `applyTiming` 을 오버레이로
바꿔도 "노출 1.0 이면 같은 결과" 라 안전하다고 적었다. **위험-오프에서 거짓이다** —
`timing_routes.py:455–528` 이 IEF/SHY + BIL 로 **교체**하므로 배율로는 재현할 수 없다.
그대로 진행했다면 위험-오프 자산 로테이션이 조용히 사라졌을 것이다. 사용자에게 물어
**"둘 다 남기고 파괴적인 쪽에 그렇게 이름 붙이기"** 로 결정했다.

**뮤테이션 프로브 21개가 전부 잡혔고, 그중 셋은 방어가 두 겹이라 바깥 겹만 보고 있었다** —
저장 팩의 `model_type`(스키마 + 하드코딩), 오버레이 노출 상한(프로바이더 + 패널). 안쪽 겹을
직접 겨냥한 테스트를 따로 세웠다.

**테스트가 스스로 헛돈 것을 두 번 잡았다.** (1) 저널 링크 테스트가 DB 부재 상태에서 돌아
모든 조회가 None 이었다 — 같은 인메모리 엔진을 물려 실제 검증으로 바꿨다. (2) E2E 가
**스테일 `.next` 빌드**에 대고 옛 버튼 라벨을 단언했고, `addInitScript` 가 네비게이션마다
재실행되며 오버레이를 씨앗으로 되돌리고 있었다.

### Phase 11a — 스펙 재감사 (읽기 전용, 근거 기반)

Phase 0–10 이 끝난 뒤 §§1–10 을 코드와 대조했다. **개수는 근거가 아니다** — 각 항목마다
파일:라인을 확인했다. 판정은 충족 / 미충족 / 데이터차단 셋뿐이다.

감사 도중 **내 자신의 grep 이 한 번 틀렸다**: `grep -l CatalogueShell` 이 *주석 언급*을
잡아 FactorPicker 가 셸을 쓴다고 보고했다. `^import` 로 다시 확인해 바로잡았다 — 이
프로젝트가 문서화된 개수에 두 번 데인 것과 같은 종류의 오류다.

#### 미충족 5건 (전부 **구현 가능** — 데이터 차단 아님)

| # | 요구 | 실측 | 근거 |
|---|---|---|---|
| A1 | §3.2 `TimingFactorDefinition` 9개 필드 | **3개만 존재** — `provenance`·`evaluation_frequency`·`unit`(스펙은 `units`). `allowed_range`·`release_lag`·`revision_policy`·`availability`·`unavailable_reason` **부재**. `use_mode` 는 *룰*에는 있고(`timing_rules_v2.py:320`) *정의*에는 없다 | `CATALOG_BY_ID` 전 항목 키 합집합 = `default_direction, default_threshold, desc, evaluation_frequency, existing, family, id, label, params, provenance, requires_as_of, unit` |
| A2 | §6 provenance 라벨 4종(`systrader_public` 등) | **자유 텍스트 인용문**이다 — "Antonacci (Dual Momentum)", "FRED/ALFRED (NFCI)". §6 이 막으려는 *위험*(유료 전략 복제 암시)은 오히려 실제 공개 출처를 적어 더 잘 막고 있으나, **분류로 필터·그룹할 수 없다** | `timing_factors.py` 카탈로그 |
| A3 | §3.4 `DataLineage` | **코드 어디에도 없다** — 타입도 필드도 UI 도 0건 | `grep -rn lineage src/ frontend/src` → 0 |
| A4 | §8.1 우측 패널 "impact preview" | 셸에 없다 | `CatalogueShell.tsx` |
| A5 | §8.1 네 번째 창 | `FactorPickerModal` 이 셸을 쓰지 않는다 | `^import` 확인 — 나머지 셋은 ✓ |

★A3·A4 는 §8.1 **소유권 표가 Phase 6 배달로 적어 둔 항목**이다.★ 포커스 트랩 행이 똑같이
거짓이었고(그래서 세 페이즈를 살아남았다) 기술부채 정리에서 바로잡았다. 같은 표에 같은 종류의
오류가 둘 더 있었다 — 표를 믿지 말고 코드를 읽으라는 CLAUDE.md 의 규칙이 여기에도 적용된다.

#### 낡은 기록 2건 (바로잡음)

- 6c 기록 *"포커스 트랩은 여전히 없다"* → **거짓**. Debt 2 가 배달했고
  `FactorPickerModal.tsx:158`·`CatalogueShell.tsx:168` 이 `useFocusTrap` 을 호출한다.
- 실행표 6c ⚠️ *"Tailwind 전환 미완"* → **거짓**. 6c-2(`dc8a286`)가 끝냈다(`style={{` 1개).
  실제 미완은 **셸 이전**뿐이다.

#### 확인된 충족 (표본)

§1 실주문 없음(`execution_routes.py` 에 `place_order` 0건) · §3.1 ALFRED 빈티지 + **의무
테스트** GDPC1 원공표값(`tests/test_pit_macro.py`) · §3.3 추가 9필드 **전부** ·
§5 `model_type` + 12 패밀리 + 팩 CRUD · §7 지정 라우터 3개 전부 · §8 `/allocation/macro` ·
§9 게이트(pytest 1487 · Playwright 98).

### Phase 11b — `AllocationProvider` 슬라이스 분할 (Deferred 항목 소화)

**측정된 동기.** 파일은 743줄 · 컨텍스트 필드 ~90개까지 자랐고(스펙 감사 시점 522/40+),
`const value: AllocationCtx = { … }` 는 **평범한 객체 리터럴**이라 매 렌더 새 신원이 된다.
소비자 26개가 전부 `useAllocation()` 하나로 구독한다.

**계획했던 2단계 중 1단계는 버렸다 (실측 근거).** "먼저 `useMemo` 로 감싸면 이득의 싼 절반을
얻는다" 는 전제가 **거짓**이었다 — 컨텍스트 값에 담기는 핸들러 20개가 전부 매 렌더 새로
만들어지는 화살표 상수라, `useMemo` 를 씌워도 의존성이 매번 달라져 캐시가 한 번도 맞지 않는다.
효과 없는 변경을 "최적화" 라고 커밋하지 않기 위해 이 단계는 실행하지 않았다.

**"형제 5개" 도 거짓이었다.** `runAnalyze` · `recordRun` · 타이밍 쿼리가 제안된 모든 경계를
가로질러 holdings · views · model · delta · tau · constraints 를 읽는다. 그래서 형제가 아니라
**위계**로 나눴다 — 사용자 승인:

| 계층 | 파일 | 소유 |
|---|---|---|
| 기반 | `slices/PortfolioContext.tsx` | holdings · views · model · delta · tau · constraints · `hydrated` |
| ↳ | `slices/TimingContext.tsx` | timingCfg · timingOverlay · activeRuleSet · `timingQ` |
| ↳ | `slices/ScenarioContext.tsx` | scenario · scenarioPackId · runPackHash · bump · severity · `stressQ` |
| ↳ | `slices/RunContext.tsx` | result · lastRun · activeRun/Study 신원 · analyze 뮤테이션 · `xrayQ` |
| ↳ | `AllocationProvider.tsx` (조립) | 타임라인 · 위저드 · 스냅샷 · **슬라이스를 가로지르는 핸들러 전부** |

중첩 순서는 취향이 아니라 의존이다 — 아래 세 슬라이스의 쿼리가 전부 보유 종목을 읽는다.
부수 효과로 하이드레이트 순서가 **구조적으로** 보장된다: React 는 자식 이펙트를 먼저 돌리므로
가장 바깥이 올리는 `hydrated` 가 서는 시점엔 모든 슬라이스의 복원이 끝나 있고, 작업셋 저장이
빈 상태를 덮어쓸 수 없다.

**저장 규칙.** 공유 블롭 `alpha_alloc_wip` 은 **읽기는 각자, 쓰기는 조립 계층 한 곳**
(슬라이스마다 같은 키에 쓰면 서로를 덮어쓴다). 전용 키(`alpha_alloc_ruleset`)는 소유 슬라이스가
읽고 쓴다. 키 형식은 한 글자도 바꾸지 않았다 — 기존 세션과 E2E 시드가 그 형식에 걸려 있다.

★**이 커밋은 구조만 바꾼다**★ 소비자가 `useAllocation()` 으로 전부 구독하는 동안에는 렌더
절감이 **없다**. 그 이득은 소비자가 좁은 슬라이스 훅으로 옮길 때 오고, 그건 26개 호출부를
고치는 별개의 변경이다(ground rule 2 — 한 커밋에 두 변경 금지). 얻은 것은 "상태의 소유자가
하나" 라는 성질이고, 그것이 이후 이전을 가능하게 한다.

**경계는 주석이 아니라 lint 로 강제한다.** `.eslintrc.js` 에 슬라이스 전용 override —
슬라이스는 서로를 import 할 수 없고 기반 `PortfolioContext` 만 예외다. 없으면 "파일만 늘고
결합은 그대로" 로 돌아간다.

| 변이 | 결과 |
|---|---|
| `ScenarioContext` 가 `./RunContext` 를 import | eslint `no-restricted-imports` 1 error ✅ |
| 합성된 `useAllocation()` 모양에서 `timingOverlay` 제거 | tsc TS2741 ✅ |

**게이트(실측):** pytest **1487 passed / 10 skipped**(불변) · Playwright **98 passed, exit 0**
(36.2m, 1 worker) · tsc 0 · eslint 0 error(경고 28 — 기준선과 동일) · `next build` exit 0 ·
**E2E 스펙 수정 0건**. 마지막 항목이 이 단계의 진짜 게이트다 — 순수 리팩터링의 유일한 증거는
"아무것도 움직이지 않았다" 이고, 선택자를 하나라도 고쳐야 통과한다면 동작이 바뀐 것이다.

### Phase 11c — `FactorPickerModal` → CatalogueShell (§8.1 의 마지막 창)

**계획된 매핑은 대체로 맞았고, 세 군데가 틀렸다. 전부 실측으로 드러났다.**

#### 드리프트 1 — 안전망이 이전을 넘기지 못했다 (사용자 판단: 단계 제거 + 재작성)

6c 가 깐 `e2e/factor-picker.spec.ts` 는 "동작으로 단정하니 셸로 옮긴 뒤에도 그대로 게이트가
된다" 고 적었지만, **7개 중 5개가 2단계 모델 자체**를 단정하고 있었다(`STEP2 함수 선택`
버튼의 disabled/enabled · `다음 단계` 3곳 · `이전 단계` · `STEP1 팩터 선택`). 단계를 없애는
변경 앞에서 그건 그물이 아니라 걸림돌이다. 단계를 제거하고 그 5개를 **단일 화면 기준의 동등한
단언**으로 다시 썼으며, 그물은 7 → **10개**로 늘렸다(중첩 출력·포커스 트랩·개수 노출 추가).

> **기록 정정.** 커밋 `a2a217b` 의 메시지와 이 절의 최초 판은 "6개 중 4개" 라고 적었다.
> 실측은 **7개 중 5개**다(`git show a2a217b^:frontend/e2e/factor-picker.spec.ts` 기준). 전체
> 스위트 합계가 이를 뒷받침한다 — 98 − 7 + 10 = **101**. 판단은 달라지지 않지만(오히려 근거가
> 더 강하다) 근거 수치를 틀리게 적은 것은 그 자체로 고칠 일이다.

#### 드리프트 2 — 셸에 자리가 없는 능력 3가지 (사용자 판단: 셸을 확장해 전부 보존)

카테고리 13 → 그룹 42 의 2단 위계 · 카테고리별 지원 개수 `n/m` · `tone`. 셸에 선택적
`groupLabel` · `countLabel` · `styleVars` 를 먼저 더한 뒤 창을 옮겼다(커밋 `f3dbe1f`).
기존 세 창은 아무것도 넘기지 않으므로 렌더가 동일하다. `countLabel` 이라는 이름은
`StressScenarioModal` 이 이미 `count: number` 를 달고 있어서다(실측: tsc TS2322).

#### 드리프트 3 — FSD 가 이전 자체를 막았다 (계획에 없던 항목)

`features/factor-picker` 가 `features/catalogue-shell` 을 import 하는 것은 **같은 계층
슬라이스 간 import** 라 Step 2b 의 가드레일이 막는다(실측: `import/no-restricted-paths`
에러 1건). 규칙 메시지가 안내하는 대로 셸을 shared 로 내렸다 —
`shared/ui/CatalogueShell.tsx` · `shared/lib/cataloguePresets.ts`. 셸은 이미 도메인 타입을
하나도 모르므로 원래 이 자리가 맞았고, "네 창이 한 셸을 쓴다" 는 §8.1 의 주장이 구조로도
참이 된다. 가드레일에 예외를 뚫는 선택지는 취하지 않았다 — 그러면 규칙이 규칙이 아니게 된다.
(부수 발견: `cataloguePresets` 는 배럴에 못 넣는다. `screenerPresets` 가 `savePreset` 등
같은 이름을 이미 내보낸다 — 실측 tsc TS2308 3건. 둘은 다른 저장소이고 합칠 물건이 아니다.)

#### ADR 001 번들 게이트 — 걸렸고, 되돌리는 대신 고쳤다

셸이 shadcn/Radix ToggleGroup 을 끌고 오면서 첫 로드가 `/backtest` 134 → **151 kB**,
`/screener` 122 → **138 kB** 로 뛰었다. ADR 001 은 설명되지 않는 4 kB 증가를 되돌리라고 한다
(6c 의 Radix 시도가 +20 kB 로 되돌려진 전례가 이 계획에 적혀 있다). **기본이 '닫힘' 인 창은
첫 로드에 있을 이유가 없다** — 두 소비자에서 `next/dynamic` 으로 바꿨다. 결과는 기준선보다
**낮다**: `/backtest` **128 kB**(−6) · `/screener` **110 kB**(−12).

#### 잃은 것 · 바뀐 것

`FactorPick` 출력 계약은 한 필드도 바뀌지 않았다. 미지원 사유는 `title=` 툴팁에서 **목록 행**
으로 옮겼다(나머지 세 창이 의도적으로 지키는 규칙). 대체 제안 칩 중 카탈로그에 없는 이름은
이제 **비활성**이다 — 눌러도 아무 일이 없던 이전 동작은 사용자가 자기 조작을 의심하게 만든다.

| 변이 | 결과 |
|---|---|
| 방출되는 `FactorPick` 에서 `innerFunctionId` 제거 | 중첩 E2E 실패 ✅ |
| 미지원 토큰을 `available: true` 로 표시 | 미지원 정직성 E2E 실패 ✅ |
| 슬라이스 간 import (11b 가드레일) | eslint 1 error ✅ |

**게이트(실측):** pytest **1487 / 10 skipped**(불변) · tsc 0 · eslint 0 error(경고 28) ·
`next build` exit 0 · 첫 로드 두 라우트 모두 기준선 이하 · factor-picker **10 passed** ·
전체 Playwright **101 passed, exit 0**(35.8m, 1 worker; 98 − 7 + 10).

### Phase 12 — 11a 감사의 미충족 4건 (A1–A4) 소화

11a 감사가 남긴 미충족 5건은 **전부 구현 가능**(데이터 차단 아님)이었다. A5 는 Phase 11c 였고
나머지 넷을 여기서 닫는다.

> **기록 정정.** Phase 11c 를 끝낸 직후 나는 "남은 것은 데이터 차단 항목의 문서화뿐" 이라고
> 보고했다. **틀렸다** — 내가 쓴 11a 감사 표가 바로 위에서 A1–A4 를 "구현 가능" 으로 적고
> 있었다. 데이터 차단 항목(Brinson 3성분 · 대차 피드)은 §9·§6.1 에 이미 반영돼 있었고,
> 실제로 남아 있던 것은 이 넷이다.

| # | 요구 | 배달 | 핵심 결정 |
|---|---|---|---|
| A1 | §3.2 정의 9필드 | **12a** `timing_factor_meta.py` | 값을 **유도**한다 — 29×8 을 손으로 채우면 대부분 추측이 된다 |
| A2 | §6 provenance 열거형 | **12a** `provenance_class` | 인용문을 **대체하지 않고 옆에** 붙인다. 미분류는 `None` + CI 금지 |
| A3 | §3.4 `DataLineage` | **12b** `data_lineage.py` + `.tfm-lin` | 계보는 **읽기**를 적는다. mock 은 "허용" 이지 "사용" 이 아니다 |
| A4 | §8.1 impact preview | **12c** `.tfm-imp` | 같은 엔드포인트에 초안만 더해 **실측**. 못 읽으면 0 이 아니라 "계산 불가" |

**덤으로 §6.1 이 요구하던 것 하나.** "소스 없음" 묶음(VIX 스큐 · 대차/공매도 잔고 · 옵션
내재상관 · 혼잡도)이 이제 **카탈로그에 보이되 켤 수 없다**. 이것이 `availability` 를
장식이 아니게 만드는 항목이기도 하다 — 없었다면 모든 항목이 `available` 이었다.

**기존 가드 2개가 이 추가에 걸렸고, 옳았다.** 도달성 검사는 "소스 없음" 을 건너뛰도록
좁히되, 그 분기가 **우회로가 되지 않도록** 새 테스트를 붙였다 — `unavailable` 을 붙이려면
사유가 있어야 하고 실제로 `evaluate()` 가 `None` 이어야 한다. 배선을 깜빡한 팩터에 표시만
달아 검사를 통과시키는 길을 막는다.

**`units` → `unit`: 고친 쪽은 코드가 아니라 스펙이다.** 프런트 타입이 `unit` 을 계약으로
쓴다. 한 글자를 맞추려 살아 있는 계약을 깨는 것은 감사가 지적한 문제(이름 불일치)보다 크다.

| 변이 | 결과 |
|---|---|
| 분류 규칙 없는 새 출처를 단다 | 분류 테스트 실패 ✅ |
| 배선된 팩터에 `unavailable` 을 달아 도달성 검사를 우회 | 우회 방지 테스트 실패 ✅ |

**게이트(실측):** ruff clean · pytest **1529 / 10 skipped**(11c 기준 1487 → +42) · tsc 0 ·
eslint 0 error(경고 28) · `next build` exit 0 · timing-factors E2E **13 passed**(8 → +5).

### Deferred
~~`AllocationProvider` splits into slices~~ — Phase 11b 에서 소화(위 참조).
§8.1 의 네 창은 Phase 11c 로 **전부** 한 셸 위에 있다.

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
