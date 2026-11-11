"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// insights/parts — 기업 분석 공용 그림 (recharts + SVG).
// BU6(토스식) — 색 뜻 넷(BU5 규칙 그대로, `widgets/macro/macroKo.ts`):
//   · 등락(추세 스파크라인) = 한국식 `--tx-up`(빨강)/`--tx-down`(파랑) — 방향은 `data-dir` 로도 남긴다
//   · 수준(팩터 백분위) = `--mc-lv-*` 양쪽 색(50 이 가운데)
//   · 판단(판정·점수·괴리·시나리오) = 색으로 말하지 않는다(중립) — 글자가 말한다
//   · 범주(가치 모형·밴드) = `catColor`
// 새 그림: 주가와 가치 범위를 겹친 그림(`PriceValueChart`). 옛 1년 주가 면적(`PriceChart`)은 지우지 않고 "자세히" 안에 둔다(사용자 결정).
// 툴팁 `title=` 0 — 값은 늘 보이는 글자로 함께 있다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { Spark as SparkLine } from "@/shared/ui/plot/Spark";
import type { FactorVal, FactorGroup, ModelResult, Scenario, VerdictTone } from "@/entities/company/insightsModel";
import { won, eok, pct } from "@/entities/company/insightsModel";
import { catColor, pctFill } from "@/shared/ui/vizColor";
import { chartModule, lazyChart } from "@/shared/ui/lazyChart";

/** 판정 칩 — ★중립★(저평가·고평가는 서버 판단이고 색으로 덧칠하지 않는다). `tone` 은 받지만 색에 쓰지 않는다. */
export function VerdictBadge({ verdict, big }: { verdict: string; tone?: VerdictTone; big?: boolean }) {
  return <span className={`ca-verdict ci-verdict${big ? " big" : ""}`} data-server>{verdict}</span>;
}

/** 반원 점수 게이지 — 중립 한 색(점수 높낮이로 색이 바뀌지 않는다). */
export function Gauge({ value, label, sub, size = 132 }: { value: number; label?: string; sub?: string; color?: string; size?: number }) {
  const v = Math.max(0, Math.min(100, value));
  const w = size, h = size * 0.62;
  return (
    <div className="ca-gauge" style={{ width: w }}>
      <svg viewBox="0 0 120 70" width={w} height={h} role="img" aria-label={`${label ?? "점수"} ${Math.round(value)}점(100점 만점)`}>
        <path d="M 10 62 A 50 50 0 0 1 110 62" fill="none" stroke="var(--tx-line)" strokeWidth="10" strokeLinecap="round" pathLength={100} />
        <path className="ca-gauge-fill" d="M 10 62 A 50 50 0 0 1 110 62" fill="none" stroke="var(--tx-blue)" strokeWidth="10" strokeLinecap="round" pathLength={100} strokeDasharray={`${v} 100`} />
        <text x="60" y="54" textAnchor="middle" className="ca-gauge-num">{Math.round(value)}</text>
      </svg>
      {label && <div className="ca-gauge-label">{label}</div>}
      {sub && <div className="ca-gauge-sub" data-server>{sub}</div>}
    </div>
  );
}

/** 점수 고리 — 중립 한 색. */
export function ScoreRing({ score, size = 84 }: { score: number; size?: number }) {
  return (
    <div className="ca-ring" style={{ width: size, height: size }}>
      <svg viewBox="0 0 80 80" width={size} height={size} role="img" aria-label={`종합점수 ${score}점`}>
        <circle cx="40" cy="40" r="34" fill="none" stroke="var(--tx-line)" strokeWidth="7" />
        <circle cx="40" cy="40" r="34" fill="none" stroke="var(--tx-blue)" strokeWidth="7" strokeLinecap="round" pathLength={100} strokeDasharray={`${score} 100`} transform="rotate(-90 40 40)" />
        <text x="40" y="45" textAnchor="middle" className="ca-ring-num">{score}</text>
      </svg>
    </div>
  );
}

// ── 주가와 가치를 겹친 그림 (BU6, 사용자 결정) ──

