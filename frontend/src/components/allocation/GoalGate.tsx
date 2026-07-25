"use client";
// ── 목표 선택 게이트 (위저드 진입점) ──────────────────────────────────────────────
// "어떤 목표의 포트폴리오를 만드시겠습니까?" — 상세 대시보드 직행 대신 목표를 먼저
// 고른다. 각 목표 = 재사용 시드(모델 + 스타터 유니버스 + 옵션 뷰). 시드는
// backtestBridgeApi.sectors()의 sample 티커 / macroApi.regime() 권고 모드 / 큐레이션
// 폴백으로 구성 → setModel/setHoldingsReset/setViewsLogged 재사용 → Construct로 착지.
import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { backtestBridgeApi } from "@/lib/screenerApi";
import { macroApi, type RegimeState } from "@/lib/macroApi";
import type { AllocationModel, AllocationViewInput } from "@/lib/allocationApi";
import { equalize, type Holding } from "./PortfolioBuilder";
import { isKnownAllocationRoute, useAllocation } from "./AllocationProvider";
import { listStudies, type AllocationStudy } from "@/lib/allocationStorage";
import { listWatchlists, type Watchlist } from "@/lib/watchlistStorage";

type Sector = { id: string; label: string; size: number; sample: string[] };

// 시세·마스터 미적재/게이트 로딩 전에도 항상 유효한 포트폴리오를 세팅하는 큐레이션 폴백
const CURATED: Holding[] = [
  { code: "005930", name: "삼성전자", weight: 0 },
  { code: "000660", name: "SK하이닉스", weight: 0 },
  { code: "035420", name: "NAVER", weight: 0 },
  { code: "051910", name: "LG화학", weight: 0 },
  { code: "005380", name: "현대차", weight: 0 },
  { code: "105560", name: "KB금융", weight: 0 },
];

const MODEL_LABEL: Record<AllocationModel, string> = {
  mvo: "최대 샤프 (MVO)", bl: "Black-Litterman", risk_parity: "리스크 패리티", hrp: "HRP", min_var: "최소 분산",
  max_div: "최대 분산", min_cvar: "최소 CVaR",
};

function fromSectors(secs: Sector[], prefer: string[], count: number): Holding[] {
  if (!secs.length) return [];
  const ordered = [
    ...prefer.flatMap((p) => secs.filter((s) => s.label.includes(p))),
    ...secs.filter((s) => !prefer.some((p) => s.label.includes(p))).sort((a, b) => b.size - a.size),
  ];
  const out: Holding[] = []; const seen = new Set<string>();
  for (const s of ordered) {
    for (const t of s.sample || []) {
      if (out.length >= count) break;
      if (!seen.has(t)) { seen.add(t); out.push({ code: t, name: t, weight: 0 }); }
    }
    if (out.length >= count) break;
  }
  return out;
}

function diversified(secs: Sector[], count: number): Holding[] {
  if (!secs.length) return [];
  const out: Holding[] = []; const seen = new Set<string>();
  for (const s of [...secs].sort((a, b) => b.size - a.size)) {
    const t = (s.sample || [])[0];
    if (t && !seen.has(t) && out.length < count) { seen.add(t); out.push({ code: t, name: t, weight: 0 }); }
  }
  return out;
}

const Ic = ({ d }: { d: string }) => (
  <svg className="aas-goal-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}
    strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);

interface GoalDef {
  id: string; label: string; sub: string; model: AllocationModel | "auto"; icon: React.ReactNode;
  seed: (secs: Sector[]) => Holding[];
  view?: (h: Holding[]) => AllocationViewInput[];
}

