"""조건식 백테스트를 ★실제로★ 빈티지에 배선한다 (MacroPitContext)

## 무엇이 문제였나

`aa3c4ba` 가 `resolve_macro_token(df, token, as_of=)` 에 PIT 경로를 붙였다.
그런데 **운영 코드에서 그 `as_of` 를 넘기는 호출부가 하나도 없었다.**

    resolve_macro_token( 호출부 → condition_strategy.py 단 한 곳, positional
    _base_series(df, token)    → 시그니처에 날짜 자체가 없다

즉 기계는 있는데 아무도 부르지 않았고, 모든 백테스트의 매크로는 라이브
(= 여러 번 개정된 최신값)로 평가됐다.

## 왜 컨텍스트 객체인가

저장소에 이미 `kis_data_fetcher._BAR_CONTEXT`(ContextVar) 라는 선례가 있다.
그런데 그 파일이 스스로 한계를 적어 두었다 — **컨텍스트는 미는 스레드에서만
보인다**. 신호 생성을 병렬화하면 컨텍스트가 조용히 사라지고 **라이브 =
룩어헤드로 폴백**한다. 그래서 여기서는 암묵 스택 대신 **명시적으로 넘기고**,
빠진 호출부를 정적 트립와이어로 잡는다.

## 이 파일이 거는 계약

① ★ctx 가 없으면 기존 동작 그대로★ — 스크리너·실시간 경로는 라이브가 맞다.
② **판정은 토큰당 1회, 실행 달력 기준** — 종목 프레임 첫 봉으로 판정하면
   상장일이 다른 종목 사이에서 같은 토큰이 다른 의미를 갖는다.
③ **전부-아니면-전혀 + 라벨** — 한 토큰은 그 실행에서 전 구간 PIT 이거나 전 구간
   라이브다. 섞이면 라벨을 붙여도 소비자가 구별하지 못한다.
④ ★조회 실패는 `live` 가 아니라 `blocked`★ — 미상 ≠ 없음. DB 가 잠깐 죽었다고
   전 실행이 조용히 룩어헤드 모드가 되면 안 되고, `live` 라벨은 "확인했더니
   빈티지가 없었다" 로 읽힌다.
⑤ **스토어는 계열당 1회** — 종목 수·봉 수와 무관하다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.pit_macro as pm  # noqa: E402
import src.kis_strategies.condition_strategy as cs  # noqa: E402
import src.kis_strategies.factor_tokens as FT  # noqa: E402
from src.kis_strategies.macro_pit_context import MacroPitContext  # noqa: E402

TOKEN = "US물가(전년비)"
TOKEN_ECOS = "국고채(10년)"
SERIES = "CPIAUCSL"

CAL = pd.bdate_range("2024-01-02", periods=40)
#: 빈티지가 **앞쪽만** 못 덮는 달력 — 첫 봉은 NaN, 뒤쪽에는 값이 있다.
#: 이 구분이 있어야 "첫 봉이 비었는가" 분기를 실제로 탄다(H2·H13 앵커).
MID_CAL = pd.bdate_range("2023-06-01", "2024-03-01")


@pytest.fixture(autouse=True)
def _clean():
    FT._ecos_cache.clear()
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


#: 2023-01 부터 매월, 전부 공표 지연 없음. 2024-01 봉에서 전년비를 낼 수 있다.
DEEP_ROWS = [_obs(f"2023-{m:02d}-01", 100.0 + m, release=f"2023-{m:02d}-01")
             for m in range(1, 13)] + \
            [_obs(f"2024-{m:02d}-01", 120.0 + m, release=f"2024-{m:02d}-01")
             for m in range(1, 3)]


def _frame(index) -> pd.DataFrame:
    idx = pd.DatetimeIndex(index)
    c = np.linspace(100, 120, len(idx))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": np.full(len(idx), 1)}, index=idx)


@pytest.fixture
def deep_store(monkeypatch):
    """실행 달력 첫 봉부터 빈티지가 있는 계열."""
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda series_id=None, **k: [
        o for o in DEEP_ROWS if series_id in (None, o.series_id)])
    return DEEP_ROWS


@pytest.fixture
def shallow_store(monkeypatch):
    """빈티지가 **실행 달력보다 늦게** 시작한다 — 첫 봉에 값이 없다."""
    rows = [_obs(f"2024-{m:02d}-01", 120.0 + m, release=f"2024-{m:02d}-01")
            for m in range(1, 3)]
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda series_id=None, **k: [
        o for o in rows if series_id in (None, o.series_id)])
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# ① ctx 가 없으면 기존 동작 그대로 (★짝★)
# ═══════════════════════════════════════════════════════════════════════════════

def test_without_a_context_the_macro_token_stays_live(deep_store, monkeypatch):
    """★H5 를 죽이는 짝★ 이것이 없으면 "항상 PIT" 구현도 통과한다.

    스크리너·실시간 경로는 ctx 를 만들지 않는다 — 거기서는 **오늘 최신값**이 맞다.
    """
    hits = {"n": 0}

    def _live(token):
        hits["n"] += 1
        return pd.Series([100.0, 130.0],
                         index=pd.DatetimeIndex(["2023-01-01", "2024-01-01"]))

    monkeypatch.setattr(FT, "_fred_fetch", _live)
    s = cs._base_series(_frame(CAL), TOKEN)
    assert s is not None
    assert hits["n"] == 1, "ctx 가 없는데 라이브를 안 탔다 — 기존 동작이 바뀌었다"


def test_the_context_requires_a_run_calendar():
    """★기준 없는 판정은 종목별로 갈린다★ 달력 없이는 ctx 를 만들 수 없다."""
    with pytest.raises(ValueError):
        MacroPitContext(pd.DatetimeIndex([]))


# ═══════════════════════════════════════════════════════════════════════════════
# ②③ 판정은 토큰당 1회, 실행 달력 기준
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_token_with_deep_vintages_is_evaluated_point_in_time(deep_store):
    ctx = MacroPitContext(CAL)
    s = cs._base_series(_frame(CAL), TOKEN, macro_ctx=ctx)
    assert s is not None and s.notna().any(), "빈티지가 있는데 값을 못 냈다"
    assert ctx.path[TOKEN]["path"] == "pit", ctx.path[TOKEN]


def test_a_token_whose_vintages_start_late_falls_back_to_live_with_a_label(
        deep_store, monkeypatch):
    """★H2 를 죽이는 앵커★ 첫 봉이 비었는데 `pit` 이라 세면 라이브가 PIT 로 위장한다.

    그리고 값을 아예 안 내면(엄격 거절) 매크로 조건이 조용히 무력화되어
    "매크로 조건 없는 전략" 을 돌린 셈이 된다 — 그래서 쓰되 **라벨**한다.

    ★`MID_CAL` 을 쓰는 이유★ 처음에는 빈티지가 아예 얕은 픽스처를 썼는데, 그러면
    PIT 시리즈가 **전부 NaN → `None`** 이 되어 `s is None` 분기로 빠진다. 즉
    "첫 봉만 NaN" 분기를 **지나가지 않아** 이 앵커가 겨냥을 빗나갔다(변이 생존).
    `MID_CAL` 은 앞쪽만 비고 뒤쪽에는 값이 있어 그 분기를 실제로 탄다.
    """
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [100.0, 130.0], index=pd.DatetimeIndex(["2023-01-01", "2024-01-01"])))
    ctx = MacroPitContext(MID_CAL)
    probe = FT.resolve_macro_token(pd.DataFrame(index=MID_CAL), TOKEN, as_of="per_bar")
    assert probe is not None and pd.isna(probe.iloc[0]) and probe.notna().any(), \
        "픽스처가 '첫 봉만 비었다' 를 만들지 못했다 — 앵커가 분기를 못 탄다"
    s = cs._base_series(_frame(MID_CAL), TOKEN, macro_ctx=ctx)
    assert s is not None, "라이브로도 값을 못 냈다"
    assert ctx.path[TOKEN]["path"] == "live", ctx.path[TOKEN]
    assert ctx.path[TOKEN]["reason"], "라이브로 떨어졌는데 사유가 없다"


def test_the_verdict_is_the_same_for_stocks_with_different_listing_dates(deep_store,
                                                                        monkeypatch):
    """★H13 을 죽이는 앵커★ 종목 프레임 첫 봉으로 판정하면 여기서 갈린다.

    늦게 상장한 종목의 프레임은 빈티지가 깊어진 뒤만 담으므로, **그 프레임만 보면
    `pit`** 이다. 실행 달력 전체로 보면 `live` 다. 판정 기준이 프레임이면 한 실행
    안에서 같은 토큰이 종목마다 다른 의미를 갖는다.

    ★두 프레임이 실제로 다른 답을 낼 수 있어야 앵커다★ — 아래 `assert` 가 그것을
    먼저 확인한다. 처음에는 둘 다 `live` 인 픽스처를 써서 변이가 살아남았다.
    """
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [100.0, 130.0], index=pd.DatetimeIndex(["2023-01-01", "2024-01-01"])))
    late_idx = MID_CAL[MID_CAL >= "2024-01-15"]
    late_probe = FT.resolve_macro_token(pd.DataFrame(index=late_idx), TOKEN,
                                        as_of="per_bar")
    assert late_probe is not None and late_probe.notna().iloc[0], \
        "늦은 프레임이 pit 가 될 수 없다 — 이 앵커는 변이를 구별하지 못한다"

    ctx = MacroPitContext(MID_CAL)
    cs._base_series(_frame(MID_CAL), TOKEN, macro_ctx=ctx)     # 일찍 상장
    verdict_after_early = ctx.path[TOKEN]["path"]
    cs._base_series(_frame(late_idx), TOKEN, macro_ctx=ctx)    # 늦게 상장
    assert ctx.path[TOKEN]["path"] == verdict_after_early == "live", (
        f"종목마다 판정이 갈렸다: {ctx.path[TOKEN]}")


def test_ecos_tokens_are_live_and_labelled(monkeypatch):
    """제공자에 빈티지 엔드포인트가 없다 — ★영구★. 쓰되 룩어헤드로 라벨한다."""
    monkeypatch.setattr(FT, "_ecos_fetch", lambda token: pd.Series(
        [3.5], index=pd.DatetimeIndex(["2024-01-02"])))
    ctx = MacroPitContext(CAL)
    cs._base_series(_frame(CAL), TOKEN_ECOS, macro_ctx=ctx)
    assert ctx.path[TOKEN_ECOS]["path"] == "live", ctx.path[TOKEN_ECOS]
    assert "구조적으로 불가능" in ctx.path[TOKEN_ECOS]["reason"]


# ═══════════════════════════════════════════════════════════════════════════════
# ④ 조회 실패는 blocked — 미상 ≠ 없음
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_store_failure_is_blocked_not_live(monkeypatch):
    """★H12 를 죽이는 앵커★

    예외를 `live` 로 떨어뜨리면 DB 가 잠깐 죽었을 때 전 실행이 조용히 룩어헤드
    모드가 되고, 화면의 `live` 라벨은 "확인했더니 빈티지가 없었다" 로 읽힌다.
    하지 않은 진술이다.
    """
    import src.data.macro_observation_store as mos

    def _boom(*a, **k):
        raise RuntimeError("DB 연결 끊김")

    monkeypatch.setattr(mos, "load", _boom)
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [100.0, 130.0], index=pd.DatetimeIndex(["2023-01-01", "2024-01-01"])))
    ctx = MacroPitContext(CAL)
    s = cs._base_series(_frame(CAL), TOKEN, macro_ctx=ctx)
    assert ctx.path[TOKEN]["path"] == "blocked", ctx.path[TOKEN]
    assert s is None, "조회가 실패했는데 값을 냈다"


def test_an_empty_store_is_live_not_blocked(monkeypatch):
    """★짝★ '확인했더니 없다' 와 '못 확인했다' 를 구별한다.

    이 짝이 없으면 "항상 blocked" 구현도 위 테스트를 통과한다.
    """
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: [])
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [100.0, 130.0], index=pd.DatetimeIndex(["2023-01-01", "2024-01-01"])))
    ctx = MacroPitContext(CAL)
    cs._base_series(_frame(CAL), TOKEN, macro_ctx=ctx)
    assert ctx.path[TOKEN]["path"] == "live", ctx.path[TOKEN]


# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ 스토어는 계열당 1회
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_store_is_read_once_per_series_regardless_of_tickers(deep_store,
                                                                 monkeypatch):
    """★H9 를 죽이는 앵커★

    `_token_series`·`prepare_panel` 은 **종목마다**, 엔진의 시장타이밍 검사는
    **봉마다** `_base_series` 를 부른다. 캐시가 없으면 그 수만큼 조회가 돈다.
    """
    import src.data.macro_observation_store as mos
    calls = {"n": 0}
    real = mos.load

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(mos, "load", counted)
    ctx = MacroPitContext(CAL)
    # ★프레임을 종목마다 다르게 만든다★ 전부 같은 인덱스면 프레임 캐시가 덮어버려
    # "계열당 1회" 를 어기는 구현도 통과한다(실제로 처음에 그렇게 통과했다).
    # 종목은 상장일·거래정지가 달라 프레임 길이가 제각각이다.
    frames = [_frame(CAL[i:]) for i in range(25)]
    assert len({len(f) for f in frames}) == 25, "프레임이 서로 달라야 앵커가 성립한다"
    for f in frames:
        cs._base_series(f, TOKEN, macro_ctx=ctx)
    assert calls["n"] == 1, f"스토어를 {calls['n']}회 읽었다 — 종목마다 읽고 있다"


def test_a_non_macro_token_is_not_recorded_in_the_path(deep_store):
    """★물어본 적 없는 것은 어느 쪽에도 넣지 않는다★

    `_base_series` 는 리졸버 체인이라 가격·수급 토큰도 매크로 리졸버를 스친다.
    그것들을 `blocked` 로 세면 라벨이 소음으로 가득 차 읽을 수 없게 된다.
    """
    ctx = MacroPitContext(CAL)
    cs._base_series(_frame(CAL), "종가", macro_ctx=ctx)
    assert ctx.path == {}, f"매크로가 아닌 토큰이 기록됐다: {ctx.path}"


# ═══════════════════════════════════════════════════════════════════════════════
# 트립와이어 — 배선이 빠진 호출부를 정적으로 잡는다
# ═══════════════════════════════════════════════════════════════════════════════

#: 백테스트 경로에서 `_base_series` 를 부르는 함수들. ★여기 없으면 라이브로 샌다★
BACKTEST_CALLERS = (
    ("src.kis_strategies.condition_strategy", "_eval_condition"),
    ("src.kis_strategies.condition_strategy", "prepare_panel"),
    ("src.kis_strategies.condition_strategy", "_token_series"),
    ("src.kis_backtest_engine", "_fill_expr_base"),
    ("src.kis_backtest_engine", "_market_timing_on"),
)


def _sources():
    """(라벨, 소스) — 클래스 메서드도 이름으로 찾는다."""
    import importlib
    import inspect
    out = []
    for mod_name, fn_name in BACKTEST_CALLERS:
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, fn_name, None)
        if fn is None:                       # 클래스 메서드
            for _n, obj in inspect.getmembers(mod, inspect.isclass):
                cand = getattr(obj, fn_name, None)
                # ★찾은 것을 덮어쓰지 않는다★ 뒤 클래스에 없으면 다시 None 이 된다.
                if cand is not None and getattr(cand, "__module__", "") == mod_name:
                    fn = cand
                    break
        assert fn is not None, f"{mod_name}.{fn_name} 을 찾지 못했다 — 이름이 바뀌었나"
        out.append((f"{mod_name}.{fn_name}", inspect.getsource(fn)))
    return out


def test_every_backtest_caller_passes_the_macro_context():
    """★배선이 빠지면 조용히 룩어헤드★ 그래서 정적으로 잡는다.

    ★`callable()` 로 검사하지 않는다★ — 예전에 그런 검사가 **존재하지도 않는
    함수**를 통과시킨 적이 있다. 소스를 읽어야 실제로 넘기는지 보인다.
    """
    missing = [label for label, src in _sources()
               if "_base_series(" in src and "macro_ctx" not in src]
    assert missing == [], f"매크로 컨텍스트를 넘기지 않는 호출부: {missing}"


def test_the_tripwire_would_catch_a_caller_that_drops_the_context():
    """★테스트의 테스트★ (변이 H6) 트립와이어가 항상 통과하는 검사면 소용없다."""
    fake = [("가짜 호출부", "def f(df):\n    return _base_series(df, tok)\n")]
    missing = [label for label, src in fake
               if "_base_series(" in src and "macro_ctx" not in src]
    assert missing == ["가짜 호출부"], "트립와이어가 빠진 호출부를 못 잡는다"
