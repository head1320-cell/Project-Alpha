import type { Metadata } from "next";
import "./globals.css";
import { TerminalShell } from "@/widgets/layout/TerminalShell";
import Providers from "@/widgets/layout/Providers";
import { THEME_BOOT } from "@/shared/theme";

export const metadata: Metadata = {
  title: "Project Alpha | Quant Platform",
  description: "Institutional-grade quant tools — screening, backtesting, macro analysis, company analysis, and risk analysis",
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
