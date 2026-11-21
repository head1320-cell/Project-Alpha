# 매매일지 v1 구현 계획 (2026-11-14)

> 설계: [`../specs/2026-11-14-trade-journal-design.md`](../specs/2026-11-14-trade-journal-design.md). 이 문서는 과제 · 파일 · 시험 이름 · 명령까지 적는다 —
> ★코드 전문은 싣지 않았다★(계획 문서의 관례보다 짧다. 시험이 계약이고, 시험은 과제마다 먼저 쓴다).

**목표**: 체결 내역 파일을 올리면 왕복 거래의 승률·손익비·비용 비중·손익분기 승률을 관측값으로 보여 준다. 서버는 저장하지 않는다.

**구조**: 브라우저가 파일을 읽어 줄을 정규화 → 서버의 순수 엔진(`src/engine/trade_journal/`)이 계산 → 브라우저가 직접 SVG 로 그린다.

**기술**: Python 표준 라이브러리(엔진 — pandas 없이) · FastAPI + Pydantic · Next.js(앱 라우터) · 직접 SVG · Playwright.

---

## 과제 1 — 엔진: 줄 검사 (`fills.py`)

- 만든다: `src/engine/trade_journal/__init__.py` · `src/engine/trade_journal/fills.py` · 시험은 `tests/test_trade_journal_matching.py` 에 함께(줄 검사와 매칭이 한 흐름이라 파일을 나누지 않았다)
- 시험(먼저): 정상 줄이 체결이 된다 · 일시 꼴 다섯(`YYYY-MM-DD HH:MM:SS` · `HH:MM` · `YYYYMMDD HHMMSS` · `T` 구분 · 날짜만) · 날짜만이면 `has_time=False` ·
  버림 사유 다섯(읽을 수 없는 일시 · 수량 ≤ 0 · 단가 ≤ 0 · 매수/매도 미상 · 종목 없음)과 줄 번호 · 음수 수수료는 버림 · 순서 보존(같은 시각은 받은 순서).
- 명령: `python -m pytest tests/test_trade_journal_matching.py -q`

## 과제 2 — 엔진: 왕복 매칭 (`matching.py`)

- 만든다: `src/engine/trade_journal/matching.py` · `tests/test_trade_journal_matching.py`
- 시험: 한 번 사고 한 번 판다 · 나눠 사고 나눠 판다(0→0 이 한 거래) · 선입선출의 원가(먼저 산 것부터) · 부분 청산 뒤 파일 끝(미청산 + 실현분) ·
  매수 없는 매도(따로 센다 · 손익 없음) · 보유보다 많이 판 매도(보유분까지만 맞추고 나머지는 매수 없는 매도) · 종목이 섞여도 종목별로 · 같은 시각 다건은 받은 순서 ·
  당일 청산 표지 · 매수만 있는 파일(거래 0 · 미청산만).
- 명령: `python -m pytest tests/test_trade_journal_matching.py -q`

## 과제 3 — 엔진: 비용 (`costs.py`)

- 만든다: `src/engine/trade_journal/costs.py` · 시험은 `tests/test_trade_journal_analyze.py` 의 '비용과 그 근거' 절
- 시험: 수수료 열이 있으면 관측 · 없고 요율이 있으면 가정(요율 × 대금) · 둘 다 없으면 미상(`None` — 0 이 아니다) ·
  세금 열이 있으면 관측 · 없으면 `sell_tax_bp_on` 추론(등급·출처가 따라온다) · 매수에는 세금 없음 · ETF 는 0(값) · 시장을 모르면 미상 ·
  사용자가 정한 시장은 '가정' · 종목 마스터가 알면 그 값(주입한 대역으로) · 2025년과 2026년 체결의 세금이 다르다(고정값이 아니라는 증거).
- 명령: `python -m pytest tests/test_trade_journal_analyze.py -q`

## 과제 4 — 엔진: 지표와 `analyze` (`metrics.py`)

