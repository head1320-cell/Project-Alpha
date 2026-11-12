# 화면 문체 전환 도구 (ADR 005 · 2026-11-11)

해요체·쉬운 말을 개조식 + 합니다체·전문 용어로 옮길 때 쓴 변환기다. ★한 번 쓰고 버리는 도구가 아니라 기록이다★ —
어떤 규칙으로 무엇을 바꿨는지가 여기 남는다. 용어집은 `docs/specs/2026-11-11-ui-terminology.md`.

| 파일 | 무엇 |
|---|---|
| `conv.py` | 변환기. 주석 밖 글자만 고친다(.ts/.tsx 는 `//`·`/* */`, .py 는 `#`). 같은 규칙을 화면 소스·E2E·서버 문자열·pytest 에 함께 건다. |
| `rules.py` | ① 말끝(해요체 → 합니다체 — 한글 자모 규칙 + 불규칙 표) ② 상태 문구(~하는 중이에요 → ~ 중 · ~지 못했어요 → ~ 실패) ③ 의문형 제목·설정 질문 → 명사형 |
| `vocab.py` | 용어 치환 ① — 성과 지표 · 공용 상태 · 단추 · 기업 분석 · 합성 데이터(연습용) |
| `manual.py` | 변환기로 안 되는 손 고침(문체를 재던 시험의 방향 · AI 말투 지시 · 낱말 조각 단언). 여러 번 돌려도 같다. |
| `vocab2.py` ~ `vocab6.py` | 용어 치환 ②~⑥ — 글자째 쌍(`ENDINGS = False`). ⑥(`vocab6.py`)은 남은 쉬운 풀이를 전 화면·서버 문장에서 전문 용어로(용어집 §3.9). |
| `efix.py` | E2E 줄 보고서의 Expected/Received 를 읽어, 규칙 사슬(①~⑥)의 변형 가운데 실제 화면 글에 든 것으로 단언을 맞춘다. |
| `inventory.py` | ★읽기 전용★ 화면 문자열 목록 — 남은 쉬운 표현을 찾고, 치환 뒤 어긋난 곳을 긴 실행(pytest 20분 · E2E 60분) 전에 싸게 찾는다. |

```bash
python scripts/voice_migration/conv.py table frontend/src          # 어절 → 바뀐 꼴 표(검토)
python scripts/voice_migration/conv.py left frontend/src           # 남은 해요체 줄
python scripts/voice_migration/conv.py apply frontend/src frontend/e2e src tests
RULES=vocab.py python scripts/voice_migration/conv.py apply frontend/src frontend/e2e src tests
python scripts/voice_migration/manual.py
python scripts/voice_migration/inventory.py count                      # 영역별·표지 낱말별 개수
python scripts/voice_migration/inventory.py list front-other 볼 수     # 그 영역에서 표지 낱말이 든 화면 문자열(파일:줄)
python scripts/voice_migration/inventory.py remnants vocab6.py         # 따옴표 쌍의 옛 이름이 JSX 글자·정규식에 남은 곳
python scripts/voice_migration/inventory.py asserts vocab6.py          # pytest·E2E 가 옛 조각을 아직 단언하는 곳
```

- 건드리지 않는 파일: `tests/test_frontend_voice.py` · `frontend/e2e/voice-audit.spec.ts`(검사기가 해요체 예문을 품는다) ·
  `src/engine/constrained_opt.py`(파일 해시 골든 — CLAUDE.md §3 의 별도 승인 사항).
- 사용자가 치는 말(AI 에게 묻는 예문 · 시험의 질문)은 바꾸지 않는다 — 변환기가 의문형(~나요·~까요)을 모르는 꼴로 남긴다.
- 치환 쌍은 다시 돌려도 같아야 한다(새 글자가 옛 글자를 품으면 안 된다 — "충격 비용 합" → "시장충격 비용 합계"가 그랬다. 따옴표째 적어 막았다).
- `inventory.py` 의 영역: `canvas-server` · `canvas-front` · `front-other` · `server-other` · `all`. `.py` 는 docstring 이 아닌 문자열 상수(ast),
  `.ts/.tsx` 는 주석을 걷은 줄을 본다. ★ast 는 이어 붙인 문자열 리터럴을 한 덩어리로 보인다★ — 쌍의 키는 소스의 리터럴 한 조각에 맞춰 적는다.
- ★파이썬은 docstring 도 글자로 본다★(변환기는 `#` 주석만 뺀다) — 한다체 docstring 을 건드리지 않으려면 낱말 하나짜리 전역 쌍(`잰 ` → `측정한 `)이 아니라
  합니다체 꼴의 조각(`재지 못했습니다` → `측정하지 못했습니다`)이나 문장째 쌍으로 적는다(⑥c).
- `asserts` 는 한글 다섯 글자 이상 조각만 본다 — 도우미 호출(`align(page, "…")`)·치환 변수가 낀 문장은 놓친다. 마지막 판정은 전체 pytest·E2E 다.
