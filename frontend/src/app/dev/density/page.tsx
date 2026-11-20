"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// /dev/density — 단 · 밀도 장치의 개발 견본 경로 (ADR 007 §7 · U0)
//
// 경로 표(`shared/ui/density` 의 `TIER_ROUTES`)에 든 ★단 하나의 화면★이다 — 제품 화면이 아니다.
// 첫 그림 전 조각이 `html` 에 속성을 달고, 셸의 맞춤 훅이 같은 답을 유지하며, 다른 화면으로 가면 떼는 것을
// 실제 브라우저에서 돌려 보는 자리다(`e2e/density.spec.ts`). 아래 상자에는 속성이 없다 — 값은 `html` 에서 내려온다.
// 메뉴에 걸지 않은 내부 경로다(`/dev/ui` 와 같다). 네트워크 호출 0.
// ═══════════════════════════════════════════════════════════════════════════════

import { useEffect, useState } from "react";
import { DensitySpecimen, densityLabel } from "../DensitySpecimen";
import type { Density, Tier } from "@/shared/ui/density";

export default function DensityDevPage() {
  // 지금 `html` 에 걸린 값을 글자로 보인다. 수화 전에는 '확인 중'(data-ready="0") — 시험이 수화 여부를 이것으로 가른다.
  const [state, setState] = useState<{ tier: Tier | null; density: Density | null } | null>(null);
  useEffect(() => {
    const h = document.documentElement;
    const read = () => setState({ tier: h.getAttribute("data-tier") as Tier | null, density: h.getAttribute("data-density") as Density | null });
    read();
    const mo = new MutationObserver(read);
    mo.observe(h, { attributes: true, attributeFilter: ["data-tier", "data-density"] });
    return () => mo.disconnect();
  }, []);

  return (
    <div className="devui devui-dn-page">
      <header className="devui-head">
        <h1 className="devui-title">단 · 밀도 (개발 견본 경로)</h1>
        <p className="devui-sub">
          이 화면만 경로 표에 있습니다(작업 단). 밀도는 이 브라우저의 저장값 <code>alpha_density</code> 를 따르고, 없으면 단의 기본값입니다.
          손가락으로 누르는 화면에서는 늘 넉넉입니다. 제품 화면에는 아직 달지 않았습니다.
        </p>
        <p className="devui-sub">
          지금 걸린 값: <strong className="devui-dn-state" data-ready={state ? "1" : "0"}>{state ? densityLabel(state.tier, state.density) : "확인 중"}</strong>
        </p>
      </header>
      <DensitySpecimen caption="경로가 정한 단과 밀도" />
    </div>
  );
}
