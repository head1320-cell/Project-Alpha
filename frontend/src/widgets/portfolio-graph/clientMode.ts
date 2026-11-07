/**
 * 캔버스의 고객 문서 모드 (CF 3부 PB3) — `/allocation?client=<cid>&doc=<did>` · `?client=<cid>&new=review`.
 * ==========================================================================
 * ★이 탭의 작업 중 문서와 섞지 않는다★ — 고객 문서는 위치를 그대로(다시 쌓지 않음) 열고, 연 뒤 되돌리기 기록을 비운다(이전 캔버스로
 * 되돌아가 그것을 고객 문서에 저장하는 일이 없게). 고객 문서를 여는 동안 작업 중 문서는 남기지 않고(`persistWip`), 고객 모드를 떠나면
 * 캔버스를 비워 일반 캔버스가 작업 중 문서를 다시 싣게 한다(`forgetClientDoc`). 저장은 서버(`/pb/clients/…/docs`)뿐이다.
 * 열지 못하면(로그인 안 함 · 남의/없는 고객) 서버 사유를 그대로 말하고 일반 캔버스로 연다.
 */
import { GRAPH_FORMAT, GRAPH_VERSION, TEMPLATES, type GraphDoc } from "@/entities/portfolio-graph";
import { getClient, getDoc, type PbClient } from "@/entities/pb-client";
import type { BootDoc } from "./useCanvasBoot";
import { usePortfolioGraph } from "./store";

export type ClientDocCtx = { clientId: string; docId: string | null; alias: string; name: string; archived: boolean };
export type ClientOpen = { ok: true; ctx: ClientDocCtx; boot: BootDoc } | { ok: false; note: string };

const localDate = (d = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** 정기 점검 템플릿 + 이 고객의 사실(별칭·성향·출처·평가일·기간)을 고객 노드 설정으로 — ★모르는 칸은 비워 둔다★(기본값으로 채우지 않는다). */
export function reviewDocFor(c: PbClient): GraphDoc {
  const base = TEMPLATES.find((t) => t.key === "review")!.doc;
  const facts: Record<string, unknown> = { alias: c.alias };
  if (c.risk_tolerance) facts.risk_tolerance = c.risk_tolerance;
  if (c.profile_source !== "unknown") facts.profile_source = c.profile_source;
  if (c.assessed_at) facts.assessed_at = c.assessed_at;
  if (c.horizon_years !== null) facts.horizon_years = c.horizon_years;
  return { ...base, nodes: base.nodes.map((n) => (n.type === "client_profile" ? { ...n, params: { ...n.params, ...facts } } : n)) };
}

export async function openClientDoc(clientId: string, docId: string | null, fresh: string | null): Promise<ClientOpen> {
  if (docId) {
    const r = await getDoc(clientId, docId);
    if (!r.ok) return { ok: false, note: `고객 문서를 열지 못했어요 — ${r.error}` };
    const d = r.value;
    return {
      ok: true,
      ctx: { clientId, docId: d.doc_id, alias: d.client_alias, name: d.name, archived: d.client_archived },
      boot: { doc: d.graph, restack: false, isolate: true,
              note: `‘${d.client_alias}’ 의 ‘${d.name}’ 이에요.${d.client_archived ? " 보관한 고객이라 읽기만 해요." : ""}` },
    };
  }
  if (fresh === "review") {
    const r = await getClient(clientId);
    if (!r.ok) return { ok: false, note: `고객 문서를 열지 못했어요 — ${r.error}` };
    const c = r.value;
    return {
      ok: true,
      ctx: { clientId, docId: null, alias: c.alias, name: `정기 점검 ${localDate()}`, archived: c.archived },
      boot: { doc: reviewDocFor(c), isolate: true,
              note: `‘${c.alias}’ 의 새 정기 점검이에요 — 위 ‘저장’ 으로 고객 문서에 남겨요.` },
    };
  }
  return { ok: false, note: "고객 문서를 열지 못했어요 — 주소에 열 문서가 없어요." };
}

/** 고객 모드를 떠날 때 — 캔버스를 비우고 되돌리기 기록도 비운다(일반 캔버스가 이 탭의 작업 중 문서를 다시 싣는다). */
export function forgetClientDoc() {
  usePortfolioGraph.getState().loadDoc({ format: GRAPH_FORMAT, version: GRAPH_VERSION, nodes: [], edges: [] });
  usePortfolioGraph.setState({ past: [], future: [] });
}
