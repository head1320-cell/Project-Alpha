"use client";
// Company Analysis — 실데이터 Cockpit. 코어 병렬 로드 + 탭별 lazy. 스크리너 핸드오프 지원.
import { useState, useEffect, useMemo } from "react";
import PageHeader from "@/components/layout/PageHeader";
import CompanyCockpit, { type LazyLoaders } from "@/components/insights/CompanyCockpit";
import { loadCompanyCore, loadSignal, loadMacro, loadNetwork, loadRisk, loadNarrative } from "@/lib/companyData";
import { companyApi } from "@/lib/screenerApi";
import type { CompanyData } from "@/components/insights/types";
import { LoadingState, ErrorState } from "@/components/layout/States";

const QUICK = [
  { code: "005930", name: "삼성전자" },
  { code: "000660", name: "SK하이닉스" },
  { code: "035720", name: "카카오" },
  { code: "035420", name: "NAVER" },
];

export default function CompanyPage() {
  const [code, setCode] = useState("005930");
  const [input, setInput] = useState("");
  const [sug, setSug] = useState<{ code: string; name: string }[]>([]);
  const [showSug, setShowSug] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
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

  // 자동완성: 입력 변화 시 디바운스 검색 (이름/코드)
  useEffect(() => {
    const q = input.trim();
    if (!q) { setSug([]); return; }
    const t = setTimeout(() => {
      companyApi.stockSearch(q, 12).then((items) => { setSug(items); setActiveIdx(-1); }).catch(() => setSug([]));
    }, 140);
    return () => clearTimeout(t);
  }, [input]);

  const pick = (c: string) => { setCode(c); setInput(""); setSug([]); setShowSug(false); setActiveIdx(-1); };
  // 분석 버튼/Enter: 활성 추천 → 6자리 코드 → 첫 추천 순
  const go = () => {
    if (activeIdx >= 0 && sug[activeIdx]) return pick(sug[activeIdx].code);
    const m = input.match(/\d{6}/);
    if (m) return pick(m[0]);
    if (sug[0]) return pick(sug[0].code);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setShowSug(true); setActiveIdx((i) => Math.min(i + 1, sug.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, -1)); }
    else if (e.key === "Enter") { e.preventDefault(); go(); }
    else if (e.key === "Escape") { setShowSug(false); }
  };

  return (
    <div className="tpage-fade">
      <PageHeader
        eyebrow="COMPANY / DEEP ANALYSIS"
        index="04 / 05"
        title="Company Analysis"
        intro="DART 재무 + KIS 시세 + 116팩터 + RIM·DCF·DDM 내재가치를 한 화면에 — 가치평가·재무·팩터·피어·네트워크·리스크·AI까지 통합 분석."
        status="LIVE"
      >
        <div className="ca-pg-search">
          <div className="ca-pg-searchbox">
            <input
              value={input}
              onChange={(e) => { setInput(e.target.value); setShowSug(true); }}
              onKeyDown={onKey}
              onFocus={() => setShowSug(true)}
              onBlur={() => setTimeout(() => setShowSug(false), 150)}
              placeholder="기업명 또는 종목코드 (예: 삼성, 005930)"
              autoComplete="off"
            />
            {showSug && sug.length > 0 && (
              <ul className="ca-pg-sug">
                {sug.map((s, i) => (
                  <li key={s.code} className={`ca-pg-sug-item${i === activeIdx ? " on" : ""}`}
                    onMouseDown={(e) => { e.preventDefault(); pick(s.code); }}
                    onMouseEnter={() => setActiveIdx(i)}>
                    <span className="ca-pg-sug-name">{s.name}</span>
                    <span className="ca-pg-sug-code">{s.code}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button className="ca-pg-go" onClick={go}>분석</button>
          <span className="ca-pg-div" />
          {QUICK.map((q) => <button key={q.code} className={`ca-pg-chip${q.code === code ? " on" : ""}`} onClick={() => setCode(q.code)}>{q.name}</button>)}
        </div>
      </PageHeader>

      {loading && <LoadingState label={`${code} — 가치평가 · 재무 · 116팩터 · 피어 로딩 중`} />}
      {error && !loading && <ErrorState sub={error} />}
      {data && !loading && <CompanyCockpit company={data} onPick={setCode} lazy={lazy} />}
    </div>
  );
}
