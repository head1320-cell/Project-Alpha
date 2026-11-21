# UI/UX 전문화 ③ — U2 출처 표지 · 갱신 시각: 구현 계획 (2026-11-21)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> (이 저장소의 받은 결정: 하위 에이전트는 쓰지 않는다 — 같은 세션에서 조각 순서대로 실행한다.)

**Goal:** 화면의 수가 어디서 · 언제 나왔는지를 한 꼴의 표지로 적는다. ★합성 계열에서 나온 수가 표시 없이 그려지는 자리(매크로 스튜디오 · C13)를 먼저 막고★, 주기 조회 화면이 '마지막으로 받은 때'를 보이는 글자로 말하게 한다(C14). 서버 · 요청 0줄.

**Architecture:** 공용 부품 하나(`shared/ui/provenance`)가 축의 차례(출처 → 시각들 → 시점 정합 → 덧붙임)와 꼴만 정하고, 낱말과 사실은 그 열거형을 아는 위젯이 정한다(shared 는 entities 를 모른다). 칩은 지금의 공용 근거 칩(`.tx-chips` · `.tx-chip[data-tone]` · `data-ev`)을 그대로 쓰고 감싸는 클래스 `tx-prov` 만 더한다. 갱신 시각 줄(`Freshness`)은 TanStack Query 의 `dataUpdatedAt` 을 받아 보이는 글자만 그린다(낭독 · 번쩍임 없음).

**Tech Stack:** Next.js(app router) · 순수 CSS(`globals.css`) · Playwright(E2E · 순수 스펙) · pytest(소스 훑기 가드). 새 의존성 0.

- 받은 말: "우선순위대로 다음 단계를 해"(2026-11-21) · 계획 승인(같은 날). 받은 결정 셋(권장안): ① 설계 문서 §8.1 의 U1 '조작 지연 기준선 이하'는 **보이는 줄을 맞춘 비교 + §7.2 문지방(200ms)** 으로 읽는다(날짜 붙인 정정 한 줄 · U1 끝) ② 라이트 계산 스타일 골든은 **U2 게이트에서 전체** 다시 얼린다 ③ 스튜디오의 합성 표시는 **서버 게이트만 · 화면만**(서버 0줄).
- 설계: [`docs/superpowers/specs/2026-11-20-uiux-professionalization-design.md`](../specs/2026-11-20-uiux-professionalization-design.md) §2.2(C13 · C14) · §5.1 · §8.1 · §9 · 결정: [ADR 007](../../decisions/adr-007-density-tiers-visual-language.md) §5.4(판정 칩 · 출처 표지는 중립 색조 · 합성 표시는 숨기지 않는다) · 앞 계획: [U1](2026-11-21-uiux-u1-table-screener.md).
- 답하는 물음: 출처 · 시각 표시의 ★구조★(`structural`) — 표시가 서는 조건 · 글자 · 낭독하지 않음 · 요청 불변까지. 어떤 수의 뜻 · 증거 등급 · 계산도 바꾸지 않는다.

---

## 0. 패널 결론 — U2 의 쟁점 (재무 · DB · 퀀트 · 수학 · 금융 · 웹디자인)

