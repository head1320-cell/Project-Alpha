"""증거 관문 판정 — ★건너뛴 관문은 통과한 관문이 아니다★ (BJ1, 순수)
==============================================================================
CLAUDE.md §1 의 관문 순서: 데이터 무결성 → 시점 정합 → 신호 타당성 → 포트폴리오 전달 →
거래비용 → 표본외 강건성 → 경제적 가치 → 모의/실계좌. 화면의 "증거 관문 레일" 이 이것을 그린다.

입력은 그래프의 노드 목록·실행 결과·노드 타입 → 워크플로우 단계 사상뿐이다. ★DB·설정·
네트워크를 읽지 않는다★(AST 테스트). 상태:

- confirmed(확인) — 이 코드가 실제로 한 일을 관측했다(계산이 끝났다 · 기준일을 기록했다).
- assumed(가정) — 입력한 가정 위에 서 있다(거래비용 10bp).
- partial(절반 확인) — 확인과 미상·가정이 섞였다.
- unknown(몰라요) — 재지 않았거나 잴 수 없다(연습용 데이터 · 출처 등급 미기록).
- skipped(건너뜀) — 그 관문을 재는 단계가 그래프에 없다.
- failed(실패) — 그 관문이 깨졌다(노드 실패 · 제약 불가).

★확인은 예측력·경제적 가치를 뜻하지 않는다★ — 경제적 가치·모의/실계좌는 이 그래프 어디에서도
확인되지 않는다(그것을 재는 노드가 없다).
"""
from __future__ import annotations

CONFIRMED, ASSUMED, PARTIAL, UNKNOWN, SKIPPED, FAILED = (
    "confirmed", "assumed", "partial", "unknown", "skipped", "failed")

GATES = [
    ("data", "데이터"), ("pit", "시점"), ("signal", "신호"), ("build", "비중 계산"),
    ("cost", "거래비용"), ("oos", "처음 보는 기간"), ("economic", "돈이 되는지"),
    ("live", "모의·실계좌"),
]

_PRACTICE = "연습용 합성 데이터예요 — 실제 시세가 아니에요."
_AXIS_PLAIN = {"window": "리밸런싱마다 그때까지의 데이터로만 비중을 정했어요",
               "as_of": "계산 기준일을 고정했어요",
               "universe": "상장폐지된 종목이 빠졌는지(생존 편향)",
               "price": "수정주가인지 원주가인지(가격 정의)"}


def _r(state: str, text: str) -> dict:
    return {"state": state, "text": text}


def _combine(reasons: list[dict]) -> str:
    states = {r["state"] for r in reasons}
    if not states:
        return SKIPPED
    if FAILED in states:
        return FAILED
    if states == {CONFIRMED}:
        return CONFIRMED
    if CONFIRMED in states:
        return PARTIAL
    if states == {ASSUMED}:
        return ASSUMED
    return UNKNOWN


def _pct_bp(bps: float) -> str:
    s = f"{bps / 100:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _not_run(r: dict) -> dict | None:
    """실패·막힘 노드의 사유. 확인이 될 수 없다."""
    st = r.get("status")
    if st == "failed":
        return _r(FAILED, f"단계가 실패했어요 — {r.get('reason') or '사유 없음'}")
    if st != "ok":
        return _r(UNKNOWN, "앞 단계에서 멈춰서 확인하지 못했어요.")
    return None


