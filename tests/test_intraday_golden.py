"""분봉 시뮬레이터의 골든 — ★속도를 고쳐도 체결이 한 줄도 달라지지 않는다★ (분봉 백테스트 W4b · W4d).

시뮬레이터는 "할 일이 없는 봉"을 건너뛴다(보유도 · 대기 중인 진입도 · 그 봉의 진입 조건도 없는 종목의 봉). 그 빠른 길이
모든 봉을 하나씩 지나는 느린 길과 같은 답을 내는지를, 아래 요약값이 붙든다. 요약값은 ★빠른 길을 넣기 전의 구현★에서도
같았다(이 파일을 그 커밋의 트리에서 돌려 확인했다 — HISTORY).

봉은 이 파일 안의 작은 난수기로 만든다 — 합성 분봉 생성기나 numpy 의 난수 흐름이 바뀌어도 골든이 흔들리지 않게.
규칙의 뜻은 `test_intraday_simulator.py`(손 계산)와 `test_intraday_rules.py` 가 건다. 여기는 뜻이 아니라 ★불변★만 본다:
골든이 깨졌다면 체결이 달라진 것이다 — 의도한 변경이면 손 계산 시험을 먼저 고치고 그다음 이 값을 다시 뜬다.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from src.engine import intraday
from src.engine.intraday import rules
from src.engine.intraday.simulator import CostAssumptions, Day, PositionRules
from src.engine.intraday.types import PrevDay, Session

RULES = {"available": True, "open": "0900", "closing_auction_from": "1520", "close": "1530"}
DATES = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
TICKERS = ["000660", "005930", "035720", "051910"]


def _stream(seed: int):
    x = seed
    while True:
        x = (x * 1103515245 + 12345) % 2_147_483_648
        yield x / 2_147_483_648


def _session(seed: int, ticker: str, date: str, prev: PrevDay | None, bars: int = 180) -> Session:
    r = _stream(seed)
    price = 8_000.0 + 6_000.0 * next(r)
    rows = []
    for i in range(bars):
        o = float(round(price))
        c = float(round(max(500.0, o + (next(r) - 0.5) * 90)))
        h, low = float(round(max(o, c) + next(r) * 30)), float(round(max(1.0, min(o, c) - next(r) * 30)))
        v = float(int(next(r) * 8_000)) if next(r) > 0.06 else 0.0          # 가끔 거래 없는 봉
        hh, mm = divmod(9 * 60 + i * 2, 60)                                  # 2분 간격 — 09:00 ~ 14:58
        rows.append((f"{hh:02d}{mm:02d}00", o, h, low, c, v))
        price = c
    t, o, h, low, c, v = zip(*rows)
    return Session(ticker, date, np.array(t), np.array(o), np.array(h), np.array(low), np.array(c), np.array(v), "kis", prev,
                   "KOSPI", "stock", None)


def _days() -> list[Day]:
    out, last = [], {}
    for d, date in enumerate(DATES):
        sessions = {}
        for k, ticker in enumerate(TICKERS):
            s = _session(1_000 + 97 * d + 13 * k, ticker, date, last.get(ticker))
            last[ticker] = PrevDay(close=float(s.close[-1]), high=float(s.high.max()), low=float(s.low.min()), basis="minute",
                                   date=date)
            sessions[ticker] = s
        out.append(Day(date, sessions))
    return out


SETUPS = {
    "guarded": (PositionRules(amount=3_000_000, stop_pct=0.4, target_pct=0.8, max_entries_per_ticker=3, max_open_positions=2,
                              daily_loss_limit=40_000, cooldown_after_loss_min=10, entry_from="0906", entry_until="1400"),
                CostAssumptions(commission_bp=1.5, slippage_ticks=1, participation_cap=0.05)),
    "plain": (PositionRules(amount=1_000_000, trail_pct=0.5, time_exit="1330", max_entries_per_ticker=None),
              CostAssumptions(commission_bp=None, slippage_ticks=0, participation_cap=None)),
}

#: (틀, 설정) → (체결·사건·센 것의 요약값, 체결 줄 수). 뜨는 법: 이 파일의 `_digest` 를 그대로 돌린다.
GOLDEN = {
    "opening_range_breakout/guarded": ("98d7fa509a01c9a736d3", 69),
    "opening_range_breakout/plain": ("942ceebbbd5308fcf52f", 140),
    "vwap_cross/guarded": ("9734dba4e64d787b88ec", 61),
    "vwap_cross/plain": ("b1567dd3dc3a6cfe8b09", 102),
    "volatility_breakout/guarded": ("c38ea208793c80a180c9", 28),
    "volatility_breakout/plain": ("b5a1536c1743ee684b92", 186),
    "gap/guarded": ("d71ad396c922162bf30b", 8),
    "gap/plain": ("326acaa32bf86cd7276b", 18),
    "volume_surge/guarded": ("9da763e8068cc08bfc42", 2),
    "volume_surge/plain": ("7ecbb6e390cde53c7273", 2),
    "rsi_reversal/guarded": ("aa116bfed04dd1983b42", 24),
    "rsi_reversal/plain": ("0582f0f0c63e068305b0", 56),
    "bollinger/guarded": ("93a53ca0b953d6148703", 75),
    "bollinger/plain": ("7022dc1888fb67159e09", 150),
}


def _digest(kind: str, setup: str) -> tuple[str, int]:
    position, costs = SETUPS[setup]
    out = intraday.simulate(_days(), rules.build(kind, {}), position, costs, rules=RULES)
    blob = json.dumps({k: out[k] for k in ("fills", "events", "skipped", "assumptions", "counts", "sources")}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20], len(out["fills"])


@pytest.mark.parametrize("kind", list(rules.TEMPLATES))
@pytest.mark.parametrize("setup", list(SETUPS))
def test_the_fills_are_the_ones_pinned_before_the_fast_path(kind, setup):
    assert _digest(kind, setup) == GOLDEN[f"{kind}/{setup}"]


def test_the_golden_is_not_vacuous():
    """요약값이 '체결 0줄'들만 붙들고 있으면 아무것도 지키지 못한다 — 틀마다 체결이 있고 봉을 전부 센다."""
    assert set(GOLDEN) == {f"{kind}/{setup}" for kind in rules.TEMPLATES for setup in SETUPS}
    assert sum(1 for _, fills in GOLDEN.values() if fills > 0) >= 12
    out = intraday.simulate(_days(), rules.build("vwap_cross", {}), *SETUPS["plain"], rules=RULES)
    assert out["counts"]["bars"] == len(DATES) * len(TICKERS) * 180 and out["counts"]["days"] == len(DATES)
    assert len({digest for digest, _ in GOLDEN.values()}) == len(GOLDEN)         # 설정이 다르면 요약값도 다르다
