"""EP 를 μ 엔진으로 (M2-A)
==============================================================================
M1-T 가 `entropy_pooling.py` 를 지었지만 배분 경로 소비자는 **0건**이었다. 이 파일이
지키는 것은 셋이다 —

  1. **`ep` 는 추가이지 변경이 아니다** — 기존 7개 모델의 출력이 한 자리도 안 바뀐다.
  2. **뷰의 단위가 연간이다** — 이 파일에서 가장 틀리기 쉬운 곳이고, 틀려도 화면에는
     "EP 가 사전분포를 돌려줬다" 로 보여 동작하는 것처럼 읽힌다.
  3. **실현 불가를 성공으로 위장하지 않는다** — 모순된 뷰로는 배분하지 않는다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.allocation_studio import MODELS, optimize, weights_for_model
from src.engine.entropy_views import (
    TRADING_DAYS,
    EPUnavailable,
    ep_mu_or_raise,
    ep_posterior_mu,
)

NAMES = ["005930", "000660", "035420", "051910", "005380", "068270"]


def _returns() -> np.ndarray:
    """M2 실행 0단계 스냅샷과 **같은 시드·같은 모양**. 골든값이 여기에 매여 있다."""
    rng = np.random.default_rng(20260815)
    n_days, n = 756, len(NAMES)
    drift = np.linspace(-0.0002, 0.0004, n)
    vol = np.linspace(0.010, 0.022, n)
    return drift + rng.normal(0, 1, (n_days, n)) * vol


def _view(assets, direction, pct, conf=60):
    return {"assets": list(assets), "direction": direction,
            "magnitude_pct": pct, "confidence": conf}


# ── 1. ★`ep` 는 추가이지 변경이 아니다★ ─────────────────────────────────────

# 실행 0단계에서 **`"ep"` 를 넣기 전에** 뜬 스냅샷의 값. 이 숫자들이 바뀌면 EP 추가가
# 기존 엔진을 건드린 것이고, 그건 이 단계가 명시적으로 금지한 일이다.
GOLDEN = {
    ("mvo", None): [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    ("min_var", None): [0.3102944, 0.2302403, 0.15510722, 0.13094289, 0.08132342, 0.09209177],
    ("hrp", None): [0.31481228, 0.2327401, 0.1642935, 0.11879158, 0.09562879, 0.07373375],
}


@pytest.mark.parametrize("model", ["mvo", "min_var", "hrp"])
def test_existing_models_are_byte_for_byte_unchanged(model):
    got = optimize(model, list(NAMES), _returns(), views=None)["weights"]
    assert np.allclose(got, GOLDEN[(model, None)], atol=1e-7), (
        f"{model} 의 출력이 바뀌었다 — EP 추가가 기존 엔진을 건드렸다")


def test_bl_with_views_is_unchanged():
    """BL 은 뷰를 먹는 유일한 기존 엔진이라 EP 와 가장 충돌하기 쉽다."""
    got = optimize("bl", list(NAMES), _returns(),
                   views=[_view(["005930"], 1, 10.0), _view(["051910", "068270"], -1, 5.0, 40)],
                   )["weights"]
    assert np.allclose(
        got, [0.63538131, 0.10882046, 0.10882183, 0.01907648, 0.1088229, 0.01907702],
        atol=1e-7)


@pytest.mark.parametrize("model", [m for m in MODELS if m != "ep"])
def test_no_other_model_is_ever_labelled_ep(model):
    """★라벨을 지어내지 않는다★ EP 가 아닌 엔진은 `ep` 진단을 갖지 않는다."""
    r = optimize(model, list(NAMES), _returns(), views=[_view(["005930"], 1, 10.0)])
    assert r["mu_engine"] in ("mvo", "bl")
    assert r["ep"] is None


def test_cov_only_models_still_route_through_weights_for_model():
    """구조적 핀 — 골든 숫자가 아니라 **호출 경로**가 그대로인지 본다.

    ★공분산은 `np.cov` 가 아니라 저장소의 `_cov`(Ledoit-Wolf 축소)다★ 처음에 `np.cov`
    로 썼다가 risk_parity 가 0.5%p 어긋났다 — 제품이 아니라 이 테스트의 결함이었다.
    같은 헬퍼를 쓰지 않으면 "경로가 같은지" 를 재는 것이 아니라 다른 것을 재게 된다.
    """
    from src.engine.risk_allocations import _cov
    R = _returns()
    S = _cov(R) * TRADING_DAYS
    for m in ("risk_parity", "min_var", "max_div", "min_cvar"):
        assert np.allclose(optimize(m, list(NAMES), R)["weights"],
                           weights_for_model(m, R, mu_override=None, S_annual=S))


# ── 2. ★단위가 연간이다★ 이 파일에서 가장 틀리기 쉬운 곳 ────────────────────

def test_an_annual_view_is_satisfied_in_annual_units():
    """연 +10% 뷰 → 사후 기대수익이 **연 10%** 다.

    ★KL 최소화라 '딱 그만큼'이 나온다★ 뷰가 요구하는 것 이상은 바꾸지 않는 것이
    Entropy Pooling 의 정의이므로, 제약이 걸린 자산의 사후 평균은 경계에 붙는다.
    실측 0.1000 — 이 등식이 단위 배선의 직접 증거다.
    """
    rep = ep_posterior_mu([_view(["005930"], 1, 10.0)], list(NAMES), _returns())
    assert rep["available"] and rep["feasible"], rep.get("reason") or rep.get("note")
    assert rep["mu_annual"][0] == pytest.approx(0.10, abs=1e-4)


def test_the_same_view_read_as_daily_would_be_a_different_answer():
    """★짝 단언★ 앞 테스트만 있으면 `×252` 를 빼도 통과할 수 있다.

    일간으로 읽으면 "일 10%" 는 이 표본(일변동 1~2%)에서 도달 불가능한 요구라
    **실현 불가**가 된다. 즉 두 해석은 관측 가능하게 다르고, 앞 테스트가 잰 것은
    우연이 아니다.
    """
    R = _returns()
    picks_daily = -1.0 * R[:, 0]                      # ×252 없이 (=잘못된 해석)
    from src.engine.entropy_pooling import entropy_pool
    n = R.shape[0]
    bad = entropy_pool(np.full(n, 1.0 / n),
                       ineq=(picks_daily.reshape(-1, 1), np.array([-0.10])))
    assert bad["available"] and not bad["feasible"], (
        "일간 해석이 실현 가능하다면 두 단위가 구분되지 않는다 — 짝 단언이 성립하지 않는다")


def test_a_downside_view_is_also_annual_and_signed():
    rep = ep_posterior_mu([_view(["000660"], -1, 8.0)], list(NAMES), _returns())
    assert rep["feasible"], rep.get("note")
    assert rep["mu_annual"][1] == pytest.approx(-0.08, abs=1e-4)


# ── 3. EP 와 BL 이 **같은 뷰**를 먹는다 ─────────────────────────────────────

def test_ep_and_bl_agree_on_direction_for_the_same_view():
    """크기는 달라도 **방향**은 같아야 한다 — 다르면 두 엔진이 같은 뷰를 먹지 않는 것이다.

    (크기가 다른 것은 결함이 아니라 두 엔진을 나란히 두는 이유다: BL 은 confidence 로
    Ω 를 잡아 부분 반영하고, EP 는 경성 제약이라 경계까지 민다.)
    """
    R = _returns()
    v = [_view(["005930"], 1, 10.0)]
    base = optimize("mvo", list(NAMES), R)["weights"]
    bl = optimize("bl", list(NAMES), R, views=v)["weights"]
    ep = optimize("ep", list(NAMES), R, views=v)["weights"]
    i = NAMES.index("005930")
    assert bl[i] > base[i], "BL 이 뷰 방향으로 움직이지 않았다"
    assert ep[i] > base[i], "EP 가 뷰 방향으로 움직이지 않았다"


def test_group_views_work_which_pool_weights_cannot_express():
    """★그룹 뷰★ `entropy_pooling.pool_weights` 는 단일 자산(`asset: int`)만 받는다.

    이 앱의 뷰는 그룹이므로 `entropy_pool` 을 직접 부르고 균등가중 피커를 쓴다.
    그룹 평균이 경계에 붙는지가 그 배선의 증거다.
    """
    R = _returns()
    rep = ep_posterior_mu([_view(["005930", "000660"], 1, 12.0)], list(NAMES), R)
    assert rep["feasible"], rep.get("note")
    grp = (rep["mu_annual"][0] + rep["mu_annual"][1]) / 2.0
    assert grp == pytest.approx(0.12, abs=1e-4)
    assert rep["n_views"] == 1


# ── 4. ★실현 불가를 성공으로 위장하지 않는다★ ──────────────────────────────

def test_contradictory_views_refuse_instead_of_falling_back():
    """같은 자산에 ≥+20% 와 ≤−20% 를 동시에 — 사전분포로 조용히 돌아가지 않는다."""
    with pytest.raises(EPUnavailable) as e:
        ep_mu_or_raise([_view(["005930"], 1, 20.0), _view(["005930"], -1, 20.0)],
                       list(NAMES), _returns())
    assert "동시에 만족" in str(e.value)
    assert e.value.report["violations"], "위반 내역 없이 거부하면 고칠 방법을 알 수 없다"


def test_optimize_ep_propagates_the_refusal_rather_than_returning_weights():
    with pytest.raises(EPUnavailable):
        optimize("ep", list(NAMES), _returns(),
                 views=[_view(["005930"], 1, 20.0), _view(["005930"], -1, 20.0)])


def test_violations_are_reported_in_user_terms_not_transformed_space():
    """★부호가 뒤집힌 숫자를 화면에 내지 않는다★

    `entropy_pool` 의 target/achieved 는 `-d·연율` 변환 공간의 값이다. 그대로 내면
    "+20% 를 요구했는데 −0.2 가 나왔다" 처럼 읽힌다.
    """
    rep = ep_posterior_mu([_view(["005930"], 1, 20.0), _view(["005930"], -1, 20.0)],
                          list(NAMES), _returns())
    v = rep["violations"][0]
    assert set(v) >= {"assets", "requested_pct", "achieved_pct", "gap_pct", "direction"}
    assert v["assets"] == "005930"
    assert abs(v["requested_pct"]) == pytest.approx(20.0, abs=1e-6)


# ── 5. 뷰가 없는 것은 실패가 아니다 · confidence 는 쓰지 않는다 ─────────────

def test_no_views_means_posterior_equals_prior_and_that_is_correct():
    R = _returns()
    rep = ep_posterior_mu(None, list(NAMES), R)
    assert rep["available"] and rep["feasible"] and rep["n_views"] == 0
    assert np.allclose(rep["mu_annual"], R.mean(axis=0) * TRADING_DAYS)
    assert np.allclose(optimize("ep", list(NAMES), R)["weights"],
                       optimize("mvo", list(NAMES), R)["weights"])


def test_confidence_is_not_used_and_the_report_says_so():
    """★매핑을 지어내지 않는다★ 신뢰도만 다른 두 뷰가 EP 에서 같은 답을 낸다.

    그리고 그 사실이 반환에 플래그로 있어야 화면이 "신뢰도가 반영됐다" 고 오해하지 않는다.
    """
    R = _returns()
    lo = ep_posterior_mu([_view(["005930"], 1, 10.0, conf=5)], list(NAMES), R)
    hi = ep_posterior_mu([_view(["005930"], 1, 10.0, conf=95)], list(NAMES), R)
    assert lo["confidence_used"] is False and hi["confidence_used"] is False
    assert np.allclose(lo["mu_annual"], hi["mu_annual"])


def test_skipped_views_are_reported_not_silently_dropped():
    rep = ep_posterior_mu(
        [_view(["999999"], 1, 10.0), _view(["005930"], 1, 0.0), _view(["005930"], 1, 6.0)],
        list(NAMES), _returns())
    assert rep["n_views"] == 1
    assert len(rep["skipped"]) == 2 and all(s["reason"] for s in rep["skipped"])


def test_ens_collapse_is_reported_when_views_overpower_the_prior():
    """유효 시나리오 수가 무너지면 숫자가 멀쩡해도 표본 몇 개에 기댄 상태다."""
    rep = ep_posterior_mu([_view(["005930"], 1, 45.0)], list(NAMES), _returns())
    assert rep["available"]
    assert rep["ens"] < rep["ens_prior"], "뷰가 걸렸는데 ENS 가 줄지 않았다"


def test_the_engine_label_is_stamped_by_the_server():
    R = _returns()
    assert optimize("ep", list(NAMES), R, views=[_view(["005930"], 1, 6.0)])["mu_engine"] == "ep"
    assert optimize("bl", list(NAMES), R, views=[_view(["005930"], 1, 6.0)])["mu_engine"] == "bl"
    assert optimize("mvo", list(NAMES), R)["mu_engine"] == "mvo"
