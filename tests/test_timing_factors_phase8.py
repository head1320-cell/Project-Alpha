"""Phase 8 — 카탈로그 확장 팩터 (스펙 §6 Phase-1 목록 중 2~6번).

★이 파일의 절반은 "퇴화한 시계열" 테스트다★
CLAUDE.md 의 수치 안전 규칙: 분수승·로그·제곱근·나눗셈에 음수나 0 이 들어갈 수 있으면 반드시
가드한다. 그리고 **그 버그는 실데이터에서만 터진다** — `KIS_USE_MOCK=1` 시계열은 항상 양수이고
우상향이라, 평평한 구간도 폭락 구간도 0 분산도 만들어 주지 않는다. 그래서 테스트가 직접
만들어 먹인다. 그러지 않으면 CI 는 영원히 초록이고 적자 국면에서 처음 터진다.

각 팩터에 대해 최소 세 가지를 고정한다:
  · 부호/방향 — 위험-온이 어느 쪽인지(카탈로그 default_direction 과 일치해야 한다)
  · 경계 — 0~1 이나 −1~1 같은 정의역을 벗어나지 않는지
  · 결측 — 데이터가 모자라면 0 이 아니라 **None**
"""
import pytest

from src.engine import timing_factors as tf

TK = "SPY"


def _flat(n=300, v=100.0):
    return [v] * n


def _rising(n=300, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


def _falling(n=300, start=300.0, step=1.0):
    return [max(start - i * step, 1.0) for i in range(n)]


def _patch_daily(monkeypatch, series_by_ticker: dict):
    """티커별 일간 종가를 지정. 없는 티커는 빈 리스트(결측)."""
    monkeypatch.setattr("src.data.etf_prices.daily_closes",
                        lambda t, m="kr", d=300: series_by_ticker.get(t, [])[-d:])


def _patch_monthly(monkeypatch, series_by_ticker: dict):
    monkeypatch.setattr("src.data.etf_prices.monthly_closes",
                        lambda t, m="kr", n=14: series_by_ticker.get(t, [])[-n:])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 상대 모멘텀
# ═══════════════════════════════════════════════════════════════════════════════
def test_relative_momentum_positive_when_asset_beats_benchmark(monkeypatch):
    _patch_monthly(monkeypatch, {"SPY": _rising(20), "AGG": _flat(20)})
    v = tf.relative_momentum(TK, "us", months=12, benchmark="AGG")
    assert v is not None and v > 0


def test_relative_momentum_negative_when_asset_lags(monkeypatch):
    _patch_monthly(monkeypatch, {"SPY": _flat(20), "AGG": _rising(20)})
    assert tf.relative_momentum(TK, "us", months=12, benchmark="AGG") < 0


def test_relative_momentum_none_when_benchmark_missing(monkeypatch):
    """벤치마크가 없으면 **자산 단독 수익률로 대체하지 않는다** — 그건 다른 팩터다."""
    _patch_monthly(monkeypatch, {"SPY": _rising(20)})
    assert tf.relative_momentum(TK, "us", months=12, benchmark="NOPE") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 브레드스 · 동일가중 vs 시총가중
# ═══════════════════════════════════════════════════════════════════════════════
def test_breadth_is_100_when_every_member_is_above_its_ma(monkeypatch):
    _patch_daily(monkeypatch, {"A": _rising(300), "B": _rising(300)})
    assert tf.breadth_above_ma(None, "us", days=200, basket=("A", "B")) == pytest.approx(100.0)


def test_breadth_is_0_when_every_member_is_below(monkeypatch):
    _patch_daily(monkeypatch, {"A": _falling(300), "B": _falling(300)})
    assert tf.breadth_above_ma(None, "us", days=200, basket=("A", "B")) == pytest.approx(0.0)


def test_breadth_counts_only_members_it_could_read(monkeypatch):
    """★읽지 못한 종목을 '이탈' 로 세면 안 된다★ 결측과 하락은 다른 사실이다."""
    _patch_daily(monkeypatch, {"A": _rising(300)})          # B 는 결측
    assert tf.breadth_above_ma(None, "us", days=200, basket=("A", "B")) == pytest.approx(100.0)


def test_breadth_none_when_nothing_readable(monkeypatch):
    _patch_daily(monkeypatch, {})
    assert tf.breadth_above_ma(None, "us", days=200, basket=("A", "B")) is None


def test_equal_vs_cap_positive_when_equal_weight_leads(monkeypatch):
    _patch_monthly(monkeypatch, {"RSP": _rising(20), "SPY": _flat(20)})
    assert tf.equal_vs_cap(None, "us", months=6, equal="RSP", cap="SPY") > 0


def test_equal_vs_cap_none_when_one_leg_missing(monkeypatch):
    """KR 시장엔 매핑된 동일가중 ETF 가 없다 — 지어내지 말고 None."""
    _patch_monthly(monkeypatch, {"SPY": _rising(20)})
    assert tf.equal_vs_cap(None, "kr", months=6, equal="RSP", cap="SPY") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 변동성 — ★0 분산 가드가 여기 산다★
# ═══════════════════════════════════════════════════════════════════════════════
def test_realized_vol_is_zero_for_a_flat_series(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _flat(100)})
    assert tf.realized_vol(TK, "us", days=20) == pytest.approx(0.0)


