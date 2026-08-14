"""다중 알파 결합 + 중복 진단 (P2-C)
==============================================================================
여기 단언들이 지키는 것은 하나다 — **분산했다고 믿는 배합이 사실은 한 베팅일 때,
화면이 그 사실을 말하게 한다.**
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.alpha_combine import (
    DUP_RHO,
    combine_alphas,
    effective_n_alphas,
    pairwise_rank_corr,
)

TICKERS = [f"{i:06d}" for i in range(1, 41)]


def _loader():
    def loader(tickers, start, end):
        import pandas as pd
        rng = np.random.default_rng(11)
        n_days = 820
        idx = pd.bdate_range("2023-01-02", periods=n_days)
        drifts = np.linspace(-0.0035, 0.0035, len(tickers[:40]))
        out = {}
        for k, t in enumerate(tickers[:40]):
            r = drifts[k] + rng.normal(0, 0.004, n_days)
            c = 10000 * np.cumprod(1 + r)
            out[t] = pd.DataFrame({"close": c, "amount": np.full(n_days, 1e9)}, index=idx)
        return {tk: {"dates": np.array(v.index.values, dtype="datetime64[D]"),
                     "close": v["close"].values, "amount": v["amount"].values}
                for tk, v in out.items()}
    return loader


def _spec(aid, expr, w=1.0):
    return {"alpha_id": aid, "expr": expr, "weight": w}


# ── 1. 상관 계산이 자명한 경우부터 맞는다 ───────────────────────────────────

def test_identical_vectors_have_rho_one_and_effective_n_one():
    """★자명한 경우로 계산을 먼저 고정한다★ 여기서 틀리면 나머지는 볼 필요가 없다."""
    v = np.linspace(0, 1, 20)
    rb = {"a": v, "b": v.copy()}
    pw = pairwise_rank_corr(rb)
    assert len(pw) == 1
    assert pw[0]["rho"] == pytest.approx(1.0)
    assert pw[0]["duplicate"] is True
    assert effective_n_alphas(rb) == pytest.approx(1.0, abs=0.01)


def test_orthogonal_vectors_have_effective_n_near_two():
    rng = np.random.default_rng(3)
    a = rng.normal(size=200)
    b = rng.normal(size=200)
    n_eff = effective_n_alphas({"a": a, "b": b})
    assert n_eff is not None and 1.8 <= n_eff <= 2.0


def test_zero_variance_is_a_reason_not_a_number():
    """★상관을 정의할 수 없으면 0 이 아니라 사유다★"""
    pw = pairwise_rank_corr({"a": np.ones(20), "b": np.linspace(0, 1, 20)})
    assert pw[0]["rho"] is None
    assert pw[0]["reason"]


# ── 2. ★같은 알파를 두 번 넣으면 중복이 잡힌다★ ────────────────────────────

def test_the_same_alpha_twice_is_reported_as_one_effective_bet():
    r = combine_alphas([_spec("A", "rank(mom_1m)"), _spec("B", "rank(mom_1m)")],
                       TICKERS, price_loader=_loader())
    assert r["available"] is True, r.get("reason")
    assert r["effective_n"] == pytest.approx(1.0, abs=0.05)
    assert any(p["duplicate"] for p in r["pairwise"])
    assert any("같은 베팅" in w for w in r["warnings"]), r["warnings"]


def test_a_negated_alpha_is_also_a_duplicate_bet():
    """부호만 뒤집은 알파는 |ρ|=1 이다 — 방향이 달라도 같은 정보다."""
    r = combine_alphas([_spec("A", "rank(mom_1m)"), _spec("B", "neg(rank(mom_1m))")],
                       TICKERS, price_loader=_loader())
    rho = r["pairwise"][0]["rho"]
    assert rho == pytest.approx(-1.0, abs=0.02)
    assert abs(rho) >= DUP_RHO and r["pairwise"][0]["duplicate"] is True


# ── 3. 가중치가 실제로 배합을 바꾼다 ────────────────────────────────────────

def test_a_single_alpha_at_full_weight_reproduces_its_own_ranking():
    from src.engine.alpha_lab import score_alpha
    solo = score_alpha("rank(mom_1m)", TICKERS, price_loader=_loader())
    r = combine_alphas([_spec("A", "rank(mom_1m)", 1.0)], TICKERS, price_loader=_loader())
    top_solo = [t for t, _ in sorted(solo["scores"].items(), key=lambda x: -x[1])[:10]]
    top_combo = [t for t, _ in sorted(r["scores"].items(), key=lambda x: -x[1])[:10]]
    assert top_combo == top_solo


def test_weights_shift_the_blend():
    a_heavy = combine_alphas([_spec("A", "rank(mom_1m)", 9.0), _spec("B", "rank(vol_20d)", 1.0)],
                             TICKERS, price_loader=_loader())
    b_heavy = combine_alphas([_spec("A", "rank(mom_1m)", 1.0), _spec("B", "rank(vol_20d)", 9.0)],
                             TICKERS, price_loader=_loader())
    assert a_heavy["scores"] != b_heavy["scores"], "가중치가 배합을 바꾸지 않는다"


def test_zero_total_weight_is_refused():
    r = combine_alphas([_spec("A", "rank(mom_1m)", 1.0), _spec("B", "rank(vol_20d)", -1.0)],
                       TICKERS, price_loader=_loader())
    assert r["available"] is False and "가중치" in r["reason"]


# ── 4. ★산출 불가 알파는 조용히 빠지지 않는다★ ─────────────────────────────

def test_an_unscorable_alpha_is_excluded_with_a_reason_and_no_renormalization():
    """제외하고 남은 가중치를 재정규화하면 **사용자가 지정한 배합과 다른 것**이 계산된다.

    그래서 제외 사실과 사유를 내고, `used` 의 가중치는 원래 값 그대로 둔다.
    """
    r = combine_alphas([_spec("GOOD", "rank(mom_1m)", 3.0),
                        _spec("BROKEN", "rank(nope_not_a_field)", 7.0)],
                       TICKERS, price_loader=_loader())
    assert r["available"] is True, r.get("reason")
    assert [e["alpha_id"] for e in r["excluded"]] == ["BROKEN"]
    assert r["excluded"][0]["reason"]
    assert [u["weight"] for u in r["used"]] == [3.0], "남은 가중치가 재정규화됐다"
    assert any("재정규화하지 않았" in w for w in r["warnings"]), r["warnings"]


def test_all_alphas_unscorable_is_refused_not_an_empty_portfolio():
    r = combine_alphas([_spec("X", "rank(nope_a)"), _spec("Y", "rank(nope_b)")],
                       TICKERS, price_loader=_loader())
    assert r["available"] is False
    assert len(r["excluded"]) == 2
    assert "scores" not in r


# ── 5. as_of 는 결합에서도 이어진다 ─────────────────────────────────────────

def test_as_of_is_carried_through_the_combination():
    r = combine_alphas([_spec("A", "rank(mom_1m)")], TICKERS,
                       as_of="2024-06-28", price_loader=_loader())
    assert r["as_of_requested"] == "2024-06-28"
    assert r["as_of_effective"]
    late = combine_alphas([_spec("A", "rank(mom_1m)")], TICKERS, price_loader=_loader())
    assert r["scores"] != late["scores"], "as_of 가 결합 결과를 바꾸지 않는다"
