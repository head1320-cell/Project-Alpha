# 백테스터 4수정 + 매크로 국면 재구축 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 백테스트 기간종료 청산(거래통계 0 해소)·평가상한 UI(전종목 존중)·종목별 성과 테이블, 그리고 매크로 국면 엔진을 YoY-변환 + 실물지표 축으로 재구축(KR/US 분리).

**Architecture:** 엔진에 `liquidate_at_end`(엔진 기본 OFF·API 기본 ON), `_compute_symbol_results`를 라운드트립 기반으로 확장. 매크로는 신규 순수모듈 `src/engine/regime_axes.py`가 변환(YoY)·축정의·사분면의 단일 진실 공급원 — collector/차트는 원시값 유지(영향 0), analyzer와 trajectory가 공유.

**Tech Stack:** FastAPI+pytest(mock `KIS_USE_MOCK=1`), Next.js14+TS. 스펙: `docs/superpowers/specs/2026-07-02-backtest-macro-fixes-design.md`

**커밋 트레일러(전 커밋)**: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`
**베이스라인**: 668 passed / 10 skipped. 브랜치 `claude/keen-thompson-bdk3e8` 외 푸시 금지.

---

### Task 1: 기간종료 청산 (엔진 TDD + API 기본 ON)

**Files:** Modify `src/kis_backtest_engine.py` (BacktestConfig ≈200대, run() 종료부 ≈588-593, `_build_result` stats 직후, `run_backtest` 시그니처+cfg), `src/api/screener_routes.py` (`ScreenToBacktestRequest` ≈1257대, run_backtest 호출 ≈1448). Test `tests/test_liquidate_at_end.py`.

- [ ] **Step 1: 실패 테스트** — `tests/test_liquidate_at_end.py`:

```python
"""기간종료 청산 — 매도 미발동 전략도 통계(승률/PF/거래수)가 실현 기준으로 채워진다."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402
from src.kis_strategies import condition_strategy  # noqa: F401,E402 — "Condition" 등록

START = "2024-04-01"


def make_up_df() -> pd.DataFrame:
    closes = [100.0] * 60 + [100.0 + i for i in range(40)]  # 워밍업 후 지속 상승
    n = len(closes)
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=n - 60))
    s = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": [10_000] * n}, index=idx)


@pytest.fixture
def up_loader(monkeypatch):
    df = make_up_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda *a, **k: df.copy())
    return df


BUY_ONLY = {"buy_conditions": [
    {"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0},
]}  # 항상 매수·매도 조건 없음 → 기간 끝까지 보유


def _cfg(**over) -> BacktestConfig:
    base = dict(symbols=["000111"], strategy_name="Condition", strategy_params=BUY_ONLY,
                start_date=START, end_date="2024-06-28", initial_capital=10_000_000,
                commission_rate=0.001, slippage_rate=0.001)
    base.update(over)
    return BacktestConfig(**base)


def test_no_liquidation_by_default(up_loader):
    e = BacktestEngine(_cfg())
    r = e.run()
    st = r["result"]["statistics"]
    assert st["num_trades"] == 0                      # 청산 없음 → 기존 동작 불변
    assert not [t for t in e.trades if t.side == "sell"]


def test_liquidate_at_end_fills_stats(up_loader):
    e = BacktestEngine(_cfg(liquidate_at_end=True))
    r = e.run()
    st = r["result"]["statistics"]
    sells = [t for t in e.trades if t.side == "sell"]
    assert len(sells) == 1 and sells[0].reason == "기간종료 청산"
    assert st["num_trades"] == 1
    assert st["win_rate"] > 0                          # 상승장 보유 → 승리
    assert st["eod_liquidated"] == 1
    assert r["result"]["round_trips"], "라운드트립도 생성"


def test_final_equity_reflects_liquidation_costs(up_loader):
    e_off = BacktestEngine(_cfg()); r_off = e_off.run()
    e_on = BacktestEngine(_cfg(liquidate_at_end=True)); r_on = e_on.run()
    eq_off = r_off["result"]["equity_curve"][-1]
    eq_on = r_on["result"]["equity_curve"][-1]
    assert eq_on < eq_off                              # 청산 수수료·슬리피지 반영(정직)
    assert eq_on > eq_off * 0.99                       # 미세 차이

```

- [ ] **Step 2: RED 확인** — `KIS_USE_MOCK=1 python -m pytest tests/test_liquidate_at_end.py -q` → TypeError(BacktestConfig unexpected kwarg liquidate_at_end).

- [ ] **Step 3: 구현**
  - `BacktestConfig`에 `liquidate_at_end: bool = False   # 기간종료 시 잔여 포지션 종가 전량청산(통계 실현화)` 추가 (rebuy_block_days 근처).
  - `BacktestEngine.__init__`(run 초기화부)에 `self._eod_liquidated = 0`.
  - `run()`의 `duration = ...`(≈592) 직전에:

```python
        # 기간종료 청산 — 잔여 포지션을 마지막 거래일 종가로 전량 실현(수수료·슬리피지 반영).
        # 매도 미발동 전략도 승률/PF/거래수/라운드트립이 채워진다 (min_hold 등 규칙은 강제 청산이라 미적용).
        if self.cfg.liquidate_at_end and self.positions and self.equity_history:
            last_date_str = self.equity_history[-1][0]
            for ticker in list(self.positions.keys()):
                df = ohlcv_map.get(ticker)
                if df is None or df.empty:
                    continue
                df_to = df.loc[:sim_date]
                if df_to.empty:
                    continue
                self._execute_sell(ticker, float(df_to["close"].iloc[-1]),
                                   last_date_str, "기간종료 청산")
                self._eod_liquidated += 1
            # 마지막 자산 기록을 청산 반영값으로 교체 (곡선 끝 == 실현 자산)
            self.equity_history[-1] = (last_date_str,
                                       self._calc_equity(ohlcv_map, sim_date, etf_map))
```

  - `_build_result`에서 `stats = _compute_statistics(...)` 직후: `stats["eod_liquidated"] = getattr(self, "_eod_liquidated", 0)`.
  - `run_backtest(..., progress_cb=None, liquidate_at_end: bool = True)` 파라미터 추가 → BacktestConfig 전달. (공개 API 기본 ON — 사용자 관측 수정)
  - `ScreenToBacktestRequest += liquidate_at_end: bool = True`; run_backtest 호출부에 `liquidate_at_end=req.liquidate_at_end` 전달.

- [ ] **Step 4: GREEN + 회귀** — 신규 3 passed; `pytest tests/ -q` — 주의: run_backtest 기본 ON으로 기존 API 경유 테스트의 거래수 변화 가능 → 실패 시 해당 테스트가 전제하는 값 검토(전략이 기간 내 전량 청산하는 시나리오는 불변; 보유 잔존 시나리오만 +N 거래). 영향 테스트는 `liquidate_at_end=False` 명시 또는 기대값 갱신(사유 주석).

- [ ] **Step 5: Commit** — `feat(backtest): 기간종료 청산 — 거래통계 0 해소 (엔진 opt-in, API 기본 ON)`

---

### Task 2: symbol_results 확장 (백엔드 TDD)

**Files:** Modify `src/kis_backtest_engine.py` (`_compute_symbol_results` ≈1703). Test `tests/test_symbol_results_ext.py`.

- [ ] **Step 1: 실패 테스트**:

```python
"""종목별 성과 확장 — 라운드트립 기반 실현손익/평균수익률/평균보유일/기여도."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.kis_backtest_engine import Trade, _compute_symbol_results  # noqa: E402

