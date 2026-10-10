/**
 * Saved Sleeves — localStorage (Full Expansion P3 잔여)
 * ==========================================================================
 * 슬리브 = 명명된 종목-비중 묶음. 현재 포트폴리오를 슬리브로 저장 → 여러 슬리브를
 * 결합(combine-sleeves)해 2단계 배분. strategyStorage/allocationStorage 관례 동일.
 */

export interface SavedSleeve {
  id: string;
  name: string;
  weights: Record<string, number>;   // code -> %
  names?: Record<string, string>;     // code -> label
  savedAt: string;
}

const KEY = "alpha_sleeves";
const MAX = 30;

function read(): SavedSleeve[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
}
function write(list: SavedSleeve[]) {
  try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX))); } catch { /* quota */ }
}

export function listSleeves(): SavedSleeve[] { return read(); }

export function saveSleeve(name: string, weights: Record<string, number>, names?: Record<string, string>): SavedSleeve {
  const list = read();
  const s: SavedSleeve = {
    id: `sl_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    name: name.trim() || `슬리브 ${list.length + 1}`,
    weights, names, savedAt: new Date().toISOString(),
  };
  write([s, ...list]);
  return s;
}

export function deleteSleeve(id: string) { write(read().filter((s) => s.id !== id)); }
