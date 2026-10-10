/**
 * ResearchCase 클라이언트 — 연구 질문 하나를 감싸는 서버 작업 단위 (M1-U)
 * ==========================================================================
 * 서버(M1-S)의 `/api/v1/research-cases`. Study(`as_*`, 브라우저 로컬 초안)와
 * **합치지 않는다** — 합치면 "브라우저에만 있는 것"과 "서버에 있는 것"의 경계가
 * 사라지고, 그 경계는 P4 가 라벨로 지켜 온 계약이다.
 *
 * ★R0-S 의 분기를 그대로 지킨다★
 *   빈 목록      → `{available: true, cases: []}`
 *   저장소 장애  → `{available: false, reason}`
 *   없는 케이스  → 404 (fetch 가 던진다)
 *   못 읽음      → 503 (fetch 가 던진다 — 404 와 다른 사실이다)
 *   네트워크     → 여기서 **던진다**. 호출부가 catch 로 뭉개면 넷이 하나가 된다.
 */

import { API_BASE } from "@/shared/api/apiBase";

export interface ResearchCase {
  case_id: string;
  created_at: number;
  updated_at: number;
  name: string;
  /** ★질문이 Case 를 Study 와 구분한다★ 서버가 필수로 강제한다. */
  question: string;
  status: "open" | "archived";
  market: string;
  universe_ref: string | null;
  active_mes_id: string | null;
  active_tpv_id: string | null;
  active_run_id: string | null;
  code_version: string | null;
  note: string | null;
}

/** 목록 — `available:false` 는 "케이스가 없다"가 아니라 "읽지 못했다"이다. */
export interface CaseList {
  available: boolean;
  cases: ResearchCase[];
  reason?: string;
}

/** 사슬 조각의 공통 모양 — 조각마다 가용성이 따로다(M1-S 가 그렇게 답한다). */
export type ChainFragment<T> =
  | { available: false; reason: string; items?: never }
  | { available: true; items: T[] };

export interface ChainTarget {
  tpv_id: string;
  created_at: number;
  status: "executable" | "research_only" | string;
  status_reason: string | null;
  cash_weight: number | null;
  mes_id: string | null;
  run_id: string | null;
}

export interface ChainRun {
  run_id: string;
  created_at: number;
  kind: string;
  name: string | null;
}

export interface CaseChain {
  case: ResearchCase;
  mes: { available: false; reason: string } | ({ available: true } & Record<string, unknown>);
  runs: ChainFragment<ChainRun>;
  targets: ChainFragment<ChainTarget>;
}

export interface CreateCaseInput {
  name: string;
  question: string;
  market?: string;
  universe_ref?: string;
  note?: string;
}

const BASE = `${API_BASE}/api/v1/research-cases`;

export const caseApi = {
  /** 생성. 저장 실패는 `created:false` + 메시지로 답한다 — 성공으로 위장하지 않는다. */
  create: async (req: CreateCaseInput): Promise<{ created: boolean; case_id: string | null; message?: string }> => {
    const r = await fetch(BASE, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`create case failed: ${r.status}`);
    return r.json();
  },

  list: async (status: "open" | "archived" = "open", limit = 50): Promise<CaseList> => {
    const q = new URLSearchParams({ status, limit: String(limit) });
    const r = await fetch(`${BASE}?${q}`);
    if (!r.ok) throw new Error(`list cases failed: ${r.status}`);
    return r.json();
  },

  get: async (caseId: string): Promise<ResearchCase> => {
    const r = await fetch(`${BASE}/${encodeURIComponent(caseId)}`);
    if (!r.ok) throw new Error(`get case failed: ${r.status}`);
    return r.json();
  },

  /** 활성 포인터·이름·상태 갱신. `question` 과 `market` 은 **불변**이다 —
   *  질문이 바뀌면 그것은 다른 연구다(M1-S 의 `_MUTABLE` 이 서버에서 강제한다). */
  patch: async (caseId: string, fields: Partial<Pick<ResearchCase,
    "name" | "status" | "active_mes_id" | "active_tpv_id" | "active_run_id" | "note">>,
  ): Promise<{ updated: boolean; case_id: string }> => {
    const r = await fetch(`${BASE}/${encodeURIComponent(caseId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields),
    });
    if (!r.ok) throw new Error(`patch case failed: ${r.status}`);
    return r.json();
  },

  chain: async (caseId: string, limit = 30): Promise<CaseChain> => {
    const r = await fetch(`${BASE}/${encodeURIComponent(caseId)}/chain?limit=${limit}`);
    if (!r.ok) throw new Error(`case chain failed: ${r.status}`);
    return r.json();
  },
};
