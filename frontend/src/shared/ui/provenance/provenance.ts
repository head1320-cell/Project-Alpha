/**
 * 출처 표지 · 갱신 시각의 순수 규칙 (U2 · 설계 문서 §5.1 · ADR 007 §4)
 * ==========================================================================
 * React 를 들이지 않는다 — 순수 스펙(`e2e/provenance-logic.spec.ts`)이 브라우저 없이 가져온다. 그리는 쪽은 `ProvenanceBadge.tsx` · `Freshness.tsx`.
 *
 * ★뜻을 정하지 않는다★ 출처의 낱말(예: '합성 분봉(E0)' · '실제 분봉' · '합성 시세')과 사실(합성인가 · 언제인가)은 그 열거형을 아는
 * 위젯이 정한다 — shared 는 entities 를 모른다. 여기는 셋만 한다:
 *   1. 축의 차례를 늘 같게 — 출처 → 시각들 → 시점 정합 → 덧붙임. 축을 한 칩에 섞지 않는다(성과의 종류 · 데이터의 실제 여부 · 시점 정합은 다른 사실).
 *   2. 꼴 — 합성은 practice(어떤 밀도에서도 숨기지 않는 칩) · 응답이 말한 출처와 시각은 plain · 모르면 'N/A(사유)'(unknown).
 *   3. ★사유 없는 모름을 만들 수 없게★ — 사유가 비었거나 시각의 값이 비면 그리지 않고 예외를 던진다(명시적으로 실패한다 · 침묵 폴백 금지).
 */
import type { Chip, ChipTone } from "../tx";
import { UNKNOWN_TEXT, clockText } from "../../lib/krFormat";

/** 출처 — 합성(practice) · 응답이 말한 출처(plain) · 모름(사유 필수 · 이름의 기본은 '출처'). */
export type ProvSource =
  | { kind: "synthetic"; label: string }
  | { kind: "known"; label: string }
  | { kind: "unknown"; reason: string; label?: string };

/** 시각 — 값이 있으면 '이름 값', 모르면 '이름 N/A(사유)'. 어느 시계인지는 값에 적는다(예: '(서버 시계 · 시간대 표기 없음)'). */
export type ProvTime = { label: string; value: string } | { label: string; unknown: string };

/** 시점 정합 — 부르는 쪽의 낱말 그대로(예: 백테스트 결과의 '시점 정합: 확인 안 됨'). */
export type ProvPit = { label: string; tone: Extract<ChipTone, "ok" | "assumed" | "unknown"> };

/**
 * 덧붙임 — 결과를 바꾸는 사실 한 줄(예: '일부만 평가(서버의 평가 상한)'). 근거의 종류(ev)는 없다.
 * 기본은 중립(plain) — 출처 표지는 중립 색조이고 파랑(info)은 하락 · 링크에만 남는다(ADR 007 §5.3 · §5.4). 가정이면 assumed.
 */
export type ProvNote = { label: string; tone?: Extract<ChipTone, "plain" | "assumed"> };

export type ProvInput = {
  source?: ProvSource | null;
  times?: ProvTime[];
  pit?: ProvPit | null;
  notes?: ProvNote[];
};

const blank = (s: string | undefined | null) => !s || !s.trim();
const na = (reason: string, what: string) => {
  if (blank(reason)) throw new Error(`출처 표지: '${what}' 의 사유가 비었습니다 — 사유 없는 N/A 는 만들지 않습니다`);
  return `${UNKNOWN_TEXT}(${reason})`;
};

function sourceChip(s: ProvSource): Chip {
  if (s.kind === "synthetic") return { label: s.label, tone: "practice", ev: "source" };
  if (s.kind === "known") return { label: s.label, tone: "plain", ev: "source" };
  const name = s.label ?? "출처";
  return { label: `${name} ${na(s.reason, name)}`, tone: "unknown", ev: "source" };
}

function timeChip(t: ProvTime): Chip {
  if ("value" in t) {
    if (blank(t.value)) throw new Error(`출처 표지: '${t.label}' 의 값이 비었습니다 — 모르면 unknown 과 사유로 넘깁니다`);
    return { label: `${t.label} ${t.value}`, tone: "plain", ev: "asof" };
  }
  return { label: `${t.label} ${na(t.unknown, t.label)}`, tone: "unknown", ev: "asof" };
}

/** 사실 → 칩(축의 차례 고정). 없는 축은 칸을 만들지 않는다 — 빈 입력은 빈 목록. */
export function provChips(p: ProvInput): Chip[] {
  const out: Chip[] = [];
  if (p.source) out.push(sourceChip(p.source));
  for (const t of p.times ?? []) out.push(timeChip(t));
  if (p.pit) out.push({ label: p.pit.label, tone: p.pit.tone, ev: "pit" });
  for (const n of p.notes ?? []) out.push({ label: n.label, tone: n.tone ?? "plain" });
  return out;
}

/** 주기(밀리초) → '5초' · '1.5초'. 양의 유한한 값이 아니면 주기가 없는 것(앞 절을 쓰지 않는다). */
const periodText = (ms: number | null | undefined): string | null => {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0) return null;
  const s = ms / 1000;
  return `${Number.isInteger(s) ? s : Number(s.toFixed(1))}초`;
};

/**
 * 갱신 시각 줄의 글 — 'N초마다 다시 읽습니다 · 마지막 수신 hh:mm:ss'(이 기기 시각). 받기 전이면 'N/A(아직 받은 값이 없습니다)'.
 * `updatedAt` 은 TanStack Query 의 `dataUpdatedAt`(마지막으로 ★성공한★ 응답을 받은 때) — 실패하는 동안에는 그 시각에 멈춘다.
 */
export function freshnessText({ updatedAt, intervalMs }: { updatedAt: number; intervalMs?: number | null }): string {
  const at = clockText(updatedAt);
  const tail = `마지막 수신 ${at ?? `${UNKNOWN_TEXT}(아직 받은 값이 없습니다)`}`;
  const period = periodText(intervalMs);
  return period ? `${period}마다 다시 읽습니다 · ${tail}` : tail;
}
