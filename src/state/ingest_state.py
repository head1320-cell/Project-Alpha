"""적재(ingest) 진행 상태 — 프로세스 로컬 공유 상태.

main_api.py에 모듈 전역으로 있던 것을 분리했다. 데이터 라우터(진행률 갱신)와
기동 시 백그라운드 데몬(같은 _ingest_run 경로를 사용)이 함께 읽고 쓰므로,
어느 한쪽 라우터 파일에 두면 순환 import가 된다.

주의: 이 dict들은 데몬 스레드에서 동기화 없이 변경된다(기존 동작 그대로).
      워커를 늘리려면 이 상태를 먼저 Redis/DB로 옮겨야 한다(CLAUDE.md 참고).
"""

# ★목록은 한 곳에만 있다★ 예전에는 이 튜플과 `data_routes._ingest_run` 의 if 분기,
# 그리고 프런트 `DbStatusPanel` 의 하드코딩이 **세 벌**로 갈라져 있었다. 그래서
# 대상을 추가하려면 세 곳을 고쳐야 했고, 실제로 `macro` 가 빠져 있었다.
# 이제 `data/ingest_registry.py` 가 단일 출처이고 이것은 파생값이다(이름은 유지 —
# 라우터·데몬·테스트가 이 상수를 쓴다).
from src.data.ingest_registry import triggerable_keys

INGEST_TARGETS = triggerable_keys()
INGEST_RUNNING: dict = {k: False for k in INGEST_TARGETS}
INGEST_STATUS: dict = {}
