"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 재무 심화(돈 버는 힘 절 안쪽) — 이익의 질 · 운전자본 · 자본 배치 · 자본비용 대비 이익률 · 듀폰 분해
// ─────────────────────────────────────────────────────────────────────────────
// BU6b(토스식): 그림·표는 그대로 두고(지우지 않음) 말과 상태를 고쳤다.
//   · 상태 넷: 불러오는 중 · ★실패 = alert + 다시 시도(옛 화면은 원시 예외 글)★ · 미적재 = 사람 말 사유(서버 원문은 "원래 사유 보기") · 값.
//   · 판단은 색으로 말하지 않는다: 자본비용 대비 이익률(ROIC−WACC)은 잉크 + 부호, 서버 판정 글자 그대로. 회계 경고는 아이콘 없는 "주의" 칩 + 서버 문장.
//   · 계열 색은 범주색(`--mc-c-*`) + 글자 범례(색 이름으로 범례를 쓰지 않는다 — 다크에서 색이 바뀐다).
//   · null = 몰라요(옛 "—" 자리표시). 연도 머리는 "24년".
// react-query(retry 끔): 종목이 바뀌면 키가 바뀌어 옛 종목 값이 남지 않는다 · [다시 시도] = refetch.
// ═══════════════════════════════════════════════════════════════════════════════
import { useQuery } from "@tanstack/react-query";
import { companyApi } from "@/entities/company/api";
import { RetryFail } from "@/shared/ui/tx";
import { eokWon, ok, pctTxt, plain, ppSigned, periodShort, bae } from "./fmt";

type N = number | null | undefined;

/** 작은 선 그림 — 축 없이 모양만(값은 옆 표·범례 글자에 있다). 계열 색은 `cls`(CSS 범주색). */
export function MiniLine({ years, series, label }: {
  years: number[];
  series: { vals: N[]; cls: string; dash?: boolean }[];
  label: string;
}) {
  const all = series.flatMap((s) => s.vals.filter((v): v is number => ok(v)));
  if (!all.length) return <p className="ci-note">그릴 값이 없어요.</p>;
  const lo = Math.min(...all, 0), hi = Math.max(...all, 0), span = hi - lo || 1;
  const X = (i: number) => (i / Math.max(1, years.length - 1)) * 100;
  const Y = (v: number) => 31 - ((v - lo) / span) * 28;
  return (
    <svg viewBox="0 0 100 34" className="ca-fd-mini" preserveAspectRatio="none" role="img" aria-label={label}>
      {lo < 0 && hi > 0 && <line className="ca-fd-zero" x1="0" x2="100" y1={Y(0)} y2={Y(0)} />}
      {series.map((s, k) => (
        <polyline key={k} className={s.cls} fill="none" vectorEffect="non-scaling-stroke"
          strokeDasharray={s.dash ? "4 3" : undefined}
          points={s.vals.map((v, i) => (ok(v) ? `${X(i)},${Y(v)}` : "")).filter(Boolean).join(" ")} />
      ))}
    </svg>
  );
}

const last = <T,>(a: T[]): T | undefined => a[a.length - 1];

