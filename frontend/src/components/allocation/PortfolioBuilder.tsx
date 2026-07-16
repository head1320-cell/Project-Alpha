"use client";
// 좌측 레일 — 포트폴리오 빌더: 종목 검색(symbols/search) + 관심그룹 가져오기 +
// 비중 입력(균등/초기화 퀵버튼) + 저장된 스터디 목록 (Decision Journal 1라운드)
import React, { useEffect, useRef, useState } from "react";
import { allocationApi, type SymbolHit } from "@/lib/allocationApi";
import { listWatchlists, type Watchlist } from "@/lib/watchlistStorage";
import { deleteStudy, listStudies, type AllocationStudy } from "@/lib/allocationStorage";

export interface Holding { code: string; name: string; weight: number }

export function equalize(holdings: Holding[]): Holding[] {
  if (!holdings.length) return holdings;
  const w = Math.round((100 / holdings.length) * 10) / 10;
  return holdings.map((h, i) => ({ ...h, weight: i === 0 ? Math.round((100 - w * (holdings.length - 1)) * 10) / 10 : w }));
}

export function PortfolioBuilder({ holdings, onChange, onLoadStudy, studiesVersion }: {
  holdings: Holding[];
  onChange: (next: Holding[]) => void;
  onLoadStudy: (s: AllocationStudy) => void;
  studiesVersion: number;   // 저장 시 목록 갱신 트리거
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SymbolHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [studies, setStudies] = useState<AllocationStudy[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { setWatchlists(listWatchlists()); }, []);
  useEffect(() => { setStudies(listStudies()); }, [studiesVersion]);

  // 검색 디바운스 300ms
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) { setHits([]); return; }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try { setHits(await allocationApi.searchSymbols(q.trim())); }
      catch { setHits([]); }
      finally { setSearching(false); }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [q]);

  const add = (code: string, name: string) => {
    if (holdings.some((h) => h.code === code)) return;
    onChange(equalize([...holdings, { code, name, weight: 0 }]));
    setQ(""); setHits([]);
  };

  const importWatchlist = (wl: Watchlist) => {
    const merged = [...holdings];
    wl.tickers.forEach((code) => {
      if (!merged.some((h) => h.code === code)) merged.push({ code, name: code, weight: 0 });
    });
    onChange(equalize(merged));
  };

  const setWeight = (code: string, w: number) => {
    onChange(holdings.map((h) => (h.code === code ? { ...h, weight: Math.max(0, Math.min(100, w)) } : h)));
  };

  const totalW = holdings.reduce((a, h) => a + h.weight, 0);

  return (
    <div className="as-rail">
      {/* 자산 검색 */}
      <div className="as-rail-sec">
        <div className="as-rail-title">자산 추가</div>
        <input className="as-input" placeholder="종목명·코드 검색 (예: 삼성전자)" value={q}
          onChange={(e) => setQ(e.target.value)} />
        {searching && <div className="as-note">검색 중…</div>}
        {(!!hits.length || /^\d{6}$/.test(q.trim())) && (
          <div className="as-search-hits">
            {hits.map((h) => (
              <button key={h.ticker} className="as-hit" onClick={() => add(h.ticker, h.name)}>
                <span className="as-hit-nm">{h.name}</span>
                <span className="num">{h.ticker}</span>
              </button>
            ))}
            {/* 6자리 코드 직접 추가 — 마스터 미적재/신규상장 폴백 */}
            {/^\d{6}$/.test(q.trim()) && !hits.some((h) => h.ticker === q.trim()) && (
              <button className="as-hit" onClick={() => add(q.trim(), q.trim())}>
                <span className="as-hit-nm">코드로 직접 추가</span>
                <span className="num">{q.trim()}</span>
              </button>
            )}
          </div>
        )}
        {!!watchlists.length && (
          <div className="as-wl-row">
            {watchlists.slice(0, 4).map((wl) => (
              <button key={wl.id} className="as-chip" title={`관심그룹 가져오기 (${wl.tickers.length}종목)`}
                onClick={() => importWatchlist(wl)}>+ {wl.name}</button>
            ))}
          </div>
        )}
      </div>

      {/* 보유 자산 + 비중 */}
      <div className="as-rail-sec">
        <div className="as-rail-title">
          포트폴리오 <span className="num" style={{ color: Math.abs(totalW - 100) < 0.5 ? "var(--t-muted)" : "var(--color-bear)" }}>{totalW.toFixed(1)}%</span>
        </div>
        {holdings.length === 0 && <div className="as-empty">위 검색으로 자산을 추가하세요 (2개 이상)</div>}
        {holdings.map((h) => (
          <div key={h.code} className="as-holding">
            <button className="as-x" title="제거" onClick={() => onChange(holdings.filter((x) => x.code !== h.code))}>×</button>
            <span className="as-holding-nm" title={h.code}>{h.name}</span>
            <input className="as-w-input num" type="number" min={0} max={100} step={0.5} value={h.weight}
              onChange={(e) => setWeight(h.code, parseFloat(e.target.value) || 0)} />
            <span className="as-w-unit">%</span>
          </div>
        ))}
        {holdings.length > 0 && (
          <div className="as-wl-row">
            <button className="as-chip" onClick={() => onChange(equalize(holdings))}>균등 배분</button>
            <button className="as-chip" onClick={() => onChange([])}>전체 비우기</button>
          </div>
        )}
      </div>

      {/* 저장된 스터디 */}
      <div className="as-rail-sec">
        <div className="as-rail-title">저장된 스터디</div>
        {studies.length === 0 && <div className="as-empty">저장된 스터디 없음</div>}
        {studies.slice(0, 8).map((s) => (
          <div key={s.id} className="as-study">
            <button className="as-study-load" onClick={() => onLoadStudy(s)} title={s.note || s.name}>
              <span className="as-study-nm">{s.name}</span>
              <span className="as-study-meta num">{Object.keys(s.holdings).length}종목 · {s.savedAt.slice(0, 10)}</span>
            </button>
            <button className="as-x" title="삭제" onClick={() => { deleteStudy(s.id); setStudies(listStudies()); }}>×</button>
          </div>
        ))}
      </div>
    </div>
  );
}
