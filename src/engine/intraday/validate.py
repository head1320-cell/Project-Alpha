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
    "too_few_days": "거래일이 하루뿐이라 표본내와 표본외로 가를 수 없습니다.",
    "loses_before_costs": "비용 전에도 손실이라 버틸 수 있는 비용이 없습니다.",
    "no_trades": "청산된 거래가 없습니다.",
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


def out_of_sample(fills: list[dict], dates: Iterable[str], *, commission_bp: float | None,
                  master: Callable[[str], dict | None] | None = None) -> dict[str, Any]:
    """같은 체결 줄을 날짜로 갈라 표본내·표본외를 따로 계산한다."""
    split = split_dates(dates)
    if split["reason"]:
        return {"split": None, "in_sample": None, "out_of_sample": None, "reason": split["reason"]}
    out: dict[str, Any] = {"reason": None}
    for name in ("in_sample", "out_of_sample"):
        chosen = set(split[name])
        part = [f for f in fills if str(f["executed_at"])[:10] in chosen]
        out[name] = brief(analyze(part, {"commission_bp": commission_bp}, master=master))
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


def multiplicity(current: list[float], family: list[list[float]]) -> dict[str, Any]:
    """이 시행의 일별 흐름과, 같은 가족의 다른 시행들의 흐름 → PSR(0) 과 시행 횟수로 보정한 DSR.

    `value` 는 관문이 보는 값이다 — 시행이 하나면 보정할 것이 없어 PSR(0), 둘 이상이면 DSR."""
    table = deflated_sharpe.compare([{"label": "current", "returns": current},
                                     *[{"label": f"trial-{i}", "returns": r} for i, r in enumerate(family)]])
    row = table["rows"][0]
    n = table["n"]
    corrected = n >= 2
    value = row["dsr"] if corrected else row["psr0"]
    reason = row["reason"] or (table["reason"] if corrected and row["dsr"] is None else None)
    return {"n": n, "days": row["t"], "sharpe_per_day": row["sr"], "psr0": row["psr0"], "dsr": row["dsr"],
            "dsr_effective": row.get("dsr_eff"), "n_effective": table.get("n_eff"), "corrected": corrected,
            "value": value, "threshold": DSR_THRESHOLD, "reason": reason, "note": NOTE_LOWER_BOUND}
