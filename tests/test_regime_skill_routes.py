"""국면 예측 비교(M2)의 문 · 캔버스 노드.

★문은 판정하지 않는다★ 엔진(`regime_skill`)의 답을 그대로 싣는다. 노드는 문과 같은 함수를 부른다(골든).
★개발 자료의 한계를 숨기지 않는다★ 개발용 합성 매크로 계열은 두 축이 다 계산된 달이 53개뿐이라 1개월 앞 평가 시점이 17개(< 20)다 —
문과 노드는 값 없음 + 사유를 낸다(평가 하한을 낮추거나 자료를 늘려 지어내지 않는다). 짝: 긴 계열을 넣으면 표가 나온다.
"""
from __future__ import annotations

import json
import math
import os
import pathlib

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402
from main_api import app  # noqa: E402

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from src.engine import regime_skill as rs  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import _node  # noqa: E402
from tests.test_regime_ensemble import _series  # noqa: E402

client = TestClient(app)
#: 개발 모드의 `macro_series_map` 이 내는 계보 태그와 같은 모양(긴 합성 계열을 심을 때).
_DEV_TAGS = {"pit": "forward_only", "practice": True, "sources": ["test:long_series"]}


def _one(**params):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("m", "regime_skill", **params)], "edges": []}
    return pg.run(g, gn.REGISTRY)["nodes"]["m"]


def _fake_arms(calls: list):
    def arms(g, i):
        calls.append(len(g))
        p = {"Goldilocks": 0.4, "Reflation": 0.3, "Stagflation": 0.2, "Disinflation": 0.1}
        return {"gmm": {"available": True, "probs": dict(p)}, "kmeans": {"available": True, "probs": dict(p)}}
    return arms


# ── 문 ─────────────────────────────────────────────────────────────────────────

def test_on_the_development_data_the_route_says_why_there_is_no_table():
    r = client.get("/api/v1/macro/regime-skill")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert "평가 시점이 17개" in body["reason"] and "최소 20개" in body["reason"]
    assert body["market"] == "kr" and body["months"] == 120
    assert body["span"]["n_months"] == 53 and body["span"]["dropped_incomplete"] == 67   # 뺀 달이 몇인지 함께 말한다
    assert "candidates" not in body


@pytest.mark.parametrize("q", ["months=59", "months=241", "k=0", "k=13", "market=jp"])
def test_out_of_range_requests_are_refused(q):
    assert client.get(f"/api/v1/macro/regime-skill?{q}").status_code == 422


def test_the_view_scores_a_long_series_and_carries_market_months_and_span(monkeypatch):
    from src.api.macro_routes import regime_skill_view
    calls: list = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))
    rs.cached_arms.cache_clear()
    out = regime_skill_view(_series(140), market="kr", months=120, k=1)
    assert out["available"] is True, out.get("reason")
    assert [c["key"] for c in out["candidates"]] == list(rs.CANDIDATES)
    assert (out["market"], out["months"]) == ("kr", 120)
    assert out["span"]["n_months"] == 120 and out["span"]["dropped_incomplete"] == 0
    assert out["n_eval"] == 120 - 36 and calls == list(range(36, 120))
    rs.cached_arms.cache_clear()


def test_the_view_reuses_the_fits_when_only_k_changes(monkeypatch):
    """k 가 바뀌어도 시점마다의 적합(축 값이 같다)은 같다 — 두 번째 요청은 다시 적합하지 않는다."""
    from src.api.macro_routes import regime_skill_view
    calls: list = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))
    rs.cached_arms.cache_clear()
    regime_skill_view(_series(140), market="kr", months=120, k=1)
    n = len(calls)
    out = regime_skill_view(_series(140), market="kr", months=120, k=3)
    assert out["available"] is True and len(calls) == n               # 새 적합 0
    rs.cached_arms.cache_clear()


def test_the_view_uses_the_complete_months_of_the_regime_path(monkeypatch):
    """두 축이 다 계산된 달만 — 앞의 빈 달을 0 으로 채워 넣지 않는다(M1b 와 같은 입력)."""
    from src.api.macro_routes import regime_skill_view
    from src.engine.regime_transitions import regime_path
    seen: list = []

    def arms(g, i):
        seen.append((tuple(g), tuple(i)))
        p = {"Goldilocks": 1.0, "Reflation": 0.0, "Stagflation": 0.0, "Disinflation": 0.0}
        return {"gmm": {"available": True, "probs": dict(p)}, "kmeans": {"available": True, "probs": dict(p)}}
    monkeypatch.setattr(rs, "default_arms", arms)
    rs.cached_arms.cache_clear()
    smap = _series(110)                                                # 120개월을 청하면 앞의 17개월은 빈 달
    pts = regime_path(smap, market="kr", months=120)["points"]
    out = regime_skill_view(smap, market="kr", months=120, k=1)
    assert out["span"]["dropped_incomplete"] == 17 and out["n_eval"] == len(pts) - 36
    g_all = tuple(p["growth"] for p in pts)
    assert all(g == g_all[: len(g)] for g, _ in seen) and 0.0 not in g_all
    rs.cached_arms.cache_clear()


