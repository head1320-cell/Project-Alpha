"""`mixed` 종목을 만났을 때 **무엇을 하는가** — `price_basis_policy` (로드맵 4단계)

## 왜 이 파일이 있나

`price_quality` 는 오래도록 **보고만** 했다. 실측해 보니 이유가 구체적이다:
`assert_prices_backtest_eligible()` 은 **운영 호출부가 0개**이고 테스트에서만
불린다. 그래서 한 티커의 `close` 에 원주가와 수정주가가 섞였을 때
(`price_basis == "mixed"`) 백테스트가 무엇을 하는지가 **정해진 적이 없었다** —
'그냥 통과' 가 사실상의 정책이었고, ★그것이 선택된 적이 없다.★

정의가 섞인 계열로 계산한 수익률은 정의가 섞인 수익률이다. 소스 경계에서
계열이 점프하는데 그 점프는 기업행위가 아니라 **누적 수정계수 전체**라,
하루짜리 수십 % 이상치가 공분산·팩터 추정을 흔든다.

**사용자 결정: 요청별 선택, 기본은 제외.**

## ★제외는 완화이지 해결이 아니다★

그래서 이 파일은 제외가 **일어나는지**만 보지 않는다. 제외해도

  · 보고의 분모와 `mixed` 개수가 **줄지 않고**(제외 전에 센다)
  · 판정의 가격 축이 `ok` 로 **올라가지 않는다**

는 것을 함께 건다. 30종목을 조용히 버린 실행에 "검증됨" 을 다는 것이
CLAUDE.md 가 금지한 *"동등 품질로 위장"* 이다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.ohlcv_loader as L  # noqa: E402
import src.kis_strategies.condition_strategy  # noqa: E402,F401 (전략 레지스트리 등록)
from src.data.price_quality import (  # noqa: E402
    BASIS_MIXED,
    BASIS_UNIFORM_ADJUSTED,
    STATE_ADJUSTED,
)
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

BUY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
        "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]

#: 이 셋 중 `000002` 만 정의가 섞였다.
MIXED_TICKER = "000002"


def _frame(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=320)
    c = 10000 * np.exp(np.cumsum(rng.normal(0, .015, len(idx))))
    return pd.DataFrame({"open": c * .995, "high": c * 1.01, "low": c * .99,
                         "close": c, "volume": rng.integers(1e5, 1e6, len(idx))},
                        index=idx)


def _sawtooth_frame() -> pd.DataFrame:
    """★반드시 신호가 나는 계열★ — 5일 -8%% 하락과 +12%% 반등을 반복한다.

    "제외했다" 를 증명하려면 **포함됐을 때 실제로 거래되는** 종목이어야 한다.
    난수 계열은 신호가 안 날 수도 있어 그때 테스트가 공허해진다.
    """
    idx = pd.bdate_range("2023-01-02", periods=320)
    px, v = [], 10000.0
    for i in range(len(idx)):
        v *= (0.983 if (i // 6) % 2 == 0 else 1.022)
        px.append(v)
    c = np.array(px)
    return pd.DataFrame({"open": c * .999, "high": c * 1.005, "low": c * .995,
                         "close": c, "volume": np.full(len(idx), 500_000)}, index=idx)


def _install(monkeypatch, labels: dict[str, str]) -> dict:
    frames = {}
    for i, (tk, basis) in enumerate(labels.items()):
        d = _sawtooth_frame() if basis == BASIS_MIXED else _frame(i + 3)
        d.attrs["price_basis"] = basis
        d.attrs["adj_status"] = STATE_ADJUSTED
        d.attrs["source"] = "db"
        frames[tk] = d
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": frames[tk].copy()
                        if tk in frames else pd.DataFrame())
    return frames


@pytest.fixture
def mixed_one(monkeypatch) -> dict:
    return _install(monkeypatch, {
        "000000": BASIS_UNIFORM_ADJUSTED,
        "000001": BASIS_UNIFORM_ADJUSTED,
        MIXED_TICKER: BASIS_MIXED,
    })


@pytest.fixture
def all_clean(monkeypatch) -> dict:
    return _install(monkeypatch, {f"{i:06d}": BASIS_UNIFORM_ADJUSTED for i in range(3)})


def _run(symbols, **cfg_kw) -> dict:
    kw = {"buy_conditions": BUY, "sell_conditions": SELL}
    return BacktestEngine(BacktestConfig(
        symbols=list(symbols), strategy_name="Condition", strategy_params=kw,
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2,
        **cfg_kw)).run()


# ═══════════════════════════════════════════════════════════════════════════
# ① 기본값 — ★'그냥 통과' 가 더는 사실상의 정책이 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_default_policy_is_exclude():
    cfg = BacktestConfig(symbols=["000000"], strategy_name="Condition",
                         strategy_params={}, start_date="2023-01-01",
                         end_date="2023-12-31")
    assert cfg.price_basis_policy == "exclude"


def test_the_request_default_is_exclude():
    from src.api.screener_routes import ScreenToBacktestRequest
    req = ScreenToBacktestRequest(filter_ast={"logic": "AND", "conditions": [],
                                              "groups": []})
    assert req.price_basis_policy == "exclude"


# ═══════════════════════════════════════════════════════════════════════════
# ②③ 제외가 실제로 일어나고, ★짝★ 통과 정책에서는 안 일어난다
# ═══════════════════════════════════════════════════════════════════════════

def _traded(res: dict) -> set[str]:
    return {t["ticker"] for t in res["result"]["trades"]}


def test_a_mixed_ticker_does_not_trade_when_excluded(mixed_one):
    """★동작을 본다★ — 라벨이 아니라 체결이 사라져야 한다.

    ★이 테스트는 처음에 공허했다★ — `symbol_results` 의 키를 `ticker` 로 잘못
    읽어 항상 빈 집합이었고, 구현 **전에** 통과했다. 게다가 그 목록은
    `cfg.symbols` 로 만들어져 제외된 종목도 (실적 0으로) 들어 있다. 그래서
    체결 목록으로 바꿨고, 혼합 종목에는 **반드시 신호가 나는 계열**을 깔았다.
    """
    res = _run(mixed_one)
    assert not res.get("error"), res.get("message")
    assert MIXED_TICKER not in _traded(res), "제외됐어야 할 종목이 체결됐다"


def test_the_same_ticker_does_trade_when_passed(mixed_one):
    """★짝★ 위 테스트의 전제를 세운다 — 포함되면 **실제로 거래된다**.

    이것이 없으면 "신호가 안 나서 안 잡힌 것" 과 "제외돼서 안 잡힌 것" 이
    구별되지 않아, 항상-제외 구현도 항상-신호없음 픽스처도 통과한다.
    """
    res = _run(mixed_one, price_basis_policy="pass_labeled")
    assert MIXED_TICKER in _traded(res), "픽스처가 거래를 만들지 못한다 — 위 검사가 공허하다"
    meta = res["price_basis"]
    assert meta["excluded"]["count"] == 0, meta["excluded"]
    assert meta["policy"] == "pass_labeled", meta


def test_the_excluded_ticker_is_not_in_the_engine_frames(mixed_one):
    """관측 가능한 흔적 — 엔진이 든 프레임 맵에서 사라졌는가."""
    eng = BacktestEngine(BacktestConfig(
        symbols=list(mixed_one), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2))
    eng.run()
    assert MIXED_TICKER not in eng.ohlcv_all, "제외 티커가 프레임 맵에 남아 있다"
    assert "000000" in eng.ohlcv_all, "깨끗한 티커까지 사라졌다"


# ═══════════════════════════════════════════════════════════════════════════
# ④ ★보고는 줄지 않는다★ — 제외 전에 센다
# ═══════════════════════════════════════════════════════════════════════════

def test_excluding_does_not_shrink_the_report(mixed_one):
    """제외한 뒤에 세면 `mixed: 0` 이 되어 **문제가 없었던 것처럼 보인다**."""
    meta = _run(mixed_one)["price_basis"]
    assert meta["tickers"] == 3, f"분모가 줄었다: {meta}"
    assert meta["basis"][BASIS_MIXED] == 1, f"혼합 개수가 사라졌다: {meta}"
    assert meta["mixed_tickers"] == [MIXED_TICKER], meta


# ═══════════════════════════════════════════════════════════════════════════
# ⑤ 깨끗한 실행은 아무것도 잃지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_clean_run_excludes_nothing(all_clean):
    eng = BacktestEngine(BacktestConfig(
        symbols=list(all_clean), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2))
    res = eng.run()
    assert res["price_basis"]["excluded"]["count"] == 0, res["price_basis"]
    assert set(eng.ohlcv_all) == set(all_clean), "깨끗한 실행에서 종목이 사라졌다"


# ═══════════════════════════════════════════════════════════════════════════
# ★정책의 대상은 `mixed` **뿐**이다★ — 변이를 재보고 알게 된 구멍
#
# "제외 조건을 `mixed` 대신 아무 비-`uniform_adjusted` 로 넓힌다" 는 변이가
# **살아남았다.** 픽스처의 비-혼합 종목이 전부 `uniform_adjusted` 라 두 조건이
# 같은 집합을 뺐기 때문이다.
#
# 그런데 그 차이는 크다 — `uniform_raw`(전부 원주가)는 **정의가 섞이지 않았다.**
# 수정주가가 아닌 것은 별개의 문제이고, 그것까지 빼는 것은 사용자가 승인한
# 정책이 아니다(유니버스가 훨씬 크게 줄어든다).
# ═══════════════════════════════════════════════════════════════════════════

def test_a_uniform_raw_ticker_is_not_excluded(monkeypatch):
    """★섞이지 않았으면 빼지 않는다★ — 원주가인 것은 다른 문제다."""
    from src.data.price_quality import BASIS_UNIFORM_RAW
    frames = _install(monkeypatch, {
        "000000": BASIS_UNIFORM_ADJUSTED,
        "000001": BASIS_UNIFORM_RAW,
        MIXED_TICKER: BASIS_MIXED,
    })
    eng = BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2))
    res = eng.run()
    assert "000001" in eng.ohlcv_all, "원주가 종목까지 제외됐다 — 승인된 정책이 아니다"
    assert MIXED_TICKER not in eng.ohlcv_all
    assert res["price_basis"]["excluded"]["tickers"] == [MIXED_TICKER], \
        res["price_basis"]["excluded"]


def test_an_unlabeled_ticker_is_not_excluded(monkeypatch):
    """★미상은 결함이 아니다★ — 못 잰 것을 뺀다면 DB 없는 실행이 통째로 비어 버린다."""
    frames = _install(monkeypatch, {"000000": BASIS_UNIFORM_ADJUSTED})
    frames["000000"].attrs.pop("price_basis")
    eng = BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2))
    eng.run()
    assert "000000" in eng.ohlcv_all, "라벨 없는 종목이 제외됐다"


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ ★이름을 낸다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_excluded_tickers_are_named(mixed_one):
    exc = _run(mixed_one)["price_basis"]["excluded"]
    assert exc["count"] == 1, exc
    assert exc["tickers"] == [MIXED_TICKER], exc
    assert exc["reason"], "사유 없는 제외"


def test_the_reason_says_the_universe_shrank_not_that_data_was_fixed():
    """★제외는 완화이지 해결이 아니다★ 사유가 그 말을 해야 한다."""
    from src.kis_backtest_engine import EXCLUDED_REASON
    assert "제외" in EXCLUDED_REASON
    assert "고쳐진" in EXCLUDED_REASON or "줄었" in EXCLUDED_REASON


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ 전부 제외되면 ★조용히 죽지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_excluding_everything_says_why(monkeypatch):
    frames = _install(monkeypatch, {f"{i:06d}": BASIS_MIXED for i in range(3)})
    res = _run(frames)
    assert res.get("error"), "전부 제외됐는데 성공 응답이 나왔다"
    msg = res.get("message") or ""
    assert "정의" in msg or "정책" in msg, f"정책 때문인지 알 수 없는 메시지: {msg!r}"
    assert "3" in msg, f"몇 종목이 제외됐는지 없다: {msg!r}"


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ 재편입 후보풀에도 적용된다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_replenishment_pool_is_filtered_too(monkeypatch):
    """후보풀은 `symbols` 밖이지만 같은 로더를 지난다 — 빠지면 재편입으로 들어온다."""
    frames = _install(monkeypatch, {
        "000000": BASIS_UNIFORM_ADJUSTED, "000001": BASIS_UNIFORM_ADJUSTED,
        "000009": BASIS_MIXED,
    })
    eng = BacktestEngine(BacktestConfig(
        symbols=["000000", "000001"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2,
        dynamic_replenishment=True, replenishment_pool=["000009"]))
    eng.run()
    assert "000009" not in eng.ohlcv_all, "후보풀의 혼합 종목이 남아 있다"
    assert len(frames) == 3  # 픽스처가 실제로 셋을 깔았다


# ═══════════════════════════════════════════════════════════════════════════
# ⑨ ★모르는 정책을 관대하게 넘기지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unknown_policy_fails_loudly(all_clean):
    with pytest.raises(ValueError, match="price_basis_policy"):
        _run(all_clean, price_basis_policy="아무거나")


def test_the_api_rejects_an_unknown_policy():
    from pydantic import ValidationError

    from src.api.screener_routes import ScreenToBacktestRequest
    with pytest.raises(ValidationError):
        ScreenToBacktestRequest(
            filter_ast={"logic": "AND", "conditions": [], "groups": []},
            price_basis_policy="아무거나")
