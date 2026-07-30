"""Phase 6b — 팩터별 평가 주기(evaluation_frequency) 카탈로그 메타.

스펙 §8.1 요구 13(팩터 샘플링 주기 ↔ 리밸런싱 주기 충돌 경고)의 데이터 쪽 절반.
Phase 7 이 판정 함수(`timing_rules_v2.frequency_conflicts`)를 만들었지만 그 함수가 읽을
**팩터별 주기 메타가 카탈로그에 없었다** — 경고를 띄울 근거가 없으니 UI 만으로는 못 만든다.

★가장 중요한 테스트는 "주기 문자열이 판정 함수가 아는 값인가"★
`frequency_conflicts` 는 모르는 주기에 대해 경고를 **지어내지 않고** False 를 돌려준다
(정직한 설계). 그래서 카탈로그에 오타가 하나 있으면 그 팩터의 경고는 조용히 영원히 꺼진다.
"""
import pytest

from src.engine import timing_rules_v2 as v2
from src.engine.timing_factors import CATALOG, CATALOG_BY_ID, catalog

# 각 팩터가 **실제로 소비하는 데이터**의 주기. 월봉 프리미티브를 쓰면 month, 일봉이면 day.
EXPECTED = {
    "score_13612": "month",         # 1·3·6·12개월 수익률 가중합
    "abs_mom": "month",             # N개월 누적 수익률
    "avg_abs_momentum": "month",    # monthly_closes
    "accel_momentum": "month",      # 1·3·6개월 평균
    "ma_month": "month",            # 월봉 이동평균
    "ma_day": "day",                # 일봉 이동평균
    "disparity": "day",             # daily_closes
    "vol_breakout": "day",          # daily_ohlc
    "channel_breakout": "day",      # daily_ohlc
    "overnight_return": "overnight",  # 종가진입→익일시가청산
    "defense_first": "month",       # 13612 스코어(월봉)
    "indicator": "day",             # VIXCLS·DGS10 등 일간 매크로 시리즈
    "curve_slope": "day",           # T10Y2Y 일간
    # ── Phase 8 ──
    "relative_momentum": "month",   # monthly_closes 2종
    "breadth_above_ma": "day",      # daily_closes 바스켓
    "equal_vs_cap": "month",        # monthly_closes 2종
    "realized_vol": "day",          # daily_closes 수익률 표준편차
    "vol_regime": "day",            # daily_closes 단기/장기
    "target_vol_size": "day",       # realized_vol 파생
    "drawdown": "day",              # daily_closes 고점 대비
    "drawdown_speed": "day",        # daily_closes 창 비교
    "recovery_state": "day",        # daily_closes 저점→고점
    "rolling_correlation": "day",   # daily_closes_indexed 2종
}


def test_every_factor_declares_an_evaluation_frequency():
    missing = [c["id"] for c in CATALOG if not c.get("evaluation_frequency")]
    assert missing == [], f"주기 메타가 없는 팩터: {missing} — 그 팩터는 충돌 경고를 못 띄운다"


@pytest.mark.parametrize("fid,freq", sorted(EXPECTED.items()))
def test_declared_frequency_matches_the_data_the_factor_consumes(fid, freq):
    assert CATALOG_BY_ID[fid]["evaluation_frequency"] == freq


def test_expected_map_covers_the_whole_catalogue():
    """카탈로그에 팩터가 추가되면 이 테스트가 먼저 깨져 주기 지정을 강제한다."""
    assert sorted(EXPECTED) == sorted(c["id"] for c in CATALOG)


def test_every_declared_frequency_is_one_the_judge_understands():
    """★오타 하나가 경고를 조용히 끈다★ — 판정 함수가 모르는 주기는 항상 '충돌 없음' 이다."""
    unknown = [c["id"] for c in CATALOG
               if c["evaluation_frequency"].lower() not in v2.FREQUENCY_RANKS]
    assert unknown == [], (
        f"frequency_conflicts 가 모르는 주기를 선언한 팩터: {unknown}. "
        "모르는 주기는 False(충돌 없음)로 떨어져 경고가 영원히 꺼진다."
    )


