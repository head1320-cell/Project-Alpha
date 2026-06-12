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

# 하이브리드 체결 센티널 — "분봉 없음(일봉 폴백)"과 "지정가 미체결(None)"의 구분
_NO_BARS = object()


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
    # 체결 가격 기준 ± 오프셋% (젠포트 "전일종가 +0.5%" 지정가 모델). 0=미사용(기존 불변).
    # 0이 아니면 지정가 도달 검증: 매수는 당일 저가≤지정가일 때 min(지정가,시가) 체결,
    # 매도는 당일 고가≥지정가일 때 max(지정가,시가) 체결 — 미도달이면 그날 미체결.
    buy_fill_offset_pct: float = 0.0
    sell_fill_offset_pct: float = 0.0   # 신호 매도에 적용 (손익절·트레일링은 기존 트리거가 체결)
    # 수식입력 기준가 (fill_type="expr"일 때) — factor_expr 산술식의 마지막 봉 값.
    # 당일 종가를 포함하는 식은 look-ahead가 될 수 있음 — 전일 기준(과거값(...)) 권장.
    buy_fill_expr: str | None = None
    sell_fill_expr: str | None = None
    # 보유일 만기 매도 가격 기준 (기본 close = 기존 동작 불변). 오프셋 지정가 미도달이면
    # 종가 폴백(만기 청산은 반드시 종결 — 보수적)
    expiry_fill_type: str = "close"
    expiry_fill_offset_pct: float = 0.0
    # 종목당 최대 매수 금액 (원). None=무제한
    max_buy_amount: float | None = None
    # 자산배분: 평가자산 대비 현금 상시 보유 비중 % (0=미사용). 매수 시 이 비중만큼 현금 잔류
    cash_reserve_pct: float = 0.0
    # 매도 정밀화 (Phase 2). 모두 기본 비활성 = 기존 동작 불변
    max_hold_days: int | None = None    # 보유기간 매도: N일 경과 시 강제 청산
    min_hold_days: int = 0              # 최소 보유: N일 전엔 손익절·신호 매도 보류
    # 당일 매매: 당일 진입 포지션을 같은 봉 종가에 전량 청산 (시가류 매수 체결과
    # 결합하면 시가 진입→종가 청산 데이트레이딩 근사). min/max_hold보다 우선
    day_trade: bool = False
    sell_divide_pct: float = 100.0      # 분할 매도 비중 % (100=전량, 50=절반씩)
    max_sell_divisions: int | None = None  # 분할 매도 최대 횟수 (None=무제한, 도달 시 전량청산)
    # 분할 래더 (젠포트 분할 매수/매도 — 가격변동%·비중% 단계). 기본 None=기존 불변.
    # 보수적 해석: 래더는 신호 당일만 유효 — 도달한 단계만 체결, 미도달 단계는 소멸.
    # 각 단계 dict: {"move_pct": 기준가 대비 변동%, "weight_pct": 배분 비중%}
    buy_ladder: list | None = None
    sell_ladder: list | None = None
    expiry_sell_method: str = "all"     # 보유일 만기: all=일괄 | ladder=분할(잔량은 종가 청산)
    # 매수 정밀화 (Phase 3). 기본값 = 기존 동작 불변
    breakthrough_buy: bool = False      # 돌파매수: 당일 고가가 전일 고가 돌파 시에만 진입
    buy_weight_mode: str = "equal"      # 매수 비중: equal(동일가중) | factor(팩터가중) | atr(역변동성)
    buy_divide_pct: float = 100.0       # 분할 매수 비중 % (100=한번에, 50=절반씩 추가매수)
    max_buy_per_day: int | None = None  # 일일 최대 신규 매수 종목 수
    max_buy_count: int | None = None    # 종목당 최대 분할 매수 횟수
    rebuy_block_days: int = 0           # 재매수 방지: 청산 후 N일(캘린더) 이내 재매수 금지 (0=미사용)
    factor_weights: dict | None = None  # 종목별 팩터 가중치 {ticker: 0~1} (팩터가중 모드용)
    # 정기 리밸런싱 + 마켓타이밍 (GENPORT_GAP ②). 기본 비활성 = 기존 동작 불변
    rebalance_period: str | None = None  # None·"daily"=매일 | "weekly"·"monthly"=주·월 첫 거래일에만 신규 매수
    market_timing: dict | None = None    # {"index_ticker","action"("block_buy"|"exit_all"),"conditions":[조건식]}
    # 시그널 벡터화 — 조건식을 전 봉 사전계산(동일 결과, 10~100×). False면 per-bar(디버그용)
    vectorize_signals: bool = True
    # 매수 우선순위식 (젠포트 매수 종목 선택 우선순위): 봉마다 후보들의 식 값으로
    # 매수 실행 순서를 정렬 — max_positions/일일 한도가 상위 후보부터 소진된다.
    buy_sort_expr: str | None = None
    buy_sort_desc: bool = True          # True=식 값 높은순
    # 하이브리드 체결 ("신호는 일봉, 체결만 분봉"): (종목,일자) 분봉이 적재돼 있으면
    # 매매 시간 윈도 안에서 정밀 체결 — 지정가 도달/시장가(윈도 시작 시가)/TWAP·VWAP.
    # 분봉 없는 날은 일봉 모델 폴백(결과 intraday에 적용/폴백 건수 보고 — 정직).
    intraday_fill: bool = False
    buy_time_start: str = "0900"        # 매수 시간 윈도 (HHMM)
    buy_time_end: str = "1530"
    sell_time_start: str = "0900"       # 매도 시간 윈도 (HHMM)
    sell_time_end: str = "1530"
    # 신호 기준일 (젠포트 Tip 3: "전일 종가 기준 선정 → 익일 매매").
    # 0 = 당일 봉 포함(기존 동작 불변, 종가 체결과 정합).
    # 1 = 전일 봉까지로 신호 평가, 체결은 당일 — 시가·전일종가류 체결의 look-ahead 제거.
    signal_lag: int = 0


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
        self._last_exit: dict[str, str] = {}    # 재매수 방지용 — 전량 청산일 {ticker: date_str}
        self._intraday = {"applied": 0, "fallback": 0}  # 하이브리드 체결 적용/일봉 폴백 건수

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

        # 매수 우선순위식 — 워밍업·패널 산정 전에 등록 (문법 오류는 ValueError 전파 → 400)
        if self.cfg.buy_sort_expr and hasattr(strategy, "set_priority_expr"):
            strategy.set_priority_expr(self.cfg.buy_sort_expr)

        # 래더 검증 (비중 합 ≤100, 단계 ≤10)
        for name, ladder in (("buy_ladder", self.cfg.buy_ladder),
                             ("sell_ladder", self.cfg.sell_ladder)):
            if ladder:
                if len(ladder) > 10:
                    raise ValueError(f"{name}: 분할 단계는 최대 10개입니다")
                total_w = sum(float(s.get("weight_pct") or 0) for s in ladder)
                if not (0 < total_w <= 100.0 + 1e-9):
                    raise ValueError(f"{name}: 비중 합은 0~100% 사이여야 합니다 (현재 {total_w:g}%)")

        # 수식입력 기준가 — 파싱 선행 (횡단면 함수는 체결가 식에 쓸 수 없음)
        self._fill_asts = {}
        for side, txt in (("buy", self.cfg.buy_fill_expr), ("sell", self.cfg.sell_fill_expr)):
            if (txt or "").strip():
                from src.kis_strategies.factor_expr import collect_cross, parse_expr
                ast = parse_expr(txt)
                if collect_cross(ast):
                    raise ValueError("체결가 수식에는 순위/비율(횡단면)을 쓸 수 없습니다")
                self._fill_asts[side] = ast

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
                # 수급 토큰(외국인순매수량 등) 해석용 종목 식별 — pandas attrs는 슬라이스에도 보존
                df.attrs["ticker"] = ticker
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

        # 시그널 벡터화: 조건을 전 봉 1회 평가(인과 연산 — per-bar와 동일 결과 보장,
        # 등가성 테스트로 고정). 실패·미지원 전략이면 루프에서 per-bar 폴백.
        if self.cfg.vectorize_signals and hasattr(strategy, "precompute_signals"):
            try:
                strategy.precompute_signals(ohlcv_map)
            except Exception as e:
                logger.debug(f"precompute_signals skipped: {e}")

        logger.info(
            f"Backtest: {self.cfg.strategy_name} | "
            f"{self.cfg.symbols} | {len(sim_dates)} trading days"
        )

        # 정기 리밸런싱(신규 매수일 게이트) + 마켓타이밍(지수 조건 포트폴리오 게이트)
        rebalance_days = self._rebalance_days(sim_dates)
        mt_df = self._load_market_timing_index(warmup_start) if self.cfg.market_timing else None
        mt_action = str((self.cfg.market_timing or {}).get("action") or "block_buy")

        # 신호 기준일 시차 (젠포트식 전일 종가 기준). 0=당일 봉(기존)
        lag = max(0, int(self.cfg.signal_lag or 0))

        # Day-by-day 시뮬레이션
        for sim_date in sim_dates:
            date_str = sim_date.strftime("%Y-%m-%d")
            self._buys_today = 0  # 일일 신규 매수 카운터 (max_buy_per_day 제한용)
            # 현금 비중 유지(자산배분): 당일 평가자산 1회 계산 — 매수 가용액 산정 기준
            self._equity_today = (self._calc_equity(ohlcv_map, sim_date)
                                  if self.cfg.cash_reserve_pct > 0 else 0.0)

            # 0. 마켓타이밍: 지수 조건 미충족(OFF) → 신규 매수 차단, exit_all이면 전량 청산
            #    (포트폴리오 레벨 리스크오프 — min_hold_days보다 우선)
            market_on = self._market_timing_on(mt_df, sim_date, lag) if mt_df is not None else True
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

                # 보유기간 매도: max_hold_days 경과 시 강제 청산 (분할 비중·만기 가격 기준 적용)
                if self.cfg.max_hold_days is not None and days_held >= self.cfg.max_hold_days:
                    reason = f"보유기간 {self.cfg.max_hold_days}일 경과"
                    if self.cfg.expiry_sell_method == "ladder" and self.cfg.sell_ladder:
                        # 만기 래더 — 미체결 잔량은 종가로 강제 청산(만기는 반드시 종결)
                        from src.engine.fill_price import resolve_from_slice
                        base = resolve_from_slice(self.cfg.expiry_fill_type or "close", df_to_date)
                        fills = self._ladder_fills("sell", self.cfg.sell_ladder,
                                                   float(base or curr_price), df_to_date)
                        self._execute_sell_ladder(ticker, fills, date_str, reason,
                                                  force_close_rest=curr_price)
                        continue
                    expiry_price = self._expiry_price(df_to_date, curr_price)
                    self._execute_sell(ticker, expiry_price, date_str, reason,
                                       sell_fraction=self.cfg.sell_divide_pct / 100.0)
                    continue
                # 손절/익절: 최소 보유기간 이후에만 (min_hold_days)
                if days_held >= self.cfg.min_hold_days:
                    self._check_risk_triggers(ticker, pos, curr_price, date_str)

            # 2. 전략 신호 생성 (각 종목별)
            # 우선순위식이 있으면 매수는 큐에 모았다가 당일 식 값 순으로 실행
            # (max_positions·일일 한도가 상위 후보부터 소진 — 젠포트 매수 우선순위)
            from src.kis_signal import Action
            buy_queue: list[tuple] | None = [] if self.cfg.buy_sort_expr else None
            for ticker in self.cfg.symbols:
                if ticker not in ohlcv_map:
                    continue

                # as-of 슬라이스 (미래 데이터 차단 — look-ahead bias 방지)
                df_slice = ohlcv_map[ticker].loc[:sim_date]
                if len(df_slice) < strategy.required_days + lag:
                    continue

                # 신호 기준 봉: signal_lag>0이면 lag봉 이전 (체결은 당일 가격 그대로)
                sig_date = sim_date if lag == 0 else df_slice.index[-1 - lag]

                # ① 벡터화 조회(사전계산 시) → ② per-bar 폴백(data_fetcher slice 패치)
                signal = None
                if self.cfg.vectorize_signals and hasattr(strategy, "signal_at"):
                    signal = strategy.signal_at(ticker, sig_date)
                if signal is None:
                    sig_slice = df_slice.iloc[: len(df_slice) - lag] if lag else df_slice
                    signal = self._generate_signal_as_of(strategy, ticker, sig_slice)
                if signal is None:
                    continue

                if signal.action == Action.BUY and signal.is_actionable():
                    if buy_queue is not None:
                        prio = (strategy.priority_at(ticker, sig_date)
                                if hasattr(strategy, "priority_at") else None)
                        buy_queue.append((prio, ticker, df_slice, signal))
                    else:
                        self._process_buy(ticker, df_slice, signal,
                                          market_on, rebalance_days, sim_date, date_str)
                elif signal.action == Action.SELL and signal.is_actionable():
                    # 최소 보유기간 미달 시 신호 매도 보류
                    pos = self.positions.get(ticker)
                    if pos is not None:
                        days_held = self._days_held(pos.entry_date, date_str)
                        if days_held < self.cfg.min_hold_days:
                            continue
                    # 분할 래더 매도 — 도달 단계만 (신호 당일 유효)
                    if self.cfg.sell_ladder and pos is not None:
                        base = self._fill_base("sell", df_slice)
                        if base and base > 0:
                            fills = self._ladder_fills("sell", self.cfg.sell_ladder,
                                                       float(base), df_slice)
                            if fills:
                                self._execute_sell_ladder(ticker, fills, date_str, signal.reason)
                        continue
                    sell_price = self._fill_with_offset("sell", df_slice)
                    if sell_price is None and self.cfg.sell_fill_offset_pct:
                        continue  # 지정가 미도달 — 그날 미체결(보유 지속)
                    close_price = float(df_slice["close"].iloc[-1])
                    self._execute_sell(ticker, sell_price or close_price, date_str, signal.reason,
                                       sell_fraction=self.cfg.sell_divide_pct / 100.0)

            if buy_queue:
                # 식 값 정렬 (None=평가 불가 → 후순위, 동률은 종목코드로 결정적)
                sign = -1.0 if self.cfg.buy_sort_desc else 1.0
                buy_queue.sort(key=lambda x: (x[0] is None,
                                              sign * x[0] if x[0] is not None else 0.0,
                                              x[1]))
                for _prio, ticker, df_slice, signal in buy_queue:
                    self._process_buy(ticker, df_slice, signal,
                                      market_on, rebalance_days, sim_date, date_str)

            # 2.5 당일 매매: 오늘 진입한 포지션을 장 마감(당일 종가)에 전량 청산
            if self.cfg.day_trade and self.positions:
                for ticker, pos in list(self.positions.items()):
                    if pos.entry_date != date_str or ticker not in ohlcv_map:
                        continue
                    df_to = ohlcv_map[ticker].loc[:sim_date]
                    if df_to.empty:
                        continue
                    self._execute_sell(ticker, float(df_to["close"].iloc[-1]),
                                       date_str, "당일 매매 청산")

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
        # 수급 토큰의 종목 식별 — 벡터화 경로(ohlcv_map attrs)와 per-bar 경로 일관성
        df_copy.attrs["ticker"] = df_slice.attrs.get("ticker", ticker)

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
        usable = self._usable_cash()  # 자산배분(현금 비중) 반영 — 미사용 시 cash 그대로
        base = usable * self.cfg.position_size_pct / slots
        if self.cfg.buy_weight_mode == "factor" and factor_weight is not None:
            # 팩터가중: 가중치를 동일가중 대비 배수로 (0.5~1.5 범위로 정규화)
            mult = 0.5 + max(0.0, min(1.0, factor_weight))
            base *= mult
        elif self.cfg.buy_weight_mode == "atr" and atr_pct:
            # ATR 비중: 기준 NATR 2% 대비 역비례 배수 (0.5~1.5 클램프) — 변동성 패리티 근사
            base *= max(0.5, min(1.5, 2.0 / atr_pct))
        return min(base, usable * 0.95)

    def _process_buy(self, ticker: str, df_slice, signal,
                     market_on: bool, rebalance_days, sim_date, date_str: str):
        """매수 신호 1건 처리 — 게이트(마켓타이밍·리밸런싱·돌파) + 체결가 + 집행."""
        can_buy = market_on and (rebalance_days is None or sim_date in rebalance_days)
        bb_price = None
        if can_buy and self.cfg.breakthrough_buy:
            # 돌파매수: 전일 고가 미돌파면 오늘은 진입하지 않음
            bb_price = self._breakthrough_price(df_slice)
            can_buy = bb_price is not None
        if not can_buy:
            return
        # 분할 래더 — 기준가 대비 가격 단계별 비중 체결 (신호 당일만 유효, 신규 진입만)
        if self.cfg.buy_ladder and ticker not in self.positions:
            base = self._fill_base("buy", df_slice)
            if base and base > 0:
                fills = self._ladder_fills("buy", self.cfg.buy_ladder, float(base), df_slice)
                if fills:
                    self._execute_buy_ladder(ticker, fills, date_str, signal.reason)
            return
        buy_price = bb_price or self._fill_with_offset("buy", df_slice)
        if buy_price is None and self.cfg.buy_fill_offset_pct:
            return  # 지정가(기준가±오프셋) 미도달 — 그날 미체결
        close_price = float(df_slice["close"].iloc[-1])
        fw = (self.cfg.factor_weights or {}).get(ticker)
        natr = self._natr_pct(df_slice) if self.cfg.buy_weight_mode == "atr" else None
        self._execute_buy(ticker, buy_price or close_price, date_str, signal.reason,
                          factor_weight=fw, atr_pct=natr)

    def _fill_base(self, side: str, df_slice) -> float | None:
        """오프셋·래더 적용 전의 체결 기준가 (유형 20종 + 수식입력)."""
        from src.engine.fill_price import resolve_from_slice
        ft = self.cfg.buy_fill_type if side == "buy" else self.cfg.sell_fill_type
        if ft == "expr":
            return self._fill_expr_base(side, df_slice)
        return resolve_from_slice(ft, df_slice)

    def _ladder_fills(self, side: str, ladder: list, base: float, df_slice) -> list[tuple]:
        """래더 단계 → 당일 도달 검증된 (체결가, 비중%) 목록.

        보수적 해석: 신호 당일만 유효 — 저가/고가 도달 단계만 체결, 나머지 소멸.
        갭이 지정가를 건너뛰면 시가 체결 (오프셋 지정가 모델과 동일 규칙)."""
        try:
            low = float(df_slice["low"].iloc[-1])
            high = float(df_slice["high"].iloc[-1])
            open_ = float(df_slice["open"].iloc[-1])
        except Exception:
            return []
        fills = []
        for s in ladder or []:
            try:
                move = float(s.get("move_pct") or 0)
                w = float(s.get("weight_pct") or 0)
            except (TypeError, ValueError):
                continue
            if w <= 0:
                continue
            p = base * (1 + move / 100.0)
            if side == "buy":
                if low <= p:
                    fills.append((min(p, open_), w))
            else:
                if high >= p:
                    fills.append((max(p, open_), w))
        return fills

    def _execute_buy_ladder(self, ticker: str, fills: list, date_str: str, reason: str):
        """래더 분할 매수 — 도달 단계별 체결을 하나의 포지션으로 합산 (Trade는 단계별)."""
        if self.positions.get(ticker) is not None:
            return
        if len(self.positions) >= self.cfg.max_positions:
            return
        if self.cfg.max_buy_per_day is not None and getattr(self, "_buys_today", 0) >= self.cfg.max_buy_per_day:
            return
        if self.cfg.rebuy_block_days > 0:
            last = self._last_exit.get(ticker)
            if last is not None and self._days_held(last, date_str) <= self.cfg.rebuy_block_days:
                return
        alloc_total = min(self._initial_alloc(), self._usable_cash() * 0.95)
        if self.cfg.max_buy_amount is not None:
            alloc_total = min(alloc_total, self.cfg.max_buy_amount)
        legs, qty_total, cost_total = [], 0, 0.0
        for price, w in fills:
            exec_price = price * (1 + self.cfg.slippage_rate)
            alloc = alloc_total * (w / 100.0)
            qty = int(alloc / exec_price)
            if qty <= 0:
                continue
            value = qty * exec_price
            commission = value * self.cfg.commission_rate
            if cost_total + value + commission > self._usable_cash():
                break
            legs.append((exec_price, qty, value, commission))
            qty_total += qty
            cost_total += value + commission
        if qty_total <= 0:
            return
        self.cash -= cost_total
        self._buys_today = getattr(self, "_buys_today", 0) + 1
        avg = sum(p * q for p, q, _, _ in legs) / qty_total
        stop = avg * (1 - self.cfg.stop_loss_pct / 100) if self.cfg.stop_loss_pct else None
        tp = avg * (1 + self.cfg.take_profit_pct / 100) if self.cfg.take_profit_pct else None
        self.positions[ticker] = Position(
            ticker=ticker, quantity=qty_total, avg_price=avg, entry_date=date_str,
            stop_loss_price=stop, take_profit_price=tp, peak_price=avg)
        for i, (p, q, v, c) in enumerate(legs, 1):
            self.trades.append(Trade(
                date=date_str, ticker=ticker, side="buy", price=p, quantity=q,
                value=v, commission=c, slippage=v * self.cfg.slippage_rate,
                reason=f"{reason} (래더 {i}/{len(legs)})"))

    def _execute_sell_ladder(self, ticker: str, fills: list, date_str: str, reason: str,
                             force_close_rest: float | None = None):
        """래더 분할 매도 — 단계 비중은 신호 시점 보유수량 기준.

        force_close_rest가 주어지면(만기) 미체결 잔량을 그 가격(종가)으로 강제 청산."""
        pos = self.positions.get(ticker)
        if pos is None:
            return
        total_w = 0.0
        for i, (price, w) in enumerate(fills, 1):
            if ticker not in self.positions:
                return
            remaining_w = max(0.0, 100.0 - total_w)
            frac = min(1.0, w / remaining_w) if remaining_w > 0 else 1.0
            self._execute_sell(ticker, price, date_str, f"{reason} (래더 {i}/{len(fills)})",
                               sell_fraction=frac)
            total_w += w
        if force_close_rest is not None and ticker in self.positions:
            self._execute_sell(ticker, force_close_rest, date_str, f"{reason} (잔량 종가)")

    def _usable_cash(self) -> float:
        """매수 가용 현금 — 자산배분(현금 비중 유지) 시 예비금을 제외한 잔액."""
        if self.cfg.cash_reserve_pct > 0:
            reserve = getattr(self, "_equity_today", 0.0) * self.cfg.cash_reserve_pct / 100.0
            return max(0.0, self.cash - reserve)
        return self.cash

    def _fill_with_offset(self, side: str, df_slice) -> float | None:
        """체결가 유형 + 오프셋%(지정가 모델).

        오프셋 0이면 기존 resolve 그대로(None 가능 — 호출부가 종가 폴백, 기존 불변).
        오프셋이 있으면 기준가×(1+off%)를 지정가로 보고 당일 도달 검증:
        매수는 저가≤지정가일 때 min(지정가, 시가), 매도는 고가≤지정가일 때
        max(지정가, 시가) — 갭이 지정가를 건너뛰면 시가 체결. 미도달이면 None.

        intraday_fill이면 (종목,일자) 분봉이 있을 때 매매 시간 윈도 안에서 정밀
        판정(지정가 도달·시장가·TWAP/VWAP) — 분봉 없으면 일봉 모델 폴백."""
        from src.engine.fill_price import resolve_from_slice
        fill_type = self.cfg.buy_fill_type if side == "buy" else self.cfg.sell_fill_type
        off = self.cfg.buy_fill_offset_pct if side == "buy" else self.cfg.sell_fill_offset_pct
        if fill_type == "expr":
            base = self._fill_expr_base(side, df_slice)
            if base is None:
                return None if off else float(df_slice["close"].iloc[-1])  # 평가 불가 → 종가 폴백
        else:
            base = resolve_from_slice(fill_type, df_slice)

        if self.cfg.intraday_fill:
            refined = self._intraday_price(side, df_slice, fill_type, base, off)
            if refined is not _NO_BARS:
                self._intraday["applied"] += 1
                return refined  # None = 윈도 내 지정가 미도달(미체결)
            self._intraday["fallback"] += 1

        if not off:
            return base
        if base is None:
            return None
        p = base * (1 + off / 100.0)
        try:
            low = float(df_slice["low"].iloc[-1])
            high = float(df_slice["high"].iloc[-1])
            open_ = float(df_slice["open"].iloc[-1])
        except Exception:
            return p
        if side == "buy":
            return min(p, open_) if low <= p else None
        return max(p, open_) if high >= p else None

    def _fill_expr_base(self, side: str, df_slice) -> float | None:
        """수식입력 기준가 — 산술식을 슬라이스에 평가한 마지막 봉 값."""
        ast = getattr(self, "_fill_asts", {}).get(side)
        if ast is None:
            return None
        try:
            from src.kis_strategies.condition_strategy import (
                _apply_function,
                _apply_two_factor,
                _base_series,
            )
            from src.kis_strategies.factor_expr import eval_expr

            def tok(name: str):
                s = _base_series(df_slice, "{" + name + "}")
                return None if s is None or len(s) == 0 else s.astype(float)

            out = eval_expr(ast, {"token": tok, "cross": lambda k: None,
                                  "apply": _apply_function, "two": _apply_two_factor})
            if out is None or not hasattr(out, "iloc") or len(out) == 0:
                return None
            v = out.iloc[-1]
            return float(v) if pd.notna(v) and float(v) > 0 else None
        except Exception:
            return None

    def _expiry_price(self, df_slice, close_price: float) -> float:
        """보유일 만기 매도가 — 가격 기준(±오프셋 지정가) 적용, 미도달 시 종가 폴백.

        만기 청산은 반드시 그날 종결돼야 하므로 미체결 상태를 남기지 않는다(보수적)."""
        from src.engine.fill_price import resolve_from_slice
        t = self.cfg.expiry_fill_type or "close"
        off = self.cfg.expiry_fill_offset_pct
        if t == "close" and not off:
            return close_price  # 기존 동작
        base = resolve_from_slice(t, df_slice)
        if base is None or base <= 0:
            return close_price
        if not off:
            return float(base)
        p = base * (1 + off / 100.0)
        try:
            high = float(df_slice["high"].iloc[-1])
            open_ = float(df_slice["open"].iloc[-1])
        except Exception:
            return close_price
        return max(p, open_) if high >= p else close_price  # 미도달 → 종가(시장가) 폴백

    def _intraday_price(self, side: str, df_slice, fill_type: str, base, off):
        """분봉 정밀 체결 — 매매 시간 윈도 내에서.

        반환: 체결가 | None(지정가 미도달=미체결) | _NO_BARS(분봉·윈도 없음 → 일봉 폴백).
        close·전일가류 체결 유형은 윈도와 무관(장마감/전일 기준)이라 일봉 유지."""
        try:
            ticker = str(df_slice.attrs.get("ticker") or "")
            date_iso = df_slice.index[-1].strftime("%Y-%m-%d")
        except Exception:
            return _NO_BARS
        if not ticker:
            return _NO_BARS
        try:
            from src.data.minute_bars import load_minute_bars
            bars = load_minute_bars(ticker, date_iso)
        except Exception:
            return _NO_BARS
        if bars is None or bars.empty:
            return _NO_BARS
        start = (self.cfg.buy_time_start if side == "buy" else self.cfg.sell_time_start) or "0900"
        end = (self.cfg.buy_time_end if side == "buy" else self.cfg.sell_time_end) or "1530"
        t4 = bars["time"].astype(str).str[:4]
        w = bars[(t4 >= start.replace(":", "")[:4]) & (t4 <= end.replace(":", "")[:4])]
        if w.empty:
            return _NO_BARS
        if off:
            if base is None:
                return _NO_BARS
            p = base * (1 + off / 100.0)
            first_open = float(w["open"].iloc[0])
            if side == "buy":
                return min(p, first_open) if float(w["low"].min()) <= p else None
            return max(p, first_open) if float(w["high"].max()) >= p else None
        if fill_type == "twap":
            return float(w["close"].astype(float).mean())
        if fill_type == "vwap":
            v = w["volume"].astype(float)
            c = w["close"].astype(float)
            tv = float(v.sum())
            return float((c * v).sum() / tv) if tv > 0 else float(c.mean())
        if fill_type == "open":
            return float(w["open"].iloc[0])  # 매매 시간 시작 시장가
        return _NO_BARS

    def _breakthrough_price(self, df_slice) -> float | None:
        """돌파매수 체결가 — 당일 고가 ≥ 전일 고가면 max(시가, 전일고가), 미돌파면 None.

        지정가를 전일 고가에 걸어둔 모델: 갭상승(시가>전일고가)이면 시가 체결."""
        try:
            if df_slice is None or len(df_slice) < 2:
                return None
            prev_high = float(df_slice["high"].iloc[-2])
            today_high = float(df_slice["high"].iloc[-1])
            today_open = float(df_slice["open"].iloc[-1])
            if today_high < prev_high:
                return None
            return max(today_open, prev_high)
        except Exception:
            return None

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
            add_alloc = min(add_alloc, self._usable_cash() * 0.95)
            # 종목당 최대 매수 금액: 기존 투자액 포함 총 한도
            if self.cfg.max_buy_amount is not None:
                remaining = self.cfg.max_buy_amount - existing.avg_price * existing.quantity
                add_alloc = min(add_alloc, max(0.0, remaining))
            exec_price = price * (1 + self.cfg.slippage_rate)
            if add_alloc < exec_price:
                return
            qty = int(add_alloc / exec_price)
            if qty <= 0:
                return
            value = qty * exec_price
            commission = value * self.cfg.commission_rate
            if value + commission > self._usable_cash():
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
        # 재매수 방지: 청산 후 N일(캘린더) 이내면 진입하지 않음
        if self.cfg.rebuy_block_days > 0:
            last = self._last_exit.get(ticker)
            if last is not None and self._days_held(last, date_str) <= self.cfg.rebuy_block_days:
                return

        alloc = self._initial_alloc(factor_weight, atr_pct)
        if self.cfg.buy_divide_pct < 100.0:
            alloc *= (self.cfg.buy_divide_pct / 100.0)
        alloc = min(alloc, self._usable_cash() * 0.95)
        if self.cfg.max_buy_amount is not None:
            alloc = min(alloc, self.cfg.max_buy_amount)  # 종목당 최대 매수 금액
        if alloc < price:
            return

        exec_price = price * (1 + self.cfg.slippage_rate)
        quantity = int(alloc / exec_price)
        if quantity <= 0:
            return

        value = quantity * exec_price
        commission = value * self.cfg.commission_rate
        total_cost = value + commission

        if total_cost > self._usable_cash():
            quantity = int((self._usable_cash() * 0.95) / (exec_price * (1 + self.cfg.commission_rate)))
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
            self._last_exit[ticker] = date_str  # 재매수 방지 기준일
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

    def _market_timing_on(self, idx_df, sim_date, lag: int = 0) -> bool:
        """지수 조건 전부 충족 시 ON. 평가 불가·데이터 부족이면 ON(fail-open — 개입 안 함).

        조건식은 ConditionStrategy와 동일 모델(가격·거래량 토큰 + 18함수)을 지수 봉에 적용.
        예: {종가} ams(20) >= 50 (평균모멘텀스코어), {종가} pct(20) >= 0 (20일 수익률).
        signal_lag>0이면 지수 판단도 종목 신호와 동일하게 lag봉 이전 데이터 기준.
        """
        if idx_df is None:
            return True
        conds = (self.cfg.market_timing or {}).get("conditions") or []
        if not conds:
            return True
        sl = idx_df.loc[:sim_date]
        if lag:
            if len(sl) <= lag:
                return True  # 데이터 부족 — fail-open
            sl = sl.iloc[: len(sl) - lag]
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

        # 하이브리드 체결 통계 (정직: 분봉 적용/일봉 폴백 비율 공개)
        intraday_meta = None
        if self.cfg.intraday_fill:
            tot = self._intraday["applied"] + self._intraday["fallback"]
            intraday_meta = {**self._intraday,
                             "applied_pct": round(self._intraday["applied"] / tot * 100, 1) if tot else 0.0}

        return {
            "currency": "KRW",
            "intraday": intraday_meta,
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
    day_trade: bool = False,
    sell_divide_pct: float = 100.0,
    max_sell_divisions: int | None = None,
    buy_weight_mode: str = "equal",
    buy_divide_pct: float = 100.0,
    max_buy_per_day: int | None = None,
    max_buy_count: int | None = None,
    factor_weights: dict | None = None,
    breakthrough_buy: bool = False,
    rebalance_period: str | None = None,
    market_timing: dict | None = None,
    signal_lag: int = 0,
    rebuy_block_days: int = 0,
    buy_fill_offset_pct: float = 0.0,
    sell_fill_offset_pct: float = 0.0,
    max_buy_amount: float | None = None,
    cash_reserve_pct: float = 0.0,
    buy_sort_expr: str | None = None,
    buy_sort_desc: bool = True,
    intraday_fill: bool = False,
    buy_time_start: str = "0900",
    buy_time_end: str = "1530",
    sell_time_start: str = "0900",
    sell_time_end: str = "1530",
    buy_fill_expr: str | None = None,
    sell_fill_expr: str | None = None,
    expiry_fill_type: str = "close",
    expiry_fill_offset_pct: float = 0.0,
    buy_ladder: list | None = None,
    sell_ladder: list | None = None,
    expiry_sell_method: str = "all",
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
        day_trade=day_trade,
        sell_divide_pct=sell_divide_pct,
        max_sell_divisions=max_sell_divisions,
        buy_weight_mode=buy_weight_mode,
        buy_divide_pct=buy_divide_pct,
        max_buy_per_day=max_buy_per_day,
        max_buy_count=max_buy_count,
        factor_weights=factor_weights,
        breakthrough_buy=breakthrough_buy,
        rebalance_period=rebalance_period,
        market_timing=market_timing,
        signal_lag=signal_lag,
        rebuy_block_days=rebuy_block_days,
        buy_fill_offset_pct=buy_fill_offset_pct,
        sell_fill_offset_pct=sell_fill_offset_pct,
        max_buy_amount=max_buy_amount,
        cash_reserve_pct=cash_reserve_pct,
        buy_sort_expr=buy_sort_expr,
        buy_sort_desc=buy_sort_desc,
        intraday_fill=intraday_fill,
        buy_time_start=buy_time_start,
        buy_time_end=buy_time_end,
        sell_time_start=sell_time_start,
        sell_time_end=sell_time_end,
        buy_fill_expr=buy_fill_expr,
        sell_fill_expr=sell_fill_expr,
        expiry_fill_type=expiry_fill_type,
        expiry_fill_offset_pct=expiry_fill_offset_pct,
        buy_ladder=buy_ladder,
        sell_ladder=sell_ladder,
        expiry_sell_method=expiry_sell_method,
    )
    engine = BacktestEngine(cfg)
    return engine.run()
