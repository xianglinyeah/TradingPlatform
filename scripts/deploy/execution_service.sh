#!/bin/bash
# Execution.Service deployment script
# Enterprise-grade deployment flow: Build → Package → Load → Deploy

set -euo pipefail  # Exit on error, undefined vars, pipe failures

echo "🚀 Starting Execution.Service deployment..."

# 1. Enter project directory
cd "$(dirname "$0")/../.."
PROJECT_ROOT=$(pwd)
echo "📁 Project root: $PROJECT_ROOT"

# 2. Build C# project
echo "🔨 Building Execution.Service..."
cd lowfreq/dotnet/execution-service
dotnet publish -c Release -o bin/Release/net8.0/publish

# 3. Build Docker image
echo "🐳 Building Docker image..."
cd "$PROJECT_ROOT"
docker build -t docker-execution-service:latest lowfreq/dotnet/execution-service/

# 4. Export image as tar file (avoid network issues)
echo "📦 Exporting Docker image..."
docker save docker-execution-service:latest -o /tmp/execution-service.tar

# 5. Load image to k3s (Rancher Desktop)
echo "📥 Loading image to k3s..."
# If using Rancher Desktop, image is auto-shared
# For manual import, uncomment below:
# ctr image import /tmp/execution-service.tar

# 6. Verify image availability
echo "✅ Verifying image..."
docker images | grep docker-execution-service

# 7. Deploy to k8s
echo "🚀 Deploying to Kubernetes..."
kubectl rollout restart deployment/execution-service -n trading-platform

# 8. Wait for deployment completion
echo "⏳ Waiting for deployment..."
kubectl rollout status deployment/execution-service -n trading-platform --timeout=60s

# 9. Verify deployment
echo "🔍 Verifying deployment..."
kubectl get pods -n trading-platform | grep execution-service

# 10. Check logs
echo "📋 Checking logs (last 10 lines)..."
kubectl logs deployment/execution-service -n trading-platform --tail=10

echo "✅ Execution.Service deployment completed!"
