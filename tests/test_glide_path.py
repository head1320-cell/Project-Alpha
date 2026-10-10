"""AO1 — 글라이드패스: ★곡선은 선언, 지점은 관측★ (순수 계층).

## 왜 이 모듈이 생겼나

로드맵 P2 가 `글라이드패스·적립` 을 **"★설계만★ — 코드 없음"** 으로 남겨 두고 사유를
적었다: *"계좌 유형이 없는 상태에서 만들면 걸 곳이 없다."* AD1(계좌 4종)·AD2
(`horizon_days`·`target_retirement_year`)·AD3(위험자산 비중 구간)이 생기면서 그
차단이 해소됐다.

## ★AD3 의 규율을 그대로 잇는다★

`risky_share.py` 가 갈라 둔 것:

    ① 보유가 어느 자산군에 있는가   ← **데이터**
    ② 어느 자산군이 '위험자산' 인가  ← ★규제 판단. 저장소가 답할 수 없다★

글라이드패스도 똑같이 갈린다:

    ① 잔여 기간은 얼마인가          ← **관측**(결정론적)
    ② 어떤 곡선을 그릴 것인가        ← ★투자 판단·상품 설계. 요청이 선언한다★

★이름 있는 프리셋(`"TDF2045"`·`"100-age"`)을 코드가 들지 않는다★ — 드는 순간 이
저장소가 "이 곡선이 옳다" 고 **주장**한다. AD3 의 문장 그대로다:
*"계산해 놓고 '참고용' 이라고 적는 것보다 아예 내지 않는 것이 정직하다."*

## ★보간만 한다. 외삽하지 않는다★

곡선 범위 밖이면 끝점으로 **고정하고 그 사실을 사유에 적는다.** 조용히 직선을
연장하면 선언되지 않은 구간을 지어내는 것이다.

## ★목표가 관측 구간 **안**에 있으면 격차는 `0` 이 아니라 미상★

AD3 의 미배정분이 격차의 **부호를 정하지 못한다**. 점 하나로 "0 입니다" 라고
말하면 그것이 `미상 ≠ 0` 위반이다.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest

from src.domain.glide_path import (
    GAP_ABOVE,
    GAP_BELOW,
    GAP_UNKNOWN,
    GlidePoint,
    gap_interval,
    glide_label,
    target_at,
    years_remaining,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "glide_path.py")

#: 예시 곡선 — ★이 저장소가 권하는 곡선이 아니다. 테스트 픽스처일 뿐이다.★
CURVE = (GlidePoint(years_to_target=30.0, risky_target_pct=80.0),
         GlidePoint(years_to_target=10.0, risky_target_pct=50.0),
         GlidePoint(years_to_target=0.0, risky_target_pct=20.0))


# ═══════════════════════════════════════════════════════════════════════════
# ★코드가 곡선을 들지 않는다★ — 이 파일의 첫 계약
# ═══════════════════════════════════════════════════════════════════════════

def test_the_module_ships_no_named_curve_preset():
    """★프리셋을 두면 "이 곡선이 옳다" 는 주장이 된다★ (AD3 규율)

    소스에 `TDF`·`100-age` 같은 상품명이나, 모듈 수준의 `GlidePoint` 목록
    상수가 있으면 red 다.
    """
    src = _MODULE.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    for banned in ("TDF", "100-age", "100 - age"):
        assert banned not in body, banned

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List)):
            dumped = ast.dump(node.value)
            assert "GlidePoint" not in dumped, (
                "모듈 수준에 곡선 상수가 있다 — 곡선은 요청이 선언한다")


def test_the_module_is_pure():
    """설정·DB·네트워크를 읽지 않는다 — 어휘는 순수해야 테스트된다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"os", "requests", "sqlalchemy", "src"}), imported


