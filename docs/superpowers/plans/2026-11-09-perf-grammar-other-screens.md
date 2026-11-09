# 성과 그림 문법 ③ — 다른 화면 넷 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 두 곡선을 겹쳐 보는 화면 셋(비교 화면·비교 노드·현실성)과 곡선 하나 화면 둘(/macro 모달·스트레스 과거 모드)을 같은 성과 그림 문법으로 — 수는 서버가 내고 화면은 서식만.

**Architecture:** 순수 모듈 `src/engine/perf_compare.py`(정렬·차이·해마다 차이·지표 차이)를 순수 엔드포인트 `POST /api/v1/perf/compare`·캔버스 비교 노드·현실성 탭이 함께 쓴다. 프론트는 `shared/ui/perf` 에 `PerfCompare`(두 곡선 + 차이 띠)와 `CompareYearTable` 을 더하고 `PerfCurve` 를 작게 넓힌다(벤치마크 낙폭 · base100 · 띠 범례 글). 설계: `docs/superpowers/specs/2026-11-09-perf-grammar-other-screens-design.md`.

**Tech Stack:** FastAPI · pytest(`$S/venv314f`) · Next 16 · React 19 · Playwright(`PLAYWRIGHT_BASE_URL=http://localhost:3000` · 서버는 `bash $S/stk/up.sh $S/venv314f/bin/python`) · `S=/tmp/claude-0/-home-user-Project-Alpha/0fe04482-a04d-5c82-835a-5814b8ac096a/scratchpad`.

---

### Task 1: 서버 — `perf_compare` 엔진 · 라우트 · 노드 · 스트레스 · 매크로 (커밋 ②)

**Files:**
- Create: `src/engine/perf_compare.py` · `src/api/perf_compare_routes.py` · `tests/test_perf_compare.py`
- Modify: `src/app_factory.py`(모듈 목록에 `"src.api.perf_compare_routes"`) · `src/api/allocation_graph_nodes_backtest.py`(`_STAT_KO` → `NODE_METRICS` import · `_compare` 에 `compare`) · `src/api/allocation_stress_routes.py::historical_replay` · `src/engine/strategy_profiles.py::_curve_summary`

- [ ] **Step 1: 빨강** — `tests/test_perf_compare.py`

