// 프리셋 카탈로그.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type {
  PresetCatalog,
  PresetDetail,
  ScreenerResponse,
} from "../model";

export const presetApi = {
  list: async (): Promise<PresetCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/presets`);
    if (!r.ok) throw new Error(`Presets fetch failed: ${r.status}`);
    return r.json();
  },
  detail: async (id: string): Promise<PresetDetail> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/presets/${id}`);
    if (!r.ok) throw new Error(`Preset detail failed: ${r.status}`);
    return r.json();
  },
  run: async (id: string, universe = "kospi50", limit = 50): Promise<ScreenerResponse & { preset_name: string; master: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/presets/${id}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ universe, limit }),
    });
    if (!r.ok) throw new Error(`Preset run failed: ${r.status}`);
    return r.json();
  },
};
