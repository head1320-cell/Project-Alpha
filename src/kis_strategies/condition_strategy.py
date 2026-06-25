# 대상 경로: src/kis_strategies/condition_strategy.py
#
# 조건식 전략 (Genport식) — 매수/매도 조건(팩터식)을 봉마다 평가해 진입/청산 시그널 생성.
#
# 엔진(kis_backtest_engine)이 fetcher.get_daily_prices 를 종목별 OHLCV 슬라이스로
# monkey-patch 하므로(look-ahead 방지), 이 전략은 그 슬라이스에서 팩터식을 계산한다.
#
# 지원 범위: 가격·거래량·기술 팩터 + 시장·매크로·수급 토큰 + 점수 근사(score_factors)
# + 펀더멘털 스냅샷(옵트인). 함수 18종 + 두 팩터 변형(비교/큰값/작은값에 factor_token2,
# 변화율_팩터=pctf — ((F1-F2)/|F2|)×100, 두 번째 피연산자도 inner2 중첩 지원).
# 순위/비율(횡단면)·점수는 prepare_panel 사전계산 패널로 평가.
# 논리 조건식(buy_logic/sell_logic)은 condition_logic 참조 — 없으면 매수=AND, 매도=OR.
# 평가 불가 조건은 건너뛴다(매수는 평가 가능한 조건이 하나도 없으면 진입하지 않음).

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

from src import kis_data_fetcher as data_fetcher
from src.kis_signal import Action, Signal
from src.kis_strategies.condition_logic import eval_logic, max_lookback, parse_logic
from src.kis_strategies.factor_expr import (
    collect_cross,
    eval_expr,
    expr_lookback,
    expr_tokens,
    parse_expr,
)
from src.kis_strategies.score_factors import SCORE_MIN_BARS, SCORE_TOKENS, build_score_panels
from src.kis_strategies.strategies import STRATEGY_REGISTRY, BaseStrategy

logger = logging.getLogger(__name__)

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

# PIT(시점) 평가를 지원하는 펀더멘털 토큰 — financials_history 적재 시 봉별 시계열로 평가
# (look-ahead 없음). 매출액증가율·PEG는 단순 시계열화가 어려워 제외(적재돼도 스냅샷 폴백/건너뜀).
_PIT_FUND_TOKENS = {"시가총액", "시총", "PER", "PBR", "PSR", "PCR", "ROE",
                    "부채비율", "매출액", "영업이익", "순이익", "EPS"}
_PIT_UNBUILT = object()  # 종목별 PIT 패널 캐시 센티넬 (미빌드 구분)


def _fundamental_value(token: str, f: dict):
    name = (token or "").strip().strip("{}").strip()
    fn = _FUND_TOKENS.get(name)
    if fn is not None:
        try:
            v = fn(f or {})
            return float(v) if v is not None else None
        except Exception:
            return None
    # 별칭 → fundamentals dict 키 (수동 별칭 + 스토어 라벨 자동 별칭 — 분기PBR→pbr,
    # 분기매출→revenue(억), "QMJ 점수"→qmj_score 등. 최신 스냅샷 근사)
    try:
        from src.kis_strategies.factor_tokens import fundamental_field_for
        fid = fundamental_field_for(name)
        if fid is not None:
            v = (f or {}).get(fid)
            return float(v) if v is not None else None
    except Exception:
        pass
    return None


def _load_fundamentals(stock_code: str) -> dict:
    """파생 팩터(64) + 원천 재무(42, 억) + 시계열 파생(흑자전환·3년연속 등 19) 병합.

    raw 금액 토큰(매출액·시가총액)과 라벨 별칭, 시계열 토큰이 실경로에서
    평가되게 한다. 시계열은 financials_history 적재 시에만 값(없으면 None→건너뜀)."""
    try:
        from src.data.fundamentals_store import FundamentalsStore
        store = FundamentalsStore.get_default()
        factors = store.get_factors(stock_code) or {}
        raw = {}
        try:
            raw = store.get_raw_financials(stock_code) or {}
        except Exception:
            pass
        hist = {}
        try:
            from src.data.dart_history import history_factors
            hist = history_factors(stock_code) or {}
        except Exception:
            pass
        ext = {}
        try:
            from src.data.extended_factors_store import ExtendedFactorsStore
            ext = {k: v for k, v in ExtendedFactorsStore.get_default().get_factors(stock_code).items()
                   if not k.startswith("_")}
        except Exception:
            pass
        return {**raw, **hist, **factors, **ext}
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


