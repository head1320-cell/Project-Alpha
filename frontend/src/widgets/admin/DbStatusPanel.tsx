"use client";

import { useCallback, useEffect, useState } from "react";

import SectionHead from "@/shared/ui/SectionHead";
import { ErrorState, LoadingState } from "@/shared/ui/States";
import { api } from "@/shared/api/legacyApi";
import { STATUS_LABEL, USAGE_LABEL, USAGE_REASON } from "@/entities/regime-snapshot/model";
import type { DataStatus, ResearchUsage } from "@/entities/regime-snapshot/model";

type DbStatus = Awaited<ReturnType<typeof api.dbStatus>>;
type Cell = number | string | null;

const TABLE_LABELS: Record<string, string> = {
  daily_prices: "일봉 (주식)",
  index_kospi_kosdaq: "지수 (KOSPI/KOSDAQ)",
  etf_cross_asset: "크로스에셋 ETF",
  investor_flows: "투자자 수급",
  factor_snapshot: "펀더멘털 스냅샷",
  financials_history: "재무 시계열 (PIT)",
};

const INGEST_TARGETS: [string, string][] = [
  ["index", "지수"], ["etf", "ETF 시세(크로스에셋 15)"], ["stocks", "주식 일봉"],
  ["factors", "펀더멘털"], ["financials", "재무시계열"], ["flows", "수급(KIS)"],
];

const fmtNum = (v: Cell | undefined) =>
  typeof v === "number" ? v.toLocaleString() : v == null ? "—" : String(v);

function period(t: Record<string, Cell>): string {
  const s = t.start, e = t.end;
  return s || e ? `${s ?? "—"} ~ ${e ?? "—"}` : "—";
}

