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

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.data.pit_macro import ResearchUsage, derive_usage

# 제공자 — MES `indicators[*].source` 와 같은 어휘를 쓴다.
ECOS = "ECOS"
FRED = "FRED"
KRX = "KRX"
NAVER = "NAVER"
GOOGLE = "GOOGLE"

# ═══════════════════════════════════════════════════════════════════════════════
# 빈티지 제공 여부 — **제공자 속성이지 계열 속성이 아니다** (P4-D1)
# ═══════════════════════════════════════════════════════════════════════════════
#
# ★정적 공표지연 선언으로는 룩어헤드를 막을 수 없다★
# P4 계획 초안은 "계열마다 공표지연을 선언한다(공표지연이 PIT 의 핵심)" 이라고 적었고,
# 그건 틀렸다. 오늘 ECOS 로 2010-05 산업생산을 당기면 2010년 **속보치**가 아니라 나중에
# 다듬어진 **확정치**가 온다. 1개월 시프트해서 백테스트에 넣으면 미래를 훔쳐보는 것이고,
# 지연 시프트는 그 **개정(revision) 편향**을 원리적으로 지우지 못한다.
#
# 라벨을 붙이는 것으로는 부족하다 — 라벨은 읽고 무시할 수 있다. 이 저장소엔 이미 더 강한
# 장치가 있다: `pit_macro.derive_usage()` 가 `has_vintage` 를 필수 조건으로 요구하고
# `assert_backtest_eligible()` 이 백테스트 진입을 **예외로 중단**한다. 여기서는 새 판정
# 로직을 만들지 않고 **그 함수에 태우기만** 한다.
#
# FRED 는 ALFRED 로 빈티지를 준다(Phase 1 에서 구현됨) → BACKTEST_ELIGIBLE.
# ECOS·KRX·검색트렌드는 빈티지 엔드포인트가 없다 → 구조적으로 FORWARD_ONLY.
# 두 소스가 같은 화면에 있으면서 **적격성이 다르다**는 것이 이 설계의 요점이다.
PROVIDER_HAS_VINTAGE: dict[str, bool] = {
    FRED: True,
    ECOS: False,
    KRX: False,
    NAVER: False,
    GOOGLE: False,
}

_REVISION_BIAS_NOTE = {
    ECOS: ("한국은행 ECOS 는 빈티지(개정 이력) 엔드포인트를 제공하지 않습니다 — "
           "오늘 조회한 과거 값은 당시 속보치가 아니라 이후 개정된 확정치입니다. "
           "공표지연을 시프트해도 이 개정 편향은 남으므로 과거 시뮬레이션에 쓸 수 "
           "없습니다(forward-only)."),
    KRX: ("KRX 공개 API 는 개정 이력을 제공하지 않습니다 — 정정 공시가 반영된 값과 "
          "당시 공표값을 구분할 수 없어 과거 시뮬레이션에 쓸 수 없습니다(forward-only)."),
    NAVER: ("검색 트렌드는 조회 시점 기준으로 재정규화되어 과거 값이 개정됩니다 — "
            "같은 기간을 다시 조회하면 다른 값이 나오므로 과거 시뮬레이션에 쓸 수 "
            "없습니다(forward-only)."),
}
_REVISION_BIAS_NOTE[GOOGLE] = _REVISION_BIAS_NOTE[NAVER]

_UNVERIFIED_NOTE = (
    "이 환경에서는 실호출로 확인하지 못했습니다(호스트 프록시 차단). "
    "응답 필드명·코드가 명세와 다르면 시리즈가 조용히 비므로, "
    "`verify_connection.py` 로 실호출을 확인한 뒤 사람이 verified_live 를 올립니다."
)