// ── 차트 셋(+ 돈 버는 힘의 이야기 그림) — 본문은 `charts.tsx`. 화면이 뜬 뒤에 받는다(recharts 를 첫 화면 JS 에서 뺌 · lazyChart).
//    기업 분석 화면 뿌리(app/insights)가 붙자마자 `loadCharts()` 로 미리 받아 둔다. 이름·prop 은 그대로라 소비자는 바뀌지 않는다.
export const loadCharts = chartModule(() => import("./charts"));
export const PriceChart = lazyChart(loadCharts, (m) => m.PriceChart, { height: (p) => (p.height ?? 200) + 76, label: "1년 주가" });
export const PriceValueChart = lazyChart(loadCharts, (m) => m.PriceValueChart, { height: (p) => (p.height ?? 260) + 56 + 76, label: "주가와 밸류에이션 밴드" });
export const KpiBars = lazyChart(loadCharts, (m) => m.KpiBars, { height: (p) => (p.height ?? 130) + 48, label: "기간별 막대" });

export type ValueBandIn = { id: string; label: string; lo: number; hi: number };


/** 추세 스파크라인 — ★등락색★(첫 값보다 끝 값이 크면 오름 = `--tx-up`). 방향은 `data-dir` 로도 남긴다(색만으로 말하지 않게 옆에 값이 있다). */
export function Spark({ values, color, w = 90, h = 26 }: { values: (number | null)[]; color?: string; w?: number; h?: number }) {
  // 모르는 기간(null)은 건너뛴다 — 0 으로 끌어내리지 않는다(BU6b)
  const v = values.filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  if (v.length < 2) return null;
  const dir = v[v.length - 1] > v[0] ? "up" : v[v.length - 1] < v[0] ? "down" : "flat";
  const stroke = color ?? (dir === "up" ? "var(--tx-up)" : dir === "down" ? "var(--tx-down)" : "var(--tx-sub)");
  return <SparkLine values={v} w={w} h={h} stroke={stroke} className="ca-spark" dir={dir} />;   // 그리는 것은 공용 스파크라인 하나(선 1.5px · 끝 점)
}

/** 내재가치 밴드 — 현재가 · 내재가치 · 모형별 값(로그 눈금). 모형 점은 범주색, 이름은 보이는 글자(툴팁 없음). */
export function ValueBand({ price, models, intrinsic }: { price: number; models: ModelResult[]; intrinsic: number }) {
  const avail = models.filter((m) => m.value > 0);
  const vals = [price, intrinsic, ...avail.map((m) => m.value)].filter((v) => v > 0);
  const lo = Math.min(...vals) * 0.94, hi = Math.max(...vals) * 1.06;
  // 로그 눈금 — RIM 등 한 모델이 매우 클 때(고ROE) 한쪽 쏠림 방지
  const llo = Math.log(lo), lspan = (Math.log(hi) - llo) || 1;
  const xp = (v: number) => Math.max(0, Math.min(100, ((Math.log(Math.max(v, 1)) - llo) / lspan) * 100));
  const x = (v: number) => `${xp(v)}%`;
  const wide = hi / lo > 4;
  return (
    <div className="ca-band">
      <div className="ca-band-track">
        <div className="ca-band-fill" style={{ left: x(Math.min(price, intrinsic)), right: `${100 - xp(Math.max(price, intrinsic))}%` }} />
        {avail.map((m, i) => (
          <div key={m.key} className="ca-band-tick" style={{ left: x(m.value) }}>
            <span className="ca-band-tick-dot" style={{ background: catColor(i) }} /><span className="ca-band-tick-lbl">{m.label} {won(m.value)}</span>
          </div>
        ))}
        <div className="ca-band-marker price" style={{ left: x(price) }}><span className="ca-band-marker-lbl">현재가<br />{won(price)}</span></div>
        <div className="ca-band-marker intrinsic" style={{ left: x(intrinsic) }}><span className="ca-band-marker-lbl up">내재가치<br />{won(intrinsic)}</span></div>
      </div>
      <div className="ca-band-axis"><span>{won(lo)}</span>{wide && <span className="ca-band-log">로그 눈금</span>}<span>{won(hi)}</span></div>
    </div>
  );
}

