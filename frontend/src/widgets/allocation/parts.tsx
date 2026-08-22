"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// Allocation Studio 시각화 프리미티브 — cockpitParts 관례(recharts + 자체 SVG,
// Institutional Terminal 토큰, 애니메이션은 `useChartAnimation()` 이 정한다) 그대로 복제.
//   FrontierChart · AllocationSankey · FactorXRayBars · RiskContribDonut ·
//   StressChart · McHistogram · ConfidenceGauge · MetricsTable
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import {
  ResponsiveContainer, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceDot, PieChart, Pie, Cell, Sankey, Layer,
  RadialBarChart, RadialBar, PolarAngleAxis,
} from "recharts";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/shared/ui/shadcn/table";
import type { AnalyzeResult, StressResult, SummaryStats, XrayFactor } from "@/entities/allocation/api";
import { TIP_STYLE } from "@/shared/ui/chartStyle";
import { useChartAnimation } from "@/shared/ui/chartStyle";

// 툴팁 스타일은 `shared/ui/chartStyle` 이 단일 출처다 (A4-X3 에서 토큰화, A6 에서
// 이 파일 밖으로 이사). 여기 두었더니 상수 하나 때문에 09 저널이 parts.tsx 전체를
// 끌어와 번들이 +30kB 였다 — 사유는 그 파일의 헤더에 있다.
/** 마커 테두리 — 차트 배경색이어야 점이 배경에서 떠 보인다. 흰색을 박으면 다크에서 흰 링이 남는다. */
const DOT_RING = "var(--card)";
// 팔레트·AllocationMap 은 recharts 를 쓰지 않아 별도 파일로 분리했다 (P3) —
// 사유는 그 파일 헤더에. 기존 import 경로를 지키기 위해 여기서 re-export 한다.
export { AllocationMap, paletteColor } from "./AllocationMap";
// 순수 계산도 shared/lib 로 — parts.tsx 를 부르면 recharts 가 딸려온다.
export { concentration, exposureLegs } from "@/shared/lib/exposure";
import { paletteColor } from "./AllocationMap";

