"""perf_compare — 두 곡선을 맞추고 차이를 내는 순수 함수 (2026-11-09 · 성과 그림 문법 ③ §3.1)

★화면이 빼지 않는다★ 정렬(날짜 합집합 / 순번)의 의미가 한 곳에 있어야 비교 화면·캔버스 비교 노드·현실성 탭이 같은 말을 한다.
- 같은 날짜 → 날짜로 · 각자 첫 유효값을 base 로 · 차이 = (B − A) / base × 100 (%p).
- 한쪽만 있는 날은 그쪽 None(0 아님) · 몇 날인지 센다.
- 공통 날이 짧은 쪽의 반 미만이면 순번("n일째")으로 맞추고 그 사실을 글로(짝: 반 이상이면 날짜).
- 해마다 차이는 해 합집합 · 지표 차이는 한쪽이 없으면 None.
- 순수 엔드포인트는 저장소 없이 답하고 길이가 어긋나면 422 · 캔버스 비교 노드는 곡선이 없으면 사유를 말한다.
- 스트레스 과거 재생은 계산해 둔 자산곡선·벤치마크 곡선·낙폭 사건을 싣는다 · /macro 전략은 낙폭 % 와 어림 라벨 사유를 싣는다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

D = ["2023-01-02", "2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06"]
A = [100.0, 102.0, 101.0, 105.0, 110.0]
B = [100.0, 101.0, 103.0, 104.0, 108.0]


# ── align_curves ───────────────────────────────────────────────────────────────
def test_same_dates_align_by_date_rebased_to_base_and_diff_in_pp():
    from src.engine.perf_compare import align_curves
    c = align_curves(D, A, D, B, base=1.0)
    assert c["alignment"] == "date" and c["x"] == D and c["n"] == 5 and c["common"] == 5
    assert c["missing_a"] == 0 and c["missing_b"] == 0 and c["note"] is None
    assert c["a"][0] == 1.0 and c["a"][-1] == pytest.approx(1.10)
    assert c["b"][-1] == pytest.approx(1.08)
    assert c["diff_pp"][-1] == pytest.approx(-2.0)                     # (1.08 − 1.10) × 100
    assert c["diff_pp"][0] == pytest.approx(0.0)


def test_base_100_scales_values_but_not_the_pp_difference():
    from src.engine.perf_compare import align_curves
    c = align_curves(D, A, D, B, base=100.0)
    assert c["base"] == 100.0 and c["a"][0] == 100.0 and c["a"][-1] == pytest.approx(110.0)
    assert c["diff_pp"][-1] == pytest.approx(-2.0)                     # base 와 무관하게 %p


def test_union_keeps_one_sided_days_as_none_not_zero_and_counts_them():
    from src.engine.perf_compare import align_curves
    c = align_curves(D, A, D[2:], B[2:], base=100.0)
    assert c["alignment"] == "date" and c["x"] == D
    assert c["missing_b"] == 2 and c["missing_a"] == 0
    assert c["b"][:2] == [None, None] and c["diff_pp"][:2] == [None, None]
    assert c["b"][2] == 100.0                                            # B 는 제 첫 유효값을 base 로
    assert c["a"][2] == pytest.approx(101.0)
    assert "없는 날" in (c["note"] or "")


def test_little_overlap_falls_back_to_index_with_reason_and_pair_half_overlap_stays_by_date():
    from src.engine.perf_compare import align_curves
    far = [f"2020-03-0{i}" for i in range(2, 7)]
    c = align_curves(D, A, far, B)
    assert c["alignment"] == "index" and c["n"] == 5
    assert c["x"][0] == "1일째" and c["x"][-1] == "5일째"
    assert "시작부터" in c["note"] and "같은 날끼리가 아니에요" in c["note"]
    assert c["missing_a"] == 0 and c["missing_b"] == 0
    assert c["diff_pp"][-1] == pytest.approx(-2.0)
    # 짝 — 공통 3 = 짧은 쪽 5 의 반 이상이면 날짜로.
    half = D[2:] + ["2023-01-09", "2023-01-10"]
    assert align_curves(D, A, half, B)["alignment"] == "date"
    # 짝 — 공통 1 (반 이상이어도 2 미만) 은 순번.
    one = [D[4], "2023-01-09"]
    assert align_curves(D, A, one, B[:2])["alignment"] == "index"


def test_a_missing_value_inside_a_curve_stays_none_and_the_first_valid_point_is_the_base():
    from src.engine.perf_compare import align_curves
    c = align_curves(D, [None, 50.0, 55.0, None, 60.0], D, B)
    assert c["a"][0] is None and c["a"][1] == 1.0 and c["a"][2] == pytest.approx(1.1) and c["a"][3] is None
    assert c["diff_pp"][0] is None and c["diff_pp"][3] is None and c["diff_pp"][1] is not None


# ── yearly_diff · metric_rows ─────────────────────────────────────────────────
def test_yearly_diff_is_a_union_of_years_with_partial_flags_and_none_where_missing():
    from src.engine.perf_compare import yearly_diff
    pa = {"yearly": [{"year": 2022, "return_pct": 5.0, "partial": True}, {"year": 2023, "return_pct": 10.0, "partial": False}]}
    pb = {"yearly": [{"year": 2023, "return_pct": 12.5, "partial": False}, {"year": 2024, "return_pct": 1.0, "partial": True}]}
    rows = yearly_diff(pa, pb)
    assert [r["year"] for r in rows] == [2022, 2023, 2024]
    assert rows[0]["a_return_pct"] == 5.0 and rows[0]["b_return_pct"] is None and rows[0]["diff_pp"] is None
    assert rows[0]["a_partial"] is True and rows[0]["b_partial"] is False
    assert rows[1]["diff_pp"] == pytest.approx(2.5)
    assert rows[2]["a_return_pct"] is None and rows[2]["b_partial"] is True
    assert yearly_diff(None, None) == []


def test_metric_rows_keep_none_when_a_side_is_missing():
    from src.engine.perf_compare import NODE_METRICS, PAGE_METRICS, metric_rows
    rows = metric_rows({"total_return_pct": 10.0}, {"total_return_pct": 22.6, "sharpe_ratio": 1.1}, PAGE_METRICS)
    by = {r["key"]: r for r in rows}
    assert by["total_return_pct"]["diff"] == pytest.approx(12.6)
    assert by["sharpe_ratio"]["a"] is None and by["sharpe_ratio"]["b"] == 1.1 and by["sharpe_ratio"]["diff"] is None
    assert len(rows) == len(PAGE_METRICS) == 10 and len(NODE_METRICS) == 7
    assert [k for k, _, _ in NODE_METRICS][:2] == ["total_return_pct", "cagr"]


# ── 순수 엔드포인트 ────────────────────────────────────────────────────────────
def _body(**over):
    body = {"a": {"label": "A", "dates": D, "equity": A, "stats": {"total_return_pct": 10.0},
                  "periods": {"yearly": [{"year": 2023, "return_pct": 10.0, "max_drawdown_pct": -1.0, "n_days": 5, "partial": True}], "monthly": []}},
            "b": {"label": "B", "dates": D, "equity": B, "stats": {"total_return_pct": 8.0}, "periods": None},
            "base": 100, "metrics": "page"}
    body.update(over)
    return body


def test_the_pure_endpoint_is_registered_and_answers_without_a_store():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    from tests.route_walk import flat_routes
    app = create_app()
    hits = [r for r in flat_routes(app) if r.path == "/api/v1/perf/compare"]
    assert [sorted(r.methods) for r in hits] == [["POST"]]
    client = TestClient(app)
    res = client.post("/api/v1/perf/compare", json=_body())
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["curves"]["alignment"] == "date" and j["curves"]["base"] == 100.0 and j["curves"]["b"][-1] == pytest.approx(108.0)
    assert j["rows"][0]["key"] == "total_return_pct" and j["rows"][0]["diff"] == pytest.approx(-2.0)
    assert j["yearly"] == [{"year": 2023, "a_return_pct": 10.0, "b_return_pct": None, "diff_pp": None, "a_partial": True, "b_partial": False}]
    # 짝 — stats·metrics 가 없으면 rows 는 None(빈 표가 아니다) · periods 가 둘 다 없으면 yearly 는 None.
    j2 = client.post("/api/v1/perf/compare", json=_body(metrics=None, a={"label": "A", "dates": D, "equity": A}, b={"label": "B", "dates": D, "equity": B})).json()
    assert j2["rows"] is None and j2["yearly"] is None


@pytest.mark.parametrize("bad", [
    {"b": {"label": "B", "dates": D, "equity": B[:-1]}},                 # 길이 불일치
    {"b": {"label": "B", "dates": D[:1], "equity": B[:1]}},               # 점 2개 미만
    {"base": 7},                                                          # base 는 1 또는 100
])
def test_the_pure_endpoint_refuses_malformed_curves_with_422(bad):
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    res = TestClient(create_app()).post("/api/v1/perf/compare", json=_body(**bad))
    assert res.status_code == 422, res.text


# ── 캔버스 비교 노드 ─────────────────────────────────────────────────────────
def _run(rid: str, eq: list[float]) -> dict:
    return {"run_id": rid, "run": {"strategy_name": rid, "is_mock_data": True, "input_snapshot": {},
                                   "result": {"backtest": {"statistics": {"total_return_pct": 1.0, "sharpe_ratio": 0.5},
                                                           "equity_curve": eq, "equity_dates": D[:len(eq)]}}}}


def test_the_compare_node_ships_curves_and_says_why_when_one_side_has_none():
    from src.api.allocation_graph_nodes_backtest import _compare
    out = _compare({"a": _run("A", A), "b": _run("B", B)}, None)
    v = out.view
    assert len(v["rows"]) == 7 and v["differences"] == []                 # 기존 계약 그대로
    cmp_ = v["compare"]
    assert cmp_["curves"]["alignment"] == "date" and cmp_["curves"]["base"] == 1.0 and cmp_["labels"] == {"a": "A", "b": "B"}
    assert cmp_["drawdowns"]["a"] is not None and cmp_["drawdowns"]["b"] is not None
    assert cmp_["yearly"][0]["year"] == 2023
    out2 = _compare({"a": _run("A", A), "b": _run("B", [])}, None)
    assert out2.view["compare"] is None and "곡선" in out2.view["compare_reason"]


# ── 스트레스 과거 재생 ───────────────────────────────────────────────────────
def test_stress_replay_ships_equity_benchmark_and_episodes(monkeypatch):
    import numpy as np
    import pandas as pd

    import src.api.allocation_stress_routes as sr
    import src.kis_portfolio_analyzer as kpa
    idx = pd.bdate_range("2020-02-03", periods=40)
    rng = np.random.default_rng(7)
    df = pd.DataFrame({"005930": rng.normal(-0.002, 0.02, 40), "000660": rng.normal(-0.001, 0.02, 40),
                       "KOSPI": rng.normal(-0.001, 0.015, 40)}, index=idx)
    monkeypatch.setattr(kpa, "load_returns", lambda tickers, start, end: df)
    out, src = sr.historical_replay({"005930": 0.6, "000660": 0.4}, "hist_2020_covid", "KOSPI")
    assert src == "db" and out["available"] is True
    n = len(out["dates"])
    assert len(out["equity_curve"]) == n == len(out["portfolio_dd"]) == len(out["benchmark_curve"]) == len(out["benchmark_dd"])
    assert out["equity_curve"][0] == pytest.approx(1.0 + float(df.iloc[0][["005930", "000660"]] @ np.array([0.6, 0.4])))
    assert out["total_return_pct"] == pytest.approx((out["equity_curve"][-1] - 1.0) * 100, abs=0.02)   # 기존 키와 같은 곡선
    assert out["drawdowns"] and out["drawdowns"][0]["depth_pct"] <= 0 and out["drawdowns"][0]["peak_date"] in out["dates"]
    assert abs(out["drawdowns"][0]["depth_pct"]) == pytest.approx(abs(out["max_dd_pct"]), abs=0.02)


# ── /macro 전략 ──────────────────────────────────────────────────────────────
def test_macro_curve_summary_with_real_month_ends_ships_dates_periods_and_episodes():
    from src.engine.strategy_profiles import _curve_summary
    dates = ["2023-10-31", "2023-11-30", "2023-12-29", "2024-01-31"]
    out = _curve_summary([100.0, 110.0, 99.0, 120.0], [0.1, -0.1, 0.2121], 3, dates=dates)
    assert [c["t"] for c in out["curve"]] == ["23.10", "23.11", "23.12", "24.01"]      # 라벨 = 실제 날짜
    assert out["dates"] == dates and out["dates_note"] is None
    assert len(out["drawdown_pct"]) == 4 and out["drawdown_pct"][2] == pytest.approx(-10.0)
    assert out["summary"]["mdd_pct"] == pytest.approx(-10.0)
    years = {r["year"]: r for r in out["periods"]["yearly"]}
    assert years[2023]["partial"] is True and years[2024]["partial"] is True
    assert years[2023]["return_pct"] == pytest.approx(-1.0)                        # 100 → 99
    assert [m["month"] for m in out["periods"]["monthly"]] == [10, 11, 12, 1]
    assert out["drawdowns"][0]["trough_date"] == "2023-12-29" and out["drawdowns"][0]["recovery_date"] == "2024-01-31"


def test_macro_curve_summary_without_dates_keeps_the_approximate_labels_and_says_so():
    from src.engine.strategy_profiles import _curve_summary
    out = _curve_summary([100.0, 110.0, 99.0, 120.0], [0.1, -0.1, 0.2121], 3)
    assert len(out["drawdown_pct"]) == 4 and max(out["drawdown_pct"]) == 0.0
    assert "어림" in out["dates_note"] and "30일" in out["dates_note"]
    assert out["dates"] is None and out["periods"] is None and out["drawdowns"] is None  # 날짜를 지어내지 않는다
    assert out["summary"]["total_return_pct"] == pytest.approx(20.0)


def test_monthly_closes_dated_matches_monthly_closes_position_by_position(monkeypatch):
    import pandas as pd

    import src.data.etf_prices as ep
    idx = pd.bdate_range("2024-01-02", "2024-06-28")
    df = pd.DataFrame({"close": [100.0 + i for i in range(len(idx))]}, index=idx)
    monkeypatch.setattr(ep, "_daily_df", lambda code: df)
    monkeypatch.setattr(ep, "resolve", lambda t, m: (t, t))
    ep.cache_clear()
    plain = ep.monthly_closes("SPY", "us", 4)
    dated = ep.monthly_closes_dated("SPY", "us", 4)
    assert [v for _, v in dated] == plain and [d for d, _ in dated] == ["2024-03-29", "2024-04-30", "2024-05-31", "2024-06-28"]
    with ep.as_of(2):                                                            # as_of 도 같은 자리를 자른다
        assert [v for _, v in ep.monthly_closes_dated("SPY", "us", 2)] == ep.monthly_closes("SPY", "us", 2)
    ep.cache_clear()


def test_macro_backtest_strategy_threads_real_month_end_dates_into_the_curve():
    from src.engine.strategy_profiles import backtest_strategy
    out = backtest_strategy("classic_dm", "us", months=12)
    assert out["curve"] and out["dates"] and len(out["dates"]) == len(out["curve"])
    assert all(len(d) == 10 and d[4] == "-" for d in out["dates"])                             # ISO 날짜
    assert [c["t"] for c in out["curve"]] == [f"{d[2:4]}.{d[5:7]}" for d in out["dates"]]      # 라벨 = 그 날짜의 달
    assert out["dates_note"] is None and out["periods"]["yearly"] and out["drawdowns"] is not None


def test_macro_backtest_strategy_without_dated_closes_falls_back_to_the_approximate_labels(monkeypatch):
    import src.data.etf_prices as ep
    from src.engine.strategy_profiles import backtest_strategy
    monkeypatch.setattr(ep, "monthly_closes_dated", lambda *a, **k: [])                        # 날짜를 못 얻는 상황
    out = backtest_strategy("classic_dm", "us", months=12)
    assert out["curve"] and out["dates"] is None and out["periods"] is None and out["drawdowns"] is None
    assert "어림" in out["dates_note"]                                                           # 날짜를 지어내지 않고 사유만