```python
"""perf_compare — 두 곡선을 맞추고 차이를 내는 순수 함수 (2026-11-09 · 성과 그림 문법 ③ §3.1)."""
from __future__ import annotations
import os
import pytest
os.environ.setdefault("KIS_USE_MOCK", "1")

D = ["2023-01-02", "2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06"]
A = [100.0, 102.0, 101.0, 105.0, 110.0]
B = [100.0, 101.0, 103.0, 104.0, 108.0]

def test_same_dates_align_by_date_rebased_to_base_and_diff_in_pp():
    from src.engine.perf_compare import align_curves
    c = align_curves(D, A, D, B, base=1.0)
    assert c["alignment"] == "date" and c["x"] == D and c["n"] == 5 and c["common"] == 5
    assert c["missing_a"] == 0 and c["missing_b"] == 0 and c["note"] is None
    assert c["a"][0] == 1.0 and c["a"][-1] == pytest.approx(1.10)
    assert c["diff_pp"][-1] == pytest.approx(-2.0)            # (1.08 − 1.10) × 100

def test_union_keeps_one_sided_days_as_none_not_zero():
    from src.engine.perf_compare import align_curves
    c = align_curves(D, A, D[2:], B[2:], base=100.0)
    assert c["x"] == D and c["missing_b"] == 2 and c["missing_a"] == 0
    assert c["b"][:2] == [None, None] and c["diff_pp"][:2] == [None, None]
    assert c["b"][2] == 100.0                                   # B 는 제 첫 유효값을 base 로
    assert "없는 날" in (c["note"] or "")

def test_little_overlap_falls_back_to_index_with_reason_and_pair_half_overlap_stays_by_date():
    from src.engine.perf_compare import align_curves
    far = ["2020-03-0%d" % i for i in range(2, 7)]
    c = align_curves(D, A, far, B)
    assert c["alignment"] == "index" and c["x"][0] == "1일째" and "시작부터" in c["note"]
    half = D[2:] + ["2023-01-09", "2023-01-10"]                 # 공통 3 = 짧은 쪽 5 의 반 이상
    assert align_curves(D, A, half, B)["alignment"] == "date"

def test_yearly_diff_is_a_union_of_years_with_partial_flags_and_none_where_missing():
    from src.engine.perf_compare import yearly_diff
    pa = {"yearly": [{"year": 2022, "return_pct": 5.0, "partial": True}, {"year": 2023, "return_pct": 10.0, "partial": False}]}
    pb = {"yearly": [{"year": 2023, "return_pct": 12.5, "partial": False}, {"year": 2024, "return_pct": 1.0, "partial": True}]}
    rows = yearly_diff(pa, pb)
    assert [r["year"] for r in rows] == [2022, 2023, 2024]
    assert rows[0]["b_return_pct"] is None and rows[0]["diff_pp"] is None and rows[0]["a_partial"] is True
    assert rows[1]["diff_pp"] == pytest.approx(2.5)

def test_metric_rows_keep_none_when_a_side_is_missing():
    from src.engine.perf_compare import PAGE_METRICS, NODE_METRICS, metric_rows
    rows = metric_rows({"total_return_pct": 10.0}, {"total_return_pct": 22.6, "sharpe_ratio": 1.1}, PAGE_METRICS)
    by = {r["key"]: r for r in rows}
    assert by["total_return_pct"]["diff"] == pytest.approx(12.6)
    assert by["sharpe_ratio"]["a"] is None and by["sharpe_ratio"]["diff"] is None
    assert len(NODE_METRICS) == 7 and len(PAGE_METRICS) == 10

def test_the_pure_endpoint_is_registered_and_answers_without_a_store(monkeypatch):
    from fastapi.testclient import TestClient
    from src.app_factory import create_app
    from tests.route_walk import flat_routes
    app = create_app()
    assert any(r.path == "/api/v1/perf/compare" and "POST" in r.methods for r in flat_routes(app))
    body = {"a": {"label": "A", "dates": D, "equity": A, "stats": {"total_return_pct": 10.0}},
            "b": {"label": "B", "dates": D, "equity": B, "stats": {"total_return_pct": 8.0}}, "base": 100, "metrics": "page"}
    res = TestClient(app).post("/api/v1/perf/compare", json=body)
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["curves"]["base"] == 100.0 and j["rows"][0]["diff"] == pytest.approx(-2.0) and j["yearly"] is None
    bad = {**body, "b": {"label": "B", "dates": D, "equity": B[:-1]}}
    assert TestClient(app).post("/api/v1/perf/compare", json=bad).status_code == 422

def test_the_compare_node_ships_curves_and_says_why_when_one_side_has_none():
    from src.api.allocation_graph_nodes_backtest import _compare
    run = lambda rid, eq: {"run_id": rid, "run": {"strategy_name": rid, "result": {"backtest": {"statistics": {"total_return_pct": 1.0},
                            "equity_curve": eq, "equity_dates": D[:len(eq)] if eq else []}}, "input_snapshot": {}, "is_mock_data": True}}
    out = _compare({"a": run("A", A), "b": run("B", B)}, None)
    assert out.view["compare"]["curves"]["alignment"] == "date" and len(out.view["rows"]) == 7
    assert out.view["compare"]["drawdowns"]["a"] is not None
    out2 = _compare({"a": run("A", A), "b": run("B", [])}, None)
    assert out2.view["compare"] is None and "곡선" in out2.view["compare_reason"]

def test_stress_replay_ships_equity_benchmark_and_episodes(monkeypatch):
    # historical_replay 에 df 를 심어 네 키가 같은 길이로 나오는지 — 기존 키는 그대로.
    ...

def test_macro_curve_summary_ships_drawdown_pct_and_a_dates_note():
    from src.engine.strategy_profiles import _curve_summary
    out = _curve_summary([100.0, 110.0, 99.0, 120.0], [0.1, -0.1, 0.21], 3)
    assert len(out["drawdown_pct"]) == 4 and max(out["drawdown_pct"]) == 0.0 and min(out["drawdown_pct"]) == pytest.approx(-10.0)
    assert "어림" in out["dates_note"]
```
Run: `$S/venv314f/bin/python -m pytest tests/test_perf_compare.py -q` → ImportError/AssertionError 로 전부 빨강.

