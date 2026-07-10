"""
Filter AST — Milestone 1 (Macro-Aware Visual Screener)
==========================================================================
절대값 + 상대 랭킹(상위 N%) 필터를 AND/OR 중첩 그룹으로 평가하는 표현식 엔진.

데이터 계약:
  FilterCondition  — 단일 조건 (절대값 또는 랭킹)
  FilterGroup      — AND/OR 논리 + 조건 + 중첩 그룹 (재귀)

평가 전략 (2-Pass):
  Pass 1: 전 종목 평가 (screener.py의 ThreadPool — 변경 없음)
  Pass 2: 랭킹 컨텍스트 구축 (percentile/rank) → 각 종목에 AST 평가

랭킹 정의:
  top_pct    — 값 내림차순 상위 N% (ROE 상위 10% → 높은 ROE)
  bottom_pct — 값 오름차순 하위 N% (PER 하위 10% → 낮은 PER)
  top_n      — 값 내림차순 상위 N개

설계 원칙:
  · field별 정렬 방향은 엔진이 강제하지 않음 (top/bottom으로 명시)
  · UI 레이어가 FIELD_META.higher_better로 방향 자동 매핑
  · None 값은 항상 조건 불통과 (방어적)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Field Metadata — 필터 가능 필드 카탈로그
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FieldMeta:
    id: str
    label: str
    category: str          # valuation | profitability | growth | dividend | stability | score
    unit: str
    higher_better: bool    # True면 "상위 N%"가 높은 값 (ROE), False면 낮은 값 선호 (PER)
    typical_min: float
    typical_max: float


FIELD_CATALOG: list[FieldMeta] = [
    # 밸류에이션
    FieldMeta("per",            "PER",          "valuation",     "배",  False, 0,   50),
    FieldMeta("pbr",            "PBR",          "valuation",     "배",  False, 0,   10),
    FieldMeta("gap_pct",        "괴리율",        "valuation",     "%",   False, -80, 80),
    FieldMeta("intrinsic_value", "적정가",        "valuation",     "원",  True,  0,   1000000),
    # 수익성
    FieldMeta("roe_pct",        "ROE",          "profitability", "%",   True,  -10, 40),
    FieldMeta("roa_pct",        "ROA",          "profitability", "%",   True,  -10, 25),
    # 배당
    FieldMeta("dividend_yield_pct", "배당수익률",  "dividend",      "%",   True,  0,   10),
    # 안정성
    FieldMeta("debt_ratio_pct", "부채비율",      "stability",     "%",   False, 0,   300),
    FieldMeta("fcf_억",         "잉여현금흐름",   "stability",     "억",  True,  -5000, 50000),
    # 시가총액은 규모(Size) 팩터 — 안정성 아님 (CIO 실사: 팩터 분류 체계 재정립)
    FieldMeta("market_cap_억",  "시가총액",      "size",          "억",  True,  0,   5000000),
    # 종합 스코어
    FieldMeta("composite_score", "종합 점수",     "score",         "점",  True,  0,   100),
    FieldMeta("gap_score",      "저평가 점수",    "score",         "점",  True,  0,   100),
    FieldMeta("roe_score",      "수익성 점수",    "score",         "점",  True,  0,   100),
    FieldMeta("stability_score", "안정성 점수",   "score",         "점",  True,  0,   100),
]

# ─── FFL: 펀더멘털 팩터를 FIELD_CATALOG에 자동 등록 ───
def _register_fundamental_fields():
    """Fundamental Factor Library의 50+ 팩터를 FIELD_CATALOG에 병합."""
    try:
        from src.data.fundamentals_store import FUNDAMENTAL_FACTORS
        for fac in FUNDAMENTAL_FACTORS:
            if fac.id not in FIELD_BY_ID:
                meta = FieldMeta(fac.id, fac.label, fac.category, fac.unit,
                                 fac.higher_better, fac.typical_min, fac.typical_max)
                FIELD_CATALOG.append(meta)
                FIELD_BY_ID[fac.id] = meta
    except Exception as e:
        logger.debug(f"펀더멘털 팩터 등록 실패: {e}")

FIELD_BY_ID: dict[str, FieldMeta] = {f.id: f for f in FIELD_CATALOG}
_register_fundamental_fields()  # FFL: 50+ 펀더멘털 팩터 병합


def _register_price_fields():
    """가격·수급 팩터(KIS OHLCV 파생)를 FIELD_CATALOG에 병합."""
    try:
        from src.data.price_factors_store import PRICE_FACTORS
        for fac in PRICE_FACTORS:
            if fac.id not in FIELD_BY_ID:
                meta = FieldMeta(fac.id, fac.label, fac.category, fac.unit,
                                 fac.higher_better, fac.typical_min, fac.typical_max)
                FIELD_CATALOG.append(meta)
                FIELD_BY_ID[fac.id] = meta
    except Exception as e:
        logger.debug(f"가격 팩터 등록 실패: {e}")

_register_price_fields()  # 가격·수급 팩터 병합


def _register_extended_fields():
    """Butler 확장 팩터(배당·지분율·사업정보 — extended_factors_store)를 FIELD_CATALOG에 병합."""
    try:
        from src.data.extended_factors_store import EXTENDED_FACTORS
        for fac in EXTENDED_FACTORS:
            if fac.id not in FIELD_BY_ID:
                meta = FieldMeta(fac.id, fac.label, fac.category, fac.unit,
                                 fac.higher_better, fac.typical_min, fac.typical_max)
                FIELD_CATALOG.append(meta)
                FIELD_BY_ID[fac.id] = meta
    except Exception as e:
        logger.debug(f"확장 팩터 등록 실패: {e}")

_register_extended_fields()  # Butler 확장 팩터 병합

CATEGORY_LABELS = {
    "size":          "규모",
    "valuation":     "밸류에이션",
    "profitability": "수익성",
    "growth":        "성장성",
    "dividend":      "배당",
    "ownership":     "지분율",
    "business":      "사업정보",
    "stability":     "안정성",
    "score":         "종합 스코어",
    "momentum":      "모멘텀",
    "volatility":    "변동성",
    "technical":     "기술 위치",
    "volume":        "거래",
    "supply":        "수급",
}

VALID_OPS = {"lt", "lte", "gt", "gte", "eq", "between"}
VALID_RANK_MODES = {None, "top_pct", "bottom_pct", "top_n"}


# ═══════════════════════════════════════════════════════════════════════════════
# Data Contract
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FilterCondition:
    """단일 필터 조건 (V2: kind 디스패처)."""
    field: str
    op: str = "lt"                      # lt|lte|gt|gte|eq|between
    value: Any = None                   # 절대값 (rank_mode None일 때)
    value2: float | None = None      # between 상한
    rank_mode: str | None = None     # None|top_pct|bottom_pct|top_n
    rank_value: float | None = None  # 상위 10% → 10
    # ─── V2 확장 ───
    kind: str = "field"                 # field | formula | peer | technical | event
    formula: str | None = None       # "(per*0.4)+(pbr*0.6)" — Custom Formula
    peer_scope: str | None = None    # "sector" | "market" — Peer-Relative 기준
    peer_stat: str | None = None     # "mean" | "median" | "rank_pct"
    indicator: str | None = None     # M3: rsi_14|macd_hist|foreign_net_5d 등
    event_type: str | None = None    # M3: earnings|ex_dividend
    within_days: int | None = None   # M3: 이벤트 임박 일수
    # ─── V3 확장 ───
    estimate_field: str | None = None  # V3-M1: fwd_eps_1m_chg|fwd_per|revision_score
    z_field: str | None = None         # V3-M2: Z-Score 대상 지표
    z_window: int | None = None        # V3-M2: 롤링 윈도우 (분기 수)
    behavior_signal: str | None = None # V3-M3: insider_buy_retail_sell|smart_divergence 등
    graph_target: str | None = None    # V3-M4: 기준 종목 코드
    graph_relation: str | None = None  # V3-M4: supplier|customer|competitor
    graph_depth: int | None = None     # V3-M4: 탐색 깊이 (1-3)
    sentiment_source: str | None = None # V3-M5: news|earnings_call
    vector_ticker: str | None = None    # V3-M6: 유사도 기준 종목
    vector_threshold: float | None = None # V3-M6: 코사인 유사도 임계

    def validate(self) -> str | None:
        # V2: formula는 field 검증 스킵 (수식 파서가 검증)
        if self.kind == "formula":
            if not self.formula:
                return "formula required for kind=formula"
            from src.engine.formula_parser import validate_formula
            ok, err, _ = validate_formula(self.formula, set(FIELD_BY_ID.keys()))
            if not ok:
                return f"수식 오류: {err}"
            if self.op not in VALID_OPS:
                return f"Invalid op: {self.op}"
            return None

        # technical/event/estimate/z_score는 field 대신 전용 필드 사용 → 위에서 이미 검증/반환
        if self.kind in ("technical", "event", "estimate", "z_score", "behavioral", "graph", "sentiment", "vector_sim"):
            pass  # 도달 안 함 (위에서 return)
        elif self.field not in FIELD_BY_ID:
            return f"Unknown field: {self.field}"

        # V2: peer 검증
        if self.kind == "peer":
            if self.peer_scope not in ("sector", "market"):
                return f"Invalid peer_scope: {self.peer_scope}"
            if self.peer_stat not in ("mean", "median", "rank_pct"):
                return f"Invalid peer_stat: {self.peer_stat}"
            if self.peer_stat == "rank_pct":
                if self.rank_value is None or self.rank_value <= 0:
                    return "rank_value required for peer rank_pct"
            else:
                if self.op not in VALID_OPS:
                    return f"Invalid op: {self.op}"
            return None

        # V3-M5: sentiment 검증
        if self.kind == "sentiment":
            from src.services.sentiment_worker import SENTIMENT_SOURCES
            if self.sentiment_source not in SENTIMENT_SOURCES:
                return f"Unknown sentiment_source: {self.sentiment_source}"
            if self.op not in VALID_OPS:
                return f"Invalid op: {self.op}"
            if self.value is None:
                return "value (sentiment threshold) required"
            return None

        # V3-M6: vector_sim 검증
        if self.kind == "vector_sim":
            if not self.vector_ticker:
                return "vector_ticker required"
            if self.vector_threshold is None or not (0 <= self.vector_threshold <= 1):
                return "vector_threshold must be 0~1"
            return None

        # V3-M3: behavioral 검증
        if self.kind == "behavioral":
            from src.data.market_data import BEHAVIOR_SIGNALS
            if self.behavior_signal not in BEHAVIOR_SIGNALS:
                return f"Unknown behavior_signal: {self.behavior_signal}"
            return None

        # V3-M4: graph 검증
        if self.kind == "graph":
            if not self.graph_target:
                return "graph_target required"
            if self.graph_relation not in ("supplier", "customer", "competitor"):
                return f"Invalid graph_relation: {self.graph_relation}"
            return None

        # V3-M1: estimate 검증
        if self.kind == "estimate":
            from src.data.consensus_store import ESTIMATE_BY_ID
            if self.estimate_field not in ESTIMATE_BY_ID:
                return f"Unknown estimate_field: {self.estimate_field}"
            if self.op not in VALID_OPS:
                return f"Invalid op: {self.op}"
            if self.value is None:
                return "value required for estimate"
            return None

        # V3-M2: z_score 검증
        if self.kind == "z_score":
            if self.z_field not in FIELD_BY_ID:
                return f"Unknown z_field: {self.z_field}"
            if self.op not in VALID_OPS:
                return f"Invalid op: {self.op}"
            if self.value is None:
                return "value (sigma threshold) required for z_score"
            return None

        # V2-M3: technical 검증
        if self.kind == "technical":
            from src.data.market_data import INDICATOR_BY_ID
            if self.indicator not in INDICATOR_BY_ID:
                return f"Unknown indicator: {self.indicator}"
            if self.op not in VALID_OPS:
                return f"Invalid op: {self.op}"
            if self.value is None:
                return "value required for technical"
            return None

        # V2-M3: event 검증
        if self.kind == "event":
            from src.data.event_calendar import EVENT_BY_ID
            if self.event_type not in EVENT_BY_ID:
                return f"Unknown event_type: {self.event_type}"
            if self.within_days is None or self.within_days < 0:
                return "within_days required for event"
            return None

        if self.rank_mode is not None:
            if self.rank_mode not in VALID_RANK_MODES:
                return f"Invalid rank_mode: {self.rank_mode}"
            if self.rank_value is None or self.rank_value <= 0:
                return f"rank_value required for {self.rank_mode}"
        else:
            if self.op not in VALID_OPS:
                return f"Invalid op: {self.op}"
            if self.value is None:
                return f"value required for op {self.op}"
            if self.op == "between" and self.value2 is None:
                return "value2 required for between"
        return None


@dataclass
class FilterGroup:
    """AND/OR 논리 그룹 (재귀 중첩 가능)."""
    logic: str = "AND"                          # AND | OR
    conditions: list[FilterCondition] = field(default_factory=list)
    groups: list[FilterGroup] = field(default_factory=list)

    def validate(self) -> str | None:
        if self.logic not in ("AND", "OR"):
            return f"Invalid logic: {self.logic}"
        for c in self.conditions:
            err = c.validate()
            if err:
                return err
        for g in self.groups:
            err = g.validate()
            if err:
                return err
        return None

    def is_empty(self) -> bool:
        return not self.conditions and not self.groups


# ═══════════════════════════════════════════════════════════════════════════════
# Parsing — dict → AST (API 수신용)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_condition(d: dict) -> FilterCondition:
    return FilterCondition(
        field=d.get("field", ""),
        op=d.get("op", "lt"),
        value=d.get("value"),
        value2=d.get("value2"),
        rank_mode=d.get("rank_mode"),
        rank_value=d.get("rank_value"),
        kind=d.get("kind", "field"),
        formula=d.get("formula"),
        peer_scope=d.get("peer_scope"),
        peer_stat=d.get("peer_stat"),
        indicator=d.get("indicator"),
        event_type=d.get("event_type"),
        within_days=d.get("within_days"),
        estimate_field=d.get("estimate_field"),
        z_field=d.get("z_field"),
        z_window=d.get("z_window"),
        behavior_signal=d.get("behavior_signal"),
        graph_target=d.get("graph_target"),
        graph_relation=d.get("graph_relation"),
        graph_depth=d.get("graph_depth"),
        sentiment_source=d.get("sentiment_source"),
        vector_ticker=d.get("vector_ticker"),
        vector_threshold=d.get("vector_threshold"),
    )


def parse_group(d: dict) -> FilterGroup:
    return FilterGroup(
        logic=d.get("logic", "AND"),
        conditions=[parse_condition(c) for c in d.get("conditions", [])],
        groups=[parse_group(g) for g in d.get("groups", [])],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Rank Context — 랭킹 percentile/rank 사전 계산
# ═══════════════════════════════════════════════════════════════════════════════

def collect_rank_fields(group: FilterGroup) -> set[str]:
    """AST에서 랭킹 모드를 쓰는 필드 수집 (Pass 2 최적화)."""
    fields: set[str] = set()
    for c in group.conditions:
        if c.kind == "field" and c.rank_mode is not None:
            fields.add(c.field)
    for g in group.groups:
        fields |= collect_rank_fields(g)
    return fields


def collect_technical_used(group: FilterGroup) -> bool:
    """technical/event 조건 사용 여부 (lazy 계산 트리거)."""
    for c in group.conditions:
        if c.kind in ("technical", "event"):
            return True
    for g in group.groups:
        if collect_technical_used(g):
            return True
    return False


def collect_peer_specs(group: FilterGroup) -> set[tuple]:
    """Peer 조건의 (field, scope) 쌍 수집 → peer context 사전계산용."""
    specs: set[tuple] = set()
    for c in group.conditions:
        if c.kind == "peer":
            specs.add((c.field, c.peer_scope or "sector"))
    for g in group.groups:
        specs |= collect_peer_specs(g)
    return specs


def build_peer_context(items: list, peer_specs: set[tuple]) -> dict:
    """
    Peer 그룹별 통계 사전계산 (2-Pass 유지).
      peer_ctx[(field, scope)] = {
          "groups": {group_key: {"mean":, "median":, "values":[...]}},
          "stock_group": {code: group_key},
          "stock_pct": {code: percentile_within_group},
      }
    scope="sector" → sector별, "market" → 전체 단일 그룹.
    """
    import statistics
    peer_ctx: dict = {}
    for (fld, scope) in peer_specs:
        groups: dict = {}        # group_key → [values]
        stock_group: dict = {}   # code → group_key
        stock_val: dict = {}     # code → value
        for it in items:
            val = getattr(it, fld, None)
            if val is None:
                continue
            code = it.stock_code
            gkey = (getattr(it, "sector", None) or "기타") if scope == "sector" else "__market__"
            groups.setdefault(gkey, []).append(val)
            stock_group[code] = gkey
            stock_val[code] = val

        group_stats = {}
        for gkey, vals in groups.items():
            if len(vals) >= 1:
                group_stats[gkey] = {
                    "mean": statistics.mean(vals),
                    "median": statistics.median(vals),
                    "n": len(vals),
                    "sorted": sorted(vals),
                }

        # 그룹 내 percentile
        stock_pct = {}
        for code, gkey in stock_group.items():
            gs = group_stats.get(gkey)
            if not gs or gs["n"] < 1:
                continue
            v = stock_val[code]
            below = sum(1 for x in gs["sorted"] if x <= v)
            stock_pct[code] = below / gs["n"] * 100

        peer_ctx[(fld, scope)] = {
            "groups": group_stats,
            "stock_group": stock_group,
            "stock_pct": stock_pct,
        }
    return peer_ctx


def build_rank_context(items: list, rank_fields: set[str]) -> dict:
    """
    랭킹 필드별 percentile + rank 맵 구축.
      ctx[field]["pct"][code]  = percentile (0-100, 값 클수록 높음)
      ctx[field]["rank"][code] = 내림차순 순위 (1 = 가장 큼)
    """
    ctx: dict[str, dict] = {}
    for fld in rank_fields:
        pairs = [(it.stock_code, getattr(it, fld, None)) for it in items]
        valid = [(code, v) for code, v in pairs if v is not None]
        n = len(valid)
        if n == 0:
            ctx[fld] = {"pct": {}, "rank": {}}
            continue

        # percentile: 오름차순 정렬 후 위치 → 값 클수록 100에 가까움
        asc = sorted(valid, key=lambda x: x[1])
        pct_map = {code: (i + 1) / n * 100 for i, (code, _v) in enumerate(asc)}

        # rank: 내림차순 (1 = 최대값)
        desc = sorted(valid, key=lambda x: -x[1])
        rank_map = {code: r for r, (code, _v) in enumerate(desc, 1)}

        ctx[fld] = {"pct": pct_map, "rank": rank_map}
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_absolute(val: float, cond: FilterCondition) -> bool:
    op = cond.op
    v = cond.value
    try:
        if op == "lt":      return val < v
        if op == "lte":     return val <= v
        if op == "gt":      return val > v
        if op == "gte":     return val >= v
        if op == "eq":      return abs(val - v) < 1e-9
        if op == "between": return v <= val <= (cond.value2 if cond.value2 is not None else v)
    except (TypeError, ValueError):
        return False
    return False


def _eval_rank(code: str, cond: FilterCondition, ctx: dict) -> bool:
    field_ctx = ctx.get(cond.field)
    if not field_ctx:
        return False

    if cond.rank_mode == "top_pct":
        pct = field_ctx["pct"].get(code)
        if pct is None:
            return False
        # 상위 N% → percentile >= (100 - N)
        return pct >= (100 - cond.rank_value)

    if cond.rank_mode == "bottom_pct":
        pct = field_ctx["pct"].get(code)
        if pct is None:
            return False
        # 하위 N% → percentile <= N
        return pct <= cond.rank_value

    if cond.rank_mode == "top_n":
        rank = field_ctx["rank"].get(code)
        if rank is None:
            return False
        return rank <= cond.rank_value

    return False


def eval_condition(item, cond: FilterCondition, ctx: dict) -> bool:
    """kind 디스패처 — field(V1) / formula / peer / technical / event."""
    if cond.kind == "formula":
        return _eval_formula(item, cond)
    if cond.kind == "peer":
        return _eval_peer(item, cond, ctx)
    if cond.kind == "technical":
        return _eval_technical(item, cond, ctx)
    if cond.kind == "event":
        return _eval_event(item, cond, ctx)
    # V3: 등록 테이블 기반 신규 kind (estimate/z_score/graph/sentiment/vector...)
    if cond.kind in EVAL_DISPATCH_V3:
        return EVAL_DISPATCH_V3[cond.kind](item, cond, ctx)

    # kind == "field" (V1 기본)
    val = getattr(item, cond.field, None)
    code = getattr(item, "stock_code", None)

    if cond.rank_mode is not None:
        if code is None:
            return False
        return _eval_rank(code, cond, ctx)

    if val is None:
        return False
    return _eval_absolute(val, cond)


def _eval_formula(item, cond: FilterCondition) -> bool:
    """Custom Formula 평가 — 수식 계산 후 op 비교."""
    from src.engine.formula_parser import extract_fields, safe_eval_formula
    if not cond.formula:
        return False
    fields = extract_fields(cond.formula)
    fv = {f: getattr(item, f, None) for f in fields}
    result = safe_eval_formula(cond.formula, fv)
    if result is None:
        return False
    # op 비교 (계산값 vs cond.value)
    tmp = FilterCondition(field="__formula__", op=cond.op, value=cond.value, value2=cond.value2)
    return _eval_absolute(result, tmp)


def _eval_peer(item, cond: FilterCondition, ctx: dict) -> bool:
    """Peer-Relative 평가 — 섹터/시장 통계 대비 비교."""
    peer_ctx = ctx.get("_peer", {})
    key = (cond.field, cond.peer_scope or "sector")
    pc = peer_ctx.get(key)
    if not pc:
        return False
    code = getattr(item, "stock_code", None)
    if code is None:
        return False

    # rank_pct: 그룹 내 상위 N%
    if cond.peer_stat == "rank_pct":
        pct = pc["stock_pct"].get(code)
        if pct is None:
            return False
        # 상위 N% → percentile >= 100 - N
        return pct >= (100 - (cond.rank_value or 0))

    # mean/median 대비 비교
    val = getattr(item, cond.field, None)
    if val is None:
        return False
    gkey = pc["stock_group"].get(code)
    gs = pc["groups"].get(gkey)
    if not gs:
        return False
    if gs["n"] < 3:  # 표본 부족 → 스킵 (불통과)
        return False
    ref = gs["mean"] if cond.peer_stat == "mean" else gs["median"]
    tmp = FilterCondition(field="__peer__", op=cond.op, value=ref)
    return _eval_absolute(val, tmp)


def _eval_technical(item, cond: FilterCondition, ctx: dict) -> bool:
    """기술지표/수급 평가 — lazy 주입된 _tech 컨텍스트 사용."""
    tech = ctx.get("_tech", {})
    code = getattr(item, "stock_code", None)
    ind_data = tech.get(code)
    if not ind_data:
        return False
    val = ind_data.get(cond.indicator)
    if val is None:
        return False
    tmp = FilterCondition(field="__tech__", op=cond.op, value=cond.value, value2=cond.value2)
    return _eval_absolute(val, tmp)


def _eval_event(item, cond: FilterCondition, ctx: dict) -> bool:
    """이벤트 임박 평가 — lazy 주입된 _event 컨텍스트 사용."""
    events = ctx.get("_event", {})
    code = getattr(item, "stock_code", None)
    ev_data = events.get(code)
    if not ev_data:
        return False
    key = f"{cond.event_type}_days"
    days = ev_data.get(key)
    if days is None:
        return False
    # within_days 이내 → 통과
    return days <= cond.within_days


def eval_group(item, group: FilterGroup, ctx: dict) -> bool:
    """재귀 AND/OR 평가."""
    results: list[bool] = []

    for c in group.conditions:
        results.append(eval_condition(item, c, ctx))
    for g in group.groups:
        results.append(eval_group(item, g, ctx))

    if not results:
        return True  # 빈 그룹은 통과 (필터 없음)

    if group.logic == "AND":
        return all(results)
    return any(results)


# ═══════════════════════════════════════════════════════════════════════════════
# Public: filter items
# ═══════════════════════════════════════════════════════════════════════════════

def apply_filter_ast(items: list, group: FilterGroup) -> list:
    """
    종목 리스트에 AST 필터 적용.
      1. 랭킹 필드 수집
      2. 랭킹 컨텍스트 구축 (전체 기준)
      3. 각 종목 평가
    """
    if group.is_empty():
        return items

    rank_fields = collect_rank_fields(group)
    ctx = build_rank_context(items, rank_fields) if rank_fields else {}

    # V2: Peer context 추가
    peer_specs = collect_peer_specs(group)
    if peer_specs:
        ctx["_peer"] = build_peer_context(items, peer_specs)

    # V2-M3: Technical/Event context (lazy — 조건 있을 때만 계산)
    if collect_technical_used(group):
        from src.data.event_calendar import EventCalendar
        from src.data.market_data import MarketDataProvider
        mdp = MarketDataProvider.get_default()
        ec = EventCalendar.get_default()
        tech_ctx, event_ctx = {}, {}
        for it in items:
            code = getattr(it, "stock_code", None)
            if not code:
                continue
            tech_ctx[code] = mdp.get_indicators(code)
            event_ctx[code] = ec.get_events(code)
        ctx["_tech"] = tech_ctx
        ctx["_event"] = event_ctx

    # V3: 확장 가능한 lazy-context 빌더 (M1+ 신규 kind들이 여기 등록)
    #   각 빌더는 (group, items) → dict 를 반환하여 ctx에 병합
    for kind_name, builder in LAZY_CONTEXT_BUILDERS.items():
        if _kind_used(group, kind_name):
            try:
                extra = builder(group, items)
                if extra:
                    ctx.update(extra)
            except Exception as e:
                logger.warning(f"lazy context 빌드 실패 ({kind_name}): {e}")

    return [it for it in items if eval_group(it, group, ctx)]


# ═══════════════════════════════════════════════════════════════════════════════
# V3: Lazy Context 등록 테이블 (확장점)
# ═══════════════════════════════════════════════════════════════════════════════
#
# 신규 kind 추가 시:
#   1. EVAL_DISPATCH_V3에 평가 함수 등록
#   2. LAZY_CONTEXT_BUILDERS에 컨텍스트 빌더 등록 (무거운 데이터일 때)
#   → apply_filter_ast / eval_condition 수정 없이 자동 통합
#
# builder signature: (group: FilterGroup, items: list) -> dict (ctx에 병합될 키들)

LAZY_CONTEXT_BUILDERS: dict[str, callable] = {}
EVAL_DISPATCH_V3: dict[str, callable] = {}


def register_kind(kind_name: str, evaluator: callable, context_builder: callable = None):
    """V3 신규 kind 등록 (평가기 + 선택적 lazy 컨텍스트 빌더)."""
    EVAL_DISPATCH_V3[kind_name] = evaluator
    if context_builder is not None:
        LAZY_CONTEXT_BUILDERS[kind_name] = context_builder


def _kind_used(group: FilterGroup, kind_name: str) -> bool:
    """특정 kind가 AST에 존재하는지 (lazy 트리거)."""
    for c in group.conditions:
        if c.kind == kind_name:
            return True
    for g in group.groups:
        if _kind_used(g, kind_name):
            return True
    return False


def fields_catalog() -> dict:
    """API용 필드 카탈로그 (카테고리별 그룹)."""
    by_cat: dict[str, list] = {}
    for f in FIELD_CATALOG:
        by_cat.setdefault(f.category, []).append(asdict(f))
    return {
        "categories": [
            {"id": cat, "label": CATEGORY_LABELS.get(cat, cat), "fields": flds}
            for cat, flds in by_cat.items()
        ],
        "operators": [
            {"id": "lt", "label": "<", "name": "미만"},
            {"id": "lte", "label": "≤", "name": "이하"},
            {"id": "gt", "label": ">", "name": "초과"},
            {"id": "gte", "label": "≥", "name": "이상"},
            {"id": "between", "label": "~", "name": "범위"},
        ],
        "rank_modes": [
            {"id": "top_pct", "label": "상위 %", "name": "상위 N%"},
            {"id": "bottom_pct", "label": "하위 %", "name": "하위 N%"},
            {"id": "top_n", "label": "상위 N개", "name": "상위 N종목"},
        ],
    }



# ═══════════════════════════════════════════════════════════════════════════════
# V3 kind 등록 (모듈 로드 시 자동)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_behavioral(item, cond, ctx: dict) -> bool:
    """V3-M3: 행동 신호 평가 — lazy 주입된 _behavior 컨텍스트 사용."""
    from src.data.market_data import eval_behavioral_signal
    bctx = ctx.get("_behavior", {})
    code = getattr(item, "stock_code", None)
    indicators = bctx.get(code)
    if not indicators:
        return False
    return eval_behavioral_signal(indicators, cond.behavior_signal)


def _collect_behavioral_used(group) -> bool:
    for c in group.conditions:
        if c.kind == "behavioral":
            return True
    for g in group.groups:
        if _collect_behavioral_used(g):
            return True
    return False


def build_behavioral_context(group, items) -> dict:
    """lazy: 행동 신호용 수급 데이터 일괄 조회."""
    if not _collect_behavioral_used(group):
        return {}
    from src.data.market_data import MarketDataProvider
    mdp = MarketDataProvider.get_default()
    bctx = {}
    for it in items:
        code = getattr(it, "stock_code", None)
        if code:
            bctx[code] = mdp.get_indicators(code)
    return {"_behavior": bctx}


def _register_v3_kinds():
    """V3 신규 kind를 등록 테이블에 등록 (지연 import로 순환 방지)."""
    try:
        from src.data.consensus_store import build_estimate_context, eval_estimate
        register_kind("estimate", eval_estimate, build_estimate_context)
    except Exception as e:
        logger.debug(f"estimate kind 등록 실패: {e}")

    try:
        from src.engine.z_score import build_z_score_context, eval_z_score
        register_kind("z_score", eval_z_score, build_z_score_context)
    except Exception as e:
        logger.debug(f"z_score kind 등록 실패: {e}")

    # M3: behavioral
    register_kind("behavioral", _eval_behavioral, build_behavioral_context)

    # M4: graph
    try:
        from src.engine.graph_store import build_graph_context, eval_graph
        register_kind("graph", eval_graph, build_graph_context)
    except Exception as e:
        logger.debug(f"graph kind 등록 실패: {e}")

    # M5: sentiment
    try:
        from src.services.sentiment_worker import build_sentiment_context, eval_sentiment
        register_kind("sentiment", eval_sentiment, build_sentiment_context)
    except Exception as e:
        logger.debug(f"sentiment kind 등록 실패: {e}")

    # M6: vector_sim
    try:
        from src.engine.vector_store import build_vector_context, eval_vector_sim
        register_kind("vector_sim", eval_vector_sim, build_vector_context)
    except Exception as e:
        logger.debug(f"vector_sim kind 등록 실패: {e}")


_register_v3_kinds()
