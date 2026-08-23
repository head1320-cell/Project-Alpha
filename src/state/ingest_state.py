"""적재(ingest) 진행 상태 — 프로세스 로컬 공유 상태.

main_api.py에 모듈 전역으로 있던 것을 분리했다. 데이터 라우터(진행률 갱신)와
기동 시 백그라운드 데몬(같은 _ingest_run 경로를 사용)이 함께 읽고 쓰므로,
어느 한쪽 라우터 파일에 두면 순환 import가 된다.

주의: 이 dict들은 데몬 스레드에서 동기화 없이 변경된다(기존 동작 그대로).
      워커를 늘리려면 이 상태를 먼저 Redis/DB로 옮겨야 한다(CLAUDE.md 참고).
"""

INGEST_TARGETS = ("index", "etf", "stocks", "factors", "financials", "flows")
INGEST_RUNNING: dict = {k: False for k in INGEST_TARGETS}
INGEST_STATUS: dict = {}