def test_realized_vol_is_positive_and_annualized(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": [100 * (1.01 if i % 2 else 0.99) for i in range(100)]})
    v = tf.realized_vol(TK, "us", days=20)
    assert v is not None and v > 0


def test_realized_vol_guards_non_positive_prices(monkeypatch):
    """★로그 수익률에 0·음수 가격이 들어가면 터진다★ 실데이터에만 나오는 조건이다."""
    _patch_daily(monkeypatch, {"SPY": [100.0, 0.0, -5.0, 100.0] * 25})
    v = tf.realized_vol(TK, "us", days=20)
    assert v is None or v >= 0.0, "음수/0 가격에서 예외나 NaN 이 새어나왔다"


def test_vol_regime_is_one_when_short_equals_long(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": [100 * (1.01 if i % 2 else 0.99) for i in range(300)]})
    v = tf.vol_regime(TK, "us", days=20, ref_days=250)
    assert v is not None and v == pytest.approx(1.0, abs=0.25)


def test_vol_regime_none_when_reference_vol_is_zero(monkeypatch):
    """★0 으로 나누지 않는다★ 평평한 기준 구간은 mock 에서 절대 안 나온다."""
    _patch_daily(monkeypatch, {"SPY": _flat(300)})
    assert tf.vol_regime(TK, "us", days=20, ref_days=250) is None


def test_target_vol_size_is_bounded_0_1(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": [100 * (1.05 if i % 2 else 0.95) for i in range(100)]})
    v = tf.target_vol_size(TK, "us", days=20, target_vol=10.0)
    assert v is not None and 0.0 <= v <= 1.0


def test_target_vol_size_is_full_when_market_is_dead_calm(monkeypatch):
    """실현변동성 0 → 목표/0 = 무한대. 상한 1.0 으로 잘린다(예외가 아니라)."""
    _patch_daily(monkeypatch, {"SPY": _flat(100)})
    assert tf.target_vol_size(TK, "us", days=20, target_vol=10.0) == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 낙폭 · 낙폭 속도 · 회복
# ═══════════════════════════════════════════════════════════════════════════════
def test_drawdown_is_zero_at_a_new_high(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _rising(300)})
    assert tf.drawdown(TK, "us", days=250) == pytest.approx(0.0)


def test_drawdown_is_negative_after_a_fall(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _rising(200) + _falling(50, start=299.0)})
    v = tf.drawdown(TK, "us", days=250)
    assert v is not None and v < 0, "고점 대비 하락인데 낙폭이 음수가 아니다"


def test_drawdown_never_below_minus_100(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _rising(100) + [0.01] * 10})
    v = tf.drawdown(TK, "us", days=250)
    assert v is not None and v >= -100.0


def test_drawdown_guards_a_non_positive_peak(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": [0.0] * 60})
    assert tf.drawdown(TK, "us", days=50) is None


def test_drawdown_speed_is_negative_while_falling(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _rising(200) + _falling(30, start=299.0)})
    v = tf.drawdown_speed(TK, "us", days=250, window=20)
    assert v is not None and v < 0


