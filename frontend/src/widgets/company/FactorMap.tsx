"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 팩터로 본 위치(BU6b · 사용자 결정 "백분위 점 지도 + 목록은 펼침")
// ─────────────────────────────────────────────────────────────────────────────
// ★백분위 점 지도★ 묶음마다 한 줄, 0~100 가로 축, 팩터마다 점 하나(수준 색 `pctFill` — 50 이 가운데 회색). 점에 올리거나 초점을 두면
//   아래 읽기 줄(aria-live)이 "이름: 값, 백분위 n" 을 말한다 — 툴팁이 아니라 보이는 글자. ←→ 로 점을 옮긴다(로빙 tabindex).
// 위에 강한 점·약한 점 칩(누르면 그 점으로) · 레이더(묶음 평균)와 묶음 평균 막대(수준 색)는 그대로 · 팩터별 막대 목록은 펼침 안(잘림 없이).
// ★백분위는 비교 표본에서만★ 표본을 불러오지 못하면 alert + 다시 시도, 표본이 5개 미만이면 사유 — 옛 코드는 둘 다 50 을 지어냈다.
// 백분위는 "업종"이 아니라 비교 표본(적재 스냅샷 또는 코스피 200) 안 위치다 — 표본의 출처와 크기를 말한다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useRef, useState } from "react";
import type { CompanyData, FactorGroup, FactorVal } from "@/entities/company/insightsModel";
import { RetryFail } from "@/shared/ui/tx";
import { UNKNOWN_TEXT } from "@/shared/lib/krFormat";
import { pctFill } from "@/shared/ui/vizColor";
import { FactorBar, Radar, factorValue } from "./parts";

type Dot = FactorVal & { group: string; lane: number; idx: number };

/** 묶음 평균 백분위 — 아는 것만. 하나도 모르면 null. */
export const groupAvg = (g: FactorGroup): number | null => {
  const k = g.factors.map((f) => f.pct).filter((p): p is number => p != null);
  return k.length ? Math.round(k.reduce((s, x) => s + x, 0) / k.length) : null;
};

/** 같은 줄에서 가까운 점(4 백분위 안)을 위아래로 비켜 겹치지 않게 한다. */
function lanes(fs: FactorVal[]): Map<string, number> {
  const out = new Map<string, number>();
  const placed: { p: number; lane: number }[] = [];
  for (const f of [...fs].filter((x) => x.pct != null).sort((a, b) => (a.pct as number) - (b.pct as number))) {
    let lane = 0;
    while (placed.some((q) => q.lane === lane && Math.abs(q.p - (f.pct as number)) < 4)) lane++;
    placed.push({ p: f.pct as number, lane });
    out.set(f.id, lane);
  }
  return out;
}

const readText = (d: Dot) => `${d.label}: ${factorValue(d)}, 백분위 ${d.pct}`;

export function FactorDotMap({ groups, strengths, weaknesses }: { groups: FactorGroup[]; strengths: FactorVal[]; weaknesses: FactorVal[] }) {
  const { rows, dots } = useMemo(() => {
    const all: Dot[] = [];
    const rows = groups.map((g) => {
      const ln = lanes(g.factors);
      const ds = g.factors.filter((f) => f.pct != null)
        .sort((a, b) => (a.pct as number) - (b.pct as number))
        .map((f) => { const d: Dot = { ...f, group: g.label, lane: ln.get(f.id) ?? 0, idx: all.length }; all.push(d); return d; });
      return { g, ds, h: Math.max(...ds.map((d) => d.lane), 0) + 1 };
    });
    return { rows, dots: all };
  }, [groups]);
  const [cur, setCur] = useState<number | null>(null);
  const btns = useRef<(HTMLButtonElement | null)[]>([]);
  const go = (i: number) => { const j = Math.max(0, Math.min(dots.length - 1, i)); setCur(j); btns.current[j]?.focus(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (cur == null) return;
    const k = e.key;
    if (k === "ArrowRight" || k === "ArrowDown") { e.preventDefault(); go(cur + 1); }
    else if (k === "ArrowLeft" || k === "ArrowUp") { e.preventDefault(); go(cur - 1); }
    else if (k === "Home") { e.preventDefault(); go(0); }
    else if (k === "End") { e.preventDefault(); go(dots.length - 1); }
  };
  const byId = (id: string) => dots.find((d) => d.id === id);
  const chip = (f: FactorVal) => { const d = byId(f.id); return d ? (
    <li key={f.id}><button type="button" className="ci-fmap-chip" onClick={() => go(d.idx)}>{f.label} <b>{f.pct}</b></button></li>) : null; };
  const active = cur != null ? dots[cur] : null;
  return (
    <div className="ci-fmap">
      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="ci-fmap-chips">
          {strengths.length > 0 && <div><span className="ci-fmap-chips-k">백분위가 높은 팩터</span><ul>{strengths.map(chip)}</ul></div>}
          {weaknesses.length > 0 && <div><span className="ci-fmap-chips-k">백분위가 낮은 팩터</span><ul>{weaknesses.map(chip)}</ul></div>}
        </div>
      )}
      <div className="ci-fmap-grid" role="group" aria-label={`팩터 ${dots.length}개의 백분위 위치. 화살표 키로 옮겨 다녀요`} onKeyDown={onKey}>
        {rows.map(({ g, ds, h }) => (
          <div key={g.id} className="ci-fmap-row" data-group={g.id}>
            <span className="ci-fmap-name" data-server>{g.label}</span>
            <span className="ci-fmap-track" style={{ "--lanes": h } as React.CSSProperties}>
              <i className="ci-fmap-mid" aria-hidden />
              {ds.map((d) => (
                <button key={d.id} type="button" ref={(el) => { btns.current[d.idx] = el; }}
                        className="ci-fmap-dot" data-pct={d.pct} data-name={d.label} data-on={cur === d.idx ? "" : undefined}
                        tabIndex={(cur ?? 0) === d.idx ? 0 : -1} aria-label={readText(d)}
                        style={{ left: `${d.pct}%`, "--lane": d.lane, background: pctFill(d.pct) } as React.CSSProperties}
                        onFocus={() => setCur(d.idx)} onMouseEnter={() => setCur(d.idx)} onClick={() => setCur(d.idx)} />
              ))}
              {!ds.length && <span className="ci-fmap-none">이 묶음은 백분위를 아는 팩터가 없어요</span>}
            </span>
          </div>
        ))}
        <div className="ci-fmap-axis" aria-hidden><span /><span className="ci-fmap-ticks"><em>0</em><em>50 가운데</em><em>100</em></span></div>
      </div>
      <p className="ci-fmap-read" aria-live="polite">
        {active ? <><b>{active.label}</b> <span>{factorValue(active)}</span> <span className="ci-fmap-read-p">백분위 {active.pct}</span> <span className="ci-fmap-read-g">{active.group}</span></>
          : "점에 올리거나 초점을 두면 그 팩터의 값과 백분위를 여기에 보여 줘요."}
      </p>
    </div>
  );
}

