/**
 * Landing — 루트(/). **모듈 갤러리 + 근거 밴드** (L1 재작성 → L2 확장).
 *
 * ★참고한 형식과 바꾼 것★
 * L1 은 lapa.ninja 류 갤러리 사이트의 정보구조를 가져왔다. L2 는 거기에 기관 제품 사이트
 * 두 곳(Aladdin Wealth · Solovis)의 밴드 구성을 얹어 4밴드 → 13밴드로 늘렸다.
 * 다만 **구조만 빌리고 내용은 전부 바꿨다.** 두 레퍼런스가 기대는 것들 — 고객 후기, 수상,
 * 파트너 로고, 보도자료, 제품 영상, 스톡 사진 — 은 이 프로젝트에 존재하지 않는다.
 * 없는 것을 지어내면 직전 커밋에서 고친 `LIVE` 배지와 똑같은 잘못이 된다. 그래서:
 *
 *   Aladdin 의 Key Pillars 01/02/03  →  CLAUDE.md §4 의 불변식 셋
 *   Aladdin 의 연결 경험 다이어그램   →  실제 근거 경로(스펙 v2.1 §5)
 *   Aladdin 의 Platform Partners     →  데이터 출처 5곳 **과 각각의 한계**
 *   Solovis 의 6-항목 혜택 그리드     →  보장 6종 + 그것을 강제하는 테스트 파일명
 *   Solovis 의 고객 인용구           →  저장소 자체의 규약 인용 (CLAUDE.md 출처 명시)
 *   Aladdin 의 수상 · 뉴스 그리드     →  **삭제.** 수상도 뉴스도 없다.
 *   Solovis 의 제품 영상             →  **삭제.** 영상이 없다.
 *
 * ★수치는 전부 출처가 있다★
 * EVIDENCE 의 모든 항목에 재현 방법(`how`)이 붙고, 달 수 없는 값은 지웠다.
 *
 * ★그리고 L2 에서 CountUp 을 증거 스트립에서 뺐다★
 * 카운트업은 1.1초 동안 **최종값이 아닌 수**를 그린다. 스크린샷을 찍으면 `BACKEND TESTS`
 * 가 1,467 로 나오는데 바로 밑 캡션은 1,534 라고 적혀 있었다. 모든 수치가 참이라는 것이
 * 유일한 주장인 밴드에서, 참값을 향해 애니메이션한다는 건 먼저 거짓을 보여 준다는 뜻이다.
 * 히어로 덱에는 남겨 둔다 — 그쪽은 `예시 수치` 라고 명시돼 있어 참을 주장하지 않는다.
 *
 * 모션: 스크롤 **연동**(scroll-linked)이지 스크롤 **가로채기**(scroll-jacking)가 아니다.
 * wheel/touch 를 가로채지 않고 스냅으로 가두지 않는다. 콘텐츠는 첫 페인트에 이미 완결돼
 * 있고 모션은 도착 방식만 바꾼다. prefers-reduced-motion 이면 전부 꺼지고 정적 레이아웃이
 * 곧 최종 디자인이다. globals.css §46 참고.
 */

import Link from "next/link";
import Reveal from "@/widgets/landing/Reveal";
import HeroDeckLive from "@/widgets/landing/HeroDeckLive";

/**
 * 갤러리 항목 = 모듈.
 * `sigs` 는 **쉴 때도 보이는** 두 줄, `metrics` 는 펼칠 때 더해지는 두 줄.
 * L1 에서는 서명이 한 줄뿐이라 쉬는 카드의 아래 40% 가 빈 채로 남았다(스크린샷에서 확인).
 * 미니 비주얼도 펼침 안에 있어서 쉴 때는 아무 그래픽이 없었다 — 둘 다 밖으로 꺼냈다.
 */
