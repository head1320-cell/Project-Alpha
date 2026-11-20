# UI/UX 전문화 ① — U0 바탕 + 접근성 P0 넷: 구현 계획 (2026-11-20)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> (이 저장소의 받은 결정: 하위 에이전트는 쓰지 않는다 — 같은 세션에서 조각 순서대로 실행한다.)

**Goal:** ADR 007 의 토큰 · 장치 · 가드를 세우되 ★제품 화면의 보이는 변화는 0★ 으로 두고, 그 바로 뒤에 접근성 P0 넷을 작은 커밋 넷으로 고친다.

**Architecture:** `globals.css` 끝의 새 토큰 블록을 `html` 의 속성 둘(`data-tier` · `data-density`)이 다시 정한다. 속성은 경로 표가 정하며 ★제품 경로는 표에 없다★ — 개발 견본 경로 하나만 있다.
규칙은 문서가 아니라 pytest 래칫과 화면 스펙이 건다.

**Tech Stack:** Next.js(app router) · 순수 CSS(`globals.css`) · Playwright(E2E · 순수 스펙) · pytest(소스 훑기 가드). 새 의존성 0.

- 받은 말: "추천대로 승인할게"(2026-11-20 — 설계 §10 의 결정 일곱 모두 추천안) · 계획 승인(같은 날).
- 설계: [`docs/superpowers/specs/2026-11-20-uiux-professionalization-design.md`](../specs/2026-11-20-uiux-professionalization-design.md) · 결정: [ADR 007](../../decisions/adr-007-density-tiers-visual-language.md).
- 답하는 물음: 배치와 읽기 쉬움의 ★구조★(`structural`). 어떤 수의 뜻 · 증거 등급 · 요청도 바꾸지 않는다.

---

## 0. 패널 결론 — U0 의 쟁점 (재무 · DB · 퀀트 · 수학 · 금융 · 웹디자인)

| 쟁점 | 갈린 의견 | 결론(근거) |
|---|---|---|
| 장치를 무엇으로 시험하나 | 웹디자인: 제품 화면 하나에 바로 달아 본다 / 퀀트 · 수학: 소스 글자가 아니라 동작으로 / 프로세스: U0 는 보이는 변화 0 | 제품 경로에는 달지 않는다. ① 카탈로그 `/dev/ui` 의 견본 상자에 속성을 직접 달아 값을 재고 ② ★개발 견본 경로 `/dev/density` 하나★를 경로 표에 넣어 첫 그림 전 조각 → 맞춤 훅 → 화면 사이 이동을 실제 브라우저에서 돌리며 ③ 제품 경로가 표에 없다는 것을 허용 목록 시험으로 건다 |
| 경로 표를 비워 둘 것인가 | 계획 파일: '경로 표는 비어 있다' / 수학: 붙이는 쪽 분기가 한 번도 돌지 않으면 공허한 분기다(CLAUDE.md §5) | ★'제품 경로 0 · 개발 견본 경로 1'로 고친다★ — 훅이 속성을 붙이고 · 다른 화면으로 가면 떼는 것을 브라우저에서 본다. 화면 사이 이동에서 속성이 새는 것이 '보이는 변화 0'을 깨는 가장 있을 법한 길이다 |
| 속성의 자리 | 설계 초안: 본문에 / 웹디자인: 첫 그림 전에 정해져야 깜박이지 않는다 | `html` 에 둔다(테마의 `.dark` 와 같은 자리 · 같은 조각 방식). 선택자는 속성만이라 견본 상자에도 그대로 걸린다 |
| 손가락 화면 | 웹디자인: CSS 질의(`pointer: coarse`)로 값을 덮는다 / 수학: 속성과 실제 값이 어긋나면 시험이 속는다 | 조각과 훅이 속성 자체를 넉넉으로 단다 — '지금 걸린 밀도'의 진실은 속성 하나다 |
| D7 걷기의 범위 | 웹디자인: 쓰이지 않는 토큰까지 다 / DB · 프로세스: `:root` 앞 네 블록은 ADR 001 이 묶었다 | ★네 블록 안은 건드리지 않는다★ — 걷는 것은 파일 · 그 파일만 쓰던 규칙 · 네 블록 밖의 토큰까지. 나머지는 목록만 남긴다 |
| 가드의 꼴 | 웹디자인: 금지 규칙 / 수학: 지금 수백 곳이 이미 어긴다 | 래칫 — 지금 수가 천장이고 줄기만 한다(줄었는데 기준선을 안 내려도 실패). 검사기마다 심은 위반을 잡는지 · 허용된 꼴은 지나가는지 짝으로 시험 |
| 잉크 강조(D2)를 언제 입히나 | 트레이더: 지금 전부 / 프로세스: 한 커밋이 셸과 여러 모듈을 함께 바꾸지 않는다 | U0 는 새 토큰(`--tx-accent` 등)까지 — 견본에서만 보인다. 옛 강조 토큰의 값은 건드리지 않고 화면 조각이 옮긴다 |
| 건너뛰기 링크가 라이트 골든을 바꾼다 | 프로세스: 골든은 못 박은 것 / 접근성: 모든 화면에 걸친 P0 | 의도한 변경으로 다시 얼린다 — 범위가 `frame:` 뿐임을 `golden-diff --expect-scope frame` 출력으로 커밋에 싣는다 |
| 우선순위 | — | CLAUDE.md 불변식 > 데이터 무결성 > 통계 타당성 > 트레이더의 쓰임 > 표현 |

## 1. 감사에서 본 것 (읽기 전용 · 2026-11-20 · HEAD `9770e4f`)

- **토큰의 자리**: `frontend/src/app/globals.css` 는 새 토큰을 파일 끝의 새 블록 + 바로 뒤 `.dark` 짝으로 받는다(같은 파일의 `--tx-*` 블록이 본).
  다크 생성기(`frontend/scripts/gen-dark-modules.mjs`)는 `:root` · `.dark` · `.tx-` · `.devui-` 선택자와 색을 글자로 적지 않은 선언을 건너뛴다 → 새 규칙이 토큰만 쓰면 생성 구역은 그대로다.
