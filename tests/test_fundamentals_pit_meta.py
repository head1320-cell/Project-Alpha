"""재무 PIT 출처가 ★결과에 남는가★ — `fundamentals_pit` (V4 ③)

## 무엇이 문제인가

V4 가 기간마다 실측 접수일과 정적 시차 추정을 섞어 쓴다. 그 비율이 결과에 남지
않으면 사용자는 **자기 백테스트가 무엇에 기대고 있는지 알 수 없다** — 전부 실측인
실행과 전부 추정인 실행이 똑같아 보인다.

`macro_lookahead`(`kis_backtest_engine.py:109-148`)가 매크로에서 같은 일을 하고,
그 파일이 두 선례를 인용한다 — `intraday_meta`(*안 쓴 실행은 `None`*)와
`_signal_path_meta`(*미측정 ≠ 0%*). 여기서도 같은 규율을 쓴다.

## 이 파일이 거는 계약

① **안 쓴 실행은 `None`** — `{measured:0, …}` 이 아니다. 0 으로 채우면 "재봤더니
   전부 0" 으로 읽히는데 그것은 하지 않은 진술이다.
② ★짝★ **썼는데 전부 추정이면 `measured_pct: 0.0`** — 그건 측정된 사실이다.
③ `unknown`(테이블을 못 읽음)은 **분모에 남는다** — 빼면 비율이 좋아 보인다.
④ 라벨 크기가 **유니버스에 비례하지 않는다** — 재무는 종목 수백 × 기간 수십이라
   종목별 맵이면 페이로드가 터진다.
⑤ ★날짜만 실측이라는 사실을 함께 싣는다★ — 빈티지가 없는 기간은 값이 여전히
   `financials_history`(정정이 원본을 덮은 표)에서 온다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import json  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

# ★이 임포트는 장식이 아니다★ 전략 레지스트리 등록이 임포트 부작용이라, 빠지면
# `get_strategy("Condition")` 이 None 을 돌려주고 엔진이 즉시 에러 응답을 낸다.
# 그 응답에는 `fundamentals_pit` 키 자체가 없어 "라벨이 안 실렸다" 와 구별되지
# 않는다 — 세션 초반에 실제로 이 실수를 했고, 실행이 0.4초에 끝나는 것이 유일한
# 단서였다.
import src.data.dart_history as DH  # noqa: E402
import src.data.ohlcv_loader as L  # noqa: E402
import src.kis_strategies.condition_strategy  # noqa: E402,F401
from src.kis_backtest_engine import (  # noqa: E402
    BacktestConfig,
    BacktestEngine,
    _fundamentals_pit_meta,
)
from src.kis_strategies.fundamentals_pit_context import FundamentalsPitContext  # noqa: E402


def _ctx(spec: dict, *, reason=None, no_financials=()) -> FundamentalsPitContext:
    """`{종목: (measured, estimated, unknown)}` → 채워진 컨텍스트."""
    ctx = FundamentalsPitContext()
    for tk, (m, e, u) in spec.items():
        ctx._vintages[tk] = ({("2024", "11011"): [{}]} if m else {}, reason)
        ctx.record(tk, measured=m, estimated=e, unknown=u)
    for tk in no_financials:
        ctx.note_no_financials(tk)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# ① 안 쓴 것과 재본 것을 구별한다
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_context_at_all_reports_nothing():
    assert _fundamentals_pit_meta(None) is None


def test_a_context_that_observed_nothing_reports_nothing():
    """PIT 재무 토큰을 쓰지 않은 실행 — 컨텍스트는 심겼지만 아무것도 안 봤다."""
    assert _fundamentals_pit_meta(FundamentalsPitContext()) is None


def test_a_run_that_used_only_estimates_reports_zero_percent_not_none():
    """★①의 짝★ 이것이 없으면 "안 쓴 것" 과 "전부 추정" 이 같아진다.

    전자는 하지 않은 진술이고 후자는 **측정된 사실**이다.
    """
    meta = _fundamentals_pit_meta(_ctx({"005930": (0, 8, 0)}))
    assert meta is not None, "추정을 8건 썼는데 라벨이 없다"
    assert meta["measured_pct"] == 0.0, meta
    assert meta["measured"] == 0 and meta["estimated"] == 8, meta


def test_a_run_where_every_ticker_lacks_financials_is_still_reported():
    """★건너뛴 사실도 진술이다★ 조건이 거짓이었던 것과 평가되지 않은 것은 다르다."""
    meta = _fundamentals_pit_meta(_ctx({}, no_financials=("005930", "000660")))
    assert meta is not None, "조건이 통째로 건너뛰어졌는데 결과가 조용하다"
    assert meta["tickers"]["no_financials"] == 2, meta
    assert meta["measured_pct"] is None, "분모가 0인데 비율을 지어냈다"


# ═══════════════════════════════════════════════════════════════════════════════
# ② 센다 — 단위는 ★(종목, 기간)★
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_fully_measured_run_reports_a_hundred_percent():
    meta = _fundamentals_pit_meta(_ctx({"005930": (12, 0, 0)}))
    assert meta["measured_pct"] == 100.0, meta
    assert meta["estimated"] == 0 and meta["unknown"] == 0, meta


def test_unknown_stays_in_the_denominator():
    """★빼면 비율이 좋아 보인다★ 못 읽은 것은 실측이 아니다."""
    meta = _fundamentals_pit_meta(_ctx({"005930": (1, 0, 1)}, reason="못 읽었습니다"))
    assert meta["measured_pct"] == 50.0, f"unknown 을 분모에서 뺐다: {meta}"


def test_the_unit_being_counted_is_named():
    """세는 단위를 밝힌다 — 매크로는 토큰이었고 여기는 (종목, 기간) 이다."""
    meta = _fundamentals_pit_meta(_ctx({"005930": (1, 1, 0)}))
    assert meta["unit"] == "ticker_period", meta


def test_every_non_measured_reason_carries_a_sentence():
    meta = _fundamentals_pit_meta(_ctx({"005930": (0, 4, 0)}))
    for code, e in meta["reasons"].items():
        if code != "measured_filing_date":
            assert e["reason"], f"{code} 에 사유가 없다"


def test_a_measured_entry_carries_no_complaint():
    """★짝★ 실측에 사유가 붙으면 "여기도 문제가 있다" 로 읽힌다."""
    meta = _fundamentals_pit_meta(_ctx({"005930": (4, 0, 0)}))
    assert meta["reasons"]["measured_filing_date"]["reason"] == "", meta["reasons"]


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 라벨이 유니버스와 함께 자라지 않는다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_label_does_not_grow_with_the_universe():
    """★종목별 맵을 싣지 않는다★ 실행마다 저장되고 브라우저로 가고 텔레메트리에 복사된다.

    ★건수는 그대로 다 싣는다★ — 줄인 것은 사유의 **모양**이지 양이 아니다.
    """
    small = _fundamentals_pit_meta(_ctx({f"{i:06d}": (0, 40, 0) for i in range(5)}))
    big = _fundamentals_pit_meta(_ctx({f"{i:06d}": (0, 40, 0) for i in range(200)}))
    assert set(small["reasons"]) == set(big["reasons"]), "사유 종류가 유니버스를 탄다"
    for e in big["reasons"].values():
        assert len(e["sample_tickers"]) <= 3, e
    a = len(json.dumps(small, ensure_ascii=False))
    b = len(json.dumps(big, ensure_ascii=False))
    assert b - a < 200, f"유니버스 40배에 페이로드가 {b - a}바이트 늘었다"
    assert big["estimated"] == 8000, f"건수까지 줄여 버렸다: {big['estimated']}"


def test_the_sample_tickers_are_the_smallest_ones_in_order():
    """★`set` 을 그대로 자르지 않는다★ 정렬 없이 자르면 어떤 종목이 예시가 될지
    해시 순서가 정하고, 진단이 실행 환경에 따라 달라진다.

    ★같은 입력에 같은 결과★ 만으로는 부족했다 — 한 프로세스 안에서는 `set` 순회가
    안정적이라 정렬을 빼도 그 검사를 통과한다(변이 테스트가 그걸 잡았다).
    """
    spec = {f"{i:06d}": (0, 2, 0) for i in range(20)}
    e = _fundamentals_pit_meta(_ctx(spec))["reasons"]["ticker_has_no_vintages"]
    assert e["sample_tickers"] == ["000000", "000001", "000002"], e["sample_tickers"]
    assert e["tickers"] == 20, e


# ═══════════════════════════════════════════════════════════════════════════════
# ④ ★날짜만 실측이라는 사실을 숨기지 않는다★
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_label_admits_where_the_values_come_from():
    """빈티지가 없는 기간은 **값**이 여전히 정정 후 표에서 온다 — 값 축 룩어헤드.

    이걸 안 적으면 `measured_pct` 하나로 "PIT 완료" 처럼 읽힌다.
    """
    meta = _fundamentals_pit_meta(_ctx({"005930": (1, 1, 0)}))
    assert meta["value_note"], "값 축에 대해 아무 말도 하지 않는다"
    assert "financials_history" in meta["value_note"], meta["value_note"]


def test_the_label_carries_the_rule_it_used(monkeypatch):
    """추정에 쓴 시차와 당일 가드를 함께 싣는다 — ★여기서 상수를 새로 적지 않는다★

    같은 값을 두 번 적으면 갈라져도 아무도 모른다. `pit_store` 를 바꿔 라벨이
    따라오는지 본다 — 값 비교만으로는 리터럴 90/45 를 박은 구현도 통과한다
    (변이 테스트가 그걸 잡았다).
    """
    from src.engine.pit_store import FILING_SAME_DAY_GUARD_DAYS
    monkeypatch.setattr("src.engine.pit_store.ANNUAL_LAG_DAYS", 123)
    monkeypatch.setattr("src.engine.pit_store.DISCLOSURE_LAG_DAYS", 77)
    meta = _fundamentals_pit_meta(_ctx({"005930": (0, 1, 0)}))
    assert meta["lag_days"] == {"annual": 123, "quarterly": 77}, (
        f"라벨이 상수를 베꼈다: {meta['lag_days']}")
    assert meta["same_day_guard_days"] == FILING_SAME_DAY_GUARD_DAYS, meta


# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ ★엔진이 실제로 싣는가★ — 배선했다고 실린 것은 아니다
# ═══════════════════════════════════════════════════════════════════════════════

PRICE_ONLY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
               "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]
#: PIT 재무 레그를 하나 얹는다 — 항상 참이라 거래 자체는 가격 조건이 정한다.
WITH_FUND = PRICE_ONLY + [{"factor_token": "ROE", "function_id": "base",
                           "params": {}, "op": "gte", "rhs": -999}]

_HIST = [{"year": y, "reprt": "11011", "revenue": 1000e8 + y, "operating_profit": 100e8,
          "net_income": 80e8, "total_equity": 500e8, "total_liabilities": 300e8,
          "operating_cf": 90e8, "shares_outstanding": 1e8}
         for y in (2021, 2022, 2023, 2024)]


@pytest.fixture
def frames(monkeypatch):
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2023-01-02", periods=700)
    out = {}
    for i in range(4):
        c = 10000 * np.exp(np.cumsum(rng.normal(0, .018, len(idx))))
        out[f"{i:06d}"] = pd.DataFrame(
            {"open": c * .995, "high": c * 1.01, "low": c * .99,
             "close": c, "volume": rng.integers(1e5, 1e6, len(idx))}, index=idx)
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": out.get(tk, pd.DataFrame()).copy())
    monkeypatch.setattr(DH, "load_history", lambda tk: [dict(r) for r in _HIST])
    return out


def _run(frames, conds) -> dict:
    return BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={"buy_conditions": conds, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2025-09-01", max_positions=3)).run()


def test_a_run_without_pit_fundamental_conditions_carries_no_label(frames, monkeypatch):
    """★안 쓴 것과 재본 것★ — 가격만 쓰면 결과에도 없다."""
    monkeypatch.setattr(DH, "load_vintages", lambda tk, engine=None: ([], None))
    assert _run(frames, PRICE_ONLY).get("fundamentals_pit") is None


def test_the_engine_actually_puts_the_label_in_the_result(frames, monkeypatch):
    """빈티지가 없는 환경 — 전부 추정이고, **그 사실이 결과에 남는지**가 대상이다."""
    monkeypatch.setattr(DH, "load_vintages", lambda tk, engine=None: ([], None))
    meta = _run(frames, WITH_FUND).get("fundamentals_pit")
    assert meta is not None, "PIT 재무 조건을 썼는데 결과에 라벨이 없다"
    assert meta["measured"] == 0 and meta["estimated"] > 0, meta
    assert meta["measured_pct"] == 0.0, meta
    assert "ticker_has_no_vintages" in meta["reasons"], meta["reasons"]


def test_a_run_with_vintages_reports_measured(frames, monkeypatch):
    """★짝★ 위 테스트만 있으면 "항상 추정" 구현도 통과한다."""
    def _lv(tk, engine=None):
        return ([{"revenue": 1000e8, "operating_profit": 100e8, "net_income": 80e8,
                  "gross_profit": None, "total_assets": 900e8, "total_liabilities": 300e8,
                  "total_equity": 500e8, "current_assets": None, "current_liabilities": None,
                  "operating_cf": 90e8, "capex": None, "shares_outstanding": 1e8,
                  "dps": None, "year": y, "reprt": "11011", "month": 12,
                  "seq": y * 12 + 12, "rcept_no": f"{y + 1}0315000001",
                  "rcept_dt": f"{y + 1}-03-15"} for y in (2021, 2022, 2023, 2024)], None)

    monkeypatch.setattr(DH, "load_vintages", _lv)
    meta = _run(frames, WITH_FUND).get("fundamentals_pit")
    assert meta is not None
    assert meta["measured"] > 0, f"빈티지를 줬는데 실측이 0이다: {meta}"
    assert meta["measured_pct"] == 100.0, meta


# ═══════════════════════════════════════════════════════════════════════════════
# ⑥ 설치 순서 트립와이어 — ★늦게 심으면 조용히 라벨이 빈다★
# ═══════════════════════════════════════════════════════════════════════════════

#: ★호출부 문자열★ — 단어만 보면 설명 주석에 먼저 걸린다.
CALL_FUND = "strategy.set_fund_ctx("
CALL_PANEL = "strategy.prepare_panel("


def _order(src: str, a: str, b: str) -> bool:
    return a in src and b in src and src.index(a) < src.index(b)


def test_the_engine_installs_the_context_before_prepare_panel():
    """`prepare_panel` 이 이미 패널을 만들므로 그 전에 심어야 한다.

    늦게 심으면 첫 종목들의 패널이 ctx 없이 만들어져 `(종목, len(df))` 캐시에
    남고, 라벨이 조용히 비거나 병합이 일어나지 않는다.
    """
    import inspect

    # ★설명 주석이 아니라 **호출부**를 본다★ 처음엔 `"prepare_panel"` 로 찾았더니
    # 바로 위에 내가 쓴 설명 주석의 그 단어가 먼저 걸려 트립와이어가 거짓
    # 실패했다. 이 세션에서 같은 부류를 이미 한 번 겪었다(없는 함수 이름을
    # 검사하던 트립와이어).
    src = inspect.getsource(BacktestEngine.run)
    assert CALL_FUND in src, "엔진이 재무 컨텍스트를 심지 않는다"
    assert CALL_PANEL in src, "이 트립와이어가 겨냥하는 호출부가 사라졌다"
    assert _order(src, CALL_FUND, CALL_PANEL), "재무 컨텍스트를 `prepare_panel` 뒤에 심었다"


def test_the_tripwire_would_catch_a_late_installation():
    """★테스트의 테스트★ 항상 통과하는 검사를 배제한다."""
    late = f"  {CALL_PANEL}ohlcv_map)\n  {CALL_FUND}ctx)\n"
    early = f"  {CALL_FUND}ctx)\n  {CALL_PANEL}ohlcv_map)\n"
    assert not _order(late, CALL_FUND, CALL_PANEL), "늦은 설치를 못 잡는다"
    assert _order(early, CALL_FUND, CALL_PANEL), "이른 설치를 잘못 잡는다"
    # ★내가 실제로 겪은 오탐을 그대로 재현한다★ 설명 주석이 맨 단어
    # `prepare_panel` 을 먼저 쓰면, 단어로 찾는 검사는 순서를 거꾸로 읽는다.
    prose = (f"  # prepare_panel 이 이미 패널을 만들므로 그 전에 심는다\n"
             f"  {CALL_FUND}ctx)\n  {CALL_PANEL}ohlcv_map)\n")
    assert not _order(prose, "set_fund_ctx", "prepare_panel"), (
        "단어로 찾는 검사가 오탐하지 않는다 — 이 테스트의 전제가 사라졌다")
    assert _order(prose, CALL_FUND, CALL_PANEL), "호출부로 찾는데도 주석에 걸렸다"
