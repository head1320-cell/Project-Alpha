"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// /dev/ui — shared/ui 부품 격리 갤러리
//
// 목적: 제품이 쓰는 shared/ui 부품(kit · States · evidence · tx)과 서식 함수 · 단과 밀도 토큰을 데이터 없이 한 화면에서 그린다.
//   · 에이전트가 "이 부품이 어떻게 생겼나"를 알려고 소비 화면을 뒤지지 않아도 된다.
//   · Playwright(e2e/dev-ui.spec.ts · e2e/density.spec.ts)가 여기서 **클래스 계약과 동작을 회귀 검사**한다.
//
// ★제품이 쓰지 않는 부품은 여기에 두지 않는다(U0-e · ADR 007 결정 D7)★ — primitives · feedback · MiniViz · SectionHead ·
// AllocationMap · EvidenceDrawer 와 shadcn 의 Button · Input · Slider · Progress · Table · Popover 는 가져다 쓰는 제품 파일이
// 하나도 없어 부품 · 표본 · 그 CSS 를 함께 걷었다. 카탈로그에만 사는 부품은 '있는 것처럼 보이는 부채'다.
//
// Storybook 을 쓰지 않은 이유: 패키지 40~60개와 두 번째 빌드 파이프라인이 붙는다. 이 라우트는
// 앱 자체의 빌드/CSS/E2E 를 그대로 쓴다 — 새 의존성 0개.
//
// 갤러리 자체는 네트워크 호출 0(모든 표본이 하드코딩 props). 셸(TerminalShell) 머리 줄의 프로필은
// 로그인 토큰이 있을 때만 /auth/me 를 한 번 부른다(토큰이 없으면 0).
// nav 에 링크되지 않은 내부 라우트다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useState } from "react";

