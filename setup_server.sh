#!/bin/bash
# ============================================================
# FICC Quant Platform — GCP 서버 전체 배포 스크립트
# Architecture: FastAPI(8000) + Next.js(3000) + PostgreSQL
# ============================================================

set -euo pipefail

GITHUB_REPO="${REPO_URL:-https://github.com/YOUR_USERNAME/ficc-platform.git}"
PROJECT_DIR="$HOME/ficc-platform"

echo "================================================="
echo "  FICC Quant Platform — Full Setup"
echo "  FastAPI :8000 + Next.js :3000"
echo "================================================="

# ─── STEP 1: 시스템 업데이트 ──────────────────────────────────
echo ""
echo "[STEP 1/6] 시스템 패키지 업데이트..."
sudo apt-get update -qq
sudo apt-get install -y -qq git curl wget

# ─── STEP 2: Docker 설치 ─────────────────────────────────────
echo ""
echo "[STEP 2/6] Docker 설치..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    rm get-docker.sh
    echo "Docker 설치 완료."
else
    echo "Docker 이미 설치됨: $(docker --version)"
fi

if ! docker compose version &> /dev/null 2>&1; then
    sudo apt-get install -y -qq docker-compose-plugin
fi
echo "Docker Compose: $(docker compose version)"

# ─── STEP 3: GitHub에서 코드 가져오기 ─────────────────────────
echo ""
echo "[STEP 3/6] GitHub에서 코드 Clone..."
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "이미 clone됨. 최신 코드 pull..."
    cd "$PROJECT_DIR"
    git pull origin main
else
    git clone "$GITHUB_REPO" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# ─── STEP 4: 프로젝트 구조 확인 ──────────────────────────────
echo ""
echo "[STEP 4/6] 프로젝트 구조 확인..."

if [ ! -f "main_api.py" ]; then
    echo "❌ ERROR: main_api.py가 없습니다!"
    echo "  현재 위치: $(pwd)"
    find . -name "main_api.py" -maxdepth 3 2>/dev/null
    exit 1
fi

if [ ! -d "frontend" ]; then
    echo "❌ ERROR: frontend/ 디렉토리가 없습니다!"
    echo "  Next.js 프론트엔드가 frontend/ 폴더에 있어야 합니다."
    exit 1
fi

# __init__.py 확인
for dir in src src/models src/api src/migrations; do
    if [ -d "$dir" ] && [ ! -f "$dir/__init__.py" ]; then
        touch "$dir/__init__.py"
        echo "  ⚠️  $dir/__init__.py 생성"
    fi
done

echo "  핵심 파일 확인:"
for f in main_api.py Dockerfile.backend Dockerfile.frontend docker-compose.yml requirements.txt frontend/package.json; do
    if [ -f "$f" ]; then
        echo "    ✓ $f"
    else
        echo "    ❌ $f 없음!"
    fi
done

# ─── STEP 5: 환경변수 설정 ────────────────────────────────────
echo ""
echo "[STEP 5/6] 환경변수 (.env) 설정..."

EXTERNAL_IP=$(curl -s http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip -H "Metadata-Flavor: Google" 2>/dev/null || hostname -I | awk '{print $1}')

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "  .env.example → .env 복사 완료"
    else
        cat > .env << ENVEOF
PG_HOST=db
PG_PORT=5432
PG_USER=ficc_user
PG_PASSWORD=ficc_password
PG_DATABASE=ficc_risk
KIS_MODE=MOCK
KIS_MOCK_APP_KEY=
KIS_MOCK_APP_SECRET=
KIS_ACCOUNT_NO=
NEXT_PUBLIC_API_URL=http://${EXTERNAL_IP}:8000
ENVEOF
        echo "  기본 .env 파일 생성 완료"
    fi
fi

# NEXT_PUBLIC_API_URL 자동 추가
if ! grep -q "NEXT_PUBLIC_API_URL" ".env"; then
    echo "NEXT_PUBLIC_API_URL=http://${EXTERNAL_IP}:8000" >> .env
    echo "  NEXT_PUBLIC_API_URL 추가됨"
fi

echo "  ⚠️  KIS API 키를 입력하려면: nano .env"

# ─── STEP 6: Docker 빌드 + 실행 ──────────────────────────────
echo ""
echo "[STEP 6/6] Docker 컨테이너 빌드 + 실행..."

docker compose down --remove-orphans 2>/dev/null || true
docker compose up --build -d

echo ""
echo "컨테이너 시작 대기 중 (30초)..."
sleep 30

# ─── 상태 확인 ────────────────────────────────────────────────
echo ""
echo "================================================="
echo "  컨테이너 상태"
echo "================================================="
docker compose ps

echo ""
docker compose logs backend --tail=10
echo ""
docker compose logs frontend --tail=5

# ─── 접속 정보 ────────────────────────────────────────────────
echo ""
echo "================================================="
echo "  ✅ 배포 완료!"
echo "================================================="
echo ""
echo "  🌐 프론트엔드  →  http://${EXTERNAL_IP}:3000"
echo "  🔌 API 문서    →  http://${EXTERNAL_IP}:8000/docs"
echo "  ❤️  헬스체크    →  http://${EXTERNAL_IP}:8000/health"
echo ""
echo "  ─── 유용한 명령어 ───"
echo "  docker compose logs -f            # 실시간 로그"
echo "  docker compose logs backend -f    # 백엔드만"
echo "  docker compose logs frontend -f   # 프론트엔드만"
echo "  docker compose restart            # 재시작"
echo "  docker compose down               # 종료"
echo "  docker compose up --build -d      # 재빌드"
echo "================================================="
