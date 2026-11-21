# README 그림 다시 찍기

저장소 첫 화면 `README.md` 의 그림(`docs/images/readme/*.png`)을 지금 앱으로 다시 찍는다. CI·E2E 에는 넣지 않는다(화면이 바뀌면 이 스크립트도 가끔 고쳐야 한다).

## 쓰는 법 (frontend 폴더에서)

```bash
npx next build                                        # 지금 코드로 빌드
node scripts/readme-shots/shoot.mjs                   # 전부
node scripts/readme-shots/shoot.mjs --only canvas,home   # 일부만(장면 이름은 shoot.mjs 의 SCENES)
```

- 제 포트 `SHOTS_WEB_PORT`(기본 3900) · `SHOTS_API_PORT`(기본 8900)가 비어 있어야 한다. 쓰고 있으면 시작하지 않는다(다른 프로세스는 끄지 않는다).
- 임시 폴더에 새 SQLite 를 두고 백엔드(`KIS_USE_MOCK=1` · 연습용 데이터)와 프론트(`next start`)를 제가 띄우며, 끝나면(실패해도) 제가 띄운 것만 끈다. 기록은 출력 첫 줄의 임시 폴더에 있다.
- 뷰포트 1440×900 · 배율 1 · 라이트 · 감속 모션.

## 화면 속 값

모두 지어낸 연습용이다: 고객 셋(개인 정보 없는 별칭) · 내 계좌의 모의 계좌(지어낸 자격 · 이 실행에서만 쓰는 암호화 키로 새 DB 에만 둔다) ·
캔버스 기본 사슬 계산 · 백테스트는 기본 설정으로 실제로 돌린 결과. 새 DB 에는 운영자의 첫 준비(`POST /api/v1/live/init-schema`)를 한 번 한다.

## 규칙 둘

1. **증권사 상표가 그림에 보이지 않는다**(2026-11-07 사용자 요청). 찍기 직전 화면 글자에서 `한국투자증권`·`KIS` 를 '증권사'로 가리고, 그래도 남아 있으면 그 그림을 쓰지 않고 실패한다.
   앱은 바꾸지 않는다 — 그림에서만 가린다.
2. **AI 그림은 실제 Claude 응답만**. AI 장면(`ai-suggest` · `ai-draft` · `ai-ask` · `ai-story`)은 앱이 답을 보일 때만 쓴다. "AI 답을 보여 줄 수 없어요" 가 나오면
   AI 그림을 하나도 쓰지 않고 그 사유와 함께 0 아닌 값으로 끝난다(AI 아닌 그림은 그 전에 쓴다). 키는 `ANTHROPIC_API_KEY` 또는, 클라우드 세션이면 환경의 네트워크 비밀(호스트
   `api.anthropic.com` · 머리글 `x-api-key`)로 준다 — 이때 백엔드에는 자리 표시 값만 들어가고 실제 키는 프록시가 넣는다.

AI 그림을 처음 넣을 때는 README 의 'AI 설계 보조 (Claude)' 절에 네 그림을 2×2 표로 더한다(캡션: "AI 답은 연습용 데이터 위에서 받은 실제 Claude 응답입니다").
