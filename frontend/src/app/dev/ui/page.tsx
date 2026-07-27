"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// /dev/ui — shared/ui 프리미티브 격리 갤러리
//
// 목적: shared/ui 의 컴포넌트 export **32개 전부**를 데이터 없이 한 화면에서 렌더한다.
//   · 에이전트가 "이 프리미티브가 어떻게 생겼나"를 알려고 소비 화면을 뒤지지 않아도 된다.
//   · Playwright(e2e/dev-ui.spec.ts)가 여기서 **클래스 계약을 회귀 검사**한다.
//     프리미티브가 내보내는 클래스명(.pv-* · .tstate-* · .tstat-* · .skeleton …)이
//     E2E 계약인데, 지금까지 그것을 직접 검증하는 테스트가 없었다.
//
// Storybook 을 쓰지 않은 이유: 패키지 40~60개와 두 번째 빌드 파이프라인이 붙고,
// "순수 CSS 유지 · UI 프레임워크 이전 금지"(CLAUDE.md) 와 충돌한다. 이 라우트는
// 앱 자체의 빌드/CSS/E2E 를 그대로 쓴다 — 새 의존성 0개.
//
// 네트워크 호출 0. nav 에 링크되지 않은 내부 라우트다.
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
import { LoadingState, EmptyState, ErrorState } from "@/shared/ui/States";
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
          shared/ui 의 컴포넌트 export 32개를 빠짐없이 렌더합니다 — 스펙이 이 1:1 대응을 강제합니다.
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
    </div>
  );
}
