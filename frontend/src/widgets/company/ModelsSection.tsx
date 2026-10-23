"use client";
// 여러 모형(BU6a+) — 백엔드에 이미 있던 가치 모형 여덟을 카드로. 카드마다: 한 줄 답(서버 값) · 그림 · 가정·출처 칩 · 입력 표(접힘).
// 상태는 넷을 가른다: 계산하는 중 · ★실패 = 그 카드 alert + 다시 시도★ · 서버가 못 함(available:false) = 사유 · 값.
// 가정형 셋(의사결정 나무·SOTP·실물옵션)은 돌리지 않는다 — 넣어야 할 것을 말하고 캔버스로 보낸다(기본값이 회사와 무관한 숫자라서).
// 색: 판단 색 없음(중립 한 색 + 글자) · 가치 변화(매크로 민감도)만 등락색 + 부호.
import React from "react";
import Link from "next/link";
import type { UseQueryResult } from "@tanstack/react-query";
import { Chips, RetryFail, type Chip } from "@/shared/ui/tx";
import { priceWon } from "@/shared/lib/krFormat";
import type { ModelHead, ModelInput, Quant } from "@/entities/company/modelsApi";
import type { CompanyModels } from "./useModels";

const fin = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const p1 = (x: number) => `${x.toFixed(1)}%`;
const pr = (x: number) => `${(x * 100).toFixed(1)}%`;
const jo = (won: number) => `${(won / 1e12).toFixed(1)}조원`;
const clean = (s?: string | null) => (s ?? "").replace(/\*\*/g, "");

/** 카드 하나 — 네 상태를 가른다. `body` 는 값이 있을 때만 부른다. */
function MCard<T extends ModelHead>({ id, title, what, q, chips, body }: {
  id: string; title: string; what: string; q: UseQueryResult<T>;
  chips?: (d: T) => Chip[]; body: (d: T) => React.ReactNode;
}) {
  const d = q.data;
  const ch: Chip[] = d && d.available !== false ? [...(d.is_mock ? [{ label: "연습용 재무", tone: "practice" as const }] : []), ...(chips ? chips(d) : [])] : [];
  return (
    <article className="ci-mcard" data-model={id} aria-busy={q.isFetching}>
      <header className="ci-mcard-h"><h3>{title}</h3><p>{what}</p></header>
      {q.isPending && !q.isError ? <p className="ci-mcard-wait">계산하는 중이에요</p>
        : q.isError ? <RetryFail title={`${title}을(를) 불러오지 못했어요`} onRetry={() => void q.refetch()} />
        : d && d.available === false ? <p className="ci-mcard-reason"><span className="ci-mcard-reason-k">이 종목에는 계산하지 못했어요.</span> <span data-server>{clean(d.reason) || "서버가 사유를 주지 않았어요"}</span></p>
        : d ? <>{body(d)}{ch.length > 0 && <Chips items={ch} label={`${title} 근거`} />}</> : null}
    </article>
  );
}

/** 입력·가정 표 — 서버 `inputs[]` 그대로(basis = 관측·근사·가정·미상). 접어 둔다. */
function Inputs({ rows }: { rows?: ModelInput[] }) {
  if (!rows?.length) return null;
  const show = (v: unknown) => (typeof v === "number" ? (Math.abs(v) < 1 ? pr(v) : v.toLocaleString("ko-KR", { maximumFractionDigits: 2 })) : Array.isArray(v) ? v.join(", ") : String(v ?? ""));
  return (
    <details className="ci-mcard-more">
      <summary>쓴 값과 출처 {rows.length}개</summary>
      <table className="ci-mtable"><tbody>
        {rows.map((r) => (
          <tr key={r.key}><th scope="row">{r.label}</th><td data-server>{show(r.value)}{r.unit && typeof r.value === "number" && Math.abs(r.value) >= 1 ? r.unit : ""}</td>
            <td><span className="ci-basis" data-basis={r.basis}>{r.basis ?? "미상"}</span></td><td className="ci-mtable-src" data-server>{r.source}</td></tr>
        ))}
      </tbody></table>
    </details>
  );
}

