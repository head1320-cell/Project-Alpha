"""테스트 세션 공통 설정 — ★한 줄만 둔다★

## 주기 데몬을 끈다 (BE, 2026-09-24)

`with TestClient(create_app())` 가 기동 이벤트를 부를 때마다 `run_startup` 이
끝나지 않는 주기 데몬(고아 스윕·리스크 감시)을 띄웠고, 15개 파일만 돌려도 436개가
살아 있었다. 그 데몬들이 모듈 전역 엔진을 바꾼 테스트의 **단일 연결**을 다른
스레드에서 써서 SQLite 안에서 SIGSEGV 가 났다(재현 5/5, 대조군 0/3).

★명시 스위치로 끈다★ — `lifecycle` 이 pytest 를 스스로 감지하지 않는다. 끄면
`lifecycle` 이 그 사실을 로그로 말한다. 데몬 자체를 재는 테스트는 루프 함수를
직접 부르거나 이 값을 `monkeypatch` 로 바꾼다(`tests/test_lifecycle_daemons.py`).
"""
import os

os.environ.setdefault("LIFECYCLE_DAEMONS", "0")