- **장치의 본**: `frontend/src/shared/theme/theme.ts` — 경로 표(`DARK_READY`) · 첫 그림 전 조각(`THEME_BOOT` — `frontend/src/app/layout.tsx` 의 `<head>`) · 셸의 맞춤 훅(`useThemeSync` — `frontend/src/widgets/layout/TerminalShell.tsx`).
  개발 화면(`/dev/…`)은 늘 라이트다(`DARK_EXCEPTIONS`) — 그래서 다크 견본은 ★견본 상자에 `dark` 클래스를 직접★ 단다(`.dark { --tx-…}` 가 클래스 선택자라 상자 안에서 토큰이 다시 정해진다).
- **한 가지 함정**: `:root` 에 적은 별칭(`--tx-accent: var(--tx-ink)`)은 `html` 에서 한 번 풀려 내려간다 — 안쪽 `.dark` 상자에서는 라이트 잉크가 그대로 물려온다. 그래서 별칭은 `.dark` 짝에도 다시 적는다(시험이 건다).
- **라이트 골든**: `frontend/e2e/dark-modules.spec.ts` 가 13 라우트의 계산 스타일을 `범위:태그.클래스` 키로 건다(범위 = shell · main · frame). 새 요소가 생기면 새 키라 실패한다 — 건너뛰기 링크가 그렇다.
- **가드의 본**: `tests/test_css_specificity_guard.py`(기준선 + 합성 위반 + 낡은 기준선 실패) · `tests/test_frontend_claim_words.py`(TSX 훑기 · 허용 목록).
- **순수 시험의 본**: `frontend/e2e/split-logic.spec.ts`(브라우저 없이 `../src/…` 를 가져와 건다 — 단위 시험 러너가 따로 없다). 모든 스펙은 `test` 를 `./fixtures` 에서 가져온다(`api-no-reuse.spec.ts` 가 건다).
- **카탈로그**: `frontend/src/app/dev/ui/page.tsx` · 스펙 `frontend/e2e/dev-ui.spec.ts`(표본 이름 목록 `SPECIMENS` 와 `.devui-item` 수가 1:1). 제품이 쓰지 않는 공용 파일을 가져다 쓰는 곳은 이 페이지 하나다(설계 §5.0).
- **P0 넷의 자리**: 셸에 건너뛰기 링크 없음 · `globals.css` 의 `transition: all` · 매매일지의 숨긴 파일 입력(`frontend/src/widgets/trade-journal/TradeJournalView.tsx`) · 이름 없는 스위치와 숫자 칸(`frontend/src/shared/ui/kit.tsx` 의 `Toggle` · `QuickStepper` — 이름 글자가 형제 `span` 이라 이어져 있지 않다).
- **CLAUDE.md 는 99줄**이다(100줄 미만 규칙) — 줄 수를 늘리지 않고 고친다.

## 2. 정한 것

### 2.1 장치의 계약 (`frontend/src/shared/ui/density/`)
| 이름 | 꼴 | 계약 |
|---|---|---|
| `Tier` · `Density` · `DensityPref` | `"work" \| "read" \| "present"` · `"compact" \| "regular" \| "comfortable"` · `"auto" \| Density` | 속성 값과 같은 글자 |
| `DENSITY_KEY` | `"alpha_density"` | 이 브라우저의 저장 열쇠(서버 0줄) |
| `TIER_DEFAULT` | 작업 → 촘촘 · 해석 → 보통 · 설명 → 넉넉 | 단의 기본 밀도 |
| `TIER_ROUTES` | `{ pattern, tier, label, lock? }[]` | ★제품 경로 0★ — 개발 견본 `/dev/density`(작업 단) 하나. `lock` 은 고객에게 보이는 화면(늘 넉넉) |
| `parsePref(v)` | 모르는 값 · 없는 값 → `"auto"` | 저장이 깨져도 지어내지 않고 자동으로 |
| `resolveDensity(path, pref, coarse, routes?)` | `{ tier, density } \| null` | 차례: 표에 없음 → `null` · `lock` → 넉넉 · 손가락 화면 → 넉넉 · 저장값 · 단의 기본값 |
| `applyDensity(el, state)` | `null` 이면 속성 둘을 뗀다 · 아니면 둘을 단다 | 둘은 늘 함께 붙거나 함께 없다 |
| `densityBoot(routes?)` · `DENSITY_BOOT` | 첫 그림 전에 도는 조각의 글 | ★같은 입력에 `resolveDensity` 와 같은 답★(순수 스펙이 격자로 견준다) · 저장을 읽다 실패해도 던지지 않는다 |
| `useDensitySync(path)` | 셸이 부른다 | ★경로가 바뀔 때마다★ 저장값과 손가락 화면 여부를 다시 읽어 `html` 의 속성을 맞춘다 — 표에 없는 경로로 가면 뗀다. React 상태 · 저장 변화 듣기 · 포인터 변화 듣기는 없다(§2.5) |

### 2.2 토큰 블록 (`globals.css` 끝 · ADR 007 §3 의 값 그대로)
- `:root` — 밀도 일곱의 기본값(넉넉) · 반경 척도(`--tx-r-1` ~ `--tx-r-5` · `--tx-r-pill`) · 깊이 여섯(`--tx-z-base` · `-sticky` · `-raised` · `-float` · `-modal` · `-toast`) · 잉크 강조 별칭(`--tx-accent` · `--tx-on-accent` · `--tx-focus` · `--tx-link`) · 수의 글꼴(`--tx-font-num`).
- `.dark` 짝 — 별칭 넷을 다시 적는다(§1 의 함정).
- `[data-density="compact" | "regular" | "comfortable"]` — 밀도 일곱 · `[data-tier="work" | "read" | "present"]` — `--tx-r-sec` · `--tx-r-row`.
- `[data-tier] .num` — 본문 글꼴 + 고정폭 숫자(결정 D3). 범위 밖 `.num` 은 그대로.
- 견본 전용 규칙은 `.devui-dn-*`(제품 CSS 가 아니다 — 공용 표는 U1 이 만든다).

