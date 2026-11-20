# 화면 재기 (UI/UX 측정 도구)

화면을 고치기 **전과 후**를 같은 자로 재는 스크립트 다섯이다. 2026-11-20 의 UI/UX 감사
(`docs/superpowers/specs/2026-11-20-uiux-professionalization-design.md` §2)가 이 스크립트로 잰 값을 기준선으로 적었고,
화면 조각(U1 ~ )은 제 화면을 옮긴 뒤 같은 스크립트로 다시 재어 견준다.

**읽기 전용이다** — 로그인과 조회(스크리너 조회처럼 POST 로 묻는 조회 포함)만 하고, 서버의 상태를 바꾸는 조작(주문 · 모드 · 설정 · 저장)은 부르지 않는다. 내 계좌 화면은 정한 모의 응답으로 그린다.
시험이 아니다(통과 · 실패가 없다): 재서 적을 뿐이다.

## 준비

스크립트는 서버를 띄우지 않는다. ★빌드한★ 화면 서버(`next start`)와 mock API 서버가 떠 있어야 한다(`next dev` 는 묶음 크기 · 시간이 다르다).
E2E 가 쓰는 서버와 같은 것이다 — 명령은 `playwright.config.ts` 의 `webServer` 두 줄이 원천이다(환경변수가 바뀌면 그쪽을 따른다).

```bash
# 저장소 뿌리에서 — API(mock · 임시 DB). 나머지 환경변수는 playwright.config.ts 의 webServer 를 본다
KIS_USE_MOCK=1 DATABASE_URL=sqlite:////tmp/e2e_pw.db python3 -m uvicorn main_api:app --port 8000 --workers 1
# frontend 폴더에서 — 화면
npm run build && BACKEND_URL=http://localhost:8000 npx next start -p 3000
```

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `UX_BASE_URL` | `http://localhost:3000` | 재는 화면 서버 |
| `UX_USER` · `UX_PASSWORD` | 로컬 mock 서버의 기본 계정 | 로그인. ★토큰과 응답 몸은 어디에도 찍지 않는다★(실패하면 상태 코드만) |
| `PW_CHROMIUM_PATH` | 샌드박스에 깔린 브라우저 → 없으면 Playwright 가 깐 것 | `playwright.config.ts` 와 같은 규칙 |

Node 22.18 이상(`.ts` 인 e2e 도우미를 바로 읽는다). `MODULE_TYPELESS_PACKAGE_JSON` 경고는 그 읽기에서 나는 것이고 결과와 무관하다.

## 스크립트 (모두 `frontend` 폴더에서)

| 스크립트 | 쓰임 | 무엇을 재나 |
|---|---|---|
| `measure.mjs` | `node scripts/ux-measure/measure.mjs <결과 폴더> [라우트 이름 정규식]` | 라우트 23 × 변형 6(1440 · 1920 · 1280 · 390 라이트 · 1440 다크 · 1440 줄인 모션). 화면마다 DOM 수 · 글자 수와 크기 분포 · 표(줄 수 · 줄 높이 · 화면 안의 줄 · 붙는 머리 · 숫자 칸의 맞춤) · 조작 요소(24px 미만 · 이름 없음) · 제목 단계 · 대비 · 첫 화면 JS · CSS 전송량 · LCP · CLS · 긴 작업 · 초점 걷기 36걸음 · 색의 뜻(뜻 있는 색이 숫자 · 누르는 것 · 글 어디에 쓰였나) |
| `interact.mjs` | `node scripts/ux-measure/interact.mjs <결과.json>` | 대표 조작(정렬 · 쪽 넘김 · 찾기 · 탭 · 노드 고르기 · 명령 팔레트 …)의 '입력 → 다음 그림' 시간(Event Timing — INP 의 근사) |
| `numprobe.mjs` | `node scripts/ux-measure/numprobe.mjs <결과.json>` | 본문 글꼴의 고정폭 숫자가 실제로 고정폭인지, 고정폭 글꼴보다 얼마나 좁은지(ADR 007 결정 D3 의 근거) |
| `focusprobe.mjs` | `node scripts/ux-measure/focusprobe.mjs [--delay] [<경로> <선택자>]...` | 정한 요소를 Tab 으로 찾아가 초점 전후의 겉모습 · 가림을 견준다. `--delay` 는 Tab 직후와 300ms 뒤의 고리(전환이 고리를 늦추는지) |
| `csscov.mjs` | `node scripts/ux-measure/csscov.mjs <결과.json>` | 화면 23 × 두 테마의 첫 그림에서 한 번이라도 쓰인 CSS 의 비율 |

