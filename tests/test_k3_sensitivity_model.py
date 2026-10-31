"""K3 · 민감도가 고른 방식·제약·위험 회피 λ 로 다시 푼다 (작업 카드 · 사용자 결정 2026-10-18 "계산하고 '안 움직여요'라고 말하기")
==============================================================================
예전 민감도 노드는 받은 비중을 만든 방식을 무시하고 생각이 있으면 BL, 없으면 평균-분산(max-sharpe)으로 다시 풀고 제약을 뺐다.
기본 템플릿 '충격 점검'(위험 똑같이 = 리스크 패리티)에서 사용자가 본 민감도는 자기 비중의 것이 아니었다.

이제 노드는 `sensitivity_matrix(..., model=, constraints=, risk_aversion=, w_current=, bench_returns=, groups_of=)` 로
'비중 계산' 과 ★같은 길★(`optimize` → 제약이면 `constrained_solve`)로 기준 비중을 풀고, 흔든 기대 수익마다 같은 길로 다시 푼다.
- 기대 수익을 쓰지 않는 방식(무제약 최소분산·위험 똑같이·HRP·최대분산·최소 CVaR, 생각 없는 BL)은 계산하되 칸이 모두 0 이고
  `mu_reach: "none"` + 서버 문장("기대 수익을 쓰지 않아 … 움직이지 않아요")을 싣는다 — 화면은 0 칸 히트맵 대신 그 문장을 보인다.
- 강건 최적화(무제약)는 기대 수익을 수익률에서 스스로 다시 추정해 흔든 값이 들어가지 않는다 — `mu_reach: "own"` + 그 문장.
- 흔든 기대 수익으로 풀지 못한 줄은 0 으로 메우지 않고 `None`(칸 "—") + 그 수를 센다(조용한 무반응 금지).
★`model` 을 주지 않으면 예전과 한 자리도 같다★ — `/sensitivity` 라우트는 그대로(`tests/golden/k3_sensitivity_legacy.json`, 바꾸기 전에 얼림).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_handoff as ho  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.allocation_routes import AnalyzeRequest  # noqa: E402
from src.engine import allocation_studio as st  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_cf3_golden import _chain, _edge, _node  # noqa: E402
from tests.test_graph_handoff_rules import clean  # noqa: E402, F401

LEGACY = Path(__file__).parent / "golden" / "k3_sensitivity_legacy.json"
NAMES = ["005930", "000660", "035420", "051910"]
V = [{"assets": ["005930"], "direction": 1, "magnitude_pct": 4.0, "confidence": 60},
     {"assets": ["000660", "035420"], "direction": -1, "magnitude_pct": 2.0, "confidence": 40}]


def _R():
    rng = np.random.default_rng(20261021)
    n = 600
    common = rng.normal(0.0003, 0.009, n)
    return np.round(np.column_stack([(0.5 + 0.25 * i) * common + rng.normal(0.0001 * (i + 1), 0.011, n)
                                     for i in range(4)]), 6)


@pytest.fixture(autouse=True)
def caps(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 400000.0, "000660": 120000.0, "035420": 30000.0}.get(code, 50000.0))


def _flat(m):
    return [x for row in m for x in (row or [])]


# ── 예전 길은 그대로 ─────────────────────────────────────────────────────────

def test_without_a_model_the_legacy_output_is_unchanged():
    frozen = json.loads(LEGACY.read_text(encoding="utf-8"))
    cases = {"plain_2": dict(views=None, bump_pct=2.0), "plain_5": dict(views=None, bump_pct=5.0),
             "views_2": dict(views=V, bump_pct=2.0), "views_1": dict(views=V, bump_pct=1.0)}
    for name, kw in cases.items():
        got = json.loads(json.dumps(st.sensitivity_matrix(NAMES, _R(), **kw),
                                    default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        assert got == frozen[name], name


# ── 고른 방식으로 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ["risk_parity", "hrp", "min_var", "max_div", "min_cvar"])
def test_mu_free_models_compute_zeros_and_say_so(model):
    out = st.sensitivity_matrix(NAMES, _R(), model=model)
    assert out["mu_reach"] == "none"
    assert all(x == 0.0 for x in _flat(out["matrix"]))
    assert "기대 수익을 쓰지 않아" in out["still"] and "움직이지 않아요" in out["still"]
    np.testing.assert_allclose(out["base_weights"],
                               np.round(st.optimize(model, NAMES, _R())["weights"] * 100, 2))


def test_mean_variance_moves():
    """짝 — 기대 수익을 쓰는 방식은 움직이고 문장이 없다."""
    out = st.sensitivity_matrix(NAMES, _R(), model="mvo")
    assert out["mu_reach"] == "reads" and out.get("still") is None
    assert any(abs(x) > 0.05 for x in _flat(out["matrix"]))


def test_bl_without_views_is_market_weights_and_does_not_move():
    """생각 없는 BL 은 시가총액 비중 — 기대 수익을 흔들어도 그대로다."""
    out = st.sensitivity_matrix(NAMES, _R(), model="bl")
    assert out["mu_reach"] == "none" and all(x == 0.0 for x in _flat(out["matrix"]))


def test_robust_re_estimates_its_own_mu():
    out = st.sensitivity_matrix(NAMES, _R(), model="robust")
    assert out["mu_reach"] == "own"
    assert "스스로" in out["still"]


def test_lambda_reaches_the_utility():
    a = st.sensitivity_matrix(NAMES, _R(), model="mv_utility", risk_aversion=1.0)
    b = st.sensitivity_matrix(NAMES, _R(), model="mv_utility", risk_aversion=12.0)
    assert a["mu_reach"] == "reads"
    assert a["matrix"] != b["matrix"]


def _cap(pct):
    from src.engine.constrained_opt import Constraints
    return Constraints(max_weight_pct=pct)


def test_constraints_hold_in_every_bumped_solve():
    out = st.sensitivity_matrix(NAMES, _R(), model="mvo", constraints=_cap(40))
    base = np.asarray(out["base_weights"])
    assert base.max() <= 40.0 + 0.05
    for row in out["matrix"]:
        assert row is not None and (base + np.asarray(row)).max() <= 40.0 + 0.1
    assert out["constraints_applied"] is True


def test_without_constraints_the_same_data_goes_past_the_cap():
    """짝 — 제약 테스트가 공허하지 않다: 무제약이면 40% 를 넘는다."""
    assert max(st.sensitivity_matrix(NAMES, _R(), model="mvo")["base_weights"]) > 40.0


def test_constrained_max_div_follows_the_optimizer_path():
    """제약이 걸리면 '비중 계산' 도 `constrained_solve` 의 기대 수익 목적함수로 푼다 — 민감도도 같은 길이라 움직인다."""
    out = st.sensitivity_matrix(NAMES, _R(), model="max_div", constraints=_cap(40))
    assert out["mu_reach"] == "reads"


def test_a_row_that_cannot_be_solved_is_unknown_not_zero(monkeypatch):
    """흔든 기대 수익으로 풀지 못하면 그 줄은 0 이 아니라 모름 — 그리고 센다."""
    monkeypatch.setattr(st, "_opt", lambda *a, **k: None)
    out = st.sensitivity_matrix(NAMES, _R(), model="mvo")
    assert out["matrix"] == [None] * len(NAMES)
    assert out["failed_rows"] == len(NAMES)


# ── 노드: 비중 계산과 같은 기준 비중 ──────────────────────────────────────────

def _sens(model, **opt):
    g = _chain(model, opt=opt or None)
    g["nodes"].append(_node("s", "sensitivity"))
    g["edges"] += [_edge("r", "returns", "s", "returns"), _edge("o", "weights", "s", "weights")]
    return pg.run(g, gn.REGISTRY)


@pytest.mark.parametrize("model,opt", [("mvo", {}), ("risk_parity", {}), ("mv_utility", {"risk_aversion": 1.5}),
                                       ("mvo", {"constraints": {"max_weight_pct": 40}}),
                                       ("min_var", {"constraints": {"max_weight_pct": 30}})])
def test_node_base_weights_equal_the_optimizer_weights(clean, model, opt):
    rep = _sens(model, **opt)
    s, o = rep["nodes"]["s"], rep["nodes"]["o"]
    assert s["status"] == "ok", s["reason"]
    names = s["view"]["result"]["names"]
    got = dict(zip(names, s["view"]["result"]["base_weights"], strict=True))
    for k, w in o["view"]["weights"].items():
        assert abs(got[k] - w) <= 0.011, (k, got[k], w)
    assert s["view"]["basis"] == model


def test_node_mu_free_explanation_says_it_does_not_move(clean):
    s = _sens("risk_parity")["nodes"]["s"]
    ex = s["explain"]
    assert "움직이지 않아요" in ex["title"]
    assert any("기대 수익을 쓰지 않아" in f for f in ex["facts"])
    assert ex.get("headline") is None                  # 0 을 '가장 큰 변화' 로 세우지 않는다


def test_node_explanation_names_what_was_passed(clean):
    s = _sens("mvo", constraints={"max_weight_pct": 40})["nodes"]["s"]
    texts = [t["text"] for t in s["explain"]["trust"]]
    line = next(t for t in texts if "다시 풀었어요" in t)
    assert "수익 대비 위험 최적" in line and "제약" in line
    assert "생각" not in line                           # 생각을 넘기지 않았으면 넘겼다고 말하지 않는다
    assert not any(t["state"] == "assumed" for t in s["explain"]["trust"])
    assert "같은 수익률·같은 제약을 넣어 다시 풀었어요" in line


def test_node_explanation_names_lambda_for_the_utility(clean):
    texts = [t["text"] for t in _sens("mv_utility", risk_aversion=1.5)["nodes"]["s"]["explain"]["trust"]]
    assert any("같은 수익률·같은 위험 회피 λ를 넣어 다시 풀었어요" in t for t in texts)
    # 짝 — λ 를 쓰지 않는 방식은 λ 를 넘겼다고 말하지 않는다
    assert not any("λ" in t["text"] for t in _sens("mvo")["nodes"]["s"]["explain"]["trust"])


# ── 선 점검 R10 ──────────────────────────────────────────────────────────────

def test_r10_same_model_now_clean(clean):
    rep = _sens("risk_parity")
    codes = {i["code"] for i in rep["edges"]["o.weights->s.weights"]["issues"] or []}
    assert "other_model" not in codes


def test_r10_constraints_are_carried(clean):
    rep = _sens("mvo", constraints={"max_weight_pct": 40})
    codes = {i["code"] for i in rep["edges"]["o.weights->s.weights"]["issues"] or []}
    assert "constraints_dropped" not in codes


def _h(view, opt=None, req=None):
    return pg.Handoff(edge_id="e", source="o", source_kind="optimizer", source_port="weights", target="s",
                      target_kind="sensitivity", target_port="weights", port_type="Weights",
                      value={"req": req, "opt": opt or {}}, source_view={}, view=view, params=None, inputs={})


def test_r10_rules_are_still_alive():
    """짝 — 규칙은 죽지 않았다: 다른 방식으로 풀었거나 제약을 빼면 여전히 말한다 · 회사 관점이 빠지면 말한다."""
    codes = lambda h: {i["code"] for i in ho.intake_sensitivity_weights(h)["issues"]}  # noqa: E731
    assert "other_model" in codes(_h({"model": "risk_parity", "basis": "mvo"}))
    assert "constraints_dropped" in codes(_h({"model": "mvo", "basis": "mvo", "has_constraints": True,
                                              "constraints_applied": False}))
    assert "constraints_dropped" not in codes(_h({"model": "mvo", "basis": "mvo", "has_constraints": True,
                                                  "constraints_applied": True}))
    req = AnalyzeRequest(tickers=NAMES, model="bl")
    assert "company_views_dropped" in codes(_h({"model": "bl", "basis": "bl"}, opt={"company_views_used": 2}, req=req))
    assert "company_views_dropped" not in codes(_h({"model": "bl", "basis": "bl"}, opt={"company_views_used": 0}, req=req))


def test_a_method_that_ignores_views_is_bumped_on_its_own_mu():
    """평균-분산(mvo)은 생각을 비중에 쓰지 않는다 — 생각이 있어도 흔드는 기대 수익은 그 방식이 쓰는 과거 평균이다(짝: 생각 없음과 같다)."""
    a = st.sensitivity_matrix(NAMES, _R(), views=V, model="mvo")
    b = st.sensitivity_matrix(NAMES, _R(), model="mvo")
    assert a["matrix"] == b["matrix"] and a["views_used"] is False
    c = st.sensitivity_matrix(NAMES, _R(), views=V, model="bl")
    assert c["views_used"] is True and c["matrix"] != b["matrix"]
