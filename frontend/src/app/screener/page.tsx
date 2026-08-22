"use client";

import { useState } from "react";
import TerminalScreener from "@/widgets/screener/TerminalScreener";

export default function ScreenerPage() {
  const [universe, setUniverse] = useState("kospi200");

  return (
    <div className="tpage-fade">
      {/* 슬림 툴바 — 헤더 제거 후 기능 컨트롤(유니버스)만 유지 */}
      <div className="t-toolbar">
        <label className="t-toolbar-label">Universe</label>
        <select
          value={universe}
          onChange={(e) => setUniverse(e.target.value)}
          style={{
            fontFamily: "var(--t-mono)", fontSize: 11, padding: "5px 9px",
            border: "1px solid var(--t-border)", borderRadius: 2, background: "#fff",
            color: "var(--t-ink)", cursor: "pointer", minWidth: 130,
          }}
        >
          <option value="kospi200">KOSPI 200</option>
          <option value="kosdaq150">KOSDAQ 150</option>
          <option value="kospi">KOSPI 전체</option>
          <option value="kosdaq">KOSDAQ 전체</option>
          <option value="etf">ETF 전체</option>
          <option value="all_listed">전체 (전종목)</option>
        </select>
      </div>

      <TerminalScreener universe={universe} />
    </div>
  );
}
