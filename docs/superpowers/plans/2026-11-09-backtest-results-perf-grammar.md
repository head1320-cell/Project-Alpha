# 백테스트 결과 화면에 성과 그림 문법 옮기기 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/backtest/runs/<id>/results` 가 캔버스와 같은 성과 그림 문법(그림 하나 + 증거 띠 + 읽는 줄 · 기간별 · 낙폭 사건 · 질문 띠 · HTML 기여도 막대)으로 그려지고, 이 화면에서 recharts 가 빠지며, 낙폭 단위 결함(비율을 %처럼)이 서버 `perf` 블록으로 고쳐진다.

**Architecture:** 서버 `run_full` 이 `perf {unit, drawdown_pct, periods, drawdowns}` 를 응답에 붙인다(같은 `quant_metrics` 함수 — 화면은 세지 않는다). 공용 부품 `widgets/portfolio-graph/perf/*` 의 클래스 접두어를 `pg-pf-*` → `pf-*` 로 바꾸고, 결과 화면은 `perfViewOfRun(run)` 으로 뷰를 옮겨 같은 부품을 쓴다. 역할 변수 `--pf-*` 는 `.rs` 에서 `--tx-*` 를 받는다.

**Tech Stack:** FastAPI 라우트(`src/api/backtest_run_routes.py`) · pytest · Next 16 / React 19 · 직접 그린 SVG 부품 · Playwright E2E · `make all` 게이트.

