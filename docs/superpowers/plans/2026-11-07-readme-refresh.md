# README 새로 고침 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** README 의 글과 그림을 지금 앱(React Flow 12 캔버스 · Claude 설계 보조 · 고객 관리)에 맞추고, 그림을 다시 찍는 스크립트를 저장소에 남긴다.

**Architecture:** 설계 `docs/superpowers/specs/2026-11-07-readme-refresh-design.md`. 앱 코드 변경 0. `frontend/scripts/readme-shots/shoot.mjs` 가
제 포트·새 DB 로 백엔드와 프론트를 띄우고, Playwright 로 장면을 만들어 `docs/images/readme/*.png` 를 쓰고, 제가 띄운 것만 끈다. README 는 구성을 두고 고쳐 쓴다.

**Tech Stack:** Node 22 · `@playwright/test`(chromium) · Next 14 `next start` · FastAPI(uvicorn, `KIS_USE_MOCK=1`) · Anthropic API(프록시가 키를 넣음).

**사용자 추가 조건(2026-11-07):** ★그림에 '한국투자증권' 문구가 드러나지 않게★. 앱의 '내 계좌' 머리말·빈 상태 글에 그 이름이 있다(`MyAccountView.tsx:32·91`).
앱은 바꾸지 않고, 찍기 직전 화면 글자에서 그 이름(과 약칭 `KIS`)을 '증권사'로 가린 뒤, ★남아 있으면 그 그림을 쓰지 않고 실패★한다.

---

### Task 1: Claude 키를 환경에 (보안 입력 · Task 4 의 '키 없이 한 번' 뒤에)

- [ ] `get_environment` 로 이 세션 환경을 본다(어디에 저장되는지 확인).
- [ ] 사용자에게 한 문장: "AI 그림을 실제 응답으로 찍으려고 api.anthropic.com 의 키를 보안 입력 창으로 받습니다(채팅에 붙이지 마세요)."
- [ ] `request_credential`(host `api.anthropic.com` · header_name `x-api-key` · prefix 없음 · display_name "Anthropic API key").
- [ ] 확인: `curl -s -o /dev/null -w '%{http_code}' https://api.anthropic.com/v1/models -H 'x-api-key: placeholder' -H 'anthropic-version: 2023-06-01'` → `200`(저장 전 401). 프록시가 늦으면 1분 뒤 한 번 더.

### Task 2: 스크립트 뼈대 — 서버 수명·브라우저·상표 가림·쓰기

**Files:** Create `frontend/scripts/readme-shots/shoot.mjs`, `frontend/scripts/readme-shots/README.md`

- [ ] 서버 수명(진단 도구 `run.sh` 규율):
  - 포트 `SHOTS_WEB_PORT`(3900)·`SHOTS_API_PORT`(8900)가 비어 있지 않으면 `포트 N 을 이미 쓰고 있어요` 로 끝(끄지 않음). `frontend/.next` 없으면 `먼저 npx next build`.
  - 새 DB: `os.tmpdir()/readme-shots-<시각>.db`. 백엔드 env: `KIS_USE_MOCK=1` · `DATABASE_URL=sqlite:////…` · `BROKER_CRED_KEY=<Fernet 키 — 실행마다 새로 만듦>` · `ANTHROPIC_API_KEY`
    (부모 env 에 없으면 `placeholder` — 실제 키는 프록시가 넣고, 없으면 AI 가 사유를 말한다).
  - `spawn(..., { detached: true })` 로 띄우고 pid 를 기억 → `finally` 에서 `process.kill(-pid)`(제 무리만). 헬스: `/api/v1/macro/health` 200 · `http://localhost:3900/` 200.
- [ ] 브라우저: `playwright.config.ts` 와 같은 규칙(`PW_CHROMIUM_PATH` → `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` 있으면 그것). 뷰포트 1440×900 · 배율 1 ·
  `localStorage`: `alpha_theme=light` · `alpha_pg_welcomed=1`.