/** 부호 있는 포맷 — 차트 라벨·요약 셀이 공유한다. `null`/비유한값은 —. */
export const fmtSign = (v: number | null | undefined, d = 2): string =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`;

/** 값 하나 — 숫자이거나, 아직 산출되지 않았거나. 0 은 세 번째가 아니라 첫 번째 경우다. */
export type CmpValue = number | null;
export interface CmpRow { code: string; name: string; current: number; market: CmpValue; optimized: CmpValue }

/**
 * 비중 비교 표 (A3 S3c).
 *
 * ★예전에는 `12.5 / 8.3 / 14.1%` 한 덩어리였다★ 9.5px 로. 세 값이 각각 무엇인지는
 * 카드 제목 옆 범례에만 있었고, 열끼리 세로로 비교하는 것 — 이 표의 존재 이유 — 이
 * 불가능했다. 진짜 <table> 로 바꾸면 스크린리더도 "삼성전자의 최적화 비중"이라고 읽는다.
 *
 * ★`null` 은 0 이 아니다★ 최적화를 돌리기 전의 캡가중/최적화 열은 **없는 값**이지
 * 0% 가 아니다. 숫자를 그리지 않고 미계산이라고 쓴다.
 */
export function WeightComparison({ rows }: { rows: CmpRow[] }) {
  const cell = (v: CmpValue) =>
    v == null
      ? <span className="aas-cmp-na">미계산</span>
      : <span className="num">{v.toFixed(1)}</span>;
  return (
    <Table className="aas-cmp-t">
      <TableHeader>
        <TableRow>
          <TableHead scope="col">자산</TableHead>
          <TableHead scope="col" className="text-right">현재</TableHead>
          <TableHead scope="col" className="text-right">캡가중</TableHead>
          <TableHead scope="col" className="text-right">최적화</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.code}>
            <TableHead scope="row" className="aas-cmp-nm">{r.name}</TableHead>
            <TableCell className="text-right"><span className="num">{r.current.toFixed(1)}</span></TableCell>
            <TableCell className="text-right">{cell(r.market)}</TableCell>
            <TableCell className="text-right">{cell(r.optimized)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** 03 THESIS — 뷰가 시장 사전분포를 얼마나 움직였는가. 값이 없으면 `null`(0 아님). */
export interface ViewEffectRow {
  code: string; name: string;
  market: CmpValue; applied: CmpValue; delta: CmpValue;
}

/**
 * 뷰 효과 표 (A5).
 *
 * 03 은 뷰를 **세우는** 화면인데 뷰가 무엇을 바꿨는지는 어디에도 없었다. 데이터는 이미
 * 있다 — `result.flow.market` / `flow.view_applied` 는 05 의 산키가 쓰는 그 값이다.
 * 새 엔드포인트 없이 같은 값을 자산별로 읽는다.
 *
 * ★실행 전에는 0 이 아니라 '미계산'이다★ 최적화를 돌리기 전에는 시장 사전분포도 뷰
 * 사후분포도 존재하지 않는다. `0.0`으로 채우면 "뷰가 아무것도 안 바꿨다"로 읽힌다 —
 * A3 가 캡가중 열에서, A4 가 Overview 의 충격에서 고친 것과 같은 부류의 거짓말이다.
 */
export function ViewEffect({ rows }: { rows: ViewEffectRow[] }) {
  const cell = (v: CmpValue, sign = false) =>
    v == null
      ? <span className="aas-cmp-na">미계산</span>
      : <span className={`num${sign ? ` as-ve-d ${v >= 0 ? "up" : "down"}` : ""}`}>
          {sign ? fmtSign(v, 1) : v.toFixed(1)}
        </span>;
  return (
    <Table className="aas-cmp-t as-ve-t">
      <TableHeader>
        <TableRow>
          <TableHead scope="col">자산</TableHead>
          <TableHead scope="col" className="text-right">시장(캡가중)</TableHead>
          <TableHead scope="col" className="text-right">뷰 반영</TableHead>
          <TableHead scope="col" className="text-right">Δ</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.code}>
            <TableHead scope="row" className="aas-cmp-nm">{r.name}</TableHead>
            <TableCell className="text-right">{cell(r.market)}</TableCell>
            <TableCell className="text-right">{cell(r.applied)}</TableCell>
            <TableCell className="text-right">{cell(r.delta, true)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * 비중 도넛 — 스트립과 같은 데이터를 원형으로. 스트립은 "누가 큰가"를, 도넛은
 * "몇 조각으로 나뉘었나"를 먼저 보여 준다. 애니메이션은 런타임 판정을 따른다
 * (`useChartAnimation` — reduced-motion 과 E2E 에서만 꺼진다).
 */
export function AllocationDonut({ items, height = 172 }: {
  items: { code: string; name: string; weight: number }[]; height?: number;
}) {
  const anim = useChartAnimation();
  // ★도넛은 gross 기준으로 그리고 그 사실을 적는다 (P3)★ 파이 조각에 음수를 넣을
  // 방법은 없다. 숏을 버리면 "이 책이 몇 조각으로 나뉘었나" 를 틀리게 말하므로,
  // |w| 로 그리되 **기준을 라벨로 밝힌다** — 라벨 없이 기준만 바꾸면 같은 자리에
  // 뜻이 다른 숫자가 앉는다.
  const hasShort = items.some((x) => x.weight < 0);
  const shown = hasShort
    ? items.filter((x) => x.weight !== 0).map((x) => ({ ...x, weight: Math.abs(x.weight) }))
    : items.filter((x) => x.weight > 0);
  if (!shown.length) return <div className="as-empty">비중이 있는 자산이 없습니다.</div>;
  return (
    <div className="aas-donut" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={shown} dataKey="weight" nameKey="name" innerRadius="55%" outerRadius="82%"
            paddingAngle={1} isAnimationActive={anim} stroke="var(--card)">
            {shown.map((x, i) => <Cell key={x.code} fill={paletteColor(i)} />)}
          </Pie>
          <Tooltip contentStyle={TIP_STYLE}
            formatter={(v: number, n: string) => [`${v.toFixed(1)}%`, n]} />
        </PieChart>
      </ResponsiveContainer>
      {hasShort && (
        <div className="as-note as-ls-basis">
          gross 기준 (|비중|) — 파이 조각은 방향을 표현하지 못하므로 크기만 그립니다.
          롱·숏 구분은 위 비중 스트립과 범례에서 보세요.
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FrontierChart — MC 클라우드(산점) + SLSQP 프론티어 곡선 + 마커 4종
//   λ(위험회피)는 클라이언트 사이드: 이미 받은 곡선 30점에서 u=μ-(λ/2)σ² argmax
// ─────────────────────────────────────────────────────────────────────────────
export function lambdaOptimalIdx(curve: { return: number; volatility: number }[], lam: number): number {
  if (!curve.length) return -1;
  let best = 0;
  let bestU = -Infinity;
  curve.forEach((p, i) => {
    const mu = p.return / 100;
    const sig = p.volatility / 100;
    const u = mu - (lam / 2) * sig * sig;
    if (u > bestU) { bestU = u; best = i; }
  });
  return best;
}

// 확률 구름 점 — sharpe 상대순위에 따라 투명도·크기 그라데이션 (Gemini ④: 선이 아니라 구름)
function CloudDot(props: { cx?: number; cy?: number; payload?: { q?: number } }) {
  const { cx = 0, cy = 0, payload } = props;
  const q = payload?.q ?? 0.3; // 0(저샤프)~1(고샤프)
  return <circle cx={cx} cy={cy} r={1.6 + q * 1.4} fill="var(--t-accent)"
    opacity={0.08 + q * 0.34} />;
}

export function FrontierChart({ result, lam, height = 256 }: { result: AnalyzeResult; lam: number; height?: number }) {
  const anim = useChartAnimation();
  const cloud = result.frontier.cloud;
  const sh = cloud.sharpes || [];
  const shMin = sh.length ? Math.min(...sh) : 0;
  const shRange = sh.length ? (Math.max(...sh) - shMin || 1) : 1;
  const cloudData = cloud.volatilities.map((v, i) => ({
    x: v, y: cloud.returns[i],
    q: sh.length ? (sh[i] - shMin) / shRange : 0.3,
  }));
  const curveData = result.frontier.curve.map((p) => ({ x: p.volatility, y: p.return }));
  const lamIdx = lambdaOptimalIdx(result.frontier.curve, lam);
  const lamPt = lamIdx >= 0 ? curveData[lamIdx] : null;
  const pts = result.points;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 14, bottom: 6, left: -8 }}>
        <CartesianGrid strokeDasharray="2 2" stroke="var(--t-border)" />
        <XAxis type="number" dataKey="x" name="변동성" unit="%" tick={{ fontSize: 9.5, fontFamily: "var(--t-mono)" }}
          label={{ value: "Risk (연 변동성 %)", position: "insideBottom", offset: -4, fontSize: 9.5, fill: "var(--t-muted)" }} />
        <YAxis type="number" dataKey="y" name="수익률" unit="%" tick={{ fontSize: 9.5, fontFamily: "var(--t-mono)" }}
          label={{ value: "Return %", angle: -90, position: "insideLeft", fontSize: 9.5, fill: "var(--t-muted)" }} />
        <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string, name: string) => [`${Number(val).toFixed(2)}%`, name === "y" ? "수익률" : "변동성"]} />
        <Scatter data={cloudData} isAnimationActive={anim} shape={<CloudDot />} />
        <Scatter data={curveData} fill="var(--t-accent)" line={{ stroke: "var(--t-accent)", strokeWidth: 1.5 }} isAnimationActive={anim} shape={() => <g />} />
        {pts?.market && <ReferenceDot x={pts.market.volatility_pct} y={pts.market.return_pct} r={5} fill="#64748b" stroke={DOT_RING} label={{ value: "시장", fontSize: 9, position: "bottom", fill: "var(--t-muted)" }} />}
        {pts?.current && <ReferenceDot x={pts.current.volatility_pct} y={pts.current.return_pct} r={5} fill="#0891b2" stroke={DOT_RING} label={{ value: "현재", fontSize: 9, position: "bottom", fill: "var(--t-muted)" }} />}
        {/* ★라벨의 `fill` 은 대비 감사가 원리적으로 못 잰다★ `contrastAudit` 은
            `getComputedStyle().color` 를 읽는데 SVG 텍스트의 색은 `fill` 속성에서
            온다. 그래서 이 10px 라벨은 가드가 없다 — 다크에서 `#dc2626` 이
            zinc-950 위 3.67:1 인 것을 알고 토큰으로 바꾸되, "측정으로 증명했다"고
            적지 않는다. 점 자체(`fill` on the dot)는 그래픽이라 3:1 기준이다. */}
        {pts?.optimal && <ReferenceDot x={pts.optimal.volatility_pct} y={pts.optimal.return_pct} r={7} fill="var(--chart-down)" stroke={DOT_RING} strokeWidth={1.5} label={{ value: "★ 최적", fontSize: 10, position: "top", fill: "var(--color-bear)" }} />}
        {lamPt && <ReferenceDot x={lamPt.x} y={lamPt.y} r={5} fill="var(--t-accent)" stroke={DOT_RING} label={{ value: `λ=${lam.toFixed(1)}`, fontSize: 9, position: "top", fill: "var(--t-accent)" }} />}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AllocationSankey — 시장(캡가중) → 뷰 반영 → 최적화 3열 가중치 흐름