const MODULES = [
  {
    n: "01", code: "SCREENER", title: "Screener", href: "/screener",
    purpose: "전 종목에서 볼 것만 남긴다.",
    desc: "유동성 게이트로 거를 종목을 먼저 줄이고, 그다음 재무·가격·수급 팩터를 겹쳐 쓴다. 말로 검색해도 되고(nl2ast), 만든 조건은 AST 로 남아서 백테스터가 그대로 받는다.",
    sigs: [["필터 구조", "게이트 → 필터 → 애널라이저"], ["대상", "국내 주권 전체"]],
    metrics: [["검색", "자연어 → AST"], ["조건 저장", "AST 로 영속"]],
    visual: "bars",
  },
  {
    n: "02", code: "BACKTEST", title: "Backtester", href: "/backtest",
    purpose: "그 규칙이 과거에 통했는지 본다.",
    desc: "조건식을 그대로 과거에 돌린다. 실행은 run_id 로 서버에 남아서 새로고침해도 주소를 넘겨도 같은 결과가 열린다. 진행률은 엔진이 실제로 끝낸 일수에서 나온다. 경과 시간으로 지어내지 않는다.",
    sigs: [["실행 단위", "run_id (영속)"], ["진행 보고", "엔진 실측"]],
    metrics: [["결과", "URL 로 재방문"], ["비교", "런 대 런 오버레이"]],
    visual: "line",
  },
  {
    n: "03", code: "MACRO", title: "Macro Analysis", href: "/macro",
    purpose: "지금 국면을 정하고 못 박아 둔다.",
    desc: "성장과 물가 2축으로 국면을 나누고 카나리 지표를 같이 본다. 판정을 스냅샷으로 고정하면 뒷단계는 그 ID 를 들고 간다. 값을 베껴 가는 게 아니라서 몇 달 뒤에 열어도 같은 근거를 가리킨다.",
    sigs: [["근거 고정", "스냅샷 ID 참조"], ["레짐", "성장·물가 2축"]],
    metrics: [["PIT", "ALFRED 빈티지"], ["연결", "AAS 로 인계"]],
    visual: "heat",
  },
  {
    n: "04", code: "COMPANY", title: "Company Analysis", href: "/insights",
    purpose: "한 기업을 공시까지 파고든다.",
    desc: "DART 재무를 공시시차 반영해서 읽는다. 내재가치와 점수 분해를 같이 보여 주는데, 계산이 안 되는 항목은 0 을 적는 대신 왜 안 되는지를 적는다.",
    sigs: [["재무 기준", "DART · 공시시차 반영"], ["가치평가", "RIM · DCF · DDM"]],
    metrics: [["품질", "QoE · 발생액"], ["없는 값", "0 이 아닌 사유"]],
    visual: "rows",
  },
  {
    n: "05", code: "RISK", title: "Risk Analysis", href: "/risk-tools",
    purpose: "잘될 때 말고 터질 때를 본다.",
    desc: "시나리오를 걸어 보고 어디가 먼저 무너지는지 본다. 시나리오는 이름이 아니라 내용 해시로 구분한다. 그래서 누가 충격 정의를 바꿔 놓으면 화면이 먼저 알려 준다.",
    sigs: [["시나리오 신원", "pack_id@해시"], ["측도", "VaR · ES"]],
    metrics: [["충격 정의", "변경 시 경고"], ["분해", "역사 vs 가정"]],
    visual: "gauge",
  },
  {
    n: "06", code: "ALLOCATION", title: "Allocation Studio", href: "/allocation",
    purpose: "결정한 이유를 남겨 둔다.",
    desc: "Black-Litterman 뷰, 효율적 프론티어, 타이밍 오버레이를 한 줄기로 묶는다. 결정에서 런, 스냅샷, 룰셋 버전까지 사슬이 이어지기 때문에 나중에 왜 그렇게 했는지 되짚을 수 있다.",
    sigs: [["재현 사슬", "결정 → 런 → 스냅샷"], ["모델", "BL · HRP · MVO"]],
    metrics: [["타이밍", "일방향 오버레이"], ["검증", "워크포워드 OOS"]],
    visual: "donut",
  },
];

/** 세 기둥 — CLAUDE.md §4 "절대 불변식" 을 그대로 옮긴 것. 마케팅 문구가 아니다. */
const PILLARS = [
  {
    n: "01", code: "REPRODUCIBILITY", title: "재현",
    lede: "몇 달 뒤에 이 결정을 다시 열어 볼 수 있습니다.",
    body: "결정에는 런(run_id)이 붙고, 런에는 스냅샷(snapshot_id)과 룰셋 버전(name@version), 시나리오 팩(pack_id@해시)이 붙습니다. 각 단계가 값을 베껴 가는 대신 ID 만 들고 있어서, 나중에 열어도 그때 본 근거를 그대로 가리킵니다.",
  },
  {
    n: "02", code: "HONESTY", title: "정직",
    lede: "0 과 계산하지 않음과 조회 불가는 다 다른 얘기입니다.",
    body: "셋을 화면에서 다르게 그립니다. 조회가 실패하면 그럴듯한 값으로 빈칸을 메우는 대신 실패했다는 사실과 이유를 적습니다. 판정하지 못한 항목에는 퍼센트도 막대도 그리지 않습니다. 0% 짜리 막대는 위험이 없다는 뜻으로 읽히니까요.",
  },
  {
    n: "03", code: "SAFETY", title: "안전",
    lede: "자동매매 기본값은 dry_run=True 입니다.",
    body: "주문은 킬 스위치, 손실 한도, 주문 상한, 일일 한도, 포지션 제한, dry-run 기본값까지 여섯 단계를 지납니다. 이걸 건너뛰는 코드는 CI 에서 막힙니다. 실계좌를 붙이기 전에 모의투자로 먼저 확인하게 되어 있습니다.",
  },
];