export function FactorsSection({ c, onRetry }: { c: CompanyData; onRetry: () => void }) {
  const groups = [...c.fundamentals, ...c.priceFactors];
  const nF = (gs: FactorGroup[]) => gs.reduce((s, g) => s + g.factors.length, 0);
  if (c.failed.includes("factors")) return <div className="ca-cp-pad"><RetryFail title="팩터 목록을 불러오지 못했어요" onRetry={onRetry} /></div>;
  if (!groups.length) return <div className="ca-cp-pad"><p className="ca-cp-empty">이 종목은 값을 아는 팩터가 없어요.</p></div>;
  const b = c.factorBasis;
  const sampleFail = c.failed.includes("factorSample");
  const known = groups.some((g) => g.factors.some((f) => f.pct != null));
  return (
    <div className="ca-cp-pad">
      {sampleFail ? <RetryFail title="비교할 종목 표본을 불러오지 못해 백분위를 재지 못했어요" onRetry={onRetry}>팩터 값은 아래 목록에 그대로 있어요. 백분위만 비어 있어요.</RetryFail>
        : b && !known ? <p className="ci-fmap-reason">비교할 종목이 {b.n}개뿐이라 백분위를 재지 않았어요(5개 이상 필요해요). 팩터 값은 아래 목록에 있어요.</p>
        : b ? <p className="ci-sec-lede">{b.source === "db" ? `적재된 종목 ${b.n.toLocaleString("ko-KR")}개` : `코스피 200 종목 ${b.n.toLocaleString("ko-KR")}개`}와 견준 백분위예요. 높을수록 그 팩터에서 좋은 쪽이에요(낮을수록 좋은 팩터는 뒤집어 셌어요).</p>
        : null}
      {known && <FactorDotMap groups={groups} strengths={c.strengths} weaknesses={c.weaknesses} />}
      <div className="ca-cp-factop">
        <div className="ca-cp-card"><div className="ca-cp-card-h">묶음 평균 백분위</div><div className="ca-cp-radar"><Radar groups={groups} size={260} /></div></div>
        <div className="ca-cp-card">
          <div className="ca-cp-card-h">묶음 평균: 재무 {nF(c.fundamentals)}개, 가격·수급 {nF(c.priceFactors)}개</div>
          <div className="ca-cp-catbars">
            {groups.map((g) => { const avg = groupAvg(g); return (
              <div key={g.id} className="ca-cp-catbar" data-unknown={avg == null ? "" : undefined}>
                <span data-server>{g.label}</span>
                <i>{avg != null && <b style={{ width: `${avg}%`, background: pctFill(avg) }} />}</i>
                <em>{avg ?? UNKNOWN_TEXT}</em>
              </div>
            ); })}
          </div>
        </div>
      </div>
      <details className="ci-fac-more">
        <summary>팩터 {nF(groups)}개 값과 백분위 모두 보기</summary>
        <div className="ca-cp-facgrid">
          {groups.map((g) => (
            <div key={g.id} className="ca-cp-facgroup">
              <div className="ca-cp-facgroup-h"><span data-server>{g.label}</span><span>{g.factors.length}개</span></div>
              {g.factors.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