**스펙:** `docs/superpowers/specs/2026-11-09-backtest-results-perf-grammar-design.md`. 규칙: TDD(빨강 먼저) · 변이로 시험이 공허하지 않은지 확인 · 커밋은 이름 적은 파일만 · 커밋 메시지 끝 트레일러
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_016th9A3WJMup61EBW8Lkazs` · 모델 id 는 커밋 본문에 쓰지 않는다.

**환경(이 저장소의 관례):** 스크래치 `S=/tmp/claude-0/-home-user-Project-Alpha/0fe04482-a04d-5c82-835a-5814b8ac096a/scratchpad` · 파이썬 `$S/venv314f/bin/python` · Node `PATH=/opt/nvm/versions/node/v24.22.2/bin:$PATH` · 서버 `bash $S/stk/up.sh $S/venv314f/bin/python`(백엔드 :8000 · `next start` :3000 — 빌드가 먼저 있어야 한다) · E2E `cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test <spec> --trace off --reporter=line --output=test-results-<name>` · 게이트 `PATH=$S/venv314f/bin:/opt/nvm/versions/node/v24.22.2/bin:$PATH make all`. 프로세스는 포트로만 죽인다(`fuser 3000/tcp`).

---

## 파일 구조

| 파일 | 역할 |
|---|---|
| `src/api/backtest_run_routes.py` (수정) | `_perf_block(row)` + `run_full` 이 `perf` 를 붙인다 |
| `tests/test_backtest_run_perf_block.py` (새) | `perf` 계약 넷 |
| `frontend/src/widgets/portfolio-graph/perf/*.tsx`, `frontend/src/app/globals.css`, `frontend/e2e/canvas-perf-grammar.spec.ts`, `frontend/e2e/canvas-perf-sheet.spec.ts`, `tests/test_badge_axis_registry.py` (수정) | 접두어 `pg-pf-*` → `pf-*` |
| `frontend/src/widgets/portfolio-graph/perf/QuestionStrip.tsx` (수정) | `noGatesText` |
| `frontend/src/widgets/portfolio-graph/perf/PerfCurve.tsx` (수정) | 세로 눈금을 여백 끝에 · 원 단위 눈금은 `krAxisTick` |
| `frontend/src/widgets/backtester/perfOfRun.ts` (새) | `perfViewOfRun(run)` — 뷰 옮기기만 |
| `frontend/src/widgets/backtester/BacktestResults.tsx` (수정) | 그림 하나 · 기간별 · 낙폭 사건 · 질문 띠 · HTML 기여도 · recharts 제거 |
| `frontend/src/entities/backtest-run/api.ts` (수정) | `RunFull.perf` 타입 |
| `frontend/e2e/helpers.ts` (수정) | `completedRun()` 에 `perf` |
| `frontend/e2e/backtest-results.spec.ts`, `frontend/e2e/backtest.spec.ts` (수정) | 눈금 셋 · S1c 재겨냥 |
| `frontend/e2e/backtest-results-perf.spec.ts` (새) | (a)~(i) |
| `docs/HISTORY.md`, 스펙 §5.1 (수정) | 기록 |

---

### Task 1: 서버 — `run_full` 의 `perf` 블록 (커밋 ①)

**Files:**
- Modify: `src/api/backtest_run_routes.py` (`run_full` 은 656~671행 · import 는 28~30행 근처)
- Test: `tests/test_backtest_run_perf_block.py`

- [ ] **Step 1: 시험을 쓴다(빨강)**

```python
"""`run_full` 의 `perf` 블록 — 화면이 세지 않도록 서버가 낸다 (2026-11-09 · 결과 화면 성과 그림 문법 §3.2)

- 끝난 실행: `perf.drawdown_pct` = 저장된 비율 ×100(엔진은 비율로 저장하고 통계는 %) · `periods`·`drawdowns` = 같은 곡선의 `quant_metrics` 재계산.
- 낙폭 곡선이 없는 결과: `drawdown_pct: None`(0 배열이 아니다).
- 끝나지 않은 실행 / result 없음: `perf: None` — 화면이 "주지 않았어요" 라고 말한다.
- 기존 키는 그대로(짝 — `test_perf_label_wiring` 과 같은 규율).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

DATES = ["2023-01-02", "2023-01-03", "2023-02-01", "2023-02-02", "2024-01-02"]
EQ = [100.0, 103.0, 98.0, 108.0, 112.0]
DD = [0.0, 0.0, -0.0485, 0.0, 0.0]       # 엔진 저장 꼴 — 비율


def _row(result):
    return {"run_id": "R-1", "status": "completed", "strategy_name": "테스트", "is_mock_data": True,
            "is_pit_verified": None, "result": result}


def _done():
    return _row({"backtest": {"statistics": {"max_drawdown_pct": 4.85}, "equity_curve": EQ, "equity_dates": DATES,
                              "drawdown_curve": DD}})


def test_a_finished_run_ships_drawdown_in_percent_and_periods_from_the_same_curve(monkeypatch):
    from src.api import backtest_run_routes as rr
    from src.engine.quant_metrics import drawdown_episodes, period_returns
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: _done())
    perf = rr.run_full("R-1")["perf"]
    assert perf["unit"] == "krw"
    assert perf["drawdown_pct"] == pytest.approx([d * 100 for d in DD], abs=1e-3)
    assert abs(min(perf["drawdown_pct"])) == pytest.approx(4.85, abs=0.01)          # 통계와 같은 단위
    assert perf["periods"] == period_returns(DATES, EQ)
    assert perf["drawdowns"] == drawdown_episodes(DATES, EQ, top=3)
    assert len(perf["periods"]["yearly"]) == 2 and perf["periods"]["yearly"][0]["partial"] is True


def test_a_result_without_a_drawdown_curve_says_none_not_zeros(monkeypatch):
    from src.api import backtest_run_routes as rr
    row = _done()
    del row["result"]["backtest"]["drawdown_curve"]
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: row)
    perf = rr.run_full("R-1")["perf"]
    assert perf["drawdown_pct"] is None
    assert perf["periods"]["yearly"], "곡선은 있으니 기간별 수익은 있다"


@pytest.mark.parametrize("row", [
    {"run_id": "R-1", "status": "simulating", "strategy_name": "테스트", "is_mock_data": True, "result": None},
    {"run_id": "R-1", "status": "completed", "strategy_name": "테스트", "is_mock_data": True, "result": {"total_return_pct": 1.0}},
])
def test_an_unfinished_or_curveless_run_has_perf_none(monkeypatch, row):
    from src.api import backtest_run_routes as rr
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: dict(row))
    assert rr.run_full("R-1")["perf"] is None


def test_existing_keys_are_untouched(monkeypatch):
    from src.api import backtest_run_routes as rr
    row = _done()
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: dict(row))
    body = rr.run_full("R-1")
    for k, v in row.items():
        assert body[k] == v, f"{k} 가 바뀌었다"
    assert body["result"]["backtest"]["drawdown_curve"] == DD, "저장 결과는 그대로(비율) — 바꾼 것이 아니라 더한 것"
```

- [ ] **Step 2: 빨강 확인**

Run: `cd /home/user/Project-Alpha && PATH=$S/venv314f/bin:$PATH KIS_USE_MOCK=1 pytest tests/test_backtest_run_perf_block.py -q -p no:cacheprovider`
Expected: 5 failed — `KeyError: 'perf'`.

- [ ] **Step 3: 구현 — `_perf_block` + `run_full`**

`src/api/backtest_run_routes.py` 의 import 블록에 더한다(30행 `from src.domain.perf_kind import backtest_label` 아래):

```python
from src.engine.quant_metrics import drawdown_episodes, period_returns
```

`run_full` 바로 위에 함수를 둔다:

```python
def _perf_block(row: dict) -> dict | None:
    """★화면이 세지 않도록 서버가 낸다★ (2026-11-09 · 결과 화면 성과 그림 문법 §3.2)

    저장된 `drawdown_curve` 는 비율(−0.15)이고 통계 `max_drawdown_pct` 는 %(14.9)다 — 화면이 비율을 %처럼 그리던 결함을
    여기서 고친다(이름에 단위를 적은 `drawdown_pct`). 해마다·달마다 수익·낙폭 사건은 캔버스 불러오기 노드와 같은 함수
    (`quant_metrics`)라 같은 실행이면 같은 수다. 곡선이 없으면 None — 화면이 "주지 않았어요" 라고 말한다(0 으로 채우지 않는다).
    """
    result = row.get("result")
    if row.get("status") != "completed" or not isinstance(result, dict):
        return None
    bt = result.get("backtest") if isinstance(result.get("backtest"), dict) else result
    dates = bt.get("equity_dates") or []
    equity = bt.get("equity_curve") or []
    if not dates or not equity:
        return None
    dd = bt.get("drawdown_curve")
    return {
        "unit": "krw",
        "drawdown_pct": ([None if d is None else round(float(d) * 100.0, 4) for d in dd] if dd else None),
        "periods": period_returns(dates, equity),
        "drawdowns": drawdown_episodes(dates, equity, top=3),
    }
```

`run_full` 의 `r["execution_assumption"] = assumption_from_result(r.get("result"))` 다음 줄에:

```python
    # ★성과 그림의 수★ — 해마다·달마다 수익 · 낙폭 사건 · % 단위 낙폭(2026-11-09). 화면이 세지 않는다.
    r["perf"] = _perf_block(r)
```

- [ ] **Step 4: 초록 확인 + 이웃 시험**

Run: `PATH=$S/venv314f/bin:$PATH KIS_USE_MOCK=1 pytest tests/test_backtest_run_perf_block.py tests/test_perf_label_wiring.py tests/test_execution_assumption_wiring.py tests/test_allocation_graph_bl3w1.py -q -p no:cacheprovider`
Expected: 모두 통과. `ruff check src tests` 통과.

- [ ] **Step 5: 변이 — 비율을 그대로 싣는 변이가 죽는가**

`round(float(d) * 100.0, 4)` 를 `round(float(d), 4)` 로 바꿔 Step 4 를 돌린다 → 첫 시험 실패(`drawdown_pct` 가 통계와 다른 단위). 되돌린다.

- [ ] **Step 6: 커밋**

```bash
git add src/api/backtest_run_routes.py tests/test_backtest_run_perf_block.py
git commit -F - <<'EOF'
server: 백테스트 실행 응답에 perf 블록 — % 단위 낙폭 · 해마다·달마다 수익 · 낙폭 사건

- `run_full` 이 `perf {unit, drawdown_pct, periods, drawdowns}` 를 붙인다(`perf_label`·`execution_assumption` 과 같은 자리).
  저장 `drawdown_curve` 는 비율이고 통계는 % 라 화면이 비율을 %처럼 그리던 결함을 여기서 고친다. 캔버스 불러오기와 같은
  `quant_metrics` 함수라 같은 실행이면 같은 수. 곡선이 없으면 None(0 으로 채우지 않는다). 기존 키·저장 결과는 그대로.
- 시험 넷(빨강 먼저) · 비율 그대로 싣는 변이 죽음.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016th9A3WJMup61EBW8Lkazs
EOF
```

---

### Task 2: 접두어 `pg-pf-*` → `pf-*` (커밋 ②)

**Files:**
- Modify: `frontend/src/widgets/portfolio-graph/perf/*.tsx` · `frontend/src/app/globals.css` · `frontend/e2e/canvas-perf-grammar.spec.ts` · `frontend/e2e/canvas-perf-sheet.spec.ts` · `tests/test_badge_axis_registry.py`

규칙 하나로 기계적으로: 문자열 `pg-pf-` 를 `pf-` 로. `.pg-sheet--wide` 는 패턴에 안 걸려 그대로(캔버스 시트 전용). 패널의 '크게 보기' 단추 `pg-pf-open` 도 규칙대로 `pf-open` 이 된다(스펙 §3.3 의 "그대로" 는 `.pg-sheet--wide` 에만 해당 — HISTORY 에 적는다).

- [ ] **Step 1: 바꾸기 전 수를 센다(짝)**

Run: `cd /home/user/Project-Alpha && grep -rho "pg-pf-[a-z0-9-]*" frontend/src frontend/e2e tests | sort | uniq -c | sort -rn | head -5; grep -rl "pg-pf-" frontend/src frontend/e2e tests`
Expected: 파일 목록 = perf/ 아래 파일들 · `globals.css` · 스펙 둘 · `test_badge_axis_registry.py` (그 밖 없음 — 있으면 멈추고 본다).

- [ ] **Step 2: 바꾼다**

```bash
cd /home/user/Project-Alpha
sed -i 's/pg-pf-/pf-/g' frontend/src/widgets/portfolio-graph/perf/*.tsx frontend/src/widgets/portfolio-graph/perf/*.ts \
  frontend/src/app/globals.css frontend/e2e/canvas-perf-grammar.spec.ts frontend/e2e/canvas-perf-sheet.spec.ts tests/test_badge_axis_registry.py
grep -rn "pg-pf" frontend/src frontend/e2e tests | wc -l      # 0 이어야 한다
grep -n "pf-open\|pg-sheet--wide" frontend/src/widgets/portfolio-graph/perf/PerfPanel.tsx frontend/src/widgets/portfolio-graph/perf/PerfSheet.tsx frontend/src/app/globals.css | head
```

- [ ] **Step 3: 정적 검사 + 배지 레지스트리**

Run: `cd frontend && npx tsc --noEmit -p . && npx eslint src/widgets/portfolio-graph/perf e2e/canvas-perf-grammar.spec.ts e2e/canvas-perf-sheet.spec.ts && cd .. && PATH=$S/venv314f/bin:$PATH KIS_USE_MOCK=1 pytest tests/test_badge_axis_registry.py tests/test_perf_label_contract.py -q -p no:cacheprovider`
Expected: 모두 통과(레지스트리의 `pf-strip-practice` 가 `PerfCurve.tsx` 에 있다).

- [ ] **Step 4: 빌드 · 서버 · 캔버스 두 스펙**

```bash
cd /home/user/Project-Alpha/frontend && npx next build > $S/stk/build_t2.log 2>&1; echo exit=$?
bash $S/stk/up.sh $S/venv314f/bin/python
PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test e2e/canvas-perf-grammar.spec.ts e2e/canvas-perf-sheet.spec.ts --trace off --reporter=line --output=test-results-t2 2>&1 | tail -3
```
Expected: `20 passed`.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/widgets/portfolio-graph/perf frontend/src/app/globals.css frontend/e2e/canvas-perf-grammar.spec.ts frontend/e2e/canvas-perf-sheet.spec.ts tests/test_badge_axis_registry.py
git commit -F - <<'EOF'
frontend: 성과 그림 부품 클래스 접두어 pg-pf-* → pf-* (둘째 소비자 앞에서)

- 백테스트 결과 화면이 같은 부품을 쓰게 되어 캔버스 접두어가 거짓말이 된다. 규칙 하나로 기계적으로 바꿨다(부품·CSS·
  캔버스 스펙 둘·배지 축 레지스트리 — CSS 클래스명은 E2E 계약이라 같은 커밋). `.pg-sheet--wide` 는 캔버스 시트 전용이라 그대로.
- 캔버스 두 스펙 20 통과.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016th9A3WJMup61EBW8Lkazs
EOF
```

---

### Task 3: 결과 화면 — 같은 부품으로 (커밋 ③)

**Files:**
- Modify: `frontend/src/widgets/portfolio-graph/perf/QuestionStrip.tsx` · `frontend/src/widgets/portfolio-graph/perf/PerfCurve.tsx` · `frontend/src/entities/backtest-run/api.ts` · `frontend/src/widgets/backtester/BacktestResults.tsx` · `frontend/src/app/globals.css` · `frontend/e2e/helpers.ts` · `frontend/e2e/backtest-results.spec.ts` · `frontend/e2e/backtest.spec.ts`
- Create: `frontend/src/widgets/backtester/perfOfRun.ts` · `frontend/e2e/backtest-results-perf.spec.ts`

#### 3.1 E2E 를 먼저 쓴다(빨강)

- [ ] **Step 1: 픽스처에 `perf` 를 넣는다** — `frontend/e2e/helpers.ts` `completedRun()` 의 `const result = {` 앞(89행 `const stats` 위)에 둔다:

```ts
  // 서버 `run_full` 이 붙이는 성과 블록(2026-11-09) — 결과 화면은 이 수만 그린다(세지 않는다). 곡선 다섯 점과 손으로 맞춘 값.
  const perf = {
    unit: "krw",
    drawdown_pct: [0, 0, -1.9, 0, 0],
    periods: {
      yearly: [{ year: 2023, return_pct: 12.0, max_drawdown_pct: -1.9, n_days: 5, partial: true }],
      monthly: [
        { year: 2023, month: 1, return_pct: 0.0, n_days: 1, partial: true }, { year: 2023, month: 2, return_pct: 3.0, n_days: 1, partial: true },
        { year: 2023, month: 3, return_pct: -1.9, n_days: 1, partial: true }, { year: 2023, month: 4, return_pct: 6.9, n_days: 1, partial: true },
        { year: 2023, month: 5, return_pct: 3.7, n_days: 1, partial: true },
      ],
    },
    drawdowns: [{ peak_date: "2023-02", trough_date: "2023-03", recovery_date: "2023-04", depth_pct: -1.9, days_to_trough: 28, days_to_recover: 59 }],
  };
```

그리고 `return { lite: { ...base }, full: { ...base, input_snapshot, parameter_snapshot: {}, result } };` 를
`return { lite: { ...base }, full: { ...base, input_snapshot, parameter_snapshot: {}, result, perf } };` 로.

- [ ] **Step 2: 새 스펙 `frontend/e2e/backtest-results-perf.spec.ts`**

```ts
import { test, expect, type Page } from "./fixtures";
import { completedRun, contrastAudit, STUB_RUN_ID, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 백테스트 결과 화면 — 성과 그림 문법 (2026-11-09 · 설계 `docs/superpowers/specs/2026-11-09-backtest-results-perf-grammar-design.md`)
//  (a) 그림 하나 — 포트폴리오 선 · 벤치마크 회색 선 · 낙폭 물속 · 읽는 줄(마지막 날 · ArrowLeft)
//  (b) 낙폭 단위 = 서버 perf.drawdown_pct(통계와 같은 %) — 축 글자도 그 값(화면이 ×100 하지 않는다)
//  (c) 달마다 격자 칸 수 = perf.periods.monthly · 칸 글자 = 서버 값
//  (d) 낙폭 사건 행 수 = perf.drawdowns · 회복 null 은 "아직"
//  (e) 기여도 HTML 막대 — 행 수 = contribution 있는 종목 수 · 부호 · 등락색
//  (f) 짝: perf 가 없으면 낙폭·기간별·낙폭 사건은 "주지 않았어요" 이고 곡선은 그대로
//  (g) 질문 띠 — 관문 없는 화면의 문장
//  (h) recharts 요소 0 · 새 부품에 title= 0
//  (i) 다크 AA(.brun-results)
// ═══════════════════════════════════════════════════════════════════════════════

type Full = ReturnType<typeof completedRun>["full"] & Record<string, unknown>;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
type Perf = { drawdown_pct: number[] | null; periods: { monthly: { year: number; month: number; return_pct: number }[] };
  drawdowns: { recovery_date: string | null; days_to_recover: number | null; peak_date: string; depth_pct: number }[] };

async function openResults(page: Page, edit: (f: Full) => void = () => {}) {
  const f = clone(completedRun().full) as Full;
  edit(f);
  await page.route(new RegExp(`/api/v1/backtest/runs/${STUB_RUN_ID}$`), (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(f) }));
  await page.goto(`/backtest/runs/${STUB_RUN_ID}/results`, { waitUntil: "networkidle" });
  return f;
}
const curveCard = (p: Page) => p.locator(".brun-card").filter({ has: p.getByRole("heading", { name: /^자산곡선/ }) });
const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;

test("(a) 그림 하나 — 선·벤치마크·낙폭 물속 · 읽는 줄 마지막 날 · ArrowLeft · 띠 범례는 라벨이 말한 만큼만", async ({ page }) => {
  // 기본 픽스처에는 perf_label 이 없다(기존 '미상' 짝 시험이 그걸 쓴다) — 연습용 띠는 라벨을 넣어서 본다.
  const f = await openResults(page, (x) => { x.perf_label = { kind: "backtest", data_real: false, data_reason: "mock 시세" }; });
  const bt = (f.result as { backtest: { equity_dates: string[] } }).backtest;
  const fig = curveCard(page).locator(".pf-curve");
  await expect(fig).toBeVisible();
  await expect(fig.locator(".pf-line-port")).toHaveCount(1);
  await expect(fig.locator(".pf-line-bench")).toHaveCount(1);
  await expect(fig.locator(".pf-dd-area")).toHaveCount(1);
  const read = curveCard(page).locator(".pf-read");
  await expect(read).toContainText(bt.equity_dates[bt.equity_dates.length - 1]);
  await fig.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(read).toContainText(bt.equity_dates[bt.equity_dates.length - 2]);
  await expect(curveCard(page).locator(".pf-legend")).toContainText("벤치마크 KOSPI");
  // 리밸런싱 날짜를 모르는 엔진 — 띠는 리밸런싱을 말하지 않는다(모름 ≠ 0).
  await expect(curveCard(page).locator(".pf-strip-legend")).not.toContainText("리밸런싱");
  await expect(curveCard(page).locator(".pf-strip-legend")).toContainText("연습용 데이터");
  // 짝: 라벨이 없으면 "실제인지 몰라요" — 연습용이라고 단정하지 않는다.
  await page.unrouteAll();
  await openResults(page);
  await expect(curveCard(page).locator(".pf-strip-legend")).toContainText("데이터가 실제인지 몰라요");
  await expect(curveCard(page).locator(".pf-strip-legend")).not.toContainText("연습용 데이터");
});

test("(b) 낙폭 단위 = perf.drawdown_pct(통계와 같은 %) — 축 글자도 그 값 · 짝: 비율을 넣으면 작은 수로 보인다", async ({ page }) => {
  await openResults(page, (f) => { (f.perf as Perf).drawdown_pct = [0, -5, -14.2, -3, 0]; });
  await expect(curveCard(page).locator(".pf-dd .pf-ytick")).toHaveText("-14%");
  await openResults(page, (f) => { (f.perf as Perf).drawdown_pct = [0, -0.05, -0.142, -0.03, 0]; });
  await expect(curveCard(page).locator(".pf-dd .pf-ytick")).toHaveText("-0%");           // 화면은 받은 값을 그대로 — ×100 하지 않는다
});

test("(c) 달마다 격자 — 칸 수 = perf.periods.monthly · 칸 글자 = 서버 값 · 짝: 값을 바꾸면 칸이 바뀐다", async ({ page }) => {
  const f = await openResults(page);
  const monthly = (f.perf as Perf).periods.monthly;
  const cells = page.locator("td.pf-month[data-month]");
  await expect(cells).toHaveCount(monthly.length);
  await expect(page.locator('td.pf-month[data-month="2023-03"]')).toHaveText(signed(-1.9));
  await expect(page.locator(".rs-periods table.pf-table-years tbody tr")).toHaveCount(1);   // 표로 보기 안의 쌍둥이 표는 빼고(기간별 카드만)
  await openResults(page, (f2) => { (f2.perf as Perf).periods.monthly[2].return_pct = 7.77; });
  await expect(page.locator('td.pf-month[data-month="2023-03"]')).toHaveText("+7.8%");
});

test("(d) 큰 낙폭 사건 — 행 수 = perf.drawdowns · 날짜·깊이 · 짝: 회복 null 은 '아직'", async ({ page }) => {
  const f = await openResults(page);
  const eps = (f.perf as Perf).drawdowns;
  const rows = page.locator(".pf-dd-ep");
  await expect(rows).toHaveCount(eps.length);
  await expect(rows.first()).toContainText(eps[0].peak_date);
  await expect(rows.first()).toContainText(`${Math.abs(eps[0].depth_pct).toFixed(1)}%`);
  await expect(rows.first()).toHaveAttribute("data-recovered", "true");
  await openResults(page, (f2) => { const e = (f2.perf as Perf).drawdowns[0]; e.recovery_date = null; e.days_to_recover = null; });
  await expect(page.locator(".pf-dd-ep").first()).toHaveAttribute("data-recovered", "false");
  await expect(page.locator(".pf-dd-ep").first()).toContainText("아직 고점을 되찾지 못했어요");
});

test("(e) 기여도 — HTML 막대 · 행 수 = contribution 있는 종목 · 부호와 등락색 · recharts 아님", async ({ page }) => {
  const f = await openResults(page);
  const rows = (f.result as { backtest: { symbol_results: { contribution_pct?: number }[] } }).backtest.symbol_results.filter((r) => r.contribution_pct != null);
  const tr = page.locator("table.brun-attr-table tbody tr");
  await expect(tr).toHaveCount(rows.length);
  await expect(tr.first()).toHaveAttribute("data-sign", "up");
  await expect(tr.first().locator(".brun-attr-bar")).toBeVisible();
  await expect(tr.last()).toHaveAttribute("data-sign", "down");
  await expect(page.locator(".recharts-wrapper")).toHaveCount(0);
});

test("(f) 짝: perf 가 없으면 낙폭·기간별·낙폭 사건은 '주지 않았어요' 이고 곡선은 그대로(화면이 세지 않는다)", async ({ page }) => {
  await openResults(page, (f) => { f.perf = null; });
  await expect(curveCard(page).locator(".pf-line-port")).toHaveCount(1);
  await expect(curveCard(page).locator(".pf-dd-area")).toHaveCount(0);
  await expect(curveCard(page).locator(".pf-legend")).toContainText("낙폭 곡선 없음");
  await expect(page.locator("td.pf-month[data-month]")).toHaveCount(0);
  await expect(page.locator(".pf-dd-ep")).toHaveCount(0);
  await expect(page.locator(".terminal-main")).toContainText("주지 않았어요");
});

test("(g) 질문 띠 — 답하는 것(전달) · 답하지 않는 것은 이 화면이 재지 않는다고 말한다(관문 칩 0)", async ({ page }) => {
  await openResults(page);
  const q = page.locator(".pf-q");
  await expect(q).toContainText("답하는 것");
  await expect(q).toContainText("답하지 않는 것");
  await expect(q).toContainText("재지 않아요");
  await expect(q.locator(".pf-q-gate")).toHaveCount(0);
});

test("(h) recharts 요소 0 · 새 부품에 title= 0", async ({ page }) => {
  await openResults(page);
  await expect(page.locator(".recharts-wrapper, .recharts-surface, .recharts-tooltip-wrapper")).toHaveCount(0);
  await expect(page.locator(".terminal-main [title]:not(.perf-label)")).toHaveCount(0);
});

for (const t of ["light", "dark"] as const) {
  test(`(i) 대비 — ${t}: 결과 화면 AA 미달 0`, async ({ page }) => {
    await page.addInitScript((v) => { try { localStorage.setItem("alpha_theme", v); } catch { /* */ } }, t);
    await openResults(page);
    await page.locator("details.pf-table summary").click();
    await page.waitForTimeout(400);
    const r = await page.evaluate<AuditResult>(contrastAudit(".terminal-main"));
    expect(r.checked).toBeGreaterThan(60);
    expect(r.low, `${t}: ${JSON.stringify(r.low.slice(0, 8))}`).toEqual([]);
    if (t === "dark") expect(r.bright).toEqual([]);
  });
}
```

- [ ] **Step 3: 기존 계약을 새 부품으로 재겨냥(동작은 같게)** — `frontend/e2e/backtest-results.spec.ts` 158~176행의 `equityTicks` 를 이렇게 바꾼다:

```ts
type Tick = { text: string; left: number; svgLeft: number; y: number };
async function equityTicks(page: Page): Promise<Tick[]> {
  const card = page.locator(".brun-card").filter({ has: page.getByRole("heading", { name: /^자산곡선/ }) });
  await expect(card.locator(".pf-curve .pf-ytick").first()).toBeVisible();
  return card.evaluate((el) => {
    const svg = el.querySelector("svg.pf-curve")!.getBoundingClientRect();
    // 자산 축의 눈금만 — 낙폭 축(`.pf-dd` 안)의 "-n%" 는 다른 축이다.
    return [...el.querySelectorAll(".pf-ytick")].filter((t) => !t.closest(".pf-dd")).map((t) => {
      const r = t.getBoundingClientRect();
      return { text: (t.textContent ?? "").trim(), left: r.left, svgLeft: svg.left, y: r.top + r.height / 2 };
    });
  });
}
```

`checkAxis` 의 첫 줄 `toBeGreaterThanOrEqual(3)` 를 `toBeGreaterThanOrEqual(2)` 로 바꾸고 주석을 단다:
`// 부품은 위·아래 + (기준선이 둘과 12px 이상 떨어질 때) 기준선 — 짧은 픽스처 곡선은 둘이 된다.`

