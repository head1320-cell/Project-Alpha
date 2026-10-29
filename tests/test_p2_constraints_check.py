"""CF 3부 P2 — 제약 편집기의 확인 경로 `POST /api/v1/allocation/constraints/check` (★엔진 무변경 · 읽기만★)

편집기가 계산 전에 "이 조합은 풀 수 없어요" 를 말하려면 엔진과 ★같은 판정★이 필요하다. 그래서 이 경로는 엔진의
`_precheck`(구조적 불능)와 `sector_groups_for`(업종 표)를 그대로 부르고, 업종 상한이 빠질지는 P1 의 `_group_cap_gaps` 로 센다.
같은 사실을 두 번 만들지 않는다 — 아래 테스트는 경로의 답이 ★실제 엔진 결과와 같은지★를 함께 본다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.app_factory import create_app  # noqa: E402

URL = "/api/v1/allocation/constraints/check"
NAMES = ["000001", "000002", "000003", "000004"]
SEMI = {"000001": "반도체", "000002": "반도체", "000003": "자동차"}


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


@pytest.fixture
def sectors(monkeypatch):
    import src.engine.constrained_opt as co
    table: dict[str, str] = dict(SEMI)
    monkeypatch.setattr(co, "sector_groups_for", lambda names: {t: g for t, g in table.items() if t in names})
    return table


def _post(client, constraints: dict, names=NAMES, **extra):
    r = client.post(URL, json={"constraints": constraints, "names": names, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _engine(constraints: dict, model: str = "mvo", groups=SEMI):
    from src.api.allocation_routes import ConstraintsInput
    from src.engine.constrained_opt import Constraints, constrained_solve
    rng = np.random.default_rng(3)
    R = rng.normal(0.0004, 0.012, (300, len(NAMES)))
    return constrained_solve(model, NAMES, R, R.mean(axis=0) * 252, np.cov(R.T) * 252,
                             Constraints(**ConstraintsInput(**constraints).model_dump()), groups_of=groups)


# ── 풀 수 없는 조합 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("c", [
    {"max_weight_pct": 20},                                    # 20% × 4종목 = 80% < 100%
    {"min_weight_pct": 30},                                    # 30% × 4 > 100%
    {"cash_min_pct": 20, "cash_max_pct": 10},                  # 현금 밴드 뒤집힘
    {"net_min_pct": 50, "net_max_pct": 10},                    # 넷 밴드 뒤집힘
    {"min_weight_pct": -10, "gross_max_pct": 50, "net_min_pct": 100, "net_max_pct": 100},
])
def test_infeasible_combination_is_refused_with_the_engines_own_reason(client, sectors, c):
    out = _post(client, c)
    eng = _engine(c)
    assert out["ok"] is False and eng["status"] == "infeasible"
    assert out["reason"] == eng["reason"]                      # ★같은 판정★ — 경로가 따로 지어내지 않는다


@pytest.mark.parametrize("c", [{"max_weight_pct": 30}, {"max_weight_pct": 40, "group_caps_pct": {"반도체": 50}}, {}])
def test_feasible_combination_passes(client, sectors, c):
    """짝 — 풀 수 있는 조합은 ok(항상-거부 구현 배제)."""
    out = _post(client, c)
    assert out["ok"] is True and out["reason"] is None


def test_group_cap_sum_infeasible_needs_the_sector_table(client, sectors):
    """업종 상한 합으로 막히는 경우 — 업종 표가 있어야 판정된다(엔진과 같은 표)."""
    c = {"max_weight_pct": 40, "group_caps_pct": {"반도체": 10, "자동차": 10}}
    sectors["000004"] = "자동차"                               # 모든 종목에 업종 → 상한 합 20% < 100%
    out = _post(client, c)
    assert out["ok"] is False and "그룹 상한" in out["reason"]


# ── 업종 ─────────────────────────────────────────────────────────────────

def test_sector_names_and_unknown_names(client, sectors):
    out = _post(client, {})
    assert out["group_names"] == ["반도체", "자동차"]
    assert out["groups"] == SEMI
    assert out["unknown"] == ["000004"]
    assert out["sectors_readable"] is True


def test_unreadable_sectors_are_said(client, monkeypatch):
    import src.engine.constrained_opt as co
    monkeypatch.setattr(co, "sector_groups_for", lambda names: {})
    out = _post(client, {"group_caps_pct": {"반도체": 30}})
    assert out["sectors_readable"] is False and out["group_names"] == []
    assert [u["group"] for u in out["unapplied"]] == ["반도체"]


def test_a_cap_on_a_missing_sector_is_previewed(client, sectors):
    out = _post(client, {"group_caps_pct": {"바이오": 20}})
    assert [u["group"] for u in out["unapplied"] if u["kind"] == "group_cap"] == ["바이오"]


def test_a_cap_on_a_present_sector_is_not_previewed(client, sectors):
    """짝."""
    out = _post(client, {"group_caps_pct": {"반도체": 20}})
    assert [u for u in out["unapplied"] if u["kind"] == "group_cap"] == []


# ── 공매도 ───────────────────────────────────────────────────────────────

def test_negative_floor_is_research_only(client, sectors):
    out = _post(client, {"min_weight_pct": -10})
    assert out["allows_short"] is True and "연구" in out["short_note"]


def test_long_only_has_no_short_note(client, sectors):
    """짝."""
    out = _post(client, {"min_weight_pct": 0})
    assert out["allows_short"] is False and out["short_note"] is None


@pytest.mark.parametrize("model", ["risk_parity", "hrp"])
def test_cov_only_model_with_shorts_is_refused_like_the_engine(client, sectors, model):
    c = {"min_weight_pct": -10}
    out = _post(client, c, model=model)
    eng = _engine(c, model=model)
    assert eng["status"] == "infeasible" and out["ok"] is False and out["reason"] == eng["reason"]


def test_cov_only_model_long_only_passes(client, sectors):
    """짝 — 공매도가 없으면 같은 방식도 통과."""
    assert _post(client, {"max_weight_pct": 40}, model="risk_parity")["ok"] is True


# ── 종목을 모를 때 · 입력 ─────────────────────────────────────────────────

def test_without_names_nothing_is_judged(client, sectors):
    """종목 수를 모르면 '× n종목' 판정을 하지 않는다 — 통과라고도 하지 않는다."""
    out = _post(client, {"max_weight_pct": 20}, names=[])
    assert out["checked"] is False and out["ok"] is None and out["reason"] is None


def test_out_of_range_values_are_422(client):
    r = client.post(URL, json={"constraints": {"max_weight_pct": 0.5}, "names": NAMES})
    assert r.status_code == 422


def test_duplicate_names_count_once(client, sectors):
    """같은 종목을 두 번 적어도 한 종목 — '× n종목' 이 부풀지 않는다(30% × 3종목 = 90% < 100% 는 불능)."""
    assert _post(client, {"max_weight_pct": 30}, names=NAMES[:3])["ok"] is False
    assert _post(client, {"max_weight_pct": 30}, names=NAMES[:3] + NAMES[:3])["ok"] is False