TRADES = [
    Trade("2024-01-02", "A", "buy", 100.0, 10, 1000, 1, 0),
    Trade("2024-01-12", "A", "sell", 120.0, 10, 1200, 1, 0, pnl=200.0),
    Trade("2024-02-01", "A", "buy", 110.0, 10, 1100, 1, 0),
    Trade("2024-02-11", "A", "sell", 99.0, 10, 990, 1, 0, pnl=-110.0),
    Trade("2024-01-02", "B", "buy", 200.0, 5, 1000, 1, 0),
    Trade("2024-03-02", "B", "sell", 220.0, 5, 1100, 1, 0, pnl=100.0),
]


def test_extended_fields():
    rs = {r["symbol"]: r for r in _compute_symbol_results(TRADES, ["A", "B"])}
    a, b = rs["A"], rs["B"]
    assert a["realized_pnl"] == 90.0            # 200 - 110
    assert a["round_trips"] == 2 and a["win_rate"] == 50.0
    assert abs(a["avg_hold_days"] - 10.0) < 0.01
    assert abs(a["avg_return_pct"] - ((20.0 + -10.0) / 2)) < 0.2   # +20%, -10%
    assert b["avg_hold_days"] == 60.0
    total = 90.0 + 100.0
    assert abs(a["contribution_pct"] - 90.0 / total * 100) < 0.1
    assert "corp_name" in a


