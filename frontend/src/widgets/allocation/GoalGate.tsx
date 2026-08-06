"use client";
// ── 목표 선택 게이트 (위저드 진입점) ──────────────────────────────────────────────
// "어떤 목표의 포트폴리오를 만드시겠습니까?" — 상세 대시보드 직행 대신 목표를 먼저
// 고른다. 각 목표 = 재사용 시드(모델 + 스타터 유니버스 + 옵션 뷰). 시드는
// backtestBridgeApi.sectors()의 sample 티커 / macroApi.regime() 권고 모드 / 큐레이션
// 폴백으로 구성 → setModel/setHoldingsReset/setViewsLogged 재사용 → Construct로 착지.
import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/shadcn/card";
import { Badge } from "@/shared/ui/shadcn/badge";
import { Button } from "@/shared/ui/shadcn/button";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import type { AllocationModel, AllocationViewInput } from "@/entities/allocation/api";
import { equalize, type Holding } from "./PortfolioBuilder";
import { isKnownAllocationRoute, useAllocation } from "./AllocationProvider";
import { GateStepper } from "./GateStepper";
import { useResearchRegime } from "./useResearchRegime";
import { listStudies, type AllocationStudy } from "@/entities/allocation/storage";
import { listWatchlists, type Watchlist } from "@/shared/lib/watchlistStorage";

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
  /** 두 번째 배지 — 이 프리셋이 무엇을 시드하는지. 예전에는 렌더 안 삼항 사슬이었다. */
  seedTag: string;
  /** 라이브러리에서 시작하는 프리셋 — 유니버스를 시드하지 않고 매크로 전략 목록으로 착지. */
  library?: boolean;
}

// ★순서가 E2E 계약이다★ `성장 추구` 가 첫 `.aas-goal` 이어야 한다 —
// aas.spec.ts:21 은 텍스트로, allocation-backtest / research-run-roundtrip / timing-factors 는
// `.aas-goal` 의 `.first()` 로 이 화면을 통과한다. 시드가 없는 카드를 앞에 두면
// 세 스펙이 빈 Construct 로 들어가 **조용히** 다른 것을 검증하게 된다.
const GOALS: GoalDef[] = [
  {
    id: "growth", label: "성장 추구", sub: "고성장 섹터 집중", model: "mvo", seedTag: "섹터 시드",
    icon: <Ic d="M3 17l6-6 4 4 8-8M21 7h-5M21 7v5" />,
    seed: (s) => fromSectors(s, ["반도체", "2차전지", "인터넷", "게임", "바이오"], 6),
  },
  {
    id: "defensive", label: "방어·안정", sub: "저변동 우선", model: "min_var", seedTag: "섹터 시드",
    icon: <Ic d="M12 3l7 3v5c0 4.4-3 8.5-7 10-4-1.5-7-5.6-7-10V6l7-3z" />,
    seed: (s) => fromSectors(s, ["통신", "금융", "철강", "화학", "자동차"], 6),
  },
  {
    id: "balanced", label: "균형 분산", sub: "섹터 고른 분산", model: "risk_parity", seedTag: "분산 시드",
    icon: <Ic d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4" />,
    seed: (s) => diversified(s, 6),
  },
  {
    id: "theme", label: "테마·뷰 기반", sub: "핵심 테마 강세 뷰", model: "bl", seedTag: "+ 강세 뷰",
    icon: <Ic d="M9 18h6M10 21h4M12 3a6 6 0 0 1 4 10.5c-.6.6-1 1.4-1 2.2H9c0-.8-.4-1.6-1-2.2A6 6 0 0 1 12 3z" />,
    seed: (s) => fromSectors(s, ["반도체", "2차전지"], 5),
    view: (h) => (h.length ? [{ assets: h.map((x) => x.code), direction: 1, magnitude_pct: 5, confidence: 65, label: "테마 강세" }] : []),
  },
  {
    id: "regime", label: "현재 국면 맞춤", sub: "레짐 권고 모드 자동", model: "auto", seedTag: "분산 시드",
    icon: <Ic d="M12 3a9 9 0 1 0 9 9M12 3v9l6 3M12 3a9 9 0 0 1 9 9" />,
    seed: (s) => diversified(s, 6),
  },
  {
    // 예전에는 그리드 뒤에 손으로 적은 별도 카드였다(클래스 `.aas-goal-strategy` 는 CSS 규칙이
    // 아예 없었다 — 붙어 있지만 아무 일도 안 하는 클래스). 다른 다섯과 같은 프리셋이므로
    // 같은 배열에 넣는다. 착지 동작만 다르다: 유니버스가 아니라 전략 라이브러리를 연다.
    id: "strategy", label: "매크로 전략 기반", sub: "듀얼모멘텀·리스크패리티·HRP 등 22전략 불러오기",
    model: "bl", seedTag: "+ 재최적화", library: true,
    icon: <Ic d="M4 19V5M4 19h16M8 15l4-6 3 3 5-8" />,
    seed: () => [],
  },
];

function modelFor(g: GoalDef, recommendedMode: string | null): AllocationModel {
  if (g.model !== "auto") return g.model;
  const m = recommendedMode;
  return m === "DEFENSIVE" ? "min_var" : m === "CAUTIOUS" ? "risk_parity" : "bl";
}

