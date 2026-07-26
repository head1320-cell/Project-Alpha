// shared/api — Public API 배럴.
// 이 슬라이스를 쓰는 쪽은 내부 구현 파일을 열지 말고 이 파일만 보면 됩니다.
// legacyApi: 이름 충돌로 배럴 제외 — `@/shared/api/legacyApi` 로 직접 import
export * from "./apiBase";
export * from "./queryClient";