def test_no_trades_symbol_zeroes():
    rs = {r["symbol"]: r for r in _compute_symbol_results([], ["C"])}
    assert rs["C"]["realized_pnl"] == 0.0 and rs["C"]["round_trips"] == 0
```

- [ ] **Step 2: RED 확인** (KeyError realized_pnl).

- [ ] **Step 3: 구현** — `_compute_symbol_results`를 `_round_trips(trades)` 기반으로 재작성(기존 필드 유지+추가):

```python
def _compute_symbol_results(trades: list[Trade], symbols: list[str]) -> list[dict]:
    """종목별 성과 — 라운드트립 기반 (실현손익/평균수익률/평균보유일/기여도 포함)."""
    from datetime import datetime as _dt

    from src.data.stock_master import get_stock_name

    rts = _round_trips(trades)
    by_sym: dict[str, list[dict]] = {s: [] for s in symbols}
    for rt in rts:
        by_sym.setdefault(rt["stock_code"], []).append(rt)
    buy_amount: dict[str, float] = {}
    for t in trades:
        if t.side == "buy":
            buy_amount[t.ticker] = buy_amount.get(t.ticker, 0.0) + t.value

    def _days(rt) -> float:
        try:
            d0 = _dt.strptime(rt["entry_date"][:10], "%Y-%m-%d")
            d1 = _dt.strptime(rt["exit_date"][:10], "%Y-%m-%d")
            return max(0.0, (d1 - d0).days)
        except Exception:
            return 0.0

    total_pnl = sum((rt["pnl"] or 0.0) for rt in rts)
    results = []
    for ticker, lst in by_sym.items():
        n = len(lst)
        pnl = sum((rt["pnl"] or 0.0) for rt in lst)
        wins = sum(1 for rt in lst if (rt["pnl"] or 0.0) > 0)
        ba = buy_amount.get(ticker, 0.0)
        results.append({
            "symbol": ticker,
            "corp_name": get_stock_name(ticker) or ticker,
            "total_return_pct": round(pnl / ba * 100, 2) if ba > 0 else 0.0,
            "num_trades": sum(1 for t in trades if t.ticker == ticker),
            "round_trips": n,
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "realized_pnl": round(pnl, 0),
            "avg_return_pct": round(sum(rt["return_pct"] for rt in lst) / n, 2) if n else 0.0,
            "avg_hold_days": round(sum(_days(rt) for rt in lst) / n, 1) if n else 0.0,
            "contribution_pct": round(pnl / total_pnl * 100, 1) if total_pnl else 0.0,
        })
    return results
