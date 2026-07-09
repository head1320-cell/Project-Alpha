# 기업분석 탭 심화 (FAS/DD 실무) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** /insights 3개 탭(Valuation/Financials/Risk)에 실무 산출물(풋볼필드·가정 샌드박스·민감도·Comps·QoE·NWC·워터폴·듀폰·Altman/Beneish 분해·커버리지·금리 스트레스)을 추가한다.

**Architecture:** 신규 순수 함수 모듈 `src/engine/company_analytics.py`(기존 ValuationEngine·financials_history·팩터 스토어 재사용) + 신규 `src/api/company_routes.py`(탭당 GET 1개) + Cockpit 탭 컴포넌트 3개 분리. 스펙: `docs/superpowers/specs/2026-07-09-company-analysis-deep-design.md`.

**Tech Stack:** FastAPI, SQLAlchemy(financials_history), 기존 ValuationEngine(RIM/DCF/DDM), Next.js 14 + 자체 SVG 차트(외부 라이브러리 금지).

**재사용 접점 (검증 완료):**
- `ValuationEngine(DARTClient()).evaluate(code, price, params, market_cap=)` → `UnifiedValuation` (DARTClient가 FS를 캐시하므로 같은 인스턴스로 25회 재평가는 저렴)
- Rf 실측: `src.engine.regime_analyzer.get_dynamic_risk_free_rate()` (실패 시 0.035)
- β 실측: `PriceFactorsStore.get_default().get_factors(code).get("beta_1y")`
- 연간 재무 10년: `src.data.dart_history.load_history(code)` → reprt=="11011" 필터 (원 단위, seq 오름차순)
- 피어: `ValuationScreener().run(universe=f"sector:{sector}", liquidity_floor="off", ...)` — item에 per/pbr/ev_ebitda/roe_pct/operating_margin/revenue_growth_yoy/market_cap_억 attach됨
- 52주: `src.data.ohlcv_loader.load_ohlcv_unified(code, start, end)`
- 원천(억): `FundamentalsStore.get_default().get_raw_financials(code)` — market_cap/current_assets/... (Altman 분해용, 팩터와 동일 원천)

---

### Task 1: company_analytics 코어 A — 기본 파라미터·샌드박스·풋볼필드·Comps (TDD)

**Files:**
- Create: `src/engine/company_analytics.py`
- Test: `tests/test_company_analytics.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_company_analytics.py`

```python
"""company_analytics — 기업분석 심화 순수 함수 (스펙 2026-07-09).

mock 모드(KIS_USE_MOCK=1)의 결정론 데이터로 수식·구조·정직성 계약을 검증.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine import company_analytics as ca  # noqa: E402

CODE = "005930"
PRICE = 70000.0


def test_resolve_default_params_shape():
    p = ca.resolve_default_params(CODE)
    assert set(p) >= {"rf", "rf_source", "beta", "beta_source", "erp", "g", "years"}
    assert 0.0 < p["rf"] < 0.15 and 0.1 <= p["beta"] <= 3.0


def test_sensitivity_grid_monotonic():
    out = ca.valuation_sandbox(CODE, PRICE, {})
    sens = out["sensitivity"]
    assert len(sens["ke_axis"]) == 5 and len(sens["g_axis"]) == 5
    grid = sens["grid"]
    # ke↑(행) → 가치↓, g↑(열) → 가치↑ (null 칸 제외 비교)
    vals = [[c for c in row] for row in grid]
    mid = 2
    col = [vals[i][mid] for i in range(5) if vals[i][mid] is not None]
    assert col == sorted(col, reverse=True), "ke 상승 시 가치는 단조 감소해야"
    row = [vals[mid][j] for j in range(5) if vals[mid][j] is not None]
    assert row == sorted(row), "g 상승 시 가치는 단조 증가해야"


def test_sensitivity_tv_divergence_guard():
    # g가 ke에 근접(0.5%p 미만)하면 해당 칸은 None (TV 발산 방지)
    out = ca.valuation_sandbox(CODE, PRICE, {"g": 0.05, "beta": 0.2, "erp": 0.01, "rf": 0.045})
    grid = out["sensitivity"]["grid"]
    assert any(c is None for row in grid for c in row)


def test_sandbox_assumptions_have_sources():
    out = ca.valuation_sandbox(CODE, PRICE, {})
    keys = {a["key"] for a in out["assumptions"]}
    assert {"rf", "beta", "erp", "g", "years"} <= keys
    assert all(a.get("source") for a in out["assumptions"])


def test_football_field_bands():
    out = ca.football_field(CODE, PRICE)
    assert out["current_price"] == PRICE
    ids = {b["id"] for b in out["bands"]}
    assert {"dcf", "rim", "ddm", "w52"} <= ids
    for b in out["bands"]:
        if b.get("available", True):
            assert b["lo"] <= b["hi"], f"{b['id']} 밴드 lo>hi"


def test_comps_table_has_median_and_implied():
    out = ca.comps_table(CODE)
    assert out["rows"], "피어 행이 비어있음"
    assert out["rows"][0]["code"] == CODE  # 첫 행 = 자사
    assert "median_row" in out and "implied" in out
    imp = out["implied"]
    assert set(imp) >= {"per_based", "pbr_based", "ev_ebitda_based"}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_company_analytics.py -x -q`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (company_analytics 없음)

- [ ] **Step 3: 구현** — `src/engine/company_analytics.py`

