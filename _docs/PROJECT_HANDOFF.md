# Project Alpha — 백테스터 재설계 작업 핸드오프

> 이 문서는 한 번의 작업 세션에서 진행한 **전체 과정·결정·산출물·남은 일**을 담은 핸드오프야.
> 목적: 이 패키지를 다운받아 **Claude Cowork에서 로컬 레포로 이어서 개발**하는 것.
> 코드는 전부 `npx tsc --noEmit`(strict + noUnusedLocals) 통과, 백엔드 엔드포인트는 로직까지 검증 완료.

---

## 0. 한 줄 요약

젠포트/밸리를 레퍼런스로 **백테스터 UI/UX를 재설계**했고, 인라인 목업 → 실제 React/TS 코드 → 백엔드 엔드포인트까지 만들었다. 모든 부품은 네 기존 디자인 토큰에 맞춰 인라인 스타일로 짜서 드롭인 가능하다. 남은 핵심 작업은 (1) 파일을 레포 `src` 경로로 이식, (2) 유니버스 실시간 카운트 백엔드 어댑터 연결, (3) `TerminalBacktester`의 흩어진 state를 단일 전략 객체로 이식 — 이 셋이 Cowork 첫 작업으로 적합하다.

---

## 1. 배경 / 문제 진단

대상: **Project Alpha** — 한국 주식 퀀트 플랫폼. 스택은 FastAPI(약 185 라우트) + Next.js 14 + PostgreSQL + Docker, Windows 개발 환경. 바이사이드(스크리너 V3: 유동성 게이트 → 13종 필터 → 포스트 애널라이저, 64+ 팩터, 학술 프리셋; 백테스터 "젠포트화" Phase 0–5; 리얼리즘 엔진)와 셀사이드/FICC(QuantLib CVA/XVA/FRTB-ES/이그조틱, DCC-GARCH, 변동성 곡면)를 모두 다룸. KIS OAuth 실행에 6개 안전 가드.

**진단:** 기능 셋은 오히려 젠포트 스크리너보다 풍부하다. 진짜 문제는 *프레젠테이션* —
- 9–11px 모노 텍스트로 인한 과도한 시각 밀도
- cold-start(빈 화면) 문제
- 높은 인지 부하
- 조건별 자연어(NL) 피드백 부재

---

## 2. 레퍼런스 분석

- **젠포트**(genport.newsystock.com, ASP.NET): 탭 = 종목발굴/스크리너, 백테스트/Trading.aspx, 포트관리, 포트AI. 본받을 강점 — NL 검색 + 아이디어 칩(cold-start 해소), 18개 함수 라이브러리 + 라이브 NL 문장, 드래그 재정렬, 상시 요약 패널, 평이한 설명이 붙은 팩터 점수.
- **밸리(valley.town)**: 거시경제/스크리너/구루트래킹/내러티브/가치평가/백테스팅.

---

## 3. 디자인 방향 (확정)