```

- [ ] **Step 4: GREEN + 회귀** — 기존 `win_rate` 의미가 leg→라운드트립 기준으로 정밀화됨: 관련 기존 테스트 실패 시 검토·갱신. `ruff check`.

- [ ] **Step 5: Commit** — `feat(backtest): 종목별 성과 확장 — 실현손익·평균수익률·보유일·기여도`

---

### Task 3: 프론트 — 평가상한 셀렉트 + 종목별 성과 테이블 + 청산 표기

**Files:** Modify `frontend/src/components/backtest/TerminalBacktester.tsx` (mapBody ≈109-115, 고급옵션 블록, substats ≈521, CONSTITUENTS ≈596-611), `frontend/src/lib/screenerApi.ts`(타입), `frontend/src/app/globals.css`.

- [ ] **Step 1: 타입** — `BacktestStatistics += eod_liquidated?: number;` / 신규 `export interface SymbolPerf { symbol: string; corp_name?: string; total_return_pct: number; num_trades: number; round_trips?: number; win_rate: number; realized_pnl?: number; avg_return_pct?: number; avg_hold_days?: number; contribution_pct?: number; }` / `ScreenToBacktestResult.backtest += symbol_results?: SymbolPerf[];` / `screenToBacktest` body에 `universe_eval_cap`·`liquidate_at_end` 전달 필드(이미 params 객체면 확장).

- [ ] **Step 2: 평가상한 셀렉트** — `const [evalCap, setEvalCap] = useState(4000);` — 고급옵션(체결가 섹션 위)에:

```tsx
<label className="tbt-adv-label">평가 종목 상한
  <select value={evalCap} onChange={(e) => setEvalCap(Number(e.target.value))}>
    <option value={500}>500</option><option value={1000}>1,000</option>
    <option value={2000}>2,000</option><option value={4000}>전체 (제한 없음)</option>
  </select>
</label>
```
바디의 `universe_eval_cap: 200` → `universe_eval_cap: evalCap`. 안내 캡션: "첫 실행은 미적재 종목 시세 수집으로 수 분 걸릴 수 있음(진행률 표시) — 이후 DB 즉시".

- [ ] **Step 3: substats 청산 표기** — 보조바에 `{(st.eod_liquidated ?? 0) > 0 && <span>기간종료 청산 <b>{st.eod_liquidated}종목</b></span>}`.

- [ ] **Step 4: CONSTITUENTS → 종목별 성과 테이블** — 칩 블록 교체. `SymbolPerfTable` 컴포넌트(파일 하단): props `{rows: SymbolPerf[]; roundTrips: BacktestTrade[]}`. 기여도 내림차순 정렬 상태(클릭 정렬: 기여도/실현손익/승률/보유일), 20행 페이지(이전/다음), 행 클릭 → 해당 종목 round_trips 필터 인라인 상세(진입/청산일·가격·수량·수익률·보유일·사유; 500캡 도달 시 "일부 표시" 주석). REAL/MOCK 배지 유지. CSS `tbt-symtable` 계열(trisk-table 변형).

- [ ] **Step 5: 검증+커밋** — `tsc 0`·`next build`. Commit `feat(backtest-ui): 평가상한 셀렉트(기본 전체) + 종목별 성과 테이블 + 청산 표기`

---

### Task 4: regime_axes.py + collector 신규 시리즈/yoy 수정 (TDD)

**Files:** Create `src/engine/regime_axes.py`. Modify `src/services/macro_collector.py` (bok_targets ≈395, MOCK dict ≈335, yoy ≈465). Test `tests/test_regime_axes.py`.

- [ ] **Step 1: 실패 테스트**:

```python
"""국면 축 — YoY 변환·z·가중 재정규화·사분면 (지수 레벨 z-score 버그의 회귀 방지)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.regime_axes import (  # noqa: E402
    KR_GROWTH, US_GROWTH, US_INFLATION, compute_axis, quadrant, yoy_pct, zscore_at,
)


class FakeSeries:
    def __init__(self, values):
        self.values = values


def test_yoy_pct_percent_change():
    vals = [100.0] * 12 + [103.0]
    y = yoy_pct(vals)
    assert abs(y[-1] - 3.0) < 1e-9 and y[0] is None


def test_constant_inflation_z_near_zero():
    # 매월 +0.25% (연 ~3%) 등속 상승 지수 — YoY가 일정 → z ≈ 0 (레벨 z였다면 ≈ +1.7)
    vals, v = [], 100.0
    for _ in range(120):
        vals.append(v)
        v *= 1.0025
    z = zscore_at(yoy_pct(vals))
    assert z is not None and abs(z) < 0.5


def test_accelerating_inflation_positive_z():
    vals, v = [], 100.0
    for i in range(120):
        vals.append(v)
        v *= 1.0015 if i < 100 else 1.006   # 최근 가속
    assert zscore_at(yoy_pct(vals)) > 1.0


def test_axis_sign_and_renormalize():
    sm = {"UNRATE": FakeSeries([4.0] * 100 + [6.0])}   # 실업률 급등(성장 부정) — 나머지 미가용
    g = compute_axis(sm, US_GROWTH)
    assert g < 0                                        # 부호 반전 + 재정규화로 단독 반영


def test_missing_all_series_zero():
    assert compute_axis({}, US_INFLATION) == 0.0
    assert compute_axis({}, KR_GROWTH) == 0.0


def test_quadrant_names():
    assert quadrant(1, -1) == "Goldilocks" and quadrant(1, 1) == "Reflation"
    assert quadrant(-1, 1) == "Stagflation" and quadrant(-1, -1) == "Deflation"
```

- [ ] **Step 2: RED** (ModuleNotFoundError).

- [ ] **Step 3: 구현** `src/engine/regime_axes.py`:

```python
"""국면 축 단일 진실 공급원 — 변환(YoY)·z·축 정의·사분면.

