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

> **Shipped in Phase 7** — `src/engine/timing_rules_v2.py`. All nine added fields present on
> `TimingRuleV2`, which wraps (not replaces) the existing `TimingRule`. Five of the six combination
> methods implemented; **`regime_conditioned` is deferred to Phase 7b** because it means "weight
> rules by macro regime" and therefore needs the macro overlay semantics 7b owns. `combine()` keeps
> the enum member and **raises naming that phase** rather than silently substituting another method.
>
> The legacy `timing_factors.passes() -> bool` is **left untouched** — the live canary endpoint calls
> it, its behaviour is already conservative (`None → False`), and what §3.3 objects to is the *type*.
> It retires when its last caller migrates, not before. `timing_rules_v2` does not import it.
>
> Two semantics this section left open, decided in Phase 7 and recorded in the plan (D7-5, D7-6):
> **rule-set versions preserve their content immutably** (a counter alone cannot satisfy "reopening
> restores the same version" — the content would already be gone), and **cooldown is symmetric across
> signal flips but never blocks a transition into `unavailable`** (losing data is not a signal flip;
> holding `risk_on` through it leaves the book exposed on a value we no longer have).

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

> **Phase 1 built this; Phase 7 gave it its first callers.** `fetch_observations` and
> `assert_backtest_eligible` had **zero** production callers until Phase 7 (tests only), which
> Phase 1's commit stated honestly — there was no historical simulation to gate yet.
> `timing_rules_v2.read_curve_slope` derives `ResearchUsage` from the observations themselves
> (vintage present · requested depth covered · `release_timestamp >= observation_period`), and
> `evaluate_rule_set(..., mode="backtest")` calls the gate **before** any value is scored, so
> ineligible data never reaches logs or caches.
>
> One consequence worth stating plainly: a price factor read while `mock_allowed()` is true is
> **never** `backtest_eligible`. The value may be synthetic and we cannot prove it is not; certifying
> the unprovable would make the gate a lie. `DataStatus.MOCK` here means "may be synthetic, not
> certified real", not "is definitely fake".
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
> | **scenario pack** | ~~selected scenario's **label**~~ → **✅ 팩 신원 `pack_id@hash` + model_type 배지** | ~~Phase 9~~ **완료** |
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

> **✅ Phase 9 실행 기록 — `src/engine/scenario_packs.py`.**
>
> 시나리오 15종이 서로 모르는 세 곳에 흩어져 있었고(`STRESS_SCENARIOS` · `_HIST_WINDOWS` ·
> `kr_scenario_pack.SCENARIOS`) **`model_type` 은 어디에도 없었다.** `/stress-scenarios` 가
> 실어 보내던 `mode: "kr_pack"` 은 *패밀리*이지 인식론적 주장이 아니라서, 국내팩 7종이
> 가정이라는 사실이 화면 어디에도 없었다 — §5 가 막으려던 실패 그 자체다.
>
> 레지스트리는 세 출처를 **감싼다**(계수는 한 벌뿐). 두 축을 분리해 `family`(§5 의 12종,
> 분류)와 `model_type`(Enum, 인식론)을 각각 싣고, 레거시 `mode` 는 **한 글자도 바꾸지 않았다**
> — 프론트가 결과 렌더링을 그것으로 분기한다.
>
> **패밀리 커버리지 (실측).** 12종 중 8종은 기존 시나리오로 채워져 있었고, 3종은 비어
> 있어 새 팩을 만들었다(`vol_shock_liquidity_vacuum` · `credit_conditions_tightening` ·
> `corr_convergence_hedge_failure`), 성장·인플레는 `stagflation_regime` 으로 보강했다. 전부
> 기존 7팩터 노출 행렬을 쓴다 — 새 노출 로더를 만들면 시나리오마다 노출이 다른 뜻을 갖는다.
> 상관 수렴 팩은 `/stress-correlation` 을 **가리킨다**(그쪽이 공분산을 다시 구성해 실제로
> 계산한다). 팩이 없는 패밀리도 목록에 남는다 — 숨기면 "없는 것" 과 "채운 것" 이 구별되지 않는다.
>
> **`user-authored` 는 인라인 전용이다.** 요청에 팩 정의를 실어 보내면 실행되지만 저장되지
> 않으며, `model_type` 은 서버가 강제로 `hypothetical` 로 못박는다(클라이언트가 정할 수 있으면
> §5 가 무의미해진다). **저장·버전·삭제(CRUD)는 Phase 10 으로 재배치했다.**
>
> **정체성은 `pack_id@content_hash`** — 충격 정의(계수·가정·윈도우)의 sha256 12자. 라벨만
> 적힌 런은 계수가 바뀌는 순간 재현되지 않는다. 표현이 아니라 모델을 가리키므로 라벨을 고쳐도
> 해시는 그대로다. M8 은 계수가 데이터가 아니라 `_stock_shock()` **코드**에 있어 함수 소스를
> 해시에 포함한다 — 카탈로그만 해싱하면 충격 모델을 통째로 바꿔도 해시가 그대로다.
>
> **3자 비교와의 합성(§5 × Phase 7b).** `POST /allocation/scenario-three-way` 는 다리별 손실을
> `충격 × 노출` 로 만든다(나머지는 현금이라 충격을 받지 않는다). 타이밍 파생은 재구현하지 않고
> `rule_set_states` + `three_way` 를 그대로 부른다. 선형 근사라는 사실은 응답과 화면에 함께
> 나간다. **판정하지 못한 다리에는 손실을 적지 않는다** — 스냅샷이 없으면 `timing_macro` 는
> 노출 0 의 unavailable 인데, 거기에 0% 를 적으면 만들지 못한 비교가 셋 중 가장 안전해 보인다.
> NaN 도 같은 이유로 클램프하지 않는다(`max(0, min(1, nan))` 은 **1.0** 이라, 값을 얻지 못한
> 다리가 조용히 전액 노출로 채점된다).
>
> **한계.** 상관 수렴을 제외한 모든 팩은 계수 모델이며 실측이 아니다. `shortsell_regulation`
> 은 대차 데이터 피드가 없어 §5 의 "데이터가 신뢰할 수 있는 경우에만" 단서를 **가정 모델임을
> 출처에 명시하는 것**으로 답한다. `credit_conditions_tightening` 은 NFCI 를 읽는 타이밍 팩터
> `financial_conditions` 와 **다른 물건**이다(그쪽은 이 환경에 FRED 키가 없어 unavailable).

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

> **Phase 8 실행 기록 (재배치 1건).** 위 목록 중 **섹터 디스퍼전**은 Phase 8 에서 만들지
> 않고 **Phase 8b(데이터 소스 확장)로 재배치**했다 — 이 코드베이스에 섹터 지수 시계열이
> 없기 때문이다. `stock_master.get_stock_sector()` 는 종목→섹터 **이름**만 주고, 섹터별
> 가격 이력은 어디에도 없다. 섹터 ETF 바스켓으로 근사할 수는 있으나 그건 새 데이터 매핑을
> 들이는 일이라 8b 의 소관이다. 나머지 Phase-1 팩터 12종은 Phase 8 에서 구현했다.
> **→ Phase 8b 에서 `sector_dispersion` 으로 구현 완료** (섹터 ETF 바스켓, 프록시임을 명시).
>
> **KOSPI/KOSDAQ 상대강도와 원/달러 추세는 ETF 프록시로 구현했다.** KOSDAQ 은 수집
> 시리즈가 없고 KOSPI·원달러는 ECOS 라 vintage 가 없다(위 표의 `forward_only`).
> 지수가 아니라 상품을 재는 것이므로 추적오차·보수가 신호에 섞이며, 그 사실을 각 팩터
> 설명에 적었다 — 위 §6 의 '데이터가 뒷받침하지 않는 주장 금지' 규칙을 그대로 적용한 것이다.

---

## 7. API direction

New routers rather than growing the 70 KB `allocation_routes.py`; registered in
`app_factory.ROUTER_MODULES`:

- `src/api/regime_snapshot_routes.py` — create / get / list / compare snapshots
- `src/api/timing_routes.py` — catalogue, preview, evaluate, compare, historical simulation,
  rule-set CRUD
  > **✅ 분리 완료 (기술부채 정리).** 8개 라우트 + 스키마 4 + 헬퍼 5 를 옮겨
  > `allocation_routes.py` 는 1601 → 1133줄이 됐다. ★URL 은 한 글자도 바뀌지 않았다★ —
  > 프리픽스를 `/api/v1/allocation` 으로 유지했다(§7 의 문제 제기는 모듈 크기이지 URL 구조가
  > 아니다). `tests/test_route_parity.py` 가 이동 **전에** 통과하도록 먼저 작성됐고, 이동
  > 전후 {메서드, 경로} 집합이 289개로 동일함을 확인했다.
  > **✅ historical simulation 도착.** `POST /api/v1/allocation/timing/simulate` +
  > `src/engine/timing_simulation.py`. 리스크 레지스터가 이 엔드포인트에 배정한 forward_only
  > 차단이 여기서 실제로 걸린다 — `mode="backtest"`(기본값)는 **걷기 전에** 한 번 읽어
  > `assert_readings_backtest_eligible` 로 거부하고, 부적격 팩터를 **이름으로 지목해** 422 를
  > 낸다. 이 환경(`KIS_USE_MOCK=1`)에서는 가격 팩터가 전부 `forward_only` 라 기본 모드가 항상
  > 거부하므로, 탐색용 `mode="forward"` 를 함께 둔다 — 걷되 `backtest_eligible=false` 와
  > 부적격 팩터 목록을 실어 **백테스트로 오해될 수 없게** 한다.
  >
  > 절단이 **두 겹**이라는 점이 이 엔드포인트의 핵심이다. `timing_factor_history` 는
  > `requires_as_of` 팩터를 건너뛰므로 `etf_prices.as_of(m)` 하나로 충분했지만, 룰셋은 가격
  > 팩터와 매크로 팩터를 섞는다. 시점마다 시세 절단과 ALFRED 빈티지 고정(`as_of` 날짜)을
  > 함께 걸지 않으면 카탈로그의 나머지 절반에서 룩어헤드가 조용히 되살아난다.
  > 히스테리시스도 walk 를 타고 흐른다(시점마다 previous 를 비우면 히스테리시스가 **없는**
  > 룰셋을 시뮬레이션하는 셈이고, 전환 횟수는 규칙에 유리한 방향으로 틀린다).
  >
  > `set_id` 로도 돌릴 수 있다 — 저장된 룰셋은 버전이 박혀 있으므로 외부 파이프라인이 같은
  > 좌표로 같은 결과를 다시 얻는다(응답에 `rule_set_version` 을 함께 싣는다).

- `src/api/scenario_routes.py` — 팩 실행 · 시나리오×3자 비교
  > **✅ Phase 9b.** `POST /scenario-run`(등록 팩 또는 인라인 사용자 정의 팩) ·
  > `POST /scenario-three-way`. 프리픽스는 `/api/v1/allocation` 그대로이고, 다른 라우터를
  > import 하지 않도록 `_overlay_from_snapshot` 을 `macro_overlay.overlay_from_snapshot` 으로
  > 옮겼다. `POST /stress` · `POST /kr-scenario` 는 **손대지 않았다**(라이브 경로 무변경).
  > `GET /stress-scenarios` 만 제자리에서 확장 — `model_type`/`pack_id`/`content_hash` 추가,
  > 패밀리는 §5 의 12종, `mode` 어휘는 불변.
  > **✅ 팩 CRUD 도착 (Phase 10a).** `POST/GET /scenario-packs` ·
  > `GET /scenario-packs/{pack_id}/versions` · `DELETE /scenario-packs/{pack_id}` +
  > `src/data/scenario_packs_store.py`. `timing_rules.py` 의 idiom 을 그대로 따랐다 —
  > 방어적 raw-SQL · `_TABLE`+`_VTABLE` · 후행 `version` 열이 없으면 버전 기능만 끄기.
  > 갱신은 버전을 올리고 그 시점 내용을 이력에 남기며, 삭제는 이력까지 지운다(고아 이력이
  > 남으면 같은 id 가 재발급될 때 남의 과거를 물려받는다).
  >
  > ★저장돼도 `model_type` 은 사용자가 정하지 못한다★ 오히려 저장 쪽이 더 위험하다 —
  > 인라인 거짓말은 요청 한 건으로 끝나지만 **저장된 거짓말은 계속 남고**, 나중에 그 팩을 여는
  > 사람은 누가 그 라벨을 정했는지 모른다. 저장 테이블에 `model_type` 열 자체가 없고
  > `saved_pack()` 이 값을 하드코딩한다(두 겹).
  >
  > ★저장 팩은 등록 팩을 가리지 못한다★ 등록 id 를 먼저 찾는다 — 가릴 수 있으면 사용자가
  > `semi_selloff` 라는 이름으로 저장하는 것만으로 내장 시나리오를 조용히 바꿔치기할 수 있다.
  > 신원은 두 축이다: `version`(정수)은 개정 **순서**를, `content_hash` 는 충격 **정의**를
  > 말한다. 버전만 있으면 v3 과 v4 가 실제로 다른지 알 수 없고, 해시만 있으면 순서를 모른다.

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

  > **✅ Phase 10c.** 이 요구는 **위반되고 있었다** — `applyTiming()` 이 `setHoldingsReset()` 으로
  > 보유를 통째로 갈아치웠고, 그 동작에는 E2E 가 **하나도 없었다**. 이제 두 동작을 이름과
  > 클래스로 갈라 둔다:
  >
  > | 동작 | 성격 | 클래스 |
  > |---|---|---|
  > | 오버레이로 적용 | **비파괴** — 전략 비중 유지, 노출만 축소 | `.as-tm-overlay` |
  > | 권고 배분으로 교체 | 파괴적 — 위험-오프면 방어자산으로 갈아탄다 | `.as-tm-replace` |
  >
  > ★교체를 없애지 않은 이유★ 계획 초안은 "노출 1.0 이면 교체와 같은 결과" 라고 적었으나
  > **위험-오프에서 거짓**이다(`timing_routes.py` 가 IEF/SHY + BIL 로 **교체**한다 — 배율로는
  > 재현할 수 없다). §8 이 금지하는 것은 *조용한* 덮어쓰기이고, 명시적 교체는 그것이 아니다.
  >
  > Optimize 의 `TimingOverlayPanel` 이 before/after 비중 · 회전율 · 집중도(HHI·유효종목) ·
  > 제약 비가능 사유를 보인다. 베타·팩터 노출은 **계산한 척하지 않는다** — 균일 배율은
  > 위험자산 상대 비중을 바꾸지 않으므로 팩터 틸트(z-score)는 불변이고 베타는 노출에 비례해
  > 축소된다는 산술적 사실만 적는다. 오버레이는 **노출을 키울 수 없다**(일방향) —
  > `macro_overlay.combine()` 과 같은 규칙이며, 키울 수 있으면 리스크 관리가 레버리지가 된다.

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
> | three-pane layout · search · families · badges · config · lineage/limitations · keyboard · Escape · ARIA · responsive · KO/EN search · validation | **Phase 6** | `.tfm-*` classes preserved, so both existing specs pass with **zero selector edits** |
> | historical preview (value / threshold / **signal state** / # state changes) | **Phase 6b-2** ✅ | shipped. `timing_factor_history.py` re-evaluates the factor inside `etf_prices.as_of(m)` so each point sees only what was knowable then — **no new truncation machinery**, and Phase 7's state rules are reused rather than reimplemented. Sampling is monthly (`as_of` is month-granular), so a daily factor's flip count is **undersampled**; that and every other limit ship in the payload's `limitations[]` and render verbatim |
> | frequency-conflict warning | **Phase 6b** ✅ | shipped. `evaluation_frequency` on every catalogue entry, plus `frequency_ranks`/`rebalance_options` published **in the catalogue response** so the rank table stays single-sourced in Python instead of being duplicated in TypeScript |
> | **focus trap** | **기술부채 정리** ✅ | `shared/lib/useFocusTrap.ts` — 위 Phase 6 행에 '전달됨' 으로 적혀 있었으나 **실제로는 없었다**(role·aria-modal·Escape·autoFocus 만 있었고 Tab 을 막는 코드가 0줄). 표를 바로잡고 별도로 구현했다. Radix Dialog 는 +20 kB/route 로 ADR 001 의 15 kB 중단선을 넘어 제외 |
> | saved presets · draft-vs-active comparison | **Phase 6d** ✅ | shipped. Net-new — absent from all four modals, kept out so Phase 6's gate could stay "no capability lost". Presets live in one namespaced `localStorage` store shared by the three shell windows, and the UI **says they are browser-local and not reproduction coordinates** so they are not mistaken for the versioned rule sets of 7c. The comparison lists **only changed fields**, and distinguishes "nothing applied yet" from "no difference" — conflating those two would tell a user configuring their first factor that it matches the applied config |
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
