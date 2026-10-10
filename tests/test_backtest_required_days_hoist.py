"""하루 × 종목 루프가 ★상수를 130,601번 재계산★ 하던 것 (②)

## 무엇이 문제였나 — 프로파일이 계산이 아니라 반복을 지목했다

사용자가 "백테스팅 로딩이 오래 걸린다" 고 해서 순수 파이썬 시뮬레이션 비용만
분리해 `cProfile` 을 걸었다(200종목 × 653일). tottime 1위가 전략 평가도
체결 시뮬레이션도 아니었다:

    522,404 calls  3.32s   factor_tokens.py:481   token_min_bars
    130,601 calls  8.59s   condition_strategy.py  required_days   ← cumtime 27%

`kis_backtest_engine.py` 의 하루 × 종목 루프가 봉마다 `strategy.required_days`
를 읽는데(200 × 653 = 130,600), 그 `@property` 는 **매번 처음부터 다시 계산**한다.
그런데 입력(`buy_conditions`·`sell_conditions`·`_prio_ast`)은 루프가 시작되기
전에 전부 확정된다 — `set_priority_expr` 는 루프보다 한참 위에서 끝난다.

**실측**(200종목, 골든 비트 동일): 28.56s → 21.57s / 14.44s → 12.31s = **15~25% 단축**.

★전략 클래스는 건드리지 않는다★ `required_days` 를 캐시하는 프로퍼티로 바꾸면
`_prio_ast` 를 나중에 세팅하는 다른 호출부의 의미가 조용히 달라진다. 소비 지점
한 곳만 고치는 쪽이 계층 경계를 넘지 않는다.

## 이 파일이 거는 것

값이 아니라 **효과**다. "호이스팅했다" 는 주장은 스파이로만 잴 수 있고
(변이 W10 의 교훈), "결과가 안 변했다" 는 골든으로만 잴 수 있다.
★그리고 골든이 공허하지 않음을 먼저 증명한다★ — `required_days` 를 실제로
구속되는 값으로 흔들면 골든이 **바뀌어야** 한다.
"""
from __future__ import annotations

import hashlib
import json
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.ohlcv_loader as ohlcv_loader  # noqa: E402
import src.kis_strategies.condition_strategy as cs  # noqa: E402
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

N_SYM, N_BAR = 12, 800
BUY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
        "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]


