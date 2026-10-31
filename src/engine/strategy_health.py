"""Strategy Health Monitoring — 슬리브·알파 건강도 (Full Expansion P5)
==============================================================================
지시서: 슬리브/알파별로 최근 IC·ICIR 악화, 성과 붕괴, 회전율 급등, 캐파 악화, 상관
상승, 국면 전환, 테마 과집중, 데이터 결측/지연, 차입 악화, 기대-실현 비용 괴리,
백테스트-실거래/모의 괴리를 표시. 상태: healthy·watch·de-risk·paused·retired.
"자동매매가 없어도 de-risk·paused 상태는 실행계획에 반영되게 하라."

★정직★: 실제 근거가 있는 신호(등록부 상태·검증 run의 IC/ICIR·검증 신선도)만 측정하고,
데이터 미연동 신호(회전율 급등·캐파·차입·백테스트 vs 실거래 괴리 등)는 'unmeasured'로
정직 표기 — 근사 날조 금지. 상태는 측정 가능한 신호에서만 판정.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

STATUSES = ("healthy", "watch", "de_risk", "paused", "retired")

# de-risk/paused는 실행계획에 반영돼야 하는 "비중 축소/중단" 상태
DERISK_STATES = ("de_risk", "paused")

# IC/ICIR 임계 (학술 관례 근사 — 러프 가이드, env 조정 가능)
_ICIR_WATCH = 0.3
_IC_WATCH = 0.02


def _run_ic(run: dict | None) -> tuple[float | None, float | None]:
    """검증 run outputs에서 Rank IC / ICIR 추출 (키 관용: rank_ic/ic, icir)."""
    if not run:
        return None, None
    out = run.get("outputs") or {}
    ic = out.get("rank_ic")
    if ic is None:
        ic = out.get("ic")
    icir = out.get("icir")
    # 중첩 validation dict도 허용
    v = out.get("validation") or {}
    ic = ic if ic is not None else v.get("rank_ic")
    icir = icir if icir is not None else v.get("icir")
    try:
        ic = float(ic) if ic is not None else None
    except (TypeError, ValueError):
        ic = None
    try:
        icir = float(icir) if icir is not None else None
    except (TypeError, ValueError):
        icir = None
    return ic, icir


# 데이터 미연동 신호 — 정직하게 'unmeasured'로 항상 표기(측정 인프라 부재)
_UNMEASURED = [
    ("turnover_spike", "회전율 급등"),
    ("capacity", "캐파 악화"),
    ("correlation_rise", "상관 상승"),
    ("borrow", "차입 가능성 악화"),
    ("cost_divergence", "기대-실현 비용 괴리"),
    ("bt_live_divergence", "백테스트 vs 실거래/모의 괴리"),
]


def _alpha_health(alpha: dict, run_getter) -> dict[str, Any]:
    status_reg = alpha.get("status")
    signals: list[dict] = []

    if status_reg == "retired":
        status = "retired"
    else:
        run = run_getter(alpha.get("last_run_id")) if alpha.get("last_run_id") else None
        ic, icir = _run_ic(run)
        # IC/ICIR 신호
        if ic is None and icir is None:
            signals.append({"key": "ic_icir", "label": "IC/ICIR", "value": None,
                            "status": "unmeasured", "basis": "unavailable",
                            "detail": "검증 리포트 없음 — 먼저 알파를 검증하세요."})
            status = "watch"
        else:
            bad = (icir is not None and icir < 0) or (ic is not None and ic < 0)
            watch = (icir is not None and icir < _ICIR_WATCH) or (ic is not None and ic < _IC_WATCH)
            sig_status = "bad" if bad else ("warn" if watch else "ok")
            signals.append({"key": "ic_icir", "label": "IC/ICIR",
                            "value": {"ic": ic, "icir": icir}, "status": sig_status, "basis": "real",
                            "detail": f"Rank IC {ic if ic is not None else '—'} · ICIR {icir if icir is not None else '—'}"})
            status = "de_risk" if bad else ("watch" if watch else "healthy")
        # 검증 신선도
        if run and run.get("created_at"):
            age_days = (time.time() - run["created_at"]) / 86400.0
            fresh = age_days < 45
            signals.append({"key": "data_freshness", "label": "검증 신선도",
                            "value": round(age_days, 1), "status": "ok" if fresh else "warn",
                            "basis": "real", "detail": f"{round(age_days, 1)}일 전 검증"})
            if not fresh and status == "healthy":
                status = "watch"

    for key, label in _UNMEASURED:
        signals.append({"key": key, "label": label, "value": None,
                        "status": "unmeasured", "basis": "unavailable"})

    return {"alpha_id": alpha.get("alpha_id"), "name": alpha.get("name"),
            "registry_status": status_reg, "status": status, "signals": signals}


def strategy_health(alphas: list[dict] | None = None,
                    run_getter=None, paused_ids: set[str] | None = None) -> dict[str, Any]:
    """등록된 알파들의 건강도. run_getter(run_id)->run(테스트 주입), 미주입 시 research_runs."""
    paused_ids = paused_ids or set()
    if run_getter is None:
        from src.data.research_runs import get_run as run_getter  # noqa: N806
    if alphas is None:
        try:
            from src.data.alpha_registry import list_alphas
            alphas = list_alphas()
        except Exception:
            alphas = []

    items = []
    for a in alphas:
        h = _alpha_health(a, run_getter)
        if a.get("alpha_id") in paused_ids:
            h["status"] = "paused"
        items.append(h)

    counts = {s: sum(1 for it in items if it["status"] == s) for s in STATUSES}
    # de-risk/paused는 실행계획에 반영(비중 축소 권고) — 목록 노출
    derisk = [it for it in items if it["status"] in DERISK_STATES]
    return {
        "items": items,
        "counts": counts,
        "n": len(items),
        "derisk_alphas": [{"alpha_id": it["alpha_id"], "name": it["name"], "status": it["status"]}
                          for it in derisk],
        "note": "상태는 측정 가능한 신호(등록부·검증 IC/ICIR·신선도)에서만 판정. 회전율·캐파·"
                "차입·백테스트 괴리 등은 데이터 미연동으로 'unmeasured'(정직). de-risk·paused "
                "알파는 실행계획에서 비중 축소/제외를 권고 — 자동 주문은 없음(지시서).",
    }