/**
 * 리서치 파이프라인 — 스펙 v2.1 §5 의 근거 경로 그대로.
 * `carries` 는 그 단계가 **다음 단계로 넘기는 신원**이다. 값을 넘기는 게 아니다.
 */
const PIPELINE: Array<{ n: string; label: string; carries: string; href?: string }> = [
  { n: "1", label: "매크로 관측", carries: "LIVE", href: "/macro" },
  { n: "2", label: "스냅샷 고정", carries: "snapshot_id" },
  { n: "3", label: "AAS 에서 참조", carries: "값 복사 아님", href: "/allocation/macro" },
  { n: "4", label: "타이밍 규칙", carries: "name@version", href: "/allocation/timing" },
  { n: "5", label: "시나리오 도전", carries: "pack_id@해시", href: "/allocation/stress" },
  { n: "6", label: "최적화 · 백테스트", carries: "run_id", href: "/allocation/optimize" },
  { n: "7", label: "저널 · 귀인", carries: "결정 사슬", href: "/allocation/journal" },
];

/**
 * ★보장 — 문장이 아니라 실행되는 것들★
 * Solovis 의 6-항목 혜택 그리드 자리인데, 혜택 대신 **깨지면 실패하는 테스트**를 적는다.
 * 여기 적힌 경로는 실재해야 한다 — tests/test_landing_claims.py 가 CI 에서 정적으로 검사한다.
 * (경로가 바뀌었는데 이 목록이 그대로면, 랜딩이 없는 보장을 광고하는 셈이 된다.)
 */
const GUARANTEES = [
  { claim: "주문 실행기를 트레이딩 엔진 밖에서 만들 수 없습니다.", why: "그 경로에는 안전장치가 없어서 바로 주문이 나갑니다.", test: "tests/test_no_order_executor_bypass.py" },
  { claim: "mock 은 KIS_USE_MOCK 이 정확히 1 일 때만 켜집니다.", why: "판정하는 곳이 하나여야 운영에 합성값이 새지 않습니다.", test: "tests/test_mock_gate.py" },
  { claim: "스크리너 종목 수가 부풀지 않습니다.", why: "걸러낸 종목과 아예 못 읽은 종목은 다릅니다.", test: "tests/test_screener_honest_counts.py" },
  { claim: "가치평가에 mock 데이터가 새지 않습니다.", why: "지어낸 값으로 계산한 내재가치는 아무 의미가 없습니다.", test: "tests/test_valuation_mock_leak.py" },
  { claim: "적재 상태를 실제보다 좋게 적지 않습니다.", why: "저장한 건수와 시도한 건수를 따로 셉니다.", test: "tests/test_ingest_saved_honest.py" },
  { claim: "라우트가 조용히 사라지지 않습니다.", why: "리팩터링하다 엔드포인트가 빠져도 보통은 아무도 모릅니다.", test: "tests/test_route_parity.py" },
];

/**
 * 데이터 출처 — Aladdin 의 Platform Partners 자리.
 * ★한계를 함께 적는다★ 출처만 나열하면 데이터가 완전하다는 인상을 준다. 실제로는 각각
 * 쿼터·지연·구간 제한이 있고, 그것이 화면의 값이 비는 이유가 된다.
 */
const SOURCES = [
  { k: "KRX", name: "한국거래소", gives: "장기 일봉, 투자자별 수급", limit: "키가 없으면 장기 구간이 빕니다. 30일보다 이전 수급은 백필을 한 번 돌려야 실데이터가 들어옵니다." },
  { k: "DART", name: "금융감독원 전자공시", gives: "재무제표와 공시", limit: "하루 20,000건 쿼터가 있습니다. 공시시차를 반영해서 읽지 않으면 과거 시점 계산에 미래 정보가 섞여 들어갑니다." },
  { k: "KIS", name: "한국투자증권 Open API", gives: "시세와 주문", limit: "일봉은 최근 30일치만 줍니다. 키가 없으면 결정론적 mock 으로 넘어갑니다." },
  { k: "ECOS", name: "한국은행", gives: "환율과 금리", limit: "지표마다 발표 주기와 지연이 제각각입니다. 최신 관측이라고 해서 오늘 값은 아닙니다." },
  { k: "FRED", name: "세인트루이스 연준 (ALFRED 포함)", gives: "미국 금리와 거시 지표", limit: "나중에 수정되는 시계열입니다. 과거 시점의 판단을 재현하려면 ALFRED 빈티지를 써야 합니다." },
];

