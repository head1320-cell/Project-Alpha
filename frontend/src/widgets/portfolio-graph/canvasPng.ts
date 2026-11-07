"use client";
/**
 * 캔버스 그림 받기 (CF 3부 R7) — 단추 · '더 보기' · 명령 찾기가 함께 부르는 한 길.
 * 띠의 성격은 지금 문서에 있는 노드의 결과로만 정한다(지운 노드의 옛 결과는 세지 않는다): 연습용 = 선 모양과 같은 `lineage.practice` ·
 * 예전 결과 = 결과가 있는 노드 중 낡은 것 · 계산 전 = 결과가 하나도 없음. 받은 뒤·실패 모두 알림으로 말한다.
 */
import { captionLines, exportNote, pngFileName } from "@/entities/portfolio-graph";
import { exportPng } from "@/features/portfolio-graph-io";
import { usePortfolioGraph } from "./store";

let busy = false;

export async function exportCanvasPng(): Promise<void> {
  if (busy) return;                                                        // 찍는 동안 또 누르면 한 번만
  const st = usePortfolioGraph.getState();
  const canvasEl = document.querySelector<HTMLElement>(".pg-canvas");
  if (!canvasEl || !st.nodes.length) return;
  const present = new Set(st.nodes.map((n) => n.id));
  const results = Object.entries(st.report?.nodes ?? {}).filter(([id]) => present.has(id));
  const lines = captionLines({
    name: st.name, now: new Date(), computed: results.length > 0,
    practice: results.some(([, r]) => !!r.lineage?.practice),
    stale: results.some(([id]) => st.staleIds.includes(id)),
  });
  busy = true;
  try {
    const { fontsMissed } = await exportPng(canvasEl, lines, pngFileName(st.name || undefined));
    st.setNote(exportNote(lines) + (fontsMissed ? ` 글꼴 조각 ${fontsMissed}개를 받지 못해 그 글자는 비슷한 글꼴로 그렸어요.` : ""));
  } catch (e) {
    st.setNote(`그림을 만들지 못했어요 — ${(e as Error).message || "까닭을 모르는 오류"}`);
  } finally {
    busy = false;
  }
}
