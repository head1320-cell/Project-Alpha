"""기업분석 심화 — FAS/DD 실무 산출물 (스펙 2026-07-09).

순수 계산 모듈: Valuation 샌드박스·민감도·Football Field·Comps (+ Task4/6에서
financial_deep·risk_deep 추가). 기존 ValuationEngine(RIM/DCF/DDM)·financials_history·
팩터 스토어를 재사용하며, 모든 산출 불가 항목은 available:false + note(사유)로
정직하게 표기한다.
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
    g ≥ ke − 0.5%p 칸은 TV 발산 → None(정직)."""
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
        {"key": "ke", "label": "자기자본비용 Ke (도출)", "value": round(ke, 4),
         "source": "CAPM: Rf+β·ERP"},
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
        peers = list(comps["rows"][1:])

        def _quart(key):
            vals = sorted(v[key] for v in peers
                          if isinstance(v.get(key), (int, float)) and v[key] > 0)
            if len(vals) < 3:
                return None
            return vals[len(vals) // 4], vals[(3 * len(vals)) // 4]
        qp, qb = _quart("per"), _quart("pbr")
        if qp and eps and eps > 0:
            bands.append({"id": "peer_per", "label": "피어 PER 25~75분위 암시가",
                          "available": True, "lo": round(qp[0] * eps, 0),
                          "hi": round(qp[1] * eps, 0), "mid": None,
                          "note": f"피어 {len(peers)}개"})
        if qb and bps and bps > 0:
            bands.append({"id": "peer_pbr", "label": "피어 PBR 25~75분위 암시가",
                          "available": True, "lo": round(qb[0] * bps, 0),
                          "hi": round(qb[1] * bps, 0), "mid": None,
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