const GOALS: GoalDef[] = [
  {
    id: "growth", label: "성장 추구", sub: "고성장 섹터 집중", model: "mvo",
    icon: <Ic d="M3 17l6-6 4 4 8-8M21 7h-5M21 7v5" />,
    seed: (s) => fromSectors(s, ["반도체", "2차전지", "인터넷", "게임", "바이오"], 6),
  },
  {
    id: "defensive", label: "방어·안정", sub: "저변동 우선", model: "min_var",
    icon: <Ic d="M12 3l7 3v5c0 4.4-3 8.5-7 10-4-1.5-7-5.6-7-10V6l7-3z" />,
    seed: (s) => fromSectors(s, ["통신", "금융", "철강", "화학", "자동차"], 6),
  },
  {
    id: "balanced", label: "균형 분산", sub: "섹터 고른 분산", model: "risk_parity",
    icon: <Ic d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4" />,
    seed: (s) => diversified(s, 6),
  },
  {
    id: "theme", label: "테마·뷰 기반", sub: "핵심 테마 강세 뷰", model: "bl",
    icon: <Ic d="M9 18h6M10 21h4M12 3a6 6 0 0 1 4 10.5c-.6.6-1 1.4-1 2.2H9c0-.8-.4-1.6-1-2.2A6 6 0 0 1 12 3z" />,
    seed: (s) => fromSectors(s, ["반도체", "2차전지"], 5),
    view: (h) => (h.length ? [{ assets: h.map((x) => x.code), direction: 1, magnitude_pct: 5, confidence: 65, label: "테마 강세" }] : []),
  },
  {
    id: "regime", label: "현재 국면 맞춤", sub: "레짐 권고 모드 자동", model: "auto",
    icon: <Ic d="M12 3a9 9 0 1 0 9 9M12 3v9l6 3M12 3a9 9 0 0 1 9 9" />,
    seed: (s) => diversified(s, 6),
  },
];

function modelFor(g: GoalDef, regime: RegimeState | null): AllocationModel {
  if (g.model !== "auto") return g.model;
  const m = regime?.recommended_mode ?? regime?.markets?.kr?.recommended_mode;
  return m === "DEFENSIVE" ? "min_var" : m === "CAUTIOUS" ? "risk_parity" : "bl";
}