`frontend/e2e/backtest.spec.ts` S1c(357~365행)를 이렇게:

```ts
  const line = page.locator(".pf-line-port").first();
  await expect(line).toBeVisible();
  const stroke = await line.evaluate((e) => getComputedStyle(e).stroke);
  // 해석 실패 시 브라우저는 none / rgb(0,0,0) 을 준다.
  expect(stroke, "차트 선 색이 해석되지 않았다").not.toBe("none");
  expect(stroke, "차트 선이 검정으로 떨어졌다 — var() 가 죽었다").not.toBe("rgb(0, 0, 0)");
  // 성과 그림 문법(2026-11-09): 포트폴리오 선은 잉크(--pf-ink ← --tx-ink · 라이트 #191f28) — 행동색 파랑은 데이터에 쓰지 않는다.
  const ink = await page.evaluate(() => { const s = document.createElement("span"); s.style.color = "var(--tx-ink)"; document.body.appendChild(s);
    const c = getComputedStyle(s).color; s.remove(); return c; });
  expect(stroke).toBe(ink);
```

- [ ] **Step 4: 빨강 확인(옛 빌드 그대로 서버가 떠 있다)**

Run: `cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test e2e/backtest-results-perf.spec.ts e2e/backtest-results.spec.ts e2e/backtest.spec.ts -g "\(a\)|\(b\)|\(c\)|\(d\)|\(e\)|\(f\)|\(g\)|\(h\)|\(i\)|세로축|S1c" --trace off --reporter=line --output=test-results-t3red 2>&1 | grep -E "passed|failed"`
Expected: 새 스펙 10 전부 실패(`.pf-curve` 없음) · 눈금 셋·S1c 실패.

