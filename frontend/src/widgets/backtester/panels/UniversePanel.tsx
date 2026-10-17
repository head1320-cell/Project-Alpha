"use client";
// 대상 경로: frontend/src/components/backtest/panels/UniversePanel.tsx
//
// ③ 어디서 고를까 — 매매 대상(유니버스, 중립 톤). 구성 방식 + 유동성 게이트 + 포함 토글 + 시총군 + 업종 + 관심그룹 + 실시간 종목 수.
// BU3: 인라인 style 을 걷고 kit 절·`bte-*` 클래스로 그린다. 대상 수 요청(300ms)·상태 갱신은 그대로(요청 골든이 건다).
// matched/totalUniverse 는 mock — 실제로는 시총군/업종/그룹 변경 시 스크리너 count API 로 재계산.

import React from "react";
import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import { Check, Plus, X } from "lucide-react";
import { Field, Section, Segmented } from "@/shared/ui/kit";
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
    <div className="bte-col">
      <Section title="매매 대상" hint="어떤 종목 안에서 고를지 정해요" tone="neutral" enabled>
        <div className="bte-uni-count" aria-live="polite">
          <span className="bte-sm">지금 고른 종목</span>
          <b className={counting ? "is-counting" : undefined}>{u.matched.toLocaleString("ko-KR")}</b>
          <span className="bte-sm">/ 전체 {u.totalUniverse.toLocaleString("ko-KR")}종목{counting ? " · 다시 세는 중이에요" : ""}</span>
        </div>

        {/* 유니버스 구성 방식 — 생존편향 보정: 시작일 당시 실제 거래 종목(상장폐지 포함) 기준.
            가장 근본적인 "후보 종목을 어떻게 정할지" 결정이라 아래 모든 세분화 필터보다 먼저. */}
        <Field label="고르는 방식" width={96}>
          <Segmented tone="neutral" act="survivorship" value={u.survivorshipMode ?? "off"}
            onChange={(t) => patch({ survivorshipMode: t as BacktestStrategy["universe"]["survivorshipMode"] })}
            options={[
              { id: "off", label: "직접 고르기(기본)" },
              { id: "all", label: "전체(생존편향 보정)" },
              { id: "top200", label: "TOP200(생존편향 보정)" },
            ]} />
          <p className="bte-note">
            {(u.survivorshipMode ?? "off") === "off"
              ? "아래 시총군·업종·ETF·관심그룹 선택을 그대로 써요."
              : "시작일 당시 실제로 거래된 종목(상장폐지 포함)으로 골라요. 아래 시총군·업종·ETF·관심그룹 선택은 쓰지 않아요."}
          </p>
        </Field>

        {/* 유동성 게이트 — 전종목이면 선택한 전 종목이 백테스트에 들어감(적자·소형 포함) */}
        <Field label="유동성 게이트" width={96}>
          <Segmented tone="neutral" act="liq-gate" value={s.liquidityGate ?? "off"}
            onChange={(t) => set((x) => ({ ...x, liquidityGate: t as BacktestStrategy["liquidityGate"] }))}
            options={[{ id: "off", label: "전종목" }, { id: "relaxed", label: "완화" }, { id: "standard", label: "표준" }]} />
          <p className="bte-note">
            {s.liquidityGate === "off" ? "고른 종목을 모두 넣어요(적자·소형 포함)."
              : s.liquidityGate === "relaxed" ? "시가총액 300억 이상 · 하루 거래대금 3억 이상만 남겨요."
              : "시가총액 1,000억 이상 · 하루 거래대금 10억 이상만 남겨요."}
          </p>
        </Field>

        {/* ETF / 관리 / 감리 */}
        {([["ETF", "etf"], ["관리종목", "managed"], ["감리종목", "supervised"]] as const).map(([label, key]) => (
          <Field key={key} label={label} width={96}>
            <Segmented tone="neutral" value={u[key] ? "in" : "out"} onChange={(t) => patch({ [key]: t === "in" } as Partial<BacktestStrategy["universe"]>)}
              options={[{ id: "out", label: "빼기" }, { id: "in", label: "넣기" }]} />
          </Field>
        ))}
      </Section>

      <Section title="시총군" hint="여섯 무리 중 고르기" tone="neutral" enabled>
        <SubHead label="고른 무리" onAll={() => patch({ caps: u.caps.length === CAPS.length ? [] : CAPS.map((c) => c.id) })} allOn={u.caps.length === CAPS.length} />
        <div className="bte-pills">
          {CAPS.map((c) => {
            const on = u.caps.includes(c.id);
            return (
              <button key={c.id} type="button" data-act="cap" aria-pressed={on} className="bte-pill"
                onClick={() => patch({ caps: toggle(u.caps, c.id) })}>
                {on && <Check size={14} aria-hidden />}{c.label}
              </button>
            );
          })}
        </div>

        {/* 평가 종목 상한 — 전종목 선택 시 200으로 잘리던 문제의 사용자 제어.
            기본 200 = 조건 추가 시에도 안전한 속도(수 초). 큰 값은 사용자가 명시적으로 선택했을
            때만(수 분 소요 가능 — 미적재 종목은 시세 수집 필요) */}
        <Field label="평가 종목 상한" width={96}>
          <select value={s.evalCap ?? 200} className="kit-select" aria-label="평가 종목 상한"
            onChange={(e) => set((x) => ({ ...x, evalCap: Number(e.target.value) }))}>
            <option value={200}>200종목 (기본, 빨라요)</option>
            <option value={500}>500종목</option>
            <option value={1000}>1,000종목</option>
            <option value={2000}>2,000종목</option>
            <option value={4000}>전체 (제한 없음 — 큰 유니버스는 몇 분 걸릴 수 있어요)</option>
          </select>
          <p className="bte-note">처음 실행은 적재되지 않은 종목의 시세를 모으느라 몇 분 걸릴 수 있어요(진행률을 보여 드려요). 그다음부터는 바로예요.</p>
        </Field>
      </Section>

      {/* 업종 (88) — 젠포트 17그룹 → 88 세부업종 트리 */}
      <Section title="업종" hint="17무리 · 88 세부 업종" tone="neutral" enabled>
        <ThemeTree selected={u.sectors} onChange={(next) => patch({ sectors: next })} />
      </Section>

      {/* 관심그룹 (watchlistStorage 연동) */}
      <Section title="관심그룹" hint="묶어 둔 종목을 넣거나 빼요" tone="neutral" enabled>
        <div className="bte-row">
          <button type="button" ref={triggerRef} className="tx-btn tx-btn--sub bte-group-add" onClick={() => setGroupModalOpen(true)}>
            <Plus size={16} aria-hidden /> 그룹 추가
          </button>
        </div>
        {u.groups.length === 0 ? (
          <p className="bte-note">관심그룹이 없어요. ‘그룹 추가’로 종목을 묶어 보세요.</p>
        ) : (
          <ul className="bte-groups">
            {u.groups.map((g, i) => (
              <li key={g.id} className="bte-group">
                <span className="bte-group-n">{g.name} <span className="bte-sm">{g.tickers.length}종목</span></span>
                <Segmented tone={g.mode === "exclude" ? "sell" : "buy"} value={g.mode}
                  onChange={(mode) => patch({ groups: u.groups.map((x, j) => (j === i ? { ...x, mode } : x)) })}
                  options={[{ id: "none", label: "쓰지 않음" }, { id: "include", label: "대상" }, { id: "exclude", label: "제외" }]} />
                <button type="button" aria-label={`${g.name} 그룹 삭제`} className="bte-icon-btn" onClick={() => handleDeleteGroup(g.id)}>
                  <X size={16} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <WatchGroupModal open={groupModalOpen} onClose={() => { setGroupModalOpen(false); // ★언마운트 뒤에 포커스를 준다★ 같은 틱에 주면 Radix 의 포커스 가드가 아직
        // 살아 있어 도로 가져간다 — 한 프레임 뒤에야 트리거가 실제로 포커스를 받는다.
        requestAnimationFrame(() => triggerRef.current?.focus()); }} onSave={handleSaveGroup} />
    </div>
  );
}

function SubHead({ label, allOn, onAll }: { label: string; allOn: boolean; onAll: () => void }) {
  return (
    <div className="bte-row">
      <span className="bte-sub-h">{label}</span>
      <button type="button" className="bte-link" onClick={onAll}>{allOn ? "모두 빼기" : "모두 고르기"}</button>
    </div>
  );
}
