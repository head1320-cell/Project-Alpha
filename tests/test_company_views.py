"""기업 → 뷰 다리 — ★밸류에이션이 화면에만 있고 배분에 닿지 않았다★ (S4)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md` §2.2
선행: S1 스토어(`da39c27`) · S2 `decide()`(`2b963b4`) · S3 라우트 위임(`72ecc5a`)

## ★실측이 스펙 원안을 세 번 뒤집었다★

mock 3종에 `valuation_distribution_for` 를 돌려 본 결과:

1. **단위가 맞지 않는다** — 밸류에이션 갭은 호라이즌이 없는 **총 갭**(−49% · +211%
   · −46%)인데 뷰의 `magnitude_pct` 는 **연간**이다. 그대로 넘기면 "연 211%
   기대수익" 으로 읽혀 BL 사후를 지배한다(S2 의 `_bps` 결함과 같은 종류).
2. **`price_percentile` 은 포화한다** — 셋 다 정확히 0.0/100.0(가격이 분포 밖).
   그래서 신뢰도는 갭과 폭을 **함께** 쓰는 표준화 갭 `z` 로 만든다.
3. **이 재무는 backtest_eligible 이 될 수 없다** — `publication_dates()` 가 이미
   `has_vintage: False` 라고 적어 뒀다. 그래서 `as_of` 가 오면 뷰를 내지 않는다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.engine.company_views as cv  # noqa: E402

CODE = "005930"
PRICE = 70_000.0


def _dist(p10: float, p50: float, p90: float, *, years: int = 10,
          is_mock: bool = True, name: str = "테스트전자") -> dict:
    """분포 산출을 **주입**한다 — 실산출은 포화 구간에만 있어 비포화를 못 본다."""
    return {"available": True, "corp_name": name, "is_mock": is_mock,
            "base_assumptions": {"years": years},
            "unified": {"available": True, "p10": p10, "p50": p50, "p90": p90}}


@pytest.fixture
def inject(monkeypatch):
    """코드 → 분포 맵을 심는다."""
    def _apply(by_code: dict[str, dict]):
        monkeypatch.setattr(
            "src.engine.valuation.valuation_distribution.valuation_distribution_for",
            lambda code, price, **kw: by_code[str(code)])
    return _apply


def _one(views: list[dict], code: str = CODE) -> dict:
    got = [v for v in views if v["assets"] == [code]]
    assert len(got) == 1, f"{code} 뷰가 {len(got)}개"
    return got[0]


# ══════════════════════════════════════════════════════════════════════════
# C1 방향
# ══════════════════════════════════════════════════════════════════════════
def test_a_cheap_stock_gets_an_upward_view(inject):
    inject({CODE: _dist(90_000, 100_000, 110_000)})       # p50 > price → 저평가
    views, _ = cv.company_views([CODE], {CODE: PRICE})
    assert _one(views)["direction"] == 1


def test_an_expensive_stock_gets_a_downward_view(inject):
    """★짝★ 항상 +1 을 내는 구현을 배제한다."""
    inject({CODE: _dist(30_000, 35_000, 40_000)})         # p50 < price → 고평가
    views, _ = cv.company_views([CODE], {CODE: PRICE})
    assert _one(views)["direction"] == -1


# ══════════════════════════════════════════════════════════════════════════
# C2·C3 ★크기는 연율이다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_longer_horizon_spreads_the_same_gap_thinner(inject):
    """같은 갭이라도 수렴 기간이 길면 **연간** 크기는 작아진다."""
    inject({CODE: _dist(90_000, 105_000, 120_000)})
    short, _ = cv.company_views([CODE], {CODE: PRICE}, convergence_years=2)
    long_, _ = cv.company_views([CODE], {CODE: PRICE}, convergence_years=8)
    assert _one(short)["magnitude_pct"] > _one(long_)["magnitude_pct"] > 0


def test_the_magnitude_is_annualized_not_the_raw_gap(inject):
    """★100배 방어★ 실측 갭 −49.2% 를 H=10 으로 펴면 약 −6.56%/yr 다.

    원시 갭(49.2)을 그대로 넘기면 "연 49% 하락 전망" 이 되어 BL 사후를 지배한다 —
    S2 가 `benefit_bps` 로 치를 뻔한 바로 그 오류의 같은 계열이다.
    """
    inject({CODE: _dist(30_297, 35_534, 41_914, years=10)})
    v = _one(cv.company_views([CODE], {CODE: PRICE})[0])
    assert v["direction"] == -1
    assert v["magnitude_pct"] == pytest.approx(6.56, abs=0.05), v["magnitude_pct"]
    assert v["horizon_years"] == 10
    assert v["total_gap_pct"] == pytest.approx(-49.24, abs=0.05)
    assert v["measured"] is False


# ══════════════════════════════════════════════════════════════════════════
# C4·C5 신뢰도
# ══════════════════════════════════════════════════════════════════════════
def test_confidence_rises_with_the_standardized_gap(inject):
    """★비포화 구간★ 같은 폭에서 갭이 클수록 신뢰도가 높다."""
    wide = {"a": _dist(80_000, 100_000, 120_000),      # half=20,000
            "b": _dist(65_000, 85_000, 105_000)}       # half=20,000
    inject(wide)
    views, _ = cv.company_views(["a", "b"], {"a": 95_000.0, "b": 95_000.0})
    ca = _one(views, "a")["confidence"]                # z = 5,000/20,000 = 0.25
    cb = _one(views, "b")["confidence"]                # z = −10,000/20,000 = −0.5
    assert 0 < ca < cb < cv.MAX_CONFIDENCE
    assert _one(views, "a")["confidence_saturated"] is False


def test_confidence_never_exceeds_the_repo_cap(inject):
    """★상한★ `_CONDITIONAL_MAX_CONFIDENCE` 와 같은 이유 — 뷰가 사용자 뷰보다
    세질 수 없다. 그리고 포화를 숨기지 않는다."""
    inject({CODE: _dist(30_297, 35_534, 41_914)})      # |z| ≈ 5.9
    v = _one(cv.company_views([CODE], {CODE: PRICE})[0])
    assert v["confidence"] == cv.MAX_CONFIDENCE
    assert v["confidence_saturated"] is True


def test_the_real_mock_universe_saturates_and_says_so():
    """★주입이 아니라 실산출★ mock 재무에서는 셋 다 포화한다 — E0 산물이라는
    사실 자체가 보고 대상이다."""
    codes = ["005930", "000660", "035420"]
    prices = {"005930": 70_000.0, "000660": 130_000.0, "035420": 200_000.0}
    views, reasons = cv.company_views(codes, prices, n=500)
    assert views, reasons
    assert all(v["confidence_saturated"] is True for v in views)
    assert all(v["is_mock"] is True for v in views)


# ══════════════════════════════════════════════════════════════════════════
# C6·C7·C11 ★내지 않는 경우 — 전부 사유가 있다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_zero_width_distribution_yields_no_view(inject):
    """폭이 0 이면 `z` 를 만들 수 없다 — 신뢰도를 지어내지 않는다."""
    inject({CODE: _dist(100_000, 100_000, 100_000)})
    views, reasons = cv.company_views([CODE], {CODE: PRICE})
    assert views == []
    assert reasons[CODE]["kind"] == cv.KIND_NO_WIDTH


def test_an_unavailable_distribution_yields_no_view(monkeypatch):
    monkeypatch.setattr(
        "src.engine.valuation.valuation_distribution.valuation_distribution_for",
        lambda code, price, **kw: {"available": False, "unified": None,
                                   "reason": "재무제표를 가져오지 못했습니다"})
    views, reasons = cv.company_views([CODE], {CODE: PRICE})
    assert views == []
    assert reasons[CODE]["kind"] == cv.KIND_NO_DISTRIBUTION
    assert "재무제표" in reasons[CODE]["reason"]


def test_an_out_of_range_magnitude_is_dropped_not_clamped(inject):
    """★조용히 조이지 않는다★ 상한으로 자르면 50%/yr 뷰가 '정상 뷰' 로 위장한다."""
    inject({CODE: _dist(190_000, 210_000, 230_000)})     # 갭 +200% · H=1
    views, reasons = cv.company_views([CODE], {CODE: PRICE}, convergence_years=1)
    assert views == []
    assert reasons[CODE]["kind"] == cv.KIND_OUT_OF_RANGE
    assert reasons[CODE]["magnitude_pct"] > cv.MAX_MAGNITUDE_PCT


def test_a_non_positive_fair_value_is_guarded_not_raised(inject):
    """★수치 안전★ `p50=0` 이면 `(1+gap)` 이 0 이라 분수승이 의미를 잃는다.

    적자기업 실데이터에서만 열리는 가지다 — mock 은 항상 흑자라 통과한다.
    """
    inject({CODE: _dist(-10_000, 0.0, 10_000)})
    views, reasons = cv.company_views([CODE], {CODE: PRICE})
    assert views == []
    assert reasons[CODE]["kind"] == cv.KIND_NON_POSITIVE_VALUE


def test_a_missing_price_yields_no_view(inject):
    inject({CODE: _dist(90_000, 100_000, 110_000)})
    views, reasons = cv.company_views([CODE], {})
    assert views == []
    assert reasons[CODE]["kind"] == cv.KIND_NO_PRICE


# ══════════════════════════════════════════════════════════════════════════
# C8 ★스키마는 매크로 뷰와 완전히 같다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_output_feeds_the_existing_row_builder_unchanged(inject):
    """새 P 빌더를 만들지 않았다는 증거 — 기존 `build_view_rows` 가 그대로 먹는다."""
    from src.engine.view_rows import KIND_ABSOLUTE, build_view_rows

    inject({"a": _dist(110_000, 120_000, 130_000),
            "b": _dist(80_000, 90_000, 100_000)})
    names = ["a", "b", "c"]
    views, _ = cv.company_views(names[:2], {"a": 100_000.0, "b": 100_000.0})
    rows, skipped = build_view_rows(views, names)

    assert skipped == [], skipped
    assert len(rows) == 2
    for r, i in zip(rows, (0, 1), strict=True):
        assert r.kind == KIND_ABSOLUTE
        assert list(r.row) == [1.0 if j == i else 0.0 for j in range(3)]
    assert rows[0].direction == 1 and rows[1].direction == -1


def test_the_confidence_reaches_omega_through_the_existing_builder(inject):
    """★짝★ 신뢰도가 실제로 Ω 에 닿는다 — 낮을수록 Ω 가 커진다(뷰가 약해진다)."""
    import numpy as np

    from src.engine.allocation_studio import build_user_views

    sigma = np.eye(2) * 0.04
    inject({"a": _dist(99_000, 101_000, 103_000)})       # 좁은 폭 · 작은 갭
    weak, _ = cv.company_views(["a"], {"a": 100_500.0})
    inject({"a": _dist(90_000, 120_000, 150_000)})       # 큰 갭 → 강한 뷰
    strong, _ = cv.company_views(["a"], {"a": 100_500.0})
    assert weak[0]["confidence"] < strong[0]["confidence"]

    om_weak = build_user_views(weak, ["a", "b"], sigma)[2]
    om_strong = build_user_views(strong, ["a", "b"], sigma)[2]
    assert om_weak[0][0] > om_strong[0][0]


# ══════════════════════════════════════════════════════════════════════════
# C9 ★등급은 파생한다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_research_usage_is_forward_only(inject):
    from src.data.pit_macro import ResearchUsage

    inject({CODE: _dist(90_000, 100_000, 110_000)})
    v = _one(cv.company_views([CODE], {CODE: PRICE})[0])
    assert v["research_usage"] == ResearchUsage.FORWARD_ONLY.value


def test_the_usage_is_derived_rather_than_written_by_hand(inject, monkeypatch):
    """★짝★ 손으로 적으면 게이트가 거짓말을 한다 — 파생기를 갈아끼우면 바뀐다."""
    from src.data.pit_macro import ResearchUsage

    monkeypatch.setattr("src.data.pit_macro.derive_usage",
                        lambda **kw: ResearchUsage.UNAVAILABLE)
    inject({CODE: _dist(90_000, 100_000, 110_000)})
    v = _one(cv.company_views([CODE], {CODE: PRICE})[0])
    assert v["research_usage"] == ResearchUsage.UNAVAILABLE.value


# ══════════════════════════════════════════════════════════════════════════
# C10 ★as_of 는 흉내낼 수 없다★
# ══════════════════════════════════════════════════════════════════════════
def test_asking_for_a_past_date_produces_no_views_at_all(inject):
    """밑단에 빈티지 재무가 없다 — 오늘 재무로 과거 뷰를 만들면 룩어헤드다."""
    inject({CODE: _dist(90_000, 100_000, 110_000)})
    views, reasons = cv.company_views([CODE], {CODE: PRICE}, as_of="2024-01-02")
    assert views == []
    assert reasons[CODE]["kind"] == cv.KIND_NO_VINTAGE
    assert "빈티지" in reasons[CODE]["reason"]


def test_without_as_of_the_same_input_does_produce_a_view(inject):
    """★짝★ 항상 거부하는 구현을 배제한다."""
    inject({CODE: _dist(90_000, 100_000, 110_000)})
    views, reasons = cv.company_views([CODE], {CODE: PRICE})
    assert len(views) == 1 and reasons == {}


# ══════════════════════════════════════════════════════════════════════════
# C12·C13 사유 맵과 라벨
# ══════════════════════════════════════════════════════════════════════════
def test_every_code_is_either_a_view_or_a_reason(inject):
    """★조용한 누락 금지★ 입력 코드 집합이 뷰∪사유 로 정확히 덮여야 한다."""
    inject({"a": _dist(90_000, 100_000, 110_000),
            "b": _dist(100_000, 100_000, 100_000),        # 폭 0
            "c": _dist(90_000, 100_000, 110_000)})        # 가격 없음
    codes = ["a", "b", "c"]
    views, reasons = cv.company_views(codes, {"a": 95_000.0, "b": 95_000.0})
    covered = {v["assets"][0] for v in views} | set(reasons)
    assert covered == set(codes)
    assert not ({v["assets"][0] for v in views} & set(reasons))


def test_the_mock_label_travels_with_the_view(inject):
    inject({CODE: _dist(90_000, 100_000, 110_000, is_mock=False)})
    assert _one(cv.company_views([CODE], {CODE: PRICE})[0])["is_mock"] is False