#### 3.2 부품 둘을 손본다

- [ ] **Step 5: `QuestionStrip` 에 `noGatesText`** — `frontend/src/widgets/portfolio-graph/perf/QuestionStrip.tsx`:

시그니처를 `export function QuestionStrip({ view, gates, noGatesText }: { view: PerfView; gates: Gate[] | null; noGatesText?: string })` 로,
마지막 줄 `{gates === null && <p className="pg-note">관문 판정이 없어요 — …</p>}` 를:

```tsx
      {gates === null && (
        <p className="pg-note pf-q-nogates">{noGatesText ?? "관문 판정이 없어요 — 계산 전이거나, 결과가 낡았거나, 부분 계산이라 관문을 매기지 않았어요."}</p>
      )}
```
(`pf-q-row` 등 클래스는 Task 2 에서 이미 `pf-` 다.)

- [ ] **Step 6: `PerfCurve` 세로 눈금 — 여백 끝 + 원 단위는 `krAxisTick`** — `frontend/src/widgets/portfolio-graph/perf/PerfCurve.tsx`:

import 에 `import { krAxisTick } from "@/shared/lib/krFormat";` 를 더한다. `geo` 안의

```ts
    const yTopV = hi - (hi - lo) * 0.06, yBotV = lo + (hi - lo) * 0.06;
```
를
```ts
    // 위·아래 눈금은 여백의 끝(= 곡선 최댓값 + 6% · 최솟값 − 6%) — 맨 위 눈금이 곡선 최댓값보다 작게 적히지 않게.
    const yTopV = hi, yBotV = lo;
    // 원 단위 눈금은 한 축 한 단위(만·억)로 짧게("1.05억" · "5,636만" · "112") — 끝값·읽는 줄은 그대로 "1.2억원".
    const tickFmt = view.unit === "krw" ? krAxisTick(Math.max(Math.abs(hi), Math.abs(lo))) : (v: number) => fmtValue("x", v);
```
로 바꾸고, `tickTexts` 의 `fmtValue(view.unit, yTopV)`·`fmtValue(view.unit, yBotV)`·`fmtValue(view.unit, baseline)` 을 `tickFmt(yTopV)`·`tickFmt(yBotV)`·`tickFmt(baseline)` 으로. `return { … }` 에 `tickFmt` 를 더한다. 렌더 쪽 `const tickLabel = (v: number) => fmtValue(view.unit, v);` 를 `const tickLabel = geo.tickFmt;` 로.

