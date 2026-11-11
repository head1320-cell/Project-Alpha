# 화면 문체 전환 도구 (ADR 005 · 2026-11-11)

해요체·쉬운 말을 개조식 + 합니다체·전문 용어로 옮길 때 쓴 변환기다. ★한 번 쓰고 버리는 도구가 아니라 기록이다★ —
어떤 규칙으로 무엇을 바꿨는지가 여기 남는다. 용어집은 `docs/specs/2026-11-11-ui-terminology.md`.

| 파일 | 무엇 |
|---|---|
| `conv.py` | 변환기. 주석 밖 글자만 고친다(.ts/.tsx 는 `//`·`/* */`, .py 는 `#`). 같은 규칙을 화면 소스·E2E·서버 문자열·pytest 에 함께 건다. |
| `rules.py` | ① 말끝(해요체 → 합니다체 — 한글 자모 규칙 + 불규칙 표) ② 상태 문구(~하는 중이에요 → ~ 중 · ~지 못했어요 → ~ 실패) ③ 의문형 제목·설정 질문 → 명사형 |
| `vocab.py` | 용어 치환 ① — 성과 지표 · 공용 상태 · 단추 · 기업 분석 · 합성 데이터(연습용) |
| `manual.py` | 변환기로 안 되는 손 고침(문체를 재던 시험의 방향 · AI 말투 지시 · 낱말 조각 단언). 여러 번 돌려도 같다. |

```bash
python scripts/voice_migration/conv.py table frontend/src          # 어절 → 바뀐 꼴 표(검토)
python scripts/voice_migration/conv.py left frontend/src           # 남은 해요체 줄
python scripts/voice_migration/conv.py apply frontend/src frontend/e2e src tests
RULES=vocab.py python scripts/voice_migration/conv.py apply frontend/src frontend/e2e src tests
python scripts/voice_migration/manual.py
```

- 건드리지 않는 파일: `tests/test_frontend_voice.py` · `frontend/e2e/voice-audit.spec.ts`(검사기가 해요체 예문을 품는다) ·
  `src/engine/constrained_opt.py`(파일 해시 골든 — CLAUDE.md §3 의 별도 승인 사항).
- 사용자가 치는 말(AI 에게 묻는 예문 · 시험의 질문)은 바꾸지 않는다 — 변환기가 의문형(~나요·~까요)을 모르는 꼴로 남긴다.
- 치환 쌍은 다시 돌려도 같아야 한다(새 글자가 옛 글자를 품으면 안 된다 — "충격 비용 합" → "시장충격 비용 합계"가 그랬다. 따옴표째 적어 막았다).
