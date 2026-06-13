"use client";
// 조건 요약 패널 (젠포트 "내가 설정한 조건 보기" 미러) — 매수/매도/매매대상 독립 탭으로
// 현재 설정 전체를 읽기 전용 카드로 표시. buildSummary(strategy, tab)가 단일 소스.
// 편집 패널과 같은 상태(s)를 읽으므로 설정 변경이 즉시 반영된다(라이브 미러).

import { useEffect, useState } from "react";
import { buildSummary, type BacktestStrategy, type SummaryTab } from "../../../lib/backtest/strategy";
import { TONES, type Tone } from "../kit";

const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";

const TABS: Array<{ id: SummaryTab; label: string; tone: Tone }> = [
  { id: "buy", label: "매수조건", tone: "buy" },
  { id: "sell", label: "매도조건", tone: "sell" },
  { id: "universe", label: "매매대상", tone: "neutral" },
];

export default function ConditionSummary({ s, activeTab, onTabChange }: {
  s: BacktestStrategy;
  /** 편집 중인 탭 — 요약이 이를 따라간다(동기화). 없으면 독립 동작 */
  activeTab?: SummaryTab;
  /** 요약 탭 클릭 시 편집 탭도 전환 (단일 소스 동기화) */
  onTabChange?: (t: SummaryTab) => void;
}) {
  const [tab, setTab] = useState<SummaryTab>(activeTab ?? "buy");
  // 편집 탭이 바뀌면 요약도 따라감 (#1). 요약 탭 클릭은 onTabChange로 편집 탭까지 전환.
  useEffect(() => {
    if (activeTab) setTab(activeTab);
  }, [activeTab]);
  const handleTab = (t: SummaryTab) => {
    setTab(t);
    onTabChange?.(t);
  };
  const active = TABS.find((t) => t.id === tab) ?? TABS[0];
  const groups = buildSummary(s, tab);

  return (
    <aside className="tbt-summary" style={{
      background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: RL, padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>내가 설정한 조건 보기</span>
      </div>

      {/* 매수/매도/매매대상 탭 */}
      <div style={{ display: "flex", gap: 0, border: "1px solid var(--border-strong)", borderRadius: R, overflow: "hidden", marginBottom: 14 }}>
        {TABS.map((t) => (
          <button key={t.id} type="button" onClick={() => handleTab(t.id)}
            style={{ flex: 1, fontSize: 12, fontWeight: tab === t.id ? 600 : 400, padding: "7px 0", border: "none", cursor: "pointer",
              background: tab === t.id ? TONES[t.tone].bg : "var(--bg-card)",
              color: tab === t.id ? TONES[t.tone].text : "var(--text-secondary)" }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* 요약 카드들 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {groups.map((g) => (
          <div key={g.label} style={{ border: "1px solid var(--border)", borderRadius: R, padding: "11px 12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 9 }}>
              <span style={{ width: 3, height: 12, borderRadius: 2, background: TONES[active.tone].accent }} />
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-primary)" }}>{g.label}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {g.rows.map((r, i) => (
                <div key={i} style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
                  <span style={{ fontSize: 11.5, color: "var(--text-secondary)", flexShrink: 0 }}>{r.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 500, textAlign: "right",
                    fontFamily: "var(--bs-font-mono)", wordBreak: "keep-all",
                    color: r.muted ? "var(--text-muted)" : "var(--text-primary)" }}>{r.value}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
