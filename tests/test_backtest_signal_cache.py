"""per-bar 프레임·인과 지표 캐시 (P1-3 · P1-1).

감사 프로파일이 지목한 것을 닫는다. 실측(small, GoldenCross, 무프로파일):

    벽시계     13.24s → 4.97s   (-62.5%)
    simulating 11.64s → 3.36s   (-71.2%)

★이 파일이 지키는 것은 속도가 아니라 **동치성**이다★ 속도는 벤치가 재고, 여기서는
"빠른 경로가 느린 경로와 같은 값을 준다" 를 단언한다. 그게 깨지면 백테스트 결과가
조용히 달라진다 — 이 저장소에서 가장 비싼 종류의 결함이다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.kis_indicators as ind  # noqa: E402


def _frame(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 10000 + np.cumsum(rng.normal(0, 80, n))
    return pd.DataFrame({
        "date": [f"2023{i:04d}" for i in range(n)],
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": rng.integers(1000, 9000, n),
    })


def _with_cache(full: pd.DataFrame, k: int) -> pd.DataFrame:
    """엔진이 만드는 것과 같은 모양 — 전체 프레임 + 접두사 슬라이스 + 캐시 표식."""
    sl = full.iloc[:k]
    sl.attrs[ind._BT_CACHE_ATTR] = {"full": full, "memo": {}}
    return sl


@pytest.mark.parametrize("fn,kwargs", [
    (ind.calc_ma, {"period": 5}),
    (ind.calc_ma, {"period": 20}),
    (ind.calc_returns, {"period": 10}),
    (ind.calc_volatility, {"period": 10}),
    (ind.calc_disparity, {"period": 20}),
])
def test_cached_equals_uncached(fn, kwargs):
    """★빠른 경로 == 느린 경로★ 값도 인덱스도 NaN 위치도 같아야 한다."""
    full = _frame()
    for k in (60, 137, 300):
        plain = fn(full.iloc[:k].copy(), **kwargs)      # 캐시 표식 없음 = 기존 경로
        cached = fn(_with_cache(full, k), **kwargs)
        pd.testing.assert_series_equal(plain, cached, check_names=False)


def test_cache_is_reused_not_recomputed():
    """같은 (지표, 기간) 은 한 번만 계산한다 — 그게 이 변경의 전부다."""
    full = _frame()
    cache = {"full": full, "memo": {}}
    calls = {"n": 0}

    def compute(d):
        calls["n"] += 1
        return d["close"].rolling(5).mean()

    for k in (50, 80, 120):
        sl = full.iloc[:k]
        sl.attrs[ind._BT_CACHE_ATTR] = cache
        out = ind._causal(sl, ("t", 5), compute)
        assert len(out) == k
    assert calls["n"] == 1, f"{calls['n']}회 계산됐다 — 캐시가 안 먹었다"


def test_short_slice_still_returns_empty_series():
    """★길이 가드를 캐시가 건너뛰면 안 된다★

    원래 `calc_ma` 는 `len(df) < period` 면 **빈 Series** 를 준다. 캐시는 전체 길이로
    계산하므로 이 분기를 건너뛰면 빈 Series 대신 NaN 이 채워진 값이 나가고, 호출부의
    `.iloc[-2]` 가 IndexError 대신 NaN 을 받는다 — 조용한 동작 변경이다.
    """
    full = _frame()
    short = _with_cache(full, 3)
    assert ind.calc_ma(short, period=20).empty
    assert ind.calc_ma(full.iloc[:3].copy(), period=20).empty


def test_live_path_has_no_cache_marker():
    """라이브 경로의 DataFrame 에는 표식이 없다 → 기존 코드가 그대로 돈다."""
    plain = _frame(50)
    assert ind._BT_CACHE_ATTR not in plain.attrs
    assert ind._causal(plain, ("ma", 5, "close"), lambda d: d["close"]) is None


def test_engine_slice_is_a_prefix_of_the_full_frame():
    """★캐시 동치성의 전제★ 엔진이 넘기는 슬라이스는 항상 전체의 **접두사**다.

    `df_slice = ohlcv_map[t].loc[:sim_date]` 이고 인덱스가 오름차순이므로 성립한다.
    이 전제가 깨지면 `full.iloc[:k]` 가 다른 행을 가리켜 **결과가 조용히 틀린다.**
    """
    idx = pd.date_range("2023-01-01", periods=50, freq="D")
    df = pd.DataFrame({"close": range(50)}, index=idx)
    for cut in (idx[9], idx[29], idx[-1]):
        sl = df.loc[:cut]
        assert sl.index.equals(df.index[:len(sl)]), "슬라이스가 접두사가 아니다"
