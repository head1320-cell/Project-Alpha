"""네 축을 하나의 판정으로 — `run_evidence.pit_evidence`

로드맵 0단계의 **완료 판정**은 "한 곳에서 넷을 동시에 읽는다" 이다. 이 모듈이
그 넷을 모아 화면의 배지 하나가 읽을 값을 만든다.

## ★boolean 을 만들지 않는다★

기존 `is_pit_verified` 컬럼은 참/거짓 둘뿐이라 **"검증됨" 과 "확인하지 못함" 을
구별할 수 없다.** (그리고 실제로 그 컬럼을 쓰는 코드가 없어 모든 실행이 항상
"PIT 미검증" 이었다.) 그래서 축마다 `ok`/`degraded`/`unknown` 을 남기고 그 위에
네 상태를 얹는다:

    verified     적용되는 축이 전부 `ok`
    partial      일부만 `ok`
    unverified   `ok` 가 없고 **관측된 결함**이 있다
    unknown      `ok` 도 관측된 결함도 없다 — 못 쟀다

## 축 넷

    price          항상 적용된다 — 모든 백테스트가 가격을 쓴다
    universe       항상 적용된다 — 종목 목록은 언제나 있다
    macro          매크로 토큰을 쓴 실행에만 (안 쓰면 `None` = 해당 없음)
    fundamentals   PIT 재무 토큰을 쓴 실행에만

★필수 축은 값이 없어도 사라지지 않는다★ — 측정에 실패하면 `unknown` 으로 **남는다.**
빠지면 "가격을 못 쟀다" 가 "가격은 문제없다" 로 둔갑한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.run_evidence import (  # noqa: E402
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    is_pit_verified_flag,
    pit_evidence,
)

CLEAN_PRICE = {"state": "ok", "reason": None}
DIRTY_PRICE = {"state": "degraded", "reason": "가격 정의 혼합(1종목)"}
FOGGY_PRICE = {"state": "unknown", "reason": "라벨 없음(2종목)"}

CORRECTED = {"survivorship": "corrected", "reason": None}
APPROXIMATED = {"survivorship": "approximated", "reason": "근사 재구성입니다"}
UNCORRECTED = {"survivorship": "not_corrected", "reason": "오늘 기준 프리셋입니다"}
UNKNOWN_UV = {"survivorship": "unknown", "reason": "사용자 목록입니다"}


def _ev(**kw):
    base = {"price_basis": CLEAN_PRICE, "universe": CORRECTED,
            "macro_lookahead": None, "fundamentals_pit": None}
    base.update(kw)
    return pit_evidence(**base)


# ═══════════════════════════════════════════════════════════════════════════
# ㉑㉒㉓ 상태 판정
# ═══════════════════════════════════════════════════════════════════════════

def test_all_clean_is_verified():
    out = _ev()
    assert out["status"] == STATUS_VERIFIED, out
    assert out["broken_axes"] == [], out


def test_one_degraded_axis_makes_it_partial():
    out = _ev(universe=UNCORRECTED)
    assert out["status"] == STATUS_PARTIAL, out
    assert out["broken_axes"] == ["universe"], out
    assert out["ok_axes"] == ["price"], out


def test_every_axis_degraded_is_unverified():
    out = _ev(price_basis=DIRTY_PRICE, universe=UNCORRECTED)
    assert out["status"] == STATUS_UNVERIFIED, out
    assert out["ok_axes"] == [], out


def test_nothing_measurable_is_unknown_not_unverified():
    """★못 잰 것과 재서 나쁜 것은 다른 답이다★"""
    out = _ev(price_basis=FOGGY_PRICE, universe=UNKNOWN_UV)
    assert out["status"] == STATUS_UNKNOWN, out


# ═══════════════════════════════════════════════════════════════════════════
# ㉔ ★미상은 ok 로 세지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unknown_axis_never_counts_as_ok():
    out = _ev(price_basis=FOGGY_PRICE)
    assert out["status"] != STATUS_VERIFIED, out
    assert "price" not in out["ok_axes"], out
    assert out["axes"]["price"]["state"] == AXIS_UNKNOWN, out


def test_a_known_defect_outranks_an_unknown_one_in_the_verdict():
    """`degraded` 하나가 있으면 `unverified` 이지 `unknown` 이 아니다."""
    out = _ev(price_basis=DIRTY_PRICE, universe=UNKNOWN_UV)
    assert out["status"] == STATUS_UNVERIFIED, out


# ═══════════════════════════════════════════════════════════════════════════
# ㉕ 해당 없음과 필수 축
# ═══════════════════════════════════════════════════════════════════════════

def test_macro_and_fundamentals_are_optional():
    """★안 쓴 축은 분모에서 빠진다★ 매크로를 안 쓴 전략에 매크로 결함은 없다."""
    out = _ev()
    assert out["axes"]["macro"] is None, out
    assert out["axes"]["fundamentals"] is None, out
    assert out["applicable"] == ["price", "universe"], out
    assert out["status"] == STATUS_VERIFIED, out


def test_price_and_universe_are_never_optional():
    """★필수 축은 빠지지 않는다★ 못 재면 `unknown` 으로 남는다.

    빠뜨리면 "가격을 못 쟀다" 가 "가격은 문제없다" 로 둔갑하고, 남은 축 하나가
    깨끗하다는 이유로 실행 전체가 `verified` 가 된다.
    """
    out = pit_evidence(price_basis=None, universe=None,
                       macro_lookahead=None, fundamentals_pit=None)
    assert out["axes"]["price"]["state"] == AXIS_UNKNOWN, out
    assert out["axes"]["universe"]["state"] == AXIS_UNKNOWN, out
    assert out["status"] == STATUS_UNKNOWN, out
    assert out["axes"]["price"]["reason"], "사유 없는 미상"


def test_a_missing_price_measurement_cannot_be_verified():
    """★짝★ 유니버스만 깨끗하다고 실행 전체가 검증되지 않는다."""
    out = pit_evidence(price_basis=None, universe=CORRECTED,
                       macro_lookahead=None, fundamentals_pit=None)
    assert out["status"] == STATUS_PARTIAL, out
    # ★못 잰 축은 `broken` 이 아니라 `unknown` 이다★ — 둘을 합치면 "재봤더니
    # 나쁘다" 와 "못 쟀다" 가 같은 칸에 들어가고, 처방이 다른데 구별이 사라진다.
    assert "price" in out["unknown_axes"], out
    assert out["broken_axes"] == [], out


# ═══════════════════════════════════════════════════════════════════════════
# 매크로·재무 축의 번역 — ★어휘를 새로 만들지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_macro_all_pit_is_ok():
    out = _ev(macro_lookahead={"pit": 3, "live": 0, "blocked": 0, "pit_pct": 100.0})
    assert out["axes"]["macro"]["state"] == AXIS_OK, out
    assert out["status"] == STATUS_VERIFIED, out


def test_macro_with_a_live_token_is_degraded():
    """★그것이 룩어헤드다★"""
    out = _ev(macro_lookahead={"pit": 2, "live": 1, "blocked": 0, "pit_pct": 66.7})
    assert out["axes"]["macro"]["state"] == AXIS_DEGRADED, out
    assert "룩어헤드" in out["axes"]["macro"]["reason"], out


def test_macro_only_blocked_is_unknown():
    """평가되지 못한 토큰뿐이면 룩어헤드 여부를 **판정할 수 없다**."""
    out = _ev(macro_lookahead={"pit": 0, "live": 0, "blocked": 2, "pit_pct": 0.0})
    assert out["axes"]["macro"]["state"] == AXIS_UNKNOWN, out


def test_fundamentals_all_measured_is_ok():
    out = _ev(fundamentals_pit={"measured": 10, "estimated": 0, "unknown": 0,
                                "measured_pct": 100.0, "tickers": {}})
    assert out["axes"]["fundamentals"]["state"] == AXIS_OK, out


def test_fundamentals_with_estimates_is_degraded():
    out = _ev(fundamentals_pit={"measured": 5, "estimated": 5, "unknown": 0,
                                "measured_pct": 50.0, "tickers": {}})
    assert out["axes"]["fundamentals"]["state"] == AXIS_DEGRADED, out


def test_fundamentals_unknown_only_is_unknown():
    out = _ev(fundamentals_pit={"measured": 0, "estimated": 0, "unknown": 7,
                                "measured_pct": 0.0, "tickers": {}})
    assert out["axes"]["fundamentals"]["state"] == AXIS_UNKNOWN, out


def test_fundamentals_with_nothing_counted_is_unknown():
    """재무가 아예 없는 종목뿐인 실행 — 0/0 을 100% 로 읽지 않는다."""
    out = _ev(fundamentals_pit={"measured": 0, "estimated": 0, "unknown": 0,
                                "measured_pct": None,
                                "tickers": {"no_financials": 4}})
    assert out["axes"]["fundamentals"]["state"] == AXIS_UNKNOWN, out


# ═══════════════════════════════════════════════════════════════════════════
# ㉗ ★강등이지 삭제가 아니다★ — 사유가 남는다
# ═══════════════════════════════════════════════════════════════════════════

def test_every_non_ok_axis_carries_a_reason():
    out = _ev(price_basis=DIRTY_PRICE, universe=APPROXIMATED,
              macro_lookahead={"pit": 0, "live": 2, "blocked": 0, "pit_pct": 0.0},
              fundamentals_pit={"measured": 0, "estimated": 3, "unknown": 0,
                                "measured_pct": 0.0, "tickers": {}})
    for name, axis in out["axes"].items():
        if axis and axis["state"] != AXIS_OK:
            assert axis["reason"], f"{name} 축에 사유가 없다"


def test_the_summary_names_the_broken_axes():
    """화면 툴팁이 읽을 한 문장 — ★어디를 봐야 하는지 말한다★"""
    out = _ev(universe=UNCORRECTED)
    assert "유니버스" in out["summary"], out["summary"]


def test_a_verified_run_says_what_it_does_not_claim():
    """★결론은 증거보다 강할 수 없다★ `verified` 도 값 축까지 보증하지 않는다."""
    out = _ev()
    assert out["note"], "검증됨에 단서가 없다"


# ═══════════════════════════════════════════════════════════════════════════
# ㉚ 저장 컬럼으로의 번역
# ═══════════════════════════════════════════════════════════════════════════

def test_the_stored_flag_is_true_only_for_verified():
    assert is_pit_verified_flag(STATUS_VERIFIED) is True
    assert is_pit_verified_flag(STATUS_PARTIAL) is False
    assert is_pit_verified_flag(STATUS_UNVERIFIED) is False


def test_the_stored_flag_is_none_when_unknown():
    """★미상은 거짓이 아니다★ 컬럼이 3-값(NULL 포함)이라 그대로 쓸 수 있다."""
    assert is_pit_verified_flag(STATUS_UNKNOWN) is None
    assert is_pit_verified_flag(None) is None


# ═══════════════════════════════════════════════════════════════════════════
# 4단계 — ★제외했다고 검증된 것이 아니다★
#
# `price_basis_policy="exclude"` 는 정의가 섞인 티커를 백테스트에서 뺀다.
# 그러면 **남은** 계열은 깨끗하다. 그래도 가격 축을 `ok` 로 올리지 않는다:
#
#   · 데이터가 고쳐진 것이 아니라 **유니버스가 줄었다**
#   · 30종목을 조용히 버린 실행에 "검증됨" 배지를 다는 것이 CLAUDE.md 가
#     금지한 *"동등 품질로 위장"* 이다
#
# 그래서 두 정책 다 `degraded` 이되 **사유가 다르다** — 고치는 사람이 무엇을
# 해야 하는지가 다르기 때문이다(정책을 바꾼다 vs 데이터를 적재한다).
# ═══════════════════════════════════════════════════════════════════════════

def _rollup(policy: str):
    """엔진이 실제로 내는 모양 그대로 만든다 — 손으로 지어내지 않는다."""
    from src.data.price_quality import (
        BASIS_MIXED,
        BASIS_UNIFORM_ADJUSTED,
        STATE_ADJUSTED,
    )
    from src.kis_backtest_engine import _price_basis_meta
    labels = {"basis": {"a": BASIS_UNIFORM_ADJUSTED, "b": BASIS_MIXED},
              "adj": {"a": STATE_ADJUSTED, "b": STATE_ADJUSTED}}
    excluded = {"b": "price_basis=mixed"} if policy == "exclude" else {}
    return _price_basis_meta(labels, policy, excluded)


def test_excluding_does_not_promote_the_price_axis_to_ok():
    out = pit_evidence(price_basis=_rollup("exclude"), universe=CORRECTED,
                       macro_lookahead=None, fundamentals_pit=None)
    assert out["axes"]["price"]["state"] == AXIS_DEGRADED, out["axes"]["price"]
    assert out["status"] != STATUS_VERIFIED, out["status"]


def test_the_two_policies_give_different_reasons():
    """★사유가 같으면 무엇을 고쳐야 할지 알 수 없다★"""
    excluded = pit_evidence(price_basis=_rollup("exclude"), universe=CORRECTED,
                            macro_lookahead=None, fundamentals_pit=None)
    passed = pit_evidence(price_basis=_rollup("pass_labeled"), universe=CORRECTED,
                          macro_lookahead=None, fundamentals_pit=None)
    a = excluded["axes"]["price"]["reason"]
    b = passed["axes"]["price"]["reason"]
    assert a and b, (a, b)
    assert a != b, "제외한 실행과 섞인 채 돈 실행의 사유가 같다"
    assert "제외" in a, a
    assert "제외" not in b, b


def test_a_run_with_no_mixed_tickers_is_ok_under_either_policy():
    """★짝★ 정책이 항상 강등시키는 구현을 배제한다."""
    from src.data.price_quality import BASIS_UNIFORM_ADJUSTED, STATE_ADJUSTED
    from src.kis_backtest_engine import _price_basis_meta
    labels = {"basis": {"a": BASIS_UNIFORM_ADJUSTED},
              "adj": {"a": STATE_ADJUSTED}}
    for policy in ("exclude", "pass_labeled"):
        meta = _price_basis_meta(labels, policy, {})
        out = pit_evidence(price_basis=meta, universe=CORRECTED,
                           macro_lookahead=None, fundamentals_pit=None)
        assert out["axes"]["price"]["state"] == AXIS_OK, (policy, out["axes"]["price"])
        assert out["status"] == STATUS_VERIFIED, (policy, out["status"])