@pytest.fixture
def frames(monkeypatch):
    """결정론적 합성 OHLCV — DB·네트워크를 타지 않는다(비용 축을 분리)."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2023-01-02", periods=N_BAR)
    out: dict[str, pd.DataFrame] = {}
    for i in range(N_SYM):
        c = 10000 * np.exp(np.cumsum(rng.normal(0, 0.018, N_BAR)))
        out[f"{i:06d}"] = pd.DataFrame(
            {"open": c * .995, "high": c * 1.01, "low": c * .99,
             "close": c, "volume": rng.integers(1e5, 1e6, N_BAR)}, index=idx)
    monkeypatch.setattr(ohlcv_loader, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": out.get(tk, pd.DataFrame()).copy())
    return out


def _run(frames) -> dict:
    # ★이 골든은 *호이스팅이 수치를 안 바꿨다* 는 증거이지 기본값의 증거가
    # 아니다★ — `signal_lag` 기본이 0→1 로 바뀌자(AG) 지문이 통째로 움직였다.
    # 스냅샷이 무관한 기본값 변경에 흔들리지 않도록 **그때의 조건을 명시**한다.
    # 새 기본값은 `tests/test_signal_lag.py` 가 건다.
    cfg = BacktestConfig(symbols=list(frames), strategy_name="Condition",
                         strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
                         start_date="2023-07-26", end_date="2026-07-26", max_positions=5,
                         signal_lag=0)
    return BacktestEngine(cfg).run()


def _golden(r: dict) -> str:
    res = r.get("result") or {}
    return json.dumps([res.get("trades"), res.get("equity_curve"), res.get("statistics")],
                      default=str, sort_keys=True)


# ── ① 효과: 루프가 상수를 다시 읽지 않는다 ──────────────────────────────────

def test_required_days_is_read_a_handful_of_times_not_once_per_bar(frames, monkeypatch):
    """★주장이 아니라 호출 횟수를 건다★

    "호이스팅했다" 는 코드를 읽어 확인할 수 있지만, 그것이 **다시 들어오지 않는지**
    는 세어봐야 안다. 시간을 단언하면 컨테이너 편차(14.4~28.6s)로 플레이키가
    되므로 시간이 아니라 **횟수**를 건다.
    """
    hits = {"n": 0}
    orig = cs.ConditionStrategy.required_days

    def counted(self):
        hits["n"] += 1
        return orig.fget(self)

    monkeypatch.setattr(cs.ConditionStrategy, "required_days", property(counted))
    r = _run(frames)
    assert (r.get("result") or {}).get("trades"), "해네스가 공허하다 — 거래가 0건이다"

    bars = len((r.get("result") or {}).get("equity_curve") or [])
    assert bars > 100, f"시뮬레이션 일수가 너무 적다: {bars}"
    # 워밍업 산정(1회) + 루프 밖 호이스트(1회) 수준이어야 한다. 봉마다 읽으면
    # 최소 N_SYM × bars ≈ 수천 회가 된다.
    assert hits["n"] <= 10, (
        f"required_days 를 {hits['n']}회 읽었다 — 루프 안에서 다시 읽고 있다 "
        f"(종목 {N_SYM} × 봉 {bars})")


# ── ② 동작 불변: 골든 ────────────────────────────────────────────────────────

#: ★변경 **전** 코드(HEAD)에서 뜬 지문★ — 위 fixture 그대로 돌린 결과의 sha256.
#: 이 값을 박아두지 않으면 "런 대 런이 같다" 만 걸리는데, 그것은 프로덕션 코드에
#: **상수 오프셋**이 박혀도 통과한다(변이 C2 가 실제로 그렇게 살아남았다).
#: AK(비용 모델) 에서 **키가 추가되어** 지문이 움직였다 — ★값은 하나도 안 바뀌었다★.
#: 갱신 전에 키별로 대조해 확인했다: 거래 275→275 · 에쿼티 곡선 동일 · 거래 행의
#: 기존 키 전부 동일 · 통계의 기존 키 전부 동일. 새로 붙은 것은 `tax`·`spread`·
#: `impact`(거래 행)와 `total_tax`·`total_spread`·`total_impact`(통계)이고 기본
#: 정책에서 전부 `0` 이다. ★지문이 깨지면 먼저 이 대조를 하고, 값이 움직였으면
#: 갱신하지 말 것★ — 그것이 이 골든의 존재 이유다.
GOLDEN_SHA256 = "6958cffe20303b72b997d2439c52afae4ffb75733a33e473d2b11a6db5d29299"
GOLDEN_TRADES = 275


def test_the_numbers_do_not_move(frames):
    """호이스팅은 **값이 같은** 계산을 덜 하는 것이다 — 결과가 움직이면 실패다."""
    a, b = _golden(_run(frames)), _golden(_run(frames))
    assert a == b, "결정론이 깨졌다 — 이 비교의 전제가 없다"
    assert json.loads(a)[0], "해네스가 공허하다 — 거래가 0건이다"


def test_the_result_still_matches_the_pre_change_snapshot(frames):
    """★상수를 박아도 통과하는 테스트는 증거가 아니다★ (변이 C2)

    앞 테스트는 같은 코드로 두 번 돌려 비교한다 — `required_days` 에 `+200` 을
    **프로덕션 코드에** 박아도 두 런이 똑같이 틀리므로 통과한다. 실제로 C2 가
    그렇게 살아남았다. 비교 대상을 바깥(변경 전 코드가 낸 지문)에 두어야 한다.
    """
    g = _golden(_run(frames))
    assert len(json.loads(g)[0]) == GOLDEN_TRADES, "거래 건수가 달라졌다"
    assert hashlib.sha256(g.encode()).hexdigest() == GOLDEN_SHA256, (
        "변경 전 코드가 내던 결과와 다르다 — 호이스팅이 동작을 바꿨다")


@pytest.mark.parametrize("delta", [200, 400])
def test_the_golden_can_actually_see_a_wrong_required_days(frames, monkeypatch, delta):
    """★해네스 비공허성★ — 이 증명 없이는 위 골든이 증거가 아니다.

    처음 쓴 probe 는 `+40봉` 이었고 골든을 **하나도 바꾸지 못했다**. 시뮬레이션
    시작이 이미 프레임 145번째 봉이라 `len(df_slice) < required_days + lag` 가드가
    애초에 걸리지 않았기 때문이다 — ★적용됐다고 겨냥이 맞은 것은 아니다.★
    실제로 구속되는 값으로 흔들어야 골든이 반응한다.
    """
    base = _golden(_run(frames))
    orig = cs.ConditionStrategy.required_days
    monkeypatch.setattr(cs.ConditionStrategy, "required_days",
                        property(lambda s: orig.fget(s) + delta))
    assert _golden(_run(frames)) != base, (
        f"required_days 를 +{delta}봉 틀렸는데 골든이 그대로다 — 이 골든은 아무것도 못 본다")