# ═══════════════════════════════════════════════════════════════════════════
# years_remaining — ★미상을 지어내지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_horizon_days_gives_years():
    yrs, reason = years_remaining(horizon_days=3650)
    assert yrs == pytest.approx(10.0, abs=0.05)
    assert reason is None


def test_target_retirement_year_gives_years():
    yrs, reason = years_remaining(target_retirement_year=2040,
                                  today=date(2026, 9, 19))
    assert yrs is not None and 13.0 < yrs < 14.5
    assert reason is None


def test_neither_declared_is_unknown_with_a_reason():
    """★기간을 기본값으로 채우지 않는다★ (`InvestorProfile` 이 같은 규율이다)"""
    yrs, reason = years_remaining()
    assert yrs is None
    assert reason


def test_a_past_retirement_year_is_zero_not_negative():
    """이미 지난 목표 시점 — 잔여는 0 이고, 음수를 곡선에 넣지 않는다."""
    yrs, reason = years_remaining(target_retirement_year=2020,
                                  today=date(2026, 9, 19))
    assert yrs == 0.0
    assert reason, "이미 지났다는 사실은 적어야 한다"


def test_the_two_inputs_disagreeing_is_reported_not_averaged():
    """★어긋나면 지어내지 않는다★ — 평균 내거나 하나를 조용히 고르지 않는다."""
    yrs, reason = years_remaining(horizon_days=3650,          # 10년
                                  target_retirement_year=2050,  # ≈24년
                                  today=date(2026, 9, 19))
    assert reason and ("어긋" in reason or "불일치" in reason)
    assert yrs is None, "둘이 어긋나면 값을 내지 않는다"


def test_consistent_inputs_do_not_complain():
    """★짝★ — 항상 불평하는 구현을 배제한다."""
    yrs, reason = years_remaining(horizon_days=3650,
                                  target_retirement_year=2036,
                                  today=date(2026, 9, 19))
    assert yrs is not None
    assert reason is None


@pytest.mark.parametrize("bad", [-1, "십년", 3.5, None])
def test_a_bad_horizon_is_unknown_not_guessed(bad):
    if bad is None:
        return
    yrs, reason = years_remaining(horizon_days=bad)
    assert yrs is None
    assert reason


# ═══════════════════════════════════════════════════════════════════════════
# target_at — ★보간만 한다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_declared_point_returns_its_value():
    assert target_at(CURVE, 10.0)[0] == pytest.approx(50.0)


def test_between_points_is_linear_interpolation():
    """20년: 30년(80%) 과 10년(50%) 의 중간 → 65%"""
    assert target_at(CURVE, 20.0)[0] == pytest.approx(65.0)


def test_beyond_the_curve_clamps_and_says_so():
    """★외삽하지 않는다★ — 끝점으로 고정하고 그 사실을 사유에 적는다."""
    val, reason = target_at(CURVE, 45.0)
    assert val == pytest.approx(80.0), "가장 먼 점으로 고정"
    assert reason and ("고정" in reason or "범위" in reason)


def test_below_the_curve_clamps_and_says_so():
    val, reason = target_at(CURVE, -3.0)
    assert val == pytest.approx(20.0)
    assert reason


def test_inside_the_curve_has_no_clamp_reason():
    """★짝★ — 항상 사유를 붙이는 구현을 배제한다."""
    assert target_at(CURVE, 20.0)[1] is None


def test_an_undeclared_curve_returns_nothing():
    """★선언이 없으면 내지 않는다★ (AD3 의 핵심 규율)"""
    for empty in (None, (), [GlidePoint(5.0, 40.0)]):
        val, reason = target_at(empty, 10.0)
        assert val is None, empty
        assert reason


def test_an_unknown_horizon_returns_nothing():
    val, reason = target_at(CURVE, None)
    assert val is None
    assert reason


def test_the_points_need_not_be_sorted():
    """운영자가 순서를 섞어 줘도 같은 답이어야 한다 — 정렬은 우리 일이다."""
    shuffled = (CURVE[1], CURVE[2], CURVE[0])
    assert target_at(shuffled, 20.0)[0] == pytest.approx(target_at(CURVE, 20.0)[0])


