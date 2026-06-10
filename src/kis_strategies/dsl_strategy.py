"""
DslStrategy — 빌더 커스텀 전략 런타임 인터프리터
==========================================================================
프론트엔드 Builder에서 만든 BuilderState(지표 + 진입/청산 조건)를
백엔드 run_backtest가 실행할 수 있는 BaseStrategy로 변환한다.

★ 안전 설계 ★
  코드 생성(codegen)이나 exec를 쓰지 않고, 조건 트리를 직접 해석(interpret)한다.
  허용된 지표 함수(kis_indicators)와 연산자만 평가하므로 임의 코드 실행 위험이 없다.

BuilderState 구조 (프론트엔드 types/builder.ts와 동일):
  {
    metadata: { name, ... },
    indicators: [{ alias, indicatorId, params:{period}, output }],
    entry: { logic: "AND"|"OR", conditions: [Condition] },
    exit:  { logic, conditions: [Condition] },
    risk:  { stopLoss, takeProfit, trailingStop }
  }
Condition:
  {
    left:  Operand, operator: str, right: Operand
  }
Operand:
  { type: "indicator", indicatorAlias, indicatorOutput }
  | { type: "value", value }
  | { type: "price", priceField: "close"|"open"|"high"|"low" }
"""

from __future__ import annotations

import logging

import pandas as pd

from src import kis_data_fetcher as data_fetcher
from src import kis_indicators as indicators
from src.kis_signal import Action, Signal
from src.kis_strategies.strategies import BaseStrategy

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 지표 alias → kis_indicators 함수 매핑
# ═══════════════════════════════════════════════════════════════════════════════
# 빌더의 indicatorId를 실제 calc 함수로 연결. period 등 파라미터는 params에서.

def _compute_indicator(df: pd.DataFrame, indicator_id: str, params: dict) -> pd.Series | None:
    """단일 지표 계산. 미지원이면 None."""
    p = params or {}
    period = int(p.get("period", p.get("length", 14)))
    try:
        iid = indicator_id.lower()
        if iid in ("sma", "ma"):
            return indicators.calc_ma(df, period)
        if iid == "ema":
            return indicators.calc_ema(df, period)
        if iid == "rsi":
            return indicators.calc_rsi(df, period)
        if iid == "roc":
            return indicators.calc_roc(df, period)
        if iid == "momentum":
            return indicators.calc_momentum(df, period)
        if iid == "atr":
            return indicators.calc_atr(df, period)
        if iid == "natr":
            return indicators.calc_natr(df, period)
        if iid == "cci":
            return indicators.calc_cci(df, period)
        if iid == "williams_r":
            return indicators.calc_williams_r(df, period)
        if iid == "disparity":
            return indicators.calc_disparity(df, period)
        if iid == "volatility":
            return indicators.calc_volatility(df, period)
        if iid in ("macd",):
            return indicators.calc_macd(df)
        if iid == "macd_signal":
            return indicators.calc_macd_signal(df)
        if iid == "macd_histogram":
            return indicators.calc_macd_histogram(df)
        if iid in ("bb_upper", "bollinger_upper"):
            return indicators.calc_bb_upper(df, period)
        if iid in ("bb_lower", "bollinger_lower"):
            return indicators.calc_bb_lower(df, period)
        if iid in ("bb_middle", "bollinger", "bollinger_middle"):
            return indicators.calc_bb_middle(df, period)
        if iid == "stochastic_k":
            return indicators.calc_stochastic_k(df, period)
        if iid == "stochastic_d":
            return indicators.calc_stochastic_d(df, period)
        if iid == "obv":
            return indicators.calc_obv(df)
        if iid == "mfi":
            return indicators.calc_mfi(df, period)
        if iid == "adx":
            return indicators.calc_adx(df, period)
        if iid == "vwap":
            return indicators.calc_vwap(df)
        if iid == "aroon_up":
            return indicators.calc_aroon_up(df, period)
        if iid == "aroon_down":
            return indicators.calc_aroon_down(df, period)
        if iid == "volume_ma":
            return indicators.calc_volume_ma(df, period)
        if iid == "stochrsi":
            return indicators.calc_stochrsi(df, period)
        # 미지원 지표 → 단순 MA로 폴백 (전략이 깨지지 않도록)
        logger.warning(f"미지원 지표 '{indicator_id}', MA로 폴백")
        return indicators.calc_ma(df, period)
    except Exception as e:
        logger.warning(f"지표 '{indicator_id}' 계산 실패: {e}")
        return None


