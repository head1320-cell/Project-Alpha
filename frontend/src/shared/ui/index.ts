// shared/ui — Public API 배럴.
// 이 슬라이스를 쓰는 쪽은 내부 구현 파일을 열지 말고 이 파일만 보면 됩니다.
// 다만 shared/ui 는 성격이 다른 것들(레이아웃 원자 · 스켈레톤/커맨드팔레트 · 미니 차트)을
// 함께 담고 있어, primitives 만 필요한 화면이 배럴로 import 하면 나머지까지 번들에 끌려온다
// (실측: /derivatives 가 5.99 → 8.38 kB). **발견은 이 배럴로, import 는 필요한 모듈에서** 하세요.
//   예) import { PageHeader } from "@/shared/ui/primitives";
// kit: 이름 충돌로 배럴 제외 — `@/shared/ui/kit` 로 직접 import
// CatalogueShell: 배럴 제외 — 셸 하나로 무게가 있고(shadcn ToggleGroup 포함) 이걸 안 쓰는
// 화면까지 끌려온다. `@/shared/ui/CatalogueShell` 로 직접 import 하세요.
export * from "./MiniViz";
export * from "./feedback";
export * from "./primitives";