export default function DbStatusPanel() {
  const [st, setSt] = useState<DbStatus | null>(null);
  const [honesty, setHonesty] =
    useState<Awaited<ReturnType<typeof api.sourceHonesty>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // 연결 진단 (DART/KRX/KIS 실도달)
  const [doctor, setDoctor] = useState<Awaited<ReturnType<typeof api.ingestDoctor>> | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const runDoctor = async () => {
    setDocLoading(true);
    try {
      setDoctor(await api.ingestDoctor());
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setDocLoading(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setSt(await api.dbStatus());
      // 출처 정직성은 실패해도 패널 전체를 죽이지 않는다 — 부가 정보다.
      try { setHonesty(await api.sourceHonesty()); } catch { setHonesty(null); }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 적재 실행 중이면 폴링
  const anyRunning = !!(st?.ingest_running && Object.values(st.ingest_running).some(Boolean));
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => void load(), 5000);
    return () => clearInterval(id);
  }, [anyRunning, load]);

  const trigger = async (target: string) => {
    setMsg(null);
    try {
      setMsg((await api.ingest(target)).message);
      void load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const toolsReady = st ? Object.values(st.tools).filter(Boolean).length : 0;
  const toolsTotal = st ? Object.keys(st.tools).length : 0;

  return (
    <div className="tpage-fade">
      {/* ── 출처별 연구 등급 (스펙 §6.1 · Phase 8b) ──
          ★"가져올 수 있다" 와 "과거 검증에 쓸 수 있다" 는 다른 축이다★ (§3.5)
          행수만 보여주면 "많으니 백테스트에 써도 되겠다" 로 읽힌다. 등급을 1급으로 적는다.
          라벨은 regime-snapshot 모델의 것을 **재사용**한다 — 문구를 새로 지으면 같은 개념이
          화면마다 다른 말로 불린다. */}
      {honesty && (
        <div className="t-honesty">
          <div className="t-honesty-h">데이터 출처 · 연구 등급</div>
          <ul className="t-honesty-list">
            {honesty.sources.map((sc) => (
              <li key={sc.id} className="t-honesty-row">
                <span className="t-honesty-nm">{sc.label}</span>
                <span className={`t-honesty-st s-${sc.data_status}`}>
                  {STATUS_LABEL[sc.data_status as DataStatus] ?? sc.data_status}
                </span>
                <span className={`t-honesty-use u-${sc.research_usage}`}
                  title={USAGE_REASON[sc.research_usage as ResearchUsage] ?? ""}>
                  {USAGE_LABEL[sc.research_usage as ResearchUsage] ?? sc.research_usage}
                </span>
                <span className="t-honesty-why">{sc.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {/* 슬림 툴바 — 헤더 제거, MODE 배지(mock 거버넌스 정보)와 새로고침만 유지 */}
      <div className="t-toolbar">
        <span className="t-mode-badge" data-real={st?.config?.kis_real ? "1" : "0"}>
          {st?.config?.kis_real ? "MODE: REAL" : "MODE: MOCK"}
        </span>
        <button className="tchip-toggle" onClick={() => void load()} disabled={loading}>
          {loading ? "조회 중…" : "↻ 새로고침"}
        </button>
      </div>

      {loading && !st && <LoadingState label="DB 적재 현황을 점검하는 중" />}
      {err && !st && <ErrorState label="DB 상태 조회 실패" sub={err} />}

      {st && (
        <div className="animate-fade-in">
          {/* 데이터 소스 키 */}
          <SectionHead label="DATA SOURCES" index="KEYS" />
          <div className="tscenario-bar">
            {Object.entries(st.config).map(([k, v]) => (
              <span key={k} className={`tchip-toggle${v ? " active" : ""}`} style={{ cursor: "default" }}>
                {v ? "● " : "○ "}
                {k}
              </span>
            ))}
          </div>

          {/* 도구별 준비상태 */}
          <SectionHead label="TOOL READINESS" index={`${toolsReady} / ${toolsTotal}`} />
          <div className="tscenario-bar">
            {Object.entries(st.tools).map(([k, ok]) => (
              <span
                key={k}
                className="tchip-toggle"
                style={{ cursor: "default", color: ok ? "var(--color-bull)" : "var(--color-bear)" }}
              >
                {ok ? "✓ " : "✗ "}
                {k}
              </span>
            ))}
          </div>

          {/* 테이블 적재 현황 */}
          <SectionHead label="TABLE COVERAGE" index="ROWS · TICKERS · PERIOD" />
          <table className="trisk-table">
            <thead>
              <tr>
                <th>테이블</th>
                <th className="num">행수</th>
                <th className="num">종목</th>
                <th>기간 (최초 ~ 최근)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(st.tables).map(([key, t]) => {
                const cells = t as Record<string, Cell>;
                const rows = cells.rows ?? cells.loaded;
                return (
                  <tr key={key}>
                    <td>{TABLE_LABELS[key] ?? key}</td>
                    <td className="num" style={{ fontFamily: "var(--t-mono)" }}>
                      {fmtNum(rows)}
                      {cells.total != null ? ` / ${fmtNum(cells.total)}` : ""}
                    </td>
                    <td className="num" style={{ fontFamily: "var(--t-mono)" }}>{fmtNum(cells.tickers)}</td>
                    <td style={{ fontFamily: "var(--t-mono)", color: "var(--t-muted)" }}>{period(cells)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* 유니버스 적재 진행 — 스크리너 유니버스가 마스터(전 상장) 대비 얼마나 채워졌는지 */}
          {st.universe_progress && Object.keys(st.universe_progress.progress ?? {}).length > 0 && (
            <>
              <SectionHead label="UNIVERSE COVERAGE" index="INGESTED / MASTER" />
              <table className="trisk-table">
                <thead>
                  <tr><th>유니버스</th><th className="num">마스터</th><th className="num">적재</th><th className="num">진행률</th></tr>
                </thead>
                <tbody>
                  {(["kospi", "kosdaq", "etf", "all_listed"] as const).map((k) => {
                    const p = st.universe_progress!.progress[k];
                    if (!p) return null;
                    const pct = p.master > 0 ? Math.round((p.ingested / p.master) * 100) : 0;
                    const label = { kospi: "KOSPI", kosdaq: "KOSDAQ", etf: "ETF (시세 전용 — 펀더멘털 적재 대상 아님)", all_listed: "전체 (전종목)" }[k];
                    return (
                      <tr key={k}>
                        <td>{label}</td>
                        <td className="num" style={{ fontFamily: "var(--t-mono)" }}>{p.master.toLocaleString()}</td>
                        <td className="num" style={{ fontFamily: "var(--t-mono)" }}>{p.ingested.toLocaleString()}</td>
                        <td className="num" style={{ fontFamily: "var(--t-mono)", color: pct >= 100 ? "#16a34a" : pct >= 50 ? "var(--t-ink)" : "#dc2626" }}>{pct}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}

          {/* 적재 실행 */}
          <SectionHead label="INGEST" index="BACKGROUND" />
          <div className="tscenario-bar">
            {INGEST_TARGETS.map(([target, label]) => (
              <button
                key={target}
                className="tchip-toggle"
                disabled={!!st.ingest_running?.[target]}
                onClick={() => void trigger(target)}
              >
                {st.ingest_running?.[target] ? `${label} 적재 중…` : label}
              </button>
            ))}
            <button className="tchip-toggle active" disabled={anyRunning} onClick={() => void trigger("all")}>
              {anyRunning ? "적재 중…" : "★ 전체 적재"}
            </button>
            <button className="tchip-toggle" disabled={docLoading} onClick={() => void runDoctor()}>
              {docLoading ? "진단 중…" : "🩺 연결 진단"}
            </button>
          </div>

          {/* 타깃별 진행/에러 — "버튼 눌러도 조용함" 제거 */}
          {st.ingest_status && Object.keys(st.ingest_status).length > 0 && (
            <div style={{ marginTop: 10, display: "grid", gap: 5 }}>
              {Object.entries(st.ingest_status).map(([k, s]) => (
                <div key={k} style={{ fontFamily: "var(--t-mono)", fontSize: 11, color: "var(--t-muted)" }}>
                  <b style={{ color: "var(--t-ink)" }}>{k}</b>
                  {" · "}{s.running ? "실행 중" : s.finished_at ? `완료 ${s.finished_at}` : "대기"}
                  {s.progress ? ` · ${s.progress.stage ?? ""} ${(s.progress.done ?? 0).toLocaleString()}/${(s.progress.total ?? 0).toLocaleString()} (저장 ${(s.progress.saved ?? 0).toLocaleString()} · 실패 ${(s.progress.failures ?? 0).toLocaleString()})` : ""}
                  {s.last_error ? <span style={{ color: "#dc2626" }}> · {s.last_error}</span> : null}
                </div>
              ))}
            </div>
          )}

          {/* DART 사용량 — 일일 한도(20,000건) 도달이 적재 정체의 흔한 원인 */}
          {st.dart_usage && (
            <p style={{ marginTop: 8, fontFamily: "var(--t-mono)", fontSize: 11, color: "var(--t-muted)" }}>
              DART 사용량(프로세스 기동 이후): 요청 {st.dart_usage.requests.toLocaleString()} · 에러 {Object.values(st.dart_usage.errors).reduce((a, b) => a + b, 0).toLocaleString()}
              {st.dart_usage.quota_exhausted && <b style={{ color: "#dc2626" }}> · 일일 한도 도달 — 적재 자동 중단, 내일 재실행 시 이어짐</b>}
              {st.dart_usage.last_error && <span> · 최근 에러: [{st.dart_usage.last_error.status}] {st.dart_usage.last_error.message}</span>}
            </p>
          )}

          {/* 연결 진단 결과 */}
          {doctor && (
            <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
              {(["dart", "krx", "kis"] as const).map((s) => (
                <div key={s} style={{ fontFamily: "var(--t-mono)", fontSize: 11 }}>
                  <b style={{ color: doctor[s].ok ? "#16a34a" : "#dc2626" }}>{doctor[s].ok ? "✓" : "✗"} {s.toUpperCase()}</b>
                  <span style={{ color: "var(--t-muted)" }}> — {doctor[s].message}</span>
                </div>
              ))}
            </div>
          )}

          <p className="tpage-intro" style={{ marginTop: 10 }}>
            키 없는 소스는 자동 건너뜀(no-op) · 진행은 "↻ 새로고침"으로 확인 · 대형 백필은 백그라운드 수 시간.
            펀더멘털과 재무시계열은 같은 DART 일일 한도를 공유 — 동시 실행 시 한도 도달이 빨라집니다(권장: 재무시계열 완주 후 펀더멘털).
          </p>
          {msg && (
            <p style={{ marginTop: 8, fontFamily: "var(--t-mono)", fontSize: 12, color: "var(--t-accent)" }}>{msg}</p>
          )}
        </div>
      )}
    </div>
  );
}
