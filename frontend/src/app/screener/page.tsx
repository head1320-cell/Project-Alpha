"use client";

import { useState } from "react";
import TerminalScreener from "@/components/screener/TerminalScreener";
import StockDetail from "@/components/valuation/StockDetail";
import PageHeader from "@/components/layout/PageHeader";
import { type ScreenerItem } from "@/lib/screenerApi";

export default function ScreenerPage() {
  const [selected, setSelected] = useState<ScreenerItem | null>(null);
  const [universe, setUniverse] = useState("kospi200");

  return (
    <div>
      {/* 메타 스탬프 (우상단) */}
      <div className="meta-stamp">
        SCR_ID: ALPHA_EQUITY_MOD<br />
        AUTH: SIG_VERIFIED
      </div>

      {/* 헤더 */}
      <PageHeader
        eyebrow="EQUITY / MULTI-FACTOR SCREEN"
        index="01 / 05"
        title="Universal Stock Screener"
        intro="~2,700개 전 주권을 290+ 팩터로 필터링 — 자연어 검색·라이브 카운트로 조건을 좁혀 그대로 백테스터로 전송합니다."
        status="LIVE COUNT"
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

      {/* 스크리너 + 상세 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className={`${selected ? "lg:col-span-8" : "lg:col-span-12"} transition-all duration-300`}>
          <TerminalScreener
            universe={universe}
            onSelect={setSelected}
            selectedTicker={selected?.stock_code}
          />
        </div>
        {selected && (
          <div className="lg:col-span-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
            <StockDetail item={selected} onClose={() => setSelected(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
