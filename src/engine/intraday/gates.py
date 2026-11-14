"""관문 표 — 한 규칙의 결과를 일곱 관문으로 읽는다 (분봉 백테스트 설계 §8.3). 순수 함수.

    데이터 무결성 → 시점 정합 → 거래비용 → 표본외 → 비용 강건성 → 다중 비교 → 경제적 가치 · 모의·실계좌

상태 어휘는 `run_evidence` 의 셋이다 — `ok`(조건을 채웠다) · `degraded`(★관측된★ 결함이나 미달) · `unknown`(재지 못했다 — 통과가 아니다).
★건너뛴 관문은 통과한 관문이 아니다★: 경제적 가치와 모의·실계좌는 이 도구가 재지 않으므로 늘 `unknown` 으로 남고,
그래서 어떤 규칙도 일곱을 전부 통과할 수 없다. 종합 점수·등급·"쓸 만하다"는 말을 만들지 않는다 — 통과·미달·미상의 개수만 센다.

이 표가 답하는 것은 "이 규칙이 이 기간·이 종목에서 이 가정 아래 무엇을 남겼고 그 숫자를 어디까지 읽을 수 있나"다.
앞으로도 그렇다는 말이 아니고, 계좌에서 돈이 된다는 말도 아니다.
"""
from __future__ import annotations

from typing import Any

from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN
from src.engine.trade_journal.metrics import SMALL_SAMPLE

GATES = ("data_integrity", "point_in_time", "costs", "out_of_sample", "cost_robustness", "multiplicity", "economic_value")
LABELS = {"data_integrity": "데이터 무결성", "point_in_time": "시점 정합", "costs": "거래비용", "out_of_sample": "표본외",
          "cost_robustness": "비용 강건성", "multiplicity": "다중 비교", "economic_value": "경제적 가치 · 모의·실계좌"}

_SYNTHETIC_TAIL = " 합성 분봉 위의 숫자이며 예측력이나 수익의 증거가 아닙니다."


def _gate(key: str, state: str, reason: str, *facts: str) -> dict[str, Any]:
    return {"key": key, "label": LABELS[key], "state": state, "reason": reason, "facts": [f for f in facts if f]}


def _data(origin: dict, sessions: int, skipped: int) -> dict:
    if sessions <= 0:
        return _gate("data_integrity", AXIS_UNKNOWN, "쓰인 분봉이 없습니다.")
    if origin.get("grade") == "E0":
        return _gate("data_integrity", AXIS_DEGRADED, origin["grade_reason"],
                     "아래 관문의 숫자는 전부 합성 분봉 위에서 계산한 것입니다.")
    if origin.get("grade") is None:
        return _gate("data_integrity", AXIS_UNKNOWN, origin["grade_reason"])
    if skipped > 0:
        return _gate("data_integrity", AXIS_DEGRADED, f"분봉이 없거나 결함이 있어 건너뛴 종목·일자가 {skipped}건 있습니다.",
                     origin["grade_reason"])
    return _gate("data_integrity", AXIS_OK, origin["grade_reason"], "건너뛴 종목·일자가 없습니다.")


def _time(bar_label_known: bool) -> dict:
    order = "신호는 봉 종가까지로 계산하고 다음 봉 시가에 체결하므로 앞뒤 순서는 지켜집니다."
    if not bar_label_known:
        return _gate("point_in_time", AXIS_UNKNOWN,
                     "봉 시각이 그 1분의 시작인지 끝인지 확인하지 못해 시각 조건이 1분 어긋날 수 있습니다.", order)
    return _gate("point_in_time", AXIS_OK, order)


def _costs(summary: dict, slippage_ticks: int) -> dict:
    facts = ("수수료는 넣은 요율로 계산한 가정값입니다.", "매도세는 거래일과 시장과 상품으로 추론한 값입니다.",
             f"슬리피지 {slippage_ticks}틱은 가정입니다.", "시장충격과 호가 잔량과 유관기관 제비용은 재지 않았습니다.")
    if summary["trades"] <= 0:
        return _gate("costs", AXIS_UNKNOWN, "청산된 거래가 없어 비용을 판단할 것이 없습니다.", *facts)
    if summary["net_expectancy"] is None:
        return _gate("costs", AXIS_UNKNOWN, "수수료율을 넣지 않았거나 시장 구분을 모르는 종목이 있어 비용 뒤 손익을 계산하지 못했습니다.", *facts)
    return _gate("costs", AXIS_OK, "수수료와 매도세와 슬리피지를 반영했습니다.", *facts)