export default function FinancialsDeepTab({ code }: { code: string }) {
  const q = useQuery({ queryKey: ["company", "financial-deep", code], queryFn: () => companyApi.financialDeep(code), retry: false, staleTime: 5 * 60_000 });
  if (q.isPending) return <div className="ci-fd"><p className="ci-fd-wait">재무를 더 깊이 계산하는 중이에요</p></div>;
  if (q.isError) return <div className="ci-fd"><RetryFail title="재무 심화를 불러오지 못했어요" onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  if (!d.available) {
    return (
      <div className="ci-fd">
        <p className="ci-fd-reason">재무 시계열이 아직 적재되지 않아 이익의 질·운전자본·자본 배치를 계산하지 못했어요. 연도별 숫자는 위 표에서 볼 수 있어요.</p>
        {d.note && <details className="ci-fd-raw"><summary>원래 사유 보기</summary><p data-server>{d.note}</p></details>}
      </div>
    );
  }
  const qe = d.qoe, wf = d.waterfall;
  const li = wf.years.length - 1;
  const debtUp = ok(wf.debt_delta[li]) && (wf.debt_delta[li] as number) > 0;
  return (
    <div className="ci-fd">
      <h3 className="ci-block-h">재무를 더 깊이</h3>

      <section className="ca-cp-sec ci-fd-qoe">
        <h4 className="ci-fd-h">이익의 질</h4>
        <p className="ci-fd-lede">장부상 순이익이 실제 들어온 현금(영업현금흐름)으로 뒷받침되는지 봐요.</p>
        <MiniLine years={qe.years} label={`순이익과 영업현금흐름 ${qe.years.length}년 추이`}
          series={[{ vals: qe.ni, cls: "ca-fd-ni" }, { vals: qe.ocf, cls: "ca-fd-ocf", dash: true }]} />
        <p className="ci-fd-keys">
          <span className="ci-fd-key"><i className="sw ni" aria-hidden />순이익(실선)</span>
          <span className="ci-fd-key"><i className="sw ocf" aria-hidden />영업현금흐름(점선)</span>
          <span className="ci-fd-yrs">{periodShort(qe.years[0])}~{periodShort(last(qe.years) ?? "")}</span>
        </p>
        <dl className="ci-fd-dl">
          <div><dt>{periodShort(last(qe.years) ?? "")} 순이익</dt><dd>{eokWon(last(qe.ni))}</dd></div>
          <div><dt>영업현금흐름</dt><dd>{eokWon(last(qe.ocf))}</dd></div>
          <div><dt>현금 − 순이익</dt><dd>{eokWon(last(qe.gap))}</dd></div>
          <div><dt>발생액 ÷ 총자산</dt><dd>{pctTxt(last(qe.accruals) ?? null, 2)}</dd></div>
        </dl>
        <div className="ci-fd-flags">
          {qe.red_flags.length
            ? qe.red_flags.map((f) => (
              <p key={f.rule} className="ci-fd-flag"><span className="ci-fd-flag-k">주의</span><span data-server>{f.msg}</span></p>))
            : <p className="ci-fd-noflag">세 가지 점검(현금이 이익보다 3년 연속 적음 · 발생액 3년 연속 증가 · 운전자본 비중 3년 연속 증가)에 걸린 것이 없어요.</p>}
        </div>
      </section>

      <div className="ca-vt-grid">
        <section className="ca-cp-sec">
          <h4 className="ci-fd-h">운전자본</h4>
          <p className="ci-fd-lede">유동자산에서 유동부채를 뺀 돈이에요. 매출 대비 비중이 늘면 현금이 영업에 묶여요.</p>
          <MiniLine years={d.nwc.years} label="운전자본 추이" series={[{ vals: d.nwc.nwc, cls: "ca-fd-ni" }]} />
          <div className="ci-tablewrap">
            <table className="ca-fd-tbl">
              <thead><tr><th scope="col">항목</th>{d.nwc.years.map((y) => <th key={y} scope="col">{periodShort(y)}</th>)}</tr></thead>
              <tbody>
                <tr><td>운전자본</td>{d.nwc.nwc.map((v, i) => <td key={i}>{eokWon(v)}</td>)}</tr>
                <tr><td>매출 대비</td>{d.nwc.nwc_to_rev_pct.map((v, i) => <td key={i}>{pctTxt(v)}</td>)}</tr>
              </tbody>
            </table>
          </div>
        </section>

        <section className="ca-cp-sec">
          <h4 className="ci-fd-h">번 현금을 어디에 썼나요</h4>
          <p className="ci-fd-lede">{periodShort(wf.years[li])} 영업현금흐름에서 설비투자·배당·빚 갚기를 뺀 나머지예요.</p>
          <WaterfallBars ocf={wf.ocf[li]} capex={wf.capex[li]} dividends={wf.dividends[li]}
            repay={ok(wf.debt_delta[li]) ? Math.max(0, -(wf.debt_delta[li] as number)) : null} residual={wf.residual[li]} />
          {debtUp && <p className="ci-note">이 해에는 부채가 {eokWon(wf.debt_delta[li])} 늘었어요. 새로 빌렸고 갚은 돈은 없어요.</p>}
          {!ok(wf.debt_delta[li]) && <p className="ci-note">전년 부채를 몰라 빚 갚은 돈을 계산하지 못했어요.</p>}
          <p className="ci-note" data-server>{wf.note}</p>
        </section>
      </div>

      {d.roic_wacc ? (
        <section className="ca-cp-sec ci-fd-rw">
          <h4 className="ci-fd-h">자본비용보다 많이 벌었나요</h4>
          <p className="ci-fd-lede">투하자본이익률(ROIC)에서 자본을 쓰는 비용(WACC)을 뺀 차이예요.</p>
          <p className="ci-fd-eq">
            <span>ROIC {pctTxt(d.roic_wacc.roic, 2)}</span><span aria-hidden>−</span><span>WACC {pctTxt(d.roic_wacc.wacc, 2)}</span><span aria-hidden>=</span>
            <b className="ci-fd-spread">{ppSigned(d.roic_wacc.spread)}</b>
          </p>
          <p className="ci-fd-verdict"><span className="ci-fd-k">서버 판정</span><span data-server>{d.roic_wacc.verdict}</span></p>
          <p className="ci-note"><span className="ci-fd-k">가정</span><span data-server>{d.roic_wacc.note}</span></p>
        </section>
      ) : (
        <p className="ci-note">자본비용 대비 이익률은 투하자본이익률(ROIC)이 적재되지 않아 계산하지 못했어요.</p>
      )}

      <details className="ca-cp-sec ci-fd-dupont">
        <summary>ROE 를 셋으로 나눠 보기(듀폰 분해)</summary>
        <p className="ci-fd-lede">순이익률 × 자산회전율 × 레버리지 = ROE 예요.</p>
        <div className="ci-tablewrap">
          <table className="ca-fd-tbl">
            <thead><tr><th scope="col">항목</th>{d.dupont.years.map((y) => <th key={y} scope="col">{periodShort(y)}</th>)}</tr></thead>
            <tbody>
              <tr><td>순이익률</td>{d.dupont.net_margin.map((v, i) => <td key={i}>{pctTxt(v, 2)}</td>)}</tr>
              <tr><td>자산회전율</td>{d.dupont.asset_turnover.map((v, i) => <td key={i}>{ok(v) ? `${plain(v, 3)}회` : plain(v)}</td>)}</tr>
              <tr><td>레버리지</td>{d.dupont.leverage.map((v, i) => <td key={i}>{bae(v, 3)}</td>)}</tr>
              <tr className="sum"><td>ROE</td>{d.dupont.roe.map((v, i) => <td key={i}>{pctTxt(v, 2)}</td>)}</tr>
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/** 현금 쓰임 막대 — 들어온 돈·남은 돈과 쓴 돈을 ★중립 두 톤★으로(판단 색 아님) + 부호 글자. 모르는 항목은 막대 없이 "몰라요". */
function WaterfallBars({ ocf, capex, dividends, repay, residual }: { ocf: N; capex: N; dividends: N; repay: N; residual: N }) {
  const items: { label: string; v: N; kind: "in" | "out" }[] = [
    { label: "영업현금흐름", v: ocf, kind: "in" },
    { label: "설비투자", v: ok(capex) ? -capex : null, kind: "out" },
    { label: "배당", v: ok(dividends) ? -dividends : null, kind: "out" },
    { label: "빚 갚기", v: ok(repay) ? -repay : null, kind: "out" },
    { label: "남은 현금", v: residual, kind: ok(residual) && residual < 0 ? "out" : "in" },
  ];
  const maxAbs = Math.max(...items.map((it) => (ok(it.v) ? Math.abs(it.v) : 0)), 1);
  return (
    <div className="ci-wf">
      {items.map((it) => (
        <div key={it.label} className="ca-fd-wf-row">
          <span className="ca-fd-wf-label">{it.label}</span>
          <div className="ca-fd-wf-track">
            {ok(it.v) && <div className="ca-fd-wf-bar" data-kind={it.kind} style={{ width: `${(Math.abs(it.v) / maxAbs) * 100}%` }} />}
          </div>
          <b className="ca-fd-wf-val">{ok(it.v) && it.v > 0 && it.label !== "영업현금흐름" && it.label !== "남은 현금" ? "+" : ""}{eokWon(it.v)}</b>
        </div>
      ))}
    </div>
  );
}
