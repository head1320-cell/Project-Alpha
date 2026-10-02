"use client";
// 관심종목 그룹 관리 모달 (젠포트 미러) — 그룹명 + 종목 검색 + 4단 카스케이드:
//   주식 유니버스(6티어) / 주식 업종(17그룹) / 주식 테마(88세부) / ETF 분류
// → 종목 체크 → 저장(watchlistStorage). 데이터는 백엔드 /stock-browse.
// BU3c: 인라인 style 을 걷고 `wg-*` 클래스(`--tx-*`)로 그린다 — Radix 구조·요청·저장은 그대로.
//   ★불러오지 못한 것을 빈 목록으로 보이지 않는다★ 분류·종목·검색 요청이 실패하면 alert 로 말한다
//   (예전에는 실패가 "분류 없음"·"◀ 분류를 선택해주세요"·검색 결과 없음과 구별되지 않았다).

import { useEffect, useMemo, useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/shared/ui/shadcn/dialog";
import { X, Search } from "lucide-react";
import { CAPS } from "./UniversePanel";

import { API_BASE } from "@/shared/api/apiBase";

type ClsId = "tier" | "group" | "theme" | "etf";
interface BrowseItem { code: string; name: string }
interface Catalog {
  tiers: Array<{ id: string; size: number }>;
  groups: Array<{ id: string; size: number }>;
  themes: Array<{ id: string; group: string; size: number }>;
  etf_size: number;
  total: number;
}

const ALL_CLS: Array<{ id: ClsId; label: string }> = [
  { id: "tier", label: "주식 유니버스" },
  { id: "group", label: "주식 업종" },
  { id: "theme", label: "주식 테마" },
  { id: "etf", label: "ETF 분류" },
];

const tierLabel = (id: string) => CAPS.find((c) => c.id === id)?.label ?? id;

async function fetchJson(url: string): Promise<Record<string, unknown>> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`browse failed: ${r.status}`);
  return r.json();
}