| 쟁점 | 갈린 의견 | 결론 |
|---|---|---|
| 스튜디오 합성 표시의 근거 | 계열마다의 출처(서버 고침) ↔ 서버 게이트 | **서버 게이트**(받은 결정 ③ · 매크로의 정해진 규칙 '합성 표시는 `connection-status.mock_allowed` 로만') — 계열별 출처는 별도 작업으로 남긴다 |
| 어느 스튜디오에 다나 | 다섯 모두 ↔ 계열을 쓰는 것만 | **서버가 답한 입력 계열(`d.inputs`)이 있는 스튜디오만** — 뷰 만들기는 데이터에서 나온 수가 없어 '합성 데이터'가 틀린 말이 된다 |
| 게이트가 꺼진 스튜디오 | 아무것도 적지 않는다 ↔ N/A + 사유 | **'출처 N/A(응답에 계열별 출처가 없습니다)'** — 모르면 모른다(합성 아님 ≠ 실데이터 확인). 게이트 조회 실패는 'N/A(출처 확인 실패)' |
| 출처 표지 부품의 일 | 등급 낱말을 부품이 정한다 ↔ 부르는 쪽이 정한다 | **부르는 쪽이 낱말 · 사실을 정하고 부품은 차례 · 꼴 · '모름이면 사유 필수'만** — 뜻 · 문구 그대로, shared 는 entities 를 모른다 |
| 축 | 하나로 합친다 ↔ 축마다 칩 | **축마다 칩**(출처 → 시각들 → 시점 정합 → 덧붙임 · 섞지 않는다) |
| 칩의 꼴 | 새 클래스 ↔ 지금 칩 | **지금의 `.tx-chips` · `.tx-chip[data-tone]` 그대로** + 감싸는 새 클래스 `tx-prov`(크기만 밀도 토큰) |
| 덧붙임 칩의 색(U2-a 에서 정함) | 정보 칩(info · 파랑) ↔ 중립 | **중립(plain) 이 기본 · 가정이면 assumed** — ADR 007 §5.4 '출처 표지는 중립 색조' · §5.3 '파랑은 하락과 링크에만'. 타입에서 info 를 뺐다 |
| 갱신 시각 | 화면마다 ↔ 한 부품 | **`Freshness` 한 부품**: 'N초마다 다시 읽습니다 · 마지막 수신 hh:mm:ss'(이 기기 시각 · 24시) · 받기 전 'N/A(아직 받은 값이 없습니다)' · 낭독하지 않음(`aria-live` · `role=status` 없음) · 조회 중에도 글자가 바뀌지 않음 · 실패 중에는 마지막 성공 시각에 멈춘다(지어내지 않는다) |
| 규칙 관제의 문장 | 부품으로 바꾼다 ↔ 그대로 | **그대로**(스펙이 글자를 건다) + 곁에 '마지막 수신' 만 |
| 실거래 화면 | 손대지 않는다 ↔ 부품으로 | **부품으로**(낭독 · 번쩍임을 없앤다) — ★요청 골든 바이트 그대로 · 주문 · 정지 · 모드 · 새로 고침 0줄 · `.lv-polled` 클래스 유지★ |
| 종목 찾기 | CSV 만 ↔ 화면에도 | **결과 도구 줄에 출처 표지**(계산 시각 · 자료 기준 시각 N/A) — CSV 와 같은 함수 · 그 결과를 만든 요청의 것. 합성 칩과 평가 상한 칩은 답 줄의 것 그대로(두 번 적지 않는다 — U2-d 에서 확인) |
| 'Live' · 펼친 줄 | — | **만들지 않는다**('Live' 는 설계 문서가 막고, 펼친 줄은 쓸 화면이 생길 때) |

## 1. 감사에서 본 것 (읽기 전용 · 2026-11-21 · HEAD `0157081`)

1. **★C13 확인(합성 표시 · 가장 먼저)★** — 매크로 스튜디오 화면(`widgets/macro/StudioPanel.tsx` · `/macro/{tsfm-latent,neural-sde,causal-deepm,pinn-tail}`)은 서버 산출값 표 · 답 줄 · 그림을 그리는데 합성 표시가 없다. mock 에서 수집기는 값이 없는 지표를 `source="MOCK"` 무작위 걸음으로 채우고(`src/services/macro_collector.py`) 스튜디오의 `load_series`(`src/engine/macro_models/base.py`)는 값만 뽑아 출처를 버린다 → 합성 계열에서 나온 수가 표시 없이 그려진다. 운영(게이트 꺼짐)에서는 MOCK 이 생기지 않는다. 매크로의 정해진 규칙(`MacroCockpit.tsx` · `MacroAnswer.tsx` 머리말)을 스튜디오만 읽지 않는다. 뷰 만들기(`agentic-mcp`)는 입력 계열이 없다.
2. **C14 정정(갱신 시각)** — 시각이 없는 주기 조회 화면은 넷이 아니라 둘: 실행 진행(`widgets/backtester/RunMonitor.tsx` · 1초)과 규칙 관제(`widgets/my-account/RuleMonitor.tsx` · 5초 · '가동 중: 5초마다 다시 읽습니다.'만 — `rule-arming.spec.ts` 가 글자를 건다). 실거래(`LiveTradingView.tsx`)는 시각을 이미 보이지만 `aria-live="polite"` 라 10초마다 낭독되고 조회 때마다 '갱신 중입니다'로 글자가 번쩍인다. 적재(`DbStatusPanel.tsx`)는 적재 중에만 'hh:mm:ss 수신' 칩(12시 '오후' 꼴). 시각 서식 함수가 두 화면에 따로 있다.
3. **종목 찾기의 계산 시각** — CSV 에만 있고 화면에는 없다. 서버의 응답 캐시(한 시간) 때문에 화면의 결과가 언제 계산됐는지 알 길이 없다.
4. **기존 어휘 · 계약** — 출처 어휘는 이미 셋(`shared/ui/evidence.tsx` · `shared/ui/tx` 의 `Chips`(+`ev`) · `shared/ui/PerfLabel.tsx`)과 기능별 등급 낱말. 기존 배지 넷(`brun-badge` · `tbt-prov` · `as-bt-badge` · 실행 모드)은 E2E 계약. 합성 칩의 꼴 `.tx-chip[data-tone=practice]` 를 스펙 수십 개가 짝으로 건다. 용어집: '합성 · 합성 데이터 · 합성 시세'.
5. **U2 밖(별도 작업)** — 응답 `data_source` 짐작(`src/api/screener_routes.py`)은 mock 에서 늘 '합성'이라 합성을 숨기지 않지만, 운영에서 KIS 키가 없을 때 '합성'이라 잘못 적는 낱말 문제다.
6. `:root` 에 넉넉 값의 밀도 토큰 기본이 있어 새 부품은 단 장치 밖 화면에서도 그려진다(그 화면의 기존 요소 값은 그대로). 요청 골든: 종목 찾기 · 실거래 · 백테스트 · 현실성(매크로 스튜디오는 없음).

