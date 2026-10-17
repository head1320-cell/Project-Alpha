"""CF3 · 전달 점검 규칙 R1~R14 — 규칙마다 ★X / X 아님★ 짝 (실제 노드)
==============================================================================
대상 `src/api/allocation_graph_handoff.py`. 데이터는 `test_cf3_golden._frame`(늦은 상장 · 빈 날 · 벤치 빈 날)과 그 짝인
깨끗한 데이터. 사실(facts)은 잰 값뿐이라 평가하는 말이 없어야 하고, 규칙은 값을 바꾸지 않는다.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_handoff as ho  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_cf3_golden import AS_OF, T5, VIEWS, _chain, _edge, _node, _opt_none  # noqa: E402

#: 사실 글에 들어가면 안 되는 평가 말(문턱을 지어내지 않는다).
JUDGMENT = ("충분", "부족", "높아", "낮아", "좋", "나빠", "안전", "괜찮", "위험해")


def _clean_frame() -> pd.DataFrame:
    idx = pd.bdate_range(end=AS_OF, periods=1100)
    rng = np.random.default_rng(11)
    common = rng.normal(0.0003, 0.009, 1100)
    return pd.DataFrame({t: np.round((0.5 + 0.1 * i) * common + rng.normal(0.0002, 0.012, 1100), 6)
                         for i, t in enumerate([*T5, "KOSPI"])}, index=idx)


def _patch(monkeypatch, df):
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns", lambda tickers, start, end: df)
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 400000.0, "000660": 120000.0}.get(code, 50000.0))


@pytest.fixture()
def gappy(monkeypatch):
    from tests.test_cf3_golden import _frame
    _patch(monkeypatch, _frame())


@pytest.fixture()
def clean(monkeypatch):
    _patch(monkeypatch, _clean_frame())


def _edges(g):
    rep = pg.run(g, gn.REGISTRY)
    return rep["edges"], rep


def _codes(rec) -> set[str]:
    return {i["code"] for i in rec["issues"] or []}


# ── R1 수익률 ← 종목 ──────────────────────────────────────────────────────────

def test_r1_a_binding_late_listing_is_lost_days(gappy):
    e, _ = _edges(_chain("mvo", lookback=900))
    rec = e["u.universe->r.universe"]
    assert {"shortfall", "holes"} <= _codes(rec)
    short = next(i for i in rec["issues"] if i["code"] == "shortfall")
    assert short["level"] == "lost" and "068270" in short["text"] and "104일" in short["text"]


def test_r1_clean_data_loses_nothing(clean):
    e, _ = _edges(_chain("mvo"))
    assert e["u.universe->r.universe"]["issues"] == []


# ── R2 구조 ───────────────────────────────────────────────────────────────────

def _h(**kw) -> pg.Handoff:
    base = dict(edge_id="e", source="s", source_kind="x", source_port="p", target="t", target_kind="y",
                target_port="q", port_type="Returns", value=None, source_view=None, view=None, params=None, inputs={})
    base.update(kw)
    return pg.Handoff(**base)


def test_r2_t_not_more_than_n_is_structural():
    R = pd.DataFrame(np.zeros((3, 5)))
    out = ho.intake_returns_default(_h(value={"returns": R}))
    assert [i["level"] for i in out["issues"]] == ["structural"]


def test_r2_more_observations_than_assets_is_clean():
    out = ho.intake_returns_default(_h(value={"returns": pd.DataFrame(np.zeros((6, 5)))}))
    assert out["issues"] == [] and out["checks"]


# ── R3 기대 수익 추정 ← 수익률 ────────────────────────────────────────────────

def test_r3_estimate_does_not_read_returns(clean):
    e, _ = _edges(_chain("mvo"))
    assert [i["level"] for i in e["r.returns->e.returns"]["issues"]] == ["unused"]
    assert e["r.returns->o.returns"]["issues"] == []           # 짝 — 옵티마이저는 읽는다


# ── R4 옵티마이저 ← 수익률 (베타 제약) ───────────────────────────────────────

def test_r4_beta_constraint_with_benchmark_gaps_is_changed(gappy):
    e, _ = _edges(_chain("mvo", opt={"constraints": {"beta_max": 1.5}}))
    assert "beta_dropped" in _codes(e["r.returns->o.returns"])


def test_r4_no_beta_constraint_no_issue(gappy):
    e, _ = _edges(_chain("mvo", opt={"constraints": {"max_weight_pct": 40}}))
    assert "beta_dropped" not in _codes(e["r.returns->o.returns"])


def test_r4_beta_with_complete_benchmark_no_issue(clean):
    e, _ = _edges(_chain("mvo", opt={"constraints": {"beta_max": 1.5}}))
    assert "beta_dropped" not in _codes(e["r.returns->o.returns"])


# ── R5 옵티마이저 ← 생각 ──────────────────────────────────────────────────────

def test_r5_dropped_legs_are_changed(clean):
    e, _ = _edges(_chain("bl", views=VIEWS))
    rec = e["v.views->o.views"]
    legs = [i for i in rec["issues"] if i["code"] == "legs_dropped"]
    assert len(legs) == 2 and all(i["level"] == "changed" for i in legs)


def test_r5_views_into_a_model_that_ignores_them_are_unused(clean):
    e, _ = _edges(_chain("mvo", views=VIEWS[:1]))
    assert [i["code"] for i in e["v.views->o.views"]["issues"]] == ["views_unused"]


def test_r5_clean_views_into_bl(clean):
    e, _ = _edges(_chain("bl", views=VIEWS[:1]))
    assert e["v.views->o.views"]["issues"] == []


def test_r5_bl_market_fallback_is_changed(clean, monkeypatch):
    monkeypatch.setattr("src.engine.allocation_studio._opt", _opt_none)
    e, _ = _edges(_chain("bl", views=VIEWS[:1]))
    assert "views_market" in _codes(e["v.views->o.views"])


# ── R6 옵티마이저 ← 기대 수익 ─────────────────────────────────────────────────

def test_r6_blocked_belief_is_changed():
    out = ho.intake_optimizer_belief(_h(view={"belief": {"blocked": True, "blocked_reason": "관문"}}))
    assert [i["code"] for i in out["issues"]] == ["belief_blocked"]


def test_r6_unblocked_belief_is_clean():
    assert ho.intake_optimizer_belief(_h(view={"belief": {"blocked": False}}))["issues"] == []


# ── R7 비중 (타입 기본) ───────────────────────────────────────────────────────

def test_r7_fallback_flows_to_every_weights_consumer(clean, monkeypatch):
    monkeypatch.setattr("src.engine.allocation_studio._opt", _opt_none)
    e, _ = _edges(_chain("mvo"))
    assert [i["code"] for i in e["o.weights->k.weights"]["issues"]] == ["fallback_optimized"]


def test_r7_a_fallback_that_missed_the_weights_does_not_flow(clean, monkeypatch):
    """짝 — mvo 의 생각 단계 대체(비중에 닿지 않음)는 비중 선에 실리지 않는다."""
    from tests.test_cf3_golden import _raise
    monkeypatch.setattr("src.engine.allocation_studio.bl_posterior", _raise)
    e, rep = _edges(_chain("mvo", views=VIEWS[:1]))
    assert rep["nodes"]["o"]["view"]["fallbacks"]
    assert e["o.weights->k.weights"]["issues"] == []


def test_r7_no_fallback_clean(clean):
    e, _ = _edges(_chain("mvo"))
    assert e["o.weights->k.weights"]["issues"] == []


# ── R8·R9 백테스트 ───────────────────────────────────────────────────────────

def test_r8_benchmark_gap_days_are_zero_filled(gappy):
    e, _ = _edges(_chain("mvo", backtest={"rebalance": "Q"}))
    assert "bench_zero_fill" in _codes(e["r.returns->b.returns"])


def test_r8_complete_benchmark_clean(clean):
    e, _ = _edges(_chain("mvo", backtest={"rebalance": "Q"}))
    assert e["r.returns->b.returns"]["issues"] == []


def test_r9_lambda_is_not_carried(clean):
    e, _ = _edges(_chain("mv_utility", opt={"risk_aversion": 1.5}, backtest={"rebalance": "Q"}))
    lam = next(i for i in e["o.weights->b.weights"]["issues"] if i["code"] == "lambda_dropped")
    assert "1.5" in lam["text"] and "4" in lam["text"]


def test_r9_same_rule_same_returns_clean(clean):
    e, _ = _edges(_chain("mvo", backtest={"rebalance": "Q"}))
    assert e["o.weights->b.weights"]["issues"] == []


def test_r9_rule_solved_on_other_returns(clean):
    g = _chain("mvo")
    g["nodes"] += [_node("r2", "returns", lookback_days=900, as_of=AS_OF), _node("b", "backtest", rebalance="Q")]
    g["edges"] += [_edge("u", "universe", "r2", "universe"), _edge("r2", "returns", "b", "returns"),
                   _edge("o", "weights", "b", "weights")]
    e, _ = _edges(g)
    other = next(i for i in e["o.weights->b.weights"]["issues"] if i["code"] == "other_returns")
    assert "기간" in other["text"]


# ── R10 민감도 ───────────────────────────────────────────────────────────────

def _sens(model, **opt):
    g = _chain(model, opt=opt or None)
    g["nodes"].append(_node("s", "sensitivity"))
    g["edges"] += [_edge("r", "returns", "s", "returns"), _edge("o", "weights", "s", "weights")]
    return g


def test_r10_sensitivity_re_solves_with_another_model(clean):
    e, rep = _edges(_sens("risk_parity"))
    assert rep["nodes"]["s"]["status"] == "ok"
    assert "other_model" in _codes(e["o.weights->s.weights"])


def test_r10_same_model_clean(clean):
    e, _ = _edges(_sens("mvo"))
    assert e["o.weights->s.weights"]["issues"] == []


def test_r10_constraints_are_lost(clean):
    e, _ = _edges(_sens("mvo", constraints={"max_weight_pct": 40}))
    assert "constraints_dropped" in _codes(e["o.weights->s.weights"])


# ── R11·R12 점수 → 비중 ──────────────────────────────────────────────────────

def test_r11_zero_weights_are_lost():
    assert _codes({"issues": ho.intake_s2w_scores(_h(view={"dropped_zero": ["035420"]}))["issues"]}) == {"dropped_zero"}
    assert ho.intake_s2w_scores(_h(view={}))["issues"] == []


def test_r12_codes_missing_is_lost():
    R = pd.DataFrame(np.zeros((10, 2)))
    out = ho.intake_s2w_returns(_h(value={"returns": R}, view={"sigma_missing": {"reason": "codes_missing", "codes": ["9"]}}))
    assert [i["code"] for i in out["issues"]] == ["codes_missing"]
    assert ho.intake_s2w_returns(_h(value={"returns": R}, view={}))["issues"] == []


# ── R13·R14 노출 조절 ───────────────────────────────────────────────────────

def test_r13_manual_does_not_use_the_signal():
    assert [i["level"] for i in ho.intake_overlay_signal(_h(view={"follow": "manual"}))["issues"]] == ["unused"]


def test_r13_unread_signals_are_lost():
    out = ho.intake_overlay_signal(_h(view={"follow": "timing", "unavailable": 2, "n_signals": 5}))
    assert [i["code"] for i in out["issues"]] == ["unread"]
    assert ho.intake_overlay_signal(_h(view={"follow": "timing", "unavailable": 0, "n_signals": 5}))["issues"] == []


def test_r14_regime_is_only_shown_unless_followed():
    assert [i["level"] for i in ho.intake_overlay_regime(_h(view={"follow": "timing"}))["issues"]] == ["unused"]
    assert ho.intake_overlay_regime(_h(view={"follow": "timing_macro"}))["issues"] == []


# ── 사실 ─────────────────────────────────────────────────────────────────────

def test_returns_and_weights_facts_are_measured(clean):
    e, _ = _edges(_chain("mvo"))
    rf = {f["key"]: f for f in e["r.returns->o.returns"]["facts"]}
    assert rf["n_assets"]["value"] == 5 and rf["n_obs"]["value"] == 756
    assert rf["t_over_n"]["value"] == round(756 / 5, 2)
    wf = {f["key"]: f for f in e["o.weights->k.weights"]["facts"]}
    assert wf["cond"]["value"] > 1 and 1 <= wf["neff"]["value"] <= 5
    assert abs(wf["sum"]["value"] - 100.0) < 0.01


def test_weights_facts_speak_plainly():
    """공분산 출처는 쉬운 말(내부 코드 "trailing" 그대로 내보내지 않는다) · 작은 조건수는 소수 한 자리(1.15 를 "1" 로 뭉개지 않는다).
    짝: 모르는 출처 코드는 지어내지 않고 그대로 · 큰 조건수는 천 단위 정수."""
    S = np.array([[1.0, 0.0], [0.0, 1.15]])
    def facts(src, sig=S):
        return {f["key"]: f for f in ho.facts_weights({"weights": np.array([0.5, 0.5]), "names": ["a", "b"],
                                                       "sigma_annual": sig, "sigma_source": src})}
    assert facts("trailing")["sigma"]["text"] == "지난 수익률로 잰 공분산"
    assert facts("sample_252")["sigma"]["text"] == "최근 252일 표본 공분산"
    assert facts("conditional")["sigma"]["text"] == "국면 조건부 공분산"
    assert facts("weird_src")["sigma"]["text"] == "weird_src"
    assert facts("trailing")["cond"]["text"] == "1.1"
    assert facts("trailing", np.diag([1.0, 1234.0]))["cond"]["text"] == "1,234"


def test_facts_without_alignment_say_unmeasured():
    R = pd.DataFrame(np.zeros((10, 2)))
    fs = ho.facts_returns({"returns": R, "coverage": {"start": "a", "end": "b"}, "universe": {}})
    assert {"key": "alignment", "label": "날짜 맞추기", "text": "재지 않았어요", "value": None} in fs


def test_facts_never_judge(gappy):
    e, _ = _edges(_chain("bl", views=VIEWS, backtest={"rebalance": "Q"}))
    texts = [f["label"] + f["text"] for r in e.values() for f in r["facts"] or []]
    assert texts
    bad = [t for t in texts if any(w in t for w in JUDGMENT)]
    assert not bad, bad


def test_rules_do_not_change_values(gappy):
    """규칙·사실은 값을 읽기만 한다 — 같은 값으로 두 번 돌려도, 돌리기 전과 같다."""
    rep, values, params = pg._execute(_chain("bl", views=VIEWS, backtest={"rebalance": "Q"}), gn.REGISTRY)
    R = values["r"]["returns"]["returns"]
    before = pd.util.hash_pandas_object(R).sum()
    w_before = np.asarray(values["o"]["weights"]["weights"]).copy()
    pg._handoffs(_chain("bl", views=VIEWS, backtest={"rebalance": "Q"}), gn.REGISTRY, rep, values, params)
    assert pd.util.hash_pandas_object(R).sum() == before
    np.testing.assert_array_equal(np.asarray(values["o"]["weights"]["weights"]), w_before)


def test_every_registered_rule_points_at_a_real_input():
    for (kind, port) in ho.INTAKES:
        spec = gn.REGISTRY.get(kind)
        assert spec is not None and spec.input(port) is not None, (kind, port)


from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