### 2.3 가드 (`tests/frontend_style_scan.py` · `tests/test_frontend_style_ratchet.py`)
| 래칫 | 세는 것 | 죽여야 하는 변이 · 짝 |
|---|---|---|
| 척도 밖 글자 크기 | `globals.css` 의 `font-size: Npx` 가운데 척도(11 · 12 · 13 · 14 · 16 · 18 · 22 · 28) 밖 | `font-size: 13.5px` 를 심으면 +1 · 짝: `13px` · `var(--fs-base)` 는 0 |
| 척도 밖 반경 | `border-radius` 의 px 값 가운데 척도(0 · 2 · 4 · 8 · 12 · 20 · 999) 밖 | `border-radius: 7px` +1 · 짝: `8px` · `var(--tx-r-row)` · `50%` 는 0 |
| 날 `z-index` | 숫자를 글자로 적은 `z-index`(`var(--tx-z-*)` · `auto` 는 세지 않는다) | `z-index: 9999` +1 · 짝: `var(--tx-z-float)` 는 0 |
| 토큰 정의 밖 hex | ★사용자 정의 속성(`--이름`)의 값이 아닌 선언★에 적힌 `#rgb` · `#rrggbb` · `#rrggbbaa`(생성 구역은 뺀다) | 규칙에 `#ff0000` +1 · 짝: `--x: #ff0000` 은 0(어느 블록이든 토큰을 정의하는 것) · `:root { color: #123 }` 은 +1 |
| 척도 밖 중단점 | `@media` 의 `min-width` · `max-width` px 가운데 척도(480 · 640 · 900 · 1280 · 1600 과 그 −1) 밖 | `(max-width: 777px)` +1 · 짝: `640px` · `1279px` 는 0 |
| 모든 속성에 거는 전환 | 선택자 목록 — `transition: all …` · `transition-property: all` · 속성 이름 없이 시간만 적은 꼴(뜻이 all) | 하나 심으면 +1 · 짝: `transition: color .15s` · `none` · `var(--t)` 는 0 |
| TSX 의 `title=` | `frontend/src` 의 요소 `title=` 속성 — ★파일별 수★(부품 prop 이름 `title` 은 세지 않는다 — 소문자 태그만 · 속성이 다음 줄로 넘어간 꼬리표도 센다) | `<span title="…">` +1 · 짝: `<Section title="…">` · 식 안의 `{ title: … }` · 주석은 0 |
| 낱 `<table>` | `<table` 을 그리는 파일의 ★목록★ | 새 파일에 `<table>` 을 심으면 실패 · 짝: 목록 안의 파일은 통과 · 목록의 파일이 표를 걷었는데 목록에 남아도 실패 |
| 색의 뜻 | 등락색(`--tx-up` · `--tx-down` 과 `-ink` · `-soft`)을 쓰는 선택자의 허용 목록 · 상태색(`--tx-danger` · `--tx-warn` · `--tx-ok`)이 수 칸 선택자(`.num` · `td.num` · `[data-num]`)에 쓰이면 실패 | 수 칸에 `color: var(--tx-danger)` 를 심으면 실패 · 허용 목록 밖 선택자에 `--tx-up` 을 심으면 실패 · 짝: 목록 안은 통과 |

기준선은 ★검사기가 센 값★으로 시험 파일에 박는다(설계 문서의 수는 다른 스크립트가 셌다 — 다르면 까닭을 HISTORY 에 적는다). 줄었는데 기준선을 내리지 않으면 실패한다.

### 2.4 걷는 것 (결정 D7 — 걷기 전에 쓰임 0 을 다시 센다)
- 파일: `frontend/src/shared/ui/{primitives,feedback,MiniViz,AllocationMap,SectionHead,EvidenceDrawer,EvidenceDrawerPanel}.tsx` · `frontend/src/shared/ui/shadcn/{table,button,input,progress,slider}.tsx`.
  ★조건★: 가져다 쓰는 곳이 `app/dev/ui/page.tsx`(와 서로)뿐일 때만. 하나라도 제품 파일이 쓰면 그 파일은 남기고 까닭을 적는다.
- 그 파일만 쓰던 CSS 규칙(쓰는 곳 0 을 `frontend/src` · `frontend/e2e` 전체에서 확인한 클래스만) · 쓰이지 않는 함수 둘(`toneColor` · `pctColor`) · 그려지지 않는 규칙 둘(`.ca-scen-card.bull` · `.bear`) · `:root` 앞 네 블록 ★밖★의 쓰이지 않는 토큰.
- 카탈로그와 그 스펙(`dev-ui.spec.ts`)은 함께 고친다 — 남는 것은 제품이 쓰는 층(kit · States · evidence · tx · 형식 함수 · 노출)과 새 견본.

