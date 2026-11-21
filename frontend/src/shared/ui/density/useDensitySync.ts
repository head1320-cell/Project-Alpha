"use client";
/**
 * 셸이 부른다 — 경로가 바뀔 때마다 `html` 의 `data-tier` · `data-density` 를 맞춘다(ADR 007 §7).
 * 규칙은 `density.ts` 의 `resolveDensity` 하나다(첫 그림 전 조각과 같은 답). ★경로 표에 없는 화면으로 가면 속성을 뗀다★ —
 * 화면 안 이동(새로 고침 없음)에서 앞 화면의 속성이 남아 다음 화면을 바꾸지 않게 한다.
 * 저장값과 손가락 화면 여부는 경로가 바뀔 때마다 다시 읽는다(React 상태로 들고 있지 않는다 — 수화 전후의 값이 갈릴 자리가 없다).
 */
import { useEffect } from "react";
import { applyDensity, readDensityPref, resolveDensity } from "./density";

export function useDensitySync(path: string) {
  useEffect(() => {
    let coarse = false;
    try {
      coarse = !!window.matchMedia?.("(pointer: coarse)").matches;
    } catch {
      coarse = false;
    }
    applyDensity(document.documentElement, resolveDensity(path, readDensityPref(), coarse));
  }, [path]);
}