`lib.mjs` 는 배관(주소 · 로그인 · 브라우저 · 맥락)뿐이다 — 재는 논리는 스크립트마다 따로 있다.

`measure.mjs` 의 결과: `<폴더>/<이름>__<변형>.json`(잰 값 전부) · `.png`(그 순간의 그림) · `summary.tsv`(한 줄 요약). 한 화면만: `… measure.mjs out '^screener$'`.

## 읽는 법

- **표의 줄**: `inView` 는 화면에 ★걸친★ 줄, `fullInView` 는 위아래가 ★다 보이는★ 줄이다. 붙는 머리 · 떠 있는 띠에 가린 줄은 따지지 않는다(상한).
- **`smallTargets`**: 조작 요소 상자의 짧은 변이 24px 미만(본문 속 글자 링크는 뺌). WCAG 2.5.8 의 간격 예외는 따지지 않았다 — ★상한★이다.
- **`unnamed`**: `aria-label` · `aria-labelledby` · 글자 · `title` · 자리 표시 · 연결된 `label` 이 모두 없는 조작 요소(체크 상자 · 라디오는 뺌). 접근성 트리의 이름 계산이 아니다 — 근사다.
- **전송량**(`sizes.js` · `sizes.css`): 응답 몸의 크기(압축된 채)의 합이다. 풀어 놓은 크기가 아니다.
- **시간**(LCP · 긴 작업 · `interact` 의 ms): ★한 번 잰 값★이고 이 기계의 것이다. 16ms 미만의 사건은 0 으로 적힌다(Event Timing 의 문턱). 두 빌드를 견줄 때는 같은 기계에서 여러 번 재어 퍼짐을 본다.
- **`csscov`**: 열지 않은 시트 · 메뉴 · 호버 · 오류 상태의 규칙은 '안 쓰임'으로 잡힌다 — 죽은 CSS 의 수가 아니라 ★그 위쪽 끝★이다.

## 기준선과 견주기

2026-11-20 감사 때의 스크리너(`/screener` · 1440 × 900 · 라이트): DOM 1,687 · 표 머리 y 745 · 줄 56px · 다 보이는 줄 2(걸친 줄 3) · 24px 미만 2 · 이름 없음 0 · 글자 크기 8가지.
스크립트를 저장소로 옮긴 뒤(U0-d) 다시 잰 값은 `docs/HISTORY.md` 의 그 조각에 있다. ★수는 문서가 아니라 다시 잰 값이 진실이다★ — 다르면 문서를 고치기 전에 차이의 까닭부터 본다.

## 한계

- mock 서버의 화면을 잰다 — 실데이터의 긴 종목명 · 큰 수 · 빈 값이 만드는 모양은 보지 못한다.
- Chromium 하나다. 손가락 화면은 뷰포트 폭만 줄인 것이다(터치 맥락이 아니다).
- 화면이 읽기 쉬운지 · 일이 빨라지는지는 재지 않는다. 재는 것은 구조(크기 · 수 · 시간)다.
- 라우트 목록과 조작 목록은 스크립트 안에 있다 — 화면이 생기거나 클래스 이름이 바뀌면 함께 고친다(닿지 못한 조작은 결과에 `error` 로 남는다).
