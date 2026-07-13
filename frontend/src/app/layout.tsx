import type { Metadata } from "next";
import "./globals.css";
import { TerminalShell } from "@/components/layout/TerminalShell";
import Providers from "@/components/layout/Providers";

export const metadata: Metadata = {
  title: "Project Alpha | Quant Platform",
  description: "Institutional-grade quant tools — screening, backtesting, macro analysis, company analysis, and risk analysis",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <Providers>
          <TerminalShell>{children}</TerminalShell>
        </Providers>
      </body>
    </html>
  );
}
