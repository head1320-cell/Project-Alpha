"""BO O3 · 갈래 비교의 다중 비교 보정 — PSR / DSR (`src/engine/deflated_sharpe.py`)
==================================================================================
거는 것:
- 공식 골든 — 정규·독립이면 PSR = Φ(SR·√(T−1)/√(1+SR²/2)) · 기대 최대 SR 은 몬테카를로 최대값의 평균과 맞는다.
- N 이 늘면 SR₀ 가 오르고 DSR 이 내려간다(짝 — N 을 무시하는 구현을 죽인다) · DSR ≤ PSR(0).
- 못 재는 경우는 None + 사유(0 으로 채우지 않는다): 후보 1개 · 짧은 표본 · 흔들림 0 · 모두 같은 SR · 망가진 곡선.
- 응답이 "N 은 하한" 을 함께 말한다.
- 문(`/graph/branch-evidence`): 서버 값 그대로 · 저장하지 않는다 · 경로에 유통 마커가 없다.
"""
from __future__ import annotations

import math
import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import deflated_sharpe as ds  # noqa: E402


def _series(mu: float, sd: float = 0.01, T: int = 500, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(mu, sd, T)


def test_psr_matches_normal_closed_form():
    sr, T = 0.08, 253
    want = 0.5 * (1 + math.erf(sr * math.sqrt(T - 1) / math.sqrt(1 + sr * sr / 2) / math.sqrt(2)))
    assert ds.psr(sr, 0.0, T, 0.0, 3.0) == pytest.approx(want, abs=1e-12)
    # 짝 — 왼쪽 꼬리(음의 왜도)·두꺼운 꼬리는 같은 SR 의 확신을 낮춘다
    assert ds.psr(sr, 0.0, T, -1.0, 3.0) < want
    assert ds.psr(sr, 0.0, T, 0.0, 9.0) < want


def test_expected_max_sr_matches_monte_carlo():
    n, v = 50, 0.0004
    rng = np.random.default_rng(1)
    sim = rng.normal(0.0, math.sqrt(v), (40_000, n)).max(axis=1).mean()
    assert ds.expected_max_sr(n, v) == pytest.approx(sim, rel=0.03)


def test_expected_max_sr_golden():
    """공식 값 골든(표준정규, V=1) — N=100 → 2.5306 · N=10 → 1.5746. 오일러–마스케로니 γ 가 틀리면 여기서 걸린다
    (몬테카를로 비교는 근사식의 1~3% 오차 때문에 γ 의 작은 변화를 잡지 못한다)."""
    assert ds.expected_max_sr(100, 1.0) == pytest.approx(2.53060, abs=1e-4)
    assert ds.expected_max_sr(10, 1.0) == pytest.approx(1.57460, abs=1e-4)
    assert ds.expected_max_sr(10, 4.0) == pytest.approx(2 * 1.57460, abs=2e-4)     # √V 배


def test_more_trials_deflate_more():
    assert ds.expected_max_sr(2, 0.001) < ds.expected_max_sr(5, 0.001) < ds.expected_max_sr(20, 0.001)
    base = [{"label": "원본", "returns": _series(0.0008, seed=1)},
            {"label": "갈래 1", "returns": _series(0.0002, seed=2)}]
    more = base + [{"label": f"갈래 {i}", "returns": _series(0.0005, seed=i)} for i in range(2, 8)]
    a, b = ds.compare(base), ds.compare(more)
    assert a["n"] == 2 and b["n"] == 8
    assert b["sr0"] > 0 and a["sr0"] > 0
    ra, rb = a["rows"][0], b["rows"][0]
    assert ra["sr"] == rb["sr"]                     # 같은 흐름
    for r in a["rows"] + b["rows"]:
        assert r["dsr"] <= r["psr0"] + 1e-12       # 보정은 확신을 늘리지 않는다
    assert b["sr0"] > a["sr0"] and rb["dsr"] < ra["dsr"]


def test_dsr_equals_psr_at_sr0():
    rows = [{"label": str(i), "returns": _series(0.0003 * i, seed=i)} for i in range(1, 5)]
    out = ds.compare(rows)
    for r in out["rows"]:
        assert r["dsr"] == pytest.approx(ds.psr(r["sr"], out["sr0"], r["t"], r["skew"], r["kurt"]))
    assert out["var_sr"] == pytest.approx(float(np.var([r["sr"] for r in out["rows"]], ddof=1)))
    assert out["n"] == 4 and out["sr0"] == pytest.approx(ds.expected_max_sr(4, out["var_sr"]))   # N = 비교한 수


@pytest.mark.parametrize("series,why", [
    ([{"label": "원본", "returns": _series(0.001)}], "둘 이상"),
    ([{"label": "a", "returns": _series(0.001, T=30)}, {"label": "b", "returns": _series(0.0, T=30)}], "둘 미만"),
    ([{"label": "a", "returns": np.zeros(200)}, {"label": "b", "returns": _series(0.0)}], "둘 미만"),
])
def test_cannot_measure_says_why(series, why):
    out = ds.compare(series)
    assert out["sr0"] is None and why in out["reason"]
    assert all(r["dsr"] is None for r in out["rows"])


def test_short_and_flat_rows_have_reasons():
    out = ds.compare([{"label": "짧음", "returns": _series(0.001, T=30)},
                      {"label": "평평", "returns": np.full(200, 0.001)},
                      {"label": "a", "returns": _series(0.001, seed=3)},
                      {"label": "b", "returns": _series(0.0, seed=4)}])
    by = {r["label"]: r for r in out["rows"]}
    assert by["짧음"]["sr"] is None and "60" in by["짧음"]["reason"]
    assert by["평평"]["sr"] is None and "표준편차 0" in by["평평"]["reason"]
    assert out["n"] == 4 and out["sr0"] is not None       # N 은 비교한 전부
    assert by["a"]["dsr"] is not None


def test_identical_sr_has_no_spread():
    r = _series(0.001, seed=5)
    out = ds.compare([{"label": "a", "returns": r}, {"label": "b", "returns": r.copy()}])
    assert out["sr0"] is None and "흩어짐이 0" in out["reason"]


def test_equity_to_returns_refuses_broken_curves():
    assert np.allclose(ds.returns_from_equity([1.0, 1.1, 0.99]), [0.1, -0.1])
    for bad in ([1.0], [1.0, 0.0, 1.0], [1.0, float("nan")], [1.0, -1.0]):
        with pytest.raises(ValueError):
            ds.returns_from_equity(bad)


def test_note_says_n_is_a_lower_bound():
    out = ds.compare([{"label": "a", "returns": _series(0.001)}, {"label": "b", "returns": _series(0.0)}])
    assert "실제로 시도한 수보다 작을 수" in out["note"]


# ── 문 ─────────────────────────────────────────────────────────────────────

def _eq(r: np.ndarray) -> list[float]:
    return [1.0] + list(np.cumprod(1 + r))


def test_route_returns_engine_values():
    from fastapi.testclient import TestClient
    from main_api import app
    a, b, c = _series(0.0008, seed=1), _series(0.0001, seed=2), _series(0.0004, seed=3)
    body = {"series": [{"label": "원본", "equity": _eq(a)}, {"label": "갈래 1", "equity": _eq(b)},
                       {"label": "갈래 2", "equity": _eq(c)}]}
    res = TestClient(app).post("/api/v1/allocation/graph/branch-evidence", json=body)
    assert res.status_code == 200, res.text
    got = res.json()
    want = ds.compare([{"label": s["label"], "returns": ds.returns_from_equity(s["equity"])} for s in body["series"]])
    assert got["n"] == 3
    assert got["sr0"] == pytest.approx(want["sr0"])
    assert [r["dsr"] for r in got["rows"]] == pytest.approx([r["dsr"] for r in want["rows"]])


def test_route_broken_curve_is_a_row_reason_not_a_crash():
    from fastapi.testclient import TestClient
    from main_api import app
    body = {"series": [{"label": "원본", "equity": [1.0, 0.0, 1.0]}, {"label": "갈래 1", "equity": _eq(_series(0.0))},
                       {"label": "갈래 2", "equity": _eq(_series(0.001, seed=9))}]}
    got = TestClient(app).post("/api/v1/allocation/graph/branch-evidence", json=body).json()
    row = got["rows"][0]
    assert row["sr"] is None and "0 이하" in row["reason"]
    assert got["n"] == 3


def test_route_path_has_no_distribution_marker():
    from src.api.allocation_graph_routes import router
    paths = [r.path for r in router.routes if "branch-evidence" in r.path]
    assert paths
    for m in ("marketplace", "subscribe", "provider", "publish", "storefront", "/share", "entitlement", "billing"):
        assert all(m not in p for p in paths)


# ── BP P3 · 유효 N — 갈래끼리 닮아 있으면 독립으로 센 수는 더 작다 ─────────────────────────────

def _corr_series(rho: float, k: int, T: int = 600, seed: int = 11) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 1, T)
    return [0.0004 * (i + 1) + 0.01 * (np.sqrt(rho) * common + np.sqrt(1 - rho) * rng.normal(0, 1, T)) for i in range(k)]


