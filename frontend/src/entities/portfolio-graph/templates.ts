/**
 * 빈 캔버스용 시작 그래프 — 핵심 사슬(스펙 §4.3) + BK W6 템플릿 셋.
 * ★종목은 예시일 뿐이다★ — 유니버스 노드에서 바꾼다. mock 모드에서는 합성 수익률로 돌고,
 * 결과의 등급 배지가 그 사실을 말한다. ★템플릿은 파라미터 규칙을 새로 정하지 않는다★ — 비운 칸은
 * 서버 기본값이고, 옳은지는 서버 검증(`/graph/validate`)이 말한다(E2E 가 네 템플릿 모두 확인).
 */
import { GRAPH_FORMAT, GRAPH_VERSION, type GraphDoc } from "./types";
import { COL } from "./size";

/** 열 번호 → x (BS2) — 배치 격자(`COL`)에 맞춘다. 예전 손으로 적은 x(0·196·400·600…)는 열 틈이 46px 이라
 *  자동 정리 전에는 선 요약이 옆 카드를 덮었다. */
const c = (col: number) => col * COL;
const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) =>
  ({ id, type, params, position: { x, y } });
const e = (source: string, source_port: string, target: string, target_port: string) =>
  ({ id: `${source}.${source_port}->${target}.${target_port}`, source, source_port, target, target_port });

const doc = (name: string, nodes: GraphDoc["nodes"], edges: GraphDoc["edges"]): GraphDoc =>
  ({ format: GRAPH_FORMAT, version: GRAPH_VERSION, meta: { name }, nodes, edges });

const TICKERS = ["005930", "000660", "035420"];

/** 종목 → 수익률 → 추정 → 비중 계산 — 여러 템플릿의 앞부분. */
const HEAD = {
  nodes: [
    n("universe", "universe", c(0), 140, { tickers: TICKERS }),
    // lookback 은 비워 둔다(서버 기본 756일) — 마법사도 같은 기본값이라 "도구로 보내기" 가
    // 같은 수를 낸다. 756 은 정책 백테스트 하한(252)도 넘는다.
    n("returns", "returns", c(1), 140),
    n("estimate", "estimate", c(2), 20),
  ],
  edges: [
    e("universe", "universe", "returns", "universe"),
    e("returns", "returns", "estimate", "returns"),
    e("returns", "returns", "optimizer", "returns"),
    e("estimate", "belief", "optimizer", "belief"),
  ],
};

export const CORE_CHAIN_TEMPLATE: GraphDoc = doc("기본 사슬", [
  ...HEAD.nodes,
  n("views", "views", c(2), 270, { views: [] }),
  n("optimizer", "optimizer", c(3), 140, { model: "bl" }),
  n("risk", "risk", c(4), 0),
  n("backtest", "backtest", c(4), 260),
], [
  ...HEAD.edges,
  e("views", "views", "optimizer", "views"),
  e("optimizer", "weights", "risk", "weights"),
  e("returns", "returns", "backtest", "returns"),
  e("optimizer", "weights", "backtest", "weights"),
]);

const STRESS_TEMPLATE: GraphDoc = doc("충격 점검", [
  ...HEAD.nodes,
  n("optimizer", "optimizer", c(3), 140, { model: "risk_parity" }),
  n("scenario", "scenario_stress", c(4), 0),
  n("corr", "corr_stress", c(4), 170),
  n("sens", "sensitivity", c(4), 340),
], [
  ...HEAD.edges,
  e("optimizer", "weights", "scenario", "weights"),
  e("returns", "returns", "corr", "returns"),
  e("optimizer", "weights", "corr", "weights"),
  e("returns", "returns", "sens", "returns"),
  e("optimizer", "weights", "sens", "weights"),
]);

const SCREENER_TEMPLATE: GraphDoc = doc("조건으로 고른 종목 나누기", [
  n("screener", "screener", c(0), 140),
  n("returns", "returns", c(1), 20),
  n("scores", "factor_scores", c(1), 240),
  n("weights", "scores_to_weights", c(2), 140, { weighting: "inverse_vol" }),
  n("risk", "risk", c(3), 140),
], [
  e("screener", "universe", "returns", "universe"),
  e("screener", "universe", "scores", "universe"),
  e("scores", "scores", "weights", "scores"),
  e("returns", "returns", "weights", "returns"),
  e("weights", "weights", "risk", "weights"),
]);

const TIMING_TEMPLATE: GraphDoc = doc("타이밍 적용 → 실행 목표", [
  ...HEAD.nodes,
  n("optimizer", "optimizer", c(3), 140, { model: "hrp" }),
  n("signal", "timing_signal", c(3), 330),
  n("overlay", "exposure_overlay", c(4), 200),
  n("target", "target_version", c(5), 120),
  n("orders", "order_preview", c(5), 300),
  n("journal", "decision_journal", c(6), 200),
], [
  ...HEAD.edges,
  e("optimizer", "weights", "overlay", "weights"),
  e("signal", "signal", "overlay", "signal"),
  e("overlay", "weights", "target", "weights"),
  e("overlay", "weights", "orders", "weights"),
  e("target", "target", "journal", "target"),
  e("orders", "trades", "journal", "trades"),
]);

