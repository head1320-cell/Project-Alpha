"""적재 레지스트리 — **어떤 데이터가 어디서 와서 어디에 쌓이는가**의 단일 출처.

★왜 만들었나 — 목록이 세 곳에 갈라져 있었다★
  · `state/ingest_state.py::INGEST_TARGETS` (6개)
  · `api/data_routes.py::_ingest_run` 의 if 분기 (6개)
  · `frontend/widgets/admin/DbStatusPanel.tsx` 의 하드코딩 (라벨 6 + 버튼 6)

그래서 대상을 추가하려면 세 곳을 고쳐야 했고, 실제로 빠진 것이 있었다:
**`macro`** 는 적재 대상이 아예 없었다 — 조건식의 ECOS/FRED 토큰이 프로세스마다
라이브 호출인데, `macro_observations` 테이블과 백필은 **이미 있었다**(연결만 안 됨).
`instrument_master` 도 종목 식별의 단일 진실인데 현황이 안 보였다.

★단위는 '테이블' 이 아니라 '데이터셋' 이다★
감사 중 확인: `db-status` 가 테이블처럼 보여주던 `index_kospi_kosdaq`·
`etf_cross_asset` 은 **실제 테이블이 아니다** — 둘 다 `daily_prices` 의 슬라이스다
(`ticker IN ('KOSPI','KOSDAQ')` / 크로스에셋 화이트리스트). 키를 테이블명으로
잡으면 모델이 틀리고, UI 가 "테이블 3개" 로 그려 저장소 구조를 오해하게 만든다.

★이 모듈은 적재 함수를 새로 만들지 않는다★ — 이미 있는 것을 **연결**만 한다.
"""
from __future__ import annotations

from dataclasses import dataclass


def _cross_asset_slice_sql() -> str:
    """크로스에셋 ETF 화이트리스트 술어 — ★코드는 레지스트리가 정한다★.

    `data_routes` 가 `US_TO_KR` 로 만들던 것과 같은 목록이다. 사용자 입력이
    섞이지 않으므로 리터럴로 넣어도 안전하다(그 라우터도 같은 이유로 그렇게 한다).
    실패하면 `None` — 슬라이스를 못 만들면 **전체를 세지 않는다**.
    """
    try:
        from src.data.etf_prices import US_TO_KR
        codes = sorted({c for c, _ in US_TO_KR.values()})
    except Exception:                                   # noqa: BLE001
        return None
    if not codes:
        return None
    inner = ",".join(f"'{c}'" for c in codes if c.isalnum())
    return f"ticker IN ({inner})" if inner else None


@dataclass(frozen=True)
class Dataset:
    """적재 대상 하나.

    `slice_of` 는 ★이 데이터셋이 공유 테이블의 부분집합★일 때 그 조건을 사람이
    읽을 수 있게 적는다(`None` 이면 테이블 전체). 없으면 UI 가 별개 테이블로
    오해한다.

    `required_env` 는 "키가 없어서 못 받는다" 와 "받았는데 비었다" 를 가르기 위한
    것이다 — 그 둘을 구별하지 못하면 사용자가 없는 문제를 쫓는다.

    `tools` 는 **이 데이터가 없으면 못 도는 도구**다. 적재 현황을 도구 관점으로
    되읽을 수 있어야 "백테스터가 왜 빈약한가" 에 답할 수 있다.
    """

    key: str
    label: str
    source: str                      # DART · KRX · KIS · ECOS/FRED · computed
    table: str
    tools: tuple[str, ...]
    required_env: tuple[str, ...] = ()
    slice_of: str | None = None      # 공유 테이블의 부분집합이면 그 조건(사람이 읽는 설명)
    #: 위 조건의 **실행 가능한** 형태. `slice_of` 는 UI 설명용 산문이고 이것은
    #: 커버리지 집계가 실제로 붙이는 술어다 — 둘을 하나로 쓰면 산문이 SQL 로
    #: 새거나 SQL 이 UI 에 노출된다. 값은 ★레지스트리가 정하는 화이트리스트★ 이고
    #: 사용자 입력이 섞이지 않는다.
    slice_sql: str | None = None
    #: 이 대상을 **버튼으로 돌릴 수 있는가**. 실행 방법 자체는 라우터의
    #: `_ingest_run` 이 갖는다 — ★여기서 다시 구현하지 않는다★. 그 함수는 대상마다
    #: 간단하지 않다(factors 는 유니버스 dedup, financials 는 2단계 + 쿼터 중단
    #: 처리). 레지스트리가 그것을 복제하면 두 벌이 갈라지고, 실제로 이 파일 초안이
    #: 함수 이름을 두 번 틀렸다(테스트가 잡았다).
    triggerable: bool = True
    note: str | None = None


