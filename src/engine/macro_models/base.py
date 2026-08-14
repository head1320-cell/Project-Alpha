"""스튜디오 공통 계약 (M1-M)
==============================================================================
다섯 스튜디오가 같은 모양으로 답하게 만드는 곳. 계약을 다섯 벌 복사하면 반드시
갈라지고, 갈라진 계약은 화면이 "어느 엔진이 낸 값인지" 를 잘못 말하게 한다.

출력 계약
------------------------------------------------------------------------------
    {available: false, engine, reason}
      또는
    {available: true, engine, outputs, note, span}

`span` 은 A8 이 세운 규칙 그대로다 — **요청보다 짧으면 응답이 그 사실을 말한다.**
표본이 모자란 것을 숨기면 화면은 짧은 구간으로 낸 값을 긴 구간의 값으로 읽는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Engine:
    """한 스튜디오 안의 엔진 하나."""
    name: str
    kind: str                       # "frontier" | "substitute"
    summary: str
    requires: tuple[str, ...] = ()  # capability.REQUIREMENTS 의 키


@dataclass(frozen=True)
class Studio:
    id: str                         # 라우트 슬러그와 같다 (`tsfm-latent` …)
    label: str
    question: str                   # 이 스튜디오가 답하는 질문 — 화면 헤더가 쓴다
    frontier: Engine
    substitute: Engine
    inputs: tuple[str, ...] = field(default_factory=tuple)   # 쓰는 시리즈 키


def unavailable(engine: str, reason: str, **extra: Any) -> dict[str, Any]:
    """숫자를 내지 않는다. **사유 없는 미가용은 만들지 않는다.**"""
    if not reason:
        raise ValueError("미가용에는 반드시 사유가 있어야 합니다.")
    return {"available": False, "engine": engine, "reason": reason, **extra}


def ok(engine: str, outputs: dict[str, Any], *, note: str | None = None,
       span: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"available": True, "engine": engine, "outputs": outputs,
            "note": note, "span": span}


def span_of(n_used: int, requested: int, first: str | None = None,
            last: str | None = None) -> dict[str, Any]:
    """★요청보다 짧으면 응답이 그 사실을 말한다 (A8 규칙)★"""
    return {"first": first, "last": last, "n": int(n_used), "requested": int(requested),
            "truncated": int(n_used) < int(requested)}


def frontier_block(engine: Engine) -> dict[str, Any]:
    """프론티어 엔진의 현재 상태 — capability 프로브를 그대로 쓴다.

    ★여기서 따로 판정하지 않는다★ 사다리와 스튜디오가 각자 판정하면 두 곳이 갈라져
    "사다리는 L1 인데 스튜디오는 프론티어가 된다고 말하는" 상태가 생긴다.
    """
    from src.engine.capability import probe_all

    p = probe_all()
    missing = [(r, p.get(r, {}).get("reason") or "미가용")
               for r in engine.requires if not p.get(r, {}).get("ok")]
    if not missing:
        return {"available": True, "engine": engine.name,
                "reason": None,
                "note": "요건은 충족됐지만 이 엔진의 구현은 아직 없습니다 — 계약만 존재합니다."}
    return unavailable(
        engine.name,
        " / ".join(f"{k}: {v}" for k, v in missing),
        missing=[k for k, _ in missing])


# ── 레지스트리 ──────────────────────────────────────────────────────────────
# 실제 실행 함수는 각 모듈이 갖는다. 여기서는 지연 import 로 묶는다 —
# 스튜디오 하나가 죽어도 나머지 넷은 답해야 한다.
_RUNNERS: dict[str, str] = {
    "tsfm-latent": "src.engine.macro_models.tsfm_latent",
    "neural-sde": "src.engine.macro_models.neural_sde",
    "causal-deepm": "src.engine.macro_models.causal_deepm",
    "pinn-tail": "src.engine.macro_models.pinn_tail",
    "agentic-mcp": "src.engine.macro_models.agentic_views",
}


def _module(studio_id: str):
    import importlib
    return importlib.import_module(_RUNNERS[studio_id])


def STUDIOS() -> list[Studio]:  # noqa: N802 — 상수처럼 쓰이는 접근자
    out: list[Studio] = []
    for sid in _RUNNERS:
        try:
            out.append(_module(sid).STUDIO)
        except Exception as e:  # noqa: BLE001
            logger.warning("스튜디오 정의를 읽지 못했습니다 (%s): %s", sid, e)
    return out


def describe_all() -> list[dict[str, Any]]:
    """스튜디오 목록 + 두 엔진의 현재 상태. 화면 내비게이션이 쓴다."""
    out = []
    for s in STUDIOS():
        out.append({
            "id": s.id, "label": s.label, "question": s.question,
            "inputs": list(s.inputs),
            "frontier": {"name": s.frontier.name, "summary": s.frontier.summary,
                         "requires": list(s.frontier.requires),
                         **frontier_block(s.frontier)},
            "substitute": {"name": s.substitute.name, "summary": s.substitute.summary,
                           "requires": list(s.substitute.requires)},
        })
    return out


def run_studio(studio_id: str, **kwargs: Any) -> dict[str, Any]:
    """대체 엔진을 돌린다. 프론티어는 계약만 있으므로 `describe_all` 이 상태를 답한다."""
    if studio_id not in _RUNNERS:
        return {"available": False, "engine": None,
                "reason": f"그런 스튜디오가 없습니다: {studio_id}"}
    try:
        mod = _module(studio_id)
    except Exception as e:  # noqa: BLE001
        return unavailable(studio_id, f"스튜디오를 불러오지 못했습니다: {e}")
    try:
        return mod.run(**kwargs)
    except Exception as e:  # noqa: BLE001 — 한 스튜디오가 죽어도 화면은 사유를 받아야 한다
        logger.exception("스튜디오 실행 실패: %s", studio_id)
        return unavailable(mod.STUDIO.substitute.name, f"실행 중 오류: {type(e).__name__}: {e}")


def load_series(keys: tuple[str, ...], months: int) -> dict[str, list[float]]:
    """매크로 시계열을 키로 뽑아 최근 `months` 개로 자른다.

    없는 키는 **조용히 빼지 않고** 호출자가 알 수 있게 결과에서 누락시킨다 —
    각 스튜디오가 "무엇이 없어서 못 했는지" 를 사유로 적을 수 있어야 한다.
    """
    from src.services.macro_collector import MacroCollector

    snap = MacroCollector().collect_all(use_cache=True)
    out: dict[str, list[float]] = {}
    for k in keys:
        s = getattr(snap, "series", {}).get(k)
        if s is None or not s.values:
            continue
        vals = [float(v) for v in s.values if v is not None]
        if vals:
            out[k] = vals[-months:]
    return out


def series_span(snap_keys: dict[str, list[float]], months: int) -> dict[str, Any]:
    n = min((len(v) for v in snap_keys.values()), default=0)
    return span_of(n, months)
