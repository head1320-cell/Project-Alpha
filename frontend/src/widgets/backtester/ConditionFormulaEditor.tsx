"use client";
// 대상 경로: frontend/src/components/backtest/ConditionFormulaEditor.tsx
//
// 조건식 설정 에디터. 좌변(LHS)을 만드는 방법은 두 가지:
//   · 수식 빌더 — 팩터를 2개 이상 + 사칙연산으로 조합 (젠포트식, 클릭으로 구성)
//   · 직접 입력 — 자유 산술식을 그대로 타이핑
// 어느 쪽이든 백엔드(factor_expr.py)가 평가하는 산술식(direct)으로 직렬화된다.
// 좌변에 연산자(≥/≤/=/범위)·값을 붙여 조건(Condition)을 만들고 리스트로 관리한다.

import { useState } from "react";
import { X, Check, ArrowRight, ShieldCheck, Save, FolderOpen, Sparkles, Pencil } from "lucide-react";
import FormulaBuilder, { buildExpr, buildLabel, type FormulaToken } from "./FormulaBuilder";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import {
  listConditionSets, saveConditionSet, deleteConditionSet, cloneConditions,
  type SavedConditionSet,
} from "@/entities/backtest/conditionSets";
import { Segmented, TONES, type Tone } from "@/shared/ui/kit";
import type { Condition, OpId } from "@/entities/backtest/conditionTypes";

// 모델은 lib/backtest/conditionTypes 에 있다(순환 방지). 기존 import 경로 호환을 위해 재수출.
export type { Condition, OpId };

const OPS: { id: OpId; label: string; word: string }[] = [
  { id: "gte", label: "≥", word: "이상" },
  { id: "lte", label: "≤", word: "이하" },
  { id: "eq", label: "=", word: "와 같을 때" },
  { id: "between", label: "범위", word: "사이" },
  { id: "cross_above", label: "↑돌파", word: "상향 돌파" },
  { id: "cross_below", label: "↓돌파", word: "하향 돌파" },
];
const opSym = (id: OpId) => OPS.find((o) => o.id === id)!.label;
const opWord = (id: OpId) => OPS.find((o) => o.id === id)!.word;

const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";
const uid = () => Math.random().toString(36).slice(2, 9);

