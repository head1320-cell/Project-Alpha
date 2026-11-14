"use client";
/**
 * 분봉 백테스트 ⑥ 판정 — 관문 일곱 · 표본내와 표본외 · 비용 민감도 · 워크포워드 · 시행 횟수
 * ==========================================================================
 * 답하는 물음은 하나다: "이 규칙이 이 기간·이 종목에서 이 가정 아래 남긴 숫자를 ★어디까지 읽을 수 있나★."
 * 앞으로도 그렇다는 말이 아니고 계좌에서 돈이 된다는 말도 아니다 — 경제적 가치와 모의·실계좌 관문은 늘 미상으로 남는다.
 * ★종합 점수·등급을 만들지 않는다★ — 통과·미달·미상의 개수만 센다. 상태는 색만으로 말하지 않고 글자(통과 · 미달 · 미상)가 함께 간다.
 * 숫자와 사유 문장은 전부 서버 값이다.
 * 화면(백테스트 › 분봉 규칙)과 캔버스의 '분봉 결과 조회' 판이 같이 쓴다 — 그래서 feature 에 둔다(위젯끼리 서로 참조하지 않는다).
 */
import type { Brief, GateState, Multiplicity, Validation, Value, WalkForward } from "@/entities/intraday";
import { UNKNOWN_TEXT, num, pct, signedWon } from "@/shared/lib/krFormat";
import { Answer, Notice, Section, type ChipTone } from "@/shared/ui/tx";
import { TrialLine, bp1, originChip } from "./parts";

const STATE_KO: Record<GateState, string> = { ok: "통과", degraded: "미달", unknown: "미상" };
const STATE_TONE: Record<GateState, ChipTone> = { ok: "ok", degraded: "assumed", unknown: "unknown" };
const prob = (v: number | null | undefined): string => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(3) : UNKNOWN_TEXT);
const dir = (v: number | null | undefined) => (typeof v !== "number" || Math.round(v) === 0 ? undefined : v > 0 ? "up" : "down");

function BriefCells({ b }: { b: Brief | null }) {
  if (!b) return <><td className="tj-num">{UNKNOWN_TEXT}</td><td className="tj-num">{UNKNOWN_TEXT}</td><td className="tj-num">{UNKNOWN_TEXT}</td><td className="tj-num">{UNKNOWN_TEXT}</td><td className="tj-num">{UNKNOWN_TEXT}</td></>;
  return (
    <>
      <td className="tj-num">{num(b.trades)}건</td>
      <td className="tj-num" data-dir={dir(b.gross_total)}>{signedWon(b.gross_total)}</td>
      <td className="tj-num" data-dir={dir(b.net_total)}>{signedWon(b.net_total)}</td>
      <td className="tj-num" data-dir={dir(b.net_expectancy)}>{signedWon(b.net_expectancy)}</td>
      <td className="tj-num">{b.trades ? pct(b.win_rate) : UNKNOWN_TEXT}</td>
    </>
  );
}
const BRIEF_HEAD = <><th scope="col" className="tj-num">거래</th><th scope="col" className="tj-num">비용 전 합계</th><th scope="col" className="tj-num">비용 후 합계</th>
  <th scope="col" className="tj-num">비용 후 거래당</th><th scope="col" className="tj-num">승률</th></>;

