/**
 * researchApi — ResearchRun 저장·조회·비교 클라이언트 (Full Expansion P1)
 * /api/v1/research-runs — 연구 실행의 재현성 단위 (run_id·inputs·outputs·snapshot·code_version)
 */
import { API_BASE } from "@/shared/api/apiBase";

export interface ResearchRunSummary {
  run_id: string;
  created_at: number;          // epoch sec
  kind: string;
  name: string | null;
  code_version: string;
  parent_run_id: string | null;
  note: string | null;
  snapshot: {
    coverage?: { start?: string; end?: string; n_obs?: number; source?: string };
    excluded?: unknown[];
    [k: string]: unknown;
  };
}

export interface ResearchRunFull extends ResearchRunSummary {
  inputs: Record<string, unknown>;
  outputs: {
    weights?: { current?: Record<string, number>; optimized?: Record<string, number> };
    flow?: Record<string, Record<string, number>>;
    summary?: {
      portfolio?: Record<string, number>;
      benchmark?: Record<string, number> | null;
      active?: Record<string, number> | null;
    };
    labels?: Record<string, string>;
    [k: string]: unknown;
  };
}

export interface RecordRunInput {
  kind: string;
  name?: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  snapshot?: Record<string, unknown>;
  parent_run_id?: string;
  note?: string;
}

export const researchApi = {
  record: async (req: RecordRunInput): Promise<{ recorded: boolean; run_id: string | null; message?: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/research-runs`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`record run failed: ${r.status}`);
    return r.json();
  },
  list: async (kind?: string, limit = 50): Promise<{ runs: ResearchRunSummary[] }> => {
    const q = new URLSearchParams();
    if (kind) q.set("kind", kind);
    q.set("limit", String(limit));
    const r = await fetch(`${API_BASE}/api/v1/research-runs?${q}`);
    if (!r.ok) throw new Error(`list runs failed: ${r.status}`);
    return r.json();
  },
  get: async (runId: string): Promise<ResearchRunFull> => {
    const r = await fetch(`${API_BASE}/api/v1/research-runs/${encodeURIComponent(runId)}`);
    if (!r.ok) throw new Error(`get run failed: ${r.status}`);
    return r.json();
  },
  remove: async (runId: string): Promise<{ deleted: boolean }> => {
    const r = await fetch(`${API_BASE}/api/v1/research-runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`delete run failed: ${r.status}`);
    return r.json();
  },
};
