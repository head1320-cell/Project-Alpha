"""매매일지 — 지표. 순수 함수.

손익의 목록(거래마다 하나)을 받아 집계한다. ★분모가 0 이면 값은 `None` 이다★ — 0 이나 무한대를 만들지 않는다.
여기서 나오는 것은 전부 "올린 파일 안에서 일어난 일"의 집계다 — 앞으로의 성과를 말하지 않는다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

#: 거래가 이보다 적으면 "표본이 작다"고 적는다(통계를 숨기지는 않는다).
SMALL_SAMPLE = 30
#: 손실로 끝난 거래의 청산 뒤 이 시간(분) 안에 시작한 거래를 '손실 직후의 진입'으로 가른다.
AFTER_LOSS_MINUTES = 10

#: 보유 시간 구간 — (열쇠, 화면 이름, 이상(초), 미만(초)). 마지막은 날짜가 바뀐 거래다(초가 아니라 날짜로 가른다).
HOLDING_BUCKETS: tuple[tuple[str, str, int | None, int | None], ...] = (
    ("lt_1m", "1분 미만", 0, 60),
    ("1m_5m", "1~5분", 60, 300),
    ("5m_30m", "5~30분", 300, 1_800),
    ("30m_day", "30분~당일", 1_800, None),
    ("overnight", "하루 넘김", None, None),
)
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def summarize(pnls: Sequence[float]) -> dict:
    """거래 손익의 목록 → 승률 · 손익비 · 기대값 · PF · 손익분기 승률 · 최대 연속 손실.

    - 본전(손익 0) 거래는 승도 패도 아니다. 승률의 분모에는 들어간다.
    - 손익분기 승률 = (1 − 본전 비율) ÷ (1 + 손익비). 본전 몫을 빼야 ★승률 − 손익분기 승률의 부호가 기대값의 부호와 같다★.
    - 연속 손실은 본전 거래로 끊기지 않는다(이익 거래가 끊는다).
    """
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    flats = n - len(wins) - len(losses)
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = sum(losses) if losses else 0.0
    total = sum(pnls) if n else 0.0
    avg_win = gross_profit / len(wins) if wins else None
    avg_loss = -gross_loss / len(losses) if losses else None
    payoff = avg_win / avg_loss if avg_win is not None and avg_loss is not None else None
    win_rate = len(wins) / n if n else None
    breakeven = (1 - flats / n) / (1 + payoff) if payoff is not None else None
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "flats": flats,
        "win_rate": win_rate,
        "total": total, "gross_profit": gross_profit, "gross_loss": gross_loss,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "payoff": payoff,
        "expectancy": total / n if n else None,
        "profit_factor": gross_profit / -gross_loss if losses else None,
        "breakeven_win_rate": breakeven,
        "edge_over_breakeven": win_rate - breakeven if breakeven is not None else None,
        "max_losing_streak": _longest_losing_streak(pnls),
        "small_sample": n < SMALL_SAMPLE,
    }


def _longest_losing_streak(pnls: Iterable[float]) -> dict:
    best_count, best_amount = 0, 0.0
    count, amount = 0, 0.0
    for p in pnls:
        if p > 0:
            count, amount = 0, 0.0
        elif p < 0:
            count, amount = count + 1, amount + p
            if (count, -amount) > (best_count, -best_amount):
                best_count, best_amount = count, amount
    return {"count": best_count, "amount": best_amount}


def cumulative(points: Sequence[tuple[datetime, float]]) -> dict:
    """(청산 시각, 손익)의 목록 → 누적 실현 손익과 고점 대비 하락(원).

    고점은 ★출발선 0 에서 시작한다★ — 첫 거래가 손실이면 그것이 곧 하락이다.
    %가 아니라 원이다: 계좌 평가금액을 모르므로 수익률·MDD(%)를 만들지 않는다.
    """
    out: list[dict] = []
    cum, peak = 0.0, 0.0
    worst, worst_at = None, None
    for at, pnl in points:
        cum += pnl
        peak = max(peak, cum)
        drawdown = peak - cum
        out.append({"at": at.isoformat(), "pnl": pnl, "cum": cum, "drawdown": drawdown})
        if worst is None or drawdown > worst:
            worst, worst_at = drawdown, at.isoformat()
    return {"points": out, "max_drawdown": worst, "max_drawdown_at": worst_at if worst else None}


def holding_bucket(seconds: int, same_day: bool) -> str:
    if not same_day:
        return "overnight"
    for key, _label, low, high in HOLDING_BUCKETS[:-1]:
        if seconds >= low and (high is None or seconds < high):
            return key
    return HOLDING_BUCKETS[0][0]        # 음수는 오지 않는다(체결은 시각 순이다)


def bucket_row(key, label: str, pnls: Sequence[float], **extra) -> dict:
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    total = sum(pnls) if n else 0.0
    return {"key": key, "label": label, "n": n, "wins": wins, "losses": sum(1 for p in pnls if p < 0),
            "win_rate": wins / n if n else None, "total": total, "expectancy": total / n if n else None, **extra}
