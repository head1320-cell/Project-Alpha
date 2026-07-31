"use client";
// 대상 경로: frontend/src/components/backtest/FormulaBuilder.tsx
//
// 젠포트식 "수식 빌더" — 팩터를 2개 이상 + 사칙연산으로 조합해 조건식 좌변을 만든다.
//   예: 전일종가 − 이동평균(전일종가, 20) > 0
//       = 과거값({종가},{1일}) - 이동평균(과거값({종가},{1일}),{20일})
// 각 항(term)은 FactorPickerModal 로 추가하고, 사이에 연산자·괄호·상수를 끼운다.
// 결과는 백엔드(factor_expr.py)가 그대로 평가하는 산술식 문자열로 직렬화된다.

import { useState } from "react";
import { Plus, X, Delete, Hash } from "lucide-react";
import dynamic from "next/dynamic";
import { type FactorPick } from "@/features/factor-picker/FactorPickerModal";
// ★기본이 '닫힘' 인 창은 첫 로드에 있을 이유가 없다★ 팩터 창이 CatalogueShell 로 옮겨가며
// shadcn/Radix ToggleGroup 을 끌고 오는데, 정적 import 로 두면 그 무게가 이 라우트의 첫
// 로드에 그대로 실린다(실측: +17 kB). ADR 001 은 설명되지 않는 4 kB 증가를 되돌리라고 한다 —
// 되돌리는 대신 **필요할 때 가져온다**. 타입은 값이 아니므로 위 import 는 런타임에 남지 않는다.
const FactorPickerModal = dynamic(
  () => import("@/features/factor-picker/FactorPickerModal"), { ssr: false });
import { renderTermExpr, termLabel } from "@/entities/backtest/factorFunctions";
import { TONES, type Tone } from "@/shared/ui/kit";

export type FormulaToken =
  | { t: "factor"; expr: string; label: string }
  | { t: "op"; v: "+" | "-" | "*" | "/" }
  | { t: "lp" }
  | { t: "rp" }
  | { t: "num"; v: string };

const OP_SYM: Record<"+" | "-" | "*" | "/", string> = { "+": "+", "-": "−", "*": "×", "/": "÷" };

/** 토큰 배열 → 백엔드 valid 산술식 (factor_expr.py 가 평가) */
export function buildExpr(tokens: FormulaToken[]): string {
  return tokens
    .map((tk) =>
      tk.t === "factor" ? tk.expr
        : tk.t === "op" ? tk.v
          : tk.t === "num" ? (tk.v.trim() || "0")
            : tk.t === "lp" ? "(" : ")")
    .join(" ");
}

/** 토큰 배열 → 사람이 읽는 라벨 (중괄호 없는 친숙한 표기) */
export function buildLabel(tokens: FormulaToken[]): string {
  return tokens
    .map((tk) =>
      tk.t === "factor" ? tk.label
        : tk.t === "op" ? OP_SYM[tk.v]
          : tk.t === "num" ? (tk.v.trim() || "0")
            : tk.t === "lp" ? "(" : ")")
    .join(" ");
}

const R = "var(--bs-border-radius)";

