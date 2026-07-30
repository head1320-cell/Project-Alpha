"""마켓타이밍 팩터 카탈로그 + TimingRule 공통 스키마 (AAS TIMING 통합 팩터 창)
==============================================================================
AAS TIMING 탭의 카나리 신호와 백테스터 팩터 창을 하나의 "타이밍 팩터" 개념으로 통합한다.
모든 팩터는 아래 공통 스키마(TimingRule)로 등록되어 UI·API·저장이 동일한 형태를 공유한다.

TimingRule 스키마(사용자 제안 그대로):
  universe · signal_family · observation_window · entry_condition · exit_condition ·
  risk_off_asset · rebalance_or_holding_period · position_sizing · leverage_cap ·
  transaction_cost_and_slippage · point_in_time_data_timestamp

signal_family: momentum | deviation | breakout | overnight | regime

재사용(신규 수학 최소화):
  · tactical_allocations._ret/_abs_mom/_score_13612/_accel/_above_ma_m/_above_ma_d
  · etf_prices.monthly_closes/daily_closes/daily_ohlc (as_of 시점절단 관례 포함)

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

logger = logging.getLogger(__name__)

SIGNAL_FAMILIES = ("momentum", "deviation", "breakout", "overnight", "regime")


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
     "params": {}, "default_threshold": 20.0, "default_direction": "below",
     "unit": "raw", "desc": "VIXCLS·DGS10·T10Y2Y 등 매크로 시리즈의 임계 통과(FRED/ECOS).",
     "provenance": "FRED/ECOS", "existing": True},
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
]

CATALOG_BY_ID: dict[str, dict] = {c["id"]: c for c in CATALOG}

FAMILY_LABELS = {
    "momentum": "모멘텀 · 추세",
    "deviation": "이격 · 평균회귀",
    "breakout": "돌파",
    "overnight": "오버나이트",
    "regime": "국면 · 매크로",
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
