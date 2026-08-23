"use client";
// 대상 경로: frontend/src/components/backtest/panels/UniversePanel.tsx
//
// 매매 대상(유니버스) 화면(중립). 포함 토글 + 시총군 + 업종(테마 그룹) + 관심그룹 + 실시간 종목 수.
// matched/totalUniverse 는 mock — 실제로는 시총군/업종/그룹 변경 시 스크리너 count API 로 재계산.

import React from "react";
import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import { Check, Plus, X } from "lucide-react";
import { Segmented } from "@/shared/ui/kit";
import { universeCount } from "@/entities/backtest/universeApi";
import type { BacktestStrategy } from "@/entities/backtest/strategy";
import { listWatchlists, createWatchlist, deleteWatchlist } from "@/shared/lib/watchlistStorage";
import dynamic from "next/dynamic";
// 기본이 '닫힘' 인 창 — Radix Dialog 무게를 /backtest 첫 로드에서 뺀다(실측 +20 kB).
const WatchGroupModal = dynamic(() => import("./WatchGroupModal"), { ssr: false });
import ThemeTree from "./ThemeTree";

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
  // ★포커스 복귀를 명시적으로 되돌린다★ 창을 `next/dynamic` 으로 떼어내면 클릭 시점에는
  // Dialog 가 아직 마운트되지 않아, Radix 가 기억하는 복귀 대상이 트리거가 아닐 수 있다.
  // 닫은 뒤 포커스가 body 로 떨어지면 키보드 사용자는 목록의 어디에 있었는지 잃는다.
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const u = s.universe;
  const patch = (p: Partial<BacktestStrategy["universe"]>) => set((x) => ({ ...x, universe: { ...x.universe, ...p } }));

  // 유니버스 선택이 바뀔 때마다 백엔드에 종목 수를 다시 물어 라이브로 갱신.
  // 백엔드 미가동/실패 시엔 기존 숫자를 그대로 유지(데모는 오프라인에서도 동작).
  const [counting, setCounting] = useState(false);
  useEffect(() => {
    // 생존편향 보정 모드에서는 caps 등 세분화 필터가 백엔드로 전송되지 않으므로
    // (screener_routes.py — all_asof/top200_asof가 우선) 이 카운트가 실제 유니버스와
    // 무관해진다 — 오해를 부르는 숫자를 보여주지 않도록 재계산 자체를 건너뜀.
    if (!live || u.survivorshipMode !== "off") return;
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
  }, [u.caps, u.sectors, u.etf, u.managed, u.supervised, u.groups, u.survivorshipMode, live]);

  const [groupModalOpen, setGroupModalOpen] = useState(false);

  // 관심그룹: watchlistStorage 에서 실제 종목코드 로드. 모드(none/include/exclude)는 보존.
  const reloadGroups = () => {
    try {
      const wls = listWatchlists();
      const prevMode = new Map(u.groups.map((g) => [g.id, g.mode]));
      patch({ groups: wls.map((w) => ({ id: w.id, name: w.name, mode: prevMode.get(w.id) ?? "none", tickers: w.tickers })) });
    } catch { /* ignore */ }
  };
  // mount 1회 로드
  useEffect(() => {
    reloadGroups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSaveGroup = (name: string, tickers: string[]) => {
    createWatchlist(name, tickers);
    reloadGroups();
  };
  const handleDeleteGroup = (id: string) => {
    deleteWatchlist(id);
    reloadGroups();
  };

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

      {/* 유니버스 구성 방식 — 생존편향 보정: 시작일 당시 실제 거래 종목(상장폐지 포함) 기준.
          가장 근본적인 "후보 종목을 어떻게 정할지" 결정이라 아래 모든 세분화 필터보다 먼저. */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 5 }}>
          <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>유니버스 구성 방식</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {(u.survivorshipMode ?? "off") === "off"
              ? "아래 시총군·업종·ETF·관심그룹 선택을 그대로 사용"
              : "시작일 당시 실제 거래 종목 기준(상장폐지 포함) — 아래 시총군·업종·ETF·관심그룹 선택은 적용되지 않습니다"}
          </span>
        </div>
        <Segmented tone="neutral" value={u.survivorshipMode ?? "off"}
          onChange={(t) => patch({ survivorshipMode: t as BacktestStrategy["universe"]["survivorshipMode"] })}
          options={[
            { id: "off", label: "직접 선택(기본)" },
            { id: "all", label: "전체(생존편향 보정)" },
            { id: "top200", label: "TOP200(생존편향 보정)" },
          ]} />
      </div>

      {/* 유동성 게이트 — 전종목이면 선택한 전 종목이 백테스트에 들어감(적자·소형 포함) */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 5 }}>
          <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>유동성 게이트</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {s.liquidityGate === "off" ? "전종목 — 선택 전부 백테스트(적자·소형 포함)"
              : s.liquidityGate === "relaxed" ? "시총 ≥ 300억 · 거래대금 ≥ 3억"
              : "시총 ≥ 1000억 · 거래대금 ≥ 10억"}
          </span>
        </div>
        <Segmented tone="neutral" value={s.liquidityGate ?? "off"}
          onChange={(t) => set((x) => ({ ...x, liquidityGate: t as BacktestStrategy["liquidityGate"] }))}
          options={[{ id: "off", label: "전종목" }, { id: "relaxed", label: "완화" }, { id: "standard", label: "표준" }]} />
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

      {/* 평가 종목 상한 — 전종목 선택 시 200으로 잘리던 문제의 사용자 제어.
          기본 200 = 조건 추가 시에도 안전한 속도(수 초). 큰 값은 사용자가 명시적으로 선택했을
          때만(수 분 소요 가능 — 미적재 종목은 시세 수집 필요) */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>평가 종목 상한</span>
        <select value={s.evalCap ?? 200} onChange={(e) => set((x) => ({ ...x, evalCap: Number(e.target.value) }))}
          style={{ fontSize: 12, padding: "4px 8px", border: "1px solid var(--border)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }}>
          <option value={200}>200 종목 (기본, 빠름)</option>
          <option value={500}>500 종목</option>
          <option value={1000}>1,000 종목</option>
          <option value={2000}>2,000 종목</option>
          <option value={4000}>전체 (제한 없음, 대형 유니버스는 수 분 소요될 수 있음)</option>
        </select>
        <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
          첫 실행은 미적재 종목 시세 수집으로 수 분 걸릴 수 있음(진행률 표시) — 이후 DB에서 즉시
        </span>
      </div>

      {/* 업종 (88) — 젠포트 17그룹 → 88 세부업종 트리 */}
      <div style={{ marginBottom: 16 }}>
        <ThemeTree selected={u.sectors} onChange={(next) => patch({ sectors: next })} />
      </div>

      {/* 관심그룹 (watchlistStorage 연동) */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 9 }}>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>관심그룹 · 매수 대상/제외</span>
        <button type="button" ref={triggerRef} onClick={() => setGroupModalOpen(true)}
          style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: R, padding: "4px 9px", cursor: "pointer" }}>
          <Plus size={12} /> 그룹 추가
        </button>
      </div>
      {u.groups.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>관심그룹이 없습니다 — "그룹 추가"로 종목을 묶어보세요.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {u.groups.map((g, i) => (
            <div key={g.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, border: "1px solid var(--border)", borderRadius: R, padding: "8px 11px" }}>
              <span style={{ fontSize: 13, color: "var(--text-primary)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.name} ({g.tickers.length})</span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Segmented tone={g.mode === "exclude" ? "sell" : "buy"} value={g.mode}
                  onChange={(mode) => patch({ groups: u.groups.map((x, j) => (j === i ? { ...x, mode } : x)) })}
                  options={[{ id: "none", label: "선택 안 함" }, { id: "include", label: "대상" }, { id: "exclude", label: "제외" }]} />
                <button type="button" aria-label="그룹 삭제" onClick={() => handleDeleteGroup(g.id)}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", flexShrink: 0 }}><X size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 선택 현황 요약 — 매매 대상 탭 하단 채움 + 빠른 확인 */}
      <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px dashed var(--border-strong)" }}>
        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 9 }}>선택 현황</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
          {([
            ["매매 대상", `${u.matched.toLocaleString()} / ${u.totalUniverse.toLocaleString()}`],
            ["시총군", u.caps.length >= CAPS.length ? "전체" : `${u.caps.length} / ${CAPS.length}군`],
            ["업종", u.sectors.filter((x) => x.startsWith("theme:")).length > 0
              ? `${u.sectors.filter((x) => x.startsWith("theme:")).length} / 88개` : "전체"],
            ["관심그룹", `${u.groups.filter((g) => g.mode !== "none").length}개 적용`],
          ] as const).map(([label, val]) => (
            <div key={label} style={{ border: "1px solid var(--border)", borderRadius: R, padding: "9px 10px" }}>
              <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginBottom: 4 }}>{label}</div>
              <div style={{ fontFamily: "var(--bs-font-mono)", fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{val}</div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
          매매 대상을 확정했으면 아래 <b>백테스트 실행</b>으로 진행하세요.
        </div>
      </div>

      <WatchGroupModal open={groupModalOpen} onClose={() => { setGroupModalOpen(false); // ★언마운트 뒤에 포커스를 준다★ 같은 틱에 주면 Radix 의 포커스 가드가 아직
        // 살아 있어 도로 가져간다 — 한 프레임 뒤에야 트리거가 실제로 포커스를 받는다.
        requestAnimationFrame(() => triggerRef.current?.focus()); }} onSave={handleSaveGroup} />
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
