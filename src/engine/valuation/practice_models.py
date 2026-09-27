"""기업 분석 현업 모델 — EVA·가치 동인 · 가치의 층(Greenwald) · 배수·PEG·정당 배수 · 영업 동인 몬테카를로 (BL3 W3b)
==============================================================================
모두 **순수 함수**다 — 재무제표(`FinancialStatement`)·가정(`ValuationParams`)을 받아 결과 dict 를 낸다. 데이터를 가져오는
일은 `src/api/company_model_routes.py` 가 한다(DART·mock 게이트).

## 공통 규칙 (CLAUDE.md §2·§4 — 결론은 증거보다 강할 수 없다)
- 결과마다 `inputs: [{key, label, value, basis, source}]` — `basis` 는 **관측**(재무제표에서 읽음) · **근사**(재무 항목으로 대신함) ·
  **가정**(사람이 정함) · **미상**(모름 — 0 이 아니다) 중 하나.
- ★확률·가중은 조용히 정규화하지 않는다★ — 합이 1 이 아니면 계산하지 않고 그렇게 말한다.
- ★분수·나눗셈에 음수·0 이 들어갈 자리는 가드한다★ — 적자 기업에서만 터지는 결함(mock 은 늘 흑자).
- WACC 는 가치평가에 쓰이는 **DCF 엔진의 식**을 그대로 쓴다(`dcf_wacc` — 테스트가 `compute_dcf` 와 대조한다).
  저장소에는 식이 하나 더 있다(`company_analytics.financial_deep` 의 ROIC−WACC 카드: Kd=Rf+2%p·0.78). 두 벌을 통일하는 것은 값이
  바뀌는 모델 변경이라 여기서 하지 않는다 — 설명에 적는다.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from src.engine.valuation.valuation_models import ValuationParams

OBSERVED, APPROX, ASSUMED, UNKNOWN = "관측", "근사", "가정", "미상"
WACC_NOTE = ("WACC 는 DCF 엔진과 같은 식(Kd=Rf+1.5%p · 세율 22% · 부채 = 총부채)이에요. 재무 심층의 ROIC−WACC 카드는 다른 근사"
             "(Kd=Rf+2%p)를 써서 값이 조금 달라요.")


def _inp(key: str, label: str, value: Any, basis: str, source: str = "", unit: str | None = None) -> dict:
    """`unit`: "원"(금액) · "%"(이미 백분율인 수) · "년". 없으면 0~1 비율이거나 글."""
    d = {"key": key, "label": label, "value": value, "basis": basis, "source": source}
    if unit:
        d["unit"] = unit
    return d


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and math.isfinite(float(x)) else None


def _off(reason: str, **extra: Any) -> dict:
    return {"available": False, "reason": reason, **extra}


def _shares(fs) -> float | None:
    s = _num(getattr(fs, "shares_outstanding", None))
    return s if s and s > 0 else None


def _years(history: list) -> list:
    """연도별 하나(같은 해가 둘이면 뒤의 것) · 오래된 순."""
    by: dict[str, Any] = {}
    for fs in history:
        by[str(fs.bsns_year)] = fs
    return [by[y] for y in sorted(by)]


# ── WACC ─────────────────────────────────────────────────────────────────────

def dcf_wacc(fs, params: ValuationParams) -> float:
    """`compute_dcf` 와 같은 WACC — ke·E/V + kd(1−t)·D/V, kd = Rf+1.5%p, 하한 3%."""
    equity = _num(fs.total_equity) or 1
    debt = _num(fs.total_liabilities) or 0
    v = equity + debt
    kd = params.risk_free_rate + 0.015
    w = params.ke * (equity / v) + kd * (1 - params.tax_rate) * (debt / v)
    return max(w, 0.03)


# ── EVA · 가치 동인 ──────────────────────────────────────────────────────────

IC_METHOD = "총자산 − 유동부채"
IC_METHOD_NO_CL = "총자산(유동부채를 몰라 빼지 못함 — EVA 를 낮게 잡는 쪽)"


def _eva_row(fs, params: ValuationParams, wacc: float) -> dict:
    op, ta, cl = _num(fs.operating_profit), _num(fs.total_assets), _num(fs.current_liabilities)
    if op is None or ta is None:
        return {"year": str(fs.bsns_year), "available": False, "reason": "영업이익이나 총자산이 없어요"}
    nopat = op * (1 - params.tax_rate)
    # 유동부채를 모르면 총자산 그대로 — 투하자본을 크게(EVA 를 낮게) 잡는 쪽의 근사이고, 행마다 방법을 적는다
    ic, method = (ta - cl, IC_METHOD) if cl is not None else (ta, IC_METHOD_NO_CL)
    return {"year": str(fs.bsns_year), "available": True, "nopat": nopat, "invested_capital": ic,
            "ic_method": method, "roic": (nopat / ic) if ic > 0 else None, "wacc": wacc, "eva": nopat - wacc * ic}


def eva_analysis(history: list, latest, params: ValuationParams, *, fade_years: int = 5,
                 g: float | None = None, ronic: float | None = None) -> dict:
    """연도별 EVA(= NOPAT − WACC × 투하자본) · EVA 소멸 가치 · 가치 동인 공식.

    투하자본 ≈ 총자산 − 유동부채(현금·무이자 부채를 가르지 못한 **근사**). EVA 는 N 년에 걸쳐 0 으로 줄어든다고 **가정**한다
    (EVA_t = EVA₀ × (1 − t/(N+1))). 지분가치 = 기업가치 − 총부채 — DCF 엔진과 같은 다리.
    가치 동인(McKinsey): 가치 = NOPAT₁ × (1 − g/RONIC) / (WACC − g).
    """
    wacc = dcf_wacc(latest, params)
    years = [_eva_row(fs, params, wacc) for fs in _years([*history, latest])]
    last = next((r for r in reversed(years) if r["year"] == str(latest.bsns_year)), None)
    inputs = [_inp("tax", "세율", params.tax_rate, ASSUMED, "법인세 22% 가정"),
              _inp("wacc", "WACC", round(wacc, 4), APPROX, "DCF 엔진과 같은 식"),
              _inp("invested_capital", "투하자본", last.get("invested_capital") if last else None, APPROX,
                   (last or {}).get("ic_method") or IC_METHOD, unit="원"),
              _inp("fade_years", "EVA 소멸 기간", fade_years, ASSUMED, "초과이익이 사라지는 데 걸리는 해", unit="년")]
    if not last or not last["available"]:
        return _off("최근 연도의 투하자본(총자산)이나 영업이익을 알 수 없어요", years=years, inputs=inputs)

    eva0, ic, nopat = last["eva"], last["invested_capital"], last["nopat"]
    n = max(1, int(fade_years))
    pv = sum(eva0 * (1 - t / (n + 1)) / (1 + wacc) ** t for t in range(1, n + 1))
    shares = _shares(latest)
    tl = _num(latest.total_liabilities) or 0.0
    firm = ic + pv
    valuation = {"pv_eva": pv, "firm_value": firm, "equity_value": firm - tl,
                 "per_share": (firm - tl) / shares if shares else None,
                 "per_share_reason": None if shares else "발행주식수를 몰라 주당 가치를 낼 수 없어요"}

    vd: dict
    if g is None and ronic is None:
        vd = _off("성장률·RONIC 을 정하지 않았어요")
    elif nopat <= 0:
        vd = _off("영업이익이 적자라 가치 동인 공식을 쓸 수 없어요(성장이 적자를 키운다)")
    elif ronic is None or ronic <= 0:
        vd = _off("새 투자의 수익률(RONIC)이 0 이하라 공식이 성립하지 않아요")
    elif g is None or g >= wacc - 1e-6:
        vd = _off(f"성장률({(g or 0):.1%})이 WACC({wacc:.1%}) 이상이면 가치가 발산해요")
    else:
        value = nopat * (1 + g) * (1 - g / ronic) / (wacc - g)
        no_growth = nopat / wacc
        vd = {"available": True, "value": value, "no_growth_value": no_growth, "g": g, "ronic": ronic,
              "growth_creates_value": ronic > wacc,
              "per_share": (value - tl) / shares if shares else None}
        inputs += [_inp("g", "성장률", g, ASSUMED), _inp("ronic", "새 투자 수익률 RONIC", ronic, ASSUMED)]
    return {"available": True, "reason": None, "years": years, "latest": last, "valuation": valuation,
            "value_driver": vd, "inputs": inputs, "note": WACC_NOTE}


# ── 가치의 층 (Greenwald 3층) ────────────────────────────────────────────────

def value_layers(history: list, latest, params: ValuationParams, *, full_value_per_share: float | None,
                 weights: tuple[float, float, float]) -> dict:
    """자산층(장부 자본) → 수익력층(EPV, 성장 없음) → 성장층(= 통합 적정가 − EPV). 셋에 확률 가중을 둔다.

    EPV = 정상화 영업이익 × (1−t) / WACC − 총부채. 정상화 = 가용 연도 평균 영업이익률 × 최근 매출. 감가상각 ≈ 유지 투자라고
    **가정**한다(감가상각 자료가 없다). 자산층은 재생산원가가 아니라 **장부 자본**(근사).
    """
    wa, we, wf = (float(x) for x in weights)
    inputs = [_inp("asset", "자산층", "장부 자본 / 주식수", APPROX, "재생산원가 대신 장부가"),
              _inp("maintenance", "유지 투자", "감가상각과 같다고 봄", ASSUMED, "감가상각 자료 없음"),
              _inp("weights", "층별 가중", [wa, we, wf], ASSUMED, "자산층·수익력층·통합 적정가")]
    if abs(wa + we + wf - 1.0) > 1e-6 or min(wa, we, wf) < 0:
        return _off(f"층별 가중의 합이 1 이어야 해요(지금 {wa + we + wf:.2f}) — 나눠 맞추지 않아요", inputs=inputs)
    shares = _shares(latest)
    if not shares:
        return _off("발행주식수를 몰라 주당 가치를 낼 수 없어요", inputs=inputs)
    wacc = dcf_wacc(latest, params)
    te, tl = _num(latest.total_equity), _num(latest.total_liabilities) or 0.0
    asset_ps = te / shares if te is not None else None

    margins = [op / rev for fs in _years(history)
               if (rev := _num(fs.revenue)) and rev > 0 and (op := _num(fs.operating_profit)) is not None]
    rev0 = _num(latest.revenue)
    epv: dict = {"key": "epv", "label": "수익력가치(EPV)"}
    if not margins or not rev0 or rev0 <= 0:
        epv.update(per_share=None, reason="매출·영업이익 이력이 없어 정상화할 수 없어요")
    else:
        margin = sum(margins) / len(margins)
        nopat = margin * rev0 * (1 - params.tax_rate)
        if nopat <= 0:
            epv.update(per_share=None, reason="정상화한 영업이익이 적자라 수익력가치가 없어요")
        else:
            epv.update(per_share=(nopat / wacc - tl) / shares, normalized_margin=margin, nopat=nopat)
    layers = [{"key": "asset", "label": "자산가치", "per_share": asset_ps,
               "reason": None if asset_ps is not None else "자본총계가 없어요"},
              {**epv, "reason": epv.get("reason")}]
    full = _num(full_value_per_share)
    growth_ps = (full - epv["per_share"]) if (full is not None and epv.get("per_share") is not None) else None
    layers.append({"key": "growth", "label": "성장가치", "per_share": growth_ps,
                   "reason": None if growth_ps is not None else "통합 적정가나 EPV 가 없어 성장층을 잴 수 없어요"})

    vals = {"asset": asset_ps, "epv": epv.get("per_share"), "full": full}
    need = [k for k, w in zip(("asset", "epv", "full"), (wa, we, wf)) if w > 0 and vals[k] is None]
    weighted = None if need else sum(w * (vals[k] or 0.0) for k, w in zip(("asset", "epv", "full"), (wa, we, wf)))
    return {"available": True, "reason": None, "layers": layers, "full_per_share": full,
            "weighted_per_share": weighted,
            "weighted_reason": (f"가중을 둔 층({', '.join('EPV' if k == 'epv' else k for k in need)})을 잴 수 없어요 — "
                                "0 으로 채우지 않아요") if need else None,
            "normalization": {"years": len(margins), "wacc": wacc},
            "franchise": (None if epv.get("per_share") is None or asset_ps is None else
                          "수익력이 자산보다 커요(초과이익을 내는 무언가가 있다)" if epv["per_share"] > asset_ps else
                          "수익력이 자산보다 작아요(자산을 제값에 못 쓰고 있다)"),
            "inputs": inputs, "note": WACC_NOTE}


# ── 배수 · PEG · 정당 배수 ───────────────────────────────────────────────────

def multiples_matrix(fs, *, price: float, params: ValuationParams, eps_growth_pct: float | None,
                     growth_axis: list[float], peg_axis: list[float],
                     peer_per_median: float | None = None) -> dict:
    """성장률 × PEG 격자의 암시 주가(= EPS × PEG × 성장률%) · 현재 PER·PEG · 정당 PBR/PER.

    정당 PBR = (ROE − g)/(Ke − g) · 정당 PER = 배당성향 × (1+g)/(Ke − g). ROE·배당성향은 재무제표에서(관측), g·Ke 는 가정.
    """
    shares = _shares(fs)
    ni = _num(fs.net_income)
    eps = _num(fs.eps) or (ni / shares if (ni is not None and shares) else None)
    inputs = [_inp("eps", "EPS", eps, OBSERVED if eps is not None else UNKNOWN, "순이익 / 주식수", unit="원"),
              _inp("eps_growth", "EPS 성장률", eps_growth_pct, OBSERVED if eps_growth_pct is not None else UNKNOWN,
                   "3년 EPS 연평균 성장률", unit="%"),
              _inp("g", "영구성장률", params.terminal_growth_rate, ASSUMED),
              _inp("ke", "자기자본비용", round(params.ke, 4), APPROX, "CAPM")]
    if eps is None or eps <= 0:
        return _off("EPS 가 0 이하라 배수(PER·PEG)가 뜻을 잃어요 — 적자 기업은 배수로 보지 않아요", inputs=inputs)
    per = price / eps
    peg, peg_reason = None, None
    if eps_growth_pct is None:
        peg_reason = "EPS 성장률을 몰라 PEG 를 낼 수 없어요"
    elif eps_growth_pct <= 0:
        peg_reason = "EPS 성장률이 0 이하라 PEG 가 뜻을 잃어요"
    else:
        peg = per / eps_growth_pct
    prices = [[eps * p * gr for p in peg_axis] for gr in growth_axis]
    near = min(((i, j) for i in range(len(growth_axis)) for j in range(len(peg_axis))),
               key=lambda ij: abs(prices[ij[0]][ij[1]] - price)) if prices and peg_axis else None

    ke, g = params.ke, params.terminal_growth_rate
    te, dps = _num(fs.total_equity), _num(fs.dps)
    roe = (ni / te) if (ni is not None and te and te > 0) else None
    bps = _num(fs.bps) or (te / shares if (te is not None and shares) else None)
    just: dict = {"roe": roe, "ke": ke, "g": g}
    if ke - g <= 1e-3:
        just.update(pbr=None, per=None, reason=f"Ke({ke:.1%})가 성장률({g:.1%})보다 커야 정당 배수가 성립해요")
    else:
        pbr = (roe - g) / (ke - g) if roe is not None else None
        payout = (dps / eps) if dps is not None else None
        jper = payout * (1 + g) / (ke - g) if payout is not None else None
        just.update(pbr=pbr, per=jper, payout=payout,
                    pbr_price=(pbr * bps) if (pbr is not None and pbr > 0 and bps) else None,
                    per_price=(jper * eps) if jper is not None else None,
                    reason=None if roe is not None else "ROE 를 몰라 정당 PBR 을 낼 수 없어요")
        if pbr is not None and pbr <= 0:
            just["pbr_note"] = "ROE 가 성장률보다 낮아 정당 PBR 이 0 이하예요 — 자본이 가치를 만들지 못한다는 뜻"
    return {"available": True, "reason": None, "eps": eps, "per": per, "peg": peg, "peg_reason": peg_reason,
            "matrix": {"growth_axis": list(growth_axis), "peg_axis": list(peg_axis), "prices": prices,
                       "nearest": list(near) if near else None},
            "justified": just, "peer": {"per_median": peer_per_median,
                                        "per_price": (peer_per_median * eps) if peer_per_median else None},
            "price": price, "inputs": inputs}


# ── 영업 동인 몬테카를로 ─────────────────────────────────────────────────────

_Q = (5, 10, 25, 50, 75, 90, 95)


def _path_values(rev0: float, g: np.ndarray, m: np.ndarray, r: np.ndarray, *, years: int, tax: float, wacc: float,
                 gt: float, debt: float, shares: float) -> np.ndarray:
    t = np.arange(1, years + 1)
    rev = rev0 * (1 + g[:, None]) ** t[None, :]
    fcf = rev * (m[:, None] * (1 - tax) - r[:, None])
    pv = (fcf / (1 + wacc) ** t[None, :]).sum(axis=1)
    tv = fcf[:, -1] * (1 + gt) / (wacc - gt) / (1 + wacc) ** years
    return (pv + tv - debt) / shares


def driver_monte_carlo(history: list, latest, params: ValuationParams, *, sigma_growth: float, sigma_margin: float,
                       sigma_reinvest: float, years: int, n: int, seed: int, price: float | None) -> dict:
    """매출 성장률·영업이익률·재투자율을 흔들어 주당 가치의 분포를 낸다(세 동인 독립 가정).

    분포의 **중심**은 재무 이력에서 읽고(관측·근사), **폭**은 사람이 정한다(가정). FCF = 매출 × (마진 × (1−t) − 재투자율),
    재투자율 = (NOPAT − (영업CF − CAPEX))/매출 — 감가상각 자료가 없어 영업CF 로 대신한다(근사). 영구성장률은 가정 그대로.
    """
    hist = [fs for fs in _years(history) if (_num(fs.revenue) or 0) > 0]
    inputs = [_inp("sigma_growth", "성장률 흔들림(σ)", sigma_growth, ASSUMED),
              _inp("sigma_margin", "마진 흔들림(σ)", sigma_margin, ASSUMED),
              _inp("sigma_reinvest", "재투자율 흔들림(σ)", sigma_reinvest, ASSUMED),
              _inp("reinvest", "재투자", "NOPAT − (영업CF − CAPEX)", APPROX, "감가상각은 영업CF 에 들어 있다고 봄"),
              _inp("independence", "동인끼리 관계", "서로 독립", ASSUMED)]
    if len(hist) < 2:
        return _off("매출 이력이 2개 연도 이상 있어야 성장률 중심을 잴 수 있어요", inputs=inputs)
    shares = _shares(latest)
    if not shares:
        return _off("발행주식수를 몰라 주당 가치를 낼 수 없어요", inputs=inputs)
    wacc, gt = dcf_wacc(latest, params), params.terminal_growth_rate
    if gt >= wacc - 1e-3:
        return _off(f"영구성장률({gt:.1%})이 WACC({wacc:.1%}) 이상이면 잔존가치가 발산해요", inputs=inputs)

    first, last = _num(hist[0].revenue), _num(hist[-1].revenue)
    cg = (last / first) ** (1 / (len(hist) - 1)) - 1
    margins = [op / _num(fs.revenue) for fs in hist if (op := _num(fs.operating_profit)) is not None]
    # 재투자율 = (NOPAT − FCF)/매출, FCF = 영업CF − CAPEX — 감가상각 자료가 없어도 영업CF 가 그것을 품고 있다(근사)
    reinv = [(op * (1 - params.tax_rate) - (ocf - abs(cx))) / _num(fs.revenue) for fs in hist
             if (op := _num(fs.operating_profit)) is not None and (ocf := _num(fs.operating_cf)) is not None
             and (cx := _num(fs.capex)) is not None]
    if not margins:
        return _off("영업이익 이력이 없어 마진 중심을 잴 수 없어요", inputs=inputs)
    cm = sum(margins) / len(margins)
    cr = sum(reinv) / len(reinv) if reinv else 0.0
    inputs = [_inp("growth", "매출 성장률 중심", cg, OBSERVED, f"{len(hist)}개 연도 연평균"),
              _inp("margin", "영업이익률 중심", cm, OBSERVED, f"{len(margins)}개 연도 평균"),
              _inp("reinvest_rate", "재투자율 중심", cr, APPROX if reinv else UNKNOWN,
                   f"{len(reinv)}개 연도 평균" if reinv else "영업CF·CAPEX 이력 없음 — 0 으로 두지 않고 미상"), *inputs]
    if not reinv:
        return _off("영업현금흐름·CAPEX 이력이 없어 재투자율을 모르면 현금흐름을 만들 수 없어요", inputs=inputs)

    rng = np.random.default_rng(seed)
    g = cg + sigma_growth * rng.standard_normal(n)
    m = cm + sigma_margin * rng.standard_normal(n)
    r = cr + sigma_reinvest * rng.standard_normal(n)       # 음수 = FCF 가 NOPAT 보다 큰 해(자르지 않는다)
    ok = g > -0.95                                   # 매출이 사라지는 경로는 모형 밖 — 버리고 센다
    debt = _num(latest.total_liabilities) or 0.0
    rev0 = last
    vals = _path_values(rev0, g[ok], m[ok], r[ok], years=years, tax=params.tax_rate, wacc=wacc, gt=gt,
                        debt=debt, shares=shares)
    vals = vals[np.isfinite(vals)]
    det = float(_path_values(rev0, np.array([cg]), np.array([cm]), np.array([cr]), years=years,
                             tax=params.tax_rate, wacc=wacc, gt=gt, debt=debt, shares=shares)[0])
    if vals.size == 0:
        return _off("쓸 수 있는 경로가 하나도 없었어요", inputs=inputs)
    q = {f"p{k}": float(np.percentile(vals, k)) for k in _Q}
    counts, edges = np.histogram(vals, bins=20)
    return {"available": True, "reason": None, "centers": {"growth": cg, "margin": cm, "reinvest": cr},
            "quantiles": q, "mean": float(vals.mean()), "deterministic_per_share": det,
            "histogram": {"counts": counts.tolist(), "edges": [float(e) for e in edges]},
            "price": price, "price_percentile": (float((vals < price).mean() * 100) if price else None),
            "n_requested": n, "n_used": int(vals.size), "n_rejected": int(n - vals.size),
            "negative_share": float((vals < 0).mean()), "wacc": wacc, "terminal_growth": gt, "years": years,
            "seed": seed, "inputs": inputs,
            "note": ("'가치 분포' 노드는 할인율·성장률 **가정**을 흔들고, 이 노드는 매출·마진·재투자라는 **영업**을 흔들어요 — "
                     "다른 불확실성이에요. 폭(σ)은 잰 값이 아니라 정한 값이에요.")}