```python
"""기업분석 심화 — FAS/DD 실무 산출물 (스펙 2026-07-09).

순수 계산 모듈: Valuation 샌드박스·민감도·Football Field·Comps.
기존 ValuationEngine(RIM/DCF/DDM)·financials_history·팩터 스토어를 재사용하며,
모든 산출 불가 항목은 available:false + note(사유)로 정직하게 표기한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_KE_STEPS = (-0.010, -0.005, 0.0, 0.005, 0.010)   # Ke ±1.0%p (rf 이동으로 실현)
_G_STEPS = (-0.010, -0.005, 0.0, 0.005, 0.010)
_TV_GAP = 0.005                                    # g < ke - 0.5%p 발산 가드


def resolve_default_params(code: str) -> dict:
    """실측 기본 가정: Rf=ECOS 국고채10년, β=KIS 1년 실측. 실패 시 표준 기본값+출처 라벨."""
    rf, rf_source = 0.035, "기본값 (국고채 10년 근사)"
    try:
        from src.engine.regime_analyzer import get_dynamic_risk_free_rate
        v = get_dynamic_risk_free_rate()
        if v and 0.0 < v < 0.15:
            rf, rf_source = round(float(v), 4), "ECOS 국고채 10년 (실시간)"
    except Exception:
        pass
    beta, beta_source = 1.0, "기본값"
    try:
        from src.data.price_factors_store import PriceFactorsStore
        b = PriceFactorsStore.get_default().get_factors(code).get("beta_1y")
        if b and 0.1 <= float(b) <= 3.0:
            beta, beta_source = round(float(b), 2), "KIS 1년 실측"
    except Exception:
        pass
    return {"rf": rf, "rf_source": rf_source, "beta": beta, "beta_source": beta_source,
            "erp": 0.06, "g": 0.02, "years": 10}


def _make_params(rf, beta, erp, g, years):
    from src.engine.valuation.valuation_models import ValuationParams
    return ValuationParams(risk_free_rate=rf, market_premium=erp, beta=beta,
                           terminal_growth_rate=g, projection_years=int(years))


def _engine():
    from src.data.dart_client import DARTClient
    from src.engine.valuation.valuation_models import ValuationEngine
    return ValuationEngine(DARTClient())


def _mcap(code: str) -> float | None:
    """시총(억) — 팩터 원천 재사용 (발행주식수 도출 → RIM/DCF 활성)."""
    try:
        from src.data.fundamentals_store import FundamentalsStore
        m = FundamentalsStore.get_default().get_raw_financials(code).get("market_cap")
        return float(m) if m and m > 0 else None
    except Exception:
        return None


def valuation_sandbox(code: str, price: float, overrides: dict) -> dict:
    """가정 샌드박스: (기본값+overrides)로 통합평가 + Ke×g 민감도 5×5.

    ke 축은 rf 평행이동으로 실현 (ke = rf + β·erp → Δrf = Δke).
    g ≥ ke − 0.5%p 칸은 TV 발산 → None."""
    d = resolve_default_params(code)
    rf = float(overrides.get("rf", d["rf"]))
    beta = float(overrides.get("beta", d["beta"]))
    erp = float(overrides.get("erp", d["erp"]))
    g = float(overrides.get("g", d["g"]))
    years = int(overrides.get("years", d["years"]))
    eng = _engine()
    mcap = _mcap(code)

    base = eng.evaluate(code, price, params=_make_params(rf, beta, erp, g, years), market_cap=mcap)
    ke = rf + beta * erp

    ke_axis = [round(ke + s, 4) for s in _KE_STEPS]
    g_axis = [round(g + s, 4) for s in _G_STEPS]
    grid: list[list[float | None]] = []
    for dk in _KE_STEPS:
        row: list[float | None] = []
        for dg in _G_STEPS:
            ke2, g2 = ke + dk, g + dg
            if g2 < 0 or g2 >= ke2 - _TV_GAP:
                row.append(None)          # 영구성장률이 할인율에 근접 → TV 발산(정직 null)
                continue
            r = eng.evaluate(code, price, params=_make_params(rf + dk, beta, erp, g2, years),
                             market_cap=mcap)
            row.append(round(r.intrinsic_value, 0) if r.intrinsic_value > 0 else None)
        grid.append(row)

    assumptions = [
        {"key": "rf", "label": "무위험수익률 Rf", "value": rf,
         "source": d["rf_source"] if abs(rf - d["rf"]) < 1e-9 else "사용자 조정"},
        {"key": "beta", "label": "베타 β", "value": beta,
         "source": d["beta_source"] if abs(beta - d["beta"]) < 1e-9 else "사용자 조정"},
        {"key": "erp", "label": "시장위험프리미엄 ERP", "value": erp,
         "source": "한국 ERP 표준 6%" if abs(erp - 0.06) < 1e-9 else "사용자 조정"},
        {"key": "g", "label": "영구성장률 g", "value": g,
         "source": "명목GDP 근사 2%" if abs(g - 0.02) < 1e-9 else "사용자 조정"},
        {"key": "years", "label": "예측기간", "value": years,
         "source": "표준 10년" if years == 10 else "사용자 조정"},
        {"key": "ke", "label": "자기자본비용 Ke (도출)", "value": round(ke, 4), "source": "CAPM: Rf+β·ERP"},
    ]
    return {
        "unified": {
            "value": round(base.intrinsic_value, 0), "gap_pct": round(base.gap_pct, 2),
            "verdict": base.verdict,
            "models": [{"model": m.model, "value": round(m.intrinsic_value_per_share, 0),
                        "available": m.available, "error": m.error} for m in base.models],
        },
        "assumptions": assumptions,
        "sensitivity": {"ke_axis": ke_axis, "g_axis": g_axis, "grid": grid,
                        "current_price": price},
        "defaults": d,
    }


def football_field(code: str, price: float) -> dict:
    """가치평가 밴드 차트 데이터 — DCF/RIM/DDM(Bear~Bull), 52주, 그레이엄, 피어 암시가."""
    d = resolve_default_params(code)
    eng = _engine()
    mcap = _mcap(code)
    scen = {}
    for name, (g, erp) in {"base": (d["g"], d["erp"]),
                           "bull": (d["g"] + 0.01, d["erp"] - 0.01),
                           "bear": (max(0.0, d["g"] - 0.01), d["erp"] + 0.01)}.items():
        scen[name] = eng.evaluate(code, price, params=_make_params(d["rf"], d["beta"], erp, g,
                                                                   d["years"]), market_cap=mcap)

    def _model_band(model_id: str, label: str) -> dict:
        vals = []
        for r in scen.values():
            m = next((m for m in r.models if m.model == model_id), None)
            if m and m.available and m.intrinsic_value_per_share > 0:
                vals.append(m.intrinsic_value_per_share)
        if not vals:
            note = "무배당 — 산출 불가" if model_id == "DDM" else "재무 데이터 부족"
            return {"id": model_id.lower(), "label": label, "available": False, "note": note,
                    "lo": None, "hi": None, "mid": None}
        return {"id": model_id.lower(), "label": label, "available": True,
                "lo": round(min(vals), 0), "hi": round(max(vals), 0),
                "mid": round(sorted(vals)[len(vals) // 2], 0), "note": "Bear~Bull 시나리오"}

    bands = [_model_band("DCF", "DCF (현금흐름할인)"),
             _model_band("RIM", "RIM (잔여이익)"),
             _model_band("DDM", "DDM (배당할인)")]

    # 52주 밴드 (일봉 — DB→KIS→mock 통합 로더)
    try:
        from src.data.ohlcv_loader import load_ohlcv_unified
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=370)).strftime("%Y-%m-%d")
        df = load_ohlcv_unified(code, start, end, prefer="auto")
        if df is not None and len(df) > 20:
            lo_col = "low" if "low" in df.columns else "close"
            hi_col = "high" if "high" in df.columns else "close"
            bands.append({"id": "w52", "label": "52주 최저~최고", "available": True,
                          "lo": round(float(df[lo_col].min()), 0),
                          "hi": round(float(df[hi_col].max()), 0), "mid": None,
                          "note": "일봉 기준"})
        else:
            bands.append({"id": "w52", "label": "52주 최저~최고", "available": False,
                          "lo": None, "hi": None, "mid": None, "note": "일봉 미적재"})
    except Exception:
        bands.append({"id": "w52", "label": "52주 최저~최고", "available": False,
                      "lo": None, "hi": None, "mid": None, "note": "일봉 조회 실패"})

    # 그레이엄 넘버 (팩터 재사용 — 점 밴드)
    try:
        from src.data.fundamentals_store import FundamentalsStore
        gn = FundamentalsStore.get_default().get_factors(code).get("graham_number")
        if gn and gn > 0:
            bands.append({"id": "graham", "label": "그레이엄 넘버", "available": True,
                          "lo": round(float(gn), 0), "hi": round(float(gn), 0),
                          "mid": round(float(gn), 0), "note": "√(22.5×EPS×BPS)"})
    except Exception:
        pass

    # 피어 멀티플 암시가 (25/75분위 × 자사 EPS/BPS)
    fsum = scen["base"].financial_summary or {}
    eps, bps = fsum.get("eps"), fsum.get("bps")
    try:
        comps = comps_table(code)
        peers = [r for r in comps["rows"][1:]]
        def _quart(key):
            vals = sorted(v[key] for v in peers if isinstance(v.get(key), (int, float)) and v[key] > 0)
            if len(vals) < 3:
                return None
            return vals[len(vals) // 4], vals[(3 * len(vals)) // 4]
        qp, qb = _quart("per"), _quart("pbr")
        if qp and eps and eps > 0:
            bands.append({"id": "peer_per", "label": "피어 PER 25~75분위 암시가", "available": True,
                          "lo": round(qp[0] * eps, 0), "hi": round(qp[1] * eps, 0), "mid": None,
                          "note": f"피어 {len(peers)}개"})
        if qb and bps and bps > 0:
            bands.append({"id": "peer_pbr", "label": "피어 PBR 25~75분위 암시가", "available": True,
                          "lo": round(qb[0] * bps, 0), "hi": round(qb[1] * bps, 0), "mid": None,
                          "note": f"피어 {len(peers)}개"})
    except Exception as e:
        logger.debug(f"피어 밴드 실패 [{code}]: {e}")

    return {"current_price": price, "bands": bands}


def comps_table(code: str) -> dict:
    """상대가치 매트릭스 — 자사+동일섹터 피어의 멀티플 표 + 중간값 + 재평가 암시가.

    암시가 = 현재가 × (피어 중간값 멀티플 / 자사 멀티플) — 중간값 재평가(re-rating) 로직."""
    from src.engine.screener import ValuationScreener
    sc = ValuationScreener()
    self_res = sc.run(universe=[code], filter_ast=None, liquidity_floor="off", limit=1)
    if not self_res.items:
        return {"rows": [], "median_row": {}, "implied": {}, "note": "종목 조회 실패"}
    me = self_res.items[0]
    sector = getattr(me, "sector", None) or "기타"
    peer_res = sc.run(universe=f"sector:{sector}", filter_ast=None,
                      liquidity_floor="off", limit=24)

    def _row(it) -> dict:
        def num(attr):
            v = getattr(it, attr, None)
            return round(float(v), 2) if isinstance(v, (int, float)) else None
        return {"code": it.stock_code, "name": it.corp_name,
                "mcap": num("market_cap_억"), "per": num("per"), "pbr": num("pbr"),
                "ev_ebitda": num("ev_ebitda"), "roe": num("roe_pct"),
                "op_margin": num("operating_margin"), "rev_growth": num("revenue_growth_yoy")}

    rows = [_row(me)] + [_row(it) for it in peer_res.items if it.stock_code != code][:15]

    def _median(key):
        vals = sorted(r[key] for r in rows[1:] if isinstance(r.get(key), (int, float)))
        return round(vals[len(vals) // 2], 2) if vals else None
    median_row = {k: _median(k) for k in ("mcap", "per", "pbr", "ev_ebitda", "roe",
                                          "op_margin", "rev_growth")}

    price = float(getattr(me, "current_price", 0) or 0)
    def _implied(mult_key):
        m_med, m_self = median_row.get(mult_key), rows[0].get(mult_key)
        if not (price > 0 and m_med and m_self and m_self > 0):
            return None
        return round(price * m_med / m_self, 0)
    implied = {"per_based": _implied("per"), "pbr_based": _implied("pbr"),
               "ev_ebitda_based": _implied("ev_ebitda")}
    return {"sector": sector, "rows": rows, "median_row": median_row, "implied": implied}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_company_analytics.py -x -q`
