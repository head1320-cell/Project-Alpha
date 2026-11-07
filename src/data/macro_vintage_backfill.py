"""ALFRED 빈티지 백필 — ★스토어가 실제로 개정을 담게 한다★
==============================================================================
감사: [`능력-계보 감사`](../../docs/specs/2026-08-27-capability-lineage-audit.md) §C1
선행: `macro_observation_store`(`0ffe083`) · 패턴: `krx_ingest`(백필 CLI·쿼터 분할)

## 왜 이 모듈이 생겼나

스토어를 넣었는데 **쓰는 경로가 하나뿐이었다** — `macro_collector` 의 빈티지 **없는**
경로. ALFRED 를 부르는 `pit_macro.fetch_observations` 는 `src/engine/timing_rules_v2`
에서만 호출되고 그건 정책 계층이라 범위 밖이다. 그 결과:

    · `macro_observation_store.SOURCE_ALFRED` 가 죽어 있었다
    · 스토어는 `vintage_id=""` 행만 담아 `coverage()` 가 영원히 `forward_only`
    · ★스토어의 존재 이유인 "개정 편향 측정" 이 여전히 불가능★

`vintages_of()` 가 한 기간에 2행 이상을 내려면 **같은 기간을 여러 `as_of` 시점으로
받아야** 한다. 이 모듈이 그 경로다.

## ★대상 계열을 하드코딩하지 않는다★

`source_registry.PROVIDER_HAS_VINTAGE` 가 권위다. `SourceSpec.has_vintage` 의
독스트링이 그 원칙을 이미 못 박아 뒀다 — *"계열별로 손으로 적지 않는다. 빈티지는
API 가 주느냐 마느냐의 문제이지 계열의 성질이 아니다."* 백필도 같은 규칙을 쓴다.
`"FRED"` 를 적어 넣으면 ECOS 가 언젠가 빈티지를 갖게 돼도 백필이 모른다.

## ★건너뛰기 규칙 — 가장 미묘한 곳★

`vintage_id` 는 `"{realtime_start}..{realtime_end}"` 다.

    realtime_end == 9999-12-31 (열림) → "우리가 아는 한 현재본"  → ★반드시 재수집★
    그 외                     (닫힘) → 이미 후속본으로 대체됨   → 건너뛴다

닫힌 구간 안의 `as_of` 를 다시 받으면 **반드시 같은 빈티지**가 온다 — 건너뛰어도
정보를 잃지 않는다. 그러나 ★열린 구간을 건너뛰면 개정을 영영 못 본다★ — 개정이
일어나야 그 구간이 닫히는데, 재수집하지 않으면 닫히는 순간을 관측할 수 없다.
**우리가 찾는 바로 그것을 숨기게 된다.**

새 진행 테이블을 만들지 않는다 — 저장된 빈티지에서 **파생**한다
(`krx_ingest.loaded_dates` 와 같은 방식).
"""

from __future__ import annotations

import calendar
import logging
import os
import time
from datetime import date, datetime
from typing import Any

from src.data.macro_observation_store import SOURCE_ALFRED, save, vintages_of
from src.data.macro_observation_store import load as _load_observations

# ★센티넬을 복제하지 않는다★ `pit_macro` 가 `realtime_end` 결측에 쓰는 바로 그 값이다.
# 여기에 "9999-12-31" 을 다시 적으면 한쪽이 바뀌는 날 조용히 갈라지고, 그때
# 열린 구간이 닫힌 것으로 오인되어 개정이 사라진다. 같은 패키지 안이라 함께 움직인다.
from src.data.pit_macro import _FAR_FUTURE, fetch_observations
from src.data.source_registry import all_specs

logger = logging.getLogger(__name__)

#: FRED 호출 간 간격(초). 공개 API 는 분당 한도가 있어 한 번에 몰아치지 않는다.
DEFAULT_THROTTLE = 0.5

#: `pit_macro.fetch_observations` 와 **같은 판정**이다(거기서도 `len < 10` 이면
#: 키 없음으로 본다). 여기서는 호출 전에 미리 걸러 "0행 성공" 으로 위장하지 않는다.
_MIN_KEY_LEN = 10


