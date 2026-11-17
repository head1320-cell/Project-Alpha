"use client";
/**
 * 모형을 쓰는 지표의 칸 — 지금은 '하루 유형'(모형 · 유형 번호) 하나 (구현 계획 2026-11-16 §6 · T2)
 * ==========================================================================
 * 모형 목록은 ★내 모형만★이다(서버가 거른다 · 운영 게이트에서는 합성 모형이 빠지고 그 수와 사유가 온다).
 * 모형 칸에 들어갈 때마다 다시 읽는다 — 같은 화면의 '하루 유형' 절에서 막 학습한 모형이 바로 보이게. 읽지 못하면 빈 목록이 아니라 그 사유를 보인다.
 * ★처음에는 비어 있다★ — 도구는 모형을 고르지 않는다. 고른 모형의 유형 수가 번호 칸의 상한이다.
 * 학습 기간이 판정 시작일 뒤인지 · 남의 모형인지는 서버가 판정해 거절한다(이 부품은 판정하지 않는다).
 */
import { useState } from "react";
import { modelLabel, NO_MODELS, useDayTypeModels, type GrammarIndicator, type GrammarModelParam, type IndNode } from "@/entities/intraday";

const HEX64 = /^[0-9a-f]{64}$/;
export const isModelKey = (v: unknown): v is string => typeof v === "string" && HEX64.test(v);

function NumberInput({ label, value, onChange, min, max }: {
  label: string; value: number | null; onChange: (v: number | null) => void; min: number; max: number;
}) {
  const [typing, setTyping] = useState<string | null>(null);
  const shown = typing ?? (value === null ? "" : String(value));
  const bad = value === null || !Number.isInteger(value) || value < min || value > max;
  return (
    <input className="ire-input" inputMode="numeric" autoComplete="off" aria-label={label} aria-invalid={bad} value={shown}
           onFocus={() => setTyping(shown)} onBlur={() => setTyping(null)}
           onChange={(e) => { setTyping(e.target.value); const t = e.target.value.trim(); onChange(/^\d+$/.test(t) ? Number(t) : null); }} />
  );
}

/** 모형 칸 하나 + 나머지 수 칸(유형 번호 — 상한은 고른 모형의 유형 수와 문법 표의 상한 가운데 작은 것). */
export function ModelParams({ spec, node, set }: { spec: GrammarIndicator; node: IndNode; set: (next: IndNode) => void }) {
  const { models, note, reload } = useDayTypeModels();
  const keyParam = spec.params.find((p): p is GrammarModelParam => p.type === "model");
  if (!keyParam) return null;
  const raw = node[keyParam.key];
  const value = isModelKey(raw) ? raw : null;
  const known = models?.find((m) => m.key === value) ?? null;
  return (
    <span className="ire-model" data-kind={keyParam.kind}>
      <span className="ire-param" data-param={keyParam.key}>
        <span className="ire-param-label">{keyParam.label}</span>
        <select className="ire-select ire-model-pick" aria-label={`${spec.label} ${keyParam.label}`} aria-invalid={value === null || (models !== null && !known)}
                value={value ?? ""} onFocus={reload} onChange={(e) => set({ ...node, [keyParam.key]: e.target.value || null })}>
          <option value="">모형 선택</option>
          {/* 시행에서 불러온 열쇠가 지금 목록에 없을 수 있다 — 지우지 않고 앞 여덟 자리로 남긴다(판정은 서버가 한다). */}
          {value !== null && !known ? <option value={value}>{value.slice(0, 8)}</option> : null}
          {(models ?? []).map((m) => <option key={m.key} value={m.key}>{modelLabel(m)}</option>)}
        </select>
      </span>
      {spec.params.map((p) => (p.type === "model" ? null : (
        <span key={p.key} className="ire-param" data-param={p.key}>
          <span className="ire-param-label">{p.label}</span>
          <NumberInput label={`${spec.label} ${p.label}`} min={p.min} max={known ? Math.min(p.max, known.k) : p.max}
                       value={typeof node[p.key] === "number" ? (node[p.key] as number) : null} onChange={(v) => set({ ...node, [p.key]: v })} />
          <span className="ire-unit">{p.unit}</span>
        </span>
      )))}
      {note ? <span className="ire-model-note" role="status">{note}</span> : null}
      {models !== null && models.length === 0 ? <span className="ire-model-note" role="status">{NO_MODELS}</span> : null}
    </span>
  );
}
