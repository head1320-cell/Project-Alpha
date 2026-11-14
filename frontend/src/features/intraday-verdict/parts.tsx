"use client";
/**
 * 분봉 판정의 작은 부품 — 출처 칩 · bp 서식 · 시행 횟수 줄. 화면(백테스트 › 분봉 규칙)과 캔버스의 결과 판이 같이 쓴다.
 * ★숫자와 사유는 서버 값이다★ — 여기서는 서식만 입힌다.
 */
import type { Origin, Trial } from "@/entities/intraday";
import { UNKNOWN_TEXT, num } from "@/shared/lib/krFormat";
import type { Chip } from "@/shared/ui/tx";

export const bp1 = (v: number | null | undefined): string => (typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(1)}bp` : UNKNOWN_TEXT);

/** 출처 등급 → 칩. 합성은 연습용 데이터, 미상은 미상, 실제 응답은 사실 표기. */
export const originChip = (o: Origin | null): Chip =>
  o?.grade === "E0" ? { label: "합성 분봉", tone: "practice" } : o?.grade === "E3" ? { label: "실제 분봉", tone: "plain" } : { label: "분봉 출처 미상", tone: "unknown" };

export function TrialLine({ trial }: { trial: Trial | null }) {
  if (!trial) return null;
  if (trial.family_n === null) {
    return <p className="tj-note itd-trial" data-recorded="false" data-server>{trial.message ?? "시행 횟수를 세지 못했습니다."}</p>;
  }
  return (
    <p className="tj-note itd-trial" data-recorded="true">
      이 종목과 기간에서 기록된 시행 {num(trial.family_n)}회 · 전체 {num(trial.user_total)}회
      {trial.new === false ? ` · 같은 설정을 ${num(trial.runs)}번째 실행(새 시행이 아님)` : ""}
      . 설정을 바꿔 다시 볼수록 좋아 보이는 결과가 우연히 나올 여지가 커집니다.
    </p>
  );
}