/** 분위 띠 한 줄(10~90 옅게 · 25~75 진하게 · 중앙선) + 현재가 선. */
function QRow({ label, q, lo, hi, price }: { label: string; q: Quant; lo: number; hi: number; price: number }) {
  const at = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo || 1)) * 100)).toFixed(2)}%`;
  const ok = fin(q.p10) && fin(q.p90);
  return (
    <div className="ci-q-row">
      <span className="ci-q-name">{label}</span>
      <span className="ci-q-track">
        {ok ? (
          <>
            <i className="ci-q-out" style={{ left: at(q.p10!), width: `calc(${at(q.p90!)} - ${at(q.p10!)})` }} />
            {fin(q.p25) && fin(q.p75) && <i className="ci-q-in" style={{ left: at(q.p25), width: `calc(${at(q.p75)} - ${at(q.p25)})` }} />}
            {fin(q.p50) && <i className="ci-q-mid" style={{ left: at(q.p50) }} />}
          </>
        ) : <em className="ci-q-na">분포 없음</em>}
        <i className="ci-q-price" style={{ left: at(price) }} aria-hidden />
      </span>
      <span className="ci-q-val">{fin(q.p50) ? priceWon(q.p50) : "값 없음"}</span>
    </div>
  );
}

/** 막대 히스토그램(영업 동인) — 10~90% 구간 진하게, 현재가 선. */
function Histo({ counts, edges, price, q }: { counts: number[]; edges: number[]; price: number; q: Quant }) {
  const lo = edges[0], hi = edges[edges.length - 1], mx = Math.max(1, ...counts);
  const at = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo || 1)) * 100)).toFixed(2)}%`;
  const inMid = (i: number) => fin(q.p10) && fin(q.p90) && edges[i + 1] > q.p10! && edges[i] < q.p90!;
  return (
    <div className="ci-histo" role="img" aria-label={`주당 가치 분포: 10% ${priceWon(q.p10 ?? null)} · 중앙 ${priceWon(q.p50 ?? null)} · 90% ${priceWon(q.p90 ?? null)} · 현재가 ${priceWon(price)}`}>
      <div className="ci-histo-bars">
        {counts.map((c, i) => <i key={i} className={inMid(i) ? "mid" : ""} style={{ height: `${(c / mx) * 100}%` }} />)}
        {price >= lo && price <= hi && <b className="ci-histo-price" style={{ left: at(price) }} aria-hidden />}
      </div>
      <div className="ci-histo-axis"><span>{priceWon(Math.round(lo))}</span><span>{priceWon(Math.round(hi))}</span></div>
      {(price < lo || price > hi) && <p className="ci-note">현재가 {priceWon(price)}는 이 분포 범위 밖이에요.</p>}
    </div>
  );
}

/** 같은 축 막대 — 값이 클수록 길다(중립 한 색). */
function HBars({ rows, unit }: { rows: { k: string; v: number | null; note?: string }[]; unit: (v: number) => string }) {
  const mx = Math.max(1e-9, ...rows.map((r) => (fin(r.v) ? Math.abs(r.v) : 0)));
  return (
    <div className="ci-hbars">
      {rows.map((r) => (
        <div key={r.k} className="ci-hbar">
          <span className="ci-hbar-k">{r.k}</span>
          <span className="ci-hbar-t"><i style={{ width: `${fin(r.v) ? (Math.abs(r.v) / mx) * 100 : 0}%` }} /></span>
          <span className="ci-hbar-v">{fin(r.v) ? unit(r.v) : (r.note ?? "값 없음")}</span>
        </div>
      ))}
    </div>
  );
}

