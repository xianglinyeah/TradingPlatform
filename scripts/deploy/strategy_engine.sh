#!/bin/bash
# strategy_engine offline deployment script
# Completely offline: Local dependencies → Build image → Deploy to k8s

set -euo pipefail

echo "🚀 Starting strategy_engine OFFLINE deployment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# 1. Prepare offline dependencies
echo "📦 Preparing offline Python dependencies..."
cd "$PROJECT_ROOT/src/strategy-engine"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "  🔨 Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Upgrade pip
pip install --upgrade pip wheel

# Clean old dependencies
rm -rf local-packages
mkdir -p local-packages

# Download all dependencies as wheel files
echo "  📥 Downloading dependencies locally..."
if [ -f "requirements.txt" ]; then
    pip download -r requirements.txt -d local-packages
    echo "  ✅ Dependencies downloaded: $(ls -1 local-packages/*.whl 2>/dev/null | wc -l) packages"
else
    echo "  ❌ requirements.txt not found"
    exit 1
fi

# 2. Build Docker image (completely offline)
echo "🐳 Building offline Docker image..."
cd "$PROJECT_ROOT"
docker build -t docker-strategy-engine:latest src/strategy-engine/

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