/** `labels` — 격자의 칸을 적을 때 쓰는 칸 이름(규칙 매개변수와 포지션 설정). 서버의 틀 목록에서 온다. */
export function Verdict({ v, labels }: { v: Validation; labels: Record<string, string> }) {
  if (v.empty || !v.gates || !v.summary) {
    return (
      <div className="itd-verdict" data-empty={v.empty?.reason ?? "no_gates"}>
        <Notice tone="warn" title="판정 없음"><span data-server>{v.empty?.message ?? "판정할 결과가 없습니다."}</span></Notice>
      </div>
    );
  }
  const g = v.gates;
  return (
    <div className="itd-verdict">
      <p className="tx-sr" role="status">판정 완료: 통과 {g.counts.ok} · 미달 {g.counts.degraded} · 미상 {g.counts.unknown}</p>
      <Answer sentence={<span data-server>{g.sentence}</span>}
              figures={[{ label: "통과", value: `${g.counts.ok}` }, { label: "미달", value: `${g.counts.degraded}` }, { label: "미상", value: `${g.counts.unknown}` }]}
              chips={[originChip(v.origin), { label: "종합 점수 없음", tone: "plain" }]} />
      <Section title="관문 일곱" sub="앞의 관문이 미달이면 뒤의 숫자는 그만큼 약하게 읽어야 합니다. 미상은 통과가 아닙니다.">
        <ol className="itd-gates">
          {g.gates.map((gate, i) => (
            <li key={gate.key} className="itd-gate" data-gate={gate.key} data-state={gate.state}>
              <span className="itd-gate-no" aria-hidden="true">{i + 1}</span>
              <div className="itd-gate-main">
                <p className="itd-gate-head"><b className="itd-gate-name" data-server>{gate.label}</b>
                  <span className="tx-chip itd-gate-state" data-tone={STATE_TONE[gate.state]}>{STATE_KO[gate.state]}</span></p>
                <p className="itd-gate-reason" data-server>{gate.reason}</p>
                {gate.facts.length ? <ul className="tj-plain-list itd-gate-facts">{gate.facts.map((f) => <li key={f} data-server>{f}</li>)}</ul> : null}
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <OutOfSample v={v} />
      <Sensitivity v={v} />
      {v.walk_forward ? <Walk w={v.walk_forward} labels={labels} /> : null}
      <Trials m={v.multiplicity} v={v} />
    </div>
  );
}

function OutOfSample({ v }: { v: Validation }) {
  const o = v.out_of_sample;
  const s = o?.split ?? null;
  return (
    <Section title="표본내와 표본외" sub="거래일을 시간순으로 앞 70% 와 뒤 30% 로 갈랐습니다(섞지 않음). 같은 체결을 날짜로 나눠 같은 방식으로 집계했습니다.">
      {o && s ? (
        <>
          <div className="tj-scroll-x">
            <table className="tj-table itd-oos">
              <thead><tr><th scope="col">구간</th><th scope="col">기간</th>{BRIEF_HEAD}</tr></thead>
              <tbody>
                <tr data-k="in_sample"><th scope="row">표본내 {num(s.in_sample_days)}일</th><td data-mono>{s.in_sample_from} ~ {s.in_sample_to}</td><BriefCells b={o.in_sample} /></tr>
                <tr data-k="out_of_sample"><th scope="row">표본외 {num(s.out_of_sample_days)}일</th><td data-mono>{s.out_of_sample_from} ~ {s.out_of_sample_to}</td><BriefCells b={o.out_of_sample} /></tr>
              </tbody>
            </table>
          </div>
          <p className="tj-note itd-oos-views" data-views={o.views ?? "unknown"}>
            {o.views === null ? "이 표본외 구간을 몇 번째 보는지 세지 못했습니다." : `이 표본외 구간을 ${num(o.views)}번째 봅니다.${o.views >= 2 ? " 두 번째부터는 표본외가 아닙니다." : ""}`}
          </p>
        </>
      ) : <p className="tj-note itd-oos-none">거래일이 모자라 표본내와 표본외로 가르지 못했습니다.</p>}
    </Section>
  );
}

function Sensitivity({ v }: { v: Validation }) {
  const st = v.stress;
  return (
    <Section title="비용 민감도" sub="슬리피지 가정을 바꿔 다시 돌린 결과와, 수수료율과 슬리피지를 두 배로 놓은 결과입니다. 매도세는 법정 세율이라 그대로 둡니다.">
      <div className="tj-scroll-x">
        <table className="tj-table itd-slippage">
          <thead><tr><th scope="col">슬리피지(편도)</th>{BRIEF_HEAD}</tr></thead>
          <tbody>
            {v.slippage.map((r) => (
              <tr key={r.ticks} data-ticks={r.ticks} data-base={r.is_base || undefined}>
                <th scope="row">{r.ticks}틱{r.is_base ? " · 지금 가정" : ""}</th><BriefCells b={r} />
              </tr>
            ))}
            {st ? (
              <tr data-k="double" className="itd-double">
                <th scope="row">비용 두 배 · 수수료 {bp1(st.commission_bp)} · 슬리피지 {st.slippage_ticks}틱</th><BriefCells b={st.double} />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="tj-note">시장충격과 호가 잔량은 반영하지 않았습니다. 체결 수량이 그 봉 거래량에 견줘 클수록 실제 체결가는 이보다 불리합니다.</p>
    </Section>
  );
}

const cellName = (c: { rule: Record<string, Value>; position: Record<string, Value> }, labels: Record<string, string>): string =>
  [...Object.entries(c.rule), ...Object.entries(c.position)].map(([k, val]) => `${labels[k] ?? k} ${String(val)}`).join(" · ");

function Walk({ w, labels }: { w: WalkForward; labels: Record<string, string> }) {
  const name = (i: number | null) => (i === null ? "고르지 못함" : `${i + 1}번 칸`);
  return (
    <Section title="워크포워드" sub="앞 구간에서 비용 후 거래당 기대값이 가장 큰 칸을 다음 구간에 적용해 이어 붙였습니다. 첫 구간은 고르는 데만 씁니다.">
      <div className="itd-walk">
        <p className="tj-note" data-server>{w.note}</p>
        <div className="tj-scroll-x">
          <table className="tj-table itd-cells">
            <thead><tr><th scope="col">칸</th><th scope="col">설정</th>{BRIEF_HEAD}</tr></thead>
            <tbody>
              {w.cells.map((c) => (
                <tr key={c.index} data-cell={c.index}><th scope="row">{c.index + 1}번 칸{c.is_base ? " · 지금 설정" : ""}</th><td>{cellName(c, labels)}</td><BriefCells b={c.whole} /></tr>
              ))}
            </tbody>
          </table>
        </div>
        {w.reason ? <Notice tone="warn" title="워크포워드를 산출하지 않았습니다."><span data-server>{w.message ?? w.reason}</span></Notice> : (
          <>
            <div className="tj-scroll-x">
              <table className="tj-table itd-steps">
                <thead><tr><th scope="col">고른 구간</th><th scope="col">고른 칸</th><th scope="col">적용한 구간</th>{BRIEF_HEAD}</tr></thead>
                <tbody>
                  {w.steps.map((s) => (
                    <tr key={s.apply.from} data-chosen={s.chosen ?? "none"}>
                      <td data-mono>{s.choose.from} ~ {s.choose.to}</td><td>{name(s.chosen)}</td><td data-mono>{s.apply.from} ~ {s.apply.to}</td><BriefCells b={s.applied} />
                    </tr>
                  ))}
                  <tr data-k="stitched" className="itd-double"><th scope="row" colSpan={3}>이어 붙인 결과(둘째 구간부터)</th><BriefCells b={w.stitched} /></tr>
                </tbody>
              </table>
            </div>
            {w.steps.some((s) => s.chosen === null) ? <p className="tj-note">고르는 구간에 거래가 있는 칸이 없으면 다음 구간에는 아무것도 적용하지 않습니다.</p> : null}
          </>
        )}
      </div>
    </Section>
  );
}

function Trials({ m, v }: { m: Multiplicity | null; v: Validation }) {
  return (
    <Section title="시행 횟수와 다중 비교" sub="설정을 바꿔 여러 번 본 뒤 가장 좋은 것을 고르면 그 숫자는 우연으로도 좋아집니다. 기록된 시행 횟수로 그만큼을 보정합니다.">
      <div className="itd-trials">
        {m ? (
          <>
            <dl className="tj-cost-figs itd-mult">
              <div data-k="n"><dt>가족 시행 횟수(N)</dt><dd>{num(m.n)}회</dd></div>
              <div data-k="days"><dt>거래일</dt><dd>{m.days === null ? UNKNOWN_TEXT : `${num(m.days)}일`}</dd></div>
              <div data-k="psr"><dt>보정 전 확률(PSR)</dt><dd>{prob(m.psr0)}</dd></div>
              <div data-k="dsr"><dt>시행 횟수로 보정한 확률(DSR)</dt><dd>{m.corrected ? prob(m.dsr) : "보정할 것 없음"}</dd></div>
            </dl>
            {m.reason ? <p className="tj-note itd-mult-why" data-server>{m.reason}</p> : null}
            {m.unscored > 0 ? <p className="tj-note">비용 후 손익이 없는 시행 {num(m.unscored)}회는 횟수에는 넣고 확률 계산에는 넣지 않았습니다.</p> : null}
            {m.n_effective !== null ? <p className="tj-note">시행끼리 닮은 정도로 줄인 수는 {m.n_effective.toFixed(2)}회이고, 그 수로 보정한 확률은 {prob(m.dsr_effective)}입니다.</p> : null}
            {m.n_effective_reason ? <p className="tj-note" data-server>{m.n_effective_reason}</p> : null}
            <p className="tj-note" data-server>{m.note}</p>
            <p className="tj-note">기준 {m.threshold} 는 관례 기준입니다. 확률은 일별 손익 흐름의 샤프가 0(보정 시 우연히 기대되는 최댓값)을 넘을 확률이며 수익의 크기를 뜻하지 않습니다.</p>
          </>
        ) : <p className="tj-note itd-mult-none">시행 횟수를 세지 못해 보정하지 않았습니다.</p>}
        <TrialLine trial={v.trial} />
      </div>
    </Section>
  );
}
