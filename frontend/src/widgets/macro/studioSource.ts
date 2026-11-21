/**
 * 스튜디오 계산의 데이터 출처 — 순수 규칙 (U2-b · 설계 문서 §2.2 C13 · ADR 007 §5.4)
 * ==========================================================================
 * React · 요청을 들이지 않는다(형만 가져온다) — 순수 스펙(`e2e/studio-source-logic.spec.ts`)이 브라우저 없이 가져온다.
 * 게이트를 묻는 훅은 `useStudioSource.ts`.
 *
 * ★합성 표시는 서버 게이트(`GET /macro/connection-status` 의 `mock_allowed` = mock_gate)로만★ — 매크로의 정해진 규칙
 * (`MacroCockpit.tsx` · `MacroAnswer.tsx` 머리말). 서버 0줄(받은 결정 ③).
 *
 *  · 계열을 쓰는 스튜디오에서만 선다 — 서버가 답한 입력 계열(`d.inputs`)이 있을 때. 스튜디오 정보를 못 받았으면 계산 응답이
 *    쓴 기간(`span`)을 말할 때. 뷰 만들기처럼 입력 계열이 없으면 게이트를 묻지도 않는다(데이터에서 나온 수가 없다).
 *  · 게이트 참 → '합성 데이터'. mock 에서 수집기는 값이 없거나 받지 못한 지표를 합성으로 채운다(키가 있어도 —
 *    `macro_collector.py` 의 대체). 어느 계열이 실데이터인지 응답이 말하지 않아 가르지 않고 보수적으로 적는다.
 *  · 게이트 거짓 → '출처 N/A(응답에 계열별 출처가 없습니다)'. ★실데이터라 단정하지 않는다★ — 스튜디오 응답에 계열마다의
 *    출처가 없다(`load_series` 가 버린다 · 서버 쪽은 별도 작업). 매크로 조종석의 '한국은행 실데이터'(`sourceChip`)는
 *    대시보드 계열에 대한 말이라 여기에 쓰지 않는다.
 *  · 게이트를 받는 중 → 표지 없음(받으면 선다 — 지어내지 않는다). 받은 값이 있으면 그것이 관측이다(다시 묻다 실패해도
 *    합성 표시를 거두지 않는다). 한 번도 받지 못하고 실패 → '출처 N/A(합성 여부를 확인하지 못했습니다)'.
 */
import type { MacroConnectionStatus } from "@/entities/macro/api";
import type { StudioDescriptor, StudioResult } from "@/entities/macro/studios";
import type { ProvSource } from "@/shared/ui/provenance";

/** 이 스튜디오의 수가 매크로 계열에서 나오는가 — 서버의 입력 계열이 먼저, 그것을 못 받았으면 계산 응답의 기간. */
export function studioUsesSeries(d: StudioDescriptor | null, run: StudioResult | null | undefined): boolean {
  if (d) return d.inputs.length > 0;
  return !!run && run.available && run.span !== null;
}

/** 게이트의 상태 → 출처. 받은 값이 없고 받는 중이면 null(아직 모른다). */
export function studioSource(gate: { data?: MacroConnectionStatus; isError: boolean }): ProvSource | null {
  if (gate.data) {
    return gate.data.mock_allowed
      ? { kind: "synthetic", label: "합성 데이터" }
      : { kind: "unknown", reason: "응답에 계열별 출처가 없습니다" };
  }
  return gate.isError ? { kind: "unknown", reason: "합성 여부를 확인하지 못했습니다" } : null;
}
