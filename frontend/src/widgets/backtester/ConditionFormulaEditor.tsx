"use client";
// 대상 경로: frontend/src/components/backtest/ConditionFormulaEditor.tsx
//
// 조건식 설정 에디터. 좌변(LHS)을 만드는 방법은 두 가지:
//   · 수식 빌더 — 팩터를 2개 이상 + 사칙연산으로 조합 (젠포트식, 클릭으로 구성)
//   · 직접 입력 — 자유 산술식을 그대로 타이핑
// 어느 쪽이든 백엔드(factor_expr.py)가 평가하는 산술식(direct)으로 직렬화된다.
// 좌변에 연산자(≥/≤/=/범위)·값을 붙여 조건(Condition)을 만들고 리스트로 관리한다.

import { useState } from "react";
import { X, Check, ShieldCheck, Save, FolderOpen, Sparkles, Pencil } from "lucide-react";
import FormulaBuilder, { buildExpr, buildLabel, type FormulaToken } from "./FormulaBuilder";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import {
  listConditionSets, saveConditionSet, deleteConditionSet, cloneConditions,
  type SavedConditionSet,
} from "@/entities/backtest/conditionSets";
import { Segmented, type Tone } from "@/shared/ui/kit";
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

  // 현재 좌변 산술식 / 라벨 (활성 모드 기준)
  const lhsExpr = (inputMode === "builder" ? buildExpr(formula) : directExpr).trim();
  const lhsLabel = inputMode === "builder" ? buildLabel(formula) : directExpr.trim();
  const canSave = lhsExpr !== "" && rhs !== "" && (op !== "between" || rhs2 !== "");

  const resetDraft = () => { setFormula([]); setDirectExpr(""); setRhs(""); setRhs2(""); setExprCheck(null); };

  const verifyExpr = async () => {
    if (!lhsExpr) { setExprCheck(null); return; }
    try {
      const r = await backtestBridgeApi.validateExpr(lhsExpr);
      if (!r.ok) setExprCheck({ ok: false, msg: r.error ?? "식이 올바르지 않아요" });
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
        : `변환된 조건이 없어요${skip}`);
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
        : { ok: false, msg: r.error ?? "식이 올바르지 않아요" });
    } catch { setLogicCheck({ ok: false, msg: "검증 요청 실패 — 백엔드 연결을 확인하세요" }); }
  };

  const verdict = (c: { ok: boolean; msg: string }) => (
    <span className={`cfe-check${c.ok ? "" : " is-bad"}`} role={c.ok ? "status" : "alert"}>{c.msg}</span>
  );

  return (
    <div className="cfe" data-tone={tone}>

      {/* 왼쪽: 만든 조건 목록 */}
      <div className="cfe-list">
        <div className="cfe-head">
          <span className="cfe-h">조건식</span>
          {sideKey && (
            <button type="button" className="cfe-ghost" aria-expanded={setsOpen} onClick={toggleSets}>
              <FolderOpen size={14} aria-hidden /> 세트 불러오기·저장
            </button>
          )}
        </div>
        {sideKey && setsOpen && (
          <div className="cfe-sets">
            <div className="cfe-row">
              <input value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="세트 이름" aria-label="세트 이름"
                className="bte-input cfe-grow" />
              <button type="button" className="cfe-btn" onClick={handleSaveSet} disabled={conditions.length === 0}>
                <Save size={14} aria-hidden /> 저장
              </button>
            </div>
            {savedSets.length === 0 ? (
              <p className="bte-note">저장한 조건식 세트가 없어요.</p>
            ) : savedSets.map((sv) => (
              <div key={sv.id} className="cfe-row">
                <button type="button" className="cfe-set" onClick={() => handleLoadSet(sv)} aria-label={`${sv.name} 세트 불러오기`}>
                  {sv.name} <span className="bte-sm">조건 {sv.conditions.length}개{sv.logicExpr ? " · 논리식" : ""}</span>
                </button>
                <button type="button" className="bte-icon-btn" aria-label={`${sv.name} 세트 삭제`}
                  onClick={() => { deleteConditionSet(sv.id); refreshSets(); }}><X size={14} aria-hidden /></button>
              </div>
            ))}
          </div>
        )}
        {conditions.length === 0 && (
          <p className="cfe-empty">아직 조건이 없어요. 오른쪽에서 식을 만들어 더해요.</p>
        )}
        {conditions.map((c, i) => (
          <div key={c.id} className="cfe-cond">
            <div className="cfe-cond-main">
              <span className="cfe-cond-k">조건식 {String.fromCharCode(65 + i)}</span>
              <span className="cfe-cond-v">
                {c.label || c.expr || c.factorName} {opSym(c.op)} {c.rhs}{c.op === "between" ? `~${c.rhs2}` : ""}
              </span>
            </div>
            <button type="button" className="bte-icon-btn" onClick={() => editCond(c)} aria-label={`조건식 ${String.fromCharCode(65 + i)} 고치기`}><Pencil size={14} aria-hidden /></button>
            <button type="button" className="bte-icon-btn" onClick={() => remove(c.id)} aria-label={`조건식 ${String.fromCharCode(65 + i)} 빼기`}><X size={16} aria-hidden /></button>
          </div>
        ))}

        {/* 논리 조건식 (젠포트 논리 레이어) — and/or/not + before/any/every */}
        {onLogicChange && conditions.length > 0 && (
          <div className="cfe-logic">
            <span className="cfe-h">조건끼리 묶기</span>
            <input value={logicExpr ?? ""} spellCheck={false} aria-label="조건끼리 묶는 식"
              className={`bte-input bte-input--mono cfe-full${logicCheck && !logicCheck.ok ? " is-bad" : ""}`}
              onChange={(e) => { onLogicChange(e.target.value); setLogicCheck(null); }}
              placeholder={`예: every(A,3) and (B or C) — 비우면 ${logicDefaultLabel}`} />
            <div className="cfe-row">
              <button type="button" className="cfe-ghost" onClick={verifyLogic}><ShieldCheck size={14} aria-hidden /> 식 확인</button>
              {logicCheck && verdict(logicCheck)}
            </div>
            <p className="bte-note">and · or · not(A) · before(A,n) n일 전에 맞음 · any(A,n) n일 안에 한 번이라도 · every(A,n) n일 내내</p>
          </div>
        )}
      </div>

      {/* 오른쪽: 새 조건 만들기(초안) */}
      <div className="cfe-draft">
        <div className="cfe-head">
          <span className="cfe-h">새 조건 만들기</span>
          <Segmented tone={tone} act="cond-mode" value={inputMode} onChange={(m) => { setInputMode(m); setExprCheck(null); }}
            options={[{ id: "builder", label: "수식 빌더" }, { id: "direct", label: "직접 입력" }]} />
        </div>

        {inputMode === "builder" ? (
          <FormulaBuilder tone={tone} tokens={formula} onChange={(f) => { setFormula(f); setExprCheck(null); }} />
        ) : (
          <div className="bte-col">
            <input value={directExpr} spellCheck={false} data-act="cond-expr" aria-label="왼쪽 식"
              className={`bte-input bte-input--mono cfe-full${exprCheck && !exprCheck.ok ? " is-bad" : ""}`}
              onChange={(e) => { setDirectExpr(e.target.value); setExprCheck(null); }}
              placeholder="예: ({분기영업현금흐름}-{분기순이익}) 또는 {종가}/과거값('최고값({고가},{40일})',{1일})" />
            <p className="bte-note">사칙연산(+ − × ÷) · 괄호 · {"{팩터}"} · 함수를 섞어 써요. 기간은 {"{20일}"}처럼, 비교할 값은 아래에 적어요.</p>
          </div>
        )}

        {/* 왼쪽 식 확인 */}
        <div className="cfe-row">
          <button type="button" className="cfe-ghost" onClick={verifyExpr} disabled={!lhsExpr}>
            <ShieldCheck size={14} aria-hidden /> 식 확인
          </button>
          {exprCheck && verdict(exprCheck)}
        </div>

        {/* 비교 + 값 */}
        <div className="cfe-row">
          <Segmented tone={tone} value={op} onChange={setOp} options={OPS.map((o) => ({ id: o.id, label: o.label }))} />
          <input type="number" className="bs-numbox kit-num" data-act="cond-rhs" aria-label="비교할 값" value={rhs} onChange={(e) => setRhs(e.target.value)} placeholder="값" />
          {op === "between" && (
            <>
              <span className="bte-sm">~</span>
              <input type="number" className="bs-numbox kit-num" aria-label="위 끝 값" value={rhs2} onChange={(e) => setRhs2(e.target.value)} placeholder="위 끝" />
            </>
          )}
        </div>
        {(op === "cross_above" || op === "cross_below") && (
          <p className="bte-note">기준선을 {op === "cross_above" ? "위로" : "아래로"} 뚫은 봉만 맞아요. 골든크로스라면 왼쪽 식은 두 이동평균의 차이, 값은 0이에요.</p>
        )}

        {/* 지금 만드는 조건을 한 줄로 */}
        <p className="cfe-preview">
          {lhsExpr && rhs !== ""
            ? <>이 조건 <b>{lhsLabel} {opSym(op)} {rhs}{op === "between" ? ` ~ ${rhs2 || "?"}` : ""}</b></>
            : "팩터로 식을 만들고 값을 넣으면 조건이 완성돼요."}
        </p>

        <button type="button" className="cfe-save" onClick={save} disabled={!canSave} data-act="cond-save">
          <Check size={16} aria-hidden /> 조건식 저장
        </button>

        {/* AI 자연어 변환 (매수 조건 전용 — 젠포트 AI 버튼) */}
        {sideKey === "buy" && (
          <div className="cfe-nl">
            <p className="cfe-h">말로 조건 만들기</p>
            <div className="cfe-row">
              <input value={nlQuery} onChange={(e) => setNlQuery(e.target.value)} aria-label="말로 적은 조건"
                onKeyDown={(e) => { if (e.key === "Enter") runNl(); }} className="bte-input cfe-grow"
                placeholder="예: PER 15 이하이고 ROE 상위 30%" />
              <button type="button" className="cfe-btn" onClick={runNl} disabled={nlBusy || !nlQuery.trim()}>
                <Sparkles size={14} aria-hidden /> {nlBusy ? "바꾸는 중이에요" : "AI 변환"}
              </button>
            </div>
            {nlMsg && <p className="bte-note" role="status">{nlMsg}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