- [ ] 로그인: `POST /api/backend/api/v1/auth/login {admin, frm123!}` → `localStorage["project-alpha.auth-token"]`.
- [ ] 상표 가림(`redact`): 페이지에 MutationObserver 를 걸어 글자 노드의 `한국투자증권(\(KIS\))?` · `\bKIS\b` → `증권사`(처음 한 번 + 바뀔 때마다). 앱 바깥에서만, 그림을 위해서만.
- [ ] 쓰기(`shot(page, name)`): `document.body.innerText` 에 `한국투자증권`·`KIS` 가 있으면 `throw new Error(name + ": 상표 문구가 남아 있어요")`. 없으면
  `docs/images/readme/<name>.png`(뷰포트) 저장 · 크기 기록.
- [ ] `--only a,b` 면 그 장면만. 끝에 쓴 그림 목록·크기 출력. 실패하면 0 아닌 값.
- [ ] `node --check scripts/readme-shots/shoot.mjs` · `npx eslint scripts/readme-shots/shoot.mjs` → 0.

### Task 3: AI 아닌 장면

각 장면은 `page.goto` → 내용이 보일 때까지 기다림 → `redact` → `shot`. 고객 셋(별칭: '은퇴 준비 고객' · '자녀 교육 자금' · '사업 운영 자금' — 개인 정보 없음)을
`POST /api/backend/api/v1/pb/clients {alias, risk_tolerance}` 로 만든다.

- [ ] `canvas`: `/allocation` → `.pg-node` 보임 → `.pg-run` → `/allocation/graph/run` 응답 → 맞춰 보기 → 오른쪽 이야기 탭.
- [ ] `canvas-wire`: 같은 캔버스에서 선 하나를 고름(`.react-flow__edge` 클릭 이벤트) → 오른쪽 링크 탭 + 선 도구줄.
- [ ] `canvas-simple`: 간단히 보기로 전환.
- [ ] `canvas-workspace`: `.pg-view-open` → `[data-view="lanes"]` 켬 · 전략 노드를 골라 '전략으로 묶기' · 미니맵 보임 · 맞춰 보기.
- [ ] `home` `/dashboard` · `screener` `/screener`(결과 표) · `screener-sheet`(첫 행 클릭) · `backtest-editor` `/backtest` ·
  `backtest-result`(`.tbt-run` → 결과 화면까지 기다림 — 기본 설정 실제 실행) · `macro` `/macro` · `insights` `/insights?code=005930` · `risk` `/risk-tools`.
- [ ] `my-account`: `POST /api/backend/api/v1/broker-accounts {label:"내 모의 계좌", app_key, app_secret(지어낸 값), account_no:"00000000", is_paper:true}` →
  `/my-account`. ★실제 경로로 안 되면★(금고·잔고 실패) `my-account.spec.ts` 와 같은 응답을 정하고 HISTORY 에 적는다.
- [ ] `clients` `/clients?client=<은퇴 준비>` · `client-sheet`: `/allocation?client=<cid>&new=review` → `.pg-run` → `.pg-client-chip .pg-client-sheet` → `.cs-sheet`.
- [ ] 실행(키 없이도 됨): `node scripts/readme-shots/shoot.mjs --only canvas,home,my-account` → 그림 셋 · 상표 없음 · 포트 비워짐(`fuser 3900/tcp 8900/tcp` 빈 출력).

### Task 4: AI 문 + AI 장면

- [ ] AI 문: 첫 AI 장면 전에 로그인 토큰으로 `POST /api/backend/api/v1/assist/canvas/suggest`(지금 캔버스 문서)를 한 번 → `available !== true` 면
  `AI 가 답할 수 없어요: ${reason} — AI 그림을 쓰지 않았어요` 로 실패(AI 그림 0장).
- [ ] `ai-suggest`: 캔버스 계산 뒤 `.pg-ai-ask` → `.pg-ghost[data-source="claude"]` 보임 → 맞춰 보기.
- [ ] `ai-draft`: `.pg-left-tab[data-tab="say"]` → `.pg-say-text` 에 문장("삼성전자·SK하이닉스·NAVER 로 3년 수익률을 보고 위험을 고르게 나눠 비중을 정해 줘") + Enter →
  `.pg-say-item` 보임 · `.pg-draft-node` 보임.
