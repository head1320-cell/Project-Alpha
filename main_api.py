"""FICC Risk Management Platform — FastAPI 진입점 (Facade).

이 파일은 앱을 조립하지 않는다. 조립은 `src/app_factory.create_app()`가 하고,
라우트는 전부 `src/api/*_routes.py`에 있다. 여기 남은 유일한 이유는
`uvicorn main_api:app` 계약(Dockerfile.backend · docker-compose ·
playwright.config.ts · Makefile)을 그대로 유지하기 위해서다.

찾는 게 있다면:
  · 라우트          → src/api/<도메인>_routes.py
  · 요청/응답 모델   → src/api/legacy_schemas.py
  · 기동 시퀀스      → src/startup/lifecycle.py
  · 공유 상태        → src/state/
  · 앱 조립·라우터 등록 → src/app_factory.py
"""

from src.app_factory import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