# ═══════════════════════════════════════════════════════════════════════════════
# 공표 주기(cycle) — ★계열 속성이라 제공자에서 유도할 수 없다★
# ═══════════════════════════════════════════════════════════════════════════════
#
# `has_vintage` 는 제공자에서 유도한다(빈티지는 API 가 주느냐 마느냐의 문제다).
# ★주기는 다르다★ — 같은 ECOS 안에서도 기준금리는 일별이고 GDP 는 분기다.
# 그래서 계열마다 적어야 하는데, 그것이 정확히 **추측이 새어 들어오는 자리**다.
#
# 그래서 기본값을 `None`(미검증)으로 둔다. `verified_live` 와 같은 규율이다 —
# 메타 API(`StatisticTableList`/`StatisticItemList`)가 말해 주기 전까지는 모른다고
# 적는다. 이 저장소는 ECOS **항목코드**를 추측했다가 회사채를 국고채라고 부른
# 전례가 있다(`1fa4fbd`). 주기를 "아마 월별" 로 채우면 같은 종류의 사고가 난다.
ECOS_CYCLES = ("D", "M", "Q", "A")

#: 수집 실패의 세 원인 — 예전에는 전부 `source="unavailable"` 한 문자열로 뭉개졌다.
#: 처방이 서로 다른데 구분이 안 되면 사용자도 우리도 어디를 고쳐야 할지 모른다.
REASON_NO_KEY = ("API 키가 설정되지 않았습니다 — 이 계열은 조회를 시도조차 "
                 "하지 않았습니다(코드가 틀렸다는 뜻이 아닙니다).")
REASON_EMPTY_RESPONSE = ("검증된 좌표인데 응답이 비었습니다 — 쿼터 소진·일시 "
                         "장애·해당 구간 미공표 중 하나입니다.")
#: ★덧붙이는 문장이다★ 위 사유를 **대체하지 않는다**. Phase 1 에서 `not_ingested`
#: 가 "미검증" 을 지워 원인을 잃었던 실수를 반복하지 않는다.
REASON_CYCLE_SUSPECT = ("★주기 불일치 의심★ 이 계열의 공표 주기는 {freq} 로 "
                        "확인됐는데 수집기는 월별(M)로 조회합니다 — 통계표가 "
                        "월별을 공표하지 않으면 응답은 항상 빕니다.")


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
    #: 공표 주기 (`ECOS_CYCLES`). ★None = 미검증★ — 추측해 채우지 않는다.
    #: `has_vintage` 처럼 제공자에서 유도할 수 없다(계열마다 다르다). 메타 API 가
    #: 유일한 권위이고, `verified_live` 와 같이 **사람이 확인한 뒤** 올린다.
    #: ★이 값은 수집 주기를 바꾸지 않는다★ — 기록·대조 전용이다(트립와이어가 지킨다).
    frequency: str | None = None

    @property
    def has_vintage(self) -> bool:
        """개정 이력을 재구성할 수 있는가 — **제공자에서 파생한다** (P4-D1).

        계열별로 손으로 적지 않는다. 빈티지는 API 가 주느냐 마느냐의 문제이지
        계열의 성질이 아니고, 계열마다 적으면 30개 중 하나만 잘못 적어도 그 계열이
        조용히 백테스트 적격이 된다.
        """
        return PROVIDER_HAS_VINTAGE.get(self.provider, False)


