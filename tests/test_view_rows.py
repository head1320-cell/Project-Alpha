"""뷰 행(P) 단일화 + 부호 있는 가중치 — ★T3-B/C 를 표현 가능하게★
==============================================================================
계획: `docs/specs/2026-08-25-t3-transmission-study.md` §5·§6.4

T3 연구가 자산군 **상대** 뷰(T3-B)를 가장 방어 가능한 전달 형태로 지목했는데,
현행 뷰 스키마는 **양수 등가중 행 + 스칼라 방향**만 표현할 수 있어 BL·EP 어느
쪽으로도 돌릴 수 없다. 이 파일은 그 장벽을 없앤 것을 못 박는다.

★채택이 아니라 표현 가능성이다.★ `weights` 를 안 보내면 행이 현행과 동일해야
한다 — 그것이 V2 다.

★그리고 절반은 스키마가 아니라 단일화다★ 같은 규칙이 **세 곳에 손으로** 구현돼
있었다(`allocation_studio:84` · `entropy_views:97` · `risk_allocations:318`).
셋 중 둘만 고치면 같은 뷰가 BL 과 EP 에서 다른 P 행이 되고, 그 차이는 두 응답을
나란히 놓기 전에는 보이지 않는다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.view_rows import (  # noqa: E402
    ViewRow,
    build_view_rows,
    group_spread_row,
    row_from_spec,
)

NAMES = ["EQ0", "EQ1", "EQ2", "FI0", "FI1", "FI2"]
SPREAD = {"EQ0": 1 / 3, "EQ1": 1 / 3, "EQ2": 1 / 3,
          "FI0": -1 / 3, "FI1": -1 / 3, "FI2": -1 / 3}


def _rows(views):
    return build_view_rows(views, NAMES)


# ══════════════════════════════════════════════════════════════════════════
# V1 · ★소비자들이 같은 행을 만든다★ (복사본 재발 방지)
# ══════════════════════════════════════════════════════════════════════════
def test_bl_and_ep_build_identical_rows():
    """★핵심 가드★ 같은 뷰 → BL 의 `P` 행과 EP 의 피커 행이 **원소별 동일**.

    셋 중 하나만 고치는 회귀를 구조적으로 막는다.
    """
    from src.engine.allocation_studio import build_user_views
    from src.engine.entropy_views import _pickers

    views = [{"assets": ["EQ0", "EQ1"], "direction": 1,
              "magnitude_pct": 8.0, "confidence": 50},
             {"weights": SPREAD, "direction": 1,
              "magnitude_pct": 3.0, "confidence": 40}]
    sigma = np.eye(len(NAMES)) * 0.04

    P, Q, om, skipped = build_user_views(views, NAMES, sigma)
    picks, ep_skipped = _pickers(views, NAMES)

    assert P is not None and len(picks) == P.shape[0]
    for i, pick in enumerate(picks):
        row = pick[0] if isinstance(pick, tuple) else pick.row
        np.testing.assert_allclose(row, P[i], rtol=0, atol=1e-15)
    assert len(skipped) == len(ep_skipped)


def test_risk_allocations_uses_the_shared_primitive():
    """세 번째 복사본(`risk_allocations:318`)도 같은 원시함수를 쓴다.

    ★그쪽은 뷰 스키마가 아니라 매크로 틸트 맵을 쓴다★ — 그래서 공유하는 것은
    `build_view_rows` 가 아니라 **등가중 행 원시함수**다. 계약을 억지로 하나로
    합치지 않되, 행을 만드는 규칙이 갈라지지는 않게 한다.
    """
    import inspect

    from src.engine import risk_allocations
    src = inspect.getsource(risk_allocations)
    assert "row_from_spec" in src or "equal_weight_row" in src, \
        "risk_allocations 가 아직 행을 손으로 만든다"
    assert "1.0 / len(assets)" not in src, "손 구현이 남아 있다"


# ══════════════════════════════════════════════════════════════════════════
# V2 · ★기본값은 바뀌지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_assets_form_is_unchanged():
    """현행 입력(`assets`)의 행·방향·크기가 그대로여야 한다 — 채택이 아니라 확장이다."""
    rows, skipped = _rows([{"assets": ["EQ0", "EQ1"], "direction": -1,
                            "magnitude_pct": 6.0}])
    assert not skipped and len(rows) == 1
    r = rows[0]
    expected = np.zeros(len(NAMES))
    expected[0] = expected[1] = 0.5
    np.testing.assert_allclose(r.row, expected, rtol=0, atol=1e-15)
    assert r.direction == -1.0
    assert r.magnitude == pytest.approx(0.06)
    assert r.kind == "absolute"


def test_single_asset_row_is_a_unit_vector():
    rows, _ = _rows([{"assets": ["FI1"], "direction": 1, "magnitude_pct": 2.0}])
    assert rows[0].row[NAMES.index("FI1")] == pytest.approx(1.0)
    assert float(np.abs(rows[0].row).sum()) == pytest.approx(1.0)


# ══════════════════════════════════════════════════════════════════════════
# V3 · ★부호 있는 가중치 = 스프레드 행★
# ══════════════════════════════════════════════════════════════════════════
def test_signed_weights_produce_a_spread_row():
    """행 합 ≈ 0(수준 성분 상쇄), `Σ|w| = 2`(재정규화하지 않는다)."""
    rows, skipped = _rows([{"weights": SPREAD, "direction": 1,
                            "magnitude_pct": 3.0}])
    assert not skipped and len(rows) == 1
    r = rows[0]
    assert r.kind == "weighted"
    assert float(r.row.sum()) == pytest.approx(0.0, abs=1e-12)
    assert float(np.abs(r.row).sum()) == pytest.approx(2.0, abs=1e-12)
    assert r.row[0] > 0 and r.row[3] < 0


def test_weights_are_not_renormalized():
    """★재정규화 금지★ `Ω` 의 base 가 행 노름에 비례해 함께 커지므로 자기정합적이다.

    여기서 정규화하면 `magnitude_pct` 의 뜻이 조용히 바뀐다.
    """
    big = {k: v * 10.0 for k, v in SPREAD.items()}
    rows, _ = _rows([{"weights": big, "direction": 1, "magnitude_pct": 3.0}])
    assert float(np.abs(rows[0].row).sum()) == pytest.approx(20.0, abs=1e-9)


def test_direction_multiplies_q_not_the_row():
    """`direction=-1` 은 **행이 아니라 Q** 를 뒤집는다 — 두 곳에 부호를 넣으면 상쇄된다."""
    pos, _ = _rows([{"weights": SPREAD, "direction": 1, "magnitude_pct": 3.0}])
    neg, _ = _rows([{"weights": SPREAD, "direction": -1, "magnitude_pct": 3.0}])
    np.testing.assert_allclose(pos[0].row, neg[0].row, rtol=0, atol=1e-15)
    assert pos[0].direction == 1.0 and neg[0].direction == -1.0


# ══════════════════════════════════════════════════════════════════════════
# V4~V6 · 모호함과 실패는 조용하지 않다
# ══════════════════════════════════════════════════════════════════════════
def test_weights_and_assets_together_is_skipped_with_a_reason():
    rows, skipped = _rows([{"assets": ["EQ0"], "weights": SPREAD,
                            "direction": 1, "magnitude_pct": 3.0}])
    assert not rows and len(skipped) == 1
    assert "동시" in skipped[0]["reason"]


def test_zero_row_is_skipped_with_a_reason():
    """★조용한 0 행 금지★ `Σ|w| ≈ 0` 이면 뷰가 아무것도 주장하지 않는다."""
    rows, skipped = _rows([{"weights": {"EQ0": 1.0, "EQ1": -1.0, "EQ2": 0.0,
                                        "FI0": 0.0, "FI1": 0.0, "FI2": 0.0},
                            "direction": 1, "magnitude_pct": 3.0}])
    assert len(rows) == 1, "합이 0이어도 |w| 합이 2 라 유효한 스프레드다"

    rows2, skipped2 = _rows([{"weights": {"EQ0": 0.0, "FI0": 0.0},
                              "direction": 1, "magnitude_pct": 3.0}])
    assert not rows2 and len(skipped2) == 1
    assert "0" in skipped2[0]["reason"] or "가중" in skipped2[0]["reason"]


def test_unknown_assets_are_dropped_but_reported():
    rows, skipped = _rows([{"weights": {"EQ0": 1.0, "없는종목": -1.0},
                            "direction": 1, "magnitude_pct": 3.0}])
    assert len(rows) == 1
    assert rows[0].row[NAMES.index("EQ0")] == pytest.approx(1.0)
    assert rows[0].dropped_assets == ["없는종목"]


def test_view_with_no_usable_asset_is_skipped():
    rows, skipped = _rows([{"weights": {"없는것": 1.0}, "direction": 1,
                            "magnitude_pct": 3.0}])
    assert not rows and skipped and skipped[0]["reason"]


def test_zero_magnitude_is_skipped():
    rows, skipped = _rows([{"weights": SPREAD, "direction": 1,
                            "magnitude_pct": 0.0}])
    assert not rows and skipped


# ══════════════════════════════════════════════════════════════════════════
# V7·V8 · ★EP 가 부호 있는 행을 받는다★ (짝 테스트)
# ══════════════════════════════════════════════════════════════════════════
def _panel(seed: int = 3, n_days: int = 500):
    """EQ 가 FI 를 앞서는 통제 패널 — 스프레드 뷰가 방향을 가질 수 있게."""
    rng = np.random.default_rng(seed)
    f = rng.normal(0.0004, 0.011, n_days)
    beta = np.array([1.2, 1.0, 0.8, 0.3, 0.2, 0.1])
    tilt = np.array([0.0004] * 3 + [-0.0002] * 3)
    return f[:, None] * beta + tilt + rng.normal(0.0, 0.004, (n_days, 6))


def test_ep_accepts_a_signed_row():
    """★V7★ 스프레드 뷰로 EP 가 **실행되고 판정을 낸다**(터지지 않는다)."""
    from src.engine.entropy_views import ep_posterior_mu

    rep = ep_posterior_mu([{"weights": SPREAD, "direction": 1,
                            "magnitude_pct": 2.0, "confidence": 50}],
                          NAMES, _panel())
    assert rep["available"] is True
    assert rep["n_views"] == 1
    assert "feasible" in rep


def test_bl_and_ep_agree_on_the_sign_of_a_spread_view():
    """★V8 — V7 의 짝★ 두 사후가 EQ−FI 스프레드의 **같은 방향**을 낸다.

    V7 만 있으면 "EP 가 터지지만 않으면 통과" 가 되고, 부호가 반대로 전달돼도
    살아남는다. 부호는 이 스키마 확장의 전부다.
    """
    from src.engine.allocation_studio import bl_posterior, build_user_views
    from src.engine.entropy_views import ep_posterior_mu

    R = _panel()
    sigma = np.cov(R, rowvar=False, ddof=1) * 252.0
    prior = R.mean(axis=0) * 252.0
    eq = [NAMES.index(n) for n in NAMES if n.startswith("EQ")]
    fi = [NAMES.index(n) for n in NAMES if n.startswith("FI")]

    def spread(mu):
        mu = np.asarray(mu, float)
        return float(mu[eq].mean() - mu[fi].mean())

    # ★"부호가 direction 과 같다" 로 쓰면 안 된다★ 처음에 그렇게 걸었다가 red 가
    # 났는데 **코드가 아니라 기대가 틀렸다**. 이 패널의 사전 스프레드(≈0.15)가 이미
    # Q(=0.04)보다 크므로 BL 은 사후를 **아래로** 당기는 것이 옳다. 사전이 어디
    # 있느냐에 의존하지 않는 불변식 둘로 바꾼다.
    post = {}
    for direction in (1, -1):
        view = [{"weights": SPREAD, "direction": direction,
                 "magnitude_pct": 4.0, "confidence": 60}]
        P, Q, om, _ = build_user_views(view, NAMES, sigma)
        bl_mu = bl_posterior(prior, sigma, P, Q, om)
        rep = ep_posterior_mu(view, NAMES, R)
        assert rep["available"]
        post[direction] = (spread(bl_mu), spread(rep["mu_annual"]),
                           spread(rep["prior_mu_annual"]), float(Q[0]))

        bl_post, ep_post, ep_prior, q = post[direction]

        # (1) BL 은 **항상 Q 쪽으로 섞인다** — 사전이 Q 보다 크면 내려간다.
        bl_move = bl_post - spread(prior)
        assert np.sign(bl_move) == np.sign(q - spread(prior)), \
            f"BL 이 Q 반대쪽으로 갔다: {bl_move}"

        # (2) ★EP 는 부등식이라 **이미 만족하면 움직이지 않는다**★
        #     이것이 BL 과의 진짜 의미 차이다 — 처음에 "둘 다 Q 쪽으로 움직인다" 로
        #     걸었다가 red 가 났는데 **코드가 아니라 기대가 틀렸다**. 사전 스프레드가
        #     0.338 이고 뷰가 "≥ 0.04" 면 EP 는 아무것도 할 필요가 없다(사후=사전).
        #     제약이 깨졌을 때만 경계로 당긴다.
        satisfied = (q >= 0 and ep_prior >= q) or (q < 0 and ep_prior <= q)
        if satisfied:
            assert ep_post == pytest.approx(ep_prior, abs=1e-9), \
                "EP 가 이미 만족된 제약에서 사후를 움직였다"
        else:
            assert np.sign(ep_post - ep_prior) == np.sign(q - ep_prior), \
                f"EP 가 Q 반대쪽으로 갔다: {ep_post - ep_prior}"
            assert ep_post == pytest.approx(q, abs=1e-6), \
                "EP 는 위반된 제약을 **경계까지만** 당긴다"

    # (3) ★두 방향이 갈린다★ — direction=+1 의 사후 스프레드가 −1 보다 **크다**.
    #     BL·EP 가 같은 순서를 내는지가 이 스키마 확장의 핵심이다.
    assert post[1][0] > post[-1][0], f"BL 방향 순서가 뒤집혔다: {post}"
    assert post[1][1] > post[-1][1], f"EP 방향 순서가 뒤집혔다: {post}"


# ══════════════════════════════════════════════════════════════════════════
# V10 · 그룹 상대 행 헬퍼
# ══════════════════════════════════════════════════════════════════════════
def test_group_spread_row_builds_a_balanced_spread():
    groups = {"EQ0": "G1", "EQ1": "G1", "EQ2": "G1",
              "FI0": "G2", "FI1": "G2", "FI2": "G2"}
    w = group_spread_row(NAMES, groups, "G1", "G2")
    assert sum(w.values()) == pytest.approx(0.0, abs=1e-12)
    assert sum(abs(v) for v in w.values()) == pytest.approx(2.0, abs=1e-12)
    assert w["EQ0"] > 0 and w["FI0"] < 0


def test_group_spread_row_refuses_an_empty_group():
    groups = {"EQ0": "G1", "EQ1": "G1"}
    with pytest.raises(ValueError) as e:
        group_spread_row(NAMES, groups, "G1", "없는그룹")
    assert "없는그룹" in str(e.value)


def test_group_spread_row_output_is_a_valid_view():
    """헬퍼 산출물이 그대로 뷰로 들어가야 한다 — 두 계약이 맞물리는지 확인."""
    groups = {n: ("G1" if n.startswith("EQ") else "G2") for n in NAMES}
    w = group_spread_row(NAMES, groups, "G1", "G2")
    rows, skipped = _rows([{"weights": w, "direction": 1, "magnitude_pct": 3.0}])
    assert not skipped and rows[0].kind == "weighted"


def test_row_from_spec_is_the_shared_primitive():
    row, kind, dropped = row_from_spec(assets=["EQ0", "EQ1"], weights=None,
                                       names=NAMES)
    assert kind == "absolute" and dropped == []
    assert row[0] == pytest.approx(0.5)
    row2, kind2, _ = row_from_spec(assets=None, weights=SPREAD, names=NAMES)
    assert kind2 == "weighted" and row2.sum() == pytest.approx(0.0, abs=1e-12)


def test_view_row_is_frozen():
    """`usage` 계약과 같은 이유 — 소비자가 행을 나중에 고치지 못하게."""
    import dataclasses
    rows, _ = _rows([{"assets": ["EQ0"], "direction": 1, "magnitude_pct": 2.0}])
    with pytest.raises(dataclasses.FrozenInstanceError):
        rows[0].direction = -1.0            # type: ignore[misc]
    assert isinstance(rows[0], ViewRow)