// ─────────────────────────────────────────────────────────────────────────────
function sankeyData(result: AnalyzeResult) {
  const stages: ["market", "view_applied", "optimized"] = ["market", "view_applied", "optimized"];
  const stageLabels = { market: "시장(캡가중)", view_applied: "뷰 반영(BL)", optimized: "최적화" };
  const nodes: { name: string }[] = [];
  const nodeIdx = new Map<string, number>();
  const links: { source: number; target: number; value: number }[] = [];
  const label = (code: string) => result.labels[code] || code;

  stages.forEach((st) => {
    Object.keys(result.flow[st]).forEach((code) => {
      const key = `${st}:${code}`;
      if (!nodeIdx.has(key)) {
        nodeIdx.set(key, nodes.length);
        nodes.push({ name: `${label(code)}` });
      }
    });
  });
  // 인접 열 간 링크: 흐름 보존을 위해 min(현재, 다음) + 잔차 재배분(단순 비례)
  for (let s = 0; s < 2; s++) {
    const cur = result.flow[stages[s]];
    const nxt = result.flow[stages[s + 1]];
    Object.entries(cur).forEach(([code, wc]) => {
      const from = nodeIdx.get(`${stages[s]}:${code}`);
      const stay = Math.min(wc, nxt[code] ?? 0);
      if (from == null) return;
      if (stay > 0.01 && nodeIdx.has(`${stages[s + 1]}:${code}`)) {
        links.push({ source: from, target: nodeIdx.get(`${stages[s + 1]}:${code}`)!, value: stay });
      }
      let spill = wc - stay;
      if (spill > 0.01) {
        // 증가한 종목들에게 비례 배분
        const gains = Object.entries(nxt).filter(([c2, w2]) => (w2 - (cur[c2] ?? 0)) > 0.01);
        const gainTot = gains.reduce((a, [c2, w2]) => a + (w2 - (cur[c2] ?? 0)), 0);
        gains.forEach(([c2, w2]) => {
          const to = nodeIdx.get(`${stages[s + 1]}:${c2}`);
          if (to == null || gainTot <= 0) return;
          const v = spill * ((w2 - (cur[c2] ?? 0)) / gainTot);
          if (v > 0.01) links.push({ source: from, target: to, value: v });
        });
        spill = 0;
      }
    });
  }
  return { nodes, links, stageLabels: stages.map((s) => stageLabels[s]) };
}