- [ ] **Step 7: 캔버스 두 스펙이 그대로 통과하는지(눈금 글자는 계약이 아니다)**

Run: `npx tsc --noEmit -p . && npx next build > $S/stk/build_t3a.log 2>&1 && bash $S/stk/up.sh $S/venv314f/bin/python && PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test e2e/canvas-perf-grammar.spec.ts e2e/canvas-perf-sheet.spec.ts --trace off --reporter=line --output=test-results-t3a 2>&1 | tail -2`
Expected: `20 passed`.

#### 3.3 결과 화면

- [ ] **Step 8: `RunFull.perf` 타입** — `frontend/src/entities/backtest-run/api.ts` 48~54행 `export interface RunFull extends RunStatusLite { … }` 안, `perf_label?: PerfLabelValue | null;` 줄 바로 다음에:

```ts
  /** 서버가 붙이는 성과 그림의 수(2026-11-09 · `run_full`) — % 단위 낙폭 · 해마다·달마다 수익 · 낙폭 사건. 없으면 null(화면은 세지 않는다). */
  perf?: {
    unit: "krw";
    drawdown_pct: (number | null)[] | null;
    periods: { yearly: { year: number; return_pct: number; max_drawdown_pct: number; n_days: number; partial: boolean }[];
               monthly: { year: number; month: number; return_pct: number; n_days: number; partial: boolean }[] };
    drawdowns: { peak_date: string; trough_date: string; recovery_date: string | null; depth_pct: number; days_to_trough: number; days_to_recover: number | null }[];
  } | null;
```

- [ ] **Step 9: 뷰 옮기기 `frontend/src/widgets/backtester/perfOfRun.ts`**

```ts
/**
 * 백테스트 실행 응답 → `PerfView` (2026-11-09 · 결과 화면 성과 그림 문법 §3.3) — ★옮기기만★: 곡선(원)·벤치마크·서버 `perf` 의 % 낙폭·
 * 기간별·낙폭 사건·연습용 여부. 리밸런싱 날짜·배움 구간·기준일은 이 엔진에 없다(모름 ≠ 0 — 띠는 말하지 않는다).
 */
import type { RunFull } from "@/entities/backtest-run/api";
import type { PerfView } from "@/widgets/portfolio-graph/perf/perfView";

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pts = (v: unknown): (number | null)[] | null => (Array.isArray(v) ? v.map((x) => num(x)) : null);

export function perfViewOfRun(run: RunFull): PerfView {
  const bt = run.result?.backtest;
  const dates = (bt?.equity_dates ?? []).map(String);
  const equity = pts(bt?.equity_curve) ?? [];
  const benchRaw = pts(bt?.benchmark?.curve);
  const perf = run.perf ?? null;
  const pl = run.perf_label ?? null;
  return {
    unit: "krw", dates, equity,
    bench: benchRaw && benchRaw.length === dates.length ? benchRaw : null,
    benchLabel: bt?.benchmark?.label ?? null,
    drawdown: perf ? pts(perf.drawdown_pct) : null,
    rebalances: [], question: "이 조건식이 과거에 어떤 성과를 냈나",
    learnFrom: null, asOf: null,
    practice: pl && typeof pl.data_real === "boolean" ? pl.data_real === false : null,
    perfLabel: pl,
    periods: perf ? perf.periods : null,
    drawdowns: perf ? perf.drawdowns : null,
    figures: [], summary: {}, metrics: null,
    cost: { bps: null, impact: null, nRebalances: null, turnoverAvg: null },
    explain: null,
  };
}
```
`RunFull.perf_label` 은 `PerfLabelValue | null | undefined` 라 `?? null` 이면 `PerfView.perfLabel` 과 맞는다.

- [ ] **Step 10: `BacktestResults.tsx` — import 바꾸기**

지운다: `import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";` ·
`import { useChartAnimation } from "@/shared/ui/chartStyle";` · `import { krAxisTick } from "@/shared/lib/krFormat";` · `MonthlyReturn` 타입 import.
더한다:

```tsx
import { DrawdownEpisodes } from "@/widgets/portfolio-graph/perf/DrawdownEpisodes";
import { MonthGrid } from "@/widgets/portfolio-graph/perf/MonthGrid";
import { PerfCurve } from "@/widgets/portfolio-graph/perf/PerfCurve";
import { PerfTableView, YearTable } from "@/widgets/portfolio-graph/perf/PerfTableView";
import { QuestionStrip } from "@/widgets/portfolio-graph/perf/QuestionStrip";
import { perfViewOfRun } from "./perfOfRun";
```
`useMemo` 는 `AttributionBars` 에서 계속 쓴다(React import 그대로).

