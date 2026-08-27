"""매크로 관측 스토어 — ★빈티지가 저장될 곳을 만든다★
==============================================================================
감사: [`능력-계보 감사`](../../docs/specs/2026-08-27-capability-lineage-audit.md) §B1·§D
패턴: `instrument_master_store` (저장 원시함수 규약) · `pit_macro` (어휘)

## 왜 이 모듈이 생겼나

계보 감사가 찾은 **가장 깊은 병목**: FRED·ECOS 시계열에 영속 계층이 **아예 없었다.**
`macro_collector` 의 캐시는 `self._cache: dict[str, tuple[float, MacroSeries]]`
— **프로세스 메모리**다. 결과가 셋이었다:

    · 재시작하면 사라진다 → 과거 매크로 실험을 재현할 수 없다
    · ALFRED 빈티지 경로가 있는데도 **저장할 곳이 없어** 소비자가 하나뿐이다
    · `regime_snapshots` 관측치 5,790개의 `vintage_id` 가 전부 빈 문자열(실측)

★이 스토어가 여는 질문★ *"오늘의 판정이 그때도 같았는가?"* — 개정 편향을 재려면
**같은 기간의 여러 빈티지가 공존**해야 한다. 덮으면 영영 못 잰다.

## ★쓰기만 한다 — 읽는 소비자는 0이다★

국면 축이 이 스토어를 읽게 하는 것은 **배분 정책 배선**이라 별도 승인 사항이다.
그 분리를 `tests/test_macro_observation_store.py` 가 정적으로 강제한다.

## `obs_key` — 이 설계의 핵심

`vintage_id` 는 **빌 수 있다**. `pit_macro.fetch_observations` 는 `realtime_start`
가 없으면 `vintage_id=""` 로 둔다 — Phase 8b 가 *"빈티지가 없는 행에 빈티지를
지어내지 않는다"* 로 고친 자리다(지어내면 `has_vintage` 가 참이 되어 **빈티지 정보가
전혀 없는 응답이 backtest_eligible 로 인증된다**).

    vintage_id 있음  → obs_key = vintage_id
                       같은 빈티지 재저장 = 멱등 · 다른 빈티지 = 새 행
    vintage_id 비었음 → obs_key = f"unknown:{value!r}"
                       ★빈티지가 없으면 두 관측치를 가르는 유일한 증거가 값이다★
                       같은 값 = 개정 증거 없음 → 1행
                       다른 값 = 개정 증거 있음 → 2행

★이것은 빈티지를 지어내는 것이 아니다★ — `vintage_id` 컬럼은 **빈 채로** 남아
`derive_usage` 가 여전히 등급을 낮춘다. `obs_key` 는 **행 식별자**일 뿐이다.

`retrieved_at` 을 키에 넣지 않는 이유: 같은 값을 재수집할 때마다 행이 무한히 늘고,
그 증가분은 **아무 정보도 담지 않는다.**

## ★mock 은 저장하지 않는다★

합성값이 영속 스토어에 들어가면 **나중에 누군가 그것을 실제 역사로 읽는다.**
감사가 이 저장소를 E0(합성)라고 적은 이유가 그것이고, 스토어는 그 구분을 흐리면
안 된다. 키가 없는 환경에서는 스토어가 **비어 있게 된다 — 그것이 정직한 결과다.**
"""

from __future__ import annotations

import logging
from typing import Any

from src.data.pit_macro import DataStatus, MacroObservation, ResearchUsage, derive_usage

logger = logging.getLogger(__name__)

TABLE = "macro_observations"

#: 이 스키마의 판본. 컬럼이 바뀌면 올린다.
STORE_SCHEMA_VERSION = "2026.1"

#: 어느 경로로 들어온 관측치인가. ★빈티지 유무와는 다른 축이다★
SOURCE_ALFRED = "alfred"      # pit_macro.fetch_observations — 빈티지 있음
SOURCE_FRED = "FRED"          # macro_collector 의 최신개정본 경로 — 빈티지 없음
SOURCE_BOK = "BOK"            # ECOS — 개정 자체가 없는 계열

