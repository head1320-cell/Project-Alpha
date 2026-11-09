"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// lazyChart — 차트 부품을 ★화면이 뜬 뒤에★ 받는다 (2026-11-08)
// ─────────────────────────────────────────────────────────────────────────────
// 차트 화면(/macro·/insights·/derivatives)의 첫 화면 JS 에서 화면 고유 몫 120~160 kB 중 96 kB(gzip)가 차트 라이브러리(recharts)였다.
// 차트는 데이터가 온 뒤에야 그려지므로 그 코드를 첫 화면에서 빼고 따로 받는다(`e2e/charts-lazy.spec.ts`).
//
// 쓰는 법 — ★경계는 부품 파일 안에 둔다(EvidenceDrawer 와 같은 까닭)★: 차트 본문은 `charts.tsx` 로 옮기고, 원래 파일은 같은 이름을
//   `export const loadCharts = chartModule(() => import("./charts"))` 를 두고, 같은 이름을
//   `export const Payoff = lazyChart(loadCharts, (m) => m.Payoff, { height: 340, label: "만기 손익" })` 로 내보낸다.
//   소비자는 그대로 import 한다. 화면 뿌리는 마운트 때 `loadCharts()` 를 불러 차트 코드가 데이터와 ★동시에★ 오게 한다.
// 받는 동안: 차트와 같은 높이의 자리(`.chart-slot` · role=status · aria-busy) — 화면이 밀리지 않고, 빈칸처럼 보이지도 않는다.
// 못 받으면: 그 자리에서만 실패를 말한다(`.chart-slot--fail` · [새로 고침]). 이 앱에는 `app/error.tsx` 가 없어서, 경계가 없으면
//   차트 하나 때문에 화면 전체가 Next 기본 오류 화면으로 바뀐다.
// ═══════════════════════════════════════════════════════════════════════════════
import { Component, Suspense, lazy, useState, useSyncExternalStore, type ComponentType, type ReactNode } from "react";
import { Notice } from "@/shared/ui/tx";

type Opts<P> = {
  /** 차트가 그려졌을 때의 대략 높이(px) — 받는 동안 그만큼 자리를 잡아 화면이 밀리지 않게. 높이를 prop 으로 받는 차트는 함수로. */
  height: number | ((props: P) => number);
  /** 폭이 정해진 작은 차트(도넛 등)만 — 받는 동안의 자리도 같은 폭으로. */
  width?: number | ((props: P) => number);
  /** 무슨 그림인지(예: "만기 손익") — 자리·실패 문구에 쓴다. */
  label: string;
};

type Box = { height: number; width?: number; label: string };

function Slot({ height, width, label }: Box) {
  return (
    <div className="chart-slot" style={{ minHeight: height, width }} role="status" aria-busy="true">
      {label} 그림을 불러오는 중이에요
    </div>
  );
}

class Boundary extends Component<Box & { children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="chart-slot chart-slot--fail" style={{ width: this.props.width }}>
        <Notice tone="danger" title="차트를 불러오지 못했어요">
          {this.props.label} 그림의 코드를 받지 못했어요(네트워크). 이 화면의 숫자와 설명은 그대로예요.
          <div className="chart-slot-act">
            <button type="button" className="tx-btn tx-btn--sub" onClick={() => window.location.reload()}>새로 고침</button>
          </div>
        </Notice>
      </div>
    );
  }
}

/**
 * 차트 모듈 import 를 감싼다 — 한 번만 받고, 받은 뒤에는 `.loaded` 로 ★바로★ 그린다.
 * 왜: 이미 받아 둔 모듈이라도 React.lazy 는 처음 그릴 때 한 번 멈추고(Suspense) 대체물을 보인다. React 19 는 대체물을 보인 뒤
 * 내용을 드러내는 것을 약 300 ms 늦춘다(깜빡임 방지) — 실측: 파생상품 [계산하기] → 그림 73 → 349 ms. 받아 둔 뒤에는 멈추지 않게 한다.
 */
export type ChartModule<M> = (() => Promise<M>) & { loaded?: M };
export function chartModule<M>(imp: () => Promise<M>): ChartModule<M> {
  let pending: Promise<M> | null = null;
  const load = (() => {
    pending ??= imp().then(
      (m) => { load.loaded = m; return m; },
      (e: unknown) => { pending = null; throw e; },   // 못 받았으면 다음 부름에서 다시 받는다
    );
    return pending;
  }) as ChartModule<M>;
  return load;
}

// 서버에서 그릴 때와 hydration 첫 그림은 false, 그 뒤는 true — 차트는 브라우저에서만 받는다(next/dynamic 의 ssr:false 와 같은 뜻).
const noop = () => () => {};
const useOnClient = () => useSyncExternalStore(noop, () => true, () => false);

export function lazyChart<M, P extends object>(mod: ChartModule<M>, pick: (m: M) => ComponentType<P>, opts: Opts<P>): ComponentType<P> {
  // next/dynamic 이 아니라 React.lazy — 받는 동안의 자리를 ★그 차트의 prop 높이로★ 그리려면 Suspense 대체물을 그리는 쪽이 정해야 한다
  // (next/dynamic 의 loading 은 prop 을 받지 못한다). import() 는 어느 쪽이든 따로 조각이 된다.
  const Lazy = lazy(() => mod().then((m) => ({ default: pick(m) })));
  function LazyChart(props: P) {
    const onClient = useOnClient();
    // 붙는 순간 이미 받아 둔 모듈이면 Suspense 를 거치지 않는다. 한 번 정하면 그대로 — 도중에 바꾸면 차트가 다시 붙는다(애니메이션·상태 초기화).
    const [Ready] = useState<ComponentType<P> | null>(() => (mod.loaded ? pick(mod.loaded) : null));
    const val = (v: number | ((p: P) => number) | undefined) => (typeof v === "function" ? v(props) : v);
    const box: Box = { height: val(opts.height) ?? 160, width: val(opts.width), label: opts.label };
    if (!onClient) return <Slot {...box} />;
    if (Ready) return <Boundary {...box}><Ready {...props} /></Boundary>;
    return (
      <Boundary {...box}>
        <Suspense fallback={<Slot {...box} />}>
          <Lazy {...props} />
        </Suspense>
      </Boundary>
    );
  }
  LazyChart.displayName = `lazyChart(${opts.label})`;
  return LazyChart;
}
