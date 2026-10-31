// ═══════════════════════════════════════════════════════════════════════════════
// 카탈로그 창 프리셋 저장소 (스펙 §8.1 요구 11, Phase 6d)
//
// 세 창(타이밍 팩터 · 스트레스 시나리오 · 알파 팩터)이 **하나의 저장소를 네임스페이스로**
// 나눠 쓴다. 창마다 따로 만들면 같은 코드가 세 벌이 되고, 그중 하나만 고쳐지는 날이 온다.
//
// ★프리셋은 재현 좌표가 아니다★
// localStorage 에 있으므로 이 브라우저에만 존재하고, 서버의 어떤 런도 프리셋을 가리키지
// 않는다. 룰셋 버전(7c)과는 다른 물건이다 — 화면도 그렇게 말해야 한다. 프리셋은 "자주 쓰는
// 설정을 다시 꺼내는" 편의이지 "이 판단이 무엇이었는지" 의 기록이 아니다.
//
// 저장 형식은 `Record<string, unknown>` 로 둔다. 셸은 도메인 타입을 모르는 것이 설계 원칙이고
// (CatalogueItem 이 최소 표면만 받는 것과 같은 이유), 프리셋도 같은 규칙을 따른다.
// ═══════════════════════════════════════════════════════════════════════════════

/** 네임스페이스 — 창마다 하나. 값이 겹치면 서로의 프리셋이 보인다. */
export type PresetNamespace = "timing-factor" | "stress-scenario" | "alpha-factor";

export interface CataloguePreset {
  id: string;
  name: string;
  /** 어느 카탈로그 항목에 대한 설정인가 — 다른 항목을 고른 상태에서 적용하지 않기 위해. */
  itemId: string;
  /** 창이 정의하는 설정 스냅샷. 셸은 내용을 해석하지 않는다. */
  payload: Record<string, unknown>;
  createdAt: number;
}

const KEY = "alpha:catalogue-presets";
/** 창 하나당 상한 — 무한정 쌓이면 목록이 쓸모없어진다. */
const MAX_PER_NS = 20;

type Store = Partial<Record<PresetNamespace, CataloguePreset[]>>;

function read(): Store {
  try {
    if (typeof window === "undefined") return {};
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    // 손상된 값은 조용히 버린다 — 프리셋 하나 때문에 창 전체가 죽으면 안 된다.
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Store) : {};
  } catch {
    return {};
  }
}

function write(store: Store): void {
  try {
    if (typeof window === "undefined") return;
    localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    /* 용량 초과·프라이빗 모드 등 — 프리셋은 부가 기능이므로 실패해도 창은 계속 쓴다 */
  }
}

/** 최신순. */
export function listPresets(ns: PresetNamespace): CataloguePreset[] {
  const rows = read()[ns];
  return Array.isArray(rows) ? [...rows].sort((a, b) => b.createdAt - a.createdAt) : [];
}

export function savePreset(
  ns: PresetNamespace, name: string, itemId: string, payload: Record<string, unknown>,
): CataloguePreset {
  const store = read();
  const preset: CataloguePreset = {
    id: `cp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
    name: name.trim() || "이름 없는 프리셋",
    itemId,
    // 깊은 복사 — 호출자가 나중에 draft 를 바꿔도 저장된 프리셋이 따라 바뀌면 안 된다.
    payload: JSON.parse(JSON.stringify(payload ?? {})),
    createdAt: Date.now(),
  };
  const rows = [preset, ...(Array.isArray(store[ns]) ? store[ns]! : [])].slice(0, MAX_PER_NS);
  write({ ...store, [ns]: rows });
  return preset;
}

export function deletePreset(ns: PresetNamespace, id: string): void {
  const store = read();
  const rows = Array.isArray(store[ns]) ? store[ns]! : [];
  write({ ...store, [ns]: rows.filter((p) => p.id !== id) });
}
