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
  { id: "cntgt", name: "큰개수", group: "all", desc: "N일 이내 팩터값이 입력값보다 컸던 날을 셉니다.", params: [N(), V()], preview: "큰개수({f}, {n}, {v})", sentence: "{n}일 중 {f}>{v} 일수" },
  { id: "cntlt", name: "작은개수", group: "all", desc: "N일 이내 팩터값이 입력값보다 작았던 날을 셉니다.", params: [N(), V()], preview: "작은개수({f}, {n}, {v})", sentence: "{n}일 중 {f}<{v} 일수" },
  { id: "ams", name: "평균모멘텀스코어", group: "all", desc: "최근 팩터가 1~N일 동안의 팩터보다 컸던 비율(%)입니다.", params: [N()], preview: "평균모멘텀스코어({f}, {n})", sentence: "{f} 평균모멘텀스코어({n})" },
  { id: "std", name: "표준편차", group: "all", desc: "특정 기간 동안 팩터값의 표준편차입니다.", params: [N()], preview: "표준편차({f}, {n})", sentence: "{n}일 {f} 표준편차" },
];

export const FUNCTIONS_BY_ID: Record<string, FactorFunction> = Object.fromEntries(
  FACTOR_FUNCTIONS.map((f) => [f.id, f]),
);

/** 내부 지표(중첩)로 쓸 수 있는 함수 — 순위/비율의 랭킹 대상 파생용 (횡단면 함수 제외) */
export const INNER_FUNCTIONS: FactorFunction[] = FACTOR_FUNCTIONS.filter(
  (f) => !["base", "rank", "ratio"].includes(f.id),
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