- [ ] `ai-ask`: 계산 뒤 `.pg-node[data-node-id="optimizer"]` 클릭 → `.pg-ask-text` 에 "이 비중은 어떤 입력에서 나왔나요?" + Enter → `.pg-ask-turn` 의 답·`.pg-ask-chip`.
- [ ] `ai-story`: 계산 뒤 이야기 탭 → `.pg-ai-story-ask` → `.pg-ai-para` 보임.
- [ ] ★키를 저장하기 전에(Task 1 보다 먼저)★ 한 번: `node scripts/readme-shots/shoot.mjs --only ai-suggest` → AI 그림 0 + 사유와 함께 0 아닌 값으로 끝남 확인.
- [ ] 키로 전체: `node scripts/readme-shots/shoot.mjs` → 그림 19장.

### Task 5: 그림 보기·보내기

- [ ] 그림마다 Read 로 직접 본다: 새 메뉴('고객') · 연습용 표시 · 상표 없음 · 개인 정보 없음 · AI 그림은 출처 칩("AI 추천" 등)·근거 칩이 보임 · 잘림 없음.
- [ ] `SendUserFile`(proactive) 로 보내고 계속 진행.

### Task 6: README 고침 (설계 §3)

**Files:** Modify `README.md`

- [ ] 머리(Claude 배지 · 한 줄 소개) · 설계 목적(AI 한 줄) · 워크플로(고객별 점검) · 캔버스(화면 구성 표 · React Flow 12 작업 공간 절 · 기존 절 고침 · 그림 셋) ·
  새 절 AI 설계 보조(다섯 기능 · 안전장치 · 그림 2×2 · 캡션) · 주요 도구에 고객 관리(그림 둘 · 유통 관문) · 실행 방법(`ANTHROPIC_API_KEY` · 그림 다시 찍기 한 줄 · 진단 도구 링크) ·
  기술 스택 · 문서 표.
- [ ] 글 규칙: 합니다체 · 세는 수 0 · 금지 표현 0 · em-dash 0 · 실제 화면 이름.

### Task 7: README 점검·미리보기

- [ ] 링크·그림 경로: `python3` 로 README 의 `](…)`·`src=` 상대 경로가 모두 실재하는지 → 빠진 것 0.
- [ ] `grep -nE "검증됨|입증됨|견고함|프로덕션 레디|투자 우위|더 나은 전략" README.md` → 0 줄 · `grep -c "—" README.md` → 0.
- [ ] README 의 따옴표 친 화면 이름(예: '말로 설계'·'AI 에게 묻기')이 `frontend/src` 에 있는지 grep.
- [ ] 미리보기: `marked`(있으면) 또는 python `markdown` 으로 HTML → Playwright 로 전체 페이지 그림 → 보낸다.

### Task 8: 기록·커밋

- [ ] 스크립트 eslint · `node --check` · 화면을 읽는 pytest(`fe_py.txt`) 통과.
- [ ] HISTORY 'README 새로 고침' — 무엇 · 왜(사용자 요청·결정 셋·상표 조건) · 그림 찍은 법(스크립트 · 새 DB · 실제 백테스트 · 내 계좌 경로) · ★AI 그림은 실제 Claude 응답★ ·
  상표 가림(앱은 그대로 · 그림에서만) · 하지 않음 · 게이트(앱 코드 변경 0 → `make all` 생략 사유).
- [ ] 명시 파일 커밋(README.md · docs/images/readme/*.png · frontend/scripts/readme-shots/* · docs/HISTORY.md · 이 계획) → 푸시(2·4·8·16초).

---

## 상태 (2026-11-08)

- 끝남: Task 2·3·5(AI 아닌 그림 15장)·6·7·8. Task 4 는 '키 없이 한 번'만(AI 그림 0 · 사유 · exit 1 확인).
- ★미룸 — AI 그림 4장(Task 1·4)★: 이 세션은 실행 중이라 새 환경('Project-Alpha' · `api.anthropic.com` 허용 · 사용자 결정으로 키는 그 환경에만)으로 옮길 수 없었다.
  다음 세션을 그 환경에서 열고: 키 저장(`request_credential` · `x-api-key`) → `cd frontend && npm ci && npx next build && node scripts/readme-shots/shoot.mjs --only ai-suggest,ai-draft,ai-ask,ai-story`
  → 그림을 직접 봄 → README 'AI 설계 보조 (Claude)' 절에 2×2 표 · 캡션("AI 답은 연습용 데이터 위에서 받은 실제 Claude 응답입니다") → HISTORY → 커밋.