/** FAQ — 답은 전부 CLAUDE.md / README 에서 나온다. 네이티브 <details> 라 JS 0. */
const FAQ = [
  {
    q: "Project Alpha 는 무엇인가요?",
    a: "한국 주식 퀀트 리서치 플랫폼입니다. 스크리닝부터 분석, 백테스트, 자산배분, 모의 자동매매까지 한 시스템 안에서 이어집니다. 중간에 내린 결정이 어떤 근거 위에 있었는지도 같이 기록해 둡니다. FastAPI 와 Next.js 14, PostgreSQL 로 만들었습니다.",
  },
  {
    q: "실제로 주문을 내나요?",
    a: "기본값은 내지 않습니다. 자동매매는 dry_run=True 로 시작하고, 주문이 나가려면 킬 스위치와 손실 한도, 주문 상한, 일일 한도, 포지션 제한을 전부 지나야 합니다. 실계좌를 붙이기 전에 모의투자(KIS_IS_PAPER=1)로 먼저 확인하도록 문서와 코드 양쪽에서 막아 뒀습니다.",
  },
  {
    q: "API 키 없이 둘러볼 수 있나요?",
    a: "있습니다. KIS_USE_MOCK=1 이 개발 기본값이라 외부로 나가는 호출이 없습니다. 결정론적 mock 으로 돌아가니 기능은 전부 그대로 볼 수 있습니다. 다만 그 값이 합성이라는 건 화면에서 숨기지 않습니다. mock 으로 만든 런에는 표시가 붙습니다.",
  },
  {
    q: "데이터는 어디서 오나요?",
    a: "KRX 에서 장기 일봉과 수급, DART 에서 재무와 공시, KIS 에서 시세와 주문, ECOS 에서 국내 거시, FRED 와 ALFRED 에서 미국 거시를 받아 옵니다. 다섯 곳 다 쿼터나 지연, 구간 제한이 있습니다. 각각의 한계는 위 데이터 출처 밴드에 적어 두었습니다.",
  },
  {
    q: "계산할 수 없는 값은 어떻게 보이나요?",
    a: "0 으로 채우지 않습니다. 조회 불가와 계산하지 않음과 값이 0 인 것은 화면에서 서로 다르게 그립니다. 판정하지 못한 항목에는 퍼센트도 비율 막대도 그리지 않고, 왜 없는지를 대신 적습니다. 귀인 화면의 몇몇 항목은 지금도 데이터가 막혀 있어서 사유와 함께 비어 있는 상태로 남아 있습니다.",
  },
];

/** 푸터 — 전부 실재하는 라우트. 마지막 열만 링크가 아닌 저장소 경로(앱 라우트가 없다). */
const FOOTER_COLS: Array<{ h: string; items: Array<{ t: string; href?: string }> }> = [
  {
    h: "모듈",
    items: [
      { t: "Screener", href: "/screener" },
      { t: "Backtester", href: "/backtest" },
      { t: "Macro Analysis", href: "/macro" },
      { t: "Company Analysis", href: "/insights" },
      { t: "Risk Analysis", href: "/risk-tools" },
      { t: "Allocation Studio", href: "/allocation" },
    ],
  },
  {
    h: "리서치 단계",
    items: [
      { t: "연구 색인", href: "/allocation/overview" },
      { t: "매크로 근거", href: "/allocation/macro" },
      { t: "타이밍 규칙", href: "/allocation/timing" },
      { t: "시나리오 검증", href: "/allocation/stress" },
      { t: "결정 저널", href: "/allocation/journal" },
      { t: "귀인", href: "/allocation/explain" },
    ],
  },
  {
    h: "운영",
    items: [
      { t: "대시보드", href: "/dashboard" },
      { t: "데이터 인프라", href: "/admin/data" },
      { t: "실거래 콘솔", href: "/admin/live-trading" },
      { t: "실현성 점검", href: "/admin/realism" },
      { t: "UI 카탈로그", href: "/dev/ui" },
    ],
  },
  {
    h: "저장소",
    items: [
      { t: "CLAUDE.md" }, { t: "README.md" }, { t: "docs/HISTORY.md" },
      { t: "docs/specs/" }, { t: "docs/decisions/adr-001-*.md" },
    ],
  },
];