### 2.5 구현하며 정한 것 · 찾은 것 (U0-b · 2026-11-20)
| 무엇 | 정한 것 · 까닭 |
|---|---|
| 빈 값의 표기 | 설계 초안 §6.5 의 '빈 값은 줄표'는 ADR 005 · 용어집(`N/A` + 사유) · `voiceAudit`(보이는 줄표 금지)와 부딪혔다 → ADR 007 §5 를 `N/A` + 사유로 바로잡고 견본은 있는 `tx.Unknown` 을 쓴다 |
| 초점 고리 | 셸의 전역 규칙(`.terminal-main button:focus-visible` — 특이도 0,2,1)이 옛 강조색을 칠한다. ★단 전체에 거는 초점 규칙은 두지 않았다★ — 속성이 `html` 에 있어 셸 크롬(머리 줄 · 메뉴)까지 바뀐다. 견본은 제 범위 선택자(0,3,0)로 걸었고, 화면 조각이 제 화면의 범위에서 건다 |
| 셸 크롬 | 속성이 `html` 에 있으므로 셸도 범위 안이다 → 스펙 하나를 더했다: 속성을 떼어도 머리 줄 · 메뉴의 계산 스타일이 한 값도 달라지지 않는다(짝: 같은 조작이 본문 견본의 줄은 28 → 44px 로 바꾼다) |
| 맞춤 훅 | React 상태 없이 경로가 바뀔 때마다 저장값과 손가락 화면 여부를 다시 읽는다. 저장 변화 · 포인터 변화 듣기는 넣지 않았다 — 전환 단추는 U6 이고, 시험할 수 없는 분기를 미리 만들지 않는다 |
| 조각 = 순수 함수 | 격자(경로 9 × 저장값 7 × 손가락 화면 2)만으로는 '조각이 첫 줄에서 멈추지 않는다'는 변이가 살아남는다(표가 한 줄이라서) → ★겹치는 표 · 빈 표★를 견줌에 더했다 |
| 스펙이 처음 돌며 잡은 것 | 견본의 등락색이 잉크로 그려졌다(칸 규칙 `.devui-dn-table td` 의 특이도가 더 높았다) → 선택자를 고쳤다 |
| ★스크린샷 검수가 잡은 것 셋★ | 스펙 16 이 초록인데 그림에서 보였다: ① 넉넉 · 설명 단 · 속성 없는 표가 제 상자(≈340px)를 넘쳤다 ② 값 없음(`N/A` + 사유) 칸이 두 줄로 접혔다 ③ 390px 손가락 화면에서 표의 끝 칸이 잘렸다. → 시험 둘을 먼저 쓰고 빨강을 본 뒤 고쳤다(격자의 가장 좁은 칸 300 → 440px · 절 안에서 가로로 밀기 · 값 없음 칸은 한 줄) |
| 변이가 가르친 것 | '값 없음 칸의 줄바꿈 막기를 걷는다'는 변이가 두 번 살아남았다 — ① 440px 상자에서는 표가 눌리지 않고 ② 넉넉의 44px 줄은 두 줄 글자를 담고도 높이가 그대로였다. ★줄 높이로는 접힘을 보지 못한다★ → 390px 에서 값과 사유가 한 줄에 나란한지를 직접 잰다 |
| 견본 제목의 줄표 | 개발 화면은 `voiceAudit` 의 대상이 아니지만 새 화면 글자의 규칙(보이는 줄표 금지)을 따랐다 — 가운뎃점 · 괄호로 |
| eslint 의 범위 | CI 는 `eslint src` 를 돈다(오류 0 · 경고 96 — 기준선 그대로). `eslint .` 은 `e2e/fixtures.ts:57` 에서 오류 1 을 낸다(Playwright 의 `use` 를 React 훅으로 읽는 것 — 이 묶음 전부터 있던 것 · CI 범위 밖). 고치지 않았다 |
| 푸시의 때 | 조각마다 그 조각의 검증을 마치면 커밋 · 푸시한다(작업 환경이 한 번 다시 시작됐다). 전체 pytest · 전체 E2E 는 계획대로 U0 끝 게이트에서 한 번 |

**U0-b 의 변이(모두 죽음)** — 순수 16: 제품 경로를 표에 넣음 · `lock` 무시 · 손가락 화면 무시 · 저장값 무시 · 뗄 때 하나만 뗌 · 붙일 때 밀도만 붙임 · 조각이 손가락 화면 무시 · 조각이 `lock` 무시 · 조각이 모르는 저장값을 그대로 씀 · `parsePref` 가 아무 글자나 받음 · 작업 단의 기본값을 보통으로 · 단을 늘 작업으로 · 조각의 저장 읽기 보호를 걷음 · 조각이 첫 줄에서 멈추지 않음 · 조각의 질의 글자를 바꿈 · 저장 열쇠를 바꿈.
브라우저 16: `.dark` 짝에서 강조 별칭 빠짐 · 촘촘의 줄 28 → 30 · 단 안의 `.num` 규칙 삭제 · 셸이 훅을 부르지 않음 · 첫 그림 전 조각을 싣지 않음 · 제품 경로(스크리너)를 표에 넣음 · 작업 단의 절 반경을 8 로 · 훅의 질의 글자를 바꿈 · 촘촘에서 합성 표시를 숨김 · 강조 위 글자 별칭을 잉크로 · 기본값의 줄을 40 으로 · 훅이 표에 없는 경로에서 떼지 않음 · 견본 초점 고리를 옛 강조색으로 · 격자의 가장 좁은 칸을 300 으로 · 값 없음 칸의 줄바꿈 막기를 걷음 · 절의 가로 밀기를 걷음.

