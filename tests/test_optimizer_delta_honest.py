"""BN N2 · '위험 회피 정도' 질문의 정직성 — δ 가 실제로 무엇을 움직이는가
==============================================================================
BN 계획은 옵티마이저 `delta` 에 "위험 성향" 프리셋(1 · 2.5 · 5)을 달기로 했다. 구현 전에 재 보니 **δ 는 기본 계산 방식(mvo)을
포함해 9 방식 모두에서 비중을 움직이지 않았다**. δ 는 시장 균형 수익 π = δΣw_mkt 에만 들어가고, π 는 블랙-리터먼(bl)에
내 생각(뷰)이 있을 때만 쓰인다(`allocation_studio.optimize`). 그래서 초심자 질문 "위험을 얼마나 피할까요?" 는 거짓 손잡이였다.

## 거는 것
- ★사실 못 박기★ — δ 를 1·2.5·5 로 바꿔도 mvo(기본)·min_var·risk_parity 비중은 같다. 짝: bl + 뷰에서는 달라진다.
  (옵티마이저 의미는 그대로다 — 이 테스트는 **표시가 사실과 맞는지**만 건다. δ 가 비중을 움직이게 바뀌면 이 테스트가 깨져 표시를 다시 보게 한다.)
- 카탈로그 — δ 는 초심자(basic) 질문이 아니다(tier advanced · question 없음) · 도움말이 "블랙-리터먼·내 생각이 있을 때만" 을 말한다 ·
  프리셋을 달지 않는다(움직이지 않는 손잡이에 선택지를 달지 않는다) · 기본값·범위는 그대로(2.5 · 0.5~10).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import VIEW, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")


def _weights(model: str, delta: float, views=None) -> dict:
    g = chain(risk=False, model=model, views=views)
    g["nodes"][3]["params"]["delta"] = delta
    r = pg.run(g, gn.REGISTRY)["nodes"]["o"]
    assert r["status"] == "ok", r["reason"]
    return r["view"]["weights"]


@pytest.mark.parametrize("model", ["mvo", "min_var", "risk_parity"])
def test_delta_does_not_move_the_weights_outside_black_litterman_with_views(market, model):
    base = _weights(model, 2.5)
    for d in (1.0, 5.0):
        assert _weights(model, d) == base, (model, d)


def test_pair_delta_moves_black_litterman_weights_when_there_are_views(market):
    w1, w5 = _weights("bl", 1.0, [VIEW]), _weights("bl", 5.0, [VIEW])
    asset = VIEW["assets"][0]
    # 도움말의 방향까지 — δ 가 클수록 시장 균형 쪽으로(내 생각을 둔 종목의 비중이 줄어든다).
    assert w1[asset] > w5[asset], (w1, w5)


def _delta_schema():
    return gn.REGISTRY.get("optimizer").params_model.model_json_schema()["properties"]["delta"]


def test_the_catalog_does_not_ask_beginners_about_delta_and_says_where_it_matters():
    s = _delta_schema()
    ui = s["x-ui"]
    assert ui["tier"] == "advanced"
    assert "question" not in ui and "presets" not in ui
    assert "블랙-리터먼" in ui["help"] and "내 생각" in ui["help"] and "바뀌지 않아요" in ui["help"]
    assert "위험을 얼마나 피할까요" not in str(ui)


def test_default_and_range_are_unchanged():
    s = _delta_schema()
    assert (s["default"], s["minimum"], s["maximum"]) == (2.5, 0.5, 10)