/**
 * 산키 노드 + 라벨.
 *
 * ★마지막 단 라벨이 잘려 나갔다 (A5)★ 예전에는 단과 무관하게 라벨을 **항상 노드 오른쪽**
 * (`x + width + 5`)에 그렸다. 오른쪽 여백은 110px 인데 "KODEX 미국S&P500 89.5%" 같은
 * 국내 ETF 이름은 그걸 훌쩍 넘는다 — 화면에서는 이름이 짧게 줄여진 것처럼 보여서
 * (`KODEX 미국S&P500 89`) 결함이 아니라 디자인처럼 읽혔다. 마지막 단은 노드 **왼쪽**에
 * 그린다(산키의 통상 규약). 그래서 `containerWidth` 가 필요하다.
 *
 * 폰트도 9.5px 하드코딩이었다. SVG 텍스트라 CSS 하한이 닿지 않으므로 여기서 올린다
 * (Overview 의 인라인 fontSize 와 같은 부류 — A4-V2).
 */
function SankeyNode(props: {
  x?: number; y?: number; width?: number; height?: number;
  index?: number; lastFrom?: number; payload?: { name: string; value: number };
}) {
  const { x = 0, y = 0, width = 0, height = 0, index = 0, lastFrom = Infinity, payload } = props;
  // ★첫 판은 `containerWidth` 로 마지막 단을 추정했다 — Recharts 가 그 prop 을 주지
  // 않아서 항상 false 였고, 테스트가 라벨 6개 초과로 잡았다. 추정 대신 **데이터에서**
  // 정한다: sankeyData 가 노드를 단 순서대로 밀어 넣으므로 마지막 단은 뒤쪽 한 덩어리다.
  const isLast = index >= lastFrom;
  const label = `${payload?.name ?? ""}${payload?.value ? ` ${payload.value.toFixed(1)}%` : ""}`;
  return (
    <Layer>
      <rect x={x} y={y} width={width} height={height} fill="var(--t-accent)" fillOpacity={0.85} rx={1} />
      <text
        x={isLast ? x - 5 : x + width + 5}
        y={y + height / 2}
        dy="0.35em"
        textAnchor={isLast ? "end" : "start"}
        fontSize={11}
        fontFamily="var(--t-mono)"
        fill="var(--t-ink)"
      >
        {label}
      </text>
    </Layer>
  );
}