### 2.6 구현하며 정한 것 · 찾은 것 (U0-c · 2026-11-20)
| 무엇 | 정한 것 · 까닭 |
|---|---|
| 기준선(검사기가 센 값) | 척도 밖 글자 크기 586 · 반경 382 · 날 `z-index` 80 · 토큰 정의 밖 hex 240 · 척도 밖 중단점 17(조건 글) · 모든 속성에 거는 전환 7(선택자) · 등락색 선택자 43(허용 목록) · 수 칸의 상태색 0(고정) · 요소의 `title=` 102(파일 32 — 파일별 수) · 낱 `<table>` 파일 59(목록). ★수는 시험 파일이 진실★ — 이 줄은 2026-11-20 의 관측이다 |
| `title=` 은 63 이 아니라 102 | 감사 스크립트는 꼬리표와 속성이 같은 줄일 때만 셌다(같은 방법으로 다시 세면 정확히 63). 다음 줄로 넘어간 39곳을 놓쳤다 → 설계 문서 §11.3 에 정정 |
| `title=` 은 파일별 수로 | 합계만 잠그면 한 파일이 줄이고 다른 파일이 늘려도 지나간다 |
| 시험 둘을 더함 | 검사기의 척도 = `:root` 토큰 블록의 값(반경 척도 · 밀도 토큰의 글자 크기) · 가드가 보는 CSS 가 `globals.css` 하나뿐인지 · 범위 문법의 폭 조건이 없는지 — 검사기가 못 보는 꼴이 생기면 먼저 실패한다 |
| 허용 목록에서 본 것 | 등락색 선택자 43 가운데 `.itd-day-checkrow[data-status="different"] .itd-day-chip` 은 수 · 표식이 아니라 상태 표시다. 고치지 않았다(기준선으로 잠금 — 분봉 화면 조각에서 본다) |
| 변이 하네스의 함정 | 같은 길이의 변이를 같은 초 안에 쓰면 파이썬 바이트코드 캐시(mtime 초 · 크기)가 앞 변이의 코드를 다시 쓴다 — 첫 실행의 짝수 번째 결과가 엇갈렸다. `-B` 와 pyc 삭제로 다시 돌렸다(32 / 32) |

### 2.7 구현하며 정한 것 · 잰 것 (U0-d · 2026-11-20)
| 무엇 | 정한 것 · 까닭 |
|---|---|
| 꼴 | 스크립트 다섯(`measure` · `interact` · `numprobe` · `focusprobe` · `csscov`) + 배관 하나(`lib.mjs` — 주소 · 로그인 · 브라우저 · 맥락). ★재는 논리는 옮기며 바꾸지 않았다★(기준선과 견줄 수 있어야 한다) — 바꾼 것은 배관과 아래 셋뿐이다 |
| 더한 값 하나 | 표의 `fullInView`(위아래가 다 보이는 줄). 설계 문서의 '다 보이는 줄 2'는 그림에서 센 값이었다 — 이제 스크립트가 잰다(스크리너 1440 × 900: 2 · 걸친 줄 3 — 같다) |
| 초점 확인 둘을 하나로 | 겉모습 견주기와 늦게 뜨는 고리(`--delay`)를 한 스크립트로. 경로 · 선택자를 인자로 받는다. 기본 목록에서 머리 줄의 찾기 칸을 뺐다(이 도구는 셸 안의 요소에 닿지 않는다 — 감사 때도 '닿지 못함'이었다) |
| 낡은 조작 하나를 고침 | `interact` 의 '지표 모두 보기'는 감사 때부터 닿지 못했다(그런 글자의 단추가 없다 — 실제 조작 요소는 `.rs-all > summary` '전체 지표'). 선택자로 고쳐 22 조작이 모두 돈다 |
| 로그인 | 주소 · 계정은 환경변수(`UX_BASE_URL` · `UX_USER` · `UX_PASSWORD`), 기본값은 로컬 mock 서버의 고정물(e2e · `scripts/readme-shots` 와 같은 값). 토큰과 응답 몸은 찍지 않는다 — 실패하면 상태 코드만 |
| 다시 잰 값(스크리너 · 1440 × 900 · 라이트) | DOM 1,687 → ★1,688★(+1 = U0-b 의 첫 그림 전 조각 `<script>` 하나) · 표 머리 y 745 → 745 · 줄 56px · 걸친 줄 3 · 다 보이는 줄 2 · 24px 미만 2 · 이름 없음 0 · 글자 크기 8가지 — 그대로. 첫 화면 전송량 JS 494,479 → 494,988 B(+509) · CSS 120,204 → 120,975 B(+771 — 토큰 블록과 견본 규칙) |

