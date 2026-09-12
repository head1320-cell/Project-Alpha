# RA 제품 축 규칙 — ★CLAUDE.md 를 늘리지 않고 규율을 더한다★

> 실측 2026-09-12 · 기준 커밋 `564e035` · ★이 문서는 코드를 한 줄도 바꾸지 않았다★
> 선행: [`../Project_Alpha_RA_Product_Master_Prompt.md`](../Project_Alpha_RA_Product_Master_Prompt.md)(원문 요구) ·
> [`../../CLAUDE.md`](../../CLAUDE.md) §2·§5·§6(상위 규율) ·
> [`2026-08-27-capability-lineage-audit.md`](2026-08-27-capability-lineage-audit.md) §0(증거 어휘)

## 0. 왜 CLAUDE.md 가 아니라 여기인가

마스터 프롬프트는 `CLAUDE.md` 를 **새로 만들라**고 했다. 그런데 이 저장소의
`CLAUDE.md` 는 이미 mock 게이트·실거래 6중 안전장치·스크리너 3-레이어·버전 핀을
**99/100줄**로 눌러 담고 있고, 자기 머리에 `100줄 미만으로 유지하세요 — 길면
읽히지 않습니다` 라고 적어 뒀다. ★한 줄도 들어갈 자리가 없다.★

덮어쓰면 원문 자신의 규칙 4번(`NO DESTRUCTIVE REFACTORING`)을 어긴다. 그래서
**규칙은 여기 쓰고 CLAUDE.md 헤더의 기존 줄에 링크만 덧붙였다**(줄 수 증가 0).
선례가 있다 — [ADR 001](../decisions/adr-001-tailwind-shadcn-aas-migration.md) 도
CLAUDE.md 의 한 조항을 문서 쪽에서 대체했다.

---

## 1. 페이퍼 기본 — ★새 규칙이 아니라, 이미 있는 불변식의 제품 축 번역★

원문은 `PaperExecutionAdapter` 를 **만들라**고 했다. 재려고 보니 ★이 저장소는
이미 그것보다 엄격하다.★ 만들 것이 아니라 **우회하지 않겠다고 적을 것**이다.

| 이미 있는 것 | 어디 | 기본값 |
|---|---|---|
| 엔진 안전 설정 | `src/engine/trading_engine.py` `SafetyConfig` | `dry_run = True` |
| 실행기 모드 사다리 | `src/execution/order_executor.py` `ExecutionMode` | `SHADOW`(→`PAPER`→`LIVE`) |
| LIVE 승격 | 같은 파일 `set_mode()` | ★명시 토큰이 있어야 한다★ |
| 브로커 경로 | `src/execution/kis_client.py` 팩터리 | `KIS_IS_PAPER` 미설정 시 **모의투자** |
| 우회 금지 | `tests/test_no_order_executor_bypass.py` | `OrderExecutor` 를 `trading_engine.py` 밖에서 생성 금지 |
| 합성 차단 | `src/data/mock_gate.py::mock_allowed()` | `KIS_USE_MOCK` 이 **정확히 `"1"`** 일 때만 mock |

★제품 축 규칙 — 새 모듈은 이 경로를 우회하지 않는다.★ 주문을 만들거나 보낼 수
있는 모든 신규 코드는 `TradingEngine` 을 통과하고, 실행 모드를 스스로 올리지
않으며, 실패할 때 합성값을 만들지 않는다(`None` + 사유).

**아직 못 하는 것을 적어 둔다** — 실계좌 집행은 **인가 확인 전까지 금지**다.
이 저장소는 그것을 확인한 적이 없다. `KIS_IS_PAPER=1` 검증은 CLAUDE.md §6 의
선행 조건이지 인가의 대체물이 아니다.

---

## 2. 출처 태그 `SRC_*` — ★외부 회사 주장에만 쓴다★

원문은 `PUBLICLY_VERIFIED`/`INFERRED`/`UNKNOWN` 을 요구했다. 그대로 쓰면 이
저장소가 **이미 한 번 겪은 충돌**을 되풀이한다.

```
E0~E5   우리 데이터의 출처 등급        E0 이 ★최악★   (capability-lineage-audit §0)
L0~L3   모델 역량 사다리              L0 이 ★최상★   (src/engine/capability.py)
structural / synthetic_mechanism / real_forecast / real_economic
        주장의 종류                                 (scripts/t3_transmission.py)
```

`E0` 과 `L0` 이 반대 방향이고 둘 다 DB 에 값으로 들어 있다. CLAUDE.md §2 가
*"저장소가 이미 쓰는 어휘이니 새로 만들지 마세요"* 라고 못 박은 이유다.

★그래서 접두사로 격리한다.★ `SRC_*` 는 **바깥 회사에 대한 우리 지식의 출처**를
말한다 — 우리 파이프라인의 데이터도, 우리 모델의 역량도 아니다.

| 태그 | 뜻 | 이 환경에서 |
|---|---|---|
| `SRC_VERIFIED` | ★1차 출처를 **열어서** 확인★ — 회사 공식 페이지 · 공시 · 코스콤 공식 기록 | ★0건★ — 아래 §2-1 |
| `SRC_INFERRED` | 검색 엔진이 요약한 보도·공식 페이지. URL 은 남았으나 **원문을 대조하지 못함** | 대부분 |
| `SRC_UNKNOWN` | 근거를 못 찾음. 내부 알고리즘·영업비밀 | 알고리즘 상세 |

★`SRC_UNKNOWN` 은 "없다" 가 아니다.★ *"우리가 모른다"* 이고, 무엇을 찾아봤는지
함께 적는다. CLAUDE.md §4 의 `미상 ≠ 0` 을 이 축에 옮긴 것이다.