Expected: 6 passed

- [ ] **Step 5: ruff + 커밋**

```bash
ruff check src/engine/company_analytics.py tests/test_company_analytics.py
git add src/engine/company_analytics.py tests/test_company_analytics.py
git commit -m "feat(company): 분석 코어 A — 가정 샌드박스·Ke×g 민감도·풋볼필드·Comps (TDD)"
```

---

### Task 2: /valuation-sandbox API + main_api 등록

**Files:**
- Create: `src/api/company_routes.py`
- Modify: `main_api.py` (라우터 등록 — 기존 `include_router` 블록 옆)
- Test: `tests/test_company_routes.py`

- [ ] **Step 1: 실패하는 테스트** — `tests/test_company_routes.py`

```python
"""company_routes — 기업분석 심화 API smoke (mock 모드)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402

from main_api import app  # noqa: E402

client = TestClient(app)


def test_valuation_sandbox_endpoint():
    r = client.get("/api/v1/company/005930/valuation-sandbox", params={"price": 70000})
    assert r.status_code == 200
    body = r.json()
    assert {"unified", "assumptions", "sensitivity", "football_field", "comps"} <= set(body)
    assert len(body["sensitivity"]["grid"]) == 5


def test_valuation_sandbox_overrides():
    r = client.get("/api/v1/company/005930/valuation-sandbox",
                   params={"price": 70000, "rf": 0.04, "beta": 1.2})
    assert r.status_code == 200
    a = {x["key"]: x for x in r.json()["assumptions"]}
    assert a["rf"]["value"] == 0.04 and a["rf"]["source"] == "사용자 조정"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_company_routes.py -x -q`
Expected: FAIL 404

- [ ] **Step 3: 구현** — `src/api/company_routes.py`

```python
"""기업분석 심화 API — 탭당 1콜 (스펙 2026-07-09).

GET /api/v1/company/{code}/valuation-sandbox  — 샌드박스+민감도+풋볼필드+Comps
GET /api/v1/company/{code}/financial-deep     — QoE·NWC·워터폴·듀폰 (Task 4)
GET /api/v1/company/{code}/risk-deep          — Altman·Beneish·커버리지·스트레스 (Task 6)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("api.company")

router = APIRouter(prefix="/api/v1/company", tags=["company-deep"])


@router.get("/{code}/valuation-sandbox")
def company_valuation_sandbox(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    rf: float | None = Query(None, ge=0, le=0.15),
    beta: float | None = Query(None, ge=0.1, le=3.0),
    erp: float | None = Query(None, ge=0, le=0.15),
    g: float | None = Query(None, ge=0, le=0.05),
    years: int | None = Query(None, ge=3, le=20),
):
    try:
        from src.engine import company_analytics as ca
        overrides = {k: v for k, v in
                     {"rf": rf, "beta": beta, "erp": erp, "g": g, "years": years}.items()
                     if v is not None}
        out = ca.valuation_sandbox(code, price, overrides)
        out["football_field"] = ca.football_field(code, price)
        out["comps"] = ca.comps_table(code)
        return out
    except Exception:
        logger.exception("valuation-sandbox 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
```

main_api.py 등록 (기존 valuation_routes 등록 라인을 찾아 그 옆에):

```python
from src.api.company_routes import router as company_router
app.include_router(company_router)
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `python -m pytest tests/test_company_routes.py tests/test_company_analytics.py -q`
Expected: 8 passed
Run: `python -c "import main_api; print(len(main_api.app.routes))"` → 217 이상 (기존 216+1)

- [ ] **Step 5: 커밋**

```bash
git add src/api/company_routes.py main_api.py tests/test_company_routes.py
git commit -m "feat(company): /valuation-sandbox API (샌드박스+풋볼필드+Comps 1콜)"
```

---

### Task 3: ValuationTab UI (풋볼필드 SVG + 슬라이더 + 히트맵 + Comps 표)

**Files:**
- Modify: `frontend/src/lib/screenerApi.ts` (companyApi에 valuationSandbox 추가 + 타입)
- Create: `frontend/src/components/insights/ValuationTab.tsx`
- Modify: `frontend/src/components/insights/CompanyCockpit.tsx` (valuation 탭 상단 렌더)
- Modify: `frontend/src/app/globals.css` (ca-ff-*/ca-heat-*/ca-comps-* 스타일)

- [ ] **Step 1: API 클라이언트 + 타입** — screenerApi.ts의 companyApi 객체에 추가

```typescript
// ── 기업분석 심화 (valuation-sandbox) ──
export interface SandboxAssumption { key: string; label: string; value: number; source: string }
export interface FootballBand {
  id: string; label: string; available?: boolean; note?: string;
  lo: number | null; hi: number | null; mid: number | null;
}
export interface CompsRow {
  code: string; name: string; mcap: number | null; per: number | null; pbr: number | null;
  ev_ebitda: number | null; roe: number | null; op_margin: number | null; rev_growth: number | null;
}
export interface ValuationSandbox {
  unified: { value: number; gap_pct: number; verdict: string;
    models: { model: string; value: number; available: boolean; error: string | null }[] };
  assumptions: SandboxAssumption[];
  sensitivity: { ke_axis: number[]; g_axis: number[]; grid: (number | null)[][]; current_price: number };
  defaults: { rf: number; beta: number; erp: number; g: number; years: number };
  football_field: { current_price: number; bands: FootballBand[] };
  comps: { sector?: string; rows: CompsRow[]; median_row: Partial<CompsRow>;
    implied: { per_based: number | null; pbr_based: number | null; ev_ebitda_based: number | null } };
}
```

companyApi 내부 메서드 (기존 evaluate 옆):

```typescript
  // 기업분석 심화: 샌드박스+민감도+풋볼필드+Comps (1콜)
  valuationSandbox: async (code: string, price: number,
    o: { rf?: number; beta?: number; erp?: number; g?: number; years?: number } = {},
  ): Promise<ValuationSandbox> => {
    const qs = new URLSearchParams({ price: String(price) });
    for (const [k, v] of Object.entries(o)) if (v != null) qs.set(k, String(v));
    const r = await fetch(`${API_BASE}/api/v1/company/${code}/valuation-sandbox?${qs}`);
    if (!r.ok) throw new Error(`valuation-sandbox failed: ${r.status}`);
    return r.json();
  },
