// 위험 점검 — 화면은 위젯 하나(BU7a). 옛 페이지(칩 하나씩 · 실패 삼킴 · 영어 대문자)는 `widgets/risk/StressCheck.tsx` 로 다시 지었다.
import { StressCheck } from "@/widgets/risk/StressCheck";

export default function RiskPage() {
  return <StressCheck />;
}