def vintage_targets() -> tuple[str, ...]:
    """빈티지를 **제공자가** 주는 계열의 id. ★레지스트리에서 파생한다★

    `SourceSpec.has_vintage` 가 `PROVIDER_HAS_VINTAGE` 를 보므로, 제공자가 빈티지를
    갖게 되면 백필 대상도 **자동으로** 늘어난다. 파생 지표는 조회 대상이 아니다.
    """
    return tuple(s.key for s in all_specs() if s.has_vintage and not s.derived_from)


def as_of_schedule(start: str, end: str | None = None, *,
                   step_months: int = 1) -> tuple[str, ...]:
    """`as_of` 시점들 — 월말 기준. 각 시점이 ALFRED 호출 한 번이다.

    개정 편향을 재려면 **같은 기간을 여러 시점으로** 봐야 한다. 월말을 쓰는 이유는
    대부분의 매크로 공표가 월 단위라 그 사이 개정이 잡히기 때문이다.
    """
    if step_months < 1:
        raise ValueError("step_months 는 1 이상이어야 합니다")
    s = datetime.strptime(str(start)[:10], "%Y-%m-%d").date()
    e = (datetime.strptime(str(end)[:10], "%Y-%m-%d").date()
         if end else date.today())
    out: list[str] = []
    y, m = s.year, s.month
    while True:
        last = calendar.monthrange(y, m)[1]
        d = date(y, m, last)
        if d > e:
            break
        if d >= s:
            out.append(d.isoformat())
        m += step_months
        while m > 12:
            y, m = y + 1, m - 12
    return tuple(out)


def closed_vintage_ranges(series_id: str, *, engine=None) -> tuple[tuple[str, str], ...]:
    """저장된 빈티지 중 **닫힌** 구간들. ★열린 구간은 포함하지 않는다★

    열린 구간(`..9999-12-31`)은 "아직 대체되지 않았다" 는 뜻이라, 그 안의 `as_of`
    를 다시 받으면 **개정으로 닫혔는지** 알 수 있다. 포함시키면 그 관측을 잃는다.
    """
    out: list[tuple[str, str]] = []
    for o in _load_observations(series_id, engine=engine):
        vid = o.vintage_id or ""
        rs, sep, re_ = vid.partition("..")
        if not sep or not rs or not re_:
            continue
        if re_ == _FAR_FUTURE:
            continue                      # ★열려 있다 — 건너뛰지 않는다★
        out.append((rs, re_))
    return tuple(sorted(set(out)))


def _is_covered(as_of: str, ranges) -> bool:
    return any(rs <= as_of <= re_ for rs, re_ in ranges)


def _key_missing() -> bool:
    key = os.getenv("FRED_API_KEY", "")
    return not key or len(key) < _MIN_KEY_LEN


def backfill(series_ids: list[str] | None = None, *, start: str = "2015-01-01",
             end: str | None = None, step_months: int = 1,
             max_calls: int | None = None, skip_covered: bool = True,
             throttle: float = DEFAULT_THROTTLE, engine=None) -> dict[str, Any]:
    """빈티지 백필. ★키가 없으면 성공처럼 보이지 않는다★

    `fetch_observations` 는 키가 없으면 **빈 리스트**를 준다. 그것을 "0행 적재
    성공" 으로 보고하면 거짓이므로, 호출 전에 걸러 `{"skipped": 사유}` 를 낸다
    (`krx_ingest.auto_backfill` 과 같은 모양).

    Returns:
        `{series, as_of_points, calls, rows, skipped_covered, errors}` 또는
        `{"skipped": 사유}`.
    """
    if _key_missing():
        return {"skipped": "FRED_API_KEY 미설정 — ALFRED 빈티지를 받을 수 없습니다."}

    targets = [str(s) for s in (series_ids or vintage_targets())]
    if not targets:
        return {"skipped": "빈티지를 제공하는 계열이 레지스트리에 없습니다."}

    points = as_of_schedule(start, end, step_months=step_months)
    stats: dict[str, Any] = {"series": len(targets), "as_of_points": len(points),
                             "calls": 0, "rows": 0, "skipped_covered": 0,
                             "errors": []}
    for sid in targets:
        ranges = closed_vintage_ranges(sid, engine=engine) if skip_covered else ()
        for as_of in points:
            if max_calls is not None and stats["calls"] >= max_calls:
                stats["stopped_at"] = f"{sid}@{as_of} (max_calls={max_calls})"
                return stats
            if skip_covered and _is_covered(as_of, ranges):
                stats["skipped_covered"] += 1
                continue
            try:
                obs = fetch_observations(sid, as_of, start=start)
            except Exception as e:  # noqa: BLE001 — 한 계열의 실패가 전체를 죽이지 않는다
                stats["errors"].append(f"{sid}@{as_of}: {type(e).__name__}")
                logger.warning("빈티지 조회 실패 (%s @ %s): %s", sid, as_of, e)
                stats["calls"] += 1
                continue
            stats["calls"] += 1
            if obs:
                stats["rows"] += save(obs, source=SOURCE_ALFRED, engine=engine)
            if throttle:
                time.sleep(throttle)
    return stats