```

- [ ] **Step 2: ValuationTab 컴포넌트** — `frontend/src/components/insights/ValuationTab.tsx`

핵심 구조 (전체 파일):

```tsx
"use client";
// ValuationTab — 실무 밸류에이션: Football Field + 가정 샌드박스 + Ke×g 민감도 + Comps.
// 마운트 시 1콜(valuationSandbox), 슬라이더 변경 시 디바운스 재호출.
import { useCallback, useEffect, useRef, useState } from "react";
import { companyApi, type ValuationSandbox } from "@/lib/screenerApi";

const fmtW = (v: number | null | undefined) =>
  v == null ? "—" : `₩${Math.round(v).toLocaleString()}`;

const SLIDERS: { key: "rf" | "beta" | "erp" | "g" | "years"; label: string;
  min: number; max: number; step: number; pct?: boolean }[] = [
  { key: "rf", label: "무위험수익률 Rf", min: 0.01, max: 0.08, step: 0.001, pct: true },
  { key: "beta", label: "베타 β", min: 0.3, max: 2.5, step: 0.05 },
  { key: "erp", label: "시장프리미엄 ERP", min: 0.03, max: 0.10, step: 0.001, pct: true },
  { key: "g", label: "영구성장률 g", min: 0.0, max: 0.04, step: 0.001, pct: true },
  { key: "years", label: "예측기간(년)", min: 5, max: 15, step: 1 },
];

export default function ValuationTab({ code, price }: { code: string; price: number }) {
  const [data, setData] = useState<ValuationSandbox | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ov, setOv] = useState<Record<string, number>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback((overrides: Record<string, number>) => {
    companyApi.valuationSandbox(code, price, overrides)
      .then(setData).catch((e) => setErr(String(e?.message ?? e)));
  }, [code, price]);

  useEffect(() => { load({}); }, [load]);
  const onSlide = (k: string, v: number) => {
    const next = { ...ov, [k]: v };
    setOv(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => load(next), 350);   // 디바운스 재평가
  };

  if (err) return <div className="ca-cp-note">밸류에이션 심화 로드 실패 — {err}</div>;
  if (!data) return <div className="ca-cp-note">불러오는 중…</div>;

  return (
    <div className="ca-vt">
      <FootballField ff={data.football_field} />
      <div className="ca-vt-grid">
        <AssumptionPanel data={data} ov={ov} onSlide={onSlide}
          onReset={() => { setOv({}); load({}); }} />
        <SensitivityHeatmap s={data.sensitivity} />
      </div>
      <CompsTable comps={data.comps} selfCode={code} />
    </div>
  );
}

function FootballField({ ff }: { ff: ValuationSandbox["football_field"] }) {
  const bands = ff.bands.filter((b) => b.available !== false && b.lo != null && b.hi != null);
  const unavailable = ff.bands.filter((b) => b.available === false);
  const values = [...bands.flatMap((b) => [b.lo!, b.hi!]), ff.current_price];
  const lo = Math.min(...values) * 0.95, hi = Math.max(...values) * 1.05;
  const X = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const H = bands.length * 34 + 20;
  return (
    <section className="ca-cp-sec">
      <h4>Valuation Football Field <span className="ca-cp-sub">현재가 대비 가치 밴드</span></h4>
      <svg viewBox={`0 0 100 ${H}`} preserveAspectRatio="none" className="ca-ff-svg"
        style={{ width: "100%", height: H * 2.2 }}>
        {bands.map((b, i) => {
          const y = 12 + i * 34;
          const x1 = X(b.lo!), x2 = Math.max(X(b.hi!), x1 + 0.6);
          return (
            <g key={b.id}>
              <rect x={x1} y={y} width={x2 - x1} height={14} rx={1}
                className={`ca-ff-band ca-ff-${b.id}`} />
              {b.mid != null && (
                <line x1={X(b.mid)} x2={X(b.mid)} y1={y - 1} y2={y + 15} className="ca-ff-mid" />
              )}
            </g>
          );
        })}
        <line x1={X(ff.current_price)} x2={X(ff.current_price)} y1={2} y2={H - 2}
          className="ca-ff-price" />
      </svg>
      <div className="ca-ff-legend">
        {bands.map((b) => (
          <span key={b.id} className="ca-ff-leg">
            <i className={`ca-ff-dot ca-ff-${b.id}`} />
            {b.label} <b>{fmtW(b.lo)}~{fmtW(b.hi)}</b>{b.note ? ` · ${b.note}` : ""}
          </span>
        ))}
        <span className="ca-ff-leg"><i className="ca-ff-dot ca-ff-cur" />현재가 <b>{fmtW(ff.current_price)}</b></span>
        {unavailable.map((b) => (
          <span key={b.id} className="ca-ff-leg ca-ff-na">{b.label}: {b.note}</span>
        ))}
      </div>
    </section>
  );
}

function AssumptionPanel({ data, ov, onSlide, onReset }: {
  data: ValuationSandbox; ov: Record<string, number>;
  onSlide: (k: string, v: number) => void; onReset: () => void;
}) {
  const byKey = Object.fromEntries(data.assumptions.map((a) => [a.key, a]));
  return (
    <section className="ca-cp-sec">
      <h4>가정 샌드박스 <button className="ca-vt-reset" onClick={onReset}>실측 기본값 복원</button></h4>
      {SLIDERS.map((s) => {
        const a = byKey[s.key];
        const cur = ov[s.key] ?? (a?.value as number) ?? s.min;
        return (
          <div key={s.key} className="ca-vt-slider">
            <div className="ca-vt-slabel">
              <span>{s.label}</span>
              <b>{s.pct ? `${(cur * 100).toFixed(1)}%` : cur}</b>
              <em className="ca-vt-src">{a?.source ?? ""}</em>
            </div>
            <input type="range" min={s.min} max={s.max} step={s.step} value={cur}
              onChange={(e) => onSlide(s.key, Number(e.target.value))} />
          </div>
        );
      })}
      <div className="ca-vt-derived">
        Ke(도출) <b>{((byKey["ke"]?.value as number) * 100).toFixed(2)}%</b> · 적정가{" "}
        <b>{fmtW(data.unified.value)}</b> · 괴리 <b>{data.unified.gap_pct.toFixed(1)}%</b> ·{" "}
        {data.unified.verdict}
      </div>
    </section>
  );
}

