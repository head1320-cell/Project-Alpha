"""BO O1 · 위험 성향 손잡이 — 평균-분산 효용(`mv_utility`, λ)
====================================================================
사용자가 **별도 승인**한 옵티마이저 변경. BN N2 에서 δ 가 9 방식 모두에서 비중을 움직이지 않는다는
사실을 찾았고(`tests/test_optimizer_delta_honest.py`), 사용자는 "움직이는 손잡이" 를 새 방식으로
더하기로 했다 — **기존 방식은 한 글자도 바꾸지 않는다.**

## 거는 것

- ★골든★ 기존 방식의 가중치는 이 변경 전 스냅샷과 같다(합성 R, 시드 7).
- λ 가 오르면 포트폴리오 분산과 기대수익이 **내려간다**(단조) — 짝: 두 끝이 실제로 다르다
  (상수로 박은 구현을 배제한다).
- λ 가 매우 크면 최소분산에 가깝다 · 최대 비중 제약을 지킨다(제약 안에서도 λ 가 움직인다).
- λ 를 주지 않으면 기본값을 쓰고 **가정**으로 공시한다(`risk_aversion.source == "default"`).
- 다른 방식에는 λ 가 아무 영향도 없고 응답에 `risk_aversion` 키도 생기지 않는다.
- 카탈로그: 질문·프리셋(범위 안)·`show_if`(그 방식을 골랐을 때만) — 움직이지 않는 손잡이를
  초심자 질문으로 다시 만들지 않는다.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from pydantic import ValidationError

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import allocation_studio as st  # noqa: E402

GOLDEN = {  # 이 변경 전 `weights_for_model(m, R)` — 반올림 6자리
    "mvo": [0.0, 1.0, 0.0, 0.0, 0.0],
    "risk_parity": [0.142112, 0.214324, 0.168481, 0.320757, 0.154325],
    "hrp": [0.106631, 0.170748, 0.133748, 0.501353, 0.087521],
    "min_var": [0.008959, 0.221061, 0.071493, 0.659778, 0.038708],
    "max_div": [0.140046, 0.19641, 0.167643, 0.350905, 0.144995],
    "min_cvar": [0.044831, 0.223092, 0.042102, 0.643336, 0.046639],
    "robust": [0.0, 0.96813, 0.0, 0.03187, 0.0],
}


def _R() -> np.ndarray:
    rng = np.random.default_rng(7)
    mu = np.array([0.0006, 0.0003, 0.0004, 0.0001, 0.0005])
    vol = np.array([0.02, 0.012, 0.016, 0.009, 0.018])
    C = np.full((5, 5), 0.3)
    np.fill_diagonal(C, 1)
    L = np.linalg.cholesky(C * np.outer(vol, vol))
    return mu + rng.standard_normal((600, 5)) @ L.T


NAMES = ["A", "B", "C", "D", "E"]


def _stats(w: np.ndarray, R: np.ndarray) -> tuple[float, float]:
    S = np.cov(R, rowvar=False) * 252.0
    return float(w @ (R.mean(axis=0) * 252.0)), float(w @ S @ w)


# ── 기존 방식 불변 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", sorted(GOLDEN))
def test_existing_models_unchanged(model):
    w = st.weights_for_model(model, _R())
    assert [round(float(x), 6) for x in w] == GOLDEN[model]


@pytest.mark.parametrize("model", ["mvo", "min_var", "risk_parity"])
def test_lambda_does_not_touch_other_models(model, monkeypatch):
    monkeypatch.setattr(st, "market_cap_weights", lambda names: (np.ones(len(names)) / len(names), []))
    R = _R()
    a = st.optimize(model, NAMES, R)
    b = st.optimize(model, NAMES, R, risk_aversion=15.0)
    assert np.allclose(a["weights"], b["weights"])
    assert "risk_aversion" not in a and "risk_aversion" not in b


# ── 새 방식 ────────────────────────────────────────────────────────────────

def test_mv_utility_is_a_model():
    assert "mv_utility" in st.MODELS
    assert st.model_availability()["mv_utility"]["available"] in (True, False)


def test_lambda_up_means_less_variance_and_less_return():
    R = _R()
    stats = [_stats(st.weights_for_model("mv_utility", R, risk_aversion=lam), R)
             for lam in (1.0, 2.0, 4.0, 8.0, 16.0)]
    rets = [s[0] for s in stats]
    vars_ = [s[1] for s in stats]
    assert all(a >= b - 1e-9 for a, b in zip(vars_, vars_[1:]))
    assert all(a >= b - 1e-9 for a, b in zip(rets, rets[1:]))
    # 짝 — 끝과 끝이 실제로 다르다(λ 를 무시하는 구현을 죽인다)
    assert vars_[0] > vars_[-1] * 1.2
    assert rets[0] > rets[-1] + 0.01


def test_huge_lambda_is_near_min_variance():
    R = _R()
    w = st.weights_for_model("mv_utility", R, risk_aversion=1e4)
    assert np.allclose(w, st.weights_for_model("min_var", R), atol=0.03)


def test_small_lambda_leans_to_highest_return():
    R = _R()
    w = st.weights_for_model("mv_utility", R, risk_aversion=0.5)
    top = int(np.argmax(R.mean(axis=0)))
    assert int(np.argmax(w)) == top


def test_default_lambda_is_disclosed_as_assumption(monkeypatch):
    monkeypatch.setattr(st, "market_cap_weights", lambda names: (np.ones(len(names)) / len(names), []))
    R = _R()
    d = st.optimize("mv_utility", NAMES, R)
    assert d["risk_aversion"] == {"value": st.RISK_AVERSION_DEFAULT, "source": "default"}
    u = st.optimize("mv_utility", NAMES, R, risk_aversion=16.0)
    assert u["risk_aversion"] == {"value": 16.0, "source": "user"}
    assert not np.allclose(d["weights"], u["weights"])
    # 기본값으로 푼 것 == 그 값을 사용자가 준 것
    same = st.optimize("mv_utility", NAMES, R, risk_aversion=st.RISK_AVERSION_DEFAULT)
    assert np.allclose(d["weights"], same["weights"])


def test_constrained_mv_utility_respects_cap_and_still_moves():
    from src.engine.constrained_opt import Constraints, constrained_solve
    R = _R()
    S = np.cov(R, rowvar=False) * 252.0
    mu = R.mean(axis=0) * 252.0
    c = Constraints(max_weight_pct=40)
    lo = constrained_solve("mv_utility", NAMES, R, mu, S, c, risk_aversion=1.0)
    hi = constrained_solve("mv_utility", NAMES, R, mu, S, c, risk_aversion=30.0)
    for sol in (lo, hi):
        assert sol["status"] == "ok"
        assert float(np.max(sol["weights"])) <= 0.40 + 1e-6
    assert float(lo["weights"] @ S @ lo["weights"]) > float(hi["weights"] @ S @ hi["weights"])


def test_constrained_other_models_ignore_lambda():
    from src.engine.constrained_opt import Constraints, constrained_solve
    R = _R()
    S = np.cov(R, rowvar=False) * 252.0
    mu = R.mean(axis=0) * 252.0
    c = Constraints(max_weight_pct=40)
    a = constrained_solve("mvo", NAMES, R, mu, S, c)
    b = constrained_solve("mvo", NAMES, R, mu, S, c, risk_aversion=30.0)
    assert np.allclose(a["weights"], b["weights"])


# ── 요청 모델·카탈로그 ─────────────────────────────────────────────────────

def test_request_bounds():
    from src.api.allocation_routes import AnalyzeRequest
    assert AnalyzeRequest(tickers=["005930"]).risk_aversion is None
    AnalyzeRequest(tickers=["005930"], risk_aversion=0.5)
    AnalyzeRequest(tickers=["005930"], risk_aversion=20)
    for bad in (0.4, 21, -1):
        with pytest.raises(ValidationError):
            AnalyzeRequest(tickers=["005930"], risk_aversion=bad)


def _optimizer_schema() -> dict:
    from src.api import allocation_graph_nodes as gn
    return gn.OptimizerParams.model_json_schema()


def test_catalog_question_presets_and_show_if():
    props = _optimizer_schema()["properties"]
    assert "mv_utility" in props["model"]["enum"]
    assert props["model"]["x-ui"]["options"]["mv_utility"] == "위험 성향에 맞춰"
    ui = props["risk_aversion"]["x-ui"]
    assert ui["tier"] == "basic"
    assert ui["question"] == "위험을 얼마나 피할까요?"
    assert ui["show_if"] == {"model": ["mv_utility"]}
    assert ui["widget"] == "slider"
    labels = [p["label"] for p in ui["presets"]]
    assert labels == ["덜 피함", "보통", "많이 피함"]
    values = [p["value"] for p in ui["presets"]]
    assert values == sorted(values) and len(set(values)) == 3
    assert all(0.5 <= v <= 20 for v in values)
    assert st.RISK_AVERSION_DEFAULT in values          # 기본값 = "보통"
    assert ui["empty_value"] == st.RISK_AVERSION_DEFAULT  # 비우면 쓰는 값 = 엔진 기본값(한 곳)
    assert "가정" in ui["help"]


def test_delta_stays_advanced():
    """δ 는 BN N2 표시 그대로 — 새 손잡이가 δ 를 초심자 질문으로 되살리지 않는다."""
    ui = _optimizer_schema()["properties"]["delta"]["x-ui"]
    assert ui["tier"] == "advanced" and "question" not in ui


# ── 그래프 노드 — `/analyze` 와 같은 수 · 설명 ─────────────────────────────

@pytest.fixture()
def market(monkeypatch):
    from tests.test_allocation_routes import T3, _fake_returns_df, _patch_caps, _patch_returns
    df = _fake_returns_df(T3, n=1100)
    _patch_returns(monkeypatch, df)
    _patch_caps(monkeypatch)
    return T3


def _graph(lam=None, constraints=None):
    from tests.test_allocation_graph import chain
    g = chain(model="mv_utility", constraints=constraints)
    for n in g["nodes"]:
        if n["id"] == "o" and lam is not None:
            n["params"]["risk_aversion"] = lam
    return g


@pytest.mark.parametrize("lam,constraints", [(None, None), (1.5, None), (10.0, {"max_weight_pct": 45})])
def test_node_equals_analyze(market, lam, constraints):
    from src.api import allocation_graph_nodes as gn
    from src.api.allocation_routes import AnalyzeRequest, run_analyze
    from src.engine import portfolio_graph as pg
    out = pg.run(_graph(lam, constraints), gn.REGISTRY)
    o = out["nodes"]["o"]
    assert o["status"] == "ok", o["reason"]
    ref = run_analyze(AnalyzeRequest(tickers=market, model="mv_utility", risk_aversion=lam,
                                     constraints=constraints))
    assert o["view"]["weights"] == ref["weights"]["optimized"]
    src = "default" if lam is None else "user"
    assert o["view"]["risk_aversion"]["source"] == src


def test_node_lambda_moves_weights_and_explains(market):
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    lo = pg.run(_graph(1.5), gn.REGISTRY)["nodes"]["o"]
    hi = pg.run(_graph(10.0), gn.REGISTRY)["nodes"]["o"]
    assert lo["view"]["weights"] != hi["view"]["weights"]
    d = pg.run(_graph(None), gn.REGISTRY)["nodes"]["o"]
    trust = " ".join(t["text"] for t in d["explain"]["trust"])
    assert "관례적인 값" in trust and "나에게 맞는 값은 아니에요" in trust
    assert any("위험 회피 λ 4" in f for f in d["explain"]["facts"])
    utrust = " ".join(t["text"] for t in hi["explain"]["trust"])
    assert "내가 고른 값" in utrust and "관례적인 값" not in utrust


def test_mvo_node_has_no_lambda_story(market):
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    from tests.test_allocation_graph import chain
    o = pg.run(chain(model="mvo"), gn.REGISTRY)["nodes"]["o"]
    assert "risk_aversion" not in o["view"]
    assert not any("λ" in f for f in o["explain"]["facts"])


def test_unused_views_are_said_not_hidden(market):
    """생각을 이었는데 그 생각을 쓰지 않는 방식이면 그 사실을 말한다 — 짝: 쓰는 방식(bl)에서는 말하지 않는다."""
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    from tests.test_allocation_graph import VIEW, chain
    g = chain(model="mv_utility", views=[VIEW])
    o = pg.run(g, gn.REGISTRY)["nodes"]["o"]
    assert o["view"]["views_unused"] == 1
    assert any("쓰이지 않아요" in t["text"] for t in o["explain"]["trust"])
    b = pg.run(chain(model="bl", views=[VIEW]), gn.REGISTRY)["nodes"]["o"]
    assert "views_unused" not in b["view"]
    assert not any("쓰이지 않아요" in t["text"] for t in b["explain"]["trust"])
    n = pg.run(chain(model="mv_utility"), gn.REGISTRY)["nodes"]["o"]
    assert "views_unused" not in n["view"]


def test_analyze_passes_lambda_and_discloses_it(market):
    """`/analyze` 도 λ 를 엔진까지 나른다 — 짝: 두 λ 의 비중이 다르다 · 다른 방식에는 키가 없다."""
    from src.api.allocation_routes import AnalyzeRequest, run_analyze
    lo = run_analyze(AnalyzeRequest(tickers=market, model="mv_utility", risk_aversion=0.5))
    hi = run_analyze(AnalyzeRequest(tickers=market, model="mv_utility", risk_aversion=20))
    assert lo["weights"]["optimized"] != hi["weights"]["optimized"]
    assert lo["risk_aversion"] == {"value": 0.5, "source": "user"}
    d = run_analyze(AnalyzeRequest(tickers=market, model="mv_utility"))
    assert d["risk_aversion"]["source"] == "default"
    assert "risk_aversion" not in run_analyze(AnalyzeRequest(tickers=market, model="mvo"))
