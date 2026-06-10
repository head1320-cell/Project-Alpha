"""
Pure-Python Backtest Engine
=============================
KIS backtester의 Lean/Docker 의존성을 제거하고,
우리 DB(daily_prices)에서 데이터를 읽는 순수 Python 시뮬레이션으로 대체.

ResultFormatter 출력 구조와 동일한 JSON을 반환하므로
기존 tear sheet UI와 완전 호환됩니다.

지원 기능:
  - 10개 KIS 전략 모두 지원 (날짜별 as-of 시뮬레이션)
  - 수수료 / 슬리피지 / 손절(stop-loss) / 익절(take-profit)
  - 다중 종목 포트폴리오
  - Sharpe, Sortino, Calmar, Max DD, Win Rate, Profit Factor
  - 월별 수익률 히트맵 / Drawdown 곡선 / Trade log
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DB Data Provider (as-of 날짜 지원)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_sync_engine():
    """
    테스트 시 monkey-patch 가능하도록 모듈 레벨 변수 사용.
    engine_override가 설정되어 있으면 그것을 사용.
    """
    if _engine_override is not None:
        return _engine_override
    try:
        from src.database import get_engine
        return get_engine()
    except Exception:
        return None


# 테스트/주입용 override
_engine_override = None


def set_engine(engine):
    """테스트 또는 의존성 주입 시 엔진을 직접 설정."""
    global _engine_override
    _engine_override = engine


def load_ohlcv(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    DB에서 OHLCV 로드 (백테스트용 — 전체 기간 한 번에).

    Returns:
        DataFrame: date(index), open, high, low, close, volume
    """
    engine = _get_sync_engine()
    if engine is None:
        return pd.DataFrame()

    code = ticker.replace(".KS", "").replace(".KQ", "")
    sql = text("""
        SELECT trade_date, "open", high, low, close, volume
        FROM daily_prices
        WHERE ticker = :ticker
          AND trade_date BETWEEN :start AND :end
        ORDER BY trade_date ASC
    """)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {
                "ticker": code,
                "start": start_date,
                "end": end_date,
            }).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["close"])

    except Exception as e:
        logger.error(f"load_ohlcv error ({ticker}): {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Position & Portfolio
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    ticker: str
    quantity: int
    avg_price: float
    entry_date: str
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    sell_count: int = 0          # 분할 매도 횟수 (max_sell_divisions 제한용)
    buy_count: int = 1           # 분할 매수 횟수 (Phase 3)
    peak_price: float = 0.0      # 보유 중 최고가(종가 기준) — 트레일링 스탑용


@dataclass
class Trade:
    date: str
    ticker: str
    side: str           # "buy" | "sell"
    price: float
    quantity: int
    value: float
    commission: float
    slippage: float
    pnl: float | None = None
    reason: str = ""


@dataclass
class BacktestConfig:
    symbols: list[str]
    strategy_name: str
    strategy_params: dict
    start_date: str
    end_date: str
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015     # 0.15% 수수료
    slippage_rate: float = 0.0005       # 0.05% 슬리피지
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None  # 트레일링 스탑: 보유 중 고점 대비 하락 % (None=미사용)
    position_size_pct: float = 0.95     # 포지션 크기 (자본 대비)
    max_positions: int = 5              # 동시 최대 포지션 수
    # 체결가 유형 (Phase 0: 주문 모델). 기본 "close" = 기존 동작 불변
    buy_fill_type: str = "close"        # 매수 체결가 유형
    sell_fill_type: str = "close"       # 매도 체결가 유형
    # 매도 정밀화 (Phase 2). 모두 기본 비활성 = 기존 동작 불변
    max_hold_days: int | None = None    # 보유기간 매도: N일 경과 시 강제 청산
    min_hold_days: int = 0              # 최소 보유: N일 전엔 손익절·신호 매도 보류
    sell_divide_pct: float = 100.0      # 분할 매도 비중 % (100=전량, 50=절반씩)
    max_sell_divisions: int | None = None  # 분할 매도 최대 횟수 (None=무제한, 도달 시 전량청산)
    # 매수 정밀화 (Phase 3). 기본값 = 기존 동작 불변
    buy_weight_mode: str = "equal"      # 매수 비중: equal(동일가중) | factor(팩터가중)
    buy_divide_pct: float = 100.0       # 분할 매수 비중 % (100=한번에, 50=절반씩 추가매수)
    max_buy_per_day: int | None = None  # 일일 최대 신규 매수 종목 수
    max_buy_count: int | None = None    # 종목당 최대 분할 매수 횟수
    factor_weights: dict | None = None  # 종목별 팩터 가중치 {ticker: 0~1} (팩터가중 모드용)
    # 정기 리밸런싱 + 마켓타이밍 (GENPORT_GAP ②). 기본 비활성 = 기존 동작 불변
    rebalance_period: str | None = None  # None·"daily"=매일 | "weekly"·"monthly"=주·월 첫 거래일에만 신규 매수
    market_timing: dict | None = None    # {"index_ticker","action"("block_buy"|"exit_all"),"conditions":[조건식]}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Core Simulation Loop
# ═══════════════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    순수 Python 백테스트 시뮬레이션 엔진.

    KIS backtester의 Lean 루프와 동일한 로직을
    pandas + our DB 기반으로 재구현합니다.
    """

    def __init__(self, config: BacktestConfig):
        self.cfg = config
        self.cash = config.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_history: list[tuple] = []   # (date_str, equity)

    def run(self) -> dict:
        """
        메인 시뮬레이션 루프.

        Returns:
            ResultFormatter.to_api_response()와 동일한 구조의 dict
        """
        started_at = datetime.now()

        # 전략 로드
        from src.kis_strategies.strategies import get_strategy
        strategy = get_strategy(self.cfg.strategy_name, **self.cfg.strategy_params)
        if strategy is None:
            return self._error_response(f"Unknown strategy: {self.cfg.strategy_name}")

        # 종목별 OHLCV 전체 로드 (DB에서 한 번만 읽음)
        warmup_start = (
            datetime.strptime(self.cfg.start_date, "%Y-%m-%d")
            - timedelta(days=strategy.required_days + 30)
        ).strftime("%Y-%m-%d")

        ohlcv_map: dict[str, pd.DataFrame] = {}
        for ticker in self.cfg.symbols:
            # 통합 로더: DB → KIS 실시간 → mock 자동 선택
            try:
                from src.data.ohlcv_loader import load_ohlcv_unified
                df = load_ohlcv_unified(ticker, warmup_start, self.cfg.end_date, prefer="auto")
            except Exception:
                df = load_ohlcv(ticker, warmup_start, self.cfg.end_date)
            if not df.empty:
                # ★ 최적화: 날짜 문자열을 여기서 1회만 생성 (매 거래일 strftime 제거)
                #   기존엔 _generate_signal_as_of가 슬라이스마다 dt.strftime 호출 → O(N²) 병목
                df = df.copy()
                df["_date_str"] = df.index.strftime("%Y%m%d")
                ohlcv_map[ticker] = df

        if not ohlcv_map:
            return self._error_response("No OHLCV data found in DB for given tickers/range")

        # 거래일 목록 (가장 많은 데이터를 가진 종목 기준)
        ref_ticker = max(ohlcv_map, key=lambda t: len(ohlcv_map[t]))
        all_dates = ohlcv_map[ref_ticker].index
        sim_dates = all_dates[all_dates >= pd.Timestamp(self.cfg.start_date)]

        # 횡단면(순위/비율) 전략용 패널 사전계산 — 전 종목 동일시점 값이 필요한 함수 지원
        if hasattr(strategy, "prepare_panel"):
            try:
                strategy.prepare_panel(ohlcv_map)
            except Exception as e:
                logger.debug(f"prepare_panel skipped: {e}")

        logger.info(
            f"Backtest: {self.cfg.strategy_name} | "
            f"{self.cfg.symbols} | {len(sim_dates)} trading days"
        )

        # 정기 리밸런싱(신규 매수일 게이트) + 마켓타이밍(지수 조건 포트폴리오 게이트)
        rebalance_days = self._rebalance_days(sim_dates)
        mt_df = self._load_market_timing_index(warmup_start) if self.cfg.market_timing else None
        mt_action = str((self.cfg.market_timing or {}).get("action") or "block_buy")

        # Day-by-day 시뮬레이션
        for sim_date in sim_dates:
            date_str = sim_date.strftime("%Y-%m-%d")
            self._buys_today = 0  # 일일 신규 매수 카운터 (max_buy_per_day 제한용)

            # 0. 마켓타이밍: 지수 조건 미충족(OFF) → 신규 매수 차단, exit_all이면 전량 청산
            #    (포트폴리오 레벨 리스크오프 — min_hold_days보다 우선)
            market_on = self._market_timing_on(mt_df, sim_date) if mt_df is not None else True
            if not market_on and mt_action == "exit_all" and self.positions:
                for ticker, _pos in list(self.positions.items()):
                    if ticker not in ohlcv_map:
                        continue
                    df_to_date = ohlcv_map[ticker].loc[:sim_date]
                    if df_to_date.empty:
                        continue
                    self._execute_sell(ticker, float(df_to_date["close"].iloc[-1]),
                                       date_str, "Market-timing exit")

            # 1. 포지션 가격 업데이트 + 손절/익절 + 보유기간 매도 체크
            for ticker, pos in list(self.positions.items()):
                if ticker not in ohlcv_map:
                    continue
                df_to_date = ohlcv_map[ticker].loc[:sim_date]
                if df_to_date.empty:
                    continue
                curr_price = float(df_to_date["close"].iloc[-1])
                days_held = self._days_held(pos.entry_date, date_str)

                # 트레일링 스탑용 고점 추적 — 손익절과 동일하게 종가 기준 (min_hold 중에도 추적)
                if self.cfg.trailing_stop_pct:
                    pos.peak_price = max(pos.peak_price, curr_price)

                # 보유기간 매도: max_hold_days 경과 시 강제 청산 (분할 비중 적용)
                if self.cfg.max_hold_days is not None and days_held >= self.cfg.max_hold_days:
                    self._execute_sell(ticker, curr_price, date_str,
                                       f"보유기간 {self.cfg.max_hold_days}일 경과",
                                       sell_fraction=self.cfg.sell_divide_pct / 100.0)
                    continue
                # 손절/익절: 최소 보유기간 이후에만 (min_hold_days)
                if days_held >= self.cfg.min_hold_days:
                    self._check_risk_triggers(ticker, pos, curr_price, date_str)

            # 2. 전략 신호 생성 (각 종목별)
            for ticker in self.cfg.symbols:
                if ticker not in ohlcv_map:
                    continue

                # as-of 슬라이스 (미래 데이터 차단 — look-ahead bias 방지)
                df_slice = ohlcv_map[ticker].loc[:sim_date]
                if len(df_slice) < strategy.required_days:
                    continue

                # 전략 실행을 위해 data_fetcher를 일시적으로 slice로 패치
                signal = self._generate_signal_as_of(
                    strategy, ticker, df_slice
                )
                if signal is None:
                    continue

                # 체결가: 유형별 계산 (기본 "close" = 종가, 기존 동작 불변)
                from src.engine.fill_price import resolve_from_slice
                from src.kis_signal import Action
                close_price = float(df_slice["close"].iloc[-1])

                if signal.action == Action.BUY and signal.is_actionable():
                    # 신규 매수 게이트: 마켓타이밍 ON + (리밸런싱 미사용 또는 리밸런싱일)
                    if market_on and (rebalance_days is None or sim_date in rebalance_days):
                        buy_price = resolve_from_slice(self.cfg.buy_fill_type, df_slice)
                        fw = (self.cfg.factor_weights or {}).get(ticker)
                        natr = self._natr_pct(df_slice) if self.cfg.buy_weight_mode == "atr" else None
                        self._execute_buy(ticker, buy_price or close_price, date_str, signal.reason,
                                          factor_weight=fw, atr_pct=natr)
                elif signal.action == Action.SELL and signal.is_actionable():
                    # 최소 보유기간 미달 시 신호 매도 보류
                    pos = self.positions.get(ticker)
                    if pos is not None:
                        days_held = self._days_held(pos.entry_date, date_str)
                        if days_held < self.cfg.min_hold_days:
                            continue
                    sell_price = resolve_from_slice(self.cfg.sell_fill_type, df_slice)
                    self._execute_sell(ticker, sell_price or close_price, date_str, signal.reason,
                                       sell_fraction=self.cfg.sell_divide_pct / 100.0)

            # 3. 포트폴리오 가치 기록
            equity = self._calc_equity(ohlcv_map, sim_date)
            self.equity_history.append((date_str, equity))

        duration = (datetime.now() - started_at).total_seconds()
        return self._build_result(duration, ohlcv_map)

    def _generate_signal_as_of(self, strategy, ticker: str, df_slice: pd.DataFrame):
        """
        특정 날짜 시점의 슬라이스 DataFrame을 이용해 신호 생성.
        data_fetcher 함수를 monkey-patch하여 look-ahead bias 방지.

        ★ 최적화: 날짜 문자열(_date_str)은 run()에서 사전 생성됨.
          매 호출 dt.strftime/copy 제거 → 슬라이스에서 컬럼만 재구성.
        """
        import src.kis_data_fetcher as fetcher
        original_fn = fetcher.get_daily_prices
        original_cp = fetcher.get_current_price

        # 사전 생성된 _date_str 사용 (strftime 재호출 없음).
        # rename으로 date 컬럼 구성 — copy 없이 뷰 기반 경량 DataFrame.
        df_copy = pd.DataFrame({
            "date": df_slice["_date_str"].values,
            "open": df_slice["open"].values,
            "high": df_slice["high"].values,
            "low": df_slice["low"].values,
            "close": df_slice["close"].values,
            "volume": df_slice["volume"].values,
        })

        # 마지막 종가 기반 현재가 정보
        last = df_copy.iloc[-1]
        price_info = {
            "price": int(last["close"]),
            "change": 0, "change_rate": 0.0,
            "high": int(last["high"]), "low": int(last["low"]),
            "volume": int(last["volume"]),
            "w52_high": int(df_copy["high"].tail(252).max()),
            "w52_low": int(df_copy["low"].tail(252).min()),
        }

        try:
            fetcher.get_daily_prices = lambda *a, **kw: df_copy
            fetcher.get_current_price = lambda *a, **kw: price_info
            return strategy.generate_signal(ticker, ticker)
        except Exception as e:
            logger.debug(f"Signal error {ticker}: {e}")
            return None
        finally:
            fetcher.get_daily_prices = original_fn
            fetcher.get_current_price = original_cp

    def _initial_alloc(self, factor_weight: float | None = None,
                       atr_pct: float | None = None) -> float:
        """최초 진입 배분액 계산 (비중 조절 모드 반영).

        · equal(동일가중): 잔여 슬롯에 균등 배분 (기존 동작)
        · factor(팩터가중): factor_weight 비율로 배분 (0~1, 높을수록 큰 비중)
        · atr(역변동성): NATR(ATR14/종가) 2% 기준 배수 — 저변동 종목에 더 큰 비중
        """
        slots = max(self.cfg.max_positions - len(self.positions), 1)
        base = self.cash * self.cfg.position_size_pct / slots
        if self.cfg.buy_weight_mode == "factor" and factor_weight is not None:
            # 팩터가중: 가중치를 동일가중 대비 배수로 (0.5~1.5 범위로 정규화)
            mult = 0.5 + max(0.0, min(1.0, factor_weight))
            base *= mult
        elif self.cfg.buy_weight_mode == "atr" and atr_pct:
            # ATR 비중: 기준 NATR 2% 대비 역비례 배수 (0.5~1.5 클램프) — 변동성 패리티 근사
            base *= max(0.5, min(1.5, 2.0 / atr_pct))
        return min(base, self.cash * 0.95)

    def _natr_pct(self, df_slice) -> float | None:
        """NATR = ATR(14)/종가 ×100 — ATR 비중 사이징용. 데이터 부족 시 None(동일가중 폴백)."""
        try:
            from src.kis_indicators import calc_atr
            if df_slice is None or len(df_slice) < 15:
                return None
            atr_val = float(calc_atr(df_slice, 14).iloc[-1])
            close = float(df_slice["close"].iloc[-1])
            if not (atr_val > 0 and close > 0):
                return None
            return atr_val / close * 100.0
        except Exception:
            return None

    def _execute_buy(self, ticker: str, price: float, date_str: str, reason: str,
                     factor_weight: float | None = None, atr_pct: float | None = None):
        """매수 집행 — 신규 매수 + 분할 매수(add-on) 지원 (Phase 3).

        · 신규: max_positions 한도 + 일일 max_buy_per_day 제한 + 비중 조절
        · 분할매수: 이미 보유 중이면 max_buy_count까지 buy_divide_pct만큼 추가
        · factor_weight: 팩터가중 모드일 때 종목 가중치 (None이면 동일가중)
        · atr_pct: ATR 비중 모드일 때 NATR% (None이면 동일가중 폴백)
        """
        existing = self.positions.get(ticker)

        # 분할 매수(add-on): 이미 보유 중
        if existing is not None:
            max_bc = self.cfg.max_buy_count
            if max_bc is None or self.cfg.buy_divide_pct >= 100.0:
                return  # 분할매수 미설정 → 기존 동작(중복 매수 스킵)
            if existing.buy_count >= max_bc:
                return
            add_alloc = self._initial_alloc(factor_weight, atr_pct) * (self.cfg.buy_divide_pct / 100.0)
            add_alloc = min(add_alloc, self.cash * 0.95)
            exec_price = price * (1 + self.cfg.slippage_rate)
            if add_alloc < exec_price:
                return
            qty = int(add_alloc / exec_price)
            if qty <= 0:
                return
            value = qty * exec_price
            commission = value * self.cfg.commission_rate
            if value + commission > self.cash:
                return
            self.cash -= (value + commission)
            new_qty = existing.quantity + qty
            existing.avg_price = (existing.avg_price * existing.quantity + exec_price * qty) / new_qty
            existing.quantity = new_qty
            existing.buy_count += 1
            existing.peak_price = max(existing.peak_price, exec_price)
            self.trades.append(Trade(
                date=date_str, ticker=ticker, side="buy",
                price=exec_price, quantity=qty, value=value,
                commission=commission, slippage=value * self.cfg.slippage_rate,
                reason=f"{reason} (분할매수 {existing.buy_count}차)",
            ))
            return

        # 신규 매수
        if len(self.positions) >= self.cfg.max_positions:
            return
        if self.cfg.max_buy_per_day is not None and getattr(self, "_buys_today", 0) >= self.cfg.max_buy_per_day:
            return

        alloc = self._initial_alloc(factor_weight, atr_pct)
        if self.cfg.buy_divide_pct < 100.0:
            alloc *= (self.cfg.buy_divide_pct / 100.0)
        alloc = min(alloc, self.cash * 0.95)
        if alloc < price:
            return

        exec_price = price * (1 + self.cfg.slippage_rate)
        quantity = int(alloc / exec_price)
        if quantity <= 0:
            return

        value = quantity * exec_price
        commission = value * self.cfg.commission_rate
        total_cost = value + commission

        if total_cost > self.cash:
            quantity = int((self.cash * 0.95) / (exec_price * (1 + self.cfg.commission_rate)))
            if quantity <= 0:
                return
            value = quantity * exec_price
            commission = value * self.cfg.commission_rate
            total_cost = value + commission

        self.cash -= total_cost
        self._buys_today = getattr(self, "_buys_today", 0) + 1

        stop_price = exec_price * (1 - self.cfg.stop_loss_pct / 100) \
            if self.cfg.stop_loss_pct else None
        tp_price = exec_price * (1 + self.cfg.take_profit_pct / 100) \
            if self.cfg.take_profit_pct else None

        self.positions[ticker] = Position(
            ticker=ticker,
            quantity=quantity,
            avg_price=exec_price,
            entry_date=date_str,
            stop_loss_price=stop_price,
            take_profit_price=tp_price,
            peak_price=exec_price,
        )
        self.trades.append(Trade(
            date=date_str, ticker=ticker, side="buy",
            price=exec_price, quantity=quantity, value=value,
            commission=commission, slippage=value * self.cfg.slippage_rate,
            reason=reason,
        ))

    def _execute_sell(self, ticker: str, price: float, date_str: str, reason: str,
                      sell_fraction: float = 1.0):
        """매도 집행. sell_fraction<1.0이면 분할 매도 (보유 수량의 일부만).

        max_sell_divisions 도달 시 잔량 전량 청산 (무한 분할 방지).
        """
        pos = self.positions.get(ticker)
        if pos is None:
            return

        # 분할 매도: 보유 수량의 일부만 매도 (최소 1주, 최대 전량)
        frac = max(0.0, min(1.0, sell_fraction))
        # 분할 횟수 제한: 마지막 분할이면 전량 청산
        is_last_division = (
            self.cfg.max_sell_divisions is not None
            and pos.sell_count + 1 >= self.cfg.max_sell_divisions
        )
        if frac >= 1.0 or is_last_division:
            sell_qty = pos.quantity
            full_exit = True
        else:
            sell_qty = max(1, int(pos.quantity * frac))
            if sell_qty >= pos.quantity:
                sell_qty = pos.quantity
                full_exit = True
            else:
                full_exit = False

        exec_price = price * (1 - self.cfg.slippage_rate)
        value = sell_qty * exec_price
        commission = value * self.cfg.commission_rate
        proceeds = value - commission
        pnl = proceeds - (sell_qty * pos.avg_price) - commission

        self.cash += proceeds
        if full_exit:
            del self.positions[ticker]
        else:
            # 부분 매도: 잔여 수량 유지 (평단가·진입일 불변), 분할 횟수 증가
            pos.quantity -= sell_qty
            pos.sell_count += 1

        self.trades.append(Trade(
            date=date_str, ticker=ticker, side="sell",
            price=exec_price, quantity=sell_qty, value=value,
            commission=commission, slippage=value * self.cfg.slippage_rate,
            pnl=pnl, reason=reason,
        ))

    def _compute_benchmark(self, dates: list, equity_values: list, strat_returns) -> dict:
        """벤치마크(코스피) 대비 지표. 동일 기간 매수후보유 곡선 + 초과수익/베타/알파.

        코스피 지수 OHLCV를 로드해 초기자본으로 매수후보유한 곡선을 만든다.
        지수 데이터 없으면 대형주(삼성전자)로 폴백, 그것도 없으면 빈 dict.
        mock 환경에선 합성 곡선 — 실데이터(KIS 지수 API)는 GCP에서 자동.
        """
        import numpy as np
        if not dates or len(dates) < 2:
            return {}
        # 코스피 지수 시도 → 대형주 폴백
        bench_df = None
        bench_label = "benchmark"
        proxy_labels = {"KOSPI": "KOSPI", "^KS11": "KOSPI", "005930": "삼성전자(프록시)"}
        for proxy in ("KOSPI", "^KS11", "005930"):
            try:
                from src.data.ohlcv_loader import load_ohlcv_unified
                df = load_ohlcv_unified(proxy, dates[0], dates[-1], prefer="auto")
            except Exception:
                df = load_ohlcv(proxy, dates[0], dates[-1])
            if df is not None and not df.empty:
                bench_df = df
                bench_label = proxy_labels.get(proxy, proxy)
                break
        if bench_df is None:
            return {}

        # 전략 날짜에 맞춰 종가 정렬 (forward-fill)
        bench_df = bench_df.copy()
        bench_close = bench_df["close"].reindex(
            pd.to_datetime(dates), method="ffill"
        ).bfill()
        if bench_close.isna().all():
            return {}

        base = float(bench_close.iloc[0])
        if base <= 0:
            return {}
        # 초기자본으로 매수후보유한 곡선
        bench_curve = [round(self.cfg.initial_capital * (float(c) / base), 0)
                       for c in bench_close.values]
        bench_returns = pd.Series(bench_close.values).pct_change().dropna()

        # 초과수익 (전략 총수익 - 벤치마크 총수익)
        strat_total = (equity_values[-1] / equity_values[0] - 1) * 100 if equity_values[0] else 0
        bench_total = (bench_curve[-1] / bench_curve[0] - 1) * 100 if bench_curve[0] else 0
        excess = strat_total - bench_total

        # 베타·알파 (전략 vs 벤치마크 일별 수익률 회귀)
        beta, alpha = 0.0, 0.0
        try:
            sr = np.array(strat_returns.values, dtype=float)
            br = np.array(bench_returns.values, dtype=float)
            n = min(len(sr), len(br))
            if n >= 5:
                sr, br = sr[-n:], br[-n:]
                var_b = float(np.var(br))
                if var_b > 0:
                    beta = float(np.cov(sr, br)[0][1] / var_b)
                    # 알파(연율화, %): 전략평균 - 베타×벤치평균, 252거래일 기준
                    alpha = float((np.mean(sr) - beta * np.mean(br)) * 252 * 100)
        except Exception:
            pass

        return {
            "label": bench_label,
            "curve": bench_curve,
            "total_return_pct": round(bench_total, 2),
            "excess_return_pct": round(excess, 2),
            "beta": round(beta, 3),
            "alpha_pct": round(alpha, 2),
        }

    def _days_held(self, entry_date: str, current_date: str) -> int:
        """진입일로부터 경과 일수 (캘린더 기준)."""
        from datetime import datetime
        try:
            d0 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
            d1 = datetime.strptime(current_date[:10], "%Y-%m-%d")
            return (d1 - d0).days
        except Exception:
            return 0

    def _rebalance_days(self, sim_dates) -> set | None:
        """정기 리밸런싱: 주/월 첫 거래일 집합. None이면 게이트 없음(매일 신규 매수 가능)."""
        period = (self.cfg.rebalance_period or "").lower()
        if period not in ("weekly", "monthly"):
            return None
        days: set = set()
        seen: set = set()
        for d in sim_dates:
            iso = d.isocalendar()
            key = (iso[0], iso[1]) if period == "weekly" else (d.year, d.month)
            if key not in seen:
                seen.add(key)
                days.add(d)
        return days

    def _load_market_timing_index(self, warmup_start: str):
        """마켓타이밍 지수 OHLCV 로드 (벤치마크와 동일 경로). 실패 시 None → 개입 안 함."""
        ticker = str((self.cfg.market_timing or {}).get("index_ticker") or "KOSPI")
        try:
            from src.data.ohlcv_loader import load_ohlcv_unified
            df = load_ohlcv_unified(ticker, warmup_start, self.cfg.end_date, prefer="auto")
        except Exception:
            df = load_ohlcv(ticker, warmup_start, self.cfg.end_date)
        if df is None or df.empty:
            logger.warning(f"마켓타이밍 지수({ticker}) 데이터 없음 — 게이트 비활성(fail-open)")
            return None
        return df

    def _market_timing_on(self, idx_df, sim_date) -> bool:
        """지수 조건 전부 충족 시 ON. 평가 불가·데이터 부족이면 ON(fail-open — 개입 안 함).

        조건식은 ConditionStrategy와 동일 모델(가격·거래량 토큰 + 18함수)을 지수 봉에 적용.
        예: {종가} ams(20) >= 50 (평균모멘텀스코어), {종가} pct(20) >= 0 (20일 수익률).
        """
        if idx_df is None:
            return True
        conds = (self.cfg.market_timing or {}).get("conditions") or []
        if not conds:
            return True
        sl = idx_df.loc[:sim_date]
        if sl.empty:
            return True
        from src.kis_strategies.condition_strategy import _eval_condition
        evals = [r for r in (_eval_condition(sl, c) for c in conds) if r is not None]
        if not evals:
            return True
        return all(evals)

    def _check_risk_triggers(self, ticker: str, pos: Position,
                              curr_price: float, date_str: str):
        """손절/익절/트레일링 트리거 체크."""
        if pos.stop_loss_price and curr_price <= pos.stop_loss_price:
            self._execute_sell(ticker, curr_price, date_str, "Stop-loss triggered")
        elif pos.take_profit_price and curr_price >= pos.take_profit_price:
            self._execute_sell(ticker, curr_price, date_str, "Take-profit triggered")
        elif (self.cfg.trailing_stop_pct and pos.peak_price > 0
              and curr_price <= pos.peak_price * (1 - self.cfg.trailing_stop_pct / 100.0)):
            self._execute_sell(ticker, curr_price, date_str, "Trailing-stop triggered")

    def _calc_equity(self, ohlcv_map: dict, sim_date: pd.Timestamp) -> float:
        """현재 포트폴리오 가치 계산."""
        equity = self.cash
        for ticker, pos in self.positions.items():
            if ticker in ohlcv_map:
                df_to = ohlcv_map[ticker].loc[:sim_date]
                if not df_to.empty:
                    equity += pos.quantity * float(df_to["close"].iloc[-1])
        return equity

    def _build_result(self, duration: float, ohlcv_map: dict) -> dict:
        """ResultFormatter.to_api_response()와 동일한 구조 반환."""
        if not self.equity_history:
            return self._error_response("No simulation data produced")

        dates = [e[0] for e in self.equity_history]
        equity_values = [e[1] for e in self.equity_history]

        eq_series = pd.Series(equity_values, index=pd.to_datetime(dates))
        returns = eq_series.pct_change().dropna()

        stats = _compute_statistics(
            eq_series, returns, self.trades, self.cfg.initial_capital
        )
        drawdown = _compute_drawdown(eq_series)
        monthly_returns = _compute_monthly_returns(returns)
        trade_dicts = [self._trade_to_dict(t) for t in self.trades]
        symbol_results = _compute_symbol_results(self.trades, self.cfg.symbols)
        # 벤치마크(코스피) 대비 — 동일 기간 매수후보유 곡선 + 초과수익/베타/알파
        benchmark = self._compute_benchmark(dates, equity_values, returns)

        return {
            "currency": "KRW",
            "result": {
                "id": f"bt_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "ran_at": datetime.now().isoformat(),
                "duration_seconds": round(duration, 2),
                "statistics": stats,
                "equity_curve": [round(v, 0) for v in equity_values],
                "equity_dates": dates,
                "drawdown_curve": [round(v, 4) for v in drawdown.values],
                "monthly_returns": monthly_returns,
                "benchmark": benchmark,
                "trades": trade_dicts[:500],
                "symbol_results": symbol_results,
                "charts": {
                    "equity": {
                        "type": "equity",
                        "title": "자산 추이",
                        "labels": dates,
                        "datasets": [{
                            "label": "자산",
                            "data": [round(v, 0) for v in equity_values],
                            "color": "#1b2a4a",
                            "type": "line",
                        }],
                    },
                    "drawdown": {
                        "type": "drawdown",
                        "title": "낙폭",
                        "labels": dates,
                        "datasets": [{
                            "label": "낙폭",
                            "data": [round(v * 100, 2) for v in drawdown.values],
                            "color": "#8b0000",
                            "type": "line",
                        }],
                    },
                },
            },
            "data_range": {
                "start": self.cfg.start_date,
                "end": self.cfg.end_date,
                "symbols_used": len(self.cfg.symbols),
            },
            "cost_analysis": {
                "total_trades": stats["num_trades"],
                "total_commission": stats["total_commission"],
                "total_slippage": stats["total_slippage"],
                "total_cost": stats["total_commission"] + stats["total_slippage"],
            },
        }

    def _trade_to_dict(self, t: Trade) -> dict:
        return {
            "date": t.date,
            "ticker": t.ticker,
            "side": t.side,
            "price": round(t.price, 2),
            "quantity": t.quantity,
            "value": round(t.value, 0),
            "commission": round(t.commission, 0),
            "slippage": round(t.slippage, 0),
            "pnl": round(t.pnl, 0) if t.pnl is not None else None,
            "reason": t.reason,
        }

    def _error_response(self, msg: str) -> dict:
        return {
            "error": True,
            "message": msg,
            "result": {
                "statistics": {k: 0 for k in [
                    "total_return", "total_return_pct", "cagr",
                    "sharpe_ratio", "sortino_ratio", "max_drawdown",
                    "max_drawdown_pct", "num_trades", "win_rate",
                    "profit_factor", "total_commission", "total_slippage",
                ]},
                "equity_curve": [], "equity_dates": [],
                "drawdown_curve": [], "trades": [], "symbol_results": [],
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Performance Metrics
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_statistics(
    equity: pd.Series,
    returns: pd.Series,
    trades: list[Trade],
    initial_capital: float,
    risk_free_rate: float = 0.035,
) -> dict:
    """KIS ResultFormatter._convert_statistics()와 동일한 키 구조."""
    final_equity = float(equity.iloc[-1])
    total_return = final_equity - initial_capital
    total_return_pct = total_return / initial_capital

    # CAGR
    n_years = len(equity) / 252
    cagr = ((final_equity / initial_capital) ** (1 / max(n_years, 0.01)) - 1) \
        if n_years > 0 else 0.0

    # Sharpe
    annual_ret = returns.mean() * 252
    annual_std = returns.std() * math.sqrt(252)
    sharpe = (annual_ret - risk_free_rate) / annual_std if annual_std > 0 else 0.0

    # Sortino
    downside = returns[returns < 0].std() * math.sqrt(252)
    sortino = (annual_ret - risk_free_rate) / downside if downside > 0 else 0.0

    # Max Drawdown
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = float(drawdown.min())  # negative number

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0

    # Trade stats (round-trip matching)
    sell_trades = [t for t in trades if t.side == "sell" and t.pnl is not None]
    n_trades = len(sell_trades)
    wins = [t for t in sell_trades if (t.pnl or 0) > 0]
    losses = [t for t in sell_trades if (t.pnl or 0) <= 0]
    win_rate = len(wins) / n_trades if n_trades > 0 else 0.0
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 0.0
    profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) \
        if losses and avg_loss > 0 else (float("inf") if wins else 0.0)

    total_commission = sum(t.commission for t in trades)
    total_slippage = sum(t.slippage for t in trades)

    return {
        "total_return": round(total_return, 0),
        "total_return_pct": round(total_return_pct * 100, 2),
        "cagr": round(cagr * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "calmar_ratio": round(calmar, 3),
        "max_drawdown": round(max_dd * initial_capital, 0),
        "max_drawdown_pct": round(abs(max_dd) * 100, 2),
        "num_trades": n_trades,
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 3),
        "avg_trade_return": round(
            (total_return_pct / n_trades * 100) if n_trades > 0 else 0, 4
        ),
        "total_commission": round(total_commission, 0),
        "total_slippage": round(total_slippage, 0),
    }


def _compute_drawdown(equity: pd.Series) -> pd.Series:
    rolling_max = equity.cummax()
    return (equity - rolling_max) / rolling_max


def _compute_monthly_returns(daily_returns: pd.Series) -> list[dict]:
    """월별 수익률 히트맵 데이터."""
    if daily_returns.empty:
        return []
    monthly = daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    result = []
    for dt, ret in monthly.items():
        result.append({
            "year": dt.year,
            "month": dt.month,
            "return_pct": round(float(ret) * 100, 2),
        })
    return result


def _compute_symbol_results(trades: list[Trade], symbols: list[str]) -> list[dict]:
    """KIS ResultFormatter._calculate_symbol_results()와 동일 로직."""
    data: dict[str, dict] = {
        s: {"ticker": s, "buy_amount": 0.0, "sell_pnl": 0.0,
            "num_trades": 0, "wins": 0, "losses": 0}
        for s in symbols
    }
    for t in trades:
        if t.ticker not in data:
            data[t.ticker] = {"ticker": t.ticker, "buy_amount": 0.0,
                               "sell_pnl": 0.0, "num_trades": 0,
                               "wins": 0, "losses": 0}
        d = data[t.ticker]
        d["num_trades"] += 1
        if t.side == "buy":
            d["buy_amount"] += t.value
        elif t.side == "sell" and t.pnl is not None:
            d["sell_pnl"] += t.pnl
            if t.pnl > 0:
                d["wins"] += 1
            else:
                d["losses"] += 1

    results = []
    for ticker, d in data.items():
        total_rt = d["num_trades"]
        win_rate = d["wins"] / total_rt * 100 if total_rt > 0 else 0
        return_pct = d["sell_pnl"] / d["buy_amount"] * 100 \
            if d["buy_amount"] > 0 else 0
        results.append({
            "symbol": ticker,
            "total_return_pct": round(return_pct, 2),
            "num_trades": total_rt,
            "win_rate": round(win_rate, 1),
        })
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Public API
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(
    symbols: list[str],
    strategy_name: str,
    start_date: str,
    end_date: str,
    strategy_params: dict | None = None,
    initial_capital: float = 100_000_000,
    commission_rate: float = 0.0015,
    slippage_rate: float = 0.0005,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    max_positions: int = 5,
    buy_fill_type: str = "close",
    sell_fill_type: str = "close",
    max_hold_days: int | None = None,
    min_hold_days: int = 0,
    sell_divide_pct: float = 100.0,
    max_sell_divisions: int | None = None,
    buy_weight_mode: str = "equal",
    buy_divide_pct: float = 100.0,
    max_buy_per_day: int | None = None,
    max_buy_count: int | None = None,
    factor_weights: dict | None = None,
    rebalance_period: str | None = None,
    market_timing: dict | None = None,
) -> dict:
    """
    백테스트 실행 진입점.

    Args:
        symbols:         종목 코드 리스트 (예: ["005930", "000660"])
        strategy_name:   전략명 (예: "골든크로스", "이격도", "GoldenCross")
        start_date:      시작일 "YYYY-MM-DD"
        end_date:        종료일 "YYYY-MM-DD"
        strategy_params: 전략 파라미터 (예: {"short_period": 5, "long_period": 20})
        initial_capital: 초기 자본 (원)
        commission_rate: 수수료율 (예: 0.0015 = 0.15%)
        slippage_rate:   슬리피지율
        stop_loss_pct:   손절 % (예: 5.0 = 5%)
        take_profit_pct: 익절 % (예: 10.0 = 10%)
        max_positions:   동시 최대 보유 종목 수

    Returns:
        ResultFormatter.to_api_response()와 동일한 구조
    """
    cfg = BacktestConfig(
        symbols=symbols,
        strategy_name=strategy_name,
        strategy_params=strategy_params or {},
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        max_positions=max_positions,
        buy_fill_type=buy_fill_type,
        sell_fill_type=sell_fill_type,
        max_hold_days=max_hold_days,
        min_hold_days=min_hold_days,
        sell_divide_pct=sell_divide_pct,
        max_sell_divisions=max_sell_divisions,
        buy_weight_mode=buy_weight_mode,
        buy_divide_pct=buy_divide_pct,
        max_buy_per_day=max_buy_per_day,
        max_buy_count=max_buy_count,
        factor_weights=factor_weights,
        rebalance_period=rebalance_period,
        market_timing=market_timing,
    )
    engine = BacktestEngine(cfg)
    return engine.run()
