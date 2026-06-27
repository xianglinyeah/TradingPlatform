#!/bin/bash
# Offline deployment dependency preparation script
# Download all dependencies locally to avoid k8s container network requirements

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "🔄 Preparing offline deployment dependencies..."
echo "📁 Project root: $PROJECT_ROOT"

# 1. C# dependency download (NuGet package cache)
echo "📦 Preparing C# dependencies..."
cd "$PROJECT_ROOT/src/execution-service"

echo "  🔨 Cleaning old build results..."
rm -rf bin/ obj/

echo "  📥 Restoring NuGet packages to local cache..."
dotnet restore --packages packages

echo "  🔨 Building and publishing (including all dependencies)..."
dotnet publish -c Release -o bin/Release/net8.0/publish --no-restore

echo "  ✅ C# dependencies prepared"
echo "     Publish directory size: $(du -sh bin/Release/net8.0/publish | cut -f1)"

# 2. Python dependency download (pip wheel files)
echo ""
echo "📦 Preparing Python dependencies..."
cd "$PROJECT_ROOT/src/strategy-engine"

# Create virtual environment (if not exists)
if [ ! -d "venv" ]; then
    echo "  🔨 Creating Python virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
echo "  🔨 Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Upgrade pip
echo "  🔄 Upgrading pip..."
pip install --upgrade pip wheel

# Clean old dependencies
echo "  🧹 Cleaning old dependency directory..."
rm -rf local-packages
mkdir -p local-packages

# Download all dependencies as wheel files
echo "  📥 Downloading pip dependencies locally..."
if [ -f "requirements.txt" ]; then
    pip download -r requirements.txt -d local-packages
    echo "  ✅ Download completed, package count: $(ls -1 local-packages/*.whl 2>/dev/null | wc -l)"
    echo "     Dependency directory size: $(du -sh local-packages | cut -f1)"
else
    echo "  ⚠️  requirements.txt not found, skipping Python dependency download"
fi

# Verify key dependencies
echo ""
echo "🔍 Verifying key Python dependencies..."
for pkg in grpcio protobuf pandas numpy; do
    if ls local-packages/${pkg}*.whl 1> /dev/null 2>&1; then
        echo "  ✅ $pkg: $(ls local-packages/${pkg}*.whl | head -1 | xargs basename)"
    else
        echo "  ❌ $pkg: Not found"
    fi
done

echo ""
echo "🎉 Offline dependency preparation completed!"
echo ""
echo "📊 Dependency summary:"
echo "   C# publish directory: $PROJECT_ROOT/src/execution-service/bin/Release/net8.0/publish"
echo "   Python dependencies: $PROJECT_ROOT/src/strategy-engine/local-packages"
echo ""
echo "🚀 Next step: Run deployment script"
echo "   cd $SCRIPT_DIR"
echo "   ./deploy_all.sh"
