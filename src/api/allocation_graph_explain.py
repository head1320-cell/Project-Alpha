"""AAS 그래프 노드 설명기 — ★쉬운 말로, 과장 없이, 모르는 것은 "몰라요" 로★ (BJ1)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-workflow-ux-design.md` §4.3 · 사용자 결정: 설명
문장은 **서버가 결정적 규칙으로** 만든다(화면은 그리기만 한다).

설명기는 `(view, provenance, params) -> dict` 순수 함수다. 반환 모양:

    {"title": 해요체 한 줄,
     "headline": {"label", "value", "unit", "text"} | 없음,
     "facts": [한 줄 사실],
     "trust": [{"state": confirmed|assumed|unknown|failed, "text"}],   # "믿어도 되나요?"
     "unmeasured": [안 잰 것]}

## 규칙 (CLAUDE.md §2 · §4)
- **숫자는 view 에서만** 가져온다 — 설명이 계산을 다시 하거나 반올림 이상으로 바꾸지 않는다.
- "확인(confirmed)" 은 **이 코드가 실제로 한 일**에만 쓴다(계산이 끝났다 · 기준일을 기록했다).
  예측력·경제적 가치를 확인했다는 말은 이 층 어디에도 없다.
- mock(E0) 은 "연습용 합성 데이터" 를 **몰라요**로 — 실제 성과를 말해 주지 않는다.
  DB 적재분은 등급을 모른다고 말한다(E3 을 지어내지 않는다).
- 과장 어휘는 테스트가 전수로 막는다(`tests/test_allocation_graph_explain.py`).
"""
from __future__ import annotations

from typing import Any

from src.engine.allocation_evidence import LOOKAHEAD_AXIS_LABELS

CONFIRMED, ASSUMED, UNKNOWN, FAILED = "confirmed", "assumed", "unknown", "failed"

#: 시장 균형(시가총액) 출발점을 쓰는 모델 — 시가총액 미상이 가정이 되는 곳.
_MARKET_PRIOR_MODELS = frozenset({"bl", "ep"})

MODEL_PLAIN = {
    "mvo": "수익 대비 위험 최적", "bl": "내 생각 반영", "ep": "내 생각 반영(엔트로피 풀링)",
    "risk_parity": "위험 똑같이", "hrp": "비슷한 것끼리 묶어", "min_var": "흔들림 최소",
    "max_div": "분산 최대", "min_cvar": "큰 손실 최소", "robust": "추정 오차에 강하게",
    "mv_utility": "위험 성향에 맞춰",
}

_PRACTICE = "연습용 합성 데이터예요 — 실제 시세가 아니라서 실제 성과를 말해 주지 않아요."


def _t(state: str, text: str) -> dict:
    return {"state": state, "text": text}


def _josa(word: str, with_batchim: str, without: str) -> str:
    """받침 유무로 조사를 고른다(한글이 아니면 받침 없음으로 본다)."""
    ch = word[-1:] if word else ""
    if "가" <= ch <= "힣":
        return with_batchim if (ord(ch) - 0xAC00) % 28 else without
    return without


def _pct(v: float, digits: int = 1) -> str:
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _signed_pct(v: float) -> str:
    return ("+" if v >= 0 else "−") + _pct(abs(v))


def _is_practice(prov: dict) -> bool:
    pl = prov.get("perf_label") or {}
    return prov.get("source") == "mock" or prov.get("data_source") == "mock" or pl.get("data_real") is False


def _names(codes: list[str], labels: dict[str, str] | None) -> str:
    labels = labels or {}
    return ", ".join(labels.get(c) or c for c in codes)


# ── 노드별 ───────────────────────────────────────────────────────────────────

def explain_universe(view: dict, prov: dict, params: Any) -> dict:
    tickers = view.get("tickers") or []
    labels = view.get("labels") or {}
    facts = [_names(tickers, labels)]
    facts.append("지금 들고 있는 비중도 알려 주었어요." if view.get("weights")
                 else "지금 들고 있는 비중은 알려 주지 않았어요.")
    trust = []
    unk = (view.get("unknown_tickers") or {}).get("codes") or []
    if unk:
        trust.append(_t(UNKNOWN, f"종목 목록에 없는 코드예요: {', '.join(unk)} — 실재하는 종목인지 몰라요."))
    return {"title": f"종목 {len(tickers)}개를 골랐어요", "facts": facts, "trust": trust}


