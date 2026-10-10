// V2 — 수식·피어·NL2AST·지표/이벤트·PIT.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type {
  EventCatalog,
  FormulaValidation,
  IndicatorCatalog,
  NL2ASTResult,
  PITDates,
  PITRunRequest,
  PeerGroups,
  ScreenerResponse,
} from "../model";

export const screenerV2Api = {
  validateFormula: async (formula: string): Promise<FormulaValidation> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/validate-formula`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ formula }),
    });
    if (!r.ok) throw new Error(`Formula validation failed: ${r.status}`);
    return r.json();
  },
  peerGroups: async (universe = "kospi50"): Promise<PeerGroups> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/peer-groups?universe=${universe}`);
    if (!r.ok) throw new Error(`Peer groups failed: ${r.status}`);
    return r.json();
  },
};

// V2 조건 라벨 (수식/Peer 포함)

export const copilotApi = {
  nl2ast: async (query: string): Promise<NL2ASTResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!r.ok) throw new Error(`NL2AST failed: ${r.status}`);
    return r.json();
  },
  examples: async (): Promise<{ examples: string[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast/examples`);
    if (!r.ok) throw new Error(`Examples failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V2 M3: Technical/Event ──────────────────────────────────────────

export const screenerV2DataApi = {
  indicators: async (): Promise<IndicatorCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/indicators`);
    if (!r.ok) throw new Error(`Indicators failed: ${r.status}`);
    return r.json();
  },
  eventsCatalog: async (): Promise<EventCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/events-catalog`);
    if (!r.ok) throw new Error(`Events catalog failed: ${r.status}`);
    return r.json();
  },
};


// ─── Screener V2 M4: Point-in-Time ────────────────────────────────────────────

export const screenerPITApi = {
  dates: async (): Promise<PITDates> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/pit-dates`);
    if (!r.ok) throw new Error(`PIT dates failed: ${r.status}`);
    return r.json();
  },
  runPit: async (req: PITRunRequest): Promise<ScreenerResponse & { as_of_date: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-pit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || `PIT run failed: ${r.status}`);
    }
    return r.json();
  },
};
