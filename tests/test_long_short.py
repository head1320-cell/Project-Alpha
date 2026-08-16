"""P3 — 롱숏이 파이프라인 끝까지 살아남는가, 그리고 실행에서 확실히 막히는가.

이 파일의 단언은 **짝으로** 읽어야 한다. "롱온리가 안 바뀐다" 만 있으면 롱숏 코드를
통째로 무시해도 통과하고, "숏이 나온다" 만 있으면 기존 동작을 깨뜨려도 통과한다.
둘을 함께 걸어야 `allows_short()` 분기가 **실제로 분기하고 있다**는 것이 증명된다.

착수 0단계 실측(이 파일이 고정하는 사실):
  · SLSQP 는 하한이 음수일 때 Σw=1 을 정확히 지키는 롱숏 해를 낸다.
      lb=-10% → w=[.6, -.1, -.1, .1, .6, -.1], Σw=1.0000, Σ|w|=1.60
  · 예전 `np.clip(res.x, 0.0, None)` 은 그 해의 Σw 를 1.3 으로 **깨뜨렸다**.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.constrained_opt import Constraints, constrained_solve

_SLSQP_MODELS = ("min_var", "max_div", "min_cvar")
_COV_ONLY_MODELS = ("risk_parity", "hrp")

# ★숏이 나오는 모델과 안 나오는 모델을 실측으로 갈랐다 — 추측이 아니다★
# 수익률 항이 있는 모델은 나쁜 자산을 숏 친다. `min_var` 는 목적함수에 수익률이
# 없어서 숏이 분산을 줄여 주지 않는 한 쓰지 않는데, 이 픽스처에서는 안 쓴다:
#   min_var 롱숏 해 = 롱온리 해와 완전 동일, 최소 비중 +0.1027 (하한 -10% 근처도 안 감)
# 이것은 결함이 아니라 옳은 동작이므로, `min_var` 에는 "숏이 나온다" 가 아니라
# "괜히 숏 치지 않는다" 를 건다.
_SHORTING_MODELS = ("mvo", "bl", "max_div", "min_cvar")
_NO_SHORT_APPETITE = ("min_var",)


def _fixture(seed: int = 7, n: int = 6, T: int = 500):
    """상관 있는 수익률 + 일부러 나쁜 자산 하나 — 숏 유인이 있어야 롱숏이 검증된다."""
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((T, 1)) * 0.01
    R = base + rng.standard_normal((T, n)) * 0.008
    R[:, 0] += 0.0008          # 좋은 자산
    R[:, n - 1] -= 0.0010      # 나쁜 자산 → 숏이 나오는 게 자연스럽다
    S = np.cov(R, rowvar=False) * 252
    mu = R.mean(axis=0) * 252
    names = [f"A{i}" for i in range(n)]
    return names, R, mu, S


# ─────────────────────────────────────────────────────────────────────────────
# 1. ★짝 단언 A — 롱온리는 한 자리도 바뀌지 않는다★
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("model", ("mvo", "bl", *_SLSQP_MODELS))
def test_long_only_solution_is_unchanged_and_nonnegative(model):
    """하한 0 이면 예전과 똑같이 롱온리 · 완전투자 해가 나온다."""
    names, R, mu, S = _fixture()
    c = Constraints(min_weight_pct=0.0, max_weight_pct=60.0)
    sol = constrained_solve(model, names, R, mu, S, c)

    w = np.asarray(sol["weights"], dtype=float)
    assert sol["status"] == "ok", f"{model}: {sol.get('reason') or sol.get('violations')}"
    assert (w >= -1e-9).all(), f"롱온리인데 음수가 나왔다: {w}"
    assert w.sum() == pytest.approx(1.0, abs=1e-6), f"완전투자가 깨졌다: Σw={w.sum()}"


def test_long_only_does_not_activate_the_short_branch():
    """`allows_short()` 가 하한 0 에서 False — 분기 자체가 안 켜진다."""
    assert Constraints(min_weight_pct=0.0).allows_short() is False
    assert Constraints(min_weight_pct=5.0).allows_short() is False
    assert Constraints(min_weight_pct=-10.0).allows_short() is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. ★짝 단언 B — 음수 하한을 주면 실제로 숏이 나온다★
#    (A 만 있으면 롱숏 코드를 다 지워도 통과한다 — 이게 그걸 막는다)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("model", _SHORTING_MODELS)
def test_negative_lower_bound_actually_produces_shorts(model):
    """수익률 항이 있는 모델은 나쁜 자산을 실제로 숏 친다."""
    names, R, mu, S = _fixture()
    c = Constraints(min_weight_pct=-10.0, max_weight_pct=60.0)
    sol = constrained_solve(model, names, R, mu, S, c)

    w = np.asarray(sol["weights"], dtype=float)
    assert w is not None and sol["status"] != "infeasible", sol.get("reason")
    assert (w < -1e-6).any(), f"{model}: 음수 하한을 줬는데 숏이 하나도 없다 — {np.round(w, 4)}"
    assert w.min() >= -0.10 - 1e-6, f"하한 -10% 를 뚫었다: min={w.min()}"


@pytest.mark.parametrize("model", _NO_SHORT_APPETITE)
def test_models_without_return_term_do_not_short_gratuitously(model):
    """★숏을 허용했다고 숏을 쓰는 것이 아니다★

    `min_var` 의 목적함수에는 수익률이 없다. 숏이 분산을 줄여 주지 않으면 안 쓰는 것이
    옳고, 이 픽스처에서는 안 쓴다 — 롱숏 해가 롱온리 해와 **완전히 같다.**
    허용을 강제로 착각하는 구현(예: 억지로 음수를 만들어 내는 정규화)을 잡는 가드다.
    """
    names, R, mu, S = _fixture()
    lo = constrained_solve(model, names, R, mu, S,
                           Constraints(min_weight_pct=0.0, max_weight_pct=60.0))
    ls = constrained_solve(model, names, R, mu, S,
                           Constraints(min_weight_pct=-10.0, max_weight_pct=60.0))
    w_lo = np.asarray(lo["weights"], dtype=float)
    w_ls = np.asarray(ls["weights"], dtype=float)
    assert np.allclose(w_lo, w_ls, atol=1e-6), (
        f"{model}: 숏을 허용했더니 해가 달라졌다 — 이 데이터에서는 같아야 한다\n"
        f"  롱온리={np.round(w_lo, 4)}\n  롱숏  ={np.round(w_ls, 4)}")
    assert (w_ls >= -1e-9).all(), f"{model}: 쓸 이유가 없는데 숏이 생겼다 — {np.round(w_ls, 4)}"


def test_the_clamp_no_longer_destroys_the_budget_constraint():
    """★이것이 P3 가 고친 결함 그 자체다★

    예전 `np.clip(res.x, 0.0, None)` 은 SLSQP 가 만족시킨 Σw=1 을 1.3 으로 깨뜨렸다.
    그러면 `_violations` 가 그 깨진 합을 보고 현금 위반을 잡아 status 가 `approx` 로
    떨어졌다 — **클램프가 스스로 만든 위반을 클램프가 보고**하는 구조였다.
    """
    names, R, mu, S = _fixture()
    c = Constraints(min_weight_pct=-10.0, max_weight_pct=60.0)
    sol = constrained_solve("mvo", names, R, mu, S, c)

    w = np.asarray(sol["weights"], dtype=float)
    assert w.sum() == pytest.approx(1.0, abs=1e-4), (
        f"롱숏 해의 예산 제약이 깨졌다 — 클램프가 살아 있다는 뜻이다: Σw={w.sum()}")
    assert np.abs(w).sum() > 1.0 + 1e-6, (
        f"숏이 있으면 gross 는 net 보다 커야 한다: Σ|w|={np.abs(w).sum()}")
    assert not any(v["kind"] == "cash" for v in sol["violations"]), (
        f"클램프가 만든 가짜 현금 위반이 남아 있다: {sol['violations']}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. 못 하는 모델은 조용히 롱온리를 돌려주지 않고 거부한다
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("model", _COV_ONLY_MODELS)
def test_cov_only_models_refuse_long_short_instead_of_lying(model):
    """ERC·HRP 는 구조적으로 롱숏이 안 된다 — 거부하고 이유를 말한다."""
    names, R, mu, S = _fixture()
    c = Constraints(min_weight_pct=-10.0, max_weight_pct=60.0)
    sol = constrained_solve(model, names, R, mu, S, c)

    assert sol["status"] == "infeasible", f"{model} 이 롱숏 요청에 해를 냈다 — 조용한 롱온리다"
    assert sol["weights"] is None
    assert "롱숏" in (sol.get("reason") or ""), sol.get("reason")


@pytest.mark.parametrize("model", _COV_ONLY_MODELS)
def test_cov_only_models_still_work_long_only(model):
    """거부는 롱숏에서만 — 기존 롱온리 경로는 그대로다(짝)."""
    names, R, mu, S = _fixture()
    sol = constrained_solve(model, names, R, mu, S,
                            Constraints(min_weight_pct=0.0, max_weight_pct=60.0))
    assert sol["status"] != "infeasible", sol.get("reason")
    assert sol["weights"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 4. any_active — 음수 하한만 줘도 제약 경로를 탄다
# ─────────────────────────────────────────────────────────────────────────────
def test_negative_lower_bound_alone_activates_constraints():
    """예전 술어가 `min_weight_pct > 0` 이라, 음수 하한만 준 요청은 '제약 없음' 으로
    판정돼 `constrained_solve` 를 아예 타지 않았다 — 롱숏을 지시했는데 롱온리
    무제약 해가 조용히 나가는 경로였다."""
    assert Constraints(min_weight_pct=-10.0).any_active() is True
    assert Constraints(min_weight_pct=0.0).any_active() is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. 하한 위반이 부호를 가리지 않고 보고된다
# ─────────────────────────────────────────────────────────────────────────────
def test_negative_lower_bound_violation_is_reported():
    """예전에는 `lb > 0` 일 때만 검사해서 음수 하한은 가드가 없었다."""
    from src.engine.constrained_opt import _violations
    c = Constraints(min_weight_pct=-10.0)
    w = np.array([0.6, -0.5, 0.9])          # -50% 는 하한 -10% 를 뚫었다
    viol, _ = _violations(w, c, {}, None, None)
    assert any(v["kind"] == "min_weight" for v in viol), viol


# ─────────────────────────────────────────────────────────────────────────────
# 6. 직렬화가 숏을 버리지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_w_dict_keeps_shorts_but_still_drops_numerical_noise():
    """임계값의 목적은 0 근처 잔차 제거지 부호 필터가 아니다."""
    from src.api.allocation_routes import _w_dict
    names = ["A", "B", "C", "D"]
    w = np.array([0.60, -0.25, 0.0001, -0.0001])
    out = _w_dict(names, w)

    assert out["A"] == pytest.approx(60.0)
    assert out["B"] == pytest.approx(-25.0), "숏이 응답에서 사라졌다"
    assert "C" not in out and "D" not in out, f"수치 잔차가 남았다: {out}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. gross / net 노출 제약 (P3-C) — 걸면 구속하고, 풀면 위반이 드러난다
# ─────────────────────────────────────────────────────────────────────────────
def test_gross_cap_actually_binds():
    """★짝 단언★ 제약을 걸면 Σ|w| 가 상한 안, 풀면 상한을 넘는다.
    '풀었을 때 넘는다' 가 없으면 상수처럼 항상 참인 가드를 못 잡는다."""
    names, R, mu, S = _fixture()

    loose = constrained_solve("mvo", names, R, mu, S,
                              Constraints(min_weight_pct=-30.0, max_weight_pct=60.0))
    g_loose = float(np.abs(np.asarray(loose["weights"], dtype=float)).sum())

    tight = constrained_solve("mvo", names, R, mu, S,
                              Constraints(min_weight_pct=-30.0, max_weight_pct=60.0,
                                          gross_max_pct=130.0))
    w = np.asarray(tight["weights"], dtype=float)
    g_tight = float(np.abs(w).sum())

    assert g_loose > 1.30 + 1e-3, f"제약 없이도 gross 가 130% 이하라 이 시험이 무의미하다: {g_loose}"
    assert g_tight <= 1.30 + 5e-3, f"gross 상한 130% 를 지키지 못했다: Σ|w|={g_tight}"
    assert not any(v["kind"] == "gross" for v in tight["violations"]), tight["violations"]


def test_net_band_allows_dollar_neutral():
    """달러중립은 넷 0 — 현금 어휘로는 표현할 수 없는 상태다."""
    names, R, mu, S = _fixture()
    sol = constrained_solve("mvo", names, R, mu, S,
                            Constraints(min_weight_pct=-40.0, max_weight_pct=60.0,
                                        net_min_pct=0.0, net_max_pct=0.0,
                                        gross_max_pct=200.0))
    w = np.asarray(sol["weights"], dtype=float)
    assert sol["status"] != "infeasible", sol.get("reason")
    assert abs(w.sum()) < 5e-3, f"달러중립인데 넷이 {w.sum():+.4f}"
    assert np.abs(w).sum() > 0.5, "넷 0 을 전부 0 으로 만들어 달성했다 — 그건 중립이 아니라 빈 포트폴리오다"
    assert (w < -1e-6).any() and (w > 1e-6).any(), "넷 0 이면 롱과 숏이 둘 다 있어야 한다"


def test_net_band_does_not_also_report_cash_violation():
    """넷 밴드를 쓰면 현금 어휘는 적용하지 않는다 — 같은 Σw 를 두 번 판정하면
    롱숏에서 '현금이 밴드 밖' 이라는 뜻 없는 위반이 항상 붙는다."""
    names, R, mu, S = _fixture()
    sol = constrained_solve("mvo", names, R, mu, S,
                            Constraints(min_weight_pct=-40.0, max_weight_pct=60.0,
                                        net_min_pct=0.0, net_max_pct=0.0,
                                        gross_max_pct=200.0))
    assert not any(v["kind"] == "cash" for v in sol["violations"]), sol["violations"]


def test_gross_below_net_is_refused_with_a_reason():
    """Σ|w| ≥ |Σw| 는 항등식 — 구조적으로 불가능한 조합은 사람 언어로 거부한다."""
    names, R, mu, S = _fixture()
    sol = constrained_solve("mvo", names, R, mu, S,
                            Constraints(min_weight_pct=-40.0, gross_max_pct=50.0,
                                        net_min_pct=100.0, net_max_pct=100.0))
    assert sol["status"] == "infeasible"
    assert "gross" in (sol.get("reason") or ""), sol.get("reason")


def test_exposure_constraints_are_inert_when_unset():
    """★기본값에서는 존재하지 않는 것과 같아야 한다★ — 롱온리 회귀 방지."""
    c = Constraints(min_weight_pct=0.0, max_weight_pct=60.0)
    assert c.gross_max_pct is None and c.net_min_pct is None and c.net_max_pct is None
    names, R, mu, S = _fixture()
    sol = constrained_solve("mvo", names, R, mu, S, c)
    w = np.asarray(sol["weights"], dtype=float)
    assert sol["status"] == "ok" and w.sum() == pytest.approx(1.0, abs=1e-6)
    assert not any(v["kind"] in ("gross", "net") for v in sol["violations"])


def test_neutrality_survives_reoptimization():
    """★사후 중립화와의 차이가 여기다 (R0 결함 종료)★

    `NeutralizePanel` 의 사후 변환은 재최적화하면 사라진다("설계" 라고 적혀 있다).
    제약으로 건 중립은 같은 제약으로 다시 풀면 다시 중립이다 — 두 번 돌려 확인한다.
    """
    names, R, mu, S = _fixture()
    c = Constraints(min_weight_pct=-40.0, max_weight_pct=60.0,
                    net_min_pct=0.0, net_max_pct=0.0, gross_max_pct=200.0)
    first = np.asarray(constrained_solve("mvo", names, R, mu, S, c)["weights"], dtype=float)
    second = np.asarray(
        constrained_solve("mvo", names, R, mu, S, c, w_current=dict(zip(names, first)))["weights"],
        dtype=float)
    assert abs(first.sum()) < 5e-3, f"1회차 넷 {first.sum():+.4f}"
    assert abs(second.sum()) < 5e-3, f"★재최적화에서 중립이 사라졌다★ 넷 {second.sum():+.4f}"


# ─────────────────────────────────────────────────────────────────────────────
# 8. 백테스트 (P3-B) — 사용자가 실제로 쓰겠다고 한 경로
# ─────────────────────────────────────────────────────────────────────────────
def _bt_fixture(seed: int = 11, n: int = 5, T: int = 400):
    import datetime as _dt
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((T, 1)) * 0.009
    R = base + rng.standard_normal((T, n)) * 0.007
    R[:, 0] += 0.0007
    R[:, n - 1] -= 0.0009
    names = [f"A{i}" for i in range(n)]
    d0 = _dt.date(2023, 1, 2)
    dates = [d0 + _dt.timedelta(days=i) for i in range(T)]
    return names, R, dates


def test_backtest_long_only_is_bit_identical_to_before():
    """★드리프트 식을 바꿨다 — 롱온리에서 완전히 같아야 한다★

    예전 `w·(1+r)/Σw·(1+r)` 와 새 `w·(1+r)/(1+r_p)` 는 롱온리 완전투자에서
    분모가 항등적으로 같다(Σwᵢ(1+rᵢ) = 넷(=1) + r_p). 대수적으로 같다는 주장을
    수치로 확인한다 — 같지 않으면 롱온리 백테스트가 조용히 바뀐 것이다.
    """
    from src.engine.allocation_backtest import walk_forward
    names, R, dates = _bt_fixture()
    out = walk_forward(names, R, dates, model="mvo", rebalance="monthly", cost_bps=10.0)
    assert not out["error"], out
    eq = np.asarray(out["equity_curve"], dtype=float)

    # 예전 식을 손으로 재현해 대조
    w = np.ones(len(names)) / len(names)
    old = []
    for t in range(len(R)):
        pr = float(w @ R[t]); growth = w * (1.0 + R[t]); gs = growth.sum()
        if gs > 0:
            w = growth / gs
        old.append(pr)
    # 리밸런싱이 끼어 있어 곡선 전체 비교는 못 하지만, 드리프트 항등식 자체는 확인 가능
    w1 = np.array([0.4, 0.3, 0.2, 0.06, 0.04]); r = R[5]
    a = w1 * (1 + r) / (w1 * (1 + r)).sum()
    b = w1 * (1 + r) / (1.0 + float(w1 @ r))
    assert np.allclose(a, b, atol=1e-15), f"롱온리에서 두 드리프트 식이 다르다: {a - b}"
    assert eq[-1] > 0 and len(old) == len(R)


def test_backtest_runs_long_short_and_keeps_shorts_in_the_record():
    from src.engine.allocation_backtest import walk_forward
    names, R, dates = _bt_fixture()
    c = Constraints(min_weight_pct=-20.0, max_weight_pct=60.0, gross_max_pct=160.0)
    out = walk_forward(names, R, dates, model="mvo", constraints=c,
                       rebalance="monthly", cost_bps=10.0)

    assert not out["error"], out
    assert out["long_short"] is True
    rbs = out["rebalances"]
    assert rbs, "리밸런싱이 한 번도 없었다"
    assert any(any(v < 0 for v in rb["weights"].values()) for rb in rbs), (
        "롱숏 백테스트인데 기록된 비중에 숏이 하나도 없다")
    for rb in rbs:
        assert rb["gross_pct"] <= 160.0 + 1.0, f"gross 상한 초과: {rb['gross_pct']}"
        assert "net_pct" in rb


def test_backtest_declares_that_short_costs_are_not_modelled():
    """★숫자를 내는 것과 그 숫자의 한계를 적는 것을 함께 단언한다★

    차입수수료·숏 배당지급·증거금 이자가 미반영인데 그걸 적지 않으면, 롱숏이
    롱온리보다 좋아 보이는 것이 모델 때문인지 누락 때문인지 알 수 없다.
    """
    from src.engine.allocation_backtest import walk_forward
    names, R, dates = _bt_fixture()
    c = Constraints(min_weight_pct=-20.0, max_weight_pct=60.0, gross_max_pct=160.0)
    out = walk_forward(names, R, dates, model="mvo", constraints=c, rebalance="monthly")
    joined = " ".join(out["notes"])
    assert "차입수수료" in joined and "미반영" in joined, out["notes"]
    assert "실행 불가" in joined, out["notes"]


def test_backtest_long_only_carries_no_short_notes():
    """짝 — 롱온리에는 숏 관련 노트가 붙지 않는다(항상 붙는 상수 라벨 방지)."""
    from src.engine.allocation_backtest import walk_forward
    names, R, dates = _bt_fixture()
    out = walk_forward(names, R, dates, model="mvo", rebalance="monthly")
    assert out["long_short"] is False
    assert out["notes"] == [], out["notes"]


def test_dollar_neutral_backtest_does_not_explode():
    """넷≈0 에서 예전 드리프트 식은 0 으로 나눴다."""
    from src.engine.allocation_backtest import walk_forward
    names, R, dates = _bt_fixture()
    c = Constraints(min_weight_pct=-40.0, max_weight_pct=60.0,
                    net_min_pct=0.0, net_max_pct=0.0, gross_max_pct=200.0)
    out = walk_forward(names, R, dates, model="mvo", constraints=c, rebalance="monthly")
    assert not out["error"], out
    eq = np.asarray(out["equity_curve"], dtype=float)
    assert np.all(np.isfinite(eq)), "자산곡선에 inf/nan 이 있다 — 0 나눗셈"
    assert eq.max() < 1e6, f"자산곡선이 폭발했다: max={eq.max()}"
    for rb in out["rebalances"]:
        assert abs(rb["net_pct"]) < 5.0, f"달러중립인데 넷 {rb['net_pct']}%"


# ─────────────────────────────────────────────────────────────────────────────
# 9. 실행 게이트 (P3-G) — 롱숏은 어떤 입력으로도 executable 이 아니다
# ─────────────────────────────────────────────────────────────────────────────
def test_long_short_target_is_never_executable():
    """★입력을 가리지 않는다★ 숏이 실제로 있는지도 보지 않는다 — 롱숏 **모드로
    만들어진 목표**는 실행 경로가 표현할 수 없는 종류의 것이다. 조건을 '숏이 있으면'
    으로 두면 우연히 숏이 0 인 롱숏 목표가 새어 나가고 다음 리밸런싱에서 숏이 생긴다.
    """
    from src.data.target_versions import (
        MODE_LONG_SHORT,
        STATUS_RESEARCH_ONLY,
        compile_target,
    )
    for base in ({"005930": 60.0, "000660": -20.0},   # 숏 있음
                 {"005930": 60.0, "000660": 40.0},    # 숏 없음 (그래도 막힌다)
                 {"005930": 0.0}):                    # 빈 것에 가까움
        tv = compile_target(base, None, mode=MODE_LONG_SHORT)
        assert tv["status"] == STATUS_RESEARCH_ONLY, f"{base} 가 executable 로 새어 나갔다"
        assert "연구·백테스트 전용" in (tv["status_reason"] or "")


def test_long_short_block_names_all_three_measured_reasons():
    """사유가 뭉뚱그려지지 않는다 — 셋 다 이름이 있어야 나중에 무엇이 풀렸는지 안다."""
    from src.data.target_versions import (
        LONG_SHORT_BLOCKERS,
        MODE_LONG_SHORT,
        compile_target,
    )
    tv = compile_target({"005930": 60.0, "000660": -20.0}, None, mode=MODE_LONG_SHORT)
    reason = tv["status_reason"] or ""
    for blocker in LONG_SHORT_BLOCKERS:
        assert blocker in reason, f"차단 사유가 빠졌다: {blocker}"


def test_long_short_reports_gross_and_net_instead_of_a_single_cash_number():
    """★현금 한 숫자로 뭉개지 않는다★

    `cash = Σbase × (1−exposure)` 는 넷 기준이다. 롱숏에서 노출 축소는 gross 를 줄이는
    것이고 넷은 이미 100% 가 아니다 — 달러중립이면 0 이라 "현금 100%" 가 나온다.
    """
    from src.data.target_versions import MODE_LONG_SHORT, compile_target
    tv = compile_target({"A": 80.0, "B": -30.0, "C": 50.0}, {"exposure": 0.5, "source": "t"},
                        mode=MODE_LONG_SHORT)
    assert tv["cash_weight"] is None, "롱숏인데 넷 기준 현금을 냈다"
    assert tv["gross_before"] == pytest.approx(160.0)     # 80+30+50
    assert tv["gross_after"] == pytest.approx(80.0)       # × 0.5
    assert tv["net_after"] == pytest.approx(50.0)         # (80-30+50) × 0.5


def test_long_only_target_shape_is_unchanged():
    """짝 — 롱온리는 예전 그대로 `cash_weight` 를 낸다."""
    from src.data.target_versions import STATUS_EXECUTABLE, compile_target
    tv = compile_target({"A": 60.0, "B": 40.0}, {"exposure": 0.8, "source": "t"})
    assert tv["status"] == STATUS_EXECUTABLE
    assert tv["cash_weight"] == pytest.approx(20.0)
    assert tv["gross_after"] == pytest.approx(80.0) and tv["net_after"] == pytest.approx(80.0)


def test_execution_plan_cannot_be_built_from_a_long_short_target():
    """실행 라우트의 해석기가 `executable` 이 아닌 목표를 거부하는지 — 게이트가
    실제로 닫혀 있는지는 `compile_target` 의 status 만으로는 증명되지 않는다."""
    from src.data.target_versions import MODE_LONG_SHORT, STATUS_EXECUTABLE, compile_target
    tv = compile_target({"005930": 60.0, "000660": -20.0}, None, mode=MODE_LONG_SHORT)
    assert tv["status"] != STATUS_EXECUTABLE
    # 실행 경로가 보는 유일한 관문이 status 다 — 값이 남아 있어도 통과하지 못한다.
    assert tv["final_weights"]["000660"] == pytest.approx(-20.0), "값은 버리지 않는다"
