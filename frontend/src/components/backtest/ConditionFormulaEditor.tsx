"use client";
// 대상 경로: frontend/src/components/backtest/ConditionFormulaEditor.tsx
//
// 조건식 설정 에디터. 팩터 선택은 FactorPickerModal 이 담당하고,
// 여기서는 [팩터+함수] 에 연산자·값을 붙여 조건(Condition)을 만들고 리스트로 관리한다.
// 만드는 즉시 "이 조건 — …" NL 한 줄로 의미를 보여준다.

import { useState } from "react";
import { Plus, Pencil, X, Check, Variable, ArrowRight, ShieldCheck } from "lucide-react";
import FactorPickerModal, { type FactorPick } from "./FactorPickerModal";
import { FUNCTIONS_BY_ID, fillTemplate } from "../../lib/backtest/factorFunctions";
import { backtestBridgeApi } from "../../lib/screenerApi";
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
  // 중첩(순위/비율 전용): 랭킹 대상 파생 지표 — 예: 순위(변화율_기간(종가,20))
  innerFunctionId?: string;
  innerParams?: Record<string, string>;
  // 두 팩터 변형(비교/큰값/작은값/변화율_팩터)의 두 번째 피연산자 + 자체 중첩
  factorName2?: string;
  factorToken2?: string;
  inner2FunctionId?: string;
  inner2Params?: Record<string, string>;
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

interface Draft { factorName: string; factorToken: string; functionId: string; params: Record<string, string>; expr: string; op: OpId; rhs: string; rhs2: string; innerFunctionId?: string; innerParams?: Record<string, string>; factorName2?: string; factorToken2?: string; inner2FunctionId?: string; inner2Params?: Record<string, string> }
const emptyDraft = (): Draft => ({ factorName: "", factorToken: "", functionId: "base", params: {}, expr: "", op: "lte", rhs: "", rhs2: "" });

export default function ConditionFormulaEditor({ tone = "neutral", conditions, onChange, logicExpr, onLogicChange, logicDefaultLabel = "모두 AND" }: {
  tone?: Tone; conditions: Condition[]; onChange: (c: Condition[]) => void;
  /** 논리 조건식 (젠포트 논리 레이어) — 전달하면 조건 리스트 아래 입력·검증 UI 노출 */
  logicExpr?: string; onLogicChange?: (v: string) => void; logicDefaultLabel?: string;
}) {
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [logicCheck, setLogicCheck] = useState<{ ok: boolean; msg: string } | null>(null);
  const accent = TONES[tone];

  const verifyLogic = async () => {
    const expr = (logicExpr ?? "").trim();
    if (!expr) { setLogicCheck({ ok: true, msg: `비어 있음 — 기본(${logicDefaultLabel}) 적용` }); return; }
    try {
      const r = await backtestBridgeApi.validateLogic(expr, conditions.length);
      setLogicCheck(r.ok
        ? { ok: true, msg: `유효한 식${r.lookback ? ` · 추가 룩백 ${r.lookback}봉` : ""}` }
        : { ok: false, msg: r.error ?? "식이 올바르지 않습니다" });
    } catch { setLogicCheck({ ok: false, msg: "검증 요청 실패 — 백엔드 연결을 확인하세요" }); }
  };

  const applyPick = (p: FactorPick) => {
    setDraft((d) => ({ ...d, factorName: p.factorName, factorToken: p.factorToken, functionId: p.functionId, params: p.params, expr: p.expr, innerFunctionId: p.innerFunctionId, innerParams: p.innerParams, factorName2: p.factorName2, factorToken2: p.factorToken2, inner2FunctionId: p.inner2FunctionId, inner2Params: p.inner2Params }));
    setPickerOpen(false);
  };

  const save = () => {
    if (!draft.factorName || draft.rhs === "") return;
    onChange([...conditions, { id: uid(), factorName: draft.factorName, factorToken: draft.factorToken, functionId: draft.functionId, params: draft.params, expr: draft.expr, op: draft.op, rhs: draft.rhs, rhs2: draft.op === "between" ? draft.rhs2 : undefined, innerFunctionId: draft.innerFunctionId, innerParams: draft.innerParams, factorName2: draft.factorName2, factorToken2: draft.factorToken2, inner2FunctionId: draft.inner2FunctionId, inner2Params: draft.inner2Params }]);
    setDraft(emptyDraft());
  };
  const remove = (id: string) => onChange(conditions.filter((c) => c.id !== id));

  // NL 한 줄 — 중첩이면 {f} 자리에 내부 지표 설명을 넣어 합성 ("20일 전 대비 종가 변화율 순위")
  // 두 팩터 조건은 픽커가 만든 식(expr)을 그대로 사용
  const fn = FUNCTIONS_BY_ID[draft.functionId];
  const innerFn = draft.innerFunctionId ? FUNCTIONS_BY_ID[draft.innerFunctionId] : null;
  const factorLabel = innerFn
    ? fillTemplate(innerFn.sentence ?? innerFn.preview, draft.factorName, draft.innerParams ?? {})
    : draft.factorName;
  const human = draft.factorName
    ? (draft.factorToken2 ? draft.expr : fillTemplate(fn.sentence ?? fn.preview, factorLabel, draft.params))
    : "";
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

        {/* 논리 조건식 (젠포트 논리 레이어) — and/or/not + before/any/every */}
        {onLogicChange && conditions.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)", marginBottom: 6 }}>논리 조건식</div>
            <input value={logicExpr ?? ""} spellCheck={false}
              onChange={(e) => { onLogicChange(e.target.value); setLogicCheck(null); }}
              placeholder={`예: every(A,3) and (B or C) — 비우면 ${logicDefaultLabel}`}
              style={{ width: "100%", boxSizing: "border-box", fontFamily: "var(--bs-font-mono)", fontSize: 13, padding: "9px 11px", border: `1px solid ${logicCheck && !logicCheck.ok ? "#dc2626" : "var(--border-strong)"}`, borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
              <button type="button" onClick={verifyLogic}
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: R, padding: "5px 9px", cursor: "pointer", flexShrink: 0 }}>
                <ShieldCheck size={13} /> 조건식 검증
              </button>
              {logicCheck && (
                <span style={{ fontSize: 11, color: logicCheck.ok ? "#16a34a" : "#dc2626" }}>{logicCheck.msg}</span>
              )}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5, lineHeight: 1.6 }}>
              and · or · not(A) · before(A,n) n일 전 성립 · any(A,n) n일 내 한번이라도 · every(A,n) n일 연속
            </div>
          </div>
        )}
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
        initial={{ functionId: draft.functionId, params: draft.params, innerFunctionId: draft.innerFunctionId, innerParams: draft.innerParams }}
        onClose={() => setPickerOpen(false)} onInsert={applyPick} />
    </div>
  );
}
