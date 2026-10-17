/**
 * 카드 크기·배치 간격 — ★한 자리★. 카드 CSS 폭·높이·자동 정리·전략 지도·묶음 상자 경계가 모두 여기를 읽는다.
 * ==========================================================================
 * BS2(실측): 카드 폭 150 · 줄은 고정 170 대신 **카드 높이 + 28**로 쌓는다.
 * CF1(사용자 결정 2026-10-16 "자리 고정"): 가까이(확대 ≥ 1.05)에서 카드가 작업 노드가 된다 — 머리 · 소켓 줄(이름 늘 보임) ·
 * 설정 위젯 · 결과 자리 · 상태 줄. ★모든 확대에서 같은 상자★라 배치가 겹치지 않는다: 폭 240, 높이는 카탈로그(포트 수 ·
 * 카드에 놓을 위젯 수)로 정한다. 확대에 따라 상자 안의 내용만 바뀐다. 카드 CSS 는 이 높이를 `min-height` 로 받는다 —
 * 막힘 사유·고치는 법이 결과 자리보다 길면 그때만 카드가 자란다(사유를 잘라 숨기지 않는다).
 */
import { cardWidgetSlots } from "./schema";
import type { GraphDoc, NodeCatalogEntry } from "./types";

/** 카드 폭(px) — CSS 는 캔버스의 `--pg-node-w` 로 이 값을 받는다. 합치기 카드도 같은 폭(뒤 열을 밀지 않는다). */
export const NODE_W = 240;
export const COMBINE_W = NODE_W;
/** 열 사이 틈 — 선 요약 라벨(최대 64px)이 양옆 8px 를 두고 들어간다. */
export const COL_GAP = 80;
export const COL = NODE_W + COL_GAP;
/** 위아래 카드 사이 틈. */
export const ROW_GAP = 28;

/** 카드 안 치수 — `GraphNode` 의 CSS(globals.css "CF1 작업 노드")와 같은 값이다. */
export const CARD_PAD_Y = 12;
export const HEAD_H = 24;
export const HEAD_GAP = 8;
/** 소켓 줄 — 첫 소켓의 가운데 높이와 줄 간격. 핸들이 이 높이에 선다. */
export const PORT_TOP = CARD_PAD_Y + HEAD_H + HEAD_GAP + 12;
export const PORT_GAP = 24;
/** 접은 카드는 머리 줄만 — 소켓이 머리 가운데 높이에 모인다. */
export const FOLD_PORT_TOP = CARD_PAD_Y + HEAD_H / 2;
export const SOCKETS_GAP = 8;
export const WIDGET_H = 48;
export const MORE_H = 24;
export const SUMMARY_H = 40;
export const HEADLINE_H = 30;
/** 결과 자리 — 작은 그림(가까이) · 막힘 사유 · 고치는 법 · 예전 결과 안내가 이 자리를 나눠 쓴다.
 *  156 = 가장 큰 작은 그림(막대 5줄 + "그림 밖 n개", 템플릿 여섯을 계산해 잰 자연 높이 153)이 들어가는 높이 — 가까이에서 그림이
 *  나타나도 상자가 자라지 않게(★모든 확대에서 같은 상자★). 종류마다 그림이 있는지는 카탈로그가 말하지 않아 한 값으로 잡는다. */
export const SLOT_H = 156;
/** 합치기 카드의 결과 자리 — 몫 도넛. */
export const COMBINE_SLOT_H = 168;
/** 상태 줄 — 근거 칩(최대 셋)과 계산 시간이 한 줄로 흐르고 두 줄까지 접힌다(8 + 20 + 4 + 20). 칩을 잘라 숨기지 않는다. */
export const FOOT_H = 52;
/** 합치기 카드의 입력 줄 — 필수 둘 + 이은 전략 + 빈 자리 하나를 미리 잡는다(더 이으면 카드가 자란다). */
export const COMBINE_ROWS = 4;

/** 열 사이 틈(80)을 둘로 나눈다(CF3b2) — 보내는 쪽 반은 선 요약 칸, 받는 쪽 끝은 전달 점검 표시 칸. 둘이 같은 틈에 놓여도 겹치지 않는다.
 *  요약: 보내는 손잡이에서 BRIEF_DX 가운데 · 폭 BRIEF_MAX_W 이하 / 표시: 받는 손잡이에서 FLAG_DX 앞 가운데 · 폭 FLAG_W. */
