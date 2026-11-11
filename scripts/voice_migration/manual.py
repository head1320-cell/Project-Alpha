"""변환기 뒤에 손으로 고치는 것 — 다시 적용할 수 있게 스크립트로 둔다."""
import pathlib, re, sys
R = pathlib.Path(__file__).resolve().parents[2]
bad = []
def sub(path, old, new, count=1):
    p = R / path; s = p.read_text()
    if new in s and old not in s: return
    if s.count(old) != count: bad.append((path, old[:50], s.count(old))); return
    p.write_text(s.replace(old, new))
# 랜딩 문체 검사 — 방향을 뒤집는다
sub("frontend/e2e/landing.spec.ts", '''  expect(text.match(/[가-힣](습니다|합니다|입니다)[.\\s]/g) ?? [], "해요체로 쓴다").toEqual([]);''',
    '''  expect(text.match(/[가-힣](어요|아요|에요|예요|세요|해요|돼요)(?![가-힣])/g) ?? [], "합니다체로 쓴다(ADR 005)").toEqual([]);''')
sub("frontend/e2e/landing.spec.ts", "em-dash 0 · 합니다체 0 · 영어 대문자 소제목 0", "em-dash 0 · 해요체 0 · 영어 대문자 소제목 0")
sub("frontend/e2e/canvas-workspace.spec.ts", 'not.toContainText("위험을 얼마나 피할까요")', 'not.toContainText("위험 회피 수준")')
sub("tests/test_optimizer_delta_honest.py", 'assert "위험을 얼마나 피할까요" not in str(ui)', 'assert "위험 회피 수준" not in str(ui)')
# AI 말투 지시
p = R / "src/services/canvas_assist/prompts.py"; s = p.read_text()
if "해요체" in s:
    s = s.replace("해요체 1~4문장으로, 금융 용어는 쉬운 말로 풀어 답한다.", "합니다체 1~4문장으로, 금융 용어는 처음 나올 때 괄호로 뜻을 붙여 답한다.")
    p.write_text(s.replace("해요체", "합니다체"))
sub("src/api/allocation_graph_explain.py", '{"title": 해요체 한 줄,', '{"title": 합니다체 한 줄,')
# 래칫 — 목록을 비운다
p = R / "tests/test_frontend_voice.py"; s = p.read_text()
a = s.index("PENDING: tuple[str, ...] = (")
if not s[a:].startswith("PENDING: tuple[str, ...] = ()"):
    b = s.index(")\n", a) + 2
    p.write_text(s[:a] + "PENDING: tuple[str, ...] = ()        # 2026-11-11 변환기로 전 폴더를 한 번에 옮겨 비었다(HISTORY)\n" + s[b:])
sub("tests/test_frontend_claim_words.py", '이 실행은 "검증됨" 이 되지 않아요', '이 실행은 "검증됨" 이 되지 않습니다', 2)
# "요로 끝난다" 단언 → 합니다체
for f in ("w1", "w2", "w3", "w4"):
    sub(f"tests/test_allocation_graph_{f}.py", 'assert r["explain"]["title"].endswith("요"), (nid, r["explain"]["title"])',
        'assert r["explain"]["title"].endswith("다"), (nid, r["explain"]["title"])')
sub("tests/test_allocation_graph_w5.py", 'assert r["explain"]["title"].endswith("요"), r["explain"]["title"]', 'assert r["explain"]["title"].endswith("다"), r["explain"]["title"]')
sub("tests/test_allocation_graph_w5_strategy.py", 'assert m["explain"]["title"].endswith("요")', 'assert m["explain"]["title"].endswith("다")')
sub("tests/test_allocation_graph_explain.py", 'assert t.endswith("요") or t.endswith("요."), (nid, t)', 'assert t.endswith("다") or t.endswith("다."), (nid, t)')
sub("tests/test_graph_port_contract.py", 'assert role.endswith(("요.", "요")) and len(role) <= 80, (kind, port, role)', 'assert role.endswith(("다.", "다")) and len(role) <= 80, (kind, port, role)')
# 낱말 조각 단언
sub("tests/test_deflated_sharpe.py", "'2 보다 작아'", "'2 보다 작'") if "'2 보다 작아'" in (R / "tests/test_deflated_sharpe.py").read_text() else sub("tests/test_deflated_sharpe.py", '"2 보다 작아"', '"2 보다 작"')
sub("tests/test_account_balance_route.py", 'assert "닿지" in body["reason"]', 'assert "연결 실패" in body["reason"]')
sub("tests/test_broker_account_routes.py", 'assert "닿지" in body["reason"]', 'assert "연결 실패" in body["reason"]')
sub("tests/test_allocation_graph_bl3w1.py", '(None, ("골라",)),', '(None, ("선택",)),')
sub("tests/test_broker_account_routes.py", 'assert "합성" in body["reason"] and "N/A" in body["reason"]', 'assert "합성" in body["reason"] and "미상" in body["reason"]')
sub("tests/test_allocation_graph_explain.py", 'assert "합성" not in unknown and "N/A" in unknown', 'assert "합성" not in unknown and "미상" in unknown')
sub("tests/test_workflow_gates.py", '"unknown" and "N/A" in _gate(db, "data")', '"unknown" and "미상" in _gate(db, "data")')
sub("tests/test_p1_constraints_report.py", 'assert all("읽지 못" in u["text"]', 'assert all("읽기 실패" in u["text"]')
# 이제 허용하는 약어(용어집 §5)를 금지 목록에서 뺀다
sub("frontend/e2e/insights.spec.ts", "const BANNED_B = /\\b(Z-Score|M-Score|QoE|", "const BANNED_B = /\\b(")
sub("frontend/e2e/macro-cards.spec.ts", "|lag|12M|MC|CAGR|MDD|ANTHROPIC_API_KEY|Claude)", "|lag|12M|MC|ANTHROPIC_API_KEY|Claude)")
sub("frontend/e2e/canvas-perf-grammar.spec.ts", """  // 영어 약어 라벨은 없다 — 한글로.
  await expect(kv).not.toContainText("CAGR");
  await expect(kv).not.toContainText("MDD");""", """  // 약어는 용어집 §5 의 것만 쓰고, 국문을 괄호로 붙인다(ADR 005).
  await expect(kv).toContainText("MDD(최대낙폭)");""")
# 표시 낱말이 "연습용" → "합성 데이터"로 바뀌었다. "합성"만 보면 원래 있던 "…합성일 수 있습니다"(가능성 — 표시가 아니다)까지 걸린다.
sub("tests/test_graph_practice_kind.py", 'and len(node.args) >= 2 and "합성" in _text_of(node.args[1], consts):',
    'and len(node.args) >= 2 and "합성 데이터" in _text_of(node.args[1], consts):')
print("안 맞은 것:", bad)
