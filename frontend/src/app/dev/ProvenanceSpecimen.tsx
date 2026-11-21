"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 출처 표지 · 갱신 시각 견본 (U2-a · 설계 문서 §5.1 · ADR 007 §5.4) — 카탈로그 `/dev/ui` 의 '출처 표지 · 갱신 시각' 절.
//
// 제품 화면이 쓸 부품(`shared/ui/provenance`)을 밀도 셋 · 두 테마에서 눈과 시험(`e2e/provenance.spec.ts`)으로 보는 자리다.
//  · 값은 손으로 적었다(받은 때는 이 기기의 09:30:05 로 고정). 스펙의 기대값은 이 값에서 손으로 적었다 — 값을 고치면 스펙도 함께.
//  · 표지 다섯: 합성(종목 찾기 · 스튜디오가 쓸 꼴) · 실데이터(분봉) · 출처 모름(게이트가 꺼진 스튜디오) · 확인 실패(게이트 조회 실패) · 덧붙임.
//  · 갱신 시각 줄 셋: 주기 + 받은 때 · 받기 전 · 주기 없음.
//  · 상자에 `tier` · `density` 를 주면 그 상자에 속성을 단다(토큰 블록의 선택자가 속성만이라 `html` 이 아니어도 걸린다).
// ═══════════════════════════════════════════════════════════════════════════════
import { type Density, type Tier } from "@/shared/ui/density";
import { Freshness, ProvenanceBadge } from "@/shared/ui/provenance";
import { densityLabel } from "./DensitySpecimen";

/** 이 기기의 2026-11-21 09:30:05 — 시간대와 무관하게 이 기기 시각의 칸으로 만든 값(스펙이 '09:30:05' 를 기대한다). */
const AT = new Date(2026, 10, 21, 9, 30, 5).getTime();

export function ProvenanceSpecimen({ tier, density, dark }: { tier?: Tier; density?: Density; dark?: boolean }) {
  return (
    <div className={`devui-pv-box${dark ? " dark" : ""}`} data-tier={tier} data-density={density}>
      <p className="devui-pv-cap">{densityLabel(tier ?? null, density ?? null)}{dark ? " · 다크" : ""}</p>
      <ProvenanceBadge
        label="합성 견본의 출처"
        source={{ kind: "synthetic", label: "합성 데이터" }}
        times={[
          { label: "계산 시각", value: "2026-11-21 09:30:05(서버 시계 · 시간대 표기 없음)" },
          { label: "자료 기준 시각", unknown: "응답에 없습니다" },
        ]}
        pit={{ label: "시점 정합: 확인 안 됨", tone: "unknown" }}
      />
      <ProvenanceBadge label="실데이터 견본의 출처" source={{ kind: "known", label: "실제 분봉" }} times={[{ label: "관측 끝", value: "2026-11-20" }]} />
      <ProvenanceBadge label="출처를 모르는 견본" source={{ kind: "unknown", reason: "응답에 계열별 출처가 없습니다" }} />
      <ProvenanceBadge label="확인에 실패한 견본" source={{ kind: "unknown", reason: "출처 확인 실패" }} />
      <ProvenanceBadge
        label="덧붙임이 있는 견본"
        times={[{ label: "계산 시각", value: "2026-11-21 09:30:05(서버 시계 · 시간대 표기 없음)" }]}
        notes={[{ label: "일부만 평가(서버의 평가 상한)" }]}
      />
      <Freshness updatedAt={AT} intervalMs={5000} />
      <Freshness updatedAt={0} intervalMs={10_000} />
      <Freshness updatedAt={AT} />
    </div>
  );
}