- [ ] **Step 2: 엔진** — `src/engine/perf_compare.py`(순수 · numpy 없이 · `quant_metrics` 재사용)

```python
"""두 곡선을 맞추고 차이를 낸다 — 비교 화면 · 캔버스 비교 노드 · 현실성 탭이 같은 함수를 쓴다 (2026-11-09 · 성과 그림 문법 ③ §3.1).

★화면이 빼지 않는다★ 정렬(날짜 합집합 / 순번)의 의미가 한 곳에 있어야 세 화면이 같은 말을 한다. 한쪽만 있는 날은 None(0 아님).
"""
from __future__ import annotations
from typing import Any

NODE_METRICS = (("total_return_pct", "총수익", "%"), ("cagr", "연평균(CAGR)", "%"), ("sharpe_ratio", "샤프", ""),
                ("max_drawdown_pct", "최대 낙폭", "%"), ("win_rate", "승률", "%"), ("num_trades", "거래 수", "회"),
                ("profit_factor", "손익비", ""))
PAGE_METRICS = (("total_return_pct", "총수익률", "%"), ("cagr", "연평균 수익률", "%"), ("max_drawdown_pct", "최대낙폭", "%"),
                ("volatility_pct", "변동성(연)", "%"), ("sharpe_ratio", "샤프 지수", ""), ("sortino_ratio", "소르티노 지수", ""),
                ("calmar_ratio", "칼마 비율", ""), ("win_rate", "이긴 거래 비율", "%"), ("profit_factor", "손익비", ""),
                ("num_trades", "거래 수", "회"))
INDEX_NOTE = "두 실행의 기간이 달라 날짜가 아니라 시작부터 {n}일째로 맞췄어요 — 같은 날끼리가 아니에요."

def _num(v): return float(v) if isinstance(v, (int, float)) and v == v else None
def _rebase(vals, base):
    first = next((v for v in vals if v is not None and v > 0), None)
    return [None if v is None or first is None else v / first * base for v in vals]

def align_curves(dates_a, eq_a, dates_b, eq_b, *, base: float = 1.0) -> dict:
    da = [str(d)[:10] for d in dates_a]; db = [str(d)[:10] for d in dates_b]
    ma = dict(zip(da, (_num(v) for v in eq_a))); mb = dict(zip(db, (_num(v) for v in eq_b)))
    common = len(set(da) & set(db))
    shortest = min(len(da), len(db))
    if common >= 2 and common >= 0.5 * shortest:
        x = sorted(set(da) | set(db))
        a = [ma.get(d) for d in x]; b = [mb.get(d) for d in x]
        missing_a = sum(1 for d in x if d not in ma); missing_b = sum(1 for d in x if d not in mb)
        note = None if not (missing_a or missing_b) else "한쪽에만 있는 날이 있어요 — 그날은 그쪽 값이 비어요."
        alignment = "date"
    else:
        n = shortest
        x = [f"{i + 1}일째" for i in range(n)]
        a = [_num(v) for v in list(eq_a)[:n]]; b = [_num(v) for v in list(eq_b)[:n]]
        missing_a = missing_b = 0; note = INDEX_NOTE.format(n=n); alignment = "index"
    ra, rb = _rebase(a, base), _rebase(b, base)
    diff = [None if (p is None or q is None) else (q - p) / base * 100.0 for p, q in zip(ra, rb)]
    return {"alignment": alignment, "x": x, "n": len(x), "common": common, "missing_a": missing_a, "missing_b": missing_b,
            "base": float(base), "a": ra, "b": rb, "diff_pp": diff, "note": note}

def yearly_diff(periods_a, periods_b) -> list[dict]:
    ya = {r["year"]: r for r in (periods_a or {}).get("yearly") or []}
    yb = {r["year"]: r for r in (periods_b or {}).get("yearly") or []}
    out = []
    for y in sorted(set(ya) | set(yb)):
        a = _num((ya.get(y) or {}).get("return_pct")); b = _num((yb.get(y) or {}).get("return_pct"))
        out.append({"year": y, "a_return_pct": a, "b_return_pct": b, "diff_pp": None if a is None or b is None else b - a,
                    "a_partial": bool((ya.get(y) or {}).get("partial", False)), "b_partial": bool((yb.get(y) or {}).get("partial", False))})
    return out

def metric_rows(stats_a, stats_b, spec) -> list[dict]:
    rows = []
    for key, label, unit in spec:
        a = _num((stats_a or {}).get(key)); b = _num((stats_b or {}).get(key))
        rows.append({"key": key, "label": label, "unit": unit, "a": a, "b": b, "diff": None if a is None or b is None else round(b - a, 4)})
    return rows
```