- [ ] **Step 11: `ResultsBody` 안 — 데이터 줄 바꾸기**

지운다: `const anim = useChartAnimation();` · `const equity = useMemo(…)` 블록 · `const equityTick = useMemo(…)` 블록 · `const monthly = useMemo(…)` 블록.
더한다(`const roundTrips` 위에):
```tsx
  const view = perfViewOfRun(run);
  const NO_GATES = "이 화면은 예측 스킬·경제적 가치를 재지 않아요. 캔버스에서 이 실행을 불러오면 관문(표본 밖 · 경제적 가치)이 매겨져요.";
```

- [ ] **Step 12: 답 문장 아래 질문 띠** — `</section>`(답 한 문장 section 닫는 줄) 바로 다음에:

```tsx
      <QuestionStrip view={view} gates={null} noGatesText={NO_GATES} />
```

- [ ] **Step 13: 자산곡선·낙폭 두 카드 → 한 카드** — `{equity.length > 1 && ( <Card className="brun-card"> … 자산곡선 … )}` 와 `{bt.drawdown_curve?.some(…) && ( … 낙폭 … )}` 두 블록을 통째로 이것으로 바꾼다:

```tsx
      {/* 곡선 먼저 — 숫자 33개보다 모양이 먼저 읽힌다. 그림 하나 = 자산 곡선 + 낙폭(물속) + 증거 띠 + 읽는 줄(성과 그림 문법 · 2026-11-09). */}
      {view.dates.length > 1 && (
        <Card className="brun-card rs-fig">
          <CardHeader className="rs-card-h">
            <CardTitle as="h2" className="brun-card-t">자산곡선과 낙폭{bt.benchmark ? <span className="brun-note">벤치마크 {bt.benchmark.label}와 함께</span> : null}</CardTitle>
          </CardHeader>
          <CardContent className="rs-card-b">
            <PerfCurve view={view} height={300} />
            {!run.perf && <p className="brun-note">낙폭 곡선·기간별 수익·낙폭 사건은 서버가 이 실행에 주지 않았어요 — 화면이 대신 세지 않아요.</p>}
            {bt.benchmark && (
              <p className="brun-benchrow">
                벤치마크 {num(bt.benchmark.total_return_pct) != null ? signedPct(bt.benchmark.total_return_pct as number) : "몰라요"}
                {num(bt.benchmark.excess_return_pct) != null && <> · 차이 <b style={{ color: col(bt.benchmark.excess_return_pct) }}>{signedPct(bt.benchmark.excess_return_pct as number).replace("%", "%p")}</b></>}
                {num(bt.benchmark.beta) != null && <> · 베타 {(bt.benchmark.beta as number).toFixed(2)}</>}
                {num(bt.benchmark.alpha_pct) != null && <> · 알파 {signedPct(bt.benchmark.alpha_pct as number)}</>}
              </p>
            )}
            <PerfTableView view={view} />
          </CardContent>
        </Card>
      )}
```
(`brun-benchrow` 의 글은 이전 그대로 — 바꾸지 않는다.)

- [ ] **Step 14: 월별 카드 → 기간별 + 낙폭 사건** — `{monthly.length > 0 && ( … 월별 수익률 … )}` 블록을 이것으로:

```tsx
      <Card className="brun-card">
        <CardHeader className="rs-card-h">
          <CardTitle as="h2" className="brun-card-t">기간별<span className="brun-note">해마다 · 달마다 (연환산하지 않아요)</span></CardTitle>
        </CardHeader>
        <CardContent className="rs-card-b rs-periods">
          <YearTable view={view} />
          <MonthGrid view={view} />
        </CardContent>
      </Card>

      <Card className="brun-card">
        <CardHeader className="rs-card-h">
          <CardTitle as="h2" className="brun-card-t">큰 낙폭 사건<span className="brun-note">고점에서 바닥까지, 되찾기까지</span></CardTitle>
        </CardHeader>
        <CardContent className="rs-card-b">
          <DrawdownEpisodes view={view} />
        </CardContent>
      </Card>
```
`MonthGrid`·`DrawdownEpisodes` 는 `periods`·`drawdowns` 가 null 이면 "서버가 … 주지 않았어요" 를 스스로 말한다(부품 그대로).

- [ ] **Step 15: 기여도 — `AttributionChart` 를 HTML 막대로** — 함수 전체를 이것으로 바꾼다(이름은 `AttributionBars` · 호출부 `<AttributionChart rows=…>` 도 `<AttributionBars rows=…>` 로):