#: ★기본 호출 상한★ 21계열 × 월별 `as_of` 는 수천 콜이고, 0.5초 스로틀이면
#: 몇 시간이다. 데몬이 처음 도는 날 쿼터를 통째로 태우지 않도록 기본을 둔다 —
#: `skip_covered` 가 이미 받은 구간을 건너뛰므로 여러 번 돌면 결국 다 채워진다.
#: `MACRO_VINTAGE_MAX_CALLS=0` 이면 상한 없음.
DEFAULT_AUTO_MAX_CALLS = 400

#: 증분 주기(초). 빈티지는 월 단위로 갱신되므로 자주 돌 이유가 없다.
DEFAULT_REFRESH_SEC = 24 * 3600


def auto_vintage_backfill(loop: bool = False) -> dict[str, Any]:
    """startup 용 자동 빈티지 백필 — ★env·키 게이트, 키 없으면 즉시 no-op★

    ## 왜 이 함수가 생겼나

    `backfill()` 은 스토어에 **빈티지 있는 행**을 넣는 유일한 경로인데 호출부가
    CLI `main()` 하나였다. 즉 키를 넣어도 아무도 부르지 않아 빈티지는 영원히 0건,
    관측 스토어는 영원히 `forward_only` 였다. `krx_ingest.auto_backfill` 이 같은
    문제를 이미 푼 모양을 그대로 쓴다.

    ## ★이 함수는 국면 축을 열지 않는다★

    축의 PIT 판정은 ⑵`COLLECTOR_READS_VINTAGE` ∧ ⑶`실제 빈티지 행` 이다.
    여기서 채우는 것은 ⑶ 뿐이다. ⑵ 를 함께 올리면 키가 들어오는 순간 축이
    저절로 `managed` 로 뒤집히고, 그것은 **사람의 결정 없이 일어나는 배분 정책
    변경**이다(CLAUDE.md §3). ⑵ 는 별도 승인으로 사람이 올린다.

    env:
        MACRO_VINTAGE_AUTOBACKFILL   기본 "1", "0" 이면 비활성
        MACRO_VINTAGE_BACKFILL_START 기본 "2015-01-01"
        MACRO_VINTAGE_MAX_CALLS      기본 400, "0" 이면 무제한
        MACRO_VINTAGE_REFRESH_SEC    `loop=True` 증분 주기, 기본 24h
    """
    import os
    import time as _time

    if os.getenv("MACRO_VINTAGE_AUTOBACKFILL", "1") == "0":
        return {"skipped": "MACRO_VINTAGE_AUTOBACKFILL=0 — 자동 빈티지 백필 비활성"}
    if _key_missing():
        return {"skipped": "FRED_API_KEY 미설정 — ALFRED 빈티지를 받을 수 없습니다."}

    start = os.getenv("MACRO_VINTAGE_BACKFILL_START", "2015-01-01")
    try:
        raw = int(os.getenv("MACRO_VINTAGE_MAX_CALLS", str(DEFAULT_AUTO_MAX_CALLS)))
    except ValueError:
        raw = DEFAULT_AUTO_MAX_CALLS
    max_calls = raw if raw > 0 else None

    def _run_once() -> dict[str, Any]:
        try:
            stats = backfill(start=start, max_calls=max_calls, skip_covered=True)
        except Exception as e:  # noqa: BLE001 — 데몬에서 돈다. 예외가 startup 을 죽인다.
            logger.warning("빈티지 자동 백필 실패: %s: %s", type(e).__name__, e)
            return {"error": f"{type(e).__name__}: {e}"}
        logger.info("빈티지 자동 백필: %s", stats)
        return stats

    stats = _run_once()
    if loop:
        period = max(3600, int(os.getenv("MACRO_VINTAGE_REFRESH_SEC",
                                         str(DEFAULT_REFRESH_SEC)) or 0))
        while True:
            _time.sleep(period)
            _run_once()
    return stats