export function AllocationSankey({ result }: { result: AnalyzeResult }) {
  const { nodes, links, stageLabels } = sankeyData(result);
  if (!links.length) return <div className="as-empty">가중치 흐름 없음</div>;
  // 마지막 단(최적화) 노드는 목록의 뒤쪽 한 덩어리다 — 그 구간부터 라벨을 안쪽으로 그린다.
  const lastFrom = nodes.length - Object.keys(result.flow.optimized).length;
  return (
    <div>
      <div className="as-sankey-heads">
        {stageLabels.map((l) => <span key={l}>{l}</span>)}
      </div>
      <ResponsiveContainer width="100%" height={Math.max(220, nodes.length * 14)}>
        {/* 오른쪽 여백 110 → 12: 마지막 단 라벨을 안쪽으로 뒤집었으므로 바깥 여백이 필요 없다.
            줄어든 만큼이 차트 폭으로 돌아간다. */}
        {/* ★Sankey 는 애니메이션 대상이 아니다 (A12, 측정으로 확인)★ 처음에는 라벨 위치를
            재는 `allocation-stages.spec.ts` 가 흔들릴까 봐 여기도 배선하려 했는데,
            `recharts/es6/chart/Sankey.js` 에는 Animate 사용이 **0건**이고 타입에도
            `isAnimationActive` 가 없다. 프롭을 넣으면 컴파일이 깨진다. */}
        <Sankey data={{ nodes, links }} node={<SankeyNode lastFrom={lastFrom} />} nodePadding={14} nodeWidth={8}
          margin={{ top: 8, right: 12, bottom: 8, left: 4 }}
          link={{ stroke: "var(--t-accent)", strokeOpacity: 0.18 }}>
          <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string) => [`${Number(val).toFixed(1)}%`, "이동 비중"]} />
        </Sankey>
      </ResponsiveContainer>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FactorXRayBars — 팩터 z 가로 막대 (포트폴리오 vs 벤치마크 틱) + 커버리지 배지