/**
 * ★EVIDENCE — 모든 항목에 재현 방법이 붙는다★
 * `how` 는 장식이 아니라 계약이다. 여기 적은 방법으로 다시 세었을 때 값이 나오지 않으면
 * 그 항목은 고치거나 지운다. 재현할 수 없어서 **지운** 것: 벡터화 배수(142×), 팩터 수
 * (290+), 체결가 모델 수(13), 조건 함수 수(19) — 근거 레지스트리를 특정하지 못했다.
 */
const EVIDENCE: Array<{ k: string; v: string; how: string }> = [
  { k: "BACKEND TESTS", v: "1,539", how: "pytest tests/ 를 돌리면 1,539 passed / 10 skipped" },
  { k: "E2E TESTS", v: "181", how: "playwright test 를 돌리면 181 passed. 전 라우트와 오류 가드 포함" },
  { k: "API ENDPOINTS", v: "292", how: "src/api/*.py 안의 @router 데코레이터를 센 값" },
  { k: "APP ROUTES", v: "29", how: "frontend/src/app 아래 page.tsx 파일 수" },
  { k: "DATA SOURCES", v: "5", how: "KRX, DART, KIS, ECOS, FRED. 각 모듈이 있는지 확인함" },
];

// ─── 카드 미니 비주얼 (순수 SVG · 외부 자산 0) ───────────────────────────────
function Visual({ kind }: { kind: string }) {
  if (kind === "bars") {
    const hs = [9, 14, 7, 18, 12, 22, 16, 27, 20, 31];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        {hs.map((h, i) => (
          <rect key={i} className="lp-vbar" x={i * 12 + 2} y={36 - h} width="7" height={h}
            fill={i === hs.length - 1 ? "var(--bs-primary)" : "#d4d4d8"} />
        ))}
      </svg>
    );
  }
  if (kind === "line") {
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        <polyline className="lp-vline2" points="2,32 22,31 42,32 62,28 82,29 102,24 118,26"
          fill="none" stroke="#d4d4d8" strokeWidth="1.2" pathLength={1} />
        <polyline className="lp-vline" points="2,30 22,26 42,29 62,18 82,21 102,10 118,13"
          fill="none" stroke="var(--bs-primary)" strokeWidth="1.6" pathLength={1} />
      </svg>
    );
  }
  if (kind === "heat") {
    const cells = [0.35, 0.7, 1, 0.25, 0.5, 0.2, 1, 0.45, 0.3, 0.6, 0.15, 0.4];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        {cells.map((o, i) => (
          <rect key={i} className="lp-vheat" x={(i % 4) * 30 + 1} y={Math.floor(i / 4) * 12 + 1}
            width="27" height="10" fill="var(--bs-primary)" opacity={0.12 + o * 0.55} />
        ))}
      </svg>
    );
  }
  if (kind === "rows") {
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        {[6, 16, 26].map((y, i) => (
          <g key={i}>
            <rect x="2" y={y} width={86 - i * 18} height="3.5" fill="#e4e4e7" />
            <rect className="lp-vrow" x="2" y={y} width={40 - i * 8} height="3.5" fill="var(--bs-primary)" opacity="0.65" />
          </g>
        ))}
      </svg>
    );
  }
  if (kind === "donut") {
    const C = 2 * Math.PI * 13;
    const segs = [
      { frac: 0.5, color: "var(--bs-primary)", off: 0 },
      { frac: 0.3, color: "#a5b4fc", off: 0.5 },
      { frac: 0.2, color: "#d4d4d8", off: 0.8 },
    ];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        <g transform="translate(60,18) rotate(-90)">
          {segs.map((s, i) => (
            <circle key={i} className="lp-vdonut" cx="0" cy="0" r="13" fill="none"
              stroke={s.color} strokeWidth="5"
              strokeDasharray={`${s.frac * C} ${C}`} strokeDashoffset={-s.off * C} pathLength={C} />
          ))}
        </g>
      </svg>
    );
  }
  return (
    <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
      <circle cx="60" cy="18" r="13" fill="none" stroke="#e4e4e7" strokeWidth="2.5" />
      <path className="lp-vgauge" d="M 60 5 A 13 13 0 0 1 72.3 22" fill="none" stroke="var(--bs-primary)" strokeWidth="2.5" pathLength={1} />
    </svg>
  );
}