- 만든다: `src/engine/trade_journal/metrics.py` · `tests/test_trade_journal_analyze.py`(요약 통계 · `analyze` 전체 · 가장자리)
- 시험: ★손으로 계산한 표본★(거래 여섯 — 시험 파일 머리에 계산 과정을 적는다)과 요약이 일치(승률 · 평균 이익·손실 · 손익비 · 기대값 · PF · 비용 비중 · 손익분기 승률) ·
  손실 0건이면 손익비·PF `None` · 거래 0건이면 전부 `None`(0 이 아니다) · 최대 연속 손실 · 누적 곡선과 고점 대비 하락 · 보유 시간 구간의 경계(59초 · 60초 · 5분 · 30분 · 하루 넘김) ·
  시간대·요일·종목·일별 묶음의 합이 전체와 같다 · 손실 직후 진입(10분 안 · 10분 밖 · 경계) · 비용을 모르는 거래는 비용 뒤 통계에서 빠지고 그 수가 적힌다 ·
  날짜만 있는 체결은 시간대·보유 시간에서 빠진다 · 표본이 작다는 표지(30건 미만).
- 변이: 선입선출 → 후입선출 · 비용 미상을 0 으로 · 손익분기 승률의 식 · 승률의 분모 · 경계(`<` ↔ `<=`) · 연속 손실 초기화 누락.
- 명령: `python -m pytest tests/test_trade_journal_*.py -q`

## 과제 5 — 라우트

- 만든다: `src/api/trade_journal_routes.py` · `tests/test_trade_journal_route.py` · 고친다: `main_api.py`(라우터 등록) · `src/api/protected_routes.py`(로그인 등록)
- 시험: 로그인 없으면 401 · 로그인하면 200 과 응답 모양 · 20,000줄 초과는 400 + 사유(계산 0 — 엔진 호출 0회) · 빈 요청은 400 ·
  ★저장하지 않는다★(요청 전후 DB 의 모든 표 행 수 동일 · 임시 작업 폴더에 새 파일 0) · `basis` 에 근거별 건수 · `not_covered` 목록 · 보호 레지스트리 양방향 시험이 그대로 초록.
- 명령: `python -m pytest tests/test_trade_journal_route.py tests/test_protected_routes.py -q`

## 과제 6 — 화면

- 만든다: `frontend/src/entities/trade-journal/{parse.ts,api.ts,types.ts,sample.ts,index.ts}` · `frontend/src/widgets/trade-journal/{TradeJournalView.tsx,MapStep.tsx,JournalResult.tsx,PnlCurve.tsx,format.ts}` ·
  `frontend/src/app/trade-journal/page.tsx` · `frontend/e2e/trade-journal.spec.ts` · `frontend/e2e/fixtures/trade-journal/*` · CSS 는 `frontend/src/app/globals.css` 의 `.tj-*` 절(저장소 관례)
- 고친다: `frontend/src/widgets/layout/TerminalShell.tsx`(내비) · `frontend/src/shared/theme/theme.ts`(다크 대응 화면 목록) · `frontend/src/entities/session/accessMap.json`(로그인 화면의 접근 지도 — 보호 등록부와 짝) · `frontend/e2e/nav.spec.ts`(메뉴 목록)
- E2E(먼저): 파일 올리기 → 열이 어림으로 골라져 있다 → 결과의 요약 값이 표본의 손 계산과 같다 · EUC-KR 파일이 깨지지 않는다 · 버린 줄 사유가 보인다 ·
  수수료 '모름'이면 비용 후 값이 `N/A` 와 사유 · 서버로 간 요청 본문에 파일 원문이 없다(정규화한 줄만) · 라이트·다크 AA · 문체 감사(`voiceAudit`).
- 명령: `npx tsc --noEmit -p . && npx eslint src && PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test e2e/trade-journal.spec.ts --trace off --reporter=line`

## 과제 7 — 마무리

- `make all`(ruff · 전체 pytest · typecheck · build) + `npx eslint src` · 관련 E2E(새 스펙 + 셸·내비·다크 모듈) · 스크린샷(라이트·다크) 검수 · HISTORY · 커밋(이름 지은 파일만) · 푸시 · CI · PR 본문.

## 범위 밖(다시 적는다)

서버 저장 · 미실현 평가 · 수익률(%)·MDD(%) · 공매도 · 파생 · 해외 · 유관기관 제비용 · 양도세 · 증권사 API · 증권사별 사전 설정 · 엑셀 · 조언과 추천.
