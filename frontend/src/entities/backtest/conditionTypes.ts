// 백테스트 조건식 도메인 타입.
// ────────────────────────────────────────────────────────────────────────────
// 이 타입들은 원래 components/backtest/ConditionFormulaEditor.tsx 안에 있었고,
// lib/backtest/{strategy,conditionSets,strategyLibrary}.ts 가 그 컴포넌트에서
// 거꾸로 import 해 순환을 만들고 있었다(하위 계층 → 상위 계층).
// 모델을 하위 계층으로 내려 순환을 끊는다 — 컴포넌트는 여기서 가져다 쓴다.

export type OpId = "gte" | "lte" | "eq" | "between" | "cross_above" | "cross_below";

export interface Condition {
  id: string;
  factorName: string;
  factorToken: string;
  functionId: string;
  params: Record<string, string>;
  expr: string;       // 좌변 산술식 (백엔드 factor_expr 로 평가)
  label?: string;     // 사람이 읽는 라벨(중괄호 없는 표기) — 표시 전용
  direct?: boolean;   // 직접 입력/수식 빌더로 만든 자유 산술식
  op: OpId;
  rhs: string;
  rhs2?: string;      // between 일 때 상한
  // 아래는 레거시(단일 팩터)·NL 변환 호환 필드 — 수식 빌더는 expr 만 사용
  innerFunctionId?: string;
  innerParams?: Record<string, string>;
  factorName2?: string;
  factorToken2?: string;
  inner2FunctionId?: string;
  inner2Params?: Record<string, string>;
}
