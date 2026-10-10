/**
 * 활성 ResearchCase 포인터 — localStorage (M1-U)
 * ==========================================================================
 * ★여기 저장되는 것은 **포인터 하나**뿐이다★ 케이스 자체(`rc_*` 의 질문·상태·
 * 포인터들)는 서버에 있다. 이 파일이 아는 것은 "이 브라우저에서 지금 어느 케이스를
 * 보고 있는가" 이고, 그것은 연구 기록이 아니라 화면 상태다.
 *
 * 그래서 CaseBar 는 이 사실을 라벨로 적는다 — Study(`as_*`)를 P4 가 "브라우저 로컬"
 * 로 라벨해 온 것과 같은 이유다. 케이스를 로컬이라고 말하지도, 포인터를 서버 상태인
 * 척하지도 않는다.
 *
 * 관례는 `sleeveStorage` · `strategyStorage` 와 동일(SSR 가드 · quota 무시).
 */

const KEY = "active_research_case";

export function getActiveCaseId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = localStorage.getItem(KEY);
    return v && v.startsWith("rc_") ? v : null;
  } catch {
    return null;
  }
}

export function setActiveCaseId(caseId: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (caseId) localStorage.setItem(KEY, caseId);
    else localStorage.removeItem(KEY);
  } catch {
    /* quota — 포인터를 못 남겨도 케이스 자체는 서버에 있다 */
  }
}
