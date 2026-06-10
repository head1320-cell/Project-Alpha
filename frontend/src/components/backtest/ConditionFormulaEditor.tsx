"use client";
// 대상 경로: frontend/src/components/backtest/ConditionFormulaEditor.tsx
//
// 조건식 설정 에디터. 팩터 선택은 FactorPickerModal 이 담당하고,
// 여기서는 [팩터+함수] 에 연산자·값을 붙여 조건(Condition)을 만들고 리스트로 관리한다.
// 만드는 즉시 "이 조건 — …" NL 한 줄로 의미를 보여준다.

import { useState } from "react";
import { Plus, Pencil, X, Check, Variable, ArrowRight } from "lucide-react";
import FactorPickerModal, { type FactorPick } from "./FactorPickerModal";
import { FUNCTIONS_BY_ID, fillTemplate } from "../../lib/backtest/factorFunctions";
import { Segmented, TONES, type Tone } from "./kit";

export interface Condition {
  id: string;
  factorName: string;
  factorToken: string;
  functionId: string;
  params: Record<string, string>;
  expr: string;       // 함수 적용 좌항 (예: "이동평균({고가}, 20)")
  op: OpId;
  rhs: string;
  rhs2?: string;      // between 일 때 상한
}

type OpId = "gte" | "lte" | "eq" | "between";
const OPS: { id: OpId; label: string; word: string }[] = [
  { id: "gte", label: "≥", word: "이상" },
  { id: "lte", label: "≤", word: "이하" },
  { id: "eq", label: "=", word: "와 같을 때" },
  { id: "between", label: "범위", word: "사이" },
];
const opSym = (id: OpId) => OPS.find((o) => o.id === id)!.label;
const opWord = (id: OpId) => OPS.find((o) => o.id === id)!.word;

const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";
const uid = () => Math.random().toString(36).slice(2, 9);

interface Draft { factorName: string; factorToken: string; functionId: string; params: Record<string, string>; expr: string; op: OpId; rhs: string; rhs2: string }
const emptyDraft = (): Draft => ({ factorName: "", factorToken: "", functionId: "base", params: {}, expr: "", op: "lte", rhs: "", rhs2: "" });

