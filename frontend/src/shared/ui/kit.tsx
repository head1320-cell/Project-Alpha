"use client";
// 대상 경로: frontend/src/components/backtest/kit.tsx
//
// 백테스터 재설계의 공통 부품. 모든 화면이 이 5개로 조립된다.
// 색은 tone(buy=빨강 / sell=파랑 / neutral)으로 주입 — 구조는 동일.
// (원하면 TONES 를 globals.css 의 --buy/--sell 변수로 빼도 됨)

import { type ReactNode } from "react";
import { X } from "lucide-react";

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
// ★죽은 삼항 하나를 걷어냈다 (Phase B)★ 테두리 색이
// `enabled ? "var(--border)" : "var(--border)"` 였다 — 두 가지가 같은 값이라 조건이
// 아무 일도 하지 않았다. 비활성 상태를 구별하려던 흔적으로 보이지만, 지금 코드가 하는 일은
// "항상 같은 테두리" 이므로 그대로 유지하고 조건만 없앴다(동작 변화 0).
export function Section({ title, hint, tone = "neutral", enabled, onToggle, children }: {
  title: string; hint?: string; tone?: Tone; enabled: boolean;
  onToggle: (v: boolean) => void; children?: ReactNode;
}) {
  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--bs-border-radius-lg)] px-4 py-[15px]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, background: enabled ? TONES[tone].accent : "var(--border-strong)" }} />
          <span style={{ fontSize: 15, fontWeight: 500, color: enabled ? "var(--text-primary)" : "var(--text-muted)", flexShrink: 0 }}>{title}</span>
          {hint && <span style={{ fontSize: 12, color: enabled ? "var(--text-secondary)" : "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{hint}</span>}
        </div>
        <Toggle on={enabled} onChange={onToggle} tone={tone} />
      </div>
      {enabled && children && (
        <div className="border-t border-[var(--border)] mt-[13px] pt-3.5 flex flex-col gap-3.5">
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
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[13px] text-[var(--text-primary)]">{label}</span>
          {hint && <span className="text-[11px] text-[var(--text-secondary)]">{hint}</span>}
        </div>
        <Toggle on={on} onChange={onChange} tone={tone} size="sm" />
      </div>
      {on && children && <div className="mt-2.5 flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

// ── Field (labeled row) ───────────────────────────────────────
export function Field({ label, width = 84, children }: { label: string; width?: number; children: ReactNode }) {
  return (
    <div className="flex items-center gap-[9px] flex-wrap">
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
      {unit && <span className="text-[13px] text-[var(--text-secondary)]">{unit}</span>}
      <span className="flex gap-[5px]">
        {chips.map((c) => (
          <button key={c} type="button" onClick={() => onChange(clamp(value + c))}
            className="text-[11px] text-[var(--text-secondary)] bg-none cursor-pointer border border-[var(--border)] rounded-md px-2 py-1">
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
    <span className="flex gap-1 bg-[var(--bg-section)] rounded-[var(--bs-border-radius)] p-[3px]">
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
