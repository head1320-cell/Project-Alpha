"""기간별 수익·낙폭 구간이 세 성과 뷰에 실리고, 서버가 그 사실을 한 줄로 말한다 (2026-11-09).

- 정책 백테스트(`walk_forward`) 출력에 `periods`·`drawdowns` 가 있고, 같은 곡선에서 다시 뽑은 것과 같다(두 벌이 아니다).
- 설명(`explain_backtest`)은 가장 깊은 낙폭 구간을 한 문장으로 — 회복했으면 며칠 걸렸는지, 못 했으면 그렇다고.
  ★짝★ 사건이 없으면 그 문장이 없다(0 일·0% 를 지어내지 않는다). 금지어 0.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.api.allocation_graph_explain import drawdown_fact, explain_backtest  # noqa: E402
from src.engine.allocation_backtest import walk_forward  # noqa: E402
from src.engine.quant_metrics import drawdown_episodes, period_returns  # noqa: E402

# 금지어 목록은 그 시험 파일이 갖는다 — 설명 모듈 소스에 그 낱말을 리터럴로 두면 AST 전수 시험이 빨개진다.
from tests.test_allocation_graph_explain import FORBIDDEN as FORBIDDEN_WORDS  # noqa: E402


def _run():
    rng = np.random.default_rng(3)
    R = rng.standard_normal((400, 3)) * np.array([0.010, 0.008, 0.014]) + np.array([0.0004, 0.0002, 0.0006])
    dates = list(pd.bdate_range("2023-01-02", periods=400))
    return walk_forward(["A", "B", "C"], R, dates, model="mvo", rebalance="M", cost_bps=10)


def test_walk_forward_carries_periods_and_drawdowns_from_its_own_curve():
    out = _run()
    assert out["periods"] == period_returns(out["dates"], out["equity_curve"])
    assert out["drawdowns"] == drawdown_episodes(out["dates"], out["equity_curve"], top=3)
    assert out["periods"]["yearly"] and out["drawdowns"]            # 400 거래일이면 둘 다 비지 않는다
    assert all(y["year"] in (2023, 2024) for y in out["periods"]["yearly"])


def test_drawdown_fact_tells_recovery_or_says_not_yet():
    recovered = {"drawdowns": [{"peak_date": "2024-02-01", "trough_date": "2024-02-20", "recovery_date": "2024-04-10",
                                "depth_pct": -12.3456, "days_to_trough": 19, "days_to_recover": 69}]}
    s = drawdown_fact(recovered)
    assert s is not None and "2024-02-01" in s and "12.3%" in s and "19일" in s and "69일" in s
    stuck = {"drawdowns": [{"peak_date": "2024-02-01", "trough_date": "2024-02-20", "recovery_date": None,
                            "depth_pct": -8.0, "days_to_trough": 19, "days_to_recover": None}]}
    s2 = drawdown_fact(stuck)
    assert s2 is not None and "아직" in s2 and "None" not in s2 and "0일" not in s2
    # ★짝★ 사건이 없으면 문장도 없다.
    assert drawdown_fact({"drawdowns": []}) is None and drawdown_fact({}) is None
    for s_ in (s, s2):
        assert not any(w in s_ for w in FORBIDDEN_WORDS)


def test_explain_backtest_includes_the_drawdown_fact_only_when_there_is_one():
    out = _run()
    ex = explain_backtest(out, {}, None)
    assert any("낙폭" in f and out["drawdowns"][0]["peak_date"] in f for f in ex["facts"])
    flat = dict(out, drawdowns=[])
    assert not any("고점" in f for f in explain_backtest(flat, {}, None)["facts"])