지수형 시리즈(CPI/산업생산/GDP/고용/KOSPI)는 레벨이 항상 우상향이라 레벨 z-score가
구조적으로 +로 고정된다(과거 Stagflation 고정 버그의 원인). 여기서 YoY %로 변환 후
z-score한다. collector/차트는 원시값을 유지 — 변환은 이 모듈에서만 수행.
축 구성: 성장×물가 2×2 (Bridgewater 4국면/경기사이클 표준 관행)."""
from __future__ import annotations

import math

# (series_key, transform, sign, weight) — transform: "yoy"(지수→전년比%) | "level"
US_GROWTH = [("INDPRO", "yoy", 1, 0.35), ("PAYEMS", "yoy", 1, 0.25),
             ("UNRATE", "level", -1, 0.20), ("GDPC1", "yoy", 1, 0.20)]
US_INFLATION = [("CPIAUCSL", "yoy", 1, 0.60), ("T10YIE", "level", 1, 0.40)]
KR_GROWTH = [("KR_LEADING_CYCLE", "level", 1, 0.40), ("KR_IP", "yoy", 1, 0.30),
             ("KOSPI", "yoy", 1, 0.30)]
KR_INFLATION = [("KR_CPI", "yoy", 1, 0.70), ("T10YIE", "level", 1, 0.30)]

AXES = {"kr": (KR_GROWTH, KR_INFLATION), "us": (US_GROWTH, US_INFLATION)}


def yoy_pct(values, lag: int = 12) -> list:
    """지수 레벨 시계열 → 전년동기比 % 시계열 (선두 lag개는 None)."""
    out = []
    for i, v in enumerate(values):
        prev = values[i - lag] if i >= lag else None
        ok = v is not None and prev is not None and prev > 0
        out.append((v / prev - 1) * 100 if ok else None)
    return out


def zscore_at(vals, back: int = 0, window: int = 60) -> float | None:
    """시계열의 -1-back 시점 값의 z (직전 window 표본 기준). 표본<8이면 None."""
    clean_idx = len(vals) - 1 - back
    if clean_idx < 0:
        return None
    seg = [v for v in vals[max(0, clean_idx - window + 1):clean_idx + 1] if v is not None]
    if len(seg) < 8:
        return None
    x = vals[clean_idx]
    if x is None:
        return None
    mean = sum(seg) / len(seg)
    var = sum((v - mean) ** 2 for v in seg) / len(seg)
    std = math.sqrt(var)
    return (x - mean) / std if std > 1e-12 else 0.0


def compute_axis(series_map: dict, axis_def: list, back: int = 0) -> float:
    """가중 z 평균. 시리즈 미가용/표본 부족은 제외하고 가중치 재정규화(허위값 금지)."""
    acc, wsum = 0.0, 0.0
    for key, transform, sign, weight in axis_def:
        s = series_map.get(key)
        vals = [v for v in (getattr(s, "values", None) or [])]
        if not vals:
            continue
        series = yoy_pct(vals) if transform == "yoy" else vals
        z = zscore_at(series, back=back)
        if z is None:
            continue
        acc += sign * z * weight
        wsum += weight
    return acc / wsum if wsum > 0 else 0.0


def quadrant(growth: float, inflation: float) -> str:
    """성장×물가 사분면 — 전 모듈 공용 명칭."""
    if growth >= 0:
        return "Reflation" if inflation >= 0 else "Goldilocks"
    return "Stagflation" if inflation >= 0 else "Deflation"
```

- [ ] **Step 4: collector 수정** — bok_targets에 2종 추가(코드는 GCP 실호출 검증, 실패 시 unavailable→축 자동 제외):

```python
            ("KR_LEADING_CYCLE", "901Y067", "I16E", "경기선행지수 순환변동치", "지수"),
            ("KR_IP",            "901Y033", "A00",  "산업생산지수",           "지수"),
```
MOCK 파라미터 dict(≈335)에 `"KR_LEADING_CYCLE": {"base": 100.3, "vol": 0.5, "trend": -0.04}, "KR_IP": {"base": 112.0, "vol": 1.0, "trend": 0.12},` 추가.
yoy(≈465)를 단위 인지형으로: `yoy = (clean[-1] - clean[-13]) if unit == "%" else ((clean[-1] / clean[-13] - 1) * 100 if clean[-13] > 0 else None)` (13표본 조건 유지).

- [ ] **Step 5: GREEN + 회귀 + Commit** — `feat(macro): regime_axes 단일 축 모듈(YoY 변환) + BOK 경기선행/산업생산 수집`

---

### Task 5: analyzer KR/US + trajectory 공유 + API markets (TDD)

**Files:** Modify `src/engine/regime_analyzer.py` (`analyze` 시그니처, `_compute_*_axis` 교체, `get_regime_states` 신규), `src/engine/macro_analytics.py` (`_GROWTH_DEF/_INFL_DEF/_quadrant_of` 제거→regime_axes, `regime_trajectory(market=...)`), `src/api/macro_routes.py` (`/regime` markets, trajectory 엔드포인트 market 쿼리). Test `tests/test_regime_analyzer_dual.py`.

- [ ] **Step 1: 실패 테스트**:

```python
"""KR/US 국면 분리 + 축이 regime_axes 기반으로 계산되는지."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.regime_analyzer import RegimeAnalyzer, get_regime_states  # noqa: E402


