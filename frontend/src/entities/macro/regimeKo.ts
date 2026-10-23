/**
 * 국면 답 문장의 번역표 — 홈(BU1)과 매크로 분석(BU5a)이 같은 말을 쓰도록 한곳에 둔다.
 * ==========================================================================
 * ★번역만 한다(ADR-003 §2.6)★ 서버 열거값(`recommended_mode`·`regime`)을 한국어로 옮기고 숫자를 서식할 뿐,
 * 임계값으로 새 판단을 만들지 않는다. 모르는 열거값은 서버 글자 그대로 둔다(지어내지 않는다).
 * ★연습용 표시는 서버 게이트로만★ `connection-status.mock_allowed`(= mock_gate) — 대시보드 출처로 추론하지 않는다.
 */
import { pct } from "@/shared/lib/krFormat";
import type { Chip } from "@/shared/ui/tx";

export const MODE_KO: Record<string, string> = { NORMAL: "보통", CAUTIOUS: "조심", DEFENSIVE: "방어" };
export const REGIME_KO: Record<string, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션", Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

/** 국면 이름(한국어) — 모르는 값은 서버 글자 그대로. */
export const regimeName = (regime: string): string => REGIME_KO[regime] ?? regime;

/** 국면 이름 + 확률. 확률이 없으면 "확률 몰라요" — 0% 로 그리지 않는다. */
export function regimeFig(r: { regime: string; regime_probs?: Record<string, number> }): string {
  const name = regimeName(r.regime);
  const p = r.regime_probs?.[r.regime];
  return typeof p === "number" && Number.isFinite(p) ? `${name} ${pct(p, 0)}` : `${name} 확률 몰라요`;
}

/** 기준 시각 칩 글자. 날짜가 아니면 null(칩을 빼고, 지어내지 않는다). */
export function when(ts: string | undefined): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return `기준 ${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export type ConnStatus = { mock_allowed: boolean; bok_configured: boolean };

/** 데이터 출처 칩 — connection-status 응답으로만. 실패는 "확인하지 못했어요"(연습용·실데이터 어느 쪽도 단정하지 않는다). */
export function sourceChip(cs: { data?: ConnStatus | null; isError: boolean; isLoading: boolean }): Chip[] {
  if (cs.isLoading) return [];
  if (cs.isError || !cs.data) return [{ label: "데이터 출처를 확인하지 못했어요", tone: "unknown" }];
  const { mock_allowed, bok_configured } = cs.data;
  if (mock_allowed && !bok_configured) return [{ label: "연습용 데이터", tone: "practice" }];
  if (bok_configured && !mock_allowed) return [{ label: "한국은행 실데이터", tone: "ok" }];
  if (!bok_configured) return [{ label: "한국은행 연결이 없어 일부 지표를 몰라요", tone: "unknown" }];
  return [{ label: "연습용 모드 — 키가 없는 지표는 합성값이에요", tone: "practice" }];
}
