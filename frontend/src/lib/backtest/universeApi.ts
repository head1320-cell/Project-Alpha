// 대상 경로: frontend/src/lib/backtest/universeApi.ts
//
// 매매 대상(유니버스) 실시간 종목 수 API.
// 백엔드 신규 엔드포인트 POST /api/v1/screener/universe-count 를 호출한다.
// 응답: { matched, total } — matched=현재 유니버스 게이트 통과 종목 수, total=전체 매매가능 종목 수.

import { API_BASE } from "@/lib/apiBase";

export interface UniverseCountRequest {
  caps: string[];        // 시총군 id (예: "kospi_l" …) — UniversePanel.CAPS 와 동일
  sectors: string[];     // 업종 그룹 id (예: "s1" …) — UniversePanel.SECTOR_THEMES 와 동일
  etf: boolean;
  managed: boolean;      // 관리종목 포함 여부
  supervised: boolean;   // 감리종목 포함 여부
  groups: { mode: "none" | "include" | "exclude"; tickers: string[] }[];
}

export interface UniverseCountResponse {
  matched: number;
  total: number;
}

export async function universeCount(
  req: UniverseCountRequest,
  signal?: AbortSignal,
): Promise<UniverseCountResponse> {
  const r = await fetch(`${API_BASE}/api/v1/screener/universe-count`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  if (!r.ok) throw new Error(`universe-count failed: ${r.status}`);
  return r.json();
}

export interface SectorOption {
  id: string;     // 실제 업종명 (백엔드 STOCK_SECTOR 와 일치)
  label: string;
  size: number;
}

// 실제 업종(테마) 목록 — GET /api/v1/screener/sectors
export async function fetchSectors(signal?: AbortSignal): Promise<SectorOption[]> {
  const r = await fetch(`${API_BASE}/api/v1/screener/sectors`, { signal });
  if (!r.ok) throw new Error(`sectors failed: ${r.status}`);
  const d = await r.json();
  return (d.sectors ?? []).map((s: { id?: string; label?: string; size?: number }) => {
    const label = String(s.label ?? s.id ?? "");
    return { id: label, label, size: Number(s.size ?? 0) };
  });
}
