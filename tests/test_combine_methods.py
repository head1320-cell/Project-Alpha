"""BS4 — 합치기 방법(고를 때만) · 조용한 대체 드러내기 · 방법 비교표
==============================================================================
설계 `docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md` §BS4. ★사용자 승인(2026-09-29)★: 기본값(risk_parity)은
그대로 두고, 고를 때만 쓰이는 방법을 더한다(CLAUDE.md §3 별도 승인 사항). 기존 방법의 답은 `test_bs4_golden.py` 가 건다.

거는 것:
- 새 방법 셋 — `manual`(몫 직접) · `crisis_risk_parity`(위기일 공분산으로 위험 균형) · `max_diversification`(분산 효과 최대).
  ★입력·풀이가 모자라면 실패 + 사유★ — 평소 공분산이나 다른 방법으로 조용히 가지 않는다.
- 엔진의 조용한 대체(점수·위험 예산 입력 없음 → 위험 똑같이 · 흔들림 최소·HRP 풀이 실패 → 역변동성 · 모르는 방식)를
  `fallback{used, from, reason}` 로 드러낸다 — 값은 그대로(골든).
- 방법 비교표는 관측이다 — "어느 방법이 낫다는 뜻이 아니에요".
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import sleeve_combine as sc  # noqa: E402
from tests.test_bs4_golden import _inputs  # noqa: E402


def _run(**kw):
    sleeves, rm = _inputs()
    return sc.combine_sleeves(sleeves, ret_matrix=rm, **kw)


# ── 대체 드러내기 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method", ["equal", "inverse_vol", "risk_parity", "min_var", "hrp"])
def test_no_fallback_is_reported_as_not_used(method):
    fb = _run(method=method)["fallback"]
    assert fb == {"used": False, "from": None, "reason": None}


@pytest.mark.parametrize("method,word", [("score", "점수"), ("risk_budget", "위험 예산"), ("whatever", "모르는")])
def test_missing_inputs_or_unknown_method_say_they_fell_back_to_risk_parity(method, word):
    out = _run(method=method)
    fb = out["fallback"]
    assert fb["used"] is True and fb["from"] == method and word in fb["reason"] and "위험 똑같이" in fb["reason"]
    assert out["sleeve_allocation"] == _run(method="risk_parity")["sleeve_allocation"]   # 값은 그대로


def test_score_with_scores_does_not_fall_back_pair():
    assert _run(method="score", scores={"가": 3.0, "나": 1.0, "다": 0.0})["fallback"]["used"] is False


def test_all_zero_scores_say_they_split_equally():
    out = _run(method="score", scores={"가": 0.0, "나": 0.0, "다": 0.0})
    assert out["fallback"]["used"] is True and "똑같이" in out["fallback"]["reason"]
    assert out["sleeve_allocation"] == _run(method="equal")["sleeve_allocation"]


def test_min_var_that_does_not_solve_says_it_used_inverse_vol(monkeypatch):
    from src.engine import risk_allocations as ra
    monkeypatch.setattr(ra, "_opt", lambda f, n: None)
    out = _run(method="min_var")
    assert out["fallback"]["used"] is True and "역변동성" in out["fallback"]["reason"]
    assert out["sleeve_allocation"] == _run(method="inverse_vol")["sleeve_allocation"]


def test_hrp_that_raises_says_it_used_inverse_vol(monkeypatch):
    from src.engine import risk_allocations as ra

    def boom(cov):
        raise RuntimeError("x")
    monkeypatch.setattr(ra, "_hrp_weights", boom)
    out = _run(method="hrp")
    assert out["fallback"]["used"] is True and out["fallback"]["from"] == "hrp"
    assert out["sleeve_allocation"] == _run(method="inverse_vol")["sleeve_allocation"]


# ── 몫 직접 정하기 ──────────────────────────────────────────────────────────────

def test_manual_shares_are_used_as_given():
    out = _run(method="manual", shares={"가": 50.0, "나": 30.0, "다": 20.0})
    assert out["sleeve_allocation"] == {"가": 50.0, "나": 30.0, "다": 20.0}
    assert out["fallback"]["used"] is False


@pytest.mark.parametrize("shares,word", [
    (None, "몫"), ({"가": 50.0, "나": 30.0}, "다"), ({"가": 50.0, "나": 30.0, "다": 10.0}, "100"),
    ({"가": 120.0, "나": -20.0, "다": 0.0}, "음수"),
])
def test_manual_without_proper_shares_fails_with_a_reason(shares, word):
    out = _run(method="manual", shares=shares)
    assert out["error"] is True and word in out["message"]


def test_manual_sum_within_rounding_is_accepted_pair():
    assert _run(method="manual", shares={"가": 33.33, "나": 33.33, "다": 33.34})["error"] is False


# ── 위기 때 위험 균형 ────────────────────────────────────────────────────────────

def _crisis_inputs(T=300, seed=5):
    """'다' 는 평소엔 조용하다가 시장이 가장 나쁜 날 크게 같이 떨어진다 — 평소 공분산은 이를 거의 못 본다."""
    rng = np.random.default_rng(seed)
    m = rng.normal(0, 0.01, T)
    bad = m <= np.quantile(m, 0.1)
    codes = ["A", "B", "C"]
    R = rng.normal(0, 0.008, (T, 3))
    R[bad, 2] += 3.0 * m[bad]
    rm = {c: [float(x) for x in R[:, i]] for i, c in enumerate(codes)}
    sleeves = [{"name": "가", "weights": {"A": 1.0}}, {"name": "나", "weights": {"B": 1.0}}, {"name": "다", "weights": {"C": 1.0}}]
    return sleeves, rm, m.tolist(), bad


def test_crisis_risk_parity_balances_risk_on_the_worst_market_days():
    sleeves, rm, m, bad = _crisis_inputs()
    out = sc.combine_sleeves(sleeves, method="crisis_risk_parity", ret_matrix=rm, market_returns=m)
    assert out["error"] is False and out["fallback"]["used"] is False
    names, S = sc._sleeve_return_series(sleeves, rm)
    want = sc._risk_budget_weights(sc._crisis_moment(S[bad]), np.ones(3))
    assert out["sleeve_allocation"] == {n: round(float(w) * 100, 2) for n, w in zip(names, want)}
    assert out["crisis"]["days"] == int(bad.sum()) and out["crisis"]["q"] == 0.1


def test_crisis_risk_parity_gives_less_to_the_one_that_falls_with_the_market_pair():
    sleeves, rm, m, _ = _crisis_inputs()
    crisis = sc.combine_sleeves(sleeves, method="crisis_risk_parity", ret_matrix=rm, market_returns=m)["sleeve_allocation"]
    normal = sc.combine_sleeves(sleeves, method="risk_parity", ret_matrix=rm)["sleeve_allocation"]
    assert crisis["다"] < normal["다"] - 5


def test_crisis_moment_keeps_the_common_fall_that_a_covariance_removes():
    """위기일마다 똑같이 −3% 인 전략 — 공분산(평균을 뺌)은 0 이지만 적률은 9e-4 다. 같이 잃은 크기를 본다."""
    Sc = np.column_stack([np.full(30, -0.03), np.random.default_rng(1).normal(0, 0.01, 30)])
    M = sc._crisis_moment(Sc)
    assert M[0, 0] == pytest.approx(9e-4, rel=1e-6)
    assert np.cov(Sc.T)[0, 0] == pytest.approx(0.0, abs=1e-15)


def test_crisis_risk_parity_without_a_market_fails_instead_of_using_normal_days():
    sleeves, rm, _, _ = _crisis_inputs()
    out = sc.combine_sleeves(sleeves, method="crisis_risk_parity", ret_matrix=rm)
    assert out["error"] is True and "시장" in out["message"]


def test_crisis_risk_parity_with_too_few_crisis_days_fails():
    sleeves, rm, m, _ = _crisis_inputs(T=150)
    out = sc.combine_sleeves(sleeves, method="crisis_risk_parity", ret_matrix=rm, market_returns=m)
    assert out["error"] is True and "위기일" in out["message"] and str(sc.CRISIS_MIN_DAYS) in out["message"]


def test_crisis_market_shorter_than_the_strategies_fails():
    sleeves, rm, m, _ = _crisis_inputs()
    out = sc.combine_sleeves(sleeves, method="crisis_risk_parity", ret_matrix=rm, market_returns=m[:100])
    assert out["error"] is True and "짧" in out["message"]


# ── 분산 효과 최대 ───────────────────────────────────────────────────────────────

def _dr(alloc: dict, sleeves, rm) -> float:
    names, S = sc._sleeve_return_series(sleeves, rm)
    cov = sc._cov_local(S)
    w = np.array([alloc[n] for n in names]) / 100.0
    return float(w @ np.sqrt(np.diag(cov)) / np.sqrt(w @ cov @ w))


def test_max_diversification_is_not_below_the_other_methods_on_its_own_measure():
    sleeves, rm = _inputs()
    best = _dr(_run(method="max_diversification")["sleeve_allocation"], sleeves, rm)
    for m in ("equal", "inverse_vol", "risk_parity", "min_var", "hrp"):
        assert best >= _dr(_run(method=m)["sleeve_allocation"], sleeves, rm) - 1e-3, m


def test_max_diversification_that_does_not_solve_fails_pair(monkeypatch):
    from src.engine import risk_allocations as ra
    monkeypatch.setattr(ra, "_opt", lambda f, n: None)
    out = _run(method="max_diversification")
    assert out["error"] is True and "풀리지" in out["message"]


def test_new_methods_are_listed_and_the_default_is_unchanged():
    import inspect
    for m in ("manual", "crisis_risk_parity", "max_diversification"):
        assert m in sc.SLEEVE_METHODS
    assert inspect.signature(sc.combine_sleeves).parameters["method"].default == "risk_parity"


# ── 방법 비교표 (관측) ────────────────────────────────────────────────────────────

def test_method_table_compares_input_free_methods_on_the_same_flows():
    sleeves, rm = _inputs()
    t = sc.compare_sleeve_methods(sleeves, ret_matrix=rm)
    rows = {r["method"]: r for r in t["rows"]}
    assert set(rows) == {"risk_parity", "equal", "inverse_vol", "min_var", "hrp", "max_diversification", "crisis_risk_parity"}
    # 같은 흐름 — 각 줄의 몫은 그 방법으로 직접 합친 몫과 같다.
    for m in ("risk_parity", "equal", "min_var", "max_diversification"):
        assert rows[m]["shares"] == _run(method=m)["sleeve_allocation"], m
        r = rows[m]
        assert r["available"] and r["vol_pct"] > 0 and r["div_ratio"] >= 1.0 - 1e-9 and 1.0 <= r["effective_n"] <= 3.0 + 1e-9
    assert rows["equal"]["effective_n"] == pytest.approx(3.0, abs=1e-3)
    # 시장이 없으면 위기 줄은 사유와 함께 비어 있다(평소 공분산으로 채우지 않는다).
    assert rows["crisis_risk_parity"]["available"] is False and "시장" in rows["crisis_risk_parity"]["reason"]
    assert "낫다는 뜻이 아니에요" in t["note"]


def test_method_table_with_a_market_fills_the_crisis_row_pair():
    sleeves, rm, m, _ = _crisis_inputs()
    rows = {r["method"]: r for r in sc.compare_sleeve_methods(sleeves, ret_matrix=rm, market_returns=m)["rows"]}
    assert rows["crisis_risk_parity"]["available"] is True
    assert rows["crisis_risk_parity"]["shares"] == sc.combine_sleeves(
        sleeves, method="crisis_risk_parity", ret_matrix=rm, market_returns=m)["sleeve_allocation"]


def test_method_table_marks_a_fallback_row(monkeypatch):
    from src.engine import risk_allocations as ra
    sleeves, rm = _inputs()
    monkeypatch.setattr(ra, "_opt", lambda f, n: None)
    rows = {r["method"]: r for r in sc.compare_sleeve_methods(sleeves, ret_matrix=rm)["rows"]}
    assert rows["min_var"]["fallback"]["used"] is True
    assert rows["max_diversification"]["available"] is False and "풀리지" in rows["max_diversification"]["reason"]


# ── 노드 `portfolio_combine` ───────────────────────────────────────────────────

from tests.test_allocation_graph import market  # noqa: E402,F401
from tests.test_graph_portfolio_combine import _graph  # noqa: E402


def _node(**params):
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    return pg.run(_graph(3, **params), gn.REGISTRY)["nodes"]["p"]


def _trust(r) -> str:
    return " ".join(t["text"] for t in r["explain"]["trust"])


def test_the_node_offers_the_new_methods_with_the_same_default():
    from src.api import allocation_graph_nodes_portfolio as npf
    m = npf.PortfolioCombineParams.model_fields["method"]
    assert m.default == "risk_parity"
    for k in ("score", "risk_budget", "manual", "crisis_risk_parity", "max_diversification"):
        assert k in npf.METHODS and k in npf.METHOD_HELP
    ui = m.json_schema_extra["x-ui"]
    assert ui["order"][0] == "risk_parity" and set(ui["order"]) == set(npf.METHODS)
    assert set(ui["descriptions"]) == set(npf.METHODS)


@pytest.mark.parametrize("method,field,word", [("score", "scores", "점수"), ("risk_budget", "budgets", "위험 예산"),
                                                ("manual", "shares", "몫")])
def test_methods_that_need_numbers_fail_without_them_instead_of_falling_back(market, method, field, word):
    r = _node(method=method)
    assert r["status"] == "failed" and word in r["reason"] and "전략 1" in r["reason"]


def test_manual_shares_by_port_become_the_shares(market):
    r = _node(method="manual", shares={"s1": 50, "s2": 30, "s3": 20})
    assert r["status"] == "ok", r["reason"]
    assert [s["share_pct"] for s in r["view"]["strategies"]] == [50.0, 30.0, 20.0]
    assert "내가 정한 몫" in _trust(r)


def test_manual_shares_that_do_not_add_up_fail_pair(market):
    r = _node(method="manual", shares={"s1": 50, "s2": 30, "s3": 10})
    assert r["status"] == "failed" and "100" in r["reason"]


def test_budgets_must_add_up_to_100(market):
    ok = _node(method="risk_budget", budgets={"s1": 50, "s2": 30, "s3": 20})
    assert ok["status"] == "ok" and "내가 정한 위험 예산" in _trust(ok)
    bad = _node(method="risk_budget", budgets={"s1": 50, "s2": 30, "s3": 30})
    assert bad["status"] == "failed" and "100" in bad["reason"]


def test_scores_all_zero_fail(market):
    assert _node(method="score", scores={"s1": 0, "s2": 0, "s3": 0})["status"] == "failed"
    ok = _node(method="score", scores={"s1": 3, "s2": 1, "s3": 0})
    assert ok["status"] == "ok" and [s["share_pct"] for s in ok["view"]["strategies"]] == [75.0, 25.0, 0.0]


def test_a_number_for_an_unknown_port_is_rejected():
    from pydantic import ValidationError

    from src.api import allocation_graph_nodes_portfolio as npf
    with pytest.raises(ValidationError):
        npf.PortfolioCombineParams(method="manual", shares={"s9": 100})
    with pytest.raises(ValidationError):
        npf.PortfolioCombineParams(method="manual", shares={"s1": -5})


def test_crisis_risk_parity_uses_the_market_proxy_and_says_so(market):
    r = _node(method="crisis_risk_parity")
    assert r["status"] == "ok", r["reason"]
    c = r["view"]["result"]["crisis"]
    assert c["days"] >= 20 and r["view"]["market"]["label"] == "KODEX 200"
    t = _trust(r)
    assert "KODEX 200" in t and "가장 나빴던" in t and f"{c['days']}일" in t


def test_crisis_risk_parity_with_mixed_markets_fails_with_the_reason(market, monkeypatch):
    from src.api import robustness_inputs as ri
    monkeypatch.setattr(ri, "market_proxy", lambda tickers: {"ticker": None, "label": None,
                                                            "reason": "한국·미국 종목이 섞여 있어 시장 하나로 위기일을 고를 수 없어요"})
    r = _node(method="crisis_risk_parity")
    assert r["status"] == "failed" and "섞여" in r["reason"]


def test_max_diversification_runs_and_says_what_it_assumes(market):
    r = _node(method="max_diversification")
    assert r["status"] == "ok", r["reason"]
    assert "분산 효과" in _trust(r)


def test_the_view_carries_the_method_table_with_the_current_method(market):
    r = _node()
    mc = r["view"]["method_compare"]
    assert mc["available"] and mc["current"] == "risk_parity"
    rows = {x["method"]: x for x in mc["rows"]}
    assert rows["risk_parity"]["shares"] == r["view"]["result"]["sleeve_allocation"]
    assert rows["crisis_risk_parity"]["available"] is True           # mock 에서는 KODEX 200 이 있다
    assert "낫다는 뜻이 아니에요" in mc["note"]
    assert {x["method"]: x["label"] for x in mc["rows"]}["max_diversification"] == "분산 효과 최대"