- [ ] **Step 3: 라우트** — `src/api/perf_compare_routes.py`(`APIRouter(prefix="/api/v1/perf", tags=["perf"])` · Pydantic 본문 `Side{label, dates:list[str], equity:list[float|None], stats?:dict, periods?:dict}` · `CompareBody{a, b, base: Literal[1,100]=1, metrics: Literal["page","node"]|None}` · 길이 불일치·2점 미만 → `HTTPException(422, "…사유")` · 응답 `{curves, yearly, rows}`), `src/app_factory.py` 모듈 목록에 추가. 노드 `_compare`: `from src.engine.perf_compare import NODE_METRICS, align_curves, yearly_diff` · `_STAT_KO = NODE_METRICS`(기존 이름은 `_explain_load` 가 쓴다) · 두 실행의 `equity_dates/equity_curve` 가 있으면 `compare` 블록, 없으면 `None` + `compare_reason="한쪽 실행에 자산 곡선이 없어 겹쳐 그리지 못했어요."`. 스트레스·매크로 키 추가.
Run: 위 pytest 초록 · `pytest tests/test_backtest_run_perf_block.py tests/test_routes_not_shadowed.py tests/test_distribution_blocked.py tests/test_allocation_graph_explain.py tests/test_metrics_single_source.py -q` · 금지어 시험.

- [ ] **Step 4: 변이 셋** — 합집합 → 교집합(`set(da) & set(db)`) · `_rebase` 가 base 무시 · diff 부호 뒤집기 → 각 시험이 죽는지 확인 뒤 되돌림.
- [ ] **Step 5: 커밋 ②** — `git add src/engine/perf_compare.py src/api/perf_compare_routes.py src/app_factory.py src/api/allocation_graph_nodes_backtest.py src/api/allocation_stress_routes.py src/engine/strategy_profiles.py tests/test_perf_compare.py`.

### Task 2: 부품 + 비교 화면 + 비교 노드 (커밋 ③)

**Files:**
- Create: `frontend/src/shared/ui/perf/perfGeo.ts` · `PerfCompare.tsx` · `CompareYearTable.tsx` · `frontend/src/entities/perf/api.ts` · `frontend/e2e/perf-compare.spec.ts`
- Modify: `frontend/src/shared/ui/perf/{PerfCurve.tsx, perfView.ts}` · `frontend/src/widgets/backtester/BacktestCompare.tsx` · `frontend/src/widgets/portfolio-graph/BacktestResults.tsx` · `frontend/src/app/globals.css` · `frontend/e2e/portfolio-graph.spec.ts`(비교 블록 한 줄)

