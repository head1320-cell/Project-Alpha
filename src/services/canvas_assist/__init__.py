"""캔버스 AI 도우미(AI0~) — Claude 에게 ★근거 묶음만★ 주고, 답은 서버가 검사한 뒤에만 화면에 낸다.

스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §AI0 ·
경로 `src/api/canvas_assist_routes.py`(로그인).

- `ground`  — 근거 묶음(카탈로그 · 그래프 구조 · 절차 · 오류)과 그 속의 숫자.
- `prompts` — 시스템 글 · 사용자 글 · 출력 스키마(설정값 칸 없음).
- `check`   — 출력 검사(카탈로그 · 연결 · 근거 밖 숫자 · 금지 표현 · 설정값 · 3개 한도). 탈락은 사유와 함께.
- `limiter` — 사용자별 시간당 한도(프로세스 안 — `--workers 1` 전제).
- `service` — 위를 잇는다. 키가 없으면 ★AI 글을 만들지 않는다★(`available:false` + 사유 + 규칙 대체).
"""