- 큰 가독 폰트(12–16px), **모노는 숫자에만**, 차분한 밀도
- **점진적 공개(progressive disclosure)**: 아이디어 칩 + 프리셋을 앞에, 64-팩터 풀 빌더는 "고급" 뒤로
- **조건별 자연어 한 줄**(이 조건이 무슨 뜻인지 즉시 설명)
- **시맨틱 색**: 매수(buy)=빨강(`--danger` #dc3545), 매도(sell)=파랑(#1565c0), 유니버스/공통=중립. 액센트(`#1200ff`)는 활성/주요 상태에만.

---

## 4. 산출물 — 파일 맵

모든 파일은 상단 주석에 타깃 경로가 적혀 있음. 인라인 스타일 + CSS 변수(`--text-primary`, `--border`, `--danger`, `--bg-section`, `--bs-border-radius`, `--bs-font-mono` …) + lucide-react. import는 전부 상대경로.

| 패키지 파일 | 레포 타깃 경로 | 역할 |
|---|---|---|
| `lib/genportFactors.json` | `frontend/src/lib/backtest/genportFactors.json` | 가이드 344개 팩터 (`{name, expr}`), 진짜 14개 대분류 |
| `lib/factorCatalog.ts` | `frontend/src/lib/backtest/factorCatalog.ts` | 타입 + `searchFactors()` + `factorToken()` |
| `lib/factorFunctions.ts` | `frontend/src/lib/backtest/factorFunctions.ts` | 18개 함수(파라미터 + 미리보기 템플릿 `{f}{n}{v}{dir}`) |
| `lib/strategy.ts` | `frontend/src/lib/backtest/strategy.ts` | **키스톤** `BacktestStrategy` 상태 스키마 + `buildSummary()` |
| `lib/universeApi.ts` | `frontend/src/lib/backtest/universeApi.ts` | `universeCount()` → `POST /api/v1/screener/universe-count` |
| `components/kit.tsx` | `frontend/src/components/backtest/kit.tsx` | 부품 5종 + `Toggle` + `SummaryRail`, `tone`(buy/sell/neutral)로 색 주입 |
| `components/FactorPickerModal.tsx` | `frontend/src/components/backtest/FactorPickerModal.tsx` | STEP1 팩터 → STEP2 함수 마법사, `onInsert(pick)` |
| `components/ConditionFormulaEditor.tsx` | `frontend/src/components/backtest/ConditionFormulaEditor.tsx` | 조건식 리스트 + 모달 + 연산자·값 + NL 한 줄 |
| `components/panels/BuyConditionPanel.tsx` | `frontend/src/components/backtest/panels/BuyConditionPanel.tsx` | 포트 기본 + 매수 조건(에디터) + 매수 비중 (빨강) |
| `components/panels/SellConditionPanel.tsx` | `frontend/src/components/backtest/panels/SellConditionPanel.tsx` | 목표가/손절가·트레일링 + 보유기간 + 조건매도 + 청산 + 시간 (파랑) |
| `components/panels/UniversePanel.tsx` | `frontend/src/components/backtest/panels/UniversePanel.tsx` | 실시간 종목 수 + 시총군·업종·ETF/관리/감리·관심그룹 (중립) |
| `components/BacktesterRedesignDemo.tsx` | `frontend/src/components/backtest/BacktesterRedesignDemo.tsx` | 통합 레퍼런스(요약 탭이 좌측 패널 전환) |
| `backend/screener_universe_count.py` | `src/api/screener_universe_count.py` | FastAPI 유니버스 카운트 엔드포인트(어댑터 seam 4곳) |
| `INTEGRATION.md` | — | 배치/통합 가이드(상세) |

`tsconfig.json` 에 `"resolveJsonModule": true` 필요(Next 기본 on).

---

## 5. 데이터 — 팩터 카탈로그

- `genportFactors.json` = 젠포트 팩터 가이드 **v1.82**에서 추출한 **344개**. PDF가 Type3 폰트라 pdfplumber가 OOM → `pdftotext -layout`로 추출.
- **카테고리는 가이드 표의 "대분류 열"을 위치 기반으로 복원**한 14개: 종합·모멘텀·펀더멘탈·뉴지지표·가격·수급·성장·가치·기술지표·마켓타이밍·환율·금리·지수·기타. 라벨·순서가 가이드와 일치.
- 대분류 라벨이 **병합셀**이라 블록 중앙에 한 번만 찍힘 → 각 팩터를 "가장 가까운 라벨"에 배정(중간점 경계). 라벨이 페이지마다 반복돼 앵커가 많아 정확도 높음.
- **블록 경계의 일부 팩터는 인접 카테고리로 들어갈 수 있음.** 명백한 것만 수동 보정(공매도/대차/신용→수급, 캔들류→가격). 팩터 이름·`{토큰}`(`expr`)은 가이드와 정확히 일치. 카테고리는 JSON의 `categories[*].id/label`과 `factors` 배치로 손튜닝 가능.
- 18개 함수는 젠포트 `trading.js`에서 추출(기본/과거값/이동평균/비율/순위/최고값/최저값/변화량_기간/변화율_기간 + 전체 9개: 절대값/기간총합/비교/큰값/작은값/큰개수/작은개수/평균모멘텀스코어/표준편차). 각 함수에 입력 파라미터(기간 N / 비교값 V / 정렬)와 미리보기 템플릿이 있어 STEP2가 입력칸과 `조건식 미리보기`를 자동 렌더.

---

## 6. 상태 객체 (키스톤)

`strategy.ts`의 `BacktestStrategy`가 핵심 설계. 지금 `TerminalBacktester`(frontend/src/components/backtest/TerminalBacktester.tsx, ~798줄)에 흩어진 `useState`(stopLoss·takeProfit·maxHoldDays·sellDividePct·buyDividePct·maxBuyPerDay…)를 객체 하나로 모은다. `buy`/`sell`/`universe` 슬라이스를 가지며, `buildSummary(s, tab)`가 우측 요약 레일 구조를 만든다(켜진 옵션만 행으로). 즉 요약 레일은 같은 state를 읽으므로 **거의 공짜로** 따라온다.

---

## 7. 유니버스 실시간 종목 수 (라이브)

- **프론트**(완료, 타입체크 통과): `universeApi.universeCount()` + `UniversePanel`의 300ms 디바운스 훅(`live` prop 기본 on, `counting` 로딩 표시). 선택 변경 시 백엔드 호출 → `matched`/`totalUniverse` 갱신. **실패 시 기존 숫자 유지**(데모는 오프라인에서도 동작).
- **백엔드**(완료, 로직 검증): `POST /api/v1/screener/universe-count` → `{matched, total}`. Pydantic 요청 `UniverseCountRequest{caps, sectors, etf, managed, supervised, groups[{mode, tickers}]}`. 게이트 로직(시총군 mask, 섹터 mask, ETF/관리/감리 flag mask, 관심그룹 include/exclude)은 작은 픽스처로 검증 완료.
- **라이브로 만들려면** `screener_universe_count.py`의 **★ADAPTER 4곳**만 연결:
  1. `_load_universe_frame()` — `stock_master`/`ticker_universe`로 전체 매매가능 종목 프레임(ticker·market·market_cap·sector·is_etf·is_managed·is_supervised).
  2. `CAP_TIER_RULES` — 시총군 id ↔ 시장/시총 기준(임계값 근사치, 네 정의로 조정).
  3. `SECTOR_THEME_MAP` — 17개 업종 그룹 ↔ 네 섹터 문자열(88업종 묶어 채움).
  4. `COL_*` — 네 프레임 컬럼명에 맞춤.
- **미연결 시 501** 반환 → 프론트가 기존 숫자 유지(silent 0 방지). `main_api.py`에 `app.include_router(universe_count_router)` 등록.
- 기존 `POST /api/v1/screener/count`는 `{total_evaluated, total_passed, elapsed_seconds}`를 반환하고 `universe` 파라미터가 coarse 프리셋 문자열이라, granular 카운팅엔 이 신규 엔드포인트가 필요(그래서 (b)로 신규 엔드포인트 구현).
- 관심그룹 include/exclude 정밀도는 그룹의 실제 종목코드 필요 — `UniversePanel`의 `universeCount({ groups: …, tickers: [] })` 자리에 `watchlistStorage`의 종목코드 연결.

---

## 8. 통합 방법 (요약)

자세한 건 `INTEGRATION.md`. 바로 보려면 파일 배치 후 아무 페이지에서:
```tsx
import BacktesterRedesignDemo from "@/components/backtest/BacktesterRedesignDemo";
export default function Page() { return <BacktesterRedesignDemo />; }
```
매수 조건 → "조건식 추가 / 팩터·함수 선택" → STEP1·STEP2 모달 → 입력 시 조건이 쌓이고 우측 요약 레일이 실시간 반영. 레일 탭(매수·매도·대상)이 좌측 패널까지 전환.

**TerminalBacktester 이식의 본질**: 흩어진 `useState`를 `BacktestStrategy` 객체 하나로 모으는 것. 그러면 `buildSummary()`로 요약 레일이 따라오고, 기존 백테스트 실행부엔 `strategy` → 기존 payload 매핑 어댑터 한 겹만 두면 된다.

---

## 9. 현재 상태 · 블로커 · 남은 일

**블로커(이 세션 한정):** 작업 중 워크스페이스의 업로드 폴더에서 **프로젝트 zip(`0605_1019_에러없음.zip`)이 빠져** 백엔드 소스(`screener_routes.py`·`ticker_universe.py`·`stock_master.py`·`engine/screener.py`·`filter_ast.py`)를 직접 확인하지 못함. 그래서 백엔드는 데이터에 닿는 부분을 어댑터 seam으로 분리해 두었고, **이 부분은 Cowork가 로컬 레포에서 직접 읽어 채우면 즉시 해결**된다.

**남은 일(우선순위):**
1. `backtest-redesign`의 파일들을 위 표의 `frontend/src` 경로로 이식. `resolveJsonModule` 확인.
2. `screener_universe_count.py`의 ADAPTER 4곳을 실제 `stock_master`/`ticker_universe`/Postgres 스키마에 연결 + `main_api.py` 등록 + pytest 픽스처.
3. `TerminalBacktester`의 흩어진 `useState` → `BacktestStrategy` 단일 객체로 이식 + 실행 payload 어댑터.
4. 팩터 카테고리 경계 손튜닝(필요 시).
5. 관심그룹 include/exclude에 `watchlistStorage` 종목코드 연결.
6. 매수 정렬(primary/secondary sort), 매수 기준가, ATR 비중 등 세부 로직을 백테스트 payload에 매핑.

각 작업 후 **프론트 `npx tsc --noEmit` 0 에러 + 백엔드 라우트 수 점검**(회귀 방지)을 돌릴 것.

---

## 10. Claude Cowork에서 개발 시작하기

Cowork는 터미널 없이 Claude Code의 에이전트 엔진을 데스크톱에서 쓰는 것. Windows GA(모든 유료 플랜). 빠른 시작:

1. 최신 Claude Desktop for Windows 설치/업데이트(claude.com/download), 유료 플랜으로 로그인.
2. Cowork는 격리 VM 사용 — Windows Home은 제어판에서 **Virtual Machine Platform** 켜고 재부팅(~2GB VM 이미지는 C: 드라이브로). arm64 미지원.
3. **권한 주기 전 git 커밋/푸시로 백업**(삭제는 매번 승인받지만 초기 사고 사례 있음).
4. Cowork 모드에서 레포 루트 폴더 추가 + read/write 권한.
5. 레포 루트에 동봉한 `CLAUDE.md`를 둬서 컨벤션(tsc 0 에러·라우트 점검·디자인 토큰·시맨틱 색·건드리면 안 되는 부분)을 따르게 함.
6. **Postgres MCP** + **GitHub** 커넥터 연결 → DB 스키마 조회로 ADAPTER를 실제 값에 맞춰 채울 수 있음.

**VM 주의:** Cowork는 VM 안에서 `pip/npm/tsc/pytest`를 돌릴 수 있지만 호스트의 Docker/`localhost:8000`/호스트 Postgres엔 자동으로 안 닿을 수 있다. 실제 스택 기동(`docker compose up`/`uvicorn`/`next dev`)은 호스트에서 돌리고, Cowork엔 편집+타입체크/테스트+리서치를 맡기는 분업이 현실적. 작업당 토큰이 챗의 수십 배라 5시간 쿼터가 빨리 닳음.

**첫 작업 프롬프트 예시:**
> "이 핸드오프(PROJECT_HANDOFF.md)와 INTEGRATION.md를 읽어. (1) backtest-redesign의 파일들을 표의 frontend/src 경로로 이식하고, (2) src/api/screener_universe_count.py의 ADAPTER 4곳을 우리 stock_master.py·ticker_universe.py·Postgres 스키마에 맞춰 채운 뒤 main_api.py에 라우터를 등록하고 matched/total을 검증하는 pytest를 추가해. 끝나면 프론트 `npx tsc --noEmit`와 라우트 수 점검을 돌려 0 에러를 확인하고 변경 요약을 알려줘. 파일 변경 전에 계획부터 보여줘."

---

## 부록: 패키지 파일 트리

```
project-alpha-backtester-redesign/
├── PROJECT_HANDOFF.md        ← 이 문서
├── CLAUDE.md                 ← 레포 루트에 둘 프로젝트 지침(Cowork용)
├── INTEGRATION.md            ← 배치/통합 상세 가이드
├── lib/
│   ├── genportFactors.json
│   ├── factorCatalog.ts
│   ├── factorFunctions.ts
│   ├── strategy.ts
│   └── universeApi.ts
├── components/
│   ├── kit.tsx
│   ├── FactorPickerModal.tsx
│   ├── ConditionFormulaEditor.tsx
│   ├── BacktesterRedesignDemo.tsx
│   └── panels/
│       ├── BuyConditionPanel.tsx
│       ├── SellConditionPanel.tsx
│       └── UniversePanel.tsx
└── backend/
    └── screener_universe_count.py
```
