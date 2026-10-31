"""T3 아키텍처 팔 계약 — ★EP 를 BL 처럼 읽지 않고, D 에 IC 0 을 적지 않는다★
==============================================================================
계획: 아키텍처 정의 패스. 대상은 `scripts/t3_transmission.py` 의 연구 팔이다.

이 파일이 막는 회귀는 셋이다:

1. ★두 엔진이 다른 P 행을 보는 것★ — BL 은 `pq_from_views`, EP 는
   `entropy_views._pickers` 로 들어가는데 **둘 다** `build_view_rows` 를 타야 한다.
   한쪽만 갈라지면 "같은 뷰인데 결과가 다르다" 가 되고, 그 원인은 두 응답을
   나란히 놓기 전에는 보이지 않는다.

2. ★EP 를 BL 처럼 읽는 것★ — BL 은 언제나 Q 쪽으로 섞지만 **EP 는 부등식**이다.
   이미 만족돼 있으면 **아무것도 하지 않고**, 위반일 때만 **경계까지** 당긴다.
   둘 중 한쪽만 테스트하면 "입력을 무시하는 EP" 가 통과한다 — 그래서 짝이다.

3. ★T3-D 에 예측 스킬 수치를 적는 것★ — D 는 기대수익 뷰를 만들지 않는다.
   IC 를 0 으로 적으면 "예측했는데 못 맞췄다" 로 읽힌다. `undefined` 여야 한다.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_studio import (  # noqa: E402
    DELTA_DEFAULT,
    TAU_DEFAULT,
    bl_posterior,
)
from src.engine.constrained_opt import Constraints, constrained_solve  # noqa: E402
from src.engine.entropy_views import _pickers, ep_posterior_mu  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _as_vec(weights, names) -> np.ndarray:
    """`constrained_solve` 의 weights → 이름 순 벡터 (dict/배열 양쪽 허용)."""
    if isinstance(weights, dict):
        return np.array([float(weights.get(nm, 0.0)) for nm in names])
    return np.asarray(weights, dtype=float)


def _load_t3():
    """연구 스크립트를 모듈로 적재 — `scripts/` 는 패키지가 아니다.

    ★`sys.modules` 등록이 필수다★ `from __future__ import annotations` 아래의
    `@dataclass` 는 타입을 문자열로 받아 `sys.modules[cls.__module__].__dict__` 를
    되짚는다. 등록하지 않으면 `AttributeError: 'NoneType' object has no attribute
    '__dict__'` 로 **적재 자체가 실패한다**(실제로 겪었다).
    """
    spec = importlib.util.spec_from_file_location(
        "t3_transmission", _ROOT / "scripts" / "t3_transmission.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


t3 = _load_t3()


@pytest.fixture(scope="module")
def panel():
    names, R, dates, points, beta = t3.build_panel(months=36)
    win = R[:504]
    return {"names": names, "R": R, "dates": dates, "points": points,
            "beta": beta, "win": win,
            "sigma": np.cov(win.T) * 252.0,
            "mu": win.mean(axis=0) * 252.0}


# ══════════════════════════════════════════════════════════════════════════
# 1) 두 엔진이 같은 행을 본다
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("arch", ["T3-A", "T3-B", "T3-C", "T3-C-rel"])
def test_ep_and_bl_see_the_same_p_row(panel, arch):
    """★핵심 가드★ 같은 뷰 → BL 경로의 P 와 EP 경로의 피커행이 **원소별 동일**."""
    views = t3._VIEWS[arch](panel["mu"], panel["names"], panel["beta"])
    P, _Q, _Om, _sk = t3.pq_from_views(views, panel["names"], panel["sigma"],
                                       25.0, TAU_DEFAULT)
    picks, _skipped = _pickers(views, panel["names"])
    assert P.shape[0] == len(picks)
    for i, (row, _d, _mag, _lab) in enumerate(picks):
        np.testing.assert_allclose(P[i], row, atol=0, rtol=0)


def test_q_carries_the_sign_and_the_row_does_not_double_it(panel):
    """★부호를 한 곳에만 넣는다★ 가중치와 direction 양쪽에 넣으면 상쇄된다."""
    views = t3.views_relative_class(panel["mu"], panel["names"], panel["beta"])
    P, Q, _Om, _sk = t3.pq_from_views(views, panel["names"], panel["sigma"],
                                      25.0, TAU_DEFAULT)
    raw = float(P[0] @ panel["mu"])
    assert Q[0] == pytest.approx(raw, abs=1e-12)


# ══════════════════════════════════════════════════════════════════════════
# 2) ★EP 는 부등식이다★ — 만족/위반 짝
# ══════════════════════════════════════════════════════════════════════════
def _scenarios():
    """EQ 가 FI 보다 확실히 잘 나오는 작은 시나리오 집합 (일간)."""
    # ★표본오차를 이기게 만든다★ 600일·일간σ 1% 면 연율 평균의 SE 가 10%p 라
    # 사전 스프레드의 **부호조차** 표본에 좌우된다(첫 픽스처가 그래서 −1.2% 였다).
    rng = np.random.default_rng(7)
    n = 4000
    R = np.column_stack([
        rng.normal(0.0012, 0.008, n),      # EQ0
        rng.normal(0.0011, 0.009, n),      # EQ1
        rng.normal(0.0001, 0.003, n),      # FI0
        rng.normal(0.0000, 0.003, n),      # FI1
    ])
    return ["EQ0", "EQ1", "FI0", "FI1"], R


def _spread_view(mag_pct: float, direction: int = 1) -> dict:
    return {"weights": {"EQ0": 0.5, "EQ1": 0.5, "FI0": -0.5, "FI1": -0.5},
            "direction": direction, "magnitude_pct": mag_pct}


def test_ep_does_nothing_when_the_view_is_already_satisfied():
    """★BL 과 다른 점★ 사전분포가 이미 뷰를 만족하면 EP 는 사후=사전이다."""
    names, R = _scenarios()
    row = np.array([0.5, 0.5, -0.5, -0.5])
    prior_spread = float(row @ (R.mean(axis=0) * 252.0))
    assert prior_spread > 0.05, "픽스처 전제: 사전 스프레드가 충분히 크다"

    rep = ep_posterior_mu([_spread_view(1.0)], names, R)   # 요구 1% ≪ 사전
    assert rep["available"] and rep["feasible"]
    assert rep["kl"] == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(rep["mu_annual"], rep["prior_mu_annual"], atol=1e-12)


def test_ep_pulls_only_to_the_boundary_when_violated():
    """★짝★ 위반일 때만 움직이고, **딱 경계까지만** 당긴다(그 이상 가지 않는다)."""
    names, R = _scenarios()
    row = np.array([0.5, 0.5, -0.5, -0.5])
    prior_spread = float(row @ (R.mean(axis=0) * 252.0))
    target = prior_spread + 0.05                      # 사전보다 더 강하게 요구

    rep = ep_posterior_mu([_spread_view(target * 100.0)], names, R)
    assert rep["available"] and rep["feasible"]
    assert rep["kl"] > 1e-9, "위반인데 사후가 움직이지 않았다"
    post = float(row @ np.asarray(rep["mu_annual"], float))
    assert post == pytest.approx(target, abs=5e-3), \
        "경계를 넘어 과도하게 당겼거나 못 미쳤다"


def test_ep_accepts_the_reverse_sign_too():
    """부호를 절댓값으로 뭉개면 이 테스트가 죽는다."""
    names, R = _scenarios()
    row = np.array([0.5, 0.5, -0.5, -0.5])
    rep = ep_posterior_mu([_spread_view(5.0, direction=-1)], names, R)
    assert rep["available"] and rep["feasible"]
    post = float(row @ np.asarray(rep["mu_annual"], float))
    assert post <= -0.05 + 5e-3, "음의 방향 뷰가 반영되지 않았다"


def test_view_builders_carry_a_negative_direction(panel):
    """★생성기가 부호를 만든다★

    앞선 `direction=-1` 테스트는 딕셔너리를 **손으로** 만들어서, `_signed_view` 가
    부호를 버리는 변이(`direction: 1` 고정)가 살아남았다. 여기서는 생성기에게
    음의 스프레드를 주고 그 부호가 나오는지 본다.
    """
    names, beta = panel["names"], panel["beta"]
    mu_down = np.array([-0.10, -0.10, -0.10, +0.08, +0.08, +0.08])   # FI 우위
    v = t3.views_relative_class(mu_down, names, beta)[0]
    assert v["direction"] == -1, "EQ−FI 가 음인데 방향이 +1 이다"
    assert v["magnitude_pct"] > 0.0

    v_up = t3.views_relative_class(-mu_down, names, beta)[0]
    assert v_up["direction"] == 1                                   # 짝

    a = t3.views_absolute(mu_down, names, beta)
    assert [x["direction"] for x in a] == [-1, -1, -1, 1, 1, 1]

    f = t3.views_factor_relative(mu_down, names, beta)[0]
    assert f["direction"] == -1, "고β 가 저β 보다 못한데 방향이 +1 이다"


def test_direction_and_weights_do_not_double_the_sign(panel):
    """짝 — 부호가 **한 곳에만** 있어야 Q 가 원래 값과 같다(양쪽이면 상쇄된다)."""
    names, beta = panel["names"], panel["beta"]
    mu_down = np.array([-0.10, -0.10, -0.10, +0.08, +0.08, +0.08])
    v = t3.views_relative_class(mu_down, names, beta)
    P, Q, _Om, _sk = t3.pq_from_views(v, names, panel["sigma"], 25.0, TAU_DEFAULT)
    assert Q[0] < 0.0, "부호가 두 번 들어가 상쇄됐다"
    assert Q[0] == pytest.approx(float(P[0] @ mu_down), abs=1e-12)


# ══════════════════════════════════════════════════════════════════════════
# 3) ★팩터 뷰 능력 vs 레버 능력★ — 항목 6 의 직접 답
# ══════════════════════════════════════════════════════════════════════════
def test_level_factor_row_sums_to_one_relative_row_sums_to_zero(panel):
    """두 행이 **구조적으로 다른 주장**임을 수치로 못 박는다."""
    lvl = t3._factor_row_level(panel["beta"])
    rel = t3._factor_row_relative(panel["beta"])
    assert lvl.sum() == pytest.approx(1.0, abs=1e-9)
    assert rel.sum() == pytest.approx(0.0, abs=1e-9)
    assert np.abs(lvl).sum() == pytest.approx(1.0, abs=1e-9)
    assert np.abs(rel).sum() == pytest.approx(1.0, abs=1e-9)   # 같은 노름


def _weights_for(views, panel, conf=25.0):
    S, n = panel["sigma"], len(panel["names"])
    pi = t3._equilibrium(S, np.ones(n) / n, DELTA_DEFAULT)
    P, Q, Om, _sk = t3.pq_from_views(views, panel["names"], S, conf, TAU_DEFAULT)
    post = bl_posterior(pi, S, P, Q, Om, tau=TAU_DEFAULT)
    return t3._min_var_long_only(S, post, DELTA_DEFAULT), pi


def test_relative_factor_row_moves_long_only_weights_more_than_the_level_row(panel):
    """★항목 6★ 롱온리·완전투자(Σw=1)에서 **상대** 팩터 뷰는 표현되고, **수준**
    팩터 뷰는 레버가 없어 훨씬 덜 표현된다.

    ★즉 T3-C 를 막고 있던 것은 '팩터 뷰' 라는 형태가 아니라 '수준 주장' 이다★ —
    그로스 레버는 상대 팩터 뷰의 **전제조건이 아니다**.
    """
    S, n = panel["sigma"], len(panel["names"])
    w0 = t3._min_var_long_only(
        S, t3._equilibrium(S, np.ones(n) / n, DELTA_DEFAULT), DELTA_DEFAULT)
    w_lvl, _ = _weights_for(
        t3.views_factor_level(panel["mu"], panel["names"], panel["beta"]), panel)
    w_rel, _ = _weights_for(
        t3.views_factor_relative(panel["mu"], panel["names"], panel["beta"]), panel)

    move_lvl = float(np.abs(w_lvl - w0).sum())
    move_rel = float(np.abs(w_rel - w0).sum())
    assert move_lvl > 0.0, "수준 뷰가 아예 아무 일도 안 하면 비교가 성립하지 않는다"
    assert move_rel > 2.0 * move_lvl, (
        f"상대 팩터 뷰가 수준 뷰보다 크게 움직이지 않았다: {move_rel:.4f} vs {move_lvl:.4f}")


# ══════════════════════════════════════════════════════════════════════════
# 4) ★T3-D 는 μ 를 읽지 않는다★ — 그리고 국면에는 반응해야 한다(짝)
# ══════════════════════════════════════════════════════════════════════════
def test_risk_budget_and_caps_take_no_mu_argument():
    """구조 가드 — 나중에 μ 를 끌어들이면 D 는 더 이상 D 가 아니다."""
    import inspect
    for fn in (t3.regime_risk_budget, t3.regime_group_caps):
        params = set(inspect.signature(fn).parameters)
        assert "mu" not in params, f"{fn.__name__} 가 μ 를 받는다"


def test_group_cap_path_is_invariant_to_mu(panel):
    """행동 가드 — 서명만으로는 부족하다. μ 를 뒤집어도 D2 비중이 같아야 한다."""
    names, S = panel["names"], panel["sigma"]
    caps = t3.regime_group_caps(S, S * 1.4, names)
    kw = dict(constraints=Constraints(group_caps_pct=caps),
              groups_of=t3.class_of(names))
    a = constrained_solve("min_var", names, panel["win"], panel["mu"], S, **kw)
    b = constrained_solve("min_var", names, panel["win"], -panel["mu"], S, **kw)
    assert a["weights"] is not None and b["weights"] is not None
    np.testing.assert_allclose(_as_vec(a["weights"], names),
                               _as_vec(b["weights"], names), atol=1e-6)


def test_regime_budget_changes_when_the_conditional_covariance_changes(panel):
    """★짝★ μ 를 안 읽는다고 **상수**여도 되는 것은 아니다 — Σ 가 바뀌면 예산도 바뀐다."""
    names, S = panel["names"], panel["sigma"]
    calm = t3.regime_risk_budget(S, names)
    stressed = S.copy()
    eq = [i for i, nm in enumerate(names) if nm.startswith("EQ")]
    stressed[np.ix_(eq, eq)] *= 4.0                 # EQ 만 변동성 급등
    hot = t3.regime_risk_budget(stressed, names)
    eq_calm = float(sum(calm[i] for i in eq))
    eq_hot = float(sum(hot[i] for i in eq))
    assert eq_hot < eq_calm - 1e-6, (
        f"EQ 변동성이 4배인데 EQ 예산이 줄지 않았다: {eq_hot:.4f} vs {eq_calm:.4f}")


def test_flat_budget_is_equal_weight_and_ignores_the_covariance(panel):
    """대조군이 진짜로 국면 정보를 안 쓰는지 — `-flat` 이 Σ 에 반응하면 대조가 아니다."""
    names, S = panel["names"], panel["sigma"]
    flat = t3.regime_risk_budget(S, names, flat=True)
    np.testing.assert_allclose(flat, np.full(len(names), 1.0 / len(names)), atol=1e-12)


def test_group_caps_bind_and_stay_feasible(panel):
    """★한도가 실제로 닿는다★ + 완전투자를 깨지 않는다(상한 합 ≥ 100)."""
    names, S = panel["names"], panel["sigma"]
    stressed = S.copy()
    eq = [i for i, nm in enumerate(names) if nm.startswith("EQ")]
    stressed[np.ix_(eq, eq)] *= 9.0
    caps = t3.regime_group_caps(stressed, S, names)
    assert caps["EQ"] < 100.0, "EQ 변동성이 9배인데 상한이 내려가지 않았다"
    assert sum(caps.values()) >= 100.0 - 1e-9, "상한 합이 100 미만이면 완전투자가 불가능하다"

    res = constrained_solve("min_var", names, panel["win"], np.zeros(len(names)),
                            stressed, Constraints(group_caps_pct=caps),
                            groups_of=t3.class_of(names))
    assert res["weights"] is not None
    w = _as_vec(res["weights"], names)
    eq_sum = 100.0 * float(sum(w[i] for i, nm in enumerate(names)
                               if nm.startswith("EQ")))
    assert eq_sum <= caps["EQ"] + 0.5


def test_open_caps_are_empty(panel):
    """대조군 — 한도 없음이 진짜 비어 있어야 한다."""
    assert t3.regime_group_caps(panel["sigma"], panel["sigma"], panel["names"],
                                open_=True) == {}


def test_cap_floor_never_zeroes_an_asset_class(panel):
    """★국면이 아무리 나빠도 한 자산군을 0 으로 만들지 않는다★"""
    names, S = panel["names"], panel["sigma"]
    catastrophic = S * 1.0
    eq = [i for i, nm in enumerate(names) if nm.startswith("EQ")]
    catastrophic[np.ix_(eq, eq)] *= 10_000.0
    caps = t3.regime_group_caps(catastrophic, S, names)
    # ★리터럴이다★ `t3.CAP_FLOOR` 를 참조하면 상수를 0 으로 바꾸는 변이가 단언까지
    # 같이 바꿔 테스트가 살아남는다(실제로 살아남았다).
    assert caps["EQ"] >= 10.0, f"EQ 상한이 {caps['EQ']:.2f}% 까지 내려갔다"
    assert t3.CAP_FLOOR >= 0.10, "하한 자체가 낮아졌다"


# ══════════════════════════════════════════════════════════════════════════
# 5) ★예측 스킬은 D 에 정의되지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_timing_ic_is_undefined_for_a_budget_arm():
    """0 을 적으면 '예측했는데 못 맞췄다' 로 읽힌다 — 그런 적이 없다."""
    rec = {"uses_mu": False, "timing_view": [], "fwd_factor": []}
    out = t3.timing_ic(rec)
    assert out["undefined"] is True
    assert out["ic"] is None and out["t"] is None
    assert out["reason"]


def test_timing_ic_is_defined_for_a_view_arm():
    """짝 — 가드가 전부를 막아버리지 않게."""
    rng = np.random.default_rng(1)
    v = rng.normal(size=40)
    rec = {"uses_mu": True, "timing_view": list(v),
           "fwd_factor": list(v * 0.5 + rng.normal(0, 0.1, 40))}
    out = t3.timing_ic(rec)
    assert not out.get("undefined")
    assert out["ic"] is not None and out["n"] == 40


# ══════════════════════════════════════════════════════════════════════════
# 6) 하네스 — 무거래를 **건너뛴 날**로 만들지 않는다
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("engine", ["bl", "ep"])
def test_every_rebalance_produces_an_entry(panel, engine):
    """★리밸런싱 수 == 기록 수★

    EP 가 실현 불가일 때 `continue` 로 빠지면 그날 수익이 사라진다(포트폴리오는
    거래를 안 했을 뿐 포지션을 그대로 들고 있다). 기록 길이가 그 회귀를 잡는다.
    """
    rec, rb = t3.run_arch("T3-B", panel["names"], panel["R"], panel["dates"],
                          panel["points"], panel["beta"], conf_override=25.0,
                          engine=engine)
    assert len(rec["w"]) == len(rb)
    assert len(rec["months"]) == len(rb)


def test_ep_infeasible_is_a_no_trade_not_a_dropped_day(panel, monkeypatch):
    """★강제 픽스처★ 이 패널에서 T3-B 는 실현 불가가 한 번도 안 난다 —
    그래서 길이 테스트만으로는 `continue` 변이가 **살아남았다**(실제로 살아남았다).
    EP 를 항상 실현 불가로 만들어 그 분기를 반드시 지나가게 한다.

    무거래는 **직전 비중을 그대로 들고 있는 것**이지 그날이 사라지는 것이 아니다.
    """
    real = t3.ep_posterior_mu

    def always_infeasible(views, names, R):
        rep = real(views, names, R)
        if rep.get("available"):
            rep = dict(rep, feasible=False)
        return rep

    monkeypatch.setattr(t3, "ep_posterior_mu", always_infeasible)
    rec, rb = t3.run_arch("T3-B", panel["names"], panel["R"], panel["dates"],
                          panel["points"], panel["beta"], conf_override=25.0,
                          engine="ep")
    assert rec["ep_infeasible"] > 0, "픽스처가 실현 불가를 만들지 못했다"
    assert len(rec["w"]) == len(rb), "무거래 리밸런싱이 기록에서 사라졌다"
    assert len(rec["months"]) == len(rb)
    # 시뮬레이터가 같은 수의 거래일을 돌려야 한다 — 그날 수익이 사라지지 않는다
    daily, _curve, _tos, _m = t3.simulate(rec, rb, panel["R"], panel["dates"], 0.0)
    assert daily.size == panel["R"].shape[0] - rb[0]


def test_budget_arm_records_every_rebalance(panel):
    rec, rb = t3.run_arch("T3-D1", panel["names"], panel["R"], panel["dates"],
                          panel["points"], panel["beta"])
    assert len(rec["w"]) == len(rb)
    assert rec["uses_mu"] is False


def test_const_arm_freezes_the_budget(panel):
    """`-const` 는 규칙을 끄지 않고 **국면 변동만** 끈다 — 예산이 하나여야 한다."""
    rec, _rb = t3.run_arch("T3-D1-const", panel["names"], panel["R"],
                           panel["dates"], panel["points"], panel["beta"])
    assert len(set(round(b, 12) for b in rec["budget_eq"])) == 1

    rec2, _ = t3.run_arch("T3-D1", panel["names"], panel["R"], panel["dates"],
                          panel["points"], panel["beta"])
    assert len(set(round(b, 12) for b in rec2["budget_eq"])) > 1, \
        "국면 팔의 예산이 상수면 -const 와의 대조가 성립하지 않는다"


# ══════════════════════════════════════════════════════════════════════════
# 7) ★EP 의 회전율에서 "사전이 움직여서 생긴 것" 을 떼어낸다★ (Phase 4)
# ══════════════════════════════════════════════════════════════════════════
def test_prior_only_arm_has_no_views_and_never_moves_the_posterior(panel):
    """뷰가 0개면 EP 사후 = 사전이다 — 이 팔의 **정의**이지 실패가 아니다."""
    rec, rb = t3.run_arch(t3.ARCH_PRIOR_ONLY, panel["names"], panel["R"],
                          panel["dates"], panel["points"], panel["beta"],
                          engine="ep")
    assert t3.views_none(panel["mu"], panel["names"], panel["beta"]) == []
    assert rec["ep_inactive"] == len(rec["ep_kl"]) > 0
    assert rec["ep_infeasible"] == 0
    assert len(rec["w"]) == len(rb)


def test_prior_only_arm_still_trades(panel):
    """★Phase 4 의 핵심★ 뷰가 하나도 없는데 **회전율이 0 이 아니다**.

    EP 에는 BL 의 `Π` 같은 정적 앵커가 없어 사전분포(트레일링 평균)가 매달 움직인다.
    그 회전율이 곧 "뷰와 무관한 거래" 이고, 뷰 팔의 회전율에서 이것을 빼야 뷰가
    실제로 유발한 거래가 나온다. 이 팔이 0 회전율이면 그 분해가 성립하지 않는다.
    """
    rec, rb = t3.run_arch(t3.ARCH_PRIOR_ONLY, panel["names"], panel["R"],
                          panel["dates"], panel["points"], panel["beta"],
                          engine="ep")
    _d, _c, tos, _m = t3.simulate(rec, rb, panel["R"], panel["dates"], 0.0)
    assert tos.size > 1
    assert float(tos.mean()) > 1e-3, "사전만으로는 거래가 없다 — 분해가 성립하지 않는다"


def test_a_view_arm_trades_strictly_more_than_the_prior_alone(panel):
    """★짝★ 뷰가 회전율을 **더한다**는 것 — 아니면 위 테스트가 무의미하다."""
    def turn(arch):
        rec, rb = t3.run_arch(arch, panel["names"], panel["R"], panel["dates"],
                              panel["points"], panel["beta"], conf_override=25.0,
                              engine="ep")
        _d, _c, tos, _m = t3.simulate(rec, rb, panel["R"], panel["dates"], 0.0)
        return float(tos.mean())

    base = turn(t3.ARCH_PRIOR_ONLY)
    with_views = turn("T3-A")
    assert with_views > base + 1e-3, (
        f"뷰를 넣었는데 회전율이 늘지 않았다: {with_views:.4f} vs {base:.4f}")


def test_prior_only_is_ep_only(panel):
    """BL 은 사전이 균형 `Π` 라 '사전이 움직인다' 가 성립하지 않는다 — 팔을 섞지 않는다."""
    assert t3.ARCH_PRIOR_ONLY in t3.ARCH_ALL
    assert t3.ARCH_PRIOR_ONLY not in t3.ARCH_VIEW
    assert t3.ARCH_PRIOR_ONLY not in t3.ARCH_BUDGET


def test_arch_names_resolve(panel):
    assert t3._resolve_arch("D") == list(t3.ARCH_BUDGET)
    assert t3._resolve_arch("ALL") == list(t3.ARCH_ALL)
    assert t3._resolve_arch("T3-B,T3-C-rel") == ["T3-B", "T3-C-rel"]
    with pytest.raises(SystemExit):
        t3._resolve_arch("T3-Z")
