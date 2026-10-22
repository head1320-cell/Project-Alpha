"""K1 · 생각이 비중에 닿았는지 라벨 + 설명 문구 둘 (작업 카드 — 계산 불변)
==============================================================================
CF3 가 드러낸 세 가지 틀린 말을 고친다. 비중·백테스트 숫자는 한 자리도 바뀌지 않는다(`test_cf3_golden`).

1. `views_applied` — BL 이 생각을 넣은 기대 수익으로 비중을 풀지 못해 시장 비중을 썼는데도 참이었다. 이제 거짓이다.
   ★예외★ 제약을 걸면 `_apply_constraints` 가 생각을 넣은 기대 수익(`mu_used`)으로 다시 풀므로 생각이 비중에 닿는다 —
   그때는 참이고, 대체 기록은 비중에 닿지 않은 것으로 바뀐다. 라벨을 뒤집는 것은 BL 만이다: 다른 방식의 비중은 생각 열을
   쓰지 않아(EP 는 자기 μ 로 생각을 쓴다) 그 라벨은 예전 뜻(생각을 넣은 기대 수익을 계산했다) 그대로다.
2. `cap_missing` 설명 — "출발점을 똑같이 나눴어요" 는 시가총액을 **모두** 모를 때만 참이다. 일부만 모르면 엔진은 나머지의
   중앙값으로 채운다(`market_cap_weights`).
3. 베타 제약 사유 — 벤치마크에 빈 날이 있어 길이가 안 맞으면 라우트가 벤치마크를 버리고, 엔진은 "벤치마크 수익률이 없어" 라고
   적는다. ★엔진 문장(`constrained_opt.py`, SHA 가드)은 그대로 두고★ 라우트가 그 경우에만 정확한 사유로 바꿔 싣는다.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_explain as ex  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api import allocation_routes as ar  # noqa: E402
from src.engine import allocation_studio as st  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_cf3_golden import VIEWS, _chain, _opt_none, _raise, market  # noqa: E402, F401
from tests.test_graph_handoff_rules import gappy  # noqa: E402, F401

NAMES = ["005930", "000660", "035420"]
VIEW = [{"assets": ["005930"], "direction": 1, "magnitude_pct": 4.0, "confidence": 60}]
MARKET_SENTENCE = "생각을 반영한 비중을 만들지 못해 시가총액 비중을 썼어요."


def _R():
    rng = np.random.default_rng(3)
    return np.round(rng.normal(0.0004, 0.012, (400, 3)) * np.array([1.0, 1.3, 0.8]), 6)


@pytest.fixture()
def caps(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 400000.0, "000660": 120000.0}.get(code, 30000.0))


def _texts(ex_: dict) -> list[str]:
    return [*(ex_.get("facts") or []), *(t["text"] for t in ex_.get("trust") or [])]


def _run(g):
    return pg.run(g, gn.REGISTRY)


# ── 1. 라벨 (엔진) ───────────────────────────────────────────────────────────

def test_bl_market_fallback_says_views_did_not_reach_the_weights(caps, monkeypatch):
    monkeypatch.setattr(st, "_opt", _opt_none)
    out = st.optimize("bl", NAMES, _R(), views=VIEW)
    assert out["views_applied"] is False
    np.testing.assert_array_equal(out["weights"], out["flow"]["market"])
    assert out["mu_engine"] == "bl"            # 기대 수익에는 생각이 들어갔다는 사실은 그대로 말한다


def test_bl_solved_says_views_reached(caps):
    """짝 — 풀리면 참이고 비중은 시장 비중이 아니다."""
    out = st.optimize("bl", NAMES, _R(), views=VIEW)
    assert out["views_applied"] is True
    assert not np.array_equal(out["weights"], out["flow"]["market"])


def test_label_flip_is_bl_only(caps, monkeypatch):
    """짝 — 비중이 생각 열을 쓰지 않는 방식은 라벨 뜻이 그대로다(뒤집으면 EP 설명이 '반영된 생각이 없어요' 로 틀려진다)."""
    monkeypatch.setattr(st, "_opt", _opt_none)
    out = st.optimize("mvo", NAMES, _R(), views=VIEW)
    assert out["views_applied"] is True


# ── 1. 제약 예외 (노드 — `_apply_constraints`) ───────────────────────────────

def test_constraints_resolve_with_the_posterior_so_views_reach_the_weights(market, monkeypatch):
    monkeypatch.setattr("src.engine.allocation_studio._opt", _opt_none)
    rep = _run(_chain("bl", views=VIEWS, opt={"constraints": {"max_weight_pct": 40}}))
    o = rep["nodes"]["o"]
    v = o["view"]
    assert v["constraints_report"]["status"] != "infeasible"
    assert v["views_applied"] is True
    assert v["weights"] != v["flow"]["market"]
    [f] = [f for f in v["fallbacks"] if f["stage"] == "view_applied"]
    assert f["affects_weights"] is False
    assert "제약" in f["text"] and "그래서 비중은 시가총액 비중이에요." not in f["text"]
    texts = _texts(o["explain"])
    assert "내 생각을 반영했어요." in texts
    assert not any(t.get("kind") == "fallback" for t in o["explain"]["trust"])
    assert "views_market" not in {i["code"] for i in rep["edges"]["v.views->o.views"]["issues"] or []}


def test_infeasible_constraints_keep_the_market_label(market, monkeypatch):
    """짝 — 제약을 못 풀면 시장 비중 그대로다: 라벨은 거짓, 대체는 비중에 닿는다."""
    monkeypatch.setattr("src.engine.allocation_studio._opt", _opt_none)
    rep = _run(_chain("bl", views=VIEWS, opt={"constraints": {"max_weight_pct": 10}}))
    v = rep["nodes"]["o"]["view"]
    assert v["constraints_report"]["status"] == "infeasible"
    assert v["views_applied"] is False
    [f] = [f for f in v["fallbacks"] if f["stage"] == "view_applied"]
    assert f["affects_weights"] is True
    assert "views_market" in {i["code"] for i in rep["edges"]["v.views->o.views"]["issues"] or []}


def test_constraints_after_posterior_failure_do_not_bring_views_back(market, monkeypatch):
    """짝 — 사후 계산이 실패했으면 다시 푸는 기대 수익에도 생각이 없다(과거 평균) — 라벨은 거짓 그대로."""
    monkeypatch.setattr("src.engine.allocation_studio.bl_posterior", _raise)
    v = _run(_chain("bl", views=VIEWS, opt={"constraints": {"max_weight_pct": 40}}))["nodes"]["o"]["view"]
    assert v["constraints_report"]["status"] != "infeasible"
    assert v["views_applied"] is False
    [f] = [f for f in v["fallbacks"] if f["stage"] == "view_applied"]
    assert f["affects_weights"] is True


# ── 1. 설명 문장 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", ["src.engine.allocation_studio._opt", "src.engine.allocation_studio.bl_posterior"])
def test_market_fallback_sentence_says_what_happened(market, monkeypatch, target):
    monkeypatch.setattr(target, _opt_none if target.endswith("_opt") else _raise)
    texts = _texts(_run(_chain("bl", views=VIEWS))["nodes"]["o"]["explain"])
    assert MARKET_SENTENCE in texts
    assert "반영된 생각이 없어요." not in texts and "내 생각을 반영했어요." not in texts


def test_bl_without_views_still_says_none(market):
    """짝 — 생각이 없으면 대체도 없고 문장은 예전 그대로."""
    texts = _texts(_run(_chain("bl"))["nodes"]["o"]["explain"])
    assert "반영된 생각이 없어요." in texts and MARKET_SENTENCE not in texts


# ── 2. 시가총액 모름 ─────────────────────────────────────────────────────────

def _opt_view(cap: list[str]) -> dict:
    return {"names": NAMES, "weights": {}, "model": "bl", "cap_missing": cap}


def test_all_caps_missing_says_split_equally():
    texts = _texts(ex.explain_optimizer(_opt_view(list(NAMES)), {}, None))
    assert any("똑같이" in t for t in texts)
    assert not any("중앙값" in t for t in texts)


def test_some_caps_missing_says_median():
    texts = _texts(ex.explain_optimizer(_opt_view(["035420"]), {}, None))
    line = next(t for t in texts if "시가총액" in t and "중앙값" in t)
    assert "1개 종목" in line
    assert not any("똑같이" in t for t in texts)


def test_the_sentences_match_what_the_engine_does(monkeypatch):
    """문장이 엔진과 같은 일을 말한다 — 일부 모름은 중앙값 채움, 모두 모름은 균등."""
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 400000.0, "000660": 100000.0}.get(code))
    w, missing = st.market_cap_weights(NAMES)
    assert missing == ["035420"]
    np.testing.assert_allclose(w, np.array([400000.0, 100000.0, 250000.0]) / 750000.0)
    monkeypatch.setattr("src.data.stock_master.get_market_cap", lambda code: None)
    w, missing = st.market_cap_weights(NAMES)
    assert missing == NAMES
    np.testing.assert_allclose(w, np.full(3, 1 / 3))


# ── 3. 베타 제약 사유 ────────────────────────────────────────────────────────

def _beta_req():
    return ar.AnalyzeRequest(tickers=NAMES, model="mvo", constraints={"beta_max": 1.5})


def test_engine_still_writes_the_sentence_the_route_replaces(caps):
    """라우트가 바꿔 싣는 문장이 지금도 엔진 문장과 정확히 같다 — 엔진 글이 바뀌면 여기서 먼저 빨개진다."""
    from src.engine.constrained_opt import Constraints, constrained_solve
    R = _R()
    opt = st.optimize("mvo", NAMES, R)
    sol = constrained_solve("mvo", NAMES, R, mu=opt["mu_used"], S=opt["sigma_annual"],
                            constraints=Constraints(beta_max=1.5), bench_returns=None)
    assert ar._ENGINE_BETA_NO_BENCH in sol["notes"]


def test_beta_reason_names_the_benchmark_gaps(caps):
    R = _R()
    opt = st.optimize("mvo", NAMES, R)
    bench = pd.Series(np.full(R.shape[0] - 6, 0.0004))
    notes = ar._apply_constraints(_beta_req(), NAMES, R, opt, bench)["notes"]
    assert ar._ENGINE_BETA_NO_BENCH not in notes
    line = next(n for n in notes if "베타" in n)
    assert "빈 날" in line and str(R.shape[0]) in line and str(R.shape[0] - 6) in line


def test_beta_reason_without_benchmark_keeps_the_engine_sentence(caps):
    """짝 — 벤치마크를 아예 받지 못했으면 엔진 문장이 참이다: 그대로 둔다."""
    R = _R()
    notes = ar._apply_constraints(_beta_req(), NAMES, R, st.optimize("mvo", NAMES, R), None)["notes"]
    assert ar._ENGINE_BETA_NO_BENCH in notes
    assert not any("빈 날" in n for n in notes)


def test_beta_with_a_full_benchmark_has_no_reason(caps):
    """짝 — 길이가 맞으면 베타 제약이 걸린다: 사유 문장이 없다."""
    R = _R()
    bench = pd.Series(np.random.default_rng(5).normal(0.0003, 0.01, R.shape[0]))
    notes = ar._apply_constraints(_beta_req(), NAMES, R, st.optimize("mvo", NAMES, R), bench)["notes"]
    assert not any("베타" in n for n in notes)


def test_r4_text_no_longer_says_the_report_blames_a_missing_benchmark(gappy):
    rep = _run(_chain("mvo", opt={"constraints": {"beta_max": 1.5}}))
    beta = next(i for i in rep["edges"]["r.returns->o.returns"]["issues"] if i["code"] == "beta_dropped")
    assert "없다" not in beta["text"]
    notes = rep["nodes"]["o"]["view"]["constraints_report"]["notes"]
    assert any("빈 날" in n for n in notes)
