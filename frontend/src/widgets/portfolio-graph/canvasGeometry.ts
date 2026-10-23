/**
 * 캔버스 좌표·맞춰 보기 (CF 3부 E2a — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변)
 * ==========================================================================
 * 확대 3단계 · 맞춰 보기 여백(떠 있는 판·아래 바) · 고른 노드 막대 자리 · 끌기 격자 · 확대 한계 · 키보드 이웃 노드.
 */
import type { ReactFlowInstance } from "@xyflow/react";
import { topoOrder } from "@/entities/portfolio-graph";
import { floatInsets } from "./panels";
import { measuredH, measuredW } from "./toolbarPlace";

/** 확대 3단계(BM C1 · 의미 확대) — 멀리: 이름과 숫자 하나 · 보통: 카드 · 가까이: 작은 그림·계산 시간까지. */
export const ZOOM_FAR = 0.55;
export const ZOOM_NEAR = 1.05;
export type ZoomLevel = "far" | "mid" | "near";
export const zoomLevel = (z: number): ZoomLevel => (z < ZOOM_FAR ? "far" : z > ZOOM_NEAR ? "near" : "mid");
/** 묶음 상자 여백·노드 카드 크기(대략) — 상자는 안의 노드를 감싸는 사각형이다. */
export const GROUP_PAD = 28;
/** 맞춰 보기의 안쪽 여백(px) — 위 64 = 선 범례·걸러 보기 판(10 + 36 + 여유), 아래 64 = 안내 줄. */
const FIT_INSET = { top: 64, bottom: 64, left: 24, right: 24 } as const;
/** 판 사이 가운데가 이보다 좁으면 선 범례·걸러 보기가 알약 아래 둘째 줄로 내려간다(BQ Q2) — 맞춰 보기 위 여백도 그만큼. */
export const TIGHT_MIDDLE = 760;
const TIGHT_ROW = 44;
/** 위 여백 — 둘째 줄이 있으면 그만큼 더. */
export const fitTop = (el: HTMLElement | null) => FIT_INSET.top + (el?.closest("[data-tight]") ? TIGHT_ROW : 0);
/** 아래 여백 — 64(안내 줄) · 아래 시트 · ★보이는 아래 바의 실제 위 끝 + 8★ 중 큰 것. 다음 한 걸음·길잡이 바는 단추가 있어 64 보다 높고
 *  좁으면 두 줄이 된다 — 길잡이 바가 맞춘 노드의 아래 끝을 덮었다(AI5b 전체 게이트가 찾음). */
const fitBottom = (el: HTMLElement, sheet: number) => {
  const bar = el.querySelector<HTMLElement>(".pg-hint");
  const clear = bar && bar.offsetParent !== null ? el.getBoundingClientRect().bottom - bar.getBoundingClientRect().top + 8 : 0;
  return Math.max(FIT_INSET.bottom + sheet, clear);
};
/** 노드 도구줄 높이 + 간격(px) — 고른 노드 위에 이만큼 비어 있어야 도구줄이 떠 있는 판 밑에 깔리지 않는다. */
export const TOOLBAR_H = 48;

/** 맞춰 보기 — 떠 있는 판(위: 선 범례·걸러 보기 · 아래: 안내 줄)이 노드·상자 머리를 가리지 않게 위아래를 비워 둔다.
 *  (BN N1 에서 찾은 결함: 균일 여백 맞춤은 맨 위 전략 상자의 머리 줄을 선 범례 밑에 두어 누를 수 없었다.) */
/** 고른 노드 막대의 자리(BS2) — 아래가 기본(상자 머리를 가리지 않게), 아래 공간이 모자라면 위로.
 *  캔버스 아래에는 안내 줄(약 60px)이 떠 있다 — 예전에는 아래 끝의 노드를 고르면 막대가 그 밑에 깔려 누를 수 없었다(E2E 가 찾음). */
