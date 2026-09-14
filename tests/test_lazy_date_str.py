"""`_date_str` 을 ★필요할 때만★ 만든다 — 프레임 메모리 42% (④)

## 무엇이 문제였나

`_absorb` 가 적재한 **모든 종목**에 즉시 날짜 문자열 컬럼을 붙였다:

```python
                d = d.copy()
                d["_date_str"] = d.index.strftime("%Y%m%d")
```

이것은 per-bar 폴백에서 봉마다 `strftime` 을 돌던 O(N²) 을 없앤 정당한 최적화였다.
문제는 **소비처가 하나뿐**이라는 것이다 — `_generate_signal_as_of` 의
`_fetch_frames` 구축(엔진 `:746`), 즉 **per-bar 폴백 경로**다.

실측(200종목 × 800봉):

| | 크기 |
|---|---|
| 엔진 보유 프레임 1종목 | 123.5 KB |
| 그중 `_date_str`(object 문자열) | **52.0 KB (42%)** |
| 숫자 5개 컬럼 합계 | 32.0 KB |
| 200종목 `ohlcv_all` | 24.7 MB (그중 `_date_str` **10.4 MB**) |

★벡터화 경로만 타는 실행에서는 한 번도 읽히지 않는다★ — 실측에서 `_fetch_frames`
가 0개였는데도 10.4 MB 를 쓰고 있었다. 실행당 RSS 90~247MB × 워커 4개라
컨테이너가 빠듯하면 OOM killer 가 자식을 죽인다(그것이 이 세션 초반에 고친
워커 사망의 방아쇠였다).

`_fetch_frames` 는 이미 **종목별 1회** 캐시이므로, 거기서 처음 필요할 때 만들면
O(N²) 도 돌아오지 않는다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.ohlcv_loader as L  # noqa: E402
import src.kis_strategies.condition_strategy as CS  # noqa: E402
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

N_SYM, N_BAR = 12, 800
BUY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
        "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]

#: ★변경 **전** 코드(HEAD)에서 per-bar 폴백을 강제해 뜬 지문★
#: 런 대 런 비교만으로는 프로덕션에 박힌 상수 오프셋을 못 잡는다(변이 C2 의 교훈).
GOLDEN_SHA256 = "9ab4249d7d2338394a1b1a7832627237ddea63dfb8d751bd675602d3da6ffb9b"
GOLDEN_TRADES = 275


@pytest.fixture
def frames(monkeypatch):
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2023-01-02", periods=N_BAR)
    out = {}
    for i in range(N_SYM):
        c = 10000 * np.exp(np.cumsum(rng.normal(0, .018, N_BAR)))
        out[f"{i:06d}"] = pd.DataFrame(
            {"open": c * .995, "high": c * 1.01, "low": c * .99,
             "close": c, "volume": rng.integers(1e5, 1e6, N_BAR)}, index=idx)
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": out.get(tk, pd.DataFrame()).copy())
    return out


def _engine(frames) -> BacktestEngine:
    # ★이 골든은 *지연 생성이 수치를 안 바꿨다* 는 증거이지 기본값의 증거가
    # 아니다★ — `signal_lag` 기본이 0→1 로 바뀌자(AG) 지문이 통째로 움직였다.
    # 스냅샷이 무관한 기본값 변경에 흔들리지 않도록 **그때의 조건을 명시**한다.
    return BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-07-26", end_date="2026-07-26", max_positions=5,
        signal_lag=0))


def _force_fallback(monkeypatch):
    monkeypatch.setattr(
        CS.ConditionStrategy, "_precompute_ticker",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("강제 폴백")))


# ── 메모리 ──────────────────────────────────────────────────────────────────

def test_the_vectorized_run_does_not_carry_the_date_column(frames):
    """★안 쓰는 것에 42% 를 내지 않는다★ 벡터화만 타면 컬럼이 없어야 한다."""
    eng = _engine(frames)
    eng.run()
    assert eng._fetch_frames == {}, "이 테스트의 전제 — 폴백이 돌면 안 된다"
    held = eng.ohlcv_all[list(eng.ohlcv_all)[0]]
    assert "_date_str" not in held.columns, (
        f"안 읽히는 컬럼을 들고 있다: {list(held.columns)}")


def test_the_fallback_run_still_gets_its_dates(frames, monkeypatch):
    """★짝★ "컬럼을 없앤다" 만 걸면 폴백이 깨진 구현도 통과한다."""
    _force_fallback(monkeypatch)
    eng = _engine(frames)
    eng.run()
    assert eng._fetch_frames, "폴백이 안 돌았다 — 이 테스트가 공허하다"
    cached = eng._fetch_frames[list(eng._fetch_frames)[0]]
    dates = cached["full"]["date"]
    assert dates.notna().all() and (dates.astype(str).str.len() == 8).all(), (
        "폴백 경로의 날짜가 비었거나 모양이 다르다")


def test_the_date_column_is_not_rebuilt_per_bar(frames, monkeypatch):
    """★O(N²) 를 되돌리지 않는다★ 원래 이 컬럼이 생긴 이유가 그것이다.

    종목마다 **한 번**만 만들어야 한다 — `_fetch_frames` 가 이미 종목별 1회 캐시다.
    """
    _force_fallback(monkeypatch)
    calls = {"n": 0}
    real = pd.DatetimeIndex.strftime

    def counted(self, fmt):
        calls["n"] += 1
        return real(self, fmt)

    monkeypatch.setattr(pd.DatetimeIndex, "strftime", counted)
    eng = _engine(frames)
    eng.run()
    assert calls["n"] <= N_SYM * 3, (
        f"strftime 이 {calls['n']}회 — 봉마다 다시 만들고 있다(종목 {N_SYM})")


# ── 동작 불변 ───────────────────────────────────────────────────────────────

def test_the_fallback_result_matches_the_pre_change_snapshot(frames, monkeypatch):
    """★변경 전 코드가 낸 지문에 못 박는다★

    per-bar 폴백을 강제해야 `_date_str` 이 실제로 읽힌다 — 벡터화만 돌면 이 골든은
    변경을 보지 못한다(공허해진다). 강제 시 `_fetch_frames` 가 12개로 채워지는 것을
    확인했다.
    """
    import hashlib
    import json
    _force_fallback(monkeypatch)
    eng = _engine(frames)
    res = eng.run().get("result") or {}
    assert eng._fetch_frames, "해네스가 공허하다 — 폴백이 안 돌았다"
    g = json.dumps([res.get("trades"), res.get("equity_curve"), res.get("statistics")],
                   default=str, sort_keys=True)
    assert len(res.get("trades") or []) == GOLDEN_TRADES
    assert hashlib.sha256(g.encode()).hexdigest() == GOLDEN_SHA256, (
        "변경 전 코드가 내던 결과와 다르다 — 지연 생성이 동작을 바꿨다")
