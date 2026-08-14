"""데이터 소스 레지스트리 — **미검증을 일급 상태로** (M1-I)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
M1-I 는 ECOS 통계표 코드 3개, KRX 엔드포인트 4개, 트렌드 API 2개를 새로 붙인다.
그런데 이 환경에서는 다섯 호스트가 전부 프록시 403 CONNECT 라 **실호출로 확인할 수
없다.** 통계표 코드나 엔드포인트가 틀리면 시리즈는 예외 없이 **조용히 빈 채로**
돌아오고, 기존 mock 폴백이 그 빈 값을 그럴듯한 숫자로 덮는다. 그러면 코드가 맞았는지
틀렸는지 **영원히 구분할 수 없다.**

그래서 세 번째 상태를 만든다:

    확인된 소스        `verified_live=True`  — 실호출로 응답 모양까지 확인됨
    선언만 된 소스     `verified_live=False` — 명세대로 썼지만 아직 실호출 없음
    없는 소스          레지스트리에 없음

★선언만 된 소스는 mock 으로 채우지 않는다★
------------------------------------------------------------------------------
기존 지표(BOK 8 · FRED 23)의 mock 폴백은 **그대로 둔다** — 개발 환경에서 화면이 도는
근거이고, 그 코드들은 실호출로 검증된 적이 있다. 새 소스만 다르게 대우한다:
`KIS_USE_MOCK=1` 이어도 `available:false` + 사유다. 검증되지 않은 코드가 만든 빈 값을
mock 이 덮으면, 그 mock 은 "데이터가 이렇게 생겼다" 가 아니라 **"내 코드가 맞다"** 는
거짓 증거가 된다.

★`verified_live` 는 사람이 올린다★
------------------------------------------------------------------------------
실호출이 한 번 성공했다고 코드가 스스로 플래그를 바꾸지 않는다. 그러면 그 플래그는
"검증됨" 이 아니라 "언젠가 한 번 됐음" 이 되고, 둘은 다른 사실이다.
검증 경로는 `verify_connection.py` 이고, 올리는 것은 그 결과를 본 사람이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 제공자 — MES `indicators[*].source` 와 같은 어휘를 쓴다.
ECOS = "ECOS"
KRX = "KRX"
NAVER = "NAVER"
GOOGLE = "GOOGLE"

_UNVERIFIED_NOTE = (
    "이 환경에서는 실호출로 확인하지 못했습니다(호스트 프록시 차단). "
    "응답 필드명·코드가 명세와 다르면 시리즈가 조용히 비므로, "
    "`verify_connection.py` 로 실호출을 확인한 뒤 사람이 verified_live 를 올립니다."
)


@dataclass(frozen=True)
class SourceSpec:
    """소스 하나의 신원과 검증 상태."""
    key: str              # MES indicators 의 키
    label: str
    provider: str
    endpoint: str         # 통계표 코드 또는 경로
    unit: str = ""
    verified_live: bool = False
    note: str = ""
    derived_from: tuple[str, ...] = ()   # 파생 지표면 원계열 키들


# ─────────────────────────────────────────────────────────────────────────────
# 신규 소스 — 전부 verified_live=False 로 커밋된다.
# ─────────────────────────────────────────────────────────────────────────────
_SPECS: tuple[SourceSpec, ...] = (
    # ── ECOS (한국은행) ────────────────────────────────────────────────────
    SourceSpec(
        key="KR_M2", label="M2 통화량(평잔)", provider=ECOS,
        endpoint="101Y003", unit="십억원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_GDP", label="실질 GDP", provider=ECOS,
        endpoint="200Y002", unit="십억원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_CORP3Y", label="회사채 3년(AA-)", provider=ECOS,
        endpoint="817Y002", unit="%", note=_UNVERIFIED_NOTE),
    # 파생 — 원계열 둘이 다 있을 때만 계산한다. 하나라도 없으면 사유를 남긴다.
    SourceSpec(
        key="KR_CREDIT_SPREAD", label="신용스프레드(회사채3Y − 국고3Y)", provider=ECOS,
        endpoint="(derived)", unit="%p", derived_from=("KR_CORP3Y", "KR_3Y"),
        note="파생 지표입니다 — 원계열 둘이 모두 있어야 계산됩니다. 합성하지 않습니다."),

    # ── KRX ────────────────────────────────────────────────────────────────
    SourceSpec(
        key="VKOSPI", label="변동성지수(VKOSPI)", provider=KRX,
        endpoint="/idx/drvprod_dd_trd", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_MARGIN_BALANCE", label="신용공여 잔고", provider=KRX,
        endpoint="/sto/mgn_bydd_trd", unit="원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_SHORT_VOLUME", label="공매도 거래", provider=KRX,
        endpoint="/sto/shrt_bydd_trd", unit="주", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_LENDING_BALANCE", label="대차거래 잔고", provider=KRX,
        endpoint="/sto/lend_bydd_trd", unit="주", note=_UNVERIFIED_NOTE),

    # ── 검색 트렌드 (둘 다 공식 API) ──────────────────────────────────────
    SourceSpec(
        key="TRENDS_KR", label="네이버 검색 트렌드", provider=NAVER,
        endpoint="/v1/datalab/search", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="TRENDS_GLOBAL", label="구글 검색 트렌드", provider=GOOGLE,
        endpoint="/v1beta/trends:fetchTimeseries", unit="지수", note=_UNVERIFIED_NOTE),
)

_BY_KEY = {s.key: s for s in _SPECS}


def all_specs() -> tuple[SourceSpec, ...]:
    return _SPECS


def get_spec(key: str) -> SourceSpec | None:
    return _BY_KEY.get(key)


def is_registered(key: str) -> bool:
    return key in _BY_KEY


def status(key: str, *, value: Any = None, as_of: str | None = None) -> dict[str, Any]:
    """MES `indicators[key]` 에 그대로 들어갈 상태 블록.

    ★키는 값이 없어도 존재한다 (M1-S 계약)★ 키가 사라지면 화면은 "그 지표를 안 본다"
    로 읽고, `0` 이 들어가면 "0 이다" 로 읽는다 — 둘 다 거짓이다.

    ★미검증 소스는 값이 있어도 내지 않는다★ 검증되지 않은 코드가 만든 값은 그것이
    실제 데이터인지 mock 인지 구분할 수 없다. 확인 전까지는 사유만 낸다.
    """
    spec = _BY_KEY.get(key)
    if spec is None:
        return {"value": None, "available": False, "source": None,
                "verified_live": False,
                "reason": f"레지스트리에 없는 소스입니다: {key}"}

    base = {"source": spec.provider, "label": spec.label,
            "endpoint": spec.endpoint, "verified_live": spec.verified_live}

    if not spec.verified_live:
        return {**base, "value": None, "as_of": None, "available": False,
                "reason": f"엔드포인트 미검증 — {spec.note}"}
    if value is None:
        return {**base, "value": None, "as_of": None, "available": False,
                "reason": "실호출에서 값을 받지 못했습니다."}
    return {**base, "value": value, "as_of": as_of, "available": True, "reason": None}


def indicator_block(values: dict[str, Any] | None = None,
                    as_of: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """등록된 **모든** 소스의 상태 맵 — MES 빌더가 쓴다.

    값이 없는 소스도 키를 갖는다. 그것이 이 함수의 존재 이유다.
    """
    values = values or {}
    as_of = as_of or {}
    return {s.key: status(s.key, value=values.get(s.key), as_of=as_of.get(s.key))
            for s in _SPECS}


def new_source_mock_allowed(key: str) -> bool:
    """★신규 미검증 소스는 mock 으로 채우지 않는다★

    기존 지표(BOK 8 · FRED 23)의 mock 폴백은 그대로다 — 그 코드들은 실호출로 검증된
    적이 있고, 개발 환경에서 화면이 도는 근거다. 검증되지 않은 코드가 만든 빈 값을
    mock 이 덮으면 그 mock 은 "내 코드가 맞다" 는 거짓 증거가 된다.
    """
    spec = _BY_KEY.get(key)
    if spec is None:
        return True          # 레지스트리 밖 = 기존 지표 → 기존 동작 유지
    return bool(spec.verified_live)
