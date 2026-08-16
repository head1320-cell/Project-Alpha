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
