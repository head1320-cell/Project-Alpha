// 스크리너 조건 프리셋 저장/불러오기 (localStorage 기반)
// 사용자가 자주 쓰는 필터 조합을 이름 붙여 저장하고 재사용.

import type { FilterGroupNode } from "@/shared/model/domain";

export interface ScreenerPreset {
  id: string;
  name: string;
  group: FilterGroupNode;
  universe: string;
  createdAt: number;
}

const KEY = "alpha:screener-presets";

function read(): ScreenerPreset[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ScreenerPreset[]) : [];
  } catch {
    return [];
  }
}

function write(presets: ScreenerPreset[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(presets));
  } catch {
    /* localStorage 불가 시 무시 */
  }
}

export function listPresets(): ScreenerPreset[] {
  return read().sort((a, b) => b.createdAt - a.createdAt);
}

export function savePreset(name: string, group: FilterGroupNode, universe: string): ScreenerPreset {
  const presets = read();
  const preset: ScreenerPreset = {
    id: `p_${Date.now().toString(36)}`,
    name: name.trim() || "이름 없는 전략",
    group: JSON.parse(JSON.stringify(group)),  // deep copy
    universe,
    createdAt: Date.now(),
  };
  presets.push(preset);
  write(presets);
  return preset;
}

export function deletePreset(id: string): void {
  write(read().filter((p) => p.id !== id));
}
