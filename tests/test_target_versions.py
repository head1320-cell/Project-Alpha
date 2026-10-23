"""TargetPortfolioVersion — 목표 포트폴리오는 하나여야 한다 (R0-T)
==============================================================================
왜 이 파일이 먼저인가
------------------------------------------------------------------------------
이 저장소에는 **화면이 보여 주는 목표와 실행이 주문하는 목표가 다른** 결함이 있었다:

  · `TimingOverlayPanel.tsx:58-61` 이 `after = before × exposure` 를 화면에서만 계산
  · `ExecutionRoom.tsx:87` 은 오버레이 이전의 `weights.optimized` 를 주문 목표로 전송
  · `stress/page.tsx:61` 은 아예 `holdings`(현재 보유)를 스트레스

즉 같은 "목표"가 세 화면에서 세 값이었다. 컴파일 산수를 **서버 한 곳**에 두고,
그 결과 하나(`final_weights`)만 실행·스트레스·귀인이 참조하게 만드는 것이 이 단계다.

여기 단언은 전부 **엔진 계약**이다 — UI 가 무엇을 그리든 이 값이 진실이어야 한다.
"""

from __future__ import annotations

import pytest

from src.data.target_versions import (
    STATUS_EXECUTABLE,
    STATUS_RESEARCH_ONLY,
    compile_target,
)

BASE = {"005930": 40.0, "000660": 35.0, "035720": 25.0}   # 합 100% (퍼센트 단위)


def _sum(w: dict[str, float]) -> float:
    return round(sum(w.values()), 6)


# ── 1. 컴파일 산수 — 오버레이가 목표에 실제로 반영된다 ────────────────────────
def test_overlay_scales_weights_and_moves_the_rest_to_cash():
    tv = compile_target(BASE, overlay={"exposure": 0.6, "source": "canary"})

    assert tv["final_weights"] == {"005930": 24.0, "000660": 21.0, "035720": 15.0}
    assert tv["cash_weight"] == pytest.approx(40.0)
    # ★현금까지 포함해야 100 이다★ 현금을 빼고 정규화하면 노출 축소가 사라진다.
    assert _sum(tv["final_weights"]) + tv["cash_weight"] == pytest.approx(100.0)
    assert tv["status"] == STATUS_EXECUTABLE


def test_no_overlay_is_the_base_portfolio_itself():
    tv = compile_target(BASE, overlay=None)
    assert tv["final_weights"] == BASE
    assert tv["cash_weight"] == pytest.approx(0.0)
    assert tv["status"] == STATUS_EXECUTABLE


def test_full_exposure_is_indistinguishable_from_no_overlay():
    a = compile_target(BASE, overlay={"exposure": 1.0, "source": "canary"})
    b = compile_target(BASE, overlay=None)
    assert a["final_weights"] == b["final_weights"]
    assert a["cash_weight"] == pytest.approx(b["cash_weight"])


def test_zero_exposure_is_all_cash_not_an_empty_portfolio():
    """노출 0 은 '포트폴리오 없음'이 아니라 '전부 현금'이다 — 둘은 다른 상태다."""
    tv = compile_target(BASE, overlay={"exposure": 0.0, "source": "canary"})
    assert tv["cash_weight"] == pytest.approx(100.0)
    assert set(tv["final_weights"]) == set(BASE)          # 종목이 사라지지 않는다
    assert all(v == 0.0 for v in tv["final_weights"].values())


# ── 2. research_only 게이트 — '시장중립인 척' 하는 경로를 막는다 ──────────────
def test_post_hoc_neutralized_target_is_not_executable():
    """`NeutralizePanel` 은 최적화 제약이 아니라 사후 변환이고, UI 스스로
    '재최적화하면 사라진다'고 적는다. 그런 목표로 주문을 내면 안 된다."""
    tv = compile_target(BASE, overlay=None, neutralized=True)
    assert tv["status"] == STATUS_RESEARCH_ONLY
    assert tv["status_reason"]                            # 사유 없이 막지 않는다
    assert "중립화" in tv["status_reason"]


def test_negative_weight_is_refused_not_silently_dropped():
    """`_w_dict`(allocation_routes.py:257)는 음수 비중을 조용히 버렸다 —
    롱숏이 아닌데 롱온리처럼 보이게 만드는 가장 위험한 형태의 침묵이다.
    버리지 말고 **거부**한다(롱숏 지원은 P3)."""
    tv = compile_target({**BASE, "035420": -12.0}, overlay=None)
    assert tv["status"] == STATUS_RESEARCH_ONLY
    assert "음수" in tv["status_reason"]
    # ★버려지지 않았다★ 값이 그대로 남아 있어야 무엇이 문제인지 화면이 말할 수 있다.
    assert tv["final_weights"]["035420"] == pytest.approx(-12.0)


def test_overlay_without_a_source_is_not_executable():
    """출처 없는 노출 축소는 근거가 없는 매도다."""
    tv = compile_target(BASE, overlay={"exposure": 0.5, "source": None})
    assert tv["status"] == STATUS_RESEARCH_ONLY
    assert "출처" in tv["status_reason"]


@pytest.mark.parametrize("bad", [-0.1, 1.4])
def test_exposure_outside_zero_to_one_is_rejected(bad):
    with pytest.raises(ValueError):
        compile_target(BASE, overlay={"exposure": bad, "source": "canary"})


# ── 3. 영속화 왕복 — 저장한 목표가 그대로 돌아온다 ───────────────────────────
def test_save_and_load_round_trip_preserves_the_compiled_target():
    from src.data.target_versions import get_target, save_target

    tv = compile_target(BASE, overlay={"exposure": 0.6, "source": "canary"},
                        run_id="rr_test_1", snapshot_id="snap_1")
    tpv_id = save_target(tv)
    assert tpv_id and tpv_id.startswith("tpv_")

    got = get_target(tpv_id)
    assert got is not None
    assert got["final_weights"] == tv["final_weights"]
    assert got["cash_weight"] == pytest.approx(tv["cash_weight"])
    assert got["status"] == STATUS_EXECUTABLE
    assert got["run_id"] == "rr_test_1"
    assert got["snapshot_id"] == "snap_1"
    assert got["code_version"]                            # 서버가 스탬프한다


def test_missing_id_returns_none_not_a_fabricated_target():
    from src.data.target_versions import get_target
    assert get_target("tpv_does_not_exist") is None
