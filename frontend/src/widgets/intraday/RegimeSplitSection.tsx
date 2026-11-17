"use client";
/**
 * 분봉 결과의 '시장 국면별로 나눠 보기' 절 — 시행의 일별 손익을 국면별로(K2a) + 하루 유형 비율(K2b) (설계 2026-11-17 §3 · 구현 계획 §7.3)
 * ==========================================================================
 * 부품은 `features/intraday-regime-split` 에 있다 — 캔버스 '분봉 결과 조회' 판과 같은 부품 · 같은 문(K2c). 여기는 화면의 자리와 머리 단계,
 * 시행을 기록하지 못한 실행의 문장만 정한다. 다른 실행이면 부르는 쪽(`IntradayResult`)이 `key` 로 새로 그린다.
 */
import { RegimeSplitBlock } from "@/features/intraday-regime-split";

const NO_TRIAL = "이 실행은 시행으로 기록되지 않아 국면별로 나눌 수 없습니다.";

export function RegimeSplitSection({ trialKey }: { trialKey: string | null | undefined }) {
  return <RegimeSplitBlock trialKey={trialKey} level={2} missing={NO_TRIAL} />;
}
