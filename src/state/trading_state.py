"""자동매매 토글 상태 — 프로세스 로컬 공유 상태.

`/toggle-auto-trading`(주문 라우터)이 쓰고 `/ws/live-risk`(시스템 라우터의 웹소켓)가
읽는다. 두 라우터가 서로 다른 파일로 갈라졌으므로 공유 모듈로 승격했다.
dict를 통째로 재할당하지 말 것 — 제자리 변경(mutate)해야 양쪽이 같은 객체를 본다.
"""

trading_config: dict = {"auto_trading": False, "risk_limit": 0.02, "max_position": 1000000}