## 2. 조각과 걸음 (하나씩: 빨강 → 구현 → 초록 → 좁은 회귀 → 변이 → 푸시 → CI)

### U2-a 출처 표지 · 갱신 시각 부품 — 제품 화면 0줄(견본만)
- [x] 순수 스펙 `e2e/provenance-logic.spec.ts`(차례 · 사유 필수 · 서식 · 문구 · 짝) 빨강 → `shared/ui/provenance/provenance.ts`(`provChips` · `freshnessText`) · `shared/lib/krFormat.ts` 의 `clockText`(24시 hh:mm:ss · 받은 적이 없으면 null).
- [x] `ProvenanceBadge.tsx`(= `tx.Chips` + `tx-prov` — `tx.Chips` 에 뒤 호환 `className` 하나) · `Freshness.tsx`(보이는 글자만 · `as` 로 span) · `index.ts`.
- [x] CSS `.tx-prov*` · `.tx-fresh`(`globals.css` 끝 · 토큰만) → `node scripts/gen-dark-modules.mjs`.
- [x] `/dev/ui` 에 `#provenance` 절(표지 다섯 · 시각 줄 셋 × 밀도 셋 × 두 테마 + 속성 없음) · krFormat 표에 `clockText` 두 줄.
- [x] 견본 스펙 `e2e/provenance.spec.ts`(★합성 칩이 밀도 셋 × 두 테마에서 보인다★ · 축의 차례 · 이름 · 글자 크기 · 낭독 0 · 대비 AA · 390) · `dev-ui` 스펙.

### U2-b 스튜디오의 합성 표시(C13) — 서버 0줄
- [x] `StudioHead`(다섯 화면 공유)에 출처 표지: 입력 계열이 있을 때만 — 게이트 참 → '합성 데이터' / 거짓 → '출처 N/A(응답에 계열별 출처가 없습니다)' / 게이트 조회 실패 → 'N/A(출처 확인 실패)' / 스튜디오 정보를 못 받음 → 'N/A(스튜디오 정보를 받지 못했습니다)'. 게이트는 `entities/macro/api.ts` 의 `connectionStatus`(매크로 머리와 캐시 공유).
- [x] 요청: 스튜디오 화면에 `GET /macro/connection-status` 하나가 는다 — 그 밖의 요청 · 서버 0줄.
- [x] 스펙(`e2e/macro-studios.spec.ts` · 빨강 먼저): 짝(참 → '합성 데이터' / 거짓 → practice 0 + N/A 사유) · 실패 · 뷰 만들기는 칩 0(짝: 입력 계열을 넣은 응답이면 선다) · 실제 mock 서버에서 넷 모두 칩 · 두 테마 대비.
- 덧줄(11-21 · 구현 중 정함 · HISTORY U2-b): ① 매크로의 기존 출처 칩(`entities/macro/regimeKo.ts` 의 `sourceChip`)을 감사가 놓쳤다 — 합성 쪽 낱말('합성 데이터')은 같게 두고, 그 칩의 '한국은행 실데이터'는 스튜디오에 쓰지 않는다(계열마다의 출처가 없다). ② 스튜디오 정보를 못 받으면 'N/A(스튜디오 정보를 받지 못했습니다)' 대신 계산 응답의 기간(span)을 증거로 쓰고, 그것도 없으면 표지 없음(실패 상자가 이미 말한다). ③ 게이트 실패의 글은 '출처 N/A(합성 여부를 확인하지 못했습니다)'. ④ 회색 바탕의 중립 칩에 판 + 선(스튜디오 범위 규칙 하나).

