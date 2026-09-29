"use client";
/**
 * 화면 테마 (BR R3) — 라이트 · 다크 · 시스템. 이 브라우저에만 남는다(`alpha_theme`).
 * ==========================================================================
 * ★다크는 다크를 구현한 화면에서만 켠다★ — globals.css §47(S1f): "절반만 대응된 앱을 내보내면 사용자는
 * '다크모드가 깨졌다'고 읽는다 — 없는 것보다 나쁘다." 다크 규칙이 있는 화면(`DARK_READY`)이 아니면 `html.dark` 를
 * 끄고, 프로필 카드가 그렇다고 밝힌다(라벨 붙은 열화). 화면이 다크를 갖추면 여기 한 줄을 더한다.
 * 적용은 기존 토큰 계층 그대로 — `html` 의 `.dark` 클래스.
 */
import { useEffect, useState } from "react";
import { create } from "zustand";

export type Theme = "light" | "dark" | "system";
export const THEME_KEY = "alpha_theme";
export const THEMES: [Theme, string][] = [["light", "라이트"], ["dark", "다크"], ["system", "시스템"]];

/** 다크 규칙이 있는 화면 — `.pg-theme`·`.aas-root`(포트폴리오 설계) · `.brun-results`(백테스트 결과). */
export const DARK_READY: { pattern: RegExp; label: string }[] = [
  { pattern: /^\/allocation(\/|$)/, label: "포트폴리오 설계" },
  { pattern: /^\/backtest\/runs\/[^/]+\/results\/?$/, label: "백테스트 결과" },
  // BS1 — 토큰(`--t-*`·shadcn 다리)만 쓰는 화면. settings.spec 이 다크 AA 로 확인한다.
  { pattern: /^\/settings\/?$/, label: "설정" },
  { pattern: /^\/login\/?$/, label: "로그인" },
];
export const darkReady = (path: string) => DARK_READY.some((r) => r.pattern.test(path));

export function readTheme(): Theme {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === "dark" || v === "system" ? v : "light";
  } catch {
    return "light";
  }
}

function saveTheme(t: Theme) {
  try { window.localStorage.setItem(THEME_KEY, t); } catch { /* 이번 방문에만 */ }
}

export const wantsDark = (theme: Theme, path: string, systemDark: boolean) =>
  darkReady(path) && (theme === "dark" || (theme === "system" && systemDark));

/** 첫 그림 전에 도는 조각 — React 가 붙기 전 깜빡임(밝게 그렸다 어두워짐)을 막는다. 규칙은 위와 같다. */
export const THEME_BOOT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});var p=location.pathname;`
  + `var r=[${DARK_READY.map((r) => r.pattern.toString()).join(",")}].some(function(x){return x.test(p)});`
  + `var s=!!(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);`
  + `if(r&&(t==="dark"||(t==="system"&&s)))document.documentElement.classList.add("dark")}catch(e){}})();`;

export const useTheme = create<{ theme: Theme; loaded: boolean; setTheme: (t: Theme) => void; load: () => void }>((set) => ({
  theme: "light",
  loaded: false,
  setTheme: (t) => { saveTheme(t); set({ theme: t }); },
  load: () => set({ theme: readTheme(), loaded: true }),
}));

/** 셸이 부른다 — 경로·저장값·시스템 설정이 바뀔 때마다 `html.dark` 를 맞춘다. */
export function useThemeSync(path: string) {
  const { theme, loaded, load } = useTheme();
  const [systemDark, setSystemDark] = useState(false);
  useEffect(() => {
    load();
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    setSystemDark(mq.matches);
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [load]);
  useEffect(() => {
    if (!loaded) return;
    document.documentElement.classList.toggle("dark", wantsDark(theme, path, systemDark));
  }, [theme, path, systemDark, loaded]);
}
