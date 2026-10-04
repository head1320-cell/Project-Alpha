"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 위험 점검(BU7a · 사용자 결정 "네 시나리오 한눈에 + 고른 것 자세히")
// ─────────────────────────────────────────────────────────────────────────────
// 위에서 아래로: 답 한 문장(서버 값 세기) → 네 충격 한눈에(버틴 종목 막대 · 평균 점수 변화, 누르면 고름) →
//   ★종목 × 충격 칸 지도★ → 고른 충격 자세히(요약 카드 넷 · 취약 종목 표 · 덜 흔들린/겨우 넘긴 종목 · 어떻게 쟀나요).
// ★지키는 것★
//   · 충격마다 따로 묻는다(react-query `useQueries`) — 하나가 실패해도 그 줄만 alert, 늦은 응답이 고른 화면을 덮지 않는다.
//   · 실패(닿지 못함) ≠ 서버가 못 했다고 답함(`available:false` → 사유) ≠ 값. 옛 화면은 앞의 둘을 삼키거나 "undefined%"·"전 종목 생존"으로 그렸다.
//   · 서버는 충격마다 취약 ≤10 · 버틴 ≤5 · 가장 덜 흔들린 ≤5 종목만 보낸다 — ★목록에 없는 칸은 "목록 밖"★(버텼다고 지어내지 않는다).
//   · 값은 "종합점수 변화 추정"(가격 손실 아님) — 부호 있는 변화라 한국식 등락색 + 부호. 막대는 중립 한 색.
// 요청 본문은 옛 화면과 같다(`analysisApi.stressTest` — 코스피 200 · PER 양수 · 종합점수 상위 30 · 유동성 standard).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { analysisApi, type StressResult, type StressRow, type StressRun } from "@/entities/macro/analysisApi";
import { macroApi } from "@/entities/macro/api";
import { Answer, PageHead, RetryFail, type Chip } from "@/shared/ui/tx";
import { MINUS, UNKNOWN_TEXT } from "@/shared/lib/krFormat";

const UNIVERSE = "kospi200";
/** 서버 `stress_test` 의 생존 기준(shock > −8) — `tests/test_stress_weak_mirror.py` 가 서버 동작과 같은지 본다. */
export const STRESS_WEAK_PCT = 8;

