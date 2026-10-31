"use client";
// 기업 분석 — 검색 줄 + 한 흐름(BU6). 코어 병렬 로드 + 절마다 늦게. `/insights?code=` 다리(머리 줄 찾기·홈·종목 찾기).
import { useState, useEffect, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import CompanyCockpit, { type LazyLoaders } from "@/widgets/company/CompanyCockpit";
import { loadCompanyCore, loadNetwork, loadRisk, loadNarrative } from "@/entities/company/data";
import { companyApi } from "@/entities/company/api";
import { LoadingState } from "@/shared/ui/States";
import { Notice, RetryFail } from "@/shared/ui/tx";

/** 자주 보는 종목 — 바로 여는 지름길(판단 아님). */
const QUICK = [
  { code: "005930", name: "삼성전자" },
  { code: "000660", name: "SK하이닉스" },
  { code: "035720", name: "카카오" },
  { code: "035420", name: "NAVER" },
];

function CompanyPage() {
  const [code, setCode] = useState("005930");
  const [input, setInput] = useState("");
  const [sug, setSug] = useState<{ code: string; name: string }[]>([]);
  const [showSug, setShowSug] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  // 종목코드별로 캐시 — 같은 종목 재방문 시 재요청 없음.
  const core = useQuery({ queryKey: ["company", "core", code], queryFn: () => loadCompanyCore(code) });
  const notFound = (core.error as Error | null)?.message === "NOT_FOUND";

  // 머리 줄 찾기(BU0) — `/insights?code=005930` 으로 오면 그 종목을 연다. 6자리 코드만 받는다(이름 해석은 서버 검색이 이미 했다).
  const qCode = useSearchParams().get("code");
  useEffect(() => { if (qCode && /^\d{6}$/.test(qCode)) setCode(qCode); }, [qCode]);

  // 스크리너 핸드오프 (sessionStorage)
  useEffect(() => {
    try { const h = sessionStorage.getItem("alpha_company_ticker"); if (h && /^\d{6}$/.test(h)) { setCode(h); sessionStorage.removeItem("alpha_company_ticker"); } } catch { /* noop */ }
  }, []);

  const data = core.data;
  // 절이 화면에 들어올 때·단추를 누를 때만 부르는 것(관계도·위험·AI 설명).
  const lazy: LazyLoaders = useMemo(() => ({
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
  // 열기 단추/Enter: 고른 추천 → 6자리 코드 → 첫 추천 순
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
    <div className="tx-page ci-page tpage-fade">
      <div className="ci-search" role="search">
        <div className="ca-pg-searchbox ci-searchbox">
          <Search size={18} aria-hidden className="ci-search-i" />
          <input
            value={input}
            onChange={(e) => { setInput(e.target.value); setShowSug(true); }}
            onKeyDown={onKey}
            onFocus={() => setShowSug(true)}
            onBlur={() => setTimeout(() => setShowSug(false), 150)}
            placeholder="기업 이름이나 종목코드(예: 삼성, 005930)"
            aria-label="기업 찾기"
            autoComplete="off"
          />
          {showSug && sug.length > 0 && (
            <ul className="ca-pg-sug" role="listbox">
              {sug.map((s, i) => (
                <li key={s.code} role="option" aria-selected={i === activeIdx} className={`ca-pg-sug-item${i === activeIdx ? " on" : ""}`}
                  onMouseDown={(e) => { e.preventDefault(); pick(s.code); }}
                  onMouseEnter={() => setActiveIdx(i)}>
                  <span className="ca-pg-sug-name">{s.name}</span>
                  <span className="ca-pg-sug-code" data-mono>{s.code}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <button type="button" className="tx-btn tx-btn--sub ca-pg-go" onClick={go}>열기</button>
        <div className="ci-quick" aria-label="자주 보는 종목">
          {QUICK.map((q) => <button type="button" key={q.code} aria-pressed={q.code === code} className={`ca-pg-chip${q.code === code ? " on" : ""}`} onClick={() => setCode(q.code)}>{q.name}</button>)}
        </div>
      </div>

      {core.isLoading && <LoadingState label="가치평가·재무·팩터·같은 업종을 불러오는 중이에요" />}
      {core.isError && !core.isLoading && (notFound
        ? <Notice tone="warn" title={`종목 ${code}을(를) 찾지 못했어요`}>종목코드를 다시 확인하거나 위에서 이름으로 찾아보세요.</Notice>
        : <RetryFail title="기업 분석을 불러오지 못했어요" onRetry={() => void core.refetch()} />)}
      {data && !core.isLoading && <CompanyCockpit company={data} onPick={setCode} lazy={lazy} onRetry={() => void core.refetch()} />}
    </div>
  );
}

/** useSearchParams 는 Suspense 경계 안에서만 정적 빌드가 된다(Next 14) — 경계 동안은 같은 로딩 상태를 보인다. */
export default function CompanyPageRoute() {
  return <Suspense fallback={<LoadingState />}><CompanyPage /></Suspense>;
}
