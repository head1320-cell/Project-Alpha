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


# 굳혀 두는 경로의 길이 — `regime_transitions.regime_path` 의 기본값과 같다.
# 매크로 시계열 자체가 mock 60개월이므로 더 길게 요청해도 늘지 않는다.
_PATH_MONTHS = 60


def _regime_path_points(macro_snap: Any, market: str) -> list[dict] | None:
    """월별 국면 경로 — 실패하면 `None`(빈 리스트가 아니다).

    ★스냅샷 생성을 죽이지 않는다★ 경로를 못 만든 것과 만든 것은 다른 사실이고,
    `None` 이 그 사실을 전한다. 소비자는 `None` 을 보고 재계산하되 **재계산했다는
    라벨을 붙인다**.
    """
    try:
        from src.engine.regime_transitions import regime_path
        series = getattr(macro_snap, "series", None) or {}
        if not series:
            return None
        return regime_path(series, market, months=_PATH_MONTHS).get("points") or None
    except Exception as e:  # noqa: BLE001
        logger.warning("국면 경로 산출 실패(스냅샷은 계속 저장): %s", e)
        return None


def build_and_store(market: str = "kr") -> str | None:
    """현재 국면을 스냅샷으로 굳힌다. 성공 시 snapshot_id, DB 미가용 시 None.

    수집·판정 실패는 삼키지 않는다 — 조용히 0 을 반환하면 호출자가 그것을 국면으로 믿는다.
    """
    state, macro_snap = _collect(market)
    observations = observations_from_series(macro_snap)
    path_points = _regime_path_points(macro_snap, market)

    regime = getattr(state, "regime", "") or "UNKNOWN"
    mode = getattr(state, "recommended_mode", "") or "NORMAL"
    desc = getattr(state, "description", "") or ""
    # 권고 모드를 설명에 남긴다 — AAS 매핑 미리보기가 "무엇이 적용될지"를 이 문자열로 보여준다.
    explanation = f"[{regime} · 권고 {mode}] {desc}".strip()

    as_of = str(getattr(state, "timestamp", "") or "")

    sid = create_snapshot(
        as_of=as_of,
        observations=observations,
        growth_axis=float(getattr(state, "growth_axis", 0.0) or 0.0),
        inflation_axis=float(getattr(state, "inflation_axis", 0.0) or 0.0),
        phase_probabilities=dict(getattr(state, "regime_probs", {}) or {}),
        stress_score=float(getattr(state, "stress_score", 0.0) or 0.0),
        confidence=float(getattr(state, "confidence", 0.0) or 0.0),
        explanation=explanation,
        # Phase 4a: 표시 문자열이 아니라 **필드**로 넘긴다 — 스트립이 explanation 을
        # 파싱하지 않아도 국면 배지를 그릴 수 있어야 한다.
        regime=regime,
        recommended_mode=mode,
        # ★그 시점에 알 수 있었던 국면 경로를 함께 굳힌다 (P2.5)★
        # 국면조건부 μ/Σ 는 월별 라벨을 필요로 한다. 스냅샷에 없으면 소비자가
        # **오늘의 데이터로** 다시 계산할 수밖에 없고, 그러면 과거 결정을 현재
        # 지식으로 재판하게 된다(Brief §16). 경로를 만들지 못했으면 `None` 을
        # 넘겨 열을 비워 둔다 — 빈 리스트로 "계산했는데 비었다" 인 척하지 않는다.
        regime_path=path_points,
    )
    if sid:
        promote_to_mes(sid)
    return sid


def _model_contracts() -> dict[str, Any]:
    """스튜디오별 **계약 상태** — 실행 결과가 아니다 (M1-V).

    ★스냅샷마다 다섯 모델을 돌리지 않는다★ DFM 적합·Granger 검정은 초 단위이고,
    스냅샷은 "결정 시점에 무엇을 보고 있었는가" 를 굳히는 것이지 그 자리에서 연구를
    수행하는 것이 아니다. 그래서 여기 남는 것은 **어느 엔진이 가용했는가**이고,
    각 항목이 `computed: False` 로 그 사실을 스스로 말한다.
    """
    from src.engine.macro_models import describe_all

    out: dict[str, Any] = {}
    for s in describe_all():
        f = s["frontier"]
        out[s["id"]] = {
            "label": s["label"],
            "frontier": {"name": f["name"], "available": f["available"],
                         "reason": f.get("reason")},
            "substitute": {"name": s["substitute"]["name"]},
            # ★이 값은 실행 결과가 아니다★ 화면이 숫자로 읽지 않도록 명시한다.
            "computed": False,
            "note": "스냅샷 시점의 엔진 가용성입니다 — 모델을 실행한 결과가 아닙니다.",
        }
    return out


def promote_to_mes(snapshot_id: str) -> dict[str, Any]:
    """스냅샷을 **MacroEvidenceSnapshot 으로 승격**한다 (M1-V 배선).

    M1-S 가 `attach_evidence` 를 만들었지만 **호출자가 없었다** — 그래서 어떤 스냅샷도
    MES 가 된 적이 없고, Case 사슬의 `mes` 조각은 언제나 "고정된 증거가 없습니다" 였다.
    이 함수가 그 빈 자리다.

    ★붙이는 것과 붙이지 않는 것★
      · `indicators` — `source_registry` 의 등록 소스 상태. **값이 없어도 키가 있고**
        미검증 소스는 사유를 갖는다(M1-I 계약). 기존 BOK/FRED 관측치는 이미
        `observations` 열에 있으므로 **복제하지 않는다** — 진실은 한 벌이다.
      · `models`     — 계약 상태(위 `_model_contracts`), 실행 결과가 아니다.
      · `capability` — 도달 레벨 + **바로 위가 막힌 사유**(M1-C).

    ★실패해도 스냅샷을 죽이지 않는다★ 증거를 못 붙인 것과 붙인 것은 다른 사실이고,
    반환값이 그 사실을 그대로 전한다. 스냅샷 자체는 이미 저장돼 있다.
    """
    from src.data.regime_snapshots import attach_evidence
    from src.data.source_registry import indicator_block
    from src.engine.capability import resolve

    try:
        cap = resolve()
        level = str(cap.get("level") or "L3")
        blocked = cap.get("blocked_level")
        reason = (f"{blocked}: {cap.get('blocked_reason')}"
                  if blocked and cap.get("blocked_reason") else None)
        attached = attach_evidence(
            snapshot_id,
            indicators=indicator_block(),
            models=_model_contracts(),
            capability_level=level,
            capability_reason=reason,
        )
        if not attached:
            return {"attached": False, "capability_level": None,
                    "reason": "증거를 붙이지 못했습니다 — 이미 채워졌거나 저장소가 "
                              "MES 열을 갖고 있지 않습니다."}
        return {"attached": True, "capability_level": level, "capability_reason": reason}
    except Exception as e:  # noqa: BLE001 — 승격 실패가 스냅샷 생성을 되돌리지 않는다
        logger.warning("MES 승격 실패 %s: %s", snapshot_id, e)
        return {"attached": False, "capability_level": None,
                "reason": f"증거 수집 중 오류가 발생했습니다: {type(e).__name__}"}
