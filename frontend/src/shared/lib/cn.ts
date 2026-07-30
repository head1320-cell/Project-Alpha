// cn — Tailwind 클래스 병합 유틸 (shadcn/ui 가 전제하는 헬퍼).
//
// clsx: 조건부 클래스를 문자열로 합친다.
// twMerge: 뒤에 온 Tailwind 유틸리티가 앞의 **같은 속성**을 이기게 한다.
//   예) cn("px-2", "px-4") → "px-4"   (clsx 만 쓰면 "px-2 px-4" 로 남아 CSS 순서에 좌우된다)
//
// tailwind-merge 는 **v2 계열(2.6.1)** 로 고정했다. v3 는 Tailwind v4 를 대상으로 하고
// 이 프로젝트는 tailwindcss 3.4.1 에 고정되어 있다(ADR 001: Next·React·TS·Tailwind 승격 금지).
//
// 위치: shared/lib — 이미 format/storage 계열 헬퍼가 사는 곳이다. shadcn 관례상 lib/utils.ts
// 이지만 그 이름으로 새 폴더를 만들면 FSD 배치가 흐려진다. components.json 의 aliases.utils
// 가 이 경로를 가리킨다.
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