export function ModelsSection({ m, price, pbr, code }: { m: CompanyModels; price: number; pbr: number | null; code: string }) {
  return (
    <>
      <p className="ci-sec-lede">백엔드의 가치 모형 여덟 가지로 같은 종목을 다른 각도에서 쟀어요. 모형마다 쓴 값과 출처를 함께 적었어요.</p>
      <div className="ci-mgrid">
        <MCard id="rdcf" title="역DCF" what="지금 주가가 미래에 대해 무엇을 가정하는지 거꾸로 풀어요." q={m.rdcf}
          chips={() => [{ label: "성장률이 일정하다고 가정했어요", tone: "assumed" }]}
          body={(d) => (
            <>
              <p className="ci-mcard-ans">
                {fin(d.implied_growth_pct)
                  ? <>지금 주가 {priceWon(price)}은 현금흐름이 해마다 {p1(d.implied_growth_pct)}씩 는다는 가정과 같아요.{fin(d.current_growth_pct) ? <> 지금까지는 {p1(d.current_growth_pct)}였어요.</> : null}</>
                  : <>시장이 가정한 성장률을 풀지 못했어요.</>}
              </p>
              <HBars unit={p1} rows={[
                { k: "시장이 가정한 성장률", v: d.implied_growth_pct },
                { k: "지금까지의 성장률", v: d.current_growth_pct, note: d.current_growth_reason ? "재지 못했어요" : undefined },
              ]} />
              <dl className="ci-mdl">
                {fin(d.wacc_pct) && <div><dt>할인율(WACC)</dt><dd>{p1(d.wacc_pct)}</dd></div>}
                {fin(d.base_dcf_price) && <div><dt>기본 가정의 DCF 값</dt><dd>{priceWon(d.base_dcf_price)}</dd></div>}
              </dl>
              {d.current_growth_reason && <p className="ci-note" data-server>{clean(d.current_growth_reason)}</p>}
            </>
          )} />

        <MCard id="dist" title="가치 분포" what="할인율·성장률 가정을 흔들어 적정가가 어디쯤 모이는지 봐요." q={m.dist}
          chips={(d) => (Object.values(d.widths ?? {}).some((w) => typeof w === "object" && w.measured === false)
            ? [{ label: "흔든 폭은 잰 값이 아니라 정한 값이에요", tone: "assumed" }] : [])}
          body={(d) => {
            const qs: [string, Quant][] = [["합친 분포", d.unified], ...Object.entries(d.by_model ?? {})];
            const xs = qs.flatMap(([, q]) => [q.p10, q.p90]).filter(fin).concat(price);
            const lo = Math.min(...xs) * 0.95, hi = Math.max(...xs) * 1.05;
            const pp = d.unified?.price_percentile;
            return (
              <>
                <p className="ci-mcard-ans">
                  {fin(pp) ? <>현재가는 가정을 흔든 적정가 분포의 {Math.round(pp)}번째 백분위예요.</> : <>현재가의 백분위를 내지 못했어요.</>}
                  {fin(d.unified?.p50) && <> 가운데 값은 {priceWon(d.unified.p50)}이에요.</>}
                </p>
                <div className="ci-q" role="img" aria-label={`적정가 분포 10% ${priceWon(d.unified?.p10 ?? null)}, 중앙 ${priceWon(d.unified?.p50 ?? null)}, 90% ${priceWon(d.unified?.p90 ?? null)}`}>
                  {qs.map(([k, q]) => <QRow key={k} label={k} q={q} lo={lo} hi={hi} price={price} />)}
                </div>
                <p className="ci-legend"><i className="ci-sw out" />10~90% <i className="ci-sw in" />25~75% <i className="ci-sw mid" />가운데 <i className="ci-sw price" />현재가</p>
                {fin(d.model_disagreement?.spread_ratio) && <p className="ci-note">같은 가정에서 모형끼리 {d.model_disagreement!.spread_ratio!.toFixed(2)}배 갈렸어요.</p>}
              </>
            );
          }} />

        <MCard id="driver" title="영업 동인 흔들기" what="매출 성장·마진·재투자를 흔들어 주당 가치가 어떻게 퍼지는지 봐요." q={m.driver}
          chips={() => [{ label: "흔든 폭은 정한 값이에요", tone: "assumed" }]}
          body={(d) => (
            <>
              <p className="ci-mcard-ans">
                {fin(d.quantiles?.p50) ? <>주당 가치의 가운데 값은 {priceWon(d.quantiles.p50)}이에요.</> : <>가운데 값을 내지 못했어요.</>}
                {fin(d.price_percentile) && <> 현재가는 {Math.round(d.price_percentile)}번째 백분위예요.</>}
              </p>
              {d.histogram && d.histogram.counts.length > 0 && <Histo counts={d.histogram.counts} edges={d.histogram.edges} price={price} q={d.quantiles} />}
              {fin(d.negative_share) && d.negative_share > 0 && <p className="ci-note">경로의 {pr(d.negative_share)}는 주당 가치가 0 아래였어요(부채가 기업가치보다 커요).</p>}
              <Inputs rows={d.inputs} />
            </>
          )} />

        <MCard id="layers" title="가치의 층" what="자산 → 지금 이익을 유지하는 힘 → 성장까지, 가치를 층으로 나눠요." q={m.layers}
          body={(d) => {
            const L = Object.fromEntries((d.layers ?? []).map((x) => [x.key, x]));
            return (
              <>
                <p className="ci-mcard-ans">
                  자산 {priceWon(L.asset?.per_share ?? null)} · 수익력 {priceWon(L.epv?.per_share ?? null)} · 성장까지 {priceWon(d.full_per_share)}이에요.
                </p>
                <HBars unit={(v) => priceWon(v)} rows={[
                  { k: "자산가치", v: L.asset?.per_share ?? null, note: L.asset?.reason ? "재지 못했어요" : undefined },
                  { k: "수익력가치", v: L.epv?.per_share ?? null, note: L.epv?.reason ? "재지 못했어요" : undefined },
                  { k: "성장까지", v: d.full_per_share },
                  { k: "현재가", v: price },
                ]} />
                {d.franchise && <p className="ci-note" data-server>{d.franchise}</p>}
                <Inputs rows={d.inputs} />
              </>
            );
          }} />

        <MCard id="eva" title="EVA(경제적 부가가치)" what="번 돈이 자본비용을 넘었는지 해마다 봐요." q={m.eva}
          body={(d) => {
            const ys = (d.years ?? []).filter((y) => y.available && fin(y.eva));
            const mx = Math.max(1, ...ys.map((y) => Math.abs(y.eva as number)));
            const last = d.latest;
            return (
              <>
                <p className="ci-mcard-ans">
                  {last && fin(last.roic) && fin(last.wacc)
                    ? <>{last.year}년 투하자본이익률(ROIC) {pr(last.roic)}, 자본비용(WACC) {pr(last.wacc)}: ROIC 가 WACC 보다 {last.roic < last.wacc ? "낮아요" : "높아요"}.</>
                    : <>최근 연도의 ROIC·WACC 를 내지 못했어요.</>}
                  {fin(d.valuation?.per_share) && <> EVA 로 잰 주당 가치는 {priceWon(d.valuation!.per_share)}이에요.</>}
                </p>
                <div className="ci-eva" role="img" aria-label={`연도별 EVA: ${ys.map((y) => `${y.year} ${jo(y.eva as number)}`).join(", ")}`}>
                  {ys.map((y) => (
                    <div key={y.year} className="ci-eva-col">
                      <span className="ci-eva-plot">
                        <i className={(y.eva as number) < 0 ? "neg" : "pos"} style={{ height: `${(Math.abs(y.eva as number) / mx) * 50}%` }} />
                      </span>
                      <span className="ci-eva-v">{(y.eva as number) < 0 ? "−" : "+"}{jo(Math.abs(y.eva as number))}</span>
                      <span className="ci-eva-y">{y.year}</span>
                    </div>
                  ))}
                </div>
                <p className="ci-note">막대는 0 기준 위(+)·아래(−)예요. 색으로 좋고 나쁨을 말하지 않아요.</p>
                <Inputs rows={d.inputs} />
              </>
            );
          }} />

        <MCard id="multiples" title="배수로 보기" what="실제 PER·PBR 을 이익·성장으로 정당화되는 배수, 같은 업종과 나란히 놓아요." q={m.multiples}
          body={(d) => {
            const j = d.justified;
            const strip = (label: string, pts: { k: string; v: number | null }[]) => {
              const ok = pts.filter((p) => fin(p.v)) as { k: string; v: number }[];
              if (!ok.length) return null;
              const hi = Math.max(...ok.map((p) => p.v)) * 1.15;
              return (
                <div className="ci-strip">
                  <span className="ci-strip-k">{label}</span>
                  <span className="ci-strip-t">
                    {ok.map((p, i) => <i key={p.k} className={`ci-strip-dot s${i}`} style={{ left: `${(p.v / hi) * 100}%` }} aria-hidden />)}
                  </span>
                  <span className="ci-strip-v">{ok.map((p, i) => <em key={p.k} className={`s${i}`}>{p.k} {p.v.toFixed(2)}배</em>)}</span>
                </div>
              );
            };
            return (
              <>
                <p className="ci-mcard-ans">
                  {fin(d.per) && fin(j?.per) ? <>실제 PER {d.per.toFixed(2)}배, 이익과 성장으로 정당화되는 PER {j!.per!.toFixed(2)}배예요.</> : <>정당 PER 을 내지 못했어요.</>}
                  {fin(d.peg) ? <> PEG(PER÷성장률)는 {d.peg.toFixed(2)}예요.</> : d.peg_reason ? <> PEG 는 내지 못했어요.</> : null}
                </p>
                {strip("PER", [{ k: "실제", v: d.per }, { k: "정당", v: j?.per ?? null }, { k: "업종 중앙", v: d.peer?.per_median ?? null }])}
                {strip("PBR", [{ k: "실제", v: pbr }, { k: "정당", v: j?.pbr ?? null }])}
                <dl className="ci-mdl">
                  {fin(j?.per_price) && <div><dt>정당 PER 로 본 가격</dt><dd>{priceWon(j!.per_price)}</dd></div>}
                  {fin(j?.pbr_price) && <div><dt>정당 PBR 로 본 가격</dt><dd>{priceWon(j!.pbr_price)}</dd></div>}
                  {fin(d.peer?.per_price) && <div><dt>업종 PER 중앙값으로 본 가격</dt><dd>{priceWon(d.peer!.per_price)}</dd></div>}
                </dl>
                {d.peg_reason && <p className="ci-note" data-server>{clean(d.peg_reason)}</p>}
                <Inputs rows={d.inputs} />
              </>
            );
          }} />

        <MCard id="scenarios" title="시나리오 가중" what="약세·기본·강세마다 가정을 바꾸고 확률로 묶어요." q={m.scenarios}
          chips={() => [{ label: "확률과 경우별 가정은 사람이 정한 값이에요", tone: "assumed" }]}
          body={(d) => {
            const mx = Math.max(1, ...d.rows.map((r) => (fin(r.value) ? r.value : 0)), price);
            return (
              <>
                <p className="ci-mcard-ans">
                  {fin(d.weighted) ? <>확률로 묶은 적정가는 {priceWon(d.weighted)}이에요.</> : <>확률로 묶은 값을 내지 못했어요.</>}
                  {fin(d.prob_above_price) && <> 현재가보다 높을 확률은 {Math.round(d.prob_above_price * 100)}%예요.</>}
                </p>
                <div className="ci-scen">
                  {d.rows.map((r) => (
                    <div key={r.name} className="ci-scen-row">
                      <span className="ci-scen-k" data-server>{r.name}</span>
                      <span className="ci-scen-p">{Math.round(r.prob * 100)}%</span>
                      <span className="ci-scen-t"><i style={{ width: `${fin(r.value) ? (r.value / mx) * 100 : 0}%`, opacity: 0.35 + r.prob }} />
                        <b className="ci-scen-price" style={{ left: `${(price / mx) * 100}%` }} aria-hidden /></span>
                      <span className="ci-scen-v">{fin(r.value) ? priceWon(r.value) : "값 없음"}</span>
                    </div>
                  ))}
                </div>
                <p className="ci-note">막대가 짙을수록 확률이 커요 · 세로선은 현재가예요.</p>
              </>
            );
          }} />

        <article className="ci-mcard ci-mneed" data-model="need">
          <header className="ci-mcard-h"><h3>가정을 넣어야 하는 모형</h3><p>회사마다 다른 값을 사람이 넣어야 의미가 있어서 여기서는 계산하지 않아요.</p></header>
          <ul>
            <li><b>합산가치(SOTP)</b> 사업 부문의 이익과 배수, 상장 자회사 지분</li>
            <li><b>의사결정 나무</b> 갈리는 사건마다 확률과 그때의 주당 가치</li>
            <li><b>실물옵션</b> 사업의 현재 가치, 투자 금액, 기간, 변동성</li>
          </ul>
          <Link className="tx-btn tx-btn--sub ci-mneed-go" href={`/allocation?company=${code}`}>캔버스에서 넣기</Link>
        </article>
      </div>
    </>
  );
}

