"use client";
// 백테스터 편집기의 공통 부품(kit) — Section · SubToggle · Field · Toggle · QuickStepper · Segmented · GroupedSelect.
//
// BU3: 인라인 style 을 걷고 클래스(`kit-*`) + data 속성(`data-on`·`data-tone`)으로 그린다. 겉은 `--tx-*`(globals.css 끝 BU3 절).
// 톤: buy = 빨강(사기) · sell = 파랑(팔기) — 한국 증권 앱의 관례이자 사용자가 고른 한국식 색 축. neutral = 파랑 강조.
// 색만으로 말하지 않는다 — 모든 토글·단추는 라벨과 함께 있다.
// ★동작·DOM 역할은 그대로★(role=switch · aria-checked · `.bs-numbox` · button 묶음) — `/dev/ui` kit 표본 테스트가 구조로 건다.
// 이름(접근성 P0-4): 스위치 · 숫자 칸 · 고르기 칸은 곁에 ★보이는 글자★와 `aria-labelledby` 로 잇는다 — Section · SubToggle 이 제 스위치를,
//   Field · SubToggle 이 안의 숫자 칸 · 고르기 칸을(문맥으로) 잇는다. 한 줄에 칸이 둘이거나 줄 밖에 있으면 호출부가 `label` 을 준다.
//   화면의 글자 · 모습은 그대로다(더한 것은 id 와 aria 속성뿐) — `e2e/kit-names.spec.ts`.

import { createContext, useContext, useId, type CSSProperties, type ReactNode } from "react";

export type Tone = "buy" | "sell" | "neutral";

/** 이 줄의 보이는 글자(라벨)의 id — Field · SubToggle 이 주고, 안의 숫자 칸 · 고르기 칸이 받아 제 이름으로 삼는다. */
const LabelIdCtx = createContext<string | undefined>(undefined);

// ── GroupedSelect (optgroup 드롭다운 — 체결가 유형 등) ────────
export function GroupedSelect({ value, onChange, groups, width = 168, label }: {
  value: string; onChange: (id: string) => void;
  groups: { label: string; options: { id: string; label: string }[] }[];
  width?: number;
  /** 줄(Field) 밖에 있거나 그 줄의 글자가 이 칸의 이름이 아닐 때. 없으면 줄의 글자를 따른다. */
  label?: string;
}) {
  const rowLabel = useContext(LabelIdCtx);
  return (
    <select className="kit-select" value={value} onChange={(e) => onChange(e.target.value)} style={{ width }}
      aria-label={label} aria-labelledby={label ? undefined : rowLabel}>
      {groups.map((g) => (
        <optgroup key={g.label} label={g.label}>
          {g.options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

// ── Toggle (스위치) ──────────────────────────────────────────
export function Toggle({ on, onChange, tone = "neutral", size = "md", act, labelledBy, label }: {
  on: boolean; onChange: (v: boolean) => void; tone?: Tone; size?: "sm" | "md"; act?: string;
  /** 이 스위치의 이름이 되는 보이는 글자의 id(Section · SubToggle 이 준다). 낱으로 쓸 때는 `label`. */
  labelledBy?: string; label?: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} data-act={act}
      aria-labelledby={labelledBy} aria-label={labelledBy ? undefined : label}
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
  const titleId = useId();
  return (
    <div className="kit-sec" data-tone={tone} data-on={enabled ? "1" : "0"}>
      <div className="kit-sec-head">
        <div className="kit-sec-title">
          <span className="kit-sec-t" id={titleId}>{title}</span>
          {hint && <span className="kit-sec-hint">{hint}</span>}
        </div>
        {onToggle && <Toggle on={enabled} onChange={onToggle} tone={tone} act={act} labelledBy={titleId} />}
      </div>
      {enabled && children && <div className="kit-sec-body">{children}</div>}
    </div>
  );
}

// ── SubToggle (절 안의 켜고 끄는 줄) ─────────────────────────
export function SubToggle({ label, hint, on, onChange, tone = "neutral", act, children }: {
  label: string; hint?: string; on: boolean; onChange: (v: boolean) => void; tone?: Tone; act?: string; children?: ReactNode;
}) {
  const labelId = useId();
  return (
    <div className="kit-sub" data-tone={tone} data-on={on ? "1" : "0"}>
      <div className="kit-sub-head">
        <div className="kit-sub-title">
          <span className="kit-sub-l" id={labelId}>{label}</span>
          {hint && <span className="kit-sub-hint">{hint}</span>}
        </div>
        <Toggle on={on} onChange={onChange} tone={tone} size="sm" act={act} labelledBy={labelId} />
      </div>
      {on && children && <div className="kit-sub-body"><LabelIdCtx.Provider value={labelId}>{children}</LabelIdCtx.Provider></div>}
    </div>
  );
}

// ── Field (라벨 + 칸) ────────────────────────────────────────
export function Field({ label, width = 84, children }: { label: string; width?: number; children: ReactNode }) {
  const labelId = useId();
  return (
    <div className="kit-field" style={{ "--kit-lw": `${width}px` } as CSSProperties}>
      <span className="kit-field-l" id={labelId}>{label}</span>
      <LabelIdCtx.Provider value={labelId}>{children}</LabelIdCtx.Provider>
    </div>
  );
}

// ── QuickStepper (숫자 + 빠른 더하기 칩) ──────────────────────
export function QuickStepper({ value, onChange, chips = [], unit = "", min, max, act, label }: {
  value: number; onChange: (v: number) => void; chips?: number[]; unit?: string; min?: number; max?: number; act?: string;
  /** 한 줄에 숫자 칸이 둘이거나 줄 밖에 있을 때. 없으면 줄의 글자(+ 단위)를 따른다. */
  label?: string;
}) {
  const rowLabel = useContext(LabelIdCtx);
  const unitId = useId();
  const clamp = (n: number) => Math.max(min ?? -Infinity, Math.min(max ?? Infinity, n));
  // 이름 = 줄의 글자 + 단위("투자 금액 만원"). 줄의 글자가 없으면 단위만으로 이름을 짓지 않는다 — '%' 는 이름이 아니다.
  const labelledBy = label || !rowLabel ? undefined : unit ? `${rowLabel} ${unitId}` : rowLabel;
  return (
    <>
      <input type="number" className="bs-numbox kit-num" value={value} data-act={act}
        aria-label={label} aria-labelledby={labelledBy}
        onChange={(e) => onChange(clamp(Number(e.target.value)))} />
      {unit && <span className="kit-unit" id={unitId}>{unit}</span>}
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