### U2-c 갱신 시각(C14) — 서버 · 요청 0줄
- [x] `RunMonitor.tsx`(1초 · 실행 중에만) · `RuleMonitor.tsx`(문장 그대로 + '마지막 수신') · `LiveTradingView.tsx`(`.lv-polled` 유지 · `aria-live` 뺌 · 번쩍임 없음 · 따로 있던 시각 서식을 걷음) · `DbStatusPanel.tsx`(적재 중 칩 → `Freshness` · 알림 문장의 시각도 공용 서식).
- [x] 스펙 새 `e2e/freshness.spec.ts`: 첫 응답 뒤 시각이 서고 다음 응답에 따라 바뀐다(짝: 응답이 실패하면 멈춘다) · 낭독 0 · 실거래 요청 골든 바이트 그대로 · `rule-arming` 의 글자 그대로.
- 덧줄(11-21 · 구현 중 정함 · HISTORY U2-c): ① 실거래의 '마지막 수신'은 읽기 넷 중 하나라도 받은 때(읽기가 실패를 던지지 않아 `dataUpdatedAt` 은 모두 실패해도 간다). ② 적재는 칩을 줄로 바꾸지 않고 칩의 글만 공용(`freshnessText`). ③ 실행 진행의 재연결 알림이 react-query v5 에서 뜰 수 없던 결함(`failureCount >= 3`)을 시간으로 세어 고쳤고, 이제 보이는 그 글의 줄표를 뺐다. ④ 규칙 관제는 문장과 받은 때를 한 줄에 놓는 `div.ma-mon-head` 하나.

### U2-d 종목 찾기의 출처 줄 — 요청 0줄
- [ ] 결과 도구 줄에 출처 표지: '계산 시각 …(서버 시계 · 시간대 표기 없음)' · '자료 기준 시각 N/A(응답에 없습니다)'. 값은 CSV 출처 열과 같은 함수(`widgets/screener/screenerCsv.ts`)에서 · 그 결과를 만든 요청의 것.
- [ ] 스펙: 화면 글자 = CSV 의 칸(짝: 응답의 `timestamp` 를 바꾸면 둘 다 바뀐다) · 새 요청이 도는 동안 앞 결과의 시각 · 밀도 셋 × 두 테마 대비 · 390 · 요청 골든 바이트 그대로.

### U2 게이트
- [ ] tsc · eslint · FSD · 다크 `--check` · 빌드 · 래칫과 문서 시험 묶음 · ★전체 E2E★ · 요청 골든 바이트 · 스크린샷 검수(라이트 · 다크 · 390 · 밀도 셋 · 스튜디오 · 관제 · 실거래 · 적재).
- [ ] ★라이트 골든 전체 다시 얼림(받은 결정 ②)★: 먼저 `golden-diff --rev 0157081` 로 U2 가 만진 경로 밖에 의도 밖 변화가 없음을 확인 → 13 경로 모두 다시 얼림 → 경로마다 새로 든 키 수를 적는다.
- [ ] 문서: 설계 문서 §8.1 U1 칸 정정(받은 결정 ①) · §2.2 C13 · C14 덧줄 · `docs/HISTORY.md` · `.claude/skills/alpha-ui/SKILL.md`(쓰는 법 몇 줄) · PR #5 본문.

## 3. 다시 쓰는 것 (새로 짓지 않는다)

`tx.Chips`(+`ev`) · `EvidenceBadge` · `PerfLabel`(뜻 그대로) · `entities/macro/api.ts` 의 `connectionStatus` · `screenerCsv.ts` · TanStack Query 의 `dataUpdatedAt` · 스펙 도우미(`contrastAudit` 등) · `scripts/golden-diff.mjs` · `scripts/gen-dark-modules.mjs`.

## 4. 하지 않는 것

서버 0줄(받은 결정 ③ — 스튜디오의 계열별 출처와 `data_source` 낱말 고치기는 별도 작업) · 'Live' 표시 · 기존 배지 넷 · 등급의 뜻과 낱말(기능별 그대로) · 다른 화면의 배지를 출처 표지로 옮기기 · 스튜디오를 단 장치에 올리기(U7) · 주문 경로 · 실거래의 동작 · 새 의존성 · 툴팁 · 펼친 줄 꼴.

## 5. 검증

- 조각마다 새 스펙의 빨강을 먼저 본다 → 초록 → 그 화면을 지나는 스펙 + `api-no-reuse` · `dark-modules` · `dev-ui` → 변이(합성 칩을 촘촘에서 숨김 · 게이트를 읽지 않음 · 참/거짓 뒤집기 · 뷰 만들기에도 칩 · `Freshness` 에 `aria-live` · 시각을 받은 때가 아니라 지금 시계로 · 실패 중에도 시각이 감 · 화면 시각 ≠ CSV) → 푸시 → CI.
- 불변: 요청 골든 바이트 · 주문 경로 0줄 · `rule-arming` 의 글자 · 다른 경로의 라이트 골든(게이트의 전체 다시 얼림 전까지 변화 0).

## 6. 주장의 범위

구조(`structural`) — 표시가 서는 조건 · 글자 · 낭독하지 않음 · 요청 불변까지. 견본과 mock 의 값은 합성 값이고, 트레이더 · 실제 화면 낭독기로는 재지 않았다. 투자 타당성과는 무관하다.
