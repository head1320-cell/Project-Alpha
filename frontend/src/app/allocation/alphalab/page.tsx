"use client";
// 02 ALPHA LAB — 알파 표현식 작성·lint·IC/ICIR 검증·레지스트리 (Full Expansion P2).
// 좌: 표현식 에디터(통합 팩터 창 + lint) + 레지스트리(검색·상태 필터·인라인 승격)
// 우: 검증 리포트(IC·ICIR·t·Hit·Decay + 분위 막대 + 롱숏 곡선 + IS/OOS + 정직 노트)
//    + "상위 종목 → 포트폴리오" 브릿지(01 Construct와 연결).
import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  alphaApi, type AlphaDef, type AlphaStatus, type AlphaValidationReport, type LintResult,
} from "@/entities/alpha/api";
import { equalize } from "@/widgets/allocation/PortfolioBuilder";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { AutoAlphaLab } from "@/widgets/allocation/AutoAlphaLab";
import { AlphaFactorModal } from "@/widgets/allocation/AlphaFactorModal";
import { LintBadges, LsCurve, QuantileBars } from "@/widgets/allocation/AlphaLabParts";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/shared/ui/shadcn/table";
import { ArchiveDrawer } from "@/shared/ui/ArchiveDrawer";

const STATUS_LABEL: Record<AlphaStatus, string> = {
  draft: "초안", experimental: "실험", validated: "검증됨", approved: "승인", retired: "폐기",
};
const STATUS_NEXT: Partial<Record<AlphaStatus, AlphaStatus>> = {
  draft: "experimental", experimental: "validated", validated: "approved",
};
const STATUS_ORDER: AlphaStatus[] = ["draft", "experimental", "validated", "approved", "retired"];
const UNIVERSES: [string, string][] = [
  ["kospi50", "KOSPI 50"], ["kospi200", "KOSPI 200"], ["kosdaq150", "KOSDAQ 150"],
];

