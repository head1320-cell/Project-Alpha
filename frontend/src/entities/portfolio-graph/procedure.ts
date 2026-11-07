/**
 * 설계 절차(BT) — 서버 `procedure` 를 화면이 읽는 도우미. ★판정은 서버가 한다★ 여기서는 모양만 다룬다.
 */
import type { Procedure, ProcedureStep } from "./types";

/** 서버 제안의 `attach` 에서 붙일 새 노드를 가리키는 자리. */
export const NEW_NODE = "@new";

/** 노드가 속한 단계(카탈로그 단계 키). 없으면 null. */
export function stepOfNode(proc: Procedure | null | undefined, nodeId: string | null): ProcedureStep | null {
  if (!proc || !nodeId) return null;
  return proc.steps.find((s) => s.node_ids.includes(nodeId)) ?? null;
}

/** 비어 있는 필수·권장 단계 — 절차 탭을 먼저 열지 정한다. */
export function hasOpenRequiredStep(proc: Procedure | null | undefined): boolean {
  return !!proc?.steps.some((s) => s.state !== "filled" && s.need !== "optional");
}