// ─────────────────────────────────────────────────────────────────────────────
export function FactorXRayBars({ factors }: { factors: XrayFactor[] }) {
  const MAX = 3; // z 클립 범위와 동일
  return (
    <div className="as-xray">
      {factors.map((f) => {
        const pw = Math.min(Math.abs(f.portfolio_z) / MAX, 1) * 50;
        const bx = 50 + Math.max(-1, Math.min(1, f.benchmark_z / MAX)) * 50;
        const pos = f.portfolio_z >= 0;
        return (
          <div key={f.id} className="as-xray-row" title={`유니버스 표본 ${f.n_universe}종목 기준 z-score`}>
            <span className="as-xray-label">{f.label}</span>
            <div className="as-xray-track">
              <i className="as-xray-mid" />
              <i className={`as-xray-bar${pos ? " pos" : " neg"}`}
                style={pos ? { left: "50%", width: `${pw}%` } : { right: "50%", width: `${pw}%` }} />
              <i className="as-xray-bench" style={{ left: `${bx}%` }} title={`벤치마크 z ${fmtSign(f.benchmark_z)}`} />
            </div>
            <span className="as-xray-val num">{fmtSign(f.portfolio_z)}</span>
            {f.coverage_pct < 99.5 && <span className="as-xray-cov" title="이 팩터 데이터가 없는 자산은 재정규화됨">{f.coverage_pct.toFixed(0)}%</span>}
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// RiskContribDonut — 리스크 기여 도넛 (HoldingsDonut 템플릿)
// ─────────────────────────────────────────────────────────────────────────────
export function RiskContribDonut({ contributions, labels, size = 128 }: {
  contributions: Record<string, number>; labels: Record<string, string>; size?: number;
}) {
  const anim = useChartAnimation();
  const entries = Object.entries(contributions).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const tot = entries.reduce((a, [, v]) => a + v, 0) || 1;
  const data = entries.map(([code, v]) => ({ name: labels[code] || code, value: Math.round((v / tot) * 1000) / 10 }));
  return (
    <div className="as-donut-wrap">
      <PieChart width={size} height={size}>
        <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={size * 0.3} outerRadius={size * 0.47} paddingAngle={1} stroke="none" isAnimationActive={anim}>
          {data.map((_, idx) => <Cell key={idx} fill={paletteColor(idx)} />)}
        </Pie>
        <Tooltip contentStyle={TIP_STYLE} formatter={(val: number | string, name: string) => [`${val}%`, name]} />
      </PieChart>
      <div className="as-donut-legend">
        {data.slice(0, 7).map((d, i) => (
          <div key={d.name} className="as-donut-li">
            <i style={{ background: paletteColor(i) }} />
            <span className="as-donut-nm">{d.name}</span>
            <span className="num">{d.value.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// StressChart — 역사 리플레이 드로다운 곡선 (자체 SVG 폴리라인, EquityChart idiom)
// ─────────────────────────────────────────────────────────────────────────────
export function StressChart({ result }: { result: StressResult }) {
  const dd = result.portfolio_dd || [];
  if (!dd.length) return null;
  const bench = result.benchmark_dd || null;
  const W = 1000; const H = 180;
  const all = bench ? [...dd, ...bench] : dd;
  const min = Math.min(...all, 0);
  const range = 0 - min || 1;
  const toPts = (arr: number[]) => arr.map((v, i) => {
    const x = (i / Math.max(arr.length - 1, 1)) * W;
    const y = ((0 - v) / range) * (H - 8) + 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 150, display: "block" }} preserveAspectRatio="none">
        <polygon points={`0,4 ${toPts(dd)} ${W},4`} fill="var(--chart-down)" opacity={0.07} />
        {bench && <polyline points={toPts(bench)} fill="none" stroke="var(--t-muted)" strokeWidth={1.4} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
        <polyline points={toPts(dd)} fill="none" stroke="var(--chart-down)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="as-stress-meta">
        <span>최대 낙폭 <b className="num" style={{ color: "var(--color-bear)" }}>{result.max_dd_pct?.toFixed(1)}%</b></span>
        {result.benchmark_max_dd_pct != null && <span>벤치마크 <b className="num">{result.benchmark_max_dd_pct.toFixed(1)}%</b></span>}
        {result.total_return_pct != null && <span>기간 수익 <b className="num">{fmtSign(result.total_return_pct, 1)}%</b></span>}
      </div>
      {!!result.dropped?.length && (
        <div className="as-note">데이터 미보유로 제외: {result.dropped.join(", ")} (잔여 자산 재정규화)</div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// McHistogram — 1년 수익 분포 (자체 SVG 바) + VaR/기대수익/CVaR 마커
// ─────────────────────────────────────────────────────────────────────────────
export function McHistogram({ mc }: { mc: AnalyzeResult["mc"] }) {
  const bins = mc.bins || [];
  if (!bins.length) return null;
  const W = 1000; const H = 150;
  const maxC = Math.max(...bins.map((b) => b.count), 1);
  const x0 = bins[0].x0; const x1 = bins[bins.length - 1].x1;
  const span = x1 - x0 || 1;
  const xOf = (v: number) => ((v - x0) / span) * W;
  const bw = W / bins.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 130, display: "block" }} preserveAspectRatio="none">
        {bins.map((b, i) => {
          const h = (b.count / maxC) * (H - 22);
          return <rect key={i} x={i * bw + 0.5} y={H - 16 - h} width={Math.max(bw - 1, 1)} height={h}
            fill="var(--t-accent)" opacity={b.x1 <= -mc.var95_pct ? 0.75 : 0.28} />;
        })}
        <line x1={xOf(-mc.var95_pct)} x2={xOf(-mc.var95_pct)} y1={4} y2={H - 16} stroke="var(--chart-down)" strokeWidth={1.5} strokeDasharray="4 3" />
        <line x1={xOf(mc.expected_pct)} x2={xOf(mc.expected_pct)} y1={4} y2={H - 16} stroke="var(--chart-up)" strokeWidth={1.5} />
      </svg>
      <div className="as-mc-meta">
        <span>95% VaR <b className="num" style={{ color: "var(--color-bear)" }}>-{mc.var95_pct.toFixed(1)}%</b></span>
        <span>기대수익 <b className="num" style={{ color: "var(--color-bull)" }}>{fmtSign(mc.expected_pct, 1)}%</b></span>
        <span>95% CVaR <b className="num" style={{ color: "var(--color-bear)" }}>-{mc.cvar95_pct.toFixed(1)}%</b></span>
      </div>
      <div className="as-note">{mc.note}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ConfidenceGauge — 종합 뷰 신뢰도 아크 (ArcGauge 템플릿)
// ─────────────────────────────────────────────────────────────────────────────
export function ConfidenceGauge({ value, height = 120 }: { value: number; height?: number }) {
  const anim = useChartAnimation();
  const v = Math.max(0, Math.min(100, value || 0));
  const label = v >= 75 ? "High" : v >= 50 ? "Moderately High" : v >= 25 ? "Moderate" : "Low";
  // 반원(180°) 게이지는 폭 ≈ 2×반지름이 필요 — flex 컨텍스트(.as-tm-mkt)에서 폭이 0으로
  // 접혀 차트가 뭉개지고 중앙 텍스트가 옆 라벨로 넘치던 문제 방지: 높이 기준으로 폭 고정.
  const w = Math.round(height * 1.8);
  return (
    <div className="as-gauge" style={{ width: w, flex: "none" }}>
      <ResponsiveContainer width={w} height={height}>
        <RadialBarChart innerRadius="66%" outerRadius="100%" data={[{ name: "v", value: v }]} startAngle={180} endAngle={0} barSize={12}>
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar background={{ fill: "var(--t-border)" }} dataKey="value" cornerRadius={6} fill="var(--t-accent)" isAnimationActive={anim} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="as-gauge-c" style={{ top: height * 0.42 }}><b>{Math.round(v)}</b><span>Overall Confidence</span><em>{label}</em></div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SensitivityHeatmap — 기댓값 변동(행: μ+bump 충격 자산) → 최적 비중 반응(열) Δ%p
//   Robustness 재정의(Research OS): 입력 불확실성에 대한 가중치 안정성 검증.
// ─────────────────────────────────────────────────────────────────────────────
function heatColor(v: number, maxAbs: number): string {
  if (!Number.isFinite(v) || maxAbs <= 0) return "transparent";
  const t = Math.max(-1, Math.min(1, v / maxAbs));
  // ★알파 상한을 0.48 로 낮췄다 (A4-X2)★ 예전 상한은 0.66 이라 셀 자체가 사실상
  // 불투명한 초록/빨강 판이 됐고, 그 위에 `--t-ink` 로 글자를 얹었다. 다크에서
  // --t-ink 는 #fafafa 로 뒤집히므로 진한 초록 위 흰 글씨(3.16:1)가 된다.
  // 0.5 아래로 두면 셀 색이 카드 배경과 합성돼 라이트·다크 양쪽에서 글자가 이긴다.
  const a = 0.06 + 0.42 * Math.abs(t);
  return t >= 0 ? `rgba(22,163,74,${a.toFixed(3)})` : `rgba(220,38,38,${a.toFixed(3)})`;
}

export function SensitivityHeatmap({ names, labels, matrix, baseWeights, bumpPct }: {
  names: string[]; labels: Record<string, string>;
  matrix: number[][]; baseWeights: number[]; bumpPct: number;
}) {
  const maxAbs = Math.max(0.01, ...matrix.flat().map((v) => Math.abs(v)));
  const nm = (c: string) => labels[c] || c;
  return (
    <div className="as-heat-wrap">
      <table className="as-heat">
        <thead>
          <tr>
            <th className="as-heat-corner">충격 ＼ 반응</th>
            {names.map((c) => <th key={c} title={c}>{nm(c)}</th>)}
            <th className="as-heat-base">base</th>
          </tr>
        </thead>
        <tbody>
          {names.map((rc, i) => (
            <tr key={rc}>
              <th title={`${nm(rc)} 기대수익 +${bumpPct}%p 충격`}>{nm(rc)} <em>+{bumpPct}%</em></th>
              {names.map((cc, j) => (
                <td key={cc} className="num" style={{ background: heatColor(matrix[i][j], maxAbs) }}
                  title={`${nm(rc)} μ+${bumpPct}%p → ${nm(cc)} 비중 ${fmtSign(matrix[i][j], 2)}%p`}>
                  {fmtSign(matrix[i][j], 1)}
                </td>
              ))}
              <td className="num as-heat-base">{baseWeights[i]?.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="as-note">셀 = 행 자산의 기대수익을 +{bumpPct}%p 올렸을 때 열 자산의 최적 비중 변화(%p).
        초록=증가·빨강=감소. 행 합≈0(완전투자 제약). 대각이 크고 비대각이 작을수록 안정적.</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CorrelationMini — 상관행렬 미니 히트맵 (result.correlation 재사용)
// ─────────────────────────────────────────────────────────────────────────────
export function CorrelationMini({ correlation, names, labels }: {
  correlation: Record<string, Record<string, number>>;
  names: string[]; labels: Record<string, string>;
}) {
  const nm = (c: string) => labels[c] || c;
  return (
    <div className="as-heat-wrap">
      <table className="as-heat">
        <thead>
          <tr><th className="as-heat-corner" />{names.map((c) => <th key={c}>{nm(c)}</th>)}</tr>
        </thead>
        <tbody>
          {names.map((r) => (
            <tr key={r}>
              <th>{nm(r)}</th>
              {names.map((c) => {
                const v = correlation[r]?.[c];
                return (
                  <td key={c} className="num"
                    style={{ background: v == null ? "transparent" : heatColor(v, 1) }}
                    title={`${nm(r)} × ${nm(c)}`}>
                    {v == null ? "—" : v.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MetricsTable — Portfolio / Benchmark / Active 3열
// ─────────────────────────────────────────────────────────────────────────────
const METRIC_ROWS: { key: keyof SummaryStats; label: string; suffix: string }[] = [
  { key: "expected_return_pct", label: "기대수익(연)", suffix: "%" },
  { key: "volatility_pct", label: "변동성(연)", suffix: "%" },
  { key: "sharpe", label: "Sharpe", suffix: "" },
  { key: "max_drawdown_pct", label: "최대낙폭", suffix: "%" },
  { key: "sortino", label: "Sortino", suffix: "" },
  { key: "calmar", label: "Calmar", suffix: "" },
];

export function MetricsTable({ summary }: { summary: AnalyzeResult["summary"] }) {
  const { portfolio, benchmark, active, benchmark_label } = summary;
  return (
    <table className="as-metrics">
      <thead>
        <tr><th>Metric</th><th>Portfolio</th><th>{benchmark_label || "Benchmark"}</th><th>Active</th></tr>
      </thead>
      <tbody>
        {METRIC_ROWS.map((m) => {
          const p = portfolio?.[m.key];
          const b = benchmark?.[m.key];
          const a = active?.[m.key];
          return (
            <tr key={m.key}>
              <td>{m.label}</td>
              <td className="num">{p != null ? `${p}${m.suffix}` : "—"}</td>
              <td className="num">{b != null ? `${b}${m.suffix}` : "—"}</td>
              <td className="num" style={{ color: a == null ? "var(--t-muted)" : a >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>
                {a != null ? `${fmtSign(a, 2)}${m.suffix}` : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
