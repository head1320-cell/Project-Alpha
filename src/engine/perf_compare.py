"""두 곡선을 맞추고 차이를 낸다 — 비교 화면 · 캔버스 비교 노드 · 현실성 탭이 같은 함수를 쓴다 (2026-11-09 · 성과 그림 문법 ③ §3.1).

★화면이 빼지 않는다★ 정렬(날짜 합집합 / 순번)의 의미가 한 곳에 있어야 세 화면이 같은 말을 한다.
- 같은 날짜가 충분하면(공통 ≥ 2 이고 짧은 쪽의 반 이상) ★날짜 합집합★ — 한쪽만 있는 날은 그쪽 None(0 아님) · 몇 날인지 센다.
- 아니면 ★순번★("1일째" …) — 같은 날끼리가 아니라는 사실을 글로 돌려준다(화면이 문장을 짓지 않는다).
- 값은 각자 ★첫 유효값을 base 로★(1 또는 100) · 차이는 (B − A) / base × 100 — base 와 무관한 %p.
지표 공식은 여기 없다(`quant_metrics` 가 단일 출처) — 이 모듈은 맞추고 빼기만 한다.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: 캔버스 비교 노드의 지표 7(이전 `_STAT_KO` — 표 7행이 E2E 계약).
NODE_METRICS: tuple[tuple[str, str, str], ...] = (
    ("total_return_pct", "총수익", "%"), ("cagr", "연평균(CAGR)", "%"), ("sharpe_ratio", "샤프", ""),
    ("max_drawdown_pct", "최대 낙폭", "%"), ("win_rate", "승률", "%"), ("num_trades", "거래 수", "회"),
    ("profit_factor", "손익비", ""),
)
#: 비교 화면의 지표 10(이전 `CMP_METRICS`).
PAGE_METRICS: tuple[tuple[str, str, str], ...] = (
    ("total_return_pct", "총수익률", "%"), ("cagr", "연평균 수익률", "%"), ("max_drawdown_pct", "최대낙폭", "%"),
    ("volatility_pct", "변동성(연)", "%"), ("sharpe_ratio", "샤프 지수", ""), ("sortino_ratio", "소르티노 지수", ""),
    ("calmar_ratio", "칼마 비율", ""), ("win_rate", "이긴 거래 비율", "%"), ("profit_factor", "손익비", ""),
    ("num_trades", "거래 수", "회"),
)
METRIC_SPECS = {"page": PAGE_METRICS, "node": NODE_METRICS}

INDEX_NOTE = "두 실행의 기간이 달라 날짜가 아니라 시작부터 {n}일째로 맞췄어요 — 같은 날끼리가 아니에요."
MISSING_NOTE = "한쪽에 없는 날이 있어요 — 그날은 그쪽 값이 비어요."


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f else None                      # NaN 은 None


def _rebase(vals: list[float | None], base: float) -> list[float | None]:
    first = next((v for v in vals if v is not None and v > 0), None)
    return [None if (v is None or first is None) else v / first * base for v in vals]


def align_curves(dates_a: Iterable[Any], eq_a: Iterable[Any], dates_b: Iterable[Any], eq_b: Iterable[Any],
                 *, base: float = 1.0) -> dict:
    """두 곡선을 맞춘다. 반환 `{alignment, x, n, common, missing_a, missing_b, base, a, b, diff_pp, note}`."""
    da = [str(d)[:10] for d in dates_a]
    db = [str(d)[:10] for d in dates_b]
    va = [_num(v) for v in eq_a]
    vb = [_num(v) for v in eq_b]
    ma = dict(zip(da, va))
    mb = dict(zip(db, vb))
    common = len(set(da) & set(db))
    shortest = min(len(da), len(db))
    if common >= 2 and common >= 0.5 * shortest:
        x = sorted(set(da) | set(db))
        a = [ma.get(d) for d in x]
        b = [mb.get(d) for d in x]
        missing_a = sum(1 for d in x if d not in ma)
        missing_b = sum(1 for d in x if d not in mb)
        note = MISSING_NOTE if (missing_a or missing_b) else None
        alignment = "date"
    else:
        n = shortest
        x = [f"{i + 1}일째" for i in range(n)]
        a, b = va[:n], vb[:n]
        missing_a = missing_b = 0
        note = INDEX_NOTE.format(n=n)
        alignment = "index"
    ra, rb = _rebase(a, float(base)), _rebase(b, float(base))
    diff = [None if (p is None or q is None) else (q - p) / float(base) * 100.0 for p, q in zip(ra, rb)]
    return {"alignment": alignment, "x": x, "n": len(x), "common": common, "missing_a": missing_a, "missing_b": missing_b,
            "base": float(base), "a": ra, "b": rb, "diff_pp": diff, "note": note}


def yearly_diff(periods_a: dict | None, periods_b: dict | None) -> list[dict]:
    """해마다 차이 — `period_returns` 출력 둘을 해 합집합으로. 한쪽이 없으면 그쪽 None · 차이 None(0 아님)."""
    ya = {int(r["year"]): r for r in ((periods_a or {}).get("yearly") or [])}
    yb = {int(r["year"]): r for r in ((periods_b or {}).get("yearly") or [])}
    out = []
    for y in sorted(set(ya) | set(yb)):
        a = _num((ya.get(y) or {}).get("return_pct"))
        b = _num((yb.get(y) or {}).get("return_pct"))
        out.append({"year": y, "a_return_pct": a, "b_return_pct": b,
                    "diff_pp": None if (a is None or b is None) else round(b - a, 4),
                    "a_partial": bool((ya.get(y) or {}).get("partial", False)),
                    "b_partial": bool((yb.get(y) or {}).get("partial", False))})
    return out


def metric_rows(stats_a: dict | None, stats_b: dict | None, spec: Iterable[tuple[str, str, str]]) -> list[dict]:
    """지표 차이 행 — 한쪽이 없으면 `diff: None`(0 이 아니다 · 화면이 "비교할 수 없어요" 라고 말한다)."""
    rows = []
    for key, label, unit in spec:
        a = _num((stats_a or {}).get(key))
        b = _num((stats_b or {}).get(key))
        rows.append({"key": key, "label": label, "unit": unit, "a": a, "b": b,
                     "diff": None if (a is None or b is None) else round(b - a, 4)})
    return rows
