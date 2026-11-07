"""마켓타이밍 팩터 카탈로그 + TimingRule 공통 스키마 (AAS TIMING 통합 팩터 창)
==============================================================================
AAS TIMING 탭의 카나리 신호와 백테스터 팩터 창을 하나의 "타이밍 팩터" 개념으로 통합한다.
모든 팩터는 아래 공통 스키마(TimingRule)로 등록되어 UI·API·저장이 동일한 형태를 공유한다.

TimingRule 스키마(사용자 제안 그대로):
  universe · signal_family · observation_window · entry_condition · exit_condition ·
  risk_off_asset · rebalance_or_holding_period · position_sizing · leverage_cap ·
  transaction_cost_and_slippage · point_in_time_data_timestamp

signal_family: momentum | deviation | breakout | overnight | regime
               | breadth | volatility | drawdown | correlation  (Phase 8)

재사용(신규 수학 최소화):
  · tactical_allocations._ret/_abs_mom/_score_13612/_accel/_above_ma_m/_above_ma_d
  · etf_prices.monthly_closes/daily_closes/daily_ohlc/daily_closes_indexed
    (as_of 시점절단 관례 포함. _indexed 는 두 종목을 날짜로 맞춰야 하는 계산용 — Phase 8)

정직성(중요):
  · systrader79 계열(평균절대모멘텀·가속듀얼모멘텀·Defense First 등)은 공개 포스팅으로
    규칙이 검증 가능해 그대로 구현한다(출처를 provenance에 명시).
  · 이격도·변동성돌파·채널돌파·오버나이트는 **공개된 일반 기술적 시그널 패밀리**로 구현한다.
    특정 유료 컨텐츠(백석꾼 등)의 정확한 조건식은 비공개이므로 재현했다고 주장하지 않으며,
    파라미터는 사용자가 직접 지정하는 일반형이다 — provenance="generic".
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.engine import timing_factor_meta as _meta

logger = logging.getLogger(__name__)

SIGNAL_FAMILIES = ("momentum", "deviation", "breakout", "overnight", "regime",
                   "breadth", "volatility", "drawdown", "correlation")


# ── 공통 스키마 ───────────────────────────────────────────────────────────────
@dataclass
class TimingRule:
    """타이밍 규칙 1건 — 시그널 + 실행/리스크 컨텍스트를 함께 담는 공통 등록 단위."""
    factor_id: str                                   # 카탈로그 팩터 id
    universe: list[str] = field(default_factory=list)  # 평가 대상 티커(비면 factor 기본값)
    signal_family: str = "momentum"
    observation_window: dict[str, Any] = field(default_factory=dict)  # {"months":12} | {"days":20} 등
    entry_condition: str = ""                        # 사람이 읽는 진입 조건 서술
    exit_condition: str = ""
    risk_off_asset: list[str] = field(default_factory=list)   # 위험-오프 시 전환 자산
    rebalance_or_holding_period: str = "month_end"    # month_end | week | day | overnight
    position_sizing: str = "equal"                    # equal | score_weighted | vol_target | inverse_vol
    leverage_cap: float = 1.0                         # 1.0 = 무레버리지
    transaction_cost_and_slippage: dict[str, float] = field(
        default_factory=lambda: {"cost_bps": 10.0, "slippage_bps": 5.0})
    point_in_time_data_timestamp: str | None = None   # 평가 시점(UTC ISO) — 룩어헤드 감사용
    params: dict[str, Any] = field(default_factory=dict)  # 팩터별 파라미터(lookback/threshold 등)
    label: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def stamp_pit(rule: TimingRule) -> TimingRule:
    """평가 직전 PIT 타임스탬프 각인 — 언제 관측된 데이터로 판단했는지 남긴다."""
    rule.point_in_time_data_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return rule


# ── 신규 시그널 구현 (기존 프리미티브 재사용) ─────────────────────────────────
def avg_abs_momentum(ticker: str, market: str = "kr", max_months: int = 12) -> float | None:
    """평균 절대 모멘텀 (systrader79) — 과거 1~N개월 수익률 중 양(+)인 비율(0~1).

    "예측해서 전부 사고 파는" 이진 신호가 아니라 **추세 강도에 비례한 위험자산 비중**으로 쓰는
    연속값이 원 규칙의 핵심. 0.6이면 위험자산 60%/현금 40%.
    출처: stock79.tistory.com (실전 투자 전략 5 — 절대 모멘텀 전략).
    """
    from src.data.etf_prices import monthly_closes
    from src.engine.tactical_allocations import _ret
    c = monthly_closes(ticker, market, max_months + 2)
    hits, seen = 0, 0
    for m in range(1, max_months + 1):
        r = _ret(c, m)
        if r is None:
            continue
        seen += 1
        if r > 0:
            hits += 1
    if seen == 0:
        return None
    return hits / seen


def accel_momentum(ticker: str, market: str = "kr") -> float | None:
    """가속 모멘텀 — 1·3·6개월 수익률 평균 (가속 듀얼모멘텀의 스코어 부분).

    기존 tactical_allocations._accel(합)을 평균으로 정규화해 임계 비교를 직관적으로.
    출처: stock79.tistory.com (Accelerating dual momentum).
    """
    from src.engine.tactical_allocations import _accel
    s = _accel(ticker, market)
    return None if s is None else s / 3.0


def disparity(ticker: str, market: str = "kr", ma_days: int = 20) -> float | None:
    """이격도 = 종가 / N일 이동평균 × 100. 100이면 이평선과 동일, 105면 5% 위.

    일반 기술적 지표(공개) — 특정 유료 전략의 조건식 재현이 아니다. 밴드 임계는 사용자 지정.
    """
    from src.data.etf_prices import daily_closes
    c = daily_closes(ticker, market, ma_days + 30)
    if len(c) < ma_days + 1:
        return None
    ma = sum(c[-ma_days:]) / ma_days
    if ma <= 0:
        return None
    return c[-1] / ma * 100.0


def vol_breakout(ticker: str, market: str = "kr", k: float = 0.5) -> float | None:
    """변동성 돌파(Larry Williams형) — (당일 종가 − 돌파선) / 돌파선 × 100.

    돌파선 = 당일 시가 + k × 전일 레인지(고가−저가). 양수면 돌파 성공.
    일반 공개 기법의 파라미터화 구현(k는 사용자 지정).
    """
    from src.data.etf_prices import daily_ohlc
    bars = daily_ohlc(ticker, market, 40)
    if len(bars) < 2:
        return None
    prev, cur = bars[-2], bars[-1]
    rng = prev["high"] - prev["low"]
    trigger = cur["open"] + k * rng
    if trigger <= 0:
        return None
    return (cur["close"] - trigger) / trigger * 100.0


def channel_breakout(ticker: str, market: str = "kr", days: int = 20) -> float | None:
    """채널 돌파 — (종가 − N일 최고가) / N일 최고가 × 100. 양수면 상단 돌파(도너찬형).

    직전 N봉(당일 제외)의 고가 채널을 기준으로 한다(당일 고가 포함 시 자기참조).
    """
    from src.data.etf_prices import daily_ohlc
    bars = daily_ohlc(ticker, market, days + 20)
    if len(bars) < days + 1:
        return None
    hi = max(b["high"] for b in bars[-days - 1:-1])
    if hi <= 0:
        return None
    return (bars[-1]["close"] - hi) / hi * 100.0


def overnight_return(ticker: str, market: str = "kr", days: int = 20) -> float | None:
    """오버나이트 수익률 평균(%) — 최근 N일의 (당일 시가 / 전일 종가 − 1) 평균.

    종가 진입 → 익일 시가 청산 계열의 기대값 프록시. 일간 OHLC만으로 산출 가능
    (분봉 불필요). 장중 경로는 반영하지 않음 — 정직한 근사.
    """
    from src.data.etf_prices import daily_ohlc
    bars = daily_ohlc(ticker, market, days + 5)
    if len(bars) < 2:
        return None
    vals = []
    for i in range(max(1, len(bars) - days), len(bars)):
        pc = bars[i - 1]["close"]
        if pc > 0:
            vals.append(bars[i]["open"] / pc - 1.0)
    if not vals:
        return None
    return sum(vals) / len(vals) * 100.0


_DEFENSE_BASKET = ("TLT", "GLD", "PDBC", "UUP")


def defense_first(_ticker: str | None = None, market: str = "kr",
                  basket: tuple[str, ...] = _DEFENSE_BASKET,
                  cash: str = "BIL") -> float | None:
    """Defense First (systrader79) 역발상 시그널 — 방어자산 평균모멘텀 − 현금성 모멘텀.

    방어자산(TLT·GLD·PDBC·UUP)이 무위험자산보다 **약하면** 위험선호(risk-on) 신호로 해석한다.
    따라서 값이 **음수일 때 위험-온** — 다른 팩터와 부호 방향이 반대라 UI에 명시한다.
    출처: stock79.tistory.com (Defense First 자산배분전략).
    """
    from src.engine.tactical_allocations import _score_13612
    scores = [s for s in (_score_13612(t, market) for t in basket) if s is not None]
    if not scores:
        return None
    cash_s = _score_13612(cash, market)
    if cash_s is None:
        return None
    return sum(scores) / len(scores) - cash_s


# ── 카탈로그 ─────────────────────────────────────────────────────────────────
# (id, 라벨, 패밀리, 기본파라미터, 단위/설명, 통과방향 기본, provenance)
# ── Phase 8 신규 팩터 ─────────────────────────────────────────────────────────
#
# ★수치 안전이 이 절의 1급 요구사항이다★ (CLAUDE.md)
# 로그·제곱근·나눗셈에 0 이나 음수가 들어갈 수 있는 자리를 전부 가드한다. 그리고 그 조건은
# **실데이터에서만 나온다** — mock 시계열은 항상 양수·우상향이라 평평한 구간도, 0 분산도,
# 0 이하 가격도 만들어 주지 않는다. 가드가 없으면 CI 는 영원히 초록이고 적자 국면에서 처음 터진다.

#: 브레드스 기본 바스켓 — `_DEFENSE_BASKET` 선례를 따른다(카탈로그 기본값, 사용자 변경 가능).
_BREADTH_BASKET = ("SPY", "QQQ", "IWM", "EFA", "EEM")
#: 연율화 계수 — 일간 표준편차 → 연 %.
_TRADING_DAYS_PER_YEAR = 252


def _pct_returns(closes: list[float]) -> list[float]:
    """단순 수익률. ★0 이하 가격은 건너뛴다★ — 로그도 나눗셈도 성립하지 않는다."""
    out = []
    for prev, cur in zip(closes, closes[1:]):
        if prev is None or cur is None or prev <= 0 or cur <= 0:
            continue
        out.append(cur / prev - 1.0)
    return out


def _stdev(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return var ** 0.5 if var > 0 else 0.0     # var 는 정의상 음수가 아니지만 부동소수 방어


def relative_momentum(ticker: str, market: str = "kr", months: int = 12,
                      benchmark: str = "AGG") -> float | None:
    """상대 모멘텀 — 자산 N개월 수익률 − 벤치마크 N개월 수익률 (%p).

    듀얼 모멘텀의 '상대' 절반. 절대 모멘텀(`abs_mom`)이 "오르고 있는가" 를 묻는다면 이쪽은
    "무엇보다 더 오르고 있는가" 를 묻는다.
    ★벤치마크를 못 읽으면 None★ — 자산 단독 수익률로 대체하면 그건 다른 팩터다.
    """
    from src.data.etf_prices import monthly_closes
    from src.engine.tactical_allocations import _ret
    a = _ret(monthly_closes(ticker, market, months + 2), months)
    b = _ret(monthly_closes(benchmark, market, months + 2), months)
    if a is None or b is None:
        return None
    return (a - b) * 100.0


def breadth_above_ma(_ticker: str | None = None, market: str = "kr", days: int = 200,
                     basket: tuple[str, ...] | list[str] | None = None) -> float | None:
    """브레드스 — 바스켓 중 N일 이동평균을 웃도는 종목 비율(0~100%).

    참여 폭이 넓을수록 위험-온. ★읽지 못한 종목은 '이탈' 로 세지 않는다★ —
    결측과 하락은 다른 사실이고, 결측을 하락으로 세면 데이터 장애가 약세 신호로 둔갑한다.
    """
    from src.data.etf_prices import daily_closes
    names = tuple(basket) if basket else _BREADTH_BASKET
    hits, seen = 0, 0
    for t in names:
        c = daily_closes(t, market, days + 5)
        if len(c) < days:
            continue                       # 읽지 못했다 — 분모에서도 뺀다
        ma = sum(c[-days:]) / days
        if ma <= 0:
            continue
        seen += 1
        if c[-1] > ma:
            hits += 1
    if seen == 0:
        return None
    return hits / seen * 100.0


def equal_vs_cap(_ticker: str | None = None, market: str = "kr", months: int = 6,
                 equal: str = "RSP", cap: str = "SPY") -> float | None:
    """동일가중 − 시총가중 수익률 (%p). 양수면 상승이 소수 대형주에 쏠리지 않았다는 뜻.

    ★국내 시장에는 매핑된 동일가중 ETF 가 없다★ market="kr" 에서 기본값 RSP 는 해석되지
    않아 None 이 된다 — 지어내지 않고 정직하게 결측으로 둔다. 티커는 파라미터이므로
    국내 동일가중 상품이 있으면 사용자가 지정할 수 있다.
    """
    from src.data.etf_prices import monthly_closes
    from src.engine.tactical_allocations import _ret
    e = _ret(monthly_closes(equal, market, months + 2), months)
    c = _ret(monthly_closes(cap, market, months + 2), months)
    if e is None or c is None:
        return None
    return (e - c) * 100.0


def realized_vol(ticker: str, market: str = "kr", days: int = 20) -> float | None:
    """실현 변동성 — 일간 수익률 표준편차의 연율화(%). 낮을수록 위험-온."""
    from src.data.etf_prices import daily_closes
    c = daily_closes(ticker, market, days + 5)
    r = _pct_returns(c[-(days + 1):])
    s = _stdev(r)
    if s is None:
        return None
    return s * (_TRADING_DAYS_PER_YEAR ** 0.5) * 100.0


def vol_regime(ticker: str, market: str = "kr", days: int = 20,
               ref_days: int = 250) -> float | None:
    """단기 변동성 ÷ 장기 기준 변동성. 1 미만이면 평소보다 조용한 국면(위험-온).

    ★기준 변동성이 0 이면 None★ — 나눌 수 없다. 완전히 평평한 구간은 실데이터(거래정지·
    상장 직후)에 실제로 존재하고, mock 에는 존재하지 않는다.
    """
    from src.data.etf_prices import daily_closes
    c = daily_closes(ticker, market, ref_days + 5)
    short = _stdev(_pct_returns(c[-(days + 1):]))
    long = _stdev(_pct_returns(c[-(ref_days + 1):]))
    if short is None or long is None or long <= 0:
        return None
    return short / long


def target_vol_size(ticker: str, market: str = "kr", days: int = 20,
                    target_vol: float = 10.0) -> float | None:
    """목표변동성 사이징 — 목표 ÷ 실현, 0~1 로 클립한 **비중**(이진 신호가 아니다).

    `avg_abs_momentum` 과 같은 연속 비중 계열. 시장이 완전히 잠잠하면(실현 0) 비율은 무한대가
    되므로 **예외가 아니라 상한 1.0** 으로 자른다 — 레버리지는 이 팩터의 역할이 아니다.
    """
    rv = realized_vol(ticker, market, days)
    if rv is None:
        return None
    if rv <= 0:
        return 1.0                          # 무변동 → 상한(레버리지 없음)
    return max(0.0, min(1.0, float(target_vol) / rv))


def _peak_and_last(closes: list[float]) -> tuple[float, float] | None:
    xs = [x for x in closes if x is not None and x > 0]
    if len(xs) < 2:
        return None
    peak = max(xs)
    return (peak, xs[-1]) if peak > 0 else None


def drawdown(ticker: str, market: str = "kr", days: int = 250) -> float | None:
    """현재 낙폭 — 구간 고점 대비 (%). 0 이면 신고가, 음수면 고점 아래.

    임계보다 **위**(덜 깊은 낙폭)면 위험-온이므로 default_direction="above".
    """
    from src.data.etf_prices import daily_closes
    pl = _peak_and_last(daily_closes(ticker, market, days))
    if pl is None:
        return None
    peak, last = pl
    return max(-100.0, (last / peak - 1.0) * 100.0)


def drawdown_speed(ticker: str, market: str = "kr", days: int = 250,
                   window: int = 20) -> float | None:
    """낙폭 변화 속도 — 최근 window 일 동안 낙폭이 얼마나 더 깊어졌나(%p).

    음수면 빠르게 무너지는 중. 같은 −10% 라도 1년에 걸친 것과 2주 만의 것은 다른 이야기다.
    """
    from src.data.etf_prices import daily_closes
    c = daily_closes(ticker, market, days)
    if len(c) < window + 2:
        return None
    now = _peak_and_last(c)
    then = _peak_and_last(c[:-window])
    if now is None or then is None:
        return None
    dd_now = (now[1] / now[0] - 1.0) * 100.0
    dd_then = (then[1] / then[0] - 1.0) * 100.0
    return dd_now - dd_then


def recovery_state(ticker: str, market: str = "kr", days: int = 250) -> float | None:
    """회복 정도 — 구간 저점에서 고점까지의 거리 중 현재까지 되찾은 비율(0~1).

    1 이면 신고가 회복, 0 이면 저점. 낙폭의 깊이가 아니라 **회복 국면인지**를 본다.
    """
    from src.data.etf_prices import daily_closes
    xs = [x for x in daily_closes(ticker, market, days) if x is not None and x > 0]
    if len(xs) < 2:
        return None
    peak, trough, last = max(xs), min(xs), xs[-1]
    span = peak - trough
    if span <= 0:
        return 1.0                          # 완전 평평 — 되찾을 낙폭 자체가 없다
    return max(0.0, min(1.0, (last - trough) / span))


def rolling_correlation(ticker: str, market: str = "kr", days: int = 60,
                        benchmark: str = "TLT") -> float | None:
    """롤링 상관 — 자산과 벤치마크 일간 수익률의 피어슨 상관(−1~1).

    ★두 종목을 날짜로 맞춘 뒤 계산한다★
    `daily_closes` 는 값만 주므로 꼬리를 zip 하면 서로 다른 거래일끼리 짝지어진다(한·미 휴장일
    차이, 상장일 차이). 그래서 `daily_closes_indexed` 로 날짜를 받아 **겹치는 날짜만** 쓴다.
    겹치는 구간이 창보다 짧으면 None — 짧은 표본으로 계산한 상관을 같은 값처럼 내보내지 않는다.

    주식-채권 상관이 음수면 분산이 살아 있다는 뜻이라 위험-온 쪽(default_direction="below").
    """
    from src.data.etf_prices import daily_closes_indexed
    a = dict(daily_closes_indexed(ticker, market, days * 2))
    b = dict(daily_closes_indexed(benchmark, market, days * 2))
    common = sorted(set(a) & set(b))
    if len(common) < max(5, days // 2):
        return None
    ra = _pct_returns([a[d] for d in common])
    rb = _pct_returns([b[d] for d in common])
    n = min(len(ra), len(rb))
    if n < 2:
        return None
    ra, rb = ra[-n:], rb[-n:]
    ma, mb = sum(ra) / n, sum(rb) / n
    sa, sb = _stdev(ra), _stdev(rb)
    if not sa or not sb:
        return None                         # 한쪽이 무변동 → 상관은 정의되지 않는다
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (n - 1)
    return max(-1.0, min(1.0, cov / (sa * sb)))


# ── Phase 8: 한국 세트 (Drift 8-2) ────────────────────────────────────────────
#
# ★지수가 아니라 ETF 를 잰다★
# KOSDAQ 은 수집 대상이 아니고 KOSPI 는 ECOS 라 vintage 가 없다(§6.1 기준 forward_only).
# 지수 시계열로는 만들 수 없어서 **거래되는 ETF 로 근사**한다. 추적오차·보수가 신호 안에
# 들어오므로 그 사실을 설명에 적는다 — 안 적으면 사용자는 "KOSPI 대비" 라고 읽는다.
# 지수 자체를 쓰려면 수집기에 시리즈를 추가해야 하고, 그건 Phase 8b(데이터 소스) 소관이다.
_KOSDAQ_ETF = "229200"      # KODEX 코스닥150
_KOSPI_ETF = "069500"       # KODEX 200
_USD_ETF = "261240"         # KODEX 미국달러선물

#: 섹터 디스퍼전용 국내 섹터 ETF 바스켓 (Phase 8b — Drift 8-1 로 Phase 8 에서 재배치).
#: ★섹터 지수 시계열이 이 코드베이스에 없다★ `stock_master.get_stock_sector()` 는 종목→섹터
#: **이름**만 주고 섹터별 가격 이력은 어디에도 없다. 그래서 거래되는 섹터 ETF 로 근사한다 —
#: 추적오차·보수·유동성 차이가 신호에 섞이며, 그건 섹터 지수 간 분산과 같지 않다.
_KR_SECTOR_ETFS = (
    "091160",   # KODEX 반도체
    "091180",   # KODEX 자동차
    "091170",   # KODEX 은행
    "266370",   # KODEX 2차전지산업
    "227540",   # TIGER 200 헬스케어
)


def sector_dispersion(_ticker: str | None = None, market: str = "kr", days: int = 20,
                      basket: tuple[str, ...] | list[str] | None = None) -> float | None:
    """섹터 디스퍼전 — 섹터 ETF 들의 N일 수익률 **횡단면 표준편차**(%p).

    값이 크면 섹터가 제각기 움직인다는 뜻(종목 선택이 통하는 국면), 작으면 다 같이 움직인다.

    ★읽지 못한 섹터가 하나라도 있으면 None★ 브레드스와 달리 여기서는 부분 집합으로 계산하면
    안 된다 — 분산은 **구성원 집합에 의존**하므로, 3개만 읽힌 분산과 5개 분산은 비교할 수 없는
    다른 수치다. 결측을 0% 수익률로 채우면 있지도 않은 분산을 만들어낸다.
    분산은 최소 2개 섹터가 필요하다(하나로는 정의되지 않는다 — 0 이 아니라 None).
    """
    from src.data.etf_prices import daily_closes
    names = tuple(basket) if basket else _KR_SECTOR_ETFS
    if len(names) < 2:
        return None
    rets = []
    for t in names:
        c = daily_closes(t, market, days + 5)
        if len(c) < days + 1 or c[-days - 1] <= 0:
            return None                     # 하나라도 못 읽으면 비교 불가능한 수치가 된다
        rets.append(c[-1] / c[-days - 1] - 1.0)
    sd = _stdev(rets)
    return None if sd is None else sd * 100.0


def kospi_kosdaq_rs(_ticker: str | None = None, market: str = "kr", months: int = 6,
                    growth: str = _KOSDAQ_ETF, core: str = _KOSPI_ETF) -> float | None:
    """코스닥 − 코스피 상대강도 (%p, ETF 프록시).

    성장·중소형(코스닥)이 대형(코스피)을 앞서면 위험선호 국면으로 읽는다.
    한쪽이라도 못 읽으면 None — 한쪽 수익률만으로 상대강도를 말할 수 없다.
    """
    from src.data.etf_prices import monthly_closes
    from src.engine.tactical_allocations import _ret
    g = _ret(monthly_closes(growth, market, months + 2), months)
    c = _ret(monthly_closes(core, market, months + 2), months)
    if g is None or c is None:
        return None
    return (g - c) * 100.0


def usdkrw_trend(_ticker: str | None = None, market: str = "kr", months: int = 6,
                 proxy: str = _USD_ETF) -> float | None:
    """원/달러 추세 (%, 달러선물 ETF 프록시). 양수면 달러 강세 = 원화 약세.

    원화 약세는 국내 주식에 위험-오프 쪽이라 카탈로그 방향이 `below` 다.
    ECOS 의 731Y001(원/달러)은 vintage 가 없어 forward_only 이므로, 가격 경로를 쓴다.
    """
    from src.data.etf_prices import monthly_closes
    from src.engine.tactical_allocations import _ret
    r = _ret(monthly_closes(proxy, market, months + 2), months)
    return None if r is None else r * 100.0


CATALOG: list[dict[str, Any]] = [
    # ── momentum ──
    {"id": "score_13612", "label": "13612W 가속모멘텀", "family": "momentum",
     "evaluation_frequency": "month",
     "params": {}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "score", "desc": "1·3·6·12개월 수익률 가중합(12/4/2/1). VAA·DAA 위험-온 판정 기준.",
     "provenance": "Keller & Keuning (VAA/DAA)", "existing": True},
    {"id": "abs_mom", "label": "절대모멘텀 (N개월)", "family": "momentum",
     "evaluation_frequency": "month",
     "params": {"months": 12}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "ratio", "desc": "N개월 누적 수익률. 0 초과면 위험-온(듀얼모멘텀의 절대 필터).",
     "provenance": "Antonacci (Dual Momentum)", "existing": True},
    {"id": "avg_abs_momentum", "label": "평균 절대 모멘텀 (연속 비중)", "family": "momentum",
     "evaluation_frequency": "month",
     "params": {"max_months": 12}, "default_threshold": 0.5, "default_direction": "above",
     "unit": "weight_0_1", "desc": "과거 1~N개월 중 수익률이 양(+)인 비율(0~1) — 이진 신호가 아니라 "
                                   "추세 강도에 비례하는 위험자산 비중으로 쓰는 것이 원 규칙.",
     "provenance": "systrader79 (절대 모멘텀 전략)", "existing": False},
    {"id": "accel_momentum", "label": "가속 모멘텀 (1·3·6 평균)", "family": "momentum",
     "evaluation_frequency": "month",
     "params": {}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "ratio", "desc": "1·3·6개월 수익률 평균. 가속 듀얼모멘텀의 스코어 부분.",
     "provenance": "systrader79 (Accelerating dual momentum)", "existing": False},
    {"id": "ma_month", "label": "N개월 이동평균 상회", "family": "momentum",
     "evaluation_frequency": "month",
     "params": {"months": 10}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "bool", "desc": "월봉 N개월 이동평균 상회 여부(GTAA형 추세 필터).",
     "provenance": "Faber (GTAA)", "existing": True},
    {"id": "ma_day", "label": "N일 이동평균 상회", "family": "momentum",
     "evaluation_frequency": "day",
     "params": {"days": 200}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "bool", "desc": "일봉 N일 이동평균 상회 여부(200일선 추세 게이트).",
     "provenance": "classic trend filter", "existing": True},
    # ── deviation ──
    {"id": "disparity", "label": "이격도 (종가/이평 ×100)", "family": "deviation",
     "evaluation_frequency": "day",
     "params": {"ma_days": 20}, "default_threshold": 105.0, "default_direction": "below",
     "unit": "pct_of_ma", "desc": "종가 ÷ N일 이동평균 × 100. 100=이평선. 과열 밴드 이탈 판정에 사용. "
                                  "일반 공개 지표 — 특정 유료 전략의 조건식 재현이 아님(밴드는 직접 지정).",
     "provenance": "generic", "existing": False},
    # ── breakout ──
    {"id": "vol_breakout", "label": "변동성 돌파 (k × 전일 레인지)", "family": "breakout",
     "evaluation_frequency": "day",
     "params": {"k": 0.5}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "pct", "desc": "돌파선=당일시가+k×전일(고−저). (종가−돌파선)/돌파선×100. 양수면 돌파 성공. "
                            "일반 공개 기법의 파라미터화 구현.",
     "provenance": "generic (Larry Williams형)", "existing": False},
    {"id": "channel_breakout", "label": "채널 돌파 (N일 고가)", "family": "breakout",
     "evaluation_frequency": "day",
     "params": {"days": 20}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "pct", "desc": "직전 N봉 고가 채널 대비 종가 위치(%). 양수면 상단 돌파(도너찬형). "
                            "당일 봉은 채널 산정에서 제외(자기참조 방지).",
     "provenance": "generic (Donchian형)", "existing": False},
    # ── overnight ──
    {"id": "overnight_return", "label": "오버나이트 수익률 (N일 평균)", "family": "overnight",
     "evaluation_frequency": "overnight",
     "params": {"days": 20}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "pct", "desc": "최근 N일 (당일시가/전일종가−1) 평균(%). 종가진입→익일시가청산 기대값 프록시. "
                            "일간 OHLC 기반이라 장중 경로는 미반영(정직한 근사).",
     "provenance": "generic", "existing": False},
    # ── regime ──
    {"id": "defense_first", "label": "Defense First (역발상)", "family": "regime",
     "evaluation_frequency": "month",
     "params": {}, "default_threshold": 0.0, "default_direction": "below",
     "unit": "score_diff", "desc": "방어자산(TLT·GLD·PDBC·UUP) 평균 13612 − 현금성(BIL). "
                                   "★음수일 때 위험-온★ — 방어자산이 약하면 위험선호로 해석(부호 반대).",
     "provenance": "systrader79 (Defense First)", "existing": False},
    {"id": "indicator", "label": "매크로 지표 임계", "family": "regime",
     "evaluation_frequency": "day",
     "params": {"series_id": "VIXCLS"}, "default_threshold": 20.0, "default_direction": "below",
     "unit": "raw", "desc": "VIXCLS·DGS10·T10Y2Y 등 매크로 시리즈의 임계 통과(FRED/ECOS). "
                            "★ALFRED 빈티지 기준★ — 그 시점에 알 수 있었던 값만 쓴다. "
                            "FRED_API_KEY 가 없으면 unavailable(0 으로 대체하지 않는다).",
     "provenance": "FRED/ECOS", "existing": True,
     # ★requires_as_of 를 붙이지 않는다★ (Phase 8b)
     # 붙이면 팩터 창이 "추가 불가" 로 표시해 **지금 되는 흐름이 사라진다** — 이 팩터는
     # 레거시 카나리 경로(`macro_analytics`)로 평가되고 있고 그 경로는 as_of 가 필요 없다.
     # 대신 `read_factor` 가 as_of 가 주어졌을 때만 시점 기반 리더로 보낸다: V2 는 올바른
     # 빈티지를 읽고, 기존 UI 능력은 그대로 남는다.
     },
    {"id": "financial_conditions", "label": "금융환경지수 (NFCI)", "family": "regime",
     "evaluation_frequency": "week",
     "params": {}, "default_threshold": 0.0, "default_direction": "below",
     "unit": "index", "desc": "시카고 연은 NFCI. 양수면 긴축, 음수면 완화 — 완화 쪽이 위험-온이라 "
                              "임계 **아래**가 통과. ★주간이고 개정된다★ 그래서 ALFRED 빈티지 "
                              "경로로만 읽는다(오늘 개정판으로 과거를 채점하면 그 시점에 알 수 "
                              "없던 정보를 쓰는 것이 된다). 키가 없으면 unavailable.",
     "provenance": "FRED/ALFRED (NFCI)", "existing": False,
     "requires_as_of": True},
    {"id": "vix_term_structure", "label": "VIX 텀 스트럭처 (30일÷3개월)", "family": "volatility",
     "evaluation_frequency": "day",
     "params": {}, "default_threshold": 1.0, "default_direction": "below",
     "unit": "ratio", "desc": "VIXCLS ÷ VXVCLS. 1 미만이면 콘탱고(평온)라 위험-온, 초과면 "
                              "백워데이션(스트레스). ★스프레드가 아니라 비율★ — 단위가 없어 "
                              "변동성 수준이 달라도 비교된다. ★한국 결정은 전날(D−1) 미국 "
                              "종가를 쓴다★ 당일 미국 종가는 KRX 장 마감 뒤에 나오므로 쓰면 "
                              "룩어헤드다. 전날이 미국 휴장이면 전진 채움하지 않고 unavailable.",
     "provenance": "FRED/ALFRED (VIXCLS·VXVCLS), 스펙 §6.2", "existing": False,
     "requires_as_of": True},
    {"id": "vix_term_spread", "label": "VIX 텀 스프레드 (30일−3개월)", "family": "volatility",
     "evaluation_frequency": "day",
     "params": {}, "default_threshold": 0.0, "default_direction": "below",
     "unit": "pp", "desc": "VIXCLS − VXVCLS(포인트). 비율 팩터의 **스프레드 변형**으로, 원하는 "
                           "사용자를 위해 따로 제공한다. ★같은 2포인트가 VIX 12 일 때와 45 일 "
                           "때 다른 뜻이라는 한계가 있다★ — 그래서 기본 팩터는 비율 쪽이다. "
                           "정렬·결측 규칙은 비율 팩터와 같다(D−1 미국 종가, 전진 채움 없음).",
     "provenance": "FRED/ALFRED (VIXCLS·VXVCLS), 스펙 §6.2", "existing": False,
     "requires_as_of": True},
    {"id": "curve_slope", "label": "장단기 금리차 (10Y−2Y)", "family": "regime",
     "evaluation_frequency": "day",
     "params": {"series_id": "T10Y2Y"}, "default_threshold": 0.0, "default_direction": "above",
     "unit": "pp", "desc": "미 국채 10년−2년 스프레드(%p). 양수면 정상 커브(위험-온), "
                           "음수면 역전(위험-오프). ★ALFRED 빈티지 기준으로 그 시점에 "
                           "알 수 있었던 값만 사용★ — 개정 이력이 있어 오늘 값으로 과거를 "
                           "채점하면 안 된다. FRED_API_KEY 가 없으면 unavailable.",
     "provenance": "FRED/ALFRED (T10Y2Y)", "existing": False,
     # ★as_of 가 필요한 팩터★ — evaluate(factor_id, ticker, market, params) 로는 시점을
     # 전달할 수 없다. timing_rules_v2.read_curve_slope(as_of) 를 써야 한다.
     "requires_as_of": True},
    # ── Phase 8: 상대 모멘텀 ──
    {"id": "relative_momentum", "label": "상대 모멘텀 (vs 벤치마크)", "family": "momentum",
     "evaluation_frequency": "month",
     "params": {"months": 12, "benchmark": "AGG"},
     "default_threshold": 0.0, "default_direction": "above",
     "unit": "pp", "desc": "자산 N개월 수익률 − 벤치마크 N개월 수익률(%p). 듀얼 모멘텀의 '상대' "
                           "절반 — 절대 모멘텀이 '오르고 있는가'라면 이쪽은 '무엇보다 더 "
                           "오르고 있는가'를 묻는다. 벤치마크를 못 읽으면 자산 단독 수익률로 "
                           "대체하지 않고 unavailable.",
     "provenance": "Antonacci (Dual Momentum — relative half)", "existing": False},
    # ── Phase 8: 브레드스 ──
    {"id": "breadth_above_ma", "label": "브레드스 (N일 이평 상회 비율)", "family": "breadth",
     "evaluation_frequency": "day",
     "params": {"days": 200}, "default_threshold": 50.0, "default_direction": "above",
     "unit": "pct_0_100", "desc": "바스켓 중 N일 이동평균을 웃도는 종목 비율(%). 참여 폭이 "
                                  "넓을수록 위험-온. ★읽지 못한 종목은 '이탈'로 세지 않는다★ — "
                                  "결측을 하락으로 세면 데이터 장애가 약세 신호로 둔갑한다.",
     "provenance": "generic (market breadth)", "existing": False},
    {"id": "equal_vs_cap", "label": "동일가중 vs 시총가중", "family": "breadth",
     "evaluation_frequency": "month",
     "params": {"months": 6, "equal": "RSP", "cap": "SPY"},
     "default_threshold": 0.0, "default_direction": "above",
     "unit": "pp", "desc": "동일가중 − 시총가중 수익률(%p). 양수면 상승이 소수 대형주에 "
                           "쏠리지 않았다는 뜻. ★국내에는 매핑된 동일가중 ETF가 없어 "
                           "market=kr 기본값으로는 unavailable★ — 티커는 직접 지정 가능.",
     "provenance": "generic (breadth via equal-weight spread)", "existing": False},
    # ── Phase 8: 변동성 ──
    {"id": "realized_vol", "label": "실현 변동성 (연율 %)", "family": "volatility",
     "evaluation_frequency": "day",
     "params": {"days": 20}, "default_threshold": 20.0, "default_direction": "below",
     "unit": "pct_annual", "desc": "일간 수익률 표준편차의 연율화(%). 낮을수록 위험-온이라 "
                                   "임계 **아래**가 통과. 0 이하 가격은 수익률 계산에서 제외.",
     "provenance": "generic (realized volatility)", "existing": False},
    {"id": "vol_regime", "label": "변동성 국면 (단기÷장기)", "family": "volatility",
     "evaluation_frequency": "day",
     "params": {"days": 20, "ref_days": 250},
     "default_threshold": 1.0, "default_direction": "below",
     "unit": "ratio", "desc": "단기 변동성 ÷ 장기 기준 변동성. 1 미만이면 평소보다 조용한 국면. "
                              "기준 변동성이 0이면(거래정지·상장직후) 나눌 수 없으므로 unavailable.",
     "provenance": "generic (volatility regime)", "existing": False},
    {"id": "target_vol_size", "label": "목표변동성 사이징 (비중)", "family": "volatility",
     "evaluation_frequency": "day",
     "params": {"days": 20, "target_vol": 10.0},
     "default_threshold": 0.5, "default_direction": "above",
     "unit": "weight_0_1", "desc": "목표변동성 ÷ 실현변동성을 0~1로 자른 **비중**(이진 신호가 "
                                   "아니다). 평균절대모멘텀과 같은 연속 비중 계열. 무변동 구간은 "
                                   "무한대가 아니라 상한 1.0 — 레버리지는 이 팩터의 역할이 아니다.",
     "provenance": "generic (volatility targeting)", "existing": False},
    # ── Phase 8: 낙폭 ──
    {"id": "drawdown", "label": "현재 낙폭 (고점 대비 %)", "family": "drawdown",
     "evaluation_frequency": "day",
     "params": {"days": 250}, "default_threshold": -10.0, "default_direction": "above",
     "unit": "pct", "desc": "구간 고점 대비 현재 위치(%). 0이면 신고가, 음수면 고점 아래. "
                            "임계보다 **위**(덜 깊은 낙폭)면 위험-온.",
     "provenance": "generic (drawdown filter)", "existing": False},
    {"id": "drawdown_speed", "label": "낙폭 속도 (최근 N일 변화 %p)", "family": "drawdown",
     "evaluation_frequency": "day",
     "params": {"days": 250, "window": 20},
     "default_threshold": -5.0, "default_direction": "above",
     "unit": "pp", "desc": "최근 window일 동안 낙폭이 얼마나 더 깊어졌나(%p). 음수면 빠르게 "
                           "무너지는 중 — 같은 −10%라도 1년에 걸친 것과 2주 만의 것은 다르다.",
     "provenance": "generic (drawdown velocity)", "existing": False},
    {"id": "recovery_state", "label": "회복 정도 (저점→고점 중 되찾은 비율)", "family": "drawdown",
     "evaluation_frequency": "day",
     "params": {"days": 250}, "default_threshold": 0.9, "default_direction": "above",
     "unit": "weight_0_1", "desc": "구간 저점에서 고점까지 중 현재까지 되찾은 비율(0~1). "
                                   "낙폭의 깊이가 아니라 **회복 국면인지**를 본다.",
     "provenance": "generic (recovery state)", "existing": False},
    # ── Phase 8: 상관 ──
    {"id": "rolling_correlation", "label": "롤링 상관 (vs 벤치마크)", "family": "correlation",
     "evaluation_frequency": "day",
     "params": {"days": 60, "benchmark": "TLT"},
     "default_threshold": 0.0, "default_direction": "below",
     "unit": "corr", "desc": "자산과 벤치마크 일간 수익률의 상관(−1~1). 주식-채권 상관이 "
                             "음수면 분산이 살아 있다는 뜻이라 위험-온 쪽. ★두 종목을 "
                             "**날짜로 맞춘 뒤** 겹치는 날짜만 사용★ — 값만 zip 하면 한·미 "
                             "휴장일 차이로 다른 날짜끼리 짝지어진다. 벤치마크를 바꾸면 "
                             "주식-채권/크로스에셋 어느 쪽이든 같은 팩터로 볼 수 있다.",
     "provenance": "generic (rolling correlation)", "existing": False},
    # ── Phase 8: 한국 세트 (ETF 프록시 — Drift 8-2) ──
    {"id": "kospi_kosdaq_rs", "label": "코스닥−코스피 상대강도", "family": "regime",
     "evaluation_frequency": "month",
     "params": {"months": 6, "growth": "229200", "core": "069500"},
     "default_threshold": 0.0, "default_direction": "above",
     "unit": "pp", "desc": "코스닥150 − 코스피200 수익률(%p). 성장·중소형이 대형을 앞서면 "
                           "위험선호 국면. ★지수가 아니라 ETF(KODEX 코스닥150·KODEX 200) "
                           "프록시★ — KOSDAQ 은 수집 시리즈가 없고 KOSPI 는 vintage 가 없어 "
                           "가격 경로로 근사한다. 추적오차·보수가 신호에 섞인다.",
     "provenance": "ETF proxy (KODEX 229200 / 069500)", "existing": False},
    {"id": "usdkrw_trend", "label": "원/달러 추세 (달러 ETF 프록시)", "family": "regime",
     "evaluation_frequency": "month",
     "params": {"months": 6, "proxy": "261240"},
     "default_threshold": 0.0, "default_direction": "below",
     "unit": "pct", "desc": "달러선물 ETF 의 N개월 수익률(%). 양수면 달러 강세=원화 약세로, "
                            "국내 주식에는 위험-오프 쪽이라 임계 **아래**가 통과. "
                            "★현물 환율 지수가 아니라 ETF 프록시★ — ECOS 원/달러(731Y001)는 "
                            "vintage 가 없어 forward_only 라서 가격 경로를 쓴다.",
     "provenance": "ETF proxy (KODEX 261240)", "existing": False},
    {"id": "sector_dispersion", "label": "섹터 디스퍼전 (횡단면 표준편차)", "family": "breadth",
     "evaluation_frequency": "day",
     "params": {"days": 20}, "default_threshold": 3.0, "default_direction": "above",
     "unit": "pp", "desc": "국내 섹터 ETF 들의 N일 수익률 횡단면 표준편차(%p). 크면 섹터가 "
                           "제각기 움직여 종목 선택이 통하는 국면, 작으면 다 같이 움직인다. "
                           "★섹터 지수가 아니라 ETF 프록시★ — 이 코드베이스에 섹터 지수 "
                           "시계열이 없어 거래되는 ETF 로 근사하며, 추적오차·보수·유동성이 "
                           "신호에 섞인다. 한 섹터라도 못 읽으면 unavailable(부분 집합으로 낸 "
                           "분산은 다른 수치라 비교할 수 없다).",
     "provenance": "ETF proxy (KODEX/TIGER 섹터)", "existing": False},
]

# ── §3.2 구조화 메타를 덧입힌다 (Phase 12a) ────────────────────────────────────
# 감사(11a·A1)가 잰 것은 `CATALOG_BY_ID` 항목의 **키 합집합**이었다. 그래서 `catalog()`
# 응답에서만 붙이면 감사가 다시 같은 결론을 낸다 — 목록 자체를 채운다.
#
# 소스가 아예 없는 §6.1 묶음도 여기서 합류한다. 켤 수는 없지만 **보이기는 해야** 한다.
CATALOG = [_meta.enrich(c) for c in CATALOG] + _meta.UNAVAILABLE_FACTORS

CATALOG_BY_ID: dict[str, dict] = {c["id"]: c for c in CATALOG}

FAMILY_LABELS = {
    "momentum": "모멘텀 · 추세",
    "deviation": "이격 · 평균회귀",
    "breakout": "돌파",
    "overnight": "오버나이트",
    "regime": "국면 · 매크로",
    # Phase 8 — 기존 5개 패밀리에 들어맞지 않는 팩터군. regime 에 몰아넣으면 그 패밀리가
    # 15개짜리 잡동사니가 되어 필터가 쓸모없어진다.
    "breadth": "브레드스 · 참여도",
    "volatility": "변동성",
    "drawdown": "낙폭 · 회복",
    "correlation": "상관",
}


# 리밸런싱 주기 선택지 — TimingRule.rebalance_or_holding_period 가 받는 값.
# ★모두 frequency_ranks 에 등급이 있어야 한다★ 없는 값을 고르면 충돌 경고가 조용히 꺼진다.
REBALANCE_OPTIONS: tuple[dict[str, str], ...] = (
    {"id": "day", "label": "매일"},
    {"id": "week", "label": "주간"},
    {"id": "month_end", "label": "월말"},
    {"id": "quarter", "label": "분기"},
    {"id": "overnight", "label": "오버나이트(익일 시가 청산)"},
)


def catalog() -> dict:
    """UI(팩터 창)용 카탈로그 — 패밀리별 그룹 + 스키마 메타."""
    # 함수 안에서 import — timing_rules_v2 가 이 모듈을 import 하므로 순환을 피한다.
    from src.engine.timing_rules_v2 import FREQUENCY_RANKS
    groups = []
    for fam in SIGNAL_FAMILIES:
        items = [c for c in CATALOG if c["family"] == fam]
        if items:
            groups.append({"family": fam, "label": FAMILY_LABELS.get(fam, fam), "factors": items})
    return {
        "groups": groups,
        "families": [{"id": f, "label": FAMILY_LABELS.get(f, f)} for f in SIGNAL_FAMILIES],
        "schema": [f.name for f in TimingRule.__dataclass_fields__.values()],
        # 주기 등급표를 그대로 내려보낸다 — UI 가 같은 표를 복제하면 두 진실이 생긴다.
        "frequency_ranks": dict(FREQUENCY_RANKS),
        "rebalance_options": [dict(o) for o in REBALANCE_OPTIONS],
        "note": ("systrader79 계열은 공개 포스팅 기준 구현. 이격도·돌파·오버나이트는 공개된 일반 "
                 "기술 시그널의 파라미터화 구현으로, 특정 유료 컨텐츠의 조건식을 재현한 것이 아닙니다."),
    }


def evaluate(factor_id: str, ticker: str, market: str = "kr",
             params: dict | None = None) -> float | None:
    """팩터 1건의 현재 값 — 실패/데이터 부족은 None(정직). 통과 판정은 호출자가 임계로."""
    p = params or {}
    try:
        if factor_id == "avg_abs_momentum":
            return avg_abs_momentum(ticker, market, int(p.get("max_months", 12)))
        if factor_id == "accel_momentum":
            return accel_momentum(ticker, market)
        if factor_id == "disparity":
            return disparity(ticker, market, int(p.get("ma_days", 20)))
        if factor_id == "vol_breakout":
            return vol_breakout(ticker, market, float(p.get("k", 0.5)))
        if factor_id == "channel_breakout":
            return channel_breakout(ticker, market, int(p.get("days", 20)))
        if factor_id == "overnight_return":
            return overnight_return(ticker, market, int(p.get("days", 20)))
        if factor_id == "defense_first":
            return defense_first(None, market)
        # ── Phase 8 ──
        if factor_id == "relative_momentum":
            return relative_momentum(ticker, market, int(p.get("months", 12)),
                                     str(p.get("benchmark", "AGG")))
        if factor_id == "breadth_above_ma":
            return breadth_above_ma(None, market, int(p.get("days", 200)),
                                    p.get("basket"))
        if factor_id == "equal_vs_cap":
            return equal_vs_cap(None, market, int(p.get("months", 6)),
                                str(p.get("equal", "RSP")), str(p.get("cap", "SPY")))
        if factor_id == "realized_vol":
            return realized_vol(ticker, market, int(p.get("days", 20)))
        if factor_id == "vol_regime":
            return vol_regime(ticker, market, int(p.get("days", 20)),
                              int(p.get("ref_days", 250)))
        if factor_id == "target_vol_size":
            return target_vol_size(ticker, market, int(p.get("days", 20)),
                                   float(p.get("target_vol", 10.0)))
        if factor_id == "drawdown":
            return drawdown(ticker, market, int(p.get("days", 250)))
        if factor_id == "drawdown_speed":
            return drawdown_speed(ticker, market, int(p.get("days", 250)),
                                  int(p.get("window", 20)))
        if factor_id == "recovery_state":
            return recovery_state(ticker, market, int(p.get("days", 250)))
        if factor_id == "rolling_correlation":
            return rolling_correlation(ticker, market, int(p.get("days", 60)),
                                       str(p.get("benchmark", "TLT")))
        if factor_id == "kospi_kosdaq_rs":
            return kospi_kosdaq_rs(None, market, int(p.get("months", 6)),
                                   str(p.get("growth", _KOSDAQ_ETF)),
                                   str(p.get("core", _KOSPI_ETF)))
        if factor_id == "usdkrw_trend":
            return usdkrw_trend(None, market, int(p.get("months", 6)),
                                str(p.get("proxy", _USD_ETF)))
        if factor_id == "sector_dispersion":
            return sector_dispersion(None, market, int(p.get("days", 20)),
                                     p.get("basket"))
        # 기존 프리미티브 위임
        from src.engine.tactical_allocations import (
            _above_ma_d,
            _above_ma_m,
            _abs_mom,
            _score_13612,
        )
        if factor_id == "score_13612":
            return _score_13612(ticker, market)
        if factor_id == "abs_mom":
            return _abs_mom(ticker, market, int(p.get("months", 12)))
        if factor_id == "ma_month":
            v = _above_ma_m(ticker, market, max(int(p.get("months", 10)), 2))
            return None if v is None else (1.0 if v else 0.0)
        if factor_id == "ma_day":
            v = _above_ma_d(ticker, market, max(int(p.get("days", 200)), 5))
            return None if v is None else (1.0 if v else 0.0)
    except Exception as e:
        logger.debug(f"timing factor 평가 실패 [{factor_id}/{ticker}]: {e}")
    return None


def passes(value: float | None, threshold: float, direction: str) -> bool:
    """임계 통과 판정 — 값이 없으면 통과 실패(보수적)."""
    if value is None:
        return False
    return value > threshold if direction == "above" else value < threshold


def rule_from_spec(spec: dict) -> TimingRule:
    """UI/API 스펙(dict) → TimingRule (카탈로그 기본값으로 결측 필드 보강)."""
    fid = str(spec.get("factor_id") or spec.get("id") or "")
    meta = CATALOG_BY_ID.get(fid, {})
    params = dict(meta.get("params") or {})
    params.update(spec.get("params") or {})
    obs = spec.get("observation_window") or {
        k: v for k, v in params.items() if k in ("months", "days", "max_months", "ma_days")}
    return TimingRule(
        factor_id=fid,
        universe=list(spec.get("universe") or []),
        signal_family=spec.get("signal_family") or meta.get("family", "momentum"),
        observation_window=obs,
        entry_condition=spec.get("entry_condition") or "",
        exit_condition=spec.get("exit_condition") or "",
        risk_off_asset=list(spec.get("risk_off_asset") or []),
        rebalance_or_holding_period=spec.get("rebalance_or_holding_period") or "month_end",
        position_sizing=spec.get("position_sizing") or "equal",
        leverage_cap=float(spec.get("leverage_cap", 1.0) or 1.0),
        transaction_cost_and_slippage=dict(
            spec.get("transaction_cost_and_slippage") or {"cost_bps": 10.0, "slippage_bps": 5.0}),
        params=params,
        label=spec.get("label") or meta.get("label", fid),
    )
