"use client";
// 파생상품 계산기(BU7c) — 화면은 `widgets/derivatives` 에 있다. `useSearchParams` 때문에 Suspense 로 감싼다.
import { Suspense } from "react";
import { DerivativesCalc } from "@/widgets/derivatives/DerivativesCalc";

export default function DerivativesPage() {
  return (
    <Suspense fallback={<p className="dv-wait">계산기를 여는 중이에요</p>}>
      <DerivativesCalc />
    </Suspense>
  );
}
