"""개정이 ★판정을 뒤집었는가★ 를 잰다 (Croushore-Stark)

## 왜 라벨로 부족한가

P4 의 `macro_lookahead` 는 "룩어헤드가 있었다/없었다" 를 말한다. 그런데 정작
물어야 하는 것은 **그것이 결론을 바꾸었는가** 다.

Croushore & Stark (2001, *J. Econometrics* 105:111-130) 의 요지가 정확히
이것이다 — 실시간(빈티지) 데이터로 다시 하면 기존 실증 결과의 robustness 가
바뀐다. 개정이 있다는 사실보다 **개정이 판정을 뒤집은 비율**이 답이다.

## ★무엇을 재는지 이름을 정확히 붙인다★

이것은 **매크로 레그의 참/거짓이 갈린 봉의 비율**이지 **최종 신호가 갈린
비율이 아니다.** 논리 결합(`and`/`or`/`every()`)이 레그 뒤집힘을 흡수하거나
증폭한다. 최종 신호 차이는 두 번의 전체 실행이 필요하고 이번 범위가 아니다.

혼동하면 "매크로 개정이 수익률을 X% 바꿨다" 같은, 증거가 뒷받침하지 않는
주장으로 번진다.

## 계약

① **PIT 토큰만 잰다** — 라이브로 떨어진 토큰은 비교 대상(PIT 값)이 없다.
② ★분모가 0이면 `None`★ — 둘 다 유효한 봉이 없으면 "0% 갈렸다" 가 아니라
   **재지 못했다**.
③ **라이브를 못 받으면 `None` + 사유** — 키가 없으면 비교 자체가 불가능하다.
④ ★새 비교 의미를 만들지 않는다★ — 기존 `_vector_compare` 를 그대로 쓴다.
   따로 구현하면 조건식의 연산자 의미와 갈라진다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.pit_macro as pm  # noqa: E402
import src.kis_strategies.factor_tokens as FT  # noqa: E402
from src.kis_strategies.condition_strategy import ConditionStrategy  # noqa: E402
from src.kis_strategies.macro_pit_context import MacroPitContext  # noqa: E402

TOKEN = "US물가(전년비)"
SERIES = "CPIAUCSL"
CAL = pd.bdate_range("2024-01-02", "2024-06-28")


@pytest.fixture(autouse=True)
def _clean():
    FT._fred_cache.clear()
    FT._macro_failures.clear()
    yield
    FT._fred_cache.clear()
    FT._macro_failures.clear()


def _obs(period: str, value: float, *, release: str):
    return pm.MacroObservation(
        series_id=SERIES, observation_period=period, value=value,
        vintage_id=f"{release}..9999-12-31", release_timestamp=release,
        retrieved_at="2026-01-01")


def _frames(index=None) -> dict:
    idx = pd.DatetimeIndex(index if index is not None else CAL)
    c = np.linspace(100, 120, len(idx))
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                       "volume": np.full(len(idx), 1)}, index=idx)
    return {"000001": df}


def _cond(rhs: float) -> dict:
    return {"factor_token": TOKEN, "function_id": "base", "params": {},
            "op": "gte", "rhs": rhs}


def _strategy(conds, ctx) -> ConditionStrategy:
    s = ConditionStrategy(buy_conditions=conds, sell_conditions=[])
    s.set_macro_ctx(ctx)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처 — 개정이 **판정을 뒤집는** 크기로 일어난다
#
#   2023년 각 월 = 100.0  (그때 공표)
#   2024년 각 월 = 103.0  (그때 공표)
#   ⇒ 그 시점 전년비 = +3.0%
#
#   그런데 2023년 값이 나중에 **101.0 으로 상향 개정**된다(2024-04-01 공표).
#   ⇒ 오늘(라이브) 보면 전년비 = 103/101 - 1 = +1.98%
#
#   임계값 2.5% 를 두면 ★PIT 는 참, 라이브는 거짓★ 이다.
# ─────────────────────────────────────────────────────────────────────────────
_MONTHS_23 = [f"2023-{m:02d}-01" for m in range(1, 13)]
_MONTHS_24 = [f"2024-{m:02d}-01" for m in range(1, 7)]

REVISED_ROWS = (
    [_obs(p, 100.0, release=p) for p in _MONTHS_23]
    + [_obs(p, 103.0, release=p) for p in _MONTHS_24]
    + [_obs(p, 101.0, release="2024-04-01") for p in _MONTHS_23]   # ★상향 개정★
)
#: 오늘 라이브가 보는 계열 — 개정이 전부 반영된 최신본.
LIVE_TODAY = pd.Series(
    [101.0] * len(_MONTHS_23) + [103.0] * len(_MONTHS_24),
    index=pd.DatetimeIndex(_MONTHS_23 + _MONTHS_24))


@pytest.fixture
def revised(monkeypatch):
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda series_id=None, **k: [
        o for o in REVISED_ROWS if series_id in (None, o.series_id)])
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: LIVE_TODAY)
    return REVISED_ROWS


# ═══════════════════════════════════════════════════════════════════════════════
# ① 개정이 판정을 뒤집으면 ★수치로 나온다★
# ═══════════════════════════════════════════════════════════════════════════════

#: 개정이 공표된 날. ★이 날 이후로는 PIT 도 개정본을 본다★
REVISION_RELEASED = "2024-04-01"
#: 그래서 판정이 갈리는 것은 **개정 전 봉뿐**이다.
EXPECTED_FLIPS = int((CAL < REVISION_RELEASED).sum())


def test_a_revision_flips_the_leg_verdict_only_on_bars_before_it_was_published(revised):
    """★이 파일의 핵심★ 임계값 2.5% 에서 PIT 는 +3.0%(참), 라이브는 +1.98%(거짓).

    ★처음에 100% 를 기대했는데 실측은 49.6% 였고, 실측이 맞다★ — 개정은
    2024-04-01 에 공표된다. 그 **이후** 봉에서는 PIT 도 개정본(101.0)을 보므로
    라이브와 값이 같아져 판정이 갈리지 않는다. 갈리는 것은 개정 전 봉뿐이다.

    그래서 마법의 숫자를 적지 않고 **공표일에서 유도**한다 — 달력이 바뀌어도
    이 테스트가 계속 옳은 것을 말한다.
    """
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(2.5)], ctx)
    st.prepare_panel(_frames())
    rev = ctx.revision[TOKEN]
    assert rev["bars"] == len(CAL), rev
    assert rev["flip"] == EXPECTED_FLIPS, (
        f"갈린 봉이 개정 공표 전 봉({EXPECTED_FLIPS}개)과 다르다: {rev}")
    assert rev["flip_pct"] == pytest.approx(
        round(EXPECTED_FLIPS / len(CAL) * 100, 1)), rev


def test_a_threshold_no_revision_can_cross_shows_no_flip(revised):
    """★짝★ 이것이 없으면 "항상 100%" 구현도 통과한다.

    임계값 0.5% 면 PIT(+3.0%) 도 라이브(+1.98%) 도 참이라 판정이 갈리지 않는다.
    개정은 여전히 있었다 — 그러나 **결론을 바꾸지 않았다.** 그 구별이 요지다.
    """
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(0.5)], ctx)
    st.prepare_panel(_frames())
    rev = ctx.revision[TOKEN]
    assert rev["bars"] > 0, rev
    assert rev["flip"] == 0, f"판정이 안 갈렸는데 갈렸다고 잡혔다: {rev}"
    assert rev["flip_pct"] == 0.0, rev


def test_the_measurement_names_the_leg_not_the_signal(revised):
    """★이름이 주장의 크기를 정한다★

    논리 결합이 레그 뒤집힘을 흡수·증폭하므로, 이 수치는 최종 신호 차이가
    **아니다.** 보고에 그 사실이 함께 실려야 소비자가 과대 해석하지 않는다.
    """
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(2.5)], ctx)
    st.prepare_panel(_frames())
    note = ctx.revision[TOKEN]["note"]
    assert "레그" in note and "신호" in note, note


# ═══════════════════════════════════════════════════════════════════════════════
# ② 못 잰 것을 0 으로 적지 않는다
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_live_token_is_not_measured_at_all(monkeypatch):
    """★비교 대상이 없다★ 라이브로 떨어진 토큰에는 PIT 값이 없다."""
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: [])
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: LIVE_TODAY)
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(2.5)], ctx)
    st.prepare_panel(_frames())
    assert ctx.path[TOKEN]["path"] == "live"
    assert TOKEN not in ctx.revision, "비교 대상이 없는데 개정 폭을 적었다"


def test_an_unavailable_live_series_is_unknown_not_zero(revised, monkeypatch):
    """★미상 ≠ 0★ 라이브를 못 받으면 "안 갈렸다" 가 아니라 **못 쟀다** 이다."""
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: None)
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(2.5)], ctx)
    st.prepare_panel(_frames())
    rev = ctx.revision.get(TOKEN)
    assert rev is not None, "PIT 인데 개정 폭 항목 자체가 없다"
    assert rev["flip_pct"] is None, f"못 쟀는데 수치를 적었다: {rev}"
    assert rev["reason"], "못 쟀는데 사유가 없다"


def test_no_overlapping_bars_is_unknown_not_zero(revised, monkeypatch):
    """★분모 0 에 0.0 을 적지 않는다★ 겹치는 유효 봉이 없으면 미상이다."""
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [101.0], index=pd.DatetimeIndex(["2010-01-01"])))   # 구간이 안 겹친다
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(2.5)], ctx)
    st.prepare_panel(_frames())
    rev = ctx.revision.get(TOKEN)
    assert rev is not None
    assert rev["flip_pct"] is None, f"겹치는 봉이 없는데 수치를 적었다: {rev}"


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 결과에 실린다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_revision_measurement_rides_along_in_the_result_meta(revised):
    """`macro_lookahead` 안에 토큰별로 함께 실린다."""
    from src.kis_backtest_engine import _macro_lookahead_meta
    ctx = MacroPitContext(CAL)
    st = _strategy([_cond(2.5)], ctx)
    st.prepare_panel(_frames())
    meta = _macro_lookahead_meta(ctx)
    assert meta is not None
    rev = meta["tokens"][TOKEN].get("revision")
    assert rev is not None, f"개정 폭이 결과에 안 실렸다: {meta['tokens'][TOKEN]}"
    assert rev["flip"] == EXPECTED_FLIPS, rev
