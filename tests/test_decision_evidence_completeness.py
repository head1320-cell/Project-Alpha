"""결정 증거의 완결성 — ★미상을 아니오·0 으로 적지 않는다★ (T1~T3)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md`
선행: S1~S6 (`da39c27`~`85a84d1`)

## T1 ★자기참조 편익★ — S6 의 "셔플 200개가 전부 trade" 를 설명한 것

편익은 `utility(w_target, μ) − utility(w_current, μ)` 인데, 라우트가 넘기는 `μ` 는
`opt["mu_used"]` — **바로 그 `w_target` 을 고른 BL 사후분포**다. `w_target` 은 그 μ
아래 효용을 최대화한 해이므로 같은 μ 로 재면 ★이득이 구조적으로 보장된다★.
어떤 뷰든(진짜든 셔플이든) 자기 신념 아래서는 크게 이득이다.

★규칙 자체는 옳다★ 자기 사후분포 아래 기대효용은 의사결정 이론의 정석이다. 틀린
것은 응답이 그것을 **독립적 증거처럼** 적는다는 점이다. 그래서 규칙을 바꾸지 않고
**신고 필드**를 더한다.

## T3 신선도

지금은 이 결정이 얼마나 낡은 데이터 위에 섰는지 기록에 없다. 라우트가 이미 갖고
있는 `coverage` 에서 **파생**한다 — 지어내지 않는다.
"""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.investment_decisions as idec  # noqa: E402
from src.engine.investment_decision import decide  # noqa: E402

NAMES = ["a", "b", "c"]
CUR = {"a": 40.0, "b": 35.0, "c": 25.0}
TGT = {"a": 60.0, "b": 25.0, "c": 15.0}
PV = 100_000_000.0

TICKERS = ["005930", "000660", "035420"]
DECIDE_URL = "/api/v1/allocation/rebalance-decision"


def _mu_sigma():
    rng = np.random.default_rng(4)
    R = rng.normal(0.0004, 0.012, size=(300, 3))
    return R.mean(axis=0) * 252.0, np.cov(R, rowvar=False) * 252.0


def _decide(evidence=None, **kw):
    mu, sigma = _mu_sigma()
    return decide(CUR, TGT, portfolio_value=PV, names=NAMES, mu=mu, sigma=sigma,
                  evidence=evidence, persist=False, **kw)


# ══════════════════════════════════════════════════════════════════════════
# E1·E2·E3 ★어느 믿음 아래서 쟀는가★
# ══════════════════════════════════════════════════════════════════════════
def test_a_target_from_the_optimizer_is_marked_self_referential():
    p = _decide({"target_source": "optimize:bl"})["benefit"]["provenance"]
    assert p["self_referential"] is True
    assert p["evaluated_under"] == "posterior_that_chose_target"
    assert p["target_source"] == "optimize:bl"
    assert p["reason"]


def test_a_client_supplied_target_is_not_self_referential():
    """★짝★ 항상 True 를 적는 구현을 배제한다 — 고객이 목표를 주면 순환이 아니다."""
    p = _decide({"target_source": "request"})["benefit"]["provenance"]
    assert p["self_referential"] is False
    assert p["evaluated_under"] == "posterior_independent_of_target"


@pytest.mark.parametrize("ev", [None, {}, {"target_source": None},
                                {"mes_id": "m1"}])
def test_an_undeclared_target_source_is_unknown_not_no(ev):
    """★핵심★ 미상 ≠ 아니오.

    출처를 선언하지 않았다는 것과 "자기참조가 아니다" 는 **다른 진술**이다.
    `False` 로 적으면 순환인 판단이 순환이 아닌 것처럼 기록된다.
    """
    p = _decide(ev)["benefit"]["provenance"]
    assert p["self_referential"] is None
    assert p["reason"] and "선언" in p["reason"]