def explain_returns(view: dict, prov: dict, params: Any) -> dict:
    cov = view.get("coverage") or {}
    n = cov.get("n_obs")
    years = (n / 252) if isinstance(n, (int, float)) and n else None
    title = (f"최근 {years:.0f}년 수익률을 불러왔어요" if years and abs(years - round(years)) < 0.15
             else f"최근 {n}일 수익률을 불러왔어요")
    facts = [f"{cov.get('start')}부터 {cov.get('end')}까지 {n}일 치예요."]
    ex = view.get("excluded") or []
    facts.append("빠진 종목은 없어요." if not ex else
                 "빠진 종목: " + "; ".join(f"{x['ticker']}({x['reason']})" for x in ex))
    trust = []
    if _is_practice(prov):
        trust.append(_t(UNKNOWN, _PRACTICE))
    elif prov.get("data_grade"):
        trust.append(_t(CONFIRMED, f"데이터 등급 {prov['data_grade']}로 기록돼 있어요."))
    else:
        trust.append(_t(UNKNOWN, "데이터 출처 등급은 몰라요 — "
                                 + str(prov.get("data_grade_reason") or "행 단위 출처가 기록되지 않았어요.")))
    if cov.get("as_of_effective"):
        trust.append(_t(CONFIRMED, f"계산 기준일을 {cov['as_of_effective']}로 기록했어요."))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["그 날 실제로 알 수 있던 값인지(공표 시점)는 행마다 재지 않았어요."]}


def explain_views(view: dict, prov: dict, params: Any) -> dict:
    from src.api.allocation_routes import _labels
    views = view.get("views") or []
    if not views:
        return {"title": "넣은 생각이 없어요", "facts": ["시장 균형만으로 계산해요."]}
    facts = []
    for v in views:
        mag = float(v.get("direction", 1)) * float(v.get("magnitude_pct", 0))
        conf = v.get("confidence", 50)
        if v.get("assets"):
            codes = list(v["assets"])
            who = _names(codes, _labels(codes))
            who = who if len(codes) == 1 else f"{who} 평균"
            facts.append(f"{who}의 1년 기대 수익을 {_signed_pct(mag)}로 봤어요 (확신 {conf:.0f}%).")
        else:
            w = v.get("weights") or {}
            parts = ", ".join(f"{_names([c], _labels([c]))} {x:+g}" for c, x in w.items())
            facts.append(f"조합({parts})의 1년 기대 수익을 {_signed_pct(mag)}로 봤어요 (확신 {conf:.0f}%).")
    return {"title": f"내 생각 {len(views)}개를 넣었어요", "facts": facts,
            "trust": [_t(ASSUMED, "내 생각은 입력한 가정이에요 — 맞는지는 이 계산이 확인하지 않아요.")]}


def explain_estimate(view: dict, prov: dict, params: Any) -> dict:
    s = view.get("settings") or {}
    if s.get("conditional"):
        return {"title": "경기 국면을 반영해 기대 수익을 잡기로 했어요",
                "facts": ["실제로 반영됐는지는 비중 계산 단계가 알려 줘요."],
                "trust": [_t(ASSUMED, "국면이 앞으로도 이어진다고 가정해요.")]}
    return {"title": "과거 수익률을 기준으로 기대 수익을 잡았어요",
            "facts": ["경기 국면은 반영하지 않았어요."],
            "trust": [_t(ASSUMED, "과거 평균이 앞으로도 비슷하다고 가정해요.")]}


def explain_optimizer(view: dict, prov: dict, params: Any) -> dict:
    w: dict[str, float] = view.get("weights") or {}
    labels = view.get("labels") or {}
    model = view.get("model")
    headline = None
    if w:
        top = max(w, key=lambda k: w[k])
        name = labels.get(top) or top
        headline = {"label": f"{name} 비중", "value": w[top], "unit": "%",
                    "text": f"{name} {_pct(w[top])}"}
    trust = [_t(CONFIRMED, "비중 계산은 문제없이 끝났어요.")]
    if _is_practice(prov):
        trust.append(_t(UNKNOWN, _PRACTICE))
    cap = view.get("cap_missing") or []
    if model in _MARKET_PRIOR_MODELS and cap:
        trust.append(_t(ASSUMED, f"시가총액을 몰라서 {len(cap)}개 종목의 출발점을 똑같이 나눴어요."))
    cr = view.get("constraints_report") or None
    if cr:
        if cr.get("status") == "infeasible":
            trust.append(_t(FAILED, "제약을 모두 지킬 수 없어서 제약 없는 비중을 그대로 보여 줘요 — "
                                    + str(cr.get("reason") or "")))
        else:
            trust.append(_t(CONFIRMED, "정한 제약 안에서 계산했어요."))
    belief = view.get("belief") or {}
    if belief.get("blocked"):
        trust.append(_t(ASSUMED, "경기 국면 반영이 막혀서 과거 기준으로 계산했어요 — "
                                 + str(belief.get("blocked_reason") or "")))
    if view.get("skipped_views"):
        trust.append(_t(UNKNOWN, f"넣은 생각 중 {len(view['skipped_views'])}개는 쓸 수 없어서 빠졌어요."))
    facts = [f"계산 방식: {MODEL_PLAIN.get(model, model)}"]
    ra = view.get("risk_aversion") or None
    if ra:
        # BO O1 — 쓴 λ 와 그 출처. 비워 두었으면 관례값이라는 사실을 **가정**으로 밝힌다.
        facts.append(f"위험 회피 λ {ra.get('value'):g}")
        if ra.get("source") == "default":
            trust.append(_t(ASSUMED, f"위험을 얼마나 피할지 정하지 않아서 관례적인 값(λ {ra.get('value'):g}, "
                                     "‘보통’)으로 계산했어요 — 나에게 맞는 값은 아니에요."))
        else:
            trust.append(_t(ASSUMED, f"위험 회피 λ {ra.get('value'):g}는 내가 고른 값이에요 — "
                                     "이 값이 나에게 맞는지는 이 계산이 말해 주지 않아요."))
    if view.get("views_unused"):
        trust.append(_t(ASSUMED, f"이어진 생각 {view['views_unused']}개는 이 계산 방식에서 쓰이지 않아요 — "
                                 "‘내 생각 반영’을 고르면 비중에 들어가요."))
    if model in _MARKET_PRIOR_MODELS:
        facts.append("내 생각을 반영했어요." if view.get("views_applied") else "반영된 생각이 없어요.")
    return {"title": "비중을 이렇게 나눴어요", "headline": headline, "facts": facts, "trust": trust}