import {
  GroupedSelect, Toggle, Section as KSection, SubToggle,
  Field as KField, QuickStepper, Segmented,
} from "@/shared/ui/kit";
import { LoadingState, EmptyState, ErrorState, UnavailableState, AsyncState } from "@/shared/ui/States";
import { EvidenceBadge } from "@/shared/ui/evidence";
// shadcn 벤더링본 — .devui-item 계약을 건드리지 않도록 **별도 섹션**에서만 쓴다(아래 주석 참조).
import { Badge as ShadBadge } from "@/shared/ui/shadcn/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/shared/ui/shadcn/card";
import {
  Dialog, DialogTrigger, DialogContent, DialogHeader,
  DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from "@/shared/ui/shadcn/dialog";
// §68 롱숏 표본 — 숏이 든 비중을 화면 경로로 만들 UI 가 없어 여기서만 잴 수 있다(집중도 · 노출 네 축의 식).
import { concentration, exposureLegs } from "@/shared/lib/exposure";
// BU0 — 토스식 공용 부품 + 한국식 숫자 표기. 서식 표의 출력은 실제 함수의 반환값이다(손으로 적지 않는다).
import * as Tx from "@/shared/ui/tx";
import { clockText, direction, krUnit, num, pct, pp, priceWon, signedPct, won } from "@/shared/lib/krFormat";
// U0(ADR 007) — 단 · 밀도 견본. 제품 부품이 아니라 토큰이 뜻대로 도는지 보는 자리다(e2e/density.spec.ts).
import { DensitySpecimen } from "../DensitySpecimen";
import { TableSpecimen } from "../TableSpecimen";
import { ProvenanceSpecimen } from "../ProvenanceSpecimen";

// ── 갤러리 프레임 ────────────────────────────────────────────────────────────
// 페이지 자체 크롬은 .devui-* 만 쓴다. 앱 클래스(.pv-* 등)는 표본 안에서만 나타나야
// 하므로(그래야 스펙이 표본 수를 셀 수 있다) 여기서는 쓰지 않는다.

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

const LS_ITEMS = [
  { code: "005930", name: "삼성전자", weight: 60 },
  { code: "000660", name: "SK하이닉스", weight: 50 },
  { code: "035420", name: "NAVER", weight: 30 },
  { code: "051910", name: "LG화학", weight: -25 },
  { code: "005380", name: "현대차", weight: -15 },
];
function LiveTxSegmented() {
  const [v, setV] = useState<"kr" | "us">("kr");
  return <Tx.Segmented label="시장" options={[{ value: "kr", label: "한국" }, { value: "us", label: "미국" }]} value={v} onChange={setV} />;
}

function LiveTxTabs() {
  const [v, setV] = useState<"a" | "b" | "c">("a");
  return (
    <Tx.Tabs label="표본 탭" tabs={[{ value: "a", label: "개요" }, { value: "b", label: "지표" }, { value: "c", label: "국면" }]} value={v} onChange={setV}>
      <span className="devui-tx-panel">{v} 패널</span>
    </Tx.Tabs>
  );
}

/** 서식 표 — [함수 이름, 입력 표기, 실제 출력]. 출력은 함수가 낸 그대로. */
const KR_FMT: [string, string, string][] = [
  ["num", "1234.5", num(1234.5)], ["num", "1234.5, 1", num(1234.5, 1)], ["num", "-0.0001", num(-0.0001)],
  ["krUnit", "3.4e11", krUnit(3.4e11)], ["krUnit", "1.234e12", krUnit(1.234e12)], ["krUnit", "9.9996e11", krUnit(9.9996e11)],
  ["krUnit", "99995000", krUnit(99_995_000)], ["krUnit", "56000000", krUnit(56_000_000)], ["krUnit", "9999.6", krUnit(9999.6)],
  ["krUnit", "-2.5e8", krUnit(-2.5e8)], ["won", "1234", won(1234)], ["won", "3.4e11", won(3.4e11)],
  ["pct", "0.241", pct(0.241)], ["pct", "-0.03", pct(-0.03)], ["signedPct", "0.241", signedPct(0.241)],
  ["signedPct", "0", signedPct(0)], ["signedPct", "-0.00004", signedPct(-0.00004)], ["pp", "0.021", pp(0.021)],
  ["pp", "-0.03", pp(-0.03)], ["num", "null", num(null)], ["pct", "NaN", pct(NaN)], ["won", "Infinity", won(Infinity)],
  ["priceWon", "71200", priceWon(71_200)], ["priceWon", "undefined", priceWon(undefined)],
  ["direction", "0.1", direction(0.1)], ["direction", "-1", direction(-1)], ["direction", "0", direction(0)], ["direction", "null", direction(null)],
  // U2 · 이 기기 시각 — 이 기기 시각의 칸으로 만든 값이라 시간대와 무관하다. 받은 적이 없으면 null(사유는 부르는 쪽이 붙인다).
  ["clockText", "new Date(2026, 10, 21, 9, 30, 5)", String(clockText(new Date(2026, 10, 21, 9, 30, 5).getTime()))], ["clockText", "0", String(clockText(0))],
];

const LO_CONC = concentration([40, 30, 20, 10]);
const LS_CONC = concentration(LS_ITEMS.map((x) => x.weight));
const LS_LEGS = exposureLegs(LS_ITEMS.map((x) => x.weight));

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
          제품이 쓰는 shared/ui 부품의 표본 23개를 렌더합니다. 스펙이 표본의 이름과 수를 강제합니다.
        </p>
      </header>

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
          <Variant label="label + sub"><EmptyState label="결과 없음" sub="필터를 완화하십시오" /></Variant>
        </Specimen>
        <Specimen name="ErrorState" from="States">
          <Variant label="기본"><ErrorState /></Variant>
          <Variant label="label + sub"><ErrorState label="조회 실패" sub="HTTP 500 — 백엔드 로그를 확인하십시오" /></Variant>
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

      </section>

      {/* ── shared/ui/tx (BU0) — 토스식 공용 부품. 평범한 props 만 받는다(서버 응답을 문장으로 바꾸는 일은 위젯이 한다). ── */}
      <section className="devui-group devui-tx">
        <h2 className="devui-group-title">shared/ui/tx — 토스식 공용 부품 (BU0)</h2>
        <p className="devui-group-note">
          ADR-003. 답 문장은 서버 값으로만 만든다 — 아래 문장은 모양을 보이는 표본이다. 클래스 <code>.tx-*</code> 가 계약.
        </p>
        <Specimen name="PageHead" from="tx"><Tx.PageHead title="매크로 분석" lede="경기·물가 국면의 방향을 분석합니다." /></Specimen>
        <Specimen name="Answer" from="tx" note="문장 + 숫자 1~3 + 근거 칩 + 다음 행동 하나.">
          <Tx.Answer sentence="(표본) 서버가 준 값을 끼운 한 문장이 여기에 옵니다."
            figures={[{ label: "스트레스", value: "52/100" }, { label: "확률", value: pct(0.54, 0) }]}
            chips={[{ label: "합성 데이터", tone: "practice" }, { label: "가정 2개", tone: "assumed" }, { label: "미측정 항목 1가지", tone: "unmeasured" }]}
            action={<button type="button" className="devui-tx-act">매크로 분석 보기</button>} />
        </Specimen>
        <Specimen name="Chips" from="tx">
          <Tx.Chips items={[{ label: "합성 데이터", tone: "practice" }, { label: "가정 1개", tone: "assumed" }, { label: "N/A 1개", tone: "unknown" },
                            { label: "미측정 항목", tone: "unmeasured" }, { label: "정상", tone: "ok" }, { label: "안내", tone: "info" }]} />
        </Specimen>
        <Specimen name="Section" from="tx">
          <Tx.Section title="작업 선택" sub="한 절은 한 가지 일만 합니다.">
            <Tx.ListRow title="종목 찾기" sub="조건식으로 종목을 선별합니다" href="/screener" />
          </Tx.Section>
        </Specimen>
        <Specimen name="ListRow" from="tx" note="href → 링크 · onClick → 단추 · 둘 다 없으면 누를 수 없는 줄(화살표 없음).">
          <Variant label="링크"><Tx.ListRow title="삼성전자" sub="005930" right={won(71_200)} href="/insights?code=005930" /></Variant>
          <Variant label="단추"><Tx.ListRow title="상세 보기" onClick={() => {}} /></Variant>
          <Variant label="그냥 줄"><Tx.ListRow title="적재 행 수" right={num(1_234_567)} /></Variant>
        </Specimen>
        <Specimen name="Stat" from="tx" note="등락은 색 + ▲▼ + 글자. 미상은 'N/A'(평평함과 다르다).">
          <Variant label="오름"><Tx.Stat label="연환산 수익률" value={signedPct(0.241)} delta={{ text: pp(0.021), dir: direction(0.021) }} /></Variant>
          <Variant label="내림"><Tx.Stat label="최대 낙폭" value={pct(-0.18)} delta={{ text: pp(-0.03), dir: direction(-0.03) }} /></Variant>
          <Variant label="그대로"><Tx.Stat label="변동성" value={pct(0.12)} delta={{ text: pp(0), dir: direction(0) }} /></Variant>
          <Variant label="모름"><Tx.Stat label="베타" value={<Tx.Unknown reason="벤치마크 시계열 없음" />} delta={{ text: pp(null), dir: direction(null) }} /></Variant>
        </Specimen>
        <Specimen name="Segmented" from="tx" note="radiogroup · 화살표·Home·End."><LiveTxSegmented /></Specimen>
        <Specimen name="Tabs" from="tx" note="tablist · 로빙 tabindex · 화살표로 옮기면 바로 고른다."><LiveTxTabs /></Specimen>
        <Specimen name="Notice" from="tx">
          <Variant label="practice"><Tx.Notice tone="practice" title="합성 데이터입니다">실제 시장 값이 아니라 합성 값으로 계산했습니다.</Tx.Notice></Variant>
          <Variant label="warn"><Tx.Notice tone="warn" title="가정이 들어 있습니다" /></Variant>
          <Variant label="danger"><Tx.Notice tone="danger" title="조회 실패">서버 연결 실패. 잠시 후 재시도하십시오.</Tx.Notice></Variant>
        </Specimen>
        <Specimen name="Unknown" from="tx" note="사유가 필수다(타입). 0 이나 빈칸으로 그리지 않는다.">
          <Tx.Unknown reason="재무 데이터가 아직 적재되지 않았습니다" />
        </Specimen>
      </section>

      {/* ── shared/lib/krFormat (BU0) — 한국식 숫자 표기. 출력 칸은 실제 함수 값이다. ── */}
      <section className="devui-group devui-krfmt">
        <h2 className="devui-h">shared/lib/krFormat — 한국식 숫자 표기</h2>
        <table className="devui-krfmt-table">
          <tbody>
            {KR_FMT.map(([fn, input, out], i) => (
              <tr key={i} data-fn={fn} data-in={input}><td>{fn}({input})</td><td className="devui-krfmt-out">{out}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* ── U0 · 단 · 밀도 견본 (ADR 007) ─────────────────────────────────────────
          상자마다 `data-tier` · `data-density` 를 직접 달았다 — 토큰 블록의 선택자가 속성만이라 `html` 이 아니어도 걸린다.
          다크 상자는 `dark` 클래스를 상자에 달았다(개발 화면은 늘 라이트 — 상자 안에서만 다크 토큰이 선다).
          `.devui-item` 을 쓰지 않는다 — 그 수는 shared/ui 부품 표본과 1:1 인 계약이다(dev-ui.spec). */}
      <section className="devui-group devui-dn" id="density">
        <h2 className="devui-h">단 · 밀도 (ADR 007 · U0)</h2>
        <p className="devui-note">
          밀도는 줄 높이 · 칸 여백 · 글자 · 조작 높이 · 절 간격을 함께 바꿉니다. 단은 절과 행의 반경을 정하고, 단 안의 수는 본문 글꼴의 고정폭 숫자입니다.
          강조(주 단추 · 초점 고리)는 잉크이고 파랑은 하락과 링크에만 남습니다. 제품 화면은 종목 찾기가 처음 올랐습니다(작업 단).
        </p>
        <h3 className="devui-dn-h">작업 단 · 밀도 셋</h3>
        <div className="devui-dn-grid">
          <DensitySpecimen tier="work" density="compact" />
          <DensitySpecimen tier="work" density="regular" />
          <DensitySpecimen tier="work" density="comfortable" />
        </div>
        <h3 className="devui-dn-h">작업 단 · 밀도 셋(다크)</h3>
        <div className="devui-dn-grid">
          <DensitySpecimen tier="work" density="compact" dark />
          <DensitySpecimen tier="work" density="regular" dark />
          <DensitySpecimen tier="work" density="comfortable" dark />
        </div>
        <h3 className="devui-dn-h">해석 단 · 설명 단 · 속성 없음</h3>
        <div className="devui-dn-grid">
          <DensitySpecimen tier="read" density="regular" />
          <DensitySpecimen tier="present" density="comfortable" />
          <DensitySpecimen bare caption="속성 없음(지금 화면과 같은 기본값)" />
        </div>
        <p className="devui-note">
          단 밖의 수는 지금 그대로입니다: <span className="num devui-dn-out">1,234.5</span>
        </p>
      </section>

      {/* ── U1 · 공용 표 견본 (shared/ui/table) ─────────────────────────────────────
          제품(종목 찾기)이 쓰는 표 부품을 밀도 셋 · 두 테마에서 본다. 상자마다 `data-tier` · `data-density` 를 직접 달았다.
          `.devui-item` 을 쓰지 않는다 — 그 수는 shared/ui 부품 표본과 1:1 인 계약이다(dev-ui.spec). 스펙: `e2e/data-table.spec.ts`. */}
      <section className="devui-group devui-tb" id="table">
        <h2 className="devui-h">공용 표 (shared/ui/table · U1)</h2>
        <p className="devui-note">
          줄 높이 · 칸 여백 · 글자는 밀도 토큰에서 옵니다. 값이 없는 칸은 N/A 이고 정렬하면 어느 방향에서도 끝에 섭니다.
          줄 하나만 탭 순서에 있고 화살표 키로 줄을 옮깁니다. 견본의 값은 손으로 적은 합성 값입니다.
        </p>
        <div className="devui-tb-grid">
          <TableSpecimen tier="work" density="compact" />
          <TableSpecimen tier="work" density="regular" />
          <TableSpecimen tier="work" density="comfortable" />
          <TableSpecimen tier="work" density="compact" dark />
          <TableSpecimen />
        </div>
      </section>

      {/* ── U2 · 출처 표지 · 갱신 시각 (shared/ui/provenance) ─────────────────────────
          출처 → 시각들 → 시점 정합 → 덧붙임의 차례로 칩을 세우고, 주기 조회 화면의 '마지막 수신' 줄을 그린다. 상자마다 `data-tier` · `data-density` 를 직접 달았다.
          `.devui-item` 을 쓰지 않는다 — 그 수는 shared/ui 부품 표본과 1:1 인 계약이다(dev-ui.spec). 스펙: `e2e/provenance.spec.ts` · `e2e/provenance-logic.spec.ts`. */}
      <section className="devui-group devui-pv" id="provenance">
        {/* 390 에서 '(shared/ui/provenance' 한 덩어리가 절보다 넓다 — 줄을 바꿀 자리를 준다(글자 · CSS 그대로). */}
        <h2 className="devui-h">출처 표지 · 갱신 시각 (shared/ui/<wbr />provenance · U2)</h2>
        <p className="devui-note">
          출처 · 시각 · 시점 정합을 칩 하나에 하나씩 적고 차례는 늘 같습니다. 합성은 경고색과 낱말로 적고 어떤 밀도에서도 숨기지 않습니다.
          모르는 값은 N/A 와 사유입니다. 갱신 시각 줄은 마지막으로 받은 때를 이 기기 시각으로 적고, 값이 바뀌어도 화면 낭독기가 끼어들어 읽지 않습니다.
          견본의 값은 손으로 적은 합성 값입니다.
        </p>
        <div className="devui-pv-grid">
          <ProvenanceSpecimen tier="work" density="compact" />
          <ProvenanceSpecimen tier="work" density="regular" />
          <ProvenanceSpecimen tier="work" density="comfortable" />
          <ProvenanceSpecimen tier="work" density="compact" dark />
          <ProvenanceSpecimen tier="work" density="regular" dark />
          <ProvenanceSpecimen tier="work" density="comfortable" dark />
          <ProvenanceSpecimen />
        </div>
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
          {/* asChild (A2a) — 카드 전체가 클릭 대상일 때. DOM 노드가 진짜 <button> 이라
              탭으로 닿고 Enter/Space 가 그냥 동작한다(div+onClick 은 둘 다 안 된다). */}
          <Card asChild className="devui-s1card devui-s1btn">
            <button type="button" onClick={() => {}}>
              <CardHeader><CardTitle as="h3">asChild — 카드 전체가 버튼</CardTitle></CardHeader>
              <CardContent>
                <p className="devui-s1why">Slot 으로 클래스를 자식에게 넘긴다. 탭 스톱 1개.</p>
              </CardContent>
            </button>
          </Card>
        </div>

      </section>

      {/* ── shadcn/ui 벤더링본 (Phase 5 스캐폴드) ─────────────────────────────
          ★위 갤러리와 클래스를 공유하지 않는다★
          e2e/dev-ui.spec.ts 는 .devui-item 개수 === SPECIMENS.length 를 단언하고
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
                <button type="button" className="devui-btn devui-dialog-open">Dialog 열기</button>
              </DialogTrigger>
              <DialogContent className="devui-dialog-content">
                <DialogHeader>
                  <DialogTitle>포털 확인용 다이얼로그</DialogTitle>
                  <DialogDescription>
                    이 내용은 document.body 로 포털됩니다 — .devui 로 스코프한 셀렉터에는 잡히지 않습니다.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose asChild><button type="button" className="devui-btn">닫기</button></DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════════
          §68 롱숏 표본 (P3) — 숏이 있는 비중을 화면 경로로 만들 UI 가 없어서,
          `concentration()`·`exposureLegs()` 가 숏을 어떻게 다루는지
          잴 곳이 여기밖에 없다. 격리 라우트에 표본을 두고 E2E 가 그것을 읽는
          방식은 이 저장소가 Step 3b 에서 세운 관례다.
          ★값을 손으로 적지 않는다★ 아래 숫자는 전부 실제 함수의 반환값이다.
          ═══════════════════════════════════════════════════════════════════ */}
      <section className="devui-group devui-ls">
        <h2 className="devui-h">§68 롱숏 — concentration / exposureLegs</h2>

        <div className="devui-row">
          <span className="devui-lbl">롱온리 [40, 30, 20, 10]</span>
          <span className="devui-ls-basis" data-case="long-only">{LO_CONC.basis}</span>
          <span className="devui-ls-hhi" data-case="long-only">{LO_CONC.hhi.toFixed(1)}</span>
        </div>

        <div className="devui-row">
          <span className="devui-lbl">롱숏 [60, 50, 30, -25, -15]</span>
          <span className="devui-ls-basis" data-case="long-short">{LS_CONC.basis}</span>
          <span className="devui-ls-hhi" data-case="long-short">{LS_CONC.hhi.toFixed(1)}</span>
        </div>

        {/* ★이 줄이 F3 의 증거다★ 예전 `Math.max(w,0)` 식이면 분모가 140 이라
            HHI 가 더 크게(=더 집중된 것처럼) 나온다. gross 180 으로 재야 옳다. */}
        <div className="devui-row">
          <span className="devui-lbl">롱숏 노출</span>
          <span className="devui-ls-legs">
            gross {LS_LEGS.gross.toFixed(1)} / net {LS_LEGS.net.toFixed(1)} /
            long {LS_LEGS.long.toFixed(1)} / short {LS_LEGS.short.toFixed(1)}
          </span>
        </div>
      </section>
    </div>
  );
}
