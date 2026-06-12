"use client";
// 대상 경로: frontend/src/components/backtest/ConditionFormulaEditor.tsx
//
// 조건식 설정 에디터. 팩터 선택은 FactorPickerModal 이 담당하고,
// 여기서는 [팩터+함수] 에 연산자·값을 붙여 조건(Condition)을 만들고 리스트로 관리한다.
// 만드는 즉시 "이 조건 — …" NL 한 줄로 의미를 보여준다.

import { useState } from "react";
import { Plus, Pencil, X, Check, Variable, ArrowRight, ShieldCheck, Save, FolderOpen, Sparkles } from "lucide-react";
import FactorPickerModal, { type FactorPick } from "./FactorPickerModal";
import { FUNCTIONS_BY_ID, fillTemplate } from "../../lib/backtest/factorFunctions";
import { backtestBridgeApi } from "../../lib/screenerApi";
import {
  listConditionSets, saveConditionSet, deleteConditionSet, cloneConditions,
  type SavedConditionSet,
} from "../../lib/backtest/conditionSets";
import { Segmented, TONES, type Tone } from "./kit";

export interface Condition {
  id: string;
  factorName: string;
  factorToken: string;
  functionId: string;
  params: Record<string, string>;
  expr: string;       // 함수 적용 좌항 (예: "이동평균({고가}, 20)") — direct면 산술식 원문
  direct?: boolean;   // 직접 입력(자유 산술식): expr를 백엔드 factor_expr로 평가
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

export default function ConditionFormulaEditor({ tone = "neutral", conditions, onChange, logicExpr, onLogicChange, logicDefaultLabel = "모두 AND", sideKey }: {
  tone?: Tone; conditions: Condition[]; onChange: (c: Condition[]) => void;
  /** 논리 조건식 (젠포트 논리 레이어) — 전달하면 조건 리스트 아래 입력·검증 UI 노출 */
  logicExpr?: string; onLogicChange?: (v: string) => void; logicDefaultLabel?: string;
  /** 조건식 세트 저장/불러오기 활성 (매수/매도 조건에서만 — 마켓타이밍 제외) */
  sideKey?: "buy" | "sell";
}) {
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [logicCheck, setLogicCheck] = useState<{ ok: boolean; msg: string } | null>(null);
  const [setsOpen, setSetsOpen] = useState(false);
  const [savedSets, setSavedSets] = useState<SavedConditionSet[]>([]);
  const [saveName, setSaveName] = useState("");
  // 직접 입력(자유 산술식) 모드 + AI 자연어 변환
  const [inputMode, setInputMode] = useState<"picker" | "direct">("picker");
  const [directExpr, setDirectExpr] = useState("");
  const [exprCheck, setExprCheck] = useState<{ ok: boolean; msg: string } | null>(null);
  const [nlQuery, setNlQuery] = useState("");
  const [nlBusy, setNlBusy] = useState(false);
  const [nlMsg, setNlMsg] = useState<string | null>(null);
  const accent = TONES[tone];

  const verifyExpr = async () => {
    const expr = directExpr.trim();
    if (!expr) { setExprCheck(null); return; }
    try {
      const r = await backtestBridgeApi.validateExpr(expr);
      if (!r.ok) setExprCheck({ ok: false, msg: r.error ?? "식이 올바르지 않습니다" });
      else setExprCheck({
        ok: true,
        msg: `유효한 식${r.lookback ? ` · 룩백 ${r.lookback}봉` : ""}${r.unknown_tokens?.length ? ` · ⚠ 미지원 토큰(건너뜀): ${r.unknown_tokens.join(", ")}` : ""}`,
      });
    } catch { setExprCheck({ ok: false, msg: "검증 요청 실패 — 백엔드 연결을 확인하세요" }); }
  };

  const saveDirect = () => {
    const expr = directExpr.trim();
    if (!expr || draft.rhs === "") return;
    onChange([...conditions, {
      id: uid(), factorName: expr, factorToken: "", functionId: "expr", params: {},
      expr, direct: true, op: draft.op, rhs: draft.rhs,
      rhs2: draft.op === "between" ? draft.rhs2 : undefined,
    }]);
    setDirectExpr(""); setExprCheck(null); setDraft(emptyDraft());
  };

  const runNl = async () => {
    const q = nlQuery.trim();
    if (!q || nlBusy) return;
    setNlBusy(true); setNlMsg(null);
    try {
      const r = await backtestBridgeApi.conditionNl(q);
      const added: Condition[] = r.conditions.map((c) => ({
        id: uid(),
        factorName: c.expr ?? (c.factor_token ?? ""),
        factorToken: c.factor_token ?? "",
        functionId: c.expr ? "expr" : (c.function_id ?? "base"),
        params: (c.params as Record<string, string>) ?? {},
        expr: c.expr ?? `${c.factor_token ?? ""}`,
        direct: !!c.expr,
        op: (c.op as OpId) ?? "gte",
        rhs: String(c.rhs ?? ""),
      }));
      if (added.length) onChange([...conditions, ...added]);
      const skip = r.skipped?.length ? ` · 변환 불가 ${r.skipped.length}건` : "";
      setNlMsg(added.length
        ? `${added.length}개 조건 추가 (${r.source === "claude" ? "AI" : "규칙"})${skip} — 펀더멘털 토큰은 '펀더멘털 조건 평가' 토글 필요`
        : `변환된 조건이 없습니다${skip}`);
      setNlQuery("");
    } catch { setNlMsg("변환 요청 실패 — 백엔드 연결을 확인하세요"); }
    finally { setNlBusy(false); }
  };

  const refreshSets = () => setSavedSets(sideKey ? listConditionSets(sideKey) : []);
  const toggleSets = () => { if (!setsOpen) refreshSets(); setSetsOpen(!setsOpen); };
  const handleSaveSet = () => {
    if (!sideKey || conditions.length === 0) return;
    saveConditionSet(saveName, sideKey, conditions, (logicExpr ?? "").trim());
    setSaveName("");
    refreshSets();
    setSetsOpen(true);
  };
  const handleLoadSet = (s: SavedConditionSet) => {
    onChange(cloneConditions(s.conditions));
    onLogicChange?.(s.logicExpr);
    setLogicCheck(null);
  };

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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 9 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>조건식</span>
          {sideKey && (
            <button type="button" onClick={toggleSets}
              style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: R, padding: "3px 8px", cursor: "pointer" }}>
              <FolderOpen size={12} /> 불러오기·저장
            </button>
          )}
        </div>
        {sideKey && setsOpen && (
          <div style={{ border: "1px solid var(--border-strong)", borderRadius: R, padding: 9, marginBottom: 9, display: "flex", flexDirection: "column", gap: 7 }}>
            <div style={{ display: "flex", gap: 6 }}>
              <input value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="세트 이름"
                style={{ flex: 1, minWidth: 0, fontSize: 12, padding: "5px 8px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
              <button type="button" onClick={handleSaveSet} disabled={conditions.length === 0}
                style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, color: conditions.length ? "#fff" : "var(--text-muted)", background: conditions.length ? accent.accent : "var(--border-strong)", border: "none", borderRadius: R, padding: "5px 9px", cursor: conditions.length ? "pointer" : "not-allowed", flexShrink: 0 }}>
                <Save size={12} /> 저장
              </button>
            </div>
            {savedSets.length === 0 ? (
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>저장된 조건식 세트가 없습니다</span>
            ) : savedSets.map((sv) => (
              <div key={sv.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <button type="button" onClick={() => handleLoadSet(sv)} title="이 세트 불러오기"
                  style={{ flex: 1, minWidth: 0, textAlign: "left", fontSize: 12, color: "var(--text-primary)", background: "var(--bg-section)", border: "1px solid var(--border-strong)", borderRadius: R, padding: "5px 8px", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {sv.name} <span style={{ color: "var(--text-muted)" }}>({sv.conditions.length}개{sv.logicExpr ? " · 논리식" : ""})</span>
                </button>
                <button type="button" onClick={() => { deleteConditionSet(sv.id); refreshSets(); }} aria-label="세트 삭제"
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", flexShrink: 0 }}><X size={13} /></button>
              </div>
            ))}
          </div>
        )}
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 13 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>조건식 설정</span>
          <Segmented tone={tone} value={inputMode} onChange={(m) => setInputMode(m)}
            options={[{ id: "picker", label: "팩터 선택" }, { id: "direct", label: "직접 입력" }]} />
        </div>

        {inputMode === "direct" ? (
          <div style={{ marginBottom: 12 }}>
            <input value={directExpr} spellCheck={false}
              onChange={(e) => { setDirectExpr(e.target.value); setExprCheck(null); }}
              placeholder="예: ({분기영업현금흐름}-{분기순이익}) 또는 {종가}/과거값('최고값({고가},{40일})',{1일})"
              style={{ width: "100%", boxSizing: "border-box", fontFamily: "var(--bs-font-mono)", fontSize: 13, padding: "10px 12px", border: `1px solid ${exprCheck && !exprCheck.ok ? "#dc2626" : "var(--border-strong)"}`, borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
              <button type="button" onClick={verifyExpr}
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: R, padding: "5px 9px", cursor: "pointer", flexShrink: 0 }}>
                <ShieldCheck size={13} /> 식 검증
              </button>
              {exprCheck && <span style={{ fontSize: 11, color: exprCheck.ok ? "#16a34a" : "#dc2626" }}>{exprCheck.msg}</span>}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5, lineHeight: 1.6 }}>
              사칙연산(+,−,×,÷)·괄호·{"{팩터}"}·함수 조합 — 인용부호(&apos;)는 중첩 인자 묶음 · 우변은 아래 값
            </div>
          </div>
        ) : (
        /* 팩터+함수 선택 트리거 */
        <button type="button" onClick={() => setPickerOpen(true)}
          style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--bs-font-mono)", fontSize: 14, color: draft.factorName ? "var(--text-primary)" : "var(--text-muted)", background: "var(--bg-card)", border: "1px solid var(--border-strong)", borderRadius: R, padding: "10px 12px", cursor: "pointer", marginBottom: 12, textAlign: "left" }}>
          <Variable size={15} style={{ color: accent.accent, flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {draft.expr || "팩터 · 함수를 선택하세요"}
          </span>
          <Pencil size={14} style={{ color: "var(--text-secondary)", flexShrink: 0 }} />
        </button>
        )}

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
            {inputMode === "direct"
              ? (directExpr.trim() && draft.rhs !== ""
                  ? <>이 조건 — <span style={{ fontFamily: "var(--bs-font-mono)", color: "var(--text-primary)" }}>{directExpr.trim()} {opSym(draft.op)} {draft.rhs}{draft.op === "between" ? `~${draft.rhs2}` : ""}</span></>
                  : "식을 입력하고 값을 넣으면 조건이 완성돼요.")
              : (draft.factorName ? <>이 조건 — <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{sentence}</span></> : sentence)}
          </span>
        </div>

        {inputMode === "direct" ? (
          <button type="button" onClick={saveDirect} disabled={!directExpr.trim() || draft.rhs === ""}
            style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 5, fontSize: 13, color: "#fff", background: (directExpr.trim() && draft.rhs !== "") ? accent.accent : "var(--border-strong)", border: "none", borderRadius: R, padding: "10px 0", cursor: (directExpr.trim() && draft.rhs !== "") ? "pointer" : "not-allowed" }}>
            <Check size={14} /> 조건식 저장
          </button>
        ) : (
        <button type="button" onClick={save} disabled={!draft.factorName || draft.rhs === ""}
          style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 5, fontSize: 13, color: "#fff", background: (draft.factorName && draft.rhs !== "") ? accent.accent : "var(--border-strong)", border: "none", borderRadius: R, padding: "10px 0", cursor: (draft.factorName && draft.rhs !== "") ? "pointer" : "not-allowed" }}>
          <Check size={14} /> 조건식 저장
        </button>
        )}

        {/* AI 자연어 변환 (매수 조건 전용 — 젠포트 AI 버튼) */}
        {sideKey === "buy" && (
          <div style={{ marginTop: 12, borderTop: "1px dashed var(--border-strong)", paddingTop: 11 }}>
            <div style={{ display: "flex", gap: 6 }}>
              <input value={nlQuery} onChange={(e) => setNlQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runNl(); }}
                placeholder="자연어로 입력 — 예: PER 15 이하이고 ROE 상위 30%"
                style={{ flex: 1, minWidth: 0, fontSize: 12, padding: "8px 10px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
              <button type="button" onClick={runNl} disabled={nlBusy || !nlQuery.trim()}
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 500, color: "#fff", background: nlBusy || !nlQuery.trim() ? "var(--border-strong)" : accent.accent, border: "none", borderRadius: R, padding: "8px 12px", cursor: nlBusy || !nlQuery.trim() ? "not-allowed" : "pointer", flexShrink: 0 }}>
                <Sparkles size={13} /> {nlBusy ? "변환 중…" : "AI 변환"}
              </button>
            </div>
            {nlMsg && <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 5 }}>{nlMsg}</div>}
          </div>
        )}
      </div>

      <FactorPickerModal open={pickerOpen} tone={tone}
        initial={{ functionId: draft.functionId, params: draft.params, innerFunctionId: draft.innerFunctionId, innerParams: draft.innerParams }}
        onClose={() => setPickerOpen(false)} onInsert={applyPick} />
    </div>
  );
}
