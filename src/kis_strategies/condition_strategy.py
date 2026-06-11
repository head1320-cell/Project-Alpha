# 대상 경로: src/kis_strategies/condition_strategy.py
#
# 조건식 전략 (Genport식) — 매수/매도 조건(팩터식)을 봉마다 평가해 진입/청산 시그널 생성.
#
# 엔진(kis_backtest_engine)이 fetcher.get_daily_prices 를 종목별 OHLCV 슬라이스로
# monkey-patch 하므로(look-ahead 방지), 이 전략은 그 슬라이스에서 팩터식을 계산한다.
#
# 지원 범위: 가격·거래량·기술 기반 팩터(시/고/저/종가, 거래량, 거래대금)와 18개 함수
# (기본/과거값/이동평균/최고값/최저값/변화량_기간/변화율_기간/절대값/기간총합/비교/큰값/
#  작은값/큰개수/작은개수/평균모멘텀스코어/표준편차). 비율·순위(횡단면)와 펀더멘털·점수·뉴지
# 팩터는 봉별 단일종목 데이터로 평가 불가 → 무시(스크리닝 filter_ast 로 분리하는 게 맞음).
# 평가 불가 조건은 건너뛴다(매수는 평가 가능한 조건이 하나도 없으면 진입하지 않음).

from __future__ import annotations

import pandas as pd

from src import kis_data_fetcher as data_fetcher
from src.kis_signal import Action, Signal
from src.kis_strategies.strategies import STRATEGY_REGISTRY, BaseStrategy

# ── 팩터 토큰 → OHLCV 베이스 시리즈 ────────────────────────────
_PRICE_COL = {
    "종가": "close", "현재가": "close", "주가": "close",
    "시가": "open", "고가": "high", "저가": "low", "거래량": "volume",
}


def _base_series(df: pd.DataFrame, token: str) -> pd.Series | None:
    name = (token or "").strip().strip("{}").strip()
    col = _PRICE_COL.get(name)
    if col is not None:
        return df[col].astype(float)
    if name in ("거래대금",):
        return df["close"].astype(float) * df["volume"].astype(float)
    # 확장 토큰: ① OHLCV 파생(RSI/MACD 등) ② 시장 지수(KOSPI지수_종가·베타 등)
    #            ③ 매크로(환율·금리 — ECOS/FRED) ④ 수급(투자자별 — KIS 적재)
    from src.kis_strategies.factor_tokens import (
        resolve_flow_token,
        resolve_macro_token,
        resolve_market_token,
        resolve_ohlcv_token,
    )
    for resolver in (resolve_ohlcv_token, resolve_market_token, resolve_macro_token,
                     resolve_flow_token):
        s = resolver(df, name)
        if s is not None:
            return s
    return None  # 뉴지 점수·세부 수급 주체 등 — 미지원(건너뜀)


# ── 펀더멘털 토큰(스냅샷) — #4. 기본 비활성(look-ahead). 활성 시 현재 스냅샷을 상수 시계열로 평가 ──
def _safe_div(a, b):
    try:
        a = float(a); b = float(b)
        return a / b if b not in (0, 0.0) else None
    except Exception:
        return None


_FUND_TOKENS = {
    "시가총액": lambda f: f.get("market_cap"),
    "시총": lambda f: f.get("market_cap"),
    "PER": lambda f: _safe_div(f.get("market_cap"), f.get("net_income")),
    "PBR": lambda f: _safe_div(f.get("market_cap"), f.get("total_equity")),
    "PSR": lambda f: _safe_div(f.get("market_cap"), f.get("revenue")),
    "PCR": lambda f: f.get("pcr") if f.get("pcr") is not None else _safe_div(f.get("market_cap"), f.get("operating_cf")),
    "ROE": lambda f: ((_safe_div(f.get("net_income"), f.get("total_equity")) or 0) * 100) if f.get("total_equity") else None,
    "EPS": lambda f: f.get("eps") if f.get("eps") is not None else _safe_div(f.get("net_income"), f.get("shares")),
    "매출액": lambda f: f.get("revenue"),
    "영업이익": lambda f: f.get("operating_profit"),
    "순이익": lambda f: f.get("net_income"),
    "부채비율": lambda f: ((_safe_div(f.get("total_liabilities"), f.get("total_equity")) or 0) * 100) if f.get("total_equity") else None,
    "매출액증가율": lambda f: (f.get("revenue_cagr_3y") * 100) if f.get("revenue_cagr_3y") is not None else None,
    "PEG": lambda f: f.get("peg"),
}


def _fundamental_value(token: str, f: dict):
    name = (token or "").strip().strip("{}").strip()
    fn = _FUND_TOKENS.get(name)
    if fn is not None:
        try:
            v = fn(f or {})
            return float(v) if v is not None else None
        except Exception:
            return None
    # 카탈로그 별칭 → fundamentals_store 팩터 id (분기PBR→pbr 등 — 최신 스냅샷 근사)
    try:
        from src.kis_strategies.factor_tokens import FUNDAMENTAL_ALIASES
        fid = FUNDAMENTAL_ALIASES.get(name)
        if fid is not None:
            v = (f or {}).get(fid)
            return float(v) if v is not None else None
    except Exception:
        pass
    return None