def _apply_inner(s: pd.Series, cond: dict, prefix: str = "inner") -> pd.Series | None:
    """내부 함수(중첩) 적용 — 예: 순위(변화율_기간(종가,20)) 의 변화율_기간 부분.

    inner_function_id 가 없으면 원 시리즈 그대로. 횡단면 함수(rank/ratio)는
    내부 지표로 쓸 수 없음(None → 조건 건너뜀). prefix="inner2"면 두 번째
    피연산자(factor_token2)의 중첩 — 예: 변화율_팩터(당기순이익, 과거값(당기순이익,1년))."""
    inner = (cond.get(f"{prefix}_function_id") or "").strip()
    if not inner or inner == "base":
        return s
    if inner in ("rank", "ratio"):
        return None
    return _apply_function(s, inner, cond.get(f"{prefix}_params") or {})


# 두 팩터 함수 (가이드: 비교(F1,F2)·큰값(F1,F2)·작은값(F1,F2)·변화율_팩터(F1,F2))
_TWO_FACTOR_FNS = {"cmp", "gt", "lt", "pctf"}


def _apply_two_factor(s1: pd.Series, s2: pd.Series, fn: str) -> pd.Series | None:
    """두 피연산자 결합 — 비교=부호(1/0/-1), 큰값/작은값=원소별 max/min,
    변화율_팩터=((F1-F2)/|F2|)×100 (가이드 종가시초가대비율 정의 그대로)."""
    if fn == "cmp":
        d = s1 - s2
        return pd.Series(np.sign(d.to_numpy(dtype=float)), index=s1.index)
    if fn == "gt":
        return pd.concat([s1, s2], axis=1).max(axis=1)
    if fn == "lt":
        return pd.concat([s1, s2], axis=1).min(axis=1)
    if fn == "pctf":
        denom = s2.abs().replace(0.0, np.nan)
        return (s1 - s2) / denom * 100.0
    return None


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
    if op in ("cross_above", "cross_below"):
        if len(series) < 2 or pd.isna(series.iloc[-2]):
            return None
        pv = float(series.iloc[-2])
        return (lhs > rhs and pv <= rhs) if op == "cross_above" else (lhs < rhs and pv >= rhs)
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


def _vector_compare(vals: pd.Series, op: str, rhs, rhs2=None):
    """_eval_condition의 연산자 의미를 전 봉 벡터로 — (valid, ok) bool 배열.

    valid=평가 가능(NaN 아님), ok=valid & 충족. 연산자 불명·rhs 파싱 실패면 None."""
    import numpy as np
    try:
        rhs_f = float(rhs)
    except (TypeError, ValueError):
        return None
    v = pd.to_numeric(vals, errors="coerce")
    valid = v.notna().to_numpy()
    x = v.to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        if op == "gte":
            ok = x >= rhs_f
        elif op == "lte":
            ok = x <= rhs_f
        elif op == "eq":
            ok = np.abs(x - rhs_f) < 1e-9
        elif op == "between":
            try:
                rhs2_f = float(rhs2)
            except (TypeError, ValueError):
                return None
            lo, hi = (rhs_f, rhs2_f) if rhs_f <= rhs2_f else (rhs2_f, rhs_f)
            ok = (x >= lo) & (x <= hi)
        elif op in ("cross_above", "cross_below"):
            # 상향/하향 돌파: 직전 봉은 반대편, 현재 봉이 기준선(rhs)을 넘김(=신호 봉만 True).
            xp = v.shift(1).to_numpy(dtype=float)
            valid = valid & v.shift(1).notna().to_numpy()   # 직전 봉도 유효해야 판정
            ok = (((x > rhs_f) & (xp <= rhs_f)) if op == "cross_above"
                  else ((x < rhs_f) & (xp >= rhs_f)))
        else:
            return None
    return valid, (ok & valid)


