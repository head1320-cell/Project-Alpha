"""λ(delta)가 최적화 응답의 어디에 영향을 주는지 **실측으로 고정**한다.

★왜 이 테스트가 필요한가★
프론트의 stale 판정 서명(AllocationProvider 의 currentSig)은 delta 를 **무조건** 포함하고
있었다. 그래서 λ 슬라이더를 한 칸 움직이면 파이프라인 전체가 "재계산 필요"로 뒤집혔다.
반면 화면(optimize/page.tsx)은 "드래그 = 프론티어 위 선택점 이동 (재계산 없음)" 이라고
적고 있었다. 둘 다 무조건문이고 서로 반대다 — 즉 둘 중 하나가 아니라 **둘 다** 틀렸다.

진실은 조건부다. optimize() 에서 delta 가 닿는 경로는 `pi = delta * S @ w_mkt` 하나뿐이고,
그 줄은 `if views:` 안에 있다. 뷰가 없으면 delta 는 응답의 어떤 숫자에도 닿지 않는다.

프론트가 이 술어를 추측으로 적으면 엔진이 바뀌는 순간 조용히 어긋난다(그리고 stale 판정은
틀려도 아무 테스트가 빨개지지 않는 종류의 상태다). 그래서 술어를 여기에 못 박는다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.allocation_studio import optimize

NAMES = ["AAA111", "BBB222", "CCC333", "DDD444"]
LAM_LO, LAM_HI = 1.0, 7.0
VIEWS = [{"assets": ["AAA111"], "direction": 1, "magnitude_pct": 8.0, "confidence": 70}]


@pytest.fixture()
def returns() -> np.ndarray:
    """결정적 합성 수익률 — 시드 고정. 자산별 변동성을 다르게 줘서 모델들이
    서로 다른 해를 내도록 한다(전부 같으면 균등가중으로 수렴해 차이가 안 보인다)."""
    rng = np.random.default_rng(20260806)
    scale = np.array([0.008, 0.013, 0.020, 0.006])
    return rng.normal(0.0004, 1.0, size=(500, len(NAMES))) * scale


def _run(returns: np.ndarray, model: str, views, delta: float) -> dict:
    return optimize(model, NAMES, returns, views=views, delta=delta, tau=0.05)


def test_no_views_delta_changes_nothing(returns: np.ndarray) -> None:
    """★핵심★ 뷰가 없으면 λ 는 응답의 어떤 숫자에도 영향을 주지 않는다.

    이것이 프론트 술어의 근거다 — 뷰가 없을 때 λ 를 서명에 넣으면, 아무것도 바뀌지
    않았는데 결과가 낡았다고 말하게 된다.
    """
    for model in ("bl", "mvo", "min_var", "risk_parity"):
        lo = _run(returns, model, None, LAM_LO)
        hi = _run(returns, model, None, LAM_HI)
        np.testing.assert_allclose(
            lo["weights"], hi["weights"], rtol=0, atol=0,
            err_msg=f"{model}: 뷰가 없는데 λ 가 최종 비중을 바꿨다",
        )
        for leg in ("market", "view_applied", "optimized"):
            np.testing.assert_allclose(
                lo["flow"][leg], hi["flow"][leg], rtol=0, atol=0,
                err_msg=f"{model}: 뷰가 없는데 λ 가 flow.{leg} 를 바꿨다",
            )


def test_bl_with_views_delta_changes_optimized(returns: np.ndarray) -> None:
    """BL + 유효한 뷰 → λ 가 최종 비중을 바꾼다 (pi = delta * S @ w_mkt → mu_bl → w_view)."""
    lo = _run(returns, "bl", VIEWS, LAM_LO)
    hi = _run(returns, "bl", VIEWS, LAM_HI)
    assert lo["views_applied"] and hi["views_applied"], "뷰가 적용되지 않으면 이 테스트는 무의미하다"
    assert not np.allclose(lo["weights"], hi["weights"]), "BL + 뷰인데 λ 가 최종 비중을 안 바꿨다"


def test_cov_only_model_with_views_delta_still_changes_flow(returns: np.ndarray) -> None:
    """★이 케이스가 프론트 술어를 '뷰 유무'로 단순화시킨 이유다★

    공분산 전용 모델(min_var 등)은 기대수익을 쓰지 않으므로 λ 가 **최종 비중**은 못 바꾼다.
    그런데 optimize() 는 모델과 무관하게 `if views:` 안에서 w_view 를 계산하고 그것을
    `flow.view_applied` 로 돌려준다. 이 열은 화면에 그려진다(explain 의 '② View(BL)' 열,
    배분 Sankey). 즉 λ 는 최종 비중을 안 건드려도 **표시되는 숫자**는 바꾼다.

    그래서 술어는 "model === 'bl' 이고 뷰가 있을 때" 가 아니라 그냥 **"유효한 뷰가 있을 때"**
    여야 한다. 모델로 좁히면 explain 화면이 낡은 flow 를 최신인 양 보여 준다.
    """
    lo = _run(returns, "min_var", VIEWS, LAM_LO)
    hi = _run(returns, "min_var", VIEWS, LAM_HI)

    np.testing.assert_allclose(
        lo["weights"], hi["weights"], rtol=0, atol=0,
        err_msg="공분산 전용 모델인데 λ 가 최종 비중을 바꿨다",
    )
    assert not np.allclose(lo["flow"]["view_applied"], hi["flow"]["view_applied"]), (
        "공분산 전용 모델이어도 flow.view_applied 는 λ 에 반응해야 한다 — "
        "반응하지 않는다면 프론트 술어를 model 기준으로 좁혀도 된다는 뜻이므로 "
        "이 주석과 AllocationProvider 의 술어를 함께 고칠 것"
    )


def test_view_with_zero_magnitude_is_not_a_valid_view(returns: np.ndarray) -> None:
    """크기 0 뷰는 build_user_views 가 스킵한다 → 유효한 뷰가 0개 → λ 무영향.

    프론트가 서명에서 쓰는 필터(`assets.length > 0 && magnitude_pct > 0`)가 엔진의
    유효성 판정과 같은 뜻인지 확인한다. 여기가 어긋나면 '뷰가 있다고 생각해서 λ 를
    서명에 넣었는데 엔진은 뷰를 버린' 상태가 되어 영원히 stale 이 된다.
    """
    empty = [{"assets": ["AAA111"], "direction": 1, "magnitude_pct": 0.0, "confidence": 70}]
    lo = _run(returns, "bl", empty, LAM_LO)
    hi = _run(returns, "bl", empty, LAM_HI)
    assert not lo["views_applied"], "크기 0 뷰가 적용됐다 — 프론트 필터와 엔진 판정이 어긋난다"
    np.testing.assert_allclose(
        lo["weights"], hi["weights"], rtol=0, atol=0,
        err_msg="유효한 뷰가 없는데 λ 가 비중을 바꿨다",
    )
