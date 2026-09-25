"""BJ1 · 노드 설명 — ★서버가 쉬운 말을 만든다, 과장 없이·미상을 숨기지 않고★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-workflow-ux-design.md` §4.3 ·
대상 `src/api/allocation_graph_explain.py`(노드 설명기) · `src/api/allocation_graph_nodes.py`

## 거는 것
- 모든 완료 노드가 해요체 제목을 갖는다. 설명의 숫자는 결과(view)의 숫자와 같다(지어내지 않는다).
- mock(합성)이면 데이터를 쓰는 노드가 "연습용" 을 **몰라요(unknown)** 로 말한다 — 짝: DB 면 "등급 몰라요".
- 시장 균형 출발점(BL·EP)에서 시가총액 미상 → 가정(assumed) — 짝: MVO 에서는 그 말을 하지 않는다.
- 백테스트 비용은 가정이고 값이 파라미터를 따른다(짝) · 룩어헤드의 안 잰 축이 `unmeasured` 에 그대로.
- 금지어("검증됨·입증됨·견고함·프로덕션 레디·투자 우위·더 나은 전략") 0 — 출력 전수 + 소스 리터럴 AST.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import VIEW, chain, market  # noqa: E402,F401
from tests.test_allocation_routes import T3, _patch_caps  # noqa: E402

FORBIDDEN = ("검증됨", "입증됨", "견고함", "프로덕션 레디", "투자 우위", "더 나은 전략")


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _texts(ex: dict) -> list[str]:
    out = [ex.get("title", "")]
    h = ex.get("headline") or {}
    out += [str(h.get("text", "")), str(h.get("label", ""))]
    out += list(ex.get("facts") or []) + list(ex.get("unmeasured") or [])
    out += [t["text"] for t in ex.get("trust") or []]
    return [t for t in out if t]


def _states(ex: dict) -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}
    for t in ex.get("trust") or []:
        d.setdefault(t["state"], []).append(t["text"])
    return d


def test_every_ok_node_speaks_in_plain_polite_korean(market):
    out = _run(chain(model="bl", views=[VIEW], lookback=1008, backtest={}))
    for nid, r in out["nodes"].items():
        assert r["status"] == "ok", (nid, r["reason"])
        t = r["explain"]["title"]
        assert t.endswith("요") or t.endswith("요."), (nid, t)


def test_the_optimizer_headline_is_the_largest_weight_it_actually_produced(market):
    o = _run(chain(model="hrp"))["nodes"]["o"]
    w = o["view"]["weights"]
    top = max(w, key=lambda k: w[k])
    h = o["explain"]["headline"]
    assert h["value"] == w[top] and h["unit"] == "%"
    assert o["view"]["labels"][top] in h["label"]


def test_mock_data_is_named_as_practice_data_not_hidden(market, monkeypatch):
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: pd.DataFrame())
    _patch_caps(monkeypatch)
    out = _run(chain(lookback=1008, backtest={}))
    for nid in ("r", "o", "b"):
        unknown = " ".join(_states(out["nodes"][nid]["explain"]).get("unknown", []))
        assert "연습용" in unknown, (nid, out["nodes"][nid]["explain"])


def test_loaded_data_says_its_grade_is_unknown_instead_of_practice(market):
    """★짝★ — DB 적재분이면 "연습용" 이 아니라 "등급을 몰라요"."""
    ex = _run(chain())["nodes"]["r"]["explain"]
    unknown = " ".join(_states(ex).get("unknown", []))
    assert "연습용" not in unknown and "몰라요" in unknown


def test_market_prior_with_missing_caps_is_an_assumption_only_where_it_applies(market, monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap", lambda code: None)
    bl = _states(_run(chain(model="bl", views=[VIEW]))["nodes"]["o"]["explain"])
    assert any("시가총액" in t for t in bl.get("assumed", []))
    mvo = _run(chain(model="mvo"))["nodes"]["o"]["explain"]
    assert not any("시가총액" in t for t in _texts(mvo)), "MVO 는 시장 균형 출발점을 쓰지 않는다"


@pytest.mark.parametrize("bps,shown", [(10.0, "0.1%"), (15.0, "0.15%")])
def test_the_backtest_cost_is_an_assumption_with_the_real_value(market, bps, shown):
    b = _run(chain(lookback=1008, backtest={"cost_bps": bps}))["nodes"]["b"]
    assumed = " ".join(_states(b["explain"]).get("assumed", []))
    assert "거래비용" in assumed and shown in assumed


def test_unmeasured_lookahead_axes_are_listed_not_dropped(market):
    b = _run(chain(lookback=1008, backtest={}))["nodes"]["b"]
    la = b["view"]["lookahead_evidence"]
    assert len(b["explain"]["unmeasured"]) == len(la["unknown_axes"]) > 0


def test_the_view_sentence_matches_black_litterman_semantics(market):
    """절대 뷰는 "그 종목의 1년 기대 수익 = 방향 × 크기" 다 — "더 오른다" 가 아니다."""
    down = {**VIEW, "direction": -1, "magnitude_pct": 3.0, "confidence": 40}
    ex = _run(chain(views=[VIEW, down]))["nodes"]["v"]["explain"]
    assert ex["title"] == "내 생각 2개를 넣었어요"
    assert "기대 수익을 +4%로 봤어요" in ex["facts"][0] and "확신 60%" in ex["facts"][0]
    assert "기대 수익을 −3%로 봤어요" in ex["facts"][1]


def test_risk_headline_is_the_volatility_it_computed(market):
    k = _run(chain())["nodes"]["k"]
    vol = k["view"]["risk_contribution_optimized"]["portfolio_volatility_pct"]
    assert k["explain"]["headline"]["value"] == round(vol, 1)


def test_a_blocked_optimizer_says_where_it_stopped(monkeypatch):
    from tests.test_allocation_routes import _fake_returns_df, _patch_returns
    _patch_returns(monkeypatch, _fake_returns_df(["005930"], n=800))
    out = _run(chain())
    assert "앞 단계 ‘수익률 불러오기’" in out["nodes"]["o"]["explain"]["facts"][0]


# ── 금지어 — 출력 전수 + 소스 리터럴 ───────────────────────────────────────

SCENARIOS = [
    dict(model="mvo"), dict(model="bl", views=[VIEW]), dict(model="hrp"),
    dict(model="risk_parity", constraints={"max_weight_pct": 40}),
    dict(model="bl", views=[VIEW], estimate={"conditional": True}),
    dict(model="min_var", lookback=1008, backtest={"cost_bps": 20}),
]


@pytest.mark.parametrize("kw", SCENARIOS)
def test_no_overclaiming_words_in_any_explanation(market, kw):
    out = _run(chain(**kw))
    texts = [t for r in out["nodes"].values() for t in _texts(r["explain"])]
    assert texts, "★공허 금지★"
    bad = [t for t in texts for w in FORBIDDEN if w in t]
    assert not bad, bad


def test_no_overclaiming_words_in_the_explainer_source():
    lits = []
    files = sorted({*map(str, pathlib.Path("src/api").glob("allocation_graph_*.py")),
                    "src/domain/workflow_gates.py"})
    assert len(files) >= 4, files                 # 설명기 · 노드 · 문 · 웨이브 모듈이 모두 쓸린다
    for f in files:
        tree = ast.parse(pathlib.Path(f).read_text("utf-8"))
        lits += [n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert lits
    assert not [s for s in lits for w in FORBIDDEN if w in s and "금지" not in s]


def test_every_core_node_has_an_explainer_plain_words_and_a_stage():
    for spec in (gn.REGISTRY.get(t) for t in gn.REGISTRY.types()):
        assert spec.explain is not None, spec.type
        assert spec.plain_label and spec.plain_description, spec.type
        assert spec.stage in {s["key"] for s in gn.STAGES}, spec.type


def test_the_universe_explains_unknown_codes_honestly(market):
    g = chain(tickers=[*T3, "ZZZZZZ"])
    ex = _run(g)["nodes"]["u"]["explain"]
    assert ex["title"] == "종목 4개를 골랐어요"
    assert any("ZZZZZZ" in t for t in _states(ex).get("unknown", []))


# ── 화면 메타(x-ui) — 쉬운 이름·층·프리셋 ─────────────────────────────────

def _props(schema: dict) -> dict:
    return (schema or {}).get("properties") or {}


def test_every_parameter_has_a_plain_label_and_a_tier():
    for c in gn.REGISTRY.catalog():
        for name, prop in _props(c["params_schema"]).items():
            ui = prop.get("x-ui")
            assert ui and ui.get("label") and ui.get("tier") in {"basic", "advanced"}, (c["type"], name)


def test_every_node_with_params_offers_at_least_one_basic_question():
    for c in gn.REGISTRY.catalog():
        props = _props(c["params_schema"])
        if props:
            assert any(p["x-ui"]["tier"] == "basic" for p in props.values()), c["type"]


def test_every_preset_is_a_value_the_server_accepts():
    """★프리셋은 버튼이다★ — 서버가 거절하는 값을 버튼으로 내면 누르는 순간 빨개진다."""
    n = 0
    for t in gn.REGISTRY.types():
        spec = gn.REGISTRY.get(t)
        if spec.params_model is None:
            continue
        for name, prop in _props(spec.params_model.model_json_schema()).items():
            for pr in prop.get("x-ui", {}).get("presets") or []:
                spec.params_model.model_validate({**_required(t), name: pr["value"]})
                n += 1
    assert n >= 8, "★공허 금지★ — 프리셋이 실제로 검사됐다"


def _required(t):
    return {"tickers": ["005930"]} if t == "universe" else {}


def test_enum_options_cover_exactly_the_allowed_values():
    for c in gn.REGISTRY.catalog():
        for name, prop in _props(c["params_schema"]).items():
            opts = prop.get("x-ui", {}).get("options")
            if opts is None:
                continue
            allowed = set(prop.get("enum") or [])
            pat = prop.get("pattern")
            if not allowed and pat:
                import re
                allowed = {k for k in opts if re.fullmatch(pat, k)}
                assert allowed == set(opts), (c["type"], name, "선택지가 패턴 밖")
            else:
                assert set(opts) == allowed, (c["type"], name)
