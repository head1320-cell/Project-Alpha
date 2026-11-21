/**
 * 예전 화면(마법사) → 캔버스 (BL4)
 * ==========================================================================
 * 마법사는 지웠다(대응표 `docs/specs/2026-09-27-bl4-wizard-contract-map.md`). 옛 주소 `/allocation/<화면>` 은
 * `next.config.js` 의 redirects 가 `/allocation?from=<화면>` 으로 보내고, 캔버스는 이 표로
 *  ① "예전 ‹화면› 은 이제 여기서 해요" 한 줄 ② 그 일을 하는 노드로 팔레트 검색 ③ 맞는 템플릿이 있으면 여는 버튼 을 보인다.
 * 팔레트 검색도 이 표의 이름(`STRESS`·`06`·`Stress`)으로 노드를 찾는다 — 예전 이름으로 찾는 사람이 길을 잃지 않게.
 * ★데이터만 둔다★ 노드 종류가 서버 카탈로그에 실제로 있는지는 E2E 가 카탈로그와 대조한다.
 */
export type LegacyScreenKey =
  | "overview" | "macro" | "construct" | "alphalab" | "thesis" | "timing"
  | "optimize" | "stress" | "explain" | "execution" | "journal" | "wizard";

export interface LegacyScreen {
  /** 배너에 쓰는 이름. */
  title: string;
  /** 팔레트 검색 별칭 — 예전 번호·영문 라벨·제목. */
  aliases: readonly string[];
  /** 그 일을 하는 노드 종류. */
  nodes: readonly string[];
  /** 맞는 템플릿(`TEMPLATES[].key`) — 없으면 검색만. */
  template?: string;
  /** 노드가 아니라 서랍이 그 일을 하는 경우. */
  drawer?: "execution" | "records" | "alphas";
}

export const LEGACY_SCREENS: Record<LegacyScreenKey, LegacyScreen> = {
  wizard: { title: "목표 선택", aliases: ["목표 선택", "WIZARD", "GATE"], nodes: [], template: "core" },
  overview: { title: "요약(OVERVIEW)", aliases: ["00", "OVERVIEW", "Overview"], nodes: [] },
  macro: { title: "매크로 국면(MACRO PHASE)", aliases: ["0M", "MACRO PHASE", "Macro Phase"], nodes: ["regime", "regime_ensemble", "regime_explain"], template: "timing" },
  construct: { title: "자산 구성(CONSTRUCT)", aliases: ["01", "CONSTRUCT", "Construct"],
               nodes: ["universe", "returns", "current_weights", "screener", "factor_scores", "scores_to_weights", "sleeve_combine"], template: "core" },
  alphalab: { title: "알파 랩(ALPHA LAB)", aliases: ["02", "ALPHA LAB", "Alpha Lab"], nodes: ["alpha_score", "alpha_validate", "alpha_portfolio"], drawer: "alphas" },
  thesis: { title: "테제(THESIS)", aliases: ["03", "THESIS", "Thesis"], nodes: ["views", "company_views", "estimate"] },
  timing: { title: "타이밍(TIMING)", aliases: ["04", "TIMING", "Timing"], nodes: ["timing_signal", "exposure_overlay", "timing_simulation", "scenario_three_way"], template: "timing" },
  optimize: { title: "최적화(OPTIMIZE)", aliases: ["05", "OPTIMIZE", "Optimize"], nodes: ["optimizer", "risk", "neutralize", "backtest", "frontier"], template: "core" },
  stress: { title: "충격 점검(STRESS)", aliases: ["06", "STRESS", "Stress"], nodes: ["scenario_stress", "custom_scenario", "corr_stress", "sensitivity", "factor_xray", "current_weights"], template: "stress" },
  explain: { title: "귀인(ATTRIBUTION)", aliases: ["07", "ATTRIBUTION", "Attribution", "EXPLAIN"], nodes: ["attribution_review"] },
  execution: { title: "실행 준비(EXECUTION)", aliases: ["08", "EXECUTION", "Execution"], nodes: ["order_preview", "target_version", "rebalance_decision"], template: "rebalance", drawer: "execution" },
  journal: { title: "저널(JOURNAL)", aliases: ["09", "JOURNAL", "Journal"], nodes: ["decision_journal"], drawer: "records" },
};

export const isLegacyScreenKey = (k: string | null | undefined): k is LegacyScreenKey =>
  !!k && Object.prototype.hasOwnProperty.call(LEGACY_SCREENS, k);

/** 노드 종류 → 그 일을 하던 예전 화면들(팔레트 검색·툴팁용). */
export function legacyScreensOf(kind: string): LegacyScreen[] {
  return Object.values(LEGACY_SCREENS).filter((s) => s.nodes.includes(kind));
}
