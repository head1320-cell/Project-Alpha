"""PIT 재무가 ★두 경로에서 같은 답을 내야 한다★ (③)

## 무엇이 문제였나

`_build_pit_base` 는 보고서의 '공시 가능일' 이후 봉부터 값을 쓰게 해 look-ahead 를
막는다. 그 정렬을 이렇게 한다:

```python
        for d in df.index:
            bd = d.date() if hasattr(d, "date") else None
```

그런데 **per-bar 폴백 경로가 넘기는 프레임은 `RangeIndex`** 다 —
`kis_backtest_engine._generate_signal_as_of` 가 `pd.DataFrame({...})` 로 새로 만들고
날짜는 `date` **컬럼**에 넣기 때문이다(`:745`). 정수 라벨에는 `.date` 가 없으므로
`bd` 가 항상 `None` 이고, `cur` 가 끝까지 비어 **패널이 전부 NaN** 이 된다.
`if not panel: return None` 가드는 NaN Series 의 dict 가 truthy 라 잡지 못한다.

결과: **벡터화 경로와 per-bar 경로가 같은 종목·같은 날짜에 다른 답을 낸다.**
PIT 재무 조건이 폴백 경로에서 "평가 불가" 로 조용히 건너뛰어진다.

★이 저장소는 이 부류를 이미 한 번 고쳤다★ — `factor_tokens._df_dates` 의
독스트링이 똑같은 사고를 기록한다: *"이전엔 RangeIndex가 1970년 epoch로 해석돼
시장·매크로·수급 토큰이 per-bar 경로에서 조용히 전부 NaN→건너뜀 — 벡터화 경로와
비일관"*. `_build_pit_base` 만 그 처리를 못 받았다. **새로 만들지 않고 그 헬퍼를 쓴다.**
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.dart_history as DH  # noqa: E402
from src.kis_strategies.condition_strategy import ConditionStrategy  # noqa: E402

TK = "005930"


def _rows():
    """financials_history 모양의 연간 보고서 3건 (공시 시차 90일)."""
    return [
        {"ticker": TK, "year": 2022, "reprt": "11011", "revenue": 1000e8,
         "operating_profit": 100e8, "net_income": 80e8, "total_equity": 500e8,
         "total_liabilities": 300e8, "operating_cf": 90e8, "shares_outstanding": 1e8},
        {"ticker": TK, "year": 2023, "reprt": "11011", "revenue": 1200e8,
         "operating_profit": 130e8, "net_income": 100e8, "total_equity": 600e8,
         "total_liabilities": 320e8, "operating_cf": 110e8, "shares_outstanding": 1e8},
        {"ticker": TK, "year": 2024, "reprt": "11011", "revenue": 1500e8,
         "operating_profit": 170e8, "net_income": 140e8, "total_equity": 750e8,
         "total_liabilities": 350e8, "operating_cf": 150e8, "shares_outstanding": 1e8},
    ]


@pytest.fixture
def hist(monkeypatch):
    monkeypatch.setattr(DH, "load_history", lambda tk: _rows())
    return _rows()


def _vectorized_frame() -> pd.DataFrame:
    """벡터화 경로가 쓰는 모양 — DatetimeIndex."""
    idx = pd.bdate_range("2023-01-02", "2025-12-31")
    c = np.linspace(10000, 20000, len(idx))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": np.full(len(idx), 1000)}, index=idx)


def _per_bar_frame(vec: pd.DataFrame) -> pd.DataFrame:
    """per-bar 폴백이 넘기는 모양 — RangeIndex + 'date'(YYYYMMDD) 컬럼.
    `kis_backtest_engine._generate_signal_as_of` 가 만드는 것과 같다."""
    return pd.DataFrame({
        "date": vec.index.strftime("%Y%m%d").values,
        "open": vec["open"].values, "high": vec["high"].values,
        "low": vec["low"].values, "close": vec["close"].values,
        "volume": vec["volume"].values,
    })


def test_the_per_bar_frame_really_is_a_range_index():
    """★전제를 먼저 못 박는다★ 이 전제가 깨지면 아래 테스트가 공허해진다."""
    vec = _vectorized_frame()
    pb = _per_bar_frame(vec)
    assert isinstance(vec.index, pd.DatetimeIndex)
    assert isinstance(pb.index, pd.RangeIndex)
    assert not hasattr(pb.index[0], "date")


def test_the_panel_is_not_all_nan_on_the_per_bar_path(hist):
    """★조용한 NaN 을 막는다★ 폴백 경로에서 패널이 통째로 비면 안 된다."""
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    pb = _per_bar_frame(_vectorized_frame())
    panel = s._build_pit_base(TK, pb)
    assert panel is not None, "적재가 있는데 패널이 None 이다"
    ni = panel["net_income"]
    assert ni.notna().any(), "per-bar 경로에서 PIT 패널이 전부 NaN 이다"


def test_both_paths_agree_bar_for_bar(hist):
    """★짝 — 이것이 핵심 계약이다★

    한쪽만 거는 테스트로는 이 결함을 잡을 수 없다. 두 경로가 **같은 봉에서 같은
    값**을 내야 한다.
    """
    s1 = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    s2 = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    vec = _vectorized_frame()
    pb = _per_bar_frame(vec)

    a = s1._build_pit_base(TK, vec)
    b = s2._build_pit_base(TK, pb)
    assert a is not None and b is not None

    for field in ("net_income", "revenue", "total_equity", "shares"):
        va = a[field].to_numpy(dtype="float64")
        vb = b[field].to_numpy(dtype="float64")
        assert len(va) == len(vb) == len(vec), f"{field}: 길이가 다르다"
        assert np.allclose(va, vb, equal_nan=True), (
            f"{field}: 두 경로의 PIT 값이 다르다 — "
            f"벡터화 유효 {np.count_nonzero(~np.isnan(va))}봉 / "
            f"per-bar 유효 {np.count_nonzero(~np.isnan(vb))}봉")


def test_the_disclosure_lag_is_still_honoured(hist):
    """★짝의 반대편★ "두 경로가 같다" 만 걸면 **둘 다 룩어헤드**여도 통과한다.

    2024 연간 보고서(기간말 2024-12-31 + 90일 = 2025-03-31)의 값은 그 전 봉에서
    보이면 안 된다.
    """
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    vec = _vectorized_frame()
    panel = s._build_pit_base(TK, vec)
    ni = panel["net_income"]
    before = ni[ni.index < pd.Timestamp("2025-03-31")].to_numpy(dtype="float64")
    after = ni[ni.index >= pd.Timestamp("2025-03-31")].to_numpy(dtype="float64")
    assert not np.isclose(before, 140.0).any(), "공시 전에 2024 실적이 보였다"
    assert np.isclose(after, 140.0).any(), "공시 후에도 2024 실적이 안 보인다"


def test_the_cache_is_not_shared_across_differently_shaped_frames(hist):
    """★패널은 인덱스에 묶여 있다★

    `_pit_base_cache` 는 `tk` 만으로 키를 잡는데 패널은 `df.index` 에 맞춰 만들어진다.
    폴백 경로는 봉마다 길이가 다른 슬라이스를 넘기므로, 종목 키만으로 캐시하면
    **길이가 안 맞는 패널**을 돌려준다.
    """
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    vec = _vectorized_frame()
    short = vec.iloc[:200]

    # ★토큰 이름은 실측한 것을 쓴다★ 처음에 "PIT순이익" 이라고 지어 썼더니
    # `_PIT_FUND_TOKENS` 에 없어 항상 None 이 나왔고, `if ... is not None` 가드
    # 때문에 단언이 **한 번도 실행되지 않았다** — 변이 D16 이 그래서 살아남았다.
    # 실제 이름은 `_PIT_FUND_TOKENS` 의 "순이익" 이다.
    long_p = s._pit_fund_series(TK, "순이익", vec)
    assert long_p is not None, "해네스가 공허하다 — 토큰이 지원되지 않는다"
    assert len(long_p) == len(vec), f"긴 프레임: {len(long_p)} != {len(vec)}"

    short_p = s._pit_fund_series(TK, "순이익", short)
    assert short_p is not None, "해네스가 공허하다"
    assert len(short_p) == len(short), (
        f"캐시가 길이를 섞었다: {len(short_p)} != 요청 {len(short)} "
        f"— 종목 키만으로 캐시하면 앞선 호출의 패널이 그대로 돌아온다")