- [ ] **Step 1: `perfGeo.ts` 추출** — `PerfCurve.tsx` 의 `textW·day·days·pickIndexes·argExt·linePath·areaPath` 와 상수를 옮기고 import 로 바꾼다. tsc · 캔버스 성과 셋 E2E 30 통과(동작 불변).
- [ ] **Step 2: 타입·서식** — `perfView.ts`: `PerfUnit` 에 `"base100"` · `fmtValue`(base100 → `fmtNum(v, 1)`) · `PerfView.benchDrawdown?`·`note?` · `PerfCompareView`·`YearDiffRow` · `compareViewOf(resp: CompareResponse, meta: { unit; labelA; labelB; practice; perfLabelA; perfLabelB; question; drawdownsA; drawdownsB })` · `perfViewOfStress(r, prov)`.
- [ ] **Step 3: 빨강** — `e2e/perf-compare.spec.ts`(비교 화면 · 실행 둘 스텁은 `backtest.spec.ts` 비교 시험의 픽스처 방식 그대로 · `/perf/compare` 는 스텁하지 않는다): (a) `.pf-cmp .pf-line-a`·`.pf-line-b`·`.pf-diff-line` 1 · `.pf-read-date` = 마지막 날짜 · ArrowLeft → 직전 날짜 · `.pf-read-diff` 가 "%p" (b) `.pf-strip-legend-align` 0 · B 의 날짜·곡선 끝 2점을 빼면 `.pf-cmp-table tbody tr` = 5 · "현실 쪽에 없는 날"류 아닌 "한쪽에만 있는 날" 글 · B 날짜를 2020 으로 바꾸면 "시작부터" (c) `.pf-year-diff tbody tr` = 해 합집합 수 (d) `.brun-cmp tr` 총수익률 차이 = "+12.6%p"(서버) · B `total_return_pct` 삭제 → "총수익률은 비교할 수 없어요" (e) `.recharts-wrapper` 0 · `.brun-results [title]:not(.perf-label)` 0 (f) `contrastAudit` 라이트·다크 (g) 390 `cardsOverflow` 0. 옛 빌드에서 전부 빨강 확인.
- [ ] **Step 4: 부품** — `PerfCompare.tsx`(설계 §3.2 와이어프레임 그대로 · `perfGeo` 공용 · 높이 기본 260 · 위 패널 70% · 차이 패널 나머지) · `CompareYearTable.tsx` · `PerfCurve.tsx` 확장(`.pf-dd-bench` · `.pf-strip-legend-note` · base100) · CSS.
- [ ] **Step 5: 화면** — `BacktestCompare.tsx`: recharts·`normalize`·`useChartAnimation` 삭제 · `useQuery(["perf","compare", a.run_id, b.run_id])` → `perfApi.compare(...)` · 답·지표 표는 `rows` · 카드 안 `PerfCompare` + `CompareYearTable` + `DrawdownEpisodes` ×2. 노드 `BacktestCompareResult`: `v.compare` → `compareViewOf` → `PerfCompare` + 표. `portfolio-graph.spec.ts` 비교 블록에 `await expect(page.locator(".pg-side .pf-cmp")).toBeVisible();` 한 줄.
Run: tsc · eslint · `npm run build` · `up.sh` · `npx playwright test e2e/perf-compare.spec.ts e2e/backtest.spec.ts e2e/backtest-results.spec.ts e2e/perf-label.spec.ts e2e/portfolio-graph.spec.ts e2e/canvas-perf-grammar.spec.ts e2e/canvas-perf-sheet.spec.ts e2e/backtest-results-perf.spec.ts --trace off --reporter=line`.
- [ ] **Step 6: 변이 둘(한 빌드)** — `align_curves` 를 index 로 강제(서버) → (b) 실패 · `PerfCompare` 가 차이 띠를 안 그림 → (a) 실패. 되돌리고 초록.
- [ ] **Step 7: 커밋 ③**.

### Task 3: 현실성 탭 (커밋 ④)

**Files:** Modify `frontend/src/widgets/live-trading/RealismTab.tsx` · `frontend/src/entities/realism/model.ts`(`joinByDate` 삭제 · `RealismRecord` 에 `cumulative_return?`·`drawdown_pct?` 선언) · `frontend/e2e/realism.spec.ts`

