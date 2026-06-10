"use client";
// 대상 경로: frontend/src/components/backtest/panels/UniversePanel.tsx
//
// 매매 대상(유니버스) 화면(중립). 포함 토글 + 시총군 + 업종(테마 그룹) + 관심그룹 + 실시간 종목 수.
// matched/totalUniverse 는 mock — 실제로는 시총군/업종/그룹 변경 시 스크리너 count API 로 재계산.

import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import { Check } from "lucide-react";
import { Segmented } from "../kit";
import { universeCount, fetchSectors, type SectorOption } from "../../../lib/backtest/universeApi";
import type { BacktestStrategy } from "../../../lib/backtest/strategy";
import { listWatchlists } from "../../../lib/watchlistStorage";

export const CAPS = [
  { id: "kospi_l", label: "코스피 대형" }, { id: "kospi_m", label: "코스피 중소형" },
  { id: "kosdaq_l", label: "코스닥 대형" }, { id: "kosdaq_m", label: "코스닥 중형" },
  { id: "kosdaq_s", label: "코스닥 소형" }, { id: "kosdaq_xs", label: "코스닥 초소형" },
];
export const SECTOR_THEMES = [
  { id: "s1", label: "반도체" }, { id: "s2", label: "금융" }, { id: "s3", label: "콘텐츠·미디어" },
  { id: "s4", label: "바이오·헬스케어" }, { id: "s5", label: "음식료·농업" }, { id: "s6", label: "레저·게임" },
  { id: "s7", label: "건설·소재" }, { id: "s8", label: "자동차·배터리" }, { id: "s9", label: "IT·플랫폼" },
  { id: "s10", label: "기계·철강" }, { id: "s11", label: "전자·전기" }, { id: "s12", label: "운송·방산" },
  { id: "s13", label: "에너지" }, { id: "s14", label: "미래기술" }, { id: "s15", label: "화장품·패션" },
  { id: "s16", label: "생활·정책" }, { id: "s17", label: "기타" },
];

const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";
const toggle = (arr: string[], id: string) => (arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);