#: 빈티지가 없는 행의 `obs_key` 접두사. ★빈티지를 지어낸 것이 아니다★
UNKNOWN_VINTAGE_PREFIX = "unknown:"

_CHUNK = 500

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    series_id           VARCHAR(64) NOT NULL,
    observation_period  VARCHAR(16) NOT NULL,
    obs_key             VARCHAR(96) NOT NULL,
    vintage_id          VARCHAR(64),
    release_timestamp   VARCHAR(32),
    retrieved_at        VARCHAR(32),
    value               FLOAT NOT NULL,
    data_status         VARCHAR(12),
    market_cutoff       VARCHAR(32),
    execution_timestamp VARCHAR(32),
    source              VARCHAR(16),
    PRIMARY KEY (series_id, observation_period, obs_key)
)
"""

_UPSERT = f"""
INSERT INTO {TABLE}
    (series_id, observation_period, obs_key, vintage_id, release_timestamp,
     retrieved_at, value, data_status, market_cutoff, execution_timestamp, source)
VALUES
    (:series_id, :observation_period, :obs_key, :vintage_id, :release_timestamp,
     :retrieved_at, :value, :data_status, :market_cutoff, :execution_timestamp, :source)
ON CONFLICT (series_id, observation_period, obs_key) DO UPDATE SET
    vintage_id=EXCLUDED.vintage_id,
    release_timestamp=EXCLUDED.release_timestamp,
    value=EXCLUDED.value,
    data_status=EXCLUDED.data_status,
    market_cutoff=EXCLUDED.market_cutoff,
    execution_timestamp=EXCLUDED.execution_timestamp,
    source=EXCLUDED.source
