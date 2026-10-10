"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 재무로 잰 위험(위험 절 안쪽) — 부도 위험 점수(알트만 Z) · 이익 조작 점검(베니시 M) · 빚 감당력 추이 · 금리 충격
// ─────────────────────────────────────────────────────────────────────────────
// BU6b(토스식):
//   · ★알트만 Z = 구간 막대★ 0~5 축에 경계 1.8·3.0 눈금과 지금 값 점. 경계는 서버 `risk_deep` 의 zone 규칙과 같은 값이다
//     (`tests/test_altman_zone_mirror.py` 가 서버 동작으로 확인). 구간 이름(위험·회색지대·안전)은 서버 글자 그대로 — 화면은 색으로 판단하지 않는다.
//   · 다섯 요소 기여 막대는 중립 한 색 + 서버 한국어 이름(옛 화면: X1~X5 대문자 + 툴팁 + 초록/빨강).
//   · 베니시 8지수는 근거 칩(실측·근사·자료 없어 1.0) — 서버 `basis` 그대로.
//   · 금리 충격 표는 원 단위(옛 ₩) · null = 몰라요(옛 "—") · 범례는 글자(옛 "(검정)·(파랑)" 색 이름).
//   · 상태 넷: 계산 중 · 실패 = alert + 다시 시도 · 못 함 = 사유 · 값. react-query(retry 끔) — 종목·가격이 바뀌면 키가 바뀐다.
// ═══════════════════════════════════════════════════════════════════════════════
import { useQuery } from "@tanstack/react-query";
import { companyApi } from "@/entities/company/api";
import { RetryFail } from "@/shared/ui/tx";
import { MiniLine } from "./FinancialsDeepTab";
import { bae, ok, periodShort, plain, wonTxt } from "./fmt";

/** 알트만 Z 구간 경계 — 서버 `src/engine/company_analytics.py::risk_deep` 의 zone 규칙(z>3 · z>1.8)과 같은 값(미러 테스트가 건다). */
export const ALTMAN_EDGES = [1.8, 3.0] as const;
const ALT_MAX = 5;
const BASIS_KO: Record<string, string> = { real: "실측", approx: "근사", neutral: "자료 없어 1.0" };
const at = (z: number) => Math.max(0, Math.min(100, (z / ALT_MAX) * 100));

