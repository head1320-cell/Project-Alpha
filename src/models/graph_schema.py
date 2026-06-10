"""
Graph Backtest Schema — Enterprise Grade
==========================================
Pydantic V2 Discriminated Union으로 노드 타입별 완벽 Validation.

Frontend React Flow JSON → 이 스키마 → DAG Runner

핵심: data.type 필드를 discriminator로 사용하여
      DataSourceNodeData | IndicatorNodeData | ConditionNodeData | ActionNodeData
      를 자동으로 구분하고 검증합니다.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

# ═══════════════════════════════════════════════════════════════════════════════
# Node Data Models — Discriminated Union (태그된 유니온)
# ═══════════════════════════════════════════════════════════════════════════════

class DataSourceNodeData(BaseModel):
    """데이터 소스 노드 — 종목/유니버스/타임프레임."""
    type: Literal["datasource"] = "datasource"
    symbol: str = Field(default="005930", min_length=1, max_length=20,
                        description="종목코드 (예: 005930)")
    universe: Literal["KOSPI", "KOSDAQ", "CUSTOM"] = "KOSPI"
    timeframe: Literal["1D", "1H", "15M"] = "1D"
    lookback: int = Field(default=200, ge=10, le=2000,
                          description="조회 기간 (거래일)")


class IndicatorNodeData(BaseModel):
    """기술 지표 노드 — 지표 ID + 파라미터 + 출력 선택."""
    type: Literal["indicator"] = "indicator"
    indicatorId: str = Field(default="rsi", min_length=1, max_length=50)
    label: str = "RSI"
    params: dict[str, Union[int, float]] = Field(
        default_factory=lambda: {"period": 14},
        description="지표 파라미터 (예: period, fast, slow)"
    )
    output: str = Field(default="value",
                        description="출력 채널 (value, signal, histogram, upper, lower 등)")

    @model_validator(mode="after")
    def validate_params(self):
        """파라미터 범위 기본 검증."""
        for k, v in self.params.items():
            if isinstance(v, (int, float)) and v < 0:
                raise ValueError(f"파라미터 '{k}'은 음수일 수 없습니다: {v}")
        return self


class ConditionNodeData(BaseModel):
    """조건 노드 — 연산자 + 비교값 + AND/OR 로직."""
    type: Literal["condition"] = "condition"
    operator: Literal[">", "<", ">=", "<=", "==", "!=",
                      "crosses_above", "crosses_below"] = ">"
    compareValue: float | None = Field(default=70.0,
                                          description="비교 기준값 (None이면 다른 지표와 비교)")
    compareIndicator: str | None = Field(default=None,
                                            description="비교 대상 지표 노드 ID")
    logic: Literal["AND", "OR"] = "AND"


class ActionNodeData(BaseModel):
    """매매 실행 노드 — 매수/매도 + 비중 + 리스크 관리."""
    type: Literal["action"] = "action"
    action: Literal["BUY", "SELL", "HOLD"] = "BUY"
    sizeType: Literal["percent", "fixed", "all"] = "percent"
    sizeValue: float = Field(default=100, ge=0, le=100000)
    stopLoss: float | None = Field(default=None, ge=0, le=100,
                                      description="손절 % (None=미사용)")
    takeProfit: float | None = Field(default=None, ge=0, le=1000,
                                        description="익절 % (None=미사용)")


# ── Discriminated Union ──────────────────────────────────────────────────────
# type 필드를 기준으로 자동 분기
NodeData = Annotated[
    Union[
        Annotated[DataSourceNodeData, Field(discriminator=None)],
        Annotated[IndicatorNodeData,  Field(discriminator=None)],
        Annotated[ConditionNodeData,  Field(discriminator=None)],
        Annotated[ActionNodeData,     Field(discriminator=None)],
    ],
    Field(discriminator="type"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Graph Structure — React Flow 1:1 대응
# ═══════════════════════════════════════════════════════════════════════════════

class GraphNode(BaseModel):
    """React Flow 노드. data는 type 기반 Discriminated Union으로 자동 파싱."""
    id: str = Field(..., min_length=1)
    type: str  # "dataSource" | "indicator" | "condition" | "action"
    position: dict[str, float]
    data: dict[str, Any]  # 런타임에 parse_data()로 타입 변환

    # React Flow 메타 (무시)
    selected: bool | None = None
    dragging: bool | None = None
    width: float | None = None
    height: float | None = None
    measured: dict[str, Any] | None = None

    class Config:
        extra = "ignore"

    def parse_data(self) -> Union[DataSourceNodeData, IndicatorNodeData,
                                   ConditionNodeData, ActionNodeData]:
        """data dict → 타입별 Pydantic 모델. Discriminator 수동 적용."""
        t = self.data.get("type", "")

        # React Flow type → data.type 매핑
        type_map = {
            "datasource": DataSourceNodeData,
            "dataSource": DataSourceNodeData,
            "indicator":  IndicatorNodeData,
            "condition":  ConditionNodeData,
            "action":     ActionNodeData,
        }

        model_cls = type_map.get(t) or type_map.get(self.type)
        if model_cls is None:
            raise ValueError(
                f"Unknown node type: data.type='{t}', node.type='{self.type}'. "
                f"Valid types: {list(type_map.keys())}"
            )

        return model_cls.model_validate(self.data)


class GraphEdge(BaseModel):
    """React Flow 엣지."""
    id: str | None = None
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    sourceHandle: str | None = None
    targetHandle: str | None = None

    # React Flow 메타 (무시)
    animated: bool | None = None
    style: dict[str, Any] | None = None
    markerEnd: dict[str, Any] | None = None

    class Config:
        extra = "ignore"

    @model_validator(mode="after")
    def no_self_loop(self):
        if self.source == self.target:
            raise ValueError(f"Self-loop detected: {self.source} → {self.target}")
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# Request / Response
# ═══════════════════════════════════════════════════════════════════════════════

class GraphBacktestRequest(BaseModel):
    """POST /api/v1/backtest/graph 요청 모델."""
    nodes: list[GraphNode] = Field(..., min_length=1,
                                   description="최소 1개 노드 필요")
    edges: list[GraphEdge] = Field(default_factory=list)

    initial_capital: float = Field(default=100_000_000, gt=0)
    commission_rate: float = Field(default=0.0015, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    start_date: str | None = None
    end_date: str | None = None

    class Config:
        extra = "ignore"

    @model_validator(mode="after")
    def validate_node_ids_unique(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            dupes = [x for x in ids if ids.count(x) > 1]
            raise ValueError(f"Duplicate node IDs: {set(dupes)}")
        return self

    @model_validator(mode="after")
    def validate_edge_references(self):
        valid_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in valid_ids:
                raise ValueError(f"Edge source '{edge.source}' not found in nodes")
            if edge.target not in valid_ids:
                raise ValueError(f"Edge target '{edge.target}' not found in nodes")
        return self


class TradeRecord(BaseModel):
    """개별 체결 내역."""
    date: str
    ticker: str
    side: Literal["buy", "sell"]
    price: float
    quantity: int
    value: float
    pnl: float | None = None
    reason: str = ""


class BacktestStatistics(BaseModel):
    """백테스트 핵심 통계 12개."""
    total_return_pct: float = 0.0
    cagr: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    num_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade_return: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0


class GraphBacktestResponse(BaseModel):
    """백테스트 결과 전체."""
    success: bool = True
    message: str = ""
    parsed_strategy: dict[str, Any] = Field(default_factory=dict)
    statistics: BacktestStatistics = Field(default_factory=BacktestStatistics)
    equity_curve: list[float] = Field(default_factory=list)
    equity_dates: list[str] = Field(default_factory=list)
    drawdown_curve: list[float] = Field(default_factory=list)
    monthly_returns: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    symbol_results: list[dict[str, Any]] = Field(default_factory=list)
