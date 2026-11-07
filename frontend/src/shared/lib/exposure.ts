/**
 * 노출·집중도 — 순수 수학. 의존성 0 (P3).
 *
 * ★왜 `widgets/allocation/parts.tsx` 에서 꺼냈나★
 * 이 두 함수는 차트가 아니라 도메인 계산인데 parts.tsx 안에 있었다. 그 파일은
 * recharts 를 import 하므로, 숫자 하나 쓰려고 부르면 **차트 라이브러리가 통째로
 * 번들에 끌려온다** — 실측으로 `/dev/ui` 가 131 kB → 254 kB 였다. 같은 이유로
 * A6 이 `TIP_STYLE` 을 `shared/ui/chartStyle` 로 옮겼고(그때 09 저널 +30 kB),
 * 이건 그 선례를 따르는 것이다.
 *
 * parts.tsx 는 기존 소비자를 위해 re-export 한다 — import 경로를 바꾸지 않는다.
 */

/**
 * 집중도 — HHI · 상위3 · 유효종목수.
 *
 * ★`Math.max(w, 0)` 이었다 — 숏이 생기면 거짓말을 했다★
 * 예전 식은 합과 분수를 롱 다리만으로 계산했다. 롱 140 / 숏 −40 인 책을 넣으면
 * 분모가 140 이 되어 **집중도를 1.6배 크게** 보고한다(실측: 3775 vs 올바른 2299).
 * 숏도 포지션이고 위험을 진다.
 *
 * 그래서 롱숏에서는 gross 기준(|w| / Σ|w|)으로 잰다 — 방향과 무관하게 "얼마나
 * 한곳에 걸었나" 를 보는 지표이기 때문이다. `basis` 를 함께 돌려주는 이유는
 * 화면이 **어느 기준으로 잰 숫자인지 말할 수 있어야** 하기 때문이다. 라벨 없이
 * 기준만 바꾸면 같은 자리에 뜻이 다른 숫자가 앉는다.
 *
 * ★롱온리에서는 한 자리도 바뀌지 않는다★ 모든 w ≥ 0 이면 |w|/Σ|w| 와
 * max(w,0)/Σmax(w,0) 은 항등적으로 같다.
 */
export function concentration(weightsPct: number[]): {
  hhi: number; top3: number; neff: number; basis: "net" | "gross";
} {
  const hasShort = weightsPct.some((w) => w < 0);
  const tot = weightsPct.reduce((a, w) => a + Math.abs(w), 0) || 1;
  const frac = weightsPct.map((w) => Math.abs(w) / tot);           // 0~1
  const hhi = frac.reduce((a, f) => a + f * f, 0) * 10000;          // Σw² × 10⁴
  const top3 = [...frac].sort((a, b) => b - a).slice(0, 3).reduce((a, f) => a + f, 0) * 100;
  const neff = hhi > 0 ? 10000 / hhi : 0;
  return { hhi, top3, neff, basis: hasShort ? "gross" : "net" };
}

/**
 * 롱/숏 다리와 gross·net.
 *
 * ★넷 하나로는 포지션 크기를 말할 수 없다★ 롱 100 / 숏 0 과 롱 150 / 숏 50 은
 * 넷이 똑같이 100% 지만 전혀 다른 포트폴리오다. `short` 는 음수 그대로 돌려준다 —
 * 절대값으로 바꾸면 부호를 잃고, 화면이 다시 부호를 붙여야 한다.
 */
export function exposureLegs(weightsPct: number[]): {
  long: number; short: number; gross: number; net: number; hasShort: boolean;
} {
  const long = weightsPct.filter((w) => w > 0).reduce((a, w) => a + w, 0);
  const short = weightsPct.filter((w) => w < 0).reduce((a, w) => a + w, 0);   // 음수
  return { long, short, gross: long - short, net: long + short, hasShort: short < 0 };
}