def test_drawdown_speed_is_zero_on_a_flat_series(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _flat(300)})
    assert tf.drawdown_speed(TK, "us", days=250, window=20) == pytest.approx(0.0)


def test_recovery_state_is_1_at_a_new_high(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _rising(300)})
    assert tf.recovery_state(TK, "us", days=250) == pytest.approx(1.0)


def test_recovery_state_is_bounded_0_1(monkeypatch):
    _patch_daily(monkeypatch, {"SPY": _rising(200) + _falling(50, start=299.0)})
    v = tf.recovery_state(TK, "us", days=250)
    assert v is not None and 0.0 <= v <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 롤링 상관 — ★날짜 정렬이 핵심★
# ═══════════════════════════════════════════════════════════════════════════════
def _patch_indexed(monkeypatch, by_ticker: dict):
    monkeypatch.setattr("src.data.etf_prices.daily_closes_indexed",
                        lambda t, m="kr", d=300: by_ticker.get(t, [])[-d:])


def _series(dates, vals):
    return list(zip(dates, vals))


def test_rolling_correlation_is_plus_one_for_identical_moves(monkeypatch):
    d = [f"2026-01-{i:02d}" for i in range(1, 31)]
    v = [100 + (i % 3) * 5 for i in range(30)]
    _patch_indexed(monkeypatch, {"SPY": _series(d, v), "TLT": _series(d, v)})
    assert tf.rolling_correlation(TK, "us", days=25, benchmark="TLT") == pytest.approx(1.0, abs=1e-6)


def test_rolling_correlation_is_minus_one_for_mirrored_moves(monkeypatch):
    d = [f"2026-01-{i:02d}" for i in range(1, 31)]
    a = [100 + (i % 3) * 5 for i in range(30)]
    b = [100 - (i % 3) * 5 for i in range(30)]
    _patch_indexed(monkeypatch, {"SPY": _series(d, a), "TLT": _series(d, b)})
    v = tf.rolling_correlation(TK, "us", days=25, benchmark="TLT")
    # ★정확히 −1 은 아니다★ 값을 대칭으로 만들어도 **퍼센트 수익률**은 기준이 서로 달라
    # (100→105 = +5%, 100→95 = −5%, 그러나 105→110 = +4.76%, 95→90 = −5.26%) 완전한 반대가
    # 되지 않는다. 실측 −0.9996. 의미 있는 주장은 "강하게 음수" 이므로 그렇게 적는다.
    assert v is not None and v < -0.95


def test_rolling_correlation_uses_only_overlapping_dates(monkeypatch):
    """★서로 다른 거래일은 짝지어지지 않는다★ 이 팩터의 존재 이유이자, 이 파일의 핵심 단언.

    ★처음 쓴 버전은 아무것도 검증하지 못했다★
    한쪽을 다른 쪽의 **접미사**(앞 4일이 없는 형태)로 만들었더니, 날짜를 무시하고 꼬리를
    zip 해도 우연히 정확히 맞아떨어졌다 — 날짜 조인을 naive zip 으로 바꾸는 뮤테이션이
    53개 테스트를 전부 통과했다. 휴장일은 **가운데**에 생기므로, 그렇게 구성해야 두 구현이
    갈린다. 이 구성에서 조인은 1.0, naive zip 은 0.918 로 실측된다.
    """
    da = [f"2026-01-{i:02d}" for i in range(1, 31)]
    va = [100 + (i * 7 % 11) for i in range(30)]              # 단조롭지 않은 패턴
    gaps = {"2026-01-10", "2026-01-11", "2026-01-12"}         # ★중간★ 휴장
    db = [d for d in da if d not in gaps]
    vb = [v for d, v in zip(da, va) if d not in gaps]
    _patch_indexed(monkeypatch, {"SPY": _series(da, va), "TLT": _series(db, vb)})
    v = tf.rolling_correlation(TK, "us", days=25, benchmark="TLT")
    assert v == pytest.approx(1.0, abs=1e-6), (
        f"겹치는 날짜만 썼다면 완전 상관이어야 한다 — 어긋난 채로 zip 했다는 뜻 (측정 {v})")


