# ═══════════════════════════════════════════════════════════════════════════════
# Project Alpha — 개발 명령어
#   make help 로 전체 목록 확인
# ═══════════════════════════════════════════════════════════════════════════════

.PHONY: help install lint fmt fmt-check test test-fast typecheck build verify dev clean all

help:  ## 명령어 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## 의존성 설치 (백엔드 + 프론트)
	pip install -r requirements.txt
	pip install ruff pytest
	cd frontend && npm ci

lint:  ## ruff 린트 검사
	ruff check src/ tests/ main_api.py

fmt:  ## ruff 자동 수정 + 포맷
	ruff check src/ tests/ main_api.py --fix
	ruff format src/ tests/ main_api.py

fmt-check:  ## 포맷 검사만 (CI용)
	ruff format --check src/ tests/ main_api.py

test:  ## 전체 테스트
	KIS_USE_MOCK=1 pytest tests/ -q --tb=short

test-fast:  ## 빠른 테스트만 (백테스트 제외)
	KIS_USE_MOCK=1 pytest tests/test_realdata_parsing.py tests/test_quant_models.py -q

typecheck:  ## 프론트 타입체크
	cd frontend && npx tsc --noEmit

build:  ## 프론트 프로덕션 빌드
	cd frontend && npx next build

verify:  ## 실데이터 연결 검증 (실키 필요, 서버에서)
	KIS_USE_MOCK=0 python verify_connection.py

dev:  ## 로컬 개발 서버 (백엔드 + 프론트)
	@echo "백엔드: uvicorn main_api:app --reload --port 8000"
	@echo "프론트: cd frontend && npm run dev"

clean:  ## 캐시/빌드 산출물 정리
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next

all: lint test typecheck build  ## 전체 검증 (CI와 동일)