class DslStrategy(BaseStrategy):
    """
    BuilderState를 해석해 매매 신호를 생성하는 범용 전략.

    Args:
        spec: BuilderState dict (indicators/entry/exit/metadata)
    """

    def __init__(self, spec: dict):
        self.spec = spec or {}
        self._name = (self.spec.get("metadata") or {}).get("name", "커스텀 전략")
        self._indicators = self.spec.get("indicators", []) or []
        self._entry = self.spec.get("entry", {"logic": "AND", "conditions": []})
        self._exit = self.spec.get("exit", {"logic": "AND", "conditions": []})

        # 필요한 데이터 일수: 지표 최대 period + 여유
        max_period = 20
        for ind in self._indicators:
            pr = (ind.get("params") or {}).get("period", 0)
            try:
                max_period = max(max_period, int(pr))
            except (ValueError, TypeError):
                pass
        self._required_days = max_period + 30

        # 펀더멘털 operand 사용 여부 (사용 시에만 스냅샷 조회 → 불필요한 DART 호출 회피)
        self._uses_fundamental = self._spec_uses_fundamental()
        self._fund_snapshot: dict | None = None
        self._fund_cache: dict[str, dict] = {}

    def _spec_uses_fundamental(self) -> bool:
        """진입/청산 조건에 fundamental operand가 있는지 검사."""
        for grp in (self._entry, self._exit):
            for cond in (grp.get("conditions") or []):
                for side in ("left", "right"):
                    if (cond.get(side) or {}).get("type") == "fundamental":
                        return True
        return False

    def _load_fundamental_snapshot(self, stock_code: str) -> dict | None:
        """종목 펀더멘털 스냅샷. 스크리너와 동일한 fundamentals_store 사용.

        이로써 백테스터가 스크리너의 35개 학술 팩터(ROIC/Altman Z/Piotroski F 등)를
        모두 동일하게 사용한다. DART_API_KEY 설정 시 실데이터, 없으면 일관된 mock.
        종목당 1회 조회 후 캐시.
        """
        if stock_code in self._fund_cache:
            return self._fund_cache[stock_code]
        snap: dict = {}
        try:
            from src.data.fundamentals_store import FundamentalsStore
            store = FundamentalsStore.get_default()
            factors = store.get_factors(stock_code, None)
            # 내부 키(_source 등) 제외하고 모두 부착
            snap = {k: v for k, v in factors.items() if not k.startswith("_")}
        except Exception as e:
            logger.warning(f"펀더멘털 스냅샷 실패 [{stock_code}]: {e}")
        # 가격·수급 팩터도 동일 스냅샷에 병합 (모멘텀/변동성/RSI 등 전략 조건 사용 가능)
        try:
            from src.data.price_factors_store import PriceFactorsStore
            pstore = PriceFactorsStore.get_default()
            pfactors = pstore.get_factors(stock_code, None)
            for k, v in pfactors.items():
                if not k.startswith("_"):
                    snap[k] = v
        except Exception as e:
            logger.warning(f"가격 팩터 스냅샷 실패 [{stock_code}]: {e}")
        self._fund_cache[stock_code] = snap
        return snap

    @property
    def name(self) -> str:
        return self._name

    @property
    def required_days(self) -> int:
        return self._required_days

    # ── 피연산자 평가 ────────────────────────────────────────────────────────
    def _eval_operand(self, operand: dict, computed: dict[str, pd.Series],
                      df: pd.DataFrame, idx: int) -> float | None:
        """피연산자를 idx 시점의 스칼라 값으로 평가. idx는 -1(현재) 또는 -2(직전)."""
        otype = operand.get("type")
        if otype == "value":
            try:
                return float(operand.get("value", 0))
            except (ValueError, TypeError):
                return None
        if otype == "price":
            field = operand.get("priceField", "close")
            if field in df.columns and len(df) >= abs(idx):
                return float(df[field].iloc[idx])
            return None
        if otype == "indicator":
            alias = operand.get("indicatorAlias")
            series = computed.get(alias)
            if series is None or len(series) < abs(idx):
                return None
            val = series.iloc[idx]
            return None if pd.isna(val) else float(val)
        if otype == "fundamental":
            # 펀더멘털은 종목당 상수 (시계열 아님) → idx 무관하게 스냅샷 값 반환
            field = operand.get("fundamentalField", "per")
            return self._fundamental_value(field)
        return None

    def _fundamental_value(self, field: str) -> float | None:
        """현재 평가 중인 종목의 펀더멘털 값 (스냅샷, 종목당 1회 조회 후 캐시)."""
        snap = getattr(self, "_fund_snapshot", None)
        if snap is None:
            return None
        return snap.get(field)

    # ── 조건 평가 ────────────────────────────────────────────────────────────
    def _eval_condition(self, cond: dict, computed: dict, df: pd.DataFrame) -> bool:
        op = cond.get("operator", "")
        # 크로스 연산자는 현재(-1)와 직전(-2) 둘 다 필요
        if op in ("cross_above", "cross_below"):
            l_now = self._eval_operand(cond.get("left", {}), computed, df, -1)
            r_now = self._eval_operand(cond.get("right", {}), computed, df, -1)
            l_prev = self._eval_operand(cond.get("left", {}), computed, df, -2)
            r_prev = self._eval_operand(cond.get("right", {}), computed, df, -2)
            if None in (l_now, r_now, l_prev, r_prev):
                return False
            if op == "cross_above":
                return l_prev <= r_prev and l_now > r_now
            else:  # cross_below
                return l_prev >= r_prev and l_now < r_now

        # 일반 비교 연산자
        left = self._eval_operand(cond.get("left", {}), computed, df, -1)
        right = self._eval_operand(cond.get("right", {}), computed, df, -1)
        if left is None or right is None:
            return False
        if op == "greater_than":
            return left > right
        if op == "less_than":
            return left < right
        if op == "greater_equal":
            return left >= right
        if op == "less_equal":
            return left <= right
        if op == "equals":
            return abs(left - right) < 1e-9
        return False

    def _eval_group(self, group: dict, computed: dict, df: pd.DataFrame) -> bool:
        conditions = group.get("conditions", []) or []
        if not conditions:
            return False
        results = [self._eval_condition(c, computed, df) for c in conditions]
        logic = group.get("logic", "AND").upper()
        return all(results) if logic == "AND" else any(results)

    # ── 신호 생성 ────────────────────────────────────────────────────────────
    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < 3:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        # 펀더멘털 조건이 있으면 종목 스냅샷 로드 (없으면 스킵 → 빠름)
        if self._uses_fundamental:
            self._fund_snapshot = self._load_fundamental_snapshot(stock_code)

        # 모든 지표 사전 계산 (alias → series)
        computed: dict[str, pd.Series] = {}
        for ind in self._indicators:
            alias = ind.get("alias")
            if not alias:
                continue
            series = _compute_indicator(df, ind.get("indicatorId", ""), ind.get("params", {}))
            if series is not None:
                computed[alias] = series

        # 진입 → 청산 순으로 평가
        try:
            if self._eval_group(self._entry, computed, df):
                return Signal(stock_code=stock_code, stock_name=stock_name,
                              action=Action.BUY, strength=0.7,
                              reason=f"{self._name} 진입 조건 충족")
            if self._eval_group(self._exit, computed, df):
                return Signal(stock_code=stock_code, stock_name=stock_name,
                              action=Action.SELL, strength=0.7,
                              reason=f"{self._name} 청산 조건 충족")
        except Exception as e:
            logger.warning(f"DslStrategy 평가 오류 [{stock_code}]: {e}")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0, reason="조건 미충족")
