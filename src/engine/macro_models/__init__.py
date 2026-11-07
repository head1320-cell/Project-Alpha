"""5개 매크로 서브스튜디오 — 프론티어 계약 + 정직한 대체 엔진 (M1-M)
==============================================================================
각 스튜디오는 **두 엔진**을 선언한다.

  · **프론티어** — 요청받은 아키텍처의 모델(Neural SDE · PINN · TSFM · DeePM ·
    Agentic CLQT). 지금은 torch·cvxpylayers·트렌드 API·LLM 이 없고 표본이 60개월
    mock 이라 **`available:false` + 사유**로만 존재한다.
  · **대체** — 지금 설치된 것(statsmodels · scipy · 저장소 엔진)으로 정직하게
    계산되는 모델. 실제로 돈다.

★화면은 어느 엔진이 그 숫자를 냈는지 항상 밝힌다★ 두 엔진의 출력을 같은 자리에
같은 모양으로 넣되 `engine` 필드로 가른다. 그래야 "프론티어가 낸 값" 과 "대체가 낸
값" 을 사용자가 혼동하지 않는다 — 혼동하면 이 구조 전체가 무의미해진다.
"""

from src.engine.macro_models.base import STUDIOS, describe_all, run_studio

__all__ = ["STUDIOS", "describe_all", "run_studio"]
