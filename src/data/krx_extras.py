"""KRX 확장 지표 수집 — ★배선하되, 모르는 집계는 거부한다★
==========================================================================
감사: [`데이터 추출 감사`](../../docs/specs/2026-08-26-data-extraction-audit.md) §1.1
관례: `krx_ingest` (날짜 루프 배치 + CLI) · `macro_collector` (`MacroSeries` 어휘)

## 왜 이 모듈이 생겼나

`krx_client.get_extra()` 는 구현돼 있었는데 **운영 호출부가 하나도 없었다.** 그래서
VKOSPI·신용잔고·공매도·대차 네 계열은 **키를 넣어도 값이 오지 않았고**, 그 사실을
`source_registry` 가 손으로 적은 목록으로 선언하고 있었다. 이 모듈이 그 빈 자리다.

## ★하루치 조회를 시계열로 접는 규칙★

`get_extra` 는 `basDd` **하루치**이고 `parse_extra_rows` 의 결과에는 **종목
식별자가 없다**. 그래서 하루에 온 행들을 한 값으로 접어야 하는데, 접는 방법이
계열마다 다르고 **일부는 알 수 없다**:

    COLLAPSE_SINGLE   이름으로 한 행을 고른다 — 의미가 알려져 있다
    COLLAPSE_UNKNOWN  전종목 일별 응답 — 시장 합계 정의가 ★미확정★

★모르면 거부한다★ 합산인지 평균인지 잔고인지 알 수 없는 상태에서 하나를 고르면
그것은 관측이 아니라 **합성**이고, 화면은 그것을 실측 시장지표로 읽는다.
거부의 사유는 **두 종류를 구분한다** — 이름이 유일하지 않은 것(필터를 고쳐야 한다)과
집계 정의가 없는 것(실응답 1건이면 확정된다)은 고치는 사람이 다르다.

## ★이 배선이 늘리지 않는 것★

`PROVIDER_HAS_VINTAGE[KRX] = False` 다. 이 계열들은 **영구 forward-only** 이고,
백테스트 적격 데이터를 **한 줄도 늘리지 않는다**. 늘어나는 것은 "아니오" 의
정확도다 — "수집 코드가 없습니다" 에서 "키가 없습니다"/"집계 정의가 미확정입니다" 로.

실행 (사용자 환경, KRX_API_KEY 필요):
    python -m src.data.krx_extras --key VKOSPI --start 2026-01-02 --end 2026-01-31
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

#: `MacroSeries.source` 에 들어가는 값. `macro_observation_store` 의 출처와 같은 문자열.
SOURCE = "KRX"

REASON_NO_PATH = (
    "이 키에는 수집 경로가 없습니다 — `krx_client.EXTRA_SERIES` 에 종류와 접기 "
    "규칙이 등록돼 있지 않습니다.")

#: ★두 거부를 뭉개지 않는다★ 고치는 사람이 다르다.
REASON_NAME_NOT_UNIQUE = (
    "{date} 하루에 이름 필터('{name}')를 통과한 행이 {n}개입니다 — 그 이름이 "
    "유일하지 않습니다. 필터를 고쳐야 하며, 아무 행이나 고르면 그것은 관측이 "
    "아닙니다.")
REASON_COLLAPSE_UNKNOWN = (
    "{date} 하루에 {n}행이 왔습니다 — 시장 전체 한 값으로 접는 ★집계 정의가 "
    "미확정★ 입니다. 엔드포인트가 미검증이라 합계·평균·잔고 중 무엇이 맞는지 알 수 "
    "없고, 임의로 고르면 그것은 관측이 아니라 합성입니다. 실응답 1건이면 확정됩니다.")


def _weekdays(start: str, end: str):
    """평일만 — 주말은 KRX 휴장이라 부르면 쿼터만 태운다(공휴일은 빈 응답으로 온다)."""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    while s <= e:
        if s.weekday() < 5:
            yield s.strftime("%Y-%m-%d")
        s += timedelta(days=1)


def _label_unit(key: str) -> tuple[str, str]:
    from src.data.source_registry import get_spec
    spec = get_spec(key)
    return (spec.label, spec.unit) if spec else (key, "")


def collect_extra(key: str, start: str, end: str, *,
                  client=None, max_calls: int | None = None):
    """확장 지표 하나를 날짜 루프로 수집 → `MacroSeries`.

    ★값을 지어내지 않는다★ 실패의 종류를 사유로 구분한다:

        수집 경로 없음   → `REASON_NO_PATH`
        키 없음          → `source_registry.REASON_NO_KEY` (호출조차 하지 않는다)
        이름 필터 중복   → `REASON_NAME_NOT_UNIQUE`
        집계 정의 미확정 → `REASON_COLLAPSE_UNKNOWN`
        전 구간 빈 응답  → `source_registry.unavailable_reason_for(..., configured=True)`

    빈 응답인 날은 **건너뛴다** — 휴장·미공표는 `0` 이 아니다.
    """
    from src.data.krx_client import COLLAPSE_SINGLE, EXTRA_SERIES, KRXClient
    from src.data.source_registry import REASON_NO_KEY, unavailable_reason_for
    from src.services.macro_collector import MacroSeries

    label, unit = _label_unit(key)

    def _empty(reason: str) -> MacroSeries:
        return MacroSeries(indicator=key, name=label, unit=unit,
                           source="unavailable", timestamps=[], values=[],
                           last_update=datetime.now().isoformat(), reason=reason)

    entry = EXTRA_SERIES.get(key)
    if entry is None:
        return _empty(REASON_NO_PATH)
    kind, rule, name_filter = entry

    cli = client if client is not None else KRXClient()
    if not cli.is_configured:
        # ★조회를 시도조차 하지 않았다★ 코드가 틀렸다는 뜻이 아니다.
        return _empty(REASON_NO_KEY)

    name_field, name_match = name_filter if name_filter else (None, None)
    stamps: list[str] = []
    values: list[float] = []
    calls = 0
    for day in _weekdays(start, end):
        if max_calls is not None and calls >= max_calls:
            break
        calls += 1
        rows = cli.get_extra(kind, day, name_field=name_field,
                             name_match=name_match) or []
        if not rows:
            continue                    # ★휴장·미공표는 0 이 아니다★
        if len(rows) > 1:
            # ★여기서 멈춘다★ 모호한 줄 알면서 남은 날짜를 부르면 쿼터만 태운다.
            reason = (REASON_NAME_NOT_UNIQUE.format(date=day, n=len(rows),
                                                    name=name_match)
                      if rule == COLLAPSE_SINGLE else
                      REASON_COLLAPSE_UNKNOWN.format(date=day, n=len(rows)))
            return _empty(reason)
        value = rows[0].get("value")
        if value is None:
            continue
        stamps.append(str(rows[0].get("date") or day))
        values.append(float(value))

    if not values:
        return _empty(unavailable_reason_for(key, configured=True))
    return MacroSeries(
        indicator=key, name=label, unit=unit, source=SOURCE,
        timestamps=stamps, values=values,
        latest=values[-1], prev=values[-2] if len(values) >= 2 else None,
        last_update=datetime.now().isoformat(), reason=None)


def collect_all_extras(start: str, end: str, *, client=None,
                       max_calls: int | None = None) -> dict:
    """등록된 확장 계열 전부. ★`MacroCollector.collect_all` 과 섞지 않는다★

    그쪽 산출은 국면 축을 거쳐 배분으로 흐른다 — 거기에 계열을 더하는 것은
    Macro → Allocation 동작 변경이라 별도 승인 사항이다(CLAUDE.md §3).
    여기는 **수집과 기록**까지다.
    """
    from src.data.krx_client import EXTRA_SERIES, KRXClient
    cli = client if client is not None else KRXClient()
    return {key: collect_extra(key, start, end, client=cli, max_calls=max_calls)
            for key in EXTRA_SERIES}


def record_extras(series_map: dict, *, engine=None) -> dict:
    """수집 결과를 관측 스토어에 기록. ★기록 전용 — 읽는 소비자는 없다★

    비-REAL(`unavailable`)은 `record_series` 가 스스로 거른다.
    """
    from src.data.macro_observation_store import record_series
    out: dict[str, int] = {}
    for key, series in series_map.items():
        try:
            out[key] = record_series(series, engine=engine)
        except Exception as e:  # noqa: BLE001 — 기록 실패가 수집을 실패로 만들지 않는다
            logger.warning(f"KRX 확장 관측 기록 실패 ({key}): {e}")
            out[key] = 0
    return out


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="KRX 확장 지표 수집 (VKOSPI·신용잔고·공매도·대차)")
    ap.add_argument("--start", required=True, help="시작일 YYYY-MM-DD")
    ap.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--key", default=None, help="계열 하나만 (기본: 전부)")
    ap.add_argument("--max-calls", type=int, default=None, help="계열당 호출 상한")
    ap.add_argument("--record", action="store_true", help="관측 스토어에 기록")
    args = ap.parse_args()

    if args.key:
        result = {args.key: collect_extra(args.key, args.start, args.end,
                                          max_calls=args.max_calls)}
    else:
        result = collect_all_extras(args.start, args.end, max_calls=args.max_calls)

    for key, s in result.items():
        if s.values:
            print(f"{key}: {len(s.values)}개 ({s.timestamps[0]}~{s.timestamps[-1]}) "
                  f"최신 {s.latest}")
        else:
            print(f"{key}: 값 없음 — {s.reason}")
    if args.record:
        print("기록:", record_extras(result))


if __name__ == "__main__":
    main()