def test_without_a_regime_path_the_view_gives_the_path_reason(monkeypatch):
    from src.api import macro_routes
    monkeypatch.setattr("src.engine.regime_transitions.regime_path",
                        lambda *a, **k: {"points": [], "reason": "성장·물가 축을 구성할 지표가 없습니다", "span": {"n_months": 0}})
    out = macro_routes.regime_skill_view({}, market="kr", months=120, k=1)
    assert out["available"] is False and "지표가 없습니다" in out["reason"]


# ── 캔버스 노드 ─────────────────────────────────────────────────────────────────

def test_the_node_is_registered_with_a_plain_label_and_a_cost_note():
    spec = gn.REGISTRY.get("regime_skill")
    assert spec.label == "국면 예측 비교" and spec.stage == "signal"
    assert "후보 여섯" in spec.plain_description and "고르지 않습니다" in spec.plain_description
    assert "macro_routes.regime_skill_view" in spec.description and "초" in spec.description   # 시간이 든다는 사실


def test_on_the_development_data_the_node_fails_with_the_engine_reason(graph_write_guard):
    r = _one()
    assert r["status"] == "failed"
    assert "평가 시점이 17개" in r["reason"] and "최소 20개" in r["reason"]


def test_the_node_equals_the_view_when_there_is_a_table(monkeypatch, graph_write_guard):
    from src.api import macro_routes
    calls: list = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))
    rs.cached_arms.cache_clear()
    long = _series(140)
    monkeypatch.setattr("src.api.allocation_graph_nodes_macro_w2.macro_series_map", lambda: (long, _DEV_TAGS))
    r = _one(market="kr", months=120, k=1)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == macro_routes.regime_skill_view(long, market="kr", months=120, k=1)
    rs.cached_arms.cache_clear()


def test_the_node_explains_every_candidate_without_naming_a_winner(monkeypatch, graph_write_guard):
    calls: list = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))
    rs.cached_arms.cache_clear()
    long = _series(140)
    monkeypatch.setattr("src.api.allocation_graph_nodes_macro_w2.macro_series_map", lambda: (long, _DEV_TAGS))
    r = _one(market="kr", months=120, k=1)
    ex = r["explain"]
    facts = " / ".join(ex["facts"])
    for name in rs.CANDIDATE_NAMES.values():
        assert name in facts
    trust = " / ".join(t["text"] for t in ex["trust"])
    assert "이전 자료만으로" in trust and "고르지 않습니다" in trust and "상한 가정 없이" in trust
    assert ex.get("headline") is None                                   # 한 숫자를 앞세우지 않는다(이긴 후보를 암시하지 않는다)
    assert any("경제적 가치" in u for u in ex["unmeasured"])
    rs.cached_arms.cache_clear()


def test_a_candidate_that_could_not_be_built_keeps_its_fact_line_with_the_reason(monkeypatch, graph_write_guard):
    """세우지 못한 후보도 사실 줄에 남는다 — 숫자 대신 사유(빼면 '다섯만 견줬다'로 읽힌다). 짝: 세운 후보는 숫자를 적는다."""
    def arms(g, i):
        p = {"Goldilocks": 0.4, "Reflation": 0.3, "Stagflation": 0.2, "Disinflation": 0.1}
        return {"gmm": {"available": False, "reason": "표본이 부족해 GMM 이 수렴하지 않았습니다"},
                "kmeans": {"available": True, "probs": dict(p)}}
    monkeypatch.setattr(rs, "default_arms", arms)
    rs.cached_arms.cache_clear()
    long = _series(140)
    monkeypatch.setattr("src.api.allocation_graph_nodes_macro_w2.macro_series_map", lambda: (long, _DEV_TAGS))
    r = _one(market="kr", months=120, k=1)
    rs.cached_arms.cache_clear()
    assert r["status"] == "ok", r["reason"]
    facts = r["explain"]["facts"]
    assert len(facts) == len(rs.CANDIDATES)
    for key in ("gmm_start", "gmm_now"):
        line = next(f for f in facts if f.startswith(rs.CANDIDATE_NAMES[key] + ":"))
        assert "값 없음" in line and "수렴하지 않았습니다" in line and "적중" not in line
    kline = next(f for f in facts if f.startswith(rs.CANDIDATE_NAMES["kmeans_share"] + ":"))
    assert "적중" in kline and "값 없음" not in kline                     # 짝