/** 첫 번째 배지 — 이 프리셋이 어떤 엔진으로 착지하는지. 레짐 프리셋만 런타임에 정해진다. */
function engineTag(g: GoalDef, recommendedMode: string | null): string {
  if (g.library) return "매크로 탭 전략";
  if (g.model === "auto") return recommendedMode ? `레짐: ${recommendedMode}` : "레짐 자동";
  return MODEL_LABEL[g.model];
}

export function GoalGate() {
  const router = useRouter();
  const { setGoal, setModel, setHoldingsReset, setViewsLogged, loadStudy, logEvent, lastPos, holdings } = useAllocation();
  const sectorsQ = useQuery({ queryKey: ["screener", "sectors"], queryFn: () => backtestBridgeApi.sectors().catch(() => null) });
  const [studies, setStudies] = useState<AllocationStudy[]>([]);
  const [wls, setWls] = useState<Watchlist[]>([]);
  useEffect(() => { setStudies(listStudies()); setWls(listWatchlists()); }, []);

  const secs = (sectorsQ.data?.sectors ?? []) as Sector[];
  // 게이트는 스터디가 생기기 **전에** 열릴 수 있다 — 붙은 스냅샷이 없으면 라이브로 폴백하므로
  // 첫 진입 동작은 그대로다. ☰ 목표로 되돌아온 경우에는 고정된 국면을 따른다.
  const rg = useResearchRegime();

  const choose = (g: GoalDef) => {
    // 전략 라이브러리 프리셋은 유니버스를 시드하지 않는다 — Construct 에서 22전략 목록을
    // 여는 것이 이 프리셋의 내용이다. 기존 startStrategy 동작을 그대로 유지한다.
    if (g.library) {
      setGoal({ id: "strategy", label: "매크로 전략" });
      setHoldingsReset([]);
      logEvent("매크로 전략 라이브러리에서 시작");
      router.push("/allocation/construct");
      return;
    }
    const seed = g.seed(secs);
    const hold = equalize(seed.length >= 2 ? seed.slice(0, 8) : CURATED.slice(0, 5));
    setGoal({ id: g.id, label: g.label });
    setModel(modelFor(g, rg.recommendedMode));
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

  const canResume = !!lastPos && isKnownAllocationRoute(lastPos) && holdings.length >= 1;
  const regimeReady = !!rg.recommendedMode;

  return (
    <div className="aas-gate tpage-fade">
      {/* 3단계 진행 표시 — 붙어 있다(§50). 라벨은 PHASES 레지스트리에서 온다. */}
      <GateStepper />

      <h1 className="aas-gate-q">어떤 목표의 포트폴리오를 만드시겠습니까?</h1>
      <p className="aas-gate-lead">
        목표를 고르면 시작 유니버스와 최적화 엔진이 자동 세팅되고, 다음 단계에서 자유롭게
        조정할 수 있습니다. 어떤 선택도 되돌릴 수 있습니다.
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
          <Card asChild key={g.id} className="aas-goal">
            <button onClick={() => choose(g)}
              disabled={g.id === "regime" && !regimeReady && sectorsQ.isLoading}>
              <CardHeader className="aas-goal-head">
                <span className="aas-goal-icw">{g.icon}</span>
                <CardTitle as="h3" className="aas-goal-t">{g.label}</CardTitle>
              </CardHeader>
              <CardContent className="aas-goal-body">
                <span className="aas-goal-d">{g.sub}</span>
                <span className="aas-goal-seed">
                  <Badge variant="secondary" className="aas-goal-bdg num">
                    {engineTag(g, rg.recommendedMode)}
                  </Badge>
                  <Badge variant="secondary" className="aas-goal-bdg num">{g.seedTag}</Badge>
                </span>
              </CardContent>
            </button>
          </Card>
        ))}
      </div>

      {/* ★빈 프리셋은 그리드 **밖**에 둔다★
          브리프의 요구(파선 테두리로 구분)이기도 하고, 그리드 밖이라는 사실 자체가
          `.aas-goal` 의 `.first()` 가 절대 이 카드가 되지 않도록 보장한다 — 이 카드는
          자산을 0개로 시드하므로, 앞에 오면 세 스펙이 빈 Construct 를 검증하게 된다. */}
      <Card asChild className="aas-goal aas-goal-custom">
        <button onClick={startEmpty}>
          <CardHeader className="aas-goal-head">
            <span className="aas-goal-icw"><Ic d="M12 5v14M5 12h14" /></span>
            <CardTitle as="h3" className="aas-goal-t">직접 구성 (Start from Scratch)</CardTitle>
          </CardHeader>
          <CardContent className="aas-goal-body">
            <span className="aas-goal-d">사전 구성 없이 빈 상태에서 자산을 직접 담습니다.</span>
            <span className="aas-goal-seed">
              <Badge variant="secondary" className="aas-goal-bdg num">Black-Litterman</Badge>
              <Badge variant="secondary" className="aas-goal-bdg num">빈 시드</Badge>
            </span>
          </CardContent>
        </button>
      </Card>

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
        <div className="aas-gate-footsec aas-gate-footskip">
          <Button variant="ghost" size="sm" className="aas-gate-skip"
            onClick={() => router.push("/allocation/overview")}>
            대시보드로 건너뛰기
            <ArrowRight size={14} aria-hidden="true" />
          </Button>
        </div>
      </div>
    </div>
  );
}
