"""CF3 · 노드가 대신한 것·잃은 것을 view 와 설명에 싣는다 (관측만 — 계산 불변)
==============================================================================
- 옵티마이저 view `fallbacks` — 엔진 기록 + 서버 문장(방식 쉬운 이름). 설명은 "문제없이"를 빼고 가정 줄(`kind: fallback`)을 단다.
- 옵티마이저 view `view_legs_dropped` — BL·EP 에서 유니버스 밖 종목 때문에 다리를 잃은 생각(그 생각은 남되 일부만 반영).
- 점수→비중 view `sigma_missing`·`dropped_zero` — 공분산을 왜 함께 보내지 못했는지, 비중 0 이라 뺀 종목. 틀린 설명("수익률을 이어 주세요") 정정.
- 백테스트 설명 — 리밸런싱마다 방식이 답을 냈는지는 세지 않았다는 사실.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_cf3_golden import VIEWS, _chain, _opt_none, _raise, market  # noqa: E402, F401


def _texts(ex: dict) -> list[str]:
    return [*(ex.get("facts") or []), *(t["text"] for t in ex.get("trust") or []), *(ex.get("unmeasured") or [])]


def _run(g):
    rep = pg.run(g, gn.REGISTRY)
    return rep["nodes"]


# ── 옵티마이저 대체 ───────────────────────────────────────────────────────────

def test_optimizer_fallback_is_in_the_view_and_the_explanation(market, monkeypatch):
    monkeypatch.setattr("src.engine.allocation_studio._opt", _opt_none)
    o = _run(_chain("mvo"))["o"]
    [f] = o["view"]["fallbacks"]
    assert f["stage"] == "optimized" and f["affects_weights"] is True
    assert "수익 대비 위험 최적" in f["text"] and "역변동성" in f["text"]
    kinds = [t for t in o["explain"]["trust"] if t.get("kind") == "fallback"]
    assert kinds and kinds[0]["state"] == "assumed" and kinds[0]["text"] == f["text"]
    assert not any("문제없이" in t for t in _texts(o["explain"]))


def test_no_fallback_keeps_the_old_view_and_sentence(market):
    """짝 — 대체가 없으면 view 에 키가 없고 설명은 예전 그대로."""
    o = _run(_chain("mvo"))["o"]
    assert "fallbacks" not in o["view"]
    assert "비중 계산은 문제없이 끝났어요." in _texts(o["explain"])
    assert not any(t.get("kind") == "fallback" for t in o["explain"]["trust"])


def test_bl_market_fallback_corrects_the_views_sentence(market, monkeypatch):
    """BL 사후는 됐는데 비중을 풀지 못함 — '내 생각을 반영했어요' 대신 무엇이 반영됐는지 말한다(라벨 `views_applied` 도 K1 부터 거짓)."""
    monkeypatch.setattr("src.engine.allocation_studio._opt", _opt_none)
    o = _run(_chain("bl", views=VIEWS))["o"]
    assert o["view"]["views_applied"] is False
    texts = _texts(o["explain"])
    assert "내 생각을 반영했어요." not in texts
    assert any("시가총액 비중" in t for t in texts)


def test_bl_normal_still_says_views_were_applied(market):
    texts = _texts(_run(_chain("bl", views=VIEWS))["o"]["explain"])
    assert "내 생각을 반영했어요." in texts


def test_bl_posterior_failure_under_mvo_is_recorded_but_not_assumed(market, monkeypatch):
    """짝 — 비중에 닿지 않은 대체는 view 에 남지만 가정 줄이 되지 않는다."""
    monkeypatch.setattr("src.engine.allocation_studio.bl_posterior", _raise)
    o = _run(_chain("mvo", views=VIEWS))["o"]
    [f] = o["view"]["fallbacks"]
    assert f["affects_weights"] is False and f["text"]
    assert not any(t.get("kind") == "fallback" for t in o["explain"]["trust"])


# ── 생각 다리 ────────────────────────────────────────────────────────────────

def test_view_legs_dropped_are_named(market):
    v = _run(_chain("bl", views=VIEWS))["o"]["view"]
    legs = {x["index"]: x["dropped"] for x in v["view_legs_dropped"]}
    assert legs == {1: ["999999"], 2: ["999998"]}


def test_no_dropped_legs_no_key(market):
    """짝 — 모든 다리가 유니버스 안이면 키가 없다 · 생각을 쓰지 않는 방식에는 다리를 재지 않는다."""
    assert "view_legs_dropped" not in _run(_chain("bl", views=VIEWS[:1]))["o"]["view"]
    assert "view_legs_dropped" not in _run(_chain("mvo", views=VIEWS))["o"]["view"]


# ── 점수 → 비중 ──────────────────────────────────────────────────────────────

def _scores(weighting, scores, with_returns=True):
    from src.api.allocation_graph_nodes_signal import (
        ScoresToWeightsParams,
        _explain_scores_to_weights,
        _scores_to_weights,
    )
    _, values, _ = pg._execute(_chain("mvo"), gn.REGISTRY)
    inputs = {"scores": {"scores": scores, "kind": "factor"},
              "returns": values["r"]["returns"] if with_returns else None}
    out = _scores_to_weights(inputs, ScoresToWeightsParams(top_k=4, weighting=weighting))
    return out.view, _texts(_explain_scores_to_weights(out.view, {}, None))


S5 = {"005930": 3.0, "000660": 2.5, "035420": 2.0, "051910": 1.0}


def test_sigma_missing_names_the_missing_codes(market):
    view, texts = _scores("equal", {**S5, "999999": 2.8})
    assert view["sigma_missing"] == {"reason": "codes_missing", "codes": ["999999"]}
    assert any("수익률에 없는 종목" in t and "999999" in t for t in texts)
    assert not any("수익률을 이어 주세요" in t for t in texts)


def test_sigma_missing_without_returns_keeps_the_old_sentence(market):
    """짝 — 수익률을 잇지 않았으면 그 말이 맞다."""
    view, texts = _scores("equal", S5, with_returns=False)
    assert view["sigma_missing"] == {"reason": "no_returns", "codes": []}
    assert any("수익률을 이어 주세요" in t for t in texts)


def test_sigma_present_no_key(market):
    view, _ = _scores("equal", S5)
    assert "sigma_missing" not in view and view["has_sigma"] is True


@pytest.mark.parametrize("weighting,expect", [("factor_tilt", ["035420"]), ("equal", None)])
def test_dropped_zero_is_named(market, weighting, expect):
    view, _ = _scores(weighting, {**S5, "999999": 2.8})
    assert view.get("dropped_zero") == expect


# ── 백테스트 ─────────────────────────────────────────────────────────────────

def test_backtest_says_it_did_not_count_per_rebalance_fallbacks(market):
    b = _run(_chain("bl", views=VIEWS, backtest={"rebalance": "Q", "cost_bps": 15}))["b"]
    assert any("리밸런싱마다" in t for t in b["explain"]["unmeasured"])