function SensitivityHeatmap({ s }: { s: ValuationSandbox["sensitivity"] }) {
  return (
    <section className="ca-cp-sec">
      <h4>민감도 매트릭스 <span className="ca-cp-sub">Ke(행) × g(열) — 파랑=현재가 대비 저평가</span></h4>
      <table className="ca-heat">
        <thead><tr><th>Ke \ g</th>{s.g_axis.map((g) => <th key={g}>{(g * 100).toFixed(1)}%</th>)}</tr></thead>
        <tbody>
          {s.grid.map((row, i) => (
            <tr key={i}>
              <th>{(s.ke_axis[i] * 100).toFixed(1)}%</th>
              {row.map((v, j) => {
                const cls = v == null ? "na" : v >= s.current_price ? "up" : "dn";
                return <td key={j} className={`ca-heat-c ${cls}`}
                  title={v == null ? "TV 발산 (g≈Ke)" : fmtW(v)}>
                  {v == null ? "—" : Math.round(v / 1000).toLocaleString() + "k"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function CompsTable({ comps, selfCode }: { comps: ValuationSandbox["comps"]; selfCode: string }) {
  if (!comps.rows.length) return null;
  const cols: { k: keyof typeof comps.rows[number]; label: string }[] = [
    { k: "mcap", label: "시총(억)" }, { k: "per", label: "PER" }, { k: "pbr", label: "PBR" },
    { k: "ev_ebitda", label: "EV/EBITDA" }, { k: "roe", label: "ROE%" },
    { k: "op_margin", label: "영업이익률%" }, { k: "rev_growth", label: "매출성장%" },
  ];
  const num = (v: unknown) => (typeof v === "number" ? v.toLocaleString() : "—");
  return (
    <section className="ca-cp-sec">
      <h4>Comps — 상대가치 매트릭스 <span className="ca-cp-sub">{comps.sector} 피어 {comps.rows.length - 1}개</span></h4>
      <div style={{ overflowX: "auto" }}>
        <table className="ca-comps">
          <thead><tr><th>기업</th>{cols.map((c) => <th key={c.k}>{c.label}</th>)}</tr></thead>
          <tbody>
            {comps.rows.map((r) => (
              <tr key={r.code} className={r.code === selfCode ? "self" : ""}>
                <td>{r.name}</td>{cols.map((c) => <td key={c.k}>{num(r[c.k])}</td>)}
              </tr>
            ))}
            <tr className="median"><td>피어 중간값</td>
              {cols.map((c) => <td key={c.k}>{num(comps.median_row[c.k])}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <div className="ca-comps-implied">
        중간값 재평가 암시가: PER 기준 <b>{fmtW(comps.implied.per_based)}</b> · PBR 기준{" "}
        <b>{fmtW(comps.implied.pbr_based)}</b> · EV/EBITDA 기준 <b>{fmtW(comps.implied.ev_ebitda_based)}</b>
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Cockpit 배선** — CompanyCockpit.tsx의 `{tab === "valuation" && (` 블록 최상단에 `<ValuationTab code={c.code} price={c.price} />` 삽입 (기존 모델 카드 콘텐츠는 아래 유지). import 추가.

- [ ] **Step 4: CSS** — globals.css 말미에 추가 (기존 ca-cp-* 톤 준수):

```css
/* ── 기업분석 심화: Football Field / 히트맵 / Comps ── */
.ca-vt-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 900px) { .ca-vt-grid { grid-template-columns: 1fr; } }
.ca-ff-svg { display: block; }
.ca-ff-band { opacity: .75; }
.ca-ff-dcf { fill: #1200ff; } .ca-ff-rim { fill: #0e7c4a; } .ca-ff-ddm { fill: #8a6d00; }
.ca-ff-w52 { fill: #71717a; } .ca-ff-graham { fill: #b0325a; }
.ca-ff-peer_per { fill: #4a5fc1; } .ca-ff-peer_pbr { fill: #2a8f9d; }
.ca-ff-mid { stroke: #111; stroke-width: .4; }
.ca-ff-price { stroke: #d00; stroke-width: .6; stroke-dasharray: 2 1.4; }
.ca-ff-legend { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 11px; margin-top: 8px; }
.ca-ff-dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }
.ca-ff-dot.ca-ff-cur { background: #d00; }
i.ca-ff-dot.ca-ff-dcf { background:#1200ff } i.ca-ff-dot.ca-ff-rim { background:#0e7c4a }
i.ca-ff-dot.ca-ff-ddm { background:#8a6d00 } i.ca-ff-dot.ca-ff-w52 { background:#71717a }
i.ca-ff-dot.ca-ff-graham { background:#b0325a }
i.ca-ff-dot.ca-ff-peer_per { background:#4a5fc1 } i.ca-ff-dot.ca-ff-peer_pbr { background:#2a8f9d }
.ca-ff-na { color: var(--muted, #71717a); font-style: italic; }
.ca-vt-slider input[type="range"] { width: 100%; }
.ca-vt-slabel { display: flex; gap: 8px; font-size: 12px; align-items: baseline; }
.ca-vt-slabel .ca-vt-src { margin-left: auto; font-size: 10px; color: var(--muted, #71717a); }
.ca-vt-reset { font-size: 11px; margin-left: 10px; cursor: pointer; }
.ca-vt-derived { margin-top: 10px; font-size: 12px; }
.ca-heat { border-collapse: collapse; font-size: 11px; font-family: var(--bs-font-mono, monospace); }
.ca-heat th, .ca-heat td { border: 1px solid var(--border, #e5e5e5); padding: 4px 8px; text-align: right; }
.ca-heat-c.dn { background: rgba(18, 0, 255, .10); }   /* 내재가치 < 현재가 → 고평가 방향 */
.ca-heat-c.up { background: rgba(14, 124, 74, .14); }  /* 내재가치 ≥ 현재가 → 저평가 방향 */
.ca-heat-c.na { color: var(--muted, #71717a); }
.ca-comps { border-collapse: collapse; font-size: 12px; width: 100%; }
.ca-comps th, .ca-comps td { border-bottom: 1px solid var(--border, #e5e5e5); padding: 5px 8px; text-align: right; }
.ca-comps td:first-child, .ca-comps th:first-child { text-align: left; }
.ca-comps tr.self { background: rgba(18, 0, 255, .06); font-weight: 600; }
.ca-comps tr.median { background: var(--surface, #fafafa); font-weight: 600; }
.ca-comps-implied { margin-top: 8px; font-size: 12px; }
```

주의: `.ca-heat-c.up`는 "내재가치 ≥ 현재가"(=업사이드) 칸이며 초록, `.dn`은 파랑 계열 — 히트맵 헤더 문구와 색 일치 확인.

- [ ] **Step 5: 검증 + 커밋**

```bash
cd frontend && npx tsc --noEmit && npx next build && cd ..
git add frontend/src/components/insights/ValuationTab.tsx frontend/src/components/insights/CompanyCockpit.tsx frontend/src/lib/screenerApi.ts frontend/src/app/globals.css
git commit -m "feat(company): Valuation 탭 — Football Field·가정 샌드박스·민감도 히트맵·Comps"
```

---

### Task 4: financial_deep 백엔드 (QoE·NWC·워터폴·듀폰) + API (TDD)

**Files:**
- Modify: `src/engine/company_analytics.py` (financial_deep 추가)
- Modify: `src/api/company_routes.py` (/financial-deep)
- Test: `tests/test_company_analytics.py` (추가), `tests/test_company_routes.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가** — test_company_analytics.py 말미

```python
# ── financial_deep (합성 financials_history로 수식 검증) ──

def _install_history(monkeypatch, rows):
    import src.engine.company_analytics as camod
    monkeypatch.setattr(camod, "_annual_rows", lambda code: rows)


def _year(y, rev, op, ni, ta, tl, te, ca_, cl, ocf, capex, shares, dps):
    return {"year": y, "reprt": "11011", "revenue": rev, "operating_profit": op,
            "net_income": ni, "total_assets": ta, "total_liabilities": tl,
            "total_equity": te, "current_assets": ca_, "current_liabilities": cl,
            "operating_cf": ocf, "capex": capex, "shares_outstanding": shares,
            "dps": dps, "gross_profit": rev * 0.3}


def test_dupont_product_equals_roe(monkeypatch):
    rows = [_year(2022 + i, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8,
                  700e8, 400e8, 90e8, 30e8, 5000, 100) for i in range(3)]
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900100")
    d = out["dupont"]
    for i in range(len(d["years"])):
        prod = d["net_margin"][i] / 100 * d["asset_turnover"][i] * d["leverage"][i]
        assert abs(prod * 100 - d["roe"][i]) < 0.5, "듀폰 곱 ≠ ROE"


def test_nwc_and_waterfall_identity(monkeypatch):
    rows = [_year(2023, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  90e8, 30e8, 5000, 100),
            _year(2024, 1100e8, 120e8, 95e8, 2100e8, 850e8, 1250e8, 720e8, 410e8,
                  110e8, 35e8, 5000, 120)]
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900101")
    assert out["nwc"]["nwc"][-1] == pytest.approx((720e8 - 410e8) / 1e8)
    w = out["waterfall"]
    i = len(w["years"]) - 1
    # OCF - CapEx - 배당 - 부채상환(감소분) = 잔여 (항등식)
    assert w["residual"][i] == pytest.approx(
        w["ocf"][i] - w["capex"][i] - w["dividends"][i] - max(0.0, -w["debt_delta"][i]), abs=0.5)


def test_qoe_red_flag_fires_when_ocf_below_ni(monkeypatch):
    rows = [_year(2021 + i, 1000e8, 100e8, 90e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  40e8, 30e8, 5000, 100) for i in range(4)]   # OCF 40 < NI 90 매년
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900102")
    assert any(f["rule"] == "R1" for f in out["qoe"]["red_flags"])


def test_qoe_no_flag_when_healthy(monkeypatch):
    rows = [_year(2021 + i, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  120e8, 30e8, 5000, 100) for i in range(4)]  # OCF 120 > NI 80
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900103")
    assert not any(f["rule"] == "R1" for f in out["qoe"]["red_flags"])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_company_analytics.py -q`
Expected: 신규 4개 FAIL (`_annual_rows`/`financial_deep` 없음)

- [ ] **Step 3: 구현** — company_analytics.py에 추가

```python
def _annual_rows(code: str) -> list[dict]:
    """financials_history 연간 행(원 단위, 과거→최근). 미적재면 []."""
    try:
        from src.data.dart_history import REPRT_ANNUAL, load_history
        return [r for r in load_history(str(code)) if r.get("reprt") == REPRT_ANNUAL]
    except Exception:
        return []


def _v(row, key):
    x = row.get(key)
    return float(x) if isinstance(x, (int, float)) else None


def financial_deep(code: str) -> dict:
    """QoE·NWC·자본배치 워터폴·듀폰 — financials_history 연간(최대 10년, 억 단위 반환)."""
    rows = _annual_rows(code)[-10:]
    if not rows:
        return {"available": False, "note": "재무 시계열 미적재 — Data Infra에서 '재무시계열' 적재 후 표시",
                "qoe": {"years": [], "red_flags": []}, "nwc": {"years": []},
                "waterfall": {"years": []}, "dupont": {"years": []}, "roic_wacc": None}
    E8 = 1e8
    years = [int(r["year"]) for r in rows]

    ni = [(_v(r, "net_income") or 0) / E8 for r in rows]
    ocf = [(_v(r, "operating_cf") or 0) / E8 for r in rows]
    ta = [(_v(r, "total_assets") or 0) / E8 for r in rows]
    accr = [round((n - o) / t * 100, 2) if t else None for n, o, t in zip(ni, ocf, ta)]
    gap = [round(o - n, 1) for n, o in zip(ni, ocf)]

    red: list[dict] = []
    if len(rows) >= 3 and all(o < n for o, n in zip(ocf[-3:], ni[-3:])):
        red.append({"rule": "R1", "severity": "bad",
                    "msg": "OCF < 순이익 3년 연속 — 보고이익이 현금으로 뒷받침되지 않음"})
    accr3 = [a for a in accr[-3:] if a is not None]
    if len(accr3) == 3 and accr3[0] < accr3[1] < accr3[2]:
        red.append({"rule": "R2", "severity": "warn",
                    "msg": "발생액 비율 3년 연속 상승 — 이익의 질 저하 신호"})

    nwc = [round(((_v(r, "current_assets") or 0) - (_v(r, "current_liabilities") or 0)) / E8, 1)
           for r in rows]
    rev = [(_v(r, "revenue") or 0) / E8 for r in rows]
    nwc_ratio = [round(n / v * 100, 1) if v else None for n, v in zip(nwc, rev)]
    r3 = [x for x in nwc_ratio[-3:] if x is not None]
    if len(r3) == 3 and r3[0] < r3[1] < r3[2]:
        red.append({"rule": "R3", "severity": "warn",
                    "msg": "NWC/매출 3년 연속 상승 — 운전자본 잠김 심화(현금전환 악화)"})

    capex = [abs(_v(r, "capex") or 0) / E8 for r in rows]
    div = [round(((_v(r, "dps") or 0) * (_v(r, "shares_outstanding") or 0)) / 1e4, 1)
           for r in rows]   # dps(원/주) × shares(만주 가정: 원천이 주 단위면 스케일 확인 필요 → Step4 검증)
    tl = [(_v(r, "total_liabilities") or 0) / E8 for r in rows]
    debt_delta = [None] + [round(tl[i] - tl[i - 1], 1) for i in range(1, len(tl))]
    residual = []
    for i in range(len(rows)):
        repay = max(0.0, -(debt_delta[i] or 0.0))
        residual.append(round(ocf[i] - capex[i] - div[i] - repay, 1))

    te = [(_v(r, "total_equity") or 0) / E8 for r in rows]
    dupont = {"years": years,
              "net_margin": [round(n / v * 100, 2) if v else None for n, v in zip(ni, rev)],
              "asset_turnover": [round(v / t, 3) if t else None for v, t in zip(rev, ta)],
              "leverage": [round(t / e, 3) if e else None for t, e in zip(ta, te)],
              "roe": [round(n / e * 100, 2) if e else None for n, e in zip(ni, te)]}

    roic_wacc = None
    try:
        from src.data.fundamentals_store import FundamentalsStore
        roic = FundamentalsStore.get_default().get_factors(code).get("roic")
        d = resolve_default_params(code)
        ke = d["rf"] + d["beta"] * d["erp"]
        ev = te[-1] + tl[-1]
        wacc = (ke * (te[-1] / ev) + (d["rf"] + 0.02) * 0.78 * (tl[-1] / ev)) if ev else ke
        if roic is not None:
            spread = round(float(roic) - wacc * 100, 2)
            roic_wacc = {"roic": round(float(roic), 2), "wacc": round(wacc * 100, 2),
                         "spread": spread, "note": "Kd=Rf+2%p 근사",
                         "verdict": "가치 창출 (ROIC > WACC)" if spread > 0 else "가치 훼손 (ROIC < WACC)"}
    except Exception:
        pass

    return {"available": True,
            "qoe": {"years": years, "ni": [round(x, 1) for x in ni],
                    "ocf": [round(x, 1) for x in ocf], "gap": gap, "accruals": accr,
                    "red_flags": red},
            "nwc": {"years": years, "nwc": nwc, "nwc_to_rev_pct": nwc_ratio},
            "waterfall": {"years": years, "ocf": [round(x, 1) for x in ocf],
                          "capex": [round(x, 1) for x in capex], "dividends": div,
                          "debt_delta": debt_delta, "residual": residual,
                          "note": "자사주 매입 데이터 미보유 — 항목 제외"},
            "dupont": dupont, "roic_wacc": roic_wacc}
```

API 추가 (company_routes.py):

```python
@router.get("/{code}/financial-deep")
def company_financial_deep(code: str):
    try:
        from src.engine import company_analytics as ca
        return ca.financial_deep(code)
    except Exception:
        logger.exception("financial-deep 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
```

- [ ] **Step 4: 배당 스케일 검증(실데이터 계약)** — dps는 원/주, shares_outstanding은 DART가 '주' 단위로 백필함. `div_억 = dps × shares / 1e8`. 위 코드의 `/1e4`는 만주 가정이므로 **백필 원천 확인 후 하나로 통일**: `python - <<'EOF'` 로 GCP가 아닌 로컬 mock에서 shares_outstanding 스케일을 financials_history 백필 코드(dart_client가 채우는 값)로 역추적 → dart_client는 fs.shares_outstanding(주)를 그대로 저장 → **`/1e8`이 맞음**. 코드 확정: `div = [round(((dps or 0) * (shares or 0)) / 1e8, 1)]`. 테스트 `_year(..., shares=5000, dps=100)` → 5000주×100원=50만원=0.005억 — 테스트 항등식은 스케일 무관(왕복 동일 수식)이라 통과 기준 유지.

- [ ] **Step 5: smoke 테스트 추가 + 통과 + 커밋**

test_company_routes.py 말미:

```python
def test_financial_deep_endpoint():
    r = client.get("/api/v1/company/005930/financial-deep")
    assert r.status_code == 200
    assert {"qoe", "nwc", "waterfall", "dupont"} <= set(r.json())
```

```bash
python -m pytest tests/test_company_analytics.py tests/test_company_routes.py -q   # 전부 통과
ruff check src/engine/company_analytics.py src/api/company_routes.py
git add -A && git commit -m "feat(company): financial-deep — QoE·NWC·워터폴·듀폰 (TDD)"
```

---

### Task 5: FinancialsDeepTab UI

**Files:**
- Create: `frontend/src/components/insights/FinancialsDeepTab.tsx`
- Modify: `frontend/src/lib/screenerApi.ts` (financialDeep 메서드+타입), `CompanyCockpit.tsx` (financials 탭 상단), `globals.css` (ca-fd-*)

- [ ] **Step 1: 클라이언트** — screenerApi.ts companyApi에:

```typescript
export interface FinancialDeep {
  available: boolean; note?: string;
  qoe: { years: number[]; ni: number[]; ocf: number[]; gap: number[];
    accruals: (number | null)[]; red_flags: { rule: string; severity: string; msg: string }[] };
  nwc: { years: number[]; nwc: number[]; nwc_to_rev_pct: (number | null)[] };
  waterfall: { years: number[]; ocf: number[]; capex: number[]; dividends: number[];
    debt_delta: (number | null)[]; residual: number[]; note: string };
  dupont: { years: number[]; net_margin: (number | null)[]; asset_turnover: (number | null)[];
    leverage: (number | null)[]; roe: (number | null)[] };
  roic_wacc: { roic: number; wacc: number; spread: number; verdict: string; note: string } | null;
}
```
```typescript
  financialDeep: async (code: string): Promise<FinancialDeep> => {
    const r = await fetch(`${API_BASE}/api/v1/company/${code}/financial-deep`);
    if (!r.ok) throw new Error(`financial-deep failed: ${r.status}`);
    return r.json();
  },
```

- [ ] **Step 2: 컴포넌트** — FinancialsDeepTab.tsx (구조: QoE 오버레이 라인차트 SVG(NI 실선·OCF 점선, 갭 영역) + Red Flag 배지 목록 + NWC 이중축 미니차트 + 워터폴(연도 선택 셀렉트 → 해당 연도 가로 바: OCF→CapEx→배당→부채상환→잔여) + 듀폰 접이식(3지표 미니라인+ROE) + ROIC−WACC 한줄 카드). 로딩/에러/미적재(`available:false` → note 그대로 렌더) 처리. `useEffect`로 마운트 시 1콜. 코드는 ValuationTab과 동일 관례 (fmt 함수·ca-cp-sec 섹션·자체 SVG polyline).

핵심 SVG 헬퍼 (파일 내):

```tsx
function MiniLine({ years, series }: { years: number[]; series: { vals: (number | null)[]; cls: string; dash?: boolean }[] }) {
  const all = series.flatMap((s) => s.vals.filter((v): v is number => v != null));
  if (!all.length) return <div className="ca-cp-note">데이터 없음</div>;
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const X = (i: number) => (i / Math.max(1, years.length - 1)) * 100;
  const Y = (v: number) => 30 - ((v - lo) / span) * 28;
  return (
    <svg viewBox="0 0 100 34" className="ca-fd-mini" preserveAspectRatio="none">
      {series.map((s, k) => (
        <polyline key={k} className={s.cls} fill="none"
          strokeDasharray={s.dash ? "2 1.5" : undefined}
          points={s.vals.map((v, i) => (v == null ? "" : `${X(i)},${Y(v)}`)).join(" ")} />
      ))}
    </svg>
  );
}
```

- [ ] **Step 3: Cockpit 배선 + CSS + 검증 + 커밋**

`{tab === "financials" && (` 블록 상단에 `<FinancialsDeepTab code={c.code} />`. CSS: `.ca-fd-mini { width:100%; height:76px } .ca-fd-ni { stroke:#111; stroke-width:.8 } .ca-fd-ocf { stroke:#1200ff; stroke-width:.8 } .ca-fd-flag { display:inline-block; padding:2px 8px; border-radius:2px; font-size:11px; margin:2px 6px 2px 0 } .ca-fd-flag.bad { background:#fde8e8; color:#b0325a } .ca-fd-flag.warn { background:#fdf3e0; color:#8a6d00 } .ca-fd-wf-bar { display:flex; align-items:center; gap:8px; font-size:12px }` 등.

```bash
cd frontend && npx tsc --noEmit && npx next build && cd ..
git add -A && git commit -m "feat(company): Financials 탭 — QoE·NWC·워터폴·듀폰 UI"
```

---

### Task 6: risk_deep 백엔드+UI + 전체 검증 + 푸시

**Files:**
- Modify: `src/engine/company_analytics.py` (risk_deep), `src/api/company_routes.py` (/risk-deep)
- Create: `frontend/src/components/insights/RiskDeepTab.tsx`
- Modify: `screenerApi.ts`, `CompanyCockpit.tsx`, `globals.css`, `CLAUDE.md`
- Test: 기존 두 테스트 파일에 추가

- [ ] **Step 1: 실패하는 테스트 추가** — test_company_analytics.py

```python
# ── risk_deep ──

def test_altman_contributions_sum_to_z():
    out = ca.risk_deep(CODE, PRICE)
    alt = out["altman"]
    s = sum(c["contribution"] for c in alt["components"])
    assert abs(s - alt["z"]) < 0.05


def test_beneish_labels_and_score(monkeypatch):
    rows = [_year(2023, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  90e8, 30e8, 5000, 100),
            _year(2024, 1300e8, 120e8, 95e8, 2100e8, 900e8, 1200e8, 720e8, 410e8,
                  60e8, 35e8, 5000, 120)]
    _install_history(monkeypatch, rows)
    out = ca.risk_deep("900200", PRICE)
    b = out["beneish"]
    assert b["available"] is True
    basis = {i["id"]: i["basis"] for i in b["indices"]}
    assert basis["sgi"] == "real" and basis["dsri"] == "neutral" and basis["aqi"] == "approx"
    sgi = next(i for i in b["indices"] if i["id"] == "sgi")
    assert sgi["value"] == pytest.approx(1.3, abs=0.01)


def test_beneish_unavailable_without_prev_year(monkeypatch):
    rows = [_year(2024, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  90e8, 30e8, 5000, 100)]
    _install_history(monkeypatch, rows)
    out = ca.risk_deep("900201", PRICE)
    assert out["beneish"]["available"] is False


def test_rate_stress_direction():
    out = ca.risk_deep(CODE, PRICE)
    rows = out["rate_stress"]["rows"]
    ics = [r["interest_coverage"] for r in rows if r["interest_coverage"] is not None]
    assert ics == sorted(ics, reverse=True), "금리 충격이 커질수록 커버리지는 하락해야"
```

- [ ] **Step 2: 실패 확인** → `python -m pytest tests/test_company_analytics.py -q` (신규 4 FAIL)

- [ ] **Step 3: 구현** — company_analytics.py 추가

```python
_BENEISH_COEF = {"dsri": 0.92, "gmi": 0.528, "aqi": 0.404, "sgi": 0.892,
                 "depi": 0.115, "sgai": -0.172, "tata": 4.679, "lvgi": -0.327}
_BENEISH_LABEL = {"dsri": "매출채권 지수", "gmi": "매출총이익률 지수", "aqi": "자산의 질 지수",
                  "sgi": "매출성장 지수", "depi": "감가상각률 지수", "sgai": "판관비 지수",
                  "tata": "총발생액/총자산", "lvgi": "레버리지 지수"}


def risk_deep(code: str, price: float) -> dict:
    """Altman 분해 · Beneish 실측 8지수 · 커버리지 추이 · 금리 스트레스."""
    # ① Altman 분해 — 팩터와 동일 원천(get_raw_financials, 억)으로 X1~X5 재구성
    altman = {"z": None, "zone": None, "components": []}
    try:
        from src.data.fundamentals_store import FundamentalsStore
        r = FundamentalsStore.get_default().get_raw_financials(code)
        ta = r["total_assets"]
        wc = (r["current_assets"] or 0) - (r["current_liabilities"] or 0)
        comps = [("x1", "운전자본/총자산", 1.2, wc / ta if ta else 0),
                 ("x2", "이익잉여금(근사)/총자산", 1.4, (r["net_income"] * 0.6) / ta if ta else 0),
                 ("x3", "영업이익/총자산", 3.3, r["operating_profit"] / ta if ta else 0),
                 ("x4", "시총/총부채", 0.6, (r["market_cap"] / r["total_liabilities"])
                  if r.get("total_liabilities") else 0),
                 ("x5", "매출/총자산", 1.0, r["revenue"] / ta if ta else 0)]
        z = sum(w * v for _, _, w, v in comps)
        zone = "안전 (>3.0)" if z > 3 else ("회색지대 (1.8~3.0)" if z > 1.8 else "위험 (<1.8)")
        altman = {"z": round(z, 2), "zone": zone,
                  "components": [{"id": i, "label": lb, "weight": w, "value": round(v, 3),
                                  "contribution": round(w * v, 3)} for i, lb, w, v in comps]}
    except Exception as e:
        logger.debug(f"altman 분해 실패 [{code}]: {e}")

    # ② Beneish 8지수 — 당년/전년 연간 재무. 원천 없는 지수는 중립 1.0 + 라벨(정직)
    rows = _annual_rows(code)[-2:]
    if len(rows) < 2:
        beneish = {"available": False, "note": "전년 재무 미적재 — 지수 산출 불가",
                   "m_score": None, "flag": None, "indices": []}
    else:
        p, c = rows[0], rows[1]
        def sd(a, b):
            return (a / b) if (a is not None and b not in (None, 0, 0.0)) else None
        gm_c = sd(_v(c, "gross_profit"), _v(c, "revenue"))
        gm_p = sd(_v(p, "gross_profit"), _v(p, "revenue"))
        idx: dict[str, tuple[float, str]] = {
            "dsri": (1.0, "neutral"), "depi": (1.0, "neutral"), "sgai": (1.0, "neutral"),
            "gmi": ((gm_p / gm_c) if (gm_p and gm_c) else 1.0, "real" if (gm_p and gm_c) else "neutral"),
            "sgi": (sd(_v(c, "revenue"), _v(p, "revenue")) or 1.0,
                    "real" if sd(_v(c, "revenue"), _v(p, "revenue")) else "neutral"),
            "lvgi": ((sd(_v(c, "total_liabilities"), _v(c, "total_assets")) or 0) /
                     (sd(_v(p, "total_liabilities"), _v(p, "total_assets")) or 1)
                     if sd(_v(p, "total_liabilities"), _v(p, "total_assets")) else 1.0, "real"),
            "tata": (((_v(c, "net_income") or 0) - (_v(c, "operating_cf") or 0)) /
                     (_v(c, "total_assets") or 1), "real"),
        }
        aqi_c = 1 - (sd(_v(c, "current_assets"), _v(c, "total_assets")) or 0)
        aqi_p = 1 - (sd(_v(p, "current_assets"), _v(p, "total_assets")) or 0)
        idx["aqi"] = ((aqi_c / aqi_p) if aqi_p else 1.0, "approx")
        m = -4.84 + sum(_BENEISH_COEF[k] * v for k, (v, _) in idx.items())
        beneish = {"available": True, "m_score": round(m, 2),
                   "flag": "조작 위험 신호 (M > -1.78)" if m > -1.78 else "안전 지대",
                   "indices": [{"id": k, "label": _BENEISH_LABEL[k], "value": round(v, 3),
                                "basis": basis} for k, (v, basis) in idx.items()],
                   "note": "매출채권·감가상각·판관비 원천 미보유 → 해당 지수 중립(1.0) 처리"}

    # ③ 커버리지 추이 (근사 라벨) + ④ 금리 스트레스
    d = resolve_default_params(code)
    base_rate = d["rf"] + 0.02   # Kd 근사
    hist = _annual_rows(code)[-10:]
    years, ic_series, nd_series = [], [], []
    for r0 in hist:
        op, tl = _v(r0, "operating_profit"), _v(r0, "total_liabilities")
        rev0, ca0 = _v(r0, "revenue"), _v(r0, "current_assets")
        years.append(int(r0["year"]))
        ic_series.append(round(op / (tl * base_rate), 2) if (op and tl) else None)
        ebitda = (op or 0) + (rev0 or 0) * 0.05
        net_debt = (tl or 0) - (ca0 or 0) * 0.25
        nd_series.append(round(net_debt / ebitda, 2) if ebitda > 0 else None)
    coverage = {"years": years, "interest_coverage": ic_series,
                "net_debt_to_ebitda": nd_series,
                "note": "이자비용=총부채×(Rf+2%p)·현금=유동자산×25%·EBITDA=영업이익+매출×5% 근사"}

    stress_rows = []
    last = hist[-1] if hist else None
    eng, mcap = _engine(), _mcap(code)
    for bp in (0, 100, 200, 300):
        ic = None
        if last and _v(last, "operating_profit") and _v(last, "total_liabilities"):
            ic = round(_v(last, "operating_profit") /
                       (_v(last, "total_liabilities") * (base_rate + bp / 1e4)), 2)
        try:
            rr = eng.evaluate(code, price, params=_make_params(d["rf"] + bp / 1e4, d["beta"],
                              d["erp"], d["g"], d["years"]), market_cap=mcap)
            dcf = next((m.intrinsic_value_per_share for m in rr.models
                        if m.model == "DCF" and m.available), None)
            uni = rr.intrinsic_value if rr.intrinsic_value > 0 else None
        except Exception:
            dcf = uni = None
        stress_rows.append({"shock_bp": bp, "interest_coverage": ic,
                            "dcf_value": round(dcf, 0) if dcf else None,
                            "unified_value": round(uni, 0) if uni else None})
    return {"altman": altman, "beneish": beneish, "coverage": coverage,
            "rate_stress": {"rows": stress_rows, "note": "충격=할인율 전체 평행이동(+Kd)"}}
```

API (company_routes.py):

```python
@router.get("/{code}/risk-deep")
def company_risk_deep(code: str, price: float = Query(..., gt=0)):
    try:
        from src.engine import company_analytics as ca
        return ca.risk_deep(code, price)
    except Exception:
        logger.exception("risk-deep 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
```

smoke (test_company_routes.py): `client.get("/api/v1/company/005930/risk-deep", params={"price": 70000})` → 200 + `{"altman","beneish","coverage","rate_stress"} <= keys`.

- [ ] **Step 4: RiskDeepTab.tsx** — 구성: Altman 기여도 가로바(components.map — 값×가중치, zone 배지) + Beneish 표(8행: 지수·값·basis 배지(real=초록/approx=노랑/neutral=회색), M-Score 헤더+flag) + 커버리지 2계열 MiniLine(Task 5의 것과 동일 헬퍼 복제) + 스트레스 표(4행: shock_bp·커버리지·DCF·통합). screenerApi에 `riskDeep(code, price)` + `RiskDeep` 타입. Cockpit `{tab === "risk" && (` 상단 배선. CSS `.ca-rd-*`.

- [ ] **Step 5: 전체 검증 + CLAUDE.md + 커밋 + 푸시**

```bash
python -m pytest tests/ -q                      # 기존 733 + 신규 ≈16 전부 통과
ruff check src/ tests/
cd frontend && npx tsc --noEmit && npx next build && cd ..
# CLAUDE.md에 요약 섹션 추가 (기존 관례)
git add -A && git commit -m "feat(company): Risk 탭 — Altman 분해·Beneish 8지수·커버리지·금리 스트레스"
git push -u origin claude/keen-thompson-bdk3e8
```

---

## Self-Review 결과
- 스펙 커버리지: Valuation(FF·샌드박스·민감도·Comps)=T1~3, Financials(QoE·NWC·워터폴·듀폰·ROIC−WACC)=T4~5, Risk(Altman·Beneish·커버리지·스트레스)=T6. 누락 없음.
- 플레이스홀더: Task 5 Step 2가 구조 서술 — MiniLine 코드 포함으로 보강 완료. 나머지 코드 블록 완전.
- 타입 일관성: FootballBand/CompsRow/FinancialDeep 등 프론트 타입이 백엔드 dict 키와 일치 확인(available/note/basis 등).
- 주의: Task 4 Step 4의 배당 스케일(주 단위 → /1e8)은 구현 시 최종 확정 — 테스트는 스케일 무관 항등식.