DATASETS: tuple[Dataset, ...] = (
    Dataset(
        key="stocks", label="주식 일봉", source="KRX", table="daily_prices",
        # ★지수는 주식이 아니다★ 같은 테이블에 섞여 있으므로 커버리지 집계에서
        # 빼지 않으면 "주식 종목 수" 에 KOSPI/KOSDAQ 이 포함된다.
        slice_sql="ticker NOT IN ('KOSPI','KOSDAQ')",
        tools=("백테스터", "스크리너", "리스크"), required_env=("KRX_API_KEY",),
    ),
    Dataset(
        key="index", label="지수 (KOSPI/KOSDAQ)", source="KRX", table="daily_prices",
        slice_of="ticker IN ('KOSPI','KOSDAQ')",
        slice_sql="ticker IN ('KOSPI','KOSDAQ')",
        tools=("벤치마크", "국면"), required_env=("KRX_API_KEY",),
    ),
    Dataset(
        key="etf", label="크로스에셋 ETF", source="KIS", table="daily_prices",
        slice_of="ticker IN (크로스에셋 화이트리스트)",
        slice_sql=_cross_asset_slice_sql(),
        tools=("자산배분", "백테스터(매크로·ETF)"),
        required_env=("KIS_APP_KEY", "KIS_APP_SECRET"),
    ),
    Dataset(
        key="factors", label="펀더멘털 스냅샷", source="DART", table="factor_snapshot",
        tools=("스크리너",), required_env=("DART_API_KEY",),
    ),
    Dataset(
        key="financials", label="재무 시계열 (PIT)", source="DART",
        # ★로스터와 같은 이름을 쓴다★ 이 문자열은 `data_routes` 의 tools 키와
        # 짝이고 `DbStatusPanel.tsx:289` 가 그대로 그린다 — 한쪽만 바꾸면 갈라진다.
        table="financials_history", tools=("PIT 펀더멘털(추정 시차)", "백테스터"),
        required_env=("DART_API_KEY",),
    ),
    Dataset(
        key="flows", label="투자자 수급", source="KIS", table="investor_flows",
        tools=("수급 시그널",), required_env=("KIS_APP_KEY", "KIS_APP_SECRET"),
        note="연구 사용은 forward_only — 소급 적용 금지(과거 구간 미적재).",
    ),
    # ── 여기부터 이번에 새로 등록한 것 ────────────────────────────────────
    Dataset(
        key="macro", label="매크로 빈티지 (ECOS/FRED)", source="ECOS/FRED",
        table="macro_observations", tools=("국면", "매크로 대시보드"),
        required_env=("BOK_API_KEY", "FRED_API_KEY"),
        note="★조건식의 매크로 토큰은 이 테이블을 읽지 않는다★ — 조회 시점의 "
             "라이브 호출이다. 이 적재는 국면·대시보드용이다.",
    ),
    Dataset(
        key="instrument_master", label="종목 마스터 (식별자)", source="KRX",
        table="instrument_master", tools=("종목명 해석", "유니버스", "ISIN"),
        required_env=("KRX_API_KEY",),
        # ★버튼이 없다 — 별도 적재 경로가 아니기 때문이다★
        # 이 테이블은 심볼 마스터 갱신(`kis_master_parser`)의 **부수 효과**로 쓰이는
        # 파일의 DB 사본이다("파일이 진실이고 이것은 복사본이다"). 없는 버튼을
        # 만들어 두면 눌러도 아무 일이 없어 더 나쁘다.
        triggerable=False,
        note="심볼 마스터 갱신의 부수 효과로 적재된다(파일이 단일 진실, DB 는 사본).",
    ),
)

_BY_KEY = {d.key: d for d in DATASETS}


def get(key: str) -> Dataset:
    """★미상은 빈 데이터셋이 아니다★ 모르는 키는 거절한다."""
    try:
        return _BY_KEY[key]
    except KeyError as e:
        raise KeyError(
            f"등록되지 않은 적재 대상: {key!r} "
            f"(등록됨: {', '.join(sorted(_BY_KEY))})") from e


def keys() -> tuple[str, ...]:
    return tuple(d.key for d in DATASETS)


def triggerable_keys() -> tuple[str, ...]:
    """버튼으로 돌릴 수 있는 대상 — `INGEST_TARGETS` 가 여기서 파생된다."""
    return tuple(d.key for d in DATASETS if d.triggerable)
