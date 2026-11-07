/**
 * researchApi — ResearchRun 저장·조회·비교 클라이언트 (Full Expansion P1)
 * /api/v1/research-runs — 연구 실행의 재현성 단위 (run_id·inputs·outputs·snapshot·code_version)
 */
import { API_BASE } from "@/shared/api/apiBase";
import { getActiveCaseId } from "@/shared/lib/caseStorage";

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
  /** Case 사슬 (M1-V). 넣지 않으면 `record` 가 활성 케이스를 붙인다. */
  case_id?: string;
  note?: string;
}

/**
 * 재현 응답 (P1-C) — `reproducible` 로 좁혀야만 판정을 읽을 수 있게 짠 유니온.
 * 이렇게 해야 "재현하지 못했는데 verdict 를 그린다" 가 타입 단계에서 불가능해진다.
 */
export interface ReproduceRefused {
  reproducible: false;
  run_id: string;
  kind: string;
  basis?: "none" | "recorded_as_of" | "server_stamped" | "coverage_end";
  as_of?: string;
  estimated?: boolean;
  reason: string;
}
export interface ReproduceDelta {
  code: string; recorded: number; fresh: number; delta_pp: number;
}
export interface ReproduceDone {
  reproducible: true;
  run_id: string;
  kind: string;
  /** 어느 좌표로 맞췄는가 — `coverage_end` 면 요청 시점의 as_of 가 아니라 관측 마지막 날이다. */
  basis: "recorded_as_of" | "server_stamped" | "coverage_end";
  as_of: string;
  estimated: boolean;
  coverage?: Record<string, unknown>;
  weights: { recorded: Record<string, number> | null; fresh: Record<string, number> };
  /** `incomparable` 은 "같다" 가 아니다 — 대조할 것이 없었다는 뜻이고 `reason` 이 붙는다. */
  verdict: "identical" | "drifted" | "incomparable";
  reason?: string;
  max_delta_pp?: number;
  deltas?: ReproduceDelta[];
  universe_changed?: { dropped: string[]; added: string[] };
  child_run_id?: string | null;
  child_recorded?: boolean;
}
export type ReproduceResult = ReproduceDone | ReproduceRefused;

/** 목록 응답 — `available:false` 면 저장소를 읽지 못한 것이고, 기록이 없는 것과 다르다. */
export interface ResearchRunList {
  available: boolean;
  runs: ResearchRunSummary[];
  reason?: string;
}

export const researchApi = {
  record: async (req: RecordRunInput): Promise<{ recorded: boolean; run_id: string | null; message?: string }> => {
    // 활성 케이스를 여기서 한 번만 붙인다 (targetVersionApi.create 와 같은 이유).
    const active = getActiveCaseId();
    const body = (req.case_id === undefined && active) ? { ...req, case_id: active } : req;
    const r = await fetch(`${API_BASE}/api/v1/research-runs`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`record run failed: ${r.status}`);
    return r.json();
  },
  /** 목록. ★서버가 `available` 로 "기록 없음"과 "저장소 장애"를 가른다 (R0-S)★
   *  네트워크 오류는 여기서 **던진다** — 호출부가 `catch` 로 뭉개면 세 상태가 다시
   *  하나가 된다(예전 `ResearchRunsPanel.tsx:98` 이 그랬다). */
  list: async (kind?: string, limit = 50): Promise<ResearchRunList> => {
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
  /** 기록된 런을 서버가 같은 코드로 다시 돌려 대조한다 (P1-C).
   *  ★네트워크 오류를 여기서 삼키지 않는다★ — 삼키면 "재현 실패"와 "응답 없음"이
   *  다시 한 값이 된다(R0-S 가 목록에서 고친 것과 같은 결함 계열). */
  reproduce: async (runId: string, record = false): Promise<ReproduceResult> => {
    const r = await fetch(
      `${API_BASE}/api/v1/research-runs/${encodeURIComponent(runId)}/reproduce`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record }) });
    if (!r.ok) throw new Error(`reproduce failed: ${r.status}`);
    return r.json();
  },
  remove: async (runId: string): Promise<{ deleted: boolean }> => {
    const r = await fetch(`${API_BASE}/api/v1/research-runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`delete run failed: ${r.status}`);
    return r.json();
  },
};
