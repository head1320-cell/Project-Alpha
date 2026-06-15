"use client";

import { useState } from "react";
import TerminalScreener from "@/components/screener/TerminalScreener";
import PageHeader from "@/components/layout/PageHeader";

export default function ScreenerPage() {
  const [universe, setUniverse] = useState("kospi200");

  return (
    <div>
      {/* 메타 스탬프 (우상단, 숨김) */}
      <div className="meta-stamp">
        SCR_ID: ALPHA_EQUITY_MOD<br />
        AUTH: SIG_VERIFIED
      </div>

      <PageHeader
        eyebrow="EQUITY / MULTI-FACTOR SCREEN"
        index="01 / 05"
        title="Quant Screener"
        intro="백테스터와 동일한 팩터 라이브러리로 전 종목을 스크리닝합니다 — 팩터를 추가하면 즉시 종목 리스트가 갱신됩니다."
        status="LIVE"
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontFamily: "var(--t-mono)", fontSize: 10, color: "var(--t-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Universe</label>
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            style={{
              fontFamily: "var(--t-mono)", fontSize: 12, padding: "8px 12px",
              border: "1px solid var(--t-border)", borderRadius: 2, background: "#fff",
              color: "var(--t-ink)", cursor: "pointer", minWidth: 140,
            }}
          >
            <option value="kospi50">KOSPI 50</option>
            <option value="kospi200">KOSPI 200</option>
            <option value="kosdaq150">KOSDAQ 150</option>
            <option value="mapped">DART 매핑</option>
          </select>
        </div>
      </PageHeader>

      <TerminalScreener universe={universe} />
    </div>
  );
}