export default function UniversePanel({ s, set, live = true }: {
  s: BacktestStrategy; set: Dispatch<SetStateAction<BacktestStrategy>>; live?: boolean;
}) {
  const u = s.universe;
  const patch = (p: Partial<BacktestStrategy["universe"]>) => set((x) => ({ ...x, universe: { ...x.universe, ...p } }));

  // 유니버스 선택이 바뀔 때마다 백엔드에 종목 수를 다시 물어 라이브로 갱신.
  // 백엔드 미가동/실패 시엔 기존 숫자를 그대로 유지(데모는 오프라인에서도 동작).
  const [counting, setCounting] = useState(false);
  useEffect(() => {
    if (!live) return;
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      setCounting(true);
      try {
        const { matched, total } = await universeCount({
          caps: u.caps, sectors: u.sectors, etf: u.etf, managed: u.managed, supervised: u.supervised,
          groups: u.groups.map((g) => ({ mode: g.mode, tickers: g.tickers })),
        }, ctrl.signal);
        set((x) => ({ ...x, universe: { ...x.universe, matched, totalUniverse: total } }));
      } catch {
        /* keep previous numbers */
      } finally {
        setCounting(false);
      }
    }, 300);
    return () => { clearTimeout(t); ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [u.caps, u.sectors, u.etf, u.managed, u.supervised, u.groups, live]);

  const [sectorOpts, setSectorOpts] = useState<SectorOption[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    fetchSectors(ctrl.signal).then(setSectorOpts).catch(() => {});
    return () => ctrl.abort();
  }, []);

  // 관심그룹: watchlistStorage 에서 실제 종목코드 로드 (mount 1회)
  useEffect(() => {
    try {
      const wls = listWatchlists();
      patch({ groups: wls.map((w) => ({ id: w.id, name: w.name, mode: "none" as const, tickers: w.tickers })) });
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: RL, padding: 16 }}>

      {/* header + live count */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 15 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text-primary)" }}>매매 대상 설정</span>
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>유니버스·업종·관심그룹</span>
        </div>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-secondary)", background: "var(--bg-section)", borderRadius: R, padding: "6px 11px" }}>
          {counting && <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", opacity: 0.7 }} />}
          매매 대상
          <span style={{ fontFamily: "var(--bs-font-mono)", fontSize: 15, fontWeight: 500, color: "var(--text-primary)", opacity: counting ? 0.45 : 1, transition: "opacity .15s" }}>{u.matched.toLocaleString()}</span>
          <span style={{ color: "var(--text-muted)" }}>/ {u.totalUniverse.toLocaleString()} 종목</span>
        </span>
      </div>

      {/* ETF / 관리 / 감리 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginBottom: 16 }}>
        {([["ETF", "etf"], ["관리종목", "managed"], ["감리종목", "supervised"]] as const).map(([label, key]) => (
          <div key={key}>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 5 }}>{label}</div>
            <Segmented tone="neutral" value={u[key] ? "in" : "out"} onChange={(t) => patch({ [key]: t === "in" } as Partial<BacktestStrategy["universe"]>)}
              options={[{ id: "out", label: "미포함" }, { id: "in", label: "포함" }]} />
          </div>
        ))}
      </div>

      {/* 시총군 */}
      <SubHead label="주식 유니버스" onAll={() => patch({ caps: u.caps.length === CAPS.length ? [] : CAPS.map((c) => c.id) })} allOn={u.caps.length === CAPS.length} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
        {CAPS.map((c) => {
          const on = u.caps.includes(c.id);
          return (
            <button key={c.id} type="button" onClick={() => patch({ caps: toggle(u.caps, c.id) })}
              style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, cursor: "pointer", borderRadius: 14, padding: "5px 11px",
                border: on ? "1px solid var(--border-strong)" : "1px solid var(--border)",
                background: on ? "var(--bg-section)" : "var(--bg-card)", color: on ? "var(--text-primary)" : "var(--text-secondary)" }}>
              {on && <Check size={12} style={{ color: "var(--text-secondary)" }} />}{c.label}
            </button>
          );
        })}
      </div>

      {/* 업종 (실제 업종 — /sectors) */}
      <SubHead label={`업종 (${sectorOpts.length || "…"}개)`} onAll={() => patch({ sectors: u.sectors.length === sectorOpts.length ? [] : sectorOpts.map((t) => t.id) })} allOn={sectorOpts.length > 0 && u.sectors.length === sectorOpts.length} />
      {sectorOpts.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>업종 목록을 불러오는 중…</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, marginBottom: 16 }}>
          {sectorOpts.map((t) => {
            const on = u.sectors.includes(t.id);
            return (
              <button key={t.id} type="button" onClick={() => patch({ sectors: toggle(u.sectors, t.id) })}
                style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", textAlign: "left",
                  border: "1px solid var(--border)", borderRadius: R, padding: "8px 11px", background: "var(--bg-card)" }}>
                <span style={{ width: 15, height: 15, borderRadius: 3, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--border-strong)", background: on ? "var(--bg-section)" : "transparent" }}>
                  {on && <Check size={11} style={{ color: "var(--text-secondary)" }} />}
                </span>
                <span style={{ fontSize: 13, color: on ? "var(--text-primary)" : "var(--text-secondary)" }}>{t.label}{t.size ? ` (${t.size})` : ""}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* 관심그룹 (watchlistStorage 연동) */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 9 }}>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>관심그룹 · 매수 대상/제외</span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{u.groups.length}개</span>
      </div>
      {u.groups.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>관심그룹이 없습니다 — 관심목록에서 종목을 추가하세요.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {u.groups.map((g, i) => (
            <div key={g.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, border: "1px solid var(--border)", borderRadius: R, padding: "8px 11px" }}>
              <span style={{ fontSize: 13, color: "var(--text-primary)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.name} ({g.tickers.length})</span>
              <Segmented tone={g.mode === "exclude" ? "sell" : "buy"} value={g.mode}
                onChange={(mode) => patch({ groups: u.groups.map((x, j) => (j === i ? { ...x, mode } : x)) })}
                options={[{ id: "none", label: "선택 안 함" }, { id: "include", label: "대상" }, { id: "exclude", label: "제외" }]} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SubHead({ label, allOn, onAll }: { label: string; allOn: boolean; onAll: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
      <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{label}</span>
      <button type="button" onClick={onAll} style={{ fontSize: 11, color: "var(--text-secondary)", background: "none", border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 2 }}>
        <Check size={12} /> {allOn ? "전체 해제" : "전체 선택"}
      </button>
    </div>
  );
}