```tsx
/** 기여도 — HTML 막대(종목 · 막대 · 부호 숫자). 상위 8 + 하위 8. 색은 등락 두 팔, 글자는 잉크(성과 그림 문법 · 2026-11-09). */
function AttributionBars({ rows }: { rows: SymbolPerf[] }) {
  const data = useMemo(() => {
    const withC = rows.filter((r) => r.contribution_pct != null);
    const sorted = [...withC].sort((a, b) => (b.contribution_pct as number) - (a.contribution_pct as number));
    const top = sorted.slice(0, 8);
    const bot = sorted.slice(-8).filter((r) => !top.includes(r));
    return [...top, ...bot].map((r) => ({ name: r.corp_name || r.symbol, contribution: r.contribution_pct as number }));
  }, [rows]);
  if (data.length === 0) return null;
  const max = Math.max(1e-9, ...data.map((d) => Math.abs(d.contribution)));
  return (
    <Card className="brun-card">
      <CardHeader className="rs-card-h">
        <CardTitle as="h2" className="brun-card-t">기여도<span className="brun-note">수익을 가장 많이 더하고 뺀 종목</span></CardTitle>
      </CardHeader>
      <CardContent className="rs-card-b">
        <table className="brun-attr-table">
          <tbody>
            {data.map((d) => (
              <tr key={d.name} data-sign={d.contribution >= 0 ? "up" : "down"}>
                <td className="brun-attr-name">{d.name}</td>
                <td className="brun-attr-track"><span className="brun-attr-bar" style={{ width: `${(Math.abs(d.contribution) / max) * 100}%` }} /></td>
                <td className="brun-attr-val num" style={{ color: col(d.contribution) }}>{signedPct(d.contribution, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 16: CSS** — `frontend/src/app/globals.css` 의 BU4 `.rs` 절(7163행 부근) 끝에:

```css
/* 성과 그림 문법(2026-11-09) — 결과 화면은 부품의 역할 변수에 --tx-* 를 넣는다(새 토큰 0). 캔버스는 .pg-theme 이 --pg-* 를 넣는다. */
.rs {
  --pf-ink: var(--tx-ink); --pf-body: var(--tx-sub); --pf-mute: var(--tx-mute); --pf-line: var(--tx-line); --pf-soft: var(--tx-soft);
  --pf-surface: var(--tx-surface); --pf-up: var(--tx-up); --pf-up-ink: var(--tx-up-ink); --pf-down: var(--tx-down); --pf-down-ink: var(--tx-down-ink);
  --pf-assume: var(--tx-warn); --pf-unknown: var(--tx-mute);
}
.rs .pf-q { margin-bottom: 14px; }
.rs-periods { display: flex; flex-direction: column; gap: 14px; }
.rs .pf-curve:focus-visible { outline: 2px solid var(--tx-blue); outline-offset: 2px; border-radius: 6px; }
/* 기여도 — HTML 막대 */
.brun-attr-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.brun-attr-table td { padding: 5px 0; vertical-align: middle; }
.brun-attr-name { width: 30%; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--tx-ink); padding-right: 10px; }
.brun-attr-track { position: relative; }
.brun-attr-bar { display: block; height: 10px; border-radius: 3px; background: var(--tx-up); }
tr[data-sign="down"] .brun-attr-bar { background: var(--tx-down); }
.brun-attr-val { width: 72px; text-align: right; font-weight: 600; padding-left: 10px; }
```
`pf-*` 부품 규칙은 전역이라 그대로 쓰인다. 캔버스 전용으로 `.pg-theme` 에만 있던 값은 `--pf-*` 뿐이므로 위 매핑으로 다 받는다.

- [ ] **Step 17: 정적 검사 · 빌드 · 초록**

```bash
cd /home/user/Project-Alpha/frontend && npx tsc --noEmit -p . && npx eslint src/widgets/backtester src/widgets/portfolio-graph/perf e2e/backtest-results-perf.spec.ts e2e/backtest-results.spec.ts e2e/backtest.spec.ts e2e/helpers.ts
npx next build > $S/stk/build_t3.log 2>&1; echo exit=$?; bash $S/stk/up.sh $S/venv314f/bin/python
PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test e2e/backtest-results-perf.spec.ts e2e/backtest-results.spec.ts e2e/backtest.spec.ts e2e/canvas-perf-grammar.spec.ts e2e/canvas-perf-sheet.spec.ts --trace off --reporter=line --output=test-results-t3 2>&1 | grep -E "^\s+[0-9]+\) |passed|failed|Error:" | head -20
```
Expected: 전부 통과(새 10 · 결과 스펙 · backtest 스펙 · 캔버스 20). 실패하면 그 시험의 기대가 맞는지 먼저 보고(계약을 바꾸는 것이 아니라면) 코드를 고친다.
`grep -n "recharts" src/widgets/backtester/BacktestResults.tsx` → 0.

- [ ] **Step 18: 변이 셋(한 빌드)**

1. `perfOfRun.ts`: `periods: perf ? perf.periods : null` 을 화면이 세는 척하는 변이 `periods: perf ? perf.periods : { yearly: [], monthly: [{ year: 2023, month: 1, return_pct: 1, n_days: 1, partial: true }] }` 로 → (f) 실패.
2. `perfOfRun.ts`: `drawdown: perf ? pts(perf.drawdown_pct) : null` 을 `drawdown: perf ? pts(perf.drawdown_pct)?.map((v) => (v === null ? null : v * 100)) ?? null : null` 로 → (b) 실패.
3. `AttributionBars`: `data-sign={d.contribution >= 0 ? "up" : "down"}` 의 up/down 을 뒤집음 → (e) 실패.
빌드·서버·`npx playwright test e2e/backtest-results-perf.spec.ts -g "\(b\)|\(e\)|\(f\)"` → 3 failed 확인 → 셋을 되돌리고 다시 빌드·서버·같은 셋 통과.

- [ ] **Step 19: 눈으로** — 라이트·다크·390 스크린샷. `$S/stk/pfshot5.js`:

```js
// 결과 화면 — 라이트·다크·390 스크린샷(겹침·잘림 확인용). 사용: node pfshot5.js OUT_DIR   (서버 :3000 · 실제 실행 하나를 만들어 연다)
const { chromium } = require("playwright");
const API = "http://localhost:8000/api/v1";
(async () => {
  const out = process.argv[2]; const b = await chromium.launch();
  const p0 = await b.newPage();
  const created = await (await p0.request.post(`${API}/backtest/runs`, { data: { strategy_name: "shot", config: { universe: "kospi50",
    filter_ast: { logic: "AND", conditions: [], groups: [] }, strategy_name: "GoldenCross", start_date: "2023-01-01", end_date: "2023-12-31", max_tickers: 2, max_positions: 2 } } })).json();
  for (let i = 0; i < 90; i++) { const st = (await (await p0.request.get(`${API}/backtest/runs/${created.run_id}/status`)).json()).status; if (st === "completed") break; await p0.waitForTimeout(2000); }
  await p0.close();
  for (const [name, w, dark] of [["light", 1280, false], ["dark", 1280, true], ["390", 390, false]]) {
    const p = await b.newPage({ viewport: { width: w, height: 3600 } });
    if (dark) await p.addInitScript(() => { try { localStorage.setItem("alpha_theme", "dark"); } catch {} });
    await p.goto(`http://localhost:3000/backtest/runs/${created.run_id}/results`, { waitUntil: "networkidle" });
    await p.locator(".pf-curve").waitFor({ timeout: 30000 });
    await p.locator("details.pf-table summary").click(); await p.waitForTimeout(300);
    await p.locator(".terminal-main").screenshot({ path: `${out}/pf5_results_${name}.png` });
    await p.close();
  }
  await b.close();
})();
```
Run: `cd frontend && node $S/stk/pfshot5.js $S/stk` → 세 장을 Read 로 보고 겹침·잘림·축 띠 포함 높이를 확인한다. 고친 것은 스펙 §5.1 에 적는다.

- [ ] **Step 20: 커밋**

```bash
git add frontend/src/widgets/portfolio-graph/perf/QuestionStrip.tsx frontend/src/widgets/portfolio-graph/perf/PerfCurve.tsx frontend/src/entities/backtest-run/api.ts frontend/src/widgets/backtester/perfOfRun.ts frontend/src/widgets/backtester/BacktestResults.tsx frontend/src/app/globals.css frontend/e2e/helpers.ts frontend/e2e/backtest-results.spec.ts frontend/e2e/backtest.spec.ts frontend/e2e/backtest-results-perf.spec.ts
git commit -F - <<'EOF'
frontend: 백테스트 결과 화면이 캔버스와 같은 성과 그림 문법으로 — recharts 가 이 화면에서 빠진다

- 답 문장 아래 질문 띠(관문 없는 화면의 문장) · 자산곡선+낙폭 두 카드 → 그림 하나(물속 낙폭 · 증거 띠 · 읽는 줄 · 표 쌍둥이) ·
  월별 막대 → 기간별(해마다 표 · 달마다 격자) + 큰 낙폭 사건 표 · 기여도 → HTML 막대. 핵심 지표·산출 불가·종목별·거래·한계는 그대로.
