"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// /dev/ui — shared/ui 프리미티브 격리 갤러리
//
// 목적: shared/ui 의 컴포넌트 export **36개 전부**를 데이터 없이 한 화면에서 렌더한다.
//   · 에이전트가 "이 프리미티브가 어떻게 생겼나"를 알려고 소비 화면을 뒤지지 않아도 된다.
//   · Playwright(e2e/dev-ui.spec.ts)가 여기서 **클래스 계약을 회귀 검사**한다.
//     프리미티브가 내보내는 클래스명(.pv-* · .tstate-* · .tstat-* · .skeleton …)이
//     E2E 계약인데, 지금까지 그것을 직접 검증하는 테스트가 없었다.
//
// Storybook 을 쓰지 않은 이유: 패키지 40~60개와 두 번째 빌드 파이프라인이 붙고,
// "순수 CSS 유지 · UI 프레임워크 이전 금지"(CLAUDE.md) 와 충돌한다. 이 라우트는
// 앱 자체의 빌드/CSS/E2E 를 그대로 쓴다 — 새 의존성 0개.
//
// 갤러리 자체는 네트워크 호출 0(모든 표본이 하드코딩 props). 단 셸(TerminalShell) 헤더의
// RegimeBadge 가 /macro/regime 을 한 번 부르므로 페이지 전체로는 0이 아니다.
// nav 에 링크되지 않은 내부 라우트다.
//
// 제외 없음. 처음엔 CommandPalette / CommandHint 두 개를 뺐었는데, 그 둘은 도달 불가
// 코드로 확인되어 같은 브랜치에서 삭제했다(TopNav 포함). 지금은 shared/ui 의 컴포넌트
// export 와 이 갤러리의 표본이 1:1 로 맞는다 — 스펙이 그 일치를 강제한다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useState } from "react";
import { Activity } from "lucide-react";