def test_n_eff_is_about_n_for_independent_and_small_for_similar():
    ind = ds.compare([{"label": str(i), "returns": r} for i, r in enumerate(_corr_series(0.0, 5))])
    assert 4.0 <= ind["n_eff"] <= 5.0 + 1e-9
    sim = ds.compare([{"label": str(i), "returns": r} for i, r in enumerate(_corr_series(0.97, 5))])
    assert 1.0 <= sim["n_eff"] < 1.3
    assert sim["n"] == 5 and sim["n_eff"] <= sim["n"]


def test_dsr_eff_uses_n_eff_and_is_not_below_dsr():
    out = ds.compare([{"label": str(i), "returns": r} for i, r in enumerate(_corr_series(0.6, 6))])
    assert 2 <= out["n_eff"] < out["n"]
    assert out["sr0_eff"] == pytest.approx(ds.expected_max_sr(out["n_eff"], out["var_sr"]))
    assert out["sr0_eff"] < out["sr0"]
    for r in out["rows"]:
        assert r["dsr_eff"] == pytest.approx(ds.psr(r["sr"], out["sr0_eff"], r["t"], r["skew"], r["kurt"]))
        assert r["dsr_eff"] >= r["dsr"] - 1e-12       # 덜 센 만큼 덜 깎는다


def test_n_eff_below_two_says_why():
    out = ds.compare([{"label": str(i), "returns": r} for i, r in enumerate(_corr_series(0.97, 5))])
    assert out["sr0_eff"] is None and "2 보다 작아" in out["n_eff_reason"]
    assert all(r["dsr_eff"] is None for r in out["rows"])
    assert out["sr0"] is not None                      # N(하한) 기준 보정은 그대로 있다


def test_n_eff_needs_every_series():
    rows = [{"label": str(i), "returns": r} for i, r in enumerate(_corr_series(0.2, 3))]
    rows.append({"label": "짧음", "returns": _series(0.001, T=30)})
    out = ds.compare(rows)
    assert out["n_eff"] is None and "짧음" in out["n_eff_reason"]
    assert out["sr0"] is not None                      # N 보정은 그대로(N=4)


def test_participation_ratio_golden():
    """상관행렬 고유값 λ 로 (Σλ)²/Σλ² — 두 흐름의 상관 ρ 면 2/(1+ρ²)."""
    C = np.array([[1.0, 0.5], [0.5, 1.0]])
    assert ds.participation_ratio(C) == pytest.approx(2 / (1 + 0.25))
    assert ds.participation_ratio(np.eye(4)) == pytest.approx(4.0)
