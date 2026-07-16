// Allocation Studio 저장 스터디 — 포트폴리오+뷰+모델 설정+메모 (Decision Journal 1라운드)
// localStorage 기반, strategyStorage/watchlistStorage와 동일 idiom (KEY=alpha_*, max 30).

import type { AllocationModel, AllocationViewInput } from "@/lib/allocationApi";

export interface AllocationStudy {
  id: string;
  name: string;
  savedAt: string;
  holdings: Record<string, number>;      // {code: weight_pct}
  names?: Record<string, string>;        // {code: 종목명} — 로드 시 표시용
  views: AllocationViewInput[];
  model: AllocationModel;
  delta: number;
  tau: number;
  note?: string;                          // 의사결정 메모 (저널)
}

const KEY = "alpha_allocation_studies";

export function listStudies(): AllocationStudy[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function persist(list: AllocationStudy[]): void {
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30)));
}

export function saveStudy(
  name: string,
  data: Omit<AllocationStudy, "id" | "name" | "savedAt">,
): AllocationStudy {
  const list = listStudies();
  const item: AllocationStudy = {
    id: `as_${Date.now()}`,
    name: name.trim() || `스터디 ${list.length + 1}`,
    savedAt: new Date().toISOString(),
    ...data,
  };
  list.unshift(item);
  persist(list);
  return item;
}

export function deleteStudy(id: string): void {
  persist(listStudies().filter((s) => s.id !== id));
}