export default function WatchGroupModal({ open, initialName, initialTickers, onClose, onSave, etfOnly, title }: {
  open: boolean;
  initialName?: string;
  initialTickers?: string[];
  onClose: () => void;
  onSave: (name: string, tickers: string[], items: BrowseItem[]) => void;
  etfOnly?: boolean;       // 자산군 그룹: ETF 분류만 노출
  title?: string;
}) {
  const [name, setName] = useState(initialName ?? "");
  const [selected, setSelected] = useState<Map<string, string>>(new Map());
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const clsList = etfOnly ? ALL_CLS.filter((c) => c.id === "etf") : ALL_CLS;
  const [cls, setCls] = useState<ClsId>(etfOnly ? "etf" : "tier");
  const [subId, setSubId] = useState<string>("");
  const [items, setItems] = useState<BrowseItem[]>([]);
  const [itemsFailed, setItemsFailed] = useState(false);
  const [query, setQuery] = useState("");
  const [searchHits, setSearchHits] = useState<BrowseItem[]>([]);
  const [searchFailed, setSearchFailed] = useState(false);
  const [loading, setLoading] = useState(false);

  // 모달 열릴 때 초기화 + 카탈로그 로드
  useEffect(() => {
    if (!open) return;
    setName(initialName ?? "");
    setSelected(new Map((initialTickers ?? []).map((t) => [t, ""])));
    setQuery(""); setSearchHits([]); setItems([]); setSubId("");
    setCatalogFailed(false);
    fetchJson(`${API_BASE}/api/v1/screener/stock-browse`)
      .then((d) => setCatalog(d as unknown as Catalog))
      .catch(() => { setCatalog(null); setCatalogFailed(true); });
  }, [open, initialName, initialTickers]);

  // 분류 → 종목 로드
  useEffect(() => {
    if (!open) return;
    const need = cls === "etf" || subId;
    if (!need) { setItems([]); setItemsFailed(false); return; }
    setLoading(true); setItemsFailed(false);
    const qs = cls === "etf" ? "cls=etf" : `cls=${cls}&id=${encodeURIComponent(subId)}`;
    fetchJson(`${API_BASE}/api/v1/screener/stock-browse?${qs}`)
      .then((d) => setItems((d.items as BrowseItem[]) ?? []))
      .catch(() => { setItems([]); setItemsFailed(true); })
      .finally(() => setLoading(false));
  }, [open, cls, subId]);

  // 검색 (디바운스)
  useEffect(() => {
    if (!open || !query.trim()) { setSearchHits([]); setSearchFailed(false); return; }
    const t = setTimeout(() => {
      fetchJson(`${API_BASE}/api/v1/screener/stock-browse?q=${encodeURIComponent(query.trim())}`)
        .then((d) => { setSearchHits((d.items as BrowseItem[]) ?? []); setSearchFailed(false); })
        .catch(() => { setSearchHits([]); setSearchFailed(true); });
    }, 250);
    return () => clearTimeout(t);
  }, [open, query]);

  const subOptions = useMemo(() => {
    if (!catalog) return [];
    if (cls === "tier") return catalog.tiers.map((t) => ({ id: t.id, label: tierLabel(t.id), n: t.size }));
    if (cls === "group") return (catalog.groups ?? []).map((g) => ({ id: g.id, label: g.id, n: g.size }));
    if (cls === "theme") return (catalog.themes ?? []).map((t) => ({ id: t.id, label: t.id, n: t.size }));
    return [];
  }, [catalog, cls]);

  // ★`open` 은 이제 Radix 가 소유한다★ 조기 return 을 두면 Dialog 가 마운트되지 않아
  // Escape·포커스 트랩·포커스 복귀가 전부 죽는다.

  const toggle = (it: BrowseItem) => {
    setSelected((m) => {
      const n = new Map(m);
      if (n.has(it.code)) n.delete(it.code);
      else n.set(it.code, it.name);
      return n;
    });
  };
  const canSave = selected.size > 0;

  const Row = ({ it }: { it: BrowseItem }) => (
    <label className="wg-row">
      <input type="checkbox" checked={selected.has(it.code)} onChange={() => toggle(it)} />
      <span className="wg-row-name">{it.name}</span>
      <span className="wg-code">{it.code}</span>
    </label>
  );

  // ★Radix Dialog 로 옮겼다 (Phase A)★
  // 이전에는 backdrop 클릭만 닫혔다 — role·aria-modal·Escape·포커스 트랩이 **0개**였고,
  // 인라인 스타일로 직접 그린 오버레이가 그 자리를 대신하고 있었다.
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="wg-modal" aria-describedby={undefined}
        // ★Radix 의 닫기-자동포커스를 막고 호출자가 직접 되돌린다★ 이 창은 `next/dynamic`
        // 으로 떼어져 있어 클릭 시점에 Dialog 가 아직 없다 — Radix 가 기억하는 복귀 대상이
        // 트리거가 아닐 수 있고, 그러면 닫은 뒤 포커스가 body 로 떨어진다.
        onCloseAutoFocus={(e) => e.preventDefault()}>
        <div className="wg-head">
          <DialogTitle className="wg-title">{title ?? "관심종목 그룹 관리"}</DialogTitle>
          <button type="button" onClick={onClose} aria-label="닫기" className="wg-x"><X size={18} /></button>
        </div>

        <label className="wg-field">
          <span className="wg-label">그룹 이름</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 반도체 대형주"
            className="wg-input" />
        </label>

        {/* 검색 */}
        <div className="wg-search">
          <Search size={16} className="wg-search-i" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="종목 이름이나 코드로 찾기"
            aria-label="종목 찾기" className="wg-input wg-input--search" />
        </div>
        {searchFailed && (
          <p className="wg-err" role="alert">종목을 찾지 못했어요 — 서버에 닿지 않았어요. 잠시 뒤 다시 입력해 주세요.</p>
        )}
        {searchHits.length > 0 && (
          <div className="wg-list wg-list--hits">
            {searchHits.map((it) => <Row key={`s-${it.code}`} it={it} />)}
          </div>
        )}

        {/* 고른 종목 */}
        <div className="wg-picked" aria-label="고른 종목">
          {selected.size === 0 ? (
            <span className="wg-picked-empty">아직 고른 종목이 없어요. 아래에서 분류를 골라 체크해요.</span>
          ) : (
            <>
              <span className="wg-picked-n">{selected.size}종목</span>
              {Array.from(selected.entries()).map(([code, nm]) => (
                <span key={code} className="wg-chip">
                  {nm && <span>{nm}</span>}<span className="wg-code">{code}</span>
                  <button type="button" aria-label={`${nm || code} 빼기`} className="wg-chip-x"
                    onClick={() => setSelected((m) => { const n = new Map(m); n.delete(code); return n; })}><X size={12} /></button>
                </span>
              ))}
            </>
          )}
        </div>

        {catalogFailed && (
          <p className="wg-err" role="alert">분류 목록을 불러오지 못했어요 — 서버에 닿지 않았어요. 창을 닫았다 다시 열어 주세요. 종목 찾기는 따로 돼요.</p>
        )}

        {/* 카스케이드: 분류 → 하위 → 종목 */}
        <div className="wg-cascade">
          <div className="wg-list" aria-label="분류">
            {clsList.map((c) => (
              <button key={c.id} type="button" className="wg-opt" aria-pressed={cls === c.id}
                onClick={() => { setCls(c.id); setSubId(""); }}>
                {c.label}{c.id === "etf" && catalog ? <span className="wg-n">{catalog.etf_size}</span> : null}
              </button>
            ))}
          </div>
          <div className="wg-list" aria-label="하위 분류">
            {cls === "etf" ? (
              <button type="button" className="wg-opt" aria-pressed={subId === "__etf__"} onClick={() => setSubId("__etf__")}>
                <span>전체 ETF{catalog?.etf_size ? <span className="wg-n">{catalog.etf_size}</span> : null}</span>
                <span className="wg-opt-note">
                  {catalog?.etf_size ? "국내 시장지수·해외·채권 같은 하위 분류는 아직 없어요" : "ETF 목록을 적재하면 보여요"}
                </span>
              </button>
            ) : subOptions.length === 0 ? (
              <p className="wg-empty">{catalogFailed ? "분류를 불러오지 못했어요" : catalog ? "이 분류에는 항목이 없어요" : "불러오는 중이에요"}</p>
            ) : subOptions.map((o) => (
              <button key={o.id} type="button" className="wg-opt" aria-pressed={subId === o.id} onClick={() => setSubId(o.id)}>
                {o.label}<span className="wg-n">{o.n}</span>
              </button>
            ))}
          </div>
          <div className="wg-list wg-items" aria-label="종목">
            {loading ? (
              <p className="wg-empty">종목을 불러오는 중이에요</p>
            ) : itemsFailed ? (
              <p className="wg-err" role="alert">종목 목록을 불러오지 못했어요 — 서버에 닿지 않았어요. 분류를 다시 눌러 주세요.</p>
            ) : items.length === 0 ? (
              <p className="wg-empty">{cls === "etf" || subId ? "이 분류에 담긴 종목이 없어요" : "왼쪽에서 분류를 골라요"}</p>
            ) : items.map((it) => <Row key={it.code} it={it} />)}
          </div>
        </div>

        <div className="wg-foot">
          <button type="button" onClick={onClose} className="tx-btn tx-btn--sub">취소</button>
          <button type="button" disabled={!canSave} className="tx-btn tx-btn--main"
            onClick={() => {
              const items = Array.from(selected.entries()).map(([code, nm]) => ({ code, name: nm }));
              onSave(name.trim() || "관심그룹", Array.from(selected.keys()), items);
              onClose();
            }}>
            저장하기
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
