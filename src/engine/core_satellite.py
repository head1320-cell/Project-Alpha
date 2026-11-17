"""매매 몫 결합(K4) — 핵심(배분 결과)과 위성(분봉 매매)을 국면별 매매 몫으로 합친 곡선 · ★순수 함수★
==============================================================================
구현 계획 `docs/superpowers/plans/2026-11-16-emeans-gmm-strategy.md` §7.5 · 설계 `2026-11-17-emeans-gmm-combination-design.md` §5.
파일 · 저장소 · 시계를 읽지 않는다 — 캔버스 노드(`allocation_graph_nodes_core_satellite`)가 입력을 모아 부른다.

- 핵심의 일별 수익 = 정책 백테스트의 비용 후 곡선의 이웃 비 · 위성의 일별 수익 = 분봉 시행의 비용 후 손익 ÷ 매매 몫 자본.
- 몫을 정하는 날 = 첫날과 그 뒤 달마다 첫 거래일(`month_starts`). 목표 몫 = Σ 그날 국면 확률 × 국면별 몫(`target_share`) —
  확률은 그날 시가 전에 아는 값(전 거래일 종가까지 · K1)이라 ★재조정은 그날 수익보다 먼저★다.
- 재조정 사이에는 두 몫이 각자의 수익으로 표류한다(날마다 되돌리지 않는다). 옮긴 몫 = |목표 − 표류한 지금 몫| ·
  비용 = 옮긴 몫 × 비용률 × 그때의 자본 — 시작 자본은 핵심에 있으므로 첫날 위성으로 옮기는 몫도 비용을 낸다.
- 몫 고정 판 = 같은 날 · 같은 재조정 날 · 같은 비용에 목표만 국면 몫 판의 ★날 가중 평균 목표 몫★으로 고정한 판(국면이 몫을 바꾼 것만 뺀 견줌).
- 낙폭은 정책 백테스트와 같은 관례(곡선의 점들 가운데 앞선 고점 대비).

★지어내지 않는다★: 길이 · 유한성 · −100% 이하 수익 · 확률 합 · 표 범위 · 몫을 정하는 날의 확률 빠짐 · 비용 범위가 어긋나면 `ValueError(코드)`.
반올림하지 않는다(보기용 반올림은 노드가 한다). 더 낫다 · 못하다를 판정하지 않는다 — 두 판을 나란히 낼 뿐이다.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

#: 확률 합이 1 에서 이만큼까지 벗어나도 받는다(국면 엔진의 시드 평균 · 반올림).
PROB_TOLERANCE = 1e-6


def _floats(values: Sequence[Any]) -> list[float]:
    out = [float(v) for v in values]
    if not all(math.isfinite(v) for v in out):
        raise ValueError("not_finite")
    return out


def _check_cost(cost: float) -> float:
    c = float(cost)
    if not math.isfinite(c) or c < 0 or c >= 1:
        raise ValueError("cost_out_of_range")
    return c


def _table(table: Sequence[Any]) -> list[float]:
    t = [float(v) for v in table]
    if not t or not all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in t):
        raise ValueError("table_out_of_range")
    return t


def month_starts(dates: Sequence[str]) -> list[int]:
    """몫을 정하는 날의 순번 — 첫날과, 달(연-월)이 바뀐 첫날."""
    out: list[int] = []
    prev: str | None = None
    for i, d in enumerate(dates):
        month = str(d)[:7]
        if month != prev:
            out.append(i)
            prev = month
    return out


def target_share(probs: Sequence[Any], table: Sequence[Any]) -> float:
    """목표 몫 = Σ 국면 확률 × 국면별 몫. 확률 수 = 표의 칸 수 · 확률은 0 이상이고 합이 1 · 표는 0 ~ 1."""
    t = _table(table)
    p = [float(v) for v in probs]
    if len(p) != len(t):
        raise ValueError("probs_shape")
    if not all(math.isfinite(v) and v >= 0.0 for v in p) or abs(sum(p) - 1.0) > PROB_TOLERANCE:
        raise ValueError("probs_not_one")
    return sum(a * b for a, b in zip(p, t, strict=True))


def run(core: Sequence[Any], sat: Sequence[Any], targets: Mapping[int, float], cost: float) -> dict[str, Any]:
    """한 판 — 시작 자본 1 은 모두 핵심에 있다. `targets` = {몫을 정하는 날의 순번: 위성 몫(0 ~ 1)}.

    반환: `equity`(그날 끝의 자본) · `drawdown_pct` · `share`(그날 시작 — 재조정 뒤의 위성 몫) ·
    `moves`([{i, before, after, moved, cost}]) · `cost_total`(비용으로 줄어든 자본의 합 · 시작 자본 대비) ·
    `total_return` · `max_drawdown` · `avg_share`."""
    c_ret, s_ret = _floats(core), _floats(sat)
    n = len(c_ret)
    if n == 0:
        raise ValueError("empty")
    if len(s_ret) != n:
        raise ValueError("length_mismatch")
    if any(r <= -1.0 for r in c_ret + s_ret):
        raise ValueError("return_at_or_below_minus_one")
    rate = _check_cost(cost)
    plan: dict[int, float] = {}
    for i, w in targets.items():
        w = float(w)
        if not (0 <= int(i) < n) or not math.isfinite(w) or not 0.0 <= w <= 1.0:
            raise ValueError("target_out_of_range")
        plan[int(i)] = w

    core_v, sat_v = 1.0, 0.0
    equity: list[float] = []
    share: list[float] = []
    moves: list[dict[str, Any]] = []
    cost_total = 0.0
    for i in range(n):
        if i in plan:                                    # 장 시작 전 — 전 거래일 종가에 아는 확률로 정한 몫
            value = core_v + sat_v
            before, after = sat_v / value, plan[i]
            moved = abs(after - before)
            paid = moved * rate * value
            left = value - paid
            core_v, sat_v = left * (1.0 - after), left * after
            moves.append({"i": i, "before": before, "after": after, "moved": moved, "cost": paid})
            cost_total += paid
        share.append(sat_v / (core_v + sat_v))
        core_v *= 1.0 + c_ret[i]                         # 그날의 수익은 재조정 뒤의 몫에 붙는다
        sat_v *= 1.0 + s_ret[i]
        equity.append(core_v + sat_v)

    drawdown, peak = [], -math.inf
    for e in equity:
        peak = max(peak, e)
        drawdown.append((e / peak - 1.0) * 100.0)
    return {"equity": equity, "drawdown_pct": drawdown, "share": share, "moves": moves, "cost_total": cost_total,
            "total_return": equity[-1] - 1.0, "max_drawdown": min(drawdown) / 100.0, "avg_share": sum(share) / n}


def mix(dates: Sequence[str], core: Sequence[Any], sat: Sequence[Any], probs_at: Mapping[int, Sequence[Any] | None],
        table: Sequence[Any], cost: float) -> dict[str, Any]:
    """국면 몫 판과 몫 고정 판. `probs_at` = {몫을 정하는 날의 순번: 그날 국면 확률} — 그 밖의 날의 확률은 쓰지 않는다.

    반환: `regime` · `fixed`(각 `run` 의 답) · `targets`({순번: 목표 몫}) · `fixed_share`(날 가중 평균 목표 몫) ·
    `months`([{i, date, probs, target, moved, cost}] — 국면 몫 판의 재조정)."""
    n = len(dates)
    if n == 0:
        raise ValueError("empty")
    if len(core) != n or len(sat) != n:
        raise ValueError("length_mismatch")
    _check_cost(cost)
    t = _table(table)
    starts = month_starts(dates)
    targets: dict[int, float] = {}
    probs: dict[int, list[float]] = {}
    for i in starts:
        got = probs_at.get(i)
        if got is None:
            raise ValueError("probs_missing")
        probs[i] = [float(v) for v in got]
        targets[i] = target_share(probs[i], t)
    ends = starts[1:] + [n]
    fixed_share = sum(targets[a] * (b - a) for a, b in zip(starts, ends, strict=True)) / n
    regime = run(core, sat, targets, cost)
    fixed = run(core, sat, {i: fixed_share for i in starts}, cost)
    moved = {m["i"]: m for m in regime["moves"]}
    months = [{"i": i, "date": str(dates[i]), "probs": probs[i], "target": targets[i],
               "moved": moved[i]["moved"], "cost": moved[i]["cost"]} for i in starts]
    return {"regime": regime, "fixed": fixed, "targets": targets, "fixed_share": fixed_share, "months": months}


__all__ = ["PROB_TOLERANCE", "mix", "month_starts", "run", "target_share"]
