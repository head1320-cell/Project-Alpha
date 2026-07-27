"""현재 국면 → RegimeSnapshot 빌더.

라이브 매크로 엔진(regime_analyzer)의 판정을 불변 스냅샷으로 굳혀, AAS 가 ID 로 참조할 수
있게 한다. 지금까지 AAS 는 ["macro","regime"] 라이브 쿼리 세 곳(ContextStrip · GoalGate ·
journal)으로 **항상 오늘의 국면**만 봤고, 어떤 국면에서 내린 결정인지 남는 곳이 없었다.

★정직성 규약★
──────────────────────────────────────────────────────────────────────────────
대시보드 수집기(MacroCollector)는 아직 빈티지를 모른다 — ALFRED 경로는 Phase 7b 다.
그래서 여기서 만든 관측치는:

  · vintage_id = ""        → 개정 이력을 재구성할 수 없다
  · data_status = partial  → 공표시각을 확정할 수 없다 (MOCK 출처면 mock)

두 값이 regime_snapshots._derive_usage / _derive_status 를 통과하면서 스냅샷 전체가
**forward_only + partial** 로 떨어진다. 즉 이 스냅샷은 전방(forward) 리서치 맥락으로는
쓸 수 있지만 과거 시뮬레이션에서는 구조적으로 차단된다.

관측일(observation_period)을 공표시각(release_timestamp)으로 베끼면 스냅샷이
backtest_eligible 로 보이게 되는데, 그것이 정확히 이 프로젝트가 막으려는 조용한 날조다.
수집기가 주는 last_update(우리가 그 값을 관측한 시각)를 쓰고, 그마저 없으면 관측일로
폴백하되 partial 딱지를 유지한다.
"""
from __future__ import annotations

import logging
from typing import Any

from src.data.pit_macro import DataStatus, MacroObservation
from src.data.regime_snapshots import create_snapshot

logger = logging.getLogger(__name__)


def _collect(market: str) -> tuple[Any, Any]:
    """국면 상태 + 원천 매크로 스냅샷을 **한 번의 수집으로** 얻는다.

    테스트에서 monkeypatch 하는 단일 지점 (네트워크 격리).
    """
    from src.engine.regime_analyzer import RegimeAnalyzer
    analyzer = RegimeAnalyzer()
    macro_snap = analyzer.collector.collect_all(use_cache=True)
    state = analyzer.analyze(macro_snap, market=market)
    return state, macro_snap


def observations_from_series(macro_snap: Any) -> list[MacroObservation]:
    """MacroSeries 들을 관측치 신원으로 변환. 값이 없는 시리즈는 **건너뛴다**(0 으로 채우지 않음)."""
    out: list[MacroObservation] = []
    for key, s in (getattr(macro_snap, "series", {}) or {}).items():
        timestamps = getattr(s, "timestamps", None) or []
        values = getattr(s, "values", None) or []
        if not timestamps or not values:
            continue
        try:
            value = float(values[-1])
        except (TypeError, ValueError):
            continue

        period = str(timestamps[-1])
        source = (getattr(s, "source", "") or "").upper()
        # MOCK 출처는 mock, 그 외에는 공표시각 미확정이므로 partial (real 이 아니다).
        status = DataStatus.MOCK if source == "MOCK" else DataStatus.PARTIAL
        # last_update = 우리가 그 값을 관측한 시각. 진짜 공표시각은 아니지만 관측일보다는
        # 사실에 가깝고, partial + vintage 없음이 오용을 막는다.
        released = str(getattr(s, "last_update", None) or period)

        out.append(MacroObservation(
            series_id=getattr(s, "indicator", None) or str(key),
            observation_period=period,
            release_timestamp=released,
            vintage_id="",                 # ★수집기는 빈티지를 모른다★ → forward_only 유발
            retrieved_at=str(getattr(macro_snap, "timestamp", "") or ""),
            value=value,
            data_status=status,
        ))
    return out


def build_and_store(market: str = "kr") -> str | None:
    """현재 국면을 스냅샷으로 굳힌다. 성공 시 snapshot_id, DB 미가용 시 None.

    수집·판정 실패는 삼키지 않는다 — 조용히 0 을 반환하면 호출자가 그것을 국면으로 믿는다.
    """
    state, macro_snap = _collect(market)
    observations = observations_from_series(macro_snap)

    regime = getattr(state, "regime", "") or "UNKNOWN"
    mode = getattr(state, "recommended_mode", "") or "NORMAL"
    desc = getattr(state, "description", "") or ""
    # 권고 모드를 설명에 남긴다 — AAS 매핑 미리보기가 "무엇이 적용될지"를 이 문자열로 보여준다.
    explanation = f"[{regime} · 권고 {mode}] {desc}".strip()

    as_of = str(getattr(state, "timestamp", "") or "")

    return create_snapshot(
        as_of=as_of,
        observations=observations,
        growth_axis=float(getattr(state, "growth_axis", 0.0) or 0.0),
        inflation_axis=float(getattr(state, "inflation_axis", 0.0) or 0.0),
        phase_probabilities=dict(getattr(state, "regime_probs", {}) or {}),
        stress_score=float(getattr(state, "stress_score", 0.0) or 0.0),
        confidence=float(getattr(state, "confidence", 0.0) or 0.0),
        explanation=explanation,
    )