export const BRIEF_DX = 30;
export const BRIEF_MAX_W = 48;
export const FLAG_DX = 12;
export const FLAG_W = 16;

/** 배치·카드가 함께 쓰는 카드 높이 — 확대와 무관한 한 상자. */
export function cardHeight(kind: string, catalog: NodeCatalogEntry[] | null | undefined): number {
  const e = catalog?.find((c) => c.type === kind);
  const combine = kind === "portfolio_combine";
  const rows = combine ? COMBINE_ROWS : e ? Math.max(e.inputs.length, e.outputs.length) : 0;
  const { slots, more } = cardWidgetSlots(e?.params_schema ?? null);
  const top = slots ? slots * WIDGET_H : SUMMARY_H;
  const body = top + (more ? MORE_H : 0) + HEADLINE_H + (combine ? COMBINE_SLOT_H : SLOT_H) + FOOT_H;
  return CARD_PAD_Y + HEAD_H + HEAD_GAP + rows * PORT_GAP + (rows ? SOCKETS_GAP : 0) + body + CARD_PAD_Y;
}

export const cardWidth = (_kind: string) => NODE_W;

type Box = { id: string; position: { x: number; y: number }; data: { kind: string } };

/** 카드끼리 겹치는 것이 있나 — 예전 크기(폭 150)로 놓인 문서를 불러왔을 때 '자동 정리' 안내를 띄울지 정한다. */
export function cardsOverlap(nodes: Box[], catalog: NodeCatalogEntry[] | null | undefined): boolean {
  const r = nodes.map((n) => ({ x: n.position.x, y: n.position.y, w: cardWidth(n.data.kind), h: cardHeight(n.data.kind, catalog) }));
  for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {
    const a = r[i], b = r[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) return true;
  }
  return false;
}

/**
 * 코드가 만든 흐름(템플릿·목표로 시작·다른 화면이 넘긴 흐름)을 새 카드 높이로 다시 쌓는다 — ★열은 그대로★, 같은 열 안의
 * 위아래 순서도 그대로, 줄 사이는 카드 높이 + 틈, 열마다 가장 긴 열의 가운데에 맞춘다(손으로 쓴 y 값은 예전 카드 높이를 가정했다).
 */
export function restackColumns<T extends Box>(nodes: T[], catalog: NodeCatalogEntry[] | null | undefined): T[] {
  const cols = new Map<number, T[]>();
  for (const n of nodes) cols.set(n.position.x, [...(cols.get(n.position.x) ?? []), n]);
  const heightOf = (col: T[]) => col.reduce((s, n) => s + cardHeight(n.data.kind, catalog), 0) + ROW_GAP * (col.length - 1);
  const tallest = Math.max(0, ...[...cols.values()].map(heightOf));
  const y = new Map<string, number>();
  for (const col of cols.values()) {
    let top = (tallest - heightOf(col)) / 2;
    for (const n of [...col].sort((a, b) => a.position.y - b.position.y)) {
      y.set(n.id, Math.round(top));
      top += cardHeight(n.data.kind, catalog) + ROW_GAP;
    }
  }
  return nodes.map((n) => ({ ...n, position: { x: n.position.x, y: y.get(n.id) ?? n.position.y } }));
}

/** 문서판 — 코드가 만든 흐름(`GraphDoc`)을 불러오기 전에 다시 쌓는다. 사용자 파일·작업 중 문서에는 쓰지 않는다(배치를 말없이 바꾸지 않음). */
export function restackDoc(doc: GraphDoc, catalog: NodeCatalogEntry[] | null | undefined): GraphDoc {
  const boxes = doc.nodes.map((n) => ({ id: n.id, position: n.position, data: { kind: n.type } }));
  const y = new Map(restackColumns(boxes, catalog).map((b) => [b.id, b.position.y]));
  return { ...doc, nodes: doc.nodes.map((n) => ({ ...n, position: { x: n.position.x, y: y.get(n.id) ?? n.position.y } })) };
}
