"""엔진이 **가격 정의 상태**를 결과에 싣는가 (`price_basis`)

로드맵 0단계의 넷 중 하나. 판정 규칙은 `price_quality.basis_rollup` 에 있고
(`test_price_basis_rollup.py` 가 건다), 이 파일은 **배선**을 건다:

  · 로더가 프레임에 붙여 둔 라벨이 실제로 결과까지 오는가
  · 로더가 준 라벨이 **그대로** 세어지는가(다른 필드를 읽지 않는가)
  · ★미상을 지어내지 않는가★ — 태그 없는 프레임은 `unlabeled` 이지 `missing`
    (= "행이 없다" 는 판단)이 아니다.

★배선했다고 실린 것은 아니다★ 그래서 엔진을 실제로 돌린다.

★재보고 알게 된 것 — 여기서 못 거는 것★ 수집 지점을 `copy()` **뒤로** 옮기는
변이는 이 pandas(2.2.2)에서 **아무 테스트도 죽이지 않는다.** 재봤더니 `copy`·
`iloc`·`reset_index`·`concat`·`groupby` 등 어느 연산도 `attrs` 를 떨어뜨리지
않았기 때문이다. 그러므로 이 파일은 "순서를 지킨다" 를 **주장하지 않는다** —
그 순서는 버전 편차에 대한 예방이고, 지금 관측 가능한 계약이 아니다.
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
    ROLLUP_UNLABELED,
    STATE_ADJUSTED,
)
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

BUY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
        "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]


def _frame(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=320)
    c = 10000 * np.exp(np.cumsum(rng.normal(0, .015, len(idx))))
    return pd.DataFrame({"open": c * .995, "high": c * 1.01, "low": c * .99,
                         "close": c, "volume": rng.integers(1e5, 1e6, len(idx))},
                        index=idx)


@pytest.fixture
def tagged(monkeypatch):
    """티커별로 **다른 라벨**을 붙인 프레임 셋 — 라벨이 섞여야 배선이 보인다."""
    labels = {
        "000000": (BASIS_UNIFORM_ADJUSTED, STATE_ADJUSTED),
        "000001": (BASIS_UNIFORM_ADJUSTED, STATE_ADJUSTED),
        "000002": (BASIS_MIXED, STATE_ADJUSTED),      # ★정의 혼합★
        "000003": (None, None),                        # ★태그 없음★
    }
    frames = {}
    for i, (tk, (b, a)) in enumerate(labels.items()):
        d = _frame(i + 3)
        if b is not None:
            d.attrs["price_basis"] = b
        if a is not None:
            d.attrs["adj_status"] = a
        d.attrs["source"] = "db"
        frames[tk] = d
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": frames[tk].copy()
                        if tk in frames else pd.DataFrame())
    # `.copy()` 는 `attrs` 를 보존한다 — 로더가 매번 새 프레임을 주는 상황을 흉내낸다.
    for tk, d in frames.items():
        assert d.attrs, f"픽스처 자체가 라벨을 안 들고 있다: {tk}"
    return frames


def _run(symbols) -> dict:
    return BacktestEngine(BacktestConfig(
        symbols=list(symbols), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2)).run()


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ 로더의 라벨이 결과까지 온다 (= ★`copy()` 전에 읽는다★)
# ═══════════════════════════════════════════════════════════════════════════

def test_loader_labels_reach_the_result(tagged):
    res = _run(tagged)
    assert not res.get("error"), res.get("message")
    meta = res.get("price_basis")
    assert meta is not None, "가격 정의 상태가 결과에 없다"
    assert meta["tickers"] == 4, meta
    assert meta["basis"][BASIS_UNIFORM_ADJUSTED] == 2, meta
    assert meta["basis"][BASIS_MIXED] == 1, meta


def test_a_mixed_ticker_is_named_in_the_result(tagged):
    """★이름을 낸다★ 개수만으로는 어느 종목을 고칠지 알 수 없다."""
    meta = _run(tagged)["price_basis"]
    assert meta["mixed_tickers"] == ["000002"], meta
    assert meta["state"] == "degraded", meta
    assert "000002" in (meta["reason"] or ""), meta["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# ⑫ 태그 없는 프레임은 `unlabeled` — ★스킵도 `missing` 도 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_an_untagged_frame_is_counted_as_unlabeled(tagged):
    meta = _run(tagged)["price_basis"]
    assert meta["basis"][ROLLUP_UNLABELED] == 1, meta
    assert meta["unlabeled_tickers"] == ["000003"], meta


def test_an_untagged_frame_is_not_silently_skipped(tagged):
    """★스킵하면 분모가 줄어 비율이 좋아 보인다★"""
    meta = _run(tagged)["price_basis"]
    assert meta["tickers"] == 4, "라벨 없는 종목이 분모에서 빠졌다"


# ═══════════════════════════════════════════════════════════════════════════
# ★깨끗한 실행은 깨끗하다고 말한다★ — 항상-강등 구현을 배제하는 짝
# ═══════════════════════════════════════════════════════════════════════════

def test_a_fully_clean_run_reports_ok(monkeypatch):
    frames = {}
    for i in range(3):
        d = _frame(i + 20)
        d.attrs["price_basis"] = BASIS_UNIFORM_ADJUSTED
        d.attrs["adj_status"] = STATE_ADJUSTED
        d.attrs["source"] = "db"
        frames[f"{i:06d}"] = d
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": frames[tk].copy()
                        if tk in frames else pd.DataFrame())
    meta = _run(frames)["price_basis"]
    assert meta["state"] == "ok", meta
    assert meta["reason"] is None, meta
    assert meta["uniform_adjusted_pct"] == 100.0, meta