def test_rolling_correlation_none_when_overlap_too_short(monkeypatch):
    da = [f"2026-01-{i:02d}" for i in range(1, 31)]
    db = [f"2026-02-{i:02d}" for i in range(1, 28)]           # 겹치는 날짜 0
    _patch_indexed(monkeypatch, {"SPY": _series(da, [100.0] * 30),
                                 "TLT": _series(db, [100.0] * 27)})
    assert tf.rolling_correlation(TK, "us", days=25, benchmark="TLT") is None


def test_rolling_correlation_none_when_one_series_is_flat(monkeypatch):
    """★표준편차 0 으로 나누지 않는다★ 평평한 시계열은 mock 에서 안 나온다."""
    d = [f"2026-01-{i:02d}" for i in range(1, 31)]
    _patch_indexed(monkeypatch, {
        "SPY": _series(d, [100 + (i % 3) * 5 for i in range(30)]),
        "TLT": _series(d, [100.0] * 30)})
    assert tf.rolling_correlation(TK, "us", days=25, benchmark="TLT") is None


def test_rolling_correlation_stays_within_minus_one_and_one(monkeypatch):
    d = [f"2026-01-{i:02d}" for i in range(1, 31)]
    _patch_indexed(monkeypatch, {
        "SPY": _series(d, [100 + (i * 7 % 11) for i in range(30)]),
        "TLT": _series(d, [100 + (i * 3 % 5) for i in range(30)])})
    v = tf.rolling_correlation(TK, "us", days=25, benchmark="TLT")
    assert v is not None and -1.0 <= v <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 카탈로그 무결성 — 26번째 팩터가 잘못 추가되는 것을 막는다
# ═══════════════════════════════════════════════════════════════════════════════
NEW_IDS = ("relative_momentum", "breadth_above_ma", "equal_vs_cap", "realized_vol",
           "vol_regime", "target_vol_size", "drawdown", "drawdown_speed",
           "recovery_state", "rolling_correlation")


@pytest.mark.parametrize("fid", NEW_IDS)
def test_every_new_factor_is_in_the_catalogue(fid):
    assert fid in tf.CATALOG_BY_ID


@pytest.mark.parametrize("fid", NEW_IDS)
def test_every_new_factor_is_reachable_through_evaluate(fid, monkeypatch):
    """★카탈로그에 있는데 evaluate 가 모르면 영원히 unavailable 이다★

    사용자에겐 "데이터가 없다" 로 보이지만 실제로는 배선이 빠진 것이다. 값이 나오든 None 이든
    상관없다 — 분기가 존재하는지만 본다.
    """
    _patch_daily(monkeypatch, {})
    _patch_monthly(monkeypatch, {})
    tf.evaluate(fid, TK, "us", dict(tf.CATALOG_BY_ID[fid].get("params") or {}))


#: `evaluate()` 분기가 없어도 되는 항목. 지금은 비어 있다.
#:
#: Phase 8 에서는 `indicator` 가 여기 있었다 — 카탈로그에 있는데 분기도 리더도 없어서 V2
#: 경로에서 영원히 unavailable 이었다(레거시 카나리 경로에서만 동작). **Phase 8b 가
#: `read_macro_indicator` 로 배선하면서 그 사유가 사라졌으므로 목록에서 뺐다.**
#: 면제는 사유가 살아 있는 동안만 유효하다 — 사유가 없어지면 항목도 없어져야 한다.
_EVALUATE_EXEMPT: set[str] = set()


