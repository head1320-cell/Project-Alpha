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
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import text

from src.engine.quant_metrics import compute_metrics

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DB Data Provider (as-of 날짜 지원)
# ═══════════════════════════════════════════════════════════════════════════════

PROGRESS_MAX_EVENTS = 100


def progress_step(total: int, max_events: int = PROGRESS_MAX_EVENTS) -> int:
    """진행 이벤트를 max_events 이하로 묶는 보고 간격.

    `total // max_events`는 실제로 상한이 아니다 — total=199면 step=1이 되어 199건이
    그대로 나간다. 각 이벤트가 워커에서 DB 쓰기로 이어지므로(진행률 영속) 올림으로
    계산해 진짜 상한을 만든다.
    """
    return max(1, math.ceil(max(0, int(total)) / max(1, int(max_events))))


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


def resolve_fill_price_safe(fill_type: str, df_slice) -> float:
    """ETF 리밸런싱용 체결 기준가 — 실패 시 마지막 종가 폴백 (수식입력 제외)."""
    try:
        from src.engine.fill_price import resolve_from_slice
        v = resolve_from_slice(fill_type or "close", df_slice)
        if v and v > 0:
            return float(v)
    except Exception:
        pass
    try:
        return float(df_slice["close"].iloc[-1])
    except Exception:
        return 0.0


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
    # 자산배분 ETF 바스켓 (젠포트 자산배분 옵션). None=미사용.
    #   {"etf_pct": 30, "stock_pct": 60,            # 잔여(10%)=현금
    #    "basket": [{"ticker":"069500","weight_pct":60}, ...],  # 바스켓 내 가중(합 100)
    #    "rebalance_months": 3, "fill_type": "prev_close", "offset_pct": 0}
    # 활성 시 주식 슬리브 가용현금 = equity×stock_pct/100 (cash_reserve_pct 일반화),
    # ETF 슬리브는 주기 리밸런싱으로 바스켓 목표 비중 유지. 매수기준가 미도달분은 다음 주기 재시도.
    asset_alloc: dict | None = None
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
    breakthrough_buy: bool = False      # 돌파매수: 기준가 돌파 시에만 진입
    breakthrough_base_type: str = "prev_high"   # 돌파 기준가 유형 (fill_price 20종)
    breakthrough_offset_pct: float = 0.0        # 기준가 ± % (돌파 라인)
    breakthrough_direction: str = "up"          # up=상방 | both=양방(상·하방 어느 쪽이든)
    # 매수 시점 (젠포트 분할 매수의 '장 시작 전|장중 주문' — 보수적 해석):
    # pre_open=장 시작 전 주문(시가 체결 가능, 기존) | intraday=장중 주문(지정가류
    # 매수에서 시가 갭 혜택 배제 — min(지정가,시가) 대신 지정가 그대로)
    buy_timing: str = "pre_open"
    buy_weight_mode: str = "equal"      # 매수 비중: equal(동일가중) | factor(팩터가중) | atr(역변동성)
    buy_divide_pct: float = 100.0       # 분할 매수 비중 % (100=한번에, 50=절반씩 추가매수)
    max_buy_per_day: int | None = None  # 일일 최대 신규 매수 종목 수
    max_buy_count: int | None = None    # 종목당 최대 분할 매수 횟수
    rebuy_block_days: int = 0           # 재매수 방지: 청산 후 N일(캘린더) 이내 재매수 금지 (0=미사용)
    liquidate_at_end: bool = False      # 기간종료 시 잔여 포지션 종가 전량청산 — 통계를 실현 기준으로
    factor_weights: dict | None = None  # 종목별 팩터 가중치 {ticker: 0~1} (팩터가중 모드용)
    # 정기 리밸런싱 + 마켓타이밍 (GENPORT_GAP ②). 기본 비활성 = 기존 동작 불변
    rebalance_period: str | None = None  # None·"daily"=매일 | "weekly"|"monthly"|"quarterly"|
    # "semiannual"|"annual"=주/월/분기/반기/연 첫 거래일에만 신규 매수 (매도는 매일 평가)
    market_timing: dict | None = None    # {"index_ticker","action"("block_buy"|"exit_all"),"conditions":[조건식]}
    # 동적 재편입 (젠포트화 Phase 6). 기본 활성 — Top-N이 매도 후에도 계속 고정되던 문제 해결.
    # 매도로 빈 슬롯이 생기면 그날 즉시, replenishment_pool 중 미보유 종목을 모멘텀점수
    # (가격+수급, look-ahead 없는 시점별 횡단면 퍼센타일) 랭킹 상위부터 채운다. rebalance_period
    # 설정 시엔 그 주기 첫 거래일에 "순위 밖으로 밀려난 보유종목"도 추가로 정리(같은 날 재편입이
    # 자동 리필). replenishment_pool이 None/빈 리스트면 사실상 비활성(레거시 동작, symbols 밖
    # 종목을 알 수 없으므로). 사용자향 API에는 끄는 스위치를 노출하지 않음 — 회귀비교용 내부 값.
    dynamic_replenishment: bool = True
    replenishment_pool: list[str] | None = None  # 재편입 후보풀(symbols의 상위집합). None=비활성
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

    def __init__(self, config: BacktestConfig, progress_cb=None):
        self.cfg = config
        self.progress_cb = progress_cb          # 스트리밍 진행률 콜백(옵션) — dict 이벤트 수신
        self.cash = config.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_history: list[tuple] = []   # (date_str, equity)
        self._last_exit: dict[str, str] = {}    # 재매수 방지용 — 전량 청산일 {ticker: date_str}
        self._eod_liquidated = 0                # 기간종료 청산 종목 수 (통계 표기용)
        self._intraday = {"applied": 0, "fallback": 0}  # 하이브리드 체결 적용/일봉 폴백 건수
        self._etf_pos: dict[str, dict] = {}     # ETF 슬리브 보유 {ticker: {"qty","avg"}}
        # 종목별 fetcher 프레임 캐시 (P1-3) — 봉마다 DataFrame 을 새로 만들지 않는다.
        # 벡터화 경로(`signal_at`)를 쓰는 전략은 여기 들어오지 않으므로 비용을 안 낸다.
        self._fetch_frames: dict[str, dict] = {}
        self.ohlcv_all: dict[str, pd.DataFrame] = {}

    def _emit(self, phase: str, done: int | None = None, total: int | None = None):
        """진행률 콜백 발행(스트리밍용). 콜백 미설정/예외 시 무시 — 백테스트 결과엔 영향 없음."""
        cb = self.progress_cb
        if cb is None:
            return
        evt: dict = {"phase": phase}
        if done is not None:
            evt["done"] = done
        if total is not None:
            evt["total"] = total
        try:
            cb(evt)
        except Exception:
            pass

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
        # 재편입 후보풀(symbols의 상위집합)도 같은 병렬 로더로 함께 적재 — 재편입 랭킹 비용을
        # universe_eval_cap(최대4000) 규모와 분리(재편입 pool은 훨씬 작게 별도 제한됨).
        repl_pool = list(dict.fromkeys(self.cfg.replenishment_pool or []))
        symbols = list(dict.fromkeys(list(self.cfg.symbols) + repl_pool))
        total_syms = len(symbols)

        def _load_one(tk: str):
            """단일 종목 OHLCV 로드 (워커 스레드 — I/O 위주, GIL 해제). 후처리는 메인에서."""
            # 통합 로더: DB → KIS 실시간 → mock 자동 선택 (KIS 경로는 daily_prices에 write-back)
            try:
                from src.data.ohlcv_loader import load_ohlcv_unified
                d = load_ohlcv_unified(tk, warmup_start, self.cfg.end_date, prefer="auto")
            except Exception:
                try:
                    d = load_ohlcv(tk, warmup_start, self.cfg.end_date)
                except Exception:
                    d = pd.DataFrame()
            return tk, d

        def _absorb(tk: str, d):
            """메인 스레드에서만 호출 — ohlcv_map 갱신(딕셔너리 경쟁 없음)."""
            if d is not None and not d.empty:
                # ★ 날짜 문자열 1회 생성 (매 거래일 strftime 제거 — O(N²) 병목 방지)
                d = d.copy()
                d["_date_str"] = d.index.strftime("%Y%m%d")
                d.attrs["ticker"] = tk  # 수급 토큰 해석용 (pandas attrs는 슬라이스에도 보존)
                ohlcv_map[tk] = d

        # KIS 토큰 1회 프리워밍 (병렬 호출 전 — 동시 토큰 발급 경쟁 회피)
        try:
            from src.execution.kis_client import get_kis_client
            _kc = get_kis_client()
            if hasattr(_kc, "prewarm_token"):
                _kc.prewarm_token()
        except Exception:
            pass

        # 종목별 OHLCV 병렬 로드: 직렬 K×(KIS 지연) 병목 제거. RateLimiter(18/s)가 총량을 묶으므로
        # KIS 부담은 동일하고 네트워크 지연만 파이프라인됨. 결과는 ticker 키 dict라 완료 순서 무관
        # → 직렬과 동일 결과(결정론 불변). 진행률은 완료 종목마다 _emit("loading", done/total).
        workers = max(1, min(int(os.getenv("BACKTEST_OHLCV_WORKERS", "10") or 10), 32))
        self._emit("loading", done=0, total=total_syms)
        done = 0
        # 시뮬레이션 루프(_sim_step)와 같은 throttle — 종목마다 emit하면 400종목 = 400 이벤트가
        # 되고, 각 이벤트가 진행률을 DB에 쓰므로 로딩 구간이 커넥션 풀을 그만큼 두드린다.
        # 마지막 종목은 항상 보고해 100%가 누락되지 않게 한다.
        _load_step = progress_step(total_syms)
        if workers <= 1 or total_syms <= 1:
            for tk in symbols:
                _t, _d = _load_one(tk)
                _absorb(_t, _d)
                done += 1
                if done % _load_step == 0 or done == total_syms:
                    self._emit("loading", done=done, total=total_syms)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_load_one, tk) for tk in symbols]
                for fut in as_completed(futs):
                    _t, _d = fut.result()
                    _absorb(_t, _d)
                    done += 1
                    if done % _load_step == 0 or done == total_syms:
                        self._emit("loading", done=done, total=total_syms)

        self.ohlcv_all = ohlcv_map   # per-bar 프레임 캐시가 원본으로 쓴다 (P1-3)

        if not ohlcv_map:
            return self._error_response("No OHLCV data found in DB for given tickers/range")

        # 자산배분 ETF 바스켓 OHLCV 로드 (주식 슬리브와 분리)
        etf_map: dict[str, pd.DataFrame] = {}
        basket = (self.cfg.asset_alloc or {}).get("basket") or []
        if basket:
            from src.data.ohlcv_loader import load_ohlcv_unified
            for leg in basket:
                tk = str(leg.get("ticker") or "").strip()
                if not tk or tk in etf_map:
                    continue
                try:
                    edf = load_ohlcv_unified(tk, warmup_start, self.cfg.end_date, prefer="auto")
                except Exception:
                    edf = pd.DataFrame()
                if not edf.empty:
                    edf = edf.copy()
                    edf.attrs["ticker"] = tk
                    etf_map[tk] = edf

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

        # 동적 재편입용 랭킹 패널 — 모멘텀점수(가격+수급, 펀더멘탈 미포함)만 사용.
        # build_score_panels는 그 날짜까지의 rolling/pct_change만 쓰는 시점별 횡단면 퍼센타일이라
        # 구조적으로 룩어헤드가 없음(전략의 prepare_panel과 별개 — 전략이 무엇이든 항상 계산).
        # 재무 포함 완전한 시점별 종합점수는 실시간 DART 재계산이 필요해 인프라 부재로 미지원
        # (정직한 한계 — trade reason에도 "재무 미반영" 명시).
        self._repl_panel = None
        if self.cfg.dynamic_replenishment and repl_pool:
            try:
                from src.kis_strategies.score_factors import build_score_panels
                panels = build_score_panels(ohlcv_map)
                self._repl_panel = panels.get("모멘텀점수")
            except Exception as e:
                logger.debug(f"replenishment score panel skipped: {e}")
                self._repl_panel = None

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

        # 자산배분 ETF 리밸런싱일 (N개월마다 첫 거래일) + 주식 슬리브 비중
        etf_rebal_days = self._etf_rebalance_days(sim_dates) if etf_map else set()
        alloc_on = bool(self.cfg.asset_alloc and etf_map)

        # 신호 기준일 시차 (젠포트식 전일 종가 기준). 0=당일 봉(기존)
        lag = max(0, int(self.cfg.signal_lag or 0))

        # Day-by-day 시뮬레이션
        _sim_total = len(sim_dates)
        _sim_step = progress_step(_sim_total)  # 진행 이벤트 최대 100개로 throttle
        self._emit("simulating", done=0, total=_sim_total)
        for _sim_idx, sim_date in enumerate(sim_dates, start=1):
            date_str = sim_date.strftime("%Y-%m-%d")
            if _sim_idx % _sim_step == 0 or _sim_idx == _sim_total:
                self._emit("simulating", done=_sim_idx, total=_sim_total)
            self._buys_today = 0  # 일일 신규 매수 카운터 (max_buy_per_day 제한용)
            # 현금/주식 비중 유지(자산배분): 당일 평가자산 1회 계산 — 매수 가용액·ETF 목표 산정
            self._equity_today = (self._calc_equity(ohlcv_map, sim_date, etf_map)
                                  if (self.cfg.cash_reserve_pct > 0 or alloc_on) else 0.0)

            # 0.5 자산배분 ETF 슬리브 리밸런싱 (N개월마다) — 주식 신호 처리 전에 비중 정렬
            if alloc_on and sim_date in etf_rebal_days:
                self._rebalance_etf(etf_map, sim_date, date_str)

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

            # 0.8 정기 리밸런싱 순위이탈 정리 — rebalance_period 첫 거래일에만, 보유종목 중
            #     현재 랭킹 상위 max_positions 밖으로 밀려난 종목만 매도(상위권은 유지).
            #     생긴 빈자리는 아래 2.6 동적 재편입이 같은 날 자동으로 채운다.
            self._rebalance_prune(ohlcv_map, sim_date, date_str, rebalance_days)

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

            # 2.6 동적 재편입: 오늘 매도(0.8 순위이탈·1 손익절/보유만기·2 신호매도 등)로 열린
            #     빈자리를, 리밸런싱 주기와 무관하게 그날 즉시 채운다(사용자 확정: 매도 시점 기준).
            #     max_buy_per_day는 다른 매수와 동일 카운터를 공유(사용자 확정).
            self._replenish_slots(ohlcv_map, sim_date, date_str, market_on)

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

            # 3. 포트폴리오 가치 기록 (주식 + ETF 슬리브 + 현금)
            equity = self._calc_equity(ohlcv_map, sim_date, etf_map)
            self.equity_history.append((date_str, equity))

        # 기간종료 청산 — 잔여 포지션을 마지막 거래일 종가로 전량 실현(수수료·슬리피지 반영).
        # 매도 미발동 전략도 승률/PF/거래수/라운드트립이 채워진다 (min_hold 등 규칙은 강제 청산이라 미적용).
        if self.cfg.liquidate_at_end and self.positions and self.equity_history:
            last_date_str = self.equity_history[-1][0]
            for ticker in list(self.positions.keys()):
                df = ohlcv_map.get(ticker)
                if df is None or df.empty:
                    continue
                df_to = df.loc[:sim_date]
                if df_to.empty:
                    continue
                self._execute_sell(ticker, float(df_to["close"].iloc[-1]),
                                   last_date_str, "기간종료 청산")
                self._eod_liquidated += 1
            # 마지막 자산 기록을 청산 반영값으로 교체 (곡선 끝 == 실현 자산)
            self.equity_history[-1] = (last_date_str,
                                       self._calc_equity(ohlcv_map, sim_date, etf_map))

        duration = (datetime.now() - started_at).total_seconds()
        return self._build_result(duration, ohlcv_map, etf_map)

    def _generate_signal_as_of(self, strategy, ticker: str, df_slice: pd.DataFrame):
        """
        특정 날짜 시점의 슬라이스 DataFrame을 이용해 신호 생성.
        data_fetcher 함수를 monkey-patch하여 look-ahead bias 방지.

        ★ 최적화: 날짜 문자열(_date_str)은 run()에서 사전 생성됨.
          매 호출 dt.strftime/copy 제거 → 슬라이스에서 컬럼만 재구성.
        """
        import src.kis_data_fetcher as fetcher

        # ★봉마다 DataFrame 을 새로 만들지 않는다 (P1-3)★
        # 예전에는 호출마다 6열 DataFrame 을 생성했다 — 실측 3,642회 / 2.20초, 그리고
        # 그 과정의 pandas `__getitem__` 이 38,666회였다. 래퍼 자체가 전략보다 두 배를
        #쓰고 있었다(래퍼 12.39s 중 전략은 4.09s).
        #
        # 종목마다 **한 번** 만들어 두고 봉마다 앞부분을 잘라 넘긴다. `df_slice` 는
        # `ohlcv_map[ticker].loc[:sim_date]` 이므로 항상 전체의 **접두사**이고,
        # 따라서 `full.iloc[:k]` 는 예전 `df_copy` 와 같은 행을 같은 RangeIndex 로 준다.
        cache = self._fetch_frames.get(ticker)
        if cache is None:
            base = self.ohlcv_all.get(ticker)
            if base is None or base.empty:
                return None
            full = pd.DataFrame({
                "date": base["_date_str"].values,
                "open": base["open"].values,
                "high": base["high"].values,
                "low": base["low"].values,
                "close": base["close"].values,
                "volume": base["volume"].values,
            })
            full.attrs["ticker"] = base.attrs.get("ticker", ticker)
            # 52주 고저도 봉마다 `tail(252).max()` 를 다시 돌던 것을 한 번에 만든다.
            # `rolling(252)` 의 i 번째 창은 [i-251, i] 이고 `tail(252)` 는 [k-252, k-1] —
            # i=k-1 에서 같은 구간이다(값 동일성은 바이트 대조로 확인했다).
            cache = {
                "full": full,
                "close": full["close"].to_numpy(),
                "high": full["high"].to_numpy(),
                "low": full["low"].to_numpy(),
                "volume": full["volume"].to_numpy(),
                "w52h": full["high"].rolling(252, min_periods=1).max().to_numpy(),
                "w52l": full["low"].rolling(252, min_periods=1).min().to_numpy(),
                # 인과 지표 캐시 (P1-1) — `kis_indicators._causal` 이 이 표식을 본다.
                "memo": {},
            }
            self._fetch_frames[ticker] = cache

        k = len(df_slice)
        if k == 0:
            return None
        i = k - 1
        df_copy = cache["full"].iloc[:k]
        # `.iloc` 이 attrs 를 전파하지 않는 pandas 버전이 있어 방어적으로 채운다
        # (수급 토큰이 종목을 못 찾으면 조용히 다른 값이 나온다).
        if not df_copy.attrs.get("ticker"):
            df_copy.attrs["ticker"] = cache["full"].attrs.get("ticker", ticker)
        # 인과 지표 캐시를 붙인다 (P1-1). 라이브 경로의 DataFrame 에는 이 표식이 없으므로
        # 지표 함수들이 기존 경로를 그대로 탄다.
        from src.kis_indicators import _BT_CACHE_ATTR
        df_copy.attrs[_BT_CACHE_ATTR] = cache

        price_info = {
            "price": int(cache["close"][i]),
            "change": 0, "change_rate": 0.0,
            "high": int(cache["high"][i]), "low": int(cache["low"][i]),
            "volume": int(cache["volume"][i]),
            "w52_high": int(cache["w52h"][i]),
            "w52_low": int(cache["w52l"][i]),
        }

        # ★전역을 덮어쓰지 않는다 (P0-1)★
        # 예전에는 `fetcher.get_daily_prices = lambda …` 로 **모듈 전역**을 대입하고
        # finally 에서 "진입 시점의 값" 으로 되돌렸다. 그 값이 이미 다른 스레드의
        # 람다일 수 있어, 동시 실행이 서로의 데이터를 읽고 두 실행이 끝난 뒤에도
        # 전역이 오염된 채 남았다(실측: `scripts/bench_backtest.py --race`).
        # ContextVar 는 스레드마다 별개이고 토큰으로 정확히 복원된다.
        # 람다가 하던 일(인자를 무시하고 이 봉을 돌려준다)은 그대로다 — 결과 불변.
        token = fetcher.push_bar_context(df_copy, price_info)
        try:
            return strategy.generate_signal(ticker, ticker)
        except Exception as e:
            logger.debug(f"Signal error {ticker}: {e}")
            return None
        finally:
            fetcher.pop_bar_context(token)

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
                    fills.append((self._entry_px(p, open_), w))
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
        """주식 슬리브 매수 가용 현금.

        자산배분 ETF 바스켓 활성 시: 주식 슬리브 = equity×stock_pct/100 한도(잔여는
        ETF·현금 슬리브 몫). 단순 현금 비중(cash_reserve_pct)은 그 일반화의 특수형."""
        eq = getattr(self, "_equity_today", 0.0)
        aa = self.cfg.asset_alloc
        if aa and aa.get("basket"):
            stock_cap = eq * float(aa.get("stock_pct", 100)) / 100.0
            etf_val = self._etf_value()
            # 주식 슬리브가 쓸 수 있는 현금 = min(보유현금 - ETF몫 보존, 주식상한 - 현 주식가치)
            stock_val = max(0.0, eq - self.cash - etf_val)
            room = max(0.0, stock_cap - stock_val)
            return max(0.0, min(self.cash - etf_val, room))
        if self.cfg.cash_reserve_pct > 0:
            reserve = eq * self.cfg.cash_reserve_pct / 100.0
            return max(0.0, self.cash - reserve)
        return self.cash

    def _etf_value(self, etf_map: dict | None = None,
                   sim_date: pd.Timestamp | None = None) -> float:
        """ETF 슬리브 평가액. etf_map·sim_date 미지정 시 마지막 평가가(_etf_last) 사용."""
        total = 0.0
        for tk, h in self._etf_pos.items():
            px = None
            if etf_map is not None and tk in etf_map and sim_date is not None:
                sub = etf_map[tk].loc[:sim_date]
                if not sub.empty:
                    px = float(sub["close"].iloc[-1])
            if px is None:
                px = h.get("last", h.get("avg", 0.0))
            else:
                h["last"] = px
            total += h["qty"] * px
        return total

    def _etf_rebalance_days(self, sim_dates) -> set:
        """ETF 리밸런싱일 — N개월마다 각 월의 첫 거래일 (시작월 포함)."""
        months = max(1, int((self.cfg.asset_alloc or {}).get("rebalance_months", 3)))
        out, seen = set(), {}
        for d in sim_dates:
            ym = (d.year, d.month)
            if ym not in seen:
                seen[ym] = d  # 각 월 첫 거래일
        ordered = sorted(seen.values())
        for i, d in enumerate(ordered):
            if i % months == 0:
                out.add(d)
        # 시작일이 첫 월 첫 거래일이 아니어도 최초 1회는 배분 (시작 시점 진입)
        if len(sim_dates):
            out.add(sim_dates[0])
        return out

    def _rebalance_etf(self, etf_map: dict, sim_date, date_str: str):
        """ETF 바스켓을 목표 비중으로 정렬 — 목표 = equity×etf_pct/100 × leg_weight/100.

        보수: 매수 기준가(±오프셋) 미도달분은 이번 주기 미체결(다음 주기 재시도).
        ETF는 슬리피지·수수료 동일 적용, 별도 _etf_pos에 보유(주식 포지션과 무관)."""
        aa = self.cfg.asset_alloc or {}
        eq = getattr(self, "_equity_today", 0.0) or self._calc_equity({}, sim_date, etf_map)
        etf_pct = float(aa.get("etf_pct", 0)) / 100.0
        basket = aa.get("basket") or []
        wsum = sum(float(b.get("weight_pct") or 0) for b in basket) or 1.0
        fill_type = aa.get("fill_type", "close")
        offset = float(aa.get("offset_pct", 0) or 0)
        for leg in basket:
            tk = str(leg.get("ticker") or "").strip()
            if tk not in etf_map:
                continue
            sub = etf_map[tk].loc[:sim_date]
            if sub.empty:
                continue
            target_val = eq * etf_pct * (float(leg.get("weight_pct") or 0) / wsum)
            base = resolve_fill_price_safe(fill_type, sub)
            px = base * (1 + offset / 100.0) if offset else base
            if not px or px <= 0:
                continue
            held = self._etf_pos.get(tk, {"qty": 0, "avg": 0.0})
            cur_val = held["qty"] * px
            diff = target_val - cur_val
            if abs(diff) < px:  # 1주 미만 차이는 무시
                held["last"] = px
                self._etf_pos[tk] = held
                continue
            if diff > 0:  # 매수
                buy_px = px * (1 + self.cfg.slippage_rate)
                qty = int(min(diff, self.cash) / buy_px)
                if qty <= 0:
                    continue
                value = qty * buy_px
                commission = value * self.cfg.commission_rate
                if value + commission > self.cash:
                    continue
                self.cash -= (value + commission)
                new_qty = held["qty"] + qty
                held["avg"] = (held["avg"] * held["qty"] + buy_px * qty) / new_qty
                held["qty"] = new_qty
                held["last"] = px
                self._etf_pos[tk] = held
                self.trades.append(Trade(
                    date=date_str, ticker=tk, side="buy", price=buy_px, quantity=qty,
                    value=value, commission=commission, slippage=value * self.cfg.slippage_rate,
                    reason="ETF 자산배분 리밸런싱"))
            else:  # 매도 (목표 초과분)
                sell_px = px * (1 - self.cfg.slippage_rate)
                qty = min(held["qty"], int(-diff / sell_px))
                if qty <= 0:
                    continue
                value = qty * sell_px
                commission = value * self.cfg.commission_rate
                self.cash += (value - commission)
                pnl = value - commission - qty * held["avg"]
                held["qty"] -= qty
                held["last"] = px
                if held["qty"] <= 0:
                    self._etf_pos.pop(tk, None)
                else:
                    self._etf_pos[tk] = held
                self.trades.append(Trade(
                    date=date_str, ticker=tk, side="sell", price=sell_px, quantity=qty,
                    value=value, commission=commission, slippage=value * self.cfg.slippage_rate,
                    pnl=pnl, reason="ETF 자산배분 리밸런싱"))

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
            return self._entry_px(p, open_) if low <= p else None
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
                return self._entry_px(p, first_open) if float(w["low"].min()) <= p else None
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
        """돌파매수 체결가 — 기준가(유형 선택)×(1±오프셋%)의 돌파 라인 도달 시 진입.

        상방: 당일 고가 ≥ 라인 → max(시가, 라인) — 갭상승이면 시가 체결.
        양방: 상방 또는 하방(저가 ≤ base×(1-|off|)) — 둘 다 도달 시 상방 우선(보수:
        더 비싼 체결가). 기본(전일고가·0%·상방) = 기존 동작과 동일."""
        try:
            if df_slice is None or len(df_slice) < 2:
                return None
            from src.engine.fill_price import resolve_from_slice
            base = resolve_from_slice(self.cfg.breakthrough_base_type or "prev_high", df_slice)
            if not base or base <= 0:
                return None
            off = abs(self.cfg.breakthrough_offset_pct) / 100.0
            today_high = float(df_slice["high"].iloc[-1])
            today_low = float(df_slice["low"].iloc[-1])
            today_open = float(df_slice["open"].iloc[-1])
            up_line = base * (1 + off)
            if today_high >= up_line:
                return max(today_open, up_line)
            if self.cfg.breakthrough_direction == "both":
                dn_line = base * (1 - off)
                if today_low <= dn_line:
                    return self._entry_px(dn_line, today_open)  # 하방 돌파 매수 (낙폭 진입)
            return None
        except Exception:
            return None

    def _entry_px(self, limit: float, open_: float) -> float:
        """매수 지정가 체결가 — 장중 주문(intraday)이면 시가 갭 혜택 배제(보수)."""
        if self.cfg.buy_timing == "intraday":
            return limit
        return min(limit, open_)

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

    def _replenish_slots(self, ohlcv_map: dict, sim_date, date_str: str, market_on: bool):
        """동적 재편입 — 빈 슬롯을 그날 즉시 모멘텀점수 랭킹 상위 미보유 종목으로 채운다.

        어떤 이유로든(순위이탈·손익절·보유만기·신호매도 등) 슬롯이 열리면 rebalance_period와
        무관하게 항상 실행된다(사용자 확정). _process_buy를 거치지 않고 직접 _execute_buy를
        호출 — 돌파매수·래더는 '시그널' 개념이라 포트폴리오 슬롯 보충과 성격이 다르다.
        마켓타이밍 리스크오프(market_on=False)는 다른 신규 매수와 동일하게 존중한다.
        """
        if not (self.cfg.dynamic_replenishment and self._repl_panel is not None
                and self.cfg.replenishment_pool):
            return
        if not market_on:
            return
        open_slots = self.cfg.max_positions - len(self.positions)
        if open_slots <= 0:
            return
        if date_str not in self._repl_panel.index:
            return

        row = self._repl_panel.loc[date_str]
        candidates: list[tuple[float, str]] = []
        for ticker in self.cfg.replenishment_pool:
            if ticker in self.positions or ticker not in ohlcv_map:
                continue
            if self.cfg.rebuy_block_days > 0:
                last = self._last_exit.get(ticker)
                if last is not None and self._days_held(last, date_str) <= self.cfg.rebuy_block_days:
                    continue
            score = row.get(ticker) if ticker in row.index else None
            if score is None or pd.isna(score):
                continue
            candidates.append((float(score), ticker))
        if not candidates:
            return
        candidates.sort(key=lambda x: (-x[0], x[1]))  # 점수 내림차순, 동률은 종목코드로 결정적

        # buy_weight_mode="factor"용 — 재편입 후보풀 내에서 0~1 min-max 정규화(초기선정과
        # 동일한 정규화 방식). 범위 밖 종목이 암묵적으로 동일가중 폴백되던 불일치를 해소.
        scores_only = [s for s, _ in candidates]
        lo, hi = min(scores_only), max(scores_only)
        rng = hi - lo

        bought = 0
        for score, ticker in candidates:
            if bought >= open_slots:
                break
            df_slice = ohlcv_map[ticker].loc[:sim_date]
            if df_slice.empty:
                continue
            buy_price = self._fill_with_offset("buy", df_slice)
            if buy_price is None and self.cfg.buy_fill_offset_pct:
                continue  # 지정가 미도달 — 그날 미체결
            close_price = float(df_slice["close"].iloc[-1])
            fw = ((score - lo) / rng if rng > 0 else 0.5) if self.cfg.buy_weight_mode == "factor" else None
            before = len(self.positions)
            self._execute_buy(ticker, buy_price or close_price, date_str,
                              "동적 재편입 — 모멘텀점수(가격+수급) 기준, 재무 미반영",
                              factor_weight=fw)
            if len(self.positions) > before:
                bought += 1

    def _rebalance_prune(self, ohlcv_map: dict, sim_date, date_str: str, rebalance_days):
        """정기 리밸런싱 순위이탈 정리 — rebalance_period 첫 거래일에만 실행.

        보유종목+재편입후보풀을 모멘텀점수로 재랭킹해 상위 max_positions 밖으로 밀려난
        '보유종목만' 매도(상위권 보유종목은 그대로 유지 — 전량 리셋 아님). 랭킹 근거가 없는
        (패널에 값 없는) 보유종목은 정리 대상에서 제외(정직 — 판단 근거 없으면 보수적 유지).
        생긴 빈자리는 같은 날 뒤이어 실행되는 _replenish_slots가 자동으로 채운다.
        """
        if rebalance_days is None or sim_date not in rebalance_days:
            return
        if not (self.cfg.dynamic_replenishment and self._repl_panel is not None
                and self.cfg.replenishment_pool and self.positions):
            return
        if date_str not in self._repl_panel.index:
            return

        row = self._repl_panel.loc[date_str]
        pool = set(self.cfg.replenishment_pool) | set(self.positions.keys())
        ranked: list[tuple[float, str]] = []
        for ticker in pool:
            score = row.get(ticker) if ticker in row.index else None
            if score is None or pd.isna(score):
                continue
            ranked.append((float(score), ticker))
        if not ranked:
            return
        ranked.sort(key=lambda x: (-x[0], x[1]))
        top_n = {tk for _, tk in ranked[: self.cfg.max_positions]}
        ranked_tickers = {tk for _, tk in ranked}

        for ticker in list(self.positions.keys()):
            if ticker not in ranked_tickers or ticker in top_n:
                continue  # 랭킹 불가 또는 상위권 → 유지
            if ticker not in ohlcv_map:
                continue
            pos = self.positions[ticker]
            if self._days_held(pos.entry_date, date_str) < self.cfg.min_hold_days:
                continue
            df_to_date = ohlcv_map[ticker].loc[:sim_date]
            if df_to_date.empty:
                continue
            sell_price = self._fill_with_offset("sell", df_to_date)
            close_price = float(df_to_date["close"].iloc[-1])
            self._execute_sell(ticker, sell_price or close_price, date_str, "리밸런싱 순위이탈 매도")

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
        """정기 리밸런싱: 주/월/분기/반기/연 첫 거래일 집합. None이면 게이트 없음(매일 신규 매수 가능)."""
        period = (self.cfg.rebalance_period or "").lower()
        if period not in ("weekly", "monthly", "quarterly", "semiannual", "annual"):
            return None
        days: set = set()
        seen: set = set()
        for d in sim_dates:
            if period == "weekly":
                iso = d.isocalendar()
                key = (iso[0], iso[1])
            elif period == "monthly":
                key = (d.year, d.month)
            elif period == "quarterly":
                key = (d.year, (d.month - 1) // 3)
            elif period == "semiannual":
                key = (d.year, (d.month - 1) // 6)
            else:  # annual
                key = (d.year,)
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

    def _calc_equity(self, ohlcv_map: dict, sim_date: pd.Timestamp,
                     etf_map: dict | None = None) -> float:
        """현재 포트폴리오 가치 — 현금 + 주식 슬리브 + ETF 슬리브."""
        equity = self.cash
        for ticker, pos in self.positions.items():
            if ticker in ohlcv_map:
                df_to = ohlcv_map[ticker].loc[:sim_date]
                if not df_to.empty:
                    equity += pos.quantity * float(df_to["close"].iloc[-1])
        if self._etf_pos:
            equity += self._etf_value(etf_map, sim_date)
        return equity

    def _build_result(self, duration: float, ohlcv_map: dict,
                      etf_map: dict | None = None) -> dict:
        """ResultFormatter.to_api_response()와 동일한 구조 반환."""
        if not self.equity_history:
            return self._error_response("No simulation data produced")

        dates = [e[0] for e in self.equity_history]
        equity_values = [e[1] for e in self.equity_history]

        eq_series = pd.Series(equity_values, index=pd.to_datetime(dates))
        returns = eq_series.pct_change().dropna()

        # 벤치마크(코스피) 대비 — 동일 기간 매수후보유 곡선 + 초과수익/베타/알파.
        # 정보비율(IR) 계산에 벤치마크 기간수익률이 필요하므로 통계보다 먼저 산출.
        benchmark = self._compute_benchmark(dates, equity_values, returns)
        bench_curve = benchmark.get("curve") if benchmark else None
        bench_rets = None
        if bench_curve and len(bench_curve) > 1:
            bench_rets = pd.Series(bench_curve, dtype=float).pct_change().dropna().tolist()

        stats = _compute_statistics(
            eq_series, returns, self.trades, self.cfg.initial_capital,
            benchmark_returns=bench_rets,
        )
        stats["eod_liquidated"] = getattr(self, "_eod_liquidated", 0)
        drawdown = _compute_drawdown(eq_series)
        monthly_returns = _compute_monthly_returns(returns)
        trade_dicts = [self._trade_to_dict(t) for t in self.trades]
        symbol_results = _compute_symbol_results(self.trades, self.cfg.symbols)

        # 하이브리드 체결 통계 (정직: 분봉 적용/일봉 폴백 비율 공개)
        intraday_meta = None
        if self.cfg.intraday_fill:
            tot = self._intraday["applied"] + self._intraday["fallback"]
            intraday_meta = {**self._intraday,
                             "applied_pct": round(self._intraday["applied"] / tot * 100, 1) if tot else 0.0}

        # 자산배분 ETF 슬리브 최종 구성 (정직: 실제 달성 비중 공개)
        alloc_meta = None
        if self.cfg.asset_alloc and self._etf_pos:
            last_eq = self.equity_history[-1][1] if self.equity_history else 0.0
            etf_val = self._etf_value(etf_map, None)
            alloc_meta = {
                "etf_value": round(etf_val),
                "etf_pct_actual": round(etf_val / last_eq * 100, 1) if last_eq else 0.0,
                "holdings": [{"ticker": tk, "qty": h["qty"], "avg": round(h["avg"], 1)}
                             for tk, h in self._etf_pos.items()],
            }

        return {
            "currency": "KRW",
            "intraday": intraday_meta,
            "asset_alloc": alloc_meta,
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
                "round_trips": _round_trips(self.trades)[:500],
                "trade_mode": "per_trade",
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
                # 동적 재편입 활성 시 실제 거래 가능한 유니버스는 symbols(초기 보유) +
                # replenishment_pool(재편입 후보) 합집합 — 재편입으로 편입된 종목도 반영.
                "symbols_used": len(set(self.cfg.symbols) | set(self.cfg.replenishment_pool or [])),
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
    benchmark_returns: list | None = None,
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

    base = {
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

    # QuantStats 표준 보강 지표 병합 (신규 키만 추가, 기존 키는 base 우선)
    extra = compute_metrics(
        returns, equity, periods_per_year=252,
        trades_pnl=[t.pnl for t in sell_trades],
        benchmark_returns=benchmark_returns,
        risk_free=risk_free_rate,
    )
    return {**extra, **base}


def _compute_drawdown(equity: pd.Series) -> pd.Series:
    rolling_max = equity.cummax()
    return (equity - rolling_max) / rolling_max


def _round_trips(trades: list[Trade]) -> list[dict]:
    """매수/매도 leg을 종목별 FIFO로 매칭해 라운드트립(체결 쌍) 리스트 생성.

    매도 leg 하나당 한 행. 소비한 매수 lot들의 가중평균 단가를 진입가로,
    진입일은 가장 이른 매수일로 한다. 부분매도·추가매수도 수량 기준 정확 매칭.
    프론트 거래로그가 기대하는 라운드트립 스키마(entry/exit/return_pct)를 제공
    — leg 포맷(result.trades)과는 별도 필드(result.round_trips).
    """
    from collections import defaultdict, deque

    from src.data.stock_master import get_stock_name

    lots: dict[str, deque] = defaultdict(deque)  # ticker → 미청산 매수 lot 큐
    out: list[dict] = []
    for t in trades:
        if t.side == "buy":
            lots[t.ticker].append({"date": t.date, "price": t.price, "qty": t.quantity})
            continue
        # 매도 leg → 앞에서부터 매수 lot 소비(FIFO)
        dq = lots[t.ticker]
        remaining, matched, cost_sum = t.quantity, 0, 0.0
        entry_date, first = t.date, True
        while remaining > 0 and dq:
            lot = dq[0]
            take = min(remaining, lot["qty"])
            if first:
                entry_date, first = lot["date"], False
            cost_sum += take * lot["price"]
            matched += take
            lot["qty"] -= take
            remaining -= take
            if lot["qty"] <= 0:
                dq.popleft()
        entry_price = (cost_sum / matched) if matched > 0 else t.price
        ret_pct = ((t.price / entry_price - 1) * 100) if entry_price > 0 else 0.0
        out.append({
            "stock_code": t.ticker,
            "corp_name": get_stock_name(t.ticker) or t.ticker,
            "entry_date": entry_date,
            "exit_date": t.date,
            "entry_price": round(entry_price, 2),
            "exit_price": round(t.price, 2),
            "quantity": t.quantity,
            "return_pct": round(ret_pct, 2),
            "pnl": round(t.pnl, 0) if t.pnl is not None else None,
            "reason": t.reason,
        })
    return out


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
    """종목별 성과 — 라운드트립 기반 (실현손익/평균수익률/평균보유일/기여도 포함)."""
    from datetime import datetime as _dt

    from src.data.stock_master import get_stock_name

    rts = _round_trips(trades)
    by_sym: dict[str, list[dict]] = {s: [] for s in symbols}
    for rt in rts:
        by_sym.setdefault(rt["stock_code"], []).append(rt)
    buy_amount: dict[str, float] = {}
    for t in trades:
        if t.side == "buy":
            buy_amount[t.ticker] = buy_amount.get(t.ticker, 0.0) + t.value

    def _days(rt) -> float:
        try:
            d0 = _dt.strptime(rt["entry_date"][:10], "%Y-%m-%d")
            d1 = _dt.strptime(rt["exit_date"][:10], "%Y-%m-%d")
            return max(0.0, float((d1 - d0).days))
        except Exception:
            return 0.0

    total_pnl = sum((rt["pnl"] or 0.0) for rt in rts)
    results = []
    for ticker, lst in by_sym.items():
        n = len(lst)
        pnl = sum((rt["pnl"] or 0.0) for rt in lst)
        wins = sum(1 for rt in lst if (rt["pnl"] or 0.0) > 0)
        ba = buy_amount.get(ticker, 0.0)
        results.append({
            "symbol": ticker,
            "corp_name": get_stock_name(ticker) or ticker,
            "total_return_pct": round(pnl / ba * 100, 2) if ba > 0 else 0.0,
            "num_trades": sum(1 for t in trades if t.ticker == ticker),
            "round_trips": n,
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "realized_pnl": round(pnl, 0),
            "avg_return_pct": round(sum(rt["return_pct"] for rt in lst) / n, 2) if n else 0.0,
            "avg_hold_days": round(sum(_days(rt) for rt in lst) / n, 1) if n else 0.0,
            "contribution_pct": round(pnl / total_pnl * 100, 1) if total_pnl else 0.0,
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
    asset_alloc: dict | None = None,
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
    breakthrough_base_type: str = "prev_high",
    breakthrough_offset_pct: float = 0.0,
    breakthrough_direction: str = "up",
    buy_timing: str = "pre_open",
    progress_cb=None,
    liquidate_at_end: bool = True,
    dynamic_replenishment: bool = True,
    replenishment_pool: list[str] | None = None,
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
        liquidate_at_end=liquidate_at_end,
        buy_fill_offset_pct=buy_fill_offset_pct,
        sell_fill_offset_pct=sell_fill_offset_pct,
        max_buy_amount=max_buy_amount,
        cash_reserve_pct=cash_reserve_pct,
        asset_alloc=asset_alloc,
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
        breakthrough_base_type=breakthrough_base_type,
        breakthrough_offset_pct=breakthrough_offset_pct,
        breakthrough_direction=breakthrough_direction,
        buy_timing=buy_timing,
        dynamic_replenishment=dynamic_replenishment,
        replenishment_pool=replenishment_pool,
    )
    engine = BacktestEngine(cfg, progress_cb=progress_cb)
    return engine.run()
