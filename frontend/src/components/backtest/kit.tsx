"use client";
// 대상 경로: frontend/src/components/backtest/kit.tsx
//
// 백테스터 재설계의 공통 부품. 모든 화면이 이 5개로 조립된다.
// 색은 tone(buy=빨강 / sell=파랑 / neutral)으로 주입 — 구조는 동일.
// (원하면 TONES 를 globals.css 의 --buy/--sell 변수로 빼도 됨)

import { type ReactNode } from "react";
import { X } from "lucide-react";
import { buildSummary, type BacktestStrategy, type SummaryTab } from "../../lib/backtest/strategy";

export type Tone = "buy" | "sell" | "neutral";

export const TONES: Record<Tone, { accent: string; bg: string; text: string }> = {
  buy: { accent: "var(--danger)", bg: "var(--danger-light)", text: "var(--danger)" },
  sell: { accent: "#1565c0", bg: "#e7f0fb", text: "#1565c0" },
  neutral: { accent: "var(--text-primary)", bg: "var(--bg-section)", text: "var(--text-primary)" },
};

const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";

// ── GroupedSelect (optgroup 드롭다운 — 체결가 유형 등) ────────
export function GroupedSelect({ value, onChange, groups, width = 168 }: {
  value: string; onChange: (id: string) => void;
  groups: { label: string; options: { id: string; label: string }[] }[];
  width?: number;
}) {
  return (
    <select
      value={value} onChange={(e) => onChange(e.target.value)}
      style={{
        fontSize: 13, color: "var(--text-primary)", border: "1px solid var(--border-strong)",
        borderRadius: R, padding: "6px 9px", width, background: "var(--bg-card)", cursor: "pointer",
      }}
    >
      {groups.map((g) => (
        <optgroup key={g.label} label={g.label}>
          {g.options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

// ── Toggle (pill switch) ──────────────────────────────────────
export function Toggle({ on, onChange, tone = "neutral", size = "md" }: {
  on: boolean; onChange: (v: boolean) => void; tone?: Tone; size?: "sm" | "md";
}) {
  const w = size === "sm" ? 32 : 34;
  const k = size === "sm" ? 13 : 14;
  return (
    <button
      type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}
      style={{
        width: w, height: w === 34 ? 18 : 17, borderRadius: 9, border: "none", cursor: "pointer",
        padding: 2, boxSizing: "border-box", display: "inline-flex", alignItems: "center",
        justifyContent: on ? "flex-end" : "flex-start",
        background: on ? TONES[tone].accent : "var(--border-strong)", transition: "background .15s",
      }}
    >
      <span style={{ width: k, height: k, borderRadius: "50%", background: "#fff" }} />
    </button>
  );
}

// ── Section (collapsible card with on/off) ────────────────────
export function Section({ title, hint, tone = "neutral", enabled, onToggle, children }: {
  title: string; hint?: string; tone?: Tone; enabled: boolean;
  onToggle: (v: boolean) => void; children?: ReactNode;
}) {
  return (
    <div style={{ background: "var(--bg-card)", border: `1px solid ${enabled ? "var(--border)" : "var(--border)"}`, borderRadius: RL, padding: "15px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, background: enabled ? TONES[tone].accent : "var(--border-strong)" }} />
          <span style={{ fontSize: 15, fontWeight: 500, color: enabled ? "var(--text-primary)" : "var(--text-muted)", flexShrink: 0 }}>{title}</span>
          {hint && <span style={{ fontSize: 12, color: enabled ? "var(--text-secondary)" : "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{hint}</span>}
        </div>
        <Toggle on={enabled} onChange={onToggle} tone={tone} />
      </div>
      {enabled && children && (
        <div style={{ borderTop: "1px solid var(--border)", marginTop: 13, paddingTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ── SubToggle (advanced sub-row inside a section) ─────────────
export function SubToggle({ label, hint, on, onChange, tone = "neutral", children }: {
  label: string; hint?: string; on: boolean; onChange: (v: boolean) => void; tone?: Tone; children?: ReactNode;
}) {
  return (
    <div style={{ background: on ? TONES[tone].bg : "var(--bg-section)", borderRadius: R, padding: "10px 12px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, color: "var(--text-primary)" }}>{label}</span>
          {hint && <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>{hint}</span>}
        </div>
        <Toggle on={on} onChange={onChange} tone={tone} size="sm" />
      </div>
      {on && children && <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>{children}</div>}
    </div>
  );
}

// ── Field (labeled row) ───────────────────────────────────────
export function Field({ label, width = 84, children }: { label: string; width?: number; children: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
      <span style={{ fontSize: 12, color: "var(--text-secondary)", width, flexShrink: 0 }}>{label}</span>
      {children}
    </div>
  );
}

const numBox: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 14, color: "var(--text-primary)",
  border: "1px solid var(--border-strong)", borderRadius: R, padding: "6px 8px",
  width: 100, textAlign: "center", background: "var(--bg-card)",
};

// ── QuickStepper (number + quick +/- chips) ──────────────────
export function QuickStepper({ value, onChange, chips = [], unit = "", min, max }: {
  value: number; onChange: (v: number) => void; chips?: number[]; unit?: string; min?: number; max?: number;
}) {
  const clamp = (n: number) => Math.max(min ?? -Infinity, Math.min(max ?? Infinity, n));
  return (
    <>
      <input type="number" className="bs-numbox" value={value}
        onChange={(e) => onChange(clamp(Number(e.target.value)))} style={numBox} />
      {unit && <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{unit}</span>}
      <span style={{ display: "flex", gap: 5 }}>
        {chips.map((c) => (
          <button key={c} type="button" onClick={() => onChange(clamp(value + c))}
            style={{ fontSize: 11, color: "var(--text-secondary)", background: "none", cursor: "pointer", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px" }}>
            {c > 0 ? `+${c}` : c}{unit}
          </button>
        ))}
      </span>
    </>
  );
}

// ── Segmented (selectable button group) ───────────────────────
export function Segmented<T extends string>({ options, value, onChange, tone = "neutral" }: {
  options: { id: T; label: string }[]; value: T; onChange: (v: T) => void; tone?: Tone;
}) {
  return (
    <span style={{ display: "flex", gap: 4, background: "var(--bg-section)", borderRadius: R, padding: 3 }}>
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button key={o.id} type="button" onClick={() => onChange(o.id)}
            style={{
              fontSize: 12, padding: "4px 13px", border: "none", cursor: "pointer", borderRadius: 6,
              background: on ? TONES[tone].bg : "transparent",
              color: on ? TONES[tone].text : "var(--text-secondary)", fontWeight: on ? 500 : 400,
            }}>
            {o.label}
          </button>
        );
      })}
    </span>
  );
}

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