### 2.8 구현하며 정한 것 · 찾은 것 (U0-e · 2026-11-20)
| 무엇 | 정한 것 · 까닭 |
|---|---|
| 걷은 파일은 13 | 계획의 열둘 + `shared/ui/shadcn/popover.tsx` — 가져다 쓰던 것이 걷는 `EvidenceDrawerPanel` 하나뿐이었다(§2.4 의 '서로'에 든다). 다시 센 가져오기 그래프: 열셋 모두 `app/dev/ui/page.tsx`(와 서로)만 가져갔다 |
| 남긴 표본 | 제품이 쓰는 것만 — kit 7 · States 5 · `EvidenceBadge` · tx 10(표본 46 → 23) · 서식 함수 표 · 단과 밀도 · Card · Badge · Dialog(shadcn 표본 3 → 2) |
| ★롱숏 집중도 표본은 남겼다★ | `concentration()` · `exposureLegs()` 는 제품(`widgets/portfolio-graph/NodeResultPanel.tsx`)이 쓴다 — 숏을 버리지 않는 식(F3)의 시험은 그대로다. 걷은 것은 `AllocationMap`(제품이 그리지 않는 부품)과 그 스트립 시험 하나다 |
| 죽은 클래스의 판정 | 걷은 파일의 글자에 나온 낱말 가운데 CSS 선택자인 것 114 → 남은 `src` 의 어디에도 낱말로 없고(주석 제외) · 지어 붙이는 꼴(`접두-${…}`)도 없는 것 37. 뜻이 넓은 이름 넷은 하나씩 확인했다: `card-md` · `skeleton` · `tabular-nums` 는 걷음 · ★`primary` 는 뺌★(`.brun-btn.primary` — 걷은 파일의 것이 아니다. 그려지지 않는 규칙이지만 목록 밖이라 적어만 둔다) · `tev-drawer-*` 다섯은 `tev-${kind}`(네 값)로는 만들어지지 않아 걷음 |
| 걷은 CSS | 규칙 72 + 선택자 조각 1 + 이번에 고아가 된 `@keyframes` 넷(`a11-grow` · `flash-bull` · `flash-bear` · `skeleton-shimmer`) + 그 규칙만 설명하던 주석. 다크 생성 구역은 생성기로 다시 만들었다(규칙 104 → 99 · 선언 132 → 123) |
| `.ca-scen-card` 는 셋 | 계획은 `.bull` · `.bear` 둘이었다. 브라우저에서 보니 `.base` 까지 셋 모두 라이트 · 다크에서 `border-top: 0px none`(늘 `.ci .ca-scen-card { border: 0 }` 에 덮인다 · 그리는 곳은 기업 화면 하나) — 같은 까닭이라 함께 걷었다 |
| ★쓰이지 않는 토큰은 걷지 않았다★ | 글자로 세면 138(앞 네 `:root` 블록 밖에서만 정의된 것 92)이다. 그러나 이름을 실행 중에 짓는 가족이 여섯 있다(`--pg-port-*` · `--pg-band-*` · `--itd-mr-s*` · `--cat-*` · `--mc-c-*` · `--mc-lv-*`) — 글자로는 '쓰임 0'을 확정할 수 없다(§2.4 의 조건을 채우지 못한다). 가족마다 실행해서 확인해야 하고, 그 가족을 가진 화면 조각의 일이다 |
| 탐색 인덱스 | `globals.css` 머리의 줄 범위 85줄을 제목 글자로 다시 맞췄다 — 이번 삭제 전부터 뒤쪽이 최대 262줄 어긋나 있었다(앞쪽 세 줄은 맞았다). 걷은 절(39) 한 줄은 뺐다. 접두 칸은 다시 세지 않았다 |
| 의존성 | `@radix-ui/react-popover` 는 가져오는 곳이 0 이 됐다. `package.json` · 잠금 파일은 건드리지 않았다(잠금 파일 변경은 따로 한다) |
| 회귀 스펙이 잡은 내 실수 | 카탈로그의 Dialog 단추(걷은 shadcn Button 의 자리)에 다크 전환 단추의 클래스를 다시 썼다 → 스펙의 `.devui-darktoggle` 이 요소 둘을 집어 실패(29개 파일 중 493 통과 · 1 실패). 겉은 같은 규칙을 쓰고 이름만 가른 새 클래스 `.devui-btn` 으로 고쳤다 — 있는 클래스는 E2E 계약이라 다른 요소에 다시 쓰지 않는다 |

### 2.9 구현하며 정한 것 (U0-f · 2026-11-20)
| 무엇 | 정한 것 · 까닭 |
|---|---|
| 꼴 | `skill-creator` 의 꼴 — 머리(`name` · `description`) + 본문 148줄(권고 500줄 아래) · 묶음 자원 없음 |
| `description` | 무엇을 하는가 + ★언제 읽는가★를 한 칸에. 화면 · CSS · 표 · 색 · 밀도 등을 건드리면 '디자인'이라는 말이 없어도 읽게 적었다(스킬은 덜 불리는 쪽이 흔한 실패다). 서버만 고치는 일은 뺐다 |
| 본문 | ★요약★이다 — 원천은 ADR 007 · 설계 §9 · 가드 시험이고, 어긋나면 원천이 옳다고 머리에 적었다. 단 · 밀도 토큰 · 척도의 값은 옮겨 적었다 → ADR 의 값이 바뀌면 이 파일도 함께 고친다(★자동으로 걸리지 않는다★ — 시험이 없다) |
| 담은 것 | 고치기 전에 정할 셋(단 · 경로 표 · 건드리지 않는 것) · 일의 순서 · 화면을 단에 올리는 걸음 넷 · 토큰 · 색 · 수와 표 · 움직임 · ★가드가 실패하면 할 일 표★ · 돌리는 명령 · U0 에서 실제로 밟은 것 넷 · 주장의 범위 |
| 평가 고리는 돌리지 않았다 | `skill-creator` 의 시험 실행 · 견주기 · `description` 다듬기는 하위 에이전트를 쓴다 — 받은 결정(하위 에이전트를 쓰지 않음)이라 하지 않았다. 스킬이 실제로 불리는지 · 불렸을 때 결과가 나아지는지는 ★미검증★이다 |
| 목록에 뜨는지 | 스킬 목록은 세션이 시작될 때 정해진다 — 다음 세션의 목록에 뜨는지는 ★미확인★ |
| 두 겹 중괄호 | 본문에 쓰지 않았다(인라인 `style` 의 예를 풀어 적음) — 틀로 읽히는 꼴을 피한다 |

## 3. 파일

| 조각 | 새로 만드는 것 | 고치는 것 |
|---|---|---|
| U0-a | `docs/decisions/adr-007-density-tiers-visual-language.md` · 이 문서 | `docs/decisions/adr-003-toss-visual-language-app-wide.md`(상태) · `docs/specs/2026-11-11-ui-terminology.md`(§3.31) · `CLAUDE.md`(프론트엔드 줄 — 99줄 그대로) · 설계 문서(머리 · §6 · §10) · `docs/superpowers/plans/2026-11-16-evidence-and-trader-ux.md`(§11) · `docs/HISTORY.md` |
| U0-b | `frontend/src/shared/ui/density/{density.ts,useDensitySync.ts,index.ts}` · `frontend/src/app/dev/density/page.tsx` · `frontend/src/app/dev/DensitySpecimen.tsx` · `frontend/e2e/density-logic.spec.ts` · `frontend/e2e/density.spec.ts` | `frontend/src/app/globals.css`(끝에만) · `frontend/src/app/layout.tsx`(조각 한 줄) · `frontend/src/widgets/layout/TerminalShell.tsx`(훅 한 줄) · `frontend/src/app/dev/ui/page.tsx`(견본 묶음) · `frontend/e2e/dev-ui.spec.ts`(견본 묶음이 `.devui-item` 수를 바꾸면) |
| U0-c | `tests/frontend_style_scan.py` · `tests/test_frontend_style_ratchet.py` | — |
| U0-d | `frontend/scripts/ux-measure/{measure,interact,numprobe,focusprobe,csscov}.mjs` · `README.md` | — |
| U0-e | — | 위 §2.4 의 파일(삭제) · `frontend/src/app/dev/ui/page.tsx` · `frontend/e2e/dev-ui.spec.ts` · `frontend/src/app/globals.css` · `frontend/src/entities/company/insightsModel.ts` · U0-c 의 기준선(내려간 값으로) |
| U0-f | `.claude/skills/alpha-ui/SKILL.md` | — |
| P0-1 | `frontend/e2e/skip-link.spec.ts` | `TerminalShell.tsx` · `globals.css` · `frontend/e2e/golden/light-styles.json`(다시 얼림) |
| P0-2 | `frontend/e2e/focus-ring.spec.ts` | `globals.css`(`transition: all` 일곱) · U0-c 의 기준선(7 → 0) |
| P0-3 | — | `frontend/src/widgets/trade-journal/TradeJournalView.tsx` · `frontend/e2e/trade-journal.spec.ts` |
| P0-4 | `frontend/e2e/kit-names.spec.ts` | `frontend/src/shared/ui/kit.tsx`(+ 문맥이 닿지 않는 호출부) |