def test_analyze_market_param():
    a = RegimeAnalyzer()
    snap = a.collector.collect_all(use_cache=True)
    kr = a.analyze(snap, market="kr")
    us = a.analyze(snap, market="us")
    assert kr.regime in ("Goldilocks", "Reflation", "Stagflation", "Deflation", "데이터 부족")
    assert us.regime in ("Goldilocks", "Reflation", "Stagflation", "Deflation", "데이터 부족")
    assert kr.market == "kr" and us.market == "us"


def test_get_regime_states_both():
    states = get_regime_states()
    assert set(states.keys()) == {"kr", "us"}
```

- [ ] **Step 2: RED** (analyze() unexpected kwarg market).

- [ ] **Step 3: 구현**
  - `RegimeState += market: str = "kr"`.
  - `analyze(self, snapshot=None, market: str = "kr")` — 축 계산부 교체:

```python
        from src.engine.regime_axes import AXES, compute_axis
        g_def, i_def = AXES.get(market, AXES["kr"])
        growth_axis = compute_axis(s, g_def)
        inflation_axis = compute_axis(s, i_def)
```
  `_classify_regime`은 `regime_axes.quadrant` 사용(명칭 동일 유지 — Goldilocks/Reflation/Stagflation/Deflation, 신뢰도 tanh 유지). `_compute_growth_axis/_compute_inflation_axis` 메서드 삭제(참조 검색 후). RegimeState 생성에 `market=market`.
  - `get_regime_state()` 기존 시그니처·KR 기본 유지. 신규:

```python
def get_regime_states() -> dict:
    """KR/US 국면 동시 — 콕핏 두 카드용."""
    global _ANALYZER_INSTANCE
    if _ANALYZER_INSTANCE is None:
        _ANALYZER_INSTANCE = RegimeAnalyzer()
    snap = _ANALYZER_INSTANCE.collector.collect_all(use_cache=True)
    return {"kr": _ANALYZER_INSTANCE.analyze(snap, market="kr"),
            "us": _ANALYZER_INSTANCE.analyze(snap, market="us")}