def _load_fundamentals(stock_code: str) -> dict:
    try:
        from src.data.fundamentals_store import FundamentalsStore
        return FundamentalsStore.get_default().get_factors(stock_code) or {}
    except Exception:
        return {}


# ── 18개 함수 적용 ────────────────────────────────────────────
def _apply_function(s: pd.Series, fn: str, p: dict) -> pd.Series | None:
    def _n(default: int = 20) -> int:
        try:
            return max(1, int(float(p.get("n", default))))
        except Exception:
            return default

    def _v(default: float = 0.0) -> float:
        try:
            return float(p.get("v", default))
        except Exception:
            return default

    if fn == "base":
        return s
    if fn == "past":
        return s.shift(_n(1))
    if fn == "ma":
        return s.rolling(_n()).mean()
    if fn == "max":
        return s.rolling(_n()).max()
    if fn == "min":
        return s.rolling(_n()).min()
    if fn == "delta":
        return s - s.shift(_n(1))
    if fn == "pct":
        return s.pct_change(_n(1)) * 100.0
    if fn == "abs":
        return s.abs()
    if fn == "sum":
        return s.rolling(_n()).sum()
    if fn == "cmp":
        x = _v()
        return s.sub(x).apply(lambda d: 1.0 if d > 0 else (-1.0 if d < 0 else 0.0))
    if fn == "gt":
        return s.clip(lower=_v())
    if fn == "lt":
        return s.clip(upper=_v())
    if fn == "cntgt":
        return (s > _v()).rolling(_n()).sum()
    if fn == "cntlt":
        return (s < _v()).rolling(_n()).sum()
    if fn == "std":
        return s.rolling(_n()).std()
    if fn == "ams":  # 평균모멘텀스코어: 최근값이 1~N일 전보다 컸던 비율(%)
        N = _n()
        parts = [(s > s.shift(k)).astype(float) for k in range(1, N + 1)]
        if not parts:
            return None
        return sum(parts) / float(N) * 100.0
    if fn in ("ratio", "rank"):
        return None  # 횡단면(전체 종목) — 봉별 단일종목에서 평가 불가
    return None


def _apply_inner(s: pd.Series, cond: dict) -> pd.Series | None:
    """내부 함수(중첩) 적용 — 예: 순위(변화율_기간(종가,20)) 의 변화율_기간 부분.

    inner_function_id 가 없으면 원 시리즈 그대로. 횡단면 함수(rank/ratio)는
    내부 지표로 쓸 수 없음(None → 조건 건너뜀)."""
    inner = (cond.get("inner_function_id") or "").strip()
    if not inner or inner == "base":
        return s
    if inner in ("rank", "ratio"):
        return None
    return _apply_function(s, inner, cond.get("inner_params") or {})


# ── 단일 조건 평가 → True / False / None(평가 불가) ───────────
def _eval_condition(df: pd.DataFrame, cond: dict, fundamentals: dict | None = None) -> bool | None:
    s = _base_series(df, cond.get("factor_token", ""))
    if (s is None or len(s) == 0) and fundamentals is not None:
        fv = _fundamental_value(cond.get("factor_token", ""), fundamentals)
        if fv is not None:
            s = pd.Series([fv] * len(df), index=df.index)
    if s is None or len(s) == 0:
        return None
    s = _apply_inner(s, cond)
    if s is None or len(s) == 0:
        return None
    series = _apply_function(s, cond.get("function_id", "base"), cond.get("params") or {})
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    lhs = float(val)
    op = cond.get("op", "gte")
    try:
        rhs = float(cond.get("rhs"))
    except Exception:
        return None
    if op == "gte":
        return lhs >= rhs
    if op == "lte":
        return lhs <= rhs
    if op == "eq":
        return abs(lhs - rhs) < 1e-9
    if op == "between":
        try:
            rhs2 = float(cond.get("rhs2"))
        except Exception:
            return None
        lo, hi = (rhs, rhs2) if rhs <= rhs2 else (rhs2, rhs)
        return lo <= lhs <= hi
    return None


def _compare(lhs: float, op: str, rhs, rhs2=None) -> bool | None:
    try:
        rhs = float(rhs)
    except Exception:
        return None
    if op == "gte":
        return lhs >= rhs
    if op == "lte":
        return lhs <= rhs
    if op == "eq":
        return abs(lhs - rhs) < 1e-9
    if op == "between":
        try:
            rhs2 = float(rhs2)
        except Exception:
            return None
        lo, hi = (rhs, rhs2) if rhs <= rhs2 else (rhs2, rhs)
        return lo <= lhs <= hi
    return None


def _max_period(conds: list[dict]) -> int:
    mx = 0
    for c in conds or []:
        for p in (c.get("params"), c.get("inner_params")):
            try:
                mx = max(mx, int(float((p or {}).get("n", 0))))
            except Exception:
                pass
    return mx