def _data(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs:
        bad = _not_run(r)
        if bad:
            out.append(bad)
            continue
        prov = r.get("provenance") or {}
        if prov.get("source") == "mock":
            out.append(_r(UNKNOWN, _PRACTICE))
        elif prov.get("data_grade"):
            out.append(_r(CONFIRMED, f"데이터 등급 {prov['data_grade']}로 기록돼 있어요."))
        else:
            out.append(_r(UNKNOWN, "데이터 출처 등급은 몰라요 — "
                                   + str(prov.get("data_grade_reason") or "기록되지 않았어요.")))
        ex = ((r.get("view") or {}).get("excluded")) or []
        if ex:
            out.append(_r(ASSUMED, f"{len(ex)}개 종목은 데이터가 모자라 빠졌어요."))
    return out


def _pit(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs:
        bad = _not_run(r)
        if bad:
            out.append(bad)
            continue
        cut = ((r.get("view") or {}).get("coverage") or {}).get("as_of_effective")
        if cut:
            out.append(_r(CONFIRMED, f"계산 기준일을 {cut}로 기록했어요."))
        out.append(_r(UNKNOWN, "그 날 실제로 알 수 있던 값인지(공표 시점)는 행마다 재지 않았어요."))
    return out


def _signal(rs: list[dict]) -> list[dict]:
    return [_not_run(r) or _r(UNKNOWN, "신호 단계는 있지만, 신호가 미래를 맞히는지 검정한 결과는 없어요.")
            for r in rs]


def _build(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs:
        bad = _not_run(r)
        if bad:
            out.append(bad)
            continue
        cr = (r.get("view") or {}).get("constraints_report") or None
        if cr and cr.get("status") == "infeasible":
            out.append(_r(FAILED, "제약을 모두 지킬 수 없었어요 — " + str(cr.get("reason") or "")))
        else:
            out.append(_r(CONFIRMED, "비중 계산이 끝났어요."))
    return out


def _cost(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs:
        bad = _not_run(r)
        if bad:
            out.append(bad)
            continue
        bps = ((r.get("view") or {}).get("config") or {}).get("cost_bps")
        if bps is None:
            out.append(_r(UNKNOWN, "거래비용을 얼마로 봤는지 기록되지 않았어요."))
        else:
            out.append(_r(ASSUMED, f"거래비용을 한 번에 {_pct_bp(float(bps))}로 가정했어요 — "
                                   "실제 체결 비용은 재지 않았어요."))
    return out


def _oos(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs:
        bad = _not_run(r)
        if bad:
            out.append(bad)
            continue
        la = (r.get("view") or {}).get("lookahead_evidence") or {}
        for a in la.get("ok_axes") or []:
            out.append(_r(CONFIRMED, _AXIS_PLAIN.get(a, a) + "."))
        for a in la.get("unknown_axes") or []:
            out.append(_r(UNKNOWN, _AXIS_PLAIN.get(a, a) + "는 재지 않았어요."))
        for a in la.get("broken_axes") or []:
            out.append(_r(FAILED, _AXIS_PLAIN.get(a, a) + "에 결함이 있어요."))
        if ((r.get("provenance") or {}).get("perf_label") or {}).get("data_real") is False:
            out.append(_r(UNKNOWN, _PRACTICE))
    return out


_SKIP = {
    "data": "수익률을 불러오는 단계가 없어요.",
    "pit": "수익률을 불러오는 단계가 없어서 기준일도 없어요.",
    "signal": "신호·알파 단계가 없어요 — 신호가 미래를 맞히는지는 재지 않았어요.",
    "build": "비중을 계산하는 단계가 없어요.",
    "cost": "과거로 돌려 보는 단계가 없어서 거래비용을 반영하지 않았어요.",
    "oos": "과거로 돌려 보는 단계가 없어서 처음 보는 기간에서는 확인하지 않았어요.",
    "economic": "비용과 위험을 뺀 뒤에도 돈이 되는지 통계로 재는 단계가 없어요.",
    "live": "모의투자·실계좌 기록과 이어지지 않았어요.",
}


def evaluate(nodes: list[dict], results: dict[str, dict], stage_of: dict[str, str]) -> dict:
    """그래프 → 8 관문 `{key, label, state, reasons[]}` + 요약."""
    def of(*types: str) -> list[dict]:
        return [results[n["id"]] for n in nodes
                if n.get("type") in types and n.get("id") in results]

    signal_types = tuple(t for t, st in stage_of.items() if st == "signal")
    rules: dict[str, list[dict]] = {
        "data": _data(of("returns")),
        "pit": _pit(of("returns")),
        "signal": _signal(of(*signal_types)) if signal_types else [],
        "build": _build(of("optimizer")),
        "cost": _cost(of("backtest")),
        "oos": _oos(of("backtest")),
        "economic": [],
        "live": [],
    }
    gates = []
    for key, label in GATES:
        reasons = rules[key] or [_r(SKIPPED, _SKIP[key])]
        gates.append({"key": key, "label": label, "state": _combine(reasons) if rules[key] else SKIPPED,
                      "reasons": reasons})
    n_ok = sum(g["state"] == CONFIRMED for g in gates)
    text = (f"{len(gates)}개 관문 중 {n_ok}개만 확인했어요." if n_ok < len(gates)
            else f"{len(gates)}개 관문을 모두 확인했어요.")
    return {"gates": gates, "summary": {"confirmed": n_ok, "total": len(gates), "text": text,
                                        "note": "끊긴 곳은 아직 재지 않은 곳이에요."}}