### 2-1. ★이 환경은 1차 출처를 못 연다★ (실측 2026-09-12)

`WebFetch` 가 **모든 외부 도메인**에서 막힌다 — 4사 사이트(`solutionquant.com` ·
`quantec.co.kr` · `qt-advisor.com`) · 코스콤(`koscom.co.kr`) · 언론
(`venturesquare.net` · `fintechtimes.co.kr`) · 대조군(`en.wikipedia.org`)까지
전부 `EGRESS_BLOCKED`. `WebSearch` 만 동작한다.

★그러므로 `SRC_VERIFIED` 가 0건인 것은 4사가 불투명해서가 아니다★ — **이 컨테이너가
원문을 못 여는 것**이다. 둘은 완전히 다른 사실이고, 섞어 적으면 다음 사람이
회사를 오해한다. 2단계 기업행위 프로브가 *"여기서는 확인할 수 없다" ≠ "그 데이터를
못 받는다"* 로 적은 것과 같은 부류다([인프라 로드맵](../plans/2026-09-06-quant-db-infra-roadmap.md)).

**승급 절차** — 증거 매트릭스에 `SRC_VERIFIED` 로 올리려면 ⑴ 해당 URL 을 열고
⑵ 인용문을 그대로 옮기고 ⑶ 조회일을 적는다. 열어야 할 URL 목록은 매트릭스
문서의 **§승급 대기** 절에 있다.

---

## 3. 수익률 4종은 ★섞이면 안 된다★

| 종류 | 무엇 | 무엇이 아닌가 |
|---|---|---|
| 코스콤 RA 테스트베드 | 표준 심사 환경의 모의 운용 | 고객 계좌 성과가 아니다 |
| 백테스트 | 과거 데이터 위의 시뮬레이션 | 실행 가능성의 증거가 아니다 |
| 페이퍼 | 모의투자 계좌의 실시간 집행 | 체결·슬리피지가 실계좌와 같지 않다 |
| 실계좌 | 실제 자금 | — |

- **한 화면에 두 종류를 이름 없이 함께 그리지 않는다.** 각 수치에 종류 라벨을 붙인다.
- **과거 성과를 미래 수익으로 투사하는 UI 를 만들지 않는다.**
- 이 저장소가 지금 낼 수 있는 것은 **백테스트뿐이다**. 페이퍼는 배선돼 있으나
  기록(`live_daily_pnl`)에 ★쓰는 코드가 없고★, 실계좌 성과는 존재하지 않는다
  ([갭 분석](2026-09-12-ra-gap-analysis.md) §NAV).
- CLAUDE.md §1 의 관문 사슬을 지운 것이 아니다 — ★이 저장소는 경제적 가치 관문을
  통과한 적이 없다.★ 제품 문서가 그 사실을 바꾸지 않는다.

---

## 4. 검증 체크리스트

```bash
make all      # = lint test typecheck build (CI 와 동일)
```

★`make test` 는 이 컨테이너에서 못 쓴다★(실측) — 맨 `pytest` 가 pandas 없는
인터프리터(`/root/.local/bin/pytest`)로 잡혀 수집 단계에서 깨진다. 대신:

```bash
ruff check src/ tests/ scripts/ main_api.py
KIS_USE_MOCK=1 python3 -m pytest tests/ -q      # /usr/local/bin/python3, pytest 8.2.2
cd frontend && npx tsc --noEmit && npx next build
```

CI(`.github/workflows/ci.yml`)는 여기에 **eslint FSD 의존 규칙**과 **Playwright
E2E** 를 더한다. `make all` 과 CI 는 같지 않다 — 프런트를 건드렸다면 CI 쪽이 넓다.

---

## 5. 코딩 규약 — ★이미 있는 것을 가리킨다★

새로 만들지 않는다. 원문이 요구한 항목별로 **이미 어디에 있는지**만 적는다.

| 원문 요구 | 이 저장소의 답 |
|---|---|
| 타입 안전성 | 백엔드 `from __future__ import annotations` + `dataclass`; 프런트 `tsc --noEmit` 가 CI 블로킹 |
| 린트·포맷 | `ruff` (line-length 120, `E,W,F,I,B,UP`) — 설정은 `pyproject.toml`, 무시 항목마다 사유 주석이 붙어 있다 |
| 비동기 오류 처리 | ★침묵 폴백 금지★(CLAUDE.md §4) — `except` 로 삼키고 `{}` 를 돌려주지 않는다. 실패는 `None` + **사유**이고, 사유 없는 `"unavailable"` 은 금지 |
| 테스트 | 계약을 테스트한다. 안전·정직성 가드에는 **변이 테스트**, "X 여야 한다" 에는 **짝**("X 가 아니어야 한다") — CLAUDE.md §5 |
| 프런트 | API 주소를 빌드 타임에 박지 않는다(`NEXT_PUBLIC_*`·`rewrites` 금지). **CSS 클래스명이 E2E 계약**이다 — [ADR 001](../decisions/adr-001-tailwind-shadcn-aas-migration.md) |
| 보안 | `.env` 커밋 금지. API 키를 채팅·이슈·로그에 노출 금지 |

---

## ★이 문서가 주장하지 않는 것★

- **페이퍼 어댑터를 만든 것이 아니다.** 이미 있는 것을 가리키고 **우회 금지**를
  적었다. 코드는 0줄 바뀌었다.
- **인가를 확인한 것이 아니다.** 실계좌 집행 금지는 여전히 유효하고, 그 해제
  조건은 이 저장소가 판단할 문제가 아니다.
- **`SRC_VERIFIED` 를 하나도 만들지 못했다.** 어휘와 승급 절차를 정의했을 뿐이고,
  그 이유는 회사가 아니라 ★이 환경★에 있다(§2-1).