def test_with_k_above_one_the_node_says_the_evidence_was_not_computed(monkeypatch, graph_write_guard):
    calls: list = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))
    rs.cached_arms.cache_clear()
    long = _series(140)
    monkeypatch.setattr("src.api.allocation_graph_nodes_macro_w2.macro_series_map", lambda: (long, _DEV_TAGS))
    r = _one(market="kr", months=120, k=3)
    trust = " / ".join(t["text"] for t in r["explain"]["trust"])
    assert "겹칩니다" in trust and "상한 가정 없이" not in trust                # 짝
    rs.cached_arms.cache_clear()


# ── 화면 고정물(E2E) — 서버가 낸 노드 결과를 그대로 찍어 둔다 ─────────────────────────────

#: 캔버스 · 매크로 화면 E2E 가 '표가 있는 응답'으로 쓰는 고정물. 개발 자료로는 표가 나오지 않으므로(평가 시점 17개) 긴 합성 계열 +
#: 결정적 가짜 군집 팔로 서버의 노드를 돌린 출력이다 — ★손으로 지은 응답이 아니다★ 이 시험이 고정물 = 지금 서버의 출력을 건다.
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "e2e" / "fixtures" / "regime-skill-node.json"


def _quad_arms(g, i):
    """결정적 가짜 군집 팔 — 값의 실재성이 아니라 응답의 모양을 위한 것(마지막 점의 사분면에 0.7 · 최근 셋의 평균 사분면에 k-평균 1)."""
    from src.engine.regime_axes import quadrant
    from src.engine.regime_transitions import REGIMES
    last = quadrant(g[-1], i[-1])
    km = quadrant(sum(g[-3:]) / 3, sum(i[-3:]) / 3)
    return {"gmm": {"available": True, "probs": {r: (0.7 if r == last else 0.1) for r in REGIMES}},
            "kmeans": {"available": True, "probs": {r: (1.0 if r == km else 0.0) for r in REGIMES}}}


def _close(a, b, path="$"):
    """같은 모양 · 같은 글 · 부동소수는 상대 1e-9 — 기계마다 수학 함수의 마지막 자리가 다를 수 있다."""
    if isinstance(a, float) or isinstance(b, float):
        assert isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), f"{path}: {a!r} ≠ {b!r}"
    elif isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f"{path}: 열쇠 {sorted(set(a) ^ set(b))}"
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), f"{path}: 길이"
        for n, (x, y) in enumerate(zip(a, b, strict=True)):
            _close(x, y, f"{path}[{n}]")
    else:
        assert a == b, f"{path}: {a!r} ≠ {b!r}"


class _Dated:
    """`_series` 의 계열에 달 날짜를 붙인 것 — 화면 고정물의 시점 이름이 실제 응답처럼 'YYYY-MM' 이 되게(없으면 'T-k')."""

    def __init__(self, values, timestamps):
        self.values, self.timestamps = values, timestamps


def _dated_series(n: int, last: tuple[int, int] = (2026, 10)) -> dict:
    y, m = last
    months = []
    for _ in range(n):
        months.append(f"{y:04d}-{m:02d}-01")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    stamps = months[::-1]
    return {k: _Dated(s.values, stamps) for k, s in _series(n).items()}


def test_the_screen_fixture_is_what_the_node_produces(monkeypatch, graph_write_guard):
    monkeypatch.setattr(rs, "default_arms", _quad_arms)
    rs.cached_arms.cache_clear()
    long = _dated_series(140)
    monkeypatch.setattr("src.api.allocation_graph_nodes_macro_w2.macro_series_map", lambda: (long, _DEV_TAGS))
    r = _one(market="kr", months=120, k=1)
    got = json.loads(json.dumps({k: r[k] for k in ("type", "status", "reason", "view", "explain")}, ensure_ascii=False))
    rs.cached_arms.cache_clear()
    assert got["status"] == "ok" and len(got["view"]["result"]["candidates"]) == 6
    if os.environ.get("REGEN_SCREEN_FIXTURES") == "1":
        FIXTURE.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert FIXTURE.exists(), f"고정물이 없습니다 — REGEN_SCREEN_FIXTURES=1 로 짓습니다: {FIXTURE}"
    _close(got, json.loads(FIXTURE.read_text(encoding="utf-8")))
