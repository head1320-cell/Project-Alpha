/**
 * PB 고객 관리 라우트 — `/api/v1/pb/clients*` (서버 CF 3부 PB3 · 로그인 · 본인 고객만).
 * ==========================================================================
 * 고객 화면(`/clients`)과 캔버스의 고객 칩이 함께 쓴다. ★남의 고객은 서버가 404★ — 화면이 거르지 않는다.
 * 별칭·문서 이름의 개인정보 모양 검사도 서버가 한다(사유를 그대로 보인다). 실패는 `Result` 로 — 서버 사유 그대로.
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call } from "@/shared/api/result";
// 타입만 참조 — 런타임 결합 없음(고객 문서의 그래프 모양).
// eslint-disable-next-line import/no-restricted-paths
import type { GraphDoc } from "@/entities/portfolio-graph/types";

export type RiskTolerance = "conservative" | "moderate_conservative" | "moderate" | "moderate_aggressive" | "aggressive";
export type ProfileSource = "survey" | "user_declared" | "default" | "unknown";

export const RISK_PLAIN: Record<RiskTolerance, string> = {
  conservative: "안정형", moderate_conservative: "안정추구형", moderate: "위험중립형",
  moderate_aggressive: "적극투자형", aggressive: "공격투자형",
};
export const SOURCE_PLAIN: Record<ProfileSource, string> = {
  survey: "설문", user_declared: "고객이 말함", default: "기본값", unknown: "모름",
};

export type PbClient = {
  client_id: string; alias: string; risk_tolerance: RiskTolerance | null; profile_source: ProfileSource;
  assessed_at: string | null; assessed_age_days: number | null; horizon_years: number | null;
  archived: boolean; archived_at: string | null; created_at: string | null; updated_at: string | null;
  doc_count: number; last_doc_at: string | null;
};
export type PbDocMeta = { doc_id: string; client_id: string; name: string; created_at: string | null; updated_at: string | null };
export type PbClientDetail = PbClient & { docs: PbDocMeta[] };
export type PbDoc = PbDocMeta & { graph: GraphDoc; client_alias: string; client_archived: boolean };

export type ClientFacts = {
  alias: string; risk_tolerance?: RiskTolerance | null; profile_source?: ProfileSource;
  assessed_at?: string | null; horizon_years?: number | null;
};

const BASE = "/api/v1/pb/clients";
const at = (cid: string, rest = "") => `${BASE}/${encodeURIComponent(cid)}${rest}`;
const send = (method: "PUT" | "PATCH", path: string, body: unknown) =>
  getWithAuth(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const listClients = (archived = false) =>
  call<{ clients: PbClient[] }>(getWithAuth(`${BASE}${archived ? "?archived=true" : ""}`));
export const createClient = (facts: ClientFacts) => call<PbClient>(postJson(BASE, facts));
export const getClient = (cid: string) => call<PbClientDetail>(getWithAuth(at(cid)));
export const updateClient = (cid: string, changes: Partial<ClientFacts>) => call<PbClient>(send("PATCH", at(cid), changes));
export const archiveClient = (cid: string) => call<PbClient>(postJson(at(cid, "/archive"), {}));
export const unarchiveClient = (cid: string) => call<PbClient>(postJson(at(cid, "/unarchive"), {}));
export const createDoc = (cid: string, name: string, graph: GraphDoc) => call<PbDocMeta>(postJson(at(cid, "/docs"), { name, graph }));
export const getDoc = (cid: string, did: string) => call<PbDoc>(getWithAuth(at(cid, `/docs/${encodeURIComponent(did)}`)));
export const saveDoc = (cid: string, did: string, graph: GraphDoc) =>
  call<PbDocMeta>(send("PUT", at(cid, `/docs/${encodeURIComponent(did)}`), { graph }));