def _oos(oos: dict | None, views: int | None) -> dict:
    seen = ("같은 표본외 구간을 몇 번째 보는지 세지 못했습니다." if views is None
            else f"이 표본외 구간을 {views}번째 봅니다. 두 번째부터는 표본외가 아닙니다." if views >= 2 else "")
    picked = "종목은 검증 기간이 지난 뒤에 고른 것입니다. 기간은 갈랐지만 종목 선택은 사후입니다."
    if not oos or oos.get("reason") or not oos.get("out_of_sample"):
        return _gate("out_of_sample", AXIS_UNKNOWN, "거래일이 모자라 표본내와 표본외로 가르지 못했습니다.", seen, picked)
    out = oos["out_of_sample"]
    days = f"거래일의 앞 {oos['split']['in_sample_days']}일을 표본내로, 뒤 {oos['split']['out_of_sample_days']}일을 표본외로 갈랐습니다."
    if out["trades"] < SMALL_SAMPLE:
        return _gate("out_of_sample", AXIS_UNKNOWN, f"표본외 거래가 {out['trades']}건으로 {SMALL_SAMPLE}건에 못 미쳐 판단하지 않았습니다.",
                     days, seen, picked)
    if out["net_expectancy"] is None:
        return _gate("out_of_sample", AXIS_UNKNOWN, "비용 뒤 손익을 계산하지 못해 표본외를 판단하지 않았습니다.", days, seen, picked)
    if out["net_expectancy"] > 0:
        return _gate("out_of_sample", AXIS_OK, "표본외 구간에서 비용 뒤 거래당 기대값이 0 보다 큽니다.", days, seen, picked)
    return _gate("out_of_sample", AXIS_DEGRADED, "표본외 구간에서 비용 뒤 거래당 기대값이 0 이하입니다.", days, seen, picked)


def _robust(stress: dict | None) -> dict:
    how = "수수료율과 슬리피지를 두 배로 놓고 다시 계산했습니다. 세금은 법정이라 그대로 두었습니다."
    doubled = (stress or {}).get("double")
    if not doubled or doubled["net_expectancy"] is None:
        return _gate("cost_robustness", AXIS_UNKNOWN, "비용을 두 배로 놓은 계산을 하지 못했습니다.", how)
    if doubled["net_expectancy"] > 0:
        return _gate("cost_robustness", AXIS_OK, "비용을 두 배로 놓아도 거래당 기대값이 0 보다 큽니다.", how)
    return _gate("cost_robustness", AXIS_DEGRADED, "비용을 두 배로 놓으면 거래당 기대값이 0 이하입니다.", how)


def _multiplicity(m: dict | None, trial_error: str | None) -> dict:
    if not m:
        return _gate("multiplicity", AXIS_UNKNOWN, trial_error or "시행 횟수를 세지 못해 보정하지 않았습니다.")
    rule = f"기준 {m['threshold']} 는 관례 기준입니다."
    count = (f"이 종목과 기간에서 기록된 시행은 {m['n']}회입니다." if m.get("corrected")
             else f"기록된 시행이 {m['n']}회라 보정할 것이 없어 보정 전 확률을 봤습니다.")
    if m["value"] is None:
        return _gate("multiplicity", AXIS_UNKNOWN, m.get("reason") or "확률을 계산하지 못했습니다.", count, rule, m.get("note", ""))
    if m["value"] >= m["threshold"]:
        return _gate("multiplicity", AXIS_OK, "시행 횟수를 감안한 확률이 기준 이상입니다.", count, rule, m.get("note", ""))
    return _gate("multiplicity", AXIS_DEGRADED, "시행 횟수를 감안한 확률이 기준에 못 미칩니다.", count, rule, m.get("note", ""))


def build(*, origin: dict, sessions: int, skipped: int, bar_label_known: bool, summary: dict, slippage_ticks: int,
          oos: dict | None, oos_views: int | None, stress: dict | None, multiplicity: dict | None,
          trial_error: str | None = None) -> dict[str, Any]:
    """일곱 관문과 그 개수. 입력은 전부 다른 모듈이 이미 계산한 것이다 — 여기서는 판정만 한다."""
    table = [
        _data(origin, sessions, skipped),
        _time(bar_label_known),
        _costs(summary, slippage_ticks),
        _oos(oos, oos_views),
        _robust(stress),
        _multiplicity(multiplicity, trial_error),
        _gate("economic_value", AXIS_UNKNOWN, "이 도구는 실제 계좌에서의 경제적 가치와 모의·실계좌 검증을 재지 않습니다.",
              "앞의 관문을 지난 규칙도 이 관문은 지나지 않았습니다."),
    ]
    counts = {name: sum(g["state"] == state for g in table)
              for name, state in (("ok", AXIS_OK), ("degraded", AXIS_DEGRADED), ("unknown", AXIS_UNKNOWN))}
    on_synthetic = origin.get("grade") == "E0" and sessions > 0
    sentence = f"관문 일곱 가운데 통과 {counts['ok']} · 미달 {counts['degraded']} · 미상 {counts['unknown']} 입니다."
    return {"gates": table, "counts": counts, "sentence": sentence + (_SYNTHETIC_TAIL if on_synthetic else ""),
            "on_synthetic": on_synthetic}
