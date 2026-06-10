#!/bin/bash
# ============================================================
# FICC Quant Platform — GCP VM 배포 스크립트
# Architecture: FastAPI(8000) + Next.js(3000) + PostgreSQL
# ============================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
REPO_URL="${REPO_URL:-https://github.com/YOUR_USERNAME/ficc-platform.git}"
INSTALL_DIR="/opt/ficc-platform"

echo "================================================="
echo "  FICC Quant Platform — GCP Deployment"
echo "  FastAPI :8000 + Next.js :3000"
echo "================================================="

# ─── 1. System update ─────────────────────────────────────────
echo "[1/7] Updating system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq git curl wget unzip ca-certificates gnupg lsb-release

# ─── 2. Install Docker ────────────────────────────────────────
echo "[2/7] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    rm get-docker.sh
fi

if ! docker compose version &> /dev/null 2>&1; then
    sudo apt-get install -y docker-compose-plugin
fi

# ─── 3. Clone repository ──────────────────────────────────────
echo "[3/7] Cloning repository..."
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER":"$USER" "$INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR" && git pull origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ─── 4. Environment configuration ─────────────────────────────
echo "[4/7] Setting up .env..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env" 2>/dev/null || true
    echo "⚠️  Edit $INSTALL_DIR/.env with your KIS API keys!"
fi

# ─── 5. Set NEXT_PUBLIC_API_URL for frontend build ─────────────
EXTERNAL_IP=$(curl -s http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip -H "Metadata-Flavor: Google" 2>/dev/null || hostname -I | awk '{print $1}')

# .env에 NEXT_PUBLIC_API_URL이 없으면 추가
if ! grep -q "NEXT_PUBLIC_API_URL" "$INSTALL_DIR/.env"; then
    echo "NEXT_PUBLIC_API_URL=http://${EXTERNAL_IP}:8000" >> "$INSTALL_DIR/.env"
    echo "  NEXT_PUBLIC_API_URL=http://${EXTERNAL_IP}:8000 추가됨"
fi

# ─── 6. Build and start containers ────────────────────────────
echo "[6/7] Building and starting Docker containers..."
cd "$INSTALL_DIR"
docker compose down --remove-orphans 2>/dev/null || true
docker compose up --build -d

echo "Waiting for services to start (30s)..."
sleep 30

# ─── 7. Configure GCP Firewall (3000 + 8000) ─────────────────
echo "[7/7] Configuring GCP firewall..."
gcloud compute firewall-rules create allow-ficc-platform \
    --project="$PROJECT_ID" \
    --allow=tcp:8000,tcp:3000 \
    --source-ranges=0.0.0.0/0 \
    --description="FICC Platform — API(8000) + Frontend(3000)" \
    --quiet 2>/dev/null || echo "Firewall rule already exists."

# ─── Done ─────────────────────────────────────────────────────
echo ""
echo "================================================="
echo "  ✅ Deployment Complete!"
echo "================================================="
echo ""
echo "  🌐 Frontend  →  http://${EXTERNAL_IP}:3000"
echo "  🔌 API Docs  →  http://${EXTERNAL_IP}:8000/docs"
echo "  ❤️  Health    →  http://${EXTERNAL_IP}:8000/health"
echo ""
echo "  Commands:"
echo "    docker compose logs -f          # live logs"
echo "    docker compose restart          # restart"
echo "    docker compose down             # stop"
echo "================================================="
