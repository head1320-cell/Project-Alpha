"use client";
// pinn-tail 스튜디오 — 얇은 라우트. 계약과 렌더는 StudioPanel 하나가 갖는다
// (다섯 벌로 복사하면 반드시 갈라진다 — M1-M 이 base.py 를 둔 것과 같은 이유).
import { StudioPanel } from "@/widgets/macro/StudioPanel";

export default function Page() {
  return <StudioPanel id="pinn-tail" />;
}
