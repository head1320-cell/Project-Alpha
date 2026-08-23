"use client";
// 전략 요약 레일. shared/ui/kit.tsx에 있었지만 BacktestStrategy/buildSummary에 의존한다 —
// 백테스터 전용 UI이므로 이 슬라이스로 올렸다(kit의 범용 프리미티브는 shared에 남음).

import { buildSummary, type BacktestStrategy, type SummaryTab } from "@/entities/backtest/strategy";
import { X } from "lucide-react";
import { TONES, type Tone } from "@/shared/ui/kit";

// kit.tsx의 모듈 내부 상수였다 — 함께 옮긴다(값 불변).
const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";


// ── SummaryRail (always-on "전략 요약") ───────────────
const TAB_TONE: Record<SummaryTab, Tone> = { buy: "buy", sell: "sell", universe: "neutral" };
const TAB_LABEL: Record<SummaryTab, string> = { buy: "매수", sell: "매도", universe: "대상" };

export function SummaryRail({ strategy, tab, onTab, onClose }: {
  strategy: BacktestStrategy; tab: SummaryTab; onTab: (t: SummaryTab) => void; onClose?: () => void;
}) {
  const groups = buildSummary(strategy, tab);
  return (
    <aside style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: RL, padding: "14px 13px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>전략 요약</span>
        {onClose && <button type="button" onClick={onClose} aria-label="닫기" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-tertiary, var(--text-muted))", display: "flex" }}><X size={15} /></button>}
      </div>
      <div style={{ display: "flex", gap: 3, background: "var(--bg-section)", borderRadius: R, padding: 3, marginBottom: 14 }}>
        {(["buy", "sell", "universe"] as SummaryTab[]).map((t) => {
          const on = t === tab;
          return (
            <button key={t} type="button" onClick={() => onTab(t)}
              style={{
                flex: 1, fontSize: 11, padding: "4px 0", border: "none", cursor: "pointer", borderRadius: 5,
                background: on ? (t === "universe" ? "var(--bg-card)" : TONES[TAB_TONE[t]].bg) : "transparent",
                color: on ? (t === "universe" ? "var(--text-primary)" : TONES[TAB_TONE[t]].text) : "var(--text-secondary)",
                boxShadow: on && t === "universe" ? "inset 0 0 0 1px var(--border-strong)" : undefined,
              }}>
              {TAB_LABEL[t]}
            </button>
          );
        })}
      </div>
      {groups.map((g, gi) => (
        <div key={g.label} style={gi ? { borderTop: "1px solid var(--border)", marginTop: 11, paddingTop: 11 } : undefined}>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>{g.label}</div>
          {g.rows.map((r) => (
            <div key={r.label} style={{ display: "flex", justifyContent: "space-between", gap: 6, padding: "2px 0" }}>
              <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{r.label}</span>
              <span style={{ fontSize: 12, fontWeight: r.muted ? 400 : 500, color: r.muted ? "var(--text-muted)" : "var(--text-primary)", textAlign: "right" }}>{r.value}</span>
            </div>
          ))}
        </div>
      ))}
    </aside>
  );
}