export default function RiskDeepTab({ code, price }: { code: string; price: number }) {
  const q = useQuery({ queryKey: ["company", "risk-deep", code, price], queryFn: () => companyApi.riskDeep(code, price), retry: false, staleTime: 5 * 60_000 });
  if (q.isPending) return <div className="ci-rd"><p className="ci-fd-wait">재무로 잰 위험을 계산하는 중이에요</p></div>;
  if (q.isError) return <div className="ci-rd"><RetryFail title="재무로 잰 위험을 불러오지 못했어요" onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  const alt = d.altman;
  const maxC = Math.max(...alt.components.map((c) => Math.abs(c.contribution)), 0.01);
  const out = ok(alt.z) && (alt.z > ALT_MAX || alt.z < 0);
  return (
    <div className="ci-rd">
      <h3 className="ci-block-h">재무로 잰 위험</h3>
      <div className="ca-vt-grid">
        <section className="ca-cp-sec ci-alt">
          <h4 className="ci-fd-h">부도 위험 점수(알트만 Z)</h4>
          {ok(alt.z) ? (
            <>
              <dl className="ci-alt-ans"><div><dt>점수</dt><dd>{plain(alt.z)}</dd></div><div><dt>서버가 본 구간</dt><dd className="ci-alt-zone" data-server>{alt.zone}</dd></div></dl>
              <div className="ci-alt-scale" role="img" aria-label={`알트만 Z ${alt.z}, 0부터 ${ALT_MAX}까지 눈금, 경계 ${ALTMAN_EDGES.join("과 ")}`}>
                <span className="ci-alt-seg" style={{ left: 0, width: `${at(ALTMAN_EDGES[0])}%` }} />
                <span className="ci-alt-seg mid" style={{ left: `${at(ALTMAN_EDGES[0])}%`, width: `${at(ALTMAN_EDGES[1]) - at(ALTMAN_EDGES[0])}%` }} />
                <span className="ci-alt-seg" style={{ left: `${at(ALTMAN_EDGES[1])}%`, width: `${100 - at(ALTMAN_EDGES[1])}%` }} />
                {ALTMAN_EDGES.map((e) => <span key={e} className="ci-alt-tick" style={{ left: `${at(e)}%` }}>{e.toFixed(1)}</span>)}
                <i className="ci-alt-dot" data-v={alt.z} style={{ left: `${at(alt.z)}%` }} aria-hidden />
              </div>
              <p className="ci-alt-axis"><span>0</span><span>{ALT_MAX} 이상</span></p>
              {out && <p className="ci-note">점수가 눈금 밖이라 끝에 붙여 그렸어요.</p>}
              <p className="ci-fd-lede">다섯 요소가 점수에 더한 몫이에요(가중치 × 비율).</p>
              <div className="ci-alt-rows">
                {alt.components.map((c) => (
                  <div key={c.id} className="ci-alt-row">
                    <span className="ci-alt-l" data-server>{c.label}</span>
                    <span className="ci-alt-track"><i className="ci-alt-bar" style={{ width: `${(Math.abs(c.contribution) / maxC) * 100}%` }} /></span>
                    <b className="ci-alt-v">{plain(c.contribution)}</b>
                    <span className="ci-alt-w">비율 {plain(c.value, 3)} × {plain(c.weight, 1)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : <p className="ci-fd-reason">부도 위험 점수를 계산하지 못했어요. 서버가 이 종목의 재무 원천을 읽지 못했어요.</p>}
        </section>

        <section className="ca-cp-sec ci-ben">
          <h4 className="ci-fd-h">이익 조작 점검(베니시 M)</h4>
          {d.beneish.available ? (
            <>
              <dl className="ci-alt-ans"><div><dt>점수</dt><dd>{plain(d.beneish.m_score)}</dd></div><div><dt>서버 판정</dt><dd data-server>{d.beneish.flag}</dd></div></dl>
              <div className="ci-tablewrap">
                <table className="ca-fd-tbl">
                  <thead><tr><th scope="col">지수</th><th scope="col" className="n">값</th><th scope="col">근거</th></tr></thead>
                  <tbody>
                    {d.beneish.indices.map((i) => (
                      <tr key={i.id}>
                        <td data-server>{i.label}</td>
                        <td className="n">{plain(i.value, 3)}</td>
                        <td><span className="ci-basis" data-basis={i.basis}>{BASIS_KO[i.basis] ?? i.basis}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {d.beneish.note && <p className="ci-note" data-server>{d.beneish.note}</p>}
            </>
          ) : (
            <>
              <p className="ci-fd-reason">전년 재무가 없어 이익 조작 점검을 하지 못했어요.</p>
              {d.beneish.note && <details className="ci-fd-raw"><summary>원래 사유 보기</summary><p data-server>{d.beneish.note}</p></details>}
            </>
          )}
        </section>
      </div>

      <section className="ca-cp-sec ci-cov">
        <h4 className="ci-fd-h">빚을 감당하는 힘</h4>
        {d.coverage.years.length ? (
          <>
            <MiniLine years={d.coverage.years} label="이자보상배율과 순부채/EBITDA 추이"
              series={[{ vals: d.coverage.interest_coverage, cls: "ca-fd-ni" }, { vals: d.coverage.net_debt_to_ebitda, cls: "ca-fd-ocf", dash: true }]} />
            <p className="ci-fd-keys">
              <span className="ci-fd-key"><i className="sw ni" aria-hidden />이자보상배율(실선 · 영업이익이 이자의 몇 배인지)</span>
              <span className="ci-fd-key"><i className="sw ocf" aria-hidden />순부채/EBITDA(점선 · 빚을 몇 년 이익으로 갚는지)</span>
            </p>
            <div className="ci-tablewrap">
              <table className="ca-fd-tbl">
                <thead><tr><th scope="col">항목</th>{d.coverage.years.map((y) => <th key={y} scope="col">{periodShort(y)}</th>)}</tr></thead>
                <tbody>
                  <tr><td>이자보상배율</td>{d.coverage.interest_coverage.map((v, i) => <td key={i}>{bae(v, 1)}</td>)}</tr>
                  <tr><td>순부채/EBITDA</td>{d.coverage.net_debt_to_ebitda.map((v, i) => <td key={i}>{bae(v, 2)}</td>)}</tr>
                </tbody>
              </table>
            </div>
          </>
        ) : <p className="ci-fd-reason">연도별 재무가 없어 추이를 그리지 못했어요.</p>}
        <p className="ci-note"><span className="ci-fd-k">근사</span><span data-server>{d.coverage.note}</span></p>
      </section>

      <section className="ca-cp-sec ci-stress">
        <h4 className="ci-fd-h">금리가 오르면</h4>
        <p className="ci-fd-lede">할인율을 한꺼번에 올려 다시 계산한 값이에요(1%p = 100bp).</p>
        <div className="ci-tablewrap">
          <table className="ca-fd-tbl">
            <thead><tr><th scope="col">금리 충격</th><th scope="col" className="n">이자보상배율</th><th scope="col" className="n">현금흐름할인 가치</th><th scope="col" className="n">통합 적정가</th></tr></thead>
            <tbody>
              {d.rate_stress.rows.map((r) => (
                <tr key={r.shock_bp}>
                  <td>{r.shock_bp === 0 ? "지금" : `+${(r.shock_bp / 100).toLocaleString("ko-KR")}%p`}</td>
                  <td className="n">{bae(r.interest_coverage, 1)}</td>
                  <td className="n">{wonTxt(r.dcf_value)}</td>
                  <td className="n">{wonTxt(r.unified_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="ci-note"><span className="ci-fd-k">가정</span><span data-server>{d.rate_stress.note}</span></p>
      </section>
    </div>
  );
}
