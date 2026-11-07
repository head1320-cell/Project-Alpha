"""KRX·DART·KIS 집계 매크로 계열 + 주기 혼합 규칙 (P4-D2).

왜 이 파일이 있는가
------------------------------------------------------------------------------
P4 계획 초안은 KRX/DART/KIS 종목 데이터를 집계해 매크로로 쓴다고 적으면서 **주기를
어떻게 맞출지 적지 않았다.** 실측으로 확인했다 — 수집기에 리샘플 정책이 없다
(`"frequency": "m"` 은 FRED 서버측 집계뿐).

일간(신용잔고·시장폭·수급) · 분기(DART 재무) · 월간(ECOS·FRED)이 한 인덱스에
섞이는데, 월말 `ffill` 로 뭉개면 일간 계열의 고주파 엣지가 통째로 죽는다.

★원칙은 `ffill` 금지가 아니라 "ffill 한 값을 그 달의 관측인 척하지 않는다" 다★
분기 데이터를 채운 달은 `stale_months > 0` 을 달고, 모델과 화면이 그걸 보고
다르게 다룰 수 있게 한다. MIDAS 까지는 가지 않는다 — 240관측에 MIDAS 는 또 하나의
과적합 기계다(A8 이 4상태 HMM 을 기각한 것과 같은 이유).

★이 컨테이너에는 집계 원천이 없다★ `daily_prices` · `investor_flows` 두 테이블이
모두 존재하지 않는다(실측). 그래서 DB 경로에서 이 파일이 지키는 것은 "값이 맞다" 가
아니라 **"없으면 없다고 답한다"** 이고, 규칙 자체는 합성 입력으로 정확히 잰다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.macro_derived import (  # noqa: E402
    Aggregation,
    MonthlyPoint,
    derived_series_specs,
    momentum,
    to_monthly,
)

# 2개월치 일간 관측 — 1월은 상승 추세, 2월은 급등 후 되돌림(월중 최대가 평균과 다르다)
_DAILY = [
    ("2026-01-05", 10.0), ("2026-01-12", 12.0), ("2026-01-19", 14.0), ("2026-01-26", 16.0),
    ("2026-02-02", 20.0), ("2026-02-09", 60.0), ("2026-02-16", 20.0), ("2026-02-23", 20.0),
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 일간 → 월간: 평균이지 마지막 값이 아니다
# ─────────────────────────────────────────────────────────────────────────────
def test_daily_downsamples_to_the_month_mean_not_the_last_observation():
    """★마지막 값을 쓰면 월말 하루의 노이즈가 그 달 전체를 대표한다★

    흔하고 편한 선택이지만 틀렸다. 2월은 마지막 값 20 · 평균 30 으로 갈린다.
    """
    out = to_monthly(_DAILY, how=Aggregation.MEAN)
    got = {p.period: p.value for p in out}
    assert got["202601"] == pytest.approx(13.0)   # (10+12+14+16)/4
    assert got["202602"] == pytest.approx(30.0)   # (20+60+20+20)/4 — 마지막 값 20 이 아니다


def test_risk_series_also_carry_the_month_max_because_the_mean_erases_the_tail():
    """★평균이 꼬리를 지운다★ 변동성·스프레드는 월중 최대를 함께 봐야 한다.

    2월 평균 30 은 60 이라는 사건이 있었다는 사실을 말해 주지 않는다.
    """
    out = {p.period: p.value for p in to_monthly(_DAILY, how=Aggregation.MAX)}
    assert out["202602"] == pytest.approx(60.0)
    assert out["202601"] == pytest.approx(16.0)


def test_months_with_no_observation_produce_no_point():
    """★관측이 없는 달을 0 으로 채우지 않는다★ `0` 과 `미관측` 은 다른 사실이다."""
    sparse = [("2026-01-05", 10.0), ("2026-03-05", 30.0)]   # 2월 없음
    periods = [p.period for p in to_monthly(sparse, how=Aggregation.MEAN)]
    assert periods == ["202601", "202603"], "빈 달이 값으로 채워졌다"


def test_daily_aggregates_are_never_marked_stale():
    """짝 — 그 달에 실제 관측이 있으므로 `stale_months` 는 0 이다."""
    assert all(p.stale_months == 0 for p in to_monthly(_DAILY, how=Aggregation.MEAN))


# ─────────────────────────────────────────────────────────────────────────────
# 2. ★분기 → 월간: ffill 은 허용하되 그 사실을 값과 함께 낸다★
# ─────────────────────────────────────────────────────────────────────────────
_QUARTERLY = [("2026-02-15", 100.0), ("2026-05-15", 130.0)]


def test_quarterly_forward_fill_marks_how_many_months_it_was_carried():
    """★이 파일의 핵심★

    `ffill` 자체가 금지가 아니다 — 금지는 **채운 값을 그 달의 관측인 척하는 것**이다.
    공표월은 `stale_months == 0`, 그 뒤 채운 달은 1, 2 … 로 늘어난다. 모델과 화면이
    이 숫자를 보고 다르게 다룰 수 있어야 저빈도 데이터를 정직하게 섞을 수 있다.
    """
    out = {p.period: p for p in to_monthly(_QUARTERLY, how=Aggregation.LAST_WITH_STALENESS,
                                           fill_until="2026-06")}
    assert out["202602"].stale_months == 0, "공표월인데 stale 로 표시됐다"
    assert out["202603"].stale_months == 1
    assert out["202604"].stale_months == 2
    assert out["202605"].stale_months == 0, "새 공표월인데 stale 이 안 초기화됐다"
    assert out["202606"].stale_months == 1


def test_forward_filled_months_carry_the_last_published_value():
    """짝 — staleness 만 맞고 값이 틀리면 소용없다."""
    out = {p.period: p.value for p in to_monthly(_QUARTERLY, how=Aggregation.LAST_WITH_STALENESS,
                                                 fill_until="2026-06")}
    assert out["202603"] == pytest.approx(100.0)
    assert out["202604"] == pytest.approx(100.0)
    assert out["202605"] == pytest.approx(130.0)


def test_forward_fill_does_not_run_past_the_requested_horizon():
    """짝 — 무한히 끌지 않는다. 끝을 안 정하면 죽은 값이 영원히 최신인 척한다."""
    periods = [p.period for p in to_monthly(_QUARTERLY, how=Aggregation.LAST_WITH_STALENESS,
                                            fill_until="2026-03")]
    assert periods[-1] == "202603"


# ─────────────────────────────────────────────────────────────────────────────
# 3. 모멘텀은 **별도 계열**이다 — 평균 계열을 덮지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_momentum_is_a_separate_series_and_needs_a_full_lookback():
    """★일간의 고주파 엣지를 살리는 방법★

    월중 평균만 남기면 "얼마나 빨리 변하고 있는가" 가 사라진다. 그래서 평균 계열
    옆에 모멘텀 계열을 따로 둔다 — 같은 자리에서 값을 바꿔치기하지 않는다.
    되돌아볼 구간이 모자란 앞부분은 **값을 만들지 않는다.**
    """
    monthly = [MonthlyPoint(p, v) for p, v in
               [("202601", 10.0), ("202602", 11.0), ("202603", 12.0), ("202604", 13.2)]]
    mom = momentum(monthly, months=3)
    assert [p.period for p in mom] == ["202604"], "룩백이 모자란 달에 값을 만들었다"
    assert mom[0].value == pytest.approx(32.0)   # 13.2/10 − 1 = +32%


def test_momentum_refuses_to_divide_by_a_zero_base():
    """0 기준의 변화율은 정의되지 않는다 — 무한대를 내지 말고 그 달을 건너뛴다."""
    monthly = [MonthlyPoint(p, v) for p, v in
               [("202601", 0.0), ("202602", 1.0), ("202603", 2.0), ("202604", 3.0)]]
    assert momentum(monthly, months=3) == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. 계열 선언 — 규칙 없는 계열이 없다
# ─────────────────────────────────────────────────────────────────────────────
def test_every_derived_series_declares_its_downsampling_rule():
    """★규칙을 안 적은 계열이 하나라도 있으면 그 계열은 조용히 뭉개진다★"""
    specs = derived_series_specs()
    assert len(specs) >= 6, f"파생 계열이 {len(specs)}개 — 확장이 안 됐다"
    for s in specs:
        assert isinstance(s.how, Aggregation), f"{s.key}: 집계 규칙이 없다"
        assert s.source_freq in ("daily", "quarterly"), f"{s.key}: 원 주기가 없다"
        assert s.reason_when_missing, f"{s.key}: 원천이 없을 때 뭐라 할지 안 적혀 있다"


def test_daily_series_that_want_momentum_declare_a_companion_key():
    """모멘텀 계열은 원계열과 **다른 키**를 갖는다 — 같은 키에 다른 뜻을 넣지 않는다."""
    specs = {s.key: s for s in derived_series_specs()}
    withmom = [s for s in specs.values() if s.momentum_key]
    assert withmom, "모멘텀을 내는 계열이 하나도 없다 — 고주파 엣지가 통째로 죽는다"
    for s in withmom:
        assert s.momentum_key != s.key
        assert s.source_freq == "daily", "월간·분기 계열에 3개월 모멘텀은 뜻이 약하다"


# ─────────────────────────────────────────────────────────────────────────────
# 5. ★원천이 없으면 없다고 답한다 — 합성 0건★
# ─────────────────────────────────────────────────────────────────────────────
def test_collection_reports_unavailable_with_a_reason_when_the_source_table_is_missing():
    """★이 컨테이너의 실제 상태다★ `daily_prices` · `investor_flows` 가 없다.

    없는 것을 0 으로 채우면 화면은 "시장폭이 0" 으로 읽는다. 없으면 없다고 적는다.
    """
    from src.data.macro_derived import collect_derived_macro
    out = collect_derived_macro()
    assert out, "결과가 비었다 — 키는 값이 없어도 존재해야 한다(M1-S 계약)"
    for key, block in out.items():
        if not block["available"]:
            assert block.get("reason"), f"{key}: 미가용인데 사유가 없다"
            assert block.get("value") is None, f"{key}: 미가용인데 값을 냈다"


def test_collection_covers_every_declared_series():
    """짝 — 선언만 하고 수집 경로에 안 붙은 계열이 없다."""
    from src.data.macro_derived import collect_derived_macro
    out = collect_derived_macro()
    for s in derived_series_specs():
        assert s.key in out, f"{s.key}: 선언됐는데 수집 결과에 없다"
