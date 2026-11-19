"""G3 — 자유도 공시: 이 자료로 고를 수 있었던 값의 수와 거래 수를 나란히 적는다(구현 계획 §4).

계약
- 규칙의 값: 틀 = 그 틀이 선언한 매개변수(수 · 고르기) 전부 · 직접 구성 = 나무 셋의 상수 · 지표 매개변수(기본값을 채운 하나의 꼴에서) · 연산 덧칸(봉 수 · 시각).
  같은 규칙은 늘 같은 수다(기본값을 적었든 안 적었든) · 검사를 지나지 못한 규칙은 세지 않는다(`RuleError`).
- 포지션의 값: 정한 칸(None 이 아닌 칸 — 기본값을 그대로 둔 칸도 센다) · 진입 금액은 세지 않는다(크기일 뿐이다) · 비용 가정은 받지도 않는다.
- 문장은 기술일 뿐 기준이 아니다: 값 하나당 거래 수를 적되 '충분하다 · 모자라다'를 말하지 않는다 · 거래 0 이면 나누지 않는다 · 값이 0 이면 나누지 않는다.
"""
from __future__ import annotations

import pytest

from src.engine.intraday import freedom, rules

POSITION = {"amount": 1_000_000, "stop_pct": 1.0, "target_pct": None, "trail_pct": None, "time_exit": "1500",
            "entry_from": None, "entry_until": None, "max_entries_per_ticker": 1, "max_open_positions": None,
            "daily_loss_limit": None, "cooldown_after_loss_min": None}            # 정한 칸 셋: 손절 · 시각 청산 · 종목당 진입 수


# ── 규칙의 값 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind,count", [
    ("opening_range_breakout", 1), ("vwap_cross", 1), ("volatility_breakout", 1), ("volume_surge", 2),
    ("gap", 3), ("rsi_reversal", 3), ("bollinger", 3),
])
def test_a_template_counts_every_value_it_declares(kind, count):
    """틀은 선언한 매개변수 전부가 손잡이다 — 기본값으로 두어도 그 값은 이 자료로 고를 수 있었다."""
    assert rules.free_values(kind)["count"] == count
    assert rules.free_values(kind, {}) == rules.free_values(kind)


def test_a_custom_rule_counts_constants_indicator_parameters_and_op_extras():
    """RSI(기간 14) > 30 으로 진입 · 14:00 ~ 15:00 이면 청산 = 상수 1 + 지표 매개변수 1 + 시각 2 = 넷."""
    params = {"entry": {"op": "gt", "args": [{"ind": "rsi"}, {"const": 30}]},
              "exit": {"op": "time_between", "from": "1400", "to": "1500"}}
    out = rules.free_values("custom", params)
    assert out["count"] == 4
    assert sorted(out["names"]) == sorted(["entry:const", "entry:rsi.n", "exit:time_between.from", "exit:time_between.to"])


def test_the_same_rule_written_with_or_without_defaults_counts_the_same():
    implicit = {"entry": {"op": "gt", "args": [{"ind": "rsi"}, {"const": 30}]}}
    explicit = {"entry": {"op": "gt", "args": [{"ind": "rsi", "n": 14}, {"const": 30.0}]}}
    assert rules.free_values("custom", implicit) == rules.free_values("custom", explicit)