def explain_risk(view: dict, prov: dict, params: Any) -> dict:
    rc = view.get("risk_contribution_optimized") or {}
    enb = view.get("enb") or {}
    vol = rc.get("portfolio_volatility_pct")
    if vol is None:
        return {"title": "흔들림을 계산하지 못했어요",
                "trust": [_t(UNKNOWN, str(rc.get("reason") or "사유를 받지 못했어요."))]}
    facts = []
    if enb.get("enb") is not None:
        facts.append(f"종목들이 함께 움직여서, 실제로 나뉜 베팅은 {enb['enb']:.1f}개 정도예요.")
    else:
        facts.append("실제로 나뉜 베팅 수는 몰라요 — " + str(enb.get("enb_reason") or ""))
    return {"title": "1년에 이 정도 흔들릴 수 있어요",
            "headline": {"label": "변동성", "value": round(float(vol), 1), "unit": "%",
                         "text": f"{_pct(float(vol))} / 년"},
            "facts": facts,
            "trust": [_t(ASSUMED, "과거에 종목들이 함께 움직인 방식이 이어진다고 가정해요.")]}


def explain_backtest(view: dict, prov: dict, params: Any) -> dict:
    s = view.get("summary") or {}
    cfg = view.get("config") or {}
    cagr, mdd = s.get("cagr_pct"), s.get("max_drawdown_pct")
    headline = None if cagr is None else {
        "label": "연 수익률", "value": cagr, "unit": "%", "text": f"연 {_pct(float(cagr))}"}
    facts = []
    if mdd is not None:
        facts.append(f"가장 크게 떨어졌을 때는 {_pct(float(mdd))}였어요.")
    if view.get("n_rebalances") is not None:
        facts.append(f"리밸런싱을 {view['n_rebalances']}번 했어요.")
    trust = []
    if _is_practice(prov):
        trust.append(_t(UNKNOWN, _PRACTICE))
    # 파라미터가 먼저 — 엔진이 실제로 받은 값이다. 없으면 결과의 config 를 본다.
    bps = getattr(params, "cost_bps", None)
    if bps is None:
        bps = cfg.get("cost_bps")
    if bps is not None:
        trust.append(_t(ASSUMED, f"거래비용은 한 번 사고팔 때마다 {_pct(float(bps) / 100, 2)}로 가정했어요."))
    la = view.get("lookahead_evidence") or {}
    for name in la.get("ok_axes") or []:
        trust.append(_t(CONFIRMED, f"{LOOKAHEAD_AXIS_LABELS.get(name, name)}: 확인했어요."))
    unmeasured = []
    for n in la.get("unknown_axes") or []:
        lab = LOOKAHEAD_AXIS_LABELS.get(n, n)
        unmeasured.append(f"{lab}{_josa(lab, '은', '는')} 재지 않았어요.")
    if view.get("belief_note"):
        trust.append(_t(ASSUMED, str(view["belief_note"])))
    return {"title": "과거에 이 규칙대로 했다면 이랬어요", "headline": headline, "facts": facts,
            "trust": trust, "unmeasured": unmeasured}


EXPLAINERS = {
    "universe": explain_universe, "returns": explain_returns, "views": explain_views,
    "estimate": explain_estimate, "optimizer": explain_optimizer, "risk": explain_risk,
    "backtest": explain_backtest,
}