"""
# ★`retrieved_at` 은 UPDATE 하지 않는다★ 최초 관측 시각을 보존한다 — 같은 값을
# 다시 받았다는 사실은 새 정보가 아니고, 덮으면 "언제부터 알았나" 가 사라진다.


def obs_key_of(observation: MacroObservation) -> str:
    """행 식별자. ★빈티지가 있으면 그것, 없으면 값이 유일한 증거다★"""
    if observation.vintage_id:
        return observation.vintage_id
    return f"{UNKNOWN_VINTAGE_PREFIX}{observation.value!r}"


def _engine(engine=None):
    if engine is not None:
        return engine
    try:
        from src.database import get_engine
        return get_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"엔진을 얻지 못했습니다: {e}")
        return None


def ensure_table(engine=None) -> bool:
    """테이블 보장. 성공 여부를 돌려준다(예외를 위로 던지지 않는다)."""
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None:
        return False
    try:
        with eng.begin() as conn:
            conn.execute(text(_DDL))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{TABLE} 생성 실패: {e}")
        return False


def save(observations: list[MacroObservation], *, source: str | None = None,
         engine=None) -> int:
    """관측치 → DB. 저장 행 수. ★실패해도 예외를 던지지 않는다★

    ★`data_status` 가 `REAL` 인 것만 적재한다★ 합성값이 영속 스토어에 들어가면
    나중에 누군가 그것을 실제 역사로 읽는다. 건너뛴 것은 로그로만 남긴다.

    같은 `(series_id, observation_period, obs_key)` 는 멱등이고, **다른 빈티지는
    별도 행**이다 — 그것이 개정 편향을 잴 수 있게 하는 유일한 조건이다.
    """
    from sqlalchemy import text
    if not observations:
        return 0
    eng = _engine(engine)
    if eng is None or not ensure_table(eng):
        return 0

    payload: list[dict[str, Any]] = []
    skipped = 0
    for o in observations:
        status = o.data_status
        status_value = status.value if isinstance(status, DataStatus) else str(status)
        if status_value != DataStatus.REAL.value:
            skipped += 1
            continue
        payload.append({
            "series_id": str(o.series_id),
            "observation_period": str(o.observation_period),
            "obs_key": obs_key_of(o),
            "vintage_id": o.vintage_id,          # ★비면 빈 채로★
            "release_timestamp": o.release_timestamp,
            "retrieved_at": o.retrieved_at,
            "value": float(o.value),
            "data_status": status_value,
            "market_cutoff": o.market_cutoff,
            "execution_timestamp": o.execution_timestamp,
            "source": source,
        })
    if skipped:
        logger.info("%s: 비-REAL 관측치 %d개를 저장하지 않았습니다(합성 금지).",
                    TABLE, skipped)
    if not payload:
        return 0

    try:
        stmt = text(_UPSERT)
        with eng.begin() as conn:
            for i in range(0, len(payload), _CHUNK):
                conn.execute(stmt, payload[i:i + _CHUNK])
        return len(payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{TABLE} 적재 실패: {e}")
        return 0


def _row_to_observation(row) -> MacroObservation:
    (series_id, period, _obs_key, vintage_id, release_ts, retrieved_at,
     value, status, market_cutoff, execution_ts, _source) = row
    try:
        data_status = DataStatus(status) if status else DataStatus.REAL
    except ValueError:
        data_status = DataStatus.REAL
    return MacroObservation(
        series_id=str(series_id),
        observation_period=str(period),
        release_timestamp=release_ts or "",
        vintage_id=vintage_id or "",
        retrieved_at=retrieved_at or "",
        value=float(value),
        data_status=data_status,
        market_cutoff=market_cutoff,
        execution_timestamp=execution_ts,
    )


_SELECT = (
    "SELECT series_id, observation_period, obs_key, vintage_id, release_timestamp, "
    "retrieved_at, value, data_status, market_cutoff, execution_timestamp, source "
    f"FROM {TABLE}"
)


def load(series_id: str | None = None, *, as_of: str | None = None,
         engine=None) -> list[MacroObservation]:
    """저장된 관측치. ★못 읽으면 빈 리스트 — 0이 아니다★

    `as_of` 를 주면 **그 시점에 알 수 있었던** 것만 남긴다. 규칙은
    `regime_snapshots._assert_pit` 과 **같다** — `release_timestamp` 가 **있고**
    `as_of` 보다 늦은 행을 제외한다.

    ★`release_timestamp` 가 빈 행은 검사할 수 없어 통과한다★ 통과가 곧 적격이
    아니다 — 그 행들은 `vintage_id` 도 비어 있어 `derive_usage` 가 등급을 낮춘다.
    과잉 차단하면 빈티지 없는 계열이 전방 연구에서도 사라진다.
    """
    from sqlalchemy import text
    eng = _engine(engine)
    if eng is None:
        return []

    where: list[str] = []
    params: dict[str, Any] = {}
    if series_id:
        where.append("series_id = :sid")
        params["sid"] = str(series_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(
                _SELECT + clause + " ORDER BY series_id, observation_period, obs_key"),
                params).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{TABLE} 조회 실패: {e}")
        return []

    out = [_row_to_observation(r) for r in rows]
    if as_of:
        out = [o for o in out
               if not (o.release_timestamp and o.release_timestamp > str(as_of))]
    return out


def vintages_of(series_id: str, observation_period: str, *,
                engine=None) -> list[MacroObservation]:
    """한 기간의 **모든 빈티지**. ★개정 편향을 재는 원시함수★

    두 개 이상 돌아오면 그 기간이 개정됐다는 뜻이고, 값의 차이가 편향의 크기다.
    공표 시각순으로 정렬한다(빈 `release_timestamp` 는 앞으로).
    """
    got = [o for o in load(series_id, engine=engine)
           if o.observation_period == str(observation_period)]
    got.sort(key=lambda o: (o.release_timestamp or "", o.vintage_id or ""))
    return got


def coverage(series_ids: list[str] | None = None, *, engine=None) -> dict[str, Any]:
    """스토어 커버리지 + 연구 등급. ★재지 못한 것을 0으로 적지 않는다★

    등급은 `pit_macro.derive_usage()` 를 **호출해서** 받는다 — 두 번째 등급 체계를
    만들면 매크로 팩터·가격 품질과 반드시 갈라진다.

    매핑:
        `has_vintage` ↔ **모든** 관측치에 `vintage_id` 가 있는가(전부-아니면-전무)
        `depth_ok`    ↔ 관측치가 하나라도 있는가
        `lag_known`   ↔ 모든 관측치에 `release_timestamp` 가 있는가
        `has_source`  ↔ 요청한 계열에 행이 있는가
    """
    eng = _engine(engine)
    if eng is None:
        return {"available": False,
                "reason": "DB 엔진이 없습니다 — 커버리지를 계산할 수 없습니다.",
                "version": STORE_SCHEMA_VERSION}

    obs = load(engine=eng)
    if series_ids:
        wanted = {str(s) for s in series_ids}
        obs = [o for o in obs if o.series_id in wanted]

    by_series: dict[str, dict[str, Any]] = {}
    for o in obs:
        s = by_series.setdefault(o.series_id, {
            "rows": 0, "with_vintage": 0, "with_release": 0, "periods": set()})
        s["rows"] += 1
        s["periods"].add(o.observation_period)
        if o.vintage_id:
            s["with_vintage"] += 1
        if o.release_timestamp:
            s["with_release"] += 1

    total = len(obs)
    has_source = total > 0 and (not series_ids or bool(by_series))
    all_vintage = has_source and all(o.vintage_id for o in obs)
    all_release = has_source and all(o.release_timestamp for o in obs)

    usage = derive_usage(has_vintage=all_vintage, depth_ok=has_source,
                         lag_known=all_release, has_source=has_source)

    if usage is ResearchUsage.BACKTEST_ELIGIBLE:
        reason = None
    elif not has_source:
        reason = ("저장된 관측치가 없습니다 — 이 환경에는 제공자 키가 없어 "
                  "실데이터가 수집되지 않았습니다(합성값은 저장하지 않습니다).")
    else:
        bits = [n for n, ok in (("빈티지 전량", all_vintage),
                                ("공표시각 전량", all_release)) if not ok]
        reason = ("충족되지 않은 조건: " + " · ".join(bits)
                  + " — 개정 편향을 재려면 빈티지가 필요합니다.")

    return {
        "available": True,
        "rows": total,
        "series": len(by_series),
        "by_series": {k: {"rows": v["rows"], "periods": len(v["periods"]),
                          "with_vintage": v["with_vintage"],
                          "with_release": v["with_release"]}
                      for k, v in sorted(by_series.items())},
        "research_usage": usage.value,
        "reason": reason,
        "version": STORE_SCHEMA_VERSION,
    }


def record_series(series, *, engine=None) -> int:
    """`macro_collector.MacroSeries` → 관측치 → `save()`. ★기록 전용★

    ★이 경로에는 빈티지가 없다★ `macro_collector` 는 FRED 의 최신 개정본
    (`series/observations`)과 ECOS `StatisticSearch` 를 읽는다. 그래서
    `vintage_id`·`release_timestamp` 를 **빈 채로** 둔다 — 지어내면
    `derive_usage` 가 거짓으로 backtest_eligible 을 낸다(Phase 8b 의 교훈).

    `source` 가 `BOK`/`FRED` 가 아니면(=`MOCK`·`unavailable`) 아무것도 하지 않는다.
    """
    from datetime import datetime, timezone

    src = getattr(series, "source", None)
    if src not in (SOURCE_BOK, SOURCE_FRED):
        return 0
    stamps = list(getattr(series, "timestamps", None) or [])
    values = list(getattr(series, "values", None) or [])
    if not stamps or len(stamps) != len(values):
        return 0

    retrieved = datetime.now(timezone.utc).isoformat()
    obs = [MacroObservation(
        series_id=str(getattr(series, "indicator", "")),
        observation_period=str(t),
        release_timestamp="",       # ★이 경로는 공표시각을 모른다★
        vintage_id="",              # ★빈티지가 없다 — 지어내지 않는다★
        retrieved_at=retrieved,
        value=float(v),
        data_status=DataStatus.REAL,
    ) for t, v in zip(stamps, values, strict=True) if v is not None]
    return save(obs, source=src, engine=engine)