def test_the_provenance_survives_into_the_stored_belief():
    """감사 자리 — 응답은 사라져도 기록은 남는다(S1 이 만든 이유가 그것이다)."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    mu, sigma = _mu_sigma()
    out = decide(CUR, TGT, portfolio_value=PV, names=NAMES, mu=mu, sigma=sigma,
                 evidence={"target_source": "optimize:mvo"},
                 belief={"mu_source": "optimize:mvo"}, persist=True, engine=eng)
    assert out["persisted"] is True, out["persist_reason"]

    row = idec.get_decision(out["dec_id"], engine=eng)
    assert row["belief"]["benefit_provenance"]["self_referential"] is True


def test_the_upstream_benefit_dict_is_not_mutated_in_place():
    """★상류를 제자리에서 고치지 않는다★

    `rebalance_policy` 가 돌려준 dict 를 그 자리에서 고치면, 같은 객체를 들고 있는
    다른 소비자가 결정 계층의 파생 필드를 **자기 산출로** 착각한다.
    """
    import src.engine.rebalance_policy as rp

    seen: list[dict] = []
    real = rp.rebalance_decision

    def spy(*a, **kw):
        out = real(*a, **kw)
        seen.append(out.get("benefit"))
        return out

    rp.rebalance_decision = spy
    try:
        _decide({"target_source": "optimize:bl"})
    finally:
        rp.rebalance_decision = real

    assert seen and seen[0] is not None
    assert "provenance" not in seen[0], "상류 dict 가 오염됐다"


def test_even_an_undetermined_decision_carries_the_provenance():
    """편익을 못 재도 **어느 믿음이었는지**는 사실이다 — 칸을 비우지 않는다."""
    out = decide(CUR, TGT, portfolio_value=PV, names=NAMES, mu=None, sigma=None,
                 evidence={"target_source": "optimize:bl"}, persist=False)
    assert out["decision"] == "undetermined"
    assert out["benefit"]["provenance"]["self_referential"] is True


# ══════════════════════════════════════════════════════════════════════════
# E7·E10·E12 라우트 — ★파생해서 담는다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _post(client, **kw):
    body = {"tickers": TICKERS, "holdings": {t: 100 / 3 for t in TICKERS},
            "portfolio_value": PV, "model": "bl", "horizon_days": 63}
    body.update(kw)
    r = client.post(DECIDE_URL, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_route_response_says_which_belief_measured_the_benefit(client):
    """응답을 읽는 사람이 보는 자리 — "2.16% 개선" 이 어느 μ 아래인지."""
    p = _post(client)["benefit"]["provenance"]
    assert p["self_referential"] is True          # 목표가 optimize 에서 나왔다
    assert p["target_source"].startswith("optimize:")


def test_a_client_supplied_target_flips_it(client):
    """★짝★ 라우트가 출처를 실제로 넘기는지 — 상수로 박은 구현을 배제한다."""
    p = _post(client, target_weights={t: 100 / 3 for t in TICKERS})["benefit"]["provenance"]
    assert p["self_referential"] is False


def test_the_decision_record_carries_data_freshness(client):
    """★이 결정이 얼마나 낡은 데이터 위에 섰는가★ — 지금까지 기록에 없었다."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    import src.data.investment_decisions as m
    orig = m._engine
    m._engine = lambda engine=None: eng
    try:
        body = _post(client, record_decision=True)
    finally:
        m._engine = orig

    row = idec.get_decision(body["dec_id"], engine=eng)
    f = row["evidence"]["data_freshness"]
    assert f["last_observation"] and f["as_of_effective"]
    assert isinstance(f["stale_days"], int) and f["stale_days"] >= 0
    assert f["source"] in ("mock", "db")
    assert f["n_obs"] > 0