type Ok = Extract<StressResult, { available: true }>;
const sgn = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? MINUS : ""}${Math.abs(v).toFixed(d)}`;
const dir = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

export function StressCheck() {
  const router = useRouter();
  const list = useQuery({ queryKey: ["risk", "stress-scenarios"], queryFn: () => analysisApi.stressScenarios(), retry: false, staleTime: 10 * 60_000 });
  const scenarios = useMemo(() => list.data?.scenarios ?? [], [list.data]);
  const runs = useQueries({
    queries: scenarios.map((s) => ({
      queryKey: ["risk", "stress", UNIVERSE, s.id], queryFn: () => analysisApi.stressTest(UNIVERSE, s.id), retry: false, staleTime: 5 * 60_000,
    })),
  });
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  const [picked, setPicked] = useState<string | null>(null);
  const sel = picked ?? scenarios[0]?.id ?? null;

  const byId = Object.fromEntries(scenarios.map((s, i) => [s.id, { meta: s, q: runs[i] }]));
  const okOf = (id: string): Ok | null => { const r = byId[id]?.q?.data?.analyzers.stress_test; return r && r.available ? r : null; };
  const oks = scenarios.map((s) => okOf(s.id)).filter((x): x is Ok => !!x);

  // ── 답: 취약 종목이 가장 많은 충격(세기만) ──
  const worst = oks.reduce<Ok | null>((a, b) => (!a || b.n_casualties > a.n_casualties ? b : a), null);
  const pending = runs.filter((q) => q.isPending).length;
  const sentence = list.isError ? "충격 목록을 받지 못해 아직 점검하지 못했어요."
    : worst ? <>네 경제 충격 중 ‘<span data-server>{worst.scenario_label}</span>’에서 {worst.n_stocks}종목 중 {worst.n_casualties}종목이 취약했어요.</>
    : pending || list.isPending ? "네 경제 충격을 계산하는 중이에요."
    : "충격 결과를 하나도 받지 못했어요.";
  const chips: Chip[] = [];
  if (cs.data?.mock_allowed) chips.push({ label: "연습용 데이터", tone: "practice" });
  chips.push({ label: "코스피 200 · PER 양수 · 종합점수 상위 30종목", tone: "plain" });
  chips.push({ label: "가격 손실이 아니라 종합점수 변화를 추정해요", tone: "assumed" });

  // ── 칸 지도: 네 충격 목록에 나온 종목의 합집합 × 충격 ──
  const map = useMemo(() => {
    const names = new Map<string, string>();
    const cells = new Map<string, StressRow>(); // `${sc}|${code}`
    for (const s of scenarios) {
      const r = okOf(s.id);
      if (!r) continue;
      for (const row of [...r.casualties, ...r.survivors, ...r.most_resilient]) {
        names.set(row.stock_code, row.corp_name);
        cells.set(`${s.id}|${row.stock_code}`, row);
      }
    }
    const worstOf = (code: string) => Math.min(...scenarios.map((s) => cells.get(`${s.id}|${code}`)?.shock_pct ?? Infinity));
    const codes = [...names.keys()].sort((a, b) => worstOf(a) - worstOf(b));
    const maxAbs = Math.max(1, ...[...cells.values()].map((c) => Math.abs(c.shock_pct)));
    return { names, cells, codes, maxAbs };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarios, ...runs.map((q) => q.data)]);
  const [read, setRead] = useState<string | null>(null);

  return (
    <div className="rk tx-page">
      <PageHead title="위험 점검" lede="경제 충격이 오면 어떤 종목의 점수가 크게 흔들리는지 미리 봐요." />
      <Answer sentence={sentence} chips={chips} />

      {list.isError ? <RetryFail title="충격 목록을 불러오지 못했어요" onRetry={() => list.refetch()} />
        : list.isPending ? <p className="rk-wait">충격 목록을 불러오는 중이에요</p>
        : (
          <>
            <section className="tx-sec rk-sum" aria-labelledby="rk-sum-h">
              <h2 id="rk-sum-h" className="tx-sec-t">네 충격 한눈에</h2>
              <p className="tx-sec-sub">막대는 30종목 중 기준을 넘겨 버틴 종목의 비율이에요. 줄을 누르면 아래에서 자세히 봐요.</p>
              <div className="rk-sum-list" role="group" aria-label="충격 고르기">
                {scenarios.map((s) => {
                  const q = byId[s.id]?.q;
                  if (q?.isError) {
                    return (
                      <div key={s.id} className="rk-sum-row rk-sum-row--fail" data-sc={s.id}>
                        <span className="rk-sum-name" data-server>{s.label}</span>
                        <RetryFail title="이 충격을 계산하지 못했어요" onRetry={() => q.refetch()} />
                      </div>
                    );
                  }
                  const r = q?.data?.analyzers.stress_test;
                  const on = sel === s.id;
                  return (
                    <button key={s.id} type="button" className="rk-sum-row" data-sc={s.id} aria-pressed={on} onClick={() => setPicked(s.id)}>
                      <span className="rk-sum-name" data-server>{s.label}</span>
                      {!q || q.isPending ? <span className="rk-sum-wait">계산하는 중이에요</span>
                        : !r ? <span className="rk-sum-reason">서버가 이 충격의 결과를 보내지 않았어요</span>
                        : !r.available ? <span className="rk-sum-reason">못 했어요: <span data-server>{r.error ?? r.reason ?? "사유를 받지 못했어요"}</span></span>
                        : (
                          <>
                            <span className="rk-sum-bar" aria-hidden><i style={{ width: `${(r.n_survivors / Math.max(1, r.n_stocks)) * 100}%` }} /></span>
                            <span className="rk-sum-n">버틴 종목 {r.n_survivors}/{r.n_stocks}</span>
                            <span className="rk-sum-avg">평균 점수 <b className="rk-dir" data-dir={dir(r.avg_shock_pct)}>{sgn(r.avg_shock_pct)}%</b></span>
                          </>
                        )}
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="tx-sec rk-mapsec" aria-labelledby="rk-map-h">
              <h2 id="rk-map-h" className="tx-sec-t">종목마다 충격별 점수 변화</h2>
              <p className="tx-sec-sub">서버는 충격마다 취약한 10종목, 버틴 5종목, 가장 덜 흔들린 5종목만 보내요. 그 밖의 칸은 ‘목록 밖’으로 비워 둬요.</p>
              {map.codes.length ? (
                <>
                  <div className="rk-mapwrap">
                    <table className="rk-map">
                      <thead><tr><th scope="col">종목</th>{scenarios.map((s) => <th key={s.id} scope="col" data-server>{s.label}</th>)}</tr></thead>
                      <tbody>
                        {map.codes.map((code) => (
                          <tr key={code}>
                            <th scope="row"><span className="rk-map-name">{map.names.get(code)}</span><span className="rk-map-code" data-mono>{code}</span></th>
                            {scenarios.map((s) => {
                              const c = map.cells.get(`${s.id}|${code}`);
                              const ok = !!okOf(s.id);
                              if (!c) {
                                const why = ok ? "목록 밖" : UNKNOWN_TEXT;
                                return (
                                  <td key={s.id} className="rk-cell" data-sc={s.id} data-code={code} {...(ok ? { "data-out": "" } : { "data-na": "" })} tabIndex={0}
                                      onFocus={() => setRead(`${map.names.get(code)}, ${s.label}: ${ok ? "서버 목록에 없어 값을 몰라요" : "이 충격의 결과를 받지 못했어요"}`)}>
                                    <span className="rk-cell-out">{why}</span>
                                  </td>
                                );
                              }
                              return (
                                <td key={s.id} className="rk-cell" data-sc={s.id} data-code={code} data-v={c.shock_pct} data-weak={c.survived ? undefined : ""} tabIndex={0}
                                    onFocus={() => setRead(`${c.corp_name}, ${s.label}: 점수 ${sgn(c.shock_pct)}% (${c.base_score} → ${c.stressed_score}) · ${c.survived ? "기준을 넘겨 버텼어요" : "취약해요"}`)}
                                    onMouseEnter={() => setRead(`${c.corp_name}, ${s.label}: 점수 ${sgn(c.shock_pct)}% (${c.base_score} → ${c.stressed_score}) · ${c.survived ? "기준을 넘겨 버텼어요" : "취약해요"}`)}>
                                  <span className="rk-cell-v" data-dir={dir(c.shock_pct)}>{sgn(c.shock_pct)}%</span>
                                  <span className="rk-cell-bar" aria-hidden><i style={{ width: `${(Math.abs(c.shock_pct) / map.maxAbs) * 100}%` }} /></span>
                                  {!c.survived && <span className="rk-cell-weak">취약</span>}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="rk-map-read" aria-live="polite">{read ?? "칸에 초점을 두거나 올리면 그 종목의 점수 변화를 여기에 보여 줘요."}</p>
                </>
              ) : <p className="rk-wait">{pending ? "충격 결과를 기다리는 중이에요" : "칸 지도에 그릴 결과가 없어요"}</p>}
            </section>

            {sel && <Detail id={sel} label={byId[sel]?.meta.label ?? sel} q={byId[sel]?.q} onPick={(code) => router.push(`/insights?code=${code}`)} />}
          </>
        )}
    </div>
  );
}

function Detail({ id, label, q, onPick }: { id: string; label: string; q: UseQueryResult<StressRun> | undefined; onPick: (code: string) => void }) {
  const r: StressResult | undefined = q?.data?.analyzers?.stress_test;
  return (
    <section className="tx-sec rk-detail" aria-labelledby="rk-detail-h" data-sc={id}>
      <h2 id="rk-detail-h" className="tx-sec-t rk-detail-h"><span data-server>{label}</span> 자세히</h2>
      {!q || q.isPending ? <p className="rk-wait">계산하는 중이에요</p>
        : q.isError ? <RetryFail title="이 충격을 계산하지 못했어요" onRetry={() => q.refetch()} />
        : !r ? <p className="rk-reason">서버가 이 충격의 결과를 보내지 않았어요.</p>
        : !r.available ? <p className="rk-reason">서버가 이 충격을 계산하지 못했다고 답했어요: <span data-server>{r.error ?? r.reason ?? "사유를 받지 못했어요"}</span></p>
        : (
          <>
            <div className="tstat-grid rk-stats">
              <div className="tstat">
                <span className="tstat-key">버틴 종목</span>
                <span className="tstat-val">{r.n_survivors}/{r.n_stocks}</span>
                <span className="rk-stat-bar" aria-hidden><i style={{ width: `${(r.n_survivors / Math.max(1, r.n_stocks)) * 100}%` }} /></span>
              </div>
              <div className="tstat"><span className="tstat-key">취약 종목</span><span className="tstat-val">{r.n_casualties}종목</span></div>
              <div className="tstat"><span className="tstat-key">버틴 비율</span><span className="tstat-val">{r.survival_rate}%</span></div>
              <div className="tstat"><span className="tstat-key">평균 점수 변화</span><span className="tstat-val rk-dir" data-dir={dir(r.avg_shock_pct)}>{sgn(r.avg_shock_pct)}%</span></div>
            </div>
            <p className="rk-rule">종합점수가 {STRESS_WEAK_PCT}% 넘게 떨어지면 ‘취약’으로 셌어요(서버 기준).</p>

            <h3 className="rk-h3">취약 종목(점수가 많이 떨어진 순)</h3>
            {r.casualties.length ? (
              <div className="rk-tablewrap">
                <table className="trisk-table rk-table">
                  <thead><tr><th scope="col">종목</th><th scope="col" className="num">점수 변화</th><th scope="col">크기</th><th scope="col" className="num">충격 뒤 점수</th></tr></thead>
                  <tbody>
                    {r.casualties.map((c) => (
                      <tr key={c.stock_code} data-code={c.stock_code} tabIndex={0} onClick={() => onPick(c.stock_code)}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(c.stock_code); } }}>
                        <td><span className="rk-map-name">{c.corp_name}</span><span className="rk-map-code" data-mono>{c.stock_code}</span></td>
                        <td className="num"><span className="rk-dir" data-dir={dir(c.shock_pct)}>{sgn(c.shock_pct)}%</span></td>
                        <td><div className="tsurvival-wrap"><div className="tsurvival-bar"><div className="tsurvival-fill" style={{ width: `${Math.min(100, Math.abs(c.shock_pct) * 3)}%` }} /></div></div></td>
                        <td className="num">{c.base_score} → {c.stressed_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="rk-reason">이 충격에서 기준을 넘겨 떨어진 종목은 없어요.</p>}

            <div className="rk-lists">
              <div>
                <h3 className="rk-h3">가장 덜 흔들린 종목</h3>
                <ul className="rk-chiplist">{r.most_resilient.map((c) => (
                  <li key={c.stock_code}><button type="button" className="rk-chip" onClick={() => onPick(c.stock_code)}>{c.corp_name} <b className="rk-dir" data-dir={dir(c.shock_pct)}>{sgn(c.shock_pct)}%</b></button></li>))}</ul>
              </div>
              <div>
                <h3 className="rk-h3">기준을 겨우 넘긴 종목</h3>
                <ul className="rk-chiplist">{r.survivors.map((c) => (
                  <li key={c.stock_code}><button type="button" className="rk-chip" onClick={() => onPick(c.stock_code)}>{c.corp_name} <b className="rk-dir" data-dir={dir(c.shock_pct)}>{sgn(c.shock_pct)}%</b></button></li>))}</ul>
              </div>
            </div>

            <details className="rk-how">
              <summary>어떻게 쟀나요</summary>
              <p>부채비율·PER·배당수익률·ROE 와 1년 베타로 충격마다 종합점수가 얼마나 바뀌는지 추정해요. 가격이 얼마나 떨어지는지는 재지 않았어요.</p>
              <p>부채·PER·배당·ROE 를 모르는 종목은 서버가 정한 기본값으로 채워 계산하고, 베타를 모르면 베타 효과를 0 으로 둬요.</p>
              {r.note && <p><span className="rk-k">서버 설명</span> <span data-server>{r.note}</span></p>}
            </details>
          </>
        )}
    </section>
  );
}