export default function Landing() {
  return (
    <div className="lp-root">
      {/* JS·모션이 없어도 콘텐츠가 숨지 않도록 — 등장 애니메이션의 기본값이 opacity:0 이다. */}
      <noscript>
        <style>{".lp-reveal,.lp-stagger>*,.lp-module,.lp-pillar,.lp-pipe-step,.lp-guard-item{opacity:1!important;transform:none!important}"}</style>
      </noscript>

      {/* ── ① 고지 바 ──────────────────────────────────────────────────────────
          레퍼런스가 이 자리에 쓰는 것은 공지/프로모션이다. 여기서는 **한계**를 알린다.
          제품의 첫 줄이 자랑이 아니라 기본값의 고백인 편이 이 도구에는 정확하다. */}
      <div className="lp-topbar">
        <span className="lp-mono lp-topbar-k">DEFAULTS</span>
        <p className="lp-topbar-t">
          개발 기본값은 <b>mock</b> 입니다. <code>KIS_USE_MOCK=1</code> 이면 외부로 나가는 호출이
          없고, 자동매매는 <code>dry_run=True</code> 로 시작합니다.
        </p>
      </div>

      <header className="lp-header">
        <div className="lp-brand">
          <span className="lp-logo" aria-hidden>
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
          </span>
          Project Alpha
        </div>
        <nav className="lp-nav">
          <a href="#pipeline">PIPELINE</a>
          <a href="#modules">MODULES</a>
          <a href="#guarantees">GUARANTEES</a>
          <a href="#evidence">EVIDENCE</a>
          <a href="#faq">FAQ</a>
          <Link href="/dashboard" className="lp-nav-cta">Dashboard →</Link>
        </nav>
      </header>

      {/* ── ② 진술: 문장 하나 + 예시 덱 하나 ── */}
      <section className="lp-statement">
        <Reveal className="lp-statement-copy" stagger>
          <p className="lp-eyebrow lp-mono">KOREAN EQUITY · QUANT RESEARCH</p>
          <h1>
            근거를 남기는<br />리서치 환경.
          </h1>
          <p className="lp-lede">
            여기 있는 숫자는 <b>전부 어디서 나왔는지</b> 말할 수 있습니다. 계산이 안 되는 값은
            0 으로 메우는 대신 없다고 적습니다. 화면이 조금 덜 예뻐지더라도 그게 낫다고 봤습니다.
          </p>
          <div className="lp-hero-cta">
            <Link href="/dashboard" className="lp-btn lp-btn-primary">대시보드 열기 →</Link>
            <a href="#pipeline" className="lp-btn lp-btn-ghost">리서치 경로 보기</a>
          </div>
        </Reveal>
        <div className="lp-statement-live">
          {/* 스톡 일러스트가 아니라 백테스터 화면의 레이아웃 예시다.
              ★수치는 실적이 아니다★ — 처음에 나는 여기에 "백엔드가 없으면 스스로 빈 상태를
              말한다" 라고 적었는데, 사실이 아니었다. 덱은 백엔드를 아예 호출하지 않고 전부
              하드코딩이다. 그래서 배지를 `예시 수치` 로 바꾸고 덱 아래에 그 사실을 적는다. */}
          <HeroDeckLive />
        </div>
      </section>

      {/* ── ③ 세 기둥 (CLAUDE.md §4) ── */}
      <section className="lp-pillars-wrap" id="pillars">
        <div className="lp-section-head">
          <span className="lp-mono">THREE INVARIANTS</span>
          <span className="lp-mono">CLAUDE.md §4 에 적어 둔 것</span>
        </div>
        <Reveal className="lp-pillars" stagger>
          {PILLARS.map((p) => (
            <article key={p.n} className="lp-pillar">
              <div className="lp-pillar-n lp-mono">{p.n}</div>
              <div className="lp-pillar-code lp-mono">{p.code}</div>
              <h3 className="lp-pillar-title">{p.title}</h3>
              <p className="lp-pillar-lede">{p.lede}</p>
              <p className="lp-pillar-body">{p.body}</p>
            </article>
          ))}
        </Reveal>
      </section>

      {/* ── ④ 리서치 파이프라인 (스펙 v2.1 §5 의 근거 경로) ── */}
      <section className="lp-pipe-wrap" id="pipeline">
        <div className="lp-section-head">
          <span className="lp-mono">EVIDENCE PATH</span>
          <span className="lp-mono">각 단계가 다음으로 넘기는 것</span>
        </div>
        <Reveal className="lp-pipe" stagger>
          {PIPELINE.map((s) => {
            const inner = (
              <>
                <span className="lp-pipe-n lp-mono">{s.n}</span>
                <span className="lp-pipe-label">{s.label}</span>
                <span className="lp-pipe-carries lp-mono">{s.carries}</span>
              </>
            );
            return s.href
              ? <Link key={s.n} href={s.href} className="lp-pipe-step">{inner}</Link>
              : <div key={s.n} className="lp-pipe-step">{inner}</div>;
          })}
        </Reveal>
        <p className="lp-pipe-note">
          스냅샷을 고정해도 값이 복사되지는 않습니다. 뒷단계는 <code>snapshot_id</code> 를 들고
          갈 뿐입니다. 그리고 <b>매크로가 타이밍을 덮어쓰는 일은 없습니다.</b> 오버레이는 한
          방향이라, 끄면 결과가 눈에 띄게 되돌아옵니다.
        </p>
      </section>

      {/* ── ⑤ 갤러리: 여섯 개 모듈 ── */}
      <section className="lp-gallery-wrap" id="modules">
        <div className="lp-section-head">
          <span className="lp-mono">RESEARCH MODULES</span>
          <span className="lp-mono">SIX SURFACES · ONE RECORD</span>
        </div>
        <div className="lp-gallery">
          {MODULES.map((m) => (
            <Link key={m.n} href={m.href} className="lp-module">
              <div className="lp-module-top">
                <span className="lp-mono lp-module-code">{m.n} / {m.code}</span>
                <span className="lp-module-open lp-mono" aria-hidden>OPEN ↗</span>
              </div>
              <h3>{m.title}</h3>
              <p className="lp-module-purpose">{m.purpose}</p>

              {/* 쉴 때도 보이는 것 — 서명 두 줄 + 미니 비주얼.
                  L1 에서는 이 둘이 펼침 안에 있어서 쉬는 카드가 이름만 있는 상자였다. */}
              <div className="lp-module-rest">
                {m.sigs.map(([k, v]) => (
                  <div key={k} className="lp-module-sig lp-mono">
                    <span>{k}</span><b>{v}</b>
                  </div>
                ))}
                <Visual kind={m.visual} />
              </div>

              {/* 펼침: 호버 **그리고** 포커스에서 열린다(키보드 사용자에게도 같은 정보). */}
              <div className="lp-module-more">
                <p className="lp-module-desc">{m.desc}</p>
                <div className="lp-module-metrics">
                  {m.metrics.map(([k, v]) => (
                    <div key={k} className="lp-metric-row lp-mono">
                      <span>{k}</span><span className="lp-metric-val">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── ⑥ 보장 (다크) — 주장마다 그것을 강제하는 테스트를 함께 적는다 ── */}
      <section className="lp-guard-wrap" id="guarantees">
        <div className="lp-guard-head">
          <div>
            <p className="lp-mono lp-guard-eyebrow">ENFORCED, NOT CLAIMED</p>
            <h2 className="lp-guard-h">보장 여섯 가지, 그리고 그걸 깨면 터지는 테스트</h2>
          </div>
          <p className="lp-guard-sub">
            각 줄 옆에 적힌 파일이 CI 에서 그대로 돌아갑니다. 주장이 깨지면 빌드가 빨개지니,
            이 목록은 시간이 지나도 혼자 낡지 않습니다.
          </p>
        </div>
        <div className="lp-guards">
          {GUARANTEES.map((g) => (
            <article key={g.test} className="lp-guard-item">
              <p className="lp-guard-claim">{g.claim}</p>
              <p className="lp-guard-why">{g.why}</p>
              <code className="lp-guard-test">{g.test}</code>
            </article>
          ))}
        </div>
      </section>

      {/* ── ⑦ 데이터 출처 — 한계를 함께 적는다 ── */}
      <section className="lp-src-wrap" id="sources">
        <div className="lp-section-head">
          <span className="lp-mono">DATA SOURCES</span>
          <span className="lp-mono">할 수 있는 것과 못 하는 것</span>
        </div>
        <Reveal className="lp-srcs" stagger>
          {SOURCES.map((s) => (
            <article key={s.k} className="lp-src">
              <div className="lp-src-top">
                <span className="lp-src-k lp-mono">{s.k}</span>
                <span className="lp-src-name">{s.name}</span>
              </div>
              <p className="lp-src-gives">{s.gives}</p>
              <p className="lp-src-limit"><span className="lp-mono lp-src-limit-k">한계</span>{s.limit}</p>
            </article>
          ))}
        </Reveal>
      </section>

      {/* ── ⑧ 인용 — 고객 후기가 아니라 저장소 자신의 규약 ────────────────────
          레퍼런스는 여기에 고객 인용구를 둔다. 우리에겐 고객이 없다. 지어내는 대신
          이 저장소가 스스로에게 적어 둔 문장을 인용한다 — 출처를 파일명으로 밝힌다. */}
      <section className="lp-quote-wrap">
        <Reveal className="lp-quote" stagger>
          <blockquote className="lp-quote-t">
            “수치는 문서가 아니라 코드가 진실입니다.”
          </blockquote>
          <p className="lp-quote-src lp-mono">CLAUDE.md, 프로젝트 규약</p>
          <p className="lp-quote-body">
            같은 파일에 그렇게 적은 이유도 남아 있습니다. 예전 CLAUDE.md 는 필터 13종,
            FIELD_BY_ID 49개, 라우트 223개라고 적고 있었는데 직접 세어 보니 <b>11개, 157개,
            268개</b> 였습니다. 셋 다 틀렸습니다. 그래서 이 페이지의 숫자에는 세는 방법을 같이
            적어 뒀습니다. 다시 세어서 다르면 고칩니다.
          </p>
        </Reveal>
      </section>

      {/* ── ⑨ 증거: 출처 없는 수치는 없다 ──────────────────────────────────────
          ★CountUp 을 쓰지 않는다★ 카운트업은 1.1초 동안 최종값이 아닌 수를 그린다.
          모든 수치가 참이라는 것이 유일한 주장인 밴드에서는 그 1.1초가 곧 거짓이다. */}
      <section className="lp-evidence-wrap" id="evidence">
        <div className="lp-section-head">
          <span className="lp-mono">EVIDENCE</span>
          <span className="lp-mono">모든 값에 재현 방법이 붙습니다</span>
        </div>
        <Reveal className="lp-evidence" stagger>
          {EVIDENCE.map((e) => (
            <div key={e.k} className="lp-ev">
              <div className="lp-mono lp-ev-k">{e.k}</div>
              <div className="lp-ev-v">{e.v}</div>
              <div className="lp-ev-how">{e.how}</div>
            </div>
          ))}
        </Reveal>
        <p className="lp-evidence-note">
          다시 셀 수 없는 숫자는 표에서 <b>뺐습니다.</b> 대충 반올림해서 남겨 두느니 없는 편이
          낫습니다. 이 숫자들은 애니메이션으로 올라가지도 <b>않습니다.</b> 최종값에 닿기까지
          1초 동안 화면에 틀린 수가 떠 있게 되니까요.
        </p>
      </section>

      {/* ── ⑩ FAQ — 네이티브 <details>. JS 0, 접근성은 브라우저가 제공. ── */}
      <section className="lp-faq-wrap" id="faq">
        <div className="lp-section-head">
          <span className="lp-mono">FAQ</span>
          <span className="lp-mono">답은 CLAUDE.md 와 README 에 있습니다</span>
        </div>
        <div className="lp-faq">
          {FAQ.map((f) => (
            <details key={f.q} className="lp-faq-item">
              <summary className="lp-faq-q">
                <span>{f.q}</span>
                <span className="lp-faq-mark" aria-hidden />
              </summary>
              <p className="lp-faq-a">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* ── ⑪ CTA ── */}
      <section className="lp-cta">
        <div className="lp-cta-in">
          <h2 className="lp-cta-h">읽는 것보다 열어 보는 게 빠릅니다.</h2>
          <p className="lp-cta-p">
            API 키는 없어도 됩니다. mock 이 기본값이고, 그 값이 합성이라는 건 화면이 알려 줍니다.
          </p>
          <div className="lp-cta-btns">
            <Link href="/dashboard" className="lp-btn lp-btn-onaccent">대시보드 →</Link>
            <Link href="/screener" className="lp-btn lp-btn-onaccent-ghost">스크리너부터 보기</Link>
          </div>
        </div>
      </section>

      {/* ── ⑫ 푸터 ── */}
      <footer className="lp-footer">
        <div className="lp-footer-cols">
          {FOOTER_COLS.map((c) => (
            <div key={c.h} className="lp-footer-col">
              <div className="lp-mono lp-footer-h">{c.h}</div>
              <ul className="lp-footer-list">
                {c.items.map((it) => (
                  <li key={it.t}>
                    {it.href
                      ? <Link href={it.href}>{it.t}</Link>
                      : <span className="lp-mono lp-footer-path">{it.t}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="lp-footer-bar">
          <div className="lp-mono lp-footer-left">
            <i className="lp-status-dot" aria-hidden />PROJECT ALPHA
          </div>
          <div className="lp-mono lp-footer-right">
            © 2026 PROJECT ALPHA · BUILT FOR ACCURACY
          </div>
        </div>
      </footer>
    </div>
  );
}