#: 빈티지가 하나뿐인 기간의 판정. ★"개정 없음" 이 아니다★
REVISION_UNOBSERVED = "unobserved"
REVISION_OBSERVED = "observed"


def revision_report(series_id: str, *, engine=None) -> dict[str, Any]:
    """기간별 **최초 빈티지 값 vs 최신 빈티지 값**. ★사슬의 목적지★

    ★빈티지가 하나뿐인 기간은 "개정 없음" 이 아니라 "개정 관측 안 됨" 이다★
    둘은 다른 사실이다. 접으면 **표본 부족이 "안정적인 계열" 로 둔갑한다** —
    이 저장소가 반복해서 막아 온 종류의 거짓말이다.
    """
    obs = _load_observations(series_id, engine=engine)
    if not obs:
        return {"available": False,
                "reason": f"{series_id} 에 저장된 관측치가 없습니다.",
                "series_id": series_id}

    periods = sorted({o.observation_period for o in obs})
    rows: list[dict[str, Any]] = []
    observed = 0
    for p in periods:
        vs = vintages_of(series_id, p, engine=engine)
        if len(vs) < 2:
            rows.append({"period": p, "vintages": len(vs),
                         "status": REVISION_UNOBSERVED,
                         "first": vs[0].value if vs else None,
                         "latest": vs[0].value if vs else None, "delta": None})
            continue
        observed += 1
        first, latest = vs[0], vs[-1]
        rows.append({"period": p, "vintages": len(vs), "status": REVISION_OBSERVED,
                     "first": first.value, "latest": latest.value,
                     "delta": round(latest.value - first.value, 6),
                     "first_release": first.release_timestamp,
                     "latest_release": latest.release_timestamp})

    deltas = [abs(r["delta"]) for r in rows if r["delta"] is not None]
    return {
        "available": True,
        "series_id": series_id,
        "periods": len(periods),
        "periods_with_observed_revision": observed,
        # ★못 본 것을 "개정 0" 으로 적지 않는다★
        "periods_revision_unobserved": len(periods) - observed,
        "mean_abs_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
        "max_abs_delta": round(max(deltas), 6) if deltas else None,
        "rows": rows,
        "note": ("빈티지가 하나뿐인 기간은 개정이 없었다는 뜻이 아니라 "
                 "여러 as_of 시점으로 받은 적이 없다는 뜻입니다 — "
                 "`macro_vintage_backfill.backfill()` 을 더 돌리십시오."),
    }


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="ALFRED 빈티지 백필 → macro_observations")
    ap.add_argument("--start", default="2015-01-01", help="관측 시작일 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="as_of 종료일 (기본 오늘)")
    ap.add_argument("--series", default=None,
                    help="쉼표 구분. 생략하면 레지스트리의 빈티지 계열 전체")
    ap.add_argument("--step-months", type=int, default=1, help="as_of 간격(개월)")
    ap.add_argument("--max-calls", type=int, default=None,
                    help="이번 실행 최대 호출 수 (쿼터 분할)")
    ap.add_argument("--force", action="store_true",
                    help="닫힌 빈티지 구간도 다시 받기")
    ap.add_argument("--report", default=None, help="이 계열의 개정 리포트를 출력")
    args = ap.parse_args()

    if args.report:
        rep = revision_report(args.report)
        print(f"개정 리포트({args.report}): "
              f"{ {k: v for k, v in rep.items() if k != 'rows'} }")
        return

    stats = backfill(
        series_ids=[s.strip() for s in args.series.split(",")] if args.series else None,
        start=args.start, end=args.end, step_months=args.step_months,
        max_calls=args.max_calls, skip_covered=not args.force,
    )
    print(f"빈티지 백필 결과: {stats}")


if __name__ == "__main__":
    main()
