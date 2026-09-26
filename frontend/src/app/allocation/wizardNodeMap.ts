/**
 * 마법사 화면 → 캔버스 노드 대응표 (BK W6)
 * ==========================================================================
 * "마법사의 STRESS 에서 하던 일은 캔버스의 어느 노드인가" 에 답한다. 팔레트 검색이 이 표로 화면 이름
 * (`STRESS`·`Stress`·`06`)을 노드로 이어 준다. ★키는 마법사 스테이지 href 전부다★(`Record<StageHref,…>`) —
 * 마법사에 화면이 생기면 여기서 컴파일 에러가 나서 빠뜨릴 수 없다. 값의 노드 종류가 서버 카탈로그에 실제로
 * 있는지는 E2E 가 카탈로그와 대조한다. **마법사를 없애는 표가 아니다**(제거는 별도 승인).
 * app 계층에 두는 이유: 두 위젯(마법사 · 캔버스)을 함께 아는 곳은 app 뿐이다(FSD).
 */
import type { StageHref } from "@/widgets/allocation/AllocationProvider";

export const WIZARD_NODE_MAP: Record<StageHref, readonly string[]> = {
  "/allocation/overview": [],                 // 요약 화면 — 대응 노드 없이 캔버스 전체가 그 자리다
  "/allocation/macro": ["regime"],
  "/allocation/construct": ["universe", "returns", "screener", "factor_scores", "scores_to_weights", "sleeve_combine"],
  "/allocation/alphalab": ["alpha_score"],
  "/allocation/thesis": ["views", "company_views", "estimate"],
  "/allocation/timing": ["timing_signal", "exposure_overlay", "timing_simulation"],
  "/allocation/optimize": ["optimizer", "risk", "neutralize", "backtest"],
  "/allocation/stress": ["scenario_stress", "corr_stress", "sensitivity", "factor_xray"],
  "/allocation/explain": ["attribution_review"],
  "/allocation/execution": ["order_preview", "target_version"],
  "/allocation/journal": ["decision_journal"],
};
