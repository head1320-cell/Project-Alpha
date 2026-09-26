/**
 * 빈 캔버스용 시작 그래프 — 핵심 사슬(스펙 §4.3) + BK W6 템플릿 셋.
 * ★종목은 예시일 뿐이다★ — 유니버스 노드에서 바꾼다. mock 모드에서는 합성 수익률로 돌고,
 * 결과의 등급 배지가 그 사실을 말한다. ★템플릿은 파라미터 규칙을 새로 정하지 않는다★ — 비운 칸은
 * 서버 기본값이고, 옳은지는 서버 검증(`/graph/validate`)이 말한다(E2E 가 네 템플릿 모두 확인).
 */
import { GRAPH_FORMAT, GRAPH_VERSION, type GraphDoc } from "./types";

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
    n("universe", "universe", 0, 140, { tickers: TICKERS }),
    // lookback 은 비워 둔다(서버 기본 756일) — 마법사도 같은 기본값이라 "도구로 보내기" 가
    // 같은 수를 낸다. 756 은 정책 백테스트 하한(252)도 넘는다.
    n("returns", "returns", 196, 140),
    n("estimate", "estimate", 400, 20),
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
  n("views", "views", 400, 270, { views: [] }),
  n("optimizer", "optimizer", 600, 140, { model: "bl" }),
  n("risk", "risk", 800, 0),
  n("backtest", "backtest", 800, 260),
], [
  ...HEAD.edges,
  e("views", "views", "optimizer", "views"),
  e("optimizer", "weights", "risk", "weights"),
  e("returns", "returns", "backtest", "returns"),
  e("optimizer", "weights", "backtest", "weights"),
]);

const STRESS_TEMPLATE: GraphDoc = doc("충격 점검", [
  ...HEAD.nodes,
  n("optimizer", "optimizer", 600, 140, { model: "risk_parity" }),
  n("scenario", "scenario_stress", 820, 0),
  n("corr", "corr_stress", 820, 170),
  n("sens", "sensitivity", 820, 340),
], [
  ...HEAD.edges,
  e("optimizer", "weights", "scenario", "weights"),
  e("returns", "returns", "corr", "returns"),
  e("optimizer", "weights", "corr", "weights"),
  e("returns", "returns", "sens", "returns"),
  e("optimizer", "weights", "sens", "weights"),
]);

const SCREENER_TEMPLATE: GraphDoc = doc("조건으로 고른 종목 나누기", [
  n("screener", "screener", 0, 140),
  n("returns", "returns", 220, 20),
  n("scores", "factor_scores", 220, 240),
  n("weights", "scores_to_weights", 460, 140, { weighting: "inverse_vol" }),
  n("risk", "risk", 680, 140),
], [
  e("screener", "universe", "returns", "universe"),
  e("screener", "universe", "scores", "universe"),
  e("scores", "scores", "weights", "scores"),
  e("returns", "returns", "weights", "returns"),
  e("weights", "weights", "risk", "weights"),
]);

const TIMING_TEMPLATE: GraphDoc = doc("타이밍 적용 → 실행 목표", [
  ...HEAD.nodes,
  n("optimizer", "optimizer", 600, 140, { model: "hrp" }),
  n("signal", "timing_signal", 600, 330),
  n("overlay", "exposure_overlay", 820, 200),
  n("target", "target_version", 1040, 120),
  n("orders", "order_preview", 1040, 300),
  n("journal", "decision_journal", 1260, 200),
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
 * 매크로 화면에서 넘어온 국면 스냅샷으로 여는 흐름 (BL2b) — 타이밍 흐름에 '경기 국면 불러오기'(그 스냅샷)를 붙이고
 * 노출 조절이 타이밍과 국면을 함께 따르게 한다. ★스냅샷 id 는 서버가 확인한다★ — 없는 id 면 국면 노드가 사유와 함께 실패한다.
 */
export function macroSnapshotDoc(snapshotId: string): GraphDoc {
  return doc("매크로 스냅샷 반영", [
    ...TIMING_TEMPLATE.nodes.map((x) => (x.id === "overlay" ? { ...x, params: { ...x.params, follow: "timing_macro" } } : x)),
    n("regime", "regime", 600, 470, { snapshot_id: snapshotId }),
  ], [
    ...TIMING_TEMPLATE.edges,
    e("regime", "regime", "overlay", "regime"),
  ]);
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
];