export default function FormulaBuilder({ tone = "neutral", tokens, onChange }: {
  tone?: Tone; tokens: FormulaToken[]; onChange: (t: FormulaToken[]) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const accent = TONES[tone];

  const append = (tk: FormulaToken) => onChange([...tokens, tk]);
  const removeAt = (i: number) => onChange(tokens.filter((_, idx) => idx !== i));
  const setNumAt = (i: number, v: string) =>
    onChange(tokens.map((tk, idx) => (idx === i && tk.t === "num" ? { ...tk, v } : tk)));
  const popLast = () => onChange(tokens.slice(0, -1));

  const onPick = (p: FactorPick) => {
    append({ t: "factor", expr: renderTermExpr(p), label: termLabel(p) });
    setPickerOpen(false);
  };

  const opBtn = (v: "+" | "-" | "*" | "/") => (
    <button key={v} type="button" onClick={() => append({ t: "op", v })} title={`연산자 ${OP_SYM[v]}`}
      style={ctrlStyle}>{OP_SYM[v]}</button>
  );

  return (
    <div>
      {/* 수식 칩 행 */}
      <div style={{
        display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, minHeight: 46,
        background: "var(--bg-card)", border: "1px solid var(--border-strong)", borderRadius: R,
        padding: "9px 11px", marginBottom: 9,
      }}>
        {tokens.length === 0 && (
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
            아래에서 팩터·연산자를 더해 수식을 만드세요 — 예: 종가 − 이동평균(종가, 20)
          </span>
        )}
        {tokens.map((tk, i) => {
          if (tk.t === "factor") {
            return (
              // `fb-chip` 은 스타일이 아니라 **E2E 계약**이다 — 팩터 창이 실제로 무엇을
              // 넘겼는지(특히 눈에 잘 안 띄는 중첩) 확인할 수 있는 유일한 지점이 이 칩이다.
              <span key={i} className="fb-chip" style={{
                display: "inline-flex", alignItems: "center", gap: 5, fontFamily: "var(--bs-font-mono)",
                fontSize: 13, color: accent.text, background: accent.bg, border: `1px solid ${accent.accent}`,
                borderRadius: R, padding: "4px 7px", maxWidth: "100%",
              }}>
                <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{tk.label}</span>
                <button type="button" onClick={() => removeAt(i)} aria-label="삭제"
                  style={{ background: "none", border: "none", cursor: "pointer", color: accent.text, display: "flex", flexShrink: 0 }}><X size={12} /></button>
              </span>
            );
          }
          if (tk.t === "op") {
            return (
              <button key={i} type="button" onClick={() => removeAt(i)} title="클릭하면 삭제"
                style={{ fontFamily: "var(--bs-font-mono)", fontSize: 15, fontWeight: 600, color: "var(--text-primary)", background: "var(--bg-section)", border: "1px solid var(--border-strong)", borderRadius: R, padding: "2px 9px", cursor: "pointer" }}>
                {OP_SYM[tk.v]}
              </button>
            );
          }
          if (tk.t === "num") {
            return (
              <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 3, background: "var(--bg-section)", border: "1px solid var(--border-strong)", borderRadius: R, padding: "2px 5px" }}>
                <input type="number" value={tk.v} onChange={(e) => setNumAt(i, e.target.value)} placeholder="0"
                  style={{ width: 48, fontFamily: "var(--bs-font-mono)", fontSize: 13, textAlign: "center", border: "none", outline: "none", background: "transparent", color: "var(--text-primary)" }} />
                <button type="button" onClick={() => removeAt(i)} aria-label="삭제"
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex" }}><X size={11} /></button>
              </span>
            );
          }
          // 괄호
          return (
            <button key={i} type="button" onClick={() => removeAt(i)} title="클릭하면 삭제"
              style={{ fontFamily: "var(--bs-font-mono)", fontSize: 15, fontWeight: 600, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border)", borderRadius: R, padding: "2px 8px", cursor: "pointer" }}>
              {tk.t === "lp" ? "(" : ")"}
            </button>
          );
        })}
      </div>

      {/* 도구 행 */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
        <button type="button" onClick={() => setPickerOpen(true)}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 13, fontWeight: 500, color: "#fff", background: accent.accent, border: "none", borderRadius: R, padding: "7px 12px", cursor: "pointer" }}>
          <Plus size={14} /> 팩터
        </button>
        <span style={{ display: "inline-flex", gap: 4 }}>
          {(["+", "-", "*", "/"] as const).map(opBtn)}
        </span>
        <button type="button" onClick={() => append({ t: "lp" })} title="여는 괄호" style={ctrlStyle}>(</button>
        <button type="button" onClick={() => append({ t: "rp" })} title="닫는 괄호" style={ctrlStyle}>)</button>
        <button type="button" onClick={() => append({ t: "num", v: "0" })} title="상수"
          style={{ ...ctrlStyle, display: "inline-flex", alignItems: "center", gap: 3, width: "auto", padding: "0 9px" }}>
          <Hash size={12} /> 상수
        </button>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={popLast} disabled={tokens.length === 0} title="마지막 지우기"
          style={{ ...ctrlStyle, display: "inline-flex", alignItems: "center", gap: 3, width: "auto", padding: "0 9px", opacity: tokens.length ? 1 : 0.4, cursor: tokens.length ? "pointer" : "not-allowed" }}>
          <Delete size={13} /> 지우기
        </button>
        {tokens.length > 0 && (
          <button type="button" onClick={() => onChange([])} title="전체 지우기"
            style={{ ...ctrlStyle, width: "auto", padding: "0 9px", color: "var(--text-muted)" }}>비우기</button>
        )}
      </div>

      <FactorPickerModal open={pickerOpen} tone={tone} allowNesting onClose={() => setPickerOpen(false)} onInsert={onPick} />
    </div>
  );
}

const ctrlStyle: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 14, fontWeight: 600, color: "var(--text-primary)",
  background: "var(--bg-card)", border: "1px solid var(--border-strong)", borderRadius: R,
  minWidth: 30, height: 30, cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center",
};
