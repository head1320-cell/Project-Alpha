import type { Metadata } from "next";
// BU0(ADR-003) — Pretendard 를 앱 전체로(npm, OFL — 외부 CDN 없음). 동적 서브셋이라 woff2 는 필요한 글자 범위만 받는다.
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
// 숫자·티커용 JetBrains Mono 도 같은 방식으로(npm, OFL — 2026-11-08 · 예전엔 globals.css 첫 줄의 Google Fonts @import). 글자 범위별 파일(라틴·그리스 등)을
// unicode-range 로 나눠 두어 쓰는 범위만 받는다 — next/font/local 은 unicode-range 를 못 실어 라틴만 남기면 σ·β·μ 가 대체 글꼴로 바뀐다.
import "@fontsource-variable/jetbrains-mono/wght.css";
import "./globals.css";
import { TerminalShell } from "@/widgets/layout/TerminalShell";
import Providers from "@/widgets/layout/Providers";
import { THEME_BOOT } from "@/shared/theme";

export const metadata: Metadata = {
  title: "Project Alpha | Quant Platform",
  description: "종목 찾기 · 백테스트 · 매크로 분석 · 기업 분석 · 위험 점검 · 포트폴리오 설계",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning — 아래 조각이 React 보다 먼저 `html` 에 `dark` 를 붙일 수 있다(저장한 테마 · 다크를 갖춘 화면).
    <html lang="ko" suppressHydrationWarning>
      <head>
        {/* 첫 그림 전에 테마를 맞춘다 — 밝게 그렸다 어두워지는 깜빡임을 막는다(규칙은 shared/theme/theme.ts 와 같다). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <Providers>
          <TerminalShell>{children}</TerminalShell>
        </Providers>
      </body>
    </html>
  );
}