/** 매크로 민감도(위험 절) — 충격마다 가치 변화(등락색 + 부호) · 못 잰 충격은 사유 목록. */
export function MacroBlock({ q }: { q: UseQueryResult<import("@/entities/company/modelsApi").MacroSensitivity> }) {
  const d = q.data;
  return (
    <div className="ci-block ci-macro">
      <h3 className="ci-block-h">경제 충격에 가치가 얼마나 흔들리나</h3>
      {q.isPending && !q.isError ? <p className="ci-mcard-wait">계산하는 중이에요</p>
        : q.isError ? <RetryFail title="매크로 민감도를 불러오지 못했어요" onRetry={() => void q.refetch()} />
        : d && d.available === false ? <p className="ci-mcard-reason" data-server>{clean(d.reason)}</p>
        : d ? (() => {
          const rows = d.rows.filter((r) => r.available && fin(r.value_pct));
          const mx = Math.max(1, ...rows.map((r) => Math.abs(r.value_pct as number)));
          return (
            <>
              <p className="ci-mcard-ans">
                {fin(d.base_value) ? <>기준 적정가 {priceWon(d.base_value)}에서 </> : null}
                {rows.map((r, i) => <React.Fragment key={r.shock}>{i ? ", " : ""}<span data-server>{r.shock}</span> 충격이면 {(r.value_pct as number) >= 0 ? "+" : "−"}{Math.abs(r.value_pct as number).toFixed(1)}%</React.Fragment>)}
                {rows.length ? " 움직여요." : "잴 수 있는 충격이 없어요."}
              </p>
              <div className="ci-tornado">
                {rows.map((r) => {
                  const v = r.value_pct as number, dir = v >= 0 ? "up" : "down";
                  return (
                    <div key={r.shock} className="ci-torn-row">
                      <span className="ci-torn-k" data-server>{r.shock}</span>
                      <span className="ci-torn-t">
                        <i className="ci-macro-bar" data-dir={dir} style={dir === "up" ? { left: "50%", width: `${(Math.abs(v) / mx) * 50}%` } : { right: "50%", width: `${(Math.abs(v) / mx) * 50}%` }} />
                      </span>
                      <span className="ci-torn-v" data-dir={dir}>{v >= 0 ? "+" : "−"}{Math.abs(v).toFixed(1)}%</span>
                    </div>
                  );
                })}
              </div>
              {d.asymmetry?.note && <p className="ci-note" data-server>{clean(d.asymmetry.note)}</p>}
              {d.unavailable.length > 0 && (
                <div className="ci-macro-na">
                  <p className="ci-note">이 충격들은 재지 않았어요:</p>
                  <ul>{d.unavailable.map((u) => <li key={u.shock}><b data-server>{u.shock}</b> <span data-server>{clean(u.reason)}</span></li>)}</ul>
                </div>
              )}
              {d.is_mock && <Chips items={[{ label: "연습용 금리·재무", tone: "practice" }]} label="매크로 민감도 근거" />}
            </>
          );
        })() : null}
    </div>
  );
}