# ══════════════════════════════════════════════════════════════════════════
# E11 ★날짜를 못 구하면 0 이 아니라 None★
# ══════════════════════════════════════════════════════════════════════════
def test_an_unknown_freshness_is_none_with_a_reason():
    """0 으로 채우면 "오늘 데이터다" 로 읽힌다 — 미상은 그것과 다른 진술이다."""
    from src.api.allocation_routes import _freshness

    f = _freshness({"end": None, "as_of_effective": "2026-08-29",
                    "source": "db", "n_obs": 10})
    assert f["stale_days"] is None and f["reason"]

    g = _freshness({})
    assert g["stale_days"] is None and g["reason"]


def test_a_known_freshness_is_measured_not_assumed():
    """★짝★ 항상 None 을 내는 구현을 배제한다."""
    from src.api.allocation_routes import _freshness

    f = _freshness({"end": "2026-08-24", "as_of_effective": "2026-08-29",
                    "source": "db", "n_obs": 300})
    assert f["stale_days"] == (date(2026, 8, 29) - date(2026, 8, 24)).days == 5
    assert f["reason"] is None
    assert f["note"]                      # 휴장일이면 0 보다 크다는 사실


# ══════════════════════════════════════════════════════════════════════════
# E8·E9 ★스킵된 조건부 뷰를 쓰인 것으로 세지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def _cond_stack(extra_views):
    return {"cond": {"available": True, "regime": "TEST", "names": [], "mu": []},
            "path": {"points": [], "path_source": None, "reason": None},
            "s_override": None, "extra_views": extra_views,
            "view_conf": 50.0, "meta": {}}


def _view(asset):
    return {"assets": [asset], "direction": 1, "magnitude_pct": 3.0,
            "confidence": 40, "source": "conditional"}


def test_a_skipped_conditional_view_is_not_counted_as_carried(client, monkeypatch):
    """유니버스 밖 자산을 겨눈 뷰는 P 행이 되지 못한다 — 그런데 공시가 셌다.

    ★패치는 `allocation_pipeline` 을 겨눈다 (P8 ②)★ `allocation_routes` 가 이
    이름을 재수출하지만 **호출부가 파이프라인에 있다** — 라우트 쪽 이름을 바꿔야
    아무 일도 일어나지 않는다. 재수출 경로로 되돌리면 이 테스트는 조용히
    아무것도 재지 않게 된다.
    """
    monkeypatch.setattr(
        "src.api.allocation_pipeline._conditional_stack",
        lambda req, returns: _cond_stack([_view(TICKERS[0]), _view("없는종목")]))
    body = _post(client, conditional=True)
    assert body["conditional"]["applied_to"]["mu_as_views"] == 1


def test_all_carried_views_are_counted(client, monkeypatch):
    """★짝★ 항상 줄여 세는 구현을 배제한다."""
    monkeypatch.setattr(
        "src.api.allocation_pipeline._conditional_stack",
        lambda req, returns: _cond_stack([_view(TICKERS[0]), _view(TICKERS[1])]))
    body = _post(client, conditional=True)
    assert body["conditional"]["applied_to"]["mu_as_views"] == 2


# ══════════════════════════════════════════════════════════════════════════
# E13 ★하네스가 그 이유를 스스로 말한다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_control_harness_reports_the_self_referential_benefit():
    """S6 의 "모든 팔이 trade" 를 리포트가 스스로 설명해야 한다."""
    from scripts.company_view_control import run

    rng = np.random.default_rng(3)
    R = rng.normal(0.0004, 0.012, size=(300, 3))
    views = [{"assets": [n], "direction": 1 if i % 2 else -1,
              "magnitude_pct": 3.0 + i, "confidence": 20.0 + 10 * i,
              "source": "company_valuation", "is_mock": True}
             for i, n in enumerate(NAMES)]
    rep = run(NAMES, R, views, n_perm=5, seed=1)

    assert rep["benefit_self_referential"] is True
    assert rep["benefit_note"]
    for arm in rep["arms"].values():
        assert arm["decision"]["self_referential"] is True
