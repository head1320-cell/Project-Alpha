"use client";
/**
 * 노드 카드 안 작은 그림 (BM C1 · Enso 의 살아 있는 미리보기 · TouchDesigner 의 뷰어 플래그)
 * ==========================================================================
 * ★그리기만 한다★ — 점과 값은 서버 `glance`(보기에서 고른 수 그대로)다. 화면은 순서·값을 바꾸지 않는다.
 * ★모르는 값은 모른다고★ — `null` 점은 막대를 그리지 않고 "모름", 선은 그 구간을 끊는다(0 으로 잇지 않는다).
 * 카드 폭(138px)에 맞춘 네 모양: 막대(비중·기여) · 선(곡선) · 분포(히스토그램) · 값 목록.
 */
import { fmtGlance, type NodeGlance } from "@/entities/portfolio-graph";

const W = 138;
const H = 40;
const MAX_ROWS = 5;

function Bars({ g }: { g: NodeGlance }) {
  const rows = g.points.slice(0, MAX_ROWS);
  const more = g.points.length - rows.length;
  const max = Math.max(...g.points.map((p) => (p.value === null ? 0 : Math.abs(p.value))), 0) || 1;
  return (
    <ul className="pg-gl-bars">
      {rows.map((p, i) => (
        <li key={`${p.label}-${i}`} className={p.value === null ? "pg-gl-unknown" : p.value < 0 ? "pg-gl-neg" : undefined}>
          <span className="pg-gl-lab" title={p.label}>{p.label}</span>
          <span className="pg-gl-track" aria-hidden="true">
            {p.value !== null && <i style={{ width: `${Math.max(2, (Math.abs(p.value) / max) * 100)}%` }} />}
          </span>
          <span className="pg-gl-val">{fmtGlance(p.value, g.unit)}</span>
        </li>
      ))}
      {more > 0 && <li className="pg-gl-more">그림 밖 {more}개</li>}
    </ul>
  );
}

/** 선 — null 에서 끊는다. 양 끝 값을 글로도 적는다(그림만으로 읽지 않게). */
function Line({ g }: { g: NodeGlance }) {
  const vals = g.points.map((p) => p.value);
  const known = vals.filter((v): v is number => v !== null);
  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const span = hi - lo || 1;
  const x = (i: number) => (g.points.length === 1 ? W / 2 : (i / (g.points.length - 1)) * (W - 4) + 2);
  const y = (v: number) => H - 3 - ((v - lo) / span) * (H - 6);
  const segs: string[] = [];
  let cur: string[] = [];
  vals.forEach((v, i) => {
    if (v === null) { if (cur.length) segs.push(cur.join(" ")); cur = []; return; }
    cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  });
  if (cur.length) segs.push(cur.join(" "));
  const first = g.points[0];
  const last = g.points[g.points.length - 1];
  const gaps = vals.some((v) => v === null);
  return (
    <>
      <svg className="pg-gl-svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
           aria-label={`${g.caption ?? "곡선"} — 처음 ${fmtGlance(first.value, g.unit)}, 끝 ${fmtGlance(last.value, g.unit)}`}>
        {segs.map((pts, i) => (pts.includes(" ")
          ? <polyline key={i} points={pts} fill="none" />
          : <circle key={i} cx={pts.split(",")[0]} cy={pts.split(",")[1]} r={1.6} />))}
      </svg>
      <div className="pg-gl-ends">
        <span title={first.label}>{fmtGlance(first.value, g.unit)}</span>
        <span title={last.label}>{fmtGlance(last.value, g.unit)}</span>
      </div>
      {gaps && <div className="pg-gl-note">끊긴 곳은 값을 몰라요</div>}
    </>
  );
}

function Hist({ g }: { g: NodeGlance }) {
  const max = Math.max(...g.points.map((p) => p.value ?? 0), 0) || 1;
  const bw = W / g.points.length;
  const first = g.points[0];
  const last = g.points[g.points.length - 1];
  return (
    <>
      <svg className="pg-gl-svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
           aria-label={`${g.caption ?? "분포"} — ${first.label}부터 ${last.label}까지`}>
        {g.points.map((p, i) => (p.value === null ? null : (
          <rect key={i} x={i * bw + 0.5} width={Math.max(1, bw - 1)} y={H - (p.value / max) * (H - 2)} height={(p.value / max) * (H - 2)} />
        )))}
      </svg>
      <div className="pg-gl-ends"><span>{first.label}</span><span>{last.label}</span></div>
    </>
  );
}

function Values({ g }: { g: NodeGlance }) {
  return (
    <dl className="pg-gl-values">
      {g.points.slice(0, MAX_ROWS).map((p, i) => (
        <div key={`${p.label}-${i}`} className={p.value === null ? "pg-gl-unknown" : undefined}>
          <dt>{p.label}</dt><dd>{fmtGlance(p.value, g.unit)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Glance({ glance }: { glance: NodeGlance }) {
  return (
    <figure className={`pg-glance pg-glance--${glance.kind}`} data-glance={glance.kind}>
      {glance.caption && <figcaption className="pg-gl-cap">{glance.caption}</figcaption>}
      {glance.kind === "bars" && <Bars g={glance} />}
      {glance.kind === "line" && <Line g={glance} />}
      {glance.kind === "hist" && <Hist g={glance} />}
      {glance.kind === "values" && <Values g={glance} />}
    </figure>
  );
}
