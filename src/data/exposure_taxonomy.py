"""정준 자산군 / 경제노출 분류 — ★체크인 레지스트리, 조용한 빈 dict 없음★
==============================================================================
계약: [`노출 분류 계약`](../../docs/specs/2026-08-26-exposure-taxonomy-contract.md)
모범: `src/data/source_registry.py` (체크인 레지스트리 + 파생 속성 + 정직한 미가용)

## 왜 이 모듈이 생겼나

상대 뷰(자산군 스프레드)와 그룹 제약에서 **분류는 계약**이다. 그런데 저장소의
기존 후보 둘은 자산군이 아니었다:

| 후보 | 실제 내용 | 문제 |
|---|---|---|
| `constrained_opt.sector_groups_for` | genport **섹터** | 예외 → `{}` · 예외가 없어도 `if t in assign` 로 **부분 배정** |
| `market_impact.ASSET_CLASS_TIERS` | `kospi_mid` 등 **유동성 티어** | 시총·시장 구분이지 경제적 노출이 아니다 |

★국내 자산군이 하나뿐이라고 적지 않는다★ `ticker_universe` 의 "Korea ETF" 8종만
보면 전부 주식형이지만, `stock_master.ETF_NAMES`(40종, 체크인)에는 **채권 3종·
원자재 2종**이 있다. 국내 상장만으로 EQUITY·RATES·COMMODITY 셋이 나온다.

★그리고 `sector_groups_for` 의 빈 dict 는 예외가 아니라 **정상 상태**다★ —
`master_flags_cache.json` 이 없으면(개발 환경의 기본) 언제나 `{}` 를 돌려준다.
그래서 정준 분류는 **캐시 파생이 아니라 체크인 선언형**이어야 한다.

## ★어휘를 새로 만들지 않는다★

경제노출 이름은 `factor_exposure.FACTORS` 를 그대로 쓴다. 팩터 모형이 노출을
**재고**, 이 레지스트리가 **어떤 상품이 그 노출을 갖는지** 말한다.

감사에서 확인된 사실: `instrument_selector.EXPOSURES` 는 독스트링으로 같은 어휘를
쓴다고 선언했지만 **실제 일치는 4/13** 이었고, `equity_us`·`equity_small`·`em`·
`real_estate` 는 경제노출이 아니라 **자산군 × 지역 슬라이스**였다. 여기서는 그 둘을
분리한다 — `AssetClass` 는 배타적 버킷, `exposures` 는 중첩 가능한 노출.

## ★부하 계수를 담지 않는다★

계약 초안은 노출마다 부하(`credit 0.8 · duration 0.4 · equity 0.35`)를 두자고
적었다. 그대로 하면 **숫자를 지어내게 된다.** 이 레지스트리는 **상품 정의에서
따라 나오는 노출 이름만** 선언한다:

    장기국채 ETF → duration        (그 상품이 보유한 것)
    IG 회사채 ETF → credit·duration
    금 ETF       → commodity

하이일드의 주식베타처럼 **추정이 필요한 노출은 넣지 않는다** — 그것은
`factor_exposure` 가 데이터에서 재는 것이고, 그 배선은 별건이다.

## ★통화 노출도 담지 않는다★

통화 노출은 상품의 성질이 아니라 **투자자의 기준통화 + 헤지 여부**의 함수다.
레지스트리는 상장 시장(`listing`)만 기록하고 통화 판단은 소비자에게 맡긴다.

## 배정하지 않는 것 — 사유와 함께

★레버리지·인버스는 자산군에 넣지 않는다★ `Σw = 1` 아래 그룹 상한은 "한 클래스
안에서 비중 합이 그 클래스 노출을 뜻한다" 를 전제한다. 인버스 ETF 를 EQUITY 로 세면
**주식 노출을 줄이는 상품이 주식 노출로 계산된다.** 감사 가능한 미배정으로 둔다.

## ★현재 상태 — 생산 소비자가 없다 (P9 ③ 실측)★

이 레지스트리는 계약으로서 준비돼 있지만 **`src/` 의 어떤 생산 경로도 아직
`classify`·`asset_class_of`·`exposures_of`·`require_complete` 를 부르지 않는다.**
다른 모듈들이 이름을 언급하는 것은 전부 독스트링이다("모범: …", "정준 분류는
여기가 갖는다"). 실측으로 확인했고, 다음 사람이 **쓰이는 줄 알고 의존하지
않도록** 여기에 적는다.

그래서 `TAXONOMY_AS_OF` 는 스탬프로 실려 나가기만 하고 **어느 요청의 `as_of` 와도
대조되지 않는다.** 그것은 결함이 아니라 미배선 상태다 — 배선하는 것은 자산군
분류를 배분 경로에 닿게 하는 일이고, CLAUDE.md §3 의 **별도 승인 사항**이라
P9 에서 하지 않았다.

다만 스탬프 **자체의 계약**은 걸어 두었다(`tests/test_exposure_taxonomy.py`):
날짜 형식 · 미래가 아님 · 버전과 연도 일치 · 읽는 쪽이 하드코딩하지 않았음.
예전 단언들은 `s.as_of == TAXONOMY_AS_OF` 라 ★상수가 상수와 같다★ 만 확인했고,
`TAXONOMY_AS_OF = "9999-99-99"` 여도 전부 통과했다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

#: 분류 체계 버전. ★분류가 바뀌면 올린다★ 소비자가 어느 판본으로 계산했는지
#: 응답에 실을 수 있어야 한다.
TAXONOMY_VERSION = "2026.1"
#: 이 판본이 유효해진 날. ★리밸런싱 시점 기준으로 쓴다★ — 재분류를 소급 적용하면
#: 룩어헤드다(재분류는 보통 그 자산의 성격이 드러난 **뒤에** 일어난다).
TAXONOMY_AS_OF = "2026-08-26"


class AssetClass(str, Enum):
    """★배타적·전수★ — 그룹 제약의 `group_id` 는 여기서만 나온다.

    한 상품은 정확히 하나의 자산군에 속한다. 중첩이 필요한 것은 `exposures` 다.
    """

    EQUITY = "EQUITY"
    RATES = "RATES"
    CREDIT = "CREDIT"
    FX = "FX"
    COMMODITY = "COMMODITY"
    REAL_ASSET = "REAL_ASSET"
    CASH = "CASH"


#: 배정 출처 — 사람이 골랐는지 규칙이 골랐는지가 값으로 남는다.
SOURCE_CURATED = "curated"
SOURCE_RULE_LISTED_EQUITY = "rule:listed_equity"

#: 미배정 사유. ★`None` 을 사유 없이 돌려주지 않는다★
UNASSIGNED_NO_MAPPING = "no_mapping"
UNASSIGNED_DIRECTIONAL = "directional_or_leveraged"
UNASSIGNED_NO_MASTER_FLAGS = "no_master_flags"
UNASSIGNED_UNREGISTERED_ETF = "etf_not_registered"

_UNASSIGNED_TEXT = {
    UNASSIGNED_NO_MAPPING: "레지스트리에 없고 규칙으로도 분류할 수 없습니다",
    UNASSIGNED_DIRECTIONAL: (
        "레버리지·인버스 상품입니다 — 자산군에 넣으면 그룹 상한이 노출을 "
        "**반대로** 계산합니다(인버스를 주식 노출로 셈)"),
    UNASSIGNED_NO_MASTER_FLAGS: (
        "KIS master 플래그 캐시가 없어 ETF 여부를 확인할 수 없습니다 — "
        "확인 없이 주식으로 추정하지 않습니다"),
    UNASSIGNED_UNREGISTERED_ETF: (
        "ETF 인데 레지스트리에 등록돼 있지 않습니다 — 지수형 상품은 "
        "규칙으로 추정하지 않고 사람이 등록합니다"),
}


@dataclass(frozen=True)
class InstrumentSpec:
    """한 상장 상품의 정준 분류.

    frozen 인 이유는 `ViewRow`·`RegimeProbabilities` 와 같다 — 소비자가 나중에
    자산군을 고쳐 계약을 우회하지 못하게 한다.
    """

    instrument_id: str            # ★안정 ID★ 티커는 재사용·변경된다
    ticker: str
    name: str
    asset_class: AssetClass
    exposures: tuple[str, ...]    # `factor_exposure.FACTORS` 의 부분집합
    listing: str                  # "kr" | "us"
    source: str = SOURCE_CURATED
    as_of: str = TAXONOMY_AS_OF
    version: str = TAXONOMY_VERSION


def _kr(code: str, name: str, ac: AssetClass, exp: tuple[str, ...]) -> InstrumentSpec:
    return InstrumentSpec(instrument_id=f"KR:{code}", ticker=code, name=name,
                          asset_class=ac, exposures=exp, listing="kr")


def _us(sym: str, name: str, ac: AssetClass, exp: tuple[str, ...]) -> InstrumentSpec:
    return InstrumentSpec(instrument_id=f"US:{sym}", ticker=sym, name=name,
                          asset_class=ac, exposures=exp, listing="us")


# ─────────────────────────────────────────────────────────────────────────────
# 레지스트리 — ★저장소가 이미 이름을 부르는 상품만★
#
# 출처: `stock_master.ETF_NAMES` (국내 40종, 체크인) + `ticker_universe` 의 US ETF.
# ★`ticker_universe` 의 "Korea ETF" 8종만 보면 안 된다★ — 그것만 보면 국내에
# 주식형 ETF 밖에 없는 것처럼 보이지만, `ETF_NAMES` 에는 **채권 3종·원자재 2종**이
# 있다. 국내 상장만으로도 EQUITY·RATES·COMMODITY 세 자산군이 나온다.
#
# 지수·FX·선물(`^KS11`·`USDKRW=X`·`CL=F`)은 이 저장소의 배분 경로에서 **주문할 수
# 없으므로** 넣지 않는다.
# ─────────────────────────────────────────────────────────────────────────────
_EQ = ("equity",)

#: 국내 주식형 — 지수·섹터·테마. 전부 `AssetClass.EQUITY` · 노출 `equity`.
_KR_EQUITY: tuple[tuple[str, str], ...] = (
    ("069500", "KODEX 200"), ("102110", "TIGER 200"), ("148020", "KBSTAR 200"),
    ("278530", "KODEX 200TR"), ("069660", "KOSEF 200"), ("226490", "KODEX 코스피"),
    ("229200", "KODEX 코스닥150"), ("091160", "KODEX 반도체"),
    ("091230", "TIGER 반도체"), ("117460", "KODEX 에너지화학"),
    ("305720", "KODEX 2차전지산업"), ("305540", "TIGER 2차전지테마"),
    ("364980", "TIGER KRX2차전지K-뉴딜"), ("091170", "KODEX 은행"),
    ("102780", "KODEX 삼성그룹"), ("266370", "KODEX IT"),
    ("117680", "KODEX 철강"), ("091180", "KODEX 자동차"),
    ("140710", "KODEX 운송"), ("244580", "KODEX 바이오"),
    ("261070", "TIGER 코스닥150바이오테크"), ("143860", "TIGER 헬스케어"),
    ("227540", "TIGER 200 헬스케어"), ("139660", "TIGER 200 IT"),
    ("139270", "TIGER 200 중공업"), ("139290", "TIGER 200 경기소비재"),
    ("139250", "TIGER 200 에너지화학"), ("278540", "KODEX MSCI Korea TR"),
    ("195930", "TIGER 선진국MSCI World"), ("143850", "TIGER 미국S&P500선물(H)"),
    ("133690", "TIGER 미국나스닥100"), ("360750", "TIGER 미국S&P500"),
    ("381180", "TIGER 미국테크TOP10"), ("453810", "TIGER 미국배당다우존스"),
)

_SPECS: tuple[InstrumentSpec, ...] = (
    *(_kr(c, n, AssetClass.EQUITY, _EQ) for c, n in _KR_EQUITY),
    # ── 국내 채권 ── ★듀레이션은 상품이 보유한 것이지 추정치가 아니다★
    _kr("273130", "KODEX 종합채권액티브", AssetClass.RATES, ("duration",)),
    _kr("153130", "KODEX 단기채권", AssetClass.RATES, ("duration",)),
    _kr("214980", "KODEX 단기채권PLUS", AssetClass.RATES, ("duration",)),
    # ── 국내 원자재 ── 선물형이라 롤수익이 붙지만 노출 **이름**은 원자재다
    _kr("132030", "KODEX 골드선물(H)", AssetClass.COMMODITY, ("commodity",)),
    _kr("130680", "TIGER 원유선물Enhanced(H)", AssetClass.COMMODITY, ("commodity",)),
    # ── 미국 상장 주식형 ────────────────────────────────────────────────────
    _us("SPY", "S&P 500 ETF", AssetClass.EQUITY, _EQ),
    _us("QQQ", "Nasdaq-100 ETF", AssetClass.EQUITY, _EQ),
    _us("IWM", "Russell 2000 ETF", AssetClass.EQUITY, _EQ),
    _us("DIA", "Dow Jones ETF", AssetClass.EQUITY, _EQ),
    _us("VTI", "Total Stock Market", AssetClass.EQUITY, _EQ),
    _us("EEM", "Emerging Markets ETF", AssetClass.EQUITY, _EQ),
    _us("XLF", "Financial Sector ETF", AssetClass.EQUITY, _EQ),
    _us("XLE", "Energy Sector ETF", AssetClass.EQUITY, _EQ),
    _us("XLK", "Technology Sector ETF", AssetClass.EQUITY, _EQ),
    _us("ARKK", "ARK Innovation ETF", AssetClass.EQUITY, _EQ),
    # ── 미국 채권 ──
    _us("TLT", "20+ Year Treasury", AssetClass.RATES, ("duration",)),
    _us("LQD", "Investment Grade Bond", AssetClass.CREDIT, ("credit", "duration")),
    # ★HYG 에 주식베타를 넣지 않는다★ 실증적으로 알려져 있지만 **추정치**다.
    # 그 숫자는 `factor_exposure` 가 데이터에서 재야 한다.
    _us("HYG", "High Yield Bond ETF", AssetClass.CREDIT, ("credit", "duration")),
    # ── 미국 원자재·부동산 ──
    _us("GLD", "Gold ETF", AssetClass.COMMODITY, ("commodity",)),
    _us("SLV", "Silver ETF", AssetClass.COMMODITY, ("commodity",)),
    # 리츠는 주식 증권이지만 자산군으로는 실물자산이다
    _us("VNQ", "Real Estate ETF", AssetClass.REAL_ASSET, _EQ),
)

#: ★배정하지 않는 상품 — 사유와 함께★ 조용히 빠지지 않는다.
#: 출처는 `stock_master.ETF_NAMES` 의 레버리지·인버스 5종.
_EXCLUDED: dict[str, str] = {
    "122630": UNASSIGNED_DIRECTIONAL,       # KODEX 레버리지
    "252670": UNASSIGNED_DIRECTIONAL,       # KODEX 200선물인버스2X
    "114800": UNASSIGNED_DIRECTIONAL,       # KODEX 인버스
    "251340": UNASSIGNED_DIRECTIONAL,       # KODEX 코스닥150선물인버스
    "233740": UNASSIGNED_DIRECTIONAL,       # KODEX 코스닥150레버리지
}

_BY_TICKER: dict[str, InstrumentSpec] = {s.ticker: s for s in _SPECS}


class TaxonomyIncomplete(ValueError):
    """전수 배정이 필요한 경로에서 미배정 상품을 만났다.

    ★조용한 폴백 대신 예외를 던지는 이유★ 상대 뷰와 그룹 제약에서 분류는 계약이다.
    절반만 분류된 유니버스로 "EQ − FI 스프레드" 를 만들면 실제로는 "EQ 일부 −
    FI 일부" 가 되고, **아무 신호도 나지 않는다.**
    """

    def __init__(self, reason: str, unassigned: list[dict[str, Any]]):
        super().__init__(reason)
        self.reason = reason
        self.unassigned = unassigned


@dataclass(frozen=True)
class Classification:
    """한 티커의 분류 결과. ★미배정도 결과다★ — `None` 을 돌려주지 않는다."""

    ticker: str
    assigned: bool
    asset_class: AssetClass | None = None
    exposures: tuple[str, ...] = ()
    instrument_id: str | None = None
    listing: str | None = None
    source: str | None = None
    as_of: str = TAXONOMY_AS_OF
    version: str = TAXONOMY_VERSION
    unassigned_reason: str | None = None
    unassigned_note: str | None = None


def _rule_listed_equity(ticker: str) -> tuple[AssetClass | None, str | None]:
    """규칙 배정 — ★적극적 증거를 요구한다★

    "상장 개별주는 주식" 은 참이지만, **그것이 개별주라는 것을 확인해야** 한다.
    KIS master 플래그가 없으면(개발 환경의 기본) ETF 인지 아닌지 알 수 없고,
    그때 주식으로 추정하면 지수형·레버리지 상품이 조용히 EQUITY 가 된다.

    ★확인할 수 없으면 배정하지 않는다.★
    """
    from src.data.stock_master import ETF_NAMES, STOCK_MASTER, load_master_flags

    # ★체크인된 증거가 먼저다★ `ETF_NAMES` 는 저장소가 들고 있는 ETF 목록이고
    # 캐시 파일에 의존하지 않는다. 여기 있으면 개별주가 아니다.
    if ticker in ETF_NAMES:
        return None, UNASSIGNED_UNREGISTERED_ETF
    if ticker not in STOCK_MASTER:
        return None, UNASSIGNED_NO_MAPPING
    flags = (load_master_flags() or {}).get(ticker)
    if not flags:
        return None, UNASSIGNED_NO_MASTER_FLAGS
    if flags.get("is_etf"):
        return None, UNASSIGNED_UNREGISTERED_ETF
    return AssetClass.EQUITY, None


def classify(ticker: str) -> Classification:
    """티커 → 분류. ★언제나 `Classification` 을 돌려준다 (`None` 없음)★"""
    t = str(ticker).strip()
    spec = _BY_TICKER.get(t)
    if spec is not None:
        return Classification(
            ticker=t, assigned=True, asset_class=spec.asset_class,
            exposures=spec.exposures, instrument_id=spec.instrument_id,
            listing=spec.listing, source=spec.source, as_of=spec.as_of,
            version=spec.version)

    reason = _EXCLUDED.get(t)
    if reason is None:
        ac, reason = _rule_listed_equity(t)
        if ac is not None:
            return Classification(
                ticker=t, assigned=True, asset_class=ac, exposures=("equity",),
                instrument_id=f"KR:{t}", listing="kr",
                source=SOURCE_RULE_LISTED_EQUITY)
    return Classification(ticker=t, assigned=False, unassigned_reason=reason,
                          unassigned_note=_UNASSIGNED_TEXT.get(reason))


def asset_class_of(tickers: list[str]
                   ) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """티커 목록 → `(배정 맵, 미배정 목록)`.

    ★`sector_groups_for` 와 모양이 같지만 계약이 다르다★ — 저쪽은 미배정을
    **조용히 빠뜨린다**. 여기서는 빠진 것이 두 번째 반환값으로 반드시 나온다.
    """
    groups: dict[str, str] = {}
    missing: list[dict[str, Any]] = []
    for t in tickers:
        c = classify(t)
        if c.assigned and c.asset_class is not None:
            groups[c.ticker] = c.asset_class.value
        else:
            missing.append({"ticker": c.ticker, "reason": c.unassigned_reason,
                            "note": c.unassigned_note})
    return groups, missing


def exposures_of(ticker: str) -> tuple[str, ...] | None:
    """티커 → 경제노출 이름들. 미배정이면 `None`(빈 튜플이 아니다).

    ★빈 튜플과 미배정을 구분한다★ 빈 튜플은 "노출이 없다", `None` 은
    "모른다" 이고 둘은 다른 사실이다.
    """
    c = classify(ticker)
    return c.exposures if c.assigned else None


def coverage(tickers: list[str]) -> dict[str, Any]:
    """분류 커버리지 블록 — ★빠진 분류가 화면에 남는다★

    응답에 그대로 실을 수 있는 모양이다. 42개 중 4개가 빠졌다는 사실이
    사라지지 않게 한다.
    """
    groups, missing = asset_class_of(tickers)
    by_class: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for t in groups:
        c = classify(t)
        by_class[c.asset_class.value] = by_class.get(c.asset_class.value, 0) + 1
        by_source[c.source or "?"] = by_source.get(c.source or "?", 0) + 1
    reasons: dict[str, int] = {}
    for m in missing:
        reasons[m["reason"]] = reasons.get(m["reason"], 0) + 1
    return {
        "universe": len(tickers),
        "classified": len(groups),
        "unassigned": len(missing),
        "unassigned_tickers": [m["ticker"] for m in missing],
        "reasons": reasons,
        "by_asset_class": by_class,
        "by_source": by_source,
        "distinct_asset_classes": len(by_class),
        "version": TAXONOMY_VERSION,
        "as_of": TAXONOMY_AS_OF,
    }


def require_complete(tickers: list[str]) -> dict[str, str]:
    """전수 배정 관문 — 하나라도 미배정이면 **올린다**.

    Raises:
        TaxonomyIncomplete: 미배정이 하나라도 있을 때.
    """
    groups, missing = asset_class_of(tickers)
    if missing:
        detail = "; ".join(f"{m['ticker']}: {m['note'] or m['reason']}"
                           for m in missing[:5])
        more = f" 외 {len(missing) - 5}건" if len(missing) > 5 else ""
        raise TaxonomyIncomplete(
            f"{len(missing)}개 종목이 분류되지 않았습니다 — 분류가 계약인 경로에서는 "
            f"부분 배정으로 진행하지 않습니다 ({detail}{more})", missing)
    return groups


def registered_tickers() -> tuple[str, ...]:
    return tuple(sorted(_BY_TICKER))


def known_exposures() -> tuple[str, ...]:
    """레지스트리가 실제로 쓰는 노출 이름들 (어휘 정합성 검사용)."""
    out: set[str] = set()
    for s in _SPECS:
        out |= set(s.exposures)
    return tuple(sorted(out))
