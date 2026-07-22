#!/bin/bash
# strategy_engine offline deployment script
# Completely offline: Local dependencies → Build image → Deploy to k8s

set -euo pipefail

echo "🚀 Starting strategy_engine OFFLINE deployment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# 1. Prepare offline dependencies
echo "📦 Preparing offline Python dependencies..."
cd "$PROJECT_ROOT/lowfreq/python/strategy-engine"

# Clean old dependencies (cp311 wheels from the previous Python 3.11 build)
rm -rf local-packages
mkdir -p local-packages

# Download all dependencies as cp312 manylinux wheels. The host (Windows)
# would otherwise pull Windows wheels; running pip inside a
# python:3.12-slim container guarantees the right platform tag.
echo "  📥 Downloading dependencies (cp312 manylinux)..."
if [ -f "requirements.txt" ]; then
    # PIP_INDEX_URL is set because VPN on the host does not always route
    # through docker NAT; the Tsinghua mirror is reachable directly.
    docker run --rm \
        -e PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
        -v "$PWD:/work" -w /work python:3.12-slim \
        bash -c "pip install --upgrade pip wheel && \
                 pip download -r requirements.txt -d local-packages \
                     --platform manylinux2014_x86_64 \
                     --python-version 312 \
                     --implementation cp \
                     --only-binary=:all:"
    echo "  ✅ Dependencies downloaded: $(ls -1 local-packages/*.whl 2>/dev/null | wc -l) packages"
else
    echo "  ❌ requirements.txt not found"
    exit 1
fi

# 2. Build Docker image (completely offline)
echo "🐳 Building offline Docker image..."
cd "$PROJECT_ROOT"
docker build -t docker-strategy-engine:latest lowfreq/python/strategy-engine/

# 3. Verify image
echo "✅ Verifying image..."
docker images | grep docker-strategy-engine

# 4. Deploy to k8s
echo "🚀 Deploying to Kubernetes..."
kubectl rollout restart deployment/strategy-engine -n trading-platform

# 5. Wait for deployment completion
echo "⏳ Waiting for deployment..."
kubectl rollout status deployment/strategy-engine -n trading-platform --timeout=90s

# 6. Verify deployment
echo "🔍 Verifying deployment..."
kubectl get pods -n trading-platform | grep strategy-engine

# 7. Check logs
echo "📋 Checking logs..."
kubectl logs deployment/strategy-engine -n trading-platform --tail=10

echo "✅ strategy_engine offline deployment completed!"
echo "   Container needs no network, all dependencies pre-packaged"
