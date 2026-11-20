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
| `useDensitySync(path)` | 셸이 부른다 | 경로 · 저장값 · 손가락 화면 여부가 바뀔 때마다 `html` 의 속성을 맞춘다 — 표에 없는 경로로 가면 뗀다 |

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
| 토큰 블록 밖 hex | `:root` · `.dark` 블록과 생성 구역 밖의 `#rgb` · `#rrggbb` | 규칙에 `#ff0000` +1 · 짝: `:root` 블록 안의 hex 는 0 |
| 척도 밖 중단점 | `@media` 의 `min-width` · `max-width` px 가운데 척도(480 · 640 · 900 · 1280 · 1600 과 그 −1) 밖 | `(max-width: 777px)` +1 · 짝: `640px` · `1279px` 는 0 |
| `transition: all` | 선언 수 | 하나 심으면 +1 · 짝: `transition: color .15s` 는 0 |
| TSX 의 `title=` | `frontend/src` 의 요소 `title=` 속성(부품 prop 이름 `title` 은 세지 않는다 — 소문자 태그만) | `<span title="…">` +1 · 짝: `<Section title="…">` 는 0 |
| 낱 `<table>` | `<table` 을 그리는 파일의 ★목록★ | 새 파일에 `<table>` 을 심으면 실패 · 짝: 목록 안의 파일은 통과 · 목록의 파일이 표를 걷었는데 목록에 남아도 실패 |
| 색의 뜻 | 등락색(`--tx-up` · `--tx-down` 과 `-ink` · `-soft`)을 쓰는 선택자의 허용 목록 · 상태색(`--tx-danger` · `--tx-warn` · `--tx-ok`)이 수 칸 선택자(`.num` · `td.num` · `[data-num]`)에 쓰이면 실패 | 수 칸에 `color: var(--tx-danger)` 를 심으면 실패 · 허용 목록 밖 선택자에 `--tx-up` 을 심으면 실패 · 짝: 목록 안은 통과 |

기준선은 ★검사기가 센 값★으로 시험 파일에 박는다(설계 문서의 수는 다른 스크립트가 셌다 — 다르면 까닭을 HISTORY 에 적는다). 줄었는데 기준선을 내리지 않으면 실패한다.

### 2.4 걷는 것 (결정 D7 — 걷기 전에 쓰임 0 을 다시 센다)
- 파일: `frontend/src/shared/ui/{primitives,feedback,MiniViz,AllocationMap,SectionHead,EvidenceDrawer,EvidenceDrawerPanel}.tsx` · `frontend/src/shared/ui/shadcn/{table,button,input,progress,slider}.tsx`.
  ★조건★: 가져다 쓰는 곳이 `app/dev/ui/page.tsx`(와 서로)뿐일 때만. 하나라도 제품 파일이 쓰면 그 파일은 남기고 까닭을 적는다.
- 그 파일만 쓰던 CSS 규칙(쓰는 곳 0 을 `frontend/src` · `frontend/e2e` 전체에서 확인한 클래스만) · 쓰이지 않는 함수 둘(`toneColor` · `pctColor`) · 그려지지 않는 규칙 둘(`.ca-scen-card.bull` · `.bear`) · `:root` 앞 네 블록 ★밖★의 쓰이지 않는 토큰.
- 카탈로그와 그 스펙(`dev-ui.spec.ts`)은 함께 고친다 — 남는 것은 제품이 쓰는 층(kit · States · evidence · tx · 형식 함수 · 노출)과 새 견본.

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

### U0-a 문서 (이 커밋)
- [ ] ADR 007 파일 · ADR 003 상태 '대체됨'(이어받는 것 명시) · 이 계획 문서
- [ ] 용어집 §3.31(단 · 밀도 · 촘촘 · 보통 · 넉넉 · 자동 · 쓰지 않는 말)
- [ ] CLAUDE.md 프론트엔드 줄에 ADR 007 가리킴(줄 수 99 그대로)
- [ ] 받은 결정 기록: 설계 문서 머리 · §6 머리 · §10 / 묶음 계획 문서 §11 / HISTORY
- [ ] 문서 시험 묶음 + 근거 대조 스크립트(줄 · 파일 근거 어긋남 0) → 커밋

### U0-b 토큰 + 장치
- [ ] **빨강** — `e2e/density-logic.spec.ts`(순수): `parsePref` · `resolveDensity` 의 차례(표에 없음 → null ↔ 표에 있음 · `lock` · 손가락 화면 · 저장값 · 기본값 — 줄마다 짝) · `applyDensity`(둘 다 붙임 ↔ 둘 다 뗌) ·
  ★조각 = 순수 함수★(경로 × 저장값 × 손가락 화면 × 표 격자를 가짜 `document` · `localStorage` · `location` · `matchMedia` 에서 돌려 견줌) · 저장이 던져도 조각이 던지지 않음 · ★`TIER_ROUTES` 의 모든 줄이 허용 목록(개발 견본) 안★.
