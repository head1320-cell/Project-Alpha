"""Alpha Lab 엔진 — 크로스섹션 알파 표현식·PIT 패널·검증 리포트 (Full Expansion P2)
================================================================================
"좋은 종목을 보여주는 도구"가 아니라 "검증된 독립 알파"를 만드는 연구실의 순수 엔진.

핵심 설계 (정직한 v1 스코프):
  · 표현식 = 사전계산 시계열 피처(모멘텀·변동성·유동성·펀더멘털) + 크로스섹션
    변환(rank/zscore/winsorize/sector_neutralize)의 산술 결합. 시계열 연산자
    (ts_*)는 피처 정의에 내장 — 표현식 레벨 ts_* 는 v2.
  · PIT 규칙:
      - 가격 파생 피처: as-of 시점까지의 OHLCV만 사용 (구조적으로 look-ahead 불가)
      - 펀더멘털: financials_history 연간 보고서를 "사업연도 Y → Y+1년 4월 1일부터
        사용 가능" 보수적 공시랙으로 as-of 선택 (분기·정정공시 미반영 — 정직 한계)
  · 검증 = 월간 리밸런스 Rank IC 시계열 → IC/ICIR/t-stat/HitRate/Decay(1·2·3M),
    분위 포트폴리오(모노토닉), 롱숏 곡선, IS/OOS 반분할, 회전율 프록시, 커버리지.
    거래비용 미반영(정직 라벨) — 비용·용량은 P3~P4에서.
  · 안전 파서: eval 금지 — 재귀하강 파서, 허용 토큰만.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

HORIZON_BARS = 21          # 1개월 ≈ 21거래일
STALE_LIMIT = 7            # as-of 매핑 시 허용 최대 시차(거래일)
MIN_NAMES = 8              # 기간당 최소 유효 종목 수 (미만이면 해당 기간 제외)
FUND_LAG_MONTH = 4         # 사업연도 Y → Y+1년 4월부터 사용 (보수적 공시랙)


# ── 피처 카탈로그 ─────────────────────────────────────────────────────────────
# (id, 라벨, family, 설명). family: price=가격파생(PIT 보장) | fund=펀더멘털(연간+공시랙)
FIELDS: list[tuple[str, str, str, str]] = [
    ("mom_1m", "1개월 모멘텀", "price", "c/c[-21]-1"),
    ("mom_3m", "3개월 모멘텀", "price", "c/c[-63]-1"),
    ("mom_6m", "6개월 모멘텀", "price", "c/c[-126]-1"),
    ("mom_12m", "12개월 모멘텀", "price", "c/c[-252]-1"),
    ("mom_12_1", "12-1 모멘텀", "price", "12M 모멘텀에서 최근 1M 제외 (고전 UMD)"),
    ("reversal_5d", "5일 단기반전", "price", "-(c/c[-5]-1) — 단기 과열 역베팅"),
    ("vol_20d", "20일 변동성", "price", "일수익률 std(20)"),
    ("vol_60d", "60일 변동성", "price", "일수익률 std(60)"),
    ("amount_20d", "20일 평균 거래대금", "price", "유동성 프록시"),
    ("price_level", "주가 레벨", "price", "종가 원값 — 알파로 직접 사용 시 lint 경고"),
    ("roe", "ROE", "fund", "순이익/자본 (연간, 공시랙 적용)"),
    ("net_margin", "순이익률", "fund", "순이익/매출"),
    ("debt_ratio", "부채비율", "fund", "부채/자본"),
    ("earnings_yield", "이익수익률", "fund", "EPS/주가 (저PER 방향)"),
    ("book_yield", "장부수익률", "fund", "BPS/주가 (저PBR 방향)"),
    ("dividend_yield_f", "배당수익률", "fund", "DPS/주가 (연간 공시 기준)"),
    ("eps_yoy", "EPS 증감(YoY)", "fund", "연간 EPS 변화율 — 컨센서스 부재 시 대용(한계)"),
]
FIELD_IDS = {f[0] for f in FIELDS}
FUND_FIELDS = {f[0] for f in FIELDS if f[2] == "fund"}

FUNCS_1 = ("rank", "zscore", "winsorize", "neg", "log1p_abs", "abs", "sign", "sector_neutralize")
FUNCS_2 = ("min2", "max2")


# ── 안전 표현식 파서 (재귀하강 — eval 금지) ────────────────────────────────────
_TOKEN_RE = re.compile(r"\s*(?:(\d+\.?\d*)|([A-Za-z_][A-Za-z0-9_]*)|(.))")


class AlphaParseError(ValueError):
    pass


@dataclass
class _Tok:
    kind: str   # num | name | op
    val: str


def _tokenize(expr: str) -> list[_Tok]:
    out: list[_Tok] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            break
        pos = m.end()
        num, name, op = m.groups()
        if num is not None:
            out.append(_Tok("num", num))
        elif name is not None:
            out.append(_Tok("name", name))
        elif op is not None and op.strip():
            if op not in "+-*/(),":
                raise AlphaParseError(f"허용되지 않는 문자: '{op}'")
            out.append(_Tok("op", op))
    return out


@dataclass
class Node:
    kind: str                       # num | field | call | bin | neg
    val: str | float = ""
    args: list[Node] = field(default_factory=list)

    def fields(self) -> set[str]:
        s = {str(self.val)} if self.kind == "field" else set()
        for a in self.args:
            s |= a.fields()
        return s

    def calls(self) -> set[str]:
        s = {str(self.val)} if self.kind == "call" else set()
        for a in self.args:
            s |= a.calls()
        return s


class _Parser:
    def __init__(self, toks: list[_Tok]):
        self.toks = toks
        self.i = 0

    def peek(self) -> _Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def eat(self, kind: str | None = None, val: str | None = None) -> _Tok:
        t = self.peek()
        if t is None or (kind and t.kind != kind) or (val and t.val != val):
            raise AlphaParseError(f"구문 오류 (위치 {self.i}): {'끝' if t is None else t.val!r}")
        self.i += 1
        return t

    def parse(self) -> Node:
        n = self.expr()
        if self.peek() is not None:
            raise AlphaParseError(f"잉여 토큰: {self.peek().val!r}")
        return n

    def expr(self) -> Node:            # + -
        n = self.term()
        while (t := self.peek()) and t.kind == "op" and t.val in "+-":
            self.eat()
            n = Node("bin", t.val, [n, self.term()])
        return n

    def term(self) -> Node:            # * /
        n = self.unary()
        while (t := self.peek()) and t.kind == "op" and t.val in "*/":
            self.eat()
            n = Node("bin", t.val, [n, self.unary()])
        return n

    def unary(self) -> Node:
        t = self.peek()
        if t and t.kind == "op" and t.val == "-":
            self.eat()
            return Node("neg", args=[self.unary()])
        return self.atom()

    def atom(self) -> Node:
        t = self.peek()
        if t is None:
            raise AlphaParseError("식이 불완전합니다")
        if t.kind == "num":
            self.eat()
            return Node("num", float(t.val))
        if t.kind == "name":
            self.eat()
            nxt = self.peek()
            if nxt and nxt.kind == "op" and nxt.val == "(":
                if t.val not in FUNCS_1 and t.val not in FUNCS_2:
                    raise AlphaParseError(f"알 수 없는 함수: {t.val}")
                self.eat(val="(")
                args = [self.expr()]
                while (p := self.peek()) and p.kind == "op" and p.val == ",":
                    self.eat()
                    args.append(self.expr())
                self.eat(val=")")
                want = 1 if t.val in FUNCS_1 else 2
                if len(args) != want:
                    raise AlphaParseError(f"{t.val}()는 인자 {want}개 필요")
                return Node("call", t.val, args)
            if t.val not in FIELD_IDS:
                raise AlphaParseError(f"알 수 없는 필드: {t.val}")
            return Node("field", t.val)
        if t.val == "(":
            self.eat()
            n = self.expr()
            self.eat(val=")")
            return n
        raise AlphaParseError(f"예상치 못한 토큰: {t.val!r}")


def parse_alpha(expr: str) -> Node:
    toks = _tokenize(expr)
    if not toks:
        raise AlphaParseError("빈 식")
    return _Parser(toks).parse()


# ── 크로스섹션 평가 ───────────────────────────────────────────────────────────
def _cs_rank(x: np.ndarray) -> np.ndarray:
    """유효값 [0,1] 균등 rank. NaN 보존."""
    out = np.full_like(x, np.nan, dtype=float)
    m = np.isfinite(x)
    if m.sum() >= 2:
        order = x[m].argsort().argsort().astype(float)
        out[m] = order / (m.sum() - 1)
    elif m.sum() == 1:
        out[m] = 0.5
    return out


def _cs_zscore(x: np.ndarray) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    m = np.isfinite(x)
    if m.sum() >= 2:
        mu, sd = x[m].mean(), x[m].std(ddof=0)
        out[m] = (x[m] - mu) / sd if sd > 1e-12 else 0.0
    return out


def _cs_winsorize(x: np.ndarray, p: float = 0.05) -> np.ndarray:
    out = x.copy().astype(float)
    m = np.isfinite(x)
    if m.sum() >= 4:
        lo, hi = np.nanpercentile(x[m], [p * 100, (1 - p) * 100])
        out[m] = np.clip(x[m], lo, hi)
    return out


def _cs_sector_neutralize(x: np.ndarray, groups: list[str | None]) -> np.ndarray:
    """섹터 그룹 내 demean. 그룹 정보 없으면 전체 demean(안전 폴백)."""
    out = x.copy().astype(float)
    arr = np.asarray(groups, dtype=object)
    for g in set(a for a in arr if a):
        m = (arr == g) & np.isfinite(x)
        if m.sum() >= 2:
            out[m] = x[m] - x[m].mean()
    none_m = np.array([a is None for a in arr]) & np.isfinite(x)
    if none_m.sum() >= 2:
        out[none_m] = x[none_m] - x[none_m].mean()
    return out


def eval_node(n: Node, panel: dict[str, np.ndarray], groups: list[str | None]) -> np.ndarray:
    if n.kind == "num":
        size = len(next(iter(panel.values()))) if panel else 0
        return np.full(size, float(n.val))
    if n.kind == "field":
        return panel[str(n.val)].astype(float)
    if n.kind == "neg":
        return -eval_node(n.args[0], panel, groups)
    if n.kind == "bin":
        a = eval_node(n.args[0], panel, groups)
        b = eval_node(n.args[1], panel, groups)
        with np.errstate(all="ignore"):
            if n.val == "+":
                r = a + b
            elif n.val == "-":
                r = a - b
            elif n.val == "*":
                r = a * b
            else:
                r = np.where(np.abs(b) > 1e-12, a / np.where(b == 0, np.nan, b), np.nan)
        r[~np.isfinite(r)] = np.nan
        return r
    if n.kind == "call":
        a = eval_node(n.args[0], panel, groups)
        f = str(n.val)
        if f == "rank":
            return _cs_rank(a)
        if f == "zscore":
            return _cs_zscore(a)
        if f == "winsorize":
            return _cs_winsorize(a)
        if f == "neg":
            return -a
        if f == "abs":
            return np.abs(a)
        if f == "sign":
            return np.sign(a)
        if f == "log1p_abs":
            return np.sign(a) * np.log1p(np.abs(a))
        if f == "sector_neutralize":
            return _cs_sector_neutralize(a, groups)
        b = eval_node(n.args[1], panel, groups)
        return np.fmin(a, b) if f == "min2" else np.fmax(a, b)
    raise AlphaParseError(f"알 수 없는 노드: {n.kind}")


# ── Lint ─────────────────────────────────────────────────────────────────────
def lint_alpha(expr: str, existing_exprs: list[str] | None = None) -> dict:
    """저장 전 필수 검사. level: error(저장 불가) | warn | info."""
    issues: list[dict] = []
    node = None
    try:
        node = parse_alpha(expr)
    except AlphaParseError as e:
        issues.append({"level": "error", "code": "parse", "message": str(e)})
        return {"ok": False, "issues": issues, "fields": [], "funcs": []}

    used = sorted(node.fields())
    calls = sorted(node.calls())

    if "price_level" in used:
        issues.append({"level": "warn", "code": "price_level",
                       "message": "주가 원값을 알파로 직접 사용 — 스케일·비정상성 문제. rank/zscore 변환 권장."})
    fund_used = [f for f in used if f in FUND_FIELDS]
    if fund_used:
        issues.append({"level": "info", "code": "pit_lag",
                       "message": f"펀더멘털 필드 {fund_used}: 연간 보고서 + {FUND_LAG_MONTH}월 공시랙 적용 "
                                  "(분기·정정공시 미반영 — 정직 한계). 미래참조는 구조적으로 차단됨."})
    if not any(c in ("rank", "zscore", "winsorize") for c in calls) and len(used) >= 2:
        issues.append({"level": "warn", "code": "scale_mix",
                       "message": "서로 다른 스케일의 필드를 변환 없이 결합 — rank()/zscore() 정규화 권장."})
    if re.search(r"/\s*0(?:\.0*)?(?:\s|$|\))", expr):
        issues.append({"level": "error", "code": "div_zero", "message": "0으로 나누기."})
    norm = re.sub(r"\s+", "", expr)
    for ex in existing_exprs or []:
        if re.sub(r"\s+", "", ex) == norm:
            issues.append({"level": "warn", "code": "duplicate",
                           "message": "동일한 식의 알파가 이미 레지스트리에 존재 (중복)."})
            break
    ok = not any(i["level"] == "error" for i in issues)
    return {"ok": ok, "issues": issues, "fields": used, "funcs": calls}


# ── 데이터 패널 (PIT) ─────────────────────────────────────────────────────────
def _load_price_series(tickers: list[str], start: str, end: str) -> dict[str, dict]:
    """종목별 (dates[np.datetime64], close, amount). 로드 실패 종목은 제외."""
    from src.data.ohlcv_loader import load_ohlcv_unified
    out: dict[str, dict] = {}
    for t in tickers:
        try:
            df = load_ohlcv_unified(t, start, end)
            if df is None or len(df) < HORIZON_BARS * 3:
                continue
            closes = df["close"].astype(float).values
            amount = (df["amount"].astype(float).values if "amount" in df.columns
                      else df["close"].astype(float).values * df.get("volume", 0))
            dates = np.array(df.index.values, dtype="datetime64[D]")
            out[t] = {"dates": dates, "close": closes, "amount": np.asarray(amount, dtype=float)}
        except Exception:
            continue
    return out


def _load_fundamentals(tickers: list[str]) -> dict[str, dict[int, dict]]:
    """financials_history 연간(11011) → {ticker: {year: {eps,bps,roe,...}}}. 없으면 빈 dict."""
    try:
        from sqlalchemy import text

        from src.database import get_engine
        eng = get_engine()
        out: dict[str, dict[int, dict]] = {}
        with eng.connect() as c:
            for i in range(0, len(tickers), 300):
                chunk = tickers[i:i + 300]
                ph = ",".join(f":t{j}" for j in range(len(chunk)))
                params = {f"t{j}": t for j, t in enumerate(chunk)}
                rows = c.execute(text(
                    "SELECT ticker, bsns_year, revenue, net_income, total_liabilities, "
                    "total_equity, shares_outstanding, dps FROM financials_history "
                    f"WHERE reprt_code = '11011' AND ticker IN ({ph})"), params).fetchall()
                for tk, yr, rev, ni, liab, eq, shares, dps in rows:
                    try:
                        y = int(yr)
                    except (TypeError, ValueError):
                        continue
                    d: dict = {}
                    sh = float(shares) if shares else None
                    if ni is not None and eq:
                        d["roe"] = float(ni) / float(eq) if float(eq) != 0 else None
                    if ni is not None and rev:
                        d["net_margin"] = float(ni) / float(rev) if float(rev) != 0 else None
                    if liab is not None and eq:
                        d["debt_ratio"] = float(liab) / float(eq) if float(eq) != 0 else None
                    if ni is not None and sh and sh > 0:
                        d["eps"] = float(ni) / sh
                    if eq is not None and sh and sh > 0:
                        d["bps"] = float(eq) / sh
                    if dps is not None:
                        d["dps"] = float(dps)
                    out.setdefault(tk, {})[y] = d
        return out
    except Exception as e:
        logger.debug(f"fundamentals 로드 실패(정직 결측): {e}")
        return {}


def _fund_asof(fund: dict[int, dict], asof: np.datetime64) -> tuple[dict | None, int | None]:
    """as-of 시점에 사용 가능한 최신 사업연도 — Y는 (Y+1)-04-01부터. (data, year)"""
    d = np.datetime64(asof, "D").astype("datetime64[M]").astype(int)  # months since 1970
    year = 1970 + d // 12
    month = d % 12 + 1
    usable_year = year - 1 if month >= FUND_LAG_MONTH else year - 2
    for y in range(usable_year, usable_year - 3, -1):
        if y in fund:
            return fund[y], y
    return None, None


def _price_features(ser: dict, idx: int) -> dict[str, float]:
    c, a = ser["close"], ser["amount"]
    f: dict[str, float] = {}

    def ret(k: int) -> float:
        return c[idx] / c[idx - k] - 1.0 if idx - k >= 0 and c[idx - k] > 0 else np.nan
    f["mom_1m"] = ret(21)
    f["mom_3m"] = ret(63)
    f["mom_6m"] = ret(126)
    f["mom_12m"] = ret(252)
    r12, r1 = ret(252), ret(21)
    f["mom_12_1"] = ((1 + r12) / (1 + r1) - 1.0) if np.isfinite(r12) and np.isfinite(r1) else np.nan
    f["reversal_5d"] = -ret(5)
    for label, win in (("vol_20d", 20), ("vol_60d", 60)):
        if idx - win >= 1:
            seg = c[idx - win:idx + 1]
            with np.errstate(all="ignore"):
                dr = np.diff(np.log(np.where(seg > 0, seg, np.nan)))
            f[label] = float(np.nanstd(dr)) if np.isfinite(dr).sum() >= win // 2 else np.nan
        else:
            f[label] = np.nan
    f["amount_20d"] = float(np.nanmean(a[max(0, idx - 19):idx + 1])) if len(a) else np.nan
    f["price_level"] = float(c[idx])
    return f


def _sector_groups(tickers: list[str]) -> list[str | None]:
    try:
        from src.data.genport_themes import build_group_assignment
        from src.data.stock_master import load_master_flags
        flags = load_master_flags() or {}
        assign = build_group_assignment(flags) if flags else {}
        return [assign.get(t) for t in tickers]
    except Exception:
        return [None] * len(tickers)


# ── 검증 ─────────────────────────────────────────────────────────────────────
def _idx_at(ser: dict, d: np.datetime64) -> int | None:
    """as-of 인덱스 — `d` 이하의 마지막 봉. 시차가 `STALE_LIMIT` 을 넘으면 None."""
    i = int(np.searchsorted(ser["dates"], d, side="right")) - 1
    if i < 0 or (d - ser["dates"][i]).astype(int) > STALE_LIMIT:
        return None
    return i


def _panel_at(d, names, groups, series, fund, need_fund, *, require_forward: bool):
    """시점 `d` 의 크로스섹션 패널을 만든다 (P2-S 로 `validate_alpha` 에서 분리).

    ★`require_forward` 가 이 함수의 존재 이유다★
    검증 루프는 forward 1개월 수익률이 없는 종목을 버린다 — IC 를 계산하려면 미래가
    있어야 하므로 맞다. 그런데 **최신 시점에는 forward 가 원래 없다.** 그래서 그 필터를
    그대로 물려받아 라이브 스코어링에 쓰면 **모든 종목이 탈락**하고, 빈 결과가
    "알파가 아무것도 못 골랐다" 로 읽힌다. 실제로는 "미래를 아직 모른다" 일 뿐이다.

    검증 경로는 `require_forward=True` 로 **한 글자도 다르지 않게** 동작한다.

    Returns:
        (row_names, row_groups, np_panel, fwd | None, n_fund)
    """
    panel: dict[str, list[float]] = {f: [] for f in FIELD_IDS}
    fwd: dict[int, list[float]] = {1: [], 2: [], 3: []}
    row_names: list[str] = []
    row_groups: list[str | None] = []
    n_fund = 0

    for tname, g in zip(names, groups):
        ser = series[tname]
        i = _idx_at(ser, d)
        if i is None or i < 252:
            continue
        pf = _price_features(ser, i)
        fd, _fy = _fund_asof(fund.get(tname, {}), d) if need_fund else (None, None)
        if need_fund:
            eps = (fd or {}).get("eps")
            bps = (fd or {}).get("bps")
            dps = (fd or {}).get("dps")
            px = ser["close"][i]
            pf["roe"] = (fd or {}).get("roe", np.nan)
            pf["net_margin"] = (fd or {}).get("net_margin", np.nan)
            pf["debt_ratio"] = (fd or {}).get("debt_ratio", np.nan)
            pf["earnings_yield"] = eps / px if eps is not None and px > 0 else np.nan
            pf["book_yield"] = bps / px if bps is not None and px > 0 else np.nan
            pf["dividend_yield_f"] = dps / px if dps is not None and px > 0 else np.nan
            prev_fd, _ = _fund_asof(fund.get(tname, {}), d - np.timedelta64(365, "D"))
            pe, pp = (fd or {}).get("eps"), (prev_fd or {}).get("eps")
            pf["eps_yoy"] = ((pe - pp) / abs(pp)) if (pe is not None and pp not in (None, 0)) else np.nan
            if fd:
                n_fund += 1
        else:
            for f in FUND_FIELDS:
                pf[f] = np.nan

        if require_forward:
            # forward 수익률 (t → t+21h) — 미래는 여기서만, 점수 입력엔 절대 미사용
            fr: dict[int, float] = {}
            for h in (1, 2, 3):
                j = i + HORIZON_BARS * h
                fr[h] = (ser["close"][j] / ser["close"][i] - 1.0
                         if j < len(ser["close"]) and ser["close"][i] > 0 else np.nan)
            if not np.isfinite(fr[1]):
                continue
            for h in (1, 2, 3):
                fwd[h].append(fr[h])

        row_names.append(tname)
        row_groups.append(g)
        for f in FIELD_IDS:
            panel[f].append(pf.get(f, np.nan))

    np_panel = {f: np.asarray(v, dtype=float) for f, v in panel.items()}
    return row_names, row_groups, np_panel, (fwd if require_forward else None), n_fund


def score_alpha(expr: str, tickers: list[str], as_of: str | None = None,
                price_loader=None) -> dict:
    """★라이브 크로스섹션 스코어 — 알파가 포트폴리오가 되는 첫 걸음 (P2-S)★

    `validate_alpha` 는 IC 를 재느라 **데이터 끝에서 21거래일 전**까지만 본다
    (`rebal_idx` 가 forward 확보분을 뺀다). 그래서 그 리포트의 `latest_scores_top` 은
    한 달 낡은 점수이고, 그것을 현재 비중으로 쓰면 낡은 값을 현재로 쓰는 것이다.
    이 함수는 **as-of 시점의 실제 점수**를 낸다.

    ★as_of 를 안 줘도 서버가 쓴 날짜를 찍는다★ (P1-A 규칙) — 그것이 없으면 이 점수로
    만든 포트폴리오는 재현 좌표를 갖지 못한다.
    """
    try:
        node = parse_alpha(expr)
    except AlphaParseError as e:
        return {"available": False, "reason": f"표현식을 해석할 수 없습니다: {e}"}

    need_fund = bool(node.fields() & FUND_FIELDS)
    end = np.datetime64(as_of, "D") if as_of else np.datetime64("today", "D")
    # 252봉 히스토리(_panel_at 의 최소 조건) + 여유. 검증과 같은 여유폭을 쓴다.
    start = str(end - np.timedelta64(int(39 * 31), "D"))

    series = (price_loader or _load_price_series)(tickers, start, str(end))
    if len(series) < MIN_NAMES:
        return {"available": False,
                "reason": f"시세 가용 종목 {len(series)}개 (<{MIN_NAMES}) — 유니버스를 넓히세요.",
                "as_of_requested": as_of, "as_of_effective": str(end)}

    names = list(series.keys())
    fund = _load_fundamentals(names) if need_fund else {}
    groups = _sector_groups(names)

    # 실제 사용한 절단일 = 가용 시세의 마지막 날 (요청일이 휴장·미래면 그보다 이르다).
    ref = max(series.values(), key=lambda s: len(s["dates"]))
    eff = min(ref["dates"][-1], end)

    row_names, row_groups, np_panel, _fwd, n_fund = _panel_at(
        eff, names, groups, series, fund, need_fund, require_forward=False)
    if len(row_names) < MIN_NAMES:
        return {"available": False,
                "reason": (f"as-of {str(eff)} 시점에 유효 종목 {len(row_names)}개 "
                           f"(<{MIN_NAMES}) — 252봉 이상 히스토리가 필요합니다."),
                "as_of_requested": as_of, "as_of_effective": str(eff)}

    try:
        scores = eval_node(node, np_panel, row_groups)
    except Exception as e:  # noqa: BLE001 — 평가 실패는 사유로 답한다
        return {"available": False, "reason": f"평가 실패: {e}",
                "as_of_requested": as_of, "as_of_effective": str(eff)}

    out = {n: float(v) for n, v in zip(row_names, scores) if np.isfinite(v)}
    if len(out) < MIN_NAMES:
        return {"available": False,
                "reason": (f"유한한 점수를 가진 종목이 {len(out)}개 (<{MIN_NAMES}) — "
                           "필드 커버리지가 부족합니다."),
                "as_of_requested": as_of, "as_of_effective": str(eff)}

    return {"available": True, "expr": expr,
            "as_of_requested": as_of, "as_of_effective": str(eff),
            "scores": out, "n_universe": len(series), "coverage": len(out),
            "fund_coverage": n_fund if need_fund else None}


def validate_alpha(expr: str, tickers: list[str], months: int = 24,
                   quantiles: int = 5, price_loader=None) -> dict:
    """월간 리밸런스 크로스섹션 검증. price_loader는 테스트 주입용."""
    node = parse_alpha(expr)
    used = node.fields()
    need_fund = bool(used & FUND_FIELDS)

    horizon_end = np.datetime64("today", "D")
    lookback_days = int((months + 15) * 31)
    start = str(horizon_end - np.timedelta64(lookback_days, "D"))
    series = (price_loader or _load_price_series)(tickers, start, str(horizon_end))
    if len(series) < MIN_NAMES:
        return {"error": True,
                "message": f"시세 가용 종목 {len(series)}개 (<{MIN_NAMES}) — 유니버스를 넓히세요."}

    fund = _load_fundamentals(list(series.keys())) if need_fund else {}
    names = list(series.keys())
    groups = _sector_groups(names)

    # 마스터 캘린더 = 최장 시계열 종목의 날짜축
    ref = max(series.values(), key=lambda s: len(s["dates"]))
    cal = ref["dates"]
    # 리밸런스 시점: 뒤에서부터 21영업일 간격, 마지막 시점은 forward 1M 확보분 제외
    rebal_idx = list(range(len(cal) - 1 - HORIZON_BARS, HORIZON_BARS * 13, -HORIZON_BARS))[:months]
    rebal_idx.reverse()
    if len(rebal_idx) < 6:
        return {"error": True, "message": "검증 가능한 기간이 6개월 미만 — 데이터가 부족합니다."}

    ic_by_h: dict[int, list[float]] = {1: [], 2: [], 3: []}
    q_rets: list[list[float]] = [[] for _ in range(quantiles)]
    ls_curve: list[float] = [1.0]
    period_dates: list[str] = []
    turnover_sum, turnover_n = 0.0, 0
    prev_scores: dict[str, float] = {}
    coverage: list[int] = []
    fund_cov: list[int] = []

    for ri in rebal_idx:
        d = cal[ri]
        # ★패널 빌드는 `_panel_at` 하나다 (P2-S)★ 라이브 스코어링과 같은 코드를 쓰되
        # forward 필터만 이 경로에서 켠다 — 그 필터가 검증에는 맞고 최신 시점에는
        # 치명적이라는 것이 두 경로를 가른 이유다.
        row_names, row_groups, np_panel, fwd, n_fund = _panel_at(
            d, names, groups, series, fund, need_fund, require_forward=True)

        if len(row_names) < MIN_NAMES:
            continue
        try:
            scores = eval_node(node, np_panel, row_groups)
        except Exception as e:
            return {"error": True, "message": f"평가 실패: {e}"}
        m = np.isfinite(scores) & np.isfinite(np.asarray(fwd[1]))
        if m.sum() < MIN_NAMES:
            continue

        s = scores[m]
        period_dates.append(str(d))
        coverage.append(int(m.sum()))
        fund_cov.append(n_fund)

        for h in (1, 2, 3):
            r = np.asarray(fwd[h])[m]
            mh = np.isfinite(r)
            if mh.sum() >= MIN_NAMES:
                sr = _cs_rank(s[mh])
                rr = _cs_rank(r[mh])
                ic = float(np.corrcoef(sr, rr)[0, 1]) if np.std(sr) > 0 and np.std(rr) > 0 else 0.0
                ic_by_h[h].append(ic)

        r1 = np.asarray(fwd[1])[m]
        ranks = _cs_rank(s)
        qcut = np.minimum((ranks * quantiles).astype(int), quantiles - 1)
        for q in range(quantiles):
            qm = qcut == q
            if qm.sum() > 0:
                q_rets[q].append(float(np.nanmean(r1[qm])))
        top, bot = qcut == quantiles - 1, qcut == 0
        ls = (float(np.nanmean(r1[top])) - float(np.nanmean(r1[bot]))
              if top.sum() and bot.sum() else 0.0)
        ls_curve.append(ls_curve[-1] * (1.0 + ls))

        cur = {n_: float(v) for n_, v in zip(row_names, scores) if np.isfinite(v)}
        common = set(cur) & set(prev_scores)
        if len(common) >= MIN_NAMES:
            a = _cs_rank(np.array([cur[k] for k in common]))
            b = _cs_rank(np.array([prev_scores[k] for k in common]))
            turnover_sum += float(np.mean(np.abs(a - b)))
            turnover_n += 1
        prev_scores = cur

    n_periods = len(period_dates)
    if n_periods < 6:
        return {"error": True, "message": f"유효 기간 {n_periods}개 (<6) — 커버리지가 부족합니다."}

    def _agg(ics: list[float]) -> dict:
        if not ics:
            return {"mean": None, "icir": None, "t_stat": None, "hit_rate": None}
        arr = np.asarray(ics)
        mu, sd = float(arr.mean()), float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        return {"mean": round(mu, 4),
                "icir": round(mu / sd, 3) if sd > 1e-9 else None,
                "t_stat": round(mu / sd * math.sqrt(len(arr)), 2) if sd > 1e-9 else None,
                "hit_rate": round(float((arr > 0).mean()) * 100, 1)}

    half = n_periods // 2
    ic1 = ic_by_h[1]
    q_ann = [round((np.mean(qr) * 12) * 100, 2) if qr else None for qr in q_rets]
    valid_q = [q for q in q_ann if q is not None]
    mono = None
    if len(valid_q) == quantiles:
        qr_rank = _cs_rank(np.asarray(valid_q, dtype=float))
        mono = round(float(np.corrcoef(qr_rank, np.arange(quantiles))[0, 1]), 3)

    ls_ret = np.diff(np.asarray(ls_curve)) / np.asarray(ls_curve[:-1])
    ls_sharpe = (round(float(ls_ret.mean() / ls_ret.std(ddof=1) * math.sqrt(12)), 2)
                 if len(ls_ret) > 2 and ls_ret.std(ddof=1) > 1e-9 else None)
    peak = np.maximum.accumulate(ls_curve)
    ls_mdd = round(float(((np.asarray(ls_curve) - peak) / peak).min()) * 100, 2)

    notes = ["거래비용·슬리피지 미반영 — 실제 수익률은 회전율만큼 낮아집니다 (비용 모델은 P3~P4).",
             "IC는 Rank IC(스피어만) — 월간 리밸런스, 1/2/3개월 지평."]
    if need_fund:
        total_fund = sum(fund_cov)
        if total_fund == 0:
            notes.append("펀더멘털 필드 커버리지 0 — financials_history 미적재 환경(정직 결측). "
                         "실데이터(GCP)에서 재검증 필요.")
        else:
            notes.append(f"펀더멘털: 연간 보고서 + {FUND_LAG_MONTH}월 공시랙 (분기·정정공시 미반영).")

    return {
        "error": False,
        "expr": expr,
        "n_periods": n_periods,
        "period_start": period_dates[0], "period_end": period_dates[-1],
        "universe_size": len(series), "avg_coverage": round(float(np.mean(coverage)), 1),
        "ic": _agg(ic1),
        "decay": {"1m": _agg(ic_by_h[1])["mean"], "2m": _agg(ic_by_h[2])["mean"],
                  "3m": _agg(ic_by_h[3])["mean"]},
        "is_oos": {"is_ic": _agg(ic1[:half])["mean"], "oos_ic": _agg(ic1[half:])["mean"],
                   "split": f"{half}/{n_periods - half}"},
        "quantiles": {"n": quantiles, "ann_return_pct": q_ann, "monotonicity": mono},
        "long_short": {"curve": [round(v, 4) for v in ls_curve],
                       "total_return_pct": round((ls_curve[-1] - 1) * 100, 2),
                       "sharpe": ls_sharpe, "mdd_pct": ls_mdd},
        "turnover_proxy": round(turnover_sum / turnover_n, 3) if turnover_n else None,
        "latest_scores_top": _latest_top(prev_scores, 20),
        "notes": notes,
    }


def _latest_top(scores: dict[str, float], k: int) -> list[dict]:
    top = sorted(scores.items(), key=lambda x: -x[1])[:k]
    try:
        from src.data.stock_master import get_stock_name
        return [{"ticker": t, "name": get_stock_name(t) or t, "score": round(s, 4)} for t, s in top]
    except Exception:
        return [{"ticker": t, "name": t, "score": round(s, 4)} for t, s in top]