/** 팩터 한 줄 — 백분위 막대는 ★수준 색★(50 가운데 회색, 높으면 주황 쪽·낮으면 청록 쪽). 좋고 나쁨은 `higherBetter` 로 서버가 이미 뒤집어 둔 백분위다. */
/** 팩터 값 글자 — 단위 그대로(억은 "억원"), 음수는 U+2212. */
export function factorValue(fac: Pick<FactorVal, "value" | "unit">): string {
  const neg = fac.value < 0 ? "−" : "";
  const a = Math.abs(fac.value);
  if (fac.unit === "억") return `${neg}${eok(a)}원`;
  if (fac.unit === "원") return `${neg}${won(a)}`;
  return `${neg}${a.toLocaleString("ko-KR")}${fac.unit}`;
}
/** ★백분위를 모르면(null) 막대를 채우지 않고 "몰라요"★ — 50 을 지어내지 않는다(BU6b). */
export function FactorBar({ fac, showPct = true }: { fac: FactorVal; showPct?: boolean }) {
  return (
    <div className="ca-fbar" data-unknown={fac.pct == null ? "" : undefined}>
      <span className="ca-fbar-lbl" data-server>{fac.label}</span>
      <span className="ca-fbar-val">{factorValue(fac)}</span>
      <span className="ca-fbar-track">{fac.pct != null && <span className="ca-fbar-fill" style={{ width: `${fac.pct}%`, background: pctFill(fac.pct) }} />}</span>
      {showPct && <span className="ca-fbar-pct">{fac.pct ?? "N/A"}</span>}
    </div>
  );
}

export function Radar({ groups: all, size = 240 }: { groups: FactorGroup[]; size?: number }) {
  // 백분위를 아는 팩터만 평균(BU6b) — 하나도 모르는 묶음은 꼭짓점에서 뺀다(0 으로 그리지 않는다).
  const known = all.map((g) => ({ g, k: g.factors.map((f) => f.pct).filter((p): p is number => p != null) })).filter((x) => x.k.length);
  const groups = known.map((x) => x.g);
  const n = groups.length, cx = size / 2, cy = size / 2, R = size / 2 - 34;
  if (n < 3) return <p className="ci-note">백분위를 아는 그룹이 셋보다 적어 레이더를 그리지 않았습니다.</p>;
  const avg = known.map((x) => x.k.reduce((s, v) => s + v, 0) / x.k.length);
  const pt = (i: number, r: number) => {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  const poly = avg.map((v, i) => pt(i, (v / 100) * R).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} className="ca-radar" role="img"
         aria-label={`카테고리별 평균 백분위: ${groups.map((g, i) => `${g.label} ${Math.round(avg[i])}`).join(", ")}`}>
      {[0.25, 0.5, 0.75, 1].map((rr, k) => (
        <polygon key={k} points={groups.map((_, i) => pt(i, R * rr).join(",")).join(" ")} fill="none" stroke="var(--tx-line)" strokeWidth="1" />
      ))}
      {groups.map((_, i) => { const [x, y] = pt(i, R); return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--tx-line)" strokeWidth="1" />; })}
      <polygon points={poly} fill="var(--tx-blue-soft)" fillOpacity={0.6} stroke="var(--tx-blue)" strokeWidth="1.6" />
      {avg.map((v, i) => { const [x, y] = pt(i, (v / 100) * R); return <circle key={i} cx={x} cy={y} r="2.6" fill="var(--tx-blue)" />; })}
      {groups.map((g, i) => { const [x, y] = pt(i, R + 16); return <text key={i} x={x} y={y} textAnchor="middle" className="ca-radar-lbl">{g.label.split("·")[0]}</text>; })}
    </svg>
  );
}

/** 낙관·기준·보수 — 가정만 바꿔 우리 엔진으로 다시 계산한 값. 현재가 대비 차이는 판단이라 색 없이 부호로. */
export function ScenarioCards({ scenarios }: { scenarios: Scenario[]; price: number }) {
  return (
    <div className="ca-scen">
      {scenarios.map((s) => (
        <div key={s.key} className={`ca-scen-card ${s.key}`}>
          <div className="ca-scen-head">{s.label}</div>
          <div className="ca-scen-val">{won(s.value)}</div>
          <div className="ca-scen-gap">현재가 대비 {pct(s.gap)}</div>
          <div className="ca-scen-note">{s.note}</div>
        </div>
      ))}
    </div>
  );
}

export function Metric({ label, value, sub, color }: { label: string; value: React.ReactNode; sub?: React.ReactNode; color?: string }) {
  return (
    <div className="ca-metric">
      <span className="ca-metric-lbl">{label}</span>
      <span className="ca-metric-val" style={color ? { color } : undefined}>{value}</span>
      {sub != null && <span className="ca-metric-sub">{sub}</span>}
    </div>
  );
}

export { won, eok, pct };
