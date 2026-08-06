"use client";
// 좌측 레일 — 포트폴리오 빌더: 종목 검색(symbols/search) + 관심그룹 가져오기 +
// 비중 입력(균등/초기화 퀵버튼) + 저장된 스터디 목록 (Decision Journal 1라운드)
import React, { useEffect, useRef, useState } from "react";
import { Scale, Eraser } from "lucide-react";
import { allocationApi, type SymbolHit } from "@/entities/allocation/api";
import { Button } from "@/shared/ui/shadcn/button";
import { Progress } from "@/shared/ui/shadcn/progress";
import { listWatchlists, type Watchlist } from "@/shared/lib/watchlistStorage";
import { deleteStudy, listStudies, type AllocationStudy } from "@/entities/allocation/storage";
import { WeightRow } from "./WeightRow";

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
  // 0.5%p 허용 오차 — equalize() 가 소수 1자리로 반올림하므로 정확히 100 이 안 나올 수 있다.
  const offTarget = holdings.length > 0 && Math.abs(totalW - 100) >= 0.5;

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
        <div className="as-rail-title">포트폴리오</div>

        {/* ★배분 게이지 — 색만으로 상태를 말하지 않는다★
            예전에는 합계 숫자의 **색**만 바뀌었다(정상=회색 / 이탈=빨강). 색각 이상
            사용자와 흑백 출력에서는 아무 신호도 아니다. 바 + 숫자 + 글자 세 겹으로 말한다. */}
        {holdings.length > 0 && (
          <div className="as-gauge">
            <Progress
              value={totalW}
              label="포트폴리오 비중 합계"
              tone={offTarget ? "warn" : "default"}
            />
            <div className="as-gauge-r">
              <span className="as-gauge-v num">{totalW.toFixed(1)}%</span>
              <span className={`as-gauge-s${offTarget ? " off" : ""}`}>
                {offTarget ? `합계 100% 아님 (${totalW > 100 ? "초과" : "부족"} ${Math.abs(totalW - 100).toFixed(1)}%p)` : "합계 100%"}
              </span>
            </div>
          </div>
        )}

        {holdings.length === 0 && <div className="as-empty">위 검색으로 자산을 추가하세요 (2개 이상)</div>}
        {holdings.map((h) => (
          <WeightRow
            key={h.code}
            code={h.code}
            name={h.name}
            weight={h.weight}
            onWeight={setWeight}
            onRemove={(code) => onChange(holdings.filter((x) => x.code !== code))}
          />
        ))}
        {holdings.length > 0 && (
          <div className="as-wl-row as-rail-acts">
            <Button variant="outline" size="sm" onClick={() => onChange(equalize(holdings))}>
              <Scale size={13} aria-hidden="true" /> 균등 배분
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onChange([])}>
              <Eraser size={13} aria-hidden="true" /> 전체 비우기
            </Button>
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
