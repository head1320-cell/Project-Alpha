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


# ── BN N2 · 선 요약을 더 많은 포트 타입으로 — 값 모양은 생산 노드에서 확인한 것만(tests/test_graph_briefs_more.py) ──
# 기대 수익 설정(Belief)은 셀 것이 없어, 시나리오·전략 묶음 성과·백테스트 실행은 기본 실행에서 값을 확인하지 못해
# 요약하지 않는다(키가 없다 = 지어내지 않는다). 충격 결과(StressReport)는 BO O4 에서 생산 노드 셋의 모양을 확인해 더했다(아래).

_PHASE_PLAIN = {"Goldilocks": "골디락스", "Reflation": "리플레이션", "Stagflation": "스태그플레이션",
                "Deflation": "디플레이션", "Disinflation": "디스인플레이션"}
_SIGNAL_PLAIN = (("risk_on", "위험-온"), ("risk_off", "위험-오프"), ("unavailable", "판단 불가"))


def _finite(v: Any) -> float | None:
    x = _num(v)
    return x if x is not None and math.isfinite(x) else None


def _count(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def brief_views(v: Any) -> str | None:
    return f"생각 {len(v)}개" if isinstance(v, list) else None


def brief_scores(v: Any) -> str | None:
    s = v.get("scores") if isinstance(v, Mapping) else None
    if not isinstance(s, Mapping) or not s:
        return None
    unknown = sum(1 for x in s.values() if _finite(x) is None)
    return f"{len(s)}종목 점수" + (f" · {unknown}개 모름" if unknown else "")


def brief_regime(v: Any) -> str | None:
    p = v.get("phase_probabilities") if isinstance(v, Mapping) else None
    known = {str(k): x for k, x in (p.items() if isinstance(p, Mapping) else []) if _finite(x) is not None}
    if not known:
        return None
    top = max(known, key=lambda k: known[k])
    return f"{_PHASE_PLAIN.get(top, top)} {float(known[top]) * 100:.0f}%"


def brief_timing(v: Any) -> str | None:
    states = v.get("states") if isinstance(v, Mapping) else None
    if not isinstance(states, list) or not states:
        return None
    vals = [getattr(s, "value", s) for s in states]
    if any(x not in dict(_SIGNAL_PLAIN) for x in vals):
        return None                                   # 모르는 상태 — 세지 않는다
    return " · ".join([f"신호 {len(vals)}개", *(f"{name} {vals.count(k)}" for k, name in _SIGNAL_PLAIN if vals.count(k))])


def brief_trades(v: Any) -> str | None:
    s = _get(v, "plan", "summary")
    n, b, sl = (_count(s.get(k)) for k in ("n_orders", "n_buy", "n_sell")) if isinstance(s, Mapping) else (None,) * 3
    if n is None:
        return None
    return f"주문 {n}건" + (f" · 매수 {b} · 매도 {sl}" if b is not None and sl is not None else "")


def brief_target(v: Any) -> str | None:
    tv = v.get("tv") if isinstance(v, Mapping) else None
    fw = tv.get("final_weights") if isinstance(tv, Mapping) else None
    cash = _finite(tv.get("cash_weight")) if isinstance(tv, Mapping) else None
    if not isinstance(fw, Mapping) or cash is None or any(_finite(x) is None for x in fw.values()):
        return None
    held = sum(1 for x in fw.values() if abs(float(x)) > 1e-9)
    # 실행 노드(`target_version`)의 설명과 같은 말 — executable 이 아니면 연구용.
    kind = "실행할 수 있는 목표" if tv.get("status") == "executable" else "연구용 목표"
    return f"{kind} · {held}종목 · 현금 {cash:.0f}%"


def brief_backtest(v: Any) -> str | None:
    if not isinstance(v, Mapping) or v.get("error"):
        return None
    d = v.get("dates")
    if not isinstance(d, list) or len(d) < 2:
        return None
    return f"{len(d)}일 · {d[0]}~{d[-1]}"


def brief_risk(v: Any) -> str | None:
    vol = _finite(_get(v, "risk_contribution_optimized", "portfolio_volatility_pct"))
    # 보기의 설명(`explain_risk`)과 같은 단위 — 1년 기준 변동성.
    return f"연 변동성 {vol:.1f}%" if vol is not None else None


_STRESS_LABEL_MAX = 28


def brief_stress(v: Any) -> str | None:
    """충격 결과 (BO O4) — 생산 노드 셋의 모양을 **각 노드 설명(explain)이 쓰는 키·단위 그대로** 읽는다.

    - 시나리오 충격 · 과거 재생(`result.mode == "historical"`): `max_dd_pct` — 최대 낙폭(%)
    - 시나리오 충격 · 가정 충격: `portfolio_shock_pct` — 추정 충격(%)
    - 직접 만든 시나리오: `shock_pct` — 예상 충격(%)
    - 상관 스트레스: `stressed.port_vol_pct` — 위기 때 연 변동성(%). ★`delta_vol_pct` 는 %p 인지 % 인지 분명하지 않아 쓰지 않는다.★
    모양이 이 넷이 아니면 요약하지 않는다(None).
    """
    r = v.get("result") if isinstance(v, Mapping) else None
    if not isinstance(r, Mapping):
        return None
    pack = v.get("pack") if isinstance(v.get("pack"), Mapping) else r.get("pack")
    label = pack.get("label") if isinstance(pack, Mapping) else None
    head = f"{label} · " if isinstance(label, str) and 0 < len(label) <= _STRESS_LABEL_MAX else ""

    def signed(x: float) -> str:
        return ("+" if x >= 0 else "−") + f"{abs(x):.1f}%"
    if r.get("mode") == "historical":
        dd = _finite(r.get("max_dd_pct"))
        return f"{head}최대 낙폭 {signed(dd)}" if dd is not None else None
    if "portfolio_shock_pct" in r:
        x = _finite(r.get("portfolio_shock_pct"))
        return f"{head}추정 충격 {signed(x)}" if x is not None else None
    if "shock_pct" in r:
        x = _finite(r.get("shock_pct"))
        return f"{head}예상 충격 {signed(x)}" if x is not None else None
    if isinstance(r.get("stressed"), Mapping):
        vol = _finite(r["stressed"].get("port_vol_pct"))
        return f"위기 때 연 변동성 {vol:.1f}%" if vol is not None else None
    return None


BRIEFS: dict[str, Callable[[Any], str | None]] = {
    "Universe": brief_universe, "Returns": brief_returns, "Weights": brief_weights,
    "Views": brief_views, "Scores": brief_scores, "RegimeState": brief_regime, "TimingSignal": brief_timing,
    "Trades": brief_trades, "TargetVersion": brief_target, "BacktestResult": brief_backtest, "RiskReport": brief_risk,
    "StressReport": brief_stress,
}


def register(registry: pg.Registry) -> None:
    for t, fn in GLANCES.items():
        if registry.get(t) is not None:
            registry.set_glance(t, fn)
    for pt, fn in BRIEFS.items():
        registry.set_port_brief(pt, fn)
