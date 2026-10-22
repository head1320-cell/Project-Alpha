"""전달 점검 — 선마다 ★건너간 것★과 ★빠지거나 바뀐 것★ (CF3, 사용자 결정 2026-10-17)
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §CF3.

선을 건너며 값이 말없이 빠지거나 바뀌는 곳이 있다(날짜 교집합이 버린 날 · 유니버스 밖이라 빠진 생각의 다리 · 역변동성으로
대신한 비중 · 다른 방식으로 다시 푼 민감도 …). 퀀트가 설계를 믿고 쓰려면 그것이 선에서 보여야 한다.

- **사실(facts)** — 출력 포트 타입별로 값에서 잰 것만. ★좋다·나쁘다 말하지 않는다★(문턱을 지어내지 않는다). 조건수·T/N 은 숫자뿐.
- **문제(issues)** — 받는 쪽 (종류, 입력 포트)별 규칙. 네 단계: `lost`(빠짐) · `changed`(바뀜) · `structural`(수학적 사실) ·
  `unused`(이어져 있지만 읽지 않음). 근거는 이미 계산된 view·값뿐이다 — 새로 계산하지 않는다.
- ★계산을 바꾸지 않는다★ — 값을 읽기만 한다(`tests/test_graph_handoff_rules.py` 가 값 불변을 건다).

엔진 고리는 `portfolio_graph.Registry.set_port_facts / set_port_intake / set_intake`. 등록은 `register()` 한 곳에서.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from src.engine import portfolio_graph as pg

#: 비중 잡음 기준 — `_w_dict` 와 같은 값(새 문턱이 아니다).
_W_NOISE = 0.0005


def _f(key: str, label: str, text: str, value: Any = None) -> dict:
    return {"key": key, "label": label, "text": text, "value": value}


def _i(level: str, code: str, text: str, fix: str | None = None) -> dict:
    return {"level": level, "code": code, "text": text, **({"fix": fix} if fix else {})}


def _num(x: float, digits: int = 0) -> str:
    return f"{x:,.{digits}f}"


def _names(codes: list[str], k: int = 5) -> str:
    head = ", ".join(str(c) for c in codes[:k])
    return head + (f" 외 {len(codes) - k}개" if len(codes) > k else "")


# ── 사실 ─────────────────────────────────────────────────────────────────────

def facts_returns(v: dict) -> list[dict]:
    R = v.get("returns")
    T, N = (int(R.shape[0]), int(R.shape[1])) if R is not None else (0, 0)
    cov = v.get("coverage") or {}
    out = [_f("n_assets", "종목", f"{N}개", N),
           _f("n_obs", "기간", f"{T}일 · {cov.get('start')}~{cov.get('end')}", T)]
    if N:
        out.append(_f("t_over_n", "종목당 관측", f"{T / N:,.0f}일 (관측 {T} ÷ 종목 {N})", round(T / N, 2)))
    a = cov.get("alignment")
    if a is None:
        out.append(_f("alignment", "날짜 맞추기", "재지 않았어요"))
    else:
        out.append(_f("requested", "요청한 기간", f"{a['requested_days']}일 · 모자란 날 {a['shortfall_days']}일",
                      a["shortfall_days"]))
        out.append(_f("holes", "창 안의 빈 날", f"{a['holes_in_window']}일(어느 한 종목이라도 비어 통째로 빠진 날)",
                      a["holes_in_window"]))
        ls = a.get("latest_start")
        if ls:
            out.append(_f("latest_start", "가장 늦게 시작한 종목",
                          f"{ls['ticker']} · {ls['first']}" + (" — 이 종목이 기간의 시작을 정했어요" if a.get("binding") else ""),
                          ls["ticker"]))
    ex = v.get("excluded") or []
    if ex:
        out.append(_f("excluded", "뺀 종목", f"{len(ex)}개 · " + _names([x.get("ticker") for x in ex]), len(ex)))
    bench_name = (v.get("universe") or {}).get("benchmark")
    if bench_name:
        gap = (a or {}).get("bench_gap_days")
        out.append(_f("bench", "벤치마크", f"{bench_name}" + (f" · 빈 날 {gap}일" if gap is not None else "")
                      + ("" if v.get("bench") is not None else " · 받지 못했어요"), gap))
    if cov.get("as_of_effective"):
        out.append(_f("as_of", "기준일", str(cov["as_of_effective"])))
    return out


# 공분산 출처 코드 → 쉬운 말(모르는 코드는 그대로 — 지어내지 않는다).
_SIGMA_PLAIN = {"trailing": "지난 수익률로 잰 공분산", "sample_252": "최근 252일 표본 공분산", "conditional": "국면 조건부 공분산"}


def facts_weights(v: dict) -> list[dict]:
    w = np.asarray(v.get("weights"), dtype=float)
    names = list(v.get("names") or [])
    out = [_f("n", "종목", f"{len(names)}개", len(names))]
    if w.size:
        k = int((np.abs(w) > _W_NOISE).sum())
        out.append(_f("k", "비중이 있는 종목", f"{k}개", k))
        s = float(w.sum())
        out.append(_f("sum", "비중 합", f"{s * 100:.1f}%", round(s * 100, 2)))
        if (w < 0).any():
            g = float(np.abs(w).sum())
            out.append(_f("gross", "비중 절댓값 합", f"{g * 100:.1f}%", round(g * 100, 2)))
        i = int(np.argmax(np.abs(w)))
        out.append(_f("max", "가장 큰 비중", f"{names[i] if i < len(names) else i} {w[i] * 100:.1f}%",
                      round(float(w[i]) * 100, 2)))
        if (w >= 0).all() and s > 0:
            neff = 1.0 / float(((w / s) ** 2).sum())
            out.append(_f("neff", "실질 종목 수(1/Σw²)", f"{neff:.1f}개", round(neff, 2)))
    sig = v.get("sigma_annual")
    src = v.get("sigma_source")
    out.append(_f("sigma", "함께 보낸 공분산",
                  (_SIGMA_PLAIN.get(str(src), str(src)) if src else "있음") if sig is not None else "없음"))
    if sig is not None:
        S = np.asarray(sig, dtype=float)
        if S.ndim == 2 and S.shape[0] == S.shape[1] and S.size and np.isfinite(S).all():
            ev = np.linalg.eigvalsh((S + S.T) / 2.0)
            if ev[0] <= 0:
                out.append(_f("cond", "공분산 조건수", "특이(가장 작은 고유값이 0 이하)"))
            else:
                c = float(ev[-1] / ev[0])
                out.append(_f("cond", "공분산 조건수", f"{c:.1f}" if c < 100 else f"{c:,.0f}", round(c, 2)))
    req = v.get("req")
    if req is not None and getattr(req, "model", None):
        from src.api.allocation_graph_explain import MODEL_PLAIN
        out.append(_f("rule", "만든 규칙", MODEL_PLAIN.get(req.model, req.model), req.model))
    return out


def facts_views(v: list) -> list[dict]:
    views = list(v or [])
    weighted = sum(1 for x in views if (x or {}).get("weights"))
    company = sum(1 for x in views if (x or {}).get("source"))
    out = [_f("n", "생각", f"{len(views)}개", len(views)),
           _f("kinds", "종류", f"한 종목·여러 종목 평균 {len(views) - weighted}개 · 조합(상대) {weighted}개", weighted)]
    if company:
        out.append(_f("company", "회사 가치에서 온 생각", f"{company}개", company))
    return out


def facts_scores(v: dict) -> list[dict]:
    sc = (v or {}).get("scores") or {}
    unknown = sum(1 for x in sc.values() if not isinstance(x, (int, float)) or not np.isfinite(float(x)))
    out = [_f("n", "점수 받은 종목", f"{len(sc)}개", len(sc)), _f("unknown", "점수를 모르는 종목", f"{unknown}개", unknown)]
    if (v or {}).get("kind"):
        out.append(_f("kind", "점수 종류", str(v["kind"])))
    if (v or {}).get("as_of"):
        out.append(_f("as_of", "기준일", str(v["as_of"])))
    return out


def facts_belief(v: dict) -> list[dict]:
    v = v or {}
    return [_f("conditional", "경기 국면 반영", "요청했어요" if v.get("conditional") else "하지 않아요(과거 기준)",
               bool(v.get("conditional")))]


def facts_universe(v: dict) -> list[dict]:
    v = v or {}
    t = list(v.get("tickers") or [])
    return [_f("n", "종목", f"{len(t)}개 · " + _names(t), len(t)),
            _f("bench", "벤치마크", str(v.get("benchmark") or "없음")),
            _f("current", "지금 비중", "함께 보내요" if v.get("weights") else "없어요")]


def facts_regime(v: dict) -> list[dict]:
    v = v or {}
    out = [_f("regime", "국면", str(v.get("regime") or "몰라요"))]
    for key, label in (("snapshot_id", "스냅샷"), ("as_of", "기준일"), ("data_status", "데이터 상태")):
        if v.get(key) is not None:
            out.append(_f(key, label, str(v[key])))
    return out


def facts_timing(v: dict) -> list[dict]:
    v = v or {}
    states = [getattr(s, "value", s) for s in v.get("states") or []]
    u = sum(1 for s in states if s == "unavailable")
    out = [_f("n", "신호", f"{len(states)}개 · 읽지 못함 {u}개", len(states)), _f("unread", "읽지 못한 신호", f"{u}개", u)]
    if v.get("combination"):
        out.append(_f("combination", "합치는 규칙", str(v["combination"])))
    if v.get("as_of"):
        out.append(_f("as_of", "기준일", str(v["as_of"])))
    return out


FACTS: dict[str, Callable[[Any], list[dict]]] = {
    "Returns": facts_returns, "Weights": facts_weights, "Views": facts_views, "Scores": facts_scores,
    "Belief": facts_belief, "Universe": facts_universe, "RegimeState": facts_regime, "TimingSignal": facts_timing,
}


# ── 문제 규칙 ────────────────────────────────────────────────────────────────

def _out(checks: list[str], issues: list[dict]) -> dict:
    return {"checks": checks, "issues": issues}


def _structural_returns(value: dict) -> list[dict]:
    """R2 — T ≤ N 이면 표본 공분산이 특이하다(수학적 사실, 문턱 아님)."""
    R = (value or {}).get("returns")
    if R is None:
        return []
    T, N = int(R.shape[0]), int(R.shape[1])
    if N and T <= N:
        return [_i("structural", "t_le_n", f"관측 {T}일이 종목 {N}개보다 많지 않아 표본 공분산이 특이해요 — "
                                           "역행렬을 쓰는 계산은 축소 추정에 기대요.")]
    return []


_R2_CHECK = "관측 일수가 종목 수보다 많은지(공분산이 특이하지 않은지)"


def intake_returns_default(h: pg.Handoff) -> dict:
    return _out([_R2_CHECK], _structural_returns(h.value))


def intake_weights_default(h: pg.Handoff) -> dict:
    """R7 — 상류가 요청한 방식 대신 다른 비중을 냈으면 그 사실이 이 자리로 흘러온다."""
    fb = [f for f in ((h.source_view or {}).get("fallbacks") or []) if f.get("affects_weights")]
    return _out(["비중을 만든 쪽이 고른 방식 대신 다른 비중을 냈는지"],
                [_i("changed", f"fallback_{f.get('stage')}", str(f.get("text") or f.get("reason") or "")) for f in fb])


def intake_returns_from_universe(h: pg.Handoff) -> dict:
    """R1 — 수익률 불러오기가 받은 종목·기간 중 잃은 것."""
    view = h.view or {}
    cov = view.get("coverage") or {}
    a = cov.get("alignment") or {}
    issues = []
    ex = view.get("excluded") or []
    if ex:
        issues.append(_i("lost", "excluded", f"종목 {len(ex)}개는 시세가 없거나 짧아 빠졌어요: "
                                             + _names([f"{x.get('ticker')}({x.get('reason')})" for x in ex], 3)))
    if a.get("shortfall_days"):
        ls = a.get("latest_start") or {}
        why = (f" — {ls.get('ticker')}가 {ls.get('first')}에 시작해 기간을 묶었어요" if a.get("binding") else "")
        issues.append(_i("lost", "shortfall", f"요청한 {a['requested_days']}일 중 {a['shortfall_days']}일이 모자라요{why}.",
                         "늦게 시작한 종목을 빼거나 기간을 줄이면 날이 맞아요." if a.get("binding") else None))
    if a.get("holes_in_window"):
        issues.append(_i("lost", "holes", f"기간 안에서 {a['holes_in_window']}일은 어느 한 종목이 비어 모든 종목에서 빠졌어요."))
    bench = (h.value or {}).get("benchmark")
    if bench and not cov.get("benchmark_available"):
        issues.append(_i("lost", "no_bench", f"벤치마크 {bench}의 수익률을 받지 못했어요 — 벤치마크를 쓰는 계산(베타 제약 등)은 빠져요."))
    return _out(["뺀 종목", "요청한 기간과 실제 기간", "기간 안의 빈 날", "벤치마크"], issues)


def intake_unused_returns(h: pg.Handoff) -> dict:
    """R3 — 기대 수익 추정은 들어오는 수익률을 읽지 않는다(설정만 넘긴다 — 입력을 바꾸는 일은 별도 승인)."""
    return _out(["받는 쪽이 이 값을 읽는지"],
                [_i("unused", "not_read", "‘기대 수익 추정’은 이 수익률을 읽지 않아요 — 설정만 ‘비중 계산’에 넘기고, "
                                          "기대 수익은 ‘비중 계산’이 자기 수익률로 계산해요.")])


def _beta_active(params: Any) -> bool:
    c = getattr(params, "constraints", None)
    return c is not None and (getattr(c, "beta_min", None) is not None or getattr(c, "beta_max", None) is not None)


def intake_optimizer_returns(h: pg.Handoff) -> dict:
    """R4 — R2 + 베타 제약을 걸었는데 벤치마크에 빈 날이 있으면 제약이 빠진다."""
    issues = _structural_returns(h.value)
    gap = (((h.value or {}).get("coverage") or {}).get("alignment") or {}).get("bench_gap_days")
    if _beta_active(h.params) and gap:
        issues.append(_i("changed", "beta_dropped", f"벤치마크가 기간 중 {gap}일 비어 기간 길이가 맞지 않아 "
                                                    "베타 제약을 걸지 못했어요."))
    return _out([_R2_CHECK, "베타 제약에 쓸 벤치마크가 기간 전체에 있는지"], issues)


def intake_optimizer_views(h: pg.Handoff) -> dict:
    """R5 — 생각이 쓰이지 않거나 · 빠지거나 · 다리를 잃거나 · 시장 비중으로 대신했는지."""
    view = h.view or {}
    issues = []
    if view.get("views_unused"):
        issues.append(_i("unused", "views_unused", f"이 계산 방식은 생각을 쓰지 않아요 — 이어진 생각 {view['views_unused']}개가 비중에 들어가지 않아요.",
                         "‘내 생각 반영’ 방식을 고르면 비중에 들어가요."))
    skipped = [s for s in view.get("skipped_views") or [] if ((s or {}).get("view") or {}).get("source") != "conditional"]
    if skipped:
        issues.append(_i("lost", "skipped", f"생각 {len(skipped)}개는 쓸 수 없어 빠졌어요 — " + str(skipped[0].get("reason") or "")))
    for leg in view.get("view_legs_dropped") or []:
        issues.append(_i("changed", "legs_dropped", f"생각 {leg['index'] + 1}({leg.get('label')})은 유니버스 밖 종목 "
                                                     f"{_names(leg.get('dropped') or [], 3)}이 빠져 나머지만 반영됐어요.",
                         "빠진 종목을 ‘종목 고르기’에 넣거나 생각에서 빼세요."))
    for f in view.get("fallbacks") or []:
        if f.get("stage") == "view_applied" and f.get("affects_weights"):
            issues.append(_i("changed", "views_market", str(f.get("text") or f.get("reason") or "")))
    return _out(["이 방식이 생각을 쓰는지", "빠진 생각", "다리를 잃은 생각", "생각을 넣은 비중을 풀었는지"], issues)


def intake_optimizer_belief(h: pg.Handoff) -> dict:
    """R6 — 경기 국면 반영을 요청했는데 막혀 과거 기준으로 계산했는지."""
    b = (h.view or {}).get("belief") or {}
    issues = ([_i("changed", "belief_blocked", "경기 국면 반영을 요청했지만 막혀 과거 기준으로 계산했어요 — "
                                               + str(b.get("blocked_reason") or ""))] if b.get("blocked") else [])
    return _out(["요청한 기대 수익 방식으로 계산했는지"], issues)


def intake_backtest_returns(h: pg.Handoff) -> dict:
    """R8 — R2 + 벤치마크 빈 날은 0 수익으로 채워 비교한다(`allocation_routes` 백테스트)."""
    issues = _structural_returns(h.value)
    gap = (((h.value or {}).get("coverage") or {}).get("alignment") or {}).get("bench_gap_days")
    if gap:
        issues.append(_i("changed", "bench_zero_fill", f"벤치마크가 빈 {gap}일은 수익 0으로 채워 비교해요."))
    return _out([_R2_CHECK, "벤치마크 빈 날"], issues)


def intake_backtest_weights(h: pg.Handoff) -> dict:
    """R9 — R7 + 백테스트는 비중이 아니라 규칙을 자기 수익률로 다시 푼다. 그때 넘어가지 않는 것들."""
    base = intake_weights_default(h)
    issues = list(base["issues"])
    w = h.value or {}
    req = w.get("req")
    r = (h.inputs or {}).get("returns") or {}
    if req is not None and r:
        diff = []
        if list(req.tickers) != list((r.get("universe") or {}).get("tickers") or []):
            diff.append("종목")
        if req.lookback_days != r.get("lookback_days"):
            diff.append("기간")
        if req.as_of != r.get("as_of"):
            diff.append("기준일")
        if diff:
            issues.append(_i("changed", "other_returns", f"규칙을 다른 수익률({'·'.join(diff)})로 다시 풀어요 — 받은 비중과 같은 비중이 아니에요."))
        if req.model == "mv_utility" and req.risk_aversion is not None:
            from src.engine.allocation_studio import RISK_AVERSION_DEFAULT
            issues.append(_i("changed", "lambda_dropped", f"위험 회피 λ {req.risk_aversion:g}는 백테스트로 넘어가지 않아 "
                                                          f"기본값 λ {RISK_AVERSION_DEFAULT:g}로 되돌려 봤어요."))
        if req.conditional:
            issues.append(_i("changed", "conditional_dropped", "경기 국면 반영은 백테스트로 넘어가지 않아 리밸런싱마다 과거 기준으로 풀어요."))
    used = ((w.get("opt") or {}).get("company_views_used")) or 0
    if used:
        issues.append(_i("lost", "company_views_dropped", f"회사 가치에서 온 생각 {used}개는 백테스트로 넘어가지 않아요."))
    return _out(base["checks"] + ["같은 수익률로 다시 푸는지", "위험 회피 λ", "경기 국면 반영", "회사 가치 생각"], issues)


def intake_sensitivity_weights(h: pg.Handoff) -> dict:
    """R10 — 민감도는 고른 방식이 아니라 BL/MVO 로 다시 풀고 제약을 뺀다."""
    base = intake_weights_default(h)
    issues = list(base["issues"])
    view = h.view or {}
    from src.api.allocation_graph_explain import MODEL_PLAIN
    model, basis = view.get("model"), view.get("basis")
    if model and basis and model != basis:
        issues.append(_i("changed", "other_model", f"‘{MODEL_PLAIN.get(model, model)}’ 비중을 받았지만 민감도는 "
                                                   f"‘{MODEL_PLAIN.get(basis, basis)}’ 방식으로 다시 풀어요."))
    if view.get("has_constraints"):
        issues.append(_i("lost", "constraints_dropped", "비중 계산에 건 제약은 민감도로 넘어가지 않아요."))
    req = (h.value or {}).get("req")
    if req is not None and getattr(req, "conditional", False):
        issues.append(_i("changed", "conditional_dropped", "경기 국면 반영은 민감도로 넘어가지 않아요."))
    return _out(base["checks"] + ["같은 방식으로 다시 푸는지", "제약", "경기 국면 반영"], issues)


def intake_s2w_scores(h: pg.Handoff) -> dict:
    """R11 — 점수 상위에 들었지만 비중이 0 으로 반올림돼 빠진 종목."""
    z = (h.view or {}).get("dropped_zero") or []
    issues = [_i("lost", "dropped_zero", f"점수 상위 {len(z)}개 종목은 비중이 0으로 반올림돼 빠졌어요: {_names(z)}")] if z else []
    return _out(["점수 상위 종목이 모두 비중을 받았는지"], issues)


def intake_s2w_returns(h: pg.Handoff) -> dict:
    """R12 — R2 + 수익률에 없는 종목이 있어 공분산을 함께 보내지 못함."""
    issues = _structural_returns(h.value)
    miss = (h.view or {}).get("sigma_missing") or {}
    if miss.get("reason") == "codes_missing":
        issues.append(_i("lost", "codes_missing", f"이 수익률에 없는 종목({_names(miss.get('codes') or [], 3)})이 있어 "
                                                  "공분산을 비중과 함께 보내지 못해요.",
                         "같은 종목으로 ‘수익률 불러오기’를 이어 주세요."))
    return _out([_R2_CHECK, "비중의 종목이 모두 이 수익률에 있는지"], issues)


def intake_overlay_signal(h: pg.Handoff) -> dict:
    """R13 — '직접 정할게요'면 신호를 적용하지 않는다 · 읽지 못한 신호가 섞였다."""
    view = h.view or {}
    issues = []
    if view.get("follow") == "manual":
        issues.append(_i("unused", "manual", "‘직접 정할게요’를 골라 이 신호는 나란히 보여 주기만 하고 적용하지 않아요."))
    elif view.get("unavailable"):
        issues.append(_i("lost", "unread", f"신호 {view.get('n_signals')}개 중 {view['unavailable']}개를 읽지 못한 채 노출을 정했어요."))
    return _out(["신호를 적용하는지", "읽지 못한 신호"], issues)


def intake_overlay_regime(h: pg.Handoff) -> dict:
    """R14 — '타이밍 + 경기 국면'을 고르지 않았으면 국면은 보여 주기만 한다."""
    view = h.view or {}
    issues = ([] if view.get("follow") == "timing_macro" else
              [_i("unused", "regime_shown_only", "‘타이밍 + 경기 국면’을 고르지 않아 경기 국면은 나란히 보여 주기만 하고 "
                                                 "비중에 적용하지 않아요.")])
    return _out(["경기 국면을 적용하는지"], issues)


#: (받는 종류, 입력 포트) → 규칙. 타입 기본(R2·R7)은 `PORT_INTAKES`.
INTAKES: dict[tuple[str, str], Callable[[pg.Handoff], dict]] = {
    ("returns", "universe"): intake_returns_from_universe,
    ("estimate", "returns"): intake_unused_returns,
    ("optimizer", "returns"): intake_optimizer_returns,
    ("optimizer", "views"): intake_optimizer_views,
    ("optimizer", "belief"): intake_optimizer_belief,
    ("backtest", "returns"): intake_backtest_returns,
    ("backtest", "weights"): intake_backtest_weights,
    ("sensitivity", "weights"): intake_sensitivity_weights,
    ("scores_to_weights", "scores"): intake_s2w_scores,
    ("scores_to_weights", "returns"): intake_s2w_returns,
    ("exposure_overlay", "signal"): intake_overlay_signal,
    ("exposure_overlay", "regime"): intake_overlay_regime,
}
PORT_INTAKES: dict[str, Callable[[pg.Handoff], dict]] = {
    "Returns": intake_returns_default, "Weights": intake_weights_default,
}


def register(registry: pg.Registry) -> None:
    for t, fn in FACTS.items():
        registry.set_port_facts(t, fn)
    for t, fn in PORT_INTAKES.items():
        registry.set_port_intake(t, fn)
    for (kind, port), fn in INTAKES.items():
        if registry.get(kind) is not None:
            registry.set_intake(kind, port, fn)