def _max_period(conds: list[dict]) -> int:
    mx = 0
    for c in conds or []:
        for p in (c.get("params"), c.get("inner_params"), c.get("inner2_params")):
            try:
                mx = max(mx, int(float((p or {}).get("n", 0))))
            except Exception:
                pass
    return mx


def _date_keys(df: pd.DataFrame) -> list[str]:
    """봉별 YYYY-MM-DD 키 — 패널(횡단면) 조회용. DatetimeIndex와
    per-bar 엔진 슬라이스('date' 컬럼 YYYYMMDD) 양쪽 포맷 지원."""
    if "date" in df.columns:
        out = []
        for d in df["date"].astype(str):
            d = d.strip()
            out.append(f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.isdigit() else d)
        return out
    return [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df.index]


class ConditionStrategy(BaseStrategy):
    """매수/매도 조건식(팩터식) 기반 진입·청산 전략."""

    def __init__(self, buy_conditions: list[dict] | None = None,
                 sell_conditions: list[dict] | None = None,
                 allow_snapshot_fundamentals: bool = False,
                 buy_logic: str | None = None, sell_logic: str | None = None,
                 **_ignore):
        self.buy_conditions = list(buy_conditions or [])
        self.sell_conditions = list(sell_conditions or [])
        # #4: 펀더멘털 토큰을 봉별 평가에 포함(현재 스냅샷 상수). 기본 비활성 — 활성 시 look-ahead 근사.
        self.allow_snapshot_fundamentals = bool(allow_snapshot_fundamentals)
        # 논리 조건식 (젠포트 논리 레이어): "every(A,3) and (B or C)" 등.
        # 비우면 기존 정책(매수=전부 AND, 매도=하나라도 OR) 그대로.
        # 문법·라벨 오류는 여기서 ValueError → API가 400(입력 오류)으로 안내.
        self.buy_logic = (buy_logic or "").strip() or None
        self.sell_logic = (sell_logic or "").strip() or None
        self._buy_ast = parse_logic(self.buy_logic, len(self.buy_conditions)) if self.buy_logic else None
        self._sell_ast = parse_logic(self.sell_logic, len(self.sell_conditions)) if self.sell_logic else None
        # 자유 산술식 조건 ("expr" 키) — 파싱 선행 (문법 오류는 여기서 400으로)
        for c in (self.buy_conditions + self.sell_conditions):
            txt = (c.get("expr") or "").strip()
            if txt:
                ast = parse_expr(txt)
                for _k, _f, _d, inner in collect_cross(ast):
                    if collect_cross(inner):
                        raise ValueError("순위/비율 안에 다시 순위/비율을 중첩할 수 없습니다")
                c["_expr_ast"] = ast
        self._panels: dict = {}  # 횡단면(순위/비율) 사전계산 {key: DataFrame[date,ticker]}
        self._score_panels: dict = {}  # 점수 근사 패널 {점수명: DataFrame[date,ticker]}
        self._expr_panels: dict = {}   # 산술식 내부 횡단면 패널 {canonical key: DataFrame}
        self._sig: dict = {}     # 벡터화 시그널 캐시 {ticker: Series[date → 0/1/2]}
        self._pit_base_cache: dict = {}  # 종목별 PIT 재무 패널 캐시 (financials_history 기반)

    @property
    def name(self) -> str:
        return "조건식 전략"

    @property
    def required_days(self) -> int:
        base = max(_max_period(self.buy_conditions), _max_period(self.sell_conditions)) + 30
        # 자유 산술식(조건 + 우선순위식)의 중첩 기간 룩백
        asts = [c.get("_expr_ast") for c in (self.buy_conditions + self.sell_conditions)]
        asts.append(getattr(self, "_prio_ast", None))
        for ast in asts:
            if ast is not None:
                base = max(base, expr_lookback(ast) + 30)
        # 확장 토큰의 내재 룩백(예: 52주 신고가=252봉) 반영 — 워밍업 부족 시 조건이 NaN으로 무시됨
        try:
            from src.kis_strategies.factor_tokens import token_min_bars
            names: list[str] = []
            for c in (self.buy_conditions + self.sell_conditions):
                names += [c.get("factor_token") or "", c.get("factor_token2") or ""]
            for ast in asts:
                if ast is not None:
                    names += ["{" + t + "}" for t in expr_tokens(ast)]
            tok = max((token_min_bars(n) for n in names), default=0)
        except Exception:
            tok = 0
        # 점수 토큰(60MA 이격도 + 변화율 합성) 워밍업
        if self._references_score():
            tok = max(tok, SCORE_MIN_BARS)
        # 논리식 시간 한정사(every/any/before)의 추가 룩백
        logic = max((max_lookback(a) for a in (self._buy_ast, self._sell_ast) if a is not None),
                    default=0)
        return max(base, tok + 10) + logic

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df is None or df.empty or len(df) < 2:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        fund = _load_fundamentals(stock_code) if self.allow_snapshot_fundamentals else None

        # per-bar도 벡터화와 동일한 _signal_hits 단일 경로 — 조건 시계열 전체를 평가해
        # 마지막 봉 판정. (스칼라 별도 경로는 토큰 종류마다 비일관 위험: 횡단면 날짜 포맷,
        # 시장 토큰 1970 정렬, 점수 패널 등 — 같은 계열 버그 3건의 구조적 재발 방지)
        sell_hit, buy_hit = self._signal_hits(df, fund, stock_code)
        if len(sell_hit) and bool(sell_hit[-1]):
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7, reason="매도 조건 충족")
        if len(buy_hit) and bool(buy_hit[-1]):
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

    def set_priority_expr(self, expr: str) -> None:
        """매수 우선순위식(일별) — 봉마다 후보들의 식 값으로 매수 순서를 정렬 (젠포트
        매수 종목 선택 우선순위). prepare_panel 전에 호출해야 패널·워밍업에 반영된다."""
        ast = parse_expr(expr)
        for _k, _f, _d, inner in collect_cross(ast):
            if collect_cross(inner):
                raise ValueError("순위/비율 안에 다시 순위/비율을 중첩할 수 없습니다")
        self._prio_ast = ast
        self._prio: dict = {}

    def priority_at(self, stock_code: str, when) -> float | None:
        """사전계산된 우선순위식 값 조회 — 없거나 NaN이면 None(정렬 시 후순위)."""
        ser = getattr(self, "_prio", {}).get(str(stock_code))
        if ser is None:
            return None
        try:
            if when not in ser.index:
                return None
            v = ser.loc[when]
        except Exception:
            return None
        return float(v) if pd.notna(v) else None

    def _references_score(self) -> bool:
        asts = [c.get("_expr_ast") for c in (self.buy_conditions + self.sell_conditions)]
        asts.append(getattr(self, "_prio_ast", None))
        for c in (self.buy_conditions + self.sell_conditions):
            for k in ("factor_token", "factor_token2"):
                if (c.get(k) or "").strip().strip("{}").strip() in SCORE_TOKENS:
                    return True
        return any(a is not None and expr_tokens(a) & SCORE_TOKENS for a in asts)

    def prepare_panel(self, ohlcv_map: dict) -> None:
        """순위/비율·점수·산술식 패널 사전계산. 엔진이 봉 루프 전에 1회 호출(전 종목 동일시점 값 필요)."""
        self._panels = {}
        self._score_panels = {}
        self._expr_panels = {}
        # 점수 근사 패널 — 조건이 점수 토큰을 참조할 때만 (성장·가치 레그는 펀더멘털 토글 시)
        if ohlcv_map and self._references_score():
            try:
                fund_map = ({str(tk): _load_fundamentals(str(tk)) for tk in ohlcv_map}
                            if self.allow_snapshot_fundamentals else None)
                self._score_panels = build_score_panels(ohlcv_map, fund_map)
            except Exception as e:
                logger.debug(f"score panels skipped: {e}")
                self._score_panels = {}
        # 자유 산술식 내부의 횡단면(순위/비율) 노드 패널 — 식별 키(canonical)별 1회
        fund_cache: dict = {}

        def _fund(tk: str):
            if not self.allow_snapshot_fundamentals:
                return None
            if tk not in fund_cache:
                fund_cache[tk] = _load_fundamentals(tk)
            return fund_cache[tk]

        expr_asts = [c.get("_expr_ast") for c in (self.buy_conditions + self.sell_conditions)]
        expr_asts.append(getattr(self, "_prio_ast", None))
        expr_cross: dict[str, tuple] = {}
        for ast in expr_asts:
            if ast is not None:
                for key, fn_id, dirv, inner in collect_cross(ast):
                    expr_cross.setdefault(key, (fn_id, dirv, inner))
        if expr_cross and ohlcv_map:
            for key, (fn_id, dirv, inner) in expr_cross.items():
                cols: dict = {}
                for tk, odf in ohlcv_map.items():
                    tk = str(tk)
                    try:
                        s = self._eval_expr_series(inner, odf, _fund(tk), tk)
                    except Exception:
                        s = None
                    if s is None or len(s) == 0:
                        continue
                    idx = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                           for d in odf.index]
                    cols[tk] = pd.Series(s.values, index=idx)
                if not cols:
                    self._expr_panels[key] = None
                    continue
                wide = pd.DataFrame(cols)
                if fn_id == "rank":
                    self._expr_panels[key] = wide.rank(axis=1, ascending=(dirv != "DESC"), method="min")
                else:
                    self._expr_panels[key] = wide.rank(axis=1, ascending=(dirv == "DESC"), pct=True) * 100.0

        # 매수 우선순위식 — 종목별 식 값 시계열 (엔진이 봉마다 priority_at으로 정렬)
        if getattr(self, "_prio_ast", None) is not None and ohlcv_map:
            self._prio = {}
            for tk, odf in ohlcv_map.items():
                tk = str(tk)
                try:
                    s = self._eval_expr_series(self._prio_ast, odf, _fund(tk), tk)
                except Exception:
                    s = None
                if s is not None and len(s):
                    self._prio[tk] = pd.Series(s.values, index=odf.index)

        cross = [c for c in (self.buy_conditions + self.sell_conditions)
                 if c.get("function_id") in ("rank", "ratio") and not c.get("_expr_ast")]
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

    # ═══════════════════════════════════════════════════════════════════════
    # 벡터화 — 전 봉 시그널 사전계산 (per-bar generate_signal과 동일 의미·결과)
    #   등가성 근거: 모든 함수가 인과적(rolling/ewm/shift/cumsum)이라
    #   전체 시리즈의 t시점 값 == t까지 슬라이스의 마지막 값.
    #   NaN = 평가 불가 → 그 봉에서 해당 조건 건너뜀(기존 정책 그대로).
    #   엔진이 봉 루프 전에 precompute_signals()를 호출하고 signal_at()으로 조회 —
    #   실패·미계산이면 None을 돌려 엔진이 per-bar로 폴백한다.
    # ═══════════════════════════════════════════════════════════════════════

    def precompute_signals(self, ohlcv_map: dict) -> None:
        """종목별 매수/매도 조건을 전체 시계열에 1회 평가 → 봉별 액션 코드 캐시."""
        self._sig = {}
        if not (self.buy_conditions or self.sell_conditions) or not ohlcv_map:
            return
        try:
            for tk, df in ohlcv_map.items():
                self._sig[str(tk)] = self._precompute_ticker(str(tk), df)
        except Exception as e:
            logger.debug(f"precompute_signals 실패 — per-bar 폴백: {e}")
            self._sig = {}

    def _precompute_ticker(self, tk: str, df: pd.DataFrame) -> pd.Series:
        import numpy as np
        fund = _load_fundamentals(tk) if self.allow_snapshot_fundamentals else None
        sell_hit, buy_hit = self._signal_hits(df, fund, tk)
        codes = np.zeros(len(df), dtype=np.int8)  # 0=HOLD
        codes[buy_hit] = 1
        codes[sell_hit] = 2                       # 매도 우선 (generate_signal과 동일)
        return pd.Series(codes, index=df.index)

    def _signal_hits(self, df: pd.DataFrame, fund: dict | None, tk: str):
        """봉별 (매도 충족, 매수 충족) bool 배열.

        논리식이 있으면 Kleene 3치(1/0/0.5)로 식을 평가해 정확히 1일 때만 발동 —
        평가 불가(0.5)가 결과를 좌우하면 보류. 없으면 기존 정책:
        매수=평가 가능 조건 전부 AND(불가는 건너뜀, 1개 이상 필요), 매도=하나라도 OR."""
        import numpy as np
        n = len(df)

        if self._sell_ast is not None:
            env = [self._cond_tri(df, c, fund, tk) for c in self.sell_conditions]
            sell_hit = eval_logic(self._sell_ast, env) >= 1.0
        else:
            sell_hit = np.zeros(n, dtype=bool)
            for c in self.sell_conditions:
                pair = self._cond_arrays(df, c, fund, tk)
                if pair is not None:
                    sell_hit |= pair[1]              # 평가 가능 & 충족 — 하나라도

        if self._buy_ast is not None:
            env = [self._cond_tri(df, c, fund, tk) for c in self.buy_conditions]
            buy_hit = eval_logic(self._buy_ast, env) >= 1.0
        else:
            any_valid = np.zeros(n, dtype=bool)
            all_ok = np.ones(n, dtype=bool)
            for c in self.buy_conditions:
                pair = self._cond_arrays(df, c, fund, tk)
                if pair is None:
                    continue
                valid, ok = pair
                any_valid |= valid
                all_ok &= (ok | ~valid)              # 평가 불가 조건은 건너뜀
            buy_hit = any_valid & all_ok             # 평가 가능 조건 ≥1 & 전부 충족
        return sell_hit, buy_hit

    def _cond_tri(self, df: pd.DataFrame, cond: dict, fund: dict | None, tk: str):
        """단일 조건 → 3치 배열 (1=충족, 0=불충족, 0.5=평가 불가). 전 봉 불가면 전부 0.5."""
        import numpy as np
        pair = self._cond_arrays(df, cond, fund, tk)
        if pair is None:
            return np.full(len(df), 0.5)
        valid, ok = pair
        tri = ok.astype(float)
        tri[~valid] = 0.5
        return tri

    def _cond_arrays(self, df: pd.DataFrame, cond: dict, fund: dict | None,
                     tk: str):
        """단일 조건 → (valid, ok) bool 배열. 전 봉 평가 불가면 None(조건 건너뜀)."""
        # 자유 산술식 조건 — 좌변을 식으로 평가 (가이드: 사칙연산 + 함수 + {팩터})
        ast = cond.get("_expr_ast")
        if ast is None and (cond.get("expr") or "").strip():
            try:
                ast = parse_expr(cond["expr"])
                cond["_expr_ast"] = ast
            except ValueError:
                return None
        if ast is not None:
            series = self._eval_expr_series(ast, df, fund, tk)
            if series is None or len(series) == 0:
                return None
            return _vector_compare(series, cond.get("op", "gte"),
                                   cond.get("rhs"), cond.get("rhs2"))
        if cond.get("function_id") in ("rank", "ratio"):
            panel = self._panels.get(self._cross_key(cond))
            if panel is None or str(tk) not in panel.columns:
                return None
            vals = panel[str(tk)].reindex(_date_keys(df))  # 패널 인덱스 포맷(YYYY-MM-DD)
            return _vector_compare(vals, cond.get("op", "lte"),
                                   cond.get("rhs"), cond.get("rhs2"))
        s = self._token_series(df, cond, fund, tk)
        if s is None or len(s) == 0:
            return None
        s = _apply_inner(s, cond)
        if s is None or len(s) == 0:
            return None
        fn = cond.get("function_id", "base")
        tok2 = (cond.get("factor_token2") or "").strip()
        op = cond.get("op", "gte")
        # 두 팩터 교차(상향/하향 돌파): (s1 - s2)가 0선을 교차 — 예: MA5 cross_above MA20(골든크로스).
        if tok2 and op in ("cross_above", "cross_below"):
            s2c = self._token_series(df, {"factor_token": tok2}, fund, tk)
            if s2c is None or len(s2c) == 0:
                return None
            s2c = _apply_inner(s2c.astype(float), cond, prefix="inner2")
            if s2c is None or len(s2c) == 0:
                return None
            return _vector_compare(s.astype(float) - s2c, op, 0.0)
        if tok2 and fn in _TWO_FACTOR_FNS:
            # 두 팩터 변형: 비교(F1,F2)·큰값·작은값·변화율_팩터 — 두 번째 피연산자도
            # 토큰 해석 + 자체 중첩(inner2) 지원
            s2 = self._token_series(df, {"factor_token": tok2}, fund, tk)
            if s2 is None or len(s2) == 0:
                return None
            s2 = _apply_inner(s2.astype(float), cond, prefix="inner2")
            if s2 is None or len(s2) == 0:
                return None
            series = _apply_two_factor(s.astype(float), s2, fn)
        elif fn == "pctf":
            return None  # 변화율_팩터는 두 번째 팩터 필수
        else:
            series = _apply_function(s, fn, cond.get("params") or {})
        if series is None or len(series) == 0:
            return None
        return _vector_compare(series, cond.get("op", "gte"),
                               cond.get("rhs"), cond.get("rhs2"))

    def _eval_expr_series(self, ast: tuple, df: pd.DataFrame, fund: dict | None, tk: str):
        """산술식 AST → 종목 시리즈. 미해석 토큰·횡단면 미계산이면 None(조건 건너뜀)."""
        def tok(name: str):
            s = self._token_series(df, {"factor_token": name}, fund, tk)
            return None if s is None or len(s) == 0 else s.astype(float)

        def cross(key: str):
            panel = (self._expr_panels or {}).get(key)
            if panel is None or str(tk) not in panel.columns:
                return None
            return pd.Series(panel[str(tk)].reindex(_date_keys(df)).values, index=df.index)

        out = eval_expr(ast, {"token": tok, "cross": cross,
                              "apply": _apply_function, "two": _apply_two_factor})
        return out if isinstance(out, pd.Series) else None

    def _build_pit_base(self, tk: str, df: pd.DataFrame):
        """financials_history → df.index에 정렬된 PIT 재무 패널(억 단위, 봉별 step + 봉별 시총).

        각 보고서의 '공시 가능일'(기간말 + 시차: 연간 90일/분기 45일) 이후 봉부터 그 값을 사용
        → look-ahead 차단. 적재 없으면 None. 손익은 연환산(분기 누적 보정), 시총은 봉별 종가×주식수."""
        import datetime as _dt
        try:
            from src.data.dart_history import ANNUALIZE_FACTOR, load_history
            rows = load_history(tk)
        except Exception:
            return None
        if not rows:
            return None
        _PEND = {"11013": (3, 31), "11012": (6, 30), "11014": (9, 30), "11011": (12, 31)}
        recs = []
        for r in rows:
            pe = _PEND.get(r.get("reprt"))
            if not pe:
                continue
            try:
                end = _dt.date(int(r["year"]), pe[0], pe[1])
            except Exception:
                continue
            lag = 90 if r["reprt"] == "11011" else 45
            af = ANNUALIZE_FACTOR.get(r["reprt"], 1.0)

            def _v(val, annualize=False, _af=af):
                # 원 → 억. 손익(annualize=True)은 분기 누적 → 연환산.
                return (val * (_af if annualize else 1.0) / 1e8) if val is not None else None
            recs.append({
                "avail": end + _dt.timedelta(days=lag),
                "net_income": _v(r.get("net_income"), True),
                "revenue": _v(r.get("revenue"), True),
                "operating_profit": _v(r.get("operating_profit"), True),
                "operating_cf": _v(r.get("operating_cf"), True),
                "total_equity": _v(r.get("total_equity")),
                "total_liabilities": _v(r.get("total_liabilities")),
                "shares": r.get("shares_outstanding"),
            })
        if not recs:
            return None
        recs.sort(key=lambda x: x["avail"])
        fields = ("net_income", "revenue", "operating_profit", "operating_cf",
                  "total_equity", "total_liabilities", "shares")
        cols: dict = {f: [] for f in fields}
        cur = dict.fromkeys(fields)
        ri = 0
        for d in df.index:
            bd = d.date() if hasattr(d, "date") else None
            if bd is not None:
                while ri < len(recs) and recs[ri]["avail"] <= bd:
                    for f in fields:
                        if recs[ri][f] is not None:
                            cur[f] = recs[ri][f]
                    ri += 1
            for f in fields:
                cols[f].append(cur[f])
        panel = {f: pd.Series(cols[f], index=df.index, dtype="float64") for f in fields}
        try:
            panel["market_cap"] = df["close"].astype(float) * panel["shares"] / 1e8  # 억
        except Exception:
            panel["market_cap"] = pd.Series([np.nan] * len(df), index=df.index)
        return panel

    def _pit_fund_series(self, tk: str, name: str, df: pd.DataFrame):
        """PIT 펀더멘털 토큰 → 봉별 시계열 (financials_history 적재 시). 미적재/미지원이면 None."""
        if os.getenv("BACKTEST_PIT_FUNDAMENTALS", "1") == "0" or name not in _PIT_FUND_TOKENS:
            return None
        panel = self._pit_base_cache.get(tk, _PIT_UNBUILT)
        if panel is _PIT_UNBUILT:
            try:
                panel = self._build_pit_base(tk, df)
            except Exception:
                panel = None
            self._pit_base_cache[tk] = panel
        if not panel:
            return None
        ni, te, rev = panel["net_income"], panel["total_equity"], panel["revenue"]
        op, tl, ocf, sh = (panel["operating_profit"], panel["total_liabilities"],
                           panel["operating_cf"], panel["shares"])
        mc = panel["market_cap"]

        def pos(s):  # 분모 ≤0 은 NaN (평가 불가) — 적자 PER 등 무의미값 차단
            return s.where(s > 0)
        if name in ("시가총액", "시총"):
            return mc
        if name == "PER":
            return mc / pos(ni)
        if name == "PBR":
            return mc / pos(te)
        if name == "PSR":
            return mc / pos(rev)
        if name == "PCR":
            return mc / pos(ocf)
        if name == "ROE":
            return ni / pos(te) * 100.0
        if name == "부채비율":
            return tl / pos(te) * 100.0
        if name == "매출액":
            return rev
        if name == "영업이익":
            return op
        if name == "순이익":
            return ni
        if name == "EPS":
            return ni * 1e8 / pos(sh)
        return None

    def _token_series(self, df: pd.DataFrame, cond: dict, fund: dict | None, tk: str):
        """조건의 좌항 베이스 시리즈 — 점수 패널 → OHLCV·시장·매크로·수급 → PIT 재무 → 스냅샷.

        점수 토큰은 횡단면 합성이라 prepare_panel에서 사전계산된 패널 열을 종목 날짜에
        정렬해 돌려준다(이후 이동평균 등 함수 체인 적용 가능 — 가이드의 기간총합({종합점수},5일))."""
        name = (cond.get("factor_token") or "").strip().strip("{}").strip()
        if name in SCORE_TOKENS:
            panel = (self._score_panels or {}).get(name)
            if panel is None or str(tk) not in panel.columns:
                return None
            return pd.Series(panel[str(tk)].reindex(_date_keys(df)).values, index=df.index)
        s = _base_series(df, cond.get("factor_token", ""))
        if s is None or len(s) == 0:
            # ① PIT 우선 — 봉별 시점 재무(financials_history). look-ahead 없음·allow_snapshot 무관.
            pit = self._pit_fund_series(tk, name, df)
            if pit is not None:
                return pit
            # ② 폴백 — 현재 스냅샷 상수 (opt-in: allow_snapshot_fundamentals, financials_history 미적재 시)
            if fund is not None:
                fv = _fundamental_value(cond.get("factor_token", ""), fund)
                if fv is not None:
                    s = pd.Series([fv] * len(df), index=df.index)
        return s

    def signal_at(self, stock_code: str, when) -> Signal | None:
        """사전계산 시그널 조회. 미계산·미보유 날짜면 None → 엔진이 per-bar 폴백."""
        sig_map = getattr(self, "_sig", None)
        ser = sig_map.get(str(stock_code)) if sig_map else None
        if ser is None:
            return None
        try:
            if when not in ser.index:
                return None
            code = int(ser.loc[when])
        except Exception:
            return None
        if code == 2:
            return Signal(stock_code=stock_code, stock_name=stock_code,
                          action=Action.SELL, strength=0.7, reason="매도 조건 충족")
        if code == 1:
            return Signal(stock_code=stock_code, stock_name=stock_code,
                          action=Action.BUY, strength=0.7, reason="매수 조건 충족")
        return Signal(stock_code=stock_code, stock_name=stock_code,
                      action=Action.HOLD, strength=0.0, reason="조건 미충족")

# 레지스트리 자기 등록 — 이 모듈이 import 되면 "Condition" 전략 사용 가능
STRATEGY_REGISTRY["Condition"] = ConditionStrategy
