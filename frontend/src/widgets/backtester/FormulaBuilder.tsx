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
import { type Tone } from "@/shared/ui/kit";

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

export default function FormulaBuilder({ tone = "neutral", tokens, onChange }: {
  tone?: Tone; tokens: FormulaToken[]; onChange: (t: FormulaToken[]) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const append = (tk: FormulaToken) => onChange([...tokens, tk]);
  const removeAt = (i: number) => onChange(tokens.filter((_, idx) => idx !== i));
  const setNumAt = (i: number, v: string) =>
    onChange(tokens.map((tk, idx) => (idx === i && tk.t === "num" ? { ...tk, v } : tk)));
  const popLast = () => onChange(tokens.slice(0, -1));

  const onPick = (p: FactorPick) => {
    append({ t: "factor", expr: renderTermExpr(p), label: termLabel(p) });
    setPickerOpen(false);
  };

  return (
    <div className="fb" data-tone={tone}>
      {/* 식 줄 — 눌러서 지운다 */}
      <div className="fb-line" aria-label="만드는 식">
        {tokens.length === 0 && (
          <span className="fb-empty">아래에서 팩터와 연산자를 더해 식을 만들어요. 예: 종가 − 이동평균(종가, 20)</span>
        )}
        {tokens.map((tk, i) => {
          if (tk.t === "factor") {
            return (
              // `fb-chip` 은 스타일이 아니라 **E2E 계약**이다 — 팩터 창이 실제로 무엇을
              // 넘겼는지(특히 눈에 잘 안 띄는 중첩) 확인할 수 있는 유일한 지점이 이 칩이다.
              <span key={i} className="fb-chip">
                <span className="fb-chip-t">{tk.label}</span>
                <button type="button" className="fb-x" onClick={() => removeAt(i)} aria-label={`${tk.label} 빼기`}><X size={12} aria-hidden /></button>
              </span>
            );
          }
          if (tk.t === "op") {
            return (
              <button key={i} type="button" className="fb-tok" onClick={() => removeAt(i)} aria-label={`연산자 ${OP_SYM[tk.v]} 빼기`}>
                {OP_SYM[tk.v]}
              </button>
            );
          }
          if (tk.t === "num") {
            return (
              <span key={i} className="fb-num">
                <input type="number" value={tk.v} onChange={(e) => setNumAt(i, e.target.value)} placeholder="0" aria-label="상수 값" />
                <button type="button" className="fb-x" onClick={() => removeAt(i)} aria-label="상수 빼기"><X size={11} aria-hidden /></button>
              </span>
            );
          }
          // 괄호
          return (
            <button key={i} type="button" className="fb-tok fb-tok--paren" onClick={() => removeAt(i)} aria-label={`${tk.t === "lp" ? "여는" : "닫는"} 괄호 빼기`}>
              {tk.t === "lp" ? "(" : ")"}
            </button>
          );
        })}
      </div>

      {/* 도구 줄 */}
      <div className="fb-tools">
        <button type="button" data-act="factor" className="fb-factor" onClick={() => setPickerOpen(true)}>
          <Plus size={16} aria-hidden /> 팩터
        </button>
        {(["+", "-", "*", "/"] as const).map((v) => (
          <button key={v} type="button" className="fb-ctrl" onClick={() => append({ t: "op", v })} aria-label={`연산자 ${OP_SYM[v]} 더하기`}>{OP_SYM[v]}</button>
        ))}
        <button type="button" className="fb-ctrl" onClick={() => append({ t: "lp" })} aria-label="여는 괄호 더하기">(</button>
        <button type="button" className="fb-ctrl" onClick={() => append({ t: "rp" })} aria-label="닫는 괄호 더하기">)</button>
        <button type="button" className="fb-ctrl fb-ctrl--wide" onClick={() => append({ t: "num", v: "0" })}>
          <Hash size={14} aria-hidden /> 상수
        </button>
        <span className="fb-gap" />
        <button type="button" className="fb-ctrl fb-ctrl--wide" onClick={popLast} disabled={tokens.length === 0}>
          <Delete size={14} aria-hidden /> 마지막 지우기
        </button>
        {tokens.length > 0 && (
          <button type="button" className="fb-ctrl fb-ctrl--wide" onClick={() => onChange([])}>모두 지우기</button>
        )}
      </div>

      <FactorPickerModal open={pickerOpen} tone={tone} allowNesting onClose={() => setPickerOpen(false)} onInsert={onPick} />
    </div>
  );
}
