"use client";
/**
 * 첫 화면 · 모든 도구가 스튜디오로 이어진다 (BU8a 개정)
 * ==========================================================================
 * 다섯 도구(종목 찾기·백테스트·매크로 분석·기업 분석·위험 점검)를 가운데 '포트폴리오 설계'에 선으로 잇는다.
 * ★지어낸 관계가 아니다★ 도구마다 캔버스에 실제로 있는 노드 이름을 함께 적는다 — 이름은 서버 노드 카탈로그의 `plain_label`
 * (`GET /api/v1/allocation/graph/node-types`)과 같은 말이다. 노드 이름이 바뀌면 여기도 바꾼다.
 *
 * 선은 카드 실제 위치를 재서 긋는다(ResizeObserver — 폭이 바뀌면 다시 잰다). 화면에 들어오면 한 번 그려지고(IntersectionObserver),
 * 그 뒤 선 위로 점이 천천히 흘러 '결과가 설계로 들어간다'를 보인다. 감속 모션이면 처음부터 그려 둔 채로, 흐르는 점은 없다.
 * 좁은 화면(≤1080px)에서는 세로 목록이 되고 선 대신 카드 왼쪽 세로줄이 같은 뜻을 말한다.
 */
import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Building2, ChevronRight, Globe2, LineChart, ListFilter, ShieldAlert, Workflow, type LucideIcon } from "lucide-react";

type Tool = { t: string; href: string; d: string; node: string; Icon: LucideIcon; side: "l" | "r" };
const TOOLS: Tool[] = [
  { t: "종목 찾기", href: "/screener", d: "조건식으로 종목을 선별합니다", node: "스크리닝", Icon: ListFilter, side: "l" },
  { t: "백테스트", href: "/backtest", d: "매매 규칙을 과거 데이터로 시뮬레이션합니다", node: "조건식 백테스트", Icon: LineChart, side: "l" },
  { t: "매크로 분석", href: "/macro", d: "경기·물가 국면의 방향을 분석합니다", node: "경기 국면", Icon: Globe2, side: "r" },
  { t: "기업 분석", href: "/insights", d: "개별 종목의 가치와 재무를 심층 분석합니다", node: "기업 가치평가", Icon: Building2, side: "r" },
  { t: "위험 점검", href: "/risk-tools", d: "충격 시나리오별 종목 점수 변동을 점검합니다", node: "시나리오 스트레스", Icon: ShieldAlert, side: "r" },
];

const useIsoLayout = typeof window === "undefined" ? useEffect : useLayoutEffect;

function ToolCard({ tool, i, refFn }: { tool: Tool; i: number; refFn: (el: HTMLAnchorElement | null) => void }) {
  const { Icon } = tool;
  return (
    <Link href={tool.href} className="ld-mod ld-hub-tool" data-side={tool.side} ref={refFn} style={{ ["--i" as string]: i }}>
      <span className="ld-mod-i" aria-hidden><Icon size={20} strokeWidth={1.8} /></span>
      <span className="ld-mod-body">
        <span className="ld-mod-t">{tool.t}</span>
        <span className="ld-mod-d">{tool.d}</span>
        <span className="ld-hub-node">캔버스에서는 <b>{tool.node}</b></span>
      </span>
      <ChevronRight className="ld-mod-go" size={18} aria-hidden />
    </Link>
  );
}

export function ToolHub() {
  const wrap = useRef<HTMLDivElement | null>(null);
  const hub = useRef<HTMLAnchorElement | null>(null);
  const cards = useRef<(HTMLAnchorElement | null)[]>([]);
  const [paths, setPaths] = useState<string[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [drawn, setDrawn] = useState(false);
  const [armed, setArmed] = useState(false);

  useIsoLayout(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => {
      const W = el.getBoundingClientRect();
      const H = hub.current?.getBoundingClientRect();
      if (!H || W.width < 1080) { setPaths([]); setSize({ w: W.width, h: W.height }); return; }
      const sides = { l: TOOLS.filter((t) => t.side === "l").length, r: TOOLS.filter((t) => t.side === "r").length };
      const seenSide = { l: 0, r: 0 };
      const out = TOOLS.map((tool, i) => {
        const c = cards.current[i]?.getBoundingClientRect();
        if (!c) return "";
        const k = seenSide[tool.side]++;
        // 가운데 카드 옆면에 고르게 나눠 닿는다.
        const ey = H.top - W.top + (H.height * (k + 1)) / (sides[tool.side] + 1);
        const sy = c.top - W.top + c.height / 2;
        const sx = tool.side === "l" ? c.right - W.left : c.left - W.left;
        const ex = tool.side === "l" ? H.left - W.left : H.right - W.left;
        const mx = (sx + ex) / 2;
        return `M ${sx.toFixed(1)} ${sy.toFixed(1)} C ${mx.toFixed(1)} ${sy.toFixed(1)}, ${mx.toFixed(1)} ${ey.toFixed(1)}, ${ex.toFixed(1)} ${ey.toFixed(1)}`;
      });
      setPaths(out);
      setSize({ w: W.width, h: W.height });
    };
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);

  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof IntersectionObserver === "undefined") { setDrawn(true); return; }
    setArmed(true);
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setDrawn(true); io.disconnect(); }
    }, { threshold: 0.3 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const left = TOOLS.map((t, i) => [t, i] as const).filter(([t]) => t.side === "l");
  const right = TOOLS.map((t, i) => [t, i] as const).filter(([t]) => t.side === "r");
  return (
    <div className="ld-hub" ref={wrap} data-arm={armed || undefined} data-in={drawn || undefined}>
      {paths.length ? (
        <svg className="ld-hub-lines" width={size.w} height={size.h} viewBox={`0 0 ${size.w} ${size.h}`} aria-hidden>
          {paths.map((d, i) => d && (
            <g key={i} style={{ ["--i" as string]: i }}>
              <path className="ld-hub-line" d={d} pathLength={1} />
              <path className="ld-hub-flow" d={d} pathLength={1} />
            </g>
          ))}
        </svg>
      ) : null}
      <div className="ld-hub-col" data-col="l">
        {left.map(([t, i]) => <ToolCard key={t.href} tool={t} i={i} refFn={(el) => { cards.current[i] = el; }} />)}
      </div>
      <Link href="/allocation" className="ld-mod ld-hub-core" ref={hub}>
        <span className="ld-hub-core-i" aria-hidden><Workflow size={28} strokeWidth={1.8} /></span>
        <span className="ld-mod-t">포트폴리오 설계</span>
        <span className="ld-mod-d">다섯 도구의 결과가 노드로 연결되어 하나의 설계를 구성합니다. 결정 근거도 함께 기록합니다.</span>
        <ChevronRight className="ld-mod-go ld-hub-core-go" size={20} aria-hidden />
      </Link>
      <div className="ld-hub-col" data-col="r">
        {right.map(([t, i]) => <ToolCard key={t.href} tool={t} i={i} refFn={(el) => { cards.current[i] = el; }} />)}
      </div>
    </div>
  );
}
