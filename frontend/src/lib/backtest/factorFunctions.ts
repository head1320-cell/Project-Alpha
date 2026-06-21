// 대상 경로: frontend/src/lib/backtest/factorFunctions.ts
//
// 젠포트 백테스터 조건식의 "함수" 카탈로그 (trading.js 의 factorFunctionList 재구성).
// 팩터를 감싸는 18개 함수. 각 함수는 입력 파라미터(기간 N / 비교값 V / 정렬 dir)와
// 조건식 미리보기 템플릿을 가진다. 템플릿 토큰: {f}=팩터, {n}=기간, {v}=값, {dir}=정렬.

export type FnParamKind = "period" | "value" | "direction";

export interface FnParam {
  kind: FnParamKind;
  label: string;
  default: string; // direction 의 기본값은 "DESC"
}

export interface FactorFunction {
  id: string;
  name: string;
  group: "common" | "all"; // 자주 쓰는 함수 / 전체
  desc: string;
  params: FnParam[];
  /** 조건식 미리보기 템플릿. {f}{n}{v}{dir} 치환 */
  preview: string;
  /** 사람이 읽는 한 줄 설명 템플릿(선택). 없으면 desc 사용 */
  sentence?: string;
}

const N = (label = "기간(일)", def = "20"): FnParam => ({ kind: "period", label, default: def });
const V = (label = "비교값", def = "0"): FnParam => ({ kind: "value", label, default: def });
const DIR: FnParam = { kind: "direction", label: "정렬", default: "DESC" };

export const FACTOR_FUNCTIONS: FactorFunction[] = [
  { id: "base", name: "기본", group: "common", desc: "입력한 팩터를 그대로 사용합니다.", params: [], preview: "{f}", sentence: "{f}" },
  { id: "past", name: "과거값", group: "common", desc: "N일 이전의 팩터 값을 사용합니다.", params: [N("며칠 전", "1")], preview: "과거값({f}, {n})", sentence: "{n}일 전 {f}" },
  { id: "ma", name: "이동평균", group: "common", desc: "특정 기간 동안의 팩터값 평균입니다.", params: [N()], preview: "이동평균({f}, {n})", sentence: "{n}일 {f} 평균" },
  { id: "ratio", name: "비율", group: "common", desc: "팩터에 속한 종목에 0~100 비율을 부여합니다.", params: [DIR], preview: "비율({f}, {dir})", sentence: "{f} 비율(0~100)" },
  { id: "rank", name: "순위", group: "common", desc: "팩터에 속한 종목들에 등수를 부여합니다.", params: [DIR], preview: "순위({f}, {dir})", sentence: "{f} 순위" },
  { id: "max", name: "최고값", group: "common", desc: "N일 이내 팩터의 최고값입니다.", params: [N()], preview: "최고값({f}, {n})", sentence: "{n}일 내 {f} 최고값" },
  { id: "min", name: "최저값", group: "common", desc: "N일 이내 팩터의 최저값입니다.", params: [N()], preview: "최저값({f}, {n})", sentence: "{n}일 내 {f} 최저값" },
  { id: "delta", name: "변화량_기간", group: "common", desc: "N일 전 대비 변화량입니다.", params: [N("며칠 전", "1")], preview: "변화량_기간({f}, {n})", sentence: "{n}일 전 대비 {f} 변화량" },
  { id: "pct", name: "변화율_기간", group: "common", desc: "N일 전 대비 변화율(%)입니다.", params: [N("며칠 전", "1")], preview: "변화율_기간({f}, {n})", sentence: "{n}일 전 대비 {f} 변화율" },
  { id: "abs", name: "절대값", group: "all", desc: "팩터값에 절대값을 취합니다.", params: [], preview: "절대값({f})", sentence: "|{f}|" },
  { id: "sum", name: "기간총합", group: "all", desc: "특정 기간 동안 팩터값의 합입니다.", params: [N()], preview: "기간총합({f}, {n})", sentence: "{n}일 {f} 합" },
  { id: "cmp", name: "비교", group: "all", desc: "팩터값과 입력값을 비교해 1, 0, -1을 부여합니다.", params: [V()], preview: "비교({f}, {v})", sentence: "{f} vs {v} 비교" },
  { id: "gt", name: "큰값", group: "all", desc: "팩터값과 입력값 중 더 큰 값을 사용합니다.", params: [V()], preview: "큰값({f}, {v})", sentence: "max({f}, {v})" },
  { id: "lt", name: "작은값", group: "all", desc: "팩터값과 입력값 중 더 작은 값을 사용합니다.", params: [V()], preview: "작은값({f}, {v})", sentence: "min({f}, {v})" },
  { id: "pctf", name: "변화율_팩터", group: "all", desc: "두 팩터 간 % 차이입니다 — ((F1−F2)/|F2|)×100. 예: 변화율_팩터({당기순이익}, 과거값({당기순이익},1년)) = 전년 대비 성장률.", params: [], preview: "변화율_팩터({f}, …)", sentence: "{f} 대비 두 번째 팩터 변화율" },
  { id: "cntgt", name: "큰개수", group: "all", desc: "N일 이내 팩터값이 입력값보다 컸던 날을 셉니다.", params: [N(), V()], preview: "큰개수({f}, {n}, {v})", sentence: "{n}일 중 {f}>{v} 일수" },
  { id: "cntlt", name: "작은개수", group: "all", desc: "N일 이내 팩터값이 입력값보다 작았던 날을 셉니다.", params: [N(), V()], preview: "작은개수({f}, {n}, {v})", sentence: "{n}일 중 {f}<{v} 일수" },
  { id: "ams", name: "평균모멘텀스코어", group: "all", desc: "최근 팩터가 1~N일 동안의 팩터보다 컸던 비율(%)입니다.", params: [N()], preview: "평균모멘텀스코어({f}, {n})", sentence: "{f} 평균모멘텀스코어({n})" },
  { id: "std", name: "표준편차", group: "all", desc: "특정 기간 동안 팩터값의 표준편차입니다.", params: [N()], preview: "표준편차({f}, {n})", sentence: "{n}일 {f} 표준편차" },
];

