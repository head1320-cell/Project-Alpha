"use client";
// Company Analysis — 실데이터 Cockpit. 코어 병렬 로드 + 탭별 lazy. 스크리너 핸드오프 지원.
import { useState, useEffect, useMemo } from "react";
import PageHeader from "@/components/layout/PageHeader";
import CompanyCockpit, { type LazyLoaders } from "@/components/insights/CompanyCockpit";
import { loadCompanyCore, loadSignal, loadMacro, loadNetwork, loadRisk, loadNarrative } from "@/lib/companyData";
import { companyApi } from "@/lib/screenerApi";
import type { CompanyData } from "@/components/insights/types";

const QUICK = [
  { code: "005930", name: "삼성전자" },
  { code: "000660", name: "SK하이닉스" },
  { code: "035720", name: "카카오" },
  { code: "035420", name: "NAVER" },
];

export default function CompanyPage() {
  const [code, setCode] = useState("005930");
  const [input, setInput] = useState("");
  const [data, setData] = useState<CompanyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 스크리너 핸드오프 (sessionStorage)
  useEffect(() => {
    try { const h = sessionStorage.getItem("alpha_company_ticker"); if (h && /^\d{6}$/.test(h)) { setCode(h); sessionStorage.removeItem("alpha_company_ticker"); } } catch { /* noop */ }
  }, []);

  useEffect(() => {
    let ok = true; setLoading(true); setError(null);
    loadCompanyCore(code)
      .then((d) => { if (ok) { setData(d); setLoading(false); } })
      .catch((e: Error) => { if (ok) { setError(e?.message === "NOT_FOUND" ? `종목 ${code}을(를) 찾을 수 없습니다.` : "데이터를 불러오지 못했습니다 (백엔드 확인)."); setLoading(false); } });
    return () => { ok = false; };
  }, [code]);

  const lazy: LazyLoaders = useMemo(() => ({
    signal: () => (data ? loadSignal(code, data.name) : Promise.resolve(null)),
    macro: () => loadMacro(),
    network: () => loadNetwork(code),
    risk: () => loadRisk(code),
    narrative: async () => {
      const item = await companyApi.byTicker(code).catch(() => null);
      const detail = await companyApi.evaluate(code, data?.price ?? 0).catch(() => null);
      return loadNarrative((item ?? {}) as object, (detail ?? {}) as object);
    },
  }), [code, data]);

  const go = (v: string) => { const m = v.match(/\d{6}/); if (m) setCode(m[0]); };

  return (
    <div>
      <div className="meta-stamp">SEC_CODE: {code}<br />EXCHANGE: KRX<br />STATUS: LIVE_FEED</div>
      <PageHeader
        eyebrow="COMPANY / DEEP ANALYSIS"
        index="04 / 05"
        title="Company Analysis"
        intro="DART 재무 + KIS 시세 + 116팩터 + RIM·DCF·DDM 내재가치를 한 화면에 — 가치평가·재무·팩터·피어·네트워크·리스크·AI까지 통합 분석."
        status="LIVE"
      >
        <div className="ca-pg-search">
          <input value={input} onChange={(e) => setInput(e.target.value.replace(/[^0-9]/g, ""))} onKeyDown={(e) => { if (e.key === "Enter") go(input); }} placeholder="종목코드 (예: 005930)" maxLength={6} />
          <button className="ca-pg-go" onClick={() => go(input)}>분석</button>
          <span className="ca-pg-div" />
          {QUICK.map((q) => <button key={q.code} className={`ca-pg-chip${q.code === code ? " on" : ""}`} onClick={() => setCode(q.code)}>{q.name}</button>)}
        </div>
      </PageHeader>

      {loading && (
        <div className="ca-pg-loading">
          <span className="ca-pg-spin" />
          <span>{code} — 가치평가 · 재무 · 116팩터 · 피어 로딩 중…</span>
        </div>
      )}
      {error && !loading && <div className="ca-pg-error">⚠ {error}</div>}
      {data && !loading && <CompanyCockpit company={data} onPick={setCode} lazy={lazy} />}
    </div>
  );
}