class ConditionStrategy(BaseStrategy):
    """매수/매도 조건식(팩터식) 기반 진입·청산 전략."""

    def __init__(self, buy_conditions: list[dict] | None = None,
                 sell_conditions: list[dict] | None = None,
                 allow_snapshot_fundamentals: bool = False, **_ignore):
        self.buy_conditions = list(buy_conditions or [])
        self.sell_conditions = list(sell_conditions or [])
        # #4: 펀더멘털 토큰을 봉별 평가에 포함(현재 스냅샷 상수). 기본 비활성 — 활성 시 look-ahead 근사.
        self.allow_snapshot_fundamentals = bool(allow_snapshot_fundamentals)
        self._panels: dict = {}  # 횡단면(순위/비율) 사전계산 {key: DataFrame[date,ticker]}

    @property
    def name(self) -> str:
        return "조건식 전략"

    @property
    def required_days(self) -> int:
        base = max(_max_period(self.buy_conditions), _max_period(self.sell_conditions)) + 30
        # 확장 토큰의 내재 룩백(예: 52주 신고가=252봉) 반영 — 워밍업 부족 시 조건이 NaN으로 무시됨
        try:
            from src.kis_strategies.factor_tokens import token_min_bars
            tok = max((token_min_bars(c.get("factor_token", ""))
                       for c in (self.buy_conditions + self.sell_conditions)), default=0)
        except Exception:
            tok = 0
        return max(base, tok + 10)

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df is None or df.empty or len(df) < 2:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        fund = _load_fundamentals(stock_code) if self.allow_snapshot_fundamentals else None
        as_of = str(df["date"].iloc[-1]) if "date" in df.columns else None

        def _ev(c: dict) -> bool | None:
            if c.get("function_id") in ("rank", "ratio"):
                return self._eval_cross(c, stock_code, as_of)
            return _eval_condition(df, c, fund)

        # 매도: 평가 가능한 조건 중 하나라도 충족 → 청산
        sell_eval = [b for b in (_ev(c) for c in self.sell_conditions) if b is not None]
        if sell_eval and any(sell_eval):
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7, reason="매도 조건 충족")

        # 매수: 평가 가능한 조건이 있고 전부 충족 → 진입
        buy_eval = [b for b in (_ev(c) for c in self.buy_conditions) if b is not None]
        if buy_eval and all(buy_eval):
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=0.7, reason="매수 조건 충족")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0, reason="조건 미충족")

    # ── 횡단면(순위/비율) ──────────────────────────────────────
    def _cross_key(self, cond: dict) -> str:
        p = cond.get("params") or {}
        ip = cond.get("inner_params") or {}
        return (f"{cond.get('factor_token','')}|{cond.get('function_id','')}|{p.get('dir','DESC')}"
                f"|{cond.get('inner_function_id','')}|{ip.get('n','')}|{ip.get('v','')}")

    def prepare_panel(self, ohlcv_map: dict) -> None:
        """순위/비율 함수용 패널 사전계산. 엔진이 봉 루프 전에 1회 호출(전 종목 동일시점 값 필요)."""
        self._panels = {}
        cross = [c for c in (self.buy_conditions + self.sell_conditions)
                 if c.get("function_id") in ("rank", "ratio")]
        if not cross or not ohlcv_map:
            return
        for cond in cross:
            key = self._cross_key(cond)
            if key in self._panels:
                continue
            token = cond.get("factor_token", "")
            cols: dict = {}
            for tk, odf in ohlcv_map.items():
                try:
                    s = _base_series(odf, token)
                    if s is None or len(s) == 0:
                        continue
                    # 내부 지표(중첩): 순위(변화율_기간(종가,20)) — 파생 시리즈를 랭킹 대상으로
                    s = _apply_inner(s, cond)
                    if s is None or len(s) == 0:
                        continue
                    idx = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in odf.index]
                    cols[str(tk)] = pd.Series(s.values, index=idx)
                except Exception:
                    continue
            if not cols:
                self._panels[key] = None
                continue
            wide = pd.DataFrame(cols)
            dirv = (cond.get("params") or {}).get("dir", "DESC")
            if cond.get("function_id") == "rank":
                # 순위: DESC → 큰 값이 1위
                self._panels[key] = wide.rank(axis=1, ascending=(dirv != "DESC"), method="min")
            else:  # 비율 → 0~100 (DESC → 큰 값이 100)
                self._panels[key] = wide.rank(axis=1, ascending=(dirv == "DESC"), pct=True) * 100.0

    def _eval_cross(self, cond: dict, ticker: str, as_of: str | None) -> bool | None:
        if as_of is None:
            return None
        panel = self._panels.get(self._cross_key(cond))
        if panel is None:
            return None
        try:
            val = panel.at[as_of, str(ticker)]
        except Exception:
            return None
        if val is None or pd.isna(val):
            return None
        return _compare(float(val), cond.get("op", "lte"), cond.get("rhs"), cond.get("rhs2"))


# 레지스트리 자기 등록 — 이 모듈이 import 되면 "Condition" 전략 사용 가능
STRATEGY_REGISTRY["Condition"] = ConditionStrategy
