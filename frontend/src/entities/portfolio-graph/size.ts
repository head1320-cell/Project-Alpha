/**
 * 카드 크기·배치 간격 (BS2) — ★한 자리★. 카드 CSS 폭·자동 정리·전략 지도·묶음 상자 경계가 모두 여기를 읽는다.
 * ==========================================================================
 * 실측(확대 1 · 두 전략 + 합치기 · 결과 붙은 뒤, `measure_cards.mjs`):
 *  - 보통 카드 내용 높이 68~124px · 합치기 220px. 카드는 이미 내용에 맞는 높이다 — 빈 곳은 **줄 간격**(170)에 있었다.
 *  - 선 요약 라벨 폭 44~94px 인데 열 사이 틈은 66px(230 − 164) → 17개 중 13개가 카드를 덮었다.
 * 그래서: 카드 폭 164 → 150(틈 80 · 라벨은 64px 로 줄바꿈), 줄은 고정 170 대신 **카드 높이 + 28**로 쌓는다.
 * 예전 `NODE_W = 176`(실제 164)·합치기 236 > 열 230 어긋남도 여기서 한 번에 없앤다.
 */
import type { NodeCatalogEntry } from "./types";

/** 보통 카드 폭(px) — CSS 는 캔버스의 `--pg-node-w` 로 이 값을 받는다. */
export const NODE_W = 150;
/** 전략 합치기 카드 폭 — 전략 이름·도넛이 들어간다. 이 카드 뒤 열은 그만큼 오른쪽으로 민다. */
export const COMBINE_W = 236;
/** 열 사이 틈 — 선 요약 라벨(최대 64px)이 양옆 8px 를 두고 들어간다. */
export const COL_GAP = 80;
export const COL = NODE_W + COL_GAP;
/** 위아래 카드 사이 틈. */
export const ROW_GAP = 28;
/** 결과가 붙은 보통 카드의 가장 큰 내용 높이(실측 124). 포트가 많으면 그 높이가 이긴다. */
export const CARD_BODY_H = 124;
/** 합치기 카드 높이(실측 220 + 여유). */
export const COMBINE_H = 224;
/** 포트 줄 — `GraphNode` 의 최소 높이 식(`PORT_TOP + 포트 수 × PORT_GAP`)과 같다. */
export const PORT_TOP = 46;
export const PORT_GAP = 22;
/** 선 요약 라벨의 가운데 — 원천 카드 오른쪽 끝에서 틈의 가운데. */
export const BRIEF_DX = COL_GAP / 2;
export const BRIEF_MAX_W = COL_GAP - 16;

/** 배치가 쓰는 카드 높이 — 실제 카드보다 작지 않게(겹치지 않게) 잡는다. */
export function cardHeight(kind: string, catalog: NodeCatalogEntry[] | null | undefined): number {
  if (kind === "portfolio_combine") return COMBINE_H;
  const e = catalog?.find((c) => c.type === kind);
  const ports = e ? Math.max(e.inputs.length, e.outputs.length) : 0;
  return Math.max(CARD_BODY_H, PORT_TOP + ports * PORT_GAP);
}

export const cardWidth = (kind: string) => (kind === "portfolio_combine" ? COMBINE_W : NODE_W);