def test_more_knobs_count_more__a_rule_without_constants_counts_zero():
    """짝: 상수를 하나 더하면 하나 는다 · 봉 수 덧칸도 하나다 ↔ 종가 > VWAP 는 값이 없다(0 은 관측이다)."""
    base = {"entry": {"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}}
    held = {"entry": {"op": "held_before", "bars": 3, "args": [{"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}]}}
    more = {"entry": {"op": "and", "args": [base["entry"], {"op": "gt", "args": [{"ind": "rsi"}, {"const": 30}]}]}}
    assert rules.free_values("custom", base)["count"] == 0
    assert rules.free_values("custom", held)["count"] == 1
    assert rules.free_values("custom", more)["count"] == 2


def test_a_rule_that_does_not_pass_the_check_is_not_counted():
    with pytest.raises(rules.RuleError):
        rules.free_values("gap", {"direction": "sideways"})
    with pytest.raises(rules.RuleError):
        rules.free_values("custom", {"exit": {"op": "gt", "args": [{"ind": "close"}, {"const": 1}]}})   # 진입이 없다
    with pytest.raises(rules.RuleError):
        rules.free_values("no_such_template")


# ── 공시 문장 ─────────────────────────────────────────────────────────────────────────
def test_the_disclosure_puts_the_count_beside_the_trades():
    """시가 범위 돌파(값 1) + 정한 포지션 칸 셋 = 넷 · 거래 20건 → 값 하나당 5.0건."""
    out = freedom.disclose("opening_range_breakout", {"minutes": 1}, POSITION, trades=20)
    assert (out["rule"], out["position"], out["count"], out["trades"]) == (1, 3, 4, 20)
    assert out["per_value"] == pytest.approx(5.0)
    assert out["position_names"] == ["stop_pct", "time_exit", "max_entries_per_ticker"]
    assert out["message"] == "조정 가능한 값 4개(규칙 1 · 포지션 3) · 거래 20건 · 값 하나당 거래 5.0건입니다."


def test_the_amount_and_unset_fields_are_not_knobs():
    """짝: 진입 금액을 바꿔도 · 비운 칸은 세지 않는다 ↔ 칸 하나를 정하면 하나 는다."""
    base = freedom.disclose("opening_range_breakout", {}, POSITION, trades=20)
    richer = freedom.disclose("opening_range_breakout", {}, {**POSITION, "amount": 5_000_000}, trades=20)
    one_more = freedom.disclose("opening_range_breakout", {}, {**POSITION, "trail_pct": 0.5}, trades=20)
    assert richer["count"] == base["count"] == 4
    assert one_more["count"] == 5 and "trail_pct" in one_more["position_names"]


def test_no_trades_and_no_knobs_are_said_without_dividing():
    none_traded = freedom.disclose("opening_range_breakout", {}, POSITION, trades=0)
    assert none_traded["per_value"] is None
    assert none_traded["message"] == ("조정 가능한 값 4개(규칙 1 · 포지션 3) · 거래 0건입니다. "
                                      "거래가 없어 값 하나당 거래 수를 계산하지 않았습니다.")
    bare = {k: None for k in POSITION} | {"amount": 1_000_000}
    nothing = freedom.disclose("custom", {"entry": {"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}}, bare, trades=12)
    assert (nothing["count"], nothing["per_value"]) == (0, None)
    assert nothing["message"] == "조정 가능한 값이 없습니다(규칙 0 · 포지션 0). 거래는 12건입니다."


def test_unknown_trades_are_not_zero():
    out = freedom.disclose("opening_range_breakout", {}, POSITION, trades=None)
    assert out["per_value"] is None and out["trades"] is None
    assert out["message"] == "조정 가능한 값 4개(규칙 1 · 포지션 3) · 거래 수는 알 수 없습니다."


def test_the_disclosure_says_which_question_it_answers():
    """어떤 물음에 답했는지 먼저 밝힌다(CLAUDE.md §2) — 표현력 · 예측력 · 경제적 가치의 물음이 아니라 셈의 물음이다."""
    out = freedom.disclose("opening_range_breakout", {}, POSITION, trades=20)
    assert out["question"] == "이 결과를 낸 설정에 조정 가능한 값은 몇 개이고 값 하나당 거래는 몇 건인가"
    assert not any(w in out["question"] for w in ("충분", "부족", "과적합", "예측", "수익"))


def test_the_sentences_describe_and_do_not_judge():
    """기술일 뿐 기준이 아니다 — 충분 · 부족 · 과적합 같은 판정 낱말이 없다 · 근거 문장은 무엇을 세고 무엇을 세지 않는지 말한다."""
    out = freedom.disclose("rsi_reversal", {}, POSITION, trades=7)
    for text in (out["message"], out["basis"], out["limit"]):
        assert not any(w in text for w in ("충분", "부족", "과적합", "위험합니다", "권", "추천"))
        assert text.endswith("니다.")
    assert "진입 금액" in out["basis"] and "비용 가정" in out["basis"] and "기본값" in out["basis"]
    assert "관문의 상태를 바꾸지 않습니다" in out["limit"]