# ─────────────────────────────────────────────────────────────────────────────
# 신규 소스 — 전부 verified_live=False 로 커밋된다.
# ─────────────────────────────────────────────────────────────────────────────
_RAW_SPECS: tuple[SourceSpec, ...] = (
    # ═══════════════════════════════════════════════════════════════════════
    # ECOS (한국은행) — P4-D1 에서 11 → 35 계열로 확장
    # ═══════════════════════════════════════════════════════════════════════
    # ★한국 주식 퀀트 플랫폼인데 한국 매크로가 가장 얕았다★
    # 착수 실측: ECOS 11계열 vs FRED 23계열. 미국 매크로로 한국 자산을 설명하고 있었다.
    # ECOS 는 수천 계열을 제공하는데 그중 11개만 쓰고 있었으므로, 정교화가 가장 크게
    # 값을 내는 지점이 여기다.
    #
    # `endpoint` 는 `통계표코드/항목코드` 다 — 이 문자열 하나가 수집기의 조회 좌표이고,
    # `ecos_collection_targets()` 가 그것을 그대로 풀어 쓴다. 레지스트리와 수집기가
    # 코드를 각자 들고 있으면 갈라진다.

    # ── 금리·수익률 곡선 ───────────────────────────────────────────────────
    SourceSpec(
        key="KR_BASE_RATE", label="한국 기준금리", provider=ECOS,
        endpoint="722Y001/0101000", unit="%", verified_live=True),
    SourceSpec(
        key="KR_3Y", label="국고채 3년", provider=ECOS,
        endpoint="817Y002/010195000", unit="%", verified_live=True),
    SourceSpec(
        key="KR_10Y", label="국고채 10년", provider=ECOS,
        endpoint="817Y003/010210000", unit="%", verified_live=True),
    SourceSpec(
        key="KR_CALL_RATE", label="콜금리(익일물)", provider=ECOS,
        endpoint="817Y002/010101000", unit="%", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_CD91", label="CD 91일", provider=ECOS,
        endpoint="817Y002/010502000", unit="%", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_1Y", label="국고채 1년", provider=ECOS,
        endpoint="817Y002/010190000", unit="%", note=_UNVERIFIED_NOTE),
    # ★국고 5년·20년은 넣지 않았다★ 817Y002 안에서 그 둘을 가리키는 항목코드를
    # 자신 있게 적을 수 없었고, 코드를 지어내서 계열을 하나 더 세는 것은 확장이
    # 아니라 그럴듯한 빈칸을 만드는 일이다. 커브는 1Y·3Y·10Y 로 충분히 잡힌다.
    SourceSpec(
        key="KR_CORP3Y", label="회사채 3년(AA-)", provider=ECOS,
        endpoint="817Y002/010200000", unit="%", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_CORP_BBB3Y", label="회사채 3년(BBB-)", provider=ECOS,
        endpoint="817Y002/010320000", unit="%", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_TIPS10Y", label="물가연동국고채 10년", provider=ECOS,
        endpoint="817Y002/010211000", unit="%", note=_UNVERIFIED_NOTE),

    # ── 통화·신용 ──────────────────────────────────────────────────────────
    SourceSpec(
        key="KR_M1", label="M1 통화량(평잔)", provider=ECOS,
        endpoint="101Y002/BBGA00", unit="십억원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_M2", label="M2 통화량(평잔)", provider=ECOS,
        endpoint="101Y003/BBHA00", unit="십억원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_HOUSEHOLD_CREDIT", label="가계신용 잔액", provider=ECOS,
        endpoint="151Y001/1000000", unit="십억원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_BANK_LOAN", label="예금은행 대출금", provider=ECOS,
        endpoint="104Y016/BCB8", unit="십억원", note=_UNVERIFIED_NOTE),

    # ── 물가 ───────────────────────────────────────────────────────────────
    SourceSpec(
        key="KR_CPI", label="소비자물가지수(CPI)", provider=ECOS,
        endpoint="901Y009/0", unit="지수", verified_live=True),
    SourceSpec(
        key="KR_CORE_CPI", label="근원 소비자물가(식료품·에너지 제외)", provider=ECOS,
        endpoint="901Y009/QB", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_PPI", label="생산자물가지수", provider=ECOS,
        endpoint="404Y014/*AA", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_SERVICE_PPI", label="서비스업 생산자물가", provider=ECOS,
        endpoint="404Y015/*AA", unit="지수", note=_UNVERIFIED_NOTE),

    # ── 실물·경기 ──────────────────────────────────────────────────────────
    SourceSpec(
        key="KR_GDP", label="실질 GDP", provider=ECOS,
        endpoint="200Y002/1400", unit="십억원", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_IP", label="산업생산지수", provider=ECOS,
        endpoint="901Y033/A00", unit="지수", verified_live=True),
    SourceSpec(
        key="KR_LEADING_CYCLE", label="경기선행지수 순환변동치", provider=ECOS,
        endpoint="901Y067/I16E", unit="지수", verified_live=True),
    SourceSpec(
        key="KR_COINCIDENT_CYCLE", label="경기동행지수 순환변동치", provider=ECOS,
        endpoint="901Y067/I16D", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_FACILITY_INVEST", label="설비투자지수", provider=ECOS,
        endpoint="901Y033/I11BC", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_RETAIL_SALES", label="소매판매액지수", provider=ECOS,
        endpoint="901Y033/I31A", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_CONSTRUCTION", label="건설기성액", provider=ECOS,
        endpoint="901Y033/I41A", unit="지수", note=_UNVERIFIED_NOTE),

    # ── 고용 ───────────────────────────────────────────────────────────────
    SourceSpec(
        key="KR_UNEMP", label="실업률", provider=ECOS,
        endpoint="901Y027/I61BC", unit="%", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_EMPLOYMENT_RATE", label="고용률", provider=ECOS,
        endpoint="901Y027/I61E", unit="%", note=_UNVERIFIED_NOTE),

    # ── 대외·환율 ──────────────────────────────────────────────────────────
    SourceSpec(
        key="USD_KRW", label="원/달러 환율", provider=ECOS,
        endpoint="731Y001/0000001", unit="원", verified_live=True),
    SourceSpec(
        key="KR_EXPORT_VALUE", label="수출금액지수", provider=ECOS,
        endpoint="403Y001/*AA", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_IMPORT_VALUE", label="수입금액지수", provider=ECOS,
        endpoint="403Y001/*AB", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_EXPORT_VOLUME", label="수출물량지수", provider=ECOS,
        endpoint="403Y002/*AA", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_IMPORT_VOLUME", label="수입물량지수", provider=ECOS,
        endpoint="403Y002/*AB", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_CURRENT_ACCOUNT", label="경상수지", provider=ECOS,
        endpoint="301Y017/SA000", unit="백만달러", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_FX_RESERVE", label="외환보유액", provider=ECOS,
        endpoint="732Y001/99", unit="백만달러", note=_UNVERIFIED_NOTE),

    # ── 심리·자산 ──────────────────────────────────────────────────────────
    SourceSpec(
        key="KOSPI", label="KOSPI 종합", provider=ECOS,
        endpoint="802Y001/0001000", unit="포인트", verified_live=True),
    SourceSpec(
        key="KR_CSI", label="소비자심리지수(CSI)", provider=ECOS,
        endpoint="511Y002/FME", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_BSI", label="기업경기실사지수(제조업 업황)", provider=ECOS,
        endpoint="512Y014/C0000", unit="지수", note=_UNVERIFIED_NOTE),
    SourceSpec(
        key="KR_HOUSE_PRICE", label="주택매매가격지수", provider=ECOS,
        endpoint="901Y062/P63AC", unit="지수", note=_UNVERIFIED_NOTE),

    # ── 파생 — 원계열이 다 있을 때만 계산한다. 하나라도 없으면 사유를 남긴다 ──
    SourceSpec(
        key="KR_CREDIT_SPREAD", label="신용스프레드(회사채3Y − 국고3Y)", provider=ECOS,
        endpoint="(derived)", unit="%p", derived_from=("KR_CORP3Y", "KR_3Y"),
        note="파생 지표입니다 — 원계열 둘이 모두 있어야 계산됩니다. 합성하지 않습니다."),
    SourceSpec(
        key="KR_CREDIT_SPREAD_BBB", label="신용스프레드(회사채3Y BBB- − 국고3Y)",
        provider=ECOS, endpoint="(derived)", unit="%p",
        derived_from=("KR_CORP_BBB3Y", "KR_3Y"),
        note="파생 지표입니다 — 원계열 둘이 모두 있어야 계산됩니다. 합성하지 않습니다."),
    SourceSpec(
        key="KR_TERM_SPREAD", label="장단기 스프레드(국고10Y − 국고3Y)", provider=ECOS,
        endpoint="(derived)", unit="%p", derived_from=("KR_10Y", "KR_3Y"),
        note="파생 지표입니다 — 원계열 둘이 모두 있어야 계산됩니다. 합성하지 않습니다."),

    # ═══════════════════════════════════════════════════════════════════════
    # FRED / ALFRED (미국) — **빈티지가 있는 대조군**
    # ═══════════════════════════════════════════════════════════════════════
    # 전부 `verified_live=True` 다 — 실호출로 돌아온 적이 있는 계열들이고, mock 폴백도
    # 그대로 유지되어야 한다(레지스트리 등재가 mock 을 막는 M1-I 규칙 때문).
    # ALFRED 빈티지가 있으므로 `PROVIDER_HAS_VINTAGE[FRED] = True` → BACKTEST_ELIGIBLE.
    SourceSpec(key="FEDFUNDS", label="Fed Funds Rate", provider=FRED,
               endpoint="FEDFUNDS", unit="%", verified_live=True),
    SourceSpec(key="DGS3MO", label="T3M (3개월물)", provider=FRED,
               endpoint="DGS3MO", unit="%", verified_live=True),
    SourceSpec(key="DGS2", label="T2Y (2년물)", provider=FRED,
               endpoint="DGS2", unit="%", verified_live=True),
    SourceSpec(key="DGS10", label="T10Y (10년물)", provider=FRED,
               endpoint="DGS10", unit="%", verified_live=True),
    SourceSpec(key="DGS30", label="T30Y (30년물)", provider=FRED,
               endpoint="DGS30", unit="%", verified_live=True),
    SourceSpec(key="T10Y2Y", label="T10Y-T2Y Spread", provider=FRED,
               endpoint="T10Y2Y", unit="%p", verified_live=True),
    SourceSpec(key="VIXCLS", label="VIX", provider=FRED,
               endpoint="VIXCLS", unit="지수", verified_live=True),
    SourceSpec(key="VXVCLS", label="VIX 3개월(VXV)", provider=FRED,
               endpoint="VXVCLS", unit="지수", verified_live=True),
    SourceSpec(key="NFCI", label="금융환경지수(NFCI)", provider=FRED,
               endpoint="NFCI", unit="지수", verified_live=True),
    SourceSpec(key="DTWEXBGS", label="DXY (광역지수)", provider=FRED,
               endpoint="DTWEXBGS", unit="지수", verified_live=True),
    SourceSpec(key="CPIAUCSL", label="US CPI", provider=FRED,
               endpoint="CPIAUCSL", unit="지수", verified_live=True),
    SourceSpec(key="BAMLH0A0HYM2", label="HY Credit Spread", provider=FRED,
               endpoint="BAMLH0A0HYM2", unit="%p", verified_live=True),
    SourceSpec(key="GDPC1", label="US 실질GDP", provider=FRED,
               endpoint="GDPC1", unit="지수", verified_live=True),
    SourceSpec(key="INDPRO", label="산업생산", provider=FRED,
               endpoint="INDPRO", unit="지수", verified_live=True),
    SourceSpec(key="UNRATE", label="실업률", provider=FRED,
               endpoint="UNRATE", unit="%", verified_live=True),
    SourceSpec(key="PAYEMS", label="비농업고용", provider=FRED,
               endpoint="PAYEMS", unit="천명", verified_live=True),
    SourceSpec(key="UMCSENT", label="소비자심리", provider=FRED,
               endpoint="UMCSENT", unit="지수", verified_live=True),
    SourceSpec(key="T10YIE", label="기대인플레(10Y)", provider=FRED,
               endpoint="T10YIE", unit="%", verified_live=True),
    SourceSpec(key="DFII10", label="실질금리(10Y)", provider=FRED,
               endpoint="DFII10", unit="%", verified_live=True),
    SourceSpec(key="M2SL", label="M2 통화량", provider=FRED,
               endpoint="M2SL", unit="지수", verified_live=True),
    SourceSpec(key="DCOILWTICO", label="WTI 유가", provider=FRED,
               endpoint="DCOILWTICO", unit="$", verified_live=True),

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


# ═══════════════════════════════════════════════════════════════════════════════
# 주기 증거 — ★사실과 출처를 붙여 다니게 한다★
# ═══════════════════════════════════════════════════════════════════════════════
#
# `frequency` 를 위 리터럴에 직접 적지 **않는다**. 그러면 `verified_live` 와 같은
# 상태가 된다 — 플래그는 코드에 있는데 그것을 뒷받침하는 관측은 어디에도 없는 상태.
# (실제로 그렇다: `verified_live=True` 인 ECOS 8계열의 근거를 추적하면 커밋 메시지
#  주장 하나뿐이고, 검증 경로인 `verify_connection.py::check_ecos` 는 값의 범위만
#  볼 뿐 주기도 TIME 문자열도 기록하지 않는다.)
#
# 대신 관측을 파일에 남기고 레지스트리가 그것을 **읽는다**. 항목마다 어떤 응답에서
# 나왔는지(`evidence_source`)·언제 봤는지(`probed_at`)·확신도(`grade`)가 붙어 다니고,
# diff 가 증거의 변화를 그대로 보여 준다. 채우는 것은 `scripts/verify_ecos_meta.py`
# 이고 사람이 검토해 커밋한다.
#: 환경변수로 덮어쓸 수 있다 — 다른 증거 파일(예: 로컬에서 갓 프로브한 것)을
#: 운영 파일을 건드리지 않고 시험해 보기 위한 것이다. 없으면 체크인된 파일을 쓴다.
FREQ_EVIDENCE_PATH = Path(
    os.getenv("ECOS_FREQ_EVIDENCE_PATH")
    or Path(__file__).resolve().parents[2] / "docs" / "specs" / "ecos-frequency-evidence.json")

#: 등급 순서 — 낮은 확신이 조용히 사실이 되는 경로를 막는다.
#:
#: ★이것은 **확신도** 척도다 — 출처 척도가 아니다★(AV 실측). 여기서 `E2` 는
#: *"메타 API 응답에서 관측했다"* 는 뜻이고, CLAUDE.md 2절의 `E2`(*"제공자
#: 파생"*)와는 **다른 축**이다. 글자가 같아 섞기 쉬우니, 출처 등급이 필요한
#: 쪽은 `src/domain/signal_evidence.py` 의 `PROV_*` 를 쓴다.
#: CLAUDE.md 가 `capability.py` 의 `L0~L3` 에 대해 적어 둔 경고와 같은 모양이다.
EVIDENCE_GRADES = ("E0", "E1", "E2", "E3")


def _load_frequency_evidence() -> tuple[dict[str, dict], str]:
    """(계열별 증거, 최소 적용 등급). ★없거나 깨져도 예외를 내지 않는다★

    증거가 없는 것은 오류가 아니라 **정상 상태**다(지금이 그렇다). 여기서 터지면
    레지스트리를 임포트하는 모든 경로가 함께 죽고, 그것은 "주기를 모른다" 보다
    훨씬 나쁜 결과다.
    """
    try:
        doc = json.loads(FREQ_EVIDENCE_PATH.read_text(encoding="utf-8"))
        series = doc.get("series")
        if not isinstance(series, dict):
            return {}, "E2"
        floor = doc.get("min_grade_to_apply")
        return series, (floor if floor in EVIDENCE_GRADES else "E2")
    except Exception:
        return {}, "E2"


def _apply_frequency_evidence(spec: SourceSpec) -> SourceSpec:
    """증거가 **충분할 때만** 주기를 입힌다. 그 외에는 `None`(미검증) 그대로."""
    ev = _FREQ_EVIDENCE.get(spec.key)
    if not isinstance(ev, dict):
        return spec
    freq, grade = ev.get("frequency"), ev.get("grade")
    if freq not in ECOS_CYCLES:
        return spec                     # 어휘 밖의 값은 사실이 아니다
    if grade not in EVIDENCE_GRADES:
        return spec
    if EVIDENCE_GRADES.index(grade) < EVIDENCE_GRADES.index(_FREQ_EVIDENCE_FLOOR):
        return spec                     # ★확신이 모자라면 적용하지 않는다★
    return replace(spec, frequency=freq)


_FREQ_EVIDENCE, _FREQ_EVIDENCE_FLOOR = _load_frequency_evidence()
#: ★`_BY_KEY` 는 반드시 `_SPECS` 에서 파생한다★ 따로 만들면 두 읽기 경로가
#: 갈라진다 — `432f554` 에서 `_BY_KEY` 에만 쓰는 변이가 실제로 살아남았다.
_SPECS: tuple[SourceSpec, ...] = tuple(_apply_frequency_evidence(s) for s in _RAW_SPECS)
_BY_KEY = {s.key: s for s in _SPECS}


def frequency_evidence_for(key: str) -> dict | None:
    """계열의 주기 증거 원본(있으면). ★사실만이 아니라 출처도 조회할 수 있어야 한다★"""
    ev = _FREQ_EVIDENCE.get(key)
    return dict(ev) if isinstance(ev, dict) else None


def all_specs() -> tuple[SourceSpec, ...]:
    return _SPECS


def get_spec(key: str) -> SourceSpec | None:
    return _BY_KEY.get(key)


def is_registered(key: str) -> bool:
    return key in _BY_KEY


def specs_by_provider(provider: str) -> tuple[SourceSpec, ...]:
    return tuple(s for s in _SPECS if s.provider == provider)


def ecos_collection_targets() -> tuple[tuple[str, str, str, str, str], ...]:
    """수집기가 조회할 ECOS 좌표 — `(key, 통계표코드, 항목코드, 라벨, 단위)`.

    ★레지스트리가 코드의 단일 출처다 (P4-D1)★
    예전에는 `macro_collector.bok_targets` 와 이 레지스트리가 **코드를 각자 들고**
    있었다. 11계열일 땐 눈으로 맞출 수 있었지만 35계열에서는 반드시 갈라진다 —
    한쪽에만 계열을 추가하면 수집은 되는데 상태를 못 내거나, 상태는 있는데 값이
    영원히 안 오는 조합이 생기고 둘 다 조용하다.

    파생 지표(`derived_from` 가 있는 것)는 조회 대상이 아니므로 제외한다.
    """
    out = []
    for s in specs_by_provider(ECOS):
        if s.derived_from:
            continue
        stat, _, item = s.endpoint.partition("/")
        out.append((s.key, stat, item, s.label, s.unit))
    return tuple(out)


def fred_collection_targets() -> dict[str, dict[str, str]]:
    """수집기의 `FRED_INDICATORS` 와 같은 모양 — 같은 이유로 레지스트리에서 나온다."""
    return {s.key: {"name": s.label, "unit": s.unit}
            for s in specs_by_provider(FRED)}


def research_usage(key: str, *, depth_ok: bool = True,
                   lag_known: bool = True) -> ResearchUsage:
    """이 계열을 **어디까지** 쓸 수 있는가 (P4-D1).

    ★판정을 여기서 하지 않는다★ `pit_macro.derive_usage()` 에 태우기만 한다.
    같은 판정을 두 곳에 두면 반드시 갈라진다 — 이 저장소가 A1(`currentSig`/`req`)과
    R0(오버레이 컴파일)에서 이미 두 번 겪었다.

    여기가 기여하는 것은 `has_vintage` 하나다. 그리고 그 하나가 ECOS 를 **구조적으로**
    forward-only 로 만든다 — 호출자가 `lag_known=True` 를 넘겨도 등급이 오르지 않는다.
    """
    spec = _BY_KEY.get(key)
    if spec is None:
        return derive_usage(has_vintage=False, depth_ok=depth_ok,
                            lag_known=lag_known, has_source=False)
    return derive_usage(has_vintage=spec.has_vintage, depth_ok=depth_ok,
                        lag_known=lag_known)


def revision_bias_note(key: str) -> str | None:
    """개정 편향 사유 — 빈티지가 있는 소스에는 `None`.

    ★모든 소스에 경고를 붙이면 경고가 의미를 잃는다★ 등급이 내려간 소스에만 붙이고,
    그 문구가 **왜** 내려갔는지 말한다. 등급만 내리고 이유를 안 적으면 블랙박스다.
    """
    spec = _BY_KEY.get(key)
    if spec is None or spec.has_vintage:
        return None
    return _REVISION_BIAS_NOTE.get(spec.provider)


def not_ingested_keys() -> frozenset[str]:
    """★엔드포인트는 있는데 **부르는 코드가 없는** 계열★ (감사 §1.1)

    이 계열들은 키를 넣어도 값이 오지 않는다 — "키 미설정" 과 원인이 다르고
    **고치는 사람이 다르다**(전자는 배선, 후자는 설정).

    ★손으로 적지 않는다 — 수집 경로에서 **유도**한다★

    예전에는 네 키를 적은 `frozenset` 이었다. 그 모양은 **비우는 것만으로 가드가
    해제된다**(직전 커밋의 Z2 변이가 정확히 그렇게 살아남았다). 이제는
    `krx_client.EXTRA_SERIES` 가 유일한 진실 공급원이라, 수집 경로를 지우면 이
    선언이 **스스로 되돌아온다**.

    ★호출 시점에 읽는다★ 모듈 적재 시점에 스냅샷을 뜨면 그 스냅샷이 두 번째
    선언이 되어 다시 갈라진다.
    """
    from src.data.krx_client import EXTRA_SERIES
    return frozenset(s.key for s in _SPECS
                     if s.provider == KRX and s.key not in EXTRA_SERIES)

_NOT_INGESTED_NOTE = (
    "**수집 코드가 없습니다** — API 키를 설정해도 값이 오지 않습니다"
    "(`krx_client` 의 확장 지표 조회를 부르는 파이프라인이 아직 없습니다)."
)
#: 미검증 사유 뒤에 덧붙일 때 쓰는 형태. ★`lstrip` 으로 접두사를 떼지 않는다★ —
#: `str.lstrip` 은 **문자 집합**을 지우므로 접두사 제거로 쓰면 조용히 더 지운다.
_NOT_INGESTED_SUFFIX = f" 그리고 {_NOT_INGESTED_NOTE}"


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
                "verified_live": False, "not_ingested": False,
                "reason": f"레지스트리에 없는 소스입니다: {key}"}

    # ★`not_ingested` 를 모든 분기가 낸다★ 어떤 응답에는 있고 어떤 응답에는 없으면
    # 소비자가 `.get()` 으로 읽다가 `None` 을 거짓으로 취급하게 된다.
    uningested = key in not_ingested_keys()
    base = {"source": spec.provider, "label": spec.label,
            "endpoint": spec.endpoint, "verified_live": spec.verified_live,
            "not_ingested": uningested}

    # ★두 사유를 **더한다** — 대체하지 않는다★ "미검증" 과 "수집 코드 없음" 은
    # 둘 다 참일 수 있고 고치는 사람이 다르다(전자는 검증, 후자는 배선).
    # 처음에는 not_ingested 를 먼저 보고 reason 을 **갈아치웠는데**, 그러면
    # "미검증인데 값을 냈다" 를 지키던 기존 가드에서 '미검증' 이라는 말이
    # 사라진다(실측: `test_an_unverified_source_reports_no_value_even_if_one_is_passed`).
    extra = _NOT_INGESTED_SUFFIX if uningested else ""
    if not spec.verified_live:
        return {**base, "value": None, "as_of": None, "available": False,
                "reason": f"엔드포인트 미검증 — {spec.note}{extra}"}
    if uningested:
        return {**base, "value": None, "as_of": None, "available": False,
                "reason": _NOT_INGESTED_NOTE}
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


def unavailable_reason_for(key: str, *, configured: bool) -> str:
    """수집 실패의 **원인**을 말한다 — 세 가지가 뭉개지지 않게.

    ★사유를 덧붙이지 덮어쓰지 않는다★ 주기 불일치 의심은 기존 사유를 **대체하지
    않고** 뒤에 붙는다. 원인이 둘 다일 수 있고, 하나를 지우면 그 정보가 사라진다.

    Args:
        configured: 클라이언트가 키를 갖고 있었는가. 없으면 조회를 시도조차 하지
            않았으므로 좌표가 맞는지 틀린지에 대해 말할 수 있는 것이 없다.
    """
    if not configured:
        return REASON_NO_KEY
    spec = _BY_KEY.get(key)
    if spec is None:
        return REASON_EMPTY_RESPONSE     # 레지스트리 밖 = 기존 지표
    base = _UNVERIFIED_NOTE if not spec.verified_live else REASON_EMPTY_RESPONSE
    if spec.frequency and spec.frequency != "M":
        return base + " " + REASON_CYCLE_SUSPECT.format(freq=spec.frequency)
    return base


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