- [ ] **빨강** — `e2e/density.spec.ts`(브라우저): 견본 상자의 줄 28 · 34 · 44px · 칸 여백 · 글자 · 조작 높이(짝: 속성 없는 상자 = 넉넉 기본값) · 단의 반경 4 · 12 · 20px · 단 안 `.num` 은 본문 글꼴(짝: 밖은 고정폭 그대로) ·
  잉크 강조(라이트 · 안쪽 다크 상자 — 짝: 강조 ≠ 하락색) · `/dev/density` 의 속성(저장값 없음 · 셋 · 깨진 값) · ★스크립트 청크를 막아도 속성이 붙는다★(조각이 한 일) · 손가락 화면은 저장값이 촘촘이어도 넉넉 ·
  화면 사이 이동(`/dev/density` → 제품 화면 → 뒤로: 뗌 → 다시 붙임) · ★제품 경로는 저장값이 있어도 속성 0★ · 견본 대비(라이트 · 다크 × 밀도 셋) · 촘촘한 견본의 누르는 것 ≥ 24px.
- [ ] 실패를 본다(모듈 · 견본이 없어서) → 구현(`density.ts` → CSS 블록 → 견본 → 조각 · 훅) → 초록
- [ ] 라이트 골든 13 라우트 변화 0(`dark-modules.spec.ts`) · 다크 생성 구역 `--check` · 카탈로그 스펙 · tsc · eslint
- [ ] **변이**(각각 죽는지): 제품 경로를 표에 넣음 · 훅이 떼지 않음 · 조각이 저장값을 무시 · 손가락 화면 무시 · `lock` 무시 · `.dark` 짝에서 별칭 빠짐 · 속성 선택자의 값 하나 바꿈 · `[data-tier] .num` 규칙 삭제
- [ ] 견본 스크린샷(밀도 셋 × 라이트 · 다크) 검수 → 커밋

### U0-c 가드
- [ ] 검사기 `tests/frontend_style_scan.py`(주석 벗기기 · 규칙 나누기 · 블록 종류 가르기 · 래칫별 세기 — 순수 함수 · 입력은 글)
- [ ] **빨강** — 래칫마다 ① 심은 위반을 센다 ② 허용된 꼴은 세지 않는다 ③ 지금 저장소 ≤ 기준선 ④ 지금 저장소 = 기준선(낡은 기준선 실패) — 기준선 없이 먼저 돌려 실패를 본다
- [ ] 기준선을 검사기가 센 값으로 박고 초록 · 설계 문서의 수와 다른 것은 까닭을 적는다
- [ ] **변이**: 검사기의 각 세기를 0 으로 · 척도 집합에서 값 하나 빼기/더하기 · 주석 벗기기 끄기 — 시험이 죽는지
- [ ] ruff · 커밋

### U0-d 재는 스크립트
- [ ] 스크립트 다섯을 `frontend/scripts/ux-measure/` 로(주소 · 출력 자리 · 로그인은 인자 · 환경변수 · 토큰은 찍지 않는다 · 기본값은 로컬 고정물) + `README.md`(무엇을 재나 · 어떻게 읽나 · 한계)
- [ ] 스크리너를 다시 재어 기준선과 견준다(다 보이는 줄 · DOM 수 · 표 머리 y) — 다르면 문서가 아니라 차이의 까닭부터 → 커밋

### U0-e 카탈로그 + 걷기
- [ ] 쓰임 0 재확인(가져오기 그래프 · 클래스 쓰임 · 스펙 참조) → 걷을 목록과 남길 목록을 확정
- [ ] 첫 화면 JS 전 값 재기 → 삭제 · 카탈로그 · 스펙 · CSS → tsc · eslint · 빌드 · 카탈로그 스펙 · 라이트 골든 변화 0 · 래칫 기준선 내림 → 첫 화면 JS 후 값 → 커밋

### U0-f 프로젝트 전용 UI 스킬
- [ ] `skill-creator` 로 꼴을 맞춰 `.claude/skills/alpha-ui/SKILL.md` — 규칙의 요약 + 원천(ADR 007 · 가드 시험)을 가리킴 → 커밋(다음 세션의 목록에 뜨는지는 미확인으로 적는다)

### U0 끝 게이트
- [ ] 격리 worktree: ruff · 전체 pytest 한 번 · tsc · eslint(FSD) · 다크 `--check` · 빌드 · ★전체 E2E★ · 문서 시험 · `golden-diff` 로 13 라우트 변화 0 → HISTORY → 푸시 → CI

### 접근성 P0 넷 (각각 빨강 → 초록 → 변이 → 커밋)
- [ ] **P0-1 건너뛰기 링크** — 셸의 첫 요소 `본문으로 건너뛰기`(초점이 갈 때만 보임 · 전환 없음) → 본문으로 초점. 스펙: 첫 Tab 에 보인다 · Enter 뒤 초점이 본문 · 본문 첫 조작 요소까지 2걸음 이하 ·
  ★짝: 셸 없는 화면(첫 화면 · 로그인 · 고객 화면)에는 없다★ · 라이트 골든은 `frame:` 만 달라짐.
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
