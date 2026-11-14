"""판정의 계산부 — 표본외 분할 · 일별 흐름 · 손익분기 비용 · 다중 비교 (분봉 백테스트 설계 §8). 순수 함수.

여기서 하는 일은 ★나누고 세는 것★이다. 손익과 비용의 정의는 매매일지 엔진 하나가 갖는다(`trade_journal.analyze`) —
표본내와 표본외는 ★같은 체결 줄★을 날짜로 갈라 같은 엔진에 넣은 것이라, 두 숫자의 정의가 어긋날 수 없다.

- 분할은 시간순이다. 섞지 않고, 돌리기 전에 정해진 비율(앞 70%)로 가른다.
- 거래가 없던 날도 하루다 — 일별 흐름에 0 으로 들어간다(빼면 샤프가 부풀려진다).
- 값이 없는 것을 0 으로 내지 않는다: 수수료율을 모르면 비용 뒤 값은 `None`, 흐름이 짧으면 확률은 `None` + 사유.
- 다중 비교의 N 은 ★하한★이다. 이 도구 밖에서 해 본 시도는 세지 못한다.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

from src.engine import deflated_sharpe
from src.engine.trade_journal import analyze

#: 표본내에 두는 거래일의 비율(앞쪽). 관례값이며 재 본 값이 아니다 — 답에 함께 싣는다.
IS_FRACTION = 0.7
#: 다중 비교 관문의 기준 — 관례 기준(Bailey · López de Prado)이다. 답에 관례라고 적는다.
DSR_THRESHOLD = 0.95

REASONS = {
    "too_few_days": "거래일이 모자라 구간으로 가를 수 없습니다.",
    "loses_before_costs": "비용 전에도 손실이라 버틸 수 있는 비용이 없습니다.",
    "no_trades": "청산된 거래가 없습니다.",
    "net_unknown": "수수료율을 넣지 않았거나 시장 구분을 모르는 종목이 있어 비용 뒤 손익이 없습니다. 비용 전 손익으로 대신 계산하지 않았습니다.",
    "different_days": "기간이 다른 시행이 섞여 있어 시행끼리 얼마나 닮았는지는 재지 않았습니다.",
    "no_choice": "고르는 구간에 거래가 있는 칸이 없어 다음 구간에 적용할 것을 고르지 못했습니다.",
}

NOTE_LOWER_BOUND = "시행 횟수는 이 도구에 기록된 것만 센 하한입니다. 기록 밖에서 해 본 시도는 세지 못해 그만큼 보정이 약합니다."


def split_dates(dates: Iterable[str]) -> dict[str, Any]:
    """거래일을 시간순으로 앞 70% · 뒤 30% 로 가른다(양쪽에 적어도 하루)."""
    days = sorted(set(dates))
    if len(days) < 2:
        return {"in_sample": [], "out_of_sample": [], "reason": "too_few_days"}
    cut = max(1, min(len(days) - 1, math.floor(len(days) * IS_FRACTION + 1e-9)))
    return {"in_sample": days[:cut], "out_of_sample": days[cut:], "reason": None}


def brief(journal: dict) -> dict[str, Any]:
    """매매일지에서 판정에 쓰는 수만 — 비용 전은 늘 있고, 비용 뒤는 모르면 `None` 이다."""
    gross, net = journal["summary"]["gross"], journal["summary"]["net"]
    return {"trades": gross["n"], "gross_total": gross["total"], "gross_expectancy": gross["expectancy"],
            "net_total": net["total"] if net else None, "net_expectancy": net["expectancy"] if net else None,
            "win_rate": (net or gross)["win_rate"], "basis": journal["basis"]["pnl_basis"]}


def result(fills: list[dict], *, commission_bp: float | None, assume: dict | None = None,
           master: Callable[[str], dict | None] | None = None) -> dict[str, Any]:
    """체결 줄 → 판정에 쓰는 요약. 체결은 수수료율과 무관하므로 ★다른 수수료율★로 볼 때 다시 돌릴 필요가 없다.

    `assume` 은 시장 구분을 모르는 종목에 대한 사용자의 가정(`unknown_market` · `unknown_instrument`)이다 — 없으면 모른다."""
    return brief(analyze(fills, {"commission_bp": commission_bp, **(assume or {})}, master=master))


def out_of_sample(fills: list[dict], dates: Iterable[str], *, commission_bp: float | None, assume: dict | None = None,
                  master: Callable[[str], dict | None] | None = None) -> dict[str, Any]:
    """같은 체결 줄을 날짜로 갈라 표본내·표본외를 따로 계산한다."""
    split = split_dates(dates)
    if split["reason"]:
        return {"split": None, "in_sample": None, "out_of_sample": None, "reason": split["reason"]}
    out: dict[str, Any] = {"reason": None}
    for name in ("in_sample", "out_of_sample"):
        chosen = set(split[name])
        part = [f for f in fills if str(f["executed_at"])[:10] in chosen]
        out[name] = result(part, commission_bp=commission_bp, assume=assume, master=master)
    first, last = split["in_sample"], split["out_of_sample"]
    out["split"] = {"in_sample_days": len(first), "out_of_sample_days": len(last), "in_sample_from": first[0],
                    "in_sample_to": first[-1], "out_of_sample_from": last[0], "out_of_sample_to": last[-1],
                    "fraction": IS_FRACTION}
    return out


def daily_values(journal: dict, dates: Iterable[str]) -> dict[str, Any]:
    """기간 안 ★모든 거래일★의 일별 손익 — 거래가 없던 날은 0. `basis` 는 그 값이 비용 뒤인지 전인지."""
    by_day = {row["key"]: float(row["total"]) for row in journal["breakdowns"]["daily"]}
    return {"basis": journal["breakdowns"]["basis"], "values": [by_day.get(d, 0.0) for d in sorted(set(dates))]}


def breakeven_cost(journal: dict) -> dict[str, Any]:
    """손익분기 비용(편도 bp) = 비용 전 총손익 ÷ 총 거래대금 × 10,000 — 편도 비용이 이만큼이면 손익이 0 이 된다.

    `spent_bp` 는 실제로 든 비용(같은 단위 — 일지의 `bp_of_turnover`)이고, 비용을 모르면 `None` 이다."""
    gross, costs = journal["summary"]["gross"], journal["summary"]["costs"]
    turnover = costs.get("turnover")
    out = {"bp": None, "turnover": turnover, "spent_bp": costs.get("bp_of_turnover"), "reason": None}
    if not gross["n"] or not turnover:
        out["reason"] = "no_trades"
    elif gross["total"] <= 0:
        out["reason"] = "loses_before_costs"
    else:
        out["bp"] = gross["total"] / turnover * 10_000
    return out


def multiplicity(current: list[float] | None, family: list[list[float] | None], *, same_days: bool = True) -> dict[str, Any]:
    """이 시행의 일별 흐름과, 같은 가족의 다른 시행들의 흐름 → PSR(0) 과 시행 횟수로 보정한 DSR.

    `value` 는 관문이 보는 값이다 — 시행이 하나면 보정할 것이 없어 PSR(0), 둘 이상이면 DSR.
    흐름이 `None` 인 시행(비용 뒤 손익이 없다)도 ★시행 횟수에는 든다★ — 해 본 것은 해 본 것이다. 샤프의 흩어짐에만 들지 않는다.
    `same_days` 가 거짓이면(기간이 다른 시행이 섞였다) 닮음으로 줄인 수(`n_effective`)는 내지 않는다 — 날이 어긋난 흐름의 상관은 뜻이 없다."""
    n = 1 + len(family)
    unscored = sum(r is None for r in family)
    blank = {"n": n, "days": None, "sharpe_per_day": None, "psr0": None, "dsr": None, "dsr_effective": None,
             "n_effective": None, "n_effective_reason": None, "corrected": n >= 2, "unscored": unscored, "value": None,
             "threshold": DSR_THRESHOLD, "reason": REASONS["net_unknown"], "note": NOTE_LOWER_BOUND}
    if current is None:
        return blank
    table = deflated_sharpe.compare([{"label": "current", "returns": current},
                                     *[{"label": f"trial-{i}", "returns": r or []} for i, r in enumerate(family)]])
    row = table["rows"][0]
    corrected = n >= 2
    value = row["dsr"] if corrected else row["psr0"]
    reason = row["reason"] or (table["reason"] if corrected and row["dsr"] is None else None)
    return {**blank, "days": row["t"], "sharpe_per_day": row["sr"], "psr0": row["psr0"], "dsr": row["dsr"],
            "dsr_effective": row.get("dsr_eff") if same_days else None,
            "n_effective": table.get("n_eff") if same_days else None,
            "n_effective_reason": table.get("n_eff_reason") if same_days else REASONS["different_days"],
            "value": value, "reason": reason}


def fold_dates(dates: Iterable[str], folds: int) -> list[list[str]]:
    """거래일을 시간순으로 이어진 `folds` 개 구간으로 — 길이는 되도록 같게(앞 구간이 하루 더 길 수 있다). 날이 모자라면 빈 목록."""
    days = sorted(set(dates))
    if folds < 2 or len(days) < folds:
        return []
    size, extra = divmod(len(days), folds)
    out, at = [], 0
    for k in range(folds):
        step = size + (1 if k < extra else 0)
        out.append(days[at:at + step])
        at += step
    return out


def walk_forward(cells: list[list[dict]], dates: Iterable[str], folds: int, *, commission_bp: float | None,
                 assume: dict | None = None, master: Callable[[str], dict | None] | None = None) -> dict[str, Any]:
    """미리 선언한 칸들 가운데, 구간 k 에서 비용 뒤 거래당 기대값이 가장 큰 칸을 ★구간 k+1 에★ 적용해 이어 붙인다.

    `cells[i]` 는 칸 i 를 기간 전체에 돌린 체결 줄이다(하루를 넘기는 보유가 없어 날짜로 자르면 그 구간만 돌린 것과 같다).
    고르는 데 쓰는 것은 앞 구간의 숫자뿐이다 — 적용할 구간은 고를 때 보지 않는다. 첫 구간은 고르는 데만 쓰인다.
    값이 같으면 먼저 선언한 칸. 거래가 없는 칸은 고르지 않는다. 비용 뒤 손익이 없으면 비용 전으로 대신 고르지 않는다(사유)."""
    parts = fold_dates(dates, folds)
    out: dict[str, Any] = {"folds": folds, "steps": [], "stitched": None, "reason": None}
    if not parts:
        return {**out, "reason": "too_few_days"}

    def on(i: int, days: list[str]) -> tuple[list[dict], dict]:
        chosen = set(days)
        part = [f for f in cells[i] if str(f["executed_at"])[:10] in chosen]
        return part, result(part, commission_bp=commission_bp, assume=assume, master=master)

    steps, kept = [], []
    for k in range(len(parts) - 1):
        seen = [on(i, parts[k])[1] for i in range(len(cells))]
        if any(b["trades"] and b["net_expectancy"] is None for b in seen):
            return {**out, "reason": "net_unknown"}
        candidates = [b["net_expectancy"] if b["trades"] else None for b in seen]
        step = {"choose": {"from": parts[k][0], "to": parts[k][-1]}, "apply": {"from": parts[k + 1][0], "to": parts[k + 1][-1]},
                "candidates": candidates, "chosen": None, "chosen_expectancy": None, "applied": None, "reason": "no_choice"}
        scored = [(value, i) for i, value in enumerate(candidates) if value is not None]
        if scored:
            best = max(value for value, _ in scored)
            index = next(i for value, i in scored if value == best)
            fills, applied = on(index, parts[k + 1])
            kept.extend(fills)
            step.update(chosen=index, chosen_expectancy=best, applied=applied, reason=None)
        steps.append(step)
    chose = any(s["chosen"] is not None for s in steps)
    stitched = result(kept, commission_bp=commission_bp, assume=assume, master=master) if chose else None
    return {**out, "steps": steps, "stitched": stitched}