def test_all_catalogue_ids_are_reachable_through_some_read_path():
    """카탈로그 전체 불변식 — **어느 경로로든** 읽히지 않으면 도달 불가능한 항목이다.

    도달 경로는 셋이다:
      · `evaluate()` 분기 — 가격 기반 팩터
      · `requires_as_of` — `read_factor` 가 시점 기반 리더로 보낸다
      · `read_factor` 안의 전용 분기 — `indicator` 처럼 플래그는 안 붙이지만
        시점이 주어지면 시점 기반으로 읽는 경우(Phase 8b)

    ★셋 다 아니면 사용자에겐 "데이터가 없다" 로 보이지만 실제로는 배선이 없는 것이다★
    Phase 8 에서 `indicator` 가 정확히 그 상태였고, 이 테스트가 그걸 찾아냈다.
    """
    import inspect
    src = inspect.getsource(tf.evaluate)
    from src.engine import timing_rules_v2 as v2
    read_src = inspect.getsource(v2.read_factor)
    for c in tf.CATALOG:
        fid = c["id"]
        # ★`availability: "unavailable"` 은 면제가 아니라 **주장**이다★ (Phase 12a)
        # 소스가 없다고 카탈로그가 스스로 밝힌 항목에 읽기 경로가 없는 것은 배선 누락이
        # 아니라 사실의 반영이다. 다만 이 분기를 면제 목록처럼 쓰면 실수로 unavailable 을
        # 붙여 배선 누락을 숨길 수 있으므로, 아래 별도 테스트가 그 주장을 검증한다.
        if c.get("availability") == "unavailable":
            continue
        if c.get("requires_as_of") or fid in _EVALUATE_EXEMPT:
            continue
        reachable = f'"{fid}"' in src or f'"{fid}"' in read_src
        assert reachable, f"{fid} 가 어떤 읽기 경로에서도 도달 불가능하다"


def test_unavailable_is_not_a_shortcut_around_the_reachability_guard():
    """★위 테스트의 면제 분기가 악용되지 않는지 지킨다★ (Phase 12a)

    `availability: "unavailable"` 을 붙이면 도달성 검사를 건너뛴다. 그러니 그 표시는
    **사유가 있고 실제로 평가되지 않을 때만** 정당하다 — 배선을 깜빡한 팩터에 이 표시를
    붙여 검사를 통과시키는 길을 막는다.
    """
    for c in tf.CATALOG:
        if c.get("availability") != "unavailable":
            continue
        assert c.get("unavailable_reason"), f"{c['id']} 가 사유 없이 검사를 면제받고 있다"
        # 정말로 값이 나오지 않아야 한다 — 나온다면 '소스 없음' 이 거짓이다.
        assert tf.evaluate(c["id"], "SPY", "us") is None, (
            f"{c['id']} 는 unavailable 이라면서 값을 돌려준다")


def test_every_catalogue_frequency_has_a_rank():
    """등급표에 없는 주기를 쓰면 빈도 충돌 경고가 **조용히** 꺼진다."""
    from src.engine.timing_rules_v2 import FREQUENCY_RANKS
    for c in tf.CATALOG:
        assert c["evaluation_frequency"] in FREQUENCY_RANKS, c["id"]


def test_every_catalogue_entry_declares_a_direction_and_a_reason():
    for c in tf.CATALOG:
        assert c["default_direction"] in ("above", "below"), c["id"]
        assert (c.get("desc") or "").strip(), f'{c["id"]} 에 설명이 없다'
        assert (c.get("provenance") or "").strip(), f'{c["id"]} 에 출처가 없다'


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 한국 세트 (Drift 8-2 — ETF 프록시)
#
# ★프록시는 프록시라고 적는다★
# KOSDAQ 은 수집 대상이 아니고 KOSPI 는 ECOS(forward_only) 라, 지수 시계열로는 만들 수 없다.
# 대신 거래되는 ETF 로 근사한다 — 추적오차와 보수가 신호 안에 섞여 들어가므로, 그 사실이
# 설명에 없으면 사용자는 지수를 본다고 오해한다.
# ═══════════════════════════════════════════════════════════════════════════════
def test_kospi_kosdaq_rs_positive_when_growth_leads(monkeypatch):
    _patch_monthly(monkeypatch, {"229200": _rising(20), "069500": _flat(20)})
    v = tf.kospi_kosdaq_rs(None, "kr", months=6)
    assert v is not None and v > 0


def test_kospi_kosdaq_rs_negative_when_core_leads(monkeypatch):
    _patch_monthly(monkeypatch, {"229200": _flat(20), "069500": _rising(20)})
    assert tf.kospi_kosdaq_rs(None, "kr", months=6) < 0


def test_kospi_kosdaq_rs_none_when_one_leg_missing(monkeypatch):
    _patch_monthly(monkeypatch, {"069500": _rising(20)})
    assert tf.kospi_kosdaq_rs(None, "kr", months=6) is None


def test_usdkrw_trend_positive_when_dollar_rises(monkeypatch):
    _patch_monthly(monkeypatch, {"261240": _rising(20)})
    v = tf.usdkrw_trend(None, "kr", months=6)
    assert v is not None and v > 0


