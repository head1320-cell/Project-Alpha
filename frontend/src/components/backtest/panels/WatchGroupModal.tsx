"use client";
// 관심종목 그룹 관리 모달 (젠포트 미러) — 그룹명 + 종목 검색 + 4단 카스케이드:
//   주식 유니버스(6티어) / 주식 업종(17그룹) / 주식 테마(88세부) / ETF 분류
// → 종목 체크 → 저장(watchlistStorage). 데이터는 백엔드 /stock-browse.

import { useEffect, useMemo, useState } from "react";
import { X, Search } from "lucide-react";
import { CAPS } from "./UniversePanel";

import { API_BASE } from "@/lib/apiBase";
const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";

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
  const clsList = etfOnly ? ALL_CLS.filter((c) => c.id === "etf") : ALL_CLS;
  const [cls, setCls] = useState<ClsId>(etfOnly ? "etf" : "tier");
  const [subId, setSubId] = useState<string>("");
  const [items, setItems] = useState<BrowseItem[]>([]);
  const [query, setQuery] = useState("");
  const [searchHits, setSearchHits] = useState<BrowseItem[]>([]);
  const [loading, setLoading] = useState(false);

  // 모달 열릴 때 초기화 + 카탈로그 로드
  useEffect(() => {
    if (!open) return;
    setName(initialName ?? "");
    setSelected(new Map((initialTickers ?? []).map((t) => [t, ""])));
    setQuery(""); setSearchHits([]); setItems([]); setSubId("");
    fetchJson(`${API_BASE}/api/v1/screener/stock-browse`)
      .then((d) => setCatalog(d as unknown as Catalog)).catch(() => setCatalog(null));
  }, [open, initialName, initialTickers]);

  // 분류 → 종목 로드
  useEffect(() => {
    if (!open) return;
    const need = cls === "etf" || subId;
    if (!need) { setItems([]); return; }
    setLoading(true);
    const qs = cls === "etf" ? "cls=etf" : `cls=${cls}&id=${encodeURIComponent(subId)}`;
    fetchJson(`${API_BASE}/api/v1/screener/stock-browse?${qs}`)
      .then((d) => setItems((d.items as BrowseItem[]) ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open, cls, subId]);

  // 검색 (디바운스)
  useEffect(() => {
    if (!open || !query.trim()) { setSearchHits([]); return; }
    const t = setTimeout(() => {
      fetchJson(`${API_BASE}/api/v1/screener/stock-browse?q=${encodeURIComponent(query.trim())}`)
        .then((d) => setSearchHits((d.items as BrowseItem[]) ?? []))
        .catch(() => setSearchHits([]));
    }, 250);
    return () => clearTimeout(t);
  }, [open, query]);

  const subOptions = useMemo(() => {
    if (!catalog) return [];
    if (cls === "tier") return catalog.tiers.map((t) => ({ id: t.id, label: `${tierLabel(t.id)} (${t.size})` }));
    if (cls === "group") return (catalog.groups ?? []).map((g) => ({ id: g.id, label: `${g.id} (${g.size})` }));
    if (cls === "theme") return (catalog.themes ?? []).map((t) => ({ id: t.id, label: `${t.id} (${t.size})` }));
    return [];
  }, [catalog, cls]);

  if (!open) return null;

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
    <label style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", borderBottom: "1px solid var(--border)", cursor: "pointer", fontSize: 13 }}>
      <input type="checkbox" checked={selected.has(it.code)} onChange={() => toggle(it)} />
      <span style={{ fontFamily: "var(--bs-font-mono)", fontSize: 12, color: "var(--text-secondary)", width: 62 }}>{it.code}</span>
      <span style={{ color: "var(--text-primary)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</span>
    </label>
  );

  return (
    <div onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 18 }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "100%", maxWidth: 680, maxHeight: "86vh", overflow: "auto", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: RL, padding: 18, boxShadow: "var(--bs-box-shadow)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 13 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>{title ?? "관심종목 그룹 관리"}</span>
          <button type="button" onClick={onClose} aria-label="닫기" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)" }}><X size={17} /></button>
        </div>

        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 5 }}>그룹명</div>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="관심종목 그룹의 이름을 입력해주세요"
          style={{ width: "100%", boxSizing: "border-box", fontSize: 13, padding: "9px 11px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)", marginBottom: 12 }} />

        {/* 검색 */}
        <div style={{ position: "relative", marginBottom: 10 }}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="종목명, 종목코드를 입력하세요"
            style={{ width: "100%", boxSizing: "border-box", fontSize: 13, padding: "9px 34px 9px 11px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
          <Search size={15} style={{ position: "absolute", right: 11, top: 10, color: "var(--text-secondary)" }} />
        </div>
        {searchHits.length > 0 && (
          <div style={{ border: "1px solid var(--border)", borderRadius: R, maxHeight: 150, overflow: "auto", marginBottom: 10 }}>
            {searchHits.map((it) => <Row key={`s-${it.code}`} it={it} />)}
          </div>
        )}

        {/* 선택된 종목 */}
        <div style={{ border: "1px dashed var(--border-strong)", borderRadius: R, padding: 9, marginBottom: 12, minHeight: 44 }}>
          {selected.size === 0 ? (
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>관심종목 그룹에 추가할 종목을 아래에서 선택하세요</span>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {Array.from(selected.entries()).map(([code, nm]) => (
                <span key={code} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, border: "1px solid var(--border-strong)", borderRadius: R, padding: "3px 7px", background: "var(--bg-section)" }}>
                  <span style={{ fontFamily: "var(--bs-font-mono)" }}>{code}</span>{nm && <span style={{ color: "var(--text-secondary)" }}>{nm}</span>}
                  <button type="button" aria-label="제거" onClick={() => setSelected((m) => { const n = new Map(m); n.delete(code); return n; })}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", padding: 0 }}><X size={12} /></button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* 카스케이드: 분류 → 하위 → 종목 */}
        <div style={{ display: "grid", gridTemplateColumns: "120px 168px minmax(0,1fr)", gap: 9, marginBottom: 14 }}>
          <div style={{ border: "1px solid var(--border)", borderRadius: R, overflow: "auto", maxHeight: 240 }}>
            {clsList.map((c) => (
              <button key={c.id} type="button" onClick={() => { setCls(c.id); setSubId(""); }}
                style={{ display: "block", width: "100%", textAlign: "left", fontSize: 13, padding: "9px 11px", border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer", background: cls === c.id ? "var(--bg-section)" : "transparent", color: cls === c.id ? "var(--text-primary)" : "var(--text-secondary)" }}>
                {c.label}{c.id === "etf" && catalog ? ` (${catalog.etf_size})` : ""}
              </button>
            ))}
          </div>
          <div style={{ border: "1px solid var(--border)", borderRadius: R, overflow: "auto", maxHeight: 240 }}>
            {cls === "etf" ? (
              <button type="button" onClick={() => setSubId("__etf__")}
                style={{ display: "block", width: "100%", textAlign: "left", fontSize: 13, padding: "8px 11px", border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer", background: subId === "__etf__" ? "var(--bg-section)" : "transparent", color: catalog?.etf_size ? "var(--text-secondary)" : "var(--text-muted)" }}>
                전체 ETF{catalog?.etf_size ? ` (${catalog.etf_size})` : " — 마스터 적재 후"}
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3 }}>국내 시장지수·해외·채권 등 하위분류는 데이터 한계</div>
              </button>
            ) : subOptions.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 10 }}>분류 없음</div>
            ) : subOptions.map((o) => (
              <button key={o.id} type="button" onClick={() => setSubId(o.id)}
                style={{ display: "block", width: "100%", textAlign: "left", fontSize: 13, padding: "8px 11px", border: "none", borderBottom: "1px solid var(--border)", cursor: "pointer", background: subId === o.id ? "var(--bg-section)" : "transparent", color: subId === o.id ? "var(--text-primary)" : "var(--text-secondary)" }}>
                {o.label}
              </button>
            ))}
          </div>
          <div style={{ border: "1px solid var(--border)", borderRadius: R, overflow: "auto", maxHeight: 240 }}>
            {loading ? (
              <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 10 }}>불러오는 중…</div>
            ) : items.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 10 }}>◀ 분류를 선택해주세요</div>
            ) : items.map((it) => <Row key={it.code} it={it} />)}
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 9 }}>
          <button type="button" onClick={onClose}
            style={{ fontSize: 13, color: "var(--text-secondary)", background: "var(--bg-section)", border: "1px solid var(--border-strong)", borderRadius: R, padding: "10px 22px", cursor: "pointer" }}>취소</button>
          <button type="button" disabled={!canSave}
            onClick={() => {
              const items = Array.from(selected.entries()).map(([code, nm]) => ({ code, name: nm }));
              onSave(name.trim() || "관심그룹", Array.from(selected.keys()), items);
              onClose();
            }}
            style={{ fontSize: 13, fontWeight: 500, color: "#fff", background: canSave ? "var(--bs-primary, #1200ff)" : "var(--border-strong)", border: "none", borderRadius: R, padding: "10px 24px", cursor: canSave ? "pointer" : "not-allowed" }}>
            저장하기
          </button>
        </div>
      </div>
    </div>
  );
}
