"""경제노출 → 상장 상품 선택 (Brief §7.1/7.2 · CTO §26)

★이 파일이 거는 것★
  1. ★노출 어휘가 팩터 어휘와 이어진다★ 재는 이름과 구현하는 이름이 같아야 한다.
  2. ★없는 기준을 지어내지 않는다★ 운용보수·분배금은 사유와 함께 `unavailable`.
  3. ★mock 추적오차를 순위에 쓰지 않는다★ 실측에서 같은 노출 후보끼리 상관이
     0.037 이었다(TE 39.95%) — 잡음을 근거로 삼지 않는다.
  4. ★합만 재지 않는다★ 구현 결과가 **어느 노출에서 왔는지**까지 못박는다
     (이 세션에서 '합만 재는 가드' 가 세 번 뚫렸다).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.instrument_selector import (  # noqa: E402
    EXPOSURES,
    FOREIGN_NOTE,
    UNAVAILABLE_CRITERIA,
    WEIGHTS,
    candidates,
    implement_exposures,
    score_instrument,
    select_instrument,
    tracking_error,
)


# ── 1. ★노출 어휘★ ────────────────────────────────────────────────────────
def test_the_exposure_names_line_up_with_the_factor_vocabulary():
    """★재는 이름과 구현하는 이름이 같아야 둘이 이어진다★"""
    from src.engine.factor_exposure import FACTORS
    shared = set(EXPOSURES) & set(FACTORS)
    assert {"equity", "duration", "credit", "commodity"} <= shared, shared


def test_every_exposure_declares_candidates_and_a_note():
    for name, spec in EXPOSURES.items():
        assert spec["label"], name
        assert isinstance(spec["kr"], list) and isinstance(spec["us"], list)
        assert spec["kr"] or spec["us"], f"{name} 에 후보가 하나도 없다"
        assert spec["note"], name


def test_an_unknown_exposure_lists_the_known_ones():
    out = candidates("없는노출")
    assert out["available"] is False
    assert "equity" in out["reason"], "가능한 노출을 알려준다"


# ── 2. ★KR 우선, 대안을 감추지 않는다★ ───────────────────────────────────
def test_a_kr_listed_candidate_is_preferred():
    """미국 대형주 노출도 국내 상장(TIGER)으로 먼저 구현한다."""
    c = candidates("equity_us", market="kr")
    assert c["available"] is True
    assert c["primary"] == EXPOSURES["equity_us"]["kr"]
    assert c["alternatives"] == EXPOSURES["equity_us"]["us"], "해외를 감추지 않는다"
    assert c["market_fallback"] is None


def test_an_exposure_without_kr_candidates_says_it_fell_back():
    """★조용히 넘어가지 않는다★ 국내 후보가 없다는 사실이 사유로 남는다."""
    c = candidates("duration", market="kr")
    assert c["available"] is True
    assert c["primary"] == ["TLT"]
    assert c["market_fallback"] and "국내 상장 후보가 없어" in c["market_fallback"]


def test_a_foreign_choice_carries_the_fx_and_tax_label():
    s = select_instrument("duration")
    assert s["available"] is True
    assert s["foreign_listing"] is True
    assert s["foreign_note"] == FOREIGN_NOTE
    assert "환노출" in s["foreign_note"] and "세율을 보유하지 않으므로" in s["foreign_note"]


def test_a_kr_choice_makes_no_foreign_claim():
    """★짝★ 전부 해외라고 하면 위 테스트도 green 이다."""
    s = select_instrument("equity_us", market="kr")
    assert s["foreign_listing"] is False and s["foreign_note"] is None


def test_the_market_argument_is_validated():
    assert candidates("equity", market="화성")["available"] is False


# ── 3. ★없는 기준을 지어내지 않는다★ ────────────────────────────────────
def test_expense_ratio_is_unavailable_with_a_reason():
    """★0 이나 기본값으로 채우지 않는다★ 벤더 데이터가 없다는 사실이 정보다."""
    s = score_instrument("069500")
    assert "expense_ratio" in s["unavailable"]
    assert "저장소에 없습니다" in s["unavailable"]["expense_ratio"]
    assert "expense_ratio" not in s, "값을 지어내지 않는다"


def test_corporate_actions_are_unavailable_with_a_reason():
    s = score_instrument("069500")
    assert "corporate_actions" in s["unavailable"]
    assert s["unavailable"]["corporate_actions"]


def test_the_unavailable_set_travels_with_the_selection():
    s = select_instrument("equity")
    assert set(s["unavailable"]) == set(UNAVAILABLE_CRITERIA)


def test_a_priceless_instrument_is_a_reason_not_a_zero(monkeypatch):
    monkeypatch.setattr("src.engine.instrument_selector._load",
                        lambda code, days: None)
    s = score_instrument("069500")
    assert s["available"] is False and s["reason"]
    assert "adv_krw" not in s


# ── 4. ★mock 추적오차를 순위에 쓰지 않는다★ ─────────────────────────────
def test_mock_tracking_error_is_marked_unusable():
    """★실측★ mock 로더는 티커마다 독립 난수walk 라 SPY-VTI 상관이 0.037 이었다."""
    te = tracking_error("SPY", "VTI")
    if not te["available"]:
        pytest.skip(f"이 환경에서 TE 를 낼 수 없다: {te['reason']}")
    assert te["source"] == "mock"
    assert te["usable"] is False
    assert "순위에 쓰지 않습니다" in te["note"]


def test_real_data_tracking_error_would_be_usable(monkeypatch):
    """★짝★ 실데이터 라벨이면 쓸 수 있어야 한다 — mock 이라 항상 막는 게 아니다."""
    monkeypatch.setattr("src.engine.instrument_selector._source_label",
                        lambda: "db")
    te = tracking_error("SPY", "VTI")
    if not te["available"]:
        pytest.skip("이 환경에서 TE 를 낼 수 없다")
    assert te["source"] == "db" and te["usable"] is True and te["note"] is None


def test_a_thin_overlap_is_a_reason(monkeypatch):
    import pandas as pd
    monkeypatch.setattr("src.engine.instrument_selector._load",
                        lambda code, days: pd.DataFrame({"close": [1.0, 1.1, 1.2]}))
    te = tracking_error("SPY", "VTI")
    assert te["available"] is False and "겹치는 일수" in te["reason"]


# ── 5. ★점수 공식을 숨기지 않는다★ ──────────────────────────────────────
def test_the_score_shows_its_parts_and_weights():
    """순위만 내면 왜 그 상품이 뽑혔는지 되짚을 수 없다."""
    s = select_instrument("equity_us", market="kr")
    top = s["ranked"][0]
    assert set(top["score_parts"]) == {"liquidity", "cost", "history"}
    assert top["score_weights"] == WEIGHTS
    assert 0.0 <= top["score"] <= 1.0
    assert "skipped_criteria" in top


def test_a_more_liquid_candidate_ranks_higher(monkeypatch):
    """★결정적으로 확인★ mock 은 후보가 동점이라 거래대금을 직접 심는다."""
    real = score_instrument

    def _spy(code, **kw):
        out = real(code, **kw)
        if out.get("available"):
            out["adv_krw"] = 1e12 if code == "381180" else 1e9
        return out
    monkeypatch.setattr("src.engine.instrument_selector.score_instrument", _spy)
    s = select_instrument("equity_us", market="kr")
    assert s["chosen"] == "381180", [r["code"] for r in s["ranked"]]


def test_the_method_is_declared():
    assert select_instrument("equity")["method"] == "liquidity_cost_history_weighted"


# ── 6. ★합이 아니라 출처까지 못박는다★ ──────────────────────────────────
def test_each_holding_records_which_exposure_it_came_from():
    """★합만 맞추면 무엇을 갈아야 하는지 알 수 없다★"""
    out = implement_exposures({"equity_us": 40.0, "duration": 30.0})
    assert out["available"] is True
    by_exposure = {ln["exposure"]: ln for ln in out["lines"]}
    assert set(by_exposure) == {"equity_us", "duration"}
    for exposure, ln in by_exposure.items():
        assert ln["instrument"] in out["holdings"]
        assert ln["weight_pct"] > 0
        assert ln["exposure"] == exposure
    assert by_exposure["duration"]["foreign_listing"] is True


def test_the_placed_weights_match_the_lines():
    out = implement_exposures({"equity_us": 40.0, "duration": 30.0})
    from collections import defaultdict
    rebuilt = defaultdict(float)
    for ln in out["lines"]:
        rebuilt[ln["instrument"]] += ln["weight_pct"]
    assert dict(rebuilt) == pytest.approx(out["holdings"])


def test_an_unresolvable_exposure_leaves_its_weight_unplaced():
    """★재분배하지 않는다★ 재분배하면 요청하지 않은 노출이 커진다."""
    out = implement_exposures({"equity_us": 40.0, "없는노출": 25.0})
    assert out["requested_pct"] == pytest.approx(65.0)
    assert out["placed_pct"] == pytest.approx(40.0)
    assert out["unplaced_pct"] == pytest.approx(25.0)
    assert "없는노출" in out["unresolved"]
    assert sum(out["holdings"].values()) == pytest.approx(40.0)
    assert "재분배하지 않습니다" in out["note"]


def test_two_exposures_sharing_an_instrument_accumulate():
    out = implement_exposures({"commodity": 10.0, "real_estate": 5.0})
    assert out["placed_pct"] == pytest.approx(15.0)
    assert sum(out["holdings"].values()) == pytest.approx(15.0)


def test_empty_input_is_a_reason():
    assert implement_exposures({})["available"] is False