export function GoalGate() {
  const router = useRouter();
  const { setGoal, setModel, setHoldingsReset, setViewsLogged, loadStudy, logEvent, lastPos, holdings } = useAllocation();
  const sectorsQ = useQuery({ queryKey: ["screener", "sectors"], queryFn: () => backtestBridgeApi.sectors().catch(() => null) });
  const regimeQ = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime().catch(() => null) });
  const [studies, setStudies] = useState<AllocationStudy[]>([]);
  const [wls, setWls] = useState<Watchlist[]>([]);
  useEffect(() => { setStudies(listStudies()); setWls(listWatchlists()); }, []);

  const secs = (sectorsQ.data?.sectors ?? []) as Sector[];
  const regime = (regimeQ.data ?? null) as RegimeState | null;

  const choose = (g: GoalDef) => {
    const seed = g.seed(secs);
    const hold = equalize(seed.length >= 2 ? seed.slice(0, 8) : CURATED.slice(0, 5));
    setGoal({ id: g.id, label: g.label });
    setModel(modelFor(g, regime));
    setHoldingsReset(hold);
    if (g.view) { const v = g.view(hold); if (v.length) setViewsLogged(v); }
    logEvent(`목표 선택 — ${g.label}`);
    router.push("/allocation/construct");
  };
  const startStudy = (s: AllocationStudy) => { loadStudy(s); setGoal({ id: "study", label: s.name }); router.push("/allocation/construct"); };
  const startWatchlist = (wl: Watchlist) => {
    setGoal({ id: "watchlist", label: wl.name });
    setHoldingsReset(equalize(wl.tickers.map((c) => ({ code: c, name: c, weight: 0 }))));
    logEvent(`관심그룹에서 시작 — ${wl.name}`);
    router.push("/allocation/construct");
  };
  const startEmpty = () => { setGoal({ id: "custom", label: "직접 구성" }); setModel("bl"); setHoldingsReset([]); router.push("/allocation/construct"); };
  const startStrategy = () => { setGoal({ id: "strategy", label: "매크로 전략" }); setHoldingsReset([]); logEvent("매크로 전략 라이브러리에서 시작"); router.push("/allocation/construct"); };

  const canResume = !!lastPos && isKnownAllocationRoute(lastPos) && holdings.length >= 1;
  const regimeReady = !!regime;

  return (
    <div className="aas-gate tpage-fade">
      <div className="aas-gate-crumb num">MODULE 06 / ALLOCATION STUDIO</div>
      <h1 className="aas-gate-q">어떤 목표의 포트폴리오를 만드시겠습니까?</h1>
      <p className="aas-gate-lead">
        전략 수립을 <b>Setup → Logic → Validation</b> 단계로 순서대로 진행합니다. 목표를 고르면
        시작 유니버스와 최적화 엔진이 자동 세팅되고, 다음 단계에서 자유롭게 조정할 수 있습니다.
      </p>

      {canResume && (
        <button className="aas-gate-resume"
          onClick={() => router.push(isKnownAllocationRoute(lastPos) ? lastPos! : "/allocation/construct")}>
          <span>이어서 계속 — 마지막 작업 재개</span>
          <em className="num">{holdings.length}종목 담긴 상태 →</em>
        </button>
      )}

      <div className="aas-gate-grid">
        {GOALS.map((g) => (
          <button key={g.id} className="aas-goal" onClick={() => choose(g)}
            disabled={g.id === "regime" && !regimeReady && sectorsQ.isLoading}>
            <div className="aas-goal-head">{g.icon}<span className="aas-goal-t">{g.label}</span></div>
            <div className="aas-goal-d">{g.sub}</div>
            <div className="aas-goal-seed num">
              <span>{g.id === "regime" ? (regimeReady ? `레짐: ${regime?.recommended_mode ?? "NORMAL"}` : "레짐 자동") : MODEL_LABEL[g.model as AllocationModel]}</span>
              <span>{g.id === "theme" ? "+ 강세 뷰" : g.id === "balanced" || g.id === "regime" ? "분산 시드" : "섹터 시드"}</span>
            </div>
          </button>
        ))}
        <button className="aas-goal aas-goal-strategy" onClick={startStrategy}>
          <div className="aas-goal-head">
            <Ic d="M4 19V5M4 19h16M8 15l4-6 3 3 5-8" />
            <span className="aas-goal-t">매크로 전략 기반</span>
          </div>
          <div className="aas-goal-d">듀얼모멘텀·리스크패리티·HRP 등 22전략 불러오기</div>
          <div className="aas-goal-seed num"><span>매크로 탭 전략</span><span>+ 재최적화</span></div>
        </button>
        <button className="aas-goal aas-goal-custom" onClick={startEmpty}>
          <div className="aas-goal-head"><Ic d="M12 5v14M5 12h14" /><span className="aas-goal-t">직접 구성</span></div>
          <div className="aas-goal-d">빈 상태에서 자산을 직접 담기</div>
          <div className="aas-goal-seed num"><span>Black-Litterman</span><span>빈 시드</span></div>
        </button>
      </div>

      <div className="aas-gate-foot">
        {!!wls.length && (
          <div className="aas-gate-footsec">
            <span className="aas-gate-footlab">관심그룹에서 시작</span>
            <div className="aas-gate-chips">
              {wls.slice(0, 6).map((wl) => (
                <button key={wl.id} className="as-chip" onClick={() => startWatchlist(wl)} title={`${wl.tickers.length}종목`}>
                  {wl.name} <b className="num">{wl.tickers.length}</b>
                </button>
              ))}
            </div>
          </div>
        )}
        {!!studies.length && (
          <div className="aas-gate-footsec">
            <span className="aas-gate-footlab">저장된 스터디 불러오기</span>
            <div className="aas-gate-chips">
              {studies.slice(0, 6).map((s) => (
                <button key={s.id} className="as-chip" onClick={() => startStudy(s)}
                  title={`${Object.keys(s.holdings).length}종목 · ${s.savedAt.slice(0, 10)}`}>
                  {s.name} <b className="num">{Object.keys(s.holdings).length}</b>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="aas-gate-footsec">
          <button className="aas-gate-skip" onClick={() => router.push("/allocation/overview")}>대시보드로 건너뛰기 →</button>
        </div>
      </div>
    </div>
  );
}
