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
    """QoE·NWC·자본배치 워터폴·듀폰 — financials_history 연간(최대 10년, 억 단위 반환).

    Red Flag 규칙(FDD 관례):
      R1 OCF<NI 3년 연속 · R2 발생액비율 3년 상승 · R3 NWC/매출 3년 상승."""
    rows = _annual_rows(code)[-10:]
    if not rows:
        return {"available": False,
                "note": "재무 시계열 미적재 — Data Infra에서 '재무시계열' 적재 후 표시",
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
    # 배당(억) = dps(원/주) × 발행주식수(주) / 1e8 — dart_client가 주 단위로 백필함
    div = [round(((_v(r, "dps") or 0) * (_v(r, "shares_outstanding") or 0)) / E8, 1)
           for r in rows]
    tl = [(_v(r, "total_liabilities") or 0) / E8 for r in rows]
    debt_delta: list[float | None] = [None] + [round(tl[i] - tl[i - 1], 1)
                                               for i in range(1, len(tl))]
    residual = []
    for i in range(len(rows)):
        repay = max(0.0, -(debt_delta[i] or 0.0))   # 부채 감소분만 '상환' 지출로
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
                         "verdict": "가치 창출 (ROIC > WACC)" if spread > 0
                         else "가치 훼손 (ROIC < WACC)"}
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


_BENEISH_COEF = {"dsri": 0.92, "gmi": 0.528, "aqi": 0.404, "sgi": 0.892,
                 "depi": 0.115, "sgai": -0.172, "tata": 4.679, "lvgi": -0.327}
_BENEISH_LABEL = {"dsri": "매출채권 지수", "gmi": "매출총이익률 지수", "aqi": "자산의 질 지수",
                  "sgi": "매출성장 지수", "depi": "감가상각률 지수", "sgai": "판관비 지수",
                  "tata": "총발생액/총자산", "lvgi": "레버리지 지수"}


def risk_deep(code: str, price: float) -> dict:
    """Altman 분해 · Beneish 실측 8지수 · 커버리지 추이 · 금리 스트레스.

    Beneish: 원천 있는 지수(GMI/SGI/LVGI/TATA + AQI 근사)만 실측, 매출채권·감가상각·
    판관비 지수는 중립 1.0 + 라벨(정직). 근사값엔 근사 라벨."""
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

    # ② Beneish 8지수 — 당년/전년 연간 재무
    rows2 = _annual_rows(code)[-2:]
    if len(rows2) < 2:
        beneish = {"available": False, "note": "전년 재무 미적재 — 지수 산출 불가",
                   "m_score": None, "flag": None, "indices": []}
    else:
        p, c = rows2[0], rows2[1]

        def sd(a, b):
            return (a / b) if (a is not None and b not in (None, 0, 0.0)) else None
        gm_c = sd(_v(c, "gross_profit"), _v(c, "revenue"))
        gm_p = sd(_v(p, "gross_profit"), _v(p, "revenue"))
        sgi_v = sd(_v(c, "revenue"), _v(p, "revenue"))
        lvg_p = sd(_v(p, "total_liabilities"), _v(p, "total_assets"))
        lvg_c = sd(_v(c, "total_liabilities"), _v(c, "total_assets"))
        idx: dict[str, tuple[float, str]] = {
            "dsri": (1.0, "neutral"), "depi": (1.0, "neutral"), "sgai": (1.0, "neutral"),
            "gmi": ((gm_p / gm_c) if (gm_p and gm_c) else 1.0,
                    "real" if (gm_p and gm_c) else "neutral"),
            "sgi": (sgi_v or 1.0, "real" if sgi_v else "neutral"),
            "lvgi": ((lvg_c / lvg_p) if (lvg_c and lvg_p) else 1.0,
                     "real" if (lvg_c and lvg_p) else "neutral"),
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