def test_a_duplicated_year_is_refused_not_averaged():
    """같은 연차에 두 목표 — ★어느 것이 맞는지 우리가 정하지 않는다★"""
    dup = (GlidePoint(10.0, 50.0), GlidePoint(10.0, 70.0), GlidePoint(0.0, 20.0))
    val, reason = target_at(dup, 10.0)
    assert val is None
    assert reason


# ═══════════════════════════════════════════════════════════════════════════
# gap_interval — ★구간을 점으로 접지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_whole_interval_above_the_target_is_above():
    g = gap_interval(50.0, observed_lo=70.0, observed_hi=75.0)
    assert g["state"] == GAP_ABOVE
    assert g["lo"] == pytest.approx(20.0) and g["hi"] == pytest.approx(25.0)


def test_the_whole_interval_below_the_target_is_below():
    g = gap_interval(50.0, observed_lo=30.0, observed_hi=40.0)
    assert g["state"] == GAP_BELOW
    assert g["lo"] == pytest.approx(-20.0) and g["hi"] == pytest.approx(-10.0)


def test_a_target_inside_the_interval_is_unknown_not_zero():
    """★이 모듈의 핵심★ — 미배정분이 부호를 정하지 못한다. `미상 ≠ 0`"""
    g = gap_interval(50.0, observed_lo=40.0, observed_hi=60.0)
    assert g["state"] == GAP_UNKNOWN
    assert g["reason"]
    assert g.get("sign") is None


def test_all_three_states_are_reachable():
    """★공허한 분기는 증거가 아니다★ (AL 의 변이 `d`)"""
    got = {gap_interval(50.0, 70.0, 75.0)["state"],
           gap_interval(50.0, 30.0, 40.0)["state"],
           gap_interval(50.0, 40.0, 60.0)["state"]}
    assert got == {GAP_ABOVE, GAP_BELOW, GAP_UNKNOWN}


def test_a_missing_target_or_observation_is_unknown():
    for args in ((None, 40.0, 60.0), (50.0, None, 60.0), (50.0, 40.0, None)):
        g = gap_interval(*args)
        assert g["state"] == GAP_UNKNOWN
        assert g["reason"]


def test_an_inverted_interval_is_refused():
    """`lo > hi` 는 호출부의 버그다 — 조용히 뒤집지 않는다."""
    g = gap_interval(50.0, observed_lo=60.0, observed_hi=40.0)
    assert g["state"] == GAP_UNKNOWN
    assert g["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# glide_label
# ═══════════════════════════════════════════════════════════════════════════

def test_the_label_carries_every_premise_and_its_state():
    out = glide_label(years=20.0, years_reason=None, curve=CURVE,
                      observed_lo=70.0, observed_hi=75.0)
    assert out["years_remaining"] == pytest.approx(20.0)
    assert out["target_pct"] == pytest.approx(65.0)
    assert out["gap"]["state"] == GAP_ABOVE
    assert out["note"]


def test_the_label_emits_no_numbers_without_a_curve():
    """★전제가 없으면 숫자를 내지 않는다★"""
    out = glide_label(years=20.0, years_reason=None, curve=None,
                      observed_lo=70.0, observed_hi=75.0)
    assert out["target_pct"] is None
    assert out["gap"]["state"] == GAP_UNKNOWN
    assert out["curve_reason"]


def test_the_note_does_not_claim_the_curve_is_right():
    """★결론은 증거보다 강할 수 없다★ — 곡선의 타당성은 이 저장소 밖이다."""
    note = glide_label(years=20.0, years_reason=None, curve=CURVE,
                       observed_lo=70.0, observed_hi=75.0)["note"]
    assert "선언" in note
    assert "권" not in note.replace("권장하지", "").replace("권하지", "")
