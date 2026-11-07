"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 데이터 상태(BU7b · 사용자 결정 "적재 확인 창 + 서버 권한은 별도 작업")
// ─────────────────────────────────────────────────────────────────────────────
// 위에서 아래로: 답 한 문장(원천별 연구 등급 세기) → 원천별 연구 등급 → 연결된 원천 → 도구 준비 → 표별 적재 →
//   ★유니버스 적재 진행 막대★ → 적재 등록부 → 매크로 토큰 → 종목 커버리지 세기 → 적재(확인 창) · 연결 진단.
// ★지키는 것★
//   · 실패(닿지 못함) ≠ 비어 있음 ≠ 몰라요. 옛 화면은 출처 등급 실패를 삼켜 절이 조용히 사라졌고, 새로고침·폴링 실패는
//     옛 값이 있으면 숨겼고(낡은 값이 새 값처럼), 불러오기 전/실패 때 실행 모드를 연습용으로 그렸다(모름 ≠ 연습용).
//   · ★적재는 확인 창을 거친다★ 옛 "전체 적재"는 누르는 즉시 몇 시간짜리 적재 + 전자공시 하루 한도를 썼다.
//     확인하면 옛 화면과 같은 요청 하나(`POST /api/v1/data/ingest/{target}` 본문 `{}`) — 취소하면 요청 0.
//   · 목록(표·적재 대상)은 서버 레지스트리가 낸다(`db-status.datasets`) — 이 파일은 이름 번역만 든다.
//   · 실행 모드 배지(`t-mode-badge`)는 ★데이터 축이 아니라 실행 모드★(배지 축 레지스트리 pytest) — 데이터 연습용 표시는 등급 절이 말한다.
// 서버 권한(적재·진단 라우트 관리자 전용)은 이 화면 작업 밖이다 — 별도 작업 카드.
// ═══════════════════════════════════════════════════════════════════════════════
import { Fragment, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { api } from "@/shared/api/legacyApi";
import { STATUS_LABEL, USAGE_LABEL, USAGE_REASON } from "@/entities/regime-snapshot/model";
import type { DataStatus, ResearchUsage } from "@/entities/regime-snapshot/model";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/shared/ui/shadcn/dialog";
import { Answer, Notice, PageHead, RetryFail, type Chip, type Figure } from "@/shared/ui/tx";
import { UNKNOWN_TEXT } from "@/shared/lib/krFormat";

type DbStatus = Awaited<ReturnType<typeof api.dbStatus>>;
type Honesty = Awaited<ReturnType<typeof api.sourceHonesty>>;
type Dataset = NonNullable<DbStatus["datasets"]>[number];
type Cell = number | string | null | undefined;

/** 표 이름 — 레지스트리를 못 읽었을 때도 키만 나열하지 않게. 목록의 근거가 아니다(목록은 서버 `tables`). */
const TABLE_KO: Record<string, string> = {
  daily_prices: "주식 일봉",
  index_kospi_kosdaq: "지수(코스피·코스닥)",
  etf_cross_asset: "자산군 ETF",
  investor_flows: "투자자 수급",
  factor_snapshot: "펀더멘털 스냅샷",
  financials_history: "재무 시계열",
  financials_vintages: "재무 정정 이력(빈티지)",
};
/** 키·연결 이름(서버 `config`). 모르는 키는 서버 이름 그대로 — 지어내지 않는다. */
const KEY_KO: Record<string, string> = {
  kis_real: "한국투자증권 실제 시세",
  dart_key: "전자공시(DART)",
  krx_key: "한국거래소(KRX)",
  bok_key: "한국은행 경제통계(ECOS)",
  fred_key: "미국 연준 경제자료(FRED)",
};
const DOCTOR_KO = { dart: "전자공시(DART)", krx: "한국거래소(KRX)", kis: "한국투자증권(KIS)" } as const;
const UNIVERSE_KO: Record<string, string> = {
  kospi: "코스피", kosdaq: "코스닥", etf: "ETF(시세만 적재해요, 재무 적재 대상이 아니에요)", all_listed: "전체 상장 종목",
};

const n = (v: number) => v.toLocaleString("ko-KR");
const clock = (t: number) => (t ? new Date(t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : UNKNOWN_TEXT);
const Unk = () => <span className="dsx-unk">{UNKNOWN_TEXT}</span>;
const cellNum = (v: Cell): ReactNode => (typeof v === "number" ? n(v) : v == null ? <Unk /> : <span data-server>{String(v)}</span>);
const err = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** 서버 글의 `**굵게**` 만 굵게로(글자는 고치지 않는다). */
function ServerText({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <Fragment key={i}>{p}</Fragment>))}</>;
}