## 4. 조각과 걸음

### U0-a 문서 (`7c2f91f`)
- [x] ADR 007 파일 · ADR 003 상태 '대체됨'(이어받는 것 명시) · 이 계획 문서
- [x] 용어집 §3.31(단 · 밀도 · 촘촘 · 보통 · 넉넉 · 자동 · 쓰지 않는 말)
- [x] CLAUDE.md 프론트엔드 줄에 ADR 007 가리킴(줄 수 99 그대로)
- [x] 받은 결정 기록: 설계 문서 머리 · §6 머리 · §10 / 묶음 계획 문서 §11 / HISTORY
- [x] 문서 시험 묶음 + 근거 대조 스크립트(줄 · 파일 근거 어긋남 0) → 커밋

### U0-b 토큰 + 장치
- [x] **빨강** — `e2e/density-logic.spec.ts`(순수): `parsePref` · `resolveDensity` 의 차례(표에 없음 → null ↔ 표에 있음 · `lock` · 손가락 화면 · 저장값 · 기본값 — 줄마다 짝) · `applyDensity`(둘 다 붙임 ↔ 둘 다 뗌) ·
  ★조각 = 순수 함수★(경로 × 저장값 × 손가락 화면 × 표 격자를 가짜 `document` · `localStorage` · `location` · `matchMedia` 에서 돌려 견줌) · 저장이 던져도 조각이 던지지 않음 · ★`TIER_ROUTES` 의 모든 줄이 허용 목록(개발 견본) 안★.
- [x] **빨강** — `e2e/density.spec.ts`(브라우저): 견본 상자의 줄 28 · 34 · 44px · 칸 여백 · 글자 · 조작 높이(짝: 속성 없는 상자 = 넉넉 기본값) · 단의 반경 4 · 12 · 20px · 단 안 `.num` 은 본문 글꼴(짝: 밖은 고정폭 그대로) ·
  잉크 강조(라이트 · 안쪽 다크 상자 — 짝: 강조 ≠ 하락색) · `/dev/density` 의 속성(저장값 없음 · 셋 · 깨진 값) · ★스크립트 청크를 막아도 속성이 붙는다★(조각이 한 일) · 손가락 화면은 저장값이 촘촘이어도 넉넉 ·
  화면 사이 이동(`/dev/density` → 제품 화면 → 뒤로: 뗌 → 다시 붙임) · ★제품 경로는 저장값이 있어도 속성 0★ · 견본 대비(라이트 · 다크 × 밀도 셋) · 촘촘한 견본의 누르는 것 ≥ 24px.
- [x] 실패를 본다(모듈 · 견본이 없어서) → 구현(`density.ts` → CSS 블록 → 견본 → 조각 · 훅) → 초록
- [x] 라이트 골든 13 라우트 변화 0(`dark-modules.spec.ts`) · 다크 생성 구역 `--check` · 카탈로그 스펙 · tsc · eslint
- [x] **변이**(각각 죽는지): 제품 경로를 표에 넣음 · 훅이 떼지 않음 · 조각이 저장값을 무시 · 손가락 화면 무시 · `lock` 무시 · `.dark` 짝에서 별칭 빠짐 · 속성 선택자의 값 하나 바꿈 · `[data-tier] .num` 규칙 삭제
- [x] 견본 스크린샷(밀도 셋 × 라이트 · 다크) 검수 → 커밋

### U0-c 가드
- [x] 검사기 `tests/frontend_style_scan.py`(주석 벗기기 · 규칙 나누기 · 블록 종류 가르기 · 래칫별 세기 — 순수 함수 · 입력은 글)
- [x] **빨강** — 래칫마다 ① 심은 위반을 센다 ② 허용된 꼴은 세지 않는다 ③ 지금 저장소 ≤ 기준선 ④ 지금 저장소 = 기준선(낡은 기준선 실패) — 기준선 없이 먼저 돌려 실패를 본다
- [x] 기준선을 검사기가 센 값으로 박고 초록 · 설계 문서의 수와 다른 것은 까닭을 적는다
- [x] **변이**: 검사기의 각 세기를 0 으로 · 척도 집합에서 값 하나 빼기/더하기 · 주석 벗기기 끄기 — 시험이 죽는지
- [x] ruff · 커밋

### U0-d 재는 스크립트
- [x] 스크립트 다섯을 `frontend/scripts/ux-measure/` 로(주소 · 출력 자리 · 로그인은 인자 · 환경변수 · 토큰은 찍지 않는다 · 기본값은 로컬 고정물) + `README.md`(무엇을 재나 · 어떻게 읽나 · 한계)
- [x] 스크리너를 다시 재어 기준선과 견준다(다 보이는 줄 · DOM 수 · 표 머리 y) — 다르면 문서가 아니라 차이의 까닭부터 → 커밋