/**
 * 포트폴리오 위험 점검 (BL3 W4) — 정한 비중의 하루 손실(세 방법)·모의 경로의 손실 꼬리를 보고, 과거 표본으로 잰 β 로
 * 지수 선물 헤지 계약 수까지. ★β 는 칸을 비워 수익률·비중에서 잰다★ — 선물 가격은 예시값이라 노드가 '가정' 으로 적는다.
 */
const RISK_TEMPLATE: GraphDoc = doc("포트폴리오 위험 점검", [
  ...HEAD.nodes,
  n("optimizer", "optimizer", c(3), 140, { model: "risk_parity" }),
  n("var", "var_es", c(4), 0),
  n("mc", "mc_var", c(4), 170),
  n("hedge", "futures_hedge", c(5), 90, { current_beta: null }),
], [
  ...HEAD.edges,
  e("returns", "returns", "var", "returns"),
  e("optimizer", "weights", "var", "weights"),
  e("returns", "returns", "mc", "returns"),
  e("optimizer", "weights", "mc", "weights"),
  e("returns", "returns", "hedge", "returns"),
  e("optimizer", "weights", "hedge", "weights"),
]);

/**
 * 리밸런싱 판단 (BL3 W5) — 비중을 정하고, 지금 들고 있는 비중에서 옮길 가치가 있는지(효용 개선 대 비용)를 본 뒤 주문 목록까지.
 * ★지금 비중은 예시★ — 판단 노드 설정에서 바꾼다. 결정 기록은 저장 버튼으로만 남는다.
 */
const REBALANCE_TEMPLATE: GraphDoc = doc("리밸런싱 판단", [
  ...HEAD.nodes,
  n("optimizer", "optimizer", c(3), 140, { model: "risk_parity" }),
  n("decide", "rebalance_decision", c(4), 60, {
    holdings: [{ code: "005930", pct: 50 }, { code: "000660", pct: 30 }, { code: "035420", pct: 20 }],
  }),
  n("orders", "order_preview", c(4), 260),
], [
  ...HEAD.edges,
  e("optimizer", "weights", "decide", "weights"),
  e("optimizer", "weights", "orders", "weights"),
]);

/**
 * 매크로 화면에서 넘어온 국면 스냅샷으로 여는 흐름 (BL2b) — 타이밍 흐름에 '경기 국면 불러오기'(그 스냅샷)를 붙이고
 * 노출 조절이 타이밍과 국면을 함께 따르게 한다. ★스냅샷 id 는 서버가 확인한다★ — 없는 id 면 국면 노드가 사유와 함께 실패한다.
 */
export function macroSnapshotDoc(snapshotId: string): GraphDoc {
  return doc("매크로 스냅샷 반영", [
    ...TIMING_TEMPLATE.nodes.map((x) => (x.id === "overlay" ? { ...x, params: { ...x.params, follow: "timing_macro" } } : x)),
    n("regime", "regime", c(3), 470, { snapshot_id: snapshotId }),
  ], [
    ...TIMING_TEMPLATE.edges,
    e("regime", "regime", "overlay", "regime"),
  ]);
}

/** "설계에 넣기"(BU2) — 기본 흐름의 종목 고르기 노드에 넘겨받은 종목을 넣는다. 종목은 호출자가 stock_master 로 확인한 것만 넘긴다. */
export function tickersDoc(tickers: string[]): GraphDoc {
  return doc("종목 찾기에서 가져온 흐름",
    CORE_CHAIN_TEMPLATE.nodes.map((x) => (x.type === "universe" ? { ...x, params: { ...x.params, tickers: [...tickers] } } : x)),
    CORE_CHAIN_TEMPLATE.edges);
}

export interface GraphTemplate { key: string; name: string; description: string; doc: GraphDoc }

/** 팔레트의 "빠른 시작" 목록 — 순서가 곧 권하는 순서다. */
export const TEMPLATES: GraphTemplate[] = [
  { key: "core", name: "기본 흐름", doc: CORE_CHAIN_TEMPLATE,
    description: "종목 3개로 비중을 정하고 과거로 돌려 봐요." },
  { key: "stress", name: "충격 점검", doc: STRESS_TEMPLATE,
    description: "정한 비중을 위기 상황·상관 급등·기대 수익 오차에 넣어 봐요." },
  { key: "screener", name: "조건으로 고른 종목 나누기", doc: SCREENER_TEMPLATE,
    description: "조건으로 거른 종목에 팩터 점수를 매겨 흔들림 기준으로 나눠요." },
  { key: "timing", name: "타이밍 적용 → 실행 목표", doc: TIMING_TEMPLATE,
    description: "타이밍 신호로 노출을 줄이고 실행 목표·주문 목록·결정 기록까지 이어요." },
  { key: "risk", name: "포트폴리오 위험 점검", doc: RISK_TEMPLATE,
    description: "정한 비중이 하루에 얼마나 잃을 수 있는지 보고, 지수 선물로 시장 위험을 줄일 계약 수까지 계산해요." },
  { key: "rebalance", name: "리밸런싱 판단", doc: REBALANCE_TEMPLATE,
    description: "지금 들고 있는 비중에서 목표로 옮길 가치가 있는지 효용과 비용을 견줘 보고 주문 목록까지 봐요." },
];
