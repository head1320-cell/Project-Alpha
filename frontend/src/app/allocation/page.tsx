"use client";

import PageHeader from "@/components/layout/PageHeader";
import AllocationStudio from "@/components/allocation/AllocationStudio";

export default function AllocationPage() {
  return (
    <div className="tpage-fade">
      <PageHeader
        eyebrow="PORTFOLIO CONSTRUCTION"
        index="06 / 06"
        title="Allocation Studio"
        intro="자산을 고르고 테제(뷰)에 신뢰도를 부여하면, Black-Litterman·리스크 패리티 등 5개 옵티마이저가 효율적 프론티어 위에서 배분을 제안합니다. 팩터 노출·리스크 기여·시나리오 스트레스까지 한 화면에서 — Two Sigma Venn 벤치마킹."
        status="ENGINE: BL · MVO · RP · HRP"
      />
      <AllocationStudio />
    </div>
  );
}