export const SELBAR_ROOM = 14 + 44 + 64;
/** 막대 폭(대략) — 가운데 맞춤이 떠 있는 판 밑으로 들어가는지 볼 때 쓴다. CF4a '정렬' 단추로 실측 255 → 321 이라 360, CF5c '갈래' 단추로 실측 386 이라 430(여유 약 40). */
export const SELBAR_W = 430;
/** 끌기 격자(BN N3) — 22 점 칸의 반. */
export const SNAP = 11;

export function fitClear(inst: ReactFlowInstance | null, el: HTMLDivElement | null,
                  opts: { ids?: string[]; minZoom?: number; maxZoom?: number; duration?: number } = {}): boolean {
  if (!inst || !el) return false;
  // 일부만 맞출 때(갈래·들어가기 — BO O5)도 같은 여백 — 예전 fitView 는 맨 위 노드의 도구줄을 캔버스 위 끝 밖으로 밀었다.
  const want = opts.ids ? new Set(opts.ids) : null;
  const shown = inst.getNodes().filter((n) => !n.hidden && (!want || want.has(n.id)));
  // 크기는 내부 노드에서 읽는다 — 묶음 상자·갈래 띠는 그릴 때마다 새로 만드는 노드라 사용자 노드에는 실측이 없다(CF0, v12).
  const ns = shown.filter((n) => { const i = inst.getInternalNode(n.id); return !!i && measuredW(i) > 0 && measuredH(i) > 0; });
  // 아직 크기를 잰 노드가 모자라면(파일을 막 불러온 직후) 맞추지 않고 "못 맞춤" 을 알린다 — 부르는 쪽이 다음 프레임에 다시.
  if (!ns.length || ns.length < shown.length) return false;
  const b = inst.getNodesBounds(ns.map((n) => n.id));
  // 떠 있는 왼쪽 목록·오른쪽 창(BQ Q1)이 가리는 폭만큼 더 비운다 — 캔버스는 판 뒤까지 이어져 있다.
  const ins = floatInsets(el);
  const L = FIT_INSET.left + ins.left;
  const w = Math.max(1, el.clientWidth - L - FIT_INSET.right - ins.right);
  const top = fitTop(el);
  const h = Math.max(1, el.clientHeight - top - fitBottom(el, ins.bottom));
  const zoom = Math.min(opts.maxZoom ?? 1, Math.max(opts.minZoom ?? 0.2, Math.min(w / b.width, h / b.height)));
  // 가장 작게 줄여도 넘치면 가운데 두지 않고 흐름의 시작(왼쪽 위)에 붙인다 — 넘친 쪽은 오른쪽·아래로 간다.
  const dx = w - b.width * zoom;
  const dy = h - b.height * zoom;
  inst.setViewport({ x: L + (dx > 0 ? dx / 2 : 0) - b.x * zoom,
                     y: top + (dy > 0 ? dy / 2 : 0) - b.y * zoom, zoom },
                   opts.duration ? { duration: opts.duration } : undefined);
  return true;
}
/** React Flow 확대 한계 — `minZoom` 속성과 기본 최대(2). */
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 2;

/** 이웃 노드 — ←→ 는 선을 따라(같은 줄에 가까운 것 먼저), ↑↓ 는 흐름 번호 순서. 없으면 null. */
export function neighbour(id: string, key: string, nodes: { id: string; position: { x: number; y: number } }[],
                   edges: { source: string; target: string }[]): string | null {
  const me = nodes.find((n) => n.id === id);
  if (!me) return null;
  const near = (ids: string[]) => ids.map((x) => nodes.find((n) => n.id === x)).filter((n): n is typeof me => !!n)
    .sort((a, b) => Math.abs(a.position.y - me.position.y) - Math.abs(b.position.y - me.position.y))[0]?.id ?? null;
  if (key === "ArrowRight") return near(edges.filter((e) => e.source === id).map((e) => e.target));
  if (key === "ArrowLeft") return near(edges.filter((e) => e.target === id).map((e) => e.source));
  const order = topoOrder(nodes.map((n) => n.id), edges);
  const i = order.indexOf(id);
  if (key === "ArrowDown") return order[i + 1] ?? null;
  if (key === "ArrowUp") return i > 0 ? order[i - 1] : null;
  return null;
}
