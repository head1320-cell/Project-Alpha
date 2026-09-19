# Project Alpha

> ★증거가 결론을 앞서는★ 한국 시장 퀀트 플랫폼. 네 축을 한 시스템으로 잇습니다 —
> ① **리서치**(스크리닝·백테스트·매크로 국면) ② **포트폴리오 운용**(자산배분·리밸런싱·진단)
> ③ **설명가능성**(모든 수치가 *무엇에서 나왔고 무엇을 안 쟀는지* 말합니다)
> ④ **전략 평가·유통**(평가 카드 + 유통 관문 — 인가 확인 전까지 닫혀 있습니다).
>
> ★이 저장소가 통과한 적 없는 관문: 경제적 가치.★ 백테스트는 예측력의 증거가 아닙니다.
> ★인가 없이 켜지 않습니다★ — 실계좌 집행과 대고객 유통은 인가 확인이 선행합니다.

[![CI](https://github.com/head1320-cell/Project-Alpha/actions/workflows/ci.yml/badge.svg)](https://github.com/head1320-cell/Project-Alpha/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-black.svg)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)

FastAPI 백엔드 + Next.js 14 프론트엔드 + PostgreSQL 로 구성된 웹 플랫폼입니다.
DART(재무) · KIS(시세·주문) · KRX(장기 일봉) 실데이터를 연동하며, **API 키가 없으면 결정론적
mock으로 자동 폴백**하기 때문에 키 없이도 전 기능을 그대로 둘러볼 수 있습니다.

---

## 네 축 — 지금 어디까지 왔나

★자평이 아니라 판정표를 링크합니다★ — 어느 칸이 왜 그 상태인지는 채점표가
기준별로 적습니다([애드덤 합격기준 13개](./docs/specs/2026-09-12-addendum-scorecard.md) ·
2026-09-19 실측 **통과 7 · 부분 6 · 미달 0**).

| 축 | 무엇을 하는가 | 지금 | 근거 |
|---|---|---|---|
| **① 리서치** | 스크리닝 · 백테스트 · 매크로 국면 · 기업 분석 | 동작 | [로드맵 P1](./docs/plans/2026-09-12-ra-product-roadmap.md) · [데이터 인프라](./docs/plans/2026-09-06-quant-db-infra-roadmap.md) |
| **② 포트폴리오 운용** | 자산배분 · 리밸런싱 사유 · 보유 진단 · 계좌 판정 · 글라이드패스 격차 | 동작 · ★배분은 계좌·목표를 모른다(관측만)★ | [로드맵 P2](./docs/plans/2026-09-12-ra-product-roadmap.md) |
| **③ 설명가능성** | 일일 설명 · 귀인 6효과 · 증거 롤업 · 포트폴리오 리포트 | 동작 | [로드맵 P3](./docs/plans/2026-09-12-ra-product-roadmap.md) · [HISTORY](./docs/HISTORY.md) |
| **④ 전략 평가·유통** | 전략 평가 카드 · 유통 관문 | 기술만 · ★유통 표면 없음★ | [로드맵 P4](./docs/plans/2026-09-12-ra-product-roadmap.md) |

★③이 이 플랫폼의 차별화 지점입니다.★ 수치가 있으면 그것이 **관측인지 가정인지
미상인지** 를 응답과 화면이 함께 말합니다 — 안 잰 것을 0 으로 그리지 않고, 재지 못한
축은 "재지 못했다" 고 적습니다. 무엇을 근거로 그렇게 말하는지는
[개발 이력](./docs/HISTORY.md)이 프로그램 단위로 기록합니다.

---

## 기능

플랫폼은 7개 모듈로 구성됩니다.

| 모듈 | 경로 | 하는 일 |
|---|---|---|
| **01 Screener** | `/screener` | 유동성 게이트 → 필터 → 후처리 애널라이저 3-레이어 스크리닝. 재무·가격·수급·기술 팩터를 자유 조합하고, 자연어 검색과 조건식 저장을 지원합니다. |
| **02 Backtester** | `/backtest` | 전략 실행 · 비주얼/DSL 설계 · 전략 비교. 체결가 13종, 분할 매수/매도, 보유기간 규칙, 동적 재편입, 벤치마크 대비 α·β. 실행은 서버에 영속되어 새로고침·북마크로 복구됩니다. |
| **03 Macro** | `/macro` | 성장·물가 2축 국면 판정(KR/US 분리), 사이클·수익률곡선·스트레스, 자산군 상관·마켓타이밍, 22종 자산배분 전략 랭킹. |
| **04 Company** | `/insights` | 기업 분석 콕핏 — RIM/DCF/DDM 내재가치, 풋볼 필드, 민감도, 피어 비교, 재무 품질(QoE·발생액), Altman Z·Beneish M 분해. |
| **05 Risk** | `/risk-tools` | 시나리오 스트레스 테스트, VaR/ES, 취약 종목 도출. |
| **06 Allocation Studio** | `/allocation` | 목표 선택 → 구성 → 알파 → 테제 → 타이밍 → 최적화 → 스트레스 → 귀인 → 실행 → 저널 순차 파이프라인. Black-Litterman 사용자 뷰, HRP·리스크패리티·최소분산·Min CVaR, 워크포워드 OOS 검증. |
| **07 Data Infra** | `/admin/data` | 적재 현황·유니버스 커버리지·연결 진단. |

**자동매매**는 기본이 `dry_run=True`이며, 6중 안전장치(킬 스위치·손실 한도·주문 상한·일일 한도·
포지션 제한·dry-run 기본값)를 거칩니다. 실계좌 사용 전 반드시 모의투자에서 검증하세요.

---

## 빠른 시작

### Docker (권장)

```bash
git clone https://github.com/head1320-cell/Project-Alpha.git
cd Project-Alpha
cp .env.example .env          # 키 없이도 mock 모드로 동작합니다
docker compose up --build -d
```

- 프론트엔드 <http://localhost:3000>
- API 문서 <http://localhost:8000/docs>

### 로컬 개발

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main_api:app --reload --port 8000

cd frontend && npm install && npm run dev          # 별도 터미널
```

요구 사항: Python 3.11 · Node.js 20+ · (Docker 사용 시) Docker Compose.

### 검증

```bash
make all        # lint + test + typecheck + build — CI와 동일한 게이트
make test       # KIS_USE_MOCK=1 pytest tests/ -q
cd frontend && npx playwright test                 # E2E (실 백엔드 + 실 프론트 기동)
python verify_connection.py                        # 실데이터 연동 단계별 점검
```

---

## 환경 변수

전체 목록과 설명은 [`.env.example`](./.env.example)에 있습니다. 핵심만 추리면:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KIS_USE_MOCK` | `1` | **`1`일 때만** mock. 실데이터를 보려면 `0`. 이 값이 mock 여부의 유일한 기준입니다. |
| `KIS_IS_PAPER` | `1` | `1`=모의투자, `0`=실계좌 ⚠ **실제 자금이 거래됩니다.** |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | — | [KIS Open API](https://apiportal.koreainvestment.com) 발급. 모의/실전 키가 서로 다르며 `KIS_IS_PAPER`와 종류를 맞춰야 합니다. |
| `KIS_ACCOUNT_NO` / `KIS_ACCOUNT_PRDT` | — / `01` | 계좌번호 앞 8자리 / 상품 코드(위탁 `01`). |
| `DART_API_KEY` | — | [OpenDART](https://opendart.fss.or.kr/) 무료 발급. 설정 시 펀더멘털 팩터가 실제 재무로 계산됩니다. |
| `KRX_API_KEY` | — | [KRX OpenAPI](https://openapi.krx.co.kr). 장기 백테스트용 역사 일봉 적재에 사용. |
| `BOK_API_KEY` / `FRED_API_KEY` | — | 매크로 지표(한국은행 ECOS / FRED). |
| `ANTHROPIC_API_KEY` | — | 선택 — 자연어 검색·AI 서술 기능. 없으면 규칙 기반으로 동작합니다. |
| `BACKEND_URL` | `http://backend:8000` | 프론트 컨테이너가 런타임에 읽는 백엔드 주소. |
| `PG_*` | — | PostgreSQL 접속 정보 (compose 기본값 제공). 미설정 시 SQLite로 폴백해 DB 없이도 기동됩니다. |

브라우저는 백엔드 주소를 직접 알지 못합니다 — 모든 호출이 동일 출처 `/api/backend/...` 런타임
프록시를 거치므로, 배포 IP가 바뀌어도 프론트를 다시 빌드할 필요가 없습니다.

---

## 구조

```
Project-Alpha/
├─ main_api.py            # FastAPI 엔트리 (자체 라우트 + 도메인 라우터)
├─ src/
│  ├─ api/                # 도메인 라우터
│  ├─ engine/             # 스크리너·백테스트·매크로·자산배분·리스크 핵심 로직
│  ├─ data/               # DART/KIS/KRX 클라이언트, 팩터 스토어, 스냅샷 DB
│  ├─ execution/          # 실거래 클라이언트, 킬 스위치, 리스크 게이트웨이
│  ├─ models/             # 계량 모델 (VaR·GARCH·CVA·파생)
│  └─ observability/      # 구조화 로깅 + 요청 추적 미들웨어
├─ frontend/src/
│  ├─ app/                # Next.js App Router 라우트
│  ├─ components/         # 도메인별 UI
│  └─ lib/                # API 클라이언트 · 도메인 로직
├─ tests/                 # pytest
└─ docs/                  # 스펙 · 계획 · 개발 이력
```

---

## 문서

| 문서 | 내용 |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | **AI 에이전트용 운영 계약** — 증거 규율 + **절대 불변식**. ★제품 소개가 아닙니다★ — 이 README 가 그 역할입니다. |
| [제품 축 로드맵](./docs/plans/2026-09-12-ra-product-roadmap.md) | 네 축의 단계(P-1~P4) · **축별 UI/UX·백엔드 방향** · 하지 않을 것. |
| [데이터 인프라 로드맵](./docs/plans/2026-09-06-quant-db-infra-roadmap.md) | 병행 트랙 — 저장·적재·품질. 제품 축과 서로를 막지 않습니다. |
| [채점표](./docs/specs/2026-09-12-addendum-scorecard.md) | 합격기준 13개의 **기준별 판정과 그 이유**. |
| [제품 규칙](./docs/specs/2026-09-12-ra-product-rules.md) | 무엇을 주장해도 되는가 — 표현·등급 규칙. |
| [4사 증거 매트릭스](./docs/specs/2026-09-12-ra-benchmark-evidence-matrix.md) | 국내 로보어드바이저 4사가 **무엇을 만들었다고 말하는가** 와 그 말의 **근거 등급**. ★평가하지 않습니다★ |
| [`docs/HISTORY.md`](./docs/HISTORY.md) | 전체 개발 이력 (연대기순) — 무엇을·왜·**무엇을 안 했는지**. |
| [`docs/specs/`](./docs/specs) · [`docs/plans/`](./docs/plans) | 기능 스펙과 구현 계획. |
| <http://localhost:8000/docs> | 전체 API 레퍼런스 (OpenAPI, 기동 후 자동 생성). |

---

## 책임 한계

이 저장소는 **연구·개발 목적**입니다. **투자 자문이 아니며**, 백테스트 결과가 미래 수익을
보장하지 않습니다. 실계좌(`KIS_IS_PAPER=0`)로 전환하면 실제 자금이 거래됩니다 — 충분히
검증한 뒤 본인 책임으로 사용하세요. API 키는 절대 커밋하지 마세요(`.env` 는 `.gitignore`
에 포함돼 있습니다).

★네 번째 축(전략 평가·유통)에 대하여★ — 이 저장소에는 **전략을 타인에게 유통하는 표면이
없습니다.** 평가 카드와 유통 관문은 기술로 존재하지만 관문은 닫혀 있고, 그 부재를
`tests/test_distribution_blocked.py` 가 전수로 지킵니다. 투자자문업·투자일임업은 인가
사항이며 ★인가는 코드로 해결되지 않습니다★ — 인가 확인 전까지 켜지 않습니다.
