/**
 * 종목 찾기의 내보내기 — 결과 줄마다 ★출처 열★을 붙인다 (U1-e · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`)
 * ==========================================================================
 * 한 줄만 떼어 붙여도 그 줄이 무엇에서 나왔는지가 따라간다(CLAUDE.md §4 '출처는 행 단위로 관측') — 파일 머리의 주석 줄이 아니라 열이다.
 * 머리 줄이 첫 줄이라 엑셀 · pandas 가 그대로 읽는다. 값이 없는 수 칸은 빈칸이다(0 이 아니다 — 도구가 결측으로 읽는다 · `toCsv`).
 *
 * 출처 열의 값은 ★관측한 것만★ 적는다:
 *  · 데이터 출처 — 화면의 합성 표시와 같은 근거(서버 게이트 `GET /macro/connection-status` 의 `mock_allowed`).
 *    응답의 `data_source` 는 쓰지 않는다 — 서버가 첫 종목 하나와 키 유무로 짐작하고, 모르면 "mock" 이라 적는다(관측이 아니다).
 *    게이트가 꺼져 있으면 '합성 아님'까지만 안다 — 실데이터의 등급(E2 ~ E4)은 응답이 말하지 않는다 → '등급 미상'.
 *  · 자료 기준 시각 — 응답에 없다 → `N/A(사유)`. 지어내지 않는다.
 *  · 계산 시각 — 응답의 `timestamp` 를 바꾸지 않고 옮긴다(서버가 그 결과를 계산한 때 · 서버 시계 · 시간대 표기 없음).
 *    같은 요청이 서버의 응답 캐시(한 시간)에 있으면 앞선 계산의 시각이다 — 내려받은 때가 아니다.
 *  · 유니버스 · 조건식 — ★그 결과를 만든 요청★의 값이다(화면에서 지금 고치는 중인 조건이 아니다 — 부르는 쪽이 요청과 결과를 함께 든다).
 *    조건식은 보낸 꼴 그대로 읽는다: 필드는 이름(식별자) · 연산자 · 값. 값이 없으면 `N/A`(0 으로 적지 않는다) · 모르는 연산자 · 모르는 꼴의
 *    조건은 그 사실과 원문(JSON)을 적는다. 유동성 게이트는 거르는 첫 층이라 조건식 끝에 켬 · 끔으로 적는다.
 *
 * React 를 들이지 않는다 — 순수 스펙(`e2e/screener-csv-logic.spec.ts`)이 브라우저 없이 가져온다.
 */
import type { FilterConditionNode, FilterGroupNode } from "@/shared/model/domain";

/** 출처 열의 머리(결과 열 뒤에 붙는다 — 앞 열의 자리는 그대로). */
export const PROVENANCE_HEADER = ["데이터 출처", "자료 기준 시각", "계산 시각(서버 · 시간대 표기 없음)", "유니버스", "조건식"] as const;
export const NO_AS_OF = "N/A(응답에 자료 기준 시각이 없습니다)";

/** 그 결과를 만든 요청 — 부르는 쪽이 결과를 받을 때 함께 든다. */
export interface RunRequest { universe: string; universeLabel: string; ast: FilterGroupNode; gateOn: boolean }
/** 서버 게이트를 읽은 상태(화면의 합성 칩과 같은 것). */
export interface SourceState { error: boolean; mockAllowed: boolean | null | undefined }

export function sourceText(s: SourceState): string {
  if (s.error) return "N/A(출처 확인 실패)";
  if (s.mockAllowed === true) return "합성 시세";
  if (s.mockAllowed === false) return "합성 아님 · 등급 미상";
  return "N/A(출처 확인 전)";
}

export function computedAtText(ts: unknown): string {
  return typeof ts === "string" && ts.trim() !== "" ? ts : "N/A(응답에 계산 시각이 없습니다)";
}

const OP: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
const val = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "N/A");

/** 조건 하나 — 보낸 꼴 그대로. 이 화면이 짓는 꼴(필드 · 기술 지표)만 풀어 읽고, 나머지는 꼴의 이름과 원문을 적는다. */
export function condCsvText(c: FilterConditionNode, label: (id: string) => string): string {
  const kind = c.kind ?? "field";
  if (kind !== "field" && kind !== "technical") return `[${kind}] ${JSON.stringify(c)}`;
  const id = kind === "technical" ? (c.indicator ?? c.field) : c.field;
  const name = label(id);
  const subject = name && name !== id ? `${name}(${id})` : id;
  if (c.rank_mode === "top_pct") return `${subject} 상위 ${val(c.rank_value)}%`;
  if (c.rank_mode === "bottom_pct") return `${subject} 하위 ${val(c.rank_value)}%`;
  if (c.rank_mode === "top_n") return `${subject} 상위 ${val(c.rank_value)}종목`;
  if (c.op === "between") return `${subject} ${val(c.value)} ~ ${val(c.value2)}`;
  const op = c.op ? OP[c.op] : undefined;
  return `${subject} ${op ?? `[연산자 ${c.op ?? "없음"}]`} ${val(c.value)}`;
}

/** 묶음 — 그리고(and) · 또는(or). 안쪽 묶음은 괄호로. 아무 조건도 없으면 '조건 없음'. */
export function astCsvText(g: FilterGroupNode, label: (id: string) => string, top = true): string {
  const parts = [...g.conditions.map((c) => condCsvText(c, label)), ...g.groups.map((sub) => astCsvText(sub, label, false))];
  if (!parts.length) return top ? "조건 없음" : "(조건 없음)";
  const body = parts.join(g.logic === "OR" ? " or " : " and ");
  return top || parts.length === 1 ? body : `(${body})`;
}

/** 줄마다 붙는 출처 칸 다섯(머리 `PROVENANCE_HEADER` 의 차례). */
export function provenanceCells(p: { source: SourceState; timestamp: unknown; capped: boolean; req: RunRequest; label: (id: string) => string }): string[] {
  return [
    sourceText(p.source),
    NO_AS_OF,
    computedAtText(p.timestamp),
    `${p.req.universeLabel}(${p.req.universe})${p.capped ? " · 일부만 평가(서버의 평가 상한)" : ""}`,
    `${astCsvText(p.req.ast, p.label)} · 유동성 게이트 ${p.req.gateOn ? "켬" : "끔"}`,
  ];
}
