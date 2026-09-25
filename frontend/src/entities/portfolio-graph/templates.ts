/**
 * 빈 캔버스용 시작 그래프 — 핵심 사슬(스펙 §4.3).
 * ★종목은 예시일 뿐이다★ — 유니버스 노드에서 바꾼다. mock 모드에서는 합성 수익률로 돌고,
 * 결과의 등급 배지가 그 사실을 말한다.
 */
import { GRAPH_FORMAT, GRAPH_VERSION, type GraphDoc } from "./types";

const n = (id: string, type: string, x: number, y: number, params: Record<string, unknown> = {}) =>
  ({ id, type, params, position: { x, y } });
const e = (source: string, source_port: string, target: string, target_port: string) =>
  ({ id: `${source}.${source_port}->${target}.${target_port}`, source, source_port, target, target_port });

export const CORE_CHAIN_TEMPLATE: GraphDoc = {
  format: GRAPH_FORMAT,
  version: GRAPH_VERSION,
  meta: { name: "기본 사슬" },
  nodes: [
    n("universe", "universe", 0, 140, { tickers: ["005930", "000660", "035420"] }),
    // lookback 은 비워 둔다(서버 기본 756일) — 마법사도 같은 기본값이라 "도구로 보내기" 가
    // 같은 수를 낸다. 756 은 정책 백테스트 하한(252)도 넘는다.
    n("returns", "returns", 196, 140),
    n("estimate", "estimate", 400, 20),
    n("views", "views", 400, 270, { views: [] }),
    n("optimizer", "optimizer", 600, 140, { model: "bl" }),
    n("risk", "risk", 800, 0),
    n("backtest", "backtest", 800, 260),
  ],
  edges: [
    e("universe", "universe", "returns", "universe"),
    e("returns", "returns", "estimate", "returns"),
    e("returns", "returns", "optimizer", "returns"),
    e("estimate", "belief", "optimizer", "belief"),
    e("views", "views", "optimizer", "views"),
    e("optimizer", "weights", "risk", "weights"),
    e("returns", "returns", "backtest", "returns"),
    e("optimizer", "weights", "backtest", "weights"),
  ],
};