export const FUNCTIONS_BY_ID: Record<string, FactorFunction> = Object.fromEntries(
  FACTOR_FUNCTIONS.map((f) => [f.id, f]),
);

/** 내부 지표(중첩)로 쓸 수 있는 함수 — 순위/비율의 랭킹 대상 파생용 (횡단면·두팩터 전용 제외) */
export const INNER_FUNCTIONS: FactorFunction[] = FACTOR_FUNCTIONS.filter(
  (f) => !["base", "rank", "ratio", "pctf"].includes(f.id),
);

/** 템플릿({f}{n}{v}{dir})을 실제 값으로 치환 */
export function fillTemplate(
  tpl: string,
  factor: string,
  params: Record<string, string>,
): string {
  return tpl
    .replace(/\{f\}/g, factor)
    .replace(/\{n\}/g, params.n ?? "N")
    .replace(/\{v\}/g, params.v ?? "값")
    .replace(/\{dir\}/g, params.dir === "ASC" ? "오름차순" : "내림차순");
}

// ─────────────────────────────────────────────────────────────────────────────
// 백엔드(factor_expr.py) valid 산술식 렌더러 — 수식 빌더(FormulaBuilder)가 사용.
//   ★ 기간 인자는 반드시 {N일} 형태. 백엔드는 평범한 20을 "식 인자"로 해석해 거부한다.
//     (이동평균({종가}, 20) → 인자 2개 오류 / 이동평균({종가}, {20일}) → 정상)
// ─────────────────────────────────────────────────────────────────────────────

const dirToken = (dir?: string) => (dir === "ASC" ? "{오름차순}" : "{내림차순}");

/** 함수 1개를 백엔드 valid 형식으로 적용. 예: renderFn("ma","{종가}",{n:"20"}) → "이동평균({종가}, {20일})" */
export function renderFn(
  fnId: string,
  inner: string,
  params: Record<string, string>,
): string {
  const fn = FUNCTIONS_BY_ID[fnId];
  if (!fn || fnId === "base") return inner;
  // 큰개수/작은개수(기간+임계값)의 값은 {0} 처럼 브레이스(=인자), 비교/큰값/작은값의 값은 bare(=피연산자 식).
  const valueIsParam = fn.params.some((p) => p.kind === "period");
  const args: string[] = [inner];
  for (const p of fn.params) {
    if (p.kind === "period") args.push(`{${params.n ?? p.default}일}`);
    else if (p.kind === "value") args.push(valueIsParam ? `{${params.v ?? p.default}}` : String(params.v ?? p.default));
    else if (p.kind === "direction") args.push(dirToken(params.dir));
  }
  return `${fn.name}(${args.join(", ")})`;
}

/** 팩터+함수 1개 항의 명세 — FactorPickerModal 의 FactorPick 과 호환되는 부분집합 */
export interface TermSpec {
  factorToken: string;
  factorName?: string;
  functionId: string;
  params?: Record<string, string>;
  innerFunctionId?: string;
  innerParams?: Record<string, string>;
  factorToken2?: string;
  inner2FunctionId?: string;
  inner2Params?: Record<string, string>;
}

/** 팩터+함수(+중첩/두번째 팩터) 1개 항을 백엔드 valid 산술식으로 렌더링 */
export function renderTermExpr(p: TermSpec): string {
  const tk = p.factorToken || `{${p.factorName ?? ""}}`;
  // 중첩(순위/비율의 랭킹 대상): 내부 함수를 먼저 적용
  let base = tk;
  if (p.innerFunctionId && p.innerFunctionId !== "base") {
    base = renderFn(p.innerFunctionId, tk, p.innerParams ?? {});
  }
  // 두 팩터 함수(비교/큰값/작은값/변화율_팩터): 두 번째 피연산자는 식
  if (p.factorToken2) {
    let op2 = p.factorToken2;
    if (p.inner2FunctionId && p.inner2FunctionId !== "base") {
      op2 = renderFn(p.inner2FunctionId, p.factorToken2, p.inner2Params ?? {});
    }
    const fn = FUNCTIONS_BY_ID[p.functionId];
    return `${fn?.name ?? p.functionId}(${base}, ${op2})`;
  }
  return renderFn(p.functionId, base, p.params ?? {});
}

/** 사람이 읽는 항 라벨 — 중괄호 제거 (예: 이동평균(종가, 20일)) */
export function termLabel(p: TermSpec): string {
  return renderTermExpr(p).replace(/[{}]/g, "");
}