- 수는 서버 `perf` 만(`perfViewOfRun` — 옮기기만) · perf 가 없으면 "주지 않았어요". 역할 변수 `--pf-*` 는 `.rs` 에서 `--tx-*`.
- 부품: `QuestionStrip.noGatesText` · `PerfCurve` 세로 눈금을 여백 끝에(맨 위 ≥ 최댓값) · 원 단위 눈금은 `krAxisTick`.
- E2E: 새 스펙 10(옛 빌드에서 빨강) · 눈금 셋·S1c 를 새 부품으로 재겨냥(동작 같음) · 변이 셋 죽음.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016th9A3WJMup61EBW8Lkazs
EOF
```

---

### Task 4: 측정 · 전체 E2E · 게이트 · 기록 (커밋 ④)

**Files:**
- Modify: `docs/HISTORY.md` · `docs/superpowers/specs/2026-11-09-backtest-results-perf-grammar-design.md`(§5.1 추가)

- [ ] **Step 1: 첫 화면 JS 전/후** — 전 = Task 3 커밋 직전 HEAD(= Task 2 커밋)를 워크트리로 빌드해 :3002 에 띄운다(node_modules 는 하드링크 복사 — 심볼릭 링크는 Turbopack 이 거부한다):

```bash
S=/tmp/claude-0/-home-user-Project-Alpha/0fe04482-a04d-5c82-835a-5814b8ac096a/scratchpad; export PATH=/opt/nvm/versions/node/v24.22.2/bin:$PATH
cd /home/user/Project-Alpha && git worktree add --detach $S/wt_before HEAD~1 && cp -al frontend/node_modules $S/wt_before/frontend/node_modules
( cd $S/wt_before/frontend && npx next build > $S/stk/wt_before.log 2>&1 && BACKEND_URL=http://localhost:8000 setsid nohup npx next start -p 3002 > $S/stk/web_before.log 2>&1 < /dev/null & )
timeout 300 bash -c 'until [ "$(curl -s -o /dev/null -w %{http_code} http://localhost:3002/)" = 200 ]; do sleep 2; done'
sed 's#const ROUTES = .*#const ROUTES = ["/backtest/runs/x/results"];#' $S/stk/firstload.js > $S/stk/firstload_results.js
cd frontend && node $S/stk/firstload_results.js http://localhost:3002 before $S/stk/firstload_results.jsonl && node $S/stk/firstload_results.js http://localhost:3000 after $S/stk/firstload_results.jsonl
for pid in $(fuser 3002/tcp 2>/dev/null); do kill $pid; done; cd .. && git worktree remove --force $S/wt_before && git worktree prune
```
Expected: `before` 는 L5 기록과 비슷(≈343 kB 압축) · `after` 가 작다(recharts 조각이 이 화면에서 빠짐). 숫자는 재서 적는다 — 예상을 적지 않는다.

- [ ] **Step 2: 엔진 월별과 `perf.periods.monthly` 대조(실제 실행 하나)**

```bash
RID=$(curl -s -X POST http://localhost:8000/api/v1/backtest/runs -H 'content-type: application/json' -d '{"strategy_name":"perf 대조","config":{"universe":"kospi50","filter_ast":{"logic":"AND","conditions":[],"groups":[]},"strategy_name":"GoldenCross","start_date":"2023-01-01","end_date":"2023-12-31","max_tickers":2,"max_positions":2}}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])'); sleep 8
curl -s http://localhost:8000/api/v1/backtest/runs/$RID | python3 -c '
import sys,json; j=json.load(sys.stdin); bt=j["result"]["backtest"]; p=j["perf"]
eng={(m["year"],m["month"]):m["return_pct"] for m in bt["monthly_returns"]}
ours={(m["year"],m["month"]):m["return_pct"] for m in p["periods"]["monthly"]}
diff=[(k,eng.get(k),ours.get(k)) for k in sorted(set(eng)|set(ours)) if eng.get(k) is None or ours.get(k) is None or abs(eng[k]-ours[k])>0.05]
print("months engine/ours:",len(eng),len(ours),"differences >0.05%p:",diff[:6])
print("dd unit:", min(p["drawdown_pct"]), bt["statistics"]["max_drawdown_pct"])'
```
결과(같다/다르다 + 어디서)를 HISTORY 에 적는다. 다르면 고치지 않는다(엔진 함수는 값 골든) — 사실만 적는다.

- [ ] **Step 3: 전체 E2E(백그라운드) → 끝나면 `make all`**

```bash
cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test --trace off --reporter=line --output=test-results-full > $S/stk/e2e_full_br.log 2>&1; echo exit=$? >> $S/stk/e2e_full_br.log
# 끝난 뒤: 서버를 내리고(빌드가 .next 를 덮는다)
cd /home/user/Project-Alpha && for port in 3000 8000; do for pid in $(fuser $port/tcp 2>/dev/null); do kill $pid; done; done
PATH=$S/venv314f/bin:/opt/nvm/versions/node/v24.22.2/bin:$PATH make all > $S/stk/make_all_br.log 2>&1; echo exit=$?; grep -E "passed|failed|error" $S/stk/make_all_br.log | tail -3
```
Expected: E2E 실패 0 또는 이전부터의 간헐(realism ST3c 다크 — HISTORY 2026-11-09 기록) 뿐 · `make all` 통과. 새로 실패한 것이 있으면 고치고 다시.

- [ ] **Step 4: HISTORY 항목 + 스펙 §5.1** — `docs/HISTORY.md` 끝에(무엇 · 왜 · 시험 · 측정 · 하지 않음):

```markdown
## 백테스트 결과 화면에 성과 그림 문법 — recharts 가 이 화면에서 빠짐 (2026-11-09)

- 설계: `docs/superpowers/specs/2026-11-09-backtest-results-perf-grammar-design.md`(사용자 결정: 범위 C · 접근 1 · 승인).
- 서버: `run_full` 에 `perf {unit, drawdown_pct, periods, drawdowns}` — 저장 `drawdown_curve` 는 비율이고 통계는 % 라 화면이 비율을 %처럼
  그리던 결함(픽스처가 %로 적혀 있어 시험이 못 봤다)을 여기서 고쳤다. 캔버스 불러오기와 같은 `quant_metrics` 함수. 곡선 없으면 None.
  시험 넷(`tests/test_backtest_run_perf_block.py` · 빨강 먼저 · 비율 그대로 싣는 변이 죽음).
- 접두어: 부품 클래스 `pg-pf-*` → `pf-*`(부품·CSS·캔버스 스펙 둘·배지 레지스트리 — 한 커밋). `pg-pf-open` 도 규칙대로 `pf-open`(스펙 §3.3 의
  "그대로" 는 `.pg-sheet--wide` 만). 캔버스 두 스펙 20 통과.
- 화면: 질문 띠(관문 없는 화면의 문장 — `QuestionStrip.noGatesText`) · 그림 하나(`PerfCurve` 300 · 원 단위 눈금은 `krAxisTick` · 맨 위 눈금 ≥
  최댓값이 되도록 눈금을 여백 끝에 — 캔버스에도 같이 적용됨) · 기간별(해마다 표 · 달마다 격자) · 큰 낙폭 사건 표 · 기여도 HTML 막대 ·
  `perfViewOfRun`(옮기기만 · 리밸런싱·배움·기준일은 이 엔진에 없어 띠는 말하지 않는다). 핵심 지표·산출 불가·종목별·거래·한계는 그대로.
  역할 변수 `--pf-*` ← `.rs` 의 `--tx-*`(`--pf-assume`=`--tx-warn` · `--pf-unknown`=`--tx-mute`) — 새 토큰 0.
- E2E: `backtest-results-perf.spec.ts` 10(옛 빌드에서 빨강) · 기존 눈금 셋·S1c 는 새 부품으로 재겨냥(잘림 없음·오름차순·만/억·토큰 해석 — 동작 같음) ·
  변이 셋(화면이 세는 척 · 화면이 ×100 · 막대 색 뒤집음) 죽음 · 전체 E2E <N>/<M>(실패: <목록 또는 0>) · `make all` 통과.
- 측정: 첫 화면 JS `/backtest/runs/x/results` <before> → <after> kB(압축 · 3회 중앙값). 엔진 `monthly_returns` 대 `perf.periods.monthly`: <같다/다르다 — 어디>.
- 하지 않음: 비교 화면 recharts · 핵심 지표 타일·산출 불가 사유 · 엔진 월별 함수 · 답 문장을 서버 explain 으로 · 부품 폴더를 shared 로 올리기.
```
`<…>` 자리는 잰 값으로 채운다(자리를 남기지 않는다). 스펙 끝에 `## 5.1 실물 대 와이어프레임` 을 더해 Step 19 에서 바꾼 것을 적는다.

- [ ] **Step 5: 커밋 · 푸시**

```bash
git add docs/HISTORY.md docs/superpowers/specs/2026-11-09-backtest-results-perf-grammar-design.md
git commit -F - <<'EOF'
docs: 백테스트 결과 화면 성과 그림 문법 — 기록 · 측정 · 실물 대 와이어프레임

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016th9A3WJMup61EBW8Lkazs
EOF
for d in 0 2 4 8 16; do sleep $d; git push -u origin claude/backtest-modern-ui-refactor-akxvbc && break; done
for port in 3000 8000; do for pid in $(fuser $port/tcp 2>/dev/null); do kill $pid; done; done
rm -rf frontend/test-results-t2 frontend/test-results-t3 frontend/test-results-t3a frontend/test-results-t3red frontend/test-results-full
```
