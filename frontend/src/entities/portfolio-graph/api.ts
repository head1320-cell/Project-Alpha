/**
 * 포트폴리오 그래프 API — ★계산은 백엔드가 한다★ (ADR 002)
 * `/api/v1/allocation/graph/*`. 문은 불러온 파일이 틀려도 422 가 아니라 노드별 명명
 * 오류를 200 으로 돌려준다 — 여기서 HTTP 오류는 "서버에 닿지 못했다" 뿐이다.
 */
import { extractErrorDetail, getWithAuth, postJson } from "@/shared/api/apiBase";
import type { GraphDoc, NodeCatalog, RunReport, ValidateReport } from "./types";

const BASE = "/api/v1/allocation/graph";

async function readJson<T>(res: Response, what: string): Promise<T> {
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(`${what} 실패 (HTTP ${res.status}) — ${extractErrorDetail(body, "사유 없음")}`);
  }
  return body as T;
}

export const portfolioGraphApi = {
  nodeTypes: async (): Promise<NodeCatalog> =>
    readJson<NodeCatalog>(await getWithAuth(`${BASE}/node-types`), "노드 카탈로그 조회"),
  validate: async (doc: GraphDoc): Promise<ValidateReport> =>
    readJson<ValidateReport>(await postJson(`${BASE}/validate`, doc), "그래프 검증"),
  run: async (doc: GraphDoc): Promise<RunReport> =>
    readJson<RunReport>(await postJson(`${BASE}/run`, doc), "그래프 실행"),
};
