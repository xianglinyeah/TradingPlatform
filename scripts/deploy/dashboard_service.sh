#!/bin/bash
# dashboard_service offline deployment script
# Completely offline: Linux wheels (cp312 manylinux) -> Build image -> Deploy to k8s
#
# Wheels are downloaded inside a python:3.12-slim container so the host OS
# does not matter (Windows pip would otherwise pull Windows wheels).

set -euo pipefail

echo "🚀 Starting dashboard_service OFFLINE deployment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
SERVICE_DIR="$PROJECT_ROOT/src/dashboard-service"

# 1. Prepare offline dependencies (manylinux cp312 wheels)
echo "📦 Preparing offline Python dependencies (cp312 manylinux)..."
cd "$SERVICE_DIR"

rm -rf artifacts/wheels
mkdir -p artifacts/wheels

if [ ! -f "requirements.txt" ]; then
    echo "  ❌ requirements.txt not found"
    exit 1
fi

# Force manylinux cp312 wheels regardless of host OS via a container.
# PIP_INDEX_URL is set because VPN on the host does not always route
# through docker NAT; the Tsinghua mirror is reachable directly.
docker run --rm \
    -e PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    -v "$SERVICE_DIR:/work" -w /work python:3.12-slim \
    bash -c "pip install --upgrade pip wheel && \
             pip download -r requirements.txt -d artifacts/wheels \
                 --platform manylinux2014_x86_64 \
                 --python-version 312 \
                 --implementation cp \
                 --only-binary=:all:"

echo "  ✅ Wheels downloaded: $(ls -1 artifacts/wheels/*.whl 2>/dev/null | wc -l) packages"

# 2. Build Docker image (completely offline)
echo "🐳 Building offline Docker image..."
cd "$PROJECT_ROOT"
docker build -t docker-dashboard-service:latest src/dashboard-service/

# 3. Verify image
echo "✅ Verifying image..."
docker images | grep docker-dashboard-service

# 4. Deploy to k8s
echo "🚀 Deploying to Kubernetes..."
kubectl rollout restart deployment/dashboard-service -n trading-platform

# 5. Wait for deployment completion
echo "⏳ Waiting for deployment..."
kubectl rollout status deployment/dashboard-service -n trading-platform --timeout=90s

# 6. Verify deployment
echo "🔍 Verifying deployment..."
kubectl get pods -n trading-platform | grep dashboard-service

# 7. Check logs
echo "📋 Checking logs..."
kubectl logs deployment/dashboard-service -n trading-platform --tail=10

echo "✅ dashboard_service offline deployment completed!"
echo "   Container needs no network, all dependencies pre-packaged"