export default function ConditionFormulaEditor({ tone = "neutral", conditions, onChange }: {
  tone?: Tone; conditions: Condition[]; onChange: (c: Condition[]) => void;
}) {
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [pickerOpen, setPickerOpen] = useState(false);
  const accent = TONES[tone];

  const applyPick = (p: FactorPick) => {
    setDraft((d) => ({ ...d, factorName: p.factorName, factorToken: p.factorToken, functionId: p.functionId, params: p.params, expr: p.expr }));
    setPickerOpen(false);
  };

  const save = () => {
    if (!draft.factorName || draft.rhs === "") return;
    onChange([...conditions, { id: uid(), factorName: draft.factorName, factorToken: draft.factorToken, functionId: draft.functionId, params: draft.params, expr: draft.expr, op: draft.op, rhs: draft.rhs, rhs2: draft.op === "between" ? draft.rhs2 : undefined }]);
    setDraft(emptyDraft());
  };
  const remove = (id: string) => onChange(conditions.filter((c) => c.id !== id));

  // NL 한 줄
  const fn = FUNCTIONS_BY_ID[draft.functionId];
  const human = draft.factorName ? fillTemplate(fn.sentence ?? fn.preview, draft.factorName, draft.params) : "";
  const sentence = draft.factorName && draft.rhs !== ""
    ? (draft.op === "between"
        ? `${human}가 ${draft.rhs} ~ ${draft.rhs2 || "?"} 사이일 때 통과`
        : `${human}가 ${draft.rhs} ${opWord(draft.op)}일 때 통과`)
    : "팩터를 선택하고 값을 입력하면 조건이 완성돼요.";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "228px minmax(0,1fr)", gap: 14, alignItems: "start" }}>

      {/* 좌: 조건 리스트 */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)", marginBottom: 9 }}>조건식</div>
        {conditions.map((c, i) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, background: accent.bg, border: `1px solid ${accent.accent}`, borderRadius: R, padding: "9px 11px", marginBottom: 7 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, color: accent.text, marginBottom: 2 }}>조건식 {String.fromCharCode(65 + i)}</div>
              <div style={{ fontFamily: "var(--bs-font-mono)", fontSize: 13, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {c.expr} {opSym(c.op)} {c.rhs}{c.op === "between" ? `~${c.rhs2}` : ""}
              </div>
            </div>
            <button type="button" onClick={() => remove(c.id)} aria-label="삭제" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", flexShrink: 0 }}><X size={14} /></button>
          </div>
        ))}
        <button type="button" onClick={() => { setDraft(emptyDraft()); setPickerOpen(true); }}
          style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 4, fontSize: 12, color: "var(--text-secondary)", background: "none", border: "1px dashed var(--border-strong)", borderRadius: R, padding: "8px 0", cursor: "pointer" }}>
          <Plus size={13} /> 조건식 추가
        </button>
      </div>

      {/* 우: 조건식 설정(드래프트) */}
      <div style={{ background: "var(--bg-section)", borderRadius: RL, padding: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)", marginBottom: 13 }}>조건식 설정</div>

        {/* 팩터+함수 선택 트리거 */}
        <button type="button" onClick={() => setPickerOpen(true)}
          style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--bs-font-mono)", fontSize: 14, color: draft.factorName ? "var(--text-primary)" : "var(--text-muted)", background: "var(--bg-card)", border: "1px solid var(--border-strong)", borderRadius: R, padding: "10px 12px", cursor: "pointer", marginBottom: 12, textAlign: "left" }}>
          <Variable size={15} style={{ color: accent.accent, flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {draft.expr || "팩터 · 함수를 선택하세요"}
          </span>
          <Pencil size={14} style={{ color: "var(--text-secondary)", flexShrink: 0 }} />
        </button>

        {/* 연산자 + 값 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 13, flexWrap: "wrap" }}>
          <Segmented tone={tone} value={draft.op} onChange={(op) => setDraft((d) => ({ ...d, op }))}
            options={OPS.map((o) => ({ id: o.id, label: o.label }))} />
          <input type="number" value={draft.rhs} onChange={(e) => setDraft((d) => ({ ...d, rhs: e.target.value }))} placeholder="값"
            style={{ width: 70, fontFamily: "var(--bs-font-mono)", fontSize: 15, textAlign: "center", padding: "9px 11px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
          {draft.op === "between" && (
            <>
              <span style={{ color: "var(--text-secondary)" }}>~</span>
              <input type="number" value={draft.rhs2} onChange={(e) => setDraft((d) => ({ ...d, rhs2: e.target.value }))} placeholder="상한"
                style={{ width: 70, fontFamily: "var(--bs-font-mono)", fontSize: 15, textAlign: "center", padding: "9px 11px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
            </>
          )}
        </div>

        {/* NL 한 줄 */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8, background: "var(--bg-card)", border: `1px solid ${accent.accent}`, borderRadius: R, padding: "11px 12px", marginBottom: 14 }}>
          <ArrowRight size={15} style={{ color: accent.text, marginTop: 2, flexShrink: 0 }} />
          <span style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            {draft.factorName ? <>이 조건 — <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{sentence}</span></> : sentence}
          </span>
        </div>

        <button type="button" onClick={save} disabled={!draft.factorName || draft.rhs === ""}
          style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 5, fontSize: 13, color: "#fff", background: (draft.factorName && draft.rhs !== "") ? accent.accent : "var(--border-strong)", border: "none", borderRadius: R, padding: "10px 0", cursor: (draft.factorName && draft.rhs !== "") ? "pointer" : "not-allowed" }}>
          <Check size={14} /> 조건식 저장
        </button>
      </div>

      <FactorPickerModal open={pickerOpen} tone={tone}
        initial={{ functionId: draft.functionId, params: draft.params }}
        onClose={() => setPickerOpen(false)} onInsert={applyPick} />
    </div>
  );
}