def test_catalog_endpoint_payload_exposes_the_frequency():
    """UI 가 경고를 띄우려면 카탈로그 응답에 실려 나와야 한다."""
    payload = catalog()
    seen = {f["id"]: f.get("evaluation_frequency")
            for g in payload["groups"] for f in g["factors"]}
    assert seen == EXPECTED


# ═══════════════════════════════════════════════════════════════════════════════
# 주기 등급표를 응답에 실어 보낸다 — TS 에 같은 표를 복제하지 않기 위해
# ═══════════════════════════════════════════════════════════════════════════════
def test_catalog_publishes_the_frequency_rank_table():
    """★등급표를 프론트에 복제하면 두 진실이 생기고 조용히 어긋난다★

    UI 는 등급을 하드코딩하지 않고 이 표를 받아서 비교한다. 파이썬 쪽 표가 바뀌면
    UI 판정도 같이 바뀐다.
    """
    assert catalog()["frequency_ranks"] == v2.FREQUENCY_RANKS


def test_published_rebalance_options_are_all_rankable():
    """★등급표에 없는 리밸런싱 값을 고르면 경고가 조용히 꺼진다★"""
    payload = catalog()
    ranks = payload["frequency_ranks"]
    bad = [o["id"] for o in payload["rebalance_options"] if o["id"] not in ranks]
    assert bad == [], f"등급을 매길 수 없는 리밸런싱 선택지: {bad} — 고르면 경고가 사라진다"


def test_rebalance_options_cover_the_timing_rule_default():
    """TimingRule 기본값(month_end)이 선택지에 없으면 UI 가 기본 상태를 표현할 수 없다."""
    ids = [o["id"] for o in catalog()["rebalance_options"]]
    assert "month_end" in ids


def test_as_of_requirement_reaches_the_catalogue_payload():
    """UI 는 이 플래그로 '카나리로 추가 불가' 를 표시한다 — 응답에 없으면 그 게이트가 사라진다.

    카나리 평가 경로 `evaluate(id, ticker, market, params)` 에는 시점을 넘길 자리가 없어서,
    as_of 기반 팩터를 규칙으로 추가하면 값이 영원히 없는(=늘 위험-오프) 규칙이 조용히 생긴다.
    """
    seen = {f["id"]: f.get("requires_as_of", False)
            for g in catalog()["groups"] for f in g["factors"]}
    assert seen["curve_slope"] is True
    assert [k for k, v in seen.items() if v] == ["curve_slope"], (
        "as_of 팩터가 늘어나면 UI 게이트도 함께 확인할 것"
    )


def test_as_of_factors_are_not_reachable_through_the_canary_evaluator():
    """★플래그와 실제 동작이 일치하는가★ — 평가되면 플래그가 거짓말이고, 그 반대도 문제다."""
    from src.engine.timing_factors import evaluate
    assert evaluate("curve_slope", "SPY", "kr", {}) is None


def test_rebalance_field_is_part_of_the_declared_schema():
    """충돌 판정의 다른 한쪽 — TimingRule 이 리밸런싱 주기를 갖고 있어야 한다."""
    assert "rebalance_or_holding_period" in catalog()["schema"]


# ═══════════════════════════════════════════════════════════════════════════════
# 실제 충돌 판정 — 카탈로그 메타를 그대로 먹여 본다
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("fid,rebalance,conflict", [
    ("ma_day", "month_end", True),           # 일간 신호를 월말에만 반영 → 대부분 버려진다
    ("ma_day", "day", False),
    ("avg_abs_momentum", "month_end", False),
    ("avg_abs_momentum", "day", True),       # 월간 신호를 일간 리밸런싱 → 같은 값 반복
    ("overnight_return", "day", False),      # 오버나이트는 일간과 같은 등급
    ("curve_slope", "month_end", True),
])
def test_catalogue_frequency_drives_the_conflict_verdict(fid, rebalance, conflict):
    freq = CATALOG_BY_ID[fid]["evaluation_frequency"]
    assert v2.frequency_conflicts(freq, rebalance) is conflict
