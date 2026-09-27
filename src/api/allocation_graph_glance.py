"""AAS 그래프 — 캔버스 위 작은 그림 (BM C1) · ★보기의 값을 그대로 옮긴다★
==============================================================================
설계 `docs/superpowers/specs/2026-09-27-canvas-workspace-design.md` §C1. 테스트 `tests/test_graph_glance.py`.

노드 카드를 가까이 보면 결과의 모양(비중 막대 · 누적 곡선 · 충격 기여 · VaR 세 방법 …)이 카드 안에 보인다. 그 그림은 서버가 만든다 —
화면은 그리기만 한다(BJ 원칙). 여기 함수들은 **보기(view)에 이미 있는 수를 고르고 줄일 뿐** 새 수를 만들지 않는다:
- 막대: 큰 것부터(절댓값) 최대 8개 — 나머지는 캡션에 "외 n개".
- 선: 양 끝을 반드시 넣고 고르게 솎아 최대 48점 — 솎은 점의 값은 원래 값 그대로.
- 값을 모르면(None) 그 점은 None 그대로(0 으로 채우지 않는다). 그릴 수가 하나도 없으면 None(그림 없음).
엔진(`portfolio_graph._check_glance`)이 모양을 다시 검사한다.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from src.api.allocation_routes import _w_dict
from src.engine import portfolio_graph as pg

TOP_BARS = 8
LINE_POINTS = 48


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _get(view: Any, *path: str) -> Any:
    cur = view
    for k in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(k)
    return cur


def _bars_from(mapping: Any, labels: Mapping | None = None, *, unit: str | None = "%",
               caption: str | None = None, extra: list[tuple[str, Any]] | None = None) -> dict | None:
    if not isinstance(mapping, Mapping) or not mapping:
        return None
    items = sorted(mapping.items(), key=lambda kv: (_num(kv[1]) is None, -abs(_num(kv[1]) or 0.0)))
    top, rest = items[:TOP_BARS], len(items) - TOP_BARS
    pts = [{"label": str((labels or {}).get(k) or k), "value": _num(v)} for k, v in top]
    pts += [{"label": str(lab), "value": _num(v)} for lab, v in (extra or [])]
    if rest > 0:
        caption = f"{caption + ' · ' if caption else ''}외 {rest}개"
    return {"kind": "bars", "unit": unit, "caption": caption, "points": pts}


def _line(labels: Any, values: Any, *, unit: str | None = None, caption: str | None = None) -> dict | None:
    if not isinstance(values, list) or len(values) < 2:
        return None
    labels = labels if isinstance(labels, list) and len(labels) == len(values) else list(range(len(values)))
    n = len(values)
    k = min(LINE_POINTS, n)
    idx = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    return {"kind": "line", "unit": unit, "caption": caption,
            "points": [{"label": str(labels[i]), "value": _num(values[i])} for i in idx]}


def _values(pairs: list[tuple[str, Any]], *, unit: str | None = None, caption: str | None = None) -> dict | None:
    pts = [{"label": lab, "value": _num(v)} for lab, v in pairs]
    return {"kind": "values", "unit": unit, "caption": caption, "points": pts} if pts else None


# ── 노드별 그림 ────────────────────────────────────────────────────────────────

def weights_bars(view: Mapping, key: str = "weights", caption: str | None = "비중") -> dict | None:
    return _bars_from(view.get(key), view.get("labels"), caption=caption)


def _risk(view):
    return _bars_from(_get(view, "risk_contribution_optimized", "pct"), view.get("labels"), caption="위험 기여")


def _backtest(view):
    return _line(view.get("dates"), view.get("equity_curve"), caption="누적 가치")


def _scenario(view):
    r = view.get("result") or {}
    if r.get("mode") == "historical":
        return _line(r.get("dates"), r.get("portfolio_dd"), unit="%", caption="낙폭")
    rows = r.get("rows") or []
    return _bars_from({(x.get("corp_name") or x.get("stock_code")): x.get("contribution_pct") for x in rows},
                      unit="%", caption="종목별 충격 기여")


def _var_es(view):
    r = view.get("result") or {}
    cl = _num(r.get("confidence_level"))
    return _values([("정규", _get(r, "normal", "var_pct")), ("EWMA", _get(r, "ewma", "var_pct")),
                    ("역사적", _get(r, "historical", "var_pct"))],
                   unit="%", caption=f"하루 VaR{f' {cl * 100:.0f}%' if cl is not None else ''}")


def _mc_var(view):
    r = view.get("result") or {}
    return _values([("VaR", r.get("mc_var_pct")), ("ES", r.get("mc_es_pct"))], unit="%", caption="몬테카를로")


def _frontier(view):
    curve = view.get("curve") or []
    if len(curve) < 2:
        return None
    return {"kind": "line", "unit": "%", "caption": "흔들림 → 연 수익",
            "points": [{"label": f"{_num(c.get('volatility')) or 0:.1f}" if _num(c.get("volatility")) is not None else "?",
                        "value": _num(c.get("return"))} for c in curve[:LINE_POINTS]]}


def _rolling_sharpe(view):
    r = view.get("result") or {}
    return _line(r.get("dates"), r.get("values"), caption=f"롤링 샤프 {r.get('window') or ''}일".strip())


def _company_valuation(view):
    u = _get(view, "result", "unified") or {}
    pairs = [("현재가", view.get("price"))] + [(str(m.get("model")), m.get("value")) for m in (u.get("models") or [])]
    return _values(pairs, unit="원", caption="모델별 적정가")


def _valuation_scores(view):
    return _bars_from(view.get("scores"), view.get("labels"), caption="적정가 대비 싼 정도")


def _screener(view):
    items = view.get("items") or []
    return _bars_from({(x.get("corp_name") or x.get("stock_code")): x.get("composite_score") for x in items},
                      unit=None, caption="종합 점수")


def _corr_stress(view):
    r = view.get("result") or {}
    return _values([("평소", _get(r, "base", "port_vol_pct")), ("위기", _get(r, "stressed", "port_vol_pct"))],
                   unit="%", caption="변동성(연)")


def _factor_xray(view):
    fs = _get(view, "result", "factors") or []
    return _bars_from({f.get("label") or f.get("id"): f.get("portfolio_z") for f in fs}, unit="σ", caption="성격 노출")


def _implement(view):
    return _bars_from(_get(view, "result", "holdings"), view.get("labels"), caption="상품 비중")


def _driver_mc(view):
    h = _get(view, "result", "histogram") or {}
    counts, edges = h.get("counts"), h.get("edges")
    if not isinstance(counts, list) or not isinstance(edges, list) or len(edges) != len(counts) + 1 or not counts:
        return None
    return {"kind": "hist", "unit": None, "caption": "주당 가치 분포(경로 수)",
            "points": [{"label": f"{edges[i]:.0f}", "value": _num(c)} for i, c in enumerate(counts)]}


def _valuation_distribution(view):
    u = _get(view, "result", "unified") or {}
    if not u.get("available"):
        return None
    return _values([(q.upper(), u.get(q)) for q in ("p10", "p25", "p50", "p75", "p90")], unit="원", caption="가치 분포")


def _overlay(view):
    cash = view.get("cash_pct")
    return _bars_from(view.get("after"), view.get("labels"), caption="조절 후 비중",
                      extra=[("현금", cash)] if _num(cash) is not None else None)


def _sleeves(view):
    return _bars_from(_get(view, "result", "sleeve_allocation"), caption="묶음 몫")


def _holding_var(view):
    rows = _get(view, "result", "results") or []
    return _values([(f"{r.get('holding_period_days')}일 {(_num(r.get('confidence_level')) or 0) * 100:.0f}%",
                     r.get("var_pct")) for r in rows], unit="%", caption="보유기간 VaR")


def _yield_curve(view):
    pts = _get(view, "result", "points") or []
    return _line([p.get("label") for p in pts], [p.get("yield_pct") for p in pts], unit="%", caption="수익률 곡선")


def _regime(view):
    return _bars_from(view.get("phase_probabilities"), unit=None, caption="국면 확률")


def _backtest_load(view):
    eq = view.get("equity") or {}
    return _line(eq.get("dates"), eq.get("values"), caption="누적 가치")


def _strategy_backtest(view):
    curve = view.get("curve") or []
    return _line([c.get("date") for c in curve], [c.get("equity") for c in curve], caption="누적 가치")


GLANCES: dict[str, Callable[[dict], dict | None]] = {
    "optimizer": weights_bars, "current_weights": weights_bars, "alpha_portfolio": weights_bars,
    "scores_to_weights": weights_bars, "risk": _risk, "backtest": _backtest,
    "scenario_stress": _scenario, "custom_scenario": _scenario, "var_es": _var_es, "mc_var": _mc_var,
    "frontier": _frontier, "rolling_sharpe": _rolling_sharpe, "company_valuation": _company_valuation,
    "valuation_scores": _valuation_scores, "screener": _screener, "corr_stress": _corr_stress,
    "factor_xray": _factor_xray, "implement_exposures": _implement, "company_driver_mc": _driver_mc,
    "valuation_distribution": _valuation_distribution, "exposure_overlay": _overlay, "sleeve_combine": _sleeves,
    "holding_var": _holding_var, "yield_curve": _yield_curve, "regime": _regime, "backtest_load": _backtest_load,
    "strategy_backtest": _strategy_backtest,
}


# ── 선 위 요약 — 포트 값의 한 줄(세기만 한다) ──────────────────────────────────

def brief_universe(v: Mapping) -> str | None:
    n = len(v.get("tickers") or [])
    return f"{n}종목" if n else None


def brief_returns(v: Mapping) -> str | None:
    names, obs = v.get("names") or [], _num(_get(v, "coverage", "n_obs"))
    if not names:
        return None
    return f"{len(names)}종목 · {obs:.0f}일" if obs is not None else f"{len(names)}종목"


def brief_weights(v: Mapping) -> str | None:
    names, w = list(v.get("names") or []), v.get("weights")
    try:
        xs = [float(x) for x in w] if w is not None else []
    except (TypeError, ValueError):
        xs = []
    if not names or len(xs) != len(names):
        return None
    total = sum(xs) * 100.0
    if not math.isfinite(total):
        return f"{len(names)}종목 · 합 모름"
    # 보유 수는 보기(`_w_dict`)와 같은 잡음 문턱으로 센다 — 카드의 막대 수와 선 라벨이 어긋나지 않게.
    return f"{len(_w_dict(names, np.asarray(xs)))}종목 · 합 {total:.0f}%"


BRIEFS: dict[str, Callable[[Any], str | None]] = {
    "Universe": brief_universe, "Returns": brief_returns, "Weights": brief_weights,
}


def register(registry: pg.Registry) -> None:
    for t, fn in GLANCES.items():
        if registry.get(t) is not None:
            registry.set_glance(t, fn)
    for pt, fn in BRIEFS.items():
        registry.set_port_brief(pt, fn)