def test_usdkrw_trend_none_when_unreadable(monkeypatch):
    _patch_monthly(monkeypatch, {})
    assert tf.usdkrw_trend(None, "kr", months=6) is None


@pytest.mark.parametrize("fid", ["kospi_kosdaq_rs", "usdkrw_trend"])
def test_korea_factors_disclose_that_they_are_etf_proxies(fid):
    """★지수가 아니라 ETF 라는 사실을 설명에 적는다★

    스펙 §6 은 데이터가 뒷받침하지 않는 주장을 금지한다. 이 팩터들은 지수가 아니라 상품을
    측정하므로, 그 차이를 적지 않으면 "KOSPI 대비" 라고 읽힌다.
    """
    desc = tf.CATALOG_BY_ID[fid]["desc"]
    assert "ETF" in desc, f"{fid}: ETF 프록시라는 사실이 설명에 없다"
    assert "지수가 아" in desc or "프록시" in desc, f"{fid}: 지수와의 차이를 적지 않았다"


@pytest.mark.parametrize("fid", ["kospi_kosdaq_rs", "usdkrw_trend"])
def test_korea_factors_are_reachable_through_evaluate(fid, monkeypatch):
    _patch_monthly(monkeypatch, {})
    tf.evaluate(fid, "069500", "kr", dict(tf.CATALOG_BY_ID[fid].get("params") or {}))


def test_usdkrw_trend_reads_dollar_strength_as_risk_off():
    """원화 약세(달러 강세)는 국내 주식에 위험-오프 쪽 — 방향이 below 여야 한다."""
    assert tf.CATALOG_BY_ID["usdkrw_trend"]["default_direction"] == "below"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 섹터 디스퍼전 (Phase 8b — Drift 8-1 로 Phase 8 에서 재배치되어 온 요구)
#
# ★섹터 지수 시계열이 없다★ `stock_master.get_stock_sector()` 는 종목→섹터 **이름**만 준다.
# 그래서 섹터 ETF 바스켓으로 근사하고, 그 사실을 설명에 적는다 — 한국 세트와 같은 규칙이다.
# ═══════════════════════════════════════════════════════════════════════════════
def test_sector_dispersion_is_zero_when_every_sector_moves_together(monkeypatch):
    _patch_daily(monkeypatch, {"A": _rising(300), "B": _rising(300)})
    v = tf.sector_dispersion(None, "kr", days=20, basket=("A", "B"))
    assert v == pytest.approx(0.0, abs=1e-9)


def test_sector_dispersion_rises_when_sectors_diverge(monkeypatch):
    _patch_daily(monkeypatch, {"A": _rising(300), "B": _falling(300)})
    together = tf.sector_dispersion(None, "kr", days=20, basket=("A", "A"))
    apart = tf.sector_dispersion(None, "kr", days=20, basket=("A", "B"))
    assert apart > together


def test_sector_dispersion_counts_only_sectors_it_could_read(monkeypatch):
    """읽지 못한 섹터를 0% 수익률로 세면 없는 분산을 만들어낸다."""
    _patch_daily(monkeypatch, {"A": _rising(300)})       # B 결측
    assert tf.sector_dispersion(None, "kr", days=20, basket=("A", "B")) is None


def test_sector_dispersion_needs_at_least_two_sectors(monkeypatch):
    """한 섹터로는 분산이 정의되지 않는다 — 0 이 아니라 None."""
    _patch_daily(monkeypatch, {"A": _rising(300)})
    assert tf.sector_dispersion(None, "kr", days=20, basket=("A",)) is None


def test_sector_dispersion_discloses_that_it_uses_etf_proxies():
    meta = tf.CATALOG_BY_ID["sector_dispersion"]
    assert "ETF" in meta["desc"]
    assert "지수가 아" in meta["desc"] or "프록시" in meta["desc"]


def test_sector_dispersion_is_reachable_through_evaluate(monkeypatch):
    _patch_daily(monkeypatch, {})
    tf.evaluate("sector_dispersion", "069500", "kr",
                dict(tf.CATALOG_BY_ID["sector_dispersion"].get("params") or {}))
