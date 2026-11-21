"use client";
/**
 * 출처 표지 — 한 꼴의 출처 · 시각 · 시점 정합 칩 (U2 · 설계 문서 §5.1)
 * ==========================================================================
 * 공용 근거 칩(`tx.Chips` — `.tx-chips` · `.tx-chip[data-tone]` · `data-ev`)을 그대로 그리고 감싸는 클래스 `tx-prov` 만 더한다.
 * 낱말과 사실은 부르는 쪽이 정한다(`provenance.ts` 의 머리말). ★합성 칩은 어떤 밀도 · 어떤 배치에서도 숨기지 않는다★ —
 * `e2e/provenance.spec.ts` 가 밀도 셋 × 두 테마에서 건다. 낭독하지 않는다(`aria-live` · `role` 없음 — 목록의 이름만 있다).
 */
import { Chips } from "../tx";
import { provChips, type ProvInput } from "./provenance";

export function ProvenanceBadge({ label, ...input }: ProvInput & { label: string }) {
  return <Chips items={provChips(input)} label={label} className="tx-prov" />;
}