export default function AlphaLabStage() {
  const router = useRouter();
  const { setHoldingsReset, markAlphaTouched, logEvent } = useAllocation();
  const [expr, setExpr] = useState("zscore(mom_6m) - zscore(vol_60d)");
  const [universe, setUniverse] = useState("kospi50");
  const [months, setMonths] = useState(24);
  const [lint, setLint] = useState<LintResult | null>(null);
  const [report, setReport] = useState<AlphaValidationReport | null>(null);
  const [alphaName, setAlphaName] = useState("");
  const [selAlpha, setSelAlpha] = useState<string | null>(null);
  const [promoteNote, setPromoteNote] = useState("");
  const [regMsg, setRegMsg] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [regQuery, setRegQuery] = useState("");
  const [regStatus, setRegStatus] = useState<AlphaStatus | "all">("all");
  const [promoteFor, setPromoteFor] = useState<string | null>(null);

  const regQ = useQuery({ queryKey: ["alpha", "registry"], queryFn: () => alphaApi.registry().catch(() => null) });
  const alphas: AlphaDef[] = regQ.data?.alphas ?? [];

  const statusCounts = useMemo(() => {
    const c: Partial<Record<AlphaStatus, number>> = {};
    alphas.forEach((a) => { c[a.status] = (c[a.status] ?? 0) + 1; });
    return c;
  }, [alphas]);
  const visibleAlphas = useMemo(() => {
    const s = regQuery.trim().toLowerCase();
    return alphas.filter((a) =>
      (regStatus === "all" || a.status === regStatus) &&
      (!s || a.name.toLowerCase().includes(s) || (a.expr ?? "").toLowerCase().includes(s) ||
        (a.tags ?? []).some((t) => t.toLowerCase().includes(s))));
  }, [alphas, regQuery, regStatus]);

  const lintMut = useMutation({
    mutationFn: () => alphaApi.lint(expr),
    onSuccess: (d) => setLint(d),
  });
  const valMut = useMutation({
    mutationFn: () => alphaApi.validate({
      expr, universe, months, alpha_id: selAlpha ?? undefined, record_run: true,
    }),
    onSuccess: (d) => {
      setReport(d);
      if (!d.error) {
        markAlphaTouched();
        logEvent(`알파 검증 — IC ${d.ic?.mean ?? "—"} · ${expr.slice(0, 40)}`);
        if (selAlpha) regQ.refetch();
      }
    },
  });
  const saveMut = useMutation({
    mutationFn: () => alphaApi.upsert({
      alpha_id: selAlpha ?? undefined, name: alphaName.trim() || expr.slice(0, 40), expr, universe,
    }),
    onSuccess: (d) => {
      if (d.error) { setRegMsg(d.message ?? "저장 실패"); setLint(d.lint ?? null); return; }
      setRegMsg(null);
      setSelAlpha(d.alpha?.alpha_id ?? null);
      markAlphaTouched();
      logEvent(`알파 저장 — ${d.alpha?.name}`);
      regQ.refetch();
    },
  });

  const pickAlpha = (a: AlphaDef) => {
    setSelAlpha(a.alpha_id);
    setAlphaName(a.name);
    if (a.expr) setExpr(a.expr);
    setLint(null);
    setReport(null);
  };
  const doPromote = async (a: AlphaDef) => {
    const next = STATUS_NEXT[a.status];
    if (!next) return;
    const res = await alphaApi.promote(a.alpha_id, next, promoteNote).catch(() => null);
    if (!res) { setRegMsg("승격 요청 실패"); return; }
    setRegMsg(res.ok ? null : res.reason ?? "승격 불가");
    if (res.ok) { setPromoteNote(""); setPromoteFor(null); regQ.refetch(); }
  };

  const applyTop = () => {
    const top = (report?.latest_scores_top ?? []).slice(0, 10);
    if (top.length < 2) return;
    setHoldingsReset(equalize(top.map((t) => ({ code: t.ticker, name: t.name, weight: 0 }))));
    logEvent(`알파 상위 ${top.length}종목 → 포트폴리오`);
    router.push("/allocation/construct");
  };

  const ic = report && !report.error ? report.ic : null;

  // ★행 JSX 를 본문과 서랍이 **같이** 쓴다 (A7)★
  // 두 벌로 복사하면 한쪽만 고쳐지는 날이 온다 — 승격 칩 하나가 서랍에서만 사라지는
  // 식으로. 클로저 하나로 두고 목록 두 곳이 같은 것을 렌더한다.
  const alphaRow = (a: AlphaDef) => (
          <React.Fragment key={a.alpha_id}>
            {/* ★알파의 정체는 표현식이다 — 그게 title= 안에만 있었다 (A4-L3)★
                호버는 키보드·터치 사용자에게 존재하지 않는다. 목록에서 두 알파를
                구별하려면 이름 말고 식을 봐야 하는데, 그 식이 보이지 않았다.
                P3 가 ContextStrip 에서 고친 것과 같은 결함이다. */}
            <div className={`as-al-item${selAlpha === a.alpha_id ? " on" : ""}`}>
              <button className="as-al-pick" onClick={() => pickAlpha(a)}>
                <span className="as-al-name">
                  {a.name}
                  {a.is_template && <em className="as-al-tpl">TPL</em>}
                  <em className="num as-al-ver">v{a.version}</em>
                </span>
                {(a.expr || a.description) && (
                  <code className="as-al-expr-r">{a.expr || a.description}</code>
                )}
                <span className={`as-al-status s-${a.status}`}>{STATUS_LABEL[a.status]}</span>
              </button>
              {STATUS_NEXT[a.status] && !a.is_template && (
                <button className="as-chip sm" title={`→ ${STATUS_LABEL[STATUS_NEXT[a.status]!]} 승격`}
                  onClick={() => setPromoteFor(promoteFor === a.alpha_id ? null : a.alpha_id)}>
                  ↑ {STATUS_LABEL[STATUS_NEXT[a.status]!]}
                </button>
              )}
              {/* 글리프 하나짜리 버튼은 이름이 없으면 "× 버튼"으로만 읽힌다 —
                  A3 가 `.as-wrow-del` 에서 고친 것과 같다. */}
              {!a.is_template && (
                <button className="as-x" aria-label={`${a.name} 삭제`}
                  onClick={() => alphaApi.remove(a.alpha_id).then(() => regQ.refetch()).catch(() => {})}>×</button>
              )}
            </div>
            {/* 승격 노트를 승격 대상 행 바로 아래에 — 어떤 알파에 붙는 노트인지 모호하지 않게 */}
            {promoteFor === a.alpha_id && (
              <div className="as-al-promote">
                <input className="as-input" autoFocus value={promoteNote}
                  placeholder={`${STATUS_LABEL[a.status]} → ${STATUS_LABEL[STATUS_NEXT[a.status]!]} 사유 (approved는 필수)`}
                  onChange={(e) => setPromoteNote(e.target.value)} />
                <button className="as-fb-apply" onClick={() => doPromote(a)}>승격</button>
                <button className="as-chip sm" onClick={() => { setPromoteFor(null); setPromoteNote(""); }}>취소</button>
              </div>
            )}
          </React.Fragment>
  );

  // 본문에는 **지금 쓰는 것**만: 선택된 알파 + 초안/승인 + 최근 몇 개. 나머지는 서랍.
  const MAIN_MAX = 4;
  const shownAlphas = visibleAlphas.slice(0, MAIN_MAX);
  const archivedAlphas = visibleAlphas.slice(MAIN_MAX);

  return (
    <div className="as-ws2">
      {/* ── 좌: 에디터 + 레지스트리 ── */}
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">ALPHA EXPRESSION <span className="as-note-inline">크로스섹션 결합 — rank/zscore/sector_neutralize</span></div>
          <textarea className="as-input as-al-expr" rows={3} value={expr}
            onChange={(e) => { setExpr(e.target.value); setLint(null); }} spellCheck={false} />
          <div className="as-wl-row">
            <button className="as-fb-apply" onClick={() => setPickerOpen(true)}>+ 팩터 창에서 추가</button>
            <span className="as-note-inline">가격·펀더멘털 피처와 변환·중립화 연산자를 한 창에서 검색</span>
          </div>
          <div className="as-wl-row">
            <select className="as-fb-add" value={universe} onChange={(e) => setUniverse(e.target.value)}>
              {UNIVERSES.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
            </select>
            <select className="as-fb-add" value={months} onChange={(e) => setMonths(parseInt(e.target.value))}>
              {[12, 24, 36].map((m) => <option key={m} value={m}>{m}개월</option>)}
            </select>
            <button className="as-chip" onClick={() => lintMut.mutate()} disabled={lintMut.isPending}>Lint</button>
            <button className="as-fb-apply" onClick={() => valMut.mutate()} disabled={valMut.isPending || !expr.trim()}>
              {valMut.isPending ? "검증 중…" : "검증 실행 →"}
            </button>
          </div>
          <LintBadges lint={lint} />
          <AlphaFactorModal open={pickerOpen} onClose={() => setPickerOpen(false)} expr={expr}
            onApply={(next) => { setExpr(next); setLint(null); }} />
        </section>

        <section className="as-card">
          <div className="as-card-title">ALPHA REGISTRY <span className="as-note-inline">{alphas.length}개 · 슬리브 템플릿 포함 · draft→…→approved</span></div>
          <div className="as-rr-record">
            <input className="as-input" placeholder="알파 이름 (저장/수정)" value={alphaName}
              onChange={(e) => setAlphaName(e.target.value)} />
            <button className="as-fb-apply" onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !expr.trim()}>
              {selAlpha ? "수정 저장" : "레지스트리에 저장"}
            </button>
          </div>
          {selAlpha && (
            <div className="as-note">
              선택: <b>{alphas.find((a) => a.alpha_id === selAlpha)?.name ?? selAlpha}</b>
              <button className="as-chip sm" style={{ marginLeft: 6 }} onClick={() => { setSelAlpha(null); setAlphaName(""); }}>선택 해제</button>
            </div>
          )}
          {regMsg && <div className="as-err">{regMsg}</div>}

          {/* 검색 + 상태 필터 — 알파가 늘어도 원하는 항목을 바로 찾도록 */}
          <input className="tfm-search" placeholder="알파 검색 — 이름·표현식·태그"
            value={regQuery} onChange={(e) => setRegQuery(e.target.value)} />
          <div className="tfm-fams">
            <button className={regStatus === "all" ? "on" : ""} onClick={() => setRegStatus("all")}>
              전체 {alphas.length}
            </button>
            {STATUS_ORDER.filter((s) => statusCounts[s]).map((s) => (
              <button key={s} className={regStatus === s ? "on" : ""} onClick={() => setRegStatus(s)}>
                {STATUS_LABEL[s]} {statusCounts[s]}
              </button>
            ))}
          </div>

          {visibleAlphas.length === 0 && (
            <div className="as-empty">{alphas.length ? "조건에 맞는 알파가 없습니다" : "레지스트리가 비어 있습니다"}</div>
          )}
          {shownAlphas.map((a) => alphaRow(a))}
          {archivedAlphas.length > 0 && (
            <div className="as-al-archrow">
              <ArchiveDrawer
                className="as-al-arch"
                label={`보관된 알파 ${archivedAlphas.length}개 열기`}
                title="ALPHA ARCHIVE"
                hint={`${alphas.length}개 중 ${archivedAlphas.length}개 — 본문에는 활성 항목만 둡니다`}>
                {archivedAlphas.map((a) => alphaRow(a))}
              </ArchiveDrawer>
            </div>
          )}
          <div className="as-note">템플릿은 정직 라벨(데이터 미보유·프록시)을 설명에 명시. validated 승격은 검증 run 필수.</div>
        </section>
      </aside>

      {/* ── 우: 검증 리포트 ── */}
      <main className="as-center">
        <section className={`as-card${valMut.isPending ? " as-loading" : ""}`} aria-busy={valMut.isPending}>
          <div className="as-card-title">VALIDATION REPORT
            {report?.run_id && <span className="as-note-inline num">run: {report.run_id}</span>}
          </div>
          {!report && !valMut.isPending && (
            <div className="as-empty">표현식을 작성하고 <b>검증 실행</b>을 누르면 IC/ICIR·분위·롱숏 리포트가 표시됩니다.</div>
          )}
          {valMut.isPending && <div className="as-empty">월간 리밸런스 시뮬레이션 중… (유니버스·기간에 따라 수십 초)</div>}
          {report?.error && <div className="as-err">{report.message}</div>}
          {report && !report.error && ic && (
            <>
              {/* ★`?? 0` 이 미산출을 **음수처럼** 칠하고 있었다 (A4-L1)★
                  `(ic.mean ?? 0) > 0 ? bull : bear` — ic.mean 이 null 이면 0 은 > 0 이
                  아니므로 **약세색**이 붙고, 값 자체는 `{null}` 이라 빈칸으로 렌더됐다.
                  즉 "아직 못 쟀다"가 "성과가 나빴다"로 보였다. 색은 값이 있을 때만. */}
              <div className="as-al-kpis">
                <div className="as-al-kpi">
                  <em>Rank IC</em>
                  <b className={`num${ic.mean == null ? "" : ic.mean > 0 ? " bull" : " bear"}`}>
                    {ic.mean ?? "—"}
                  </b>
                </div>
                <div className="as-al-kpi"><em>ICIR</em><b className="num">{ic.icir ?? "—"}</b></div>
                <div className="as-al-kpi"><em>t-stat</em><b className="num">{ic.t_stat ?? "—"}</b></div>
                <div className="as-al-kpi"><em>Hit</em><b className="num">{ic.hit_rate == null ? "—" : `${ic.hit_rate}%`}</b></div>
                <div className="as-al-kpi"><em>회전율</em><b className="num">{report.turnover_proxy ?? "—"}</b></div>
                <div className="as-al-kpi"><em>기간</em><b className="num">{report.n_periods}M</b></div>
              </div>

              {/* ★한 표에 두 표가 들어 있었다 (A4-L2)★ Decay(1M/2M/3M)와 IS/OOS 는
                  서로 다른 축인데 머리글 한 줄에 7칸으로 붙어 있었고, `<th>` 에 scope 가
                  없어 스크린리더가 어느 열의 값인지 말할 수 없었다. 두 표로 나눈다. */}
              <div className="as-al-tables">
                <Table className="as-metrics">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">IC DECAY</TableHead>
                      <TableHead scope="col" className="text-right">1M</TableHead>
                      <TableHead scope="col" className="text-right">2M</TableHead>
                      <TableHead scope="col" className="text-right">3M</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow>
                      <TableHead scope="row">IC</TableHead>
                      <TableCell className="text-right"><span className="num">{report.decay?.["1m"] ?? "—"}</span></TableCell>
                      <TableCell className="text-right"><span className="num">{report.decay?.["2m"] ?? "—"}</span></TableCell>
                      <TableCell className="text-right"><span className="num">{report.decay?.["3m"] ?? "—"}</span></TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
                <Table className="as-metrics">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">IS / OOS{report.is_oos?.split ? ` (${report.is_oos.split})` : ""}</TableHead>
                      <TableHead scope="col" className="text-right">IS</TableHead>
                      <TableHead scope="col" className="text-right">OOS</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow>
                      <TableHead scope="row">IC</TableHead>
                      <TableCell className="text-right"><span className="num">{report.is_oos?.is_ic ?? "—"}</span></TableCell>
                      <TableCell className="text-right"><span className="num">{report.is_oos?.oos_ic ?? "—"}</span></TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>

              {report.quantiles && <QuantileBars q={report.quantiles} />}
              <div className="as-card-title as-al-ls-t">LONG-SHORT (Q{report.quantiles?.n}−Q1)
                <span className="as-note-inline num">
                  {report.long_short?.total_return_pct}% · Sharpe {report.long_short?.sharpe ?? "—"} · MDD {report.long_short?.mdd_pct}%
                </span>
              </div>
              {report.long_short && <LsCurve curve={report.long_short.curve} />}
              {/* 신원·커버리지는 접지 않는다 — 무엇을 근거로 잰 값인지는 결론과 같은 급이다. */}
              <div className="as-note num">
                유니버스 {report.universe_size} · 평균 커버리지 {report.avg_coverage} · {report.period_start} ~ {report.period_end}
              </div>
              {/* 정직 노트는 길고 항상 펼쳐져 있었다 — 접되, 개수는 요약에 드러낸다.
                  (A3 가 SleeveStudio 에 쓴 것과 같은 네이티브 <details> — JS 0.) */}
              {(report.notes ?? []).length > 0 && (
                <details className="as-adv as-al-notes">
                  <summary className="as-adv-s">
                    정직 노트 <span className="as-note-inline">{(report.notes ?? []).length}건 — 커버리지·대체·한계</span>
                  </summary>
                  <div className="as-adv-b">
                    {(report.notes ?? []).map((n, i) => <div key={i} className="as-note">• {n}</div>)}
                  </div>
                </details>
              )}
            </>
          )}
        </section>

        {report && !report.error && (report.latest_scores_top?.length ?? 0) > 0 && (
          <section className="as-card">
            <div className="as-card-title">최신 시점 상위 종목
              <button className="as-fb-apply" onClick={applyTop}>상위 10종목 → 포트폴리오</button>
            </div>
            <div className="as-sl-holds">
              {(report.latest_scores_top ?? []).slice(0, 12).map((t) => (
                <span key={t.ticker} className="as-sl-hold" title={`score ${t.score}`}>
                  {t.name}<b className="num"> {t.score}</b>
                </span>
              ))}
            </div>
            <div className="as-note">알파 점수 상위 종목을 균등가중으로 01 Construct에 적재 — 이후 최적화·스트레스는 동일 파이프라인.</div>
          </section>
        )}

        {/* P6 실험 — AutoAlpha 후보 생성 샌드박스 (자동 채택 금지) */}
        <AutoAlphaLab onUseExpr={(e) => { setExpr(e); setLint(null); markAlphaTouched(); }} />
      </main>
    </div>
  );
}

