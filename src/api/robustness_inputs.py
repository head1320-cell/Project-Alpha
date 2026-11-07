"""견고성 입력 (BS3) — 날짜로 줄을 세운 전략 흐름 · 끝 맞춤과의 어긋남 관측 · 시장 대용 고르기.

★왜 날짜인가★ 합치기(`sleeve_combine._load_ret_matrix` → `risk_allocations._daily_returns_matrix`)는 종목마다
종가 **값만** 받아 끝을 맞춰 줄을 세운다. 한 종목에 거래정지·상장 차이로 빠진 날이 있으면 그 앞쪽은 서로 **다른 날끼리**
짝지어진다. 여기서는 `etf_prices.daily_closes_indexed`(날짜와 종가)로 **날짜 교집합**만 쓴다 — 없는 날을 채우지 않는다.

★합치기 경로는 고치지 않는다★ 몫을 정하는 흐름을 바꾸면 배분 정책이 바뀐다(CLAUDE.md §3, 별도 승인). 대신
`alignment_check` 가 두 흐름이 다른지 관측해 보고한다 — 고칠지는 사람이 정한다.
설계: docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md §BS3
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

import numpy as np

from src.data import etf_prices

logger = logging.getLogger(__name__)

#: 한국 종목 코드 — 6자리 숫자(ETF 포함).
_KR_CODE = re.compile(r"^\d{6}$")
#: 시장 대용 — 한국은 KODEX 200(타이밍 신호 `timing_factors._KOSPI_ETF` 와 같은 대용).
KR_PROXY = ("069500", "KODEX 200")
#: 미국 기호 — 그래프는 "kr" 로 값을 매기므로 `US_TO_KR` 가 같은 길로 원화 상장 ETF 에 대응시킨다(SPY → 379800).
US_PROXY = ("SPY", "KODEX 미국S&P500 — 미국 종목을 원화 상장 ETF 로 쟀어요")


def _codes(sleeves: Sequence[dict]) -> list[str]:
    return sorted({c for s in sleeves for c, w in (s.get("weights") or {}).items() if float(w) != 0.0})


def market_proxy(tickers: Sequence[str]) -> dict[str, Any]:
    """전략이 든 종목으로 시장 대용을 고른다. 섞이면 고르지 않고 사유(전략 평균으로 위기일을 고른다 — 라벨 붙은 열화)."""
    ts = [t for t in tickers if t]
    kr = [t for t in ts if _KR_CODE.match(t)]
    us = [t for t in ts if not _KR_CODE.match(t)]
    if ts and not us:
        return {"ticker": KR_PROXY[0], "label": KR_PROXY[1], "reason": None}
    if ts and not kr:
        return {"ticker": US_PROXY[0], "label": US_PROXY[1], "reason": None}
    return {"ticker": None, "label": None,
            "reason": "한국·미국 종목이 섞여 있어 시장 하나로 위기일을 고를 수 없어요" if ts else "종목이 없어요"}


def _indexed(ticker: str, days: int) -> list[tuple[str, float]]:
    try:
        return etf_prices.daily_closes_indexed(ticker, "kr", days)
    except Exception:  # noqa: BLE001 — 빈 것으로 두고 부르는 쪽이 이름을 들어 말한다
        logger.warning("날짜 있는 종가를 못 받음: %s", ticker, exc_info=True)
        return []


def dated_sleeve_returns(sleeves: Sequence[dict], *, lookback: int = 252,
                         rebalance_every: dict[str, int] | None = None,
                         cost_bps: dict[str, float] | None = None) -> dict[str, Any]:
    """전략 흐름을 **날짜 교집합**으로 — `{available, names, S, dates}` 또는 `{available: False, reason}`.

    되돌림 주기·비용은 합치기와 같은 식(`_sleeve_return_series`)을 그대로 쓴다.
    """
    from src.engine import sleeve_combine as sc
    codes = _codes(sleeves)
    if not codes:
        return {"available": False, "reason": "비중이 있는 종목이 없어요"}
    series: dict[str, dict[str, float]] = {}
    empty = []
    for c in codes:
        rows = _indexed(c, lookback + 12)
        if len(rows) < 30:
            empty.append(c)
        else:
            series[c] = dict(rows)
    if empty:
        return {"available": False, "reason": f"날짜 있는 시세가 모자란 종목이 있어요({', '.join(empty)}) — 빼거나 기간을 줄여 주세요"}
    common = sorted(set.intersection(*(set(v) for v in series.values())))
    common = common[-(lookback + 1):]
    if len(common) < 31:
        return {"available": False, "reason": f"모든 종목에 공통인 날이 {len(common)}일뿐이라 흐름을 만들 수 없어요"}
    ret = {}
    for c, byday in series.items():
        px = np.asarray([byday[d] for d in common], dtype=float)
        ret[c] = (px[1:] / px[:-1] - 1.0).tolist()
    names, S = sc._sleeve_return_series(list(sleeves), ret, rebalance_every, cost_bps)
    if S.size == 0:
        return {"available": False, "reason": "전략 흐름을 만들 수 없어요"}
    dates = common[1:][-S.shape[0]:]
    return {"available": True, "names": names, "S": S, "dates": dates}


def alignment_check(sleeves: Sequence[dict], *, lookback: int = 252,
                    rebalance_every: dict[str, int] | None = None,
                    cost_bps: dict[str, float] | None = None,
                    dated: dict[str, Any] | None = None) -> dict[str, Any]:
    """합치기가 쓰는 끝 맞춤 흐름과 날짜 맞춤 흐름이 같은가 — ★관측만, 고치지 않는다★."""
    from src.engine import sleeve_combine as sc
    d = dated or dated_sleeve_returns(sleeves, lookback=lookback, rebalance_every=rebalance_every, cost_bps=cost_bps)
    if not d.get("available"):
        return {"same": None, "differing_days": None, "reason": f"날짜로 맞춘 흐름이 없어 비교하지 못했어요 — {d.get('reason')}"}
    _, T = sc._sleeve_return_series(list(sleeves), sc._load_ret_matrix(list(sleeves), lookback=lookback),
                                    rebalance_every, cost_bps)
    D = d["S"]
    n = min(T.shape[0], D.shape[0])
    if n == 0:
        return {"same": None, "differing_days": None, "reason": "끝 맞춤 흐름이 비어 비교하지 못했어요"}
    diff = np.abs(T[-n:] - D[-n:]).max(axis=1) > 1e-12
    k = int(diff.sum()) + abs(T.shape[0] - D.shape[0])
    if k == 0:
        return {"same": True, "differing_days": 0, "reason": None}
    return {"same": False, "differing_days": k,
            "reason": f"몫을 정하는 계산은 종목마다 끝을 맞춰 줄을 세워요 — 날짜로 맞추면 {k}일이 달라요. "
                      "견고성은 날짜로 맞춘 흐름으로 쟀고, 몫은 그대로예요."}


def market_on_dates(ticker: str, dates: Sequence[str]) -> tuple[np.ndarray | None, str | None]:
    """시장 대용의 일별 수익을 **같은 날짜**에 — 하루라도 없으면 맞추지 않고 사유."""
    rows = _indexed(ticker, len(dates) + 40)
    if not dates:
        return None, "맞출 날짜가 없어요"
    byday = dict(rows)
    order = [d for d, _ in rows]
    missing = [d for d in dates if d not in byday]
    if missing:
        return None, f"시장 대용 시세에 없는 날이 {len(missing)}일 있어 날짜를 맞출 수 없어요"
    # 구간은 전략 흐름과 같게 — 앞 날짜(전략이 빠진 날을 건너뛰었으면 그 앞)부터. 첫 구간만 시장의 바로 앞 거래일부터.
    pos = {d: i for i, d in enumerate(order)}
    first = pos[dates[0]]
    if first == 0:
        return None, "시장 대용 시세가 첫날 전을 담고 있지 않아요"
    prev = [order[first - 1], *dates[:-1]]
    out = [byday[d] / byday[p] - 1.0 for d, p in zip(dates, prev)]
    r = np.asarray(out, dtype=float)
    if not np.all(np.isfinite(r)):
        return None, "시장 대용 시세에 빈 값이 있어요"
    return r, None
