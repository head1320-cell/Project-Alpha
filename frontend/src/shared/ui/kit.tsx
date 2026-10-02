"use client";
// 백테스터 편집기의 공통 부품(kit) — Section · SubToggle · Field · Toggle · QuickStepper · Segmented · GroupedSelect.
//
// BU3: 인라인 style 을 걷고 클래스(`kit-*`) + data 속성(`data-on`·`data-tone`)으로 그린다. 겉은 `--tx-*`(globals.css 끝 BU3 절).
// 톤: buy = 빨강(사기) · sell = 파랑(팔기) — 한국 증권 앱의 관례이자 사용자가 고른 한국식 색 축. neutral = 파랑 강조.
// 색만으로 말하지 않는다 — 모든 토글·단추는 라벨과 함께 있다.
// ★동작·DOM 역할은 그대로★(role=switch · aria-checked · `.bs-numbox` · button 묶음) — `/dev/ui` kit 표본 테스트가 구조로 건다.
// `TONES` 는 팩터 고르기 창·조건식 편집기가 아직 쓴다(BU3c 에서 옮긴다) — 값은 그대로 둔다.

import { type CSSProperties, type ReactNode } from "react";

export type Tone = "buy" | "sell" | "neutral";

export const TONES: Record<Tone, { accent: string; bg: string; text: string }> = {
  buy: { accent: "var(--danger)", bg: "var(--danger-light)", text: "var(--danger)" },
  sell: { accent: "var(--hx-t-1565c0)", bg: "var(--hx-b-e7f0fb)", text: "var(--hx-t-1565c0)" },
  neutral: { accent: "var(--kit-neutral)", bg: "var(--bg-section)", text: "var(--text-primary)" },
};

// ── GroupedSelect (optgroup 드롭다운 — 체결가 유형 등) ────────
export function GroupedSelect({ value, onChange, groups, width = 168 }: {
  value: string; onChange: (id: string) => void;
  groups: { label: string; options: { id: string; label: string }[] }[];
  width?: number;
}) {
  return (
    <select className="kit-select" value={value} onChange={(e) => onChange(e.target.value)} style={{ width }}>
      {groups.map((g) => (
        <optgroup key={g.label} label={g.label}>
          {g.options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

// ── Toggle (스위치) ──────────────────────────────────────────
export function Toggle({ on, onChange, tone = "neutral", size = "md", act }: {
  on: boolean; onChange: (v: boolean) => void; tone?: Tone; size?: "sm" | "md"; act?: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} data-act={act}
      className="kit-toggle" data-tone={tone} data-size={size}>
      <span className="kit-toggle-k" aria-hidden />
    </button>
  );
}

// ── Section (절 — 켜고 끌 수 있으면 스위치) ───────────────────
// ★`onToggle` 이 없으면 스위치를 그리지 않는다★(BU3) — 예전에는 늘 켜진 절에도 눌러도 아무 일 없는 스위치가 있었다(`onToggle={() => {}}`).
export function Section({ title, hint, tone = "neutral", enabled, onToggle, act, children }: {
  title: string; hint?: string; tone?: Tone; enabled: boolean;
  onToggle?: (v: boolean) => void; act?: string; children?: ReactNode;
}) {
  return (
    <div className="kit-sec" data-tone={tone} data-on={enabled ? "1" : "0"}>
      <div className="kit-sec-head">
        <div className="kit-sec-title">
          <span className="kit-sec-t">{title}</span>
          {hint && <span className="kit-sec-hint">{hint}</span>}
        </div>
        {onToggle && <Toggle on={enabled} onChange={onToggle} tone={tone} act={act} />}
      </div>
      {enabled && children && <div className="kit-sec-body">{children}</div>}
    </div>
  );
}

// ── SubToggle (절 안의 켜고 끄는 줄) ─────────────────────────
export function SubToggle({ label, hint, on, onChange, tone = "neutral", act, children }: {
  label: string; hint?: string; on: boolean; onChange: (v: boolean) => void; tone?: Tone; act?: string; children?: ReactNode;
}) {
  return (
    <div className="kit-sub" data-tone={tone} data-on={on ? "1" : "0"}>
      <div className="kit-sub-head">
        <div className="kit-sub-title">
          <span className="kit-sub-l">{label}</span>
          {hint && <span className="kit-sub-hint">{hint}</span>}
        </div>
        <Toggle on={on} onChange={onChange} tone={tone} size="sm" act={act} />
      </div>
      {on && children && <div className="kit-sub-body">{children}</div>}
    </div>
  );
}

// ── Field (라벨 + 칸) ────────────────────────────────────────
export function Field({ label, width = 84, children }: { label: string; width?: number; children: ReactNode }) {
  return (
    <div className="kit-field" style={{ "--kit-lw": `${width}px` } as CSSProperties}>
      <span className="kit-field-l">{label}</span>
      {children}
    </div>
  );
}

// ── QuickStepper (숫자 + 빠른 더하기 칩) ──────────────────────
export function QuickStepper({ value, onChange, chips = [], unit = "", min, max, act }: {
  value: number; onChange: (v: number) => void; chips?: number[]; unit?: string; min?: number; max?: number; act?: string;
}) {
  const clamp = (n: number) => Math.max(min ?? -Infinity, Math.min(max ?? Infinity, n));
  return (
    <>
      <input type="number" className="bs-numbox kit-num" value={value} data-act={act}
        onChange={(e) => onChange(clamp(Number(e.target.value)))} />
      {unit && <span className="kit-unit">{unit}</span>}
      {chips.length > 0 && (
        <span className="kit-chips">
          {chips.map((c) => (
            <button key={c} type="button" className="kit-chip" onClick={() => onChange(clamp(value + c))}>
              {c > 0 ? `+${c}` : c}{unit}
            </button>
          ))}
        </span>
      )}
    </>
  );
}

// ── Segmented (고르는 단추 묶음) ─────────────────────────────
export function Segmented<T extends string>({ options, value, onChange, tone = "neutral", act }: {
  options: { id: T; label: string }[]; value: T; onChange: (v: T) => void; tone?: Tone; act?: string;
}) {
  return (
    <span data-act={act} className="kit-seg" data-tone={tone}>
      {options.map((o) => (
        <button key={o.id} type="button" className="kit-seg-opt" aria-pressed={o.id === value} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </span>
  );
}