/** 원래 사유는 지우지 않고 닫힌 칸 안에 그대로. */
function RawWhy({ raw }: { raw: string }) {
  return (
    <details className="dsx-raw">
      <summary>원래 사유 보기</summary>
      <p data-server>{raw}</p>
    </details>
  );
}

function period(t: Record<string, Cell>): ReactNode {
  const rows = t.rows ?? t.loaded;
  if (t.start == null && t.end == null) return rows === 0 ? <span className="dsx-mute">비어 있어요</span> : <Unk />;
  return <>{t.start ?? UNKNOWN_TEXT} ~ {t.end ?? UNKNOWN_TEXT}</>;
}

export default function DbStatusPanel() {
  // 적재가 돌면 5초마다 다시 묻는다(옛 화면과 같은 주기). 실패해도 옛 값은 react-query 가 들고 있다 — 그때는 낡았다고 말한다.
  const db = useQuery({
    queryKey: ["data", "db-status"], queryFn: () => api.dbStatus(), retry: false,
    refetchInterval: (q) => (Object.values(q.state.data?.ingest_running ?? {}).some(Boolean) ? 5000 : false),
  });
  const hon = useQuery({ queryKey: ["data", "source-honesty"], queryFn: () => api.sourceHonesty(), retry: false });
  const st = db.data;
  const running = st?.ingest_running ?? {};
  const anyRunning = Object.values(running).some(Boolean);

  // ── 실행 모드(데이터 축이 아니다) ──
  const realAttr = st ? (st.config?.kis_real ? "1" : "0") : undefined;
  const modeText = db.isPending ? "실행 모드를 확인하는 중이에요"
    : !st ? "실행 모드를 몰라요"
    : st.config?.kis_real ? "실제 시세로 돌아요"
    : hon.data?.mock_mode === true ? "연습용 시세로 돌아요"
    : hon.data?.mock_mode === false ? "실제 시세 연결이 없어요"
    : "실제 시세 연결이 아니에요";

  // ── 답: 원천별 연구 등급 세기 ──
  const srcs = hon.data?.sources ?? [];
  const cnt = (u: string) => srcs.filter((s) => s.research_usage === u).length;
  const m = cnt("backtest_eligible");
  const sentence = hon.isPending ? "원천별 연구 등급을 확인하는 중이에요."
    : hon.isError ? "원천별 연구 등급을 받지 못해 몇 개를 연구에 쓸 수 있는지 아직 몰라요."
    : srcs.length === 0 ? "서버가 알려 준 데이터 원천이 없어요."
    : m > 0 ? `데이터 원천 ${srcs.length}개 중 ${m}개를 과거 검증에 쓸 수 있어요.`
    : `데이터 원천 ${srcs.length}개 중 과거 검증에 쓸 수 있는 원천은 아직 없어요.`;
  const figures: Figure[] = hon.data && srcs.length ? [
    { label: USAGE_LABEL.backtest_eligible, value: `${m}개` },
    { label: USAGE_LABEL.forward_only, value: `${cnt("forward_only")}개` },
    { label: USAGE_LABEL.unavailable, value: `${cnt("unavailable")}개` },
  ] : [];
  if (st) figures.push({ label: "적재 중", value: `${Object.values(running).filter(Boolean).length}개` });
  const chips: Chip[] = [{ label: "가져올 수 있는 것과 과거 검증에 쓸 수 있는 것은 따로 매겨요", tone: "info" }];
  if (st) chips.push({ label: `${clock(db.dataUpdatedAt)}에 받은 값`, tone: "plain" });

  // ── 적재 확인 창 ──
  const [ask, setAsk] = useState<{ target: string; label: string; ds: Dataset[] } | null>(null);
  const [res, setRes] = useState<Record<string, { ok: true; text: string; server?: string } | { ok: false; raw: string }>>({});
  const ingest = useMutation({
    mutationFn: (target: string) => api.ingest(target),
    onSuccess: (r, target) => {
      setRes((p) => ({ ...p, [target]: r.started.length ? { ok: true, text: "적재를 시작했어요.", server: r.message } : { ok: true, text: "이미 실행 중이에요. 새로 시작하지 않았어요.", server: r.message } }));
      void db.refetch();
    },
    onError: (e, target) => setRes((p) => ({ ...p, [target]: { ok: false, raw: err(e) } })),
  });
  const doctor = useMutation({ mutationFn: () => api.ingestDoctor() });

  // ── 종목 커버리지(무거운 집계 — 눌러야 돈다) ──
  const [covTarget, setCovTarget] = useState("stocks");
  const [covStart, setCovStart] = useState("2020-01-01");
  const [covEnd, setCovEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const cov = useMutation({ mutationFn: () => api.dataCoverage(covTarget, covStart, covEnd) });

  const datasets = st?.datasets ?? [];
  const triggerable = datasets.filter((d) => d.triggerable);
  const dsLabel = (k: string) => datasets.find((d) => d.key === k)?.label ?? k;
  const toolEntries = st ? Object.entries(st.tools) : [];
  const toolsReady = toolEntries.filter(([, ok]) => ok).length;
  const refresh = () => { void db.refetch(); void hon.refetch(); };

  return (
    <div className="dsx tx-page">
      <PageHead title="데이터 상태" lede="어떤 데이터가 연결되고 적재됐는지, 연구에 쓸 수 있는지 봐요."
        actions={(
          <div className="dsx-head-act">
            <span className="t-mode-badge" data-real={realAttr}>{modeText}</span>
            <button type="button" className="tx-btn tx-btn--sub dsx-refresh" onClick={refresh} disabled={db.isFetching}>
              <RefreshCw size={16} aria-hidden />{db.isFetching ? "받는 중이에요" : "새로 받기"}
            </button>
          </div>
        )} />
      <Answer sentence={sentence} figures={figures} chips={chips} />

      {db.isError && st ? (
        <Notice tone="warn" title={`마지막으로 받은 값이에요(${clock(db.dataUpdatedAt)}). 새 값을 받지 못했어요.`}>
          <span data-server>{err(db.error)}</span>
          <div className="ms-act"><button type="button" className="tx-btn tx-btn--sub" onClick={() => void db.refetch()}>다시 시도</button></div>
        </Notice>
      ) : null}

      {/* ── 원천별 연구 등급 — ★"가져올 수 있다" 와 "과거 검증에 쓸 수 있다" 는 다른 축★(§3.5). 두 칩을 따로 둔다. ── */}
      <section className="tx-sec t-honesty" aria-labelledby="dsx-hon-h">
        <h2 id="dsx-hon-h" className="tx-sec-t t-honesty-h">원천별 연구 등급</h2>
        <p className="tx-sec-sub">가져올 수 있는지(왼쪽 칩)와 과거 검증에 쓸 수 있는지(오른쪽 칩)를 따로 매겨요.</p>
        {srcs.length ? (
          <dl className="dsx-legend">
            {(["backtest_eligible", "forward_only", "unavailable"] as const).filter((u) => srcs.some((s) => s.research_usage === u)).map((u) => (
              <div key={u}><dt><span className={`dsx-legend-k u-${u}`}>{USAGE_LABEL[u]}</span></dt><dd>{USAGE_REASON[u]}</dd></div>
            ))}
          </dl>
        ) : null}
        {hon.isError ? <RetryFail title="원천별 연구 등급을 불러오지 못했어요" onRetry={() => void hon.refetch()} />
          : hon.isPending ? <p className="dsx-wait">원천별 연구 등급을 불러오는 중이에요</p>
          : (
            <ul className="t-honesty-list">
              {srcs.map((sc) => (
                <li key={sc.id} className="t-honesty-row">
                  <span className="t-honesty-nm" data-server>{sc.label}</span>
                  <span className="dsx-hon-chips">
                    <span className={`t-honesty-st s-${sc.data_status}`}>{STATUS_LABEL[sc.data_status as DataStatus] ?? sc.data_status}</span>
                    <span className={`t-honesty-use u-${sc.research_usage}`}>{USAGE_LABEL[sc.research_usage as ResearchUsage] ?? sc.research_usage}</span>
                  </span>
                  {USAGE_REASON[sc.research_usage as ResearchUsage] ? null : <span className="dsx-hon-use">이 등급의 뜻을 화면이 몰라요.</span>}
                  <span className="t-honesty-why" data-server>{sc.reason}</span>
                </li>
              ))}
            </ul>
          )}
      </section>

      {db.isError && !st ? <RetryFail title="데이터 상태를 불러오지 못했어요" onRetry={() => void db.refetch()} />
        : db.isPending ? <p className="dsx-wait">적재 현황을 점검하는 중이에요</p>
        : st ? (
          <>
            {!st.available && (
              <Notice tone="warn" title="서버가 적재 저장소에 연결하지 못했어요">
                그래서 표별 적재와 도구 준비 상태는 몰라요. 키 연결과 적재 등록부는 아래에 그대로 보여요.
              </Notice>
            )}

            <section className="tx-sec dsx-keys" aria-labelledby="dsx-keys-h">
              <h2 id="dsx-keys-h" className="tx-sec-t">연결된 데이터 원천</h2>
              <p className="tx-sec-sub">키가 있다고 데이터가 오는 것은 아니에요. 실제로 닿는지는 아래 ‘연결 진단’에서 봐요.</p>
              <ul className="dsx-keylist">
                {Object.entries(st.config).map(([k, v]) => (
                  <li key={k} className="dsx-key" data-on={v ? "1" : "0"}>
                    <span className="dsx-key-nm">{KEY_KO[k] ?? <span data-mono>{k}</span>}</span>
                    <span className="dsx-key-st">{k === "kis_real" ? (v ? "연결됐어요" : "연결되지 않았어요") : v ? "키 있음" : "키 없음"}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="tx-sec dsx-tools" aria-labelledby="dsx-tools-h">
              <h2 id="dsx-tools-h" className="tx-sec-t">도구 준비</h2>
              {toolEntries.length ? (
                <>
                  <p className="tx-sec-sub">도구 {toolEntries.length}개 중 {toolsReady}개가 적재된 데이터로 돌 수 있어요.</p>
                  <ul className="dsx-toollist">
                    {toolEntries.map(([k, ok]) => (
                      <li key={k} className="dsx-tool" data-ok={ok ? "1" : "0"}>
                        <span data-server>{k}</span><span className="dsx-tool-st">{ok ? "쓸 수 있어요" : "데이터가 부족해요"}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : <p className="dsx-reason">서버가 도구 준비 상태를 보내지 않았어요. 적재 저장소를 읽지 못하면 비어 있어요.</p>}
            </section>

            <section className="tx-sec dsx-tables" aria-labelledby="dsx-tbl-h">
              <h2 id="dsx-tbl-h" className="tx-sec-t">표별 적재</h2>
              {Object.keys(st.tables).length ? (
                <div className="dsx-tablewrap">
                  <table className="trisk-table">
                    <thead><tr><th scope="col">표</th><th scope="col" className="num">행 수</th><th scope="col" className="num">종목</th><th scope="col">기간(처음 ~ 마지막)</th></tr></thead>
                    <tbody>
                      {Object.entries(st.tables).map(([key, t]) => {
                        const c = t as Record<string, Cell>;
                        const rows = "rows" in c ? c.rows : c.loaded;
                        return (
                          <tr key={key} data-table={key}>
                            <td>
                              {TABLE_KO[key] ?? <span data-mono>{key}</span>}
                              {typeof c.reason === "string" && c.reason ? (
                                <div className="dsx-cellwhy"><span>이 표를 읽지 못했어요.</span><RawWhy raw={c.reason} /></div>
                              ) : null}
                            </td>
                            <td className="num">{cellNum(rows)}{c.total != null ? <span className="dsx-mute"> / {cellNum(c.total)}</span> : null}</td>
                            <td className="num">{"tickers" in c ? cellNum(c.tickers) : <span className="dsx-mute">해당 없음</span>}</td>
                            <td>{"start" in c || "end" in c ? period(c) : <span className="dsx-mute">해당 없음</span>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : <p className="dsx-reason">서버가 표별 적재 현황을 보내지 않았어요.</p>}
            </section>

            {/* 새 그림 — 유니버스마다 적재/전체 막대. ★전체가 0 이면 0% 가 아니라 몰라요★ */}
            <section className="tx-sec dsx-uni" aria-labelledby="dsx-uni-h">
              <h2 id="dsx-uni-h" className="tx-sec-t">유니버스 적재 진행</h2>
              <p className="tx-sec-sub">종목 마스터의 종목 수 중 펀더멘털 스냅샷이 쌓인 종목 수예요.</p>
              {st.universe_progress && Object.keys(st.universe_progress.progress ?? {}).length ? (
                <ul className="dsx-unilist">
                  {(["kospi", "kosdaq", "etf", "all_listed"] as const).map((k) => {
                    const p = st.universe_progress!.progress[k];
                    if (!p) return null;
                    const known = p.master > 0;
                    const pct = known ? Math.min(100, (p.ingested / p.master) * 100) : null;
                    return (
                      <li key={k} className="dsx-uni-row" data-uni={k}>
                        <span className="dsx-uni-nm">{UNIVERSE_KO[k]}</span>
                        <span className="dsx-uni-bar" aria-hidden>{pct != null ? <i style={{ width: `${pct}%` }} /> : null}</span>
                        <span className="dsx-uni-n">
                          {known ? <>{n(p.ingested)} / {n(p.master)}종목 · {Math.round(pct!)}%</>
                            : <>{n(p.ingested)}종목 적재 · 전체 수를 {UNKNOWN_TEXT}</>}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="dsx-reason">서버가 유니버스 적재 진행을 보내지 않았어요. 종목 마스터를 읽지 못했거나 스냅샷 저장소가 비어 있어요.</p>}
            </section>

            <section className="tx-sec dsx-reg" aria-labelledby="dsx-reg-h">
              <h2 id="dsx-reg-h" className="tx-sec-t">적재 등록부</h2>
              <p className="tx-sec-sub">무엇이 어디서 와서 어디에 쌓이는지예요. 목록은 서버가 정해요.</p>
              {st.datasets === null ? (
                <Notice tone="warn" title="적재 등록부를 읽지 못했어요">{st.datasets_error ? <RawWhy raw={st.datasets_error} /> : "서버가 사유를 보내지 않았어요."}</Notice>
              ) : datasets.length ? (
                <div className="dsx-tablewrap">
                  <table className="trisk-table">
                    <thead><tr><th scope="col">데이터</th><th scope="col">출처</th><th scope="col">저장 위치</th><th scope="col">필요한 키</th><th scope="col">없으면 못 쓰는 도구</th></tr></thead>
                    <tbody>
                      {datasets.map((d) => (
                        <tr key={d.key} data-ds={d.key}>
                          <td>
                            <span data-server>{d.label}</span>
                            {!d.triggerable && <span className="dsx-mute"> · 여기서 적재하지 않아요</span>}
                            {d.note && <div className="dsx-note" data-server><ServerText text={d.note} /></div>}
                          </td>
                          <td data-server>{d.source}</td>
                          <td><span data-mono>{d.table}</span>{d.slice_of && <div className="dsx-note">그 안의 일부: <span data-mono>{d.slice_of}</span></div>}</td>
                          <td>
                            {d.required_env.length === 0 ? <span className="dsx-mute">필요 없어요</span> : (
                              <>
                                <span className="dsx-env" data-ready={d.env_ready == null ? "" : d.env_ready ? "1" : "0"}>{d.env_ready == null ? UNKNOWN_TEXT : d.env_ready ? "키 있음" : "키 없음"}</span>
                                <div className="dsx-note">{d.required_env.map((e) => <span key={e} data-mono>{e}</span>)}</div>
                              </>
                            )}
                          </td>
                          <td data-server>{d.tools.join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="dsx-reason">등록된 적재 대상이 없어요.</p>}
            </section>

            {st.macro ? (
              <section className="tx-sec dsx-macro" aria-labelledby="dsx-macro-h">
                <h2 id="dsx-macro-h" className="tx-sec-t">매크로 토큰</h2>
                <p className="tx-sec-sub" data-server><ServerText text={st.macro.note} /></p>
                {Object.keys(st.macro.unavailable).length === 0 ? (
                  <p className="dsx-reason">실패로 기록된 토큰이 없어요{st.macro.ok.length ? `. 조회에 성공한 토큰은 ${st.macro.ok.length}개예요.` : "."}</p>
                ) : (
                  <div className="dsx-tablewrap">
                    <table className="trisk-table">
                      <thead><tr><th scope="col">토큰</th><th scope="col">못 쓴 이유</th></tr></thead>
                      <tbody>
                        {Object.entries(st.macro.unavailable).map(([k, v]) => (
                          <tr key={k}><td><span data-mono>{k}</span></td><td data-server>{v.reason}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            ) : null}

            {/* ★온디맨드★ 일봉은 수백만 행이라 화면을 여는 것만으로 세지 않는다. */}
            <section className="tx-sec dsx-cov" aria-labelledby="dsx-cov-h">
              <h2 id="dsx-cov-h" className="tx-sec-t">종목 커버리지 세기</h2>
              <p className="tx-sec-sub">적재됐다와 충분히 적재됐다는 달라요. 기간을 덮는 종목이 몇 개인지 세요. 무거운 집계라 눌러야 돌아요.</p>
              <div className="dsx-form">
                <label className="dsx-field"><span>데이터</span>
                  <select className="dsx-input" value={covTarget} onChange={(e) => setCovTarget(e.target.value)}>
                    {datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
                  </select>
                </label>
                <label className="dsx-field"><span>시작일</span><input className="dsx-input" type="date" value={covStart} onChange={(e) => setCovStart(e.target.value)} /></label>
                <label className="dsx-field"><span>끝일</span><input className="dsx-input" type="date" value={covEnd} onChange={(e) => setCovEnd(e.target.value)} /></label>
                <button type="button" className="tx-btn tx-btn--sub dsx-cov-go" disabled={cov.isPending} onClick={() => cov.mutate()}>
                  {cov.isPending ? "세는 중이에요" : "커버리지 세기"}
                </button>
              </div>
              {cov.isError ? <RetryFail title="커버리지를 세지 못했어요" onRetry={() => cov.mutate()}><span data-server>{err(cov.error)}</span></RetryFail>
                : cov.data ? (
                  cov.data.measured ? (
                    <div className="dsx-cov-out">
                      <p><b data-server>{cov.data.label}</b>: {cellNum(cov.data.tickers_total)}종목 중 {cellNum(cov.data.tickers_covering)}종목이 {cov.data.start} ~ {cov.data.end}를 덮어요{cov.data.covering_pct != null ? `(${cov.data.covering_pct}%)` : ""}.</p>
                      {cov.data.covering_pct != null && <span className="dsx-uni-bar" aria-hidden><i style={{ width: `${Math.min(100, cov.data.covering_pct)}%` }} /></span>}
                    </div>
                  ) : <p className="dsx-reason"><b data-server>{cov.data.label}</b>: 세지 못했어요. <span data-server>{cov.data.reason ?? "서버가 사유를 보내지 않았어요."}</span></p>
                ) : null}
            </section>

            <section className="tx-sec dsx-ing" aria-labelledby="dsx-ing-h">
              <h2 id="dsx-ing-h" className="tx-sec-t">적재</h2>
              <p className="tx-sec-sub">적재는 서버 뒤에서 돌아요. 큰 백필은 몇 시간 걸릴 수 있고, 키가 없는 원천은 서버가 건너뛰어요. 누르면 먼저 확인을 받아요.</p>
              <ul className="dsx-inglist">
                {triggerable.map((d) => {
                  const s = st.ingest_status?.[d.key];
                  const r = res[d.key];
                  return (
                    <li key={d.key} className="dsx-ing-row" data-ds={d.key}>
                      <div className="dsx-ing-main">
                        <span className="dsx-ing-nm" data-server>{d.label}</span>
                        <span className="dsx-ing-sub"><span data-server>{d.source}</span>에서 <span data-mono>{d.table}</span>로</span>
                        {s ? <IngestLine s={s} /> : null}
                      </div>
                      <button type="button" className="tx-btn tx-btn--sub dsx-ing-go" data-act={`ingest-${d.key}`} disabled={!!running[d.key]}
                        onClick={() => setAsk({ target: d.key, label: d.label, ds: [d] })}>
                        {running[d.key] ? "적재하는 중이에요" : "적재하기"}
                      </button>
                      {r ? <IngestResult r={r} /> : null}
                    </li>
                  );
                })}
                <li className="dsx-ing-row dsx-ing-row--all" data-ds="all">
                  <div className="dsx-ing-main">
                    <span className="dsx-ing-nm">전체 적재</span>
                    <span className="dsx-ing-sub">위의 {triggerable.length}개를 한꺼번에 시작해요. 이미 도는 것은 건너뛰어요.</span>
                  </div>
                  <button type="button" className="tx-btn tx-btn--sub dsx-ing-go" data-act="ingest-all" disabled={anyRunning}
                    onClick={() => setAsk({ target: "all", label: "전체", ds: triggerable })}>
                    {anyRunning ? "적재하는 중이에요" : "전체 적재하기"}
                  </button>
                  {res.all ? <IngestResult r={res.all} /> : null}
                </li>
              </ul>
              {st.ingest_status && Object.keys(st.ingest_status).some((k) => !triggerable.find((d) => d.key === k)) ? (
                <ul className="dsx-inglist">
                  {Object.entries(st.ingest_status).filter(([k]) => !triggerable.find((d) => d.key === k)).map(([k, s]) => (
                    <li key={k} className="dsx-ing-row"><div className="dsx-ing-main"><span className="dsx-ing-nm" data-server>{dsLabel(k)}</span><IngestLine s={s} /></div></li>
                  ))}
                </ul>
              ) : null}

              {st.dart_usage ? (
                <div className="dsx-dart">
                  <p>전자공시 요청 {n(st.dart_usage.requests)}건 · 오류 {n(Object.values(st.dart_usage.errors).reduce((a, b) => a + b, 0))}건(서버가 켜진 뒤부터 센 값이에요)</p>
                  {st.dart_usage.quota_exhausted && <Notice tone="warn" title="전자공시 하루 요청 한도에 닿았어요">적재가 저절로 멈췄어요. 내일 다시 실행하면 이어서 적재해요.</Notice>}
                  {st.dart_usage.last_error && <p className="dsx-note">최근 오류: <span data-server>[{st.dart_usage.last_error.status}] {st.dart_usage.last_error.message}</span></p>}
                </div>
              ) : <p className="dsx-reason">전자공시 사용량을 받지 못했어요.</p>}
              <p className="dsx-note">펀더멘털과 재무 시계열은 전자공시 하루 한도를 나눠 써요. 함께 돌리면 한도에 빨리 닿아요(재무 시계열을 끝낸 뒤 펀더멘털을 권해요).</p>
            </section>

            <section className="tx-sec dsx-doc" aria-labelledby="dsx-doc-h">
              <h2 id="dsx-doc-h" className="tx-sec-t">연결 진단</h2>
              <p className="tx-sec-sub">원천마다 가벼운 요청을 한 번씩 보내 실제로 닿는지 봐요. 전자공시 하루 한도를 1건 써요.</p>
              <button type="button" className="tx-btn tx-btn--sub" data-act="doctor" disabled={doctor.isPending} onClick={() => doctor.mutate()}>
                {doctor.isPending ? "진단하는 중이에요" : "연결 진단하기"}
              </button>
              {doctor.isError ? <RetryFail title="연결 진단을 하지 못했어요" onRetry={() => doctor.mutate()}><span data-server>{err(doctor.error)}</span></RetryFail>
                : doctor.data ? (
                  <ul className="dsx-doclist">
                    {(["dart", "krx", "kis"] as const).map((s) => (
                      <li key={s} className="dsx-doc-row" data-ok={doctor.data[s].ok ? "1" : "0"}>
                        <span className="dsx-doc-nm">{DOCTOR_KO[s]}</span>
                        <span className="dsx-doc-st">{doctor.data[s].ok ? "닿았어요" : "닿지 못했어요"}</span>
                        <span className="dsx-note" data-server>{doctor.data[s].message}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
            </section>
          </>
        ) : null}

      <Dialog open={!!ask} onOpenChange={(o) => { if (!o) setAsk(null); }}>
        <DialogContent className="dsx-dlg">
          {ask ? (
            <>
              <DialogTitle className="dsx-dlg-t">{ask.target === "all" ? "전체 적재를 시작할까요?" : `‘${ask.label}’ 적재를 시작할까요?`}</DialogTitle>
              <DialogDescription className="dsx-dlg-d">서버 뒤에서 돌고, 끝날 때까지 이 화면이 5초마다 진행을 다시 받아요.</DialogDescription>
              <ul className="dsx-dlg-list">
                <li><b>무엇을</b><span className="dsx-dlg-what">{ask.ds.length ? ask.ds.map((d) => <span key={d.key}>{d.label} · {d.source}</span>) : "등록된 대상이 없어요"}</span></li>
                <li><b>얼마나</b><span>큰 백필은 몇 시간 걸릴 수 있어요.</span></li>
                {ask.ds.some((d) => d.source.includes("DART")) && <li><b>한도</b><span>전자공시(DART) 하루 요청 한도를 함께 써요.</span></li>}
                {ask.ds.some((d) => d.env_ready === false) && (
                  <li><b>키</b><span>필요한 키가 없는 대상({ask.ds.filter((d) => d.env_ready === false).map((d) => d.label).join(", ")})은 서버가 건너뛰어요.</span></li>
                )}
              </ul>
              <div className="dsx-dlg-act">
                <button type="button" className="tx-btn tx-btn--sub" onClick={() => setAsk(null)}>취소</button>
                <button type="button" className="tx-btn tx-btn--main" data-act="ingest-confirm"
                  onClick={() => { const t = ask.target; setAsk(null); setRes((p) => { const { [t]: _drop, ...rest } = p; void _drop; return rest; }); ingest.mutate(t); }}>
                  적재 시작
                </button>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function IngestLine({ s }: { s: NonNullable<DbStatus["ingest_status"]>[string] }) {
  const p = s.progress;
  const pct = p && p.total ? Math.min(100, ((p.done ?? 0) / p.total) * 100) : null;
  return (
    <span className="dsx-ing-st">
      <span>{s.running ? "적재하는 중이에요" : s.finished_at ? `${s.finished_at}에 끝났어요` : "기다리는 중이에요"}</span>
      {p ? (
        <>
          <span className="dsx-ing-prog">
            {p.stage ? <span data-server>{p.stage}</span> : null} {p.total ? `${n(p.done ?? 0)} / ${n(p.total)}` : `${n(p.done ?? 0)}개 처리 · 전체 수를 ${UNKNOWN_TEXT}`} · 저장 {n(p.saved ?? 0)} · 실패 {n(p.failures ?? 0)}
          </span>
          {pct != null ? <span className="dsx-uni-bar dsx-ing-bar" aria-hidden><i style={{ width: `${pct}%` }} /></span> : null}
        </>
      ) : null}
      {s.last_error ? <span className="dsx-ing-err">마지막 오류: <span data-server>{s.last_error}</span></span> : null}
    </span>
  );
}

function IngestResult({ r }: { r: { ok: true; text: string; server?: string } | { ok: false; raw: string } }) {
  if (!r.ok) return <div className="dsx-ing-res"><Notice tone="danger" title="적재를 시작하지 못했어요"><span data-server>{r.raw}</span></Notice></div>;
  return <p className="dsx-ing-res dsx-ing-ok" role="status">{r.text}{r.server ? <> <span className="dsx-mute" data-server>({r.server})</span></> : null}</p>;
}