export default function ConditionFormulaEditor({ tone = "neutral", conditions, onChange, logicExpr, onLogicChange, logicDefaultLabel = "모두 AND", sideKey }: {
  tone?: Tone; conditions: Condition[]; onChange: (c: Condition[]) => void;
  /** 논리 조건식 (젠포트 논리 레이어) — 전달하면 조건 리스트 아래 입력·검증 UI 노출 */
  logicExpr?: string; onLogicChange?: (v: string) => void; logicDefaultLabel?: string;
  /** 조건식 세트 저장/불러오기 활성 (매수/매도 조건에서만 — 마켓타이밍 제외) */
  sideKey?: "buy" | "sell";
}) {
  // 좌변 입력 방법 + 비교 연산자·값 (두 모드 공용)
  const [inputMode, setInputMode] = useState<"builder" | "direct">("builder");
  const [formula, setFormula] = useState<FormulaToken[]>([]);
  const [directExpr, setDirectExpr] = useState("");
  const [op, setOp] = useState<OpId>("gte");
  const [rhs, setRhs] = useState("");
  const [rhs2, setRhs2] = useState("");
  const [exprCheck, setExprCheck] = useState<{ ok: boolean; msg: string } | null>(null);
  // 논리식 / 세트 / 자연어
  const [logicCheck, setLogicCheck] = useState<{ ok: boolean; msg: string } | null>(null);
  const [setsOpen, setSetsOpen] = useState(false);
  const [savedSets, setSavedSets] = useState<SavedConditionSet[]>([]);
  const [saveName, setSaveName] = useState("");
  const [nlQuery, setNlQuery] = useState("");
  const [nlBusy, setNlBusy] = useState(false);
  const [nlMsg, setNlMsg] = useState<string | null>(null);
  const accent = TONES[tone];

  // 현재 좌변 산술식 / 라벨 (활성 모드 기준)
  const lhsExpr = (inputMode === "builder" ? buildExpr(formula) : directExpr).trim();
  const lhsLabel = inputMode === "builder" ? buildLabel(formula) : directExpr.trim();
  const canSave = lhsExpr !== "" && rhs !== "" && (op !== "between" || rhs2 !== "");

  const resetDraft = () => { setFormula([]); setDirectExpr(""); setRhs(""); setRhs2(""); setExprCheck(null); };

  const verifyExpr = async () => {
    if (!lhsExpr) { setExprCheck(null); return; }
    try {
      const r = await backtestBridgeApi.validateExpr(lhsExpr);
      if (!r.ok) setExprCheck({ ok: false, msg: r.error ?? "식이 올바르지 않습니다" });
      else setExprCheck({
        ok: true,
        msg: `유효한 식${r.lookback ? ` · 룩백 ${r.lookback}봉` : ""}${r.unknown_tokens?.length ? ` · ⚠ 미지원 토큰(건너뜀): ${r.unknown_tokens.join(", ")}` : ""}`,
      });
    } catch { setExprCheck({ ok: false, msg: "검증 요청 실패 — 백엔드 연결을 확인하세요" }); }
  };

  const save = () => {
    if (!canSave) return;
    onChange([...conditions, {
      id: uid(), factorName: lhsLabel, factorToken: "", functionId: "expr", params: {},
      expr: lhsExpr, label: lhsLabel, direct: true, op, rhs,
      rhs2: op === "between" ? rhs2 : undefined,
    }]);
    resetDraft();
  };
  const remove = (id: string) => onChange(conditions.filter((c) => c.id !== id));
  // 조건 편집 — 직접 입력 칸으로 다시 불러와 수정 후 재저장 (수식·직접·NL 모두 expr 보유)
  const editCond = (c: Condition) => {
    setInputMode("direct");
    setDirectExpr(c.expr || c.factorName);
    setFormula([]);
    setOp(c.op); setRhs(c.rhs); setRhs2(c.rhs2 ?? "");
    setExprCheck(null);
    remove(c.id);
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
        label: (c.expr ?? c.factor_token ?? "").replace(/[{}]/g, ""),
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
        {conditions.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", border: "1px dashed var(--border-strong)", borderRadius: R, padding: "12px 11px", marginBottom: 7, lineHeight: 1.6 }}>
            아직 조건이 없습니다. 오른쪽에서 수식을 만들어 추가하세요.
          </div>
        )}
        {conditions.map((c, i) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, background: accent.bg, border: `1px solid ${accent.accent}`, borderRadius: R, padding: "9px 11px", marginBottom: 7 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, color: accent.text, marginBottom: 2 }}>조건식 {String.fromCharCode(65 + i)}</div>
              <div style={{ fontFamily: "var(--bs-font-mono)", fontSize: 13, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {c.label || c.expr || c.factorName} {opSym(c.op)} {c.rhs}{c.op === "between" ? `~${c.rhs2}` : ""}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
              <button type="button" onClick={() => editCond(c)} aria-label="수정" title="수정"
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", padding: 2 }}><Pencil size={13} /></button>
              <button type="button" onClick={() => remove(c.id)} aria-label="삭제" title="삭제"
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", padding: 2 }}><X size={14} /></button>
            </div>
          </div>
        ))}

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
          <Segmented tone={tone} value={inputMode} onChange={(m) => { setInputMode(m); setExprCheck(null); }}
            options={[{ id: "builder", label: "수식 빌더" }, { id: "direct", label: "직접 입력" }]} />
        </div>

        {inputMode === "builder" ? (
          <div style={{ marginBottom: 12 }}>
            <FormulaBuilder tone={tone} tokens={formula} onChange={(f) => { setFormula(f); setExprCheck(null); }} />
          </div>
        ) : (
          <div style={{ marginBottom: 12 }}>
            <input value={directExpr} spellCheck={false}
              onChange={(e) => { setDirectExpr(e.target.value); setExprCheck(null); }}
              placeholder="예: ({분기영업현금흐름}-{분기순이익}) 또는 {종가}/과거값('최고값({고가},{40일})',{1일})"
              style={{ width: "100%", boxSizing: "border-box", fontFamily: "var(--bs-font-mono)", fontSize: 13, padding: "10px 12px", border: `1px solid ${exprCheck && !exprCheck.ok ? "#dc2626" : "var(--border-strong)"}`, borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 5, lineHeight: 1.6 }}>
              사칙연산(+,−,×,÷)·괄호·{"{팩터}"}·함수 조합 — 기간은 {"{20일}"} 형태 · 우변은 아래 값
            </div>
          </div>
        )}

        {/* 좌변 검증 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 13 }}>
          <button type="button" onClick={verifyExpr} disabled={!lhsExpr}
            style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: R, padding: "5px 9px", cursor: lhsExpr ? "pointer" : "not-allowed", opacity: lhsExpr ? 1 : 0.5, flexShrink: 0 }}>
            <ShieldCheck size={13} /> 식 검증
          </button>
          {exprCheck && <span style={{ fontSize: 11, color: exprCheck.ok ? "#16a34a" : "#dc2626" }}>{exprCheck.msg}</span>}
        </div>

        {/* 연산자 + 값 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 13, flexWrap: "wrap" }}>
          <Segmented tone={tone} value={op} onChange={setOp} options={OPS.map((o) => ({ id: o.id, label: o.label }))} />
          <input type="number" className="bs-numbox" value={rhs} onChange={(e) => setRhs(e.target.value)} placeholder="값"
            style={{ width: 104, fontFamily: "var(--bs-font-mono)", fontSize: 15, textAlign: "center", padding: "9px 8px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
          {(op === "cross_above" || op === "cross_below") && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              기준선을 {op === "cross_above" ? "상향" : "하향"} 돌파한 봉만 (골든크로스: 좌변=두 MA의 차이, 값=0)
            </span>
          )}
          {op === "between" && (
            <>
              <span style={{ color: "var(--text-secondary)" }}>~</span>
              <input type="number" className="bs-numbox" value={rhs2} onChange={(e) => setRhs2(e.target.value)} placeholder="상한"
                style={{ width: 104, fontFamily: "var(--bs-font-mono)", fontSize: 15, textAlign: "center", padding: "9px 8px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
            </>
          )}
        </div>

        {/* NL 한 줄 */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8, background: "var(--bg-card)", border: `1px solid ${accent.accent}`, borderRadius: R, padding: "11px 12px", marginBottom: 14 }}>
          <ArrowRight size={15} style={{ color: accent.text, marginTop: 2, flexShrink: 0 }} />
          <span style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            {lhsExpr && rhs !== ""
              ? <>이 조건 — <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{lhsLabel} {opSym(op)} {rhs}{op === "between" ? ` ~ ${rhs2 || "?"}` : ""}</span></>
              : "팩터로 수식을 만들고 값을 입력하면 조건이 완성돼요."}
          </span>
        </div>

        <button type="button" onClick={save} disabled={!canSave}
          style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 5, fontSize: 13, color: "#fff", background: canSave ? accent.accent : "var(--border-strong)", border: "none", borderRadius: R, padding: "10px 0", cursor: canSave ? "pointer" : "not-allowed" }}>
          <Check size={14} /> 조건식 저장
        </button>

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
    </div>
  );
}