import {
  PageHeader, PageContent, StatCard, Tabs, Spinner, Badge,
  Section as PSection, FormRow, Field as PField, ErrorMsg, Empty,
} from "@/shared/ui/primitives";
import {
  GroupedSelect, Toggle, Section as KSection, SubToggle,
  Field as KField, QuickStepper, Segmented,
} from "@/shared/ui/kit";
import { LoadingState, EmptyState, ErrorState, UnavailableState, AsyncState } from "@/shared/ui/States";
import { EvidenceBadge } from "@/shared/ui/evidence";
import { EvidenceDrawer } from "@/shared/ui/EvidenceDrawer";
// shadcn 벤더링본 — .devui-item 계약을 건드리지 않도록 **별도 섹션**에서만 쓴다(아래 주석 참조).
import { Button } from "@/shared/ui/shadcn/button";
import { Badge as ShadBadge } from "@/shared/ui/shadcn/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/shared/ui/shadcn/card";
import {
  Dialog, DialogTrigger, DialogContent, DialogHeader,
  DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from "@/shared/ui/shadcn/dialog";
import {
  Skeleton, SkeletonText, SkeletonCard, SkeletonTable,
  TickValue, MetricCard, Sparkline,
} from "@/shared/ui/feedback";
import { MiniViz, StatGrid, Stat, type MiniVizKind } from "@/shared/ui/MiniViz";
import SectionHead from "@/shared/ui/SectionHead";

// ── 갤러리 프레임 ────────────────────────────────────────────────────────────
// 페이지 자체 크롬은 .devui-* 만 쓴다. 앱 클래스(.pv-* 등)는 표본 안에서만 나타나야
// 하므로(그래야 스펙이 "PageHeader 표본 1개" 를 셀 수 있다) 여기서는 쓰지 않는다.

function Specimen({ name, from, note, children }: {
  name: string; from: string; note?: string; children: React.ReactNode;
}) {
  return (
    <div className="devui-item">
      <div className="devui-item-head">
        <code className="devui-item-name">{name}</code>
        <span className="devui-item-from">{from}</span>
      </div>
      {note && <p className="devui-item-note">{note}</p>}
      <div className="devui-stage">{children}</div>
    </div>
  );
}

function Variant({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="devui-variant">
      <span className="devui-variant-label">{label}</span>
      <div className="devui-variant-body">{children}</div>
    </div>
  );
}

// ── 상태가 필요한 표본용 래퍼 ────────────────────────────────────────────────

function LiveTabs() {
  const [i, setI] = useState(0);
  return <Tabs tabs={["개요", "재무", "리스크"]} active={i} onChange={setI} />;
}

function LiveToggle({ tone }: { tone?: "buy" | "sell" | "neutral" }) {
  const [on, setOn] = useState(true);
  return <Toggle on={on} onChange={setOn} tone={tone} />;
}

function LiveKSection() {
  const [on, setOn] = useState(true);
  return (
    <KSection title="유동성 게이트" hint="거래대금 하위 20% 제외" enabled={on} onToggle={setOn} tone="buy">
      <KField label="최소 거래대금">
        <span className="devui-inline-note">자식 노드는 enabled 일 때만 렌더된다</span>
      </KField>
    </KSection>
  );
}

function LiveSubToggle() {
  const [on, setOn] = useState(true);
  return (
    <SubToggle label="트레일링 스톱" hint="고점 대비" on={on} onChange={setOn} tone="sell">
      <span className="devui-inline-note">펼쳐진 내용</span>
    </SubToggle>
  );
}

function LiveStepper() {
  const [v, setV] = useState(20);
  return <QuickStepper value={v} onChange={setV} chips={[-5, 5]} unit="%" min={0} max={100} />;
}

function LiveSegmented() {
  const [v, setV] = useState<"eq" | "mc" | "rp">("eq");
  return (
    <Segmented
      value={v}
      onChange={setV}
      tone="buy"
      options={[{ id: "eq", label: "동일가중" }, { id: "mc", label: "시가총액" }, { id: "rp", label: "리스크패리티" }]}
    />
  );
}

function LiveSelect() {
  const [v, setV] = useState("per");
  return (
    <GroupedSelect
      value={v}
      onChange={setV}
      groups={[
        { label: "밸류", options: [{ id: "per", label: "PER" }, { id: "pbr", label: "PBR" }] },
        { label: "퀄리티", options: [{ id: "roe", label: "ROE" }] },
      ]}
    />
  );
}

function LivePSection() {
  return (
    <PSection title="섹션 제목" action={<Badge variant="blue">action 슬롯</Badge>}>
      <span className="devui-inline-note">본문</span>
    </PSection>
  );
}

const SPARK_UP = [10, 12, 11, 14, 13, 17, 19, 18, 22];
const SPARK_DOWN = [22, 20, 21, 17, 15, 16, 12, 11, 9];
const MINIVIZ_KINDS: MiniVizKind[] = ["bars", "line", "heat", "rows", "gauge"];

export default function DevUiPage() {
  return (
    <div className="devui">
      <header className="devui-head">
        <h1 className="devui-title">shared/ui — 프리미티브 격리 갤러리</h1>
        <p className="devui-sub">
          데이터·API 없이 렌더된 표본입니다. 이 페이지는 nav 에 링크되지 않은 내부 라우트이며,
          <code>e2e/dev-ui.spec.ts</code> 가 여기서 클래스 계약을 회귀 검사합니다.
        </p>
        <p className="devui-sub devui-omit">
          shared/ui 의 컴포넌트 export 36개를 빠짐없이 렌더합니다 — 스펙이 이 1:1 대응을 강제합니다.
        </p>
      </header>

      {/* ── shared/ui/primitives ───────────────────────────────────────────── */}
      <section className="devui-group">
        <h2 className="devui-group-title">shared/ui/primitives</h2>

        <Specimen name="PageHeader" from="primitives" note="브레드크럼·부제·actions 슬롯 모두 옵션.">
          <PageHeader
            title="페이지 제목"
            subtitle="부제목 — 옵션"
            breadcrumb={[{ label: "홈", href: "/dashboard" }, { label: "현재 위치" }]}
            actions={<Badge variant="green">actions</Badge>}
          />
        </Specimen>

        <Specimen name="PageContent" from="primitives" note="container-pv 폭 제한 + 상하 패딩만 담당.">
          <PageContent><span className="devui-inline-note">본문 래퍼</span></PageContent>
        </Specimen>

        <Specimen name="StatCard" from="primitives">
          <Variant label="trend=up / size=md"><StatCard label="누적수익률" value="+18.4%" sub="2020-01 ~ 2025-12" trend="up" /></Variant>
          <Variant label="trend=down"><StatCard label="MDD" value="-24.1%" trend="down" /></Variant>
          <Variant label="trend=neutral / size=sm"><StatCard label="거래횟수" value={412} trend="neutral" size="sm" /></Variant>
        </Specimen>

        <Specimen name="Tabs" from="primitives" note="클릭하면 active 가 바뀝니다(상호작용 표본).">
          <LiveTabs />
        </Specimen>

        <Specimen name="Spinner" from="primitives">
          <Variant label="size=16"><Spinner /></Variant>
          <Variant label="size=28"><Spinner size={28} /></Variant>
        </Specimen>

        <Specimen name="Badge" from="primitives">
          <Variant label="4개 variant 전부">
            <span className="devui-row">
              <Badge variant="green">green</Badge>
              <Badge variant="red">red</Badge>
              <Badge variant="amber">amber</Badge>
              <Badge variant="blue">blue</Badge>
            </span>
          </Variant>
        </Specimen>

        <Specimen name="Section" from="primitives" note="kit 의 Section 과 이름만 같고 별개 구현입니다(합치지 않았습니다).">
          <LivePSection />
        </Specimen>

        <Specimen name="FormRow" from="primitives" note="cols 를 Tailwind grid-cols-* 로 매핑합니다.">
          <FormRow cols={3}>
            <PField label="시작일"><input className="bs-numbox" defaultValue="2020-01-01" /></PField>
            <PField label="종료일"><input className="bs-numbox" defaultValue="2025-12-31" /></PField>
            <PField label="수수료" hint="bps"><input className="bs-numbox" defaultValue="15" /></PField>
          </FormRow>
        </Specimen>

        <Specimen name="Field" from="primitives" note="kit 의 Field 와 이름만 같고 별개 구현입니다.">
          <Variant label="hint 있음"><PField label="라벨" hint="힌트 문구"><input className="bs-numbox" defaultValue="42" /></PField></Variant>
          <Variant label="hint 없음"><PField label="라벨만"><input className="bs-numbox" defaultValue="7" /></PField></Variant>
        </Specimen>

        <Specimen name="ErrorMsg" from="primitives">
          <ErrorMsg msg="종목 조회에 실패했습니다 (HTTP 500)" />
        </Specimen>

        <Specimen name="Empty" from="primitives">
          <Variant label="기본 문구"><Empty /></Variant>
          <Variant label="문구 지정"><Empty msg="조건에 맞는 종목이 없습니다" /></Variant>
        </Specimen>
      </section>

      {/* ── shared/ui/kit ──────────────────────────────────────────────────── */}
      <section className="devui-group">
        <h2 className="devui-group-title">shared/ui/kit</h2>
        <p className="devui-group-note">
          kit 은 전부 인라인 스타일입니다 — <code>.bs-numbox</code> 외에 클래스 계약이 없습니다.
          그래서 스펙은 클래스가 아니라 role·태그 구조(<code>[role=switch]</code>, <code>optgroup</code>)로 검증합니다.
        </p>

        <Specimen name="GroupedSelect" from="kit" note="optgroup 으로 묶인 native select."><LiveSelect /></Specimen>

        <Specimen name="Toggle" from="kit" note="role=switch + aria-checked. tone 이 켜진 색을 결정.">
          <Variant label="tone=buy"><LiveToggle tone="buy" /></Variant>
          <Variant label="tone=sell"><LiveToggle tone="sell" /></Variant>
          <Variant label="tone=neutral"><LiveToggle tone="neutral" /></Variant>
        </Specimen>

        <Specimen name="Section" from="kit" note="on/off 카드. 토글을 끄면 자식이 사라집니다."><LiveKSection /></Specimen>
        <Specimen name="SubToggle" from="kit"><LiveSubToggle /></Specimen>
        <Specimen name="Field" from="kit" note="라벨 폭 고정형 가로 행."><KField label="보유기간"><span className="devui-inline-note">자식</span></KField></Specimen>
        <Specimen name="QuickStepper" from="kit" note="숫자 입력 + 증감 칩. min/max 로 clamp."><LiveStepper /></Specimen>
        <Specimen name="Segmented" from="kit"><LiveSegmented /></Specimen>
      </section>

      {/* ── shared/ui/States ───────────────────────────────────────────────── */}
      <section className="devui-group">
        <h2 className="devui-group-title">shared/ui/States</h2>
        <p className="devui-group-note">
          6개 화면 공용 로딩/빈/오류 상태. <code>.tstate-*</code> 가 클래스 계약입니다.
        </p>

        <Specimen name="LoadingState" from="States">
          <Variant label="기본"><LoadingState /></Variant>
          <Variant label="label + sub"><LoadingState label="백테스트 실행 중" sub="1,024 종목 / 6년" /></Variant>
        </Specimen>
        <Specimen name="EmptyState" from="States">
          <Variant label="기본"><EmptyState /></Variant>
          <Variant label="label + sub"><EmptyState label="결과 없음" sub="필터를 완화해 보세요" /></Variant>
        </Specimen>
        <Specimen name="ErrorState" from="States">
          <Variant label="기본"><ErrorState /></Variant>
          <Variant label="label + sub"><ErrorState label="조회 실패" sub="HTTP 500 — 백엔드 로그를 확인하세요" /></Variant>
        </Specimen>
        <Specimen name="UnavailableState" from="States"
          note="빈 상태(0건)와 다른 사실입니다 — 사유가 필수 prop 입니다.">
          <Variant label="사유 필수"><UnavailableState reason="빈티지 이력이 없어 과거 시점의 값을 재구성할 수 없습니다." /></Variant>
          <Variant label="label 지정"><UnavailableState label="Brinson 분해 불가" reason="벤치마크 구성종목 시계열이 없습니다." /></Variant>
        </Specimen>
        <Specimen name="AsyncState" from="States"
          note="네 갈래를 한 곳에서. unavailable 만 reason 이 필수라 tsc 가 정직함을 강제합니다.">
          <Variant label="loading"><AsyncState status={{ kind: "loading", label: "최적화 중" }} /></Variant>
          <Variant label="empty"><AsyncState status={{ kind: "empty", label: "해당 종목 없음" }} /></Variant>
          <Variant label="unavailable"><AsyncState status={{ kind: "unavailable", reason: "이 팩터는 데이터 소스가 없습니다." }} /></Variant>
          <Variant label="ready"><AsyncState status={{ kind: "ready" }}><span className="num">12.3%</span></AsyncState></Variant>
        </Specimen>
      </section>

      {/* ── shared/ui/evidence ─────────────────────────────────────────────── */}
      <section className="devui-group">
        <h2 className="devui-group-title">shared/ui/evidence</h2>
        <p className="devui-group-note">
          증거 상태의 <b>시각 처리</b> 단일 출처. 의미(DataStatus·ResearchUsage·Basis)는
          정의하지 않습니다 — 그 매핑은 열거형을 아는 계층이 합니다(FSD 상 shared 는
          entities 를 import 할 수 없습니다). <code>.tev-*</code> 가 클래스 계약입니다.
        </p>

        <Specimen name="EvidenceBadge" from="evidence"
          note="caution·unavailable 은 reason 이 필수. 사유는 title= 이 아니라 보이는 텍스트로 나갑니다.">
          <Variant label="measured"><EvidenceBadge kind="measured">실측</EvidenceBadge></Variant>
          <Variant label="estimated"><EvidenceBadge kind="estimated" reason="합성(mock) 시세로 계산됨">추정</EvidenceBadge></Variant>
          <Variant label="caution"><EvidenceBadge kind="caution" reason="입력이 바뀌었지만 아직 재계산되지 않았습니다.">주의</EvidenceBadge></Variant>
          <Variant label="unavailable"><EvidenceBadge kind="unavailable" reason="데이터 출처가 없습니다.">없음</EvidenceBadge></Variant>
        </Specimen>

        <Specimen name="EvidenceDrawer" from="EvidenceDrawer"
          note="정상 상태의 부연만 담습니다. 경고는 닫힌 서랍 안에서 존재하지 않는 것과 같으므로 넣지 않습니다. Radix Popover — 내용은 document.body 로 포털됩니다.">
          <EvidenceDrawer title="재현 좌표" rows={[
            { label: "스냅샷", value: "rgs_20260601_a91f", mono: true, note: "이 국면 판정의 기준시점 — 값은 고정되어 있습니다." },
            { label: "룰셋", value: "tr_momentum v4", mono: true },
            { label: "엔진", value: "dev", mono: true, note: "서버가 스탬프한 코드 버전." },
          ]} />
        </Specimen>
      </section>

      {/* ── shared/ui/feedback ─────────────────────────────────────────────── */}
      <section className="devui-group">
        <h2 className="devui-group-title">shared/ui/feedback</h2>

        <Specimen name="Skeleton" from="feedback" note=".skeleton 이 클래스 계약. 높이·폭은 호출자가 지정.">
          <Skeleton className="h-3" style={{ width: "60%" }} />
        </Specimen>
        <Specimen name="SkeletonText" from="feedback">
          <Variant label="lines=3 (기본)"><SkeletonText /></Variant>
          <Variant label="lines=5"><SkeletonText lines={5} /></Variant>
        </Specimen>
        <Specimen name="SkeletonCard" from="feedback"><SkeletonCard /></Specimen>
        <Specimen name="SkeletonTable" from="feedback">
          <Variant label="rows=3"><SkeletonTable rows={3} /></Variant>
        </Specimen>

        <Specimen name="TickValue" from="feedback" note="값이 바뀌면 0.6초 flash. 여기서는 정적 표본.">
          <Variant label="number"><TickValue value={1234.5678} /></Variant>
          <Variant label="currency"><TickValue value={98_450_000} format="currency" /></Variant>
          <Variant label="percent"><TickValue value={12.345} format="percent" /></Variant>
          <Variant label="null → 대시"><TickValue value={null} /></Variant>
        </Specimen>

        <Specimen name="MetricCard" from="feedback" note="loading=true 면 SkeletonCard 로 대체됩니다.">
          <Variant label="delta 양수 + icon"><MetricCard label="샤프" value={1.42} delta={3.1} sublabel="전월 대비" icon={Activity} /></Variant>
          <Variant label="delta 음수"><MetricCard label="변동성" value={18.7} unit="%" delta={-2.4} color="#dc2626" /></Variant>
          <Variant label="value=null"><MetricCard label="미집계" value={null} /></Variant>
          <Variant label="loading=true"><MetricCard label="로딩" value={0} loading /></Variant>
        </Specimen>

        <Specimen name="Sparkline" from="feedback" note="data.length < 2 면 같은 크기의 빈 span 을 반환합니다.">
          <Variant label="상승"><Sparkline data={SPARK_UP} color="auto" /></Variant>
          <Variant label="하락"><Sparkline data={SPARK_DOWN} color="auto" /></Variant>
          <Variant label="데이터 1개 → 빈 자리"><Sparkline data={[1]} /></Variant>
        </Specimen>
      </section>

      {/* ── shared/ui/MiniViz + SectionHead ────────────────────────────────── */}
      <section className="devui-group">
        <h2 className="devui-group-title">shared/ui/MiniViz · SectionHead</h2>

        <Specimen name="MiniViz" from="MiniViz" note="kind 5종. 데이터를 받지 않는 순수 플레이스홀더 그래픽입니다.">
          {MINIVIZ_KINDS.map((k) => (
            <Variant key={k} label={`kind=${k}`}><MiniViz kind={k} /></Variant>
          ))}
        </Specimen>

        <Specimen name="StatGrid" from="MiniViz" note="Stat 들을 담는 그리드(.tstat-grid).">
          <StatGrid>
            <Stat k="CAGR" v="14.2%" sub="2020~2025" />
            <Stat k="MDD" v="-24.1%" sub="2022-09" />
            <Stat k="샤프" v="1.42" />
          </StatGrid>
        </Specimen>

        <Specimen name="Stat" from="MiniViz" note="valueColor 는 값 텍스트에만 적용됩니다.">
          <Variant label="valueColor 없음"><Stat k="거래횟수" v={412} /></Variant>
          <Variant label="valueColor 지정"><Stat k="승률" v="58.3%" sub="412건 중" valueColor="var(--color-bull)" /></Variant>
        </Specimen>

        <Specimen name="SectionHead" from="SectionHead" note="default export. index 는 옵션.">
          <Variant label="index 있음"><SectionHead label="유동성 게이트" index="01" /></Variant>
          <Variant label="index 없음"><SectionHead label="후처리" /></Variant>
        </Specimen>
      </section>

      {/* ── S1: Card 표본 + 다크 토큰 확인 ────────────────────────────────────
          ★다크 토큰이 '정의만 되고 아무도 안 쓰는' 상태가 되지 않게 하는 자리다★
          globals.css §47 은 .dark 에서 --card/--border/--foreground 를 덮는다. 그런데
          그 값을 실제로 그리는 화면이 없으면 오타 하나로 죽어도 아무도 모른다.
          여기 토글이 그 유일한 소비처다 — 다크는 아직 이 표면에서만 검증된다. */}
      <section className="devui-group devui-s1">
        <h2 className="devui-h">Card (S1a) · 다크 토큰 (S1f)</h2>
        <p className="devui-note">
          상류 기본값 p-6 대신 CardContent=p-3 · CardHeader=px-3 py-2 로 정의했다.
          소비처마다 덮지 않는 이유는 CSS 특이도 충돌(KNOWN_COLLISIONS 22건)이 전부 그 유형이기 때문.
        </p>
        <button
          className="devui-darktoggle"
          onClick={() => document.documentElement.classList.toggle("dark")}
        >
          다크 토글 (.dark 클래스)
        </button>
        <div className="devui-s1grid">
          <Card className="devui-s1card">
            <CardHeader>
              <CardTitle>백테스트 요약</CardTitle>
              <CardDescription>고밀도 기본값 · 지표 화면용</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="devui-s1row"><span>CAGR</span><b className="num">+5.8%</b></div>
              <div className="devui-s1row"><span>Sharpe</span><b className="num">0.72</b></div>
              <div className="devui-s1row"><span>MDD</span><b className="num">-14.2%</b></div>
            </CardContent>
          </Card>
          <Card className="devui-s1card">
            <CardHeader><CardTitle>산출 불가 처리</CardTitle></CardHeader>
            <CardContent>
              {/* 값 노드를 만들지 않는다 — 0 이나 — 을 적으면 측정값처럼 읽힌다. */}
              <div className="devui-s1row"><span>정보비율(IR)</span>
                <span className="brun-kpi-nabadge">산출 불가</span></div>
              <p className="devui-s1why">벤치마크를 지정하지 않아 추적오차를 계산할 수 없습니다.</p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* ── shadcn/ui 벤더링본 (Phase 5 스캐폴드) ─────────────────────────────
          ★위 갤러리와 클래스를 공유하지 않는다★
          e2e/dev-ui.spec.ts 는 .devui-item 개수 === SPECIMENS.length(32) 를 단언하고
          이름 목록까지 대조한다. shadcn 표본을 같은 클래스로 넣으면 그 계약이 깨진다.
          그래서 .devui-shadcn / .devui-sitem 이라는 **별개 클래스**를 쓴다 —
          기존 단언은 그대로 유효하고, 새 섹션은 자체 단언으로 검증한다.

          이 컴포넌트들은 shared/ui/index.ts 에 **재수출하지 않는다**. 갤러리가 지켜 온
          "shared/ui 배럴 export ↔ 표본 1:1" 관례도 그대로 유지된다.

          Dialog 가 여기 있는 이유: Radix 는 document.body 로 포털하므로 .devui 로 스코프한
          단언이 내용을 놓친다. Phase 6 모달 통합 전에 그 사실을 지금 노출해 둔다. */}
      <section className="devui-shadcn">
        <h2 className="devui-group-title">shared/ui/shadcn — Tailwind + Radix (Phase 5)</h2>
        <p className="devui-sub">
          토큰은 globals.css §34 브릿지로 기존 <code>--t-*</code> 를 참조합니다(팔레트 복제 없음).
          CLI 가 이 환경에서 차단되어 shadcn 공개 구조를 그대로 손으로 작성했습니다.
        </p>

        <div className="devui-sitem">
          <code className="devui-sitem-name">Button</code>
          <div className="devui-variants">
            {(["default", "secondary", "outline", "ghost", "destructive", "link"] as const).map((v) => (
              <Button key={v} variant={v}>{v}</Button>
            ))}
            <Button size="sm">sm</Button>
            <Button size="lg">lg</Button>
            <Button disabled>disabled</Button>
          </div>
        </div>

        <div className="devui-sitem">
          <code className="devui-sitem-name">Badge</code>
          <div className="devui-variants">
            {(["default", "secondary", "outline", "destructive"] as const).map((v) => (
              <ShadBadge key={v} variant={v}>{v}</ShadBadge>
            ))}
          </div>
        </div>

        <div className="devui-sitem">
          <code className="devui-sitem-name">Dialog</code>
          <div className="devui-variants">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline" className="devui-dialog-open">Dialog 열기</Button>
              </DialogTrigger>
              <DialogContent className="devui-dialog-content">
                <DialogHeader>
                  <DialogTitle>포털 확인용 다이얼로그</DialogTitle>
                  <DialogDescription>
                    이 내용은 document.body 로 포털됩니다 — .devui 로 스코프한 셀렉터에는 잡히지 않습니다.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose asChild><Button variant="secondary">닫기</Button></DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </section>
    </div>
  );
}
