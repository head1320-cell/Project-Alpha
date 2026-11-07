# 중계 층 탐침 (진단 도구)

화면이 `/api/backend/…` 응답을 끝내 받지 못할 때 **어느 층이 붙잡았는지** 가른다. 2026-11-07 에 이 도구로
"브라우저가 먼저 떠난 요청의 백엔드 응답이 남던 것"을 찾아 고쳤다(`docs/HISTORY.md` · CF 3부 U 이어서 5·5b).
그때의 원래 증상 — **브라우저가 기다리는데 백엔드가 200 을 적은 응답이 오지 않음** — 은 재현되지 않았고 원인도 모른다.
다시 나면 이 배치로 잰다.

## 배치

```
브라우저 → :3000 TCP 중계(quiet, fe.log) → :3001 next start(PROXY_TRACE_LOG=route.log) → :8100 TCP 중계(be.log) → :8000 백엔드
```

- `route.log` — 중계(`src/app/api/backend/[...path]/route.ts`)의 요청별 단계: `start` · `fetch` · `headers <상태>` ·
  `chunk1 <바이트>`(Next 가 첫 조각을 **실제로 읽음** — 미리 당겨 읽지 않는다) · `end` · `cancel` · `body-error` ·
  `fetch-error` · `client-gone 499` · `nobody`, 그리고 `PROXY_TRACE_STUCK_MS`(기본 10초) 넘게 열린 요청에 한 번 `STUCK stage=<마지막 단계>`.
  **`PROXY_TRACE_LOG` 를 두지 않으면(기본) 아무것도 쓰지 않고 본문도 감싸지 않는다.**
- `fe.log` · `be.log` — `relay.mjs` 의 연결별 요청 줄·상태 줄·닫힘 시각(본문 내용은 적지 않는다). 닫힘을 그대로 옮겨 연결 유지 동작을 바꾸지 않는다.

## 쓰는 법 (frontend 폴더에서)

```bash
# 백엔드를 :8000 에 띄우고, 프론트를 빌드해 둔다(npx next build). :3000·:3001·:8100 은 비어 있어야 한다.
scripts/proxy-probe/run.sh start /tmp/probe        # 띄움 — 브라우저·시험은 평소처럼 http://localhost:3000
npx playwright test                                # (예) 전체 E2E — 시험은 :3000 을 그대로 쓴다
node scripts/proxy-probe/classify.mjs /tmp/probe   # 남은 요청을 가른다(--json 이면 JSON)
scripts/proxy-probe/run.sh stop /tmp/probe         # 이 폴더로 띄운 것만 끈다
```

## 읽는 법

`classify.mjs` 는 STUCK 요청마다 브라우저 쪽 연결이 **멈춘 자리(STUCK 바로 앞 단계의 시각)보다 먼저** 닫혔는지 본다.

| 분류 | 뜻 | 다음에 볼 것 |
|---|---|---|
| `orphan` | 브라우저가 먼저 떠났다 — 아무도 기다리지 않음 | 고친 뒤로는 `client-gone 499` 로 바로 끝나야 한다 |
| `still-connected` | 브라우저가 기다리는데 멈췄다 — **원래 증상 후보** | 아래 표로 층을 가른다 |
| `unmatched` | 브라우저 쪽 요청 줄을 못 찾음(시작 ±50ms) | fe.log 를 직접 본다 |

`still-connected` 의 멈춘 단계로 층을 가른다:

| 멈춘 단계 | be.log(백엔드 쪽) | 붙잡은 층 |
|---|---|---|
| `fetch` | 백엔드가 `HTTP/1.1 200` 을 보냄 | Next 의 HTTP 클라이언트(undici)가 머리를 못 받음 |
| `fetch` | 답이 없음 | 백엔드가 머리를 보내지 않음(백엔드 기록은 머리 준비 때 쓰인다 — 본문 전이다) |
| `headers` | 본문을 다 보냄 | Next 가 본문을 읽지 않음 |
| `chunk1` 이후 · `end` | — | Next → 브라우저(fe.log 에 상태 줄이 있는지) |

시험 `e2e/proxy-trace.spec.ts` 가 단계 기록·중계·분류를 건다.
