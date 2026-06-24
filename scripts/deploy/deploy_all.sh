#!/bin/bash
# Unified deployment script - Deploy all services
# Usage: ./deploy_all.sh [service_name]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "🚀 TradingPlatform Unified Deployment Script"
echo "📁 Project root: $PROJECT_ROOT"

# Check prerequisites
echo "🔍 Checking prerequisites..."

# 1. Check k3s status
if ! kubectl cluster-info &>/dev/null; then
    echo "❌ k3s is not running, please start Rancher Desktop first"
    exit 1
fi
echo "✅ k3s is running normally"

# 2. Check Docker status
if ! docker info &>/dev/null; then
    echo "❌ Docker is not running"
    exit 1
fi
echo "✅ Docker is running normally"

# 3. Check proxy settings (Rancher Desktop)
echo "⚠️  IMPORTANT: Ensure Rancher Desktop proxy is disabled"
echo "   Check: Rancher Desktop GUI → Settings → Proxy → Disable"

# Deploy services
if [ -n "$1" ]; then
    # Deploy specific service
    echo "🎯 Deploying service: $1"
    case "$1" in
        execution-service|execution)
            bash "$SCRIPT_DIR/execution_service.sh"
            ;;
        strategy-engine|strategy)
            bash "$SCRIPT_DIR/strategy_engine.sh"
            ;;
        *)
            echo "❌ Unknown service: $1"
            echo "   Available services: execution-service, strategy-engine"
            exit 1
            ;;
    esac
else
    # Deploy all services
    echo "🎯 Deploying all services..."

    echo "1/2 Deploying Execution.Service..."
    bash "$SCRIPT_DIR/execution_service.sh"

    echo "2/2 Deploying strategy_engine..."
    bash "$SCRIPT_DIR/strategy_engine.sh"
fi

echo "🎉 All services deployed successfully!"
echo ""
echo "📋 Check deployment status:"
kubectl get pods -n trading-platform
echo ""
echo "📋 Check service status:"
kubectl get svc -n trading-platform