```
  - `macro_analytics.py`: `_GROWTH_DEF/_INFL_DEF/_quadrant_of` 삭제 → `regime_trajectory(n_months=18, market="kr")`가 `compute_axis(series, AXES[market][0|1], back=back)` 사용(÷2·clamp 유지), quadrant는 공용. 라우트(trajectory 엔드포인트)에 `market: str = Query("kr")` 전달.
  - `/api/v1/macro/regime`: 스냅샷 1회 수집 → `out = asdict(kr); out["markets"] = {"kr": asdict(kr), "us": asdict(us)}` (기존 최상위 = KR, 하위호환).

- [ ] **Step 4: GREEN + 회귀(특히 기존 regime/macro 테스트·trajectory 소비자) + Commit** — `feat(macro): KR/US 국면 분리 + 축 정의 단일화(analyzer·trajectory 공유)`

---

### Task 6: 콕핏 KR/US 두 카드 (프론트)

**Files:** Modify `frontend/src/components/macro/MacroCockpit.tsx` (레짐 배너 ≈47-50 명칭 맵, 헤더 카드), `frontend/src/lib/*` macro API 타입 (macroRegime 반환에 `markets?`), 필요시 `globals.css`.

- [ ] **Step 1**: 타입 — regime 응답에 `markets?: { kr: RegimeDto; us: RegimeDto }` (RegimeDto = 기존 regime 타입 + `market?: string`).
- [ ] **Step 2**: 배너 교체 — 기존 단일 "현재 국면" 카드 → 좌우 2카드(`KR 국면`/`US 국면`): 국면명·설명·성장/물가 축·모드·신뢰도. `markets` 없으면(구버전 응답) 기존 단일 카드 폴백. 사분면 명칭 맵을 Goldilocks/Reflation/Stagflation/Deflation 4종으로 통일(Overheating/Disinflation 제거 — RegimeTrajectory 범례 포함).
- [ ] **Step 3**: `tsc 0`·`next build`·(가능 시) mock 라이브 렌더. Commit `feat(macro-ui): KR/US 국면 두 카드 + 사분면 명칭 통일`

---

### Task 7: 전체 검증 + CLAUDE.md + 푸시

- [ ] `KIS_USE_MOCK=1 python -m pytest tests/ -q` (668+신규 ≈680± passed / 10 skipped) + `ruff check .`
- [ ] `npx tsc --noEmit && npx next build` (16/16)
- [ ] mock 라이브: 백테스트(매수만 전략) → 거래통계 채워짐+청산 표기 / 매크로 헤더 두 카드 / 평가상한 셀렉트
- [ ] CLAUDE.md 세션 요약 + 커밋 + `git push -u origin claude/keen-thompson-bdk3e8` (백오프 재시도)
- [ ] 보고: GCP 확인 항목(실 국면 값, BOK 신규 시리즈 코드 검증 — 소스 패널 real/mock, 실패 시 유일 수정 지점은 bok_targets 코드 2줄)