- [ ] **Step 1: 빨강** — `realism.spec.ts` 에 (r1) `.rl-chart .pf-cmp` 보임 · `.pf-read-diff` 가 "%p" · 라디오 "현실" → `.pf-cmp--focus-b` (r2) 짝: 현실 앞 3일 빼기 → `data-days` 합집합(기존) + `.pf-strip-legend-align` 0.
- [ ] **Step 2: 교체** — `GapChart`: `perfApi.compare({a:{label:"이상", dates, equity}, b:{label:"현실", …}, base:1})` 를 `useEffect`/`useQuery` 로 · 맞추는 중 `rl-aligning` · 실패 `role=alert` + 다시 시도 · `PerfCompare` · `.rl-missing` 은 `missing_b/missing_a`. recharts import 삭제. `rl-legend` 삭제(부품 범례).
Run: `npx playwright test e2e/realism.spec.ts e2e/admin.spec.ts e2e/live-safety.spec.ts --trace off --reporter=line`.
- [ ] **Step 3: 변이** — `data-days` 를 `ideal.daily_records.length` 로 → (p3) 실패 → 되돌림. **Step 4: 커밋 ④**.

### Task 4: /macro 모달 + 스트레스 노드 (커밋 ⑤)

**Files:** Modify `frontend/src/widgets/macro/StrategyModal.tsx` · `frontend/src/entities/macro/analysisApi.ts`(타입에 `drawdown_pct?`·`dates_note?`) · `frontend/src/widgets/portfolio-graph/CheckResults.tsx` · `frontend/e2e/macro-cards.spec.ts` · `frontend/e2e/portfolio-graph.spec.ts`

- [ ] **Step 1: 빨강** — `macro-cards.spec.ts`: 전략 창 열어 `.sm-modal .pf-curve`·`.pf-dd-area` 1 · `.pf-strip-legend-note` 에 "어림" · `.sm-modal .recharts-wrapper` 0('그림 수 보존 — 전략 창' 이 recharts 를 세면 세는 법을 `svg.pf-curve, .recharts-wrapper` 로 넓히고 사유). `portfolio-graph.spec.ts` 스트레스 과거 모드: `.pg-side .pf-curve`·`.pf-dd-bench`·`.pf-episodes` 보임.
- [ ] **Step 2: 교체** — `StrategyModal`: `PerfCurve({unit:"base100", dates: curve.t, equity: curve.v, drawdown: perf.drawdown_pct, note: perf.dates_note, practice, perfLabel, …})` · `.sm-note` 삭제 · recharts import 삭제. `CheckResults`: `Drawdown` → `PerfCurve(perfViewOfStress(r, prov))` + `DrawdownEpisodes` · recharts import 삭제.
Run: `npx playwright test e2e/macro-cards.spec.ts e2e/radix-dialogs.spec.ts e2e/portfolio-graph.spec.ts e2e/canvas-robust.spec.ts --trace off --reporter=line`.
- [ ] **Step 3: 변이 둘** — 벤치 낙폭 안 그림 → 스트레스 실패 · 매크로 낙폭 ×100 → 축 글자 실패. **Step 4: 커밋 ⑤**.

### Task 5: 측정 · 전체 E2E · 게이트 · 기록 (커밋 ⑥)

- [ ] **Step 1: 첫 화면 JS 전/후** — 커밋 ② 워크트리(`git worktree add --detach $S/wt_before <커밋②>` · `cp -al node_modules`) :3002 대 지금 :3000 · `firstload.js` 경로 `["/backtest/runs/x/compare", "/admin/live-trading", "/macro"]` · 모달 조각은 모달을 열며 받은 script 크기.
- [ ] **Step 2: 수 대조** — 끝난 실행 둘로 서버 `rows[].diff` 와 `vb − va` · 현실성 `curves.n` 과 옛 합집합(픽스처).
- [ ] **Step 3: 스크린샷** — `$S/stk/pfshot6.js`: 비교 화면·현실성 탭·모달·캔버스 비교 노드·스트레스 노드 × 라이트/다크/390 → 고칠 것 고치고 스펙 §5.1.
- [ ] **Step 4: 전체 E2E(백그라운드) → 서버 내리고 `make all`** — 실패는 HISTORY 의 간헐 기록과 대조.
- [ ] **Step 5: HISTORY + 커밋 ⑥ + 푸시(재시도 2/4/8/16) + 정리**(포트 3000/8000 · `frontend/test-results-*` 명시 삭제 · 워크트리 prune).
