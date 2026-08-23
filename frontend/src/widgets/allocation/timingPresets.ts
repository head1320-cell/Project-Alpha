// AAS TIMING 프리셋 상수 — 자산/지표 제안 목록과 마켓 게이트 프리셋.
// (app/allocation/timing/page.tsx에서 분리, 값 불변)

import type { TimingConfig } from "@/widgets/allocation/AllocationProvider";

export type Gate = { id: string; label: string; sub: string; build: (mk: "kr" | "us") => TimingConfig };

export const ASSET_SUGGEST = ["SPY", "QQQ", "IWM", "EFA", "EEM", "AGG", "TLT", "IEF", "SHY", "LQD", "HYG", "GLD", "VNQ", "BIL"];
export const IND_SUGGEST: [string, string][] = [
  ["VIXCLS", "VIX 변동성"], ["DGS10", "미 10년물"], ["BAMLH0A0HYM2", "HY 스프레드"], ["T10Y2Y", "10Y-2Y"],
];

// ── 마켓 지수 게이트 프리셋 — 백테스터 탭 '마켓타이밍'(지수 조건 → 위험 시 방어 전환)을
//    자산배분 맥락으로 일반화. 위험-온이면 현재/전략 포트폴리오 유지, 위험-오프면 방어자산 전환
//    (백테스터 exit_all 대응). 위험자산 추세 프록시는 ETF 매핑(SPY→국내 대형주 ETF)을 사용. ──
export const OFF_DEFENSIVE = ["IEF", "SHY"];
export const MARKET_GATES: Gate[] = [
  {
    id: "trend200", label: "추세 게이트 (200일선)",
    sub: "위험자산이 200일 이동평균 위 → 위험-온 · 아래 → 방어 전환",
    build: (mk) => ({ market: mk,
      canaries: [{ kind: "asset", id: "SPY", signal: "ma_day", lookback: 200, threshold: 0, direction: "above" }],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "none", n: 200, lookback: 12 },
      regimeBlend: false, targetVolPct: null }),
  },
  {
    id: "mom13612", label: "가속 모멘텀 게이트 (13612W)",
    sub: "1·3·6·12M 가속 모멘텀 > 0 → 위험-온 (VAA/DAA식)",
    build: (mk) => ({ market: mk,
      canaries: [{ kind: "asset", id: "SPY", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" }],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "none", n: 200, lookback: 12 },
      regimeBlend: false, targetVolPct: null }),
  },
  {
    id: "dual", label: "이중 확인 게이트",
    sub: "추세(200일) + 가속 모멘텀 둘 다 통과해야 위험-온",
    build: (mk) => ({ market: mk,
      canaries: [
        { kind: "asset", id: "SPY", signal: "ma_day", lookback: 200, threshold: 0, direction: "above" },
        { kind: "asset", id: "EFA", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" },
      ],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "none", n: 200, lookback: 12 },
      regimeBlend: false, targetVolPct: null }),
  },
  {
    id: "trend_overlay", label: "추세 + 자산별 청산",
    sub: "게이트 + 보유자산 개별 추세 이탈분 현금화 (백테스터 exit_all 근사)",
    build: (mk) => ({ market: mk,
      canaries: [{ kind: "asset", id: "SPY", signal: "ma_day", lookback: 200, threshold: 0, direction: "above" }],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "ma_day", n: 200, lookback: 12 },
      regimeBlend: false, targetVolPct: null }),
  },
];

