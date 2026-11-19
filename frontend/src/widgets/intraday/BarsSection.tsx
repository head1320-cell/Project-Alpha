"use client";
/**
 * 분봉 결과의 '봉과 체결' 절 — 그 시행의 하루를 시행 설정으로 다시 계산한 봉과 체결 (G4 · 구현 계획 §5)
 * ==========================================================================
 * 부품은 `features/intraday-trial-day` 에 있다. 여기는 화면의 자리와 머리, 시행을 기록하지 못한 실행의 문장만 정한다.
 * 다른 실행이면 부르는 쪽(`IntradayResult`)이 `key` 로 새로 그린다.
 */
import { TrialDayBlock } from "@/features/intraday-trial-day";
import { Section } from "@/shared/ui/tx";

const NO_TRIAL = "이 실행은 시행으로 기록되지 않아 하루를 다시 그릴 수 없습니다.";

export function BarsSection({ trialKey }: { trialKey: string | null | undefined }) {
  return (
    <Section title="봉과 체결" sub="시행의 설정으로 고른 하루를 다시 계산해 시뮬레이터가 본 1분봉과 그 체결을 함께 그립니다. 다시 계산은 시행으로 세지 않습니다.">
      <TrialDayBlock trialKey={trialKey} missing={NO_TRIAL} />
    </Section>
  );
}