### U0-e 카탈로그 + 걷기
- [x] 쓰임 0 재확인(가져오기 그래프 · 클래스 쓰임 · 스펙 참조) → 걷을 목록과 남길 목록을 확정
- [x] 첫 화면 JS 전 값 재기 → 삭제 · 카탈로그 · 스펙 · CSS → tsc · eslint · 빌드 · 카탈로그 스펙 · 라이트 골든 변화 0 · 래칫 기준선 내림 → 첫 화면 JS 후 값 → 커밋

### U0-f 프로젝트 전용 UI 스킬
- [x] `skill-creator` 로 꼴을 맞춰 `.claude/skills/alpha-ui/SKILL.md` — 규칙의 요약 + 원천(ADR 007 · 가드 시험)을 가리킴 → 커밋(다음 세션의 목록에 뜨는지는 미확인으로 적는다)

### U0 끝 게이트
- [x] 격리 worktree: ruff · 전체 pytest 한 번 · tsc · eslint(FSD) · 다크 `--check` · 빌드 · ★전체 E2E★ · 문서 시험 · `golden-diff` 로 13 라우트 변화 0 → HISTORY → 푸시 → CI
  - 결과(2026-11-20): 전체 E2E 1,714 통과 · 4 건너뜀 · 실패 0(`a2f0402`) · 전체 pytest 11,844 통과 · 11 건너뜀 · 실패 0(`6a3dec2` · 격리 worktree) · 골든 파일은 U0 앞과 같다(다시 얼리지 않았다)

### 접근성 P0 넷 (각각 빨강 → 초록 → 변이 → 커밋)
- [x] **P0-1 건너뛰기 링크** — 셸의 첫 요소 `본문으로 건너뛰기`(초점이 갈 때만 보임 · 전환 없음) → 본문으로 초점. 스펙: 첫 Tab 에 보인다 · Enter 뒤 초점이 본문 · 본문 첫 조작 요소까지 2걸음 이하 ·
  ★짝: 셸 없는 화면(첫 화면 · 로그인 · 고객 화면)에는 없다★ · 라이트 골든은 `frame:` 만 달라짐.
  - 결과(2026-11-20): 스펙 7 통과 · 회귀 11개 파일 156 통과 · 변이 12 / 12 죽음. ★계획과 달라진 것 셋★ — ① 링크는 셸 뿌리가 아니라 머리 줄 안의 첫 요소다(머리 줄이 제 겹침 맥락 z-index 100 을 가져 밖에 두면 가린다) → 골든의 범위가 `frame:` 이 아니라 `shell:` ② 골든을 다시 얼리지 않고 키 하나(`shell:a.tx-skip`)만 더했다(다시 얼리면 무관한 키가 쓸려 온다) ③ 다크는 잉크 채움이 아니라 잉크 글자 + 잉크 선이다(다크 검사가 잉크 채움을 '밝은 판'으로 잡았다 — 주 단추의 다크 꼴은 U1 에서 정한다)
- [ ] **P0-2 늦는 초점 고리** — `transition: all` 일곱을 실제로 바뀌는 속성만으로. 스펙: 자판 초점 → 다음 프레임에 고리가 끝값 · 래칫 7 → 0 · 라이트 골든 변화 0.
- [ ] **P0-3 숨긴 파일 입력** — 탭 순서에서 뺀다(보이는 `파일 선택` 단추가 자판 길). 스펙: 탭 걷기에 보이지 않는 걸음 0 · 짝: 단추로 파일 대화가 열린다 · 기존 올리기 시험 그대로.
- [ ] **P0-4 이름 없는 요소** — 스위치와 숫자 칸이 옆의 보이는 글자를 이름으로 잇는다(`aria-labelledby`). 스펙: `/backtest` 의 이름 없는 조작 요소 0 · 이름 = 보이는 글자 · 짝: 이름이 서로 다르다 · 요청 골든 그대로.
- [ ] 게이트: 관련 E2E + ★전체 E2E 한 번★ · tsc · eslint · 빌드 · 문서 시험 → 스크린샷 검수(건너뛰기 링크의 초점 상태 라이트 · 다크 · 390px) → HISTORY → 푸시 → CI → PR 본문 → 보고

## 5. 하지 않는 것

제품 화면의 겉모습 변경 · 어느 제품 경로에도 단을 달지 않음(U1 부터) · 밀도 전환 단추(U6) · 공용 표(U1) · 옛 강조 토큰(`--tx-cta` · `--tx-blue`)의 값 · `:root` 앞 네 블록 편집 · 기존 클래스 이름 바꾸기 ·
새 의존성 · 서버 코드 · 요청의 꼴 · hooks 설정과 플러그인 설치(사용자 결정) · 하위 에이전트 · 병합 · 리베이스 · 강제 푸시 · 가드가 드러낸 기존 위반을 이 묶음에서 고치기(기준선으로 잠그고 화면 조각에서 줄인다).

## 6. 주장의 범위

- U0 가 거는 것은 구조다(`structural`) — 토큰과 장치가 뜻대로 돌고, 끄면 지금 화면 그대로이며, 날 값이 더 늘지 않는다는 것까지다. ★화면이 읽기 쉬워졌다는 증거가 아니다★(제품 화면은 아직 바뀌지 않는다).
- 가드는 글자를 훑는다 — 인라인 스타일 · 실행 중에 지은 클래스 · Tailwind 유틸리티로 적은 값은 보지 못한다(그 한계를 시험 파일 머리에 적는다).
- P0 넷은 이름 · 역할 · 초점 순서를 자동 검사로 거는 것까지이며, 실제 낭독기로는 이 환경에서 듣지 못한다.
- 손가락 화면은 Chromium 의 흉내로만 본다(실제 기기 아님).
