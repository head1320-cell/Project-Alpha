"""매크로 룩어헤드를 ★결과에 남긴다★ (`macro_lookahead`)

## 왜 라벨이 필요한가

배선(P3) 후에도 모든 토큰이 PIT 가 되지는 않는다. 빈티지 적재가 얕거나(백필은
2015 시작·스로틀), 제공자가 빈티지를 아예 주지 않으면(ECOS) 라이브로 평가된다.
그것은 ★룩어헤드★ 이고, **그 사실이 결과에 남지 않으면 소비자는 알 수 없다.**

값을 아예 안 내는 선택지도 있었지만, 그러면 매크로 조건이 조용히 무력화되어
"매크로 조건 없는 전략" 을 돌린 셈이 된다 — 그것이 더 나쁘다. 그래서 **쓰되
라벨한다.**

## 두 선례를 그대로 따른다

① ★off ⇒ `None`, 빈 dict 아님★ — `intraday_meta` 가 그렇다
   (`test_minute_bars.py::test_intraday_off_no_meta`). 매크로 토큰을 하나도 안 쓴
   전략에 `{"pit":0,"live":0,...}` 을 실으면 "재봤더니 전부 0" 으로 읽힌다.
② ★미측정 ≠ 0%★ — `_signal_path_meta` 가 분모 0 일 때 `0.0` 이 아니라 `None` 을
   낸다 (`test_signal_path_counters.py`). 같은 이유로 `pit_pct` 도 그렇다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402

from src.kis_backtest_engine import _macro_lookahead_meta  # noqa: E402
from src.kis_strategies.macro_pit_context import MacroPitContext  # noqa: E402

CAL = pd.bdate_range("2024-01-02", periods=10)


def _ctx_with(paths: dict) -> MacroPitContext:
    ctx = MacroPitContext(CAL)
    for tok, (path, reason) in paths.items():
        ctx.path[tok] = {"path": path, "reason": reason}
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# ① 안 쓴 것과 재본 것을 구별한다
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_run_without_macro_tokens_reports_nothing_at_all():
    """★H8 을 죽이는 앵커★ 빈 dict 는 "재봤더니 전부 0" 으로 읽힌다.

    `intraday_meta` 선례와 같다 — 안 켠 기능은 `None` 이다.
    """
    assert _macro_lookahead_meta(_ctx_with({})) is None


def test_no_context_at_all_reports_nothing():
    """ctx 를 못 만든 실행(엔진이 경고를 남긴다)도 `None` 이다."""
    assert _macro_lookahead_meta(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# ② 센다 — 단위는 ★실행당 토큰 1개★
# ═══════════════════════════════════════════════════════════════════════════════

def test_each_token_is_counted_once_with_its_path():
    """전부-아니면-전혀이므로 봉 단위가 아니라 토큰 단위다."""
    meta = _macro_lookahead_meta(_ctx_with({
        "US물가(전년비)": ("pit", ""),
        "US실업률": ("pit", ""),
        "국고채(10년)": ("live", "제공자가 빈티지를 주지 않습니다"),
        "US고용(전월차)": ("blocked", "빈티지 조회에 실패했습니다"),
    }))
    assert meta["pit"] == 2 and meta["live"] == 1 and meta["blocked"] == 1
    assert meta["pit_pct"] == 50.0, meta
    assert meta["tokens"]["국고채(10년)"]["path"] == "live"
    assert meta["tokens"]["국고채(10년)"]["reason"], "라이브인데 사유가 비었다"


def test_a_fully_point_in_time_run_reports_a_hundred_percent():
    meta = _macro_lookahead_meta(_ctx_with({"US실업률": ("pit", "")}))
    assert meta["pit_pct"] == 100.0
    assert meta["live"] == 0 and meta["blocked"] == 0


def test_a_pit_token_carries_no_reason():
    """★사유는 '왜 PIT 가 아닌가' 다★ PIT 인 토큰에 사유를 붙이면 읽는 사람이
    거기에도 문제가 있다고 오해한다."""
    meta = _macro_lookahead_meta(_ctx_with({"US실업률": ("pit", "")}))
    assert not meta["tokens"]["US실업률"]["reason"]


def test_a_live_token_always_carries_a_reason():
    """★사유 없는 라벨은 금지★ — `{}` 나 사유 없는 'unavailable' 은 CLAUDE.md 위반.

    사유가 없으면 사용자는 빈티지를 더 쌓아야 하는지, 제공자가 영영 못 주는지,
    DB 가 죽은 건지 구별할 수 없다 — 처방이 셋 다 다르다.
    """
    meta = _macro_lookahead_meta(_ctx_with({
        "국고채(10년)": ("live", ""),
        "US물가(전년비)": ("blocked", ""),
    }))
    for tok in ("국고채(10년)", "US물가(전년비)"):
        assert meta["tokens"][tok]["reason"], f"{tok} 에 사유가 없다"


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 룩어헤드가 있으면 ★숨기지 않는다★
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_run_with_only_live_tokens_reports_zero_percent_not_none():
    """★짝★ 위의 "안 쓰면 None" 과 구별된다.

    매크로를 **썼는데 전부 룩어헤드**인 것은 측정된 사실이다 — `0.0%` 가 맞다.
    여기서 `None` 을 내면 "안 썼다" 와 같아져 룩어헤드가 은폐된다.
    """
    meta = _macro_lookahead_meta(_ctx_with({
        "국고채(10년)": ("live", "제공자 빈티지 없음"),
    }))
    assert meta is not None
    assert meta["pit_pct"] == 0.0, meta


def test_blocked_tokens_are_in_the_denominator():
    """평가되지 못한 토큰도 "PIT 가 아니다" — 분모에서 빼면 비율이 부풀려진다."""
    meta = _macro_lookahead_meta(_ctx_with({
        "US실업률": ("pit", ""),
        "US물가(전년비)": ("blocked", "조회 실패"),
    }))
    assert meta["pit_pct"] == 50.0, meta


# ═══════════════════════════════════════════════════════════════════════════════
# ④ ★엔진이 실제로 싣는가★ — 배선했다고 실린 것은 아니다
# ═══════════════════════════════════════════════════════════════════════════════

# ★`condition_strategy` 임포트는 장식이 아니다★ 전략 레지스트리 등록이 그 임포트의
# 부작용이라, 빠지면 `get_strategy("Condition")` 이 None 을 돌려주고 엔진이 즉시
# 에러 응답을 낸다. 그 응답에는 `macro_lookahead` 키 자체가 없어 "라벨이 안 실렸다"
# 와 구별되지 않는다 — 실행이 0.4초 만에 끝나는 것이 유일한 단서였다.
import numpy as np  # noqa: E402
import pytest  # noqa: E402

import src.data.macro_observation_store as MOS  # noqa: E402
import src.data.ohlcv_loader as L  # noqa: E402
import src.data.pit_macro as PM  # noqa: E402
import src.kis_strategies.condition_strategy  # noqa: E402,F401
import src.kis_strategies.factor_tokens as FT  # noqa: E402
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

PRICE_ONLY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
               "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]
#: 매크로 레그를 하나 얹는다 — 항상 참이라 거래 자체는 가격 조건이 정한다.
WITH_MACRO = PRICE_ONLY + [{"factor_token": "US물가(전년비)", "function_id": "base",
                            "params": {}, "op": "gte", "rhs": -999}]


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
    FT._fred_cache.clear()
    FT._macro_failures.clear()
    return out


def _run(frames, conds) -> dict:
    return BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={"buy_conditions": conds, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2025-09-01", max_positions=3)).run()


def test_a_run_without_macro_conditions_carries_no_label(frames):
    """★안 쓴 것과 재본 것★ — 매크로가 없으면 결과에도 없다."""
    assert _run(frames, PRICE_ONLY).get("macro_lookahead") is None


def test_the_engine_actually_puts_the_label_in_the_result(frames, monkeypatch):
    """★배선했다고 실린 것은 아니다★ 엔진을 실제로 돌려 결과를 본다.

    빈티지도 FRED 키도 없는 환경이라 이 토큰은 `blocked` 가 된다 — 그것이 정직한
    답이고, **그 사실이 결과에 남는지**가 이 테스트의 대상이다.
    """
    monkeypatch.setattr(MOS, "load", lambda *a, **k: [])
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: None)
    meta = _run(frames, WITH_MACRO).get("macro_lookahead")
    assert meta is not None, "매크로 조건을 썼는데 결과에 라벨이 없다"
    assert "US물가(전년비)" in meta["tokens"], meta
    assert meta["tokens"]["US물가(전년비)"]["path"] == "blocked", meta
    assert meta["tokens"]["US물가(전년비)"]["reason"], "사유 없는 라벨"
    assert meta["pit_pct"] == 0.0, meta


def test_a_run_with_deep_vintages_reports_point_in_time(frames, monkeypatch):
    """★짝★ 위 테스트만 있으면 "항상 blocked" 구현도 통과한다."""
    rows = [PM.MacroObservation(
        series_id="CPIAUCSL", observation_period=f"{y}-{m:02d}-01",
        value=100.0 + m + (y - 2020) * 12,
        vintage_id=f"{y}-{m:02d}-01..9999-12-31",
        release_timestamp=f"{y}-{m:02d}-01", retrieved_at="2026-01-01")
        for y in range(2020, 2026) for m in range(1, 13)]
    monkeypatch.setattr(MOS, "load", lambda series_id=None, **k: [
        o for o in rows if series_id in (None, o.series_id)])
    meta = _run(frames, WITH_MACRO).get("macro_lookahead")
    assert meta is not None
    assert meta["tokens"]["US물가(전년비)"]["path"] == "pit", meta
    assert meta["pit_pct"] == 100.0, meta
